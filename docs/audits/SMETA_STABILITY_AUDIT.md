# Аудит сметного контура и план стабилизации

Дата среза: 2026-07-23  
Базовая ветка: `audit/rag-stabilization`, commit `216a353`  
Источник безопасной синхронизации: `proovcme/les_rag`, `main`, commit
`9af71346e72489efb9e8a1ff8fda4ad88986ff56`

## Вердикт

Сметный контур в исходном `public/main` был демонстрационным набором нескольких
legacy-сервисов, а не воспроизводимым smeta-core. Публичные тесты ожидали локальную
базу норм, которой в репозитории нет: baseline-проверка дала `32 failed, 55
passed`. Выборочный перенос нового ядра оказался технически неверным — smeta
зависит от общих contracts, application facade, prompt/skill registry,
document workflow, FGIS/ГЭСН update pipeline, UI/API entrypoints и fixtures.

Поэтому эта ветка является интеграционным слоем public: поверх проверенного RAG
в неё влит весь безопасный tracked source из чистого `private/main`, а не только
папка `proxy/smeta_core`. Не перенесены runtime data, RAG content, базы,
индексы, логи, `.env`, внутренний архив, сетевые инструкции и секреты.
`publication_check` проходит.

Текущий результат:

- 3087 тестов собираются без import errors;
- smeta/ГЭСН/ФГИС профиль: `271 passed, 1 skipped, 17 failed`;
- оставшиеся провалы в основном показывают отсутствие публикуемой test-base и
  расхождение эталона старого расчёта с актуальной ресурсной нормализацией;
- живой Windows/Ollama и реальный ФСНБ-контур не проверялись.

Статус — **полный публикуемый исходный код, но ещё не воспроизводимый stable
smeta runtime**.

### Прогресс 2026-07-23 (clean Windows clone)

- Добавлен `tests/fixtures/smeta/public_base/` + `tools/build_smeta_public_fixture.py`.
- `tests/conftest.py` подключает fixture, если нет runtime `data/smeta_base/les_smeta_base.sqlite`.
- Env-overrides: `LES_SMETA_STRUCTURED_BASE` / `_MANIFEST` / `_INTEGRITY` / `_SOURCE`.
- Эталон семени без runtime ФСЭМ/pricebook зафиксирован как **11813.04**
  (старое 11896.35 — путь с полным ФСЭМ+тарифной книгой).
- Узкий offline suite: **115 passed, 2 skipped**.
- Полный ФСНБ/ФСЭМ runtime и live BAP на моделях <12B ещё впереди.

## Что было в public/main

Сильные стороны:

- чтение XLS/XLSX, импорт смет и ВОР;
- legacy estimate harness, ГЭСН/РИМ и ФГИС pricebook services;
- формирование таблиц и XLSX;
- правило «модель выбирает, код считает» заявлено в README.

Блокеры:

1. Нет `proxy/smeta_core`, application facade, revision store, typed contracts,
   source intake, norm browser и resource normalizer.
2. Нет smeta skill и model-facing договора инструментов.
3. Нет единого tracked trace от исходной строки до выбранной нормы, ресурсов,
   коэффициентов, цен и XLSX.
4. Тесты используют локальную базу `data/smeta_base/les_smeta_base.sqlite`,
   которая правильно не публикуется, но публичной минимальной замены нет.
5. Legacy harness мог возвращать пустой shortlist и массово переводить позиции
   в `rejected_norm`.
6. INSTALL и docs позиционировали public как showcase и ссылались на private
   clone.

## Что перенесено

- `proxy/smeta_core`: contracts, workflow, application facade, revision store,
  validator, calculator, source intake, renderer и resource normalizer.
- Сметные application/chat/agent services и skill contract.
- ГЭСН/ФГИС update pipeline, norm store, artifacts, quantity audit и trace
  schemas.
- API/UI integration, desktop/build/install code и общие сервисы, без которых
  clean clone не собирался бы.
- Каноническая документация, module/code/test maps и version contract.
- Актуальные tests, fixtures и tools, доступные в private git.

## Нерешённые провалы

### Нет публичной минимальной базы норм

Пять norm-store/estimate тестов не находят карточки
`ГЭСНм08-03-575-01` и `ГЭСНм08-02-409-09`. В private git самой SQLite/Parquet
базы нет; она живёт как runtime data. Перенести её из git невозможно.

Нужно собрать маленький лицензированно безопасный fixture-pack из вымышленных
или разрешённых карточек, достаточный для contract tests, и отделить его от
реальной ФСНБ.

### Разошёлся старый стоимостной эталон

Часть legacy tests ожидает `11 896.35`, актуальный код считает `11 813.04` и
явно сообщает неполную детализацию ОТм из-за отсутствующего machine mapping.
Эталон нельзя просто переписать под зелёный тест: сначала нужен независимый
разбор нормы, ФСЭМ mapping и формул НР/СП.

### Не опубликован полный demo workflow

Код и тесты теперь доступны, но fresh clone не может пройти end-to-end
`ВОР → выбранная моделью норма → ресурсы → цены → ЛСР` без разрешённой test-base,
provider setup и Qdrant demo generation.

## Определение stable

Сметный контур стабилен, когда:

- модель сама ищет, открывает и выбирает норму/аналог; код не подменяет выбор;
- первичная mapping revision immutable, любые изменения — новой ревизией;
- quantity/unit/provenance gates не позволяют pricing при конфликте;
- ресурсы и коэффициенты возвращаются модели на подтверждение;
- отсутствующая цена остаётся gap/КАЦ, а не нулём;
- основной XLSX строится из последней завершённой модельной ревизии;
- clean public clone проходит offline contract suite без private runtime data;
- Windows/Ollama и облачный provider проходят одинаковый release baseline;
- на BAP/контрольном наборе нет регрессии выбора, покрытия и трассы.

## План до стабильного

### P0 — воспроизводимый public fixture и зелёный offline gate

1. Создать `tests/fixtures/smeta/public_base/` с минимальными norm/resource
   records и manifest/integrity contract.
2. Переключать тесты на fixture только при `PYTEST_CURRENT_TEST`; production
   всегда требует verified active base.
3. Независимо разобрать расхождение `11 896.35`/`11 813.04` и зафиксировать
   профессионально подтверждённый эталон.
4. Добавить CI: collect-only, smeta contract suite, `publication_check`.

Критерий выхода: профиль даёт 0 failed на clean clone без `data/`.

### P1 — единый пользовательский workflow

1. Провести все smeta entrypoints только через application facade.
2. Закрепить один model turn / tool session и прозрачный trace в UI.
3. Доделать документный intake: просмотр исходной строки, источника количества,
   выбранной нормы, resources/НР/СП/цен и blockers.
4. Добавить resumable state для длинной локальной модели.

Критерий выхода: один и тот же ВОР даёт одинаковую immutable trace на локальном
и облачном provider; различается только модельное решение, а не арифметика.

### P2 — профессиональная приёмка

1. Прогнать BAP baseline и расширенный набор ВОР/спецификаций.
2. Ввести метрики exact/close analog, unit conflicts, coverage, price gaps,
   human overrides и artifact fidelity.
3. Провести ручной сметный review спорных аналогов и ресурсов.
4. Зафиксировать Windows release smoke и rollback.

Критерий выхода: согласованный baseline проходит три раза подряд, а все
изменения решения модели видны ревизиями.

## Риски и границы

- Ветка большая намеренно: выборочный перенос оставлял import-broken public.
- Она должна вливаться после RAG-ветки.
- Runtime data и лицензируемая ФСНБ не публикуются; нужен отдельный безопасный
  test fixture.
- Версия уже синхронизирована с чистым private source, но релизом ветка станет
  только после зелёного public gate и пользовательского merge.
