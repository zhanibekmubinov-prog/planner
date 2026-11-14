"""Майндмапы.

v1.8 — совместная работа:
  * карта видна и правится вслед за направлением / задачей, к которым привязана, плюс её можно
    открыть отдельно (Share с entity_type="mindmap"); правила — scope.mindmap_access;
  * правки идут пачками операций над узлами (POST /{id}/ops, см. mindmap_ops.py) — двое
    одновременно больше не затирают друг друга;
  * после каждой принятой правки карта рассылается открытым живым соединениям (live.py).
Удалить карту, поменять её привязку и раздавать доступ — только владелец (создатель).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.orm import Session
from .. import models, schemas
from ..auth import current_user
from ..crud import log
from ..db import get_db
from ..live import hub
from ..mindmap_ops import OpError, apply_ops, normalize, validate
from ..scope import (OWNER, WRITE, get_direction_editable, get_mindmap_editable, get_mindmap_visible, get_task_visible,
                     mindmap_access, stamp, visible_mindmaps)

router = APIRouter(prefix="/mindmaps", tags=["mindmaps"])


def snapshot(m: models.MindMap) -> dict:
    return {"type": "snapshot", "version": m.version, "title": m.title, "data": m.data,
            "direction_id": m.direction_id, "task_id": m.task_id}


def _relink(db: Session, user: models.User, m: models.MindMap, direction_id: int | None, task_id: int | None) -> bool:
    """Сменить привязку карты. Это меняет круг тех, кто карту видит, — поэтому только владелец."""
    if direction_id == m.direction_id and task_id == m.task_id:
        return False
    if m.access != OWNER:
        raise HTTPException(403, "Привязку карты к направлению или задаче меняет только её владелец")
    if direction_id and direction_id != m.direction_id:
        get_direction_editable(db, user, direction_id)
    if task_id and task_id != m.task_id:
        get_task_visible(db, user, task_id)
    m.direction_id, m.task_id = direction_id, task_id
    return True


@router.get("", response_model=list[schemas.MindMapOut])
def list_(direction_id: int | None = None, task_id: int | None = None, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    maps = visible_mindmaps(db, user)
    if direction_id: maps = [m for m in maps if m.direction_id == direction_id]
    if task_id: maps = [m for m in maps if m.task_id == task_id]
    return maps


@router.get("/{id}", response_model=schemas.MindMapOut)
def get(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return get_mindmap_visible(db, user, id)


@router.post("", response_model=schemas.MindMapOut, status_code=201)
def create(data: schemas.MindMapIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    if data.direction_id: get_direction_editable(db, user, data.direction_id)
    if data.task_id: get_task_visible(db, user, data.task_id)
    obj = models.MindMap(**data.model_dump(exclude={"version"}), owner_id=user.id, version=0)
    db.add(obj); db.flush(); log(db, obj, "create"); db.commit(); db.refresh(obj)
    return stamp(obj, OWNER)


@router.put("/{id}", response_model=schemas.MindMapOut)
def update(id: int, data: schemas.MindMapIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Заменить карту целиком. Редактор v1.8 так не делает (шлёт операции); маршрут оставлен для
    старых клиентов и скриптов. Передали version, а карту уже поменяли — 409."""
    obj = get_mindmap_editable(db, user, id)
    if data.version is not None and data.version != obj.version:
        raise HTTPException(409, "Карту успели изменить — откройте её заново, чтобы не затереть чужие правки")
    _relink(db, user, obj, data.direction_id, data.task_id)
    obj.title, obj.data = data.title, data.data
    obj.version = (obj.version or 0) + 1
    acc = obj.access
    db.commit(); db.refresh(obj)
    hub.publish(id, snapshot(obj))
    return stamp(obj, acc)


@router.put("/{id}/link", response_model=schemas.MindMapOut)
def relink(id: int, data: schemas.MindMapLinkIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Привязать карту к другому направлению / задаче, не трогая её содержимое."""
    obj = get_mindmap_visible(db, user, id)
    acc = obj.access
    if _relink(db, user, obj, data.direction_id, data.task_id):
        db.commit(); db.refresh(obj)
        hub.publish(id, {"type": "meta", "direction_id": obj.direction_id, "task_id": obj.task_id})
    return stamp(obj, acc)


@router.post("/{id}/ops", response_model=schemas.MindMapOpsOut)
def apply(id: int, body: schemas.MindMapOpsIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Принять пачку операций над узлами. Пропущенные (узел уже удалили и т. п.) — в `skipped`, это не ошибка."""
    try:
        ops = validate(body.ops)
    except OpError as e:
        raise HTTPException(400, str(e))
    # Строка карты под замком до конца транзакции: две пачки одновременно не прочитают одну и ту же
    # версию дерева (иначе вторая затёрла бы первую). В sqlite FOR UPDATE игнорируется — там и так один писатель.
    obj = db.scalars(select(models.MindMap).where(models.MindMap.id == id).with_for_update()).first()
    acc = mindmap_access(db, user, obj) if obj else None
    if not acc:
        raise HTTPException(404, f"MindMap {id} not found")
    if acc not in WRITE:
        raise HTTPException(403, "Только просмотр: карту открыли вам без права редактирования")
    root, title, applied, skipped = apply_ops(normalize(obj.data, obj.title), obj.title, ops)
    if applied:
        obj.data, obj.title = root, title
        obj.version = (obj.version or 0) + 1
        db.commit(); db.refresh(obj)
        hub.publish(id, {"type": "ops", "version": obj.version, "batch": body.batch,
                         "by": {"id": user.id, "name": user.name}, "ops": applied, "title": obj.title})
    else:
        db.rollback()   # ничего не поменялось — просто отпускаем замок
    return schemas.MindMapOpsOut(version=obj.version, title=obj.title, data=obj.data, applied=len(applied), skipped=skipped)


@router.delete("/{id}", status_code=204)
def delete(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_mindmap_visible(db, user, id)
    if obj.access != OWNER:
        raise HTTPException(403, "Удалить карту может только её владелец")
    db.execute(sa_delete(models.Share).where(models.Share.entity_type == "mindmap", models.Share.entity_id == id))
    db.delete(obj); db.commit()
    hub.publish(id, {"type": "deleted"})
