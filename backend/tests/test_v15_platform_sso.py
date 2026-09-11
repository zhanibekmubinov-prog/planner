"""v1.5 — вход из платформы CIS: планнер открыт вкладкой внутри платформы.

Платформа опознала сотрудника своим входом Microsoft и выписала одноразовый билет,
подписанный общим секретом. Проверяем весь путь пользователя: GET /api/auth/platform?t=…
→ 307 на фронт с #token, сессия работает; и что билет нельзя подделать, переиспользовать
или растянуть по времени.
"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select

from app import models
from app.config import settings
from app.routers.auth import PLATFORM_AUD, PLATFORM_ISS, _used_tickets

SECRET = "test-platform-sso-secret-0123456789"
EMAIL = "d.dzhumagazieva@cis.kz"


def ticket(secret: str = SECRET, **over) -> str:
    now = datetime.now(timezone.utc)
    body = {"iss": PLATFORM_ISS, "aud": PLATFORM_AUD, "email": EMAIL, "name": "Диана Джумагазиева",
            "iat": int(now.timestamp()), "exp": int((now + timedelta(seconds=60)).timestamp()),
            "jti": uuid.uuid4().hex}
    body.update(over)
    return jwt.encode(body, secret, algorithm="HS256")


@pytest.fixture(autouse=True)
def _clean_tickets():
    _used_tickets.clear()
    yield
    _used_tickets.clear()


def enter(client, t: str):
    return client.get("/api/auth/platform", params={"t": t}, follow_redirects=False)


def test_valid_ticket_gives_session(client, db):
    r = enter(client, ticket())
    assert r.status_code in (302, 307), r.text
    loc = r.headers["location"]
    # фронт забирает токен из #token=…, а ?embed=1 переживает замену истории и говорит ему «мы в рамке»
    assert loc.startswith(f"{settings.frontend_url}/?embed=1#token=")
    token = loc.split("#token=", 1)[1]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    assert me.json()["email"] == EMAIL

    user = db.scalar(select(models.User).where(models.User.email == EMAIL))
    assert user is not None and user.last_login_at is not None
    # «Люди» заводятся сразу — иначе сотруднику нельзя поручить задачу
    person = db.scalar(select(models.Person).where(models.Person.email == EMAIL))
    assert person is not None and person.user_id == user.id


def test_second_entry_reuses_same_user(client, db):
    enter(client, ticket())
    enter(client, ticket())
    assert db.scalars(select(models.User).where(models.User.email == EMAIL)).all().__len__() == 1


def test_ticket_works_once(client):
    t = ticket()
    assert enter(client, t).status_code in (302, 307)
    r = enter(client, t)
    assert r.status_code == 401
    assert "использован" in r.json()["detail"]


def test_foreign_signature_rejected(client):
    r = enter(client, ticket(secret="someone-elses-secret-0123456789"))
    assert r.status_code == 401


def test_expired_ticket_rejected(client):
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    r = enter(client, ticket(iat=int(past.timestamp()), exp=int((past + timedelta(seconds=60)).timestamp())))
    assert r.status_code == 401


def test_long_lived_ticket_capped_by_age(client):
    """Даже если платформа выпишет билет на сутки, старше потолка мы его не принимаем."""
    old = datetime.now(timezone.utc) - timedelta(hours=3)
    r = enter(client, ticket(iat=int(old.timestamp()),
                             exp=int((datetime.now(timezone.utc) + timedelta(hours=21)).timestamp())))
    assert r.status_code == 401
    assert "просрочен" in r.json()["detail"]


@pytest.mark.parametrize("over", [{"aud": "someone-else"}, {"iss": "not-platform"}])
def test_wrong_audience_or_issuer_rejected(client, over):
    assert enter(client, ticket(**over)).status_code == 401


@pytest.mark.parametrize("over", [{"email": None}, {"jti": None}, {"exp": None}])
def test_missing_claims_rejected(client, over):
    key = next(iter(over))
    now = datetime.now(timezone.utc)
    body = {"iss": PLATFORM_ISS, "aud": PLATFORM_AUD, "email": EMAIL, "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=60)).timestamp()), "jti": uuid.uuid4().hex}
    body.pop(key)
    assert enter(client, jwt.encode(body, SECRET, algorithm="HS256")).status_code == 401


def test_foreign_domain_rejected(client, db):
    r = enter(client, ticket(email="stranger@gmail.com"))
    assert r.status_code == 403
    assert db.scalar(select(models.User).where(models.User.email == "stranger@gmail.com")) is None


def test_disabled_without_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "platform_sso_secret", "")
    r = enter(client, ticket())
    assert r.status_code == 503


def test_microsoft_login_still_creates_user_the_same_way(db):
    """Общий кусок _sign_in_user не должен разойтись между двумя входами."""
    from app.routers.auth import _sign_in_user
    u = _sign_in_user(db, "N.Abilkhanov@CIS.KZ", "Нурлан", "oid-1")
    db.commit()
    assert u.email == "n.abilkhanov@cis.kz"
    assert db.scalar(select(models.Person).where(models.Person.user_id == u.id)) is not None
