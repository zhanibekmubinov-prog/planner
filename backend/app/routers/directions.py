from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from .. import models, schemas, spaces, trash
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
    # v1.7: направление рождается в том слое, в котором владелец сейчас работает (фронт шлёт space).
    # Слой не пришпилен — автоправило ещё может перевести его в «Организацию» при первом доступе.
    fields = data.model_dump()
    fields["space"] = fields.get("space") or spaces.PERSONAL
    obj = models.Direction(**fields, owner_id=user.id)
    db.add(obj); db.flush(); log(db, obj, "create"); db.commit()
    return stamp(obj, OWNER)

@router.put("/{id}", response_model=schemas.DirectionOut)
def update(id: int, data: schemas.DirectionIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_direction_editable(db, user, id)
    # space здесь не трогаем: слой меняется только через PUT /directions/{id}/space (v1.7)
    for k, v in data.model_dump(exclude={"space"}).items(): setattr(obj, k, v)
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


@router.get("/{id}/space-preview", response_model=schemas.SpacePreview)
def space_preview(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """v1.7: кому открыто направление (само, его проекты и задачи) — для окна «Перенести в Личное»."""
    obj = get_owned(db, user, models.Direction, id)
    return schemas.SpacePreview(people=spaces.access_preview(db, obj))


@router.put("/{id}/space", response_model=schemas.DirectionOut)
def set_space(id: int, data: schemas.DirectionSpaceIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """v1.7: перенести направление между слоями. Перенос всегда пришпиливает слой
    (`space_pinned`), чтобы автоправило больше не возвращало направление обратно.

    `revoke_shares=true` дополнительно снимает весь доступ — владелец выбирает это в окне,
    увидев список тех, кто сейчас видит направление. Само по себе «Личное» доступ НЕ закрывает:
    слой — это удобство раскладки, а не замок.
    """
    obj = get_owned(db, user, models.Direction, id)
    revoked = spaces.revoke_all(db, obj) if (data.space == spaces.PERSONAL and data.revoke_shares) else 0
    obj.space = data.space
    obj.space_pinned = True
    log(db, obj, "space", {"space": data.space, "revoked": revoked, "by": user.id})
    db.commit()
    return stamp(obj, OWNER)
