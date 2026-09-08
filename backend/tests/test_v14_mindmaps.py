"""v1.4 — майндмапы через MCP: list_mindmaps / get_mindmap (только чтение).

Симптом владельца: «сделал майндмап, хочу показать его Claude, чтобы он сделал документ — а экспорта нет».
Проверяем через /mcp тем же путём, каким ходит Claude: карта приходит текстом-структурой со всем, что на ней есть.
"""
import json

from app import models
from tests.conftest import ok

TREE = {"id": "root", "text": "ГРП", "children": [
    {"id": "a", "text": "Насосы", "priority": 2, "children": [{"id": "a1", "text": "Импеллеры", "note": "критично", "children": []}]},
    {"id": "b", "text": "Химия", "collapsed": True, "children": [{"id": "b1", "text": "Гуар", "children": []}]},
], "links": [{"id": "L1", "from": "b", "to": "a1", "note": "зависит от"}, {"id": "L2", "from": "b", "to": "нет-такого"}]}


def rpc(client, u, tool, **args):
    r = client.post("/mcp", content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                 "params": {"name": tool, "arguments": args}}), headers=u.mcp_h)
    assert r.status_code == 200, r.text[:200]
    res = r.json()["result"]
    return json.loads(res["content"][0]["text"]), bool(res.get("isError"))


def must_ok(client, u, tool, **args):
    d, err = rpc(client, u, tool, **args)
    assert not err, f"{tool} → {d}"
    return d


def must_fail(client, u, tool, **args):
    d, err = rpc(client, u, tool, **args)
    assert err, f"{tool} должен был вернуть ошибку, а вернул {d}"
    return d


def mindmap(client, u, title, data=None, **kw):
    return ok(client.post("/api/mindmaps", json={"title": title, "data": data or {"id": "root", "text": title, "children": []}, **kw}, headers=u.h), 201)


def test_tools_are_listed(client, jack):
    r = client.post("/mcp", content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}), headers=jack.mcp_h)
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert {"list_mindmaps", "get_mindmap"} <= names


def test_get_mindmap_outline_has_everything(client, jack, api):
    d = api.direction(jack, "Снабжение")
    m = mindmap(client, jack, "ГРП", TREE, direction_id=d["id"])
    out = must_ok(client, jack, "get_mindmap", mindmap="грп")
    assert out["id"] == m["id"] and out["title"] == "ГРП" and out["direction"] == "Снабжение"
    assert out["nodes"] == 4 and out["links"] == 2 and "tree" not in out
    assert out["outline"] == "\n".join([
        "- Насосы (!!)",
        "  - Импеллеры [линия: критично]",
        "- Химия",                 # свёрнутая ветка раскрыта
        "  - Гуар",
        "",
        "Связи между узлами:",
        "- Химия → Импеллеры: зависит от",   # висячая связь L2 пропущена
        "",
        "(!) (!!) (!!!) — важность узла; [линия: …] — подпись на линии от родительского узла; → — связь-стрелка между узлами.",
    ])
    full = must_ok(client, jack, "get_mindmap", mindmap=str(m["id"]), include_tree=True)
    assert full["tree"] == TREE


def test_empty_and_legacy_maps(client, jack):
    mindmap(client, jack, "Пусто")
    out = must_ok(client, jack, "get_mindmap", mindmap="Пусто")
    assert out["outline"] == "(карта пока пустая)" and out["nodes"] == 0
    # карта без данных (старый формат) — не падаем
    legacy = mindmap(client, jack, "Старая", data={})
    out = must_ok(client, jack, "get_mindmap", mindmap=legacy["id"])
    assert out["central_topic"] == "Старая" and out["outline"] == "(карта пока пустая)"


def test_list_filters_and_privacy(client, jack, nur, api):
    d = api.direction(jack, "Эмба")
    t = api.task(jack, "Скважина 14", direction_ids=[d["id"]])
    mindmap(client, jack, "Карта Эмбы", direction_id=d["id"])
    mindmap(client, jack, "Карта скважины", task_id=t["id"])
    mindmap(client, jack, "Своя")
    mindmap(client, nur, "Карта Нурлана")
    assert {m["title"] for m in must_ok(client, jack, "list_mindmaps")["mindmaps"]} == {"Своя", "Карта скважины", "Карта Эмбы"}
    assert [m["title"] for m in must_ok(client, jack, "list_mindmaps", direction="эмба")["mindmaps"]] == ["Карта Эмбы"]
    by_task = must_ok(client, jack, "list_mindmaps", task="скважина 14")["mindmaps"]
    assert [m["title"] for m in by_task] == ["Карта скважины"] and by_task[0]["task"] == "Скважина 14"
    # чужие карты не видны и не читаются — даже по id
    assert [m["title"] for m in must_ok(client, nur, "list_mindmaps")["mindmaps"]] == ["Карта Нурлана"]
    jack_map_id = must_ok(client, jack, "list_mindmaps", direction="Эмба")["mindmaps"][0]["id"]
    err = must_fail(client, nur, "get_mindmap", mindmap=jack_map_id)
    assert "не найдено" in err["error"] and "list_mindmaps" in err["hint"]


def test_ambiguous_and_missing(client, jack):
    mindmap(client, jack, "План ГРП север")
    mindmap(client, jack, "План ГРП юг")
    err = must_fail(client, jack, "get_mindmap", mindmap="план грп")
    assert "несколько совпадений" in err["error"] and "север" in err["error"] and "юг" in err["error"]
    assert must_ok(client, jack, "get_mindmap", mindmap="План ГРП юг")["title"] == "План ГРП юг"
    err = must_fail(client, jack, "get_mindmap", mindmap="Бурение")
    assert "не найдено" in err["error"]
    err = must_fail(client, jack, "get_mindmap")
    assert "не указано" in err["error"]


def test_read_only_and_deleted_direction(client, jack, api, db):
    d = api.direction(jack, "Временное")
    m = mindmap(client, jack, "Карта", TREE, direction_id=d["id"])
    ok(client.delete(f"/api/directions/{d['id']}", headers=jack.h), 204)   # направление в корзине
    out = must_ok(client, jack, "get_mindmap", mindmap=m["id"])
    assert out["direction"] is None and out["nodes"] == 4
    assert db.get(models.MindMap, m["id"]).data == TREE   # чтение ничего не меняет
