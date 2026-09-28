# Chat profiles

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
модель. Сравнительный baseline задаётся полем
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
