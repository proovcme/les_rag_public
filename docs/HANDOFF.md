# HANDOFF — снимок на закрытие сессии (2026-06-20, ночь)

Ветка `feat/les3-p1`. `make verify` зелёный (1025 тестов). Рантайм (live): `/Users/ovc/LES`
(правки портируются пофайлово, не git pull). Коммит этой сессии — большой, многофункциональный.

## Что сделано этой сессией

**Облако / модели:**
- **КРИТ-ФИКС: облачный 400.** `gpt-5.4-mini` требует `max_completion_tokens`, а ЛЕС слал
  `max_tokens` → 400 во **всех** вспомогательных вызовах (валидация Т.О.С.К.А., `doc_router`,
  `les_md`-enrich) → всё сваливалось на медленный локальный 4B (генерация 105с). Починено в 4 местах
  (`_cloud_body_for_model` + инлайн в doc_router/les_md). Проверено: облако отвечает за ~2с, VERIFIED.
- **Локальная модель чата: Qwen3.5-4B-MLX-4bit (основная)** вместо 9B (на M4/24GB 9B = 5-7 ток/с
  из-за свопа; 4B = ~20). **9B — резерв, переключаемый в GUI** (⚙ → «Локальная модель»,
  `POST /api/settings/mlx-model` → host `/api/switch_model` вживую). Активный провайдер сейчас
  **openai (cloud)** — быстрые ответы; P0 (котельная) гейтом ADR-9 всё равно остаётся локально.

**GUI / артефакты:**
- **Файл-вьювер видит внешние корни** (`LES_EXTERNAL_SOURCE_ROOTS`) — проекты по ссылке (котельная,
  каталоги) листаются; ленивая дозагрузка дерева; path-guard на каждый корень. `files.py` мульти-корень.
- **Артефакт = только таблица** (без дубля прозы), заголовок «Таблица»/«Спецификация».
- **GOST 21.110-рендерер**: спека рендерится по форме (графы Поз./Обозначение/Наименование и тех.хар-ка/
  Тип,марка/Ед.изм/Кол./Масса ед./Примечание) + рамка + заголовок формы.
- **Авто-GOST**: «собери/составь спецификацию …» авто-уходит в формат спеки (не липко).
- **Кнопка-артефакт в сообщении** (как Claude Desktop) — открывает артефакт в панели.
- **CSV-экспорт** таблиц (`;` + UTF-8 BOM, рус-Excel); кнопка «Копировать» через JS-fallback (secure-context).
- **Резиновый layout** — разделитель чат↔артефакты тащится по ширине (CSS-var + localStorage).
- **Группировка датасетов** в САМОВАРе (колонка «Группа», `group_name` в БД, `PATCH …/group`); P0/P1 тоггл уже был.

**Индексация:**
- **Авто-нарезка крупных PDF** вшита в `index-external` (`tools/pdf_preprocess.preprocess_dir`,
  TOC-aware, оригиналы→`_originals/`, флаг `auto_split`, порог `split_max_mb=40`). Молотилка =
  штатный `parse-scheduler` (батчи+кулдаун+выгрузка).
- **Фикс маршрутизации**: `is_spec_to_bor_query` ловил «вор» подстрокой → «**пово**ро**т**ы» (по-**ВОР**-оты)
  + «спецификацию» уводили в ВОР-канал. Теперь `\bвор\b` по границе слова.
- **Сводка проекта**: документный проект (нет Parquet) не падает в clarification (guard на summary-интент).

## Состояние рантайма
- Чат-модель: **4B локально** (.env MLX_MODEL/LLM_MODEL), 9B в кэше (резерв-тоггл). Активен **openai**.
- **Каталоги** (датасет `133004e7`, P1, группа «Каталоги»): Systeme + DKC (нарезаны на части) —
  **58 доков / 8171 чанк**, IDLE. Источники: DKC/Systeme — Совушка отвечает по каталогу с источниками.
- **W-205-MP-02-VK02** (`3f053c90`, P1): ~42 дока (парс прерван рестартом, остаток PENDING — дотянуть СИНКом).
- Котельная (`8c14…`, P0): 75 доков, локально.

## ПЛАН СЛЕДУЮЩЕЙ СЕССИИ (приоритет Олега)

**1. РЕЛИЗЫ под Mac и Windows с человеческой установкой** («чем мы хуже AnythingLLM?»).
Развилки решены (Олег): **лёгкий .app-бутстрап** (не PyInstaller) + **докачка весов при первом запуске**.

- **Mac — Фаза 1 ГОТОВА (эта сессия).** Дабл-клик `LES.app` собирается из чистого экспорта кода:
  - `installers/macos/app/` — `Info.plist.template`, `launcher` (bundle exec), `bootstrap.sh`
    (install-uv-if-missing → `uv sync --extra mac-mlx` → `lesctl init` → `onboard_models` →
    `lesctl start --include-ui` → open `127.0.0.1:8051/les`; прогресс = нотификации, ошибки = диалог,
    лог `~/Library/Logs/LES/bootstrap.log`; рантайм разворачивается в `~/Library/Application Support/LES`,
    override `LES_HOME`).
  - `tools/build_macos_app.py` → `dist/LES.app` (ad-hoc подпись, переиспользует `iter_files`,
    без `.env`/данных). `tools/build_macos_dmg.py` → `dist/LES.dmg` (~20 МБ, drag-to-Applications).
  - `tools/onboard_models.py` — идемпотентная докачка весов (4B MLX + эмбеддер) из `.env`/`env.example`.
  - Тесты: `tests/test_installer_macos.py` (4, зелёные). Бандл провалидирован (`plutil`/`codesign`).
  - **Проверено офлайн** (сборка+валидация). **НЕ проверено на чистой машине** — `bootstrap.sh`
    специально не запускался (живой рантайм не трогать). Следующий шаг — прогон на свежем Mac/в песочнице.
  - Осталось по Mac: иконка `LES.icns`, Developer ID-подпись + нотаризация (сейчас только ad-hoc),
    богатый онбординг-UI (сейчас нотификации), coreml-эмбеддер из `artifacts/` в бандл не входит →
    фолбэк на mlx-эмбеддер (`COREML_EMBED_FALLBACK=true`) — проверить на чистой установке.
- **Windows — Фаза 1 ГОТОВА (эта сессия).** Зеркало mac-подхода (без MLX → движок облако/ollama/lemonade,
  выбор в GUI, веса не бандлятся):
  - `installers/windows/app/` — `bootstrap.ps1` (install-uv: winget/офиц.скрипт → `uv sync` →
    `lesctl init --profile windows-lite` → `onboard_models --skip-if-cloud` → Qdrant best-effort (docker
    если есть) → `start-light.ps1` (proxy+UI) → open `127.0.0.1:8051/les`; прогресс = трей-баллоны,
    ошибки = диалог, лог `%LOCALAPPDATA%\LES\logs\bootstrap.log`), `launcher.vbs` (скрытый запуск, без
    мелькания консоли), `LES.nsi` (NSIS per-user в `%LOCALAPPDATA%\Programs\LES`, ярлыки Пуск/Рабочий стол,
    uninstaller, Add/Remove). `bootstrap.ps1`+`LES.nsi` — UTF-8 **с BOM** (PowerShell 5.1/NSIS читают кириллицу).
  - `tools/build_windows_installer.py` — стейдж чистого экспорта (`iter_files`); `makensis` есть → `dist/LES-Setup.exe`,
    нет → `dist/LES-windows-portable.zip` + печать команды makensis. Тесты `tests/test_installer_windows.py` (3).
  - **НЕ проверено**: `.ps1`/NSIS на этой машине не исполнялись (нет `pwsh`/`makensis` на Mac); прогон/сборка
    `.exe` — на Windows-боксе. Осталось: иконка `LES.ico`; решить дефолт-провайдер/онбординг-ключ в GUI;
    нативный Qdrant без Docker (сейчас docker-or-warn); подпись (signtool).
  - Артель — отдельный Win+Revit пакет (см. память `legion-build-workflow`).

**2. Дотянуть данные**: W-205 (остаток PENDING), каталоги DKC (если пара кусков не домолота),
проверить ГОСТ-спеку в GUI начисто (облако + скоуп «Каталоги» → артефакт ГОСТ-таблица + CSV).

## Долг / наблюдать
- ГОСТ-рендер/авто-GOST/резиновый-layout/кнопка-артефакт **глазами в GUI не проверены** — смотреть.
- Парс **блокирует event loop** proxy (CPU-bound in-process) → во время индексации GUI лагает, health
  таймаутит (HTTP 000), потом оживает. Архдолг: вынести парс из процесса / давать await-точки.
- Public-курация (`les_rag_public`) — не трогали; субсет, не зеркало.
- `agent_router_service._llm_text` тоже шлёт `max_tokens` (не в гор. пути чата) — добить при заходе в агента.

## Как продолжить
Поднять контекст с этого HANDOFF + памяти (`mlx-model-choice-m4`, `les3-rag-intake-state`,
`runtime-uv-sync-mlx-extra`, `gui-first-principle`). Рантайм: `/Users/ovc/LES`. Гейт — `make verify`.
