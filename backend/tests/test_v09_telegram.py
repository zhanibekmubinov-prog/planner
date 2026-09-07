"""v0.9: бот сам показывает chat id и привязывает его к учётной записи.

Проверяем вебхук (секрет, /start с кодом, /start без кода, /id, /stop, мусор)
и эндпоинт /api/telegram/link для кнопки «Подключить Telegram» в профиле.
"""
import pytest
from sqlalchemy import select

from app import models
from app.config import settings
from app.routers import telegram as tg
from app.telegram_link import make_code
from tests.conftest import ok

SECRET = "webhook-secret-0123456789"


@pytest.fixture(autouse=True)
def bot(monkeypatch):
    """Бот «настроен», но в сеть не ходим: ответы копятся в списке."""
    sent: list[tuple[str, str]] = []

    async def fake_reply(chat_id: str, text: str) -> None:
        sent.append((str(chat_id), text))

    monkeypatch.setattr(tg, "_reply", fake_reply)
    monkeypatch.setattr(settings, "telegram_webhook_secret", SECRET)
    monkeypatch.setattr(settings, "telegram_bot_username", "cisplannerbot")
    return sent


def hook(client, text: str, chat: int = 555, secret: str = SECRET, first: str = "Нурлан"):
    return client.post(
        "/api/telegram/webhook",
        json={"update_id": 1, "message": {"message_id": 1, "chat": {"id": chat, "type": "private"},
                                          "from": {"id": chat, "first_name": first}, "text": text}},
        headers={"X-Telegram-Bot-Api-Secret-Token": secret},
    )


def test_v09_secret_required(client, bot):
    assert hook(client, "/id", secret="wrong").status_code == 403
    assert not bot


def test_v09_no_secret_configured(client, bot, monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", "")
    assert hook(client, "/id").status_code == 503


def test_v09_start_with_code_binds_user(client, db, nur, bot):
    ok(hook(client, f"/start {make_code(nur.id)}", chat=777))
    db.expire_all()
    assert db.get(models.User, nur.id).telegram_chat_id == "777"
    assert "Готово, Нурлан" in bot[-1][1] and bot[-1][0] == "777"


def test_v09_start_with_code_updates_person(client, db, nur, bot):
    person = models.Person(name="Нурлан", email=nur.email, user_id=nur.id)
    db.add(person); db.commit()
    ok(hook(client, f"/start {make_code(nur.id)}", chat=777))
    db.expire_all()
    assert db.get(models.Person, person.id).telegram_chat_id == "777"


def test_v09_one_chat_one_user(client, db, jack, nur, bot):
    """Тот же чат привязали к другому человеку — у первого привязка снимается."""
    ok(hook(client, f"/start {make_code(jack.id)}", chat=777))
    ok(hook(client, f"/start {make_code(nur.id)}", chat=777))
    db.expire_all()
    assert db.get(models.User, jack.id).telegram_chat_id is None
    assert db.get(models.User, nur.id).telegram_chat_id == "777"


def test_v09_bad_code_does_not_bind(client, db, nur, bot):
    ok(hook(client, f"/start {nur.id}-deadbeef00", chat=777))
    db.expire_all()
    assert db.get(models.User, nur.id).telegram_chat_id is None
    assert "устарела" in bot[-1][1] and "777" in bot[-1][1]


def test_v09_code_of_missing_user(client, bot):
    ok(hook(client, f"/start {make_code(90210)}", chat=777))
    assert "устарела" in bot[-1][1]


def test_v09_start_without_code_shows_chat_id(client, bot):
    ok(hook(client, "/start", chat=1234))
    assert "<code>1234</code>" in bot[-1][1] and "Подключить Telegram" in bot[-1][1]


def test_v09_start_when_already_bound(client, db, nur, bot):
    ok(hook(client, f"/start {make_code(nur.id)}", chat=777))
    ok(hook(client, "/start", chat=777))
    assert "уже привязан" in bot[-1][1] and nur.email in bot[-1][1]


def test_v09_id_command(client, db, nur, bot):
    ok(hook(client, "/id", chat=42))
    assert "<code>42</code>" in bot[-1][1] and "не привязан" in bot[-1][1]
    ok(hook(client, f"/start {make_code(nur.id)}", chat=42))
    ok(hook(client, "/id@cisplannerbot", chat=42))          # в группах команда приходит с именем бота
    assert "Привязан к: Нурлан" in bot[-1][1]


def test_v09_stop_unbinds(client, db, nur, bot):
    ok(hook(client, f"/start {make_code(nur.id)}", chat=777))
    ok(hook(client, "/stop", chat=777))
    db.expire_all()
    assert db.get(models.User, nur.id).telegram_chat_id is None
    assert "Отключил" in bot[-1][1]
    ok(hook(client, "/stop", chat=777))
    assert "не был привязан" in bot[-1][1]


def test_v09_any_text_answers_with_help(client, bot):
    ok(hook(client, "привет", chat=9))
    assert "<code>9</code>" in bot[-1][1] and "/stop" in bot[-1][1]


def test_v09_non_message_update_ignored(client, bot):
    r = client.post("/api/telegram/webhook", json={"update_id": 2, "my_chat_member": {}},
                    headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})
    assert ok(r) == {"ok": True} and not bot


def test_v09_link_endpoint(client, nur, bot):
    j = ok(client.get("/api/telegram/link", headers=nur.h))
    assert j["ready"] and j["bot"] == "cisplannerbot"
    assert j["url"] == f"https://t.me/cisplannerbot?start={j['code']}"
    assert j["connected"] is False
    ok(hook(client, f"/start {j['code']}", chat=321))       # код из ссылки действительно работает
    assert ok(client.get("/api/telegram/link", headers=nur.h))["connected"] is True


def test_v09_link_requires_auth(client, bot):
    assert client.get("/api/telegram/link").status_code == 401


def test_v09_link_without_bot_username(client, nur, bot, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_username", "")
    j = ok(client.get("/api/telegram/link", headers=nur.h))
    assert j["ready"] is False and j["url"] is None and "вручную" in j["hint"]


def test_ok_profile_still_accepts_manual_chat_id(client, nur, bot):
    """Регрессия: ручной ввод chat id в профиле никуда не делся."""
    j = ok(client.put("/api/auth/me", json={"name": "Нурлан", "telegram_chat_id": "999", "digest_enabled": True}, headers=nur.h))
    assert j["telegram_chat_id"] == "999"
