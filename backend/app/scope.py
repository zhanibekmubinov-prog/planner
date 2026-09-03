"""Правила видимости и прав (v0.6).

Каждый видит: своё + порученное ему + то, чем с ним поделились.
Уровни доступа к сущности (строка `access`, отдаётся фронту):
  owner    — автор: всё, включая удаление и управление доступом;
  edit     — поделились с правом редактирования: менять можно, удалять и делиться — нельзя;
  view     — поделились на просмотр;
  via      — контейнер виден только потому, что внутри него что-то доступно (например, направление
             проекта, которым поделились): сам контейнер только для навигации;
  assignee — задача поручена этому пользователю: можно менять статус и писать отчёт.
Доступ к направлению распространяется на его проекты и задачи; доступ к проекту — на его задачи.
"""
from fastapi import HTTPException
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session
from . import models

OWNER, EDIT, VIEW, VIA, ASSIGNEE = "owner", "edit", "view", "via", "assignee"
WRITE = (OWNER, EDIT)


def my_person_id(db: Session, user: models.User) -> int | None:
    return db.scalar(select(models.Person.id).where(models.Person.user_id == user.id))


# ── Что с пользователем расшарено ────────────────────────────────────────────

class Grants:
    """Все шары пользователя одним запросом: {entity_type: {entity_id: permission}}."""
    def __init__(self, db: Session, user: models.User):
        rows = db.execute(select(models.Share.entity_type, models.Share.entity_id, models.Share.permission)
                          .where(models.Share.user_id == user.id)).all()
        self.direction: dict[int, str] = {}
        self.project: dict[int, str] = {}
        self.task: dict[int, str] = {}
        for et, eid, perm in rows:
            getattr(self, et, {})[eid] = perm

    @property
    def empty(self) -> bool:
        return not (self.direction or self.project or self.task)


def _best(*perms: str | None) -> str | None:
    """Из нескольких прав выбрать сильнейшее (edit > view)."""
    ps = [p for p in perms if p]
    if not ps:
        return None
    return EDIT if EDIT in ps else VIEW


# ── Уровень доступа к конкретной сущности ────────────────────────────────────

def direction_access(db: Session, user: models.User, d: models.Direction, g: Grants | None = None) -> str | None:
    if d.owner_id == user.id:
        return OWNER
    g = g or Grants(db, user)
    if d.id in g.direction:
        return g.direction[d.id]
    if any(p.id in g.project for p in d.projects):
        return VIA
    if g.task and db.scalar(select(models.task_directions.c.task_id).where(
            models.task_directions.c.direction_id == d.id, models.task_directions.c.task_id.in_(list(g.task))).limit(1)) is not None:
        return VIA
    return None


def project_access(db: Session, user: models.User, p: models.Project, g: Grants | None = None) -> str | None:
    if p.owner_id == user.id:
        return OWNER
    g = g or Grants(db, user)
    direct = _best(g.project.get(p.id), g.direction.get(p.direction_id))
    if direct:
        return direct
    if g.task and db.scalar(select(models.Task.id).where(models.Task.project_id == p.id, models.Task.id.in_(list(g.task))).limit(1)) is not None:
        return VIA
    return None


def task_access(db: Session, user: models.User, t: models.Task, g: Grants | None = None) -> str | None:
    if t.owner_id == user.id:
        return OWNER
    g = g or Grants(db, user)
    shared = _best(g.task.get(t.id), g.project.get(t.project_id) if t.project_id else None,
                   *[g.direction.get(d.id) for d in t.directions])
    if shared == EDIT:
        return EDIT
    if is_assignee(db, user, t):
        return ASSIGNEE   # исполнитель: статус и отчёт — даже если контейнер открыт только на просмотр
    return shared


def stamp(obj, access: str | None):
    """Положить уровень доступа в объект — pydantic (from_attributes) подхватит поле `access`."""
    obj.access = access
    return obj


# ── Списки видимого ──────────────────────────────────────────────────────────

def visible_directions(db: Session, user: models.User) -> list[models.Direction]:
    g = Grants(db, user)
    q = select(models.Direction).where(models.Direction.owner_id == user.id)
    own = db.scalars(q.order_by(models.Direction.id)).all()
    out = [stamp(d, OWNER) for d in own]
    if g.empty:
        return out
    seen = {d.id for d in own}
    ids = set(g.direction)
    if g.project:
        ids |= set(db.scalars(select(models.Project.direction_id).where(models.Project.id.in_(list(g.project)))).all())
    if g.task:
        ids |= set(db.scalars(select(models.task_directions.c.direction_id).where(models.task_directions.c.task_id.in_(list(g.task)))).all())
    ids -= seen
    if ids:
        for d in db.scalars(select(models.Direction).where(models.Direction.id.in_(list(ids))).order_by(models.Direction.id)).all():
            out.append(stamp(d, direction_access(db, user, d, g)))
    return out


def visible_projects(db: Session, user: models.User) -> list[models.Project]:
    g = Grants(db, user)
    own = db.scalars(select(models.Project).where(models.Project.owner_id == user.id).order_by(models.Project.id)).all()
    out = [stamp(p, OWNER) for p in own]
    if g.empty:
        return out
    seen = {p.id for p in own}
    ids = set(g.project)
    if g.direction:
        ids |= set(db.scalars(select(models.Project.id).where(models.Project.direction_id.in_(list(g.direction)))).all())
    if g.task:
        ids |= set(x for x in db.scalars(select(models.Task.project_id).where(models.Task.id.in_(list(g.task)))).all() if x)
    ids -= seen
    if ids:
        for p in db.scalars(select(models.Project).where(models.Project.id.in_(list(ids))).order_by(models.Project.id)).all():
            out.append(stamp(p, project_access(db, user, p, g)))
    return out


def assigned_to_me_clause(db: Session, user: models.User):
    """Условие: задача поручена этому пользователю (открытое или закрытое поручение)."""
    pid = my_person_id(db, user)
    if pid is None:
        return False  # SQLAlchemy превратит в ложное условие
    return exists().where(models.Delegation.task_id == models.Task.id, models.Delegation.person_id == pid)


def visible_tasks_query(db: Session, user: models.User):
    g = Grants(db, user)
    conds = [models.Task.owner_id == user.id, assigned_to_me_clause(db, user)]
    if g.task:
        conds.append(models.Task.id.in_(list(g.task)))
    if g.project:
        conds.append(models.Task.project_id.in_(list(g.project)))
    if g.direction:
        conds.append(exists().where(models.task_directions.c.task_id == models.Task.id,
                                    models.task_directions.c.direction_id.in_(list(g.direction))))
    return select(models.Task).where(or_(*conds))


def stamp_tasks(db: Session, user: models.User, tasks) -> list[models.Task]:
    g = Grants(db, user)
    pid = my_person_id(db, user)
    for t in tasks:
        stamp(t, task_access(db, user, t, g))
        t.assigned_to_me = pid is not None and any(d.person_id == pid for d in t.delegations)
    return list(tasks)


# ── Проверки для роутеров ────────────────────────────────────────────────────

def is_assignee(db: Session, user: models.User, task: models.Task) -> bool:
    pid = my_person_id(db, user)
    return pid is not None and any(d.person_id == pid for d in task.delegations)


def get_task_visible(db: Session, user: models.User, id_: int) -> models.Task:
    t = db.get(models.Task, id_)
    acc = task_access(db, user, t) if t else None
    if not acc:
        raise HTTPException(404, f"Task {id_} not found")
    pid = my_person_id(db, user)
    t.assigned_to_me = pid is not None and any(d.person_id == pid for d in t.delegations)
    return stamp(t, acc)


def get_task_editable(db: Session, user: models.User, id_: int) -> models.Task:
    t = get_task_visible(db, user, id_)
    if t.access not in WRITE:
        raise HTTPException(403, "Только просмотр: эту задачу вам открыли без права редактирования" if t.access == VIEW
                            else "Задача поручена вам — менять можно только статус и отчёт")
    return t


def get_owned(db: Session, user: models.User, model, id_: int):
    obj = db.get(model, id_)
    if not obj or getattr(obj, "owner_id", None) != user.id:
        raise HTTPException(404, f"{model.__name__} {id_} not found")
    return obj


def get_direction_visible(db: Session, user: models.User, id_: int) -> models.Direction:
    d = db.get(models.Direction, id_)
    acc = direction_access(db, user, d) if d else None
    if not acc:
        raise HTTPException(404, f"Direction {id_} not found")
    return stamp(d, acc)


def get_direction_editable(db: Session, user: models.User, id_: int) -> models.Direction:
    d = get_direction_visible(db, user, id_)
    if d.access not in WRITE:
        raise HTTPException(403, "Только просмотр: направление открыто вам без права редактирования")
    return d


def get_project_visible(db: Session, user: models.User, id_: int) -> models.Project:
    p = db.get(models.Project, id_)
    acc = project_access(db, user, p) if p else None
    if not acc:
        raise HTTPException(404, f"Project {id_} not found")
    return stamp(p, acc)


def get_project_editable(db: Session, user: models.User, id_: int) -> models.Project:
    p = get_project_visible(db, user, id_)
    if p.access not in WRITE:
        raise HTTPException(403, "Только просмотр: проект открыт вам без права редактирования")
    return p


def fetch_owned_many(db: Session, user: models.User, model, ids: list[int]):
    return [get_owned(db, user, model, i) for i in ids]


def fetch_directions_for_task(db: Session, user: models.User, ids: list[int], current: list[models.Direction]) -> list[models.Direction]:
    """Направления задачи: свои или открытые на редактирование; уже привязанные к задаче оставляем как есть."""
    keep = {d.id: d for d in current}
    out = []
    for i in ids:
        if i in keep:
            out.append(keep[i]); continue
        out.append(get_direction_editable(db, user, i))
    return out


def fetch_tools_for_task(db: Session, user: models.User, ids: list[int], current: list[models.Tool]) -> list[models.Tool]:
    """Тулы задачи: свои добавлять можно; чужие, уже привязанные автором, — оставляем."""
    keep = {t.id: t for t in current}
    return [keep[i] if i in keep else get_owned(db, user, models.Tool, i) for i in ids]
