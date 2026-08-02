# RELEASE_LEDGER — текущий выпуск

Канон «где мы сейчас» для агентов и релизной дисциплины.

| Поле | Значение |
|------|----------|
| product_version | **0.25.12** |
| build_number | **485** |
| desktop_version | 5.1.485 |
| base | `origin/main` @ `1fde2ea` (0.25.0 / build 473) |
| branch | `feature/smeta-local-ollama-stability` |

## 0.25.12 — LSR coverage gate + missing-rows pass (2026-08-02)

**Зачем:** при 6/19 привязках UI показывал «стоимость … 17 тыс.» как будто итог
сметы; дорогие строки оставались MISSING между fresh-run.

**Что вошло:** coverage gate в чате и шапке XLSX («сумма только по привязанным»);
второй model-pass только по unbound (`LES_SMETA_DOCUMENT_MISSING_PASS`, default on
для local Ollama/Qwen) — уже bound нормы не трогает; revision kind
`missing_rows_pass`.

## 0.25.11 — Ollama Qwen tool XML parse 500 retry (2026-08-02)

**Зачем:** mid-workflow `HTTP 500 XML syntax error … <function> closed by </parameter>`
ронял весь ЛСР (известный drift парсера tool-call у Qwen/Ollama).

**Что вошло:** в `_smeta_document_exchange` до 2 ретраев на такой 500: `seed+n`,
`think=false`, короткий nudge без XML-примеров; нормы не выбираются. Env
`LES_SMETA_DOCUMENT_XML_PARSE_RETRIES` (default 2).

## 0.25.10 — LSR: reject ГЭСНр without intent + mapping fingerprint (2026-08-02)

**Зачем:** два fresh-run по одному ВОР давали сильный разброс ФОТ из‑за разных
модельных привязок, в т.ч. ремонтных `ГЭСНр` на монтажные строки.

**Что вошло:** hard demote bind `ГЭСНр`/`ГЭСНмр` без маркеров ремонта в тексте ВОР
→ unbound (норма не подменяется); `mapping_fingerprint` + предупреждение в ответе
черновика; тесты.

## 0.25.9 — KS-2 official XLSX + download .xlsx not .txt (2026-08-02)

**Зачем:** заполненный КС-2 скачивался как «Акт…(КС-2).txt» (bytes были ZIP/XLSX,
но UI регистрировал title без расширения); бланк был плоской таблицей, а не формой
как в HTML-примере Госкомстата.

**Что вошло:** `ks2_xlsx_render` (шапка/ОКУД/8 колонок/подписи); filename с `.xlsx`
в chat command; тесты layout + extension.

## 0.25.8 — Studio icon + KS-2 after document LSR (2026-08-02)

**Зачем:** вкладка «Студия» без иконки (`o_edit_document` нет в Quasar outlined);
«сделай КС-2» после PDF/LSR отвечал «Нет последней ЛСР» — document artifact хранил
только `rim_trace`, а `assembled_from_artifact` читал лишь `rim_lsr_form`/`positions`.

**Что вошло:** иконка `o_edit_note`; разбор `rim_trace`/`lsr` → assemble; compact
`positions` + `.ks.json` sidecar после document LSR; тесты.

## 0.25.7 — PDF LSR needs attachment_id without OCR text (2026-07-31)

**Зачем:** «ЛСР не сформирована… строк 0» — скрепка `read` без текста не
передавала `attachment_id`, document workflow не стартовал, direct-путь не видел таблицу.

**Что вошло:** `_attachment_chat_payload` всегда шлёт `attachment_id` в режиме «В чат»;
понятнее hint при missing calculation.

## 0.25.6 — dispatcher status tasklist None stdout (2026-07-31)

**Зачем:** `GET /api/runtime/dispatcher/status` → 500: `tasklist` на Windows
иногда отдаёт `stdout=None`, парсер падал на `.splitlines()`.

**Что вошло:** безопасный разбор `None`/пустого stdout в `les_runtime_control`.

## 0.25.5 — KS chat hook before smeta mode (2026-07-31)

**Зачем:** «Собери КС-2» в режиме Смета уходил в model/RAG (пустые PRICE/SMETA)
вместо детерминированного `ks_forms`.

**Что вошло:** хук `is_ks_forms_query` перенесён сразу после /-команд, до
`estimate_harness` / RAG; регрессионный source-order тест.

## 0.25.4 — filled KS-2 / KS-3 / KS-6а from chat (2026-07-31)

**Зачем:** в чате нужны скачиваемые заполненные КС-формы, а не только blank бланки
и сверка уже существующих КС-2 Parquet.

**Что вошло:**
- `ks_forms_service` / `ks_forms_chat_service`: КС-2/КС-3 из последней ЛСР; КС-6а из
  confirmed журнала (без подстановки ЛСР как факта);
- `forms.generate(rows=)`, API `source=last_lsr|field_journal`, `/кс-2` `/кс-3` `/кс-6а`,
  NL «собери КС-…», `save_smeta` → ks2/ks3, ontology `ks6a`, sidecar JSON у smeta artifact.

**Проверки:** `uv run pytest tests/test_ks_forms_service.py tests/test_command_service.py
tests/test_smeta_ontology_service.py tests/test_les_action_service.py -q`; verify-эквивалент.

## 0.25.3 — fresh smeta run stability without mapping memory (2026-07-31)

**Зачем:** одинаковые PDF→ЛСР на `qwen3.5:9b` расходились по `bind`/`unbound` и соседним
шифрам таблицы при `temperature=0`, без кэша прошлого mapping.

**Что вошло:**
- Ollama `options.seed` = `LES_SMETA_DOCUMENT_SEED` (default `0`) в document/mapping exchange;
- стабильный порядок search/read items, RRF identity tie-break, одинаковый evidence path;
- submit отклоняет floating reject opened close-analog / table-neighbor без mismatch или явного
  критерия различия; skill/prompt ужесточены; code-side выбор нормы и replay mapping не добавлялись.

**Проверки:** `uv run pytest tests/test_smeta_core.py -k "floating_close or rrf_equal or search_batch_items or seed"`;
`uv run pytest tests/test_smeta_chat_application_service.py -k seed`; `make verify`.

## 0.25.2 — autonote false-positive on «выгрузи … — …» (2026-07-31)

**Зачем:** команда «выгрузи полную таблицу … — без пропусков» уходила в
`route=memory` / авто-заметку из‑за маркера ` — ` и отсутствия глагола «выгрузи»
в стоп-листе. RAG не вызывался.

**Что вошло:** `выгруз*` + request-маркеры в `memory_service`; тест; локально
`LES_AUTONOTE_ENABLED=false` в `config/local/windows-cuda.env`.

## 0.25.1 — local Ollama/Qwen LSR stability (2026-07-29)

**Зачем:** после 0.25.0 локальный `qwen3.5:9b` часто ронял PDF→ЛСР на hard-reject
`invalid unbound_evidence` / truncated structured JSON / catalog-only turns. На 0.24.48
неполный evidence шёл в `precalculation_blockers`, и XLSX всё равно собирался.

**Что вошло:**
- soft-accept incomplete unbound/bind evidence → `precalculation_blockers` (default для
  local Ollama+Qwen; env `LES_SMETA_DOCUMENT_SOFT_ACCEPT`);
- mapping transport: parse thinking / one `think=false` retry / higher token budget on
  `done_reason=length`;
- local batch_size=1; max tool turns 6; global review off by default on local;
- search/open-cards preflight before forced mapping; align truncated `queries_used` /
  `opened_norm_codes` to tool trace;
- Windows helper scripts `scripts/windows/LES-START|STOP` + `config/local/windows-cuda.env`.

**Проверки:** `uv run pytest tests/test_smeta_core.py -k "soft_accept or unbound_fills or batch_agent_opens or batch_agent_searches or unbound_aligns"`;
`make verify` перед merge.

**Не в коммите:** `tools/bin/qdrant.exe` (локальный бинарь).

## Предыдущий якорь

| product_version | build | commit | note |
|-----------------|-------|--------|------|
| 0.25.0 | 473 | `1fde2ea` | почта вручную + лёгкая проверка выпуска |
| 0.25.0 | 472 | `65aa9a9` | Outlook освобождён до разбора снимков |
| 0.25.0 | 470 | `3b8eb35` | mail Outlook + Windows packaging поверх выпуска 0.25.0 |
| 0.25.0 | 470 | `4f1a305` | полный исходный код и документация 0.25.0 |
