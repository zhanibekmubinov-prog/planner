"""Инструменты MCP-коннектора CIS Planner для Claude.

Всё, что умеет планнер, кроме удаления: сводки по направлениям/задачам/людям, создание и правка направлений
и задач, поручения, сроки, напоминания. Права — как в REST: пользователь видит своё + порученное ему,
исполнитель может менять статус и писать отчёт по своему поручению.

Ссылки на сущности принимаются как id (число) или название (без учёта регистра, можно часть). Если совпадений
несколько — возвращается ошибка со списком кандидатов, чтобы Claude уточнил у человека.
"""
import json
import logging
import re
import secrets
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import digest, models
from .config import settings
from .crud import log
from .scope import (OWNER, WRITE, direction_access, is_assignee, my_person_id, project_access, stamp, task_access, visible_directions,
                    visible_projects, visible_tasks_query)

_log = logging.getLogger("mcp")
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
    """Ошибка, текст которой уходит Claude. hint — что сделать дальше, чтобы вызов прошёл."""

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


_SPLIT_RE = re.compile(r"[,;\n]+")
_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
LEN_TITLE, LEN_NAME, LEN_TEXT, LEN_URL = 300, 200, 5000, 1000
PAST_TOLERANCE = timedelta(minutes=5)


def _list(a: dict, key: str) -> list:
    """Список из аргумента: null → [], строка → элементы через `,` / `;` / перевод строки
    (Claude в голосовом режиме присылает «Снабжение, Бурение» одной строкой), массив → без пустых."""
    v = a.get(key)
    if v in (None, ""):
        return []
    if isinstance(v, (list, tuple)):
        out = []
        for x in v:
            if isinstance(x, str):
                out.extend(p.strip() for p in _SPLIT_RE.split(x) if p.strip())
            elif x not in (None, ""):
                out.append(x)
        return out
    if isinstance(v, str):
        return [p.strip() for p in _SPLIT_RE.split(v) if p.strip()]
    if isinstance(v, dict):
        raise ToolError(f"{key}: ожидается список строк, получен объект")
    return [v]


def _str(a: dict, key: str, max_len: int = LEN_TEXT, required: bool = False) -> str | None:
    """Строковый аргумент: None → None; список/объект → ToolError; число → строка; обрезка пробелов, лимит длины."""
    v = a.get(key)
    if v is None:
        if required:
            raise ToolError(f"{key}: обязательное поле")
        return None
    if isinstance(v, (list, tuple, dict)) or isinstance(v, bool):
        raise ToolError(f"{key}: ожидается строка, получен {type(v).__name__}",
                        hint=f"Передайте {key} одной строкой текста.")
    s = str(v).strip()
    if required and not s:
        raise ToolError(f"{key}: обязательное поле")
    if len(s) > max_len:
        raise ToolError(f"{key}: слишком длинно ({len(s)} символов, максимум {max_len})", hint="Сократите текст или перенесите подробности в описание.")
    return s


def _color(a: dict) -> str | None:
    c = _str(a, "color", 16)
    if not c:
        return None
    if not _COLOR_RE.match(c):
        raise ToolError("color: ожидается цвет вида #rrggbb, например #0f766e")
    return c.lower()


def parse_int(value, field: str, lo: int | None = None, hi: int | None = None) -> int:
    if isinstance(value, bool):
        raise ToolError(f"{field}: ожидается целое число")
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        raise ToolError(f"{field}: ожидается целое число, получено «{value}»",
                        hint=f"Передайте {field} числом (например 7); слова вроде «неделя» переведите в число сами.")
    if lo is not None and n < lo or hi is not None and n > hi:
        raise ToolError(f"{field}: число от {lo if lo is not None else '…'} до {hi if hi is not None else '…'}, получено {n}")
    return n


def _norm(s: str) -> str:
    """Нормализация для сравнения названий: регистр, ё→е, пунктуация, лишние пробелы."""
    s = str(s or "").lower().replace("ё", "е")
    s = _PUNCT_RE.sub(" ", s)
    return " ".join(s.split())


def _stem_eq(w: str, nw: str) -> bool:
    """Слово запроса ≈ слово названия с учётом окончаний: общий префикс ≥ 3 и не короче min(len)-2 («эмба» ≈ «эмбой»)."""
    if nw.startswith(w) or w.startswith(nw):
        return True
    n = 0
    for x, y in zip(w, nw):
        if x != y:
            break
        n += 1
    return n >= 3 and n >= min(len(w), len(nw)) - 2


def _alive(items):
    """Без записей в корзине (soft-delete v0.8): deleted_at есть не у всех моделей — проверяем через getattr."""
    return [x for x in items if getattr(x, "deleted_at", None) is None]


def _is_alive(obj) -> bool:
    return obj is not None and getattr(obj, "deleted_at", None) is None


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


def parse_future_dt(value, field: str) -> datetime | None:
    """Дата-время для напоминаний/проверок: в прошлом больше чем на 5 минут — ошибка (Claude часто путает год)."""
    dt = parse_dt(value, field)
    if dt is not None and dt < _now() - PAST_TOLERANCE:
        raise ToolError(f"{field}: {_local(dt)} уже в прошлом (сейчас {_local(_now())} {settings.app_timezone})",
                        hint="Уточните у человека дату и время; «завтра», «в пятницу» считайте от текущей даты.")
    return dt


def deadline_warning(d: date | None) -> str | None:
    if d and d < _today():
        return f"Дедлайн {d.isoformat()} уже в прошлом (сегодня {_today().isoformat()}) — задача сразу считается просроченной. Если это ошибка года, поправьте через update_task."
    return None


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


_LIST_TOOL = {"Направление": "list_directions", "Проект": "list_projects", "Задача": "list_tasks", "Человек": "list_people"}
_MISSING_HINT = {
    "Направление": "Направления должны существовать. Возьмите одно из доступных, либо создайте его create_direction "
                   "(или передайте create_direction_if_missing=true в create_task), либо создайте задачу без направления.",
    "Проект": "Проект должен уже существовать внутри направления. Посмотрите list_projects, создайте его create_project "
              "(или передайте create_project_if_missing=true в create_task) либо уберите поле project — задача лягет прямо в направление.",
    "Задача": "Найдите задачу через list_tasks (query=часть названия; include_done=true, если она могла быть закрыта) и повторите с её id.",
    "Человек": "Человека нет в справочнике. Передайте create_person_if_missing=true или сначала вызовите create_person (имя, почта).",
}


def _is_done(it) -> bool:
    return getattr(it, "status", None) == models.TaskStatus.done


def _prefer_open(cands: list, write: bool, s: str):
    """Среди кандидатов-задач предпочесть открытые. Единственный кандидат — выполненная задача, а вызов пишущий →
    ошибка с id (С1: «возьми в работу договор» не должно оживлять закрытый «Договор»)."""
    open_ = [it for it in cands if not _is_done(it)]
    if len(open_) == 1:
        return open_[0]
    if not open_ and len(cands) == 1 and write:
        t = cands[0]
        raise ToolError(f"Задача «{t.title}» (id {t.id}) уже выполнена — открытых задач с таким названием нет.",
                        hint=f"Если нужно изменить именно её, повторите вызов с task={t.id}. Если имелась в виду другая задача — уточните название.")
    if len(cands) == 1:
        return cands[0]
    return None


def _match(items, ref, label: str, name_attr: str = "name", write: bool = False):
    """Найти одну сущность по id или названию (регистр, ё/е и пунктуация не важны; допускается часть названия и словоформы)."""
    if ref is None or str(ref).strip() == "":
        raise ToolError(f"{label}: не указано")
    s = str(ref).strip()
    is_task = name_attr == "title"
    id_missing = None
    if s.isdigit():
        for it in items:
            if it.id == int(s):
                return it
        id_missing = s  # Н1: числовое название («2026») — дальше ищем по имени
    q = _norm(s)
    if not q:
        raise ToolError(f"{label}: пустое название")
    names = [(it, _norm(getattr(it, name_attr))) for it in items]
    exact = [it for it, n in names if n == q]
    if exact:
        hit = _prefer_open(exact, write, s) if is_task else (exact[0] if len(exact) == 1 else None)
        if hit is not None:
            return hit
        partial = exact
    else:
        partial = [it for it, n in names if q in n]
        if not partial:
            # мягкий поиск по словам: каждое слово запроса (≥3 символов) есть в названии; слова ≥4 — по основе («договор эмба» ≈ «Договор с Эмбой»)
            words = [w for w in q.split() if len(w) > 2]
            def hit(n: str) -> bool:
                nws = n.split()
                return bool(words) and all((w in n) if len(w) < 4 else any(_stem_eq(w, nw) for nw in nws) for w in words)
            partial = [it for it, n in names if hit(n)]
        if is_task and partial:
            got = _prefer_open(partial, write, s)
            if got is not None:
                return got
        elif len(partial) == 1:
            return partial[0]
    if not partial:
        listed = ", ".join(f"«{getattr(it, name_attr)}» (id {it.id})" for it in items[:25])
        prefix = f"{label} с id {id_missing} не найдено, задачи с названием «{s}» тоже нет" if id_missing else f"{label} «{s}» не найдено"
        raise ToolError(f"{prefix}. Доступные: {listed or 'пока нет ни одного'}", hint=_MISSING_HINT.get(label))
    listed = ", ".join(f"«{getattr(it, name_attr)}» (id {it.id}{', выполнено' if _is_done(it) else ''})" for it in partial[:10])
    raise ToolError(f"{label} «{s}»: несколько совпадений — уточните: {listed}",
                    hint="Спросите человека, какой вариант имелся в виду, и повторите вызов с точным названием или id.")


def _checklist_done_count(t: models.Task) -> str:
    cl = t.checklist or []
    return f"{sum(1 for c in cl if c.get('done'))}/{len(cl)}"


def my_directions(db: Session, user: models.User, include_archived=True) -> list[models.Direction]:
    """Свои направления + открытые мне на просмотр/редактирование (access в объекте)."""
    dirs = [d for d in _alive(visible_directions(db, user)) if d.access != "via"]
    if not include_archived:
        dirs = [d for d in dirs if d.status != models.DirectionStatus.archived]
    return dirs


def my_projects(db: Session, user: models.User, include_archived=True) -> list[models.Project]:
    ps = [p for p in _alive(visible_projects(db, user)) if p.access != "via" and _is_alive(p.direction)]
    if not include_archived:
        ps = [p for p in ps if p.status != models.DirectionStatus.archived]
    return ps


def visible_tasks(db: Session, user: models.User) -> list[models.Task]:
    return _alive(db.scalars(visible_tasks_query(db, user).order_by(models.Task.priority, models.Task.deadline)).unique().all())


def all_people(db: Session) -> list[models.Person]:
    return db.scalars(select(models.Person).order_by(models.Person.name)).all()


def resolve_direction(db, user, ref) -> models.Direction:
    return _match(my_directions(db, user), ref, "Направление")


def resolve_task(db, user, ref, write: bool = False) -> models.Task:
    """write=True — пишущий вызов: единственное совпадение с выполненной задачей → ошибка с id, а не тихая правка."""
    return _match(visible_tasks(db, user), ref, "Задача", "title", write=write)


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


def _owner_only(obj, what: str):
    if getattr(obj, "access", OWNER) != OWNER:
        raise ToolError(f"{what}: это может делать только владелец", hint="Попросите владельца сделать это в планнере или через свой Claude.")
    return obj


def _owned_task(db, user, ref) -> models.Task:
    t = resolve_task(db, user, ref, write=True)
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
        "directions": [d.name for d in _alive(t.directions)],
        "project": t.project.name if _is_alive(t.project) else None, "project_id": t.project_id if _is_alive(t.project) else None,
        "assignees": [f"{d.person.name}{' ✓' if d.status == models.DelegationStatus.done else ''}" for d in t.delegations],
        "owner": t.owner.name if t.owner else None,
        "checklist": _checklist_done_count(t) if t.checklist else None,
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
        "checklist": [{"id": c.get("id"), "text": c.get("text"), "done": bool(c.get("done"))} for c in (t.checklist or [])],
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
        "undelivered_reminders": [{"task": x["task"].title, "task_id": x["task"].id, "fire_at": _local(x["fire_at"]), "reason": x["reason"], "detail": x["detail"]}
                                  for x in data.get("undelivered", [])],
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
    if a.get("due_within_days") not in (None, ""):
        lim = today + timedelta(days=parse_int(a["due_within_days"], "due_within_days", 0, 3650))
        tasks = [t for t in tasks if t.deadline and t.deadline <= lim]
    if a.get("query"):
        q = _norm(_str(a, "query", LEN_TITLE))
        tasks = [t for t in tasks if q and (q in _norm(t.title) or (t.description and q in _norm(t.description)))]
    limit = parse_int(a["limit"], "limit", 1, 500) if a.get("limit") not in (None, "") else 50
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

def _clean_name(a: dict, key: str, what: str) -> str:
    """Название направления/проекта/человека: строка ≤200, без запятых (иначе это список, а не имя)."""
    name = _str(a, key, LEN_NAME)
    if not name:
        raise ToolError(f"{key}: укажите название {what}")
    if "," in name or ";" in name or "\n" in name:
        raise ToolError(f"{key}: «{name}» похоже на несколько названий через запятую — создавайте по одному",
                        hint="Разбейте на отдельные вызовы или передайте список в поле-массив (directions, assign_to…).")
    return name


def t_create_direction(db, user, a):
    name = _clean_name(a, "name", "направления")
    existing = [d for d in my_directions(db, user) if _norm(d.name) == _norm(name)]
    if existing:
        raise ToolError(f"Направление «{existing[0].name}» уже есть (id {existing[0].id}). Используйте его или выберите другое название.")
    used = {d.color for d in my_directions(db, user)}
    color = _color(a) or next((c for c in PALETTE if c not in used), PALETTE[len(used) % len(PALETTE)])
    d = models.Direction(name=name, goal=_str(a, "goal"), description=_str(a, "description"), color=color, owner_id=user.id)
    db.add(d); db.flush(); log(db, d, "create", {"via": "mcp"}); db.commit()
    return {"created": True, "direction": direction_brief(d)}


def _apply_container_update(obj, a: dict, what: str) -> list[str]:
    """Общая правка направления/проекта. Переименование и архив — только владелец (Н6: голосовая ошибка распознавания
    не должна архивировать чужую доску)."""
    changed = []
    for k in ("name", "goal", "description"):
        if a.get(k) is not None:
            val = _str(a, k, LEN_NAME if k == "name" else LEN_TEXT)
            if k == "name":
                if not val:
                    raise ToolError("name: название не может быть пустым")
                _owner_only(obj, f"{what}: переименование")
            setattr(obj, k, val or None); changed.append(k)
    if a.get("color") is not None:
        obj.color = _color(a); changed.append("color")
    if a.get("status") is not None:
        key = str(a["status"]).strip().lower()
        if key not in DIR_STATUS_ALIASES:
            raise ToolError("status: active (активно) | paused (пауза) | archived (архив)")
        st = models.DirectionStatus(DIR_STATUS_ALIASES[key])
        if st == models.DirectionStatus.archived:
            _owner_only(obj, f"{what}: перенос в архив")
        obj.status = st; changed.append("status")
    if not changed:
        raise ToolError("Нечего менять: передайте name, goal, description, color или status")
    return changed


def t_update_direction(db, user, a):
    d = _editable(resolve_direction(db, user, a.get("direction")), "Направление")
    changed = _apply_container_update(d, a, "Направление")
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


def _similar_people(db, name: str) -> list[models.Person]:
    """Кто в справочнике похож на это имя (С2): одно слово запроса ≈ слово существующего имени (по основе),
    либо одно из имён — префикс другого. Полное «Имя Фамилия» против другого полного имени — не похоже."""
    q = _norm(name); qw = q.split()
    out = []
    for p in all_people(db):
        n = _norm(p.name); nw = n.split()
        if not n or not nw:
            continue
        if n == q or n.startswith(q + " ") or q.startswith(n + " "):
            out.append(p)
        elif len(qw) == 1 and any(_stem_eq(qw[0], w) for w in nw):
            out.append(p)
        elif len(nw) == 1 and any(_stem_eq(nw[0], w) for w in qw):
            out.append(p)
    return out


def _new_person(db, name: str) -> models.Person:
    sim = _similar_people(db, name)
    if sim:
        listed = ", ".join(f"«{p.name}» (id {p.id})" for p in sim[:10])
        raise ToolError(f"«{name}»: похожие люди уже есть в справочнике — {listed}",
                        hint="Если это тот же человек — используйте его имя или id. Если другой — укажите полное имя (имя и фамилию).")
    p = models.Person(name=name); db.add(p); db.flush(); log(db, p, "create", {"via": "mcp"})
    return p


def _find_or_create_person(db, ref, create: bool) -> models.Person:
    try:
        return resolve_person(db, ref)
    except ToolError as e:
        if create and "не найдено" in str(e):
            name = _clean_name({"name": ref}, "name", "человека")
            return _new_person(db, name)
        raise


def _check_owner_sees(db, user, t: models.Task, d: models.Direction):
    """Редактор не может привязать чужую задачу к направлению, которого владелец задачи не видит."""
    if t.owner_id != user.id and t.owner is not None and direction_access(db, t.owner, d) is None:
        raise ToolError(f"Направление «{d.name}» не видно владельцу задачи ({t.owner.name}) — привязать нельзя",
                        hint="Добавляйте чужие задачи только в направления, открытые их владельцу.")


def t_create_task(db, user, a):
    title = _str(a, "title", LEN_TITLE)
    if not title:
        raise ToolError("title: укажите название задачи")
    dirs = []
    for ref in _list(a, "directions"):
        try:
            dirs.append(resolve_direction(db, user, ref))
        except ToolError as e:
            if a.get("create_direction_if_missing") and "не найдено" in str(e):
                name = _clean_name({"directions": ref}, "directions", "направления")
                dirs.append(models.Direction(name=name, owner_id=user.id, color=PALETTE[len(my_directions(db, user)) % len(PALETTE)]))
                db.add(dirs[-1]); db.flush(); log(db, dirs[-1], "create", {"via": "mcp"})
            else:
                raise
    project = None
    if a.get("project"):
        pref = _str(a, "project", LEN_NAME)
        try:
            project = resolve_project(db, user, pref, dirs[0] if len(dirs) == 1 else None)
        except ToolError as e:
            if a.get("create_project_if_missing") and "не найдено" in str(e) and len(dirs) == 1:
                _editable(dirs[0], f"Направление «{dirs[0].name}»")
                project = models.Project(name=_clean_name({"project": pref}, "project", "проекта"), direction_id=dirs[0].id, owner_id=dirs[0].owner_id or user.id)
                db.add(project); db.flush(); log(db, project, "create", {"via": "mcp", "by": user.id})
                stamp(project, project_access(db, user, project))
            elif a.get("create_project_if_missing") and "не найдено" in str(e):
                raise ToolError(str(e), hint="Чтобы создать проект вместе с задачей, укажите ровно одно направление в directions.")
            else:
                raise
        project = _editable(project, "Проект")
        if all(x.id != project.direction_id for x in dirs):
            dirs.append(project.direction)
    for d in dirs:
        _editable(d, f"Направление «{d.name}»")
    # задача в чужом (открытом мне) направлении принадлежит его хозяину — доска остаётся его
    owner_id = user.id if (not dirs or any(x.owner_id == user.id for x in dirs)) else (project.owner_id if project and project.owner_id else dirs[0].owner_id or user.id)
    deadline = parse_date(a.get("deadline"), "deadline")
    t = models.Task(title=title, description=_str(a, "description"), owner_id=owner_id,
                    status=parse_status(a["status"]) if a.get("status") else models.TaskStatus.backlog,
                    priority=parse_priority(a["priority"]) if a.get("priority") is not None else 3,
                    deadline=deadline, next_check_at=parse_future_dt(a.get("next_check_at"), "next_check_at"))
    t.directions = dirs
    t.project = project
    db.add(t); db.flush(); log(db, t, "create", {"via": "mcp", "by": user.id})
    check_at = parse_future_dt(a.get("check_at"), "check_at")
    comment = _str(a, "comment")
    for ref in _list(a, "assign_to"):
        p = _find_or_create_person(db, ref, bool(a.get("create_person_if_missing")))
        _add_delegation(db, user, t, p, check_at, comment)
    if a.get("remind_at"):
        _add_reminder(db, t, a["remind_at"], a.get("remind_channels"), _str(a, "remind_message"), a.get("remind_recipient"))
    db.commit(); db.refresh(t)
    out = {"created": True, "task": task_full(t), "link": f"{settings.frontend_url.rstrip('/')}/?task={t.id}" if settings.frontend_url else None}
    if (w := deadline_warning(deadline)):
        out["warning"] = w
    return out


def t_update_task(db, user, a):
    t = _owned_task(db, user, a.get("task"))
    is_owner = t.owner_id == user.id
    changed = []; warning = None
    if a.get("title") is not None:
        title = _str(a, "title", LEN_TITLE)
        if not title:
            raise ToolError("title: название не может быть пустым")
        t.title = title; changed.append("title")
    if a.get("description") is not None: t.description = _str(a, "description"); changed.append("description")
    if a.get("priority") is not None: t.priority = parse_priority(a["priority"]); changed.append("priority")
    if "deadline" in a:
        t.deadline = parse_date(a["deadline"], "deadline"); changed.append("deadline"); warning = deadline_warning(t.deadline)
    if "next_check_at" in a: t.next_check_at = parse_future_dt(a["next_check_at"], "next_check_at"); changed.append("next_check_at")
    if a.get("status") is not None:
        old = t.status; t.status = parse_status(a["status"])
        if old != t.status: log(db, t, "status_change", {"from": old.value, "to": t.status.value, "by": user.id, "via": "mcp"}); changed.append("status")
    # направления и проект — по правилам REST: добавлять только в свои/редактируемые, снимать — только своё/редактируемое;
    # редактор чужой задачи не может увести её с доски владельца (В1)
    for ref in _list(a, "add_directions"):
        d = _editable(resolve_direction(db, user, ref), "Направление")
        _check_owner_sees(db, user, t, d)
        if d not in t.directions: t.directions.append(d); changed.append(f"+{d.name}")
    for ref in _list(a, "remove_directions"):
        d = _editable(resolve_direction(db, user, ref), "Направление")
        if d in t.directions: t.directions.remove(d); changed.append(f"-{d.name}")
    if "project" in a:
        if a["project"] in (None, "", "null", "none", "без проекта"):
            if t.project is not None:
                if not is_owner and project_access(db, user, t.project) not in WRITE:
                    raise ToolError(f"Убрать задачу из проекта «{t.project.name}» может владелец задачи или редактор проекта")
                t.project = None; changed.append("project: без проекта")
        else:
            p = _editable(resolve_project(db, user, _str(a, "project", LEN_NAME)), "Проект")
            if t.project is not None and t.project.id != p.id and not is_owner and project_access(db, user, t.project) not in WRITE:
                raise ToolError(f"Перенести задачу из проекта «{t.project.name}» может владелец задачи или редактор этого проекта")
            if not is_owner and t.owner is not None and project_access(db, t.owner, p) is None:
                raise ToolError(f"Проект «{p.name}» не виден владельцу задачи — перенести нельзя")
            t.project = p
            if all(x.id != p.direction_id for x in t.directions): t.directions.append(p.direction)
            changed.append(f"project: {p.name}")
    if not changed:
        raise ToolError("Нечего менять: передайте title, description, priority, deadline, next_check_at, status, project, add_directions или remove_directions")
    if "status" not in changed: log(db, t, "update", {"via": "mcp", "fields": changed})
    db.commit(); db.refresh(t)
    out = {"updated": changed, "task": task_full(t)}
    if warning:
        out["warning"] = warning
    return out


def t_set_task_status(db, user, a):
    # write=True: единственное совпадение с выполненной задачей → ошибка с id; но переоткрыть по id можно
    t = resolve_task(db, user, a.get("task"), write=True)
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
    text = _str(a, "text")
    if not text:
        raise ToolError("text: пустая заметка")
    stamp_ = _now().astimezone(TZ).strftime("%d.%m.%Y %H:%M")
    t.description = f"{(t.description or '').rstrip()}\n\n[{stamp_}] {text}".strip()
    log(db, t, "update", {"via": "mcp", "fields": ["note"]}); db.commit()
    return {"task": t.id, "title": t.title, "description": t.description}


def t_add_checklist_items(db, user, a):
    t = _owned_task(db, user, a.get("task"))
    items = [str(x).strip()[:LEN_TITLE] for x in _list(a, "items") if str(x).strip()]
    if not items:
        raise ToolError("items: список пунктов (строки)", hint="Передайте items массивом строк, например [\"Собрать КП\", \"Согласовать с юристом\"].")
    cl = list(t.checklist or [])
    have = {_norm(c.get("text", "")) for c in cl}
    added, skipped = [], []
    for x in items:
        if _norm(x) in have:
            skipped.append(x); continue
        have.add(_norm(x)); added.append(x)
        cl.append({"id": secrets.token_hex(4), "text": x, "done": False})
    if not added:
        raise ToolError("Все эти пункты уже есть в чеклисте", hint="Ничего добавлять не нужно; отметить пункт — check_item.")
    t.checklist = cl
    log(db, t, "update", {"via": "mcp", "fields": ["checklist"]}); db.commit(); db.refresh(t)
    out = {"task": t.id, "title": t.title, "added": len(added), "progress": _checklist_done_count(t), "checklist": t.checklist}
    if skipped:
        out["skipped"] = skipped
    return out


def t_check_item(db, user, a):
    t = resolve_task(db, user, a.get("task"), write=True)
    acc = task_access(db, user, t)
    if acc == "view" or acc is None:
        raise ToolError(f"Задача «{t.title}» открыта вам только на просмотр.")
    cl = list(t.checklist or [])
    if not cl:
        raise ToolError(f"У задачи «{t.title}» нет чеклиста.", hint="Добавьте пункты через add_checklist_items.")
    raw = _str(a, "item", LEN_TITLE) or ""
    ref = _norm(raw)
    if not ref:
        raise ToolError("item: какой пункт отметить (текст или его часть, либо id)")
    hits = [c for c in cl if c.get("id") == raw.lower() or _norm(c.get("text", "")) == ref] or [c for c in cl if ref in _norm(c.get("text", ""))]
    if len(hits) != 1:
        names = ", ".join(f"«{c.get('text')}»" for c in (hits or cl)[:10])
        raise ToolError(f"Пункт «{a.get('item')}»: {'несколько совпадений' if hits else 'не найден'} — {names}",
                        hint="Уточните пункт: передайте более полный текст или id из get_task.")
    done = a.get("done", True)
    done = done if isinstance(done, bool) else str(done).lower() not in ("false", "0", "нет", "no")
    # не мутируем старые словари: иначе SQLAlchemy не увидит изменения JSON-колонки (старое == новому)
    t.checklist = [{**c, "done": done} if c is hits[0] else dict(c) for c in cl]
    log(db, t, "update", {"via": "mcp", "fields": ["checklist"]}); db.commit(); db.refresh(t)
    return {"task": t.id, "title": t.title, "item": hits[0]["text"], "done": done, "progress": _checklist_done_count(t)}


def t_delegate_task(db, user, a):
    t = _owned_task(db, user, a.get("task"))
    refs = _list(a, "people") or _list(a, "person")
    if not refs:
        raise ToolError("person или people: кому поручить")
    check_at = parse_future_dt(a.get("check_at"), "check_at")
    comment = _str(a, "comment")
    result = []
    for ref in refs:
        p = _find_or_create_person(db, ref, bool(a.get("create_person_if_missing")))
        result.append(_add_delegation(db, user, t, p, check_at, comment))
    warning = None
    if "deadline" in a and a["deadline"]:
        t.deadline = parse_date(a["deadline"], "deadline"); warning = deadline_warning(t.deadline)
    db.commit(); db.refresh(t)
    out = {"task": task_brief(t), "delegations": [delegation_out(d) for d in result],
           "note": "Исполнителю в течение минуты уйдёт уведомление «Вам поручено» (Telegram или почта), если он есть в планнере."}
    if warning:
        out["warning"] = warning
    return out


def t_update_delegation(db, user, a):
    t = resolve_task(db, user, a.get("task"), write=True)
    pid = my_person_id(db, user)
    acc = task_access(db, user, t)
    can_write = acc in WRITE  # владелец или редактор задачи — как PUT /delegations в REST (Н5)
    if a.get("person"):
        p = resolve_person(db, _str(a, "person", LEN_NAME))
        d = next((x for x in t.delegations if x.person_id == p.id), None)
    else:
        d = next((x for x in t.delegations if x.person_id == pid), None) if not can_write else (t.delegations[0] if len(t.delegations) == 1 else None)
    if d is None:
        names = ", ".join(x.person.name for x in t.delegations) or "нет поручений"
        raise ToolError(f"Не удалось определить поручение по задаче «{t.title}». Укажите person. Исполнители: {names}")
    is_mine = d.person_id == pid
    if not (can_write or is_mine):
        raise ToolError("Менять поручение может владелец задачи, редактор или сам исполнитель")
    changed = []
    if a.get("status") is not None:
        key = str(a["status"]).strip().lower()
        st = "done" if key in ("done", "выполнено", "готово", "сделано", "закрыто") else "open" if key in ("open", "открыто", "вернуть", "снова") else None
        if st is None: raise ToolError("status: done (выполнено) | open (открыто)")
        d.status = models.DelegationStatus(st); changed.append("status")
    if a.get("report") is not None: d.report = _str(a, "report"); changed.append("report")
    if can_write:
        if "check_at" in a: d.check_at = parse_future_dt(a["check_at"], "check_at"); d.notified_at = None; changed.append("check_at")
        if a.get("comment") is not None: d.comment = _str(a, "comment"); changed.append("comment")
    elif "check_at" in a or a.get("comment") is not None:
        raise ToolError("Исполнитель может менять только status и report")
    if not changed:
        raise ToolError("Нечего менять: status, report, check_at, comment")
    log(db, d, "report" if "report" in changed else "update", {"by": user.id, "via": "mcp", "fields": changed}); db.commit()
    return {"updated": changed, "delegation": delegation_out(d, with_task=True)}


def _add_reminder(db, task: models.Task, fire_at, channels, message, recipient) -> models.Reminder:
    when = parse_future_dt(fire_at, "fire_at")
    if when is None:
        raise ToolError("fire_at: когда напомнить (ISO дата-время)")
    if message is not None and not isinstance(message, str):
        raise ToolError("message: ожидается строка")
    message = (message or "").strip()[:LEN_TEXT] or None
    chans = _list({"c": channels}, "c") or ["telegram"]
    chans = [{"calendar": "outlook_calendar", "outlook": "outlook_calendar", "mail": "email", "почта": "email", "телеграм": "telegram", "tg": "telegram"}.get(str(c).strip().lower(), str(c).strip().lower()) for c in chans]
    bad = [c for c in chans if c not in ("telegram", "email", "outlook_calendar")]
    if bad:
        raise ToolError(f"channels: допустимы telegram, email, outlook_calendar (получено {bad})",
                        hint="Передайте channels массивом строк из этих трёх значений или не передавайте вовсе — тогда будет telegram.")
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


def _work_email(a: dict, key: str = "email", db=None) -> str | None:
    """Почта: одна строка, user@domain; рабочий домен из ALLOWED_EMAIL_DOMAINS либо адрес из списка гостей (v0.10)."""
    v = a.get(key)
    if v in (None, ""):
        return None
    if not isinstance(v, str):
        raise ToolError(f"{key}: ожидается одна почта строкой", hint="Передайте один адрес, например n.abilkhanov@cis.kz.")
    email = v.strip().lower()
    if "@" not in email or " " in email or email.count("@") != 1 or "." not in email.split("@")[1]:
        raise ToolError(f"{key}: «{v}» не похоже на почту", hint="Формат: имя@домен, например n.abilkhanov@cis.kz.")
    if len(email) > LEN_NAME:
        raise ToolError(f"{key}: слишком длинно")
    domain = email.split("@")[1]
    # v0.10: рабочий домен либо адрес из списка гостей (гостей добавляет админ в разделе «Гости»)
    from .guests import email_allowed, is_work_email
    ok = is_work_email(email) if db is None else email_allowed(db, email)
    if settings.allowed_domains and not ok:
        raise ToolError(f"{key}: разрешена рабочая почта @{', @'.join(settings.allowed_domains)} или адрес из списка гостей (получено @{domain})",
                        hint="Внешнего человека сначала добавляет администратор в разделе «Гости» — потом его можно указывать здесь.")
    return email


def t_create_person(db, user, a):
    name = _clean_name(a, "name", "человека")
    dup = [p for p in all_people(db) if _norm(p.name) == _norm(name)]
    if dup:
        raise ToolError(f"«{dup[0].name}» уже есть в справочнике (id {dup[0].id})")
    email = _work_email(a, db=db)
    if email and (same := db.scalar(select(models.Person).where(models.Person.email == email))):
        raise ToolError(f"Почта {email} уже у «{same.name}» (id {same.id})", hint="Используйте существующую запись.")
    tg = _str(a, "telegram_chat_id", 64)
    if tg and not re.fullmatch(r"-?\d{1,20}", tg):
        raise ToolError("telegram_chat_id: ожидается числовой chat id")
    p = _new_person(db, name)
    # без автопривязки user_id к чужому аккаунту (С10): связь Person↔User создаёт только сам пользователь при входе
    p.email, p.telegram_chat_id, p.note = email, tg or None, _str(a, "note")
    db.commit()
    return {"created": True, "person": person_brief(p)}


def t_add_tool(db, user, a):
    name = _str(a, "name", LEN_NAME)
    if not name:
        raise ToolError("name: название тула")
    typ = str(a.get("type") or "other").strip().lower()
    if typ not in [x.value for x in models.ToolType]:
        raise ToolError("type: google_sheet | excel_sharepoint | telegram_bot | notion | other")
    url = _str(a, "url", LEN_URL)
    if url and not re.match(r"^https?://\S+$", url):
        raise ToolError("url: ожидается ссылка вида https://…")
    tool = models.Tool(name=name, type=models.ToolType(typ), url=url or None, note=_str(a, "note"), owner_id=user.id)
    tool.tasks = [_owned_task(db, user, r) for r in _list(a, "tasks")]
    # тул вешается только на свои направления или открытые на редактирование (В1)
    tool.directions = [_editable(resolve_direction(db, user, r), "Направление") for r in _list(a, "directions")]
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
    name = _clean_name(a, "name", "проекта")
    d = _editable(resolve_direction(db, user, a.get("direction")), "Направление")
    dup = [p for p in my_projects(db, user) if p.direction_id == d.id and _norm(p.name) == _norm(name)]
    if dup:
        raise ToolError(f"Проект «{dup[0].name}» в направлении «{d.name}» уже есть (id {dup[0].id}).",
                        hint="Создавать не нужно — используйте этот проект: передайте его название или id в поле project у create_task / update_task.")
    p = models.Project(name=name, goal=_str(a, "goal"), description=_str(a, "description"), color=_color(a), direction_id=d.id,
                       owner_id=d.owner_id if d.owner_id else user.id)
    db.add(p); db.flush(); log(db, p, "create", {"via": "mcp", "by": user.id}); db.commit(); db.refresh(p)
    stamp(p, project_access(db, user, p))
    return {"created": True, "project": project_brief(p)}


def t_update_project(db, user, a):
    p = _editable(resolve_project(db, user, a.get("project")), "Проект")
    changed = _apply_container_update(p, a, "Проект")
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
    email = a.get("email")
    if not isinstance(email, str) or not email.strip():
        raise ToolError("email: ожидается одна рабочая почта строкой", hint="Например n.abilkhanov@cis.kz; несколько человек — отдельными вызовами.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()):
        raise ToolError(f"email: «{email}» не похоже на почту")
    try:
        target = find_or_invite_user(db, email)
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
    email = (_str(a, "email", LEN_NAME) or "").lower()
    target = db.scalar(select(models.User).where(models.User.email == email)) if email else None
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
        if _is_alive(obj):
            out.append({"entity_type": s.entity_type, "id": obj.id, "name": getattr(obj, "title", None) or obj.name,
                        "permission": s.permission, "shared_by": s.granter.name if s.granter else None})
    return {"shared_with_me": out}


# ── Описание инструментов для Claude ─────────────────────────────────────────

def _s(desc, **extra): return {"type": "string", "description": desc, **extra}
def _i(desc): return {"type": "integer", "description": desc}
def _b(desc): return {"type": "boolean", "description": desc}
def _arr(desc): return {"type": "array", "items": {"type": "string"}, "description": desc}
REF = "id или название (можно часть названия, без учёта регистра); объект должен уже существовать"

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
     "description": "Создать проект внутри направления («заведи проект Договор бурение в Эмбе»). Направление должно уже существовать (см. list_directions, "
                    "иначе сначала create_direction). Проект — контейнер задач; задачи привязываются к нему полем project в create_task/update_task. "
                    "Если проект с таким названием в направлении уже есть — вернётся ошибка с его id, повторно создавать не нужно.",
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
                    "поставить дедлайн, дату проверки и напоминание. Даты — ISO (YYYY-MM-DD, дата-время YYYY-MM-DDTHH:MM по местному времени). "
                    "Направления, проект и люди должны уже существовать (ищутся по части названия) — либо передайте флаги create_*_if_missing. "
                    "Проект без направления не создаётся: для create_project_if_missing укажите ровно одно направление. Если ничего не известно — достаточно title.",
     "inputSchema": {"type": "object", "properties": {
         "title": _s("название задачи — коротко, глаголом"), "description": _s("подробности, контекст"),
         "directions": _arr("направления по названию/id; можно несколько. Должны существовать (list_directions), иначе create_direction_if_missing=true"),
         "project": _s("проект внутри направления по названию/id. Должен уже существовать (list_projects) — иначе сначала create_project "
                       "или create_project_if_missing=true с одним направлением в directions. Направление проекта привяжется само"),
         "create_direction_if_missing": _b("создать направление, если такого нет (по умолчанию нет — лучше уточнить)"),
         "create_project_if_missing": _b("создать проект в указанном направлении, если такого нет (нужно ровно одно направление в directions)"),
         "priority": _i("1 (самый важный) … 5 (наименее важный); по умолчанию 3"),
         "status": _s("backlog (по умолчанию) | in_progress | waiting | done"),
         "deadline": _s("дедлайн YYYY-MM-DD"), "next_check_at": _s("когда мне самому проверить задачу, ISO дата-время"),
         "assign_to": _arr("кому поручить: люди по имени или id из list_people; нового человека — с create_person_if_missing=true"),
         "create_person_if_missing": _b("добавить человека в справочник, если не найден"),
         "check_at": _s("когда спросить исполнителя о результате (ISO дата-время) — по нему придёт «Пора проверить у X»"), "comment": _s("комментарий к поручению — что именно нужно от исполнителя"),
         "remind_at": _s("напоминание мне: ISO дата-время"), "remind_channels": _arr("telegram | email | outlook_calendar (по умолчанию telegram)"),
         "remind_message": _s("текст напоминания"), "remind_recipient": _s("owner | assignees | both")},
         "required": ["title"]}},
    {"name": "update_task", "handler": t_update_task,
     "description": "Изменить задачу: название, описание, приоритет, дедлайн (null — убрать), дату проверки, статус, проект, добавить/убрать направления. Для своих задач и открытых на редактирование.",
     "inputSchema": {"type": "object", "properties": {"task": _s(f"задача: {REF}"), "title": _s("новое название"), "description": _s("новое описание (заменяет)"),
                                                      "priority": _i("1–5"), "deadline": _s("YYYY-MM-DD или null"), "next_check_at": _s("ISO дата-время или null"),
                                                      "status": _s("backlog | in_progress | waiting | done"),
                                                      "project": _s("перенести в существующий проект (название/id; см. list_projects, нового — create_project) или null — убрать из проекта"),
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
    {"name": "add_checklist_items", "handler": t_add_checklist_items,
     "description": "Добавить пункты в чеклист задачи («добавь в задачу пункты: …», «разбей на шаги»). Пункты — галочки внутри карточки задачи; "
                    "прогресс виден на карточке как 2/5. Для длинного свободного текста используй add_task_note.",
     "inputSchema": {"type": "object", "properties": {"task": _s(f"задача: {REF}"), "items": _arr("пункты чеклиста, по одному на строку")},
                     "required": ["task", "items"]}},
    {"name": "check_item", "handler": t_check_item,
     "description": "Отметить пункт чеклиста задачи выполненным (или снять отметку: done=false). Пункт ищется по тексту или его части. Доступно владельцу, редактору и исполнителю.",
     "inputSchema": {"type": "object", "properties": {"task": _s(f"задача: {REF}"), "item": _s("текст пункта (или часть) либо id"), "done": _b("true — выполнен (по умолчанию), false — снять")},
                     "required": ["task", "item"]}},
    {"name": "delegate_task", "handler": t_delegate_task,
     "description": "Поручить существующую задачу человеку (или нескольким). Задача и человек должны существовать (list_tasks / list_people; нового человека — "
                    "create_person_if_missing=true). Можно задать дату проверки и комментарий, заодно дедлайн задачи. Для новой задачи используй create_task с assign_to.",
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
        "ОШИБКИ: если инструмент вернул isError, в ответе поле error (что не так) и hint (что сделать). Следуй hint: уточни название из списка кандидатов, "
        "создай недостающий проект/направление/человека (create_project, create_direction, create_person или флаги create_*_if_missing) и повтори вызов. "
        "Не повторяй тот же вызов без изменений и не объявляй человеку сбой, пока не исправил вызов по подсказке. Сначала создаётся направление, потом проект в нём, "
        "потом задача в проекте — в этом порядке.\n"
        "Выполненные задачи по названию для правок не берутся: если сервер ответил «уже выполнена, id N» — уточни у человека или повтори с id. "
        "Даты напоминаний и проверок в прошлом сервер отклоняет; дедлайн в прошлом принимается, но в ответе будет warning — озвучь его. "
        "Списки (directions, assign_to, items) можно передавать строкой через запятую; названия направлений/людей с запятой не создаются.\n"
        "Чеклист: «добавь пункты», «разбей на шаги» — add_checklist_items; «отметь пункт …» — check_item. "
        "Проекты: задача может лежать в проекте внутри направления («в Эмбе проект Договор основной») или прямо в направлении. "
        "«Поделись», «дай доступ», «открой Нурлану» — share_access; коллеги видят открытое им в разделе «Общие»."
    )


def call_tool(db: Session, user: models.User, name: str, arguments) -> tuple[str, bool]:
    handler = _HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"неизвестный инструмент «{name}»", "hint": "Доступные: " + ", ".join(sorted(_HANDLERS))}, ensure_ascii=False), True
    if isinstance(arguments, str):  # некоторые клиенты присылают аргументы JSON-строкой
        try:
            arguments = json.loads(arguments)
        except ValueError:
            arguments = {}
    args = arguments if isinstance(arguments, dict) else {}
    brief_args = json.dumps(args, ensure_ascii=False, default=str)[:600]
    try:
        result = handler(db, user, args)
        return json.dumps(result, ensure_ascii=False, default=str), False
    except ToolError as e:
        db.rollback()
        _log.warning("mcp %s by %s: %s | args=%s", name, user.email, e, brief_args)
        out = {"error": str(e)}
        if e.hint:
            out["hint"] = e.hint
        return json.dumps(out, ensure_ascii=False), True
    except Exception as e:  # noqa: BLE001
        db.rollback()
        incident = secrets.token_hex(4)
        _log.exception("mcp %s by %s: внутренняя ошибка [%s] | args=%s", name, user.email, incident, brief_args)
        # текст исключения (SQL, параметры) Claude не отдаём — только тип и номер инцидента для поиска в логе
        return json.dumps({"error": f"внутренняя ошибка сервера ({type(e).__name__}), инцидент {incident}",
                           "hint": "Это сбой на стороне планнера, а не в вызове. Сообщите человеку номер инцидента; не повторяйте вызов вслепую."},
                          ensure_ascii=False), True
