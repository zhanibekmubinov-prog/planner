from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models, schemas
from ..auth import current_user
from ..crud import log
from ..db import get_db
from ..scope import get_owned

router = APIRouter(prefix="/directions", tags=["directions"])

@router.get("", response_model=list[schemas.DirectionOut])
def list_(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return db.scalars(select(models.Direction).where(models.Direction.owner_id == user.id).order_by(models.Direction.id)).all()

@router.post("", response_model=schemas.DirectionOut, status_code=201)
def create(data: schemas.DirectionIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = models.Direction(**data.model_dump(), owner_id=user.id)
    db.add(obj); db.flush(); log(db, obj, "create"); db.commit()
    return obj

@router.put("/{id}", response_model=schemas.DirectionOut)
def update(id: int, data: schemas.DirectionIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_owned(db, user, models.Direction, id)
    for k, v in data.model_dump().items(): setattr(obj, k, v)
    log(db, obj, "update"); db.commit()
    return obj

@router.delete("/{id}", status_code=204)
def delete(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    db.delete(get_owned(db, user, models.Direction, id)); db.commit()
