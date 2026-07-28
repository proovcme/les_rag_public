# Сметный модуль Л.Е.С. — единый технический паспорт

> Канонический обзор для человека и AI-агента. Состояние: **18 июля 2026 года**, продукт
> **0.24.40 / build 461**. Этот файл сводит в одном месте архитектуру, рабочий цикл, skill,
> prompt-контракт, данные ФСНБ/ФГИС, model↔code boundary, UI, настройки, тесты и ограничения.
> При расхождении с исполняемым кодом первичны `AGENTS.md`, `SKILL.md`, активная версия
> `/api/version` и перечисленные ниже точки входа.

## 1. Назначение

Сметный модуль превращает ВОР, спецификацию, ТЗ или проектный документ в проверяемую ЛСР:

```text
исходник
  → строки работ и объёмы с provenance
  → модель ищет и читает нормы
  → модель принимает решение по каждой строке
  → код выявляет противоречия, не выбирая замену
  → та же модель проверяет всю таблицу новой immutable-ревизией
  → код проверяет ссылки и единицы
  → код раскрывает ресурсы и считает РИМ
  → цены ФГИС / КАЦ, ФСЭМ, НР, СП, НДС
  → формульный XLSX + лист проверки + trace
```

Главный принцип:

> **Модель связывает и принимает профессиональные решения. RAG показывает evidence. Код считает.**

Код не вправе выбрать норму по top-1, исправить аналог, удалить модельное решение, придумать
coverage, коэффициент или цену. Он вправе исполнить инструмент, проверить машинную ссылочную
целостность, перевести единицы, посчитать формулы и честно поставить blocker.

## 2. Пользовательский сценарий

1. Пользователь выбирает в Совушке режим «Смета».
2. Прикрепляет PDF/XLSX с ВОР либо документ, из которого модель должна получить ВОР.
3. Ставит задачу, например: «Собери ЛСР».
4. Во время работы видит:
   - текущий этап и технический журнал;
   - готовые строки, которые по мере принятия появляются таблицей в текущем сообщении;
   - честное состояние незакрытых строк.
5. После завершения получает:
   - короткое человеческое сообщение;
   - XLSX «ЛСР РИМ»;
   - лист «Проверка»;
   - JSON trace и сохранённый артефакт в истории чата.
6. Автоматический XLSX помечен `Авточерновик`. Без конфликтов пользователь нажимает
   «Проверил — зафиксировать»; при конфликтах сначала открывает их список и явно принимает после
   проверки листа. В обоих случаях создаётся отдельная `mapping_locked`-ревизия и новый расчёт.

Черновой кандидат из поиска не считается готовой строкой. Строка появляется в живой таблице только
после terminal-вызова `submit_lsr_mapping`, то есть после фиксации решения самой моделью.

## 3. Архитектурная схема

```text
NiceGUI / Совушка
  sovushka/pages/chat.py
        │ attachment_id + mode=smeta + user request
        ▼
FastAPI chat stream
  proxy/routers/chat.py
        │
        ▼
Application boundary
  proxy/services/smeta_chat_application_service.py
        │ open server-owned attachment
        │ select agent engine
        │ bridge progress → SSE
        ▼
Document workflow
  proxy/smeta_core/source_intake.py
  proxy/smeta_core/document_workflow.py
        │ work_items + neighbor_context + task_state
        ▼
SmetaAgentRunner
  native | qwen_agent | google_adk
  proxy/services/smeta_agent_runner_service.py
        │
        ▼
SmetaNormToolSession
  browse_norm_catalog → search_norms_batch → read_norms_batch → submit_lsr_mapping
        │
        ├── Typed SQLite: расчётная карточка нормы
        ├── Qdrant/FTS: навигация и кандидаты
        └── модельное решение bind|covered_by|unbound
        ▼
Single merged model revision
        ▼
Calculator / RIM / FSEM / NR-SP / prices
        ▼
XLSX + trace + chat artifact
```

### Слои и ответственность

| Слой | Что делает | Чего не делает |
|---|---|---|
| `source_intake` | читает строки, разделы, количество, единицу, координаты источника | не создаёт норму |
| agent runner | ведёт model/tool loop выбранного фреймворка | не содержит своего сметного selector |
| `SmetaNormToolSession` | исполняет typed tools, хранит открытые карточки и принятые строки | не решает применимость |
| norm browser | exact/FTS/dense+sparse/RRF поиск кандидатов | ranking не означает выбор |
| calculator | переводит единицы, раскрывает ресурсы, считает | не меняет mapping |
| price services | читают цену по точному коду и provenance | не подменяют отсутствующую цену нулём |
| UI | показывает прогресс, готовые строки и артефакт | не выдаёт черновик за результат |

## 4. Формат одной задачи и построчный Qwen-loop

Вся ВОР остаётся одной пользовательской задачей, но решения разделены на построчную mapping-ревизию
и обязательную итоговую `global_review`-ревизию той же модели. Qwen-Agent
обрабатывает её **по одной активной строке**, чтобы 9B-модель не смешивала `work_id`, не рвала JSON и
не тратила контекст на одновременное решение десятков независимых позиций.

Для каждой строки модель видит:

```json
{
  "work_id": "vor-0007",
  "title": "...",
  "unit": "шт",
  "quantity": 4,
  "section": "...",
  "note": "...",
  "source_refs": [],
  "neighbor_context": [],
  "task_state": {
    "mode": "sequential_rows",
    "source_rows_total": 19,
    "completed_rows": 6,
    "remaining_rows": 13,
    "completed_decisions": []
  }
}
```

`completed_decisions` — компактная память общей задачи: `work_id`, название, `bind|covered_by|unbound`,
код нормы, связь покрытия и причина. Она нужна модели для проверки дублей и coverage. Код не правит
эти решения и запрещает текущему row-loop повторно вызывать tools по уже закрытым `work_id`.

Последовательность:

1. `_run_native_norm_agent(... batch_size=1, accumulate_task_state=True)` создаёт одну активную строку.
2. Qwen-Agent получает строку, task state, phase skill и четыре LES tool.
3. Модель смотрит семейства и сборники typed-каталога, выбирает область, ищет внутри неё,
   читает карточки и фиксирует решение.
4. `SmetaNormToolSession` принимает terminal mapping.
   Если Qwen закончила обычным текстом, runner повторно вызывает ту же модель с той же историей и
   просит только сериализовать её собственное решение. Максимум два recovery-хода не дают открыть
   новый бесконечный loop.
5. Сразу публикуется `row_ready` → application переводит его в SSE `smeta_row`.
6. Совушка добавляет строку в живую таблицу.
7. Решение входит в `task_state` следующей строки.
8. После всех строк код предъявляет всей модели полную таблицу, открытые карточки и найденные конфликты.
9. Модель создаёт новую immutable `global_review`-ревизию; код считает её как `priced_draft`.
10. Финальный расчёт разрешён только после отдельного пользовательского `mapping_locked`.

`unbound` принимается только когда `queries_used` буквально присутствуют в выполненном search trace,
а `opened_norm_codes` — среди реально открытых карточек. При ошибке tool возвращает `allowed_evidence`;
его исправляет модель. Для похожих строк одного раздела с одинаковой нормой код создаёт
`possible_duplicate_norm_binding`, но не решает, является ли это дублем: global review может изменить
решение, а оставшийся конфликт блокирует автоматическую трактовку draft как проверенного результата.

Это агентный loop, но его границы реализованы кодом: код управляет очередью, бюджетом, tools и
сохранением состояния; профессиональное содержание каждого решения остаётся у модели.

Production default движка пока `native`. При `LES_SMETA_AGENT_ENGINE=qwen_agent` Qwen default — одна
строка. Native local default — до 10 строк, cloud — вся ВОР одним conversation. Явный
`LES_SMETA_DOCUMENT_BATCH_SIZE` переопределяет транспортный размер.

## 5. Решение строки

Для каждого `work_id` модель обязана вернуть ровно один вариант:

| Решение | Смысл |
|---|---|
| `bind` | открытая карточка применима как точная норма или защищаемый аналог |
| `covered_by` | операция доказанно входит в состав нормы другой выбранной строки |
| `unbound` | после осмысленного поиска защищаемой нормы или покрытия нет |

Для `bind` модель открывает карточку и проверяет операцию, назначение, измеритель, состав работ,
чужие ресурсы, условия и пересечения. Для аналога явно сохраняет ограничения и ресурсные действия.
Terminal без полного `technology_check` не принимается: код проверяет только наличие обязательных
полей, а не правильность профессионального вывода.

Для `unbound` требуются минимум две разные фактически выполненные формулировки поиска, реально
открытые близкие карточки (если были), причины отказа и проверка coverage/декомпозиции.

`covered_by` допустим только по составу работ открытой нормы. Соседство и похожее название ничего не
доказывают.

### Если решение не найдено

- Модель фиксирует `unbound`; код не подставляет первый кандидат.
- Строка появляется в UI как «Оставлено без нормы» и сохраняет причину.
- Остальные строки продолжают обрабатываться и считаться.
- Итог получает `priced_partial`/blockers, а неизвестная сумма остаётся `null`, не `0`.
- Бесконечного поиска нет: действует `LES_SMETA_DOCUMENT_MAX_TOOL_TURNS` (local default 6 на строку).
- Две same-model recovery-попытки ограничены; затем возникает явная ошибка без скрытого fallback.
- При падении всего workflow вложение не потребляется: пользователь может повторить задачу.

## 6. Tools модели

### `browse_norm_catalog`

Читает компактную актуальную карту Typed SQLite: семейства → сборники. После выбора сборника
возвращает подтверждение scope и направляет модель в `search_norms_batch`; таблицы и нормы этим
инструментом не выгружаются. Повтор уже просмотренной страницы не дублирует меню в контексте.
Модель выбирает семейство и один или несколько сборников сама; каталог не является evidence
применимости и не заменяет поиск нормы.

### `search_norms_batch`

Получает `work_id`, осмысленные поисковые формулировки, выбранные моделью `base_types`/`collections`
и страницу. Возвращает компактные карточки с `source_ref` и кратким составом работ. Exact, BM25 sparse,
dense и RRF помогают навигации, но не выбирают норму. Варианты языка
ФСНБ из `config/domain/smeta_retrieval_vocabulary.json` видны в trace и не являются case-specific
boost.

### `read_norms_batch`

Гидратирует выбранные коды из Typed SQLite. Возвращает идентичность, редакцию, семейство, измеритель,
состав работ, provenance и по запросу полный ресурсный состав. `bind` без открытой карточки сохраняет
расчётный blocker.

### `submit_lsr_mapping`

Terminal tool с модельными решениями. Поддерживает `bind`, `covered_by`, `unbound`, applicability,
technology check, analog limitations и `add|replace|exclude|reuse`. После принятия именно здесь
возникает событие готовой строки.

## 7. Skill и prompt

### 7.1. Где лежит канон

| Назначение | Источник |
|---|---|
| полный профессиональный skill | `skills/smeta/SKILL.md` |
| активная документная фаза | `skills/smeta/references/document-mapping-agent.md` |
| устройство ГЭСН-хранилища | `skills/smeta/references/gesn-storage.md` |
| машинный role pack | `config/prompts/smeta_estimator_role.json` |
| сборка prompt | `proxy/services/prompt_registry_service.py` |

Skill — единственный профессиональный контракт. Python не добавляет параллельный prompt с выбором
норм. Для документного runner функция `smeta_native_skill_prompt()` загружает phase-файл и передаёт
его Qwen-Agent как `system_message`. Пользовательская часть `_agent_input()` содержит исходную задачу,
`work_items` и короткий tool contract.

### 7.2. Содержание полного skill

Полный skill закрепляет:

- модельное владение ВОР, операциями, запросами, нормами, аналогами, coverage, основаниями
  коэффициентов и цен; числовые нормативные значения извлекаются из typed-источников;
- независимость mapping-status и pricing-status;
- обязательный provenance `source_row → operation → position → resolution → pricing basis → evidence`;
- правила `bind`, `covered_by`, `unbound` и technology check;
- идентичность нормы через `edition + base_type + norm_key`;
- обязательную глобальную модельную ревизию после построчного mapping и отдельный расчёт user lock;
- ресурсные действия `add|replace|exclude|reuse`;
- отсутствие цены как `null`;
- правила РИМ, ФСЭМ, НР/СП, коэффициентов и финальности;
- запрет case-specific steering, скрытого selector и кодового улучшения решения модели.

### 7.3. Активный prompt документного mapping-agent

Ниже — полный текст исполняемой фазы на дату паспорта; канонический редактируемый источник остаётся в
`skills/smeta/references/document-mapping-agent.md`.

```text
# Document mapping agent

Ты — сметчик, который принимает профессиональные решения по текущему пакету `work_items`.
Этот файл — рабочая фаза канонического `skills/smeta/SKILL.md`; Python не выбирает нормы,
аналоги, coverage, ресурсы или решение строки.

## Задача

Для каждого переданного `work_id` самостоятельно принять ровно одно решение:

- `bind` — выбранная открытая карточка нормы применима как точная норма или защищаемый аналог;
- `covered_by` — операция доказанно входит в состав другой выбранной строки пакета;
- `unbound` — защищаемой нормы или покрытия после осмысленной проверки нет.

Отсутствие региона, периода или цены не мешает завершить mapping. Это замечания последующего
расчёта, а не повод продолжать подбор или останавливать весь пакет.

## Работа с evidence tools

Сначала `browse_norm_catalog` показывает семейства и сборники текущей typed-базы. После списка
семейств повторно открой выбранное семейство, выбери сборники и выполни первый `search_norms_batch`
с `base_types`/`collections`. Общий поиск допустим как последующее расширение recall. Каталог не
является поиском нормы и не может быть основанием для terminal-решения.

`search_norms_batch` ищет кандидатов, `read_norms_batch` раскрывает typed-карточки. Все доступные
tools можно вызывать повторно и пакетно; порядок и достаточность доказательств определяешь ты.
Каждый поиск содержит `search_intent`: `source_literal`, `fsnb_technology`, `key_operation`,
`equipment_or_measure` или `composite_coverage`; перестановка слов не считается новой стратегией.
Поисковая карточка показывает семейство, редакцию, сборник, измеритель и его совместимость, несколько
операций, ресурсный профиль, `matched_query` и источник. Поэтому модель видит, почему кандидат попал
в меню, не получая от кода готового вывода о применимости.

Для `bind` обязательно открой выбранную карточку и проверь назначение, операцию, измеритель,
состав работ, очевидные чужие ресурсы и пересечения с соседними строками. Совпадение названия или
единицы само по себе не доказывает применимость. Для аналога явно сохрани ограничения и нужные
`add|replace|exclude|reuse` ресурсные действия.
В `candidate_evaluations` сохрани оценку выбранной карточки. Если поиск показал несколько карточек,
открой и сравни выбранную минимум с одной отклонённой или спорной. Эта таблица живёт во внутренней trace;
Python проверяет только форму и факт открытия карточек.

Для `unbound` выполни минимум две разные осмысленные формулировки поиска: исходную и на языке ФСНБ.
Открой технологически близкие карточки, если они найдены, и зафиксируй конкретные причины отказа и
проверку `covered_by`/декомпозиции. `has_more` не требует листать страницы. После двух содержательных
поисков и проверки близких карточек прими решение; не повторяй перестановки тех же слов и не ищи
бесконечно.
Если terminal отклонил `unbound_evidence`, модель использует фактические `allowed_evidence`, не
придумывая отсутствующие запросы или открытые карточки.

`covered_by` допустим только когда состав работ открытой нормы другой строки действительно включает
операцию. Соседство строк и похожее название не являются покрытием.

При `review_phase=global_cross_row_review` та же модель проверяет всю ВОР, открытые карточки и
предъявленные кодом конфликты: forward/backward coverage, дубли работ/ресурсов, направление операции
и exact/analog. В контекст передаются компактные карточки без полного списка ресурсов; спорная норма
повторно открывается через `read_norms_batch`. Новое решение остаётся модельным и создаёт отдельную
immutable revision.

## Завершение

Когда решения по всем `work_id` готовы и среди объявленных tools есть `submit_lsr_mapping`, вызови
его и передай решения всех строк. Если transport не объявил этот terminal tool, заверши evidence
loop обычным текстом: ЛЕС сразу запросит у тебя те же решения отдельным JSON Schema mapping. В этом
структурированном ответе не меняй уже принятое решение. Если доказательств недостаточно, верни
собственный `unbound`, а не продолжай поиск ради видимости полноты.
Если Qwen-Agent завершил обычным текстом, ЛЕС может повторно предъявить той же модели и истории
короткое требование terminal serialization без нового исследования.

Tool loop имеет технический бюджет времени/ходов. Это не лимит кандидатов и не выбор кода: на его
границе ты сама фиксируешь решения по уже собранным доказательствам, включая `unbound` там, где
защищаемого решения нет.

Код после mapping проверяет ссылочную целостность/единицы/provenance, выявляет противоречия, считает
и формирует черновой XLSX. Он не заменяет и не улучшает профессиональные решения. Финальная ЛСР
считается только после явного пользовательского `mapping_locked`.
```

### 7.4. Машинный role pack

`smeta_agent_v2` задаёт типизированные перечисления, но не отвечает вместо модели:

- modes: `estimate`, `candidate_review`, `continue_reviewed`;
- mapping: `candidates_ready`, `mapping_selected`, `mapping_globally_reviewed`,
  `mapping_user_reviewed`, `mapping_locked`;
- pricing: `unpriced`, `priced_partial`, `priced_draft`, `priced_final`;
- relationships: `alternative`, `complementary`, `partial_coverage`, `covered_by`;
- applicability: `exact`, `close_analog`, `weak_analog`, `not_applicable`;
- pricing basis: `norm`, `analog_norm`, `commercial_offer`, `calculation`;
- quantity origin: `source_explicit`, `source_calculated`, `user_provided`, `inferred`, `missing`.

Ключевые invariants role pack: `continue_reviewed` требует `mapping_locked`; код не ставит lock молча;
inferred quantity блокирует final; missing price не равна нулю; комбинации кандидатов создаёт модель,
а не декартово произведение в Python.

## 8. Нормативное хранилище

### Typed SQLite — расчётная истина

Активная база задаётся `config/domain/smeta_base_active.json`:

```text
edition: FSNB-2022
base: data/smeta_base/les_smeta_base.sqlite
source: data/gesn_base/gesn2022_unified.parquet
manifest + integrity: рядом с SQLite
minimum_norms: 40000
navigation collection: les_smeta_norm_cards
embedding: qwen3-embedding-0.6b
```

Основные таблицы: `norms`, `resources`, `norms_fts`. Ресурс связан с нормой через
`parent_norm_id + norm_key`. Идентичность нормы:

```text
norm_key = base_type:bare_code
пример: ГЭСНм:08-02-420-01
```

Одинаковый цифровой хвост ГЭСН и ГЭСНм — разные нормы.

### Qdrant и FTS — навигация

Production retrieval для индексируемых dataset использует named dense + BM25 sparse, native RRF,
общий rerank и parent/context expansion. В сметах выбранная карточка всегда повторно читается из
Typed SQLite. Несовпадение collection/fingerprint/SHA отключает dense и честно оставляет sparse-only;
payload Qdrant не становится нормативной истиной.

## 9. ФГИС ЦС: что и как скачивается

Для публичного скачивания не нужен пользовательский API key. LES обращается к открытым metadata/file
endpoint ФГИС ЦС. У ФГИС нет используемого LES per-code price API: доказанный источник цены —
скачанный файл «Сплит-форма» для ценовой зоны и периода.

Полный updater:

```text
public catalog subjects → price zones → periods
  → latest split form для каждой зоны (или all periods явно)
  → XLSX parse по заголовку «Код ресурса»
  → normalized Parquet price books
  → загрузка/обновление ГЭСН и ресурсов ФСНБ
  → unified typed Parquet
  → integrity-checked SQLite
  → service RAG projection
```

Точки входа:

- `POST /api/service-sources/fgis/update` — старт фоновой задачи;
- `GET /api/service-sources/fgis/update/status` — stage, heartbeat, bytes, rate, ETA и layers;
- `tools/fgis_full_update.py` — оркестратор;
- `proxy/services/fgis_price_fetch_service.py` — публичный catalog/download;
- `proxy/services/fgis_price_service.py` — exact lookup локальной книги;
- `tools/gesn_update_from_fgis.py` — нормативный слой;
- `tools/gesn_unify_base.py` и `tools/build_smeta_structured_base.py` — сборка typed-базы.

Price lookup нормализует код и делает точное совпадение. Текущая эффективная цена берётся из явной
текущей колонки, а при её отсутствии считается как базовая цена × индекс группы. Если кода нет,
строка уходит в price gap/КАЦ, а не получает похожую цену.

Updater checkpointed и restart-safe по книгам, пишет атомарный status/manifest и не активирует
структурную базу до integrity gate. GUI показывает отдельные стадии: baseline, catalog, price books,
GESN, unify, structured, service RAG.

## 10. Расчёт

Количество:

```text
norm_quantity = source_quantity × unit_conversion_factor
resource_quantity = norm_quantity × per_unit × quantity_coefficient
```

Исходное количество входит один раз. `unit_conversion_factor` только переводит единицу ВОР в
измеритель нормы; старый двусмысленный `quantity_multiplier` запрещён.

Ресурсы модели:

| Action | Эффект |
|---|---|
| `add` | добавить проектный ресурс |
| `replace` | заменить ресурс нормы |
| `exclude` | исключить неприменимый ресурс |
| `reuse` | сохранить физический ресурс без новой покупки |

Деньги:

```text
ОТ      = труд рабочих
ЭМ      = эксплуатация машин без оплаты машинистов
ОТм     = труд машинистов по ФСЭМ
М       = материалы и оборудование
Прямые  = ОТ + ЭМ + ОТм + М
ФОТ     = ОТ + ОТм
НР      = ФОТ × норматив НР
СП      = ФОТ × норматив СП
Позиция = Прямые + НР + СП
НДС     = итог без НДС × 22%
```

ФОТ — база НР/СП и второй раз в итог не прибавляется. Отсутствующая цена — `null`; известная часть
остаётся видимой, но полный итог не объявляется.

## 11. UI, progress и артефакты

Backend SSE:

| Event | Назначение |
|---|---|
| `smeta_step` | этап workflow/model/tool/retrieval и heartbeat |
| `smeta_batch` | legacy/ordinary batch telemetry |
| `smeta_row` | terminal модельное решение готовой строки |
| `final` | авторитетный response payload и artifact |
| `error` | честная ошибка без второго дорогого запуска |

Совушка хранит готовые строки по `work_id` и перерисовывает компактную Markdown-таблицу: номер,
работа, объём, решение/код нормы. Числа используют tabular numerals; таблица имеет bounded height и
скролл, поэтому длинная ВОР не растягивает чат бесконечно.

Черновой XLSX строится по последней завершённой модельной ревизии; финальный — только по отдельной
пользовательской lock-ревизии. Предыдущие решения не скрываются. Лист
«Проверка» содержит исходную строку, выбранную норму, применимость/аналог, причину, ресурсные действия,
blockers и источники.

## 12. Конфигурация

| Переменная | Смысл | Default |
|---|---|---|
| `LES_SMETA_AGENT_ENGINE` | `native|qwen_agent|google_adk` | `native` |
| `LES_SMETA_QWEN_MODEL` | локальная модель Qwen-Agent | `qwen3.5:9b` |
| `OLLAMA_BASE_URL` | Ollama для Qwen-Agent | `http://127.0.0.1:11434` |
| `LES_SMETA_GOOGLE_MODEL` | Google ADK model | `gemini-3.5-flash` |
| `GOOGLE_API_KEY` | ключ Google ADK | отсутствует, fail-closed |
| `LES_CLOUD_CONSENT` | явное согласие на cloud source | false |
| `LES_SMETA_DOCUMENT_BATCH_SIZE` | строк на transport task | Qwen 1, native local 10, cloud 0 |
| `LES_SMETA_DOCUMENT_MAX_TOOL_TURNS` | модельных ходов на task | local 10, cloud 64 |
| `LES_SMETA_SEARCH_BUDGET` / `LES_SMETA_READ_BUDGET` | отдельные evidence tool-вызовы | 4 / 4 |
| `LES_SMETA_OPENED_CARD_BUDGET` | максимум открытых карточек на task | 12 |
| `LES_SMETA_TASK_TIME_BUDGET_SEC` | wall-time evidence task | 180 |
| `LES_SMETA_DOCUMENT_PROVIDER` | provider native document model | runtime config |

Qwen-Agent использует Ollama OpenAI-compatible `/v1`, `use_raw_api=true`, context 32K,
`reasoning_effort=none`. Framework владеет function loop; Ollama сериализует declared tool calls.
Скрытого перехода Qwen→native или Google→local нет.

## 13. Отказы и честные состояния

| Ситуация | Поведение |
|---|---|
| файл не распознан как ВОР | fail до расчёта, исходник остаётся для повтора |
| model/tool transport упал | explicit error, без профессионального fallback |
| строка не закрыта | `unbound`, причина и evidence сохраняются |
| карточка не открыта | model decision сохраняется, строка получает blocker |
| единица несовместима | строка блокируется для расчёта, соседние считаются |
| цены нет | `null`, price gap/КАЦ, partial total |
| ФГИС/SQLite integrity не пройден | новая база не активируется |
| пользователь остановил диалог | cooperative cancellation между model/tool ходами |
| SSE оборвался после токенов | показывается неполный ответ и ошибка, повтор не запускается молча |

## 14. Тестирование

Последовательный Qwen quick gate:

```bash
uv run python tools/smeta_agent_benchmark.py <ВОР.xlsx> \
  --engine qwen_agent --phase quick --batch-size 1
```

Полная ВОР:

```bash
uv run python tools/smeta_agent_benchmark.py <ВОР.xlsx> \
  --engine qwen_agent --phase full --batch-size 1
```

Benchmark хранит dataset-specific проверки только в tool, не в production skill или коде. Созданный
XLSX сам по себе не означает профессиональную приёмку: проверяются нормы, coverage, открытые карточки,
ресурсы и итоговая полнота.

Регрессионные гейты:

```bash
uv run pytest tests/test_smeta_core.py tests/test_smeta_agent_runners.py \
  tests/test_smeta_chat_application_service.py tests/test_sovushka_chat.py
make verify
make test
```

После изменения retrieval/router дополнительно:

```bash
uv run python tools/rag_golden_set.py --cases golden/domain_fire_hvac_set.json
```

## 15. Точки входа в код

| Область | Файл |
|---|---|
| intake PDF/XLSX | `proxy/smeta_core/source_intake.py` |
| model/tool workflow | `proxy/smeta_core/document_workflow.py` |
| runner adapters | `proxy/services/smeta_agent_runner_service.py` |
| chat application | `proxy/services/smeta_chat_application_service.py` |
| transport/native adapters | `proxy/services/smeta_chat_adapter_service.py` |
| prompt/role pack assembly | `proxy/services/prompt_registry_service.py` |
| norm retrieval | `proxy/smeta_core/norm_browser.py` |
| typed contracts | `proxy/smeta_core/contracts.py` |
| integrity | `proxy/smeta_core/integrity.py` |
| calculator | `proxy/smeta_core/calculator.py` |
| RIM trace | `proxy/services/rim_lsr_trace_service.py` |
| XLSX | `proxy/services/rim_trace_xlsx_service.py` |
| FGIS update | `tools/fgis_full_update.py`, `proxy/services/fgis_update_service.py` |
| FGIS prices | `proxy/services/fgis_price_fetch_service.py`, `fgis_price_service.py` |
| UI | `sovushka/pages/chat.py`, `sovushka/styles.py` |
| benchmark | `tools/smeta_agent_benchmark.py` |

## 16. Неподвижные правила

1. Модель отвечает за профессиональное решение; код отвечает за вычисление и техническую проверку.
2. Ranking, exact hit и цена не являются автоматическим выбором нормы.
3. Typed SQLite — расчётная истина; Qdrant/FTS — навигация.
4. Первичный mapping immutable; обязательный cross-row review и пользовательский lock создают новые ревизии.
5. Количество исходника применяется один раз.
6. Missing не превращается в zero.
7. Незакрытая строка не скрывает рассчитанные строки.
8. Skill является единственным предметным контрактом; case-specific prompt-патчи запрещены.
9. ФГИС активируется только после build→integrity→activate.
10. Production default не меняется по факту технически завершившегося XLSX — нужен профессиональный gate.

## 17. Текущие ограничения и TODO

- Qwen 9B доказал техническую способность завершать tool loop, но ещё не прошёл полный
  профессиональный gate на актуальной цельной базе ФГИС/ФСНБ; поэтому production default — `native`.
- Изолированный live-probe `vor-0013` подтвердил путь `5 семейств → 47 сборников ГЭСН → сборник 15
  → scoped search → read → bind`: прежний уверенный выбор специализированного сборника 34 исчез.
  Проверка одной строки не заменяет six-row/full golden-гейт.
- Последовательный loop передаёт прошлые решения следующей строке; затем workflow обязательно запускает
  глобальный пересмотр той же моделью. Не закрыта профессиональная приёмка на экспертном golden-наборе
  100–300 строк: runtime уже считает wrong bind/unbound/coverage/unopened-card/unit/resource/price metrics,
  но экспертные эталоны нельзя сгенерировать кодом. `tools/smeta_mapping_quality.py --prepare-from
  <mapping.json> --out <expert.json>` создаёт очередь разметки со статусом `needs_expert_review` и
  отделяет предложение модели от будущей экспертной истины; scorer отказывается считать непроверенные строки.
- Качество результата зависит от полноты Typed SQLite, ФСЭМ и региональных price books. Missing слой
  должен давать partial, а не правдоподобную выдуманную сумму.
- Живой UI следует проверять после deploy: branch-правка не обновляет запущенный runtime автоматически.
