# Алгоритм: маршрутизация запроса чата (ProfileResolver + agent-router)

Как ЛЕС выбирает, ЧЕМ отвечать на запрос. Канон текущей механики (сверено с кодом 2026-06-27).
История решения «инвертировать детерминизм» — в [AUDIT_DETERMINISM.md](AUDIT_DETERMINISM.md) (исполнено).

## Принцип: видимый ответ принадлежит модели

Обычный текстовый запрос не может завершиться готовым ответом regex/SQL/Python-обработчика.
Модель сама выбирает read-only инструменты в evidence-loop; код ищет, читает, считает,
валидирует и возвращает ей результаты. Видимый содержательный ответ формулирует модель.
Явные slash-команды остаются control-plane действиями и не считаются экспертным ответом.

```
запрос → runtime_admission (очередь/режим)
       → ProfileResolver.resolve() → Profile
       → retrieval / exact readers / typed context
       → model-owned research loop выбирает read-only tools
       → результаты инструментов возвращаются модели как evidence
       → модель формулирует ответ
       → validation + sources + trace + history
```

## Сбой выбора инструмента

Сбой tool-selector не включает старый каскад кодовых автоответов. Ошибка остаётся в
`retrieval_trace`, после чего основной модельный вызов работает с уже доступным evidence.
Если обязательного evidence нет, модель получает честный `MISSING/BLOCKED`; код не сочиняет
заменяющий ответ.

## ProfileResolver — единый контракт

`proxy/services/profile_resolver.py`: `resolve()` → `Profile` (dataclass), `refine()`, `as_trace()`;
реестр `PROFILES`, `MODE_TO_PROFILE`. Резолвер отвечает только за маршрут и policy/output
contract. Он **не хранит и не применяет allowlist инструментов**: factory allowlist строит
`chat_profile_service` из живого `ToolHarness` registry, активная редакция фиксируется в
immutable `chat_profile_snapshot`, а `chat_evidence_application_service` применяет её при
shortlist и исполнении. Trace явно сообщает `tool_policy_source=chat_profile_snapshot`.

Режим-чип GUI → профиль:

| Режим (чип) | Профиль | Контур |
|---|---|---|
| Сметы | `estimator` | общий model-owned evidence/tool loop; точный набор инструментов задаёт snapshot профиля |
| Инженер | `engineer` | модель формулирует вывод по RAG/tool evidence |
| Поиск | `search` | RAG с цитатами и source readers |
| Агент (default) | `agent` | универсальный model-owned loop; factory snapshot включает зарегистрированные tools |

`query_route.profile` несёт честный `route_source` + `channel` в trace каждого ответа.

После выполнения ответа `answer_contract_service.decorate_payload()` добавляет общий
`workflow_plan_v1` (`workflow_plan_service`): какой workflow фактически прошёл, какие входы нужны,
чего не хватило, сколько claims/evidence собрано, есть ли blockers и какие next actions нужны.
`ProfileResolver` не исполняет задачу; `workflow_plan` не выбирает маршрут. Первый отвечает на
«куда пошли», второй — «что получилось и насколько это финально».

## Где в коде

- Резолвер профиля: `proxy/services/profile_resolver.py`
- Model-owned research loop: `proxy/services/chat_evidence_application_service.py`
- Tool-selector: `proxy/services/agent_router_service.py` (выдаёт только typed
  `tool_result`, top-level `answer` удаляется на его границе)
- Детерм. политика: `proxy/services/deterministic_policy_service.py` (разрешает
  code-final только control-plane; glossary/registry/smeta/field и другие
  professional-domain каналы всегда требуют model final)
- Область поиска: `proxy/services/scope_service.py` (all/project/dataset…; проектный запрос при scope=all → не искать молча, спросить)
- Поток: `proxy/routers/chat.py` (`_run_chat`: profile/scope → evidence application; свободный
  запрос не вызывает `_det_channels`, auto-note или note-команды)
- Общий план результата: `proxy/services/workflow_plan_service.py`, док [ALGO-workflow-plan.md](ALGO-workflow-plan.md)
- Read-вложение из скрепки (`attachment_context`) — часть следующего пользовательского запроса:
  в auto-профиле ранний keyword/clarification-каскад пропускается, чтобы файл обработал LLM/RAG-путь.
  Если project/dataset scope не выбран, используется `attachment_context`-канал без глобального RAG:
  источником ответа считается только `attachment:<имя файла>`.
- Обзор на ревью: [ARCHITECTURE_les_algorithm.md](ARCHITECTURE_les_algorithm.md) §10

## Граница

- `table_query` детект всё ещё substring (`_looks_like_table_query`) — но теперь под router-интентом, агрегация пост-ретрив над Parquet ([[ALGO-table-query]]).
- Операторские заметки не создаются, не читаются и не подмешиваются в чат.
- Кодовый visible final для любого обычного текстового запроса запрещён независимо от формулировки и
  доступности router/tool-selector.
- Глоссарий и реестр проектов возвращают структурированное evidence без поля `answer`;
  блокеры могут быть сформированы кодом, но не подменяют предметное объяснение.
