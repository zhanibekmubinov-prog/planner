from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from .. import models, schemas, trash
from ..auth import current_user
from ..crud import log
from ..db import get_db
from ..scope import OWNER, get_direction_editable, get_direction_visible, get_owned, stamp, visible_directions

router = APIRouter(prefix="/directions", tags=["directions"])

@router.get("", response_model=list[schemas.DirectionOut])
def list_(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Свои направления + те, что открыли мне (или в которых мне открыли проект/задачу — access=via). Корзина не видна."""
    return visible_directions(db, user)

@router.get("/{id}", response_model=schemas.DirectionOut)
def get(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return get_direction_visible(db, user, id)

@router.get("/{id}/impact", response_model=schemas.Impact)
def impact(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Сколько проектов/задач/шар затронет удаление — для текста подтверждения на фронте."""
    return trash.direction_impact(db, get_owned(db, user, models.Direction, id))

@router.post("", response_model=schemas.DirectionOut, status_code=201)
def create(data: schemas.DirectionIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = models.Direction(**data.model_dump(), owner_id=user.id)
    db.add(obj); db.flush(); log(db, obj, "create"); db.commit()
    return stamp(obj, OWNER)

@router.put("/{id}", response_model=schemas.DirectionOut)
def update(id: int, data: schemas.DirectionIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_direction_editable(db, user, id)
    for k, v in data.model_dump().items(): setattr(obj, k, v)
    log(db, obj, "update", {"by": user.id}); db.commit()
    return obj

@router.delete("/{id}", status_code=204)
def delete(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """В корзину: направление и его проекты получают deleted_at, задачи остаются (связи сохраняются для восстановления),
    шары снимаются. Вернуть — POST /directions/{id}/restore; навсегда — DELETE /trash/direction/{id}."""
    obj = get_owned(db, user, models.Direction, id)
    trash.soft_delete_direction(db, obj); db.commit()

@router.post("/{id}/restore", response_model=schemas.DirectionOut)
def restore(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Вернуть из корзины вместе с проектами, удалёнными тем же действием. Доступ (шары) не возвращается."""
    obj = get_owned(db, user, models.Direction, id, include_deleted=True)
    trash.restore_direction(db, obj); db.commit()
    return stamp(obj, OWNER)
