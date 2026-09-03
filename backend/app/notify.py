"""Каналы доставки напоминаний: Telegram и Microsoft Graph (почта + календарь Outlook).
Каждая функция бросает NotifyError с понятным текстом, если канал не настроен или ответ не 2xx."""
import time
from datetime import datetime, timedelta
import httpx
from .config import settings


class NotifyError(Exception):
    pass


# ---------------- Telegram ----------------
async def send_telegram(text: str, chat_id: str | None = None) -> None:
    if not settings.telegram_ready:
        raise NotifyError("Telegram не настроен: нужны TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(url, json={"chat_id": chat_id or settings.telegram_chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
    if r.status_code >= 300:
        raise NotifyError(f"Telegram {r.status_code}: {r.text[:200]}")


# ---------------- Microsoft Graph ----------------
_token: dict = {"value": "", "exp": 0.0}


async def _graph_token() -> str:
    if not settings.graph_ready:
        raise NotifyError("Microsoft Graph не настроен: нужны MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET, MS_MAILBOX")
    if _token["value"] and _token["exp"] > time.time() + 60:
        return _token["value"]
    url = f"https://login.microsoftonline.com/{settings.ms_tenant_id}/oauth2/v2.0/token"
    data = {"client_id": settings.ms_client_id, "client_secret": settings.ms_client_secret,
            "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(url, data=data)
    if r.status_code >= 300:
        raise NotifyError(f"Graph auth {r.status_code}: {r.text[:200]}")
    j = r.json()
    _token["value"] = j["access_token"]; _token["exp"] = time.time() + int(j.get("expires_in", 3600))
    return _token["value"]


async def _graph(method: str, path: str, json: dict | None = None) -> httpx.Response:
    tok = await _graph_token()
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.request(method, f"https://graph.microsoft.com/v1.0{path}", json=json,
                            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    if r.status_code >= 300:
        raise NotifyError(f"Graph {method} {path} → {r.status_code}: {r.text[:300]}")
    return r


async def send_email(subject: str, html: str, to: str | None = None) -> None:
    to = to or settings.notify_email_to or settings.ms_mailbox
    body = {"message": {"subject": subject, "body": {"contentType": "HTML", "content": html},
                        "toRecipients": [{"emailAddress": {"address": to}}]},
            "saveToSentItems": False}
    await _graph("POST", f"/users/{settings.ms_mailbox}/sendMail", body)


async def upsert_calendar_event(event_id: str | None, subject: str, html: str, start: datetime, minutes: int = 30) -> str:
    """Создаёт или обновляет событие в календаре ms_mailbox. Возвращает id события."""
    payload = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html},
        "start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": settings.app_timezone},
        "end": {"dateTime": (start + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": settings.app_timezone},
        "isReminderOn": True, "reminderMinutesBeforeStart": 15,
        "categories": ["Planner"],
    }
    base = f"/users/{settings.ms_mailbox}/events"
    if event_id:
        try:
            await _graph("PATCH", f"{base}/{event_id}", payload)
            return event_id
        except NotifyError as e:
            if "404" not in str(e):
                raise
    r = await _graph("POST", base, payload)
    return r.json()["id"]
