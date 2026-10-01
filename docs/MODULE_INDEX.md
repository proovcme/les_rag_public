# MODULE_INDEX — карта модулей Л.Е.С.

> **Кандидат 0.31.122 / 850:** `core/chat-evidence`/`core/workbook-research`
> сохраняют review baseline IDs, точные цитированные карточки и замечание по
> lineage при пересмотре/продолжении. `record_packet` пишет следующую ревизию
> прежнего ID; новые accepted rows только из ответа модели. Pending-only очередь
> и подтверждения оператора также наследуются. Док↔код ✅; `workbook_chat_review_context`,
> `model_rag_existing_operation_rows`, `chat_review_context`,
> [chat-profiles](modules/chat-profiles.md), `test_workbook_chat_refinement.py`.
> Live 849: 163 unknown_operation_id, 35 unknown_evidence_ref; fixed validation
> and evidence replay are pending installed acceptance, not customer-ready.

> **Кандидат 0.31.121 / 849:** `core/chat-evidence` safe workbook history/harvester
> сохраняют все VOR source audit warnings; `/api/chat/repack-lsr` возвращает VOR
> readiness для VOR, включая незакрытые исходные объёмы. Точки:
> `safe_workbook_history_projection`, `harvest_workbook_tool_result`,
> `repack_lsr_without_model`. Док↔код ✅; [ADR-15](ADR-15-model-rag-result.md).
> Две regressions red before; focused 270 passed. Offline 2046 passed /
> 20 existing opt-in skipped / 5 warnings; verify 2066, compileall/version/
> architecture passed. Installed pending.
>
> **Установленная 848, a47eb6a9:** 18/18 patch hashes, native RRF 1/1,
> basic 9 pass / 1 WARN / 0 fail; immutable old VOR/LSR recovery exact.
> Большой клиентский ВОР: repack 427 saved decisions, 22.2 с без model call,
> 185 positions built / 23 calculated, preliminary 7810166.92, priced_partial.
> Новая revision/SHA/parent/replay совпадают, все model decisions неизменны.
> Это тест расчёта/доставки масштаба, не свежий полный inference или профприёмка.
> ВОР ЭОМ repack сохраняет 83 строки/роли/замечания в XLSX; API carrier терял
> source audit field, что воспроизведено и закрывается в 849.

> **Кандидат 0.31.120 / 848:** `core/rim` учитывает множитель исходной единицы;
> catalog/adapter/trace подтверждают физически равные меры. `header_bound_unit`,
> `_attach_catalog_facts`, `_norm_qty_from_visible_row` — точки входа.
> `core/workbook` сохраняет model VOR decisions и на XLSX, не заменяет их spec
> reader/derive dictionary. В ВОР сохраняются роли, связи и замечания; материалы
> также сверяются с исходником, без подмены количества. Receipt сохраняет
> vor_source_errors при replay. Док↔код ✅; [ALGO-lsr-assembly](ALGO-lsr-assembly.md),
> [ALGO-spec-to-bor](ALGO-spec-to-bor.md), [ADR-15](ADR-15-model-rag-result.md).
> Regressions red before; focused quantity/price 116 passed, VOR/trace 137 passed.
> Offline: 2045 passed / 20 existing opt-in skipped / 5 warnings; verify 2065,
> compileall/version/architecture и active artifacts passed. Installed проверки
> ещё ожидаются; customer-ready нет.
>
> **Замер установленной 847:** 12/12 patch hashes, native RRF 1/1,
> basic 9 pass / 1 WARN / 0 fail; old VOR/LSR recovery same bytes/SHA.
> ЭОМ PDF→ВОР B0: 310.6 с, no file, два реальных work quantity/unit conflicts.
> B1: 1058.7 с, 51/51 учтены, 83 строки (31 work/44 material/7 header/1 unresolved),
> XLSX скачивается, SHA совпадает. Независимая сверка обнаружила 11 material rows
> с неверными источниками/объёмами; это измеренный дефект, не приемочный успех.
> Source parser не сдвигает колонки после 847, остаток — authored decisions.

> **Кандидат 0.31.119 / 847:** `rag/pdf` сохраняет координаты пустых ячеек
> разреженных таблиц; количества больше не сдвигаются под соседние заголовки.
> CSV catalog исправляет ту же потерю пустых полей (`;` и `,`). Точки:
> `pdf_layout._table_to_markdown`, `attachment_source_catalog_service`;
> док [ALGO-pdf-layout](ALGO-pdf-layout.md), [ADR-15](ADR-15-model-rag-result.md).
> Четыре regressions red before, focused 21 passed / 1 existing corpus-absent skip.
> Оригинальные количества 25/14/43/25 подтверждаются reader после исправления.
> Док↔код ✅; offline 2039 passed / 20 existing opt-in skipped, verify 2059,
> compileall/version/architecture/active artifacts passed. Installed comparative
> gate pending. Customer-ready нет.
>
> **Кандидат 0.31.118 / 846:** `intake/chat-attachment` обнаруживает image-only
> DOCX по OOXML и возвращает OCR-required HTTP 422 до сохранения/chat; подписи
> картинок не считаются содержимым исходника. Точки:
> `chat_attachment_service.docx_is_image_only`, `datasets._prepare_read_attachment`;
> док [ADR-15](ADR-15-model-rag-result.md), tests `test_datasets_router.py`.
> Transitional/strict OOXML, смешанный текст и altChunk покрыты; 65 focused passed.
> Installed 11/11 hashes; native RRF 1/1, basic 9 pass / 1 WARN / 0 fail,
> immutable recovery same revisions/SHA/price basis. Extra mail gate 66 passed.
> Fresh БАП B1/64K: 19/19 source rows, 467.8 с, 8 calculated positions;
> полный расчёт не готов (4 norms missing, 7 applicability gaps, 18 price gaps).
> Новый ЭОМ PDF показал общий дефект разреженных колонок, исправляемый в 847.
> Customer-ready не заявлено.
>
> **0.31.117 / 845:** `core/chat-evidence` и workbook research store
> version cache entries, refresh incompatible pending queries with the same
> declared wording, preserve old hits in superseded and all authored decisions.
> Prior model context excludes only application diagnostic duplicates, preserving
> the exact cited card bodies. `core/rim`/readiness report exact_match_unresolved
> when an explicit no/unknown fact contradicts EXACT; no status/cipher rewrite.
> Regressions reproduced first; focused 325 passed. Док↔код ✅;
> [rag-evidence-flow](modules/rag-evidence-flow.md), [ALGO-lsr-assembly](ALGO-lsr-assembly.md).
> Offline: 2032 passed / 20 existing opt-in skipped; verify/architecture green.
> Installed 16/16 hashes; B1 БАП: 19/19 source rows, 6 calculated positions,
> 737.2 с; full estimate incomplete. СКС resume: 11→35/75 accounted,
> price basis and parent revision preserved; control paused by operator.
> Customer-ready не заявлено.

> **Кандидат 0.31.116 / 844:** `core/chat-evidence` model norm reader явно
> выключает legacy vocabulary expansions; `norm_browser.browse_norms_many` default
> тоже literal. ADR-16 systematic builders, dense+sparse RRF и rerank не
> меняются. На 843 locator «СКС!Rn» добавлял cable queries для шкафа/шины;
> generic source-label regression воспроизвела потерю query identity.
> Код↔док ✅; installed comparative/financial gate pending.

> **Кандидат 0.31.115 / 843:** `core/chat-evidence` разрешает модели
> формулировать поиск монтажной операции вместо буквального изделия.
> Дословность относится к исполнению уже объявленного запроса; systematic
> candidate builders ADR-16 не изменены. `core/chat-profiles` просит таблицу
> первой, без длинных последовательностей пустых маркеров. Код↔док ✅;
> installed comparative/financial gate pending. Замер 842 не проходит
> customer gate: 11/75 СКС, 0 work/calculated, evidence_capacity; durable IDs
> работают, ошибочный расчёт mounting norm на supply не повторился.

> **Кандидат 0.31.114 / 842:** `core/chat-profiles` основной plain-text output
> contract требует эхо application operation_id, отделяет work от наличия
> нормы в ВОР и не разрешает вывод о недостающих строках по одному пакету.
> `core/rim` сохраняет material/equipment/header + mounting cipher как явный
> role_norm_conflict без начисления монтажных ресурсов на поставку;
> RIM/readiness norms counters относятся только к work. Док↔код ✅;
> [chat-profiles](modules/chat-profiles.md), [rag-evidence-flow](modules/rag-evidence-flow.md).
> Reproduction first: 3 failed, focused after 119 passed. Offline/live pending.
> Нормы/роли кодом не заменяются; customer-ready не заявлено.

> **Кандидат 0.31.113 / 841:** `core/chat-evidence` сохраняет все Q/H refs,
> передавая точные повторы карточек одного источника одним телом на странице.
> Canonical operation IDs после record_packet возвращаются в следующий
> model context; parser сохраняет ID, validator запрещает неизвестный ID
> и смену его source_row. Surplus explanatory cell не сдвигает unit/quantity/status.
> Док↔код ✅; [rag-evidence-flow](modules/rag-evidence-flow.md),
> `_model_rag_exact_card_key`, `model_rag_prior_page_context`,
> `parse_model_rag_result`, `validate_model_rag_result_structure`.
> Focused 284 passed. Installed gates pending; профессиональная готовность
> не заявлена. Измеренная 840: B1 920.8 с, 23/75 accounted, 0 calculated;
> данные сохранены для resume. Подтверждён регресс времени/покрытия.

> **Кандидат 0.31.112 / 840:** `core/chat-evidence` резервирует тела всех
> карточек запроса до optional previews; хвост evidence не исчезает после
> терминального ответа строки. Durable cursor и прежние cited cards проходят
> resume; selected groups mandatory в ContextGovernor. Выбор нормы/решения
> остаётся модели. Док↔код ✅; [rag-evidence-flow](modules/rag-evidence-flow.md),
> `model_rag_evidence_page_state`, `model_rag_prior_page_context`,
> `select_model_rag_query_hits_for_budget`. `core/workbook-research` проверяет
> точный suffix/cursor, отличая доставку страниц от неизменившегося retry;
> профессиональное решение не повышается. Six regressions, focused 236
> passed. Installed comparative gate pending; customer-ready не заявлено.

> **Кандидат 0.31.111 / 839:** `core/tool-harness` передаёт все exact варианты НР/СП
> для сборника карточки без выбора ставки и путей. `core/chat-profiles` сохраняет
> `nr_sp_rule_id` в decoder/контексте пересмотра; `core/rim` — в позиции расчёта.
> Missing/foreign choices не закрываются. Док↔код ✅; [chat-profiles](modules/chat-profiles.md),
> `nr_sp_service.model_candidates`, `_norm_card_content`, `positions_from_visible_lsr_rows`.
> Budget renderer сохраняет источник и все варианты НР/СП shown карточки целиком.
> 7 regressions failed before, focused 248 passed after. Installed tested code
> 96db6fa1: offline 2000 passed/20 opt-in skipped, alignment 96/96, RRF 1/1,
> basic 9 pass/1 diagnostics WARN/0 fail, recovery same revision/SHA. SKS 75/75,
> 0 calculated works; PDF→LSR 19/19, 6 calculated, partial, exact match fields
> absent. PDF→VOR 3 unresolved rows have incomplete quantity/unit cells.
> Финансовый/профессиональный gate НЕ пройден; [ledger](RELEASE_LEDGER.md),
> `artifacts/live_839` сохраняют реальные результаты, customer-ready не заявлено.

> **Кандидат 0.31.110 / 838:** `core/chat-profiles` передаёт наблюдаемую UTC дату
> и bounded каталог файлов цен estimator-модели до query/result. Нет ставок,
> выбора книги, путей или подтверждения норм. Большой каталог явно частичен;
> non-estimator его не читает. Док↔код ✅; `model_runtime_facts`,
> [chat-profiles](modules/chat-profiles.md), four runtime-facts regression tests.
> Live 837 СКС: 75/75, 2 нормы с совпадающими citations, 0 полных расчётов;
> preliminary 160711.54. Финансовая готовность не объявляется.

> **Кандидат 0.31.109 / 837:** `core/tool-harness` перестал терять resource_preview
> и прочие исходные поля typed нормы на пути к модели. `_norm_card_content`
> явно различает состав работ и ограниченный обзор ресурсов; отсутствующий
> состав не изобретается. Retrieval/выбор нормы не меняются. Док↔код ✅;
> [ALGO-tool-harness](ALGO-tool-harness.md), `test_model_research_tool_service.py`.
> `core/chat-evidence`: query/answer instructions соответствуют текущему пакету,
> не просят весь лист повторно; множество модельных операций не ограничивается.
> Regression: `test_sheet_packet_prompts_do_not_request_the_whole_sheet_again`.
> `core/chat-profiles`: `build_vor_result_readiness` сохраняет авторские вопросы
> и отделяет `vor_complete` от доставки; короткий skill не требует нормы для
> известной работы ВОР. [chat-profiles](modules/chat-profiles.md). Док↔код ✅.
> Live 836: recovery ВОР/ЛСР повторяет revision/SHA/снимок; fresh СКС 75/75
> учтено, но 0 норм/0 рассчитанных позиций. Финансовый gate не пройден.

> **Кандидат 0.31.108 / 836:** `smeta/workbook-tools` сохраняет
> `calculation_snapshot` вместе с ревизией. Повторная доставка возвращает те же
> суммы, price_basis, row_projection и gaps, не считает старый файл заново.
> Док↔код ✅; `_result_from_revision`, `test_workbook_tool_service.py`,
> [ALGO-tool-harness](ALGO-tool-harness.md).

> **Кандидат 0.31.107 / 835:** `core/chat-profiles` передаёт свободное замечание
> в обычный проход исходного документа без обязательного JSON-плана;
> `reopen_locators(chat_review=…)` хранит прежние строки и подтверждения пользователя.
> `smeta/workbook-tools` атомарно выдаёт следующий свободный номер ревизии
> при старом родителе или параллельной доставке, сохраняя parent и старые bytes.
> Док↔код ✅; `workbook_chat_review_needed`, `begin_workbook_chat_review`,
> [chat-profiles](modules/chat-profiles.md), `test_workbook_chat_refinement.py`.

> **Кандидат 0.31.105 / 833:** `workbook_document_from_events` сохраняет тип
> ВОР в проекции задания, чате и repack. ВОР получает свою цепочку ревизий и
> сообщение без требований ЛСР к нормам/ценам. Док↔код ✅; regression в
> `test_packaging_recovery_service.py`; [chat-profiles](modules/chat-profiles.md).

> **Кандидат 0.31.104 / 832:** `core/sovushka-ui` разрешает номера позиций
> текущей ЛСР через `row_projection`, отклоняет неизвестные/неоднозначные номера
> до мутации задания, прячет ручной перевод единиц в дополнительный блок.
> Док↔код ✅; `resolve_lsr_position_selectors`, `test_sovushka_chat.py`.

> **Кандидат 0.31.103 / 831:** `core/chat-profiles` и workbook sheet-pass сохраняют
> явные параметры задания до первой упаковки (`task_context_json`,
> `requested_price_basis`, `task_document_price_basis`); исходный пакет передаётся
> как `required_evidence`; обработанные строки показаны отдельно от структурной
> готовности. Заводской сметный skill: `skills/smeta/references/rag-estimator.md`.
> Док↔код ✅; установленная приёмка и полнота денежного расчёта пока не подтверждены.
> Детали: [chat-profiles](modules/chat-profiles.md), [UI-kit](modules/sovushka-uikit.md).

> **0.31.102 / 830:** сохранённый токен статуса перестал быть доказательством, а чат и тон подписывают
> расчёт тем же словом, что и форма (`proxy/services/gesn_service.py`,
> `proxy/services/rim_lsr_trace_service.py`, `proxy/services/lsr_assembly_service.py`,
> `proxy/services/smeta_chat_service.py`, `proxy/services/sovushka_tone.py`,
> `tools/architecture_contract_gate.py`). Readiness пересчитывает цитату из тех карточек, которые
> модель действительно привела (`cited_ciphers_of`), а не верит сохранённому флагу: замер на
> собственных долговечных строках установленного хранилища — 280 из 1082 EXACT-строк ссылаются на
> карточку, в теле которой назван другой шифр, и ещё 440 считались «согласием» только потому, что
> вердикта в старом payload не было. Вопрос применимости живёт в одной функции
> (`applicability_gap_kind`), которую читают и колонка XLSX-трассы, и денежный гейт, и карточка
> readiness, и назван отдельной причиной `cipher_without_cited_card` — пять различных причин вместо
> одного «не готово». Эталон пересеян с демо-семени на основную базу: **12 679,40** (карточка
> `ГЭСН12-01-034-02` × книга `sankt-peterburg_2kv2026`, `priced_partial`, дыра
> `price_missing:11.1.03.01-0076`) вместо суммы семени 11 813,04; семя вынесено из производственного
> слияния, закреплённые суммы больше не читают книгу оператора (`tests/pricebook_probe.py` плюс
> `tests/test_pricebook_hermeticity_830.py` — 223 passed и без probe, и с ним, а отрицательный
> контроль под probe красный), и обе лестницы цены обязаны назвать владельца ставки
> (`price_is_attributed`, нарушение `UNOWNED_PRICE_SOURCE_ADOPTED`). Тон над `partial` и
> `unsafe_source` больше не обещает «можешь не перепроверять» (20 из 28 достижимых формулировок
> сборки → 0 из 28), над `not_calculated` рамки нет вовсе; чат берёт слово подписи у самой трассы
> (`position_total_label`) и печатает основания трассы, когда ⚠-флага нет. Gate: канонический
> `CURRENT_TESTS`, развёрнутый из Makefile в 147 файлов, — 1907 passed / 20 skipped
> (`stage_b/live_830/current_tests_830_shipped.log`), доковые гейты после записи в леджер и сюда —
> 49 passed (`stage_b/live_830/gates_830.log`); карта регенерирована (1038 файлов, 340
> маршрутов). Ни один тест не ослаблен. Живая приёмка установленного приложения сделана и
> измерена: деплой `status=deployed` (34/34 поверхностей, smoke `pass=10 warn=0 fail=0`), данные
> клиента не сдвинулись, а `stage_b/verify_installed_830.py` прогнан дважды — по коду
> установленного `runtime` и по коду worktree, 16 проверок, `all_passed: true` в обеих половинах
> (`stage_b/live_830/installed_live_830.md`): 12 679,40 как `known_amount` при `full_amount = null`
> и именованной дыре, 0,00 и 7 дыр без книги, `labor_code_trace.derived = 0`, лист «ЛСР РИМ» с
> подписью «Известная стоимость позиции», итогом-формулой и строкой дыры без цены, 49 865 карточек
> производственной view при 0 карточках семени, реплика чата без обещания не перепроверять.
> Прогон модели здесь не участник: сметный канал отвечает до хода LLM. Не закрыты § 5 (штатный
> рестарт теряет провайдера) и построчный позитивный прогон большого ВОР клиента: 318/318 работ
> учтены, каждой частичной строке названа причина и ложных зелёных в доставленном файле нет, но
> `calculated_with_money: 0` — первая упаковка большого ВОР случилась на ходе «Продолжи это же
> задание», где названной в задании книги нет, а наследовать базе было нечего
> (`workbook_packaged → price_basis: {}`); контроль на той же сборке и с тем же текстом задания —
> малая Каменка: `B0_camenka` (фактор системных кандидатов `off`) даёт 10 из 27 блоков с деньгами,
> `B1_camenka` (фактор `on`, как у большого ВОР) — 19 из 35, оба с `sankt-peterburg_3kv2026`,
> `match: exact` и базой, выведенной из хода задания. Подробно —
> [RELEASE_LEDGER.md](RELEASE_LEDGER.md).

> **0.31.101 / 829:** reader ответа модели перестал терять решения из-за оформления строки
> (`core/chat-evidence`, `proxy/services/model_answer_table_service.py`,
> `proxy/services/chat_evidence_application_service.py`,
> `proxy/services/lsr_norm_quality_gate_service.py`). Дефект измерен на сохранённом корпусе
> установленного приложения, а не найден разбором: из 369 ответов, содержащих `|`, пять не
> читались совсем, а в восьми строки читались частично (`stage_b/live_829/rendering_diff_829.json`).
> Три причины, каждая привязана к чат-строке: метка `[Источник 1]`, которую требует сам prompt,
> приклеена к строке заголовка (506 — заголовок не узнавался, `parsed_rows = 0` при записанном
> решении); выравнивающая ячейка из двух дефисов `|:--|` (53, 55, 76 — с 8007b38a reader требовал
> не меньше трёх дефисов, и таблица ВОР!R4…ВОР!R41 из 38 строк не читалась вовсе); строки без
> внешних `|` (330 — внешние разделители в markdown необязательны, reader останавливался на первой
> такой строке и терял все разделы ниже). Теперь формат живёт в одном модуле и его вызывают и
> `parse_model_rag_result`, и `parse_quality_table`: срезается только оформление строки, значения
> ячеек остаются дословными, `[Q4.H1]` и любое значение в квадратных скобках внутри ячейки меткой
> не считаются. Обратная сторона терпимости закодирована: строка заметно уже таблицы и не открыта
> как табличная — проза, и таблица на ней заканчивается, а не дописывается пустыми ячейками до
> «решения» (§ 1 — технический дефект чтения не становится «нет нормы»; § 2 — «выбрано» нельзя
> измерять, если строка решения не доходит до записи; § 3 — «reader — сохранить»). Правка строго
> добавочна и это проверено отдельно, а не по ощущению: восстановлено 5 ответов (+128 позиций),
> 8 ответов получили строго больше строк (+286, всего 14470 → 14756), `lost_answers = 0`, а по 13
> затронутым ответам каждая ранее прочитанная строка присутствует после правки дословно и текст
> ответа возвращается без изменений (`stage_b/live_829/additivity_829.json`). Ни одно поле модели
> не заполняется и не переименовывается кодом. Regex в чтении результата модели не появился —
> `tools/architecture_contract_gate.py` это проверяет. Tests: `tests/test_model_answer_table_service.py`
> (новый, 7), `tests/test_chat_evidence_application_service.py` (+4, в том числе три настоящих
> формата из корпуса; прежний `test_model_rag_result_rejects_ambiguous_short_dividers` переписан
> под измеренный контракт, а не удалён — он кодировал именно то правило, которое выбрасывал 38
> реальных строк). Ни один тест не ослаблен. Gate: `make verify` — 1780 collected; `make test-unit`
> — 701 passed / 2 skipped; полный `make test` — зелёный (`stage_b/live_829/test_829.log`); карта
> регенерирована (1029 файлов, 338 маршрутов). Живой проверки на установленной 829 на момент
> записи ещё нет, и § 3/§ 4/§ 5 эта правка не закрывает.

> **0.31.100 / 828:** «найдено» в замере § 2 — это пул, который поиск сматчил, а не срез
> `model_evidence_k` (`core/chat-evidence`, `proxy/services/chat_evidence_application_service.py`,
> `proxy/services/model_research_tool_service.py`). Дефект измерен архивными замерами одного
> документа, а не разбором: `stage_b/live_824/b2_query_pollution_824.json` даёт min = median = max = 6
> на 1004 запросах, `stage_b/live_826/b2_query_measurement_826.json` — 29 строк с `found = 6`,
> `stage_b/live_827/b2_query_measurement_827.json` — `found values {6: 42}` при `model_visible`
> 12 / 24 / 22 по группам; две величины были неразличимы по построению, потому что счёт снимался
> после обрезки, а немодифицированный пул (`fusion_candidates` у браузера норм, `merged_count` у
> канонического RRF) инструмент выбрасывал. Теперь число несёт каждая доставленная карточка
> (`meta.matched_before_cap`) и payload вызова (`matched_before_cap`, `verified_before_cap`,
> `evidence_cap`), строка замера держит `returned_within_cap` рядом с `found`, а `found_basis`
> разделяет `pre_cap_pool` / `pool_within_cap` / `pool_not_reported` — без метки запись кэша или
> пустой пул выглядела бы доказательством, что карточек в базе ровно шесть; групповая свёртка
> несёт `found_from_pre_cap_queries`. Глубина поиска, `candidate_k` и `model_evidence_k` не
> изменены, в промпт не добавлено ни одного символа (тест проверяет, что отрендеренный текст не
> содержит ключа и даёт те же заголовки карточек). Остаток § 2 задокументирован и не закрашен:
> строка модели о самом поиске («Прочитал приложенный материал целиком. Сформуировал поисковые
> запросы…») исполняется как запрос — 1 из 29 модельных запросов по сохранённому корпусу
> (чат-строка 500, `rejected = 0`); двухмерные структурные правила измерены и отклонены
> (морфология глагола отвергает и настоящие формулировки ВОР, `. ` как граница предложения
> отвергает дословный текст строки «Тип А. Комплектная система КНАУФ С112. …»), а пополнение
> списка русских префиксов § 2 запрещает; новый флаг
> `narration_is_not_executed_as_a_query` падает на реальном случае, а
> `prose_is_separated_with_a_reason` получил состояние `NOT_EXERCISED` вместо зелёного marks на
> ненагруженном пути (§ 6). Tests: `tests/test_model_research_tool_service.py` (8 → 9),
> `tests/test_model_rag_query_declaration.py` (17 → 20). Ни один тест не ослаблен. Gate: `make verify`
> — 1770 collected; `make test-unit` — 691 passed / 2 skipped; полный `make test` — 1750 passed /
> 20 skipped (`stage_b/live_828/test_828.log`); карта регенерирована (1027 файлов, 338 маршрутов).
> Docs: `docs/modules/rag-evidence-flow.md`, `docs/RELEASE_LEDGER.md`. Живой замер на установленной
> 828 на момент этой записи не выполнен — без него § 2 не закрыт; профессиональную правильность
> подбора норм правка не доказывает, § 3…§ 6 открыты.


> **0.31.99 / 827:** шапка столбцов клиентского ВОР перестала читаться как подытог, каталог источника связывает строки с колонками, и написанные в 826 фильтр служебных колонок и группа `derived` впервые сработали на боевых данных (блок-лист `QWEN_BLOCKERS_AFTER_823_2026-09-29.md` § 2; `data/attachment-source-catalog`, `proxy/services/attachment_source_catalog_service.py`). Измерено пробой на боевом загрузчике (`stage_b/b2_header_probe_827.py`; до — `stage_b/live_826/header_probe_before.json` и `header_probe_before_groups.txt`, после — `stage_b/live_827/header_probe_after_fix.txt`): `header rows: []` на всех 439 строках → `header rows: [СВОДНАЯ!R7, АР!R8, АПС!R8, ВК!R8, ПТ!R8, СКС!R8, СКУД!R8, СОУЭ!R8, ЭОМ!R8, ОВиК!R8]`, классы `{'note': 24, 'subtotal': 29, 'ambiguous': 100, 'work': 286}` → `{'note': 24, 'header': 10, 'subtotal': 19, 'ambiguous': 100, 'work': 286}` (знаменатель работы не тронут), привязка количества на живых отказах `0/11` → `11/11` (`АР!R11 → 98.6`), на листе АР `99/99` строк привязаны и `79` с вычисленным значением, по пакетам в 10 строк `original 99 + derived 0` → `original 99 + derived 79`, служебных ячеек отброшено `0/641` → `384/641`, запросов с текстом формулы или «итого» — `0`, отложенных бюджетом — `0`; `line` строки размечен заголовками (`98.6 [Кол-во]`). Корень: шапка листа называет денежные колонки («Материал (итого), руб. без НДС»), содержит слово подытога и не даёт числа (деньги — формулы), поэтому правило подытога брало её себе, `column_headers` оставался пустым, количество работы читалось как номер позиции (`1.2`), а корректная модельная величина становилась `source_quantity_mismatch`. Исправление — порядок и форма: `_looks_like_column_header_strip` (≥2 непустых ячеек, ни одной ячейки-выражения) проверяется раньше подытога; настоящая строка итога (`АР!R109`, `АР!R111`, ещё 17) сохраняет `subtotal`. Русских префиксов не добавлено, пороги планировщика не менялись. Измерено и отвергнуто: правило отделения прозы модели по совпадению корней слов (`stage_b/b2_narration_rule_probe_827.py` → `stage_b/live_827/b2_narration_rule_probe_827.json`, 1185 живых запросов) отклоняло 54 настоящих запроса (36 с глаголом работы, 10 дословных строк) и не ловило саму прозу — не внедрено, остаток прозы (19 из 1185, 1,6 %) остаётся измеренным. Исправлена запись 826 о том, что фильтр «работает по `column_headers`»: на клиентском файле они были пустыми, утверждение было верным про код и неверным про рантайм. Tests: `tests/test_attachment_source_catalog_service.py` (2 → 5), `tests/test_lsr_candidate_query_service.py` (22 → 23, сквозной через `load_tabular_source_catalog`; на до-версии кода падает с `column_headers == ()`). Gate: `make verify` — 1766 collected, `make test-unit` — 687 passed / 2 skipped, полный `make test` — 1746 passed / 20 skipped (`stage_b/live_827/test_827.log`), карта регенерирована. Чем не является: живого замера § 2 на установленной 827 на момент записи нет, профессиональная правильность подбора не доказана, `ambiguous`/`note` остались своими классами, § 3…§ 6 открыты.

> **0.31.98 / 826:** объявленные моделью поисковые запросы читаются одним форматом в prompt, reader и адаптере, запросы адресуются строкам, а найдено/показано/отложено/выбрано измеряются раздельно (блок-лист `QWEN_BLOCKERS_AFTER_823_2026-09-29.md` § 2; `core/chat-evidence`, `proxy/services/chat_evidence_application_service.py`, `proxy/services/lsr_candidate_query_service.py`, `proxy/services/attachment_source_catalog_service.py`). Дефект измерен на живом прогоне 824 (`stage_b/b2_query_pollution_824.py` → `stage_b/live_824/b2_query_pollution_824.json`), а не разбором: из 1004 закешированных «запросов» 543 (54,08 %) запросами к норме не являются — 320 дамп строки таблицы (в том числе текст формулы `=АР!$G$111`), 190 без адреса, шифра и глагола работы, 33 проза модели; запросов с адресом строки — 20 (1,99 %); число найденных кандидатов насыщено на одном значении (min = median = max = 6 при `model_evidence_k = 6`, всего 6024), поэтому «найдено» и «показано модели» из одного top-k наружу неразличимы; 0 из 305 принятых строк имеют durable-связь нормы с запросом, который её принёс. Ядро: единственный читатель формата — `read_declared_query_list` (список русских префиксов заморожен и не дописывается; снимается только синтаксическая оболочка кавычек и `search_sources("…")`, смысл запроса не переписывается), сопровождающая проза отделяется и сохраняется с механической причиной (`declared_query_rejection_reason`: `empty_after_presentation_markers`, `table_rule_line`, `conversational_acknowledgement`, `shorter_than_a_query`, `heading_line`, `label_line_without_query`, `narrative_answer_line`) в `retrieval_trace.declared_query_rejections` (`les.declared-query-rejections.v1`, счётчики по причинам — `rejected_reason_counts`); адресация — заголовок группы `[строки: …]` показывает только адреса, написанные самой моделью, и `locator`, из которого собран системный кандидат, а совпадение запроса с дословным текстом строки (`row_literal_text` — один источник такого текста для автора кандидатов и для атрибуции; `attribution = literal_matches_row`) фиксируется лишь в трассировке, потому что назвать модели адрес строки — значит направить поиск кодом; `query_addresses` проходит через `model_rag_evidence_header_chars`, `select_model_rag_query_hits_for_budget` и `build_model_rag_evidence_groups`, то есть адрес стоит ровно столько символов, сколько отрендерился; системные запросы получают релевантный исходный текст с заголовком колонки у голой цифры («300» → «300 [Кол-во]») и теряют служебные колонки (итог/стоимость/сумма/цена/№/п/п) и указатели формул, а размеры, состав и условия остаются — фильтр работает по новым `CatalogRow.column_headers`, которых на боевом каталоге раньше не было; баланс групп держится round-robin'ом по строкам пакета плюс символьный бюджет `LES_LSR_SYSTEM_CANDIDATE_MAX_CHARS` (default 12000, зарегистрирован в `runtime_config_registry_service`, действует со следующего запроса без рестарта): переполнение бюджета откладывает кандидата по имени адреса (`deferred_by_char_budget`), а не объявляет отсутствие нормы; раздельный замер — `les.query-measurement.v1` на пакет (по каждому запросу: found / model_visible / not_visible / deferred_wholly / cards_omitted / chosen_rows, provenance и адреса) и `les.query-measurement-rollup.v1` на прогон, где пакеты остаются пакетами и суммарное found никогда не сравнивается с `model_visible` последнего вызова (явный флаг `compares_only_within_this_packet`); `finish_reason=length` на вызове запросов даёт один адресный оборот «дочитай хвост» (`declared_query_attempt_plan` + `declared_query_continuation_instruction`, уже объявленное не переиздается), а не ложное финальное решение. Ни один порог не поднят (`_STALL_THRESHOLD`, `_RUN_PACKET_BUDGET`, `_ROW_PACKET_MAX_ATTEMPTS`, `_HELD_PACKET_MAX_ATTEMPTS`, `STALL_TERMINAL_OCCURRENCES` без изменений), проверки не отключены; единственная новая граница — технический потолок `_MAX_SHEET_PASS_QUERY_CALLS = 3` на объявление запросов в пакете, и это не «увеличение числа попыток». Gate: `QUERY_PROVENANCE_BUILDERS` согласован с новым kwarg'ом `query_addresses` во всех трёх звеньях, `architecture_contract_gate` зелёный. Tests: `tests/test_model_rag_query_declaration.py` (17, новый файл, включён в `UNIT_TESTS`): формат, причины отклонения, адрес в заголовке и его символьная цена, потолок вызовов, раздельный замер одного пакета и накопление двух пакетов без «единой потери»; `tests/test_lsr_candidate_query_service.py` (15 → 22): служебные колонки и формулы вне запроса, заголовок колонки у цифры, round-robin, бюджет символов и `deferred_by_char_budget`; `tests/test_chat_evidence_application_service.py` (143 collected, +2): кандидат несёт адрес своей строки, пакет, отложенный бюджетом, остаётся видимым; `tests/test_attachment_source_catalog_service.py` (включён в `UNIT_TESTS`): `column_headers` доходит до потребителя. `make test-unit` — 683 passed / 2 skipped; `make verify` — 1762 collected, зелёный. Полный `make test` прогонялся дважды, и оба падения были сгенерированной картой, а не кодом: первый замер дал 1722 passed / 1 failed (`tests/test_code_runtime_map.py::test_runtime_map_is_conservative_and_deterministically_sorted` — счётчик строк двух сервисов и новый тест-файл ещё не учтены), карта регенерирована `tools/code_runtime_map.py`; после этого полный гейт на уже закоммиченном дереве дал 1741 passed / 1 failed, потому что новый тест-файл стал отслеживаться git только собственным коммитом и число файлов карты должно было стать 1027 вместо 1026. Карта регенерирована вторично (1027 файлов, 358 product_reachable / 657 test_or_tool_only, 338 маршрутов), `tests/test_code_runtime_map.py` — 11 passed. Третий замер на финальном дереве: полный `make test` — 1742 passed / 20 skipped зелёный (`stage_b/live_826/test_826_final.log`), `make verify` после регенерации — 1762 collected зелёный (`stage_b/live_826/verify_826_after_map_refresh.log`). Ни один тест не ослаблен и не пропущен. Docs: `docs/ADR-16-systematic-candidate-retrieval.md`, `docs/modules/rag-evidence-flow.md`, `docs/RELEASE_LEDGER.md`. Доказательством чего это НЕ является: профессиональной правильности подбора норм и полноты пакета по строкам это не доказывает; живой замер на установленной 826 не выполнен — без него § 2 не закрыт (AGENTS.md: не объявлять исправление готовым до installed user journey), целевой прогон обязан показать раздельные found/show/deferred/chosen по пакетам живого ВОР, баланс original/derived/model, доступность подходящей карточки вместе с исходными характеристиками строки и обработку хвоста при `finish_reason=length`. За пределами § 2 остаются и задокументированы: 497 строк `source_row_omitted` (ёмкость пакета), «норм выбрано 12» против «позиций рассчитано 237» и подтверждённая сумма 0,00 (§ 3, § 4).

> **0.31.97 / 825:** продолжение того же документа наследует его durable-состояние, а ledger предложений читается по цепочке исследований (блок-лист `QWEN_BLOCKERS_AFTER_823_2026-09-29.md` § 1; `core/workbook-research`, `proxy/services/workbook_research_job_service.py` и `core/chat-evidence`, `proxy/services/chat_evidence_application_service.py`). Дефект измерен живым прогоном 824 на клиентском ВОР, а не разбором: `Продолжи это же задание по тому же прикреплённом документу.` — другой вопрос, digest вопроса входит в идентичность исследования, поэтому продолжение открыло новый job поверх того же `attachment_id = read_5810d7bf494f` и начало очередь с первого листа — 282 уже решённых строки предложены модели заново, все 32 отложенные пере-предложены, 18 из 32 отложений потеряны, 417 закешированных запросов выпущены повторно, 463 evidence-записи переизвлечены, документа прирост на 4 строки за 42 минуты (`stage_b/b1_continuation_lineage_probe_825.py` → `stage_b/live_824/b1_lineage_824_continuation_final.json`, шесть из семи boundary-флагов FAIL). Тот же живой прогон закрыл первую половину § 1: 48 пакетов, `pause_kind='run_end'`, лист ЭОМ, 284 решённых адреса, 314 когда-либо предложены, `declared_without_a_single_offer=0` — восемь листов, которые 823 не предложил ни разу, на 824 предложены девять (не дошёл только ОВиК, 67 строк остались `never_offered` и не объявлены). Ядро: колонка `continues_job_id` (`_EXTRA_COLUMNS`, авто-миграция, `''` = первое исследование документа); `_inherit_document_progress` в `begin_or_resume` — область наследования это **документ** (`attachment_id` + `source_sha256`, как § 7/§ 9 для базы ценования: подменённый файл не наследует чужих решений, перегенерированная сессия не теряет свои), переносятся `accepted_rows`/`evidence`/`omitted`/`query_cache`/`deferrals`/`held_packet`/`remaining`, а guard-счётчики (`run_round_count`, `stall_count`, `held_attempts`) начинаются заново, потому что продолжение — новый прогон с новым бюджетом; отложения сохраняют смысл через пере-базирование `evidence_watermark = len(evidence)+len(query_cache)`, то есть держатся, пока именно это продолжение не соберёт evidence, которого у документа не было (§ 1 «не повторять один и тот же набор без новых данных/evidence»); событие `progress_inherited` (`les.progress-inherited.v1`) несёт `from_job`, статус/лист/модель/профиль родителя и продолжения, перенесённые числа, `guard_counters_reset` и `parent_elapsed_seconds` (время документа входит в ETA). `lineage_job_ids` + `list_events_with_lineage` — `packet_offer_counts` и `packet_attempt_seed` в цикле листов и в терминальном баре читаются по цепочке, каждое событие остаётся принадлежащим своему job; наружу — `retrieval_trace.workbook_research_job.continues_job_id`, чтобы ответ с 305 решениями на строке отличался от ответа, которому модель решила 305 строк в этой реплике. Gate: новый код `OFFER_LEDGER_READ_AT_JOB_SCOPE` держит три звена (loop кормит ledger-хелперы только `list_events_with_lineage`; `list_events_with_lineage` обязан вызывать `lineage_job_ids`, а тот — читать `continues_job_id`; `begin_or_resume` обязан вызывать `_inherit_document_progress`, а тот — писать `continues_job_id`) — три пары мутаций. Пороги не подняты (`_STALL_THRESHOLD`, `_ROW_PACKET_MAX_ATTEMPTS`, `_RUN_PACKET_BUDGET`, `STALL_TERMINAL_OCCURRENCES`), проверки не отключены; миграция — только добавление колонки. Tests: `tests/test_lsr_continuation_lineage_825.py` (11, включён в `UNIT_TESTS`): перенос решений/evidence/кэша, сохранение унаследованных отложений и их снятие новым evidence, ledger продолжения = история документа (третья реплика читает всю цепочку), неизменённый вопрос резюмирует тот же row и ничего не переносит, другой файл под тем же attachment начинает с нуля, replay цикла реальными хелперами доходит до листов, которые первый прогон не видел, наследование добавляет строку и не переписывает историю, проверка исходника цикла; `tests/test_architecture_contract_gate.py` (64, +7). Docs: `docs/ADR-16-systematic-candidate-retrieval.md`, `docs/RELEASE_LEDGER.md`. Доказательством чего это НЕ является: профессиональной правильности ЛСР по большому ВОР не доказывает. Живая проверка штатного продолжения на установленной 825 **выполнена** на конфигурации заказчика и разобранная в `stage_b/RELEASE_825.md`: кнопка «Продолжить» возобновляет ту же durable-строку (за оборот 621 с 316 → 401 принятых строк, остаток 99 → 14, курсор ЭОМ → ОВиК, `declared_without_a_single_offer=0`), а продолжение теми же мыслями другими словами открывает `wrj_52d9231a5560` с `continues_job_id = wrj_ffa319f8a7d9` и даёт 8 из 8 PASS в `stage_b/b1_continuation_lineage_probe_825.py` (0 пере-предложений решённого и отложенного, 14/14 отложений удержаны, 0 переизданных запросов, 0 переизвлечённых evidence, цифры события сверены с состоянием родителя) — при тех же восьми флагах живая граница 824 в том же отчёте даёт 7 FAIL; пользовательские данные не уменьшились (`documents` 12 → 12, digest загруженных файлов тот же, `jobs` 103 → 104). Этим прогоном § 1 закрыт в части продолжения, но не закрыт в части полноты: 14 строк АР остались `deferred_still_open`, 497 строк исходника `source_row_omitted` (ёмкость пакета — § 2), а тот же оборот выдал «норм выбрано 12» при «позиций рассчитано 237» и подтверждённую сумму 0,00 (§ 3, § 4). Открытым и задокументированным остаётся параллельный двойной прогон одного документа: `claim_or_join_sheet_pass` работает по `job_id`, эта правка его не меняет.

> **0.31.96 / 824:** планировщик исследования различает «пакет отложен» и «документ остановлен», а критерий прогресса стал тем же множеством, из которого пул пакетов вычитает решённое (блок-лист `QWEN_BLOCKERS_AFTER_823_2026-09-29.md` § 1; `core/workbook-research`, `proxy/services/workbook_research_job_service.py` и `core/chat-evidence`, `proxy/services/chat_evidence_application_service.py`). Измерено durable-следствием живых прогонов 823, а не догадкой: `stage_b/live_823/b1_plateau_trace_823.json` — `packets=31 accepted=101 remaining=295 ever_offered=108 remaining_never_offered=278`, гистограмма предложений `{0: 278, 13: 3, 14: 14}`, все 360 предложений принадлежат листу АР, восемь следующих листов не предложены модели ни разу, а плато из повторяющегося ГЛОБАЛЬНОГО remainder закрывало эти строки как «модель не решила после N предложений». Ядро хранилища: колонки `pause_kind` и `deferrals_json` (`_ensure_columns`, ничего не удаляется), `PACKET_DEFERRAL_PAUSE_KINDS = {stalled, held_retry_exhausted}`, пара `_pause_defers_one_packet` / `_pause_stops_the_run` c fail-closed правилом (останавливает прогон всё, что не является отложением одного пакета: операторская пауза, отмена, легаси-пауза без метки) и `run_should_stop`; `record_packet` при прогрессе возвращает отложенное паузой задание в `running`, а при отложении — пишет `pause_kind` и не трогает `should_cancel`, так что внешнему наблюдателю пауза по-прежнему выглядит паузой. `defer_locators` / `still_deferred` — отложение scoped к листу, переживает рестарт процесса, само снимается при новом evidence (`_evidence_watermark`, события `locators_deferred`/`deferrals_released`, схема `les.packet-deferral.v1`) и снимается оператором через `reopen_locators`; попытки re-delivered-пакета продолжает `packet_attempt_seed`, а не обнуляет. `finish_with_declared_gaps(…, offers_by_locator=…)` не объявляет строку с нулевым счётчиком предложений: она остаётся в `remaining`, задание — `paused` с `pause_kind='starved_scheduler'`, событие `gaps_declared` несёт `unoffered_open`/`unoffered_locators`. Ядро цикла: обе остановки листа теперь `research_run_stopped(research_job)` вместо `should_cancel`; `made_progress = bool(settled_after - settled_before)` считается по `settled_source_keys` — тому же множеству, которое вычитает пул (раньше guard мерил `structurally_complete_source_keys` и считал строку, честно решённую с предметным пробелом, нулевым прогрессом); `truncated_tail_locator` + `sheet_pass_keep_rows(drop_locator=…)` не сохраняют строку, обрезанную на `finish_reason=length` до колонок решения (технический пробел чтения ≠ «нет нормы», явный `MISSING` остаётся решением); `starved_locators` + `declared_gap_rows(offers_by_locator=…)` дают индивидуальную историю предложений и причину собственной строки; `sheet_pass_state` (`les.sheet-pass-states.v1`) разводит пять состояний § 1 — ещё не предложено модели / хвост не прочитан / решение с предметным пробелом / требуется уточнение / отложено на дополнительный поиск; `retrieval_trace.scheduler_gap` (`les.scheduler-gap.v1`) и расширенная pass-трасса (`parsed_rows → kept_rows → unread_tail_row → newly_decided → pool_remaining → durable_rows → stall_count → pause_kind → run_stops`) покрывают цепочку § 1. Ни один порог не поднят (`_STALL_THRESHOLD`, `_ROW_PACKET_MAX_ATTEMPTS`, `_RUN_PACKET_BUDGET`, `STALL_TERMINAL_OCCURRENCES`) — блок-лист прямо запрещает лечить это увеличением времени или попыток, и проверки не отключены. Docs: `docs/RELEASE_LEDGER.md`. Gate: нового кода `architecture_contract_gate` не добавлено — инвариант цикла («лист спрашивает про остановку прогона, а не про паузу») держится regression-тестом на исходный цикл (`inspect.getsource` + substring-проверки), как и принятые в репозитории петлевые проверки. Tests: `tests/test_lsr_scheduler_starvation_824.py` (16, включён в `UNIT_TESTS`): пауза guard'а не стопит прогон, оператор/отмена/легаси стопят, отложение переживает рестарт и ограничено листом, новое evidence снимает, никогда не предложенная строка не объявляется, обрезанный хвост не решение, пять состояний разведены, сценарий § 1 (неразрешимая позиция на первом листе + разрешимые следующие; без рестарта и с рестартом) доходит до решений на всех листах плюс легаси-контроль `["АПС"]` плюс проверка исходника цикла. Офлайн-доказательство без модели: `stage_b/b1_fix_check_824.py` → `stage_b/live_824/b1_fix_check_824.json` 9/9, включая «второй прогон того же файла не повторяет ни одного пакета» (12 предложений до и 12 после). Затронутые сюиты зелёные: job service 39, stall bound 14, packet integrity 11, CEA 141, `make verify` 1716 collected; `make test` дал единственное падение — устаревшая `docs/CODE_RUNTIME_MAP.md` (число строк двух сервисов), регенерирована. Доказательством чего это НЕ является: профессиональной правильности ЛСР по большому ВОР не доказывает; живой прогон большого документа на 824 на момент записи правки не выполнен — без него § 1 не закрыт, потому что положительный gate требует, чтобы в живом прогоне не предложенные модели строки остались открытыми.

> **0.31.95 / 823:** непрерывность ценовой базы перенесена с границы исследования на документ, а применённая база стала читаемой в ответе оператору (задача 2026-09-28 § 4, § 7, § 9, § 10, § 11 № 1). Найдено живым прогоном 822, а не разбором: `B0_camenka` записал `sankt-peterburg_3kv2026` в событие ревизии 1 (`wrj_3d1896b01aea…` seq 32, read-only SQL по `C:\Users\MVBul\AppData\Local\LES\data\les_meta_qwen.db`), а проходы 2..5 того же файла открыли новое исследование `wrj_93f74345fa69…` поверх того же `attachment_id = read_2f0cbe1d6afb` — идентичность исследования включает `question_sha256`, — и `workbook_document_price_basis`, накормленный событиями только текущего `job_id`, ответил «no_book» (`stage_b/live_822/basis_continuation/B0_camenka_basis_continuation.json`). Ядро: `document_packaging_events(*, attachment_id, source_sha256, limit)` (`core/workbook-research`, `proxy/services/workbook_research_job_service.py`) — события `workbook_packaged` всех исследований одного attachment, упорядоченные по `created_at` события (не по `sequence`, который обнуляется в каждом job; совпадающие секунды — по `rowid` исследования), несовпадающий `source_sha256` отсекается (§ 9: подменённый файл не наследует чужую базу), пустой digest старых записей — нет (иначе перегенерированная после рестарта сессия потеряла бы свой документ); `document_priced_basis(...)` (`core/chat-evidence`, `proxy/services/chat_evidence_application_service.py`) — одно правило для обоих маршрутов поверх того же `workbook_document_price_basis`, сбой хранилища логируется и оставляет вопрос открытым. Code-owned маршрут читает документную историю (`document_basis_events`) с откатом на события своего job, только когда документ ещё не посчитан; модельный `model_packaging_document_basis` при пустой проекции своего job падает в `document_priced_basis`. Родитель ревизии — из ответа packagera (`artifact["parent_revision_id"]`), иначе durable-цепочка рвётся на первом проходе нового исследования (822, ревизия 2). § 7: `_lsr_basis_suffix(match, note, book)` в `proxy/services/lsr_result_readiness_service.py` печатает «Книга цен: <идентификатор>», а `basis_visible = bool(basis_note or basis_book)` заменил белый список `{mismatch, unspecified, no_book}` — раньше карточка молчала о привязанной книге, тогда как отданный XLSX печатал её в шапке (§ 10). Docs: `docs/ADR-16-systematic-candidate-retrieval.md`, `docs/RELEASE_LEDGER.md`. Gate: новые коды `DOCUMENT_BASIS_READ_AT_JOB_SCOPE` (каждый вызов читателя базы кормится документной историей; модельный читатель обязан вызывать `document_priced_basis`; `document_packaging_events` действительно собирает исследования по attachment) и `APPLIED_BASIS_NOT_NAMED` (нельзя показывать только испорченную базу и нельзя прятать идентификатор книги) — по парам мутаций на каждом звене. Второй дефект той же сборки найден живым прогоном 822 в тех же ячейках: отказ выбирать базу объяснялся единственной фразой «локально не найдена», которая была неправдой про установленный каталог — `B3_bap_pdf` (задача называет Москву III/2026, адрес объекта в том же PDF — Санкт-Петербург, книги обеих баз стоят локально) и `B4_eom_pdf` (назван только субъект, периода нет; подходят `sankt-peterburg_2kv2026` и `sankt-peterburg_3kv2026`) напечатали отсутствие книги, которого не было (`stage_b/live_822/basis_refusals/basis_refusals.md`, скрипт `stage_b/basis_refusal_proof.py` — офлайн-разбор записанных входов теми же функциями `explicit_estimate_pricebook` и `summarize_lsr_price_basis`). Механика: вывод базы называет причину отказа (`contradiction`, `unnamed_period`, `unnamed_subject`, `no_matching_book`, `ambiguous_catalog`, `no_local_books`) и поля `contradicting_regions`, `contradicting_quarters`, `refusal`, `matching_books`, `requested_region_origin`; объяснитель обязан разобрать причину **до** ветки «локально не найдена» и назвать недостающую половину базы со списком подходящих книг; `sovushka/pages/chat.py::_price_basis_contradiction_lines` приписывает противоречие явным источникам, а не очередной реплике, и карточка не печатает «Регион в запросе не назван» над списком двух названных регионов (§ 10). Негативный контроль сохранён: `B7_fourth_quarter` (IV/2026 локально нет) печатает «локально не найдена» по-прежнему (§ 7 требует показывать запрошенное и применённое, а не выдумывать базу). Третий код гейта — `CONTRADICTED_BASIS_ANNOUNCED_ABSENT`: три звена одного шва (вывод пишет поля отказа, объяснитель их принимает и проверяет причину до константы «локально не найдена», каждый вызов передаёт все три аргумента). Tests: `tests/test_lsr_price_basis_continuation.py` (25, +6), `tests/test_architecture_contract_gate.py` (57, +13), `tests/test_lsr_result_readiness_service.py` (21, +3), `tests/test_lsr_price_basis_explicit.py` (19, +4: отказ противоречия называет оба субъекта, незаконченная половина базы называет подходящие книги, честно отсутствующий период остаётся отсутствующим, отказ донесён адаптером до формулировки оператору), `tests/test_sovushka_chat.py` (124, +1: карточка показывает отказ как отказ). Числа расчёта, retrieval, индексы, corpus не изменены; миграций нет. Доказательством чего это НЕ является: профессиональной правильности ЛСР по большому ВОР не доказывает; живая проверка наследования через границу исследования выполняется на 823; разбор отказов на `stage_b/live_822/basis_refusals/` — офлайн-прогон текущих функций на записанных входах 822, живым доказательством служит тот же разбор на матрице 823 (`stage_b/live_823/basis_refusals/`), и на момент записи правки он не выполнен; и остаётся открытым живой дефект — продолжение заново решает подбор норм (`ВОР!R4`: `ГЭСН14-03-001-01 EXACT` → `ГЭСНм20-01-046-12 ANALOGUE_CANDIDATE`, пробелы цены 15 → 62), эта правка меняет только читаемую базу, а не повторное решение.

> **0.31.94 / 822:** шов непрерывности ценовой базы 821 закрыт на втором маршруте пакетирования, а его провенанс стал неизменным (задача 2026-09-28 § 4, § 5, § 9, § 10, § 11 № 9). Найдено разбором выпущенного 821, а не живой ошибкой — это надо читать именно так: живого прогона на 821 не было вообще (матрица 821 оборвалась за 1 с на отсутствующем `openpyxl`, `stage_b/live_821/matrix_35b/driver_index.json`), а § 5 требует перечислить *все* поддерживаемые маршруты. (1) `core/chat-evidence` — `proxy/services/chat_evidence_application_service.py`: при ACTIVE каноническом маршруте (обычный чат: GUI-привязка ответа авторитетна) модель вправе сама вызвать `build_lsr_workbook`, и этот сайт `workbook_tool_executor` отдавал файл, не записав `workbook_packaged` → у документа, впервые посчитанного здесь, наследовать было нечего, и следующая реплика вернула бы дефект 820 поверх посчитанного файла. Три новых читателя/писателя того же durable-шва: `workbook_research_job_for_document` (только чтение, ключ — `attachment_id` + sha256 исходника, поэтому перегенерированная после рестарта сессия находит свой документ, а подменённый под тем же attachment файл не наследует чужую базу; реплика модели не заводит чужой checkpoint), `model_packaging_document_basis` (база из той же проекции `document.price_basis`, что у карточки и repack — разбор через общий `document_price_basis_arguments`, а не свой парсер) и `model_packaging_record_arguments` (событие с тем родителем, который packager реально использовал, и `draft` по состоянию задания: посчитанная ревизия незавершённого задания остаётся черновиком). Ничего не доставлено или нет durable-задания — ничего не пишется; сбой хранилища виден в логе и не ломает ответ. (2) Провенанс: `workbook_document_price_basis` и `describe_packaging_document` (`proxy/services/packaging_recovery_service.py`) возвращают в `revision_id` ревизию, в которой книга была *выбрана*, а не самую свежую, в которой её пересчитали; книга, субъект и период по-прежнему берутся из последней посчитанной ревизии, сдвигается провенанс только вместе с базой. Запись входит в аргументы вызова packager, аргументы — в идентичность технического вызова, поэтому растущий номер превратил бы повтор законченного задания в новый запрос и вторую копию того же документа; карточка готовности, repack без модели и продолжение в чате теперь называют для одного документа одну ревизию. Docs: `docs/ADR-16-systematic-candidate-retrieval.md` (§ «Ценовая база принадлежит документу, а не реплике», § «Архитектурный gate»), `docs/RELEASE_LEDGER.md`. Gate: новый код `PACKAGING_ROUTE_NOT_DURABLE` — число `record_packaging` обязано покрывать все маршруты, отдающие packager файлом, модельный маршрут обязан строить событие через `model_packaging_record_arguments`, а разбор базы — через общий keeper; проверен на трёх парах мутаций. Tests: `tests/test_lsr_price_basis_continuation.py` (19, +7: неизменность аргументов при повторе, сдвиг провенанса только вместе с базой, совпадение карточки и продолжения, наследование и запись модельного маршрута, сквозной шов «модельное событие → читатель → args», отказ наследовать подменённый файл), `tests/test_architecture_contract_gate.py` (+3 пары). Числа расчёта, retrieval, индексы и corpus не изменены; миграций нет — правки читают и пишут те же события. Доказательством чего это НЕ является: профессиональной правильности ЛСР по большому ВОР это не доказывает, и живая матрица на 822 на момент правки не проведена.

> **0.31.93 / 821:** ценовая база принадлежит документу, а не тексту очередной реплики (задача 2026-09-28 § 4, § 7, § 11 № 1). Живой дефект сборки 820: у «ВОР — Общая по Каменке» ревизия 1 была посчитана в `sankt-peterburg_3kv2026` и напечатала это в файле, а ревизии 2..6 того же `artifact_id` после «Продолжи это же задание по тому же прикреплённому документу.» напечатали «Ценовая база не задана явно, поэтому книга не выбрана» и не подставили ни одной цены по книге; `GET /api/workbook-research/{job}` при этом возвращал `price_basis = null` (`stage_b/live_820/basis_continuation/basis_continuation.json`, `stage_b/live_820/matrix_35b/stage_summary.md`). Цепочка ревизий и идентичность были корректны (один `artifact_id`, `parent_revision_id` 1→6, `document.state = ready`, загрузка 200 с совпадающим sha256) — то есть § 4 выполнялся, а § 7 нет, потому что база каждый раз выводилась из `args["question"]` и нигде не сохранялась. Теперь: `record_packaging` (`proxy/services/workbook_research_job_service.py`, `_packaged_price_basis`) пишет базу в payload того же события `workbook_packaged`, что и lineage → она переживает рестарт; `describe_packaging_document`/`get()` отдают её как `document.price_basis` и `price_basis`; `workbook_document_price_basis` + `workbook_packaging_args(document_price_basis=…)` несут её в новый аргумент только `build_lsr_workbook` (контракт ВОР с `additionalProperties: false` его не принимает); `POST /api/chat/repack-lsr` (`proxy/routers/chat.py`, `document_price_basis_arguments`) пересобирает файл без модели с той же базой; `explicit_estimate_pricebook(document_basis=…)` помечает `origin = «наследие документа (ревизия …)»`, `summarize_lsr_price_basis` — «Ценовая база этого документа сохранена… текущая реплика её не называла, поэтому она не обнулена», а шапка XLSX и `tool_call_meta.price_basis_inherited_from` несут её наружу. Явное указание в новой реплике побеждает сохранённое, частичное — наследует остальное; отсутствующая книга не подменяется ближайшей, а повторяет тот же вопрос с перечнем доступных; непосчитанная ревизия наследовать не может. GUI показывает продолженную базу спокойной строкой `lsr_price_basis_prompt.confirmed_line` (§ 3 — новое поведение видимо с effective value и источником), потому что пузырик выбора при `match = exact` правильно молчит. Попутно исправлены два собственных дефекта переноса: repack читал `list_events` с фильтром по `event_type` и лишал `workbook_packaging_lineage` событий смены решений; `job` не был инициализирован при пустом `job_id`. Числа расчёта, индексы, retrieval, corpus не изменены; миграций нет, старые события без базы читаются как «наследовать нечего». Docs: `docs/ADR-16-systematic-candidate-retrieval.md` (§ «Ценовая база принадлежит документу, а не реплике», приёмка № 6), `skills/smeta/SKILL.md` (раздел «Цены, коэффициенты и нули»), `docs/RELEASE_LEDGER.md`. Gate: новый код `DOCUMENT_BASIS_NOT_CARRIED` (три звена: событие → аргументы упаковки → пересборка без модели), проверен на трёх парах мутаций. Tests: `tests/test_lsr_price_basis_continuation.py` (12, включая сквозной шов «событие → читатель → args» с валидацией по контрактам обоих packagerов), `test_record_packaging_stores_the_basis_that_revision_was_priced_in`, `test_record_packaging_does_not_invent_a_basis_from_an_unpriced_revision`, `test_price_basis_prompt_shows_a_continued_basis_with_its_source`. Это механика непрерывности выбора, а не доказательство профессиональной правильности ЛСР: на том же живом прогоне остаются открытыми `estimate_complete = false`, `confirmed_amount = 0,00`, 28 пробелов покрытия и 593 записи `omitted` — последние являются карточки-кандидаты, не попавшие в токенный бюджет (`Q<запрос>.H<карточка>`), а не потерянные строки исходника: строки каталога там приняты 120/120.

> **0.31.92 / 820:** светлый рестарт не выбирает заново, в каком хранилище живут документы (задача 2026-09-28 § 4, § 9). Точка входа: `installers/windows/start-light.ps1`. Цепочка одна и та же на старте и на остановке: `LES_WINDOWS_STATE_ROOT` → `LES_ENV_PATH` (`.env` state-корня) → `LES_EMBED_PROFILE` → `backend/rag_config.py:rag_meta_db_path` → `data/les_meta.db` (legacy) либо `data/les_meta_qwen.db` (клиентский профиль). `stop-light.ps1` и `state.ps1` уже выводили корень из `%LOCALAPPDATA%\LES`, а `start-light.ps1` — только когда переменная пришла из окружения запускающего; рестарт без неё открывал чужое хранилище, и наружу это выглядит как отказ приёмки: 404 на существующий job, 409 «Версия профиля не найдена» на каждый оборот обычным чатом, пустой список документов. Так сгорел первый прогон матрицы 819: `B0_camenka` — 22 отказа из 22 проходов за 51.2 с при статусе `finished` и 0 артефактов (`stage_b/live_819/matrix_35b/quarantined_wrong_store/`). Правило: start выводит `%LOCALAPPDATA%\LES`, когда переменная не задана и каталог существует; явный `LES_WINDOWS_STATE_ROOT` побеждает (на нём стоят smoke-тесты), desktop задаёт его сам. Живой драйвер добавил preflight `store_scope()` (`stage_b/run_matrix_819_35b.py`) — известный клиентский job до очереди и перед каждой ячейкой, STOP матрицы, если приложение её не видит. Docs: `docs/ADR-16-systematic-candidate-retrieval.md` (§ «Хранилище документов не выбирается заново при рестарте»), `docs/RELEASE_LEDGER.md`. Tests: `test_windows_light_start_and_stop_resolve_one_state_root` (общий вывод корня, порядок относительно `LES_ENV_PATH`, тот же корень в `stop-light.ps1`). Формулировки гейта 819 (`proxy/services/rim_lsr_trace_service.py`, `tools/architecture_contract_gate.py`, ADR-16) приведены к доказанному: guard закрывает путь, по которому позиция в «л» считалась строкой книги в «кг», но на реальной выборке карточки с книгой не расходятся (0 из 135 пар) и guard не сдвигает ни одной суммы; обе ветки показаны на установленной сборке (`stage_b/live_819/installed/book_unit_latest.json`). Числа расчёта не изменены, миграций нет, индексы и retrieval не затронуты.

> **0.31.91 / 819:** строка ценовой книги — это цена за единицу, которую называет сама строка. `smeta/lsr-trace` — `proxy/services/rim_lsr_trace_service.py`: `PriceBook.lookup` (`proxy/services/fgis_price_service.py`) сопоставляет ресурс по одному нормализованному шифру, и ни один из двух движков ЛСР не спрашивал единицу найденной строки, поэтому позиция, в которой ресурс назван в «л», могла быть посчитана строкой книги в «кг», а позиция выглядела посчитанной по выбранной базе. Новая функция `book_price_unit_conflict` (канонизация единиц: «п.м» = «м», «м3» ≠ «100 м3») — единственное правило, вызываемое и `build_position_trace`, и `smeta/lsr-assembly` — `proxy/services/lsr_assembly_service.py` (`_rejected_book_unit`, `_resource_price`), чтобы § 10 не дал два набора сумм на один документ. При расхождении строка отвергается: `source`/`basis`/`action` = `book_unit_conflict` (`BOOK_UNIT_CONFLICT_ACTION`), цены нет (`columns["10"]` не пишется), `meta.price_book_unit` называет единицу книги, флаг и `completeness_reasons` дают ровно одну причину `price_missing:<шифр>`, `amount_status` ≠ `complete`, `full_amount` = `None`; ставка карточки нормы при этом остаётся под `card_price_without_basis`. Операторские поверхности — `lsr_workbook_adapter_service.py` (`collect_lsr_price_gaps`) и `lsr_result_readiness_service.py` — спрашивают про единицу, а не про несуществующую цену; пустая единица с любой стороны конфликтом не считается (§ 7: конфликт показывают, а не изобретают). На живом срезе правило не двигает ничего: 186 ресурсов → 135 строк книги, 131 совпадение, 0 расхождений, 4 строки без единицы (`stage_b/live_818/book_unit_gap.json`), 17 позиций / 168 посчитанных из книги ресурсов — 0 конфликтов, 0 сдвинутых сумм (`stage_b/live_819/book_unit_guard_effect.json`). Числа текущих документов не изменены, миграций нет, `runtime-config`, индексы и retrieval не затронуты. Docs: `docs/ADR-16-systematic-candidate-retrieval.md` (§ Цена обязана иметь владельца, приёмка № 11), `docs/SMETA_MECHANICS.md` (порядок разрешения цены), `docs/RELEASE_LEDGER.md`. Gate: новый код `BOOK_PRICE_UNIT_UNCHECKED` в `tools/architecture_contract_gate.py` — читает ли каждый сайт `.lookup(` через правило и названа ли дыра в двух операторских модулях; проверен на двух мутациях. Tests: `test_a_book_row_that_prices_the_cipher_in_another_unit_prices_nothing`, `test_the_question_asks_about_the_unit_the_position_counts_in`, `test_the_same_unit_or_a_row_without_a_unit_prices_exactly_as_before` (негативный контроль), `test_a_norm_factor_unit_next_to_its_plain_form_is_a_question_not_a_product`, `test_a_rejected_book_row_does_not_delete_the_money_the_card_already_had`, `test_both_lsr_engines_refuse_the_same_book_row` + четыре пробы гейта. Механическое закрытие латентной дыры: профессиональная правильность ЛСР на живых документах этим не доказывается.

> **0.31.89 / 817:** расчёт обязан дойти до оператора, а ставка начислений — иметь владельца. Первое: на живом прогоне 816 `result_readiness.dimensions.prices.basis` у всех packaged-проходов оставался `{}`, поэтому пузырёк «Выберите регион и уровень цен» не открывался, даже когда адаптер нашёл непустую базу. Виновник — два переносчика: `proxy/services/workbook_tool_service.py` не клал `price_basis`/`price_gaps` в payload, а `safe_workbook_history_projection` (`proxy/services/chat_evidence_application_service.py`, он же tool result для модели) не переносил ни одного из `price_basis`/`price_gaps`/`norm_conflicts`, и `harvest_workbook_tool_result` не возвращал `norm_conflicts`; два production-сайта читали пустоту. Переносчики теперь общие и ограничены по объёму (`_bounded_history_value`: 40 элементов, 400/2000 знаков), итоги пробелов считаются по полному `missing`. Второе: ставка НР/СП, списанная с самой карточки нормы, перестала выглядеть принятой — `build_position_trace` (`rim_lsr_trace_service.py`) пишет `summary.nr_sp_ownership` (`nr_source`/`sp_source` ∈ `explicit|catalog|norm_card`) и метку `nr_sp_without_basis`/`nr_sp_unresolved`, а `lsr_workbook_adapter_service.py` добавляет по одному пробелу на позицию (`_nr_sp_gap`, ресурс «НР и СП (<шифр>)»: 300 позиций одного шифра — один вопрос). Деньги не меняются, `full_amount` остаётся `None`; закрытие — только нормативным основанием (812/пр, 774/пр) или явным выбором ставки. Попутно readiness-карта больше не показывает оператору токен `row:<локатор>:<статус>` и не велит «закройте нормы» там, где `norms` уже полные (`_unbound_rows`/`_ROW_STATUS_LABEL`), и эталон ЛСР пересобран по компонентам (ГЭСН12-01-034-02 @ 0,61 → 11 998,07). `runtime-config`, индексы и retrieval не затронуты; `/assemble` (легаси) для той же позиции даёт 11 896,35 — расхождение двух движков зафиксировано как открытый риск, а не исправлено молча. Docs: `docs/ADR-16-systematic-candidate-retrieval.md` (§ 7), `CODE_MAP.md`. Gates: новые коды `BASIS_QUESTIONS_NOT_CARRIED` и `ACCRUAL_LABEL_NOT_ASKED` в `tools/architecture_contract_gate.py`. Tests: `test_packaging_publishes_the_basis_and_conflicts_the_operator_must_answer`, `test_projected_basis_and_conflicts_open_the_chat_readiness_block`, `test_accrual_rate_read_off_the_norm_card_keeps_the_position_draft`, `test_owned_resource_prices_do_not_close_a_position_without_an_accrual_owner`, `test_an_explicit_accrual_choice_closes_the_same_document`, `test_a_volume_in_pieces_is_not_rescaled_into_the_norm_unit` + пробы гейта. Механическая коррекция переносчика, владения ставкой и контрольных входов: профессиональная правильность ЛСР на живых документах этим не доказывается.

> **0.31.88 / 816:** продолжение документа остаётся тем же документом. На живом прогоне 815 (ВОР 318 строк, путь «готовая ВОР → ЛСР») пакет первого прохода был опубликован до появления research job, поэтому событие `workbook_packaged` не записалось и второй проход начал **второй** artifact (`art_839329a1` rev 1 → `art_85ffba25` rev 1) вместо revision 2 того же `artifact_id`. `smeta/workbook-tools` — `proxy/services/workbook_tool_service.py` теперь сам разрешает родителя через `_packaging_parent(...)`: явный `parent_revision_id` (explicit) → новейшая завершённая revision этого же chat-сеанса по `workflow_checkpoints.last_completed_revision(session_id, attachment_id, tool_name)` (session_lineage) → первая revision (first_revision); отсутствующий в artifact-store родитель и сбой хранилица не блокируют доставку (parent_missing_from_store / checkpoint_store_unavailable). Родитель не приходит от модели и не выводится из имени файла; источник решения виден в `tool_calls[].parent_revision_source`. Область поиска — `session_id`, поэтому гарантия 812 (новый чат не подхватывает чужую сборку) сохранена и закреплена тестом. `runtime-config`, индексы, retrieval и ценовая база не затронуты. Docs: `docs/ADR-16-systematic-candidate-retrieval.md`, `CODE_MAP.md`. Gate: новый код `DOCUMENT_LINEAGE_UNOWNED` в `tools/architecture_contract_gate.py`. Tests: `test_continuation_without_explicit_parent_stays_one_document`, `test_another_chat_session_packages_its_own_document` (`tests/test_workbook_tool_service.py`), `test_rejects_artifact_revision_built_from_model_supplied_parent`, `test_allows_code_resolved_document_lineage` (`tests/test_architecture_contract_gate.py`). Механическая коррекция идентичности документа: она не доказывает профессиональную правильность ЛСР на живых документах.

> **0.31.87 / 815:** ADR-16 переносит гарантию полноты кандидатов на сметном пути в код, не трогая право модели решать. `smeta/retrieval-candidates` — новый `proxy/services/lsr_candidate_query_service.py`: на sheet-pass пакета строк он собирает на каждую строку по две доскиловно обоснованные группы запроса — `original` (дословный исходный текст строки) и `derived` (тот же дословный текст плюс только явно представленные в исходнике атрибуты — заголовок раздела листа и написанный в ячейке шифр); запрос с токеном, которого нет в его собственных строках, отбрасывается и остаётся видимым в трассировке как `dropped_ungrounded`. `core/chat-evidence` — `proxy/services/chat_evidence_application_service.py`: системные запросы идут в тот же read-only `search_sources`, в ту же contract-versioned named `dense + bm25_sparse` коллекцию, native RRF и общий rerank; каждая группа помечена `query_provenance ∈ original|derived|model`; в сравнительном baseline `B0_DIRECT` и на обычном пользовательском dataset/chat-прогоне системные запросы не исполняются вовсе. `runtime-config` — два видимых в Совушке фактора категории `smeta` без необходимости рестарта: `LES_LSR_SYSTEM_CANDIDATE_QUERIES` (default `on`) и `LES_LSR_SYSTEM_CANDIDATE_MAX` (default `24`). За моделью остаются определение операций, применимость норм и соответствие ресурсов, её собственные запросы (заголовки которых byte-identical прежнему) и право отклонить всех предложенных кандидатов; код не выбирает норму, не ранжирует по «правильности» и не выводит из текста ничего, чего в тексте нет. Docs: `docs/ADR-16-systematic-candidate-retrieval.md`, `modules/chat-profiles.md`, `modules/rag-evidence-flow.md`, `CODE_MAP.md`. Tests: `tests/test_lsr_candidate_query_service.py` (11) плюс 7 wiring-тестов `test_adr16_*` в `tests/test_chat_evidence_application_service.py`. Изолированные unit-тесты и проверка wiring не являются доказательством профессиональной правильности подбора норм на живых документах: установленная приёмка этого пути ещё не проводилась.

> **0.31.86 / 814:** `smeta/bor` scans every tabular XLSX sheet, keeps physical source coordinates and exposes formulas without cached quantities as blockers (`spec_to_bor_service`, `workbook_tool_service`, `bor_service`); `rag/answer-render` restores a completed file after repainting session history (`sovushka/pages/chat.py`); LSR readiness keeps unspecified/missing price basis and a catalog with materials but no authored work layer incomplete (`lsr_result_readiness_service`); RIM audit orders immutable revisions by insertion sequence rather than equal timestamps plus UUID (`rim_session.py`). Module docs: `ALGO-spec-to-bor.md`, `modules/rag-evidence-flow.md`, `modules/sovushka-uikit.md`, `modules/rim-dialog-session.md`. These are mechanical corrections, not evidence of model-owned norm coverage on arbitrary input.

> **0.31.76 / 782 stage F:** the six 781 defects closed on existing seams. Merge/validator key on decision identity (operation_id, else locator+role+content sha); trace amounts, positions and bindings carry op_key so per-operation sums replace per-locator overwrite; norms counters accept only real ciphers; summarize_lsr_price_basis binds explicit requested_region (with origin) + year + quarter (incl. file-name tokens) + book id, lists contradictions instead of resolving them, and honors the operator _price_basis confirmation; apply_confirmed_data is addressed by operation_id/row_role (confirm_ambiguous guards unaddressed multi-row patches) and double_count_conflicts makes the R6 equipment+material pattern visible; replace_accepted_rows enforces base_revision (router 409) and packet_attempt_seed restores attempt numbering from durable events. Code: chat_evidence_application_service.py, lsr_source_coverage_service.py, rim_lsr_trace_service.py, lsr_result_readiness_service.py, lsr_workbook_adapter_service.py, workbook_research_job_service.py, routers/chat.py; tests: +22 (test_finalization_defects_782.py).

> **0.31.75 / 781 stage D:** the price basis became an explicit, visible part of
> the LSR result without a new subsystem: `summarize_lsr_price_basis` binds the
> requested basis (tool arg `pricebook`, source-text price level, period named in
> the question — digits or roman `III квартала 2026`) against the actually resolved
> book's region/quarter and returns `exact|mismatch|unspecified|no_book` with a
> confirmation-procedure note; the result carries `price_basis`, the XLSX header
> prints the note (warning fill on mismatch) and `lsr_result_readiness` refuses to
> mark prices complete while a mismatch is unconfirmed. `collect_lsr_price_gaps`
> now names per concrete position: resource+code, quantity with unit, required
> source, the checked basis (book region/quarter) and the dependent position
> totals. Refill keeps using the durable confirmed-data path — recalculation at
> trace time with no norm re-search. Code: `lsr_workbook_adapter_service.py`,
> `rim_trace_xlsx_service.py`, `lsr_result_readiness_service.py`,
> `workbook_tool_service.py` (`pricebook` argument), `chat_evidence_application_service.py`,
> `routers/chat.py`; tests: +6 (`test_workbook_tool_service`,
> `test_lsr_result_readiness_service`, `test_rim_trace_xlsx`).

> **0.31.74 / 780 stage G:** norm-search trace attributes the §7 control cases
> without a new audit subsystem: the evidence namespace is scoped per packet
> attempt (`row_packet_id(...)+":a<n>"`) so one alias `Qx.Hy` can no longer resolve
> to several cards across retries; every visible chunk carries `model_query_text`;
> budget-dropped cards are named per pass (`omitted_cards`: ref/query/card) with
> deferred `leftover_query_texts`; `search_cache` events carry sheet/packet/locators/
> queries context; accepted rows store `_evidence_check` — a structural citation
> check (cited card vs authored norm_code, unresolved refs) that never rewrites the
> model's decision. Code: `chat_evidence_application_service.py`,
> `workbook_research_job_service.py`; tests: +4 (`test_chat_evidence_application_service`,
> `test_workbook_research_job_service`).

> **0.31.73 / 779 stage V:** every LSR row binding carries split readiness
> (`source_accounted / operation_defined / norm_selected / applicability_substantiated /
> volume_verified / position_calculated / prices_provided`) — `bound` alone never means
> "ready" or "priced". Model may author `row_role=header`: headings/notes/subtotals are
> accounted as `structure_accounted` without any mounting norm demand. Summary exposes
> per-kind counts and the confirmed/preliminary amount split (NEEDS_RESEARCH analogues
> and unpriced supply lines stay preliminary, model status never raised); the review
> sheet and the chat readiness notice show them. Code: `rim_lsr_trace_service.py`,
> `lsr_source_coverage_service.py`, `lsr_result_readiness_service.py`,
> `rim_trace_xlsx_service.py`; tests: +8 (`test_rim_lsr_trace_service`,
> `test_lsr_result_readiness_service`).

> **0.31.72 / 778 stage B:** the workbook adapter stamps raw source cells/numbers
> (`_catalog_source_*`) from the server-owned attachment catalog; the calculator
> refuses an authored unit/quantity change that has no cited conversion basis —
> the row stays visible as `unconfirmed_quantity` with field/source/authored/needed
> data and produces no position (absent from every sum); materials without a
> quantity no longer silently become qty=1. Code: `lsr_workbook_adapter_service.py`,
> `rim_lsr_trace_service.py`; tests: `test_rim_lsr_trace_service.py` (+6),
> `test_chat_evidence_application_service` adapter contract. Live СКС replay:
> R47/R48/R49/R50 (30/210/18/162 м→шт) and R12 (990→12) left the confirmed sums.

> **0.31.71 / 777 stage A:** durable workbook decisions carry a stable
> `operation_id` (uuid; legacy rows get a deterministic `op_leg_` content mapping,
> never merged by title). Explicit refinements append to
> `workbook_research_revisions` with origin + `base_revision` stale-guard;
> `record_packet` keeps several distinct operations on one `(locator, role)` and
> dedupes identical re-delivery. Code: `workbook_research_job_service.py`;
> tests: `test_workbook_research_job_service.py` (12). Live-job migration
> rehearsed on a backup copy without loss.

> **0.31.70 / 776:** durable job merge and source coverage are per
> `(locator, role)`; named `NEEDS_RESEARCH` goes to exact lookup without
> becoming `priced_final`; FGIS overlay fills missing calc cards.
> Code: `workbook_research_job_service.py`, `lsr_source_coverage_service.py`,
> `rim_lsr_trace_service.py`, `gesn_service.py`. Tests: job, coverage, RIM,
> gesn overlay. Live installer acceptance still pending.

> Build 775 candidate: decorative Markdown divider width no longer drops tables;
> per-pass parsed_rows/kept_rows/row_errors expose acceptance losses.
> Module: core/chat-evidence; doc: [chat-profiles](modules/chat-profiles.md).
> Live customer acceptance remains pending.


> **0.31.68 / 774 candidate:** material+work on the same locator are distinct
> decisions; markdown title pipes no longer drop the row. Code:
> `chat_evidence_application_service.py`; tests: chat-evidence + packet integrity;
> doc: [chat-profiles](modules/chat-profiles.md). Live full-SKS hand-off pending.
>
> **0.31.67 / 773 candidate:** model-result reader preserves malformed numeric
> cells without dropping the table; RIM calculation exposes a per-row numeric gap.
> Code: `chat_evidence_application_service.py`, `rim_lsr_trace_service.py`;
> tests: corresponding service suites; doc: [chat-profiles](modules/chat-profiles.md).
>
> **0.31.66 / 772 source candidate:** Settings only probes FreeToken cache;
> chat cache preparation acquires the generation permit and retains it until
> the worker finishes even after cancellation. Module doc: [chat-profiles](modules/chat-profiles.md).
> Live comparative acceptance and installed candidate acceptance remain pending.
>
> **0.31.65 / 771 candidate:** ACTIVE chat rebuilds FreeToken KV once at turn
> start when 35B is still on a legacy <16384 window; Settings uses the same
> lift so GET cannot shrink the factory 35000 envelope. Packet loops do not
> rebuild. Code: `freetoken_cache_profile_service.py`,
> `chat_evidence_application_service.py`, `settings.py`. Tests:
> `test_freetoken_cache_profile_service.py`. Live SKS/B0_DIRECT pending.

> **0.31.64 / 770 candidate:** resource parent must resolve to a model-authored
> `work` decision; self-linked materials and links to other materials no longer
> close packets. All incomplete locators survive the 80-item display limit.
> `lsr_result_readiness_service.py` keeps saved but incomplete rows resumable.
> Estimator instruction explains specification-to-work derivation without
> assigning a norm per product. Code: `lsr_source_coverage_service.py`,
> `chat_evidence_application_service.py`; tests: source coverage + packet integrity.
> Live model/harness comparison and installed acceptance are pending.

> **0.31.63 / 769:** после паузы первого прохода пузырь больше не пишет
> «Сборка продолжается» и ETA. Tests: `tests/test_sovushka_chat.py`,
> `tests/test_workbook_research_job_service.py`.

> **0.31.62 / 768:** пузырь не падает на UTC `created_at` (`compute_eta`
> aware/naive). Tests: `tests/test_sovushka_chat.py`, `tests/test_indexing_eta.py`.

> **0.31.61 / 767:** открытие «выполняется» из Истории снова рисует пузырь
> сборки (hydrate checkpoint по session_id). Tests: `tests/test_sovushka_chat.py`.

> **0.31.60 / 766:** пузырь держит знаменатель 75 work-локаторов; 35/65
> была ошибка сложения materials+leftover. Tests: `tests/test_sovushka_chat.py`.

> **0.31.59 / 765:** пузырь реконнекта считает закрытые source-строки, а не
> только `row_role=work`; SKS 35/65 leftover 30, не 0/30. Tests:
> `tests/test_sovushka_chat.py`.

> **0.31.58 / 764:** follow не принимает старый ответ в сессии за завершение
> текущей ночной PENDING-сборки и не стирает N/M после первого кадра.
> Tests: `tests/test_sovushka_chat.py`.

> **0.31.57 / 763:** после обрыва SSE пузырь читает checkpoint sheet-pass
> (`list_active` / `GET /api/workbook-research-active`) и показывает текущие
> N/M, этап листа и «готово через». Tests: `tests/test_sovushka_chat.py`,
> `tests/test_workbook_research_job_service.py`.

> **0.31.56 / 762:** реконнект чата больше не показывает «Связь с окном
> пропала» и второй пузырь «Запрос выполняется». Один статус «Сборка
> продолжается» с последним 24/75; NiceGUI держит сокет 12 ч. Tests:
> `tests/test_sovushka_chat.py`.

> **0.31.55 / 761:** clean Windows runtime resolves core `data` and RAG
> MetaDB paths directly under `LES_WINDOWS_STATE_ROOT`. Proxy startup can create
> `les_meta.db` without writing through `runtime/data` junction; repository/dev
> paths stay unchanged. Tests: `tests/test_runtime_paths.py`,
> `tests/test_rag_config.py`; exact installed smoke is the release gate.

> **0.31.54 / 760:** чистая Windows-установка пишет startup-журналы и
> `windows-light-state.json` прямо в persistent state `LES_WINDOWS_STATE_ROOT/logs`.
> Создание новых файлов больше не зависит от записи через runtime junction,
> которая на чистом NSIS-контуре давала `services_start_failed` после запуска
> процессов. 760 superseded: installed smoke затем выявил тот же junction-only
> дефект для новой MetaDB. Tests: `tests/test_installer_windows.py`,
> `tests/test_tauri_desktop.py`.

> **0.31.53 / 759:** ночная ЛСР отвязывается от закрытого SSE без ожидания и
> без отмены sheet-pass; strong reference сохраняет runner до завершения.
> Пузырь не пишет «Соединение прервано», PENDING-история дожидается файла,
> повторный «Продолжить» не запускает второй packet-loop. Tests:
> `tests/test_chat_stream_w51.py`, `tests/test_sovushka_chat.py`,
> `tests/test_chat_evidence_application_service.py`.

> **0.31.51 / 757:** «Продолжить незакрытые строки» больше не выглядит как
> новая сборка: пузырь «Продолжаю…», счётчик принятых/оставшихся строк,
> режим Сметчик и ETA сразу по прошлому темпу. Tests:
> `tests/test_sovushka_chat.py`, `tests/test_chat_evidence_application_service.py`,
> `tests/test_workbook_research_job_service.py`.

> **0.31.50 / 756:** кнопка «Продолжить незакрытые строки» больше не роняет
> NiceGUI slot stack: resume/repack/уточнение toast идут через слот чата,
> а XLSX регистрируется до черновика в aside. Tests:
> `tests/test_sovushka_chat.py`.

> **0.31.49 / 755:** после стрима ЛСР toast «новый файл» больше не падает
> NiceGUI slot stack: артефакты собираются в слоте панели. Пока идёт sheet-pass,
> под таймером — «Результат будет готов примерно через ~XX». Tests:
> `tests/test_sovushka_chat.py`, `tests/test_indexing_eta.py`.

> **0.31.48 / 754:** мастер запуска больше не зависает на «Подготовка…», если
> boot уже идёт или UI уже жив. Очередь модели ждёт 1800 с (видимый фактор
> `LES_MODEL_QUEUE_WAIT_SEC`), а не обрывает второй чат через 45 с во время ЛСР.
> Tests: `tests/test_tauri_desktop.py`, `tests/test_runtime_admission.py`.

> **0.31.47 / 753:** панель «Артефакты» показывает новый XLSX сверху как
> текущий файл, одну карточку готовности ЛСР и прокручивает кнопки/текст.
> Поля уточнения подписаны по-русски (адрес строки, не SKS-заглушки).
> Tests: `tests/test_sovushka_chat.py`.

> **0.31.46 / 752:** empty `search_sources` (`status=missing`) no longer
> aborts sheet-pass before the row table. Remaining model queries still run;
> zero hits stay visible as empty groups. Tests:
> `tests/test_chat_evidence_application_service.py`.

> **0.31.45 / 751:** FreeToken default context is factory 35B `35000`; rebuild
> clamps to GPU-feasible KV with minimum MoE. ACTIVE chat observes live pages
> and does not rebuild during generation. Tests:
> `tests/test_freetoken_cache_profile_service.py`.

> **0.31.44 / 750:** structural source completion preserves the set contract
> used by packet progress; live-found regression covered in packet integrity tests.

> **0.31.43 / 749:** packet budget leaves header space and permits 1–3 rows
> on small output budgets. `structurally_complete_source_keys` keeps broken
> source links pending; `sheet_pass_keep_rows` excludes unknown locators from
> accepted decisions while preserving raw model text. `work_row_key` resolves
> relative R coordinates on their source sheet. Tests: `test_lsr_packet_integrity.py`.

> **0.31.42 workbook overflow:** упаковка LSR не прячет XLSX, если результат
> больше model-prompt budget. Cursor overflow отдаёт полный artifact оператору.

> **0.31.41 pause actually stops:** `should_cancel` истинен при `paused`, а не
> только пока `cancel_requested=1`. `POST /api/workbook-research/{id}/pause`
> больше не отпускает живой цикл сразу после сброса флага. `ChatRequest`
> принимает `comparative_acceptance_variant=B0_DIRECT` для живого baseline.

> **0.31.40 packaging confirmed_data:** контракт `build_lsr_workbook` принимает
> operator overlay до расчёта; чат №124 больше не падает `TOOL_SCHEMA_INVALID`.

> **0.31.39 source coverage + one route:** малый и большой исходник идут одним
> порядком (запросы → источники → решения → расчёт). Роли строк, `work_row`,
> исходное vs расчётное количество, конверсия только с источником, покрытие/
> нормы/цены отдельно, уточнение строк и подтверждённые данные без вызова
> модели. Точки: `chat_evidence_application_service.sheet_pass_should_run`,
> `lsr_source_coverage_service`, `rim_lsr_trace_service`,
> `lsr_result_readiness_service`, `workbook_research_job_service`,
> `POST /api/chat/patch-lsr-rows`, `sovushka/pages/chat.py`. Статус док↔код: ✅;
> live серия п.6 (БАП+СКС 9B/35B, `B0_DIRECT`, сметчик, stop/resume, exact
> Windows candidate) **не закрыта**.

> **0.31.38 packet = BAP + resume + three-way readiness:** пакетный sheet-pass
> сохраняет терминальные решения модели, без обязательного verifier и без
> заглушек при исчерпании попыток. Незавершённые пакеты, источники и кэш
> запросов переживают остановку; повтор упаковки XLSX не вызывает модель.
> Результат разделяет готовность файла, полноту норм и полноту цен с конкретным
> действием и кнопками в чате. Точки:
> `chat_evidence_application_service`, `workbook_research_job_service`,
> `lsr_result_readiness_service`, `sovushka/pages/chat.py`,
> `tests/test_{chat_evidence_application,workbook_research_job,lsr_result_readiness}_service.py`.
> Статус док↔код: ✅; live BAP/СКС 9B+35B + baseline + stop/resume + exact
> Windows candidate **не закрыты**.

> **0.31.37 query-header packets:** sheet-pass и grouped evidence больше не
> падают `MODEL_RAG_EVIDENCE_BUDGET_TOO_SMALL_FOR_ALL_QUERY_HEADERS`. Префикс
> запросов, чьи заголовки влезают, резервируется; остаток — следующий
> технический пакет (как строки 8–12) или честный omit. Точки:
> `chat_evidence_application_service.select_model_rag_query_hits_for_budget`,
> `tests/test_chat_evidence_application_service.py`. Статус док↔код: ✅;
> live СКС 35B overlay pending.

> **0.31.36 FreeToken observed KV + thinking-off:** bound ACTIVE chat больше
> не остаётся на заводском `qwen-9b-restrictive`, если GUI-подключение
> FreeToken 35B уже имеет физический KV. Probe читает
> `observed_context_tokens` из `/v1/cache/status` (`geometry.num_pages`,
> запасной `/v1/models.context_length`) и не открывает extended preset по
> одному `requested_context_tokens`. Тот же bound OpenAI transport шлёт
> `enable_thinking=false` по `extension_type`, а complete() принимает до
> 512 KiB, чтобы таблица ЛСР не обрезалась лимитом probe. Точки:
> `model_capability_service`, `openai_compatible_transport_service`,
> `proxy/routers/chat.py`. Статус док↔код: ✅; live 0.31.36 overlay:
> answer FreeToken 35B, `qwen-35b-extended`, input 28001; BAP repeat pending.

> **0.31.35 ADR-15 money unlock:** упаковочный adapter больше не требует
> независимого `EXACT_VERIFIED`/`ANALOGUE_VERIFIED`. Явный шифр терминального
> результата модели идёт в exact lookup и расчёт; `MISSING`/`CONFLICT`,
> неизвестный шифр, конфликт единиц и отсутствие цены остаются unbound/missing.
> `pricing_block_reason` живёт только в `QUALITY_DIAGNOSTIC`. Точки:
> `rim_lsr_trace_service`, `lsr_workbook_adapter_service`,
> `tests/{test_workbook_tool_service,test_rim_lsr_trace_service}.py`.
> Статус док↔код: ✅; installed live money pending.

> **0.31.34 PDF locator integrity:** terminal-result prompt требует копировать
> locator/title/unit/quantity из одной строки source catalog и сохранять
> пропуски locator, созданные строками-разделами PDF. Это предотвращает сдвиг
> всех последующих работ на locator раздела и остаётся модельным исправлением
> собственного структурного ответа. Статус док↔код: ✅; live repeat pending.

> **0.31.33 terminal model result and resumable packaging:** активная ЛСР снова
> следует принятому ADR-15: модель формулирует запросы, видит RAG и её первый
> полный итог без последующего verifier/research/coefficient-loop передаётся в
> детерминированный расчёт и XLSX. Дополнительная модельная проверка доступна
> только в изолированном `QUALITY_DIAGNOSTIC`. Техническая упаковка имеет один
> идемпотентный повтор по той же checkpoint и тем же решениям; при постоянном
> сбое видны код, checkpoint и сохранённые строки вместо общего сообщения.
> Точки: `proxy/services/{chat_evidence_application,lsr_norm_quality_gate}_service.py`,
> `tests/{test_chat_evidence_application_service,test_lsr_norm_quality_research_reopen}.py`.
> Статус док↔код: ✅; Windows live acceptance pending.

> **0.31.32 LSR conflict preservation and PDF row integrity:** исчерпание повторного поиска больше
> не превращает отклонённый моделью шифр из `CONFLICT` в ложный `MISSING`.
> PDF-ведомости получают точные `PDF!Rn` source locators из распознанной
> Markdown-таблицы, поэтому карточки норм не могут подменить строки исходного ВОР.
> Нейтральный verifier проверяет применимость, масштабные единицы совместимы,
> а XLSX выпускается как рабочий partial-аудит даже при нуле строк в деньгах.
> Точки: `lsr_norm_quality_gate_service`, `chat_evidence_application_service`,
> `lsr_workbook_adapter_service`. Статус док↔код: ✅.

> **0.30.59 local-Qwen result parse candidate:** reader принимает короткий
> markdown-divider `:--`, заголовок «Норматив монтажа (norm_code)», явные
> спецификационные таблицы без `norm_code` и секционные `###` кроме `Строка N`.
> Значения ячеек не переписываются; вопрос не выбирает ЛСР/ВОР. Длинный SSE
> держит соединение `ping` каждые 15 с, а история сразу показывает PENDING-stub
> и `in_progress`. Точки: `proxy/services/chat_evidence_application_service.py`,
> `proxy/routers/{chat,chat_history}.py`, `sovushka/pages/{chat,history}.py`,
> `tests/{test_chat_evidence_application_service,test_chat_history_router,test_chat_stream_w51,test_sovushka_chat}.py`.
> Статус док↔код: ✅; candidate not published.

> **0.30.58 liberal model-result reader candidate:** модельный ответ остаётся
> неизменным, а локальный упаковочный reader принимает обычный явный блок
> `Строка N: название` и явное отсутствие количества. Значения `source_row`,
> нормы, обоснования и evidence не выводятся из прозы и не исправляются кодом.
> Точки: `proxy/services/chat_evidence_application_service.py`,
> `tests/test_chat_evidence_application_service.py`. Статус док↔код: ✅; installed
> Legion live workbook accepted (5/5 bound, 128 formulas, automatic XLSX);
> candidate not published.

> **0.30.57 long-running chat stream candidate:** UI keeps an already active
> SSE answer open until the proxy emits its authoritative `final` or `error`.
> Connect/write/pool remain bounded, while the redundant UI read deadline is
> removed; server-side model/tool limits and explicit user stop remain in
> force. This does not add a model turn, route, retry, or alter model output.
> Points: `sovushka/state.py`, `tests/test_chat_stream_w51.py`. Status doc↔code:
> ✅; live workbook acceptance pending; candidate not published.

> **0.30.56 per-answer citation anchors candidate:** адреса цитат scoped по
> `history_id`, поэтому одинаковые номера источников в разных репликах не
> конфликтуют. Точки: `sovushka/{answer_render.py,pages/chat.py}`,
> `tests/{test_answer_render_v16.py,test_sovushka_chat.py}`. Статус док↔код: ✅;
> candidate не опубликован.

> **0.30.55 legacy web evidence recovery candidate:** история прежних
> web-реплик восстанавливает URL, заголовки и snippets из сохранённых tool
> results, когда полный source map ещё не записывался. Повторный поиск и model
> turn не выполняются. Точки: `proxy/routers/chat_history.py`,
> `tests/test_chat_history_router.py`. Статус док↔код: ✅; candidate не
> опубликован.

> **0.30.54 exact evidence history candidate:** полный фактически показанный
> модели source map и три счётчика сохраняются с репликой. Старые реплики
> восстанавливают навигацию из immutable evidence manifest. Диапазоны цитат
> одинаково читаются presentation, source counts, integrity check и manifest;
> модельный ответ не переписывается. Точки:
> `proxy/{routers/chat_history.py,services/{chat_evidence_application,
> chat_evidence_manifest,evidence_packet,source_locator}_service.py}`,
> `sovushka/answer_render.py` и соответствующие tests. Статус док↔код: ✅;
> candidate не опубликован.

> **0.30.53 source navigation candidate:** метки `[Источник N]`, перечисления
> и обычные диапазоны `[Источник 1–4]` в тексте и Markdown-таблицах ведут к
> компактным кнопкам процитированных
> документов. Кнопка открывает существующую карточку источника с цитатой,
> locator, путём и оригиналом. Это только представление уже готового ответа:
> модельный текст, retrieval и evidence не изменяются. Точки:
> `sovushka/{answer_render.py,pages/chat.py}`,
> `tests/{test_answer_render_v16.py,test_sovushka_chat.py}`. Статус док↔код: ✅;
> candidate не опубликован.

> **0.30.48 model-owned RAG/web/live-workbook candidate:** Qwen-authored query
> lines are retrieved independently and rendered as balanced `Qx.Hy` groups;
> only syntactic quote/`search_sources(...)` wrappers are removed, without
> regex, topic routing or another model call. Attachment storage follows the
> selected runtime state root, so the unchanged model result reaches the
> canonical workbook adapter and pricebook. Web research has GUI-owned
> `simple | extended` policy, SearXNG fallback and model-invoked page reading.
> Startup mutation can be disabled for bounded acceptance; resident-model
> admission no longer rejects the already loaded exact Qwen or silently swaps
> Ollama for MLX. ColBERT remains generation-gated and was shadow-tested only.
> Live isolated acceptance: ordinary dialogue and web succeeded; alternate
> 5-row VOR produced 5 bound norms, 121 formulas, 0 formula errors and a priced
> XLSX total of 154,981.55 RUB. Installed baseline `0.30.42 · 682 · ab5146b2`
> is unchanged. Status docs↔code: ✅; candidate is not installed or published.

> **0.30.47 all-update/database-resilience candidate:** все активные пути
> обновления сметной базы (GUI/API ФГИС, Make и CLI) замкнуты на один
> coordinator; низкоуровневый builder не может заменить configured active
> SQLite. Общий межпроцессный lease исключает гонку полной публикации и
> фоновой пересборки, различает свежий незавершённый lock и след упавшего
> процесса. Startup восстанавливает exact-SHA manifest/integrity после
> прерванного переключения и поддерживает произвольные configured пути и alias.
> Windows runtime/patch manifests fail-closed запрещают `data`, `storage`,
> `RAG_Content`, `logs`, `artifacts`; матрица update-resilience включена в
> обязательные гейты. Точки: `tools/{smeta_generation_coordinator,
> smeta_generation_lease,rebuild_active_smeta_rag,build_tauri_app,
> release_classification}.py`, `proxy/services/
> smeta_generation_reconciliation_service.py`, runtime manifests и
> `tests/test_update_resilience_matrix.py`. Статус док↔код: ✅; candidate не
> установлен и не опубликован.

> **0.30.46 atomic smeta base/index generation candidate:** обновление ФГИС
> строит SQLite, manifest/integrity и dedicated native-RRF индекс рядом с
> активной парой, проверяет exact SHA и переключает файлы+Qdrant alias только
> после readiness; отказ восстанавливает прежнюю пару. Startup сверяет живой
> alias, находит сохранённую exact-SHA generation либо запускает фоновую
> sibling-сборку. Read-only readiness и «Документы» явно показывают
> `SMETA_BASE_INDEX_REVISION_MISMATCH`; рестарт ЛЕС не требуется. Точки:
> `tools/{smeta_generation_coordinator,rebuild_active_smeta_rag,
> activate_smeta_rag_generation,gesn_update_from_fgis}.py`,
> `proxy/services/{smeta_generation_reconciliation,rag_readiness}_service.py`,
> `sovushka/pages/documents.py`. Чат, решения модели и `proxy/smeta_core/**` не
> изменяются. Статус док↔код: ✅; candidate не установлен и не опубликован.

> **0.30.43 RAG evidence continuity and readiness candidate:** native RRF
> overfetch, document diversity и model evidence limit принадлежат effective
> профилю (`64/2/6` по умолчанию) и видны в GUI. Source map сохраняет typed
> locator/page/source_ref и раздельные found/model-visible/cited counts;
> фактически показанный evidence сохраняется immutable manifest между
> репликами. `selected_sources_only` исполняемо управляет web capability.
> Запросы ждут bounded model queue без чтения `Semaphore._value`; публичные
> ошибки не раскрывают exception detail. Readiness разделён по измерениям,
> RAPTOR default `off`, ColBERT работает только с audited ready generation.
> Точки: `proxy/services/{retrieval_candidate,source_locator,
> chat_evidence_manifest,chat_capability_scope,public_error,runtime_admission,
> rag_advanced_policy,rag_pipeline_status,rag_readiness}_service.py`, существующие
> chat/retrieval services и `sovushka/pages/{chat,profiles,diag}.py`.
> [Модуль](modules/rag-evidence-flow.md). Статус док↔код: ✅; candidate не
> установлен и не опубликован.

> **0.30.41 installed contour compatibility hotfix:** effective estimator
> snapshot поднимает model-authored query policy для старых user revisions без
> их перезаписи; каждый model-visible `search_sources` использует effective
> profile limit (заводской default 6).
> Health распознаёт полную legacy-смесь system ФСНБ в общем физическом индексе,
> отдельно показывает её объём и оценивает user-каталог без ложного red.
> Механический упаковщик понимает обычные подписанные строки ответа модели, а не
> только Markdown-таблицы. Точки: `proxy/services/{chat_profile,
> model_research_tool,chat_evidence_application}_service.py`,
> `backend/qdrant_adapter.py`; соответствующие четыре regression tests. ✅

> **0.30.40 dedicated estimate RAG hotfix:** запросы профиля сметчика идут в
> effective сметную RAG-коллекцию из активной настройки базы, а не в общий
> `les_rag`. Имя коллекции не зашито: поддерживается любой настроенный alias.
> Каждый запрос возвращает модели не более 6 карточек; неготовый dedicated
> native RRF блокируется без fallback в смешанный общий корпус. Для уже
> выбранных пользовательских estimator-профилей model-authored query является
> инвариантом режима и не зависит от отсутствующего в старом snapshot флага. Точки:
> `proxy/services/{chat_evidence_application,model_research_tool}_service.py`,
> `tests/test_{chat_evidence_application,model_research_tool}_service.py`.
> Статус док↔код: ✅.

> **0.30.39 installed FGIS supervisor:** Windows runtime manifest включает
> динамическую `python -m tools.fgis_update_supervisor` зависимость штатной
> кнопки обновления ФГИС/ФСНБ. Installed API больше не сообщает ложный
> `started` перед немедленным отказом отсутствующего модуля. Точки:
> `config/windows_runtime_manifest.json`, `tests/test_tauri_desktop.py`. Статус
> док↔код: ✅.

> **0.30.42 model→RAG hotfix:** `chat_evidence_application_service` сохраняет
> значения результата Qwen без перенумерации/regex-подмены, проверяет только
> полноту и evidence-ссылки перед XLSX; `model_research_tool_service` и
> `retrieval_service` ограничивают model-facing поиск шестью hits; estimator и
> обычный RAG разведены; smeta alias берётся из active config; capability
> evidence обновляется без рестарта. `rag_readiness_service` считает native
> dense+sparse RRF без запрещённой зависимости от legacy lexical sidecar.
> Точки: `proxy/{routers/chat.py,services/{chat_evidence_application_service,
> model_research_tool_service,retrieval_service,rag_readiness_service}.py}`,
> `proxy/smeta_core/norm_browser.py`, `tools/release_orchestrator.py`. Статус: ✅.
>
> **0.30.38 bounded Windows smoke path:** full-release clean-install сохраняет
> изоляцию внутри checkout, но использует короткий `.codex_tmp/wrs/<sha12>-<id8>`.
> Глубокие временные пути `uv`/Hatchling больше не достигают Windows
> `STATUS_NAME_TOO_LONG` до запуска ЛЕС. Точки:
> `tools/windows_prepare_update.ps1`, `tests/test_patch_release.py`. Статус
> док↔код: ✅.

> **0.30.37 installed-smoke environment repair:** full-release smoke перед
> запуском установленного `bootstrap.ps1` восстанавливает совместимый с Windows
> PowerShell 5.1 `PSModulePath` и удаляет унаследованные dev `VIRTUAL_ENV/UV_*`.
> Clean install больше не объявляет исправный bundled runtime повреждённым из-за
> отсутствующего `Get-FileHash`. Точки: `tools/windows_release_smoke.ps1`,
> `tests/test_installer_windows.py`. Статус док↔код: ✅.

> **0.30.36 full-installer staging repair:** Windows runtime manifest включает
> корневой `README.md`, который объявлен package metadata в `pyproject.toml` и
> необходим локальному `uv sync --locked` при сборке offline cache. Ошибка
> локального `windows_prepare_update.ps1` теперь сохраняет bounded stdout/stderr
> в сообщении оркестратора вместо немого exit code. Точки:
> `config/windows_runtime_manifest.json`, `tools/release_orchestrator.py`,
> `tests/test_{tauri_desktop,release_orchestrator}.py`. Статус док↔код: ✅.

> **0.30.35 release recovery:** release-orchestrator разрешает feature worktree
> найти attested full-base в каноническом `repo_root`; `--force-full` переводит
> доказанно несовместимую установленную базу в полный NSIS-контур, не ослабляя
> checksum guard. Для `--host local` installer готовится штатным
> `windows_prepare_update.ps1`, копируется в immutable candidate и получает
> bounded hard-update job для install → smoke → rollback → reinstall. Точки:
> `tools/release_orchestrator.py`, `tests/test_release_orchestrator.py`,
> `docs/RELEASE_PROCEDURE.md`. Статус док↔код: ✅.

> **Текущий model → RAG → result:** активный контракт закреплён в
> [ADR-15](ADR-15-model-rag-result.md): одна модель видит исходный вопрос и
> вложение, сама формулирует любое необходимое число запросов, получает карточки
> из настроенного dedicated сметного native-RRF RAG и выдаёт все профессиональные
> строки. Только после терминального model result код рассчитывает, подставляет
> цены из pricebook и автоматически прикладывает XLSX. Selector/workbook loop,
> `status`, confirm/review и лимит числа строк в активном пути отсутствуют.
> Ошибка упаковки не меняет model result и не запускает новый предметный ход.
> Точки входа: `proxy/services/chat_evidence_application_service.py`,
> `proxy/services/model_research_tool_service.py`,
> `proxy/services/lsr_workbook_adapter_service.py`,
> `tests/test_chat_evidence_application_service.py`. Статус док↔код: ✅ —
> изолированный dev-chat на Legion принял реальный PDF: Qwen сформировала 11
> обычных поисковых строк, RAG вернул 11 групп по 6 карточек `Qx.Hy`, финальный
> no-tools ответ дал 19 строк, а код автоматически собрал XLSX. В книге 17
> привязанных норм, 2 видимых конфликта единиц, цены Санкт-Петербурга за II
> квартал 2026 года и формульный итог. Установленные 8050/8051 не изменялись.

> **0.30.30 model → RAG → result:** role-bound estimator scope добавляет только
> typed system datasets `smeta`; первый и последующие запросы `search_sources`
> формулирует сама active answer model. Вложение входит в evidence первого
> model call, native tool schemas строятся из registry, все model tool calls
> сохраняются, а `decisions` дословно передаются workbook adapter. Исходная
> команда пользователя не превращается кодом в сметный поисковый запрос. Общая
> политика `rag_policy.model_authored_initial_query` включает этот поток без
> сценарного условия по имени режима.
> Точки входа: `proxy/services/{chat_profile,chat_evidence_application,
> model_research_tool,canonical_route,capability_broker}_service.py`,
> `proxy/routers/chat.py`; tests `test_{chat_profile,chat_evidence_application,
> model_connection_chat_integration,capability_broker}_service.py`,
> `test_chat_harness_format.py`. Статус док↔код: ✅.

> **0.30.29 workbook attachment handoff repair:** model selector получает в
> обязательном request-блоке факт привязанного server-owned attachment и exact
> временный ID. Это восстанавливает рабочую границу PR `dbd4123a` после перехода
> на ContextGovernor: модель выбирает `build_lsr_workbook` / `build_vor_workbook`,
> код не выбирает за неё и не копирует полный текст файла в control payload.
> Точки входа: `proxy/services/chat_evidence_application_service.py`,
> `tests/test_chat_evidence_application_service.py`. Статус док↔код: ✅.

> **0.30.28 factory profile upgrade repair:** startup синхронизирует стабильные
> `factory:*:base` prompt/skill/profile snapshots с текущим code contract и
> обновляет только bindings на эти заводские revision ID. Поэтому установленная
> MetaDB прошлой сборки получает `build_lsr_workbook` / `build_vor_workbook` в
> режиме «Сметчик»; пользовательские ревизии и bindings не переписываются.
> Ordinary-chat trace показывает фактический active answer-binding route.
> Точки входа: `proxy/services/{chat_profile_service,canonical_route_service,
> chat_evidence_application_service}.py`, `tests/{test_chat_profile_service,
> test_canonical_route_service}.py`. Статус док↔код: ✅.

> **0.30.27 Windows patch EOL repair:** cumulative builder получает путь exact
> установленного Legion runtime и включает его raw SHA лишь после
> content-equivalence с доверенной Git ancestry при LF-нормализации. Клиент и
> target helper канонизируют только CRLF→LF для разрешённых текстовых файлов;
> checksum guard остаётся fail-closed для любого иного изменения. Точки входа:
> `tools/{release_orchestrator,github_patch_release,vps_patch,vps_patch_apply}.py`,
> `proxy/services/update_service.py`, `tests/{test_release_orchestrator,test_vps_patch}.py`.
> Статус док↔код: ✅.

> **0.30.25 operator-output repair:** release CLI принудительно использует UTF-8
> stdout/stderr до progress и итогового JSON. Subprocess-регрессия с
> `PYTHONIOENCODING=cp1251` доказывает byte-valid русский вывод. Продуктовый
> runtime, RAG, сметы и данные не менялись. Точки входа:
> `tools/release_orchestrator.py`, `tests/test_release_orchestrator.py`.
> Карта: 960 tracked Python-файлов / 297684 строки, 337 product-reachable,
> 8 runtime-support, 614 test/tool-only, 1 dormant, 330 API routes, 0 warnings.
> Статус док↔код: ✅.
>
> **0.30.24 release-path repair:** cumulative patch строится пакетным чтением
> ancestry/tree/blob вместо тысяч отдельных Git-процессов и показывает
> ограниченный progress. После живой acceptance оркестратор сам выполняет
> fail-closed non-force fast-forward публичного `main` до exact target; при
> divergence draft не создаётся, а доказательство sync сохраняется в receipt.
> Карта: 960 tracked Python-файлов / 297641 строка, 337 product-reachable,
> 8 runtime-support, 614 test/tool-only, 1 dormant, 330 API routes, 0 warnings.
> Точки входа: `tools/{vps_patch,release_orchestrator,github_patch_release}.py`,
> `tests/{test_vps_patch,test_release_orchestrator}.py`. Статус док↔код: ✅.
>
> **0.30.23 experimental API, tool-availability and release-procedure cleanup:** из production app
> удалены 64 route без Совушки, ToolHarness или внутренних HTTP-потребителей:
> BOR, decisions, doc-review, edges, estimates, field, KAC, LES MD, ontology,
> prices и старая proxy status page. Общие сервисы, используемые чатом, MCP,
> проектным dossier, расчётом и dataset intake, сохранены; удалены только 11
> router-файлов и три исключительно зависимых service-island. Пользовательские
> БД, документы и артефакты не мигрировались и не удалялись. Context-bound
> workbook contracts больше не считаются обычным ToolHarness исполняемыми:
> чат показывает модели VOR и тонкий LSR adapter; LSR принимает model-owned
> `decisions`, считает и рендерит без скрытого model loop. Карта: 960 tracked Python-файлов /
> 297229 строк, 337 product-reachable, 8 runtime-support, 614 test/tool-only,
> 1 dormant, 330 API routes, 0 parse warnings. Точки входа: `proxy/app.py`,
> `proxy/services/{tool_harness_service,workbook_tool_service,
> chat_evidence_application_service}.py`, `tests/{test_code_runtime_map,
> test_tool_harness_service,test_workbook_tool_contracts}.py`. Статус док↔код: ✅.

> **0.30.19 profile tool-policy cleanup:** удалён неиспользуемый второй набор
> tool allowlists из `ProfileResolver`. Единственный фактический allowlist
> строится `chat_profile_service` из живого ToolHarness registry, фиксируется
> immutable snapshot чата и применяется evidence application. Trace теперь
> прямо сообщает `tool_policy_source=chat_profile_snapshot`. Эффективные tools,
> сметы, RAG, Qdrant, данные и Legion не менялись. Карта: 979 tracked
> Python-файлов / 299483 строки, 354 product-reachable, 8 runtime-support,
> 616 test/tool-only, 1 dormant, 394 API routes, 0 parse warnings. Точки входа:
> `proxy/services/{profile_resolver,chat_profile_service,chat_evidence_application_service}.py`,
> `tests/{test_profile_resolver,test_chat_profile_runtime}.py`. Статус док↔код: ✅.

> **0.30.18 legacy normcontrol API cleanup:** удалён неиспользуемый router и
> два `/api/normcontrol/*` route. Формальный `normcontrol_service`, его 13
> behavior-тестов и активный `/api/doc-review/*` сохранены. Фантомный
> `run_normcontrol` удалён из прежней декларативной карты профиля. Данные,
> отчёты, review decisions, сметы, RAG и Legion не
> менялись. Карта на момент 0.30.18: 979 tracked Python-файлов / 299491 строк, 354 product-reachable,
> 8 runtime-support, 616 test/tool-only, 1 dormant, 394 API routes,
> 0 parse warnings. Точки входа: `proxy/app.py`,
> `proxy/services/profile_resolver.py`, `tests/test_code_runtime_map.py`.
> Статус док↔код: ✅.

> **0.30.17 unintegrated product-island cleanup:** удалён изолированный W12.1
> «Дифф CAD/BIM и текстов»: три `/api/diff/*` route, router, service и
> service-only тесты. Контур не имел UI, model tool, dossier или иных
> production-потребителей; live-приёмка двух реальных ревизий не была выполнена.
> Активный `/api/cad-bim/imports`, viewer, CAD/BIM graph data, документы, сметы,
> RAG и Legion не менялись. Карта: 980 tracked Python-файлов,
> 355 product-reachable, 8 runtime-support, 616 test/tool-only, 1 dormant,
> 396 API routes, 0 parse warnings. Точки входа: `proxy/app.py`,
> `tests/test_code_runtime_map.py`, `docs/CODE_MAP.md`. Статус док↔код: ✅.

> **0.30.16 unfinished product-island cleanup:** удалён изолированный W20.3
> «Общий журнал работ»: четыре `/api/worklog/*` route, router, service и
> service-only тест. Контур реализовывал только незавершённую форму разделов
> 1–3 и не имел UI, model tool, project dossier или иных production-потребителей.
> Таблица `les_work_log_meta`, пользовательские БД и сформированные файлы не
> удалялись и не мигрировались. Активный `/api/field`, проекты, словарь ОЖР,
> сметы, RAG и Legion не менялись. Карта: 983 tracked Python-файла,
> 357 product-reachable, 8 runtime-support, 617 test/tool-only, 1 dormant,
> 399 API routes, 0 parse warnings. Точки входа: `proxy/app.py`,
> `tests/test_code_runtime_map.py`, `docs/CODE_MAP.md`. Статус док↔код: ✅.

> **0.30.15 unfinished product-island cleanup:** удалён изолированный W20.4
> «Входной контроль»: семь `/api/incoming-control/*` routes, router, service и
> service-only тест. Контур не имел UI, model tool, project dossier или иных
> production-потребителей; заявленная W20.5-интеграция так и не была сделана.
> SQLite/user state не удалялись и не мигрировались. Активные `/api/field`,
> `/api/tasks`, `/api/notes`, `/api/filemap`, `/api/decisions`, сметы, RAG и Legion
> не менялись. Карта: 986 tracked Python-файлов, 359 product-reachable,
> 8 runtime-support, 618 test/tool-only, 1 dormant, 403 API routes, 0 parse warnings.
> Точки входа: `proxy/app.py`, `tests/test_code_runtime_map.py`,
> `docs/CODE_MAP.md`. Статус док↔код: ✅.

> **0.30.14 API surface cleanup:** удалены четыре переходных/дублирующих route:
> mutable `GET/PATCH/DELETE /api/prompts*`, заменённый immutable-профилями, и
> неавторизованный generic `POST /api/extract/structured`. Внутренние
> `prompt_registry_service` и `extract_service` сохранены для штатных workflow;
> `/api/profiles`, `/api/rerank`, сметные API, RAG и Legion не менялись. Карта:
> 989 tracked Python-файлов, 361 product-reachable, 8 runtime-support,
> 619 test/tool-only, 1 dormant, 410 API routes, 0 parse warnings. Точки входа:
> `proxy/app.py`, `tests/test_code_runtime_map.py`, `docs/CODE_MAP.md`.
> Статус док↔код: ✅.

> **0.30.13 operator-tool cleanup:** две будущие идеи визуализации разнесены в
> backlog: лесная оболочка текущего графа не меняет RAG, а evidence-replay остаётся
> отдельной будущей функцией наблюдаемости. После проверки импортов, документации и
> Git history удалены шесть неиспользуемых одноразовых CLI: исторический checklist
> smoke с UUID прежнего корпуса, pre-IMAP mail smoke, ручной batch-parser до job/scheduler
> и мигратор старой корзины `NTD_OTHER_Index`, а также старые `smart_dataset_plan/rebuild`:
> их read-only план уже доступен через API, а rebuild напрямую удалял БД, storage и
> коллекцию по жёстко заданному старому адресу вместо guarded reindex. Активные checklist API, Самовар,
> `test-mail`/IMAP, guarded reindex, RAG, Qdrant visualizer, сметы и установленный
> Legion не менялись. Runtime-map теперь игнорирует уже удалённые tracked-файлы в
> незакоммиченном дереве и поэтому может проверять сам cleanup. Карта: 991 tracked
> Python-файл, 363 product-reachable, 8 runtime-support, 619 test/tool-only,
> 1 dormant, 414 API routes, 0 parse warnings. Точки входа:
> `tools/code_runtime_map.py`, `tests/test_code_runtime_map.py`,
> `ROADMAP_TO_V1.md`. Статус док↔код: ✅.

> **0.30.10 second proven cleanup:** удалены неиспользуемый
> `proxy/legacy_app.py`, два корневых ручных пробника, отдельный устаревший
> chunk-density prototype, Pikabu R&D experiment и весь tracked `legacy/`
> backup/patch-каталог. Git history остаётся recovery-источником. Единственный
> `DORMANT_CANDIDATE` — намеренно сохранённая будущая Mail-страница.
> `TEST_INVENTORY.md` снова является текущей картой команд и границ; его
> релизная хронология перенесена в архив. Карта после удаления: 997 tracked
> Python-файлов, 363 product-reachable, 8 runtime-support, 625 test/tool-only,
> 1 dormant, 414 API routes и 0 parse warnings. Сметы, Mail, ARTEL, runtime и
> пользовательские данные не менялись. Точки входа: `tools/code_runtime_map.py`,
> `tests/test_code_runtime_map.py`, `Makefile`. Статус док↔код: ✅.

> **0.30.5 first proven dead-code cleanup (build 645, dev candidate):** удалены
> 15 Python-файлов (2615 строк, включая тест удалённой Mermaid-страницы) и один
> orphan HTML, для которых карта импортов,
> production shell и точечный поиск не нашли продуктового пути. Число
> product-reachable модулей осталось 363, фактических FastAPI routes — 396;
> вместе с очисткой сохранявших их тестов общий Python-инвентарь уменьшился на
> 2726 строк; на этом checkpoint `DORMANT_CANDIDATE` сократился с 14 до двух файлов:
> `proxy/legacy_app.py` и `sovushka/pages/mail.py`; следующий cleanup удалил shim. RIM backend/API, активная
> Qdrant-визуализация, Mail-код и `proxy/smeta_core/**` не менялись. Точки входа:
> `tools/code_runtime_map.py`, `docs/CODE_RUNTIME_MAP.md`. Статус док↔код: ✅.

> **0.30.4 generated code-runtime map (build 644, dev candidate):**
> `tools/code_runtime_map.py` строит из tracked Python, AST-imports, боевых entrypoint,
> Windows runtime manifest и FastAPI decorators воспроизводимую карту
> `docs/CODE_RUNTIME_MAP.md` + `docs/generated/code_runtime_map.json`. Статусы разделяют
> `PRODUCT_REACHABLE`, отдельные `RUNTIME_SUPPORT`, тесты/инструменты и только
> `DORMANT_CANDIDATE` — без автоматического объявления кода мёртвым. Отдельный focus
> показывает реальные импорты символов 9530-строчного
> `proxy/smeta_core/document_workflow.py`; сметное поведение не менялось.
> Точки входа: `tools/code_runtime_map.py`, `tests/test_code_runtime_map.py`.
> Статус док↔код: ✅.

> **0.30.3 clean Windows runtime manifest (build 643, dev candidate):** Tauri больше не
> копирует почти весь tracked repository в установленный runtime. Явный
> `config/windows_runtime_manifest.json` оставляет продуктовые пакеты, Windows bootstrap,
> runtime assets и 24 необходимых runtime/updater tools; tests/docs/legacy/dev/golden,
> build/publish tools и исходники отдельных продуктов не устанавливаются. Контракт проверяет
> allowlist и транзитивные Python imports из `tools`. Точки входа:
> `tools/build_tauri_app.py`, `tests/test_tauri_desktop.py`. Статус док↔код: ✅.

> **0.30.6 transactional delete bridge (build 646):** cumulative GitHub patch
> остаётся `les.vps-patch.v2`, поэтому установленная `0.30.0` проверяет пакет и
> извлекает checksum-declared target helper. Delete-entry имеет нулевой
> compatibility payload; новый `vps_patch_apply.py` до stop проверяет historical
> SHA, сохраняет файл, удаляет его и возвращает при forced rollback. Уже
> отсутствующий файл — идемпотентная цель; unknown bytes и protected paths
> отклоняются без мутации. User state и `proxy/smeta_core/**` не меняются.
>
> **0.30.1 model-owned evidence-first RAG + readable UI + soft updater (build 640):** без выбора источников
> чат идёт напрямую к модели; выбранные датасеты/вложения и явный «Все
> источники» создают точный scope. Initial и повторный model-selected поиск
> используют один production native RRF. Evidence упаковывается раньше памяти,
> полный model-visible packet доступен в trace, а финальный ответ модели не
> переписывается валидатором. Точки входа:
> `proxy/services/{scope,chat_evidence_application,model_research_tool,
> context_governor,model_execution_preset}_service.py`,
> `sovushka/pages/chat.py`, `tools/rag_dataset_story_acceptance.py`. Общий
> UI-kit убирает legacy desktop `12px`/monospace, применяет системный sans и
> шкалу `16/15/14` с WCAG AA-контрастом; desktop rail расширен до `200px` без
> обрезания русских действий. Точки UI: `sovushka/{styles,uikit/tokens}.py`.
> Soft updater поверх установленной `0.30.0` не управляет Docker/Qdrant,
> принимает внешний Qdrant как `available`/`N/A`, а version-only `uv.lock` не
> превращает runtime-патч в полную переустановку. Точки updater:
> `tools/{release_classification,vps_patch,vps_patch_apply}.py`.
> Если proxy завис, runtime recovery принимает только exact записанные PID,
> полный набор портов, persistent Python и process contract; чужой владелец
> порта по-прежнему получает `foreign_port_owner`. Точка: `tools/windows_runtime.py`.
> Preflight ФСНБ совместим с bootstrap 0.30.0: доказательством служит exact
> ГЭСН expand с ресурсами, а не отсутствующие в старом readiness новые поля.
> Detached patch task имеет один delayed trigger и auto-expiry; ручной
> `Start-ScheduledTask` больше не создаёт второй запуск и конфликт `apply.lock`.
> Статус док↔код: ✅.

> **0.29.4 answer binding + visible scope (build 633):** назначенная в
> `Конфигурация → Модели → Ответы` ревизия является фактической моделью обычного
> чата без promotion/shadow-подмены на legacy. Shadow сохранён только для
> изолированной телеметрии/приёмки. Явно выбранные dataset IDs остаются exact
> retrieval scope; ответ и trace показывают фактически использованные датасеты.
> Точки входа: `proxy/routers/chat.py`,
> `proxy/services/chat_evidence_application_service.py`,
> `sovushka/pages/{chat,model_connections}.py`. Статус док↔код: ✅.

> **0.28.1 public Windows runtime:** `LES-Setup.exe` содержит проверенные portable Python/uv,
> exact `uv.lock` и offline dependency cache. Стартовый Tauri-экран показывает совместимые
> Ollama/FreeToken/Lemonade/OpenAI-compatible, embeddings и Qdrant по ролям, но ничего не
> устанавливает и не выбирает. Отсутствие внешних движков — capability warning; LES core запускается.
> Upload и global auto-resume сериализованы одним parse semaphore, поэтому first-run supervisor
> не индексирует только что загруженный smoke/user document параллельно второй раз.

> **0.29.0 active architecture:** все новые inference/tool изменения сразу идут
> через общий Tool Registry, Capability Broker, Trusted Executor,
> ContextGovernor и typed memory projection. Канонические workbook-tools —
> `build_lsr_workbook` / `build_vor_workbook`; параллельные `estimate_*`, regex
> forcing и автоматическая активация профиля запрещены. Один workflow работает
> на Qwen 3.5 9B и 35B с разными execution-presets. Текущий контракт:
> [Canonical Tool, Context, Memory and Artifact Update](superpowers/specs/2026-08-26-canonical-tool-context-memory-update-design.md).
> Старые estimator bridge design/plan помечены superseded и не являются
> инструкциями. Исполнимый маршрут разбит на пять независимых планов, связанных
> из раздела `Executable implementation plans` канонической спецификации.
> Изолированный candidate rollout управляется фактором `legacy | shadow | active`:
> отсутствующее значение означает side-effect-free `shadow`, а `active`
> fail-closed требует точного 9B acceptance receipt и явного действия оператора;
> установка обновления ничего не активирует автоматически. Этот фактор не
> переопределяет явную пользовательскую привязку роли `answer` в обычном чате.

> **0.29.0 workbook execution (build 620):** `build_vor_workbook` проверяет
> server-owned attachment ID+SHA, сохраняет исходные XLSX-строки/количества и
> locators без догадок, публикует append-only artifact revision и возобновляет
> durable checkpoint по idempotency key. `build_lsr_workbook` принимает только
> явно подключённый application-adapter; готовые цены/суммы/строки из tool args
> запрещены. Точки входа: `proxy/services/{workbook_tool_service,bor_service,
> artifact_revision_service,workflow_checkpoint_service}.py`.
> Architecture guard отличает реальный language matching по question/query/
> prompt/message/text от обычных membership-проверок JSON schema.

> **0.29.0 workbook live-acceptance (build 623):** opt-in
> `tools/live_workbook_acceptance.py` проверяет реальный ordinary-chat contract
> через `/api/chat/attachments`, `/api/chat/stream` и authenticated
> artifact metadata/download. Receipt содержит только redacted `live_runtime`:
> exact full 40-hex version commit/positive build/clean aligned runtime,
> profile/model/preset, attachment/provenance/checkpoint lineage, immutable N+1
> parent, complete monotonic SSE progress, readable XLSX with two-cell header
> and data row, и downloaded SHA-256; missing/blockers сохраняются только как counts with
> exact typed receipt allowlists. Guarded `candidate_acceptance` доступен лишь root-admin в отдельном
> process-CWD, совпадающем с read-only Danger
> `LES_CANONICAL_ACCEPTANCE_STATE_ROOT`; candidate upload is guarded before
> persistence and all effective workbook state stays below it. Public route остаётся shadow,
> receipt не подделывается: fake transport имеет только nonpersistent `contract_test`.
> Hermetic ASGI check uses real multipart/SSE/artifact route composition and
> real chat application/harvest. Fixture supplies an isolated profile snapshot,
> empty retrieval/history ports, and lower model transport, tool shortlist and
> workbook executor. It is not model-quality evidence.
> Статус: 🟡 **PENDING: live user-owned input/model acceptance**;
> offline contracts не являются quality evidence.

> **0.29.0 model-connection runtime (build 610):** ordinary free и evidence
> chat в `active` разрешают точную immutable ревизию роли `answer` и вызывают
> единый OpenAI-compatible transport. Единственный fallback — точная привязка
> `local_fallback`; shadow не делает второй inference-вызов. Bound preset идёт
> в ContextGovernor, notebook memory и вложения остаются частью того же
> governed packet, а из нескольких tool calls исполняемым становится только
> первый, остальные учитываются как pending. Публичная трасса не содержит URL
> и secret reference. Точки входа: `proxy/routers/chat.py`,
> `proxy/services/canonical_route_service.py`,
> `proxy/services/chat_evidence_application_service.py`,
> `proxy/services/openai_compatible_transport_service.py`.

> **0.29.0 model-connections API (build 611):** authenticated router
> `proxy/routers/model_connections.py` управляет immutable revisions,
> capability snapshots, server-owned masked secrets и exact bindings ролей
> `answer | embeddings | local_fallback`. Полный registry/templates/write/test
> surface доступен только administrator; обычный пользователь видит лишь
> безопасный effective summary без endpoint/secret данных. Unsafe URL получает
> 422 до записи, stale CAS — 409, отключение bound head требует явного
> подтверждения. Статус док↔код: ✅ runtime integration + API + GUI. Build 615
> добавляет `sovushka/pages/model_connections.py`: shared-UIKit registry с
> role bindings, requested→effective context, capability evidence и guarded
> create/copy/edit/test/secret/bind/disable actions; mobile contract закреплён
> `tests/test_sovushka_model_connections.py`.
> С 0.30.27 bind роли автоматически probe-ит непроверенную/непригодную точную
> ревизию и требует подтверждённый `chat_completions` либо `embeddings`.
> Ollama-native chat выбирается только live capability snapshot и отключает
> reasoning через официальный `think=false`; шаблоны UI предлагают уникальные
> имена и объясняют конфликт названия по-русски. При приложенной ВОР оба
> workbook-tool входят даже в ограниченный shortlist 9B; код их не вызывает
> автоматически. Статус док↔код: ✅.

> **0.29.0 private nodes / promotion closure:** LAN и ZeroTier являются одной
> явной locality `private_network`; HTTP разрешён только после private-only DNS
> и connected-peer проверки, тогда как remote остаётся HTTPS-only. Read-only
> FreeToken/MLX extension status изолирован от inference; неизвестные extensions
> возвращают `unsupported`. Admin может принять redacted live 9B workbook
> report, но это не переключает режим: requested `active` становится effective
> только при exact receipt для текущих commit/build/preset/model. Постоянные
> Make/portable gates включают registry/security/resolver/transport/chat/API/UI,
> candidate acceptance, live workbook contract, extensions и promotion.

> **0.29.0 closing runtime gates (build 626):** model-only opt-in acceptance
> проверяет exact 9B/35B revisions через живой HTTP transport и сохраняет
> redacted receipt без prompt/answer. Windows lifecycle поддерживает независимые
> `full | backend | ui`: отдельная Совушка требует explicit backend URL и не
> поднимает backend/model dependencies; backend не занимает UI-порт; Tauri
> по-прежнему стартует `full`. Installed Windows и real workbook acceptance
> остаются отдельными обязательными release gates. Точки входа:
> `tools/{model_connection_live_acceptance,windows_runtime}.py`,
> `installers/windows/{start-light,stop-light}.ps1`; тесты
> `test_model_connection_live_acceptance.py`, `test_windows_application_update.py`,
> `test_installer_windows.py`. Статус док↔код: ✅.

> **0.29.3 capability probe fix (build 631):** connected-peer policy теперь
> проверяет фактический upstream до чтения response body. Это сохраняет
> ZeroTier/LAN SSRF-защиту и корректно принимает завершённый SSE, у которого
> сетевой stream metadata освобождается после `[DONE]`. Тело по-прежнему
> читается с жёстким лимитом и не попадает в capability evidence. Точки входа:
> `proxy/services/model_capability_service.py`,
> `tests/test_model_capability_service.py`. Статус док↔код: ✅.
> Тот же build нормализует публичный unscoped `dataset_ids=None` в пустую
> внутреннюю область до typed-memory и Broker: память больше не пропускается с
> `TypeError`, shortlist строится, а shadow executor не получает неявный доступ
> ко всему корпусу. Регрессия: `normal_unscoped` в
> `tests/test_chat_evidence_application_service.py`.
> Windows release entrypoint теперь безопасно различает public и private
> branches: `main/release` обязаны fetch/pull exact remote ref, а чистая
> `codex/*` собирается из exact локального HEAD без публикации приватной ветки.
> Оба пути проверяют branch, commit и clean worktree до сборки.

> **0.28.0 chat profile studio:** четыре явных режима (`search`, `agent`,
> `estimator`, `engineer`) разрешаются в immutable prompt+skill+tools+policy
> snapshot. Factory Base удалить нельзя; пользовательские редакции и активная
> версия хранятся в MetaDB, а каждый chat session привязан к точной ревизии до
> явного применения новой активной версии. Legacy mode names и JSON prompt
> overrides поддерживаются только миграционным слоем. Профиль `estimator`
> использует общий native-RRF evidence flow и большую модель; специализированный
> `smeta_core` сохранён как неактивный совместимый модуль и не является chat-route.

> **0.27.77 ordinary smeta RAG:** отдельные видимые `Сметный проект` и chat
> `mode=smeta` сняты с product surface. `SMETA_NORMS_Index` — обычный явно
> выбираемый system dataset в общей named dense+bm25_sparse коллекции; Big Qwen
> получает его через тот же native-RRF evidence flow, что и проектные документы.
> Typed SQLite и legacy RIM state сохранены только как совместимый read-only
> источник/слой. FreeToken settings показывают configured и physical KV и
> синхронизируют loopback cache перед обычной RAG-генерацией.

> **0.27.76 capacity-aware FreeToken evidence:** ordinary RAG no longer caps
> FreeToken at four chunks or 5000 evidence characters. The prompt ceiling is
> derived from the GUI-owned token window with a generation reserve; the shared
> evidence assembler keeps native-RRF order while covering distinct documents
> first. Bounded session/working memory is packed before evidence so follow-up
> turns retain dialogue continuity. No domain terms, boosts, or file-name rules
> were added.

> **0.27.75 FreeToken streaming contract:** OpenAI-compatible SSE chunks may
> carry generated text in `delta.content`, `delta.reasoning`, or
> `delta.reasoning_content`. The shared transport parser normalizes all three;
> ordinary RAG and free-mode streams no longer report a false empty LLM answer
> when FreeToken serves `Qwen3.6-35B-A3B-NVFP4`. Provider/model selection and
> the model-owned answer remain unchanged.

> **0.27.74 general RAG contract:** ordinary chat retrieval now keeps the
> evidence returned by named dense+sparse native RRF when the optional
> cross-encoder reranker is disabled or unavailable. The Windows/runtime default
> is `RERANKER_ENABLED=false`; query embeddings remain on Ollama `bge-m3`, while
> Big Qwen receives the bounded evidence window and chooses any follow-up tools.
> `make ship` and `make ship-full` enforce this through a one-query
> `/api/rag/retrieve-debug` smoke: non-empty evidence, both Qdrant channels,
> native RRF fusion, and explicit reranker bypass. The old smeta-reranker A/B
> remains an opt-in diagnostic and no longer blocks a general LES release.
> A known divergent runtime file may be included only through the explicit
> `DEPLOY_FORCE_FILES='path ...'` ship parameter; the regular deploy still handles
> every classifier-approved file and writes the final stamp after that narrow copy.
> Candidate-dependent HTTP checks run only after deploy: the previous installed
> runtime cannot block its own fix through stale chat or diagnostics behavior.
> Native-RRF post-smoke uses the same bounded startup retry as the basic HTTP
> smoke; every attempt remains fail-closed on missing channels/evidence/bypass.

> **0.27.73 FSNB retrieval contract:** active clean-base identity снова совпадает
> с опубликованным индексом: `bge-m3`/Ollama. Retrieval-only probe проверяет
> известные нормы и отдельно маркирует неоднозначные stress-перефразировки;
> модель, reranker, каталог и `smeta_core` workflow в тест не входят.

> **0.27.72 FreeToken smeta transport:** document LSR now sends exactly one
> immutable source row per local FreeToken batch. Accepted rows keep the existing
> durable attachment checkpoint; FreeToken terminal serialization uses one forced
> `submit_estimate_mapping` tool because its server deliberately rejects
> constrained `response_format`. Agent tool turns reserve at most 1024 output
> tokens. Durable history remains complete, while inference receives the stable
> system/source prefix, latest tool exchange and authoritative typed working
> memory, so prompt+generation stays within FreeToken's 8253-token KV budget.
> Failed runs preserve the exact chat attachment.

> **0.27.34 boundary update:** `smeta/rim-dialog` keeps model ownership while a
> repeated, typed and unit-compatible semantic conflict is emitted as a
> calculated `model_batch_candidate` after one repair turn. Memory captures no
> such candidate and recalls smeta experience only after explicit confirmation.

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
| workbook-tools | Канонические `build_lsr_workbook` / `build_vor_workbook`: server-owned attachment, required idempotency, durable checkpoint, immutable artifact lineage и bounded result без filesystem path. Родителя revision выбирает код (`_packaging_parent`: explicit → session_lineage по `workflow_checkpoints.last_completed_revision` в границах одного `session_id` → first_revision), а не модель и не имя файла; источник решения публикуется как `tool_calls[].parent_revision_source`, а `DOCUMENT_LINEAGE_UNOWNED` не оставляет модулю права собирать `ArtifactRevisionRequest` с самодельным parent. Оба контракта context-bound и не выдаются обычным ToolHarness shortlist. Единый chat capability manifest одновременно определяет, что видит модель и какой callable исполняет tool. VOR использует built-in adapter; тонкий LSR adapter принимает выбранные моделью строки/шифры и operator `confirmed_data` в input schema без смены шифра, использует exact calculation/renderer и не запускает второго агента. Имя файла не берёт пользовательский запрос | `proxy/services/{workbook_tool_service,lsr_workbook_adapter_service,artifact_revision_service,workflow_checkpoint_service,bor_service,rim_lsr_trace_service,rim_trace_xlsx_service,lsr_source_coverage_service}.py`; `proxy/routers/{chat,artifacts}.py` | [ALGO-tool-harness](ALGO-tool-harness.md) | ✅ |
| smeta/model-quality | Воспроизводимый live Qwen↔Gemma A/B на одном canonical XLSX/PDF→ЛСР workflow: одинаковые prompt, corpus, tools, seed, limits и начальное состояние; per-row calculated/partial/missing, tool calls/repeats, **stage_latency** (catalog/search/read/bind/llm p50/p95), unit/volume/provenance integrity, hierarchical-route trace и реальный checkpoint/resume. `--resume-run` продолжает существующий run только после совпадения source SHA, model profiles и fixed contract. Главный сравнительный gate вместо golden/ranx. Профессиональная правильность — только по явному `les.smeta.qrels.v1` | `tools/smeta_model_quality_benchmark.py`; `tests/test_smeta_model_quality_benchmark.py` | [modules/smeta-core.md](modules/smeta-core.md) · [BACKLOG_RAG_EXCEL_PDF.md](BACKLOG_RAG_EXCEL_PDF.md) | ✅ |
| core/modules | лёгкий реестр профессиональных модулей LES: smeta, normcontrol, BIM/QTO, docs_review, procurement, contracts, project RAG; router выбирает модуль, но не решает предметную область | `les_module_service`, `active_state_service`, `scoped_rag_builder`, `skill_snippet_registry`, `tool_trace_policy` | [ALGO-routing.md](ALGO-routing.md) | ✅ |
| core/chat-evidence | application-граница model-owned evidence-first RAG: явный user scope либо typed system datasets роли → первый no-tools model call возвращает обычные поисковые строки → estimator исполняет exact queries через настраиваемую dedicated сметную dense+sparse RRF collection, остальные профили — через scoped общий RAG → по 6 карточек на запрос группируются только как `Qx.Hy`; заголовки, которые влезают в остаток окна, резервируются, leftover-запросы идут следующим техническим пакетом или честным omit → второй no-tools call той же модели возвращает обычный итоговый текст → механический reader собирает Markdown-таблицы, секционные блоки или обычные подписанные строки ответа без изменения решений → только затем код вызывает `build_lsr_workbook`. Пакетный sheet-pass сохраняет терминальные решения как БАП: без обязательного verifier и без заглушек при исчерпании; пустой поиск (`status=missing`) не рвёт пакет до таблицы строк; checkpoint/resume (`should_cancel` истинен при `paused`), `POST /api/chat/repack-lsr` и `POST /api/chat/patch-lsr-rows` не вызывают модель. `comparative_acceptance_variant=B0_DIRECT` отключает packet harness для живого baseline. Результат разделяет покрытие исходника, полноту норм, полноту цен и техническую готовность файла. Нет JSON-schema, native-tool selector/workbook loop, `status`, confirm/review и row-count cap; packaging failure не меняет model result. Неготовый сметный RRF не откатывается в смешанный `les_rag` | `proxy/services/chat_evidence_application_service.py`, `proxy/services/{context_governor,model_execution_preset,llm_transport_profile,model_research_tool,workbook_research_job,lsr_result_readiness,lsr_source_coverage}_service.py`, `proxy/routers/chat.py`, `retrieval_service`, `evidence_packet_service` | [ALGO-evidence-packet.md](ALGO-evidence-packet.md) · [ADR-15](ADR-15-model-rag-result.md) | ✅ |
| core/tool-harness | controlled registry/executor для инструментов: карта датасета, source search/read, PDF/Excel readers, bounded public web search и read-only filesystem. Model shortlist строится только из runtime-исполняемых контрактов: registry-запись сама по себе не делает context-bound tool доступным. В Agent restrictive shortlist `web_search` не вытесняется filesystem tools старого user-profile snapshot; модель по-прежнему сама выбирает вызовы и запросы. В grounded chat `ModelResearchToolService` исполняет `search_sources` тем же production native RRF и не позволяет модели расширить операторский dataset scope; общий call budget применяется ко всему research loop, затем финальный ответ модели сохраняется без rewrite | `proxy/services/{tool_contract_service,tool_registry_service,capability_broker_service,trusted_executor_service,tool_harness_service,model_research_tool_service,workbook_tool_service}.py`, `proxy/routers/tools.py`, `tools/les_tool_harness.py`, `routers/chat.py` | [ALGO-tool-harness.md](ALGO-tool-harness.md) · [CHAT_OPERATOR_CONTRACT.md](CHAT_OPERATOR_CONTRACT.md) | ✅ |
| core/public-provider-session | обязательный выбор локальной или BYOK-облачной модели после публичного ключа; API-ключ хранится только в process-memory vault с TTL, runtime изолирован `ContextVar`, общий `.env` не меняется | `sovushka/{auth,provider_setup,provider_session,state}.py`, `proxy/services/chat_provider_session_service.py`, `proxy/routers/chat.py`, `/provider-setup`, `/api/chat[/stream]` | [modules/public-provider-session.md](modules/public-provider-session.md) | ✅ |
| core/test-infrastructure | комплексная автоматизированная тестовая инфраструктура: unit, offline smoke, test runner, coverage и CI отчёты | `tools/test_runner.py`, `tests/test_smoke_offline.py`, `tests/test_unit_core_business.py`, `Makefile` | [TESTING_GUIDE.md](TESTING_GUIDE.md) · [TEST_INVENTORY.md](TEST_INVENTORY.md) | ✅ |
| core/runtime-config | GUI-first реестр runtime/env и фактических model/context-факторов: для preset/input/reserves/reasoning показывает человеческое `requested → effective · source`, restart и честный read-only/profile-clone путь; внешний Qdrant имеет отдельное человеческое имя и редактируемый HTTP(S)-адрес для local/LAN/VPS, а общий таймаут назначенной answer model виден как restart-bound фактор. Env сохраняет masked secrets, read-only bootstrap, `Danger` confirmation и recoverable atomic write. Advanced RAG policy хранится отдельно от env | `proxy/services/runtime_config_registry_service.py`, `proxy/services/rag_advanced_policy_service.py`, `proxy/routers/settings.py`, `proxy/routers/rag_advanced.py`, `sovushka/pages/diag.py` | [modules/sovushka-uikit.md](modules/sovushka-uikit.md) · [modules/chat-profiles.md](modules/chat-profiles.md) | ✅ |
| core/chat-profiles | Factory Base синхронизируется с текущим code contract при startup; пользовательские версии prompt/skill/profile остаются immutable. Четыре явных режима, tool allowlist, model/RAG policy, active revision и per-chat snapshot binding в MetaDB. Estimator Base явно привязывает system dataset role `smeta` и ровно `search_sources`, `read_source`, `build_lsr_workbook`, `build_vor_workbook`; это scope/capability, не скрытый сценарий или выбор нормы. Prompt ограничен 16 000, skill — 8 000 символов. Пользовательский snapshot меняется только явно; заводской binding получает актуальный Base-контракт при upgrade | `proxy/services/chat_profile_service.py`, `proxy/routers/profiles.py`, `proxy/services/profile_resolver.py`, `proxy/routers/chat.py`, `sovushka/pages/profiles.py` | [modules/chat-profiles.md](modules/chat-profiles.md) · [modules/sovushka-uikit.md](modules/sovushka-uikit.md) · [design](superpowers/specs/2026-08-24-chat-profile-studio-design.md) | ✅ |
| core/agent-foundation | Canonical 0.29 Agent Foundation завершён и проверен: structural gate, Registry, CapabilityBroker, TrustedExecutor и fail-closed ordinary-chat route; default `shadow` сохраняет legacy answer, рассматривает максимум один canonical call и не допускает persistence, `active` требует exact promotion receipt. Runtime presets, ContextGovernor и typed advisory memory подключены к ordinary-chat candidate; live model quality/promotion отдельно не заявлены | `tools/architecture_contract_gate.py`, `proxy/services/{tool_contract_service,tool_registry_service,capability_broker_service,trusted_executor_service,canonical_route_service,tool_harness_service,chat_evidence_application_service,runtime_config_registry_service}.py`, `proxy/routers/tools.py` | [ALGO-tool-harness.md](ALGO-tool-harness.md) · [ALGO-context-memory.md](ALGO-context-memory.md) · [current architecture](CURRENT_ARCHITECTURE.md) | ✅ |
| core/model-execution-presets | Фактическая requested/observed context capacity модели является total window; фабричные Qwen 9B/35B значения используются только как fallback. Если заданы оба источника, берётся безопасный минимум; generation/safety reserves вычитаются Governor ровно один раз. FreeToken default `35000` clamp'ится к `max_feasible_kv`. Effective/source виден в version API и GUI-first runtime registry; resolver не меняет route/backend | `proxy/services/model_execution_preset_service.py`, `proxy/services/llm_transport_profile_service.py`, `proxy/services/freetoken_cache_profile_service.py`, `proxy/services/version_service.py`, `proxy/services/runtime_config_registry_service.py`, `sovushka/pages/diag.py` | [modules/chat-profiles.md](modules/chat-profiles.md) · [ALGO-context-memory.md](ALGO-context-memory.md) | ✅ |
| core/context-governor | Единый budget-aware packer inference: после reserves и обязательных profile/request целиком упаковываются evidence/source map, затем tool exchange, checkpoint, working memory и dialogue. Omission возвращает IDs/cursor, required overflow блокирует model call; evidence packet trace хранит точный model-visible текст и SHA-256, не раскрывая память/profile | `proxy/services/context_governor_service.py`, `proxy/services/llm_transport_profile_service.py`, `proxy/services/chat_evidence_application_service.py` | [ALGO-context-memory.md](ALGO-context-memory.md) · [canonical design](superpowers/specs/2026-08-30-model-owned-evidence-first-rag-design.md) | ✅ |

## 1. Смета (ценообразование, 0 LLM в расчёте — ADR-11)

Текущая карта сметного режима — [SMETA_MECHANICS.md](SMETA_MECHANICS.md). Сквозной поток и эталон
(позиция = **12679.40**, `priced_partial` с дырой `11.1.03.01-0076`; смета 2× = **25358.80**; карточка
основной базы × книга `sankt-peterburg_2kv2026`) — [ALGO-smeta.md](ALGO-smeta.md).
**Скилл-плейбук (для агента и ЛЕС): [skills/smeta/SKILL.md](../skills/smeta/SKILL.md).**
Понятное описание живого модуля, его данных, потока и проблем —
**[SMETA_MODULE_EXPLAINED.md](SMETA_MODULE_EXPLAINED.md)**.

С 0.24.16 сметный document-agent выбирается отдельно от модели обычного чата. Локальный transport
делает один видимый model request на ход без скрытых required-tool retries; резервная модель
настраивается отдельно и может быть отключена для чистого сравнительного прогона Gemma.

**0.24.42 / build 463:** smeta/core получил модельную иерархию `browse_norm_catalog → scoped
search_norms_batch → read_norms_batch`: полный каталог текущей typed-базы не зашит в skill и не
обрезается привычным top-10, а семейства/сборники выбирает модель. Search-кандидаты сразу показывают
`source_ref` и состав работ. Неполный bind-evidence возвращается той же модели на terminal recovery.
Live Qwen `vor-0013` прошёл `5 семейств → 47 сборников ГЭСН → сборник 15 → search/read → близкий
аналог`; прежний сборник 34 не выбран. Это регрессия одной строки, не полный golden-гейт.

**0.24.43 / build 464:** model-visible search card дополнена typed identity, редакцией/сборником,
совместимостью измерителя, ресурсным профилем и `matched_query`; чтение с `include_resources=true`
больше не обрезает ресурсы после 30. Каждый bind хранит model-owned `candidate_evaluations`, а при
нескольких открытых карточках сравнивает выбранную минимум с одной альтернативой. Global review
получает компактную карту карточек и перечитывает полный disputed evidence только через tool.
`smeta_mapping_quality --prepare-from` создаёт очередь экспертной разметки, не принимая предложение
модели за эталон.

**ADR-13 / 0.24.45 — исторический/экспериментальный контур:** `SmetaSession`,
`smeta_scope_plan_v1`, R1→R2 и `mapping_locked` заменены ADR-15 для активного
продуктового пути и не могут быть обязательной обвязкой между моделью и RAG.

**0.24.46 / build 467:** принят operational-контур публичного PR: document Qwen `qwen3.5:9b`
работает с `temperature=0`, фиксируемым `LES_SMETA_DOCUMENT_SEED` и локальным batch=5; запросы и
tool-items получают стабильный transport-порядок, seed записывается в trace. Текущий `session_id`
сохраняется в NiceGUI user storage, recovered SSE попадает в history, закрытие вкладки не обрывает
серверное завершение сметы. Предметный self-check PR заменён каноническим immutable R2
`global_review`, поэтому смена нормы не наследует поля R1.

**0.24.47 / build 468:** тестовый контур разделён на hermetic unit, поведенческие integration,
smoke фактических active-артефактов и live runtime. Сметный batch больше не отключает reranker при
пяти и более строках; ошибка cross-encoder видна как `rerank_status`. После model-selected
`table_codes` код возвращает полную официальную таблицу по порядку кодов без top-k. Живой A/B smoke
блокирует ship, если Qdrant/RRF не довёл кандидатов до reranker.

**0.27.71 / build 578:** локальный FreeToken/Big Qwen использует тот же живой document workflow,
но с `batch_size=1`: один полный исходный ряд на model transport, durable checkpoint до следующего
ряда и дословный resume оставшихся `work_id`. Terminal mapping передаётся forced function-call
`submit_estimate_mapping`; `response_format` для FreeToken не используется. Отдельный mini-Qwen,
карточный orchestrator и дополнительный reranker в сметный маршрут не добавлены.

С 0.24.0.382 старый поштучный orchestrator физически удалён. Один model-owned batch-диалог вызывает
`search_norms_batch`, `read_norms_batch`, затем `submit_lsr_mapping`; после этого код один раз считает
и собирает XLSX. С 0.24.23 полный `skills/smeta/SKILL.md` является единственным профессиональным
prompt: каждый `bind` содержит полный technology/overlap evidence, `unbound` — проверяемый search/read
trace, а ресурсное действие — явный `basis_ref`. Это формальный гейт полноты, а не кодовый выбор нормы.

> **0.27.2 intake correction:** `smeta/rim-dialog` сохраняет служебный
> `visible_row_number` в audit/source trace, но не считает его смысловым
> assumption/blocker; валидность строки определяется только реальными
> допущениями извлечения.

| Суб-модуль | Назначение | Точки входа | Док | Статус |
|---|---|---|---|---|
| smeta/core | Исторический/экспериментальный PDF/XLSX→ЛСР contour (`document_workflow`, catalog/search/read/submit, review/checkpoint loops). Не является активным ядром чата и не определяет production-поведение «Сметчика». Сохранён до отдельного reachability/удаления; текущая архитектура находится в `core/chat-evidence`, а расчёт/рендер завершённого model result — в тонком workbook adapter | `proxy/smeta_core/**`, `proxy/services/{smeta_agent_runner_service,smeta_chat_application_service,smeta_chat_adapter_service}.py`, экспериментальные RIM/tool consumers | [modules/smeta-core.md](modules/smeta-core.md) | 🗄 |
| smeta/public-sync | Публичный релиз 0.27.64: XLSX `Ко-во` под длинной шапкой, однократный evidence-repair, terminal candidate-draft, scoped local Qwen и soft-continue malformed tool XML; локальная rerank-политика остаётся operator-owned | `proxy/smeta_core/{source_intake,document_workflow,norm_browser}.py`, `proxy/services/{smeta_chat_application_service,smeta_chat_adapter_service}.py`, `tools/smeta_stability_ab_run.py` | [modules/smeta-core.md](modules/smeta-core.md) | ✅ |
| smeta/ks-forms | Заполненные КС-2/КС-3 из текущей ЛСР выбранного проекта создаются только как явный черновик, не факт выполнения; КС-6а читает только confirmed журнал того же `project_id`. Глобального fallback к «последней смете» нет. | `proxy/services/{ks_forms_service,ks_forms_chat_service,ks2_xlsx_render}.py`; `proxy/routers/{chat,forms}.py`; `tools/les_mcp_server.py`; `config/forms/{ks2,ks3,ks6a}.yaml` | [modules/smeta-core.md](modules/smeta-core.md) | ✅ |
| memory_core | Изолированная project-scoped advisory-память фактов и трасс плюс общий typed projection существующих chat/notebook/notes/MemoryPort stores. Projection выдаёт bounded addressable checkpoint/working-memory items, решения только с revision ref, всегда `is_evidence=false`; legacy memory views остаются рабочими adapters. `NullMemoryPort` сохраняет default-off; память не выбирает профессиональное решение и не пересобирает notebook. | `proxy/memory_core/*`; `proxy/services/{memory_port,memory_runtime_service,memory_worker_service,memory_rag_adapter,typed_memory_projection_service,context_memory_service,memory_service}.py`; `proxy/routers/memory.py`; `sovushka/pages/diag.py` | [ALGO-context-memory.md](ALGO-context-memory.md) · [ADR-14](ADR-14-memory-core-v1.md) · [modules/memory-core.md](modules/memory-core.md) | ✅ |
| smeta/rim-dialog | persistent диалоговая РИМ-сессия: XLSX/CSV intake, ВОР, один технический вопрос с вариантами, строгий model-selected маршрут `browse root → continue/ask/broaden/unbound → family → collection → section → table → search → read → submit`. Одинаковая фаза нескольких строк исполняется одним batch tool call; durable checkpoint пишется после каждого tool result и каждой принятой строки. Проверенный маршрут доступен как evidence-cache только через явный model call, без наследования нормы/applicability. Global review работает по connected conflict groups и сохраняет полный terminal mapping. Read-only progress-проекция показывает authoritative resume-budget/evidence status. Typed FSNB-узлы содержат `node_id/parent_id/node_type/cipher/source_ref/edition`; код проверяет только смежность, реально показанное evidence и model self-conflict, не выбирая применимость. Lifetime evidence остаётся в аудите, каждый resume получает bounded execution slice. `bind` разрешён schema только по открытым typed-карточкам с совместимой единицей. Phase-scoped skill/tool schemas не грузят Qwen всем workflow сразу. Session API проецирует один `next_step`; сохранённый `mapping_selected|candidates_ready` после вопроса возобновляется через existing global review и canonical draft calculation без повторного поиска всех строк. Далее immutable mapping/global review/two user locks, authored scenarios, canonical РИМ-расчёт, typed requirements и audit/XLSX. Отдельной NiceGUI-вкладки нет: пользовательский маршрут идёт через универсального агента, API остаётся инструментальным контрактом | `config/domain/smeta_normative_catalog.json`, `proxy/smeta_core/{norm_browser,rim_session,document_workflow}.py`, `proxy/services/{rim_knowledge_service,rim_agent_action_service,rim_agent_turn_service,rim_next_step_service,rim_mapping_progress_service,rim_mapping_review_service,rim_mapping_xlsx_service,rim_scenario_service,rim_session_xlsx_service}.py`, `proxy/routers/rim.py`; `/api/rim/sessions/*`, `GET /mapping/progress` | [modules/rim-dialog-session.md](modules/rim-dialog-session.md) | ✅ |
| smeta/mechanics | предметная карта ВОР/РИМ/ГЭСН/ФГИС/КАЦ и границы model↔code; верхняя PDF→ЛСР схема актуализирована, нижние direct/harness-слои требуют сжатия после удаления legacy маршрутов | `proxy/smeta_core`, `chat.py`, `smeta_user_message_service`, legacy `estimate_harness_service`, `quantity_trace_service`, `lsr_assembly_service` | [SMETA_MECHANICS.md](SMETA_MECHANICS.md) | 🟡 |
| smeta/system-dataset | `SMETA_NORMS_Index` публикует каждую trusted SQLite-норму как обычную RAG-карточку в общей named dense+bm25_sparse коллекции и доступен через явный dataset scope; `SMETA_SERVICE_Index` остаётся служебной навигацией. Отдельный smeta-turn для чтения норм не требуется | `system_dataset_service`, `tools/publish_smeta_norm_dataset.py`, `qdrant_adapter.MetaDB`, `retrieval_service`; datasets `SMETA_NORMS_Index`, `SMETA_SERVICE_Index`, `SMETA_RU_NORM_*` | [CODE_MAP.md](CODE_MAP.md) | ✅ |
| smeta (поток) | объём ВОР → … → ВСЕГО; сметные lookup/calculation tools без финального visible-answer из кода | `smeta_chat_service`, `deterministic_policy_service` | [ALGO-smeta.md](ALGO-smeta.md) | ✅ |
| smeta/lsr | сборка позиции→Всего→свод; РИМ-трасса (графы 2-12); XLSX форма **ЛСР РИМ**. ADR-15 adapter берёт явный шифр модели в exact lookup без независимого `EXACT_VERIFIED`; роли строк и `work_row`; исходное количество отдельно от расчётного; конверсия только с источником; `MISSING`/единицы/цена остаются gaps; названный `NEEDS_RESEARCH` считается как аналог и не делает `priced_final`; отсутствие цены не уничтожает норму | `lsr_assembly_service`, `rim_lsr_trace_service`, `rim_trace_xlsx_service`, `lsr_workbook_adapter_service`, `lsr_source_coverage_service`, `fsem_machinist_service`; `POST /api/lsr/{assemble,rim-trace,lsr-trace}[/export]`; MCP `les_lsr_assemble` | [ALGO-lsr-assembly.md](ALGO-lsr-assembly.md) | ✅ |
| smeta/gesn | норма ГЭСН → ресурсы (расход×объём); canonical typed SQLite, raw/unified только source/staging. Обновление строит SQLite+manifest/integrity и exact-SHA dense+sparse RAG как sibling-generation; только после live readiness одна транзакция переключает файлы и Qdrant alias, а rollback возвращает прежнюю пару. Startup reconciliation проверяет реальный alias, активирует сохранённую exact-SHA generation либо запускает фоновую sibling-сборку; readiness остаётся read-only и показывает рассогласование в GUI. Windows clean install получает immutable source/base/FSEM payload и default regional pricebook с SHA/schema/count gates; существующий state не перезаписывается | `gesn_service`, `gesn_update_service`, `proxy/services/{smeta_generation_reconciliation,rag_readiness}_service.py`, `tools/{gesn_update_from_fgis,gesn_unify_base,build_smeta_structured_base,smeta_generation_coordinator,rebuild_active_smeta_rag,activate_smeta_rag_generation,smeta_release_baseline}.py`; `config/domain/smeta_base_active.json`; Make `smeta-base*`; Windows bootstrap/release smoke | [ALGO-gesn.md](ALGO-gesn.md) · [modules/smeta-core.md](modules/smeta-core.md) | ✅ |
| smeta/fgis | цена ресурса по коду из «Сплит-формы» ФГИС ЦС; единый операторский updater получает публичный каталог, последнюю книгу каждой ценовой зоны и полный ГЭСН pipeline; UI показывает job status, heartbeat, текущий регион/сборник и ETA; visible-книги управляются `pricebook_manifest.json` | `fgis_price_service`, `fgis_update_service`, `process_status`, `tools/{fgis_full_update,gesn_update_from_fgis,gesn_bulk_import}.py`; `/api/service-sources/fgis/update[/status]`; `sovushka/pages/instrumenty.py`; MCP `les_price_lookup` | [ALGO-fgis-price.md](ALGO-fgis-price.md) | ✅ |
| smeta/artifact | оформление сметных таблиц в отдельный Markdown-artifact и выгрузку XLSX/CSV: извлекает уже написанные моделью ВОР/стоимость/развилки, считает видимые суммы, делает `lsr_rim_display_form_v1` отдельным способом выдачи сметного артефакта, добавляет Markdown/XLSX ЛСР РИМ в 12-графной форме Приложения №3/421-пр и отдельные источники, а исходные таблицы оставляет расшифровкой; живой чат копит terminal-строки по мере готовности, а на финале сверяет таблицу с авторитетным `rim_trace`, поэтому строки без отдельного stream-события не исчезают; внутренние фазы/ошибки и resource-guard локализуются только на UI-границе; на stage `norm_candidates` строит рабочую таблицу `ВОР ↔ кандидаты ГЭСН` из executed `search_norm` trace и отдаёт её даже при пустом финальном LLM-тексте, а следующий ход “деньги по ним” считает по candidates текущего/предыдущего trace; если построен проверенный `lsr_rim_trace_form_v1`, visible answer показывает именно расчётную РИМ-ЛСР с ценами/книгой/статусом, без конкурирующей модельной placeholder-таблицы; legacy compact только через `LES_SMETA_COMPACT_CHAT_TABLES=1`; не выбирает работы, нормы или ставки | `smeta_artifact_service`, `chat.py` payload `artifact`, `sovushka/pages/chat.py`, `/api/smeta-artifacts/download` | [SMETA_MECHANICS.md](SMETA_MECHANICS.md) | ✅ |
| smeta/kac | конъюнктурный анализ цен (≥3 КП на материал); web-discovery принимает только model-selected exact product query, сильный артикул и три разных supplier domains, иначе цена остаётся missing. Самостоятельный HTTP API удалён как неиспользуемый; живой внешний вход — MCP | `kac_service`, `kac_web_service`; MCP `les_kac` | [ALGO-kac.md](ALGO-kac.md) | ✅ |
| smeta/stesn | коэффициент стеснённости (k к ОЗП/ЭМ) | `stesnennost_service`; `/api/lsr/stesnennost/*`; MCP `les_stesnennost` | [ALGO-stesnennost.md](ALGO-stesnennost.md) | ✅ |
| smeta/object | мутное ТЗ «дай смету на …» → model-first декомпозиция: модель сама раскладывает объект, харнесс даёт `search_norm`/`add_position`; при приложенной таблице direct Smeta отдаёт модели само вложение, skill и scoped RAG без промежуточного табличного калькулятора; если это спецификация, модель сначала собирает мост specification→BOR: поставка/работы/parent-child/quantity trace, и только затем ведёт к нормам и смете; `search_norm` использует typed SQLite-light `smeta_norm_store_v5` как широкий индекс норм с норм-карточками и навигацией (семья/элемент/действие/условия/ресурсы/provenance/`model_card`/`navigation`/`nearby_norms`/decision checklist), ранжирует редкие технические совпадения поверх общих FTS-хитов и видит overlay `ГЭСНм10` для СКС/ВОЛС; общий `candidate_selection_v1`, код проверяет нормы/единицы/объёмы и считает только прошедшие gates; прямые объёмы идут как `quantity_candidates`/`quantity_trace` с provenance, а статус ГЭСН/ФГИС/КАЦ/коэффициентов попадает в результат | `estimate_harness_service`, `smeta_norm_store`, `candidate_selection_service`, `estimate_math_service`, `quantity_trace_service`, `nr_sp_service`, `evidence_contract`, `tools/gesn_fgis_overlay_import.py`; готовые объектные составы удалены | [ALGO-object-estimate.md](ALGO-object-estimate.md) 🟡 · [ALGO-gesn.md](ALGO-gesn.md) ✅ | 🟡 |
| smeta/ontology | доменные понятия (ВОР/КАЦ/ЛСР/КС) | `smeta_ontology_service`; MCP `les_glossary` | [ALGO-smeta-ontology.md](ALGO-smeta-ontology.md) ✅ · [smeta_ontology.md](smeta_ontology.md) ✅ (генерится) | ✅ |
| smeta/bor | спецификация Ф9 → ВОР работ; workbook VOR adapter читает все табличные листы и сохраняет адреса строк; формулы объёма без кэша остаются явным блокером; MCP сохраняется | `spec_to_bor_service`, `bor_service`, `workbook_tool_service`; MCP `les_bor`, `les_spec_to_bor` | [ALGO-spec-to-bor.md](ALGO-spec-to-bor.md) | ✅ |
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
| rag/core | поток чата, retrieval/evidence/research-loop и честные статусы; общий `les_rag` принимает только exact-manifest пользовательских документов и исключает module-owned projections. `ARTEL_Index` типизирован как внешняя `system/artel` интеграция и не создаётся bootstrap'ом LES. Contract-clean sibling строится resumable supervised job, а SHA-256 scope manifest проверяется на build/resume/readiness до полного live RRF gate. Legion supervisor принимает явный Ollama profile; legacy physical `les_rag` переводится в alias только после snapshot/recovery archive, exact-count gate и немедленного безопасного navigation-count reconcile MetaDB | `retrieval_service`, `notebook_study_service`, `saferag_service`, `evidence_packet_service`, `runtime_dispatcher`; `backend/smart_index.py`; `routers/chat.py`; `tools/rag_scope_manifest.py`; `tools/build_rag_contract_sibling.py`; `tools/rag_generation_supervisor.py`; `tools/rag_rrf_readiness.py`; `tools/activate_qdrant_generation.py` | [CODE_MAP.md](CODE_MAP.md) · [ALGO-rag-best-practices.md](ALGO-rag-best-practices.md) · [RAG_TEST_PROGRAM_AUDIT.md](RAG_TEST_PROGRAM_AUDIT.md) | ✅ |
| rag/evidence-packet | общий контракт normal-RAG: source-diverse bounded context, table header, source version/locator/retrieval features; модель видит те же `Источник N`, что UI, а post-generation check отмечает missing/invalid labels | `evidence_packet_service`, `saferag_service`, `routers/chat.py` payload `evidence_packet`, `retrieval_trace.evidence_packet/citation_check` | [ALGO-evidence-packet.md](ALGO-evidence-packet.md) | ✅ |
| rag/answer-render | видимый слой evidence в Совушке: conversation-first чат с progressive disclosure, копирование с источниками и artifact `Источники ответа`; канонический Locia-like UI kit ограничивает новый UI семью общими примитивами, едиными tokens и WCAG-проверками. Build 613 задаёт 16/14/12 px typography, 44 px hit target и 184 px desktop rail; mobile использует нижнюю навигацию с safe-area и одно меню вторичных действий. Composer оставляет вложение, один selector режима, настройки и отправку; файл добавляется через три понятные задачи и русский control. Студия сохраняется в коде/API, но до продуктовой приёмки скрыта за disabled-заглушкой `Студия · скоро`, а старый direct URL возвращает в чат. Общий `acronym_identity` показывает фирменный зелёный акроним и каноническую расшифровку, которую пользователь может скрыть. Общие controls/status/evidence/feedback используются в чате, документах, почте, истории, В.О.Л.К. и оболочке Qdrant visualizer; общий `select_field` исключает локальную геометрию выпадающих полей. Конфигурация показывает один паспорт готовности и вертикальные контуры; «Датасеты» — компактный паспорт корпуса и единый реестр наборов. История — читаемый список диалогов, В.О.Л.К. — адаптивный реестр ключей вместо таблицы, Qdrant canvas — светлая зелёно-графитовая тема с доступным iframe. Документы ведут по цепочке dataset→files→sticky «Спросить в чате», почта показывает индекс/spool и передаёт exact письмо в чат; обязательный reranker не имеет пользовательского выключателя и не может быть отключён старым API-клиентом; машинные статусы локализуются на границе UI и не выходят в операторские подписи; технический trace свёрнут; Build 814 добавляет в карточку готовности ЛСР вертикальный блок «Выберите регион и уровень цен» для неразрешённой ценовой базы: запрошенная база, фактически подставленная книга с точным идентификатором и русской расшифровкой региона и квартала, переведённые противоречия «регион / период цен», явный отказ применять отсутствующий квартал и список реально доступных локальных книг (`fgis_price_service.available_pricebooks()`); выбор оператора вставляется обычной формулировкой пересчёта в поле ввода — без нового API, без нового примитива, без переменных окружения и без изменения model answer. Build 817: сам блок не менялся; чат-side проекция истории начала переносить `price_basis` / `price_gaps` / `norm_conflicts`, без которых на маршруте рабочей книги `dimensions.prices.basis` оставался пустым и пузырик не открывался (ADR-16 § 7, gate `BASIS_QUESTIONS_NOT_CARRIED`) | `sovushka/uikit/{tokens,states,components}.py`, `sovushka/styles.py`, `sovushka/answer_render.py`, `sovushka/pages/{chat,documents,mail,history,volk,diag,samovar}.py`, `sovushka/components/header.py`, `sovushka_ng.py`, `qdrant_visualizer/index.html`; `skills/sovushka-ui/{SKILL.md,references/review-checklist.md}`; tests `test_sovushka_uikit.py`, `test_answer_render_v16.py`, `test_static_assets.py`, `test_sovushka_chat.py` | [modules/sovushka-uikit.md](modules/sovushka-uikit.md) · [modules/file-viewer.md](modules/file-viewer.md) | ✅ |

**0.30.44 / build 684:** model-RAG query/result boundary больше не имеет
legacy JSON, regex-разбора ответа или language-driven выбора workbook. Только
обычные строки запросов Qwen, `Qx.Hy` evidence и однозначная итоговая таблица
либо запись с явно подписанными полями;
нечитаемая структура остаётся видимым ответом без синтетического XLSX.
Artifact/UI сохраняют все workbook-файлы, безопасное UTF-8 имя и время
запроса/ответа. Точки входа: `chat_evidence_application_service.py`,
`workbook_tool_service.py`, `routers/artifacts.py`, `sovushka/pages/chat.py`,
`sovushka/answer_render.py`, `sovushka/uikit/tokens.py`,
`tools/architecture_contract_gate.py`; contract tests — соответствующие
`test_chat_evidence_application_service.py`, `test_workbook_*`,
`test_artifacts_router.py`, `test_sovushka_chat.py`,
`test_architecture_contract_gate.py`. ✅

**0.30.45 / build 685:** безопасный model-result decoder принимает проверенный
вариант заголовков и пустых/дробных числовых полей из рабочего контура Максима,
не используя regex и не обрезая лишние клетки. Offline contract покрывает
совместимость, но статус кандидата остаётся pending до отдельного живого
Qwen→RAG→XLSX прогона. ✅ code / ⏳ live

**0.29.0 / build 614:** `ui/pwa-shell` публикует manifest, root-scoped worker и
offline draft surface для того же NiceGUI frontend. Cache allowlist содержит
только offline HTML и общий Tauri icon; API, streams, documents/files,
cross-origin и non-GET не кэшируются и не переигрываются. Точки входа:
`frontend/pwa/{manifest.webmanifest,service-worker.js,offline.html}`,
`sovushka_ng.py`; contract: `tests/test_sovushka_pwa.py`.

**0.29.0 / build 616:** `rag/answer-render` и `rag/document-explorer` имеют один
production-вход `Данные`: `sovushka/pages/data_workspace.py` переключает
role-aware каталог `samovar.py` и focused detail `documents.py` по exact
`dataset_id`; старые `documents|datasets` routes канонизируются в `data` с
сохранением query-параметров. Mail collector/dataset/API сохранены без отдельной
кнопки; Studio и CAD/BIM представлены disabled-заглушками. Обычный пользователь
не получает mutation controls. Контракты:
`tests/test_sovushka_{data_workspace,samovar,documents,uikit}.py`,
`tests/test_static_assets.py`, `tests/test_outlook_mail_poller.py`.

**0.29.0 / build 617:** добавлен общий `artifacts/immutable-revisions`:
`ArtifactRevisionStore` хранит append-only XLSX revisions с SHA-256, размером,
parent lineage и bounded provenance, публикует файл через temporary sibling +
atomic replace и никогда не переиспользует revision path. Авторизованные
`GET /api/artifacts/{revision_id}`, `/download` и
`/{artifact_id}/revisions` проверяют identity/hash и не раскрывают filesystem
paths. Точки входа: `proxy/services/artifact_revision_service.py`,
`proxy/routers/artifacts.py`, `proxy/app.py`; тесты
`test_artifact_revision_service.py`, `test_artifacts_router.py`. ✅

**0.29.0 / build 618:** `workflows/durable-checkpoint` связывает idempotency key
с session/tool, неизменяемыми attachment ID+SHA-256, canonical args hash и
model-decision revision. Повтор продолжает последний bounded progress; identity
drift fail-closed, completion хранит exact artifact revision. Точки входа:
`proxy/services/workflow_checkpoint_service.py`, существующий
`chat_attachment_service.py`; тесты `test_workflow_checkpoint_service.py`,
`test_chat_attachment_service.py`. ✅

**0.29.0 / build 619:** `tools/workbook-contracts` регистрирует только
`build_lsr_workbook` и `build_vor_workbook` как provider-neutral draft tools с
required idempotency и immutable-artifact provenance. Schema-only проекции
OpenAI/OpenAI-compatible/Ollama/MCP сохраняют name/version/effect/schema без
handler. Только новые factory estimator seeds получают allowlist; active
revisions/session bindings не меняются. Точки входа:
`workbook_tool_service.py`, `tool_provider_projection_service.py`,
`tool_harness_service.py`, `chat_profile_service.py`; тесты
`test_workbook_tool_contracts.py`, `test_tool_provider_projection_service.py`. ✅

**0.29.0 / build 621:** `rag/answer-render` и `tools/workbook-contracts`
соединены в ordinary chat: attachment-aware Broker выдаёт draft contract,
Trusted Executor исполняет один model call, `tool_progress` несёт checkpoint
identity, а complete immutable revision сохраняется в history и существующей
file card. После progress UI не запускает duplicate `/api/chat`. Точки входа:
`proxy/routers/chat.py::_execute_chat_workbook_tool`,
`chat_evidence_application_service.harvest_workbook_tool_result`,
`sovushka/state.py::should_retry_unstreamed_chat`; тесты
`test_{capability_broker_service,chat_evidence_application_service,chat_stream_w51,sovushka_chat}.py`. ✅

**0.27.67 / build 574:** `rag/answer-render` на каждом terminal-событии
`smeta_row` обновляет один черновой Markdown-артефакт с уже готовыми строками.
Это UI-проекция существующего stream/checkpoint-контракта: сметное ядро, выбор
норм, расчёт и финальный XLSX не изменены.

**0.27.66 / build 573:** `rag/answer-render` теперь использует стабильный
`source_map.doc_id`: строки источников кликабельны, PDF открывается на точной странице,
а вторичная кнопка собирает те же ссылки и цитаты в единый артефакт «Источники ответа».
`rag/document-explorer` добавляет guarded `GET /api/documents/by-id/{doc_id}/raw` и
`GET /api/documents/by-id/{doc_id}/viewer` для office-preview;
legacy-история без `source_map` сохраняет прежний path fallback.

**0.27.39 / build 556:** рабочие tab-panel переключаются без искусственного
slide-transition; Самовар принимает вставленный абсолютный путь и выводит имя
конечной папки по умолчанию, а «Открыть файлы» deep-link-ом ведёт в
Документы/Л.И.С.Т. с exact `dataset_id`. Служебная загрузка файла больше не
показывает пустой счётчик `0.0 B / 0%`; UI и visualizer слушают только loopback,
не вызывая Windows Firewall prompt.
| rag/file-viewer | единый локальный read-only viewer источников в GUI: PDF page/zoom/bbox через PyMuPDF; DOCX paragraphs/tables; XLSX/XLSM sheets/rows/formulas; PPTX slide text; EML, CSV/TSV, text и images. Все пути проходят allowlisted `RAG_Content`/external-root guard, HTML экранируется, originals не меняются; legacy DOC/XLS честно остаются только raw | `file_viewer_service`, `pdf_viewer_service`, `pdf_contour_service.render_page_preview`, `routers/files.py`; `GET /api/rag/file/viewer`, `/pdf-info`, `/pdf-preview`; tests `test_file_viewer_service.py`, `test_files_router_w181.py`, `test_answer_render_v16.py`, `test_static_assets.py` | [modules/file-viewer.md](modules/file-viewer.md) · [modules/pdf-contour.md](modules/pdf-contour.md) | ✅ |
| rag/search-skill | рабочий контракт инженерного RAG-поиска: модель связывает источники и формулирует вывод, код только ищет/ранжирует/считает таблицы/даёт trace; неполный поиск не превращается в отрицательный факт; нормативный вопрос ведётся маршрутом `норма → пункт → вывод`, а развилки «требуется/не требуется» требуют обе стороны нормы | `prompt_registry_service.rag_search_role_pack`; [skills/rag_search/SKILL.md](../skills/rag_search/SKILL.md); tests `test_rag_normcontrol_skill_contract.py` | [CODE_MAP.md](CODE_MAP.md) | ✅ |
| rag/routing | выбор контура: ProfileResolver → evidence application; doc_type классификация в `backend/document_router.py` (`CONTRACT`, `ACT_GENERAL`, `ADDENDUM`, `INVOICE_BILL`, `TZ_TOR`, `LETTER`, `PASSPORT_CERT`, `DRAWING`, `KS2`, `AOSR`, `SMETA`, `SPEC`, `NORMATIVE`); model-owned loop выбирает read-only tools, а при server-owned attachment и активном workbook profile — ровно один canonical draft tool | `profile_resolver`, `chat_evidence_application_service`, `query_router`, `scope_service`, `answer_contract_service`, `workflow_plan_service`, `backend/document_router.py`, `routers/chat.py` | [ALGO-routing.md](ALGO-routing.md) ✅ · [ALGO-workflow-plan.md](ALGO-workflow-plan.md) ✅ | ✅ |
| rag/retrieval | production contract v3: deterministic hierarchy `navigation|evidence`; global evidence native RRF всегда сохраняется, navigation RRF только строит descendant filter, descendant evidence проходит второй native RRF. Optional RAPTOR публикует navigation-only summary tree в отдельной generation-bound collection и спускается только к exact leaf evidence; optional ColBERT хранит token vectors только в contract-clean sibling generation и выполняет MaxSim. Затем evidence-only fusion идёт в общий rerank и parent/context expansion. Navigation/summary nodes запрещены в citations. Exact readers отдельно. Все optional-стадии имеют GUI-owned policy, preflight, progress, timeout/circuit breaker и request trace; runtime не дополняется в месте | `backend/{rag_hierarchy,raptor_tree,raptor_publication_worker,raptor_qdrant_store,raptor_summarizer,colbert_late_interaction}.py`, `backend/qdrant_adapter.py`, `proxy/services/{retrieval_service,raptor_publication_service,colbert_generation_service,rag_advanced_policy_service,rag_advanced_preflight_service,rag_pipeline_status_service}.py`, `proxy/routers/rag_advanced.py`, `tools/{rag_rrf_readiness,rag_advanced_synthetic_benchmark}.py`; tests `test_{raptor_*,colbert_*,rag_advanced_*,rag_rrf_readiness,retrieval_service}.py` | [ADR-12-typed-retrieval.md](ADR-12-typed-retrieval.md) · [ALGO-rag-best-practices.md](ALGO-rag-best-practices.md) | ✅ |
| rag/catalog-integrity | единый durable-контур MetaDB↔Qdrant↔lexical↔storage: startup guard выявляет orphan dataset payload и аддитивно восстанавливает каталог/FTS; sibling hierarchy delta в legacy `chunk_count` исправляется только metadata-only при exact source/delta/projection proof. Удаление fail-closed требует SQLite backup, Qdrant snapshot, exact pre/post count и recovery quarantine. Прерванные состояния и due-retryable `ERROR` автоматически возвращаются в очередь; `SKIPPED`, retryable и terminal имеют разные disposition/stable code. Startup bounded repair requeue только allowlisted исправленные systemic-коды, не более GUI-visible `RAG_BOUNDED_REPAIR_MAX_FILES`, только пользовательские датасеты и никогда успешные документы. Health/Самовар показывают skipped/retryable/terminal, следующий retry, причины и последний bounded repair. Sibling-generation имеет single-run lock и fail-closed self-migration guard | `backend/qdrant_adapter.py`, `proxy/app.py`, `proxy/services/{dataset_deletion_service,rag_catalog_guard_service,rag_catalog_recovery_service,rag_pipeline_status_service}.py`, `proxy/routers/datasets.py`, `tools/{recover_orphan_rag_catalog,rag_generation_supervisor,build_rag_contract_sibling,basic_function_smoke}.py`, `sovushka/pages/{diag,samovar}.py`; tests `test_{dataset_deletion_service,rag_catalog_guard_service,rag_catalog_recovery_service,rag_pipeline_status_service,parse_resume,rag_generation_supervisor,basic_function_smoke}.py` | [CODE_MAP.md](CODE_MAP.md) · [modules/sovushka-uikit.md](modules/sovushka-uikit.md) | ✅ |
| rag/document-explorer | Л.И.С.Т. — read-only Document Explorer поверх пользовательского RAG. Рабочая вкладка «Документы» показывает выбор датасета/файла, фактически извлечённые фрагменты и кнопку системного открытия оригинала (`native_open_service`, Windows `os.startfile`/cmd start, macOS `open`, Linux `xdg-open`); технические и офисные паспорта (`pdf_contour_service`, `office_passport_service`), карта, PDF-контур и index-quality остаются backend/operator API. Qdrant/LES хранит проверяемые фрагменты и не генерирует ответ. Старые MetaDB без `lexical_chunks[_fts]` получают additive schema migration без reindex | `document_explorer_service`, `native_open_service`, `office_passport_service`, `pdf_contour_service`, `lexical_index_service`, `backend/qdrant_adapter.py`, `routers/documents.py`, `sovushka/pages/documents.py`, `sovushka/styles.py`; endpoints `GET /api/documents/datasets/{id}/quality`, `GET /api/documents/by-id/{doc_id}/chunks`, `GET /api/rag/datasets/{id}/integrity`, `POST /api/documents/by-id/{doc_id}/open-native`, `POST /api/documents/open-native-by-ref`; tests `test_document_explorer_service.py`, `test_native_open_service.py`, `test_office_passport_service.py`, `test_pdf_contour_service.py`, `test_dataset_integrity.py`, `test_static_assets.py` | [CODE_MAP.md](CODE_MAP.md) · [modules/pdf-contour.md](modules/pdf-contour.md) · [modules/file-viewer.md](modules/file-viewer.md) | ✅ |
| rag/list-office-studio | Самостоятельная вкладка «Студия» ведёт по схеме датасет → том/папка → явно выбранные файлы-основания → шаблон/объект → поля → review → immutable draft. Л.Е.С. через typed `office_document_ir_v1` предлагает все незаполненные поля по bounded field-specific exact/FTS-фрагментам с evidence/confidence/assumptions; в том числе может достать имя и адрес с проектного листа при пустой карточке объекта. Неизвестное остаётся missing, ошибки модели не маскируются fallback-текстом. После ручной проверки Л.И.С.Т. создаёт append-only DOCX/XLSX draft с manifest `list.office_artifact.v1`, IR, SHA-256 и fail-closed скачиванием. OOXML и originals модель не меняет | `list_office_agent_service`, `list_office_service`, `forms_service`, `routers/forms.py`, `sovushka/pages/documents.py`, `config/forms/{technical_letter,meeting_protocol}.yaml`; endpoints `POST /api/forms/agent-draft`, `GET/POST /api/forms/artifacts`, `GET /api/forms/artifacts/{revision_id}/download`; tests `test_list_office_{agent_,}service.py`, `test_forms_service_w113.py`, `test_forms_templates.py`, `test_static_assets.py` | [modules/list-office-studio.md](modules/list-office-studio.md) | ✅ |
| rag/corpus-inventory | read-only source-quality cards приоритетного evidence-core корпуса: использует только operator API (`health`, Document Explorer, Dataset Notebook), показывает revision/reader/maps, document statuses/types/chunks и кандидаты pending/error/zero-chunk для ручного решения; не обходит API, не является evidence и не мутирует corpus | `tools/priority_corpus_inventory.py`; generated `docs/EVIDENCE_CORE_PRIORITY_INVENTORY.md`; tests `test_priority_corpus_inventory.py` | [PLAN_EVIDENCE_CORE.md](PLAN_EVIDENCE_CORE.md) · [CODE_MAP.md](CODE_MAP.md) | ✅ |
| rag/service-datasets | Типизированные служебные датасеты `Нормативы и чек-листы`, `Прайсы`, `Сметные источники`, `Сметные нормы`: создаются идемпотентно при bootstrap реального RAG runtime как `dataset_scope=system`; отдельный временный `MetaDB` остаётся без продуктовых side effects. Обычный чат выбирает их явно в общей области поиска; selector берёт человеческое имя из registry, показывает files/chunks и не даёт выбрать пустую базу. `SMETA_NORMS_Index` содержит обычные dense+sparse карточки норм, без отдельного сметного режима. | `system_dataset_service`, `scope_service`, `document_explorer_service`, `backend/qdrant_adapter.py`, `sovushka/pages/{chat,documents}.py`, `config/service_sources.yaml` | [CODE_MAP.md](CODE_MAP.md) | ✅ |
| rag/table | детерм. SUM по полному Parquet (числа — код) | `table_query_service`; MCP `les_table_*` | [ALGO-table-query.md](ALGO-table-query.md) | ✅ |
| rag/parent-card | После RRF+rerank (и exact guards) к hits с `parent_id` крепится typed `les.parent_card.v1`: siblings из candidate pool (+ optional provider). Не выбирает ответ — только раскрывает parent window для модели/evidence | `parent_card_hydration_service.py`; hook в `retrieval_service.py`; `tests/test_parent_card_hydration_service.py` | [BACKLOG_RAG_EXCEL_PDF.md](BACKLOG_RAG_EXCEL_PDF.md) | ✅ |
| docs/spreadsheet-object | Skeleton структурной модели Excel: workbook overview (листы/used range/sample/формулы) + formula dependency stub; calamine/COM — следующие шаги backlog | `spreadsheet_object_model.py`; `tests/test_spreadsheet_object_model.py` | [BACKLOG_RAG_EXCEL_PDF.md](BACKLOG_RAG_EXCEL_PDF.md) | 📋 |
| docs/document-object | Skeleton маршрутизации PDF-страницы: page_type → parser_chain (cheap PyMuPDF vs OCR/Docling), typed `page_fact` с provenance | `document_object_model.py`; `tests/test_document_object_model.py` | [BACKLOG_RAG_EXCEL_PDF.md](BACKLOG_RAG_EXCEL_PDF.md) | 📋 |
| rag/pdf | PDF ingestion для RAG: обязательный быстрый page-text baseline на PyMuPDF, page-level nodes вместо markdown chunk flood, layout/table/OCR как enrichment. Единый `list.pdf_page_passport.v1` классифицирует страницы (`digital_text/table/drawing/scan/mixed/damaged_text_layer`), измеряет качество/OCR-needed, штамп и координаты; те же поля попадают в RAG payload и GUI. OCR markdown `## Стр. N` теперь сохраняет page nodes, `source_layer=pdf_ocr_text`; сбой паспорта fail-soft и не удаляет searchable baseline. Уже выделенная непустая PDF-страница не отбрасывается общим 100-символьным markdown-порогом: короткие штампы, марки и номера остаются page evidence с точным `source_ref`. Короткие технические обозначения получают sparse fallback только для иначе пустого фрагмента, а separator/symbol/custom-font noise без sparse-термов отбрасывается по чанку, не превращая весь PDF в `ERROR`; Ollama embedding использует bounded retry и деление проблемной партии, а dataset-job показывает очередь, текущий файл и человеческий этап | `backend/converter`, `backend/qdrant_adapter`, `backend/inference/bm25_sparse`, `backend/document_router`, `backend/pdf_layout`, `proxy/services/pdf_contour_service.py`, `proxy/routers/documents.py`; флаги `RAG_PDF_INDEX_FAST_TEXT_FIRST`, `RAG_PDF_FAST_TEXT_FALLBACK_ENABLED`, `RAG_PDF_PAGE_NODES_ENABLED`, `RAG_PDF_PAGE_PASSPORT_ENABLED`, `RAG_PDF_PAGE_NODE_MAX_CHARS`, `RAG_EMBED_RETRY_ATTEMPTS`, `LES_LAYOUT_PDF` | [ALGO-pdf-ingestion.md](ALGO-pdf-ingestion.md) · [ALGO-pdf-layout.md](ALGO-pdf-layout.md) · [modules/pdf-contour.md](modules/pdf-contour.md) | ✅ |
| rag/harvest | verify-правки → train-set + таксономия ошибок | `harvest_service`; `tools/harvest_dataset.py` | [ALGO-harvest.md](ALGO-harvest.md) | ✅ |
| rag/context-memory | паспорт чата + metadata/deep паспорт датасета (`_les_dataset_profile.json`) + общий `notebook_v1`; typed dataset memory хранит `dataset_revisions`/`dataset_memory`/`file_cards`/`evidence_atoms`, мультислои данных, file cards, `navigation_terms`, `dataset_topic_map_v1` и `dataset_section_map_v1`; `NTD_*` домен считается технической областью поиска, а не нормативностью без явного `NORMATIVE`; карты темы/файлов остаются навигацией и доступны модели/явному `target_file`, но production chat не выполняет скрытый targeted fan-out до исходного RRF; `saferag_service` focus учитывает lexical `_rank_score` и promoted fallback; model reader-pass сохраняет `reader_output` как navigation-not-evidence; `dataset_brief_for_model_v1` упаковывает это для модели и явно связывает `file_name` с Qdrant/`lexical_chunks`/`doc_filter`; deep-слой читает FTS-проекцию `lexical_chunks`, а при пустой lexical-карте берёт `top_documents`/`priority_files` из MetaDB/file_cards; оператор может сохранить `operator_guidance` и ручной `dataset_kind` как навигационные пояснения для модели/сортировки, не evidence; UI-вкладка «Документы» показывает карту датасета, typed-бейджи в реестре файлов и в Самоваре | `context_memory_service`, `dataset_memory_service.select_topic_retrieval_plan`, `saferag_service`, `notebook_service`, `prompt_registry_service`, `lexical_index_service`, `backend/qdrant_adapter`; `GET /api/chat/memory/{session_id}`; `GET/POST /api/rag/datasets/{id}/profile*`; `PATCH /api/rag/datasets/{id}/profile/guidance`; `PATCH /api/rag/datasets/{id}/profile/kind`; `GET /api/notebooks/{dataset_id}`; `GET/POST /api/notebooks/{dataset_id}/memory*`; `POST /api/notebooks/{dataset_id}/memory/read`; `POST /api/notebooks/warmup`; `GET /api/service-sources/notebooks`; `routers/chat.py`; `sovushka/pages/chat.py`; `sovushka/pages/documents.py`; `sovushka/pages/samovar.py` | [ALGO-context-memory.md](ALGO-context-memory.md) · [CODE_MAP.md](CODE_MAP.md) | ✅ |
| rag/notebook-study | NotebookLM-подобная навигация без query-time оркестратора: готовая typed map/реестр + один исходный native RRF + модельный синтез. Скрытый reader, topic/section/file prefetch и локальный selector-loop по умолчанию отключены; явный target-file сохраняет один строгий `doc_filter`. Карты остаются navigation, факты требуют chunks/tool sources и корректных `Источник N` | `notebook_study_service`, `dataset_memory_service`, `tool_harness_service`, `routers/chat.py`; payload `retrieval_trace.notebook_study.status=map_only` | [ALGO-notebook-study.md](ALGO-notebook-study.md) · [ALGO-rag-best-practices.md](ALGO-rag-best-practices.md) | ✅ |
| rag/vision | вердикт по VL-LoRA (пока не нужна) | — | [ALGO-vl-lora.md](ALGO-vl-lora.md) | ✅ (решение) |
| rag/scan-mining | поиск данных в сканах + различение типа (verify) | `verify_service`, `table_detect`, `doc_classifier`; `routers/verify.py` | [scan_data_mining.md](scan_data_mining.md) | ✅ |
| rag/source-adapters | exact/read-only adapters для lexical, vector, file body, extracted body и mail evidence; doc-type берётся из самостоятельного classifier без старого harness | `source_adapters`, `doc_type_classifier` | [CODE_MAP.md](CODE_MAP.md) | ✅ |
| harness/history | прежний Unified Construction Harness; выключен, не импортируется product-кодом, сохраняется временно только для консолидации полезных исторических adapter-тестов | `unified_construction_harness_service`; legacy test profile | [unified_harness_failure_ledger.md](unified_harness_failure_ledger.md) | 🗄 |

**✅ исправлено:** CODE_MAP-счётчики (~101/~36/~2062); создан `ALGO-routing.md` (канон маршрутизации); AUDIT_DETERMINISM/AUDIT_CORE получили статус-баннер «исполнено»; ALGO-table-query уточнён (агрегация после ретрива). В 0.23.6.1 router-primary fallback закрыт через `RouterUnavailable` → deterministic cascade/in-flow fallback. В 0.23.6.9 `evidence_contract` расширен до системного `DefensePack/DefenseClaim`, первым подключены smeta/object и normcontrol/doc-review. В 0.24.0.18 `workflow_plan_v1` стал общим тонким контрактом для smeta/normcontrol/RAG/table payload: workflow, required/missing inputs, evidence policy, claim summary, source summary, blockers и next actions. В 0.24.0.19 Совушка начала показывать этот план оператору: статус/финальность в первом слое, workflow id/missing/actions в техдеталях. В 0.24.0.29 поверх паспортов добавлен общий `notebook_v1` и prompt registry; сметный режим получает ГЭСН-блокнот как навигацию перед tool-contract. В 0.24.0.30 ГЭСН-блокнот различает `ГЭСНм38` как монтажный раздел, не evidence. В 0.24.0.32 broad-вопросы по проекту больше не перехватываются скрытой deterministic-сводкой: обычный чат идёт в retrieval+модель, `project_summary` остаётся явным инструментом. В 0.24.0.33 qwen `lexical_chunks` восстановлены из существующих Qdrant payloads и дальше синхронизируются при parse-переиндексации файла, поэтому notebook/deep и lexical/hybrid слой больше не слепнут при уже загруженных PDF. В 0.24.0.34 добавлен `notebook_study`: явный broad-запрос по выбранной области получает reading plan, section retrieval и artifact, но итоговый текст остаётся модельным RAG-синтезом. В 0.24.0.35 этот слой стал быстрее: план выбирает меньше релевантных секций, а retrieval по ним идёт параллельно. В 0.24.0.36 cloud preset/admission починен: кастомная cloud-модель не сбрасывается, облачная генерация разрешена во время guarded reindex. В 0.24.0.37 admission стал ресурсным: индексация больше не тупой рубильник, cloud проходит всегда, локальный MLX допускается только при Core ML embedder и зелёной памяти, а runtime status показывает effective chat state. В 0.24.0.38 SSE-чат получил synthetic token fallback для final-only веток, ранние source chips и живой таймер progress. В 0.24.0.39 prompt registry v2 стал видимым API/админским слоем: общий промт, тон, режимные промты и инструменты. В 0.24.0.40 исправлены light-default и перенос многострочных промтов в админке. В 0.24.0.41 notebook-study перестал стираться generic TOSKA fallback при наличии контекста; явный артефакт обновляет открытую панель, а cloud preset включает согласие на P2-облако. В 0.24.0.42 broad-запросы по объекту/проекту обходят answer-cache и идут в широкое чтение блокнота; таблицы в чате/артефактах получили горизонтальную прокрутку. В 0.24.0.43 UUID датасета в legacy `dataset_filter` резолвится как выбранный датасет, а не как нерешённый класс фильтра. В 0.24.0.44 notebook-study снял отдельный короткий token-cap, а артефакт-блокнот рендерится как markdown-отчёт целиком: сначала найденные материалы, потом пробелы, служебный маршрут чтения внизу. В 0.24.0.45 широкие ответы больше не сжимаются фиксированными правилами строк: краткость включается только явной просьбой оператора, а source-маркеры в чате выводятся визуально как цитаты. В 0.24.0.46 скрепка чата адаптирована к NiceGUI 3 upload API (`e.file.read()`): файл снова становится видимым pending-вложением после загрузки. В 0.24.0.48 `_sync_parse` считает lexical FTS sidecar опциональной проекцией для lightweight/legacy adapter-объектов: отсутствие `_sync_delete_file_lexical`/`_sync_upsert_file_lexical` больше не валит vector parse. В 0.24.0.57 prompt registry получил editable overrides для системных промтов, tool-contracts перестали добавляться в системный prompt и остались только API/UI-метаданными; запросы на перечень файлов/реестр документов получают MetaDB `documents` inventory как evidence-блок внутри обычного RAG-ответа. В 0.24.0.58 верхняя плашка `MODEL` показывает активную модель из `/api/status`, модель конкретного ответа вернулась бейджем в AI-пузырь, а служебный inventory-заголовок заменён человеческим названием и запрещён к выводу наружу. В 0.24.0.175 broad-study перед чтением выбранного проекта best-effort поднимает модельный reader-pass и использует MetaDB-реестр для выбора файлов, не подменяя им финальный ответ.

Исторические 0.24.0.59–0.24.0.60 впервые ввели file-target и native RRF, но использовали legacy
vector-copy/sparse-sidecar/rollback-конфигурации. Эти пути удалены в 0.24.0.360 и не являются
инструкцией: текущий контракт — только полный re-embed в named contract-v2 collection.
С contract v3 native RRF становится обязательным общим путём, а не датасетным флагом: exact scope manifest включает все текущие indexed `user` datasets и исключает `system/<module>`; его hash неизменен от build/checkpoint до readiness. Выбранный scope проходит полный re-embed в clean sibling, будущий parse записывает только named dense+sparse points, collection/embedding/chunk/vector schema закреплены manifest. Потребители используют стабильные aliases `les_rag` и `les_smeta_norm_cards`; номера физических поколений остаются только в сборке и rollback. `tools/rag_generation_supervisor.py` возобновляет сборку через bounded retry; progress и source identity пишутся атомарно. `tools/rag_rrf_readiness.py` блокирует activation без полного migration report, audited exclusion accounting, единого fingerprint, обоих vector channels, полного alias-ready FTS и filtered live RRF каждого dataset; live probe берёт model/backend из immutable generation contract, а не из default активного рантайма. `tools/activate_qdrant_generation.py` перед переключением повторно сверяет живую collection, публикует Qdrant+SQLite alias с rollback и при прямом аварийном запуске согласует supervisor state; legacy vector-copy migration отключена.
В 0.25.0 общий `les_rag` закреплён за пользовательскими документами: `sync-smart` не регистрирует module-owned generated projections. Сметный ФГИС/ФСНБ-контур отдельно строит typed SQLite и sibling `dense+bm25_sparse`; generation-scoped manifest не меняет активный, readiness требует полного dense/sparse/fingerprint/native-RRF+rehydration, а `activate_smeta_rag_generation.py` атомарно переключает alias и active manifest. Полный selector выбранной моделью таблицы читается напрямую из SQLite.
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
| normcontrol/doc-review | RAG-led СПДС-review по ГОСТ Р 21.101-2026 (computed + retrieval-подфаза + PDF sheet geometry + layout-zone штампа) + defense-contract + `normalized_remarks` + решения инженера для checklist/report renderers; факты комплекта ищутся в project dataset, а текст требования берётся из явного нормативного SPDS RAG (`NTD_SPDS_Index`/`LES_NORMCONTROL_SPDS_DATASET_IDS`) с актуальным ГОСТ Р 21.101-2026; самостоятельный экспериментальный doc-review API удалён, живой вход — checklist review | `doc_review_service`, `doc_review_retrieval_service`, `title_block_extract_service`, `document_set_model`, `normcontrol_review_map_service`, `evidence_contract`; `routers/checklist_review.py`; флаг `LES_TITLE_BLOCK_OCR` | [DOC_REVIEW_GOST_R_21_101_2026_PLAN.md](DOC_REVIEW_GOST_R_21_101_2026_PLAN.md) · [PD_RD_REGULATORY_BASE.md](PD_RD_REGULATORY_BASE.md) | ✅ |
| normcontrol/skill | рабочий контракт нормоконтроля: модель формулирует замечания по правилу/месту/риску/действию, код выполняет computed checks/layout/RAG/defense trace; missing = unknown, не pass/fail | `prompt_registry_service.normcontrol_role_pack`; [skills/normcontrol/SKILL.md](../skills/normcontrol/SKILL.md); tests `test_rag_normcontrol_skill_contract.py` | [ALGO-normcontrol.md](ALGO-normcontrol.md) · [DOC_REVIEW_GOST_R_21_101_2026_PLAN.md](DOC_REVIEW_GOST_R_21_101_2026_PLAN.md) | ✅ |
| normcontrol/formal-v1 | внутренние формальные NK-01..04 (форматы ГОСТ, шифры, ведомость), переиспользуемые checklist review; отдельные normcontrol/doc-review API удалены как неиспользуемые | `normcontrol_service`, `doc_review_service`, `checklist_review_service`; `/api/checklist-review` | [ALGO-normcontrol.md](ALGO-normcontrol.md) | ✅ |
| drawings/manifest | MVP паспорта листа чертежа: PDF → формат листа, правая нижняя зона штампа, positioned text blocks, кандидаты объект/адрес/том/шифр с provenance, смысловой разбор шифра `ИОС.ЭС.ПЗ`, номера листов для текстовой и графической частей, `Содержание тома` как `volume_contents_row_v1` реестр состава тома, batch-реестр по `cipher_norm` и явные `no_cipher`/`no_stamp`/`cipher_conflicts`; read-only, без LLM и без reindex | `drawing_manifest_service`; CLI `tools/drawing_manifest.py`; tests `test_drawing_manifest_service.py` | [CODE_MAP.md](CODE_MAP.md) | ✅ |
| pd-rd/manifest | Source-map ПД/РД для RAG: многостраничное `Содержание тома`, `Состав проектной документации`, `Оглавление` ПЗ, compact sheet summary и PDF-mojibake repair; `ПЗ` = тип документа, домен берётся из шифра, темы из оглавления; нормативный профиль строится от ПП N 87 + ГОСТ Р 21.101-2026; read-only, без LLM, без reindex и без чтения графических схем как схем | `pd_rd_manifest_service`; CLI `tools/pd_rd_manifest.py`; tests `test_pd_rd_manifest_service.py` | [CODE_MAP.md](CODE_MAP.md) · [PD_RD_REGULATORY_BASE.md](PD_RD_REGULATORY_BASE.md) | ✅ |
| project/pdf-extract / Л.И.С.Т. | Единый source-map PDF-проекта без reindex: оркестрирует `drawing_manifest_v1`, `pd_rd_manifest_v1`, shared `project_pdf_table_manifest_v1` и дисциплинные readers в sidecar `_les_pdf_extract`; source-map остаётся навигацией, не evidence. После source-map автоматически обновляются адресный реестр таблиц и реестр документов/виртуальных томов, поэтому model tools готовы без отдельной build-команды; `UNKNOWN` остаётся в диагностике, но не занимает компактную навигацию модели. `project_document_registry_service` строит read-only JSON-проекцию `Документация → проект → стадии → виртуальные тома → разделы → документы`; договоры/КП/сметы/переписка — связанные сущности. С 0.24.0.376 выпущенный PDF якорит том по cipher+discipline, supporting-файлы присоединяются по identity/discipline/stage, путь — последний fallback; каждый том показывает basis/confidence. `project_table_registry_service` строит адресный каталог: 32-hex `table_id` связывает SHA-256 PDF, page, bbox, полный header и версии algorithm/detector; exact read проверяет drift и возвращает `stale`, а не устаревший evidence. Shared table layer склеивает только безопасные соседние фрагменты одной страницы, наследует заголовок кабельного журнала, отделяет `ОТМ. 0.000` и распознаёт состав проекта; per-file checkpoint/resume сохраняется | `project_pdf_extract_service`, `project_pdf_table_service`, `project_table_registry_service`, `project_document_registry_service`; `/api/rag/datasets/{dataset_id}/pdf-extract/{status,run,summary}`, `/table-registry/build`, `/table-registry/summary`, `/tables/search`, `/tables/{table_id}`, `/document-registry/build`, `/document-registry`, `/virtual-volume`; model tools `search_project_tables`, `read_project_table`, `assemble_project_volume`; tests `test_project_pdf_extract_service.py`, `test_project_pdf_table_service.py`, `test_project_table_registry_service.py`, `test_project_document_registry_service.py`, `test_project_registry_router_contract.py` | [ALGO-pdf-ingestion.md](ALGO-pdf-ingestion.md) · [ALGO-electrical-schematics.md](ALGO-electrical-schematics.md) | ✅ |
| electrical/schematic-reader | Read-only MVP чтения электрических однолинейных схем, таблиц расчёта нагрузок и ВОР/СО: PDF text blocks + vector line primitives + candidate circuits + normalized load rows + material rows + model-facing summary; словарь `electrical_schema_terms.yaml` мапит `Руст/Pуст`→`p_installed_kw`, `Рр/Pр`→`p_calc_kw`, `Iр`→`i_calc_a`, `L/длина`→`cable_length_m`; materials layer отдаёт `cable/panel/lighting/containment/busbar/protection` rows, `doc_role`, кабельные марки/сечения/`quantity_m`, action/technical fields (`IP`, ток, напряжение/список напряжений, мощность, высота, dкаб, габариты, масса), product code/supplier/type mark; summary layer отдаёт source navigation, агрегаты нагрузок по щитам, cable/equipment inventory, SO→draft-VOR seeds и coverage counts + capped examples, но не кодовый отказ/вердикт; ВОР и СО не суммируются, следующие задачи — сверка ВОР↔СО и СО→draft ВОР; слой не утверждает топологию без читаемых подписей и отдаёт `unknown`/warnings вместо fake graph | `electrical_schematic_service`, `electrical_materials_service`, `electrical_evidence_summary_service`, `config/domain/electrical_schema_terms.yaml`; CLI `tools/electrical_schematic.py`, `tools/electrical_materials.py`, `tools/electrical_evidence_summary.py`; tests `test_electrical_schematic_service.py`, `test_electrical_materials_service.py`, `test_electrical_evidence_summary_service.py` | [ALGO-electrical-schematics.md](ALGO-electrical-schematics.md) | ✅ |
| normcontrol/checklist | чек-лист входного контроля ПД БУП/ГИП | 📋 кода нет | [CHECKLIST_REVIEW_PD_TASK.md](CHECKLIST_REVIEW_PD_TASK.md) | 📋 |

**✅ исправлено (437f1aa):** DOC_REVIEW шапка «planned»→«Phases 1-5 реализованы»; призрачные сервисы → реальные имена; создан `ALGO-normcontrol.md` (formal-v1). В 0.23.6.11 чатовый doc-review стал человеческим defense-отчётом без подмешивания memory, а D4-001 формат листа проверяется по PDF-геометрии/ГОСТ 2.301. В 0.23.6.12 D4-002 проверяет, что сигнатуры основной надписи попали в ожидаемую нижнюю правую зону листа; сигнатуры вне зоны становятся computed issue. В 0.24.0.0 JSON/XLSX получил `normalized_remarks`; в 0.24.0.1 инженер может подтвердить/отклонить/запросить данные, и решение сохраняется в API/экспорт. Остаётся 📋 Phase 6: ПП-87 composition profile, DOCX/PDF renderer, checklist importer и deeper layout-tool для заполнения всех граф.

## 4. Приёмка / Intake

| Суб-модуль | Назначение | Точки входа | Док | Статус |
|---|---|---|---|---|
| intake/asbuilt | смонтированный объём из сканов исполнительных → журнал (pending); отдельный field API удалён, обработка доступна через dataset intake, чат и CLI | `asbuilt_intake_service`, `datasets.py`, `agent_router_service`; чат «вытащи объём из …»; `tools/asbuilt_extract.py` | [ALGO-asbuilt-intake.md](ALGO-asbuilt-intake.md) | ✅ |
| intake/mail / Е.Ж.И.К. | read-only полный сбор classic Outlook + multi-account IMAP; один ящик = отдельный P0 dataset; exact registry/cursors/snapshot, `.msg/.eml` message+attachment nodes и Windows interactive sidecar. Рабочий UI ведёт по цепочке `ящик → переписка → письмо → exact target_file в чат`; private mailbox означает `ready` без обязательного legacy `MAIL_Index`. Outlook cursor фиксирует завершённый backfill и не перечитывает историю; ручной проход запускает installed `LesMailPoller.exe` напрямую из loopback/root-admin API, без UAC-зависимости от Scheduled Task, ограничен 10 снимками/12 секундами и watchdog 15 секунд. Release smoke не регистрирует user-wide Outlook task. Loopback intake атомарно сохраняет raw+manifest и освобождает Outlook до exact registry/RAG; последовательный spool возобновляется после рестарта, а parser стартует после его опустошения. Windows gate компилирует sidecar и проверяет cursor persistence; legacy `/push` сохранён | `mail_registry_service`, `mail_sync_service`, `mail_profile`; `proxy/routers/mail.py` (`_queue_outlook_spool_manifest`, `_drain_outlook_uploads`, `recover_outlook_spool`, `/collector/run`); `clients/outlook_mail_poller`; `tools/{platform_release_gate.py,windows_release_smoke.ps1}`; `/api/mail/accounts*`, `/collector/import`, `/messages/{id}/open`; `sovushka/pages/mail.py` (`build_mail`, `build_mail_settings`) | [ALGO-mail-intake.md](ALGO-mail-intake.md) · [modules/sovushka-uikit.md](modules/sovushka-uikit.md) | ✅ |
| intake/les_md | LES.md — файл-контекст папки (привязка к проекту) | `les_md_service`; чат «пойми папку …» | [ALGO-les-md.md](ALGO-les-md.md) | ✅ |

## 5. Инфраструктура / Операции / Версии

Канонический Windows lifecycle: [ALGO-windows-lifecycle.md](ALGO-windows-lifecycle.md). Любой install,
launch, soft update и hard recovery обязан реализовывать его состояния и terminal errors без UAC.
Installer содержит exact deploy stamp; offline cache распаковывается bundled Python и автоматически
переиспользуется builder-ом по content address. Каждый изолированный release smoke получает новые
GUID-qualified install/state roots, поэтому частичный предыдущий запуск и его ACL не наследуются.
Во время bootstrap desktop блокирует повторный запуск, показывает текущую фазу и не ждёт сеть ради tokenizer.
Qdrant payload-индексы создаются best-effort после готовности коллекции и не удерживают API startup.

| Суб-модуль | Назначение | Точки входа | Док | Статус |
|---|---|---|---|---|
| ops/github-update-channel | GitHub Releases — default для full и lightweight patch releases; immutable latest feed + tag-specific hashed asset, deterministic patch/full classifier, published full-feed commit aliases, isolated apply/rollback. Release gate доказывает replace/add/delete target state, skipped-version compatibility и byte-exact rollback; Совушка проверяет feed при старте и раз в сутки | `tools/{release_classification,github_patch_release}.py`; `vps_patch.py`, `vps_patch_apply.py`, `update_service.py`; `sovushka/components/header.py` | [design](superpowers/specs/2026-08-25-github-release-update-channel-design.md) | ✅ |
| ops/documentation-contract | каноническая цепочка документации, локальные ссылки и ограничение размера продуктового roadmap проверяются как кодовый контракт | `tools/documentation_contract.py`; `tests/test_documentation_contract.py`; `make verify/test` | [DOCUMENTATION_PLAYBOOK.md](DOCUMENTATION_PLAYBOOK.md) | ✅ |
> `ops/vps-patch` (0.27.13): `tools/vps_patch.py update-local` сам читает exact deployed commit,
> формирует допустимый runtime diff и выполняет локальное обновление через Limited Scheduled Task
> без SSH, UAC и ручного списка файлов.
| ops/windows-process | единый запрет видимых console windows: UI/runtime probes и фоновые Python jobs запускают Windows children с `CREATE_NO_WINDOW`; Чат/Студия переключаются внутри готовой `/classic` без повторного построения страницы; общий `lazy_tab_panels` создаёт только активный раздел, Quasar `keep_alive` сохраняет уже открытый UI, но periodic timers активны только у видимой вкладки. Датасеты используют дешёвый `/api/runtime/dispatcher/reindex/status` вместо полного process/service preflight. same-origin Чат↔Конфигурация получает короткий `@view-transition`; оба motion-пути соблюдают `prefers-reduced-motion`; soft allowlist разрешает exact общий process launcher и его проверенный helper | `tools/{les_runtime_control,vps_patch,vps_patch_apply}.py`; `proxy/{routers/runtime.py,services/runtime_dispatcher.py}`; `sovushka/{lite_bridge.py,components/header.py,pages/{chat,rim,samovar}.py,uikit/{components,tokens}.py}`; `sovushka_ng.py`; tests `test_{les_runtime_control,runtime_router,runtime_dispatcher,lite_bridge,sovushka_uikit,vps_patch,windows_application_update}.py` | [VPS_PATCH_CHANNEL.md](VPS_PATCH_CHANNEL.md) · [modules/sovushka-uikit.md](modules/sovushka-uikit.md) | ✅ |
| infra/runtime-profiles | явные режимы `full` (proxy+UI), `backend` (proxy) и `ui` (Совушка); внешние model/Qdrant не стартуют скрыто, локальные qdrant/MLX/indexer добавляются только явным флагом. Поддерживает co-located и split VPS/ZeroTier topology без смены frontend/backend contract | `tools/les_runtime_control.py`; `tests/test_les_runtime_control.py` | [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md) · [CODE_MAP.md](CODE_MAP.md) | ✅ |
| infra/runtime | топология (proxy:8050 / sovushka:8051 / mlx:8080 / qdrant:6333) | `proxy_server.py`, `sovushka_ng.py`, `mlx_host.py` | [PROXY_ARCHITECTURE.md](../PROXY_ARCHITECTURE.md) ✅ · топология в [CODE_MAP.md](CODE_MAP.md) (INFRASTRUCTURE_v2.0 → archive) | ✅ |
| infra/api-integrations | публичный provider-neutral сетевой контракт для независимых Sovushka/backend/model/Qdrant nodes без machine-specific IP, active-provider snapshots или устаревшего public relay; exact route inventory берётся из live `/openapi.json`, роли answer/embeddings/fallback назначаются независимо, browser не получает secrets | `proxy/app.py`, `proxy/routers/{chat,datasets,model_connections,status_page}.py`, `proxy/routers/settings.py`, `sovushka/lite_bridge.py`, `mlx_host.py`, `env.example` | [LES_API_AND_EXTERNAL_INTEGRATIONS.md](LES_API_AND_EXTERNAL_INTEGRATIONS.md) | ✅ |
| infra/mlx | TTL-выгрузка, memory-guard, профили памяти и bounded KV/prefix cache на стабильной границе chat-сообщений; hard-stop локального чата отделён от операторских GREEN/YELLOW/RED границ. С 0.30.50 доказанно резидентная exact answer-модель не блокируется повторно default RAM loading-floor после собственного warmup; swap guard и явный operator resident floor сохраняются. С 0.30.51 runtime status не использует занятость semaphore текущим ответом как новый admission-denial: ожиданием владеет bounded generation queue. Настоящий `mlx_lm.stream_generate` логирует TTFT/prefill/decode/peak memory, а OpenAI usage показывает `cached_tokens`; direct OpenAI benchmark различает stream/non-stream, cache и tools; изолированный OptiQ probe принудительно проверяет MTP single-path, sampler forwarding, acceptance и Metal memory без production dependency; 9B — целевой профиль M4/24 ГБ, 4B — диагностика/малопамятный режим | `backend/mlx_adapter`, `mlx_host.py`, `proxy/services/runtime_admission.py`, `proxy/routers/runtime.py`, `tools/local_inference_benchmark.py`, `tools/optiq_mtp_probe_server.py` | [MLX_GUIDE.md](../MLX_GUIDE.md), [RUNTIME_MEMORY_PROFILES.md](../RUNTIME_MEMORY_PROFILES.md) ✅; [LOCAL_INFERENCE_OPTIQ_MTP_M4_2026-07-13.md](LOCAL_INFERENCE_OPTIQ_MTP_M4_2026-07-13.md) ✅; [TODO_LOCAL_INFERENCE_BENCHMARK.md](TODO_LOCAL_INFERENCE_BENCHMARK.md) 📋 | ✅ |
| ops/deploy | dev→рантайм cp-деплой + stamp; принятый internal Mac updater строит из чистого pushed `codex/audit-rag` малый ZIP только изменённых runtime-файлов. Подготовка не запускает tests/build и не включает baseline/user data; API и CLI независимо проверяют archive/helper/file SHA, allowlist и base identity. Partial-restore hash принимается только если его полный SHA подтверждён старым deploy stamp; исторический drift требует committed exact reconciliation, которая активна только пока runtime имеет её historical accepted SHA и после выравнивания не блокирует будущие изменения файла. Recovery хранит предыдущий stamp, новый наследует ownership SHA нетронутых файлов. Apply делает backup→atomic replace→restart→version/health/index-contract smoke и автоматический rollback. Legion намеренно отключён до отдельной приёмки, публикация отсутствует | `config/mac_runtime_reconciliation.json`; `tools/{mac_update,mac_update_apply,deploy_to_runtime}.py`; `proxy/services/update_service.py`; `proxy/routers/updates.py`; `sovushka/components/header.py`; `make prepare/inspect/apply/status-mac-update` | [INTERNAL_MAC_UPDATE.md](INTERNAL_MAC_UPDATE.md) ✅, [SKILL.md](../SKILL.md), [RELEASE_LEDGER.md](RELEASE_LEDGER.md) | ✅ |
| ops/vps-patch | Windows имеет два режима поверх одного lifecycle: hard install заменяет дерево программы, soft package транзакционно заменяет, добавляет и с 0.30.6 удаляет bounded content-файлы. Delete остаётся v2-compatible через нулевой payload и обязательный target `vps_patch_apply.py`, поэтому `0.30.0` напрямую запускает новый helper; known SHA сохраняется в backup, absence идемпотентен, unknown bytes/protected path отклоняются до stop, rollback восстанавливает файл и stamp. `windows_update_engine.py` владеет stop/start/smoke; `%LOCALAPPDATA%\LES` никогда не входит в транзакцию. Soft apply проверяет persistent venv и live mechanical baseline, не запускает tests/build/network sync и не управляет внешним Qdrant. После successful apply отдельные exact-identity функции умеют контролируемо вернуть прежние soft-файлы/stamp или hard application tree; если smoke прежней версии падает, accepted candidate восстанавливается. `vps_patch.py` строит cumulative manifest пакетным чтением ancestry/tree/blob и сообщает progress без отдельного Git-процесса на каждый файл. С 0.30.49 classifier, builder и installed updater имеют синхронный exact allowlist объявленных runtime-support файлов; его рассинхрон ловится тестом и не превращает безопасную Python/UI-правку в ложное требование NSIS. Публичный текст `README.md` считается release-only metadata: наличие файла в полном runtime обязательно, но его текстовый drift не требует NSIS и не входит в soft patch. `release_orchestrator.py` автоматически классифицирует выпуск, гоняет обязательные gates, замораживает устанавливаемые bytes в receipt и передаёт их Legion runner без пересборки. `windows_release_acceptance.py` принимает кандидата только после exact install, smoke, controlled rollback, smoke восстановленной версии и повторной установки тех же bytes; ранее доступные capabilities не могут исчезнуть, а доступный Qdrant обязан пройти временный native RRF dataset smoke. После acceptance оркестратор разрешает только доказанный non-force fast-forward public main и сохраняет evidence sync в attempt. Feed/notes/public receipt формируются только поверх уже принятого ZIP/installer; оба publisher требуют accepted receipt, явный target, immutable draft, обратное скачивание всех assets и независимый postflight refs/feed/hashes. `stop-light`/`windows_runtime.stop` останавливают только confirmed LES PID. Public release запрещён до Legion-приёмки | `tools/{release_receipt,release_orchestrator,windows_runtime,windows_env_doctor,windows_update_engine,windows_release_acceptance,vps_patch_apply,vps_patch,windows_update_shell,windows_clean_install,github_patch_release}.py`; `proxy/services/{update_service,version_service,rag_readiness_service}.py`; `proxy/routers/updates.py`; `sovushka/components/header.py`; tests `test_{release_classification,release_receipt,release_orchestrator,vps_patch,windows_application_update,windows_release_acceptance,github_patch_release,patch_release}.py` | [ALGO-windows-lifecycle.md](ALGO-windows-lifecycle.md) · [VPS_PATCH_CHANNEL.md](VPS_PATCH_CHANNEL.md) ✅ · [release orchestrator design](superpowers/specs/2026-08-30-release-acceptance-orchestrator-design.md) | ✅ |
| ops/versioning | единый `config/version.json`: пользовательский SemVer, отдельный монотонный номер сборки и внутренняя Tauri/NSIS-версия; `make version-sync` обновляет машинные поверхности, а `make verify` ловит drift; `/api/version` показывает repo↔runtime divergence. `make release` — единственная публичная операторская граница и ведёт persisted prepare→Legion acceptance→draft→postflight; старые patch/full/multiplatform targets остаются внутренними адаптерами. Internal Mac updater отделён и не меняет public release metadata | `version_service`; `tools/{sync_version_contract,release_receipt,release_orchestrator,patch_release,github_patch_release,mac_update,mac_update_apply}.py`; `GET /api/version`; `make {version-sync,release}` | [RELEASE_PROCEDURE.md](RELEASE_PROCEDURE.md), [INTERNAL_MAC_UPDATE.md](INTERNAL_MAC_UPDATE.md), [RELEASE_LEDGER.md](RELEASE_LEDGER.md), [VERSIONING.md](VERSIONING.md), [SOFTWARE_VERSIONS.md](SOFTWARE_VERSIONS.md) | ✅ |
| ops/service-sources | видимый реестр служебных источников для смет и нормоконтроля; `SMETA_SERVICE` Play показывает manifest требуемых сметных документов и форматов по классам нормы/цены/методика/формы. Полное обновление ФГИС запускается из GUI как backend-job; экран показывает этап, текущий регион/сборник, completed/total, bytes/rate/ETA и живой лог, а уже идущий отдельный ГЭСН не блокирует скачивание Сплит-форм | `service_source_registry`; `fgis_update_service`; `gesn_update_service`; `tools/fgis_full_update.py`; `routers/service_sources.py`; `config/service_sources.yaml`; GUI `sovushka/pages/instrumenty.py`, чат `sovushka/pages/chat.py` | [SKILL.md](../SKILL.md), [CODE_MAP.md](CODE_MAP.md) | ✅ |
| ops/http-client-policy | внутренние loopback HTTP-вызовы не наследуют системный SOCKS/HTTP proxy; внешние, LAN и ZeroTier URL сохраняют обычный `httpx` contract | `backend/http_client_policy.py`, критические callers в `sovushka/state.py`, `proxy/app.py`, diagnostics/runtime, metrics/reranker | [modules/http-client-policy.md](modules/http-client-policy.md) | ✅ |
| normcontrol/checklist-review | evidence-led проверка ПД/РД по корпоративным шаблонам Glorax: 335 пунктов ПД, 692 пункта РД, formal/parametric/ПП РФ №87 checks, immutable run, отдельные решения инженера и XLSX/HTML/JSON; UI показывает evidence-статус отдельно от решения и не формирует code-owned chat answer | `proxy/services/checklist_*`, `proxy/services/pp87_composition_service.py`, `proxy/routers/checklist_review.py`, `config/checklists/*`, `sovushka/checklist_review_*` | [CHECKLIST_REVIEW.md](CHECKLIST_REVIEW.md), [ALGO-glorax-checklist-review.md](ALGO-glorax-checklist-review.md) | ✅ |
| ops/dataset-integrity | единый аудит источников и всех поисковых проекций датасета: source fingerprint, MetaDB, Qdrant point ids, named dense+sparse, lexical/FTS, текстовые страницы PDF и orphan-документы. Health сравнивает активную пользовательскую collection с `user`-чанками MetaDB и явно учитывает исключённые module-owned `system`-чанки. Обычное удаление остаётся recoverable через MetaDB backup, Qdrant snapshot и storage quarantine; recovery-free ветка закрыта exact release-acceptance fixture. Ремонт не перестраивает весь корпус: удаляет stale/orphan-проекции, помечает отсутствующие исходники и ставит только повреждённые файлы в видимый bounded parse-job. Ошибка одного датасета не блокирует запуск ЛЕС; в «Документах» оператор получает одну кнопку и русский статус | `backend/qdrant_adapter.py`; `proxy/routers/datasets.py`; `proxy/services/dataset_deletion_service.py`; `sovushka/pages/documents.py`; `GET /api/rag/datasets/{id}/integrity`; `POST /api/rag/datasets/{id}/integrity/repair` | [CODE_MAP.md](CODE_MAP.md) | ✅ |
| ops/external-radar | радар внешних папок: configured roots + filemap + in-place `source_path` без reindex/OCR/LLM; ручная сверка in-place датасета по папке показывает new/changed/deleted и может синхронизировать изменения без фонового watcher-а. Добавление/синк внешней папки с `parse=true` создаёт видимый dataset-scoped `rag_parse_drain` job и продолжает bounded партии, а одиночный `parse-batch` честно показывает `PARTIAL`, если pending ещё остался. Intake-plan выполняется как внутренняя preflight-проверка без системного браузерного confirm; основная кнопка сразу запускает создание и индексацию. Карты `LES.md`/`00_dataset_map.md` создаются как служебный слой папки, но не регистрируются как RAG-документы. Google Drive / Яндекс Диск подключаются через web/API: облачная папка синхронизируется в mirror-кэш и дальше регистрируется существующим `index-external`; локальные sync-папки остаются fallback | `external_radar_service`, `cloud_drive_service`; `GET /api/external-radar/summary`; `GET /api/rag/cloud-drives`; `POST /api/rag/cloud-drives/list`; `POST /api/rag/cloud-drives/sync`; `POST /api/rag/external/intake-plan`; `POST /api/rag/index-external`; `POST /api/rag/external/check`; `POST /api/rag/external/sync`; `POST /api/rag/parse-batch/{dataset_id}`; GUI Самовар | [ALGO-external-radar.md](ALGO-external-radar.md) | ✅ |
| ops/public-showcase | curated public GitHub/Pages surface без приватных датасетов и runtime-секретов; README и versioned release document разделяют готовые, preview и planned surfaces, описывают Совушку/backend/model/Qdrant как независимые узлы и не выдают наличие внутреннего модуля за product acceptance; release staging берёт только файлы под контролем Git и дополнительно исключает runtime-данные и отдельный продукт `products/artel/**`, поэтому локальные рабочие папки коллег не могут попасть в установщик | `README.md`, `docs/index.md`, `docs/public/{overview,releases/0.29.3}.md`, `tools/publication_check.py`, `tools/build_release_artifacts.py` | [PUBLICATION_CHECKLIST.md](PUBLICATION_CHECKLIST.md), [public/overview.md](public/overview.md), [public/releases/0.29.3.md](public/releases/0.29.3.md) | ✅ |
| ops/test | Общая suite сохранена только как явная диагностика и запрещена в updater-контуре до переработки тестовой архитектуры. `make test-updater` — отдельный короткий hermetic behavior-гейт: hard whole-tree replace/rollback/state boundary, soft manifest/SHA/apply/rollback, установленная Legion-приёмка, shell attestation и Mac updater; он не запускает NSIS/baseline/общую suite. Apply никогда не запускает тесты. Legion acceptance поверх живого Windows runtime проверяет exact proxy identity/UI как LES core отдельно от user-managed Qdrant, сохраняет capability continuity и запускает native RRF при ранее доступном Qdrant на substantive fixture; exact временный набор удаляется без snapshot всей collection, но обычное пользовательское удаление остаётся recoverable. Генеративный ответ модели не требуется | `Makefile`; `tests/{test_vps_patch,test_windows_application_update,test_windows_release_acceptance,test_windows_update_shell,test_update_service,test_manual_update_ui,test_mac_update,test_dataset_deletion_service,test_qdrant_health_count_contract}.py`; `tools/{windows_updater_smoke.ps1,windows_release_acceptance.py}` | [TEST_INVENTORY.md](TEST_INVENTORY.md) · [VPS_PATCH_CHANNEL.md](VPS_PATCH_CHANNEL.md) | ✅ |
| install | Tauri 2 — канонический desktop shell над NiceGUI. Публичный Windows `LES-Setup.exe` ставится per-user и обновляется поверх; application tree `%LOCALAPPDATA%\Programs\LES` отделён от persistent `%LOCALAPPDATA%\LES`. Payload содержит SHA-256-проверенные portable Python/uv, exact `uv.lock`, offline dependency cache и immutable ФГИС/ФСНБ baseline, но не пользовательский RAG. Bootstrap использует только bundled runtime и locked/offline sync; несовпадение payload — явная fatal-ошибка. Ollama, FreeToken, Lemonade, OpenAI-compatible, embeddings, Docker и Qdrant остаются user-managed: wizard показывает role/availability/official links, не ставит и не выбирает их; отсутствие внешнего компонента не блокирует LES core. Shell — GUI subsystem с single-instance/lifecycle guard и `CREATE_NO_WINDOW`; proxy/UI запускаются direct Python PID без `cmd.exe`/`uv` wrappers. `tools/windows_release.ps1` автоматически выводит identity из version/Git, находит baseline, выполняет build→isolated smoke→transactional deploy; updater до replace перечисляет `cwd`-locks. Upgrade/rollback сохраняют state; core acceptance проверяет exact version, API/UI и process contract, а внешний Qdrant/RRF получает отдельный passed/N/A результат. macOS остаётся reference profile, Linux — server profile. | `.github/workflows/{verify,release}.yml`; `desktop/tauri`; `desktop/tauri/src-tauri/windows-installer-hooks.nsh`; `installers/windows/{start-light,state,app/bootstrap.ps1}`; `tools/{platform_release_gate,multiplatform_release,patch_release,build_tauri_app}.py`; `tools/windows_{release,release_smoke,production_deploy,production_rollback}.ps1` | [WINDOWS_DESKTOP.md](WINDOWS_DESKTOP.md) ✅, [ALGO-windows-lifecycle.md](ALGO-windows-lifecycle.md), [INSTALL_RUNBOOK.md](INSTALL_RUNBOOK.md) ✅, [PLATFORMS.md](PLATFORMS.md) ✅ | ✅ |

**0.29.1 / build 627:** `install` создаёт вложенные каталоги через разрешённый target
persistent-state junction; живой Windows-тест воспроизводит Programs+junction boundary.

**0.29.2 / build 628:** `install` не допускает прямые mutable paths в application tree;
Programs-shaped prebundle smoke запускается до npm/NSIS и сохраняет bounded service diagnostics.
Offline uv cache использует dependency-only fingerprint с exact lock/archive SHA verification,
поэтому release-only версия ЛЕС не пересобирает тяжёлый dependency archive.

**✅ исправлено:** SKILL/TEST_INVENTORY → v0.23/~2063/smoke-basic done; PROXY_ARCHITECTURE → `les_meta_qwen.db`; INFRASTRUCTURE_v2.0 (мёртвое) → archive. Версии (3 оси) объяснены в [RELEASE_LEDGER.md](RELEASE_LEDGER.md); 0.23.N.P внедрено в `version_service`. В 0.23.6.2 добавлены checksum для backup/restore и сужены дефолтные trusted loopback/proxy-сети; в 0.23.6.3 скрепка чата стала реальным контекстом/payload scope; в 0.23.6.4 закреплены светлая тема по умолчанию, скрытая панель артефактов и OpenAI-compatible `gpt-4.1` fallback; в 0.23.6.5 добавлен явный GUI-контроль открытия артефактов и управляемый fail-path чтения вложений; в 0.23.6.6 source chips открывают citation drawer без fake-open; в 0.23.6.7 router-primary стал explicit opt-in, чтобы убрать 12s latency fallback; в 0.23.6.8 read-вложение стало видимым файлом следующего сообщения, plain file-reading идёт без глобального RAG, direct/router LLM без облачного ключа уходит в локальный MLX; в 0.23.6.10 `make ship` стал быстрым итерационным gate, `make ship-full` — полным release gate с retry post-smoke; в 0.23.6.11 нормоконтрольный чат отдаёт defense-report и top-level `defense`; в 0.24.0.1 служебные источники доступны из чата отдельной панелью.

> **Поправка 0.24.21 / build 442:** Windows payload теперь содержит SHA-256-проверенный официальный
> portable CPython `3.13.12` ZIP. Bootstrap распаковывает его в persistent state без MSI/реестра и запускает
> `uv sync --python <bundled> --no-python-downloads`; прежняя формулировка строки `install` про
> один только `uv.exe` описывает 0.24.19 и заменена этим дополнением.
> **Поправка 0.24.22 / build 443:** Windows `uv sync` использует системное хранилище сертификатов,
> bounded retry/timeout, `--locked`, удаляет только недосозданную `.venv` и сохраняет точный
> sanitized stderr в bootstrap log/status вместо общего «uv sync не удался». Установка с
> повышением не оставляет state административному токену: SID интерактивного пользователя получает
> `Modify` на `%LOCALAPPDATA%\LES` и восстановленный сметный baseline.

## 6. Прочие модули (отдельные продукты/контуры)

| Модуль | Назначение | Док |
|---|---|---|
| cad-bim | CAD/BIM граф + вьювер (three.js/web-ifc); DWG/DXF путь идёт через `tools/cad_bim_extract_dxf.py` (`dwg2dxf` → DXF repair-pass → реконструкция нарисованных таблиц → `cad_bim_graph.json` → `/api/cad-bim/import`) и затем `sync-smart` projections в `CAD_BIM_Index`; projection выводит `CAD drawn tables`, `first positions`, `logical positions`, data row-lines и compact row-lines перед поэлементным шумом; `retrieval_service` для `target_file` умеет `first_ordinal_guard` по фактическим `position N`; `GET /api/cad-bim/imports` даёт read-only inventory импортов, слабых графов, дублей и статуса индексации projection; Совушка показывает это в самостоятельной вкладке `CAD/BIM`, отдельно от документов | (в [CODE_MAP.md](CODE_MAP.md); `routers/speckle.py` = `/api/cad-bim/*`) |
| artel | самостоятельный Revit-продукт: исходники и выпуск принадлежат `proovcme/Agnostis`; LES хранит только pinned `products/artel` submodule для интеграционных контрактов, ARTEL Index retrieval и BIM-export связи | `products/artel/README.md`, `.gitmodules`, `tests/test_artel_packaging.py` |
| mail (Е.Ж.И.К.) | read-only classic Outlook + IMAP, private dataset per mailbox; Apple Mail/.olm remain legacy imports | [ALGO-mail-intake.md](ALGO-mail-intake.md) · [CODE_MAP.md](CODE_MAP.md) |
| mcp | ЛЕС как MCP-сервер (18 инструментов наружу, включая пакетный поиск цен ФГИС) | `tools/les_mcp_server.py` (в [CODE_MAP.md](CODE_MAP.md)) |

---

## Шаблон дока модуля (`docs/modules/<name>.md` или `docs/ALGO-<name>.md`)

```
# <Модуль> — <одна строка назначения>
Назначение · Точки входа (сервис/роутер/MCP/чат) · Данные/конфиг · Зависимости ·
Поток (формулы/шаги, 0 LLM где про числа) · Статус-vs-код (что сверено) · Грабли/границы · Тесты
```

> **0.27.2 Windows updater contract:** `ops/vps-patch` и `ops/test` используют
> единый переносимый `tools/platform_release_gate.py updater`: на Windows он не
> требует GNU Make, сам создаёт доступный pytest temp, а prepared hard-job
> сохраняет exact `codex/*` branch. `start-light.ps1` нормализует дублированные
> `Path`/`PATH` до запуска дочернего Python.
>
> Канон 0-LLM ядер — `docs/ALGO-*.md` (по кирпичу). Этот индекс их агрегирует; при добавлении/правке
> модуля — обнови строку здесь и поставь честный статус (✅/🟡/🗄/📋).
