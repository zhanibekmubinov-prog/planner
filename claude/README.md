# Planner — личный таскборд

Монорепо: `backend/` (FastAPI + Postgres), `frontend/` (React + Vite, PWA), `agents/` (позже), `claude/` — заметки для Claude-сессий: **начинать любую сессию с `claude/PROJECT.md` → `HANDOFF.md`, заканчивать записью в `LOG.md` и обновлением `HANDOFF.md`**.

## Локальный запуск (Windows cmd)

**База**
```
docker compose up -d db
```

**Бэкенд** (первый раз)
```
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
alembic revision --autogenerate -m "init"
alembic upgrade head
uvicorn app.main:app --reload
```
Swagger: http://localhost:8000/docs — все запросы с заголовком `X-API-Token` (значение из `.env`).

Дальше при изменении моделей: `alembic revision --autogenerate -m "что изменил"` → `alembic upgrade head`.

**Фронтенд**
```
cd frontend
npm install
copy .env.example .env
npm run dev
```
http://localhost:5173

## Railway

Один проект, три сервиса:

| Сервис | Источник | Root Directory | Переменные |
|---|---|---|---|
| `postgres` | плагин Railway | — | — |
| `backend` | этот репо | `backend` | `DATABASE_URL=${{Postgres.DATABASE_URL}}` (заменить `postgresql://` на `postgresql+psycopg://`), `API_TOKEN`, `CORS_ORIGINS=https://<frontend-домен>` |
| `frontend` | этот репо | `frontend` | `VITE_API_URL=https://<backend-домен>/api`, `VITE_API_TOKEN` (тот же) |

Миграции применяются автоматически при старте бэкенда (`alembic upgrade head` в Dockerfile CMD).

## Модель

- **Direction** — направление развития.
- **Task** ↔ Direction: many-to-many (кросс-направленческие задачи).
- **Tool** ↔ Task / Direction: many-to-many; `type` + `source_ref` (JSON) — точка входа для агентов.
- **Person / Delegation** — кому поручено, когда контроль.
- **Reminder** — несколько на задачу, каналы `telegram | email | outlook_calendar`; `Task.outlook_event_id` — чтобы обновлять событие, а не дублировать.
- **ActivityLog** — сырьё для health-score направлений и отчётов агентов.
