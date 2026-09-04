# Юнит-тесты фронтенда (vitest) — сводка

Дата: 2026-09-04. Тесты лежат в `frontend/src/__tests__/`, описывают **ожидаемое** поведение из `review/frontend.md`.
Пока баг не исправлен — тест падает (FAIL = баг подтверждён). Тесты-регрессии фиксируют то, что уже работает (PASS).
После исправления бага соответствующий тест должен стать зелёным — так проверяется правка.

Итог сейчас: **`Tests  13 failed | 35 passed | 1 todo (49)`** — все 13 падений это подтверждённые находки, ошибок импорта/настройки нет.
`npm run build` проходит (тесты исключены из сборки через `tsconfig.json → exclude`).

## Тесты → находка → статус

| Файл теста | Тест | Находка | Статус сейчас |
|---|---|---|---|
| `DirectionPage.contextmenu.test.tsx` | ПКМ на карточке «Без проекта» НЕ открывает меню направления | К1 | **FAIL — баг подтверждён** |
| | ПКМ на строке задачи внутри «Без проекта» НЕ открывает меню направления | С1 | **FAIL — баг подтверждён** |
| | У карточки «Без проекта» есть кнопка действий «⋯» | К1 / С11 | **FAIL — баг подтверждён** |
| | ПКМ на карточке проекта открывает меню проекта, а не направления | регрессия | PASS |
| | Кнопка «⋯» проекта открывает меню проекта | регрессия | PASS |
| | ПКМ на шапке направления открывает меню направления | регрессия | PASS |
| `confirm.test.tsx` | При `danger` в фокусе НЕ красная кнопка (ожидаем фокус на «Отмена») | К2 | **FAIL — баг подтверждён** |
| | Enter сразу после открытия danger-диалога НЕ подтверждает удаление | К2 | **FAIL — баг подтверждён** |
| | Enter при открытом диалоге не долетает до других window-слушателей | С4 / С9 | **FAIL — баг подтверждён** |
| | Повторный `ask()` при открытом диалоге: первый промис резолвится `false`, а не висит | (из раздела «Проверяемые функции») | **FAIL — баг подтверждён** |
| | alertdialog, заголовок «Подтвердите удаление», кнопка «Удалить»; okLabel/title/cancelLabel | регрессия | PASS |
| | OK → true; Отмена → false; Escape → false (и не долетает дальше); фон → false; клик по тексту не закрывает | регрессия | PASS (4 теста) |
| `TaskPanel.autosave.test.tsx` | Закрытие панели раньше 600 мс не теряет правку — PUT уходит с новым названием | В1 | **FAIL — баг подтверждён** |
| | Набор текста во время запроса не откатывается; последний PUT содержит актуальный текст | В2 | **FAIL — баг подтверждён** (поле «прыгает назад» на `…A`, второго PUT нет) |
| | Пауза 600 мс → один PUT `/tasks/100` с новым названием, шапка «сохранено», повторов нет | регрессия | PASS |
| `modals.doublesubmit.test.tsx` | DirectionModal: Enter-Enter в поле названия → ровно один POST `/directions` | С2 | **FAIL — баг подтверждён** (2 POST) |
| | ProjectModal: Enter-Enter → ровно один POST `/projects` | С2 | **FAIL — баг подтверждён** (2 POST) |
| | DirectionModal: двойной клик по «Создать» → один POST (`disabled={busy}` работает) | регрессия | PASS |
| | Один Enter → POST с обрезанным именем, `reloadDirections`, `onSaved`; пустое имя → POST не уходит | регрессия | PASS (2 теста) |
| | ProjectModal: один Enter → POST с `direction_id`, `onSaved` после ответа | регрессия | PASS |
| `pure.test.tsx` | `showDate("2026-09-04")` → «04 сент.» в отрицательном поясе (TZ=America/New_York) | Н6 | **FAIL — баг подтверждён** (даёт «03 сент.») |
| | `buildReport`: `updated_at` в будущем не даёт отрицательный `idleDays` | из раздела «Проверяемые функции» | **FAIL — баг подтверждён** (даёт −1) |
| | `isOverdue`: пусто/прошлое/будущее; граница 23:59:59 / 00:00:00 локально | регрессия | PASS |
| | `toDateTimeInput`/`fromDateTimeInput` round-trip; пустые значения | регрессия | PASS |
| | `canEdit`/`isShared`; `dirColor` (id=0 → первый цвет); `projColor` (запасной `var(--line-strong)`) | регрессия | PASS |
| | `newNodeId`: формат и 10 000 без коллизий | регрессия | PASS |
| | `checklistProgress`: пусто → нули; `[done,done,open]` → 3/2/67; всё → 100 | регрессия | PASS |
| | `buildReport`: нет задач → 45/«нет ни одной задачи»/**fading** (зафиксировано текущее: 45 не < 45) | зафиксировано | PASS |
| | `buildReport`: пауза → ≤15 и только «на паузе»; просрочка по локальному 23:59:59 | регрессия | PASS |
| | `buildReport`: idleDays 0 / 6 (без причины) / 7 и 13 («тихо уже») / 14 («нет движения») | регрессия | PASS |
| | `buildReport`: 5 просрочек → +30, 3 проверки → +20, итог ≤100 и целый, уровень `lost` | регрессия | PASS |
| | `buildReport`: фильтр по направлению, задача в двух направлениях — в обоих; счётчики без NaN | регрессия | PASS |
| | `plural` через шапку DirectionPage: 0/1/2/5/11/21/22 | регрессия | PASS |
| | Проект без задач: доли шкалы `0%`, не `NaN%` | регрессия | PASS |
| | `toIn(task, projectId)` | — | **todo**: функция не экспортирована из `DirectionPage.tsx`/`TaskPanel.tsx`; экспортировать и включить тест |

Замечание по ревью: в разделе «Проверяемые функции» сказано «13 дней → без причины», но код даёт «тихо уже N дн.» уже с 7 дней — тест зафиксирован по коду (6 дней → без причины).

## Что добавлено/изменено в репо

- `frontend/package.json` — dev-зависимости `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`; скрипт `"test": "vitest run"`.
- `frontend/package-lock.json` — обновлён.
- `frontend/vitest.config.ts` — новый (jsdom, globals, setupFiles, `TZ=America/New_York`).
- `frontend/tsconfig.json` — добавлен `exclude` для тестов (чтобы `npm run build` их не собирал).
- `frontend/tsconfig.test.json` — новый, типы для тестов (`npx tsc -p tsconfig.test.json --noEmit`).
- `frontend/src/test-setup.ts` — новый (jest-dom + cleanup).
- `frontend/src/__tests__/` — 5 файлов тестов + `fixtures.ts`.
- Файлы в `src/` (кроме `test-setup.ts` и `__tests__/`) не менялись.

## Команды для владельца (PowerShell, Windows)

Один блок — одно действие.

```powershell
cd C:\Users\ZhanibekMubinov\Desktop\planner\frontend
npm install
```
Ожидаемо: в конце `added N packages` / `up to date`, `found 0 vulnerabilities`. Ошибок нет.

```powershell
cd C:\Users\ZhanibekMubinov\Desktop\planner\frontend
npm test
```
Ожидаемо (пока баги не исправлены), последние строки:
```
 Test Files  5 failed (5)
      Tests  13 failed | 35 passed | 1 todo (49)
```
Каждое падение подписано номером находки (К1, К2, В1, В2, С1, С2, С4/С9, Н6). По мере исправлений число `failed` должно уменьшаться; цель — `Tests  48 passed | 1 todo (49)`.

```powershell
cd C:\Users\ZhanibekMubinov\Desktop\planner\frontend
npm run build
```
Ожидаемо: `✓ built in …s`, затем блок `PWA … files generated`. Тесты в сборку не попадают.

Запустить один файл тестов (например, только К1):
```powershell
cd C:\Users\ZhanibekMubinov\Desktop\planner\frontend
npx vitest run src/__tests__/DirectionPage.contextmenu.test.tsx
```
