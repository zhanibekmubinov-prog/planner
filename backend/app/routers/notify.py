"""Служебные ручки: статус каналов и тестовая отправка."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..config import settings
from ..db import get_db
from ..notify import NotifyError, send_email, send_telegram, upsert_calendar_event
from ..scheduler import process_delegations, process_due, send_digest

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
async def test(data: TestIn):
    try:
        if data.channel == "telegram":
            await send_telegram("✅ Planner: тестовое сообщение. Канал Telegram работает.")
        elif data.channel == "email":
            await send_email("Planner: тест", "<p>Канал email работает.</p>")
        elif data.channel == "outlook_calendar":
            ev = await upsert_calendar_event(None, "Planner: тестовое событие", "<p>Календарь подключён.</p>", datetime.now(timezone.utc).astimezone())
            return {"ok": True, "event_id": ev}
        else:
            raise HTTPException(400, "channel must be telegram | email | outlook_calendar")
    except NotifyError as e:
        raise HTTPException(502, str(e))
    return {"ok": True}


@router.post("/run-now")
async def run_now(db: Session = Depends(get_db)):
    """Принудительно обработать напоминания и проверки поручений, у которых время уже наступило."""
    return {"reminders": await process_due(db), "delegations": await process_delegations(db)}


class DigestIn(BaseModel):
    channels: list[str] | None = None  # по умолчанию — DIGEST_CHANNELS


@router.post("/digest")
async def digest_now(data: DigestIn | None = None, db: Session = Depends(get_db)):
    """Отправить утреннюю сводку прямо сейчас (для проверки). Не влияет на ежедневную отправку."""
    return await send_digest(db, channels=(data.channels if data else None), manual=True)
