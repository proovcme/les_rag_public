# ALGO-glorax-checklist-review — RAG-led проверка ПД/РД по чек-листам Glorax

Рабочая спецификация. Перенесена на актуальное ядро LES 2026-07-14.

## Назначение

Модуль реализует **чек-лист входного контроля ГИПа БУП (Glorax)** не как отдельный
rule-engine, а как **generic-профиль `checklist-review` поверх doc_review_service**
и уже работающих слоёв LES (`normcontrol_service`, `retrieval_service`, `evidence_contract`).
Архитектура и полное обоснование — [implementation_plan.md](../implementation_plan.md);
исходный канон задачи — [CHECKLIST_REVIEW_PD_TASK.md](CHECKLIST_REVIEW_PD_TASK.md) (2026-06-26).

Инвариант (AGENTS.md, ADR-11): чек-лист задаёт вопрос → RAG ищет evidence → код проверяет
формализуемое → LLM связывает и объясняет → инженер принимает решение. Уверенный `yes/no`
без `source_ref` — архитектурный регресс.

## Эталонные счётчики (снапшот-спайк T0.1/T0.2, после решения оператора 2026-07-04)

Источник: `tools/checklist_snapshot_spike.py` → `docs/checklist_review/SNAPSHOT_PD.md` /
`SNAPSHOT_RD.md`. Правило классификации закрыто решением оператора 2026-07-04 (см. ниже) —
секция «Спорные строки» в обоих снапшотах пуста.

### ПД (`Чек_лист_входного_контроля_ПД_ГИПы_БУП.xlsx`, 10 содержательных листов)

| Лист | Критериев | Заголовков блоков (с заливкой) | Заголовков блоков (без заливки) | Заголовков раздела |
|---|---|---|---|---|
| Общее | 5 | 0 | 0 | 0 |
| СПОЗУ | 17 | 4 | 1 | 1 |
| АР | 66 | 14 | 0 | 1 |
| КР | 31 | 6 | 1 | 1 |
| ЭОМ | 26 | 6 | 0 | 2 |
| ЭН | 11 | 0 | 0 | 3 |
| ВК и НВК | 49 | 8 | 0 | 3 |
| ОВиК | 59 | 10 | 0 | 5 |
| СС | 47 | 11 | 0 | 1 |
| ПБ2 (АППЗ) | 24 | 4 | 0 | 1 |
| **ИТОГО** | **335** | **63** | **2** | **18** |

Заголовков блоков всего (с заливкой + без): **65**.

### РД (`Чек_лист_входного_контроля_РД_ГИПы_БУП.xlsx`, 26 содержательных листов, итог)

| Метрика | Значение |
|---|---|
| Критериев всего | **692** |
| Заголовков блоков с заливкой | 75 |
| Заголовков блоков без заливки | 26 |
| Заголовков блоков всего | **101** |
| Заголовков раздела верхнего уровня | 0 |

По листам — см. полную таблицу в `docs/checklist_review/SNAPSHOT_RD.md`. Характерный пример
заголовка блока без заливки на каждом РД-листе: `"Том РД соответствует требованиям
ГОСТ Р 21.101-2020:"` (напр. АР:4) — answer-ячейка C4 не покрыта DV (DV на листе начинается
с C5), строка группирует подпункты 1.1.1–1.1.5 (общие данные/содержание/ведомости), сама
критерием не является.

### Правило классификации строки (решение оператора 2026-07-04)

```
заголовок блока = ячейка B имеет заливку FF3200F0 (приоритетный признак, T1.3)
                  ИЛИ (B непустая И DV на C нет)
критерий        = ячейка B непустая  И  answer-ячейка C покрыта data validation
                  И заливки FF3200F0 нет
заголовок раздела = ячейка B пустая, A содержит текст (напр. "ИСХОДНАЯ ДОКУМЕНТАЦИЯ")
```

Уточнение T1.3 (2026-07-04): в реальном ПД-файле две строки (`ОВиК:15`, `ОВиК:18`)
имеют одновременно заливку заголовка блока и артефактную пустую DV-разметку на C
(протянутое форматирование Excel). Заливка `FF3200F0` решает конфликт в пользу
заголовка — закреплено в `checklist_template_importer._has_block_header_fill`
и тестом `test_checklist_template_importer_fill_wins_over_dv_conflict`.

Прежнее вспомогательное правило «номер `N`/`N.M` в колонке A без DV = критерий» **убрано**:
строки, ранее считавшиеся «спорными» (СПОЗУ:6 «Отчёт об инженерно-геодезических изысканиях»,
КР:7 «Отчёт об инженерно-геологических изысканиях» и аналогичные), — это заголовки блоков,
не критерии. DV-покрытие answer-ячейки — решающий признак критерия при отсутствии заливки
заголовка; заливка `FF3200F0` приоритетна при конфликте признаков (см. уточнение T1.3 выше).

Historical note: до решения оператора ПД давал 337 критериев + 63 заголовка (сумма 400,
совпадала с ранней оценкой «~400» из CHECKLIST_REVIEW_PD_TASK.md); после решения —
335 критериев + 65 заголовков (та же сумма 400, но 2 строки переклассифицированы из
критериев в заголовки). Число «533» из самой ранней разведки остаётся историческим
ориентиром (переучёт непустых B без какой-либо классификации), не источником истины.
Точное число для importer фиксирует Phase 1 снапшот-тестом на живом XLSX, а не этот спайк.

## Классы критериев (`kind`) — по одному примеру на класс

| kind | Смысл | Пример (лист:строка, дословно) |
|---|---|---|
| `presence` | наличие документа/раздела/расчёта как артефакта | Общее:3 «Приложен отчет об инженерно-геологических изысканиях» |
| `calculation` | наличие расчёта + evidence его результата (без пересчёта по существу) | АР:13 «Теплотехнический расчет» |
| `parametric` | значение находит retrieval/таблица, порог сравнивает код | КР:20 «Марка бетона соответствует требованиям по водонепроницаемости для ростверка» (W12) |
| `cross_section` | сверка между разделами/документами, two-sided evidence | СПОЗУ:10 «Соответствие пирогов благоустройства ТЗ и техническому стандарту Glorax» |
| `spatial_visual` | пространственная/визуальная проверка, честная граница (v1 = manual_required + подсказки) | АР:49 «Расположение корзин для кондиционеров» |
| `spds_formal` | СПДС-оформление, ссылается на уже посчитанные NK-01..04/D2-D4 | РД АР:5 «Общие данные комплекта приложены» (подпункт 1.1.1 под заголовком АР:4) |
| `manual_required` | пункт требует инженерного решения, не формализуется | СПОЗУ:13 «Соответствие элементов благоустройства концепции» |

`kind` не является вердиктом — он отвечает только на вопрос, какой evidence нужен и каким
способом его искать (CHECKLIST_REVIEW_PD_TASK.md §3). Итоговая классификация каждого item —
эвристика на импорте + ручная правка инженера в template (Phase 1, T1.4).

## Интерфейсы к существующему коду

Модуль **переиспользует**, не дублирует:

- **Статусы item** — `proxy/services/doc_review_service.py:23-28`, тот же enum:
  `computed_issue` (S_COMPUTED_ISSUE) · `supported_by_evidence` (S_SUPPORTED) ·
  `not_applicable` (S_NOT_APPLICABLE) · `manual_required` (S_MANUAL) ·
  `review_needed` (S_REVIEW_NEEDED). `human_decision` у каждого item = `unset` по умолчанию —
  финальный статус ставит инженер, не движок.
- **Связи `ChecklistReviewItem`** (канон §5, implementation_plan.md §4) — `doc_review_item_ids`
  (ссылка на items `doc_review_service`/rulepack `gost_r_21_101_2026`), `formal_check_ids`
  (ссылка на NK-01..04 из `normcontrol_service.py`), `normalized_remark_ids` (ссылка на
  `normalized_remark_v1`, category=`checklist`).
- **`normalized_remark_v1`** (CHECKLIST_REVIEW_PD_TASK.md §4) — единый выход замечания:
  `id, severity, category, location, description, normative_ref, document_evidence,
  checklist_ref, recommendation, human_decision`. Общий формат для checklist/formal/
  normative/consistency замечаний — не изобретаем новый.
- **`defense_contract_v1`** (`proxy/services/evidence_contract.py`) — `EvidenceItem`
  (RETRIEVED/COMPUTED/ASSUMED/MISSING/BLOCKED), `DefenseClaim`, `DefensePack`. Инвариант уже
  в коде: RETRIEVED обязан иметь `source_ref`.
- **Persist-паттерн `human_decisions.json`** — `proxy/routers/doc_review.py:59-76` →
  `storage/doc_review/{dataset_id}/human_decisions.json`
  (`doc_review_human_decisions_v1`). Checklist-review копирует sidecar-паттерн в
  `storage/checklist_review/{dataset_id}/{run_id}/…`.

## Жёсткие правила (переносятся в safety-тесты, Phase 4)

1. `suggested_answer ∈ {yes,no}` **запрещён** без непустого `document_evidence[].source_ref`.
2. Presence подтверждается **содержимым**, не именем файла: evidence обязан иметь
   snippet/лексический якорь из тела документа; filename-match без контентного хита →
   максимум `review_needed`.
3. Отсутствие найденного evidence **≠** нарушение → `review_needed`, не автоматический `no`.
4. LLM **не считает числа и не ставит статусы** — только `model_note`/экстракция кандидатов
   значений; сравнение порогов и агрегация всегда в коде.
5. Общий вердикт «ПД/РД соответствует» **не формируется никогда**; финальный ответ —
   `human_decision`/`human_answer`, `human_final_required: true` всегда в `workflow_plan`.

## Где в коде

```
proxy/services/checklist_template_importer.py   # XLSX → versioned template JSON
proxy/services/checklist_review_service.py      # построчный прогон и evidence-guard
proxy/services/checklist_report_service.py      # XLSX/JSON/HTML отчёты
proxy/services/pp87_composition_service.py      # состав ПД по ПП РФ №87
proxy/routers/checklist_review.py                # API прогонов, решений и выгрузок
sovushka/checklist_review_panel.py               # интерфейс оператора
config/checklists/glorax_pd_2026.json            # 335 критериев ПД
config/checklists/glorax_rd_2026.json            # 692 критерия РД
config/checklists/glorax_param_rules.yaml        # параметрические правила
```

Существующий код, который эти компоненты вызывают/расширяют (не переписывают):
`proxy/services/doc_review_service.py`, `proxy/services/normcontrol_service.py`,
`proxy/services/doc_review_retrieval_service.py`, `proxy/services/evidence_contract.py`,
`proxy/services/normcontrol_review_map_service.py`, `proxy/services/document_set_model.py`,
`proxy/services/job_service.py`, `proxy/services/workflow_plan_service.py`.

## Граница / связь

- Реализованы импорт, evidence-движок, параметры, ПП РФ №87, API, решения инженера,
  UI KIT-интерфейс и отчёты XLSX/JSON/HTML. Checklist-chat из забытой ветки не
  перенесён: финальный текст принадлежит общему model-owned контуру. Следующий
  эксплуатационный этап — фоновый полный прогон с checkpoint/progress.
- Не подменяет [CHECKLIST_REVIEW_PD_TASK.md](CHECKLIST_REVIEW_PD_TASK.md) (архитектурный
  канон) и [implementation_plan.md](../implementation_plan.md) (полный план фаз) — этот
  документ фиксирует эталонные числа и определения для последующих фаз importer/service.
- Пространственно-визуальные критерии (кухни над жилыми, ворота паркинга и пр.) — честная
  граница `manual_required` в v1; уверенные проверки только при структурной геометрии
  (IFC/CAD-BIM rooms), см. implementation_plan.md §3.4 и Phase 6 (go/no-go).
