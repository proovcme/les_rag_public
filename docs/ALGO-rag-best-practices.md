# ALGO - RAG Best Practices for LES

Статус: рабочий стандарт для LES. Использовать перед изменениями в ingestion, dataset memory,
retrieval, tool-harness, notebook-study, PDF/XLS readers и ответах по датасетам.

## Цель

LES не должен быть "чатом над чанками". Для строительных документов нужен notebook-style RAG:
корпус сначала получает карту, модель читает карту и выбирает источники, retrieval приносит
проверяемые фрагменты, код читает/считает только то, что можно проверить, а финальный ответ пишет
модель со ссылками на evidence.

Ориентир "НБЛМ, но лучше" означает не копировать NotebookLM UI, а взять его сильную идею:
пользователь и модель работают с выбранным набором источников, source guide, заметками и
проверяемыми цитатами, а не с безликой кучей похожих фрагментов.

## Внешние опоры

- Google NotebookLM: пользователь задаёт notebook как выбранный набор источников; система строит
  source guide, summaries, вопросы и ответы по загруженным источникам с citations. См.
  `https://workspace.google.com/products/notebooklm/` и help по источникам/цитатам:
  `https://support.google.com/notebooklm/`.
- Google NotebookLM "Discover Sources": source discovery полезен как этап подбора источников, но
  источник всё равно должен попасть в notebook/scope до ответа. См.
  `https://blog.google/innovation-and-ai/models-and-research/google-labs/notebooklm-discover-sources/`.
- RAG как архитектура: retrieval дополняет параметрическую память модели внешним корпусом, но
  качество зависит от retrieve/read/generate/evaluate pipeline, а не только от embedding similarity.
  Базовая работа: Lewis et al., "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
  `https://arxiv.org/abs/2005.11401`.
- Современные обзоры RAG сходятся на том, что production RAG состоит из ingestion, indexing,
  retrieval, reranking, generation, evaluation и feedback loops, а не из одного top-k vector search.
  См. Gao et al., "Retrieval-Augmented Generation for Large Language Models: A Survey",
  `https://arxiv.org/abs/2312.10997`.

Эти источники не являются спецификацией LES. Ниже - локальный стандарт.

## Базовая модель

```text
folder/project/dataset
  -> intake plan
  -> source manifest
  -> parsed/indexed sources
  -> typed dataset memory / source guide
  -> model reader-pass
  -> model-selected tools: dataset_map/search/read/table/pdf/cad
  -> retrieved evidence
  -> model final answer
  -> trace, sources, missing, blockers
```

## Единственный production retrieval path

```text
model/user query
  -> format-agnostic normalization
  -> selected dataset/file/version scope
  -> Qdrant named dense + BM25 sparse prefetch
  -> RRF fusion
  -> SQLite FTS exact-reference/file safety merge
  -> reranker over a wider candidate pool
  -> parent/neighbor context expansion
  -> compact evidence packet
  -> model reads, may call search/read again, then answers
```

Typed SQLite, PDF/table/CAD readers и exact lookup являются инструментами того же evidence-контура.
Они могут вернуть точную карточку, строку или координату, но не выбирают норму, аналог, состав работ
или профессиональный вывод. Отдельной альтернативной RAG-архитектуры для модуля или датасета нет.

Запрещено:

- unnamed production vectors и отдельный sparse sidecar;
- копировать legacy dense в новую коллекцию без полного contract-clean re-embed;
- включать/выключать обязательный RRF env-флагом;
- дописывать в query готовые доменные утверждения или ожидаемые golden-термины;
- выбирать top-1, норму, аналог, coverage или ответ кодовым score/boost/regex;
- дробить профессиональное решение фиксированными окнами строк; batching допустим только внутри
  исполнения независимых tool calls и не меняет видимую модели задачу;
- считать navigation maps доказательством или отдавать модели сырой бесконечный registry;
- маркировать single-channel fallback как hybrid/RRF.

При нарушении embedding/index contract система работает только в явном degraded режиме до clean
rebuild. Аварийный fallback не становится поддерживаемой второй архитектурой.

Главная граница:

```text
navigation != evidence
```

`LES.md`, `00_dataset_map.md`, typed memory, file cards, topic maps, operator guidance и reader-pass
помогают выбрать путь чтения. Факты в ответе должны идти из retrieved chunks, PDF pages, table rows,
CAD/BIM atoms, normative clauses или calculation trace.

## Принципы

### 0. Исправлять систему, а не симптом

Конкретный провал датасета, документа или запроса является regression-кейсом, но не границей ремонта.
Изменение RAG считается архитектурным только тогда, когда инвариант выполнен для всего текущего
корпуса и автоматически применяется к будущим датасетам. Объектные boosts, отдельные обходы FIRE,
BAI, ПД или смет и ручное включение обязательного retrieval-слоя не являются исправлением ядра.

Для штатного LES каждый индексируемый evidence-chunk обязан иметь совместимые named dense и sparse
vectors, production retrieval обязан выполнять RRF, а смена embedding/chunking/vector schema обязана
создавать новую contract-versioned коллекцию. Частный кейс используется только для измеримого гейта.
Нормализация запроса ограничена Unicode/whitespace/exact-reference формой; код не дописывает в query
готовые FIRE/HVAC/ПП87 утверждения. Переформулировать поиск может модель через следующий tool-call.

### 1. Корпус важнее чанка

До поиска по похожести модель должна понимать:

- что это за датасет;
- какие файлы входят в scope;
- какие файлы служебные;
- какие документы являются версиями одного комплекта;
- где титул, состав, общие данные, изменения, спецификации, таблицы;
- какие источники отсутствуют.

Если corpus map пустая, broad-вопросы будут случайно цепляться за шумные chunks.

### 2. Scope задаёт оператор, а не эвристический router

Для GUI `+ папка` источник истины - выбранная папка, dataset/project и `LES.md`.
Router может дать мягкие hints: file role, parse pipeline, warnings. Router не должен без явного
действия оператора переносить проектный файл в соседний глобальный индекс и менять dataset boundary.

### 3. Типизация мягкая

Типы нужны модели как подсказки чтения, а не как жёсткий приговор:

- `technical_document` - проектная/техническая документация;
- `normative` - явная нормативка: СП, ГОСТ, ГЭСН, ФЕР, ФСЭМ, ФСБЦ, rulepack;
- `estimate/calculations` - ЛСР, ВОР, КС, расчётные таблицы;
- `tables` - строки, количества, спецификации, ведомости;
- `drawings/cad_bim/graphics` - листы, схемы, элементы, свойства.

Пример: `NTD_ELECTRICAL` - область поиска ЭОМ. Это не означает "нормативный документ".

### 4. Intake должен быть прозрачным

Перед Play пользователь должен видеть:

- будет создано/обновлено: project, dataset, service maps;
- принято: список файлов и форматы;
- пропущено: `.DS_Store`, временные файлы, unsupported;
- parse status: ready, pending, partial, blocked, failed;
- warnings: scan/no text/encrypted/huge/timeout/manual_required;
- missing: какие документы нужны для заявленного workflow.

Нельзя молча создавать `INDEXED` с нулём полезного текста.

### 5. PDF/XLS/CAD - это readers, не только chunks

Dense chunks подходят для поиска. Для профессионального ответа нужны reader tools:

- PDF: page locator, page text, table locator, preview/open, OCR/manual_required;
- XLS/XLSX/CSV: sheets, columns, row ranges, filters, numeric aggregation;
- CAD/DWG/BIM: projection, element properties, drawn tables, source row/cell/element refs.

Если таблица попала только как prose chunk, это acceptable baseline, но не final-quality table RAG.

### 6. Retrieval должен быть additive

Гибридный retrieval, rerank, source concentration и validators должны помогать, а не занулять
релевантные sources.

Правило:

```text
если найден релевантный источник -> ответ строится на нём с уровнем уверенности/ограничениями;
не превращать moderate score в "нет данных", если source явно полезен.
```

Гейты могут помечать `UNVALIDATED`, `PARTIAL`, `MISSING`, `CONFLICT`, но не должны стирать
проверяемый контекст без объяснения.

### 6a. Dense-вектор имеет контракт модели

Имя модели, запрошенное клиентом у `/v1/embeddings`, не выбирает модель на сервере само по
себе. Сервер обязан вернуть фактические `embedding_model` и backend; клиент обязан сравнить их
с моделью активной Qdrant-коллекции до поиска.

```text
expected Qwen + actual Qwen -> dense/hybrid search allowed
expected Qwen + actual BGE  -> dense disabled, lexical-only, status=degraded
missing actual model         -> dense disabled, status=degraded
```

Нельзя сравнивать вектора разных embedding-моделей только потому, что у них одинаковая
размерность. Режим `lexical_only` — честный временный ответ, а не `quality=good`; восстановление
dense требует выравнивания runtime-конфига и целевого reindex, а не скрытого fallback.

С 0.24.0.350 совместимость фиксирует `les.rag.index-contract.v1`: collection, модель/vector size,
raw document mode, tokenizer budget, chunker и sparse revision. Missing/mismatch manifest также
запрещает dense. Совпадение количества SQLite chunks и Qdrant points не доказывает совместимость.

До embedding каждый parser output обязан пройти единый финальный gate: реальные токены не выше
budget, mixed base64/data URI удалены, координаты и parent/child provenance сохранены. PDF/table/mail
не могут иметь отдельный обход этого инварианта.

### 6b. Reranker обязан получать меньший top-k, чем входной пул

Reranker полезен только если переупорядочивает широкий пул до видимого окна. Передавать ему
`top_k=len(pool)` — фактически no-op для cross-encoder и нельзя отмечать это как успешный rerank.
Хвост может сохраниться для downstream-readers, но первые позиции должны быть реальным top-k
reranker-а, а trace обязан отражать применённый режим.

Явно названная норма (`СП 7.13130`, `ГОСТ Р 21.101`) имеет ещё одно общее правило: файл самой
нормы приоритетнее документов, которые только ссылаются на неё. Это reorder уже найденного пула,
не ручной ответ и не подстановка источника вне retrieval.

### 7. Model reader-pass обязателен для эталонных датасетов

Typed memory - это кодовая карта. Этого мало. Для golden dataset должен проходить модельный reader-pass:

- модель получает компактную карту корпуса;
- модель возвращает corpus kind, file roles, where-to-look, known gaps, answer guidance;
- результат сохраняется как navigation-not-evidence;
- failure сохраняется с понятной ошибкой и виден оператору.

Если reader-pass падает, нельзя говорить "модель знает датасет". Можно говорить только:
"индекс и карта готовы, модельное чтение не закрыто".

### 7a. Research guide измеряет путь чтения, а не заменяет его

У notebook-study может быть `notebook_research_guide_v1`. Это производная навигационная
карта текущей сессии, а не summary источников и не новый knowledge store. Она может показать:

- revision-id и наличие topic/section map для каждого выбранного датасета;
- был ли успешен model reader-pass;
- сколько запланированных разделов и точечных файлов действительно дали retrieved chunks;
- с каких файлов начать и какие source-grounded вопросы задать дальше.

Контракт guide всегда `context_role=navigation`, `is_evidence=false`. Поле coverage означает
только полноту маршрута в этом проходе: `ready` не доказывает полноту проекта, а `partial` не
обнуляет найденные источники. Любой факт, вывод или citation по-прежнему должен происходить из
retrieved chunk/page/row/element либо calculation trace.

### 8. Модель выбирает ход, код выполняет инструменты

Правильный loop:

```text
model decides: open dataset_map -> search_sources -> read_source/table/pdf -> answer
code executes: bounded read/search/count/calc with source refs
model writes: final answer with sources, missing, caveats
```

Неправильно:

```text
code sees keyword -> writes professional answer
code sees domain -> forbids source
code sees missing price -> refuses entire task
code silently falls back to соседний датасет
```

### 9. Контекст модели должен быть компактным

Не душить модель полным JSON memory и всем реестром. В prompt идут:

- короткий dataset brief;
- operator guidance;
- top files/topic map;
- выбранные chunks/reader results;
- explicit missing/blockers.

Полная карта остаётся в API/artifact/tool result. Модель может запросить детали через tool.

### 10. Citations должны быть проверяемыми

Минимальный source ref:

```text
dataset_id
file_name / doc_name
page или sheet/row/cell или CAD element/table
chunk_ord/point_id when available
```

Ответ без source refs допустим только для явно conversational/non-evidence вопросов. Для проектных,
сметных, нормативных и табличных вопросов источник обязателен.

### 11. Missing - это результат, но не отказ по умолчанию

Если не хватает ВОР, XLSX, цен, норм или OCR, ответ должен разделять:

- что можно сказать по имеющимся источникам;
- что нельзя доказать;
- какие документы нужны;
- какой следующий шаг.

`MISSING` не должен уничтожать уже найденную часть ответа.

### 12. Evaluation сначала на golden datasets

Любая правка RAG должна проверяться не только unit-тестом, а контрольными вопросами:

- overview: что за датасет/объект;
- inventory: какие документы и версии;
- target-file: вопрос по конкретному файлу;
- version diff: что изменилось;
- table/spec: найти строку/позицию;
- missing: честно сказать, чего нет;
- no-neighbor: не отвечать по соседнему датасету.

Для НС такой golden dataset уже есть: `7fa2dbaa-ee36-422e-8876-80ab28b9b17e`.

## LES Acceptance Checklist

Для датасета:

- [ ] Есть `LES.md` с project/dataset ownership.
- [ ] Есть `00_dataset_map.md` как navigation, не evidence.
- [ ] Service maps не зарегистрированы как RAG documents.
- [ ] MetaDB documents соответствуют реальному числу пользовательских файлов.
- [ ] Qdrant count == lexical_chunks count для dataset.
- [ ] File cards не путают project docs с normative.
- [ ] Operator guidance сохранён в profile и typed memory.
- [ ] `dataset_map` tool показывает source layers, topics/routes и guidance.
- [ ] Model reader-pass `reader_status=model`.
- [ ] Если `model_failed`, есть сохранённая причина и видимый blocker.
- [ ] Search/read tools возвращают source refs.
- [ ] Broad chat не уходит в deterministic auto-note/router вместо чтения dataset.

Для ответа модели:

- [ ] Модель сама выбрала/вызвала source tools или получила retrieved context.
- [ ] Ответ ссылается на PDF page / sheet row / table row / CAD element / clause.
- [ ] Ответ отделяет evidence от navigation.
- [ ] Missing/blockers видны, но не стирают найденные факты.
- [ ] Нет silent fallback на соседний датасет.
- [ ] Нет code-written professional answer вместо model final.

## NS Golden Dataset - текущий эталон

Dataset:

```text
name: НС_Проект
id: 7fa2dbaa-ee36-422e-8876-80ab28b9b17e
source: /Users/ovc/Downloads/ns
files: 4 PDF
chunks: 999
role: project PDF corpus, ЭОМ
not: normative corpus, smeta corpus
```

Контрольные запросы:

```text
паспорт:
  заказчик научный центр большая цифра центр обработки данных шифр 27/05-22-Р-ЭОМ.1

состав:
  ведомость рабочих чертежей основного комплекта общие данные план ЦОД

изменение 8.3:
  содержание изменения 8.3 откорректированы общие данные замена производителя оборудования

лист изменений:
  лист изменений 07.07.2025 скорректированы расчеты лист 20 21 22

система:
  описание основных систем электроснабжения ЦОД ИБП ДГУ РЩБ АВР 4/3N

спецификация:
  спецификация оборудования комплектная система бесперебойного питания 1800кВт 2х900кВт
```

Текущий статус НС:

```text
index/map: ready
operator_guidance: ready
search_sources: finds expected pages
model reader-pass: not ready if reader_status=model_failed
live chat route: not ready if overview goes to auto-note
PDF table/layout reader: baseline only
```

## Anti-patterns

- "Нашли 999 chunks, значит модель знает датасет."
- "Есть typed memory, значит reader-pass не нужен."
- "NTD_* значит нормативка."
- "Служебный `LES.md` можно удалить, потому что он не evidence."
- "Полный реестр файлов надо засунуть в prompt."
- "Нет XLSX/цен, значит нельзя сказать ничего."
- "Validator не уверен, значит надо стереть найденные sources."
- "Router выбрал канал, значит модель больше не нужна."

## Practical Rule

Перед фразой "датасет готов" должны быть зелёными три слоя:

```text
1. index/readiness: файлы прочитаны, chunks/source refs есть;
2. navigation: source guide, file cards, operator guidance, dataset_map есть;
3. model reading: модельный reader-pass и/или tool-loop реально открывает источники и отвечает по ним.
```

Если зелёны только первые два слоя, формулировка должна быть честной:

```text
датасет подготовлен как корпус, но модельное чтение ещё не принято.
```
# Qwen query embedding contract

Для `Qwen/Qwen3-Embedding-0.6B` документы индексируются raw. Query-side instruction
является отдельным, измеряемым контрактом: `RAG_QUERY_EMBEDDING_MODE=raw-v1` — текущий
baseline, `qwen-retrieval-v1` добавляет английский retrieval instruction только к запросу.
Режим и его id пишутся в `retrieval_trace.query_embedding` и runtime embedding config.
Не менять его одновременно с ingestion, collection или embedder: A/B сравнивает один и тот же
индекс на FIRE, BAI, ПД ИЦ и сметах, затем фиксирует source/section/table-row recall и latency.
