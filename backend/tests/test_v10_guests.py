"""v0.10: внешние участники — список гостей (только админ) и вход по одноразовой ссылке.

Проверяем: кто может добавлять гостей, что сотрудник этим путём не входит, одноразовость и срок
ссылки, отзыв доступа (удалили из списка → активная сессия перестаёт работать), а также что гостя
теперь можно приглашать в «Поделиться» и заводить в справочнике «Люди».
"""
import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import guests as g
from app import models
from app.config import settings
from app.routers import auth as auth_router
from tests.conftest import NUR_EMAIL, ok

GUEST = "partner@podryadchik.kz"


@pytest.fixture(autouse=True)
def mail(monkeypatch):
    """Письма не уходят в сеть: собираем их сюда. Graph «настроен», иначе гостей нельзя добавлять."""
    sent: list[tuple[str, str, str]] = []

    async def fake_send_email(subject: str, html: str, to: str | None = None) -> None:
        sent.append((to or "", subject, html))

    monkeypatch.setattr(auth_router.notify, "send_email", fake_send_email)
    monkeypatch.setattr(settings, "ms_tenant_id", "t"); monkeypatch.setattr(settings, "ms_client_id", "c")
    monkeypatch.setattr(settings, "ms_client_secret", "s"); monkeypatch.setattr(settings, "ms_mailbox", "box@cis.kz")
    g._recent.clear()
    return sent


def add_guest(client, u, email=GUEST, name="Партнёр", **kw):
    return client.post("/api/guests", json={"email": email, "name": name, **kw}, headers=u.h)


def link_from(mail) -> str:
    m = re.search(r'href="([^"]+)"', mail[-1][2])
    assert m, mail[-1][2]
    return m.group(1)


def token_from(mail) -> str:
    return link_from(mail).split("#guest=")[1]


# ---------------- список гостей ----------------

def test_v10_only_admin_manages_guests(client, jack, nur, mail):
    assert add_guest(client, nur).status_code == 403
    j = ok(add_guest(client, jack), 201)
    assert j["email"] == GUEST and j["invited_by_id"] == jack.id and j["last_login_at"] is None
    assert client.get("/api/guests", headers=nur.h).status_code == 403
    assert len(ok(client.get("/api/guests", headers=jack.h))) == 1


def test_v10_work_email_cannot_be_guest(client, jack, mail):
    r = add_guest(client, jack, email=NUR_EMAIL)
    assert r.status_code == 400 and "рабочий домен" in r.text


def test_v10_duplicate_guest(client, jack, mail):
    ok(add_guest(client, jack), 201)
    assert add_guest(client, jack).status_code == 409


def test_v10_guest_needs_mail_configured(client, jack, mail, monkeypatch):
    monkeypatch.setattr(settings, "ms_mailbox", "")          # Graph не настроен
    r = add_guest(client, jack)
    assert r.status_code == 503 and "Почта не настроена" in r.text


def test_v10_bad_email_rejected(client, jack, mail):
    assert add_guest(client, jack, email="просто-строка").status_code == 422


def test_v10_email_is_immutable(client, jack, mail):
    j = ok(add_guest(client, jack), 201)
    r = client.put(f"/api/guests/{j['id']}", json={"email": "other@x.kz", "name": "Партнёр"}, headers=jack.h)
    assert r.status_code == 400
    ok(client.put(f"/api/guests/{j['id']}", json={"email": GUEST, "name": "Партнёр Б.", "note": "ЛВД"}, headers=jack.h))
    assert ok(client.get("/api/guests", headers=jack.h))[0]["name"] == "Партнёр Б."


# ---------------- вход по ссылке ----------------

def test_v10_login_flow(client, db, jack, mail):
    ok(add_guest(client, jack), 201)
    ok(client.post("/api/auth/guest/request", json={"email": GUEST}), 202)
    assert mail[-1][0] == GUEST and "15 минут" in mail[-1][2]
    j = ok(client.post("/api/auth/guest/verify", json={"token": token_from(mail)}))
    assert j["guest"] is True
    me = ok(client.get("/api/auth/me", headers={"Authorization": f"Bearer {j['token']}"}))
    assert me["email"] == GUEST and me["is_admin"] is False
    # запись «Люди» связана — поручения дойдут
    assert db.scalar(select(models.Person).where(models.Person.email == GUEST)).user_id is not None
    # в списке гостей виден вход
    assert ok(client.get("/api/guests", headers=jack.h))[0]["last_login_at"] is not None


def test_v10_link_is_single_use(client, jack, mail):
    ok(add_guest(client, jack), 201)
    ok(client.post("/api/auth/guest/request", json={"email": GUEST}), 202)
    t = token_from(mail)
    ok(client.post("/api/auth/guest/verify", json={"token": t}))
    r = client.post("/api/auth/guest/verify", json={"token": t})
    assert r.status_code == 400 and "устарела" in r.text


def test_v10_link_expires(client, db, jack, mail):
    ok(add_guest(client, jack), 201)
    ok(client.post("/api/auth/guest/request", json={"email": GUEST}), 202)
    row = db.scalars(select(models.GuestLoginToken)).all()[-1]
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1); db.commit()
    assert client.post("/api/auth/guest/verify", json={"token": token_from(mail)}).status_code == 400


def test_v10_new_request_kills_previous_link(client, jack, mail):
    ok(add_guest(client, jack), 201)
    ok(client.post("/api/auth/guest/request", json={"email": GUEST}), 202)
    first = token_from(mail)
    ok(client.post("/api/auth/guest/request", json={"email": GUEST}), 202)
    assert client.post("/api/auth/guest/verify", json={"token": first}).status_code == 400
    ok(client.post("/api/auth/guest/verify", json={"token": token_from(mail)}))


def test_v10_unknown_email_answers_the_same_and_sends_nothing(client, mail):
    r = client.post("/api/auth/guest/request", json={"email": "kto-to@example.com"})
    assert r.status_code == 202 and r.json()["sent"] is True and not mail


def test_v10_work_email_cannot_use_link_login(client, jack, mail):
    """Сотрудник входит только через Microsoft — иначе появился бы обход корпоративного входа."""
    ok(client.post("/api/auth/guest/request", json={"email": NUR_EMAIL}), 202)
    assert not mail


def test_v10_rate_limit(client, jack, mail):
    ok(add_guest(client, jack), 201)
    for _ in range(3):
        ok(client.post("/api/auth/guest/request", json={"email": GUEST}), 202)
    ok(client.post("/api/auth/guest/request", json={"email": GUEST}), 202)   # ответ тот же
    assert len(mail) == 3                                                     # но письма больше не уходят


def test_v10_garbage_token(client):
    assert client.post("/api/auth/guest/verify", json={"token": "a" * 40}).status_code == 400


# ---------------- отзыв доступа ----------------

def test_v10_delete_guest_revokes_open_session(client, db, jack, mail):
    ok(add_guest(client, jack), 201)
    ok(client.post("/api/auth/guest/request", json={"email": GUEST}), 202)
    token = ok(client.post("/api/auth/guest/verify", json={"token": token_from(mail)}))["token"]
    h = {"Authorization": f"Bearer {token}"}
    ok(client.get("/api/auth/me", headers=h))
    gid = ok(client.get("/api/guests", headers=jack.h))[0]["id"]
    ok(client.delete(f"/api/guests/{gid}", headers=jack.h), 204)
    assert client.get("/api/auth/me", headers=h).status_code == 401          # сессия больше не действует
    assert client.get("/api/tasks", headers=h).status_code == 401
    assert not db.scalars(select(models.GuestLoginToken)).all()              # неиспользованные ссылки убраны


def test_v10_deleted_guest_link_does_not_work(client, jack, mail):
    ok(add_guest(client, jack), 201)
    ok(client.post("/api/auth/guest/request", json={"email": GUEST}), 202)
    t = token_from(mail)
    gid = ok(client.get("/api/guests", headers=jack.h))[0]["id"]
    ok(client.delete(f"/api/guests/{gid}", headers=jack.h), 204)
    assert client.post("/api/auth/guest/verify", json={"token": t}).status_code == 400


def test_ok_employee_session_survives(client, jack, nur, mail):
    """Регрессия: проверка гостей не должна мешать обычным сотрудникам."""
    ok(client.get("/api/auth/me", headers=nur.h))
    ok(client.get("/api/auth/me", headers=jack.h))


# ---------------- гость в работе ----------------

def test_v10_can_share_with_guest(client, api, jack, mail):
    ok(add_guest(client, jack), 201)
    d = api.direction(jack, "Подряд ЛВД")
    ok(client.post("/api/shares", json={"entity_type": "direction", "entity_id": d["id"],
                                        "email": GUEST, "permission": "edit"}, headers=jack.h), 201)
    assert any(s["user"]["name"] for s in ok(client.get(f"/api/shares?entity_type=direction&entity_id={d['id']}", headers=jack.h)))


def test_v10_cannot_share_with_outsider(client, api, jack, mail):
    d = api.direction(jack, "Подряд ЛВД")
    r = client.post("/api/shares", json={"entity_type": "direction", "entity_id": d["id"],
                                         "email": "nobody@example.com", "permission": "view"}, headers=jack.h)
    assert r.status_code == 400 and "только своих" in r.text


def test_v10_guest_in_people_registry(client, jack, mail):
    ok(add_guest(client, jack), 201)
    ok(client.post("/api/people", json={"name": "Партнёр", "email": GUEST}, headers=jack.h), 201)
    r = client.post("/api/people", json={"name": "Кто-то", "email": "nobody@example.com"}, headers=jack.h)
    assert r.status_code == 400


def test_v10_purge_login_tokens(client, db, jack, mail):
    ok(add_guest(client, jack), 201)
    ok(client.post("/api/auth/guest/request", json={"email": GUEST}), 202)
    row = db.scalars(select(models.GuestLoginToken)).all()[-1]
    row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1); db.commit()
    assert g.purge_login_tokens(db) == 1
    assert not db.scalars(select(models.GuestLoginToken)).all()


# ---------------- пароль гостя (v0.10.1) ----------------

GOOD = "podryad-2026-lvd"


def by_link(client, mail) -> dict:
    """Пройти по ссылке из письма и получить сессию (в ответе просьба задать пароль)."""
    ok(client.post("/api/auth/guest/request", json={"email": GUEST}), 202)
    return ok(client.post("/api/auth/guest/verify", json={"token": token_from(mail)}))


def test_v10_1_link_asks_for_password(client, jack, mail):
    ok(add_guest(client, jack), 201)
    j = by_link(client, mail)
    assert j["need_password"] is True and j["has_password"] is False
    assert "задать пароль" in mail[-1][2]


def test_v10_1_set_password_then_login(client, jack, mail):
    ok(add_guest(client, jack), 201)
    h = {"Authorization": f"Bearer {by_link(client, mail)['token']}"}
    j = ok(client.post("/api/auth/guest/password", json={"password": GOOD}, headers=h))
    assert j["need_password"] is False and j["token"]
    # теперь обычный вход почтой и паролем
    j2 = ok(client.post("/api/auth/guest/login", json={"email": GUEST, "password": GOOD}))
    me = ok(client.get("/api/auth/me", headers={"Authorization": f"Bearer {j2['token']}"}))
    assert me["email"] == GUEST
    assert ok(client.get("/api/guests", headers=jack.h))[0]["has_password"] is True


def test_v10_1_weak_password_rejected(client, jack, mail):
    ok(add_guest(client, jack), 201)
    h = {"Authorization": f"Bearer {by_link(client, mail)['token']}"}
    for bad in ("1234", "1234567890", GUEST, "aaaaaaaaaaaa"):
        r = client.post("/api/auth/guest/password", json={"password": bad}, headers=h)
        assert r.status_code == 400, bad
    assert ok(client.get("/api/guests", headers=jack.h))[0]["has_password"] is False


def test_v10_1_wrong_password(client, jack, mail):
    ok(add_guest(client, jack), 201)
    h = {"Authorization": f"Bearer {by_link(client, mail)['token']}"}
    ok(client.post("/api/auth/guest/password", json={"password": GOOD}, headers=h))
    r = client.post("/api/auth/guest/login", json={"email": GUEST, "password": "ne-tot-parol-1"})
    assert r.status_code == 401 and "не подходят" in r.text


def test_v10_1_login_without_password_set(client, jack, mail):
    ok(add_guest(client, jack), 201)
    r = client.post("/api/auth/guest/login", json={"email": GUEST, "password": GOOD})
    assert r.status_code == 401 and "запросите ссылку" in r.text


def test_v10_1_unknown_email_same_answer(client, mail):
    r = client.post("/api/auth/guest/login", json={"email": "kto-to@example.com", "password": GOOD})
    assert r.status_code == 401 and "не подходят" in r.text


def test_v10_1_brute_force_blocked(client, jack, mail):
    ok(add_guest(client, jack), 201)
    h = {"Authorization": f"Bearer {by_link(client, mail)['token']}"}
    ok(client.post("/api/auth/guest/password", json={"password": GOOD}, headers=h))
    for _ in range(5):
        assert client.post("/api/auth/guest/login", json={"email": GUEST, "password": "mimo-parol-1"}).status_code == 401
    r = client.post("/api/auth/guest/login", json={"email": GUEST, "password": GOOD})   # даже верный
    assert r.status_code == 429 and "попыток" in r.text


def test_v10_1_successful_login_clears_counter(client, jack, mail):
    ok(add_guest(client, jack), 201)
    h = {"Authorization": f"Bearer {by_link(client, mail)['token']}"}
    ok(client.post("/api/auth/guest/password", json={"password": GOOD}, headers=h))
    for _ in range(4):
        client.post("/api/auth/guest/login", json={"email": GUEST, "password": "mimo-parol-1"})
    ok(client.post("/api/auth/guest/login", json={"email": GUEST, "password": GOOD}))
    for _ in range(4):
        assert client.post("/api/auth/guest/login", json={"email": GUEST, "password": "mimo-parol-1"}).status_code == 401


def test_v10_1_password_change_kills_old_sessions(client, jack, mail):
    """Сброс пароля выкидывает всех, кто вошёл раньше, — в том числе того, кто увёл ящик."""
    ok(add_guest(client, jack), 201)
    h = {"Authorization": f"Bearer {by_link(client, mail)['token']}"}
    ok(client.post("/api/auth/guest/password", json={"password": GOOD}, headers=h))
    old = ok(client.post("/api/auth/guest/login", json={"email": GUEST, "password": GOOD}))["token"]
    old_h = {"Authorization": f"Bearer {old}"}
    ok(client.get("/api/auth/me", headers=old_h))
    h2 = {"Authorization": f"Bearer {by_link(client, mail)['token']}"}
    new = ok(client.post("/api/auth/guest/password", json={"password": "drugoi-parol-2026"}, headers=h2))
    assert client.get("/api/auth/me", headers=old_h).status_code == 401          # прежняя сессия умерла
    ok(client.get("/api/auth/me", headers={"Authorization": f"Bearer {new['token']}"}))
    ok(client.post("/api/auth/guest/login", json={"email": GUEST, "password": "drugoi-parol-2026"}))
    assert client.post("/api/auth/guest/login", json={"email": GUEST, "password": GOOD}).status_code == 401


def test_v10_1_admin_notified_about_password(client, jack, mail):
    ok(add_guest(client, jack), 201)
    h = {"Authorization": f"Bearer {by_link(client, mail)['token']}"}
    ok(client.post("/api/auth/guest/password", json={"password": GOOD}, headers=h))
    assert any("сменил пароль" in s or "задал пароль" in s for _, subj, s in mail)


def test_v10_1_admin_reset_link(client, jack, mail):
    j = ok(add_guest(client, jack), 201)
    r = ok(client.post(f"/api/guests/{j['id']}/reset-link", headers=jack.h), 202)
    assert r["sent"] and mail[-1][0] == GUEST
    ok(client.post("/api/auth/guest/verify", json={"token": token_from(mail)}))


def test_v10_1_reset_link_admin_only(client, jack, nur, mail):
    j = ok(add_guest(client, jack), 201)
    assert client.post(f"/api/guests/{j['id']}/reset-link", headers=nur.h).status_code == 403


def test_v10_1_password_of_deleted_guest_useless(client, jack, mail):
    ok(add_guest(client, jack), 201)
    h = {"Authorization": f"Bearer {by_link(client, mail)['token']}"}
    ok(client.post("/api/auth/guest/password", json={"password": GOOD}, headers=h))
    gid = ok(client.get("/api/guests", headers=jack.h))[0]["id"]
    ok(client.delete(f"/api/guests/{gid}", headers=jack.h), 204)
    assert client.post("/api/auth/guest/login", json={"email": GUEST, "password": GOOD}).status_code == 401
