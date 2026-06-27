# Release log — Unified Construction Harness / Runtime

Версии для отката. Источник истины — `proxy/services/version_service.py`. Видно в шапке (бейдж) и
`GET /api/version`. Product-версия (`APP_VERSION`) пользовательская; harness — внутренний контур.

**App `5.1.0` · harness `0.24` · evidence schema `1.0` · extraction schema `1.0` · resource calc `0.6`.**

| версия | commit | что |
|---|---|---|
| **v0.24.0.1** | HEAD | Operator-facing normcontrol stabilization: doc-review now persists engineer decisions (`confirmed/rejected/needs_more_evidence`) through API, JSON/XLSX/HTML and Admin GUI controls; the Admin “Инструменты” tab is mounted again; chat has a direct service-sources panel for ГЭСН/ФГИС/СПДС/layout visibility; doc-review chat output no longer turns human reports into giant markdown artifact tables. |
| **v0.24.0.0** | HEAD | SPDS/public-ready baseline: doc-review exposes `normalized_remarks` for checklist/report renderers, XLSX includes a normalized remarks sheet, GUI downloads XLSX/JSON/HTML, runtime alignment now watches doc-review/service-source entrypoints, and the repo has source-available `LICENSE`, `SECURITY.md`, publication checklist and `make public-check`. |
| **v0.23.6.12** | uncommitted | Service source registry + layout v1: Admin/GUI now shows required data sources for smeta/normcontrol via `/api/service-sources`, and title-block review verifies that stamp signatures are in the expected bottom-right sheet zone instead of merely existing somewhere in text. |
| **v0.23.6.11** | uncommitted | Normcontrol human defense report: doc-review chat answers now render a defendable human report with evidence/action tables, no working-memory leakage, top-level `defense` payload, and D4-001 sheet-format computed from PDF page geometry via ГОСТ 2.301. |
| **v0.23.6.10** | uncommitted | Attachment UX + release cadence: uploaded files now leave an explicit composer strip and chat system message saying they will be used in the next request; `make ship` is the fast iteration gate with retry post-deploy smoke, while `make ship-full` keeps the full pytest release gate. |
| **v0.23.6.9** | uncommitted | System defense-contract v1: `DefensePack/DefenseClaim` in the evidence contract, object-estimate defense with formula/cost/price-coverage/non-defensible status, doc-review/normcontrol JSON defense output, and object-estimate chat payload exposing `defense` for UI/export. |
| **v0.23.6.8** | uncommitted | Chat attachment stabilization: default file attach is now “to chat”, the user bubble shows the attached filename, read attachments are sent to the model with filename-bearing `attachment_context`, plain file-reading tasks use an attachment-only LLM route without global RAG noise, and direct/router LLM calls fall back to local MLX when cloud is not keyed. |
| **v0.23.6.7** | uncommitted | Latency hotfix deployed: router-primary is now explicit opt-in, preventing deterministic chat requests from waiting for the 12s LLM-router timeout before cascade fallback; post-deploy smoke has deterministic chat at millisecond scale. |
| **v0.23.6.6** | uncommitted | v0.23B partial: source chips with a real `source_ref` open a citation drawer in Artifacts; weak/vector and missing-ref sources are not fake-opened and show a clear unavailable reason. |
| **v0.23.6.5** | uncommitted | Stability contract pass: read-attachment conversion errors are controlled 422 responses, the collapsed artifact panel has an explicit GUI open control, and Guardrails records the new per-feature stability contract/current green baseline. |
| **v0.23.6.4** | uncommitted | UI defaults: light theme by default in chat/admin, artifacts panel collapsed by default, OpenAI-compatible cloud uses `gpt-4.1` instead of a blank model, and object-estimate responses now expose calculation logic, sources, trace and evidence summary. |
| **v0.23.6.3** | uncommitted | UI/smeta stabilization: chat attachments can be read as request context, quick/index attachments now scope the next chat request, composer has direct scope/folder controls, and object-estimate now gives a rough full-object budget from vague ToR via explicit ASSUME allowances and `price_level_k`; detailed smeta remains driven by files/datasets. |
| **v0.23.6.2** | uncommitted | Operational hardening: trusted loopback/proxy defaults narrowed, KOT term matching made boundary-safe, Samovar verifies Qdrant point counts per file by default, backup/restore now has SHA256 checksum gate. |
| **v0.23.6.1** | uncommitted | Router-primary fallback: недоступность LLM-роутера отделена от осознанного `none`; при timeout/сети/5xx включается deterministic cascade и legacy in-flow gates (`mail`/table/clause/etc.) с честным `route_source`. |
| **v0.23** | _текущая_ | ProfileResolver (единый контракт маршрутизации); doc_registry видит `dataset_ids`; «Сводка проекта» строит реестр из описи MetaDB (датасет без Parquet тоже отвечает); симметрия датасет↔проект (LES.md и в режиме датасета); ollama-нативный `think:false` + reasoning-fallback; qdrant `check_compatibility=False`; кнопка «Копировать» — клиентский копир в жесте (http/туннель); Windows-lite инсталлятор + Outlook-поллер. |
| **v0.22** | — | Source Operations: scope_clarification (проектный запрос при scope=all не ищет молча); sidecar/extraction как понятная операция. |
| **v0.21** | — | Route Safety Freeze + scope_service (нормализованная ОБЛАСТЬ ПОИСКА all/project/dataset/…); scope-snapshot в trace. |
| **v0.20** | — | deploy stamp (`.les_deploy_stamp.json`) + runtime alignment; начало Evidence-UI. |
| **v0.19** | `5ded539`→ | version_service + `/api/version` + runtime-divergence детектор + version_info в trace + бейдж версии в шапке. |
| **v0.18** | `5ded539` | DeterministicFinalPolicy — «Расскажи про котельную» больше НЕ ОЖР; glossary-final только при литеральном термине; registry только глобальный. (пластыри: `63675d6` «на»≠ОЖР; `93aff24` фикс 500 unified-импорт при OFF) |
| **v0.17** | `30283f4` | runtime alignment, 3 extraction-эндпоинта; «реестр документации» ≠ глобальный реестр; honest legacy `.xls`; doc_type_classifier вынесен из unified |
| **v0.16** | `1e9e76c` / `bff22c7` | sidecar operations: инвентарь, heading-классификатор, extraction-state, lexical `extracted_fts`; approved write `e19cc409` |
| **v0.15** | `fbb93fe` | approved sidecar write `844a2b53` (27 sidecar, 23 930 параграфов, оригиналы read-only по shasum) |
| **v0.14** | — | sidecar write policy (env+confirm gate), manifest, staleness |
| **v0.13** | — | document body extraction PDF/DOCX/XLSX (без OCR, оригиналы не трогаются) |

## Откат

```
git checkout <commit> -- <files>
uv run python -m tools.deploy_to_runtime --apply --files <files>
launchctl kickstart -k gui/$(id -u)/me.ovc.les.proxy   # рестарт прокси (порт 8050) — только с ОК оператора
```

Флаг `LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED` — **OFF по умолчанию** (не менять). Runtime `.env` оператор
меняет сам. `/api/version` → `runtime_alignment.status` показывает, расходятся ли repo и `/Users/ovc/LES`.
