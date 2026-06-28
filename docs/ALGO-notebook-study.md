# ALGO-notebook-study — инженерное чтение блокнота

## Назначение

Дать ЛЕС NotebookLM-подобный режим для проектных датасетов: не отвечать одним случайным top-k,
а сначала построить план чтения по карте блокнота, затем целево достать источники по разделам,
и только после этого дать модельную сводку. Чат получает краткий ответ, правая панель — полный
артефакт с планом, источниками по разделам и пробелами.

Это не `project_summary_service` и не детерминированная подмена ответа. `notebook_study` — navigation
layer: блокнот и план помогают читать корпус, но evidence остаются найденные чанки и source-map.

## Точки входа

- `proxy/services/notebook_study_service.py` — trigger, reading plan, section retrieval pack,
  prompt-block и markdown artifact.
- `proxy/routers/chat.py` — подключает слой в обычный RAG-путь для явных broad-запросов по выбранной
  области: «расскажи/разбери проект», «инженерная сводка по блокноту», «что внутри датасета».
- `proxy/services/notebook_service.py` — источник карты датасета (`notebook_v1`).
- `proxy/services/retrieval_service.py` — для каждого раздела плана выполняется обычный hybrid retrieval.
- UI Совушки уже умеет показывать payload `artifact` в панели артефактов.

## Поток

1. Пользователь задаёт широкий исследовательский вопрос в выбранном scope/dataset.
2. `is_notebook_study_query()` включает слой только для явных study-интентов и не перехватывает смету,
   нормоконтроль, source lookup и точечные поисковые вопросы.
3. `build_dataset_notebooks()` читает deep-блокноты выбранных датасетов. Блокноты — navigation,
   `is_evidence=false`.
4. `build_reading_plan()` строит компактный план: состав комплекта, архитектура/конструктив,
   инженерные системы, ведомости/спецификации/таблицы, нормативные ссылки, пробелы.
5. Для каждого раздела вызывается тот же `retrieve_chat_chunks()`, но с расширенным section query.
6. Найденные фрагменты добавляются в общий RAG-контекст; LLM получает `notebook_study` prompt-block
   и отвечает обычным модельным синтезом.
7. Payload получает:
   - `notebook_context.schema=notebook_study_v1`;
   - `retrieval_trace.notebook_study`;
   - `artifact.title=Инженерный блокнот` с планом/источниками/пробелами.

## Границы

- Нет скрытого final-ответа без модели. Слой только организует чтение и retrieval.
- Нет объектных шаблонов состава работ.
- Числа не считаются этим слоем. Если вопрос про стоимость, объёмы или суммы — должны сработать
  сметные/табличные инструменты.
- Если раздел плана не нашёл источники, это пишется как пробел, а не заполняется догадкой.
- Полнота ограничена текущей индексацией: pending PDF и OCR-сканы останутся пробелами, пока не пройдут
  свой ingestion-путь.

## Тесты

- `tests/test_notebook_study_service.py` — trigger без hijack сметы/source lookup, план по карте блокнота,
  section retrieval pack, artifact/prompt contract.
- `tests/test_notebook_api.py` и `tests/test_context_memory_service.py` — базовый notebook/context-memory слой.
