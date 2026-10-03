# RAG evidence flow

Дополнение889: экспорт сохраняет numeric formula caches из готовой трассы
(`rim_trace_xlsx_service`). Данные читаются без внешнего пересчёта Excel;
редактируемые формулы и partial-статус сохраняются. См. ALGO-lsr-assembly.

## 889 — бюджетная остановка не скрывает сохранённый файл

Sheet-pass после CloudBudgetStop с принятыми терминальными решениями доходит до
существующего XLSX executor. Модель больше не вызывается, предметные строки
не изменяются. Workbook получает WORKBOOK_RESEARCH_INCOMPLETE и причину остановки;
задание остаётся paused/cloud_token_budget с неполным остатком и исходной ценовой базой.
Если нет ни одного принятого решения, сохраняется429: пустой результат не создаётся.

Held packet сохраняется только для текущих locators. cloud_budget_pending означает
техническую остановку, а не успешный model read. Поэтому отказ до первого ответа
не скрывает never_offered и не превращает его в MISSING нормы. Проверены query,
answer и native-read точки остановки с реальным offline workbook executor.
Live888 показал дефект автоматической выдачи; ручная API-пересборка подтвердила,
что12 строк доступны без модели. Исправление упаковки не доказывает применимость
их норм, полноту материалов или отсутствие повторного начисления.

## 888: обычный native research завершается ответом, а не текстом команды

В installed887 history768 после calls_budget финальный вызов (без tools) вернул
Qwen XML web_search, принятый за ответ. Теперь обязательный финальный system prefix
сообщает фактическую фазу: инструментов нет, ответить по сохранённому evidence или
назвать недостающее. Применяется только обычному research, не smeta model-driven
continuation с readers. Вопрос, evidence, calls/replies и профессиональный ответ
модели не переписываются.

Если финал всё же содержит новый native call либо нефенсированный protocol frame,
граница выдаёт MODEL_OUTPUT_INCOMPLETE с reason=model_tool_request_in_final_answer.
Служебный JSON/XML и reasoning не отправляются в SSE/answer/history. Новых вызовов,
авторетраев или придуманных результатов нет. Корректные ответы и fenced примеры
сохраняются. Basic smoke считает такой результат FAIL, даже при HTTP200/nonempty.
Регрессии проходят через реальную application boundary с токенами и историей;
сама синтетическая проверка не подтверждает качество подбора норм и цен.

## 887: provider reasoning сохраняется в native protocol

OpenAICompatibleTransport.complete читает только явное строковое reasoning_content.
BoundModelChatRunner сохраняет весь response, меняя только список допустимых calls.
Обычный research и сметные B0/B1 передают reasoning через typed NativeToolExchange
отдельно от assistant content. Для отсутствующего поля не создаётся пустая имитация;
для переданного пустого/многострочного поля сохраняются точные байты текста.
Router native parser делегирует общему smeta parser, не режет пакет до driver и
сохраняет исходные arguments/content. Сначала декодируется внешний JSON, затем
legacy fenced text: вложенные Markdown/JSON не перехватывают envelope.

Контекст и облачный расход учитывают это поле; overflow виден технически.
Публичные receipts, ответ, trace и история reasoning не сохраняют. После resume
новый ход использует durable evidence; утраченное старое reasoning не выдумывается.
Регрессии проверяют фактические B0/B1 callbacks, обычный research, второй mock HTTP,
unknown-reader stops, privacy и оба бюджета. Это не живая приёмка качества норм.
Provider contract: https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions.

## 886: повтор native-чтения получает сохранённый результат

Live885 B0 на FreeToken с физическим KV131072 завершился через1007,74с без XLSX:
три успешных дополнительных поиска, затем evidence_read_repeat. Немедленный
отказ на первом повторе не возвращал модели уже найденные карточки. Теперь
driver один раз возвращает тот же receipt с прежними evidence_refs/bindings и
новым provider call_id, без повторного поиска, новых Q-ref или изменения тела.
Смешанный batch сохраняет порядок ответов; одинаковые аргументы внутри batch
исполняются один раз. Только успешный/предметно missing/conflict receipt
пригоден для replay; ошибки и неизвестные старые записи не превращаются в успех.
Replay расходует общий max_calls, второй повтор в том же ходе останавливается.
Журнал сохраняется при продолжении, но старые receipts не становятся кэшем
нового хода: инженер мог сменить регион, квартал или редакцию источника. Новое
чтение использует актуальную область. Legacy текстовый loop сохраняет guard.

B0/B1 используют общий driver; technical read stop маркируется technical_pending
с точным reason, без ложной диагностики отсутствия таблицы. Тесты проверяют
реальные callbacks, сохранённые ссылки, native ID, бюджет, resume и упаковщик
на синтетических данных. Это не профессиональная приёмка настоящей ЛСР.

## 885: восстановление журнала охватывает цепочку продолжений

Сообщение с другим question_sha может создать новый research job с inherited
task_context/evidence. Для старых повреждённых журналов этого недостаточно:
полные receipts сохранились в событиях родителя. `evidence_read_receipts`
использует `list_events_with_lineage` (существующая ограниченная цепочка),
сохраняя фильтр packet_id и ключ call+bindings. Другой исходный SHA не наследует
эти события. Доставка монотонна, тексты evidence и решения не изменяются.
Регрессия: `test_read_ledger_recovers_legacy_events_across_document_continuation`.

## 884: журнал чтений переживает следующий resumed read

Live883 доказал14 успешных чтений по ссылкам. Повторный ход при новом чтении
записывал только текущий `read_receipts=[]`, заменяя накопленный журнал18
операций одной записью. Evidence bytes сохранялись, но audit/resume терял
историю вызовов. Теперь список начинается с `saved_read_receipts`; после
успешной передачи initial resumed frame подтверждаются и старые receipts.
Новые чтения добавляются к ним. Старые883 записи восстанавливает read-only
`WorkbookResearchJobService.evidence_read_receipts(job_id, packet_id)` по
сохранённым событиям model_evidence_read и текущему task_context. Доставка
монотонна; разные calls/bindings не сливаются. Решения не пересчитываются.
Полный ledger сохраняется при следующем новом чтении. Регрессионный тест
`test_resumed_new_read_preserves_prior_receipts` воспроизводит stop→resume→new read.
Профессиональные решения и лимит бюджета не меняются.

## 883: начальные ссылки должны быть доступны exact reader

Live881: семь вызовов `read_norm_card(evidence_ref=...)` отклонены, хотя среди
них были уже показанные полные карточки и указатели. Начальный builder давал
`body_status`, но не delivery receipt; строгий reader правомерно не принимал
неподтверждённые ссылки. Нельзя трактовать это как отсутствие запросов модели.

После успешного первого ответа B0/B1 `confirm_model_read_delivery` отмечает
inventory и отдельно full bodies, затем `register_shown_norm_cards` повторно
регистрирует ссылки. Начальные groups обязательны в соответствующем кадре,
включая fallback. При resumed native frame используются фактические множества
inventory/body refs governor, в том числе текущие начальные chunks. Ошибка
отправки ничего не подтверждает. Отложенный указатель разрешает чтение, но не
служит доказательством содержания полного тела. Immutable identity/source
проверки exact reader не ослаблены. Regression B0/B1 × full/pointer + failed
answer + partial admission входят в related245passed; live ещё не выполнен.

## 882: облачный бюджет учитывается при упаковке native continuation

Installed881 BAP Flash B1 сделал2 вызова, provider usage66364, затем следующий
body396663bytes требовал reservation414081 при remaining233636. Нет final/XLSX;
job paused,20pending,0accepted. Safe trace сохранился и в SSE, и в history.
Offline replay114 saved evidence даёт281281bytes optional discovery groups;
полный профиль/ответ модели не подменяются. Receipts:
`artifacts/live_881/bap_flash_candidate/{failure_trace,offline_replay_sizes}.json`.

882 передаёт remaining-budget admission в общий ContextGovernor: сохраняет
обязательные данные, откладывает только целые optional группы с явными pointers.
Бюджет неизменен, запросы/выбор норм принадлежат модели. При budget stop во время
native чтения сохраняется held packet с исходными запросами/locators и read_pending;
точные результаты чтения уже записаны в durable evidence. Outer boundary не
добавляет повторную паузу/счётчик stall. Приёмка требует установленного live;
офлайн 146passed не являются доказательством качества норм.

## 879: native read capacity не является ошибкой формата модели

Если held packet содержит model_read_pending/read_stop, финализация сохраняет
read_stop как job.phase. Уже предъявленные locators исключаются из diagnostic
scheduler_gap.never_offered, но остаются незавершёнными: accepted rows, remaining
и closure ledger не изменяются. При отсутствии terminal rows evidence_read_capacity
даёт model_result.status=technical_pending с отдельным reason и понятным сообщением
о нехватке контекста, а не unstructured/«таблица не получена».
Регрессия проходит actual sheet/native control flow с двумя пакетами: первый
предъявлен, второй нет; оба остаются pending, ни одной строки/XLSX не выдумано.
Причинный RED воспроизведён, related48passed; canonical8793178passed/20existing
skipped, verify/architecture/docs exit0. Install879 pending.

## 878: буквальные названия и единицы ценовых кандидатов

`read_pricebook_evidence` сохраняет name/unit конкретной строки закреплённой
книги в metadata, которую читает общий inventory_pointer. Поэтому отложенное
тело ценового кандидата остаётся различимым по названию, единице и коду, а не
только по служебному имени источника. Это точная проекция имеющейся строки,
без выбора ресурса, подтверждения применимости или изменения цены. Source SHA,
book/region/quarter, raw body, порядок кандидатов и явное чтение сохраняются.

Причина: installed877 thinking B0 показал42 ценовых указателя без name/unit;
модель затем выполнила40 отдельных чтений цен и остановилась по ёмкости.
Последовательность измерена, причинное влияние на качество требует live878.
Исправление не означает, что выбранная модель уже корректно подбирает нормы.
Regression `test_model_research_evidence_actions` проходит настоящий producer
и deferred inventory planner для search/exact read: Unicode/name/unit/code/book/SHA,
неизменное raw resource body, без добавления полного тела или цены в pointer.
RED2→focused131passed; canonical8783177passed/20existing skipped. Installed878
thinking B0/B1 не вызвали price tools, поэтому влияние исправления на live качество
этими прогонами не измерено; B0 professional failed, B1 остановлен ёмкостью.

Ниже сохранена историческая запись875 до установки:
**Doc↔candidate code: ✅875; установлен874 `c4253e38`, professional FAILED.**

Native-capacity pause сохраняет literal query/provenance/address/offset state,
prepared bodies и read receipts. Resume читает saved query cache; не формулирует
новые запросы ради восстановления. Initial answer overflow включает truthful
required/available/overflow trace до model call. `bind_model_requested_read_evidence`
имеет internal optional reserved_query_end: max этого whole declared range и
existing durable Q определяет первый новый native handle. Sheet передаёт
query_offset+len(pass_hits), B0 — len(model_rag_query_hits), включая unshown/empty
query groups. Held/deferred raw cursor увеличивается только на len(included_hits);
native high-water mark не меняет original query aliases на следующих страницах.
Receipts/global IDs/raw bodies и prepared/delivered semantics
прежние. Это предотвращает новые raw/native alias collisions; старые aliases
не чинятся. Ambiguous unbound refs остаются unresolved; exact persisted immutable
binding не переписывается. Focused native/read suites143 passed; live875 pending.

`decode_model_result_rows` отделяет standalone `artifact_kind: ...` transport line
вне JSON/fences от единственного полного JSON результата. Строки и их literal
fields не меняются; raw_original сохраняется в diagnostics. Marker внутри JSON
или fence не вырезается. Duplicate/invalid/conflicting target по-прежнему
независимо отклоняет `decode_model_artifact_kind`, а однозначные row decisions
остаются сохранёнными до видимого packaging pending.

Для неизменного UI repack с пустым question `workbook_repack_replay_arguments`
сопоставляет server-owned business inputs с последним `workbook_packaged`
snapshot и возвращает ровно первоначальные arguments. Learned book/provenance
и inherited_from=self revision не создают новый расчёт; applied pricebook SHA
сохраняется. Source bytes, decisions, overlays, trusted issues, effective profile
и явная смена price basis нарушают cache identity. Unknown/incomplete snapshot
идёт обычным путём. Router перед replay проверяет saved artifact bytes и complete
checkpoint через существующие stores. Потерянный файл/checkpoint даёт explicit
409 `WORKBOOK_REPACK_CACHE_UNAVAILABLE`, без executor/модели и без пересчёта по
новым bytes под старой identity. Текущая цена каталога не объявляется ценой
старого сохранённого расчёта; pinned revision остаётся immutable.

Explicit plain continuation пересекает terminal packet locators с реально
settled source keys только при новом literal resume: same-request replay,
later terminal barriers и принятые MISSING не меняются. Freeform chat review
остаётся отдельным model-owned пересмотром прежних решений/operation IDs.

Ordinary continuation остаётся delta. При nonempty current-packet review_rows
prior-page инструкция требует все предложенные прежние операции, включая
неизменённые с дословными model fields/citations, прежним operation_id и
expected_revision из показанного revision. Shared system field/table instruction
и sheet tail явно отделяют этот режим от ordinary delta. Reopen сохраняет
старые решения в prior history, но убирает их из active accepted; omitted review
операции не восстанавливаются автоматически. No schema handshake, code norm
choice/default status/auto-confirmation или новый model cycle не добавлены.
Actual fake-chat full answer повторяет unchangedA и changedB; cut answer
сохраняет accepted0/remaining2 и исходный prior event. Focused316 passed;
это не доказывает живую корректность окраски R18/R19 или полноту всей ревизии.

После admission каждый shown norm body (включая shown aliases) получает
card_delivery_facts: normative_card_complete и normative_resources_status.
Preview/unknown имеет optional read_norm_card(evidence_ref=literal ref).
Raw body, index, immutable IDs остаются прежними; deferred/unshown не получают
body proof. Новые маркеры входят в реальную стоимость capacity planner.
Инструкция отделяет применимость от расхода: обзор N/N не содержит доказанного
per_unit; отсутствие цены/прочитанного тела не доказывает отсутствие нормы.

Durable accepted subset при локальной transport/quantity ошибке может быть
упакован как промежуточная ЛСР. Unapplied proposals сохраняются целиком;
trusted document_issues проходят application/router/context/adapter/snapshot.
Позиции и model decisions не чинятся. Только summary документа остаётся
priced_partial/full_amount=None/confirmed_amount=0, known subtotal preliminary;
watermark и «Проверка» показывают технические причины. Readiness блокирует
estimate_complete при document issues; повторная упаковка idempotent, без модели.
All-invalid/unknown mandatory errors остаются blocking.

Тип итогового документа при смешанных ВОР/ЛСР упоминаниях объявляет модель
в том же query/final ходе. `decode_model_artifact_kind` читает только literal target;
`read_model_query_response` сохраняет дословные запросы. Для model-declared ВОР
queries=[] не запускает repair, нормо-поисковые candidate queries или extra call.
`WorkbookResearchJobService.record_artifact_kind` хранит target отдельно от rows.
Plain continuation наследует его; новое замечание может разрешить прежний конфликт.
Native builder и repack не обходят target ambiguity. Без допустимого выбора упаковка pending;
исходные решения не теряются и дополнительный предметный вызов не запускается.

MODEL_OUTPUT теперь нейтральный M, не VERIFIED/UNVALIDATED/crag_fail.
Diagnostics сохраняет прежние V/H/U quality thresholds и явно сообщает,
что M не доказывает качество. Только-M — insufficient-validation warning.

Installed874 `c4253e38ea9539eb841e993eb373a42665079c0a`: BAP260.5s professional
FAILED, B0~79s без файла, SKS~387s overflow. EOM821.75s дал actual partial ВОР
46 rows/23 из56 locators; saved first packet24 rows потерял decoder из-за
standalone marker. 875 replay восстановил все24 поля/строки без изменений.
Физический XLSX EOM сохранил роли21 material/24 work/1 header и все authored
количества; final remaining33 сохраняет все исходные gaps. SKS plain continue
16.56s оставил23/75,0работ/0денег и не дошёл до answer phase: FAILED.
BAP engineer remark738.11s дал файл; professional acceptance ещё pending.
875 focused: cache100 passed, row transport139 passed; full gates/install/live pending.
Проверки транспорта/арифметики не доказывают профессиональную применимость.

**Doc↔candidate code: ✅ 872 literal shown-code navigation and lossless pointer replay.**
Missing parent/table code feedback uses only admitted literal prefix+dash siblings
with refs/title/source/edition/identity. It remains missing/conflict, hits/count0;
no reader, norm selection, fuzzy lookup or query rewrite. Separate navigation
records do not change exact resolver uniqueness. Actual inventory view supplies
titles; hidden raw body titles are never used. Options survive native receipt trace.
Unread pointer-field aliases preserve each ref and provenance; no body confirmation.
Installed871 `e8657ba3`: API/GUI/19 hashes aligned; native RRF exit0, EXE858 retained.
Original90s smoke7 pass/1 warn/2 timeout fail is retained; finite180s exit0,
10 pass/0 warn/0 fail (112.66s). Professional871 FAILED, readiness not asserted:
B0/B1 same identity,331.73s/92.17s,required46993/47433 at budget46246,no XLSX.
B1 six exact cards delivered, thenfour searches blocked;20remaining/0accepted.
SECOND canonical: 2925 passed / 20 existing opt-in skipped / 5 warnings,
verify/architecture/baseline/active artifacts exit0. Первый FAILED 2923 passed /
2 rawsearch-before-admission fixture failures сохранён; исправлен только test
fixture explicit admission (119 passed / 15.60s), source8 неизменён.
Professional871 FAILED/private exact installer pending; native EXE858 retained.
Review охватил 8 source files; initial focused 10 suites 392 passed (21.54s),
4 causal old-boundary ablations red сохранены. Это не professional proof.
Предыдущий exact870 `7ba406a1`; professional870 FAILED: B0 179.56s,
required 55639 / budget 46246, 4 searches / 24 prepared refs, no XLSX;
B1 57.97s paused, 0 rows / 20 remaining, first read frame 45230 admitted,
second required 72822 / budget 46246, no XLSX. Prepared≠delivered остаётся
обязательной границей. 30 разных saved body и их provenance не являются
повтором native receipt; код не выбирает, какие нормы профессионально верны.
`prepare_model_read_replay` сохраняет exact reads и уже cited bodies mandatory
вместе с literal inventory; discovery bodies входят optional whole query groups.
`govern_model_read_messages` получает фактически admitted objects от Governor
в initial saved replay, `_continue_sheet_reads` и `_continue_direct_reads`.
Raw body, immutable IDs и все refs остаются durable, view clone не стирает их.
`model_inventory_delivery_status` и body `model_delivery_status` независимы:
индекс разрешает точное чтение, но не доказывает полный body или цену.
Source map показывает inventory view и body_visible; manifest/row binding/
`price_evidence_check` не используют непоказанный raw body. Raw search не
регистрирует shown card до admission; delivery подтверждается после ответа
провайдера. Legacy saved exact-price receipts обязательны, pointer-only не
производит full-body receipt. Scripted B0/B1 JSON→XLSX fixtures дают confirmed
1800 при 24 сохранённых raw refs; это offline proof транспорта и расчёта.
Canonical 870: 2906 passed / 20 existing opt-in skipped / 5 warnings,
verify/architecture/pinned baseline exit0. Native RRF exit0; basic 90s project
timeout сохранён отдельно от finite hardware-calibrated 180s smoke:
10 PASS / 0 WARN / 0 FAIL (85.55s), glossary/project 31.640s/51.438s,
оба ниже исходного 90s. Измеренный FT request p95 128.233s объясняет явный
лимит; технический smoke не снимает professional capacity failure.

870: governed native continuation получает один полный receipt body и сохраняет
original source/question, prior decisions и exact evidence identities. Убрана
повторная копия body в evidence projection; сохранённая 869 форма уменьшилась
на 3092 governed input tokens без увеличения context/GPU/runtime budget.
Числовая capacity проверяется до admission. `prepared` означает подготовленный
результат, а не evidence, прочитанное моделью: delivered относится к frame,
фактически переданному модели. Сохранённые native `read_chunks` участвуют
в binding только после admission в resumed answer frame. Повтор immutable global ID может
повысить prepared→delivered для того же literal body; иной body/identity этим
не объединяется. Точки: `chat_evidence_application_service`,
`chat_evidence_manifest_service`, `model_research_tool_service`,
`source_locator_service`.

Row-local повтор JSON field не выбирает значение: конфликтная авторская строка
с literal diagnostics сохраняется в pending durable snapshot, независимые
строки остаются доступными для admission. Неоднозначный envelope остаётся
packet-level technical failure. Ordinary continuation не исправляет конфликт
и не запускает предметный цикл; existing explicit reopen предлагает выбранный
locator той же модели для нового решения. Проверенная durable fixture сохраняет
3 независимые строки / 1 remaining, correction даёт настоящий XLSX.
Focused root 109/native 56/decoder-durable 73 passed; final targeted parser
118 passed (15.98s), transport/persistence 119 passed (20.44s).
Последние boundary regressions: 8 red / 2 prose controls green → 128 passed
(14.64s). Canonical/installed 870 отражены выше. Предыдущий 869 professional FAILED:
draft 7/19 реальных работ, header учитывается отдельно; 64 545.14 known draft,
confirmed 0. Доступный файл и арифметика не подтверждают применимость карточек.

869: повторная буквальная команда «Продолжи» при совпадении прежнего identity
следует к более позднему исправлению в той же lineage. Проверяются session,
attachment, source SHA, datasets, profile и model binding на каждом звене;
чужое промежуточное звено не допускает перенос. Incoming original_question
должен соответствовать question hash; legacy caller без контекста распознаёт
только конечный набор существующих команд продолжения. Явный повтор исходной
задачи сохраняет exact/idempotent поведение. Completed revision сохраняет
исправленные rows, price_basis, evidence и overrides; paused возобновляется,
guards уже работающей ревизии не сбрасываются. Точки:
`workbook_research_job_service.{_is_plain_continuation,_latest_compatible_continuation}`.
17 focused regressions и 138 related tests passed; установленная приёмка 869 FAILED.

869: общий `model_lsr_result_field_instruction` ставит явно запрошенный пользователем
формат структурированных строк выше общих рекомендаций оформления. Без заданного
формата предпочтителен компактный JSON rows; прежние Markdown/text parsers доступны.
`lsr_result_table_instruction` передаёт общий контракт до условных подсказок Markdown.
Это не schema API и не исправление авторских значений; факт соблюдения реальной
моделью проверяется installed live gate. Три новые регрессии failed до изменения;
59 related tests passed после него.

869: malformed результат сохраняется в durable `pending_model_result_packets`
вместе с literal diagnostics/cursor/query provenance. Он не запускает repair
и не останавливает ещё не предложенные строки. Обычное продолжение не меняет
его решения; существующий explicit reopen позволяет модели исправить только
выбранные source rows. Снимаются лишь разрешённые snapshots; до разрешения
технической неоднозначности готовность и упаковка не объявляются. Join перечитывает
состояние owner; raw исторические proposals остаются в аудите.

PDF-каталог сохраняет нетабличный literal текст отдельными `PDF_TEXT!Rn`
блоками до 4096 chars. Прежние `PDF!Rn`, source SHA и табличные объёмы стабильны.
Роль текстовых блоков определяет модель; они входят в scope учёта исходника.
Малый контекст показан целиком; большой имеет явный `model_context_partial`,
точный диапазон непоказанных locator и отдельные source packets.
`source_extraction_complete` и полнота показанного контекста различаются;
image/SVG/OCR warnings исключают ложную полноту извлечения.
Converter Markdown `source_start/source_end` сохраняют буквальный порядок таблиц
и примечаний; одинаковые таблицы имеют разные source spans. Catalog/packet
rendering используют этот порядок, не предметную связь условий. PDF-specific
facts не увеличивают пакеты XLSX/CSV/DOCX; 226 catalog/chat checks passed.
Native `read_source(source_row=...)` читает literal строку текущего bound
каталога с SHA/source_file_id; произвольные paths/другие вложения не доступны.
Native receipt содержит полный literal body и offsets; governed replay не
дублирует body. Reader/native integration: 169 passed, без изменения budget.
`begin_or_resume(source_locators=...)` принимает только server-owned catalogue
scope. Новый адрес того же SHA дополняет remaining, сохраняя прежние решения;
old completed file остаётся previous_final_revision_id, а текущий scope pending
до новой упаковки. Watermark принадлежит своему job; legacy/inherited revisions
и price basis сохранены. Scope/join/sheet/recovery bundle: 374 passed.
Свежая installed приёмка этих границ обязательна; offline не доказывает качество.

Archive intake использует `tools/unpack_archives.py` до обычной индексации файлов.
Завершение подтверждается marker с SHA исходного архива и manifest извлечённых
файлов. Частичный каталог без валидного marker повторно проверяется;
пользовательские файлы не перезаписываются. Ошибка любого архива видна и даёт
ненулевой exit; traversal/link targets отклоняются. Оставшийся prior-owned файл,
которого больше нет в новой версии архива, даёт stale-output blocker и сохраняется;
новая completion marker не выдаёт старое evidence за текущую revision.
Прямое chat-вложение ZIP/RTF
не объявляется поддержанным только на основании этого препроцесса.

866 уточняет только общий model-owned контракт до final: исходные ограничения
сравниваются с реально показанным составом и ресурсами; указатель не доказывает
условия. MODEL_EVIDENCE_READ_INSTRUCTION требует настоящий вызов при недостатке
содержания и ответ инструмента как факт выполнения. Ресурсные формы описаны
точными enum и компонентными reasons из contracts.ResourceBinding/ResourceReview.
Это инструкция модели, не parser forcing/кодовый выбор/новый review loop.
Ресурсный guide применяется только через MODEL_EVIDENCE_READ_INSTRUCTION на
сметном read/answer-ходе. Общий field/format contract и обычный non-native RAG
сохраняют прежнюю нагрузку на контекст; полные evidence не вытесняются этим guide.
Query-фаза отдельно объясняет, что форматирование и workflow требования пользователя
не являются предметными поисковыми фразами; literal query execution не изменён.
865 live: первый terminal B1 дал partial 12/19 за 129.50s без повторных начислений
того цикла, но карточки модель не прочитала и качество не прошло приёмку.

865: inventory JSON pointer связывает только шифр, буквально показанный в body.
Producer metadata и совпадение кода не подтверждают чтение условий; полное
чтение требует body и той же immutable identity. После terminal ответа B1
сохраняет `terminal_model_result_saved` в held packet и немедленно упаковывает
авторские строки. Deferred query hits не требуют нового предметного ответа:
курсор, cache, literal queries и непоказанный хвост остаются для явного resume.
Native reads внутри модельного хода и продолжение усечённого transport result
сохраняются. При оставшихся строках ревизия partial и job не объявляется complete.
Live 864 сравнение FAILED: B0 19/19 за 231.09s; B1 47 операций на 12/19 за
1011.75s с повторными начислениями. Суммы файлов независимо совпали с API, но
подтверждённая сумма обоих 0 и профессиональные ошибки остаются открытыми.
Свежая установленная приёмка 865 обязательна; offline не заменяет качество ЛСР.

Кандидат 864 исправляет измеренную потерю полного авторского JSON-массива.
Reader принимает единственный завершённый массив либо объект `rows`, в том числе
JSON fence с пояснением; разные завершённые результаты неоднозначны, усечённый
JSON не восстанавливается. Обычная таблица и подписанный текст сохраняются.
`resource_bindings` и `resource_review` — буквальные optional поля во всех форматах;
их JSON-значения не угадываются. Ссылки действия разрешаются независимо от ссылки
нормы и сохраняют immutable identity при совпадении alias следующего пакета.
App-derived checks не принимаются из ответа модели и не возвращаются как её решения.
Пакетирование XLSX сохраняет действия, основания, ссылки и конфликты в «Проверка».

Полный body — неделимая единица capacity-плана обеих веток. Точный общий
каталог НР/СП передаётся один раз вместе с буквальными ссылками, ресурсы и
состав не обрезаются. Сначала показывается помещающийся индекс кандидатов,
затем полные группы; хвост индекса может уступать место первой полной группе,
чтобы курсор не застревал. Индекс, полные body и непоказанный хвост считаются
раздельно. Модель может сама прочитать показанный точный указатель существующим
native reader до terminal result; после него новый предметный ход не запускается.
`deferred_capacity` не является полной карточкой: `norm_card_body_unread`
оставляет авторский выбор и известные деньги видимыми, но не закрывает готовность.
Parent cipher, другая редакция или другой источник не подтверждают exact item.

Installed 863 B0: полный array19, старый reader0 и XLSX0; B1: answer length32768,
paused19 и XLSX0. Профессиональная проверка B0 FAILED, несмотря на верные количества
и цитаты шифров. Fresh live comparison 864 остаётся обязательной.

863 добавляет явные profile query/answer output budgets внутри того же
подтверждённого окна. Governor учитывает каждый до упаковки evidence/native
schemas; provider max_output_tokens ограничен diagnostic reserve, а model-RAG
использует весь выбранный резерв. Ordinary notebook/inventory caps сохранены.
Defaults и профессиональные решения не изменяются. 861 reasoning B0/B1
не дали final/XLSX из-за `length`; это технический отказ, не отсутствие норм.
[Поля профиля и границы](chat-profiles.md). Fresh live acceptance пока открыта.

Кандидат **861**; установлен runtime **860**. Свежий B0 860 выдал файл с
правильным переносом ячеек и арифметикой, но необоснованными авторскими нормами;
B1 удержал malformed proposals и не выдал XLSX. Клиентская приёмка FAILED.
861 исправляет техническую диагностику и согласование query-output с резервом;
свежая профессиональная сравнительная приёмка остаётся открытой.

## Назначение

Обычный чат и model-authored estimate используют один принцип: модель сама формулирует запросы и
пишет итог, код только выполняет retrieval, сохраняет provenance и механически исполняет
разрешённый постпроцессинг. На сметном пути к запросам модели добавляется гарантированный системный
сбор кандидатов (ADR-16, см. ниже); он не отнимает у модели ни выбора нормы, ни решения о
применимости. Дополнительного planner/model-review шага и JSON-протокола между моделью и RAG нет.

## Активный поток

Необязательное рассуждение модели задаётся строгим boolean
`model_policy.reasoning_enabled` в сохраняемой пользовательской версии профиля;
отсутствующее поле означает `false`. Переключатель «Рассуждение модели» находится
в существующем редакторе профилей, requested/effective/source видны в диагностике
исполнения, перезапуск не требуется. Политика проходит через bound runner и
typed `InferenceRequest` одинаково для B0/B1 и продолжений чтения; FreeToken
получает `chat_template_kwargs.enable_thinking`. Модель, провайдер, sampling,
KV и резерв контекста не меняются. Для generic OpenAI-compatible подключения без известного управления transport
сохраняет `requested=true`, но показывает `effective=false` с причиной
`unsupported_by_transport`; поддержка не угадывается. Известные способы —
FreeToken template flag и уже выбранный native Ollama protocol.
Отдельные reasoning-каналы и ведущий `<think>`-блок,
включая разрезанные streaming tags, не передаются parser строк; после начала
финального текста буквальные XML/code markers сохраняются. Ответ без final
content при исчерпании генерации остаётся видимой технической остановкой без
выдуманных строк и дополнительного предметного вызова. Это опция для проверяемого
эксперимента; улучшение качества требует установленного live-сравнения.

С 861 query-output ограничен фактическим `query_packet.generation_reserve_tokens`.
Пустой GUI-фактор `LES_CHAT_MODEL_RAG_QUERY_MAX_TOKENS` означает auto: до 1600
без рассуждения, при явно включённом рассуждении — уже выделенный резерв.
Явный положительный cap также ограничен резервом; ошибка настройки видна отдельно.
Каждый call сохраняет safe `model_query_outputs` (requested/effective/source,
reserve, finish, usage, final_chars) без hidden reasoning и текста источника.
Пустой final + length не запускает repair: `MODEL_QUERY_OUTPUT_INCOMPLETE`,
candidate checkpoint остаётся paused и resumable без workbook. Завершённый
невалидный final по-прежнему допускает штатный repair; законченные строки
обрезанного query list сохраняются, оборванная последняя не исполняется.
Коды `MODEL_RAG_QUERY_LIST_EMPTY` и `MODEL_RAG_SEARCH_INCOMPLETE` проходят
public error boundary отдельно от реальной недоступности upstream.

1. Effective chat profile задаёт `candidate_k`, `document_diversity_k` и
   `model_evidence_k`. Заводские значения — `64 / 2 / 6`; пользовательская
   ревизия хранит свои значения, GUI показывает effective policy.
2. Native dense+sparse RRF получает широкий `candidate_k`. Код удаляет только
   точные дубли фрагментов и ограничивает число фрагментов одного физического
   документа, затем передаёт модели `model_evidence_k` результатов.
   На norm path с 844 production `retrieve_smeta_norm_cards` явно передаёт
   expand_queries=False; тот же literal default используется norm browser API.
   Legacy vocabulary не добавляет доменные шаблоны по source locator/изделию.
   С 845 результаты поиска в durable query_cache имеют технический contract:
   smeta_literal_query_v1 / shared_native_query_v1. Старый либо несовместимый
   кэш, включая пустую выдачу, не подменяет новый поиск. На продолжении held
   queries исполняются исходными формулировками через текущий reader без
   нового модельного планирования; offset/addresses остаются прежними.
   Envelope хранит прежнюю выдачу в superseded для аудита. Accepted rows,
   cited evidence, operation revisions и immutable файлы не переписываются.
   Отказ инфраструктуры при обновлении кэша — техническая pause,
   search_cache_refresh_blocked, а не MISSING нормы.
   Модель получает карточки собственного запроса и дополнительных literal
   original/derived запросов ADR-16; code-chosen query paraphrases отсутствуют.
3. Для model-authored запросов каждая группа сохраняется независимо как `Qx.Hy`.
   С 843 инструкция не запрещает модели переформулировать изделие в
   обоснованный поисковый запрос по монтажной операции. Дословное исполнение
   относится к готовому запросу модели, а не к запрету её профессионального
   связывания; original/derived builders по-прежнему ограничены исходными
   словами ADR-16. Итог допускает таблицу, обычные подписанные поля или
   необязательный JSON; одна условная схема полей применяется ко всем примерам.
   Начиная с 840 sheet-pass резервирует не только заголовки, но
   обязательное содержимое ВСЕХ карточек запроса (typed prefix либо 400
   символов обычного текста) до любого optional resource preview. Группы,
   не влезающие целиком, доставляются следующей страницей без нового поиска.
   Терминальное решение строки не отменяет доставку уже найденного хвоста.
   `held_packet` сохраняет locators, query_offset, queries, provenance и addresses;
   cursor восстанавливается даже для уже решённых строк. Прежние авторские
   решения и именно их процитированные карточки передаются одновременно
   со следующей страницей. Q/H не переназначаются между её страницами,
   immutable global evidence IDs остаются основанием ссылочной проверки.
   Выбранные группы входят в required evidence ContextGovernor: объявленное
   показанным не может тихо исчезнуть при окончательной упаковке prompt.
   Если одна целая группа не помещается, это видимая возобновляемая
   `evidence_capacity` pause, а не NO_NORM. Transport-pending строки исключены
   из автоматического объявления предметных пробелов. В непакетном direct
   пути overflow по-прежнему честно назван в `omitted_evidence_refs`.
   Guard признаёт только точное продвижение cursor и остаток-сuffix прежней
   очереди доставкой новых страниц; прежняя модельная строка сохраняется.
   Неизменившийся cursor остаётся held retry; thresholds и run budget не меняются.
   С 841 точные повторы содержимого одной карточки с тем же источником,
   редакцией и scope показываются один раз в пределах страницы; каждая
   исходная Q/H группа сохраняет место, score и ссылку на это тело.
   Manifest хранит фактически показанное тело по каждому immutable ID,
   ссылки на разные источники не объединяются. Аналогично сокращаются
   повторы уже процитированных тел в контексте следующей страницы.
   С 845 prior_model_decisions сохраняет авторские поля, IDs и все citations,
   но не повторяет application-derived _quality_gate/_evidence_check/
   quality_message. Эти диагностики остаются в durable state и GUI; их
   повторные дампы не вытесняют очередную целую evidence-группу. Тела
   процитированных карточек не сокращаются этим изменением.
   После durable record_packet приложение возвращает назначенные им
   operation_id модели: прежняя операция может быть авторски пересмотрена
   как revision N+1; новая остаётся без ID до записи. Неизвестный ID или
   перенос существующего ID на другую source_row — структурная ошибка.
   Код не угадывает, какие разные операции надо объединить. Прогресс
   показывает доставленные группы карточек отдельно от числа source rows.
   Транспорт принимает обычные строки. Кавычки и явно написанная самой моделью
   оболочка `search_sources("…")` снимаются только синтаксически; вступительная
   проза при наличии таких строк не превращается в дополнительный запрос.
   Пакетный sheet-pass — тот же порядок, что у малого исходника: модель
   формулирует запросы, получает источники, принимает решения, код считает.
   Порог «маленький/большой документ» не выбирает другой контур. Первое
   принятое решение модели по строке сохраняется, обязательный verifier
   и кодовые заглушки при исчерпании попыток не запускаются. Кэш запросов и
   незакрытые locators живут в `workbook_research_jobs`; повтор поиска
   обработанного не выполняется, повтор упаковки XLSX — без модели.
   Оператор может уточнить выбранные locator или внести подтверждённые
   данные (`conversion_factor`/`conversion_source`) без смены шифра.
   Упаковка XLSX принимает то же `confirmed_data` в контракте
   `build_lsr_workbook`; поле доходит до расчёта, а не отвергается schema.
4. Фактически показанные модели chunks образуют immutable evidence manifest.
   Следующая реплика получает компактный индекс использованного evidence и тот
   же frozen scope, но не повторные полные тела фрагментов.
5. Source map хранит `evidence_ref`, `source_ref`, страницу и typed locator:
   `file_excerpt`, `norm_card`, `web_result` или `unavailable`. UI отдельно
   показывает найденные, показанные модели и процитированные источники.
6. `selected_sources_only=true` исполняемо удаляет web capability; при `false`
   web остаётся доступен согласно профилю. Между репликами флаг наследуется из
   manifest, если пользователь не изменил его явно.
7. Web policy принадлежит GUI: `simple` использует рабочий DuckDuckGo,
   `extended` запрашивает SearXNG и даёт модели отдельный `web_read` для
   выбранной страницы через Crawl4AI. Недоступный расширенный поиск явно
   деградирует в simple; код не выбирает страницу за модель.
8. После финального ответа упаковочный reader читает явные таблицы или явные
   подписанные поля. Короткий divider `:--`, заголовок «Норматив монтажа
   (norm_code)» и спецификационная таблица без `norm_code` допустимы; `###`
   задаёт секцию, если это не заголовок `Строка N`. Обычный заголовок
   `Строка N: название` допустим, если сам блок содержит явные поля. Reader не
   извлекает решение из произвольной прозы, не переписывает значения модели и
   не выбирает ЛСР/ВОР по тексту вопроса.
   При surplus cells reader объединяет текст только в title/open_gap и только
   при единственном структурно совместимом выравнивании. Число не считается
   единицей, gap_reason не считается norm_status; объём и шифр не сдвигаются
   ради восстановления строки. Неоднозначная реконструкция не выполняется.
9. С 842 явные material/equipment/header с монтажным шифром не становятся
   монтажной расчётной позицией: `positions_from_visible_lsr_rows` сохраняет
   роль, код и исходное решение в binding с `role_norm_conflict`. Объём не
   умножается на труд/машины чужой категории данных. Приложение не меняет
   роль на work и не выбирает другую норму; требуется авторское уточнение.
   Счётчики выбранных монтажных норм RIM и readiness относятся к work,
   независимо от нормальных стоимостей поставки/ресурсов.

## Необязательные чтения в answer-ходе (candidate 859)

Модель получает native read-only schemas и может запросить недостающее evidence
до итоговых строк: `read_norm_card`, `search_pricebook_resources`,
`read_resource_price`, `search_sources` (`target=norms|documents`), `read_source`.
Если она сразу вернула итог, новых model calls нет. B0_DIRECT получает те же
доступные действия; original/derived candidate queries остаются вне baseline.

Exact norm reader допускает только ранее показанный pointer: key/code conflict
не выбирает альтернативу. Карточка содержит все resources, per_unit/units,
work steps, provenance и явные count/completeness/consumption flags. Unknown
расход не выдаётся за полный ресурсный состав. Поиск документов использует
замороженные selected datasets; цена читается из закреплённой region/quarter
книги. Model-selected resource и условие НР/СП остаются выбором модели.
`fgis_price_service.get_pricebook` использует официальный reader и cache
snapshot по whole-file SHA-256/размеру; замена bytes по тому же path/mtime
не возвращает старую книгу. Typed price body, metadata и source_ref сохраняют
exact hash/name/size. Drift при чтении или mismatch с сохранённым task hash
возвращает conflict; partial snapshot не объявляется доказательством цены.
Фактический hash сохраняется в packaging `price_basis` и document/job projection.
Continuation той же literal книги проверяет expected hash до расчёта/render;
замена bytes даёт `PRICEBOOK_VERSION_CONFLICT` без нового artifact. Reader
не архивирует прежний файл; legacy basis без hash не доказывает прошлую версию.

`run_model_evidence_read_turn` исполняет literal calls, различает все аргументы
и останавливает повтор одного вызова; полный read result привязывается к новым
immutable Q/H evidence IDs и сохраняется до продолжения модели.
`shown_evidence_registry` передаёт literal предыдущие тела со всеми aliases;
точные norm pointer/source/edition с идентичным либо проверенным prefix view
разделяют одно уже показанное тело. Разные документы/price evidence с разными
IDs остаются отдельными. Shared-body reference разрешается только в фактический
показанный original; отсутствующее или неоднозначное тело явно unavailable.
ContextGovernor сохраняет целые обязательные source/evidence объекты и
учитывает schemas; overflow — видимая technical capacity pause. Read receipts
и exact cards durable, но сами по себе не отмечают source rows выполненными.
С 868 `compact_read_replay` повторяет полные показанные тела с exact shared
catalogs; deferred entries сохраняет как буквальные компактные identity pointers,
не раскрывая непоказанное stored body. Повторные projections aliases/IDs/delivery
flags не раздувают inventory в обязательный JSON registry. Source SHA/edition
разделяют разные карточки; original attachment, question и model decisions остаются.
До первоначальной выдачи групп B0/B1 одинаково оставляют native growth reserve:
`min(answer generation reserve, available group tokens / 2)`, с уменьшением до
остатка после первой целой группы. Уже помещавшаяся первая группа сохраняется;
inventory tail имеет explicit cursor. Requested/effective reserve и источник
расчёта видны в `native_read_growth_budget` trace, новых runtime factors нет.
Три чтения при call budget=3 ещё допускают terminal model continuation;
новое четвёртое чтение получает `evidence_read_budget`. Фактически слишком
большие полные результаты дают честную capacity pause, без обрезки тела или
подмены профессионального решения.

`model_lsr_result_contract` — общий контракт таблицы, JSON и подписанного текста:
выбранная work-норма требует пять match flags и coverage, выбранный supply
resource — resource_code/refs, выбранное условие НР/СП — известный rule ID либо
конкретный вопрос. Delta не требует повторить уже сохранённые операции.
`model_result_packet_service` допускает только текущую packet identity либо
явно предложенный известный operation_id; source/revision conflicts и новые
внепакетные строки остаются полными unapplied proposals. Это структурная
принадлежность пакету, не исправление роли, объёма или нормы.

Supply price/unit/source и optional quote context проверяются по фактически
процитированным телам. Один resource_code или model token `price_source=operator`
не создаёт подтверждения. Неподтверждённая цена сохраняется как preliminary/gap;
её наличие не разрешает ложную confirmed sum. Source quantity errors одинаково
проверяются для work, material и equipment до расчёта.

Source catalog не обрезает клетки до 480 символов, сохраняет 0/False и пустые
колонки. PDF catalog использует conversion без preview character cap; это не
гарантия распознавания произвольного скана. ВОР из authored decisions принимает
PDF/XLSX/XLSM/DOCX/CSV; это поддержка source reader, а не обход upload policy.
XLSM входит в default `RAG_UPLOAD_SUFFIXES` и picker без исполнения macros;
явный operator override сохраняется. Actual saved 870/871-control override
не содержит `.xlsm`, поэтому такой upload не разрешён текущей политикой.
DOCX сохраняет literal body/table/header/footer locators,
unread images/textboxes/embedded content отмечаются source_extraction_incomplete.
Примечания другого листа видны как reference_only_source_rows и не расширяют
requested_source_rows. RTF/ZIP не поддержаны этим workbook-путём; пустой ВОР
получает NO_SOURCE_ROWS до создания файла.

## Происхождение поисковых запросов (ADR-16)

Каждая исполненная поисковая группа несёт `query_provenance` — в заголовке группы и в trace:

- `model` — запрос, написанный моделью; его заголовок `[Поисковый запрос Qx] …` остаётся
  байт-в-байт прежним;
- `original` — дословный исходный текст строки каталога без сокращений и пересказа, с меткой
  «дословный исходный текст строки»;
- `derived` — тот же дословный текст плюс только явно представленные в исходнике атрибуты
  (заголовок раздела листа и написанный в ячейке шифр), с меткой «системный подбор по атрибутам
  этой строки».

Авторы `original`/`derived` — `proxy/services/lsr_candidate_query_service.py`, единственное место
активного сметного пути, где запрос пишет код. Системные группы добавляются к группам модели после
того, как её запросы исполнены, идут в тот же read-only `search_sources`, в ту же
contract-versioned named `dense + bm25_sparse` коллекцию, native RRF, общий rerank и тот же кэш
запросов: параллельного поиска, отдельного индекса и case-specific boost'ов нет. Точно совпавший с
уже исполненным запрос не дублируется, близкая формулировка остаётся — сводить разные запросы в
«один и тот же» код права не имеет.

Scope: только профиль `estimator` на табличном sheet-pass (`mode == estimator` в effective
snapshot). На обычном пользовательском dataset/chat-прогоне и в quality-diagnostic-раунде
происхождение проставляется явно как `model`, и системных запросов нет вовсе; сравнительный baseline
`B0_DIRECT` их не исполняет, а trace честно пишет `system_candidate_queries.status = skipped_baseline`.
Сбой retrieval на системном запросе виден как `search_blocked` и не превращает строки в `MISSING`.

Grounding: каждый нетривиальный токен запроса обязан дословно встречаться в его собственных
строках-источниках; при нарушении запрос отбрасывается целиком и остаётся видимым в
`dropped_ungrounded` с `reason = query_token_not_in_source` — не «исправляется». Технологию, условия
производства, объём, применимость нормы, коэффициенты и профессиональный статус код из текста не
выводит и норму не выбирает.

Факторы (категория `smeta`, видны в Совушке, применяются со следующего запроса без рестарта):
`LES_LSR_SYSTEM_CANDIDATE_QUERIES` — default `on`, выключенный возвращает путь «только запросы
модели»; `LES_LSR_SYSTEM_CANDIDATE_MAX` — default `24`, технический предел числа кодовых запросов
на пакет строк: по достижении предела код не добавляет запросов к оставшимся строкам, и это не
признак отсутствия нормы; `LES_LSR_SYSTEM_CANDIDATE_MAX_CHARS` — default `12000`, символовный
бюджет текстов кодовых запросов на пакет: перешедший бюджет откладывается в
`deferred_by_char_budget`, а не вытесняет соседей по пакету.

## Объявленные запросы: prompt, reader и адаптер (блокер § 2, 29.09)

Формат списка поисковых запросов объявлен один раз — `_DECLARED_QUERY_MARKER_EXAMPLES` и
`_MODEL_RAG_QUERY_FORMAT_CONTRACT` в `proxy/services/chat_evidence_application_service.py` — и
цитируется и prompt'ом sheet-pass, и prompt' ordinary-пути, и читается тем же reader'ом
(`read_declared_query_list`). `is_model_rag_search_query_line` и `classify_model_rag_query_lines`
делегируют ему, поэтому второй разбор одной строки не существует. Обычный текстовый вывод,
нумерованный (`1.` `1)` `(1)` `1-` `№ 1:`) и маркированный (`-` `*` `•` `—`) список читаются как
запросы; со снятием маркера снимается только оформление, формулировка остаётся дословной, а «2.5
мм2 кабель» не режется на «номер списка».

Сопровождающий ответ (вступление, пояснение, заключение, `|---|---|`, заголовок, подпись без
запроса) отделяется по структурному правилу и сохраняется с причиной в
`declared_query_rejections.reasons`; он не исполняется и не выбрасывается. Русские префиксы из
исторического списка заморожены и не пополняются: незнакомая формулировка прозы классифицируется
по форме, а не по совпадению со словарём.

Адрес строки запрос получает из самого ответа модели: написанный локатор печатается в заголовке
группи (`[Поисковый запрос Q3] … [строки: СКС!R12]`) и входит в бюджет символов той же функцией;
совпадение с текстом строки пакета (`literal_matches_row`) остаётся в trace и в заголовок не
пишется, потому что решение «о каком строке этот запрос» не кода. Локатор вне пакета сохраняется
как `address_outside_packet` и не переписывается. Кодовые кандидаты печатаются со своим локатором,
а дословный текст строки для обоих случаев читается одной функцией `row_literal_text`.

Системный запрос строится из релевантного исходного текста и явных характеристик: служебные
колонки (итог, стоимость, сумма, цена, всего, П/П, эксплуатационные расходы) и ячейки-ссылки формул
из текста строки исключены, подписанный столбец берётся из `CatalogRow.column_headers` — тех же
заголовков, которыми `attachment_source_catalog_service` размечает `line`; голое число получает
подпись своего заголовка только на `derived`. Строка без проверенных метаданных ячеек сохраняется
своим `line` целиком, и об этом пишет `source_text_filter`. Значимые размеры, состав и условия при
этом не удаляются: исключаются только перечисленные по имени служебные колонки.

Всё вышеперечисленное держится на одном предусловии: каталог должен посчитать строку заголовков
`header`. В 826 фильтр и `derived` были написаны, но на клиентском ВОР не сработали ни разу,
потому что ни одна строка заголовков туда не попала: шапка каждого листа называет денежные колонки
(«Материал (итого), руб. без НДС», «Стоимость (итого), руб. без НДС»), то есть содержит слово
подытога, а деньги там формулами, которые не дают вычисленного числа; правило подытога брало такую
строку себе, и дальше `column_headers = ()`, `quantity_column_known = False`, `header_quantity = None`
оказывались на всех 439 строках. Разрешение — порядок и форма, а не список слов: сначала
`_looks_like_column_header_strip` (≥2 непустых ячеек и ни одной ячейки-выражения) вместе с маркером
заголовка, затем подытог. Настоящая строка итога так и остаётся `subtotal` — она либо несёт число,
либо состоит из формул; на клиентском ВОР все 19 таких строк (`АР!R109`, `АР!R111`, …) сохранили
класс. Проверено пробой на боевом загрузчике (`stage_b/b2_header_probe_827.py`;
`stage_b/live_826/header_probe_before_groups.txt` против
`stage_b/live_827/header_probe_after_fix.txt`): 10 шапок связались, на реальных пакетах по 10 строк
системные запросы перестали терять служебные колонки (0 → 384 из 641 ячеек), группа `derived`
появилась (0 → 79), количество работы перестало путаться с номером позиции.

Измерение разделено: `les.query-measurement.v1` на пакет даёт по каждому запросу
`found / model_visible / not_visible / cards_omitted / chosen_rows` и группует их по
происхождению, а rollup держит число пакетов и каждый счётчик отдельно. Сравнивать суммарное
`found` нескольких пакетов с `model_visible` одного последнего вызова как единую потерю нельзя.

`found` — это пул, который поиск сматчил, а не срез, который пропустил
`model_evidence_k`. Замер 824/826/827 давал `found = 6` на каждом запросе именно потому,
что счёт снимался после обрезки: две величины неразличимы по построению, и потеря,
которую приносит потолок, невидима для любого читателя отчёта. Оба retriever и так
сообщали немодифицированный пул — `fusion_candidates` в браузере норм и `merged_count`
в каноническом RRF, — но инструмент его выбрасывал. Теперь число несёт каждая
доставленная карточка (`meta.matched_before_cap`), payload вызова добавляет
`matched_before_cap`, `verified_before_cap` и `evidence_cap`, а строка замера держит
`returned_within_cap` рядом с `found` и `found_basis` в одном из трёх состояний:
`pre_cap_pool` (потолок срезал реальный пул), `pool_within_cap` (пул уместился целиком),
`pool_not_reported` (число не пришло — запись кэша до 828 или пустой пул; падать на
`returned_within_cap` без метки означало бы выдавать потолок за объём базы). Поле
живёт в meta карточки и в payload: в промпт оно не рендерится, поэтому ни один
символ модельного входа от замера не зависит. Глубина поиска, `candidate_k` и
`model_evidence_k` не изменены — измерено то, что уже было.

`finish_reason=length` на вызове списков запросов обрабатывается адресно: последняя оборванная
строка не исполняется как запрос, модель просят дописать именно её (один раз), а список, в котором
что-то объявлено, не запрашивается заново. На пакет отведено не больше
`_MAX_SHEET_PASS_QUERY_CALLS = 3` вызовов — объявление, одна починка формата, одно продолжение;
наращивание числа попыток дефектом не считается.

## Таблица решения: reader и quality gate читают один и тот же формат (блокер § 1 и § 3, 29.09)

Reader ответа и gate закрытых статусов перечитывают один и тот же модельный текст:
если они разошлись в том, что считать строкой таблицы, решение модели попадает в
документ из одного текста, а оценивается по другому. Формат читает
`proxy/services/model_answer_table_service.py`, и reader
(`parse_model_rag_result`), и `parse_quality_table` вызывают его.

Разобрались три записи, каждая — по сохранённому в установленной версии ответу:

- `[Источник 1] | source_row | … |` — метка, которую требует сам prompt, приклеена к
  строке заголовка (чат-строка 506). Строка не начиналась с `|`, заголовок не
  узнавался, и обе позиции строки (`АР!R49`, `АР!R64`) пропадали: `parsed_rows = 0`
  при том, что модель решение записала. Снятие только этой метки — правка
  оформления; текст ответа возвращается дословно, значение каждой ячейки остаётся
  своим.
- `|:--|:--|` — выравнивающая ячейка из двух (и одного) дефиса (чат-строки 53, 55,
  76). С 8007b38a reader требовал не меньше трёх дефисов, и таблица из 38 строк
  ВОР!R4…ВОР!R41 не читалась вовсе.
- `source_row | row_role | …` без внешних `|` (чат-строка 330): внешние `|` в
  markdown необязательны, а reader на первой такой строке останавливался, и
  все разделы ниже первого терялись.

Обратная сторона терпимости: строка, которая заметно уже таблицы и не открыта как
табличная, — проза, и таблица на ней заканчивается; такой текст не дописывается
пустыми ячейками до «решения». Модельный `[Q4.H1]` или значение в квадратных
скобках внутри ячейки меткой не считается и остаётся в ячейке.

Измерено на всём сохранённом корпусе ответов (369 ответов с `|`, read-only
`chat_history`; `stage_b/live_829/rendering_diff_829.json`): восстановлено 5
ответов, которые не читались совсем (+128 позиций), изменено 8 ответов — строго
прирост (+286 позиций всего, 14470 → 14756), потерянных ответов и строк нет
(`lost_answers = 0`), и по 13 затронутым ответам каждая строка, прочитанная раньше,
присутствует после правки дословно, а текст ответа возвращается без изменений
(`stage_b/live_829/additivity_829.json`). Ни одно поле модели не заполняется и не
переименовывается кодом: reader стал читать то, что модель уже предъявила.

## Надёжность и readiness

- Параллельный model request ждёт публичный semaphore API до bounded timeout;
  приватный `_value` не читается. Отмена освобождает только реально полученный
  permit.
- HTTP/SSE/model-visible tool result получают стабильный код и операторский
  текст; класс исключения и diagnostic detail остаются в логах/trace.
- Readiness разделяет `backend_available`, `contract_complete`,
  `optional_stages` и per-query `query_quality`. Слабый отдельный запрос не
  делает исправный backend или контракт красным.
- RAPTOR по умолчанию `off`. ColBERT вызывается только при status `ready`,
  закрытом breaker и audited active-generation contract с полной multivector
  readiness; отсутствие такой генерации — обычный `not_ready` bypass.
- Приёмочный runtime может выставить
  `LES_STARTUP_BACKGROUND_MUTATIONS=false`: startup тогда не запускает repair,
  generation reconciliation и resume supervisors. Default остаётся `true` и
  виден в runtime registry.
- Admission различает загрузку точной локальной answer-model и чужой модели.
  Для уже резидентной модели действует отдельный жёсткий RAM floor; swap guard
  сохраняется. Chat не заменяет выбранный Ollama/MLX provider по уровню RAM.

## Точки входа

В 0.31.86 готовая ревизия файла в восстановленной сессии возвращается в панель после перерисовки истории, чтобы `chat.py` не очищал ссылку на скачивание. Readiness ЛСР считает цену закрытой только при определённом и согласованном базисе; состояние `unspecified` требует выбора города и уровня цен, а отсутствие книги или противоречие периоду остаются видимым блокером. Если исходный каталог имеет позиции, а модель дала только материалы/оборудование и ни одной работы, `missing_work_layer` оставляет смету незавершённой. Это проверка результата после решения модели: она не выбирает норму и не подменяет модельный ответ.

- `proxy/services/chat_profile_service.py`
- `proxy/services/retrieval_candidate_service.py`
- `proxy/services/retrieval_service.py`
- `proxy/services/model_research_tool_service.py`
- `proxy/services/model_evidence_read_{contract,service}.py` — optional reads,
  literal body registry и технические stop conditions.
- `proxy/services/model_lsr_result_contract.py` — один условный контракт полей.
- `proxy/services/model_result_packet_service.py` — admission/unapplied proposals.
- `proxy/services/model_pricebook_evidence_service.py` и
  `proxy/services/model_price_provenance_service.py` — чтение закреплённой книги
  и механическая сверка authored цены с cited evidence.
- `proxy/services/fgis_price_service.py:get_pricebook` — официальный snapshot
  reader/cache по exact source bytes.
- `proxy/services/chat_evidence_application_service.py`
- `proxy/services/model_answer_table_service.py` — один формат таблицы решения для
  reader и quality gate; снимает только оформление строки, смысл ячеек не трогает.
- `proxy/services/lsr_candidate_query_service.py` — автор `original`/`derived` запросов сметного
  sheet-pass (ADR-16); норму не выбирает и решение модели не подменяет.
- `proxy/services/lsr_source_coverage_service.py` — покрытие по всем ролям
  локатора; last-write одной роли больше не закрывает и не ломает пакет.
- `proxy/services/lsr_result_readiness_service.py`
- `proxy/services/workbook_research_job_service.py`
- `proxy/services/chat_evidence_manifest_service.py`
- `proxy/services/chat_capability_scope_service.py`
- `proxy/services/source_locator_service.py`
- `proxy/services/runtime_admission.py`
- `proxy/services/web_{research_config,search,page_reader}_service.py`
- `proxy/services/rag_{readiness,pipeline_status,advanced_policy}_service.py`
- `sovushka/pages/{chat,profiles,diag}.py`

Активный exact reader: `proxy/smeta_core/norm_browser.py:read_norm_card_exact`.
Исторический `document_workflow` не становится активным ядром чата.

### 867: terminal текущего пакета и независимые evidence cursors

`sheet_pass_question_tail` ограничивает ответ текущим исходным пакетом. Его
неусечённый terminal сохраняет авторские строки и завершает именно этот пакет;
следующее предложение содержит только ещё не показанные исходные строки. Даже
если модель не вернула решение части пакета, приложение не придумывает строки:
их locators остаются в source coverage gap и durable `remaining`.

`workbook_research_jobs.held_packet_json.terminal_packets` накапливает отдельные
snapshots с packet identity, literal queries, query offset, provenance и
addresses. `record_packet` и `pause` атомарно сохраняют предыдущие snapshots при
смене активного курсора. Query cache и immutable evidence с признаками реально
показанных bodies/native reads сохраняются отдельно; restart и document lineage
переносят их вместе. Схема SQLite не меняется. `reopen_locators` отдельно отмечает
явно открытые пользователем строки, не переписывая evidence snapshots.
Такой reopen сохраняет текущие operation IDs/revisions и пользовательскую
инструкцию в review baseline. При незавершённом предыдущем review его ещё не
пересмотренные решения сохраняются; после завершённой ревизии удалённые старые
операции из исторического baseline не восстанавливаются. Эта граница действует
по terminal конкретного исходного пакета, даже если другие пакеты ещё открыты;
повторный явный reopen до нового terminal сохраняет текущие IDs/revisions.

Same-request replay не предлагает закрытые пакеты повторно. Неиспользованные
кандидаты остаются для явного уточнения; их непрочитанные страницы не являются
source omission или требованием нового предметного ответа. Готовность документа
определяют source coverage, авторские proposals, доказательство выбранной нормы
и цены. `status_dimensions.deferred_evidence` отделяет Qx.Hy от пропущенных
исходных строк. Native requests до terminal и transport continuation усечённого
ответа сохраняют прежний путь. Расчёт и XLSX выполняются после прохода новых
пакетов без дополнительного предметного вызова модели.

Регрессии: несколько terminal пакетов с 35 запросами, native card/price reads,
неполный первый ответ без повторного предложения готовых строк, сохранение всех
cursors/cache/evidence после restart и lineage, явное снятие packet marker.
Offline gate не доказывает качество: обязательна installed live-проверка той же
318-строчной ВОР, model/provider/source/scope/pricebook identity и сравнение с B0.

Native continuation передаёт `NativeToolExchange` целиком через ContextGovernor:
assistant content и исходные function arguments/IDs сохраняются, каждый tool
reply связывается с тем же ID и содержит receipt с новыми immutable Qx.Hy refs.
Полные тела карточек остаются одной копией в required evidence registry. Native
batch с недопустимыми ID/arguments, неизвестным tool, повтором либо превышением
лимита не исполняется частично; transport protocol не меняет решение модели.

Query failure передаёт приватный typed `ModelQueryFailure` через provider wrapper
в существующую error history. `retrieval_trace` сохраняет session/model/connection
facts, finish reason, tokens/budget, counts/reasons declared parse и final text
последних восьми query calls (до 8192 символов каждого, с явными признаками
ограничения). Hidden thinking и credentials удаляются до ограничения текста.
SSE/HTTP error содержит только безопасные code/detail; arbitrary HTTP detail не
может подставить диагностический trace. Правила парсера и запросы модели не меняются.
