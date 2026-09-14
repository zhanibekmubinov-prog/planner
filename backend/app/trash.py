"""Корзина (v0.8, soft-delete).

Удаление направления/проекта/задачи ставит `deleted_at`; связи (task_directions, project_id) не трогаем — они нужны
для восстановления. Шары на удалённое снимаются сразу (восстановление доступ не возвращает). Удалить навсегда —
`DELETE /trash/{entity_type}/{id}`, вся корзина — `DELETE /trash`; автоочистка старше 30 дней — `purge_trash()`
(вызывает планировщик раз в сутки).
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session
from . import models, schemas
from .auth import current_user
from .crud import log
from .db import get_db
from .scope import alive, get_owned, my_person_id, stamp, OWNER

router = APIRouter(prefix="/trash", tags=["trash"])
ENTITY = {"direction": models.Direction, "project": models.Project, "task": models.Task}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def drop_shares(db: Session, entity_type: str, ids: list[int]) -> None:
    """Снять все шары на сущности (С1/Н7): в корзине они не нужны, а мусорные строки давали бы доступ к новым id."""
    if ids:
        db.execute(delete(models.Share).where(models.Share.entity_type == entity_type, models.Share.entity_id.in_(ids)))


# ── В корзину ────────────────────────────────────────────────────────────────

def soft_delete_task(db: Session, t: models.Task, ts: datetime | None = None) -> None:
    t.deleted_at = ts or _now(); drop_shares(db, "task", [t.id]); log(db, t, "trash")


def soft_delete_project(db: Session, p: models.Project, ts: datetime | None = None) -> None:
    """v1.6 (решение владельца 2026-09-14): задачи проекта уходят в корзину ВМЕСТЕ с ним, одним timestamp.
    Раньше они оставались живыми и всплывали в «Все задачи» как «без проекта» — это и было симптомом."""
    ts = ts or _now()
    for t in list(p.tasks):        # только живые (см. Project.tasks в models.py)
        soft_delete_task(db, t, ts)
    p.deleted_at = ts; drop_shares(db, "project", [p.id]); log(db, p, "trash")


def soft_delete_direction(db: Session, d: models.Direction) -> None:
    """Направление, его живые проекты и задачи — одним timestamp (по нему restore вернёт всё разом).

    Задача уходит в корзину вместе с направлением, только если больше нигде не живёт: если она числится
    ещё в одном живом направлении, она там и остаётся (задачи кросс-направленческие).
    """
    ts = _now()
    for p in list(d.projects):
        soft_delete_project(db, p, ts)
    for t in list(d.tasks):        # только живые задачи этого направления
        if t.deleted_at is not None:
            continue               # уже ушла вместе со своим проектом
        if any(x.id != d.id for x in t.directions):
            continue               # живёт ещё в одном направлении — остаётся там
        soft_delete_task(db, t, ts)
    d.deleted_at = ts; drop_shares(db, "direction", [d.id]); log(db, d, "trash")


# ── Восстановление ───────────────────────────────────────────────────────────

def _restore_tasks_deleted_with(db: Session, ts: datetime | None, ids: list[int]) -> int:
    """Вернуть из корзины задачи, ушедшие туда тем же действием (тот же timestamp)."""
    if ts is None or not ids:
        return 0
    rows = db.scalars(select(models.Task).where(models.Task.id.in_(ids), models.Task.deleted_at == ts)).all()
    for t in rows:
        t.deleted_at = None
    return len(rows)


def restore_direction(db: Session, d: models.Direction) -> None:
    """Возвращает направление вместе с проектами и задачами, удалёнными тем же действием."""
    ts = d.deleted_at
    d.deleted_at = None
    task_ids = set(db.scalars(select(models.task_directions.c.task_id).where(models.task_directions.c.direction_id == d.id)).all())
    for p in d.all_projects:
        if p.deleted_at is not None and p.deleted_at == ts:
            p.deleted_at = None
            task_ids |= set(db.scalars(select(models.Task.id).where(models.Task.project_id == p.id)).all())
    _restore_tasks_deleted_with(db, ts, list(task_ids))
    log(db, d, "restore")


def restore_project(db: Session, p: models.Project) -> None:
    """Возвращает проект вместе с задачами, ушедшими в корзину тем же действием."""
    if p.direction is not None and p.direction.deleted_at is not None:
        raise HTTPException(409, f"Сначала восстановите направление «{p.direction.name}»")
    ts = p.deleted_at
    p.deleted_at = None
    _restore_tasks_deleted_with(db, ts, list(db.scalars(select(models.Task.id).where(models.Task.project_id == p.id)).all()))
    log(db, p, "restore")


# ── Навсегда ─────────────────────────────────────────────────────────────────

def hard_delete_task(db: Session, t: models.Task) -> None:
    drop_shares(db, "task", [t.id])
    db.execute(delete(models.task_directions).where(models.task_directions.c.task_id == t.id))  # включая связи с направлениями в корзине
    db.delete(t)   # напоминания/поручения/майндмапы — каскадом


def _hard_delete_tasks_deleted_with(db: Session, ts: datetime | None, ids: list[int]) -> None:
    """v1.6: задачи, ушедшие в корзину вместе с контейнером, стираются вместе с ним же —
    иначе после «удалить навсегда» они остались бы в корзине висячими строками."""
    if ts is None or not ids:
        return
    for t in db.scalars(select(models.Task).where(models.Task.id.in_(ids), models.Task.deleted_at == ts)).all():
        hard_delete_task(db, t)
    db.flush()


def hard_delete_project(db: Session, p: models.Project) -> None:
    """Задачи, удалённые вместе с проектом, стираются; остальные остаются (project_id → NULL)."""
    drop_shares(db, "project", [p.id])
    _hard_delete_tasks_deleted_with(db, p.deleted_at, list(db.scalars(select(models.Task.id).where(models.Task.project_id == p.id)).all()))
    db.execute(update(models.Task).where(models.Task.project_id == p.id).values(project_id=None))
    db.delete(p)


def hard_delete_direction(db: Session, d: models.Direction) -> None:
    """Проекты направления удаляются, задачи, ушедшие в корзину вместе с направлением, — тоже;
    остальные задачи остаются (теряют project_id), связи task_directions — каскадом."""
    pids = [p.id for p in d.all_projects]
    drop_shares(db, "direction", [d.id]); drop_shares(db, "project", pids)
    ids = set(db.scalars(select(models.task_directions.c.task_id).where(models.task_directions.c.direction_id == d.id)).all())
    if pids:
        ids |= set(db.scalars(select(models.Task.id).where(models.Task.project_id.in_(pids))).all())
    _hard_delete_tasks_deleted_with(db, d.deleted_at, list(ids))
    if pids:
        db.execute(update(models.Task).where(models.Task.project_id.in_(pids)).values(project_id=None))
    db.execute(delete(models.task_directions).where(models.task_directions.c.direction_id == d.id))
    db.delete(d)


def purge_trash(db: Session, older_than_days: int = 30, owner_id: int | None = None) -> dict:
    """Удалить навсегда всё из корзины старше N дней (owner_id — только корзину этого пользователя; None — всех).
    Порядок: задачи → проекты → направления. Возвращает {"tasks": n, "projects": n, "directions": n}."""
    cutoff = _now() - timedelta(days=older_than_days)
    out = {}
    for key, model, fn in (("tasks", models.Task, hard_delete_task), ("projects", models.Project, hard_delete_project),
                           ("directions", models.Direction, hard_delete_direction)):
        q = select(model).where(model.deleted_at.is_not(None))
        if older_than_days > 0:
            q = q.where(model.deleted_at <= cutoff)
        if owner_id is not None:
            q = q.where(model.owner_id == owner_id)
        rows = db.scalars(q).all()
        # deleted_at в sqlite может быть без tz — сравниваем в Python на всякий случай
        rows = [r for r in rows if older_than_days <= 0 or (r.deleted_at.replace(tzinfo=r.deleted_at.tzinfo or timezone.utc) <= cutoff)]
        for r in rows:
            fn(db, r)
        db.flush()
        out[key] = len(rows)
    db.commit()
    return out


# ── Impact (числа для подтверждения удаления) ────────────────────────────────

def direction_impact(db: Session, d: models.Direction) -> schemas.Impact:
    pids = [p.id for p in d.projects]
    in_dir = select(models.task_directions.c.task_id).where(models.task_directions.c.direction_id == d.id)
    cond = models.Task.id.in_(in_dir)
    if pids:
        cond = or_(cond, models.Task.project_id.in_(pids))
    tasks = db.scalars(select(models.Task).where(alive(models.Task), cond)).all()
    shares = db.scalar(select(func.count()).select_from(models.Share).where(or_(
        (models.Share.entity_type == "direction") & (models.Share.entity_id == d.id),
        (models.Share.entity_type == "project") & models.Share.entity_id.in_(pids or [-1]))))
    return schemas.Impact(projects=len(pids), tasks=len(tasks), open_tasks=sum(1 for t in tasks if t.status != models.TaskStatus.done), shares=shares or 0)


def project_impact(db: Session, p: models.Project) -> schemas.Impact:
    tasks = db.scalars(select(models.Task).where(alive(models.Task), models.Task.project_id == p.id)).all()
    shares = db.scalar(select(func.count()).select_from(models.Share).where(models.Share.entity_type == "project", models.Share.entity_id == p.id))
    return schemas.Impact(projects=0, tasks=len(tasks), open_tasks=sum(1 for t in tasks if t.status != models.TaskStatus.done), shares=shares or 0)


# ── Роуты /trash ─────────────────────────────────────────────────────────────

@router.get("", response_model=schemas.TrashOut)
def list_(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Моя корзина: удалённые направления, проекты и задачи (с deleted_at)."""
    def mine(model):
        return db.scalars(select(model).where(model.owner_id == user.id, model.deleted_at.is_not(None)).order_by(model.deleted_at.desc())).all()
    pid = my_person_id(db, user)
    tasks = []
    for t in mine(models.Task):
        stamp(t, OWNER); t.assigned_to_me = pid is not None and any(x.person_id == pid for x in t.delegations); tasks.append(t)
    return schemas.TrashOut(directions=[stamp(x, OWNER) for x in mine(models.Direction)],
                            projects=[stamp(x, OWNER) for x in mine(models.Project)], tasks=tasks)


@router.delete("", status_code=204)
def purge_all(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Очистить всю мою корзину (удалить навсегда)."""
    purge_trash(db, older_than_days=0, owner_id=user.id)


@router.delete("/{entity_type}/{id}", status_code=204)
def purge_one(entity_type: str, id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Удалить навсегда одну сущность из корзины (с прежними каскадами)."""
    model = ENTITY.get(entity_type)
    if not model:
        raise HTTPException(400, "entity_type: direction | project | task")
    obj = get_owned(db, user, model, id, include_deleted=True)
    if obj.deleted_at is None:
        raise HTTPException(409, "Сущность не в корзине — сначала удалите её обычным способом")
    {"direction": hard_delete_direction, "project": hard_delete_project, "task": hard_delete_task}[entity_type](db, obj)
    db.commit()
