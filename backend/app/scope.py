"""Правила видимости: каждый видит своё + порученное ему."""
from fastapi import HTTPException
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session
from . import models


def my_person_id(db: Session, user: models.User) -> int | None:
    return db.scalar(select(models.Person.id).where(models.Person.user_id == user.id))


def assigned_to_me_clause(db: Session, user: models.User):
    """Условие: задача поручена этому пользователю (открытое или закрытое поручение)."""
    pid = my_person_id(db, user)
    if pid is None:
        return False  # SQLAlchemy превратит в ложное условие
    return exists().where(models.Delegation.task_id == models.Task.id, models.Delegation.person_id == pid)


def visible_tasks_query(db: Session, user: models.User):
    return select(models.Task).where(or_(models.Task.owner_id == user.id, assigned_to_me_clause(db, user)))


def is_assignee(db: Session, user: models.User, task: models.Task) -> bool:
    pid = my_person_id(db, user)
    return pid is not None and any(d.person_id == pid for d in task.delegations)


def get_task_visible(db: Session, user: models.User, id_: int) -> models.Task:
    t = db.get(models.Task, id_)
    if not t or not (t.owner_id == user.id or is_assignee(db, user, t)):
        raise HTTPException(404, f"Task {id_} not found")
    return t


def get_owned(db: Session, user: models.User, model, id_: int):
    obj = db.get(model, id_)
    if not obj or getattr(obj, "owner_id", None) != user.id:
        raise HTTPException(404, f"{model.__name__} {id_} not found")
    return obj


def fetch_owned_many(db: Session, user: models.User, model, ids: list[int]):
    return [get_owned(db, user, model, i) for i in ids]
