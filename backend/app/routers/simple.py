"""People (общий справочник), Delegations (поручения), Reminders (напоминания владельца задачи)."""
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models, schemas
from ..auth import current_user
from ..crud import get_or_404, log
from ..db import get_db
from ..scope import get_owned, get_task_visible, my_person_id

# ---------------- Люди: общий справочник ----------------
people = APIRouter(prefix="/people", tags=["people"])

@people.get("", response_model=list[schemas.PersonOut])
def people_list(db: Session = Depends(get_db), _: models.User = Depends(current_user)):
    return db.scalars(select(models.Person).order_by(models.Person.name)).all()

@people.post("", response_model=schemas.PersonOut, status_code=201)
def people_create(data: schemas.PersonIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = models.Person(**data.model_dump())
    if obj.email:
        u = db.scalar(select(models.User).where(models.User.email == obj.email.lower()))
        if u and not db.scalar(select(models.Person).where(models.Person.user_id == u.id)): obj.user_id = u.id
    db.add(obj); db.flush(); log(db, obj, "create"); db.commit(); return obj

@people.put("/{id}", response_model=schemas.PersonOut)
def people_update(id: int, data: schemas.PersonIn, db: Session = Depends(get_db), _: models.User = Depends(current_user)):
    obj = get_or_404(db, models.Person, id)
    for k, v in data.model_dump().items(): setattr(obj, k, v)
    db.commit(); return obj

@people.delete("/{id}", status_code=204)
def people_delete(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_or_404(db, models.Person, id)
    if obj.user_id:
        raise HTTPException(400, "Нельзя удалить человека, который входит в планнер")
    db.delete(obj); db.commit()


class PersonSummary(BaseModel):
    person: schemas.PersonOut
    total: int; open: int; done: int; overdue: int; check_due: int
    tasks: list[schemas.TaskOut]
    delegations: list[schemas.DelegationOut]

@people.get("/{id}/summary", response_model=PersonSummary)
def people_summary(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Сводка по человеку: что Я ему поручил и как идёт."""
    person = get_or_404(db, models.Person, id)
    delegs = db.scalars(select(models.Delegation).join(models.Task).where(models.Delegation.person_id == id, models.Task.owner_id == user.id)
                        .order_by(models.Delegation.assigned_at.desc())).all()
    tasks = {d.task_id: d.task for d in delegs}.values()
    tasks = sorted(tasks, key=lambda t: (t.status == models.TaskStatus.done, t.priority))
    now = datetime.now(timezone.utc); today = date.today()
    open_ = [t for t in tasks if t.status != models.TaskStatus.done]
    def utc(dt): return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    return PersonSummary(
        person=person, total=len(tasks), open=len(open_), done=len(tasks) - len(open_),
        overdue=sum(1 for t in open_ if t.deadline and t.deadline < today),
        check_due=sum(1 for d in delegs if d.status == models.DelegationStatus.open and d.check_at and utc(d.check_at) <= now and d.task.status != models.TaskStatus.done),
        tasks=tasks, delegations=delegs,
    )


# ---------------- Поручения ----------------
delegations = APIRouter(prefix="/delegations", tags=["delegations"])

@delegations.get("", response_model=list[schemas.DelegationOut])
def deleg_list(mine: bool = False, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """mine=true — поручения МНЕ (входящие); иначе — поручения по моим задачам."""
    if mine:
        pid = my_person_id(db, user)
        if pid is None: return []
        q = select(models.Delegation).where(models.Delegation.person_id == pid)
    else:
        q = select(models.Delegation).join(models.Task).where(models.Task.owner_id == user.id)
    return db.scalars(q.order_by(models.Delegation.assigned_at.desc())).all()

@delegations.post("", response_model=schemas.DelegationOut, status_code=201)
def deleg_create(data: schemas.DelegationIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    get_owned(db, user, models.Task, data.task_id); get_or_404(db, models.Person, data.person_id)
    obj = models.Delegation(**data.model_dump()); db.add(obj); db.flush(); log(db, obj, "create"); db.commit(); return obj

@delegations.put("/{id}", response_model=schemas.DelegationOut)
def deleg_update(id: int, data: schemas.DelegationIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_or_404(db, models.Delegation, id); get_owned(db, user, models.Task, obj.task_id)
    if obj.check_at != data.check_at: obj.notified_at = None  # перенесли проверку — напомнить снова
    for k, v in data.model_dump().items(): setattr(obj, k, v)
    db.commit(); return obj

@delegations.put("/{id}/report", response_model=schemas.DelegationOut)
def deleg_report(id: int, data: schemas.DelegationReportIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Исполнитель отчитывается: статус поручения и текст отчёта."""
    obj = get_or_404(db, models.Delegation, id)
    pid = my_person_id(db, user)
    if obj.person_id != pid and obj.task.owner_id != user.id:
        raise HTTPException(403, "not your delegation")
    obj.status = data.status; obj.report = data.report
    log(db, obj, "report", {"status": data.status, "by": user.id}); db.commit(); return obj

@delegations.delete("/{id}", status_code=204)
def deleg_delete(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_or_404(db, models.Delegation, id); get_owned(db, user, models.Task, obj.task_id)
    db.delete(obj); db.commit()


# ---------------- Напоминания ----------------
reminders = APIRouter(prefix="/reminders", tags=["reminders"])

@reminders.get("", response_model=list[schemas.ReminderOut])
def rem_list(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return db.scalars(select(models.Reminder).join(models.Task).where(models.Task.owner_id == user.id).order_by(models.Reminder.fire_at)).all()

@reminders.post("", response_model=schemas.ReminderOut, status_code=201)
def rem_create(data: schemas.ReminderIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    get_owned(db, user, models.Task, data.task_id)
    obj = models.Reminder(**data.model_dump()); db.add(obj); db.flush(); log(db, obj, "create"); db.commit(); return obj

@reminders.put("/{id}", response_model=schemas.ReminderOut)
def rem_update(id: int, data: schemas.ReminderIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_or_404(db, models.Reminder, id); get_owned(db, user, models.Task, obj.task_id)
    for k, v in data.model_dump().items(): setattr(obj, k, v)
    db.commit(); return obj

@reminders.delete("/{id}", status_code=204)
def rem_delete(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    obj = get_or_404(db, models.Reminder, id); get_owned(db, user, models.Task, obj.task_id)
    db.delete(obj); db.commit()
