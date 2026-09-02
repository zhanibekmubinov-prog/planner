from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models, schemas
from ..crud import fetch_many, get_or_404, log
from ..db import get_db

router = APIRouter(prefix="/tasks", tags=["tasks"])

def _apply(obj: models.Task, data: schemas.TaskIn, db: Session):
    d = data.model_dump()
    obj.directions = fetch_many(db, models.Direction, d.pop("direction_ids"))
    obj.tools = fetch_many(db, models.Tool, d.pop("tool_ids"))
    for k, v in d.items(): setattr(obj, k, v)

@router.get("", response_model=list[schemas.TaskOut])
def list_(direction_id: int | None = None, status: models.TaskStatus | None = None, db: Session = Depends(get_db)):
    q = select(models.Task)
    if direction_id: q = q.join(models.Task.directions).where(models.Direction.id == direction_id)
    if status: q = q.where(models.Task.status == status)
    return db.scalars(q.order_by(models.Task.priority, models.Task.deadline)).unique().all()

@router.get("/{id}", response_model=schemas.TaskOut)
def get(id: int, db: Session = Depends(get_db)):
    return get_or_404(db, models.Task, id)

@router.post("", response_model=schemas.TaskOut, status_code=201)
def create(data: schemas.TaskIn, db: Session = Depends(get_db)):
    obj = models.Task(); _apply(obj, data, db)
    db.add(obj); db.flush(); log(db, obj, "create"); db.commit()
    return obj

@router.put("/{id}", response_model=schemas.TaskOut)
def update(id: int, data: schemas.TaskIn, db: Session = Depends(get_db)):
    obj = get_or_404(db, models.Task, id)
    old = obj.status; _apply(obj, data, db)
    log(db, obj, "status_change" if old != obj.status else "update", {"from": old, "to": obj.status})
    db.commit(); return obj

@router.delete("/{id}", status_code=204)
def delete(id: int, db: Session = Depends(get_db)):
    db.delete(get_or_404(db, models.Task, id)); db.commit()

@router.get("/{id}/delegations", response_model=list[schemas.DelegationOut])
def delegations(id: int, db: Session = Depends(get_db)):
    return get_or_404(db, models.Task, id).delegations

@router.get("/{id}/reminders", response_model=list[schemas.ReminderOut])
def reminders(id: int, db: Session = Depends(get_db)):
    return get_or_404(db, models.Task, id).reminders
