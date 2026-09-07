"""Аутентификация.
Два способа: (1) Bearer-JWT нашей сессии, выданный после входа через Microsoft; (2) служебный X-API-Token —
для Swagger, скриптов и планировщика; он действует от имени владельца (OWNER_EMAIL)."""
import secrets
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import models
from .config import settings
from .db import get_db

api_key_header = APIKeyHeader(name="X-API-Token", auto_error=False)
bearer = HTTPBearer(auto_error=False)


def issue_session(user: models.User, days: int | None = None, password_version: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "email": user.email, "iat": int(now.timestamp()),
               "exp": int((now + timedelta(days=days or settings.session_days)).timestamp())}
    if password_version is not None:
        payload["pv"] = int(password_version)      # версия пароля гостя, см. current_user
    return jwt.encode(payload, settings.session_secret, algorithm="HS256")


def owner_user(db: Session) -> models.User:
    """Пользователь-владелец для служебного токена. Создаётся при первом обращении, если задан OWNER_EMAIL."""
    if settings.owner_email:
        u = db.scalar(select(models.User).where(models.User.email == settings.owner_email.lower()))
        if not u:
            u = models.User(email=settings.owner_email.lower(), name=settings.owner_email.split("@")[0], is_admin=True)
            db.add(u); db.commit(); db.refresh(u)
        return u
    u = db.scalar(select(models.User).where(models.User.is_admin.is_(True)).order_by(models.User.id))
    if not u:
        u = models.User(email="owner@local", name="Владелец", is_admin=True)
        db.add(u); db.commit(); db.refresh(u)
    return u


def current_user(
    token: str | None = Depends(api_key_header),
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> models.User:
    if creds and creds.scheme.lower() == "bearer":
        try:
            # exp и sub обязательны: без exp сессия была бы бессрочной, без числового sub — 500 вместо 401
            data = jwt.decode(creds.credentials, settings.session_secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
            uid = int(data["sub"])
        except (jwt.PyJWTError, KeyError, TypeError, ValueError):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")
        u = db.get(models.User, uid)
        if not u:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
        # v0.10: гость работает, пока он в списке гостей. Убрали из списка — сессия перестаёт действовать сразу.
        # v0.10.1: смена пароля гасит прежние сессии — сессия старше password_set_at не принимается.
        from .guests import get_guest, is_work_email
        if not is_work_email(u.email) and settings.allowed_domains:
            g = get_guest(db, u.email)
            if g is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "access revoked")
            if int(data.get("pv") or 0) != int(g.password_version or 0):
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "password changed")
        return u
    if token and secrets.compare_digest(token.encode(), settings.api_token.encode()):  # Н1: сравнение за постоянное время
        return owner_user(db)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad token")


def require_token(user: models.User = Depends(current_user)) -> None:  # совместимость со старым именем
    return None


def require_admin(user: models.User = Depends(current_user)) -> models.User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return user
