"""v1.8 — совместная работа над майндмапом.

Симптом владельца: «сделай совместный режим в планере, особенно майндмап». До v1.8 карту видел
только её автор, а редактор отправлял её целиком — двое одновременно затирали друг друга.

Проверяем путём пользователя: создать карту → открыть коллеге (через направление / задачу / саму
карту) → оба правят операциями → правки обоих на месте; живой канал раздаёт чужие правки и присутствие.
"""
import json

import pytest
from starlette.websockets import WebSocketDisconnect

from app import live, mcp_tools, models
from app.auth import issue_session
from tests.conftest import NUR_EMAIL, AIDA_EMAIL, ok


def mindmap(client, u, title="Карта", data=None, **kw):
    body = {"title": title, "data": data or {"id": "root", "text": title, "children": []}, **kw}
    return ok(client.post("/api/mindmaps", json=body, headers=u.h), 201)


def ops(client, u, map_id, *items, batch="b1", code=200):
    r = client.post(f"/api/mindmaps/{map_id}/ops", json={"batch": batch, "ops": list(items)}, headers=u.h)
    assert r.status_code == code, r.text[:300]
    return r.json()


def add(parent, nid, text="", **extra):
    return {"type": "add", "parent": parent, "node": {"id": nid, "text": text, **extra}}


def texts(node):
    out = [node["text"]]
    for c in node.get("children", []):
        out += texts(c)
    return out


def listed(client, u):
    return {m["id"]: m for m in ok(client.get("/api/mindmaps", headers=u.h))}


# ── доступ ───────────────────────────────────────────────────────────────────

def test_map_follows_direction_access(client, api, jack, nur):
    d = api.direction(jack, "Снабжение")
    m = mindmap(client, jack, "Закуп", direction_id=d["id"])
    # пока не поделились — чужая карта не видна даже по id
    assert m["id"] not in listed(client, nur)
    assert client.get(f"/api/mindmaps/{m['id']}", headers=nur.h).status_code == 404
    ops(client, nur, m["id"], add("root", "x", "чужое"), code=404)

    api.share(jack, "direction", d["id"], NUR_EMAIL, "view")
    seen = listed(client, nur)[m["id"]]
    assert seen["access"] == "view" and seen["owner"]["id"] == jack.id
    ops(client, nur, m["id"], add("root", "x", "чужое"), code=403)       # смотреть — не править

    api.share(jack, "direction", d["id"], NUR_EMAIL, "edit")             # смена права
    assert listed(client, nur)[m["id"]]["access"] == "edit"
    res = ops(client, nur, m["id"], add("root", "x", "Нурлан добавил"))
    assert res["applied"] == 1 and res["version"] == 1
    assert "Нурлан добавил" in texts(ok(client.get(f"/api/mindmaps/{m['id']}", headers=jack.h))["data"])


def test_project_share_does_not_open_direction_maps(client, api, jack, nur):
    """Доступ к одному проекту делает направление «обложкой» (via) — карты направления он не открывает."""
    d = api.direction(jack, "Эмба")
    p = api.project(jack, d["id"], "Скважина 14")
    m = mindmap(client, jack, "Эмба", direction_id=d["id"])
    api.share(jack, "project", p["id"], NUR_EMAIL, "edit")
    assert m["id"] not in listed(client, nur)


def test_map_follows_task_access(client, api, jack, nur):
    t = api.task(jack, "Скважина 14")
    m = mindmap(client, jack, "По скважине", task_id=t["id"])
    api.share(jack, "task", t["id"], NUR_EMAIL, "view")
    assert listed(client, nur)[m["id"]]["access"] == "view"


def test_share_map_itself(client, api, jack, nur, aida):
    m = mindmap(client, jack, "Идеи")
    s = api.share(jack, "mindmap", m["id"], NUR_EMAIL, "edit")
    assert s["entity_type"] == "mindmap"
    assert listed(client, nur)[m["id"]]["access"] == "edit"
    assert m["id"] not in listed(client, aida)
    # раздел «Общие» показывает карту
    rows = ok(client.get("/api/shares/with-me", headers=nur.h))
    assert [(r["entity_type"], r["entity_id"], r["name"]) for r in rows] == [("mindmap", m["id"], "Идеи")]
    # делиться дальше, удалять и перепривязывать — только владелец
    r = client.post("/api/shares", json={"entity_type": "mindmap", "entity_id": m["id"], "email": AIDA_EMAIL, "permission": "view"}, headers=nur.h)
    assert r.status_code == 403
    assert client.delete(f"/api/mindmaps/{m['id']}", headers=nur.h).status_code == 403
    d = api.direction(nur, "Своё у Нурлана")
    assert client.put(f"/api/mindmaps/{m['id']}/link", json={"direction_id": d["id"]}, headers=nur.h).status_code == 403
    # а править содержимое можно
    ops(client, nur, m["id"], {"type": "title", "title": "Идеи v2"})
    assert listed(client, jack)[m["id"]]["title"] == "Идеи v2"


def test_owner_relinks_and_delete_cleans_shares(client, api, jack, nur, db):
    from sqlalchemy import select
    d = api.direction(jack, "Снабжение")
    m = mindmap(client, jack, "Карта")
    api.share(jack, "mindmap", m["id"], NUR_EMAIL, "view")
    out = ok(client.put(f"/api/mindmaps/{m['id']}/link", json={"direction_id": d["id"]}, headers=jack.h))
    assert out["direction_id"] == d["id"] and out["access"] == "owner"
    # чужое направление, которое мне не открыто, к карте не привязать
    other = api.direction(nur, "Нурлана")
    assert client.put(f"/api/mindmaps/{m['id']}/link", json={"direction_id": other["id"]}, headers=jack.h).status_code == 404
    ok(client.delete(f"/api/mindmaps/{m['id']}", headers=jack.h), 204)
    assert db.scalars(select(models.Share).where(models.Share.entity_type == "mindmap")).all() == []


def test_sharing_map_moves_personal_direction_to_org(client, api, jack):
    d = api.direction(jack, "Личное направление")
    m = mindmap(client, jack, "Карта", direction_id=d["id"])
    s = api.share(jack, "mindmap", m["id"], NUR_EMAIL, "view")
    assert s["space_moved"] == ["Личное направление"]


def test_mcp_lists_shared_maps(client, api, jack, nur, db):
    m = mindmap(client, jack, "Общая карта")
    api.share(jack, "mindmap", m["id"], NUR_EMAIL, "view")
    u = db.get(models.User, nur.id)
    assert "Общая карта" in [x["title"] for x in mcp_tools.t_list_mindmaps(db, u, {})["mindmaps"]]


# ── операции: правки двоих не затирают друг друга ────────────────────────────

def test_two_editors_both_changes_survive(client, api, jack, nur):
    m = mindmap(client, jack, "ГРП")
    api.share(jack, "mindmap", m["id"], NUR_EMAIL, "edit")
    # оба открыли версию 0 и правят одновременно — каждый своё
    ops(client, jack, m["id"], add("root", "a", "Насосы"), batch="j1")
    res = ops(client, nur, m["id"], add("root", "b", "Химия"), batch="n1")
    assert res["version"] == 2
    assert texts(res["data"]) == ["ГРП", "Насосы", "Химия"]
    # одно поле одного узла — выигрывает последний, остальные поля целы
    ops(client, jack, m["id"], {"type": "set", "id": "a", "fields": {"text": "Насосы ГРП", "priority": 2}})
    res = ops(client, nur, m["id"], {"type": "set", "id": "a", "fields": {"text": "Насосы (Нурлан)"}})
    a = res["data"]["children"][0]
    assert a["text"] == "Насосы (Нурлан)" and a["priority"] == 2


def test_stale_ops_are_skipped_not_failed(client, jack):
    m = mindmap(client, jack, "Карта")
    ops(client, jack, m["id"], add("root", "a", "A"), add("a", "a1", "A1"), {"type": "link_add", "link": {"id": "L", "from": "a1", "to": "root"}})
    # ветку удалили — связь в неё ушла вместе с ней
    res = ops(client, jack, m["id"], {"type": "remove", "id": "a"})
    assert res["data"]["links"] == [] and texts(res["data"]) == ["Карта"]
    # кто-то ещё правил узел, которого уже нет, — пропуск, не ошибка; версия не растёт
    res = ops(client, jack, m["id"], {"type": "set", "id": "a1", "fields": {"text": "поздно"}}, add("a", "a2"))
    assert res["applied"] == 0 and res["version"] == 2
    assert [s["reason"] for s in res["skipped"]] == ["узла уже нет", "родителя уже нет"]


def test_ops_shapes(client, jack):
    m = mindmap(client, jack, "Карта")
    ops(client, jack, m["id"], {"type": "drop_table"}, code=400)
    ops(client, jack, m["id"], {"type": "set", "id": "root", "fields": {"owner_id": 5}}, code=400)
    ops(client, jack, m["id"], {"type": "set", "id": "root", "fields": {"priority": 7}}, code=400)
    ops(client, jack, m["id"], add("root", "a", "x" * 2001), code=400)
    ops(client, jack, m["id"], {"type": "remove", "id": "root"})   # корень не удаляется — пропуск
    res = ops(client, jack, m["id"], add("root", "a", "A"), add("a", "b", "B"), {"type": "move", "id": "a", "parent": "b"})
    assert res["skipped"][0]["reason"] == "нельзя перенести ветку внутрь неё самой"
    # снять поле = вернуть «как по умолчанию»: в JSON его больше нет
    ops(client, jack, m["id"], {"type": "set", "id": "a", "fields": {"color": "#2F6FED", "priority": 3}})
    res = ops(client, jack, m["id"], {"type": "set", "id": "a", "fields": {"color": None, "priority": 0}})
    assert set(res["data"]["children"][0]) == {"id", "text", "children"}


def test_empty_legacy_map_gets_root(client, jack):
    m = mindmap(client, jack, "Старая", data={})
    res = ops(client, jack, m["id"], add("root", "a", "Первый"))
    assert res["data"]["id"] == "root" and texts(res["data"]) == ["Старая", "Первый"]


def test_put_with_stale_version_is_409(client, jack):
    m = mindmap(client, jack, "Карта")
    ops(client, jack, m["id"], add("root", "a", "A"))
    body = {"title": "Карта", "data": {"id": "root", "text": "Карта", "children": []}}
    r = client.put(f"/api/mindmaps/{m['id']}", json={**body, "version": 0}, headers=jack.h)
    assert r.status_code == 409
    # без версии — как у старых клиентов: замена целиком
    out = ok(client.put(f"/api/mindmaps/{m['id']}", json=body, headers=jack.h))
    assert out["version"] == 2 and texts(out["data"]) == ["Карта"]


# ── живой канал ──────────────────────────────────────────────────────────────

def ws_open(client, u, map_id):
    ws = client.websocket_connect(f"/api/mindmaps/{map_id}/live")
    s = ws.__enter__()
    s.send_text(json.dumps({"type": "auth", "token": issue_session(u.obj)}))
    return ws, s


def until(s, kind):
    for _ in range(10):
        msg = s.receive_json()
        if msg["type"] == kind:
            return msg
    raise AssertionError(f"не дождались {kind}")


def test_live_broadcasts_ops_and_presence(client, api, jack, nur):
    m = mindmap(client, jack, "Живая")
    api.share(jack, "mindmap", m["id"], NUR_EMAIL, "edit")
    cj, sj = ws_open(client, jack, m["id"])
    try:
        hello = until(sj, "hello")
        assert hello["version"] == 0 and hello["access"] == "owner" and [p["name"] for p in hello["peers"]] == [jack.name]
        cn, sn = ws_open(client, nur, m["id"])
        try:
            assert until(sn, "hello")["access"] == "edit"
            joined = until(sj, "presence")
            assert sorted(p["name"] for p in joined["peers"]) == sorted([jack.name, nur.name])
            # Нурлан выбрал узел и печатает — Жанибек видит, где
            sn.send_text(json.dumps({"type": "focus", "node": "root", "editing": True}))
            nur_peer = next(p for p in until(sj, "presence")["peers"] if p["user_id"] == nur.id)
            assert nur_peer["node"] == "root" and nur_peer["editing"] is True and nur_peer["color"].startswith("#")
            # правка Нурлана приходит Жанибеку сразу, с версией и id пачки
            ops(client, nur, m["id"], add("root", "a", "Новая ветка"), batch="nur-1")
            msg = until(sj, "ops")
            assert msg["version"] == 1 and msg["batch"] == "nur-1" and msg["by"]["id"] == nur.id
            assert msg["ops"][0]["node"]["text"] == "Новая ветка"
        finally:
            cn.__exit__(None, None, None)
        left = until(sj, "presence")
        assert [p["name"] for p in left["peers"]] == [jack.name]
        # удаление карты — тоже событие
        ok(client.delete(f"/api/mindmaps/{m['id']}", headers=jack.h), 204)
        assert until(sj, "deleted")["type"] == "deleted"
    finally:
        cj.__exit__(None, None, None)


@pytest.mark.parametrize("token", ["не-токен", None])
def test_live_rejects_bad_session(client, jack, token):
    m = mindmap(client, jack, "Карта")
    with client.websocket_connect(f"/api/mindmaps/{m['id']}/live") as s:
        s.send_text(json.dumps({"type": "auth", "token": token}))
        with pytest.raises(WebSocketDisconnect) as e:
            s.receive_json()
    assert e.value.code == live.CLOSE_UNAUTHORIZED


def test_live_hides_foreign_map(client, jack, nur):
    m = mindmap(client, jack, "Чужая")
    with client.websocket_connect(f"/api/mindmaps/{m['id']}/live") as s:
        s.send_text(json.dumps({"type": "auth", "token": issue_session(nur.obj)}))
        with pytest.raises(WebSocketDisconnect) as e:
            s.receive_json()
    assert e.value.code == live.CLOSE_GONE


def test_live_closes_when_access_revoked(client, api, jack, nur, monkeypatch):
    monkeypatch.setattr(live, "RECHECK_SEC", 0.05)
    m = mindmap(client, jack, "Карта")
    s = api.share(jack, "mindmap", m["id"], NUR_EMAIL, "view")
    with client.websocket_connect(f"/api/mindmaps/{m['id']}/live") as w:
        w.send_text(json.dumps({"type": "auth", "token": issue_session(nur.obj)}))
        until(w, "hello")
        ok(client.delete(f"/api/shares/{s['id']}", headers=jack.h), 204)
        with pytest.raises(WebSocketDisconnect) as e:
            for _ in range(50):
                w.receive_json()
    assert e.value.code == live.CLOSE_GONE
