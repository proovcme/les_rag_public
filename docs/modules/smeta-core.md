# Smeta Core — единое сметное ядро

## Граница ответственности

`proxy/smeta_core` не является сметчиком. Модель или пользователь создаёт `NormBinding`; код
проверяет source integrity, единицы и формальные ограничения, затем считает и сохраняет provenance.
`NormBinding(selected_by="code")` является ошибкой контракта.

Живой native-agent получает не отдельный несвязанный prompt, а компактную reference-карту из
`skills/smeta/references/gesn-storage.md`: идентичность нормы, схему `norms/resources`, роль typed
SQLite и hybrid sibling, формулу количеств и источники РИМ. Это инструкция навигации, не evidence.

## Текущий поток

```text
project/source evidence
  → одна задача модели + smeta skill + native RAG tools
  → batch search_norms (deduplicated embeddings + hybrid/RRF)
  → read_norm только для содержательной проверки
  → explicit model/user norm/coverage binding
  → legacy calculator adapter
  → smeta_workflow_result_v1
  → LSR / partial LSR / blockers
```

Для нового PDF-вложения действует отдельный zero-state вход:

```text
server-owned PDF attachment
  → lossless source_intake (rows + locators + source hash)
  → model-owned search/read/bind/covered/unbound loop без code-side selector
  → deterministic resources/RIM/tax calculation
  → first immutable trace + formula XLSX
  → optional resource/dominant audit
  → optional revised LSR
```

Точка входа — `proxy.smeta_core.document_workflow.run_vor_pdf_workflow`; чат вызывает её только
для явного smeta/ЛСР-запроса с server-issued `read_<id>`. Клиентский путь не является API.
Workflow не читает историю, старую ревизию или prepared decisions. `chat_attachment_service`
проверяет TTL, size и SHA-256; файл удаляется только после успешного артефакта.

Нормативный browse использует широкие независимые пулы typed SQLite FTS и dedicated
Qdrant dense+sparse и объединяет их RRF. Все `search_norms` одного ответа модели сначала
дедуплицируются и исполняются одним batch: embedding строится списком, Qdrant-запросы относятся
к своим query/work_id и затем раскладываются обратно по исходным tool calls. Для массового triage
single-query reranker откладывается; он включается на узком повторном поиске (до четырёх запросов),
но никогда не выбирает норму за модель. Qdrant считается
совместимым лишь при совпадении collection, embedding model и SHA-256 активной SQLite-базы в
`les_smeta_norm_rag_manifest.json`; иначе browse честно остаётся в lexical-only. Векторная
проекция содержит название, измеритель и состав работ, но не список случайных ресурсов нормы:
ресурсы возвращаются в `resource_preview` как evidence для проверки технологии и входят в
reranker-контекст, а не служат самостоятельным retrieval-якорем.

Количество имеет однозначную трассу: `source_quantity × unit_conversion_factor = norm_quantity`;
ресурс считается от `norm_quantity × consumption`. Поле `quantity_multiplier` удалено из binding/tool
contract. Для `8 шт`, `3,2 м² / 100 м²` и `160 м / 100 м` тестируются промежуточные значения
`8`, `0,032` и `1,6`. Незакрытая цена хранится как `null`; ноль допустим для `covered_by`.

Technology check и ограничения аналога могут сохраняться как решение модели и audit trace. Код не ищет
слова «сварка/кран», не отклоняет норму по ресурсам и не переписывает модельную ЛСР. Формальный bind
проверяет только открытый candidate, тип exact/analog, шифр, единицу, количество и source integrity.
`bind_norm` требует только показанную и открытую карточку, `decision=selected`, exact/analog и причину.
Расширенный technology JSON не является допуском к первой ЛСР; отрицательное решение оформляется
`leave_unbound` самой моделью.

Для денег отдельно хранятся `known_amount` и `full_amount`. Missing цена, нерешённый ФСЭМ/ОТм или
неподтверждённый ресурсный состав оставляют известную арифметическую часть, но делают полную стоимость
позиции и сметы `null`. В XLSX такая строка называется «Известная стоимость позиции», а общий итог —
«Известная рассчитанная часть».

Resource review и dominant review не вызываются до первой ЛСР. Они могут использовать те же поля, что
`ResourceBinding`, только в последующей ревизии. ФСЭМ зарегистрирован отдельным service source;
отсутствие его SQLite даёт построчный gap, но не отменяет первую рассчитанную часть.

## Архитектурный инвариант первой ЛСР

`run_vor_pdf_workflow` обязан после model-owned mapping вызвать calculator/XLSX напрямую. Функции
resource/dominant review не могут быть precondition этого вызова. Тест должен падать, если первый
workflow обращается к дополнительному reviewer или если tool contract требует component-review до денег.

## Пользовательский ответ

Машинный контракт и сообщение в чате разделены. `smeta_document_workflow_v2`, внутренние статусы,
blockers и trace остаются в payload и журнале проверки. `smeta_user_message_service` детерминированно
формирует один короткий русский абзац из готовой summary: покрытие строк, стоимость рассчитанной части
без НДС/с НДС и подготовленный Excel. Он не выбирает нормы, не меняет решения модели и не пересчитывает
суммы. В частичной смете известная сумма не называется общей стоимостью работ.

Точка входа auto-smeta: `proxy.smeta_core.workflow.run_smeta_workflow`. Старый
`estimate_harness_service` пока остаётся adapter и переносится по частям; обходные direct/artifact/API
пути перечислены в [TODO_SMETA_CORE.md](../TODO_SMETA_CORE.md).

## Integrity gate

Structured base доверяется только при наличии `data/smeta_base/les_smeta_base_integrity.json` с
`schema=les_smeta_base_integrity_v1`, `verdict=passed`, совпадающими SHA-256 source/base и нулевыми
failure counts для cross-family, orphan, duplicate-key и parent mismatch checks. SQLite/manifest
сам по себе не означает готовность.

Историческая SQLite без такого отчёта остаётся доступной для аудита/навигации, получает
`quarantined_blocking` и не может подтверждать `priced_final`.

## Статусы результата

- `evidence_status`: `supported | partial | blocked`.
- `calculation_status`: `complete | partial | unsafe_source | not_calculated`.
- `total_status` остаётся legacy-проекцией до завершения миграции.

Непроверенная сумма может быть показана только как черновик с `unsafe_source`; она не является
финальной стоимостью.
