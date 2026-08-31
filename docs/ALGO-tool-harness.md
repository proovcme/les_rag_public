# ALGO-tool-harness — controlled tools for LES

## Model-owned research loop (0.30.1 / build 635)

Обычный чат имеет три явных document scope: `none` («Без источников»), конкретно
выбранные датасеты/вложения и явный `all` («Все источники»). Router не выводит
scope из слов вопроса. При `none` документальные tools не выдаются и модель
общается как обычный ИИ в harness; вложение создаёт явную доказательную область.

При выбранных источниках код до первого model call выполняет канонический
production retrieval и даёт модели начальный evidence packet. Модель может
повторять `search_sources` с собственными формулировками и открывать точные
источники. Внутри chat research `search_sources` использует тот же named
`dense + bm25_sparse` native RRF, общий rerank и context expansion, а не
параллельный FTS-поиск. Разрешённые dataset IDs заморожены операторским scope;
модель не может расширить их аргументами tool call.

Цикл заканчивается, когда модель возвращает `calls: []`, либо по техническому
monotonic deadline. Семантического дедупликатора запросов, лимита «три попытки»
и кодовой оценки достаточности нет. Код механически удаляет только точные
дубликаты одного chunk ID/hash, исполняет tools и собирает следующий packet.
Финальный текст возвращается без validation/rewrite; citation check пишется
только в trace.

## Canonical workbook execution (0.29.0 / build 620)

Реестр содержит ровно `build_lsr_workbook` и `build_vor_workbook` версии
`1.0.0` с effect `draft`, обязательным idempotency key, server-owned attachment
scope и результатом `les.workbook_tool_result.v1`. Модель сама выбирает вызов;
regex forcing и автоматическая активация профиля отсутствуют. OpenAI,
OpenAI-compatible, Ollama и MCP получают schema-only проекцию одной записи.

Для context-bound workbook tools действует fail-closed capability manifest:
одна таблица `tool name → callable adapter` одновременно определяет model schema
и executor. Имя без callable не может попасть в shortlist; callable вне manifest
не обещается модели. Контракт проверяется сквозным тестом реального chat executor.

`WorkbookExecutionContext` связывает вызов с session/idempotency key,
model-decision revision, профилем, моделью и preset. Перед генерацией сервер
повторно проверяет ID, SHA-256 и тип вложения. Один idempotency key продолжает
тот же durable checkpoint; завершённый повтор возвращает уже опубликованную
revision и не запускает адаптер второй раз. Исправление с `parent_revision_id`
создаёт N+1, не меняя N.

VOR-адаптер переносит исходные строки, единицы, количества и locator в XLSX
без группировки и подстановки нулей; пустые unit/quantity выходят как `missing`.
LSR запускается через явно переданный тонкий application-adapter: модель сама
выбирает строки и шифры по RAG/tool evidence и передаёт их как `decisions`.
Adapter связывает решения с exact-карточками, считает trace и рендерит XLSX;
он не импортирует старый document workflow и не создаёт второй model loop.
Аргументы модели не могут передать готовые цены, суммы или рассчитанные строки. Публичный результат содержит
artifact/revision metadata, SHA, progress, missing/blockers и download URL, но
не filesystem path.

## Назначение

`tool_harness_service` даёт ЛЕСу единый слой инструментов: поиск/чтение источников,
карту датасета, bounded public web search и read-only filesystem. Это не второй
ответчик. Модель остаётся субъектом workflow: выбирает тему, документ, раздел,
смотрит результат инструмента и решает, хватает ли данных.

## Контракт

Канонический provider-neutral слой разделён на два типа:

- `ToolContract` — immutable имя/версия, JSON-вход, result schema, effect,
  scopes, timeout, retry/idempotency, result budget, model-owned fields и
  provenance policy;
- `ToolRegistration` — один contract, существующий sync/async handler и
  runtime availability predicate.

`ToolRegistry` допускает только одну активную регистрацию имени и fail-closed
отклоняет дубликаты. `canonical_tool_registry()` собирает реестр из существующих
handlers `tool_harness_service`: бизнес-логика не копируется. Старые
`ToolHarness.registry()/shortlist()/call()` являются compatibility facades над
этим реестром; поля `args_schema`, `returns`, `side_effects` сохранены вместе с
новой execution policy.

`CapabilityBroker` строит model-visible shortlist как детерминированное
пересечение immutable profile tools, dataset scope, workflow phase, runtime
availability, resolved model preset и оставшихся call/result budgets. В
`BrokerRequest` нет текста вопроса: broker не может выбрать workbook, норму или
другое профессиональное действие по словам пользователя. Не вошедшие tools
возвращаются по причинам `unknown/runtime/phase/scope/calls_budget/result_budget/
preset_limit`, а порядок разрешённых tools сохраняет порядок профиля. Qwen 9B
получает не более пяти contracts; 35B может получить большую coherent page, но
не другой набор профессиональных возможностей.

`TrustedExecutor` — единственная доверенная граница вызова зарегистрированного
handler. До исполнения он проверяет полный JSON Schema входа, dataset scope,
роль actor, deadline и idempotency policy. `commit`, `external` и `destructive`
разрешены только администратору с durable approval receipt, совпадающим по
`proposal_revision`, имени tool, SHA-256 точных аргументов и actor. В `shadow`
`draft` и любые более сильные эффекты не исполняются. Результат сначала
проверяется как `les_tool_result_v1`, затем оборачивается в
`les_tool_execution_v1`; превышение бюджета сохраняет целый объект за cursor и
никогда не режет JSON-текст. Старые `ToolHarness.call()` и `/api/tools/call`
проходят через ту же границу.

Approval не является JSON-заявлением клиента: request передаёт только
`approval_receipt_id`, а Executor читает immutable запись из доверенного SQLite
store и повторно проверяет status/expiry/actor/revision/tool/hash. Для
привилегированного эффекта тот же store атомарно резервирует idempotency key;
конкурентный вызов не запускает второй handler, а таймаут или невалидный ответ
оставляет `ambiguous`, запрещая слепой retry. Cursor привязан к actor, имеет TTL
и при durable execution хранит целый результат в том же store.

Один approval receipt атомарно связывается с первым actor/tool/argument hash/
idempotency key и не может разрешить второе действие под другим ключом. Для
любого privileged effect durable key обязателен независимо от декларации
handler. Косвенный `doc_id` до исполнения разрешается в authoritative dataset;
подстановка разрешённого `dataset_id` рядом с чужим `doc_id` scope не обходит.

Каждый вызов возвращает `les_tool_result_v1`:

- `tool`, `operation`, `inputs`, `status`;
- `result` — машинный результат инструмента;
- `sources` — проверяемые источники;
- `missing` — что не найдено;
- `warnings` — ограничения чтения;
- `trace` и `tool_trace` — почему результат получен именно так;
- `decision_required_from_model=true` — tool не принимает финальное предметное решение.

`validate_tool_result()` из `tool_trace_policy` проверяет базовый контракт и
запрещает типовые ошибки: превращать missing в ноль, выбирать финальную норму
или договорный объём кодом.

## Инструменты первого слоя

Dataset/source:

- `dataset_map` — typed карта датасета: `topic_map`, `section_map`, source layers,
  маршруты и operator guidance. Это navigation, not evidence.
- `search_sources` — в самостоятельном compatibility API это bounded
  `DocumentExplorer`; в model research loop — канонический production native
  RRF через `ModelResearchToolService`.
- `read_source` — ordered chunks одного документа.
- `read_pdf_source` — PDF-aware оболочка над indexed chunks. Raw page/table parser
  пока честно отмечается как отсутствующий.
- `read_excel_source` — Excel/CSV-aware оболочка над indexed chunks. Raw sheet/range
  parser пока честно отмечается как отсутствующий.

Filesystem:

- `filesystem_roots`;
- `filesystem_list`;
- `filesystem_stat`;
- `filesystem_read_text`;
- `filesystem_search`;
- `filesystem_hash`.

Filesystem read-only и whitelist-first. Базовые корни: `docs`,
`storage_datasets`, `rag_content`, `artifacts`; дополнительные корни можно
добавить через `LES_TOOL_FS_EXTRA_ROOTS=key=/path,key2=/path2`. Запрещены
секретные/тяжёлые/служебные сегменты: `.env`, `.git`, `.venv`, `data`, `logs`,
`dist`, `local_private_archive` и выход за корень.

Web:

- `web_search` — bounded поиск публичных страниц через существующий DuckDuckGo HTML adapter;
  возвращает title/snippet/direct URL и никогда не объявляет snippet доказанным фактом.

Режим чата «Агент» явно включает model-owned research loop. Он не получает shell,
desktop-control, запись файлов или произвольные HTTP-действия: только зарегистрированные
read-only tools. Финальный ответ и оценку достаточности источников делает модель.

## Рычаги

### GUI dry-run

В «Документы» блок `Tool-harness dry-run` — это операторский пульт тех же
инструментов, которые модель получает в tool loop. Он не вызывает модель и не
пишет в источники; он показывает, какой packet вернёт executor.

Кнопки:

- `Registry` — показать полный реестр инструментов: имя, категория, краткое
  назначение, `args_schema`, тип результата, side effects.
- `Shortlist` — дать текущий запрос/режим в `harness.shortlist()`. Это первый
  шаг модельного loop: из этого списка модель должна выбрать tool calls.
- `Dataset map` — вызвать `dataset_map` для выбранного датасета. Возвращает
  навигацию: topics, sections, source layers, routes, gaps. Это не evidence.
- `Search` — вызвать `search_sources` по строке верхнего поиска, с фильтром по
  выбранному датасету/документу.
- `Read doc` — вызвать `read_source` для выбранного документа или
  `dataset_id + doc_name`.
- `FS roots` — показать разрешённые read-only filesystem roots.

Нижний trace-блок всегда показывает один формат: `schema`, `tool`, `operation`,
`status`, `sources`, `missing`, `warnings`, `trace`, `result`. Это важно: если
оператор видит в dry-run `missing` или warning, модель получит тот же сигнал и
должна решать, что делать дальше, а не получать скрытый fallback.

### API

- `GET /api/tools/registry`;
- `POST /api/tools/shortlist`;
- `POST /api/tools/call`;
- `GET /api/tools/filesystem/roots`;
- `GET /api/tools/filesystem/list`.

Auth policy:

- `registry`, `shortlist`, `filesystem/roots`, `filesystem/list` — user-level;
- `call` — admin-level, потому что это executor даже для read-only tools.

Request/response examples:

```bash
curl -fsS http://127.0.0.1:8050/api/tools/registry | python3 -m json.tool
```

```bash
curl -fsS -X POST http://127.0.0.1:8050/api/tools/shortlist \
  -H 'content-type: application/json' \
  -d '{"question":"что есть по котельной в проекте","mode":"map","limit":8}' \
  | python3 -m json.tool
```

```bash
curl -fsS -X POST http://127.0.0.1:8050/api/tools/call \
  -H 'content-type: application/json' \
  -d '{"tool":"search_sources","args":{"q":"котельная","dataset_ids":["<dataset_id>"],"limit":20}}' \
  | python3 -m json.tool
```

`/api/tools/call` request:

```json
{
  "tool": "search_sources",
  "args": {
    "q": "пожарная сигнализация",
    "dataset_ids": ["<dataset_id>"],
    "doc_id": "",
    "doc_name": "",
    "limit": 20,
    "max_chars": 1200
  }
}
```

`les_tool_result_v1` response:

```json
{
  "schema": "les_tool_result_v1",
  "tool": "search_sources",
  "operation": "search",
  "status": "ok",
  "result": {},
  "sources": [],
  "missing": [],
  "warnings": [],
  "trace": "searched lexical chunks through DocumentExplorer",
  "decision_required_from_model": true,
  "contract_check": {"ok": true}
}
```

Успешный compatibility-ответ сохраняет верхний `les_tool_result_v1`, прежний
`spec` и добавляет поле `execution` с metadata envelope. Typed rejection/
timeout/overflow возвращаются как `les_tool_execution_v1`. Публичный admin API
принимает только `approval_receipt_id`, `idempotency_key` и относительный
`timeout_seconds`; authorization scope и monotonic deadline создаёт сервер.
Identity API-key строится как server-side SHA-256 principal id, а не из
неуникального отображаемого имени владельца.

### CLI

```bash
uv run python tools/les_tool_harness.py registry
uv run python tools/les_tool_harness.py shortlist "что есть по котельной в проекте" --mode map --limit 8
uv run python tools/les_tool_harness.py search "пожарная сигнализация" --dataset-id <dataset_id>
uv run python tools/les_tool_harness.py read --doc-id <doc_id> --kind pdf
uv run python tools/les_tool_harness.py fs-list --root docs --depth 1
uv run python tools/les_tool_harness.py fs-search "pdf-extract" --root docs --content
```

### Инструменты и входы

| Tool | Когда использовать | Основные args | Что возвращает |
|---|---|---|---|
| `dataset_map` | Нужно понять корпус/датасет до чтения chunks | `dataset_id`, `depth` | `topic_map`, `section_map`, `source_layers`, `retrieval_routes`, `known_gaps` |
| `search_sources` | Нужно найти релевантные indexed chunks | `q`, `dataset_ids`, `doc_id`, `doc_name`, `limit`, `max_chars` | ranked hits + `sources` |
| `read_source` | Нужно прочитать конкретный документ по chunks | `doc_id` или `dataset_id+doc_name`, `q`, `limit`, `max_chars` | ordered chunks / in-document hits |
| `read_pdf_source` | То же, но явно PDF-контекст | как `read_source` | indexed chunks + warning, если raw PDF parser недоступен в этом tool pass |
| `read_excel_source` | То же, но Excel/CSV-контекст | как `read_source` | indexed chunks + warning по sheet/range limits |
| `web_search` | Нужны актуальные публичные источники в явном Agent mode | `q`, `limit` | bounded title/snippet/direct URL + web sources |
| `filesystem_roots` | Нужно увидеть whitelisted корни | нет | keys, paths, forbidden parts |
| `filesystem_list` | Нужно открыть дерево разрешённого корня | `root`, `path`, `depth` | bounded tree |
| `filesystem_stat` | Нужно metadata без чтения | `root`, `path` | size, suffix, mtime, type |
| `filesystem_read_text` | Нужно прочитать небольшой текстовый файл | `root`, `path`, `max_chars` | text + truncation flag |
| `filesystem_search` | Нужно найти файл/текст вне индекса, но в whitelist | `root`, `path`, `q`, `content`, `limit` | bounded hits |
| `filesystem_hash` | Нужно проверить неизменность файла | `root`, `path` | sha256 + metadata |

## Статусы результата

- `ok` — инструмент вернул usable result.
- `missing` — выбранный путь/документ/запрос не дал данных; это не ноль и не
  отрицательный инженерный вывод.
- `error` — executor поймал исключение и вернул traceable packet.

`missing` и `warnings` обязательны для модели: она должна либо выбрать другой
tool/источник, либо честно сказать, чего не хватает.

## Model-selected loop в чате

Существующий visible path пока выполняет bounded multi-round legacy loop; явный
режим `agent` включает его независимо от общего optional-флага:

```text
question -> tool shortlist -> model tool_call -> validated executor
         -> les_tool_result_v1 -> model decides next step/final answer
```

Код не выбирает предметный ответ. Он строит shortlist, просит модель вернуть
строгий JSON `{"calls":[...]}`, исполняет только tools из shortlist, добавляет
`les_tool_result_v1` в prompt и пишет полный `retrieval_trace.tool_loop`.
Финальный visible answer снова пишет модель. Loop read-only, ограничен числом раундов
и вызовов; filesystem остаётся whitelist-first, web-search возвращает только публичные
результаты поиска с direct URLs.

Параллельно `canonical_route_service` разрешает `legacy | shadow | active`.
Отсутствующее значение — `shadow`; неизвестное значение — тоже `shadow`.
Запрошенный `active` без exact passing receipt для commit/build/preset/observed
model/acceptance hash эффективно остаётся `shadow`. Публикация/установка ничего
не активирует.

В `shadow` та же первая model-owned selector выдача проходит canonical one-call
validation: рассматривается максимум один разрешённый call, остальные учитываются
как pending. Broker получает фактические dataset ids чата, research phase,
профильный preset, runtime allowlist и оставшийся call/result budget; wildcard
scope по умолчанию в этот путь не подставляется. До shadow-решения Executor
проверяет JSON Schema, monotonic deadline
и dataset scope; косвенный `doc_id` разрешается прямым SQLite `mode=ro` без
миграций. Dataset/source/web и model-backed reads работают validate-only и
возвращают `TOOL_WOULD_EXECUTE`, не открывая provider/handler; исполняться могут
только чистые bounded filesystem reads. Draft/commit/external/destructive также
не исполняются. Пользователь видит только legacy answer; canonical result text
отбрасывается, а trace содержит лишь schema/status/code/counts/tool name с
`user_visible=false` и `persisted=false`. Обычный legacy `dataset_map` по-прежнему
строит notebook штатным путём; shadow не перестраивает память. `legacy` кандидат
полностью пропускает. Настройка видна в GUI runtime registry как `Danger` и
требует явного подтверждения и restart.
