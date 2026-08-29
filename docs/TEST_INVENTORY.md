# TEST_INVENTORY — карта тестов Л.Е.С.

> **0.29.0 private model/promotion closure:** canonical `make test`, `make
> verify` collection и portable platform gate теперь постоянно включают все
> model-connection tests: immutable registry, endpoint/DNS/peer security,
> secrets, capability snapshots, resolver, transport, chat/embedding binding,
> API/UI, candidate workbook acceptance, read-only extensions, append-only
> promotion и hermetic contract нового opt-in model-only runner.
> `tests/test_canonical_promotion_service.py` доказывает, что только
> exact live 9B report + текущие commit/build/preset/model дают effective
> `active`; drift остаётся `shadow`. `test_model_engine_extension_service.py`
> дополнительно проверяет endpoint revalidation до status HTTP request. Fresh
> Build 626 дополнительно проверяет exact revision resolution, upstream
> response model identity, redacted chat/SSE/tools/context receipt и Windows
> `full | backend | ui` ownership/CLI/PowerShell contracts. Fresh build 626
> current gate: **920 passed / 5 warnings**, `make verify`: **920 collected**.

> **0.29.0 model-connections API (build 611):**
> `tests/test_model_connections_router.py` проверяет user/admin boundary,
> safe effective redaction, append-only create/revise, stale CAS 409, unsafe
> endpoint 422 до записи, explicit capability selection, masked server-owned
> secret replacement, bound-disable confirmation, templates без credentials и
> регистрацию router в приложении. Совместный API/registry/security/secret/
> capability/resolver/transport/chat gate: **81 passed**.

> **0.29.0 bound chat and Windows-safe gates (build 610):**
> `tests/test_model_connection_chat_integration.py` и расширенные chat/
> architecture/runtime tests проверяют exact answer/fallback revisions,
> zero-call shadow, consent по locality, безопасную provenance, governed memory,
> один canonical tool call и запрет engine-name routing в нейтральных сервисах.
> Все pytest-профили `Makefile` теперь сами задают отдельный workspace-local
> `.test-tmp/<profile>`; регрессия закреплена в `tests/test_test_profiles.py`,
> поэтому обычный `make test` не зависит от Windows `%TEMP%`. `make verify`:
> **722 collected**; `make test`: **722 passed**.

> **0.29.0 governed context and preset parity (build 603):**
> `tests/test_model_execution_preset_service.py`,
> `test_context_governor_service.py`, `test_typed_memory_projection_service.py`,
> `test_model_preset_workflow_parity.py` и chat integration проверяют один
> governed inference path. Parity test сравнивает реальные model-visible tool
> payloads (schema/effect/approval включительно), порядок context objects и
> одну typed advisory-memory projection в пакетах 9B/35B; различаться обязаны только
> числовые capacity limits. Эти новые suites включены в постоянный `make test`,
> а не оставлены отдельной ручной командой. Полный current behavior gate:
> **717 passed**; `make verify` собрал **717 тестов**. Это offline contract
> evidence, не проверка качества живой модели и не release promotion.

> **0.29.0 Agent Foundation (build 598):**
> `tests/test_architecture_contract_gate.py`, `test_tool_contract_service.py`,
> `test_tool_registry_service.py`, `test_capability_broker_service.py`,
> `test_trusted_executor_service.py`, `test_tool_harness_service.py`,
> `test_tool_trace_policy.py`, `test_canonical_route_service.py`,
> `test_chat_evidence_application_service.py`, profile/runtime/harness tests и
> runtime-config registry образуют focused foundation gate: **181 passed**.
> Сквозной chat-test использует настоящий TrustedExecutor и SQLite persistence
> probe, проверяя one-call shadow, exact Broker context, legacy answer/history и
> продолжение после redacted candidate exception. Полный current behavior gate:
> **681 passed** с workspace-local `--basetemp`; это исторический checkpoint.

> **0.27.77 ordinary smeta RAG and physical KV:**
> `tests/test_publish_smeta_norm_dataset.py` фиксирует read-only card rendering
> и unified point payload; `tests/test_system_dataset_service.py` — стабильный
> `SMETA_NORMS_Index`; UI-тесты запрещают отдельные RIM/smeta controls.
> `tests/test_freetoken_provider.py` воспроизводит physical cache rebuild
> `8226 → 30000`, а settings tests показывают desired/effective state без живой
> внешней мутации.

> **0.27.76 FreeToken capacity:** `tests/test_freetoken_provider.py` защищает
> вывод prompt ceiling из GUI-owned token window (`8253 → 14106`,
> `30000 → 57600`), сохранение multi-document evidence и явного override.
> `tests/test_source_excerpts.py` запрещает возврат provider-specific лимита
> четырёх чанков/5000 символов; `tests/test_sovushka_chat.py` фиксирует порядок
> dialogue memory → evidence → tools. `tests/test_proxy_routers.py` проверяет,
> что Совушка показывает тот же derived effective value.

> **0.27.75 FreeToken SSE:** `tests/test_freetoken_provider.py` воспроизводит
> живой формат `delta.reasoning_content` от
> `Qwen3.6-35B-A3B-NVFP4`; общий transport parser обязан вернуть текст вместо
> ложного `Пустой ответ LLM (stream=True)`. Смежные проверки
> `tests/test_reasoning_answer.py` и `tests/test_chat_stream_w51.py` защищают
> non-stream reasoning и клиентский SSE-контракт.

> **0.27.74 reranker-free general RAG:** `tests/test_retrieval_service.py`
> защищает native-RRF evidence и его исходный порядок при выключенном reranker,
> а `tests/test_installer_windows.py` фиксирует безопасный Windows default
> `RERANKER_ENABLED=false`.
> `tests/test_rag_golden_set.py` защищает release-smoke contract: mode
> `qdrant_native_hybrid`, оба Qdrant-канала, допустимый lexical safety merge и
> `rerank.status=bypassed` с сохранённым native-RRF порядком.
> `tests/test_test_profiles.py` фиксирует post-deploy порядок native-RRF smoke и
> узкий `DEPLOY_FORCE_FILES`, который выполняется до обычного restart/stamp deploy.
> Тот же contract не позволяет pre-deploy `ship-check` проверять stale live runtime;
> basic HTTP release smoke обязан находиться после candidate deploy.
> Dry-run contract также требует bounded `post-deploy-rag-smoke` retry, защищая
> Windows startup window без ослабления финального native-RRF результата.

> **0.27.73 smeta retrieval probe:**
> `tests/test_smeta_retrieval_recall_probe.py` защищает active-base embedding
> contract и строгую/нестрогую трактовку retrieval cases. Живая диагностика
> `tools/smeta_retrieval_recall_probe.py` измеряет top-k без LLM, reranker и
> каталожного маршрута и явно показывает, работал ли Qdrant hybrid или только FTS.

> **0.27.66 source links:** `tests/test_answer_render_v16.py`,
> `tests/test_source_excerpts.py`, `tests/test_document_explorer_service.py` и
> `tests/test_sovushka_chat.py` защищают `source_map.doc_id`, raw-доступ по стабильной
> identity, точную PDF-страницу, кликабельные строки и единый артефакт без legacy-дубля.
> Тот же render-contract удаляет видимые inline-LaTeX `$...$`, не затрагивая escaped currency.
>
> **0.27.65 public smeta sync:** `tests/test_smeta_core.py` защищает XLSX intake
> с заголовком `Ко-во` ниже длинной договорной шапки и bounded terminal
> candidate promotion; `tests/test_smeta_chat_application_service.py` покрывает
> local Ollama/Qwen scoped fast-profile и soft-continue; `tests/test_smeta_norm_browser.py`
> проверяет сохранение исходного порядка при недоступном reranker.

> **0.27.35 PR #8 acceptance contracts:**
> `tests/test_ks_forms_service.py` covers project isolation, draft status,
> confirmed KS-6а input, MCP/chat output and XLSX formula safety;
> `tests/test_rim_coverage_header.py` protects the partial-total warning;
> `tests/test_smeta_chat_application_service.py` covers compact Qwen retry and
> harmless JSON repair; `tests/test_les_runtime_control.py` protects the
> LES-owned Windows stop boundary. These tests are part of `CURRENT_TESTS`.

> **0.27.34 focused contracts:** `tests/test_smeta_core.py` covers bounded
> candidate-draft repair versus hard unit/reference failures;
> `tests/test_smeta_memory_isolation.py` proves candidate drafts are not
> captured; `tests/test_memory_core.py` proves smeta advisory appears only
> after explicit confirmation and never crosses projects.

Общая диагностическая suite сохранена как `make test`. На 2026-07-29 она собирает
**2808 тестов** и даёт
**2799 passed / 9 skipped**. Прямой
`uv run pytest` использует тот же default из `pytest.ini`. Физический total включает также
архивные и отдельные продуктовые профили;
архивный Unified запускается только через `make test-legacy`, а ARTEL — в отдельном продукте.
`make test-mail` отдельно содержит **66 тестов**.

`tests/test_artel_packaging.py` проверяет только границу продуктов: pinned
Agnostis submodule, отсутствие tracked build outputs и LES↔ARTEL integration
contracts. Это не release-gate самостоятельного ARTEL и не переносит его
сборочную ответственность обратно в LES.

`tests/test_checklist_*.py` и `tests/test_pp87_composition.py` проверяют импорт
ПД/РД, evidence-guard, параметры, API/persist/report и UI-view checklist-review.
Исторический checklist-chat не входит в активный контур и не может вернуть
готовый ответ за модель.

`tests/test_http_client_policy.py` проверяет scoped proxy-env contract:
loopback всегда идёт напрямую, внешние/LAN/ZeroTier URL не лишаются proxy,
а критические внутренние `httpx`-клиенты используют общий helper.

Для updater общая suite **запрещена**: prepare/apply не вызывают `make test`, `make verify`,
Tauri build или baseline. Единственный offline-гейт этого слоя — `make test-updater`; нативная
Windows-приёмка после ручной установки — `tools/windows_updater_smoke.ps1`, максимум 90 секунд.
`make test` пока остаётся только явной диагностикой других модулей до отдельной переработки
архитектуры тестов.

Архитектурный разбор и список исторического долга:
[TEST_ARCHITECTURE_AUDIT_2026-07-14.md](TEST_ARCHITECTURE_AUDIT_2026-07-14.md).

- `make test` / `make test-release` — канонический LES-профиль без 11 файлов выключенного
  Unified/Construction Harness и без `test_artel*` (запуск через `tools/test_runner.py all`);
- `make test-unit` — быстрые hermetic unit-проверки чистых контрактов/вычислений (`tests/test_unit_core_business.py` и профильные модули);
- `make test-smoke` — быстрый герметичный офлайн smoke-набор (`tests/test_smoke_offline.py`, FastAPI TestClient, health, version, status, scope, scenario);
- `make test-coverage` — запуск тестов с формированием отчёта о покрытии (`artifacts/coverage_report.txt` и `artifacts/coverage.json`);
- `make test-ci` — запуск проверок в режиме CI с генерацией XML отчёта (`artifacts/junit-report.xml`);
- `make test-integration` — 120 поведенческих проверок временных SQLite/API/release-артефактов,
  включая atomic smeta rebuild, batch rerank и полный table listing;
- `make smoke-smeta-rerank` — живой hybrid+rerank gate: требует совместимые dense+sparse/RRF,
  успешный cross-encoder и содержательные anchors в видимом top-3; один `rerank_status=ok`
  больше не считается качеством;
- `make test-architecture` — совместимый псевдоним того же профиля;
- `make test-legacy` — только явный opt-in запуск 288 исторических проверок; не release-доказательство;
- `make test-mail` — 66 offline/static проверок Е.Ж.И.К.: отдельный dataset на ящик,
  IMAP/registry/cursors/dedup, mail projection/API/UI и Windows-sidecar source contract;
- `make test-mail-release` — `test-mail` плюс Rust compile-check Tauri. Он обязателен в
  `make patch-release`, но не подменяет установленный Outlook COM/task/index/open smoke на Legion;
- `make test-updater` — короткий hermetic behavior-профиль Mac/Windows (текущий gate: 127 тестов):
  hard whole-tree replace/rollback/state boundary, soft manifest/base/target/archive
  SHA, атомарная замена runtime и `les-desktop.exe`, shell attestation, release
  identity/API/UI contract и Mac updater. Никаких build/baseline/общей suite;
- `make test-release-critical` — совместимый псевдоним `make test-integration`;
- `make test-rag-core` — короткий обязательный RAG integrity-профиль;
- `make test-legacy-full` — прежний repository-wide 3204-test прогон, только
  opt-in диагностика; не release evidence;
- `make smoke-active-artifacts` проверяет фактические active base/FSEM, SHA/count/provenance;
- `make smoke-smeta-rerank` — fail-closed A/B живой цепочки active base → Qdrant/RRF → reranker;
- `make smoke-basic-release` — живой HTTP/UI/product smoke. Эти проверки не подменяются зелёным pytest.
- `platform-gate` — исторический полный release-контур, не гейт application updater: одинаковый на Mac и Windows переносимый набор поведенческих unit/integration
  проверок, фактическая проверка комплектной сметной базы и нативная Tauri-сборка; отдельно
  добавляет проверки установщика соответствующей ОС. До переработки тестовой архитектуры этот
  тяжёлый контур не запускается updater-командами;

RAG-ядро имеет отдельный обязательный профиль `make test-rag-core`; offline defaults задаются в
`tests/conftest.py`. Аудит достоверности гейтов: [RAG_TEST_PROGRAM_AUDIT.md](RAG_TEST_PROGRAM_AUDIT.md).

Ниже сохранена подробная карта профильных наборов. Строки v0.16–v0.24 являются исторически
сложившимися именами файлов, а не текущей версией архитектуры.

| Файл | Тестов | Покрывает |
|---|---:|---|
| `tests/test_tauri_desktop.py` (Windows startup additions), `tests/test_windows_prebundle_smoke.py`, `tests/test_mutable_path_architecture.py` | focused + live prebundle | provider-neutral role catalogue, external-engine warnings that do not block core, setup-button bootstrap lock, offline tokenizer startup, dependency-only cache fingerprint with full offline sync proof, Programs-shaped pre-NSIS API/UI/process smoke, isolated state/cleanup and architecture ban on application-tree mutable writes |
| `tests/test_installer_windows.py::test_qdrant_payload_indexes_do_not_block_api_startup` | focused | Qdrant filter indexes remain `wait=false` and run outside `_ensure_collection()` startup await path |
| `tests/test_dataset_integrity.py`, integrity cases in `tests/test_datasets_router.py` | focused + live dataset | Полная связность одного датасета: исходные файлы/fingerprint, MetaDB status, exact Qdrant point ids, named dense+sparse, lexical rows/FTS, PDF page coverage и index contract; repair переочередит только повреждённые документы и не трогает здоровые |
| `tests/test_release_classification.py`, `tests/test_github_patch_release.py`, `tests/test_vps_patch.py`, `tests/test_windows_application_update.py`, `tests/test_windows_update_shell.py`, `tests/test_update_service.py`, `tests/test_manual_update_ui.py` | `make test-updater` | GitHub lightweight/full classification, exact immutable five-asset release, clean pushed commit/tag/feed binding, isolated apply/skipped-version/rollback; Windows hard + soft updater: full app-tree rollback, exact identity/SHA, runtime allowlist, bounded console-free processes и отдельные UI/API пути |
| `tests/test_installer_windows.py`, `tests/test_tauri_desktop.py`, `tests/test_install_les.py`, `tests/test_software_versions.py`, `tests/test_patch_release.py`; `.github/workflows/{verify,release}.yml`; live `tools/windows_{release_smoke,production_deploy}.ps1` | portable + Windows live | проверяет SHA-256 portable Python/uv, `requires-python >=3.12,<3.14`, exact lock/cache, lock-bound venv marker и отсутствие повторного sync. Installed smoke делает два запуска одного state: первый без Docker обязан дать core API/UI + capability warnings, второй — `environment_action=skipped`, затем exact version/process/index/native-RRF contract без изменения пользовательского RAG |
| `tests/test_chat_mail_query.py`, `tests/test_converter_email.py`, `tests/test_ezhik_imap_smoke.py`, `tests/test_mail_*.py`, `tests/test_outlook_mail_poller.py` | `make test-mail`: 66 | Е.Ж.И.К.: один IMAP/Outlook ящик = отдельный dataset; secret-vault boundary; Message-ID/native/SHA dedup; multiple locations и snapshot retention; UIDVALIDITY reset; read-only `BODY.PEEK[]`; cursor после каждого registered UID; failure mid-batch; inline CID exclusion; attachment SHA-256/20-MB MISSING; account API, legacy compatibility, UI и Windows packaging contract |
| `tests/test_outlook_mail_poller.py`, `tests/test_mail_router.py`, `tests/test_patch_release.py`; cross-platform `platform_release_gate`; Windows live gate | unit/static + native Windows compile/self-test + live | Classic Outlook sidecar recursively visits stores/folders, excludes Deleted/Drafts/Junk by identifiers, saves Unicode MSG и opens exact original. Per-folder cursor persists `backfill_complete`; каждый ручной проход ограничен 10 снимками/12 секундами и независимым hard-stop 15 секунд. Root-admin loopback API запускает installed interactive EXE напрямую без UAC; private mailbox делает статус ready без legacy `MAIL_Index`; release smoke не регистрирует user-wide Outlook task. Unit с заблокированным backend и отдельный intake unit доказывают durable raw+manifest до exact registry/RAG; spool возобновляется после рестарта. Static/self-test не заменяют COM probe, idempotent repeat, INDEXED, фактическую duration и original-opening smoke на Legion |
| `tests/test_smeta_model_quality_benchmark.py` | 5 | offline-контракт честного Qwen/Gemma A/B: явные model profiles, строгая совместимость manifest при `--resume-run`, одинаковый изолированный Ollama env с восстановлением, calculated/partial/missing, stage latency, tool calls/repeats, route/unit/volume/provenance integrity и qrels-only профессиональная оценка |
| `tests/test_local_inference_benchmark.py` | 8 | офлайн-контракт direct OpenAI benchmark и OptiQ probe: p50/p95, usage/cache normalization, MTP summary, tool/prefix profiles, sampler forwarding и чтение per-request telemetry JSONL; live model-series запускаются отдельно через `tools/local_inference_benchmark.py` + `tools/optiq_mtp_probe_server.py` |
| `tests/test_answer_render_v16.py` | focused | render-хелперы Совушки: strip markdown из ячеек, source-chips и usage `used/found/weak`, громкий degraded/blocked notice, evidence-секции, citation/conflict-блоки, citation drawer payload, PDF page/bbox и DOCX/XLSX locator deep-links, compact trace и `answer_copy_text` |
| `tests/test_mac_update.py` | `make test-updater` | Mac-only internal updater: archive/helper SHA-256, runtime allowlist, base compatibility, атомарная замена, recovery copy и обязательный rollback при провале smoke без build/test |
| `tests/test_files_router_w181.py`, `tests/test_file_viewer_service.py` | 15 + 11 | allowlisted read-only file routes и `list.file_viewer.v1`: prefixed `RAG_Content` refs, PDF info/preview/bbox, unified PDF/DOCX/XLSX viewer, Office locator/order, HTML escaping, PPTX slide text, EML plain body, legacy DOC/XLS honesty |
| `tests/test_sidecar_ops_v16.py` | 32 | sidecar-операции: инвентарь датасетов, heading-классификатор, extraction-state, lexical `extracted_fts`, OCR-детект, `run_extraction`/`extract_body_op` (gate env+confirm), originals read-only, legacy `.xls`; агрегатные вызовы v0.3–v0.15 удалены |
| `tests/test_route_and_runtime_v17.py` | 20 | runtime alignment (extract-эндпоинты зарегистрированы), route-fix «реестр документации» ≠ глобальный реестр, doc_type_classifier, honest `.xls`; цепочка повторных `test_vNN_*` удалена |
| `tests/test_deterministic_policy_v18.py` | 27 | DeterministicFinalPolicy: glossary-final только при литеральном термине, registry только глобальный, source-scoped/descriptive→reject; professional-domain candidates (`smeta/asbuilt/doc_registry/field`) не становятся final-ответом кода |
| `tests/test_version_service_v19.py` | 22 | `/api/version` 200, no-secrets, git-unavailable-safe, runtime_alignment (aligned/divergent/missing/dev-only/unknown), version_info в trace, route-регрессия |
| `tests/test_v020_deploy_stamp_ui.py` | 23 | deploy stamp (missing/ok/stale/hash-mismatch), `deployed_commit` в endpoint, copy plain/markdown/with-sources/no-trace, prompt-chips→меню «Примеры» |
| `tests/test_scope_model_v21.py` | 34 | Scope-резолвер (all/project/projects/dataset/datasets/mixed/legacy/filter-warning/scope>legacy); scope_options (админ-датасет/unassigned/system-reason/counts, human display name и chunk count системной базы); scope в trace; document-prep labels |
| `tests/test_scope_clarification_v22.py` | 19 | §1 needs_project_scope and scope UI helpers remain, but chat no longer returns final `scope_clarification` for project questions at scope=all; `scope_all_for_project_query` is trace warning only, generic empty retrieval continues to model instead of code `NO_DATA` final |
| `tests/test_prompt_registry_service.py` | focused | prompt registry: common/tone/mode prompts, smeta role-pack, editable prompt overrides, plus live native-smеta loading of the GESN/typed-storage reference |
| `tests/test_chat_profile_service.py`, `tests/test_profiles_router.py`, `tests/test_chat_profile_runtime.py`, `tests/test_profiles_ui.py` | focused | immutable Factory Base/user revisions, active/per-chat snapshot, prompt 16 000 + skill 8 000 authoritative server limits/schema, readable legacy oversized revisions, UI counters/disabled over-limit save, tool allowlist и model/RAG policies |
| `tests/test_module_router.py`, `tests/test_active_state.py`, `tests/test_scoped_rag.py`, `tests/test_skill_snippet_registry.py`, `tests/test_tool_trace_policy.py` | 23 | лёгкий LES core: module routing, active state as working memory, typed scoped evidence packet, short skill snippets instead of full skill injection, and transparent tool trace policy |
| `tests/test_tool_harness_service.py`, `tests/test_web_search_service.py` | focused | controlled tool-harness: typed read-only registry, indexed source search/read, PDF/Excel reader warnings, filesystem whitelist read/list/search/hash, bounded public web titles/snippets/direct URLs, Agent shortlist and `/api/tools/call` dry-run |
| `tests/test_service_source_registry.py` | 4 | service-source registry and Play contract: required files/folders, canonical smeta/normcontrol sources, `SMETA_SERVICE` required-documents manifest, non-mutating operator messages, and normative base quarantine when semantic integrity report is absent |
| `tests/test_doc_review_retrieval.py` | 14 | doc-review retrieval-подфаза: факты project dataset отдельно от текста требования, явный нормативный SPDS RAG для ГОСТ Р 21.101-2026, запрет project fallback при настроенном нормативном источнике, legacy fallback только без найденного NTD |
| `tests/test_datasets_router.py` | focused | RAG dataset router/API plus retrieve-debug integrity: debug fields are exact projections of chunks and cannot inject FIRE/HVAC expected terms |
| `tests/test_smeta_artifact_service.py` | 10 | smeta direct artifact layer: extracts model-written Markdown estimate tables, totals visible `Сумма/Стоимость` columns, keeps long model tables visible by default, keeps legacy compaction opt-in, and writes XLSX/CSV downloads without changing model-selected works |
| `tests/test_project_summary_inventory.py` | 5 | MetaDB `documents` inventory for dataset file registers, extension/folder grouping, inventory prompt context, `что это за датасет` inventory intent, and explicit inventory intent distinct from broad project summary |
| `tests/test_estimate_harness.py` | 74 | smeta model-first harness: norm search/tool loop, direct mass/volume slots, duplicate direct-quantity guard, scenario assumptions, Russian dialog state, norm applicability questions (`norm_questions`), and `search_norm.norm_navigation` for model-facing shortlist guidance |
| `tests/test_smeta_core.py`, `tests/test_smeta_professional_review.py`, `tests/test_smeta_agent_runners.py`, `tests/test_smeta_chat_application_service.py`; live `tools/smeta_document_live_smoke.py` | focused + live model/XLSX | smeta-core boundaries: code cannot own norm binding; bind requires selected/applicable; invalid model output never falls back to top candidate; append-only row/global/user-lock revisions; conflict-validator не меняет решения и флагирует возможный cross-row double count; раздельный evidence budget; `unbound_evidence` обязан ссылаться на фактический tool trace; local Ollama/Qwen and FreeToken use one-row batches with durable resume; FreeToken agent tool turns reserve at most 1024 output tokens inside its shared KV budget, and terminal mapping is a forced same-model tool-call without unsupported `response_format`; Qwen ordinary-text получает same-model terminal recovery; обязательный model-owned cross-row review; автoрасчёт остаётся draft; финальный расчёт требует user lock; wrong-bind/unbound/coverage/unopened-card/unit/resource/price metrics; live smoke требует real ВОР→model tools→non-empty XLSX без fallback |
| `tools/freetoken_context_probe.py` | isolated live transport | FreeToken own-tokenizer input sizing + exactly one forced tool call; proves prompt+tools+generation KV capacity without loading a dataset or starting the smeta document workflow |
| `tests/test_rim_*.py`, `tests/test_sovushka_uikit.py` | focused + isolated Mac UI/live model smoke | persistent owner-scoped RIM sessions and immutable parent graph; XLSX/CSV intake and mapping round-trip; typed FSNB nodes and strict adjacency; simple continue/ask/broaden/unbound phase tools; evidence refs only to shown fields; selected-vs-rejected conflict rejection; per-work scope without batch inheritance; strict table-scoped search→batch read→submit; accepted/rejected durable route trace; lifetime evidence vs bounded resume-slice; stable MLX prefix cache; unit-scoped bind schema; persisted model conflict + final agent audit; navigation-card vs structured-card evidence; questions with options; saved-mapping continuation after answer; explicit session `next_step`; global review/mapping lock; authored scenario limits; canonical calculation requirements; mandatory recalculation after KAC/coefficient resolution; final lock/export/audit; responsive lazy RIM workbench |
| `tests/test_rag_hierarchy.py`, `tests/test_rag_config.py`, `tests/test_rag_rrf_readiness.py` | offline contract | deterministic hierarchy ids/ancestors; navigation is never evidence; global evidence survives route miss; v3 contract/readiness requires hierarchy and navigation policy |
| `tests/test_raptor_tree.py`, `tests/test_raptor_publication_worker.py`, `tests/test_raptor_qdrant_store.py`, `tests/test_raptor_summarizer.py`, `tests/test_raptor_publication_service.py`, `tests/test_raptor_retrieval.py` | hermetic contract/integration | deterministic RAPTOR tree; per-document checkpoint/resume; separate generation-bound dense+sparse store; source-generation staleness guard; local Ollama/extractive summary contract; exact descendant evidence retrieval; summary nodes never citable |
| `tests/test_colbert_late_interaction.py`, `tests/test_colbert_generation_service.py`, `tests/test_rag_advanced_preflight_service.py`, `tests/test_rag_generation_supervisor.py`, `tests/test_build_rag_contract_sibling.py` | hermetic contract/integration | BGE-M3 MaxSim, lazy/circuit behavior, no-load model/cache/disk estimate, complete required-vector readiness, resumable sibling build and atomic activation; active generation is never backfilled in place |
| `tests/test_rag_advanced_synthetic_benchmark.py`, `tools/rag_advanced_synthetic_benchmark.py` | synthetic A/B | ColBERT MRR/Recall@1 must improve over baseline cases; RAPTOR descent must cover every exact leaf and navigation summaries remain non-citable. This is algorithmic evidence, not live corpus quality acceptance |
| `tests/test_parse_resume.py`, `tests/test_basic_function_smoke.py`, recovery cases in `tests/test_qdrant_adapter_parse.py` | offline recovery/smoke | explicit skipped/retryable/terminal dispositions, bounded attempts/backoff, allowlisted capped startup repair excluding module datasets, persisted GUI diagnostics; dev smoke warns/skips chat during indexing while release smoke fails with `INDEXING_IN_PROGRESS` |
| `tests/test_smeta_user_message_service.py` | focused | машинные smeta-статусы не попадают в обычный ответ; частичная сумма названа стоимостью рассчитанной части; автoрасчёт явно назван проверяемым черновиком и не выдаётся за финальную смету; рубли форматируются по-русски; covered/open строки описываются человеческим языком |
| `tests/test_chat_attachment_service.py` | 3 | server-owned read attachments: opaque id/path containment, SHA/size validation, consume and TTL cleanup |
| `tests/test_live_workbook_acceptance_contract.py`, `tests/test_candidate_acceptance_service.py`, `tools/live_workbook_acceptance.py` | offline contract + hermetic ASGI boundary + opt-in live runner | Offline transport exercise is explicitly nonpersistent `contract_test`, so it cannot create `live_runtime` evidence. It proves fail-closed exact typed/redacted receipt validation: two immutable revisions, parent/attachment/checkpoint/provenance/hash/model identity, `/api/version` full 40-hex commit + positive build + clean/aligned runtime, monotonic complete SSE progress, and XLSX with a visible two-cell header/data row. The hermetic TestClient proof uses real multipart candidate upload, chat SSE, `_run_chat_with_provider → _run_chat → evidence application → harvest`, and artifact routers. Its fixture supplies an isolated profile snapshot, empty retrieval/history ports, and lower model transport, tool shortlist, and workbook executor. A harvest-source mutation must make the runner reject the SSE final. Fixture paths, unprivileged/non-isolated candidate uploads before persistence, unknown/auth/prompt/path/traceback data are rejected. Only the real entrypoint constructs its HTTP client and can write `live_runtime`; `make live-workbook-acceptance LIVE_WORKBOOK_ACCEPTANCE_ARGS='…'` remains a separate owner-authorized real-input gate, not fixture/model-quality evidence. |
| `tests/test_request_idempotency_service.py` | focused | внешний контракт ЛСР: пользовательское временное вложение, привязка ключа к файлу/телу/пользователю, replay готового ответа без второго model call, `409` на конкурентный или конфликтующий повтор |
| `tests/test_prices_router_batch.py`, `tests/test_fgis_price_service.py`, `tests/test_les_mcp_server.py` | focused | пакетный exact lookup ФГИС: одна загрузка книги, сохранение missing, дедупликация кодов и наличие `les_price_lookup_batch` в MCP-каталоге |
| `tests/test_kac_web_service.py` | 2 | fail-closed web-KAC: strong exact-product identifier and three distinct suppliers with VAT normalization |
| `tests/test_smeta_norm_store.py` | 7 | typed SQLite-light smeta norm projection over existing GESN/FSM/TER sources: schema payload, FTS/LIKE candidate search, norm-card profiles with hints/resources/condition_hints/provenance/model_card/navigation, nearby norms, worker-thread cached reads, no heavy row leak in trace |
| `tests/test_smeta_structured_base.py` | focused | canonical smeta machine base: typed SQLite, quarantine, resource dedupe and pre-replace `minimum_norms` + provenance gates that preserve the existing canonical file byte-for-byte on regression; проверочные соединения закрываются до atomic replace, включая Windows |
| `tests/test_smeta_norm_browser.py`, `tests/test_build_smeta_norm_rag.py`, `tests/test_smeta_rerank_ab_probe.py`, `tests/test_activate_smeta_rag_generation.py`; live `make smoke-smeta-rerank` | integration + live | resumable exact-generation build, document batch не обходит cross-encoder, selected official table возвращается полностью; staged manifest не меняет active; activation повторно проверяет dense/sparse/fingerprint/native RRF и атомарно публикует alias+manifest |
| `tests/test_smeta_release_baseline.py` | focused | immutable Windows smeta payload: source/base/FSEM SHA and counts plus default pricebook parquet schema/row floor, archive verification, clean-state provisioning, keep-valid-existing, upgrade валидного, но менее полного state, fail-closed partial-state protection и repair с резервной копией |
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
| `tests/test_build_rag_contract_sibling.py` | focused | contract-clean migration safety: exact indexed-user scope manifest excludes module-owned ARTEL and becomes stale on corpus change; deterministic ids, atomic checkpoint, retry, immutable-contract env restore and explicit punctuation/noise exclusion without synthetic sparse tokens |
| `tests/test_rag_generation_supervisor.py` | focused | supervisor restarts only on unsuccessful exit and carries the same scope manifest through build/readiness/activation arguments |
| `tests/test_rag_rrf_readiness.py` | focused | fail-closed activation gate: scope manifest hash must match migration; every selected dataset/destination point needs fingerprint+dense+sparse, source/child/exclusion accounting, complete FTS and contract-model/backend identity-checked live RRF endpoint |
| `tests/test_activate_qdrant_generation.py` | focused | stable alias activation requires green structural+FTS+live-RRF report; Qdrant/SQLite alias rollback clears or restores lexical projection; direct activation reconciles supervisor state and immediately runs fail-closed navigation-count MetaDB reconciliation |
| `tests/test_rag_readiness_service.py` | focused | GUI readiness reports honest ready/degraded/building/awaiting-activation states from contract, dense, sparse, fingerprint, FTS and alias coverage |
| `tests/test_deploy_to_runtime.py` | focused | service restart routing, clean-release scope from `deploy_stamp.deployed_commit..HEAD`, and safe distinction between a file matching the deployed commit and true runtime-only drift |
| `tests/test_internal_dual_deploy.py`; `tests/test_{installer_windows,tauri_desktop}.py`; `tools/browser_layout_smoke.py` | focused + installed Windows + live browser | prepare-once/apply-fast exact safe branch: checksum-valid local bundle cache, unchanged baseline transfer skipped, separate Windows prepare/apply, no pytest/build on apply, no publish path, Mac atomic replace/rollback and Legion application rollback without user state; Windows GUI subsystem, single-instance/in-flight lifecycle, direct Python PID contract, no LES-owned `cmd.exe`, no repeated bootstrap at desktop handoff; `/`, `/classic`, `/les/classic` on desktop/mobile without overflow, clipped actions or hidden focus |
| `tests/test_smeta_rag_quality_probe.py` | 2 | smeta diagnostic probe preserves norm identity and technology evidence while keeping professional applicability outside machine scoring |
| `tests/test_system_dataset_service.py` | 3 | module-owned RAG identity: SMETA_SERVICE/GESN projections are typed `system/smeta`, project tables stay user-owned, MetaDB and module lookup persist the boundary |
| `tests/test_smart_index.py` | focused | общий пользовательский RAG не регистрирует module-owned generated projections; ФГИС-смета остаётся в typed smeta contour |
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
| `tests/test_pdf_contour_service.py` | 8 | Общий `list.pdf_page_passport.v1` для GUI и RAG: digital/table/drawing/scan/mixed/damaged routing, text quality/OCR-needed, short-page RAG regression, safe uploaded-source resolution, partial coverage, read-only full-page/bbox PNG, SHA неизменность, RAG payload со source_ref/bbox и сохранение OCR `## Стр. N` page nodes |
| `tests/test_list_office_service.py` | 6 | Л.И.С.Т. Студия: отдельные append-only DOCX/XLSX ревизии, atomic publish без частичных каталогов, manifest/provenance/missing fields, неизменность файла-основания, последовательные revision numbers, SHA-256 fail-closed download, path-safe IDs и порядок API routes |
| `tests/test_list_office_agent_service.py` | 6 | `office_document_ir_v1`: только выбранные server-resolved документы, bounded field-specific evidence, пустые `project.name/address` извлекаются с выбранного проектного листа и после review заполняют typed fields; invalid evidence→visible assumption, model failure without prose fallback, explicit review gate and preserved IR in immutable manifest |
| `tests/test_cad_bim_extract_dxf.py`, `tests/test_cad_bim_aggregate_w61.py`, `tests/test_cad_bim_import_inventory.py`, `tests/test_retrieval_service.py` | focused additions | CAD/BIM DWG input uses LibreDWG conversion before canonical graph build, repairs broken DXF group-code lines from real DWG output, JSON-sanitizes surrogate text, reconstructs drawn CAD tables from line/polyline grids plus text, and renders `CAD drawn tables`, first-position anchors, logical position rows, and compact row text before element noise; import inventory marks weak/minimal imports, duplicate source groups, and duplicate indexed projections; retrieval promotes exact source/projection/import-id and format-neutral hyphenated identifier hits after rerank, plus first ordinal table chunks, so a precise designation, CAD source or beginning of a target-file table is not hidden by a larger similar projection |
| `tests/test_saferag_service.py` | 12 | SafeRAG context/source helpers: lexical rank boost, source concentration, low raw-score lexical matches, protected opened documents, deduplicated copied docs, context builders and source-name order |
| `tests/test_static_assets.py` | 10 | статический продуктовый контракт UI: рабочие «Документы»/«Студия»/`CAD/BIM`/«Почта» вне конфигуратора; документы показывают RAG-фрагменты и оригинал без старого технического экрана; Студия использует датасет/том/явные основания; admin содержит отдельную настройку почты без сообщений; chat deep-link, Qdrant visualizer и deploy shell остаются подключены |
| `tests/test_fgis_full_update.py` | focused | публичный каталог/Сплит-формы, checkpoint/resume, автоматический перезапуск, объединение с уже идущим обновлением норм, API/UI wiring, отсутствие системного confirm при добавлении датасета и операторский progress contract: этапы, остаток, ETA, байты, скорость и журнал |
| `tests/test_document_explorer_service.py` | 11 | no-AI список/поиск/чтение документов и additive migration старой MetaDB без `lexical_chunks[_fts]`, без reindex |
| `tests/test_mermaid_graph.py` | 2 | live graph payload `/api/rag/graph/full` renders into Mermaid and empty graph is explicit |
| `tests/test_proxy_security.py`, `tests/test_proxy_routers.py` | 43 focused with Sovushka | trust/auth guardrails: ZeroTier/trusted admin, API-key roles, protected `les-admin-` root-admin keys without device binding, and trusted-only mutation of protected keys |
| `tests/test_sovushka_chat.py`, `tests/test_sovushka_uikit.py`, `tests/test_chat_stream_w51.py` | 39+ + focused | Sovushka chat/UI and SSE regressions: durable per-browser `session_id`, history restore, recovered-answer persistence, markdown rendering, progressive-disclosure topbar and secondary actions, floating mode guidance/examples, stop of the active streaming dialog, reader-position-preserving SSE autoscroll, new-chat/model-chip/table wrapping, editable prompt controls, attachment context, no project-summary final hijack, additive MetaDB inventory context, clickable file-register RAG, selected-dataset deep link Самовар→Документы/Л.И.С.Т., pasted folder path→default dataset name, compact service upload, lazy panel cache without slide-transition, scheduler-start endpoint guard, WAITING-vs-PARSING status, and file-layer labels |
| `tests/test_memory_core.py`, `tests/test_memory_api.py`, `tests/test_memory_ui_contract.py`, `tests/test_smeta_memory_isolation.py` | 18 | Memory default-off/strict grounded predicate, project scoping, candidate/confirmation/conflict rules, queue worker, exact route identity, root-admin API, GUI danger confirmation contract и read-only smeta capture без изменений стабильного ядра |

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
у каждого chat check отдельный конечный `--chat-timeout` (по умолчанию 90s), поэтому timeout
даёт наблюдаемый P0/P1 result, а не зависший gate.
L1 HTTP-смоук базовых функций против живого runtime (:8050/:8051), JSON-артефакт, non-zero на P0.
`make smoke-basic-release` и все пути `ship`/post-deploy добавляют `--release`, поэтому P1 также
блокирует выкат.
Браузерный слой L2/L3 (Playwright + `data-testid`) пока **открыт** — см. план.

Проверяется на L1:

```text
runtime/version/health
scope options
chat route/version trace: glossary отдельно, project query не glossary; текущий `versions.version_info` и legacy trace принимаются
health/diagnostics do not hide FAIL; чистый runtime без проверяемых ответов даёт TOSKA WARN, а не ложный ERR
```

## Чек-лист перед коммитом версии

1. `product_version` и `build_number` согласованно подняты в `config/version.json`.
2. `make verify` зелёный.
3. Профильные тесты версии + регрессия зелёные.
4. Deploy stamp пишется на `--apply` (или вручную `write_deploy_stamp` при cp).
5. `docs/RELEASE_LEDGER.md` обновлён; версии внешнего ПО сверены с `docs/SOFTWARE_VERSIONS.md`.
## Advanced RAG / GUI-first configuration (0.27.47)

- `tests/test_runtime_config_registry_service.py` — полный GUI-visible factor registry, secret masking, Danger confirmation, read-only/unknown guards, Unicode/quotes/spaces.
- `tests/test_rag_advanced_policy_service.py` — versioned atomic RAPTOR/ColBERT policy and stable status/error codes.
- `tests/test_colbert_late_interaction.py` — MaxSim ordering and self-recovering circuit breaker.
- `tests/test_raptor_tree.py` — deterministic navigation-only tree, checkpoint and exact leaf descent.
- `tests/test_qdrant_adapter_parse.py::test_hierarchy_navigation_nodes_receive_prevalidated_sparse_vectors` — hierarchy не может добавить navigation node после sparse prevalidation.
- `tests/test_qdrant_adapter_parse.py::test_file_upsert_waits_before_exact_count_verification` — exact Qdrant count выполняется только после `wait=True` upsert acknowledgement.
- `tests/test_parse_resume.py::{test_legacy_navigation_count_repair_requires_exact_safe_delta,test_metadb_applies_navigation_count_repairs_atomically}` — metadata-only repair допустим только когда весь delta состоит из явных hierarchy navigation points и dense/sparse/lexical полностью совпадают; SQLite обновляется атомарно.
- `tests/test_rag_advanced_synthetic_benchmark.py` / `tools/rag_advanced_synthetic_benchmark.py` — hermetic A/B: baseline RRF order vs ColBERT MRR/Recall@1 plus RAPTOR citation boundary.
