# Л.Е.С. как управленческий роман: система, ограничение и поток

**Дата:** 25.05.2026  
**Формат:** техническое описание в духе бизнес-романа о Теории ограничений  
**Состояние:** no-Docker host runtime, локальный Qdrant, MLX, guarded Qwen indexing

---

## Пролог. Завод, который должен отвечать

Вечером система снова остановилась не потому, что она не знала ответа. Она знала слишком много.

На диске лежали сотни нормативных документов: СП, ГОСТ, постановления, таблицы, письма, проектные файлы. Внутри них были числа, пункты, формулировки, исключения и ссылки друг на друга. Пользователь задавал простой вопрос: "какая минимальная ширина прохода?", но за этим вопросом стоял целый производственный поток: найти нужный датасет, поднять фрагменты, не перепутать пожарные нормы с архитектурными, не придумать ответ, проверить его и вернуть источник.

Снаружи это выглядело как чат. Внутри это был завод.

Цель завода была сформулирована просто: **давать локальные, проверяемые, быстрые ответы по нормативной и проектной базе, не отправляя данные в облако**.

Но у любого завода есть ограничение. Сначала казалось, что ограничение — Docker. Потом Qdrant. Потом память. Потом PDF. В конце выяснилось, что главное узкое место текущего потока — **эмбеддинги под нагрузкой индексации**, то есть время и память, которые нужны, чтобы превратить огромный корпус документов в векторы.

И тогда система была перестроена вокруг этого факта.

---

## Глава 1. Действующие лица

Л.Е.С. — Локальная Единая Система. Не один сервис, а связка ролей.

| Имя | Техническая роль | Бизнес-роль |
|---|---|---|
| **Ж.А.Б.А.** | Mac Mini M4 / 24 GB RAM | заводская площадка, где всё производится локально |
| **С.О.В.У.Ш.К.А.** | NiceGUI UI, порт `8051` | диспетчерская: чат, админка, карта состояния |
| **les-proxy** | FastAPI/Uvicorn, порт `8050` | центральный планировщик заказов и правил |
| **С.А.М.О.В.А.Р.** | RAG pipeline, datasets, Qdrant orchestration | цех приёмки и индексации знаний |
| **Т.О.С.К.А.** | CRAG validation через малую модель | отдел контроля качества ответа |
| **В.О.Л.К.** | API keys, роли, trusted contour, SQLite | охрана периметра и прав доступа |
| **П.Р.О.Р.А.Б.** | метрики, диагностика, runtime status | мастер смены, который видит состояние линии |
| **Д.И.А.Г.Н.О.З.** | `/api/diag` + UI-карта | табло готовности, нагрузки, ошибок и здоровья |
| **П.А.У.К.** | VPS + Caddy + ZeroTier/SSH fallback | внешний HTTPS-периметр без хранения данных |
| **Qdrant** | vector database, порт `6333` | склад адресуемой смысловой памяти |
| **MLX Host** | модели Qwen и embedder, порт `8080` | станок, который читает, сравнивает и формулирует |

Главное управленческое решение v3.6: **Docker больше не является участником производства**. Qdrant, proxy, UI, MLX и индексатор живут на host через `launchd`.

---

## Глава 2. Что производит система

Л.Е.С. производит не "текст от модели". Его продукт сложнее:

1. **Ответ на русском языке** по локальной базе.
2. **Источники**: документы, чанки, страницы или строки таблиц.
3. **Оценку достоверности**: `VERIFIED`, `NO_DATA` или `HALLUCINATION`.
4. **Маршрут принятия решения**: какой датасет выбран, какие фрагменты подняты, был ли rerank, был ли table-query.
5. **Артефакты**: таблицы, JSON, Mermaid, SVG, структуры, спецификации.

Для пользователя это выглядит как окно чата. Для системы это заказ, который проходит несколько рабочих станций.

---

## Глава 3. Карта потока

Полный поток запроса:

```text
Пользователь
  -> NiceGUI chat
  -> FastAPI /api/chat
  -> clarification gate
  -> query router
  -> dataset filter
  -> semantic cache
  -> Qwen embedding query vector
  -> Qdrant vector search
  -> optional reranker
  -> table query gate
  -> prompt assembly
  -> Qwen main model
  -> CRAG validator
  -> answer + sources + status
```

Полный поток индексации:

```text
RAG_Content / upload
  -> smart-plan / smart-upload
  -> deterministic document routing
  -> dataset registration in SQLite
  -> converter
  -> chunker
  -> Qwen embeddings
  -> Qdrant upsert
  -> SQLite metadata update
  -> health reconciliation: sqlite_chunks == qdrant_points
```

С точки зрения Теории ограничений, это не набор микросервисов. Это линия. Если одна рабочая станция медленнее остальных, вся линия производит с её скоростью.

---

## Глава 4. Узкое место

Индексация 800+ файлов показала неприятную правду: Qdrant не был главным тормозом. Конвертация тоже не была главным тормозом. SQLite не был главным тормозом.

Профилирование batch-ов показало: **около 99% времени уходит в `embed_sec`**.

Ограничение системы:

```text
embedding throughput + MLX/MPS memory pressure
```

Это ограничение диктует всё остальное:

- chat generation ставится на паузу во время массовой индексации;
- `parse_concurrency = 1`;
- `batch_limit = 1`;
- scheduler запускает короткие batches и проверяет память;
- Qdrant держится локальным binary без Docker VM;
- proxy не перезапускается во время активного parse-job без необходимости;
- каждое улучшение оценивается не "красотой", а влиянием на files/hour, swap, RAM и качество retrieval.

Так система перестала спорить с ограничением и начала управлять им.

---

## Глава 5. Пять шагов управления ограничением

### 1. Найти ограничение

Ограничение найдено в embedding stage:

- модель: `Qwen/Qwen3-Embedding-0.6B`;
- API-name: `qwen3-embedding-0.6b`;
- размерность: `1024`;
- коллекция: `les_rag_qwen3_06b`;
- chunk profile: `1400/100`;
- storage: `data/qdrant`;
- metadata DB: `data/les_meta_qwen.db`.

### 2. Использовать ограничение максимально эффективно

Ограничение не должно простаивать и не должно падать:

- `me.ovc.les.qwen-index-until-done` держит indexing loop живым;
- `tools/qwen_index_until_done.py` ждёт proxy и MLX;
- scheduler запускает waves по `max_batches=500`;
- внутри wave batch идёт по одному файлу;
- memory guard проверяет свободную RAM и swap;
- Qdrant и SQLite сверяются по количеству chunks/points.

### 3. Подчинить всё остальное ограничению

Пока узкое место занято индексом:

- chat generation paused;
- UI показывает `INDEXING`;
- reranker и validator не должны съедать общий бюджет без нужды;
- proxy restart откладывается, если active parse scheduler жив;
- Docker удалён, потому что он добавлял нестабильность и накладные расходы.

### 4. Расширить ограничение

План расширения:

- benchmark `RAG_EMBED_BATCH`: `8 -> 16 -> 24 -> 32`;
- chunk-text hash cache для retry без повторной векторизации;
- query-side instruction для Qwen embeddings без reindex;
- hybrid retrieval: dense + lexical + RRF;
- conditional reranking вместо rerank каждого запроса;
- parent-section retrieval вокруг найденных chunks;
- RAPTOR-lite и GraphRAG-lite только после golden-set проверки.

### 5. Вернуться к шагу 1

Когда embedding перестанет быть ограничением, следующим ограничением может стать retrieval quality, validation latency или UX. Система должна снова измерить поток, а не гадать.

---

## Глава 6. Runtime без Docker

Старый контур зависел от Docker/OrbStack. Новый контур живёт на host:

| Сервис | LaunchAgent | Порт | Назначение |
|---|---|---:|---|
| Qdrant | `me.ovc.les.qdrant` | `6333/6334` | vector DB, local binary |
| Proxy | `me.ovc.les.proxy` | `8050` | FastAPI, RAG, auth, metrics |
| UI | `com.les.sovushka` | `8051/8066` | NiceGUI + Qdrant visualizer |
| MLX | `me.ovc.les.mlx` | `8080` | LLM, validator, embedder |
| Indexer | `me.ovc.les.qwen-index-until-done` | — | guarded indexing loop |
| PAUK fallback | `me.ovc.les.pauk` | — | SSH tunnel fallback |

Технологический смысл этого решения:

- меньше фоновых процессов;
- нет Docker daemon/socket;
- нет VM bind mount latency;
- Qdrant persistence лежит прямо в `data/qdrant`;
- `launchd` сам поднимает критические процессы после reboot;
- Mac Mini становится appliance, а не dev-сервером с ручным запуском.

---

## Глава 7. Слой доступа

Снаружи пользователь видит HTTPS-домен. Внутри данные не покидают Mac Mini.

```text
Internet
  -> VPS Debian + Caddy + Let's Encrypt
  -> ZeroTier private route
  -> Mac Mini proxy/UI
```

VPS не хранит RAG, SQLite, Qdrant, документы или модели. Он только принимает HTTPS и прокидывает трафик. Если ZeroTier не работает, есть SSH tunnel fallback.

Доступ контролирует В.О.Л.К.:

- API keys в SQLite;
- роли `admin/user`;
- trusted local/private-network contour;
- server-side guards на FastAPI;
- trusted-proxy boundary для forwarded headers.

---

## Глава 8. MLX Host: станок модели

`mlx_host.py` — отдельный FastAPI-сервис на `:8080`.

Он поддерживает OpenAI-compatible endpoints и внутренние endpoints:

| Endpoint | Назначение |
|---|---|
| `/api/health` | состояние моделей и памяти |
| `/v1/models` | список доступных моделей |
| `/v1/chat/completions` | chat completion для proxy |
| `/v1/embeddings` | embedding endpoint |
| `/api/embeddings` | legacy-compatible embeddings |
| `/api/validate` | CRAG validation |
| `/api/unload_val` | выгрузить validator |
| `/api/unload_all` | освободить MLX memory |
| `/api/host_memory` | RAM/swap snapshot |
| `/api/ps` | loaded model inventory |

Модельные роли:

| Модель | Роль |
|---|---|
| `mlx-community/Qwen3.5-9B-MLX-4bit` | основной генератор ответов |
| `mlx-community/Qwen3-4B-Instruct-2507-4bit` | validator/reranker |
| `Qwen/Qwen3-Embedding-0.6B` | embeddings для Qdrant |
| `BAAI/bge-m3` | legacy baseline |

MLX Host делает несколько важных вещей:

- убирает `<think>...</think>` из Qwen output;
- нормализует embeddings;
- держит memory guard;
- умеет unload моделей;
- маршрутизирует запросы по точному имени модели;
- не зависит от shell env, потому что читает `.env` при старте.

---

## Глава 9. Qdrant: склад смысла

Qdrant хранит не документы, а точки:

```text
vector[1024] + payload(metadata) + content reference
```

Активная коллекция:

```text
les_rag_qwen3_06b
```

Профили embeddings:

| Profile | Model | Collection | Vector | Chunk |
|---|---|---|---:|---|
| `legacy` | `BAAI/bge-m3` | `les_rag` | 1024 | 900/80 |
| `quality` | `BAAI/bge-m3` | `les_rag_bge_m3` | 1024 | 900/80 |
| `qwen` | `Qwen/Qwen3-Embedding-0.6B` | `les_rag_qwen3_06b` | 1024 | 1400/100 |
| `fast` | `intfloat/multilingual-e5-small` | `les_rag_fast` | 384 | 1200/80 |

Ключевой инвариант:

```text
SQLite chunks == Qdrant points
```

Если эти числа расходятся, значит поток потерял синхронизацию между учётом и складом.

---

## Глава 10. SQLite: бухгалтерия завода

SQLite — не временная мелочь, а бухгалтерская книга:

| База | Роль |
|---|---|
| `data/les_meta_qwen.db` | Qwen profile metadata: datasets, files, chunks |
| `data/les_meta.db` | legacy metadata |
| `data/les_metrics.db` | time-series metrics |
| auth SQLite | ключи и роли В.О.Л.К. |

В SQLite живут:

- datasets;
- files;
- chunk counts;
- statuses: `PENDING`, `INDEXED`, `ERROR`;
- parquet artifact paths;
- semantic cache;
- jobs history;
- auth keys.

Qdrant отвечает на вопрос "где близкий смысл?". SQLite отвечает на вопрос "что у нас вообще есть и в каком состоянии?".

---

## Глава 11. Приёмка документов

Документ попадает в систему двумя путями:

1. Из `RAG_Content/` через sync/smart sync.
2. Через upload/smart upload.

Перед индексацией работает routing:

- `GKRF_Index`;
- `NTD_FIRE_Index`;
- `NTD_ELECTRICAL_Index`;
- `NTD_STRUCTURAL_Index`;
- `NTD_GEOTECH_Index`;
- `NTD_SPDS_Index`;
- `NTD_HVAC_Index`;
- `NTD_WATER_Index`;
- `NTD_PIPELINES_Index`;
- `NTD_TRANSPORT_Index`;
- `NTD_ARCH_URBAN_Index`;
- `NTD_CONSTRUCTION_Index`;
- `NTD_BIM_OPERATION_Index`;
- `NTD_SAFETY_Index`;
- `NTD_MATERIALS_Index`;
- `NTD_GENERAL_Index`;
- `NTD_OTHER_Index`;
- table indexes for estimates/specs where applicable.

Маршрутизация нужна не для красоты. Она уменьшает область retrieval и снижает риск смешать пожарные нормы с конструкциями или сметами.

---

## Глава 12. Конвертеры

Система читает разные форматы:

| Формат | Технология/подход |
|---|---|
| PDF | PyMuPDF / `pymupdf4llm` |
| DOCX | `mammoth` |
| XLSX/CSV | `pandas` |
| EML/MSG/PST | mail parsers, `extract-msg`, PST reader |
| JSON/MD/TXT | direct text parsing |
| tables | normalized rows + Parquet artifacts |

Цель конвертера — не просто вынуть текст. Цель — сохранить полезную структуру: имя документа, страницу, строку, dataset, content type, parquet path, домен.

---

## Глава 13. Chunking: нарезка без потери смысла

Для Qwen profile текущий chunk profile:

```text
chunk_size = 1400
chunk_overlap = 100
```

Это компромисс:

- крупнее legacy BGE chunks, чтобы уменьшить количество embedding calls;
- overlap сохраняет соседний контекст;
- меньше chunks на документ снижает нагрузку на узкое место;
- слишком крупный chunk ухудшит точность, поэтому качество проверяется golden-set тестами.

В будущем chunking должен стать нормативно-осознанным: не резать внутри пунктов, подпунктов, таблиц и ссылок.

---

## Глава 14. Query Router: первый диспетчер

Когда пользователь задаёт вопрос, система сначала не бежит к LLM. Она спрашивает: "в какой цех это отправить?"

`proxy/services/retrieval_service.py` использует deterministic routing:

| Сигналы | Dataset filter |
|---|---|
| `эвакуац`, `пожар`, `13130` | `NTD_FIRE` |
| `пуэ`, `кабел`, `заземл` | `NTD_ELECTRICAL` |
| `фундамент`, `нагрузк`, `железобетон` | `NTD_STRUCTURAL` |
| `грунт`, `сейсми` | `NTD_GEOTECH` |
| `отоп`, `вентиляц`, `акуст` | `NTD_HVAC` |
| `водоснаб`, `канализац` | `NTD_WATER` |
| `пп 87`, `гкрф`, `градостроительн` | `GKRF` |
| `смет`, `ведомост`, `таблиц` | `TABLE_SMETA` |
| `сп`, `гост`, `снип` | broad `NTD` |

Для ГКРФ и ПП 87 есть query expansion: если вопрос про состав разделов проектной документации, в retrieval query добавляются ожидаемые формулировки разделов. Это не ответ пользователю, а способ вернуть нужный документ из векторного поиска.

---

## Глава 15. Clarification Gate: не запускать завод без заказа

Если пользователь пишет "проверь всё" или "что не так", система не должна делать вид, что поняла задачу.

Clarification gate классифицирует:

- domain;
- intent;
- scope;
- route reason;
- reasons for clarification.

Если запрос слишком широкий, ответ не идёт в retrieval. Система задаёт до трёх уточняющих вопросов:

- какая область;
- что именно сделать;
- каким файлом/датасетом ограничить поиск.

Это управленческое правило: **не загружать ограничение работой, которая не определена как заказ**.

---

## Глава 16. Semantic Cache: память о повторных вопросах

Semantic cache хранит:

- normalized question;
- scope key;
- embedding JSON;
- answer;
- sources;
- CRAG status.

Поиск cache hit идёт через cosine similarity. Если пользователь задаёт почти тот же вопрос в том же scope, система может вернуть сохранённый ответ, не прогоняя весь дорогой pipeline.

Это не просто ускорение. Это разгрузка ограничения.

---

## Глава 17. Retrieval: найти не документ, а место ответа

Vector retrieval:

```text
question -> embedding -> Qdrant search -> top_k chunks
```

Обычный путь:

```text
top_k = 5
```

Если включён reranker:

```text
raw top_k = 8
Qwen validator/reranker -> top_k = 5
```

Reranker работает как дополнительный инспектор качества. Но он стоит MLX-времени, поэтому стратегически его нужно включать условно: когда retrieval неуверенный, broad или multi-hop.

---

## Глава 18. Table Query Gate: когда LLM не нужен

Если вопрос табличный, система сначала пытается ответить точно из Parquet:

```text
"посчитай сумму"
"сколько позиций"
"итого по расценке"
```

Алгоритм:

1. Проверить tokens табличного запроса.
2. Найти retrieved chunks с `parquet_path`.
3. Выбрать numeric field:
   - `amount`;
   - `qty`;
   - `price`;
   - `amount_mat`;
   - `amount_work`;
   - `work_done`;
   - `weight_total`.
4. Выбрать operation: `sum` или `list`.
5. Прочитать Parquet rows.
6. Отфильтровать rows по keywords.
7. Вернуть точный `VERIFIED` ответ.

Это важнейший принцип: **если можно посчитать, не надо просить модель угадывать**.

---

## Глава 19. Prompt Assembly и генерация

Когда retrieval готов, proxy собирает prompt:

```text
system prompt
+ retrieved context
+ citations/source hints
+ user question
+ output format instructions
```

Дальше запрос идёт в MLX:

```text
/v1/chat/completions
model = mlx-community/Qwen3.5-9B-MLX-4bit
```

UI поддерживает форматы:

- text;
- specification;
- schema;
- structure;
- table;
- Mermaid;
- SVG;
- template-style response.

Правая панель артефактов превращает ответ в рабочий объект, а не просто сообщение.

---

## Глава 20. Т.О.С.К.А.: контроль качества

CRAG validation — это постконтроль:

```text
answer + question + retrieval context -> Qwen3-4B validator
```

Результаты:

| Статус | Смысл |
|---|---|
| `VERIFIED` | ответ подтверждён источниками |
| `NO_DATA` | данных недостаточно |
| `HALLUCINATION` | ответ не подтверждён или противоречит контексту |

Главное правило: отсутствие ошибки модели не равно истинности ответа. Истинность устанавливается связкой retrieval context + validator + citations.

---

## Глава 21. UI как диспетчерская

С.О.В.У.Ш.К.А. разделена на два входа:

| Route | Назначение |
|---|---|
| `/` | лёгкий пользовательский чат |
| `/les` | админский контур |

Админка включает:

- обзор;
- С.А.М.О.В.А.Р. datasets/documents;
- П.Р.О.Р.А.Б. metrics;
- Qdrant visualizer;
- диагностику;
- В.О.Л.К. auth/admin.

Важный UX-принцип: обычный пользователь не должен платить загрузкой админских панелей за возможность задать вопрос.

---

## Глава 22. Диагностика и метрики

В интерфейсе эта роль вынесена в Д.И.А.Г.Н.О.З. — Диспетчер Инфраструктурного Анализа Готовности, Нагрузки, Ошибок и Здоровья. Его первая обязанность — не завалить оператора деталями, а показать живую карту контура: где зелёный поток, где задержка, где настоящий красный узел.

П.Р.О.Р.А.Б. смотрит на систему как мастер смены:

- RAM;
- CPU;
- disk;
- Qdrant health;
- Qdrant points;
- proxy health;
- MLX loaded models;
- queue;
- CRAG rates;
- indexing mode;
- runtime status.

Теперь П.Р.О.Р.А.Б. не только смотрит, но и держит аварийные рубильники. Если proxy лежит, кнопки в С.О.В.У.Ш.К.А. всё равно работают напрямую через локальный `launchd`: поднять контур, остановить контур без остановки UI, перезапустить Qdrant, MLX, proxy, UI или guarded indexer.

Диагностика больше не вызывает Docker. Docker runtime отображается как intentionally removed, потому что это теперь факт архитектуры, а не авария.

---

## Глава 23. Job Scheduler: не толкать поток руками

Индексатор работает как автоматический диспетчер:

```text
tools/qwen_index_until_done.py
  -> /api/indexing-mode
  -> /api/health snapshot
  -> /api/rag/parse-scheduler
  -> poll active job
  -> repeat until pending_files = 0
```

Parse scheduler защищён:

- duplicate guard: не запускать второй scheduler, если первый активен;
- memory guard: не стартовать при плохой RAM/swap;
- batch accounting: processed/total/message;
- durable jobs history;
- graceful continuation after interruption.

Это убирает ручное "ну ещё один batch". Система сама тянет поток, но не быстрее ограничения.

---

## Глава 24. Документы как актив

Индекс — это не временный cache. Это производственный актив.

Поэтому модернизация начинается с правил:

1. Не делать full reindex без доказанной необходимости.
2. Дождаться `pending_files=0`.
3. Проверить `error_files=0`.
4. Проверить `sqlite_chunks == qdrant_points`.
5. Сделать snapshot SQLite и Qdrant.
6. Прогнать golden retrieval set.
7. Только после baseline менять retrieval algorithms.

Иначе улучшение может уничтожить уже оплаченный временем индекс.

---

## Глава 25. Golden Set: бухгалтерия качества

Ускорить систему легко. Сломать качество ещё легче.

Golden set нужен, чтобы измерять:

- вернулись ли правильные документы;
- не упал ли score;
- не потерялись ли ключевые домены;
- сколько времени занял retrieval;
- сколько памяти ушло;
- изменился ли CRAG status.

Только так можно понять, является ли новый алгоритм улучшением или просто движением.

---

## Глава 26. Будущие алгоритмы

После стабилизации индекса планируется не "добавить магии", а расширить поток по шагам.

### Hybrid Retrieval

```text
dense vector search
+ lexical/sparse search
+ RRF fusion
```

Нужно для точных номеров пунктов, обозначений СП/ГОСТ и терминов, которые vector search может сгладить.

### Retrieval Evaluator

Перед генерацией система оценивает:

- слабые ли top results;
- есть ли конфликт;
- слишком ли широкая область;
- нужен ли rewrite;
- нужен ли rerank.

### Conditional Rerank

Reranker запускается не всегда, а только когда retrieval uncertainty высокая.

### Parent-Section Retrieval

Найден маленький chunk — в prompt добавляется родительский раздел, чтобы ответ не вырывался из контекста.

### RAPTOR-lite

Иерархические summaries по документам/датасетам для широких вопросов.

### GraphRAG-lite

Не полный graph over everything, а полезные связи:

- document -> clause;
- clause -> referenced SP/GOST;
- document -> domain/topic;
- project artifact -> normative requirement.

---

## Глава 27. Почему это бизнес-система, а не просто RAG

Обычный RAG отвечает на вопрос. Л.Е.С. управляет производством ответа:

- принимает заказ;
- уточняет заказ;
- выбирает маршрут;
- бережёт узкое место;
- использует склад знаний;
- проверяет качество;
- показывает источники;
- пишет метрики;
- переживает перезапуск;
- работает локально.

В бизнес-терминах throughput системы — это не tokens/sec. Это **количество проверяемых полезных ответов в единицу времени при сохранении доверия к источникам**.

Inventory системы — это:

- pending files;
- chunks;
- Qdrant points;
- cached answers;
- unverified outputs;
- незавершённые jobs.

Operating expense — это:

- MLX memory;
- embedding time;
- reranker calls;
- validator calls;
- CPU/RAM/swap;
- человеческое внимание на восстановление после падений.

Цель управления — увеличить throughput, не раздувая inventory и не превращая operating expense в пожар.

---

## Глава 28. Текущий статус линии

На момент описания:

- runtime: no-Docker;
- Qdrant: local binary + LaunchAgent;
- active collection: `les_rag_qwen3_06b`;
- profile: `qwen`;
- vector size: `1024`;
- chunking: `1400/100`;
- indexing: guarded `batch_limit=1`;
- chat generation: paused during indexing mode;
- hourly watch: active;
- Docker/OrbStack: removed from штатный runtime;
- protected macOS Docker metadata stub may remain but is not runtime.

Критический принцип эксплуатации:

```text
Не перезапускать proxy во время active parse scheduler без причины.
```

UI можно перезапускать безопаснее, потому что он не держит scheduler state. Proxy держит in-memory active job, поэтому его рестарт — это производственное вмешательство.

---

## Эпилог. Вопрос, который изменил архитектуру

В какой-то момент команда перестала спрашивать: "как заставить всё работать быстрее?"

Она спросила иначе: "что мешает системе производить проверяемые ответы устойчиво?"

Ответ оказался не в одной библиотеке и не в одной модели. Ответ был в потоке.

Docker был удалён не потому, что Docker плох сам по себе, а потому что в этой системе он перестал помогать потоку. Qdrant был оставлен не потому, что моден, а потому что хорошо выполняет роль склада векторов. MLX выбран не ради новизны, а потому что Apple Silicon уже стоит на столе и умеет работать локально. Clarification gate добавлен не ради "умного UX", а чтобы не загружать ограничение неопределёнными заказами. CRAG нужен не ради статуса, а потому что доверие к ответу — часть продукта.

Л.Е.С. — это локальная фабрика инженерного знания. Её главный закон прост:

> Не производить больше шума. Производить больше проверяемого смысла.
