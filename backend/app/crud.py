"""Общие CRUD-помощники, чтобы роутеры были тонкими."""
from fastapi import HTTPException
from sqlalchemy.orm import Session
from . import models


def get_or_404(db: Session, model, id_: int):
    obj = db.get(model, id_)
    if not obj:
        raise HTTPException(404, f"{model.__name__} {id_} not found")
    return obj


def fetch_many(db: Session, model, ids: list[int]):
    return [get_or_404(db, model, i) for i in ids]


def log(db: Session, entity, action: str, payload: dict | None = None):
    db.add(models.ActivityLog(entity_type=type(entity).__name__, entity_id=entity.id, action=action, payload=payload))
