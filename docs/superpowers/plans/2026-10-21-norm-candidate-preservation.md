# Сохранение кандидатов норм до повторного ранжирования — Implementation Plan

> **For agentic workers:** execute task-by-task with the available systematic-debugging, test-driven-development and verification-before-completion skills. Subagents audit source only; ROOT serially owns tests and live calls.

**Goal:** устранить измеренную техническую потерю найденных карточек до reranker и проверить влияние на разные запросы и доставленные документы.

**Architecture:** модельные запросы остаются буквальными. Dedicated native dense+sparse RRF и exact typed/FTS сохраняют прежние каналы; до rerank передаётся их полный ограниченный union. Видимый topK применяется после ранжирования. Расчёт, нормы, решения модели и пользовательские данные не переписываются.

**Tech Stack:** существующие Python/Qdrant/bge-m3/local cross-encoder, uv/pytest; без новых зависимостей.

**Spec:** `AGENTS.md`, `SKILL.md`, `docs/modules/rag-evidence-flow.md`; измеренный baseline — `artifacts/retrieval_977/stages02_installed_python`.

## Global Constraints

- Не изменять запросы модели, профессиональные решения и source scope.
- Не добавлять dataset/case-specific boosts, зависимости или скрытые факторы.
- Не изменять индексы/БД/manifest и не выполнять полный реиндекс.
- Метаданные fingerprint/generation не считать причиной плохой выдачи без отдельного доказательства.
- Offline checks не заменяют installed baseline → candidate → rollback и проверку документов.

## Review Focus

- Маленький visible limit не должен уменьшать доступный reranker pool.
- Непересекающиеся typed/native списки не теряют хвост при объединении.
- Общие карточки не дублируются; identity и фильтры сохраняются.
- Disabled/failed reranker сохраняет детерминированный retrieval fallback.
- Увеличение CE pool ограничено и измеряется по времени; рост recall не равен точности применения норм.

### Task 1: сохранный ограниченный pool

**Files:** `proxy/smeta_core/norm_browser.py`, `tests/test_smeta_norm_browser.py`.

**Interfaces:** `browse_norms_many` сохраняет сигнатуру, visible cap50 и literal query; `_rerank_cards` получает неусечённый union двух каналов, каждый не более50.

- [x] Добавить generic regression: native tail, который исходный outer cap удалял, достигает reranker и может попасть в выдачу; limits6/50 используют одинаковый pool.
- [x] ROOT запускает тест до правки и сохраняет RED.
- [x] Отвязать retrieval pool от visible topK; убрать outer cap, оставив dedup/RRF и общий bounded input.
- [x] ROOT запускает focused related tests, проверяет fallback/dedup/filters и literal query.

### Task 2: проверка эффекта и ограничений

**Files:** существующие `tools/smeta_rag_quality_probe.py`, `tools/smeta_retrieval_recall_probe.py`, `tools/smeta_rerank_ab_probe.py` — сначала проверить возможность переиспользования. Доказательства сохранять в новом неизменяемом `artifacts/retrieval_978/`.

- [x] Повторить те же literal запросы с тем же индексом/embedder/reranker; сохранить pool, visible result, timings и source SHA.
- [x] По cached8-query контролю проверить следующий seam:20из48CE-head теряются при повторном RRF. Generic RED3 → убрать повторную fusion, сохранить measured CE-order/input fallback; related78passed. Повторный source comparison выполняется.
- [x] Comparison02:8queries, RAG/CE ok, inputs unchanged; cost71.063→183.911s. Качество cable/primer остаётся OPEN; bigger pool не принят за90%.
- [x] Versioned smeta query cachev2: старые empty/card не маскируют новый authored поиск; superseded/accepted сохранены. Finite команды добора используют gap queue только при известной LSR, после VOR остаются remark. RED cache5/gap3/kind6 → related111passed.
- [ ] Проверить разные разделы и независимые запросы; не объявлять найденный шифр применимым без данных о технологии/измерителе.
- [ ] Если качества недостаточно, определить следующий первый сломанный переход по фактам, без новых orchestration loops.
- [ ] Согласованно обновить версию, MODULE_INDEX/module doc/ledger и test inventory; выполнить канонические gates.
- [ ] Только после gate собрать exact installer и проверить установленный baseline/candidate/rollback и обычные ВОР/ЛСР. Customer-ready только по доставленным проверенным документам.

### Измеренная граница 978 и два следующих исправления

Коммит `22f577d1`: canonical verify/test/updater/public и сборка exact installer прошли
(6956 passed / 20 skipped; updater328 passed). Установка не принята: изолированный
оператор не передал Windows USERNAME, поэтому desktop restart и restart после
rollback отказали. Прежний976 восстановлен, API подтвердил aligned98. Receipt и
неудачная попытка неизменны;978 не объявляется установленным или готовым.

Свежий обычный baseline976 (`artifacts/live_978/baseline976_ordinary01`) доставил
7 строк за312.781s,5model calls, но0complete/0confirmed. Книга цен сохранена.
Два воспроизводимых технических дефекта следующей узкой правки:

- [x] RED4 → unresolved role с открытым решением не исчезает из research IDs.
  Возвращать модели вопрос о роли и норме, не назначать work и не менять её решение.
  Нулевой объём, подтверждённое покрытие, закрытые соседи, evidence/cache/pricebasis
  и CAS сохраняются.
- [x] RED3/2fallback passed → upgrade preview/full не повторяет их точный общий leading-line prefix.
  Исходный preview сохраняется; полный typed body восстанавливается байт-в-байт из
  общего prefix и добавленного suffix. Все отличающиеся сведения и ресурсы сохраняются.
  Живой trace:11upgrades,12309повторных символов, из них5009НР/СП; initial answer60016tokens.
  ROOT related270passed/12.44s; установленная проверка ещё не выполнена.
- [ ] Focused related gates, независимый review, version/docs/ledger/map, canonical
  gates и exact artifact acceptance с исправленным окружением оператора.
- [ ] Установленный candidate и direct baseline на тех же source/question/profile/
  connection; скачанный файл и добор незакрытых решений. Качество и производительность
  измерять отдельно. Полное покрытие и90% точности по этим seam-тестам не заявлять.
