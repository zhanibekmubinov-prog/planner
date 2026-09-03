"""Утренняя сводка: состояние направлений (та же логика, что на Карте направлений во фронте),
дедлайны дня, просрочки, проверки поручений. Формирует текст для Telegram и HTML для почты."""
import html
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import models
from .config import settings

TZ = ZoneInfo(settings.app_timezone)
DAY = timedelta(days=1)
LEVELS = {"focus": "в фокусе", "ok": "норма", "fading": "ослабло", "lost": "упущено"}


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


@dataclass
class DirReport:
    direction: models.Direction
    total: int = 0; done: int = 0; in_progress: int = 0; waiting: int = 0; backlog: int = 0
    overdue: list = field(default_factory=list)
    idle_days: int | None = None
    score: int = 0
    level: str = "focus"
    reasons: list = field(default_factory=list)


def build_report(d: models.Direction, tasks: list[models.Task], now: datetime) -> DirReport:
    """Порт buildReport() из frontend/src/Overview.tsx — держать формулы одинаковыми."""
    r = DirReport(direction=d)
    mine = [t for t in tasks if any(x.id == d.id for x in t.directions)]
    open_ = [t for t in mine if t.status != models.TaskStatus.done]
    r.total = len(mine)
    r.done = sum(t.status == models.TaskStatus.done for t in mine)
    r.in_progress = sum(t.status == models.TaskStatus.in_progress for t in mine)
    r.waiting = sum(t.status == models.TaskStatus.waiting for t in mine)
    r.backlog = sum(t.status == models.TaskStatus.backlog for t in mine)
    today = now.astimezone(TZ).date()
    r.overdue = [t for t in open_ if t.deadline and t.deadline < today]
    check_due = [t for t in open_ if t.next_check_at and _utc(t.next_check_at) <= now]
    stamps = [_utc(t.updated_at or t.created_at) for t in mine]
    if stamps:
        r.idle_days = (now - max(stamps)).days

    score = 0.0
    if not mine:
        score += 45; r.reasons.append("нет ни одной задачи")
    elif r.idle_days is not None:
        score += min(r.idle_days, 30) / 30 * 40
        if r.idle_days >= 14: r.reasons.append(f"нет движения {r.idle_days} дн.")
        elif r.idle_days >= 7: r.reasons.append(f"тихо уже {r.idle_days} дн.")
    if r.overdue: score += min(len(r.overdue) * 15, 30); r.reasons.append(f"просрочено {len(r.overdue)}")
    if check_due: score += min(len(check_due) * 10, 20); r.reasons.append(f"пропущено проверок {len(check_due)}")
    if open_ and r.in_progress == 0: score += 10; r.reasons.append("ничего не в работе")
    if open_ and all(not t.deadline and not t.next_check_at for t in open_): score += 5; r.reasons.append("ни у одной задачи нет срока")
    if d.status == models.DirectionStatus.paused:
        score = min(score, 15); r.reasons = ["на паузе"]
    r.score = round(min(score, 100))
    r.level = "focus" if r.score < 20 else "ok" if r.score < 45 else "fading" if r.score < 70 else "lost"
    return r


def collect(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(TZ).date()
    directions = [d for d in db.scalars(select(models.Direction)).all() if d.status != models.DirectionStatus.archived]
    tasks = db.scalars(select(models.Task)).unique().all()
    open_ = [t for t in tasks if t.status != models.TaskStatus.done]
    reports = sorted((build_report(d, tasks, now) for d in directions),
                     key=lambda r: (r.direction.status == models.DirectionStatus.paused, -r.score))
    active = [r for r in reports if r.direction.status != models.DirectionStatus.paused]
    delegs = db.scalars(select(models.Delegation).where(models.Delegation.status == models.DelegationStatus.open)).all()
    return {
        "today": today,
        "reports": reports,
        "neglected": [r for r in active if r.level in ("fading", "lost")],
        "due_today": [t for t in open_ if t.deadline == today],
        "overdue": sorted([t for t in open_ if t.deadline and t.deadline < today], key=lambda t: t.deadline),
        "check_today": [t for t in open_ if t.next_check_at and _utc(t.next_check_at).astimezone(TZ).date() <= today],
        "deleg_due": [x for x in delegs if x.check_at and _utc(x.check_at).astimezone(TZ).date() <= today and x.task.status != models.TaskStatus.done],
        "open_count": len(open_),
    }


def _link(t: models.Task) -> str:
    return f"{settings.frontend_url.rstrip('/')}/?task={t.id}" if settings.frontend_url else ""


def render(data: dict) -> tuple[str, str, str]:
    """(subject, telegram_html, email_html)."""
    e = html.escape
    d: date = data["today"]
    title = f"Сводка на {d.strftime('%d.%m.%Y')}"
    neglected = data["neglected"]

    tg: list[str] = [f"☀️ <b>{title}</b>"]
    if neglected:
        tg.append("⚠️ <b>Требуют внимания:</b> " + ", ".join(e(r.direction.name) for r in neglected))
    else:
        tg.append("✅ Все направления в поле зрения")
    tg.append("")
    for r in data["reports"]:
        mark = {"focus": "🟢", "ok": "⚪", "fading": "🟠", "lost": "🔴"}[r.level]
        if r.direction.status == models.DirectionStatus.paused: mark = "⏸"
        line = f"{mark} <b>{e(r.direction.name)}</b> — открыто {r.total - r.done}, в работе {r.in_progress}"
        if r.overdue: line += f", просрочено {len(r.overdue)}"
        if r.reasons and r.level in ("fading", "lost"): line += f"\n    <i>{e(' · '.join(r.reasons))}</i>"
        tg.append(line)

    def tasks_block(header: str, items: list[models.Task], with_date=False):
        if not items: return
        tg.append(""); tg.append(f"<b>{header}</b>")
        for t in items[:10]:
            extra = f" (до {t.deadline.strftime('%d.%m')})" if with_date and t.deadline else ""
            link = _link(t)
            name = f"<a href=\"{link}\">{e(t.title)}</a>" if link else e(t.title)
            tg.append(f"• {name}{extra}")
        if len(items) > 10: tg.append(f"… и ещё {len(items) - 10}")

    tasks_block("📅 Дедлайн сегодня", data["due_today"])
    tasks_block("🚩 Просрочено", data["overdue"], with_date=True)
    tasks_block("🔁 Проверить сегодня", data["check_today"])
    if data["deleg_due"]:
        tg.append(""); tg.append("<b>👤 Спросить у людей</b>")
        for x in data["deleg_due"][:10]:
            tg.append(f"• {e(x.person.name)} — {e(x.task.title)}" + (f": {e(x.comment)}" if x.comment else ""))
    tg.append(""); tg.append(f"Всего открытых задач: {data['open_count']}")
    tg_text = "\n".join(tg)

    # HTML для почты — тот же текст, аккуратнее оформлен
    body = tg_text.replace("\n", "<br>")
    mail = f"<div style='font-family:Georgia,serif;font-size:15px;line-height:1.5'>{body}</div>"
    return f"Planner · {title}", tg_text, mail
