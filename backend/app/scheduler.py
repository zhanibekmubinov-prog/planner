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
    subject = f"CIS Planner · {t.title}"
    tg = f"⏰ <b>{e(t.title)}</b>\n" + "\n".join(lines) + (f"\n<a href=\"{link}\">Открыть в планнере</a>" if link else "")
    mail = f"<h3 style='margin:0 0 8px'>{e(t.title)}</h3><p>" + "<br>".join(lines) + "</p>" + (f"<p><a href='{link}'>Открыть в планнере</a></p>" if link else "")
    return subject, tg, mail


def chat_id_for(user: models.User | None) -> str | None:
    """Telegram владельца задачи; для админа-владельца планнера — глобальный TELEGRAM_CHAT_ID как запасной."""
    if user and user.telegram_chat_id: return user.telegram_chat_id
    if user and user.is_admin and settings.telegram_chat_id: return settings.telegram_chat_id
    return None


async def deliver(reminder: models.Reminder) -> dict[str, str]:
    """Отправляет по всем каналам напоминания владельцу задачи. Возвращает {канал: 'ok' | текст ошибки}."""
    subject, tg, mail = render(reminder)
    owner = reminder.task.owner
    results: dict[str, str] = {}
    for ch in reminder.channels or []:
        try:
            if ch == "telegram":
                chat = chat_id_for(owner)
                if not chat: raise NotifyError("у владельца задачи не указан Telegram chat id (Профиль)")
                await send_telegram(tg, chat)
            elif ch == "email":
                await send_email(subject, mail, owner.email if owner else None)
            elif ch == "outlook_calendar":
                start = _utc(reminder.fire_at).astimezone(TZ)
                ev = await upsert_calendar_event(reminder.task.outlook_event_id, subject, mail, start, mailbox=(owner.email if owner else None))
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
    subject = f"CIS Planner · проверить у {d.person.name}: {t.title}"
    tg = f"👤 <b>Пора проверить у {e(d.person.name)}</b>\n{e(t.title)}\n" + "\n".join(lines) + (f"\n<a href=\"{link}\">Открыть в планнере</a>" if link else "")
    mail = f"<h3 style='margin:0 0 8px'>Пора проверить у {e(d.person.name)}: {e(t.title)}</h3><p>" + "<br>".join(lines) + "</p>" + (f"<p><a href='{link}'>Открыть в планнере</a></p>" if link else "")
    return subject, tg, mail


async def send_to_user(user: models.User | None, subject: str, tg: str, mail: str, channels: list[str] | None = None) -> dict[str, str]:
    """Сообщение пользователю по доступным ему каналам (Telegram, если есть chat id; почта — если настроен Graph)."""
    if user is None: return {}
    chat = chat_id_for(user)
    if not channels:
        channels = ["telegram"] if (chat and settings.telegram_bot_token) else ["email"] if settings.graph_ready else []
    results: dict[str, str] = {}
    for ch in channels:
        try:
            if ch == "telegram":
                if not chat: raise NotifyError("нет Telegram chat id")
                await send_telegram(tg, chat)
            elif ch == "email": await send_email(subject, mail, user.email)
            else: raise NotifyError(f"неизвестный канал {ch}")
            results[ch] = "ok"
        except Exception as ex:  # noqa: BLE001
            results[ch] = str(ex)[:300]
    return results


async def process_delegations(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    handled = 0
    for d in due_delegations(db, now):
        results = await send_to_user(d.task.owner, *render_delegation(d))
        ok = any(v == "ok" for v in results.values())
        if ok or not results or now - _utc(d.check_at) > GIVE_UP_AFTER:
            d.notified_at = now
        db.add(models.ActivityLog(entity_type="Delegation", entity_id=d.id, action="check_reminder" if ok else "check_reminder_failed", payload=results))
        db.commit(); handled += 1
    return handled


def render_assignment(d: models.Delegation) -> tuple[str, str, str]:
    e = html.escape
    t = d.task; who = e(t.owner.name) if t.owner else "—"
    link = _task_link(t)
    lines = [f"От: {who}"]
    if d.comment: lines.append(f"Что ждут: {e(d.comment)}")
    if t.deadline: lines.append(f"Дедлайн: {t.deadline.strftime('%d.%m.%Y')}")
    if d.check_at: lines.append(f"Проверка: {_fmt(d.check_at)}")
    subject = f"CIS Planner · вам поручено: {t.title}"
    tg = f"📥 <b>Вам поручено</b>\n{e(t.title)}\n" + "\n".join(lines) + (f"\n<a href=\"{link}\">Открыть в планнере</a>" if link else "")
    mail = f"<h3 style='margin:0 0 8px'>Вам поручено: {e(t.title)}</h3><p>" + "<br>".join(lines) + "</p>" + (f"<p><a href='{link}'>Открыть в планнере</a></p>" if link else "")
    return subject, tg, mail


async def process_assignments(db: Session, now: datetime | None = None) -> int:
    """Новые поручения: сообщить исполнителю, если у него есть аккаунт или контакты."""
    now = now or datetime.now(timezone.utc)
    q = select(models.Delegation).where(models.Delegation.assigned_notified_at.is_(None), models.Delegation.status == models.DelegationStatus.open)
    handled = 0
    for d in db.scalars(q).all():
        p = d.person
        if p.user_id and p.user and p.user.id == d.task.owner_id:
            d.assigned_notified_at = now; db.commit(); continue  # поручил сам себе — не шумим
        results: dict[str, str] = {}
        subject, tg, mail = render_assignment(d)
        target_user = p.user
        chat = (target_user.telegram_chat_id if target_user else None) or p.telegram_chat_id
        email = (target_user.email if target_user else None) or p.email
        try:
            if chat and settings.telegram_bot_token: await send_telegram(tg, chat); results["telegram"] = "ok"
            elif email and settings.graph_ready: await send_email(subject, mail, email); results["email"] = "ok"
        except Exception as ex:  # noqa: BLE001
            results["error"] = str(ex)[:300]
        d.assigned_notified_at = now  # одна попытка: нет контактов — просто отмечаем
        db.add(models.ActivityLog(entity_type="Delegation", entity_id=d.id, action="assigned_notice", payload=results))
        db.commit(); handled += 1
    return handled


# ---------------- Утренняя сводка ----------------
def digest_sent_today(db: Session, today, user_id: int) -> bool:
    last = db.scalars(select(models.ActivityLog).where(models.ActivityLog.entity_type == "Digest", models.ActivityLog.action == "sent", models.ActivityLog.entity_id == user_id)
                      .order_by(models.ActivityLog.created_at.desc()).limit(1)).first()
    return bool(last) and _utc(last.created_at).astimezone(TZ).date() >= today


def digest_time_passed(now: datetime) -> bool:
    if not settings.digest_time or not settings.digest_channel_list:
        return False
    local = now.astimezone(TZ)
    if settings.digest_weekdays_only and local.weekday() >= 5:
        return False
    hh, mm = (int(x) for x in settings.digest_time.split(":"))
    return (local.hour, local.minute) >= (hh, mm)


def digest_due(db: Session, now: datetime, user: models.User) -> bool:
    return digest_time_passed(now) and user.digest_enabled and not digest_sent_today(db, now.astimezone(TZ).date(), user.id)


async def send_digest(db: Session, user: models.User, now: datetime | None = None, channels: list[str] | None = None, manual: bool = False) -> dict[str, str]:
    now = now or datetime.now(timezone.utc)
    data = digest_mod.collect(db, user, now)
    # по умолчанию — каналы из настроек, но только те, что у пользователя реально есть
    chans = channels or [c for c in settings.digest_channel_list if (c == "email" and settings.graph_ready) or (c == "telegram" and chat_id_for(user))]
    results = await send_to_user(user, *digest_mod.render(data), channels=chans)
    ok = any(v == "ok" for v in results.values())
    db.add(models.ActivityLog(entity_type="Digest", entity_id=user.id, action=("sent_manual" if manual else "sent") if ok else "failed", payload=results))
    db.commit()
    return results


async def tick(db: Session) -> None:
    now = datetime.now(timezone.utc)
    await process_due(db, now)
    await process_delegations(db, now)
    await process_assignments(db, now)
    if digest_time_passed(now):
        for u in db.scalars(select(models.User)).all():
            if digest_due(db, now, u) and (chat_id_for(u) or settings.graph_ready):
                res = await send_digest(db, u, now)
                log.info("digest → %s: %s", u.email, res)


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
