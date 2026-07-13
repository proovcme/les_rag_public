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

## 0. Core Runtime (модули, active state, scoped evidence)

Локальный 24-ГБ профиль держит основную `Qwen3.5-9B-OptiQ-4bit` тёплой до часа. Единый
реестр/default моделей — `proxy/local_model_registry.py`; env/GUI-выбор оператора выше default. Проверка ответа по умолчанию
идёт через `rules`, поэтому отдельная validator-LLM не вытесняет main после каждого хода;
критический memory-guard сохраняет право выгрузить main ниже 4 ГБ RAM или при реальном swap-давлении,
но не принимает накопленный macOS swap за аварию после восстановления свободной RAM.

| Суб-модуль | Назначение | Точки входа | Док | Статус |
|---|---|---|---|---|
| core/modules | лёгкий реестр профессиональных модулей LES: smeta, normcontrol, BIM/QTO, docs_review, procurement, contracts, project RAG; router выбирает модуль, но не решает предметную область | `les_module_service`, `active_state_service`, `scoped_rag_builder`, `skill_snippet_registry`, `tool_trace_policy` | [ALGO-routing.md](ALGO-routing.md) | ✅ |
| core/chat-evidence | application-граница общего model-first RAG после scope/route и deterministic tools: retrieval → context/evidence packet → model answer → validation → sources/trace/history. Router передаёт три явных typed-контракта `EvidenceRequestContext`, `EvidenceRuntimeDeps`, `ResponseBoundary`; namespace capture запрещён | `proxy/services/chat_evidence_application_service.py`, `proxy/routers/chat.py`, `retrieval_service`, `evidence_packet_service`, `saferag_service` | [ALGO-evidence-packet.md](ALGO-evidence-packet.md) | 🟡 |
| core/tool-harness | controlled registry/executor для инструментов: карта датасета, indexed source search/read, PDF/Excel indexed readers и read-only filesystem; возвращает `les_tool_result_v1` с sources/missing/warnings/trace, без финальных предметных решений; общий чат умеет одношаговый model-selected loop shortlist→JSON calls→executor→model final; Sovushka dry-run показывает тот же интерфейс `Registry/Shortlist/Call` | `tool_harness_service`, `proxy/routers/tools.py`, `tools/les_tool_harness.py`, `routers/chat.py`, Sovushka Documents dry-run | [ALGO-tool-harness.md](ALGO-tool-harness.md) | ✅ |

## 1. Смета (ценообразование, 0 LLM в расчёте — ADR-11)

Текущая карта сметного режима — [SMETA_MECHANICS.md](SMETA_MECHANICS.md). Сквозной поток и эталон
(позиция = **11813.04**, смета 2× = **23626.08**) — [ALGO-smeta.md](ALGO-smeta.md).
**Скилл-плейбук (для агента и ЛЕС): [skills/smeta/SKILL.md](../skills/smeta/SKILL.md).**
Понятное описание живого модуля, его данных, потока и проблем —
**[SMETA_MODULE_EXPLAINED.md](SMETA_MODULE_EXPLAINED.md)**.

С 0.24.0.382 старый поштучный orchestrator физически удалён. Один model-owned batch-диалог вызывает
`search_norms_batch`, `read_norms_batch`, затем `submit_lsr_mapping`; после этого код один раз считает
и собирает XLSX. Обязательных resource/impact/dominant review и отдельного finish-вызова нет.

| Суб-модуль | Назначение | Точки входа | Док | Статус |
|---|---|---|---|---|
| smeta/core | model-first PDF→ЛСР: единая публичная application-граница, один batch tool-loop модели, три инструмента, один расчёт и XLSX. Ordinary/PDF orchestration находится в `smeta_chat_application_service`, а smeta transport/RAG/prompts/parsers — в `smeta_chat_adapter_service`; chat сохраняет request и общий response/history contract. Код проверяет только ссылки/единицы/арифметику и не выбирает нормы. Legacy harness остаётся private implementation adapter до физической миграции | `proxy/smeta_core/{application,contracts,integrity,norm_browser,source_intake,document_workflow,calculator,resource_normalizer,lsr_renderer,workflow,unit_contract}.py`, `proxy/services/{smeta_chat_application_service,smeta_chat_adapter_service,prompt_registry_service,rim_lsr_trace_service,rim_trace_xlsx_service,smeta_user_message_service,fsem_machinist_service}.py`, `proxy/routers/{chat,chat_history}.py`, `sovushka/pages/chat.py`, `skills/smeta/{SKILL.md,references/gesn-storage.md,references/runtime-agent.md}` | [SMETA_MODULE_EXPLAINED.md](SMETA_MODULE_EXPLAINED.md) · [modules/smeta-core.md](modules/smeta-core.md) | 🟡 |
| smeta/mechanics | предметная карта ВОР/РИМ/ГЭСН/ФГИС/КАЦ и границы model↔code; верхняя PDF→ЛСР схема актуализирована, нижние direct/harness-слои требуют сжатия после удаления legacy маршрутов | `proxy/smeta_core`, `chat.py`, `smeta_user_message_service`, legacy `estimate_harness_service`, `quantity_trace_service`, `lsr_assembly_service` | [SMETA_MECHANICS.md](SMETA_MECHANICS.md) | 🟡 |
| smeta/system-dataset | модульные RAG-источники отделены от project/user datasets: typed MetaDB identity `system/smeta`, отдельный scope и автоматическое подключение только к smeta-turn; generated cards идут в `SMETA_SERVICE_Index` | `system_dataset_service`, `qdrant_adapter.MetaDB`, `document_router`, `scope_service`, `routers/chat.py`; datasets `SMETA_SERVICE_Index`, `SMETA_RU_NORM_*`, `GESN_NORMS_2022_PDF` | [CODE_MAP.md](CODE_MAP.md) | ✅ |
| smeta (поток) | объём ВОР → … → ВСЕГО; сметные lookup/calculation tools без финального visible-answer из кода | `smeta_chat_service`, `deterministic_policy_service` | [ALGO-smeta.md](ALGO-smeta.md) | ✅ |
| smeta/lsr | сборка позиции→Всего→свод; РИМ-трасса (графы 2-12); XLSX форма **ЛСР РИМ** по Приложению №3/421-пр (одно/многопозиц.) | `lsr_assembly_service`, `rim_lsr_trace_service`, `rim_trace_xlsx_service`, `fsem_machinist_service`; `POST /api/lsr/{assemble,rim-trace,lsr-trace}[/export]`; MCP `les_lsr_assemble` | [ALGO-lsr-assembly.md](ALGO-lsr-assembly.md) | ✅ |
| smeta/gesn | норма ГЭСН → ресурсы (расход×объём); canonical machine base `data/smeta_base/les_smeta_base.sqlite` (`norms/resources`), raw/unified parquet только source/staging; update pipeline `raw/cache → unified parquet → SQLite → SMETA_SERVICE cards`; source и runtime защищены conservative resource-identity dedupe, audit/manifest показывают схлопнутые дубли; фоновый PID проверяется немутирующим cross-platform probe | `gesn_service`, `gesn_update_service`, `process_status`; `tools/gesn_update_from_fgis.py`, `tools/gesn_unify_base.py`, `tools/build_smeta_structured_base.py`, `tools/build_smeta_service_rag.py`; Make `smeta-base*`; `GET /api/lsr/gesn[/{code}/expand]`, `POST /api/service-sources/gesn_base/fgis-update`; GUI «Инструменты → ГЭСН → скачать/обновить»; MCP `les_gesn_*` | [ALGO-gesn.md](ALGO-gesn.md) | ✅ |
| smeta/fgis | цена ресурса по коду из «Сплит-формы» ФГИС ЦС; единый операторский updater получает публичный каталог, последнюю книгу каждой ценовой зоны и полный ГЭСН pipeline; visible-книги управляются `pricebook_manifest.json`, duplicate/scratch parquet не показываются в discovery; Windows status polling не вызывает `os.kill` и не завершает updater | `fgis_price_service`, `fgis_update_service`, `process_status`, `tools/fgis_full_update.py`; `/api/prices/*`, `/api/service-sources/fgis/update[/status]`; GUI «Источники данных → СКАЧАТЬ ФГИС ЦС»; MCP `les_price_lookup` | [ALGO-fgis-price.md](ALGO-fgis-price.md) | ✅ |
| smeta/artifact | оформление сметных таблиц в отдельный Markdown-artifact и выгрузку XLSX/CSV: извлекает уже написанные моделью ВОР/стоимость/развилки, считает видимые суммы, делает `lsr_rim_display_form_v1` отдельным способом выдачи сметного артефакта, добавляет Markdown/XLSX ЛСР РИМ в 12-графной форме Приложения №3/421-пр и отдельные источники, а исходные таблицы оставляет расшифровкой; на stage `norm_candidates` строит рабочую таблицу `ВОР ↔ кандидаты ГЭСН` из executed `search_norm` trace и отдаёт её даже при пустом финальном LLM-тексте, а следующий ход “деньги по ним” считает по candidates текущего/предыдущего trace; если построен проверенный `lsr_rim_trace_form_v1`, visible answer показывает именно расчётную РИМ-ЛСР с ценами/книгой/статусом, без конкурирующей модельной placeholder-таблицы; legacy compact только через `LES_SMETA_COMPACT_CHAT_TABLES=1`; не выбирает работы, нормы или ставки | `smeta_artifact_service`, `chat.py` payload `artifact`, `sovushka/pages/chat.py`, `/api/smeta-artifacts/download` | [SMETA_MECHANICS.md](SMETA_MECHANICS.md) | ✅ |
| smeta/kac | конъюнктурный анализ цен (≥3 КП на материал); web-discovery принимает только model-selected exact product query, сильный артикул и три разных supplier domains, иначе цена остаётся missing | `kac_service`, `kac_web_service`; `/api/kac/*`; MCP `les_kac` | [ALGO-kac.md](ALGO-kac.md) | ✅ |
| smeta/stesn | коэффициент стеснённости (k к ОЗП/ЭМ) | `stesnennost_service`; `/api/lsr/stesnennost/*`; MCP `les_stesnennost` | [ALGO-stesnennost.md](ALGO-stesnennost.md) | ✅ |
| smeta/object | мутное ТЗ «дай смету на …» → model-first декомпозиция: модель сама раскладывает объект, харнесс даёт `search_norm`/`add_position`; при приложенной таблице direct Smeta отдаёт модели само вложение, skill и scoped RAG без промежуточного табличного калькулятора; если это спецификация, модель сначала собирает мост specification→BOR: поставка/работы/parent-child/quantity trace, и только затем ведёт к нормам и смете; `search_norm` использует typed SQLite-light `smeta_norm_store_v5` как широкий индекс норм с норм-карточками и навигацией (семья/элемент/действие/условия/ресурсы/provenance/`model_card`/`navigation`/`nearby_norms`/decision checklist), ранжирует редкие технические совпадения поверх общих FTS-хитов и видит overlay `ГЭСНм10` для СКС/ВОЛС; общий `candidate_selection_v1`, код проверяет нормы/единицы/объёмы и считает только прошедшие gates; прямые объёмы идут как `quantity_candidates`/`quantity_trace` с provenance, а статус ГЭСН/ФГИС/КАЦ/коэффициентов попадает в результат | `estimate_harness_service`, `smeta_norm_store`, `candidate_selection_service`, `estimate_math_service`, `quantity_trace_service`, `nr_sp_service`, `evidence_contract`, `tools/gesn_fgis_overlay_import.py`; готовые объектные составы удалены | [ALGO-object-estimate.md](ALGO-object-estimate.md) 🟡 · [ALGO-gesn.md](ALGO-gesn.md) ✅ | 🟡 |
| smeta/ontology | доменные понятия (ВОР/КАЦ/ЛСР/КС) | `smeta_ontology_service`; MCP `les_glossary` | [ALGO-smeta-ontology.md](ALGO-smeta-ontology.md) ✅ · [smeta_ontology.md](smeta_ontology.md) ✅ (генерится) | ✅ |
| smeta/bor | спецификация Ф9 → ВОР работ | `spec_to_bor_service`; `/api/bor/{id}/from-spec*` | [ALGO-spec-to-bor.md](ALGO-spec-to-bor.md) | ✅ |
| smeta/indices | индексы изменения сметной стоимости (Минстрой ИФ/09) | 📋 v0.26+ ([../ROADMAP_TO_V1.md](../ROADMAP_TO_V1.md)) | — | 📋 |

**✅ исправлено (437f1aa):** ALGO-smeta/object — ранний объектный слой и ГЭСН-кандидаты. **Новая текущая правда с 0.24.0.20:** режим «Смета» не использует готовые объектные составы как маршрут продукта. Модель первична и сама раскладывает объект; харнесс только даёт инструменты (`search_norm`, `add_position`) и gates по нормам/единицам/объёмам. С 0.24.0.24 `candidate_selection_v1` вынесен в общий `candidate_selection_service`: shortlist, причины score и действие для ясного лидера/модельной развилки теперь reusable для следующих модулей. С 0.24.0.30 smeta harness различает типы нормативных баз (`ГЭСН38` ≠ `ГЭСНм38`) и считает массовые `metal_assembly`-позиции через `mass_t`/ЛСР-калькулятор. С 0.24.0.31 сметный чат показывает краткую сводку, а полная ресурсная расшифровка, структура стоимости, НР/СП и условия работ уходят в артефакт. С 0.24.0.47 извлечение числовых слотов из ТЗ принимает Office-разделители тысяч/десятых без объектных спец-веток; явные объёмы/площади/массы работ могут задавать физический объём позиции напрямую, а auto-чат узко переводит запросы «рассчитать сметную стоимость работ + явное количество» в smeta harness вместо table/RAG. С 0.24.0.49 одинаковые direct-позиции с тем же кодом и тем же физическим объёмом не умножают сумму: первая считается, повторы получают `skipped_duplicate`; direct-расчёты не показывают в заголовке служебную площадь, если она пришла только от планировщика. С 0.24.0.50 prompt registry подмешивает JSON role-pack `config/prompts/smeta_estimator_role.json` (`experienced_estimator_v1`, `smeta_work_plan_v1`) как роль опытного сметчика РИМ/ГЭСН; это первый образец схемы skill + JSON role-pack + code guards для будущих ролей. С 0.24.0.51 direct quantity больше не валидируется magnitude-guard по служебной геометрии планировщика: guard остаётся для формульных объёмов, а явные `volume_m3`/`mass_t`/`area_m2`/`piece_count` считаются авторитетным физическим количеством. С 0.24.0.52 объектная площадь больше не становится direct `area_m2` для всех м2-позиций; role-pack/skill закрепляют model-first декомпозицию без объектных if-шаблонов. С 0.24.0.53 широкая объектная смета без площади/габаритов не считает микросмету по модельной заглушке `1 м2`, smetnik-layer стал вторым ходом модели по tool-result payload, а `smeta_dialog_state_v1` сохраняется в `retrieval_trace_json` для продолжения диалога. С 0.24.0.55 явное пользовательское «придумай/прикинь/по допущениям» включает сценарную прикидку: модель может задать геометрию и слоты как `assumptions`, код считает их отдельно помеченным сценарием, а без такого разрешения модельная площадь по-прежнему не становится evidence. С 0.24.0.56 видимый сметный слой и память диалога русифицируют внутренние имена параметров (`element_type`, `wall_length_m`, `area_total_m2` и т.п.) в человеческие сметные формулировки. С 0.24.0.57 mode tool-contracts больше не инжектятся в системный prompt; сметный JSON role-pack остаётся машинным контрактом tool-loop, а системные тексты редактируются оператором через prompt overrides. С 0.24.0.84 `search_norm` использует `smeta_norm_store_v3`: in-memory SQLite/FTS-проекцию существующих норм с типом базы, сборником, единицей, provenance, ресурсами, hints по семье/элементу/действию и русской `model_card` по условиям применимости; индекс расширяет candidate pool и даёт модели понятный норм-профиль, но не заменяет модельную декомпозицию. Старый объектный слой и его YAML-данные удалены; auto-запросы на объектную смету без явного количества не перехватываются быстрым сметным каналом.

**0.24.0.85:** `add_position` переносит условия выбранной нормы в `norm_questions`: строка может быть рассчитана, но общий итог остаётся `partial`, пока пользователь/файл не подтвердит ключевые условия применимости нормы; модель видит эти вопросы и продолжает диалог по-русски.

**0.24.0.86:** `smeta_norm_store_v4` и `search_norm.norm_navigation` дают модели карту нормы: сборник/подраздел, вопросы применимости, РИМ-границу и соседние нормы (`nearby_norms`), чтобы модель выбирала разделы/вопросы по нормам, а код оставался калькулятором и bind-проверкой.

**0.24.0.97:** `smeta_norm_store_v5` добавляет в норм-карточку явные `applicability`, `price_inputs` и `decision_order`; `search_norm.norm_navigation` несёт `norm_decision_context`, а `estimate_harness` отдаёт `quantity_candidates` и `smeta_service_sources`, чтобы модель видела происхождение объёмов и состояние ценовых/нормативных источников без объектных шаблонов.

**0.24.0.101:** batch-сметчик больше не выбирает “первую применимую” норму из неоднозначного shortlist сам. После `search_norm` он вызывает второй ход модели с компактным списком кандидатов; модель выбирает `norm_code` из shortlist или задаёт вопрос, а `add_position` остаётся единственным местом расчёта и проверки единиц/применимости/provenance.

**0.24.0.102:** `_normalize_work_item` больше не переписывает `work_family`/`element_type` за модель по regex-сигналам текста. Смысловые поля остаются ответственностью модели; код нормализует только action/unit aliases и отдаёт несовпадения как trace `intent_hints`, не используя их для поиска или расчёта.

**0.24.0.103:** старый пошаговый `{tool,args}` сметный loop удалён из runtime-пути. Живой контракт один: `smeta_work_plan_v1`. Если модель возвращает legacy tool-call, harness просит переписать его в batch JSON, а не запускает второй prompt/протокол сметчика.

**0.24.0.104:** `BATCH_TOOL_CONTRACT` стал тонким машинным контрактом: только JSON shape и допустимые machine ids, без профессиональных правил сметчика. Правила вложенных ВОР/спецификаций (`для 1 изделия` × родительское количество, не задваивать родительскую сборку и детальную расшифровку) живут в role-pack/skill. `_object_area_from_text` больше не принимает произвольные площади строк ВОР (`0,07 м²/шт`) за площадь объекта.

**0.24.0.105:** прямые количества из текста разделены на `quantity_candidates` и расчётные слоты. В широком ТЗ/ВОР/объектной смете код больше не использует найденные `volume_m3`/`area_m2`/`mass_t`/`piece_count` как глобальный объём любой позиции; модель должна привязать нужный кандидат в `slots` конкретной work-позиции. Автопривязка direct quantity остаётся только для узкого запроса “посчитай эту работу с этим количеством”.

**0.24.0.106:** smeta chat больше не душит длинные ТЗ/ВОР коротким planning-budget: для большого вложения work-plan получает динамический лимит ответа, а видимый smetnik-comment получает тот же `harness_question` (с вложением/историей) и compact excerpt. Голосовой слой дополнительно фильтруется от ложных фраз “исходные оборвались/пришлите продолжение”, если это не следует из расчётного payload.

**0.24.0.107:** если harness полностью заблокировал смету (`blocked`, 0 computed), видимый ответ больше не является кодовой таблицей отказов. Модель получает полный `harness_question` и компактный `blocked_harness_advisory`, после чего сама даёт сметный разбор/ведомость количеств/ценовые пробелы; кодовый результат остаётся trace/artifact и калькуляторным протоколом.

**0.24.0.108:** явный режим «Смета» теперь сначала отдаёт полный вопрос/вложение/историю сметчику-модели без запуска кодового harness. Кодовый harness остаётся fallback и будущим калькулятором/проверкой единиц/цен/provenance, но больше не является предварительным разрешителем видимого ответа.

**0.24.0.109:** direct smeta mode при выбранной области получает компактный RAG-пакет: retrieved chunks/source-map + navigation memory. Модель видит источники и карту корпуса до ответа, но code harness не возвращается как автор видимой сметы.

**0.24.0.110:** direct smeta RAG-пакет больше не включается по автоматическому `TABLE`/широкому inference, если оператор только приложил файл. Без явного dataset/project scope модель работает по вложению, а не по случайному соседнему корпусу.

**0.24.0.113:** short-lived `smeta_table_calculator` удалён из direct smeta. Табличное вложение снова читает модель; skill говорит ей сначала делать ВОР из спецификации, а код не подсовывает промежуточную классификацию/арифметику.

**0.24.0.114:** если direct smeta модель не вернула видимый ответ, старый code harness больше не собирает смету вместо неё по умолчанию. Кодовый fallback возможен только явным аварийным флагом `LES_SMETA_CODE_FALLBACK_AFTER_MODEL_FAIL=1`.

**0.24.0.254:** direct smeta для табличной ВОР получает source-row coverage contract: каждая строка `section/source_no/name/unit/qty` должна попасть в ЛСР с `SRC`-маркером, а строки без выбранного шифра нормы остаются в форме с `0.00` и примечанием. Длинные ВОР получают больший лимит генерации, а checked RIM visible answer показывает покрытие `bound/input` при partial trace, чтобы потеря строк не выглядела как полная ЛСР.

**0.24.0.255:** smeta skill стал предметным playbook сметчика: ценообразование РИМ/ГЭСН, ресурсы, ФГИС/pricebook, НР/СП, КАЦ/КП, карта локальной базы (`data/gesn_base/*.parquet`, `data/price_base/*.parquet`, `SMETA_SERVICE`) и правило “что смог — оценил; чего не хватает — строка ЛСР с 0.00/пустой ценой”. System prompt только маршрутизирует к `skills/smeta/SKILL.md` и не тащит предметную базу; role-pack закрепляет `code_does_not_select_norms`/`code_arithmetic_only_after_visible_model_choice`; активные частные шаблоны аварийного питания убраны.

**0.24.0.256:** direct smeta prompt теперь физически получает компактные `skill_snippets` из `skill_snippet_registry`: сметная модель видит рабочее правило “модель выбирает норму, код только раскрывает ресурсы/цены/НР/СП и считает после видимого выбора”, локальные семейства ГЭСН/ГЭСНм и книги цен. Это не candidate shortlist и не кейсовый шаблон, а runtime-доставка skill-методики до модели.

**0.24.0.257:** direct smeta получил model-selected norm lookup перед финальным ответом: модель сама возвращает JSON-вызовы `search_norm` по нормируемым работам, код только исполняет read-only lookup и передаёт найденные нормы обратно модели. Результаты пишутся в `retrieval_trace.smeta_norm_lookup`; это не code-side выбор нормы и не финальная смета.

**0.24.0.258:** direct smeta запрещает модельные ставки/рубли без checked trace: если есть norm lookup, модель должна скопировать полный `norm_code` в Обоснование, чтобы расчётный слой раскрыл ресурсы/цены, либо оставить строку с `0.00` и примечанием. Общие `ГЭСН 09`/`ГЭСН 15`/`ГЭСНм10` не считаются основанием для денег.

**0.24.0.259:** direct smeta loop замкнут до расчёта: после model-selected `search_norm` модель отдельным JSON-шагом выбирает `norm_code` только из lookup candidates и указывает количество/единицу; код валидирует, что код был в candidates, строит checked `lsr_rim_trace_form_v1` и отдаёт деньги из РИМ trace. Colon-коды `ГЭСНм:38-...`/`ГЭСНм:10-...` нормализуются в trace. **0.24.0.260:** structured norm-choice больше не предлагает модели оставлять строку пустой из-за приблизительного кандидата: если candidates есть и объём есть, модель выбирает ближайшую норму и пишет допущение; РИМ trace принимает инженерные счётные измерители (`статив`, `система`, `цепь (линия)` и т.п.) как расчётные count/line aliases, чтобы выбранные моделью нормы не превращались в `unit_conflict`-нули. **0.24.0.261:** РИМ trace принимает `отверстия` как count alias и умеет после модельного выбора нормы переводить поштучные элементы с габаритом `400x400 мм` в площадь (`шт × м2/шт / измеритель нормы`), чтобы строки вроде лючков/проёмов не выпадали из БАП-ЛСР. **0.24.0.262:** smeta direct получил ТЗ-stage gate: сырой ТЗ/ВОР/спецификация останавливается на этапе `ВОР -> кандидаты ГЭСН` и Excel round-trip; structured norm-choice/РИМ-деньги запускаются только по проверенной таблице соответствия ВОР-ГЭСН или явной команде принять candidates модели без ручной проверки. **0.24.0.263:** stage `norm_candidates` теперь отдаёт не только текст, а полноценный artifact/XLSX/CSV `ВОР ↔ кандидаты ГЭСН` из executed `search_norm` trace; строки без найденных candidates остаются в проверочной таблице с пустым кодом и примечанием, без остановки процесса. **0.24.0.264:** явная просьба “таблица кандидатов/кандидаты ГЭСН/этап 1” по сырому ВОР остаётся в `norm_candidates`, даже если оператор не просит ЛСР или деньги. **0.24.0.265:** ручная Excel-проверка больше не описывается как обязательный барьер: базовый UX — candidates first, затем “деньги по ним” по доступным candidates; missing остаётся 0.00/пусто с примечанием. **0.24.0.266:** candidates artifact не теряется при пустом финальном LLM-тексте, а “деньги по ним” переиспользует последний candidates trace текущей сессии при selector-error. **0.24.0.267:** stage detector для `norm_candidates` смотрит только на текущее сообщение/вложение, поэтому история с “дай кандидатов” не возвращает второй ход “деньги по ним” обратно в этап 1. **0.24.0.268:** СПб без явного периода больше не выбирает scratch-книгу `spb_refresh` перед полноценной `spb_2kv2026`; это закрывает нулевую БАП-ЛСР при `bound_rows>0`. **0.24.0.269:** явное “деньги по ним/по этим кандидатам” переиспользует последнюю candidate trace из сессии перед новым lookup, чтобы повторный pricing не менял нарезку ВОР 9/10 строк. **0.24.0.270:** live smeta route получает `stage` и `use_previous_candidates` из model-owned workflow JSON decision; regex stage/follow-up остаётся только legacy/rollback, а `explanation` не запускает расчётные инструменты. **0.24.0.271:** smeta norm lookup больше не режет ВОР дефолтным `max_calls=10`; при `source_no` технический лимит масштабируется от числа строк, чтобы модель могла покрыть весь source-row contract. **0.24.0.272:** тот же coverage contract работает для реального UI/PDF `read` пути: detector считает строки Markdown/PDF-таблицы `№/Наименование/Ед./Кол-во`, поэтому обычный запрос “Дай оценку стоимости и ЛСР” по прикреплённой ВОР не сваливается обратно в 10 lookup-групп из-за отсутствия JSON `source_no`. **0.24.0.273:** structured norm-choice получает `norm_card` candidates (domain/actions/conditions/resources/navigation) и обязан оставлять `norm_code` пустым при явном mismatch, вместо того чтобы считать “ближайшую” неверную норму; norm-store/search scoring получил action hints для демонтажа/грунтования/шпатлевки и штрафы за конфликт действия. **0.24.0.274:** если строгий model norm-choice не возвращает строку или оставляет `norm_code` пустым, direct smeta сохраняет эту lookup-строку в ЛСР как `нужен подбор нормы` вместо потери строки; деньги считаются только по accepted rows. **0.24.0.275:** разрыв `Состав работ` закрыт на уровне источников: `gesn_api_service`/parquet поддерживают `work_steps`, `gesn_service` и `smeta_norm_store_v5` поднимают их в `model_card.work_composition`, store также читает `SMETA_SERVICE/smetnoedelo_api/**/codes/*.md`; structured norm-choice получает эти steps в `norm_card` и сверяет их моделью.

**0.24.0.298:** direct smeta получил второй model-owned audit после structured norm-choice и до РИМ-расчёта: `_smeta_review_structured_norm_choice` проверяет черновые строки по тем же candidates/norm_card и возвращает `approve|replace|unbound`. Код не выбирает норму сам: он только проверяет, что `replace.norm_code` дословно есть в candidates данного lookup, и дальше считает подтверждённые строки или оставляет строку `нужен подбор нормы` с `0.00`/причиной.

**0.24.0.299:** `search_norm` чинит generic finish lookup: когда модель прислала `element_type=finish`, `action=устройство`, но в тексте явно есть грунтование/шпатлевка/оклейка/окраска, поиск уточняет retrieval-route до `primer/putty/wallpaper/painting` и поднимает same-operation candidates. Это слой показа норм модели, не кодовый выбор строки ЛСР.

**0.24.0.325:** pricing-route для ВОР расширяет model-visible окно норм (`lookup top_k=25`, prompt/choice candidates=20) и снимает скрытый review-stop для неточного демонтажа: ревизор теперь должен выбирать ближайший защитимый аналог из candidates, а `unbound` оставлять только при пустых/чужих/несовместимых candidates. `search_norm` поднимает ремонтные `ГЭСНр63` для реечных потолков и `ГЭСН17-01-010-*` для ревизионных люков; защитное укрытие плёнкой не разрешается закрывать штукатуркой/грунтовкой/окраской. Код по-прежнему не выбирает норму, а только показывает карточки, проверяет provenance выбранного моделью шифра и считает.

**0.24.0.326:** `finish/hatch` route обрабатывает `люк/люч/ревизион` раньше окраски, чтобы формулировка “ревизионный лючок под покраску” не уходила в отделочные окраски. False-analog guard запрещает временное защитное укрытие считать декоративной/самоклеящейся ПВХ-плёнкой или натяжным потолком, а ГКЛ-проём под ревизионный люк — люком на крыше, фасадным/оконным/дверным проёмом или акустической дверью.

**0.24.0.327:** structured norm-choice считает допустимым для РИМ только candidate, который модель видела в lookup и который сам lookup не пометил `applicability_status=rejected` или `unit_compatible=false`. Это не выбор нормы кодом: rejected/несовместимая карточка не может стать деньгами, строка остаётся в ЛСР с `нужен подбор нормы`/0.00.

**0.24.0.328:** generic `finish` lookup для подготовки/ремонта потолочной поверхности маршрутизируется в `ceiling`/ремонтный слой до `hatch`, чтобы слово “лючков” в контексте последующего восстановления не прятало от модели `ГЭСНр63`. Rejected/unit-mismatch строка в ЛСР сохраняет исходное описание ВОР и показывает причину отказа (`candidate_rejected_by_lookup`/`candidate_unit_mismatch_by_lookup`), вместо подмены строки названием плохого candidate.

**0.24.0.329:** direct selector и model-owned review audit сохраняют в видимой ЛСР исходные `work_description`/`unit_hint` для всех строк ВОР. Выбранная/заменённая норма остаётся в графе `Обоснование`, но название строки больше не подменяется title карточки нормы.

**0.24.0.330:** `search_norm` показывает модели более правильные candidates для двух общих ВОР-типов: временное защитное укрытие поверхностей уходит в `protective_cover`/сборник 46 без возврата декоративной ПВХ-плёнки и натяжных потолков, а штучные скобы для крепления гофры маршрутизируются как `fastener` вместо `pipe` и не поднимают светильники/изоляторы.

**0.24.0.331:** smeta model-owned steps (`direct`, structured norm-choice/review) по умолчанию используют локальный MLX даже при доступном глобальном cloud API key. Cloud для сметы включается только явным `LES_SMETA_PROVIDER`/step-provider override; это убирает скрытую смену модели между локальными и облачными тестами.

**0.24.0.332:** local structured norm-choice/review больше не получает весь `lookup_results` одним монолитным prompt: для MLX включён batching по 5 строк (`LES_SMETA_NORM_CHOICE_BATCH_SIZE`). Каждый батч остаётся model-owned, выбирает шифры только из candidates и проходит review отдельно; наружу возвращаются глобальные `lookup_index`, объединённые строки и batch trace.

**0.24.0.333:** после live БАП batching default для local MLX уменьшен до 2 строк, а selector `max_tokens` считается от строк текущего батча. Батч 5 оставлен как явная настройка, но не как дефолт: текущие norm-card payload на 5 строк всё ещё перегружали локальную модель.

**0.24.0.334:** smeta batching стал наблюдаемым в live UI: structured norm-choice пишет start/done каждого батча в backend log (`[SMETA_BATCH]`) и отдаёт SSE-событие `smeta_batch`; Совушка показывает текущий диапазон строк, принято/добор и пишет те же этапы в операторский лог. Если батч не вернул строк, строки не теряются, а идут дальше как `нужен подбор нормы` с причиной.

**0.24.0.335:** live БАП показал 165 секунд тишины до первого batch event, поэтому `/api/chat/stream` получил `smeta_step` для крупных стадий сметного маршрута: RAG-context, workflow decision, norm lookup, norm choice, final answer. Совушка показывает эти этапы в пузыре и пишет их в операторский лог; backend пишет `[SMETA_STEP]`.

**0.24.0.336:** smeta norm-choice перестал давить local 9B большим candidate payload: локальный default `LES_SMETA_NORM_CHOICE_CANDIDATES` теперь 5 candidates на строку (cloud default 8), `norm_card` сжат до коротких `domain/work_steps/conditions/resources/collection`, а `[SMETA_NORM_CHOICE]` пишет `rows/candidates/prompt_chars/prompt_est_tokens`. Код не выбирает нормы; он только уменьшает меню, из которого выбирает модель.

**0.24.0.300:** smeta data/lookup audit fix: дефолтная книга цен теперь выбирается единым resolver-ом (`LES_DEFAULT_PRICEBOOK` → `spb_2kv2026`/`sankt-peterburg_2kv2026` → 2026), а не первым parquet по алфавиту; scratch-книги вроде `spb_refresh` скрыты из обычного списка и не становятся дефолтом. Strict `gesn_service.get_norm(..., strict_family=True)` не превращает bare-код в `ГЭСН`, если тот же номер есть в нескольких семействах; обычный `get_norm()` оставлен совместимым для legacy API. Model-facing `smeta_norm_store_v5` демотирует legacy-untyped parquet и не показывает пустые norm cards. Код не выбирает нормы, а чистит карту источников и расчетный default.

**0.24.0.301:** smeta cleanup после аудита: отсутствие pricebook больше не возвращает проверенную таблицу ВОР-ГЭСН или `MODEL-SELECTED NORM LOOKUP` в candidates-stage; raw specification без найденных норм/ценников остаётся stage `ВОР -> кандидаты`. Harness проверяет явно выбранный моделью шифр по локальной базе и считает его, не подменяя первым `search_norm` candidate; parquet overlay не стирает старые `norm_name/norm_unit` пустыми значениями, а `smeta_norm_store` даёт broad nearby-навигацию для одиночных typed-норм вроде `ГЭСНм38`.

**0.24.0.316:** ГЭСН-база сведена к одному боевому parquet: `data/gesn_base/gesn2022_unified.parquet` + audit JSON. Старые `gesn2022.parquet`/`gesn2022_v2.parquet` удалены из `data/gesn_base`; raw-докачка ФГИС и ручные импорты пишутся только в `storage/cache/gesn_fgis/`, затем `tools/gesn_unify_base.py` пересобирает unified. GUI «Инструменты» получил кнопку скачать/обновить ГЭСН из ФГИС ЦС; API запускает фоновый updater и отдаёт status/log. Strict lookup не схлопывает совпадающие bare-коды разных семейств, например `ГЭСН:38-01-001-01` и `ГЭСНм:38-01-001-01`.

**0.24.0.320:** smeta/GESN runtime-facing база переведена с parquet на одну canonical SQLite-базу `data/smeta_base/les_smeta_base.sqlite`: таблица `norms` хранит typed identity/name/unit/work_steps, таблица `resources` хранит ресурсные строки. `data/gesn_base/gesn2022_unified.parquet` остаётся source/staging слоем; `tools/build_smeta_structured_base.py` собирает SQLite и manifest качества. Нормы без `norm_name`/`norm_unit` не выдаются машине и фиксируются как excluded в manifest (`11849` norm_key на текущем снимке), вместо того чтобы светиться как пустые candidates.

**0.24.0.321:** smeta-base pipeline стал единым воспроизводимым путём: `tools/gesn_update_from_fgis.py` после ФГИС-download и unified parquet теперь строит structured SQLite и generated `SMETA_SERVICE` cards, а status API показывает unified/audit/structured/manifest/service_rag слои. Make targets: `smeta-base` (checked unified → SQLite → cards), `smeta-base-source` (raw/cache → unified → SQLite → cards), `smeta-base-update` (ФГИС → полный pipeline).

**0.24.0.115:** direct smeta отделён от `smeta_harness` на уровне prompt registry: видимый ответ получает отдельный prompt опытного сметчика с ролью, рабочей петлёй, путём «спецификация → ВОР → смета», дисциплиной источников/цен и стабильной формой ответа. Вход для direct-модели теперь обычный русский текст, а не машинный JSON payload.

**0.24.0.116:** RAG prompt усилен как роль опытного инженера-строителя/проектировщика: broad-запросы по корпусу должны давать инженерный обзор объекта/состава/технических решений/конфликтов, карта датасета остаётся навигацией, target-file запросы не заменяются похожими файлами, а служебные машинные слова скрываются из видимого ответа.

**0.24.0.122:** smeta direct/role-pack/skill закрепляют технологическую ВОР-арифметику для конструкций с явными операциями: модель сохраняет заданные разделы сметы, выводит 0-рублёвые этапы отдельно, считает массу/стыки/болты/долю затяжки как проверяемые объёмы до выбора нормы и не превращает отсутствие ценовых строк в отказ от ВОР.

**0.24.0.123:** smeta prompt/skill разделены по слоям: system prompt остаётся коротким поведенческим каркасом, `_render_smeta_role_pack()` подмешивает только компактный машинный контракт (статусы, типы цен, hard rules, visible answer contract, shape `smeta_work_plan_v1`), а подробная профессиональная методика живёт в `skills/smeta/SKILL.md` и полном JSON role-pack.

**0.24.0.124:** smeta direct-answer ограничен по форме: ответ должен быть завершённым, до 6 коротких разделов, с финальным «Итогом», без отказного вступления «нет денег» и без длинного чек-листа уточнений; strict-разделы оператора нельзя заменять спорными этапами вроде упаковки или нулевой логистики.

**0.24.0.126:** smeta role-pack/direct prompt получили общую числовую дисциплину без case-specific решений: любое существенное числовое утверждение требует расчётной трассы, конфликт исходных объёмов выводится через форму развилки договорной величины, прежняя оценка/xlsx/форма развилки в контексте считается источником сверки. Конкретные регрессии запрещено заносить в system/role-pack как готовые ответы; они живут в тестах/fixtures/skill-уроке. Добавлен единый документ [SMETA_MECHANICS.md](SMETA_MECHANICS.md).

**0.24.0.127:** конфликтная форма переименована в «форму развилки исходных объёмов» / `quantity_conflict_form_policy`, чтобы не путать её со сплит-формой ФГИС ЦС. Док [SMETA_MECHANICS.md](SMETA_MECHANICS.md) усилен: допустимые промежуточные результаты, continuation/change поверх предыдущей оценки, длинные ряды только через calculator/trace, direct answer без итоговых рублей без источника, давальческий 0 руб, смешанные источники и одинаковый физический объём в разных операциях.

**0.24.0.130:** НР/СП code-only ЛСР переведены с префиксной эвристики на системную классификацию по базе и номеру сборника нормы: `nr_sp_service` нормализует шифр в ключ `база:сборник`, сверяет его со справочником `collections`, затем использует текстовое совпадение только как fallback. Частные расчётные примеры в системные решения не добавлялись.

**0.24.0.131:** справочник НР/СП расширен по сборникам ГЭСН и ГЭСНм: прямой путь `code -> база:сборник -> НР/СП` покрывает больше общестроительных и монтажных сборников, поддерживает голые шифры из parquet-базы, а официальные подвиды внутри сборника могут переопределять общий сборник через `collection_match_priority`.

**0.24.0.132:** smeta role-pack/skill/direct prompt закрепляют обязательную попытку оценки стоимости работ по измеримой ВОР: незакрытая поставка и добор цен не блокируют блок `Стоимость работ`, а только понижают статус до `priced_partial`, `resources_expanded` или `scenario_estimate`; частные расчётные кейсы в system/role-pack не добавляются.

**0.24.0.133:** после live-регрессии direct smeta усилен: запрос на смету/стоимость/оценку по измеримой ВОР считается разрешением на сценарные допущения по работам, если пользователь их явно не запретил; сценарные рубли по работам должны идти до уточняющих вопросов и добора до `priced_final`.

**0.24.0.134:** smeta role-pack/skill/direct prompt получили приоритет РИМ/trace над свободным scenario: после model decision по норме расчётная трасса `calculation_trace` показывается раньше рыночной ставки; код остаётся только калькулятором выбранного моделью хода и не получает права выбирать операции/нормы.

**0.24.0.135:** smeta role-pack/skill/direct prompt расширяют свободу модели при явном "можешь придумать"/"по допущениям": модель сама выбирает нейтральные assumptions, даёт числовой диапазон до вопросов и не заменяет деньги списком добора. Запрос двух оценок рынок/РИМ требует сравнительную числовую таблицу со статусами источников; КП/ФГИС gaps понижают статус, но не отменяют scenario-цифры.

**0.24.0.136:** smeta visible answer переведён на компактное оформление: direct/harness prompt запрещает Markdown-заголовки `#`/`##`/`###` в обычном чат-ответе и требует короткие жирные метки секций; Совушка ограничивает размер `h1`-`h6` внутри `.sov-chat-md`, чтобы случайные заголовки не раздували пузырь ответа.

**0.24.0.137:** smeta role-pack сжат до тонкого машинного контракта (статусы, источники цен,
capabilities, порядок visible-секций, hard rules и колонки таблиц), direct prompt закрепляет
9-блочный smeta_direct ответ и обязательную сравнительную таблицу РИМ/ГЭСН vs рынок, а
`estimate_math_service` получил generic arithmetic/quantity audit helper для русских чисел,
кг↔т, сумм, процентов, partial matches и trace. Частные числа regression-кейса живут только в
`tests/fixtures/smeta` и проверяются no-case-constants тестом.

**0.24.0.138:** `_smeta_direct_model_answer` добавляет в prompt deterministic numeric audit context
по очевидным mass-таблицам вложения: сумма строк, сравнение с текстовым/табличным итогом и
partial match `rows_1_N`. Код остаётся калькулятором и не выбирает договорный объём.

**0.24.0.139:** numeric audit context дополнительно отдаёт `source_delta` между сравниваемыми
исходными итогами, чтобы direct-ответ показывал малое расхождение источников отдельно от крупного
расхождения состава строк.

**0.24.0.140:** smeta_direct закрепляет построчный расчёт работ для измеримых ВОР/спецификаций:
модель не должна заменять понятные строки работ несколькими укрупнёнными корзинами с широкой вилкой.
Видимый ответ показывает строку, количество, единицу, ставку/источник, статус и сумму, а диапазон
идёт только как сводка после строк.

**0.24.0.142:** smeta skill/role-pack получили универсальный режим `specification_to_bor`.
Спецификация больше не равна смете: модель сначала классифицирует строки как поставку, работы,
комплектующие, крепёж, расходники, подключения и испытания, сохраняет parent/child-иерархию,
строит ВОР-кандидат и только затем идёт к нормам/ценам. Новый `quantity_trace_service` считает
русские числа, parent×child и простые конверсии единиц после решения модели; он не выбирает работы
или нормы.

**0.24.0.143:** smeta direct numeric audit принимает markdown-таблицы DOCX с крайними `|`, поэтому
реальный табличный контекст вложений больше не теряет строки масс при расчётной сверке. Видимый
prompt очищен от утечки служебных самоинструкций: пользовательский ответ должен говорить русскими
сметными статусами, а не машинными id и пересказом внутренних запретов.

**0.24.0.144:** если deterministic numeric audit нашёл `source_delta` между исходными итогами,
smeta direct должен назвать это малое расхождение отдельно от крупного расхождения состава строк.

**0.24.0.145:** smeta direct дополнительно чистит видимую речь от внутреннего слова `evidence`:
наружу должны идти «источник», «подтверждение» или «расчётная трасса».

**0.24.0.146:** smeta skill/role-pack/direct prompt получили слой `ВОР -> нормируемая ВОР ->
таблица подбора норм`: одна строка исходной ВОР может раскладываться на несколько ГЭСН/ГЭСНм,
если это следует из технологии или состава норм; кандидаты показываются как таблица для ручной
проверки/Excel round-trip и не считаются финальным РИМ до подтверждения, раскрытия ресурсов и цен.
Видимый ответ дополнительно чистится от служебных слов `role-pack`/`harness`/`slots`/`shortlist`.

**0.24.0.147:** live-прогон СКС/столпа закрыл транспортные регрессии smeta_direct: numeric audit
понимает DOCX table source-ref префиксы `#tNrM:`, а локальные MLX/Qwen smeta model calls получают
пустой `<think></think>` prefill, чтобы endpoint возвращал видимый текст вместо пустого content.
Оставшийся риск — latency полного direct prompt на локальном MLX.

**0.24.0.148:** smeta direct/role-pack добавили обязательный `rim_scenario_estimate`: запрос РИМ/ГЭСН
нельзя закрывать свободной рыночной вилкой. Если полного trace нет, модель даёт РИМ-сценарий по
нормативным аналогам с базовой точкой, допуском и добором до final.

**0.24.0.149:** обычная просьба «оценить стоимость/сделать смету» в smeta-режиме по умолчанию
ведёт к РИМ-сценарию, если нормативные данные доступны и пользователь не попросил именно рынок.
Рынок остаётся дополнительной проверкой или отдельной оценкой по явной просьбе.

**0.24.0.150:** smeta direct по умолчанию получает короткий light prompt вместо полного
машинного контракта: модель видит исходник/RAG/trace и должна дать РИМ-сценарий по нормативным
аналогам, если доступна сметно-нормативная база. Полный prompt оставлен за флагом
`LES_SMETA_DIRECT_LIGHT_PROMPT=0` для регрессионной проверки.

**0.24.0.151:** smeta direct перестаёт вести себя как stateless чат-бот на продолжениях:
`_smeta_harness_question` добавляет последние Q/A текущей сессии, включая предыдущий ответ с ВОР
и таблицами, а light prompt для follow-up-команд (`добавь номера ГЭСН`, `поправь таблицу`,
`добавь НДС`) возвращает изменённый фрагмент без полного 10-блочного ритуала.

**0.24.0.197:** `search_norm` получил навигацию по разделам для `electric`, `low_current` и
`finishes`: кабель/трубы/коробки/светильники и отделочные операции сначала поднимают релевантные
кандидаты из электромонтажных/связных/отделочных сборников, а уже потом проходят общий score и
applicability. Код по-прежнему не выбирает норму, но перестаёт предлагать дорожную разметку вместо
кабеля и буровые машины вместо коробки.

**0.24.0.198:** `smeta_artifact_service` выбирает одну primary-таблицу стоимости для
`ЛСР РИМ`, а не складывает все `work_cost`-таблицы ответа. Это закрывает провал,
где полная оценка работ и короткая предварительная ЛСР одного и того же состава
склеивались в 30+ строк и завышали сметную стоимость.

**0.24.0.199:** `rim_lsr_trace_service` получил мост `visible/BOR/LSR rows -> RIM trace`:
если строка уже содержит выбранный шифр нормы, код раскрывает норму, переводит физическое
количество в измеритель нормы, ищет цены и собирает `priced_partial`/`priced_final` trace.
Строки без шифра или с конфликтом единиц остаются `row_bindings`/добором; код не выбирает
работы и нормы за модель.

**0.24.0.201:** smeta direct и артефакт ЛСР синхронизированы по форме выдачи:
prompt даёт модели заполняемый шаблон ЛСР граф 1-12 с обязательной строкой
`ВСЕГО по смете`; XLSX открывается с листа `ЛСР РИМ`; compact-ответ убирает
ручные итоговые строки, если они конфликтуют с суммой выбранной ЛСР-формы.
Это presentation/export guard: работы, нормы, ставки и применимость остаются
решением модели/источников, а не renderer-а.

**0.24.0.202:** `smeta_artifact_service` корректно читает суммы в ЛСР даже
если модель написала англо-Excel формат `17,000.00`, и не принимает строку
`ВСЕГО по смете` внутри пользовательской таблицы за отдельную позицию.
Это устраняет ложные итоги `2 017 руб.` вместо `~1,1 млн` и задвоение строк аварийного питания.

**0.24.0.203:** для 12-графной ЛСР renderer мапит количество из графы 7
`Кол-во всего`, а цену за единицу из графы 10/8. Суммы и отображаемые
количества больше не расходятся из-за первой найденной колонки `Кол-во на ед.`.

**0.24.0.204:** smeta skill получил карту сметного RAG/датасета: нормы,
ресурсы, сплит-формы/локальные книги ФГИС ЦС, НР/СП, формы ЛСР, КАЦ/КП и
проектные ВОР/спецификации описаны как разные источники с разной ролью.
Артефакт ЛСР стал trace-first, когда модель сама указала полный шифр нормы:
`smeta_artifact_service` читает графу `Обоснование`, передаёт видимые строки в
`rim_lsr_trace_service`, раскрывает ресурсы и считает проверяемую ЛСР-сумму.
Строки без полного шифра остаются в доборе; код не выбирает нормы/работы за модель.

**0.24.0.205:** `notebook_service` добавляет service notebook `smeta_norms`:
сметный RAG подаётся модели как навигационная карта корпуса, а не как
query-specific shortlist. Блокнот раскрывает слои источников (нормы,
ресурсы, ФГИС/сплит-формы, НР/СП, формы ЛСР, проектные ВОР/спецификации),
маршруты по разделам (`СКС/связь/ВОЛС -> ГЭСНм10`, `ЭОМ -> 21`,
`ОВ -> 18/20`, `металл -> 09/ГЭСНм38`) и доступные коллекции с примерами
полных шифров из `smeta_norm_store`. `smeta_direct` получает этот notebook
в RAG-map context; код по-прежнему не выбирает норму и не делает bind без
полного шифра, принятого моделью.

**0.24.0.206:** общий RAG слой `dataset_memory_service` получил
`source_layers`, `retrieval_routes` и компактный `dataset_source_graph_v1`.
Typed memory теперь объясняет модели не только список файлов, но и рабочую
навигацию: что значат слои `text/tables/calculations/normative/cad_bim`, для
каких вопросов их открывать и какие файлы являются первыми точками входа.
`dataset_brief_for_model_v1` выводит маршруты поиска и связку `слой -> файлы`
как навигацию, не evidence; нормативный маршрут включается только при наличии
слоя `normative`, чтобы обычные проектные тексты не выдавались за нормативный корпус.

**0.24.0.207:** вкладка «Документы» стала операторской витриной карты датасета:
правая панель переключается между фрагментами и «Картой», показывает
`source_layers`, `retrieval_routes`, первые файлы по слоям, ограничения и
статус `navigation, not evidence`. Через `PATCH /api/rag/datasets/{id}/profile/guidance`
оператор может сохранить пояснение для модели; оно пишется в профиль/sidecar
датасета и попадает в `dataset_brief_for_model_v1` как навигационная подсказка,
не как evidence. Сметные нормативные архивы `SMETA_RU_NORM/FSNB` теперь получают
слой `normative` и роли `ГЭСН/ГЭСНм/ГЭСНп/ФЕР/ФСЭМ/ФСБЦ/сплит-форма ФГИС`, а
служебные `manifest/dataset_card/preprocess_state` понижаются в первых файлах
карты и notebook priority.

**0.24.0.208:** добавлена статья `docs/ARTICLE_NOTEBOOK_RAG_ARCHITECTURE.md`
про notebook-подход к RAG: источник/датасет как блокнот, карта корпуса,
роли документов, навигационные веса и граница “модель связывает, код считает”.
Сметный importer `tools/smeta_ru_norm_rag_ingest.py` начал подписывать
внутренние таблицы `.vnbx` человеческими ролями (`A_SRF_F` — таблица
норм/расценок ФСНБ, `A_SRF_TR` — таблица ресурсов нормы, `LEVEL_COST` —
ценовой уровень и т.д.). `dataset_memory_service` даёт эти роли и для уже
проиндексированных старых файлов, чтобы модель видела нормативную карту, а
не экскурсию по подсобке базы.

**0.24.0.209:** typed dataset memory получил `navigation_terms` в file cards,
routes, source graph и compact brief: модель видит не только имя файла и роль,
но и короткие поисковые синонимы. Для FSNB `A_SRF_F` раскрывается как
“нормы/расценки/шифр нормы”, `A_SRF_TR` — как “ресурсы нормы/машины/материалы”,
pricebook — как “ФГИС ЦС/цены ресурсов/регион/квартал”. Старые cached memory
дообогащаются без reindex; это навигация, не evidence и не выбор нормы кодом.

**0.24.0.210:** typed dataset memory получил `dataset_topic_map_v1` и
`dataset_section_map_v1`: карта тем связывает инженерные вопросы с файлами,
разделами и поисковыми aliases, а section map берёт `section_heading/parent_heading`
из `lexical_chunks` как лёгкое оглавление без OCR/reindex. `dataset_brief_for_model_v1`
показывает модели темы и видимые разделы как source guide уровня датасета:
сначала выбрать тему/документ/раздел, затем открыть источник через retrieval/doc_filter.
Это NBLM-подобная навигация, не готовый ответ и не evidence.

**0.24.0.211:** обычный RAG при выбранном датасете начал выполнять
`dataset_topic_selection_v1` перед широким поиском: вопрос выбирает тему из
`dataset_topic_map_v1`, её `top_files/top_sections` идут в targeted `doc_filter`
retrieval, затем добавляется широкий fallback. В `retrieval_trace.topic_guided_retrieval`
пишутся выбранная тема, файлы, разделы, targeted/fallback counts, promoted fallback
и файлы, по которым targeted pass ничего не нашёл. Focus использует lexical `_rank_score`
и даёт широкому fallback место в контексте, чтобы карта источников была routing-слоем,
а не закрытым фильтром; retrieved chunks остаются единственным evidence.

**0.24.0.212:** карта тем стала видимой в UI: вкладка «Документы» показывает
`dataset_topic_map_v1` и `dataset_section_map_v1`, включая темы, файлы, headings
и операторское пояснение; кнопка «Спросить по теме» открывает чат с
`scope=ds:<dataset_id>` и предзаполненным вопросом. Compact trace summary ответа
показывает topic-guided retrieval: выбранную тему, targeted/fallback counts и
promoted fallback-документ.

**0.24.0.213:** добавлен controlled tool-harness: registry, shortlist и
`les_tool_result_v1` для `dataset_map`, `search_sources`, `read_source`,
`read_pdf_source`, `read_excel_source` и read-only filesystem
`roots/list/stat/read_text/search/hash`. API `/api/tools/*`, CLI
`tools/les_tool_harness.py` и блок `Tool-harness dry-run` во вкладке
«Документы» дают оператору те же рычаги, которые затем можно отдавать модели
через shortlist/tool-call loop. Filesystem whitelist-first и без write.

**0.24.0.311:** `Tool-harness dry-run` в «Документы» получил явную кнопку
`Shortlist` и встроенное описание интерфейса: оператор видит тот же первый шаг
выбора инструментов, который использует модель, а trace-блок показывает единый
packet `status/sources/missing/warnings/trace/result`.

**0.24.0.318:** diagnostic dry-run убран из штатного операторского вида
«Документы»: вкладка Л.И.С.Т. начинается с ручного типа датасета и реестра
файлов, затем показывает карту.

**0.24.0.312:** общий PDF table semantic layer добил массовые obvious buckets
на ИЦ: однострочные/абзацные “таблицы” уходят в `TEXT/NAV`, графические обрезки
схем в `NOISE`, а устойчивые проектные таблицы раскладываются в
`ENV/ACOUSTIC`, `ENV/SOIL`, `FIRE/AUPT`, `FIRE/RISK`, `ELEC/LIGHT`,
`TEP/STAFF`, `ENERGY`, `STRUCT/*`, `HVAC/*`, `SPEC/QTY` без генерации
предметного ответа кодом.

**0.24.0.313:** финальный ИЦ cleanup/rebuild: source-map по
`ПД_Инновационный центр` rebuilt live без reindex (`154` PDF, `153` ok,
`5754` table candidates, `UNKNOWN=268`, `stale=false`), dataset memory refreshed.

**0.24.0.314:** вкладка «Документы» получила человекочитаемую Mermaid-схему
«Структура датасета»: датасет → проекты/папки → разделы → найденные PDF/ПЗ/ВОР/СО,
таблицы, экспликации, водные балансы, ХВС и узел «Что проверить». Это UI-навигация
по source-map, не evidence и не шаблон ответа модели.

**0.24.0.315:** внешний intake получил web-путь Google Drive / Яндекс Диск:
`cloud_drive_service` листает и синхронизирует облачную папку по OAuth-токену
из env в mirror-кэш `storage/cloud_drives/...`, после чего существующий
`index-external` регистрирует mirror как датасет. Самовар показывает
«Google / Яндекс через веб» при добавлении датасета и статус web-дисков в
External Radar; локальные sync-папки остаются fallback.

**0.24.0.317:** слой разбора документации получил имя **Л.И.С.Т.** —
«Локальный индекс структуры томов». В UI «Документы» карта проекта, Mermaid-схема
и кнопка датасета теперь называют этот слой Л.И.С.Т.; технические контракты
`project_pdf_extract_v1` / `project_source_map` не переименовывались.

**0.24.0.214:** удалён smeta fast visible fallback как кодовая подмена
модельного ответа. `_smeta_direct_model_answer()` больше не строит
case-specific сценарии при timeout/empty, а явный smeta-mode при пустом
LLM-ответе возвращает технический failure с trace
`code_fallback_disabled=true`. `КП` больше не ведёт в старый stub-профиль, а
professional-domain deterministic candidates (`smeta`, `asbuilt`,
`doc_registry`, `field`) не могут стать финальным visible answer без модели.
ЛСР/ВОР должен формировать модель; код может считать, доставать источники,
валидировать и трассировать, но не имитировать профессиональный ответ.

**0.24.0.295:** checked RIM artifact сохраняет связь `source_row` →
рассчитанная позиция. Многопозиционная RIM-трасса может группироваться по
разделам для формы, но видимая ЛСР не должна съезжать: каждая исходная строка
получает только свой шифр/цену/флаги, строки без выбранной нормы остаются
нулевыми строками добора.

**0.24.0.296:** явный smeta-chat запрос `сделай ЛСР/смету/стоимость`
имеет приоритет pricing-route даже для сырой ВОР. Candidate-stage остаётся
только для явного `этап 1/кандидаты/без денег`; КАЦ/КП/missing не блокируют
ЛСР, а остаются построчным добором. Lookup policy для ЭОМ запрещает уводить
гофру, скобы крепления гофры, коробки проводки и БАП в `metal/ГЭСН09`, если
это не строительные металлоконструкции по массе.

**0.24.0.297:** smeta norm retrieval/ranking для live ЛСР не подменяет выбор
модели, но поднимает правильные соседние карточки норм: малый БАП светильника
видит `ГЭСНм10/10` `преобразователь/блок питания`, indoor гофра ПВХ не тонет
под подземной трубой, простая коробка открытой проводки не вытесняется
клеммной коробкой, кабель с креплением скобами не тонет под высоковольтным
или бескрепёжным кабелем. Structured norm-choice prompt запрещает считать
демонтаж монтажом/облицовкой, шпатлевку облицовкой и требует предпочитать
совпадающую поверхность (`потолки` над `стены`), оставляя непригодные строки
в доборе. Окно smeta lookup/choice расширено до 10 candidates, чтобы модель
видела рабочие отделочные аналоги за пределами шумного top-5. Smeta
model-owned steps используют подключённый global cloud runtime, если он реально
доступен с ключом; явный `LES_SMETA_PROVIDER=mlx` сохраняет локальный режим.

**0.24.0.215:** общий чат получил одношаговый model-selected tool loop:
модель выбирает tools из shortlist, код исполняет только read-only executor,
а финальный ответ снова пишет модель. Починен Qdrant visualizer в Совушке:
`/graph` ведёт на mounted `/qdrant-visualizer/index.html`, чтобы ассеты
`visualizer.js/pca.js/data.js` грузились same-origin. Mermaid-вкладка получила
живой `Граф знаний` из `/api/rag/graph/full`. Сметный compact выключен по
умолчанию, XLSX sidecar extraction больше не имеет молчаливого `5000 rows`
cap; лимиты зафиксированы в `ANSWER_LIMIT_AUDIT.md`.

**0.24.0.196:** smeta direct снижает дефолтную температуру до 0 и требует устойчивый базовый
сценарий для одного и того же исходника. Сметный артефакт рендерит `ЛСР РИМ (форма 421/пр)` перед
исходными таблицами и делает лист `ЛСР РИМ` основным XLSX-выводом; `lsr_rim_display_form_v1`
использует 12-графную РИМ-форму Приложения №3 в Markdown и XLSX, строку `ВСЕГО по смете` и
отдельные источники. Форматные follow-up команды больше не должны пересчитывать смету: active-state
передаёт до 60 строк с обоснованием, ставкой, суммой и статусом. Сценарные строки явно не являются
финальной ЛСР без выбранных норм, ресурсов, цен, НР/СП, НДС и расчётной трассы.

**0.24.0.152:** direct smeta сохраняет `active_smeta_state` из видимого ответа: задача,
рабочий вариант, исключения и строки ВОР из таблиц. Следующий smeta-turn получает это как
компактную «Активную смету», чтобы продолжать рабочий документ, а не пересказывать историю чата.

**0.24.0.153:** default light prompt упрощён для сильной модели: короткая роль сметчика,
граница model↔code и короткий user template «новая задача или продолжение активной сметы».
Специализированные микроправила остаются в skill/RAG/tests, а не грузятся в каждый runtime prompt.

**0.24.0.154:** light `smeta_direct` сохраняет свободную форму, но требует видимую базу
сценарной суммы (`объём × ставка` / калькуляция / допущение) и разрешает запросы на
коды/номера ГЭСН через активную ВОР + RAG/поиск норм: если точный код не подтверждён,
модель даёт кандидата или раздел с пометкой проверки, а не просит ВОР заново. `active_smeta_state`
запоминает методику, последнюю таблицу/действие, допущения и открытые развилки.

**0.24.0.155:** добавлен безопасный импорт Smetnoedelo API v2.0 в сметный RAG:
`tools/smetnoedelo_rag_import.py` пишет markdown-карточки разделов/норм/ресурсов в
`RAG_Content/TABLE_SMETA/SMETA_SERVICE/smetnoedelo_api`, берёт токен только из
`LES_SMETNOE_TOKEN`, кеширует ответы без секрета, ограничивает сетевые запросы
`--max-requests` и опционально вызывает `POST /api/rag/sync-smart`.

**0.24.0.156:** добавлен downloader публичных ZIP-архивов Smeta.RU:
`tools/smeta_ru_norm_download.py` читает `https://smeta.ru/download/norm`,
извлекает прямые ссылки `obs.smeta.ru/*.zip`, умеет `--latest fsnb2022`,
`--pattern`, `--with-head`, скачивание, `sha256` manifest и опциональный extract.
Архив остаётся исходником; импорт в Parquet/RAG выполняется отдельным явным шагом.

**0.24.0.157:** добавлен worker `tools/smeta_ru_norm_rag_ingest.py`: скачивает
архивы Smeta.RU по одному, распаковывает, пишет provenance/manifest и машинные
карточки в `RAG_Content/TABLE_SMETA/SMETA_RU_NORM`, затем может вызывать
`POST /api/rag/sync-smart` после каждого нового архива. RAG-структура — группа
`TABLE_SMETA` и пачка датасетов `SMETA_RU_NORM_<CATEGORY>_Index`; routing по пути
`smeta_ru_norm/<category>/...` закреплён в `backend/document_router.py`.

**0.24.0.158:** default sync-root worker сужен до
`RAG_Content/TABLE_SMETA/SMETA_RU_NORM`, чтобы автоиндекс нового архива не
сканировал весь `RAG_Content`.

**0.24.0.159:** `tools/smeta_ru_norm_rag_ingest.py` по умолчанию не копирует
поддерживаемые исходные документы из архива в RAG (`--max-source-files 0`):
raw хранится в `storage/extracted`, а автоиндекс получает manifest/classifier/text
projections без подвисания на больших XLSX.

**0.24.0.160:** worker раскрывает вложенные `.vnbx` как ZIP и пишет nested
inventory + markdown-проекции внутренних `.json/.xml/.txt/...` в RAG, чтобы
модель получила машинно-читаемые слои Smeta.RU norm до Parquet-parser.

**0.24.0.164:** default `smeta_direct` получает compact-карту сметного RAG
`SMETA_SERVICE` и полный список доступных локальных pricebook перед ответом.
Правило источников стало prompt-level: сначала проверить RAG/источники ЛЕС,
потом спрашивать пользователя; если книга, сборник или нормативная база уже
доступны, не писать, что пользователь не приложил сплит-форму/ценовую базу.

**0.24.0.165:** спецификация с пустыми ценовыми колонками больше не является
стоп-фактором для оценки работ. `smeta_direct` должен трактовать такие поля
как missing по поставке/прайсу, строить `спецификация -> ВОР` и давать
построчную стоимость монтажных работ по измеримым строкам.

**0.24.0.171:** skill/role-pack уточнили Excel round-trip сметчика: таблица кандидатов имеет блок
`Данные ТЗ / ВОР` и блок `Соответствие данным ТЗ / ГЭСН`, видимый `№ ВОР` является только
отображаемой нумерацией, связь держится на стабильных `vor_row_id`/`source_row_id`, а повторный
подбор кандидатов выполняется только для новых или изменённых строк. Несколько загруженных вариантов
подбора ГЭСН не смешиваются молча.

**0.24.0.249:** присланные рабочие DOCX закреплены как live-estimator workflow: модель сначала
читает все источники и фиксирует их роль, затем ведёт состояния `SOURCE_READING → BOR_DRAFT →
NORM_CANDIDATE_TABLE → USER_VARIANT_SELECTION → RESOURCE_EXPANSION → FIRST_LSR_DRAFT →
COEFFICIENT_AND_KAC_PASS → PRICED_FINAL`. Нулевые значения в первом ЛСР допустимы только как
placeholders с примечанием КАЦ/КП/ручной ввод; финал невозможен без выбранного варианта норм,
ресурсов, цен/КАЦ, коэффициентов, региона/периода, НР/СП и trace. Skill, role-pack и ALGO-smeta
обновлены; код не выбирает работы/нормы.

**0.24.0.250:** дополнительные DOCX-заметки закрепили уточнения round-trip: таблица кандидатов
поддерживает не только `одна ВОР → несколько ГЭСН`, но и `несколько ВОР → одна ГЭСН` через
`source_row_ids`/`mapping_cardinality`; поиск нормы идёт уровнем `семейство работ → группа
сборников → сборник → раздел/таблица → конкретная норма`; семейства норм включают `ГЭСН`, `ГЭСНм`,
`ГЭСНп`, `ГЭСНр`, `ГЭСНмр`; ведомость добора относится к ресурсам выбранной нормы без цены в
сплит-форме/книге/КП, а не к нераспознанным работам; режим качества фиксируется как
`rough_cost`/`stage_p`/`stage_rd`.

**0.24.0.251:** цикл `тесты → выводы → правки` по live smeta prompt: методический запрос
`без расчёта/без рублей` больше не должен принудительно оформляться как ЛСР с нулевыми деньгами.
Light direct prompt выдаёт workflow/ВОР/нормируемую ВОР/таблицу кандидатов/добор без денежных граф,
а расчётные запросы сохраняют ЛСР-контракт. Compact render smeta role-pack сжат с раздутого batch
prompt до `7714` символов, чтобы не душить модель системным JSON.

**0.24.0.252:** второй цикл `тесты → выводы → правки → тесты`: вопрос `объясни, как ты
работаешь по сметам / что выбираешь ты / что считает код` теперь считается process-explanation
intent, а не расчётной командой, даже если внутри перечислены `ЛСР`, `нули` и `сметы`.
Явные команды `сделай/оформи/рассчитай/дай ЛСР|смету|стоимость` остаются в ЛСР/расчётной ветке.

**0.24.0.98:** сметный skill/role-pack и компактный work-plan contract усилены как prompt-first слой: модель должна переносить уже сказанные параметры в слоты, понимать разговорные площади/глубины как сметчик и задавать сценарные допущения сама при явном разрешении пользователя. Код при этом не придумывает недостающие формульные параметры, только принимает русские формы единиц (`2 метра`, `160 метров`), считает и штрафует свайные нормы для несвайных фундаментов без объектных hardcode-шаблонов.

**0.24.0.99:** duplicate-guard прямых количеств стал мягче и профессиональнее: одна масса/площадь/объём не размножается на придуманные опции, но может использоваться для нескольких явно названных операций из ТЗ/ВОР/файла над тем же изделием (контрольная сборка, промежуточная разборка, монтаж на площадке и т.п.). Skill/role-pack/contract закрепляют, что модель должна сохранить такие разделы и идти через ГЭСН notebook/search_norm, а не схлопывать их в одну позицию.

**0.24.0.100:** batch-путь больше не блокирует работы с недостающей геометрией до поиска норм: `search_norm` и ГЭСН/РИМ-навигация выполняются даже при missing geometry, а расчёт останавливает уже `add_position` как калькуляторный gate. Это даёт модели норм-кандидатов и вопросы применимости вместо пустого “нет площади”, не добавляя объектных шаблонов.

## 2. RAG-ядро и маршрутизация

| Суб-модуль | Назначение | Точки входа | Док | Статус |
|---|---|---|---|---|
| rag/core | поток чата, retrieval/evidence/research-loop и честные статусы; corpus-derived notebook не подставляет доменные разделы; contract-clean sibling строится resumable supervised job, noise children исключаются только с audited accounting, activation требует полного live RRF gate | `retrieval_service`, `notebook_study_service`, `saferag_service`, `evidence_packet_service`, `runtime_dispatcher`; `routers/chat.py`; `tools/build_rag_contract_sibling.py`; `tools/rag_generation_supervisor.py`; `tools/rag_rrf_readiness.py`; `tools/activate_qdrant_generation.py` | [CODE_MAP.md](CODE_MAP.md) · [ALGO-rag-best-practices.md](ALGO-rag-best-practices.md) · [RAG_TEST_PROGRAM_AUDIT.md](RAG_TEST_PROGRAM_AUDIT.md) | ✅ |
| rag/evidence-packet | общий контракт normal-RAG: source-diverse bounded context, table header, source version/locator/retrieval features; модель видит те же `Источник N`, что UI, а post-generation check отмечает missing/invalid labels | `evidence_packet_service`, `saferag_service`, `routers/chat.py` payload `evidence_packet`, `retrieval_trace.evidence_packet/citation_check` | [ALGO-evidence-packet.md](ALGO-evidence-packet.md) | ✅ |
| rag/answer-render | видимый слой evidence в Совушке: conversation-first чат с progressive disclosure, короткие подсказки ожидаемых запросов/данных для `Auto/Search/Estimates/Normcontrol`, source chips, citation drawer, копирование с источниками и artifact `Источники ответа`; технические статусы и вторичные действия скрыты из первого слоя; не меняет retrieval/model answer | `sovushka/answer_render.py`, `sovushka/pages/chat.py`, `sovushka/styles.py`; tests `test_answer_render_v16.py`, `test_notebook_study_chat_policy.py`, `test_sovushka_chat.py` | [CODE_MAP.md](CODE_MAP.md) | ✅ |
| rag/search-skill | рабочий контракт инженерного RAG-поиска: модель связывает источники и формулирует вывод, код только ищет/ранжирует/считает таблицы/даёт trace; неполный поиск не превращается в отрицательный факт; нормативный вопрос ведётся маршрутом `норма → пункт → вывод`, а развилки «требуется/не требуется» требуют обе стороны нормы | `prompt_registry_service.rag_search_role_pack`; [skills/rag_search/SKILL.md](../skills/rag_search/SKILL.md); tests `test_rag_normcontrol_skill_contract.py` | [CODE_MAP.md](CODE_MAP.md) | ✅ |
| rag/routing | выбор контура: ProfileResolver + agent-router (router-primary ON), `output_contract` в trace; сценарии/контракты ответа + мягкий `answer_contract_check` + общий `workflow_plan_v1`; model-first guardrail: scope warnings, empty retrieval and unified harness no longer become generic visible final stops for ordinary chat, model still gets the turn | `profile_resolver`, `agent_router_service`, `query_router`, `deterministic_policy_service`, `scope_service`, `answer_contract_service`, `workflow_plan_service`, `routers/chat.py` | [ALGO-routing.md](ALGO-routing.md) ✅ · [ALGO-workflow-plan.md](ALGO-workflow-plan.md) ✅ · [AUDIT_DETERMINISM.md](AUDIT_DETERMINISM.md) (решение/история) | ✅ |
| rag/retrieval | exact/FTS/dense/native hybrid/rerank с раздельными score scales; dense требует совместимый `les.rag.index-contract.v1`, retry сохраняет backend, reranker пишет model/score/rank и quality считается после него. Debug endpoint является точной проекцией chunks | `retrieval_service`, `retrieval_quality_service`, `lexical_index_service`, `backend/rag_config`, `backend/qdrant_adapter`, `backend/reranker`, `routers/datasets.py` | [ADR-12-typed-retrieval.md](ADR-12-typed-retrieval.md) · [ALGO-rag-best-practices.md](ALGO-rag-best-practices.md) | ✅ |
| rag/document-explorer | Л.И.С.Т. — no-AI файловый проводник проекта поверх read-only Document Explorer: структура папок, inventory, извлечённые типы/шифры/таблицы и поиск; Qdrant/LES остаётся индексом проверяемых фрагментов, а не генератором ответа. Совушка показывает три панели `выбор датасета → иерархия файлов и папок → контекст датасета или выбранного файла`. Кнопка `Данные о датасете` открывает паспорт, интерактивную CSS-карту, реестр и извлечённые данные; узлы папок раскрывают дерево, узлы разделов фильтруют по metadata discipline. Клик по файлу показывает только его краткую справку, содержание indexed fragments и `Открыть оригинал`. Служебные parser warnings агрегируются в понятные статусы; raw diagnostics, Mermaid и дублирующие счётчики не выводятся. `Qdrant/LES` маркируется только при наличии `point_id`. Датасеты фильтруются как `Все / Проекты / Не проекты`; карта использует project roots, discipline summaries и PDF/тома из `project_pdf_extract` | `document_explorer_service`, `routers/documents.py`, `sovushka/pages/documents.py`, `sovushka/styles.py`; endpoints `GET /api/documents/by-id/{doc_id}/chunks`, `POST /api/documents/by-id/{doc_id}/open-native`, `PATCH /api/rag/datasets/{id}/profile/kind`; tests `test_document_explorer_service.py`, `test_static_assets.py`, `test_notebook_api.py` | [CODE_MAP.md](CODE_MAP.md) | ✅ |
| rag/corpus-inventory | read-only source-quality cards приоритетного evidence-core корпуса: использует только operator API (`health`, Document Explorer, Dataset Notebook), показывает revision/reader/maps, document statuses/types/chunks и кандидаты pending/error/zero-chunk для ручного решения; не обходит API, не является evidence и не мутирует corpus | `tools/priority_corpus_inventory.py`; generated `docs/EVIDENCE_CORE_PRIORITY_INVENTORY.md`; tests `test_priority_corpus_inventory.py` | [PLAN_EVIDENCE_CORE.md](PLAN_EVIDENCE_CORE.md) · [CODE_MAP.md](CODE_MAP.md) | ✅ |
| rag/table | детерм. SUM по полному Parquet (числа — код) | `table_query_service`; MCP `les_table_*` | [ALGO-table-query.md](ALGO-table-query.md) | ✅ |
| rag/pdf | PDF ingestion для RAG: обязательный быстрый page-text baseline на PyMuPDF, page-level nodes вместо markdown chunk flood, layout/table/OCR как enrichment; timeout тяжёлого PDF-конвертера не должен превращать текстовый PDF в `ERROR`, а проектные PDF с weak smeta-словами не должны уходить в `TABLE_SMETA` | `backend/converter`, `backend/qdrant_adapter`, `backend/document_router`, `backend/pdf_layout`; флаги `RAG_PDF_INDEX_FAST_TEXT_FIRST`, `RAG_PDF_FAST_TEXT_FALLBACK_ENABLED`, `RAG_PDF_PAGE_NODES_ENABLED`, `RAG_PDF_PAGE_NODE_MAX_CHARS`, `LES_LAYOUT_PDF` | [ALGO-pdf-ingestion.md](ALGO-pdf-ingestion.md) · [ALGO-pdf-layout.md](ALGO-pdf-layout.md) | ✅ |
| rag/harvest | verify-правки → train-set + таксономия ошибок | `harvest_service`; `tools/harvest_dataset.py` | [ALGO-harvest.md](ALGO-harvest.md) | ✅ |
| rag/context-memory | паспорт чата + metadata/deep паспорт датасета (`_les_dataset_profile.json`) + общий `notebook_v1`; typed dataset memory хранит `dataset_revisions`/`dataset_memory`/`file_cards`/`evidence_atoms`, мультислои данных, file cards, `navigation_terms`, `dataset_topic_map_v1` и `dataset_section_map_v1`; `NTD_*` домен считается технической областью поиска, а не нормативностью без явного `NORMATIVE`; карты темы/файлов остаются навигацией и доступны модели/явному `target_file`, но production chat не выполняет скрытый targeted fan-out до исходного RRF; `saferag_service` focus учитывает lexical `_rank_score` и promoted fallback; model reader-pass сохраняет `reader_output` как navigation-not-evidence; `dataset_brief_for_model_v1` упаковывает это для модели и явно связывает `file_name` с Qdrant/`lexical_chunks`/`doc_filter`; deep-слой читает FTS-проекцию `lexical_chunks`, а при пустой lexical-карте берёт `top_documents`/`priority_files` из MetaDB/file_cards; оператор может сохранить `operator_guidance` и ручной `dataset_kind` как навигационные пояснения для модели/сортировки, не evidence; UI-вкладка «Документы» показывает карту датасета, typed-бейджи в реестре файлов и в Самоваре | `context_memory_service`, `dataset_memory_service.select_topic_retrieval_plan`, `saferag_service`, `notebook_service`, `prompt_registry_service`, `lexical_index_service`, `backend/qdrant_adapter`; `GET /api/chat/memory/{session_id}`; `GET/POST /api/rag/datasets/{id}/profile*`; `PATCH /api/rag/datasets/{id}/profile/guidance`; `PATCH /api/rag/datasets/{id}/profile/kind`; `GET /api/notebooks/{dataset_id}`; `GET/POST /api/notebooks/{dataset_id}/memory*`; `POST /api/notebooks/{dataset_id}/memory/read`; `POST /api/notebooks/warmup`; `GET /api/service-sources/notebooks`; `routers/chat.py`; `sovushka/pages/chat.py`; `sovushka/pages/documents.py`; `sovushka/pages/samovar.py` | [ALGO-context-memory.md](ALGO-context-memory.md) · [CODE_MAP.md](CODE_MAP.md) | ✅ |
| rag/notebook-study | NotebookLM-подобная навигация без query-time оркестратора: готовая typed map/реестр + один исходный native RRF + модельный синтез. Скрытый reader, topic/section/file prefetch и локальный selector-loop по умолчанию отключены; явный target-file сохраняет один строгий `doc_filter`. Карты остаются navigation, факты требуют chunks/tool sources и корректных `Источник N` | `notebook_study_service`, `dataset_memory_service`, `tool_harness_service`, `routers/chat.py`; payload `retrieval_trace.notebook_study.status=map_only` | [ALGO-notebook-study.md](ALGO-notebook-study.md) · [ALGO-rag-best-practices.md](ALGO-rag-best-practices.md) | ✅ |
| rag/vision | вердикт по VL-LoRA (пока не нужна) | — | [ALGO-vl-lora.md](ALGO-vl-lora.md) | ✅ (решение) |
| rag/scan-mining | поиск данных в сканах + различение типа (verify) | `verify_service`, `table_detect`, `doc_classifier`; `routers/verify.py` | [scan_data_mining.md](scan_data_mining.md) | ✅ |
| harness | unified construction harness (source-adapters, evidence) — флаг OFF | `source_adapters`, `unified_construction_harness_service` | [unified_harness_failure_ledger.md](unified_harness_failure_ledger.md) | ✅ (OFF) |

**✅ исправлено:** CODE_MAP-счётчики (~101/~36/~2062); создан `ALGO-routing.md` (канон маршрутизации); AUDIT_DETERMINISM/AUDIT_CORE получили статус-баннер «исполнено»; ALGO-table-query уточнён (агрегация после ретрива). В 0.23.6.1 router-primary fallback закрыт через `RouterUnavailable` → deterministic cascade/in-flow fallback. В 0.23.6.9 `evidence_contract` расширен до системного `DefensePack/DefenseClaim`, первым подключены smeta/object и normcontrol/doc-review. В 0.24.0.18 `workflow_plan_v1` стал общим тонким контрактом для smeta/normcontrol/RAG/table payload: workflow, required/missing inputs, evidence policy, claim summary, source summary, blockers и next actions. В 0.24.0.19 Совушка начала показывать этот план оператору: статус/финальность в первом слое, workflow id/missing/actions в техдеталях. В 0.24.0.29 поверх паспортов добавлен общий `notebook_v1` и prompt registry; сметный режим получает ГЭСН-блокнот как навигацию перед tool-contract. В 0.24.0.30 ГЭСН-блокнот различает `ГЭСНм38` как монтажный раздел, не evidence. В 0.24.0.32 broad-вопросы по проекту больше не перехватываются скрытой deterministic-сводкой: обычный чат идёт в retrieval+модель, `project_summary` остаётся явным инструментом. В 0.24.0.33 qwen `lexical_chunks` восстановлены из существующих Qdrant payloads и дальше синхронизируются при parse-переиндексации файла, поэтому notebook/deep и lexical/hybrid слой больше не слепнут при уже загруженных PDF. В 0.24.0.34 добавлен `notebook_study`: явный broad-запрос по выбранной области получает reading plan, section retrieval и artifact, но итоговый текст остаётся модельным RAG-синтезом. В 0.24.0.35 этот слой стал быстрее: план выбирает меньше релевантных секций, а retrieval по ним идёт параллельно. В 0.24.0.36 cloud preset/admission починен: кастомная cloud-модель не сбрасывается, облачная генерация разрешена во время guarded reindex. В 0.24.0.37 admission стал ресурсным: индексация больше не тупой рубильник, cloud проходит всегда, локальный MLX допускается только при Core ML embedder и зелёной памяти, а runtime status показывает effective chat state. В 0.24.0.38 SSE-чат получил synthetic token fallback для final-only веток, ранние source chips и живой таймер progress. В 0.24.0.39 prompt registry v2 стал видимым API/админским слоем: общий промт, тон, режимные промты и инструменты. В 0.24.0.40 исправлены light-default и перенос многострочных промтов в админке. В 0.24.0.41 notebook-study перестал стираться generic TOSKA fallback при наличии контекста; явный артефакт обновляет открытую панель, а cloud preset включает согласие на P2-облако. В 0.24.0.42 broad-запросы по объекту/проекту обходят answer-cache и идут в широкое чтение блокнота; таблицы в чате/артефактах получили горизонтальную прокрутку. В 0.24.0.43 UUID датасета в legacy `dataset_filter` резолвится как выбранный датасет, а не как нерешённый класс фильтра. В 0.24.0.44 notebook-study снял отдельный короткий token-cap, а артефакт-блокнот рендерится как markdown-отчёт целиком: сначала найденные материалы, потом пробелы, служебный маршрут чтения внизу. В 0.24.0.45 широкие ответы больше не сжимаются фиксированными правилами строк: краткость включается только явной просьбой оператора, а source-маркеры в чате выводятся визуально как цитаты. В 0.24.0.46 скрепка чата адаптирована к NiceGUI 3 upload API (`e.file.read()`): файл снова становится видимым pending-вложением после загрузки. В 0.24.0.48 `_sync_parse` считает lexical FTS sidecar опциональной проекцией для lightweight/legacy adapter-объектов: отсутствие `_sync_delete_file_lexical`/`_sync_upsert_file_lexical` больше не валит vector parse. В 0.24.0.57 prompt registry получил editable overrides для системных промтов, tool-contracts перестали добавляться в системный prompt и остались только API/UI-метаданными; запросы на перечень файлов/реестр документов получают MetaDB `documents` inventory как evidence-блок внутри обычного RAG-ответа. В 0.24.0.58 верхняя плашка `MODEL` показывает активную модель из `/api/status`, модель конкретного ответа вернулась бейджем в AI-пузырь, а служебный inventory-заголовок заменён человеческим названием и запрещён к выводу наружу. В 0.24.0.175 broad-study перед чтением выбранного проекта best-effort поднимает модельный reader-pass и использует MetaDB-реестр для выбора файлов, не подменяя им финальный ответ.

Исторические 0.24.0.59–0.24.0.60 впервые ввели file-target и native RRF, но использовали legacy
vector-copy/sparse-sidecar/rollback-конфигурации. Эти пути удалены в 0.24.0.360 и не являются
инструкцией: текущий контракт — только полный re-embed в named contract-v2 collection.
С contract v2 native RRF становится обязательным общим путём, а не датасетным флагом: все текущие indexed datasets мигрируют через полный re-embed в clean sibling, будущий parse записывает только named dense+sparse points, collection/embedding/chunk/vector schema закреплены manifest. Потребители используют стабильные aliases `les_rag` и `les_smeta_norm_cards`; номера физических поколений остаются только в сборке и rollback. `tools/rag_generation_supervisor.py` возобновляет сборку через launchd с bounded retry; progress и source identity пишутся атомарно. `tools/rag_rrf_readiness.py` блокирует activation без полного migration report, audited exclusion accounting, единого fingerprint, обоих vector channels, полного alias-ready FTS и filtered live RRF каждого dataset; live probe берёт model/backend из immutable generation contract, а не из default активного рантайма. `tools/activate_qdrant_generation.py` перед переключением повторно сверяет живую collection, публикует Qdrant+SQLite alias с rollback и при прямом аварийном запуске согласует supervisor state; legacy vector-copy migration отключена.
В 0.24.0.369 `rag_readiness_service` и `/api/rag/readiness` делают эти состояния видимыми в GUI по общему корпусу, сметам и выбранному dataset scope. Сметный alias активирован только после `47191/47191` dense+sparse/fingerprint и live RRF; современная терминология расширяется через видимые query variants из конфигурации, не через selector нормы.
В 0.24.0.61 selected-scope broad-запросы `notebook_study`/`project_inventory` больше не запускают дорогую TOSKA validation по умолчанию: source-map и deterministic MetaDB inventory artifact остаются проверяемой границей, ответ маркируется `UNVALIDATED`, а явный `validation_enabled=true` сохраняет старый путь.
В 0.24.0.340 `notebook_research_guide_v1` делает маршрут wide-чтения проверяемым для оператора: фиксирует revision/source-map и reader-pass, считает разделы/точечные файлы с retrieved chunks, даёт стартовые источники и вопросы продолжения. Это не summary и не evidence: `coverage=ready` описывает только текущий маршрут, а факты остаются за retrieved chunks/reader tools.
В 0.24.0.62 stream UI не делает скрытый повторный `/api/chat`, если SSE уже прислал backend error до первого токена; пользователь видит ошибку, таймер останавливается. Trace latency получил `pre_retrieval`/`wall_total`, чтобы broad notebook/inventory-запросы показывали полный пользовательский wait.
В 0.24.0.63 broad notebook+inventory ответы всегда несут top-level `project_inventory`, поэтому Совушка может автооткрыть кликабельный реестр файлов; таблицы в пузырях/артефактах используют внутренний горизонтальный scroll и нормальный перенос слов.
В 0.24.0.64 добавлен typed dataset memory: модель получает карту датасета как navigation-not-evidence, код хранит file cards/evidence atoms/revisions, Qdrant payload и реестр файлов Совушки несут мультислои данных.
В 0.24.0.65 добавлен model reader-pass: активная модель может отдельным JSON-проходом “освоить” датасет, записать `reader_output` в `dataset_memory` и дать ответчику карту, где искать паспорт объекта, состав проекта, ТЭП, инженерку, сметы, спецификации и нормы; awaited parse-пути умеют ставить этот проход в фон через `LES_DATASET_READER_AFTER_PARSE=1`.
В 0.24.0.70 широкое чтение блокнота добирает паспортные документы точечно: `notebook_study_service` выбирает candidate-файлы из typed memory/reader-pass/inventory и `chat.py` вызывает retrieval со строгим `doc_filter`, чтобы модель получила фрагменты конкретных ПЗ/составов/заданий/СТУ/ТЭП.
В 0.24.0.71 SafeRAG получил protected evidence tier: `target_file`/клик по реестру и notebook target-файлы передаются в `concentrate_sources(protected_doc_names=...)`, поэтому намеренно открытый документ не выкидывается общим `max_docs` focus.
В 0.24.0.73 `answer_form_service` больше не сжимает широкий инженерный обзор до `enum`, если внутри есть слова «какие файлы/разделы»: маркеры «технические решения», «что не сходится», «требует проверки» получают full-бюджет генерации. В 0.24.0.75 этот full-бюджет ограничен 2048 токенами, чтобы широкий обзор не зависал на облаке. В 0.24.0.77 full-инструкция задаёт порядок разделов: паспорт, ключевые решения, важные файлы/разделы, несостыковки/что проверить, затем детали.
В 0.24.0.78 полный MetaDB-реестр отделён от prompt-а: модель получает компактную `КАРТА РЕЕСТРА ДАТАСЕТА`, а полный список файлов остаётся в `project_inventory`/artifact/UI.
В 0.24.0.79 широкий inventory-ответ получил 3072-token budget, запрет на гигантские обзорные markdown-таблицы и приоритет artifact-а `Реестр файлов датасета` над параллельным notebook artifact.
В 0.24.0.80 явный inventory-запрос с «кратко» больше не режется `brief`-бюджетом до середины фразы: минимум generation budget 2048, видимый ответ — списки + ссылка на artifact, полный реестр остаётся в UI.
В 0.24.0.81 notebook-study больше не показывает оператору artifact `Инженерный блокнот` по умолчанию: слой остаётся в `notebook_context`/trace, а наружу идёт только ответ модели и, при явном запросе, `Реестр файлов`. Prompt дополнительно запрещает служебные слова evidence/dataset/context/RAG/notebook в видимом ответе.
В 0.24.0.238 вопросы вида `что это за датасет/что за проект` включают broad notebook-study и, для `датасет`, компактный MetaDB inventory prompt, чтобы модель сначала читала карту корпуса/титулы/ведомости, а не отвечала по случайному top chunk. Точные lookup/сметные запросы не расширяются.
В 0.24.0.216 raw CAD/BIM-исходники (`.dwg/.dxf/.rvt/.rfa/.ifc/.ifczip/.nwc`) перестали попадать в ложный `INDEXED 0`: parse ставил явный `ERROR` и вёл к canonical CAD/BIM JSON/JSONL projection, а штатные текстовые/JSON/Markdown-проекции продолжали индексироваться. В 0.24.0.288 эта граница стала операторской: default intake больше не принимает raw `.dwg/.rvt/.ifc/.ifczip` как RAG-документы, `+ папка` показывает их как `unsupported_suffix`, а старые raw CAD/BIM строки в parse queue получают `SKIPPED`, не `ERROR`. В 0.24.0.221 DWG/DXF-инструмент получил repair-pass для DXF, где LibreDWG рвёт кириллический MTEXT/строки в нечисловые group-code lines; trace ремонта сохраняется в `cad_bim_graph.json`. В 0.24.0.222 добавлен read-only `GET /api/cad-bim/imports`: операторская сверка import graph DB ↔ `CAD_BIM_Index`, weak/minimal imports, duplicate groups и duplicate indexed projections без удаления/реиндекса. В 0.24.0.223 этот inventory выведен во вкладку «Документы» как режим `CAD` с открытием projection и переходом в чат по `target_file`. В 0.24.0.224 DWG/DXF extractor восстанавливает таблицы, нарисованные сеткой линий и текстом, пишет `tables[]` в `cad_bim_graph.json`, а projection показывает `First data rows / первые позиции`, data row-lines, compact row-lines и `CAD drawn tables` до поэлементного шума. В 0.24.0.225 projection добавляет `first positions`/`logical positions` с нормализованными `position/name/mark/manufacturer/unit/qty/source_row`; в 0.24.0.228 retrieval `first_ordinal_guard` при `target_file` поднимает начало CAD-спецификации по минимальной фактической `position N`, а не по `chunk_ord` листа/продолжения.
В 0.24.0.217 PDF/P7M/XLS/XLSX/XLSM markdown-конвертация в index path выполняется в отдельном killable subprocess: timeout убивает дочерний процесс, а не бросает зависший thread внутри proxy; остальные форматы идут прежним прямым путём. В 0.24.0.218 большие Excel/CSV в markdown path идут в RAG как `spreadsheet_navigation_projection` (колонки/профили/образец) с payload `type=spreadsheet_projection`, а не как тысячи row-chunks. В 0.24.0.219 parquet path сохраняет полный Parquet для точных строк/сумм, но при большом числе строк кладёт в Qdrant `table_navigation_projection`, а не каждую строку; точные расчёты остаются задачей table-reader/tool по Parquet/source. В 0.24.0.233 PDF ingestion стал baseline-first: реальные PDF в index path сначала получают быстрый PyMuPDF page-text слой, а `pymupdf4llm`/Docling/layout/table/OCR считаются enrichment; timeout тяжёлого isolated converter падает в page-text fallback вместо `ERROR`, если текстовый слой доступен. В 0.24.0.234 PDF/P7M page-text индексируется bounded page-level nodes с page anchors (`pdf_page_text`), а document router перестал отправлять обычные проектные PDF в `TABLE_SMETA` по weak словам/substring-сигналам.

## 3. Нормоконтроль и проверка документации

| Суб-модуль | Назначение | Точки входа | Док | Статус |
|---|---|---|---|---|
| normcontrol/doc-review | RAG-led СПДС-review по ГОСТ Р 21.101-2026 (computed + retrieval-подфаза + PDF sheet geometry + layout-zone штампа) + defense-contract + `normalized_remarks` + решения инженера для checklist/report renderers; факты комплекта ищутся в project dataset, а текст требования теперь берётся из явного нормативного SPDS RAG (`NTD_SPDS_Index`/`LES_NORMCONTROL_SPDS_DATASET_IDS`) с актуальным ГОСТ Р 21.101-2026; 2020 считается историческим источником | `doc_review_service`, `doc_review_retrieval_service`, `title_block_extract_service`, `document_set_model`, `normcontrol_review_map_service`, `evidence_contract`; `routers/doc_review.py`; флаг `LES_TITLE_BLOCK_OCR` | [DOC_REVIEW_GOST_R_21_101_2026_PLAN.md](DOC_REVIEW_GOST_R_21_101_2026_PLAN.md) · [PD_RD_REGULATORY_BASE.md](PD_RD_REGULATORY_BASE.md) | ✅ |
| normcontrol/skill | рабочий контракт нормоконтроля: модель формулирует замечания по правилу/месту/риску/действию, код выполняет computed checks/layout/RAG/defense trace; missing = unknown, не pass/fail | `prompt_registry_service.normcontrol_role_pack`; [skills/normcontrol/SKILL.md](../skills/normcontrol/SKILL.md); tests `test_rag_normcontrol_skill_contract.py` | [ALGO-normcontrol.md](ALGO-normcontrol.md) · [DOC_REVIEW_GOST_R_21_101_2026_PLAN.md](DOC_REVIEW_GOST_R_21_101_2026_PLAN.md) | ✅ |
| normcontrol/formal-v1 | формальные NK-01..04 (форматы ГОСТ, шифры, ведомость) | `normcontrol_service`; `/api/normcontrol` | [ALGO-normcontrol.md](ALGO-normcontrol.md) | ✅ |
| drawings/manifest | MVP паспорта листа чертежа: PDF → формат листа, правая нижняя зона штампа, positioned text blocks, кандидаты объект/адрес/том/шифр с provenance, смысловой разбор шифра `ИОС.ЭС.ПЗ`, номера листов для текстовой и графической частей, `Содержание тома` как `volume_contents_row_v1` реестр состава тома, batch-реестр по `cipher_norm` и явные `no_cipher`/`no_stamp`/`cipher_conflicts`; read-only, без LLM и без reindex | `drawing_manifest_service`; CLI `tools/drawing_manifest.py`; tests `test_drawing_manifest_service.py` | [CODE_MAP.md](CODE_MAP.md) | ✅ |
| pd-rd/manifest | Source-map ПД/РД для RAG: многостраничное `Содержание тома`, `Состав проектной документации`, `Оглавление` ПЗ, compact sheet summary и PDF-mojibake repair; `ПЗ` = тип документа, домен берётся из шифра, темы из оглавления; нормативный профиль строится от ПП N 87 + ГОСТ Р 21.101-2026; read-only, без LLM, без reindex и без чтения графических схем как схем | `pd_rd_manifest_service`; CLI `tools/pd_rd_manifest.py`; tests `test_pd_rd_manifest_service.py` | [CODE_MAP.md](CODE_MAP.md) · [PD_RD_REGULATORY_BASE.md](PD_RD_REGULATORY_BASE.md) | ✅ |
| project/pdf-extract / Л.И.С.Т. | Единый source-map PDF-проекта без reindex: оркестрирует `drawing_manifest_v1`, `pd_rd_manifest_v1`, shared `project_pdf_table_manifest_v1` и дисциплинные readers в sidecar `_les_pdf_extract`; source-map остаётся навигацией, не evidence. `project_document_registry_service` строит read-only JSON-проекцию `Документация → проект → стадии → виртуальные тома → разделы → документы`; договоры/КП/сметы/переписка — связанные сущности. С 0.24.0.376 выпущенный PDF якорит том по cipher+discipline, supporting-файлы присоединяются по identity/discipline/stage, путь — последний fallback; каждый том показывает basis/confidence. `project_table_registry_service` строит адресный каталог: 32-hex `table_id` связывает SHA-256 PDF, page, bbox, полный header и версии algorithm/detector; exact read проверяет drift и возвращает `stale`, а не устаревший evidence. Shared table layer склеивает только безопасные соседние фрагменты одной страницы, наследует заголовок кабельного журнала, отделяет `ОТМ. 0.000` и распознаёт состав проекта; per-file checkpoint/resume сохраняется | `project_pdf_extract_service`, `project_pdf_table_service`, `project_table_registry_service`, `project_document_registry_service`; `/api/rag/datasets/{dataset_id}/pdf-extract/{status,run,summary}`, `/table-registry/build`, `/table-registry/summary`, `/tables/search`, `/tables/{table_id}`, `/document-registry/build`, `/document-registry`, `/virtual-volume`; model tools `search_project_tables`, `read_project_table`, `assemble_project_volume`; tests `test_project_pdf_extract_service.py`, `test_project_pdf_table_service.py`, `test_project_table_registry_service.py`, `test_project_document_registry_service.py`, `test_project_registry_router_contract.py` | [ALGO-pdf-ingestion.md](ALGO-pdf-ingestion.md) · [ALGO-electrical-schematics.md](ALGO-electrical-schematics.md) | ✅ |
| electrical/schematic-reader | Read-only MVP чтения электрических однолинейных схем, таблиц расчёта нагрузок и ВОР/СО: PDF text blocks + vector line primitives + candidate circuits + normalized load rows + material rows + model-facing summary; словарь `electrical_schema_terms.yaml` мапит `Руст/Pуст`→`p_installed_kw`, `Рр/Pр`→`p_calc_kw`, `Iр`→`i_calc_a`, `L/длина`→`cable_length_m`; materials layer отдаёт `cable/panel/lighting/containment/busbar/protection` rows, `doc_role`, кабельные марки/сечения/`quantity_m`, action/technical fields (`IP`, ток, напряжение/список напряжений, мощность, высота, dкаб, габариты, масса), product code/supplier/type mark; summary layer отдаёт source navigation, агрегаты нагрузок по щитам, cable/equipment inventory, SO→draft-VOR seeds и coverage counts + capped examples, но не кодовый отказ/вердикт; ВОР и СО не суммируются, следующие задачи — сверка ВОР↔СО и СО→draft ВОР; слой не утверждает топологию без читаемых подписей и отдаёт `unknown`/warnings вместо fake graph | `electrical_schematic_service`, `electrical_materials_service`, `electrical_evidence_summary_service`, `config/domain/electrical_schema_terms.yaml`; CLI `tools/electrical_schematic.py`, `tools/electrical_materials.py`, `tools/electrical_evidence_summary.py`; tests `test_electrical_schematic_service.py`, `test_electrical_materials_service.py`, `test_electrical_evidence_summary_service.py` | [ALGO-electrical-schematics.md](ALGO-electrical-schematics.md) | ✅ |
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
| infra/api-integrations | единая карта proxy/MLX/Lite API, локальных сервисов, внешних провайдеров, каналов доступа и безопасных имён конфигурации; внешний разовый документ идёт через пользовательский `POST /api/chat/attachments` → `attachment_id` → идемпотентный `POST /api/chat` → артефакт, а административный `/api/rag/attach` остаётся Совушке/совместимости; цены ресурсов доступны одиночно и пакетом | `proxy/app.py`, `proxy/routers/{chat,datasets,prices}.py`, `proxy/services/{chat_attachment,request_idempotency}_service.py`, `proxy/routers/settings.py`, `sovushka/lite_bridge.py`, `mlx_host.py`, `env.example` | [LES_API_AND_EXTERNAL_INTEGRATIONS.md](LES_API_AND_EXTERNAL_INTEGRATIONS.md) | ✅ |
| infra/mlx | TTL-выгрузка, memory-guard, профили памяти; hard-stop локального чата отделён от операторских GREEN/YELLOW/RED границ; настоящий `mlx_lm.stream_generate` логирует TTFT/prefill/decode/peak memory; direct OpenAI benchmark различает stream/non-stream, cache и tools; изолированный OptiQ probe принудительно проверяет MTP single-path, sampler forwarding, acceptance и Metal memory без production dependency; 9B — целевой профиль M4/24 ГБ, 4B — диагностика/малопамятный режим | `backend/mlx_adapter`, `mlx_host.py`, `proxy/services/runtime_admission.py`, `tools/local_inference_benchmark.py`, `tools/optiq_mtp_probe_server.py` | [MLX_GUIDE.md](../MLX_GUIDE.md), [RUNTIME_MEMORY_PROFILES.md](../RUNTIME_MEMORY_PROFILES.md) ✅; [LOCAL_INFERENCE_OPTIQ_MTP_M4_2026-07-13.md](LOCAL_INFERENCE_OPTIQ_MTP_M4_2026-07-13.md) ✅; [TODO_LOCAL_INFERENCE_BENCHMARK.md](TODO_LOCAL_INFERENCE_BENCHMARK.md) 📋 | ✅ |
| ops/deploy | dev→рантайм cp-деплой + stamp; scope включает committed diff от последнего реально задеплоенного commit, manifest защищает runtime-only divergence; откат | `tools/deploy_to_runtime.py`, `tools/restore_runtime.sh` | [SKILL.md](../SKILL.md) 🟡, [RELEASE_LEDGER.md](RELEASE_LEDGER.md) | 🟡 |
| ops/versioning | единый центр версий + divergence repo↔runtime | `version_service`; `GET /api/version` | [RELEASE_LEDGER.md](RELEASE_LEDGER.md), [VERSIONING.md](VERSIONING.md), [releases.md](releases.md) | 🟡 |
| ops/service-sources | видимый реестр служебных источников для смет и нормоконтроля; `SMETA_SERVICE` Play показывает manifest требуемых сметных документов и форматов по классам нормы/цены/методика/формы | `service_source_registry`; `routers/service_sources.py`; `config/service_sources.yaml`; GUI `sovushka/pages/instrumenty.py`, чат `sovushka/pages/chat.py` | [SKILL.md](../SKILL.md), [CODE_MAP.md](CODE_MAP.md) | ✅ |
| ops/external-radar | радар внешних папок: configured roots + filemap + in-place `source_path` без reindex/OCR/LLM; ручная сверка in-place датасета по папке показывает new/changed/deleted и может синхронизировать изменения без фонового watcher-а. С 0.24.0.200 добавление/синк внешней папки с `parse=true` создаёт видимый dataset-scoped `rag_parse_drain` job и продолжает bounded партии, а одиночный `parse-batch` честно показывает `PARTIAL`, если pending ещё остался. С 0.24.0.232 GUI `+ папка` сначала показывает transparent intake plan: project/dataset, accepted/skipped, `LES.md`/`00_dataset_map.md`, discipline hints и missing для расчётных задач; с 0.24.0.235 карты создаются как служебный слой папки, но не регистрируются как RAG-документы. С 0.24.0.315 Google Drive / Яндекс Диск можно подключать через web/API: облачная папка синхронизируется в mirror-кэш и дальше регистрируется существующим `index-external`; локальные sync-папки остаются fallback | `external_radar_service`, `cloud_drive_service`; `GET /api/external-radar/summary`; `GET /api/rag/cloud-drives`; `POST /api/rag/cloud-drives/list`; `POST /api/rag/cloud-drives/sync`; `POST /api/rag/external/intake-plan`; `POST /api/rag/index-external`; `POST /api/rag/external/check`; `POST /api/rag/external/sync`; `POST /api/rag/parse-batch/{dataset_id}`; GUI Самовар | [ALGO-external-radar.md](ALGO-external-radar.md) | ✅ |
| ops/public-showcase | curated public GitHub/Pages surface без приватных датасетов и runtime-секретов; README объясняет evidence-harness, единый dense+sparse native RRF, typed readers, Л.И.С.Т. и ФГИС ЦС; release staging исключает `.codex_tmp/**` и `tmp/**` | `README.md`, `docs/index.md`, `docs/public/*`, `tools/publication_check.py`, `tools/build_release_artifacts.py` | [PUBLICATION_CHECKLIST.md](PUBLICATION_CHECKLIST.md), [public/overview.md](public/overview.md) | ✅ |
| ops/test | гейт (verify/test/smoke-basic); Windows release smoke запускает установленный runtime, ждёт terminal `ready`, проверяет API/UI/Qdrant и фактический `dense + qdrant_sparse → RRF → rerank`; timeout остаётся failure/warn, а не silent hang | `Makefile`, `tools/basic_function_smoke.py`, `tools/windows_release_smoke.ps1` | [TEST_INVENTORY.md](TEST_INVENTORY.md) ✅ | ✅ |
| install | Tauri 2 — канонический Mac/Windows shell над NiceGUI; **production target — Legion/Windows**, Mac — dev/reference. Rust владеет окном/tray/health/lifecycle, Python остаётся backend sidecar. Финальный Tauri/NSIS EXE собирается на Windows. Свежая Windows-установка держит заменяемый код в латинском `%LOCALAPPDATA%\Programs\LES`, mutable state/venv — отдельно в `%LOCALAPPDATA%\LES`; существующая установка обновляется на месте. Выпускной staging платформенный: Windows не получает macOS `bootstrap.sh`, Mac не получает Windows bootstrap. `windows-lite` мигрирует legacy с backup и требует полный локальный RAG-контур: `uv`, Ollama и Docker Desktop ставятся через winget либо показывается официальный адрес; Docker/Qdrant не деградируют молча. Bootstrap пишет `bootstrap-status.json`, Tauri запускает PowerShell без консольного окна и показывает точную причину/код/ссылку/журнал. Named Qdrant volume, `bge-m3`/1024 и checksum/load-probe проверенный `BAAI/bge-reranker-v2-m3` сохраняются. Живой выпускной gate отдельным процессом проверяет terminal `ready`, API/UI и native RRF, не зависая на stdout дочерних служб. Обновления только ручные: проверка → отдельная установка, GitHub asset + SHA-256, без фоновой проверки. Legacy pywebview shell не входит в обязательный runtime | `desktop/tauri`, `desktop/tauri/src-tauri/windows-installer-hooks.nsh`, `tools/build_tauri_app.py`, `tools/build_{macos_app,windows_installer}.py`, `tools/windows_release_smoke.ps1`, `installers/windows/{state,start-light,stop-light}.ps1`, `installers/windows/app/bootstrap.ps1`, `tools/onboard_reranker.py`, `proxy/services/{update_service,smeta_chat_adapter_service}.py`, `proxy/routers/updates.py`, `backend/reranker.py` | [INSTALL_RUNBOOK.md](INSTALL_RUNBOOK.md) ✅, [PLATFORMS.md](PLATFORMS.md) ✅, [CODE_MAP.md](CODE_MAP.md) | ✅ |

**✅ исправлено:** SKILL/TEST_INVENTORY → v0.23/~2063/smoke-basic done; PROXY_ARCHITECTURE → `les_meta_qwen.db`; INFRASTRUCTURE_v2.0 (мёртвое) → archive. Версии (3 оси) объяснены в [RELEASE_LEDGER.md](RELEASE_LEDGER.md); 0.23.N.P внедрено в `version_service`. В 0.23.6.2 добавлены checksum для backup/restore и сужены дефолтные trusted loopback/proxy-сети; в 0.23.6.3 скрепка чата стала реальным контекстом/payload scope; в 0.23.6.4 закреплены светлая тема по умолчанию, скрытая панель артефактов и OpenAI-compatible `gpt-4.1` fallback; в 0.23.6.5 добавлен явный GUI-контроль открытия артефактов и управляемый fail-path чтения вложений; в 0.23.6.6 source chips открывают citation drawer без fake-open; в 0.23.6.7 router-primary стал explicit opt-in, чтобы убрать 12s latency fallback; в 0.23.6.8 read-вложение стало видимым файлом следующего сообщения, plain file-reading идёт без глобального RAG, direct/router LLM без облачного ключа уходит в локальный MLX; в 0.23.6.10 `make ship` стал быстрым итерационным gate, `make ship-full` — полным release gate с retry post-smoke; в 0.23.6.11 нормоконтрольный чат отдаёт defense-report и top-level `defense`; в 0.24.0.1 служебные источники доступны из чата отдельной панелью.

## 6. Прочие модули (отдельные продукты/контуры)

| Модуль | Назначение | Док |
|---|---|---|
| cad-bim | CAD/BIM граф + вьювер (three.js/web-ifc); DWG/DXF путь идёт через `tools/cad_bim_extract_dxf.py` (`dwg2dxf` → DXF repair-pass при битых group-code строках → реконструкция нарисованных таблиц `LINE/LWPOLYLINE`+`TEXT/MTEXT` → `cad_bim_graph.json` → `/api/cad-bim/import`) и затем `sync-smart` projections в `CAD_BIM_Index`; projection выводит `CAD drawn tables`, `first positions`, `logical positions`, data row-lines и compact row-lines перед поэлементным шумом; `retrieval_service` для `target_file` умеет `first_ordinal_guard` по фактическим `position N`; `GET /api/cad-bim/imports` даёт read-only inventory импортов, слабых графов, дублей и статуса индексации projection; Совушка «Документы» → `CAD` показывает эти рычаги человеку | (в [CODE_MAP.md](CODE_MAP.md); `routers/speckle.py` = `/api/cad-bim/*`) |
| artel | генератор семейств Revit (отдельный Win+Revit пакет) | `products/artel/skills/*/SKILL.md` |
| mail (Е.Ж.И.К.) | приёмка почты IMAP/Apple Mail/.olm | (в [CODE_MAP.md](CODE_MAP.md)) |
| mcp | ЛЕС как MCP-сервер (18 инструментов наружу, включая пакетный поиск цен ФГИС) | `tools/les_mcp_server.py` (в [CODE_MAP.md](CODE_MAP.md)) |

---

## Шаблон дока модуля (`docs/modules/<name>.md` или `docs/ALGO-<name>.md`)

```
# <Модуль> — <одна строка назначения>
Назначение · Точки входа (сервис/роутер/MCP/чат) · Данные/конфиг · Зависимости ·
Поток (формулы/шаги, 0 LLM где про числа) · Статус-vs-код (что сверено) · Грабли/границы · Тесты
```

> Канон 0-LLM ядер — `docs/ALGO-*.md` (по кирпичу). Этот индекс их агрегирует; при добавлении/правке
> модуля — обнови строку здесь и поставь честный статус (✅/🟡/🗄/📋).
