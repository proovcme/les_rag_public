# TEST_INVENTORY — тесты Unified Construction Harness v0.16–v0.23

Гейт: `make verify` (офлайн, синтаксис+импорт-смоук). Полная сюита: `uv run python -m pytest tests/ -q` (~2046 тестов / 218 файлов).
Все тесты ниже офлайн (без живых Qdrant/MLX), flag `LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED` OFF.

**Профильные таблицы v0.16–v0.22: 230 тестов** (+ регрессия v0.3–v0.15 и chat/router при OFF). Полная сюита на h0.23 — **~2046 тестов в 218 файлах**.

| Файл | Тестов | Покрывает |
|---|---:|---|
| `tests/test_answer_render_v16.py` | 22 | render-хелперы Совушки: strip markdown из ячеек, source-chips, evidence-секции, citation/conflict-блоки, `answer_copy_text` (Копировать без trace/тела письма) |
| `tests/test_sidecar_ops_v16.py` | 50 | sidecar-операции: инвентарь датасетов, heading-классификатор, extraction-state (7 кейсов), lexical `extracted_fts`, OCR-детект, `run_extraction`/`extract_body_op` (gate env+confirm), originals read-only (shasum), legacy `.xls` |
| `tests/test_route_and_runtime_v17.py` | 34 | runtime alignment (extract-эндпоинты зарегистрированы), route-fix «реестр документации» ≠ глобальный реестр, doc_type_classifier, honest `.xls`, регрессии v0.3–v0.16 |
| `tests/test_deterministic_policy_v18.py` | 27 | DeterministicFinalPolicy: glossary-final только при литеральном термине, registry только глобальный, source-scoped/descriptive→reject; «расскажи про котельную»≠ОЖР; ОЖР/КАЦ/ЛСР работают |
| `tests/test_version_service_v19.py` | 23 | `/api/version` 200, no-secrets, git-unavailable-safe, runtime_alignment (aligned/divergent/missing/dev-only/unknown), version_info в trace, route-регрессия |
| `tests/test_v020_deploy_stamp_ui.py` | 24 | deploy stamp (missing/ok/stale/hash-mismatch), `deployed_commit` в endpoint, copy plain/markdown/with-sources/no-trace, prompt-chips→меню «Примеры» |
| `tests/test_scope_model_v21.py` | 32 | Scope-резолвер (all/project/projects/dataset/datasets/mixed/legacy/filter-warning/scope>legacy); scope_options (админ-датасет/unassigned/system-reason/counts); scope в trace; document-prep labels |
| `tests/test_scope_clarification_v22.py` | 18 | §1 needs_project_scope (проектные→clarify, нормы/глоссарий→allowed), scope_clarification + suggest_project, ScopeSelector wiring, scope→payload |

## Ключевые «живые» доказательства (на рантайме :8050)

- **844a2b53 / e19cc409** — approved sidecar write: 27 / 22 sidecar, оригиналы байт-в-байт целы (shasum); extracted_body отвечает по ГОСТ/СП с source_ref до `.docx#para`.
- **resource workbook** — `ПРИМЕР_обсчета_24_06.xlsx` валидирован кодом: grand total **16 827 283.19 ₽**, line_diffs=0.
- **route**: «расскажи про котельную»@all→`scope_clarification`; @project→RAG; «что такое ОЖР»→glossary; «реестр документации»≠глобальный.
- **`/api/scope/options`**: 28 датасетов (assigned 2 / unassigned 25 / system 1), 6 проектов.
- **`/api/version`**: harness 0.23, `deployed_commit` ≠ git (deploy stamp), 0 секретов.

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
