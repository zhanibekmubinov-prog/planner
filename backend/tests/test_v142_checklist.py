"""v1.4.2 — чеклист через MCP: пункты не режутся по запятым, появился remove_checklist_items.

Симптом (задача 93): add_checklist_items из 7 пунктов сделал 27 обрывков — «Оператор 2 — опыт 0», «5–1 год».
Причина: общий разборщик списков _list делит и элементы массива по `,` / `;`. Убрать ошибочные пункты через Claude было нечем.
"""
import json

from app import models
from tests.conftest import link_person, ok

ITEMS = ["Оператор 2 — опыт 0,5–1 год", "Мастер ГРП; стаж от 3 лет", "Собрать КП, согласовать с юристом, финансистом"]


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


def texts(client, jack, tid):
    return [c["text"] for c in must_ok(client, jack, "get_task", task=str(tid))["checklist"]]


def test_items_with_commas_stay_whole(client, jack, api):
    t = api.task(jack, "Набор бригады")
    d = must_ok(client, jack, "add_checklist_items", task="Набор бригады", items=ITEMS)
    assert d["added"] == 3 and texts(client, jack, t["id"]) == ITEMS


def test_string_splits_only_by_newline(client, jack, api):
    t = api.task(jack, "Ремонт")
    must_ok(client, jack, "add_checklist_items", task=str(t["id"]), items="Снять импеллер, промыть\nЗамерить зазоры; записать\n\n")
    assert texts(client, jack, t["id"]) == ["Снять импеллер, промыть", "Замерить зазоры; записать"]


def test_objects_and_duplicates(client, jack, api):
    t = api.task(jack, "Разное")
    d = must_ok(client, jack, "add_checklist_items", task=str(t["id"]), items=[{"text": "Один, два"}, "Один, два", "  ", "Три"])
    assert d["added"] == 2 and d["skipped"] == ["Один, два"]
    assert texts(client, jack, t["id"]) == ["Один, два", "Три"]


def test_remove_by_text_part_and_id(client, jack, api, db):
    t = api.task(jack, "Чистка")
    must_ok(client, jack, "add_checklist_items", task=str(t["id"]), items=["Оператор 2 — опыт 0", "5–1 год", "Мастер ГРП", "Сварщик"])
    cl = must_ok(client, jack, "get_task", task=str(t["id"]))["checklist"]
    d = must_ok(client, jack, "remove_checklist_items", task=str(t["id"]), items=["5–1 год", "оператор 2", cl[3]["id"]])
    assert d["removed"] == ["5–1 год", "Оператор 2 — опыт 0", "Сварщик"] and d["left"] == 1
    assert texts(client, jack, t["id"]) == ["Мастер ГРП"]
    assert db.get(models.Task, t["id"]).checklist[0]["text"] == "Мастер ГРП"   # реально записано в базу


def test_remove_ambiguous_or_missing_changes_nothing(client, jack, api):
    t = api.task(jack, "Неясно")
    must_ok(client, jack, "add_checklist_items", task=str(t["id"]), items=["Оператор смены А", "Оператор смены Б", "Мастер"])
    err = must_fail(client, jack, "remove_checklist_items", task=str(t["id"]), items=["Мастер", "оператор"])
    assert "несколько совпадений" in err["error"] and "Ничего не убрано" in err["error"]
    err = must_fail(client, jack, "remove_checklist_items", task=str(t["id"]), items=["Электрик"])
    assert "не найден" in err["error"]
    err = must_fail(client, jack, "remove_checklist_items", task=str(t["id"]))
    assert "all=true" in err["error"]
    assert len(texts(client, jack, t["id"])) == 3


def test_remove_all_then_readd_cleanly(client, jack, api):
    """Сценарий починки задачи 93: снести обрывки и добавить пункты заново целыми."""
    t = api.task(jack, "Задача 93")
    must_ok(client, jack, "add_checklist_items", task=str(t["id"]), items=["Оператор 2 — опыт 0", "5–1 год", "Мастер"])
    d = must_ok(client, jack, "remove_checklist_items", task=str(t["id"]), all=True)
    assert d["left"] == 0 and len(d["removed"]) == 3
    must_fail(client, jack, "remove_checklist_items", task=str(t["id"]), all=True)   # пусто — «убирать нечего»
    must_ok(client, jack, "add_checklist_items", task=str(t["id"]), items=ITEMS)
    assert texts(client, jack, t["id"]) == ITEMS


def test_remove_permissions(client, jack, nur, api, db):
    t = api.task(jack, "Чужая")
    must_ok(client, jack, "add_checklist_items", task=str(t["id"]), items=["Пункт"])
    # Нурлану задача не видна вовсе; исполнитель (порученная задача) может отмечать, но не убирать
    must_fail(client, nur, "remove_checklist_items", task=str(t["id"]), all=True)
    pid = link_person(db, nur)
    ok(client.post("/api/delegations", json={"task_id": t["id"], "person_id": pid, "status": "open"}, headers=jack.h), 201)
    must_ok(client, nur, "check_item", task=str(t["id"]), item="Пункт")
    err = must_fail(client, nur, "remove_checklist_items", task=str(t["id"]), all=True)
    assert texts(client, jack, t["id"]) == ["Пункт"], err
