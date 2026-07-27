# План evidence-core LES

Статус: **активный план исполнения**. Актуализирован: 2026-07-10 по коду и runtime
`0.24.0.348` в dev. Это уточнение [ROADMAP_TO_V1.md](../ROADMAP_TO_V1.md), а не второй
независимый roadmap. Состояние конкретного релиза — только
[RELEASE_LEDGER.md](RELEASE_LEDGER.md).

## Цель

```text
источники → ingestion → каталог данных → индексы → retrieval
→ evidence-пакет → модель и инструменты → проверки/расчёты кодом
→ доказуемый ответ
```

Сметы, нормоконтроль, ПД/РД, спецификации и CAD/BIM — потребители одного
evidence-контура. Они не должны получать независимые RAG-архитектуры.

## Текущий факт

| Слой | Статус | Проверяемый факт |
|---|---|---|
| Runtime/code alignment | 🟡 | runtime `0.24.0.343` даёт common evidence packet и weak-status gate; dev `0.24.0.344` ждёт объединённого selective deploy с Л.И.С.Т. bundle |
| Embedding safety | ✅ P0 | Contract mismatch отключает dense/sparse и оставляет честный `lexical_only`/`degraded` |
| Hybrid retrieval | 🟡 | Qdrant native hybrid + FTS + rerank + target-file/topic routing существуют, но их качество не измерено единым набором |
| Navigation | 🟡 | file cards, maps и reader-pass — navigation, не evidence; target-file coverage теперь проверяет identity источника, но его качество ещё не измерено на четырёх контурах |
| Evidence contract | 🟡 | `les.evidence_packet.v1` объединяет normal-RAG chunks, точные `Источник N`, locator, quality и navigation boundary; доменные модули ещё не переведены |
| Corpus | 🔴 | runtime `degraded`: 5629 файлов, 2696 indexed, 2467 pending, 13 error; Qdrant `228707` points совпадает с SQLite chunks |
| Smeta finality | ✅ P0 | missing price даёт `partial`, а не фиктивный финальный total; ресурсные дубли защищены |

## Сделано в рамках этого плана

1. Убрана ложная уверенность dense retrieval: фактическая embedding-модель проверяется против
   активной коллекции; mismatch не может выглядеть как качественный dense-поиск.
2. Reranker получил реальное окно top-k; найденная по явной ссылке СП/ГОСТ получает приоритет
   над вторичными цитатами на неё.
3. Navigation развита до notebook-style пути: реальные section maps и file groups корпуса
   → bounded targeted retrieval → реальные fragments. План не подставляет АР, инженерку,
   ВОР или иной тип документа; research guide показывает ограниченное покрытие чтения, но не
   выдаёт его за доказательство или за полное чтение архива.
4. Сметный слой перестал называть неполное денежное покрытие финальным расчётом.
5. Первый NotebookLM-продукт определён архитектурно: «что в выбранном датасете?» читается по
   реальной карте файлов/групп и retrieved evidence, а не по ожидаемому составу данных.

## Не считать закрытым

- Единый inventory с актуальностью, parser-quality, таблицами/OCR, дубликатами и quarantine.
- Версионированное чистое индексное ядро для выбранных приоритетных датасетов.
- Общий evidence-пакет «утверждение ↔ точная опора» для RAG, нормоконтроля, таблиц, CAD/BIM и смет.
- Полный iterative tool loop, где модель при нехватке evidence сама повторно читает источник.
- Единые retrieval/evidence метрики и golden-наборы всех доменов.
- Shadow-сравнение и поэтапное переключение на новый индекс/retrieval.

## Сейчас: фаза 2 — inventory выбранного корпуса

Цель — не спасать все `PENDING` и не запускать полный reindex. Выбор оператора зафиксирован:

| Продуктовый контур | Runtime source | Факт на 2026-07-10 | Роль в фазе |
|---|---|---|---|
| ПД ИЦ | `ПД_Инновационный центр` · `1728e431-56d1-410f-8bf9-fdbf2543dce0` | 674 files, 297 indexed, 49 pending | главный проектный корпус и главный кандидат на первый index-quality проход |
| BAI | `BAI` · `449190eb-050e-422f-91a6-54852469201a` | 80 files, 75 indexed, 0 pending | компактный project regression и проверка навигации/targeted retrieval |
| Fire | `NTD_FIRE_Index` · `5a17e366-4c9a-489e-bfda-518f8fe1223f` | 125 files, 125 indexed, 0 pending | эталон нормативного retrieval; FIRE/HVAC golden остаётся доменным гейтом |
| Сметы: проектные таблицы | отдельного production dataset пока нет | test-only `TABLE_SMETA_Index` удалён 2026-07-10 | реальные ВОР/ЛСР при загрузке должны создавать user/project dataset, не смешиваться с module cards |
| Сметы: нормативная опора | `SMETA_RU_NORM_FSNB2022_Index` · `9bc6cd77-37f8-4be2-a95a-64d20891ca49` | 193 files, 191 indexed, 2 pending | нормы/расценки; технически отдельный источник, но тот же продуктовый сметный контур |

ПД ИЦ, BAI и Fire — текущие индексные canary-контуры. Сметный продуктовый контур остаётся,
но его module sources теперь системные, а реального project-table dataset пока нет. Нормативная
сметная опора отделена, чтобы будущие проектные сметы не смешивались с нормами и ценами.

Для каждого контура нужно получить проверяемую карточку:

```text
dataset / владелец / назначение
файлы и версии / актуальность / типы документов
parser и status / chunks / tables-OCR-layout
дубли и повреждённые источники / known blockers
приоритет: принять | исправить | quarantine | отложить
```

Генератор карточек: `tools/priority_corpus_inventory.py`. Он читает только `/api/health`,
Document Explorer и Dataset Notebook, чтобы проверять операторскую поверхность, а не обходить её
прямым чтением SQLite/Qdrant. Команда по умолчанию строит Markdown в stdout; для обновления
снимка: `uv run python -m tools.priority_corpus_inventory --output docs/EVIDENCE_CORE_PRIORITY_INVENTORY.md`.

Границы:

- Не читать и не чинить архивный хвост без приоритета.
- Не запускать reindex, OCR или parse-batch без отдельного утверждённого датасета.
- Не менять embedding, collection или retrieval до исходного inventory.
- Quarantine — статус/реестр причин, не удаление источника.

Критерии приёмки фазы:

- [x] Выбраны четыре приоритетных продуктовых контура: ПД ИЦ, BAI, Fire и сметы.
- [x] Зафиксирована техническая граница проектных и нормативно-ценовых источников смет.
- [x] Для каждого есть generated source-quality card; owner пока **UNSET** и должен быть назначен оператором.
- [x] Выявлены очереди, требующие решения: ПД ИЦ — 49 `PENDING`; нормативные сметы — 2 `PENDING` с повторным именем; BAI zero-chunk оказался служебным state-файлом, не evidence дефектом.
- [x] Первым датасетом следующей index-quality фазы выбран **BAI**: это полноценный проектный корпус без pending; Fire остаётся нормативным regression/golden контуром.
- [ ] Не выполнено ни одного массового мутирующего действия над корпусом.

### Решение по итогам inventory

| Контур | Решение | Почему |
|---|---|---|
| BAI | первый index-quality canary | 75 indexed, 5 ожидаемых `SKIPPED` raw CAD/BIM, единственный zero-chunk — служебный preprocess-state |
| Fire | regression/golden, без reindex | 125/125 indexed, нормативный corpus уже даёт FIRE/HVAC acceptance |
| TABLE_SMETA | baseline для table quality | 103/103 indexed; следующий сметный проход должен проверить table coordinates/headers, не заменять RAG новым индексом |
| Сметная нормативная опора | сначала manual disposition 2 pending | два XLSX имеют одно имя в raw/projection layers; отчёт не выбирает, что quarantine/parse |
| ПД ИЦ | сначала status/pending triage | 49 pending PDF и runtime `ERROR` при нуле document-row `ERROR`; это status drift или незакрытая очередь, не основание для массового parse |

Owner всех контуров пока `UNSET`: назначение владельца — операторское решение, его нельзя
выдумывать из метаданных. Reader-pass у текущих карт `bootstrap`; это отдельный navigation gate,
не повод подменять чтение summary-ответом.

## Дальше, только в этом порядке

1. **Evidence-core canary.** `les.evidence_packet.v1` в обычном RAG: retrieved chunks и
   navigation разделены, источник модели совпадает с UI citation; BAI golden фиксирует
   baseline без reindex.
2. **Index quality.** Версионированная коллекция и document-type chunking для первого
   приоритетного датасета только после результата canary; fingerprint embedding и source
   coordinates обязательны.
3. **Unified retrieval.** Exact/typed/FTS/dense с объяснимой fusion, реальным rerank,
   source diversity и target-file/topic navigation.
4. **Iterative model tools.** Модель выбирает bounded read/search/table/pdf/CAD tools и может
   уточнить чтение; код не пишет профессиональный ответ вместо неё.
5. **Domain migration.** ПД/РД, нормативка, таблицы, CAD/BIM и сметы используют один
   evidence-core; доменный код остаётся только там, где нужны structured data и расчёт.
6. **Evaluation and rollout.** Metrics по данным/retrieval/evidence/answer, golden-наборы,
   shadow run, переключение по одному датасету.

## Напоминание для следующей сессии

Короткая исполнимая очередь — [TODO_EVIDENCE_CORE.md](TODO_EVIDENCE_CORE.md); этот план
остаётся источником обоснования и границ.

Перед любой новой RAG- или сметной правкой сначала открыть этот файл и ответить:

```text
Это закрывает текущую фазу inventory?
Или это преждевременная оптимизация retrieval/prompt/domain-case?
```

Текущий следующий ход: **измерить широкий corpus-first retrieval на четырёх приоритетных
контурах.** Точный `target_file` нужен только когда его явно выбрал оператор; широкий вопрос
должен синтезировать доступный корпус без предположений о его типах или ожидаемых файлах.
