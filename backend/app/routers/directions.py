from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .. import models, schemas
from ..auth import current_user
from ..crud import log
from ..db import get_db
from ..scope import OWNER, get_direction_editable, get_direction_visible, get_owned, visible_directions

router = APIRouter(prefix="/directions", tags=["directions"])

@router.get("", response_model=list[schemas.DirectionOut])
def list_(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Свои направления + те, что открыли мне (или в которых мне открыли проект/задачу — access=via)."""
    return visible_directions(db, user)

@router.get("/{id}", response_model=schemas.DirectionOut)
def get(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return get_direction_visible(db, user, id)

@router.post("", response_model=schemas.DirectionOut, status_code=201)
def create(data: schemas.DirectionIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = models.Direction(**data.model_dump(), owner_id=user.id)
    db.add(obj); db.flush(); log(db, obj, "create"); db.commit()
    obj.access = OWNER
    return obj

@router.put("/{id}", response_model=schemas.DirectionOut)
def update(id: int, data: schemas.DirectionIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_direction_editable(db, user, id)
    for k, v in data.model_dump().items(): setattr(obj, k, v)
    log(db, obj, "update", {"by": user.id}); db.commit()
    return obj

@router.delete("/{id}", status_code=204)
def delete(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_owned(db, user, models.Direction, id)
    if obj.projects:
        # задачи проектов остаются (project_id → NULL каскадом на уровне БД), сами проекты удаляются вместе с направлением
        pass
    db.delete(obj); db.commit()
