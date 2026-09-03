"""Проекты (v0.6): Направление → Проекты → Задачи."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models, schemas
from ..auth import current_user
from ..crud import log
from ..db import get_db
from ..scope import OWNER, get_direction_editable, get_owned, get_project_editable, get_project_visible, visible_projects

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[schemas.ProjectOut])
def list_(direction_id: int | None = None, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    items = visible_projects(db, user)
    if direction_id:
        items = [p for p in items if p.direction_id == direction_id]
    return items


@router.get("/{id}", response_model=schemas.ProjectOut)
def get(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return get_project_visible(db, user, id)


@router.post("", response_model=schemas.ProjectOut, status_code=201)
def create(data: schemas.ProjectIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    d = get_direction_editable(db, user, data.direction_id)
    obj = models.Project(**data.model_dump(), owner_id=d.owner_id if d.access != OWNER else user.id)
    # проект, созданный в чужом направлении (с правом редактирования), принадлежит владельцу направления,
    # чтобы у того оставался полный контроль; автор сохраняет доступ через направление
    db.add(obj); db.flush(); log(db, obj, "create", {"by": user.id}); db.commit()
    obj.access = OWNER if obj.owner_id == user.id else d.access
    return obj


@router.put("/{id}", response_model=schemas.ProjectOut)
def update(id: int, data: schemas.ProjectIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_project_editable(db, user, id)
    if data.direction_id != obj.direction_id:
        get_direction_editable(db, user, data.direction_id)
        # перенос проекта в другое направление: задачи проекта получают новое направление
        new_dir = db.get(models.Direction, data.direction_id)
        for t in obj.tasks:
            if all(x.id != new_dir.id for x in t.directions):
                t.directions.append(new_dir)
    for k, v in data.model_dump().items(): setattr(obj, k, v)
    log(db, obj, "update", {"by": user.id}); db.commit()
    return obj


@router.delete("/{id}", status_code=204)
def delete(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Удалить проект. Задачи остаются в направлении (без проекта)."""
    obj = get_owned(db, user, models.Project, id)
    for t in obj.tasks:
        t.project_id = None
    db.flush(); db.delete(obj); db.commit()
