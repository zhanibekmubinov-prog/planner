"""v0.8: корзина (soft-delete), восстановление, удаление навсегда, «без направления», impact, люди — только админ.

Спецификация — /root/review/CONTRACT.md. Участники: jack — владелец, nur — коллега (edit), aida — коллега (view).
"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import models, trash
from tests.conftest import NUR_EMAIL, AIDA_EMAIL, count, link_person, ok


def _setup(api, jack, nur):
    """Направление D (Нурлану edit) → проект P (Аиде view) → задача T в проекте, задача T2 прямо в направлении."""
    d = api.direction(jack, "Эмба")
    p = api.project(jack, d["id"], "Договор")
    t = api.task(jack, "В проекте", project_id=p["id"])
    t2 = api.task(jack, "В направлении", direction_ids=[d["id"]])
    api.share(jack, "direction", d["id"], NUR_EMAIL, "edit")
    api.share(jack, "project", p["id"], AIDA_EMAIL, "view")
    return d, p, t, t2


def _mcp(client, u, tool, **args):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}, headers=u.mcp_h)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    return json.loads(res["content"][0]["text"]), res["isError"]


# ═══════════════════════ Задача ═══════════════════════

def test_task_delete_hides_everywhere_and_restore(client, api, db, jack, nur):
    d, p, t, t2 = _setup(api, jack, nur)
    api.share(jack, "task", t2["id"], NUR_EMAIL, "edit")
    ok(client.delete(f"/api/tasks/{t2['id']}", headers=jack.h), 204)
    # скрыта: карточка, списки, фильтр по направлению — и у владельца, и у редактора
    assert client.get(f"/api/tasks/{t2['id']}", headers=jack.h).status_code == 404
    assert client.get(f"/api/tasks/{t2['id']}", headers=nur.h).status_code == 404
    assert t2["id"] not in [x["id"] for x in ok(client.get("/api/tasks", headers=jack.h))]
    assert t2["id"] not in [x["id"] for x in ok(client.get(f"/api/tasks?direction_id={d['id']}", headers=nur.h))]
    # шара на задачу снята, запись жива в БД с deleted_at
    assert count(db, models.Share, models.Share.entity_type == "task") == 0
    row = db.get(models.Task, t2["id"]); assert row is not None and row.deleted_at is not None
    # в корзине
    tr = ok(client.get("/api/trash", headers=jack.h))
    assert [x["id"] for x in tr["tasks"]] == [t2["id"]] and tr["tasks"][0]["deleted_at"] and tr["directions"] == [] and tr["projects"] == []
    assert ok(client.get("/api/trash", headers=nur.h)) == {"directions": [], "projects": [], "tasks": []}
    # восстановление владельцем: задача снова в направлении, доступ по прямой шаре не вернулся (только через направление)
    back = ok(client.post(f"/api/tasks/{t2['id']}/restore", headers=jack.h))
    assert back["deleted_at"] is None and [x["id"] for x in back["directions"]] == [d["id"]]
    assert ok(client.get(f"/api/tasks/{t2['id']}", headers=nur.h))["access"] == "edit"   # через направление
    assert ok(client.get("/api/trash", headers=jack.h))["tasks"] == []


def test_task_restore_and_purge_only_by_owner(client, api, jack, nur):
    d, p, t, t2 = _setup(api, jack, nur)
    assert client.delete(f"/api/tasks/{t2['id']}", headers=nur.h).status_code == 403   # редактор — не владелец
    ok(client.delete(f"/api/tasks/{t2['id']}", headers=jack.h), 204)
    assert client.post(f"/api/tasks/{t2['id']}/restore", headers=nur.h).status_code == 404   # в корзине чужое не видно
    assert client.delete(f"/api/trash/task/{t2['id']}", headers=nur.h).status_code == 404
    assert client.delete(f"/api/trash/task/{t['id']}", headers=jack.h).status_code == 409   # живую навсегда нельзя


def test_task_in_trash_invisible_to_mcp_and_delegations(client, api, db, jack, aida):
    pa = link_person(db, aida)
    t = api.task(jack, "Поручено Аиде")
    ok(client.post("/api/delegations", json={"task_id": t["id"], "person_id": pa}, headers=jack.h), 201)
    ok(client.delete(f"/api/tasks/{t['id']}", headers=jack.h), 204)
    assert ok(client.get("/api/delegations?mine=true", headers=aida.h)) == []
    assert ok(client.get("/api/delegations", headers=jack.h)) == []
    assert client.get(f"/api/tasks/{t['id']}", headers=aida.h).status_code == 404
    data, err = _mcp(client, jack, "list_tasks", include_done=True)
    assert not err and all(x["id"] != t["id"] for x in data["tasks"]), data
    data, err = _mcp(client, aida, "list_tasks", scope="assigned_to_me")
    assert not err and data["count"] == 0, data


# ═══════════════════════ Проект ═══════════════════════

def test_project_delete_and_restore(client, api, db, jack, nur, aida):
    d, p, t, t2 = _setup(api, jack, nur)
    ok(client.delete(f"/api/projects/{p['id']}", headers=jack.h), 204)
    assert client.get(f"/api/projects/{p['id']}", headers=jack.h).status_code == 404
    assert ok(client.get(f"/api/projects?direction_id={d['id']}", headers=jack.h)) == []
    assert count(db, models.Share, models.Share.entity_type == "project") == 0
    # задача проекта жива, видна владельцу, направление сохранено; Аида (view на проект) её больше не видит
    got = api.get_task(jack, t["id"])
    assert [x["id"] for x in got["directions"]] == [d["id"]]
    assert client.get(f"/api/tasks/{t['id']}", headers=aida.h).status_code == 404
    # редактору направления проект тоже не виден и не редактируется
    assert client.put(f"/api/projects/{p['id']}", json={"direction_id": d["id"], "name": "x"}, headers=nur.h).status_code == 404
    # нельзя положить задачу в проект из корзины
    assert client.post("/api/tasks", json={"title": "в корзину", "project_id": p["id"], "direction_ids": [], "tool_ids": []}, headers=jack.h).status_code == 404
    tr = ok(client.get("/api/trash", headers=jack.h))
    assert [x["id"] for x in tr["projects"]] == [p["id"]] and tr["projects"][0]["deleted_at"]
    back = ok(client.post(f"/api/projects/{p['id']}/restore", headers=jack.h))
    assert back["deleted_at"] is None and back["access"] == "owner"
    assert api.get_task(jack, t["id"])["project_id"] == p["id"]
    assert [x["id"] for x in ok(client.get(f"/api/tasks?project_id={p['id']}", headers=jack.h))] == [t["id"]]


def test_project_restore_with_direction_in_trash_is_409(client, api, jack, nur):
    d, p, t, t2 = _setup(api, jack, nur)
    ok(client.delete(f"/api/directions/{d['id']}", headers=jack.h), 204)
    r = client.post(f"/api/projects/{p['id']}/restore", headers=jack.h)
    assert r.status_code == 409 and "направление" in r.json()["detail"].lower()
    ok(client.post(f"/api/directions/{d['id']}/restore", headers=jack.h))
    assert ok(client.get(f"/api/projects/{p['id']}", headers=jack.h))["deleted_at"] is None   # вернулся вместе с направлением


# ═══════════════════════ Направление ═══════════════════════

def test_direction_delete_cascades_to_projects_keeps_tasks(client, api, db, jack, nur, aida):
    d, p, t, t2 = _setup(api, jack, nur)
    other = api.direction(jack, "Другое")
    t3 = api.task(jack, "В двух направлениях", direction_ids=[d["id"], other["id"]])
    imp = ok(client.get(f"/api/directions/{d['id']}/impact", headers=jack.h))
    assert imp == {"projects": 1, "tasks": 3, "open_tasks": 3, "shares": 2}, imp
    ok(client.delete(f"/api/directions/{d['id']}", headers=jack.h), 204)
    assert client.get(f"/api/directions/{d['id']}", headers=jack.h).status_code == 404
    assert [x["id"] for x in ok(client.get("/api/directions", headers=jack.h))] == [other["id"]]
    assert ok(client.get("/api/directions", headers=nur.h)) == [] and ok(client.get("/api/projects", headers=aida.h)) == []
    assert count(db, models.Share) == 0
    db.expire_all()
    assert db.get(models.Project, p["id"]).deleted_at is not None
    # задачи живы: у t и t2 направлений не осталось (без направления), у t3 осталось «Другое»
    assert api.get_task(jack, t["id"])["directions"] == [] and api.get_task(jack, t2["id"])["directions"] == []
    assert [x["id"] for x in api.get_task(jack, t3["id"])["directions"]] == [other["id"]]
    # связи в БД сохранены — нужны для восстановления
    assert count(db, models.task_directions, models.task_directions.c.direction_id == d["id"]) == 3
    # «Без направления»
    orphans = {x["id"] for x in ok(client.get("/api/tasks?orphans=true", headers=jack.h))}
    assert orphans == {t["id"], t2["id"]}, orphans
    assert ok(client.get("/api/tasks?orphans=true", headers=nur.h)) == []
    # корзина: направление и проект (удалены одним действием)
    tr = ok(client.get("/api/trash", headers=jack.h))
    assert [x["id"] for x in tr["directions"]] == [d["id"]] and [x["id"] for x in tr["projects"]] == [p["id"]]
    # restore возвращает направление, проект и связи задач; доступ (шары) не возвращается
    back = ok(client.post(f"/api/directions/{d['id']}/restore", headers=jack.h))
    assert back["deleted_at"] is None
    assert ok(client.get(f"/api/projects/{p['id']}", headers=jack.h))["deleted_at"] is None
    assert [x["id"] for x in api.get_task(jack, t2["id"])["directions"]] == [d["id"]]
    assert api.get_task(jack, t["id"])["project_id"] == p["id"]
    assert ok(client.get("/api/tasks?orphans=true", headers=jack.h)) == []
    assert ok(client.get("/api/directions", headers=nur.h)) == []


def test_direction_restore_does_not_restore_separately_deleted_project(client, api, jack, nur):
    d, p, t, t2 = _setup(api, jack, nur)
    p2 = api.project(jack, d["id"], "Удалён раньше")
    ok(client.delete(f"/api/projects/{p2['id']}", headers=jack.h), 204)
    ok(client.delete(f"/api/directions/{d['id']}", headers=jack.h), 204)
    ok(client.post(f"/api/directions/{d['id']}/restore", headers=jack.h))
    ids = [x["id"] for x in ok(client.get(f"/api/projects?direction_id={d['id']}", headers=jack.h))]
    assert p["id"] in ids and p2["id"] not in ids, "проект, удалённый отдельно раньше, должен остаться в корзине"


def test_archived_status_unaffected(client, api, jack):
    d = api.direction(jack, "Архивное", status="archived")
    p = api.project(jack, d["id"], "Архивный проект", status="archived")
    assert d["id"] in [x["id"] for x in ok(client.get("/api/directions", headers=jack.h))]
    assert p["id"] in [x["id"] for x in ok(client.get("/api/projects", headers=jack.h))]
    assert ok(client.get("/api/trash", headers=jack.h)) == {"directions": [], "projects": [], "tasks": []}


# ═══════════════════════ Навсегда / очистка ═══════════════════════

def test_purge_one_and_all(client, api, db, jack, nur):
    d, p, t, t2 = _setup(api, jack, nur)
    ok(client.delete(f"/api/tasks/{t2['id']}", headers=jack.h), 204)
    ok(client.delete(f"/api/directions/{d['id']}", headers=jack.h), 204)
    assert client.delete("/api/trash/user/1", headers=jack.h).status_code == 400
    ok(client.delete(f"/api/trash/task/{t2['id']}", headers=jack.h), 204)
    db.expire_all()
    assert db.get(models.Task, t2["id"]) is None
    ok(client.delete("/api/trash", headers=jack.h), 204)
    db.expire_all()
    assert db.get(models.Direction, d["id"]) is None and db.get(models.Project, p["id"]) is None
    alive_t = db.get(models.Task, t["id"])
    assert alive_t is not None and alive_t.project_id is None and alive_t.deleted_at is None, "живая задача остаётся, теряет проект"
    assert count(db, models.task_directions) == 0 and count(db, models.Share) == 0
    assert ok(client.get("/api/trash", headers=jack.h)) == {"directions": [], "projects": [], "tasks": []}


def test_purge_trash_older_than_days(client, api, db, jack, nur):
    d, p, t, t2 = _setup(api, jack, nur)
    d_old = api.direction(jack, "Старое удалённое")
    ok(client.delete(f"/api/directions/{d_old['id']}", headers=jack.h), 204)
    ok(client.delete(f"/api/tasks/{t2['id']}", headers=jack.h), 204)
    row = db.get(models.Direction, d_old["id"])
    row.deleted_at = datetime.now(timezone.utc) - timedelta(days=40); db.commit()
    res = trash.purge_trash(db, older_than_days=30)
    assert res == {"tasks": 0, "projects": 0, "directions": 1}, res
    db.expire_all()
    assert db.get(models.Direction, d_old["id"]) is None
    assert db.get(models.Task, t2["id"]) is not None, "свежее удаление (сегодня) должно остаться в корзине"
    assert db.get(models.Direction, d["id"]).deleted_at is None


# ═══════════════════════ Impact ═══════════════════════

def test_impact_numbers(client, api, jack, nur):
    d, p, t, t2 = _setup(api, jack, nur)
    ok(client.post(f"/api/tasks/{t['id']}/status", json={"status": "done"}, headers=jack.h))
    assert ok(client.get(f"/api/directions/{d['id']}/impact", headers=jack.h)) == {"projects": 1, "tasks": 2, "open_tasks": 1, "shares": 2}
    assert ok(client.get(f"/api/projects/{p['id']}/impact", headers=jack.h)) == {"projects": 0, "tasks": 1, "open_tasks": 0, "shares": 1}
    assert client.get(f"/api/directions/{d['id']}/impact", headers=nur.h).status_code == 403   # только владелец


# ═══════════════════════ Люди: править/удалять — только админ ═══════════════════════

def test_people_admin_only_and_domain(client, api, jack, nur):
    p = api.person(nur, "Ержан", email="e.saparov@cis.kz")   # добавлять может любой
    assert p["user_id"] is None
    assert client.post("/api/people", json={"name": "Чужой", "email": "x@gmail.com"}, headers=nur.h).status_code == 400
    body = {"name": "Ержан С.", "email": "e.saparov@cis.kz"}
    assert client.put(f"/api/people/{p['id']}", json=body, headers=nur.h).status_code == 403
    assert ok(client.put(f"/api/people/{p['id']}", json=body, headers=jack.h))["name"] == "Ержан С."
    t = api.task(jack, "с поручением")
    ok(client.post("/api/delegations", json={"task_id": t["id"], "person_id": p["id"]}, headers=jack.h), 201)
    assert client.delete(f"/api/people/{p['id']}", headers=nur.h).status_code == 403
    r = client.delete(f"/api/people/{p['id']}", headers=jack.h)
    assert r.status_code == 409 and "(1)" in r.json()["detail"]
