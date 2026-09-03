"""OAuth 2.0 для MCP-коннектора Claude (та же схема, что в CIS Platform).

Claude (claude.ai, мобильное приложение, Claude Desktop) добавляет custom connector с URL
https://<backend>/mcp, сам регистрируется как публичный клиент (RFC 7591), отправляет пользователя
на /oauth/authorize → мы ведём его во вход через Microsoft → страница «Разрешить» → код → токены.

Метаданные: RFC 8414 (/.well-known/oauth-authorization-server) и RFC 9728 (/.well-known/oauth-protected-resource).
PKCE S256 обязателен. В базе хранятся только SHA-256 хеши кодов и токенов.
"""
import base64
import hashlib
import html
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import models
from ..auth import owner_user
from ..config import settings
from ..db import get_db

router = APIRouter(tags=["mcp"])

ACCESS_TOKEN_TTL = timedelta(hours=8)
REFRESH_TOKEN_TTL = timedelta(days=30)
AUTH_CODE_TTL = timedelta(minutes=10)
PENDING_TTL = timedelta(minutes=10)
SCOPE = "planner:full"
MS_OAUTH = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0"


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
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
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

def _valid_redirect_uri(uri) -> bool:
    return isinstance(uri, str) and (uri.startswith("https://") or uri.startswith("http://localhost") or uri.startswith("http://127.0.0.1"))


@router.post("/oauth/register", status_code=201)
async def oauth_register(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
    except Exception:
        data = {}
    uris = data.get("redirect_uris") or []
    if not uris or not all(_valid_redirect_uri(u) for u in uris):
        return JSONResponse({"error": "invalid_redirect_uri", "error_description": "redirect_uris: нужен список https-адресов"}, status_code=400)
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


@router.get("/oauth/authorize")
def oauth_authorize(request: Request, db: Session = Depends(get_db)):
    q = request.query_params
    p = {k: (q.get(k) or "").strip() for k in ("client_id", "redirect_uri", "response_type", "state", "code_challenge", "code_challenge_method", "scope")}
    client = db.scalar(select(models.McpClient).where(models.McpClient.client_id == p["client_id"]))
    if client is None:
        return JSONResponse({"error": "unauthorized_client", "error_description": "неизвестный client_id"}, status_code=400)
    if p["redirect_uri"] not in (client.redirect_uris or []):
        return JSONResponse({"error": "invalid_request", "error_description": "redirect_uri не зарегистрирован"}, status_code=400)
    if p["response_type"] != "code":
        return _redirect_error(p["redirect_uri"], p["state"], "unsupported_response_type", "поддерживается только code")
    if not p["code_challenge"] or p["code_challenge_method"] != "S256":
        return _redirect_error(p["redirect_uri"], p["state"], "invalid_request", "требуется PKCE S256")

    db.execute(delete(models.McpPendingAuth).where(models.McpPendingAuth.expires_at < _now()), execution_options={"synchronize_session": False})
    pending = models.McpPendingAuth(key=secrets.token_urlsafe(24), client_id=client.client_id, redirect_uri=p["redirect_uri"],
                                    state=p["state"] or None, code_challenge=p["code_challenge"], scope=p["scope"] or SCOPE,
                                    expires_at=_now() + PENDING_TTL)
    db.add(pending); db.commit()

    if settings.ms_login_ready:
        # Вход через Microsoft; state «mcp:<key>» обрабатывает /api/auth/callback и возвращает на /oauth/consent
        params = {"client_id": settings.ms_client_id, "response_type": "code", "redirect_uri": settings.ms_redirect_uri,
                  "response_mode": "query", "scope": "openid profile email", "state": f"mcp:{pending.key}", "prompt": "select_account"}
        return RedirectResponse(f"{MS_OAUTH.format(tenant=settings.ms_tenant_id)}/authorize?{urlencode(params)}", status_code=302)
    # Без Microsoft (локальная разработка): вход служебным токеном от имени владельца
    return RedirectResponse(f"/oauth/consent?k={pending.key}", status_code=302)


def _get_pending(db: Session, key: str) -> models.McpPendingAuth:
    row = db.scalar(select(models.McpPendingAuth).where(models.McpPendingAuth.key == key))
    if row is None or _utc(row.expires_at) < _now():
        raise HTTPException(400, "запрос авторизации истёк — начните подключение в Claude заново")
    return row


PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CIS Planner · доступ для Claude</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f3efe6;color:#1f1b16;font:16px/1.5 Rubik,system-ui,sans-serif}
.card{background:#fffdf8;border:1px solid #d9d2c3;border-radius:14px;padding:32px 36px;max-width:440px;width:calc(100% - 32px);box-shadow:0 12px 40px rgba(60,40,20,.12)}
h1{font-family:"Source Serif 4",Georgia,serif;font-size:26px;margin:0 0 6px}
.muted{color:#6b6257;font-size:14px}
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
    if user is None:
        who = ("<p class=\"muted\">Вход через Microsoft не настроен. Введите служебный токен планнера (API_TOKEN) — "
               "доступ будет выдан от имени владельца.</p>"
               "<form method=\"post\"><label>Служебный токен<input type=\"password\" name=\"api_token\" autofocus required></label>"
               f"<input type=\"hidden\" name=\"k\" value=\"{html.escape(pending.key)}\">"
               f"<div class=\"err\">{html.escape(error)}</div>"
               "<div class=\"row\"><button type=\"submit\" name=\"decision\" value=\"deny\">Отклонить</button>"
               "<button type=\"submit\" name=\"decision\" value=\"allow\" class=\"primary\">Разрешить</button></div></form>")
        return f"<h1>CIS Planner</h1><p><b>{name}</b> просит доступ к вашему планнеру.</p>{who}"
    return (f"<h1>CIS Planner</h1><p><b>{name}</b> просит доступ к планнеру от имени "
            f"<b>{html.escape(user.name)}</b> <span class=\"muted\">({html.escape(user.email)})</span>.</p>"
            "<p class=\"muted\">Claude сможет:</p><ul class=\"muted\">"
            "<li>читать ваши направления, задачи, поручения и напоминания, строить сводки и отчёты по людям;</li>"
            "<li>создавать и менять направления и задачи, поручать задачи людям, ставить сроки и напоминания;</li>"
            "<li>отмечать выполненное, ставить направления на паузу или в архив.</li></ul>"
            "<p class=\"muted\">Удалять что-либо через Claude нельзя. Доступ отзывается удалением коннектора в Claude.</p>"
            f"<form method=\"post\"><input type=\"hidden\" name=\"k\" value=\"{html.escape(pending.key)}\">"
            "<div class=\"row\"><button type=\"submit\" name=\"decision\" value=\"deny\">Отклонить</button>"
            "<button type=\"submit\" name=\"decision\" value=\"allow\" class=\"primary\">Разрешить</button></div></form>")


@router.get("/oauth/consent", response_class=HTMLResponse)
def oauth_consent(k: str, db: Session = Depends(get_db)):
    pending = _get_pending(db, k)
    client = db.scalar(select(models.McpClient).where(models.McpClient.client_id == pending.client_id))
    user = db.get(models.User, pending.user_id) if pending.user_id else None
    if user is None and settings.ms_login_ready:
        raise HTTPException(400, "сначала нужно войти через Microsoft — начните подключение в Claude заново")
    return HTMLResponse(PAGE.replace("__BODY__", _consent_body(pending, client, user)))


@router.post("/oauth/consent")
def oauth_consent_post(k: str = Form(...), decision: str = Form(...), api_token: str = Form(""), db: Session = Depends(get_db)):
    pending = _get_pending(db, k)
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
                              payload={"user_id": user.id, "client": client.client_name if client else None}))
    redirect_uri, state = pending.redirect_uri, pending.state
    db.delete(pending); db.commit()
    sep = "&" if "?" in redirect_uri else "?"
    url = f"{redirect_uri}{sep}code={code}"
    if state:
        url += f"&state={quote(state)}"
    return RedirectResponse(url, status_code=302)


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


@router.post("/oauth/token")
async def oauth_token(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    grant = form.get("grant_type", "")
    now = _now()

    if grant == "authorization_code":
        code, verifier = form.get("code", ""), form.get("code_verifier", "")
        if not code or not verifier:
            return _token_error("invalid_request", "нужны code и code_verifier")
        row = db.scalar(select(models.McpAuthCode).where(models.McpAuthCode.code_hash == sha256(code)))
        if row is None or row.used or _utc(row.expires_at) < now:
            return _token_error("invalid_grant", "код неверен или истёк")
        client_id = form.get("client_id", "")
        if client_id and client_id != row.client_id:
            return _token_error("invalid_grant", "код выдан другому клиенту")
        redirect_uri = form.get("redirect_uri", "")
        if redirect_uri and redirect_uri != row.redirect_uri:
            return _token_error("invalid_grant", "redirect_uri не совпадает")
        if not _verify_pkce(verifier, row.code_challenge):
            return _token_error("invalid_grant", "PKCE-проверка не пройдена")
        row.used = True
        db.execute(delete(models.McpAuthCode).where(models.McpAuthCode.expires_at < now), execution_options={"synchronize_session": False})
        return JSONResponse(_issue_tokens(db, row.client_id, row.user_id), headers={"Cache-Control": "no-store"})

    if grant == "refresh_token":
        refresh = form.get("refresh_token", "")
        if not refresh:
            return _token_error("invalid_request", "нужен refresh_token")
        row = db.scalar(select(models.McpToken).where(models.McpToken.refresh_token_hash == sha256(refresh)))
        if row is None or row.revoked or _utc(row.refresh_expires_at) < now:
            return _token_error("invalid_grant", "refresh_token неверен или истёк")
        if db.get(models.User, row.user_id) is None:
            return _token_error("invalid_grant", "учётная запись не найдена")
        row.revoked = True  # ротация: старая пара отзывается
        return JSONResponse(_issue_tokens(db, row.client_id, row.user_id), headers={"Cache-Control": "no-store"})

    return _token_error("unsupported_grant_type", "поддерживаются authorization_code и refresh_token")


# ── Проверка Bearer-токена для /mcp ───────────────────────────────────────────

def bearer_user(request: Request, db: Session) -> models.User | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()
    if settings.api_token and token == settings.api_token:
        return owner_user(db)  # служебный токен = владелец (для Claude Code / отладки)
    row = db.scalar(select(models.McpToken).where(models.McpToken.access_token_hash == sha256(token)))
    now = _now()
    if row is None or row.revoked or _utc(row.access_expires_at) < now:
        return None
    user = db.get(models.User, row.user_id)
    if user is None:
        return None
    row.last_used_at = now; db.commit()
    return user
