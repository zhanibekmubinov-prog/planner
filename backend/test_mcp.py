"""Проверка MCP-коннектора на sqlite: OAuth-флоу + инструменты. Запуск: python test_mcp.py"""
import base64, hashlib, json, os, secrets
os.environ.update({"DATABASE_URL": "sqlite:///./_mcp_test.db", "API_TOKEN": "tok", "OWNER_EMAIL": "jack@cis.kz",
                   "SCHEDULER_ENABLED": "false", "FRONTEND_URL": "https://cis-planner.up.railway.app", "APP_TIMEZONE": "Asia/Oral"})
if os.path.exists("_mcp_test.db"): os.remove("_mcp_test.db")
from fastapi.testclient import TestClient
from app.db import Base, engine
from app.main import app
Base.metadata.create_all(engine)
c = TestClient(app, base_url="https://backend.test")
R = "https://claude.ai/api/mcp/auth_callback"

def rpc(token, method, params=None, id_=1):
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, (r.status_code, r.text)
    return r.json()["result"]

def call(token, _tool, **args):
    res = rpc(token, "tools/call", {"name": _tool, "arguments": args})
    data = json.loads(res["content"][0]["text"])
    return data, res["isError"]

# --- метаданные ---
m = c.get("/.well-known/oauth-authorization-server").json()
assert m["issuer"] == "https://backend.test" and m["registration_endpoint"].endswith("/oauth/register"), m
pr = c.get("/.well-known/oauth-protected-resource/mcp").json(); assert pr["resource"] == "https://backend.test/mcp"
assert c.post("/mcp", json={}).status_code == 401
assert "resource_metadata" in c.post("/mcp", json={}).headers["www-authenticate"]

# --- DCR + authorize (без Microsoft → консент с токеном) ---
reg = c.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": [R]}); assert reg.status_code == 201, reg.text
cid = reg.json()["client_id"]
verifier = secrets.token_urlsafe(40)
challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
r = c.get("/oauth/authorize", params={"client_id": cid, "redirect_uri": R, "response_type": "code", "state": "xyz",
                                     "code_challenge": challenge, "code_challenge_method": "S256", "scope": "planner:full"}, follow_redirects=False)
assert r.status_code == 302 and "/oauth/consent?k=" in r.headers["location"], r.headers
key = r.headers["location"].split("k=")[1]
page = c.get(f"/oauth/consent?k={key}"); assert page.status_code == 200 and "CIS Planner" in page.text
bad = c.post("/oauth/consent", data={"k": key, "decision": "allow", "api_token": "wrong"}); assert bad.status_code == 401
ok = c.post("/oauth/consent", data={"k": key, "decision": "allow", "api_token": "tok"}, follow_redirects=False)
assert ok.status_code == 302 and ok.headers["location"].startswith(R + "?code="), ok.headers
code = ok.headers["location"].split("code=")[1].split("&")[0]
assert "state=xyz" in ok.headers["location"]
t = c.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "code_verifier": "bad", "client_id": cid, "redirect_uri": R})
assert t.status_code == 400
t = c.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "code_verifier": verifier, "client_id": cid, "redirect_uri": R})
assert t.status_code == 200, t.text
tok = t.json(); access, refresh = tok["access_token"], tok["refresh_token"]
t2 = c.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "code_verifier": verifier}); assert t2.status_code == 400  # повторно нельзя
rt = c.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": refresh}); assert rt.status_code == 200, rt.text
access = rt.json()["access_token"]
old_access = tok["access_token"]
assert c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers={"Authorization": f"Bearer {old_access}"}).status_code == 401  # после ротации старая пара отозвана
assert c.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": refresh}).status_code == 400  # старый refresh отозван
print("OAuth: ok")

# --- MCP ---
init = rpc(access, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
assert init["serverInfo"]["name"] == "CIS Planner" and "запиши" in init["instructions"], init
assert c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers={"Authorization": f"Bearer {access}"}).status_code == 202
tools = rpc(access, "tools/list")["tools"]; names = {t["name"] for t in tools}
assert "create_task" in names and "delete_task" not in names and all("handler" not in t for t in tools); print("tools:", len(tools))

d, err = call(access, "get_overview"); assert not err and d["directions"] == [] and d["user"], d
d, err = call(access, "create_direction", name="Снабжение", goal="Закрыть дефицит запчастей"); assert not err and d["direction"]["color"], d
d, err = call(access, "create_direction", name="снабжение"); assert err and "уже есть" in d["error"]
d, err = call(access, "create_direction", name="Бурение"); assert not err
d, err = call(access, "create_person", name="Ержан Сапаров", email="e.saparov@cis.kz"); assert not err
d, err = call(access, "create_task", title="Заказать фильтры на НС-3", directions=["снабж"], deadline="2026-09-10", priority=2,
              assign_to=["Ержан"], check_at="2026-09-08T10:00", comment="уточнить количество", remind_at="2026-09-09", remind_channels=["telegram", "email"])
assert not err, d
task = d["task"]; assert task["directions"] == ["Снабжение"] and task["assignees"] == ["Ержан Сапаров"] and task["reminders"][0]["fire_at"] == "2026-09-09 09:00", task
assert task["delegations"][0]["check_at"] == "2026-09-08 10:00" and d["link"].endswith("?task=1")
d, err = call(access, "create_task", title="Задача без направления", assign_to=["Айдос"]); assert err and "не найдено" in d["error"], d
d, err = call(access, "create_task", title="Согласовать график ТО", assign_to=["Айдос Нурланов"], create_person_if_missing=True, directions=["Бурение"], deadline="2026-08-30")
assert not err and d["task"]["overdue"] is True, d
d, err = call(access, "create_task", title="Проверить остатки", directions=["Логистика"], create_direction_if_missing=True); assert not err and d["task"]["directions"] == ["Логистика"]
d, err = call(access, "list_tasks"); assert not err and d["count"] == 3, d
d, err = call(access, "list_tasks", overdue_only=True); assert d["count"] == 1 and d["tasks"][0]["title"].startswith("Согласовать")
d, err = call(access, "list_tasks", direction="бурение"); assert d["count"] == 1
d, err = call(access, "list_tasks", person="ержан"); assert d["count"] == 1
d, err = call(access, "get_task", task="фильтры"); assert not err and d["delegations"][0]["comment"] == "уточнить количество", d
d, err = call(access, "get_task", task="Заказать"); assert not err  # частичное совпадение одной задачи
d, err = call(access, "add_task_note", task="фильтры", text="Поставщик обещал счёт в понедельник"); assert not err and "Поставщик" in d["description"]
d, err = call(access, "delegate_task", task="Проверить остатки", people=["Ержан", "Айдос"], check_at="2026-09-12T09:00"); assert not err and len(d["delegations"]) == 2, d
d, err = call(access, "update_task", task="Проверить остатки", status="в работе", deadline="2026-09-15", add_directions=["Снабжение"]); assert not err and d["task"]["status"] == "in_progress" and set(d["task"]["directions"]) == {"Логистика", "Снабжение"}, d
d, err = call(access, "update_delegation", task="Проверить остатки", person="Айдос", status="done", report="Остатки сверены, расхождений нет"); assert not err and d["delegation"]["status"] == "done", d
d, err = call(access, "update_delegation", task="Проверить остатки"); assert err and "Укажите person" in d["error"], d
d, err = call(access, "set_task_status", task="Согласовать график", status="готово"); assert not err and d["to"] == "выполнено"
d, err = call(access, "get_person_report", person="Айдос"); assert not err and d["tasks_total"] == 2 and d["done"] == 1 and d["done_late"] == 1 and d["completion_rate_pct"] == 50, d
d, err = call(access, "get_team_report"); assert not err and len(d["people"]) == 2 and d["people"][0]["person"]["name"] in ("Ержан Сапаров", "Айдос Нурланов"), d
d, err = call(access, "get_direction_summary", direction="Снабжение"); assert not err and d["tasks_total"] == 2 and "Ержан Сапаров" in d["people"], d
d, err = call(access, "add_reminder", task="Проверить остатки", fire_at="2026-09-14T18:30", channels=["outlook_calendar"], recipient="both"); assert not err and d["reminder"]["fire_at"] == "2026-09-14 18:30"
d, err = call(access, "add_reminder", task="Проверить остатки", fire_at="завтра"); assert err and "ISO" in d["error"]
d, err = call(access, "update_direction", direction="Бурение", status="пауза"); assert not err and d["direction"]["status"] == "paused"
d, err = call(access, "list_directions"); assert not err and len(d["directions"]) == 3 and any(x["attention_level_ru"] for x in d["directions"])
d, err = call(access, "add_tool", name="Таблица остатков", type="excel_sharepoint", url="https://x.sharepoint.com/a.xlsx", tasks=["Проверить остатки"]); assert not err and d["tool"]["tasks"] == ["Проверить остатки"]
d, err = call(access, "get_overview"); assert not err and d["overdue"] == [] and d["open_tasks_total"] == 2, d
d, err = call(access, "list_people"); assert not err and any(p["delegated_by_me"]["open"] == 2 for p in d["people"]), d
# служебный токен как Bearer = владелец
d, err = call("tok", "list_tasks", include_done=True); assert not err and d["count"] == 3
# неизвестный инструмент
d, err = call(access, "delete_task", task="1"); assert err
print("MCP tools: ok")

# --- второй пользователь (исполнитель) видит поручённое и может отчитаться ---
from app.db import SessionLocal
from app import models
from app.auth import issue_session
from app.routers.mcp_oauth import _issue_tokens
db = SessionLocal()
u2 = models.User(email="e.saparov@cis.kz", name="Ержан Сапаров"); db.add(u2); db.flush()
p = db.query(models.Person).filter_by(email="e.saparov@cis.kz").one(); p.user_id = u2.id; db.commit()
tok2 = _issue_tokens(db, cid, u2.id)["access_token"]; db.close()
d, err = call(tok2, "list_tasks", scope="assigned_to_me"); assert not err and d["count"] == 2, d
d, err = call(tok2, "update_task", task="фильтры", title="x"); assert err and "поручена вам" in d["error"], d
d, err = call(tok2, "update_delegation", task="фильтры", status="done", report="Фильтры заказаны, счёт оплачен"); assert not err and d["delegation"]["report"], d
d, err = call(tok2, "update_delegation", task="Проверить остатки", check_at="2026-09-20"); assert err and "только status и report" in d["error"], d
d, err = call(tok2, "set_task_status", task="фильтры", status="done"); assert not err
d, err = call(tok2, "get_overview"); assert not err and d["directions"] == []
d, err = call(access, "get_person_report", person="Ержан", include_done=True); assert not err and d["done"] == 1 and d["reports_recent"][0]["report"].startswith("Фильтры"), d
print("assignee: ok")
engine.dispose()
try: os.remove("_mcp_test.db")
except OSError: pass  # Windows может ещё держать файл — не страшно
print("ALL OK")
