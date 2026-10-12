# Алгоритм: Спецификация (форма 9, ГОСТ 21.110) → ВОР

## Кандидат928 — сохранение входных строк и авторских решений

Литеральный каталог сохраняет строки таблицы с Name/Unit/Quantity даже при
пустом объёме или формуле без cached result как ambiguous. Код не вычисляет
формулу и не назначает работе роль/объём. CSV/DOCX/RTF используют тот же
model-authored workbook boundary. PDF Markdown учитывает escaped delimiters.

`bor_service` сохраняет полный авторский JSON, включая операции, coverage,
ресурсы и перевод единиц, на листе «Решения модели». Длинный JSON разбивается
на фрагменты без обрезания. Повторный intake признаёт audit только при точной
схеме, физических main locators, последовательных уникальных фрагментах и
валидном JSON-объекте; иначе возвращает явный vor_model_audit_invalid.
Audit не добавляется к числу исходных работ. Ни норма, ни родитель, ни объём
кодом не создаются. ZIP и комплект нескольких вложений этой правкой не
поддерживаются. Профессиональная приёмка разных входных документов открыта.

## Candidate911: exact clean Windows dependencies

Candidate911 clean Windows packaging now allowlists the exact RTF reader
`tools/windows_rtf_extract.ps1` and classic Outlook setup dependencies
`clients/outlook_mail_poller/setup_task.ps1` / `LesMailPoller.cs`. Broad tools/client
trees remain excluded. Clean staging tests prove included bytes and the real file
iterator; they do not establish exact installer, Outlook COM or document-quality
acceptance. Installed EXE remains the separately measured5.1.813 until a new
installer is actually built and tested.

Earlier entries retain their stated build/date scope.

##909 — partial model-authored VOR

A late technical failure may deliver only previously saved model-authored rows when the model
unambiguously declared VOR. Draft/technical error/remaining source information are document-level
facts; code does not correct decisions or infer missing operations, quantities, norms or parents.
No-search VOR remains model-declared and skips retrieval. Complete VOR behavior is unchanged.
Installed diverse-document and professional acceptance are pending; customer-ready false.

Earlier entries record evidence at their stated build/date.

##908 — literal RTF intake

Strict lexical admission precedes hidden bounded native rendering; no model or OCR is called by the reader.
Verified boundaries expose literal cells; unverified tabs remain ambiguous native text, with no inferred quantity.
rtf_native_text_char_offsets label offsets in the exact native text. Warnings/source completeness remain explicit
in upload/catalog/readers/frame/VOR output and raw/replayed delivery status. Authored decisions remain model-owned.
OS reader unavailability/malformed input/source changes are visible failures; native success is not whole-source proof.

Earlier entries record evidence at their stated build/date.

## Текущий чатовый workbook-путь (candidate 859, установлен 858)

Если модель уже вернула `decisions`, XLSX/XLSM, PDF, DOCX и CSV упаковываются из них.
Исходная спецификация не заменяет выбранные операции; словарь ниже не создаёт
операцию вместо модели. В ВОР сохраняются row_role, work_row, open_gap, авторские
количества и единицы. Проверка каталога охватывает также материалы: несовпадение
объёма/единицы или отсутствие исходной строки печатается в примечаниях и readiness;
файл доступен как черновик, никакой исправленный объём код не подставляет.
Заголовки не требуют количества или нормы. Сомнения и вопросы модели остаются
в XLSX; готовность файла не означает профессиональную полноту ВОР.

Каталог исходника сохраняет длинные ячейки без preview cap, нулевые значения
и физические пустые колонки. PDF conversion для каталога вызывается с
`apply_char_limit=False`; UI preview cap остаётся прежним. Все XLSX листы,
включая hidden, сохраняют исходные адреса. CSV сохраняет физический номер строки.
DOCX reader использует существующий python-docx: body text, таблицы, вложенные
таблицы и header/footer получают стабильные `DOCX_Tn!Rk`/text locators.
Параграф без tabular role остаётся ambiguous до решения модели; код не
превращает его в монтаж. Notes-only листы и DOCX context доходят в packet как
reference_only_source_rows без расширения requested locators.

Неизвлечённые изображения, textboxes, embedded/tracked content и footnotes
обозначаются extraction warnings и `source_extraction_incomplete`; это честная
граница literal text/table extraction, не утверждение о содержимом картинки.
Проверка сохраняется и для header-only authored результата, и в readiness/XLSX.
Пустой набор authored/source строк даёт `NO_SOURCE_ROWS` до записи artifact;
quantity=0 сохраняется как исходное значение.
RTF/ZIP остаются неподдерживаемыми форматами этого workbook-пути. OCR scan
не объявляется полностью извлечённым только потому, что создан файл.
Живая приёмка candidate 859 остаётся открытой.

**Отдельный legacy path без модельных решений:**

`build_vor_workbook` читает все листы XLSX с распознанной колонкой наименования, сохраняя адрес `Лист!Rномер` и исходный порядок. Формула объёма без сохранённого вычисленного значения остаётся пустой и получает явный блокер `quantity_formula_without_cached_value` в результате и пометку в XLSX; Python не вычисляет формулы Excel. Для PDF строки должны быть представлены решением модели. Этот путь создаёт проверяемый черновик ВОР, а не гарантирует профессиональную декомпозицию произвольной спецификации; неоднозначные операции требуют решения инженера.

Детерминированное преобразование **спецификации оборудования/изделий/материалов**
(форма 9 ГОСТ 21.110) в **ведомость объёмов работ (ВОР)**. Ноль LLM (ADR-11):
алгоритм + словарь категорий. LLM — последний инструмент ([[llm-minimalism-principle]]).

## Идея

Спецификация перечисляет **что** смонтировать и **сколько** (позиция, наименование,
тип/марка, ед.изм., количество). ВОР перечисляет **какие работы** и в **каком объёме**.
Объём монтажной работы пропорционален количеству оборудования/материала, поэтому:

> одна позиция спецификации → одна строка работы; **объём работы = количество из
> спецификации**; **глагол работы** выбирается по категории предмета.

## Шаги

1. **Источник.** Берём строки `doc_type ∈ {SPEC, VEDOMOST}` из Parquet датасета
   (нормализованный табличный конвейер). Поля: `name`, `unit`, `qty`, `code`, `mark`, `section`.
2. **Фильтр шума.** Отбрасываем заголовки секций и нечисловой мусор (как в сверке).
3. **Количество.** qty-приоритет (`qty`), затем data-aware fallback по полям объёма.
4. **Категория → глагол работы** (словарь, по ключевым словам наименования + единице):
   | Категория (ключевые слова) | Глагол | Типичная ед. |
   |---|---|---|
   | кабель, провод, шнур | **Прокладка** | м |
   | лоток, короб, труба, гофра, канал, стойка, полка, подвес | **Монтаж** | м/шт |
   | коробка, клемма, наконечник, крепёж, дюбель, хомут, скоба, зажим, закладная | **Установка** | шт |
   | светильник, прожектор, щит, шкаф, бокс, розетка, выключатель, датчик, извещатель, прибор, блок, автомат, трансформатор, привод, двигатель, насос, вентилятор, агрегат | **Монтаж** | шт/компл |
   | *(по умолчанию)* | **Монтаж** | — |
5. **Строка работы.** `Наименование работы = "{Глагол}: {наименование позиции}"`
   (форма с двоеточием — без падежного согласования). Ед. и кол-во переносятся 1:1.
   `code`/`mark`/`section` сохраняются для трассировки к спецификации.
6. **Свод.** Одинаковые работы (по разделу × наименованию работы × ед.) суммируются —
   как в `bor_service`. Позиции без количества помечаются (`qty_missing_rows`).
7. **Экспорт.** JSON-превью + xlsx (та же стилистика, что у ВОР-свода).

## Где в коде

- Сервис: `proxy/services/spec_to_bor_service.py` (без LLM).
- Канонический workbook tool использует `bor_service.source_rows_to_vor_xlsx`:
  это отдельный lossless-экспорт без свода — порядок, единицы, количества и
  `source_file#position` переносятся 1:1, пустые значения остаются пустыми.
- Активный чатовый `build_vor_workbook` сохраняет authored decisions через
  `workbook_tool_service` → `source_rows_to_vor_xlsx`, сверяя literal
  `attachment_source_catalog_service`; `rows_from_spec_xlsx` применяется только
  к отдельному legacy пути без decisions. MCP сохраняет отдельные
  `les_bor`/`les_spec_to_bor`. Старый `/api/bor` удалён в 0.30.21.

## v2 — декомпозиция (методика ГОСТ 21.111, дефолт)

`generate_spec_bor(..., decompose=True)` — методически правильная ВОР: **позиция → НАБОР работ**
(не «1 к 1»), графы как в ГОСТ 21.111. Словарь `_DECOMPOSE`: категория → перечень работ.
**Все под-работы наследуют ЕД.+КОЛ-ВО позиции** (объём один и тот же — линейный/поштучный),
поэтому чисел не выдумываем (ADR-11). Работы по числу концов (маркировка, расключение) в
авто-объём НЕ попадают — отмечаются в примечании.

| Категория | Работы (декомпозиция) |
|---|---|
| кабель/провод/шнур | Разметка трассы · Прокладка кабеля (+примечание: маркировка/расключение по концам) |
| лоток/короб/труба/гофра | Разметка трассы · Монтаж {предмет} |
| стойка/полка/подвес/закладн | Монтаж {предмет} |
| коробка/клемма/крепёж | Установка {предмет} |
| прибор/щит/датчик/оповещатель/… | Установка {предмет} · Подключение |

Вывод: `WorkLine` (раздел/работа/ед/кол-во/**чертёж**/**примечание**), группировка по разделам,
свод одинаковых (раздел×работа×ед → SUM). xlsx `work_lines_to_xlsx` — графы
**№ · Наименование работ · Ед.изм · Кол-во · Ссылка на чертёж · Примечание**, разделители разделов.

## v1 — простой режим (`decompose=False`)

«1 позиция → 1 монтажная работа» (глагол по `_WORK_RULES`, форма «Глагол: Наименование»). Оставлен
для укрупнённой оценки.

## Границы

- ВОР ≠ смета: расценки **не** добавляются (это ЛС).
- Словарь декомпозиции покрывает ЭОМ/слаботочку в первую очередь; расширяется правкой `_DECOMPOSE`
  (новая категория = одна строка, не код). Падежи не согласуем (форма «Работа: Предмет»).
- Объёмы под-работ = кол-ву позиции; работы с иной размерностью (по концам/узлам) — вручную.
