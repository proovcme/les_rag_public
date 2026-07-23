# Аудит RAG и план стабилизации

Дата среза: 2026-07-23  
Базовая ветка: `public/main`, commit `ef8389ab4aa906c634b9fd0b270fbe4b4fd7134a`  
Источник безопасной синхронизации: `proovcme/les_rag`, `main`, commit
`9af71346e72489efb9e8a1ff8fda4ad88986ff56`

## Вердикт

RAG в исходном `public/main` — работающий переходный контур, но не стабильная
командная реализация заявленного в README договора. Dense-поиск хранится в
основной коллекции без имени вектора, sparse-поиск — в отдельной sidecar-коллекции,
а RRF выполняется в приложении. Sparse выключен по умолчанию и при сбое молча
заменяется SQLite FTS. Это расходится с публично заявленным инвариантом
`dense + bm25_sparse` в одной contract-versioned коллекции с native Qdrant RRF.

В этой ветке безопасные актуальные реализации и тесты перенесены из private:

- единая коллекция с named-векторами `dense` и `bm25_sparse`;
- native Qdrant `Fusion.RRF`;
- проверка схемы коллекции и embedding fingerprint;
- read-only readiness, аудит индекса и управляемая сборка новой генерации;
- общий rerank и parent/context expansion поверх гибридного пула;
- явный диагностический fallback для legacy-контура вместо притворной готовности.

После переноса узкий offline-гейт даёт `105 passed`. Живой Qdrant и реальный
корпус в рамках этой ветки не проверялись, поэтому статус — **release candidate
для кода, но не подтверждённый stable runtime**.

## Что было в public/main

Сильные стороны:

- FastAPI/Qdrant-контур, маршрутизация по dataset/document scope;
- dense retrieval, lexical FTS, sparse sidecar, RRF и cross-encoder rerank;
- восстановление соседнего/родительского контекста;
- 2191 тест собрался без import errors;
- `publication_check` и Python compileall прошли.

Блокеры стабильности:

1. README описывает единый named-vector контракт, а код создаёт unnamed dense
   коллекцию и отдельный sparse sidecar.
2. `RAG_SPARSE_ENABLED=false` по умолчанию; ошибка sparse превращается в
   dense+FTS без hard readiness gate.
3. Нет обязательной проверки fingerprint/schema перед поиском и нет атомарного
   переключения поколения индекса.
4. В baseline-проверке RAG было `5 failed, 39 passed`: parse-тесты отстали от
   lexical cleanup path.
5. В public отсутствовали readiness/audit/supervisor tools, которыми команда
   может доказать готовность, а не только увидеть HTTP 200.
6. Полный живой golden gate нельзя воспроизвести без собственного разрешённого
   корпуса; данные и snapshots правильно не публикуются.

## Что добавлено в этой ветке

- Актуализированы adapter, retrieval, converter/interface и связанные сервисы.
- Добавлены `rag_readiness_service`, contract audit, RRF readiness и generation
  supervisor.
- Добавлены проверки layout, fingerprint, native RRF и качества retrieval.
- Удалён отдельный `reindex_sparse_bge_m3.py`: целевой контракт больше не
  поддерживает sparse sidecar как нормальное состояние.
- Перенесены только tracked source/tests. Runtime data, `.env`, базы, индексы,
  логи и ключи не переносились.

## Определение stable

RAG можно считать стабильным, когда одновременно выполнено следующее:

- каждый новый dataset индексируется в одну named-vector коллекцию;
- readiness подтверждает dense, sparse, fingerprint, payload contract и alias;
- production retrieval использует native RRF, затем общий rerank и context
  expansion;
- legacy fallback виден оператору как degraded и не считается зелёным релизом;
- переиндексация строит sibling generation и переключает alias только после
  аудита;
- fresh clone собирается по публичной инструкции;
- offline tests зелёные, domain golden gate проходит полностью;
- Windows/Ollama и macOS reference smoke дают одинаковый retrieval contract;
- ответ содержит проверяемые source coordinates, а navigation map не выдаётся
  за evidence.

## План до стабильного

### P0 — командная воспроизводимость и честный контракт

1. Слить эту ветку и удалить все оставшиеся sidecar-defaults из конфигурации и
   документации.
2. Подтянуть в public общие `AGENTS.md`, `SKILL.md`, module/code/test maps и
   version ledger после синхронизации остальных трёх контуров.
3. Добавить CI для `compileall`, collect-only, RAG unit tests и
   `publication_check`.
4. Зафиксировать одну команду fresh-install и пустой demo corpus с разрешёнными
   материалами.

Критерий выхода: чистый clone собирается; layout/fingerprint tests зелёные;
readiness на пустом корпусе честно возвращает `empty`, а не `ready`.

### P1 — миграция и эксплуатация

1. На тестовом Qdrant построить sibling generation через supervisor.
2. Прогнать contract audit, golden set и live RRF probe.
3. Переключить alias только после полного зелёного отчёта; сохранить откат на
   предыдущее поколение.
4. Вывести readiness/degraded reason в UI и diagnostics API.

Критерий выхода: restart не меняет результат; отказ sparse/rerank виден;
переключение поколения и rollback воспроизводимы.

### P2 — качество и производительность

1. Утвердить публичный обезличенный golden corpus по документам, таблицам,
   точным кодам и нормативным пунктам.
2. Замерить recall@k, MRR/nDCG, citation precision, p50/p95 latency и память.
3. Добавить Windows/Ollama и macOS smoke в release gate.
4. Запретить merge при регрессии golden floor или contract audit.

Критерий выхода: согласованные пороги проходят на двух целевых платформах три
последовательных прогона.

## Риски и границы

- Эта ветка не переносит приватные документы или готовый индекс.
- Живой runtime не изменялся.
- Readiness включает smeta-срез, но его полный тест должен войти вместе со
  smeta-core в отдельной ветке.
- Версия public должна быть поднята один раз в интеграционном merge после
  согласования всех четырёх PR, чтобы не создавать четыре конфликтующих версии.
