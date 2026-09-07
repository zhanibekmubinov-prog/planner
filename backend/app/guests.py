"""Внешние участники (v0.10).

Сотрудники входят через Microsoft. Внешний человек (подрядчик, партнёр) Microsoft-учётки
может не иметь, поэтому для него сделан отдельный вход — по одноразовой ссылке на почту:

1. админ добавляет его в список гостей (`guests`) — это и есть разрешение входить;
2. гость запрашивает ссылку на свою почту (первый вход или «забыл пароль»);
3. ссылка живёт 15 минут и срабатывает один раз; в базе хранится только SHA-256 хеш;
4. по ссылке гость **придумывает пароль** — дальше он входит почтой и паролем (v0.10.1),
   а ссылка нужна только для первого входа и сброса пароля.

Что важно для безопасности:
- войти по ссылке может только адрес из списка гостей; сотрудник @<рабочий домен> — не может
  (у него есть Microsoft, и ослаблять этот путь незачем);
- ответ на запрос ссылки всегда одинаковый, чтобы нельзя было перебором узнать список гостей;
- частота запросов ограничена (на адрес и на IP);
- удаление гостя из списка закрывает доступ немедленно, включая уже открытые сессии:
  `auth.current_user` на каждом запросе проверяет, что гость всё ещё в списке — длина сессии
  на управляемость доступом не влияет;
- права у гостя такие же, как у сотрудника (решение владельца), поэтому единственный контроль —
  список гостей и то, чем с ним поделились;
- пароль хранится как scrypt-хеш с солью (stdlib, без новых зависимостей); подбор ограничен
  (5 неудач на адрес и на IP за 15 минут);
- смена пароля гасит все прежние сессии гостя: сессия старше `password_set_at` не действует.
  Поэтому сброс по почте, если ящик уже чужой, хотя бы выкидывает настоящего владельца — и
  админу уходит уведомление о смене пароля.
"""
import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import models
from .config import settings

TOKEN_TTL = timedelta(minutes=15)
GUEST_SESSION_DAYS = settings.session_days   # как у сотрудников (решение владельца, 2026-09-07): гость не должен
                                             # входить заново каждую неделю. Отзыв доступа мгновенный и от срока
                                             # сессии не зависит — см. auth.current_user.
_RATE_WINDOW = 900              # 15 минут
_RATE_MAX = 3                   # столько запросов ссылки на адрес и на IP в окне
_recent: dict[str, list[float]] = {}


def norm_email(email: str) -> str:
    return (email or "").strip().lower()


def is_work_email(email: str) -> bool:
    """Почта сотрудника — из ALLOWED_EMAIL_DOMAINS. Такой человек входит только через Microsoft."""
    domain = norm_email(email).split("@")[-1]
    return bool(settings.allowed_domains) and domain in settings.allowed_domains


def get_guest(db: Session, email: str) -> models.Guest | None:
    return db.scalar(select(models.Guest).where(models.Guest.email == norm_email(email)))


def is_guest(db: Session, email: str) -> bool:
    return get_guest(db, email) is not None


def email_allowed(db: Session, email: str) -> bool:
    """Можно ли работать с этой почтой: сотрудник или приглашённый гость.

    Используется там, где раньше стояла только проверка домена: «Поделиться», справочник
    «Люди», create_person через Claude.
    """
    email = norm_email(email)
    if not settings.allowed_domains:
        return True
    return is_work_email(email) or is_guest(db, email)


def allowed_hint(db: Session) -> str:
    doms = ", @".join(settings.allowed_domains)
    return f"почта @{doms} или адрес из списка гостей (добавляет администратор)"


# ---------------- одноразовые ссылки ----------------

def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def rate_limited(*keys: str) -> bool:
    """Простой счётчик в памяти процесса: бэкенд один, отдельного хранилища не нужно."""
    now = time.time()
    for k in keys:
        if not k:
            continue
        hits = [t for t in _recent.get(k, []) if now - t < _RATE_WINDOW]
        if len(hits) >= _RATE_MAX:
            _recent[k] = hits
            return True
        hits.append(now)
        _recent[k] = hits
    return False


def create_login_token(db: Session, email: str) -> str:
    """Выдать одноразовый токен. Прежние неиспользованные ссылки этого адреса гасятся."""
    email = norm_email(email)
    db.execute(delete(models.GuestLoginToken).where(models.GuestLoginToken.email == email,
                                                    models.GuestLoginToken.used_at.is_(None)))
    raw = secrets.token_urlsafe(32)
    db.add(models.GuestLoginToken(email=email, token_hash=_hash(raw),
                                  expires_at=datetime.now(timezone.utc) + TOKEN_TTL))
    db.commit()
    return raw


def consume_login_token(db: Session, raw: str) -> str | None:
    """Проверить ссылку и погасить её. Возвращает почту гостя или None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    row = db.scalar(select(models.GuestLoginToken).where(models.GuestLoginToken.token_hash == _hash(raw)))
    if row is None or row.used_at is not None:
        return None
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        return None
    if not is_guest(db, row.email):          # гостя убрали из списка, пока письмо лежало в почте
        return None
    row.used_at = datetime.now(timezone.utc)
    db.commit()
    return row.email


def purge_login_tokens(db: Session, now: datetime | None = None) -> int:
    """Убрать просроченные и использованные ссылки. Зовётся из ежедневной уборки планировщика."""
    now = now or datetime.now(timezone.utc)
    r = db.execute(delete(models.GuestLoginToken).where(
        (models.GuestLoginToken.expires_at < now) | (models.GuestLoginToken.used_at.is_not(None))))
    db.commit()
    return r.rowcount or 0


# ---------------- пароль гостя (v0.10.1) ----------------

MIN_PASSWORD = 10
_WEAK = {"1234567890", "qwertyuiop", "password11", "паролькласс", "planner123", "0123456789"}
_LOGIN_MAX = 5              # неудачных попыток пароля на адрес и на IP за 15 минут


def password_problem(password: str, email: str) -> str | None:
    """Понятная причина отказа или None, если пароль годится."""
    p = (password or "").strip()
    if len(p) < MIN_PASSWORD:
        return f"пароль должен быть не короче {MIN_PASSWORD} символов"
    if p.lower() in _WEAK:
        return "такой пароль слишком простой — придумайте другой"
    if p.lower() == norm_email(email) or p.lower() == norm_email(email).split("@")[0]:
        return "пароль не должен повторять почту"
    if len(set(p)) < 4:
        return "в пароле слишком мало разных символов"
    return None


def hash_password(password: str) -> str:
    """scrypt из стандартной библиотеки: соль на каждый пароль, параметры хранятся рядом."""
    salt = secrets.token_bytes(16)
    n, r, p = 2 ** 14, 8, 1
    dk = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not password:
        return False
    try:
        algo, n, r, p, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                            n=int(n), r=int(r), p=int(p), dklen=len(hash_hex) // 2)
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(dk.hex(), hash_hex)


def login_attempt_blocked(*keys: str) -> bool:
    """Ограничение подбора пароля: 5 неудач на ключ за 15 минут (счётчик в памяти процесса)."""
    now = time.time()
    for k in keys:
        if not k:
            continue
        kk = f"pwd:{k}"
        hits = [t for t in _recent.get(kk, []) if now - t < _RATE_WINDOW]
        _recent[kk] = hits
        if len(hits) >= _LOGIN_MAX:
            return True
    return False


def login_attempt_failed(*keys: str) -> None:
    now = time.time()
    for k in keys:
        if not k:
            continue
        kk = f"pwd:{k}"
        _recent[kk] = [t for t in _recent.get(kk, []) if now - t < _RATE_WINDOW] + [now]


def login_attempt_ok(*keys: str) -> None:
    for k in keys:
        _recent.pop(f"pwd:{k}", None)


def set_password(db: Session, guest: models.Guest, password: str) -> None:
    """Сохранить новый пароль и поднять номер версии — прежние сессии гостя сразу недействительны."""
    guest.password_hash = hash_password(password)
    guest.password_set_at = datetime.now(timezone.utc)
    guest.password_version = int(guest.password_version or 0) + 1
    db.commit()


async def notify_admin_password_change(guest: models.Guest, first: bool) -> None:
    """Сообщить владельцу планнера, что гость задал или сменил пароль.

    Нужно потому, что сброс пароля гость делает сам по письму: если его ящик увели, владелец
    хотя бы увидит смену пароля и сможет закрыть доступ.
    """
    from . import notify
    what = "задал пароль" if first else "сменил пароль"
    text = f"🔑 Гость {guest.name} ({guest.email}) {what} в планнере."
    try:
        if settings.telegram_bot_token and settings.telegram_chat_id:
            await notify.send_telegram(text)
            return
        if settings.graph_ready:
            await notify.send_email("CIS Planner: гость сменил пароль", f"<p>{text}</p>")
    except notify.NotifyError:
        pass          # уведомление — не критично: событие всё равно в логе


def login_email(link: str, name: str) -> tuple[str, str]:
    """Тема и HTML письма со ссылкой входа."""
    subject = "CIS Planner: ссылка для входа и пароля"
    html = (
        f"<p>Здравствуйте, {name}!</p>"
        f"<p>По этой ссылке можно войти в CIS Planner и задать пароль. Она действует 15 минут "
        f"и срабатывает один раз:</p>"
        f'<p><a href="{link}">Открыть планнер и задать пароль</a></p>'
        f"<p>Дальше вход будет обычным: ваша почта и этот пароль.</p>"
        f"<p style=\"color:#666;font-size:13px\">Если вы не запрашивали ссылку, просто удалите письмо. "
        f"Пароль от этого не изменится.</p>"
    )
    return subject, html
