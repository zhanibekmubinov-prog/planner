# HANDOFF — текущее состояние и следующий шаг

_Обновлено: 2026-09-04, сессия 7 (Cowork) — адверсариальное ревью и тесты, код не менялся. Версия v0.7 — чеклист в задаче + перенос задач между проектами перетаскиванием; v0.6.1 — понятные ошибки MCP (v0.6: проекты, совместный доступ; v0.5: MCP-коннектор)._

## Состояние
| Что | Статус |
|---|---|
| Railway `postgres` | ✅ |
| Railway `backend` | ✅ https://backend-production-830f1.up.railway.app — `/health` ok, `/docs` с кнопкой Authorize |
| Railway `frontend` | ✅ https://cis-planner.up.railway.app — деплой зелёный |
| `CORS_ORIGINS` у backend | ✅ `https://cis-planner.up.railway.app,http://localhost:5173` |
| Переменные frontend `VITE_API_URL`, `VITE_API_TOKEN` | ✅ заданы |
| Шаг 2 — фронт MVP | ✅ v0.2 в проде; тема «Инженерный журнал» (бумага, Source Serif 4 заголовки, Rubik текст, Source Code Pro цифры), шрифты через `@fontsource` |
| Шаг 4 — планировщик напоминаний | ✅ `backend/app/scheduler.py` (цикл раз в 60 с внутри бэкенда), `notify.py` (Telegram Bot API; Microsoft Graph: sendMail + события календаря), `routers/notify.py` (`GET /api/notify/status`, `POST /api/notify/test {channel}`, `POST /api/notify/run-now`, `POST /api/notify/digest`) |
| Напоминания по поручениям | ✅ `Delegation.notified_at` (миграция `b7c1d2e3f4a5`), `scheduler.process_delegations` — «Пора проверить у X» владельцу |
| Утренняя сводка | ✅ `digest.py` + `scheduler.send_digest`; ежедневно в `DIGEST_TIME` (08:30 Asia/Oral) по `DIGEST_CHANNELS` |
| v0.3 Многопользовательский режим | ✅ `users` + `owner_id`, вход через Microsoft (`routers/auth.py`), JWT, видимость «своё + порученное», раздел «Мне поручено», профиль |
| Майндмапы | ✅ модель `MindMap` (миграция `c8d2e3f4a5b6`), роутер `/api/mindmaps`, редактор MindNode-стиля (`MindMapEditor.tsx`) |
| v0.4 | ✅ `Reminder.recipient` (миграция `e0f4a5b6c7d8`), сайдбар с разделами и списком направлений, `DirectionMenu.tsx`, страницы-списки по центру |
| v0.5 MCP-коннектор для Claude | ✅ в проде, владелец и коллеги подключены. `routers/mcp_oauth.py`, `routers/mcp.py`, `mcp_tools.py` (25 инструментов), миграция `f1a5b6c7d8e9`, `docs/MCP_CONNECTOR.md`, `test_mcp.py` |
| v0.6 Проекты + совместный доступ | ✅ закоммичено (`d78411e`), задеплоено; миграция `a2b3c4d5e6f7` (projects, shares, tasks.project_id). Проверка в проде с коллегой — частично (Нурлан 04.09 создал через Claude ~30 задач) |
| v0.6.1 Понятные ошибки MCP | ✅ в git (`df6895b`) |
| v0.7 Чеклист + перенос задач между проектами | ✅ в git (`cbbea7f`); в проде проверить `alembic current` = `b3c4d5e6f7a8` |
| **Адверсариальное ревью (сессия 7)** | ✅ `claude/REVIEW-2026-09-04.md` (сводка + план по фазам), `claude/review/*.md` (подробности). Тесты: `backend/tests/` (pytest, `86 failed, 26 passed`), `frontend/src/__tests__/` (vitest, `13 failed, 35 passed`). Падающий тест = подтверждённый баг. **Ждёт коммита; починка — следующие сессии** |
| Вход коллег в Entra | ✅ «Требуется назначение?» = Нет — входит любой @cis.kz |
| Каналы в проде | ✅ Telegram, email и календарь Outlook через Graph проверены. Секрет Graph был вставлен в чат — стоит перевыпустить. |

## Следующий шаг (по порядку)
0. **Владелец:** закоммитить тесты и отчёт (`git add . / commit -m "review: адверсариальное ревью, pytest + vitest" / push`). Проверить, что `pytest`/`npm test` запускаются локально (команды — в конце `REVIEW-2026-09-04.md`).
1. **Владелец — ответить на 5 вопросов** из раздела «Решения, которые нужны от владельца» в `REVIEW-2026-09-04.md`: сироты при удалении направления; перенос проекта между направлениями; права на справочник людей; раздел «Архив»; soft-delete.
2. **Сессия починки, фаза 1 (UI, потеря данных одним движением):** F-К1 меню «Без проекта» + ПКМ только на шапке; F-К2 confirm (фокус на «Отмена», ввод названия для непустых, заголовок по типу сущности, глушить Enter для других слушателей); F-В1/В2 автосейв (flush при закрытии + счётчик ревизий); F-В3 плашка «Обновить» вместо автоперезагрузки; F-В4/В5 раздел «Архив» + мягкий confirm; F-С2 `if (busy) return`; F-С3, F-С6/С7. После каждой правки — `npm test` (падений должно становиться меньше, регрессия зелёная) и `npm run build`.
3. **Фаза 2 (безопасность/права, бэкенд):** B-К2 секреты обязательны; B-К1 `task_id` неизменяем в PUT поручения/напоминания; M-К1/К2 OAuth (cookie-привязка consent, хост redirect на странице, `client_id`+`redirect_uri` в `/oauth/token`, атомарный `used`); B-В1/В2/В5 + M-В1 единая правка `_apply`/`_owner_for_new`/`projects.update` и `_editable` в MCP; B-В4; M-В2/С10; M-В3…В6; M-С12. После — `python -m pytest tests -q`.
4. Фазы 3–6 по REVIEW (валидация и `shares`, планировщик, разрешение имён в MCP, мелкий UX).
5. Потом — прежние планы: проверка v0.7 в проде, роли «руководитель/команда», агенты тулов; перевыпустить client secret в Entra.

## Тесты (для следующей сессии)
- Бэкенд: `backend/tests/conftest.py` — sqlite во временной папке, `PRAGMA foreign_keys=ON`, фикстуры `client`, `jack` (владелец, `X-API-Token` и Bearer MCP), `nur`, `aida`, помощник `api`. Имена `test_<Уровень><№>_*` соответствуют находкам в `claude/review/backend_*.md`; `test_ok_*` — регрессия. Запуск из `backend/` в venv: `python -m pytest tests -q` (`-k K1`, `-k test_ok_`, `-x --tb=short`).
- Фронт: `frontend/vitest.config.ts` (jsdom, `TZ=America/New_York`, чтобы ловить ошибки пояса), `tsconfig.test.json`; тесты в `src/__tests__/`, фикстуры стора — `fixtures.ts`. `npm test`; один файл — `npx vitest run src/__tests__/confirm.test.tsx`. `toIn` не экспортирован — тест `it.todo`.
- В среде Claude: `pip install -r requirements.txt pytest`, `npm ci`; оба прогона < 30 с.

## Что в UI (v0.2–v0.6)
- **Правило владельца: никаких системных окон браузера** (`window.prompt/confirm/alert`). Создание задачи — поле прямо в колонке (Enter добавляет, Esc закрывает); подтверждения — свой диалог `confirm.tsx` (`useConfirm()` через `ConfirmProvider` в `main.tsx`).
- Доска вписывается в ширину экрана: `grid-template-columns: repeat(var(--cols), minmax(0,1fr))`; на телефоне — горизонтальная прокрутка.
- Кнопки: акцентная (`.btn.primary`) — ржавая, у всех кнопок/чипов/карточек есть hover-реакция; `prefers-reduced-motion` учитывается. Кнопки «+» круглые залитые акцентные.
- **Карта направлений** (`Overview.tsx`, стартовый экран): карточка на каждое направление — шкала внимания («долг внимания» 0–100 → В фокусе / Норма / Ослабло / Упущено), причины, полоса состава задач, счётчики, последнее движение, топ-5 открытых задач. Формула — в `buildReport()`; на бэкенде — `digest.py` (`build_report`). Менять синхронно.
- Сериф (Source Serif 4) — на названиях задач, людей, тулов и заголовках; Rubik — контролы и текст. Оформление: `styles.css` — базовые правила + блок `[data-theme="journal"]`.
- Левая панель (v0.4–v0.6): сверху разделы — Карта направлений, Мне поручено, Общие, Все задачи, Майндмапы, Люди, Тулы; ниже группа «Направления» (сворачивается, фильтр при >8), направления раскрываются в проекты, «+ проект», пометка ⇄ у открытого мне. Правая кнопка / «⋯» на направлении и проекте — меню действий (`DirectionMenu.tsx`, `ProjectMenu.tsx`).
- Клик по направлению → карта проектов (`DirectionPage.tsx`) + блок «Без проекта»; клик по проекту → канбан проекта. Шапка доски — крошки «Направление › Проект», фильтры статусов — вкладки с подчёркиванием.
- Доска: 4 колонки по статусу, drag-and-drop, «+» в колонке создаёт задачу сразу в этом статусе.
- Карточка задачи — **модальное окно по центру** (`.task-modal`, две колонки; Esc / клик мимо — закрыть; на телефоне — на весь экран). Автосохранение через 0.6 с. Поле «Проект» (выбор проекта сам добавляет его направление). При `view` — только-просмотр (`fieldset disabled`, жёлтая шапка). Кнопка ⇄ Поделиться.
- Направление: модалка (название, цель, описание, цвет из палитры, статус). Люди и тулы — таблицы с редактированием. Страницы-списки — колонка по центру ≤1080px.
- `ShareModal.tsx` — почта с подсказками из `/shares/people`, право Смотреть/Редактировать, список и отзыв. `SharedPage.tsx` — раздел «Общие».

## MCP-коннектор (для следующей сессии)
- Схема как в CIS Platform. Claude регистрируется сам (`/oauth/register`), `/oauth/authorize` создаёт `McpPendingAuth` и уводит в Entra со state `mcp:<key>`; `/api/auth/callback` при таком state записывает `user_id` в pending и редиректит на `/oauth/consent?k=`; «Разрешить» → `McpAuthCode` → `/oauth/token` (PKCE) → `McpToken` (хеши). Refresh ротируется.
- Инструменты — `mcp_tools.TOOLS` (name, description, inputSchema, handler). Добавить инструмент = функция `t_<имя>(db, user, args)` + запись в `TOOLS`. Сущности резолвятся `_match()` по id/названию/части/словам. Записи через Claude помечены в `activity_log` `{"via": "mcp"}`.
- **Ошибки (v0.6.1):** `ToolError(message, hint)` → Claude получает `isError` с `{"error", "hint"}`. Подсказки «не найдено» по типу сущности — словарь `_MISSING_HINT`; неоднозначность — «уточните у человека»; дубликат проекта — «используйте существующий»; внутренние сбои — traceback в лог + hint «сообщите человеку». Инструкции сервера (`instructions_for`) велят следовать hint и соблюдать порядок направление → проект → задача.
- **Терпимость к формату (v0.6.1):** `_list(a, key)` — строка вместо массива → `[строка]` (`directions`, `assign_to`, `people`, `add/remove_directions`, `tasks`, `channels`); `arguments` JSON-строкой разбираются; каналы `calendar/outlook/mail/почта/tg` нормализуются. `create_task` понимает `create_direction_if_missing`, `create_project_if_missing` (ровно одно направление), `create_person_if_missing`.
- **Логи:** `INFO mcp: mcp tools/call <tool> by <email> -> ok|error` (роутер) + `WARNING mcp: <tool> by <email>: <текст> | args={…}` (mcp_tools). В Railway фильтр `WARNING mcp`. За 03–04.09 было 125 вызовов, 4 ошибки.
- Права: владелец задачи — всё; исполнитель — `set_task_status` и `update_delegation` (status/report) по своим поручениям; `list_tasks scope=assigned_to_me` — «мне поручено». Удаления нет намеренно. Майндмапы через MCP пока не выведены.
- Инструменты чеклиста (v0.7): `add_checklist_items(task, items[])`, `check_item(task, item, done)`.
- Идея (владелец, 2026-09-03): роли/видимость для руководителей — отдельное решение по модели прав, не начато.
- Проверка: `python test_mcp.py` и `python test_v06.py` из `backend/` (sqlite, без сети).

## Чеклист и перенос задач (v0.7, для следующей сессии)
- `Task.checklist` — JSON-список `{id, text, done}`; id генерируется на клиенте (`newNodeId()`), на бэкенде в MCP — `secrets.token_hex(4)`. Порядок пунктов — порядок в списке; перестановка пунктов пока не сделана (идея).
- Правка чеклиста идёт тем же `PUT /tasks/{id}` (поле `checklist` в `TaskIn`) — через автосейв карточки. Исполнитель (`assignee`) чеклист в UI не правит (режим только-просмотр); через MCP `check_item` ему разрешён.
- Меняя JSON-колонку на бэкенде — всегда присваивать новый список (не мутировать словари внутри), иначе SQLAlchemy не запишет UPDATE.
- Перенос задачи между проектами: `DirectionPage.moveTask` → `PUT /tasks/{id}` с полной карточкой (`toIn`) и новым `project_id`; `tasks._apply` добавляет направление проекта. Drop-цели — `DropCard` (проекты с правом edit и «Без проекта»); `dataTransfer` тип `text/task-id` — тот же, что на доске.
- Идеи от коллег: перетаскивание задач в проекты из сайдбара; перестановка пунктов чеклиста; превращение пункта в задачу.

## Проекты и совместный доступ
- При выдаче доступа получателю уходит «⇄ Вам открыли …» (`routers/shares.py: share_notice / notify_share`) — Telegram, если есть chat id, иначе письмо.
- Права считаются в `backend/app/scope.py`: `Grants(db, user)`; `task_access` → owner | edit | view | assignee | None; контейнеры могут быть `via`. Фронт получает `access` в каждом объекте (`canEdit()` в `api.ts`).
- Задача, созданная редактором в чужом направлении/проекте, принадлежит владельцу направления (`tasks._owner_for_new`). Напоминания и поручения — owner/edit; удаление и шаринг — только owner.
- `store.tasks` (доска) = мои + открытые мне (+ порученные мне в открытом мне контейнере); `store.inbox` = порученные мне чужие.
- Стенд для скриншотов: `cd backend && python _serve_ui.py 8000` (sqlite с демо-данными, фронт из `frontend/dist`) → `python _shots.py`. В git не нужны.
- Миграцию на sqlite целиком не прогнать (init-миграция Postgres-специфична) — только `alembic upgrade head` у владельца на Docker-Postgres.

## Многопользовательский режим
- Служебный `X-API-Token` = владелец (`OWNER_EMAIL`). Пользовательские сессии — JWT HS256 (`SESSION_SECRET`, 30 дней) в `localStorage['planner.session']`; 401 → экран входа.
- `Person` — общий справочник; при входе запись `Person` с его почтой связывается (`user_id`) или создаётся. Удалять людей с `user_id` нельзя.
- Каналы: Telegram — `User.telegram_chat_id`, почта — `User.email`; календарь — в ящик владельца задачи. Уведомление «Вам поручено» уходит исполнителю один раз (`assigned_notified_at`).

## Майндмапы
- `MindMap.data = {id:"root", text, children:[{id, text, children, collapsed?}]}`; раскладка на фронте (`layout()` в `MindMapEditor.tsx`).
- У направления кнопка: 0 карт → создаёт; 1 → открывает; >1 → список. У задачи — раздел в окне задачи.
- Идеи: перетаскивание узлов между ветками, заметки/ссылки на узле, экспорт в PNG, узел → задача.

## Как устроены напоминания
- Поручения: `Delegation.notified_at IS NULL AND check_at <= now AND status=open` → сообщение владельцу → `notified_at`. Лог `Delegation/check_reminder`.
- Сводка: `digest_due()` — время ≥ `DIGEST_TIME` по `APP_TIMEZONE` и сегодня ещё не было `Digest/sent`. Ручная — `sent_manual`.
- `Reminder.recipient`: `owner` / `assignees` / `both`. `Reminder.sent_at IS NULL AND fire_at <= now` → `deliver()`; при успехе `sent_at`; >24 ч неудач — `gave_up`. Результаты — в `activity_log`.
- `outlook_calendar`: событие 30 мин, id в `Task.outlook_event_id`, повтор — PATCH. Сообщение содержит ссылку `FRONTEND_URL/?task=ID`.

## Правила работы в папке владельца (Cowork)
- Файлы записывать напрямую через device bridge — но **git не запускать вообще** (даже `git status`/`diff` оставляют `.git/index.lock`, который потом блокирует коммит владельца). Если всё же появился — удалить `.git/index.lock` (в PowerShell: `Remove-Item .git\index.lock`).
- Python-зависимости в локальной VM Cowork ставятся `pip install -r requirements.txt`; тесты гонять на копии в `$HOME`, не в папке владельца.

## Известные шероховатости
- Тесты бэкенда (REST) не написаны — есть только `test_mcp.py` / `test_v06.py`.
- В `agents/` только README.
