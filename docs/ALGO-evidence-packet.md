# Evidence packet в общем RAG-контуре

Статус: **✅ реализован для обычного model-first RAG**. Dev-версия: `0.30.34`.

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

Для role-bound estimator retrieval полностью model-owned: исходный вопрос и
полный текст явного вложения видит модель, она обычным текстом формулирует по
одному поисковому запросу на строку. Код снимает только оформление списка
(кавычки и Markdown fence), не меняя формулировки, и буквально выполняет каждую
строку через `retrieve_chat_chunks()`.

Результаты не складываются в общий плоский список. Для каждого запроса берутся
первые шесть карточек и создаётся отдельная группа:

```text
[Поисковый запрос Q1] <точный текст Qwen>
[Q1.H1 | файл | score] точный шифр, название, измеритель, состав работ
...
[Q1.H6 | файл | score] ...
```

Все группы получают равную долю символьного бюджета; ранний запрос не может
вытеснить поздний. В финальный no-tools вызов входят полный исходный файл и все
группы. Дублирующий source map `Источник N`, checkpoint и advisory memory в этом
простом answer-вызове не передаются. Qwen отвечает обычным Markdown-текстом без
JSON/schema/tool call; mechanical reader собирает все таблицы по разделам,
извлекает значения ровно из подписанных моделью колонок и сохраняет видимый
ответ неизменным. После этого код сам один раз вызывает `build_lsr_workbook`,
подключает штатный pricebook, рассчитывает и прикладывает XLSX.

Ни специальный JSON-план, ни отклонённый workbook-вызов, ни R1/R2-review, ни
подтверждение привязки не являются воротами к RAG. Технический предел может
остановить лишь бесконечное исполнение; он не задаёт число строк, запросов или
профессиональных решений. Полный контракт закреплён в
[ADR-15](ADR-15-model-rag-result.md).

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
