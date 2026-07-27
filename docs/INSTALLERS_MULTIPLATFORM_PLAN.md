# Детальный план: инсталляторы и мультиплатформа

Расширение волн **W4 (мультиплатформа)** и **W7 (установка/релиз)** из `LES3_PLAN.md`.
Связанные доки: [PLATFORMS.md](PLATFORMS.md) (профили/адаптеры), [PACKAGING.md](PACKAGING.md)
(издания/стадии). Здесь — конкретные под-задачи, приёмка и анализ разрыва «что есть vs нужно».

## Текущее состояние (ground truth на 2026-06-14)

Уже есть:
- `tools/lesctl.py` — фасад с командами `doctor · install · init · status · start · stop · restart · smoke`.
- `tools/les_doctor.py` — **W7.2 готова**: health-отчёт (порты/RAM/диск/GPU/MLX/proxy/провайдеры/Qdrant), `--json`, exit-коды.
- `tools/les_runtime_control.py` — управление сервисами **только через launchd (macOS)**.
- `installers/{macos,linux,windows}/` — тонкие скрипты (`install.sh`, `uninstall.sh`, `install.ps1`,
  `start-light.ps1`), `docker-compose.yml` для linux/windows, `systemd/` юниты (заготовки).
- `config/profiles/*.yaml` — 6 профилей: `mac-native`, `linux-docker`, `linux-systemd`,
  `windows-docker`, `windows-lite`, `server-remote-model`.
- `tools/build_release_artifacts.py`, `tools/clean_install_smoke.py` — заготовки сборки/смоука.

**Главный разрыв:** супервизор знает только macOS/launchd. Профили описаны (yaml), но
**адаптеры service-manager под systemd/Windows не реализованы**; `lesctl start` на Linux/Win
не поднимает стек. Windows-специфика (пути/кодировки/русские имена) не проверена. CI — только текущая ОС.

---

## W4.1 — Кроссплатформенный супервизор `lesctl` · L · приоритет 1

Цель: `lesctl start/stop/status/restart` работает на macOS, Linux, Windows через адаптеры.

- **W4.1.1 Абстракция service-manager.** Ввести интерфейс `ServiceManager` (start/stop/status/enable/
  logs) и реестр адаптеров, выбираемый профилем. Вынести текущий launchd-код `les_runtime_control`
  за этот интерфейс (адаптер `launchd`). Приёмка: `lesctl start --profile mac-native` = прежнее поведение, тесты зелёные.
- **W4.1.2 Адаптер `systemd` (Linux).** Генерация/установка user-юнитов `les-proxy`, `les-ui`
  (заготовки в `installers/linux/systemd/`); `--install-units`; start/stop через `systemctl --user`.
  Qdrant/модель — внешние (docker/native), супервизор их только проверяет (doctor). Приёмка: на чистой
  Linux-VM `lesctl init && lesctl start --profile linux-systemd` → `/api/health` зелёный.
- **W4.1.3 Адаптер `docker-compose` (Linux/Windows).** start/stop = `docker compose up -d/down` поверх
  `installers/<os>/docker-compose.yml`; именованный том Qdrant; модели вне образа (bind/volume).
  Приёмка: `lesctl start --profile linux-docker` и `windows-docker` поднимают стек, `/api/search` отвечает.
- **W4.1.4 Адаптер Windows-сервиса.** Без Docker: NSSM или Планировщик задач для `proxy`/`ui`;
  `start-light.ps1` довести до управляемого профиля `windows-lite`. Приёмка: `lesctl start --profile windows-lite` на чистой Win-VM → чат отвечает.
- **W4.1.5 Алиас `up`/`down`.** Добавить `lesctl up` (= init→start→smoke) и `down` для соответствия
  тексту приёмки плана. Приёмка: `lesctl up && lesctl status` на Mac и Win.

## W4.2 — Windows-профиль рантайма · M `[live]` · приоритет 2

- **W4.2.1 Аудит путей/кодировок.** Прогнать `pathlib` вместо строковых путей; проверить русские имена
  и сплит-суффиксы `_частьN.pdf` на NTFS, длинные пути (`\\?\`), CRLF, UTF-8 в логах/CSV.
- **W4.2.2 Модель/эмбеддер.** Профиль `win-ollama`: chat/OCR через Ollama, эмбеддер
  sentence-transformers/ONNX (без MLX). Свериться с `routing.py`/настройками провайдеров.
- **W4.2.3 Зависимости.** `uv sync` на Windows без Mac-only пакетов (MLX/CoreML — опциональные extras).
- Приёмка: golden-прогон и `make verify` зелёные на Windows.

## W4.3 — CI-матрица · S · приоритет 3

- Расширить workflow (W0.2) до matrix `macos + ubuntu (+ windows)`; на каждом — `make verify` +
  `lesctl doctor --json` + `clean_install_smoke`. Приёмка: все ячейки зелёные.

## W7.1 — Установка одной командой · M · приоритет 2

- **W7.1.1 Единый вход.** `install.sh`/`install.ps1` → `uv` → `uv sync` → выбор/валидация профиля →
  `lesctl init` → регистрация сервисов (W4.1) → загрузка моделей (вне образов) → `lesctl smoke`.
- **W7.1.2 Загрузка моделей.** Отдельный шаг (не в инсталляторе/образе): MLX/Core ML (Mac),
  Ollama pull (Linux/Win) или remote-провайдер; приватные корпуса не входят в пакет.
- **W7.1.3 Чистый-VM smoke.** Довести `clean_install_smoke.py` до прогона полного цикла install→up→
  `/api/health`+`/api/search` на чистой ОС (CI или ручная VM). Приёмка плана: «чистая VM → работающий
  чат одной командой» на Mac и Win.

## W7.3 (новое) — Сборка/подпись релиза · M · перед публичным релизом

- `build_release_artifacts.py`: собрать per-OS бандлы (вьювер АТЛАС уже есть в `build_atlas_release.py`).
- macOS: подпись + нотаризация `.pkg`/`.dmg`; Windows: подпись `.msi`/`.exe`; Linux: tarball/deb + checksums.
- SBOM/лицензии; версия из `VERSIONING.md`. Приёмка: артефакты ставятся на чистых ОС без警告 безопасности.

---

## Порядок и зависимости

```
W4.1 (адаптеры) ──► W7.1 (install одной командой) ──► W7.3 (подпись/релиз)
   │                                   ▲
   └► W4.2 (Win-рантайм) ──────────────┘
W4.1 + W7.1 ──► W4.3 (CI-матрица закрепляет зелёное)
```

Минимальный смоук каждого профиля (из PLATFORMS.md) — обязателен в приёмке каждой под-задачи:
`lesctl doctor → init → start → /api/health → /api/search`.

## Принципы (из PLATFORMS.md, держим)
- API стабилен на всех профилях; `/api/search` — продуктовый контракт АТЛАС/АРТЕЛЬ, не зависит от
  локальной генерации; `/api/chat` опционален.
- launchd/systemd/Windows-service — только адаптеры за `lesctl`, не в продуктовом коде.
- Модели и приватные корпуса — вне пакетов/образов; Qdrant на Windows — именованные тома.
