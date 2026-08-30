# INSTALL_RUNBOOK — boxed install on a clean Mac / Windows

Operator runbook for taking ЛЕС from a fresh repo to a double-click app on a
**clean target machine**. This is the honest version: every step that needs a
human at a real Mac/Windows box, an Apple/Microsoft signature, or a VM is marked
**[ручками]** (manual / cannot be done in CI or on the build box).

Audience: Олег. Build box = your dev Mac. Target = the clean machine the app
ships to.

**Windows для пользователя (не этот runbook):** установка / удаление / обновление
через `LES-Setup.exe` и «Параметры → Приложения» — [WINDOWS_DESKTOP.md](WINDOWS_DESKTOP.md).
Машинный lifecycle — [ALGO-windows-lifecycle.md](ALGO-windows-lifecycle.md).

---

## 0. What's automated vs. what isn't

| Stage | Automated (build box) | [ручками] on target / needs signature |
|---|---|---|
| Icons | `tools/build_icons.py` (Pillow fallback or cairosvg) | — |
| Build `.app` / `.dmg` | `tools/build_tauri_app.py --bundles app,dmg` | — |
| Build Win installer | `tools/build_windows_installer.py` on Windows | Windows host/VM is required for the final Tauri/NSIS EXE |
| First launch / bootstrap | `bootstrap.sh` / `bootstrap.ps1` (uv, sync, onboarding, weights, shell) | runs **only on the target**, needs network |
| Provider/key/model | `tools/onboard_provider.py` (first-run default) + GUI «Настройки» | cloud key is pasted by a human |
| Gatekeeper / SmartScreen | — | **[ручками]** unblock, or buy Developer ID / Authenticode |

There is **no Developer ID / Apple notarization / Windows Authenticode** yet.
The bundles are **ad-hoc signed** (Mac) / **unsigned** (Win). On a clean machine
the OS *will* warn — see §4. Real signing is a paid, account-bound step that
cannot be faked here; it's tracked in §6.

---

## 1. One-time prep on the build box (Mac)

```bash
# Icons — regenerate .icns/.ico from installers/icon/les.svg.
# Pillow is already in the runtime env (built-in fallback renderer); cairosvg
# gives full SVG fidelity if you install it.
uv run --with pillow python tools/build_icons.py
#   -> installers/macos/app/LES.icns
#   -> installers/windows/app/LES.ico
# (committed assets; only rerun when les.svg changes)
```

Sanity-check the offline gate before building anything:

```bash
make verify        # syntax + import smoke + pytest collect (no Qdrant/MLX)
```

---

## 2. Build the macOS bundle (on the Mac build box)

```bash
uv run python tools/build_tauri_app.py --version X.Y.Z --bundles app,dmg
# -> dist/LES.app + dist/LES.dmg
```

- `--sign` = **ad-hoc** codesign (`codesign --sign -`). Enough to run locally;
  **not** enough to clear Gatekeeper on someone else's Mac without §4.
- Weights and the venv are NOT bundled. The clean Python runtime source is bundled and
  materialized into `~/Library/Application Support/LES` on first launch.

**[ручками]** Copy `dist/LES.dmg` to the clean Mac (AirDrop / USB / download).

---

## 3. Build the Windows installer

The final Tauri/NSIS `LES-Setup.exe` must be built on Windows. A Mac build does
not produce an old look-alike EXE under the same name.

```bash
uv run python tools/build_windows_installer.py --version X.Y.Z
```

- Windows → `dist/LES-Setup.exe` through Tauri/NSIS.
- macOS/Linux → `dist/LES-windows-tauri-source.zip`; transfer it to Windows and
  run the same command there.

### Ручное обновление Windows

ЛЕС не проверяет обновления в фоне. Оператор открывает настройки и нажимает
`Проверить обновление`; только после найденной новой версии становится доступна отдельная
кнопка `Обновить`. Публичный выпуск GitHub обязан содержать три файла с точными именами:

- `latest.json` — версия и краткое описание выпуска по схеме `les.update.v1`;
- `LES-Setup.exe`;
- `LES-Setup.exe.sha256` — строка `<sha256>  LES-Setup.exe`.

Проверка обновления читает `latest.json` напрямую, без GitHub API. Затем серверная часть скачивает
установщик и контрольную сумму в `%LOCALAPPDATA%\LES\artifacts\updates\<version>`, принимает
только адреса GitHub по HTTPS, сверяет SHA-256 и открывает обычный установщик NSIS. Фоновая
загрузка, downgrade и установка неполного/непроверенного выпуска запрещены.

### Каноническая приёмка и публикация Windows-выпуска

Собирать выпуск только из чистой, отправленной ветки. Версия продукта и номер сборки задаются
в `config/version.json`; версии обязательной инфраструктуры — в `docs/SOFTWARE_VERSIONS.md`.
Единственный операторский канон — [`RELEASE_PROCEDURE.md`](RELEASE_PROCEDURE.md).

1. Подготовить короткое описание выпуска и выполнить:

   ```text
   make release RELEASE_ARGS='run --host legion --publish'
   ```

2. `tools/release_orchestrator.py` проверяет clean/pushed commit, обязательные gates и
   автоматически выбирает soft/full. Подготовленные candidate bytes после этого не пересобираются.

3. На Legion exact candidate устанавливается штатным updater/NSIS-путём, проходит smoke,
   controlled rollback, smoke восстановленной версии и повторную установку. Внутренний full-builder
   `tools/windows_patch_release.ps1` на Windows строго обновляет checkout до запрошенного commit,
   собирает Tauri/NSIS, устанавливает EXE в новый одноразовый каталог под
   `%LOCALAPPDATA%\LES-release-smoke` и
   запускает `windows_release_smoke.ps1`. Только после его успеха installer передаётся как
   payload в `windows_update_engine.py`: движок переименовывает всё старое дерево приложения
   в recovery, ставит новое, повторно привязывает persistent `%LOCALAPPDATA%\LES` и проверяет
   exact identity, API/UI, index contract и process contract. Пользовательские данные не входят
   в удаляемую область; провал smoke целиком возвращает предыдущее дерево. Outlook probe и
   доменная проверка остаются отдельными release-гейтами, а не частью install-транзакции.
   Холодный импорт большого Windows runtime получает до 120 секунд до `/api/version`; управляющий
   updater ограничен 180 секундами и затем делает обычный rollback.

4. Публикация начинается только после stage `accepted`. Feed связывает SHA
   `release-receipt.json`; GitHub Release сначала остаётся draft с явным target commit,
   все assets скачиваются обратно и сверяются до publish, после чего отдельный postflight
   проверяет public main/tag/feed/receipt/hashes.

   RRF-smoke не доверяет уже лежащим в Qdrant чужим коллекциям. До bootstrap он задаёт уникальную
   `RAG_COLLECTION_NAME`, через API установленного runtime создаёт временный датасет, индексирует
   контрольный UTF-8-документ, выполняет scoped `dense + qdrant_sparse → RRF`, а затем
   удаляет и свой датасет, и свою одноразовую коллекцию. Это не позволяет локальному паспорту
   индекса случайно проверять общую непустую коллекцию другого контура.

#### Грабли Windows OpenSSH / PowerShell

Удалённый bootstrap намеренно находится в `tools/patch_release.py`, а не только в PowerShell-файле
репозитория. На старом checkout новый `windows_patch_release.ps1` ещё отсутствует, поэтому сначала
нужно синхронизировать точный commit, и только затем вызывать versioned script.

- Сложную команду нельзя передавать как обычный `PowerShell -Command` через Windows OpenSSH:
  удалённый shell разрушает кавычки и переменные вроде `$repo`. Канонический путь —
  `PowerShell -EncodedCommand`, UTF-16LE → base64.
- `git fetch origin main` при узком fetchspec обновляет только `FETCH_HEAD` и не обязан создавать
  `origin/main`. Использовать явный refspec `main:refs/remotes/origin/main`, затем создавать
  локальную `main` непосредственно от `refs/remotes/origin/main`. Не использовать `--track`:
  Git с узким fetchspec может не признать даже существующий ref tracking-веткой и оставить
  незавершённый checkout в рабочем дереве. Release-flow всё равно обновляет ветку явным
  `pull --ff-only origin main`.
- Windows PowerShell 5 может вернуть SSH код `0`, когда файл из `-File` не найден. Нельзя считать
  этот код достаточным доказательством: обязательны точный remote HEAD, новый машинный
  `windows-patch-release.json`, совпадение commit/SHA и `smoke.ok=true`.
- Не скачивать и не публиковать лежащий в `dist` EXE без нового отчёта: там может оставаться
  артефакт предыдущего выпуска.
- Фоновый upload не считается успешным по ответу `queued`. Ошибка admission/контракта/парсинга
  должна переводить конкретный документ из `PENDING` в `ERROR` с `last_error`; вечный `PENDING`
  является дефектом наблюдаемости и должен останавливать smoke.
- Общий `env.example` содержит `EMBED_URL_PARSE=:8081` для отдельного Mac/dev-эмбеддера. В
  Windows/Ollama `start-light.ps1` обязан переопределить и `MLX_URL`, и `EMBED_URL_PARSE` на
  `OLLAMA_BASE_URL`; иначе query dense работает, а индексация новых документов падает на
  несуществующем sidecar. Проверять нужно upload→INDEXED, а не только retrieval старых точек.

#### Номер сборки меняется один раз

`config/version.json` — единственный вход. После правки версии или номера сборки выполнить:

```bash
make version-sync
```

Команда синхронизирует `pyproject.toml`, `package.json`, Cargo, Tauri и паспорт версий. `make verify`
запускает тот же механизм в режиме `--check` и останавливает выпуск при любом расхождении. Тесты не
хранят текущее число сборки вручную, а сверяются с контрактом.

Ручной вызов `build_windows_installer.py` допустим для разработки, но не является выпуском.

**[ручками]** Copy the installer/zip to the clean Windows machine.

---

## 4. First launch on the CLEAN target

The Windows core needs **no network** on first launch: CPython, `uv` and the exact
lock-bound dependency cache are inside the installer. Network is needed only if the user chooses
to obtain an external provider or its models. A failed offline sync writes the exact sanitized
`uv` failure to `%LOCALAPPDATA%\LES\logs\bootstrap.log`; an incomplete `.venv` is removed before
retry. The bootstrap also grants the installing interactive user `Modify` on
the persistent state and repaired smeta baseline, so an administrator-assisted
install cannot leave ordinary Tauri/uvicorn without access. Repeated launches
first prove real write access with a temporary file and do not rewrite ACLs.
Only an elevated repair may change the discretionary access list; ordinary
launches never request `SeSecurityPrivilege` or permission to change DACL.
After a successful
first launch it can run offline (local provider).

### macOS

1. Open `LES.dmg`, drag `LES.app` to Applications.
2. First open: because the app is ad-hoc signed (not notarized), Gatekeeper
   blocks it. **[ручками]** right-click → **Open** → **Open** (or
   `System Settings → Privacy & Security → Open Anyway`). One time per machine.
3. The bootstrap runs with no terminal:
   - installs `uv` if missing,
   - `uv sync --extra mac-mlx` (Tauri is already the desktop shell),
   - `lesctl init --profile mac-native`,
   - `onboard_provider.py --skip-if-configured` → sets a **local MLX** default,
   - `onboard_models.py` → downloads weights (first run only, resumable),
   - Tauri waits for health and loads `:8051/les` in the native window.
   Progress = macOS notifications; errors = a dialog; full log in
   `~/Library/Logs/LES/bootstrap.log`.

### Windows

This is the canonical public Windows install path. Release readiness is decided by the exact
Tauri/NSIS artifact installed and smoked on a clean isolated Windows state.

1. Run `LES-Setup.exe` (per-user, **no admin**). It drops the code export under
   the ASCII-only `%LOCALAPPDATA%\Programs\LES` + Start-Menu/Desktop shortcuts. The visible
   product and window name remain «ЛЕС». An already installed Tauri release is updated in its
   existing directory instead of being orphaned during the path transition.
2. First launch: SmartScreen warns (unsigned). **[ручками]** **More info →
   Run anyway**. One time per machine.
3. Ярлык запускает `les-desktop.exe` напрямую. Release EXE собран как Windows GUI application:
   отдельной консоли у Tauri нет, второй запуск тихо завершается по named single-instance mutex,
   а повторные команды setup/restart не создают параллельный bootstrap:
   - separates replaceable code from persistent state: `data`, `storage`,
     `RAG_Content`, `logs`, `artifacts`, `.env` and the uv environment live in
     `%LOCALAPPDATA%\LES`; update-safe directory junctions preserve existing
     relative Python paths,
   - запускает только `installers\windows\app\bootstrap.ps1`; macOS `bootstrap.sh` и
     `installers/macos` исключаются из Windows-пакета во время сборки,
   - on the first updated launch, moves legacy runtime state into a timestamped
     backup, merges only missing files, and records `migration/last_state_init.json`;
     repeated launch is idempotent,
   - проверяет встроенные portable CPython, `uv.exe`, exact `uv.lock` и
     `windows-uv-cache.zip`: archive и lock SHA-256 обязаны совпасть с cache contract,
   - распаковывает Python и dependency cache в persistent state без MSI/реестра; большой cache
     распаковывается самим bundled Python, а не медленным PowerShell `Expand-Archive` (контрольный
     Legion-замер: 39 563 файла за 25,1 с вместо примерно 470 с), затем выполняет
     `uv sync --locked --offline --python <bundled> --no-python-downloads --extra windows-reranker`;
     system Python/uv, winget и network package fallback запрещены,
   - открывает нативный setup catalogue. Он показывает роли, availability и официальные ссылки
     Ollama, FreeToken, Lemonade, OpenAI-compatible API, embeddings и Qdrant, но не устанавливает,
     не выбирает и не настраивает их за пользователя,
   - отсутствие answer engine, embedding engine или Qdrant записывается как предупреждение
     `answer_engine_unavailable`, `embedding_engine_unavailable` или `qdrant_unavailable`;
     запуск LES core продолжается,
   - `lesctl init --profile windows-lite`,
   - не вызывает `ollama pull`, provider/model onboarding, reranker download или Docker Desktop;
     уже работающий Docker/Qdrant может быть обнаружен и использован, но не является core gate,
   - brings the stack up via `start-light.ps1`; proxy/UI и только явно настроенные adapters
     стартуют прямыми `pythonw.exe`/`python.exe` из persistent venv, без `cmd.exe /c uv run` wrappers.
     Tauri открывает live UI, а `windows-light-state.json` хранит реальные PID и
     `process_contract=direct_python_no_console_v1`;
   Ход запуска и незакрытые шаги видны в wizard. Реальные ошибки внутренней подготовки остаются
   внутри этого же экрана с кодом и путём к журналу; приложение не заменяет их общим fatal-screen. Подробный журнал:
   `%LOCALAPPDATA%\LES\logs\bootstrap.log`; машинный статус:
   `%LOCALAPPDATA%\LES\logs\bootstrap-status.json`.
Оба файла создаются до подключения state helper, поэтому даже самая ранняя ошибка запуска
должна оставить читаемую причину. `%LOCALAPPDATA%\ЛЕС` — возможный старый каталог программы,
а не каталог постоянных журналов.

Установочный и updater smoke дополнительно проверяют чистоту lifecycle: terminal bootstrap
обязан завершиться, runtime PID должны принадлежать прямым Python-процессам, LES-owned
`cmd.exe` wrappers запрещены, а после desktop handoff остаётся ровно один `les-desktop.exe`.
Подготовленный updater сохраняет уже прошедшие health-проверку API/UI при запуске нового
desktop shell, поэтому не повторяет полный bootstrap и не устраивает второй цикл подготовки.

После запуска мастер остаётся доступным через tray → **«Настройка и справка»**. Он показывает
текущий LES core и совместимые внешние компоненты. Открытие справки не устанавливает программы,
не останавливает службы и не меняет документы, индексы, модели или чаты. Полный справочник ошибок:
[public/windows-troubleshooting.md](public/windows-troubleshooting.md).

After first launch, **Инструменты → Источники данных → СКАЧАТЬ ФГИС ЦС** starts
the bounded public update: catalogue, latest Split Form for every official price
zone, and the GESN update pipeline. Closed Bearer/captcha surfaces are reported
as unavailable; the updater does not bypass access protection. On Windows the
status endpoint uses a read-only Win32 process probe; polling progress does not
send a signal to or terminate the updater.

---

## 5. Pick / change the engine (provider, key, model)

First-run picks a safe **local** default so the very first chat works. To use a
cloud model or change the model:

- **Primary path (gui-first):** Совушка → **«Настройки»** → провайдер / ключ /
  модель. Applies live (no restart for MLX model switch). This is the canonical
  place; the wizard is only a cold-start convenience.
- **CLI (before the GUI is up, or scripted):**
  ```bash
  uv run python tools/onboard_provider.py                       # interactive
  uv run python tools/onboard_provider.py --provider openrouter --api-key sk-...
  uv run python tools/onboard_provider.py --show                # current provider
  ```
  Writes the same `.env` keys the GUI uses (`LES_LLM_PROVIDER`,
  `<PROVIDER>_MODEL/_API_KEY/_BASE_URL`, `LES_CLOUD_CONSENT`).

Per ADR-11 (LLM-minimalism): local first, cloud opt-in, key never invented.
Cloud providers are **only** OpenRouter / OpenAI (no direct Anthropic).

---

## 6. What still requires money / a signature / a VM — be honest

These are **not** code gaps; they cannot be closed without paid accounts or
real target hardware:

- **Apple notarization** — needs a paid Apple Developer ID, `codesign` with that
  identity, `notarytool submit`, `stapler staple`. Until then every clean Mac
  shows the Gatekeeper prompt (§4) once. Ad-hoc `--sign` is all the build box
  can do.
- **Windows Authenticode** — needs a paid code-signing cert + `signtool`. Until
  then SmartScreen warns once per machine.
- **Windows Tauri/NSIS build host** — the final `.exe` requires Windows. From
  the Mac the builder emits a staged Tauri source zip, not a misleading EXE.
- **Clean-machine smoke** — the only true test of the boxed install is running
  it on a Mac/Windows that has never seen the repo. This **[ручками]** step is
  Олег's: do not assume its result. `tools/clean_install_smoke.py` rehearses the
  *Linux/server* path in a temp clone, but it does not exercise the
  Gatekeeper/SmartScreen/desktop-shell path.

---

### 6.6 Workbook live acceptance (owner-authorized only)

**PENDING: live user-owned input/model acceptance.** The offline suite does not
claim live model quality and must not be used to promote the canonical route.
Only run this after an owner supplies a representative document, an immutable
ordinary-chat profile revision, and a running configured 9B runtime. Do not
use a path below `tests/fixtures`.

The acceptance runtime must be a separate isolated checkout/state process, not
the normal runtime. Before starting that process through the standard launcher,
set `LES_CANONICAL_ACCEPTANCE_STATE_ROOT` to its exact process working
directory. The server exposes this bootstrap factor as read-only `Danger` and
restart-required; an ordinary user, a non-root administrator, an unset factor,
or a different process CWD receives a fail-closed rejection. The configured
attachment root, RAG/meta DB, idempotency DB and workbook checkpoint/artifact
paths must all resolve below that same CWD; candidate upload is rejected before
temporary-file/idempotency persistence otherwise. Do not set it in
the normal runtime. `candidate_acceptance=true` is carried only by the runner;
it enables a candidate execution without a promotion receipt and remains
explicitly traceable as `candidate_acceptance`, never `active` rollout.

Set an optional API key only through the environment (the runner never prints
or persists it), then invoke the opt-in target with all explicit identities:

```powershell
$env:LES_LIVE_WORKBOOK_ACCEPTANCE_API_KEY = '<provided out of band>'
make live-workbook-acceptance LIVE_WORKBOOK_ACCEPTANCE_ARGS='--attachment "C:\real-user-owned\source.xlsx" --base-url http://127.0.0.1:8050 --profile-revision "profile:immutable-revision" --model-preset qwen-9b --out artifacts\live-workbook-acceptance.json'
```

The runner first binds the receipt to `/api/version` 40-hex `git_commit_full`,
positive build, `repo_dirty=false` and `runtime_alignment=aligned`,
then uses the public authenticated attachment and artifact APIs plus the
ordinary chat SSE route. It writes a redacted `live_runtime` receipt only after
revision 1 and correction revision 2 have distinct downloaded SHA-256 values,
exact parent lineage, attachment provenance, profile/model/preset identity,
checkpoint-bound complete monotonic progress, readable XLSX files with a
visible two-cell header and data row beneath it,
`missing_count`/`blocker_count`, and the configured elapsed deadline. The
receipt has an exact typed allowlist and never preserves the source runtime
wording for either array. Repeat with
`--model-preset qwen-35b` only when that configured runtime exists; its contract
must remain identical.

## 7. Quick reference

| Want | Command |
|---|---|
| Regenerate icons | `uv run --with pillow python tools/build_icons.py` |
| Offline gate | `make verify` |
| Current-platform test + native build | `make platform-gate` |
| Build Mac app + dmg | `tools/build_tauri_app.py --version X.Y.Z --bundles app,dmg` |
| Stage/build Win installer | `tools/build_windows_installer.py --version X.Y.Z` |
| Public release through Legion acceptance | `make release RELEASE_ARGS='run --host legion --publish'` |
| Set provider (first run) | `tools/onboard_provider.py [--provider …]` |
| Pre-pull weights | `tools/onboard_models.py [--skip-if-cloud]` |
| Logs (Mac) | `~/Library/Logs/LES/bootstrap.log` |
| Logs (Win) | `%LOCALAPPDATA%\LES\logs\bootstrap.log` |
| Windows persistent data | `%LOCALAPPDATA%\LES\{data,storage,RAG_Content,logs,artifacts}` |
