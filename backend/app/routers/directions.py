from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models, schemas
from ..crud import get_or_404, log
from ..db import get_db

router = APIRouter(prefix="/directions", tags=["directions"])

@router.get("", response_model=list[schemas.DirectionOut])
def list_(db: Session = Depends(get_db)):
    return db.scalars(select(models.Direction).order_by(models.Direction.id)).all()

@router.post("", response_model=schemas.DirectionOut, status_code=201)
def create(data: schemas.DirectionIn, db: Session = Depends(get_db)):
    obj = models.Direction(**data.model_dump())
    db.add(obj); db.flush(); log(db, obj, "create"); db.commit()
    return obj

@router.put("/{id}", response_model=schemas.DirectionOut)
def update(id: int, data: schemas.DirectionIn, db: Session = Depends(get_db)):
    obj = get_or_404(db, models.Direction, id)
    for k, v in data.model_dump().items(): setattr(obj, k, v)
    log(db, obj, "update"); db.commit()
    return obj

@router.delete("/{id}", status_code=204)
def delete(id: int, db: Session = Depends(get_db)):
    db.delete(get_or_404(db, models.Direction, id)); db.commit()
