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
from . import digest as digest_mod
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


# ---------------- Поручения: «пора проверить» ----------------
def due_delegations(db: Session, now: datetime) -> list[models.Delegation]:
    q = select(models.Delegation).where(
        models.Delegation.status == models.DelegationStatus.open,
        models.Delegation.notified_at.is_(None),
        models.Delegation.check_at.is_not(None),
    )
    return [d for d in db.scalars(q).all() if _utc(d.check_at) <= now and d.task.status != models.TaskStatus.done]


def render_delegation(d: models.Delegation) -> tuple[str, str, str]:
    e = html.escape
    t = d.task
    link = _task_link(t)
    lines = [f"Поручено {_fmt(d.assigned_at)}" + (f", проверить {_fmt(d.check_at)}" if d.check_at else "")]
    if d.comment: lines.append(f"Что ждём: {e(d.comment)}")
    if t.deadline: lines.append(f"Дедлайн задачи: {t.deadline.strftime('%d.%m.%Y')}")
    subject = f"Planner · проверить у {d.person.name}: {t.title}"
    tg = f"👤 <b>Пора проверить у {e(d.person.name)}</b>\n{e(t.title)}\n" + "\n".join(lines) + (f"\n<a href=\"{link}\">Открыть в планнере</a>" if link else "")
    mail = f"<h3 style='margin:0 0 8px'>Пора проверить у {e(d.person.name)}: {e(t.title)}</h3><p>" + "<br>".join(lines) + "</p>" + (f"<p><a href='{link}'>Открыть в планнере</a></p>" if link else "")
    return subject, tg, mail


async def send_to_owner(subject: str, tg: str, mail: str, channels: list[str] | None = None) -> dict[str, str]:
    """Сообщение владельцу по доступным каналам (по умолчанию Telegram, иначе почта)."""
    channels = channels or (["telegram"] if settings.telegram_ready else ["email"] if settings.graph_ready else [])
    results: dict[str, str] = {}
    for ch in channels:
        try:
            if ch == "telegram": await send_telegram(tg)
            elif ch == "email": await send_email(subject, mail)
            else: raise NotifyError(f"неизвестный канал {ch}")
            results[ch] = "ok"
        except Exception as ex:  # noqa: BLE001
            results[ch] = str(ex)[:300]
    return results


async def process_delegations(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    handled = 0
    for d in due_delegations(db, now):
        results = await send_to_owner(*render_delegation(d))
        ok = any(v == "ok" for v in results.values())
        if ok or not results or now - _utc(d.check_at) > GIVE_UP_AFTER:
            d.notified_at = now
        db.add(models.ActivityLog(entity_type="Delegation", entity_id=d.id, action="check_reminder" if ok else "check_reminder_failed", payload=results))
        db.commit(); handled += 1
    return handled


# ---------------- Утренняя сводка ----------------
def digest_sent_today(db: Session, today) -> bool:
    last = db.scalars(select(models.ActivityLog).where(models.ActivityLog.entity_type == "Digest", models.ActivityLog.action == "sent")
                      .order_by(models.ActivityLog.created_at.desc()).limit(1)).first()
    return bool(last) and _utc(last.created_at).astimezone(TZ).date() >= today


def digest_due(db: Session, now: datetime) -> bool:
    if not settings.digest_time or not settings.digest_channel_list:
        return False
    local = now.astimezone(TZ)
    if settings.digest_weekdays_only and local.weekday() >= 5:
        return False
    hh, mm = (int(x) for x in settings.digest_time.split(":"))
    if (local.hour, local.minute) < (hh, mm):
        return False
    return not digest_sent_today(db, local.date())


async def send_digest(db: Session, now: datetime | None = None, channels: list[str] | None = None, manual: bool = False) -> dict[str, str]:
    now = now or datetime.now(timezone.utc)
    data = digest_mod.collect(db, now)
    results = await send_to_owner(*digest_mod.render(data), channels=channels or settings.digest_channel_list)
    ok = any(v == "ok" for v in results.values())
    db.add(models.ActivityLog(entity_type="Digest", entity_id=0, action=("sent_manual" if manual else "sent") if ok else "failed", payload=results))
    db.commit()
    return results


async def tick(db: Session) -> None:
    now = datetime.now(timezone.utc)
    await process_due(db, now)
    await process_delegations(db, now)
    if digest_due(db, now):
        res = await send_digest(db, now)
        log.info("digest sent: %s", res)


async def run_forever(stop: asyncio.Event) -> None:
    log.info("scheduler started, interval %ss, tz %s, digest at %s via %s", settings.scheduler_interval_sec, settings.app_timezone, settings.digest_time or "-", settings.digest_channels or "-")
    while not stop.is_set():
        try:
            db = SessionLocal()
            try:
                await tick(db)
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            log.exception("scheduler iteration failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.scheduler_interval_sec)
        except asyncio.TimeoutError:
            pass
