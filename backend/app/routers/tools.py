from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models, schemas
from ..auth import current_user
from ..crud import log
from ..db import get_db
from ..scope import fetch_owned_many, get_owned

router = APIRouter(prefix="/tools", tags=["tools"])

def _apply(obj: models.Tool, data: schemas.ToolIn, db: Session, user: models.User):
    d = data.model_dump()
    obj.tasks = fetch_owned_many(db, user, models.Task, d.pop("task_ids"))
    obj.directions = fetch_owned_many(db, user, models.Direction, d.pop("direction_ids"))
    for k, v in d.items(): setattr(obj, k, v)

@router.get("", response_model=list[schemas.ToolOut])
def list_(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return db.scalars(select(models.Tool).where(models.Tool.owner_id == user.id).order_by(models.Tool.id)).all()

@router.post("", response_model=schemas.ToolOut, status_code=201)
def create(data: schemas.ToolIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = models.Tool(owner_id=user.id); _apply(obj, data, db, user)
    db.add(obj); db.flush(); log(db, obj, "create"); db.commit()
    return obj

@router.put("/{id}", response_model=schemas.ToolOut)
def update(id: int, data: schemas.ToolIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_owned(db, user, models.Tool, id); _apply(obj, data, db, user); db.commit(); return obj

@router.delete("/{id}", status_code=204)
def delete(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    db.delete(get_owned(db, user, models.Tool, id)); db.commit()
