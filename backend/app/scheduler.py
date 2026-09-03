"""Фоновый планировщик: раз в N секунд забирает напоминания с наступившим fire_at и рассылает по каналам.
Запускается внутри бэкенда (lifespan в main.py). Идемпотентен: отправленное помечается sent_at."""
import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import models
from .config import settings
from .db import SessionLocal
from .notify import NotifyError, send_email, send_telegram, upsert_calendar_event

log = logging.getLogger("planner.scheduler")
TZ = ZoneInfo(settings.app_timezone)
GIVE_UP_AFTER = timedelta(hours=24)
STATUS_RU = {"backlog": "бэклог", "in_progress": "в работе", "waiting": "ожидание", "done": "готово"}  # если сутки не удаётся отправить — помечаем и перестаём пытаться


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _fmt(dt: datetime | None) -> str:
    return _utc(dt).astimezone(TZ).strftime("%d.%m %H:%M") if dt else ""


def _task_link(task: models.Task) -> str:
    return f"{settings.frontend_url.rstrip('/')}/?task={task.id}" if settings.frontend_url else ""


def render(reminder: models.Reminder) -> tuple[str, str, str]:
    """Возвращает (subject, telegram_html, email_html) для напоминания."""
    t = reminder.task
    e = html.escape
    dirs = ", ".join(d.name for d in t.directions) or "без направления"
    open_deleg = [d for d in t.delegations if d.status == models.DelegationStatus.open]
    lines = []
    if reminder.message: lines.append(e(reminder.message))
    lines.append(f"Направление: {e(dirs)}")
    lines.append(f"Статус: {STATUS_RU.get(t.status.value, t.status.value)} · приоритет P{t.priority}")
    if t.deadline: lines.append(f"Дедлайн: {t.deadline.strftime('%d.%m.%Y')}")
    if open_deleg: lines.append("Поручено: " + ", ".join(e(d.person.name) for d in open_deleg))
    if t.tools: lines.append("Тулы: " + ", ".join(e(x.name) for x in t.tools))
    link = _task_link(t)
    subject = f"Planner · {t.title}"
    tg = f"⏰ <b>{e(t.title)}</b>\n" + "\n".join(lines) + (f"\n<a href=\"{link}\">Открыть в планнере</a>" if link else "")
    mail = f"<h3 style='margin:0 0 8px'>{e(t.title)}</h3><p>" + "<br>".join(lines) + "</p>" + (f"<p><a href='{link}'>Открыть в планнере</a></p>" if link else "")
    return subject, tg, mail


async def deliver(reminder: models.Reminder) -> dict[str, str]:
    """Отправляет по всем каналам напоминания. Возвращает {канал: 'ok' | текст ошибки}."""
    subject, tg, mail = render(reminder)
    results: dict[str, str] = {}
    for ch in reminder.channels or []:
        try:
            if ch == "telegram":
                await send_telegram(tg)
            elif ch == "email":
                await send_email(subject, mail)
            elif ch == "outlook_calendar":
                start = _utc(reminder.fire_at).astimezone(TZ)
                ev = await upsert_calendar_event(reminder.task.outlook_event_id, subject, mail, start)
                reminder.task.outlook_event_id = ev
            else:
                raise NotifyError(f"неизвестный канал {ch}")
            results[ch] = "ok"
        except Exception as ex:  # noqa: BLE001 — один упавший канал не должен ронять остальные
            results[ch] = str(ex)[:300]
    return results


def due_reminders(db: Session, now: datetime) -> list[models.Reminder]:
    q = select(models.Reminder).where(models.Reminder.sent_at.is_(None)).order_by(models.Reminder.fire_at)
    return [r for r in db.scalars(q).all() if _utc(r.fire_at) <= now]


async def process_due(db: Session, now: datetime | None = None) -> int:
    """Одна итерация. Возвращает число обработанных напоминаний."""
    now = now or datetime.now(timezone.utc)
    handled = 0
    for r in due_reminders(db, now):
        results = await deliver(r)
        ok = any(v == "ok" for v in results.values())
        expired = now - _utc(r.fire_at) > GIVE_UP_AFTER
        if ok or expired or not results:
            r.sent_at = now
        db.add(models.ActivityLog(entity_type="Reminder", entity_id=r.id,
                                  action="sent" if ok else ("gave_up" if expired else "failed"), payload=results))
        db.commit()
        handled += 1
        if not ok:
            log.warning("reminder %s not delivered: %s", r.id, results)
    return handled


async def run_forever(stop: asyncio.Event) -> None:
    log.info("scheduler started, interval %ss, tz %s", settings.scheduler_interval_sec, settings.app_timezone)
    while not stop.is_set():
        try:
            db = SessionLocal()
            try:
                await process_due(db)
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            log.exception("scheduler iteration failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.scheduler_interval_sec)
        except asyncio.TimeoutError:
            pass
