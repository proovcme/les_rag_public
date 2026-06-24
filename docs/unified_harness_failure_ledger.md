# Unified Construction Harness — Failure Ledger (v0.8)

Реестр поведения на operational-смоуке. `no_data`/`MISSING` с честным evidence — НЕ баг, а
корректный отказ. Баг — только системная ошибка, фейковый источник или маршрут не туда.

**Как включить (dev):** `LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1` (OFF по умолчанию — в коде и
тестах не меняется). Смоук: `LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1 uv run python
scripts/smoke_unified_v08.py` (фикстура) или `--dataset-id <ds>` (реальный проект). Trace ответа:
`query_route.version=unified_construction_harness_v0_8` + `unified_trace` + `evidence_summary`.
Выключить: убрать env-переменную. Runtime (`/Users/ovc/LES/.env`) НЕ трогался — флаг ставит оператор.

## Прогон 2026-06-24 (фикстура «котельная», 10 кейсов, offline)

| # | вопрос | route | status | failure_type | вердикт |
|---|--------|-------|--------|--------------|---------|
| 1 | опиши проект + реестр | project_document_registry | complete (6 src, 3 мусор) | — | OK |
| 2 | найди ОЗК в актах | asbuilt_extract | complete (1 src) | — | OK (не нормы) |
| 3 | найди КДУ в актах | asbuilt_extract | no_data | term-not-in-source | OK (generic, честный MISSING) |
| 4 | найди ОЗК в спецификации | project_doc_entity_search | complete (1 src) | — | OK (не «монтаж») |
| 5 | правила расстановки ОЗК | norm_qa | no_data | **lexical_miss** | limitation |
| 6 | что писали в почте | mail_entity_search | no_data | **mail_source_missing** | limitation |
| 7 | извлеки ВОР из Ф9 | bor_extract | complete (1 src) | — | OK |
| 8 | собери ЛСР по Ф9 | estimate_from_bor | complete | — | OK |
| 9 | проверь пример обсчёта | resource_cost_calc | complete (real workbook) | — | OK |
| 10 | что требует КАЦ | resource_cost_calc | complete | — | OK |

**Маршрутизация: 10/10 верно.** source_scope доминирует над термином (2,3,4 → не нормы),
generic-термины без словаря (КДУ), нормы/обсчёт раздельно.

## Открытые limitation'ы (не баги — честный MISSING)

| failure_type | где | причина | proposed_fix | статус |
|--------------|-----|---------|--------------|--------|
| `no_scope` | project/asbuilt/ВОР/mail без проекта | нет project_id/dataset_ids | **actionable MISSING** (какой источник нужен) | ✅ v0.8 |
| `lexical_miss` | norm_qa | в фикстуре нет lexical-индекса; PDF-тело не ищется | Qdrant-vector + PDF-тело в norm_qa | ⏳ v0.9 |
| `mail_source_missing` | mail_entity | async `mail_query` не интегрирован в unified | read-only mail-adapter (rag_backend + mail-dataset) | ⏳ v0.9 |
| `parquet_only_limitation` | source_scoped | ищет в parquet-строках + именах файлов, не в теле PDF/чанках | tier-3 lexical + tier-4 vector с пометкой `chunk` | ⏳ v0.9 |
| `qdrant_not_used` | norm/source_scoped | vector-ретрив не подключён к unified | source-adapter к Qdrant | ⏳ v0.9 |
| `price_db_missing` | resource | цены из workbook-ячеек, не из ФГИС | bridge `fgis_price_lookup` (готов, not_found) | ⏳ |

## Safety-инварианты (подтверждены смоуком + тестами)

- числа/нормы/письма/факт монтажа — НЕ из модели; нет фейковых source_refs;
- spec-совпадение (#4) ≠ подтверждение монтажа;
- мусор (#1) помечен, НЕ удалён физически;
- mail read-only (нет send/push); reconstructed workbook не выдаётся за real;
- `final_total` только при complete; «П»/needs_kac → MISSING.

## ✅ v0.9 (2026-06-24): real source adapters — размытые limitation'ы → ЯВНЫЕ статусы

`proxy/services/source_adapters.py` (unavailable-safe, без фейков): lexical (sync SQLite/FTS — реально
находит при наличии индекса), vector (Qdrant — async+backend → `unavailable` в sync-пути), mail
(async mail_query+backend → `mail_backend_not_configured`). source_scoped и norm_qa отчитываются
`searched_tiers`; trace v0_9 несёт searched_tiers + adapter_warnings. Смоук v0.9 (`smoke_unified_v09.py
--append-ledger`):

| статус был (v0.8) | стал (v0.9) |
|---|---|
| `parquet_only_limitation` (молча) | tier-chain: parquet→filename→**lexical_chunk**→vector; searched_tiers в trace |
| `lexical_miss` (vague) | norm_qa layered (lexical→vector); MISSING перечисляет tier'ы |
| `qdrant_not_used` (vague) | **explicit `vector_unavailable`** warning (async не вшит в sync-путь) |
| `mail_source_missing` (vague) | **explicit `mail_backend_not_configured`** (read-only adapter, нет send/push) |

Прогон фикстуры: КДУ-в-актах → no_data, tiers=4, `vector_unavailable`; нормы → no_data, tiers=2;
почта → no_data, `mail_backend_not_configured`. Маршруты 10/10. Адаптеры в оффлайне честно
`unavailable`/`not_found` — НЕ фейк.

## ✅ v0.10 (2026-06-24): async real adapters — vector/mail из static unavailable → реальные

`source_adapters.py`: `search_vector_chunks_async` / `retrieve_mail_evidence_async` (через инжекцию
async-замыкания из `_run_chat`; адаптер не знает тяжёлую сигнатуру retrieve_chat_chunks/mail_query).
`run_unified_construction_harness_async` (sync-first + async-escalate): sync делает tier 1-3, при
наличии backend эскалирует tier-4 vector / mail. Trace v0_10 несёт `adapter_statuses`
{parquet/lexical/vector/mail}. Новые статусы: timeout, error, weak_related, no_source.

| было (v0.9) | стало (v0.10) |
|---|---|
| vector static `unavailable` | реальный async-адаптер: backend→found, нет→unavailable, медленно→timeout, сбой→error |
| mail static `not_configured` | реальный async mail_query (read-only): backend→found(message_id), нет→unavailable |
| — | **семантический vector без точного термина → `weak_related`, НЕ «найдено»** (анти-overclaim) |

Smoke v0.10 (`smoke_unified_v10.py --stub-vector --stub-mail`): norm→complete vector=found;
mail→complete mail=found; КДУ-в-актах→vector=**weak_related** (семантика, термина нет). Offline (без
backend) → честный unavailable. `_run_chat` строит vector_fn/mail_fn ТОЛЬКО при реальном backend
(есть list_datasets); test/offline → fn=None → unavailable. Нет asyncio.run в running loop.

## ✅ v0.12 (2026-06-24): FILE_BODY + EML + MARKDOWN — закрыт реальный gap v0.11

v0.11 вскрыл: реальные датасеты = `.md`/`.eml`, не parquet. v0.12 читает их НАПРЯМУЮ read-only (без
OCR/бинарей), source_ref до файла/строки/message_id.

`source_adapters.py`: `search_file_body` (.md/.txt, path-traversal + лимиты), `search_eml_messages`
(.eml через email.parser, snippet-only, нет send/delete), `extract_markdown_tables_from_file`/
`markdown_table_to_rows` (markdown pipe-таблица → ВОР-строки). Интеграция: source_scoped tier-chain
parquet→filename→**file_body→eml**→lexical→vector; norm_qa file_body первым tier'ом; retrieve_project_doc
markdown-fallback при no_parquet. index_health +md/txt/eml/markdown_table counts + readable_body_available.
doc_classifier: revit-api/cad_bim/speckle .md → external_reference (не проектный док), .md/.txt→project_doc.

| было (v0.11) | стало (v0.12) |
|---|---|
| `no_lexical_index` (слепо) | **file_body** ищет в .md напрямую → RETRIEVED; health: no_lexical_index_but_file_body_available |
| `mail_backend_not_configured` | **.eml читается** → mail_not_found (термина нет) ИЛИ found(message_id); backend опционален |
| `f9_not_found_no_parquet` | **markdown-таблица в .md** → ВОР-строки с source_ref (ЛСР проходит) |

**Реальный прогон датасета 11da8ad7 (402 .eml):** health eml=402; mail → `mail_not_found` (прочитал 402
реальных письма, термина нет — НЕ backend_not_configured); norm file_body-tier. Синтетика: markdown
Ф9 → ВОР (3 строки), .eml ОЗК → found(message_id), file_body .md → found(#L3). 33 теста v0.12.

**Безопасность v0.12:** read-only, без OCR, path-traversal блок, лимит размера/числа файлов/сниппетов,
snippet-only (нет полного тела письма), нет send/delete/mutate, нет fake source_refs, нет хардкод-словаря.

## ✅ v0.13 (2026-06-24): DOCUMENT BODY EXTRACTION — PDF/DOCX/XLSX → searchable

v0.12 закрыл .md/.eml; v0.13 закрывает БИНАРНЫЕ доки через read-only sidecar-извлечение (БЕЗ OCR,
без облака, оригиналы не трогаются). Библиотеки в окружении: fitz/PyMuPDF + pdfplumber (PDF),
python-docx (DOCX), openpyxl (XLSX) — все есть.

`doc_extract_service.py`: extract_pdf_text (no_text_layer без OCR), extract_docx (абзацы+таблицы),
extract_xlsx_generic (строки), extract_bor_tables (xlsx/docx → ВОР-таблицы), sidecar write/read
(storage/datasets/{ds}/_extracted/<rel>.jsonl). source_ref до page/paragraph/sheet/row.
`search_extracted_body` адаптер: source_ref до ОРИГИНАЛА (не sidecar). Интеграция: source_scoped
tier-5 extracted_body (после file_body/eml, до lexical); norm_qa tier-2; retrieve_project_doc xlsx/
docx-table fallback. index_health +pdf/docx/xlsx/sidecar counts. extract_dataset_bodies_v13.py
(--dry-run/--report, path-safe, лимит размера).

| было (v0.11/v0.12) | стало (v0.13) |
|---|---|
| `no_lexical_index` для PDF/DOCX | **extracted_body** ищет в sidecar → RETRIEVED #page/#para |
| `pdf_files_without_sidecars` (новый health-warn) | actionable: «запустите extract_dataset_bodies_v13.py» |
| `f9_not_found_no_parquet` | **ВОР из XLSX/DOCX-таблицы** (sheet!row / table-row source_ref) |
| `no_text_layer` (новый) | scanned PDF → честный no_text_layer, не фейк (OCR вне hot-path) |

Смоук (синтетика): PDF/DOCX/XLSX → extract (sidecar), search_extracted «ОЗК» → found #para1,
source-scoped спец → complete (extracted_body tier), ВОР из XLSX → 2 строки. 28 тестов v0.13.
**runtime .env НЕ трогал; sidecar в рантайм НЕ писал** (только dry-run разрешён без ОК оператора).

**Безопасность v0.13:** read-only оригиналы (тест на неизменность байтов), без OCR, path-traversal
блок, лимит размера 40МБ, dry-run не пишет, нет fake source_refs, нет облака, extractor_version в каждом
item, scanned PDF → no_text_layer (не выдумка).

## ✅ v0.14 (2026-06-24): RUNTIME SIDECAR ACCEPTANCE + WRITE-POLICY + TEST-STABILITY

v0.13 доказал extraction на синтетике; v0.14 — operator-safe runtime-процесс + реальная dry-run-
приёмка + починка test-flakiness.

**Test-stability (КОРЕНЬ найден):** «2 chat-падения в общей сессии» — НЕ chat-state leakage и НЕ
pytest-randomly (его вообще нет в окружении). Реальная причина: `test_agent_router.py::test_classify_*`
мокали `les_md_service._llm_text`, а `_classify` зовёт `_route_llm_text` → мок не срабатывал → РЕАЛЬНЫЙ
LLM-вызов на :8080 (24с), шум→'none'. «Flaky» = зависело, ответил ли живой :8080. Фикс: мок на правильный
путь `ar._route_llm_text` → герметично (24с→0.25с). Полный chat/router/mail-сет: 2 failed → **0 failed (83)**.

**Write-policy gate:** doc_extract_service +manifest/staleness/runtime-guard. scripts/extract_dataset_
bodies_v14.py: dry-run по умолчанию; --write-sidecars пишет; запись в RUNTIME (/Users/ovc/LES) требует
--confirm-runtime-write И env LES_ALLOW_RUNTIME_SIDECAR_WRITE=1, иначе ⛔ `runtime_sidecar_write_not_
approved` (dry-run). manifest.json (mtime/size оригиналов) → `sidecar_stale`. index_health +manifest_
present/stale_count/sidecar_stale-warning.

**Реальная dry-run приёмка (датасет 844a2b53, 27 ГОСТ/СП .docx, read-only):** would_write=27,
**docx_paragraphs=23 930** извлекаемо, 0 failures, originals_mutated=False. Gate проверен: --write в runtime
без разрешения → ⛔, _extracted НЕ создан. **Sidecar в рантайм НЕ писал (нет одобрения оператора в этой
сессии); runtime .env НЕ трогал.**

15 тестов v0.14 (write-policy gate, manifest, staleness, real dry-run, agent_router-герметичность,
регрессии). 345 unified-сюита + 83 chat (0 failed) + verify зелёные.

**Safety v0.14:** оригиналы read-only (тест на байты), dry-run не пишет, runtime-write за двойным гейтом,
без OCR, без облака, нет fake source_refs, staleness честно помечается, evidence-контракт цел.

## Открыто (когда backend подключён в рантайме)
- vector/mail сейчас `unavailable` в **sync** unified-пути (async retrieve/mail_query не вшит). Закрыть —
  async-обёртка адаптеров в chat-пути ИЛИ sync-мост к Qdrant.
- lexical реально найдёт тело PDF, **если корпус проиндексирован** в lexical_chunks (в фикстуре пусто).
- реальный resource-price DB/ФГИС (bridge готов, not_found). **На реальном проекте в GUI прогон ещё не
  делался** — оператору включить флаг в рантайме (`LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1`) и
  `smoke_unified_v09.py --dataset-id <id> --append-ledger`.

## ✅ v0.11 (2026-06-24): REAL-DATA ACCEPTANCE (26 датасетов рантайма, read-only)

**runtime flag NOT changed by policy** — оператор не давал явного разрешения; прогон только через
script-smoke на реальных данных `/Users/ovc/LES/storage/datasets` (read-only). `inspect_dataset_index_
health` (§5) превращает общий lexical_miss в КОНКРЕТНЫЙ no_lexical_index/no_parquet.

**Главное открытие о реальных данных:** датасеты рантайма НЕ хранят `_parquet/` — это `.md`/`.docx`/
`.eml`, проиндексированные в Qdrant/lexical. parquet-путь harness'а (ВОР/ЛСР/source-scoped-по-строкам)
на реале пуст; нужен lexical/vector (в dev-view индекс пуст → no_lexical_index).

**Прогон датасета 844a2b53 (27 реальных ГОСТ/СП, 16 вопросов) — 16/16 классифицировано верно:**

| вопрос-класс | route | status | failure_type | вердикт |
|---|---|---|---|---|
| опиши проект + реестр | project_document_registry | **complete (27 src)** | — | ✅ WIN: registry РАБОТАЕТ на реальных ГОСТ/СП |
| найди ОЗК/КДУ в актах | asbuilt_extract | no_data | `no_source_in_scope` | OK (нет актов в норм-датасете) |
| правила/нормы (×4) | norm_qa | no_data | `no_lexical_index` | limitation (индекс пуст → проиндексировать) |
| почта (×2) | mail_entity_search | no_data | `mail_backend_not_configured` | limitation |
| ВОР/ЛСР | bor/estimate | no_data | `f9_not_found_no_parquet` | OK (Ф9 не выгружен как parquet) |
| обсчёт/КАЦ | resource_cost_calc | **complete** | — | ✅ real workbook |

**Категории (real): no_source_in_scope=4, no_lexical_index=4, mail_backend_not_configured=2,
f9_not_found_no_parquet=2.** Все — честные limitation'ы (нет источника нужного типа в датасете), НЕ
баги: маршрут верный, evidence честный, нет фейков/галлюцинаций. elapsed 0.2–155 мс.

**Закрыто в v0.11 (failure-driven):**
- ✅ `lexical_miss` → конкретный **`no_lexical_index`** через index-health (norm_qa MISSING называет
  причину: «корпус не проиндексирован, проиндексируйте документы», а не общее «не найдено»).
- ✅ failure-классификация по intent (был баг: asbuilt-без-актов помечался mail → теперь no_source_in_scope).

**Блокировано отсутствием инфраструктуры (не баг, нужен оператор/рантайм):**
- `no_lexical_index` — индекс lexical_chunks пуст в dev-view (в рантайме наполнен; нужен прогон ТАМ).
- `mail_backend_not_configured` — async mail_query требует живой rag_backend (есть в рантайме).
- `f9_not_found_no_parquet` — реальные Ф9/ВОР индексируются, не лежат parquet'ом в датасете.

**Следующий шаг — РЕАЛЬНЫЙ прогон В РАНТАЙМЕ** (оператор включает флаг): тогда lexical/vector/mail
наполнены → no_lexical_index/mail закроются реальными RETRIEVED. Команда: `LES_UNIFIED_CONSTRUCTION_
HARNESS_ENABLED=1 python scripts/smoke_unified_v11.py --dataset-id <ID> --storage-root /Users/ovc/LES/
storage/datasets --append-ledger`.
