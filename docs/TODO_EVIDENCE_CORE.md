# TODO · healthy LES evidence core

Последнее обновление: 2026-07-10. Это короткая рабочая очередь; обоснование и границы — в
[PLAN_EVIDENCE_CORE.md](PLAN_EVIDENCE_CORE.md). Перед каждой новой RAG- или сметной задачей
сначала открывать этот файл и начинать с первого незакрытого пункта.

## Сейчас

- [ ] Перевести весь текущий общий корпус, а не только canary-датасеты, в contract-v2 collection:
  все source points представлены, каждый destination point имеет named `dense` + `bm25_sparse`,
  каждый активный dataset проходит filtered live RRF. После этого переключить production и запретить
  дозапись при drift контракта. Любой будущий dataset получает этот путь автоматически.
- [x] Удалить альтернативные RAG-архитектуры из runtime: unnamed schema, sparse sidecar,
  vector-copy migration, env-переключение на legacy backend и domain-prose query expansion.
  Неактивные Qdrant `les_rag`, `les_rag_qwen3_06b`, `contract_v1`, `_sparse` и smeta v1 удалены;
  текущие `native_v1`/smeta v2 живут только до успешного clean switch.

- [x] Убран BAI-specific negative contract: широкое чтение не зависит от ожидаемого имени,
  типа или отсутствия конкретного файла.
- [x] Notebook reading plan и target-file spread строятся из реальных headings/file groups
  выбранного корпуса. Это bounded coverage, не заявление, что модель прочитала весь архив.
- [x] Reader-pass для первого NotebookLM-сценария принимает только реальные file cards/folder groups/
  section map, а его model output очищается от несуществующих file names и заранее заданной taxonomy.
- [x] Target-file reading не считает chunk другого файла доказательством выбранного файла; guide
  показывает покрытие групп и discarded mismatches вместо ложного success.
- [x] Qwen query embedding contract versioned: `raw-v1` baseline и opt-in
  `qwen-retrieval-v1` с trace id; документы остаются raw, reindex для A/B не нужен.
- [x] Удалена подмена expected terms из `/api/rag/retrieve-debug`; прежние debug-based
  FIRE/HVAC/golden результаты аннулированы до чистого перезапуска.
- [x] Добавлены fail-closed `les.rag.index-contract.v1`, общий tokenizer-budget и mixed-base64
  gate для всех parser outputs.
- [x] Retrieval разделяет dense/RRF/rerank scores, retry сохраняет backend, rerank и citation
  integrity видны в trace.
- [x] Evidence assembler покрывает разные источники, сохраняет table header и не останавливается
  на одном большом чанке; model research loop ограничен тремя раундами.
- [x] Создать contract-clean sibling-canary под `0.24.0.352` для BAI, ПД ИЦ и Fire.
  `les_rag_qwen3_06b_contract_v1`: по 256 source points на корпус →
  `397/297/278` clean points, всего `972`; sample `972/972` имеет один Qwen/Core ML
  fingerprint, token-budget и sanitation metadata, manifest compatible. Текущую коллекцию не
  «усыновлять»: sample 1000 старых точек показал 5 fingerprints
  (`672/146/128/53/1`), разные backend/seq_len/compute/fallback и одну точку без model id;
  token-budget/sanitation metadata отсутствует `1000/1000`.
- [x] Подтвердить manifest и filtered dense retrieval на canary: BAI/ПД ИЦ/Fire
  возвращают по `3/3` chunks без debug-подмены. Production не переключён: canary покрывает лишь
  bounded subset, а missing/mismatch намеренно оставляет старый dense выключенным; не обходить
  `RAG_INDEX_CONTRACT_ENFORCE=true`.
- [x] Подтвердить настоящий native dense+sparse RRF на clean canary: FIRE-запрос дал разные
  dense/sparse top-5 (пересечение `2/5`), fused top-5 получил кандидатов из обоих каналов и поднял
  релевантный фрагмент СП 1.13130 на первое место. Production по-прежнему lexical-only из-за
  загрязнённой коллекции; single-channel выдачу больше не маркировать как hybrid/RRF.
- [ ] Пересобрать чистые FIRE/HVAC оценки из неизменённого debug output и вручную проверить
  первоисточники ожидаемых кейсов.
- [ ] Добавить к factual golden cases reviewer, source file/page/section и дату проверки; без
  provenance кейс остаётся smoke, а не ground truth.
- [ ] Отделить runtime/corpus-dependent тесты маркерами и добавить CI для offline `test-rag-core`.
- [x] Закрыть два сметных finality regression в `test_direct_mass_*`: finality состава/количеств
  отделена от `pricing_status`, а сценарные/formula gaps остаются partial.
- [ ] Измерить broad-coverage retrieval на BAI, ПД ИЦ, Fire и сметах: какие реальные группы
  файлов были запланированы, прочитаны и попали в evidence-пакет.
- [x] Удалить test-only `TABLE_SMETA_Index`: `690` active points, `310` canary points,
  `690` FTS rows, `103` MetaDB documents и runtime storage удалены; исходные системные базы
  ГЭСН/ФГИС не затронуты.
- [x] Ввести системный dataset contract: `dataset_scope=system`, `module_id`; сметные
  `SMETA_SERVICE_Index`, `SMETA_RU_NORM_*` и GESN projection принадлежат модулю `smeta`,
  показываются отдельной группой и добавляются только к smeta-turn.
- [x] Зарегистрировать generated `SMETA_SERVICE/**` в новом `SMETA_SERVICE_Index` без parse:
  runtime создал `system/smeta` dataset и принял `98` файлов. Индексировать только после чистого
  production collection switch, не обходя index contract.
- [ ] Выполнить Qwen raw-v1 ↔ qwen-retrieval-v1 A/B на golden-наборах по source/section/table-row
  recall и latency; включать instruction только при измеримом выигрыше.
- [ ] На следующем доменном переносе подключить `les.evidence_packet.v1` к одному потребителю:
  сначала PD/RD или normcontrol; сметный калькулятор не заменять RAG-пакетом.

## Затем

- [x] Сделать bounded dry-run/canary QA по oversize/base64/fingerprint для BAI, ПД ИЦ и Fire;
  полный reindex не запускался.
- [ ] Продолжить resumable sibling migration после разделения scope; полный production switch
  только при покрытии нужных datasets и чистых retrieval/evidence gates.
- [ ] Добавить retrieval/evidence golden для ПД ИЦ, Fire и смет. Fire `domain_fire_hvac_set.json`
  остаётся обязательным domain gate.
- [ ] Добавить conflict и domain missing-input contract после измерений; source versions и
  table headers уже входят в общий пакет при наличии metadata.
- [ ] Перевести PD/RD, normcontrol, generic tabular project datasets и CAD/BIM на общий пакет,
  не создавая независимые RAG-пайплайны.

## Не делать без отдельного решения

- Полный reindex, OCR/parse-batch, новую vector DB или замену embedding-модели.
- GraphRAG, multi-agent orchestration, крупную новую модель или prompt-only «улучшение».
- Hardcoded профессиональные ответы. Модель выбирает и отвечает; код ищет, хранит provenance,
  выполняет формальные проверки и считает.
