"""Фоновый планировщик: раз в N секунд забирает напоминания с наступившим fire_at и рассылает по каналам.
Запускается внутри бэкенда (lifespan в main.py). Идемпотентен: отправленное помечается sent_at.

v0.8 — устойчивость:
- каждая запись обрабатывается в своём try/except: битая запись логируется и пропускается, тик не обрывается (С8);
- claim-before-send: `UPDATE … SET sent_at=now WHERE id=… AND sent_at IS NULL` с проверкой rowcount — два экземпляра
  бэкенда (перекрытие деплоя на Railway) не отправят одно и то же дважды (С9); если отправка не удалась, метка снимается;
- ошибки делятся на постоянные (нет адресата, канал не настроен, Telegram/Graph 4xx) → сразу `gave_up` и запись
  остаётся закрытой, и временные (сеть, 5xx, исключение) → повтор не раньше чем через RETRY_BACKOFF, не дольше GIVE_UP_AFTER (С6);
- дайджест: только в окне [digest_time, digest_time+2ч); после неудачи — пауза DIGEST_RETRY, после 3 неудач за день — стоп (С7);
- раз в сутки housekeeping: purge_trash(30 дней) и cleanup_oauth().
"""
import asyncio
import html
import logging
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from . import models
from .config import settings
from .db import SessionLocal
from . import digest as digest_mod
from .notify import NotifyError, send_email, send_telegram, upsert_calendar_event

log = logging.getLogger("planner.scheduler")
TZ = ZoneInfo(settings.app_timezone)
GIVE_UP_AFTER = timedelta(hours=24)     # если сутки не удаётся отправить — помечаем gave_up и перестаём пытаться
RETRY_BACKOFF = timedelta(minutes=5)    # временная ошибка: следующая попытка не раньше чем через 5 минут
DIGEST_WINDOW = timedelta(hours=2)      # дайджест отправляется только в окне после digest_time
DIGEST_RETRY = timedelta(minutes=15)    # пауза между попытками дайджеста
DIGEST_MAX_FAILURES = 3                 # неудач за день, после которых дайджест на сегодня считается «сделанным»
STATUS_RU = {"backlog": "бэклог", "in_progress": "в работе", "waiting": "ожидание", "done": "готово"}
# признаки постоянной ошибки (конфигурация/адресат), ретраить бессмысленно
_PERMANENT_RE = re.compile(r"не настроен|не указан|нет Telegram|нет почты|нет открытых поручений|неизвестный канал|нет каналов|нет доступных каналов"
                           r"|(?:Telegram|Graph)[^\d]{0,40}\b4(?!29)\d\d\b", re.IGNORECASE)
_last_housekeeping: date | None = None


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _fmt(dt: datetime | None) -> str:
    return _utc(dt).astimezone(TZ).strftime("%d.%m %H:%M") if dt else ""


def _task_link(task: models.Task) -> str:
    return f"{settings.frontend_url.rstrip('/')}/?task={task.id}" if settings.frontend_url else ""


def _deleted(obj) -> bool:
    return getattr(obj, "deleted_at", None) is not None


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


def _person_chat(p: models.Person) -> str | None:
    return (p.user.telegram_chat_id if p.user and p.user.telegram_chat_id else None) or p.telegram_chat_id

def _person_email(p: models.Person) -> str | None:
    return (p.user.email if p.user else None) or p.email


async def deliver(reminder: models.Reminder) -> dict[str, str]:
    """Отправляет напоминание по всем каналам адресатам (recipient: owner | assignees | both).
    Возвращает {канал[/адресат]: 'ok' | текст ошибки}."""
    subject, tg, mail = render(reminder)
    owner = reminder.task.owner
    recipient = reminder.recipient or "owner"
    results: dict[str, str] = {}
    channels = reminder.channels or []
    if not channels:
        results["channels"] = "нет каналов: у напоминания не указан ни один канал"

    if recipient in ("owner", "both"):
        for ch in channels:
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

    if recipient in ("assignees", "both"):
        people = [d.person for d in reminder.task.delegations if d.status == models.DelegationStatus.open]
        # исполнитель-владелец уведомление уже получил как владелец
        people = [p for p in people if not (owner and p.user_id == owner.id and recipient == "both")]
        if not people:
            results["assignees"] = "у задачи нет открытых поручений"
        for p in people:
            for ch in channels:
                key = f"{ch}/{p.name}"
                try:
                    if ch == "telegram":
                        chat = _person_chat(p)
                        if not chat: raise NotifyError("нет Telegram chat id")
                        await send_telegram(tg, chat)
                    elif ch == "email":
                        to = _person_email(p)
                        if not to: raise NotifyError("нет почты")
                        await send_email(subject, mail, to)
                    elif ch == "outlook_calendar":
                        to = _person_email(p)
                        if not to: raise NotifyError("нет почты для календаря")
                        await upsert_calendar_event(None, subject, mail, _utc(reminder.fire_at).astimezone(TZ), mailbox=to)
                    else:
                        raise NotifyError(f"неизвестный канал {ch}")
                    results[key] = "ok"
                except Exception as ex:  # noqa: BLE001
                    results[key] = str(ex)[:300]
    return results


# ---------------- Общее: классификация ошибок, claim, backoff ----------------
def classify(results: dict[str, str]) -> str:
    """'ok' — хоть один канал доставил; 'permanent' — все ошибки постоянные (адресат/конфигурация); иначе 'transient'."""
    if any(v == "ok" for v in results.values()):
        return "ok"
    if results and all(_PERMANENT_RE.search(v or "") for v in results.values()):
        return "permanent"
    return "transient"


def _claim(db: Session, model, id_: int, col: str, now: datetime) -> bool:
    """Атомарно занять запись под отправку: UPDATE … WHERE <col> IS NULL. rowcount 0 = уже взял другой экземпляр."""
    res = db.execute(update(model).where(model.id == id_, getattr(model, col).is_(None)).values({col: now}),
                     execution_options={"synchronize_session": False})
    db.commit()
    return (res.rowcount or 0) == 1


def _last_attempt(db: Session, entity_type: str, entity_id: int, actions: tuple[str, ...]) -> datetime | None:
    row = db.scalars(select(models.ActivityLog).where(models.ActivityLog.entity_type == entity_type, models.ActivityLog.entity_id == entity_id,
                                                     models.ActivityLog.action.in_(actions))
                     .order_by(models.ActivityLog.created_at.desc()).limit(1)).first()
    return _utc(row.created_at) if row else None


def _in_backoff(db: Session, entity_type: str, entity_id: int, now: datetime, actions: tuple[str, ...]) -> bool:
    last = _last_attempt(db, entity_type, entity_id, actions)
    return last is not None and now - last < RETRY_BACKOFF


def _log(db: Session, entity_type: str, entity_id: int, action: str, payload: dict, now: datetime | None = None) -> None:
    # created_at = время тика (а не БД): backoff и «сделано сегодня» считаются от него же
    db.add(models.ActivityLog(entity_type=entity_type, entity_id=entity_id, action=action, payload=payload, created_at=now or datetime.now(timezone.utc)))


def _release(db: Session, model, id_: int, col: str) -> None:
    db.execute(update(model).where(model.id == id_).values({col: None}), execution_options={"synchronize_session": False})


# ---------------- Напоминания ----------------
def due_reminders(db: Session, now: datetime) -> list[models.Reminder]:
    q = select(models.Reminder).where(models.Reminder.sent_at.is_(None)).order_by(models.Reminder.fire_at)
    return [r for r in db.scalars(q).all() if _utc(r.fire_at) <= now]


async def process_due(db: Session, now: datetime | None = None) -> int:
    """Одна итерация. Возвращает число обработанных напоминаний (claim взят и попытка сделана)."""
    now = now or datetime.now(timezone.utc)
    handled = 0
    for r in due_reminders(db, now):
        rid, fire_at = r.id, _utc(r.fire_at)
        try:
            if _in_backoff(db, "Reminder", rid, now, ("failed",)):
                continue
            if not _claim(db, models.Reminder, rid, "sent_at", now):
                continue
            handled += 1
            r = db.get(models.Reminder, rid)
            expired = now - fire_at > GIVE_UP_AFTER
            if r.task is None or _deleted(r.task):
                _log(db, "Reminder", rid, "gave_up", {"reason": "задача удалена (в корзине)"}, now); db.commit()
                continue
            try:
                results = await deliver(r)
                kind = classify(results)
            except Exception as ex:  # noqa: BLE001 — рендер/связи/БД: считаем временной ошибкой
                results, kind = {"error": f"{type(ex).__name__}: {str(ex)[:200]}"}, "transient"
                log.exception("reminder %s: сбой обработки", rid)
            if kind == "ok":
                _log(db, "Reminder", rid, "sent", results, now)
            elif kind == "permanent" or expired:
                _log(db, "Reminder", rid, "gave_up", {**results, "reason": "постоянная ошибка" if kind == "permanent" else "не удалось доставить за 24 ч"}, now)
                log.warning("reminder %s gave up: %s", rid, results)
            else:
                _release(db, models.Reminder, rid, "sent_at")  # временно: снимаем метку, повтор через RETRY_BACKOFF
                _log(db, "Reminder", rid, "failed", results, now)
                log.warning("reminder %s not delivered (retry later): %s", rid, results)
            db.commit()
        except Exception:  # noqa: BLE001 — одна битая запись не должна останавливать остальные
            db.rollback()
            log.exception("reminder %s: необработанная ошибка, пропускаем", rid)
            try:
                _log(db, "Reminder", rid, "failed", {"error": "internal"}, now); db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
    return handled


# ---------------- Поручения: «пора проверить» ----------------
def due_delegations(db: Session, now: datetime) -> list[models.Delegation]:
    q = select(models.Delegation).where(
        models.Delegation.status == models.DelegationStatus.open,
        models.Delegation.notified_at.is_(None),
        models.Delegation.check_at.is_not(None),
    )
    return [d for d in db.scalars(q).all() if _utc(d.check_at) <= now and d.task.status != models.TaskStatus.done and not _deleted(d.task)]


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
    """Сообщение пользователю по доступным ему каналам (Telegram, если есть chat id; почта — если настроен Graph).
    Если каналов нет — возвращает причину (постоянная ошибка), а не пустой словарь."""
    if user is None: return {"user": "нет адресата (пользователь не найден)"}
    chat = chat_id_for(user)
    if not channels:
        channels = ["telegram"] if (chat and settings.telegram_bot_token) else ["email"] if settings.graph_ready else []
    if not channels:
        return {"channels": "нет доступных каналов: не указан Telegram chat id, почта (Graph) не настроена"}
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
        did, check_at = d.id, _utc(d.check_at)
        try:
            if _in_backoff(db, "Delegation", did, now, ("check_reminder_failed",)):
                continue
            if not _claim(db, models.Delegation, did, "notified_at", now):
                continue
            handled += 1
            d = db.get(models.Delegation, did)
            try:
                results = await send_to_user(d.task.owner, *render_delegation(d))
                kind = classify(results)
            except Exception as ex:  # noqa: BLE001
                results, kind = {"error": f"{type(ex).__name__}: {str(ex)[:200]}"}, "transient"
                log.exception("delegation %s: сбой «пора проверить»", did)
            if kind == "ok":
                _log(db, "Delegation", did, "check_reminder", results, now)
            elif kind == "permanent" or now - check_at > GIVE_UP_AFTER:
                _log(db, "Delegation", did, "check_reminder_gave_up", {**results, "reason": "постоянная ошибка" if kind == "permanent" else "не удалось за 24 ч"}, now)
                log.warning("delegation %s check reminder gave up: %s", did, results)
            else:
                _release(db, models.Delegation, did, "notified_at")
                _log(db, "Delegation", did, "check_reminder_failed", results, now)
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("delegation %s: необработанная ошибка, пропускаем", did)
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
        did = d.id
        try:
            if d.task is None or _deleted(d.task):
                continue
            if _in_backoff(db, "Delegation", did, now, ("assigned_notice_failed",)):
                continue
            if not _claim(db, models.Delegation, did, "assigned_notified_at", now):
                continue
            d = db.get(models.Delegation, did)
            p = d.person
            if p.user_id and p.user and p.user.id == d.task.owner_id:
                continue  # поручил сам себе — не шумим (метка уже стоит)
            handled += 1
            results: dict[str, str] = {}
            try:
                subject, tg, mail = render_assignment(d)
                target_user = p.user
                chat = (target_user.telegram_chat_id if target_user else None) or p.telegram_chat_id
                email = (target_user.email if target_user else None) or p.email
                if chat and settings.telegram_bot_token: await send_telegram(tg, chat); results["telegram"] = "ok"
                elif email and settings.graph_ready: await send_email(subject, mail, email); results["email"] = "ok"
                else: results["channels"] = "нет каналов: у исполнителя нет Telegram chat id / почты или каналы не настроены"
            except Exception as ex:  # noqa: BLE001
                results["error"] = str(ex)[:300]
            kind = classify(results)
            if kind == "transient" and now - _utc(d.assigned_at or now) <= GIVE_UP_AFTER:
                _release(db, models.Delegation, did, "assigned_notified_at")
                _log(db, "Delegation", did, "assigned_notice_failed", results, now)
            else:
                _log(db, "Delegation", did, "assigned_notice" if kind == "ok" else "assigned_notice_gave_up", results, now)
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("delegation %s: необработанная ошибка «вам поручено», пропускаем", did)
    return handled


# ---------------- Утренняя сводка ----------------
def _digest_today(db: Session, today, user_id: int) -> list[models.ActivityLog]:
    rows = db.scalars(select(models.ActivityLog).where(models.ActivityLog.entity_type == "Digest", models.ActivityLog.entity_id == user_id,
                                                      models.ActivityLog.action.in_(("sent", "failed")))
                      .order_by(models.ActivityLog.created_at.desc()).limit(DIGEST_MAX_FAILURES + 1)).all()
    return [r for r in rows if _utc(r.created_at).astimezone(TZ).date() >= today]


def digest_sent_today(db: Session, today, user_id: int, now: datetime | None = None) -> bool:
    """Сводка на сегодня «сделана»: отправлена; или неудач уже DIGEST_MAX_FAILURES; или последняя неудача была меньше DIGEST_RETRY назад."""
    rows = _digest_today(db, today, user_id)
    if any(r.action == "sent" for r in rows):
        return True
    fails = [r for r in rows if r.action == "failed"]
    if len(fails) >= DIGEST_MAX_FAILURES:
        return True
    if fails and now is not None and now - _utc(fails[0].created_at) < DIGEST_RETRY:
        return True
    return False


def digest_time_passed(now: datetime) -> bool:
    """Сейчас — окно отправки сводки: [digest_time, digest_time + DIGEST_WINDOW) по местному времени."""
    if not settings.digest_time or not settings.digest_channel_list:
        return False
    local = now.astimezone(TZ)
    if settings.digest_weekdays_only and local.weekday() >= 5:
        return False
    hh, mm = (int(x) for x in settings.digest_time.split(":"))
    start = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return start <= local < start + DIGEST_WINDOW


def digest_due(db: Session, now: datetime, user: models.User) -> bool:
    return digest_time_passed(now) and user.digest_enabled and not digest_sent_today(db, now.astimezone(TZ).date(), user.id, now)


async def send_digest(db: Session, user: models.User, now: datetime | None = None, channels: list[str] | None = None, manual: bool = False) -> dict[str, str]:
    now = now or datetime.now(timezone.utc)
    data = digest_mod.collect(db, user, now)
    # по умолчанию — каналы из настроек, но только те, что у пользователя реально есть
    chans = channels or [c for c in settings.digest_channel_list if (c == "email" and settings.graph_ready) or (c == "telegram" and chat_id_for(user))]
    results = await send_to_user(user, *digest_mod.render(data), channels=chans)
    ok = any(v == "ok" for v in results.values())
    db.add(models.ActivityLog(entity_type="Digest", entity_id=user.id, action=("sent_manual" if manual else "sent") if ok else ("failed_manual" if manual else "failed"),
                              payload=results, created_at=now))
    db.commit()
    return results


# ---------------- Housekeeping (раз в сутки) ----------------
def housekeeping(db: Session, now: datetime) -> None:
    global _last_housekeeping
    today = now.astimezone(TZ).date()
    if _last_housekeeping == today:
        return
    _last_housekeeping = today
    try:
        from .trash import purge_trash
        log.info("trash purge: %s", purge_trash(db, 30))
    except ImportError:
        log.info("trash purge: модуль app.trash ещё не подключён")
    except Exception:  # noqa: BLE001
        db.rollback(); log.exception("trash purge failed")
    try:
        from .routers.mcp_oauth import cleanup_oauth
        log.info("oauth cleanup: %s", cleanup_oauth(db, now))
    except Exception:  # noqa: BLE001
        db.rollback(); log.exception("oauth cleanup failed")


async def tick(db: Session) -> None:
    now = datetime.now(timezone.utc)
    for step in (process_due, process_delegations, process_assignments):
        try:
            await step(db, now)
        except Exception:  # noqa: BLE001 — один этап не должен ронять остальные
            db.rollback(); log.exception("scheduler step %s failed", step.__name__)
    if digest_time_passed(now):
        for u in db.scalars(select(models.User)).all():
            try:
                if digest_due(db, now, u) and (chat_id_for(u) or settings.graph_ready):
                    res = await send_digest(db, u, now)
                    log.info("digest → %s: %s", u.email, res)
            except Exception:  # noqa: BLE001
                db.rollback(); log.exception("digest for %s failed", u.email)
    housekeeping(db, now)


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
