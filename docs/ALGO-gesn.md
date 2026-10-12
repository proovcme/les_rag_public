# Алгоритм: ГЭСН — норма → ресурсы (замыкает сборку ЛСР от кода)

## Кандидат929 — nullable finite consumption

Новая сборка typed SQLite допускает per_unit NULL; importer сохраняет
неизвестное/invalid как отсутствие расхода, а известный0 как0. Readers и
expand_position не дописывают0 вместо неизвестного; norm_browser сообщает
consumption_known только для конечного расхода. Проверки None/0/NaN/inf
проходят через импорт, чтение, расчёт и XLSX. Пользовательская БД не изменялась,
нормы/ресурсы не выбираются кодом, старые0 не переинтерпретируются.

## Проверенная граница 894: calculator overlay не равен каталогу

Диагностика установленной893: typed `norm_browser` и `read_norm_card_exact`
читают canonical SQLite; `_merged_norms` дополнительно заполняет отсутствующие
ключи runtime overlay. Поэтому наличие нормы в expand не доказывает её
доступность модели через поиск. ГЭСНм10-01-001-12: expand200/1ресурс, в browse
по коду и таблице нет; см. artifacts/live_892/reference_inventory. Это долг
согласованности данных, не основание подмешивать ответы из контрольной сметы
или автоматически считать непроверенный overlay нормативным эталоном.
Ни миграции, ни реиндекса в894 не выполнено. Историческое описание общей базы
ниже не означает, что дополнительный overlay опубликован в RAG.

Разложение **нормы ГЭСН** на ресурсы (расход труда/машин/материалов на единицу) → строки для
движка сборки ЛСР. 0 LLM (ADR-11). Это последний кирпич: после него ЛСР собирается прямо от
`{код ГЭСН, объём}`, без ручного ввода ресурсов.

## Идея

Норма ГЭСН-2022 (Приказ 1046/пр) задаёт **количества** ресурсов на единицу работы: трудозатраты
рабочих (чел-ч), время эксплуатации машин (маш-ч) + ОТм машинистов, расход материалов. Цены —
из ФГИС ЦС (по коду ресурса), кроме ОЗП/ОТм (тариф по разряду). `expand_position(code, qty)`
умножает расход на объём позиции → строки ресурсов для [[ALGO-lsr-assembly]].

## Шаги

1. **Каталог** — `gesn_service._merged_norms` объединяет базу и официальный overlay; это
   source of truth расчёта и поиска (§ 3):
   - **Canonical machine base** `data/smeta_base/les_smeta_base.sqlite`: одна структурированная
     SQLite-база с таблицами `norms` и `resources`. Ключ нормы:
     `norm_key=<base_type>:<bare_code>`. `ГЭСН:38-01-001-01` и `ГЭСНм:38-01-001-01` — разные нормы;
     bare-код при multi-family collision не раскрывается strict lookup. Overlay
     `data/gesn_base/gesn2022_overlay.parquet` (`tools/gesn_fgis_overlay_import.py`)
     закрывает только отсутствующие ключи, не выбирает работу и не затирает SQLite.
   - **Семя** `config/domain/gesn_seed.yaml`: демо-нормы = {code, name, unit, resources:[…]}.
     Ресурс: kind (labor|machinist|machine|material), per_unit, code (для цены ФГИС ЦС),
     price (тариф ОЗП/ОТм; для машин/материалов — опц. снимок цены).  В production НЕ участвует:
     подключается только явным `path=` в вызове или `LES_GESN_SEED_ENABLED=1` (названный тестовый
     сценарий) и помечается `_source_kind = "seed_yaml"`.  Семя больше не перекрывает базу: замеры
     30.09.2026 показали, что все 10 демо-карточек уже есть в базе и семя подменяло их числа
     (`stage_b/live_830/seed_vs_base_reconcile_830.md`, запрет закреплён
     `tests/test_gesn_seed_is_test_only_830.py`).
   `data/gesn_base/gesn2022_unified.parquet` теперь source/staging слой, а не runtime-facing база:
   он собирается из raw ФГИС/ручных импортов через `tools/gesn_unify_base.py`, затем очищается и
   раскладывается в staging SQLite через `tools/build_smeta_structured_base.py`, а активная пара
   SQLite+RAG публикуется только `tools/smeta_generation_coordinator.py`. Нормы без `norm_name` или
   `norm_unit` не выдаются машине; они попадают в `data/smeta_base/les_smeta_base_manifest.json`
   как excluded source debt.
2. **Разворот** (`expand_position`): qty_строки = per_unit × объём; kind/name/code/price переносятся.
3. **Интеграция**: `lsr_assembly.compute_position` — если у позиции есть `code`, но нет `resources`,
   разворачивает по норме; дальше штатный пайплайн (цены→ОЗП/ЭМ/М→стеснённость→НР/СП→Всего).

## Импорт полной базы ГЭСН-2022

`tools/gesn_import.py` — CLI: выгрузка (xlsx/csv) → нормализованный Parquet (аналог импорта ФГИС ЦС).

    uv run python -m tools.gesn_import IN.xlsx --out storage/cache/gesn_fgis/gesn2022_manual_raw.parquet
    uv run python -m tools.gesn_import IN.csv  --layout flat     # строка=ресурс, явная шапка
    uv run python -m tools.gesn_import IN.xlsx --layout blocks   # норма-блоками (стиль ГРАНД)

Схема Parquet (плоско, строка=ресурс): `norm_code, norm_name, norm_unit, kind, per_unit,
resource_code, resource_name, resource_unit, price`. Сервис группирует по `norm_code`.

**Источник (уточнено895).** Официальный ФГИС даёт структурированные карточки через
`FullTextSearch/SearchEstimatedRates`; официальный OpenData ФСНБ также содержит XML
снимки. Утверждение «только PDF, бесплатных машиночитаемых данных нет» было неверным.
Это подтверждают исходники [fgis-mcp](https://github.com/proovcme/fgis-mcp/tree/7a6aeeb01b33866d20b5a0ad9a71fbc590d47b00)
и HTTP200 на публичный запрос10-01-001-12 (410029bytes,2 публикации):
`artifacts/live_895/fgis_http_probe.json`. Нужная норма присутствует; проверка текущим
импортёром дала1 строку ресурса. Версия/действие публикации не сертифицированы этим
поиском. Ответ сохранён в staging/audit и не активировал новую базу или индекс.
XLSX/CSV импорт остаётся альтернативой; неполный или непроверенный снимок нельзя
выдавать за полную нормативную базу. Публикация по-прежнему только через coordinator.

## Storage contract: source похож на ФГИС, runtime похож на сметную модель

Для автоматизации обновления структура должна быть близкой к источнику, а для ответа/расчёта —
близкой к предметной области:

1. `storage/cache/gesn_fgis/` — raw/source cache. Здесь допустимы исходные payload/parquet ФГИС,
   overlay и промежуточные файлы. Это не runtime base и не часть репо.
2. `data/gesn_base/gesn2022_unified.parquet` — checked source/staging snapshot: одна строка =
   ресурс нормы, typed `norm_key=<base_type>:<bare_code>`, удобно для bulk merge/diff/audit.
3. `data/smeta_base/les_smeta_base.sqlite` — canonical machine base: `norms` и `resources`,
   индексы, точный lookup, manifest исключений. Это читает `gesn_service` в нормальном режиме.
4. `RAG_Content/TABLE_SMETA/SMETA_SERVICE` — generated markdown-карты для модели. Они строятся
   из machine/source state и не являются расчётной базой.

Команды:

    # быстро: из уже проверенного unified parquet в runtime SQLite + service cards
    make smeta-base

    # без скачивания: raw/cache → unified parquet → SQLite → service cards
    make smeta-base-source

    # долго: скачать/обновить ФГИС → unified parquet → SQLite → service cards
    make smeta-base-update

## Полная база из ФГИС ЦС — `tools/gesn_bulk_import.py` (рекомендуемый путь)

Структурный расход ВСЕХ норм бесплатно отдаёт сам ФГИС ЦС через
`GET /api/FullTextSearch/SearchEstimatedRates?search=<код>` (без auth/квоты/гео — прямой urllib).
Поиск — **префиксный по шифру**: `search=NN-NN` (отдел) возвращает все нормы всех таблиц отдела
одним ответом (доказано: `12-03` ⊇ нормы per-table `12-03-001` без потерь). Поэтому перебор идёт
по **отделам** `NN-NN` (на порядок меньше запросов, чем per-table); `search=NN` (сборник целиком)
НЕнадёжен — >15 МБ, рвётся по таймауту. Отделы разрежены (у сб.12: 01–05,07–18,20,21,23) — отдел
`NN-01..NN-MAX` сканируется с допуском пропусков (`--otdel-gap`), записи с чужим префиксом
отбрасываются (защита от шума fulltext).

    # один сборник (проверка):
    uv run python -m tools.gesn_bulk_import --sbornik 12

    # ПОЛНАЯ база (numeric prefixes 01..69, ~часы — оценка ниже):
    uv run python -m tools.gesn_bulk_import --all --rate 1.0

После bulk/import raw-слой пересобирается в единый source parquet и canonical SQLite:

    uv run python -m tools.gesn_unify_base
    uv run python -m tools.smeta_generation_coordinator \
      --source data/gesn_base/gesn2022_unified.parquet

Coordinator reads configured active SQLite/metadata paths, arbitrary RAG alias and `minimum_norms`
from `config/domain/smeta_base_active.json`. It builds both artifacts beside the active generation,
checks the floor, exact SQLite SHA and live native RRF, then switches them under one cross-process
lease. The low-level builder CLI refuses the configured active path. An incomplete or unavailable
SQLite/Qdrant build remains an error and cannot overwrite the active pair. For Windows clean install the releaser creates a verified payload with
`uv run python tools/smeta_release_baseline.py create`; manually bundling an old `gesn2022.parquet` or
an unverified SQLite is prohibited.

Операторский путь в GUI: **Инструменты → Источники данных → ГЭСН-2022 → скачать/обновить из ФГИС ЦС**.
API: `POST /api/service-sources/gesn_base/fgis-update`, статус:
`GET /api/service-sources/gesn_base/fgis-update/status`.

Свойства: **резюмируемость** (уже залитые отделы пропускаются — прогон можно прерывать/продолжать),
rate-limit + retry с backoff, прогресс-лог, идемпотентный append с дедупом по ключу нормы.
**Оценка полного прогона:** prefixes 01..69, до 40 отделов с early-stop после 8 пустых;
обычно сотни запросов. Диапазон включает 47 строительных сборников и поздние префиксы
ГЭСНм/ГЭСНп/ГЭСНр/ГЭСНмр; семейство определяет metadata ФГИС. При `--rate 1.0`
(1 req/с) + время скачивания крупных отделов (отдельные ответы до 15 МБ) — порядка **30–90 мин**;
итог — десятки тысяч норм. На проверке: сб.12 = 1536 норм / 27 899 строк-ресурсов; сб.1 (2 отдела)
= 1462 нормы / 6714 строк; эталон 12-01-034-02 в базе точен (труд 12.94, краны 0.97/0.01, бортовой
0.03, гвозди 0.0015, бруски 0.4). Опц. VPS-egress: env `LES_FGIS_VIA_SSH=root@HOST`.

## Точечный overlay ГЭСНм/ГЭСНп

Когда нужна не вся база, а недостающая монтажная семья с правильным типом базы
(`ГЭСНм`, `ГЭСНп`), используется cache overlay:

    uv run python -m tools.gesn_fgis_overlay_import --preset sks \
      --out storage/cache/gesn_fgis/gesn2022_overlay_raw.parquet

Инструмент тянет официальный `SearchEstimatedRates` по точным шифрам норм/таблиц,
парсит структурный JSON и сохраняет `base_type`, `norm_key`, `source_doc`,
`source_guid`. Это важно для сборников с одинаковым голым номером: `ГЭСН10`
и `ГЭСНм10` не являются одной базой. Старый широкий bulk остаётся для полного
строительного слоя; overlay — для аккуратной дозаливки конкретных монтажных
разделов без полного реимпорта. После этого обязательно пересобирается unified parquet.

С 0.24.0.300 strict lookup (`get_norm(..., strict_family=True)`) не раскрывает голый шифр
без семейства (`38-01-001-01`) молча, если такой номер есть в нескольких семействах (`ГЭСН`,
`ГЭСНм`, `ГЭСНр`, `ГЭСНп` и т.д.). Обычный `get_norm()` оставлен совместимым для legacy API,
но model-facing candidate-store должен показывать typed-шифры; модель выбирает typed-шифр,
а код только проверяет ключ и раскрывает ресурсы.

С 0.24.0.301 overlay parquet (`gesn2022_v2.parquet`) не может пустыми `norm_name`/`norm_unit`
перетереть заполненные поля старой базы. Новый слой может добавить `work_steps`, typed key и
ресурсы, но имя и измеритель нормы сохраняются из предыдущего источника, если в overlay они
пустые. Это нужно, чтобы `add_position` доходил до формул/слотов и РИМ-расчёта, а не падал в
ложный `ambiguous` из-за пустого названия нормы.

## RAG-карточки из Smetnoedelo API v2.0

`api.smetnoedelo.ru/cs` полезен как читаемый для модели источник: разделы ФСНБ,
шифры норм/ресурсов, состав работ и ресурсные строки. Это не заменяет расчётный
Parquet и не делает сумму `priced_final`; карточки нужны для RAG-навигации и
подбора кандидатов ГЭСН/ГЭСНм/ГЭСНп/ресурсов.

Токен считается секретом и передаётся только через окружение:

```bash
export LES_SMETNOE_TOKEN='...'

# точечно нужные нормы/ресурсы
uv run python -m tools.smetnoedelo_rag_import \
  --runtime-root /Users/ovc/LES \
  --base gesnm2 \
  --code 10-06-058-01 \
  --code 38-01-001-01 \
  --sync-rag --parse

# навигация по базе с жёстким лимитом запросов
uv run python -m tools.smetnoedelo_rag_import \
  --runtime-root /Users/ovc/LES \
  --base gesn2 \
  --max-depth 2 \
  --max-requests 40 \
  --sync-rag
```

Поддерживаемые `base` берутся из API v2.0: `gesn2`, `gesnm2`, `gesnmr2`,
`gesnp2`, `gesnr2`, `fsbcm`, `fsbco`, `fsbcmm`, а также старые ресурсные
слои `fsem`, `fsscm`, `fssco`. Скрипт кеширует ответы в
`storage/cache/smetnoedelo_api`, не пишет токен в кеш/manifest/markdown и
останавливается по `--max-requests`. Для полного обхода баз сначала делать
малый прогон и проверять остаток квоты.

## Публичные ZIP-архивы Smeta.RU

Страница `https://smeta.ru/download/norm` отдаёт обычный HTML с прямыми ссылками
на `obs.smeta.ru/*.zip`. Эти архивы можно скачать без токена и браузерной сессии.
Для модели источником истины является RAG-корпус: архивы скачиваются в storage,
распаковываются, получают manifest/provenance, затем проецируются в
`RAG_Content/TABLE_SMETA/SMETA_RU_NORM` и индексируются как группа сметных
нормативных датасетов.

```bash
# посмотреть свежий ФСНБ-2022 и размер
uv run python -m tools.smeta_ru_norm_download --latest fsnb2022 --with-head --list

# скачать свежий архив в runtime storage
uv run python -m tools.smeta_ru_norm_download \
  --runtime-root /Users/ovc/LES \
  --latest fsnb2022 \
  --download

# скачать конкретную редакцию/семейство по regex
uv run python -m tools.smeta_ru_norm_download \
  --runtime-root /Users/ovc/LES \
  --pattern 'red-2020/gesn_i9' \
  --download
```

Скрипт пишет архивы в `storage/downloads/smeta_ru_norm`, считает `sha256` и
обновляет manifest. `--extract` распаковывает в `storage/extracted/smeta_ru_norm`,
но не создаёт RAG-корпус сам.

Авто-ingest архив-за-архивом:

```bash
uv run python -m tools.smeta_ru_norm_rag_ingest \
  --runtime-root /Users/ovc/LES \
  --latest-per-category \
  --category fsnb2022 \
  --sync-rag --parse
```

Worker скачивает один архив, безопасно распаковывает его, создаёт карточки
`00_group_classifier.md`, `00_dataset_card.md`, `01_archive_manifest.md`,
проецирует читаемые текстовые файлы и после каждого нового архива вызывает
`POST /api/rag/sync-smart`. Поддерживаемые исходные документы из архива
копируются в RAG только при явном `--max-source-files N`; по умолчанию raw
остаётся в `storage/extracted`, чтобы автоиндекс не подвисал на больших XLSX.
Вложенные `.vnbx` раскрываются как ZIP: worker пишет инвентарь и markdown-
проекции внутренних `.json/.xml/.txt/...`, чтобы RAG получил машинно-читаемые
слои архива до отдельного Parquet-parser.
Для машинных имён внутренних таблиц worker добавляет навигационную карточку:
`A_SRF_F` помечается как таблица норм/расценок ФСНБ, `A_SRF_TR` — как таблица
ресурсов нормы, `A_SRF_VR`/`A_F3_VR` — как навигация по видам работ и разделам,
`B_NORMTYPE` — как тип нормативной базы, `LEVEL_COST` — как ценовой уровень.
Это нужно, чтобы модель открывала нужные таблицы по роли, а не гадала по имени
служебного файла. Карточка остаётся навигацией/evidence к корпусу; применимость
нормы и сметный маршрут выбирает модель, а расчёт делает код по trace.
Состояние лежит в
`storage/state/smeta_ru_norm_rag_ingest_state.json`, поэтому повторный запуск
пропускает уже обработанные архивы без `--force`.

Структура RAG:

- группа: `TABLE_SMETA`;
- датасеты: `SMETA_RU_NORM_FSNB2022_Index`, `SMETA_RU_NORM_RED2020_Index` и т.д.;
- карточки архива хранят URL, редакцию, issue/date, sha256, инвентарь файлов и
  путь к извлечённым исходникам.

## Где в коде

- Сервис: `proxy/services/gesn_service.py`; production-каталог: `data/smeta_base/les_smeta_base.sqlite`
  (+ overlay `data/gesn_base/gesn2022_overlay.parquet`).  `config/domain/gesn_seed.yaml` — демо-нормы
  только для названного тестового сценария (§ 3).
- Overlay-import: `tools/gesn_fgis_overlay_import.py` (`--preset sks` для СКС/ВОЛС-кандидатов).
- Smetnoedelo API → RAG-карточки: `tools/smetnoedelo_rag_import.py`.
- Smeta.RU ZIP downloader: `tools/smeta_ru_norm_download.py`.
- Smeta.RU ZIP → RAG ingest worker: `tools/smeta_ru_norm_rag_ingest.py`.
- API: `GET /api/lsr/gesn` (список), `GET /api/lsr/gesn/{code}/expand?qty=` (`proxy/routers/lsr.py`).
- MCP: `les_gesn_expand`. Сборка от кода — `POST /api/lsr/assemble` (позиции `{code, qty}`).
- Тест: `tests/test_gesn_service.py` — сборка ЛСР прямо от кода карточки основной базы; цены берёт
  из книги, которую пишет сам тест (`BOOK_PRICES`), поэтому закреплённый итог 18535.77 пересчитывается
  на бумаге и не зависит от установленной ценовой базы.  Демо-ставка 475,11 руб./чел.-ч из семени в
  расчёт не попадает.

## Граница (главное незакрытое)

- **Семя** содержит демо-норму эталона и больше не участвует в расчёте: карточка эталона берётся из
  основной базы (замер 30.09.2026 — `stage_b/live_830/seed_vs_base_reconcile_830.md`).  **База
  ГЭСН-2022 импортирована**: `data/smeta_base/les_smeta_base.sqlite` несёт 49 818 норм и 504 891
  ресурс (`les_smeta_base_manifest.json`, `les_smeta_base_integrity.json` с `integrity.verdict =
  "passed"`).  Осталось закрытие отдельных пробелов импорта: 923 нормы без `norm_name`/`norm_unit`
  публикуются как excluded source debt, а не подменяются демо-числами.
- Подбор кода нормы под работу ВОР (наименование→ГЭСН) — отдельный шаг (ретрив по базе ГЭСН).
