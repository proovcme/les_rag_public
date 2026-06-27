# CHECKLIST_REVIEW_PD_TASK

# Модуль проверки ПД по чек-листам входного контроля

Дата: 2026-06-26.

Статус: planned feature.

Цель: сделать отдельный workflow проверки проектной документации стадии ПД по чек-листам
входного контроля ГИПа БУП. Это не замена СПДС-нормоконтролю и не новый rule-engine.
Архитектурно это **RAG-led checklist review**: чек-лист задает карту требований,
RAG ищет evidence в комплекте и исходниках, код проверяет только формализуемое,
модель связывает evidence и объясняет, инженер подтверждает итоговый ответ.

Дополнение 2026-06-26 по `les final build spec.pdf`:

```text
/Users/ovc/Documents/les final build spec.pdf
```

Чек-лист ПД — НЕ верхний продукт нормоконтроля. Он должен быть прикладным профилем
поверх общего workflow **Doc Review / Formal Checker**:

```text
ГОСТ/СПДС/ПП 87 review-map
  -> Formal Checker (0 LLM)
  -> RAG requirement/evidence retrieval
  -> checklist profile БУП/ГИП
  -> normalized remarks
  -> human decision
  -> XLSX/JSON/HTML/DOCX/PDF report
```

Иначе модуль быстро скатится в "заполнить Да/Нет в Excel" и потеряет главный смысл LES:
проверяемые замечания с источниками, трассой и ручным подтверждением инженера.

---

## 1. Reference inputs

Исходные файлы оператора:

```text
/Users/ovc/Documents/Чек_лист_входного_контроля_ПД_ГИПы_БУП.xlsx
/Users/ovc/Documents/Приложение 1[1].pdf
/Users/ovc/Documents/Приложение 2[1].pdf
/Users/ovc/Documents/Чек_лист_входного_контроля_РД_ГИПы_БУП.xlsx
```

Для первого релиза использовать:

```text
Чек_лист_входного_контроля_ПД_ГИПы_БУП.xlsx
Приложение 1[1].pdf как печатный контрольный образ
```

РД-чек-лист использовать только как future template:

```text
Чек_лист_входного_контроля_РД_ГИПы_БУП.xlsx
Приложение 2[1].pdf
```

Политику хранения принять такую:

```text
исходные XLSX/PDF не коммитить в git
в git коммитить только нормализованный checklist template / config
PDF считать human-readable образом XLSX, а не главным машинным источником требований
```

---

## 2. Что обнаружено при анализе файлов

### ПД workbook

```text
файл: Чек_лист_входного_контроля_ПД_ГИПы_БУП.xlsx
листов: 12
проверяемых разделов: 10
criteria-like пунктов: около 400
```

Листы:

```text
Правила заполнения
Общее
СПОЗУ
АР
КР
ЭОМ
ЭН
ВК и НВК
ОВиК
СС
ПБ2 (АППЗ)
Сводная
```

Структура проверочных листов:

```text
row 1: название раздела
row 2: заголовки
column A: номер / иерархия / заголовок блока
column B: критерий проверки
column C: отметка выполнения
column D: примечание
```

Data validation:

```text
Да
Нет
Не требуется
```

Некоторые пункты исходной документации допускают только:

```text
Да
Нет
```

Итоговые формулы находятся на каждом листе и в `Сводная`. Их не использовать как источник
истины для automated review, но использовать как ориентир для XLSX-отчета.

### РД workbook

```text
файл: Чек_лист_входного_контроля_РД_ГИПы_БУП.xlsx
листов: 28
criteria-like пунктов: около 793
```

РД-чек-лист содержит много повторяющихся СПДС-пунктов вида:

```text
Том РД соответствует требованиям ГОСТ Р 21.101-2020
Общие данные комплекта приложены
Содержание комплекта приложено
Ведомость томов приложена
Ведомость основного комплекта рабочих чертежей приложена
```

Для v1 РД не реализовывать, но importer делать достаточно универсальным, чтобы позже принять
РД workbook без переписывания архитектуры.

### PDF-приложения

```text
Приложение 1[1].pdf: 24 страницы, A4, текстовый PDF
Приложение 2[1].pdf: 28 страниц, A4, текстовый PDF
```

PDF являются печатным образом чек-листов. Для машинного импорта предпочтителен XLSX,
потому что в нем сохранены листы, ячейки, формулы и data validation.

---

## 3. Классы пунктов проверки

Пункты чек-листа не являются однородными. Их надо классифицировать перед проверкой.

Минимальные классы:

```text
presence          наличие документа / расчета / раздела / таблицы
calculation       наличие расчета и evidence его результата
spds_formal       СПДС-оформление, ведомости, общие данные, содержание
cross_section     увязка между разделами
tz_vendor         соответствие ТЗ, ОПР, АТР, СТУ, вендор-листу, стандарту GloraX
layout            читаемость листов, границы листа, наложения, планы/узлы/схемы
manual_required   пункт требует инженерного решения или внешнего подтверждения
```

Принцип:

```text
kind не является verdict
kind отвечает только на вопрос, какой evidence нужен и каким способом его искать
```

Примеры:

```text
Приложен отчет об инженерно-геологических изысканиях
  -> presence, source_doc

Выполнен расчет инсоляции и КЕО
  -> calculation, source_doc + project_doc

Раздел СПОЗУ соответствует ГПЗУ/ППТ
  -> cross_section, project_doc + source_doc

Слои конструкций благоустройства соответствуют ТЗ
  -> tz_vendor, project_doc + source_doc

Листы комплекта читаемы
  -> layout, computed/layout evidence
```

---

## 4. Архитектура

### Общая схема

```text
dataset ПД + source datasets
  -> document set model (ПД/РД, раздел, комплект, шифр, ведомости, листы)
  -> formal checker evidence (ГОСТ Р 21.101, ПП 87, штампы, ведомости, изменения)
  -> RAG requirement retrieval (ГОСТ/СПДС/ПП 87/source docs)
  -> checklist template
  -> selection by stage/discipline
  -> retrieval queries per item
  -> computed checks where possible
  -> evidence pack per item
  -> suggested answer + confidence
  -> human confirmation
  -> XLSX/JSON/HTML report
```

### Что НЕ делать

```text
не делать чек-лист автономным rule-engine
не заполнять "Да/Нет" без source_ref
не считать наличие слова в тексте достаточным доказательством
не заставлять LLM считать числа
не смешивать этот workflow с текущим normcontrol_service.py
не коммитить исходные XLSX/PDF оператора
не дублировать Doc Review / Formal Checker отдельным чек-листовым движком
не превращать ГОСТ Р 21.101-2026 или ПП 87 в полный YAML-текст стандарта
не давать общий юридический verdict "ПД соответствует"
```

### Что переиспользовать

```text
retrieval/RAG слой для поиска evidence
normcontrol_service для формальных computed checks: PDF, текстовый слой, формат, шифры, ведомость
normcontrol_review_map_service как архитектурный пример review-map loader
doc_review_service как верхний SPDS review workflow
document_set_model как модель комплекта ПД/РД
config/normcontrol/gost_r_21_101_2026.yaml как первый rulepack/review-map
существующие dataset/source_ref механизмы
XLSX report паттерны из normcontrol/bor/forms
```

### Верхний слой из final build spec

`les final build spec.pdf` задает более полный продукт, чем один чек-лист БУП:

```text
Formal Checker
  - ГОСТ Р 21.101-2026 / СПДС
  - ПП РФ №87: состав ПД
  - состав тома / ведомости
  - шифры разделов и комплектов
  - основная надпись / штамп / подпись ГИПа
  - ИУЛ / изменения / ИЦД

RAG normative checker
  - находит пункт ГОСТ/СПДС/ПП 87
  - даёт requirement_source_ref
  - не заменяет computed checks

Checklist profile
  - прикладывает пункты БУП/ГИП к уже найденным evidence
  - добавляет дисциплинарный UX: Общее / СПОЗУ / АР / КР / ...
  - хранит human_answer и human_note

Cross-Checker ПД↔РД
  - отдельная фаза, не v1 checklist
  - сравнивает извлечённые параметры стадий
```

Для v1 чек-листа ПД не надо строить всё сразу, но интерфейсы должны быть совместимы с этой
иерархией: `ChecklistReviewItem` должен уметь ссылаться на `doc_review_item_id`,
`formal_check_id`, `requirement_source_ref`, `document_source_ref`.

### Normalized remark

Единый выход замечания должен быть совместим с final build spec:

```json
{
  "id": "REM-042",
  "severity": "critical|major|minor|info",
  "category": "formal|normative|consistency|checklist",
  "location": {
    "document": "Том 3. ПБ. Лист 5",
    "page": 5,
    "section": "Основная надпись"
  },
  "description": "Отсутствует подпись ГИПа",
  "normative_ref": {
    "document": "ГОСТ Р 21.101-2026",
    "clause": "пункт/раздел",
    "source_ref": "dataset:file#page=..."
  },
  "document_evidence": [
    {
      "source_ref": "pd_dataset:file#page=5",
      "snippet": "..."
    }
  ],
  "checklist_ref": {
    "template": "pd_bup_glorax",
    "item_id": "PD-OB-1.2"
  },
  "recommendation": "Проверить/добавить подпись ГИПа",
  "human_decision": "unset|confirmed|rejected|needs_more_evidence"
}
```

XLSX-чек-лист может быть одним из renderer-ов этого замечания, но не единственным форматом.

### Новые сервисы

```text
proxy/services/checklist_template_importer.py
proxy/services/checklist_review_service.py
proxy/services/checklist_report_service.py
proxy/routers/checklist_review.py
```

Опционально позже:

```text
proxy/services/checklist_item_classifier.py
```

В первом релизе классификацию можно сделать эвристически и сохранить в template, чтобы инженер мог
править руками.

---

## 5. Data model

### ChecklistTemplate

```json
{
  "name": "pd_bup_glorax",
  "stage": "PD",
  "title": "Чек-лист входного контроля ПД ГИПы БУП",
  "source_file_name": "Чек_лист_входного_контроля_ПД_ГИПы_БУП.xlsx",
  "version": "2026-06-26",
  "disciplines": ["Общее", "СПОЗУ", "АР", "КР", "ЭОМ", "ЭН", "ВК_НВК", "ОВиК", "СС", "ПБ2"],
  "items": []
}
```

### ChecklistItem

```json
{
  "id": "PD-AR-3.4",
  "stage": "PD",
  "discipline": "АР",
  "sheet_name": "АР",
  "row": 35,
  "item_no": "3.4",
  "section_path": ["Архитектурные решения", "Наличие необходимых расчетов"],
  "criterion": "Выполнен расчет ...",
  "answer_cell": "C35",
  "note_cell": "D35",
  "allowed_answers": ["Да", "Нет", "Не требуется"],
  "kind": "calculation",
  "required_sources": ["project_doc", "calculation"],
  "suggested_check": "retrieval",
  "severity": "review"
}
```

### ChecklistReviewRun

```json
{
  "run_id": "uuid",
  "dataset_id": "pd_dataset",
  "source_dataset_ids": ["tz_dataset", "opr_dataset", "stu_dataset"],
  "template": "pd_bup_glorax",
  "mode": "evidence_review",
  "created_at": "iso8601",
  "status": "running|done|failed",
  "summary": {}
}
```

### ChecklistReviewItem

```json
{
  "item_id": "PD-AR-3.4",
  "suggested_answer": "yes|no|not_required|manual_required|unknown",
  "confidence": 0.0,
  "evidence": [
    {
      "kind": "project_doc|source_doc|computed|layout",
      "source_ref": "dataset:file#page=1",
      "snippet": "short extract",
      "reason": "why this supports or blocks the criterion"
    }
  ],
  "computed_check": {
    "name": "optional",
    "status": "ok|issue|not_run"
  },
  "model_note": "short explanation",
  "human_answer": "unset|yes|no|not_required",
  "human_note": "",
  "doc_review_item_ids": ["G21.101-2026-D3-001"],
  "formal_check_ids": ["NK-03"],
  "normalized_remark_ids": ["REM-042"]
}
```

Правило:

```text
suggested_answer yes/no запрещен без evidence.source_ref
manual_required допустим без evidence, если критерий неразрешим по загруженным данным
human_answer всегда сильнее suggested_answer в финальном отчете
```

---

## 6. API

Добавить endpoints:

```text
GET  /api/checklist-review/templates
POST /api/checklist-review/{dataset_id}/run
GET  /api/checklist-review/{run_id}
GET  /api/checklist-review/{run_id}/download
POST /api/checklist-review/{run_id}/items/{item_id}/decision
```

Связь с общим нормоконтролем:

```text
POST /api/doc-review/{dataset_id}/run        # общий СПДС-review по rulepack
POST /api/checklist-review/{dataset_id}/run  # профиль чек-листа поверх evidence/review
```

`checklist-review` не должен повторно реализовывать проверки ГОСТ/ПП 87. Он должен:

```text
1) запускать/переиспользовать doc-review результат;
2) запускать retrieval по специфическим пунктам чек-листа;
3) объединять evidence в рабочий чек-лист ГИПа;
4) хранить human decisions.
```

Request для запуска:

```json
{
  "template": "pd_bup_glorax",
  "source_dataset_ids": ["..."],
  "discipline": "all|Общее|СПОЗУ|АР|КР|ЭОМ|ЭН|ВК_НВК|ОВиК|СС|ПБ2",
  "mode": "evidence_review"
}
```

Decision request:

```json
{
  "human_answer": "yes|no|not_required",
  "human_note": "optional"
}
```

---

## 7. UI

Добавить в Совушку:

```text
Инструменты -> Проверка ПД по чек-листу
```

Минимальный UI:

```text
template selector: Чек-лист входного контроля ПД
dataset selector: комплект ПД
source datasets selector: исходники / ТЗ / ОПР / СТУ / вендор-листы / изыскания
discipline selector: all / раздел
button: Проверить
summary: всего / yes / no / manual_required / unknown / confirmed
table: пункт, критерий, suggested answer, confidence, evidence count, human answer
drawer/card: source refs, snippets, model note, кнопки Да/Нет/Не требуется
download: XLSX/JSON/HTML
```

UX-принцип:

```text
не показывать бинарный "соответствует/не соответствует" для всего комплекта
показывать review progress и незакрытые manual_required пункты
```

---

## 8. Report

Форматы:

```text
XLSX
JSON
HTML
DOCX
PDF
```

XLSX должен быть близок к исходному чек-листу:

```text
Раздел
№
Критерий
Предложенный ответ
Уверенность
Evidence
Примечание системы
Ответ инженера
Примечание инженера
```

Сводка:

```text
всего пунктов
suggested yes/no/not_required/manual_required/unknown
confirmed yes/no/not_required
без evidence
top risk items
```

DOCX/PDF отчёт — для выдачи замечаний в формате нормоконтроля, а не для заполнения чек-листа:

```text
1. Сводка проверки
2. Перечень замечаний по severity
3. Нормативное основание
4. Локация в комплекте
5. Evidence / screenshot / source_ref
6. Рекомендация
7. Статус инженера
```

Для v1 можно сделать XLSX/JSON/HTML, но модель данных не должна блокировать DOCX/PDF renderer.

---

## 9. Первый набор проверок

### Formal Checker / ГОСТ / ПП 87

```text
проверить состав ПД по ПП РФ №87: обязательные разделы, отсутствующие/лишние/unknown
проверить состав тома: наличие ведомостей, состава проекта/тома, общих данных
проверить шифры разделов и комплектов
проверить согласованность имени файла, обозначения, ведомости и штампа там, где evidence доступен
проверить признаки основной надписи / штампа; если layout не уверен -> manual_required
проверить наличие поля/подписи ГИПа как potential/manual issue, не как silent pass
проверить ИУЛ/изменения/ИЦД только при наличии признаков изменений; иначе info/not_applicable
```

Принцип:

```text
Formal Checker даёт computed_issue/supported_by_evidence/manual_required.
Checklist review использует эти результаты как evidence, но не превращает их в безусловный итог.
```

### Presence

```text
найти наличие отчетов изысканий
найти наличие ГПЗУ/ППТ/АГО/ОПР/ТЗ/СТУ/вендор-листа
найти наличие расчетов
найти наличие разделов ПД по дисциплинам
```

### Calculation

```text
проверить, что расчет присутствует как документ/раздел/таблица
не пересчитывать инженерный расчет в v1
если расчет найден, дать source_ref и suggested yes с confidence
если расчет не найден, дать unknown/manual_required, а не автоматический no
```

### Cross-section

```text
для "соответствует ТЗ/ОПР/СТУ/GloraX" искать evidence минимум в двух местах:
  1) проверяемый раздел ПД
  2) исходный документ
если одна сторона отсутствует, статус manual_required/unknown
```

### SPDS formal

```text
переиспользовать normcontrol_service и doc_review_service
формат листа, текстовый слой, шифры, ведомость, состав комплекта
ГОСТ Р 21.101-2026 review-map как source of requirement routing
ПП РФ №87 как composition checker для ПД
```

### Layout

```text
в v1 только простые computed/layout признаки:
  PDF открывается
  есть текстовый слой
  листы имеют распознаваемый формат
  страницы не пустые
сложные визуальные пункты -> manual_required
```

---

## 10. Tests

### Unit tests

```text
test_checklist_template_importer_pd_extracts_sections
test_checklist_template_importer_skips_rules_and_summary_sheets
test_checklist_template_importer_reads_allowed_answers
test_checklist_template_importer_stable_ids
test_checklist_template_importer_classifies_basic_kinds
test_checklist_items_can_reference_doc_review_items
test_checklist_items_can_reference_normalized_remarks
```

Acceptance for importer:

```text
ПД template содержит 10 проверяемых разделов
ПД template содержит примерно 400 items
каждый item имеет id, discipline, item_no, criterion, allowed_answers
```

### Service tests

```text
presence item with matching source doc -> suggested yes + source_ref
presence item without source doc -> unknown/manual_required, no fake no
calculation item finds calculation evidence but does not compute engineering result
cross_section item requires project_doc and source_doc evidence
spds item can attach computed evidence from normcontrol_service
spds item can attach doc_review evidence from ГОСТ Р 21.101-2026 rulepack
ПП 87 missing section -> checklist item gets computed_issue evidence, not raw no
stamp/title-block uncertain -> manual_required, not pass
```

### API tests

```text
templates endpoint lists pd_bup_glorax
run endpoint creates review result
get endpoint returns summary and items
download endpoint returns XLSX
decision endpoint persists human answer
```

### Safety tests

```text
no suggested yes/no without evidence.source_ref
LLM markers are not present in computed-only helpers
manual_required is preserved in report
doc_review/checklist never emits final legal verdict for whole ПД
ГОСТ/ПП 87 full text is not committed into YAML/rulepack
```

---

## 11. Acceptance

Первая рабочая приемка:

```text
реальный комплект ПД от оператора загружается как dataset
исходники выбираются отдельными source datasets
run завершается без crash
top-20 suggested answers сверены оператором вручную
0 пунктов с уверенным yes/no без source_ref
XLSX отчет пригоден как рабочий чек-лист ГИПа
manual_required виден отдельно и не маскируется под pass
```

Дополнительная приемка по final build spec:

```text
doc-review по ГОСТ Р 21.101-2026 запускается как отдельный слой
checklist-review может переиспользовать doc-review evidence
ПП 87 composition checker на синтетике находит отсутствующий раздел ПД
title-block/stamp uncertainty дает manual_required
normalized remark JSON формируется для computed_issue
нет общего статуса "ПД соответствует" без human decision
экспорт XLSX чек-листа и JSON remarks имеют общие ids/source_refs
```

Не цель v1:

```text
полностью автоматическая экспертиза
юридический verdict соответствия
проверка всех инженерных расчетов по существу
DWG/RVT/BIM geometry checks
автоматическое сравнение всех чертежных узлов с АТР
```

---

## 12. Roadmap

### Phase 0: Doc Review alignment

```text
связать план чек-листа с docs/DOC_REVIEW_GOST_R_21_101_2026_PLAN.md
не дублировать doc_review_service
добавить в ChecklistReviewItem ссылки на doc_review/formal/remark ids
зафиксировать normalized remark schema
```

### Phase 1: Template import

```text
импорт ПД XLSX
нормализация items
эвристическая классификация kinds
тесты importer
```

### Phase 2: Evidence review service

```text
run по dataset + source datasets
retrieval под каждый item
computed checks для простых формальных пунктов
переиспользование doc_review results
переиспользование ПП 87 composition results
JSON result
```

### Phase 3: Report and UI

```text
XLSX/HTML report
JSON remarks
Инструменты -> Проверка ПД по чек-листу
human decisions
download
```

### Phase 3b: Normcontrol report renderer

```text
DOCX/PDF отчёт нормоконтроля по normalized remarks
скриншоты/evidence attachments для штампов и листов
severity summary
```

### Phase 4: RD extension

```text
импорт РД workbook
сопоставление повторяющихся СПДС-пунктов с ГОСТ Р 21.101-2026 review-map
дисциплины РД
```

### Phase 5: Cross-Checker ПД↔РД

```text
извлечь параметры из ПД
извлечь параметры из РД
сравнить значения как consistency review
LLM объясняет расхождение, но не генерирует нормативное требование
```

---

## 13. Архитектурный инвариант

Этот модуль должен сохранять главный принцип:

```text
чек-лист задает вопрос
RAG ищет evidence
код проверяет формализуемое
LLM связывает и объясняет
инженер принимает ответственное решение
```

Если будущая реализация начинает сама проставлять итоговые `Да/Нет` без source_ref и human decision,
это архитектурный регресс в ловушку детерминации.

После сверки с `les final build spec.pdf` добавляется ещё один инвариант:

```text
чек-лист ПД — профиль общего Doc Review, а не отдельный нормоконтроль
Formal Checker — evidence provider, а не единственный судья
normalized remark — общий выход для checklist/formal/normative/consistency
```
