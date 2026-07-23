# Аудит тестовой программы RAG

Дата: 2026-07-10. Версия кода: `0.24.0.352`.

## Вердикт

До повторного аудита тестовая программа давала ложную уверенность: **4/10**. Главная причина —
live golden проверял `/api/rag/retrieve-debug`, а endpoint дописывал ожидаемые FIRE/HVAC слова.
Зелёный `16/16` не являлся доказательством retrieval quality.

После исправлений базовый инженерный контур оценивается в **7/10**: offline integrity-гейт ловит
подмену debug, несовместимый index contract, oversize/base64 chunks, смешение score scales,
смену backend при retry, непрозрачный rerank, рассинхрон source map и неправильные citation labels.
До production-quality остаются чистые source-verified goldens и реальные canary трёх проектных/нормативных корпусов; тестовый сметный dataset удалён.

## Найдено и исправлено

- Удалены expected-term вставки из debug; добавлены негативные тесты на прежние три подмены.
- Golden `must_find` проверяется только в content, не в имени файла; по умолчанию все ожидаемые
  термины должны находиться в одном retrieved chunk, а не быть размазаны по случайным источникам.
- Tokenizer в config/health/tests работает `local_files_only`; unit suite больше не ждёт сеть/HF.
- `tests/conftest.py` фиксирует offline defaults до импорта приложения.
- `make test-rag-core` стал отдельным обязательным гейтом и включён в `ship-check`; прежний
  `FOCUS_TESTS` был сметно/UI-центричным и мог пропустить регрессию RAG-ядра.
- Полный pytest показывает 20 самых медленных тестов, чтобы зависание не оставалось без следа.

## Уровни проверки

1. `make verify` — только syntax/import/collection. Не является проверкой поведения.
2. `make test-rag-core` — детерминированные offline-инварианты RAG.
3. `make test` — общая регрессия проекта и отчёт медленных тестов.
4. `make smoke-basic` — живые HTTP/runtime пути с конечными timeout.
5. `tools/rag_golden_set.py` — только после deploy чистого debug endpoint; factual cases должны
   иметь вручную проверенный первоисточник.
6. Canary BAI, ПД ИЦ, FIRE, сметы — обзор корпуса, targeted read, citations, missing/coverage.

## Незакрытые риски

- Существующие FIRE/HVAC результаты аннулированы; чистый baseline ещё не получен.
- Golden cases пока не хранят обязательный reviewer/source-page provenance.
- Часть общей сюиты зависит от локальных runtime-файлов и skipif; это не переносимый CI.
- Автоматического CI нет.
- `make verify` только собирает тесты и не должен называться quality gate без `test-rag-core`.
- Общего per-test timeout пока нет; зависания обнаруживаются full-suite/run-level наблюдением.
- Некоторые модули читают репозиторный `.env` при импорте; offline defaults закрывают модельную
  сеть, но полная hermetic-конфигурация потребует переноса `load_dotenv` на app bootstrap.
- Full run после RAG-правок: `2733 passed / 16 failed`; 14 падений оказались stale tests старого
  unified-final flag и после актуализации прошли focused `81 passed`. Остались два сметных
  finality failure (`test_direct_mass_*`), не относящиеся к RAG-core.

Операционная очередь находится в [TODO_EVIDENCE_CORE.md](TODO_EVIDENCE_CORE.md).

## Проверка активной коллекции

Read-only sample `1000` points активной `les_rag_qwen3_06b_native_v1` выявил пять fingerprints:
`672/146/128/53/1`. В payload смешаны Core ML Qwen с seq_len `512/1024`, разные compute/fallback,
sentence-transformers Qwen и одна точка без model id. Полей нового final token/sanitation gate нет.
Это запрещает слепое создание manifest поверх старой коллекции; нужен sibling canary index.

## Contract-clean sibling canary

`tools/build_rag_contract_sibling.py` проверяет отдельный, не production, индекс без копирования
старых vectors. После удаления test-only TABLE_SMETA bounded run содержит BAI, ПД ИЦ и FIRE:
`397/297/278`, всего `972` clean points. `rag_index_contract_audit` подтвердил один Qwen/Core ML
fingerprint и `972/972` покрытие token-budget/sanitation metadata. Прямой filtered dense
retrieval вернул 3/3 chunks для каждого из трёх scopes.

Это integrity/canary gate, не golden качества ответа. Сметные module cards перенесены в отдельную
системную сущность `SMETA_SERVICE_Index`; бывший `TABLE_SMETA_Index` содержал только тестовые
ВОР/CSV и generated service navigation, поэтому удалён из runtime, active/canary Qdrant, FTS и storage.
