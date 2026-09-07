"""Одноразовые коды привязки Telegram (v0.9).

Пользователь нажимает в профиле «Подключить Telegram» → открывается
https://t.me/<бот>?start=<код> → бот получает `/start <код>` и сам сохраняет
chat id в его учётной записи. Копировать id руками больше не нужно.

Код не хранится в базе (никакой миграции): это подпись HMAC от id пользователя
и номера текущих суток на SESSION_SECRET. Живёт сутки (принимаем текущие и
предыдущие сутки, чтобы ссылка, открытая около полуночи, ещё работала).
"""
import hashlib
import hmac
import time

from sqlalchemy.orm import Session

from . import models
from .config import settings

_DAY = 86400


def _sig(user_id: int, bucket: int) -> str:
    msg = f"tg-link:{user_id}:{bucket}".encode()
    return hmac.new(settings.session_secret.encode(), msg, hashlib.sha256).hexdigest()[:10]


def make_code(user_id: int) -> str:
    """Код для ссылки t.me/<бот>?start=<код>. Только цифры, буквы и дефис — как требует Telegram."""
    return f"{user_id}-{_sig(user_id, int(time.time() // _DAY))}"


def resolve_code(db: Session, code: str) -> models.User | None:
    """Пользователь по коду или None, если код чужой, испорченный или старше суток."""
    code = (code or "").strip()
    if "-" not in code:
        return None
    left, sig = code.rsplit("-", 1)
    if not left.isdigit():
        return None
    uid, now = int(left), int(time.time() // _DAY)
    if not any(hmac.compare_digest(sig, _sig(uid, b)) for b in (now, now - 1)):
        return None
    return db.get(models.User, uid)


def bind_chat(db: Session, user: models.User, chat_id: str) -> None:
    """Привязать чат к пользователю. Один чат = один человек: у остальных эта привязка снимается."""
    chat_id = str(chat_id)
    for other in db.query(models.User).filter(models.User.telegram_chat_id == chat_id, models.User.id != user.id):
        other.telegram_chat_id = None
    for p in db.query(models.Person).filter(models.Person.telegram_chat_id == chat_id, models.Person.user_id != user.id):
        p.telegram_chat_id = None
    user.telegram_chat_id = chat_id
    person = db.query(models.Person).filter(models.Person.user_id == user.id).first()
    if person:
        person.telegram_chat_id = chat_id
    db.commit()


def unbind_chat(db: Session, chat_id: str) -> models.User | None:
    """Отключить напоминания в этот чат. Возвращает пользователя, если он был привязан."""
    chat_id = str(chat_id)
    user = db.query(models.User).filter(models.User.telegram_chat_id == chat_id).first()
    for p in db.query(models.Person).filter(models.Person.telegram_chat_id == chat_id):
        p.telegram_chat_id = None
    if user:
        user.telegram_chat_id = None
    db.commit()
    return user
