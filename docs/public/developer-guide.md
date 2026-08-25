# Разработка и выпуск ЛЕС

Этот документ — публичный вход для разработчика. Он не заменяет канонические карты и runbook, а связывает их в один воспроизводимый маршрут без приватных данных и имён рабочих машин.

## Архитектура

ЛЕС состоит из четырёх независимых ролей:

```text
Tauri desktop
  → FastAPI + NiceGUI «Совушка»
  → document parse + dense/sparse native RRF
  → выбранные пользователем answer/embedding providers
  → Qdrant + typed SQLite/Parquet evidence
```

- Tauri владеет окном, tray, первым запуском и lifecycle.
- FastAPI владеет прикладным API; NiceGUI — рабочим интерфейсом.
- Qdrant хранит named dense + BM25 sparse vectors; retrieval объединяет их native RRF.
- Typed readers возвращают точные строки и карточки, но не принимают профессиональное решение вместо модели.
- Модель формулирует и выбирает; код валидирует структуру, происхождение и выполняет вычисления.

Карта модулей: [MODULE_INDEX.md](../MODULE_INDEX.md). Потоки по файлам: [CODE_MAP.md](../CODE_MAP.md).

## Репозиторий и данные

Код приложения находится в `backend/`, `proxy/`, `sovushka/`, `desktop/tauri/`, `installers/` и `tools/`. Пользовательские `data/`, `storage/`, `RAG_Content/`, журналы, индексы, `.env` и model cache не входят в Git и release payload.

На Windows заменяемая программа находится в `%LOCALAPPDATA%\Programs\LES`, persistent state — в `%LOCALAPPDATA%\LES`. Обновление не должно переносить или удалять state.

## Локальная разработка

Требуются Git и uv. Точные версии Python-пакетов задаёт `uv.lock`.

```bash
git clone --recurse-submodules https://github.com/proovcme/les_rag_public.git
cd les_rag_public
uv sync
make verify
```

Платформенные extras и lifecycle описаны в [PLATFORMS.md](../PLATFORMS.md) и [INSTALL_RUNBOOK.md](../INSTALL_RUNBOOK.md). Не копируйте `.env` из чужой установки и не добавляйте модельные веса в репозиторий.

## Windows installer без Python на машине пользователя

`tools/build_tauri_app.py` создаёт чистое runtime-дерево и добавляет:

1. SHA-256-проверенный portable CPython archive;
2. SHA-256-проверенный `uv.exe`;
3. `windows-uv-cache.zip`, заранее заполненный на Windows-сборщике по `uv.lock` и extra `windows-reranker`;
4. `uv-cache-contract.json` с SHA archive и SHA точного lock-файла;
5. immutable release assets и deploy identity.

Первый запуск проверяет все три payload, распаковывает Python и cache в persistent state и выполняет:

```text
uv sync --locked --offline --python <bundled-python> --no-python-downloads --extra windows-reranker
```

Bootstrap не использует system Python/uv, winget или сетевой installer как fallback. Несовпадение contract означает повреждённый release payload, а не запрос пользователю самостоятельно чинить Python.

Модельные движки, веса, Docker и Qdrant image не входят в EXE. Setup snapshot только выполняет bounded local probes и показывает совместимость.

## Тесты

Минимальный обязательный цикл:

```bash
make verify
make test
make public-check
```

После правки Windows/Tauri:

```bash
uv run pytest tests/test_tauri_desktop.py tests/test_installer_windows.py \
  --basetemp=.test-tmp/windows-installer -q
cargo check --manifest-path desktop/tauri/src-tauri/Cargo.toml
```

Windows release требует не только compile-check, но и реальную установку собранного NSIS EXE в изолированный каталог. Smoke проверяет identity/version, API/UI, процессы, Qdrant/RRF для настроенного поискового контура и безопасную остановку.

Общий список тестов находится в [TEST_INVENTORY.md](../TEST_INVENTORY.md). Нельзя заменять release gate исторической полной suite или ослаблять тест ради зелёного статуса.

## Версии и документация

Единственный вход версии — `config/version.json`. После изменения:

```bash
make version-sync
uv run python tools/sync_version_contract.py --check
```

В том же коммите обновляются module doc, строка `MODULE_INDEX`, `CODE_MAP` при изменении потока, `SOFTWARE_VERSIONS`, `RELEASE_LEDGER` и `TEST_INVENTORY`. Публичная документация не должна требовать приватный hostname, corpus или credential.

## Публичный выпуск

Порядок нельзя переставлять:

1. clean committed and pushed source commit;
2. `make verify`, `make test`, `make test-mail-release`, `make public-check`;
3. Windows Tauri/NSIS build;
4. реальная isolated install и `windows_release_smoke.ps1`;
5. checksum installer и создание `latest.json`;
6. публикация очищенного commit в public `main`;
7. GitHub Release с `LES-Setup.exe`, `LES-Setup.exe.sha256`, `latest.json`;
8. download-compare опубликованных assets.

Скрипты выпуска: `tools/patch_release.py` и `tools/windows_patch_release.ps1`. Ручная сборка EXE полезна для разработки, но не считается выпуском.

## Безопасность изменений

- Не читать и не публиковать `.env`, credentials или пользовательские базы.
- Не удалять Qdrant volume, `data/`, `storage/` или `RAG_Content/` без прямого запроса владельца.
- Не менять `proxy/smeta_core/**` вместе с обычной RAG/UI-стабилизацией.
- Не force-push public `main` до scrub и installed-EXE acceptance.
- Доменный smoke с отсутствующим user-owned corpus отмечается `N/A: corpus absent`, а не заменяется выдуманным корпусом.

Операторская диагностика пользовательского выпуска: [windows-troubleshooting.md](windows-troubleshooting.md).
