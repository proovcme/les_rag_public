# RAG evidence flow

## 11.10.2026 — .204, шаг 4: однозначная область поисковых запросов

В model_rag_query_instruction сметная инструкция начинает с работ и материалов,
заголовки оставляет контекстом. Убрано противоречивое требование охватить «все
строки»; generic RAG сохраняет прежний текст. Парсер и исполнение literal queries
не менялись. Доставка проверена интеграционным тестом (focused136 PASS).
Живой .203 не улучшил запросы: заголовки2→3, цены0; новая .204 ещё не принята.
Полные факты и следующий шаг — audits/lsr-pr21-integration-20261008/p9/query-step4-20261011/REPORT.md.


## 11.10.2026 — шаг 4, кандидат .203: инструкция формирования запросов

После переноса fc606ba1 и 61b2e2c1 уточнена только smeta-инструкция query-вызова:
модель различает заголовок и содержательную позицию по смыслу и окружению,
использует заголовок как контекст, сохраняет исходную операцию и различающие
признаки. Неизвестный объём сам по себе не исключает работу из поиска.
Код не классифицирует строки, не фильтрует и не переписывает запросы модели.
Регрессия сохраняет буквально даже запрос-заголовок, если модель его вернула.

Доказательство проблемы: candidate-0201-bge-v2-run/pass-1-response.json —
«Архитектурные решения» и «Напольные покрытия» среди пяти запросов.
RED: 1 failed / 9 passed; GREEN: 136 passed (query budget + chat application).
Это проверка доставки инструкции и неизменности решений, а не качества норм.
Проверка модели: только p9-run-control-vulkan-text.py, исходник v2, expected-rows 9,
practice none, без question-file; r11/Vulkan + BGE/CPU + timeout1800 неизменны.
В v2 девять номерных строк, три содержательные работы. Старый v1 и вывод об
ошибочном монтаже ковровой плитки вместо демонтажа исключены из сравнения.

Дополнительный технический блокер гейта: реестр runtime-факторов читает старый
staging runtime и маскирует отсутствие AST-default timeout; отдельная регрессия
и диагностика описаны в timeout-gate-20261011/REPORT.md. Реальный timeout не меняется.

До живого контроля улучшение подбора не подтверждено. Следующий шаг после
измерения запросов — проверить очередь отложенных строк, затем rerank502.
STOP318 сохраняется; практика выключена. Public не публикуется.


Final .197 r1 canonical:2595PASS/19SKIP/5warnings, verify2614/all0,
architecture0. Wall11824.72s includes Windows Modern Standby observed in System:
506 at05:19:58 (SC_MONITORPOWER),507 at08:33:44 (Power Button),10.10.2026.
No caller identity is established. Initial pre-review gate199.22s is preserved
but is not the final release gate. Review availability P2 closed by conditional
wording with RED1→GREEN1; independent static review closed. Installed .197 accepted:
install→rollback196→reinstall/nativeRRF3/3, 30runtimefiles exact, 3HTTP norm reads
with14resources each. Same-input none/r10 control ACTIVE53086; professional result pending.

P9.13 source-кандидат .197/build837: `model_answer_request` явно ограничивает
Markdown/первую строку/noJSON итоговым пользовательским ответом; до него доступен
необязательный native search_sources по решению модели. Профессиональные правила,
schema, profile, queries и обычный ответный путь неизменны. RED1 → GREEN1;
diff-proof подтверждает старый contract после удаления одного уточнения.
Гипотеза требует installed same-input проверки, улучшение нормы не доказано.
Предыдущий .196 final: exact wire schema присутствует/HTTP200, reads0, книги нет
из-за6duplicateworkIDs; все3temporarysettings восстановлены, профессионально0/3.

## P9.11/P9.12 — source-кандидат .196/build836, диагностика после .195

Пустой видимый состав обычного preview при известном положительном `resource_count`
получает явное «состав ресурсов не показан». Неизвестные/некорректные значения не
превращаются в утверждение о числе ресурсов; full read не меняется. У непустого
preview предупреждение о неполноте уже было. Эта правка не доказана причиной
или решением отсутствия дополнительных модельных чтений.

Для ACTIVE model-owned estimate `answer`/`answer_read` transport получает
request-local `ModelRequestAudit`. После HTTPX serialization сохраняются точные
body bytes с SHA, затем отдельные события prepared/send_attempt/response_headers_observed
либо transport_error/cancelled. Retry/fallback имеют отдельные тела с фактическими
model/revision; это доказательство запроса клиента, не серверной обработки.
`tool_choice` отмечается как present/omitted, отсутствие не называется auto.
Query и остальные чаты opt-out. Аудит не создаёт inference, не изменяет schema,
параметры модели, профессиональный выбор или ContextGovernor.

Тела хранятся локально в `storage/model_request_receipts` и могут содержать частный
текст проекта, уже допущенный в messages. Headers, endpoint и секретная конфигурация
не записываются; обычный trace отдаёт только метаданные и относительный locator.
Не публиковать каталог с частными телами. Удаление/retention этой правкой не вводятся.
Отказ writer означает явный audit_unavailable и не вызывает повтор генерации.
При отказе события сохраняется корреляция и SHA уже записанного body, но снимаются
утверждения о lifecycle/HTTP status. Публикация final через exclusive hard link
не перезаписывает существующий receipt; неподдерживаемая файловая система явно
даёт audit_unavailable. Review P2/P3 закрыт; canonical2594PASS/19SKIP,
verify2613/all0, architecture0. Installed .196 install/rollback/reinstall PASS,
nativeRRF3/3,30runtimefiles exact. Actual wire/model контроль ещё идёт.

## Кандидат 0.30.193/build833 — P9.8a, адресное чтение модели

После первоначальной batch-выдачи Canonical ACTIVE предоставляет той же модели
необязательный `search_sources(q)`. Полный шифр использует существующий full reader,
возвращая операции и ресурсы; новые шифры код не выбирает. Обычный ответ без вызовов
сразу идёт в прежний расчёт/XLSX. JSON-планировщик и отдельный worker не добавлены.

Continuation — новый пакет штатного ContextGovernor: исходное вложение/вопрос,
текущий literal call/status и целая карточка обязательны; предыдущие результаты
сохраняются и по возможности включаются. Вытесненные объекты имеют видимые IDs/cursor.
Native schema имеет отдельный резерв, не дублируется в user text. Q-номера продолжают
batch без переименования. Нет post-pack добавлений. При required overflow или
техническом обрыве полный trace/исходник сохраняются UTF-8 receipt в
`storage/model_read_receipts`; строки не закрываются. Смена revision/model во время
чтения — явная ошибка. Конфликты нормативных редакций остаются в карточках и штатном
identity binding, код редакцию не выбирает.

Reader также сохраняет буквальные `source_doc/source_guid` ресурсов при наличии
колонок, иначе NULL; родительское происхождение не подставляется. Расходы/цены и
видимое тело preview не меняются.

Статус: focused153PASS, canonical2545PASS/19SKIP, verify2564/all0, architecture0.
.193 установлена: install→rollback.192→reinstall.193, nativeRRF3/3,26payloadfiles exact.
Реальный контроль .193 ACTIVE; профессиональная приёмка pending. Практика none, STOP318. Это исправление
доступа к evidence, не доказательство профессиональной пригодности сметы.

## 03.10.2026 — кандидат 0.30.173: полное чтение ресурсов по точному шифру

`norm_browser._code_listing` при полном шифре передаёт `_card(full_resources=True)`.
Карточка сохраняет прежний `resource_preview` и добавляет все исходные `resources`
с row_id/kind/code/name/unit/per_unit. Повторяющиеся коды, строки без названия,
труд, ноль и неизвестный расход не отбрасываются. `resources_complete` истинно
только при совпадении числа строк с паспортом нормы. Поиск таблицы остаётся preview.
Редакции одного шифра возвращаются отдельными карточками, не сливаются.

`smeta_card_text` отображает все эти строки и весь состав работ. ModelResearchToolService
помечает точное чтение `smeta_full_read`; упаковщик сохраняет его тело целиком.
Если бюджет недостаточен, действующий механизм сообщает исключённые группы,
а единственное невмещающееся чтение даёт явный EVIDENCE_BUDGET. Это не устраняет
все бюджетные потери обычной поисковой выдачи и не вводит дополнительный модельный цикл.
Нет новых цен, выбора аналогов, пересчёта количества или изменения решений модели.

Регрессии: реальные 36 разных сохранённых preview на бюджетах12/24/48тыс.,
разные provenance одного текста, SQLite24/26/33 ресурса, ноль/unknown/повторный код,
несовпадение счётчика, разные редакции, длинный состав и недостаточный бюджет.
Исторические fixture — preview, не полный нормативный состав и не одна сессия.
RED5FAIL/2PASS →75focusedPASS; test2185PASS/19SKIP, verify2204collected, architecture exit0. Реальная SQLite:24/24,26/26,33/33 строк в полном read и упаковке. Кандидат не выложен; installed/XLSX ожидаются.


## 0.30.174: фактическая доставка секций и ресурсов

`smeta_evidence_delivery_service` сохраняет компактный manifest смещений/хешей
исходных операций и отображаемых ресурсных строк. Один renderer ресурсов используется
для текста и manifest. Все три маршрута — ModelResearchToolService, _PracticeChunk,
_MaterialChunk — передают общий manifest и признак полного чтения. Поэтому полное
чтение из практики тоже сохраняется целиком либо явно не помещается в бюджет.

После окончательного ContextGovernor trace `smeta_evidence_delivery` сверяет исходные
query_hits, model_evidence_chunks и реальный user message. Для каждой нормативной
identity/редакции есть полнота тела, секций, числа исходных/отрендеренных/упакованных/
доставленных операций и ресурсов, доставленные row_id. Ссылка на повтор требует
доставленного оригинала той же identity; текст за пределами тела не дополняет ресурс.
Старые карточки без manifest имеют unknown item counts, а не придуманные нули.
Полностью доставленный preview не объявляется полным набором ресурсов базы.

Это наблюдаемость и сохранность полного чтения, не селектор/новый модельный цикл.
Обычные preview всё ещё могут усекаться. Offline replay сохранён в
`docs/audits/les-delivery-t3-replay-20261004.json`; installed/XLSX не проверены.

## 0.30.169: точность карточки цены

`price_card_text` передаёт исходную числовую точность `price_current_eff`:
56223.48 за1000м больше не превращается в56223.5 из-за шестизначного `:g`.
Ранжирование, набор источников, профессиональные решения и расчёт не меняются.
Проверка: `test_price_card_preserves_pricebook_precision` и реальный R13,
`SMETA-R13-DIRECT-CONTROL-2026-09-19.md`. Готовность сметы этим не доказана.

## Назначение

Обычный чат и model-authored estimate используют один принцип: модель сама
формулирует запросы и пишет итог, код только выполняет retrieval, сохраняет
provenance и механически исполняет разрешённый постпроцессинг. Дополнительного
planner/model-review шага и JSON-протокола между моделью и RAG нет.

## Активный поток

Обычный текст не является командой. Подстроки вроде `стоимост`, `КС-2`,
`пожар`, `вентиляция` или `список` не могут вернуть готовый ответ кодом, выбрать
датасет, сузить корпус или расширить число кандидатов. Scope приходит только из
явного выбора пользователя, проекта или effective profile binding. Расчётные
сервисы остаются доступными как явные команды и model tools.

1. Effective chat profile задаёт `candidate_k`, `document_diversity_k` и
   `model_evidence_k`. Заводские значения — `64 / 2 / 6`; пользовательская
   ревизия хранит свои значения, GUI показывает effective policy.
2. Native dense+sparse RRF получает широкий `candidate_k`. Код удаляет только
   точные дубли фрагментов и ограничивает число фрагментов одного физического
   документа, затем передаёт модели `model_evidence_k` результатов.
3. Для model-authored запросов каждая группа сохраняется независимо как
   `Qx.Hy`; ранние запросы не могут вытеснить поздние.
   Транспорт принимает обычные строки. Кавычки и явно написанная самой моделью
   оболочка `search_sources("…")` снимаются только синтаксически; вступительная
   проза при наличии таких строк не превращается в дополнительный запрос.
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
   подписанные поля. Обычный заголовок `Строка N: название` допустим, если сам
   блок содержит `source_row`, `title`, `unit` и `norm_code`; пустое количество
   остаётся пустым. Reader не извлекает решение из произвольной прозы и не
   переписывает ни одно переданное моделью значение.
9. Проверка ссылочной целостности блокирует упаковку только при отсутствующем
   или неизвестном `Qx.Hy`, а также при пустом/дублированном `source_row`.
   Пояснение рядом с точным шифром допустимо и сохраняется. Если выбранный
   `norm_code` не совпадает с карточкой по указанной ссылке, trace показывает
   warning, но исходные решения всё равно передаются `build_lsr_workbook`:
   конфликт должен быть виден в `partial` XLSX, а не скрывать артефакт.

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

- `proxy/services/chat_profile_service.py`
- `proxy/services/retrieval_candidate_service.py`
- `proxy/services/retrieval_service.py`
- `proxy/services/model_research_tool_service.py`
- `proxy/services/chat_evidence_application_service.py`
- `proxy/services/chat_evidence_manifest_service.py`
- `proxy/services/chat_capability_scope_service.py`
- `proxy/services/source_locator_service.py`
- `proxy/services/runtime_admission.py`
- `proxy/services/web_{research_config,search,page_reader}_service.py`
- `proxy/services/rag_{readiness,pipeline_status,advanced_policy}_service.py`
- `sovushka/pages/{chat,profiles,diag}.py`

## Целые карточки и охват запросов (0.30.201)

Упаковщик поисковых групп (`_fit_evidence_into_budget` → `build_model_rag_evidence_groups`)
отдаёт нормативную карточку модели целиком. Порядок ужатия: необязательные группы практики →
сужение выбора до пяти карточек на запрос → отбрасывание поздних запросов целиком. Отброшенные
запросы считаются в `model_evidence_coverage` и объявляются модели блоком `[ОХВАТ]`; их строки
остаются открытыми для следующего прохода. Карточка длиннее `max_chars // 5` считается по полу
и сокращается с пометкой «карточка сокращена». Единственный запрос, не помещающийся целиком,
сокращается как раньше.

Бюджет запросов первого вызова считается по `query_rows_in_pass` — строкам порции с единицей
или количеством; заголовки разделов остаются в порции, но запросов не получают.
