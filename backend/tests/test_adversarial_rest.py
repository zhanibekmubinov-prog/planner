"""REST: права, целостность данных, валидация — по отчёту /root/review/backend_rest.md.

Каждый тест test_<severity>_* закрепляет ОЖИДАЕМОЕ поведение: пока баг не исправлен, тест падает
с понятным сообщением; после исправления — зелёный. Тесты test_ok_* — регрессия того, что уже работает.
Участники: jack — владелец (админ), nur — коллега с правом edit, aida — коллега с view / исполнитель.
"""
import inspect
import time

import jwt
import pytest
from sqlalchemy import select

from app import models
from app.config import Settings
from tests.conftest import NUR_EMAIL, AIDA_EMAIL, count, link_person, ok


# ═══════════════════════ Критично ═══════════════════════

def test_K1_delegation_task_id_immutable(client, api, db, jack, nur):
    """К1. PUT /delegations/{id} принимает task_id из тела и переносит поручение на ЛЮБУЮ задачу:
    редактор становится исполнителем приватной задачи владельца (читает, меняет статус).
    Ожидается: смена task_id запрещена (4xx) и доступа к приватной задаче не появляется."""
    d = api.direction(jack, "Джек")
    secret = api.task(jack, "СЕКРЕТНАЯ", direction_ids=[d["id"]])
    shared = api.task(jack, "Общая", direction_ids=[d["id"]])
    api.share(jack, "task", shared["id"], NUR_EMAIL, "edit")
    pn = link_person(db, nur)
    dl = ok(client.post("/api/delegations", json={"task_id": shared["id"], "person_id": pn}, headers=nur.h), 201)

    r = client.put(f"/api/delegations/{dl['id']}", json={"task_id": secret["id"], "person_id": pn}, headers=nur.h)
    assert r.status_code in (400, 403, 422), f"PUT /delegations с чужим task_id должен отклоняться, получено {r.status_code}"
    assert client.get(f"/api/tasks/{secret['id']}", headers=nur.h).status_code == 404, \
        "Нурлан получил доступ к приватной задаче Джека через перенос поручения"
    db.expire_all()
    assert db.get(models.Delegation, dl["id"]).task_id == shared["id"], "task_id поручения изменён"


def test_K2_default_secrets_rejected_on_startup():
    """К2. Settings стартует с SESSION_SECRET='change-me-too' / API_TOKEN='change-me' — с публично известными
    секретами любой подделает JWT владельца. Ожидается: конфиг с дефолтными/пустыми секретами не создаётся."""
    try:
        # значения как при отсутствии переменных окружения на Railway
        s = Settings(database_url="sqlite://", api_token="change-me", session_secret="change-me-too", _env_file=None)
    except Exception:
        return  # ожидаемо: конфиг без секретов отклонён
    pytest.fail(f"Settings принял дефолтные секреты api_token={s.api_token!r}, session_secret={s.session_secret!r} — "
                "приложение стартует с публично известными секретами")


def test_K2_jwt_without_exp_rejected(client, jack):
    """К2 (доп.). JWT без exp принимается — бессрочная сессия. Ожидается 401."""
    tok = jwt.encode({"sub": str(jack.id)}, "test-secret", algorithm="HS256")
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401, f"JWT без exp принят ({r.status_code}) — сессия бессрочная"


# ═══════════════════════ Высоко ═══════════════════════

def _editor_setup(api, jack, nur):
    """Джек: направление D (Нурлану — edit), задача в D. Нурлан: своё направление N."""
    dj = api.direction(jack, "Эмба (Jack)")
    dn = api.direction(nur, "Личное (Nur)")
    api.share(jack, "direction", dj["id"], NUR_EMAIL, "edit")
    return dj, dn


def test_V1a_editor_cannot_move_task_to_own_direction(client, api, jack, nur):
    """В1(a). Редактор направления делает PUT задачи владельца с direction_ids=[своё направление]:
    ответ 404, но задача уже перенесена — пропала с доски Джека, Джеку утекло название чужого направления.
    Ожидается: 403 и задача остаётся в направлении владельца."""
    dj, dn = _editor_setup(api, jack, nur)
    t = api.task(jack, "ГРП", direction_ids=[dj["id"]])
    r = client.put(f"/api/tasks/{t['id']}", json=api.task_body(t, direction_ids=[dn["id"]]), headers=nur.h)
    after = api.get_task(jack, t["id"])
    assert [d["id"] for d in after["directions"]] == [dj["id"]], \
        f"задача Джека уведена в направление Нурлана: directions={[d['name'] for d in after['directions']]}"
    assert r.status_code == 403, f"ожидался 403, получено {r.status_code}"


def test_V1b_editor_cannot_orphan_task(client, api, jack, nur):
    """В1(b). Редактор снимает все направления и проект: задача-сирота, пропадает с доски владельца («тихое удаление»).
    Ожидается: 403, задача остаётся в проекте и направлении."""
    dj, dn = _editor_setup(api, jack, nur)
    p = api.project(jack, dj["id"], "Договор")
    t = api.task(jack, "В проекте", project_id=p["id"])
    r = client.put(f"/api/tasks/{t['id']}", json=api.task_body(t, direction_ids=[], project_id=None), headers=nur.h)
    after = api.get_task(jack, t["id"])
    assert after["project_id"] == p["id"] and [d["id"] for d in after["directions"]] == [dj["id"]], \
        f"редактор сделал задачу сиротой: project_id={after['project_id']}, directions={after['directions']}"
    assert r.status_code == 403, f"ожидался 403, получено {r.status_code}"


def test_V1c_editor_cannot_move_task_to_own_project(client, api, jack, nur):
    """В1(c). Редактор переносит задачу владельца в СВОЙ проект: у Джека задача в проекте, к которому у него нет доступа.
    Ожидается: 403, project_id не меняется."""
    dj, dn = _editor_setup(api, jack, nur)
    p = api.project(jack, dj["id"], "Договор")
    pn = api.project(nur, dn["id"], "Проект Нурлана")
    t = api.task(jack, "Ещё задача", project_id=p["id"])
    r = client.put(f"/api/tasks/{t['id']}", json=api.task_body(t, project_id=pn["id"], direction_ids=[]), headers=nur.h)
    after = api.get_task(jack, t["id"])
    assert after["project_id"] == p["id"], f"задача Джека оказалась в проекте Нурлана (project_id={after['project_id']})"
    assert r.status_code == 403, f"ожидался 403, получено {r.status_code}"


def test_V2_task_created_by_editor_in_shared_direction_visible_to_owner(client, api, jack, nur):
    """В2. Нурлан (edit на D) создаёт задачу с direction_ids=[D, N]: _owner_for_new назначает владельцем Нурлана,
    и Джек не видит задачу на собственной доске D. Ожидается: либо 400 (нельзя смешивать), либо задача
    принадлежит Джеку и видна ему в направлении D."""
    dj, dn = _editor_setup(api, jack, nur)
    r = client.post("/api/tasks", json={"title": "Скрытая", "direction_ids": [dj["id"], dn["id"]], "tool_ids": []}, headers=nur.h)
    if r.status_code == 400:
        return
    t = ok(r, 201)
    ids = [x["id"] for x in ok(client.get(f"/api/tasks?direction_id={dj['id']}", headers=jack.h))]
    assert t["id"] in ids, "на доске Джека (направление D) лежит задача, которую он не видит"
    assert client.get(f"/api/tasks/{t['id']}", headers=jack.h).status_code == 200, "владелец направления не видит задачу в нём"


def test_V2_task_created_by_editor_in_owner_project_visible_to_owner(client, api, jack, nur):
    """В2 (проект). Нурлан создаёт задачу в проекте Джека, добавив своё направление: владельцем становится Нурлан,
    Джек не видит задачу в своём проекте. Ожидается: задача видна владельцу проекта (или 400)."""
    dj, dn = _editor_setup(api, jack, nur)
    p = api.project(jack, dj["id"], "Договор")
    r = client.post("/api/tasks", json={"title": "Скрытая в проекте", "project_id": p["id"], "direction_ids": [dn["id"]], "tool_ids": []}, headers=nur.h)
    if r.status_code == 400:
        return
    t = ok(r, 201)
    ids = [x["id"] for x in ok(client.get(f"/api/tasks?project_id={p['id']}", headers=jack.h))]
    assert t["id"] in ids, "в проекте Джека есть задача, которую Джек не видит"


def test_V3_reminder_task_id_immutable(client, api, db, jack, nur):
    """В3. PUT /reminders/{id} переносит напоминание на чужую задачу (проверяется только старый task_id).
    Ожидается: смена task_id отклоняется, напоминание остаётся на исходной задаче."""
    d = api.direction(jack, "Джек")
    secret = api.task(jack, "СЕКРЕТНАЯ", direction_ids=[d["id"]])
    shared = api.task(jack, "Общая", direction_ids=[d["id"]])
    api.share(jack, "task", shared["id"], NUR_EMAIL, "edit")
    rm = ok(client.post("/api/reminders", json={"task_id": shared["id"], "fire_at": "2030-01-01T09:00:00Z"}, headers=nur.h), 201)
    r = client.put(f"/api/reminders/{rm['id']}", json={"task_id": secret["id"], "fire_at": "2030-01-01T09:00:00Z", "channels": ["telegram"], "recipient": "owner"}, headers=nur.h)
    assert r.status_code in (400, 403, 422), f"PUT /reminders с чужим task_id должен отклоняться, получено {r.status_code}"
    db.expire_all()
    assert db.get(models.Reminder, rm["id"]).task_id == shared["id"], "напоминание перенесено на чужую задачу"


@pytest.mark.parametrize("method", ["post", "put"])
def test_V3_reminder_fire_at_in_past_rejected(client, api, jack, method):
    """В3/С6. fire_at в прошлом принимается — планировщик отправит на первом же тике (мгновенный спам).
    Ожидается: 400/422 при создании и при изменении."""
    t = api.task(jack, "Т")
    body = {"task_id": t["id"], "fire_at": "2020-01-01T09:00:00Z", "channels": ["telegram"], "recipient": "owner"}
    if method == "post":
        r = client.post("/api/reminders", json=body, headers=jack.h)
    else:
        rm = ok(client.post("/api/reminders", json={**body, "fire_at": "2030-01-01T09:00:00Z"}, headers=jack.h), 201)
        r = client.put(f"/api/reminders/{rm['id']}", json=body, headers=jack.h)
    assert r.status_code in (400, 422), f"напоминание с fire_at=2020 принято ({r.status_code})"


def test_V4_person_update_by_stranger_forbidden(client, api, jack, aida):
    """В4. Любой пользователь правит любого человека: подмена telegram_chat_id/email → уведомления о чужих
    поручениях уходят в чужой чат. Ожидается: 403 для не-автора и не-админа."""
    p = api.person(jack, "Асхат", telegram_chat_id="111", email="askhat@cis.kz")
    r = client.put(f"/api/people/{p['id']}", json={"name": "Асхат", "telegram_chat_id": "999-attacker", "email": "attacker@evil.com"}, headers=aida.h)
    assert r.status_code == 403, f"Аида изменила запись человека Джека ({r.status_code})"


def test_V4_person_delete_by_stranger_forbidden(client, api, jack, aida):
    """В4. Любой пользователь удаляет любого человека из общего справочника. Ожидается 403."""
    p = api.person(jack, "Асхат")
    r = client.delete(f"/api/people/{p['id']}", headers=aida.h)
    assert r.status_code == 403, f"Аида удалила человека Джека ({r.status_code})"


def test_V4_person_delete_with_delegations_is_409_not_500(client, api, jack):
    """В4. Удаление человека с поручениями → IntegrityError → 500. Ожидается 409 с понятным текстом."""
    p = api.person(jack, "Асхат")
    t = api.task(jack, "С поручением")
    ok(client.post("/api/delegations", json={"task_id": t["id"], "person_id": p["id"]}, headers=jack.h), 201)
    r = client.delete(f"/api/people/{p['id']}", headers=jack.h)
    assert r.status_code == 409, f"удаление человека с поручениями вернуло {r.status_code} вместо 409"


def test_V5_editor_cannot_move_project_to_own_direction(client, api, jack, nur):
    """В5. Редактор направления переносит проект владельца в своё направление: у Джека проект в недоступном ему
    направлении, Нурлан сам теряет доступ. Ожидается: 403, direction_id не меняется."""
    dj, dn = _editor_setup(api, jack, nur)
    p = api.project(jack, dj["id"], "Переносимый")
    r = client.put(f"/api/projects/{p['id']}", json={"direction_id": dn["id"], "name": p["name"], "description": None, "goal": None, "color": None, "status": "active"}, headers=nur.h)
    after = ok(client.get(f"/api/projects/{p['id']}", headers=jack.h))
    assert after["direction_id"] == dj["id"], f"проект Джека перенесён в направление Нурлана (direction_id={after['direction_id']})"
    assert r.status_code == 403, f"ожидался 403, получено {r.status_code}"


# ═══════════════════════ Средне ═══════════════════════

def test_S1_direction_delete_removes_stale_shares(client, api, db, jack, nur, aida):
    """С1. После DELETE направления в shares остаются строки на удалённое направление и его проекты
    (мусор в Grants, отозвать нельзя — GET /shares → 404). Ожидается: шары удаляются вместе с сущностью."""
    d = api.direction(jack, "Эмба")
    p = api.project(jack, d["id"], "Договор")
    api.share(jack, "direction", d["id"], NUR_EMAIL, "edit")
    api.share(jack, "project", p["id"], AIDA_EMAIL, "view")
    ok(client.delete(f"/api/directions/{d['id']}", headers=jack.h), 204)
    stale = db.execute(select(models.Share.entity_type, models.Share.entity_id)).all()
    assert stale == [], f"висячие шары после удаления направления: {stale}"


def test_S1_stale_share_does_not_grant_access_to_new_entity(client, api, jack, nur):
    """С1. Висячая шара + повторное использование id (sqlite без AUTOINCREMENT) → Нурлан получает edit
    на новое приватное направление Джека. Ожидается: новое направление Нурлану не видно."""
    d = api.direction(jack, "Старое")
    api.share(jack, "direction", d["id"], NUR_EMAIL, "edit")
    ok(client.delete(f"/api/directions/{d['id']}", headers=jack.h), 204)
    d2 = api.direction(jack, "Новое приватное")
    visible = [(x["id"], x["name"]) for x in ok(client.get("/api/directions", headers=nur.h))]
    assert (d2["id"], d2["name"]) not in visible, f"Нурлан видит приватное направление Джека через висячую шару: {visible}"


def test_N7_task_delete_removes_stale_shares(client, api, db, jack, nur):
    """Н7. DELETE задачи оставляет shares с entity_type='task'. Ожидается: шары задачи удалены."""
    t = api.task(jack, "Удаляемая")
    api.share(jack, "task", t["id"], NUR_EMAIL, "edit")
    ok(client.delete(f"/api/tasks/{t['id']}", headers=jack.h), 204)
    assert count(db, models.Share, models.Share.entity_type == "task") == 0, "после удаления задачи остались её шары"


def test_S2_project_move_replaces_direction_on_tasks(client, api, jack):
    """С2. Перенос проекта в другое направление: задачи получают новое направление, но сохраняют старое —
    числятся в двух направлениях, статистика старого считает чужой проект.
    Ожидается: у задачи проекта остаётся только новое направление."""
    d1 = api.direction(jack, "Д1"); d2 = api.direction(jack, "Д2")
    p = api.project(jack, d1["id"], "П")
    t = api.task(jack, "в П", project_id=p["id"])
    ok(client.put(f"/api/projects/{p['id']}", json={"direction_id": d2["id"], "name": "П", "description": None, "goal": None, "color": None, "status": "active"}, headers=jack.h))
    after = api.get_task(jack, t["id"])
    assert [x["id"] for x in after["directions"]] == [d2["id"]], \
        f"после переноса проекта задача в направлениях {[x['name'] for x in after['directions']]}, ожидалось только «Д2»"


@pytest.mark.parametrize("method", ["post", "put"])
def test_S3_duplicate_tool_ids_not_500(client, api, jack, method):
    """С3. tool_ids: [1, 1] → IntegrityError на tool_tasks → 500. Ожидается: дедупликация (2xx) или 422."""
    tool = ok(client.post("/api/tools", json={"name": "t"}, headers=jack.h), 201)
    body = {"title": "ok", "direction_ids": [], "tool_ids": [tool["id"], tool["id"]]}
    if method == "post":
        r = client.post("/api/tasks", json=body, headers=jack.h)
    else:
        t = api.task(jack, "x")
        r = client.put(f"/api/tasks/{t['id']}", json=body, headers=jack.h)
    assert r.status_code in (200, 201, 422), f"дублирующиеся tool_ids дали {r.status_code}"


@pytest.mark.parametrize("payload", [{"email": "x", "exp": 4102444800}, {"sub": "abc", "exp": 4102444800}], ids=["без sub", "sub='abc'"])
def test_S4_jwt_bad_sub_is_401_not_500(client, payload):
    """С4. JWT без sub / с нечисловым sub → int(data['sub']) падает → 500. Ожидается 401."""
    tok = jwt.encode(payload, "test-secret", algorithm="HS256")
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401, f"некорректный JWT дал {r.status_code} вместо 401"


def test_S5_stale_put_detected(client, api, jack):
    """С5. Lost update: PUT без версии — устаревший снимок клиента B затирает статус/чеклист клиента A.
    Ожидается: PUT с устаревшим updated_at → 409, изменения A сохраняются."""
    t = api.task(jack, "автосохранение", checklist=[{"id": "1", "text": "a", "done": False}])
    snapshot = api.get_task(jack, t["id"])
    time.sleep(1.1)  # чтобы updated_at первого PUT точно отличался от снимка
    ok(client.put(f"/api/tasks/{t['id']}", json=api.task_body(snapshot, status="in_progress", checklist=[{"id": "1", "text": "a", "done": True}]), headers=jack.h))
    stale = {**api.task_body(snapshot, description="клиент B дописал"), "updated_at": snapshot["updated_at"]}
    r = client.put(f"/api/tasks/{t['id']}", json=stale, headers=jack.h)
    after = api.get_task(jack, t["id"])
    assert r.status_code == 409, f"PUT с устаревшим updated_at принят ({r.status_code}) — изменения другого клиента потеряны"
    assert after["status"] == "in_progress" and after["checklist"][0]["done"] is True, "статус/чеклист клиента A затёрты"


_VALIDATION = [
    ("/api/directions", {"name": ""}, "направление: пустое имя"),
    ("/api/directions", {"name": "   "}, "направление: имя из пробелов"),
    ("/api/directions", {"name": "x" * 5000}, "направление: имя 5000 символов при String(200)"),
    ("/api/directions", {"name": "ok", "color": "javascript:alert(1)"}, "направление: color не #rrggbb"),
    ("/api/tasks", {"title": "", "direction_ids": [], "tool_ids": []}, "задача: пустой title"),
    ("/api/tasks", {"title": "x" * 10000, "direction_ids": [], "tool_ids": []}, "задача: title 10000 символов при String(300)"),
    ("/api/tasks", {"title": "ok", "priority": 0, "direction_ids": [], "tool_ids": []}, "задача: priority 0"),
    ("/api/tasks", {"title": "ok", "priority": 99, "direction_ids": [], "tool_ids": []}, "задача: priority 99"),
    ("/api/tasks", {"title": "ok", "priority": -5, "direction_ids": [], "tool_ids": []}, "задача: priority -5"),
    ("/api/tasks", {"title": "ok", "direction_ids": [], "tool_ids": [], "checklist": [{"id": "a", "text": "1"}, {"id": "a", "text": "2"}]}, "чеклист: дублирующиеся id"),
    ("/api/tasks", {"title": "ok", "direction_ids": [], "tool_ids": [], "checklist": [{"id": "", "text": ""}]}, "чеклист: пустые id/text"),
    ("/api/people", {"name": ""}, "человек: пустое имя"),
    ("/api/mindmaps", {"title": "", "data": {}}, "майндмап: пустой title"),
]


@pytest.mark.parametrize("url,body,label", _VALIDATION, ids=[x[2] for x in _VALIDATION])
def test_S6_input_validation(client, jack, url, body, label):
    """С6. Пробелы во входной валидации schemas.py: всё перечисленное сейчас → 201 (на Postgres длинные строки → 500).
    Ожидается 422."""
    r = client.post(url, json=body, headers=jack.h)
    assert r.status_code == 422, f"{label}: принято со статусом {r.status_code}, ожидалось 422"


def test_S6_project_validation(client, api, jack):
    """С6. Проект с пустым именем и color длиной 101 при String(16) → 201. Ожидается 422."""
    d = api.direction(jack, "Д")
    r = client.post("/api/projects", json={"direction_id": d["id"], "name": "", "color": "#" + "f" * 100}, headers=jack.h)
    assert r.status_code == 422, f"проект с пустым именем и мусорным color принят ({r.status_code})"


def test_S6_reminder_channels_empty_rejected(client, api, jack):
    """С6. Напоминание с channels=[] создаётся (никуда не отправится). Ожидается 422."""
    t = api.task(jack, "Т")
    r = client.post("/api/reminders", json={"task_id": t["id"], "fire_at": "2030-01-01T09:00:00Z", "channels": []}, headers=jack.h)
    assert r.status_code == 422, f"напоминание без каналов принято ({r.status_code})"


def test_S7_error_response_means_no_change(client, api, jack, nur):
    """С7. Мутация фиксируется в БД, а ответ — 404: клиент считает, что ничего не произошло.
    Ожидается: если ответ ≥ 400, состояние задачи не изменилось."""
    dj, dn = _editor_setup(api, jack, nur)
    t = api.task(jack, "ГРП", direction_ids=[dj["id"]])
    r = client.put(f"/api/tasks/{t['id']}", json=api.task_body(t, direction_ids=[dn["id"]], title="переименована"), headers=nur.h)
    after = api.get_task(jack, t["id"])
    if r.status_code >= 400:
        assert after["title"] == "ГРП" and [d["id"] for d in after["directions"]] == [dj["id"]], \
            f"ответ {r.status_code}, но изменение сохранено: title={after['title']!r}, directions={[d['name'] for d in after['directions']]}"


# ═══════════════════════ Низко ═══════════════════════

def test_N1_api_token_constant_time_compare():
    """Н1. X-API-Token сравнивается через ==. Ожидается secrets.compare_digest в auth.current_user."""
    import app.auth as A
    src = inspect.getsource(A.current_user)
    assert "compare_digest" in src, "auth.current_user сравнивает X-API-Token оператором == (не константное время)"


def test_N2_share_email_without_local_part_rejected(client, api, jack):
    """Н2. POST /shares с email '@cis.kz' создаёт пользователя с пустым именем. Ожидается 400/422."""
    d = api.direction(jack, "Д")
    r = client.post("/api/shares", json={"entity_type": "direction", "entity_id": d["id"], "email": "@cis.kz"}, headers=jack.h)
    assert r.status_code in (400, 422), f"приглашение по адресу '@cis.kz' принято ({r.status_code})"


@pytest.mark.parametrize("kind", ["direction", "task"])
def test_N4_editor_delete_is_403(client, api, jack, nur, kind):
    """Н4. Редактор (edit) делает DELETE чужой сущности → 404, хотя сущность ему видна. Ожидается 403."""
    d = api.direction(jack, "Д")
    api.share(jack, "direction", d["id"], NUR_EMAIL, "edit")
    t = api.task(jack, "Т", direction_ids=[d["id"]])
    url = f"/api/directions/{d['id']}" if kind == "direction" else f"/api/tasks/{t['id']}"
    r = client.delete(url, headers=nur.h)
    assert r.status_code == 403, f"DELETE {kind} редактором → {r.status_code}, ожидалось 403"


def test_N6_person_with_other_users_email_not_autolinked(client, api, jack, nur, aida):
    """Н6/С10. Нурлан создаёт Person с почтой Аиды → запись автоматически привязывается к её аккаунту (user_id),
    имя задаёт не она. Ожидается: user_id не выставляется (связь создаётся только при входе самой Аиды)."""
    p = api.person(nur, "fake", email=AIDA_EMAIL)
    assert p["user_id"] is None, f"Person, созданный Нурланом, привязан к аккаунту Аиды (user_id={p['user_id']})"


# ═══════════════════════ Служебные ручки (из отчёта MCP, С12) ═══════════════════════

def test_S12_notify_run_now_admin_only(client, nur):
    """С12. POST /api/notify/run-now доступен любому пользователю и обрабатывает напоминания ВСЕХ.
    Ожидается 403 для не-админа."""
    r = client.post("/api/notify/run-now", headers=nur.h)
    assert r.status_code == 403, f"не-админ запустил глобальную обработку напоминаний ({r.status_code})"


def test_S12_notify_digest_rate_limited(client, nur):
    """С12. POST /api/notify/digest без ограничения частоты — спам Telegram/Graph и рост activity_log.
    Ожидается: повторный вызов в течение минуты → 429."""
    first = client.post("/api/notify/digest", json={"channels": []}, headers=nur.h)
    assert first.status_code in (200, 429, 502), first.text
    second = client.post("/api/notify/digest", json={"channels": []}, headers=nur.h)
    assert second.status_code == 429, f"второй вызов /notify/digest подряд принят ({second.status_code}), ожидалось 429"


# ═══════════════════════ Регрессия: что уже работает ═══════════════════════

def test_ok_view_only_user_cannot_write(client, api, jack, aida):
    """Регрессия. view: PUT/status/DELETE/напоминание/проект/шара — отклоняются."""
    d = api.direction(jack, "Только просмотр")
    api.share(jack, "direction", d["id"], AIDA_EMAIL, "view")
    t = api.task(jack, "view task", direction_ids=[d["id"]])
    assert client.put(f"/api/tasks/{t['id']}", json=api.task_body(t), headers=aida.h).status_code == 403
    assert client.post(f"/api/tasks/{t['id']}/status", json={"status": "done"}, headers=aida.h).status_code == 403
    assert client.delete(f"/api/tasks/{t['id']}", headers=aida.h).status_code in (403, 404)
    assert client.post("/api/reminders", json={"task_id": t["id"], "fire_at": "2030-01-01T09:00:00Z"}, headers=aida.h).status_code == 403
    assert client.post("/api/projects", json={"direction_id": d["id"], "name": "x"}, headers=aida.h).status_code == 403
    assert client.post("/api/shares", json={"entity_type": "direction", "entity_id": d["id"], "email": NUR_EMAIL}, headers=aida.h).status_code == 403
    assert ok(client.get(f"/api/tasks/{t['id']}", headers=aida.h))["access"] == "view"


def test_ok_editor_cannot_manage_shares(client, api, jack, nur, aida):
    """Регрессия. Редактор не может делиться, отзывать и менять чужие шары; шара с собой — 400;
    permission/entity_type вне списка — 400."""
    d = api.direction(jack, "Д")
    api.share(jack, "direction", d["id"], NUR_EMAIL, "edit")
    sh = api.share(jack, "direction", d["id"], AIDA_EMAIL, "view")
    assert client.post("/api/shares", json={"entity_type": "direction", "entity_id": d["id"], "email": AIDA_EMAIL}, headers=nur.h).status_code == 403
    assert client.delete(f"/api/shares/{sh['id']}", headers=nur.h).status_code == 403
    assert client.put(f"/api/shares/{sh['id']}", json={"permission": "edit"}, headers=nur.h).status_code == 403
    assert client.post("/api/shares", json={"entity_type": "direction", "entity_id": d["id"], "email": "jack@cis.kz"}, headers=jack.h).status_code == 400
    assert client.post("/api/shares", json={"entity_type": "direction", "entity_id": d["id"], "email": AIDA_EMAIL, "permission": "admin"}, headers=jack.h).status_code == 400
    assert client.post("/api/shares", json={"entity_type": "user", "entity_id": 1, "email": AIDA_EMAIL}, headers=jack.h).status_code == 400
    assert client.post("/api/shares", json={"entity_type": "direction", "entity_id": d["id"], "email": "x@gmail.com"}, headers=jack.h).status_code == 400


def test_ok_assignee_can_change_status_and_report_only(client, api, db, jack, aida):
    """Регрессия. Исполнитель: статус и отчёт — 200; PUT задачи и поручения, DELETE поручения — 403."""
    pa = link_person(db, aida)
    t = api.task(jack, "поручено Аиде")
    dl = ok(client.post("/api/delegations", json={"task_id": t["id"], "person_id": pa}, headers=jack.h), 201)
    got = ok(client.get(f"/api/tasks/{t['id']}", headers=aida.h))
    assert got["access"] == "assignee" and got["assigned_to_me"] is True
    assert client.post(f"/api/tasks/{t['id']}/status", json={"status": "in_progress"}, headers=aida.h).status_code == 200
    assert client.put(f"/api/delegations/{dl['id']}/report", json={"status": "done", "report": "ok"}, headers=aida.h).status_code == 200
    assert client.put(f"/api/tasks/{t['id']}", json=api.task_body(got), headers=aida.h).status_code == 403
    assert client.put(f"/api/delegations/{dl['id']}", json={"task_id": t["id"], "person_id": pa}, headers=aida.h).status_code == 403
    assert client.delete(f"/api/delegations/{dl['id']}", headers=aida.h).status_code == 403


def test_ok_project_delete_keeps_tasks_in_direction(client, api, jack, nur):
    """Регрессия. Удаление проекта: задачи остаются в направлении (project_id=None), шары на проект перестают действовать."""
    d = api.direction(jack, "Д"); p = api.project(jack, d["id"], "П")
    t = api.task(jack, "в проекте", project_id=p["id"])
    api.share(jack, "project", p["id"], NUR_EMAIL, "edit")
    ok(client.delete(f"/api/projects/{p['id']}", headers=jack.h), 204)
    after = api.get_task(jack, t["id"])
    assert after["project_id"] is None and [x["id"] for x in after["directions"]] == [d["id"]]
    assert ok(client.get("/api/tasks", headers=nur.h)) == []


def test_ok_task_delete_cascades(client, api, db, jack):
    """Регрессия. Удаление задачи каскадно удаляет напоминания, поручения и майндмапы задачи."""
    p = api.person(jack, "Асхат")
    t = api.task(jack, "удаляемая")
    rm = ok(client.post("/api/reminders", json={"task_id": t["id"], "fire_at": "2030-01-01T09:00:00Z"}, headers=jack.h), 201)
    dl = ok(client.post("/api/delegations", json={"task_id": t["id"], "person_id": p["id"]}, headers=jack.h), 201)
    mm = ok(client.post("/api/mindmaps", json={"title": "mmt", "task_id": t["id"], "data": {}}, headers=jack.h), 201)
    ok(client.delete(f"/api/tasks/{t['id']}", headers=jack.h), 204)
    assert db.get(models.Reminder, rm["id"]) is None and db.get(models.Delegation, dl["id"]) is None and db.get(models.MindMap, mm["id"]) is None


def test_ok_direction_delete_nulls_mindmap_direction(client, api, db, jack):
    """Регрессия. Удаление направления обнуляет mindmap.direction_id, сам майндмап остаётся."""
    d = api.direction(jack, "Д")
    mm = ok(client.post("/api/mindmaps", json={"title": "mm", "direction_id": d["id"], "data": {}}, headers=jack.h), 201)
    ok(client.delete(f"/api/directions/{d['id']}", headers=jack.h), 204)
    db.expire_all()
    obj = db.get(models.MindMap, mm["id"])
    assert obj is not None and obj.direction_id is None


def test_ok_enum_validation_and_404(client, api, jack):
    """Регрессия. status/channels/recipient вне enum → 422; несуществующие id → 404."""
    t = api.task(jack, "Т")
    assert client.post("/api/tasks", json={"title": "x", "status": "bogus", "direction_ids": [], "tool_ids": []}, headers=jack.h).status_code == 422
    assert client.post("/api/reminders", json={"task_id": t["id"], "fire_at": "2030-01-01T00:00:00Z", "channels": ["sms"]}, headers=jack.h).status_code == 422
    assert client.post("/api/reminders", json={"task_id": t["id"], "fire_at": "2030-01-01T00:00:00Z", "recipient": "everyone"}, headers=jack.h).status_code == 422
    for url in ("/api/tasks/99999", "/api/directions/99999", "/api/projects/99999", "/api/mindmaps/99999"):
        assert client.get(url, headers=jack.h).status_code == 404, url
    assert client.post("/api/delegations", json={"task_id": t["id"], "person_id": 999}, headers=jack.h).status_code == 404


def test_ok_api_token_auth(client, jack):
    """Регрессия. X-API-Token верный → владелец; неверный → 401; без токена → 401."""
    me = ok(client.get("/api/auth/me", headers={"X-API-Token": "tok"}))
    assert me["email"] == "jack@cis.kz" and me["is_admin"] is True
    assert client.get("/api/auth/me", headers={"X-API-Token": "tokk"}).status_code == 401
    assert client.get("/api/auth/me").status_code == 401
