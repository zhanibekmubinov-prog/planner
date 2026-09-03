# LOG — журнал сессий

Формат записи: дата · сессия/инструмент · что сделано · что решено · что осталось. Новые записи — сверху.

---

## 2026-09-03 · сессия 2 · Cowork (desktop)
**Сделано**
- Проверено: `backend` и `frontend` на Railway — SUCCESS. Домен фронта: `https://frontend-production-ed9c.up.railway.app`.
- `CORS_ORIGINS` у backend заменён с `*` на `https://frontend-production-ed9c.up.railway.app,http://localhost:5173` (через Railway MCP, бэкенд переразвёрнут).
- `backend/app/auth.py`: `X-API-Token` стал security-схемой `APIKeyHeader` → в `/docs` кнопка **Authorize**. Проверено TestClient'ом: без токена 401, с токеном 200.
- **Шаг 2 — фронт MVP написан** (референс Huly, ноутбук-first): `index.html` (шрифты IBM Plex Sans/Mono), `src/api.ts`, `store.ts`, `Sidebar.tsx`, `Board.tsx`, `TaskPanel.tsx`, `DirectionModal.tsx`, `Registry.tsx`, `App.tsx`, `styles.css`. Сборка `npm run build` проходит; проверено на sqlite-бэкенде со скриншотами (десктоп 1440, мобильный 390), автосохранение карточки работает.
- Файлы записаны в `frontend/` на компьютере владельца. Владелец коммитит сам (git из среды Claude в этой папке не запускать — оставляет `index.lock`).

- Владелец счёл первую версию UI «сырой и стандартной» (плюс Google Fonts не загрузились → системный шрифт). Сделаны 3 темы на выбор (control / journal / signal) и подборка 8 шрифтов; владелец выбрал **«Инженерный журнал» + Rubik**. Остальные темы удалены из CSS, шрифты зашиты через `@fontsource`. `api.ts` терпит `VITE_API_URL` с `/api` на конце (была ошибка 404 в проде).

**Решения владельца**
- Оформление: тема «Инженерный журнал», шрифт текста Rubik (заголовки Source Serif 4, цифры Source Code Pro).
- UI-референс — Huly: тёмная левая панель направлений, канбан по статусам, карточка задачи в правой панели. Основной экран — ноутбук, телефон — упрощённая версия.
- Перед любой UI-работой — использовать UI-скилы и Uizze и спрашивать референс у владельца.

**Осталось** — владелец: `npm run build` локально, коммит, пуш, проверить фронт на Railway; создать первое направление уже через UI. Далее — шаг 4 (scheduler напоминаний).

---

## 2026-09-02 → 09-03 · сессия 1 · chat (claude.ai)
**Сделано**
- Согласован план из 7 шагов и архитектура (монорепо, фронт/бэк раздельно, Railway ×3 сервиса, PWA-first).
- Сгенерирован каркас: бэкенд (модели, схемы, CRUD-роутеры, auth по токену, Alembic, Dockerfile, railway.json), фронт-заглушка (Vite + React + PWA), docker-compose, README.
- Владелец установил Docker Desktop + WSL 2, поднял локально базу/бэк/фронт, создал репо на GitHub, задеплоил `postgres` и `backend` на Railway.
- Починен фронт-билд: `types: ["vite/client"]`, Node ≥20, убран `npm ci` из buildCommand.
- Заведены `claude/PROJECT.md`, `HANDOFF.md`, `LOG.md`.

**Решения владельца**
- Задачи и тулы — кросс-направленческие (M2M).
- Напоминания: Telegram + email + события в Outlook-календаре.
- Тип тула и `source_ref` закладываем сразу.

**Осталось** — см. HANDOFF.md: дождаться зелёного деплоя фронта, CORS, кнопка Authorize, затем шаг 2 (UI).
