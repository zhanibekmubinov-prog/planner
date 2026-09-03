from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models, schemas
from ..auth import current_user
from ..crud import log
from ..db import get_db
from ..scope import get_owned, get_task_visible

router = APIRouter(prefix="/mindmaps", tags=["mindmaps"])


@router.get("", response_model=list[schemas.MindMapOut])
def list_(direction_id: int | None = None, task_id: int | None = None, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    q = select(models.MindMap).where(models.MindMap.owner_id == user.id)
    if direction_id: q = q.where(models.MindMap.direction_id == direction_id)
    if task_id: q = q.where(models.MindMap.task_id == task_id)
    return db.scalars(q.order_by(models.MindMap.updated_at.desc())).all()


@router.get("/{id}", response_model=schemas.MindMapOut)
def get(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return get_owned(db, user, models.MindMap, id)


@router.post("", response_model=schemas.MindMapOut, status_code=201)
def create(data: schemas.MindMapIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    if data.direction_id: get_owned(db, user, models.Direction, data.direction_id)
    if data.task_id: get_task_visible(db, user, data.task_id)
    obj = models.MindMap(**data.model_dump(), owner_id=user.id)
    db.add(obj); db.flush(); log(db, obj, "create"); db.commit()
    return obj


@router.put("/{id}", response_model=schemas.MindMapOut)
def update(id: int, data: schemas.MindMapIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_owned(db, user, models.MindMap, id)
    for k, v in data.model_dump().items(): setattr(obj, k, v)
    db.commit(); return obj


@router.delete("/{id}", status_code=204)
def delete(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    db.delete(get_owned(db, user, models.MindMap, id)); db.commit()
