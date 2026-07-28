# Public provider session

## Назначение

После успешного публичного входа по ключу пользователь обязательно выбирает модель до открытия
чата: локальную MLX или облачную OpenRouter/OpenAI со своим ключом. Выбор относится только к его
NiceGUI-сессии и не меняет общий `.env` или административный `/api/settings`.

## Поток

`/login` → `/provider-setup` → `/classic` (user) или `/les` (admin). `sovushka/provider_session.py`
хранит в `app.storage.user` только провайдера, модель и непрозрачную ссылку. Сам API-ключ находится
в process-memory vault не дольше 12 часов, не восстанавливается после рестарта и передаётся proxy
только в `provider_config` конкретного `/api/chat` или `/api/chat/stream`.

`proxy/services/chat_provider_session_service.py` валидирует allowlist `mlx|openrouter|openai`, фиксированные официальные API
URL и длины полей. `ContextVar` изолирует runtime и cloud-consent между конкурентными asyncio-задачами;
после ответа значения сбрасываются. Idempotency fingerprint содержит только SHA-256 ключа, не
открытый секрет. Серверные fallback-цепочки к BYOK-запросу не примешиваются.

## Границы безопасности

- Пользовательский ключ не пишется на диск, в `.env`, общий settings API или payload ответа.
- Произвольный OpenAI-compatible URL не принимается: это исключает пользовательский SSRF-контур.
- P0 и иные запрещённые политикой данные остаются на локальной модели даже при выборе облака.
- Выход удаляет vault-запись; истёкшая или потерянная ссылка требует повторного ввода ключа.

## Проверка

`tests/test_public_provider_setup.py` закрепляет TTL, отсутствие plaintext в user storage,
валидацию облачного выбора, request-scoped runtime/consent и редактирование idempotency payload.
