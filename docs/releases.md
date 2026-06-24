# Release log — Unified Construction Harness / Runtime

Версии для отката. Источник истины — `proxy/services/version_service.py`. Видно в шапке (бейдж) и
`GET /api/version`. Product-версия (`APP_VERSION`) пользовательская; harness — внутренний контур.

**App `5.1.0` · harness `0.19` · evidence schema `1.0` · extraction schema `1.0` · resource calc `0.6`.**

| версия | commit | что |
|---|---|---|
| **v0.19** | _текущая_ | version_service + `/api/version` + runtime-divergence детектор + version_info в trace + бейдж версии в шапке. UI-пакет (Stop/Открыть/Копировать/citations/evidence/extraction/chips) — НЕ начат. |
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
