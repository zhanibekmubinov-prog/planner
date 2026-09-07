"""Список внешних участников (v0.10). Смотреть и менять — только админ.

Запись в списке = разрешение входить по одноразовой ссылке (см. app/guests.py).
Удаление записи закрывает доступ сразу, в том числе уже открытые сессии.
Данные, которые гость успел создать, остаются — как и у обычного пользователя.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import require_admin
from ..config import settings
from ..db import get_db
from ..guests import is_work_email, norm_email

router = APIRouter(prefix="/guests", tags=["guests"])


def _out(db: Session, g: models.Guest) -> schemas.GuestOut:
    u = db.scalar(select(models.User).where(models.User.email == g.email))
    data = schemas.GuestOut.model_validate(g)
    data.last_login_at = u.last_login_at if u else None
    data.has_password = bool(g.password_hash)
    return data


@router.get("", response_model=list[schemas.GuestOut])
def list_(db: Session = Depends(get_db), _: models.User = Depends(require_admin)):
    rows = db.scalars(select(models.Guest).order_by(models.Guest.name)).all()
    return [_out(db, g) for g in rows]


@router.post("", response_model=schemas.GuestOut, status_code=201)
def create(data: schemas.GuestIn, db: Session = Depends(get_db), admin: models.User = Depends(require_admin)):
    email = norm_email(data.email)
    if is_work_email(email):
        raise HTTPException(400, f"@{email.split('@')[-1]} — рабочий домен: этот человек входит через Microsoft, в гости его добавлять не нужно")
    if not settings.graph_ready:
        raise HTTPException(503, "Почта не настроена на сервере (MS_* для Microsoft Graph) — ссылку для входа отправить будет нечем")
    if db.scalar(select(models.Guest).where(models.Guest.email == email)):
        raise HTTPException(409, "Такой гость уже есть в списке")
    g = models.Guest(email=email, name=data.name, note=(data.note or None), invited_by_id=admin.id)
    db.add(g); db.commit(); db.refresh(g)
    return _out(db, g)


@router.put("/{id}", response_model=schemas.GuestOut)
def update(id: int, data: schemas.GuestIn, db: Session = Depends(get_db), _: models.User = Depends(require_admin)):
    g = db.get(models.Guest, id)
    if not g:
        raise HTTPException(404, "Гость не найден")
    if norm_email(data.email) != g.email:
        raise HTTPException(400, "Почту менять нельзя: удалите гостя и добавьте заново")
    g.name = data.name; g.note = (data.note or None)
    db.commit(); db.refresh(g)
    return _out(db, g)


@router.post("/{id}/reset-link", status_code=202)
async def reset_link(id: int, db: Session = Depends(get_db), _: models.User = Depends(require_admin)):
    """Выслать гостю ссылку, по которой он задаст новый пароль (например, если он его забыл).

    Старый пароль продолжает работать, пока гость не задаст новый.
    """
    g = db.get(models.Guest, id)
    if not g:
        raise HTTPException(404, "Гость не найден")
    if not settings.graph_ready:
        raise HTTPException(503, "Почта не настроена на сервере — отправить ссылку нечем")
    from ..guests import create_login_token, login_email
    from .. import notify
    raw = create_login_token(db, g.email)
    front = (settings.frontend_url or "").rstrip("/")
    subject, html = login_email(f"{front}/#guest={raw}", g.name)
    try:
        await notify.send_email(subject, html, to=g.email)
    except notify.NotifyError as e:
        raise HTTPException(502, f"Письмо не ушло: {e}")
    return {"sent": True, "message": f"Ссылка отправлена на {g.email}. Действует 15 минут."}


@router.delete("/{id}", status_code=204)
def delete(id: int, db: Session = Depends(get_db), _: models.User = Depends(require_admin)):
    """Отзыв доступа: гость больше не войдёт, а его открытые сессии перестают работать сразу."""
    g = db.get(models.Guest, id)
    if not g:
        raise HTTPException(404, "Гость не найден")
    db.execute(models.GuestLoginToken.__table__.delete().where(models.GuestLoginToken.email == g.email))
    db.delete(g); db.commit()
