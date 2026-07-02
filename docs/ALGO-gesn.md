# Алгоритм: ГЭСН — норма → ресурсы (замыкает сборку ЛСР от кода)

Разложение **нормы ГЭСН** на ресурсы (расход труда/машин/материалов на единицу) → строки для
движка сборки ЛСР. 0 LLM (ADR-11). Это последний кирпич: после него ЛСР собирается прямо от
`{код ГЭСН, объём}`, без ручного ввода ресурсов.

## Идея

Норма ГЭСН-2022 (Приказ 1046/пр) задаёт **количества** ресурсов на единицу работы: трудозатраты
рабочих (чел-ч), время эксплуатации машин (маш-ч) + ОТм машинистов, расход материалов. Цены —
из ФГИС ЦС (по коду ресурса), кроме ОЗП/ОТм (тариф по разряду). `expand_position(code, qty)`
умножает расход на объём позиции → строки ресурсов для [[ALGO-lsr-assembly]].

## Шаги

1. **Каталог** — два источника, объединяются прозрачно (`gesn_service._merged_norms`):
   - **Семя** `config/domain/gesn_seed.yaml`: норма = {code, name, unit, resources:[…]}.
     Ресурс: kind (labor|machinist|machine|material), per_unit, code (для цены ФГИС ЦС),
     price (тариф ОЗП/ОТм; для машин/материалов — опц. снимок цены).
   - **Полная база** — parquet-слой `data/gesn_base/` (десятки тысяч норм, в gitignore как ФГИС ЦС):
     `gesn2022.parquet` + опц. `gesn2022_v2.parquet` поверх (если файл есть — `_default_base_paths`
     грузит оба, v2 дополняет старый слой). При совпадении кода **семя побеждает** (эталон точен).
2. **Разворот** (`expand_position`): qty_строки = per_unit × объём; kind/name/code/price переносятся.
3. **Интеграция**: `lsr_assembly.compute_position` — если у позиции есть `code`, но нет `resources`,
   разворачивает по норме; дальше штатный пайплайн (цены→ОЗП/ЭМ/М→стеснённость→НР/СП→Всего).

## Импорт полной базы ГЭСН-2022

`tools/gesn_import.py` — CLI: выгрузка (xlsx/csv) → нормализованный Parquet (аналог импорта ФГИС ЦС).

    uv run python -m tools.gesn_import IN.xlsx --out data/gesn_base/gesn2022.parquet
    uv run python -m tools.gesn_import IN.csv  --layout flat     # строка=ресурс, явная шапка
    uv run python -m tools.gesn_import IN.xlsx --layout blocks   # норма-блоками (стиль ГРАНД)

Схема Parquet (плоско, строка=ресурс): `norm_code, norm_name, norm_unit, kind, per_unit,
resource_code, resource_name, resource_unit, price`. Сервис группирует по `norm_code`.

**Источник (что реально доступно).** Машиночитаемой бесплатной выгрузки расхода ресурсов ГЭСН-2022
нет: официальный ФСНБ-2022 (fgiscs.minstroyrf.ru) раздаётся **только PDF**; fsnb2022.ru /
cs.smetnoedelo.ru дают **постраничный HTML** на каждую норму (`…/gesn12-01-034-02.html` — таблица
«Затраты труда рабочих/машинистов · Машины · Материалы»), bulk-экспорта нет. Реалистичный
табличный вход — **XLSX-экспорт из ГРАНД-Сметы / коммерческой НСИ** (ресурсная часть построчно).
Импортёр читает его как `flat` (строка=ресурс, явная шапка) или `blocks` (норма-блоками, вид
ресурса — по русской метке категории). Файл-выгрузку предоставляет пользователь.

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
    uv run python -m tools.gesn_bulk_import --sbornik 12 --out data/gesn_base/gesn2022.parquet

    # ПОЛНАЯ база (47 сборников, ~часы — оценка ниже):
    uv run python -m tools.gesn_bulk_import --all --rate 1.0 --out data/gesn_base/gesn2022.parquet

Свойства: **резюмируемость** (уже залитые отделы пропускаются — прогон можно прерывать/продолжать),
rate-limit + retry с backoff, прогресс-лог, идемпотентный append с дедупом по ключу нормы.
**Оценка полного прогона:** ~47 сборников × ~20–40 отделов ≈ **600–900 запросов**; при `--rate 1.0`
(1 req/с) + время скачивания крупных отделов (отдельные ответы до 15 МБ) — порядка **30–90 мин**;
итог — десятки тысяч норм. На проверке: сб.12 = 1536 норм / 27 899 строк-ресурсов; сб.1 (2 отдела)
= 1462 нормы / 6714 строк; эталон 12-01-034-02 в базе точен (труд 12.94, краны 0.97/0.01, бортовой
0.03, гвозди 0.0015, бруски 0.4). Опц. VPS-egress: env `LES_FGIS_VIA_SSH=root@HOST`.

## Точечный overlay ГЭСНм/ГЭСНп

Когда нужна не вся база, а недостающая монтажная семья с правильным типом базы
(`ГЭСНм`, `ГЭСНп`), используется overlay поверх старого parquet:

    uv run python -m tools.gesn_fgis_overlay_import --preset sks \
      --out data/gesn_base/gesn2022_v2.parquet

Инструмент тянет официальный `SearchEstimatedRates` по точным шифрам норм/таблиц,
парсит структурный JSON и сохраняет `base_type`, `norm_key`, `source_doc`,
`source_guid`. Это важно для сборников с одинаковым голым номером: `ГЭСН10`
и `ГЭСНм10` не являются одной базой. Старый широкий bulk остаётся для полного
строительного слоя; overlay — для аккуратной дозаливки конкретных монтажных
разделов без полного реимпорта.

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
Состояние лежит в
`storage/state/smeta_ru_norm_rag_ingest_state.json`, поэтому повторный запуск
пропускает уже обработанные архивы без `--force`.

Структура RAG:

- группа: `TABLE_SMETA`;
- датасеты: `SMETA_RU_NORM_FSNB2022_Index`, `SMETA_RU_NORM_RED2020_Index` и т.д.;
- карточки архива хранят URL, редакцию, issue/date, sha256, инвентарь файлов и
  путь к извлечённым исходникам.

## Где в коде

- Сервис: `proxy/services/gesn_service.py`; каталог: `config/domain/gesn_seed.yaml`.
- Overlay-import: `tools/gesn_fgis_overlay_import.py` (`--preset sks` для СКС/ВОЛС-кандидатов).
- Smetnoedelo API → RAG-карточки: `tools/smetnoedelo_rag_import.py`.
- Smeta.RU ZIP downloader: `tools/smeta_ru_norm_download.py`.
- Smeta.RU ZIP → RAG ingest worker: `tools/smeta_ru_norm_rag_ingest.py`.
- API: `GET /api/lsr/gesn` (список), `GET /api/lsr/gesn/{code}/expand?qty=` (`proxy/routers/lsr.py`).
- MCP: `les_gesn_expand`. Сборка от кода — `POST /api/lsr/assemble` (позиции `{code, qty}`).
- Тест: `tests/test_gesn_service.py` — **gold: сборка от кода эталона = 11813.04**.

## Граница (главное незакрытое)

- **Семя** содержит демо-норму эталона. Полная **база ГЭСН-2022** (десятки тысяч норм) импортируется
  отдельно, как ФГИС ЦС (источник https://fsnb2022.ru/gesn/) — это объём данных, не логики.
- Подбор кода нормы под работу ВОР (наименование→ГЭСН) — отдельный шаг (ретрив по базе ГЭСН).
