# DOC_REVIEW_GOST_R_21_101_2026_PLAN

# СПДС-нормоконтроль документации по ГОСТ Р 21.101-2026

Дата: 2026-06-26.

Статус: **Phases 1-5 РЕАЛИЗОВАНЫ** (computed-проверки D0-D6, title_block OCR за флагом
`LES_TITLE_BLOCK_OCR`, retrieval-подфаза `doc_review_retrieval_service`); **0.24.0.0 добавил
`normalized_remarks` JSON/XLSX** как общий выход для следующих слоёв. **Phase 6** (ПП-87
composition, DOCX/PDF renderer, checklist importer) — план. **Первый доменный workflow
перед сметами и прочими расширениями**.
Это не замена текущему `normcontrol_service.py`, а следующий вертикальный слой поверх него.
Архитектурно это **RAG-led SPDS review**, а не чистая экспертная система.

Дополнение по `/Users/ovc/Documents/les final build spec.pdf`:

```text
Doc Review — верхний продукт нормоконтроля.
Formal Checker — детерминированный evidence provider.
ГОСТ Р 21.101-2026 и ПП РФ №87 — первые обязательные профили.
Чек-листы БУП/ГИП — прикладные профили поверх Doc Review, а не отдельный движок.
Normalized remark JSON — общий выход для formal/normative/checklist/consistency замечаний.
```

Приоритет оператора:

```text
Нормоконтроль первым.
Проверка на соответствие СПДС и требованиям нормоконтроля.
Первый стандарт в фокусе: ГОСТ Р 21.101-2026.
```

Внешняя проверка статуса стандарта:

```text
ГОСТ Р 21.101-2026
Система проектной документации для строительства.
Основные требования к проектной и рабочей документации.
Утверждён приказом Росстандарта от 12.02.2026 № 129-ст.
Дата введения: 01.04.2026.
Взамен: ГОСТ Р 21.101-2020.
```

Важно: полный текст стандарта не коммитить в репозиторий. Rulepack хранит карту review:
какие требования искать, какие evidence нужны, какие checks возможны. Source evidence
по пунктам берётся из легально доступного оператору экземпляра стандарта в RAG.

---

## 1. Что уже есть

Текущий формальный нормоконтроль v1:

```text
NK-01 формат листов по ГОСТ 2.301
NK-02 текстовый слой / сканы
NK-03 согласованность шифра комплекта в именах файлов
NK-04 ведомость рабочих чертежей ↔ фактический состав
```

Файлы:

```text
proxy/services/normcontrol_service.py
proxy/routers/normcontrol.py
tests/test_normcontrol_service.py
docs/API.md
docs/LES3_PLAN.md W13.1
```

Чего не хватает для ГОСТ Р 21.101-2026:

```text
версии стандарта как review rulepack
проверки применимости ПД/РД
проверки структуры комплекта документации
проверки состава ведомостей/основных надписей/обозначений/изменений
RAG-поиска требований стандарта и evidence в комплекте
отчёта "пункт ГОСТ → замечание → источник в комплекте → severity"
матрицы manual_required там, где без layout/эксперта нельзя
```

---

## 2. Цель первой вертикали

Первый рабочий срез:

```text
загрузить комплект ПД/РД
выбрать "Проверка документации: ГОСТ Р 21.101-2026"
получить отчёт по формальным и структурным требованиям
получить review status по СПДС / требованиям нормоконтроля, а не юридическое решение
видеть найденные требования ГОСТ/СПДС и evidence по комплекту
видеть, какие пункты проверены кодом
видеть, какие пункты требуют ручного подтверждения
получить source_refs до листа/файла/пункта ГОСТ
скачать XLSX/JSON/HTML отчёт
иметь машинный JSON замечаний, совместимый с DOCX/PDF renderer
```

Не цель первого среза:

```text
полный юридически исчерпывающий нормоконтроль
проверка всех специализированных ГОСТ СПДС
проверка проектных решений по существу
автоматическая экспертиза без человека
```

Но workflow должен быть построен так, чтобы следующие СПДС-стандарты добавлялись
RAG/rulepack-ами, а не отдельными разовыми сервисами и не зашитым "ГОСТ в YAML".

Ключевой принцип:

```text
RAG ищет требования и evidence.
Код проверяет только формализуемые вещи.
Модель объясняет и связывает найденное.
Инженер подтверждает или отклоняет замечание.
Итоговый статус замечания появляется только после computed evidence или human decision.
```

---

## 3. Архитектура

### Rulepack as Review Map

Новый каталог:

```text
config/normcontrol/gost_r_21_101_2026.yaml
```

Формат правила:

```yaml
- id: G21.101-2026-NK-001
  clause: "4.1.2"
  title: "Обозначение документа"
  kind: retrieval|computed|layout|manual_required
  scope: project_doc|working_doc|both
  severity: error|warning|info
  check: designation_pattern
  evidence_required:
    - document_file
    - sheet_or_table
  message: "Краткое paraphrase-описание нарушения"
```

Принцип:

```text
rulepack не содержит полный текст ГОСТ
rulepack не выносит review status сам по себе
rulepack направляет RAG: какие требования/evidence искать
каждый результат содержит requirement source_ref и document source_ref
непроверяемое автоматически правило даёт review_needed/manual_required, а не fake pass
computed/layout checks являются evidence-слоем, а не заменой retrieval
```

### Services

Новые/расширяемые сервисы:

```text
proxy/services/doc_review_service.py
proxy/services/doc_review_retrieval_service.py     # retrieval-подфаза (kind: retrieval)
proxy/services/normcontrol_review_map_service.py   # loader rulepack/review map
proxy/services/title_block_extract_service.py
proxy/services/document_set_model.py
 normalized_remarks in doc_review_service.py        # v0.24 baseline contract
 proxy/services/remark_normalization_service.py     # (позже, если контракт разрастётся)
```

**Retrieval-подфаза (`doc_review_retrieval_service`).** Для целей `kind: retrieval` ищет в корпусе
проекта ДВА вкуса (через `source_adapters`, лексика; vector в sync-пути пока UNAVAILABLE/отложен):
1) **факты** — D0-002 устаревший `ГОСТ Р 21.101-2020` в корпусе (найден → `computed_issue` warning с
   source_ref+snippet; не найден → `supported`), D1-010 стадия ПД/РД по маркерам (однозначно →
   `supported`, иначе `manual`);
2) **текст требования** (flavor B) — лексический поиск пункта ГОСТ в корпусе → заполняет
   `requirement.snippet`+source_ref (если стандарт проиндексирован), иначе пусто.
Подфаза живёт в ОРКЕСТРАТОРЕ (`review_dataset`) и инъектирует `retrieval_evidence` в чистую
`run_review`. **Анти-галлюцинация:** поиск UNAVAILABLE → факт `None` → цель остаётся `review_needed`
(не утверждаем «не найдено», если искать не смогли). 0 LLM; числа/факты — детерминированная лексика.

Текущий `normcontrol_service.py` остаётся низкоуровневым formal engine для computed checks.
Он не должен становиться главным продуктовым "судьёй": в новом workflow его выводы
встраиваются в RAG-led review рядом с requirement/document evidence.

Проверка состава ПД по ПП РФ №87 должна жить как отдельный profile/checker над
`document_set_model`, а не внутри YAML ГОСТ Р 21.101-2026. ГОСТ отвечает за СПДС-оформление
и структуру документации, ПП 87 — за состав разделов ПД.

### API

```text
POST /api/doc-review/{dataset_id}/run
GET  /api/doc-review/{dataset_id}/download
GET  /api/doc-review/rulepacks
GET  /api/doc-review/{run_id}
```

Минимальный request:

```json
{
  "rulepack": "gost_r_21_101_2026",
  "mode": "rag_review",
  "project_stage": "PD|RD|unknown",
  "discipline": "auto|AR|KR|OV|VK|EM|...",
  "strictness": "normal|strict"
}
```

### UI

В Совушке:

```text
Инструменты → Проверка документации
  rulepack: ГОСТ Р 21.101-2026
  комплект/датасет
  стадия: ПД/РД/авто
  кнопка: Проверить
  результат: requirements / potential issues / computed checks / manual_required
  фильтр: пункт ГОСТ / файл / status / evidence type
  скачать XLSX/JSON/HTML
```

---

## 4. Первый набор проверок

### D-1. СПДС applicability

```text
определить, что комплект относится к СПДС-документации
определить ПД/РД/unknown
определить основной комплект / раздел / марку / дисциплину
выбрать применимые rulepack-и: сначала ГОСТ Р 21.101-2026, затем расширения
если применимость не доказана — review_needed/manual_required, не окончательный статус
```

### D0. Standard/version gate

```text
проверить, что выбран rulepack ГОСТ Р 21.101-2026, а не 2020
в отчёте указать дату rulepack и source standard
если в корпусе найден только ГОСТ Р 21.101-2020 — warning "устаревшая база"
```

### D1. Комплект и стадия

```text
определить ПД/РД/unknown
найти основной комплект / раздел / подраздел / марку
проверить, что файлы комплекта имеют согласованный базовый шифр
```

### D2. Состав комплекта

```text
найти ведомость рабочих чертежей / состав проекта / перечень документов
сверить ведомость с фактическими файлами
пометить отсутствующие, лишние и нераспознанные документы
для каждого результата показать, каким требованием он мотивирован
для стадии ПД отдельно сверить состав разделов с профилем ПП РФ №87
```

### D3. Обозначения и именование

```text
проверить формат обозначений документов/комплектов
проверить недопустимые пробелы/разделители в обозначениях
проверить согласованность обозначения в имени файла, штампе и ведомости
```

### D4. Листы и основные надписи

```text
извлечь формат листа
найти основную надпись / штамп
проверить наличие обязательных зон, если layout уверен
если layout не уверен — manual_required
```

**D4-002 (штамп) — computed + scan-aware OCR.** `title_block_extract_service` детектит штамп по
сигнатурам полей основной надписи (Изм./Кол.уч./Стадия/Листов/Разраб./Н.контр./Масштаб…) в тексте
листа. Для **сканов без текст-слоя** (где текстом штамп не извлечь) за флагом `LES_TITLE_BLOCK_OCR`
включается **Tesseract-OCR** нижне-правого угла листа (клип формы 3 ДО растеризации — быстро; бинарь
изолирован от venv, `backend.ocr_parser`). Принцип консервативный (анти-галлюцинация): OCR может только
**подтвердить** штамп (скан → `present` → D4-002 supported); если OCR не подтвердил — лист остаётся
`scan` → `manual_required`, «нет штампа» по шумному OCR НЕ утверждается. OCR вне hot-path (флаг OFF по
умолчанию), оператор включает на скан-комплект. Сводка `detect_dataset` несёт `ocr_used`.

### D5. Изменения и revisions

```text
найти таблицы изменений / признаки revision
проверить согласованность revision в листе, ведомости и имени файла
если комплект без изменений — info, не error
```

### D6. Electronic/source readiness

```text
PDF открывается
есть текстовый слой или понятный OCR-required
лист можно привязать к source_ref
нет silent parser degradation
```

---

## 5. Evidence model

Каждый review item:

```json
{
  "rule_id": "G21.101-2026-NK-001",
  "clause": "4.1.2",
  "status": "retrieved_requirement|computed_issue|potential_issue|supported_by_evidence|manual_required|not_applicable|confirmed|rejected",
  "severity": "error|warning|info",
  "target": "АТ-РД-ОВ2-С-00-П1.pdf#page=1",
  "requirement": {
    "source_ref": "ГОСТ Р 21.101-2026#clause=4.1.2",
    "snippet": "краткий фрагмент/пересказ требования"
  },
  "document_evidence": [
    {
      "kind": "document",
      "source_ref": "file://...#page=1",
      "snippet": "короткий фрагмент/значение"
    }
  ],
  "computed_check": {
    "name": "designation_consistency",
    "status": "ok|issue|not_run"
  },
  "model_note": "почему это может быть замечанием",
  "human_decision": "unset|confirmed|rejected|needs_more_evidence",
  "confidence": 0.0
}
```

Начиная с 0.23.6.9 JSON-отчёт дополнительно несёт системный `defense`:
`defense_contract_v1` (`DefensePack/DefenseClaim` из `evidence_contract`). Это тот же
claim→source/formula/input→gaps/actions контракт, что у смет: UI/экспорт могут показывать
обоснование пунктов нормоконтроля без парсинга markdown и без финального verdict от модели.

Начиная с 0.23.6.11 чатовый ответ `doc_review` — не служебная трассировка, а человекочитаемый
отчёт для защиты: краткий verdict машины, сводка классов, таблицы `Основание / Evidence комплекта /
Почему так / Действие`, блок `Защита решения`. Рабочая память диалога (`LES.md`/history memory) не
добавляется в этот отчёт: все доказательные данные должны приходить из `ReviewItem` и JSON `defense`.

D4-001 `sheet_format` снова computed: `doc_review_service.build_sheet_format_evidence()` открывает
PDF через PyMuPDF, измеряет страницы и классифицирует формат через `normcontrol_service.classify_format`
по ГОСТ 2.301. Если PDF-геометрия недоступна — пункт честно остаётся `manual_required`; если размер
нестандартный — это `computed_issue` с `source_ref` страницы. Это НЕ заменяет проверку размещения рамки,
основной надписи и заполнения граф: эти вещи должны идти отдельным layout/title-block инструментом.

Начиная с 0.23.6.12 D4-002 получил layout-tool v1 для текстового PDF: `title_block_extract_service`
ищет сигнатуры основной надписи не только в тексте листа целиком, но и в ожидаемой нижней правой зоне
листа (`layout_zone.expected_zone_rel`). Если сигнатуры есть вне этой зоны, пункт не считается
подтверждённым: `doc_review` выдаёт `computed_issue` с пояснением, что основная надпись не в ожидаемой
зоне. Это всё ещё не полный контроль всех граф формы: заполненность/координаты каждой ячейки требуют
следующего эталонного `layout_reference`.

Служебные источники для работы вынесены в `config/service_sources.yaml` и API `/api/service-sources`.
Для нормоконтроля важны как минимум: СПДС rulepack, нормативный RAG с легальным текстом ГОСТ/СПДС,
и layout-reference (сейчас optional/degraded). UI показывает, чего не хватает, чтобы не было эффекта
чёрного ящика.

Единый normalized remark для отчётов и интеграций:

```json
{
  "id": "REM-042",
  "source": "doc_review|formal_checker|checklist|cross_checker",
  "severity": "critical|major|minor|info",
  "category": "formal|normative|consistency|checklist",
  "location": {
    "document": "Том 3. ПБ",
    "page": 5,
    "section": "Основная надпись"
  },
  "description": "Краткое описание замечания",
  "normative_ref": {
    "document": "ГОСТ Р 21.101-2026",
    "clause": "пункт/раздел",
    "source_ref": "norm_dataset:file#page=..."
  },
  "document_evidence": [
    {
      "source_ref": "pd_dataset:file#page=5",
      "snippet": "короткий фрагмент"
    }
  ],
  "recommendation": "Что проверить или исправить",
  "human_decision": "unset|confirmed|rejected|needs_more_evidence"
}
```

Правила:

```text
нет requirement source_ref — нет замечания по ГОСТ
нет document source_ref — только missing_evidence/review_needed
нет уверенного extraction — manual_required
окончательный статус не рисовать без computed evidence или human_decision
LLM объясняет, связывает и предлагает вопросы, но не утверждает финальное решение
remark может попасть в XLSX/DOCX/PDF только с source_ref или явным статусом manual_required
```

---

## 6. Acceptance

Минимальная приёмка первой версии:

```text
synthetic комплект РД с ведомостью: no confirmed error, requirements/evidence trace есть
synthetic комплект РД: лист из ведомости отсутствует → computed_issue с пунктом/файлом
synthetic комплект: шифр в имени и ведомости расходится → potential/computed issue
PDF без текстового слоя → OCR/manual_required, не crash
штамп не найден → manual_required, не fake pass
ГОСТ 21.101-2020 в корпусе при выбранном 2026 → warning о версии
отчёт XLSX/JSON создаётся
UI показывает retrieved requirements / document evidence / computed checks / review needed отдельно
ПП 87 checker на синтетической ПД находит отсутствующий обязательный раздел
normalized remark JSON создаётся для computed_issue и potential_issue
чек-лист ПД может сослаться на doc_review item / normalized remark без повторной проверки
```

Live-приёмка:

```text
1 реальный комплект РД от оператора
1 реальный комплект ПД или mixed комплект
ручная сверка top-10 proposed issues
ложные confirmed error ≤ согласованный порог
нет silent pass по непроверенным правилам
```

---

## 7. Test plan

Новые тесты:

```text
tests/test_doc_review_gost_21_101_2026.py
tests/test_normcontrol_review_map_service.py
tests/test_title_block_extract_service.py
tests/test_doc_review_api.py
```

Новые fixtures:

```text
tests/fixtures/doc_review/gost_21_101_2026/
  rd_clean/
  rd_missing_sheet/
  rd_bad_designation/
  rd_no_text_layer/
  rd_stamp_unknown/
```

Гейт:

```bash
uv run python -m pytest tests/test_doc_review_gost_21_101_2026.py -q
make verify
make smoke-basic
```

Дополнительные safety tests:

```text
doc_review/checklist не emit-ит общий verdict "ПД соответствует" без human decision
ПП 87 не зашит в ГОСТ 21.101 rulepack как полный текст
normalized remark без source_ref допускается только для manual_required/missing_evidence
DOCX/PDF renderer потребляет тот же JSON remarks, что и XLSX/HTML
```

---

## 8. Порядок реализации

### Phase 1 — review map skeleton

```text
создать schema review map/rulepack
завести 10-15 review targets первого среза
не коммитить полный текст ГОСТ
unit-тест загрузки/валидации rulepack
```

### Phase 2 — document set model

```text
нормализовать файлы комплекта
извлечь sheet/document designation candidates
сопоставить ведомость ↔ файлы ↔ detected sheets
```

### Phase 3 — report engine

```text
structured review items
XLSX/JSON/HTML report
source_refs
manual_required
normalized remarks
```

### Phase 4 — UI

```text
страница/карта "Проверка документации"
фильтры severity/status/rule
download
open source
```

### Phase 5 — real dataset acceptance

```text
прогон на реальном комплекте
ручной аудит top-10
обновление review map/rulepack
запись в failure ledger
```

### Phase 6 — profiles and final reports

```text
ПП 87 composition profile для ПД
Checklist Review profile: БУП/ГИП поверх doc-review evidence
DOCX/PDF renderer по normalized remarks
Cross-Checker ПД↔РД как отдельная следующая вертикаль
```
