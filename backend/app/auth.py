"""Аутентификация.
Два способа: (1) Bearer-JWT нашей сессии, выданный после входа через Microsoft; (2) служебный X-API-Token —
для Swagger, скриптов и планировщика; он действует от имени владельца (OWNER_EMAIL)."""
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


def issue_session(user: models.User) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "email": user.email, "iat": int(now.timestamp()), "exp": int((now + timedelta(days=settings.session_days)).timestamp())}
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
            data = jwt.decode(creds.credentials, settings.session_secret, algorithms=["HS256"])
        except jwt.PyJWTError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")
        u = db.get(models.User, int(data["sub"]))
        if not u:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
        return u
    if token and token == settings.api_token:
        return owner_user(db)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad token")


def require_token(user: models.User = Depends(current_user)) -> None:  # совместимость со старым именем
    return None


def require_admin(user: models.User = Depends(current_user)) -> models.User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return user
