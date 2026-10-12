# ALGO — model connections и provider extensions

Статус: базовая граница 0.30.175; уточнение tools evidence ниже — installed 0.30.198 с rollback/reinstall acceptance. Общая архитектура реестра описана в
[universal model connections design](superpowers/specs/2026-08-27-universal-model-connections-design.md).

## Владение ответственностью

Model connection хранит выбранные оператором endpoint, model id, locality, role bindings и
extension type. Общий OpenAI-compatible transport выполняет inference; provider extension
нормализует только доказанные особенности конкретного движка. Extension не выбирает
профессиональное решение, не переписывает evidence и не управляет пользовательским индексом.

## Lemonade

`extensions/lemonade/` является provider-owned границей:

- `contracts.py` разделяет configured model id, observed backend и фактический loaded state;
- `vendor_status.py` принимает loaded только из непротиворечивой vendor health-записи и фиксирует
  embedding identity `Qwen3-Embedding-0.6B-GGUF / llama_cpp / 1024 / 430 / 50`;
- `transport.py` добавляет `enable_thinking=false` только для Lemonade + Qwen 3.6 + observed
  `llama_cpp`; явное значение caller имеет приоритет, неизвестный backend ничего не меняет;
- `extension.py` разрешает только зарегистрированную операцию `flash_attention` на loopback.

Flash Attention проходит `GET current → POST dry_run → exact receipt/approval → persist`.
Private/LAN endpoint, неподдерживаемая recipe, изменившееся состояние или несовпавший approval
закрываются до мутации. FLM этим контуром не изменяется.

`lemonade_host.py` остаётся compatibility façade. Его `/health` не объявляет configured модели
загруженными без vendor evidence, а `/v1/embeddings` отклоняет несовпавший model id и возвращает
точную embedding identity. Установщик LES не включает и не устанавливает vendor binaries.

Capability probe разбирает только запись exact выбранной модели из Lemonade `/models`. В
immutable snapshot сохраняются normalized backend и положительный настроенный
`recipe_options.ctx_size`. После проверок capabilities read-only запрос
`/models/<encoded-model-id>/options` на том же endpoint уточняет размер по
`resolved_ctx_size` только при совпадении `model_name`. В snapshot записывается
`observed_context_source`: options либо configured recipe. Паспортный
`max_context_window` никогда не является fallback для доступного окна.
Options ограничены общим лимитом тела ответа и проверкой peer, redirects запрещены.
При недоступном/невалидном options сохраняется только явно заданный recipe context;
если его нет, ёмкость неизвестна. Это наблюдение разрешённой конфигурации провайдера,
не постоянный монитор фактических llama slots: после изменения/downsizing нужен новый
probe и проверка живого backend. Пользовательский лимит может только сужать известное окно. Resolver
выбирает execution preset по exact model id и observed context, после чего общий
`OpenAICompatibleTransport` применяет policy по `extension_type` и observed backend.
Display name не участвует; отдельного Lemonade network transport нет.

### Staged ownership

Task 5 владеет подключением `runtime_env.py` к Windows lifecycle. До этого только точный
runtime-map exemption для `extensions/lemonade/runtime_env.py` допускает его как staged dormant
surface; Task 5 обязан удалить exemption в том же атоме, что и wiring. Task 6 владеет активацией
observed transport wiring для Lemonade model connection; Task 3 не создаёт второй HTTP transport.

## Проверка

Офлайн-контракты: `tests/test_lemonade_{transport,vendor_status,engine_extension}.py`,
`tests/test_lemonade_{host,model_connection_flow}.py`,
`tests/test_model_engine_extension_service.py`. Реальная доступность
движка проверяется только отдельной live-приёмкой; offline GREEN её не заявляет.

## P9.14 — доказательство native tools (installed .198)

`model_capability_service._tools_probe_outcome` проверяет bounded HTTP response:
SUPPORTED означает native tool_call ожидаемого имени `les_capability_probe`,
непустой ID, type=function и валидный JSON arguments `{}`. Text-only HTTP2xx,
псевдовызов в content, invalid/truncated/oversized response — UNKNOWN с причиной.
Только явный typed tools refusal считается UNSUPPORTED; generic HTTP error не
доказывает отсутствие tools. Probe output limit256 действует только в уже
существующей явной проверке capabilities, не в профессиональном запросе.

`capability_diagnostic_observation` даёт effective projection старых HTTP2xx и
advertised SUPPORTED в UNKNOWN. Literal snapshots не меняются. Public API,
strict `require_capabilities` и optional transport gate используют эту границу.
Строгое явное TOOLS requirement требует proof. Необязательные schemas при UNKNOWN
могут быть отправлены той же модели; отсутствие proof не создаёт fallback.
Explicit UNSUPPORTED не понижается и сохраняет отказ до send. CHAT/auth/security
не ослаблены. Ни автоматического reprobe, ни замены role/model не добавлено.

Проверки: capability service/transport/router,92focusedPASS включая независимый
root review. Это диагностическое исправление, не доказательство чтения карточек
35B в длинном сметном контексте. Canonical2632PASS/19SKIP,verify2651,architecture0; installed rollback/reinstall,31payloadfiles exact и public legacy projection проверены. Нового model probe не выполнялось.
