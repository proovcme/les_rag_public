# Unified Construction Harness — Failure Ledger (v0.8)

Реестр поведения на operational-смоуке. `no_data`/`MISSING` с честным evidence — НЕ баг, а
корректный отказ. Баг — только системная ошибка, фейковый источник или маршрут не туда.

**Как включить (dev):** `LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1` (OFF по умолчанию — в коде и
тестах не меняется). Смоук: `LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1 uv run python
scripts/smoke_unified_v08.py` (фикстура) или `--dataset-id <ds>` (реальный проект). Trace ответа:
`query_route.version=unified_construction_harness_v0_8` + `unified_trace` + `evidence_summary`.
Выключить: убрать env-переменную. Runtime (`/Users/ovc/LES/.env`) НЕ трогался — флаг ставит оператор.

## Operational incident 2026-06-27: partial runtime deploy with divergent app.py

During v0.23.6.12 rollout, `make ship` copied the new `service_sources` router and service, but
skipped divergent `proxy/app.py`; `/api/service-sources` returned 404. A targeted `--force` copy of
`proxy/app.py` then exposed older clean@HEAD app dependencies that were not present in the runtime
clone (`incoming_control`, `estimates`, `extract` routers and their services), so proxy failed to
start until those files were copied too. Final recovery: copy missing clean dependencies, verify
`create_app()` in `/Users/ovc/LES`, `launchctl kickstart -k gui/$(id -u)/me.ovc.les.proxy`, then
`/api/service-sources` and `tools/basic_function_smoke.py` passed.

**Rule:** when force-copying a divergent runtime entrypoint, also audit imports against the runtime
clone before restart; `make ship` only follows dirty files and can miss clean tracked dependencies
that never existed in `/Users/ovc/LES`.

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

## ✅ v0.15 (2026-06-24): APPROVED RUNTIME SIDECAR WRITE + REAL EXTRACTED-BODY SMOKE

**Оператор ЯВНО разрешил запись** sidecar для датасета 844a2b53 (через AskUserQuestion). Выполнен
approved runtime write (env LES_ALLOW_RUNTIME_SIDECAR_WRITE=1 + --confirm-runtime-write):
- 27 ГОСТ/СП .docx → **27 sidecar'ов + manifest.json**, **23 930 параграфов**, 0 failures;
- **оригиналы БАЙТ-В-БАЙТ идентичны** (shasum до/после), only _extracted/ добавлен;
- index_health: sidecar_available=True, extracted_body=23930, stale=0, warns→
  `no_lexical_index_but_file_body_available` (НЕ blind).

**Реальный extracted_body smoke (через unified harness на данных оператора):**
- registry → complete (27 ГОСТ/СП);
- norm_qa «правила огнестойкости стен» → **complete → СП 327.1325800.2017 #para85**;
- «требования к кровлям» → СП 17.13330; «опалубку» → СП 114.13330; «по нормам для серверной» → 9 src;
- «АУПТ для серверной» → honest `norm_no_source` (термина нет в структурных ГОСТ — НЕ no_lexical_index);
- asbuilt/spec → `no_source_in_scope` (нет актов в норм-датасете).

**v0.15 фиксы:** (1) norm_qa word-expansion — фраза нормализуется в склеенный блок и не матчит тело →
добавлен поиск по СОДЕРЖАТЕЛЬНЫМ словам >5 симв (кроме служебных); «огнестойкости» в «правила
огнестойкости стен» теперь матчит. (2) sample_extracted_terms_v15.py — сэмпл реальных норм-кодов/слов/
заголовков из sidecar (для позитивного smoke, не только negative).

| было (v0.14) | стало (v0.15) |
|---|---|
| no_lexical_index для ГОСТ-датасета | **extracted_body → complete с source_ref до .docx#para** ИЛИ honest norm_no_source |
| dry-run only | **approved runtime write** (27 sidecar, оригиналы read-only доказано) |
| — | term-sampler находит реальные термины (СП 20.13330, огнестойкость…) с source_ref |

24 теста v0.15 (norm word-expansion, sidecar-available, sampler, **4 реальных на 844a2b53-sidecars**,
write-policy/staleness регрессии). 351 unified-сюита + 83 chat (0 failed) + verify зелёные.

**Safety v0.15:** запись ТОЛЬКО с явным разрешением оператора (получено), оригиналы read-only (shasum),
без OCR, без облака, source_ref до реального абзаца (не sidecar-путь), нет fake-хитов, no_lexical_index
заменён реальным RETRIEVED или честным term_not_found. runtime .env НЕ трогал.

## ✅ v0.16 (2026-06-24): SIDECAR OPERATIONS + CLASSIFIER + EXTRACTION UX HOOKS

Извлечение стало **операторски видимой и управляемой** операцией (бэкенд; флаг OFF не менялся, runtime
.env не трогал, новых runtime-записей без одобрения НЕТ — только dry-run).

**§1 Инвентарь (28 датасетов, без записи):** mail=1 (11da8ad7, 402 .eml), norm=15, project-like=4,
extract-candidates=19, already-extracted=1 (844a2b53). `inspect_runtime_datasets_v16.py` →
`artifacts/runtime_dataset_inventory_v16.json`.

**§2 Dry-run на реальных датасетах (БЕЗ записи, оригиналы целы):** e19cc409 (project docx): files_seen=22,
would_write=22, **docx_paragraphs=20054**, originals_mutated=False; 11da8ad7: 402 .eml + 1 pdf; a1cc873f:
файлы `.xls` (legacy) + уже `_parquet/` — **парсер-лимит: .xls не извлекается** (данные уже в parquet);
844a2b53: manifest/sidecar=27/stale=0 — **дубль-записи не делал**; write без env → wrote_sidecars=0.

**§3 Классификатор по заголовкам** (`classify_document_from_sidecar`): мусорное имя + heading «Акт …
смонтированного оборудования» → **installed_equipment_act** (by=sidecar_heading); 844a2b53 остаётся
**norm** (by=filename). Heading улучшает, filename — фолбэк, «не-мусор» не теряется.

**§4 Extraction-state сообщения** (видимый MISSING/BLOCKED + действие, 7 кейсов A–G): sidecar_exists_and_
searched / extraction_required / extraction_write_not_approved / sidecar_stale / no_text_layer(ocr_required) /
term_absent_after_extracted_search / eml_dataset_searched. **Нет дженерик «не найдено»/«no_lexical_index».**

**§5 GUI/API** (backend готов; кнопка — TODO): `GET …/datasets/{id}/extraction-status`, `POST …/extract-
body/dry-run`, `POST …/extract-body/write` (write только confirm+env, иначе blocked-отчёт). Сервис:
`extraction_status`, `extract_body_op` (гейт extract_v14).

**§6A Lexical extracted_fts** (отдельная FTS): dry-run 844a2b53 → would_index=23930; write+search находит
текст с сохранённым source_ref до `.docx#para`; дубли по source_ref не переиндексируются. **§6B Qdrant —
только отчёт** (~2386 точек, deferred, embedding_run=False).

**§7 OCR — только детект** (`ocr_detection`): pdf_no_text_layer_count из manifest, ocr_status=deferred.
OCR не реализован, зависимостей не добавлено.

**§8 Smoke v16** (`smoke_unified_v16.py`, 15 канон.вопросов): 844a2b53 — norm_qa→complete (СП 70/114 с
source_ref), АУПТ→term_absent_after_extracted_search; 11da8ad7 — mail→eml_dataset_searched.

**Категории:** extraction_dry_run_done · extraction_write_blocked_by_policy · extraction_already_present ·
sidecar_heading_classified · extracted_lexical_index_ready · qdrant_index_deferred · no_text_layer/ocr_
required · eml_dataset_read · project_like_dataset(.xls лимит).

50 тестов + verify + 254 backend-регрессия + 17 chat OFF — зелёные. Safety: оригиналы read-only (shasum),
запись только env+confirm, без OCR/облака/Qdrant-эмбеддинга, без фейк-source_ref, без хардкода терминов,
флаг OFF и runtime .env не тронуты.

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

- smoke v16 `e19cc409-ac45-42b9-8029-d74cd9659a12`: corpus=norm sidecar=True states=['sidecar_exists_and_searched', 'term_absent_after_extracted_search'] complete=6/15
