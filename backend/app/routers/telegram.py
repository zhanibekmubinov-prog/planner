"""Бот планнера отвечает пользователю (v0.9).

Telegram присылает сообщения на вебхук `POST /api/telegram/webhook`; проверяем
секрет из заголовка `X-Telegram-Bot-Api-Secret-Token` (его задаёт setWebhook).

Команды:
  /start <код>  — привязать этот чат к учётной записи (код из профиля планнера)
  /start        — показать chat id и объяснить, что делать
  /id           — показать chat id
  /stop         — больше не присылать напоминания в этот чат
  /help         — короткая справка

Настройка одним запросом в браузере (см. docs/TELEGRAM.md):
  https://api.telegram.org/bot<ТОКЕН>/setWebhook?url=<БЭКЕНД>/api/telegram/webhook&secret_token=<СЕКРЕТ>
"""
import logging
import secrets as _secrets

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .. import models
from ..auth import current_user
from ..config import settings
from ..db import get_db
from ..telegram_link import bind_chat, make_code, resolve_code, unbind_chat

router = APIRouter(prefix="/telegram", tags=["telegram"])
_log = logging.getLogger("telegram")

HELP = (
    "Я бот планнера CIS. Присылаю напоминания, поручения и утреннюю сводку.\n\n"
    "<b>/id</b> — показать ваш chat id\n"
    "<b>/stop</b> — не присылать напоминания в этот чат\n"
    "<b>/help</b> — эта справка\n\n"
    "Задачи ставятся в планнере или голосом через Claude — сюда писать команды не нужно."
)

# Меню команд (синяя кнопка «Меню» в Telegram). Ставится само при старте бэкенда — в BotFather вручную ничего вбивать не нужно.
COMMANDS = [
    {"command": "start", "description": "подключить этот чат к планнеру"},
    {"command": "id", "description": "показать мой chat id"},
    {"command": "stop", "description": "не присылать напоминания сюда"},
    {"command": "help", "description": "что умеет бот"},
]


async def sync_commands() -> None:
    """Отправить меню команд в Telegram. Без токена бота (локально, тесты) — тихо ничего не делает."""
    if not settings.telegram_bot_token:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/setMyCommands"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(url, json={"commands": COMMANDS})
        if r.status_code >= 300:
            _log.warning("setMyCommands %s: %s", r.status_code, r.text[:200])
        else:
            _log.info("telegram: меню команд обновлено (%d команд)", len(COMMANDS))
    except httpx.HTTPError as e:
        _log.warning("setMyCommands: %s", e)


async def _reply(chat_id: str, text: str) -> None:
    """Ответ в чат. Без токена бота (локально и в тестах) молча ничего не делает."""
    if not settings.telegram_bot_token:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                        "disable_web_page_preview": True})
        if r.status_code >= 300:
            _log.warning("sendMessage %s: %s", r.status_code, r.text[:200])
    except httpx.HTTPError as e:                      # сеть моргнула — Telegram повторит апдейт сам
        _log.warning("sendMessage: %s", e)


def _front(path: str = "") -> str:
    return (settings.frontend_url or "").rstrip("/") + path


@router.get("/link")
def link(user: models.User = Depends(current_user)):
    """Ссылка «Подключить Telegram» для профиля: t.me/<бот>?start=<код>."""
    if not settings.telegram_bot_username:
        return {"ready": False, "bot": None, "code": None, "url": None,
                "hint": "На сервере не задан TELEGRAM_BOT_USERNAME — впишите chat id вручную."}
    code = make_code(user.id)
    bot = settings.telegram_bot_username.lstrip("@")
    return {"ready": True, "bot": bot, "code": code, "url": f"https://t.me/{bot}?start={code}",
            "connected": bool(user.telegram_chat_id)}


@router.post("/webhook", include_in_schema=False)
async def webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(None),
    db: Session = Depends(get_db),
):
    if not settings.telegram_webhook_secret:
        raise HTTPException(503, "вебхук не настроен: задайте TELEGRAM_WEBHOOK_SECRET")
    got = (x_telegram_bot_api_secret_token or "").encode()
    if not _secrets.compare_digest(got, settings.telegram_webhook_secret.encode()):
        raise HTTPException(403, "bad secret")

    try:
        update = await request.json()
    except ValueError:
        return {"ok": True}
    msg = update.get("message") or update.get("edited_message") or {}
    chat = str((msg.get("chat") or {}).get("id") or "")
    text = (msg.get("text") or "").strip()
    if not chat:
        return {"ok": True}                            # не сообщение (нажатие кнопки, вход в канал и т.п.)

    first = (msg.get("from") or {}).get("first_name") or ""
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()                    # в группах команды приходят как /id@cisplannerbot
    arg = arg.strip()

    try:
        if cmd == "/start" and arg:
            user = resolve_code(db, arg)
            if user is None:
                await _reply(chat, "Ссылка устарела или неверная. Откройте профиль в планнере и нажмите "
                                   "«Подключить Telegram» ещё раз.\n\n"
                                   f"Ваш chat id: <code>{chat}</code>")
            else:
                bind_chat(db, user, chat)
                await _reply(chat, f"Готово, {user.name}! Напоминания, поручения и утренняя сводка будут приходить сюда.\n\n"
                                   f"Ваш chat id: <code>{chat}</code>\nОтключить — /stop")
                _log.info("telegram: chat %s привязан к %s", chat, user.email)
        elif cmd == "/start":
            u = db.query(models.User).filter(models.User.telegram_chat_id == chat).first()
            if u:
                await _reply(chat, f"Этот чат уже привязан к {u.name} ({u.email}).\n\n"
                                   f"Ваш chat id: <code>{chat}</code>\n{HELP}")
            else:
                link_hint = f"\n\nПланнер: {_front()}" if settings.frontend_url else ""
                await _reply(chat, f"Здравствуйте{', ' + first if first else ''}!\n\n"
                                   f"Ваш chat id: <code>{chat}</code>\n\n"
                                   "Чтобы напоминания приходили сюда, откройте профиль в планнере "
                                   "(ваше имя в правом верхнем углу) и нажмите «Подключить Telegram» — "
                                   "я привяжу чат сам. Либо вставьте этот chat id в поле профиля вручную."
                                   + link_hint)
        elif cmd in ("/id", "/myid", "/chatid"):
            u = db.query(models.User).filter(models.User.telegram_chat_id == chat).first()
            who = f"\nПривязан к: {u.name} ({u.email})" if u else "\nК учётной записи пока не привязан."
            await _reply(chat, f"Ваш chat id: <code>{chat}</code>{who}")
        elif cmd == "/stop":
            u = unbind_chat(db, chat)
            await _reply(chat, "Отключил: напоминания в этот чат больше не приду́т. Включить снова — "
                               "кнопка «Подключить Telegram» в профиле." if u else
                               "Этот чат и не был привязан — напоминания сюда не приходят.")
        elif cmd == "/help":
            await _reply(chat, HELP)
        else:
            await _reply(chat, f"Ваш chat id: <code>{chat}</code>\n\n{HELP}")
    except Exception:                                  # не роняем вебхук: иначе Telegram будет повторять апдейт
        _log.exception("telegram webhook: chat=%s text=%r", chat, text[:80])
    return {"ok": True}
