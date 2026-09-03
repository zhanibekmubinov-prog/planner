# Planner — контекст проекта для Claude-сессий

**Читать первым в любой сессии.** Затем `HANDOFF.md` (что делать сейчас), затем последние записи `LOG.md`.

## Что это
Личный планнер-таскборд Jack'а (Zhanibek). Направления развития → задачи → делегирование людям → вспомогательные тулы (таблицы/боты) → позже агенты контроля и напоминаний. Один пользователь, без регистрации.

Репо: `zhanibekmubinov-prog/planner`. Локально: `C:\Users\ZhanibekMubinov\Desktop\planner`.

## Архитектура
- Монорепо: `backend/` (FastAPI + SQLAlchemy 2 + Alembic + Postgres), `frontend/` (React 18 + Vite + TS, PWA), `agents/` (пусто, шаг 4+), `claude/` (эти заметки).
- Фронт ↔ бэк только через REST `/api/*`. Мобильное приложение позже станет вторым клиентом того же API.
- Railway, один проект, три сервиса: `postgres`, `backend` (Dockerfile, root `backend`), `frontend` (Nixpacks, root `frontend`, `serve -s dist`).
- Авторизация: заголовок `X-API-Token` = env `API_TOKEN`. Один токен на бэке и фронте.
- Миграции применяются при старте бэкенда (`alembic upgrade head` в Dockerfile CMD).

## Модель данных (решения владельца, 2026-09-02)
- Task ↔ Direction — many-to-many (`task_directions`): задачи кросс-направленческие.
- Tool ↔ Task и Tool ↔ Direction — many-to-many (`tool_tasks`, `tool_directions`).
- `Tool.type` enum: `google_sheet | excel_sharepoint | telegram_bot | notion | other`; `Tool.source_ref` JSON (`spreadsheet_id`, `drive_id`/`item_id`, `bot_username`) — точка входа для агентов.
- `Reminder` — отдельная таблица, несколько на задачу; `channels` JSON из `telegram | email | outlook_calendar`.
- `Task.outlook_event_id` — чтобы обновлять событие в Outlook, а не дублировать.
- `ActivityLog` пишется на create и смену статуса — сырьё для health-score направлений.
- Люди: `Person` (имя, telegram_chat_id, email); `Delegation` (task, person, check_at, status).

## Дорожная карта
0. ✅ Каркас (бэк, фронт-заглушка, compose, Railway).
1. ✅ Бэкенд MVP (CRUD всех сущностей).
2. ⏳ Фронт MVP: направления → канбан задач → карточка задачи (делегирование, тулы, напоминания).
3. ⏳ Деплой фронта (в процессе, см. HANDOFF).
4. Scheduler напоминаний (Telegram, email, Outlook-календарь через Microsoft Graph).
5. Health-score направлений + дашборд «что проседает».
6. ИИ-агенты контроля тулов (читают `source_ref`, пишут отчёты). Возможно, MCP-сервер как у Cis-Platform.
7. Мобильное приложение (Expo) либо остаёмся на PWA.

## Правила работы в этом проекте
- Ответы по-русски. Владелец — не разработчик: команды давать готовыми к копированию, по блокам, с ожидаемым результатом.
- Терминал владельца — **PowerShell**, не cmd: `.\.venv\Scripts\Activate.ps1`, пути абсолютные (`C:\Users\ZhanibekMubinov\...`), без `%VAR%`.
- Изменения файлов отдавать либо готовыми файлами на замену, либо одной точной правкой с указанием строки. Не давать длинные diff'ы.
- Локальная проверка перед пушем: бэк — `uvicorn` + `/docs`; фронт — обязательно `npm run build` (dev не проверяет типы!).
- Модели меняем → `alembic revision --autogenerate -m "..."` → `alembic upgrade head` → миграцию коммитим.
- **Каждая сессия обязана** перед завершением: (1) добавить запись в `LOG.md`, (2) обновить `HANDOFF.md` — статус и следующий шаг. Без этого следующая сессия не знает, где мы. Это часть задачи, а не опция.
- Решения владельца (модель, приоритеты, UX) фиксировать в этом файле в разделе «Модель данных» или новом разделе «Решения».
