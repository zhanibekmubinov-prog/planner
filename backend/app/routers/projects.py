"""Проекты (v0.6): Направление → Проекты → Задачи. v0.8: корзина, перенос/копирование в другое направление, impact."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models, schemas, trash
from ..auth import current_user
from ..crud import log
from ..db import get_db
from ..scope import (OWNER, WRITE, _best, direction_access, get_direction_editable, get_owned, get_project_editable, get_project_visible,
                     stamp, visible_projects)

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


@router.get("/{id}/impact", response_model=schemas.Impact)
def impact(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return trash.project_impact(db, get_owned(db, user, models.Project, id))


def _current_viewers(db: Session, p: models.Project) -> dict[int, str]:
    """Кто видит проект через шары направления или самого проекта (кроме владельца): {user_id: permission}."""
    rows = db.execute(select(models.Share.user_id, models.Share.permission).where(
        ((models.Share.entity_type == "direction") & (models.Share.entity_id == p.direction_id)) |
        ((models.Share.entity_type == "project") & (models.Share.entity_id == p.id)))).all()
    out: dict[int, str] = {}
    for uid, perm in rows:
        if uid != p.owner_id:
            out[uid] = _best(out.get(uid), perm) or perm
    return out


def _keeps_access(db: Session, p: models.Project, uid: int, new_dir: models.Direction) -> bool:
    if db.scalar(select(models.Share.id).where(models.Share.entity_type == "project", models.Share.entity_id == p.id, models.Share.user_id == uid)):
        return True
    u = db.get(models.User, uid)
    return bool(u and direction_access(db, u, new_dir) in ("owner", "edit", "view"))


@router.get("/{id}/access-preview", response_model=list[schemas.AccessPreviewRow])
def access_preview(id: int, direction_id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Перед переносом в направление direction_id: кто сейчас видит проект и сохранит ли доступ без дополнительной шары."""
    p = get_project_editable(db, user, id)
    new_dir = db.get(models.Direction, direction_id)
    if not new_dir or new_dir.deleted_at is not None:
        raise HTTPException(404, f"Direction {direction_id} not found")
    out = []
    for uid, perm in _current_viewers(db, p).items():
        u = db.get(models.User, uid)
        if u: out.append(schemas.AccessPreviewRow(user=u, permission=perm, keeps_access=_keeps_access(db, p, uid, new_dir)))
    return out


@router.post("", response_model=schemas.ProjectOut, status_code=201)
def create(data: schemas.ProjectIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    d = get_direction_editable(db, user, data.direction_id)
    obj = models.Project(**data.db_fields(), owner_id=d.owner_id if d.access != OWNER else user.id)
    # проект, созданный в чужом направлении (с правом редактирования), принадлежит владельцу направления,
    # чтобы у того оставался полный контроль; автор сохраняет доступ через направление
    db.add(obj); db.flush(); log(db, obj, "create", {"by": user.id}); db.commit()
    return stamp(obj, OWNER if obj.owner_id == user.id else d.access)


@router.put("/{id}", response_model=schemas.ProjectOut)
def update(id: int, data: schemas.ProjectIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_project_editable(db, user, id)
    if data.direction_id != obj.direction_id:
        new_dir = get_direction_editable(db, user, data.direction_id)
        # В5: новое направление должно быть доступно ВЛАДЕЛЬЦУ проекта (своё или открытое ему на edit) —
        # иначе редактор «уводит» проект туда, где владелец его не увидит
        owner = obj.owner or user
        if new_dir.owner_id != owner.id and direction_access(db, owner, new_dir) not in WRITE:
            raise HTTPException(403, f"Направление «{new_dir.name}» недоступно владельцу проекта ({owner.name}) — перенести туда нельзя")
        old_dir = obj.direction
        viewers = _current_viewers(db, obj)
        # move — задачи проекта теряют старое направление, copy — остаются в обоих (решение владельца 2026-09-04)
        for t in obj.all_tasks:
            if data.move_mode == "move" and old_dir in t.directions:
                t.directions.remove(old_dir)
            if all(x.id != new_dir.id for x in t.directions):
                t.directions.append(new_dir)
        # кому из имевших доступ через старое направление открыть проект напрямую (с прежним правом)
        for uid in data.grant_access_user_ids:
            perm = viewers.get(uid)
            if not perm or uid == obj.owner_id: continue
            exists_ = db.scalar(select(models.Share.id).where(models.Share.entity_type == "project", models.Share.entity_id == obj.id, models.Share.user_id == uid))
            if not exists_:
                db.add(models.Share(entity_type="project", entity_id=obj.id, user_id=uid, permission=perm, granted_by=user.id))
        log(db, obj, "move", {"from": old_dir.id if old_dir else None, "to": new_dir.id, "mode": data.move_mode, "by": user.id})
    acc = obj.access
    for k, v in data.db_fields().items(): setattr(obj, k, v)
    log(db, obj, "update", {"by": user.id}); db.commit()
    return stamp(obj, acc)


@router.delete("/{id}", status_code=204)
def delete(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """В корзину: проект получает deleted_at, задачи не трогаем (project_id остаётся — нужен для восстановления),
    шары на проект снимаются. Вернуть — POST /projects/{id}/restore; навсегда — DELETE /trash/project/{id}."""
    obj = get_owned(db, user, models.Project, id)
    trash.soft_delete_project(db, obj); db.commit()


@router.post("/{id}/restore", response_model=schemas.ProjectOut)
def restore(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Вернуть из корзины. Если направление проекта тоже в корзине — 409 (сначала восстановите направление)."""
    obj = get_owned(db, user, models.Project, id, include_deleted=True)
    trash.restore_project(db, obj); db.commit()
    return stamp(obj, OWNER)
