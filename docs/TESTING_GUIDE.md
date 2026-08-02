# Руководство по тестированию и настройке CI (Л.Е.С. / LES_v2)

Настоящий документ определяет устройство тестовой инфраструктуры проекта Л.Е.С. (LES_v2), порядок локального запуска тестов, правила изоляции тестовых данных и интеграцию с CI/CD.

---

## 1. Структура системы тестирования

Тестовая инфраструктура состоит из следующих слоёв:

1. **Модульные тесты (`Unit Tests`)**:
   - Находятся в `tests/test_unit_core_business.py` и профильных модулях (`test_answer_contract_service.py`, `test_candidate_selection_service.py`, `test_query_router.py` и др.).
   - Проверяют бизнес-логику изолированно от внешней сети, реальных LLM/Qdrant и дисковых баз данных.
   - Используют моки и герметичные фикстуры.

2. **Дымовые тесты (`Smoke Tests`)**:
   - **Автономный герметичный smoke (`tests/test_smoke_offline.py`)**: мгновенно (< 5 секунд) проверяет инициализацию FastAPI приложения через `TestClient`, эндпоинты `/api/health`, `/api/version`, `/api/status`, загрузку конфигураций и чистый teardown без запущенных сервисов.
   - **Live HTTP smoke (`tools/basic_function_smoke.py`)**: L1-проверка работоспособности против живого запущенного экземпляра (`http://127.0.0.1:8050`).

3. **Единая точка запуска (`Test Runner`)**:
   - Скрипт `tools/test_runner.py` объединяет запуск всех проверок в единые режимы: `all`, `unit`, `smoke`, `coverage`, `ci`.
   - Интегрирован в `Makefile` через стандартные цели.

---

## 2. Зависимости и окружение

Для запуска тестов необходим Python 3.12+ и менеджер пакетов `uv`.

### Установка и подготовка

```bash
# Проверка синхронизации версионного контракта
uv run python tools/sync_version_contract.py --check

# Проверка синтаксиса и сборки
make verify
```

### Переменные окружения для тестов

Скопируйте пример файла окружения:

```bash
cp env.test.example .env.test
```

---

## 3. Изоляция тестовых данных и безопасность

Все автоматические тесты соблюдают строгие правила безопасности:

- **Отсутствие обращений к рабочей БД**: Все тесты используют изолированные SQLite БД во временных каталогах (`tmp_path` или `tmp/pytest_temp`).
- **Изоляция временных файлов**: Выполнение `pytest` использует параметр `--basetemp=tmp/pytest_temp`, предотвращая конфликты блокировок файлов в ОС Windows (`PermissionError`).
- **Мокирование внешних API**: Сетевые вызовы к OpenAI, Qdrant, MLX и почтовым серверам перехватываются моками.
- **Очистка ресурсов**: Тестовые фикстуры гарантируют удаление временных файлов и корректное завершение потоков.

---

## 4. Команды запуска тестов

Проект предоставляет стандартизированный интерфейс команд:

| Команда | Описание | Выполняемые действия |
|---|---|---|
| `make test` / `uv run python tools/test_runner.py all` | Полный запуск всех канонических тестов | Запускает unit, integration и smoke тесты с консольным отчётом |
| `make test-unit` / `uv run python tools/test_runner.py unit` | Быстрые модульные тесты | Проверяет чистую бизнес-логику |
| `make test-smoke` / `uv run python tools/test_runner.py smoke` | Дымовые тесты | Запускает герметичную офлайн smoke-сюиту |
| `make test-coverage` / `uv run python tools/test_runner.py coverage` | Отчёт о покрытии кода | Формирует `artifacts/coverage_report.txt` и `artifacts/coverage.json` |
| `make test-ci` / `uv run python tools/test_runner.py ci` | Режим для CI контура | Генерирует JUnit XML отчёт `artifacts/junit-report.xml` |

---

## 5. Интеграция с CI (GitHub Actions)

Пример конфигурации `.github/workflows/verify.yml` для автоматического запуска проверок при каждом PR и коммите:

```yaml
name: CI Gate

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install uv
        run: curl -sSf https://astral.sh/uv/install.sh | sh

      - name: Verify Code Structure
        run: make verify

      - name: Run Unit & Offline Smoke Tests with JUnit XML
        run: make test-ci

      - name: Upload Test Results Artifact
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: junit-report
          path: artifacts/junit-report.xml
```

---

## 6. Решение типовых ошибок (Troubleshooting)

### 1. `PermissionError: [WinError 5] Access is denied` на Windows
**Причина**: Временный каталог Windows заблокирован антивирусом или параллельным процессом.
**Решение**: Тестовый запуск автоматически передает `--basetemp=tmp/pytest_temp`. Убедитесь, что запуск выполняется через `tools/test_runner.py` или `make test-*`.

### 2. `HTTP 401 / 403` при обращении к защищённым API
**Причина**: Эндпоинты требуют авторизации или административного API-ключа.
**Решение**: В офлайн-тестах статус 401/403 подтверждает корректную работу guardrail безопасности.

### 3. Зависшие тесты при потере связи с Qdrant/MLX
**Причина**: Попытка выполнения реального вызова в герметичном unit-тесте.
**Решение**: Мокируйте `QdrantLlamaIndexAdapter` и HTTP-клиенты через `monkeypatch` или `unittest.mock`.

---

## 7. Правила добавления новых тестов

1. **Модульные тесты**:
   - Помещайте в `tests/test_unit_core_business.py` или отдельный `tests/test_<module_name>.py`.
   - Название функций: `test_<function>_<scenario>()`.
   - Каждая функция должна проверять:
     - Обычный успешный сценарий;
     - Граничный сценарий;
     - Пустые или некорректные входные данные;
     - Проверку структуры возвращаемого ответа.

2. **Обновление версионного леджера**:
   - При создании новых тестовых файлов или обновлении контрактов повышайте `build_number` в `config/version.json` и добавляйте запись в `docs/RELEASE_LEDGER.md`.
