"""Инструменты MCP-коннектора CIS Planner для Claude.

Всё, что умеет планнер, кроме удаления: сводки по направлениям/задачам/людям, создание и правка направлений
и задач, поручения, сроки, напоминания. Права — как в REST: пользователь видит своё + порученное ему,
исполнитель может менять статус и писать отчёт по своему поручению.

Ссылки на сущности принимаются как id (число) или название (без учёта регистра, можно часть). Если совпадений
несколько — возвращается ошибка со списком кандидатов, чтобы Claude уточнил у человека.
"""
import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import digest, models
from .config import settings
from .crud import log
from .scope import (OWNER, is_assignee, my_person_id, project_access, stamp, task_access, visible_directions, visible_projects,
                    visible_tasks_query)

TZ = ZoneInfo(settings.app_timezone)
STATUS_RU = {"backlog": "бэклог", "in_progress": "в работе", "waiting": "ждём", "done": "выполнено"}
STATUS_ALIASES = {
    "backlog": "backlog", "бэклог": "backlog", "беклог": "backlog", "новая": "backlog", "todo": "backlog", "к выполнению": "backlog",
    "in_progress": "in_progress", "в работе": "in_progress", "делается": "in_progress", "начата": "in_progress", "in progress": "in_progress",
    "waiting": "waiting", "ждём": "waiting", "ждем": "waiting", "ожидание": "waiting", "на паузе": "waiting", "blocked": "waiting",
    "done": "done", "выполнено": "done", "готово": "done", "сделано": "done", "закрыта": "done", "завершена": "done",
}
DIR_STATUS_RU = {"active": "активно", "paused": "на паузе", "archived": "в архиве"}
DIR_STATUS_ALIASES = {"active": "active", "активно": "active", "активное": "active", "возобновить": "active",
                      "paused": "paused", "пауза": "paused", "на паузе": "paused",
                      "archived": "archived", "архив": "archived", "в архив": "archived", "в архиве": "archived"}
LEVEL_RU = {"focus": "в фокусе", "ok": "норма", "fading": "ослабло", "lost": "упущено"}
PALETTE = ["#9a3b1c", "#0f766e", "#1d4ed8", "#a16207", "#6d28d9", "#be185d", "#15803d", "#b45309", "#0e7490", "#4d7c0f"]


class ToolError(Exception):
    pass


# ── Вспомогательное ──────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _local(dt: datetime | None) -> str | None:
    return _utc(dt).astimezone(TZ).strftime("%Y-%m-%d %H:%M") if dt else None


def _today() -> date:
    return _now().astimezone(TZ).date()


def parse_date(value, field: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    s = str(value).strip()
    try:
        return date.fromisoformat(s[:10]) if len(s) >= 10 else date.fromisoformat(s)
    except ValueError:
        raise ToolError(f"{field}: ожидается дата в формате YYYY-MM-DD, получено «{s}». Сегодня {_today().isoformat()}.")


def parse_dt(value, field: str) -> datetime | None:
    """Дата-время в ISO. Если пришла только дата — 09:00 по местному времени. Без зоны — считаем местным (APP_TIMEZONE)."""
    if value in (None, ""):
        return None
    s = str(value).strip()
    try:
        if len(s) == 10:
            return datetime.combine(date.fromisoformat(s), time(9, 0), tzinfo=TZ).astimezone(timezone.utc)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise ToolError(f"{field}: ожидается дата-время ISO, например 2026-09-05T15:00, получено «{s}». Сейчас {_local(_now())} ({settings.app_timezone}).")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(timezone.utc)


def parse_status(value) -> models.TaskStatus:
    key = str(value or "").strip().lower()
    if key not in STATUS_ALIASES:
        raise ToolError(f"Неизвестный статус «{value}». Допустимо: backlog (бэклог), in_progress (в работе), waiting (ждём), done (выполнено).")
    return models.TaskStatus(STATUS_ALIASES[key])


def parse_priority(value) -> int:
    try:
        p = int(value)
    except (TypeError, ValueError):
        raise ToolError("priority: число от 1 (самый важный) до 5 (наименее важный)")
    if not 1 <= p <= 5:
        raise ToolError("priority: число от 1 (самый важный) до 5 (наименее важный)")
    return p


def _match(items, ref, label: str, name_attr: str = "name"):
    """Найти одну сущность по id или названию."""
    if ref is None or str(ref).strip() == "":
        raise ToolError(f"{label}: не указано")
    s = str(ref).strip()
    if s.isdigit():
        for it in items:
            if it.id == int(s):
                return it
        raise ToolError(f"{label} с id {s} не найдено среди доступных вам")
    low = s.lower()
    exact = [it for it in items if getattr(it, name_attr).strip().lower() == low]
    if len(exact) == 1:
        return exact[0]
    partial = [it for it in items if low in getattr(it, name_attr).lower()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        # мягкий поиск по словам: все слова запроса встречаются в названии
        words = [w for w in low.replace(",", " ").split() if len(w) > 2]
        partial = [it for it in items if words and all(w in getattr(it, name_attr).lower() for w in words)]
        if len(partial) == 1:
            return partial[0]
    if not partial:
        names = ", ".join(f"«{getattr(it, name_attr)}» (id {it.id})" for it in items[:25])
        raise ToolError(f"{label} «{s}» не найдено. Доступные: {names or 'пока нет ни одного'}")
    names = ", ".join(f"«{getattr(it, name_attr)}» (id {it.id})" for it in partial[:10])
    raise ToolError(f"{label} «{s}»: несколько совпадений — уточните: {names}")


def my_directions(db: Session, user: models.User, include_archived=True) -> list[models.Direction]:
    """Свои направления + открытые мне на просмотр/редактирование (access в объекте)."""
    dirs = [d for d in visible_directions(db, user) if d.access != "via"]
    if not include_archived:
        dirs = [d for d in dirs if d.status != models.DirectionStatus.archived]
    return dirs


def my_projects(db: Session, user: models.User, include_archived=True) -> list[models.Project]:
    ps = [p for p in visible_projects(db, user) if p.access != "via"]
    if not include_archived:
        ps = [p for p in ps if p.status != models.DirectionStatus.archived]
    return ps


def visible_tasks(db: Session, user: models.User) -> list[models.Task]:
    return db.scalars(visible_tasks_query(db, user).order_by(models.Task.priority, models.Task.deadline)).unique().all()


def all_people(db: Session) -> list[models.Person]:
    return db.scalars(select(models.Person).order_by(models.Person.name)).all()


def resolve_direction(db, user, ref) -> models.Direction:
    return _match(my_directions(db, user), ref, "Направление")


def resolve_task(db, user, ref) -> models.Task:
    return _match(visible_tasks(db, user), ref, "Задача", "title")


def resolve_person(db, ref) -> models.Person:
    return _match(all_people(db), ref, "Человек")


def resolve_project(db, user, ref, direction: models.Direction | None = None) -> models.Project:
    items = my_projects(db, user)
    if direction is not None:
        items = [p for p in items if p.direction_id == direction.id]
    return _match(items, ref, "Проект")


def _editable(obj, what: str):
    acc = getattr(obj, "access", OWNER)
    if acc not in (OWNER, "edit"):
        raise ToolError(f"{what} открыт(о) вам только на просмотр — менять нельзя")
    return obj


def _owned_task(db, user, ref) -> models.Task:
    t = resolve_task(db, user, ref)
    acc = task_access(db, user, t)
    if acc == "view":
        raise ToolError(f"Задача «{t.title}» открыта вам только на просмотр.")
    if acc not in (OWNER, "edit"):
        raise ToolError(f"Задача «{t.title}» поручена вам, а не создана вами — менять можно только статус (set_task_status) и отчёт (update_delegation).")
    return t


# ── Сериализация ─────────────────────────────────────────────────────────────

def person_brief(p: models.Person) -> dict:
    return {"id": p.id, "name": p.name, "email": p.email, "in_planner": p.user_id is not None}


def delegation_out(d: models.Delegation, with_task=False) -> dict:
    out = {"id": d.id, "person": d.person.name, "person_id": d.person_id, "status": d.status.value,
           "status_ru": "выполнено" if d.status == models.DelegationStatus.done else "открыто",
           "assigned_at": _local(d.assigned_at), "check_at": _local(d.check_at), "comment": d.comment, "report": d.report}
    if with_task:
        out["task"] = {"id": d.task.id, "title": d.task.title, "status": d.task.status.value, "deadline": d.task.deadline.isoformat() if d.task.deadline else None}
    return out


def task_brief(t: models.Task) -> dict:
    today = _today()
    open_ = t.status != models.TaskStatus.done
    return {
        "id": t.id, "title": t.title, "status": t.status.value, "status_ru": STATUS_RU[t.status.value], "priority": t.priority,
        "deadline": t.deadline.isoformat() if t.deadline else None,
        "overdue": bool(open_ and t.deadline and t.deadline < today),
        "next_check_at": _local(t.next_check_at),
        "directions": [d.name for d in t.directions],
        "project": t.project.name if t.project else None, "project_id": t.project_id,
        "assignees": [f"{d.person.name}{' ✓' if d.status == models.DelegationStatus.done else ''}" for d in t.delegations],
        "owner": t.owner.name if t.owner else None,
        "updated_at": _local(t.updated_at),
    }


def task_full(t: models.Task) -> dict:
    out = task_brief(t)
    out.update({
        "description": t.description,
        "created_at": _local(t.created_at),
        "delegations": [delegation_out(d) for d in t.delegations],
        "reminders": [{"id": r.id, "fire_at": _local(r.fire_at), "channels": r.channels, "recipient": r.recipient, "message": r.message,
                       "sent": r.sent_at is not None} for r in t.reminders],
        "tools": [{"id": x.id, "name": x.name, "type": x.type.value, "url": x.url} for x in t.tools],
    })
    return out


def direction_brief(d: models.Direction) -> dict:
    out = {"id": d.id, "name": d.name, "status": d.status.value, "status_ru": DIR_STATUS_RU[d.status.value], "goal": d.goal, "color": d.color}
    acc = getattr(d, "access", None)
    if acc and acc != OWNER:
        out["shared_by"] = d.owner.name if d.owner else None; out["access"] = acc
    return out


def project_brief(p: models.Project, tasks: list[models.Task] | None = None) -> dict:
    out = {"id": p.id, "name": p.name, "direction": p.direction.name, "direction_id": p.direction_id, "status": p.status.value,
           "status_ru": DIR_STATUS_RU[p.status.value], "goal": p.goal}
    if tasks is not None:
        mine = [t for t in tasks if t.project_id == p.id]
        out.update({"tasks_total": len(mine), "open": sum(1 for t in mine if t.status != models.TaskStatus.done),
                    "in_progress": sum(1 for t in mine if t.status == models.TaskStatus.in_progress),
                    "overdue": sum(1 for t in mine if t.status != models.TaskStatus.done and t.deadline and t.deadline < _today())})
    acc = getattr(p, "access", None)
    if acc and acc != OWNER:
        out["shared_by"] = p.owner.name if p.owner else None; out["access"] = acc
    return out


def report_out(r: digest.DirReport) -> dict:
    return {**direction_brief(r.direction), "attention_score": r.score, "attention_level": r.level, "attention_level_ru": LEVEL_RU[r.level],
            "reasons": r.reasons, "tasks_total": r.total, "done": r.done, "in_progress": r.in_progress, "waiting": r.waiting,
            "backlog": r.backlog, "overdue": len(r.overdue), "idle_days": r.idle_days}


# ── Чтение и сводки ───────────────────────────────────────────────────────────

def t_get_overview(db, user, a):
    data = digest.collect(db, user)
    return {
        "today": data["today"].isoformat(), "now": _local(_now()), "timezone": settings.app_timezone, "user": user.name,
        "verdict": ("Требуют внимания: " + ", ".join(r.direction.name for r in data["neglected"])) if data["neglected"] else "Все направления в поле зрения",
        "directions": [report_out(r) for r in data["reports"]],
        "due_today": [task_brief(t) for t in data["due_today"]],
        "overdue": [task_brief(t) for t in data["overdue"]],
        "check_today": [task_brief(t) for t in data["check_today"]],
        "ask_people_today": [delegation_out(x, with_task=True) for x in data["deleg_due"]],
        "assigned_to_me": [delegation_out(x, with_task=True) for x in data["inbox"]],
        "open_tasks_total": data["open_count"],
    }


def t_list_directions(db, user, a):
    dirs = my_directions(db, user, include_archived=bool(a.get("include_archived")))
    tasks = visible_tasks(db, user)
    now = _now()
    return {"directions": [report_out(digest.build_report(d, tasks, now)) for d in dirs]}


def t_get_direction_summary(db, user, a):
    d = resolve_direction(db, user, a.get("direction"))
    tasks = visible_tasks(db, user)
    r = digest.build_report(d, tasks, _now())
    mine = [t for t in tasks if any(x.id == d.id for x in t.directions)]
    projects = [p for p in my_projects(db, user) if p.direction_id == d.id]
    by_status = {s: [task_brief(t) for t in mine if t.status.value == s] for s in ("in_progress", "waiting", "backlog", "done")}
    people: dict[str, dict] = {}
    for t in mine:
        for dl in t.delegations:
            p = people.setdefault(dl.person.name, {"open": 0, "done": 0})
            p["done" if dl.status == models.DelegationStatus.done else "open"] += 1
    return {**report_out(r), "description": d.description,
            "projects": [project_brief(p, mine) for p in projects],
            "tasks_without_project": sum(1 for t in mine if not t.project_id),
            "tasks": by_status if a.get("include_done", True) else {k: v for k, v in by_status.items() if k != "done"},
            "people": people,
            "tools": [{"id": x.id, "name": x.name, "type": x.type.value} for x in d.tools],
            "mindmaps": db.scalar(select(models.MindMap.id).where(models.MindMap.direction_id == d.id).limit(1)) is not None}


def t_list_tasks(db, user, a):
    tasks = visible_tasks(db, user)
    scope = a.get("scope") or "mine"
    pid = my_person_id(db, user)
    if scope == "assigned_to_me":
        tasks = [t for t in tasks if t.owner_id != user.id and pid and any(d.person_id == pid for d in t.delegations)]
    elif scope == "mine":
        # мои + открытые мне (общие); порученные другими — отдельно (assigned_to_me)
        tasks = [t for t in tasks if t.owner_id == user.id or task_access(db, user, t) in (OWNER, "edit", "view")]
    d = None
    if a.get("direction"):
        d = resolve_direction(db, user, a["direction"])
        tasks = [t for t in tasks if any(x.id == d.id for x in t.directions)]
    if a.get("project"):
        p = resolve_project(db, user, a["project"], d)
        tasks = [t for t in tasks if t.project_id == p.id]
    if a.get("person"):
        p = resolve_person(db, a["person"])
        tasks = [t for t in tasks if any(dl.person_id == p.id for dl in t.delegations)]
    if a.get("status"):
        st = parse_status(a["status"])
        tasks = [t for t in tasks if t.status == st]
    elif not a.get("include_done"):
        tasks = [t for t in tasks if t.status != models.TaskStatus.done]
    today = _today()
    if a.get("overdue_only"):
        tasks = [t for t in tasks if t.status != models.TaskStatus.done and t.deadline and t.deadline < today]
    if a.get("due_within_days") is not None:
        lim = today + timedelta(days=int(a["due_within_days"]))
        tasks = [t for t in tasks if t.deadline and t.deadline <= lim]
    if a.get("query"):
        q = str(a["query"]).lower()
        tasks = [t for t in tasks if q in t.title.lower() or (t.description and q in t.description.lower())]
    limit = int(a.get("limit") or 50)
    return {"count": len(tasks), "tasks": [task_brief(t) for t in tasks[:limit]]}


def t_get_task(db, user, a):
    return task_full(resolve_task(db, user, a.get("task")))


def t_list_people(db, user, a):
    people = all_people(db)
    delegs = db.scalars(select(models.Delegation).join(models.Task).where(models.Task.owner_id == user.id)).all()
    counts: dict[int, dict] = {}
    for d in delegs:
        c = counts.setdefault(d.person_id, {"open": 0, "done": 0})
        c["done" if d.status == models.DelegationStatus.done else "open"] += 1
    return {"people": [{**person_brief(p), "delegated_by_me": counts.get(p.id, {"open": 0, "done": 0})} for p in people]}


def _done_at(db, task_id: int) -> datetime | None:
    rows = db.scalars(select(models.ActivityLog).where(models.ActivityLog.entity_type == "Task", models.ActivityLog.entity_id == task_id,
                                                        models.ActivityLog.action == "status_change").order_by(models.ActivityLog.created_at.desc())).all()
    for r in rows:
        if (r.payload or {}).get("to") == "done":
            return _utc(r.created_at)
    return None


def _person_stats(db, user, person: models.Person, delegs: list[models.Delegation]) -> dict:
    today, now = _today(), _now()
    tasks = list({d.task_id: d.task for d in delegs}.values())
    open_ = [t for t in tasks if t.status != models.TaskStatus.done]
    done = [t for t in tasks if t.status == models.TaskStatus.done]
    on_time = late = 0; durations = []
    for t in done:
        finished = _done_at(db, t.id)
        if t.deadline and finished:
            if finished.astimezone(TZ).date() <= t.deadline: on_time += 1
            else: late += 1
        assigned = min((_utc(d.assigned_at) for d in delegs if d.task_id == t.id), default=None)
        if finished and assigned:
            durations.append((finished - assigned).days)
    overdue = [t for t in open_ if t.deadline and t.deadline < today]
    check_due = [d for d in delegs if d.status == models.DelegationStatus.open and d.check_at and _utc(d.check_at) <= now and d.task.status != models.TaskStatus.done]
    stale = [t for t in open_ if (now - _utc(t.updated_at or t.created_at)).days >= 14]
    total = len(tasks)
    return {
        "person": person_brief(person),
        "tasks_total": total, "open": len(open_), "done": len(done),
        "completion_rate_pct": round(100 * len(done) / total) if total else None,
        "done_on_time": on_time, "done_late": late,
        "on_time_rate_pct": round(100 * on_time / (on_time + late)) if (on_time + late) else None,
        "avg_days_to_complete": round(sum(durations) / len(durations), 1) if durations else None,
        "overdue_now": len(overdue), "checks_due": len(check_due), "stale_14d": len(stale),
        "overdue_tasks": [task_brief(t) for t in overdue],
        "reports_recent": [{"task": d.task.title, "status": d.status.value, "report": d.report} for d in delegs if d.report][:10],
    }


def t_get_person_report(db, user, a):
    p = resolve_person(db, a.get("person"))
    delegs = db.scalars(select(models.Delegation).join(models.Task).where(models.Delegation.person_id == p.id, models.Task.owner_id == user.id)
                        .order_by(models.Delegation.assigned_at.desc())).all()
    stats = _person_stats(db, user, p, delegs)
    tasks = sorted({d.task_id: d.task for d in delegs}.values(), key=lambda t: (t.status == models.TaskStatus.done, t.priority, t.deadline or date.max))
    if not a.get("include_done", False):
        tasks = [t for t in tasks if t.status != models.TaskStatus.done]
    stats["tasks"] = [{**task_brief(t), "delegation": next((delegation_out(d) for d in delegs if d.task_id == t.id), None)} for t in tasks]
    return stats


def t_get_team_report(db, user, a):
    delegs = db.scalars(select(models.Delegation).join(models.Task).where(models.Task.owner_id == user.id)).all()
    by_person: dict[int, list] = {}
    for d in delegs:
        by_person.setdefault(d.person_id, []).append(d)
    rows = [_person_stats(db, user, db.get(models.Person, pid), ds) for pid, ds in by_person.items()]
    for r in rows:
        r.pop("overdue_tasks", None); r.pop("reports_recent", None)
    rows.sort(key=lambda r: (-r["overdue_now"], -r["checks_due"], -r["open"]))
    return {"today": _today().isoformat(), "people": rows,
            "note": "Учитываются только задачи, которые поручили ВЫ. on_time — по дате перевода задачи в «выполнено» относительно дедлайна."}


# ── Запись ───────────────────────────────────────────────────────────────────

def t_create_direction(db, user, a):
    name = str(a.get("name") or "").strip()
    if not name:
        raise ToolError("name: укажите название направления")
    existing = [d for d in my_directions(db, user) if d.name.strip().lower() == name.lower()]
    if existing:
        raise ToolError(f"Направление «{existing[0].name}» уже есть (id {existing[0].id}). Используйте его или выберите другое название.")
    used = {d.color for d in my_directions(db, user)}
    color = a.get("color") or next((c for c in PALETTE if c not in used), PALETTE[len(used) % len(PALETTE)])
    d = models.Direction(name=name, goal=a.get("goal"), description=a.get("description"), color=color, owner_id=user.id)
    db.add(d); db.flush(); log(db, d, "create", {"via": "mcp"}); db.commit()
    return {"created": True, "direction": direction_brief(d)}


def t_update_direction(db, user, a):
    d = _editable(resolve_direction(db, user, a.get("direction")), "Направление")
    changed = []
    for k in ("name", "goal", "description", "color"):
        if a.get(k) is not None:
            val = str(a[k]).strip()
            if k == "name" and not val:
                raise ToolError("name: название не может быть пустым")
            setattr(d, k, val or None); changed.append(k)
    if a.get("status") is not None:
        key = str(a["status"]).strip().lower()
        if key not in DIR_STATUS_ALIASES:
            raise ToolError("status: active (активно) | paused (пауза) | archived (архив)")
        d.status = models.DirectionStatus(DIR_STATUS_ALIASES[key]); changed.append("status")
    if not changed:
        raise ToolError("Нечего менять: передайте name, goal, description, color или status")
    log(db, d, "update", {"via": "mcp", "fields": changed}); db.commit()
    return {"updated": changed, "direction": direction_brief(d)}


def _add_delegation(db, user, task: models.Task, person: models.Person, check_at, comment) -> models.Delegation:
    for d in task.delegations:
        if d.person_id == person.id and d.status == models.DelegationStatus.open:
            if check_at is not None and d.check_at != check_at:
                d.check_at = check_at; d.notified_at = None
            if comment:
                d.comment = comment
            return d
    d = models.Delegation(task_id=task.id, person_id=person.id, check_at=check_at, comment=comment)
    db.add(d); db.flush(); log(db, d, "create", {"via": "mcp"})
    task.delegations.append(d)
    return d


def _find_or_create_person(db, ref, create: bool) -> models.Person:
    try:
        return resolve_person(db, ref)
    except ToolError as e:
        if create and "не найдено" in str(e):
            p = models.Person(name=str(ref).strip()); db.add(p); db.flush(); log(db, p, "create", {"via": "mcp"})
            return p
        raise


def t_create_task(db, user, a):
    title = str(a.get("title") or "").strip()
    if not title:
        raise ToolError("title: укажите название задачи")
    dirs = []
    for ref in a.get("directions") or []:
        try:
            dirs.append(resolve_direction(db, user, ref))
        except ToolError as e:
            if a.get("create_direction_if_missing") and "не найдено" in str(e):
                dirs.append(models.Direction(name=str(ref).strip(), owner_id=user.id, color=PALETTE[len(my_directions(db, user)) % len(PALETTE)]))
                db.add(dirs[-1]); db.flush(); log(db, dirs[-1], "create", {"via": "mcp"})
            else:
                raise
    project = None
    if a.get("project"):
        project = _editable(resolve_project(db, user, a["project"], dirs[0] if len(dirs) == 1 else None), "Проект")
        if all(x.id != project.direction_id for x in dirs):
            dirs.append(project.direction)
    for d in dirs:
        _editable(d, f"Направление «{d.name}»")
    # задача в чужом (открытом мне) направлении принадлежит его хозяину — доска остаётся его
    owner_id = user.id if (not dirs or any(x.owner_id == user.id for x in dirs)) else (project.owner_id if project and project.owner_id else dirs[0].owner_id or user.id)
    t = models.Task(title=title, description=a.get("description"), owner_id=owner_id,
                    status=parse_status(a["status"]) if a.get("status") else models.TaskStatus.backlog,
                    priority=parse_priority(a["priority"]) if a.get("priority") is not None else 3,
                    deadline=parse_date(a.get("deadline"), "deadline"), next_check_at=parse_dt(a.get("next_check_at"), "next_check_at"))
    t.directions = dirs
    t.project = project
    db.add(t); db.flush(); log(db, t, "create", {"via": "mcp", "by": user.id})
    check_at = parse_dt(a.get("check_at"), "check_at")
    for ref in a.get("assign_to") or []:
        p = _find_or_create_person(db, ref, bool(a.get("create_person_if_missing")))
        _add_delegation(db, user, t, p, check_at, a.get("comment"))
    if a.get("remind_at"):
        _add_reminder(db, t, a["remind_at"], a.get("remind_channels"), a.get("remind_message"), a.get("remind_recipient"))
    db.commit(); db.refresh(t)
    return {"created": True, "task": task_full(t), "link": f"{settings.frontend_url.rstrip('/')}/?task={t.id}" if settings.frontend_url else None}


def t_update_task(db, user, a):
    t = _owned_task(db, user, a.get("task"))
    changed = []
    if a.get("title") is not None: t.title = str(a["title"]).strip() or t.title; changed.append("title")
    if a.get("description") is not None: t.description = a["description"]; changed.append("description")
    if a.get("priority") is not None: t.priority = parse_priority(a["priority"]); changed.append("priority")
    if "deadline" in a: t.deadline = parse_date(a["deadline"], "deadline"); changed.append("deadline")
    if "next_check_at" in a: t.next_check_at = parse_dt(a["next_check_at"], "next_check_at"); changed.append("next_check_at")
    if a.get("status") is not None:
        old = t.status; t.status = parse_status(a["status"])
        if old != t.status: log(db, t, "status_change", {"from": old.value, "to": t.status.value, "by": user.id, "via": "mcp"}); changed.append("status")
    for ref in a.get("add_directions") or []:
        d = resolve_direction(db, user, ref)
        if d not in t.directions: t.directions.append(d); changed.append(f"+{d.name}")
    for ref in a.get("remove_directions") or []:
        d = resolve_direction(db, user, ref)
        if d in t.directions: t.directions.remove(d); changed.append(f"-{d.name}")
    if "project" in a:
        if a["project"] in (None, "", "null", "none", "без проекта"):
            t.project = None; changed.append("project: без проекта")
        else:
            p = _editable(resolve_project(db, user, a["project"]), "Проект")
            t.project = p
            if all(x.id != p.direction_id for x in t.directions): t.directions.append(p.direction)
            changed.append(f"project: {p.name}")
    if not changed:
        raise ToolError("Нечего менять: передайте title, description, priority, deadline, next_check_at, status, project, add_directions или remove_directions")
    if "status" not in changed: log(db, t, "update", {"via": "mcp", "fields": changed})
    db.commit(); db.refresh(t)
    return {"updated": changed, "task": task_full(t)}


def t_set_task_status(db, user, a):
    t = resolve_task(db, user, a.get("task"))
    acc = task_access(db, user, t)
    if acc == "view" or acc is None:
        raise ToolError("Менять статус может владелец задачи, редактор или исполнитель")
    old, t.status = t.status, parse_status(a.get("status"))
    log(db, t, "status_change", {"from": old.value, "to": t.status.value, "by": user.id, "via": "mcp"})
    if t.status == models.TaskStatus.done and a.get("close_delegations", True):
        for d in t.delegations:
            if d.status == models.DelegationStatus.open and (t.owner_id == user.id or d.person_id == my_person_id(db, user)):
                d.status = models.DelegationStatus.done
    db.commit(); db.refresh(t)
    return {"task": task_brief(t), "from": STATUS_RU[old.value], "to": STATUS_RU[t.status.value]}


def t_add_task_note(db, user, a):
    t = _owned_task(db, user, a.get("task"))
    text = str(a.get("text") or "").strip()
    if not text:
        raise ToolError("text: пустая заметка")
    stamp = _now().astimezone(TZ).strftime("%d.%m.%Y %H:%M")
    t.description = f"{(t.description or '').rstrip()}\n\n[{stamp}] {text}".strip()
    log(db, t, "update", {"via": "mcp", "fields": ["note"]}); db.commit()
    return {"task": t.id, "title": t.title, "description": t.description}


def t_delegate_task(db, user, a):
    t = _owned_task(db, user, a.get("task"))
    refs = a.get("people") or ([a["person"]] if a.get("person") else [])
    if not refs:
        raise ToolError("person или people: кому поручить")
    check_at = parse_dt(a.get("check_at"), "check_at")
    result = []
    for ref in refs:
        p = _find_or_create_person(db, ref, bool(a.get("create_person_if_missing")))
        result.append(_add_delegation(db, user, t, p, check_at, a.get("comment")))
    if "deadline" in a and a["deadline"]:
        t.deadline = parse_date(a["deadline"], "deadline")
    db.commit(); db.refresh(t)
    return {"task": task_brief(t), "delegations": [delegation_out(d) for d in result],
            "note": "Исполнителю в течение минуты уйдёт уведомление «Вам поручено» (Telegram или почта), если он есть в планнере."}


def t_update_delegation(db, user, a):
    t = resolve_task(db, user, a.get("task"))
    pid = my_person_id(db, user)
    if a.get("person"):
        p = resolve_person(db, a["person"])
        d = next((x for x in t.delegations if x.person_id == p.id), None)
    else:
        d = next((x for x in t.delegations if x.person_id == pid), None) if t.owner_id != user.id else (t.delegations[0] if len(t.delegations) == 1 else None)
    if d is None:
        names = ", ".join(x.person.name for x in t.delegations) or "нет поручений"
        raise ToolError(f"Не удалось определить поручение по задаче «{t.title}». Укажите person. Исполнители: {names}")
    is_owner, is_mine = t.owner_id == user.id, d.person_id == pid
    if not (is_owner or is_mine):
        raise ToolError("Менять поручение может владелец задачи или сам исполнитель")
    changed = []
    if a.get("status") is not None:
        key = str(a["status"]).strip().lower()
        st = "done" if key in ("done", "выполнено", "готово", "сделано", "закрыто") else "open" if key in ("open", "открыто", "вернуть", "снова") else None
        if st is None: raise ToolError("status: done (выполнено) | open (открыто)")
        d.status = models.DelegationStatus(st); changed.append("status")
    if a.get("report") is not None: d.report = a["report"]; changed.append("report")
    if is_owner:
        if "check_at" in a: d.check_at = parse_dt(a["check_at"], "check_at"); d.notified_at = None; changed.append("check_at")
        if a.get("comment") is not None: d.comment = a["comment"]; changed.append("comment")
    elif "check_at" in a or a.get("comment") is not None:
        raise ToolError("Исполнитель может менять только status и report")
    if not changed:
        raise ToolError("Нечего менять: status, report, check_at, comment")
    log(db, d, "report" if "report" in changed else "update", {"by": user.id, "via": "mcp", "fields": changed}); db.commit()
    return {"updated": changed, "delegation": delegation_out(d, with_task=True)}


def _add_reminder(db, task: models.Task, fire_at, channels, message, recipient) -> models.Reminder:
    when = parse_dt(fire_at, "fire_at")
    if when is None:
        raise ToolError("fire_at: когда напомнить (ISO дата-время)")
    chans = channels or ["telegram"]
    bad = [c for c in chans if c not in ("telegram", "email", "outlook_calendar")]
    if bad:
        raise ToolError(f"channels: допустимы telegram, email, outlook_calendar (получено {bad})")
    rec = recipient or "owner"
    if rec not in ("owner", "assignees", "both"):
        raise ToolError("recipient: owner (мне) | assignees (исполнителям) | both (обоим)")
    r = models.Reminder(task_id=task.id, fire_at=when, channels=list(chans), message=message, recipient=rec)
    db.add(r); db.flush(); log(db, r, "create", {"via": "mcp"})
    return r


def t_add_reminder(db, user, a):
    t = _owned_task(db, user, a.get("task"))
    r = _add_reminder(db, t, a.get("fire_at"), a.get("channels"), a.get("message"), a.get("recipient"))
    db.commit()
    return {"task": t.title, "reminder": {"id": r.id, "fire_at": _local(r.fire_at), "channels": r.channels, "recipient": r.recipient, "message": r.message}}


def t_create_person(db, user, a):
    name = str(a.get("name") or "").strip()
    if not name:
        raise ToolError("name: имя человека")
    dup = [p for p in all_people(db) if p.name.strip().lower() == name.lower()]
    if dup:
        raise ToolError(f"«{dup[0].name}» уже есть в справочнике (id {dup[0].id})")
    p = models.Person(name=name, email=(a.get("email") or None), telegram_chat_id=(a.get("telegram_chat_id") or None), note=a.get("note"))
    if p.email:
        u = db.scalar(select(models.User).where(models.User.email == p.email.lower()))
        if u and not db.scalar(select(models.Person).where(models.Person.user_id == u.id)): p.user_id = u.id
    db.add(p); db.flush(); log(db, p, "create", {"via": "mcp"}); db.commit()
    return {"created": True, "person": person_brief(p)}


def t_add_tool(db, user, a):
    name = str(a.get("name") or "").strip()
    if not name:
        raise ToolError("name: название тула")
    typ = a.get("type") or "other"
    if typ not in [x.value for x in models.ToolType]:
        raise ToolError("type: google_sheet | excel_sharepoint | telegram_bot | notion | other")
    tool = models.Tool(name=name, type=models.ToolType(typ), url=a.get("url"), note=a.get("note"), owner_id=user.id)
    tool.tasks = [_owned_task(db, user, r) for r in a.get("tasks") or []]
    tool.directions = [resolve_direction(db, user, r) for r in a.get("directions") or []]
    db.add(tool); db.flush(); log(db, tool, "create", {"via": "mcp"}); db.commit()
    return {"created": True, "tool": {"id": tool.id, "name": tool.name, "type": tool.type.value, "url": tool.url,
                                      "tasks": [t.title for t in tool.tasks], "directions": [d.name for d in tool.directions]}}



# ── Проекты (v0.6) ────────────────────────────────────────────────────────────

def t_list_projects(db, user, a):
    ps = my_projects(db, user, include_archived=bool(a.get("include_archived")))
    if a.get("direction"):
        d = resolve_direction(db, user, a["direction"])
        ps = [p for p in ps if p.direction_id == d.id]
    tasks = visible_tasks(db, user)
    return {"projects": [project_brief(p, tasks) for p in ps]}


def t_create_project(db, user, a):
    name = str(a.get("name") or "").strip()
    if not name:
        raise ToolError("name: укажите название проекта")
    d = _editable(resolve_direction(db, user, a.get("direction")), "Направление")
    dup = [p for p in my_projects(db, user) if p.direction_id == d.id and p.name.strip().lower() == name.lower()]
    if dup:
        raise ToolError(f"Проект «{dup[0].name}» в направлении «{d.name}» уже есть (id {dup[0].id}).")
    p = models.Project(name=name, goal=a.get("goal"), description=a.get("description"), color=a.get("color"), direction_id=d.id,
                       owner_id=d.owner_id if d.owner_id else user.id)
    db.add(p); db.flush(); log(db, p, "create", {"via": "mcp", "by": user.id}); db.commit(); db.refresh(p)
    stamp(p, project_access(db, user, p))
    return {"created": True, "project": project_brief(p)}


def t_update_project(db, user, a):
    p = _editable(resolve_project(db, user, a.get("project")), "Проект")
    changed = []
    for k in ("name", "goal", "description", "color"):
        if a.get(k) is not None:
            val = str(a[k]).strip()
            if k == "name" and not val:
                raise ToolError("name: название не может быть пустым")
            setattr(p, k, val or None); changed.append(k)
    if a.get("status") is not None:
        key = str(a["status"]).strip().lower()
        if key not in DIR_STATUS_ALIASES:
            raise ToolError("status: active (активно) | paused (пауза) | archived (архив)")
        p.status = models.DirectionStatus(DIR_STATUS_ALIASES[key]); changed.append("status")
    if not changed:
        raise ToolError("Нечего менять: передайте name, goal, description, color или status")
    log(db, p, "update", {"via": "mcp", "fields": changed}); db.commit(); db.refresh(p)
    return {"updated": changed, "project": project_brief(p)}


# ── Совместный доступ (v0.6) ─────────────────────────────────────────────────

def _share_target(db, user, a):
    et = str(a.get("entity_type") or "").strip().lower()
    ref = a.get("entity")
    if et in ("direction", "направление"):
        obj, et = resolve_direction(db, user, ref), "direction"
    elif et in ("project", "проект"):
        obj, et = resolve_project(db, user, ref), "project"
    elif et in ("task", "задача"):
        obj, et = resolve_task(db, user, ref), "task"
    else:
        raise ToolError("entity_type: direction | project | task")
    if obj.owner_id != user.id:
        raise ToolError("Управлять доступом может только владелец")
    return et, obj


def t_share_access(db, user, a):
    from .routers.shares import find_or_invite_user
    from fastapi import HTTPException
    et, obj = _share_target(db, user, a)
    perm = str(a.get("permission") or "view").strip().lower()
    perm = {"view": "view", "просмотр": "view", "смотреть": "view", "edit": "edit", "редактирование": "edit", "редактировать": "edit"}.get(perm)
    if not perm:
        raise ToolError("permission: view (смотреть) | edit (редактировать)")
    try:
        target = find_or_invite_user(db, str(a.get("email") or ""))
    except HTTPException as e:
        raise ToolError(e.detail)
    if target.id == user.id:
        raise ToolError("Это вы сами")
    sh = db.scalar(select(models.Share).where(models.Share.entity_type == et, models.Share.entity_id == obj.id, models.Share.user_id == target.id))
    is_new = sh is None
    if sh:
        sh.permission = perm
    else:
        sh = models.Share(entity_type=et, entity_id=obj.id, user_id=target.id, permission=perm, granted_by=user.id); db.add(sh)
    log(db, obj, "share", {"via": "mcp", "to": target.email, "permission": perm})
    if is_new:  # уведомление «вам открыли …» — в отдельном потоке, чтобы не держать ответ Claude
        import asyncio, threading
        from types import SimpleNamespace
        from .routers.shares import notify_share, share_notice
        subject, tg, mail = share_notice(et, obj, user, perm)
        snap = SimpleNamespace(email=target.email, telegram_chat_id=target.telegram_chat_id, is_admin=False, name=target.name)
        threading.Thread(target=lambda: asyncio.run(notify_share(snap, subject, tg, mail)), daemon=True).start()
    db.commit()
    name = getattr(obj, "title", None) or obj.name
    return {"shared": True, "entity_type": et, "name": name, "with": {"name": target.name, "email": target.email, "in_planner": target.ms_oid is not None},
            "permission": perm, "permission_ru": "редактирование" if perm == "edit" else "просмотр"}


def t_revoke_access(db, user, a):
    et, obj = _share_target(db, user, a)
    email = str(a.get("email") or "").strip().lower()
    target = db.scalar(select(models.User).where(models.User.email == email))
    sh = target and db.scalar(select(models.Share).where(models.Share.entity_type == et, models.Share.entity_id == obj.id, models.Share.user_id == target.id))
    if not sh:
        raise ToolError(f"У {email} нет доступа к этому объекту")
    db.delete(sh); log(db, obj, "unshare", {"via": "mcp", "from": email}); db.commit()
    return {"revoked": True, "email": email}


def t_list_shares(db, user, a):
    if a.get("entity_type") or a.get("entity"):
        et, obj = _share_target(db, user, a)
        rows = db.scalars(select(models.Share).where(models.Share.entity_type == et, models.Share.entity_id == obj.id)).all()
        return {"entity_type": et, "name": getattr(obj, "title", None) or obj.name,
                "shares": [{"name": s.user.name, "email": s.user.email, "permission": s.permission} for s in rows]}
    # без параметров — что открыли мне
    rows = db.scalars(select(models.Share).where(models.Share.user_id == user.id)).all()
    out = []
    for s in rows:
        model = {"direction": models.Direction, "project": models.Project, "task": models.Task}[s.entity_type]
        obj = db.get(model, s.entity_id)
        if obj:
            out.append({"entity_type": s.entity_type, "id": obj.id, "name": getattr(obj, "title", None) or obj.name,
                        "permission": s.permission, "shared_by": s.granter.name if s.granter else None})
    return {"shared_with_me": out}


# ── Описание инструментов для Claude ─────────────────────────────────────────

def _s(desc, **extra): return {"type": "string", "description": desc, **extra}
def _i(desc): return {"type": "integer", "description": desc}
def _b(desc): return {"type": "boolean", "description": desc}
def _arr(desc): return {"type": "array", "items": {"type": "string"}, "description": desc}
REF = "id или название (можно часть названия, без учёта регистра)"

TOOLS: list[dict] = [
    # чтение
    {"name": "get_overview", "handler": t_get_overview,
     "description": "Сводка «что сегодня»: состояние всех направлений (шкала внимания — какое направление упускается и почему), дедлайны сегодня, просрочки, "
                    "проверки, кого из людей пора спросить, что поручено мне. Начинай с неё на вопросы «что у меня», «как дела», «что сегодня», «утренняя сводка».",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_directions", "handler": t_list_directions,
     "description": "Список направлений пользователя со статистикой задач и шкалой внимания.",
     "inputSchema": {"type": "object", "properties": {"include_archived": _b("включить архивные (по умолчанию нет)")}}},
    {"name": "get_direction_summary", "handler": t_get_direction_summary,
     "description": "Подробная сводка по одному направлению: шкала внимания и причины, задачи по статусам, кто задействован, тулы.",
     "inputSchema": {"type": "object", "properties": {"direction": _s(f"направление: {REF}"), "include_done": _b("включить выполненные задачи (по умолчанию да)")},
                     "required": ["direction"]}},
    {"name": "list_tasks", "handler": t_list_tasks,
     "description": "Поиск задач с фильтрами: направление, статус, человек, просроченные, срок в ближайшие N дней, текст. По умолчанию — мои открытые задачи. "
                    "scope=assigned_to_me — задачи, которые поручили мне другие («мне поручено»).",
     "inputSchema": {"type": "object", "properties": {
         "scope": _s("mine (мои и открытые мне задачи, по умолчанию) | assigned_to_me (поручены мне) | all", enum=["mine", "assigned_to_me", "all"]),
         "direction": _s(f"направление: {REF}"), "project": _s(f"проект: {REF}"), "person": _s(f"исполнитель: {REF}"),
         "status": _s("backlog | in_progress | waiting | done (можно по-русски: бэклог, в работе, ждём, выполнено)"),
         "include_done": _b("включить выполненные (по умолчанию нет)"), "overdue_only": _b("только просроченные"),
         "due_within_days": _i("дедлайн в ближайшие N дней"), "query": _s("текст для поиска в названии/описании"), "limit": _i("максимум записей (по умолчанию 50)")}}},
    {"name": "list_projects", "handler": t_list_projects,
     "description": "Проекты (внутри направлений: Направление → Проекты → Задачи) со статистикой задач. Можно отфильтровать по направлению.",
     "inputSchema": {"type": "object", "properties": {"direction": _s(f"направление: {REF}"), "include_archived": _b("включить архивные")}}},
    {"name": "get_task", "handler": t_get_task,
     "description": "Карточка задачи целиком: описание, направления, поручения с отчётами исполнителей, напоминания, тулы.",
     "inputSchema": {"type": "object", "properties": {"task": _s(f"задача: {REF}")}, "required": ["task"]}},
    {"name": "list_people", "handler": t_list_people,
     "description": "Справочник людей (кому можно поручать) с числом открытых/закрытых поручений от меня.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_person_report", "handler": t_get_person_report,
     "description": "Отчёт по человеку: что я ему поручил и как он справляется — всего/открыто/выполнено, доля выполненных, вовремя ли закрывает "
                    "(on_time_rate), средний срок выполнения, просрочки сейчас, пропущенные проверки, застоявшиеся задачи, последние отчёты, список задач.",
     "inputSchema": {"type": "object", "properties": {"person": _s(f"человек: {REF}"), "include_done": _b("включить выполненные задачи в список (по умолчанию нет)")},
                     "required": ["person"]}},
    {"name": "get_team_report", "handler": t_get_team_report,
     "description": "Сводный отчёт по всем людям, кому я поручал: успешность каждого (выполнено, вовремя, просрочено, пропущенные проверки), отсортировано по проблемности. "
                    "Для вопросов «кто не справляется», «как команда», «у кого просрочки».",
     "inputSchema": {"type": "object", "properties": {}}},
    # запись
    {"name": "create_direction", "handler": t_create_direction,
     "description": "Создать направление развития. Цвет подбирается автоматически.",
     "inputSchema": {"type": "object", "properties": {"name": _s("название"), "goal": _s("цель направления"), "description": _s("описание"), "color": _s("цвет #hex (необязательно)")},
                     "required": ["name"]}},
    {"name": "update_direction", "handler": t_update_direction,
     "description": "Изменить направление: название, цель, описание, цвет, статус (active | paused — пауза | archived — в архив). Удаления нет — вместо него archived.",
     "inputSchema": {"type": "object", "properties": {"direction": _s(f"направление: {REF}"), "name": _s("новое название"), "goal": _s("цель"),
                                                      "description": _s("описание"), "color": _s("#hex"), "status": _s("active | paused | archived")},
                     "required": ["direction"]}},
    {"name": "create_project", "handler": t_create_project,
     "description": "Создать проект внутри направления («заведи проект Договор бурение в Эмбе»). Задачи потом привязываются к проекту.",
     "inputSchema": {"type": "object", "properties": {"direction": _s(f"направление: {REF}"), "name": _s("название проекта"), "goal": _s("цель"),
                                                      "description": _s("описание"), "color": _s("#hex (необязательно, иначе цвет направления)")},
                     "required": ["direction", "name"]}},
    {"name": "update_project", "handler": t_update_project,
     "description": "Изменить проект: название, цель, описание, цвет, статус (active | paused | archived). Удаления нет — вместо него archived.",
     "inputSchema": {"type": "object", "properties": {"project": _s(f"проект: {REF}"), "name": _s("новое название"), "goal": _s("цель"),
                                                      "description": _s("описание"), "color": _s("#hex"), "status": _s("active | paused | archived")},
                     "required": ["project"]}},
    {"name": "create_task", "handler": t_create_task,
     "description": "Создать задачу («запиши», «добавь задачу», «поручи X сделать Y»). Одним вызовом можно сразу привязать к направлениям, поручить людям, "
                    "поставить дедлайн, дату проверки и напоминание. Даты — ISO (YYYY-MM-DD, дата-время YYYY-MM-DDTHH:MM по местному времени).",
     "inputSchema": {"type": "object", "properties": {
         "title": _s("название задачи — коротко, глаголом"), "description": _s("подробности, контекст"),
         "directions": _arr(f"направления: {REF}; можно несколько"), "project": _s(f"проект внутри направления: {REF}; направление проекта привяжется само"),
         "create_direction_if_missing": _b("создать направление, если такого нет (по умолчанию нет — лучше уточнить)"),
         "priority": _i("1 (самый важный) … 5 (наименее важный); по умолчанию 3"),
         "status": _s("backlog (по умолчанию) | in_progress | waiting | done"),
         "deadline": _s("дедлайн YYYY-MM-DD"), "next_check_at": _s("когда мне самому проверить задачу, ISO дата-время"),
         "assign_to": _arr(f"кому поручить: люди по имени или id"), "create_person_if_missing": _b("добавить человека в справочник, если не найден"),
         "check_at": _s("когда спросить исполнителя о результате (ISO дата-время) — по нему придёт «Пора проверить у X»"), "comment": _s("комментарий к поручению — что именно нужно от исполнителя"),
         "remind_at": _s("напоминание мне: ISO дата-время"), "remind_channels": _arr("telegram | email | outlook_calendar (по умолчанию telegram)"),
         "remind_message": _s("текст напоминания"), "remind_recipient": _s("owner | assignees | both")},
         "required": ["title"]}},
    {"name": "update_task", "handler": t_update_task,
     "description": "Изменить задачу: название, описание, приоритет, дедлайн (null — убрать), дату проверки, статус, проект, добавить/убрать направления. Для своих задач и открытых на редактирование.",
     "inputSchema": {"type": "object", "properties": {"task": _s(f"задача: {REF}"), "title": _s("новое название"), "description": _s("новое описание (заменяет)"),
                                                      "priority": _i("1–5"), "deadline": _s("YYYY-MM-DD или null"), "next_check_at": _s("ISO дата-время или null"),
                                                      "status": _s("backlog | in_progress | waiting | done"),
                                                      "project": _s("перенести в проект (название/id) или null — убрать из проекта"),
                                                      "add_directions": _arr("добавить направления"), "remove_directions": _arr("убрать направления")},
                     "required": ["task"]}},
    {"name": "set_task_status", "handler": t_set_task_status,
     "description": "Сменить статус задачи («отметь выполненным», «взял в работу», «поставь на ожидание»). Доступно владельцу и исполнителю. "
                    "При done открытые поручения закрываются автоматически.",
     "inputSchema": {"type": "object", "properties": {"task": _s(f"задача: {REF}"), "status": _s("backlog | in_progress | waiting | done (или по-русски)"),
                                                      "close_delegations": _b("закрыть поручения при done (по умолчанию да)")},
                     "required": ["task", "status"]}},
    {"name": "add_task_note", "handler": t_add_task_note,
     "description": "Дописать заметку в описание задачи с отметкой времени («запиши по задаче X, что …»). Описание не затирается.",
     "inputSchema": {"type": "object", "properties": {"task": _s(f"задача: {REF}"), "text": _s("текст заметки")}, "required": ["task", "text"]}},
    {"name": "delegate_task", "handler": t_delegate_task,
     "description": "Поручить существующую задачу человеку (или нескольким). Можно задать дату проверки и комментарий, заодно дедлайн задачи. "
                    "Для новой задачи используй create_task с assign_to.",
     "inputSchema": {"type": "object", "properties": {"task": _s(f"задача: {REF}"), "person": _s(f"исполнитель: {REF}"), "people": _arr("несколько исполнителей"),
                                                      "check_at": _s("когда спросить о результате, ISO дата-время"), "comment": _s("что именно нужно"),
                                                      "deadline": _s("заодно поставить дедлайн задачи YYYY-MM-DD"),
                                                      "create_person_if_missing": _b("добавить человека в справочник, если не найден")},
                     "required": ["task"]}},
    {"name": "update_delegation", "handler": t_update_delegation,
     "description": "Изменить поручение: закрыть (status=done) или вернуть (open), записать отчёт исполнителя, перенести дату проверки, поправить комментарий. "
                    "Владелец задачи — всё; исполнитель — status и report по своему поручению («отчитайся: сделал …»).",
     "inputSchema": {"type": "object", "properties": {"task": _s(f"задача: {REF}"), "person": _s("исполнитель (если у задачи несколько)"),
                                                      "status": _s("done | open"), "report": _s("текст отчёта о выполнении"),
                                                      "check_at": _s("новая дата проверки, ISO дата-время"), "comment": _s("комментарий")},
                     "required": ["task"]}},
    {"name": "add_reminder", "handler": t_add_reminder,
     "description": "Поставить напоминание по задаче («напомни мне в пятницу в 10 про …»). Каналы: telegram, email, outlook_calendar (создаёт событие в календаре). "
                    "recipient: owner — мне, assignees — исполнителям, both — обоим.",
     "inputSchema": {"type": "object", "properties": {"task": _s(f"задача: {REF}"), "fire_at": _s("когда, ISO дата-время по местному времени"),
                                                      "channels": _arr("telegram | email | outlook_calendar"), "message": _s("текст"), "recipient": _s("owner | assignees | both")},
                     "required": ["task", "fire_at"]}},
    {"name": "create_person", "handler": t_create_person,
     "description": "Добавить человека в справочник (кому можно поручать). Если указать рабочую почту, он получит уведомления и увидит поручения при входе в планнер.",
     "inputSchema": {"type": "object", "properties": {"name": _s("имя и фамилия"), "email": _s("почта"), "telegram_chat_id": _s("Telegram chat id"), "note": _s("заметка: роль, отдел")},
                     "required": ["name"]}},
    {"name": "add_tool", "handler": t_add_tool,
     "description": "Добавить вспомогательный тул (таблица, бот, документ) и привязать к задачам/направлениям.",
     "inputSchema": {"type": "object", "properties": {"name": _s("название"), "type": _s("google_sheet | excel_sharepoint | telegram_bot | notion | other"),
                                                      "url": _s("ссылка"), "note": _s("заметка"), "tasks": _arr("задачи"), "directions": _arr("направления")},
                     "required": ["name"]}},
    # совместный доступ
    {"name": "share_access", "handler": t_share_access,
     "description": "Открыть коллеге доступ к направлению, проекту или задаче («поделись Эмбой с Нурланом», «дай доступ на редактирование»). "
                    "Приглашение по рабочей почте — можно даже если человек ещё не входил в планнер. Только для своих объектов.",
     "inputSchema": {"type": "object", "properties": {"entity_type": _s("direction | project | task"), "entity": _s(f"объект: {REF}"),
                                                      "email": _s("рабочая почта коллеги, напр. n.abilkhanov@cis.kz"),
                                                      "permission": _s("view (смотреть, по умолчанию) | edit (редактировать)")},
                     "required": ["entity_type", "entity", "email"]}},
    {"name": "revoke_access", "handler": t_revoke_access,
     "description": "Закрыть коллеге доступ к направлению/проекту/задаче.",
     "inputSchema": {"type": "object", "properties": {"entity_type": _s("direction | project | task"), "entity": _s(f"объект: {REF}"), "email": _s("почта коллеги")},
                     "required": ["entity_type", "entity", "email"]}},
    {"name": "list_shares", "handler": t_list_shares,
     "description": "Кому открыт мой объект (укажите entity_type и entity) или — без параметров — что открыли мне другие («общие»).",
     "inputSchema": {"type": "object", "properties": {"entity_type": _s("direction | project | task"), "entity": _s(f"объект: {REF}")}}},
]
_HANDLERS = {t["name"]: t["handler"] for t in TOOLS}


def tools_for(user: models.User) -> list[dict]:
    return [{k: v for k, v in t.items() if k != "handler"} for t in TOOLS]


def instructions_for(user: models.User) -> str:
    now = _now().astimezone(TZ)
    return (
        f"CIS Planner — рабочий планнер-таскборд пользователя {user.name} ({user.email}): направления развития → проекты → задачи → поручения людям → "
        f"сроки и напоминания (Telegram, почта, календарь Outlook). Сейчас {now.strftime('%Y-%m-%d %H:%M')} ({settings.app_timezone}), "
        f"{['понедельник','вторник','среда','четверг','пятница','суббота','воскресенье'][now.weekday()]}.\n"
        "ПРАВИЛО: слова «запиши», «добавь задачу», «поручи», «делегируй», «напомни», «поставь срок/дедлайн», «отметь выполненным», «возьми в работу», "
        "«что у меня», «сводка», «как дела у <человек>», «что по <направление>», «кто не справляется», «что сегодня» — это команды планнеру. "
        "Сразу вызывай инструменты, не спрашивай, куда записать и не предлагай другие места. Голосовые формулировки короткие и неточные: "
        "названия направлений, задач и людей передавай как сказано — сервер ищет по части названия и сам вернёт кандидатов, если совпадений несколько; "
        "только тогда уточняй у человека. Если направление не названо — создай задачу без направления, не переспрашивай.\n"
        "Даты: «завтра», «в пятницу», «через неделю», «к концу месяца» переводи в ISO сам от текущей даты; время без указания — 09:00; "
        "«напомни в 10» — сегодня в 10:00, если ещё не прошло, иначе завтра.\n"
        "После записи подтверждай одной фразой: что создано, в каком направлении, срок, кому поручено. Сводки пересказывай кратко, по делу, "
        "выделяя просроченное и то, что требует внимания; цифры не выдумывай — только из ответа инструментов.\n"
        "Удалять ничего нельзя (нет такого инструмента): вместо удаления — статус done, направление/проект в paused/archived, поручение status=open→done.\n"
        "Проекты: задача может лежать в проекте внутри направления («в Эмбе проект Договор основной») или прямо в направлении. "
        "«Поделись», «дай доступ», «открой Нурлану» — share_access; коллеги видят открытое им в разделе «Общие»."
    )


def call_tool(db: Session, user: models.User, name: str, arguments) -> tuple[str, bool]:
    handler = _HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"неизвестный инструмент {name}"}, ensure_ascii=False), True
    args = arguments if isinstance(arguments, dict) else {}
    try:
        result = handler(db, user, args)
        return json.dumps(result, ensure_ascii=False, default=str), False
    except ToolError as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False), True
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return json.dumps({"error": f"внутренняя ошибка: {type(e).__name__}: {e}"}, ensure_ascii=False), True
