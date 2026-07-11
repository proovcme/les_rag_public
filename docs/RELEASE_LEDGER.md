# RELEASE_LEDGER — где мы сейчас (единый источник состояния)

> **Единственный источник правды о версии/деплое.** Не «хер знает где мы»: здесь — что за версия, какой
> commit в dev, какой задеплоен на рантайм, что вошло. Сверяй с `GET /api/version` и `git log`.
> Модель — locia `SERVER_BUILD_LEDGER`. Канон-бэклог — [../ROADMAP_TO_V1.md](../ROADMAP_TO_V1.md).

## Текущее состояние (2026-07-11)

```
версия (схема 0.N.FEATURE.PATCH): 0.24.0.364  (в КОДЕ: LES_VERSION; в /api/version поле les_version)
ветка:                     feat/les3-p1
dev HEAD:                  HEAD  (см. git log -1)
задеплоено на рантайм:     0.24.0.364 UI-only поверх runtime-базы 0.24.0.357
НЕ задеплоено:             RRF contract-v2 0.24.0.360, smeta-изменения 0.24.0.358 и прочий dev divergence
рантайм /api/version:      0.24.0.364, stamp ok, public/local подтверждены
```

> 0.24.0.364 — читаемые Qdrant-справки Л.И.С.Т.
>
> Дата: 2026-07-11
> Статус: dev + runtime, UI-only deploy 2026-07-11.
> Л.И.С.Т. закреплён как файловый проводник проекта: без ИИ показывает структуру и извлечённые
> проектные данные, а через существующий индекс Qdrant/LES даёт проверяемые справки. Справка
> о датасете теперь всегда находится над статистикой и собирается из фрагментов нескольких
> индексированных документов; справка о файле открывается кликом по строке. Карточки датасетов,
> файлов, дерева и статистики очищены от россыпи контурных меток, raw CAD/BIM error заменён
> человеческим пояснением, служебные dot-файлы отсортированы в конец. BAI browser smoke:
> справка датасета `Qdrant/LES · 5 955 фрагментов · прочитано 4 файла`, справка выбранного PDF —
> `Qdrant/LES: 100 фрагментов`, selected-state один, чипов в карточках датасетов/файлов — `0`.
> Проверки: `18 passed`; `make verify` — `2741 tests collected`; `make test` не запускался по
> указанию пользователя. Deploy: `documents.py`, `styles.py`, `version_service.py`; local/public
> `/api/version=0.24.0.364`, deploy stamp `ok`, hash mismatch `[]`.

> 0.24.0.363 — проводник состава датасета
>
> Дата: 2026-07-11
> Статус: dev + runtime, UI-only deploy 2026-07-11.
> «Состав датасета» стал read-only проводником Л.И.С.Т.: иерархия папок с вложенными файлами,
> переключатели `Дерево / Плитка / Список / Таблица`, статистика по форматам и состоянию, фильтры
> по папке, расширению, статусу, типу metadata и имени/пути, а также инспектор выбранной папки.
> Для файла инспектор показывает metadata и краткую справку по индексированным фрагментам; при
> наличии `point_id` источник честно маркируется `Qdrant/LES`, иначе — `Индекс LES`. В левую панель
> возвращён явный фильтр `Все / Проекты / Не проекты`; пока `dataset_kind` у всех живых корпусов
> пуст, UI использует ограниченный fallback по известным системным префиксам, не меняя metadata.
> Browser smoke на BAI: 80 файлов, пять полей фильтрации, таблица на 80 строк и чистая справка
> проектного PDF из 100 Qdrant/LES-фрагментов. Проверки: `18 passed`; `make verify` —
> `2741 tests collected`; `make test` не запускался по указанию пользователя. Deploy:
> `documents.py`, `styles.py`, `version_service.py`; local/public `/api/version=0.24.0.363`,
> deploy stamp `ok`, hash mismatch `[]`.

> 0.24.0.362 — информативный состав датасета
>
> Дата: 2026-07-11
> Статус: dev + runtime, UI-only deploy 2026-07-11.
> «Состав датасета» больше не подменяет полный корпус коротким PDF-source-map Л.И.С.Т. Блок строится
> по всему реестру документов и только обогащает его LIST-метаданными. Сразу раскрыты: общее число
> файлов и папок, доступно/ожидает/проверить, распределение форматов и карточки первых 12 папок с
> количеством, форматами и тремя примерами файлов. Для ARTEL_Index UI показывает 134 файла,
> 74 папки, 87 доступных, 47 ожидающих, MD 132/PDF 2 вместо прежнего малоинформативного заголовка.
> Проверки: `18 passed`; `make verify` — `2747 tests collected`; browser smoke на ARTEL_Index;
> `make test` не запускался по указанию пользователя. Deploy: `documents.py`, `styles.py`,
> `version_service.py`; local/public `/api/version=0.24.0.362`, stamp `ok`, mismatch `[]`.

> 0.24.0.361 — визуальная СОД документов и широкий композер
>
> Дата: 2026-07-11
> Статус: dev + runtime, UI-only deploy 2026-07-11.
> Вкладка «Документы» перестроена поверх существующего read-only Document Explorer: единый поиск,
> три панели `Датасеты / Файлы / Обзор`, карточки без UUID и chunk chrome, типовые иконки файлов,
> режимы `Обзор/Текст/CAD-BIM` и вторичные действия через меню. Л.И.С.Т. остаётся source-map и
> показывает состав датасета, проектную структуру, разделы и файлы; mutation-кнопки классификации,
> перечитывания PDF и операторской заметки убраны из первого слоя. Композер чата расширен до
> адаптивных `1440px`, чтобы совпадать с рабочей шириной ленты. Backend API/retrieval не менялись.
> Проверки: `51 passed`; `make verify` — `2744 tests collected`; browser smoke на отдельном `:8052`
> и live `:8051`: 36 карточек датасетов, 134 файла в выбранном корпусе, UUID/chunk chrome скрыты,
> все видимые действия ≥40 px, chat composer `1170/1248px` (`94%`, max `1440px`). `make test`
> не запускался по прямому указанию пользователя. Deploy: `documents.py`, `styles.py`,
> `version_service.py`; local/public `/api/version=0.24.0.361`, stamp `ok`, mismatch `[]`.

> 0.24.0.360 — corpus-wide contract-v2 native RRF
>
> Дата: 2026-07-11
> Статус: dev; deploy заблокирован до полного re-embed/readiness gate.
> Причина: активная production collection физически содержит dense vectors, но sample-аудит выявил
> пять несовместимых embedding fingerprints и два backend-а. Fail-closed contract поэтому корректно
> оставляет runtime в lexical-only. Частный canary доказал, что Qwen dense + BM25 sparse + Qdrant RRF
> работает, но три датасета не являются системным исправлением.
> Правки: native RRF стал кодовым default; contract v2 привязан к collection и фиксирует embedding,
> chunking, named dense/sparse schema и point fingerprint. Parse больше нельзя запустить без
> совместимого contract и нельзя записать named-point без обоих vector channels. Мигратор по умолчанию
> берёт все indexed datasets, умеет настоящий resume, пишет migration report и требует 100% source
> coverage без dropped points. `rag_rrf_readiness.py` блокирует activation без полного migration
> report, единого fingerprint, dense+sparse у каждой точки и покрытия каждого dataset. Старый CLI,
> копировавший legacy dense vectors, выведен из эксплуатации. Trace различает настоящий RRF и
> single-channel fallback.
> Read-only приёмка scope: `34` indexed datasets покрывают `228017/228017` production points,
> orphan scope `0`. Canary live probe: dense/sparse top-5 пересеклись на `2/5`, fused top-5 получил
> кандидатов из обоих каналов и поднял релевантный СП 1.13130 на первое место.
> После решения «один системный курс» удалены runtime sparse-sidecar, unnamed/legacy backend env
> choices, vector-copy/sparse-reindex CLI и domain-prose query expansion; фиксированные окна строк
> старого smeta selector обезврежены. Из Qdrant удалены неактивные `les_rag`, старый unnamed Qwen,
> bounded contract-v1, sparse-sidecar и smeta v1. До clean switch сохранены только активный общий
> `native_v1`, активный smeta v2 и строящийся с нуля CoreML+BM25 smeta v3; общий contract-v2 будет
> создан очередью после readiness v3.
> Проверки на этом этапе: `py_compile` изменённых Python-модулей; тесты намеренно отложены до
> завершения уже идущего smeta dense build. Runtime, Qdrant production collection и сервисы не менялись.

> 0.24.0.359 — conversation-first UI чата
>
> Дата: 2026-07-11
> Статус: dev + runtime, UI-only deploy 2026-07-11.
> Верхний слой чата очищен от инженерных меток и вторичных действий. Добавлены четыре явных режима
> `Auto/Search/Estimates/Normcontrol` с коротким объяснением ожидаемых запросов и данных и максимум
> тремя примерами, которые заполняют ввод без автоматической отправки. Команды, документы, служебные
> источники и артефакты перенесены в компактное меню; технические `RAG/CRAG/MODEL` сохранены скрыто,
> чтобы не менять текущую механику. Панель артефактов больше не открывается для обычного текста.
> Backend payload, retrieval, model routing и живой runtime не менялись.
> Проверки: браузерный smoke на отдельном NiceGUI `:8052` (переключение режима, заполнение примера,
> закрытый artifact panel, свёрнутые команды, размеры действий); `64 passed`; `make verify` —
> `2737 tests collected`; полный `make test` — `2735 passed`, два устаревших ожидания старого меню,
> после замены этих контрактов затронутый набор зелёный.
> Деплой: точечно перенесены `sovushka/pages/chat.py`, `sovushka/styles.py` и
> `proxy/services/version_service.py`; перезапущены только Sovushka и proxy. Local/public
> `/api/version` показывают `0.24.0.359`, deploy stamp `ok`, mismatch-файлов нет. Публичный
> `/classic` сохраняет штатный `307 → /login`; новый UI проверен в том же runtime на `:8051/classic`.

> 0.24.0.358 — архитектурный инвариант первой денежной ЛСР
>
> Дата: 2026-07-11
> Статус: dev, deploy после полного gate.
> Основной `estimate` закреплён как `model + skill/prompt → RAG/tools → calculator → formula XLSX`.
> Модель выбирает работы, нормы, аналоги и coverage; код проверяет показанный/открытый код, единицы
> и арифметику. Resource/component review, dominant review и пользовательское согласование отложены
> до последующей ревизии и не могут блокировать первую ЛСР. `bind_norm` больше не требует расширенный
> technology/component JSON. Native workflow сохраняет полный evidence открытых карточек и не имеет
> короткого лимита, завершающего модель до решений. Архитектура описана в `ALGO-smeta`, `SMETA_MECHANICS`,
> `modules/smeta-core`, `CODE_MAP`, `MODULE_INDEX` и smeta skill/reference. Регрессии проверяют отсутствие
> pre-LSR reviewers, минимальный model-owned bind и одну задачу на 50 строк.

> 0.24.0.357 — исполнимый resource review и честная полнота ЛСР
>
> Дата: 2026-07-11
> Статус: dev + runtime targeted port; полный 7/10 live-gate не закрыт.
> Живой native-agent теперь получает reference-карту структуры ГЭСН и хранилища LES. `bind_norm`
> требует явное model decision `selected` и машинный conclusion применимости. Каждая выбранная норма
> требует `keep_all_confirmed|actions_confirmed|unresolved`; пустые actions аналога больше не означают
> молчаливое принятие чужих ресурсов. РИМ хранит `known_amount/full_amount`; missing цена, ФСЭМ/ОТм
> или resource review делают полную стоимость null и меняют подписи XLSX на известную часть.
> Первый fresh GPT-5.4 БАП: 207,7 с, 19 visible, 8 bound / 11 open, известная часть
> 35 174,65 / 42 913,07 руб., full null. Он вскрыл отсутствие runtime ФСЭМ и несовпадение имён полей
> resource actions. После исправления ФСЭМ (1 576 строк) и точного action contract второй fresh запуск
> остановлен provod.ai с HTTP 402 на третьем ходу. 7/10 пока не заявляется.
> Проверки: focused финальный smeta/service-source/prompt/artifact/FSEM/RIM gate `80 passed`; расширенный
> smeta/chat gate ранее `153 passed`; `make verify` green (`2722 collected`); skill validation green.
> Полный `make test` до последнего boundary-fix: `2694 passed, 28 failed`; один новый artifact-fail затем
> исправлен и его focused test green, остаются прежние 27 legacy construction/spec/unified/context failures.
> Runtime: `0.24.0.357`, alignment 102/102, FSEM service source `ok`.

> 0.24.0.356 — человеческий ответ ЛСР и промежуточная цель качества 7/10
>
> Дата: 2026-07-11
> Статус: dev only.
> Машинный `smeta_document_workflow_v2` не пересказывается пользователю: отдельный детерминированный
> formatter сообщает покрытие строк, стоимость рассчитанной части и подготовленный Excel русским
> текстом и форматом денег. Skill закрепляет ту же границу. Живой БАП 14 bound / 5 open зафиксирован
> как промежуточный успех, а resource review аналогов, `known_amount/full_amount`, ФСЭМ/ЗПМ и
> согласованность текста решения с binding — как обязательный гейт к 7/10.
> Проверки: formatter/core/chat focused suite `86 passed`; skill validation passed; `make verify`
> green (`2719 collected`). Полный `make test`: `2692 passed, 27 failed`; новый formatter и smeta-core
> green, падения находятся в ранее дрейфующих legacy F9/specification/unified/profile/retrieval слоях.

> 0.24.0.355 — model-direct smeta RAG, quantity contract и живой БАП
>
> Дата: 2026-07-11
> Статус: dev + targeted runtime port, полный ship gate выполняется после живой ЛСР.
> GPT получает исходник, skill и native search/read/bind/coverage tools без code-side stage selector.
> Все search_norms одного хода дедуплицируются и исполняются batch; mass triage использует hybrid/RRF
> без последовательного rerank, узкий повторный поиск сохраняет rerank. `quantity_multiplier` удалён:
> source/unit conversion/norm quantity разделены и покрыты тестами 8 шт, 3,2 м² и 160 м. Missing price
> остаётся null. Technology binding fail-closed, когда модель сама указала missing/extra/foreign.
> Live БАП: 419 с до дальнейшего latency-долга. Созданная позднее аудиторская ревизия не считается
> результатом модели и не подменяет raw ЛСР; актуальный промежуточный результат зафиксирован в 0.24.0.356.

> 0.24.0.354 — zero-state PDF → ЛСР в штатном чате
>
> Дата: 2026-07-10
> Статус: dev, deploy только после полного gate.
> Правки: `mode=read` сохраняет исходный файл на 6 часов под server-owned `read_<id>` с hash/size
> проверкой; UI передаёт opaque id, не путь. В режиме «Смета» явный запрос ЛСР по PDF идёт в
> `smeta_core.document_workflow`: новый intake без истории/предыдущей ревизии, model-owned выбор
> exact/analog/НР-СП, coverage, множителей и resource actions, model-owned binding точного кода
> ФГИС, fail-closed web-КАЦ по минимум трём exact-product supplier domains, затем кодовая РИМ/НДС
> арифметика и формульный XLSX. Успешное вложение одноразовое; при ошибке сохраняется для retry.
> Объектных/БАП-специфичных правил нет. Focused gate: `92 passed`; живой локальный BAP smoke
> остаётся обязательным до ship, так как Qwen 9B показала высокую batch latency.

> 0.24.0.353 — smeta-core phase 0/1: fail-closed normative integrity
>
> Дата: 2026-07-10
> Статус: dev only до полного gate/deploy.
> Причина: аудит доказал cross-family contamination текущей structured ГЭСН-базы и скрытый
> fallback выбора первого сильного кандидата после невалидного ответа модели.
> Правки: добавлен `proxy/smeta_core` с typed contracts, `smeta_norm_browse_v1`, canonical workflow
> adapter и раздельными `evidence_status`/`calculation_status`. Любая code-owned `NormBinding`
> запрещена. Fallback/не-модельные env-bind пути удалены. ГЭСН source registry теперь требует
> совпадающий `les_smeta_base_integrity_v1`; без него текущая база получает
> `quarantined_blocking`, structured money остаётся `priced_partial/unsafe_source`. Quick price
> lookup использует manifest-default pricebook. Остаток фаз записан в `docs/TODO_SMETA_CORE.md`.
> Проверки: focused smeta/core/chat/version suite `250 passed`; `make verify` — `2768 collected`;
> полный `make test` — `2768 passed / 6 warnings`; lock/diff checks — выполнить перед ship.

> 0.24.0.344 — Л.И.С.Т. reliability hardening
>
> Дата: 2026-07-10
> Статус: готово локально, не задеплоено; source-map не перестраивался.
> Причина: аудит живого sidecar выявил системные ложные роли/дисциплины из substring matching
> (`ДОГОВОР→ВОР`, `СОСТАВ→СО`, `ПЗУ→ПЗ`, почти все PDF→ОВ), завышение
> `files_extracted`, неполные bounded-массивы без total/truncated, слабые
> `line/length`/`quantity` признаки таблиц и незащищённый path component `dataset_id`.
> Правка: filename/cipher tokens и whitelist заменили подстроки; composition rows больше не
> делают соседний файл электрическим. Summary различает attempted/successful и
> `ok/partial/failed/empty`; warnings/source refs/volume register имеют total+truncated, а
> row/table refs идут первыми. Dataset ID проверяется как один безопасный компонент. Shared
> table classifier требует составные признаки кабеля и ВОР. Совушка показывает успешные,
> error/missing и truncation честно, фильтр датасетов применяется сразу. Публичный `les-list`
> получил те же guards, installable CLI, wheel data fallback, CI и package version `0.1.1`.
> Проверки: focused LES `79 passed`; public `105 passed`; public compileall, lock/diff checks,
> wheel build + isolated install/CLI/YAML smoke; `make verify` green (`2728 collected`). Полный
> `make test`: `2711 passed`, `17 failed`; все падения вне Л.И.С.Т. — 2 в параллельно изменённом
> estimate finality, 1 в retrieval `exact_refs`, 14 в legacy live-unified/fake-backend маршрутах.
> Профиль Л.И.С.Т. в полном прогоне green (`24 + 48 + 7`). Runtime/reindex/rebuild не запускались.
> Историческая пометка evidence-core о конкретной архитектурной ведомости BAI отменена в
> dev `0.24.0.345`: broad RAG не зависит от ожидаемого имени или типа файла. До deploy `0.24.0.344`
> не получает эту отмену и остаётся только текущим runtime Л.И.С.Т. bundle.

> 0.24.0.345 — corpus-first notebook read
>
> Дата: 2026-07-10
> Статус: dev only, runtime не обновлялся.
> Причина: broad RAG не может предполагать, что в следующем датасете есть АР, ВОР, паспорт,
> инженерный том или иной заранее известный тип файла. BAI-specific negative case и требование
> внешней архитектурной ведомости были сняты как неверная архитектурная развилка.
> Правки: `notebook_study_service` строит section plan из фактических topic/section maps, file
> cards и folder groups, а bounded target-file pass берёт представителей реальных групп без
> штрафа смет/таблиц. `EvidencePacket` при `partial` использует найденные фрагменты, но явно
> не называет их полным покрытием; при `missing` не изображает отсутствующий факт. BAI canary
> проверяет реально доступную таблицу, не вымышленный ожидаемый документ.
> Проверки: focused notebook/evidence/golden tests и `make verify` — выполнить перед deploy.

> 0.24.0.347 — corpus-first dataset reader
>
> Дата: 2026-07-10
> Статус: dev only, runtime не обновлялся.
> Причина: первый NotebookLM-сценарий должен отвечать на «что в выбранном датасете?», не
> предполагая заранее проект, паспорт, нормативку, смету или какой-либо иной состав корпуса.
> Правки: model reader-pass получает только реальные file cards, section map и summary фактических
> folder groups; при лимите сначала покрывается по одному представителю группы. Input явно сообщает
> его границу. Model output очищается от имён файлов, отсутствующих в карте корпуса. Wide prompt
> требует от модели рассказать, какие материалы представлены, что в них содержится, какие источники
> важны и где граница чтения; карта остаётся navigation, а факты — только retrieved evidence.
> Проверки: focused dataset-memory/notebook/evidence/chat/version suite `89 passed`; `make verify`
> green (`2737 tests collected`). Ни reindex, ни OCR, ни parse, ни deploy не запускались.

> 0.24.0.348 — target-file evidence identity
>
> Дата: 2026-07-10
> Статус: dev only, runtime не обновлялся.
> Причина: `doc_filter` и непустой retrieval-result сами по себе не доказывают, что модель прочла
> выбранный файл. Иначе соседний файл мог ложно закрыть target-file coverage в любом корпусе.
> Правки: notebook-study сверяет `chunk.doc_name`/source metadata с target file по нормализованному
> full-path reference; basename-only совпадение запрещено. Mismatched chunks исключаются из evidence,
> становятся явным gap, а research guide показывает source-identity diagnostics и coverage реальных
> file groups. Ни reindex, ни OCR, ни parse, ни deploy не запускались.
> Проверки: focused notebook/dataset/evidence/chat/version suite `90 passed`; `make verify` green
> (`2738 tests collected`). Попытка `make ship` не дошла до deploy: profile pytest оставил
> незавершившиеся процессы, а отдельно запущенный L1 smoke завис на chat path >70s. Оба прогона
> остановлены вручную; runtime намеренно остаётся `0.24.0.343`, пока smoke не даст честный результат.

> 0.24.0.349 — bounded live smoke
>
> Дата: 2026-07-10
> Статус: dev only, runtime не обновлялся.
> Причина: live smoke наследовал общий HTTP timeout 120s для каждого chat check и мог оставлять
> ship-gate без диагностического результата. Это скрывало runtime problem вместо честного fail/warn.
> Правки: smoke получил отдельный configurable `--chat-timeout` (45s default) и более короткий
> обычный HTTP timeout; chat timeout остаётся результатом smoke и не переводится в success.
> Проверки: focused `96 passed`; `make verify` green (`2739 tests collected`); live smoke с
> `--chat-timeout 15` — `9/9 pass` (glossary 6ms, broad no-scope chat 3929ms). Runtime ещё не
> обновлялся этой версией.

> 0.24.0.350 — integrity-first RAG core
>
> Дата: 2026-07-10
> Статус: dev only; runtime и индекс не изменялись.
> Причина: повторный аудит обнаружил, что `/api/rag/retrieve-debug` дописывал ожидаемые FIRE/HVAC
> термины в имена/preview. Прежний debug-based `16/16` и остальные такие отчёты аннулированы.
> Правки: debug точно отражает chunks; индекс получил versioned manifest и fail-closed dense guard;
> все parser outputs проходят общий tokenizer-budget и mixed-base64 gate. Retrieval различает
> dense/RRF/rerank шкалы, retry сохраняет backend, reranker пишет score/rank, quality считается
> после него. Evidence assembler сохраняет source diversity/table header; tool loop стал bounded
> research loop до трёх раундов; ответ получает citation-integrity check.
> Проверки: объединённый RAG/chat focused gate `210 passed`; обязательный `make test-rag-core`
> `151 passed`; `make verify` green (`2751 collected`). Первый full run: `2733 passed / 16 failed`;
> 14 stale unified-final tests исправлены и затем прошли focused `81 passed`; остаются 2 известных
> сметных finality failure вне RAG-core. Reindex/OCR/parse и deploy не запускались.

> 0.24.0.351 — contract-clean Qwen sibling canary
>
> Дата: 2026-07-10
> Статус: dev + отдельная canary-коллекция; production collection не переключена.
> Причина: активная `les_rag_qwen3_06b_native_v1` содержит пять несовместимых embedding
> fingerprints и не может получить новый manifest задним числом. Полный синхронный re-embed
> четырёх корпусов занял бы 1–2 часа и мешал бы живому MLX-чату.
> Правки: `tools/build_rag_contract_sibling.py` читает только payload старой коллекции,
> прогоняет текст через общий sanitation/token-budget gate, заново получает Qwen vectors,
> строит native dense+sparse points с детерминированными id и migration provenance. Источник,
> MetaDB и исходные vectors не меняются; повторный запуск идемпотентен. Обязательный
> `test-rag-core` включает тесты resolver/id contract мигратора.
> Приёмка: dry-run точно разрешил BAI, `ПД_Инновационный центр`, `NTD_FIRE_Index` и
> `TABLE_SMETA_Index`; 4×4 initial canary создал 19 clean points и manifest fingerprint
> `33507479e43bd3ba8afc3b3bfeb86ad8033c7e1b3912d92a6a894b8ae288cb3c`.
> Расширенный bounded canary: по 256 source points каждого корпуса дали BAI `397`, ПД ИЦ `297`,
> FIRE `278`, TABLE_SMETA `310` clean points; destination total `1282`. Sample audit:
> `1000/1000` один Qwen/Core ML fingerprint, token-budget и sanitation metadata, manifest
> compatible. Прямой filtered dense retrieval вернул по `3/3` chunks для всех четырёх scopes.
> TABLE_SMETA при этом признан смешанным: 3 реальные ВОР + test table, norms, price cards и
> service files в одном scope; classifier попал в top-3. Production не переключать, пока
> canary не покрывает требуемый scope и TABLE_SMETA не разделён по назначению.
> Проверки кода: `make test-rag-core` — `154 passed`; `make verify` — `2754 collected`;
> `uv lock --check` и `git diff --check` green.

> 0.24.0.352 — module-owned system datasets + test corpus removal
>
> Дата: 2026-07-10
> Статус: runtime `0.24.0.352`; system dataset зарегистрирован без parse.
> Причина: аудит `TABLE_SMETA_Index` показал, что 3 ВОР и CSV — пользовательские тесты, а
> остальные документы — generated module cards. Смешение project/table и module navigation
> делало classifier конкурентом factual retrieval.
> Правки: MetaDB `datasets` получил `dataset_scope`/`module_id`; registry типизирует
> `SMETA_SERVICE_Index`, `SMETA_RU_NORM_*` и `GESN_NORMS_2022_PDF` как `system/smeta`.
> Scope показывает их отдельно, smeta-turn добавляет только свои system dataset ids, а router
> направляет `SMETA_SERVICE/**` в `SMETA_SERVICE_Index`. Dataset deletion теперь чистит Qdrant,
> FTS, structured rules и project links. Pricing gaps отделены в `pricing_status` и остаются
> row-level: они не превращают завершённый состав/количества в global stop.
> Runtime cleanup: `TABLE_SMETA_Index` удалён — active Qdrant `690→0`, canary `310→0`,
> FTS `690`, MetaDB documents `103`, dataset row `1`, storage dir; ГЭСН/ФГИС sources сохранены.
> `SMETA_SERVICE_Index` создан как `system/smeta`: зарегистрировано `98` generated service files,
> parse не запускался до совместимого production index contract. `/api/scope/options` показывает
> датасет отдельно от проектов и пользовательских корпусов.
> Canary после cleanup: BAI/ПД ИЦ/FIRE `397/297/278`, total `972`; audit `972/972` compatible.
> Focused system/router/delete/smeta suite: `204 passed`; `make test-rag-core` — `157 passed`;
> `make verify` — `2760 collected`; lock/diff checks green. `make ship` green; pre-deploy smoke
> честно зафиксировал один P1 `45s ReadTimeout`, после рестарта post-deploy smoke — `9/9` green,
> включая broad-chat probe `728ms`.

> 0.24.0.346 — Qwen query embedding contract
>
> Дата: 2026-07-10
> Статус: dev only, runtime не обновлялся.
> Причина: Qwen3-Embedding supports query-side instructions, but the existing Qwen collection
> stores raw document vectors. Prefixing queries without a visible contract would make retrieval
> non-reproducible and tempt an unmeasured production change.
> Правки: `raw-v1` remains default; opt-in `qwen-retrieval-v1` formats only dense queries as
> `Instruct ... / Query ...`, documents remain raw. Runtime config and `RetrievalTrace` expose
> the instruction id; dense/sparse model mismatch safety is unchanged. No reindex/OCR/parse.
> Проверки: focused Qwen config/embed/retrieval/evidence/notebook suite `65 passed`, один
> известный независимый `test_retrieve_chat_chunks_promotes_exact_source_after_rerank` trace
> regression исключён из focused run; `make verify` green (`2734 tests collected`).
> Live CoreML embedding probe: raw documents против трёх русских query pairs (security/HVAC/table)
> дали correct top-1 `3/3` и в `raw-v1`, и с Qwen instruction. Similarity целевого источника
> выросла для security `0.5397→0.6018` и HVAC `0.6578→0.6879`, для table слегка снизилась
> `0.5712→0.5634`; это smoke механизма, не corpus A/B verdict.

> 0.24.0.343 — scattered low-score honesty gate
>
> Дата: 2026-07-10
> Статус: deployed to runtime.
> Причина: BAI canary exposed a retrieval result with no expected work-volume source, yet
> `quality_status=good`: low-score neighbours happened to cover some lexical terms. This is a
> false confidence problem in the common RAG core, not a BAI-specific answer rule.
> Правка: `retrieval_quality_service` returns `weak/low_score_scattered_sources` when the best
> candidate is below `0.42` and the pool spans four or more documents. Model-first generation
> continues; `EvidencePacket.evidence_status` becomes `partial`, so UI/trace cannot call such a
> result complete evidence. Regression tests cover weak scatter and a high-score hybrid control.
> Проверки: targeted 121 passed (quality/evidence/source-map/chat/version); `make verify`
> (`2727 tests collected`); selective runtime probe returns `0.24.0.343`, deploy stamp `ok`,
> BAI failure is now `quality_status=weak`, and a normal BAI chat returns
> `les.evidence_packet.v1` with a separate navigation boundary. No reindex/OCR/parse/embedding
> change. Full `make test` was stopped after it stalled on an outbound HTTPS test; its result is
> not claimed. An existing independent retrieval regression remains:
> `test_retrieve_chat_chunks_promotes_exact_source_after_rerank` lacks expected `trace.exact_refs`.

> 0.24.0.342 — common evidence packet for normal RAG
>
> Дата: 2026-07-10
> Статус: deployed to runtime; superseded by `0.24.0.343` only for scattered low-score status.
> Причина: source map, retrieved context, navigation and retrieval trace existed as independent
> surfaces. The model could cite `Источник N`, but no explicit common contract proved which
> retrieved material it saw or prevented navigation from being presented as evidence.
> Правка: `proxy/services/evidence_packet_service.py` adds `les.evidence_packet.v1` above
> already selected/context-expanded chunks. The model renderer and response `source_map` share
> exact source numbering; payload exposes source locator, retrieval quality, separate navigation
> (`is_evidence=false`), deterministic inventory facts, `evidence_status`, and distinct
> answer/calculation status. `retrieval_trace.evidence_packet` is compact enough for history.
> BAI receives a four-case no-LLM retrieval canary in `golden/bai_evidence_core_set.json`; no
> parse, OCR, reindex, embedding or collection change is part of the release.
> Проверки: focused evidence/chat/source-map/golden/version tests; `make verify`; BAI live canary
> after selective deploy. Initial BAI canary is 3/4: architecture work-volume query retrieves
> low-score neighbouring documents rather than the expected table. The release therefore adds a
> generic `weak/low_score_scattered_sources` quality state; it is not an index repair.

> 0.24.0.341 — read-only priority corpus inventory
>
> Дата: 2026-07-10
> Статус: deployed to runtime.
> Причина: общий runtime health показывал только агрегат `PENDING/ERROR`; нельзя было
> объективно выбрать первый evidence-core датасет и отличить незакрытую очередь от служебной
> записи без прямого чтения внутренних БД или ручной археологии.
> Правка: `tools/priority_corpus_inventory.py` строит `priority_corpus_inventory_v1` и
> generated `docs/EVIDENCE_CORE_PRIORITY_INVENTORY.md` исключительно из operator API:
> `/api/health`, Document Explorer и Dataset Notebook. Карточка несёт revision/reader/maps,
> statuses/types/chunks, pending/error/zero-chunk samples и operator disposition; она всегда
> `navigation`, не evidence, не читает SQLite/Qdrant напрямую, не запускает parse/OCR/reindex
> и не делает automatic quarantine. Service maps/state исключаются из zero-chunk defect,
> а duplicate pending basenames и dataset-status drift видны явно.
> Первый снимок выбрал BAI как index-quality canary; Fire остаётся golden, ПД ИЦ ждёт triage
> 49 pending и stale `ERROR`, сметная нормативка — решения по двум одинаково названным pending XLSX.
> Проверки: targeted 60 passed (`priority_corpus_inventory`, Document Explorer, dataset memory,
> version service); `make verify` (`2698 tests collected`); `git diff --check`.
> Runtime: `/api/version` = `0.24.0.341`, deploy stamp `ok`, runtime alignment `aligned`;
> runtime-clone probe построил BAI card с `baseline_candidate` и исключил service state из
> zero-chunk defect. Ни parse, ни OCR, ни reindex не запускались.

> 0.24.0.340 — notebook research guide
>
> Дата: 2026-07-10
> Статус: deployed to runtime.
> Причина: notebook-study уже строил хороший план и добирал источники, но оператор не видел
> revision/source-map выбранной области, фактическое покрытие маршрута чтения и следующие
> source-grounded шаги. Это затрудняло отличить «блокнот подготовлен» от «по нему уже читали».
> Правка: `notebook_research_guide_v1` выводится в `notebook_context` и markdown artifact:
> revision/source-map/reader status, coverage плановых разделов и точечных файлов, стартовые
> источники и вопросы продолжения. Guide вычисляется только из карты и результатов текущего
> retrieval, не создаёт нового индекса/LLM-вызова и строго помечен
> `context_role=navigation`, `is_evidence=false`; `ready` означает полноту текущего маршрута,
> не полноту проекта.
> Проверки: targeted 33 passed (`notebook_study`, chat policy, Sovushka visibility,
> dataset memory); `make verify` (`2692 tests collected`); `make ship-check` green.
> Runtime: `/api/version` = `0.24.0.340`, deploy stamp `ok`, runtime alignment `aligned`;
> direct runtime probe подтвердил `notebook_research_guide_v1`, navigation-only contract и
> model reader-pass/revision flags.

> 0.24.0.339 — smeta resource identity and honest finality
>
> Дата: 2026-07-09
> Статус: deployed to runtime.
> Причина: audit воспроизвёл завышение позиции `ГЭСНм38-01-001-01`: старая SQLite-база содержала
> семантические дубли ресурсов, а harness мог назвать итог `final_total`, хотя уже вернул
> `needs_kac`/отсутствующую ресурсную цену.
> Правка: unified Parquet, structured SQLite builder и runtime reader используют консервативный
> resource identity: код ресурса (либо нормализованное имя без кода), единица, расход и явная цена.
> Число схлопнутых строк идёт в audit/manifest; guard чинит уже собранную базу при чтении без
> мутирующего rebuild. `price_requirements` оставляют строку, trace и частичную сумму видимыми,
> но переводят статус в `partial` и не создают `final_total`; partial artifact отдельно называет
> ценовой добор и не подменяет его нулевой ценой.
> Проверки: targeted 7/7: source/structured/runtime identity guards, live-base ГЭСНм38 control,
> два end-to-end harness finality cases и partial artifact; `make verify` (`2692 tests collected`).
> Live `/api/lsr/assemble` для `ГЭСНм38-01-001-01 @ 664.71112` вернул 110519705.74 ₽
> (НР 37258263.86, СП 18629131.93), не старое завышение. Один ресурс без цены остался
> `needs_price=1` и потому не даёт finality. Полный focused smeta set был
> остановлен из-за зависания в существующем тяжёлом наборе после 23%; результат полного прогона
> не заявляется.

> 0.24.0.338 — explicit norm-reference promotion
>
> Дата: 2026-07-09
> Статус: deployed to runtime.
> Причина: после выравнивания Qwen/CoreML live FIRE/HVAC golden выявил реальный дефект:
> для запроса `Найди пункт 7.3 в СП 7.13130` документ СП попадал в кандидатный пул, но
> reranker оставлял его на 7–8 месте после документов, которые лишь ссылаются на СП.
> Правка: generic extracted СП/ГОСТ ref поднимает уже найденный файл самой нормы над
> документами-цитатами до и после rerank; trace получает `norm_ref_exact`. Это не lookup
> вне пула и не hardcoded fire rule.
> Проверки: focused `53 passed` (`test_retrieval_service`, `test_rag_golden_set`,
> `test_mlx_host_embeddings`, `test_qdrant_adapter_parse`); `make verify` (`2689 tests collected`);
> live FIRE/HVAC golden `16/16`; `git diff --check`. Full `make test` был остановлен на 67%:
> до остановки обнаружен ранее известный независимый failure `test_lsr_assembly_service` по НР/СП.
>
> 0.24.0.337 — retrieval embedding-contract gate
>
> Дата: 2026-07-09
> Статус: deployed to runtime.
> Причина: live audit выявил, что active Qwen-коллекция могла получать query-вектор от
> BGE-M3: MLX endpoint принимал имя модели в запросе, но возвращал вектора глобального
> embedder и эхо requested model. При одинаковой размерности это давало тихий неверный dense
> поиск. Cross-encoder reranker одновременно получал `top_k=len(pool)` и был no-op.
> Правка: `/v1/embeddings` публикует фактические `embedding_model`/backend; клиент сверяет
> контракт до использования вектора. Mismatch или старый endpoint выключает dense/sparse,
> оставляет только lexical retrieval и пишет `mode=lexical_only`,
> `fallback_reason=embedding_contract_mismatch`, `quality=degraded`. Reranker получает
> `RAG_CHAT_RERANK_TOP_K`, меньший входного пула. Критичный deploy bundle теперь включает
> MLX host, embedding interface и retrieval-quality service; `deploy_to_runtime --restart` также
> перезапускает MLX host при изменении `mlx_host.py`, а не только proxy/UI.
> `les_runtime_control restart` при реально изменённом/force-rendered plist делает
> `bootout → bootstrap`: один `kickstart` не перечитывает новые `EnvironmentVariables`.
> Проверки: targeted `73 passed`; `make verify` (`2685 tests collected`); isolated Qwen/CoreML
> probe → 1024d L2-normalized vector. Runtime MLX reloaded through force-rendered plist as
> Qwen/CoreML, live embedding contract confirmed, and direct dense Qdrant query succeeded.
>
> 0.24.0.336 — smeta compact norm-choice payload
>
> Дата: 2026-07-09
> Статус: deployed to runtime.
> Причина: audit БАП показал, что проблема не в 2 строках батча, а в
> размере payload: current compact при 20 candidates на 2 строки даёт около
> 47k JSON chars только candidates; local 9B тонет до выбора норм.
> Правка: local default `LES_SMETA_NORM_CHOICE_CANDIDATES` уменьшен до 5
> candidates на строку (cloud default 8, env override сохранён), `norm_card`
> сжат до коротких `domain/work_steps/conditions/resources/collection`, а
> `[SMETA_NORM_CHOICE]` пишет rows/candidates/prompt_chars/prompt_est_tokens.
> Код не выбирает нормы: он только уменьшает меню для model-owned выбора.
> Проверки: `uv run pytest -q tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_local_default_limits_candidates tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_batches_local_lookup_rows tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_validates_model_code_from_lookup tests/test_chat_harness_format.py::test_smeta_structured_norm_review_keeps_model_chosen_analog`; `python3 -m py_compile proxy/routers/chat.py proxy/services/version_service.py`; `git diff --check`; `make verify`.
>
> 0.24.0.335 — smeta pre-batch SSE/log visibility
>
> Дата: 2026-07-09
> Статус: deployed to runtime.
> Причина: live БАП на `0.24.0.334` показал, что `smeta_batch` работает, но
> первые 164.6 с до первого batch event всё ещё были непрозрачными; это
> оказался участок workflow/norm-lookup до structured norm-choice.
> Правка: `/api/chat/stream` отдаёт `smeta_step` для крупных стадий сметного
> маршрута (`rag_context`, `workflow`, `norm_lookup`, `norm_choice`,
> `final_answer`), backend пишет `[SMETA_STEP]`, Совушка показывает этап в
> пузыре и пишет его в операторский лог. Это не меняет выбор норм: модель
> выбирает, код только трассирует этапы и считает.
> Проверки: `python3 -m py_compile proxy/routers/chat.py sovushka/pages/chat.py proxy/services/version_service.py`; `uv run pytest -q tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_batches_local_lookup_rows tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_validates_model_code_from_lookup tests/test_chat_harness_format.py::test_smeta_structured_norm_review_keeps_model_chosen_analog`; `git diff --check`; `make verify`.
>
> 0.24.0.334 — smeta batch SSE/log visibility
>
> Дата: 2026-07-09
> Статус: deployed to runtime.
> Причина: local БАП/СКС через `/api/chat/stream` слишком долго молчали на
> тяжёлом structured norm-choice: оператор не видел, на каком диапазоне строк
> модель зависла и сколько строк принято/ушло в добор.
> Правка: `_smeta_direct_structured_norm_choice` отдаёт start/done каждого
> batch как SSE `smeta_batch`, пишет `[SMETA_BATCH]` в backend log, а Совушка
> показывает текущий диапазон строк и пишет батчи в операторский лог. Если
> batch не вернул строк, строки не теряются: они идут дальше как `нужен подбор
> нормы` с причиной, без кодового выбора нормы.
> Проверки: `uv run pytest -q tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_batches_local_lookup_rows tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_validates_model_code_from_lookup tests/test_chat_harness_format.py::test_smeta_structured_norm_review_keeps_model_chosen_analog`; `python3 -m py_compile proxy/routers/chat.py proxy/services/version_service.py sovushka/pages/chat.py`; `git diff --check`; `make verify`.
>
> 0.24.0.333 — smeta smaller local norm-choice batches
>
> Дата: 2026-07-09
> Статус: code, not deployed.
> Причина: live БАП на `0.24.0.332` подтвердил, что batching включился, но
> batch size 5 всё ещё слишком тяжёлый для локального MLX с текущими norm-card
> payload: final payload не пришёл, MLX снова ушёл в memory pressure/main model
> busy. Лог: `tmp/smeta_local_0_24_0_332/bap_batched_log.md`.
> Правка: local default `LES_SMETA_NORM_CHOICE_BATCH_SIZE` уменьшен до 2, а
> `max_tokens` selector-а внутри батча считается от строк текущего батча, не от
> всей ВОР. Если машина тянет, оператор может вернуть 5 явным env override.
> Проверки: pending.
>
> 0.24.0.332 — smeta batched local norm-choice
>
> Дата: 2026-07-09
> Статус: code, not deployed.
> Причина: live БАП на локальном `0.24.0.331` дважды не вернул final payload:
> SSE показывал только 4 progress events, а затем монолитный local smeta step
> зависал дольше 10 минут; в первом прогоне MLX ушёл в memory pressure, во
> втором после restart генерация всё равно не дошла до final trace. Поэтому
> “куда модель смотрит” не было видно до конца запроса.
> Правка: structured norm-choice/review для локального MLX режет `lookup_results`
> батчами по 5 строк (`LES_SMETA_NORM_CHOICE_BATCH_SIZE`, default 5 для local,
> 0 для cloud). Каждый батч выбирает нормы моделью только из своих candidates,
> review идёт на том же батче, затем код склеивает строки обратно с глобальными
> `lookup_index` и отдаёт batch trace. Код по-прежнему не выбирает нормы.
> Проверки: pending.
>
> 0.24.0.331 — smeta local-by-default model runtime
>
> Дата: 2026-07-09
> Статус: deployed to runtime.
> Причина: СКС smoke не был честным тестом локальной модели: structured
> norm-choice ушёл в global cloud runtime из-за доступного API key и упал на
> `402 Payment Required`. Локальный MLX endpoint при этом жив: `/v1/models`
> показывает `Qwen3.5-9B-MLX-4bit`, короткая генерация ответила за 33.7 с.
> Правка: smeta model-owned steps (`LES_SMETA_DIRECT_MODEL_PROVIDER`,
> `LES_SMETA_NORM_CHOICE_PROVIDER` и общий `LES_SMETA_PROVIDER`) теперь по
> умолчанию используют локальный MLX. Cloud остаётся доступен только через явный
> smeta provider override; наличие глобального cloud key больше не меняет смету
> молча. Это не меняет правило выбора норм: модель выбирает, код считает и
> проверяет provenance/арифметику.
> Проверки: focused `tests/test_chat_harness_format.py` passed; `py_compile` +
> `git diff --check` → ok; `make verify` → ok (`2676 tests collected`);
> `make ship` → verify ok, focused `193 passed`, basic/post smoke accepted by
> ship with `8/9` pass and non-blocking P1 `chat_project_noscope` timeout.
> Initial ship deploy skipped divergent runtime files after writing deploy stamp,
> then runtime-critical files were synchronized with explicit force deploy.
>
> 0.24.0.330 — smeta protective-cover + fastener candidates
>
> Дата: 2026-07-09
> Статус: deployed to runtime.
> Причина: fresh БАП 0.24.0.329 оставил 3 нуля. Два из них были не отсутствием
> базы, а плохой model-facing картой candidates: временное защитное укрытие
> полиэтиленовой плёнкой резалось глобальным forbidden-якорем `защитн`, а
> строка скоб приходила от модели как `pipe` и показывала трубы/светильники
> вместо штучных крепёжных конструкций.
> Правки: `protective_cover` получил отдельные applicability/score anchors для
> временного укрытия/ограждения, не поднимая декоративную ПВХ-плёнку и натяжные
> потолки; `electric pipe + шт + скобы/крепление` маршрутизируется как
> `fastener`, а светильники/изоляторы штрафуются в fastener-route. Код не
> выбирает норму: он показывает модели правильные candidates и оставляет
> selector/review владельцами выбора.
> Проверки: focused regression `4 passed`; `py_compile` + `git diff --check` → ok.
> Runtime `/api/version` → `0.24.0.330`, deploy stamp ok,
> `runtime_alignment=aligned`. Fresh БАП через `/api/chat/stream`: HTTP 200
> за 131.6 с, lookup `19/19`, review `approved=0`, `replaced=18`,
> `unbound=1`, visible ЛСР `18/19`, сумма `1 471 554 руб.`. Строка 1
> рассчитана через `ГЭСН46-05-001-03`, строка 18 — через
> `ГЭСНм08-02-152-13`; единственный ноль остался по строке 3
> “Разработка проема в потолке из ГКЛ...” из-за отсутствия точной штучной
> нормы/размера для перевода в м2. Ответ сохранён:
> `tmp/bap_fresh_test/0_24_0_330_cloud_body.json`.
>
> 0.24.0.329 — smeta source-row display contract
>
> Дата: 2026-07-09
> Статус: deployed to runtime.
> Причина: fresh БАП на 0.24.0.328 подтвердил, что lookup coverage полный
> (`19/19`) и строка 5 начала считаться через ремонтный `ГЭСНр63`, но visible
> ЛСР всё ещё могла показывать title выбранной/отклонённой карточки нормы
> вместо исходной строки ВОР. Draft norm-choice уже сохранял source title, но
> второй model-owned review (`approve|replace|unbound`) перетирал его своим
> `title`.
> Правки: direct selector и review audit теперь для всех строк с
> `work_description` сохраняют в видимой ЛСР исходное название/единицу ВОР;
> chosen/replaced norm_code остаётся в `Обоснование`, а карточка нормы/состав
> работ остаются в evidence. Это display/provenance contract, не выбор нормы
> кодом.
> Проверки: focused regression `4 passed`; `py_compile` + `git diff --check` → ok;
> `make verify` → ok (`2674 tests collected`). Runtime `/api/version` →
> `0.24.0.329`, deploy stamp ok, `runtime_alignment=aligned`. Fresh БАП
> через `/api/chat/stream`: HTTP 200 за 105.4 с, lookup `19/19`,
> review `approved=8`, `replaced=8`, `unbound=3`, visible ЛСР `16/19`,
> сумма `1 152 416 руб.`; строки 1/3/18 остались нулевыми с исходными
> названиями ВОР. Ответ сохранён:
> `tmp/bap_fresh_test/0_24_0_329_cloud_body.json`.
>
> 0.24.0.328 — smeta surface-prep visibility + rejected-row provenance
>
> Дата: 2026-07-09
> Статус: deployed to runtime.
> Причина: БАП после 0.24.0.327 уже не пропускал rejected/unit-mismatch
> карточки в деньги, но две вещи искажали результат для оператора: строка
> “подготовка поверхности потолка ... после монтажа лючков” уходила в hatch
> lookup из-за слова “лючков” и не показывала модели ремонтные `ГЭСНр63`, а
> rejected-норма могла подменить в нулевой строке ЛСР исходное название ВОР.
> Это выглядело как “код/SQL душит модель”, хотя SQL/parquet не был главным
> узлом: lookup cold может занимать секунды, но повторный cached lookup быстрее,
> а live БАП в основном тратит время на модельный выбор/review и РИМ trace.
> Правки: `search_norm` для generic finish теперь маршрутизирует подготовку/
> ремонт потолочной поверхности в ceiling/repair до hatch-route; structured
> norm-choice при rejected/unit-mismatch сохраняет в видимой нулевой строке
> исходное описание/единицу ВОР и пишет машинную причину (`candidate_rejected_by_lookup`
> или `candidate_unit_mismatch_by_lookup`). Код по-прежнему не выбирает норму:
> он только не даёт отвергнутой карточке стать суммой и не теряет исходную строку.
> Проверки: focused regression `2 passed`; `py_compile` + `git diff --check` → ok;
> runtime `/api/version` → `0.24.0.328`, deploy stamp ok,
> `runtime_alignment=aligned`; fresh БАП rerun saved under `tmp/bap_fresh_test/`.
>
> 0.24.0.327 — smeta rejected-candidate gate
>
> Дата: 2026-07-09
> Статус: deployed to runtime.
> Причина: fresh БАП после 0.24.0.326 стал 16/19 и 1 403 680 руб.,
> но строка 1 всё ещё попала в расчёт через `ГЭСН46-05-001-03`, хотя сам
> `search_norm` уже пометил этот candidate как `applicability_status=rejected`.
> Правки: structured norm-choice теперь разрешает к расчёту только candidates,
> которые были видимы модели и не имеют `applicability_status=rejected` и
> `unit_compatible=false`. Это не выбор нормы кодом: код остаётся provenance/
> validity gate и не даёт заведомо отвергнутой карточке превратиться в деньги.
> Проверки: focused smeta gate с rejected-candidate регрессией → `9 passed`;
> `py_compile` + `git diff --check` по затронутым файлам → ok. Runtime:
> `/api/version` → `0.24.0.327`, deploy stamp ok,
> `runtime_alignment=aligned`; fresh БАП cloud rerun pending in this session.
>
> 0.24.0.326 — smeta BAP false-analog guard
>
> Дата: 2026-07-09
> Статус: deployed to runtime.
> Причина: fresh БАП после 0.24.0.325 поднялся до 17/19 строк, но итог
> раздулся до 2 697 674 руб. из-за ложных слабых аналогов: временное защитное
> укрытие плёнкой было посчитано декоративной ПВХ-плёнкой, а ГКЛ-проём под
> ревизионный люк — люком на крыше. Монтаж ревизионного лючка из-за слов
> “под покраску” уходил в окраску, а не в люки.
> Правки: `search_norm` для `finish/hatch` теперь маршрутизирует `люк/люч/ревизион`
> раньше окраски и поднимает `ГЭСН17-01-010-*`; защитное укрытие плёнкой
> штрафует декоративную/самоклеящуюся ПВХ-плёнку, натяжные потолки и отделочные
> операции; prompt/review явно запрещает крыши/фасады/оконные и дверные проёмы
> как аналоги ГКЛ-проёма и декоративную плёнку как аналог временного укрытия.
> Проверки: `uv run pytest tests/test_chat_harness_format.py::test_smeta_direct_norm_lookup_is_model_selected
> tests/test_chat_harness_format.py::test_smeta_norm_lookup_prompt_keeps_deeper_candidate_window
> tests/test_chat_harness_format.py::test_smeta_structured_norm_review_keeps_model_chosen_analog
> tests/test_chat_harness_format.py::test_smeta_structured_norm_review_can_replace_empty_finish_draft
> tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_gets_norm_card_and_mismatch_rule
> tests/test_estimate_harness.py::test_search_norm_routes_revision_hatch_to_gesn17
> tests/test_estimate_harness.py::test_search_norm_routes_hidden_hatch_even_when_under_painting
> tests/test_estimate_harness.py::test_search_norm_routes_reed_ceiling_demolition_to_repair_collection -q` → `8 passed`;
> `py_compile` + `git diff --check` по затронутым файлам → ok. Runtime:
> `/api/version` → `0.24.0.326`, deploy stamp ok,
> `runtime_alignment=aligned`; fresh БАП cloud rerun pending in this session.
>
> 0.24.0.325 — smeta BAP norm-candidate visibility + review boundary
>
> Дата: 2026-07-09
> Статус: deployed to runtime.
> Причина: fresh БАП ЛСР на облачной модели принимал 19 строк ВОР, но priced-часть
> собиралась только 12/19; review-промпт содержал скрытый стоп-кран `unbound`
> для демонтажа/неточных строк, а `search_norm` показывал модели слишком узкое
> окно candidates и не доводил до ремонтных `ГЭСНр63`/ревизионных люков.
> Правки: дефолт norm lookup расширен до 25 найденных и 20 model-visible
> candidates; structured choice/review получают больше токенов; review boundary
> заменён на сметческий аналог из candidates вместо `unbound` по умолчанию;
> `search_norm` поднимает ремонтные потолки `ГЭСНр63`, ревизионные люки
> `ГЭСН17-01-010-*`, защитную плёнку не разрешает закрывать штукатуркой/
> грунтовкой/окраской. Код по-прежнему не выбирает норму: он приносит карточки,
> проверяет provenance выбранного моделью шифра и считает арифметику.
> Проверки: `uv run pytest tests/test_chat_harness_format.py::test_smeta_direct_norm_lookup_is_model_selected
> tests/test_chat_harness_format.py::test_smeta_norm_lookup_prompt_keeps_deeper_candidate_window
> tests/test_chat_harness_format.py::test_smeta_structured_norm_review_keeps_model_chosen_analog
> tests/test_chat_harness_format.py::test_smeta_structured_norm_review_can_replace_empty_finish_draft -q` → `4 passed`;
> `uv run pytest tests/test_estimate_harness.py::test_search_norm_routes_revision_hatch_to_gesn17
> tests/test_estimate_harness.py::test_search_norm_routes_reed_ceiling_demolition_to_repair_collection -q` → `2 passed`.
> Runtime: `/api/version` → `0.24.0.325`, deploy stamp ok,
> `runtime_alignment=aligned`; fresh БАП cloud rerun pending in this session.
>
> 0.24.0.324 — cloud provider model/key preservation
>
> Дата: 2026-07-09
> Статус: deployed to runtime.
> Причина: live `.env` оказался обрезан до `MLX_MODEL`/`LLM_MODEL`; cloud
> provider снова показывал fallback `gpt-4.1` и `api_key_set=false`, хотя
> оператор вводил ключ и модель 5.4. Старый дефолт `gpt-4.1` всплывал из
> settings/chat/runtime fallback и мог перезаписываться UI при сохранении.
> Правки: OpenAI-compatible fallback model в settings/chat/runtime/service
> точках обновлён до `gpt-5.4`; добавлена регрессия, что переключение MLX-модели
> не выбрасывает `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL`,
> `LES_LLM_PROVIDER`, `LES_CLOUD_CONSENT` из `.env`.
> Проверки: `uv run pytest tests/test_proxy_routers.py::test_save_settings_updates_provider_keys_without_exposing_secret
> tests/test_proxy_routers.py::test_set_mlx_model_preserves_cloud_provider_settings
> tests/test_proxy_routers.py::test_settings_openai_default_model_is_current
> tests/test_runtime_router.py::test_openai_provider_status_defaults_to_gpt_model
> tests/test_chat_harness_format.py::test_smeta_workflow_decision_routes_explicit_lsr_without_selector -q` → `5 passed`;
> `compileall` + `git diff --check` по затронутым файлам → ok. Runtime:
> `/api/settings` → active/effective `openai`, model `gpt-5.4-mini`,
> `api_key_set=true`, fallback `false`; `/api/version` → `0.24.0.324`,
> deploy stamp ok, `runtime_alignment=aligned`.
>
> 0.24.0.323 — macOS stale swap chat admission
>
> Дата: 2026-07-09
> Статус: deployed to runtime.
> Причина: fresh БАП smoke после `0.24.0.322` был заблокирован на входе
> `/api/chat` с HTTP 503: `ram_free_gb=4.8 < 8.0; swap_pct=75.8 > 60.0`.
> После штатного рестарта MLX RAM стала 18.6 GB free, но macOS сохранила
> 4.1 GB swap; старый допуск stale swap `2.0 GB` всё ещё блокировал чат,
> хотя давления памяти уже не было.
> Правки: дефолт `LES_CHAT_MAX_SWAP_USED_GB` поднят до `6.0`, добавлена
> регрессия на реальное состояние `18.6 GB free / 4.1 GB swap / 75.8% swap`.
> Проверки: pending.
>
> 0.24.0.322 — smeta explicit LSR route bypass
>
> Дата: 2026-07-09
> Статус: deployed to runtime.
> Причина: первый запрос вида «сделай оценку стоимости и ЛСР по ВОР» зависал на
> локальном smeta workflow-selector до таймаута и возвращал пустой workflow stage,
> хотя это буквальная команда на pricing-этап. Это ломало fresh БАП smoke до
> подбора норм/расчёта.
> Правки: `_smeta_direct_workflow_decision()` теперь без selector отправляет
> явные запросы ЛСР/стоимости/«деньги по ним» в `pricing`. Это только
> маршрутизация этапа; выбор норм/аналогов и применимости остаётся за моделью,
> код занимается lookup/provenance/арифметикой.
> Проверки: pending.
>
> 0.24.0.321 — smeta base pipeline
>
> Дата: 2026-07-09
> Статус: deployed to runtime.
> Причина: после перехода runtime на structured SQLite нужно, чтобы ФГИС-update
> не останавливался на unified parquet и не оставлял машинную базу/RAG-карты
> устаревшими.
> Правки: `tools/gesn_update_from_fgis.py` теперь ведёт полный pipeline
> `ФГИС/raw → unified parquet → structured SQLite → SMETA_SERVICE cards`;
> добавлены CLI-флаги `--structured-out`, `--structured-manifest-out`,
> `--service-rag-out`, `--skip-structured`, `--skip-service-rag`.
> `gesn_update_service.status()` показывает unified/audit/structured/manifest/
> service_rag слои. Make targets: `make smeta-base` (checked unified →
> SQLite → cards), `make smeta-base-source` (raw/cache → unified → SQLite →
> cards), `make smeta-base-update` (ФГИС → полный pipeline).
> Доп. правки перед деплоем: `estimate_harness_service` больше не переводит
> весь расчёт в `partial` только из-за `price_requirements`: ценовые gaps
> остаются row-level требованиями, а инженерные blockers (`needs_input`,
> rejected, `norm_questions`) по-прежнему блокируют `final_total`. Роутинг
> силового кабеля уточнён под новую structured base: запрос с `силовой кабель`
> поднимает нормы силового кабеля, а `накладные скобы` не получают бонус без
> явного признака крепления/скоб.
> Проверки: `uv run pytest tests/test_estimate_harness.py -q` → `94 passed`;
> focused deploy set `uv run pytest tests/test_sovushka_chat.py
> tests/test_static_assets.py tests/test_smeta_chat_service.py
> tests/test_estimate_harness.py tests/test_profile_resolver.py
> tests/test_doc_review_gost_21_101_2026.py tests/test_doc_review_chat_tool.py
> tests/test_title_block_extract.py tests/test_service_source_registry.py -x
> --tb=short -q` → `187 passed`; `make verify` → ok (`2664 tests collected`);
> `git diff --check` → ok. Runtime data copied manually:
> `data/gesn_base/gesn2022_unified.parquet` and
> `data/smeta_base/les_smeta_base.sqlite`. Deploy: `tools.deploy_to_runtime
> --apply --restart --force`, then explicit clean sync for
> `proxy/routers/runtime.py` and `sovushka/styles.py`; live `/api/version` →
> `0.24.0.321`, deploy stamp ok, `runtime_alignment=aligned`.
> Post-deploy smoke: `make post-deploy-smoke` → `8 pass`, `1 warn`,
> `0 fail`; warning is transient `chat_project_noscope memory-guard`.
>
> 0.24.0.320 — smeta structured machine base
>
> Дата: 2026-07-09
> Статус: dev only, не задеплоено.
> Причина: unified parquet был хорошим source/staging снимком, но runtime и модель
> видели слишком рыхлый слой: нормы и ресурсы были смешаны строками, пустые
> `norm_name`/`norm_unit` оставались в низовой базе, а exact lookup требовал
> загрузки parquet целиком.
> Правки: добавлен canonical SQLite `data/smeta_base/les_smeta_base.sqlite`
> (`norms` + `resources`) и manifest качества
> `data/smeta_base/les_smeta_base_manifest.json`; `tools/build_smeta_structured_base.py`
> собирает SQLite из `data/gesn_base/gesn2022_unified.parquet`, исключая нормы
> без имени/единицы вместо показа их машине. `gesn_service.load_base_norms()`
> без явного пути теперь читает structured SQLite first, parquet остаётся
> source/debug fallback и совместимостью тестов. Текущий снимок: source
> `773727` rows / `58886` norm_key; runtime base `47037` norms / `664597`
> resources; excluded `11849` norm_key with missing name/unit.
> Проверки: `uv run pytest tests/test_smeta_structured_base.py
> tests/test_gesn_unify_base.py tests/test_gesn_service.py
> tests/test_gesn_import.py::test_missing_base_falls_back_to_seed
> tests/test_smeta_norm_store.py::test_smeta_norm_store_demotes_legacy_untyped_and_hides_empty_norms
> tests/test_version_service_v19.py -q` → `33 passed`;
> `python3 -m compileall -q proxy/services/gesn_service.py
> proxy/services/version_service.py tools/build_smeta_structured_base.py
> tests/test_smeta_structured_base.py tests/test_gesn_unify_base.py` → ok;
> `git diff --check` по затронутым файлам → ok; `make verify` → ok
> (`2662 tests collected`). Smoke: `load_base_norms()` → `47037` norms,
> source_kind `structured_sqlite`; SQLite counts → `47037` norms / `664597`
> resources.
>
> 0.24.0.319 — smeta pricebook cleanup
>
> Дата: 2026-07-09
> Статус: dev only, не задеплоено.
> Причина: аудит сметной базы нашёл лишние/ошибочно названные книги цен,
> засорявшие `SMETA_SERVICE` и model-facing source map.
> Правки: добавлен `config/domain/pricebook_manifest.json` с canonical default
> `sankt-peterburg_2kv2026`, hidden stems и aliases для дублей; `fgis_price_service`
> скрывает duplicate/scratch books из обычного discovery, но explicit alias
> `spb_2kv2026` резолвит в canonical Санкт-Петербург. `tools/build_smeta_service_rag.py`
> перед пересборкой чистит только generated cards (`00_smeta_service_overview.md`,
> `collection_*.md`, `pricebook_*.md`) и пишет `SMETA_SERVICE` по visible-книгам.
> Из рабочей `data/price_base` в quarantine перенесены `spb_refresh.parquet`,
> `spb_2kv2026.parquet`, `omskaya-oblast_2kv2026.parquet`,
> `nizhegorodskaya-oblast_2kv2026.parquet`; рабочее discovery видит 85 книг.
> Проверки: `uv run pytest tests/test_fgis_price_service.py
> tests/test_smeta_artifact_service.py::test_smeta_artifact_uses_default_system_pricebook_without_region
> tests/test_smeta_artifact_service.py::test_smeta_artifact_prefers_full_spb_pricebook_over_refresh_without_period
> tests/test_service_source_registry.py tests/test_version_service_v19.py -q` →
> `36 passed`; `python3 -m compileall -q proxy/services/fgis_price_service.py
> proxy/services/version_service.py tools/build_smeta_service_rag.py` → ok;
> `git diff --check` по затронутым файлам → ok; `make verify` → ok
> (`2660 tests collected`). Smoke: `available_pricebooks()` → 85 visible books,
> default → `sankt-peterburg_2kv2026`; `SMETA_SERVICE` overview больше не
> содержит `spb_refresh`, `spb_2kv2026`, `omskaya-oblast_2kv2026`,
> `nizhegorodskaya-oblast_2kv2026`.
>
> 0.24.0.318 — L.I.S.T. dataset registry/kinds UI
>
> Дата: 2026-07-09
> Статус: dev only, не задеплоено отдельно от pending `0.24.0.316`/`0.24.0.317`.
> Правки: ручной тип датасета (`project`, `norm`, `estimate`, `catalog`,
> `cad_bim`, `correspondence`, `mixed`, `other`) сохраняется в
> `_les_dataset_profile.json`/`les_dataset_profiles`, отдаётся в
> `/api/documents/datasets` как поле сортировки и меняется через
> `PATCH /api/rag/datasets/{dataset_id}/profile/kind`. Совушка «Документы»
> получила фильтр датасетов по типу, control «Тип датасета», сворачиваемый
> верхний «Реестр файлов» по разделам/типам и порядок `реестр → карта`; штатный
> экран убрал diagnostic tool-harness controls и дублирующие кнопки карточек
> датасета.
> Проверки: `python3 -m compileall -q ...` по затронутым backend/UI/tests → ok;
> `uv run pytest tests/test_document_explorer_service.py
> tests/test_context_memory_service.py::test_dataset_kind_is_manual_navigation_metadata
> tests/test_notebook_api.py::test_dataset_kind_endpoint
> tests/test_static_assets.py::test_admin_documents_tab_is_mounted -q` →
> `13 passed`; `make verify` → ok (`2660 tests collected`).

> 0.24.0.317 — L.I.S.T. module naming
>
> Дата: 2026-07-09
> Статус: dev only, не задеплоено отдельно от pending `0.24.0.316`.
> Причина: выбран пользовательский нейминг слоя разбора документации:
> **Л.И.С.Т. · Локальный индекс структуры томов**.
> Правки: в Совушке «Документы» карта проекта, Mermaid-схема, подсказки и кнопка
> датасета называют слой `Л.И.С.Т.`; `MODULE_INDEX` и `CODE_MAP` закрепляют
> Л.И.С.Т. как пользовательское имя `project_pdf_extract` / project source-map
> слоя. Технические JSON/API контракты не переименовывались.
> Проверки: `python3 -m compileall -q sovushka/pages/documents.py
> tests/test_static_assets.py proxy/services/version_service.py` → ok;
> `uv run pytest tests/test_static_assets.py -q` → `7 passed`;
> `git diff --check` по затронутым файлам → ok. Deploy отдельно не выполнялся,
> чтобы не смешивать с pending `0.24.0.316` GESN bundle.

> 0.24.0.316 — GESN unified base and FGIS updater
>
> Дата: 2026-07-09
> Статус: dev only, не задеплоено.
> Причина: старые слои `gesn2022.parquet`/`gesn2022_v2.parquet` смешивали typed и untyped нормы; одинаковые bare-коды разных семейств (`ГЭСН:38-...` и `ГЭСНм:38-...`) должны жить в одной нормальной базе без схлопывания.
> Правки: добавлен tracked `data/gesn_base/gesn2022_unified.parquet` + `gesn2022_unified_audit.json`; `gesn_service` предпочитает unified-файл и оставляет legacy/v2 только fallback, если unified отсутствует. Старые parquet удалены из `data/gesn_base`; raw ФГИС/ручные импорты перенесены в `storage/cache/gesn_fgis/`. Добавлены `tools/gesn_unify_base.py`, `tools/gesn_update_from_fgis.py`, `gesn_update_service`, API `POST/GET /api/service-sources/gesn_base/fgis-update[/status]` и кнопка GUI «скачать/обновить из ФГИС ЦС» в «Инструменты → Источники данных». Старые launchd backfill labels остановлены.
> Проверки: `uv run pytest tests/test_gesn_unify_base.py
> tests/test_gesn_import.py::test_base_type_prevents_gesn_gesnm_collision
> tests/test_gesn_service.py tests/test_smeta_norm_store.py tests/test_static_assets.py -q`
> → `25 passed`; локальный smoke `load_base_norms=58886`, strict bare
> `38-01-001-01` → `None`, typed `ГЭСН38...`/`ГЭСНм38...` раскрываются отдельно;
> `python3 -m compileall -q` по изменённым GESN/API/UI файлам → ok;
> `git diff --check` по затронутым файлам → ok; `make verify` → ok
> (`2656 tests collected`); `uv run pytest tests/test_service_source_registry.py
> tests/test_proxy_routers.py tests/test_version_service_v19.py -q` → `41 passed`.

> 0.24.0.315 — Google/Yandex Drive web dataset intake
>
> Дата: 2026-07-09
> Статус: deployed to runtime точечно (`cloud_drive_service.py`,
> `datasets.py`, `external_radar_service.py`, `samovar.py`, `version_service.py`).
> Причина: оператору нужны папки Google Drive / Яндекс Диска как датасеты не
> через desktop-sync папку, а через web/API.
> Правки: добавлен `cloud_drive_service`: web-status провайдеров, list/sync для
> Google Drive и Яндекс Диска по env OAuth-токенам (`LES_GOOGLE_DRIVE_ACCESS_TOKEN`,
> `LES_YANDEX_DISK_TOKEN`), mirror-кэш `storage/cloud_drives/...`,
> экспорт Google Docs/Sheets/Slides в Office/PDF и последующая регистрация mirror
> через существующий in-place `index-external`. API: `GET /api/rag/cloud-drives`,
> `POST /api/rag/cloud-drives/list`, `POST /api/rag/cloud-drives/sync`. Самовар
> получил блок «Google / Яндекс через веб» в диалоге добавления датасета и
> статус web-дисков в External Radar. Локальные sync-папки Google/Yandex остаются
> fallback-путём в браузере папок.
> Проверки: `python3 -m compileall -q` по изменённым backend/UI/test файлам → ok;
> `uv run pytest tests/test_cloud_drive_service.py tests/test_static_assets.py
> tests/test_external_radar_service.py tests/test_datasets_router.py -q` →
> `58 passed`; `make verify` → ok (`2656 tests collected`); `git diff --check`
> по затронутым файлам → ok. Deploy tool copied 5 files and restarted
> `com.les.sovushka` + `me.ovc.les.proxy`; live `/api/version` →
> `0.24.0.315`, deploy stamp ok. Smoke: `GET /api/rag/cloud-drives` → providers
> visible, tokens not configured; `GET /api/external-radar/summary?limit=2` →
> `status=ok`, `cloud_local=1`; `POST /api/rag/cloud-drives/list` without Google
> token → HTTP `400` with `LES_GOOGLE_DRIVE_ACCESS_TOKEN` message; `GET /classic`
> → NiceGUI HTML (`144389` bytes).

> 0.24.0.314 — Documents dataset Mermaid structure
>
> Дата: 2026-07-09
> Статус: deployed to runtime точечно (`sovushka/pages/documents.py`,
> `version_service.py`).
> Причина: вкладка «Документы» должна показывать оператору красивую
> человекочитаемую структуру датасета, а не только длинный список файлов и
> диагностические рычаги.
> Правки: в «Карту проекта» добавлен нативный `ui.mermaid`-блок «Структура
> датасета»: датасет → проекты/папки → разделы → найденные сущности
> (`PDF`, таблицы, ПЗ, ВОР, СО, экспликации, водные балансы, ХВС) и отдельный
> узел «Что проверить» для проблемных PDF/неизвестных таблиц. Это остаётся
> обзорной навигацией для человека и модели, не evidence и не шаблон ответа.
> Проверки: `python3 -m compileall -q sovushka/pages/documents.py
> tests/test_static_assets.py proxy/services/version_service.py` → ok;
> `uv run pytest tests/test_static_assets.py -q` → `6 passed`;
> `make verify` → ok; `git diff --check` по затронутым файлам → ok.
> Deploy tool copied 2 files and restarted `com.les.sovushka` +
> `me.ovc.les.proxy`; live `/api/version` → `0.24.0.314`, deploy stamp ok;
> runtime_alignment остаётся `divergent` по файлам вне этого UI-bundle
> (`chat.py`, `runtime.py`, `document_explorer_service.py` и др.);
> `GET /classic` → NiceGUI HTML (`144389` bytes).

> 0.24.0.313 — final IC table semantic cleanup pass 2
>
> Дата: 2026-07-09
> Статус: deployed to runtime точечно (`project_pdf_table_service.py`,
> `project_pdf_extract_service.py`, `version_service.py`); ИЦ PDF extract
> rebuilt live.
> Причина: первый живой rebuild `0.24.0.312` нашёл больше таблиц, чем replay
> по старому sidecar (`5754` вместо `5340`), поэтому остались obvious-хвосты:
> `dB(A)` акустика, координатные таблицы ООС, СС2/СС5 графические labels,
> каталожные панели/оборудование, микроклимат ОВ, ТХ спецификационные строки.
> Правки: расширены существующие buckets `ENV/ACOUSTIC`, `ENV/AIR`, `GEO`,
> `HVAC`, `CATALOG`, `SPEC`, `ROOM`, `FIRE/RISK`, `NOISE` без добавления
> answer templates. Replay по свежему live sidecar: `5754` candidates,
> `UNKNOWN=374`; оставшийся хвост считаем честным `manual/visual required`, а
> не поводом бесконечно расширять эвристику.
> Проверки: `python3 -m compileall -q` по изменённым сервисам/тестам → ok;
> `uv run pytest tests/test_project_pdf_table_service.py
> tests/test_project_pdf_extract_service.py tests/test_tool_harness_service.py
> tests/test_static_assets.py -q` → `59 passed`; `git diff --check` по
> затронутым файлам → ok. Deploy tool copied 3 files and restarted
> `me.ovc.les.proxy`; live `/api/version` → `0.24.0.313`, deploy stamp ok.
> Финальный живой rebuild ИЦ:
> `POST /api/rag/datasets/1728e431-56d1-410f-8bf9-fdbf2543dce0/pdf-extract/run?force=true&max_files=500&max_pages=260`
> → `154` PDF, `153` ok, `1` extract error, `detected_tables=5754`,
> `UNKNOWN=268`, `ENV/ACOUSTIC=968`, `SERVICE=2195`, `NOISE=296`, `NAV=323`.
> `GET pdf-extract/status` → `stale=false`, `updated_at=2026-07-09T09:37:24+00:00`.
> `POST /api/notebooks/.../memory/refresh` подтвердил `project_pdf_extract`
> в `dataset_memory_v1` с теми же `5754/268`.

> 0.24.0.312 — final IC table semantic cleanup
>
> Дата: 2026-07-09
> Статус: superseded by `0.24.0.313`; deployed/rebuilt промежуточно.
> Причина: после `0.24.0.311` в ИЦ оставался крупный obvious-хвост
> `UNKNOWN`: СС5/СС2 графические обрезки, ПБ АУПТ/риски, ООС акустика/почвы,
> ЭЭ энергопаспорт и ЭС КЕО/освещение.
> Правки: `project_pdf_table_service` получил последние стабильные buckets:
> `FIRE/AUPT`, `FIRE/RISK`, `ELEC/LIGHT`, `ENV/SOIL`, `TEP/STAFF`, расширенные
> `ENV/ACOUSTIC`, `ENERGY`, `STRUCT/*` и `NOISE` для графических fragments.
> Это остаётся navigation/source-map layer: код классифицирует тип таблицы и
> source_ref, но не пишет инженерный ответ за модель.
> Проверки: pending. Replay по live ИЦ sidecar без rebuild: `5340` candidates,
> `UNKNOWN=316` против старого сохранённого `1242`; top buckets:
> `TEXT=1634`, `ENV/ACOUSTIC=796`, `SERVICE=492`, `AUTOMATION=344`,
> `NOISE=268`, `NAV=243`, `STRUCT/REINF=226`, `SPEC=157`,
> `ENV/AIR=151`.

> 0.24.0.311 — tool-harness dry-run interface + one-row table cleanup
>
> Дата: 2026-07-09
> Статус: deployed to runtime точечно (`sovushka/pages/documents.py`,
> `project_pdf_table_service.py`, `project_pdf_extract_service.py`,
> `version_service.py`).
> Причина: операторский `Tool-harness dry-run` должен нормально показывать тот
> же интерфейс, который получает модель, включая первый шаг `shortlist`, а PDF
> table classifier не должен отбрасывать длинные однострочные таблицы/абзацы
> PyMuPDF, потому что они сильно искажают статистику ИЦ.
> Правки: в Sovushka «Документы» добавлена кнопка `Shortlist` и компактное
> описание interface contract рядом с `Registry/Dataset map/Search/Read doc/FS
> roots`. `ALGO-tool-harness.md` расширен до полноценного описания GUI/API/CLI,
> auth policy, request/response и tool args. `project_pdf_table_service`
> классифицирует длинные one-row samples как `NAV`/`TEXT`/discipline candidates
> вместо silent drop; добавлены regression tests. `PROJECT_PDF_EXTRACT_ALGO_VERSION`
> поднят до `0.24.0.311`, так что старые sidecars честно stale до rebuild.
> Проверки: `python3 -m compileall -q sovushka/pages/documents.py
> proxy/services/project_pdf_table_service.py
> tests/test_project_pdf_table_service.py` → ok; `uv run pytest
> tests/test_tool_harness_service.py tests/test_static_assets.py
> tests/test_project_pdf_table_service.py tests/test_project_pdf_extract_service.py
> -q` → `44 passed`; `git diff --check` по затронутым файлам → ok. Deploy tool
> copied 4 files and restarted `me.ovc.les.proxy` + `com.les.sovushka`; live
> `/api/version` → `0.24.0.311`, deploy stamp ok. Replay новым classifier по
> live ИЦ sidecar без rebuild: `5340` candidates, `UNKNOWN=773`, `TEXT=1638`,
> `ENV/ACOUSTIC=759`, `NAV=238`, `SPEC=157`, `HVAC/HEAT=55`. Live
> `pdf-extract/status` остаётся `stale=true`; сохранённый sidecar всё ещё
> показывает старую статистику до rebuild (`UNKNOWN=1242`).

> 0.24.0.310 — СОД dataset project map + table semantic cleanup
>
> Дата: 2026-07-09
> Статус: deployed to runtime точечно (`sovushka/pages/documents.py`,
> `proxy/routers/documents.py`, `project_pdf_table_service.py`,
> `project_pdf_extract_service.py`, `version_service.py`).
> Причина: при выборе датасета оператору нужна не только выдача chunks, а СОД:
> карта корпуса, описание, перечень проектов/корней, PDF/тома с
> характеристиками, поиск и быстрые действия открыть/спросить.
> Правки: `sovushka/pages/documents.py` делает вкладку `СОД` первым видом
> датасета, автоматически поднимает `project_pdf_extract/summary`, показывает
> coverage, project roots, discipline summaries и фильтруемый список PDF/томов
> с действиями `Открыть в LES`, `Открыть системно`, `Спросить`. Добавлен
> admin-only endpoint `POST /api/documents/by-id/{doc_id}/open-native`, который
> открывает системно только `source_path` документа из MetaDB.
> Дополнительно: table semantic classifier получил bounded cleanup по ИЦ
> sidecar samples: состав томов уходит в `NAV`, короткие слаботочные выноски
> схем в `NOISE`, спецификационные шапки в `SPEC`, воздухообмен в `HVAC`,
> теплопотери в `HVAC/HEAT`, абзацы ПЗ в `TEXT`, крупные акустические/КР
> buckets меньше тонут в `UNKNOWN`/`CATALOG`. `PROJECT_PDF_EXTRACT_ALGO_VERSION`
> поднят до `0.24.0.310`, поэтому старые sidecars честно `stale=true`.
> Проверки: `python3 -m compileall -q` по изменённым сервисам/UI/тестам → ok;
> `uv run pytest tests/test_project_pdf_table_service.py
> tests/test_project_pdf_extract_service.py tests/test_static_assets.py -q`
> → `32 passed`; `git diff --check` по затронутым файлам → ok; deploy tool
> copied 5 files and restarted `me.ovc.les.proxy` + `com.les.sovushka`;
> live `/api/version` → `0.24.0.310`, deploy stamp ok; live ИЦ
> `pdf-extract/status` → `stale=true`, `154` PDF, `153` ok, `1` extract error.
> `POST /api/documents/by-id/__missing__/open-native` → `404`, route mounted
> without opening a real file.

> 0.24.0.309 — heavy-vector table detection guard
>
> Дата: 2026-07-09
> Статус: deployed to runtime точечно (`project_pdf_table_service.py`,
> `project_pdf_extract_service.py`, `version_service.py`).
> Причина: полный `pdf-extract/run` по `ПД_Инновационный центр` должен идти по
> всем 154 PDF, но `PyMuPDF page.find_tables()` может зависать на тяжёлых
> векторных планах. Ранее разовый аудит шёл с внешним timeout; runtime endpoint
> такой защиты не имел.
> Правки: `project_pdf_table_service` перед `find_tables()` считает vector
> drawings страницы и пропускает чрезмерно тяжёлые страницы с warning
> `table_detection_skipped_heavy_vector_page`, вместо блокировки всего run.
> Проверки: `python3 -m compileall -q` по изменённым сервисам/тестам → ok;
> `uv run pytest tests/test_project_pdf_table_service.py
> tests/test_project_pdf_extract_service.py -q` → `15 passed`; `git diff --check`
> по затронутым файлам → ok; live `/api/version` → `0.24.0.309`, deploy stamp
> ok. Полный живой прогон ИЦ ПД:
> `POST /api/rag/datasets/1728e431-56d1-410f-8bf9-fdbf2543dce0/pdf-extract/run?force=true&max_files=500&max_pages=260`
> завершён: `154` PDF, `153` ok, `1` пустой/битый PDF, `stale=false`.
> `project_table_summary`: `detected_tables=5340`, `hvs_rows=85`,
> `water_balance_rows=2`, `room_explication_rows=119`. Top semantic table
> classes: `UNKNOWN=1242`, `SERVICE=988`, `CATALOG=592`,
> `ENV/ACOUSTIC=490`, `AUTOMATION=303`, `QTY=282`, `FIRE=232`,
> `ENV/AIR=214`, `ELEC/LINE=125`, `ENV/WASTE=118`, `STRUCT/CALC=113`,
> `LOWCURRENT=110`, `ELEC=46`, `HVAC=16`, `ROOM=14`. В sidecar warnings
> ожидаемо попали тяжёлые векторные страницы с
> `table_detection_skipped_heavy_vector_page`. `POST
> /api/notebooks/1728e431-56d1-410f-8bf9-fdbf2543dce0/memory/refresh`
> подтвердил `project_pdf_extract_brief_v1` в `dataset_memory_v1`.
> Попытка `max_pages=2000` была остановлена после зависания на гигантском
> векторном листе; рабочий production-safe прогон сейчас ограничен
> `max_pages=260`, без reindex.

> 0.24.0.308 — semantic table type candidates for PDF projects
>
> Дата: 2026-07-08
> Статус: deployed to runtime точечно (`project_pdf_table_service.py`,
> `project_pdf_extract_service.py`, `version_service.py`).
> Причина: первый проход по `ПД_Инновационный центр` нашёл `7446`
> tabular objects, но сырые сигнатуры и служебные рамки не дают модели
> компактную карту типов таблиц. Нужен слой "какая это таблица" без
> нормализации всех строк и без answer-template.
> Правки: `project_pdf_table_service` теперь для каждой найденной PDF-таблицы
> пишет compact `project_pdf_table_type_candidate_v1` с `semantic_type`,
> `category`, `source_ref` и sample; dataset summary агрегирует
> `semantic_table_types` и добавляет model-facing navigation по инженерным
> классам. Sidecar `project_pdf_table_manifest` теперь сохраняется при любых
> найденных таблицах, не только при ХВС/ВК/экспликациях. Классы покрывают
> КР расчёты/арматуру/грунты, ООС шум/выбросы/отходы, ПБ эвакуацию/АУПТ/
> токопотребление, ИОС automation/слаботочку/спецификации, а также
> `SERVICE`/`NAV`/`NOISE` как неинженерные группы.
> Дополнительно: `PROJECT_PDF_EXTRACT_ALGO_VERSION` включён в input signature,
> поэтому старые sidecars после смены extraction logic становятся `stale=true`.
> Проверки: `compileall` по изменённым сервисам/тестам ok;
> `uv run pytest tests/test_project_pdf_table_service.py
> tests/test_project_pdf_extract_service.py -q` → 15 passed; `git diff --check`
> по затронутым файлам → ok; live `/api/version` → `0.24.0.308`, deploy stamp
> ok; live ИЦ ПД targeted runtime extraction: `ИОС.ОВ.pdf` → `detected_tables=136`,
> `hvs_rows=85`, `HVAC: характеристики воздушных систем ХВС=10`; `ООС1.pdf`
> → `detected_tables=148`, `ENV/WASTE=49`, `ENV/AIR=32`, `water_balance_rows=2`;
> `ПБ.pdf` → `detected_tables=69`, `room_explication_rows=25`,
> `FIRE: эвакуация, АУПТ и пожарный риск=30`. ИЦ sidecar status после смены
> algo signature → `stale=true`, полный `run` не запускался.

> 0.24.0.307 — HVS table row quality for OVK
>
> Дата: 2026-07-08
> Статус: deployed to runtime точечно (`project_pdf_table_service.py`,
> `version_service.py`).
> Причина: живая проверка `ОВК` ИЦ ПД подтвердила правильный принцип
> `find table -> header/context -> classify -> read rows`, но в ХВС/ОВК
> попадали строки-нумераторы колонок и секционные строки.
> Правки: `project_pdf_table_service` теперь читает multi-row/stacked table
> headers, классифицирует таблицу до нормализации и фильтрует ХВС-строки:
> чистые номера и разделы без обслуживаемой зоны/оборудования/числовой
> характеристики не попадают в normalized rows.
> Проверки: `compileall` по изменённым сервисам/тестам ok;
> `uv run pytest tests/test_project_pdf_table_service.py
> tests/test_project_pdf_extract_service.py -q` → 9 passed;
> live ИЦ ПД runtime: ОВК `ИОС.ОВ.pdf` → `hvs_rows=8`,
> `water_balance_rows=0`, пример строк `У1, У3`, `У2`, `У4`, `А1-А10`;
> live ИЦ ПД runtime: СС2 `ИОС.СС2.pdf` → `room_explication_rows=374`.
> ВС/ВО ИЦ ПД быстрый поиск по `баланс/водопотреб/водоотвед` нашёл только
> страницы состава проекта, без реального водного баланса в текстовом слое.

> 0.24.0.306 — shared project PDF table extractor
>
> Дата: 2026-07-08
> Статус: deployed to runtime точечно (`project_pdf_table_service.py`;
> `project_pdf_extract_service.py` и `version_service.py` уже совпадали).
> Причина: PDF Project Reader должен извлекать общие проектные таблицы, которые
> есть не только в ЭС: ОВ `ХВС`/характеристики воздушных систем, ВК водные
> балансы и экспликации помещений на графических листах.
> Правки: добавлен `project_pdf_table_service` с нормализацией
> `hvs_air_system_row_v1`, `vk_water_balance_row_v1`,
> `room_explication_row_v1`; `project_pdf_extract_service` пишет
> `project_pdf_table_manifest.json`, агрегирует `project_pdf_table_summary`
> в coverage/source_navigation и не подменяет ответ модели.
> Проверки: `python3 -m compileall -q proxy/services/project_pdf_table_service.py
> proxy/services/project_pdf_extract_service.py proxy/services/version_service.py
> tests/test_project_pdf_table_service.py tests/test_project_pdf_extract_service.py`
> → ok; `uv run pytest tests/test_project_pdf_table_service.py
> tests/test_project_pdf_extract_service.py -q` → `8 passed`; `git diff --check`
> по затронутым файлам → ok; live `/api/version` → `0.24.0.306`, deploy
> stamp ok. Живая проверка на `ПД_Инновационный центр`: runtime extractor по
> `395.01-B481.120100.2.4-ИОС.СС2.pdf` дал `room_explication_rows=374`;
> ложные чтения состава проекта как ВК/экспликации отфильтрованы через
> классификацию `find table -> header/context -> table_type -> rows`.

> 0.24.0.305 — PDF reader contract for OV/VK/room explications
>
> Дата: 2026-07-08
> Статус: deployed to runtime точечно (`version_service.py`); документационный
> контракт обновлён в dev.
> Причина: project PDF reader должен покрывать не только ЭС/ЭОМ. Для реальной
> ПД/РД базовыми машиночитаемыми слоями являются ОВ таблицы `ХВС`
> (характеристики воздушных систем), ВК водные балансы и экспликации помещений
> на графических листах с планировками: номер, имя, площадь, категории.
> Правки: `ALGO-pdf-ingestion.md` фиксирует эти слои как контракт следующих
> extractors; `MODULE_INDEX` и `ROADMAP_TO_V1` обновлены, чтобы не свести
> PDF Project Reader к электрическим шаблонам.
> Проверки: `python3 -m compileall -q proxy/services/version_service.py` → ok;
> `git diff --check` по затронутым файлам → ok; live `/api/version` →
> `0.24.0.305`, deploy stamp ok.

> 0.24.0.304 — project PDF extract fail-open on broken PDFs
>
> Дата: 2026-07-08
> Статус: deployed to runtime точечно (`project_pdf_extract_service`,
> `version_service`).
> Причина: прогон `ПД_Инновационный центр` показал реальный архивный случай:
> один нулевой PDF (`Приложение Д_tmp.pdf`) валил весь `pdf-extract/run`.
> Правки: `project_pdf_extract_service` теперь помечает пустой/битый PDF как
> `extract_error` с warning и продолжает строить source-map по остальному
> комплекту; добавлен coverage-счётчик `extract_errors`.
> Проверки: `python3 -m compileall -q proxy/services/project_pdf_extract_service.py
> proxy/services/version_service.py tests/test_project_pdf_extract_service.py` → ok;
> `uv run pytest tests/test_project_pdf_extract_service.py -q` → `2 passed`;
> `git diff --check` по затронутым файлам → ok; live `/api/version` →
> `0.24.0.304`, deploy stamp ok.
> Реальный прогон: `ПД_Инновационный центр`
> (`1728e431-56d1-410f-8bf9-fdbf2543dce0`) `pdf-extract/run` построил
> sidecar по `154` PDF: `153` ok, `1` `extract_error`
> (`Приложение Д_tmp.pdf` пустой), `17` ПЗ, `12` ВОР, `17` СО. Electrical
> summary: `1731` load rows, `226` candidate circuits, `680` material rows,
> `55` cable material rows, `394` SO rows, `284` VOR rows, `386`
> SO→draft-VOR seed rows. `POST /api/notebooks/{dataset_id}/memory/refresh`
> подтвердил, что `project_pdf_extract` попал в `dataset_memory_v1`.

> 0.24.0.303 — project shortcut from dataset lists
>
> Дата: 2026-07-08
> Статус: deployed to runtime точечно (`sovushka/pages/documents.py`,
> `sovushka/pages/samovar.py`, `proxy/services/version_service.py`).
> Причина: операторский action “Проект” был доступен из RAG/chat-контекста,
> но на списках датасетов не было прямого входа “спросить модель про весь
> проектный датасет”.
> Правки: в `sovushka/pages/documents.py` добавлена кнопка “Проект” на
> карточку датасета; в `sovushka/pages/samovar.py` добавлен такой же action
> в строку действий нового экрана датасетов. Переход открывает чат со
> `scope=ds:{dataset_id}` и общим проектным вопросом, без предметного
> answer-template.
> Проверки: `python3 -m compileall -q sovushka/pages/documents.py
> sovushka/pages/samovar.py proxy/services/version_service.py` → ok;
> `git diff --check` по затронутым файлам → ok; live `/api/version` →
> `0.24.0.303`, deploy stamp ok.

> 0.24.0.302 — project PDF extract source-map for RAG
>
> Дата: 2026-07-08
> Статус: deployed to runtime точечно (`project_pdf_extract_service`,
> `drawing_manifest_service`, `pd_rd_manifest_service`,
> `electrical_*_service`, `config/domain/electrical_schema_terms.yaml`,
> `proxy/routers/datasets.py`, `dataset_memory_service`,
> `sovushka/pages/documents.py`, CLI tools).
> Причина: PDF-проект должен попадать в RAG не как случайные чанки, а как
> source-map: состав томов, листы/штампы, ПЗ/оглавления, ВОР/СО/таблицы и
> дисциплинные подсказки для открытия нужных файлов. Код не должен отвечать за
> модель и не должен reindex-ить корпус ради этой карты.
> Правки: добавлен `project_pdf_extract_service` с sidecar
> `storage/datasets/{dataset_id}/_les_pdf_extract/project_pdf_extract_v1`, API
> `/api/rag/datasets/{dataset_id}/pdf-extract/{status,run,summary}`, compact
> `project_pdf_extract` в `dataset_brief_for_model`, операторская панель
> “PDF extract” в «Документы», critical bundle обновлён.
> Проверки: `python3 -m compileall -q` по затронутым Python-файлам;
> `uv run pytest tests/test_project_pdf_extract_service.py
> tests/test_dataset_memory_service.py -q` → `22 passed`; `git diff --check`
> по затронутым файлам → ok; live `/api/version` → `0.24.0.302`, deploy
> stamp ok; live `GET /api/rag/datasets/449190eb-050e-422f-91a6-54852469201a/pdf-extract/status`
> → 37 PDF, summary not built yet.

> 0.24.0.301 — smeta cleanup: prompt boundaries, checked model code, norm source merge
>
> Дата: 2026-07-08
> Статус: dev, deploy pending.
> Причина: после чистки pricebook/norm identity оставались ошибки обвязки:
> отсутствие pricebook слишком широко откатывало `сделай ЛСР` в этап
> candidates; batch harness мог заменить выбранный моделью шифр первым
> кандидатом shortlist; `gesn2022_v2.parquet` с пустыми `norm_name/norm_unit`
> стирал заполненные поля старой базы; одиночные typed-нормы вроде
> `ГЭСНм:38-01-001-01` давали пустую nearby-навигацию.
> Правки: `_smeta_direct_user_prompt` разводит raw source без найденных
> норм/ценников в `ВОР -> кандидаты`, но проверенную таблицу ВОР-ГЭСН и
> MODEL-SELECTED NORM LOOKUP оставляет в pricing с 0.00/добором; scoped
> empty retrieval возвращает честный `NO_DATA` без падения на тестовом
> semaphore. `estimate_harness_service` проверяет явный шифр, выбранный
> моделью, по локальной базе и считает именно его, не подменяя первым
> search-кандидатом; ranking труб кабельных трасс снова держит `08-05-044`
> в candidate pool. `gesn_service.load_base_norms()` больше не даёт пустому
> overlay стирать название/измеритель, а `smeta_norm_store.nearby_rows()`
> даёт broad fallback по typed базе/element hints для навигации.
> Проверки: compact regression `6 passed`; focused failed-regression set
> `11 passed`; `tests/test_chat_harness_format.py
> tests/test_clarification_service.py tests/test_estimate_harness.py -q`
> → `179 passed`.

> 0.24.0.300 — smeta data/lookup consistency audit fix
>
> Дата: 2026-07-08
> Статус: dev, deploy pending.
> Причина: аудит БАП/нормативной базы показал внутренние расхождения, которые
> мешают модели и расчёту: low-level LSR/API без `book` мог брать первый
> parquet по алфавиту (например, не СПб), scratch `spb_refresh` висел как
> обычная ценовая книга, а bare-нормы старого parquet могли молча
> трактоваться как `ГЭСН` при наличии нескольких семейств норм.
> Правки: добавлен единый `fgis_price_service.resolve_pricebook_path()` с
> дефолтом `LES_DEFAULT_PRICEBOOK` → `spb_2kv2026`/
> `sankt-peterburg_2kv2026` → доступные 2026; `available_pricebooks()` по
> умолчанию скрывает scratch/`*_refresh`; `lsr_assembly_service`,
> `/api/prices` и `lookup_local_first` используют тот же resolver.
> `gesn_service.get_norm(..., strict_family=True)` больше не возвращает
> `ГЭСН:<bare>`, если bare-код найден в нескольких семействах; обычный
> `get_norm()` оставлен совместимым для legacy API. Parquet без
> `base_type/norm_key` помечается как `legacy_untyped_parquet`.
> `smeta_norm_store_v5` не показывает пустые
> карточки и демотирует legacy-untyped candidates ниже typed-кандидатов.
> Код не выбирает нормы за модель, а выравнивает источники, ключи и расчетный
> default.
> Проверки: focused pytest
> `tests/test_fgis_price_service.py tests/test_gesn_import.py
> tests/test_smeta_norm_store.py tests/test_lsr_assembly_service.py -q`
> → `36 passed`.

> 0.24.0.299 — smeta finish operation retrieval exposure
>
> Дата: 2026-07-07
> Статус: deployed to runtime точечно (`proxy/routers/chat.py`,
> `proxy/services/estimate_harness_service.py`,
> `proxy/services/version_service.py`).
> Причина: live БАП на `0.24.0.298` доказал, что review-pass снимает
> неверные аналоги (`демонтаж кабеля` как прокладку, `люк ГКЛ` как чужую
> монтажную норму), но стандартная отделка 6/7/8/10/13/14 оставалась нулём:
> model-owned lookup передавал общий `element_type=finish`, `action=устройство`,
> и `search_norm` показывал модели штукатурку/каркасы/потолки вместо
> грунтовки/шпатлевки/оклейки/окраски. Это retrieval exposure, не выбор нормы.
> Правки: `search_norm` для `work_family=finishes` теперь уточняет generic
> `finish/устройство` по видимой операции в тексте (`primer`, `putty`,
> `wallpaper`, `painting`) и поднимает same-operation candidates с
> поверхностью/единицей в score_parts, чтобы модель видела правильный участок
> базы. Review prompt дополнен общей сметной проверкой: строку «подготовка
> поверхности к восстановлению отделки» не закрывать штукатуркой/каркасом/
> устройством потолка, если candidates не описывают именно подготовку этой
> поверхности; при отсутствии точной нормы — `unbound` со строкой `0.00`.
> Проверки: focused pytest
> `tests/test_estimate_harness.py::test_generic_finish_search_infers_standard_finish_operations
> tests/test_estimate_harness.py::test_finish_painting_search_routes_to_painting_norms -q`
> → `2 passed`; focused review+finish+electric ranking → `7 passed`;
> `git diff --check` clean; `make verify` → compileall ok, pytest
> collect-only `2597 tests collected`; deploy copied `chat.py`,
> `estimate_harness_service.py`, `version_service.py`, proxy restarted;
> `/api/version` → `les_version=0.24.0.299`,
> `deployed_les_version=0.24.0.299`, stamp ok. Live БАП SSE:
> workflow/lookup/choice/review provider `openai gpt-5.4`, stage `pricing`,
> visible 19 строк, `review.status=ok`, `approved=12`, `replaced=0`,
> `unbound=7`, `missing_review_rows=0`; ЛСР РИМ `12/19`, итог
> `483 720 руб.`. Остались нулём только строки без честного кандидата:
> защитное укрытие пленкой, демонтаж кабеля, проём ГКЛ под люк, монтаж
> скрытого лючка, подготовка поверхности как общая строка, демонтаж реечного
> потолка, отдельные скобы. Live artifact сохранён:
> `/tmp/bap_live_chat_final_299.json`, SSE `/tmp/bap_live_chat_stream_299.sse`;
> XLSX выгружен в `/Users/ovc/Downloads/BAP_LSR_LES_live_0.24.0.299.xlsx`.

> 0.24.0.298 — smeta model-owned norm review before pricing
>
> Дата: 2026-07-07
> Статус: deployed to runtime точечно (`proxy/routers/chat.py`,
> `proxy/services/version_service.py`).
> Причина: после `0.24.0.297` live БАП route/provider/retrieval стали
> рабочими, но первичный norm-choice иногда одновременно принимал чужие
> аналоги (демонтаж кабеля как прокладку, люк ГКЛ как другую технологию) и
> оставлял нормируемую отделку пустой. Это не задача для кода-решателя:
> пользовательская граница остаётся прежней — модель выбирает нормы, код
> считает и проверяет provenance.
> Правки: `_smeta_direct_structured_norm_choice()` теперь после чернового
> выбора запускает второй model-owned review-pass. Ревизор получает тот же
> `lookup_results` с `norm_card` и черновые строки и возвращает JSON
> `approve|replace|unbound` по каждой позиции. `replace` разрешён только шифром,
> дословно присутствующим в candidates этого lookup; код не выбирает лучший
> кандидат и не делает смысловой фильтр, а только валидирует наличие шифра,
> переносит подтверждённые строки в расчёт или оставляет строку `нужен подбор
> нормы` с `0.00`/причиной. Prompt ревизора закрепляет общие сметные проверки:
> не менять действие/элемент/технологию, не считать демонтаж монтажом, не
> закрывать ГКЛ-люки нормами другого потолка, добирать стандартную отделку
> same-operation analog при совместимой единице, предпочитать малый БАП
> светильника крупной UPS-системе без исходного признака системы/шкафа/кВт.
> Trace `smeta_norm_choice.review` показывает provider/model, timeout,
> selector_text, approved/replaced/unbound, missing review rows и invalid
> norm_code rows.
> Проверки: focused pytest
> `tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_validates_model_code_from_lookup
> tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_gets_norm_card_and_mismatch_rule
> tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_keeps_unreturned_lookup_as_unbound_row
> tests/test_chat_harness_format.py::test_smeta_structured_norm_review_can_unbind_wrong_action_draft
> tests/test_chat_harness_format.py::test_smeta_structured_norm_review_can_replace_empty_finish_draft -q`
> → `5 passed`; focused smeta route/ranking/review → `12 passed`;
> `git diff --check` clean; `make verify` → compileall ok, pytest
> collect-only `2596 tests collected`; deploy copied `chat.py` and
> `version_service.py`, proxy restarted; `/api/version` →
> `les_version=0.24.0.298`, `deployed_les_version=0.24.0.298`, stamp ok.
> Live БАП SSE: route/provider ok, review ok (`approved=5`, `replaced=2`,
> `unbound=12`, `missing_review_rows=0`), visible 19 строк, сумма
> `489 729 руб.`, `7/19` priced. Review снял неверные строки 2 и 4, но
> отделочные строки 6/7/8/10/13/14 остались нулём из-за generic finish lookup;
> закрывается следующим патчем `0.24.0.299`.

> 0.24.0.297 — smeta norm retrieval/ranking for live ЛСР
>
> Дата: 2026-07-07
> Статус: deployed to runtime точечно (`proxy/services/estimate_harness_service.py`,
> `proxy/routers/chat.py`, `proxy/services/version_service.py`).
> Причина: после `0.24.0.296` live БАП chat-route перестал уходить в candidate
> stage и выдал ЛСР на 19 строк, но сумма отличалась от проверенного golden:
> модель брала крупную UPS-норму для БАП светильника, клеммную коробку вместо
> ответвительной и indoor гофру могла заменить подземной трубой. Это не
> арифметика, а model-facing norm retrieval/ranking: расчётная база нормы знала,
> но lookup-витрина поднимала шумные аналоги.
> Правки: smeta model runtime больше не игнорирует подключённый cloud:
> если глобальный `LES_LLM_PROVIDER` указывает на usable cloud runtime с ключом,
> smeta workflow/lookup/choice/final используют его; явный
> `LES_SMETA_PROVIDER=mlx` по-прежнему принудительно оставляет локальную модель,
> а отсутствие ключа падает в MLX. `search_norm` точечно допускает `ГЭСНм10/10` для
> `electric+backup_power` и поднимает `преобразователь/блок питания` над
> крупной UPS-системой для светильников; для гофрированной ПВХ-трубы поднимает
> indoor route `для защиты проводов и кабелей` и штрафует `в земле`, если
> исходник не про траншею; для коробок открытой проводки поднимает
> `ответвительную` и штрафует `клеммную`, если нет клемм/зажимов; для кабеля
> поднимает прокладку `с креплением накладными скобами` и штрафует
> `маслонаполненный/высокого давления` и `без креплений`, когда исходник не про
> эти условия. Structured
> norm-choice prompt запрещает аналоги с обратным или чужим действием
> (`демонтаж` через монтаж/облицовку, `шпатлевка` через облицовку), требует
> предпочитать совпадающую поверхность (`потолки` над `стены`) и малый БАП
> светильника над кВт UPS-системой. Candidate window для smeta lookup/choice
> расширено до 10, чтобы модель видела не только шумный top-5; для стандартной
> отделки (`грунтовка`, `шпатлевка`, `оклейка`, `окраска`) prompt требует брать
> same-operation/same-surface analog при совместимой единице, а проёмы/люки ГКЛ
> оставлять нулём, если candidates про другой тип потолка/люка. Код по-прежнему
> не выбирает норму строки:
> он только ранжирует read-only candidates; выбор остаётся у модели.
> Проверки: focused pytest
> `tests/test_chat_harness_format.py::test_smeta_model_runtime_defaults_to_global_cloud_when_api_key_is_available
> tests/test_chat_harness_format.py::test_smeta_model_runtime_explicit_mlx_overrides_global_cloud
> tests/test_chat_harness_format.py::test_smeta_model_runtime_can_explicitly_follow_global_provider`
> плюс
> `tests/test_estimate_harness.py::test_electric_backup_power_search_prefers_power_over_lighting_blocks
> tests/test_estimate_harness.py::test_electric_backup_power_for_luminaire_prefers_small_power_supply_block
> tests/test_estimate_harness.py::test_electric_pipe_search_routes_to_cable_trace_pipes
> tests/test_estimate_harness.py::test_electric_box_search_routes_to_electrical_boxes
> tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_gets_norm_card_and_mismatch_rule
> tests/test_chat_harness_format.py::test_smeta_norm_lookup_policy_keeps_eom_containment_out_of_metal_family -q`
> → `6 passed`; доп. focused runtime/default-provider tests → `10 passed`;
> `make verify` → compileall ok, pytest collect-only `2594 tests collected`;
> deploy copied `estimate_harness_service.py`/`chat.py`, proxy restarted;
> `/api/version` → `les_version=0.24.0.297`,
> `deployed_les_version=0.24.0.297`, stamp ok.
> Runtime spot-check `search_norm`: БАП → `ГЭСНм10-02-016-06`, кабель →
> `ГЭСНм08-02-146-04`, гофра → `ГЭСНм08-02-409-09`, коробка →
> `ГЭСНм08-02-420-01` в top. Live БАП SSE после cloud-default: route/provider
> исправлены (`workflow/lookup/choice provider=openai gpt-5.4`, 19 rows
> covered), но golden ещё не достигнут. Лучший cloud smoke:
> `7/19`, `482 132.69 руб.`; после расширения candidate window:
> `8/19`, `581 586.99 руб.`. Остаток: model-choice stability — модель
> иногда принимает чужие аналоги (демонтаж кабеля как прокладку, лючок как
> лепные детали) и одновременно оставляет нормируемую отделку пустой. Следующий
> фикс нужен как model-owned review/approval-pass выбранных норм перед расчётом,
> не как кодовый выбор нормы.

> 0.24.0.296 — smeta chat ЛСР-pricing priority
>
> Дата: 2026-07-07
> Статус: deployed to runtime точечно (`proxy/routers/chat.py`,
> `proxy/services/version_service.py`).
> Причина: live `/api/chat/stream mode=smeta` по БАП завершался candidate-stage:
> `smeta_norm_choice.status=blocked_by_tz_stage_gate`, без RIM total. Это
> противоречит текущему правилу: явное «сделай ЛСР/смету/стоимость» должно
> давать `priced_partial`, а КАЦ/missing остаются строками добора.
> Правки: `_smeta_direct_norm_candidate_stage_required()` больше не трактует
> raw ВОР + ЛСР как обязательный этап кандидатов; candidate-stage остаётся
> только для явного «кандидаты/этап 1/без денег». Workflow selector prompt
> закрепляет pricing для явных ЛСР/стоимость запросов, а ошибочный
> `norm_candidates` корректируется в `pricing` с trace
> `stage_correction=explicit_lsr_request_has_pricing_priority`. Norm lookup
> prompt получил системную ЭОМ-границу: гофра/скобы крепления гофры/коробки
> проводки/БАП маршрутизируются как `electric`, не как `metal/ГЭСН09`;
> отдельная скоба без нормы остаётся normative gap, а не бункеры/опорные
> металлоконструкции.
> Проверки: focused pytest
> `tests/test_chat_harness_format.py::test_smeta_direct_raw_vor_lsr_goes_to_pricing_stage
> tests/test_chat_harness_format.py::test_smeta_direct_explicit_candidate_table_stays_stage_one
> tests/test_chat_harness_format.py::test_smeta_workflow_decision_corrects_candidate_stage_for_explicit_lsr
> tests/test_chat_harness_format.py::test_smeta_norm_lookup_policy_keeps_eom_containment_out_of_metal_family
> tests/test_chat_harness_format.py::test_smeta_direct_norm_lookup_is_model_selected
> tests/test_chat_harness_format.py::test_smeta_direct_checked_norm_table_allows_pricing_stage
> tests/test_smeta_artifact_service.py::test_checked_rim_form_keeps_source_row_order_across_sections -q`
> → `7 passed`; `make verify` → compileall ok, pytest collect-only
> `2592 tests collected`; deploy copied 2 files, proxy restarted;
> `/api/version` → `les_version=0.24.0.296`, `deployed_les_version=0.24.0.296`,
> stamp ok. Live БАП SSE на `0.24.0.296`: route исправлен
> (`workflow.stage=pricing`, artifact `rim_lsr_form`, 19 rows), но результат
> ещё расходится с golden из-за norm retrieval/ranking (`14/19`,
> `1 062 700.79 руб.` вместо проверенных `12/19`, `491 737.47 руб.`);
> закрывается следующим патчем `0.24.0.297`.

> 0.24.0.295 — RIM artifact source-row mapping
>
> Дата: 2026-07-07
> Статус: deployed to runtime точечно (`proxy/services/rim_lsr_trace_service.py`,
> `proxy/services/smeta_artifact_service.py`, `proxy/services/version_service.py`).
> Причина: при checked RIM-артефакте рассчитанные позиции группировались по
> разделам, а видимая ЛСР сопоставляла их с исходными строками последовательным
> iterator-ом. Если ВОР содержала несколько разделов и незакрытые строки, сумма
> оставалась общей, но отдельные строки могли получить чужой шифр/цену. На БАП
> это маскировало нормативную проверку строк.
> Правки: `build_lsr_trace()` сохраняет `source_row`, а
> `smeta_artifact_service._build_rim_trace_form()` мапит рассчитанную позицию
> по исходному номеру строки; fallback на старый порядок оставлен только для
> legacy trace без `source_row`. Код по-прежнему не выбирает нормы.
> Проверки: focused pytest
> `tests/test_smeta_artifact_service.py::test_checked_rim_form_keeps_source_row_order_across_sections
> tests/test_smeta_artifact_service.py::test_smeta_artifact_keeps_calculated_rows_when_source_rows_are_partial
> tests/test_smeta_artifact_service.py::test_smeta_artifact_trace_does_not_invent_norms_for_unbound_rows
> tests/test_rim_lsr_trace_service.py -q` → `16 passed`; `make verify` →
> compileall ok, pytest collect-only `2590 tests collected`. Deploy copied
> 3 files, proxy restarted; `/api/version` → `les_version=0.24.0.295`,
> `deployed_les_version=0.24.0.295`, stamp ok, `hash_mismatch_files=[]`.
> БАП checked endpoint smoke: `POST /api/lsr/lsr-trace/from-rows`
> (`spb_2kv2026`) → `19` row bindings, `12/19` bound, total
> `491 737.47 руб.`. Chat SSE smoke по той же ВОР завершился candidate-stage
> artifact без RIM total: `smeta_norm_choice.status=blocked_by_tz_stage_gate`,
> что соответствует текущему ТЗ "ВОР → кандидаты" без ручного подтверждения.

> 0.24.0.294 — smeta local MLX path and BAP smoke
>
> Дата: 2026-07-07
> Статус: deployed to runtime точечно (`proxy/routers/chat.py`,
> `proxy/services/version_service.py`) поверх `0.24.0.289`.
> Причина: после фикса `ГЭСНм08` live БАП всё ещё падал до расчёта на cloud
> `402 Payment Required`. Сметные model-owned шаги теперь по умолчанию идут в
> local MLX через smeta runtime helper: workflow decision, norm lookup,
> structured norm choice и финальный smeta answer. Cloud можно вернуть только
> явным `LES_SMETA_*_PROVIDER`, но глобальный `LES_LLM_PROVIDER=openai` больше
> не должен сам утаскивать smeta-контур в cloud.
> Правки: default `LES_SMETA_PROVIDER=mlx`; `LES_SMETA_NORM_LOOKUP_TIMEOUT_SEC`
> и `LES_SMETA_DIRECT_MODEL_TIMEOUT_SEC` для MLX — `1200s`, workflow для MLX —
> `300s`; trace пишет provider/model/timeout для lookup/choice/workflow.
> Selector выбора норм смягчён для pricing-stage: модель может брать
> технически близкий нормативный аналог из candidates и помечать проверку,
> вместо глобального отказа. Код по-прежнему не выбирает норму: он выполняет
> read-only lookup, проверяемую арифметику и provenance.
> Проверки: `python3 -m compileall -q proxy/routers/chat.py
> proxy/services/version_service.py tests/test_chat_harness_format.py` → ok;
> `git diff --check -- proxy/routers/chat.py proxy/services/version_service.py
> tests/test_chat_harness_format.py` → ok; focused pytest
> `tests/test_chat_harness_format.py::test_smeta_workflow_decision_is_model_owned_pricing_reuse
> tests/test_chat_harness_format.py::test_smeta_model_runtime_defaults_to_local_even_when_global_provider_is_cloud
> tests/test_chat_harness_format.py::test_smeta_model_runtime_can_explicitly_follow_global_provider
> tests/test_estimate_harness.py -q` → `95 passed`.
> Runtime: deploy copied 2 files, proxy restarted; `/api/version` →
> `les_version=0.24.0.294`, `deployed_les_version=0.24.0.294`, stamp ok,
> `hash_mismatch_files=[]`.
> Live БАП smoke на `0.24.0.293` перед финальным workflow-local patch:
> PDF read `25` table rows / `19` work rows; elapsed `864.5s`; norm lookup
> `provider=mlx`, `results=19`, `coverage_missing=0`; norm choice
> `provider=mlx`, `status=ok`, selected/priced `13/19`; RIM total
> `422 866 руб.`; visible LSR kept all `19` source rows with `0.00` on
> unclosed rows. Остаток: workflow trace в этом smoke ещё был cloud
> (`openai gpt-5.4`); это закрыто в `0.24.0.294`, но полный 15-минутный БАП
> повтор после `0.24.0.294` не запускался.

> 0.24.0.289 — smeta ГЭСНм08 candidate boundary
>
> Дата: 2026-07-07
> Статус: deployed to runtime точечно (`proxy/services/estimate_harness_service.py`,
> `proxy/services/version_service.py`)
> Причина: live БАП smoke на runtime `0.24.0.288` прочитал 19 строк ВОР,
> но priced только `3/19` и дал `4 700 руб.`. Диагноз: новая runtime-база
> маркирует электромонтажные нормы как `ГЭСНм:08-...` (`collection_key=ГЭСНм08`),
> а smeta search gate разрешал для `electric` только старый `08`. Правильные
> нормы `08-05-044`, `08-03-641`, `08-01-125` выпадали из route-кандидатов,
> а FTS-шум внутри строительного `08` (печи/мусоропровод) оставался в shortlist.
> Правки: `electric` и смежный `low_current` допускают `ГЭСНм08`; route priority
> считает `ГЭСНм08` электромонтажной базой. Это не выбор нормы кодом: модель
> по-прежнему выбирает норму, код только не выбрасывает релевантный сборник из
> candidate pool.
> Проверки: focused pytest
> `tests/test_estimate_harness.py::test_collection_of_prefixed_norm_code
> tests/test_estimate_harness.py::test_electric_accepts_gesnm08_from_current_fsnb_base
> tests/test_estimate_harness.py::test_electric_pipe_search_routes_to_cable_trace_pipes
> tests/test_estimate_harness.py::test_electric_box_search_routes_to_electrical_boxes
> tests/test_estimate_harness.py::test_electric_backup_power_search_prefers_power_over_lighting_blocks -q`
> → `5 passed`; `git diff --check -- proxy/services/estimate_harness_service.py
> tests/test_estimate_harness.py proxy/services/version_service.py
> docs/RELEASE_LEDGER.md` → ok; deploy
> `uv run python -m tools.deploy_to_runtime --apply --restart --force --files
> proxy/services/estimate_harness_service.py proxy/services/version_service.py`
> → copied 2 files, proxy restarted; `/api/version` →
> `les_version=0.24.0.289`, `deployed_les_version=0.24.0.289`,
> stamp ok, hash_mismatch_files=[].
> Runtime search spot-check после deploy: гофра БАП поднимает
> `ГЭСНм:08-02-409-09`/`ГЭСНм:08-05-044-*`, коробка —
> `ГЭСНм:08-02-420-01`/`ГЭСНм:08-03-641-*`, БАП —
> `ГЭСНм:08-01-125-01`; печи/мусоропровод ушли из top.
> Повторный live БАП smoke: 19 строк прочитаны, `smeta_norm_lookup` сделал
> 19 вызовов, но `smeta_norm_choice` упал на `402 Payment Required` от
> `https://openai.api.proxyapi.ru/v1/chat/completions`, поэтому проверенная
> расчётная РИМ-трасса не построилась (`accepted_rows=0`); видимый ответ —
> ЛСР-черновик, не priced-final.

> 0.24.0.288 — raw CAD/BIM skip boundary
>
> Дата: 2026-07-07
> Статус: deployed to runtime точечно (`backend/qdrant_adapter.py`,
> `proxy/config.py`, `proxy/routers/datasets.py`,
> `proxy/services/version_service.py`)
> Причина: raw `.dwg/.rvt/.ifc/.ifczip` через `+ папку` попадали в общий RAG
> intake и светились как `ERROR`, хотя LES не индексирует эти бинарные исходники
> как текстовые документы. Рабочий CAD/BIM вход — canonical JSON/JSONL projection
> или специализированный extractor/import.
> Правки: default `RAG_UPLOAD_SUFFIXES` больше не содержит raw CAD/BIM
> расширения; external intake-plan показывает их как `unsupported_suffix`; если
> старый raw CAD/BIM уже стоит в parse queue, `_sync_parse` помечает его
> `SKIPPED`, а не `ERROR`; `/api/rag/documents` принимает фильтр `SKIPPED`.
> Проверки: focused pytest
> `tests/test_datasets_router.py::test_external_intake_plan_keeps_maps_out_of_accepted_count
> tests/test_datasets_router.py::test_external_intake_plan_skips_raw_cad_bim_sources
> tests/test_parse_pipeline_w14.py::test_raw_cad_bim_source_is_skipped_not_indexed_zero -q`
> → `3 passed`; `git diff --check -- ...` → ok; `make verify` →
> compileall ok, pytest collect-only `2586 tests collected`; deploy
> `uv run python -m tools.deploy_to_runtime --apply --restart --force --files
> backend/qdrant_adapter.py proxy/config.py proxy/routers/datasets.py
> proxy/services/version_service.py` → copied 4 files, proxy restarted;
> `/api/version` → `les_version=0.24.0.288`,
> `deployed_les_version=0.24.0.288`, stamp ok, hash_mismatch_files=[].
> Runtime DB cleanup: raw CAD/BIM `.dwg/.dxf/.rvt/.rfa/.ifc/.ifczip/.nwc`
> entries in `ERROR`/`PENDING` converted to `SKIPPED` (`453` rows);
> post-check raw CAD/BIM `ERROR=0`, documents API accepts
> `status=SKIPPED`.
>
> 0.24.0.287 — chat validator fail-open final
>
> Дата: 2026-07-07
> Статус: deployed to runtime точечно (`proxy/routers/chat.py`,
> `proxy/services/version_service.py`), без полного bundle
> Причина: даже после снятия scope/empty-retrieval stop финальный слой SafeRAG
> мог заменить уже полученный модельный ответ на TOSKA fallback при
> `UNKNOWN`/`HALLUCINATION`, либо уйти в повторный строгий прогон. Это снова
> превращало инженерный вопрос в отказ/таймаут.
> Правки: `/api/chat` больше не вызывает `final_answer_for_status` как
> финальный фильтр видимого ответа. Новый локальный helper
> `_chat_model_final_answer` чистит текст, но сохраняет непустой модельный
> ответ; статусы `UNKNOWN`/`HALLUCINATION` понижаются до `UNVALIDATED`, а trace
> получает `final_answer_policy=chat_model_final_preservation_v1`.
> Если валидатор вернул непринятый статус после непустого ответа и
> `TOSKA_FAIL_OPEN=true`, чат завершает попытку как `UNVALIDATED` вместо
> дорогого retry.
> Проверки: `python3 -m compileall -q proxy/routers/chat.py
> proxy/services/version_service.py tests/test_chat_harness_format.py` → ok;
> `uv run pytest tests/test_chat_harness_format.py::test_chat_model_final_answer_preserves_text_on_validator_block
> tests/test_chat_harness_format.py::test_chat_model_final_answer_preserves_hallucination_label_as_warning
> tests/test_scope_clarification_v22.py -q` → ok;
> `git diff --check -- proxy/routers/chat.py proxy/services/version_service.py
> tests/test_chat_harness_format.py docs/RELEASE_LEDGER.md docs/CODE_MAP.md
> docs/MODULE_INDEX.md` → ok. Live deploy:
> `uv run python -m tools.deploy_to_runtime --apply --restart --force --files
> proxy/routers/chat.py proxy/services/version_service.py` → copied 2 files,
> proxy restarted, `/api/version` → `0.24.0.287`, deploy stamp ok.
> Полный `make test`/`make verify` не запускались: оператор попросил не гонять
> долгие тесты в этом цикле.
> Остаточный риск/TODO: deterministic tool-finals для явных table/mail/field/
> reconcile/doc-review команд остаются, потому что это инструментальные ветки;
> если они начнут перехватывать обычный вопрос, резать надо их policy-гейтом,
> не предметным шаблоном.

> 0.24.0.286 — model-first chat unthrottle
>
> Дата: 2026-07-06
> Статус: deployed to runtime точечно (`proxy/routers/chat.py`,
> `proxy/services/version_service.py`,
> `proxy/services/electrical_evidence_summary_service.py`), полный bundle не
> выкатывался
> Причина: защитные слои начали душить модель: проектный вопрос при `scope=all`
> мог завершаться `scope_clarification`, пустой retrieval — generic `NO_DATA`,
> а electrical summary отдавал тысячи gap rows как будто это инженерный verdict.
> На живом сценарии это ломало “расскажи про котельную” и давало отписки вместо
> модельного инженерного разбора.
> Правки: `chat.py` больше не возвращает финальный `scope_clarification` для
> обычных проектных вопросов — warning `scope_all_for_project_query` остаётся
> только в trace, дальше идут RAG/модель. Generic empty retrieval больше не
> возвращает кодовый `Нет данных в выбранных источниках`; он помечается
> `empty_retrieval_model_first_v1` и продолжает к модели с памятью/навигацией
> (точный `target_file` mismatch/ambiguity по-прежнему уточняется кодом).
> Unified construction harness visible final оставлен только за явным
> `LES_UNIFIED_CONSTRUCTION_HARNESS_FINAL_ENABLED=1`.
> RAG prompt ослаблен с “только найденные материалы” до model-first: не выдумывать
> числа/источники, но и не превращать неполный поиск в отказ.
> `electrical_evidence_summary_v1` теперь model-facing navigation: добавлены
> `model_reading_contract`, `source_navigation`, `issue_counts`, а `issues` —
> только capped examples с семантикой extractor gap, не design/code verdict.
> Реальный `tmp/electrical_pd_ic_20260706/evidence_summary.json` обновлён:
> полный `issue_count=3845`, но в prompt-facing `issues` только 24 примера,
> `source_navigation=6`.
> Проверки: `python3 -m compileall -q proxy/routers/chat.py
> proxy/services/electrical_evidence_summary_service.py
> tests/test_scope_clarification_v22.py
> tests/test_electrical_evidence_summary_service.py` → ok;
> `uv run pytest tests/test_scope_clarification_v22.py
> tests/test_electrical_evidence_summary_service.py
> tests/test_deterministic_policy_v18.py
> tests/test_project_summary_inventory.py -q` → `60 passed`;
> `make verify` → ok (`2583 tests collected`). Live deploy:
> `uv run python -m tools.deploy_to_runtime --apply --restart --force --files
> proxy/routers/chat.py proxy/services/version_service.py
> proxy/services/electrical_evidence_summary_service.py` → copied 3 files,
> proxy restarted, `/api/version` → `0.24.0.286`, deploy stamp ok.
> Полный `make test` не запускался: оператор попросил не гонять получасовую
> сюиту.
> Post-deploy smoke: `tools/basic_function_smoke.py` → P0 ok, 8/9 passed,
> P1 `chat_project_noscope` timed out at 120s. Это подтверждает, что старый
> мгновенный кодовый stop снят и запрос пошёл в модель, но latency полного
> model answer для “расскажи про котельную” надо отдельно ограничить без
> возврата шаблонного отказа.
> Остаточный риск/TODO: сделать быстрый bounded model-first ответ для широких
> проектных вопросов без финального `scope_clarification`/`NO_DATA` fallback.

> 0.24.0.285 — electrical evidence summary and gap layer
>
> Дата: 2026-07-06
> Статус: dev only, runtime не обновлялся
> Причина: после извлечения таблиц нагрузок, схемных кандидатов и ВОР/СО нужен
> слой “что есть / чего не хватает”: агрегаты по щитам, inventory кабелей и
> оборудования, SO→draft ВОР seeds, дырки по кабелю/аппарату/длине/марке.
> Правки: добавлены `electrical_evidence_summary_service` и CLI
> `tools/electrical_evidence_summary.py`. Контракт
> `electrical_evidence_summary_v1` принимает уже готовые manifest JSON и отдаёт
> `load_aggregates_by_panel`, `cable_inventory`, `equipment_inventory`,
> `load_to_material_cable_matches`, `so_to_vor_seeds`, `issues`.
> Из имени файлов `Таблица расчета нагрузок ГРЩ1/ГРЩ2` берётся честный
> `panel_source=file_name`, если в строках таблицы нет отдельной колонки щита.
> В `ALGO-electrical-schematics.md` записана полная карта извлечения: состав
> тома/шифры/ПЗ-навигация, planned ПЗ-решения, ЭОМ/ЭС tables/labels, ВОР/СО
> materials и summary/gap layer.
> Реальный прогон ПД ИЦ: `tmp/electrical_pd_ic_20260706/evidence_summary.json`
> и `.md`. Сводка: 1727 load rows, 209 candidate circuits, 678 material rows,
> 55 cable material rows, 394 SO rows, 284 VOR rows, 386 SO→VOR seed rows.
> После panel hint и фикса `КунРс Внг(А)-FRLS` issue_count=3845: 1727 load rows без cable, 1727 без
> protection, 206 circuit missing cable, 181 circuit missing protection,
> 1 material cable missing mark, 3 circuit missing cable length.
> Проверки: `uv run pytest tests/test_electrical_evidence_summary_service.py -q`
> → `3 passed`; `uv run pytest tests/test_electrical_evidence_summary_service.py
> tests/test_electrical_materials_service.py tests/test_electrical_schematic_service.py -q`
> → `17 passed`; `uv run pytest tests/test_electrical_materials_service.py
> tests/test_electrical_evidence_summary_service.py -q` → `10 passed`;
> `python3 -m compileall -q proxy/services/electrical_evidence_summary_service.py
> tools/electrical_evidence_summary.py tests/test_electrical_evidence_summary_service.py`
> → ok; `uv run python tools/electrical_evidence_summary.py --help` → ok;
> `make verify` → ok (`2581 tests collected`). Полный `make test` не запускался:
> оператор попросил не гонять получасовую сюиту.
> Остаточный риск/TODO: это presence/gap layer, не row-level reconciliation.
> Следующий шаг — matcher по panel/line/consumer/cable и ПЗ-project-decisions
> extractor.

> 0.24.0.284 — electrical materials technical attributes
>
> Дата: 2026-07-06
> Статус: dev only, runtime не обновлялся
> Причина: ВОР и СО не надо суммировать. Следующая задача — уметь сверять
> ВОР↔СО и делать draft ВОР из СО/спецификации, поэтому строкам ведомостей
> нужны технические признаки и роль документа.
> Правки: `electrical_materials_service` расширяет строки
> `electrical_material_manifest_v1`: `doc_role` (`vor`/`so`), `work_action`,
> `ip_rating`, `rated_current_a`, `voltage_v`, `voltages_v`, `rated_power_w`,
> `rated_power_kw`, `rated_reactive_power_kvar`, `install_height_m`,
> `cable_diameter_mm`, `dimensions_mm`, `unit_mass_kg`, `total_mass_kg`.
> Задачи записаны в `ALGO-electrical-schematics.md`: сверка ВОР↔СО
> (`missing-in-VOR`, `missing-in-SO`, quantity/attribute mismatch) и
> СО→draft ВОР без выбора норм кодом.
> Реальный прогон ПД ИЦ обновил `tmp/electrical_pd_ic_20260706/materials/*.json`
> и `summary.md`: `ИОС.ЭС-ВОР` сохранил 284 rows/26 cable rows/36 690 м и
> дополнительно дал 182 work actions, 118 IP, 15 токов, 3 напряжения, 16 W,
> 2 kVAr, 33 высоты монтажа, 44 dкаб, 119 габаритов, 84 удельные/общие массы;
> `ИОС.ЭС-СО` сохранил 394 rows/29 cable rows/84 460 м и дал 41 IP, 25 токов,
> 7 напряжений, 16 W, 2 kVAr, 7 габаритов, 39 type marks, 214 product codes,
> 379 suppliers.
> Проверки: `uv run pytest tests/test_electrical_materials_service.py -q`
> → `6 passed`; `uv run pytest tests/test_electrical_materials_service.py
> tests/test_electrical_schematic_service.py -q` → `13 passed`;
> `python3 -m compileall -q proxy/services/electrical_materials_service.py
> tests/test_electrical_materials_service.py` → ok; `make verify` → ok
> (`2577 tests collected`); `make test` → `2577 passed, 6 warnings in 281.60s`.
> Остаточный риск/TODO: нужен matcher ВОР↔СО и генератор draft ВОР из СО,
> но без code-side выбора ГЭСН/норм.

> 0.24.0.283 — electrical VOR/SO materials reader
>
> Дата: 2026-07-06
> Статус: dev only, runtime не обновлялся
> Причина: длины кабелей не читаются как `L/длина` на однолинейках и в таблицах нагрузок
> ПД ИЦ, но присутствуют в ВОР/СО как строки `м`. Нужен отдельный evidence-layer
> для ведомостей, а не попытка угадать длины по графике.
> Правки: добавлен `electrical_materials_service` и CLI `tools/electrical_materials.py`.
> Новый `electrical_material_manifest_v1` нормализует таблицы ВОР/СО:
> `position/name/unit/quantity/section/source_ref`, чинит PDF mojibake в СО,
> классифицирует строки `cable/panel/lighting/containment/busbar/protection/equipment`,
> вытаскивает `cable_mark`, `cable_cores`, `cable_section_mm2`, `quantity_m`.
> Реальный прогон ПД ИЦ: `tmp/electrical_pd_ic_20260706/materials/*.json`,
> сводка `tmp/electrical_pd_ic_20260706/materials/summary.md`.
> Результат: `ИОС.ЭС-ВОР` → 284 rows, 26 cable rows, 36 690 м кабеля,
> 5 panel rows, 31 lighting rows, 58 containment rows, 6 busbar rows;
> `ИОС.ЭС-СО` → 394 rows, 29 cable rows, 84 460 м кабеля,
> 95 panel rows, 26 lighting rows, 63 containment rows, 5 busbar rows.
> ВОР и СО не суммируются как общий итог без workflow-решения: это разные
> роли документов.
> Проверки: `uv run pytest tests/test_electrical_materials_service.py tests/test_electrical_schematic_service.py -q`
> → `11 passed`; `python3 -m compileall -q proxy/services/electrical_materials_service.py
> tools/electrical_materials.py tests/test_electrical_materials_service.py` → ok;
> `uv run python tools/electrical_materials.py --help` → ok; `make verify` → ok
> (`2575 tests collected`); `make test` → `2575 passed, 6 warnings in 279.15s`.
> Остаточный риск/TODO: следующий слой — связать `load_rows` из таблиц
> нагрузок с кабельными строками ВОР/СО по щитам/линиям/потребителям.

> 0.24.0.282 — PD IC electrical real-run fixes
>
> Дата: 2026-07-06
> Статус: dev only, runtime не обновлялся
> Причина: реальный прогон ПД ИЦ (`5.1. ЭС и ЭО / 5.1.1. Здание ИЦ`) показал две проблемы:
> типовые таблицы расчёта нагрузок имеют 11 колонок с потерянными PDF-подзаголовками
> `Pр/Qр/Sр/Iр`, а panel-regex принимал слово `ручки` за `РУ`.
> Правки: `electrical_schematic_service` теперь распознаёт 11-колоночную форму
> расчёта нагрузок (`Pуст`, `Pр`, `Qр`, `Sр`, `Iр`) и выкидывает строку
> нумерации колонок; panel-кандидаты дополнительно фильтруются от обычных
> lowercase-слов. Прогнаны 5 PDF: основной `ИОС.ЭС`, `ВОР`, `СО`,
> `Таблица расчета нагрузок ГРЩ1`, `Таблица расчета нагрузок ГРЩ2`.
> Артефакты: `tmp/electrical_pd_ic_20260706/*.json`, сводка
> `tmp/electrical_pd_ic_20260706/summary.md`.
> Результат прогона: основной том 242 стр. → 183 single-line pages, 150
> candidate circuits; таблицы ГРЩ1/ГРЩ2 → 31 таблица, 1727 строк нагрузок,
> 1312 строк с `Pр/Iр`. Длины кабелей не извлечены (`0`): в этих PDF нет
> читаемой колонки/подписи `L`/`длина`; вероятно, длины сидят в графике,
> ВОР или требуют отдельного table/OCR-слоя.
> Проверки:
> - `uv run pytest tests/test_electrical_schematic_service.py -q` → `7 passed`
> - `make verify` → ok (`2571 tests collected`)
> - `make test` → `2571 passed, 6 warnings in 275.23s`
> Остаточный риск/TODO: добавить специализированный extractor для кабельных
> строк ВОР/СО и геометрическую/OCR-привязку длин кабеля к линиям схем.

> 0.24.0.281 — electrical single-line/load reader MVP
>
> Дата: 2026-07-06
> Статус: dev only, runtime не обновлялся
> Причина: реальный ЭОМ/ИОС.ЭС нельзя читать как табличные однолинейки. Нужен отдельный
> source-backed reader: графическая схема + таблица расчёта нагрузок + длины кабелей.
> Правки: добавлен `electrical_schematic_service` и CLI `tools/electrical_schematic.py`.
> Manifest `electrical_schematic_manifest_v1` читает PDF text blocks, vector line primitives,
> text nodes (`panel/protection/cable/line`), candidate circuits и normalized load rows.
> `cable_length_m` стал отдельным полем и для подписи на схеме (`L=35 м`), и для таблиц расчёта
> нагрузок (`L, м`/`длина`). Добавлен словарь `config/domain/electrical_schema_terms.yaml`:
> `Руст/Pуст` → `p_installed_kw` (установленная мощность), `Рр/Pр` → `p_calc_kw`,
> `Iр` → `i_calc_a`, `L/длина` → `cable_length_m`. Сервис и словарь добавлены в
> runtime-alignment bundle.
> Проверки:
> - `uv run pytest tests/test_electrical_schematic_service.py -q` → `5 passed`
> - `make verify` → ok (`2569 tests collected`)
> - `make test` → `2569 passed, 6 warnings in 280.43s`
> Остаточный риск/TODO: нужен прогон на реальных листах `ИОС.ЭС` и накопление словаря
> обозначений/false positives; пока геометрическая топология не утверждается без читаемых подписей.

> 0.24.0.280 — explicit ГОСТ Р 21.101-2026 source for doc-review retrieval
>
> Дата: 2026-07-06
> Статус: dev only, runtime не обновлялся
> Причина: live `NTD_SPDS_Index` уже содержит актуальный ГОСТ Р 21.101-2026, но retrieval-подфаза
> doc-review брала `requirement.snippet` из проверяемого проектного датасета. Это смешивало
> "где проверяем факты комплекта" и "откуда берём текст нормы".
> Правки: `doc_review_retrieval_service` теперь отдельно ищет факты корпуса в project dataset
> (устаревший ГОСТ 2020, стадия ПД/РД) и текст требования в нормативном SPDS RAG:
> env `LES_NORMCONTROL_SPDS_DATASET_IDS`, затем auto-discovery датасетов с `ГОСТ Р 21.101-2026`
> в `NTD_SPDS_Index`/доменах `NTD_SPDS`/`NTD_GENERAL`. Если нормативный источник настроен, проектный
> датасет не используется как fallback для `requirement`; legacy fallback остаётся только для стендов
> без найденного нормативного dataset. `doc_review_retrieval_service.py` добавлен в critical
> runtime-alignment bundle.
> Проверки:
> - `python3 -m compileall -q proxy/services/doc_review_retrieval_service.py tests/test_doc_review_retrieval.py` → ok
> - `uv run pytest tests/test_doc_review_retrieval.py -q` → `14 passed`
> - `uv run pytest tests/test_doc_review_retrieval.py tests/test_doc_review_gost_21_101_2026.py tests/test_doc_review_chat_tool.py tests/test_doc_review_api.py tests/test_normcontrol_service.py tests/test_version_service_v19.py -q` → `68 passed`
> - `make verify` → ok (`2564 tests collected`)
> - `make test` → `2564 passed, 6 warnings in 292.66s`
> - live `/api/version` → `les_version=0.24.0.276`, `deployed_les_version=0.24.0.276`,
>   `runtime_alignment.status=divergent`
> Остаточный риск/TODO: live proxy всё ещё 0.24.0.276 до `make ship`; после деплоя нужен live
> doc-review smoke на проектном датасете с source_ref требования из `NTD_SPDS_Index`.

> 0.24.0.279 — ГОСТ Р 21.101-2026 as PD/RD normative source
>
> Дата: 2026-07-06
> Статус: dev only для кода/доков; live RAG source обновлён без деплоя proxy
> Причина: ГОСТ Р 21.101-2026 сам по себе является базовым источником для
> нормоконтроля, штампов, ведомостей, комплектования ПД/РД, шифров, изменений
> и электронных пакетов. В PD/RD source-map он должен быть первым нормативным
> профилем вместе с ПП N 87, а не случайной справкой в промпте.
> Правки: добавлен `docs/PD_RD_REGULATORY_BASE.md`, в `PD_RD_RAG_MINI_PRODUCT`
> и `MODULE_INDEX` закреплено, что актуальный профиль использует ПП N 87 и
> ГОСТ Р 21.101-2026. Уточнены сущности: раздел/подраздел/часть/книга/том,
> шифры ПД, формы основных надписей 3/5/6, графы штампа, состав ПД по форме 13,
> RD main set + attached docs.
> Live RAG: скачан PDF ГОСТ Р 21.101-2026, добавлен в `NTD_SPDS_Index`
> (`dataset_id=10ccce5f-99c5-4231-b1ff-0a2115371859`,
> `doc_id=7177fcf6-631e-4e21-bf07-2a3f5ea77b0b`), проиндексирован через
> `parse-scheduler` одним batch: `127` chunks, `files_parsed=1`, `errors=0`.
> Старый `ГОСТ Р 21.101-2020.docx` в датасете оставлен как исторический
> источник; актуальные проверки должны таргетить 2026.
> Проверки:
> - `curl /api/documents/datasets/.../documents?q=21.101-2026` → `INDEXED`, `chunk_count=127`
> - `POST /api/search` по “основные надписи форма 3 форма 5 форма 6” → top hit page 18, `quality_status=good`
> - `POST /api/search` по “состав проектной документации номер тома форма 13” → top hit page 34, `quality_status=good`
> - `git diff --check -- docs/PD_RD_REGULATORY_BASE.md docs/PD_RD_RAG_MINI_PRODUCT.md` → ok
> Остаточный риск/TODO: memory guard был в CRITICAL (`ram_free_gb≈5.3`,
> `swap_pct≈82` после batch), поэтому дальнейший mass-parse не запускался.
> Следующий кодовый слой — сделать ГОСТ 21.101-2026 explicit rulepack/source
> для `doc_review_retrieval_service` и `normcontrol_service`, а не только
> общим NTD-документом.

> 0.24.0.278 — PD/RD manifest for RAG
>
> Дата: 2026-07-06
> Статус: dev only, runtime не обновлялся
> Причина: для ПД/РД в RAG нужен слой source-map до чанков: модель должна
> видеть состав проекта, состав тома и оглавление ПЗ как навигацию, а не
> искать это в случайных фрагментах. `ПЗ` трактуется только как тип документа
> "пояснительная записка"; домен берётся из шифра (`ИОС.ЭС`), а темы — из
> оглавления ПЗ.
> Правки: добавлен `proxy/services/pd_rd_manifest_service.py` и CLI
> `tools/pd_rd_manifest.py`. Новый `pd_rd_manifest_v1` использует sheet
> manifest и строит `volume_contents_register_v1`,
> `project_composition_register_v1`, `pz_toc_v1`, compact `sheet_summary`,
> source refs и warnings. `Содержание тома` читается многостранично, а не
> только по первой странице; `Состав проектной документации` получает второй
> PDF-mojibake repair-pass для glyph-слоя вида `ɋɉ`→`СП`, `ɂɈɋ`→`ИОС`.
> Это read-only navigation layer: без LLM, без reindex, без финального ответа
> за модель и без интерпретации графических схем.
> Проверки:
> - `uv run pytest tests/test_pd_rd_manifest_service.py tests/test_drawing_manifest_service.py -q` → `12 passed`
> - `make verify` → ok (`2561 tests collected`)
> - real spot-check на
>   `5. ИОС/2_PDF/5.1. ЭС и ЭО/5.1.1. Здание ИЦ/395.01-B481.120100.2.4-ИОС.ЭС.pdf`
>   → `volume_contents_register.row_count=92` на страницах `5-8`,
>   `declared_total_sheets=242`; `project_composition_register.row_count=49`
>   на страницах `9-12`, включая `5.1.1 ИОС.ЭС`, `5.5.5 ИОС.СС5`,
>   `11 СМ`; `pz_toc.row_count=32` на странице `13`.
> Остаточный риск/TODO: в хвосте `Прилагаемые документы` ещё есть шум от
> многострочных названий приложений; следующий слой — merge continuation lines
> и сверка `volume_contents_register` ↔ фактические штампы листов.

> 0.24.0.277 — drawing sheet manifest MVP
>
> Дата: 2026-07-06
> Статус: dev only, runtime не обновлялся
> Причина: для отдельного pipeline чертежей нужен первый проверяемый слой
> навигации: не понимать весь лист, а собрать паспорт листа по стабильным
> признакам СПДС/ЕСКД — формат A4-A0/кратный, штамп справа снизу, текстовые
> блоки и шифр как ключ группировки.
> Правки: добавлен `proxy/services/drawing_manifest_service.py`. Сервис
> read-only читает PDF через PyMuPDF, режет ожидаемую правую нижнюю зону
> штампа, возвращает positioned text blocks, кандидаты `object_name`,
> `object_address`, `volume`, `cipher`, `stage`, `sheet_no`, `sheet_count`
> с `source_ref`/`confidence`, нормализует `cipher_norm` и группирует страницы
> по шифру. Если объект/название листа в штампе идут строками после шифра без
> явных меток, сервис добавляет structural-кандидаты с пониженной уверенностью.
> Для реальных PDF с кириллическим text-layer mojibake добавлен repair-pass
> cp1251→Unicode до извлечения полей. Batch-реестр
> `drawing_manifest_registry_v1` собирает PDF по `cipher_norm` и показывает
> `no_cipher`, `no_stamp`, `cipher_conflicts`. Штампы текстовой и графической
> частей теперь читают `stage`, `sheet_no`, `sheet_count`, `source_file_name`,
> `declared_format`; рыхлые шифры графики вида `...- ИОС .ЭС`
> нормализуются в `...-ИОС.ЭС`. `Содержание тома` извлекается как
> `volume_contents_row_v1`: обозначение, название, примечание, section,
> `sheet_no`/`sheet_count`, `source_ref`; это заявленный реестр состава тома
> для будущей сверки с фактически найденными листами. CLI
> `tools/drawing_manifest.py` даёт консольные рычаги `scan-path` и
> `scan-dataset` через Documents API. Код не вызывает модель, не делает
> reindex и не выдаёт финальный пользовательский ответ.
> Проверки:
> - `uv run pytest tests/test_drawing_manifest_service.py -q` → `10 passed`
> - `make verify` → ok (`2559 tests collected`)
> - read-only spot-check на случайном PDF из `ПД_Инновационный центр`:
>   `5. ИОС/2_PDF/5.5. СС/.../395.01-В481.120100.6.4-ИОС.СС4.ВОР.pdf`
>   → формат `А4`, штамп найден справа снизу, из штампа извлечён
>   `395.01/В481.120000.6.4-ИОС.СС4.ВОР`, из имени файла отдельный кандидат
>   `395-01-В481-120100-6-4-ИОС-СС4`; расхождение сохранено как provenance,
>   а не скрыто нормализацией.
> - read-only spot-check на ЭОМ/ЭО:
>   `5. ИОС/2_PDF/5.1. ЭС и ЭО/5.1.1. Здание ИЦ/395.01-B481.120100.6.4-ИОС.ЭС-СО.pdf`
>   → формат `А3`, 16 страниц, после mojibake repair штамп читается, найден
>   `volume=5. ИОС`, `object_name=Здание инновационного центра`,
>   `sheet_title=Система электроснабжения...`, `cipher_norm=395.01/B481.120100.6.4-ИОС.ЭС.СО`.
> - read-only spot-check на томе
>   `5. ИОС/2_PDF/5.1. ЭС и ЭО/5.1.1. Здание ИЦ/395.01-B481.120100.2.4-ИОС.ЭС.pdf`:
>   страница 5 дала `volume_contents=27` строк (`ПЗ`, графическая часть,
>   `ГРЩ/ЩЭ/ЩР` с листами); страница 84 дала
>   `cipher_norm=395.01/B481.120100.1.4-ИОС.ЭС`, `stage=П`,
>   `sheet_no=24.1`, `sheet_count=7`, `object_name=Здание инновационного центра`,
>   `sheet_title=ЩО 1.1.1. Схема электрическая принципиальная`,
>   `source_file_name=395_01_B481_120100_1_4_IOS_ES_24_00.dwg`,
>   `declared_format=А3х3`; страница 85 дала continuation-штамп
>   `sheet_no=24.2`, `source_file_name=...dwg`, `declared_format=A3`.
> - CLI smoke: `uv run python tools/drawing_manifest.py scan-dataset <ПД_ИЦ> --q ЭО --limit 3 --max-pages-per-pdf 1`
>   → `files_read=3`, `pages_read=3`, `ciphers_total=3`, найдены группы
>   `395-01-B481-120100-2-4-ИОС`,
>   `395.01/B481.120100.6.4-ИОС.ЭС.ВОР`,
>   `395.01/B481.120100.6.4-ИОС.ЭС.СО`, issues: `no_stamp=1`,
>   `cipher_conflicts=2`.

> 0.24.0.276 — FGIS work-steps backfill path
>
> Дата: 2026-07-06
> Статус: deployed to runtime 2026-07-06, deploy stamp ok; overnight backfill running under launchd
> Причина: `0.24.0.275` научил norm-card показывать `work_composition`, но
> существующая runtime база была залита раньше без `work_steps`. Официальный
> ФГИС ЦС `SearchEstimatedRates` уже отдаёт `normCatalogWorkTableJson` —
> состав работ по `NormNumber`.
> Правки: `tools/gesn_pdf_import.py::parse_fgis_json` сохраняет
> `normCatalogWorkTableJson` в поле `work_steps` каждой ресурсной строки нормы.
> Это источник данных для модели, не правило выбора нормы. Начата дозаливка
> runtime parquet: сборник 15 закрыт без ошибок; сборник 08 закрыт без ошибок;
> следующий шаг — ночной `--all --no-resume` backfill в фоне с логом, без
> Qdrant/RAG reindex.
> Проверки:
> - `uv run pytest tests/test_gesn_pdf_import.py tests/test_gesn_import.py tests/test_smeta_norm_store.py -q` → `22 passed`
> - runtime `/api/version` → `les_version=0.24.0.276`, deploy stamp ok, `hash_mismatch_files=[]`
> - runtime spot-check после дозаливки сборника 15: `15-02-036-02`,
>   `15-01-052-01`, `15-01-054-01` читаются через `gesn_service.get_norm(...)`
>   с непустыми `work_steps`
> - runtime spot-check после дозаливки сборника 08: `ГЭСНм08-05-041-01`,
>   `ГЭСНм08-03-641-06`, `ГЭСНм08-01-125-01`, `ГЭСНм08-03-545-06`
>   читаются с непустыми `work_steps`
> - night backfill: `launchctl submit` label
>   `me.ovc.les.gesn.worksteps.backfill.20260706`, log
>   `/tmp/les_gesn_work_steps_backfill_launchd_20260706.log`, command:
>   `uv run python -u -m tools.gesn_bulk_import --all --no-resume --rate 0.5 --out /Users/ovc/LES/data/gesn_base/gesn2022.parquet`.
>   Это обновляет только parquet, без Qdrant/RAG reindex; после завершения нужен proxy restart.

> 0.24.0.275 — smeta norm work-composition cards
>
> Дата: 2026-07-06
> Статус: deployed to runtime 2026-07-06, deploy stamp ok
> Причина: в БАП модель не видела настоящий `Состав работ` нормы: быстрый
> `search_norm -> structured norm-choice` передавал title/unit/resources/hints,
> но не пункты состава работ. Из-за этого выбор шёл по похожему названию и
> слабым hints, а не по технологическому содержанию нормы.
> Правки: `tools/gesn_import.py`/`gesn_api_service` получили поле `work_steps`;
> `gesn_service` читает его из parquet; `smeta_norm_store_v5` поднимает
> `work_steps` в `model_card.work_composition.steps` и дополнительно умеет
> читать `## Состав работ` из
> `RAG_Content/TABLE_SMETA/SMETA_SERVICE/smetnoedelo_api/**/codes/*.md`.
> `_smeta_norm_candidate_card` больше не выкидывает title/work_composition, а
> structured norm-choice сверяет их моделью. Код по-прежнему не выбирает нормы:
> он только доставляет источник состава работ модели и считает после видимого
> выбора.
> Проверки:
> - `uv run pytest tests/test_gesn_api_service.py tests/test_smeta_norm_store.py tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_gets_norm_card_and_mismatch_rule -q` → `13 passed`
> - `uv run pytest tests/test_gesn_import.py tests/test_gesn_pdf_import.py tests/test_gesn_api_service.py -q` → `13 passed`
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_gets_norm_card_and_mismatch_rule tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_keeps_unreturned_lookup_as_unbound_row tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_validates_model_code_from_lookup -q` → `3 passed`
> - `uv run pytest tests/test_gesn_api_service.py tests/test_smeta_norm_store.py tests/test_gesn_import.py tests/test_gesn_pdf_import.py tests/test_chat_harness_format.py tests/test_smeta_artifact_service.py -q` → `102 passed`
> - `make verify` → ok (`2548 tests collected`)
> - runtime `/api/version` → `les_version=0.24.0.275`, deploy stamp ok, `hash_mismatch_files=[]`
> - runtime norm store payload → `schema=smeta_norm_store_v5`, `norm_count=42572`, `work_composition` in `profile_fields`
> Примечание: простой переиндекс текущего SMETA_SERVICE не добавит составы,
> потому что в папке сейчас нет `smetnoedelo_api/codes/*.md`; нужен импорт/Play
> карточек норм с `## Состав работ` или обновление parquet с `work_steps`.

> 0.24.0.274 — smeta preserve unbound lookup rows
>
> Дата: 2026-07-06
> Статус: deployed to runtime 2026-07-06, deploy stamp ok
> Причина: после 0.24.0.273 модель перестала выбирать часть явно неверных
> норм, но structured norm-choice отдавал в `rows` только accepted строки.
> В live БАП это превратило 19-row lookup в 2-row ЛСР: непрошедшие строки
> исчезали вместо того, чтобы остаться в форме с `нужен подбор нормы`.
> Правки: `_smeta_direct_structured_norm_choice` теперь добавляет unbound row
> для каждого lookup, который модель не вернула, вернула без `norm_code`,
> вернула с кодом вне candidates или без количества. Это не выбор нормы кодом:
> код только сохраняет строку ВОР в ЛСР с `0.00`/пустыми полями и причиной.
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_keeps_unreturned_lookup_as_unbound_row tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_gets_norm_card_and_mismatch_rule tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_validates_model_code_from_lookup -q` → `3 passed`
> - `uv run pytest tests/test_chat_harness_format.py tests/test_smeta_artifact_service.py -q` → `79 passed`
> - `make verify` → ok (`2546 tests collected`)
> - runtime `/api/version` → `les_version=0.24.0.274`, deploy stamp ok, `hash_mismatch_files=[]`
> - live BAP PDF-read smoke, обычный запрос `Дай оценку стоимости и ЛСР`: lookup `source_rows_expected=19`, `results=19`, `coverage_missing=0`; structured choice `accepted=2`, `unbound_rows_added=17`, `rejected=17`; checked ЛСР `input_rows=19`, `bound_rows=2`, `unbound_rows=17`, сумма `1 963 434 руб.`. Плохие коды из пользовательской разметки (`ГЭСН15-02-036-02`, `ГЭСН15-01-052-01`, `ГЭСН15-01-054-01`, `ГЭСН08-05-041-01`) в видимую priced ЛСР не попали. Остаточный риск: coverage слишком низкий, нужен следующий слой качества norm retrieval/composition cards.

> 0.24.0.273 — smeta norm-choice card/mismatch guard
>
> Дата: 2026-07-06
> Статус: dev, готовится к runtime deploy
> Причина: БАП ЛСР после закрытия 19-row coverage всё ещё выбирала явно
> неверные нормы: защитное укрытие плёнкой → штукатурка по сетке, демонтаж
> кабеля → монтаж электропроводки, проём в ГКЛ → отверстия в натяжном/реечном
> потолке. Причина не в арифметике, а в выборе нормы: structured norm-choice
> видел только `norm_code/title/unit/score/status` и был прямо проинструктирован
> выбирать ближайший candidate даже при неполном совпадении.
> Правки: в norm lookup/choice payload добавлена компактная `norm_card`
> (`domain/actions`, conditions, resources, collection navigation). Prompt
> выбора нормы теперь требует сверять карточку и оставлять `norm_code` пустым,
> если candidate описывает другую операцию; `score` больше не permission to
> price a wrong norm. Norm-store action hints расширены для демонтажа,
> грунтования, шпатлевки и оклейки; search score штрафует очевидный конфликт
> действий вроде `демонтаж` vs `монтаж`.
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_gets_norm_card_and_mismatch_rule tests/test_chat_harness_format.py::test_smeta_action_title_score_penalizes_demolition_vs_installation tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_validates_model_code_from_lookup -q` → `3 passed`

> 0.24.0.272 — smeta PDF/Markdown VOR row coverage
>
> Дата: 2026-07-06
> Статус: deployed to runtime 2026-07-06, deploy stamp ok
> Причина: 0.24.0.271 проверил искусственный JSON/source_no path, но реальный
> пользовательский сценарий "скрепка read PDF -> Дай оценку стоимости и ЛСР"
> отдаёт модели Markdown-таблицу без JSON `source_no`. Поэтому coverage detector
> видел `source_rows_expected=0`, selector не получал контракт "19 строк ВОР" и
> модель могла снова выбрать только 10 lookup-групп.
> Правки: `_smeta_source_row_count` считает рабочие строки не только по
> `source_no`, но и по Markdown/PDF-таблице `| № | Наименование | Ед. | Кол-во |`.
> Source-row contract и norm lookup policy теперь говорят про табличную
> ВОР/PDF table/source_no, а не только про JSON. Это не выбор норм кодом:
> код только сохраняет входной row coverage, чтобы модель не теряла строки.
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_source_row_count_reads_markdown_pdf_vor_rows tests/test_chat_harness_format.py::test_smeta_norm_lookup_max_calls_does_not_cut_source_rows_to_ten tests/test_chat_harness_format.py::test_smeta_direct_prompt_requires_source_row_coverage_for_tabular_vor -q` → `3 passed`
> - real PDF converter output `/Users/ovc/Downloads/ВОР монтаж БАП П1 13.05.pdf` → `_smeta_source_row_count=19`, `_smeta_norm_lookup_max_calls=38`, selector tokens `4980`
> - `uv run pytest tests/test_chat_harness_format.py tests/test_smeta_artifact_service.py -q` → `76 passed`
> - `make verify` → ok (`2543 tests collected`)
> - runtime `/api/version` → `les_version=0.24.0.272`, deploy stamp ok, `hash_mismatch_files=[]`
> - live BAP PDF-read smoke, обычный запрос `Дай оценку стоимости и ЛСР` + `attachment_context` из PDF converter, без JSON: workflow `stage=pricing`, lookup `source_rows_expected=19`, `selected_calls=19`, `results=19`, `coverage_missing=0`, `max_calls=38`; visible checked ЛСР: `18/19` рассчитано, сумма `4 719 778 руб.`

> 0.24.0.271 — smeta lookup no ten-row cap
>
> Дата: 2026-07-06
> Статус: deployed to runtime 2026-07-06, deploy stamp ok
> Причина: полный БАП PDF содержит 19 строк ВОР, но norm lookup selector
> получал дефолтный `max_calls=10`, поэтому кодовая обвязка сама обрезала
> модельный `search_norm` plan до 10 групп. Это нарушало source-row coverage и
> давало красивую partial ЛСР вместо полной 19-строчной оценки.
> Правки: дефолт smeta norm lookup calls поднят до 30, а при наличии
> `source_no` технический лимит масштабируется от числа исходных строк
> (`source_rows * 2`, ceiling 300). Это не выбор норм и не stage logic, а
> removal of truncation: модель может покрыть все source rows, код больше не
> режет обычную ВОР до 10.
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_norm_lookup_max_calls_does_not_cut_source_rows_to_ten tests/test_chat_harness_format.py::test_smeta_workflow_decision_is_model_owned_pricing_reuse -q` → `2 passed`
> - `uv run python -m py_compile proxy/routers/chat.py` → ok
> - `uv run pytest tests/test_chat_harness_format.py tests/test_smeta_artifact_service.py -q` → `75 passed`
> - `make verify` → ok (`2542 tests collected`)
> - runtime `/api/version` → `les_version=0.24.0.271`, deploy stamp ok, `hash_mismatch_files=[]`
> - live BAP full-PDF smoke, stage 1 (`/Users/ovc/Downloads/ВОР монтаж БАП П1 13.05.pdf`, 19 ВОР rows extracted): `smeta_norm_lookup.source_rows_expected=19`, `selected_calls=19`, `results=19`, `coverage_missing=0`, `max_calls=38`
> - live BAP follow-up pricing in same session: model-owned workflow `stage=pricing`, `use_previous_candidates=true`, `previous_candidate_groups=19`; visible checked ЛСР: `18/19` рассчитано, сумма `3 790 263 руб.`

> 0.24.0.270 — smeta model-owned workflow decision
>
> Дата: 2026-07-06
> Статус: deployed to runtime 2026-07-06, deploy stamp ok
> Причина: в smeta direct route всё ещё оставался код, который “думал”:
> regex решал `norm_candidates` vs `pricing`, а другой regex решал, что
> “деньги по ним” надо привязать к предыдущим candidates. Это противоречило
> контракту “модель выбирает смысл/workflow, код исполняет”.
> Правки: добавлен model-owned `smeta_workflow_decision` JSON-step:
> `stage=norm_candidates|pricing|explanation`, `use_previous_candidates`.
> Live route больше не определяет stage regex-ом; при `pricing` и
> `use_previous_candidates=true` код только достаёт уже существующий candidate
> state и считает по нему. `explanation` не запускает norm choice / РИМ-расчёт.
> Regex-функции оставлены как legacy helpers/tests/rollback, но рабочий route
> по умолчанию управляется модельным workflow decision.
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_workflow_decision_is_model_owned_pricing_reuse tests/test_chat_harness_format.py::test_smeta_user_prompt_respects_model_explanation_stage tests/test_chat_harness_format.py::test_smeta_direct_followup_prefers_previous_candidate_trace tests/test_smeta_artifact_service.py::test_smeta_artifact_prefers_full_spb_pricebook_over_refresh_without_period -q` → `4 passed`
> - `uv run pytest tests/test_chat_harness_format.py tests/test_smeta_artifact_service.py -q` → `74 passed`
> - `uv run python -m py_compile proxy/routers/chat.py` → ok
> - `make verify` → compileall + pytest collect-only, `2541 tests collected`
> - runtime `/api/version` → `0.24.0.270`, deployed `0.24.0.270`, stamp `ok`
> - live explanation smoke: model chose `stage=explanation`,
>   `smeta_norm_lookup.status=workflow_stage_explanation`, norm choice blocked
>   by model workflow stage; no РИМ calculation.
> - live BAP workflow smoke: stage 1 → model-owned `norm_candidates`,
>   `lookup_results=5`; pricing #1/#2 → model-owned `pricing`,
>   `use_previous_candidates=True`, `lookup_results=5`, `reused_from_session=True`,
>   both totals `731 434.03`, `bound_rows=4`, `unbound_rows=1`.

> 0.24.0.269 — smeta candidate trace stability
>
> Дата: 2026-07-06
> Статус: deployed to runtime 2026-07-06, deploy stamp ok
> Причина: после 0.24.0.268 live BAP перестал быть нулевым, но повтор
> “Теперь деньги по ним” мог заново запускать `search_norm` по накопленной
> истории и получать другую нарезку ВОР: один pricing trace имел 9 lookup rows,
> другой 10 lookup rows. Это ломало повторяемость суммы ещё до выбора конкретных
> норм.
> Правки: для явных follow-up команд “деньги по ним / ЛСР по этим кандидатам”
> smeta route сначала переиспользует последний `smeta_norm_lookup.results` из
> session trace и не запускает новый lookup, если candidates уже есть. Модель
> по-прежнему выбирает `norm_code` из candidates; код только фиксирует тот же
> candidate set/source rows между повторами.
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_direct_prices_previous_candidates_request_detects_followup tests/test_chat_harness_format.py::test_smeta_direct_previous_norm_lookup_trace_reuses_latest_session_candidates tests/test_chat_harness_format.py::test_smeta_direct_followup_prefers_previous_candidate_trace tests/test_smeta_artifact_service.py::test_smeta_artifact_prefers_full_spb_pricebook_over_refresh_without_period -q` → `4 passed`
> - `uv run python -m py_compile proxy/routers/chat.py proxy/services/smeta_artifact_service.py` → ok
> - `uv run pytest tests/test_chat_harness_format.py tests/test_smeta_artifact_service.py -q` → `72 passed`
> - `make verify` → compileall + pytest collect-only, `2539 tests collected`
> - runtime `/api/version` → `0.24.0.269`, deployed `0.24.0.269`, stamp `ok`
> - live BAP stability smoke на новой сессии:
>   stage 1 → `norm_candidates`, `lookup_results=5`;
>   pricing #1 → `lookup_results=5`, `reused_from_session=True`,
>   `amount_total=268 193.44`, `bound_rows=4`, `unbound_rows=1`;
>   pricing #2 → те же `lookup_results=5`, `reused_from_session=True`,
>   `amount_total=268 193.44`.

> 0.24.0.268 — smeta SPb pricebook default fix
>
> Дата: 2026-07-06
> Статус: deployed to runtime 2026-07-06, deploy stamp ok
> Причина: live БАП pricing после “деньги по ним” вернул `0 руб.`, хотя
> `smeta_structured_rim_trace` имел `bound_rows=9`, `unbound_rows=0` и
> ненулевые трудозатраты. Trace показал, что расчёт ушёл в книгу
> `spb_refresh`; это scratch parquet на 2 строки, поэтому не находились ставки
> ОЗП, цены машин и материалы. Триггер: контекст БАП содержит `СПб`, но без
> явного периода; селектор для СПб ставил `spb_refresh` перед полноценной
> `spb_2kv2026`.
> Правки: для СПб без явного периода `smeta_artifact_service` теперь выбирает
> `spb_2kv2026` перед `spb_2kv2025` и только затем `spb_refresh`.
> Проверки:
> - те же 9 accepted BAP rows из live trace после фикса: книга `spb_2kv2026`,
>   `amount_total=10 663 956.52`, `bound_rows=9`, `unbound_rows=0`,
>   `result_status=priced_partial`.
> - `uv run pytest tests/test_smeta_artifact_service.py::test_smeta_artifact_prefers_full_spb_pricebook_over_refresh_without_period tests/test_smeta_artifact_service.py::test_smeta_artifact_uses_default_system_pricebook_without_region tests/test_smeta_artifact_service.py::test_smeta_artifact_prefers_rim_trace_when_model_selected_norm_code -q` → `3 passed`
> - `uv run pytest tests/test_smeta_artifact_service.py -q` → `16 passed`
> - `make verify` → compileall + pytest collect-only, `2538 tests collected`
> - runtime `/api/version` → `0.24.0.268`, deployed `0.24.0.268`, stamp `ok`
> - live `/api/chat` повтор “Теперь деньги по ним” в BAP-сессии:
>   `smeta_tz_stage=pricing`, книга `spb_2kv2026`, `amount_total=3 688 325.16`,
>   `bound_rows=10`, `unbound_rows=0`, `priced_partial`. Отличается от replay
>   старых 9 rows, потому что модель заново выбрала строки/нормы; нулевой
>   `spb_refresh` больше не воспроизводится.

> 0.24.0.267 — smeta continuation stage boundary
>
> Дата: 2026-07-06
> Статус: deployed to runtime 2026-07-06; live СКС/БАП smoke всё ещё fail на LLM model-call/selector
> Причина: live smoke 0.24.0.266 показал, что второй ход “Теперь деньги по ним”
> всё ещё мог уходить в `norm_candidates`, потому что stage detector смотрел
> на весь `harness_question` с историей, где уже были слова “дай кандидатов”.
> Правки: stage `norm_candidates` теперь определяется только по текущему
> сообщению/вложению (`_question_with_attachment(req)`), а не по истории
> диалога. История по-прежнему доступна модели и trace-continuity для “по ним”,
> но не может сама вернуть второй ход в этап 1.
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_direct_prices_previous_candidates_request_detects_followup tests/test_chat_harness_format.py::test_smeta_direct_previous_norm_lookup_trace_reuses_latest_session_candidates tests/test_smeta_artifact_service.py::test_norm_candidate_artifact_formats_lookup_trace_for_excel_roundtrip -q` → `3 passed`
> - `uv run pytest tests/test_skill_snippet_registry.py tests/test_smeta_module.py tests/test_prompt_registry_service.py tests/test_chat_harness_format.py tests/test_smeta_artifact_service.py tests/test_estimate_harness.py tests/test_rim_lsr_trace_service.py tests/test_v020_deploy_stamp_ui.py -q` → `215 passed`
> - deployed runtime `/api/version` → `0.24.0.267`, deploy stamp `ok`
> - live СКС/БАП smoke на активном `mlx-community/Qwen3.5-9B-MLX-4bit`:
>   - СКС ход 1 → `norm_candidates`, candidates artifact/XLSX есть, но финальный LLM-текст пустой (`PARTIAL`).
>   - СКС ход 2 “деньги по ним” → `pricing`, previous lookup reused, но `structured_norm_choice` упал `selector_error`; ЛСР/суммы нет.
>   - БАП PDF ход 1/2 → LLM lookup/model-call failure, candidates artifact и ЛСР не построены.
>   Текущий effective provider: `mlx`, cloud key не активен (`api_key_present=false`). Следующий блокер — не арифметика, а LLM/provider reliability для selector/model JSON.

> 0.24.0.266 — smeta candidate trace continuity
>
> Дата: 2026-07-06
> Статус: dev, готовится к runtime deploy/smoke
> Причина: live СКС/БАП после 0.24.0.265 показал два runtime-gap:
> stage 1 мог уже выполнить `search_norm` и получить candidates, но при
> пустом финальном LLM-тексте возвращал только `smeta_model_failed` без
> artifact; ход “деньги по ним” мог сорваться на новом selector-error вместо
> использования предыдущего candidates trace из той же сессии.
> Правки: если stage `norm_candidates` уже имеет lookup results, но финальный
> LLM-текст не сгенерирован, чат возвращает partial candidates artifact/XLSX/CSV
> вместо пустого failure. Для pricing follow-up “деньги по ним / ЛСР по этим
> кандидатам” smeta route переиспользует последний `smeta_norm_lookup.results`
> из session trace, если текущий lookup пустой или selector failed. Код не
> выбирает нормы: модельный `structured_norm_choice` всё равно выбирает
> `norm_code` из candidates, а код только валидирует и считает.
> Проверки:
> - focused tests/deploy/live smoke будут зафиксированы ниже после прогона.

> 0.24.0.265 — smeta candidates-then-money default
>
> Дата: 2026-07-06
> Статус: deployed to runtime 2026-07-06, live two-step smoke прошёл
> Причина: UX-решение оператора: ручная Excel-проверка candidates не должна
> быть обязательным барьером. Базовый сценарий — сначала показать, что
> найдено, затем по команде “деньги по ним” считать по доступным candidates;
> чего нет, остаётся 0.00/пусто с примечанием.
> Правки: smeta direct prompt, TZ-stage context и `norm_candidates` artifact
> больше не требуют “ручной приемки/загрузки проверенного варианта” как
> обязательный следующий шаг. Stage 1 теперь формулирует следующий ход как:
> “деньги по ним”; Excel-правка остаётся опциональной. Расчётный слой не
> изменён: модель выбирает candidates, код раскрывает ресурсы/цены и считает,
> missing остаётся нулём/примечанием.
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_direct_prompt_does_not_block_on_empty_spec_price_columns tests/test_chat_harness_format.py::test_smeta_direct_prompt_keeps_norm_selection_model_first tests/test_chat_harness_format.py::test_smeta_direct_explicit_candidate_table_stays_stage_one tests/test_smeta_artifact_service.py::test_norm_candidate_artifact_formats_lookup_trace_for_excel_roundtrip -q` → `4 passed`
> - `uv run pytest tests/test_skill_snippet_registry.py tests/test_smeta_module.py tests/test_prompt_registry_service.py tests/test_chat_harness_format.py tests/test_smeta_artifact_service.py tests/test_estimate_harness.py tests/test_rim_lsr_trace_service.py tests/test_v020_deploy_stamp_ui.py -q` → `213 passed`
> - deployed runtime `/api/version` → `0.24.0.265`, deploy stamp `ok`
> - live `/api/chat/stream` smoke:
>   - ход 1 “Дай кандидатов ГЭСН” → `smeta_tz_stage=norm_candidates`, artifact `stage=norm_candidates`, downloads есть.
>   - ход 2 “Теперь деньги по ним” → `smeta_tz_stage=pricing`, `lsr_rim_trace_form_v1`, `82 767.02 руб.`, `rows=5`, downloads есть.

> 0.24.0.264 — smeta explicit candidate-table stage boundary
>
> Дата: 2026-07-06
> Статус: deployed to runtime 2026-07-06, live stage-1 artifact smoke прошёл
> Причина: live-smoke 0.24.0.263 показал, что запрос вида “сделай этап 1 /
> верни таблицу кандидатов ГЭСН по ВОР” не попадал в stage
> `norm_candidates`: predicate сначала требовал ЛСР/деньги, поэтому чистая
> проверочная таблица кандидатов уходила в pricing.
> Правки: явный запрос `таблица кандидатов` / `кандидаты ГЭСН` / `этап 1`
> при наличии ВОР/сырого источника теперь включает stage 1 сам по себе.
> Pricing по-прежнему разрешён только для проверенной таблицы с кодами норм
> или явного bypass “прими кандидатов модели / без ручной проверки”.
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_direct_explicit_candidate_table_stays_stage_one tests/test_chat_harness_format.py::test_smeta_direct_raw_vor_stops_at_norm_candidate_stage tests/test_chat_harness_format.py::test_smeta_direct_checked_norm_table_allows_pricing_stage tests/test_smeta_artifact_service.py::test_norm_candidate_artifact_formats_lookup_trace_for_excel_roundtrip -q` → `4 passed`
> - `uv run pytest tests/test_skill_snippet_registry.py tests/test_smeta_module.py tests/test_prompt_registry_service.py tests/test_chat_harness_format.py tests/test_smeta_artifact_service.py tests/test_estimate_harness.py tests/test_rim_lsr_trace_service.py tests/test_v020_deploy_stamp_ui.py -q` → `213 passed`
> - deployed runtime `/api/version` → `0.24.0.264`, deploy stamp `ok`
> - live `/api/chat/stream` smoke на сыром ВОР “этап 1 / таблица кандидатов ГЭСН” → `smeta_tz_stage=norm_candidates`, `smeta_norm_choice.status=blocked_by_tz_stage_gate`, artifact `stage=norm_candidates`, table `kind=norm_candidates`, `rows=10`, downloads XLSX/CSV отдают HTTP 200.

> 0.24.0.263 — smeta norm-candidate artifact/XLSX
>
> Дата: 2026-07-06
> Статус: deployed to runtime 2026-07-06; live-smoke нашёл boundary gap, закрыт в 0.24.0.264
> Причина: 0.24.0.262 правильно остановил сырой ТЗ/ВОР на этапе кандидатов
> ГЭСН, но пользователю нужен поставляемый результат, а не только текст:
> проверочная таблица кандидатов должна быть артефактом/XLSX для ручной
> приемки и повторной загрузки.
> Правки: `smeta_artifact_service` строит `norm_candidates` artifact из
> executed `search_norm` trace: колонки `№ ВОР`, исходная/нормируемая работа,
> единицы, группа сборников, сборник/раздел, код/наименование/единица ГЭСН,
> статус применимости и комментарий. `chat.py` в stage
> `norm_candidates` сохраняет именно этот artifact через существующий
> XLSX/CSV exporter. Код не выбирает финальную норму, не считает деньги и не
> скрывает строки без кандидатов: такие строки остаются в таблице с пустым
> кодом и примечанием.
> Проверки:
> - `uv run pytest tests/test_smeta_artifact_service.py tests/test_chat_harness_format.py -q` → `67 passed`
> - `uv run pytest tests/test_skill_snippet_registry.py tests/test_smeta_module.py tests/test_prompt_registry_service.py tests/test_chat_harness_format.py tests/test_smeta_artifact_service.py tests/test_estimate_harness.py tests/test_rim_lsr_trace_service.py tests/test_v020_deploy_stamp_ui.py -q` → `212 passed`
> - deployed runtime `/api/version` → `0.24.0.263`, deploy stamp `ok`
> - live `/api/chat/stream` smoke на формулировке “этап 1 / таблица кандидатов ГЭСН” вернул `smeta_tz_stage=pricing`, что неверно для чистой проверочной таблицы; regression зафиксирован и исправлен в 0.24.0.264.

> 0.24.0.262 — smeta TZ stage gate before pricing
>
> Дата: 2026-07-06
> Статус: deployed to runtime 2026-07-06, stage-gate smoke прошёл
> Причина: 0.24.0.261 доказал, что модель может дать живую ЛСР с деньгами, но
> это шло вразрез с ТЗ сметного модуля. По ТЗ default flow: сырой
> ТЗ/ВОР/спецификация -> таблица `ВОР ↔ кандидаты ГЭСН` -> ручная проверка в
> Excel -> загрузка проверенного варианта -> раскрытие ресурсов/ФГИС -> добор
> КАЦ/коэффициентов -> финальная смета. Runtime же сразу запускал structured
> norm-choice и checked РИМ-деньги.
> Правки: smeta direct получил stage gate. Если вход не содержит признака
> вручную проверенной таблицы соответствия ВОР-ГЭСН, structured norm-choice и
> checked `lsr_rim_trace_form_v1` не запускаются. Модель получает явный контракт
> этапа 1: выдать таблицу кандидатов норм для Excel round-trip без рублей,
> строки ВСЕГО и финального выбора одного `norm_code`. Pricing stage разрешён
> только для проверенной таблицы с полными кодами ГЭСН/ГЭСНм или по явной
> команде оператора принять candidates модели без ручной проверки.
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_direct_raw_vor_stops_at_norm_candidate_stage tests/test_chat_harness_format.py::test_smeta_direct_checked_norm_table_allows_pricing_stage tests/test_chat_harness_format.py::test_smeta_direct_prompt_requires_source_row_coverage_for_tabular_vor tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_validates_model_code_from_lookup -q` → `4 passed`
> - `uv run pytest tests/test_skill_snippet_registry.py tests/test_smeta_module.py tests/test_prompt_registry_service.py tests/test_chat_harness_format.py tests/test_smeta_artifact_service.py tests/test_estimate_harness.py tests/test_rim_lsr_trace_service.py tests/test_v020_deploy_stamp_ui.py -q` → `211 passed`
> - deployed runtime `/api/version` → `0.24.0.262`, deploy stamp `ok`
> - live `/api/chat/stream` smoke:
>   - raw СКС ВОР → `smeta_tz_stage=norm_candidates`, `amount_total=None`, `rows=0`, `smeta_norm_choice.status=blocked_by_tz_stage_gate`.
>   - проверенная таблица ВОР-ГЭСН (`ГЭСНм:10-01-052-07`) → `smeta_tz_stage=pricing`, `lsr_rim_trace_form_v1`, `4 047.15 руб.`, `bound_rows=1/1`.

> 0.24.0.261 — smeta direct piece-dimension quantity conversion
>
> Дата: 2026-07-06
> Статус: deployed to runtime 2026-07-06, live СКС/БАП smoke прошёл
> Причина: live БАП на 0.24.0.260 стал живой (`2.28–2.58 млн руб.`), но две
> строки по лючкам/проёмам выпадали как `unit_conflict`: модель выбрала
> `ГЭСН15-01-052-01` (`100 отверстий`) и `ГЭСН15-01-059-01` (`100 м2`), а
> исходная ВОР задавала `шт`.
> Правки: РИМ trace принимает `отверстия` как count alias и после модельного
> выбора нормы переводит поштучные элементы с габаритом вида `400x400 мм` в
> площадь (`шт × м2/шт / измеритель нормы`). Это арифметика количества, а не
> выбор нормы кодом.
> Проверки:
> - `uv run pytest tests/test_rim_lsr_trace_service.py::test_visible_rows_convert_piece_dimensions_to_area_norm_qty tests/test_rim_lsr_trace_service.py::test_visible_rows_accept_engineering_count_unit_aliases tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_validates_model_code_from_lookup -q` → `3 passed`
> - direct builder smoke: `ГЭСН15-01-052-01`, `10 шт`, `400х400 мм` + `ГЭСН15-01-059-01`, `10 шт`, `400х400 мм` → checked `lsr_rim_trace_form_v1`, `6 929.83 руб.`, `bound_rows=2/2`.
> - `uv run pytest tests/test_skill_snippet_registry.py tests/test_smeta_module.py tests/test_prompt_registry_service.py tests/test_chat_harness_format.py tests/test_smeta_artifact_service.py tests/test_estimate_harness.py tests/test_rim_lsr_trace_service.py tests/test_v020_deploy_stamp_ui.py -q` → `209 passed`
> - deployed runtime `/api/version` → `0.24.0.261`, deploy stamp `ok`
> - final live `/api/chat/stream` smoke:
>   - СКС → `lsr_rim_trace_form_v1`, `3 741 981.42 руб.`, `rows=6`, `nonzero_rows=6`, `bound_rows=6/6`, `norm_lookup_calls=6`, `norm_choice_rows=6`.
>   - БАП ВОР PDF (таблица извлечена локальным `pdfplumber`) → `lsr_rim_trace_form_v1`, `1 932 794.62 руб.`, `rows=10`, `nonzero_rows=10`, `bound_rows=10/10`, `norm_lookup_calls=10`, `norm_choice_rows=10`.

> 0.24.0.260 — smeta direct unit aliases and no-empty approximate norm choice
>
> Дата: 2026-07-06
> Статус: dev, готовится к runtime smoke
> Причина: live 0.24.0.259 доказал, что structured norm-choice работает, но СКС
> считал только одну строку: модель выбрала нормы для шкафа/линий, а РИМ trace
> отбрасывал их как `unit_conflict` (`шт` против `статив`, `линия` против
> `цепь (линия)`). Также prompt selector разрешал модели оставлять строку пустой,
> если кандидат технически приблизительный.
> Правки: РИМ trace принимает инженерные счётные измерители (`статив`,
> `система`, `объект`, `цепь (линия)` и т.п.) как count/line aliases после
> модельного выбора нормы. Structured norm-choice теперь требует выбрать
> ближайший candidate при наличии объёма и candidates; пустой `norm_code` только
> когда candidates пустой или нет количества. Код по-прежнему не выбирает норму:
> он валидирует выбранный моделью `norm_code` и считает.
> Проверки:
> - `uv run pytest tests/test_rim_lsr_trace_service.py::test_visible_rows_accept_engineering_count_unit_aliases tests/test_rim_lsr_trace_service.py::test_visible_rows_accept_colon_prefixed_norm_codes tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_validates_model_code_from_lookup -q` → `3 passed`
> - direct builder smoke: СКС-фрагмент с model-selected `ГЭСНм:10-01-052-07`,
>   `ГЭСНм:10-02-050-01`, `ГЭСН:10-03-032-02` → checked
>   `lsr_rim_trace_form_v1`, `34 119.25 руб.`, `bound_rows=3/3`,
>   `priced_partial`.
> - focused suite/deploy/live smoke будут зафиксированы ниже после прогона.

> 0.24.0.259 — smeta direct structured norm-choice loop
>
> Дата: 2026-07-06
> Статус: dev, готовится к runtime smoke
> Причина: 0.24.0.258 закрыл ложные модельные цены, но не давал живые деньги:
> модель видела lookup candidates, но не переносила полный `norm_code` в ЛСР.
> Правки: direct smeta loop теперь замкнут до расчёта. После model-selected
> `search_norm` запускается отдельный JSON-шаг `structured norm_choice`: модель
> выбирает `norm_code` только из lookup candidates и задаёт quantity/unit. Код
> валидирует, что выбранный код был в candidates, затем строит checked
> `lsr_rim_trace_form_v1` через РИМ trace. Colon-коды `ГЭСНм:38-...` и
> `ГЭСНм:10-...` нормализуются в trace extractor.
> Проверки:
> - `uv run pytest tests/test_rim_lsr_trace_service.py::test_visible_rows_accept_colon_prefixed_norm_codes tests/test_chat_harness_format.py::test_smeta_structured_norm_choice_validates_model_code_from_lookup tests/test_chat_harness_format.py::test_smeta_direct_norm_lookup_is_model_selected -q` → `3 passed`
> - direct builder smoke: model-selected `ГЭСНм:38-01-001-01`, `2 т` → checked `lsr_rim_trace_form_v1`, `297 232.88 руб.`, `priced_partial`.
> - focused suite/deploy/live smoke будут зафиксированы ниже после прогона.

> 0.24.0.258 — smeta direct no model-made prices
>
> Дата: 2026-07-06
> Статус: deployed to runtime 2026-07-06, live smoke показал no-fake-price pass / priced-trace gap
> Причина: live 2×3 после 0.24.0.257 доказал, что model-selected lookup
> срабатывает (`norm_lookup_calls=5..10`), но финальная модель всё ещё может
> не копировать полный `norm_code` в ЛСР и иногда придумывать unit_price
> (`СКС run1 = 133 300.00`) без `trace`/`pricebook`.
> Правки: direct smeta prompt и norm-lookup context теперь явно запрещают
> модельные ставки/рубли без checked trace. Если есть lookup results, модель
> должна либо скопировать полный `norm_code` буквально в `Обоснование`, чтобы
> расчётный слой построил `lsr_rim_trace_form_v1`, либо оставить строку с
> `0.00` и примечанием. Общие `ГЭСН 09`/`ГЭСН 15`/`ГЭСНм10` не считаются
> основанием для денег.
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_direct_norm_lookup_is_model_selected tests/test_chat_harness_format.py::test_smeta_direct_prompt_keeps_norm_selection_model_first tests/test_skill_snippet_registry.py tests/test_smeta_module.py tests/test_prompt_registry_service.py tests/test_v020_deploy_stamp_ui.py -q` → `43 passed`
> - `uv run pytest tests/test_skill_snippet_registry.py tests/test_smeta_module.py tests/test_prompt_registry_service.py tests/test_chat_harness_format.py tests/test_smeta_artifact_service.py tests/test_estimate_harness.py tests/test_v020_deploy_stamp_ui.py -q` → `195 passed`
> - deployed runtime `/api/version` → `0.24.0.258`, deploy stamp `ok`
> - live `/api/chat/stream` 2×3 (`аварийное питание` PDF, СКС, столп) → HTTP `200` везде,
>   `norm_lookup_calls=4..10`, все ответы `lsr_rim_display_form_v1`, все суммы `0.00`/`None`,
>   `nonzero_rows=0`. Ложные модельные ставки закрыты. Priced trace gap остаётся: модель
>   видит lookup, но не переносит полный `norm_code` в `Обоснование`; `lsr_rim_trace_form_v1`
>   не строится.

> 0.24.0.257 — smeta direct model-selected norm lookup
>
> Дата: 2026-07-06
> Статус: deployed to runtime 2026-07-06, live smoke показал gap переноса norm_code
> Причина: live 2×3 после 0.24.0.256 показал, что prompt/skill snippets
> улучшают форму, но не дают устойчивого priced trace: все 6 ответов остались
> `display_form`; единственная ненулевая сумма `28 703.50` была взята из
> модельной таблицы без `trace`/`pricebook`, а не из расчёта.
> Правки: direct smeta перед финальным ответом запускает model-selected
> `search_norm` lookup. Модель сама возвращает JSON-вызовы по нормируемым
> работам; код только исполняет read-only lookup и передаёт найденные нормы
> обратно модели. Результаты фиксируются в `retrieval_trace.smeta_norm_lookup`.
> Это не code-side выбор нормы и не финальная смета: полный шифр всё равно
> должен выбрать и написать visible estimator.
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_direct_norm_lookup_is_model_selected tests/test_chat_harness_format.py::test_smeta_direct_prompt_keeps_norm_selection_model_first tests/test_skill_snippet_registry.py tests/test_smeta_module.py -q` → `10 passed`
> - `uv run pytest tests/test_skill_snippet_registry.py tests/test_smeta_module.py tests/test_prompt_registry_service.py tests/test_chat_harness_format.py tests/test_smeta_artifact_service.py tests/test_estimate_harness.py tests/test_v020_deploy_stamp_ui.py -q` → `195 passed`
> - повтор того же focused suite → `195 passed`
> - deployed runtime `/api/version` → `0.24.0.257`, deploy stamp `ok`
> - live `/api/chat/stream` 2×3 → lookup сработал во всех 6 ответах
>   (`norm_lookup_calls=5..10`), но quality fail: все ответы остались
>   `display_form`, trace не появился; СКС run1 дал `133 300.00` из model
>   table без `pricebook`, СКС run2 `0.00`, столп и аварийное питание `0.00`.

> 0.24.0.256 — smeta direct skill-snippet delivery
>
> Дата: 2026-07-06
> Статус: deployed to runtime 2026-07-06, live smoke показал quality gap
> Правки: direct smeta prompt теперь физически получает компактные
> `skill_snippets` через `skill_snippet_registry`, включая сметный workflow:
> модель сама выбирает нормируемую работу и полный шифр нормы; код после этого
> только раскрывает ресурсы/цены/НР/СП и считает арифметику. Snippet указывает
> ход `исходная работа -> нормируемая работа -> семейство ГЭСН/ГЭСНм/ГЭСНп/ГЭСНр
> -> сборник/таблица/код -> ресурсы нормы -> книга ФГИС/КАЦ/КП -> ЛСР` и
> доступные локальные источники (`ГЭСН-2022`, `ГЭСНм10/ГЭСНм38`,
> `spb_2kv2026/moskva_2kv2026`, НР/СП, коэффициенты). Это не shortlist норм к
> конкретной строке и не кейсовый шаблон; это доставка skill-методики до
> runtime-модели.
> Проверки:
> - `uv run pytest tests/test_skill_snippet_registry.py tests/test_smeta_module.py tests/test_prompt_registry_service.py tests/test_chat_harness_format.py tests/test_smeta_artifact_service.py tests/test_estimate_harness.py -q` → `170 passed`
> - повтор того же focused suite → `170 passed`
> - deployed runtime `/api/version` → `0.24.0.256`, deploy stamp `ok`
> - live `/api/chat/stream` 2×3 (`аварийное питание` PDF, СКС, столп) → HTTP `200` везде, но quality fail:
>   все 6 ответов `display_form`, ни одного `lsr_rim_trace_form_v1`;
>   аварийное питание run1 `19` строк, `28 703.50` из model table без trace;
>   аварийное питание run2 `19` строк, `0.00`; СКС оба раза `6` строк,
>   `0.00`; столп `7` и `5` строк, `0.00`.

> 0.24.0.255 — smeta estimator skill and prompt boundary
>
> Дата: 2026-07-06
> Статус: dev, готовится к runtime smoke
> Правки: `skills/smeta/SKILL.md` получил предметный skill сметчика:
> как устроено ценообразование РИМ/ГЭСН, как строка проходит через норму,
> ресурсы, ФГИС/pricebook, НР/СП, КАЦ/КП и ЛСР; отдельно указана локальная
> база ЛЕС (`data/gesn_base/gesn2022*.parquet`, `data/price_base/*.parquet`,
> `config/domain/*.yaml`, `RAG_Content/TABLE_SMETA/SMETA_SERVICE`).
> System/common prompt теперь только маршрутизирует smeta-задачи к
> `skills/smeta/SKILL.md`, не тащит предметную базу в system prompt. Role-pack
> фиксирует `code_does_not_select_norms`, `code_arithmetic_only_after_visible_model_choice`,
> `no_global_stop_cranes_for_incomplete_estimates` и partial-ЛСР: рассчитанные
> строки остаются рассчитанными, незакрытые строки остаются с `0.00`/пустой
> ценой и примечанием. Активные частные шаблоны аварийного питания убраны из prompt/skill/code/tests.
> Проверки:
> - `python3 -m json.tool config/prompts/smeta_estimator_role.json` → ok
> - `uv run pytest tests/test_prompt_registry_service.py tests/test_chat_harness_format.py tests/test_smeta_artifact_service.py tests/test_estimate_harness.py -q` → `162 passed`
> - `rg -n "БАП|бап" proxy config skills tests docs --glob '!docs/RELEASE_LEDGER.md' --glob '!docs/archive/**'` → no matches
> - `git diff --check ...` → clean

> 0.24.0.254 — smeta BAP source-row coverage
>
> Дата: 2026-07-05
> Статус: deployed to runtime 2026-07-05 (manual patch+stamp, proxy restart)
> Тест: реальный файл `/Users/ovc/Downloads/ВОР монтаж БАП П1 13.05.pdf`
> извлекается как 19 строк ВОР; два одинаковых live-запроса до фикса дали
> разные partial-ЛСР: 9 строк / `1 553 051.56 руб.` и 2 строки /
> `93 034.06 руб.`. Это признано невалидным для пользовательского критерия
> “тот же файл -> та же построчная ЛСР”.
> Правки: direct smeta prompt получает source-row coverage contract для
> табличной ВОР (`section/source_no/name/unit/qty`) и требует `SRC`-маркер на
> каждую исходную строку; лимит генерации direct smeta растёт для длинных ВОР;
> checked RIM visible answer показывает покрытие `bound/input` при partial trace
> и не маскирует потерю строк под полную ЛСР. Если табличная ВОР не содержит
> исходных полных шифров норм, а модель выбрала нормы только для части строк,
> частичная случайная цена подавляется: все строки остаются в ЛСР с `0.00`, а
> статус становится `norm_selection_required`.
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py tests/test_smeta_artifact_service.py -q` → `61 passed`
> - `uv run pytest tests/test_smeta_artifact_service.py tests/test_chat_harness_format.py -q` → `62 passed`
> - `make verify` → `2525 collected`
> - live `/api/chat/stream` BAP same-file 2/2 after final fix → canonical artifact digest equal
>   `958317c2dc1c078e`; `rows=19/19`, `SRC=19/19`, `total=0.0`, `bound=0/19`,
>   `status=norm_selection_required`, `same_rows=true`, `same_total=true`.

> 0.24.0.253 — smeta checked RIM LSR visible output
>
> Дата: 2026-07-05
> Статус: deployed to runtime 2026-07-05 (`make ship`)
> Тесты: live `/api/chat/stream` три запроса ЛСР с выбранной нормой показали,
> что расчётная РИМ-трасса, сумма и артефакт уже строятся, но видимый ответ
> смешивал проверенную форму с модельной placeholder-ЛСР и текстом про
> “приоритет” артефакта.
> Правки: `compact_smeta_answer()` при наличии `lsr_rim_trace_form_v1` теперь
> показывает пользователю только проверенную РИМ-ЛСР из trace: сумма, книга
> цен, статус, форма Приложения №3/421-пр и графы 1–12. Модельные нули и
> конфликтующая черновая ЛСР не остаются в visible answer. Markdown-заголовки
> граф стоимости расширены до формулировок “Сметная стоимость …”.
>
> Проверки:
> - `uv run pytest tests/test_smeta_artifact_service.py tests/test_rim_lsr_trace_service.py tests/test_rim_trace_xlsx.py -q` → `29 passed`
> - `uv run pytest tests/test_smeta_artifact_service.py tests/test_rim_lsr_trace_service.py tests/test_rim_trace_xlsx.py tests/test_lsr_rim_trace_api.py -q` → `33 passed`
> - `make verify` → `2522 collected`
> - `make ship` → focused `183 passed`, pre-smoke `9/9`, post-deploy smoke `9/9`
> - live `/api/chat/stream` LSR priced smoke → `3/3`: one-position
>   `11 813 руб.`, two-section `23 626 руб.`, visible-row `11 813 руб.`;
>   each answer starts with checked RIM LSR, includes Appendix №3/421-pr
>   form/graphs/artifact, no placeholder noise.
> - live `/api/chat/stream` SKS/BAP smoke → checked RIM LSR starts the answer,
>   amount `6 721 447 руб.`, status `priced_partial`; long resource-gap list is
>   not shown before the form and is reduced to a note after the LSR/artifact.

> 0.24.0.252 — smeta process-explanation intent fix
>
> Дата: 2026-07-05
> Статус: deployed to runtime 2026-07-05 (`make ship`)
> Тесты: live `/api/chat/stream` вопрос “объясни, как ты работаешь по сметам”
> на `0.24.0.251`; затем unit/focused prompt tests.
> Выводы: `0.24.0.251` правильно различал `без расчёта/без рублей`, но вопрос
> класса `объясни процесс / как ты работаешь / что выбираешь ты / что считает
> код` всё ещё попадал в расчётную ЛСР-ветку, потому что содержал слова
> `сметы` и `ЛСР`.
> Правки: `_smeta_request_needs_lsr_output()` получил отдельный
> `process-explanation` intent. Такие запросы идут в method-ветку даже при
> упоминании ЛСР/сметы/нулей; явные команды `сделай/оформи/рассчитай/дай
> ЛСР|смету|стоимость` остаются расчётными.
>
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_direct_process_explanation_prompt_does_not_force_lsr tests/test_chat_harness_format.py::test_smeta_direct_method_prompt_does_not_force_lsr_or_zero_money tests/test_chat_harness_format.py::test_smeta_direct_prompt_does_not_block_on_empty_spec_price_columns -q` → `3 passed`
> - `uv run pytest tests/test_chat_harness_format.py tests/test_prompt_registry_service.py tests/test_smeta_quantity_audit.py -q` → `68 passed`
> - `make verify` → `2522 collected`
> - `make ship` → focused `183 passed`, pre-smoke `9/9`, post-deploy smoke `9/9`
> - live `/api/chat/stream` process-explanation probe → pass: no LSR header, no
>   `0.00`, model explains model-vs-code split, norm families and resource gap.

> 0.24.0.251 — smeta prompt tests, conclusions, fixes
>
> Дата: 2026-07-05
> Статус: deployed to runtime 2026-07-05 (`make ship`)
> Тесты: live `/api/chat/stream` smeta-method probe, затем focused pytest по
> `tests/test_chat_harness_format.py`, `tests/test_prompt_registry_service.py`,
> `tests/test_smeta_quantity_audit.py`.
> Выводы: method-запрос с явным `без расчёта/без рублей` всё равно превращался
> в ЛСР с нулевыми рублями; модель сужала семейства норм до `ГЭСН/ГЭСНм` и
> путала ведомость добора с нераспознанными работами. Второй провал — batch
> smeta prompt раздулся до `10210` символов при тестовом лимите `9000`.
> Правки: light direct prompt различает методический запрос и расчёт/ЛСР; для
> методического запроса запрещает ЛСР/нулевые рубли и закрепляет `несколько
> ВОР → одна норма`, полный набор семейств `ГЭСН/ГЭСНм/ГЭСНп/ГЭСНр/ГЭСНмр`,
> маршрут поиска нормы и точное значение ведомости добора. Compact render
> role-pack теперь отдаёт ключи правил и имена chain modes без лишнего JSON:
> batch prompt сжат до `7714` символов. Финальный live-probe также закрепил
> запрет на отложенное “следующим сообщением” для методического smeta-ответа.
>
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py tests/test_prompt_registry_service.py tests/test_smeta_quantity_audit.py -q` → `67 passed`
> - `make verify` → `2521 collected`
> - `make ship` → focused `183 passed`, pre-smoke `9/9`, post-deploy smoke `9/9`
> - `GET /api/version` → `les_version=0.24.0.251`
> - live `/api/chat/stream` smeta-method probe → pass: no LSR table, no zero rubles,
>   `many ВОР → one norm`, all norm families, precise resource gap wording,
>   no “следующим сообщением”, no markdown headings.

> 0.24.0.250 — estimator roundtrip refinements from new DOCX notes
>
> Дата: 2026-07-05
> Статус: deployed to runtime 2026-07-05 (`make ship`)
> Причина: дополнительные DOCX уточнили первый этап живого сметчика: связь
> `ВОР ↔ ГЭСН` не обязана быть один-ко-многим; несколько строк ВОР могут
> ссылаться на одну норму, если норма покрывает общий состав работ. Подбор
> норм должен идти маршрутом `семейство работ → группа сборников → сборник →
> раздел/таблица → конкретная норма`, с учётом `ГЭСН`, `ГЭСНм`, `ГЭСНп`,
> `ГЭСНр`, `ГЭСНмр`. Ведомость добора относится к ресурсам выбранной нормы,
> которых нет в сплит-форме/ценовой книге/КП, а не к нераспознанным работам.
> Режим качества расчёта фиксируется как `rough_cost`, `stage_p`, `stage_rd`.
>
> Проверки:
> - `uv run python -m json.tool config/prompts/smeta_estimator_role.json`
> - `uv run pytest tests/test_prompt_registry_service.py::test_smeta_estimator_role_pack_is_json_contract -q`
> - `make verify`
> - `make ship` → post-deploy smoke `9/9`
> - `GET /api/version` → `les_version=0.24.0.250`, `runtime_alignment.status=divergent`
>   только по старым unrelated файлам: `proxy/routers/runtime.py`,
>   `proxy/services/document_explorer_service.py`, `sovushka/styles.py`
> - `GET /api/prompts` → `smeta_harness.version=0.24.0.250-live-estimator-roundtrip`,
>   families `ГЭСН/ГЭСНм/ГЭСНп/ГЭСНр/ГЭСНмр`, modes `rough_cost/stage_p/stage_rd`,
>   route `work_family → collection_group → collection → collection_section_or_table → specific_norm`

> 0.24.0.249 — live estimator TZ skill/prompt/algorithm
>
> Дата: 2026-07-05
> Статус: deployed to runtime 2026-07-05 (`make ship`; затем точечно
> `skills/smeta/SKILL.md` после allowlist fix)
> Причина: присланные рабочие DOCX описывают не “одну правильную сумму”, а
> процесс живого сметчика: сначала прочитать все источники, затем собрать ВОР,
> таблицу кандидатов ГЭСН, дать пользователю выбрать/исправить вариант, только
> потом раскрывать ресурсы, делать первый ЛСР, принимать коэффициенты/КАЦ/КП и
> доводить до `priced_final`. Этот контракт закреплён в `skills/smeta/SKILL.md`,
> `config/prompts/smeta_estimator_role.json` и `docs/ALGO-smeta.md`. Код по-прежнему
> не выбирает работы и нормы; он считает после решения модели и хранит trace.
> `tools/deploy_to_runtime.py` добавил `skills/` в allowlist, потому что
> `version_service` уже считает smeta skill критичным файлом, а deploy tool
> раньше не умел штатно копировать skill-файлы.
>
> Проверки:
> - `uv run python -m json.tool config/prompts/smeta_estimator_role.json`
> - `uv run pytest tests/test_prompt_registry_service.py::test_smeta_estimator_role_pack_is_json_contract -q`
> - `make verify`
> - `make ship` → focused `183 passed`, pre-smoke `9/9`, post-deploy smoke `9/9`
> - `GET /api/version` → `les_version=0.24.0.249`
> - `GET /api/prompts` → `smeta_harness.version=0.24.0.249-live-estimator-workflow`,
>   `live_estimator_workflow=True`
> - `uv run python tools/basic_function_smoke.py` → `9/9`

> 0.24.0.248 — provider effective config visibility
>
> Дата: 2026-07-05
> Статус: deployed with 0.24.0.249 runtime ship, 2026-07-05
> Причина: диагностика через `launchctl getenv` дала ложный вывод, что GPT не
> подключена, хотя runtime `/Users/ovc/LES/.env` содержит `LES_LLM_PROVIDER=openai`
> и OpenAI-compatible ключ/модель. `/api/settings` теперь отдаёт
> `providers.effective` из того же `_llm_runtime()`, которым пользуется чат:
> configured/effective provider, model, `chat_url_set`, fallback и причину fallback
> без раскрытия ключей.
>
> Проверки:
> - `uv run pytest tests/test_proxy_routers.py::test_settings_reports_effective_openai_provider tests/test_proxy_routers.py::test_settings_reports_cloud_provider_fallback_without_key -q`

> 0.24.0.247 — smeta visible system RIM total
>
> Дата: 2026-07-05
> Статус: deployed to runtime 2026-07-05 (`smeta_artifact_service.py`, `version_service.py`)
> Причина: после подключения физически доступных системных источников artifact
> уже считал РИМ/ЛСР по `spb_2kv2026`, но видимый модельный ответ мог оставаться
> с `0.00` placeholders. Теперь `compact_smeta_answer()` всегда добавляет в
> начало ответа строку системного РИМ-расчёта из `rim_lsr_form`, даже когда
> сжатие длинных таблиц выключено. Модельная ЛСР остаётся видимой ниже как
> черновик/выбор норм, но расчётная сумма системы не прячется в artifact.
>
> Проверки:
> - `uv run pytest tests/test_smeta_artifact_service.py::test_compact_smeta_answer_prepends_trace_total_when_compaction_off -q`
> - `uv run pytest tests/test_smeta_artifact_service.py tests/test_chat_harness_format.py -q`
> - `make verify`
> - `uv run python tools/basic_function_smoke.py` → 9/9
>
> Live caveat: длинный live `/api/chat` запрос `СКС/БАП system sources v247`
> дважды упёрся в клиентский timeout (120s и 300s). Runtime живой, `/api/version`
> и `/api/service-sources` отвечают; это latency локальной генерации, не отсутствие
> системных сметных источников.

> 0.24.0.246 — smeta uses physically installed service sources by default
>
> Дата: 2026-07-05
> Статус: deployed to runtime 2026-07-05 (`chat.py`, `smeta_artifact_service.py`, `version_service.py`)
> Причина: оператор справедливо потребовал подключить всё, что физически есть
> в системе, а missing перечислять отдельно. `/api/service-sources` показывает:
> ГЭСН ok (`609987` parquet rows, `42572` base norms), ФГИС ЦС ok (`47`
> pricebooks, `12816756` price rows), сметные YAML ok. Direct smeta prompt
> теперь явно сообщает модели о физически подключённых системных источниках.
> Artifact/RIM trace теперь выбирает системную книгу цен по умолчанию даже
> без региона в вопросе: `LES_DEFAULT_PRICEBOOK` → `spb_2kv2026` →
> `spb_refresh` → `spb_2kv2025` → первая доступная 2026 → первая доступная.
> Если после этого сумма всё ещё нулевая, причина не “нет базы”, а разрыв
> связки `выбранная норма -> ресурсы -> коды ресурсов -> цены`.
>
> Физически не хватает по service-sources: `config/normcontrol/layout_reference.yaml`
> для строгого нормоконтроля лист/рамка/основная надпись; это не блокирует
> сметный РИМ/ЛСР расчёт.
>
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_direct_prompt_includes_available_pricebooks_without_region_hardcode tests/test_chat_harness_format.py::test_smeta_direct_prompt_exposes_physical_service_source_readiness tests/test_smeta_artifact_service.py::test_smeta_artifact_uses_default_system_pricebook_without_region -q`

> 0.24.0.245 — smeta LSR zero placeholders instead of missing amounts
>
> Дата: 2026-07-05
> Статус: dev, ждёт deploy
> Причина: оператору нужна сумма в ЛСР, а не объяснение отсутствия суммы.
> Direct smeta contract теперь запрещает `missing` в числовых/денежных графах
> ЛСР: если нет ставки, индекса или цены ресурса, ставится `0.00`, строка
> `ВСЕГО` тоже числовая, а причина уходит в примечания/добор. Это не делает
> нулевую цену фактом; это видимый placeholder для продолжения работы.
>
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_direct_light_prompt_cuts_heavy_contract_by_default tests/test_chat_harness_format.py::test_smeta_direct_prompt_does_not_block_on_empty_spec_price_columns -q`

> 0.24.0.244 — smeta candidate card binding guard
>
> Дата: 2026-07-05
> Статус: dev, ждёт deploy
> Причина: live `СКС/БАП ЛСР` после 0.24.0.243 показал, что БАП-карточки
> стали доходить и модель выбрала `ГЭСН:08-01-125-01`, но по СКС она
> перенесла кандидат кроссировки на кабель и переписала формат шифра без
> двоеточия. Теперь карточки нормативного поиска явно запрещают переносить
> шифр между работами и требуют копировать норму буквально из карточки.
> Это guardrail привязки evidence, не кодовый выбор нормы.
>
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_direct_prompt_includes_norm_search_cards_for_sks_bap tests/test_estimate_harness.py::test_direct_smeta_norm_search_context_exposes_sks_bap_candidate_cards -q`

> 0.24.0.243 — smeta norm cards before source maps
>
> Дата: 2026-07-05
> Статус: dev, ждёт deploy
> Причина: live `СКС/БАП ЛСР` после 0.24.0.242 показал, что ЛСР-форма
> появилась, но БАП всё ещё уходил в общий `ГЭСН 21`: не потому что модель
> не могла выбрать, а потому что конкретные карточки БАП стояли после общей
> карты сметных источников и обрезались лимитом контекста на блоке СКС.
> Теперь конкретные карточки нормативного поиска по работам запроса идут
> перед общей source-map/pricebook картой; тест требует, чтобы `08-01-125`
> по БАП был виден в direct prompt.
>
> Проверки:
> - `uv run pytest tests/test_chat_harness_format.py::test_smeta_direct_prompt_includes_norm_search_cards_for_sks_bap -q`

> 0.24.0.242 — smeta LSR-first output and BAP candidate cleanup
>
> Дата: 2026-07-05
> Статус: dev, ждёт deploy
> Причина: после live `СКС/БАП тест 3-3` модель начала видеть конкретные
> `ГЭСНм:10-*` кандидаты по СКС, но форма ответа оставалась ВОР/оценкой с
> ЛСР только по явной просьбе, а БАП конкурировал с шумными строками
> `08-03-594-*` про светильники блоками. Теперь direct smeta contract
> требует ЛСР-черновик граф 1-12 как основную форму выдачи любой сметной
> оценки; ВОР остаётся исходной расшифровкой. Для БАП добавлен элемент
> `backup_power`: кандидатные карточки поднимают `08-01-125-*` по системе
> бесперебойного электропитания и штрафуют светильниковый/подстанционный шум.
> User-facing prompt больше не показывает имя внутреннего инструмента
> `search_norm`, только «нормативный поиск ЛЕС».
>
> Проверки:
> - `uv run pytest tests/test_estimate_harness.py::test_electric_bap_search_prefers_backup_power_over_lighting_blocks tests/test_estimate_harness.py::test_direct_smeta_norm_search_context_exposes_sks_bap_candidate_cards tests/test_chat_harness_format.py::test_smeta_direct_prompt_includes_norm_search_cards_for_sks_bap tests/test_chat_harness_format.py::test_smeta_direct_light_prompt_cuts_heavy_contract_by_default -q`

> 0.24.0.241 — smeta direct answers get search_norm candidate cards
>
> Дата: 2026-07-05
> Статус: dev, ждёт deploy
> Причина: live `СКС/БАП тест 3-3` после восстановления cloud key дал
> нормальный ВОР/ЛСР-черновик, но конкретные шифры норм оставались текстовыми
> догадками модели (`ГЭСНм10/ГЭСН 21 кандидат, уточнить`). Теперь direct smeta
> prompt получает компактный навигационный блок из реального `search_norm`:
> candidate cards с `norm_code`, измерителем, применимостью и collection.
> Код не выбирает норму и не пишет ответ; модель видит shortlist и должна
> выбрать кандидата или оставить `missing`. Для low-current route scoring
> `ГЭСНм10` поднят выше строительного/силового шума, а БАП идёт через
> электромонтажные candidate cards без маскировки под финальный шифр.
>
> Проверки:
> - `uv run pytest tests/test_estimate_harness.py tests/test_chat_harness_format.py tests/test_smeta_norm_store.py -q`
> - `uv run python -m py_compile proxy/services/estimate_harness_service.py proxy/routers/chat.py`
> - `git diff --check -- proxy/services/estimate_harness_service.py proxy/routers/chat.py tests/test_estimate_harness.py tests/test_chat_harness_format.py`
>
> 0.24.0.240 — compact dataset reader-pass input + diagnostic local extraction
>
> Дата: 2026-07-05
> Статус: dev, ждёт deploy
> Причина: NS golden dataset показал, что `memory/read` возвращал
> `reader_status=model_failed`: модельный reader-pass не строил собственную
> навигационную карту, а system счётчики маскировали это как готовность
> корпуса. `_reader_context()` теперь передаёт модели компактный source-guide
> вместо полного технического JSON: operator guidance, top files, bounded
> routes/topics/sections и явное правило `navigation != evidence`. Параллельно
> `extract_service` сохраняет диагностируемый provider error даже когда
> исключение провайдера имеет пустой `str(exc)`, а локальный MLX structured
> extraction получает default timeout 300s вместо cloud-oriented 120s.
>
> Проверки:
> - `uv run pytest tests/test_dataset_memory_service.py tests/test_extract_service.py -q`
> - `uv run python -m py_compile proxy/services/dataset_memory_service.py proxy/services/extract_service.py proxy/services/version_service.py`
>
> 0.24.0.239 — project PDF typing repair for NTD datasets
>
> Дата: 2026-07-04
> Статус: dev, ждёт deploy
> Причина: NS quality audit показал, что индекс физически полон (`999`
> chunks в SQLite/Qdrant), но typed memory/Qdrant payloads помечали проектные
> ЭОМ PDF как `normative` из-за домена `NTD_ELECTRICAL`. Теперь `NTD_*`
> сам по себе означает техническую область поиска, а не нормативный документ:
> `NORMATIVE` ставится только по явному doc_type/имени/сметно-нормативному
> источнику. Router также не переводит проектный PDF с `Заказчик` +
> `Рабочая документация` в нормативку только из-за внутренних ссылок на
> СП/ГОСТ/своды правил.
>
> Проверки:
> - `uv run pytest tests/test_document_router.py tests/test_dataset_memory_service.py -q`
>
> 0.24.0.238 — broad dataset overview включается для вопросов “что это за датасет”
>
> Дата: 2026-07-04
> Статус: dev, ждёт deploy
> Причина: NS live probe показал, что общий вопрос `что это за датасет`
> не включал notebook-study/project-inventory слой и модель отвечала по
> случайному page chunk схемы. `notebook_study_service.is_notebook_study_query`
> теперь считает `что это за датасет/что за проект` broad-study запросом при
> выбранной области, а `project_summary_service.is_project_inventory_query`
> включает компактную MetaDB-карту для вопросов вида `что это за датасет`.
> Точные lookup/сметные запросы (`где лежит`, `найди`, `дай смету`) не
> расширяются.
>
> Проверки:
> - `uv run pytest tests/test_notebook_study_service.py tests/test_project_summary_inventory.py -q`
>
> 0.24.0.237 — embedding timeout/batch defaults for PDF indexing
>
> Дата: 2026-07-04
> Статус: deployed to runtime 2026-07-04
> Причина: NS retry после 0.24.0.236 успешно индексировал первые PDF, но два
> больших файла падали `last_error=timed out`: legacy `BAAI/bge-m3`
> sentence-transformers CPU batch иногда считает один `/v1/embeddings` request
> дольше жёстких 60 секунд. `RAG_EMBED_BATCH` default синхронизирован с
> `env.example` до 16, добавлен `RAG_EMBED_TIMEOUT_SEC=300`.
>
> Проверки:
> - `uv run pytest tests/test_qdrant_adapter_parse.py tests/test_converter_process_isolation.py -q`
>
> 0.24.0.236 — PDF page-node bound for embedder stability
>
> Дата: 2026-07-04
> Статус: deployed to runtime 2026-07-04
> Причина: runtime NS parse после 0.24.0.235 показал, что page-node strategy
> уже не падает на PDF conversion, но default `RAG_PDF_PAGE_NODE_MAX_CHARS=5000`
> слишком крупный для текущего sentence-transformers embedder batch: `/v1/embeddings`
> упал с `Invalid buffer size: 15.18 GiB`. Default снижен до 1800 chars /
> overlap 150, чтобы PDF ingestion масштабировался по памяти.
>
> Проверки:
> - `uv run pytest tests/test_document_router.py tests/test_qdrant_adapter_parse.py tests/test_converter_process_isolation.py tests/test_datasets_router.py::test_external_intake_plan_keeps_maps_out_of_accepted_count tests/test_datasets_router.py::test_index_external_starts_dataset_scoped_parse_drain -q`
>
> 0.24.0.235 — external folder service maps are not indexed as corpus documents
>
> Дата: 2026-07-04
> Статус: deployed to runtime 2026-07-04
> Причина: NS должен быть “4 файла”, но `index-external` создавал `LES.md` /
> `00_dataset_map.md` до регистрации и затем регистрировал markdown-карту как
> обычный RAG-документ. Теперь эти файлы остаются прозрачным служебным слоем
> папки и не попадают в document count / parse queue. Это общий фикс GUI-пути
> `+ папка`, не smeta-specific.
>
> Проверки:
> - `uv run pytest tests/test_datasets_router.py::test_external_intake_plan_keeps_maps_out_of_accepted_count tests/test_datasets_router.py::test_index_external_starts_dataset_scoped_parse_drain -q`
> - `make verify`
>
> 0.24.0.234 — PDF page-node indexing + general PDF router fix
>
> Дата: 2026-07-04
> Статус: deployed to runtime 2026-07-04
> Причина: NS показал второй дефект общего PDF path: после baseline-first обычные
> проектные PDF всё ещё уходили в `TABLE_SMETA` по слабым словам (`смета затрат`) и
> substring-сигналам (`тер` внутри других слов), а markdown heading splitter делал
> сотни плотных chunks на файл. Новый контракт общий для PDF: `qdrant_adapter`
> индексирует PDF/P7M page-text слой как bounded `pdf_page_text` nodes с page anchors,
> а `document_router` требует explicit estimate signals для `SMETA`/`TABLE_SMETA`.
>
> Локальный NS-бенч dev-кода на 4 PDF: старые 550/561/649/737 chunks заменяются
> на 104/104/116/143 page nodes; route для трёх проектных ЭОМ PDF — `DOCUMENT` /
> `NTD_ELECTRICAL`, сметные PDF по явному имени остаются `SMETA`.
>
> Проверки:
> - `uv run pytest tests/test_document_router.py tests/test_qdrant_adapter_parse.py tests/test_converter_process_isolation.py -q`
> - `make verify`
>
> 0.24.0.233 — PDF ingestion baseline-first: page-text не блокируется table/layout timeout
>
> Дата: 2026-07-04
> Статус: dev, не задеплоено на runtime
> Причина: NS показал дефект текущего PDF path: 4 проектных PDF уходили в `ERROR`
> из-за `markdown_pdf_tables`/isolated converter timeout. Новый контракт:
> реальный PDF в index path сначала получает быстрый PyMuPDF page-text слой с page anchors;
> Docling/pymupdf4llm/layout/table/OCR считаются enrichment, а не gate. Если тяжёлый
> isolated converter падает по timeout, `convert_to_markdown_for_indexing()` пробует
> page-text fallback вместо `ERROR`. Док-канон: `docs/ALGO-pdf-ingestion.md`.
>
> Проверки:
> - `uv run pytest tests/test_converter_process_isolation.py -q`
> - `uv run python -m py_compile backend/converter.py`
>
> 0.24.0.232 — `+ папка` показывает transparent intake plan перед индексацией
>
> Дата: 2026-07-04
> Статус: dev, не задеплоено на runtime
> Причина: основной GUI-путь добавления проектных документов теперь получает
> `POST /api/rag/external/intake-plan`: до Play оператор видит, какой проект/dataset
> будет создан, сколько файлов принято/пропущено, какие карты `LES.md`/`00_dataset_map.md`
> будут использованы, какие дисциплины распознаны и чего не хватает для сметных расчётов.
> `index-external` создаёт/обновляет `00_dataset_map.md` до регистрации файлов, поэтому карта
> попадает в тот же dataset первой волной. В roadmap добавлен refactor `document_router`:
> выбранная папка/датасет/`LES.md` владеют scope, router остаётся file-role/parse-pipeline hints.
>
> Проверки:
> - `uv run pytest tests/test_datasets_router.py::test_external_intake_plan_keeps_maps_out_of_accepted_count tests/test_datasets_router.py::test_index_external_starts_dataset_scoped_parse_drain -q`
> - `uv run python -m py_compile proxy/routers/datasets.py sovushka/pages/samovar.py`
>
> 0.24.0.231 — `SMETA_SERVICE` Play показывает требуемые сметные документы и форматы
>
> Дата: 2026-07-04
> Статус: dev, не задеплоено на runtime
> Причина: roadmap v0.24D зафиксировал отдельный служебный сметный датасет:
> оператор кладёт постоянные нормы/цены/индексы/методики/формы в `SMETA_SERVICE`
> и нажимает Play. `config/service_sources.yaml` получил источник
> `smeta_service_dataset` с manifest классов `norms/prices/methodology/forms`.
> `service_source_registry` теперь рекурсивно понимает `**` globs, отдаёт
> `required_documents` со статусами `ready/partial/missing_blocking/missing_degraded`,
> а Play возвращает понятное summary без мутации базы. UI «Инструменты» показывает
> раскрываемый блок «Какие документы нужны» с preferred/raw форматами.
>
> Проверки:
> - `uv run pytest tests/test_service_source_registry.py -q`
> - `make verify`
>
> 0.24.0.230 — `first_ordinal_guard` переживает общий chat lexical rerank
>
> Дата: 2026-07-04
> Статус: deployed to runtime 2026-07-04
> Причина: live CAD smoke показал, что retrieval ставит `drawn_table_1 first positions`
> первым, но `chat.py` затем снова вызывает `rank_chunks_for_question`, и lexical boost
> поднимает `drawn_table_3` по score/терминам. `retrieval_service` теперь помечает выбранный
> first-position evidence `_rank_pin`, а `saferag_service.rank_chunks_for_question` уважает
> этот pin при последующем ранжировании.
>
> Проверки:
> - `uv run pytest tests/test_retrieval_service.py::test_retrieve_chat_chunks_promotes_earliest_first_positions_with_doc_filter tests/test_context_expander_service.py tests/test_cad_bim_aggregate_w61.py::test_render_projection_includes_drawn_tables_before_elements -q`
> - direct retrieval → `rank_chunks_for_question` → `concentrate_sources` → `expand_context_windows` smoke
> - `make verify`
> - `make ship`
>
> 0.24.0.229 — context-window больше не выталкивает основной найденный chunk соседним контекстом
>
> Дата: 2026-07-04
> Статус: deployed to runtime 2026-07-04
> Причина: live CAD smoke после 0.24.0.228 показал, что retrieval уже ставит
> `drawn_table_1 first positions` первым, но `expand_context_windows` рендерит длинный
> `Контекст до` перед `Основной фрагмент` и режет окно до того, как до evidence доходит
> модель. `context_expander_service` теперь всегда пишет `Основной фрагмент` сразу после
> `Раздел`, а соседей добавляет после него; длинные соседи режутся первыми. Заголовок окна
> берётся из точного `section_heading` перед более общим `parent_heading`.
>
> Проверки:
> - `uv run pytest tests/test_context_expander_service.py tests/test_retrieval_service.py::test_retrieve_chat_chunks_promotes_earliest_first_positions_with_doc_filter tests/test_cad_bim_aggregate_w61.py::test_render_projection_includes_drawn_tables_before_elements -q`
> - `make verify`
> - `make ship`
>
> 0.24.0.228 — first-position guard ранжирует CAD-таблицы по фактической `position N`, а не по `chunk_ord`
>
> Дата: 2026-07-04
> Статус: deployed to runtime 2026-07-04
> Причина: live CAD smoke показал, что `first_ordinal_guard` помечался, но выбирал лист/продолжение
> таблицы с меньшим `chunk_ord` (`position 6/21`) вместо фактического начала спецификации
> (`position 1`). `retrieval_service` теперь промотит первый CAD-чунк по минимальному найденному
> номеру позиции, а `chunk_ord` использует только как tie-breaker.
>
> Проверки:
> - `uv run pytest tests/test_retrieval_service.py::test_retrieve_chat_chunks_promotes_earliest_first_positions_with_doc_filter tests/test_context_expander_service.py::test_context_expander_accepts_runtime_metadata_alias tests/test_cad_bim_aggregate_w61.py::test_render_projection_includes_drawn_tables_before_elements -q`
> - `make verify`
> - `make ship`
>
> 0.24.0.227 — `context_expander_service` тоже принимает runtime alias
> `metadata` наряду со старым `meta`, чтобы context-window видел
> `chunk_ord`/heading/context_before/context_after у настоящих Qdrant chunks.
> Это закрывает следующий live-провал: retrieval trace уже содержал
> `first_ordinal_guard`, но prompt/source-map после expansion всё равно
> начинались с соседних drawn tables. Checks:
> `uv run pytest tests/test_context_expander_service.py
> tests/test_retrieval_service.py tests/test_cad_bim_extract_dxf.py
> tests/test_cad_bim_aggregate_w61.py -q`.

> 0.24.0.226 — `first_ordinal_guard` читает оба runtime-варианта
> метаданных chunk (`meta` и `metadata`). Live `0.24.0.225` уже показывал
> `first_ordinal_guard` в trace, но на настоящих Qdrant chunks не видел
> `chunk_ord`, поэтому не поднимал начало `drawn_table_1`. Тест
> `test_retrieve_chat_chunks_promotes_earliest_first_positions_with_doc_filter`
> переведён на `metadata`, чтобы ловить этот класс регрессии. Checks:
> `uv run pytest tests/test_retrieval_service.py
> tests/test_cad_bim_extract_dxf.py tests/test_cad_bim_aggregate_w61.py -q`
> 32/32.

> 0.24.0.225 — CAD drawn-table projection получил отдельные
> `first positions / первые три позиции` и `logical positions / позиции
> спецификации` узлы: для таблиц, нарисованных линиями, projection теперь
> выводит нормализованные строки `position N | name | mark | manufacturer |
> unit | qty | source_row`, включая случаи, где номер позиции слипся с
> текстом в одной CAD-ячейке. `retrieval_service` добавил generic
> `first_ordinal_guard`: при `target_file/doc_filter` и запросах про первые
> строки/позиции среди уже найденных chunks поднимается самый ранний
> подходящий табличный chunk по `chunk_ord`, чтобы модель получала начало
> выбранной таблицы, а не середину соседней. Checks:
> `uv run pytest tests/test_retrieval_service.py
> tests/test_cad_bim_extract_dxf.py tests/test_cad_bim_aggregate_w61.py -q`
> 32/32. Live before guard: projection contained correct positions 1-3, but
> chat still chose drawn_table_2/3; guard is the runtime fix to ship next.

> 0.24.0.224 — DWG/DXF extractor восстанавливает таблицы, нарисованные
> примитивами `LINE`/`LWPOLYLINE` плюс `TEXT`/`MTEXT`: ищет связные
> горизонтально-вертикальные сетки, кластеризует границы строк/колонок,
> раскладывает текст по ячейкам и пишет `tables[]` +
> `properties.drawn_tables_detected` в `cad_bim_graph.json`. CAD/BIM importer
> не разворачивает этот слой в шумные graph-properties, а рендерит отдельный
> блок `CAD drawn tables` в projection перед элементами, чтобы RAG видел
> спецификацию как строки таблицы, а не как сотни примитивов; перед широкой
> markdown-таблицей добавляются `First data rows / первые позиции`, data
> row-lines и compact row-lines, чтобы context-window/rerank не уводил модель
> в середину таблицы и не обрезал позиции после одной шапки. Live dry probe на уже извлечённом
> `kotelnaya_repair_gsv_spec.cad_bim_graph.json`: 3 таблицы; первая 37 строк /
> 19 колонок / 168 непустых ячеек, включая заголовки и позиции газового
> оборудования. Checks:
> `uv run pytest tests/test_cad_bim_extract_dxf.py
> tests/test_cad_bim_aggregate_w61.py -q` 10/10; `make verify` collected
> 2495; `make ship` green (`179 passed`, smoke 9/9, post-deploy smoke 9/9).

> 0.24.0.223 — вкладка «Документы» получила режим `CAD`: GUI-рычаг
> поверх `GET /api/cad-bim/imports` с метриками imports/elements/projection
> docs, списком слабых импортов, duplicate groups, duplicate indexed
> projections, кнопками «Открыть projection» и «Спросить» по конкретному
> CAD/DWG import. Chat page теперь принимает query-param `target_file`, чтобы
> переход из CAD inventory мог сразу сузить RAG к выбранной projection-карточке.
> Checks: `uv run pytest tests/test_static_assets.py
> tests/test_cad_bim_import_inventory.py -q` 8/8; `make verify` collected
> 2493; `make ship` green (`179 passed`, smoke 9/9, post-deploy smoke 9/9).

> 0.24.0.222 — CAD/BIM получил read-only inventory для контроля качества
> конвейера `import → graph DB → markdown projection → CAD_BIM_Index`:
> `GET /api/cad-bim/imports` сверяет `cad_bim_imports` с MetaDB
> `documents`, показывает `quality_status` (`ok/minimal/suspicious/empty`),
> `projection_index_status` (`indexed/not_indexed/duplicate_indexed/...`),
> indexed-документы, слабые импорты и duplicate groups по нормализованному
> source-фингерпринту. Это диагностический слой для GUI/консоли: он ничего не
> удаляет, не чистит Qdrant и не запускает реиндекс. `cad_bim_graph.py` и
> `routers/speckle.py` добавлены в critical version alignment, чтобы deploy
> stamp видел CAD/BIM-правки.
> Checks: `uv run pytest tests/test_cad_bim_import_inventory.py
> tests/test_cad_bim_extract_dxf.py
> tests/test_retrieval_service.py::test_retrieve_chat_chunks_promotes_cad_source_name_with_compact_path
> tests/test_retrieval_service.py::test_retrieve_chat_chunks_promotes_cad_source_name_after_rerank
> tests/test_retrieval_service.py::test_retrieve_chat_chunks_promotes_exact_source_after_rerank -q`
> 9/9; `make verify` collected 2493; `make ship` green
> (`179 passed`, smoke 9/9). Live `GET /api/cad-bim/imports?limit=200`:
> 23 imports, 27 projection documents, 3 duplicate groups, 7 weak imports,
> 1 duplicate-indexed import.

> 0.24.0.221 — DWG/DXF extractor получил repair-pass для реальных
> LibreDWG DXF с битой кириллицей/MTEXT: если строгий `ezdxf.readfile()`
> падает на нечисловой group-code line, инструмент чинит ASCII DXF,
> склеивая оборванную строку обратно в предыдущее значение, добавляет EOF при
> необходимости и пишет trace `dxf_read_mode`/`dxf_strict_error` в
> `cad_bim_graph.json`. JSON output дополнительно проходит `_json_safe`, чтобы
> surrogate bytes из старых DWG не ломали запись. Live CAD probe:
> ранее падавшая `лесной ГСВ Спецификация.dwg` извлеклась в 533 элемента и
> импортировалась как `502617b60ad4`; пять ранее падавших DWG из первой пачки
> Котельной теперь доходят до import, хотя два дают пустой/minimal graph.
> Retrieval получил CAD/BIM source-name boost: generic projection больше не
> должен заслонять chunk, в source path/content которого совпали специфичные
> термины запроса (`ГСВ`, `АТМ`, `Лесной`, `Спецификация`), при этом нормативные
> ссылки не попадают в этот guard; compact-нормализация склеивает `Лесной_64`
> и `Лесной64`. Checks:
> `uv run pytest tests/test_retrieval_service.py::test_retrieve_chat_chunks_promotes_cad_source_name_with_compact_path tests/test_retrieval_service.py::test_retrieve_chat_chunks_promotes_cad_source_name_after_rerank tests/test_retrieval_service.py::test_retrieve_chat_chunks_promotes_exact_source_after_rerank tests/test_cad_bim_extract_dxf.py -q`
> 7/7.

> 0.24.0.220 — CAD/BIM DWG получил штатный инструментальный вход:
> `tools/cad_bim_extract_dxf.py` теперь принимает `.dwg`, вызывает LibreDWG
> `dwg2dxf`, сохраняет trace конвертации в `cad_bim_graph.json` и дальше
> использует существующий `/api/cad-bim/import`. Retrieval получил
> source-exact guard: если в запросе/выбранном scope есть точное имя projection,
> DWG/DXF/JSON/MD или import/source id, такой chunk поднимается после merge и
> после rerank, чтобы большой старый CAD/BIM projection не заслонял точный новый
> источник. Live CAD smoke: `03_00-14-АПС_ТА.dwg` → DXF → JSON →
> import `db1941fd7ee6`; `sync-smart` для `RAG_Content/CAD_BIM/exports`
> распарсил 3 projection-файла в `CAD_BIM_Index`, 900 chunks, errors=0.
> Checks: `uv run pytest tests/test_retrieval_service.py::test_retrieve_chat_chunks_promotes_exact_source_after_rerank tests/test_cad_bim_extract_dxf.py -q`
> 3/3; `make verify` 2487 collected; `make ship` green with post-deploy
> smoke 9/9. Live retrieval check after deploy: exact query
> `cad_bim_json_db1941fd7ee6.md` returns that projection at rank 1 with trace
> `qdrant_native_hybrid+source_exact+source_exact_guard+rerank`.
> Follow-up regression: первый полный `make test` показал, что guard слишком
> широко ловил нормативные ссылки `СП 1.13130` как source-id; regex сужен до
> filenames/paths/import-id/long hex/underscore/colon source terms. Final checks:
> `uv run pytest tests/test_retrieval_service.py tests/test_cad_bim_extract_dxf.py -q`
> 21/21; `make test` 2487 passed.

> 0.24.0.219 — закрывает вторую причину XLS/XLSX chunk explosion:
> Excel route `pipeline=parquet` сохраняет полный Parquet для точных строк,
> фильтров, сумм и группировок, но больше не обязан класть каждую parquet-строку
> в Qdrant. Если нормализованных row chunks больше
> `RAG_TABLE_ROW_INDEX_MAX_CHUNKS` (default 600), Qdrant получает один
> `table_navigation_projection` с `parquet_path`, числом строк, листов и
> примерами ключевых полей. Это сохраняет точность расчётов в Parquet и убирает
> доминирование больших таблиц в semantic retrieval. Checks:
> `uv run pytest tests/test_qdrant_adapter_parse.py::test_sync_table_nodes_projects_large_row_sets tests/test_converter_process_isolation.py tests/test_qdrant_adapter_parse.py -q`
> 28/28.

> 0.24.0.218 — большие Excel/CSV больше не разворачиваются в тысячи
> равноправных markdown-row чанков. `converter._parse_spreadsheet()` оставляет
> маленькие листы полными markdown-таблицами, а большие листы рендерит как
> `spreadsheet_navigation_projection`: список колонок, размеры прочитанного
> окна, профили колонок, числовые min/max/sum и небольшой образец строк. Это
> навигационный слой для выбора файла/листа/колонки; точные строки и расчёты
> должны читаться из исходного файла табличным reader/tool. В Qdrant payload
> такие узлы маркируются `type=spreadsheet_projection`. Live-проба на тяжёлом
> `РТ1.xlsx` из ПД ИЦ: было 2405 chunks, новая проекция даёт ~15 final nodes
> до эмбеддинга. Checks: `uv run pytest tests/test_converter_process_isolation.py tests/test_qdrant_adapter_parse.py -q`
> 27/27.

> 0.24.0.217 — индексатор переводит рискованную markdown-конвертацию
> PDF/P7M/XLS/XLSX/XLSM в отдельный killable subprocess
> (`RAG_CONVERT_SUBPROCESS_ENABLED`, default true). Timeout дочернего
> процесса берётся из `RAG_CONVERT_SUBPROCESS_TIMEOUT_SEC` или 90% от
> `RAG_PARSE_FILE_TIMEOUT_SEC`, чтобы зависший `pymupdf4llm`/OCR/MarkItDown/
> pandas-openpyxl не оставался брошенным потоком внутри proxy. Обычные
> текстовые/JSON/DOCX/почтовые пути не менялись. Для Excel/CSV порядок
> конвертации изменён на `pandas/openpyxl -> MarkItDown`, потому что реальный
> `РТ1.xlsx` из ПД ИЦ читается прямым spreadsheet parser за 0.84с, тогда как
> старый вход мог тратить timeout на MarkItDown до fallback. Checks:
> Parent process читает `multiprocessing.Queue` до `join()`, чтобы большой
> markdown-результат не блокировал завершение дочернего процесса. Checks:
> `uv run pytest tests/test_converter_process_isolation.py -q` 8/8,
> `uv run pytest tests/test_parse_pipeline_w14.py -q` 8/8,
> focused converter+parse+adapter 35/35, `make verify` 2485 collected,
> `make test` 2481 passed before spreadsheet-projection follow-up.
> Live read-only XLSX probe after fix: 12/12 проблемных workbook из ПД ИЦ
> сконвертированы subprocess-путём за ~0.4-0.9с каждый, без оставшихся
> `les-convert` процессов.
> Live read-only probe: проблемный `РТ3.xlsx` из ПД ИЦ сконвертирован
> subprocess-путём за 5.67с (~49k chars); проблемный PDF с timeout 45с
> завершился `convert subprocess timeout` без оставшегося `les-convert`
> процесса.

> 0.24.0.216 — parse-контур больше не записывает raw CAD/BIM
> исходники (`.dwg/.dxf/.rvt/.rfa/.ifc/.ifczip/.nwc`) как `INDEXED`
> с `0` чанков. Такие файлы получают явный `ERROR` с маршрутом
> `export/import as canonical CAD/BIM JSON/JSONL projection`, чтобы
> документы не выглядели проиндексированными до typed CAD/BIM-конвертера.
> Текстовые/JSON/Markdown проекции внутри `CAD_BIM` остаются штатным входом.
> Live MetaDB cleanup 2026-07-04: 119 существующих raw CAD/BIM документов
> в `BAI`/`Котельная_Лесной64` переведены из ложного `INDEXED 0` в `ERROR`;
> backup создан рядом с `les_meta_qwen.db` перед транзакцией.
> Checks: `uv run pytest tests/test_parse_pipeline_w14.py -q` 8/8,
> `uv run pytest tests/test_qdrant_adapter_parse.py -q` 18/18,
> `make verify` 2475 collected.

> 0.24.0.214 — удалён smeta fast visible fallback как кодовая подмена
> модельного ответа. При timeout/empty `_smeta_direct_model_answer()` больше
> не генерирует case-specific сценарии, а явный smeta-mode возвращает
> технический failure с trace `code_fallback_disabled=true`. `КП` больше не
> ведёт в старый stub-профиль; professional-domain deterministic candidates (`smeta`,
> `asbuilt`, `doc_registry`, `field`) не могут стать финальным visible answer
> без модели. Корневой дефект надо чинить в provider/key routing, model call,
> prompt/contract, retrieval или tool layer; ЛСР/ВОР не собираются regex/code-
> ответом.

> 0.24.0.215 — общий чат получил bounded model-selected tool loop:
> `shortlist` строит доступные read-only tools, модель возвращает JSON calls,
> код исполняет только выбранные tools, а финальный visible answer снова пишет
> модель. `retrieval_trace.tool_loop` хранит shortlist, selected calls,
> provider/model selector и tool results. Qdrant visualizer в Совушке починен:
> `/graph` редиректит на mounted `/qdrant-visualizer/index.html`, поэтому
> `visualizer.js/pca.js/data.js` грузятся same-origin. Mermaid-вкладка получила
> live `Граф знаний` из `/api/rag/graph/full`. Сметный compact-ответ выключен
> по умолчанию (`LES_SMETA_COMPACT_CHAT_TABLES=1` для legacy), XLSX sidecar
> extraction больше не имеет молчаливого `5000` rows cap
> (`LES_XLSX_EXTRACT_MAX_ROWS` только opt-in). Аудит лимитов зафиксирован в
> `docs/ANSWER_LIMIT_AUDIT.md`. Checks: focused 96/96, `make verify`
> 2474 collected, `make test` 2474 passed, FIRE/HVAC golden 16/16,
> `git diff --check`, `uv lock --check`.

> 0.24.0.213 — добавлен controlled tool-harness без автономного agent loop:
> `proxy/services/tool_harness_service.py` регистрирует `dataset_map`,
> `search_sources`, `read_source`, `read_pdf_source`, `read_excel_source` и
> read-only filesystem tools (`roots/list/stat/read_text/search/hash`), а каждый
> вызов возвращает `les_tool_result_v1` с `sources`, `missing`, `warnings`,
> `trace` и `contract_check`. API `/api/tools/{registry,shortlist,call}` и CLI
> `tools/les_tool_harness.py` дают оператору консольные рычаги, а вкладка
> «Документы» получила блок `Tool-harness dry-run`. Filesystem работает только
> по whitelist-root и без write; PDF/Excel tools пока честно читают indexed
> chunks и отмечают raw page/table или sheet/range extraction как следующий слой.

> 0.24.0.212 — карта источников стала видимой оператору: вкладка
> «Документы» показывает `dataset_topic_map_v1` и `dataset_section_map_v1`
> как темы, файлы и разделы, а кнопка «Спросить по теме» открывает чат с
> `scope=ds:<dataset_id>` и предзаполненным вопросом. Trace summary в чате
> теперь показывает topic-guided retrieval: выбранную тему, targeted/fallback
> counts и promoted fallback-документ.

> 0.24.0.211 — карта тем стала рабочим retrieval layer: при выбранном
> датасете `routers/chat.py` строит `dataset_topic_selection_v1`, выбирает
> тему/файлы/разделы из `dataset_topic_map_v1`, сначала делает targeted
> `doc_filter` retrieval, затем добавляет широкий fallback. Focus использует
> lexical `_rank_score` и поднимает лучший внешний fallback-документ в видимое
> окно контекста, чтобы карта не закрывала соседние проектные тома. В trace
> `topic_guided_retrieval` пишутся selected topic/files/sections,
> targeted/fallback counts, promoted fallback и not-found files. Semantic cache
> отключается для таких запросов, чтобы старая плоская выдача не обходила карту.

> 0.24.0.210 — typed dataset memory получил слой `dataset_topic_map_v1`
> и `dataset_section_map_v1`: поверх file cards/source graph строится
> NBLM-подобный source guide датасета. Topic map связывает инженерные темы
> (`пожарная сигнализация и противопожарная автоматика`, `ОВ/противодымная
> вентиляция`, `электроснабжение`, `ВОР/сметы` и т.д.) с первыми файлами,
> aliases и видимыми headings. Section map берёт bounded-сигналы
> `section_heading/parent_heading` из `lexical_chunks`, без OCR/reindex.
> `dataset_brief_for_model_v1` теперь показывает модели тему -> файлы ->
> разделы -> doc_filter маршрут. Это навигация и оглавление корпуса, не
> evidence и не ответ кодом.

> 0.24.0.209 — typed dataset memory получил `navigation_terms` в file cards,
> routes, source graph и compact brief: модель видит не только имя файла и
> роль, но и короткие поисковые синонимы. Для FSNB `A_SRF_F` раскрывается как
> “нормы/расценки/шифр нормы”, `A_SRF_TR` — как
> “ресурсы нормы/машины/материалы”, pricebook — как
> “ФГИС ЦС/цены ресурсов/регион/квартал”. Старые cached memory дообогащаются
> без reindex; это навигация, не evidence и не выбор нормы кодом.

> 0.24.0.208 — добавлен публичный текст `docs/ARTICLE_NOTEBOOK_RAG_ARCHITECTURE.md`
> о подходе LES: не просто поиск по нарезанным фрагментам, а блокноты
> источников, карты датасетов, роли документов, веса навигации и баланс
> “модель связывает, источники доказывают, код считает”. Для сметного RAG
> projector `tools/smeta_ru_norm_rag_ingest.py` теперь пишет человеческие
> карточки внутренних таблиц `.vnbx`: `A_SRF_F` = таблица норм/расценок ФСНБ,
> `A_SRF_TR` = таблица ресурсов нормы, `A_SRF_VR/A_F3_VR` = иерархия разделов,
> `B_NORMTYPE` = тип нормативной базы, `LEVEL_COST` = ценовой уровень. Typed
> dataset memory умеет давать эти роли и для уже старых проекций без полного
> переиндекса, чтобы модель открывала нормативный корпус по смыслу, а не по
> служебным именам.

> 0.24.0.207 — вкладка «Документы» получила человеческую витрину typed dataset
> memory: справа можно переключаться между фрагментами и «Картой» датасета,
> видеть слои, маршруты чтения, первые файлы по слоям, ограничения карты и
> статус `navigation, not evidence`. Добавлен комментарий оператора для модели:
> `PATCH /api/rag/datasets/{id}/profile/guidance` сохраняет пояснение в
> `les_dataset_profiles` и sidecar `_les_dataset_profile.json`, а
> `dataset_brief_for_model_v1` и context-memory prompt читают его как
> навигационную подсказку, не как источник фактов. Сметные нормативные архивы
> `SMETA_RU_NORM/FSNB` теперь типизируются как `normative` с ролями
> `ГЭСН/ГЭСНм/ГЭСНп/ФЕР/ФСЭМ/ФСБЦ/сплит-форма ФГИС`, а служебные
> `manifest/dataset_card/preprocess_state` мягко понижаются в top-files.
> Это делает RAG менее чёрным ящиком: оператор и модель смотрят на одну карту
> корпуса, а нормы видятся нормами, не “сметным расчётом”.

> 0.24.0.206 — общий слой typed dataset memory получил `source_layers`,
> `retrieval_routes` и компактный `dataset_source_graph_v1`: датасет теперь
> объясняет модели, какие слои есть (`text`, `tables`, `calculations`,
> `normative`, `cad_bim` и т.д.), что они значат, для каких вопросов их
> открывать и какие файлы являются первыми точками входа. `dataset_brief_for_model`
> показывает маршруты поиска и связку `слой -> файлы`, но не выводит служебный
> граф наружу и не делает фактических утверждений. Нормативный маршрут теперь
> появляется только при наличии слоя `normative`, чтобы обычная ПЗ не
> притворялась СП/ГОСТ.

> 0.24.0.205 — service notebook для смет получил отдельный `smeta_norms`
> слой: модель видит карту сметного RAG как рабочий стол сметчика — нормы,
> ресурсы, ФГИС/сплит-формы, НР/СП, формы ЛСР и проектные источники с разными
> ролями. `smeta_norm_rag_prompt_excerpt()` отдаёт маршруты по разделам
> (СКС/связь/ВОЛС -> `ГЭСНм10`, ЭОМ -> `21`, ОВ -> `18/20`, металл ->
> `09/ГЭСНм38` и т.д.), доступные коллекции и примеры полных шифров. Это
> навигация, не evidence и не candidate selector: код не выбирает норму за
> модель, а только раскрывает полный шифр после её решения.

> 0.24.0.204 — сметный skill получил явную карту сметного RAG/датасета:
> нормы, ресурсы, сплит-формы/локальные книги ФГИС ЦС, НР/СП, формы ЛСР,
> КАЦ/КП и проектные ВОР/спецификации разделены по роли. Light prompt просит
> модель писать полный шифр нормы, если она сама приняла конкретную норму.
> `smeta_artifact_service` теперь строит проверяемую РИМ-ЛСР из видимых строк
> с уже выбранным шифром: код читает графу `Обоснование`, раскрывает норму,
> переводит количество в измеритель нормы и считает trace; строки без полного
> шифра остаются в доборе. Код по-прежнему не выбирает работы или нормы за модель.

> 0.24.0.203 — ЛСР 12-графный extractor теперь берёт количество из
> графы 7 `Кол-во всего`, а цену за единицу из графы 10/8, вместо первой
> найденной колонки `Кол-во на ед.`. Это исправляет XLSX-вид, где суммы
> были рассчитаны по полному объёму, но в строках почти везде отображалось
> количество `1`.

> 0.24.0.202 — после живого 3×3 прогона СКС/БАП закрыты два
> артефактных провала ЛСР: деньги вида `17,000.00` больше не читаются как
> `17`, а строка `ВСЕГО по смете`, если модель вставила её внутрь таблицы,
> не считается отдельной сметной позицией и не задваивает итог. Оставшаяся
> нестабильность повторных прогонов относится к модельному выбору сценарных
> ставок без закрытого `норма -> ресурсы -> pricebook` trace.

> 0.24.0.201 — ЛСР-выдача перестала жить в двух реальностях:
> prompt даёт модели размеченный шаблон ЛСР граф 1-12 и обязательную строку
> `ВСЕГО по смете`, а не укороченную 8-колоночную таблицу. XLSX-экспорт с
> ЛСР теперь открывается с листа `ЛСР РИМ`, чтобы оператор сразу видел форму,
> а не диагностическую сводку. Compact-ответ удаляет конфликтующие ручные
> итоговые строки в прозе, если они расходятся с суммой выбранной ЛСР-формы;
> код при этом не выбирает работы/нормы/цены, а только не даёт двум итогам
> одновременно изображать правду.

> 0.24.0.200 — Windows/Legion parsing drain: `parse-batch` больше не
> показывает `processed=0` на больших очередях, когда партия реально разобрала
> часть файлов, а статус job становится `PARTIAL`, если после партии остался
> хвост `PENDING`. In-place добавление/синк внешней папки с `parse=true`
> создаёт видимый `rag_parse_drain` job и продолжает партии по конкретному
> датасету до исчерпания pending или bounded `max_batches`; Совушка логирует
> job id/batch/max. Это не полный reindex и не watcher: ручной контроль папки
> остаётся операторским действием, но свежий датасет больше не выглядит пустым
> после первого скрытого батча. В runtime divergence добавлены `lsr.py`,
> `rim_lsr_trace_service.py` и `rim_trace_xlsx_service.py`, чтобы сметный
> RIM-слой был виден в deploy-stamp, а не жил в зоне “ну вроде же скопировали”.

> 0.24.0.199 — добавлен короткий RIM-trace мост из уже выбранных/видимых строк
> ЛСР/ВОР: `POST /api/lsr/lsr-trace/from-rows[/export]` принимает строки с
> `basis/code` и количеством, не выбирает нормы за модель, переводит физические
> единицы в измеритель нормы (`61 м2` при норме `100 м2` → `0.61`) и строит
> `priced_partial`/`priced_final` trace. Строки без шифра или с конфликтом единиц
> остаются в `row_bindings` как добор, поэтому не могут тихо стать финальной ЛСР.

> 0.24.0.198 — артефакт ЛСР больше не складывает несколько альтернативных
> стоимостных таблиц одного ответа. Если модель дала полную `Оценку стоимости работ`
> и отдельную короткую `ЛСР (предварительная форма)`, renderer выбирает одну
> primary-таблицу для `ЛСР РИМ`, обычно самую полную таблицу стоимости работ.
> В compact-ответе добавлена проверенная сумма по строкам выбранной таблицы,
> чтобы ручной итог модели не становился главным числом при арифметической ошибке.

> 0.24.0.197 — `search_norm` получил навигационные маршруты по семействам `electric`,
> `low_current` и `finishes`: кабели, трубы кабельных трасс, коробки, устройства,
> окраска/шпатлевка/обои/потолки поднимают релевантные сборники/таблицы в shortlist
> с route-бонусом и отсевом очевидно чужих терминов. Это не выбор нормы за модель:
> код только помогает увидеть правильный раздел, а модель/сметчик выбирает норму и
> применимость. Закрывает провал, где ЭОМ-строки уходили в дорожную разметку,
> буровые машины и прочую сметную комедию.

> 0.24.0.196 — форматные команды сметы (`сделай ЛСР`, `оформи в ЛСР`,
> `добавь шифры/колонки`) больше не должны запускать новый расчёт: prompt
> и active-state явно требуют сохранять уже принятые строки, ставки и итоги.
> Активная смета больше не режет ВОР на 12 строках; в рабочую память
> передаются до 60 строк, а также обоснование, ставка, сумма и статус строки.
> Markdown-артефакт `ЛСР РИМ (форма 421/пр)` теперь начинается как отдельная
> форма ЛСР РИМ: Приложение №3, титул ЛСР, сметная стоимость, графы 1-12,
> `ВСЕГО по смете` и отдельный блок источников. Payload получил отдельный
> `rim_lsr_form`, XLSX-лист называется `ЛСР РИМ`; исходные модельные таблицы
> остаются расшифровкой, а не заменяют форму.
> Skill/role-pack дополнены порядком заполнения формы: раздел → выбранная
> норма → коэффициенты → ОТ/расшифровка → ЭМ/ОТм → М → прямые → ФОТ → НР/СП
> → всего по позиции → КАЦ/missing → итоги раздела/сметы. Это защита от
> плоской таблицы `работа/ставка/сумма` под видом ЛСР.

> 0.24.0.195 — smeta direct deterministic scenario + LSR artifact v3 + active estimate preservation.

> 0.24.0.194 — исторический промежуточный XLSX-артефакт: вместо плоской
> “почти-ЛСР” таблицы появился отдельный лист формы и лист `Источники ЛСР`.
> С 0.24.0.196 этот слой заменён на `ЛСР РИМ (форма 421/пр)` / `rim_lsr_form`.

> 0.24.0.193 — smeta direct стал устойчивее для повторов одного
> исходника: дефолтная температура модели снижена до 0, а prompt требует не
> менять базовые сценарные ставки, норм-кандидаты и группировку без нового
> источника или команды. Сметный XLSX больше не маскирует плоскую таблицу
> под ЛСР: `smeta_artifact_service` ставит отдельную форму перед
> исходными таблицами, пишет display-form с шапкой, ресурсными
> графами и явной пометкой, что без РИМ-trace/цен/НР/СП/НДС это
> предварительная форма вывода, не финальная ЛСР по форме Минстроя.

> 0.24.0.192 — вкладка «Документы» больше не прячется в `/classic`
> за admin-флагом: no-AI просмотр датасетов монтируется в обычной чат-оболочке,
> а в верхней панели чата есть явная кнопка «Документы». Backend-права
> документов остаются на API; это исправление видимости и навигации.

> 0.24.0.191 — ScopeSelector в чате больше не показывает тупиковое
> “закройте и откройте ещё раз”: по клику он дожидается `/api/scope/options`,
> имеет кнопку “Обновить список” и fallback на прямые `/api/projects` +
> `/api/rag/datasets`, если основной scope endpoint временно не ответил.

> 0.24.0.190 — Windows light hotfix: Explorer/Finder folder picker on Windows
> forces UTF-8 PowerShell stdout, while backend path validation repairs the
> common CP866-as-CP1251 mojibake for Cyrillic paths before failing `path not
> found`. Sovushka no longer polls `MLX_URL/api/health` when the active provider
> is Ollama/OpenAI/OpenRouter, removing the misleading `/api/health 404 page not
> found` noise from non-MLX Windows runs.

> 0.24.0.189 — общий Mac/Windows parity-pass для Совушки и датасетов:
> pending-внешние датасеты больше не выглядят пустыми (`doc_count/files`
> считает все зарегистрированные документы, `indexed_files/pending_files`
> идут отдельно), вкладка «Документы» показывает pending/error/missing
> статусы, внешняя in-place папка получила ручные `/api/rag/external/check`
> и `/api/rag/external/sync` для new/changed/deleted файлов, удалённые
> внешние источники помечаются `MISSING` и чистятся из Qdrant/lexical.
> Settings-router стал совместим с Pydantic v1/v2 и пишет `.env` в UTF-8;
> local preset сохраняет текущий локальный backend (MLX на Mac или Ollama
> на Windows), а non-MLX runtime status больше не стучит в
> `MLX_URL/api/host_memory`. UI разрешает выделение текста и добивает
> Quasar dark-theme контраст в диалогах/меню/диагностике.

> 0.24.0.188 — Windows light startup получил динамические порты:
> если дефолтные `8050/8051` заняты и оператор не передал `-ProxyPort` /
> `-UiPort` явно, `start-light.ps1` берёт ближайшие свободные порты,
> прокидывает `PROXY_URL`, `SOVUSHKA_UI_PORT` и CORS под выбранную пару,
> пишет `logs/windows-light-state.json`, а `tools.les_shell` читает этот
> state-файл и открывает фактический URL Совушки. Явно переданные порты
> сохраняют старое поведение: процесс на указанном порту останавливается и
> порт переиспользуется.

> 0.24.0.187 — Совушка получила локальный системный выбор папки
> `Explorer/Finder…` для операторских сценариев: быстрое добавление датасета,
> in-place индексация внешней папки и скан карты архива. Новый маршрут
> `/lite-runtime/pick-folder` открывает native folder dialog только при
> loopback-доступе к UI; удалённый trusted/public клиент не может случайно
> открыть папку на сервере. Старый серверный `Обзор…` оставлен как fallback и
> для безопасной навигации по разрешённым корням.

> 0.24.0.186 — Windows/Mac runtime status portability pass: shared runtime
> status no longer crashes on Windows when Unix `ps` is unavailable. Memory
> preflight now uses Windows `tasklist` for process inventory and command
> re-checks, treats core Windows processes such as `Memory Compression` as
> protected, and returns empty inventories instead of 500s when a platform
> command is missing. Runtime dispatcher background jobs now use
> platform-specific `Popen` kwargs (`start_new_session`/`close_fds` on POSIX,
> Windows process-group flags when available), and PID status checks avoid
> zombie-only `ps` probing on Windows.

> 0.24.0.185 — Windows installer/bootstrap no longer fails with
> “загрузка моделей не удалась” when the active provider is Ollama,
> Lemonade or another OpenAI-compatible local server. The historical
> `tools/onboard_models.py --skip-if-cloud` flag now skips Hugging Face /
> MLX weight downloads for providers that do not need local HF weights. Root
> cause on Legion: `%LOCALAPPDATA%\LES\logs\bootstrap.log` showed failure at
> `uv run python tools\onboard_models.py --skip-if-cloud`; `.env` had
> `LES_LLM_PROVIDER=ollama`, but the old script still tried to resolve/download
> `MLX_MODEL=mlx-community/Qwen3.5-4B-OptiQ-4bit` and failed because the
> Windows desktop extra does not install `huggingface_hub`.
> 0.24.0.184 — Windows/Legion light startup fix: `start-light.ps1`
> запускает proxy/UI через `cmd.exe /c uv run ...`, потому что прямой
> `Start-Process uv -ArgumentList ...` на Legion мог завершать launcher после
> build/sync, оставляя `8050/8051` закрытыми при почти пустых логах. Скрипт
> теперь ждёт `/api/health` до 45 секунд и возвращает реальный startup status.
> На Legion дополнительно снят старый `git sparse-checkout`, из-за которого
> в `C:\Users\Oleg\les_rag` отсутствовали `proxy/`, `sovushka/` и
> `installers/`; после восстановления полного checkout `8050`, `8051` и
> `/classic` поднялись.
> 0.24.0.183 — dataset notebooks/profile/brief перестали слепнуть, когда
> deep lexical `top_documents` пустой или старый cached typed memory не имеет
> `important_files`. `context_memory_service` добавляет `top_documents` из
> MetaDB `documents` как navigation fallback и backfill-ит cached profiles на
> чтении; `notebook_service` показывает `priority_files` и включает их в
> prompt excerpt; `dataset_memory_service` выбирает role-priority файлы, а при
> отсутствии ролей — indexed/chunk-rich файлы. Вкладка «Документы» добавлена
> не только в админку, но и в chat shell `/classic` для admin/trusted
> оператора. Это навигация для модели и оператора, не evidence и не готовый
> ответ.
> 0.24.0.182 — Совушка получила no-AI вкладку «Документы» в админке:
> датасеты → документы → фрагменты, поиск по выбранному датасету/документу
> или всему индексу и копирование списка источников для артефакта. Document
> Explorer API расширен `doc_id`-маршрутами:
> `GET /api/documents/by-id/{doc_id}` и
> `GET /api/documents/by-id/{doc_id}/chunks`; `GET /api/documents/search`
> принимает `doc_id`. Если в старом/живом индексе `documents.id` не совпал с
> `lexical_chunks.doc_id`, чтение падает назад на устойчивую пару
> `dataset_id + file_name`. Старые маршруты по `dataset_id/doc_name`
> сохранены. Слой остаётся навигационным: модель отвечает, код только
> показывает корпус.
> 0.24.0.181 — Windows light installer/startup fix: `start-light.ps1 -StartQdrant`
> больше не делает слепой `docker rm -f`, а переиспользует running/existing
> `les-light-qdrant` или создаёт его при отсутствии. Это сохраняет локальный
> Windows Qdrant между запусками и убирает падение первого запуска, если
> контейнер ещё не существовал.
> 0.24.0.180 — добавлен no-AI Document Explorer API: прямой
> просмотр и поиск по датасетам/документам через MetaDB `datasets` /
> `documents` и SQLite `lexical_chunks`, без вызова модели. Эндпоинты:
> `GET /api/documents/datasets`, `GET /api/documents/datasets/{dataset_id}/documents`,
> `GET /api/documents/datasets/{dataset_id}/chunks/{doc_name}` и
> `GET /api/documents/search`. Это база для нормального проводника документов,
> поиска по документу/датасету и будущего read-only WebDAV; выводы и ответы
> по-прежнему делает модель в RAG-режиме, а этот слой показывает источники.
> 0.24.0.179 — RAG-поиск закрепляет model-first нормативный маршрут:
> модель идёт `норма → пункт → вывод`, а код помогает навигацией по
> датасету, не готовым ответом. `dataset_brief_for_model_v1` теперь
> добавляет «Нормативную навигацию»: список нормативных файлов-кандидатов
> из file cards, напоминание открыть документ через retrieval/doc_filter и
> искать внутри пункт/таблицу/приложение; для развилок «требуется / не
> требуется» модель должна искать обе стороны нормы и не додумывать
> отсутствующую. RAG skill/role-pack фиксируют этот контракт. `clause_lookup`
> остаётся deterministic final только для явных запросов «найди пункт /
> раздел / приложение» и узкого established shortcut «исключения
> дымоудаления → СП 7.13130 п. 7.3». `retrieval_service` и
> `clause_lookup_service` включены в deploy-stamp critical files, чтобы
> drift нормативного поиска был виден в `/api/version`.
> 0.24.0.178 — центральный `LES_TONE_PROMPT` вернул фирменный голос:
> живой инженерный тон, короткая едкость к бардаку в данных/пустым таблицам/
> мутным ТЗ и канцеляриту, но уважение к оператору и строгая дисциплина для
> чисел, норм, цитат, ЛСР/КС и официальных текстов. Локальный нормативный
> prompt больше не запрещает весь юмор подряд: вместо стерильного «без шуток»
> стоит «без балагана», с допустимой короткой живой репликой вне таблиц/цитат.
> 0.24.0.177 — prompt получает `dataset_brief_for_model_v1` вместо полного
> служебного dump typed memory: brief компактно объясняет модели, что за корпус
> выбран, какие файлы открывать первыми, как `file_name` связан с Qdrant /
> `lexical_chunks` / `doc_filter`, и какой маршрут чтения подходит под текущий
> вопрос. Это навигация, не evidence: модель и режимный prompt остаются выше,
> факты берутся только из retrieved фрагментов, таблиц, графа или расчёта.
> 0.24.0.176 — `smeta_direct` артефакт получил дополнительный вид
> `lsr_display_form_v1`: по уже написанным моделью строкам стоимости строится
> раздел «Форма ЛСР» и отдельный лист `ЛСР` в XLSX. Это форма вывода, не новый
> расчёт: сервис не добавляет работы, не выбирает нормы и не меняет ставки.
> 0.24.0.175 — broad-запросы по выбранному датасету/проекту перед
> `notebook_study` теперь best-effort готовят модельный `reader-pass`
> (`reader_output`) для карты корпуса: если он уже готов — используется
> сразу, если не успевает за лимит — ставится фоновая задача, а ответ идёт
> по bootstrap-карте и найденным источникам. Реестр MetaDB строится и для
> `notebook_study` как навигация выбора файлов, но не перетирает видимый
> инженерный артефакт. Артефакт «Инженерный блокнот» включён по умолчанию.
> 0.24.0.174 — выбранный в UI датасет (`dataset_ids`) теперь считается
> полноценной областью для `DeterministicFinalPolicy`: описательные
> проектные вопросы вроде «расскажи про проект» не перехватываются
> глоссарием даже при совпадении коротких стадийных/документных терминов
> (`ПД`, `ИЦ`, `ИД` и т.п.). Явное «что такое ОЖР/КАЦ» по-прежнему идёт
> в glossary.
> 0.24.0.173 — Совушка больше не превращает inline-маркеры
> `[Источник N]` в зелёные blockquote-простыни внутри ответа. Явные строки
> `Источники: ...` выносятся из пузыря в Markdown-артефакт
> `Источники ответа`; в самом ответе остаётся короткая ссылка на артефакт,
> source chips и кнопка «С источниками». Payload `source_map` теперь
> прокидывается в UI meta, чтобы артефакт мог показать перечень источников
> без повторной генерации и без подмены RAG-логики.
> 0.24.0.172 — RAG-поиск и нормоконтроль получили такой же слой
> prompt/skill-контракта, как сметный режим: `prompt_registry_service`
> отдаёт role-pack'и `rag_search_researcher_v1` и `normcontrol_reviewer_v1`,
> а подробная рабочая дисциплина вынесена в `skills/rag_search/SKILL.md` и
> `skills/normcontrol/SKILL.md`. Инвариант общий: модель связывает источники
> и формулирует вывод/замечания, код только ищет, ранжирует, считает,
> проверяет layout/formal и отдаёт trace; missing не становится фактом,
> pass или fail.
> 0.24.0.171 — smeta skill/role-pack закрепили алгоритм сметчика для
> Excel round-trip: таблица кандидатов разделена на блок `Данные ТЗ / ВОР`
> и блок `Соответствие данным ТЗ / ГЭСН`; видимый `№ ВОР` не является
> стабильным ключом; связь держится на `vor_row_id`/`source_row_id`; новые
> или изменённые строки получают новый подбор кандидатов, а пользовательские
> варианты подбора не смешиваются молча.
> 0.24.0.170 — smeta prompt/skill уточнили нормативный маршрут:
> раздел ВОР не равен одному сборнику; по каждой работе нужен shortlist
> кандидатов по действию, объекту, измерителю и составу работ. `ГЭСНм10`
> не должен натягиваться на силовую ЭОМ без явной применимости; голые коды
> без типа базы запрещены из-за коллизий вроде `ГЭСН10`/`ГЭСНм10`.
> 0.24.0.169 — исправлена кнопка скачивания файловых артефактов Совушки:
> `ui.download(...)` больше не вызывается из `asyncio.create_task`, поэтому
> NiceGUI не теряет UI-контекст при скачивании XLSX/CSV.
> 0.24.0.168 — Совушка регистрирует `artifact.downloads` сметного ответа
> как файловые артефакты в панели «Файлы»: XLSX/CSV можно открыть в панели
> или скачать кнопкой сразу после ответа.
> 0.24.0.167 — `smeta_direct` artifact получил выгрузку XLSX и CSV:
> `smeta_artifact_service` сохраняет модельные Markdown-таблицы как листы Excel
> и CSV-разделы, а payload `artifact.downloads` отдаёт ссылки
> `/api/smeta-artifacts/download`. Prompt/skill ужесточены по источникам строк
> стоимости: нельзя писать одиноко `ГЭСНм`/`ГЭСН`; нужен сборник, раздел,
> таблица или код-кандидат, а сценарная ставка маркируется явно.
> 0.24.0.166 — `smeta_direct` получил отдельный Markdown-artifact для длинных
> сметных таблиц. `smeta_artifact_service` извлекает уже написанные моделью
> таблицы ВОР/стоимости/развилок, считает видимые суммы по колонкам
> `Сумма/Стоимость/Итого`, кладёт полный расчёт в payload `artifact` и может
> схлопнуть длинную таблицу в чате до короткой ссылки на артефакт. Сервис не
> выбирает работы, нормы, ставки или применимость.
> 0.24.0.165 — smeta direct закрепляет правило для спецификаций с пустыми
> ценовыми колонками: отсутствие заполненных цен материалов/работ означает
> missing по поставке или прежней смете, но не блокирует оценку монтажных
> работ. По измеримым строкам модель должна построить ВОР, отделить поставку
> и дать построчную стоимость работ с честным статусом/допущениями.
> 0.24.0.164 — smeta direct получил source discipline без региональных
> костылей и без пост-редактора ответа: light prompt видит компактную карту
> `SMETA_SERVICE`, полный список доступных локальных pricebook и правило
> сначала проверять RAG/источники ЛЕС. Если книга, сборник или нормативная
> база доступны, модель должна писать, что источник есть, а до финального РИМ
> остаются выбор нормы, раскрытие ресурсов, exact-match ценовой строки,
> регион/период или условия применимости.
> 0.24.0.163 — smeta runtime polish после живых прогонов СКС/столпа:
> быстрый `smeta_direct` fallback больше не выводит наружу машинные статусы
> `scenario_estimate/priced_final`, а пишет человечески: предварительная
> РИМ-оценка по допущениям, не финальная ЛСР. Для СКС и тяжёлых
> металлоконструкций добавлена видимая нормативная опора из локального RAG
> (`ГЭСН 10`, `ГЭСН 09`, `ГЭСНм 38`, pricebook `spb_2kv2026`), чтобы ответ
> был не рыночной магией, а РИМ-сценарием по нормативным аналогам до закрытия
> ресурсной ФГИС-трассы.
> 0.24.0.162 — добавлен первый лёгкий LES core слой: `les_module_service`,
> универсальный `active_state_service`, `scoped_rag_builder`,
> `skill_snippet_registry` и `tool_trace_policy`. Смета остаётся первым
> модулем, но не центром архитектуры. `smeta_direct` получил аварийный
> быстрый composer `smeta_fast_answer_service`: если локальный LLM timeout/empty,
> измеримые СКС/тяжёлые ярусные ТЗ получают видимую сценарную РИМ-таблицу
> вместо пустого ответа. Локальный MLX runtime теперь берёт `LLM_MODEL`, затем
> `MLX_MODEL`, а не устаревший `qwen3:14b`; для local smeta direct снижены
> default timeout/max_tokens, чтобы fallback включался живо.
> 0.24.0.161 — дефолтный guard парсинга RAG снижен с `8` до `7` GB
> свободной RAM (`RAG_PARSE_MIN_FREE_GB` всё ещё может переопределить значение
> через env). Это помогает дренировать smeta norm batches на текущем Mac без
> ручного рестарта MLX между малыми batch-ами.
> 0.24.0.160 — Smeta.RU norm ingest раскрывает вложенные `.vnbx` как ZIP:
> пишет nested inventory и markdown-проекции внутренних `.json/.xml/.txt/...`
> в RAG. Это даёт модели машинно-читаемые слои архива до отдельного
> структурного Parquet-parser.
> 0.24.0.159 — auto-ingest Smeta.RU больше не копирует поддерживаемые исходные
> документы из архива в RAG по умолчанию (`--max-source-files` default `0`):
> raw остаётся в `storage/extracted`, а RAG получает manifest/classifier/text
> projections. Это защищает автоиндекс от подвисания на больших XLSX внутри ZIP.
> 0.24.0.158 — `tools/smeta_ru_norm_rag_ingest.py` по умолчанию синхронизирует
> только подкорпус `RAG_Content/TABLE_SMETA/SMETA_RU_NORM`, чтобы новый архив
> регистрировался как smeta norm dataset без сканирования всего `RAG_Content`.
> 0.24.0.157 — добавлен `tools/smeta_ru_norm_rag_ingest.py`: worker скачивает
> архивы Smeta.RU по одному, распаковывает, пишет RAG-projection cards и
> machine provenance в `RAG_Content/TABLE_SMETA/SMETA_RU_NORM`, вызывает
> `sync-smart` после каждого нового архива, ведёт resume-state и раскладывает
> категории в датасеты `SMETA_RU_NORM_<CATEGORY>_Index`. Для модели этот
> RAG-корпус является источником истины нормативной базы; raw ZIP/storage
> остаются provenance и воспроизводимостью.
> 0.24.0.156 — добавлен `tools/smeta_ru_norm_download.py`: Python-downloader
> публичных архивов `https://smeta.ru/download/norm`. Он извлекает прямые
> `obs.smeta.ru/*.zip` ссылки, поддерживает `--latest fsnb2022`, `--pattern`,
> `--with-head`, скачивание в `storage/downloads/smeta_ru_norm`, `sha256`
> manifest и опциональный extract. Архивы не считаются готовым расчётным
> источником до отдельного парсинга/импорта.
> 0.24.0.155 — добавлен `tools/smetnoedelo_rag_import.py`: безопасный
> Smetnoedelo API v2.0 → markdown-карточки для сметного RAG. Импорт поддерживает
> базы `gesn2/gesnm2/gesnmr2/gesnp2/gesnr2`, `fsbcm/fsbco/fsbcmm` и ресурсные
> `fsem/fsscm/fssco`, берёт токен только из env `LES_SMETNOE_TOKEN`, кеширует
> ответы без секрета, останавливается по `--max-requests` и может вызвать
> `POST /api/rag/sync-smart` для регистрации/парсинга. Это RAG-навигация для
> модели, не замена расчётному Parquet/trace.
> 0.24.0.154 — default light `smeta_direct` сохраняет свободную модельную форму, но добавляет
> два точечных инварианта: сценарная сумма должна иметь видимую базу расчёта, а запросы на
> коды/номера ГЭСН продолжают активную ВОР через RAG/поиск норм и возвращают кандидата/раздел
> вместо отказа. `active_smeta_state` расширен методикой, последней таблицей/действием,
> допущениями и открытыми развилками; role-pack получил отдельные `rim_scenario_estimate` и
> `market_scenario_estimate` как машинные статусы fallback/тестов.
> 0.24.0.153 — default light `smeta_direct` упрощён под сильную модель:
> короткий system prompt с ролью/границами и короткий user template
> «новая задача или продолжение активной сметы». Из default path убраны
> специализированные микроправила про ГЭСН/ФГИС/НР/СП, follow-up-команды и
> формат секций; их место — active_smeta_state, RAG/skill и tests/golden.
> 0.24.0.152 — direct smeta теперь сохраняет компактное
> `active_smeta_state` из видимого ответа: задача, рабочий вариант, исключения
> и строки ВОР из таблиц. Следующие smeta-сообщения получают это состояние
> отдельным блоком «Активная смета», поэтому команды вроде «добавь номера
> ГЭСН» должны продолжать текущую смету, а не полагаться на длинный prompt или
> пересказ прошлого ответа.
> 0.24.0.151 — light `smeta_direct` получил отдельную форму для продолжений
> расчёта: запросы вида «добавь номера ГЭСН», «подпиши нормы», «поправь
> таблицу» работают поверх предыдущей ВОР/оценки из диалога и возвращают
> изменённый фрагмент, а не полный 10-блочный ответ и не просьбу прислать ВОР
> заново, если строки уже есть в истории.
> 0.24.0.150 — `_smeta_direct_model_answer` по умолчанию использует короткий
> light prompt вместо полного role-pack/system-contract: модель получает
> вопрос, вложения, RAG и arithmetic trace, а главная установка простая —
> если доступна нормативная база и пользователь просит оценку/смету, дать
> РИМ-сценарий по нормативным аналогам с допуском, не заменяя его широкой
> рыночной вилкой. Тяжёлый prompt сохранён для регрессий и включается через
> `LES_SMETA_DIRECT_LIGHT_PROMPT=0`.
> 0.24.0.149 — smeta direct/skill/role-pack меняют дефолт обычной
> «оценки стоимости»: если пользователь просит оценку/стоимость/смету
> строительных работ и не задаёт рыночный метод, а в контексте доступны
> ГЭСН/ФГИС/НР/СП или сметно-нормативная база, основным числовым ответом
> должен быть РИМ-сценарий по нормативным аналогам. Рынок допустим только
> как sanity-check или отдельная оценка по явной просьбе.
> 0.24.0.148 — smeta direct/role-pack получили отдельный режим
> `rim_scenario_estimate`: если пользователь просит РИМ/ГЭСН и разрешает
> оценку, модель не должна заменять РИМ свободной рыночной вилкой. Даже без
> полного `priced_final` она обязана дать РИМ-сценарий по нормативным аналогам:
> нормируемая строка, сборник/аналог, объём в измерителе нормы, базовая точка
> расчёта, НР/СП/индексы/НДС как допущения, сумма, допуск и добор до final.
> Это не финальная ЛСР, но это числовой РИМ-ответ.
> 0.24.0.147 — предметный прогон СКС/столпа выявил runtime-слой поверх
> prompt-контракта: DOCX attachment context несёт таблицы как
> `source_ref#tNrM: cell | cell`, и numeric audit должен снимать этот
> префикс перед разбором строк. `_smeta_direct_numeric_audit_context`
> теперь на реальном DOCX столпа находит сумму всех строк, partial match
> строк 1-10 и `source_delta`. Для локального MLX/Qwen direct smeta calls
> добавлен `<think></think>` prefill: без него endpoint может отвечать
> пустым `content`. Оставшийся риск live-прогона — latency: полный
> `smeta_direct` prompt на локальном MLX всё ещё уходит в timeout на
> СКС/столпе и требует отдельного укороченного runtime-контракта или
> streaming/native generation path.
> 0.24.0.146 — smeta skill/role-pack/direct prompt получили слой
> `ВОР -> нормируемая ВОР -> таблица подбора норм`: модель показывает
> кандидаты ГЭСН/ГЭСНм напротив строк ВОР, одна исходная строка может
> раскладываться на несколько норм при технологическом основании, Excel
> round-trip подтверждает/исключает кандидаты, а расчёт РИМ идёт только
> по подтверждённым или явно выбранным строкам. Видимый ответ дополнительно
> чистится от служебной лексики `role-pack`/`harness`/`slots`/`shortlist`;
> missing-цена может быть черновым пробелом, но не ценой 0 руб. После
> регрессионного прогона восстановлена совместимость старого harness-формата:
> explicit work в auto-профиле снова идёт через harness, частичные деньги
> показываются как закрытая часть протокола, а formula/default gates не
> выбирают работы, а только считают уже предложенные моделью строки.
> 0.24.0.145 — smeta direct visible prompt дополнительно запрещает
> выводить внутреннее слово `evidence` в пользовательскую сметную речь:
> вместо него использовать «источник», «подтверждение» или «расчётная трасса».
> 0.24.0.144 — smeta direct prompt теперь явно требует показывать
> `source_delta` из deterministic numeric audit в видимом контроле чисел:
> малое расхождение между исходными итогами не должно теряться на фоне
> крупного расхождения суммы строк/состава.
> 0.24.0.143 — live-прогон СКС/столпа выявил две системные проблемы:
> numeric audit не считал markdown-таблицы DOCX с крайними `|`, поэтому
> реальная таблица масс не давала trace по сумме всех строк и partial match
> `rows_1_N`; `_split_table_line` теперь нормализует такие таблицы и audit
> принимает короткие строки из 3 ячеек. Дополнительно smeta direct prompt
> очищен от видимой утечки внутренних запретов и машинных статусов: модель
> должна отвечать русской речью сметчика, а `scenario_assumption` /
> `scenario_estimate` / `priced_final` переводить наружу как сценарное
> допущение, сценарная оценка и финально закрыто источниками.
> 0.24.0.142 — smeta skill/role-pack получили универсальный слой
> `specification_to_bor`: спецификация больше не считается готовой сметой,
> модель сначала делит строки на поставку/работы/комплектующие/крепёж,
> сохраняет parent/child-иерархию и строит ВОР-кандидат до выбора норм.
> Добавлен `quantity_trace_service` для расчётной трассы количества
> (`direct_from_spec`, `parent_child_calculated`, `unit_conversion`,
> `missing_quantity`): сервис считает формулы и единицы после решения
> модели, но не выбирает работы или нормы. Skill также получил мягкую
> карту нормативных маршрутов по разделам (СКС, электрика, ОВ/ВК,
> металлоконструкции, МАФ, покрытия) без case-specific констант.
> 0.24.0.141 — добавлен точечный официальный overlay-import ГЭСН/ГЭСНм из
> ФГИС ЦС JSON (`tools/gesn_fgis_overlay_import.py`) для дозаливки
> `data/gesn_base/gesn2022_v2.parquet` без полного bulk-import. Для СКС
> дозалит preset `sks`: 166 норм / 869 ресурсных строк, в основном
> `ГЭСНм10` по кроссам, стативам, ВОЛС, сварке, измерениям и приемке.
> `smeta_norm_store` теперь ранжирует FTS-кандидатов через строгие
> совпадения всех терминов, чтобы редкие технические нормы вроде
> `ГЭСНм10-06-058-01` не тонули под общими строительными совпадениями
> слова "сварка". Код по-прежнему не выбирает применимость нормы.
> 0.24.0.140 — smeta_direct запрещает схлопывать измеримую спецификацию/ВОР
> в несколько укрупнённых корзин с широкой вилкой. Если строки работ понятны,
> стоимость работ должна идти построчно: раздел, работа, количество, единица,
> ставка/источник, статус, сумма; диапазоны допустимы как сводка после строк.
> 0.24.0.139 — numeric audit context для smeta_direct отдельно показывает
> `source_delta` между конфликтующими исходными итогами, чтобы маленькое
> расхождение источников не терялось на фоне крупного расхождения суммы строк.
> 0.24.0.138 — smeta_direct получает deterministic numeric audit context из очевидных
> mass-таблиц вложения: калькулятор считает сумму строк, сравнивает с текстовым и табличным
> итогом, ищет partial match вида `rows_1_N` и отдаёт trace в prompt. Это не выбирает работы,
> нормы или договорный объём, но запрещает модели снова руками промахнуться по длинному ряду.
> 0.24.0.137 — smeta_direct приведён к устойчивому контракту: role-pack
> стал тонким машинным JSON (статусы, типы источников, capabilities, порядок
> секций, hard rules и колонки таблиц), direct prompt закрепляет 9-блочный
> видимый ответ и сравнительную таблицу РИМ/ГЭСН vs рынок, а
> `estimate_math_service` получил generic arithmetic/quantity audit helper
> для русских чисел, кг↔т, сумм, процентов, partial matches и trace. Добавлена
> regression-fixture по конфликту масс и no-case-constants тест, чтобы частные
> числа не попадали в system prompt/role-pack.
> 0.24.0.136 — smeta visible answer получил компактное оформление:
> direct/harness prompt запрещает Markdown-заголовки `#`, `##`, `###` в
> обычном чат-ответе и требует короткие жирные метки секций; Совушка
> дополнительно ограничивает размеры `h1`-`h6` внутри `.sov-chat-md`, чтобы
> случайные старшие заголовки не раздували ответ.
> 0.24.0.135 — smeta role-pack/skill/direct prompt получили более широкую
> свободу для запросов вида "дай оценку, чего не хватает — можешь придумать":
> модель обязана выбрать нейтральные assumptions, дать числовой диапазон и
> только потом перечислить добор до final. Запрос двух оценок рынок/РИМ теперь
> требует сравнительную числовую таблицу со статусами источников; отсутствие
> КП/ФГИС-строк не отменяет scenario-цифры, если допущения разрешены.
> 0.24.0.134 — smeta role-pack/skill/direct prompt получили приоритет
> РИМ/trace над свободной рыночной ставкой: после решения модели по работе,
> норме и объёму расчётная трасса `calculation_trace` показывается раньше
> `scenario_assumption`. Код остаётся калькулятором выбранного моделью хода,
> не выбирает операции и нормы.
> 0.24.0.133 — smeta direct/role-pack/skill усилены после live-прогона:
> запрос на смету/стоимость/оценку по измеримой ВОР считается разрешением
> на сценарные допущения по работам, если пользователь их явно не запретил.
> Сценарные рубли по работам должны идти до уточняющих вопросов и добора
> до `priced_final`.
> 0.24.0.132 — smeta role-pack/skill/direct prompt закрепляют правило:
> если ВОР содержит измеримые работы, ЛЕС обязан попытаться вывести стоимость
> работ отдельно от поставки. Незакрытая поставка, добор цен или условия
> применимости понижают статус до `priced_partial`, `resources_expanded` или
> `scenario_estimate`, но не превращают ответ в отказ. Частные кейсы и примеры
> в system/role-pack не добавлялись.
> 0.24.0.131 — справочник НР/СП расширен по сборникам ГЭСН и ГЭСНм:
> прямой путь `code -> база:сборник -> НР/СП` покрывает больше
> общестроительных и монтажных сборников, поддерживает голые шифры из
> parquet-базы, а официальные подвиды внутри сборника могут переопределять
> общий сборник через `collection_match_priority`.
> 0.24.0.130 — НР/СП code-only ЛСР переведены с префиксной эвристики на
> системную классификацию по базе и номеру сборника нормы: `nr_sp_service`
> нормализует шифр в ключ `база:сборник`, сверяет его со справочником
> `collections`, затем использует текстовое совпадение только как fallback.
> Частные расчётные примеры в системные решения не добавлялись.
> 0.24.0.129 — убрана слишком узкая текстовая эвристика НР/СП: вместо
> распознавания вида работ по фразе из названия нормы `nr_sp_service`
> сначала проверяет нормативный шифр/префикс сборника, затем имя позиции/нормы.
> Это справочное правило по сборнику, а не case-specific подгонка под расчёт.
> 0.24.0.128 — причина “нет денег” по столпу локализована и закрыта в
> калькуляторе ЛСР: ГЭСН и ФГИС price books были доступны, но `/assemble`
> при позиции только `{code, qty}` не подтягивал НР/СП, поэтому отдавал
> прямые затраты без хвоста. Теперь `lsr_assembly_service` подставляет НР/СП
> по имени позиции/нормы, если проценты не переданы явно; `nr_sp.yaml`
> перестал ловить слово “сборка” как “сборные ЖБ”.
> 0.24.0.127 — конфликтная smeta-форма переименована в «форму развилки
> исходных объёмов» / `quantity_conflict_form_policy`, чтобы термин
> `split-form` остался только за сплит-формой ФГИС ЦС. `SMETA_MECHANICS`
> дополнен допустимыми промежуточными результатами, continuation/change
> поверх предыдущей оценки, правилом длинных рядов через calculator/trace,
> direct answer без итоговых рублей без источника, давальческим `0 руб`,
> смешанными источниками и одинаковым физическим объёмом в разных операциях.
> 0.24.0.126 — smeta direct/role-pack/skill закрепляют числовую дисциплину
> без case-specific системных решений: существенные числовые утверждения
> требуют расчётной трассы, конфликт исходных объёмов должен идти через
> форму развилки договорной величины, прежняя оценка/xlsx/форма развилки в
> контексте считается источником сверки. Конкретные регрессии запрещено заносить в
> system/role-pack как готовые ответы; они остаются в тестах/fixtures/skill-
> уроке. Добавлен единый актуальный док [SMETA_MECHANICS.md](SMETA_MECHANICS.md).
> 0.24.0.125 — smeta direct стал source-aware и строже к принятой ВОР:
> если служебные источники ГЭСН/ФГИС имеют статус `ok`, модель не должна писать
> «пользователь не дал сплит-форму», а должна сказать, что база доступна, но
> нужны выбранная норма/ресурс/ценовая строка. Также запрещено вводить спор
> массы без калькулятора и превращать упаковку/такелаж в отдельные платные
> разделы без явной команды оператора.
> 0.24.0.124 — smeta direct-answer стал bounded: модель должна отвечать
> завершённо, максимум 6 коротких разделов, обязательно с финальным «Итогом»,
> не начинать с отказного нытья «денег нет», не раздувать чек-лист уточнений и
> не заменять заданные оператором разделы (например демонтаж) спорной упаковкой
> или нулевой логистикой.
> 0.24.0.123 — smeta system prompt сжат до жёсткого поведенческого
> каркаса: role-pack больше не сериализуется целиком в system, а рендерится как
> компактный машинный контракт (статусы, типы цен, hard rules, visible answer
> contract, shape `smeta_work_plan_v1`). `skills/smeta/SKILL.md` переписан как
> короткий runtime-контракт агента: инварианты, ВОР, выбор нормы, деньги,
> статусы, запреты и регрессионные ошибки; API/roadmap оставлены ссылками.
> 0.24.0.122 — smeta role-pack/direct prompt/skill усилены для технологических
> смет по одному изделию/конструкции: модель должна сохранять строгую структуру
> разделов из ТЗ, выводить нулевые этапы отдельно, считать проверяемую ВОР-
> арифметику по ярусам/стыкам/болтам/массе до выбора норм и отделять готовую
> ВОР от незакрытых ГЭСН/ФГИС/КАЦ рублей.
> 0.24.0.116 — RAG prompt получил роль опытного инженера-строителя/
> проектировщика: широкие вопросы читаются как обзор корпуса/проекта
> (объект, состав, технические решения, конфликты, пробелы), карта датасета
> используется как навигация, вопросы по конкретному файлу не уходят в соседние,
> а видимые ответы не должны тащить служебные payload-слова.
> 0.24.0.115 — direct smeta получил отдельный prompt опытного сметчика вместо
> режима `smeta_harness`: роль, рабочая петля, спецификация→ВОР→сметный путь,
> правила источников/цен и стабильная форма ответа. Пользовательский prompt для
> direct-ответа стал обычным русским текстом без машинного JSON-каркаса; температура
> снижена по умолчанию для повторяемости.
> 0.24.0.114 — при включённом direct model-first сметный код больше не
> подменяет молча модель старым `run_estimate_harness`, если модель не вернула
> видимый ответ. По умолчанию оператор видит сбой сметчика-модели; аварийный
> code-fallback включается только явно через `LES_SMETA_CODE_FALLBACK_AFTER_MODEL_FAIL=1`.
> 0.24.0.113 — short-lived `smeta_table_calculator` убит: direct smeta больше
> не получает кодовую табличную подложку и не видит классификацию/арифметику,
> собранную кодом. Табличное вложение читает модель через обычный
> attachment+skill+scoped RAG путь; код остаётся только будущим calculator/tool
> после модельного решения.
> 0.24.0.112 — сметный direct-ответ по таблице очищен от машинных
> классификаций и англо-служебных слов: модель больше не видит колонку
> row-type, а видимый ответ запрещает `evidence`/`provenance`/`BoM` и говорит
> нормальным русским языком сметчика. Живой СКС-прогон держит ход
> «спецификация → ВОР → сметный путь».
> 0.24.0.111 — явный режим «Смета» при приложенной таблице строит
> калькуляторную подложку: строки таблицы, очевидные множители, упаковки,
> минимальные поставки и простые суммы с provenance. Это контекст для
> сметчика-модели, а не готовый ответ кодом: модель решает, перед ней
> спецификация, ВОР или смесь; если это спецификация, сначала предлагает ВОР,
> а затем сметный ход. Код только считает проверяемую арифметику. Флаг
> `LES_SMETA_TABLE_CALCULATOR=0` полностью убирает этот слой из direct smeta.
> 0.24.0.110 — direct smeta RAG-пакет больше не включается по автоматическому
> `TABLE`/широкому inference, если оператор только приложил файл. Без явного
> dataset/project scope модель работает по вложению, а не по случайному соседнему
> корпусу.
> 0.24.0.109 — явный режим «Смета» при выбранном dataset/project/target-file
> scope получает компактный RAG-пакет: top chunks, source map и навигационную
> память датасета. Это контекст для сметчика-модели, а не детерминированный
> ответ; кодовый harness всё ещё не фильтрует видимый ответ заранее.
> 0.24.0.108 — явный режим «Смета» теперь идёт от обратного: видимый ответ
> сначала пишет сметчик-модель по полному `harness_question`/вложению и smeta
> skill, без запуска кодового harness как предварительного фильтра. Harness
> остаётся fallback/калькулятором/проверкой provenance; флаг
> `LES_SMETA_DIRECT_MODEL_FIRST` по умолчанию включён для explicit Smeta и не
> трогает auto-routed work estimate.
> 0.24.0.107 — если сметный harness полностью заблокировал все позиции
> (`blocked`, 0 computed), видимый ответ больше не строится как кодовая таблица
> отказов. Модель получает полный `harness_question` и компактный
> `blocked_harness_advisory`, сама даёт сметный разбор/ведомость количеств/
> ценовые пробелы, а кодовый blocked-протокол остаётся в trace/artifact.
> 0.24.0.106 — сметный chat/harness перестал создавать ложный “обрыв ТЗ”:
> work-plan получает динамический budget ответа для длинных ТЗ/ВОР/вложений, а
> видимый smetnik-comment теперь строится от того же `harness_question`, что и
> расчётный планировщик. Комментатор получает compact excerpt и дополнительно
> фильтруется от неподтверждённых заявлений “файл/ведомость оборвались, пришлите
> продолжение”, если расчётный payload сам этого не доказывает.
> 0.24.0.105 — сметный harness разделяет найденные числа и расчётные слоты:
> `parse_params()` может найти объёмы/массы/площади/штуки как `quantity_candidates`
> с provenance, но в широком ТЗ/ВОР/объектной смете эти числа больше не становятся
> глобальными входами калькулятора. Модель обязана привязать нужный кандидат в
> `slots` конкретной work-позиции; код считает только после такой привязки или
> в узком прямом запросе “посчитай эту работу с этим объёмом”.
> 0.24.0.104 — ещё один срез кода-няньки: `BATCH_TOOL_CONTRACT`
> теперь описывает только машинный JSON shape и допустимые ids, а не профессию
> сметчика. Поведение сметчика перенесено/закреплено в JSON role-pack и
> `skills/smeta/SKILL.md`. Там же добавлено общее правило для вложенных ВОР/спецификаций:
> если строка дана “для 1 изделия/узла”, родительское количество является множителем,
> а родительскую строку сборки нельзя автоматически считать вместе с детальной
> расшифровкой. `_object_area_from_text` больше не превращает площади отдельных
> строк вроде `0,07 м²/шт` в площадь объекта.
> 0.24.0.103 — сметный harness срезал второй старый протокол: legacy
> `{tool,args}` loop и его отдельный prompt больше не исполняются как runtime-путь.
> Если модель вернула старый tool-call, harness просит переписать тот же смысл
> в единый `smeta_work_plan_v1` batch JSON. Так у сметного режима остаётся один
> model-first контракт, а код не держит параллельного “маленького сметчика”
> с отдельными подсказками и сценариями.
> 0.24.0.102 — следующий срез смысловой автоправки: `_normalize_work_item`
> больше не переписывает `work_family` и `element_type` по regex-сигналам из текста.
> Эти поля остаются решением модели. Код нормализует только машинные алиасы действия
> и единицы (`assemble`→`монтаж`, `m2`→`м2`) и кладёт несовпадения в trace как
> `intent_hints`, не используя их для поиска или расчёта. Если модель назвала
> деревянный каркас металлом или инженерные сети отделкой, harness не “починит”
> это за неё: shortlist/отказ вернёт проблему обратно в модельный ход.
> 0.24.0.101 — ещё один срез сметного “кода-няньки”: если `search_norm`
> вернул неоднозначный shortlist, batch harness больше не проваливается к первому
> применимому кандидату. Он делает второй короткий ход модели: выбрать `norm_code`
> строго из shortlist или вернуть `ask_user`. Чужой код не принимается, а расчёт
> всё равно проходит через `add_position` с проверками единиц/применимости/цены.
> Так модель реально выбирает норму, а код остаётся протоколом поиска, валидации
> и калькулятором.
> 0.24.0.100 — ещё один шаг к “модель+skill+RAG решают, код считает”:
> batch-план больше не режет геометрически зависимую работу до `search_norm`.
> Даже если площади/габаритов пока нет, ГЭСН/РИМ-кандидаты и навигация попадают в trace,
> а `add_position` остаётся калькуляторным gate: без геометрии он не считает и просит
> исходные. Так модель получает карту норм и может задавать осмысленный следующий вопрос,
> вместо того чтобы код заранее скрывал от неё RAG.
> 0.24.0.99 — сметному режиму возвращена свобода профессиональной декомпозиции:
> ТЗ/ВОР/приложенный файл и предыдущий диалог объявлены первичными исходными для модели.
> Если в ТЗ явно перечислены самостоятельные операции над одним изделием (например контрольная
> сборка, промежуточная разборка, монтаж на строительной площадке), одна физическая масса может
> быть исходным количеством для каждой операции. Duplicate-guard теперь отличает такие операции
> от настоящих дублей и опциональных “если требуется/уточнить долю”, а prompt/skill направляют
> модель в ГЭСН notebook/search_norm вместо схлопывания разделов в одну позицию.
> 0.24.0.98 — сметный режим усилен со стороны prompt/skill, а не объектных шаблонов:
> `skills/smeta/SKILL.md`, JSON role-pack и компактный machine contract закрепляют,
> что модель-сметчик переносит уже сказанные параметры в план, использует разрешённые
> сценарные допущения как допущения, понимает разговорные фразы вроде “3000 метров” у здания
> и “глубина 2 метра”, а код только парсит/проверяет/считает. Калькулятор принимает полные
> русские формы метров для глубины/высоты/периметра, не додумывает недостающие формульные слоты
> сам и штрафует свайные нормы, если пользователь/модель не говорят про сваи или ростверк.
> Объектных составов, hardcode-шаблонов детсада/дачи/дома не добавлено.
> 0.24.0.97 — сметный режим получил следующий системный шаг без объектных шаблонов:
> `smeta_norm_store_v5` добавляет в карточку нормы явные `applicability`, `price_inputs`
> и `decision_order`; `search_norm` возвращает `norm_decision_context` для выбора нормы,
> а `estimate_harness` отдаёт `quantity_candidates` с provenance и `smeta_service_sources`.
> Модель видит происхождение прямых объёмов и состояние ГЭСН/ФГИС/КАЦ/коэффициентов, код
> по-прежнему только проверяет и считает.
> 0.24.0.96 — сметный расчёт теперь явно говорит, чего не хватает для полного итога:
> отсутствующие цены ресурсов классифицируются как `needs_kac`, `needs_fgis_price`,
> `needs_labor_rate`, `needs_machinist_rate`; в артефакте появляется “Что нужно добрать”.
> Материалы без цены помечаются как “нужен КАЦ”, машины/труд/машинисты — как нужная цена
> или ставка. `estimate_harness` больше не ставит `complete`, если есть price gaps:
> рассчитанная часть остаётся `partial_total`, а `final_total` появляется только после закрытия
> ценовых требований.
> 0.24.0.95 — публичная витрина GitHub/Pages без изменения рантайма: README переписан как
> внешний продуктовый вход, добавлены `docs/index.md`, `docs/_config.yml` и `docs/public/*`
> (overview, demo workflows, privacy boundaries, что нужно сметному модулю, чтобы считать).
> Сметный документ больше не содержит заготовленных запросов: он фиксирует, чего не хватает
> для уверенного расчёта без шаблонов — норм-навигации, цен ресурсов, связи с объёмами,
> профессионального skill/prompt и eval-критериев. Можно давать сметчику оценивать ход рассуждения,
> нормы, границу частично/готово и происхождение чисел, но нельзя
> продавать как готовый автосметчик по любому объекту. В `ALGO-smeta.md` закрыт старый doc-drift
> с удалённым `object_estimate_service.py`.
> 0.24.0.94 — операторский контур индексации в С.А.М.О.В.А.Р.: play по датасету
> создаёт настоящую background parse-job, GUI показывает live jobs/ETA/memory guard и
> очередь `лёгкие/OCR`; настройки scheduler-а возвращены с предупреждением и сбросом
> к умолчанию. Очередь pending в backend теперь предпочитает не-OCR документы перед
> scan/OCR, чтобы лёгкий разбор не блокировался маленькими сканами.
> 0.24.0.93 — hotfix второго 500 на classic admin: в `sovushka/pages/volk.py`
> кнопки и table-events В.О.Л.К. теперь привязываются после объявления `_volk_*` handlers.
> Симптом: `UnboundLocalError: cannot access local variable '_volk_load'`.
> 0.24.0.92 — hotfix classic admin 500: в `sovushka/pages/instrumenty.py` кнопки
> `ОБНОВИТЬ` теперь привязывают async handlers после объявления `_refresh`/`_refresh_prompts`.
> Симптом: `UnboundLocalError: cannot access local variable '_refresh'` при открытии админки.
> 0.24.0.91 — честный запуск и статус индексатора в Самоваре: верхний `Пуск` теперь вызывает
> `/api/rag/parse-scheduler` напрямую, а не только переключает dispatcher/runtime mode. Строки
> датасетов больше не называют `PENDING` “парсингом”: очередь отображается как `WAITING`/“Ждёт”,
> `PARSING` показывается только при активной parse-job из `/api/jobs/summary`. Диалог файлов и
> таблицы индекса показывают человеческие бейджи слоёв (`таблицы`, `расчёты`, `чертежи`, `BIM`,
> `нормы`, `сметы`) из typed `file_cards`.
> 0.24.0.90 — hotfix кнопок индексации в Самоваре + root-admin контур: `play`/parse actions и
> события таблицы выполняются как NiceGUI async handlers, а не через оторванный `asyncio.create_task`.
> Симптом был UI-slot crash (`The current slot cannot be determined`) до/вокруг уведомления, не
> запрет backend: indexing mode остаётся Core ML (`embed_backend=coreml`, `indexing_uses_coreml=true`).
> Ключи `les-admin-…` принудительно считаются root-admin, не привязываются к устройству и не получают
> срок действия; менять/удалять такие ключи можно только из trusted-сети. Danger-zone endpoints для
> удаления датасетов и удаления/restore бэкапов требуют trusted ZeroTier/loopback/proxy или protected
> `les-admin-` key.
> 0.24.0.89 — polish для панели файлов выбранного датасета: служебные dot/`_les_` файлы не
> показываются в компактной полоске, а для одиночного датасета под именем файла показывается
> короткий путь папки, чтобы одинаковые `001_Содержание тома.docx` не выглядели дублями.
> 0.24.0.88 добавляет MVP “датасет как блокнот” прямо в чат: при выбранной области поиска
> появляется компактная панель файлов выбранного датасета/области с бейджами слоёв (`text`,
> `tables`, `calculations`, `drawings`, `cad_bim`, `normative`, `estimate`) и кнопкой
> “спросить по файлу”. Панель берёт `file_cards` из typed dataset memory через
> `/api/notebooks/{dataset_id}/memory`, не кладёт полный реестр в prompt и использует уже
> существующий strict `target_file`-канал.
> 0.24.0.87 — сметная косметика после `smeta_norm_store_v4`: role-pack больше не содержит
> противоречивый пример с `area_total_m2=1`, навигационные подсказки для модели говорят
> человеческим языком («соседние нормы», «выбранная применимая норма») и дополнительно запрещают
> выносить `nearby_norms` в видимый ответ. Поведение остаётся model-first: без объектных шаблонов,
> код только даёт норм-навигацию, проверяет и считает.
> 0.24.0.86 расширяет `smeta_norm_store_v4`: норм-карточка теперь несёт `navigation`
> (сборник/подраздел, вопросы применимости, РИМ-граница и `nearby_norms` вокруг кандидата), а
> `search_norm` отдаёт общий `norm_navigation` по shortlist. Блокнот ГЭСН в prompt получил
> короткую карту РИМ/ГЭСН: семейство работ → сборник/единица → вопросы применимости. Это навигация
> для модели, а не объектный шаблон: состав работ по-прежнему делает модель, расчёт и bind-гейты —
> код. Дополнительно voice-layer больше не принимает противоречие вида «деньги не считаю», если
> ниже уже показана рассчитанная часть `partial_total`.
> `make ship` 0.24.0.86: verify `2256 collected`; focused `151 passed`; pre-smoke `9/9`;
> post-smoke `9/9`. `docs/RELEASE_LEDGER.md` на runtime намеренно остался divergent и не копировался
> deploy tool'ом; dev-ledger обновлён как источник состояния.
> 0.24.0.85 подключает норм-карточки к `add_position`: рассчитанная строка может оставаться
> `computed`, но если выбранная норма требует условий применимости (например группа грунта,
> глубина, крепления или ширина/сечение), итог становится `partial`, а модель получает
> `norm_questions` и задаёт именно эти вопросы. Прямой `volume_m3` по-прежнему считается как
> физический объём, но не продаётся как финальная смета без подтверждения условий нормы.
> `make ship` 0.24.0.85: verify `2253 collected`; focused `150 passed`; pre-smoke `9/9`;
> post-smoke `9/9`. `docs/RELEASE_LEDGER.md` на runtime намеренно остался divergent и не копировался
> deploy tool'ом; dev-ledger обновлён как источник состояния.
> 0.24.0.84 расширяет сметный `smeta_norm_store_v3`: норма теперь отдаёт не только технический
> профиль, но и русскую `model_card` для модели (`measure`, domain, условия применимости,
> ресурсы, предупреждения). Условия вроде группы грунта, глубины, креплений, массы элемента и
> способа производства работ извлекаются из названия нормы как навигационные hints: модель может
> задавать правильные уточняющие вопросы, но расчёт по-прежнему идёт только через code guards.
> `make ship` 0.24.0.84: verify `2250 collected`; focused/release `147 passed`; pre-smoke `9/9`;
> post-smoke `9/9`. `docs/RELEASE_LEDGER.md` на runtime намеренно остался divergent и не копировался
> deploy tool'ом; dev-ledger обновлён как источник состояния.
> 0.24.0.83 расширяет сметный `smeta_norm_store_v2`: вместо голого SQLite-light shortlist
> каждая норма получает карточку профиля (`family_hints`, `element_hints`, `action_hints`,
> `resource_kinds`, `resource_count`, `provenance`). `search_norm` использует профиль в прозрачном
> `score_parts`, но не забирает у модели декомпозицию и не считает вместо `add_position`/ЛСР.
> Это системный шаг к “ГЭСН как мини-раг/карта норм”, без объектных шаблонов и ситуационных заплаток.
> `make ship` 0.24.0.83: verify `2250 collected`; focused/release `147 passed`; pre-smoke `9/9`;
> post-smoke `9/9`. `docs/RELEASE_LEDGER.md` на runtime намеренно остался divergent и не копировался
> deploy tool'ом; dev-ledger обновлён как источник состояния.
> 0.24.0.82 добавляет сметный `smeta_norm_store_v1`: это typed SQLite/FTS-проекция существующих
> ГЭСН/ФСНБ/ТЕР-источников, а не новая “сметная голова” и не объектный шаблон. Модель по-прежнему
> раскладывает задачу, код выдаёт широкий shortlist норм, проверяет единицы/применимость и считает.
> Broad SSE-ответы, которые уже успели отдать полезный текст, теперь не стираются поздним reset/error:
> backend завершает их recovered `UNVALIDATED` payload.
> `make ship` 0.24.0.82: verify `2248 collected`; focused `147 passed`; pre-smoke `9/9`;
> post-smoke `9/9`. В ходе ship пойман и закрыт thread-regression: кэшированный SQLite norm-store
> создавался в main thread, а chat-harness читал его из worker thread; теперь connection read-safe
> (`check_same_thread=False` + lock) и покрыт тестом.
> 0.24.0.79 чинит живой broad BAI-регресс после 0.24.0.78: `full` получает 3072 токена,
> чтобы не резать ответ на середине фразы, инженерные обзоры не превращаются в гигантские
> markdown-таблицы, а явный запрос реестра делает `Реестр файлов датасета` главным UI-artifact
> даже если параллельно собран `Инженерный блокнот`.
> 0.24.0.80 закрывает живой обрез на слове «кратко»: для явного inventory-запроса `brief/enum`
> получает минимум 2048 токенов, а prompt просит списки и ссылку на artifact вместо большой таблицы.
> 0.24.0.81 убирает видимый `Инженерный блокнот` из обычных broad-ответов: reading layer остаётся
> в machine payload, но оператор видит ответ модели. Prompt дополнительно чистит наружный текст от
> служебных слов evidence/dataset/context/RAG/notebook; реестр называется `Реестр файлов`.

> 0.24.0.6 выкачен через `make ship`. Живой чат-прогон без semantic cache:
> FIRE `52.8s` (`generation=44.313s`, `source_map=5`, unknown citations `0`);
> HVAC `37.0s` (`generation=30.148s`, `source_map=4`, unknown citations `0`).
> 0.24.0.7 возвращает таблицы как нормальный формат строительной выдачи. Живой FIRE-прогон:
> `has_table=true`, `50.6s` (`generation=42.264s`), `source_map=5`, unknown citations `0`.
> 0.24.0.8 выкачен через `make ship`: операторский слой чата прячет внутренние KOT/CTX/CACHE
> за раскрывашку, добавляет видимый «Паспорт области» и принудительно обновляет пузырь на каждом
> SSE-токене.
> 0.24.0.9 — hotfix кнопки «Паспорт области»: диалог заранее создаётся в UI-slot NiceGUI, а клик
> только заполняет его после async-загрузки профилей.
> 0.24.0.10 добавляет видимый ход работы для tool/детерминированных веток (`progress` SSE)
> и явный `answer_contract`/`scenario` в payload ответа.
> 0.24.0.11 добавляет мягкую машинную проверку `answer_contract_check`: pass/warn,
> missing-поля и признаки таблиц/evidence без блокировки ответа.
> 0.24.0.12 чинит наблюдённые системные провалы smeta-чата: состояние параметров по истории
> текущей сессии, разговорные площадь/этажность, предупреждения по неподдержанным вариантам и
> фильтр кандидатов ГЭСН по реальному сборнику даже при префиксе `ГЭСН:`.
> 0.24.0.13 добавляет память tool-следов для smeta-продолжений: повторная реплика может
> использовать массу/ярусы из предыдущего `retrieval_trace`; mass-fallback показывает кандидатов
> ГЭСН, но не выдаёт их за ЛСР, и убирает внутренние refs ставок/yaml из видимого ответа.
> PDF-нормы ГЭСН/ФЕР/ТЕР классифицируются как нормативные строительные документы, а не `TABLE_SMETA`.
> 0.24.0.14 добавляет bounded analog fallback для объектной сметы: если точного шаблона нет,
> ЛЕС ищет ближайший локальный аналог в `object_templates.yaml`, помечает результат
> `rough_analog_object_assumed` и удерживает диалоговый сценарий каркасной дачи без скрытых подсказок.
> 0.24.0.15 чистит видимый ответ объектной сметы: вместо абзацев с внутренними терминами —
> короткие списки «Коротко / Что не покрыто точно / Итог / Ключевые допущения».
> 0.24.0.16 добавляет `composition_candidates`: спорные части объектной сметы ищут реальные
> ГЭСН-кандидаты в локальной базе, но эти нормы не включаются в сумму без ВОР/подтверждения.
> 0.24.0.17 делает паспорта датасетов измеримыми: quality-сигнал и no-reindex benchmark
> cold rebuild против warm cached read по каждому датасету.
> 0.24.0.18 добавляет общий `workflow_plan_v1`: smeta/normcontrol/RAG/table payload получают
> единый план workflow, required/missing inputs, evidence policy, claim/source summary, blockers/actions.
> 0.24.0.19 выводит `workflow_plan_v1` в операторский слой Совушки: статус/финальность видны в чипах,
> а workflow id, missing inputs и next actions доступны в технических деталях ответа.
> 0.24.0.20 переключает режим «Смета» на model-first tool-loop: модель сама раскладывает объект,
> харнесс только даёт инструменты и gates; старый объектный слой, его YAML-данные и mass-rate fallback
> удалены, а auto-router больше не имеет отдельного объектного инструмента.
> 0.24.0.23 добавляет explainable shortlist поверх `search_norm`: кандидаты ГЭСН получают
> `candidate_selection_v1` с причинами score, отрывом лидера и действием для привязки/модельной развилки.
> 0.24.0.24 выносит `candidate_selection_v1` в общий `candidate_selection_service`: смета стала первым
> потребителем, а следующий нормоконтроль/табличные кандидаты могут использовать тот же контракт.
> 0.24.0.25 чинит видимую выдачу сметного режима: вместо внутреннего trace и списка инструментов —
> операторский ответ с таблицами, черновыми цифрами по лучшим применимым кандидатам и явными допущениями.
> AI-пузыри Совушки теперь рендерят обычный Markdown, а не показывают `**...**` сырьём.
> 0.24.0.26 чинит противоречие в частичной смете: если рассчитанная часть уже показана в рублях,
> ответ больше не пишет «число не показываю», а честно помечает только отсутствие финальной суммы.
> 0.24.0.27 возвращает прямой ZeroTier-доступ к UI/API: launchd plist снова задают
> `TRUSTED_NETWORKS=127.0.0.1/32,::1/128,10.195.146.0/24` и узкий
> `TRUSTED_PROXY_NETWORKS=127.0.0.1/32,::1/128,10.195.146.136/32`.
> 0.24.0.28 чинит причину провала кровли в smeta-harness: bind берёт первого кандидата,
> прошедшего применимость и единицу измерения, а не слепо top-1; видимый UI больше не показывает
> внутренние route/contract/workflow-чипы; инженерные сети уходят в отдельное MEP-семейство и без
> раздела/объёмов требуют данные, а не маскируются под отделку; planner получает repair-ход, если
> первый ответ модели был не машинным JSON или неполной схемой; земляные признаки (`котлован`,
> `траншея`, `грунт`) при нормализации побеждают слово `свайный` внутри земляной работы.
> 0.24.0.29 добавляет общий `notebook_v1`: датасетный блокнот поверх deep-паспорта, системный
> ГЭСН-блокнот из локальной базы норм, prompt registry (`LES_SYSTEM_PROMPT` + режимные prompts) и
> подключение ГЭСН-блокнота в smeta planner как навигации, не evidence.
> 0.24.0.30 возвращает потерянный мост к монтажному сметному каналу: ГЭСН-блокнот и smeta harness
> различают строительный `ГЭСН38` и монтажный `ГЭСНм38`, `metal_assembly` разрешает `ГЭСНм38`,
> масса из ТЗ парсится в тонны (`mass_t`), текст `СПб 2 кв. 2026` ведёт в `spb_2kv2026`, а
> тоннажные металлические позиции снова доходят до code-calculator/ЛСР-сборки вместо блокировки
> на плоском `search_norm`.
> 0.24.0.33 чинит PDF/RAG-слой без реиндекса: qwen lexical FTS разово построен из уже существующих
> Qdrant payloads (`188121/188121`), notebook/deep-паспорта снова видят PDF/DOCX-чанки, а обычная
> parse-переиндексация теперь сама удаляет/перезаписывает `lexical_chunks` для файла вместе с Qdrant.
> Это системная проекция корпуса для lexical/notebook/hybrid, не evidence и не подмена модели.
> 0.24.0.34 добавляет NotebookLM-подобный study layer: явный широкий запрос по выбранной области
> строит reading plan из `notebook_v1`, добирает источники по разделам обычным retrieval,
> передаёт организованный контекст в модель и отдаёт полный артефакт «Инженерный блокнот»
> с планом, источниками и пробелами. Это navigation, не deterministic final.
> 0.24.0.35 ускоряет `notebook_study`: reading plan выбирает меньший набор релевантных секций
> по карте блокнота, а section retrieval идёт параллельно (`LES_NOTEBOOK_STUDY_PARALLELISM`,
> default 3). Answer-cache не добавлялся; итог по-прежнему пишет модель.
> 0.24.0.36 чинит облачный режим: пресет «Облако» больше не перетирает выбранный
> `OPENAI_MODEL` на дефолтный `gpt-4.1`, а admission разрешает cloud generation во время
> guarded reindex/`INDEX_LIGHT`, потому что облако не держит локальный MLX-слот.
> 0.24.0.37 делает admission ресурсным: cloud проходит во время guarded reindex; локальный
> MLX во время индексации допускается только для Core ML embedder и зелёной памяти; `/api/status`
> отдаёт effective chat state вместо сырого `paused`, когда admission реально разрешил чат.
> 0.24.0.38 чинит ощущение долгого ответа: final-only ветки получают синтетическую печать токенами,
> progress не останавливает секундомер, источники могут показываться до финального payload, а видимый
> ответ чистится от CJK/OCR-мусора.
> 0.24.0.39 расширяет prompt registry: общий промт ЛЕС, тон, режимные промты и tool contracts
> доступны через `/api/prompts`, RAG/free/attachment/smeta-harness используют registry, а Совушка
> показывает карту промтов в админских «Инструментах».
> 0.24.0.57 делает системные промты редактируемыми через админские «Инструменты» и
> `PATCH/DELETE /api/prompts/{key}`. Tool contracts больше не инжектятся в системный prompt:
> они остаются только картой режима/API-метаданными, чтобы не превращать модель в чек-лист.
> Для запросов «перечень файлов/реестр документов + описание проекта» RAG получает
> evidence-блок из MetaDB `documents`, а semantic cache выключается, чтобы старый cache не подменял
> свежую опись.
> 0.24.0.58 разделяет модель runtime и модель ответа: верхняя плашка `MODEL` рядом с `RAG/CRAG`
> показывает активную конфигурацию из `/api/status`, а каждый AI-пузырь получает свой бейдж модели
> ответа. Опись файлов остаётся MetaDB evidence, но служебный inventory-заголовок заменён
> человеческой формулировкой и запрещён к выводу в видимую речь модели.
> агрегатный ответ не обходил поимённый реестр.
> 0.24.0.60 переводит native Qdrant из экспериментального флага в runtime path: sibling-коллекция
> `les_rag_qwen3_06b_native_v1` содержит named dense+sparse vectors; после первичного копирования
> удалены `108` orphan-точек PENDING-документа, runtime count стал `187960` и совпал с MetaDB
> indexed chunks. `retrieval_service` больше не выходит ранним native-return, а гонит результат через
> общий postprocess/rerank и SQLite FTS safety merge. Это сохраняет точные буквальные совпадения и
> `doc_filter`, но убирает отдельную sparse-коллекцию из горячего пути.
> 0.24.0.61 чинит latency широкого BAI-запроса «расскажи про объект и дай реестр файлов»:
> последняя сохранённая строка занимала `89.5s`, из них `38.3s` уходило в TOSKA validation длинного
> broad-ответа. Для selected-scope `notebook_study`/`project_inventory` validation теперь по умолчанию
> выключена (`UNVALIDATED` + source-map + deterministic MetaDB inventory artifact); явный
> `validation_enabled=true` оставляет старый путь.
> 0.24.0.62 чинит UX-симптом «таймер идёт, ответа нет»: если `/api/chat/stream` прислал backend
> error до первого токена, Совушка больше не запускает молча второй долгий `/api/chat`, а показывает
> ошибку и останавливает таймер. Trace latency получил `pre_retrieval` и `wall_total`, чтобы broad
> notebook/inventory-запросы показывали полный пользовательский wait, а не только LLM/retrieval-фазы.
> 0.24.0.63 чинит две видимые регрессии broad BAI-ответа: `project_inventory` теперь приходит top-level
> даже рядом с `Инженерным блокнотом`, поэтому Совушка автооткрывает кликабельный реестр файлов;
> таблицы больше не сжимаются до побуквенных «во/до/па/ды», а скроллятся внутри пузыря/артефакта.
> 0.24.0.64 добавляет typed dataset memory: MetaDB получает `dataset_revisions`/`dataset_memory`/
> `file_cards`/`evidence_atoms`, notebook и chat prompt видят карту слоёв данных как navigation-not-evidence,
> Qdrant payload получает `content_layers/file_kind/document_role/source_granularity`, а Совушка показывает
> бейджи слоёв в кликабельном реестре файлов.
> 0.24.0.65 добавляет model reader-pass поверх typed memory: модель может отдельным проходом
> “освоить” датасет и сохранить JSON-карту (`reader_output`) как navigation-not-evidence; API
> `POST /api/notebooks/{dataset_id}/memory/read` запускает проход вручную/в фоне, а awaited parse-пути
> могут ставить reader-pass после индексации через `LES_DATASET_READER_AFTER_PARSE=1`.
> 0.24.0.66 чинит реальный reader-pass на cloud GPT-5.x: structured extraction получает больший
> token budget (`LES_EXTRACT_MAX_TOKENS`, default 4096) и fallback без native `json_schema`, если
> OpenAI-compatible proxy вернул не-JSON; `extract_service.py` включён в deploy hash bundle.
> 0.24.0.67 добавляет второй слой для GPT-5 JSON-reader: default token budget поднят до 8192,
> структурные GPT-5/o-series вызовы получают low-reasoning/low-verbosity подсказки, а при 400 от
> OpenAI-compatible proxy автоматически повторяются без этих экспериментальных полей.
> 0.24.0.68 расширяет карту, которую получает model reader-pass: лимиты `LES_DATASET_READER_FILE_LIMIT`
> и `LES_DATASET_READER_CONTEXT_CHARS` стали настраиваемыми и шире по умолчанию, добавлен
> `file_cards_scope`, а prompt запрещает путать выбранную навигационную карту с отсутствием данных.
> 0.24.0.69 чинит локальный reader-pass: structured extraction для MLX/Qwen3 теперь добавляет
> `/no_think`, иначе модель тратила генерацию на скрытый think-блок, который MLX-host срезал до
> пустого `content`.
> 0.24.0.40 чинит UI-регрессию: системные промты в админке переносятся как многострочный текст,
> светлая тема снова дефолт при старте, а кастомный CSS больше не перетирает light-переменные.
> 0.24.0.41 возвращает notebook-study к “котельному” поведению: валидация больше не стирает
> инженерную сводку в SAFE_FALLBACK при наличии контекста, явный артефакт обновляет открытую панель
> вместо старой таблицы, а пресет «Облако» включает `LES_CLOUD_CONSENT=true`, чтобы UI не обещал
> cloud при фактическом MLX-дегрейде P2-датасета.
> 0.24.0.42 закрепляет принцип ширины ответа: broad-запросы по объекту/проекту обходят answer-cache
> и идут в notebook-study, а точные вопросы остаются узким RAG. Таблицы в чате и артефактах получили
> горизонтальную прокрутку вместо обрезки длинных проектных строк.
> 0.24.0.43 чинит live-причину, почему `расскажи про объект` по выбранному BAI всё ещё не запускал
> notebook-study: UI передавал UUID датасета в `dataset_filter`, а резолвер трактовал его только как
> имя/класс фильтра. Теперь UUID в `dataset_filter` резолвится как dataset scope и идёт в `_dataset_ids`.
> 0.24.0.44 снимает отдельный короткий token-cap с notebook-study и чинит артефакт: «Инженерный
> блокнот» отдаётся/рендерится как markdown-отчёт целиком, начинается с найденных материалов, а не
> с первой служебной таблицы плана чтения.
> 0.24.0.45 убирает фиксированную краткость по умолчанию: `расскажи про объект` и широкие
> notebook/RAG-запросы больше не получают скрытые правила «5-8 строк»/«до 6 строк»; краткость
> включается только явной просьбой оператора. Source-маркеры `[Источник N | ...]` в чате
> визуально отделяются как цитаты.
> 0.24.0.46 чинит скрепку чата под NiceGUI 3: upload-событие читает `e.file.read()`, а не
> старое `e.content`; обработчик больше не уходит в background task без UI-контекста. Файл в
> режиме «В чат» снова становится видимым pending-вложением под полем ввода и системной строкой
> в истории.
> 0.24.0.31 разделяет сметную выдачу на операторскую сводку в чате и полный артефакт:
> расшифровка позиций, ОЗП/ЭМ/ЗПМ/материалы/прямые/ФОТ/НР/СП/СМР, ресурсы с ценами и явное
> предупреждение, если высотные/производственные коэффициенты не применены без нормативного основания.
> 0.24.0.32 делает вложение видимым событием истории чата, а broad-вопросы по проекту больше не
> перехватываются автосводкой `project_summary`: обычный чат идёт в retrieval+модель, явная сводка
> остаётся инструментом/командой.

> Деплоятся только code-правки (`proxy/`,`backend/`,`sovushka/`,`config/`). Доки на рантайм не катятся —
> поэтому dev HEAD ≠ deployed_commit это нормально, пока расходятся только доки.

## Три оси версий (почему путаница) — и целевая одна

Сейчас в коде/доках живут ТРИ несвязанные оси (отсюда «где мы»):

| Ось | Где | Значение | Назначение |
|---|---|---|---|
| **APP_VERSION** | `version_service.py:19` | `5.1.0` | пользовательская «маркетинговая» версия ЛЕС |
| **HARNESS_VERSION** | `version_service.py:20` | `0.23` | внутренний строительный контур (веха roadmap) |
| **package** | `pyproject.toml` | `0.1.1.dev0` | версия python-пакета (SemVer сборки) |

Старые доки добавляют 4-ю («v2.0/v4.0» в README_v2.0/MASTER_DOC/INFRASTRUCTURE) — историческое, в архив.

**Целевая схема (по запросу оператора): `0.MILESTONE.FEATURE.PATCH`**

| часть | смысл | пример |
|---|---|---|
| `0` | до релиза v1.0 | — |
| `MILESTONE` | веха roadmap (растёт к v0.24…v1.0) | `0.23` |
| `FEATURE` | фиче-инкремент внутри вехи (двигать КАЖДУЮ фичу) | `0.23.5` |
| `PATCH` | фикс/патч | `0.23.5.1` |

**Статус:** схема зафиксирована здесь и внедрена в код (`version_service` → 4-частная версия в
`/api/version` + deployed-версия рядом).
Дисциплина после: бамп версии + строка в этот леджер + строка в `releases.md` на каждую фичу; деплой —
через `make ship` (быстрый gate: verify→focused tests→smoke→deploy→retry-smoke) или `make ship-full`
(полная сюита на границе версии), откат — `git checkout <prev>` + redeploy
(код) / `tools/restore_runtime.sh` (данные). См. [GUARDRAILS.md](GUARDRAILS.md) (в очереди).

## Леджер (новое → старое)

| Версия | commit | дата | что | деплой |
|---|---|---|---|---|
| 0.24.0.100 | HEAD | 2026-06-30 | Smeta RAG-before-calculation cut: batch-путь больше не блокирует geometry-dependent работы до `search_norm`; ГЭСН/РИМ-кандидаты попадают в trace даже при missing geometry, а расчёт по-прежнему останавливает `add_position` без исходных объёмов | ✅ smeta focused 80/80 + verify |
| 0.24.0.99 | HEAD | 2026-06-30 | Smeta model-freedom repair: ТЗ/ВОР/файл первичны для модели; прямой физический объём может использоваться несколькими явно названными самостоятельными операциями над тем же изделием; duplicate-guard отличает такие операции от опциональных дублей без доли/объёма | ✅ smeta focused 80/80 + verify |
| 0.24.0.98 | HEAD | 2026-06-30 | Smeta prompt-first repair: сметный skill/role-pack и machine contract учат модель переносить уже сказанные параметры/допущения в work-plan, понимать разговорные площади/глубины и не выбирать сваи/ростверк без явного указания; код принимает русские формы метров, штрафует свайные нормы вне свайного контекста и не придумывает недостающие формульные слоты | ✅ full test 2272/2272 + verify/public-check |
| 0.24.0.94 | HEAD | 2026-06-30 | Samovar operator indexing pass: dataset play creates a durable/background `rag_parse_batch` job, the GUI shows live parse jobs/ETA/memory guard/light-vs-OCR pending counts, scheduler settings return with safe defaults reset, and backend pending order prefers non-OCR documents before scan/OCR work | ✅ focused Sovushka/backend + ship/smoke |
| 0.24.0.93 | HEAD | 2026-06-30 | Volk admin hotfix: кнопки и события таблицы В.О.Л.К. привязываются после объявления `_volk_*` async handlers; classic admin закрывает второй `UnboundLocalError` после cleanup-а async handlers | ✅ focused Sovushka + ship/smoke |
| 0.24.0.92 | HEAD | 2026-06-30 | Instrumenty admin hotfix: кнопки обновления на странице «Инструменты» привязываются после объявления async handlers; classic admin больше не падает 500 из-за `UnboundLocalError` | ✅ focused Sovushka + ship/smoke |
| 0.24.0.91 | HEAD | 2026-06-30 | Samovar scheduler truth pass: верхний `Пуск` запускает реальный `/api/rag/parse-scheduler`, `PENDING` больше не подписывается как активный парсинг, `PARSING` зависит от живой job, а список файлов/индекс-таблицы показывают типизированные слои данных из `file_cards` | ✅ focused Sovushka + verify/ship |
| 0.24.0.90 | HEAD | 2026-06-30 | Samovar indexing play + root-admin hotfix: кнопки `play`/parse и события таблицы запускают async-обработчики внутри NiceGUI slot, а не через detached `asyncio.create_task`; клик снова показывает уведомления и доходит до `/api/rag/parse-batch`/scheduler. Диагностика подтвердила Core ML индексатор (`embed_backend=coreml`) и отсутствие backend-блокировки. `les-admin-` ключи стали protected root-admin без expiry/device binding; danger-zone удаление датасетов и delete/restore бэкапов требует trusted ZeroTier/loopback/proxy или protected `les-admin-` key | ✅ focused security/auth/Sovushka 43/43; make ship/post-smoke |
| 0.24.0.78 | HEAD | 2026-06-29 | Compact inventory prompt: полный MetaDB-реестр больше не скармливается модели целиком; LLM получает компактную `КАРТА РЕЕСТРА ДАТАСЕТА` (папки, типы, важные файлы-кандидаты), а полный проверяемый реестр остаётся в `project_inventory`/artifact/UI | ✅ focused inventory/chat/notebook 34/34; make ship/post-smoke 9/9 |
| 0.24.0.77 | HEAD | 2026-06-29 | Enforced overview sections: `full`-форма инженерного обзора задаёт порядок разделов — паспорт, ключевые решения, важные файлы/разделы, несостыковки/что проверить, затем детали; блок проверок обязателен даже при отсутствии явных противоречий | ✅ focused answer 19/19; make ship/post-smoke 9/9 |
| 0.24.0.76 | HEAD | 2026-06-29 | Full overview priority: `full`-форма ответа теперь просит модель в первой половине инженерного обзора дать паспорт объекта, ключевые решения, важные файлы и несостыковки/что проверить, чтобы ответ не тратил весь лимит на один раздел и не обрывался до выводов | ✅ focused answer 19/19; make ship/post-smoke 9/9 |
| 0.24.0.75 | HEAD | 2026-06-29 | Practical full answer budget: `full`-форма ответа ограничена 2048 токенами; это оставляет место для нормального инженерного обзора, но не провоцирует текущую облачную модель уходить в 180+ секунд без ответа | ✅ focused answer 19/19; make ship/post-smoke 9/9 |
| 0.24.0.74 | HEAD | 2026-06-29 | Bounded full answer budget: `full`-форма ответа остаётся широкой, но ограничена 4096 токенами, чтобы инженерные обзоры не обрывались как `enum` и одновременно не зависали на облачной модели на 200+ секунд | ✅ focused answer 19/19; make ship/post-smoke 9/9 |
| 0.24.0.73 | HEAD | 2026-06-29 | Answer-form broad overview fix: запросы вида «инженерный обзор / технические решения / что не сходится / требует проверки» больше не классифицируются как короткий `enum` из-за слов «какие файлы/разделы»; широкому RAG-ответу возвращён нормальный token budget. `answer_form_service.py` добавлен в deploy-stamp critical files, чтобы дрейф формы ответа был виден в `/api/version` | ✅ focused answer/RAG 42/42; make ship/post-smoke 9/9 |
| 0.24.0.72 | HEAD | 2026-06-29 | File-target suffix resolver: `resolve_inventory_file_reference()` понимает пути из реестра без первого сегмента датасета (`OUT/...` вместо `BAI/OUT/...`) и использует boundary/scored matching, чтобы `01_...` не матчился внутри `001_...`; запрос по конкретному файлу больше не должен уходить в соседние документы. LES skill закрепляет философию model-first: модель ведёт ход, код хранит evidence/provenance/граф/версии и считает, ситуационные hardcode-костыли запрещены | ✅ focused resolver+SafeRAG+notebook 24/24; make verify; make ship/post-smoke 9/9 |
| 0.24.0.71 | HEAD | 2026-06-29 | Protected evidence tier: `concentrate_sources()` принимает `protected_doc_names`, поэтому документы, явно открытые через `target_file`/клик по реестру или notebook target-file pass, не теряются из-за общего `max_docs` focus; клик по файлу больше не должен подменяться соседним похожим документом | ✅ focused SafeRAG+notebook 17/17; make ship/post-smoke 9/9 |
| 0.24.0.70 | HEAD | 2026-06-29 | Wide notebook target-file pass: широкое чтение блокнота после section retrieval выбирает паспортные файлы из typed memory/model reader-pass/MetaDB inventory (`состав проекта`, `ПЗ`, `содержание`, `задание`, `СТУ`, `ТЭП`) и добирает их через строгий `doc_filter`, чтобы модель синтезировала ответ по конкретным файлам, а не по случайным top chunks | ✅ focused notebook-study 6/6 + make verify + make ship/post-smoke 9/9 |
| 0.24.0.69 | HEAD | 2026-06-29 | Local structured extraction hotfix: локальные MLX/Qwen3 JSON-вызовы extractor-а получают `/no_think`, чтобы hidden-thinking не срезался в пустой ответ и dataset reader-pass мог работать на локальной модели | ✅ focused 26/26 + make verify + full `make test` 2237 passed + make ship/post-smoke 9/9 |
| 0.24.0.68 | HEAD | 2026-06-29 | Dataset reader input quality: reader-pass получает более широкий env-настраиваемый контекст (`LES_DATASET_READER_FILE_LIMIT`, `LES_DATASET_READER_CONTEXT_CHARS`), `file_cards_scope` объясняет выборку карточек, prompt требует 10-30 конкретных file_roles и запрещает писать “данных нет” из-за ограниченной навигационной карты | ✅ focused 25/25 + make verify + full `make test` 2236 passed + make ship/post-smoke 9/9 |
| 0.24.0.67 | HEAD | 2026-06-29 | GPT-5 structured reader-pass tuning: `LES_EXTRACT_MAX_TOKENS` default 8192, JSON-вызовы GPT-5/o-серии получают `reasoning_effort=minimal`/`verbosity=low`, при 400 от OpenAI-compatible proxy extractor повторяет запрос без этих полей, list-формат `message.content` приводится к тексту | ✅ focused 24/24 + make verify + full `make test` 2235 passed + make ship/post-smoke 9/9 |
| 0.24.0.66 | HEAD | 2026-06-29 | Structured extraction hotfix для model reader-pass: `LES_EXTRACT_MAX_TOKENS` default 4096 вместо 1024 для GPT-5/o-серии, cloud structured-output fallback без native `json_schema` при не-JSON ответе, `extract_service.py` добавлен в critical deploy bundle | ✅ focused 20/20 + make verify + full `make test` 2231 passed + make ship/post-smoke 9/9 |
| 0.24.0.65 | HEAD | 2026-06-29 | Model reader-pass для typed dataset memory: отдельный schema-bound проход модели строит навигационную карту корпуса (`corpus_kind`, где искать паспорт/ТЭП/инженерку/сметы/нормы, роли файлов, пробелы), хранится в `dataset_memory.reader_output` как НЕ evidence; добавлен `POST /api/notebooks/{dataset_id}/memory/read`, prompt использует reader-советы, awaited parse-пути умеют фоново переизучать датасет через `LES_DATASET_READER_AFTER_PARSE=1` | ✅ focused 11/11 + make verify + full `make test` 2228 passed + make ship/post-smoke 9/9 |
| 0.24.0.64 | HEAD | 2026-06-29 | Model-first typed dataset memory: новые MetaDB-таблицы `dataset_revisions`/`dataset_memory`/`file_cards`/`evidence_atoms`; мультислои данных (`text/tables/calculations/technical_docs/drawings/cad_bim/normative/estimate`) идут в notebook/chat prompt как навигация, Qdrant payload и UI-реестр файлов с бейджами слоёв | ✅ focused 35/35 + make verify + full `make test` 2226 passed + make ship/post-smoke 9/9 |
| 0.24.0.63 | HEAD | 2026-06-29 | Sovushka inventory/table UX hotfix: broad notebook+inventory ответы всегда несут top-level `project_inventory`, реестр файлов автооткрывается кликабельным артефактом, таблицы получают внутренний горизонтальный scroll и нормальный перенос слов вместо побуквенного `overflow-wrap:anywhere` | ✅ focused tests; ship/live UI probe см. текущий прогон |
| 0.24.0.62 | HEAD | 2026-06-29 | Chat stream error/latency guard: SSE backend error до первого токена больше не превращается в скрытый повторный `/api/chat`, UI показывает ошибку и гасит таймер; `latency_phases` добавляет `pre_retrieval` и `wall_total`, а `latency_sec` истории пишет полный wall-time запроса | ✅ focused 49 passed; ship/live stream probe см. текущий прогон |
| 0.24.0.61 | HEAD | 2026-06-29 | Broad project inventory speed guard: selected-scope `notebook_study`/`project_inventory` broad-ответы (`расскажи про объект и дай реестр файлов`) больше не запускают дорогую TOSKA validation по умолчанию; проверяемость держится source-map + deterministic MetaDB inventory artifact, а явный `validation_enabled=true` сохраняет старый validation path | ✅ focused 49 passed; live BAI probe см. текущий прогон |
| 0.24.0.60 | HEAD | 2026-06-29 | Qdrant native runtime switch: создана sibling-коллекция `les_rag_qwen3_06b_native_v1` (named `dense`/`bm25_sparse`), построена её `lexical_chunks` FTS-проекция, удалены `108` orphan-точек PENDING-документа (`points_match_sqlite_chunks=true`, active count `187960`), `retrieve_chat_chunks` больше не возвращает native-ветку ранним выходом и прогоняет её через общий postprocess/rerank; native shortlist смешивается с SQLite FTS exact-word/doc-filter safety pool из той же коллекции; launchd proxy plist переключены на `RAG_COLLECTION_NAME=les_rag_qwen3_06b_native_v1`, `RAG_QDRANT_SCHEMA=named`, `RAG_HYBRID_BACKEND=qdrant_native`; deploy drift `tools/deploy_to_runtime.py` закрыт force-copy | ✅ runtime ship/post-deploy smoke 9/9 + FIRE/HVAC golden 16/16 + retrieve-debug `qdrant_native_hybrid+rerank` ✅ |
| 0.24.0.59 | HEAD | 2026-06-29 | Qdrant document path + hybrid hardening: запросы по конкретному файлу из MetaDB inventory резолвятся в `target_file`/`doc_filter` и отключают cache; артефакт реестра файлов в Совушке стал кликабельным (`Спросить по файлу`) со статусом индекса и `chunk_count`; sparse sidecar `{collection}_sparse` теперь best-effort чистится/обновляется при parse/delete/reconcile; hybrid не выключает весь lexical FTS при малом sidecar drift (`RAG_LEXICAL_STALE_TOLERANCE`, default 2%); добавлены флаги `RAG_HYBRID_BACKEND`, `RAG_QDRANT_SCHEMA`, named dense/sparse support, `retrieve_native_hybrid()` через Qdrant `Prefetch+Fusion.RRF` и safe migration tool `tools/migrate_qdrant_native_hybrid.py` для sibling collection | ✅ рантайм, full test 2222/2222 + make ship/post-deploy smoke 9/9 + FIRE/HVAC golden 16/16 ✅ |
| 0.24.0.58 | HEAD | 2026-06-29 | Sovushka/RAG wording hotfix: верхняя плашка `MODEL` показывает активную модель из `/api/status`, модель конкретного ответа показывается бейджем внутри AI-пузыря, а MetaDB file inventory больше не протаскивает в видимый ответ служебный `DETERMINISTIC DATASET FILE INVENTORY`; источники называются человекочитаемо как «Опись файлов датасета» | ✅ рантайм вместе с последующими релизами |
| 0.24.0.57 | HEAD | 2026-06-29 | Editable prompt registry + RAG inventory context: `/api/prompts` получил admin `PATCH/DELETE` для override общего, tonal и режимных системных промтов; Совушка в «Инструментах» редактирует/сбрасывает эти тексты; локальный `config/prompts/prompt_overrides.json` игнорируется git; tool contracts больше не добавляются в системный prompt и остаются только метаданными карты режима; модель последнего ответа вынесена в верхнюю плашку `MODEL` рядом с `RAG/CRAG`; RAG-запросы «перечень файлов/реестр документов + описание проекта» получают MetaDB `documents` inventory как evidence/context/artifact, отключают semantic cache и не проваливаются в NO_DATA при слабом retrieval | ✅ рантайм, focused tests + verify + make ship/post-deploy smoke 9/9 ✅ |
| 0.24.0.56 | HEAD | 2026-06-29 | Smeta Russian-facing technical terms: видимый smetnik-layer и `smeta_dialog_state_v1` больше не тащат наружу внутренние поля (`element_type`, `slots`, `wall_length_m`, `area_total_m2`); форматтер переводит их в русские сметные формулировки, а role-pack запрещает англицизмы в видимой прозе | ✅ рантайм, focused tests + verify/ship/smoke + live UI/API probe ✅ |
| 0.24.0.55 | HEAD | 2026-06-29 | Smeta authorized assumptions: если пользователь явно просит «придумай/прикинь/по допущениям/типовой вариант», smeta harness разрешает модели задать недостающую геометрию и слоты как `assumptions`; модельная площадь всё ещё игнорируется без такого разрешения, а видимый ответ маркируется как «Сценарий по допущениям», не проектная смета | ✅ рантайм, focused tests + verify/ship/smoke + live smeta probe ✅ |
| 0.24.0.54 | HEAD | 2026-06-29 | Chat UI cosmetics: Совушка получила явную кнопку «Новый чат» (новая `session_id` без памяти прошлого диалога), каждый AI-пузырь показывает provider/model ответа из payload `versions`/`retrieval_trace.routing`, а inline Quasar-таблицы в чате переносят строки внутри пузыря и скрывают footer `Records per page` | ✅ рантайм, focused 43 passed + verify/ship/smoke + live UI probe ✅ |
| 0.24.0.53 | HEAD | 2026-06-29 | Smeta model-tool-model dialog loop: модель остаётся сметчиком-оркестратором (`model -> tools -> model reads tool result -> answer`), видимый smetnik-layer получает computed/pending/missing slots, а не только счётчики; broad object без площади/габаритов больше не считает м²-разделы по JSON-заглушке `1 м2`, а возвращает `needs_input`; `smeta_dialog_state_v1` сохраняется в `retrieval_trace_json`, чтобы следующий ход диалога видел расчётный статус/слоты, а не только текст ответа; partial-голос не получает рубли как разрешённый факт | ✅ рантайм, focused 102 passed + verify/ship/smoke + live smeta probe ✅ |
| 0.24.0.52 | HEAD | 2026-06-29 | Smeta prompt/skill/voice boundary: role-pack и smeta skill закрепляют model-first декомпозицию без объектных if-шаблонов; счётные `шт` нельзя выводить из площади/массы/объёма другого раздела; объектная площадь не становится direct `area_m2` для всех м2-позиций; видимый ответ получает LLM voice-layer на 2-4 строки, который может цитировать только exact facts из расчётного payload, а таблицы/суммы остаются кодовым слоем; UI-progress больше не показывает `N/N`, а видимые причины подбора норм убраны из HR-style “кандидат не прошёл” | ✅ рантайм, full test 2193 passed + make ship/post-deploy smoke 9/9 + `/api/version` aligned ✅ |
| 0.24.0.51 | HEAD | 2026-06-28 | Smeta direct quantity magnitude bypass: `magnitude_guard` больше не сравнивает прямые пользовательские `volume_m3`/`mass_t`/`area_m2`/`piece_count` со служебной геометрией планировщика; guard остаётся для формульных объёмов, а direct quantity считается авторитетным физическим количеством | ✅ рантайм, full test + make ship/post-deploy smoke + live metal/trench probes ✅ |
| 0.24.0.50 | HEAD | 2026-06-28 | Smeta experienced-estimator role-pack: добавлен `config/prompts/smeta_estimator_role.json` (`experienced_estimator_v1`) с ролью опытного сметчика РИМ/ГЭСН, direct quantity policy, anti-patterns и machine contract `smeta_work_plan_v1`; `prompt_registry_service` подмешивает JSON role-pack в smeta harness prompt и отдаёт его через `/api/prompts`; `skills/smeta/SKILL.md` обновлён под схему skill + JSON role-pack + code guards для будущих ролей | ✅ рантайм, full test + make ship/post-deploy smoke + `/api/prompts` role-pack probe ✅ |
| 0.24.0.49 | HEAD | 2026-06-28 | Smeta direct quantity duplicate guard: если планировщик несколько раз предлагает один и тот же `code` с тем же direct-слотом (`mass_t`/`volume_m3`/`area_m2`/`piece_count`) и тем же физическим объёмом, harness считает первую позицию, а повторы помечает `skipped_duplicate`, чтобы одна масса/объём не умножались в сумме; visible title для direct-расчётов скрывает служебную площадь планировщика | ✅ рантайм, full test + make ship/post-deploy smoke + live metal/trench probes ✅ |
| 0.24.0.48 | HEAD | 2026-06-28 | Qdrant parse lexical guard: `_sync_parse` больше не падает на legacy/test/lightweight adapter без `_sync_delete_file_lexical`/`_sync_upsert_file_lexical`; vector parse остаётся обязательным, lexical FTS sidecar работает, когда методы доступны, и становится no-op только для адаптеров без sidecar-слоя | ✅ рантайм, full test + make ship/post-deploy smoke ✅ |
| 0.24.0.47 | HEAD | 2026-06-28 | Smeta direct work quantity route: `parse_params` принимает Office/DOCX-форматы чисел с пробелами/NBSP и смешанными разделителями тысяч/десятых (`664.711,12 кг`, `664,711.12 кг`) для общих слотов без объектных спец-веток; добавлены прямые физические слоты `volume_m3`/`area_m2`/`mass_t`/`piece_count`, чтобы `200 м3` считались как объём позиции и пересчитывались кодом в измеритель нормы (`100 м3` → `qty=2`); auto-чат узко переводит запросы «рассчитать сметную стоимость работ + явное количество» в smeta harness вместо table/RAG, а `найди/покажи строки сметы` остаются табличным поиском; smeta-harness prompt сохраняет операторскую метку `Режим «Смета»` | ✅ рантайм вместе с 0.24.0.48, full test + make ship/post-deploy smoke ✅ |
| 0.24.0.46 | 9d82b60 | 2026-06-28 | Chat attachment upload hotfix: Совушка читает файл из актуального NiceGUI `UploadEventArguments.file.read()`, сохраняет fallback для старого `content`, больше не запускает upload handler через `asyncio.create_task` без UI-контекста; read-вложение после upload снова отображается под полем ввода и в истории как файл следующего сообщения | ✅ рантайм, focused/verify + live attach probe ✅ |
| 0.24.0.45 | HEAD | 2026-06-28 | Broad answer length/source visual hotfix: удалены скрытые fixed-line правила для notebook-study/default RAG (`5-8 строк`, `до 6 строк`), `расскажи`/`требования к` больше не классифицируются как brief без явной просьбы `кратко`; default/full generation budget не режется local cap; source-маркеры в Совушке выводятся отдельными citation-строками | ✅ рантайм, focused/verify + live BAI probe ✅ |
| 0.24.0.44 | HEAD | 2026-06-28 | Notebook artifact/length hotfix: снят отдельный `LES_NOTEBOOK_STUDY_CHAT_MAX_TOKENS=900` cap; notebook-study использует общий generation budget; payload artifact `Инженерный блокнот` теперь `mode=markdown`, Совушка рендерит markdown-артефакт целиком, а сам артефакт начинается с найденных материалов, не со служебного маршрута чтения | ✅ рантайм, focused/verify + live BAI probe ✅ |
| 0.24.0.43 | HEAD | 2026-06-28 | Dataset UUID scope hotfix: legacy `dataset_filter=<uuid>` теперь резолвится как выбранный датасет и в `scope_service`, и в `retrieval_service`; broad-study получает `_dataset_ids` и может строить notebook artifact по выбранному объекту вместо fallback на широкий RAG | ✅ рантайм, focused/verify + live BAI probe ✅ |
| 0.24.0.42 | HEAD | 2026-06-28 | Broad-study/table UX hotfix: общие запросы по объекту/проекту помечаются `breadth=wide`, не берут stale answer-cache и проходят через notebook-study; точные запросы остаются обычным RAG; inline/artifact Quasar-таблицы обёрнуты в горизонтальный scroll-container | ✅ рантайм, focused/verify + live probes ✅ |
| 0.24.0.41 | HEAD | 2026-06-28 | Notebook-study/cloud/artifact hotfix: broad-инженерные ответы с найденным контекстом больше не заменяются generic TOSKA fallback при неполной проверке; явный артефакт обновляет открытую панель и markdown-артефакты открываются как текст; пресет `cloud` теперь включает `LES_CLOUD_CONSENT=true`, а local/mix явно выключают согласие | ✅ рантайм, focused/verify + live probes ✅ |
| 0.24.0.40 | HEAD | 2026-06-28 | UI hotfix: prompt registry в «Инструментах» переносится многострочно; NiceGUI стартует в light mode; порядок CSS больше не перетирает светлую тему тёмными `:root`; `sovushka/styles.py` добавлен в deploy hash bundle | ✅ рантайм, focused/verify + browser style probe ✅ |
| 0.24.0.39 | HEAD | 2026-06-28 | Prompt registry v2: общий системный промт, тон, режимные промты и tool contracts вынесены в единый registry/API `/api/prompts`; RAG/free/attachment/smeta-harness берут системный слой оттуда; «Инструменты» показывают оператору карту промтов | ✅ рантайм, focused/verify + live `/api/prompts` probe ✅ |
| 0.24.0.38 | HEAD | 2026-06-28 | Chat streaming UX: final-only ветки `/api/chat/stream` печатают ответ порциями, `progress` сохраняет живой таймер, SSE может отдавать ранние `sources` для чипов/цитат до финала, а видимый текст чистится от CJK/OCR-мусора | ✅ рантайм, focused/verify + live SSE probe ✅ |
| 0.24.0.37 | HEAD | 2026-06-28 | Resource-aware chat admission/status: indexing mode больше не является тупым рубильником; cloud generation проходит во время guarded reindex, локальный MLX допускается только при `EMBED_BACKEND=coreml` и зелёной памяти, а `/api/status`/`/api/indexing-mode` показывают effective chat state + `indexing_chat_policy` без операторского “paused”, если чат реально разрешён | ✅ рантайм, focused/verify ✅ |
| 0.24.0.36 | HEAD | 2026-06-28 | Cloud model/admission hotfix: пресет `cloud` сохраняет операторский `OPENAI_MODEL` (`gpt-5.2` не откатывается на `gpt-4.1`), а cloud generation проходит admission даже при active guarded reindex/`INDEX_LIGHT`; локальные провайдеры по-прежнему блокируются ради памяти | ✅ рантайм, focused/verify + live settings/admission probe ✅ |
| 0.24.0.35 | HEAD | 2026-06-28 | Notebook study speed pass: план чтения выбирает меньше релевантных секций по `notebook_v1`, а retrieval по выбранным секциям идёт параллельно (`LES_NOTEBOOK_STUDY_PARALLELISM`, default 3); кэш готовых ответов не добавлен, итоговый синтез остаётся за моделью | ✅ рантайм, focused/verify + live probe ✅ |
| 0.24.0.32 | HEAD | 2026-06-28 | Attachment visibility + no auto project-summary: uploaded chat files now persist as system messages in chat history and user turns keep a clear attachment line; broad project questions no longer auto-return deterministic project registers, so notebook/RAG synthesis goes to retrieval + model while project summary remains an explicit tool/MCP command | ✅ dev, focused tests/verify pending |
| 0.24.0.30 | HEAD | 2026-06-28 | Smeta GESNm bridge: ГЭСН-блокнот различает `ГЭСН38` и `ГЭСНм38`; `metal_assembly` допускает монтажный сборник `ГЭСНм38`, масса `кг/т` нормализуется в `mass_t`, `СПб 2 кв. 2026` маршрутизируется в `spb_2kv2026`, тоннажные металлические позиции снова доходят до code-calculator/ЛСР-сборки вместо блокировки на плоском `search_norm` | ✅ dev, focused tests pass, deploy pending |
| 0.24.0.29 | HEAD | 2026-06-28 | Notebook/prompt layer: общий `notebook_v1` поверх dataset profiles и service sources, публичные `/api/notebooks/*` + `/api/service-sources/notebooks`, системный ГЭСН-блокнот с картой сборников из локальной базы норм, prompt registry для общего LES prompt и режимных prompts; smeta planner получает ГЭСН-блокнот как navigation/context, а UI показывает «Блокнот области» | ✅ dev, focused tests/verify pending |
| 0.24.0.28 | HEAD | 2026-06-28 | Smeta visible-output + MEP routing hotfix: if top-1 norm candidate fails unit/applicability gates, harness binds the first accepted unit-compatible candidate; visible answer footer no longer shows route/contract/workflow internals; engineering networks are routed to MEP and ask for subsystem/volume data instead of binding to finishing norms; planner retries once when the model returns non-JSON/incomplete schema; excavation signals win over pile words for pit works | ✅ рантайм, focused tests + live probes ✅ |
| 0.24.0.27 | HEAD | 2026-06-28 | ZeroTier trusted access hotfix: installed launchd plists and repo templates restore direct `10.195.146.0/24` trusted admin access while keeping public `/classic` redirected to `/login`; proxy/UI trust diagnostics are green | ✅ рантайм, focused trust checks + public login guard ✅ |
| 0.24.0.26 | HEAD | 2026-06-28 | Smeta partial-total wording hotfix: partial preliminary totals stay visible, but the answer no longer contradicts itself with “число не показываю”; only the final guarded total is withheld until all key norms/parameters are confirmed | ✅ рантайм, focused + ship/smoke + live dacha probe ✅ |
| 0.24.0.25 | HEAD | 2026-06-28 | Smeta answer hotfix: visible estimate-harness response no longer exposes planner/tool trace or internal terms, shows computed preliminary totals when best applicable candidates can be priced, renders pending candidates as a compact table, and Совушка renders plain AI Markdown instead of raw `**...**`; ambiguous top norms can produce explicitly assumed preliminary figures while final status remains guarded by missing/rejected positions | ✅ рантайм, full test + ship/smoke + runtime format probe ✅ |
| 0.24.0.24 | HEAD | 2026-06-28 | Candidate selection system service: reusable `candidate_selection_service` owns `candidate_selection_v1` shortlist/reasons/gap/action contract; smeta `search_norm` delegates selection to it with smeta-specific reason labels, and the new service is included in runtime alignment critical files | ✅ рантайм, full test + ship/smoke + alignment checked=32 ✅ |
| 0.24.0.23 | HEAD | 2026-06-28 | Smeta candidate selection contract: `search_norm` now returns `candidate_selection_v1` with an explainable shortlist, score parts translated into human reasons, score gap and action (`bind_top_candidate` only for a clear applicable leader; otherwise the model must choose or ask for data); batch trace and unbound positions carry the selection contract | ✅ рантайм, full test + ship/smoke + runtime selection probe ✅ |
| 0.24.0.22 | HEAD | 2026-06-28 | Smeta tool-argument normalization: `estimate_harness` нормализует аргументы work-plan модели перед `search_norm` (каркасные/каркасно-щитовые стены не уходят в металл, английские action слова переводятся в строительные действия, unit aliases приводятся к `м2/м3/т`), сохраняя model-first декомпозицию и не добавляя объектных составов | ✅ рантайм, full test + ship/smoke + live dacha: frame candidates now `ГЭСН:10-*` ✅ |
| 0.24.0.21 | HEAD | 2026-06-28 | Smeta harness latency: режим «Смета» больше не гоняет многоходовую LLM-петлю по умолчанию; модель одним компактным JSON отдаёт схему объекта и works, после чего код пакетно выполняет `search_norm`/`add_position` по ГЭСН, показывает коды-кандидаты при неоднозначности и не добавляет их в сумму без уверенной применимости; LLM-вызов планировщика ограничен timeout | ✅ рантайм, full test + ship/smoke + live dacha 18s ✅ |
| 0.24.0.20 | HEAD | 2026-06-28 | Smeta model-first route: режим «Смета» идёт через `estimate_harness` (модель сама раскладывает объект; харнесс даёт `search_norm`/`add_position` и gates); старый объектный слой, его YAML-данные, mass-rate fallback и auto-router target удалены; служебные источники больше не требуют готовых объектных составов | ✅ рантайм, full test + ship/smoke; runtime old files removed ✅ |
| 0.24.0.19 | HEAD | 2026-06-28 | Workflow plan UI: Совушка сохраняет `workflow_plan_v1` в metadata сообщения, показывает статус/финальность workflow оператору и оставляет `workflow_id`, missing inputs, next actions в технических деталях без вывода router/debug полей в первый слой | ✅ рантайм, focused/verify + ship/smoke + live workflow UI ✅ |
| 0.24.0.18 | HEAD | 2026-06-27 | Workflow plan contract: ответы чата и JSON нормоконтроля получают общий `workflow_plan_v1` (workflow id, required/missing inputs, evidence policy, claim/source summary, blockers, next actions), чтобы smeta/normcontrol/checklist развивались через один информационный контракт | ✅ рантайм, focused/verify + ship/smoke + live workflow plan ✅ |
| 0.24.0.17 | HEAD | 2026-06-27 | Dataset passport benchmark: deep-паспорта датасетов получили `quality` (`good/partial/weak/empty`, score/warnings/signals), warmup теперь отдаёт per-dataset timing/cache-status, а новый `POST /api/rag/datasets/profiles/benchmark` сравнивает cold rebuild и warm cached read без reindex/OCR/LLM | ✅ рантайм, focused/verify + ship/smoke + live warmup/benchmark ✅ |
| 0.24.0.16 | HEAD | 2026-06-27 | Smeta composition candidates: объектная прикидка теперь показывает ГЭСН-кандидаты для непокрытого scope (`каркасные стены`, `сваи/ростверк`, `плоская кровля`, `крыльцо/терраса`) через `estimate_harness.search_norm`; кандидаты идут в answer/source/trace, но не добавляются в сумму автоматически | ✅ рантайм, focused/verify + ship/smoke + live dacha candidates ✅ |
| 0.24.0.15 | HEAD | 2026-06-27 | Smeta answer readability: объектная прикидка теперь отдаёт операторский список вместо плотного абзаца, прячет слово “шаблон” из видимого текста в пользу “типовой состав/локальный аналог”, warnings выводит отдельными bullet-строками, а итог — отдельным списком | ✅ рантайм, focused/verify + ship/smoke + preview ✅ |
| 0.24.0.14 | HEAD | 2026-06-27 | Smeta object analog fallback: объектная смета больше не падает в “нет шаблона” для близкого локального аналога; каркасная дача 150 м² на сваях считается по ближайшему ИЖС-аналогу `wooden_house` со статусом `rough_analog_object_assumed`, trace/provenance/source помечают аналог, а цепочка “два этажа → крыльцо → фундамент → плоская кровля” сохраняет контекст и выводит warnings по непокрытому scope | ✅ рантайм, full test + ship/smoke + live dacha dialogue ✅ |
| 0.24.0.13 | HEAD | 2026-06-27 | Smeta tool-trace memory: явный режим `smeta` читает прошлые `retrieval_trace` для продолжений tool-расчётов; fallback по массе для стальных/бронзовых конструкций не показывает `custom_mass_rates`/yaml как источники, добавляет кандидаты ГЭСН из сб.09 для ручной привязки, распознаёт высотные работы и применяет только явный коэффициент; `ГЭСН/ФЕР/ТЕР` PDF-нормы классифицируются как `NORMATIVE/NTD_CONSTRUCTION`, не `TABLE_SMETA` | ✅ рантайм, full test + ship/smoke + live smeta follow-up ✅ |
| 0.24.0.12 | HEAD | 2026-06-27 | Smeta context hardening: явный режим `smeta` собирает параметры объектной сметы из прошлых вопросов текущей сессии без склейки строк; `free`/read-attachment LLM-пути получают `session_memory`; парсер понимает «метров 150» и «в два этажа»; шаблонная смета предупреждает про сваи/крыльцо/плоскую кровлю вне состава; `estimate_harness` извлекает сборник из `ГЭСН:10-...` и rejects wrong collection для work_family | ✅ рантайм, full test + ship/smoke + live smeta context ✅ |
| 0.24.0.11 | HEAD | 2026-06-27 | Answer contract checks: финальные payload чата получают `answer_contract_check` с pass/warn, missing-полями и observed-сигналами таблиц/evidence; Совушка показывает операторское предупреждение «Контракт: замечания» и прячет детали в technical chips | ✅ рантайм, full test + ship/smoke + live SSE ✅ |
| 0.24.0.10 | HEAD | 2026-06-27 | Chat workflow contracts: `/api/chat/stream` шлёт операторские `progress`-события до final, tool/детерминированные ветки больше не выглядят как зависший чат; каждый final payload получает `scenario` и `answer_contract`, а `ProfileResolver.as_trace()` отдаёт `output_contract`; Совушка показывает сценарий и табличный контракт в чипах, технические id — в раскрывашке | ✅ рантайм, full test + ship/smoke + browser smoke ✅ |
| 0.24.0.9 | HEAD | 2026-06-27 | Passport dialog hotfix: «Паспорт области» больше не создаёт `ui.dialog()` из фоновой задачи; диалог предмонтирован в правильном NiceGUI slot и заполняется после async-загрузки памяти чата/deep-паспортов датасетов | ✅ рантайм, full test + ship/smoke + browser click ✅ |
| 0.24.0.8 | HEAD | 2026-06-27 | Operator UX/passports/streaming: первый слой чата показывает человеческие статусы (`Проверено`, `Без проверки`, маршрут, секунды), внутренние KOT/CTX/CACHE переехали в «Технические детали»; добавлена кнопка «Паспорт области» с памятью чата и deep-паспортами выбранных датасетов; SSE-токены принудительно обновляют пузырь ответа и скролл | ✅ рантайм, full test + ship/smoke ✅ |
| 0.24.0.7 | HEAD | 2026-06-27 | Chat table-format correction: локальный technical/legal RAG снова предпочитает компактную markdown-таблицу, если найдено несколько требований/условий; короткий профиль теперь режет простыни/постскриптумы, а не таблицы | ✅ рантайм, full test + ship/smoke + live table check ✅ |
| 0.24.0.6 | HEAD | 2026-06-27 | Chat stability/source trace: локальный MLX получает меньший default context budget и короткий формат для technical/legal RAG; `/api/chat` отдаёт `source_map`, совпадающий с номерами prompt-блоков `Источник N`; `latency_phases` возвращает retrieval/context/generation/validation/overhead/total; `saferag_service.py` добавлен в critical runtime alignment | ✅ рантайм, full test + ship/smoke + live chat latency/source-map ✅ |
| 0.24.0.5 | HEAD | 2026-06-27 | External Radar: Самовар получил no-reindex обзор внешних корней, `file_map.db`-кандидатов и уже indexed in-place `documents.source_path`; новый API `GET /api/external-radar/summary`; радар делает только shallow-статистику и не читает содержимое файлов | ✅ рантайм, full test + ship/smoke + live radar ✅ |
| 0.24.0.4 | HEAD | 2026-06-27 | Deep context memory: паспорта датасетов получили `depth=deep` поверх bounded read из `lexical_chunks` (top-documents/headings/content-keywords/norm_refs/table-signal/fragments) без reindex/OCR/LLM; prompt-блок ограничивает число датасетов; добавлен no-reindex прогрев `POST /api/rag/datasets/profiles/warmup`; профиль честно пишет `available=false`, если lexical index не готов | ✅ рантайм, full test + ship/smoke + live warmup ✅ |
| 0.24.0.3 | HEAD | 2026-06-27 | Context memory: добавлен `context_memory_service` с паспортом чата (`les_chat_profiles`) и паспортом датасета (`les_dataset_profiles` + `storage/datasets/{dataset_id}/_les_dataset_profile.json`); RAG-промпт получает компактный фон по текущей сессии/датасетам после resolve scope, явно помеченный как НЕ evidence; `save_chat_history` обновляет профиль сессии; добавлены API просмотра `GET /api/chat/memory/{session_id}`, `GET /api/rag/datasets/{id}/profile` и admin refresh | ✅ рантайм, full test + ship/smoke ✅ |
| 0.24.0.2 | HEAD | 2026-06-27 | Operator-facing source/normcontrol polish: вкладка «Инструменты» оставлена только под служебные источники данных с папками, кнопкой открытия и безопасной play-проверкой; `/api/service-sources/{id}/process` отдаёт понятный статус без скрытых импортов; явные режимы больше не теряют read-вложение: «Смета»/smeta_harness передают текст в инструмент, «Проверка проекта» честно просит датасет/PDF для layout-нормоконтроля; сметный чат получил weight-based fallback для тяжёлых стальных/бронзовых ярусов по массе с ASSUME-ставками; chat-report нормоконтроля очищен от служебных enum/англицизмов; drawer источников больше не показывает техническое предупреждение для логических refs типа ГЭСН/ГОСТ | ✅ рантайм, fast ship/smoke ✅ |
| 0.24.0.1 | HEAD | 2026-06-27 | Operator-facing normcontrol stabilization: `doc_review` получил persist-sidecar решений инженера (`confirmed/rejected/needs_more_evidence`) через API, JSON/XLSX/HTML и GUI-кнопки; вкладка «Инструменты» возвращена в админку; `sovushka_ng.py` добавлен в deploy/critical bundle, чтобы shell-правки реально выкатывались; чат получил явную панель служебных источников (ГЭСН/ФГИС/СПДС/layout); chat-report нормоконтроля больше не рендерится как огромные markdown-таблицы/авто-артефакт | ✅ рантайм, fast ship/smoke ✅ |
| 0.24.0.0 | HEAD | 2026-06-27 | SPDS/public-ready baseline: ГОСТ Р 21.101-2026 doc-review теперь отдаёт общий `normalized_remarks` contract поверх `items`/`defense` для checklist/DOCX/PDF renderers; XLSX включает лист `normalized_remarks`; Admin GUI скачивает XLSX/JSON/HTML; `/api/version.runtime_alignment` расширен на doc-review/service-sources entrypoints; добавлены source-available `LICENSE`, `SECURITY.md`, public publication checklist and `make public-check` guardrail | ✅ рантайм, full ship/smoke ✅ |
| 0.23.6.12 | uncommitted | 2026-06-27 | Service source registry + layout v1: added `config/service_sources.yaml`, `service_source_registry` and `/api/service-sources` so Admin/GUI shows required data for smeta and normcontrol (ГЭСН, ФГИС ЦС, coefficients/templates, СПДС rulepack, normative RAG, layout reference); Instruments page now surfaces those sources and missing/degraded status; title-block check now verifies that text-layer stamp signatures are in the expected bottom-right zone, and reports signatures outside the zone as a computed issue | ✅ рантайм, fast ship/smoke ✅ |
| 0.23.6.11 | uncommitted | 2026-06-27 | Normcontrol human defense report: chat doc-review now renders a defendable human report with verdict, evidence/action tables and “Защита решения”; working memory is no longer appended to doc-review answers; `defense` is exposed at top-level chat payload; D4-001 sheet format is computed from PDF page geometry via ГОСТ 2.301, while deeper element placement/fill remains explicit layout/title-block work | ✅ рантайм, fast ship/smoke ✅ |
| 0.23.6.10 | uncommitted | 2026-06-27 | Attachment UX + release cadence: after upload the chat now shows a visible system message and composer strip saying the file/table will go with the next request; `make ship` is the fast iteration gate (verify + focused tests + smoke + deploy + retry post-smoke), `make ship-full` keeps the full pytest release gate | ✅ рантайм, fast ship/smoke ✅ |
| 0.23.6.9 | uncommitted | 2026-06-27 | System defense-contract v1: `DefensePack/DefenseClaim` added to `evidence_contract`; object-estimate now exposes per-GESН formula values, physical quantities, direct/НР/СП build-up, resource price coverage/missing-price examples, explicit non-defensible-LSR status, and ASSUME sections as non-normative; doc-review/normcontrol JSON now emits the same `defense` contract; object-estimate chat payload includes `defense` for UI/export | ✅ рантайм, full pytest/smoke ✅ |
| 0.23.6.8 | uncommitted | 2026-06-27 | Chat attachment contract: default file attach is "to chat", composer/user bubble show the attached file, read attachments send filename-bearing `attachment_context` to the model; plain file-reading tasks use attachment-only LLM route without global RAG noise; direct/router LLM calls use local MLX when cloud is not keyed | ✅ рантайм, make ship/smoke/live attach ✅ |
| 0.23.6.7 | uncommitted | 2026-06-27 | Latency hotfix: `LES_ROUTER_PRIMARY` default is now explicit opt-in (`false` unless set) so deterministic chat paths do not wait the 12s LLM-router timeout before cascade fallback; added regression for router-primary default | ✅ рантайм, verify/test/smoke ✅ |
| 0.23.6.6 | uncommitted | 2026-06-27 | v0.23B partial: source chips with real `source_ref` open a citation drawer in the Artifacts panel; weak/vector and missing-ref sources do not fake file opening and expose a clear unavailable reason; citation drawer keeps snippets only and copy actions for `source_ref`/citation | ✅ рантайм via 0.23.6.7 |
| 0.23.6.5 | uncommitted | 2026-06-27 | Stability contract pass: read-attachment converter failures return controlled 422 instead of leaking a backend exception; the hidden-by-default artifact panel now has an explicit GUI open control; Guardrails documents the per-feature stability contract and current green test baseline | КОД, verify/test ✅, ждёт deploy |
| 0.23.6.4 | uncommitted | 2026-06-27 | UI defaults: chat/admin start in light theme, artifacts panel is collapsed by default and opens only on explicit artifact/file/verify actions; OpenAI-compatible cloud defaults to `gpt-4.1` instead of blank/local model names; object-estimate carries calculation footer, sources, trace and evidence summary through `/api/chat` | КОД, verify/test/smoke ✅, ждёт deploy |
| 0.23.6.3 | uncommitted | 2026-06-27 | UI/smeta stabilization: chat attachments get `read` mode (file text as request context), quick/index attachments are sent as `dataset_ids`; composer gets direct scope/folder buttons and removable attachment chip; object-estimate now produces a rough full-object budget from vague ToR (ГЭСН-конструктив + explicit `ASSUME` allowances + `price_level_k` + VAT) while detailed estimates remain file/dataset-driven | КОД, verify/test/smoke ✅, ждёт deploy |
| 0.23.6.2 | uncommitted | 2026-06-27 | v0.23A stabilization: default trusted loopback/proxy networks narrowed to `127.0.0.1/32`; KOT term matching uses word-boundary regex with explicit `противопожар`; Samovar verifies Qdrant point count for every indexed file by default; backup archives get `SHA256SUMS.txt`, restore refuses checksum mismatch | КОД, verify/test/smoke ✅, ждёт deploy |
| 0.23.6.1 | uncommitted | 2026-06-27 | router-primary fallback: `RouterUnavailable` ≠ `none`; при недоступном роутере включается deterministic cascade + legacy in-flow gates (`mail`/`reconcile`/`table_agg`/`clause`/scope clarification) с честным `route_source`; `maybe_agent_route` снова зависит только от `LES_AGENT_LOOP` | КОД, tests ✅, ждёт deploy |
| 0.23.6 | `3362cee`+ | 2026-06-27 | версия 0.23.N.P в /api/version (`LES_VERSION`) + 5 fail-фиксов (4 версионных стейл-теста, help topic_slices) + сметный скилл (`skills/smeta/SKILL.md`) + `make ship`-гейт | КОД, ждёт deploy |
| 0.23.5 | `1cb1bd4` | 2026-06-27 | docs-аудит (4 прохода, сверка с кодом) + `MODULE_INDEX.md` + `RELEASE_LEDGER.md` + 3 новых ALGO/GUARDRAILS + архив мёртвого | — (docs) |
| 0.23.4 | `8f777a8`/`f414c90` | 2026-06-27 | чистка доков: 18 исторических → `docs/archive/` + указатели | — (docs) |
| 0.23.3 | `75ed9da` | 2026-06-27 | нормоконтроль: doc-review retrieval-подфаза (факты корпуса + текст требования) | ✅ рантайм |
| 0.23.2 | `a21f7dc` | 2026-06-27 | нормоконтроль: title_block OCR для сканов (флаг `LES_TITLE_BLOCK_OCR`) | ✅ рантайм |
| 0.23.1 | `57e4337` | 2026-06-27 | смета: многопозиционная ЛСР форма Приложения 4 (разделы+свод) | ✅ рантайм |
| 0.23.0 | `530f07b` | 2026-06-27 | смета: рендер ЛСР в форму Приложения 4 (одна позиция) | ✅ рантайм |
| ≤0.23 | см. [releases.md](releases.md) | до 06-27 | вехи v0.19–v0.23 (version stamp, evidence UI, route safety, source ops, trust hardening) | — |

> Полная история вех v0.13–v0.23 — в [releases.md](releases.md). Этот леджер ведём с гранулярностью фич
> (`0.23.N`), releases.md — по вехам (`v0.NN`).

## Здоровье на 2026-06-27 (из прогона)

```
make verify:     ✅ зелёный (2062 собрано)
make test:       ✅ 2062 passed / 6 warnings / 317.64s
make smoke-basic: ✅ pass=9 / warn=0 / fail=0 (chat_glossary 75.6с; chat_project_noscope 106.3с)
make verify 0.23.6.7: ✅ зелёный (2063 собрано)
make test 0.23.6.7:   ✅ 2063 passed / 6 warnings / 223.75s
post-deploy smoke:    ✅ pass=9 / warn=0 / fail=0 (chat_glossary 5ms; chat_project_noscope 8ms)
make ship 0.23.6.8:   ✅ verify 2067 collected; test 2067 passed / 6 warnings / 220.73s; smoke pass=9
post-deploy 0.23.6.8: ✅ pass=9 / warn=0 / fail=0 (chat_glossary 49ms; chat_project_noscope 10ms)
live attach-check:    ✅ crag_status=ATTACHMENT; route=attachment_context/read_attachment; sources=[attachment:demo.txt]
make ship-full 0.23.6.9: ✅ verify 2068 collected; test 2068 passed / 6 warnings / 221.83s; smoke pass=9
post-deploy 0.23.6.9:   ✅ pass=9 / warn=0 / fail=0 (manual retry after restart; motivated retry-smoke)
make ship 0.23.6.10:    ✅ verify 2069 collected; focused 35 passed; pre-smoke pass=9; post-smoke pass=9 after retry
make ship 0.23.6.11:    ✅ verify 2071 collected; focused 40 passed; pre-smoke pass=9; post-smoke pass=9
live doc-review BAI:    ✅ crag_status=VERIFIED; cache=doc_review; items=15; top-level defense present; no LES.md/memory leak
make ship 0.23.6.12:    ✅ verify 2076 collected; focused 56 passed; pre-smoke pass=9; post-smoke pass=9
live service-sources:     ✅ /api/service-sources total=6; ok=5; missing_blocking=0; smoke pass=9 after runtime app registration
make ship-full 0.24.0.0: ✅ verify 2078 collected; test 2078 passed / 6 warnings / 223.10s; pre-smoke pass=9; post-smoke pass=9
live doc-review 0.24:   ✅ ГОСТ Р 21.101-2026; items=15; normalized_remarks=15; defense=true
public-check 0.24:      ✅ git-visible files: no forbidden runtime paths or high-signal secrets
focused 0.24.0.3:       ✅ 33 passed (context-memory + chat/version)
make verify 0.24.0.3:   ✅ 2088 collected
make test 0.24.0.3:     ✅ 2088 passed / 6 warnings / 220.92s
make ship 0.24.0.3:     ✅ verify 2088 collected; focused 61 passed; pre-smoke pass=9; post-smoke pass=9
live context-memory:    ✅ /api/version 0.24.0.3 aligned checked=24; dataset profile endpoint wrote `_les_dataset_profile.json`
focused 0.24.0.4:       ✅ 60 passed (context-memory + datasets router + version)
make verify 0.24.0.4:   ✅ 2090 collected
make test 0.24.0.4:     ✅ 2090 passed / 6 warnings / 220.45s
make ship 0.24.0.4:     ✅ verify 2090 collected; focused 61 passed; pre-smoke pass=9; post-smoke pass=9
live deep warmup:       ✅ /api/version 0.24.0.4 aligned checked=24; warmup status=ok built=3/3 depth=deep
focused 0.24.0.5:       ✅ 43 passed (external radar + external index/filemap/version)
make verify 0.24.0.5:   ✅ 2093 collected
make test 0.24.0.5:     ✅ 2093 passed / 6 warnings / 122.18s
make ship 0.24.0.5:     ✅ verify 2093 collected; focused 61 passed; pre-smoke pass=9; post-smoke pass=9 after retry
live external-radar:    ✅ /api/version 0.24.0.5 aligned checked=26; summary status=ok roots=2 external_docs=1842 candidates=2
focused 0.24.0.6:       ✅ 65 passed (source-map/chat/version); после short-format tuning ✅ 32 passed
make verify 0.24.0.6:   ✅ 2096 collected
make test 0.24.0.6:     ✅ 2096 passed / 6 warnings / 126.83s
make ship 0.24.0.6:     ✅ verify 2096 collected; focused 61 passed; pre-smoke pass=9; post-smoke pass=9
live chat 0.24.0.6:     ✅ FIRE 52.8s (source_map=5, unknown citations=0); HVAC 37.0s (source_map=4, unknown citations=0)
focused 0.24.0.7:       ✅ 32 passed (source-map/chat/version)
make test 0.24.0.7:     ✅ 2096 passed / 6 warnings / 121.69s
make ship 0.24.0.7:     ✅ verify 2096 collected; focused 61 passed; pre-smoke pass=9; post-smoke pass=9 after restart retry
live table 0.24.0.7:    ✅ FIRE has_table=true; 50.6s; source_map=5; unknown citations=0
focused 0.24.0.10:      ✅ 58 passed (answer contracts + SSE progress + UI helpers + profile resolver + version)
make verify 0.24.0.10:  ✅ 2102 collected
make test 0.24.0.10:    ✅ 2102 passed / 6 warnings / 127.99s
make ship 0.24.0.10:    ✅ verify 2102 collected; focused 63 passed; pre-smoke pass=9; post-smoke pass=9
live 0.24.0.10:         ✅ /api/chat/stream emits progress→final with scenario=tool and answer_contract=tool_result_v1; /classic 200
focused 0.24.0.11:      ✅ 45 passed (answer_contract_check + SSE + UI chips + version)
make verify 0.24.0.11:  ✅ 2104 collected
make test 0.24.0.11:    ✅ 2104 passed / 6 warnings / 126.62s
make ship 0.24.0.11:    ✅ verify 2104 collected; focused 63 passed; pre-smoke pass=9; post-smoke pass=9
live 0.24.0.11:         ✅ /api/chat/stream final has answer_contract_check=pass for glossary tool route; /classic 200
focused 0.24.0.12:      ✅ 86 passed (memory + smeta/object + harness + attachment prompt)
make verify 0.24.0.12:  ✅ 2113 collected
make test 0.24.0.12:    ✅ 2113 passed / 6 warnings / 133.58s
make ship 0.24.0.12:    ✅ verify 2113 collected; focused 69 passed; pre-smoke pass=9; post-smoke pass=9
live 0.24.0.12:         ✅ /api/version 0.24.0.12 aligned checked=30; smeta follow-up `А давай два этажа` keeps 150 м² and returns `2 эт.`; frame-house request now recognizes area/floors/material and refuses no-template instead of losing params
focused 0.24.0.13:      ✅ 92 passed (document router + smeta/memory/harness)
make verify 0.24.0.13:  ✅ 2117 collected
make test 0.24.0.13:    ✅ 2117 passed / 6 warnings / 136.34s
make ship 0.24.0.13:    ✅ verify 2117 collected; focused 71 passed; pre-smoke pass=9; post-smoke pass=9
live 0.24.0.13:         ✅ /api/version 0.24.0.13 aligned checked=30; `учти высотные работы` reuses prior mass and blocks coefficient; `k=1,15` recalculates to 139 532 515.00 ₽; GESN PDF route=NORMATIVE/NTD_CONSTRUCTION
dataset 0.24.0.13:      ✅ external `GESN_NORMS_2022_PDF` = b774e116-8172-4b53-84da-9c923c13693d, 118 PDF as NORMATIVE/NTD_CONSTRUCTION, metadata profile built; parse left PENDING due memory guard
focused 0.24.0.14:      ✅ 30 passed (object_estimate + smeta_chat), ship-focused ✅ 74 passed
make verify 0.24.0.14:  ✅ 2120 collected
make test 0.24.0.14:    ✅ 2120 passed / 6 warnings / 133.34s
make ship 0.24.0.14:    ✅ verify 2120 collected; focused 74 passed; pre-smoke pass=9; post-smoke pass=9
live 0.24.0.14:         ✅ /api/version 0.24.0.14 aligned checked=30; smeta session `дача каркас 150 м² 1 эт.` → `два этажа` → `крыльцо` → `фундамент` → `плоская кровля` keeps 150 м²/2 эт., status `rough_analog_object_assumed`, total 48 283 098.41 ₽, warnings for piles/porch/flat roof
focused 0.24.0.15:      ✅ 30 passed (object_estimate + smeta_chat)
make verify 0.24.0.15:  ✅ 2120 collected
make ship 0.24.0.15:    ✅ verify 2120 collected; focused 74 passed; pre-smoke pass=9; post-smoke pass=9
live 0.24.0.15:         ✅ /api/version 0.24.0.15 aligned checked=30; object-estimate answer preview uses bullet blocks: `Коротко`, `Почему выбран этот аналог`, `Что не покрыто точно`, `Итог`, `Ключевые допущения`
focused 0.24.0.16:      ✅ 62 passed (object_estimate + smeta_chat + estimate_harness)
make verify 0.24.0.16:  ✅ 2121 collected
make ship 0.24.0.16:    ✅ verify 2121 collected; focused 75 passed; pre-smoke pass=9; post-smoke pass=9 after restart retry
live 0.24.0.16:         ✅ /api/version 0.24.0.16 aligned checked=30; smeta dacha answer returns `composition_candidates.status=found`, source_kind `norm_candidate`, and visible ГЭСН candidates for frame walls/piles/flat roof/porch without adding them to the total
focused 0.24.0.17:      ✅ 38 passed (context-memory + datasets router)
make verify 0.24.0.17:  ✅ 2122 collected
make ship 0.24.0.17:    ✅ verify 2122 collected; focused 75 passed; pre-smoke pass=9; post-smoke pass=9 after restart retry
live 0.24.0.17:         ✅ /api/version 0.24.0.17 aligned checked=30; dataset profiles warmup 31/31 in 19.007s; benchmark 31/31 cold 9988.91ms vs warm 3462.95ms, speedup 2.88x, quality good=22 partial=9
focused 0.24.0.18:      ✅ 54 passed (answer contracts + doc-review + smeta + version)
make verify 0.24.0.18:  ✅ 2123 collected
make ship 0.24.0.18:    ✅ verify 2123 collected; focused 75 passed; pre-smoke pass=9; post-smoke pass=9 after restart retry
live 0.24.0.18:         ✅ /api/chat returns `workflow_plan.schema=workflow_plan_v1`; /api/version 0.24.0.18 aligned checked=31
focused 0.24.0.19:      ✅ 19 passed (sovushka chat + answer contracts)
make verify 0.24.0.19:  ✅ 2123 collected
make ship 0.24.0.19:    ✅ verify 2123 collected; focused 75 passed; pre-smoke pass=9; post-smoke pass=9 after restart retry
live 0.24.0.19:         ✅ /api/chat returns `workflow_plan.schema=workflow_plan_v1`, `workflow_id=tool`, `status=needs_data`, `finality=not_final`; /api/version 0.24.0.19 aligned checked=31
focused 0.24.0.20:      ✅ 92 passed (profile resolver + answer contracts + smeta quick tools + estimate harness + agent router)
make verify 0.24.0.20:  ✅ 2101 collected
make test 0.24.0.20:    ✅ 2101 passed / 6 warnings / 134.60s
make ship 0.24.0.20:    ✅ verify 2101 collected; focused 99 passed; pre-smoke pass=9; post-smoke pass=8 warn=1 fail=0 after proxy restart retry
live 0.24.0.20:         ✅ /api/version 0.24.0.20 aligned checked=31; runtime `object_templates.yaml` and `object_estimate_service.py` absent; quick smeta channel returns None for house/dacha/steel-mass object requests. ⚠ `/api/chat mode=smeta` dacha live probe timed out at 180s in model tool-loop — stability/latency backlog, not fallback.
```

**Закрыто в 0.23.6.7:** latency-smoke был не LLM generation, а 12s ожидание недоступного
LLM-router перед deterministic fallback (`router_unavailable_cascade_fallback`). Router-primary теперь
явный opt-in: без `LES_ROUTER_PRIMARY=true` быстрые deterministic/RAG fallback-пути не ждут router timeout.
**Закрыто в 0.23.6.8:** read-вложение стало контрактом "файл к следующему сообщению": UI показывает
имя файла, backend получает `attachment_context`, plain file-reading идёт по attachment-only LLM route
без глобального RAG, а direct/router LLM без облачного ключа уходит в локальный MLX вместо 401.
**Закрыто в 0.23.6.10:** после галочки upload файл не исчезает в тишину: composer показывает явную
плашку "к следующему сообщению", а в ленте чата появляется системное сообщение. Полный pytest теперь
`make ship-full`, быстрый итерационный выкат — `make ship` с retry post-deploy smoke.
**Закрыто в 0.23.6.11:** нормоконтроль в чате больше не выглядит как trace-мусор: это человеческий
отчёт с defended/blocked/manual секциями, source/action таблицами и top-level `defense`. `memory_block`
не примешивается к doc-review. Формат листа D4-001 снова computed: PDF-страницы измеряются и
классифицируются по ГОСТ 2.301; размещение рамки/граф и заполнение основной надписи остаются отдельной
layout/title-block задачей, а не скрытой уверенностью модели.
**Закрыто в 0.23.6.12:** служебные источники стали видимым контрактом (`/api/service-sources` + блок в
Инструментах): оператор видит, какие файлы нужны ЛЕСу для смет и нормоконтроля, где они лежат и что
деградирует без них. Layout v1 для основной надписи проверяет не только наличие сигнатур, но и попадание
в ожидаемую нижнюю правую зону листа; сигнатуры вне зоны дают computed issue.
**Закрыто в 0.24.0.0:** v0.24 оформлен как первый публично объяснимый SPDS workflow: doc-review
имеет человеческий отчёт, `defense_contract_v1`, `normalized_remarks` для последующих checklist/DOCX/PDF
слоёв, XLSX/JSON/HTML выгрузки в GUI, а repo получил source-available license/security/publication gate.
Полная публикация GitHub остаётся owner-gated: сначала scrub private data/secrets, затем менять visibility.

**Закрыто в 0.23.6.1:** router-primary регрессия переведена в честный
`RouterUnavailable` → deterministic cascade/in-flow fallback; `LES_ROUTER_PRIMARY` больше не включает
legacy agent loop. Латентность live-чата остаётся отдельной операционной темой.

## Следующее (по приоритету — хендофф)

1. **v0.24+ ПП-87/checklist/DOCX/PDF**: composition profile, checklist template import, rendered
   DOCX/PDF normcontrol reports.
2. **v0.26+ Минстрой-индексы** ([[minstroy-indices-source]]): последнее письмо ИФ/09 через VPS box →
   parquet → `index_lookup` к РИМ-трассе.
3. **GRAND-фиделити формы ЛСР** (долг #2): метаданные шапки из проекта, расширенные графы.
4. Доделать `make ship`-дисциплину как привычку: версия+леджер+док в каждом фиче-коммите
   (Definition of Done в AGENTS.md; стандарт — `docs/DOCUMENTATION_PLAYBOOK.md`).
