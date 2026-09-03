"""Локальный стенд для скриншотов: бэкенд на sqlite + собранный фронт (dist) с одного порта. Не для прода."""
import os, sys
os.environ.update({"DATABASE_URL": "sqlite:///./_ui.db", "API_TOKEN": "tok", "OWNER_EMAIL": "jack@cis.kz", "SCHEDULER_ENABLED": "false", "ALLOWED_EMAIL_DOMAINS": "cis.kz"})
if os.path.exists("_ui.db"): os.remove("_ui.db")
from fastapi.staticfiles import StaticFiles
from app.db import Base, engine, SessionLocal
from app.main import app
from app import models
from app.auth import issue_session, owner_user
from datetime import date, timedelta
Base.metadata.create_all(engine)

with SessionLocal() as db:
    jack = owner_user(db); jack.name = "Zhanibek Mubinov"
    nur = models.User(email="n.abilkhanov@cis.kz", name="Нурлан Абильханов", ms_oid="oid-n"); db.add(nur)
    db.flush()
    pj = models.Person(name="Zhanibek Mubinov", email=jack.email, user_id=jack.id); pn = models.Person(name="Нурлан Абильханов", email=nur.email, user_id=nur.id)
    db.add_all([pj, pn])
    emba = models.Direction(name="Эмба", goal="Держать месторождение в договорном контуре и без простоев", color="#9a3b1c", owner_id=jack.id)
    kk = models.Direction(name="КК", goal="Кадры и компетенции", color="#0f766e", owner_id=jack.id)
    zakup = models.Direction(name="Закуп", color="#1d4ed8", owner_id=jack.id)
    db.add_all([emba, kk, zakup]); db.flush()
    p1 = models.Project(direction_id=emba.id, name="Договор основной", goal="Подписать до декабря, объём +15%", owner_id=jack.id)
    p2 = models.Project(direction_id=emba.id, name="Договор мини", owner_id=jack.id)
    p3 = models.Project(direction_id=emba.id, name="Договор бурение", goal="Две скважины в Q1", owner_id=jack.id, color="#a16207")
    p4 = models.Project(direction_id=kk.id, name="Найм 2027", owner_id=jack.id)
    db.add_all([p1, p2, p3, p4]); db.flush()
    T = models.TaskStatus; today = date.today()
    def task(title, d, p=None, st=T.backlog, pr=3, dl=None, owner=jack):
        t = models.Task(title=title, status=st, priority=pr, deadline=dl, owner_id=owner.id, project_id=p.id if p else None); t.directions = [d]; db.add(t); return t
    task("Сделать ГРП на скв. 14", emba, p1, T.in_progress, 1, today + timedelta(days=4))
    task("Договориться на следующий год", emba, p1, T.waiting, 2, today - timedelta(days=2))
    task("Почистить месторождение", emba, p1, T.backlog, 3)
    task("Сдать отчёт по добыче", emba, p1, T.done, 3)
    task("Согласовать спецификацию мини-договора", emba, p2, T.backlog, 2, today + timedelta(days=10))
    task("Выбрать подрядчика по бурению", emba, p3, T.in_progress, 1)
    task("Обновить карту рисков Эмбы", emba, None, T.backlog, 4)
    task("Собрать вакансии от начальников участков", kk, p4, T.in_progress, 2)
    t_kk = task("Оценить программу наставничества", kk, None, T.backlog, 3)
    task("Тендер на запчасти Streicher", zakup, None, T.waiting, 1, today + timedelta(days=1))
    db.flush()
    db.add(models.Share(entity_type="project", entity_id=p1.id, user_id=nur.id, permission="edit", granted_by=jack.id))
    db.add(models.Share(entity_type="direction", entity_id=kk.id, user_id=nur.id, permission="view", granted_by=jack.id))
    # Нурлан открыл Джеку своё направление
    dn = models.Direction(name="Сервис ГНБ", goal="Парк Streicher без простоев", color="#6d28d9", owner_id=nur.id); db.add(dn); db.flush()
    pn1 = models.Project(direction_id=dn.id, name="Ремонт HDD-2", owner_id=nur.id); db.add(pn1); db.flush()
    task("Заказать гидромотор", dn, pn1, T.in_progress, 1, owner=nur)
    task("Подготовить акт дефектовки", dn, pn1, T.backlog, 2, owner=nur)
    db.flush()
    db.add(models.Share(entity_type="direction", entity_id=dn.id, user_id=jack.id, permission="view", granted_by=nur.id))
    d_ass = models.Delegation(task_id=t_kk.id, person_id=pn.id)  # поручение Нурлану
    db.add(d_ass)
    db.commit()
    print("JACK", issue_session(jack)); print("NUR", issue_session(nur))

app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"), html=True), name="ui")
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8765, log_level="warning")
