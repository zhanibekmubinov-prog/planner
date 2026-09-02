"""People, Delegations, Reminders — плоские CRUD без M2M."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models, schemas
from ..crud import get_or_404, log
from ..db import get_db


def make_router(prefix: str, model, In, Out, order):
    r = APIRouter(prefix=f"/{prefix}", tags=[prefix])

    @r.get("", response_model=list[Out])
    def list_(db: Session = Depends(get_db)):
        return db.scalars(select(model).order_by(order)).all()

    @r.post("", response_model=Out, status_code=201)
    def create(data: In, db: Session = Depends(get_db)):
        obj = model(**data.model_dump()); db.add(obj); db.flush(); log(db, obj, "create"); db.commit(); return obj

    @r.put("/{id}", response_model=Out)
    def update(id: int, data: In, db: Session = Depends(get_db)):
        obj = get_or_404(db, model, id)
        for k, v in data.model_dump().items(): setattr(obj, k, v)
        db.commit(); return obj

    @r.delete("/{id}", status_code=204)
    def delete(id: int, db: Session = Depends(get_db)):
        db.delete(get_or_404(db, model, id)); db.commit()

    return r


people = make_router("people", models.Person, schemas.PersonIn, schemas.PersonOut, models.Person.name)
delegations = make_router("delegations", models.Delegation, schemas.DelegationIn, schemas.DelegationOut, models.Delegation.assigned_at.desc())
reminders = make_router("reminders", models.Reminder, schemas.ReminderIn, schemas.ReminderOut, models.Reminder.fire_at)
