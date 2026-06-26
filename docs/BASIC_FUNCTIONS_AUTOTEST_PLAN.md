# BASIC_FUNCTIONS_AUTOTEST_PLAN

# План автопроверки базовых функций ЛЕС

Дата: 2026-06-26.

Цель: закрыть класс ситуаций "тесты зелёные, а руками базовая функция не работает".
Этот план дополняет `make verify`: он проверяет не только импорт модулей, а минимальные
пользовательские сценарии продукта на живом runtime.

---

## 1. Что считаем базовой функцией

Базовая функция - это действие, которое пользователь ожидает от ЛЕС каждый день:

```text
открыть UI
увидеть версию и статус
задать вопрос
получить ответ или честный MISSING/BLOCKED
выбрать scope/project/dataset
увидеть источники
открыть/скопировать источник или понять, почему нельзя
скопировать ответ
остановить генерацию
посмотреть историю
проверить health/diagnostics
сделать безопасную операцию подготовки документов
```

Если одна из этих вещей ломается, это release blocker даже при зелёных unit-тестах.

---

## 2. Уровни проверки

### L0 - offline contract

Запускается всегда, без сервисов:

```bash
make verify
uv run python -m pytest tests/test_answer_render_v16.py tests/test_v020_deploy_stamp_ui.py -q
uv run python -m pytest tests/test_scope_model_v21.py tests/test_scope_clarification_v22.py -q
```

Проверяет:

```text
рендер answer/source/citation/copy
source chip не становится фейковой кнопкой без source_ref
mail snippet не раскрывает тело письма
version/deploy stamp не течёт секретами
scope model и clarification не ломаются
```

### L1 - live HTTP smoke

Запускается против живого proxy/UI/Qdrant, без браузера:

```bash
uv run python tools/runtime_smoke.py \
  --proxy-url http://127.0.0.1:8050 \
  --ui-url http://127.0.0.1:8051 \
  --qdrant-url http://127.0.0.1:6333 \
  --question "что такое ОЖР" \
  --question "расскажи про котельную на лесном 64"
```

Обязательные проверки L1:

```text
/api/health отвечает и статус не маскирует FAIL
/api/version содержит app/harness/deployed_commit/runtime_alignment
/api/status отвечает
/api/metrics отвечает
/api/diag отвечает или честно требует auth
/api/scope/options отвечает и содержит проекты/датасеты
/api/chat возвращает answer, status, trace/version_info
глоссарный запрос не требует проекта
проектный вопрос без scope даёт clarification/MISSING, а не мусорный ответ
```

### L2 - browser smoke

Запускается Playwright-ом по UI. Это главный слой против "руками лезет".

```bash
uv run --with playwright python tools/browser_smoke.py \
  --ui-url http://127.0.0.1:8051 \
  --trusted-local \
  --question "что такое ОЖР"
```

Обязательные проверки L2:

```text
страница /les открывается
виден runtime/version badge
виден статус health
виден чат
поле ввода активно
кнопка отправки активна
ответ появляется в UI
кнопка "Копировать" есть и кладёт текст в clipboard
кнопка "Стоп" появляется во время генерации и не ломает следующий вопрос
source chip/citation artifact отображается, если backend дал source_ref
"Открыть" работает или disabled с объяснением
MISSING/BLOCKED видны как отдельное состояние, а не спрятаны в тексте
```

### L3 - product journey smoke

Запускается после заметных изменений router/retrieval/UI/source operations.
Это короткий набор пользовательских маршрутов, не полный регресс.

```text
1. Системный статус
   открыть UI -> проверить version/health -> открыть diagnostics

2. Глоссарий
   спросить "что такое ОЖР" -> получить deterministic answer -> copy answer

3. Проектный вопрос без scope
   спросить "расскажи про котельную на лесном 64" в all/no scope
   ожидать clarification или честный MISSING, не glossary hijack

4. Проектный вопрос со scope
   выбрать проект/датасет котельной
   спросить "составь реестр документации котельной"
   ожидать project registry с source_refs

5. Source-scoped query
   спросить "найди ОЗК в актах смонтированного оборудования"
   ожидать поиск по asbuilt/source scope, не norm/glossary

6. Документы
   открыть Source Operations
   dry-run "Подготовить к поиску"
   проверить, что dry-run ничего не пишет

7. Негативный сценарий
   выбрать пустой/неподготовленный датасет
   спросить вопрос по документам
   ожидать actionable MISSING с причиной

8. История
   отправить вопрос
   открыть историю
   убедиться, что session/question/answer доступны
```

---

## 3. Что надо автоматизировать первым

### P0

```text
tools/basic_function_smoke.py
  объединяет L1 + минимальный L2
  пишет JSON artifact
  возвращает non-zero на любом P0

make smoke-basic
  запускает basic_function_smoke.py против локального runtime

tests/test_basic_function_smoke.py
  unit-тестирует парсинг результатов и критерии fail/warn
```

P0 assertions:

```text
version visible
health reachable
chat returns non-empty answer or explicit MISSING/BLOCKED
scope options reachable
copy button rendered
source buttons are not fake
diagnostics does not normalize FAIL to OK
auth/trust public boundary is not accidentally open
```

### P1

```text
Playwright checks for:
  copy answer clipboard
  stop generation
  citation drawer
  open source disabled reason
  history entry after answer
  scope selector state
```

### P2

```text
visual snapshots:
  desktop /les
  mobile /les
  answer with citations
  MISSING/BLOCKED answer
  diagnostics degraded state
```

Snapshots нужны не для пиксель-перфекционизма, а чтобы ловить исчезнувшие кнопки,
перекрытый текст, пустую правую панель и сломанный layout.

---

## 4. Критерии результата

Каждый smoke case должен возвращать structured result:

```json
{
  "name": "copy_answer",
  "status": "pass|warn|fail|skip",
  "severity": "P0|P1|P2",
  "elapsed_ms": 123,
  "evidence": {
    "url": "http://127.0.0.1:8051/les",
    "selector": "button[data-testid='copy-answer']",
    "text": "Копировать"
  },
  "reason": ""
}
```

Правила:

```text
P0 fail -> exit 1
P1 fail -> exit 1 перед release, warn в обычной dev-сессии
P2 fail -> warn, если не затрагивали UI
skip допустим только с явной причиной: нет ключа, нет dataset, сервис выключен
```

---

## 5. Нужные data-testid

Чтобы browser-smoke был устойчивым, UI должен иметь стабильные селекторы:

```text
data-testid="runtime-version"
data-testid="runtime-health"
data-testid="chat-input"
data-testid="chat-send"
data-testid="chat-stop"
data-testid="answer-copy"
data-testid="answer-block"
data-testid="source-chip"
data-testid="citation-drawer"
data-testid="source-open"
data-testid="scope-selector"
data-testid="history-button"
data-testid="diagnostics-panel"
data-testid="source-ops-dry-run"
```

Тесты не должны цепляться за декоративный текст, если есть `data-testid`.

---

## 6. Команды после реализации

Обычная dev-проверка:

```bash
make verify
make smoke-basic
```

Перед release/деплоем:

```bash
make verify
make test
make smoke-basic
uv run python tools/rag_golden_set.py --cases golden/domain_fire_hvac_set.json
```

После UI/source changes:

```bash
make verify
make smoke-basic
uv run --with playwright python tools/browser_smoke.py --trusted-local
```

---

## 7. Чего этот план не заменяет

```text
полную pytest-сюиту
golden FIRE/HVAC gate
ручную экспертную проверку смет/норм
backup restore smoke
MetaDB↔Qdrant consistency smoke
security audit
```

Он закрывает другой слой: "жив ли базовый продукт глазами пользователя".

