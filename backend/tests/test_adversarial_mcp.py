"""MCP-коннектор (POST /mcp) и OAuth — по отчёту /root/review/backend_mcp_sched.md.

Вызовы идут через HTTP как из Claude: JSON-RPC tools/call с Bearer-токеном. Джек — служебный API_TOKEN
(владелец), Нурлан/Аида — MCP access-токены из mcp_tokens. Тесты test_<severity>_* падают на текущем коде,
test_ok_* — регрессия того, что уже работает. Сеть не используется.
"""
import base64
import hashlib
import inspect
import json
import secrets
import threading
import urllib.parse as up

import pytest
from sqlalchemy import select

from app import models
from tests.conftest import NUR_EMAIL, AIDA_EMAIL, count, link_person, ok


# ── Вспомогательное ──────────────────────────────────────────────────────────

def rpc(client, u, method, params=None, id_=1, raw=None):
    body = raw if raw is not None else json.dumps({"jsonrpc": "2.0", "id": id_, "method": method, "params": params if params is not None else {}})
    return client.post("/mcp", content=body, headers=u.mcp_h)


def call(client, u, tool, **args):
    """tools/call → (данные, isError). Ошибка HTTP/протокола — сразу assert с текстом."""
    r = rpc(client, u, "tools/call", {"name": tool, "arguments": args})
    assert r.status_code == 200, f"/mcp tools/call {tool} → HTTP {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert "result" in body, f"tools/call {tool}: JSON-RPC error вместо результата: {body}"
    res = body["result"]
    return json.loads(res["content"][0]["text"]), bool(res.get("isError"))


def must_ok(client, u, tool, **args):
    d, err = call(client, u, tool, **args)
    assert not err, f"{tool}({args}) → ошибка: {d}"
    return d


@pytest.fixture
def shared_world(client, api, jack, nur):
    """Джек: направление «Эмба» (Нурлану — view), задача «Подписать договор» в проекте (Нурлану — edit как задача)."""
    d = must_ok(client, jack, "create_direction", name="Эмба")["direction"]
    p = must_ok(client, jack, "create_project", direction="Эмба", name="Договор основной")["project"]
    t = must_ok(client, jack, "create_task", title="Подписать договор", directions=["Эмба"], project="Договор основной")["task"]
    api.share(jack, "direction", d["id"], NUR_EMAIL, "view")
    api.share(jack, "task", t["id"], NUR_EMAIL, "edit")
    return {"dir": d, "project": p, "task": t}


# ═══════════════════════ Высоко ═══════════════════════

def test_V1_editor_cannot_add_view_only_direction(client, jack, nur, shared_world):
    """В1. Редактор задачи (edit) добавляет её в направление, открытое ему только на просмотр —
    REST (fetch_directions_for_task) вернул бы 403, MCP пропускает. Ожидается ToolError."""
    t2 = must_ok(client, jack, "create_task", title="Отдельная")["task"]
    ok(client.post("/api/shares", json={"entity_type": "task", "entity_id": t2["id"], "email": NUR_EMAIL, "permission": "edit"}, headers=jack.h), 201)
    d, err = call(client, nur, "update_task", task="Отдельная", add_directions=["Эмба"])
    assert err, f"редактор задачи привязал её к view-only направлению «Эмба»: {d}"


def test_V1_editor_cannot_remove_owner_direction(client, jack, nur, shared_world):
    """В1. Редактор задачи убирает её из направления владельца (у него на направление только view)
    и из проекта — задача исчезает с доски Джека. Ожидается: ошибка, направление и проект на месте."""
    d1, err1 = call(client, nur, "update_task", task="Подписать договор", remove_directions=["Эмба"])
    d2, err2 = call(client, nur, "update_task", task="Подписать договор", project=None)
    after = must_ok(client, jack, "get_task", task="Подписать договор")
    assert err1 and err2, f"редактор снял задачу с направления/проекта владельца: {d1} | {d2}"
    assert [x["name"] for x in after["directions"]] == ["Эмба"] and after["project"], f"задача Джека потеряла направление/проект: {after}"


def test_V1_add_tool_directions_must_be_own_or_editable(client, jack, nur, shared_world):
    """В1. add_tool(directions=[view-only направление]) вешает тул на чужое направление (REST: только свои).
    Ожидается ToolError."""
    d, err = call(client, nur, "add_tool", name="Таблица", directions=["Эмба"])
    assert err, f"тул привязан к чужому view-only направлению: {d}"


def test_V2_create_person_external_email_rejected(client, nur):
    """В2. create_person с внешней почтой + create_task(assign_to) = рассылка «вам поручено» с корпоративного
    ящика на любой адрес. Ожидается: домен проверяется по ALLOWED_EMAIL_DOMAINS (как в share_access)."""
    d, err = call(client, nur, "create_person", name="Внешний", email="victim@gmail.com")
    assert err, f"человек с внешней почтой victim@gmail.com создан: {d}"


def test_V5_internal_error_does_not_leak_sql(client, jack):
    """В5. Не-строковое description → ProgrammingError → в ответе Claude полный SQL с параметрами.
    Ожидается: ToolError о типе аргумента либо короткая ошибка без текста SQL."""
    d, err = call(client, jack, "create_task", title="descr", description=["a", "b"])
    text = json.dumps(d, ensure_ascii=False)
    assert "[SQL" not in text and "INSERT INTO" not in text and "parameters" not in text, f"в ответе утёк SQL: {text[:300]}"
    assert "внутренняя ошибка" not in text, f"сырое исключение вместо понятной ошибки аргумента: {text[:300]}"


def test_V4_batch_size_limited(client, jack):
    """В4. Батч JSON-RPC без ограничений: 2000×tools/list → 52 МБ ответа одним запросом.
    Ожидается: батч больше разумного (здесь 50) отклоняется JSON-RPC ошибкой / 4xx."""
    batch = [{"jsonrpc": "2.0", "id": i, "method": "tools/list"} for i in range(50)]
    r = client.post("/mcp", content=json.dumps(batch), headers=jack.mcp_h)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
    rejected = r.status_code >= 400 or (isinstance(body, dict) and "error" in body)
    assert rejected, f"батч из 50 запросов обработан целиком ({r.status_code}, {len(r.content)} байт)"


def test_V3_oauth_register_capped(client):
    """В3. /oauth/register без аутентификации и лимитов (200 клиентов за 1.4 с). Ожидается: после серии
    регистраций подряд — 429 (или иной отказ), а не бесконечные 201."""
    statuses = [client.post("/oauth/register", json={"client_name": "A", "redirect_uris": [f"https://x.test/{i}"]}).status_code for i in range(30)]
    assert any(s != 201 for s in statuses), f"30 регистраций подряд — все 201: {statuses}"


# ═══════════════════════ Критично (OAuth) ═══════════════════════

def _pkce():
    v = secrets.token_urlsafe(40)
    ch = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    return v, ch


def _authorize(client, redirect="https://client.test/cb"):
    """Регистрация клиента + /oauth/authorize (режим без Microsoft → редирект на /oauth/consent). Возвращает (client_id, key, verifier)."""
    reg = client.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": [redirect]}).json()
    verifier, challenge = _pkce()
    r = client.get("/oauth/authorize", params={"client_id": reg["client_id"], "redirect_uri": redirect, "response_type": "code", "state": "s1",
                                              "code_challenge": challenge, "code_challenge_method": "S256"}, follow_redirects=False)
    assert r.status_code == 302, r.text
    key = up.parse_qs(up.urlparse(r.headers["location"]).query)["k"][0]
    return reg["client_id"], key, verifier


def _consent_allow(client, key):
    r = client.post("/oauth/consent", data={"k": key, "decision": "allow", "api_token": "tok"}, follow_redirects=False)
    assert r.status_code == 302, r.text
    return up.parse_qs(up.urlparse(r.headers["location"]).query)["code"][0]


def test_K2_auth_code_single_use_under_parallel_exchange(client, db, jack, monkeypatch):
    """К2. Флаг used читается и пишется неатомарно: параллельные обмены одного кода → несколько пар токенов.
    Барьер в _verify_pkce гарантирует, что все 4 запроса прочитали код до того, как первый его пометил.
    Ожидается: ровно один 200 и одна строка mcp_tokens (атомарный UPDATE … WHERE used=false)."""
    from app.routers import mcp_oauth
    cid, key, verifier = _authorize(client)
    code = _consent_allow(client, key)
    barrier = threading.Barrier(4, timeout=5)
    orig = mcp_oauth._verify_pkce

    def synced(v, c):
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return orig(v, c)
    monkeypatch.setattr(mcp_oauth, "_verify_pkce", synced)
    results = []

    def exchange():
        results.append(client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                                                          "client_id": cid, "redirect_uri": "https://client.test/cb"}).status_code)
    threads = [threading.Thread(target=exchange) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    issued = count(db, models.McpToken, models.McpToken.client_id == cid)
    assert results.count(200) == 1 and issued == 1, f"код обменян несколько раз: статусы {results}, выдано пар токенов {issued}"


def test_K1_token_exchange_requires_client_id_and_redirect_uri(client, jack):
    """К1. /oauth/token принимает код без client_id и redirect_uri (проверка только «если передали»).
    Ожидается: без них — 400 invalid_request/invalid_grant."""
    cid, key, verifier = _authorize(client)
    code = _consent_allow(client, key)
    r = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "code_verifier": verifier})
    assert r.status_code == 400, f"обмен кода без client_id/redirect_uri прошёл ({r.status_code})"


def test_K1_consent_page_shows_redirect_host(client, jack):
    """К1. Страница согласия показывает имя клиента («Claude»), но не хост redirect_uri — фишинг одним кликом.
    Ожидается: хост redirect_uri виден на странице."""
    cid, key, _ = _authorize(client, redirect="https://evil.example/cb")
    page = client.get(f"/oauth/consent?k={key}")
    assert page.status_code == 200
    assert "evil.example" in page.text, "на странице согласия не показан адрес, куда уйдёт код (redirect_uri)"


def test_K1_consent_bound_to_initiating_browser(client, jack):
    """К1. Запрос авторизации не привязан к браузеру, начавшему /oauth/authorize (нет cookie):
    ссылку можно переслать жертве. Ожидается: согласие из другого браузера (без cookie) не выдаёт код."""
    from fastapi.testclient import TestClient
    from app.main import app
    cid, key, _ = _authorize(client)
    other = TestClient(app, base_url="https://backend.test", raise_server_exceptions=False)  # чужой браузер: без cookies
    r = other.post("/oauth/consent", data={"k": key, "decision": "allow", "api_token": "tok"}, follow_redirects=False)
    got_code = r.status_code == 302 and "code=" in r.headers.get("location", "")
    assert not got_code, "согласие принято из браузера, который не начинал авторизацию — код выдан"


@pytest.mark.parametrize("uri", ["http://localhost.evil.com/cb", "http://127.0.0.1.evil.com/cb", "https://", "https://evil.com/cb#frag"])
def test_N9_redirect_uri_validation(client, uri):
    """Н9. _valid_redirect_uri — префиксная проверка: принимает localhost.evil.com, пустой хост, URI с #fragment.
    Ожидается 400."""
    r = client.post("/oauth/register", json={"client_name": "x", "redirect_uris": [uri]})
    assert r.status_code == 400, f"redirect_uri {uri!r} принят ({r.status_code})"


def test_N9_code_challenge_format_checked(client):
    """Н9. code_challenge='abc' (не 43 символа base64url) принимается. Ожидается редирект с error=invalid_request."""
    reg = client.post("/oauth/register", json={"client_name": "x", "redirect_uris": ["https://client.test/cb"]}).json()
    r = client.get("/oauth/authorize", params={"client_id": reg["client_id"], "redirect_uri": "https://client.test/cb", "response_type": "code",
                                              "code_challenge": "abc", "code_challenge_method": "S256"}, follow_redirects=False)
    assert r.status_code == 302 and "error=" in r.headers.get("location", ""), f"короткий code_challenge принят: {r.headers.get('location')}"


def test_N8_bearer_api_token_constant_time():
    """Н8. bearer_user сравнивает служебный токен через ==. Ожидается secrets.compare_digest."""
    from app.routers import mcp_oauth
    assert "compare_digest" in inspect.getsource(mcp_oauth.bearer_user), "mcp_oauth.bearer_user: token == settings.api_token"


# ═══════════════════════ Средне ═══════════════════════

def test_S1_exact_name_match_must_not_silently_pick_done_task(client, jack):
    """С1. Точное совпадение по названию побеждает даже у выполненной задачи: «возьми в работу договор» →
    set_task_status меняет done-задачу «Договор» вместо открытой «Договор с Эмбой».
    Ожидается: выполненная задача не трогается (ошибка с подсказкой или выбор открытой)."""
    must_ok(client, jack, "create_task", title="Договор", status="done")
    must_ok(client, jack, "create_task", title="Договор с Эмбой")
    d, err = call(client, jack, "set_task_status", task="договор", status="in_progress")
    done = must_ok(client, jack, "list_tasks", include_done=True, query="Договор")["tasks"]
    st = {t["title"]: t["status"] for t in done}
    assert st["Договор"] == "done", f"молча изменена ВЫПОЛНЕННАЯ задача «Договор» ({st}); ответ: {d}"


def test_S2_create_person_prefix_duplicate_rejected(client, jack):
    """С2. При существующем «Ержан Сапаров» create_person(name='Ержан') создаёт второго — далее delegate_task('Ержан')
    молча уходит новому. Ожидается: ошибка/кандидаты, второй «Ержан» не создаётся."""
    must_ok(client, jack, "create_person", name="Ержан Сапаров", email="e.saparov@cis.kz")
    d, err = call(client, jack, "create_person", name="Ержан")
    names = [p["name"] for p in must_ok(client, jack, "list_people")["people"]]
    assert err and names == ["Ержан Сапаров"], f"создан дубликат по префиксу: люди={names}, ответ={d}"


def test_S4_comma_joined_directions_split(client, jack):
    """С4. directions='Снабжение, Бурение' → одно направление «Снабжение, Бурение».
    Ожидается: строка режется на элементы (или создание с запятой в имени запрещено)."""
    d, err = call(client, jack, "create_task", title="Z", directions="Снабжение, Бурение", create_direction_if_missing=True)
    names = [x["name"] for x in must_ok(client, jack, "list_directions")["directions"]]
    assert "Снабжение, Бурение" not in names, f"создано направление с запятой в имени: {names}"


def test_S4_comma_joined_checklist_items_split(client, jack):
    """С4. add_checklist_items(items='a, b, c') → один пункт «a, b, c». Ожидается 3 пункта."""
    must_ok(client, jack, "create_task", title="Чеклист")
    d, err = call(client, jack, "add_checklist_items", task="Чеклист", items="Собрать КП, Согласовать, Подписать")
    cl = must_ok(client, jack, "get_task", task="Чеклист")["checklist"]
    assert len(cl) == 3, f"строка через запятую стала одним пунктом: {[c['text'] for c in cl]}"


@pytest.mark.parametrize("args", [{"limit": "все"}, {"due_within_days": "неделя"}, {"limit": -1}], ids=["limit=все", "due_within_days=неделя", "limit=-1"])
def test_S5_non_integer_limit_is_argument_error(client, jack, args):
    """С5. Нецелые limit/due_within_days → ValueError → «внутренняя ошибка сервера… не повторяйте» — Claude сдаётся,
    хотя виноват аргумент; limit=-1 → пустой список. Ожидается ToolError об аргументе (или корректная обработка)."""
    must_ok(client, jack, "create_task", title="Т")
    d, err = call(client, jack, "list_tasks", **args)
    text = json.dumps(d, ensure_ascii=False)
    assert "внутренняя ошибка" not in text, f"list_tasks({args}) → внутренняя ошибка вместо ошибки аргумента: {text[:200]}"
    if not err:
        assert d["count"] == 1 and len(d["tasks"]) == 1, f"list_tasks({args}) вернул {d}"


@pytest.mark.parametrize("msg", [
    {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": [1]},
    {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": "x"},
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": [1]},
    {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": ["get_overview"]}},
], ids=["params=list", "params=str", "initialize params=list", "name=list"])
def test_S11_non_object_params_is_jsonrpc_error_not_500(client, jack, msg):
    """С11. params/name не-объект → AttributeError/TypeError → HTTP 500 без JSON-RPC тела.
    Ожидается: HTTP 200/400 с JSON-RPC error (-32600/-32602)."""
    r = client.post("/mcp", content=json.dumps(msg), headers=jack.mcp_h)
    assert r.status_code != 500, f"{msg} → HTTP 500"
    body = r.json()
    assert isinstance(body, dict) and "error" in body, f"ожидался JSON-RPC error, получено {body}"


def test_S10_create_person_with_other_users_email_not_autolinked(client, nur, aida):
    """С10. create_person(email=<почта другого пользователя>) привязывает запись к чужому аккаунту (user_id).
    Ожидается: связь Person↔User создаётся только при входе самого пользователя."""
    d, err = call(client, nur, "create_person", name="Хакер", email=AIDA_EMAIL)
    if err:
        return  # отклонено — тоже приемлемо
    assert d["person"]["in_planner"] is False, f"Person «Хакер» привязан к аккаунту Аиды: {d}"


# ═══════════════════════ Низко ═══════════════════════

def test_N4_share_access_email_list_rejected(client, jack, monkeypatch):
    """Н4. share_access(email=[...]) создаёт пользователя с почтой "['nur@cis.kz']" (при пустом ALLOWED_EMAIL_DOMAINS).
    Ожидается: ошибка формата почты или нормализация к одному адресу."""
    from app.config import settings
    monkeypatch.setattr(settings, "allowed_email_domains", "")
    must_ok(client, jack, "create_task", title="Т")
    d, err = call(client, jack, "share_access", entity_type="task", entity="Т", email=[NUR_EMAIL])
    if not err:
        assert d["with"]["email"] == NUR_EMAIL, f"создан пользователь с мусорной почтой: {d['with']}"


def test_N7_reminder_in_past_rejected(client, jack):
    """Н7. add_reminder(fire_at=2020) создаётся и уходит на следующем тике. Ожидается ToolError «дата в прошлом»."""
    must_ok(client, jack, "create_task", title="Т")
    d, err = call(client, jack, "add_reminder", task="Т", fire_at="2020-01-01T09:00")
    assert err, f"напоминание в прошлом создано: {d}"


def test_N1_numeric_title_falls_back_to_name_search(client, jack):
    """Н1. Задача с названием «2026»: get_task(task='2026') ищет id 2026 и не находит. Ожидается поиск по названию."""
    must_ok(client, jack, "create_task", title="2026")
    d, err = call(client, jack, "get_task", task="2026")
    assert not err and d["title"] == "2026", f"числовое название трактуется как id: {d}"


# ═══════════════════════ Регрессия: что уже работает ═══════════════════════

@pytest.mark.parametrize("tool,args", [
    ("update_task", {"task": "Собрать КП", "priority": 1}),
    ("set_task_status", {"task": "Собрать КП", "status": "done"}),
    ("delegate_task", {"task": "Собрать КП", "person": "Кто-то", "create_person_if_missing": True}),
    ("add_reminder", {"task": "Собрать КП", "fire_at": "2030-09-10T10:00"}),
    ("update_direction", {"direction": "Эмба", "status": "archived"}),
    ("update_project", {"project": "Договор основной", "status": "archived"}),
    ("share_access", {"entity_type": "direction", "entity": "Эмба", "email": AIDA_EMAIL}),
    ("add_checklist_items", {"task": "Собрать КП", "items": ["a"]}),
])
def test_ok_view_only_user_writes_rejected(client, jack, nur, shared_world, tool, args):
    """Регрессия. Пользователь с view: все write-инструменты отклоняются."""
    must_ok(client, jack, "create_task", title="Собрать КП", directions=["Эмба"])
    d, err = call(client, nur, tool, **args)
    assert err, f"{tool} прошёл у view-пользователя: {d}"


def test_ok_ambiguous_match_returns_candidates(client, jack):
    """Регрессия. Несколько частичных совпадений → ошибка с кандидатами, а не тихий выбор первого."""
    must_ok(client, jack, "create_task", title="Отчёт по ГРП за август")
    must_ok(client, jack, "create_task", title="Согласовать ГРП на скв. 12")
    d, err = call(client, jack, "set_task_status", task="ГРП", status="done")
    assert err and "несколько совпадений" in d["error"] and "hint" in d


def test_ok_assignee_can_set_status_and_report(client, db, jack, nur):
    """Регрессия. Исполнитель: статус, отчёт — можно; update_task — нельзя."""
    link_person(db, nur, "Nurlan")
    must_ok(client, jack, "create_task", title="Порученная", assign_to=["Nurlan"])
    assert not call(client, nur, "set_task_status", task="Порученная", status="in_progress")[1]
    assert not call(client, nur, "update_delegation", task="Порученная", report="сделал")[1]
    assert call(client, nur, "update_task", task="Порученная", priority=1)[1]


def test_ok_mcp_protocol_basics(client, jack):
    """Регрессия. Без токена → 401 + WWW-Authenticate; неизвестный метод → -32601; уведомление → 202;
    arguments строкой/массивом → понятная ToolError, не 500."""
    r = client.post("/mcp", content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}), headers={"content-type": "application/json"})
    assert r.status_code == 401 and "resource_metadata" in r.headers.get("www-authenticate", "")
    assert rpc(client, jack, "ping").json()["result"] == {}
    assert rpc(client, jack, "tools/delete").json()["error"]["code"] == -32601
    assert client.post("/mcp", content=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}), headers=jack.mcp_h).status_code == 202
    for args in ("не json", [1, 2], None):
        r = rpc(client, jack, "tools/call", {"name": "get_task", "arguments": args})
        assert r.status_code == 200 and r.json()["result"]["isError"] is True, r.text


def test_ok_pkce_plain_rejected_and_refresh_rotation(client, jack):
    """Регрессия. PKCE plain отклоняется; ротация refresh отзывает старый access; повтор refresh → 400."""
    reg = client.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": ["https://client.test/cb"]}).json()
    r = client.get("/oauth/authorize", params={"client_id": reg["client_id"], "redirect_uri": "https://client.test/cb", "response_type": "code",
                                              "code_challenge": "abc", "code_challenge_method": "plain"}, follow_redirects=False)
    assert "error=invalid_request" in r.headers["location"]
    cid, key, verifier = _authorize(client)
    code = _consent_allow(client, key)
    tok = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "code_verifier": verifier, "client_id": cid}).json()
    h = {"Authorization": f"Bearer {tok['access_token']}", "content-type": "application/json"}
    assert client.post("/mcp", content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}), headers=h).status_code == 200
    r2 = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
    assert r2.status_code == 200
    assert client.post("/mcp", content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}), headers=h).status_code == 401
    assert client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]}).status_code == 400
