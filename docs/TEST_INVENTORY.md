# TEST_INVENTORY — тесты Unified Construction Harness v0.16–v0.24

Гейт: `make verify` (офлайн, синтаксис+импорт-смоук). Полная сюита: `uv run python -m pytest tests/ -q` (~2462 тестов).
Все тесты ниже офлайн (без живых Qdrant/MLX), flag `LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED` OFF.

**Профильные таблицы v0.16–v0.22: 230 тестов** (+ регрессия v0.3–v0.15 и chat/router при OFF). `make verify` на h0.24 собирает **2462 теста**.

| Файл | Тестов | Покрывает |
|---|---:|---|
| `tests/test_answer_render_v16.py` | 26 | render-хелперы Совушки: strip markdown из ячеек, source-chips, evidence-секции, citation/conflict-блоки, citation drawer payload, compact trace включая topic-guided retrieval, `answer_copy_text` (Копировать без trace/тела письма) |
| `tests/test_sidecar_ops_v16.py` | 50 | sidecar-операции: инвентарь датасетов, heading-классификатор, extraction-state (7 кейсов), lexical `extracted_fts`, OCR-детект, `run_extraction`/`extract_body_op` (gate env+confirm), originals read-only (shasum), legacy `.xls` |
| `tests/test_route_and_runtime_v17.py` | 34 | runtime alignment (extract-эндпоинты зарегистрированы), route-fix «реестр документации» ≠ глобальный реестр, doc_type_classifier, honest `.xls`, регрессии v0.3–v0.16 |
| `tests/test_deterministic_policy_v18.py` | 27 | DeterministicFinalPolicy: glossary-final только при литеральном термине, registry только глобальный, source-scoped/descriptive→reject; «расскажи про котельную»≠ОЖР; ОЖР/КАЦ/ЛСР работают |
| `tests/test_version_service_v19.py` | 23 | `/api/version` 200, no-secrets, git-unavailable-safe, runtime_alignment (aligned/divergent/missing/dev-only/unknown), version_info в trace, route-регрессия |
| `tests/test_v020_deploy_stamp_ui.py` | 24 | deploy stamp (missing/ok/stale/hash-mismatch), `deployed_commit` в endpoint, copy plain/markdown/with-sources/no-trace, prompt-chips→меню «Примеры» |
| `tests/test_scope_model_v21.py` | 32 | Scope-резолвер (all/project/projects/dataset/datasets/mixed/legacy/filter-warning/scope>legacy); scope_options (админ-датасет/unassigned/system-reason/counts); scope в trace; document-prep labels |
| `tests/test_scope_clarification_v22.py` | 18 | §1 needs_project_scope (проектные→clarify, нормы/глоссарий→allowed), scope_clarification + suggest_project, ScopeSelector wiring, scope→payload |
| `tests/test_prompt_registry_service.py` | 5 | prompt registry: common/tone/mode prompts, smeta role-pack, editable prompt overrides, and no mode tool-contract injection into system prompt |
| `tests/test_module_router.py`, `tests/test_active_state.py`, `tests/test_scoped_rag.py`, `tests/test_skill_snippet_registry.py`, `tests/test_tool_trace_policy.py` | 23 | лёгкий LES core: module routing, active state as working memory, typed scoped evidence packet, short skill snippets instead of full skill injection, and transparent tool trace policy |
| `tests/test_smeta_fast_answer_service.py` | 4 | smeta visible fast fallback: СКС line-item RIM scenario, XLSX package-length parsing, ярусная quantity split without machine status leakage, and `_smeta_direct_model_answer` fallback after timeout |
| `tests/test_smeta_artifact_service.py` | 3 | smeta direct artifact layer: extracts model-written Markdown estimate tables, totals visible `Сумма/Стоимость` columns, compacts long tables in chat, and writes XLSX/CSV downloads without changing model-selected works |
| `tests/test_project_summary_inventory.py` | 5 | MetaDB `documents` inventory for dataset file registers, extension/folder grouping, inventory prompt context, and explicit inventory intent distinct from broad project summary |
| `tests/test_estimate_harness.py` | 74 | smeta model-first harness: norm search/tool loop, direct mass/volume slots, duplicate direct-quantity guard, scenario assumptions, Russian dialog state, norm applicability questions (`norm_questions`), and `search_norm.norm_navigation` for model-facing shortlist guidance |
| `tests/test_smeta_norm_store.py` | 7 | typed SQLite-light smeta norm projection over existing GESN/FSM/TER sources: schema payload, FTS/LIKE candidate search, norm-card profiles with hints/resources/condition_hints/provenance/model_card/navigation, nearby norms, worker-thread cached reads, no heavy row leak in trace |
| `tests/test_smetnoedelo_rag_import.py` | 5 | Smetnoedelo API v2.0 → smeta RAG importer: section/code payload normalization, markdown card rendering, request-budget stop, manifest output, and token-free cache/card behavior |
| `tests/test_smeta_ru_norm_download.py` | 5 | Smeta.RU public norm ZIP downloader: HTML link extraction, archive metadata, latest selection, pattern filter, and manifest-only run without network download |
| `tests/test_smeta_ru_norm_rag_ingest.py` | 3 | Smeta.RU ZIP → RAG worker: latest archive selection, archive projection into `RAG_Content/TABLE_SMETA/SMETA_RU_NORM`, state-based skip of already processed archives |
| `tests/test_chat_harness_format.py` | 19 | smeta answer formatting and voice-layer guards: partial/final totals, hidden tool terms, model comments, and rejection of contradictions when calculated partial totals are visible |
| `tests/test_context_memory_service.py` | 9 | dataset/service notebooks including GESN collection map prompt excerpt, typed dataset memory context, warmup, and navigation-not-evidence behavior |
| `tests/test_dataset_memory_service.py` | 18 | typed dataset memory source guide: file cards, source layers, retrieval routes, source graph, `navigation_terms`, `dataset_topic_map_v1`, `dataset_section_map_v1`, `dataset_topic_selection_v1`, lexical heading use, operator guidance, FSNB human roles, service-noise downrank, reader-pass storage |
| `tests/test_saferag_service.py` | 12 | SafeRAG context/source helpers: lexical rank boost, source concentration, low raw-score lexical matches, protected opened documents, deduplicated copied docs, context builders and source-name order |
| `tests/test_static_assets.py` | 5 | статическая проводка UI: вкладки «Инструменты»/«Документы», topic/section map в Documents UI, deep-link «Спросить по теме», разрешения deploy для shell |
| `tests/test_proxy_security.py`, `tests/test_proxy_routers.py` | 43 focused with Sovushka | trust/auth guardrails: ZeroTier/trusted admin, API-key roles, protected `les-admin-` root-admin keys without device binding, and trusted-only mutation of protected keys |
| `tests/test_sovushka_chat.py` | 30+ | Sovushka chat/UI regressions: markdown rendering, new-chat/model-chip/table wrapping, editable prompt controls, attachment context, no project-summary final hijack, additive MetaDB inventory context, clickable file-register RAG, selected-dataset file panel, Samovar parse/play slot-context guard, scheduler-start endpoint guard, WAITING-vs-PARSING status, and file-layer labels |

## Ключевые «живые» доказательства (на рантайме :8050)

- **844a2b53 / e19cc409** — approved sidecar write: 27 / 22 sidecar, оригиналы байт-в-байт целы (shasum); extracted_body отвечает по ГОСТ/СП с source_ref до `.docx#para`.
- **resource workbook** — `ПРИМЕР_обсчета_24_06.xlsx` валидирован кодом: grand total **16 827 283.19 ₽**, line_diffs=0.
- **route**: «расскажи про котельную»@all→`scope_clarification`; @project→RAG; «что такое ОЖР»→glossary; «реестр документации»≠глобальный.
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
