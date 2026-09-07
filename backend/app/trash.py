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

def soft_delete_task(db: Session, t: models.Task) -> None:
    t.deleted_at = _now(); drop_shares(db, "task", [t.id]); log(db, t, "trash")


def soft_delete_project(db: Session, p: models.Project, ts: datetime | None = None) -> None:
    p.deleted_at = ts or _now(); drop_shares(db, "project", [p.id]); log(db, p, "trash")


def soft_delete_direction(db: Session, d: models.Direction) -> None:
    """Направление и все его живые проекты — одним timestamp (по нему restore направления вернёт проекты)."""
    ts = _now()
    for p in list(d.projects):
        soft_delete_project(db, p, ts)
    d.deleted_at = ts; drop_shares(db, "direction", [d.id]); log(db, d, "trash")


# ── Восстановление ───────────────────────────────────────────────────────────

def restore_direction(db: Session, d: models.Direction) -> None:
    ts = d.deleted_at
    d.deleted_at = None
    for p in d.all_projects:
        if p.deleted_at is not None and p.deleted_at == ts:
            p.deleted_at = None
    log(db, d, "restore")


def restore_project(db: Session, p: models.Project) -> None:
    if p.direction is not None and p.direction.deleted_at is not None:
        raise HTTPException(409, f"Сначала восстановите направление «{p.direction.name}»")
    p.deleted_at = None; log(db, p, "restore")


# ── Навсегда ─────────────────────────────────────────────────────────────────

def hard_delete_task(db: Session, t: models.Task) -> None:
    drop_shares(db, "task", [t.id])
    db.execute(delete(models.task_directions).where(models.task_directions.c.task_id == t.id))  # включая связи с направлениями в корзине
    db.delete(t)   # напоминания/поручения/майндмапы — каскадом


def hard_delete_project(db: Session, p: models.Project) -> None:
    """Задачи остаются (project_id → NULL), удаляется только сам проект."""
    drop_shares(db, "project", [p.id])
    db.execute(update(models.Task).where(models.Task.project_id == p.id).values(project_id=None))
    db.delete(p)


def hard_delete_direction(db: Session, d: models.Direction) -> None:
    """Проекты направления удаляются (задачи теряют project_id), связи task_directions — каскадом; сами задачи остаются."""
    pids = [p.id for p in d.all_projects]
    drop_shares(db, "direction", [d.id]); drop_shares(db, "project", pids)
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
