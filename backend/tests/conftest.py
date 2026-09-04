"""Общие фикстуры для adversarial-тестов бэкенда CIS Planner.

Запуск из backend/:  python -m pytest tests -q

Окружение задаётся ДО импорта приложения (settings и engine создаются при импорте).
База — sqlite-файл во временной папке, PRAGMA foreign_keys=ON (эмуляция ondelete Postgres),
перед каждым тестом схема пересоздаётся — тесты изолированы друг от друга.
"""
import hashlib
import os
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="planner-tests-"))
_DB = (_TMP / "test.db").as_posix()

os.environ.update({
    "DATABASE_URL": f"sqlite:///{_DB}",
    "API_TOKEN": "tok",
    "OWNER_EMAIL": "jack@cis.kz",
    "SCHEDULER_ENABLED": "false",
    "ALLOWED_EMAIL_DOMAINS": "cis.kz",
    "SESSION_SECRET": "test-secret",
    # каналы выключены — тесты не ходят в сеть
    "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "",
    "MS_TENANT_ID": "", "MS_CLIENT_ID": "", "MS_CLIENT_SECRET": "", "MS_MAILBOX": "", "MS_REDIRECT_URI": "",
    "FRONTEND_URL": "https://front.test", "PUBLIC_URL": "",
    "APP_TIMEZONE": "Asia/Oral", "DIGEST_TIME": "08:30", "DIGEST_CHANNELS": "telegram,email", "DIGEST_WEEKDAYS_ONLY": "false",
})

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import event, select  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.db import Base, engine, SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app import models  # noqa: E402
from app.auth import issue_session, owner_user  # noqa: E402


@event.listens_for(engine, "connect")
def _fk_on(dbapi_conn, _rec):
    dbapi_conn.execute("PRAGMA foreign_keys=ON")


NUR_EMAIL, AIDA_EMAIL = "n.abilkhanov@cis.kz", "aida@cis.kz"


class U:
    """Пользователь в тесте: ORM-объект, id, JWT-заголовки, MCP Bearer-токен."""

    def __init__(self, obj: models.User, mcp_token: str):
        self.obj, self.id, self.email, self.name = obj, obj.id, obj.email, obj.name
        self.h = {"Authorization": f"Bearer {issue_session(obj)}"}
        self.mcp_token = mcp_token
        self.mcp_h = {"Authorization": f"Bearer {mcp_token}", "content-type": "application/json"}


def _mcp_token_for(db, user: models.User) -> str:
    """MCP access-токен пользователя: строка в mcp_tokens с хешем (как выдаёт /oauth/token)."""
    from datetime import datetime, timedelta, timezone
    raw = f"mcp-{user.id}-{user.email}"
    now = datetime.now(timezone.utc)
    db.add(models.McpToken(access_token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                           refresh_token_hash=hashlib.sha256((raw + "-r").encode()).hexdigest(),
                           client_id="test-client", user_id=user.id,
                           access_expires_at=now + timedelta(hours=8), refresh_expires_at=now + timedelta(days=30)))
    db.commit()
    return raw


@pytest.fixture(autouse=True)
def fresh_db():
    """Пустая схема перед каждым тестом."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    return TestClient(app, base_url="https://backend.test", raise_server_exceptions=False)


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def jack(db):
    u = owner_user(db)  # владелец (OWNER_EMAIL), is_admin
    return U(u, "tok")   # служебный API_TOKEN действует от имени владельца и в /mcp


@pytest.fixture
def nur(db):
    u = models.User(email=NUR_EMAIL, name="Нурлан", ms_oid="oid-nur")
    db.add(u); db.commit(); db.refresh(u)
    return U(u, _mcp_token_for(db, u))


@pytest.fixture
def aida(db):
    u = models.User(email=AIDA_EMAIL, name="Аида", ms_oid="oid-aida")
    db.add(u); db.commit(); db.refresh(u)
    return U(u, _mcp_token_for(db, u))


def ok(r, code=200):
    """Проверить статус и вернуть json (None для 204)."""
    assert r.status_code == code, f"{r.request.method} {r.request.url} → {r.status_code} (ожидалось {code}): {r.text[:300]}"
    return r.json() if r.status_code != 204 else None


class Api:
    """Тонкие обёртки над REST для подготовки данных в тестах."""

    def __init__(self, client: TestClient):
        self.c = client

    def direction(self, u: U, name="Направление", **kw):
        return ok(self.c.post("/api/directions", json={"name": name, **kw}, headers=u.h), 201)

    def project(self, u: U, direction_id: int, name="Проект", **kw):
        return ok(self.c.post("/api/projects", json={"direction_id": direction_id, "name": name, **kw}, headers=u.h), 201)

    def task(self, u: U, title="Задача", **kw):
        body = {"title": title, "direction_ids": [], "tool_ids": []}; body.update(kw)
        return ok(self.c.post("/api/tasks", json=body, headers=u.h), 201)

    def share(self, u: U, entity_type: str, entity_id: int, email: str, permission="view"):
        return ok(self.c.post("/api/shares", json={"entity_type": entity_type, "entity_id": entity_id, "email": email, "permission": permission}, headers=u.h), 201)

    def person(self, u: U, name="Человек", **kw):
        return ok(self.c.post("/api/people", json={"name": name, **kw}, headers=u.h), 201)

    def get_task(self, u: U, id_: int):
        return ok(self.c.get(f"/api/tasks/{id_}", headers=u.h))

    @staticmethod
    def task_body(t: dict, **kw) -> dict:
        """Тело PUT /tasks из ответа GET (как это делает фронт), с переопределениями."""
        b = {"title": t["title"], "description": t["description"], "status": t["status"], "priority": t["priority"],
             "deadline": t["deadline"], "next_check_at": t["next_check_at"], "direction_ids": [d["id"] for d in t["directions"]],
             "tool_ids": [x["id"] for x in t["tools"]], "project_id": t["project_id"], "checklist": t["checklist"]}
        b.update(kw)
        return b


@pytest.fixture
def api(client):
    return Api(client)


def link_person(db, user: U, name: str | None = None) -> int:
    """Person, привязанный к пользователю (чтобы он был исполнителем поручений). Возвращает id."""
    p = models.Person(name=name or user.name, email=user.email, user_id=user.id)
    db.add(p); db.commit(); db.refresh(p)
    return p.id


def count(db, model, *where) -> int:
    from sqlalchemy import func
    q = select(func.count()).select_from(model)
    if where:
        q = q.where(*where)
    return db.scalar(q)
