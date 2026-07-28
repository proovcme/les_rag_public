# Internal updater: prepare once, apply fast

Внутреннее обновление `codex/audit-rag` разделено на подготовку и установку.
Повторный apply не запускает тесты, не пересобирает приложения и не передаёт
неизменившуюся сметную базу.

Публичная публикация отсутствует: команды не принимают `--publish`, не создают
tag/GitHub Release и не обновляют public feed.

## Команды

1. `make preflight-audit-rag-update` — быстрый read-only статус ветки, cache и
   Mac runtime; Legion не опрашивается.
2. `make prepare-audit-rag` — один тяжёлый локальный prepare для точного SHA:
   `verify`, полная suite, RAG-гейт, Mac app/DMG и smeta baseline. Результат
   сохраняется в `/Users/ovc/LES_update_cache/audit-rag/<commit>/manifest.json`.
   Повторная команда с тем же SHA и совпадающими checksum возвращает
   `cache_hit=true` без тестов и сборки.
3. `make inspect-audit-rag-update` — read-only проверка identity и SHA локального
   prepared bundle.
4. `make prepare-audit-rag-legion` — отдельная подготовка Windows без production
   install. Baseline хранится на Legion по SHA-256 и передаётся только при
   отсутствии этого хэша. Installer собирается один раз, проходит isolated
   clean-install/RRF smoke и сохраняется в
   `%LOCALAPPDATA%\LES\update-cache\bundles\<commit>`.
5. `make deploy-audit-rag-mac` — быстрый apply подготовленного SHA только на Mac.
6. `make deploy-audit-rag` — быстрый apply уже подготовленных Mac+Legion
   артефактов. Команда отказывается работать без обоих prepared manifests.

## Инварианты

- ветка чистая, `HEAD == origin/codex/audit-rag`;
- bundle связан с точными `commit + product_version + build_number`;
- каждый artifact повторно проверяется по размеру и SHA-256 перед apply;
- prepare и apply — разные процессы: host retry не повторяет gates/build;
- Legion preflight очищает только LES-процессы на `8050–8053`;
- Windows apply использует cached installer и не передаёт baseline;
- production update не повторяет first-run onboarding: после NSIS выполняются
  только sync существующего окружения, запуск API/UI и контрактные health-гейты;
- после установки Windows runtime получает проверяемый deploy stamp с точным
  commit `codex/audit-rag`, который затем сверяется из новой SSH-сессии;
- форматированный многострочный JSON и служебный CLIXML от PowerShell
  разбираются без ложного провала apply;
- интерактивный Outlook probe относится к отдельному mail-гейту: его
  недоступность записывается как warning и не откатывает зелёные core/API/UI;
- Mac и Legion имеют автоматические точки rollback; `.env`, `data/`, `storage/`,
  документы и пользовательские Qdrant collections не входят в заменяемый код;
- Windows backup копирует только код приложения через `robocopy /XJ`, не
  проходит внутрь runtime junctions и не дублирует пользовательские данные;
- Legion не обновляется командой prepare: production mutation выполняет только
  явный apply.

## Ожидаемое время

Первый prepare остаётся release-гейтом и может быть длительным. Регулярный apply
и повтор после host-smoke ошибки должны занимать минуты: без pytest, Rust/Tauri
build и 54-МБ baseline transfer. Если checksum prepared artifact изменился,
updater блокирует apply вместо неявной пересборки.
