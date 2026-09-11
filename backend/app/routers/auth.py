"""Вход через Microsoft (OpenID Connect, authorization code) и профиль текущего пользователя."""
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import guests, models, notify, schemas
from ..auth import current_user, issue_session, require_admin
from ..config import settings
from ..db import get_db

import logging

_log = logging.getLogger("auth")
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
    """Фронт спрашивает, какие способы входа включены."""
    return {"microsoft": settings.ms_login_ready, "guest_login": settings.graph_ready,
            "frontend_url": settings.frontend_url}


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


def _sign_in_user(db: Session, email: str, name: str, oid: str | None) -> models.User:
    """Найти или завести пользователя по почте и связать его с записью «Люди».
    Общая часть для входа через Microsoft и входа из платформы (v1.5) — чтобы оба
    пути заводили сотрудника одинаково, а не двумя разными способами."""
    email = (email or "").strip().lower()
    if not email:
        raise HTTPException(401, "в учётной записи нет почты")
    if settings.allowed_domains and email.split("@")[-1] not in settings.allowed_domains:
        raise HTTPException(403, f"домен {email.split('@')[-1]} не разрешён")

    cond = models.User.email == email
    if oid: cond = cond | (models.User.ms_oid == oid)   # Н3: без oid условие «ms_oid IS NULL» совпало бы с любым приглашённым
    user = db.scalar(select(models.User).where(cond))
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
    return user


@router.get("/callback")
async def callback(code: str = Query(...), state: str = Query(...), db: Session = Depends(get_db)):
    _cleanup_states()
    # Вход ради MCP-коннектора Claude: state = «mcp:<ключ ожидающего запроса>» (см. routers/mcp_oauth.py)
    pending = None
    if state.startswith("mcp:"):
        pending = db.scalar(select(models.McpPendingAuth).where(models.McpPendingAuth.key == state[4:]))
        if pending is None:
            raise HTTPException(400, "запрос подключения Claude истёк — начните подключение заново")
    elif state not in _states:
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
    user = _sign_in_user(db, email, name, oid)
    if pending is not None:
        pending.user_id = user.id
        db.commit()
        return RedirectResponse(f"/oauth/consent?k={pending.key}")
    db.commit()

    token = issue_session(user)
    front = (settings.frontend_url or "/").rstrip("/")
    return RedirectResponse(f"{front}/#token={token}")


# ---------------- вход из платформы CIS: планнер открыт вкладкой внутри неё (v1.5) ----------------
#
# Почему не «просто iframe с обычным входом»: login.microsoftonline.com отдаёт
# X-Frame-Options: DENY, внутри рамки форма Microsoft не откроется. Плюс браузер делит
# localStorage по верхнему сайту, поэтому сессия, полученная при прямом заходе на планнер,
# внутри рамки не видна. Значит вход отдаёт платформа: она уже опознала сотрудника через
# тот же Entra и подписывает одноразовый билет общим секретом.

PLATFORM_ISS = "cis-platform"     # кто выписал билет
PLATFORM_AUD = "cis-planner"      # кому он адресован

_used_tickets: dict[str, float] = {}   # jti → когда истекает; билет срабатывает один раз
# Хватает памяти процесса, пока бэкенд один (Dockerfile: один uvicorn без --workers).
# Станет несколько процессов — переносить в таблицу, иначе билет сработает по разу в каждом.


@router.get("/platform")
def platform_login(t: str = Query(...), db: Session = Depends(get_db)):
    """Обменять одноразовый билет платформы на сессию планнера и отправить во фронт —
    так же, как после возврата от Microsoft."""
    if not settings.platform_sso_ready:
        raise HTTPException(503, "вход из платформы не настроен (PLATFORM_SSO_SECRET)")
    now = time.time()
    for k in [k for k, exp in _used_tickets.items() if exp < now]:
        _used_tickets.pop(k, None)
    try:
        data = jwt.decode(t, settings.platform_sso_secret, algorithms=["HS256"],
                          audience=PLATFORM_AUD, issuer=PLATFORM_ISS,
                          options={"require": ["exp", "iat", "jti", "email"]})
    except jwt.PyJWTError:
        raise HTTPException(401, "билет платформы недействителен")
    # Потолок возраста на нашей стороне: даже если платформа однажды выпишет билет на час,
    # украденная ссылка не будет жить дольше пары минут.
    if now - float(data["iat"]) > settings.platform_ticket_max_age_sec:
        raise HTTPException(401, "билет платформы просрочен")
    jti = str(data["jti"])
    if jti in _used_tickets:
        raise HTTPException(401, "билет платформы уже использован")
    _used_tickets[jti] = float(data["exp"])

    email = str(data["email"])
    user = _sign_in_user(db, email, str(data.get("name") or "").strip() or email.split("@")[0], None)
    db.commit()
    token = issue_session(user)
    front = (settings.frontend_url or "/").rstrip("/")
    # embed=1 остаётся в query (фрагмент фронт съедает, забирая токен) — по нему фронт понимает,
    # что он внутри платформы
    return RedirectResponse(f"{front}/?embed=1#token={token}")


# ---------------- вход внешнего участника по одноразовой ссылке (v0.10) ----------------

@router.post("/guest/request", status_code=202)
async def guest_request(data: schemas.GuestLoginIn, request: Request, db: Session = Depends(get_db)):
    """Отправить гостю ссылку для входа.

    Ответ всегда одинаковый — иначе по нему можно перебором узнать список гостей.
    Ссылку получают только адреса из списка гостей; сотруднику @<рабочий домен> этот путь закрыт.
    """
    email = guests.norm_email(data.email)
    answer = {"sent": True, "message": "Если этот адрес в списке гостей, ссылка для входа отправлена на почту."}
    if not schemas.EMAIL_RE.match(email) or guests.is_work_email(email):
        return answer
    ip = (request.client.host if request.client else "") or ""
    if guests.rate_limited(f"email:{email}", f"ip:{ip}"):
        _log.warning("guest login: слишком часто (%s, %s)", email, ip)
        return answer
    g = guests.get_guest(db, email)
    if g is None:
        _log.info("guest login: адреса %s нет в списке гостей", email)
        return answer
    raw = guests.create_login_token(db, email)
    front = (settings.frontend_url or "").rstrip("/")
    subject, html = guests.login_email(f"{front}/#guest={raw}", g.name)
    try:
        await notify.send_email(subject, html, to=email)
        _log.info("guest login: ссылка отправлена %s", email)
    except notify.NotifyError as e:
        _log.warning("guest login: письмо не ушло (%s): %s", email, e)
    return answer


@router.post("/guest/verify")
def guest_verify(data: schemas.GuestVerifyIn, db: Session = Depends(get_db)):
    """Обменять одноразовую ссылку на сессию. Токен гасится, сессия короче обычной."""
    email = guests.consume_login_token(db, data.token)
    if not email:
        raise HTTPException(400, "Ссылка устарела или уже использована — запросите новую")
    g = guests.get_guest(db, email)
    if g is None:
        raise HTTPException(403, "Доступ закрыт")
    user = db.scalar(select(models.User).where(models.User.email == email))
    if not user:
        user = models.User(email=email, name=g.name, is_admin=False)
        db.add(user); db.flush()
    user.name = user.name or g.name
    user.last_login_at = datetime.now(timezone.utc)
    person = db.scalar(select(models.Person).where(models.Person.user_id == user.id)) or \
             db.scalar(select(models.Person).where(models.Person.email == email))
    if not person:
        person = models.Person(name=user.name, email=email); db.add(person)
    person.user_id = user.id
    db.commit()
    _log.info("guest login: вошёл по ссылке %s", email)
    # По ссылке гость приходит на первый вход или на сброс — в обоих случаях просим задать пароль.
    return {"token": issue_session(user, days=guests.GUEST_SESSION_DAYS, password_version=g.password_version),
            "guest": True, "need_password": True, "has_password": bool(g.password_hash)}


@router.post("/guest/password")
async def guest_set_password(data: schemas.GuestPasswordIn, user: models.User = Depends(current_user),
                             db: Session = Depends(get_db)):
    """Гость задаёт себе пароль. Прежние его сессии после этого недействительны, поэтому выдаём новую."""
    g = guests.get_guest(db, user.email)
    if g is None:
        raise HTTPException(403, "Доступ закрыт")
    problem = guests.password_problem(data.password, user.email)
    if problem:
        raise HTTPException(400, f"Пароль не подходит: {problem}")
    first = g.password_hash is None
    guests.set_password(db, g, data.password)
    _log.info("guest password: %s %s", user.email, "задан впервые" if first else "изменён")
    await guests.notify_admin_password_change(g, first=first)
    return {"token": issue_session(user, days=guests.GUEST_SESSION_DAYS, password_version=g.password_version),
            "guest": True, "need_password": False}


@router.post("/guest/login")
def guest_login(data: schemas.GuestPasswordLoginIn, request: Request, db: Session = Depends(get_db)):
    """Обычный вход гостя: почта и пароль."""
    email = guests.norm_email(data.email)
    ip = (request.client.host if request.client else "") or ""
    if guests.login_attempt_blocked(email, ip):
        raise HTTPException(429, "Слишком много попыток. Подождите 15 минут или запросите ссылку на почту.")
    g = guests.get_guest(db, email)
    if g is None or not g.password_hash:
        guests.login_attempt_failed(email, ip)
        # Одинаковый текст и для «нет такого гостя», и для «пароль не задан» — чтобы список гостей не вычислялся
        raise HTTPException(401, "Почта или пароль не подходят. Если входите впервые — запросите ссылку на почту.")
    if not guests.verify_password(data.password, g.password_hash):
        guests.login_attempt_failed(email, ip)
        _log.warning("guest login: неверный пароль %s (%s)", email, ip)
        raise HTTPException(401, "Почта или пароль не подходят. Если входите впервые — запросите ссылку на почту.")
    guests.login_attempt_ok(email, ip)
    user = db.scalar(select(models.User).where(models.User.email == email))
    if not user:
        user = models.User(email=email, name=g.name, is_admin=False)
        db.add(user); db.flush()
    user.last_login_at = datetime.now(timezone.utc)
    person = db.scalar(select(models.Person).where(models.Person.user_id == user.id)) or \
             db.scalar(select(models.Person).where(models.Person.email == email))
    if not person:
        person = models.Person(name=user.name, email=email); db.add(person)
    person.user_id = user.id
    db.commit()
    _log.info("guest login: вошёл паролем %s", email)
    return {"token": issue_session(user, days=guests.GUEST_SESSION_DAYS, password_version=g.password_version),
            "guest": True, "need_password": False}


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
