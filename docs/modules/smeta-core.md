# Smeta Core — единое сметное ядро

> **Статус 2026-07-14: ✅ код и документ синхронизированы.** Канонический PDF→ЛСР путь — один
> model-owned batch-диалог и один расчёт. Старый поштучный оркестратор физически удалён.

## Архитектурная граница

```text
исходник / ВОР / спецификация
  → source_intake: строки, количества, единицы, координаты
  → модель + smeta skill
  → search_norms_batch: RRF dense+sparse, только кандидаты
  → read_norms_batch: фактические карточки Typed SQLite
  → submit_lsr_mapping: решения модели по всем строкам
  → calculator: единицы, ресурсы, цены, РИМ, НР/СП, НДС
  → formula XLSX + журнал проверки + короткий ответ
```

Модель выбирает работы, декомпозицию, запросы, нормы, аналоги, coverage и ресурсные действия
`add|replace|exclude|reuse`. Код не выбирает и не переписывает профессиональное решение. Он может
отклонить только технически несостоятельную ссылку: неизвестный `work_id`, дубликат, неоткрытую
карточку нормы, битую единицу или неполный mapping. Для `bind` полнота mapping теперь означает
структурированное сопоставление операций/условий/ресурсов и межстрочных пересечений. Код проверяет
наличие этих полей и согласованность exact/analog, но не оценивает их профессиональное содержание.

Отдельных обязательных resource-review, impact-review, dominant-review и
`finish_norm_selection` нет. После полного `submit_lsr_mapping` выполняется один расчёт без нового
обращения к модели.

## Точки входа

- `proxy.smeta_core.application` — единственная публичная application-граница смет: model-first
  workflow, расчёт уже принятых решений, immutable revision и finality.
- `proxy.smeta_core.document_workflow.run_vor_pdf_workflow` — zero-state PDF→ЛСР.
- `proxy.smeta_core.document_workflow._run_batch_norm_agent` — тонкий tool-loop модели.
- `proxy.services.smeta_chat_application_service` — application flows ordinary smeta и PDF→ЛСР:
  безопасно открывает одноразовое вложение, координирует RAG/model/progress, сохраняет artifact/trace
  и возвращает response envelope. Профессиональных решений не принимает.
- `proxy.services.smeta_chat_adapter_service` — smeta transport/RAG adapters, prompts и parsers:
  runtime провайдера, document exchange, evidence packet, model-owned lookup/choice и numeric audit.
  Router этих реализаций не содержит и не собирает их вручную.
- `proxy.smeta_core.norm_browser.browse_norms_many` — пакетный RRF-поиск.
- `proxy.smeta_core.calculator.calculate_visible_rows_revision` — один расчёт решения модели.
- `proxy.services.smeta_user_message_service` — человеческое сообщение из готовой summary.
- `proxy.routers.chat` — request context, вызов application flow и общий history/response contract.

`estimate_harness_service` временно исполняет старый tool-loop только за
`smeta_core.application`; это implementation adapter, а не самостоятельная точка входа.
`construction_harness_service` и `unified_construction_harness_service` помечены
`LEGACY_PRIVATE`, остаются feature-off для старых evidence-fixtures и не входят в сметный маршрут.
Их старый `gesn_expand` больше не выбирает первый candidate кодом: он останавливается на
model-visible candidate list.

## Инструменты модели

### `search_norms_batch`

Принимает любое число независимых `work_id` и поисковых формулировок. Одинаковые запросы
дедуплицируются, embedding/retrieval выполняются пакетно. Результаты не смешиваются между строками.
Score и порядок кандидатов не являются выбором нормы.

### `read_norms_batch`

Открывает выбранные карточки из Typed SQLite: идентичность, измеритель, состав работ, ресурсы и
источники. Норму нельзя связать со строкой, пока модель её не открыла.

### `submit_lsr_mapping`

Один раз передаёт решение по каждой исходной строке:

- `bind` — выбранная открытая норма, явные exact/analog и applicability, полный `technology_check`
  (совпавшие/отсутствующие/лишние операции, посторонние ресурсы, условия, пересечения и их разрешение)
  и массив ресурсных действий;
- `covered_by` — доказанное покрытие другой исходной строкой;
- `unbound` — модель осознанно оставила работу открытой.

Аналог без конкретных ограничений не проходит формальный контракт. Каждое
`add|replace|exclude|reuse` требует причины и `basis_ref` на норму, техчасть или проектный источник;
субъективное исключение ресурса не превращается в расчётное решение. Runtime skill требует от модели
не считать частичное технологическое совпадение exact и сверять выбранные нормы между строками, чтобы
подготовительные операции и слои не оплачивались дважды.

Число строк и поисковых ходов не зашито под один тестовый объект. Транспорт поддерживает минимум
50 строк тем же контрактом. `max_turns` — только аварийный предел сетевого диалога, по умолчанию 64,
а не профессиональный workflow.

## Нормативное хранилище и retrieval

Typed SQLite — расчётная истина. `norm_key = base_type:bare_code` отделяет одинаковые цифровые коды
разных семейств. Qdrant является навигационным sibling-индексом. Поиск использует dense+sparse и RRF;
при несовпадении fingerprint/контракта dense не маскируется как исправный.

Структура базы, формула количества и источники РИМ описаны в
[`skills/smeta/references/gesn-storage.md`](../../skills/smeta/references/gesn-storage.md).

## Количества и деньги

```text
norm_quantity = source_quantity × unit_conversion_factor
resource_quantity = norm_quantity × per_unit × quantity_coefficient
```

Исходное количество входит в расчёт один раз. `quantity_multiplier` в tool-контракте отсутствует.
Альтернативные представления одного трудового ресурса дедуплицируются до денег.

Missing price хранится как `null`, не как бесплатный ресурс. В частичной ЛСР показывается известная
рассчитанная часть, а в редактируемом XLSX ячейки цены и стоимости такого ресурса остаются пустыми.
Строка работы показывает официальное название нормы и через `/` фактическое описание исходной работы;
шапка явно называет ресурсно-индексный метод (РИМ). НДС задаётся параметром расчёта; для текущего
сценария используется 22%.

## Артефакт и история

Формульный XLSX, trace и download contract сохраняются вместе с сообщением. При открытии истории
Совушка должна восстановить карточку того же файла без повторного расчёта и без вызова модели.
Внешний ответ формируется отдельно от машинного JSON и не показывает служебные имена полей.

## Гейты

- `tests/test_smeta_core.py` — три инструмента, model-owned выбор, полный technology/resource evidence,
  50 строк, единицы и один расчёт.
- `tests/test_rim_trace_xlsx.py` — форма РИМ, официальное наименование и пустая missing price.
- `tests/test_smeta_prompt_freedom.py` — отсутствие объектных якорей и скрытого selector.
- `tests/test_prompt_registry_service.py` — runtime skill и prompt registry.
- `tests/test_specification_to_bor_contract.py` — model-owned декомпозиция и quantity trace.
- `make verify` и `make test` — релизный офлайн-гейт.

## Открытые долги

- Завершить integrity gate нормативной SQLite и полный ценовой контур ФГИС/ФСЭМ/КАЦ.
- Подтвердить новый batch-путь живым zero-state прогоном и качественным аудитом ЛСР.
- Завершить clean dense+sparse reindex общего RAG и только после гейтов переключить alias.

Эти долги влияют на качество/полноту денег, но не дают права возвращать кодовый выбор норм или
многоступенчатый оркестратор.
