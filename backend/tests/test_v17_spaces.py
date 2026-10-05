"""v1.7: слои «Личное» / «Организация».

Решения владельца (2026-10-05): слой живёт на направлении; попадание автоматическое
(поделились или поручили → «Организация») с возможностью переопределить руками;
перенос в «Личное» сам доступ не снимает — владелец выбирает это в окне.
"""
from app import models
from tests.conftest import NUR_EMAIL, link_person, ok


def _dir(client, u, id_):
    return ok(client.get(f"/api/directions/{id_}", headers=u.h))


# ═══════════════════════ Слой по умолчанию и создание ═══════════════════════

def test_new_direction_is_personal_by_default(client, api, jack):
    d = api.direction(jack, "Личное развитие")
    assert d["space"] == "personal"
    assert d["space_pinned"] is False


def test_direction_created_in_current_space(client, api, jack):
    """Фронт шлёт слой, в котором владелец сейчас работает."""
    d = api.direction(jack, "Эмба", space="org")
    assert d["space"] == "org"
    assert d["space_pinned"] is False, "создание в слое не пришпиливает — автоправило ещё работает"


def test_update_does_not_touch_space(client, api, jack):
    """Обычная правка направления слой не меняет, даже если старый клиент его не прислал."""
    d = api.direction(jack, "Эмба", space="org")
    ok(client.put(f"/api/directions/{d['id']}", json={"name": "Эмба-2"}, headers=jack.h))
    assert _dir(client, jack, d["id"])["space"] == "org"


# ═══════════════════════ Автоправило ═══════════════════════

def test_share_moves_direction_to_org(client, api, jack, nur):
    d = api.direction(jack, "Эмба")
    out = api.share(jack, "direction", d["id"], NUR_EMAIL)
    assert out["space_moved"] == ["Эмба"], "фронту нужен повод показать тост"
    assert _dir(client, jack, d["id"])["space"] == "org"


def test_share_on_project_moves_its_direction(client, api, jack, nur):
    d = api.direction(jack, "Эмба")
    p = api.project(jack, d["id"], "Договор")
    api.share(jack, "project", p["id"], NUR_EMAIL)
    assert _dir(client, jack, d["id"])["space"] == "org"


def test_share_on_task_moves_all_its_directions(client, api, jack, nur):
    a = api.direction(jack, "Эмба")
    b = api.direction(jack, "Кашаган")
    t = api.task(jack, "Общая", direction_ids=[a["id"], b["id"]])
    api.share(jack, "task", t["id"], NUR_EMAIL)
    assert _dir(client, jack, a["id"])["space"] == "org"
    assert _dir(client, jack, b["id"])["space"] == "org"


def test_delegation_moves_direction_to_org(client, api, db, jack, nur):
    d = api.direction(jack, "Эмба")
    t = api.task(jack, "Собрать документы", direction_ids=[d["id"]])
    pid = link_person(db, nur)
    out = ok(client.post("/api/delegations", json={"task_id": t["id"], "person_id": pid}, headers=jack.h), 201)
    assert out["space_moved"] == ["Эмба"]
    assert _dir(client, jack, d["id"])["space"] == "org"


def test_repeated_share_does_not_report_move_twice(client, api, jack, nur, aida):
    """Направление уже в «Организации» — второй доступ ничего не двигает и тост не показывает."""
    d = api.direction(jack, "Эмба")
    api.share(jack, "direction", d["id"], NUR_EMAIL)
    out = api.share(jack, "direction", d["id"], aida.email)
    assert out["space_moved"] == []


def test_pinned_direction_is_not_moved_by_sharing(client, api, jack, nur):
    """Главное правило: поставил слой руками — автоправило больше не вмешивается."""
    d = api.direction(jack, "Личное развитие")
    ok(client.put(f"/api/directions/{d['id']}/space", json={"space": "personal"}, headers=jack.h))
    out = api.share(jack, "direction", d["id"], NUR_EMAIL)
    assert out["space_moved"] == []
    assert _dir(client, jack, d["id"])["space"] == "personal", "осталось личным, хотя доступ выдан"


# ═══════════════════════ Перенос руками ═══════════════════════

def test_move_pins_the_space(client, api, jack):
    d = api.direction(jack, "Эмба")
    out = ok(client.put(f"/api/directions/{d['id']}/space", json={"space": "org"}, headers=jack.h))
    assert out["space"] == "org" and out["space_pinned"] is True


def test_move_to_personal_keeps_access_by_default(client, api, db, jack, nur):
    """Слой — это раскладка, а не замок: молча доступ не снимаем."""
    d = api.direction(jack, "Эмба")
    api.share(jack, "direction", d["id"], NUR_EMAIL)
    ok(client.put(f"/api/directions/{d['id']}/space", json={"space": "personal"}, headers=jack.h))
    assert db.query(models.Share).count() == 1
    assert ok(client.get("/api/directions", headers=nur.h)), "коллега всё ещё видит направление"


def test_move_to_personal_can_revoke_access(client, api, db, jack, nur):
    d = api.direction(jack, "Эмба")
    p = api.project(jack, d["id"], "Договор")
    t = api.task(jack, "Задача", direction_ids=[d["id"]])
    api.share(jack, "direction", d["id"], NUR_EMAIL)
    api.share(jack, "project", p["id"], NUR_EMAIL)
    api.share(jack, "task", t["id"], NUR_EMAIL)
    ok(client.put(f"/api/directions/{d['id']}/space", json={"space": "personal", "revoke_shares": True}, headers=jack.h))
    assert db.query(models.Share).count() == 0, "снимается доступ и к направлению, и к проекту, и к задаче"
    assert ok(client.get("/api/directions", headers=nur.h)) == []


def test_revoke_flag_ignored_when_moving_to_org(client, api, db, jack, nur):
    d = api.direction(jack, "Эмба")
    api.share(jack, "direction", d["id"], NUR_EMAIL)
    ok(client.put(f"/api/directions/{d['id']}/space", json={"space": "org", "revoke_shares": True}, headers=jack.h))
    assert db.query(models.Share).count() == 1


def test_space_preview_lists_people_once(client, api, jack, nur):
    """Один человек — одна строка, право сильнейшее из его шар."""
    d = api.direction(jack, "Эмба")
    p = api.project(jack, d["id"], "Договор")
    api.share(jack, "direction", d["id"], NUR_EMAIL, permission="view")
    api.share(jack, "project", p["id"], NUR_EMAIL, permission="edit")
    out = ok(client.get(f"/api/directions/{d['id']}/space-preview", headers=jack.h))
    assert len(out["people"]) == 1
    assert out["people"][0]["email"] == NUR_EMAIL
    assert out["people"][0]["permission"] == "edit"


def test_only_owner_moves_direction(client, api, jack, nur):
    d = api.direction(jack, "Эмба")
    api.share(jack, "direction", d["id"], NUR_EMAIL, permission="edit")
    r = client.put(f"/api/directions/{d['id']}/space", json={"space": "personal"}, headers=nur.h)
    assert r.status_code in (403, 404), "редактор не распоряжается чужой раскладкой"


def test_bad_space_rejected(client, api, jack):
    d = api.direction(jack, "Эмба")
    assert client.put(f"/api/directions/{d['id']}/space", json={"space": "secret"}, headers=jack.h).status_code == 422


# ═══════════════════════ Задачи ═══════════════════════

def test_orphan_task_keeps_its_own_space(client, api, jack):
    """Задача без направлений наследует слой, в котором её создали."""
    t = api.task(jack, "Позвонить", space="org")
    assert api.get_task(jack, t["id"])["space"] == "org"


def test_task_space_is_not_cleared_by_update(client, api, jack):
    """Старый клиент не шлёт space — уже выставленный слой не должен обнуляться."""
    t = api.task(jack, "Позвонить", space="org")
    ok(client.put(f"/api/tasks/{t['id']}", json=api.task_body(t), headers=jack.h))
    assert api.get_task(jack, t["id"])["space"] == "org"


def test_task_with_directions_carries_their_space(client, api, jack):
    """Слой задачи с направлениями фронт считает по направлениям — они приходят в выдаче."""
    d = api.direction(jack, "Эмба", space="org")
    t = api.task(jack, "Задача", direction_ids=[d["id"]])
    got = api.get_task(jack, t["id"])
    assert [x["space"] for x in got["directions"]] == ["org"]


# ═══════════════════════ Через Claude (MCP) ═══════════════════════

def _rpc(client, u, tool, **args):
    import json
    r = client.post("/mcp", content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                "params": {"name": tool, "arguments": args}}), headers=u.mcp_h)
    assert r.status_code == 200, r.text[:200]
    res = r.json()["result"]
    return json.loads(res["content"][0]["text"]), bool(res.get("isError"))


def test_mcp_list_directions_shows_and_filters_space(client, api, jack):
    api.direction(jack, "Личное развитие")
    api.direction(jack, "Эмба", space="org")
    out, err = _rpc(client, jack, "list_directions")
    assert not err
    assert {d["name"]: d["space"] for d in out["directions"]} == {"Личное развитие": "personal", "Эмба": "org"}
    only_org, _ = _rpc(client, jack, "list_directions", space="org")
    assert [d["name"] for d in only_org["directions"]] == ["Эмба"]


def test_mcp_move_direction_space(client, api, jack):
    d = api.direction(jack, "Эмба")
    out, err = _rpc(client, jack, "move_direction_space", direction="Эмба", space="org")
    assert not err, out
    assert out["direction"]["space"] == "org"
    assert _dir(client, jack, d["id"])["space_pinned"] is True, "перенос закрепляет слой"


def test_mcp_move_does_not_touch_access(client, api, db, jack, nur):
    """Через Claude доступ не снимается — это решение принимается в планнере, видя список людей."""
    d = api.direction(jack, "Эмба")
    api.share(jack, "direction", d["id"], NUR_EMAIL)
    out, err = _rpc(client, jack, "move_direction_space", direction="Эмба", space="personal")
    assert not err, out
    assert db.query(models.Share).count() == 1
    assert "закрыть его можно в планнере" in out["note"]


def test_mcp_bad_space_gives_hint(client, api, jack):
    api.direction(jack, "Эмба")
    out, _ = _rpc(client, jack, "move_direction_space", direction="Эмба", space="secret")
    assert out["isError"] and "personal" in out["hint"]
