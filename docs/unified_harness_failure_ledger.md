# Unified Construction Harness — Failure Ledger (v0.8)

Реестр поведения на operational-смоуке. `no_data`/`MISSING` с честным evidence — НЕ баг, а
корректный отказ. Баг — только системная ошибка, фейковый источник или маршрут не туда.

**Как включить (dev):** `LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1` (OFF по умолчанию — в коде и
тестах не меняется). Смоук: `LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1 uv run python
scripts/smoke_unified_v08.py` (фикстура) или `--dataset-id <ds>` (реальный проект). Trace ответа:
`query_route.version=unified_construction_harness_v0_8` + `unified_trace` + `evidence_summary`.
Выключить: убрать env-переменную. Runtime (`/Users/ovc/LES/.env`) НЕ трогался — флаг ставит оператор.

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

## Открыто (v0.10+): когда backend подключён
- vector/mail сейчас `unavailable` в **sync** unified-пути (async retrieve/mail_query не вшит). Закрыть —
  async-обёртка адаптеров в chat-пути ИЛИ sync-мост к Qdrant.
- lexical реально найдёт тело PDF, **если корпус проиндексирован** в lexical_chunks (в фикстуре пусто).
- реальный resource-price DB/ФГИС (bridge готов, not_found). **На реальном проекте в GUI прогон ещё не
  делался** — оператору включить флаг в рантайме (`LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1`) и
  `smoke_unified_v09.py --dataset-id <id> --append-ledger`.
