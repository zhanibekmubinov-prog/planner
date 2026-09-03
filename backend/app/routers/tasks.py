from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .. import models, schemas
from ..auth import current_user
from ..crud import log
from ..db import get_db
from ..scope import fetch_owned_many, get_owned, get_task_visible, is_assignee, visible_tasks_query

router = APIRouter(prefix="/tasks", tags=["tasks"])

def _apply(obj: models.Task, data: schemas.TaskIn, db: Session, user: models.User):
    d = data.model_dump()
    obj.directions = fetch_owned_many(db, user, models.Direction, d.pop("direction_ids"))
    obj.tools = fetch_owned_many(db, user, models.Tool, d.pop("tool_ids"))
    for k, v in d.items(): setattr(obj, k, v)

@router.get("", response_model=list[schemas.TaskOut])
def list_(direction_id: int | None = None, status: models.TaskStatus | None = None,
          db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    q = visible_tasks_query(db, user)
    if direction_id: q = q.join(models.Task.directions).where(models.Direction.id == direction_id)
    if status: q = q.where(models.Task.status == status)
    return db.scalars(q.order_by(models.Task.priority, models.Task.deadline)).unique().all()

@router.get("/{id}", response_model=schemas.TaskOut)
def get(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return get_task_visible(db, user, id)

@router.post("", response_model=schemas.TaskOut, status_code=201)
def create(data: schemas.TaskIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = models.Task(owner_id=user.id); _apply(obj, data, db, user)
    db.add(obj); db.flush(); log(db, obj, "create"); db.commit()
    return obj

@router.put("/{id}", response_model=schemas.TaskOut)
def update(id: int, data: schemas.TaskIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_owned(db, user, models.Task, id)
    old = obj.status; _apply(obj, data, db, user)
    log(db, obj, "status_change" if old != obj.status else "update", {"from": old, "to": obj.status})
    db.commit(); return obj


class StatusIn(BaseModel):
    status: models.TaskStatus

@router.post("/{id}/status", response_model=schemas.TaskOut)
def set_status(id: int, data: StatusIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Смена статуса — доступна владельцу и исполнителям (кому поручено)."""
    obj = get_task_visible(db, user, id)
    if obj.owner_id != user.id and not is_assignee(db, user, obj):
        raise HTTPException(403, "not allowed")
    old = obj.status; obj.status = data.status
    log(db, obj, "status_change", {"from": old, "to": obj.status, "by": user.id}); db.commit()
    return obj

@router.delete("/{id}", status_code=204)
def delete(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    db.delete(get_owned(db, user, models.Task, id)); db.commit()

@router.get("/{id}/delegations", response_model=list[schemas.DelegationOut])
def delegations(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return get_task_visible(db, user, id).delegations

@router.get("/{id}/reminders", response_model=list[schemas.ReminderOut])
def reminders(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return get_owned(db, user, models.Task, id).reminders
