# Evidence packet в общем RAG-контуре

Статус: **✅ реализован для обычного model-first RAG**. Dev-версия: `0.30.31`.

## Зачем

Обычный чат прежде передавал модели контекст, а UI отдельно получал `source_map`, navigation
память и retrieval trace. Это позволяло каждому слою выглядеть правильно по отдельности, но не
давало одного проверяемого контракта «что именно увидела модель и на что она может сослаться».

`proxy/services/evidence_packet_service.py` собирает уже выбранные и расширенные чанки в
`les.evidence_packet.v1`. Он **не** выполняет поиск, rerank, профессиональный вывод или расчёт.

С 0.24.0.350 assembler сначала покрывает разные source documents, затем добирает соседние
фрагменты; большой chunk может быть безопасно обрезан или пропущен и не блокирует последующие.
Табличный evidence сохраняет header, source unit несёт locator/version/retrieval features.
После генерации `les.answer-citation-check.v1` проверяет, что `[Источник N]` существует в реально
видимом source map. Это проверка ссылочной целостности, а не доменной истинности.

С 0.27.76 FreeToken использует тот же assembler без отдельного лимита в четыре чанка.
Фактический объём ограничивает derived prompt capacity выбранного runtime; перед evidence
резервируются bounded session/working memory и обязательный хвост вопроса. Это сохраняет
продолжение диалога и расширяет покрытие документов без доменных слов, boosts или ожидаемых файлов.

```text
retrieval + context windows
    → EvidencePacket
        ├─ retrieved sources (фактические фрагменты и координаты)
        ├─ navigation (карты/reader/target-file, явно не evidence)
        ├─ deterministic evidence (например, MetaDB inventory)
        ├─ retrieval status + missing
        └─ model renderer с теми же «Источник N», что в source_map UI
    → model/tools → answer + answer_status/calculation_status отдельно
```

Для role-bound estimator первый retrieval также model-owned: текст явного
вложения входит в evidence первого model call, после чего модель формулирует
один или несколько `search_sources.q`. Код только исполняет каждый запрос через
тот же `retrieve_chat_chunks()` и возвращает найденные карточки; исходная
команда «Собери ЛСР» не используется как запасной поисковый запрос.
Отклонённый workbook-вызов не завершает цикл: его result видит та же модель и
сама решает, нужен ли дополнительный RAG-запрос, другой инструмент или остановка.
Технические deadline/call budgets только ограничивают бесконечное исполнение.

## Контракт

| Поле | Значение |
|---|---|
| `evidence_status` | `available`, `partial` или `missing`; это наличие и состояние фрагментов, не вердикт истинности ответа |
| `answer_status` | в generic chat живёт отдельно в `crag_status` |
| `calculation_status` | `not_applicable` для обычного RAG; сметный расчёт остаётся в расчётном модуле |
| `evidence.sources` | только фактические чанки: `S1`, совпадающий `Источник 1`, файл, excerpt, score и locator |
| `navigation` | только навигация с `context_role=navigation`, `is_evidence=false` |
| `deterministic_evidence` | точные структурированные сведения с собственным источником, например `metadb.documents` |
| `retrieval` | компактная диагностика режима, качества, fallback и embedding contract; полный trace остаётся в `retrieval_trace` |
| `missing` | известные пробелы пакета; не заполняется догадками модели |

`locator` переносит доступные координаты: dataset/file, page, sheet/row/cell, section/parent
heading, `chunk_ord`, `source_ref`, тип документа. Отсутствующие координаты не выдумываются.

При `partial` или `missing` model renderer добавляет служебный статус перед фрагментами. Он не
выводится пользователю как внутренняя терминология: модель использует все найденные релевантные
фрагменты, но не называет их полным покрытием корпуса и не выдумывает отсутствующий факт.

## Граница navigation и факта

Dataset brief, topic/section map, reader-pass, target-file selection и notebook plan помогают
выбрать следующий read. Они не становятся фактом проекта только потому, что попали в prompt.
Рендерер evidence packet передаёт модели только retrieved source chunks; navigation и tool
outputs идут отдельными блоками с уже существующими системными правилами. Это сохраняет
model-first ход без hardcoded профессионального ответа.

## BAI canary

`golden/bai_evidence_core_set.json` — четыре retrieval-проверки BAI: состав ИОС 5.2,
пояснительная записка, КСБ и реально доступная таблица. Он не измеряет качество
модельного текста и не разрешает reindex. Запуск:

```bash
uv run python tools/rag_golden_set.py --cases golden/bai_evidence_core_set.json
```

Если canary падает, сначала зафиксировать источник/координаты и trace; только затем решать,
нужны ли document-type chunk contract или отдельная миграция BAI.

Первый runtime прогон `0.24.0.342` выявил low-score разброс соседних проектных томов, который
trace ошибочно называл `good`; `retrieval_quality_service` теперь маркирует `top_score < 0.42`
при четырёх и более источниках как `weak/low_score_scattered_sources`, не блокируя модельный
ответ. Это диагностический статус, не отрицательный ответ и не правило об ожидаемом файле.

## Границы текущего шага

- Индексы, embedding и chunking не мигрируются.
- Старое сметное ядро, normcontrol и CAD/BIM не переписаны этим пакетом; тонкий
  ordinary-chat workbook adapter уже использует общий model-owned RAG и exact
  решения модели.
- `available` не означает `VERIFIED`; проверка ответа, расчёта и source conflict остаётся
  отдельной задачей.
