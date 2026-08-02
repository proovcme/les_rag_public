# Backlog — RAG / Excel / PDF (Legion)

Статус: рабочий backlog. Не заменяет [ROADMAP_TO_V1.md](../ROADMAP_TO_V1.md).
Инвариант LES: модель связывает, код считает; число без provenance — не результат.

Пользовательский Windows Setup/Uninstall — [WINDOWS_DESKTOP.md](WINDOWS_DESKTOP.md).

## Не делать

- GraphRAG для ФСНБ (каталог уже граф).
- Полная миграция на LlamaIndex/Haystack.
- ColBERT / late interaction — только если A/B+trace покажет потолок dense+sparse+rerank.
- Dataset-specific boosts / domain-prose в query (запрещены каноном).
- Отдельный golden/ranx как главный gate — **вместо него** live A/B Gemma↔Qwen с полным stage-trace.

## Волна 0 — Setup без зомби (сейчас)

| Задача | Статус |
|---|---|
| Перед install убивать **все** `les-desktop.exe` и LES python, не только INSTDIR | done (`preflight-install`) |
| Сносить `LES-removed-*` / `LES-purge-*` до Setup | done |
| Ярлыки только на `%LOCALAPPDATA%\Programs\LES\les-desktop.exe` | done |
| Setup не падает с «ошибка 1»; deps → `setup-deps-missing.txt` | done |

## Волна 1 — Измерить: A/B Gemma↔Qwen + trace

Точка входа: `tools/smeta_model_quality_benchmark.py` (уже Qwen/Gemma, tool-events).

| Задача | Зачем |
|---|---|
| Единый stage-trace на профиль: catalog / search / read / bind / LLM / tools | **started** — `stage_latency` в analysis/JSONL |
| Per-stage p50/p95 latency в summary JSON | **started** |
| Trace полей: scope, filters, candidate ids, selected/rejected, unbound reason | partial (route traces уже есть) |
| Не выбирать норму кодом; qrels только для метрик качества | done (инвариант) |
| Windows A/B: live sentence-transformers reranker + fail-closed preflight | **done** (0.27.24) |
| Resume batch≠batch без fingerprint poison | **done** (0.27.24) |
| Interrupt по умолчанию выключен (только явный resume-proof) | **done** |

**Done when:** один JSONL+summary на профиль с stage timings и route, два профиля side-by-side.

## Волна 2 — Поиск

| Задача | Зачем |
|---|---|
| Один Qdrant Query: metadata filters + exact cipher + dense+sparse → RRF → rerank | filters+exact guards уже есть; дальше — единый Query API |
| Parent/context hydration после rerank (`search_chunk` → parent card) | **started** — `les.parent_card.v1` |
| Иерархический scope ФСНБ до semantic search | smeta catalog уже; общий RAG — дальше |
| Сравнение reranker: текущий bge vs Qwen3-Reranker — только по A/B+trace | не гадать |

**Done when:** A/B показывает рост bound quality и/или снижение catalog latency без роста false_bound.

## Волна 3 — Документы

| Задача | Зачем |
|---|---|
| `les-spreadsheet-parser`: calamine overview → openpyxl detail → formula graph; COM recalc на Windows | **skeleton** — `spreadsheet_object_model` overview |
| `les-document-parser`: classify page → PyMuPDF / Docling → OCR fallback | **skeleton** — `document_object_model` routes |
| Единый provenance: file/version/page\|sheet/bbox\|cell/parser | в skeleton schemas |
| Сверка Excel↔PDF / version diff — после парсеров | не раньше |

**Done when:** tool harness отдаёт range/page/crop с provenance; LLM не глотает целый файл.

## Порядок работ (канон для агента)

1. Волна 0 (зомби Setup) — блокер установки.
2. Волна 1 (A/B+trace) — блокер любых «улучшений поиска».
3. Волна 2 (поиск) — по метрикам волны 1.
4. Волна 3 (Excel/PDF) — параллельно после скелета контрактов, сверка в конце.

## Точки входа в коде

- Setup helper: `installers/windows/app/les-setup-helpers.ps1` (`preflight-install`)
- NSIS hooks: `desktop/tauri/src-tauri/windows-installer-hooks.nsh`
- A/B: `tools/smeta_model_quality_benchmark.py`
- Retrieval: `backend/qdrant_adapter.py`, `backend/rag_hierarchy.py`
- Smeta catalog: `proxy/smeta_core/`
- Tool harness: `proxy/services/tool_harness_service.py`
