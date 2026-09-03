"""Совместный доступ (v0.6): открыть направление / проект / задачу коллеге на просмотр или редактирование.

Приглашать можно по рабочей почте — даже если человек ещё ни разу не входил: заводим заготовку User,
при первом входе через Microsoft она связывается по e-mail (routers/auth.py) и всё уже открыто.
Управлять доступом (давать, менять, отзывать) может только владелец сущности.
"""
import html
import logging
from types import SimpleNamespace
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models, schemas
from ..auth import current_user
from ..config import settings
from ..crud import log
from ..db import get_db

router = APIRouter(prefix="/shares", tags=["shares"])
log_ = logging.getLogger("shares")

ENTITY = {"direction": models.Direction, "project": models.Project, "task": models.Task}
PERMS = ("view", "edit")


def _entity(db: Session, entity_type: str, entity_id: int):
    model = ENTITY.get(entity_type)
    if not model:
        raise HTTPException(400, "entity_type: direction | project | task")
    obj = db.get(model, entity_id)
    if not obj:
        raise HTTPException(404, f"{entity_type} {entity_id} not found")
    return obj


def _owned_entity(db: Session, user: models.User, entity_type: str, entity_id: int):
    obj = _entity(db, entity_type, entity_id)
    if obj.owner_id != user.id:
        raise HTTPException(403, "Управлять доступом может только владелец")
    return obj


def _name(obj) -> str:
    return getattr(obj, "title", None) or getattr(obj, "name", "")


KIND_RU = {"direction": "направление", "project": "проект", "task": "задачу"}
PERM_RU = {"view": "просмотр", "edit": "редактирование"}


def _link(entity_type: str, obj) -> str:
    base = settings.frontend_url.rstrip("/")
    if not base: return ""
    if entity_type == "task": return f"{base}/?task={obj.id}"
    if entity_type == "project": return f"{base}/?project={obj.id}"
    return f"{base}/?direction={obj.id}"


def share_notice(entity_type: str, obj, granter: models.User, permission: str) -> tuple[str, str, str]:
    """Текст уведомления «вам открыли …» (тема, Telegram-HTML, письмо-HTML)."""
    e = html.escape
    name, kind, perm, link = e(_name(obj)), KIND_RU[entity_type], PERM_RU[permission], _link(entity_type, obj)
    subject = f"CIS Planner · {e(granter.name)} открыл(а) вам {kind}: {_name(obj)}"
    tg = (f"⇄ <b>Вам открыли {kind}</b>\n{name}\nОт: {e(granter.name)} · право: {perm}"
          + (f"\n<a href=\"{link}\">Открыть в планнере</a>" if link else "") + "\nВ планнере — раздел «Общие».")
    mail = (f"<h3 style='margin:0 0 8px'>Вам открыли {kind}: {name}</h3><p>От: {e(granter.name)}<br>Право: {perm}</p>"
            + (f"<p><a href='{link}'>Открыть в планнере</a></p>" if link else "") + "<p>В планнере это лежит в разделе «Общие».</p>")
    return subject, tg, mail


async def notify_share(target: SimpleNamespace, subject: str, tg: str, mail: str) -> None:
    """Фоновая отправка: Telegram, если у человека есть chat id, иначе почта через Graph."""
    from ..scheduler import send_to_user
    try:
        res = await send_to_user(target, subject, tg, mail)  # type: ignore[arg-type]
        log_.info("share notice to %s -> %s", target.email, res)
    except Exception as ex:  # noqa: BLE001
        log_.warning("share notice to %s failed: %s", target.email, ex)


def _direction_id(obj) -> int | None:
    if isinstance(obj, models.Direction): return obj.id
    if isinstance(obj, models.Project): return obj.direction_id
    if isinstance(obj, models.Task): return obj.directions[0].id if obj.directions else None
    return None


def find_or_invite_user(db: Session, email: str) -> models.User:
    """Пользователь по почте; если ещё не входил — заготовка, которую подхватит первый вход через Microsoft."""
    email = email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "Укажите рабочую почту, например n.abilkhanov@cis.kz")
    domain = email.split("@")[-1]
    if settings.allowed_domains and domain not in settings.allowed_domains:
        raise HTTPException(400, f"Можно приглашать только сотрудников с почтой @{', @'.join(settings.allowed_domains)}")
    u = db.scalar(select(models.User).where(models.User.email == email))
    if not u:
        local = email.split("@")[0]
        # n.abilkhanov → «N. Abilkhanov» — имя обновится при первом входе
        parts = [p for p in local.replace("_", ".").split(".") if p]
        name = " ".join((p.capitalize() + ("." if len(p) == 1 else "")) for p in parts) or local
        u = models.User(email=email, name=name, is_admin=False)
        db.add(u); db.flush()
    return u


@router.get("", response_model=list[schemas.ShareOut])
def list_(entity_type: str, entity_id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Кому открыта сущность (видит только владелец)."""
    _owned_entity(db, user, entity_type, entity_id)
    return db.scalars(select(models.Share).where(models.Share.entity_type == entity_type, models.Share.entity_id == entity_id)
                      .order_by(models.Share.created_at)).all()


@router.post("", response_model=schemas.ShareOut, status_code=201)
def create(data: schemas.ShareIn, background: BackgroundTasks, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    if data.permission not in PERMS:
        raise HTTPException(400, "permission: view | edit")
    obj = _owned_entity(db, user, data.entity_type, data.entity_id)
    target = find_or_invite_user(db, data.email)
    if target.id == user.id:
        raise HTTPException(400, "Это вы сами — доступ у вас уже есть")
    share = db.scalar(select(models.Share).where(models.Share.entity_type == data.entity_type, models.Share.entity_id == data.entity_id,
                                                  models.Share.user_id == target.id))
    is_new = share is None
    if share:
        share.permission = data.permission
    else:
        share = models.Share(entity_type=data.entity_type, entity_id=data.entity_id, user_id=target.id, permission=data.permission, granted_by=user.id)
        db.add(share); db.flush()
    log(db, obj, "share", {"to": target.email, "permission": data.permission, "by": user.id})
    if is_new:
        # уведомление «вам открыли …» — один раз, при выдаче доступа (смена права не шумит)
        subject, tg, mail = share_notice(data.entity_type, obj, user, data.permission)
        snapshot = SimpleNamespace(email=target.email, telegram_chat_id=target.telegram_chat_id, is_admin=False, name=target.name)
        background.add_task(notify_share, snapshot, subject, tg, mail)
    db.commit(); db.refresh(share)
    return share


@router.delete("/mine", status_code=204)
def leave(entity_type: str, entity_id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Приглашённый отказывается от доступа к объекту сам."""
    share = db.scalar(select(models.Share).where(models.Share.entity_type == entity_type, models.Share.entity_id == entity_id,
                                                  models.Share.user_id == user.id))
    if not share: raise HTTPException(404, "share not found")
    db.delete(share); db.commit()


@router.put("/{id}", response_model=schemas.ShareOut)
def update(id: int, data: schemas.SharePermissionIn, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    if data.permission not in PERMS:
        raise HTTPException(400, "permission: view | edit")
    share = db.get(models.Share, id)
    if not share: raise HTTPException(404, "share not found")
    _owned_entity(db, user, share.entity_type, share.entity_id)
    share.permission = data.permission; db.commit(); db.refresh(share)
    return share


@router.delete("/{id}", status_code=204)
def delete(id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Отозвать доступ. Владелец — у любого; приглашённый — может отказаться от доступа сам."""
    share = db.get(models.Share, id)
    if not share: raise HTTPException(404, "share not found")
    if share.user_id != user.id:
        _owned_entity(db, user, share.entity_type, share.entity_id)
    db.delete(share); db.commit()


@router.get("/with-me", response_model=list[schemas.SharedWithMe])
def with_me(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Раздел «Общие»: что мне открыли другие."""
    out = []
    for s in db.scalars(select(models.Share).where(models.Share.user_id == user.id).order_by(models.Share.created_at.desc())).all():
        obj = db.get(ENTITY[s.entity_type], s.entity_id)
        if not obj: continue
        out.append(schemas.SharedWithMe(entity_type=s.entity_type, entity_id=s.entity_id, permission=s.permission, name=_name(obj),
                                        direction_id=_direction_id(obj), shared_by=s.granter, created_at=s.created_at))
    return out


@router.get("/people", response_model=list[schemas.UserBrief])
def known_people(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """Подсказка при вводе почты: все пользователи планнера (входили или уже приглашены)."""
    return db.scalars(select(models.User).where(models.User.id != user.id).order_by(models.User.name)).all()
