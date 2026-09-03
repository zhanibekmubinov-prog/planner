"""Проверка v0.6 на sqlite: проекты и совместный доступ. Запуск из backend/: python test_v06.py"""
import os
os.environ.update({"DATABASE_URL": "sqlite:///./_v06_test.db", "API_TOKEN": "tok", "OWNER_EMAIL": "jack@cis.kz",
                   "SCHEDULER_ENABLED": "false", "ALLOWED_EMAIL_DOMAINS": "cis.kz"})
if os.path.exists("_v06_test.db"): os.remove("_v06_test.db")
from fastapi.testclient import TestClient
from app.db import Base, engine, SessionLocal
from app.main import app
from app import models
from app.auth import issue_session, owner_user

Base.metadata.create_all(engine)
c = TestClient(app)

def H(tok): return {"Authorization": f"Bearer {tok}"}
def ok(r, code=200):
    assert r.status_code == code, (r.request.method, r.request.url, r.status_code, r.text)
    return r.json() if r.status_code != 204 else None

with SessionLocal() as db:
    jack = owner_user(db)
    nur = models.User(email="n.abilkhanov@cis.kz", name="Нурлан", ms_oid="oid-nur"); db.add(nur); db.commit(); db.refresh(nur)
    J, N = issue_session(jack), issue_session(nur)

# --- Джек: направление → проекты → задачи ---
emba = ok(c.post("/api/directions", json={"name": "Эмба", "goal": "Месторождение"}, headers=H(J)), 201)
assert emba["access"] == "owner"
p_main = ok(c.post("/api/projects", json={"direction_id": emba["id"], "name": "Договор основной"}, headers=H(J)), 201)
p_mini = ok(c.post("/api/projects", json={"direction_id": emba["id"], "name": "Договор мини"}, headers=H(J)), 201)
# задача в проекте — направление подтягивается само
t1 = ok(c.post("/api/tasks", json={"title": "Сделать ГРП", "project_id": p_main["id"], "direction_ids": [], "tool_ids": []}, headers=H(J)), 201)
assert t1["project_id"] == p_main["id"] and [d["id"] for d in t1["directions"]] == [emba["id"]], t1
t2 = ok(c.post("/api/tasks", json={"title": "Почистить месторождение", "direction_ids": [emba["id"]], "tool_ids": []}, headers=H(J)), 201)
assert t2["project_id"] is None
# фильтр задач по проекту
assert [t["id"] for t in ok(c.get(f"/api/tasks?project_id={p_main['id']}", headers=H(J)))] == [t1["id"]]
assert len(ok(c.get(f"/api/projects?direction_id={emba['id']}", headers=H(J)))) == 2

# --- Нурлан пока ничего не видит ---
assert ok(c.get("/api/directions", headers=H(N))) == []
assert ok(c.get("/api/tasks", headers=H(N))) == []
assert c.get(f"/api/tasks/{t1['id']}", headers=H(N)).status_code == 404

# --- Джек делится проектом «Договор основной» на просмотр ---
bad = c.post("/api/shares", json={"entity_type": "project", "entity_id": p_main["id"], "email": "x@gmail.com", "permission": "view"}, headers=H(J))
assert bad.status_code == 400 and "cis.kz" in bad.text
sh = ok(c.post("/api/shares", json={"entity_type": "project", "entity_id": p_main["id"], "email": "N.Abilkhanov@cis.kz", "permission": "view"}, headers=H(J)), 201)
assert sh["user"]["email"] == "n.abilkhanov@cis.kz" and sh["permission"] == "view"
# Нурлан: видит направление (via), проект (view), задачу проекта (view), но не задачу без проекта
dirs = ok(c.get("/api/directions", headers=H(N))); assert [(d["id"], d["access"]) for d in dirs] == [(emba["id"], "via")], dirs
prj = ok(c.get("/api/projects", headers=H(N))); assert [(p["id"], p["access"]) for p in prj] == [(p_main["id"], "view")], prj
ts = ok(c.get("/api/tasks", headers=H(N))); assert [(t["id"], t["access"]) for t in ts] == [(t1["id"], "view")], ts
# только просмотр: править нельзя, статус тоже
body = {"title": "Сделать ГРП!", "status": "in_progress", "priority": 3, "direction_ids": [emba["id"]], "tool_ids": [], "project_id": p_main["id"]}
assert c.put(f"/api/tasks/{t1['id']}", json=body, headers=H(N)).status_code == 403
assert c.post(f"/api/tasks/{t1['id']}/status", json={"status": "done"}, headers=H(N)).status_code == 403
assert c.post("/api/tasks", json={"title": "Чужая", "project_id": p_main["id"], "direction_ids": [], "tool_ids": []}, headers=H(N)).status_code == 403
# управлять доступом может только владелец
assert c.post("/api/shares", json={"entity_type": "project", "entity_id": p_main["id"], "email": "a@cis.kz"}, headers=H(N)).status_code == 403
assert c.get(f"/api/shares?entity_type=project&entity_id={p_main['id']}", headers=H(N)).status_code == 403
# раздел «Общие» у Нурлана
wm = ok(c.get("/api/shares/with-me", headers=H(N)))
assert len(wm) == 1 and wm[0]["name"] == "Договор основной" and wm[0]["shared_by"]["email"] == "jack@cis.kz" and wm[0]["direction_id"] == emba["id"], wm

# --- повышаем до редактирования ---
ok(c.put(f"/api/shares/{sh['id']}", json={"permission": "edit"}, headers=H(J)))
ts = ok(c.get("/api/tasks", headers=H(N))); assert ts[0]["access"] == "edit"
ok(c.put(f"/api/tasks/{t1['id']}", json=body, headers=H(N)))
assert ok(c.get(f"/api/tasks/{t1['id']}", headers=H(J)))["title"] == "Сделать ГРП!"
# Нурлан создаёт задачу в чужом проекте → задача принадлежит Джеку, Нурлан видит её как edit
t3 = ok(c.post("/api/tasks", json={"title": "Договориться на следующий год", "project_id": p_main["id"], "direction_ids": [], "tool_ids": []}, headers=H(N)), 201)
assert t3["owner"]["email"] == "jack@cis.kz" and t3["access"] == "edit", t3
assert any(t["id"] == t3["id"] and t["access"] == "owner" for t in ok(c.get("/api/tasks", headers=H(J))))
# удалять и делиться редактор не может
assert c.delete(f"/api/tasks/{t3['id']}", headers=H(N)).status_code == 404
assert c.delete(f"/api/projects/{p_main['id']}", headers=H(N)).status_code == 404
# редактор может переименовать проект
ok(c.put(f"/api/projects/{p_main['id']}", json={**{k: p_main[k] for k in ("direction_id", "name", "description", "goal", "color", "status")}, "goal": "Подписать до декабря"}, headers=H(N)))
# но не направление (оно только via)
assert c.put(f"/api/directions/{emba['id']}", json={"name": "Эмба-2"}, headers=H(N)).status_code == 403

# --- делимся целым направлением на просмотр: видны оба проекта и все задачи ---
sh_dir = ok(c.post("/api/shares", json={"entity_type": "direction", "entity_id": emba["id"], "email": "n.abilkhanov@cis.kz", "permission": "view"}, headers=H(J)), 201)
dirs = ok(c.get("/api/directions", headers=H(N))); assert dirs[0]["access"] == "view"
prj = ok(c.get("/api/projects", headers=H(N))); assert sorted((p["id"], p["access"]) for p in prj) == sorted([(p_main["id"], "edit"), (p_mini["id"], "view")]), prj
ts = ok(c.get("/api/tasks", headers=H(N))); assert {t["id"] for t in ts} == {t1["id"], t2["id"], t3["id"]}
assert {t["id"]: t["access"] for t in ts}[t2["id"]] == "view"
assert len(ok(c.get("/api/shares/with-me", headers=H(N)))) == 2

# --- приглашение ещё не входившего человека: заводится заготовка, вход по e-mail подхватит ---
sh_new = ok(c.post("/api/shares", json={"entity_type": "task", "entity_id": t2["id"], "email": "a.serik@cis.kz", "permission": "view"}, headers=H(J)), 201)
assert sh_new["user"]["name"] == "A. Serik", sh_new
people = ok(c.get("/api/shares/people", headers=H(J))); assert {p["email"] for p in people} == {"n.abilkhanov@cis.kz", "a.serik@cis.kz"}

# --- отзыв доступа ---
ok(c.delete(f"/api/shares/{sh_dir['id']}", headers=H(J)), 204)
ok(c.delete(f"/api/shares/{sh['id']}", headers=H(N)), 204)   # приглашённый отказался сам
assert ok(c.get("/api/tasks", headers=H(N))) == []
assert ok(c.get("/api/directions", headers=H(N))) == []

# --- удаление проекта: задачи остаются в направлении ---
ok(c.delete(f"/api/projects/{p_main['id']}", headers=H(J)), 204)
t1_after = ok(c.get(f"/api/tasks/{t1['id']}", headers=H(J))); assert t1_after["project_id"] is None and t1_after["directions"][0]["id"] == emba["id"]

# --- MCP: проекты через Claude ---
import json
def call(tool, **args):
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}, headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200, r.text
    res = r.json()["result"]; return json.loads(res["content"][0]["text"]), res["isError"]
d, err = call("create_project", direction="Эмба", name="Договор бурение"); assert not err, d
d, err = call("list_projects", direction="эмба"); assert not err and {p["name"] for p in d["projects"]} == {"Договор мини", "Договор бурение"}, d
d, err = call("create_task", title="Заказать буровую", project="бурение"); assert not err and d["task"]["project"] == "Договор бурение" and d["task"]["directions"] == ["Эмба"], d
d, err = call("list_tasks", project="Договор бурение"); assert not err and d["count"] == 1, d
d, err = call("get_direction_summary", direction="Эмба"); assert not err and len(d["projects"]) == 2, d
d, err = call("share_access", entity_type="project", entity="бурение", email="n.abilkhanov@cis.kz", permission="edit"); assert not err, d
d, err = call("list_shares", entity_type="project", entity="бурение"); assert not err and d["shares"][0]["email"] == "n.abilkhanov@cis.kz", d
d, err = call("update_project", project="Договор мини", status="пауза"); assert not err and d["project"]["status"] == "paused", d

print("ALL OK")
