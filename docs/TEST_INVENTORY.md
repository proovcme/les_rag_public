# TEST_INVENTORY — тесты Unified Construction Harness v0.16–v0.24

Гейт: `make verify` (офлайн, синтаксис+импорт-смоук). Полная сюита: `uv run python -m pytest tests/ -q` (~2664 теста).
Все тесты ниже офлайн (без живых Qdrant/MLX), flag `LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED` OFF.

**Профильные таблицы v0.16–v0.24: 299 тестов** (+ регрессия v0.3–v0.15 и chat/router при OFF). `make verify` на h0.24 собирает **2664 теста**.

| Файл | Тестов | Покрывает |
|---|---:|---|
| `tests/test_answer_render_v16.py` | 26 | render-хелперы Совушки: strip markdown из ячеек, source-chips, evidence-секции, citation/conflict-блоки, citation drawer payload, compact trace включая topic-guided retrieval, `answer_copy_text` (Копировать без trace/тела письма) |
| `tests/test_sidecar_ops_v16.py` | 50 | sidecar-операции: инвентарь датасетов, heading-классификатор, extraction-state (7 кейсов), lexical `extracted_fts`, OCR-детект, `run_extraction`/`extract_body_op` (gate env+confirm), originals read-only (shasum), legacy `.xls` |
| `tests/test_route_and_runtime_v17.py` | 34 | runtime alignment (extract-эндпоинты зарегистрированы), route-fix «реестр документации» ≠ глобальный реестр, doc_type_classifier, honest `.xls`, регрессии v0.3–v0.16 |
| `tests/test_deterministic_policy_v18.py` | 28 | DeterministicFinalPolicy: glossary-final только при литеральном термине, registry только глобальный, source-scoped/descriptive→reject; professional-domain candidates (`smeta/asbuilt/doc_registry/field`) не становятся final-ответом кода |
| `tests/test_version_service_v19.py` | 23 | `/api/version` 200, no-secrets, git-unavailable-safe, runtime_alignment (aligned/divergent/missing/dev-only/unknown), version_info в trace, route-регрессия |
| `tests/test_v020_deploy_stamp_ui.py` | 24 | deploy stamp (missing/ok/stale/hash-mismatch), `deployed_commit` в endpoint, copy plain/markdown/with-sources/no-trace, prompt-chips→меню «Примеры» |
| `tests/test_scope_model_v21.py` | 32 | Scope-резолвер (all/project/projects/dataset/datasets/mixed/legacy/filter-warning/scope>legacy); scope_options (админ-датасет/unassigned/system-reason/counts); scope в trace; document-prep labels |
| `tests/test_scope_clarification_v22.py` | 19 | §1 needs_project_scope and scope UI helpers remain, but chat no longer returns final `scope_clarification` for project questions at scope=all; `scope_all_for_project_query` is trace warning only, generic empty retrieval continues to model instead of code `NO_DATA` final |
| `tests/test_prompt_registry_service.py` | 5 | prompt registry: common/tone/mode prompts, smeta role-pack, editable prompt overrides, and no mode tool-contract injection into system prompt |
| `tests/test_module_router.py`, `tests/test_active_state.py`, `tests/test_scoped_rag.py`, `tests/test_skill_snippet_registry.py`, `tests/test_tool_trace_policy.py` | 23 | лёгкий LES core: module routing, active state as working memory, typed scoped evidence packet, short skill snippets instead of full skill injection, and transparent tool trace policy |
| `tests/test_tool_harness_service.py` | 5 | controlled tool-harness: typed read-only registry, indexed source search/read, PDF/Excel reader warnings, filesystem whitelist read/list/search/hash, and `/api/tools/call` dry-run |
| `tests/test_service_source_registry.py` | 3 | service-source registry and Play contract: required files/folders, canonical smeta/normcontrol sources, `SMETA_SERVICE` required-documents manifest with ready/partial/missing classes, and non-mutating operator messages |
| `tests/test_doc_review_retrieval.py` | 14 | doc-review retrieval-подфаза: факты project dataset отдельно от текста требования, явный нормативный SPDS RAG для ГОСТ Р 21.101-2026, запрет project fallback при настроенном нормативном источнике, legacy fallback только без найденного NTD |
| `tests/test_datasets_router.py` | focused | RAG dataset router/API: dataset CRUD, external in-place indexing, dataset-scoped parse drain, and transparent `external/intake-plan` preview (`+ папка`) with accepted/skipped counts, service map files excluded from preview and registration document counts, discipline hints, and missing inputs for downstream calculations |
| `tests/test_smeta_artifact_service.py` | 10 | smeta direct artifact layer: extracts model-written Markdown estimate tables, totals visible `Сумма/Стоимость` columns, keeps long model tables visible by default, keeps legacy compaction opt-in, and writes XLSX/CSV downloads without changing model-selected works |
| `tests/test_project_summary_inventory.py` | 5 | MetaDB `documents` inventory for dataset file registers, extension/folder grouping, inventory prompt context, `что это за датасет` inventory intent, and explicit inventory intent distinct from broad project summary |
| `tests/test_estimate_harness.py` | 74 | smeta model-first harness: norm search/tool loop, direct mass/volume slots, duplicate direct-quantity guard, scenario assumptions, Russian dialog state, norm applicability questions (`norm_questions`), and `search_norm.norm_navigation` for model-facing shortlist guidance |
| `tests/test_smeta_norm_store.py` | 7 | typed SQLite-light smeta norm projection over existing GESN/FSM/TER sources: schema payload, FTS/LIKE candidate search, norm-card profiles with hints/resources/condition_hints/provenance/model_card/navigation, nearby norms, worker-thread cached reads, no heavy row leak in trace |
| `tests/test_smeta_structured_base.py` | 2 | canonical smeta machine base: builds `data/smeta_base/les_smeta_base.sqlite` from unified GESN parquet, excludes norms without name/unit, writes manifest counts, and makes `gesn_service.load_base_norms()` prefer structured SQLite |
| `tests/test_gesn_update_pipeline.py` | 2 | smeta base update pipeline: FGIS download/unify now continues into structured SQLite and generated `SMETA_SERVICE` cards, with explicit skip flags for generated layers |
| `tests/test_smetnoedelo_rag_import.py` | 5 | Smetnoedelo API v2.0 → smeta RAG importer: section/code payload normalization, markdown card rendering, request-budget stop, manifest output, and token-free cache/card behavior |
| `tests/test_smeta_ru_norm_download.py` | 5 | Smeta.RU public norm ZIP downloader: HTML link extraction, archive metadata, latest selection, pattern filter, and manifest-only run without network download |
| `tests/test_smeta_ru_norm_rag_ingest.py` | 3 | Smeta.RU ZIP → RAG worker: latest archive selection, archive projection into `RAG_Content/TABLE_SMETA/SMETA_RU_NORM`, state-based skip of already processed archives |
| `tests/test_chat_harness_format.py` | 38 | smeta answer formatting and voice-layer guards: partial/final totals, hidden tool terms, model comments, model-selected tool-call JSON parsing/scoping, rejection of contradictions when calculated partial totals are visible, and no code-generated smeta answer on model failure |
| `tests/test_context_memory_service.py` | 9 | dataset/service notebooks including GESN collection map prompt excerpt, typed dataset memory context, warmup, and navigation-not-evidence behavior |
| `tests/test_dataset_memory_service.py` | 19 | typed dataset memory source guide: file cards, source layers, retrieval routes, source graph, `navigation_terms`, `dataset_topic_map_v1`, `dataset_section_map_v1`, `dataset_topic_selection_v1`, lexical heading use, operator guidance, `NTD_*` project docs not mislabeled normative, FSNB human roles, service-noise downrank, reader-pass storage |
| `tests/test_converter_process_isolation.py` | 11 | index-конвертация PDF/Excel: PDF/XLSX выбирают killable subprocess where needed, реальные PDF по умолчанию получают fast page-text baseline, timeout isolated PDF converter падает в page-text fallback вместо `ERROR`, fast PDF baseline не запускает дорогой global boilerplate regex, флаг отключения возвращает direct path, spreadsheet parser идёт до MarkItDown, реальный XLSX проходит через child process, timeout вызывает terminate, большой результат читается из queue до join, маленькие таблицы остаются полными, большие дают `spreadsheet_navigation_projection` |
| `tests/test_document_router.py` | 33 | document router: typed file-role/domain/pipeline routing, Smeta.RU norm archives as normative, raw CAD/BIM guards, project PDF with weak estimate words or internal СП/ГОСТ references stays general `DOCUMENT`/electrical material instead of `TABLE_SMETA`/`NORMATIVE`, while explicit estimate PDFs still route to `SMETA` |
| `tests/test_parse_pipeline_w14.py` | 8 | parse-конвейер: стадии, prefetch/timeout/resume, сохранение границы delete-after-convert, и raw CAD/BIM не становится ложным `INDEXED 0` |
| `tests/test_qdrant_adapter_parse.py` | 21 | parse/Qdrant adapter: pending-safety, legacy/exact file matching, count mismatch cleanup, vector hash cache, sparse reconcile, unbounded parse guard, PDF page-text nodes carry page/page_part payload, spreadsheet nodes carry `type=spreadsheet_projection`, and large parquet row sets become `table_navigation_projection` instead of row-chunk floods |
| `tests/test_drawing_manifest_service.py` | 10 | MVP паспорта листа чертежа: PDF A4/A0 geometry, правая нижняя зона штампа, positioned text blocks, object/address/volume/cipher candidates with provenance, structural/text/graphical stamp parsing, semantic cipher split `ИОС.ЭС.ПЗ`, `Содержание тома` register rows, cp1251 mojibake repair, batch `cipher_norm` registry grouping, and scan/textless pages staying unknown instead of fake extraction |
| `tests/test_electrical_schematic_service.py` | 7 | electrical single-line/load reader: словарь расчёта нагрузок (`Руст/Pуст`→`p_installed_kw`, `Рр/Pр`→`p_calc_kw`, `Iр`→`i_calc_a`, `L/длина`→`cable_length_m`), типовая 11-колоночная таблица расчёта нагрузок с `Pр/Qр/Sр/Iр`, защита `РУ` как panel от путаницы с `Ру`/словами вроде `ручки`, extraction text nodes/vector lines/candidate circuit from synthetic one-line PDF, `cable_length_m` from scheme labels, and blank PDF stays unknown |
| `tests/test_electrical_materials_service.py` | 7 | electrical VOR/SO material reader: normalized `Поз/Наименование/Ед./Кол-во` rows, PDF mojibake repair for SO tables, cable mark/cores/section/`quantity_m`, section tracking, lighting classification, VOR/SO `doc_role`, work action, IP/current/single+multi-voltage/power, height, cable diameter, dimensions and mass attributes, `КунРс Внг(А)-FRLS` cable marks without `кг/м` false-positive, and guardrails so шинопровод/кабельная розетка do not become cable rows |
| `tests/test_electrical_evidence_summary_service.py` | 4 | electrical evidence summary: load aggregates by panel, panel hint from load-table file name, cable inventory/matching against material rows, SO→draft-VOR seed rows, issue counts with capped examples, and guard that gap rows are model navigation rather than a design/code verdict |
| `tests/test_pd_rd_manifest_service.py` | 2 | PD/RD source-map: многостраничное `Содержание тома`, `Состав проектной документации`, `Оглавление` ПЗ, declared total sheets, glyph mojibake repair `ɋɉ`→`СП`, and `ПЗ` kept as document kind/navigation rather than domain answer logic |
| `tests/test_cad_bim_extract_dxf.py`, `tests/test_cad_bim_aggregate_w61.py`, `tests/test_cad_bim_import_inventory.py`, `tests/test_retrieval_service.py` | focused additions | CAD/BIM DWG input uses LibreDWG conversion before canonical graph build, repairs broken DXF group-code lines from real DWG output, JSON-sanitizes surrogate text, reconstructs drawn CAD tables from line/polyline grids plus text, and renders `CAD drawn tables`, first-position anchors, logical position rows, and compact row text before element noise; import inventory marks weak/minimal imports, duplicate source groups, and duplicate indexed projections; retrieval promotes exact source/projection/import-id hits and first ordinal table chunks after rerank, selecting CAD first-position chunks by actual `position N` before `chunk_ord`, so a precise CAD source or beginning of a target-file table is not hidden by a larger similar projection |
| `tests/test_saferag_service.py` | 12 | SafeRAG context/source helpers: lexical rank boost, source concentration, low raw-score lexical matches, protected opened documents, deduplicated copied docs, context builders and source-name order |
| `tests/test_static_assets.py` | 6 | статическая проводка UI: вкладки «Инструменты»/«Документы», topic/section map в Documents UI, CAD inventory panel + target_file deep-link, Qdrant visualizer static mount, разрешения deploy для shell |
| `tests/test_mermaid_graph.py` | 2 | live graph payload `/api/rag/graph/full` renders into Mermaid and empty graph is explicit |
| `tests/test_proxy_security.py`, `tests/test_proxy_routers.py` | 43 focused with Sovushka | trust/auth guardrails: ZeroTier/trusted admin, API-key roles, protected `les-admin-` root-admin keys without device binding, and trusted-only mutation of protected keys |
| `tests/test_sovushka_chat.py` | 30+ | Sovushka chat/UI regressions: markdown rendering, new-chat/model-chip/table wrapping, editable prompt controls, attachment context, no project-summary final hijack, additive MetaDB inventory context, clickable file-register RAG, selected-dataset file panel, Samovar parse/play slot-context guard, scheduler-start endpoint guard, WAITING-vs-PARSING status, and file-layer labels |

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

1. `HARNESS_VERSION` в `version_service.py` поднят (двигать КАЖДУЮ версию).
2. `make verify` зелёный.
3. Профильные тесты версии + регрессия зелёные.
4. Deploy stamp пишется на `--apply` (или вручную `write_deploy_stamp` при cp).
5. `docs/releases.md` обновлён (commit для отката).
