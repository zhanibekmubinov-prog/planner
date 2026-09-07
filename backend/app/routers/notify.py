"""Служебные ручки: статус каналов и тестовая отправка.
v0.8: /run-now — только админ (обработка глобальная, не «своя»); /test и /digest — не чаще 1 раза в минуту на пользователя
(проверка по activity_log, работает и при нескольких экземплярах бэкенда)."""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..config import settings
from ..db import get_db
from ..notify import NotifyError, send_email, send_telegram, upsert_calendar_event
from ..auth import current_user, require_admin
from .. import models
from ..scheduler import chat_id_for, process_assignments, process_delegations, process_due, send_digest

router = APIRouter(prefix="/notify", tags=["notify"])
MANUAL_RATE = timedelta(minutes=1)
ALLOWED_CHANNELS = ("telegram", "email", "outlook_calendar")


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _rate_limit(db: Session, user: models.User, action: str) -> None:
    """Не чаще одного ручного вызова в минуту: последняя запись NotifyManual/<action> этого пользователя в activity_log."""
    last = db.scalars(select(models.ActivityLog).where(models.ActivityLog.entity_type == "NotifyManual", models.ActivityLog.entity_id == user.id,
                                                      models.ActivityLog.action == action)
                      .order_by(models.ActivityLog.created_at.desc()).limit(1)).first()
    now = datetime.now(timezone.utc)
    if last and now - _utc(last.created_at) < MANUAL_RATE:
        wait = int((MANUAL_RATE - (now - _utc(last.created_at))).total_seconds()) + 1
        raise HTTPException(429, f"Не чаще одного раза в минуту — повторите через {wait} с", headers={"Retry-After": str(wait)})
    db.add(models.ActivityLog(entity_type="NotifyManual", entity_id=user.id, action=action, payload=None))
    db.commit()


@router.get("/status")
def status():
    return {
        "scheduler_enabled": settings.scheduler_enabled,
        "interval_sec": settings.scheduler_interval_sec,
        "timezone": settings.app_timezone,
        "telegram": settings.telegram_ready,
        "email": settings.graph_ready,
        "outlook_calendar": settings.graph_ready,
        "digest_time": settings.digest_time,
        "digest_channels": settings.digest_channel_list,
    }


class TestIn(BaseModel):
    channel: str = "telegram"


@router.post("/test")
async def test(data: TestIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Тест каналов — для текущего пользователя (его Telegram chat id и почта). Не чаще 1 раза в минуту."""
    if data.channel not in ALLOWED_CHANNELS:
        raise HTTPException(400, "channel must be telegram | email | outlook_calendar")
    _rate_limit(db, user, "test")
    try:
        if data.channel == "telegram":
            chat = chat_id_for(user)
            if not chat: raise NotifyError("У вас не указан Telegram chat id — заполните в Профиле")
            await send_telegram("✅ CIS Planner: тестовое сообщение. Канал Telegram работает.", chat)
        elif data.channel == "email":
            await send_email("CIS Planner: тест", "<p>Канал email работает.</p>", user.email)
        else:
            ev = await upsert_calendar_event(None, "CIS Planner: тестовое событие", "<p>Календарь подключён.</p>", datetime.now(timezone.utc).astimezone(), mailbox=user.email)
            return {"ok": True, "event_id": ev}
    except NotifyError as e:
        raise HTTPException(502, str(e))
    return {"ok": True}


@router.post("/run-now")
async def run_now(db: Session = Depends(get_db), _: models.User = Depends(require_admin)):
    """Принудительно обработать напоминания, проверки и уведомления о поручениях (всех пользователей) — только админ."""
    return {"reminders": await process_due(db), "delegations": await process_delegations(db), "assignments": await process_assignments(db)}


class DigestIn(BaseModel):
    channels: list[str] | None = None  # по умолчанию — DIGEST_CHANNELS


@router.post("/digest")
async def digest_now(data: DigestIn | None = None, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Отправить МОЮ утреннюю сводку прямо сейчас (для проверки). Не влияет на ежедневную отправку. Не чаще 1 раза в минуту."""
    chans = data.channels if data else None
    if chans is not None:
        bad = [c for c in chans if c not in ("telegram", "email")]
        if bad:
            raise HTTPException(400, f"channels: допустимы telegram, email (получено {bad})")
    _rate_limit(db, user, "digest")
    return await send_digest(db, user, channels=chans or None, manual=True)
