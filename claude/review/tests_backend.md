# Тесты по результатам adversarial-ревью бэкенда

Дата: 2026-09-04. Файлы (новые, ничего существующего не менялось):

- `backend/pytest.ini` — настройки pytest (папка `tests`, без кэша).
- `backend/tests/conftest.py` — окружение (sqlite во временной папке, `PRAGMA foreign_keys=ON`, `SCHEDULER_ENABLED=false`,
  каналы уведомлений выключены — сеть не используется), пользователи `jack` (владелец), `nur`, `aida`, помощники.
- `backend/tests/test_adversarial_rest.py` — REST (отчёт `backend_rest.md`).
- `backend/tests/test_adversarial_mcp.py` — MCP `/mcp` и OAuth (отчёт `backend_mcp_sched.md`).
- `backend/tests/test_scheduler.py` — планировщик и уведомления (отчёт `backend_mcp_sched.md`, С6–С8, В6).

Каждый тест `test_<уровень>_*` закрепляет **ожидаемое** поведение из отчёта: пока баг не исправлен, тест падает
с сообщением по-русски, что именно не так; после исправления должен стать зелёным. Тесты `test_ok_*` — регрессия
того, что уже работает (раздел «Что работает корректно» в отчётах): они зелёные сейчас и должны остаться зелёными.

Результат на текущем коде: **86 failed, 26 passed за ~17 с** (86 = подтверждённые баги, 26 = регрессия).

---

## Как запустить (Windows, PowerShell)

```powershell
cd C:\Users\ZhanibekMubinov\Desktop\planner\backend
.\.venv\Scripts\Activate.ps1
```
Ожидается: в начале строки появится `(.venv)`.

```powershell
pip install pytest
```
Ожидается: `Successfully installed pytest-…` (или `Requirement already satisfied`).

```powershell
python -m pytest tests -q
```
Ожидается на текущем коде (до исправлений) последняя строка вида:
```
86 failed, 26 passed in 17.0s
```
Выше неё — список `FAILED tests/…::test_…` и для каждого падения текст `AssertionError: …` по-русски.

После исправления всех багов ожидается:
```
112 passed in …s
```

Полезно:
```powershell
python -m pytest tests -q -k "test_ok_"          # только регрессия — должно быть всё зелёное
python -m pytest tests -q -k "K1 or K2"          # только критичные
python -m pytest tests\test_scheduler.py -q      # один файл
python -m pytest tests -q -x --tb=short -k V1a   # один тест с коротким выводом
```
Тесты не трогают рабочую базу и не ходят в сеть: sqlite создаётся во временной папке, Telegram/Graph отключены.

---

## REST — `tests/test_adversarial_rest.py` (отчёт `backend_rest.md`)

| Тест | Находка | Сейчас |
|---|---|---|
| `test_K1_delegation_task_id_immutable` | К1 — PUT /delegations переносит поручение на любую задачу | FAIL — баг подтверждён |
| `test_K2_default_secrets_rejected_on_startup` | К2 — дефолтные `change-me` / `change-me-too` принимаются | FAIL — баг подтверждён |
| `test_K2_jwt_without_exp_rejected` | К2 (доп.) — JWT без `exp` принимается | FAIL — баг подтверждён |
| `test_V1a_editor_cannot_move_task_to_own_direction` | В1(a) — редактор уводит задачу в своё направление | FAIL — баг подтверждён |
| `test_V1b_editor_cannot_orphan_task` | В1(b) — редактор делает задачу сиротой | FAIL — баг подтверждён |
| `test_V1c_editor_cannot_move_task_to_own_project` | В1(c) — редактор переносит задачу в свой проект | FAIL — баг подтверждён |
| `test_V2_task_created_by_editor_in_shared_direction_visible_to_owner` | В2 — `_owner_for_new`: задача в направлении владельца ему не видна | FAIL — баг подтверждён |
| `test_V2_task_created_by_editor_in_owner_project_visible_to_owner` | В2 — то же для проекта | FAIL — баг подтверждён |
| `test_V3_reminder_task_id_immutable` | В3 — PUT /reminders переносит напоминание на чужую задачу | FAIL — баг подтверждён |
| `test_V3_reminder_fire_at_in_past_rejected[post/put]` | В3/С6 — `fire_at` в прошлом принимается | FAIL — баг подтверждён |
| `test_V4_person_update_by_stranger_forbidden` | В4 — любой правит любого человека | FAIL — баг подтверждён |
| `test_V4_person_delete_by_stranger_forbidden` | В4 — любой удаляет любого человека | FAIL — баг подтверждён |
| `test_V4_person_delete_with_delegations_is_409_not_500` | В4 — удаление человека с поручениями → 500 | FAIL — баг подтверждён |
| `test_V5_editor_cannot_move_project_to_own_direction` | В5 — редактор переносит проект владельца в своё направление | FAIL — баг подтверждён |
| `test_S1_direction_delete_removes_stale_shares` | С1 — висячие шары после удаления направления | FAIL — баг подтверждён |
| `test_S1_stale_share_does_not_grant_access_to_new_entity` | С1 — висячая шара + повтор id даёт доступ к новому направлению | FAIL — баг подтверждён |
| `test_N7_task_delete_removes_stale_shares` | Н7 — висячие шары после удаления задачи | FAIL — баг подтверждён |
| `test_S2_project_move_replaces_direction_on_tasks` | С2 — при переносе проекта задачи сохраняют старое направление | FAIL — баг подтверждён (решение по PROJECT.md) |
| `test_S3_duplicate_tool_ids_not_500[post/put]` | С3 — дубли `tool_ids` → 500 | FAIL — баг подтверждён |
| `test_S4_jwt_bad_sub_is_401_not_500[без sub / sub='abc']` | С4 — JWT без/с нечисловым `sub` → 500 | FAIL — баг подтверждён |
| `test_S5_stale_put_detected` | С5 — lost update, PUT без версии | FAIL — баг подтверждён |
| `test_S6_input_validation[13 вариантов]` | С6 — пустые имена, длина, `color`, `priority`, чеклист | FAIL — баг подтверждён |
| `test_S6_project_validation` | С6 — проект: пустое имя, `color` 101 символ | FAIL — баг подтверждён |
| `test_S6_reminder_channels_empty_rejected` | С6 — `channels: []` | FAIL — баг подтверждён |
| `test_S7_error_response_means_no_change` | С7 — мутация применена, ответ 404 | FAIL — баг подтверждён |
| `test_N1_api_token_constant_time_compare` | Н1 — сравнение `X-API-Token` через `==` | FAIL — баг подтверждён |
| `test_N2_share_email_without_local_part_rejected` | Н2 — приглашение `@cis.kz` | FAIL — баг подтверждён |
| `test_N4_editor_delete_is_403[direction/task]` | Н4 — DELETE редактором → 404 вместо 403 | FAIL — баг подтверждён |
| `test_N6_person_with_other_users_email_not_autolinked` | Н6 — Person с чужой почтой привязывается к аккаунту | FAIL — баг подтверждён |
| `test_S12_notify_run_now_admin_only` | С12 (MCP-отчёт) — `/api/notify/run-now` доступен всем | FAIL — баг подтверждён |
| `test_S12_notify_digest_rate_limited` | С12 (MCP-отчёт) — `/api/notify/digest` без лимита частоты | FAIL — баг подтверждён |
| `test_ok_view_only_user_cannot_write` | «Проверено OK»: view не пишет | PASS — регрессия |
| `test_ok_editor_cannot_manage_shares` | «Проверено OK»: шары — только владелец; валидация шар | PASS — регрессия |
| `test_ok_assignee_can_change_status_and_report_only` | «Проверено OK»: исполнитель | PASS — регрессия |
| `test_ok_project_delete_keeps_tasks_in_direction` | «Проверено OK»: удаление проекта | PASS — регрессия |
| `test_ok_task_delete_cascades` | «Проверено OK»: каскад при удалении задачи | PASS — регрессия |
| `test_ok_direction_delete_nulls_mindmap_direction` | «Проверено OK»: майндмап при удалении направления | PASS — регрессия |
| `test_ok_enum_validation_and_404` | «Проверено OK»: enum → 422, несуществующие id → 404 | PASS — регрессия |
| `test_ok_api_token_auth` | служебный токен | PASS — регрессия |

Не покрыто тестами (нельзя проверить без сети / по коду): Н3 (`ms_oid IS NULL` в callback Microsoft), Н5 (утечка `tools.url` view-пользователю — решение по дизайну), С6 на Postgres (`StringDataRightTruncation`).

## MCP и OAuth — `tests/test_adversarial_mcp.py` (отчёт `backend_mcp_sched.md`)

| Тест | Находка | Сейчас |
|---|---|---|
| `test_K1_token_exchange_requires_client_id_and_redirect_uri` | К1 — обмен кода без `client_id`/`redirect_uri` | FAIL — баг подтверждён |
| `test_K1_consent_page_shows_redirect_host` | К1 — на странице согласия нет хоста `redirect_uri` | FAIL — баг подтверждён |
| `test_K1_consent_bound_to_initiating_browser` | К1 — согласие не привязано к браузеру (нет cookie) | FAIL — баг подтверждён |
| `test_K2_auth_code_single_use_under_parallel_exchange` | К2 — код обменивается несколько раз (гонка `used`) | FAIL — баг подтверждён |
| `test_V1_editor_cannot_add_view_only_direction` | В1 — `update_task add_directions` в view-only направление | FAIL — баг подтверждён |
| `test_V1_editor_cannot_remove_owner_direction` | В1 — `remove_directions` / `project=null` редактором | FAIL — баг подтверждён |
| `test_V1_add_tool_directions_must_be_own_or_editable` | В1 — `add_tool(directions=[view-only])` | FAIL — баг подтверждён |
| `test_V2_create_person_external_email_rejected` | В2 — `create_person` с внешней почтой (рассылка наружу) | FAIL — баг подтверждён |
| `test_V3_oauth_register_capped` | В3 — `/oauth/register` без лимитов | FAIL — баг подтверждён |
| `test_V4_batch_size_limited` | В4 — батч JSON-RPC без ограничений | FAIL — баг подтверждён |
| `test_V5_internal_error_does_not_leak_sql` | В5 — текст SQL с параметрами уходит Claude | FAIL — баг подтверждён |
| `test_S1_exact_name_match_must_not_silently_pick_done_task` | С1 — точное совпадение выбирает выполненную задачу | FAIL — баг подтверждён |
| `test_S2_create_person_prefix_duplicate_rejected` | С2 — «Ержан» при «Ержан Сапаров» | FAIL — баг подтверждён |
| `test_S4_comma_joined_directions_split` | С4 — `directions="A, B"` → одно направление | FAIL — баг подтверждён |
| `test_S4_comma_joined_checklist_items_split` | С4 — `items="a, b, c"` → один пункт | FAIL — баг подтверждён |
| `test_S5_non_integer_limit_is_argument_error[limit=все / due_within_days=неделя / limit=-1]` | С5 — нецелые `limit`/`due_within_days` → «внутренняя ошибка» | FAIL — баг подтверждён |
| `test_S10_create_person_with_other_users_email_not_autolinked` | С10 — `create_person` привязывает к чужому аккаунту | FAIL — баг подтверждён |
| `test_S11_non_object_params_is_jsonrpc_error_not_500[4 варианта]` | С11 — `params`/`name` не-объект → HTTP 500 | FAIL — баг подтверждён |
| `test_N1_numeric_title_falls_back_to_name_search` | Н1 — «2026» трактуется как id | FAIL — баг подтверждён |
| `test_N4_share_access_email_list_rejected` | Н4 — `share_access(email=[...])` (при пустом ALLOWED_EMAIL_DOMAINS) | FAIL — баг подтверждён |
| `test_N7_reminder_in_past_rejected` | Н7 — `add_reminder` с датой в прошлом | FAIL — баг подтверждён |
| `test_N8_bearer_api_token_constant_time` | Н8 — `bearer_user` сравнивает токен через `==` | FAIL — баг подтверждён |
| `test_N9_redirect_uri_validation[4 варианта]` | Н9 — префиксная проверка `redirect_uri` | FAIL — баг подтверждён |
| `test_N9_code_challenge_format_checked` | Н9 — `code_challenge="abc"` принимается | FAIL — баг подтверждён |
| `test_ok_view_only_user_writes_rejected[8 инструментов]` | «Проверено OK»: view-пользователь не пишет | PASS — регрессия |
| `test_ok_ambiguous_match_returns_candidates` | «Проверено OK»: неоднозначность → кандидаты | PASS — регрессия |
| `test_ok_assignee_can_set_status_and_report` | «Проверено OK»: исполнитель | PASS — регрессия |
| `test_ok_mcp_protocol_basics` | «Проверено OK»: 401 + `WWW-Authenticate`, -32601, 202, `arguments` мусором | PASS — регрессия |
| `test_ok_pkce_plain_rejected_and_refresh_rotation` | «Проверено OK»: PKCE plain, ротация refresh | PASS — регрессия |

Не покрыто: В6 частично (см. планировщик), С3 (ё/е и словоформы — UX, критерий «правильно» не задан), С9 (двойная отправка при двух инстансах — нужна вторая копия бэкенда), Н2/Н3/Н5/Н6 (UX-рекомендации без однозначного ожидаемого поведения).

## Планировщик — `tests/test_scheduler.py` (отчёт `backend_mcp_sched.md`)

| Тест | Находка | Сейчас |
|---|---|---|
| `test_S6_reminder_to_assignees_without_delegations_not_retried_forever` | С6 — `recipient=assignees` без поручений ретраится сутки | FAIL — баг подтверждён |
| `test_S6_owner_without_chat_id_is_permanent_failure` | С6 — владелец без chat id ретраится сутки | FAIL — баг подтверждён |
| `test_S7_digest_failure_not_retried_every_minute` | С7 — дайджест при ошибке повторяется каждый тик | FAIL — баг подтверждён |
| `test_S7_digest_only_within_window_after_digest_time` | С7 — дайджест уйдёт в 23:59 после позднего рестарта | FAIL — баг подтверждён |
| `test_S8_exception_in_one_reminder_does_not_abort_others` | С8 — одна битая запись останавливает весь тик | FAIL — баг подтверждён |
| `test_S8_check_reminder_without_channels_not_silently_lost` | С8/С6 — «пора проверить» без каналов тихо теряется | FAIL — баг подтверждён |
| `test_V6_httpx_logger_does_not_print_bot_token` | В6 — токен бота в логе httpx (INFO) | FAIL — баг подтверждён |
| `test_ok_due_reminder_delivered_and_html_escaped` | «Проверено OK»: доставка и `html.escape` | PASS — регрессия |
| `test_ok_future_reminder_not_sent` | напоминание в будущем не уходит | PASS — регрессия |
| `test_ok_assignment_notice_to_assignee_not_to_self` | «вам поручено» исполнителю, не себе | PASS — регрессия |
| `test_ok_check_reminder_sent_once` | «пора проверить» один раз | PASS — регрессия |
| `test_ok_digest_time_rules` | «Проверено OK»: `DIGEST_WEEKDAYS_ONLY`, время дайджеста | PASS — регрессия |
| `test_ok_digest_sent_once_per_day` | дайджест один раз в день | PASS — регрессия |

---

## Как читать падение

Пример:
```
FAILED tests/test_adversarial_rest.py::test_K1_delegation_task_id_immutable
AssertionError: PUT /delegations с чужим task_id должен отклоняться, получено 200
```
Первая строка — какой тест и какая находка (`K1`), вторая — что именно не так. В docstring теста (открыть файл,
найти функцию) — описание бага и ожидаемого поведения по-русски. После исправления кода запустить снова:
падений должно стать меньше, `test_ok_*` — по-прежнему все зелёные.
