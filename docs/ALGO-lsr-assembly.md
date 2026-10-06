# Алгоритм: движок сборки ЛСР (позиция → ресурсы → цены → НР/СП → Всего)

##906: machine-derived operator labour with source reconciliation

FSEM machine crew hours and source tariff codes compute machinist labour as
machine quantity x crew hours x hourly tariff, using raw Decimal quantities without
blanket rounding/scaling or a fitted tolerance. Anonymous unpriced labour aggregates
are retained in audit and never double charged. Existing explicit machinists/prices
are preserved; unknown/invalid mapping stays unresolved. If derived hours differ
from the norm aggregate, priced components are preliminary and the position keeps
fsem_aggregate_discrepancy / needs_fsem_resolution. The source/edition discrepancy
is not repaired by entering a price and never yields false confirmed readiness.
Regression fixture0.02+0.002machine hours yields0.022derived crew hours, while the
source aggregate0.02 remains an explicit reconciliation blocker. 172 focused PASS.
Primary basis:421/pr amended55/pr, paragraph80 formula1.2;916/pr paragraphs78-79.
577/pr Appendix15 is not a blanket licence to round imported resource quantities.
No normative data, authored choices, provider, dependencies or runtime factors changed.

## 890 — полное включение работы в другую работу

`covered_by_work_id` — необязательное решение модели: точный source_row другой
работы, R# относительно своего листа или существующий operation_id. Нужны
пояснение coverage, разрешаемые evidence_refs и исходный объём. Две строки с
одинаковой нормой остаются двумя начислениями без явного решения модели.
`resolve_work_coverage` проверяет уникальность адресата, роли и отсутствие циклов;
расчёт дополнительно проверяет основание, источник и возможность расчёта адресата.
Неверная связь даёт coverage_conflict и не подменяется самостоятельным начислением.
Частичное пересечение требует авторского разделения операций/объёмов.

Валидная covered-строка не создаёт позицию и отдельную сумму; сохраняет свой
source_row и authored fields, ссылается на корневую billed operation и наследует
её readiness, в том числе пробелы цен/применимости. Счётчики covered_rows и
positions_built разделены. Основной лист сохраняет строку с исходным объёмом
и пометкой «повторно не начисляется»; лист «Проверка» — основание и связь.
Raw row без расчётной проекции не может скрыть вопрос о норме в readiness.
Перенос поддержан одинаково для JSON/Markdown/подписанного текста и durable draft.

## 889 — рассчитанные значения в экспортируемом XLSX

`rim_trace_xlsx_service._set_formula` сохраняет числовое значение из готовой
расчётной трассы перед назначением редактируемой формулы. `_save_calculated_workbook`
пишет его в OOXML `<v>` только той же formula-cell основного листа, сохраняя `<f>`
и остальные части книги. Никакой второй сметный расчёт или выполнение формул не
вводится. Неизвестные цены не заменяются нулём. После ручных изменений Excel
пересчитывает книгу (`auto`, `fullCalcOnLoad`, `forceFullCalc`). Доступны значения
ресурсов, позиций, разделов и свода без Excel: проверено `data_only=True`.

В live888 XLSX имел226 формул без кэша. Независимый ограниченный арифметический
разбор дал274783,91 — ту же предварительную сумму, что API. Дефект касался выдачи
уже рассчитанных чисел в просмотрщики, а не правильности модельных норм/состава.

864: активный RIM переносит literal `resource_bindings`/`resource_review` через
`model_resource_binding_service`, не через исторический workflow. Действия
add/replace/exclude/reuse имеют точную цель, основание и independent citations;
невалидная замена не удаляет исходный ресурс. Количество хранится как физическое
и переводится в расход на расчётную единицу один раз. Reuse сохраняет количество,
но учитывает авторское повторное использование по нулю, поверх цены книги.
Явные действия, причины, ссылки и конфликты видны в XLSX «Проверка».
Отдельная поставка не исключает все материалы нормы: сохраняется состав,
возможное неразрешённое пересечение блокирует полную готовность. Выбор нормы
и профессиональные решения остаются авторскими; цифры без происхождения не закрывают gaps.

Build 749: relative `work_row=R4` resolves against the source sheet, never
against a norm code or an arbitrary sheet. Unknown source locators remain
in the raw answer, but are not accepted workbook decisions. Packet sizes
reserve 400 output tokens for headers/prose and 250 per decision row;
structural coverage gaps remain pending for continuation. This does not
verify, replace or choose model norms. FreeToken capacity remains observed,
not increased from the model name alone.

Связывает кирпичи сметного ценообразования в сборку **позиция-к-позиции**. 0 LLM (ADR-11).
Финальная веха ценообразования: всё построенное сходится в один конвейер.

## Конвейер

```
объём (ВОР) → ресурсы позиции → цены (ФГИС ЦС lookup / КАЦ) →
  ОЗП / ЭМ(машины+ОТм) / М → коэф. стеснённости → НР / СП → Всего по позиции → свод в ЛСР
```

## Бухгалтерия позиции (выверена на Эталон_кровля, поз.1)

Эталоном до сборки 830 называли сумму 11 813,04 — её печатало демо-семя
`config/domain/gesn_seed.yaml` (замер и разбор — `stage_b/live_830/seed_vs_base_reconcile_830.md`,
запрет закреплён `tests/test_gesn_seed_is_test_only_830.py`).  Ниже — та же позиция на карточке
проверенной базы `data/smeta_base/les_smeta_base.sqlite` (объём 0,61 по карточке «на 100 м2») и
ценниках книги `sankt-peterburg_2kv2026`; замер — `stage_b/live_830/gold_rebaseline_830.json`.

| Величина | Формула | Эталон |
|---|---|---|
| ОЗП | Σ labor | 4006.37 |
| ЗПМ | Σ machinist (ОТм, ФСЭМ) | 490.00 |
| ЭМ | машины (640.59) + ЗПМ | 1130.59 |
| М | Σ material (гвозди; бруски — пробел цены) | 78.47 |
| Прямые | ОЗП + ЭМ + М | 5215.43 |
| ФОТ | ОЗП + ЗПМ | 4496.37 |
| НР | ФОТ × нр% (109) | 4901.04 |
| СП | ФОТ × сп% (57) | 2562.93 |
| **Известная стоимость позиции** | Прямые + НР + СП | **12679.40** |

Одна позиция не получает «Всего по позиции»: не закрыт ресурс `11.1.03.01-0076`
(`price_missing`), поэтому статус — `priced_partial`, а не `priced_final`.  Подпись строки
взята у формы (`rim_lsr_trace_service.position_total_label`) и та же в чате: один и тот же
числовой результат нигде не называется итогом, пока есть незакрытое основание.

## Шаги

1. **Ресурсы → цены** (`compute_position`): для каждой строки ресурса цена = явная `price`, иначе
   `code`→ФГИС ЦС (`fgis_price_service.lookup`), иначе material→КАЦ по наименованию; нет цены → флаг.
   Стоимость = qty × price.
2. **Агрегация по видам** (`kind`): labor→ОЗП, machinist→ЗПМ, machine→машины, material→М; ЭМ=машины+ЗПМ.
3. **Стеснённость + НР/СП** (делегирует `stesnennost_service.apply_position`): при k≠1 берётся
   скорректированное «Всего», иначе базовое. См. [[ALGO-stesnennost]].
4. **Свод** (`assemble`): по разделам + итог ЛСР (base_total / total / stesnennost_uplift) + флаги
   позиций без цены (кандидаты на КАЦ).

## РИМ-трасса граф 2-12

`rim_lsr_trace_service.build_position_trace` — отдельный evidence-слой для Приложения № 3 к Методике
421/пр (форма ЛСР РИМ). Он не заменяет `lsr_assembly_service`, а раскладывает одну позицию в проверяемые
строки: работа, коэффициент, ОТ(ЗТ), машины, ОТм(ЗТм), материалы, прямые, ФОТ, НР, СП, итог. Для ФГИС
ЦС сохраняет происхождение цены: текущая цена (графа 10) или базовая цена × индекс (графы 8-10).

`build_lsr_trace(positions)` — **многопозиционная** трасса: каждая позиция через тот же
`build_position_trace` (числа те же — gold сохраняется), группировка по разделам (поле `section`,
порядок первого появления), свод = Σ позиций (прямые/ФОТ/НР/СП/Всего + нормативные чел.-ч рабочих/
машинистов для шапки). Рендер — `rim_trace_xlsx_service` (форма Приложения № 3): одна позиция —
`render_trace_xlsx`; смета — `render_lsr_xlsx` (шапка с общим итогом + разделы с заголовком и «Итого
по разделу N» + «ВСЕГО по смете»). Числа не пересчитываются (рендер ГОТОВОЙ трассы, 0 LLM).

`build_lsr_trace_from_visible_rows(rows)` — мост из уже выбранных/видимых строк ЛСР/ВОР в трассу.
Он не ищет и не выбирает норму: строка должна содержать `basis`/`code` с шифром. Код только
нормализует шифр, переводит физическое количество в измеритель нормы (`61 м2` при норме `100 м2`
→ `0.61`), раскрывает ресурсы, ищет цены и возвращает `row_bindings`. Operator `confirmed_data`
применяется до этого расчёта и не подменяет `norm_code`. Контракт `build_lsr_workbook` принимает
это поле; отсутствие его в schema давало `TOOL_SCHEMA_INVALID` на сохранённых строках. В активном ADR-15 пути
независимый `EXACT_VERIFIED` не требуется: явный шифр терминального результата модели идёт в
exact lookup. `MISSING`/`CONFLICT`, неизвестный шифр, отсутствие цитированной
конверсии единиц или отсутствие цены не попадают в `priced_final` и остаются
видимыми gaps. Названный `NEEDS_RESEARCH` считается, если карточка есть в базе,
остаётся аналогом на «Проверке» и не делает `priced_final`. Выбранный шифр при
этом не превращается в `MISSING`.
С 845 явные match facts модели проверяются также для EXACT/EXACT_VERIFIED:
неизвестное/отрицательное совпадение нельзя подтвердить одним статусом или
ссылкой на правильный шифр. Общий gap exact_match_unresolved используется
readiness и денежной трассой; решение/код нормы/flags не переписываются.
Legacy rows без блока match facts сохраняют прежний citation contract.
Исходное `quantity` хранится отдельно от расчётного; фасовка/длина/масса на метр
принимаются только с `conversion_source`. Ресурсы связываются по `work_row`,
а не только по шифру. `pricing_block_reason`
используется только изолированным `QUALITY_DIAGNOSTIC`, не workbook adapter.

С 848 физический объём учитывает множитель исходной единицы перед делением
на измеритель нормы: `61 м²`, `0.61 × 100 м²` и `0.061 × 1000 м²` дают одну
сумму, без повторного деления на 100. Множитель сохраняется в quantity trace;
явный цитированный conversion_factor/calc_quantity сохраняет прежнюю семантику.
Переполнение — needs_input, а не бесконечная сумма. Catalog, adapter и money trace
проверяют равные меры по подтверждённым колонкам единицы и количества. Единица
не подтверждается буквой из названия работы; масса соседней колонки не является
объёмом. Допускаются только формы записи той же единицы, без шт↔комплект/порт.
Новая арифметика применяется к новым расчётам; старые ревизии остаются неизменными.

Если `book` не передан, все LSR/API пути используют единый `fgis_price_service.resolve_pricebook_path()`:
`LES_DEFAULT_PRICEBOOK` → `spb_2kv2026`/`sankt-peterburg_2kv2026` → доступные книги 2026 → первая
обычная книга. Scratch-файлы (`*_refresh`, например `spb_refresh`) не становятся дефолтом и не
показываются как обычные книги; их можно использовать только явным именем для диагностики/добора.

## Индекс ГЭСН/ГЭСНм

Ключ нормы в parquet — не голый номер `38-01-001-01`, а `norm_key = <base_type>:<код>`, например
`ГЭСН:38-01-001-01` и `ГЭСНм:38-01-001-01`. Это обязательный invariant: строительные, монтажные,
пусконаладочные и ремонтные сборники могут иметь одинаковые номера таблиц, но разные ресурсы.

Для FGIS SearchEstimatedRates возможны несколько опубликованных версий одной таблицы. Парсер берёт
актуальную версию по максимальному `id` внутри одинаковых `(documentTypeName, documentName)`, иначе
одна норма получает дубли ресурсов из старой и новой публикации.

Тарифные коды труда вида `1-100-40` сохраняются как `resource_code` и ценятся по Сплит-форме ФГИС ЦС.
Агрегированная строка `Затраты труда машинистов` без разряда/кода раскладывается только если машины
позиции полностью покрываются явным маппингом машина→машинист, а сумма машино-часов совпадает с
агрегатом ОТм. Если покрытие неполное — строка остаётся `missing`, без молчаливой подстановки.

Текущий минимальный маппинг нужен для проверенного кейса столпа: `91.05.05-015` → `4-100-060`
(машинист 6,0), `91.14.02-001/002` → `4-100-040` (машинист 4,0). Расширять его нужно только по
ФСЭМ/официальному источнику, а не по догадке модели.

## Где в коде

- Сервис: `proxy/services/lsr_assembly_service.py` (переиспользует `stesnennost`/`fgis_price`/`kac`).
- РИМ-трасса: `proxy/services/rim_lsr_trace_service.py` (`build_position_trace` — позиция, графы 2-12;
  `build_lsr_trace` — смета: разделы + итоги разделов + общий свод;
  `build_lsr_trace_from_visible_rows` — выбранные строки ЛСР/ВОР → `priced_partial` trace).
- Рендер формы ЛСР РИМ Приложения №3: `proxy/services/rim_trace_xlsx_service.py` (`render_trace_xlsx` — позиция;
  `render_lsr_xlsx` — многопозиционная смета).
- API: `POST /api/lsr/assemble`; `POST /api/lsr/rim-trace[/export]` (позиция);
  `POST /api/lsr/lsr-trace[/export]` (смета → XLSX-форма);
  `POST /api/lsr/lsr-trace/from-rows[/export]` (видимые строки с выбранными шифрами → trace)
  (`proxy/routers/lsr.py`).
- GUI: «Инструменты» → карточка «Сборка ЛСР» (позиции JSON + книга/условие → свод по разделам).
- MCP: `les_lsr_assemble`.
- Тесты: `tests/test_rim_lsr_trace_service.py` — **эталон позиции 12679.40 (`priced_partial`,
  дыра `11.1.03.01-0076`), смета 2× = 25358.80**; карточка берётся из основной базы, ставки книги
  `sankt-peterburg_2kv2026` зафиксированы в самом тесте (`GOLD_PRICES`), поэтому сумма не зависит от
  установленной книги (`tests/test_pricebook_hermeticity_830.py`).  Арифметика движка сборки —
  `tests/test_lsr_assembly_service.py` (итоки на ставках, которые тест пишет сам: позиция 16628.00,
  свод 2× = 33256.00) и `tests/test_gesn_service.py` (сборка от кода карточки базы через книгу теста:
  18535.77).  Рендер формы — `tests/test_rim_trace_xlsx.py`.

## Граница (что осталось)

- Рендер в форму Приложения № 3 (одна позиция + многопозиционная смета: разделы + итоги разделов +
  «ВСЕГО по смете») — **готов**. Осталась полная GRAND-фиделити (179 кол., НР/СП с типом работ в
  графах), реальные метаданные шапки и вызов формы прямо из чата (сейчас — через API-эндпоинт).
- ФСЭМ-связка «машина → машинист» пока частичная; для новых машин без маппинга ЛСР честно вернёт
  `needs_price`, пока не загружен официальный справочник.
