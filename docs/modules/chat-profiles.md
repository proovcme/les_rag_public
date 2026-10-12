# Chat profiles

## .203 — диагностика таймаута (11.10.2026)

GUI runtime registry не сканирует старую staging-копию Tauri resources/runtime.
Для LES_MODEL_CONNECTION_TIMEOUT_SEC показывает фактический default 1800s local /
300s external по runtime_admission, либо валидный process override. Пустой или
нечисловой override показывает fallback/source=default. Незагруженный dotenv
не считается effective. Chat transport и настройки Lemonade не изменены.


P9.15 .199/build839 установлена: exact frozen9affdc415e35,4replace/0delete,
install→rollback198→reinstall, nativeRRF3/3,33runtimefiles exact.
Canonical2641PASS19SKIP/verify2660/architecture0. Same-input none/r10 контроль
ACTIVE16770 в p9/candidate-0199-none-available-tools; результата ещё нет.
Последний .198 pass2: полные receipts8/8+1/1, но0/3; новый mismatch и31/32cells.
P9.16 source-only диагностика format status начата отдельно, в runtime199 её нет.

Исторические точки:

## ACTIVE estimator answer contract (.199 source candidate)

`factory_estimator_texts` содержит прежние registered factory prompt/skill без изменения
текста. `render_factory_estimator_answer` делает временную answer-only копию лишь при
совпадении factory IDs/is_factory, текущих exact texts и их SHA. Неизвестные исторические
и пользовательские тексты не заменяются текущим Base. Registry/seed/bindings не меняются.

Перед ContextGovernor `prepare_estimator_answer_contract` действует только на ACTIVE
model-driven estimator answer. Code-owned ссылка на filesystem skill заменяется на
inline правила; недоступный read_source — на фактически переданный search_sources(q).
Если tools не переданы, prompt прямо это сообщает. Code-added citation fragments
используют Qn.Hm. Профессиональные инструкции и свободный выбор чтения сохраняются;
обязательных вызовов, нового каталога/worker или старого phase-workflow нет.

Тот же rendered prefix используется для native read continuations. Query stage, обычный
RAG и legacy/shadow не изменены. Пользовательские prompt/skill bytes сохраняются, даже
если содержат недоступные ссылки: trace показывает их как unavailable_references.
`answer_contract_availability` различает original/rendered prompt, skill, system и
request fingerprints, provenance IDs и actual available tools. Это диагностическое
свидетельство rendering, не подтверждение чтения или пригодности нормы.

19 focused PASS, 51 neighboring PASS (пересекаются); root full three-file177PASS.
Canonical и exact installed candidate ещё pending. Исторические build описания ниже
не заменяют активную границу ADR-15: модель → её literal queries → RAG → та же модель
→ терминальные строки → расчёт/XLSX.


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
- reasoning по умолчанию выключен;
- разрешение пресета не меняет `legacy`/`shadow`/`active` и не перезапускает backend;
- `/api/version` и GUI-first runtime registry показывают только безопасные
  `requested → effective · source`;
- фактический preset, лимиты, reserves и reasoning в реестре read-only:
  model/context можно менять только через пользовательскую копию профиля,
  safety и наблюдаемая ёмкость напрямую не редактируются.

Точки входа: `proxy/services/model_execution_preset_service.py` и
`proxy/services/llm_transport_profile_service.py`.
