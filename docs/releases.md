# Release log — Unified Construction Harness / Runtime

Версии для отката. Источник истины — `proxy/services/version_service.py`. Видно в шапке (бейдж) и
`GET /api/version`. Product-версия (`APP_VERSION`) пользовательская; harness — внутренний контур.

**App `5.1.0` · harness `0.23` · evidence schema `1.0` · extraction schema `1.0` · resource calc `0.6`.**

| версия | commit | что |
|---|---|---|
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
