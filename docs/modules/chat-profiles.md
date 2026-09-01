# Chat profiles

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
