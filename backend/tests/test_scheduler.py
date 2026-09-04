"""Планировщик и уведомления (app/scheduler.py, notify.py) — по отчёту /root/review/backend_mcp_sched.md, С6–С8, В6.

Отправка Telegram/почты замокана через monkeypatch в app.scheduler; сеть не используется.
Тесты test_<severity>_* падают на текущем коде, test_ok_* — регрессия.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import models, scheduler
from app.config import settings
from app.notify import NotifyError
from tests.conftest import count, link_person, ok


@pytest.fixture
def outbox(monkeypatch):
    """Перехват отправок: список кортежей (канал, адресат, текст)."""
    sent = []

    async def fake_tg(text, chat_id=None): sent.append(("telegram", chat_id, text))
    async def fake_mail(subject, html, to=None): sent.append(("email", to, subject))
    monkeypatch.setattr(scheduler, "send_telegram", fake_tg)
    monkeypatch.setattr(scheduler, "send_email", fake_mail)
    monkeypatch.setattr(settings, "telegram_bot_token", "123:TEST")
    monkeypatch.setattr(settings, "telegram_chat_id", "1")
    return sent


def _reminder(db, task_id: int, fire_at: datetime, channels=("telegram",), recipient="owner") -> models.Reminder:
    r = models.Reminder(task_id=task_id, fire_at=fire_at, channels=list(channels), recipient=recipient)
    db.add(r); db.commit(); db.refresh(r)
    return r


def _log_actions(db, entity_type: str, entity_id: int) -> list[str]:
    return [a.action for a in db.scalars(select(models.ActivityLog).where(models.ActivityLog.entity_type == entity_type,
                                                                          models.ActivityLog.entity_id == entity_id)).all()]


NOW = datetime(2026, 9, 4, 6, 0, tzinfo=timezone.utc)  # 11:00 Asia/Oral, пятница


# ═══════════════════════ Средне ═══════════════════════

def test_S6_reminder_to_assignees_without_delegations_not_retried_forever(db, api, jack, outbox):
    """С6. recipient=assignees у задачи без поручений: results={'assignees': 'нет открытых поручений'} → ok=False,
    sent_at не ставится → новая строка failed каждую минуту сутки (1440 записей), потом gave_up.
    Ожидается: постоянная ошибка (нет адресата) закрывает напоминание с первого тика — sent_at выставлен,
    не более одной записи в activity_log за три тика."""
    t = api.task(jack, "Без поручений")
    r = _reminder(db, t["id"], NOW - timedelta(minutes=1), recipient="assignees")
    for i in range(3):
        asyncio.run(scheduler.process_due(db, NOW + timedelta(minutes=i)))
    db.refresh(r)
    actions = _log_actions(db, "Reminder", r.id)
    assert r.sent_at is not None, f"напоминание без адресата не закрыто после 3 тиков (sent_at=None), лог: {actions}"
    assert len(actions) <= 1, f"постоянная ошибка логируется на каждом тике: {actions}"


def test_S6_owner_without_chat_id_is_permanent_failure(db, api, nur, outbox):
    """С6. У владельца задачи (не админ) нет Telegram chat id: 'не указан Telegram chat id' — ошибка конфигурации,
    но ретраится каждую минуту сутки. Ожидается: закрывается с первого тика (sent_at) и не спамит лог."""
    t = api.task(nur, "Нурлан задача")
    r = _reminder(db, t["id"], NOW - timedelta(minutes=1), channels=("telegram",))
    for i in range(3):
        asyncio.run(scheduler.process_due(db, NOW + timedelta(minutes=i)))
    db.refresh(r)
    actions = _log_actions(db, "Reminder", r.id)
    assert r.sent_at is not None and len(actions) <= 1, \
        f"напоминание владельцу без chat id ретраится каждый тик: sent_at={r.sent_at}, лог={actions}"


def test_S8_exception_in_one_reminder_does_not_abort_others(db, api, jack, outbox, monkeypatch):
    """С8. Исключение вне per-channel try (render, битая связь, ошибка БД) прерывает process_due → tick →
    остальные напоминания, «пора проверить» и дайджест не обрабатываются, пока запись не починят руками.
    Ожидается: битая запись помечается/пропускается, остальные отправляются, process_due не бросает."""
    bad = api.task(jack, "Битая")
    good = api.task(jack, "Нормальная")
    rb = _reminder(db, bad["id"], NOW - timedelta(minutes=5))
    rg = _reminder(db, good["id"], NOW - timedelta(minutes=1))
    orig = scheduler.render

    def render(rem):
        if rem.id == rb.id:
            raise RuntimeError("render broke")
        return orig(rem)
    monkeypatch.setattr(scheduler, "render", render)
    crashed = None
    try:
        asyncio.run(scheduler.process_due(db, NOW))
    except Exception as e:  # noqa: BLE001
        crashed = e
    assert crashed is None, f"process_due упал целиком из-за одной битой записи: {type(crashed).__name__}: {crashed}"
    db.refresh(rg)
    assert any("Нормальная" in s[2] for s in outbox), f"второе напоминание не отправлено, outbox={outbox}"
    assert rg.sent_at is not None, "второе напоминание не помечено отправленным"


def test_S7_digest_failure_not_retried_every_minute(db, api, jack, outbox, monkeypatch):
    """С7. digest_sent_today учитывает только action='sent': при ошибке Telegram digest_due каждый тик True →
    ~900 попыток и вызовов API в день. Ожидается: после неудачной попытки следующая — не раньше чем через 15 минут."""
    async def boom(text, chat_id=None): raise NotifyError("Telegram 400: chat not found")
    monkeypatch.setattr(scheduler, "send_telegram", boom)
    monkeypatch.setattr(settings, "ms_tenant_id", "")  # почта выключена — только telegram
    jack.obj.telegram_chat_id = "777"; db.commit()
    t9 = datetime(2026, 9, 4, 9, 0, tzinfo=scheduler.TZ).astimezone(timezone.utc)
    assert scheduler.digest_due(db, t9, jack.obj) is True
    asyncio.run(scheduler.send_digest(db, jack.obj, t9))
    assert _log_actions(db, "Digest", jack.id) == ["failed"]
    assert scheduler.digest_due(db, t9 + timedelta(minutes=1), jack.obj) is False, \
        "через минуту после неудачной отправки дайджест снова due — повтор каждый тик до полуночи"


def test_S7_digest_only_within_window_after_digest_time(monkeypatch):
    """С7. digest_time_passed — «после времени», без окна: при позднем рестарте бэкенда дайджест уйдёт в 23:59.
    Ожидается: отправка только в окне [digest_time, digest_time + 2 ч)."""
    monkeypatch.setattr(settings, "digest_time", "08:30")
    monkeypatch.setattr(settings, "digest_weekdays_only", False)
    late = datetime(2026, 9, 4, 23, 59, tzinfo=scheduler.TZ)
    assert scheduler.digest_time_passed(late) is False, "в 23:59 дайджест (08:30) всё ещё считается «пора» — уйдёт после позднего рестарта"


def test_S8_check_reminder_without_channels_not_silently_lost(db, api, nur, outbox, monkeypatch):
    """С8/С6. «Пора проверить» владельцу без Telegram и без Graph: results={} → notified_at ставится,
    лог check_reminder_failed {} — напоминание тихо потеряно. Ожидается: не помечать как обработанное
    (или явно логировать причину 'нет каналов')."""
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "ms_tenant_id", "")
    p = api.person(nur, "Айдос", email="a@cis.kz")
    t = api.task(nur, "Нурлан задача")
    d = models.Delegation(task_id=t["id"], person_id=p["id"], check_at=NOW - timedelta(hours=1))
    db.add(d); db.commit(); db.refresh(d)
    asyncio.run(scheduler.process_delegations(db, NOW))
    db.refresh(d)
    rows = db.scalars(select(models.ActivityLog).where(models.ActivityLog.entity_type == "Delegation", models.ActivityLog.entity_id == d.id)).all()
    payloads = [r.payload for r in rows]
    assert d.notified_at is None or any(pl for pl in payloads), \
        f"«пора проверить» тихо потеряно: notified_at={d.notified_at}, лог без причины: {payloads}"


# ═══════════════════════ Высоко ═══════════════════════

def test_V6_httpx_logger_does_not_print_bot_token():
    """В6. logging.basicConfig(INFO) в main.py → httpx пишет 'POST https://api.telegram.org/bot<TOKEN>/sendMessage'
    в лог Railway. Ожидается: уровень логгера httpx ≥ WARNING."""
    import app.main  # noqa: F401 — basicConfig выполнен при импорте
    lvl = logging.getLogger("httpx").getEffectiveLevel()
    assert lvl >= logging.WARNING, f"логгер httpx на уровне {logging.getLevelName(lvl)} — токен бота уходит в лог при каждой отправке"


# ═══════════════════════ Регрессия ═══════════════════════

def test_ok_due_reminder_delivered_and_html_escaped(db, api, jack, outbox):
    """Регрессия. Напоминание с наступившим fire_at уходит владельцу (админ → глобальный chat id),
    заголовок экранируется для Telegram-HTML, sent_at и лог 'sent' проставлены."""
    t = api.task(jack, "Задача <b>&</b>")
    r = _reminder(db, t["id"], NOW - timedelta(minutes=1), channels=("telegram", "email"))
    n = asyncio.run(scheduler.process_due(db, NOW))
    db.refresh(r)
    assert n == 1 and r.sent_at is not None and _log_actions(db, "Reminder", r.id) == ["sent"]
    tg = [s for s in outbox if s[0] == "telegram"][0]
    assert tg[1] == "1" and "&lt;b&gt;&amp;&lt;/b&gt;" in tg[2], tg
    assert [s for s in outbox if s[0] == "email"][0][1] == "jack@cis.kz"


def test_ok_future_reminder_not_sent(db, api, jack, outbox):
    """Регрессия. Напоминание с fire_at в будущем не отправляется."""
    t = api.task(jack, "Позже")
    r = _reminder(db, t["id"], NOW + timedelta(hours=1))
    assert asyncio.run(scheduler.process_due(db, NOW)) == 0 and outbox == []
    db.refresh(r); assert r.sent_at is None


def test_ok_assignment_notice_to_assignee_not_to_self(db, api, jack, nur, outbox):
    """Регрессия. «Вам поручено» уходит исполнителю в Telegram; поручение самому себе — без уведомления."""
    link_person(db, nur, "Нурлан"); nur.obj.telegram_chat_id = "555"; db.commit()
    pj = link_person(db, jack, "Джек")
    pn = db.scalar(select(models.Person.id).where(models.Person.user_id == nur.id))
    t = api.task(jack, "Поручение")
    ok(api.c.post("/api/delegations", json={"task_id": t["id"], "person_id": pn}, headers=jack.h), 201)
    ok(api.c.post("/api/delegations", json={"task_id": t["id"], "person_id": pj}, headers=jack.h), 201)
    asyncio.run(scheduler.process_assignments(db, NOW))
    assert [(s[0], s[1]) for s in outbox] == [("telegram", "555")], outbox
    assert all(d.assigned_notified_at is not None for d in db.scalars(select(models.Delegation)).all())


def test_ok_check_reminder_sent_once(db, api, jack, outbox):
    """Регрессия. «Пора проверить» уходит владельцу один раз: notified_at выставлен, повторный тик — без отправки."""
    p = api.person(jack, "Асхат")
    t = api.task(jack, "Проверить")
    d = models.Delegation(task_id=t["id"], person_id=p["id"], check_at=NOW - timedelta(minutes=1), comment="ждём КП")
    db.add(d); db.commit()
    assert asyncio.run(scheduler.process_delegations(db, NOW)) == 1
    assert asyncio.run(scheduler.process_delegations(db, NOW + timedelta(minutes=1))) == 0
    assert len(outbox) == 1 and "Асхат" in outbox[0][2] and "ждём КП" in outbox[0][2]


def test_ok_digest_time_rules(monkeypatch):
    """Регрессия. digest_time_passed: до 08:30 — нет, в 08:30 — да; DIGEST_WEEKDAYS_ONLY — суббота нет."""
    monkeypatch.setattr(settings, "digest_time", "08:30")
    monkeypatch.setattr(settings, "digest_weekdays_only", False)
    assert scheduler.digest_time_passed(datetime(2026, 9, 4, 8, 29, tzinfo=scheduler.TZ)) is False
    assert scheduler.digest_time_passed(datetime(2026, 9, 4, 8, 30, tzinfo=scheduler.TZ)) is True
    monkeypatch.setattr(settings, "digest_weekdays_only", True)
    assert scheduler.digest_time_passed(datetime(2026, 9, 5, 9, 0, tzinfo=scheduler.TZ)) is False  # суббота


def test_ok_digest_sent_once_per_day(db, api, jack, outbox):
    """Регрессия. Успешный дайджест помечается 'sent' и в тот же день повторно не due."""
    jack.obj.telegram_chat_id = "777"; db.commit()
    api.task(jack, "Задача дня")
    t9 = datetime(2026, 9, 4, 9, 0, tzinfo=scheduler.TZ).astimezone(timezone.utc)
    assert scheduler.digest_due(db, t9, jack.obj) is True
    res = asyncio.run(scheduler.send_digest(db, jack.obj, t9))
    assert res.get("telegram") == "ok" and _log_actions(db, "Digest", jack.id) == ["sent"]
    assert scheduler.digest_due(db, t9 + timedelta(hours=1), jack.obj) is False
