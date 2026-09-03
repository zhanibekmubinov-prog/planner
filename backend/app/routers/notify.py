"""Служебные ручки: статус каналов и тестовая отправка."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..config import settings
from ..db import get_db
from ..notify import NotifyError, send_email, send_telegram, upsert_calendar_event
from ..auth import current_user
from .. import models
from ..scheduler import chat_id_for, process_assignments, process_delegations, process_due, send_digest

router = APIRouter(prefix="/notify", tags=["notify"])


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
async def test(data: TestIn, user: models.User = Depends(current_user)):
    """Тест каналов — для текущего пользователя (его Telegram chat id и почта)."""
    try:
        if data.channel == "telegram":
            chat = chat_id_for(user)
            if not chat: raise NotifyError("У вас не указан Telegram chat id — заполните в Профиле")
            await send_telegram("✅ Planner: тестовое сообщение. Канал Telegram работает.", chat)
        elif data.channel == "email":
            await send_email("Planner: тест", "<p>Канал email работает.</p>", user.email)
        elif data.channel == "outlook_calendar":
            ev = await upsert_calendar_event(None, "Planner: тестовое событие", "<p>Календарь подключён.</p>", datetime.now(timezone.utc).astimezone(), mailbox=user.email)
            return {"ok": True, "event_id": ev}
        else:
            raise HTTPException(400, "channel must be telegram | email | outlook_calendar")
    except NotifyError as e:
        raise HTTPException(502, str(e))
    return {"ok": True}


@router.post("/run-now")
async def run_now(db: Session = Depends(get_db), _: models.User = Depends(current_user)):
    """Принудительно обработать напоминания, проверки и уведомления о поручениях."""
    return {"reminders": await process_due(db), "delegations": await process_delegations(db), "assignments": await process_assignments(db)}


class DigestIn(BaseModel):
    channels: list[str] | None = None  # по умолчанию — DIGEST_CHANNELS


@router.post("/digest")
async def digest_now(data: DigestIn | None = None, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Отправить МОЮ утреннюю сводку прямо сейчас (для проверки). Не влияет на ежедневную отправку."""
    return await send_digest(db, user, channels=(data.channels if data else None), manual=True)
