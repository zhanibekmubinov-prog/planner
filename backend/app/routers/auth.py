"""Вход через Microsoft (OpenID Connect, authorization code) и профиль текущего пользователя."""
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models, schemas
from ..auth import current_user, issue_session, require_admin
from ..config import settings
from ..db import get_db

router = APIRouter(prefix="/auth", tags=["auth"])
_states: dict[str, float] = {}          # anti-CSRF state → время создания (живёт 10 минут)
_jwks: dict = {"keys": None, "exp": 0.0}

AUTHORITY = "https://login.microsoftonline.com/{tenant}/v2.0"          # issuer + openid-configuration
OAUTH = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0"        # authorize / token


def _cleanup_states() -> None:
    now = time.time()
    for k in [k for k, t in _states.items() if now - t > 600]:
        _states.pop(k, None)


@router.get("/config")
def config():
    """Фронт спрашивает, включён ли вход через Microsoft."""
    return {"microsoft": settings.ms_login_ready, "frontend_url": settings.frontend_url}


@router.get("/login")
def login():
    if not settings.ms_login_ready:
        raise HTTPException(503, "Вход через Microsoft не настроен (MS_TENANT_ID / MS_CLIENT_ID / MS_CLIENT_SECRET / MS_REDIRECT_URI)")
    _cleanup_states()
    state = secrets.token_urlsafe(24); _states[state] = time.time()
    params = {
        "client_id": settings.ms_client_id, "response_type": "code", "redirect_uri": settings.ms_redirect_uri,
        "response_mode": "query", "scope": "openid profile email", "state": state, "prompt": "select_account",
    }
    return RedirectResponse(f"{OAUTH.format(tenant=settings.ms_tenant_id)}/authorize?{urlencode(params)}")


async def _jwks_keys() -> list[dict]:
    if _jwks["keys"] and _jwks["exp"] > time.time():
        return _jwks["keys"]
    async with httpx.AsyncClient(timeout=15) as c:
        meta = (await c.get(f"{AUTHORITY.format(tenant=settings.ms_tenant_id)}/.well-known/openid-configuration")).json()
        keys = (await c.get(meta["jwks_uri"])).json()["keys"]
    _jwks["keys"] = keys; _jwks["exp"] = time.time() + 6 * 3600
    return keys


async def _verify_id_token(id_token: str) -> dict:
    header = jwt.get_unverified_header(id_token)
    key = next((k for k in await _jwks_keys() if k["kid"] == header["kid"]), None)
    if not key:
        _jwks["exp"] = 0  # ключи могли ротироваться — перечитать
        key = next((k for k in await _jwks_keys() if k["kid"] == header["kid"]), None)
    if not key:
        raise HTTPException(401, "неизвестный ключ подписи id_token")
    pub = jwt.algorithms.RSAAlgorithm.from_jwk(key)
    return jwt.decode(id_token, pub, algorithms=["RS256"], audience=settings.ms_client_id,
                      issuer=f"https://login.microsoftonline.com/{settings.ms_tenant_id}/v2.0")


@router.get("/callback")
async def callback(code: str = Query(...), state: str = Query(...), db: Session = Depends(get_db)):
    _cleanup_states()
    if state not in _states:
        raise HTTPException(400, "state не совпал — попробуйте войти ещё раз")
    _states.pop(state, None)
    data = {"client_id": settings.ms_client_id, "client_secret": settings.ms_client_secret, "code": code,
            "redirect_uri": settings.ms_redirect_uri, "grant_type": "authorization_code", "scope": "openid profile email"}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{OAUTH.format(tenant=settings.ms_tenant_id)}/token", data=data)
    if r.status_code >= 300:
        raise HTTPException(401, f"Microsoft не выдал токен: {r.text[:300]}")
    claims = await _verify_id_token(r.json()["id_token"])
    email = (claims.get("preferred_username") or claims.get("email") or "").lower()
    name = claims.get("name") or email.split("@")[0]
    oid = claims.get("oid")
    if not email:
        raise HTTPException(401, "в учётной записи нет почты")
    if settings.allowed_domains and email.split("@")[-1] not in settings.allowed_domains:
        raise HTTPException(403, f"домен {email.split('@')[-1]} не разрешён")

    user = db.scalar(select(models.User).where((models.User.ms_oid == oid) | (models.User.email == email)))
    if not user:
        user = models.User(email=email, name=name, ms_oid=oid, is_admin=(email == settings.owner_email.lower()))
        db.add(user)
    else:
        user.name = user.name or name; user.ms_oid = user.ms_oid or oid
        if email == settings.owner_email.lower(): user.is_admin = True
    user.last_login_at = datetime.now(timezone.utc)
    db.flush()
    # Связать с записью «Люди» по почте (или создать), чтобы поручения доходили до пользователя
    person = db.scalar(select(models.Person).where(models.Person.user_id == user.id)) or \
             db.scalar(select(models.Person).where(models.Person.email == email))
    if not person:
        person = models.Person(name=user.name, email=email); db.add(person)
    person.user_id = user.id
    if user.telegram_chat_id and not person.telegram_chat_id: person.telegram_chat_id = user.telegram_chat_id
    db.commit()

    token = issue_session(user)
    front = (settings.frontend_url or "/").rstrip("/")
    return RedirectResponse(f"{front}/#token={token}")


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(current_user)):
    return user


@router.put("/me", response_model=schemas.UserOut)
def update_me(data: schemas.ProfileIn, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    user.name = data.name.strip() or user.name
    user.telegram_chat_id = (data.telegram_chat_id or "").strip() or None
    user.digest_enabled = data.digest_enabled
    person = db.scalar(select(models.Person).where(models.Person.user_id == user.id))
    if person:
        person.name = user.name; person.telegram_chat_id = user.telegram_chat_id
    db.commit(); db.refresh(user)
    return user


@router.get("/users", response_model=list[schemas.UserOut])
def users(_: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(models.User).order_by(models.User.name)).all()
