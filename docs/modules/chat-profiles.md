# Chat profiles

## 946 — частичный переопрос сохраняет измеряемый набор возможностей

`CapabilityProbe.probe_and_store` заново проверяет объединение requested и
наблюдений `evidence_source=probe` последнего snapshot той же immutable revision.
Состояния SUPPORTED не копируются из прошлого: текущий отказ/UNKNOWN заменяет
старое измерение, новый TTL относится только к заново измеренным возможностям.
Непроверенные/template-наблюдения и другая revision не расширяют набор.
Ранее сохранённый узкий snapshot восстанавливается штатным полным переопросом.

`ModelCapabilityError` отделяет локальный отказ допуска от ошибки провайдера:
HTTP409 с `CAPABILITY_REQUIRED` либо `CAPABILITY_EVIDENCE_INSUFFICIENT`, без
вызова другого подключения и деградации в повторный ответ. Точки входа:
model_capability_service, openai_compatible_transport_service,
canonical_route_service и общий catch активного chat. Регрессии:
test_model_capability_service и test_model_capability_admission_946.

<!-- candidate939-proof-kind-sampling:v1 -->
## 939: optional sampling в immutable model connection

top_p, top_k и presence_penalty задаются в «Модели и подключения» существующими
очищаемыми number controls. Пустое значение означает default backend; явный0
presence_penalty остаётся0. Источник — операторская immutable revision,
перезапуск не нужен; edit/copy не переназначают ANSWER. API не принимает bool,
строки, NaN/Infinity, дробный top_k или значения вне контрактного диапазона.
Probe и inference используют один sampling_parameters helper; unsupported
параметры не удаляются при retry. Подробный контракт — ALGO-context-memory.
Пользовательский профиль и старые подключения не мигрируются автоматически.

## Кандидат938: автор пересборки и внешние пробелы вопроса

Пересборка accepted_rows не вызывает модель. Известные model_identity,
profile_revision_id и dataset_ids принадлежат сохранённой job.identity: пустые
поля запроса наследуются до расчётного fingerprint и executor, совпадающие
допустимы, противоречащие409 REPACK_IDENTITY_MISMATCH без новой упаковки.
Явно переданные новые decisions и jobless/исторически отсутствующие identity
сохраняют прежний контракт; неизвестный model_preset не выдумывается.
Существующие immutable ревизии не переписываются.

workbook_model_question сравнивает original.strip()==current.strip(), возвращая
буквальный current. Конечный LF/внешние пробелы fresh-запроса не создают ложное
сообщение об изменении задачи; реальные изменения, регистр и внутренние пробелы
сохраняют original/current framing. Это не обещание исправить выбор норм модели.
Живой937: repack подтверждён, B0/B1 качество не принято; RELEASE_LEDGER.

## Candidate 0.31.184 / 912 - optional export declaration in model queries

Query JSON accepts queries without an artifact_kind for source questions; explicit model vor/lsr declarations and strict invalid-metadata checks remain. Bound profile/skill and literal searches are preserved. Frozen912 offline canonical gates PASS: 4056 passed, 20 skipped, 5 warnings in 256.51s (0:04:16); mail: 66 passed, 4 warnings in 6.27s; metadata: 31 passed in 4.40s. Customer-ready false.
The source_read phase addition distinguishes answering/reading from export requirements while retaining the immutable user profile and skill literally. Model-authored explicit workbook declarations are never overwritten by an application intent guess.

## Candidate911: source-read purpose

The bound immutable profile and skill remain literal. Application workbook/volume
carrier additions are omitted only for a model-driven answer without a bound
attachment/catalog and without a valid model-authored VOR/LSR declaration. The
`source_read` purpose does not infer an artifact from the question. Final model
declarations are recorded before deciding whether to parse/package a workbook.
Attached-source and explicitly declared workbook contracts remain strict.
Focused actual-producer tests include native READ and ordinary answer delivery;
installed live acceptance is pending.

Earlier entries retain their stated build/date scope.

## Бюджет облачного хода (кандидат 882)

`LES_CLOUD_TURN_TOKEN_BUDGET` виден в общем реестре Совушки как числовая,
редактируемая настройка без рестарта; default `0` сохраняет прежнее поведение.
Положительное значение ограничивает совокупный вход и полный выход назначенной
remote-модели в одном сообщении чата. Транспорт резервирует UTF-8 размер тела,
1024 служебных единицы и `max_completion_tokens + 10` перед каждой отправкой,
включая транспортный повтор. Это консервативная оценка для текстовых запросов,
не точный tokenizer или баланс Alibaba. Без полного output-cap и при мультимодальном
вводе защищённый вызов отклоняется. После полного ответа резерв заменяется
валидным `usage`; ошибки, неизвестный usage и стрим оставляют резерв списанным.
Запрос, который не помещается, не отправляется; `CloudBudgetStop` не активирует
fallback. `retrieval_trace.cloud_token_budget` содержит счётчики без текста/ключей.
881 сохраняет их и при отказе через typed `ModelExecutionFailure`, HTTP/SSE и
историю; `ModelQueryFailure` наследует тот же закрытый диагностический канал.
`reported_tokens` отделён от `unsettled_reservation_tokens`, последняя попытка
хранит только размеры, резерв и признак отправки. SSE `cloud_budget` выдаётся
после каждого завершённого вызова/отказа, чтобы наблюдатель видел расход до final.
Внешняя ошибка по-прежнему содержит только безопасное понятное сообщение.
882 использует тот же точный wire-reservation до упаковки optional discovery
контекста: [алгоритм](../ALGO-context-memory.md). Проверка не делает HTTP, не
расходует резерв и не меняет лимит. Mandatory overflow по-прежнему останавливает
вызов; native checkpoint сохраняет текущий пакет для продолжения.
Остановка возвращает отдельный HTTP429/CLOUD_TURN_TOKEN_BUDGET, не отсутствие норм.
Новый ход, в том числе «продолжи», получает новый бюджет: это не общий лимит job
или аккаунта. Контрольная серия дополнительно ограничивает число запусков.
Код не меняет инженерные решения, запросы модели или сохранённые строки.

## Раздельное рассуждение при поиске и ответе

Необязательный boolean `model_policy.query_reasoning_enabled` входит в immutable
ревизию профиля. Отсутствие поля наследует общий `reasoning_enabled`; явные
`true`/`false` действуют только при составлении, продолжении и исправлении
поисковых запросов. Ответ и native-чтения источников сохраняют общий режим.
Невалидное значение отклоняется до записи профиля; исходная ревизия и активный
профиль не меняются при сохранении копии.

Редактор использует существующий `select_field` «Рассуждение при поисковых
запросах»: «Наследовать общее», «Включено», «Выключено». Наследование не записывает
скрытый boolean. Фактор `query_reasoning` показывает requested/effective/source
и `restart_required=False`; capability-ограничения остаются явными.

`model_rag_query_execution_preset` связывает этот режим с существующим query
reserve до ContextGovernor; тот же typed preset передаётся в `InferenceRequest`
для B0/B1 и repair. Output не превышает упакованный резерв, окно, provider,
модель и общие answer/native настройки не изменяются. Новых model calls и циклов
нет. При query failure фактические безопасные provider/model берутся из
исполненного подключения; legacy-конфигурация и requested assignment показываются
отдельно, когда соответствующие данные доступны.

Регрессии: `tests/test_model_query_reasoning.py` (immutable/API/GUI/фактор,
query/global наследование, B0/B1 repair и mocked HTTP). Это проверка transport;
живое качество модели и профессиональная приёмка требуют отдельного gate.

## 863: раздельные резервы поиска и итогового ответа

Необязательные `model_policy.query_output_tokens` и `answer_output_tokens`
задаются положительными целыми числами в версии профиля. Пустые поля в GUI
сохраняют прежние лимиты; невалидное значение отклоняется до записи ревизии.
Поля представлены существующим `text_field` в редакторе, источник и фактический
лимит каждого этапа видны в diagnostic trace/runtime-factor contract.
Сохранение копии само по себе не меняет активный профиль.

Query и answer имеют независимые резервы. ContextGovernor резервирует выбранный
output до упаковки источников и native tools, provider не превышает резерв.
Для model-RAG лимит совпадает с резервом; обязательные ограничения обычного
notebook/inventory могут дополнительно уменьшить генерацию.
Лимит ограничен уже наблюдаемым effective окном минус safety и 1024 токена
входного headroom; неизвестная ёмкость не разрешает увеличение стандартного
резерва. Ни requested/observed KV, ни модель, ни температура не меняются.
Увеличение output уменьшает бюджет evidence и может увеличить время ответа.
Явный env-cap query остаётся ограничителем внутри резерва. Без новых полей
прежние defaults сохранены, включая 8192 для model-RAG при достаточном окне.
Обычный answer сохраняет обязательные notebook/inventory ограничения.

Измеренная причина: 861 B1 query израсходовал 4095 из 4096, `length`, final пуст;
B0 query завершился нормально, answer с резервом 8192 завершился `length`
без final. Отсутствие final не объявляется отсутствием норм. Эффективность
увеличенных резервов и профессиональная приёмка требуют отдельного live контроля.

## Установлено 0.31.130 / 858: явные коды ресурсов и сравнение прежнего результата

`parse_model_rag_result` сохраняет явно написанный `resource_code` в Markdown,
inline, multiline block и labelled формах; `compact_estimator_draft_rows`
переносит его в контекст следующей страницы и пересмотра. Это поле отдельно от
`norm_code`: `positions_from_visible_lsr_rows` передаёт выбранный моделью код
ресурса в расчёт материальной позиции. Код не извлекается из названия и не
получает значения по умолчанию. Сохранение шифра не подтверждает соответствие
ресурса, наличие цены или применимость ценовой книги. `confirmed_price` и
`price_source` используют существующий контракт передачи.
Bridge описывает `resource_code` только как буквальный код уже выбранного
моделью ресурса для material/equipment; отсутствие выбора оставляет поле пустым.
Цена отдельного ресурса не объявляется подтверждённой ценой всей работы.

`model_rag_prior_page_context` отдельно предъявляет
`prior_result_structural_facts` на уже существующей следующей странице evidence
или при пересмотре. Наблюдения вычисляются заново по immutable bindings,
фактическим карточкам и исходному source catalog. `norm_reference` содержит
выбранный шифр, шифры цитированных карточек, `code_in_refs` и неразрешённые
ссылки; `code_in_refs=null` означает невозможность сравнения. `source_comparison`
показывает ошибки сравнения, известность колонки количества, исходные
quantity/unit и возвращённые моделью quantity/unit. Сравнение исходника
выполняется для всех авторских ролей, включая material/equipment/resource,
unresolved и header; факт выводится только при выявленном расхождении.
Заголовок с пустым количеством не получает придуманного объёма.

Авторские операции, роли, нормы, объёмы и точные цитированные карточки остаются
в своих полях. Наблюдения не являются вердиктом о применимости, не выбирают
замену, не меняют допуск файла и не запускают дополнительный модельный цикл.
Объёмные `_quality_gate`/`_evidence_check` dumps не возвращаются в
`prior_model_decisions`; компактные факты находятся в отдельном поле.

Механическое сравнение source quantities принимает точные м↔км и кг↔т
с теми же физическими коэффициентами, которые использует калькулятор. Отличие
объёма после пересчёта остаётся ошибкой; quantity/unit модели не переписываются.

Tests: `tests/test_model_result_resource_code.py` (14 cases) и восемь cases
`test_prior_page_*` в `tests/test_chat_evidence_application_service.py`.
Четыре прямых catalog regressions проверяют равные метрические количества
и обнаружение неравных.
E2E parse→compact→immutable evidence/catalog→RIM→XLSX доказывает передачу
выбранного кода: 12 м × 100 из выбранной тестовой книги = 1200 confirmed,
предварительных 0. Справочная цена 777 из evidence не применяется.
Сохранён red baseline: resource-code 12 failed / 1 passed, structural facts
4 failed. Итоговый canonical 2101 passed / 20 existing opt-in skipped;
verify 2121 collected, architecture/active artifacts green. Installed comparative
control завершён на том же EOM/задании/FreeToken35B: B0 38/51 адресов,
2 calculated / 0 source errors / 295.6s; B1 51/51 учтены, но 1 calculated,
18 ошибочных work/material решений / 1482.6s. В обоих model results нет
resource_code и nr_sp_rule_id. B1 сохраняет 30 nr_sp_unresolved и 43 ценовых
пробела. Technical packaging passed, estimate_complete=false; customer gate
FAILED. Подробные receipts и SHA — RELEASE_LEDGER. Транспортный гейт не
подтверждает качество конкретной сметы; исправление поля не доказывает, что
модель его выбирает, а предъявление сравнения не гарантирует исправления выбора.

857 UI transport: `view=progress` on job/last/active drops only bulk
evidence and query_cache from the HTTP response, retaining authored rows,
identity, task, held cursor, remaining scope and recovery projection. Default
full response and all durable data remain unchanged; the model uses full state.
Own 854 checkpoint is 17,643,398 bytes pretty JSON; UI does not need raw cards/cache.
Three route regressions preserve full reads/source dictionaries; focused UI/API
212 passed. This reduces polling traffic, not generation time. Installed size
measurement and browser recovery after the ongoing 856 controls remain pending.

856: новые sheet-pass пакеты получают Q/H identifiers после максимального
сохранённого model_evidence_ref, включая evidence прежнего review.
Старые карточки/ссылки/решения остаются дословными; held page продолжает
сохранённый query_offset. Нумерация идентифицирует evidence, не меняет query
или профессиональный выбор. GUI progress показывает группы текущей страницы,
а omitted-card trace использует тот же offset. Live comparative gate обязателен.

## 852: исходная задача сохраняется и в запросе модели

Source packet: `catalog_sheet_packet_facts` отдельно перечисляет requested и
reference source locators, передаёт точные значения доказанной колонки количества
и её единицу. Пустая/неопределённая ячейка остаётся null, неизвестная колонка —
quantity_column_known=false без придуманного количества. Дословный исходник
остаётся одновременно в том же ContextGovernor packet. Нет переклассификации,
выбора нормы, удаления авторской операции или назначения нулевого объёма.
Live 851: actual quantity-bearing rows больше не смещены, но группа без количества
возвращалась material трижды на разных packets. Source scope/quantity facts
устраняют эту неоднозначность передачи; профессиональную готовность доказывает
только новый installed control, не этот текст и не unit tests.

UI: выбранный из истории чат получает только принадлежащий ему progress;
предыдущее pending очищается, поздние API-ответы другой сессии игнорируются.
Совместимое восстановление ночной задачи вне history selection сохраняется.
Live 851: current VOR скачан кнопкой в Downloads, SHA совпал с API; история
вместе с этим показывала progress другого активного контрольного чата. Три
новых regressions воспроизводят prior retention, foreign adoption и pinned job.

`workbook_model_question` передаёт исходный пользовательский текст вместе с
последней репликой в query и answer sheet-pass calls. Последняя реплика и
durable явные параметры target/region/quarter имеют приоритет: продолжение после
конвертации или смены квартала не возвращается к старому назначению/периоду.
Функция не меняет literal question упаковки, job identity или idempotency;
не дописывает поисковый запрос и не выбирает норму/объём. В новом задании без
прежнего контекста вопрос остаётся дословно прежним. Три regressions проверяют
original/current, перепрайсинг после restart и совместную доступность task,
source row и полной карточки в ContextGovernor. Live отдельно от unit tests.

## 851: целевой документ и родитель ревизии принадлежат заданию

`task_context.artifact_intent` сохраняет явно названный пользователем ВОР/ЛСР.
Обычный `Продолжи` и замечание без нового типа документа не меняют его;
явный запрос другого типа меняет, исходная задача остаётся в original_question.
Для прежних заданий без поля `workbook_packaging_tool` читает исходную задачу.
Предыдущие jobs дают `workbook_packaging_lineage` только родителя revision;
их последовательности не участвуют в текущем settled replay guard. Поэтому
новое замечание создаёт связанную ревизию, а повторная доставка текущего
завершённого результата сохраняет прежнюю идентичность. Независимые истории
вне continues_job_id цепочки не выбирают родителя.

`catalog_sheet_pack_lines` сохраняет дословные строки с пустой известной
колонкой количества как контекст текущего листа. Нумерованное описание группы
может быть ambiguous, но нужно модели рядом с кратким вариантом изделия.
Строки с количеством вне текущего пакета по-прежнему исключаются. Это не
выбор технологии/нормы, не восстановление количества и не переклассификация.
Четыре durable target/lineage и два source context regression cases;
live gates и профессиональная правильность проверяются отдельно.

## 850: свободное замечание и продолжение пересмотра

`workbook_chat_review_context` читает latest review из lineage события
`locators_reopened`: сохраняются исходное замечание, прежние authored rows
и их operation IDs. Обычный `Продолжи` не теряет этот контекст. Обе ветки
пакетного запроса/ответа передают точные прежде цитированные карточки через
`model_rag_prior_page_context`, а не только названия норм и старые Qx.Hy.
Валидация знает IDs baseline и принятых новых ревизий; неизвестные IDs и
перенос операции на другой source остаются ошибками. `record_packet` сохраняет
тот же ID и следующую ревизию для операции, которую модель сама вернула.
Baseline — контекст, не источник автоматического восстановления accepted rows.
При новом замечании к неполному пересмотру baseline не теряется; после полного
результата удалённые моделью операции не восстанавливаются. Pending queue/held
page и подтверждения оператора наследуются даже до первого принятого решения.
Пять regression cases; installed comparative gate отдельно от offline проверок.

## 842: непротиворечивый контракт роли и повторной операции

Основной `lsr_result_table_instruction` явно требует вернуть назначенный
приложением operation_id прежней операции (для новой — пустой), а не только
вложенный prior-page hint. Изменённая норма или пояснение — авторская ревизия;
дополнительная работа — новая операция. Роль work означает технологическую
операцию и не требует нормы для создания ВОР. Для ЛСР отсутствующая норма
остаётся явным вопросом. Для каждой выбранной нормы требуются пять авторских
match fields; unknown не подменяется yes. Монтажная норма относится к работе,
а не к цене изделия. Текущий пакет не даёт основания утверждать, что в
остальных строках исходника нет нужных данных. Нет model/schema handshake,
промпт не выбирает шифры и не изменяет выбранные моделью поля.

## 839: основания НР/СП доходят до модели и расчёта

Dedicated norm RAG передаёт все строки установленного каталога НР/СП для
сборника карточки: rule_id, вид/условия работ, проценты, основание, typed source_ref
и SHA исходных документов. Пути исходных файлов не передаются. Это exact reader
каталога, не выбор подходящей ставки, не изменение RRF или применимости нормы.
Модель выбирает `nr_sp_rule_id` по условиям объекта либо оставляет вопрос.
`parse_model_rag_result` сохраняет поле в таблице, inline, block и labelled форме;
`compact_estimator_draft_rows` — в контексте пересмотра. `positions_from_visible_lsr_rows`
передаёт его штатному `nr_sp_service.resolve`: чужой сборник отклоняется, отсутствие
выбора при нескольких строках остаётся ambiguous, проценты не угадываются.
До исправления живой 837 СКС имел две привязанные нормы с nr_sp_unresolved:
модель не видела варианты, а даже явно возвращённое поле терялось в decoder/adapter.
Budget renderer сохраняет обязательный prefix shown typed карточки целиком,
включая источник/условия/основания НР/СП; сокращаться может обзор ресурсов.
Если prefix не помещается, карточка явно omitted, не частично обоснованная.
Это не утверждает, что все найденные кандидаты помещаются в один контекст.
Regression 7 cases failed before, focused related suites 248 passed after.
Живой финансовый gate и профессиональный выбор остаются отдельной приёмкой.
Installed 839 evidence: SKS 75/75 but 0 calculated works; PDF LSR has 6 numerical
positions yet lacks applicability match fields on those EXACT rows. Current
exact-citation policy accepts same-cipher references without those fields;
this release does not change that policy or call those sums an expert acceptance.
PDF VOR still has 3 incomplete unit/quantity rows. See RELEASE_LEDGER/live_839;
these limitations are retained, not hidden behind offline test counts.

## 838: наблюдаемая дата и каталог цен до исследования

`model_runtime_facts` добавляет в обязательный profile prefix UTC дату приложения.
Только estimator/tabular bridge получает имена файлов из typed pricebook catalog,
без путей и цен. Наличие файла не утверждает применимость/полноту; ставка и база
не выбираются этой функцией. Список ограничен 2048 символами по целым именам,
с полным количеством и `pricebook_inventory_complete`. Не-smeta профили не
читают каталог. Короткий skill отличает дату выполнения от памяти обучения,
а частичный перечень — от отсутствия книги. Это закрывает live 837 baseline,
который отказался, ошибочно назвав III квартал 2026 будущим и книгу отсутствующей.
Структурный контракт и финансовая приёмка остаются отдельными проверками.

## 837: ВОР не зависит от подбора нормы, вопросы модели сохраняются

Короткий estimator skill разделяет ВОР (операции/единицы/объёмы) и ЛСР
(дополнительно нормы/ресурсы/цены). Отсутствующая норма не делает известную
работу ВОР неопределённой. Код не меняет авторские роли или вопросы.
`build_vor_result_readiness` предъявляет `open_gap` и unresolved позиции;
`technical_complete` означает доставленный файл и прочитанный исходник,
`vor_complete` дополнительно требует отсутствия открытых вопросов. До правки
fresh PDF 837 имел две unresolved строки с вопросами, но `open_questions=[]`.
Regression сохраняет количество и роль, проверяет независимость от норм/цен
и структурные ошибки. Полнота ВОР не равна профессиональной приёмке ЛСР.

## 835: свободное замечание к сохранённому документу без JSON-барьера

Новая реплика не равна автоматической пересборке. `workbook_chat_review_needed`
сохраняет быстрый путь только для обычного продолжения/повтора задачи. При новом
замечании `begin_workbook_chat_review` повторно предлагает весь исходный документ
в обычных пакетах query → RAG → result. Обязательный JSON-план из 834 удалён:
он провалился на установленной модели и противоречил отсутствию planning-gate
перед RAG. Код не угадывает предметный поднабор строк; та же модель получает
замечание и прежние решения пакета, сохраняет либо меняет их и объясняет пробелы.
Свободное замечание требует нового прохода документа; обычное «Продолжи» его
не запускает. Точный выбор строк по номерам доставленной ЛСР остаётся в GUI.

`reopen_locators(chat_review=…)` записывает замечание пользователя и полные `prior_rows`
в долговечное событие, сохраняет операторские подтверждения. Предыдущие решения
данного пакета передаются модели как обязательный контекст, включая все пять
признаков применимости и цитаты. Повторный вход с тем же запросом продолжает
очередь; новая реплика может запустить новый пересмотр.
Digest исходного запроса родителя поддерживает старые jobs без текста задачи.
Регрессия: `tests/test_workbook_chat_refinement.py`; установленная приёмка обязана
подтвердить реальные model calls и новую ревизию, а не один token статуса.

Обязательный формат таблицы в `profile_system_prompt` перечисляет все пять
признаков применимости и `coverage`. Их отсутствие в 9 сохранённых строках СКС
с шифром измерено на 832; skill требовал признаки, а последняя инструкция о
таблице их не перечисляла. Значения задаёт модель по карточке; код не дописывает
yes и не повышает вердикт.

## 833: тип ВОР при восстановлении документа

`workbook_document_from_events` определяет тип по сохранённому инструменту
упаковки. Чат, последнее задание и repack используют этот тип: ВОР восстанавливается
через `build_vor_workbook` с собственной цепочкой ревизий. Для ВОР не создаётся
карточка готовности ЛСР и не требуются нормы/цены. Repack использует общий
`workbook_packaging_args`: поле `confirmed_data` и ценовая база передаются только
ЛСР, иначе реальная валидация ВОР возвращает `TOOL_SCHEMA_INVALID`. Regression:
`test_packaging_recovery_service.py`, `test_chat_evidence_application_service.py`.

## 832: сохранять явные решения и привязку цитат

`parse_model_rag_result` принимает явную однострочную форму
`source_row=…, title=…, unit=…, norm_code=…` наравне с Markdown-таблицей.
Значения, в том числе запятые в наименовании и десятичные запятые, сохраняются;
дубли полей, конфликт locator в префиксе и произвольная проза не принимаются.
Повторное чтение неизменённого ответа live 831 восстановило 36 из 48 потерянных
locator (72 → 108 из 120). Остальные строки этим исправлением не закрыты;
профессиональный вердикт не повышается.

`bind_row_evidence_ids` проверяет сохранённую цитату по `global_evidence_id`:
Q/H — локальный alias пакета, повторение alias в другом пакете не подменяет
карточку. Новая строка с неоднозначным alias остаётся без подтверждённой ссылки.
Сметный контракт требует явные признаки применимости и исключает повторное
начисление нормы за входящие в её состав операции. Regression:
`test_chat_evidence_application_service.py`; профессиональная приёмка — live.

## 831: исходный запрос, обязательные строки и монтаж из спецификации

`WorkbookResearchJobService.begin_or_resume(task_context=…)` сохраняет исходный
запрос и явно названные регион/квартал до первого результата модели. Аддитивная
колонка `task_context_json` не меняет identity/hash существующих jobs. Контекст
наследуется для того же attachment/source SHA даже без принятых решений; иной
SHA ничего не наследует. Применённая при упаковке книга обновляет этот контекст.
`task_document_price_basis` заполняет разрыв до первой упаковки на sheet-pass,
native packaging и repack. Явная смена периода снимает старую книгу; эквивалентные
формулировки сохраняют идентичность вызова. Отсутствующая книга не заменяется.

`govern_inference_messages(required_evidence=…)` сохраняет целиком исходные строки
текущего пакета и полный манифест листов как обязательный контекст; найденные
карточки остаются бюджетируемыми. Переполнение обязательной части явно ошибочно,
а не скрытое усечение. Это не обещает, что модель правильно решит каждую строку.

Заводской профиль читает профессиональный контракт из
`skills/smeta/references/rag-estimator.md`: модель выделяет операции из изделий,
возвращает реальные связи поставки с работами, проверяет двойной учёт и происхождение
норм/цен. Существующие пользовательские immutable snapshots не переписываются:
табличный capability bridge добавляет этот же короткий контракт к effective
snapshot текущего запроса и сохраняет его путь/хеш в `effective_skill_modules`.
Повторное подключение не дублирует текст; пользовательские правила сохраняются.

Прогресс sheet-pass показывает обработанные исходные locator отдельно от числа
строк без структурных пробелов. Монтаж не считается подтверждённым по одному
статусу обработки. ETA использует обработанные locator, а не полноту расчёта.
Регрессии: `tests/test_workbook_task_context.py`, профиль, repack и чат.

Build 775 result instruction uses ten core columns and adds conversion,
coefficient and assessment fields only when applicable. It preserves source
locator/unit/quantity while allowing the model to name a derived installation
work; the previous mandatory verbatim product title contradicted that task.
No norms or installation operations are chosen by code.


Build 775 also requires an explicit code/norm_code cell to contain only a
code (formatting and colon prefixes are accepted). It never extracts a rejected
norm from shifted explanatory prose. Original cell text remains in the binding.


## Build 815: три происхождения поисковых запросов в профиле «Сметчик»

ADR-16 (`docs/ADR-16-systematic-candidate-retrieval.md`) касается только активного профиля
`estimator` на табличном sheet-pass: системный сбор включается по effective snapshot
(`mode == estimator`) и по фактору `LES_LSR_SYSTEM_CANDIDATE_QUERIES`. Каждая исполненная
поисковая группа помечена `query_provenance`: `model` — запрос, написанный моделью (её заголовок
остаётся прежним байт в байт), `original` — дословный исходный текст строки каталога, `derived` —
тот же текст плюс только явно представленные в исходнике атрибуты (заголовок раздела листа и
написанный в ячейке шифр). Кодовые группы помечаются по-русски — «дословный исходный текст
строки» и «системный подбор по атрибутам этой строки» — и добавляются после запросов модели, а не
вместо них: инструкция sheet-pass явно сообщает модели про эти группы, она вправе добавить свои
запросы и отклонить всех предложенных кандидатов. Метка входит в бюджет заголовков `Qx`.

Границы: обычный пользовательский dataset/chat-прогон и quality-diagnostic-раунд остаются
model-only — там происхождение проставляется явно (`_model_only_query_provenance`), а не падает в
default; сравнительный baseline `B0_DIRECT` системные запросы не исполняет вовсе и пишет в trace
`system_candidate_queries.status = skipped_baseline`.

Запросы автора кода собираются из дословных значений ячеек: токен, которого нет в собственных
строках этого запроса, отбрасывает весь запрос, и отбрасывание видно в trace как
`dropped_ungrounded` с `reason = query_token_not_in_source`; ничего из текста строки не выводится.
Два видимых в Совушке фактора категории `smeta` применяются со следующего запроса без рестарта:
`LES_LSR_SYSTEM_CANDIDATE_QUERIES` (default `on`; выключенный возвращает путь «только запросы
модели») и `LES_LSR_SYSTEM_CANDIDATE_MAX` (default `24`; технический предел числа кодовых запросов
на пакет строк, достигнутый предел не означает «норма отсутствует»). Норму код не выбирает и
применимость не решает. Tests: `tests/test_lsr_candidate_query_service.py`, `test_adr16_*` в
`tests/test_chat_evidence_application_service.py`. Это проверка wiring и происхождения запросов, а
не доказательство профессиональной правильности на живом документе: установленная приёмка ещё не
проводилась.

## Build 775: decorative table separators cannot erase decisions

The labelled table header determines the columns. A nonempty Markdown divider
containing valid separator cells may have a different width; data cells and
professional decisions are unchanged. Invalid separator tokens remain rejected.
Each sheet-pass trace records parsed_rows, kept_rows and row_errors so losses
between reading and acceptance can be distinguished. History 162 replay reads
143 authored rows across attempts instead of 12; this is not proof of selected
norms or a priced estimate. Missing norms and malformed authored cells remain
open. Tests: test_chat_evidence_application_service.py.


## Build 774: material+work на одном локаторе

Спецификация может отдать и материал, и монтажную работу на одном `source_row`.
Дубликат считается только для одной и той же роли; merge — first-wins на пару
(locator, role). Authored `row_role` задаёт `model_rag_row_kind`, поэтому
материал не проходит work-гейты evidence. Лишние `|` внутри title сливаются в
ячейку названия, строка не отбрасывается целиком. История 161: шифры R28–R38
больше не должны выжигаться из‑за пары material+work. Код по-прежнему не
выдумывает ГЭСН.

## Build 773: одна числовая ячейка не уничтожает таблицу

Reader сохраняет исходный текст нечисловых полей quantity/calc_quantity/
conversion_factor/confirmed_price во всех поддержанных текстовых формах.
Расчёт требует числовые quantity и confirmed_price; нечисловой conversion_factor
или calc_quantity создаёт needs_input с invalid_field/authored_value и не
подменяется первым числом из выражения или другим количеством. Соседние строки
продолжают рассчитываться. Это не вычислитель выражений и не исправление норм.
Реальный ответ 160 теперь читается целиком (6 строк); live release acceptance
фиксируется отдельно в RELEASE_LEDGER.

## Build 772: безопасная подготовка FreeToken

Чтение настроек только наблюдает KV (`probe_freetoken_cache`), не запускает
перестройку. ACTIVE выбирает cache target по extension фактического answer
connection, а не по старому env provider (Ollama в history 158 при ответе FreeToken).
ACTIVE и legacy подготовка кеша в chat-evidence использует тот же
generation semaphore, что генерация. Отмена ожидающего HTTP-запроса не освобождает
слот до завершения уже запущенного worker перестройки. Это защита от конкуренции
внутри процесса LES, а не блокировка внешних клиентов FreeToken.
Регрессии: `tests/test_freetoken_cache_profile_service.py` и
`tests/test_proxy_routers.py`. Live B0_DIRECT/СКС и установленный 772 не проверены.

## Build 768: пузырь не падает на UTC-метке

ETA считает aware `created_at` без TypeError; иначе typing-пузырь не
рисуется.

## Build 767: История снова показывает живую сборку

Открытие «выполняется» подтягивает checkpoint и рисует пузырь, даже если
в истории нет PENDING.

## Build 766: знаменатель 75, не 65

N/M — work-локаторы каталога. 35/65 была ошибка: материалы + leftover.
Текущий пакет показывает оставшиеся поисковые запросы.

## Build 765: СКС 35/65, не 0/30

Пузырь считает закрытые source-строки (включая material/equipment), если
work-role пуст. «С начала задачи» — прошедшее время, не остаток.

## Build 764: прогресс не сбрасывается старым ответом

Follow смотрит только текущий ход. Старое «ЛСР не создана» в той же сессии
не завершает ночную сборку и не стирает N/M.

## Build 763: реконнект показывает текущий N/M и ETA

Обрыв SSE больше не обнуляет прогресс. Совушка опрашивает checkpoint
sheet-pass (тот же SQLite, что пишет proxy) и пишет в пузырь принятые/всего,
остаток, лист/этап, сколько уже идёт и «готово примерно через». Новый
примитив не вводится.

## Build 762: одно окно «сборка продолжается»

Реконнект NiceGUI больше не пишет «Связь с окном чата пропала» и не
дублирует «Запрос выполняется» с исходным вопросом. Один пузырь с
последним счётчиком строк. Сокет UI ждёт 12 часов.

## Build 759: ночная ЛСР переживает обрыв окна

Обрыв SSE (закрытие вкладки, пропадание сети, рестарт UI) сразу отвязывает
ответ от уже созданного runner: закрытый HTTP-поток не отменяет sheet-pass и
не ждёт его завершения. Пузырь пишет, что сборка идёт на сервере; утром сессия
подхватывает PENDING→файл. Повторный «Продолжить» ждёт живой loop, а не
стартует второй. Явная «Остановить» по-прежнему pause API. Рестарт процесса
proxy останавливает process-local runner.

## Build 757: продолжение ЛСР видно как продолжение

Кнопка «Продолжить незакрытые строки» не подставляет исходный «Собери ЛСР»
в пузырь. Видно «Продолжаю незакрытые…», счётчик принятых/оставшихся строк,
режим Сметчик и оценка «готово через» сразу по прошлому темпу. Поиск по
уже принятым решениям не повторяется.

## Build 756: продолжение ЛСР без English slot-stack

Кнопки готовности («Продолжить незакрытые строки», пересборка, уточнение,
подтверждённые данные) вызываются через `asyncio.create_task` и больше не
зовут голый `ui.notify`. Toast идёт в слот чата; сбой toast не отменяет
`send_chat`. XLSX регистрируется до перерисовки черновика в «Артефактах».

## Build 755: оценка «готово через» и слот артефактов

Пока идёт sheet-pass, под секундомером — отдельная строка
«Результат будет готов примерно через ~XX». Оценка по `completed/total` после
первой принятой порции; дни только если прогноз ≥ 24 ч. Точного часа нет.
Toast «новый файл в артефактах» входит в виджет чата, иначе NiceGUI после
длинного СКС писал English slot-stack в панель «Артефакты», хотя XLSX уже был.

## Build 754: очередь модели и мастер запуска

Ожидание слота генерации — `LES_MODEL_QUEUE_WAIT_SEC` (по умолчанию 1800),
видимый фактор без рестарта. 45 с больше не обрывают второй запрос, пока
собирается ЛСР. Мастер запуска идемпотентен: повтор «Запустить ЛЕС» во время
boot не ошибка; живой UI открывается сразу.

## Build 752: пустой поиск не рвёт таблицу ЛСР

`search_sources` со `status=missing` (ноль карточек) больше не обрывает
sheet-pass. Остальные запросы модели и вызов таблицы строк идут дальше;
пустая группа видна модели, нормы код не подставляет. Abort только при
`blocked`/ошибке RRF. Если таблица так и не пришла, notice отдельно от
ошибки разбора колонок.

## Build 771: 35B получает заводское окно в начале хода

Bound ACTIVE чат больше не оставляет live `num_pages≈8214` на весь overnight
прогон. Если модель 35B, а запрошенное/живое окно < 16384, код поднимает
запрос до заводских `35000` и один раз вызывает loopback rebuild до первого
generate. Пакеты внутри хода KV не трогают. Settings GET/save используют тот
же lift, чтобы карточка настроек не сжимала 35000 обратно в исторические
`8253`. Если после rebuild живой KV всё ещё < 16384, ход 503, а не тихий
`qwen-9b-restrictive`.

## Build 751: FreeToken KV без OOM и без урезания 35B

Запрошенное окно по умолчанию — заводские `35000` токенов 35B, не исторические
`8253`. Rebuild loopback-кэша сам ужимает запрос до `max_feasible_kv`
(минимум MoE + 128 MiB safety), поэтому слишком большое GUI-значение не
роняет движок. Bound ACTIVE чат не пересобирает кэш во время генерации: он
читает живые `num_pages` и по ним выбирает `qwen-35b-extended`, если
наблюдаемый KV ≥ 16384. Физический потолок GPU может быть выше 35k; LES его
не занимает, чтобы не красть expert cache и не растягивать prefill.

## Build 744: пакетный путь = правило БАП

Обычный sheet-pass больше не запускает обязательный verifier и не ставит
кодовые заглушки `MISSING`/`CONFLICT` при исчерпании попыток. Первое принятое
решение модели по locator остаётся; оставшиеся строки живут в checkpoint.
`empty_retrieval` не ставится, пока модель ещё должна сформулировать запросы,
а фактические LLM/search вызовы пишутся в `actual_model_calls`. Остановка
пакетов — `paused`; повтор того же вопроса продолжает remaining и берёт кэш
поиска. Живой `pause` останавливает текущий цикл: `should_cancel` смотрит
статус `paused`, а не только флаг, который `pause()` сбрасывает.
`POST /api/chat/repack-lsr` и кнопка «Пересобрать файл» не вызывают
модель. Если задание приостановлено, уже имеет сохранённые решения, но ещё
не имеет файла, `document.needs_document` предлагает эту же пересборку как
черновик. Пустое или выполняющееся задание не получает действие восстановления;
наличие промежуточного файла не требует повторной упаковки. Пересборка не
переводит исследование в `complete`: необработанные адреса, решения и identity
остаются в задании, а черновик наследует его ценовую базу. Регрессии:
`test_packaging_recovery_service.py`, `test_workbook_repack_target.py`.
Сравнительный baseline задаётся полем
`comparative_acceptance_variant=B0_DIRECT`. В результате отдельно: готовность
файла, полнота норм, полнота цен, каждому пробелу — конкретное действие.

Ограниченная приёмка BAP+СКС 9B/35B, прямой baseline `B0_DIRECT`, проверка
сметчиком, stop→resume и установка точного Windows-кандидата **ещё не
проводились**. Это условие передачи сборки, не доказательство этого билда.

## Build 743: пакет заголовков запросов

Число строк ведомости по-прежнему режет sheet-pass и `adaptive_row_packet`.
Отдельно режется налог заголовков `Qn`/`Qn.Hm`: если они не влезают в остаток
окна, код не поднимает `INTERNAL_CHAT_ERROR`. Влезающий префикс идёт в ответ,
остаток запросов на sheet-pass — следующий технический пакет без нового
поиска; однопроходный путь честно пишет `omitted_evidence_refs`. Нормы и
текст запросов код не меняет.

## Build 742: наблюдаемый KV FreeToken

Пресет `qwen-35b-extended` по-прежнему требует распознанную 35B и **наблюдаемый**
KV, а не одно поле `requested_context_tokens`. Для `extension_type=freetoken`
capability probe записывает `observed_context_tokens` из
`GET /v1/cache/status` (`geometry.num_pages` или верхний `num_pages`); если
статус кэша недоступен, берётся `context_length` совпавшего id в
`GET /v1/models`. Отсутствие этих ответов не валит probe и оставляет
заводской 9B. Bound OpenAI transport на том же подключении отправляет
`chat_template_kwargs.enable_thinking=false`.

## Build 740: пропуски locator в PDF

PDF source catalog присваивает locator и строкам-разделам. Поэтому номера работ
могут идти с пропусками. Terminal-result prompt требует копировать
`source_row`, название, единицу и количество из одной строки каталога и перед
ответом сверять точный набор locator. Код не перенумеровывает и не переносит
решение на другую работу.

## Build 739: терминальный результат модели

Обычный активный сметный запрос завершает предметную часть первым полным
результатом той же модели, которая сформулировала RAG-запросы и увидела
карточки. Код после этого проверяет только структуру, идентичность строк,
количество, единицы и происхождение, затем считает и упаковывает XLSX. Он не
запускает verifier, новые поиски, format-repair или coefficient-review и не
переводит выбранные моделью нормы в другой профессиональный статус.

Исторический quality-loop сохранён только для явного изолированного варианта
`QUALITY_DIAGNOSTIC`; его вывод не является пользовательской ЛСР. Если
упаковщик возвращает технический `failed`, чат ровно один раз повторяет тот же
идемпотентный workbook-вызов с неизменными строками и checkpoint. Постоянный
сбой показывает код и checkpoint, а компактные строки решения остаются в
истории для диагностики и восстановления.

## Build 738: устойчивый результат ЛСР

PDF с распознанной Markdown-таблицей теперь получает полный source catalog со
стабильными локаторами `PDF!Rn`. Модель обязана вернуть решения именно для этих
строк; полнота, количество и единица проверяются по исходнику так же, как для
XLSX/CSV. Это не выбирает норму кодом, а фиксирует идентичность входных строк.
Live БАП-PDF подтвердил выпуск XLSX для всех 19 строк даже при 19 модельных
`CONFLICT`: документ остаётся доступным для проверки и продолжения работы.

Verifier получает нейтральную задачу определить применимость выбранной моделью
карточки по действию, объекту, условиям, физическому измерителю и составу работ.
Он не получает указание искать противоречие. Масштабные измерители (`м²` и
`100 м²`, `шт` и `100 шт`) считаются совместимыми для проверки; количество
пересчитывает код после подтверждения.

Если новые стратегии поиска исчерпаны, последний модельный `CONFLICT`, шифр и
причина сохраняются с отдельным признаком `_research_exhausted`. `MISSING`
означает отсутствие найденного применимого кандидата. В деньги по-прежнему
попадает только подтверждённая строка, но XLSX с конфликтами и пропусками
остаётся доступным как partial-документ для продолжения работы.

## Workbook tools in installed factory profiles (0.30.28 / build 668)

Factory Base профиля `estimator` хранит два канонических workbook tool contract,
но profile allowlist — только намерение, а не доказательство исполнимости.
CapabilityBroker выдаёт модели лишь tools, доступные в текущем runtime context.

**Build 663:** context-bound workbook contracts не попадают в обычный ToolHarness
shortlist. При server-owned read-вложении чат добавляет реально исполняемые
`build_vor_workbook` и `build_lsr_workbook`. Тонкий LSR adapter принимает явные
`decisions` той же модели и только рассчитывает/рендерит их, не запуская скрытый
второй model loop.

**Build 668:** startup-синхронизация обновляет стабильные `factory:*:base`
snapshot-ы по текущему code contract и обновляет только chat bindings на эти
заводские revision ID. Это закрывает upgrade со старой MetaDB, где профиль
«Сметчик» был создан до появления workbook-tools. Пользовательские profile,
prompt и skill revisions, а также их активные bindings не изменяются.

**Build 669:** обязательный selector request явно сообщает модели о привязанном
server-owned attachment и его временном ID. Поэтому малой модели не требуется
вместить весь извлечённый XLSX-текст только для понимания, что workbook-tool
можно применить. Выбор инструмента и его предметные аргументы остаются за моделью.

**Build 670:** Factory Base «Сметчик» сводит capability к
`search_sources`, `read_source`, `build_lsr_workbook`, `build_vor_workbook` и
явно привязывает typed system datasets модуля `smeta`. Профиль не формирует
запросы и не выбирает нормы. Модель видит attachment evidence в первом active
call, сама делает native tool calls общего RAG и передаёт свои решения
workbook adapter. Ограничение количества tool definitions малого preset не
обрезает число поисков в одном model response. Передача первого запроса модели
задаётся общей политикой `rag_policy.model_authored_initial_query`, а не
зашитым в application-код именем режима.

**Build 776:** checkpoint и coverage хранят работу и материал на одном
локаторе; named `NEEDS_RESEARCH` идёт в exact lookup и остаётся аналогом.
Код шифр не выбирает.

**Build 671:** generic selector больше не получает скрытое указание немедленно
выбрать ровно один workbook-tool. Отклонённый workbook result возвращается той
же модели, поэтому она может продолжить собственный поиск по RAG и повторить
сборку. Профиль по-прежнему задаёт доступные capability/datasets, но не порядок
вызовов и не предметное решение.

**Build 680:** model-authored query является инвариантом режима `estimator`,
поэтому keep-state старого пользовательского profile snapshot не возвращает
чат в прежний общий-RAG путь. Prompt, skill и сохранённая ревизия пользователя
не переписываются. Поиск норм использует effective dedicated collection,
настроенную active base/runtime, и не делает fallback в общий `les_rag`.

**Build 681:** runtime effective snapshot старого пользовательского estimator-
профиля явно содержит `model_authored_initial_query=true`, хотя его immutable
revision остаётся нетронутой. Любой ответ `search_sources`, видимый модели,
ограничен шестью верхними hits.

**Build 684:** запросный model-RAG transport — только обычные строки Qwen:
без JSON/native-tools и без лимита их количества. Итоговый ответ модели не
маршрутизируется по словам и не исправляется regex-ами. XLSX decoder принимает
однозначную Markdown-таблицу с фиксированными известными заголовками либо строки
с явно подписанными полями и передаёт их штатному workbook adapter. Произвольная
проза и неизвестные aliases не интерпретируются: текст остаётся видимым как
ответ Qwen, но артефакт не создаётся. Проверка полноты `source_row`, реальности
`Qx.Hy` и соответствия шифра указанной карточке локальна, не меняет модельные
поля и не создаёт дополнительный model turn. `architecture-gate` запрещает
regex в decoder-е и language/regex forcing workbook-вызова.

**Build 685:** result decoder сохраняет безопасную совместимость с фактическим
форматом рабочего прогона Максима: точные заголовки `Нормативный код
(ГЭСН/ЕР)`, `Коэфф.`, `Примечание`, пустые quantity/coefficient, тире и
числовая дробь принимаются без regex. Могут быть дополнены только отсутствующие
справа пустые optional-клетки; лишняя ячейка закрывает упаковку вместо
обрезания. Это синтаксическая терпимость, а не выбор нормы или исправление
модельного результата.

**Build 688:** запросный decoder остаётся либеральным только к оформлению:
принимает кавычки и написанные Qwen строки `search_sources("…")`, но не
классифицирует темы и не создаёт запросы из окружающей прозы. Финальный ответ и
его поля остаются неизменными. Серверное вложение хранится в effective runtime
state root; после локальной проверки ссылок canonical workbook adapter сам
получает тот же результат и подключает штатную pricebook. Memory pressure не
переназначает выбранную модель на другого локального provider.

Канонический профиль чата связывает immutable Factory Base и пользовательские ревизии
prompt/skill с режимом, allowlist инструментов, model policy и RAG policy. Активная ревизия
фиксируется snapshot-ом при создании чата; уже открытый чат меняет её только по явному действию
оператора, кроме синхронизации стабильного заводского Base-контракта при обновлении приложения.

Allowlist имеет одного владельца: `chat_profile_service` строит factory-набор только из
инструментов живого `ToolHarness` registry, а `chat_evidence_application_service` применяет
точный список immutable snapshot. `profile_resolver.py` выбирает маршрут и output policy, но
не содержит второго списка названий инструментов.

## Текстовые бюджеты

- prompt: не более **16 000** символов после удаления пробелов по краям;
- skill: не более **8 000** символов после удаления пробелов по краям.

Источник истины — `proxy/services/chat_profile_service.py`. API registry возвращает
`text_limits`, а схема публикации содержит `x-les-max-length-by-kind`. Клиент не дублирует числа:
экран «Конфигурация → Профили» строит счётчики из registry, предупреждает на границе и блокирует
сохранение только при превышении. Сервер повторно проверяет бюджет и отвечает `409` с кодом
`profile_text_too_long`, поэтому ограничение нельзя обойти другим клиентом.

Retrieval policy также принадлежит effective profile: `candidate_k` управляет
шириной native-RRF overfetch, `document_diversity_k` — максимумом фрагментов
одного физического документа, `model_evidence_k` — итоговым окном evidence для
модели. Заводские значения `64/2/6` не являются предметным лимитом и доступны
для настройки в редакторе профиля.

Старые сохранённые ревизии сверх новых лимитов остаются читаемыми и могут быть выбраны для
аудита. Повторная публикация такого текста требует сначала сократить его до текущего бюджета;
существующие данные автоматически не переписываются и не удаляются.

## Точки входа

- `proxy/services/chat_profile_service.py` — хранение, лимиты, system-dataset binding и публикация ревизий;
- `proxy/routers/profiles.py` — registry и HTTP-контракт ошибок;
- `proxy/services/profile_resolver.py` — разрешение route/profile policy без tool allowlist;
- `sovushka/pages/profiles.py` — редактор, счётчики и client-side guard;
- `tests/test_chat_profile_service.py`, `tests/test_profiles_router.py`,
  `tests/test_profiles_ui.py` — service/API/UI contract.

## Эффективный пресет исполнения модели

Профиль чата может только сужать безопасный фабричный пресет. Итог определяется
в порядке: инварианты workflow → наблюдаемая ёмкость backend → фабричный пресет →
необязательный клон оператора → ограничения workflow/профиля.

- неизвестная модель или неподтверждённая ёмкость получает `qwen-9b-restrictive`;
- `qwen-35b-extended` доступен только при распознанной 35B и наблюдаемом KV;
- для FreeToken наблюдаемый KV берётся из cache status / models, не из requested window;
- default `FREETOKEN_CONTEXT_TOKENS=35000` совпадает с заводским окном 35B;
  rebuild clamp'ит запрос до `max_feasible_kv`; для 35B окно <16384
  поднимается до 35000, ACTIVE чат пересобирает KV один раз в начале хода,
  пакеты только читают уже выровненные pages;
- reasoning по умолчанию выключен;
- разрешение пресета не меняет `legacy`/`shadow`/`active` и не перезапускает backend;
- `/api/version` и GUI-first runtime registry показывают только безопасные
  `requested → effective · source`;
- фактический preset, лимиты, reserves и reasoning в реестре read-only:
  model/context можно менять только через пользовательскую копию профиля,
  safety и наблюдаемая ёмкость напрямую не редактируются.

Точки входа: `proxy/services/model_execution_preset_service.py`,
`proxy/services/model_capability_service.py` и
`proxy/services/llm_transport_profile_service.py`.
