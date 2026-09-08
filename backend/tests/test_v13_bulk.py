"""v1.3 — create_tasks_bulk: пачка задач одним вызовом (переезд из Trello).

Симптом: доска на 80 карточек через create_task — 200+ вызовов, обрыв чата даёт дубли. Проверяем через /mcp
тем же путём, каким ходит Claude.
"""
import json

from sqlalchemy import select

from app import models
from tests.conftest import count


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


BOARD = [  # то, что Claude соберёт из экспорта Trello
    {"title": "Заказать уплотнения для насоса", "status": "backlog", "deadline": "2026-10-01",
     "description": "Метки: Снабжение. Карточка: https://trello.com/c/abc", "checklist": ["Собрать КП", "Согласовать с юристом, финансистом"]},
    {"title": "Ревизия блендера", "status": "in_progress", "priority": 2,
     "checklist": [{"text": "Снять импеллер", "done": True}, {"text": "Замерить зазоры", "done": False}]},
    {"title": "Ждём ответ поставщика", "status": "waiting"},
    {"title": "Отчёт за август", "status": "done", "deadline": "2026-08-31"},
]


def test_bulk_creates_everything_in_one_call(client, jack, db):
    d = must_ok(client, jack, "create_tasks_bulk", tasks=BOARD, directions=["Снабжение"], project="Доска Trello",
                create_direction_if_missing=True, create_project_if_missing=True)
    assert d["created"] == 4 and d["skipped"] == [] and d["project"] == "Доска Trello" and d["directions"] == ["Снабжение"]
    assert [t["status_ru"] for t in d["tasks"]] == ["бэклог", "в работе", "ждём", "выполнено"]
    assert any("в прошлом" in w for w in d["warnings"])   # дедлайн 2026-08-31
    tasks = {t.title: t for t in db.scalars(select(models.Task)).all()}
    assert set(tasks) == {x["title"] for x in BOARD}
    t1 = tasks["Заказать уплотнения для насоса"]
    assert t1.project.name == "Доска Trello" and [x.name for x in t1.directions] == ["Снабжение"]
    assert t1.deadline.isoformat() == "2026-10-01" and t1.description.startswith("Метки: Снабжение")
    # запятая внутри пункта не разбивает его
    assert [c["text"] for c in t1.checklist] == ["Собрать КП", "Согласовать с юристом, финансистом"]
    t2 = tasks["Ревизия блендера"]
    assert t2.priority == 2 and [(c["text"], c["done"]) for c in t2.checklist] == [("Снять импеллер", True), ("Замерить зазоры", False)]
    assert all(c["id"] for c in t2.checklist)
    assert tasks["Отчёт за август"].status == models.TaskStatus.done
    # видно и через обычный список
    lst = must_ok(client, jack, "list_tasks", project="Доска Trello", include_done=True)
    assert len(lst["tasks"]) == 4


def test_bulk_repeat_skips_duplicates(client, jack, db):
    """Обрыв чата → повтор того же вызова не создаёт дублей; новые карточки в повторе добавляются."""
    must_ok(client, jack, "create_tasks_bulk", tasks=BOARD, directions=["Снабжение"], project="Доска",
            create_direction_if_missing=True, create_project_if_missing=True)
    again = must_ok(client, jack, "create_tasks_bulk", tasks=BOARD + [{"title": "Новая карточка"}], directions=["Снабжение"], project="Доска")
    assert again["created"] == 1 and again["tasks"][0]["title"] == "Новая карточка"
    assert len(again["skipped"]) == 4 and all(s["existing_id"] for s in again["skipped"])
    assert count(db, models.Task) == 5
    # тот же заголовок в ДРУГОМ проекте — не дубль
    other = must_ok(client, jack, "create_tasks_bulk", tasks=[{"title": "Ревизия блендера"}], directions=["Снабжение"], project="Другая доска",
                    create_project_if_missing=True)
    assert other["created"] == 1
    # skip_duplicates=false — создаёт, но предупреждает не о пропуске
    forced = must_ok(client, jack, "create_tasks_bulk", tasks=[{"title": "Ревизия блендера"}], directions=["Снабжение"], project="Доска", skip_duplicates=False)
    assert forced["created"] == 1 and forced["skipped"] == []


def test_bulk_all_or_nothing(client, jack, db):
    bad = BOARD[:2] + [{"title": "Сломанная", "status": "в процессе размышлений"}] + BOARD[2:]
    d = must_fail(client, jack, "create_tasks_bulk", tasks=bad, directions=["Снабжение"], create_direction_if_missing=True)
    assert "tasks[2]" in d["error"] and "Сломанная" in d["error"] and "статус" in d["error"].lower()
    assert "Ничего из этой пачки не записано" in d["hint"]
    assert count(db, models.Task) == 0
    # направление, созданное по флагу в том же вызове, тоже откатилось
    assert count(db, models.Direction) == 0
    # без title
    d = must_fail(client, jack, "create_tasks_bulk", tasks=[{"title": "ок"}, {"description": "без названия"}])
    assert "tasks[1]" in d["error"] and count(db, models.Task) == 0
    # неизвестный человек без флага — вся пачка стоит
    d = must_fail(client, jack, "create_tasks_bulk", tasks=[{"title": "А"}, {"title": "Б", "assign_to": ["Неизвестный Человек"]}])
    assert "tasks[1]" in d["error"] and count(db, models.Task) == 0
    # с флагом — создаётся и человек, и поручение
    ok = must_ok(client, jack, "create_tasks_bulk", tasks=[{"title": "А"}, {"title": "Б", "assign_to": ["Неизвестный Человек"], "comment": "к пятнице"}],
                 create_person_if_missing=True)
    assert ok["created"] == 2
    t = db.scalar(select(models.Task).where(models.Task.title == "Б"))
    assert [d.person.name for d in t.delegations] == ["Неизвестный Человек"] and t.delegations[0].comment == "к пятнице"


def test_bulk_dry_run_writes_nothing(client, jack, db):
    d = must_ok(client, jack, "create_tasks_bulk", tasks=BOARD, directions=["Снабжение"], project="Доска", dry_run=True,
                create_direction_if_missing=True, create_project_if_missing=True)
    assert d["dry_run"] is True and d["would_create"] == 4 and "created" not in d
    assert d["tasks"][1] == {"title": "Ревизия блендера", "status_ru": "в работе", "deadline": None, "checklist": 2, "assignees": []}
    assert count(db, models.Task) == 0 and count(db, models.Project) == 0 and count(db, models.Direction) == 0
    # после dry_run обычный вызов работает как ни в чём не бывало
    real = must_ok(client, jack, "create_tasks_bulk", tasks=BOARD, directions=["Снабжение"], project="Доска",
                   create_direction_if_missing=True, create_project_if_missing=True)
    assert real["created"] == 4


def test_bulk_limits_and_formats(client, jack, db):
    d = must_fail(client, jack, "create_tasks_bulk", tasks=[{"title": f"Задача {i}"} for i in range(51)])
    assert "не больше 50" in d["error"] and "по частям" in d["hint"].lower() or "разбейте" in d["hint"].lower()
    assert count(db, models.Task) == 0
    for bad in ([], None, "просто строка", 5):
        must_fail(client, jack, "create_tasks_bulk", tasks=bad)
    # tasks JSON-строкой (некоторые клиенты так присылают) и один объект вместо массива
    ok = must_ok(client, jack, "create_tasks_bulk", tasks=json.dumps([{"title": "Из строки"}]))
    assert ok["created"] == 1
    ok = must_ok(client, jack, "create_tasks_bulk", tasks={"title": "Один объект"})
    assert ok["created"] == 1
    # чеклист строкой — по строкам; повтор пункта схлопывается
    ok = must_ok(client, jack, "create_tasks_bulk", tasks=[{"title": "Ч", "checklist": "первый\nвторой\nпервый"}])
    t = db.scalar(select(models.Task).where(models.Task.title == "Ч"))
    assert [c["text"] for c in t.checklist] == ["первый", "второй"]
    # ровно 50 — можно
    ok = must_ok(client, jack, "create_tasks_bulk", tasks=[{"title": f"Задача {i}"} for i in range(50)])
    assert ok["created"] == 50


def test_bulk_respects_view_only_access(client, jack, nur, api, db):
    """Направление открыто Нурлану только на просмотр — пачку туда не положить; с правом edit — задачи принадлежат владельцу доски."""
    d = api.direction(jack, "Эмба")
    api.share(jack, "direction", d["id"], nur.email, "view")
    err = must_fail(client, nur, "create_tasks_bulk", tasks=[{"title": "Чужая"}], directions=["Эмба"])
    assert "только на просмотр" in err["error"] and count(db, models.Task) == 0
    api.share(jack, "direction", d["id"], nur.email, "edit")
    ok = must_ok(client, nur, "create_tasks_bulk", tasks=[{"title": "Чужая"}, {"title": "Ещё"}], directions=["Эмба"])
    assert ok["created"] == 2
    assert {t.owner_id for t in db.scalars(select(models.Task)).all()} == {jack.id}


def test_bulk_without_container_dedupes_among_loose_tasks(client, jack, db):
    """Без направления и проекта дубли ищутся среди моих задач без направлений; задача с тем же названием в проекте не мешает."""
    must_ok(client, jack, "create_task", title="Позвонить поставщику", directions=["Снабжение"], create_direction_if_missing=True)
    ok = must_ok(client, jack, "create_tasks_bulk", tasks=[{"title": "Позвонить поставщику"}, {"title": "Свободная"}])
    assert ok["created"] == 2
    again = must_ok(client, jack, "create_tasks_bulk", tasks=[{"title": "позвонить поставщику"}, {"title": "СВОБОДНАЯ"}])
    assert again["created"] == 0 and len(again["skipped"]) == 2


def test_create_task_still_works_after_refactor(client, jack, db):
    """create_task разобран на общие куски — поведение прежнее: проект создаётся по флагу, направление проекта привязывается."""
    d = must_ok(client, jack, "create_task", title="Одна", directions=["Эмба"], project="Договор", deadline="2026-12-01",
                create_direction_if_missing=True, create_project_if_missing=True, assign_to=["Нурлан"], create_person_if_missing=True)
    t = d["task"]
    assert t["project"] == "Договор" and t["directions"] == ["Эмба"] and t["assignees"] == ["Нурлан"] and d["link"].endswith(f"?task={t['id']}")
    assert count(db, models.Task) == 1


# ── сквозной сценарий: экспорт Trello → пачка ─────────────────────────────────

TRELLO = {  # структура настоящего экспорта «Меню → Печать и экспорт → Экспорт в JSON» (укорочена)
    "name": "Снабжение ГРП", "url": "https://trello.com/b/Ab1/snabzhenie",
    "lists": [{"id": "L1", "name": "Надо сделать", "closed": False}, {"id": "L2", "name": "В работе", "closed": False},
              {"id": "L3", "name": "Ждём поставку", "closed": False}, {"id": "L4", "name": "Готово", "closed": False},
              {"id": "L5", "name": "Старое", "closed": True}],
    "labels": [{"id": "lb1", "name": "Срочно", "color": "red"}, {"id": "lb2", "name": "Насосы", "color": "blue"}],
    "members": [{"id": "M1", "fullName": "Ержан Сапаров"}, {"id": "M2", "fullName": "Nurlan Abilkhanov"}],
    "cards": [
        {"id": "c1", "name": "Заказать уплотнения для насоса", "desc": "Комплект на 2 насоса", "idList": "L1", "due": "2026-10-01T09:00:00.000Z",
         "dueComplete": False, "closed": False, "idLabels": ["lb1", "lb2"], "idMembers": ["M1"], "idChecklists": ["ck1"], "shortUrl": "https://trello.com/c/c1"},
        {"id": "c2", "name": "Ревизия блендера", "desc": "", "idList": "L2", "due": None, "closed": False, "idLabels": [], "idMembers": ["M2"], "idChecklists": [], "shortUrl": "https://trello.com/c/c2"},
        {"id": "c3", "name": "Фильтры для НС-3", "desc": "", "idList": "L3", "due": "2026-09-20T09:00:00.000Z", "closed": False, "idLabels": [], "idMembers": [], "idChecklists": [], "shortUrl": "https://trello.com/c/c3"},
        {"id": "c4", "name": "Отчёт за август", "desc": "", "idList": "L4", "due": "2026-08-31T09:00:00.000Z", "dueComplete": True, "closed": False, "idLabels": [], "idMembers": [], "idChecklists": [], "shortUrl": "https://trello.com/c/c4"},
        {"id": "c5", "name": "Архивная карточка", "desc": "", "idList": "L1", "due": None, "closed": True, "idLabels": [], "idMembers": [], "idChecklists": [], "shortUrl": "https://trello.com/c/c5"},
        {"id": "c6", "name": "В закрытой колонке", "desc": "", "idList": "L5", "due": None, "closed": False, "idLabels": [], "idMembers": [], "idChecklists": [], "shortUrl": "https://trello.com/c/c6"},
    ],
    "checklists": [{"id": "ck1", "idCard": "c1", "name": "Шаги", "checkItems": [
        {"name": "Собрать КП", "state": "complete"}, {"name": "Согласовать с юристом, финансистом", "state": "incomplete"}]}],
    "actions": [{"type": "commentCard", "date": "2026-09-01T08:00:00.000Z", "data": {"card": {"id": "c1"}, "text": "Поставщик обещал КП к пятнице"},
                 "memberCreator": {"fullName": "Ержан Сапаров"}}],
}
STATUS_MAP = {"Надо сделать": "backlog", "В работе": "in_progress", "Ждём поставку": "waiting", "Готово": "done"}   # согласовано с человеком


def trello_to_bulk(board: dict, status_map: dict, skip_archived=True) -> list[dict]:
    """То, что делает Claude в чате, прочитав экспорт (описано в инструкции «Переезд из Trello»)."""
    lists = {l["id"]: l for l in board["lists"]}
    labels = {l["id"]: l["name"] for l in board["labels"]}
    members = {m["id"]: m["fullName"] for m in board["members"]}
    checklists = {}
    for ck in board["checklists"]:
        checklists.setdefault(ck["idCard"], []).extend({"text": it["name"], "done": it["state"] == "complete"} for it in ck["checkItems"])
    comments = {}
    for act in board["actions"]:
        if act["type"] == "commentCard":
            comments.setdefault(act["data"]["card"]["id"], []).append(f"[{act['date'][:10]} {act['memberCreator']['fullName']}] {act['data']['text']}")
    out = []
    for c in board["cards"]:
        lst = lists[c["idList"]]
        if skip_archived and (c["closed"] or lst["closed"]):
            continue
        desc = [c["desc"]] if c["desc"] else []
        if c["idLabels"]:
            desc.append("Метки: " + ", ".join(labels[x] for x in c["idLabels"]))
        desc.extend(comments.get(c["id"], []))
        desc.append(f"Из Trello: {c['shortUrl']} (колонка «{lst['name']}»)")
        item = {"title": c["name"], "description": "\n".join(desc), "status": status_map[lst["name"]]}
        if c.get("due"):
            item["deadline"] = c["due"][:10]
        if c["id"] in checklists:
            item["checklist"] = checklists[c["id"]]
        if c["idMembers"]:
            item["assign_to"] = [members[m] for m in c["idMembers"]]
        out.append(item)
    return out


def test_trello_export_end_to_end(client, jack, db):
    items = trello_to_bulk(TRELLO, STATUS_MAP)
    assert [x["title"] for x in items] == ["Заказать уплотнения для насоса", "Ревизия блендера", "Фильтры для НС-3", "Отчёт за август"]
    # шаг 1 — план человеку
    plan = must_ok(client, jack, "create_tasks_bulk", tasks=items, directions=["Снабжение"], project=TRELLO["name"], dry_run=True,
                   create_direction_if_missing=True, create_project_if_missing=True, create_person_if_missing=True)
    assert plan["would_create"] == 4 and plan["tasks"][0]["assignees"] == ["Ержан Сапаров"] and plan["tasks"][0]["checklist"] == 2
    assert count(db, models.Task) == 0 and count(db, models.Person) == 0
    # шаг 2 — «да, создавай»
    res = must_ok(client, jack, "create_tasks_bulk", tasks=items, directions=["Снабжение"], project=TRELLO["name"],
                  create_direction_if_missing=True, create_project_if_missing=True, create_person_if_missing=True)
    assert res["created"] == 4 and res["project"] == "Снабжение ГРП"
    t = db.scalar(select(models.Task).where(models.Task.title == "Заказать уплотнения для насоса"))
    assert t.status == models.TaskStatus.backlog and t.deadline.isoformat() == "2026-10-01"
    assert "Метки: Срочно, Насосы" in t.description and "Поставщик обещал КП" in t.description and "https://trello.com/c/c1" in t.description
    assert [(c["text"], c["done"]) for c in t.checklist] == [("Собрать КП", True), ("Согласовать с юристом, финансистом", False)]
    assert [d.person.name for d in t.delegations] == ["Ержан Сапаров"]
    t2 = db.scalar(select(models.Task).where(models.Task.title == "Ревизия блендера"))
    assert t2.status == models.TaskStatus.in_progress and [d.person.name for d in t2.delegations] == ["Nurlan Abilkhanov"]
    assert db.scalar(select(models.Task).where(models.Task.title == "Отчёт за август")).status == models.TaskStatus.done
    # шаг 3 — чат оборвался, человек сказал «продолжай» → тот же вызов, дублей нет
    again = must_ok(client, jack, "create_tasks_bulk", tasks=items, directions=["Снабжение"], project=TRELLO["name"])
    assert again["created"] == 0 and len(again["skipped"]) == 4 and count(db, models.Task) == 4
    # сводка по проекту видит всё
    lst = must_ok(client, jack, "list_tasks", project="Снабжение ГРП", include_done=True)
    assert len(lst["tasks"]) == 4


def test_bulk_fits_in_request_limit(client, jack, db):
    """50 карточек с описаниями и чеклистами — в один запрос (лимит тела /mcp 256 КБ)."""
    items = [{"title": f"Карточка {i} " + "с длинным названием", "description": ("Описание " * 60) + f"\nИз Trello: https://trello.com/c/x{i}",
              "status": "backlog", "checklist": [{"text": f"Пункт {j} с текстом", "done": j % 2 == 0} for j in range(8)]} for i in range(50)]
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "create_tasks_bulk", "arguments": {"tasks": items}}}, ensure_ascii=False)
    assert len(body.encode()) < 256 * 1024, len(body.encode())
    r = client.post("/mcp", content=body.encode(), headers=jack.mcp_h)
    assert r.status_code == 200
    d = json.loads(r.json()["result"]["content"][0]["text"])
    assert d["created"] == 50 and count(db, models.Task) == 50
