from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .. import models, schemas
from ..auth import current_user
from ..crud import log
from ..db import get_db
from ..scope import (OWNER, fetch_directions_for_task, fetch_tools_for_task, get_owned, get_project_editable, get_task_editable,
                     get_task_visible, is_assignee, stamp_tasks, visible_tasks_query)

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _apply(obj: models.Task, data: schemas.TaskIn, db: Session, user: models.User):
    d = data.model_dump()
    dir_ids = list(d.pop("direction_ids"))
    project_id = d.pop("project_id")
    project = None
    if project_id is not None:
        project = get_project_editable(db, user, project_id) if project_id != obj.project_id else db.get(models.Project, project_id)
        if project and project.direction_id not in dir_ids:
            dir_ids.append(project.direction_id)   # проект всегда тянет своё направление
    # направление проекта проверять не нужно: право на проект уже даёт право положить в него задачу
    implied = [project.direction] if project else []
    obj.directions = fetch_directions_for_task(db, user, dir_ids, list(obj.directions or []) + implied)
    obj.tools = fetch_tools_for_task(db, user, d.pop("tool_ids"), obj.tools or [])
    obj.project = project
    for k, v in d.items(): setattr(obj, k, v)


def _owner_for_new(obj: models.Task, user: models.User) -> int:
    """Задача, созданная внутри чужого направления/проекта (с правом редактирования), принадлежит хозяину
    этого направления — доска остаётся его; автор сохраняет доступ через общий доступ."""
    if any(d.owner_id == user.id for d in obj.directions) or not obj.directions:
        return user.id
    if obj.project and obj.project.owner_id:
        return obj.project.owner_id
    return obj.directions[0].owner_id or user.id


@router.get("", response_model=list[schemas.TaskOut])
def list_(direction_id: int | None = None, project_id: int | None = None, status: models.TaskStatus | None = None,
          db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    q = visible_tasks_query(db, user)
    if direction_id: q = q.join(models.Task.directions).where(models.Direction.id == direction_id)
    if project_id: q = q.where(models.Task.project_id == project_id)
    if status: q = q.where(models.Task.status == status)
    return stamp_tasks(db, user, db.scalars(q.order_by(models.Task.priority, models.Task.deadline)).unique().all())


@router.get("/{id}", response_model=schemas.TaskOut)
def get(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return get_task_visible(db, user, id)


@router.post("", response_model=schemas.TaskOut, status_code=201)
def create(data: schemas.TaskIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = models.Task(); _apply(obj, data, db, user)
    obj.owner_id = _owner_for_new(obj, user)
    db.add(obj); db.flush(); log(db, obj, "create", {"by": user.id}); db.commit()
    return get_task_visible(db, user, obj.id)


@router.put("/{id}", response_model=schemas.TaskOut)
def update(id: int, data: schemas.TaskIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_task_editable(db, user, id)
    old = obj.status; _apply(obj, data, db, user)
    log(db, obj, "status_change" if old != obj.status else "update", {"from": old, "to": obj.status, "by": user.id})
    db.commit(); return get_task_visible(db, user, id)


class StatusIn(BaseModel):
    status: models.TaskStatus

@router.post("/{id}/status", response_model=schemas.TaskOut)
def set_status(id: int, data: StatusIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Смена статуса — владельцу, редакторам и исполнителям (кому поручено)."""
    obj = get_task_visible(db, user, id)
    if obj.access == "view":
        raise HTTPException(403, "Только просмотр")
    old = obj.status; obj.status = data.status
    log(db, obj, "status_change", {"from": old, "to": obj.status, "by": user.id}); db.commit()
    return get_task_visible(db, user, id)


@router.delete("/{id}", status_code=204)
def delete(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    db.delete(get_owned(db, user, models.Task, id)); db.commit()


@router.get("/{id}/delegations", response_model=list[schemas.DelegationOut])
def delegations(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return get_task_visible(db, user, id).delegations


@router.get("/{id}/reminders", response_model=list[schemas.ReminderOut])
def reminders(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    t = get_task_visible(db, user, id)
    if t.access not in (OWNER, "edit"):
        return []
    return t.reminders
