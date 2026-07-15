# TEST_INVENTORY — карта тестов Л.Е.С.

Гейт: `make verify` (офлайн, синтаксис+сбор коллекции). Полная сюита: `make test`.
На исходном срезе 2026-07-14 полный контролируемый прогон дал `2926 passed, 6 warnings`;
после clean-install smeta baseline и Windows launcher regression текущая коллекция — **2947 тестов**.
Это регрессионная коллекция, а не 2947 равноценных release-гейтов.

Архитектурный разбор и список исторического долга:
[TEST_ARCHITECTURE_AUDIT_2026-07-14.md](TEST_ARCHITECTURE_AUDIT_2026-07-14.md).

- `make test-architecture` — текущие тесты без 11 файлов выключенного Unified/Construction Harness;
- `make test-release-critical` — узкие unit/code-проверки ФСНБ, clean-install baseline,
  index-contract и жизненного цикла датасетов; это локальный gate Windows-выпуска;
- `make test-rag-core` — короткий обязательный RAG integrity-профиль;
- `make test` — всё, включая 288 исторических тестов, пока legacy adapters не удалены;
- живые Qdrant/модель/Windows release-smoke запускаются отдельными инструментами и не подменяются
  зелёным offline pytest.

RAG-ядро имеет отдельный обязательный профиль `make test-rag-core`; offline defaults задаются в
`tests/conftest.py`. Аудит достоверности гейтов: [RAG_TEST_PROGRAM_AUDIT.md](RAG_TEST_PROGRAM_AUDIT.md).

Ниже сохранена подробная карта профильных наборов. Строки v0.16–v0.24 являются исторически
сложившимися именами файлов, а не текущей версией архитектуры.

| Файл | Тестов | Покрывает |
|---|---:|---|
| `tests/test_installer_windows.py`, `tests/test_tauri_desktop.py`, `tests/test_install_les.py`, `tests/test_onboard_reranker.py`, `tests/test_software_versions.py`, `tests/test_patch_release.py`; live `tools/windows_{release_smoke,production_deploy}.ps1` | focused + Windows live | Windows/Tauri release contract: persistent state, обязательные uv/Ollama/Docker/Qdrant, version/build contract, bootstrap-status и verified BGE. Изолированный gate доказывает provisioned smeta baseline (≥40 000 норм, ≥1 500 ФСЭМ), настоящий старт resumable ФСНБ-job со слоями/статусом, временный датасет и native RRF. Затем production gate устанавливает тот же EXE в Legion state и требует `4/4` реальных тяжёлых PDF, ненулевые фрагменты, `dense + qdrant_sparse → RRF` и удаление только smoke-датасета до публикации |
| `tests/test_local_inference_benchmark.py` | 8 | офлайн-контракт direct OpenAI benchmark и OptiQ probe: p50/p95, usage/cache normalization, MTP summary, tool/prefix profiles, sampler forwarding и чтение per-request telemetry JSONL; live model-series запускаются отдельно через `tools/local_inference_benchmark.py` + `tools/optiq_mtp_probe_server.py` |
| `tests/test_answer_render_v16.py` | 26 | render-хелперы Совушки: strip markdown из ячеек, source-chips, evidence-секции, citation/conflict-блоки, citation drawer payload, compact trace включая topic-guided retrieval, `answer_copy_text` (Копировать без trace/тела письма) |
| `tests/test_sidecar_ops_v16.py` | 50 | sidecar-операции: инвентарь датасетов, heading-классификатор, extraction-state (7 кейсов), lexical `extracted_fts`, OCR-детект, `run_extraction`/`extract_body_op` (gate env+confirm), originals read-only (shasum), legacy `.xls` |
| `tests/test_route_and_runtime_v17.py` | 34 | runtime alignment (extract-эндпоинты зарегистрированы), route-fix «реестр документации» ≠ глобальный реестр, doc_type_classifier, honest `.xls`, регрессии v0.3–v0.16 |
| `tests/test_deterministic_policy_v18.py` | 28 | DeterministicFinalPolicy: glossary-final только при литеральном термине, registry только глобальный, source-scoped/descriptive→reject; professional-domain candidates (`smeta/asbuilt/doc_registry/field`) не становятся final-ответом кода |
| `tests/test_version_service_v19.py` | 23 | `/api/version` 200, no-secrets, git-unavailable-safe, runtime_alignment (aligned/divergent/missing/dev-only/unknown), version_info в trace, route-регрессия |
| `tests/test_v020_deploy_stamp_ui.py` | 24 | deploy stamp (missing/ok/stale/hash-mismatch), `deployed_commit` в endpoint, copy plain/markdown/with-sources/no-trace, prompt-chips→меню «Примеры» |
| `tests/test_scope_model_v21.py` | 32 | Scope-резолвер (all/project/projects/dataset/datasets/mixed/legacy/filter-warning/scope>legacy); scope_options (админ-датасет/unassigned/system-reason/counts); scope в trace; document-prep labels |
| `tests/test_scope_clarification_v22.py` | 19 | §1 needs_project_scope and scope UI helpers remain, but chat no longer returns final `scope_clarification` for project questions at scope=all; `scope_all_for_project_query` is trace warning only, generic empty retrieval continues to model instead of code `NO_DATA` final |
| `tests/test_prompt_registry_service.py` | focused | prompt registry: common/tone/mode prompts, smeta role-pack, editable prompt overrides, plus live native-smеta loading of the GESN/typed-storage reference |
| `tests/test_module_router.py`, `tests/test_active_state.py`, `tests/test_scoped_rag.py`, `tests/test_skill_snippet_registry.py`, `tests/test_tool_trace_policy.py` | 23 | лёгкий LES core: module routing, active state as working memory, typed scoped evidence packet, short skill snippets instead of full skill injection, and transparent tool trace policy |
| `tests/test_tool_harness_service.py` | 5 | controlled tool-harness: typed read-only registry, indexed source search/read, PDF/Excel reader warnings, filesystem whitelist read/list/search/hash, and `/api/tools/call` dry-run |
| `tests/test_service_source_registry.py` | 4 | service-source registry and Play contract: required files/folders, canonical smeta/normcontrol sources, `SMETA_SERVICE` required-documents manifest, non-mutating operator messages, and normative base quarantine when semantic integrity report is absent |
| `tests/test_doc_review_retrieval.py` | 14 | doc-review retrieval-подфаза: факты project dataset отдельно от текста требования, явный нормативный SPDS RAG для ГОСТ Р 21.101-2026, запрет project fallback при настроенном нормативном источнике, legacy fallback только без найденного NTD |
| `tests/test_datasets_router.py` | focused | RAG dataset router/API plus retrieve-debug integrity: debug fields are exact projections of chunks and cannot inject FIRE/HVAC expected terms |
| `tests/test_smeta_artifact_service.py` | 10 | smeta direct artifact layer: extracts model-written Markdown estimate tables, totals visible `Сумма/Стоимость` columns, keeps long model tables visible by default, keeps legacy compaction opt-in, and writes XLSX/CSV downloads without changing model-selected works |
| `tests/test_project_summary_inventory.py` | 5 | MetaDB `documents` inventory for dataset file registers, extension/folder grouping, inventory prompt context, `что это за датасет` inventory intent, and explicit inventory intent distinct from broad project summary |
| `tests/test_estimate_harness.py` | 74 | smeta model-first harness: norm search/tool loop, direct mass/volume slots, duplicate direct-quantity guard, scenario assumptions, Russian dialog state, norm applicability questions (`norm_questions`), and `search_norm.norm_navigation` for model-facing shortlist guidance |
| `tests/test_smeta_core.py` | focused | smeta-core boundaries: code cannot own norm binding; bind requires selected/applicable; invalid model output never falls back to top candidate; document workflow applies explicit model coverage/resource decisions; analog with empty actions remains unresolved; valid target/resource/quantity action contract reaches calculation |
| `tests/test_smeta_user_message_service.py` | focused | машинные smeta-статусы не попадают в обычный ответ; частичная сумма названа стоимостью рассчитанной части; рубли форматируются по-русски; covered/open строки описываются человеческим языком |
| `tests/test_chat_attachment_service.py` | 3 | server-owned read attachments: opaque id/path containment, SHA/size validation, consume and TTL cleanup |
| `tests/test_request_idempotency_service.py` | focused | внешний контракт ЛСР: пользовательское временное вложение, привязка ключа к файлу/телу/пользователю, replay готового ответа без второго model call, `409` на конкурентный или конфликтующий повтор |
| `tests/test_prices_router_batch.py`, `tests/test_fgis_price_service.py`, `tests/test_les_mcp_server.py` | focused | пакетный exact lookup ФГИС: одна загрузка книги, сохранение missing, дедупликация кодов и наличие `les_price_lookup_batch` в MCP-каталоге |
| `tests/test_kac_web_service.py` | 2 | fail-closed web-KAC: strong exact-product identifier and three distinct suppliers with VAT normalization |
| `tests/test_smeta_norm_store.py` | 7 | typed SQLite-light smeta norm projection over existing GESN/FSM/TER sources: schema payload, FTS/LIKE candidate search, norm-card profiles with hints/resources/condition_hints/provenance/model_card/navigation, nearby norms, worker-thread cached reads, no heavy row leak in trace |
| `tests/test_smeta_structured_base.py` | focused | canonical smeta machine base: typed SQLite, quarantine, resource dedupe and pre-replace `minimum_norms` floor that preserves the existing canonical file on regression |
| `tests/test_smeta_release_baseline.py` | focused | immutable Windows smeta payload: source/base/FSEM SHA and counts, archive verification, clean-state provisioning, keep-valid-existing, fail-closed partial-state protection и repair с резервной копией повреждённого состояния |
| `tests/test_gesn_update_pipeline.py` | 2 | smeta base update pipeline: FGIS download/unify now continues into structured SQLite and generated `SMETA_SERVICE` cards, with explicit skip flags for generated layers |
| `tests/test_smetnoedelo_rag_import.py` | 5 | Smetnoedelo API v2.0 → smeta RAG importer: section/code payload normalization, markdown card rendering, request-budget stop, manifest output, and token-free cache/card behavior |
| `tests/test_smeta_ru_norm_download.py` | 5 | Smeta.RU public norm ZIP downloader: HTML link extraction, archive metadata, latest selection, pattern filter, and manifest-only run without network download |
| `tests/test_smeta_ru_norm_rag_ingest.py` | 3 | Smeta.RU ZIP → RAG worker: latest archive selection, archive projection into `RAG_Content/TABLE_SMETA/SMETA_RU_NORM`, state-based skip of already processed archives |
| `tests/test_chat_harness_format.py` | 38 | smeta answer formatting and voice-layer guards: partial/final totals, hidden tool terms, model comments, model-selected tool-call JSON parsing/scoping, rejection of contradictions when calculated partial totals are visible, and no code-generated smeta answer on model failure |
| `tests/test_context_memory_service.py` | 9 | dataset/service notebooks including GESN collection map prompt excerpt, typed dataset memory context, warmup, and navigation-not-evidence behavior |
| `tests/test_dataset_memory_service.py` | 20 | typed dataset memory source guide: file cards, source layers, retrieval routes, source graph, `navigation_terms`, `dataset_topic_map_v1`, `dataset_section_map_v1`, `dataset_topic_selection_v1`, lexical heading use, operator guidance, `NTD_*` project docs not mislabeled normative, FSNB human roles, service-noise downrank, reader-pass storage, actual-folder coverage and removal of invented reader file names |
| `tests/test_priority_corpus_inventory.py` | 6 | priority evidence-core inventory: read-only API pagination, source-quality card statuses/revision/maps, service-state exclusion, pending duplicate/runtime-status drift, operator disposition, and generated navigation-only Markdown |
| `tests/test_evidence_packet_service.py` | 5 | common evidence packet, shared source numbering and post-generation missing/invalid citation labels |
| `tests/test_retrieval_quality_service.py` | 3 | score-aware quality: dense thresholds apply only to dense similarity and never to Qdrant/local RRF or rerank logits |
| `tests/test_notebook_study_service.py` | 8 | broad notebook-study: explicit intent boundary, compact adaptive plan, actual file-group targeting, stale/invented reader-file rejection, strict target-file source identity, parallel retrieval, and `notebook_research_guide_v1` navigation contract (revision/source-map, reader status, coverage, follow-up questions) without turning it into evidence |
| `tests/test_converter_process_isolation.py` | 11 | index-конвертация PDF/Excel: PDF/XLSX выбирают killable subprocess where needed, реальные PDF по умолчанию получают fast page-text baseline, timeout isolated PDF converter падает в page-text fallback вместо `ERROR`, fast PDF baseline не запускает дорогой global boilerplate regex, флаг отключения возвращает direct path, spreadsheet parser идёт до MarkItDown, реальный XLSX проходит через child process, timeout вызывает terminate, большой результат читается из queue до join, маленькие таблицы остаются полными, большие дают `spreadsheet_navigation_projection` |
| `tests/test_document_router.py` | 33 | document router: typed file-role/domain/pipeline routing, Smeta.RU norm archives as normative, raw CAD/BIM guards, project PDF with weak estimate words or internal СП/ГОСТ references stays general `DOCUMENT`/electrical material instead of `TABLE_SMETA`/`NORMATIVE`, while explicit estimate PDFs still route to `SMETA` |
| `tests/test_parse_pipeline_w14.py` | 8 | parse-конвейер: стадии, prefetch/timeout/resume, сохранение границы delete-after-convert, и raw CAD/BIM не становится ложным `INDEXED 0` |
| `tests/test_bm25_sparse.py`, `tests/test_qdrant_adapter_parse.py`, `tests/test_datasets_router.py` | focused | parse/Qdrant adapter, explicit immutable model/backend embed contract, universal final token-budget and mixed-base64 sanitation gate; sparse fallback for compact drawing labels; bounded Ollama retry/batch split with real error reason; durable current-file/stage progress and truthful `QUEUED` semaphore wait |
| `tests/test_build_rag_contract_sibling.py` | focused | contract-clean migration safety: all-indexed scope, deterministic ids, atomic checkpoint, retry, immutable-contract env restore and explicit punctuation/noise exclusion without synthetic sparse tokens |
| `tests/test_rag_generation_supervisor.py` | 1 | launchd supervisor restarts only on unsuccessful exit and keeps build/gate/activation arguments explicit |
| `tests/test_rag_rrf_readiness.py` | focused | fail-closed activation gate: every dataset/destination point needs fingerprint+dense+sparse, source/child/exclusion accounting, complete FTS and contract-model/backend identity-checked live RRF endpoint |
| `tests/test_activate_qdrant_generation.py` | focused | stable alias activation requires green structural+FTS+live-RRF report; Qdrant/SQLite alias rollback clears or restores lexical projection; direct activation reconciles supervisor state |
| `tests/test_rag_readiness_service.py` | focused | GUI readiness reports honest ready/degraded/building/awaiting-activation states from contract, dense, sparse, fingerprint, FTS and alias coverage |
| `tests/test_deploy_to_runtime.py` | focused | service restart routing, clean-release scope from `deploy_stamp.deployed_commit..HEAD`, and safe distinction between a file matching the deployed commit and true runtime-only drift |
| `tests/test_smeta_rag_quality_probe.py` | 2 | smeta diagnostic probe preserves norm identity and technology evidence while keeping professional applicability outside machine scoring |
| `tests/test_system_dataset_service.py` | 3 | module-owned RAG identity: SMETA_SERVICE/GESN projections are typed `system/smeta`, project tables stay user-owned, MetaDB and module lookup persist the boundary |
| `tests/test_drawing_manifest_service.py` | 10 | MVP паспорта листа чертежа: PDF A4/A0 geometry, правая нижняя зона штампа, positioned text blocks, object/address/volume/cipher candidates with provenance, structural/text/graphical stamp parsing, semantic cipher split `ИОС.ЭС.ПЗ`, `Содержание тома` register rows, cp1251 mojibake repair, batch `cipher_norm` registry grouping, and scan/textless pages staying unknown instead of fake extraction |
| `tests/test_electrical_schematic_service.py` | 7 | electrical single-line/load reader: словарь расчёта нагрузок (`Руст/Pуст`→`p_installed_kw`, `Рр/Pр`→`p_calc_kw`, `Iр`→`i_calc_a`, `L/длина`→`cable_length_m`), типовая 11-колоночная таблица расчёта нагрузок с `Pр/Qр/Sр/Iр`, защита `РУ` как panel от путаницы с `Ру`/словами вроде `ручки`, extraction text nodes/vector lines/candidate circuit from synthetic one-line PDF, `cable_length_m` from scheme labels, and blank PDF stays unknown |
| `tests/test_electrical_materials_service.py` | 7 | electrical VOR/SO material reader: normalized `Поз/Наименование/Ед./Кол-во` rows, PDF mojibake repair for SO tables, cable mark/cores/section/`quantity_m`, section tracking, lighting classification, VOR/SO `doc_role`, work action, IP/current/single+multi-voltage/power, height, cable diameter, dimensions and mass attributes, `КунРс Внг(А)-FRLS` cable marks without `кг/м` false-positive, and guardrails so шинопровод/кабельная розетка do not become cable rows |
| `tests/test_electrical_evidence_summary_service.py` | 4 | electrical evidence summary: load aggregates by panel, panel hint from load-table file name, cable inventory/matching against material rows, SO→draft-VOR seed rows, issue counts with capped examples, and guard that gap rows are model navigation rather than a design/code verdict |
| `tests/test_pd_rd_manifest_service.py` | 2 | PD/RD source-map: многостраничное `Содержание тома`, `Состав проектной документации`, `Оглавление` ПЗ, declared total sheets, glyph mojibake repair `ɋɉ`→`СП`, and `ПЗ` kept as document kind/navigation rather than domain answer logic |
| `tests/test_project_pdf_extract_service.py` | 25 | Л.И.С.Т. dataset summary/status: exact role/discipline boundaries, resumable per-file checkpoints after summary loss, attempted vs successful coverage including explicit max-files truncation, honest `ok/partial/failed/empty`, bounded warnings/refs/register metadata, row-ref priority, path-safe dataset IDs and composition/electrical isolation; successful source-map automatically refreshes table/document registries and exposes integration status |
| `tests/test_project_pdf_table_service.py` | 52 | shared project table extraction/normalization and semantic navigation across ОВ/ВК/rooms/КР/ООС/ПБ/ИОС; cable-journal fragment merge/header inheritance; zero-level drawing annotation; project-composition headers; noise/text/service guards, including `UNKNOWN` retained in diagnostics but excluded from compact model navigation, and negative manual-table cases |
| `tests/test_project_table_registry_service.py` | 4 | build/search/read contract: registry cards stay navigation-only, hidden noise/service filters are honored, exact reads bind fingerprint+bbox+header+versions, and changed source PDF returns stale with tool evidence blocked |
| `tests/test_project_document_registry_service.py` | 3 | Documentation→project→stage→volume→section projection, existing-classifier/SPDS/drawing provenance, related КП separation, canonical stage fallback, implausible sheet-count rejection, metadata-only volume selection and flat-folder grouping by cipher instead of `/PDF` |
| `tests/test_project_registry_router_contract.py` | 1 | read-only/build API routes for table and document registries plus virtual-volume selection are registered without shadowing the generic dataset route |
| `tests/test_cad_bim_extract_dxf.py`, `tests/test_cad_bim_aggregate_w61.py`, `tests/test_cad_bim_import_inventory.py`, `tests/test_retrieval_service.py` | focused additions | CAD/BIM DWG input uses LibreDWG conversion before canonical graph build, repairs broken DXF group-code lines from real DWG output, JSON-sanitizes surrogate text, reconstructs drawn CAD tables from line/polyline grids plus text, and renders `CAD drawn tables`, first-position anchors, logical position rows, and compact row text before element noise; import inventory marks weak/minimal imports, duplicate source groups, and duplicate indexed projections; retrieval promotes exact source/projection/import-id hits and first ordinal table chunks after rerank, selecting CAD first-position chunks by actual `position N` before `chunk_ord`, so a precise CAD source or beginning of a target-file table is not hidden by a larger similar projection |
| `tests/test_saferag_service.py` | 12 | SafeRAG context/source helpers: lexical rank boost, source concentration, low raw-score lexical matches, protected opened documents, deduplicated copied docs, context builders and source-name order |
| `tests/test_static_assets.py` | 8 | статическая проводка UI: вкладки «Инструменты»/«Документы», visual read-only CDE contract, Л.И.С.Т. coverage/truncation, live dataset filter, topic/section map, CAD inventory panel + target_file deep-link, Qdrant visualizer mount, deploy shell permissions |
| `tests/test_fgis_full_update.py` | focused | публичный каталог/Сплит-формы, checkpoint/resume, автоматический перезапуск, объединение с уже идущим обновлением норм, API/UI wiring, отсутствие системного confirm при добавлении датасета и операторский progress contract: этапы, остаток, ETA, байты, скорость и журнал |
| `tests/test_document_explorer_service.py` | 11 | no-AI список/поиск/чтение документов и additive migration старой MetaDB без `lexical_chunks[_fts]`, без reindex |
| `tests/test_mermaid_graph.py` | 2 | live graph payload `/api/rag/graph/full` renders into Mermaid and empty graph is explicit |
| `tests/test_proxy_security.py`, `tests/test_proxy_routers.py` | 43 focused with Sovushka | trust/auth guardrails: ZeroTier/trusted admin, API-key roles, protected `les-admin-` root-admin keys without device binding, and trusted-only mutation of protected keys |
| `tests/test_sovushka_chat.py` | 32+ | Sovushka chat/UI regressions: markdown rendering, progressive-disclosure topbar and secondary actions, compact mode guidance/examples, new-chat/model-chip/table wrapping, editable prompt controls, attachment context, no project-summary final hijack, additive MetaDB inventory context, clickable file-register RAG, selected-dataset file panel, Samovar parse/play slot-context guard, scheduler-start endpoint guard, WAITING-vs-PARSING status, and file-layer labels |

## Ключевые «живые» доказательства (на рантайме :8050)

- **844a2b53 / e19cc409** — approved sidecar write: 27 / 22 sidecar, оригиналы байт-в-байт целы (shasum); extracted_body отвечает по ГОСТ/СП с source_ref до `.docx#para`.
- **resource workbook** — `ПРИМЕР_обсчета_24_06.xlsx` валидирован кодом: grand total **16 827 283.19 ₽**, line_diffs=0.
- **route**: «расскажи про котельную»@all→RAG/model with scope warning; @project→RAG; «что такое ОЖР»→glossary; «реестр документации»≠глобальный.
- **`/api/scope/options`**: 28 датасетов (assigned 2 / unassigned 25 / system 1), 6 проектов.
- **`/api/version`**: harness 0.24, `deployed_commit` ≠ git (deploy stamp), 0 секретов.

## Basic product smoke (L1 — реализован)

`make verify` и основная pytest-сюита хорошо ловят синтаксис, импорты, unit/regression
и часть contract-поведения. Но они не гарантируют, что живой пользовательский маршрут
"открыл UI -> задал вопрос -> увидел источники -> скопировал/открыл/остановил" работает
после очередной правки.

План: `docs/BASIC_FUNCTIONS_AUTOTEST_PLAN.md`.

Гейт `make smoke-basic` — **РЕАЛИЗОВАН** (`tools/basic_function_smoke.py` + цель в `Makefile`):
у каждого chat check отдельный конечный `--chat-timeout` (по умолчанию 45s), поэтому timeout
даёт наблюдаемый P0/P1 result, а не зависший gate.
L1 HTTP-смоук базовых функций против живого runtime (:8050/:8051), JSON-артефакт, non-zero на P0.
Браузерный слой L2/L3 (Playwright + `data-testid`) пока **открыт** — см. план.

Проверяется на L1:

```text
runtime/version/health
scope options
chat answer or explicit MISSING/BLOCKED
copy answer rendered
source chip/citation not fake
auth/trust boundary
diagnostics does not hide FAIL
```

## Чек-лист перед коммитом версии

1. `product_version` и `build_number` согласованно подняты в `config/version.json`.
2. `make verify` зелёный.
3. Профильные тесты версии + регрессия зелёные.
4. Deploy stamp пишется на `--apply` (или вручную `write_deploy_stamp` при cp).
5. `docs/RELEASE_LEDGER.md` обновлён; версии внешнего ПО сверены с `docs/SOFTWARE_VERSIONS.md`.
