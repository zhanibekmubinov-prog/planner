from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .. import models, schemas, trash
from ..auth import current_user
from ..crud import log
from ..db import get_db
from ..scope import (EDIT, OWNER, WRITE, direction_access, fetch_tools_for_task, get_direction_editable, get_owned, get_project_editable,
                     get_task_editable, get_task_visible, orphan_clause, project_access, stamp_tasks, task_access, visible_tasks_query)

# Без prefix: сюда же подключается корзина (/trash) со своим префиксом — main.py подключает только этот router.
router = APIRouter(tags=["tasks"])


def _utc(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _owner_can_reach(db: Session, owner: models.User | None, dirs: list[models.Direction], project: models.Project | None) -> str | None:
    """Все направления и проект задачи должны быть доступны её ВЛАДЕЛЬЦУ (свои или открытые ему на edit) —
    иначе задача пропадёт с его доски или ему утечёт название чужого направления (В1/В2/С7). Возвращает текст ошибки."""
    if owner is None:
        return None
    for d in dirs:
        if d.owner_id != owner.id and direction_access(db, owner, d) not in WRITE:
            return f"Направление «{d.name}» недоступно владельцу задачи ({owner.name}) — переносить в него нельзя"
    if project and project.owner_id != owner.id and project_access(db, owner, project) not in WRITE:
        return f"Проект «{project.name}» недоступен владельцу задачи ({owner.name})"
    return None


def _apply(obj: models.Task, data: schemas.TaskIn, db: Session, user: models.User):
    d = data.model_dump(exclude={"updated_at"})
    dir_ids = list(d.pop("direction_ids"))
    project_id = d.pop("project_id")
    project = None
    if project_id is not None:
        project = get_project_editable(db, user, project_id) if project_id != obj.project_id else db.get(models.Project, project_id)
        if project and project.direction_id not in dir_ids:
            dir_ids.append(project.direction_id)   # проект всегда тянет своё направление
    # направление проекта проверять не нужно: право на проект уже даёт право положить в него задачу
    current = list(obj.directions or [])
    keep = {x.id: x for x in current}
    if project: keep.setdefault(project.direction_id, project.direction)
    new_dirs = [keep[i] if i in keep else get_direction_editable(db, user, i) for i in dir_ids]
    if obj.owner_id is not None and obj.owner_id != user.id:
        # редактор чужой задачи: добавлять направления/проект, недоступные владельцу, нельзя (В1)
        added = [x for x in new_dirs if x.id not in {c.id for c in current}]
        err = _owner_can_reach(db, obj.owner, added, project if project_id != obj.project_id else None)
        if err: raise HTTPException(403, err)
    obj.directions = new_dirs
    obj.tools = fetch_tools_for_task(db, user, d.pop("tool_ids"), obj.tools or [])
    obj.project = project
    for k, v in d.items(): setattr(obj, k, v)


def _owner_for_new(db: Session, obj: models.Task, user: models.User) -> int:
    """Задача, созданная внутри чужого направления/проекта (с правом редактирования), принадлежит хозяину
    этого контейнера — доска остаётся его; автор сохраняет доступ через общий доступ (В2)."""
    if obj.project and obj.project.owner_id:
        owner_id = obj.project.owner_id
    else:
        foreign = [x for x in obj.directions if x.owner_id and x.owner_id != user.id]
        owner_id = foreign[0].owner_id if foreign else user.id
    if owner_id != user.id:
        err = _owner_can_reach(db, db.get(models.User, owner_id), obj.directions, obj.project)
        if err:
            raise HTTPException(400, "Нельзя смешивать свои направления с чужими в одной задаче. " + err)
    return owner_id


@router.get("/tasks", response_model=list[schemas.TaskOut])
def list_(direction_id: int | None = None, project_id: int | None = None, status: models.TaskStatus | None = None, orphans: bool = False,
          db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """orphans=true — мои задачи «без направления» (ни одного живого направления)."""
    q = visible_tasks_query(db, user)
    if direction_id: q = q.join(models.Task.directions).where(models.Direction.id == direction_id)
    if project_id: q = q.where(models.Task.project_id == project_id)
    if status: q = q.where(models.Task.status == status)
    if orphans: q = q.where(models.Task.owner_id == user.id, orphan_clause())
    return stamp_tasks(db, user, db.scalars(q.order_by(models.Task.priority, models.Task.deadline)).unique().all())


@router.get("/tasks/{id}", response_model=schemas.TaskOut)
def get(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return get_task_visible(db, user, id)


@router.post("/tasks", response_model=schemas.TaskOut, status_code=201)
def create(data: schemas.TaskIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = models.Task(); _apply(obj, data, db, user)
    obj.owner_id = _owner_for_new(db, obj, user)
    db.add(obj); db.flush(); log(db, obj, "create", {"by": user.id}); db.commit()
    return get_task_visible(db, user, obj.id)


@router.put("/tasks/{id}", response_model=schemas.TaskOut)
def update(id: int, data: schemas.TaskIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_task_editable(db, user, id)
    if data.updated_at is not None and abs((_utc(obj.updated_at) - _utc(data.updated_at)).total_seconds()) > 0.001:
        raise HTTPException(409, "Задачу изменили в другом окне, обновите карточку")   # С5: lost update
    old = obj.status; _apply(obj, data, db, user)
    db.flush()
    # доступ считаем ДО коммита: если после правки я сам задачу не увижу — откат и 403 (С7)
    if task_access(db, user, obj) not in WRITE:
        db.rollback()
        raise HTTPException(403, "После этой правки вы потеряете доступ к задаче — изменение отменено")
    log(db, obj, "status_change" if old != obj.status else "update", {"from": old, "to": obj.status, "by": user.id})
    db.commit(); return get_task_visible(db, user, id)


class StatusIn(BaseModel):
    status: models.TaskStatus

@router.post("/tasks/{id}/status", response_model=schemas.TaskOut)
def set_status(id: int, data: StatusIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Смена статуса — владельцу, редакторам и исполнителям (кому поручено)."""
    obj = get_task_visible(db, user, id)
    if obj.access == "view":
        raise HTTPException(403, "Только просмотр")
    old = obj.status; obj.status = data.status
    log(db, obj, "status_change", {"from": old, "to": obj.status, "by": user.id}); db.commit()
    return get_task_visible(db, user, id)


@router.delete("/tasks/{id}", status_code=204)
def delete(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """В корзину (soft-delete): задача скрывается везде, шары на неё снимаются; вернуть — POST /tasks/{id}/restore."""
    obj = get_owned(db, user, models.Task, id)
    trash.soft_delete_task(db, obj); db.commit()


@router.post("/tasks/{id}/restore", response_model=schemas.TaskOut)
def restore(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_owned(db, user, models.Task, id, include_deleted=True)
    obj.deleted_at = None; log(db, obj, "restore", {"by": user.id}); db.commit()
    return get_task_visible(db, user, id)


@router.get("/tasks/{id}/delegations", response_model=list[schemas.DelegationOut])
def delegations(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return get_task_visible(db, user, id).delegations


@router.get("/tasks/{id}/reminders", response_model=list[schemas.ReminderOut])
def reminders(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    t = get_task_visible(db, user, id)
    if t.access not in (OWNER, EDIT):
        return []
    return t.reminders


router.include_router(trash.router)   # /trash, /trash/{entity_type}/{id}
