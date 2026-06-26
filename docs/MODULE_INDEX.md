# MODULE_INDEX — карта модулей Л.Е.С.

> **Единый навигатор по модулям** (для AI-агентов и людей). Один модуль — одна строка: назначение,
> точки входа (сервис/роутер/MCP/чат-канал), **статус док↔код** и ссылка на док модуля.
> Карта кода по файлам — [CODE_MAP.md](CODE_MAP.md); бэклог/вехи — [../ROADMAP_TO_V1.md](../ROADMAP_TO_V1.md);
> состояние версий/деплоя — [RELEASE_LEDGER.md](RELEASE_LEDGER.md); правила/гейты — [../AGENTS.md](../AGENTS.md).
>
> Собрано аудитом 2026-06-27 (4 параллельных прохода, сверка каждого тезиса с кодом). Источник истины —
> код; при расхождении док↔код **прав код** (`/api/version`, `git log`). Статус: ✅ canonical (сверено,
> держать) · 🟡 drifted (содержание разошлось, чинить — см. примечание) · 🗄 stale (историческое, в архив)
> · 📋 plan (ещё не в коде).

## Как пользоваться

1. Нужен модуль → найди строку в таблицах ниже → открой **док модуля** (если ✅) или код (точки входа).
2. Статус 🟡/🗄 у дока = **не доверяй слепо**, сверь с кодом по примечанию.
3. Новый модуль → добавь строку сюда + один док по шаблону `docs/modules/<name>.md` (см. низ файла).

---

## 1. Смета (ценообразование, 0 LLM в расчёте — ADR-11)

Сквозной поток и эталон (позиция = **11813.04**, смета 2× = **23626.08**) — [ALGO-smeta.md](ALGO-smeta.md).

| Суб-модуль | Назначение | Точки входа | Док | Статус |
|---|---|---|---|---|
| smeta (поток) | объём ВОР → … → ВСЕГО; чат-команды сметы | `smeta_chat_service` | [ALGO-smeta.md](ALGO-smeta.md) | 🟡 |
| smeta/lsr | сборка позиции→Всего→свод; РИМ-трасса (графы 2-12); XLSX форма **Прил.4** (одно/многопозиц.) | `lsr_assembly_service`, `rim_lsr_trace_service`, `rim_trace_xlsx_service`, `fsem_machinist_service`; `POST /api/lsr/{assemble,rim-trace,lsr-trace}[/export]`; MCP `les_lsr_assemble` | [ALGO-lsr-assembly.md](ALGO-lsr-assembly.md) | ✅ |
| smeta/gesn | норма ГЭСН → ресурсы (расход×объём); база 42408 норм | `gesn_service`; `GET /api/lsr/gesn[/{code}/expand]`; MCP `les_gesn_*` | [ALGO-gesn.md](ALGO-gesn.md) | 🟡 |
| smeta/fgis | цена ресурса по коду из «Сплит-формы» ФГИС ЦС | `fgis_price_service`; `/api/prices/*`; MCP `les_price_lookup` | [ALGO-fgis-price.md](ALGO-fgis-price.md) | ✅ |
| smeta/kac | конъюнктурный анализ цен (≥3 КП на материал) | `kac_service`; `/api/kac/*`; MCP `les_kac` | [ALGO-kac.md](ALGO-kac.md) | ✅ |
| smeta/stesn | коэффициент стеснённости (k к ОЗП/ЭМ) | `stesnennost_service`; `/api/lsr/stesnennost/*`; MCP `les_stesnennost` | [ALGO-stesnennost.md](ALGO-stesnennost.md) | ✅ |
| smeta/object | фраза «дай смету на …» → объектный расчёт (СМР→НДС→ВСЕГО) | `object_estimate_service`, `nr_sp_service`; шаблоны `config/domain/object_templates.yaml` | [ALGO-object-estimate.md](ALGO-object-estimate.md) | 🟡 |
| smeta/ontology | доменные понятия (ВОР/КАЦ/ЛСР/КС) | `smeta_ontology_service`; MCP `les_glossary` | [ALGO-smeta-ontology.md](ALGO-smeta-ontology.md) ✅ · [smeta_ontology.md](smeta_ontology.md) 🟡 (генерится) | 🟡 |
| smeta/bor | спецификация Ф9 → ВОР работ | `spec_to_bor_service`; `/api/bor/{id}/from-spec*` | [ALGO-spec-to-bor.md](ALGO-spec-to-bor.md) | ✅ |
| smeta/indices | индексы изменения сметной стоимости (Минстрой ИФ/09) | 📋 v0.26+ ([../ROADMAP_TO_V1.md](../ROADMAP_TO_V1.md)) | — | 📋 |

**🟡 чинить:** ALGO-smeta §3/§6 и ALGO-object-estimate — «только деревянный дом, офис→отказ» ВРЁТ: `monolith_office` живой (`object_templates.yaml`). ALGO-gesn — добавить `gesn2022_v2.parquet` (v2-слой) + разнести `gesn_import` (XLSX/ГРАНД) vs `gesn_bulk_import` (ФГИС ЦС API). smeta_ontology(.md+yaml) — «Приложение 3» → «Приложение 4» (ЛСР); чинить ИСТОЧНИК `smeta_ontology.yaml`, файл регенерится.

## 2. RAG-ядро и маршрутизация

| Суб-модуль | Назначение | Точки входа | Док | Статус |
|---|---|---|---|---|
| rag/core | поток чата, ретрив, C-RAG, диспетч | `retrieval_service`, `saferag_service`, `runtime_dispatcher`/`runtime_admission`; `routers/chat.py` | [ARCHITECTURE_les_algorithm.md](ARCHITECTURE_les_algorithm.md) ✅ · [STORY_les_dispatcher.md](STORY_les_dispatcher.md) ✅ · [CODE_MAP.md](CODE_MAP.md) 🟡 | 🟡 |
| rag/routing | выбор контура: ProfileResolver + agent-router (router-primary ON) | `profile_resolver`, `agent_router_service`, `query_router`, `deterministic_policy_service`, `scope_service` | — (истина в ARCHITECTURE §10 + коде; [AUDIT_DETERMINISM.md](AUDIT_DETERMINISM.md) 🗄 план исполнен) | 🟡 |
| rag/retrieval | типизированный ретрив (ADR-12), doc_router | `retrieval_service`, `doc_router`; флаг `LES_TYPED_RETRIEVAL` | [ADR-12-typed-retrieval.md](ADR-12-typed-retrieval.md) | ✅ |
| rag/table | детерм. SUM по полному Parquet (числа — код) | `table_query_service`; MCP `les_table_*` | [ALGO-table-query.md](ALGO-table-query.md) | 🟡 (порядок вызова) |
| rag/pdf | layout-aware PDF (колонки/таблицы→pipe) | `backend/pdf_layout`; флаг `LES_LAYOUT_PDF` | [ALGO-pdf-layout.md](ALGO-pdf-layout.md) | ✅ |
| rag/harvest | verify-правки → train-set + таксономия ошибок | `harvest_service`; `tools/harvest_dataset.py` | [ALGO-harvest.md](ALGO-harvest.md) | ✅ |
| rag/vision | вердикт по VL-LoRA (пока не нужна) | — | [ALGO-vl-lora.md](ALGO-vl-lora.md) | ✅ (решение) |
| rag/scan-mining | поиск данных в сканах + различение типа (verify) | `verify_service`, `table_detect`, `doc_classifier`; `routers/verify.py` | [scan_data_mining.md](scan_data_mining.md) | ✅ |
| harness | unified construction harness (source-adapters, evidence) — флаг OFF | `source_adapters`, `unified_construction_harness_service` | [unified_harness_failure_ledger.md](unified_harness_failure_ledger.md) | ✅ (OFF) |

**🟡 чинить:** CODE_MAP — счётчики (**~21→101 сервисов, ~15→36 роутеров, 146→218 тестов**) + вписать ProfileResolver в «Поток чата». rag/routing — нет своего канон-дока (истина размазана по ARCHITECTURE §10 + AUDIT_DETERMINISM, который теперь описывает «как было ДО инверсии»). ALGO-table-query — уточнить: агрегация **после** ретрива по router-интенту, не «до семантики».

## 3. Нормоконтроль и проверка документации

| Суб-модуль | Назначение | Точки входа | Док | Статус |
|---|---|---|---|---|
| normcontrol/doc-review | RAG-led СПДС-review по ГОСТ Р 21.101-2026 (computed + retrieval-подфаза + штамп) | `doc_review_service`, `doc_review_retrieval_service`, `title_block_extract_service`, `document_set_model`, `normcontrol_review_map_service`; `routers/doc_review.py`; флаг `LES_TITLE_BLOCK_OCR` | [DOC_REVIEW_GOST_R_21_101_2026_PLAN.md](DOC_REVIEW_GOST_R_21_101_2026_PLAN.md) | 🟡 |
| normcontrol/formal-v1 | формальные NK-01..04 (форматы ГОСТ, шифры, ведомость) | `normcontrol_service`; `/api/normcontrol` | — (**нет ALGO-дока — пробел**) | 🟡 |
| normcontrol/checklist | чек-лист входного контроля ПД БУП/ГИП | 📋 кода нет | [CHECKLIST_REVIEW_PD_TASK.md](CHECKLIST_REVIEW_PD_TASK.md) | 📋 |

**🟡 чинить:** DOC_REVIEW план помечен «planned», хотя **Phases 1-5 в проде**; ссылается на призрачные `normcontrol_rulepack_service`/`remark_normalization_service` (реально `normcontrol_review_map_service`; remark-слой не написан). Создать короткий ALGO-док для `normcontrol_service` (formal-v1) — сейчас он без своей доки.

## 4. Приёмка / Intake

| Суб-модуль | Назначение | Точки входа | Док | Статус |
|---|---|---|---|---|
| intake/asbuilt | смонтированный объём из сканов исполнительных → журнал (pending) | `asbuilt_intake_service`; `POST /api/field/extract-asbuilt`; чат «вытащи объём из …» | [ALGO-asbuilt-intake.md](ALGO-asbuilt-intake.md) | ✅ |
| intake/mail | Outlook → классификация вложений (КП/смета/скан/документ) | `mail_push_service`; `POST /api/mail/push` | [ALGO-mail-intake.md](ALGO-mail-intake.md) | ✅ |
| intake/les_md | LES.md — файл-контекст папки (привязка к проекту) | `les_md_service`; чат «пойми папку …» | [ALGO-les-md.md](ALGO-les-md.md) | ✅ |

## 5. Инфраструктура / Операции / Версии

| Суб-модуль | Назначение | Точки входа | Док | Статус |
|---|---|---|---|---|
| infra/runtime | топология (proxy:8050 / sovushka:8051 / mlx:8080 / qdrant:6333) | `proxy_server.py`, `sovushka_ng.py`, `mlx_host.py` | [PROXY_ARCHITECTURE.md](../PROXY_ARCHITECTURE.md) 🟡 · [INFRASTRUCTURE_v2.0.md](../INFRASTRUCTURE_v2.0.md) 🗄 | 🟡 |
| infra/mlx | TTL-выгрузка, memory-guard, профили памяти | `backend/mlx_adapter`, `mlx_host.py` | [MLX_GUIDE.md](../MLX_GUIDE.md), [RUNTIME_MEMORY_PROFILES.md](../RUNTIME_MEMORY_PROFILES.md) ✅ | 🟡 |
| ops/deploy | dev→рантайм cp-деплой + stamp; откат | `tools/deploy_to_runtime.py`, `tools/restore_runtime.sh` | [SKILL.md](../SKILL.md) 🟡, [RELEASE_LEDGER.md](RELEASE_LEDGER.md) | 🟡 |
| ops/versioning | единый центр версий + divergence repo↔runtime | `version_service`; `GET /api/version` | [RELEASE_LEDGER.md](RELEASE_LEDGER.md), [VERSIONING.md](VERSIONING.md), [releases.md](releases.md) | 🟡 |
| ops/test | гейт (verify/test/smoke-basic) | `Makefile`, `tools/basic_function_smoke.py` | [TEST_INVENTORY.md](TEST_INVENTORY.md) 🟡 | 🟡 |
| install | сборка/инсталляторы Mac/Win/Linux | `tools/build_*`, `installers/` | [INSTALL_RUNBOOK.md](INSTALL_RUNBOOK.md) ✅, [PLATFORMS.md](PLATFORMS.md) ✅ | 🟡 |

**🟡 чинить:** версии (3 несвязанные оси) — см. [RELEASE_LEDGER.md](RELEASE_LEDGER.md). SKILL.md/TEST_INVENTORY — «v0.22/230 тестов/h0.20» отстали от h0.23; smoke-basic уже сделан (в TEST_INVENTORY помечен планом). INFRASTRUCTURE/PROXY_ARCHITECTURE — мёртвое (Speckle/GLM-OCR/4B/`les_meta.db`).

## 6. Прочие модули (отдельные продукты/контуры)

| Модуль | Назначение | Док |
|---|---|---|
| cad-bim | CAD/BIM граф + вьювер (three.js/web-ifc) | (в [CODE_MAP.md](CODE_MAP.md); `routers/speckle.py` = `/api/cad-bim/*`) |
| artel | генератор семейств Revit (отдельный Win+Revit пакет) | `products/artel/skills/*/SKILL.md` |
| mail (Е.Ж.И.К.) | приёмка почты IMAP/Apple Mail/.olm | (в [CODE_MAP.md](CODE_MAP.md)) |
| mcp | ЛЕС как MCP-сервер (16 инструментов наружу) | `tools/les_mcp_server.py` (в [CODE_MAP.md](CODE_MAP.md)) |

---

## Шаблон дока модуля (`docs/modules/<name>.md` или `docs/ALGO-<name>.md`)

```
# <Модуль> — <одна строка назначения>
Назначение · Точки входа (сервис/роутер/MCP/чат) · Данные/конфиг · Зависимости ·
Поток (формулы/шаги, 0 LLM где про числа) · Статус-vs-код (что сверено) · Грабли/границы · Тесты
```

> Канон 0-LLM ядер — `docs/ALGO-*.md` (по кирпичу). Этот индекс их агрегирует; при добавлении/правке
> модуля — обнови строку здесь и поставь честный статус (✅/🟡/🗄/📋).
