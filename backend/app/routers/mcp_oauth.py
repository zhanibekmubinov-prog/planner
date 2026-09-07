"""OAuth 2.0 для MCP-коннектора Claude (та же схема, что в CIS Platform).

Claude (claude.ai, мобильное приложение, Claude Desktop) добавляет custom connector с URL
https://<backend>/mcp, сам регистрируется как публичный клиент (RFC 7591), отправляет пользователя
на /oauth/authorize → мы ведём его во вход через Microsoft → страница «Разрешить» → код → токены.

Метаданные: RFC 8414 (/.well-known/oauth-authorization-server) и RFC 9728 (/.well-known/oauth-protected-resource).
PKCE S256 обязателен. В базе хранятся только SHA-256 хеши кодов и токенов.

v0.8 (защита от consent-фишинга и гонок):
- /oauth/authorize ставит httpOnly-cookie `mcp_auth`; её SHA-256 хранится в McpPendingAuth.scope как суффикс
  «|cb=<hash>» (отдельной колонки нет — схема не менялась). /oauth/consent (GET и POST) принимает запрос только
  из того же браузера. На странице согласия показан хост redirect_uri.
- redirect_uri: https и хост из REDIRECT_HOST_ALLOWLIST (claude.ai, claude.com, anthropic.com); http — только localhost/127.0.0.1.
- /oauth/token требует client_id и redirect_uri, совпадающие с кодом; код и refresh одноразовые атомарно
  (UPDATE … WHERE used=false / revoked=false с проверкой rowcount). Повтор уже использованного кода отзывает токены, выданные по нему.
- /oauth/register: лимит по IP и общий (в памяти процесса). /oauth/revoke (RFC 7009). Чистка просроченного — cleanup_oauth() из планировщика.
"""
import base64
import hashlib
import html
import logging
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode, urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import delete, exists, select, update
from sqlalchemy.orm import Session

from .. import models
from ..auth import owner_user
from ..config import settings
from ..db import get_db

log = logging.getLogger("mcp.oauth")
router = APIRouter(tags=["mcp"])

ACCESS_TOKEN_TTL = timedelta(hours=8)
REFRESH_TOKEN_TTL = timedelta(days=30)
AUTH_CODE_TTL = timedelta(minutes=10)
PENDING_TTL = timedelta(minutes=10)
CLIENT_UNUSED_TTL = timedelta(days=1)          # клиент без единой авторизации удаляется через сутки
SCOPE = "planner:full"
MS_OAUTH = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
COOKIE = "mcp_auth"
# Хосты, на которые разрешено отдавать код (суффиксное совпадение: *.claude.ai). Пустое множество = любой https-хост.
REDIRECT_HOST_ALLOWLIST: set[str] = {"claude.ai", "claude.com", "anthropic.com", "localhost", "127.0.0.1"}
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
# Лимиты регистрации клиентов (в памяти процесса): на IP и суммарно за окно
REGISTER_LIMIT_PER_IP, REGISTER_LIMIT_TOTAL, REGISTER_WINDOW_SEC = 10, 100, 3600
_reg_hits: dict[str, list[float]] = {}
LAST_USED_UPDATE_EVERY = timedelta(minutes=1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def issuer(request: Request) -> str:
    """Публичный адрес бэкенда. За прокси Railway берём X-Forwarded-*."""
    if settings.public_url:
        return settings.public_url.rstrip("/")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    return f"{proto}://{host}"


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else "") or (request.client.host if request.client else "?")


# ── Метаданные (RFC 8414 + RFC 9728) ─────────────────────────────────────────

@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/oauth-authorization-server/mcp")
def oauth_metadata(request: Request):
    base = issuer(request)
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [SCOPE],
    }


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
def resource_metadata(request: Request):
    base = issuer(request)
    return {
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "scopes_supported": [SCOPE],
        "bearer_methods_supported": ["header"],
    }


# ── Dynamic Client Registration (RFC 7591) ───────────────────────────────────

def _host_allowed(host: str) -> bool:
    if not REDIRECT_HOST_ALLOWLIST:
        return True
    return any(host == h or host.endswith("." + h) for h in REDIRECT_HOST_ALLOWLIST)


def _valid_redirect_uri(uri) -> bool:
    """https на разрешённый хост; http — только localhost/127.0.0.1 (Claude Code и локальная отладка); без #fragment."""
    if not isinstance(uri, str) or len(uri) > 1000:
        return False
    try:
        u = urlparse(uri)
        host = (u.hostname or "").lower()
    except ValueError:
        return False
    if not host or u.fragment or "#" in uri:
        return False
    if u.scheme == "https":
        return _host_allowed(host)
    if u.scheme == "http":
        return host in LOCAL_HOSTS
    return False


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    for key in (ip, "*"):
        _reg_hits[key] = [t for t in _reg_hits.get(key, []) if now - t < REGISTER_WINDOW_SEC]
    if len(_reg_hits[ip]) >= REGISTER_LIMIT_PER_IP or len(_reg_hits["*"]) >= REGISTER_LIMIT_TOTAL:
        return True
    _reg_hits[ip].append(now); _reg_hits["*"].append(now)
    return False


@router.post("/oauth/register", status_code=201)
async def oauth_register(request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    if _rate_limited(ip):
        log.warning("oauth register rate-limited: %s", ip)
        return JSONResponse({"error": "invalid_client_metadata", "error_description": "слишком много регистраций — попробуйте позже"},
                            status_code=429, headers={"Retry-After": "600"})
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    uris = data.get("redirect_uris") or []
    if not isinstance(uris, list) or not uris or len(uris) > 10 or not all(_valid_redirect_uri(u) for u in uris):
        return JSONResponse({"error": "invalid_redirect_uri",
                             "error_description": "redirect_uris: список https-адресов на разрешённые хосты (claude.ai) или http://localhost"}, status_code=400)
    client = models.McpClient(client_id=secrets.token_urlsafe(24), client_name=str(data.get("client_name") or "MCP client")[:128], redirect_uris=uris)
    db.add(client); db.commit()
    return {
        "client_id": client.client_id,
        "client_name": client.client_name,
        "redirect_uris": uris,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }


# ── Authorization endpoint ────────────────────────────────────────────────────

def _redirect_error(redirect_uri: str, state: str | None, error: str, description: str) -> RedirectResponse:
    sep = "&" if "?" in redirect_uri else "?"
    url = f"{redirect_uri}{sep}error={error}&error_description={quote(description)}"
    if state:
        url += f"&state={quote(state)}"
    return RedirectResponse(url, status_code=302)


def _pack_scope(scope: str, cookie_hash: str) -> str:
    return f"{scope}|cb={cookie_hash}"


def _unpack_scope(pending: models.McpPendingAuth) -> tuple[str, str | None]:
    """(scope, хеш cookie) из поля scope."""
    raw = pending.scope or SCOPE
    if "|cb=" in raw:
        scope, _, h = raw.partition("|cb=")
        return scope or SCOPE, h or None
    return raw, None


@router.get("/oauth/authorize")
def oauth_authorize(request: Request, db: Session = Depends(get_db)):
    q = request.query_params
    p = {k: (q.get(k) or "").strip() for k in ("client_id", "redirect_uri", "response_type", "state", "code_challenge", "code_challenge_method", "scope")}
    client = db.scalar(select(models.McpClient).where(models.McpClient.client_id == p["client_id"]))
    if client is None:
        return JSONResponse({"error": "unauthorized_client", "error_description": "неизвестный client_id"}, status_code=400)
    if p["redirect_uri"] not in (client.redirect_uris or []) or not _valid_redirect_uri(p["redirect_uri"]):
        return JSONResponse({"error": "invalid_request", "error_description": "redirect_uri не зарегистрирован"}, status_code=400)
    if p["response_type"] != "code":
        return _redirect_error(p["redirect_uri"], p["state"], "unsupported_response_type", "поддерживается только code")
    if p["code_challenge_method"] != "S256" or not _CHALLENGE_RE.match(p["code_challenge"]):
        return _redirect_error(p["redirect_uri"], p["state"], "invalid_request", "требуется PKCE S256 (code_challenge — 43–128 символов base64url)")
    if len(p["state"]) > 500:
        return _redirect_error(p["redirect_uri"], None, "invalid_request", "state слишком длинный")

    db.execute(delete(models.McpPendingAuth).where(models.McpPendingAuth.expires_at < _now()), execution_options={"synchronize_session": False})
    cookie_val = secrets.token_urlsafe(24)
    pending = models.McpPendingAuth(key=secrets.token_urlsafe(24), client_id=client.client_id, redirect_uri=p["redirect_uri"],
                                    state=p["state"] or None, code_challenge=p["code_challenge"],
                                    scope=_pack_scope((p["scope"] or SCOPE)[:100], sha256(cookie_val)),
                                    expires_at=_now() + PENDING_TTL)
    db.add(pending); db.commit()

    if settings.ms_login_ready:
        # Вход через Microsoft; state «mcp:<key>» обрабатывает /api/auth/callback и возвращает на /oauth/consent
        params = {"client_id": settings.ms_client_id, "response_type": "code", "redirect_uri": settings.ms_redirect_uri,
                  "response_mode": "query", "scope": "openid profile email", "state": f"mcp:{pending.key}", "prompt": "select_account"}
        resp = RedirectResponse(f"{MS_OAUTH.format(tenant=settings.ms_tenant_id)}/authorize?{urlencode(params)}", status_code=302)
    else:
        # Без Microsoft (локальная разработка): вход служебным токеном от имени владельца
        resp = RedirectResponse(f"/oauth/consent?k={pending.key}", status_code=302)
    # привязка запроса к браузеру инициатора: согласие примем только с этой cookie
    resp.set_cookie(COOKIE, cookie_val, max_age=int(PENDING_TTL.total_seconds()), httponly=True, samesite="lax",
                    secure=issuer(request).startswith("https"), path="/oauth")
    return resp


def _get_pending(db: Session, key: str, request: Request) -> models.McpPendingAuth:
    row = db.scalar(select(models.McpPendingAuth).where(models.McpPendingAuth.key == key))
    if row is None or _utc(row.expires_at) < _now():
        raise HTTPException(400, "запрос авторизации истёк — начните подключение в Claude заново")
    _, cb_hash = _unpack_scope(row)
    cookie = request.cookies.get(COOKIE, "")
    if not cb_hash or not cookie or not secrets.compare_digest(sha256(cookie), cb_hash):
        log.warning("oauth consent без cookie инициатора: key=%s… ip=%s", key[:6], _client_ip(request))
        raise HTTPException(400, "запрос авторизации начат в другом браузере — откройте подключение в Claude заново и подтвердите в том же окне")
    return row


PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CIS Planner · доступ для Claude</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f3efe6;color:#1f1b16;font:16px/1.5 Rubik,system-ui,sans-serif}
.card{background:#fffdf8;border:1px solid #d9d2c3;border-radius:14px;padding:32px 36px;max-width:440px;width:calc(100% - 32px);box-shadow:0 12px 40px rgba(60,40,20,.12)}
h1{font-family:"Source Serif 4",Georgia,serif;font-size:26px;margin:0 0 6px}
.muted{color:#6b6257;font-size:14px}
.host{font-family:ui-monospace,Menlo,monospace;background:#f3efe6;padding:2px 6px;border-radius:6px}
ul{padding-left:20px;margin:14px 0}
.row{display:flex;gap:10px;margin-top:22px}
button{flex:1;padding:12px 16px;border-radius:10px;border:1px solid #d9d2c3;background:#fff;font:inherit;font-weight:500;cursor:pointer;transition:transform .12s,box-shadow .12s}
button:hover{transform:translateY(-1px);box-shadow:0 6px 18px rgba(60,40,20,.15)}
button.primary{background:#9a3b1c;border-color:#9a3b1c;color:#fff}
input{width:100%;box-sizing:border-box;padding:11px 12px;border:1px solid #d9d2c3;border-radius:10px;font:inherit;margin-top:6px}
.err{color:#9a3b1c;font-size:14px;margin-top:10px}
</style></head><body><div class="card">__BODY__</div></body></html>"""


def _consent_body(pending: models.McpPendingAuth, client: models.McpClient | None, user: models.User | None, error: str = "") -> str:
    name = html.escape(client.client_name if client else "MCP client")
    host = html.escape(urlparse(pending.redirect_uri).hostname or pending.redirect_uri)
    where = (f"<p class=\"muted\">Код доступа будет отправлен на <span class=\"host\">{host}</span>. "
             "Если вы не начинали подключение сами — нажмите «Отклонить».</p>")
    if user is None:
        who = ("<p class=\"muted\">Вход через Microsoft не настроен. Введите служебный токен планнера (API_TOKEN) — "
               "доступ будет выдан от имени владельца.</p>"
               "<form method=\"post\"><label>Служебный токен<input type=\"password\" name=\"api_token\" autofocus required></label>"
               f"<input type=\"hidden\" name=\"k\" value=\"{html.escape(pending.key)}\">"
               f"<div class=\"err\">{html.escape(error)}</div>"
               "<div class=\"row\"><button type=\"submit\" name=\"decision\" value=\"deny\">Отклонить</button>"
               "<button type=\"submit\" name=\"decision\" value=\"allow\" class=\"primary\">Разрешить</button></div></form>")
        return f"<h1>CIS Planner</h1><p><b>{name}</b> просит доступ к вашему планнеру.</p>{where}{who}"
    return (f"<h1>CIS Planner</h1><p><b>{name}</b> просит доступ к планнеру от имени "
            f"<b>{html.escape(user.name)}</b> <span class=\"muted\">({html.escape(user.email)})</span>.</p>{where}"
            "<p class=\"muted\">Claude сможет:</p><ul class=\"muted\">"
            "<li>читать ваши направления, задачи, поручения и напоминания, строить сводки и отчёты по людям;</li>"
            "<li>создавать и менять направления и задачи, поручать задачи людям, ставить сроки и напоминания;</li>"
            "<li>отмечать выполненное, ставить направления на паузу или в архив.</li></ul>"
            "<p class=\"muted\">Удалять что-либо через Claude нельзя. Доступ отзывается удалением коннектора в Claude.</p>"
            f"<form method=\"post\"><input type=\"hidden\" name=\"k\" value=\"{html.escape(pending.key)}\">"
            "<div class=\"row\"><button type=\"submit\" name=\"decision\" value=\"deny\">Отклонить</button>"
            "<button type=\"submit\" name=\"decision\" value=\"allow\" class=\"primary\">Разрешить</button></div></form>")


@router.get("/oauth/consent", response_class=HTMLResponse)
def oauth_consent(k: str, request: Request, db: Session = Depends(get_db)):
    pending = _get_pending(db, k, request)
    client = db.scalar(select(models.McpClient).where(models.McpClient.client_id == pending.client_id))
    user = db.get(models.User, pending.user_id) if pending.user_id else None
    if user is None and settings.ms_login_ready:
        raise HTTPException(400, "сначала нужно войти через Microsoft — начните подключение в Claude заново")
    return HTMLResponse(PAGE.replace("__BODY__", _consent_body(pending, client, user)))


@router.post("/oauth/consent")
def oauth_consent_post(request: Request, k: str = Form(...), decision: str = Form(...), api_token: str = Form(""), db: Session = Depends(get_db)):
    pending = _get_pending(db, k, request)
    client = db.scalar(select(models.McpClient).where(models.McpClient.client_id == pending.client_id))
    if decision != "allow":
        db.delete(pending); db.commit()
        return _redirect_error(pending.redirect_uri, pending.state, "access_denied", "пользователь отклонил доступ")
    user = db.get(models.User, pending.user_id) if pending.user_id else None
    if user is None:
        if settings.ms_login_ready or not api_token or not secrets.compare_digest(api_token, settings.api_token):
            return HTMLResponse(PAGE.replace("__BODY__", _consent_body(pending, client, None, "Токен не подошёл")), status_code=401)
        user = owner_user(db)

    code = secrets.token_urlsafe(32)
    db.add(models.McpAuthCode(code_hash=sha256(code), client_id=pending.client_id, user_id=user.id, redirect_uri=pending.redirect_uri,
                              code_challenge=pending.code_challenge, expires_at=_now() + AUTH_CODE_TTL))
    db.add(models.ActivityLog(entity_type="McpClient", entity_id=client.id if client else 0, action="authorized",
                              payload={"user_id": user.id, "client": client.client_name if client else None,
                                       "redirect_host": urlparse(pending.redirect_uri).hostname}))
    redirect_uri, state = pending.redirect_uri, pending.state
    db.delete(pending); db.commit()
    sep = "&" if "?" in redirect_uri else "?"
    url = f"{redirect_uri}{sep}code={code}"
    if state:
        url += f"&state={quote(state)}"
    resp = RedirectResponse(url, status_code=302)
    resp.delete_cookie(COOKIE, path="/oauth")
    return resp


# ── Token endpoint ────────────────────────────────────────────────────────────

def _token_error(error: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=status, headers={"Cache-Control": "no-store"})


def _issue_tokens(db: Session, client_id: str, user_id: int) -> dict:
    access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = _now()
    db.add(models.McpToken(access_token_hash=sha256(access), refresh_token_hash=sha256(refresh), client_id=client_id, user_id=user_id,
                           access_expires_at=now + ACCESS_TOKEN_TTL, refresh_expires_at=now + REFRESH_TOKEN_TTL))
    db.commit()
    return {"access_token": access, "token_type": "Bearer", "expires_in": int(ACCESS_TOKEN_TTL.total_seconds()),
            "refresh_token": refresh, "scope": SCOPE}


def _verify_pkce(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(expected, challenge)


def _revoke_tokens_of_code(db: Session, row: models.McpAuthCode) -> int:
    """Повтор использованного кода (RFC 6749 §4.1.2): отозвать токены, выданные по нему.
    Прямой связи токен↔код в схеме нет — отзываем токены этого клиента и пользователя, выданные после появления кода."""
    issued_after = _utc(row.expires_at) - AUTH_CODE_TTL
    res = db.execute(update(models.McpToken).where(models.McpToken.client_id == row.client_id, models.McpToken.user_id == row.user_id,
                                                   models.McpToken.revoked.is_(False), models.McpToken.created_at >= issued_after)
                     .values(revoked=True), execution_options={"synchronize_session": False})
    db.commit()
    return res.rowcount or 0


@router.post("/oauth/token")
async def oauth_token(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    grant = form.get("grant_type", "")
    now = _now()

    if grant == "authorization_code":
        code, verifier = str(form.get("code", "")), str(form.get("code_verifier", ""))
        client_id, redirect_uri = str(form.get("client_id", "")), str(form.get("redirect_uri", ""))
        if not code or not verifier:
            return _token_error("invalid_request", "нужны code и code_verifier")
        if not client_id or not redirect_uri:
            return _token_error("invalid_request", "нужны client_id и redirect_uri (те же, что в запросе авторизации)")
        row = db.scalar(select(models.McpAuthCode).where(models.McpAuthCode.code_hash == sha256(code)))
        if row is None or _utc(row.expires_at) < now:
            return _token_error("invalid_grant", "код неверен или истёк")
        if row.used:
            n = _revoke_tokens_of_code(db, row)
            log.warning("oauth: повторное использование кода клиентом %s (user %s) — отозвано токенов: %s", row.client_id, row.user_id, n)
            return _token_error("invalid_grant", "код уже использован")
        if client_id != row.client_id:
            return _token_error("invalid_grant", "код выдан другому клиенту")
        if redirect_uri != row.redirect_uri:
            return _token_error("invalid_grant", "redirect_uri не совпадает")
        if not _verify_pkce(verifier, row.code_challenge):
            return _token_error("invalid_grant", "PKCE-проверка не пройдена")
        # одноразовость атомарно: кто первым пометил used — тот и получает токены (работает и на sqlite, и на Postgres)
        res = db.execute(update(models.McpAuthCode).where(models.McpAuthCode.id == row.id, models.McpAuthCode.used.is_(False)).values(used=True),
                         execution_options={"synchronize_session": False})
        db.commit()
        if res.rowcount != 1:
            return _token_error("invalid_grant", "код уже использован")
        return JSONResponse(_issue_tokens(db, row.client_id, row.user_id), headers={"Cache-Control": "no-store"})

    if grant == "refresh_token":
        refresh = str(form.get("refresh_token", ""))
        if not refresh:
            return _token_error("invalid_request", "нужен refresh_token")
        row = db.scalar(select(models.McpToken).where(models.McpToken.refresh_token_hash == sha256(refresh)))
        if row is None or row.revoked or _utc(row.refresh_expires_at) < now:
            return _token_error("invalid_grant", "refresh_token неверен или истёк")
        client_id = str(form.get("client_id", ""))
        if client_id and client_id != row.client_id:
            return _token_error("invalid_grant", "refresh_token выдан другому клиенту")
        if db.get(models.User, row.user_id) is None:
            return _token_error("invalid_grant", "учётная запись не найдена")
        # ротация: старая пара отзывается атомарно — параллельный повтор того же refresh получит 400
        res = db.execute(update(models.McpToken).where(models.McpToken.id == row.id, models.McpToken.revoked.is_(False)).values(revoked=True),
                         execution_options={"synchronize_session": False})
        db.commit()
        if res.rowcount != 1:
            return _token_error("invalid_grant", "refresh_token уже использован")
        return JSONResponse(_issue_tokens(db, row.client_id, row.user_id), headers={"Cache-Control": "no-store"})

    return _token_error("unsupported_grant_type", "поддерживаются authorization_code и refresh_token")


@router.post("/oauth/revoke")
async def oauth_revoke(request: Request, db: Session = Depends(get_db)):
    """RFC 7009: отзыв access- или refresh-токена (пара отзывается целиком). Всегда 200 — неизвестный токен не раскрываем."""
    form = await request.form()
    token = str(form.get("token", "")).strip()
    if token:
        h = sha256(token)
        res = db.execute(update(models.McpToken).where((models.McpToken.access_token_hash == h) | (models.McpToken.refresh_token_hash == h),
                                                       models.McpToken.revoked.is_(False)).values(revoked=True),
                         execution_options={"synchronize_session": False})
        db.commit()
        if res.rowcount:
            log.info("oauth: токен отозван через /oauth/revoke")
    return JSONResponse({}, headers={"Cache-Control": "no-store"})


def cleanup_oauth(db: Session, now: datetime | None = None) -> dict[str, int]:
    """Чистка просроченного (планировщик, раз в сутки): pending, коды, просроченные и давно отозванные токены,
    клиенты без единой выдачи старше суток."""
    now = now or _now()
    opts = {"synchronize_session": False}
    out: dict[str, int] = {}
    out["pending"] = db.execute(delete(models.McpPendingAuth).where(models.McpPendingAuth.expires_at < now), execution_options=opts).rowcount or 0
    out["codes"] = db.execute(delete(models.McpAuthCode).where(models.McpAuthCode.expires_at < now - timedelta(days=1)), execution_options=opts).rowcount or 0
    out["tokens"] = db.execute(delete(models.McpToken).where((models.McpToken.refresh_expires_at < now) |
                                                             ((models.McpToken.revoked.is_(True)) & (models.McpToken.created_at < now - timedelta(days=7)))),
                               execution_options=opts).rowcount or 0
    has_use = (exists().where(models.McpToken.client_id == models.McpClient.client_id)
               | exists().where(models.McpAuthCode.client_id == models.McpClient.client_id)
               | exists().where(models.McpPendingAuth.client_id == models.McpClient.client_id))
    out["clients"] = db.execute(delete(models.McpClient).where(models.McpClient.created_at < now - CLIENT_UNUSED_TTL, ~has_use),
                                execution_options=opts).rowcount or 0
    db.commit()
    return out


# ── Проверка Bearer-токена для /mcp ───────────────────────────────────────────

def bearer_user(request: Request, db: Session) -> models.User | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()
    if not token:
        return None
    if settings.api_token and secrets.compare_digest(token, settings.api_token):
        return owner_user(db)  # служебный токен = владелец (для Claude Code / отладки)
    row = db.scalar(select(models.McpToken).where(models.McpToken.access_token_hash == sha256(token)))
    now = _now()
    if row is None or row.revoked or _utc(row.access_expires_at) < now:
        return None
    user = db.get(models.User, row.user_id)
    if user is None:
        return None
    if row.last_used_at is None or now - _utc(row.last_used_at) >= LAST_USED_UPDATE_EVERY:
        row.last_used_at = now; db.commit()
    return user
