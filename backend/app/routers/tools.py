from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models, schemas
from ..crud import fetch_many, get_or_404, log
from ..db import get_db

router = APIRouter(prefix="/tools", tags=["tools"])

def _apply(obj: models.Tool, data: schemas.ToolIn, db: Session):
    d = data.model_dump()
    obj.tasks = fetch_many(db, models.Task, d.pop("task_ids"))
    obj.directions = fetch_many(db, models.Direction, d.pop("direction_ids"))
    for k, v in d.items(): setattr(obj, k, v)

@router.get("", response_model=list[schemas.ToolOut])
def list_(db: Session = Depends(get_db)):
    return db.scalars(select(models.Tool).order_by(models.Tool.id)).all()

@router.post("", response_model=schemas.ToolOut, status_code=201)
def create(data: schemas.ToolIn, db: Session = Depends(get_db)):
    obj = models.Tool(); _apply(obj, data, db)
    db.add(obj); db.flush(); log(db, obj, "create"); db.commit()
    return obj

@router.put("/{id}", response_model=schemas.ToolOut)
def update(id: int, data: schemas.ToolIn, db: Session = Depends(get_db)):
    obj = get_or_404(db, models.Tool, id); _apply(obj, data, db); db.commit(); return obj

@router.delete("/{id}", status_code=204)
def delete(id: int, db: Session = Depends(get_db)):
    db.delete(get_or_404(db, models.Tool, id)); db.commit()
