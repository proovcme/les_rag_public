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
**Скилл-плейбук (для агента и ЛЕС): [skills/smeta/SKILL.md](../skills/smeta/SKILL.md).**

| Суб-модуль | Назначение | Точки входа | Док | Статус |
|---|---|---|---|---|
| smeta (поток) | объём ВОР → … → ВСЕГО; чат-команды сметы | `smeta_chat_service` | [ALGO-smeta.md](ALGO-smeta.md) | ✅ |
| smeta/lsr | сборка позиции→Всего→свод; РИМ-трасса (графы 2-12); XLSX форма **Прил.4** (одно/многопозиц.) | `lsr_assembly_service`, `rim_lsr_trace_service`, `rim_trace_xlsx_service`, `fsem_machinist_service`; `POST /api/lsr/{assemble,rim-trace,lsr-trace}[/export]`; MCP `les_lsr_assemble` | [ALGO-lsr-assembly.md](ALGO-lsr-assembly.md) | ✅ |
| smeta/gesn | норма ГЭСН → ресурсы (расход×объём); база 42408 норм | `gesn_service`; `GET /api/lsr/gesn[/{code}/expand]`; MCP `les_gesn_*` | [ALGO-gesn.md](ALGO-gesn.md) | ✅ |
| smeta/fgis | цена ресурса по коду из «Сплит-формы» ФГИС ЦС | `fgis_price_service`; `/api/prices/*`; MCP `les_price_lookup` | [ALGO-fgis-price.md](ALGO-fgis-price.md) | ✅ |
| smeta/kac | конъюнктурный анализ цен (≥3 КП на материал) | `kac_service`; `/api/kac/*`; MCP `les_kac` | [ALGO-kac.md](ALGO-kac.md) | ✅ |
| smeta/stesn | коэффициент стеснённости (k к ОЗП/ЭМ) | `stesnennost_service`; `/api/lsr/stesnennost/*`; MCP `les_stesnennost` | [ALGO-stesnennost.md](ALGO-stesnennost.md) | ✅ |
| smeta/object | мутное ТЗ «дай смету на …» → model-first декомпозиция: модель сама раскладывает объект, харнесс даёт `search_norm`/`add_position`; `search_norm` использует общий `candidate_selection_v1`, код проверяет нормы/единицы/объёмы и считает только прошедшие gates | `estimate_harness_service`, `candidate_selection_service`, `estimate_math_service`, `nr_sp_service`, `evidence_contract`; готовые объектные составы удалены | [ALGO-object-estimate.md](ALGO-object-estimate.md) 🟡 | 🟡 |
| smeta/ontology | доменные понятия (ВОР/КАЦ/ЛСР/КС) | `smeta_ontology_service`; MCP `les_glossary` | [ALGO-smeta-ontology.md](ALGO-smeta-ontology.md) ✅ · [smeta_ontology.md](smeta_ontology.md) ✅ (генерится) | ✅ |
| smeta/bor | спецификация Ф9 → ВОР работ | `spec_to_bor_service`; `/api/bor/{id}/from-spec*` | [ALGO-spec-to-bor.md](ALGO-spec-to-bor.md) | ✅ |
| smeta/indices | индексы изменения сметной стоимости (Минстрой ИФ/09) | 📋 v0.26+ ([../ROADMAP_TO_V1.md](../ROADMAP_TO_V1.md)) | — | 📋 |

**✅ исправлено (437f1aa):** ALGO-smeta/object — ранний объектный слой и ГЭСН-кандидаты. **Новая текущая правда с 0.24.0.20:** режим «Смета» не использует готовые объектные составы как маршрут продукта. Модель первична и сама раскладывает объект; харнесс только даёт инструменты (`search_norm`, `add_position`) и gates по нормам/единицам/объёмам. С 0.24.0.24 `candidate_selection_v1` вынесен в общий `candidate_selection_service`: shortlist, причины score и действие для ясного лидера/модельной развилки теперь reusable для следующих модулей. С 0.24.0.30 smeta harness различает типы нормативных баз (`ГЭСН38` ≠ `ГЭСНм38`) и считает массовые `metal_assembly`-позиции через `mass_t`/ЛСР-калькулятор. С 0.24.0.31 сметный чат показывает краткую сводку, а полная ресурсная расшифровка, структура стоимости, НР/СП и условия работ уходят в артефакт. Старый объектный слой и его YAML-данные удалены; auto-запросы на объектную смету не перехватываются быстрым сметным каналом.

## 2. RAG-ядро и маршрутизация

| Суб-модуль | Назначение | Точки входа | Док | Статус |
|---|---|---|---|---|
| rag/core | поток чата, ретрив, C-RAG, source-map/latency trace, диспетч | `retrieval_service`, `saferag_service`, `runtime_dispatcher`/`runtime_admission`; `routers/chat.py` | [ARCHITECTURE_les_algorithm.md](ARCHITECTURE_les_algorithm.md) ✅ · [STORY_les_dispatcher.md](STORY_les_dispatcher.md) ✅ · [CODE_MAP.md](CODE_MAP.md) ✅ | ✅ |
| rag/routing | выбор контура: ProfileResolver + agent-router (router-primary ON), `output_contract` в trace; сценарии/контракты ответа + мягкий `answer_contract_check` + общий `workflow_plan_v1` | `profile_resolver`, `agent_router_service`, `query_router`, `deterministic_policy_service`, `scope_service`, `answer_contract_service`, `workflow_plan_service` | [ALGO-routing.md](ALGO-routing.md) ✅ · [ALGO-workflow-plan.md](ALGO-workflow-plan.md) ✅ · [AUDIT_DETERMINISM.md](AUDIT_DETERMINISM.md) (решение/история) | ✅ |
| rag/retrieval | типизированный ретрив (ADR-12), doc_router | `retrieval_service`, `doc_router`; флаг `LES_TYPED_RETRIEVAL` | [ADR-12-typed-retrieval.md](ADR-12-typed-retrieval.md) | ✅ |
| rag/table | детерм. SUM по полному Parquet (числа — код) | `table_query_service`; MCP `les_table_*` | [ALGO-table-query.md](ALGO-table-query.md) | ✅ |
| rag/pdf | layout-aware PDF (колонки/таблицы→pipe) | `backend/pdf_layout`; флаг `LES_LAYOUT_PDF` | [ALGO-pdf-layout.md](ALGO-pdf-layout.md) | ✅ |
| rag/harvest | verify-правки → train-set + таксономия ошибок | `harvest_service`; `tools/harvest_dataset.py` | [ALGO-harvest.md](ALGO-harvest.md) | ✅ |
| rag/context-memory | паспорт чата + metadata/deep паспорт датасета (`_les_dataset_profile.json`) + общий `notebook_v1` поверх датасетов/служебных источников; deep-слой читает поддерживаемую FTS-проекцию `lexical_chunks` из Qdrant payloads; quality/warmup benchmark; навигационный фон, НЕ evidence; UI-кнопка «Блокнот области» | `context_memory_service`, `notebook_service`, `prompt_registry_service`, `lexical_index_service`, `backend/qdrant_adapter`; `GET /api/chat/memory/{session_id}`; `GET/POST /api/rag/datasets/{id}/profile*`; `GET /api/notebooks/{dataset_id}`; `POST /api/notebooks/warmup`; `GET /api/service-sources/notebooks`; `routers/chat.py`; `sovushka/pages/chat.py` | [ALGO-context-memory.md](ALGO-context-memory.md) | ✅ |
| rag/vision | вердикт по VL-LoRA (пока не нужна) | — | [ALGO-vl-lora.md](ALGO-vl-lora.md) | ✅ (решение) |
| rag/scan-mining | поиск данных в сканах + различение типа (verify) | `verify_service`, `table_detect`, `doc_classifier`; `routers/verify.py` | [scan_data_mining.md](scan_data_mining.md) | ✅ |
| harness | unified construction harness (source-adapters, evidence) — флаг OFF | `source_adapters`, `unified_construction_harness_service` | [unified_harness_failure_ledger.md](unified_harness_failure_ledger.md) | ✅ (OFF) |

**✅ исправлено:** CODE_MAP-счётчики (~101/~36/~2062); создан `ALGO-routing.md` (канон маршрутизации); AUDIT_DETERMINISM/AUDIT_CORE получили статус-баннер «исполнено»; ALGO-table-query уточнён (агрегация после ретрива). В 0.23.6.1 router-primary fallback закрыт через `RouterUnavailable` → deterministic cascade/in-flow fallback. В 0.23.6.9 `evidence_contract` расширен до системного `DefensePack/DefenseClaim`, первым подключены smeta/object и normcontrol/doc-review. В 0.24.0.18 `workflow_plan_v1` стал общим тонким контрактом для smeta/normcontrol/RAG/table payload: workflow, required/missing inputs, evidence policy, claim summary, source summary, blockers и next actions. В 0.24.0.19 Совушка начала показывать этот план оператору: статус/финальность в первом слое, workflow id/missing/actions в техдеталях. В 0.24.0.29 поверх паспортов добавлен общий `notebook_v1` и prompt registry; сметный режим получает ГЭСН-блокнот как навигацию перед tool-contract. В 0.24.0.30 ГЭСН-блокнот различает `ГЭСНм38` как монтажный раздел, не evidence. В 0.24.0.32 broad-вопросы по проекту больше не перехватываются скрытой deterministic-сводкой: обычный чат идёт в retrieval+модель, `project_summary` остаётся явным инструментом. В 0.24.0.33 qwen `lexical_chunks` восстановлены из существующих Qdrant payloads и дальше синхронизируются при parse-переиндексации файла, поэтому notebook/deep и lexical/hybrid слой больше не слепнут при уже загруженных PDF.

## 3. Нормоконтроль и проверка документации

| Суб-модуль | Назначение | Точки входа | Док | Статус |
|---|---|---|---|---|
| normcontrol/doc-review | RAG-led СПДС-review по ГОСТ Р 21.101-2026 (computed + retrieval-подфаза + PDF sheet geometry + layout-zone штампа) + defense-contract + `normalized_remarks` + решения инженера для checklist/report renderers | `doc_review_service`, `doc_review_retrieval_service`, `title_block_extract_service`, `document_set_model`, `normcontrol_review_map_service`, `evidence_contract`; `routers/doc_review.py`; флаг `LES_TITLE_BLOCK_OCR` | [DOC_REVIEW_GOST_R_21_101_2026_PLAN.md](DOC_REVIEW_GOST_R_21_101_2026_PLAN.md) | ✅ |
| normcontrol/formal-v1 | формальные NK-01..04 (форматы ГОСТ, шифры, ведомость) | `normcontrol_service`; `/api/normcontrol` | [ALGO-normcontrol.md](ALGO-normcontrol.md) | ✅ |
| normcontrol/checklist | чек-лист входного контроля ПД БУП/ГИП | 📋 кода нет | [CHECKLIST_REVIEW_PD_TASK.md](CHECKLIST_REVIEW_PD_TASK.md) | 📋 |

**✅ исправлено (437f1aa):** DOC_REVIEW шапка «planned»→«Phases 1-5 реализованы»; призрачные сервисы → реальные имена; создан `ALGO-normcontrol.md` (formal-v1). В 0.23.6.11 чатовый doc-review стал человеческим defense-отчётом без подмешивания memory, а D4-001 формат листа проверяется по PDF-геометрии/ГОСТ 2.301. В 0.23.6.12 D4-002 проверяет, что сигнатуры основной надписи попали в ожидаемую нижнюю правую зону листа; сигнатуры вне зоны становятся computed issue. В 0.24.0.0 JSON/XLSX получил `normalized_remarks`; в 0.24.0.1 инженер может подтвердить/отклонить/запросить данные, и решение сохраняется в API/экспорт. Остаётся 📋 Phase 6: ПП-87 composition profile, DOCX/PDF renderer, checklist importer и deeper layout-tool для заполнения всех граф.

## 4. Приёмка / Intake

| Суб-модуль | Назначение | Точки входа | Док | Статус |
|---|---|---|---|---|
| intake/asbuilt | смонтированный объём из сканов исполнительных → журнал (pending) | `asbuilt_intake_service`; `POST /api/field/extract-asbuilt`; чат «вытащи объём из …» | [ALGO-asbuilt-intake.md](ALGO-asbuilt-intake.md) | ✅ |
| intake/mail | Outlook → классификация вложений (КП/смета/скан/документ) | `mail_push_service`; `POST /api/mail/push` | [ALGO-mail-intake.md](ALGO-mail-intake.md) | ✅ |
| intake/les_md | LES.md — файл-контекст папки (привязка к проекту) | `les_md_service`; чат «пойми папку …» | [ALGO-les-md.md](ALGO-les-md.md) | ✅ |

## 5. Инфраструктура / Операции / Версии

| Суб-модуль | Назначение | Точки входа | Док | Статус |
|---|---|---|---|---|
| infra/runtime | топология (proxy:8050 / sovushka:8051 / mlx:8080 / qdrant:6333) | `proxy_server.py`, `sovushka_ng.py`, `mlx_host.py` | [PROXY_ARCHITECTURE.md](../PROXY_ARCHITECTURE.md) ✅ · топология в [CODE_MAP.md](CODE_MAP.md) (INFRASTRUCTURE_v2.0 → archive) | ✅ |
| infra/mlx | TTL-выгрузка, memory-guard, профили памяти | `backend/mlx_adapter`, `mlx_host.py` | [MLX_GUIDE.md](../MLX_GUIDE.md), [RUNTIME_MEMORY_PROFILES.md](../RUNTIME_MEMORY_PROFILES.md) ✅ | 🟡 |
| ops/deploy | dev→рантайм cp-деплой + stamp; откат | `tools/deploy_to_runtime.py`, `tools/restore_runtime.sh` | [SKILL.md](../SKILL.md) 🟡, [RELEASE_LEDGER.md](RELEASE_LEDGER.md) | 🟡 |
| ops/versioning | единый центр версий + divergence repo↔runtime | `version_service`; `GET /api/version` | [RELEASE_LEDGER.md](RELEASE_LEDGER.md), [VERSIONING.md](VERSIONING.md), [releases.md](releases.md) | 🟡 |
| ops/service-sources | видимый реестр служебных источников для смет и нормоконтроля | `service_source_registry`; `routers/service_sources.py`; `config/service_sources.yaml`; GUI `sovushka/pages/instrumenty.py`, чат `sovushka/pages/chat.py` | [SKILL.md](../SKILL.md), [CODE_MAP.md](CODE_MAP.md) | ✅ |
| ops/external-radar | радар внешних папок: configured roots + filemap + in-place `source_path` без reindex/OCR/LLM | `external_radar_service`; `GET /api/external-radar/summary`; GUI Самовар | [ALGO-external-radar.md](ALGO-external-radar.md) | ✅ |
| ops/test | гейт (verify/test/smoke-basic) | `Makefile`, `tools/basic_function_smoke.py` | [TEST_INVENTORY.md](TEST_INVENTORY.md) 🟡 | 🟡 |
| install | сборка/инсталляторы Mac/Win/Linux | `tools/build_*`, `installers/` | [INSTALL_RUNBOOK.md](INSTALL_RUNBOOK.md) ✅, [PLATFORMS.md](PLATFORMS.md) ✅ | 🟡 |

**✅ исправлено:** SKILL/TEST_INVENTORY → v0.23/~2063/smoke-basic done; PROXY_ARCHITECTURE → `les_meta_qwen.db`; INFRASTRUCTURE_v2.0 (мёртвое) → archive. Версии (3 оси) объяснены в [RELEASE_LEDGER.md](RELEASE_LEDGER.md); 0.23.N.P внедрено в `version_service`. В 0.23.6.2 добавлены checksum для backup/restore и сужены дефолтные trusted loopback/proxy-сети; в 0.23.6.3 скрепка чата стала реальным контекстом/payload scope; в 0.23.6.4 закреплены светлая тема по умолчанию, скрытая панель артефактов и OpenAI-compatible `gpt-4.1` fallback; в 0.23.6.5 добавлен явный GUI-контроль открытия артефактов и управляемый fail-path чтения вложений; в 0.23.6.6 source chips открывают citation drawer без fake-open; в 0.23.6.7 router-primary стал explicit opt-in, чтобы убрать 12s latency fallback; в 0.23.6.8 read-вложение стало видимым файлом следующего сообщения, plain file-reading идёт без глобального RAG, direct/router LLM без облачного ключа уходит в локальный MLX; в 0.23.6.10 `make ship` стал быстрым итерационным gate, `make ship-full` — полным release gate с retry post-smoke; в 0.23.6.11 нормоконтрольный чат отдаёт defense-report и top-level `defense`; в 0.24.0.1 служебные источники доступны из чата отдельной панелью.

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
