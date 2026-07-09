# ANSWER_LIMIT_AUDIT — где ЛЕС режет ответы, строки и контекст

Дата: 2026-07-04. Версия кода: 0.24.0.215.

## Что снято в 0.24.0.215

1. `proxy/services/smeta_artifact_service.py`
   - Было: длинные сметные таблицы в видимом чате заменялись маркером
     `Таблица вынесена в артефакт`.
   - Стало: по умолчанию видимый ответ модели остаётся полным. Legacy compact
     только через явный `LES_SMETA_COMPACT_CHAT_TABLES=1`.

2. `proxy/services/doc_extract_service.py`
   - Было: generic XLSX sidecar extraction молча ограничивался `max_rows=5000`.
   - Стало: по умолчанию все непустые строки читаются. Ограничение возможно
     только явно через `LES_XLSX_EXTRACT_MAX_ROWS`; при срабатывании пишется warning.

3. `proxy/routers/chat.py`
   - Было: active smeta state хранил до 60 строк, а в prompt отдавал 40.
   - Стало: лимиты подняты и управляются env:
     `LES_SMETA_ACTIVE_STATE_MAX_WORKS=500`,
     `LES_SMETA_ACTIVE_STATE_PROMPT_WORKS=200`.
   - Это рабочая память follow-up, не финальный расчёт; visible answer теперь не
     схлопывается `compact_smeta_answer` по умолчанию.

## Оставлены как context/safety caps

Эти ограничения не являются расчётным ответом и не должны превращаться в
предметный отказ. Они ограничивают prompt/preview/transport:

- `proxy/routers/chat.py`: `max_tokens`, `RAG_*_CONTEXT_CHARS`,
  `RAG_VALIDATION_CONTEXT_CHARS`, source excerpts. Это бюджет генерации и
  валидации, не “не больше N строк сметы”.
- `proxy/routers/datasets.py`: `RAG_ATTACH_READ_MAX_CHARS` для read-вложения.
  Для больших PDF/XLSX правильный путь — индексировать файл или читать через
  tool/retrieval, а не пытаться засунуть весь документ в один prompt.
- `proxy/services/tool_harness_service.py`: `limit/max_chars` в tools.
  Tool payload режется только для transport; trace сохраняет, что именно было
  запрошено и что не найдено.
- UI-панели (`sovushka/pages/*`) используют `[:5]`, `[:10]`, `[:20]` для
  списков-превью, легенд и карточек. Это не расчёт и не финальный ответ.

## Требование

Для профессиональных доменов ответ формирует модель. Код может считать,
доставать источники, валидировать, трассировать и экспортировать, но не должен
подменять ЛСР/ВОР/экспертный текст заглушкой, regex-case или “не больше 10
строк” без явной команды оператора.
