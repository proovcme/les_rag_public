# ALGO-tool-harness — controlled tools for LES

## Назначение

`tool_harness_service` даёт ЛЕСу единый слой инструментов: поиск/чтение источников,
карту датасета и read-only filesystem. Это не автономный агент и не второй
ответчик. Модель остаётся субъектом workflow: выбирает тему, документ, раздел,
смотрит результат инструмента и решает, хватает ли данных.

## Контракт

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
- `search_sources` — FTS/LIKE поиск по `lexical_chunks` через `DocumentExplorer`.
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

С 0.24.0.215 общий чат делает первый bounded tool loop:

```text
question -> tool shortlist -> model tool_call -> validated executor
         -> les_tool_result_v1 -> model decides next step/final answer
```

Код не выбирает предметный ответ. Он строит shortlist, просит модель вернуть
строгий JSON `{"calls":[...]}`, исполняет только tools из shortlist, добавляет
`les_tool_result_v1` в prompt и пишет полный `retrieval_trace.tool_loop`.
Финальный visible answer снова пишет модель. Loop одношаговый и read-only;
filesystem остаётся whitelist-first.
