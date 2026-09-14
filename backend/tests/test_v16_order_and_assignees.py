"""v1.6: ручной порядок проектов и задач (перетаскивание) и ответственные в выдаче задач.

Правила корзины v1.6 проверяются в test_v08_softdelete.py (задачи уходят и возвращаются вместе с контейнером).
"""
from tests.conftest import NUR_EMAIL, link_person, ok


# ═══════════════════════ Порядок (перетаскивание) ═══════════════════════

def test_projects_reorder(client, api, jack):
    d = api.direction(jack, "Эмба")
    a = api.project(jack, d["id"], "А"); b = api.project(jack, d["id"], "Б"); c = api.project(jack, d["id"], "В")
    assert [x["id"] for x in ok(client.get("/api/projects", headers=jack.h))] == [a["id"], b["id"], c["id"]]
    out = ok(client.post("/api/projects/reorder", json={"ids": [c["id"], a["id"], b["id"]]}, headers=jack.h))
    assert [x["id"] for x in out] == [c["id"], a["id"], b["id"]]
    assert [x["sort_order"] for x in out] == [0, 1, 2]
    # порядок держится между запросами
    assert [x["id"] for x in ok(client.get("/api/projects", headers=jack.h))] == [c["id"], a["id"], b["id"]]


def test_tasks_reorder(client, api, jack):
    d = api.direction(jack, "Эмба")
    p = api.project(jack, d["id"], "Договор")
    t1 = api.task(jack, "Первая", project_id=p["id"], priority=1)
    t2 = api.task(jack, "Вторая", project_id=p["id"], priority=2)
    t3 = api.task(jack, "Третья", project_id=p["id"], priority=3)
    assert [x["id"] for x in ok(client.get(f"/api/tasks?project_id={p['id']}", headers=jack.h))] == [t1["id"], t2["id"], t3["id"]]
    ok(client.post("/api/tasks/reorder", json={"ids": [t3["id"], t1["id"], t2["id"]]}, headers=jack.h))
    got = ok(client.get(f"/api/tasks?project_id={p['id']}", headers=jack.h))
    assert [x["id"] for x in got] == [t3["id"], t1["id"], t2["id"]], "ручной порядок важнее приоритета"
    assert [x["sort_order"] for x in got] == [0, 1, 2]


def test_reorder_skips_foreign_ids(client, api, db, jack, nur):
    """Чужая и недоступная задача молча пропускается — перетаскивание не падает из-за одной строки."""
    d = api.direction(jack, "Эмба")
    mine = api.task(jack, "Моя", direction_ids=[d["id"]])
    d_nur = api.direction(nur, "Чужое")
    foreign = api.task(nur, "Чужая", direction_ids=[d_nur["id"]])
    out = ok(client.post("/api/tasks/reorder", json={"ids": [foreign["id"], mine["id"], 999999]}, headers=jack.h))
    assert [x["id"] for x in out] == [mine["id"]]
    db.expire_all()
    from app import models
    assert db.get(models.Task, mine["id"]).sort_order == 0, "нумерация идёт только по доступным id"
    assert db.get(models.Task, foreign["id"]).sort_order == 0, "чужая задача не тронута"


def test_view_only_project_not_reordered(client, api, jack, nur):
    d = api.direction(jack, "Эмба")
    p = api.project(jack, d["id"], "Договор")
    api.share(jack, "direction", d["id"], NUR_EMAIL, "view")
    p2 = api.project(nur, api.direction(nur, "Своё")["id"], "Своё")
    out = ok(client.post("/api/projects/reorder", json={"ids": [p["id"], p2["id"]]}, headers=nur.h))
    assert [x["id"] for x in out if x["sort_order"]] == []
    assert ok(client.get(f"/api/projects/{p['id']}", headers=nur.h))["sort_order"] == 0


# ═══════════════════════ Ответственные в выдаче ═══════════════════════

def test_task_carries_assignees(client, api, db, jack, aida):
    pa = link_person(db, aida)
    t = api.task(jack, "Согласовать КП")
    dele = ok(client.post("/api/delegations", json={"task_id": t["id"], "person_id": pa, "comment": "до пятницы"}, headers=jack.h), 201)
    got = api.get_task(jack, t["id"])
    assert got["assignees"] == [{"delegation_id": dele["id"], "person_id": pa, "name": aida.name,
                                 "status": "open", "check_at": None, "comment": "до пятницы"}], got["assignees"]
    # и в списке тоже — Action Tracker не должен ходить за поручениями отдельно
    row = next(x for x in ok(client.get("/api/tasks", headers=jack.h)) if x["id"] == t["id"])
    assert [a["name"] for a in row["assignees"]] == [aida.name]


def test_assignees_open_first_and_no_duplicates(client, api, db, jack, aida, nur):
    pa, pn = link_person(db, aida), link_person(db, nur)
    t = api.task(jack, "Две головы")
    d1 = ok(client.post("/api/delegations", json={"task_id": t["id"], "person_id": pa}, headers=jack.h), 201)
    ok(client.post("/api/delegations", json={"task_id": t["id"], "person_id": pn}, headers=jack.h), 201)
    ok(client.post("/api/delegations", json={"task_id": t["id"], "person_id": pa}, headers=jack.h), 201)  # повтор тому же
    ok(client.put(f"/api/delegations/{d1['id']}/report", json={"status": "done", "report": "сделал"}, headers=jack.h))
    names = [a["name"] for a in api.get_task(jack, t["id"])["assignees"]]
    assert names == [nur.name, aida.name], "на человека одна строка, открытые поручения впереди"


def test_task_without_delegations_has_empty_assignees(api, jack):
    assert api.get_task(jack, api.task(jack, "Ничья")["id"])["assignees"] == []
