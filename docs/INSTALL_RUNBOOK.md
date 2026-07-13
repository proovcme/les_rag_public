# INSTALL_RUNBOOK — boxed install on a clean Mac / Windows

Operator runbook for taking ЛЕС from a fresh repo to a double-click app on a
**clean target machine**. This is the honest version: every step that needs a
human at a real Mac/Windows box, an Apple/Microsoft signature, or a VM is marked
**[ручками]** (manual / cannot be done in CI or on the build box).

Audience: Олег. Build box = your dev Mac. Target = the clean machine the app
ships to.

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

### Каноническая сборка и публикация Windows-выпуска

Собирать выпуск только из чистого, отправленного в `origin` коммита. Нельзя переименовывать старый
EXE под новую версию или публиковать `latest.json` раньше проверенного установщика.

1. На машине разработки закрыть кодовый гейт и отправить коммит:

   ```bash
   make test
   make verify
   make test-rag-core
   make public-check
   uv lock --check
   git diff --check
   git push origin feat/les3-p1
   ```

2. На Legion обновить чистый checkout строго fast-forward и собрать Tauri/NSIS:

   ```powershell
   Set-Location C:\Users\Oleg\les_rag
   git fetch origin
   git checkout feat/les3-p1
   git pull --ff-only origin feat/les3-p1
   git status --short
   uv run python tools/build_windows_installer.py --version 0.24.0.406
   ```

   Результат обязан находиться в `dist\LES-Setup.exe`. Перед публикацией проверить, что
   `proxy\services\version_service.py` и staged runtime содержат ту же версию, Tauri получил
   desktop-версию `5.1.406`, а checkout всё ещё указывает на выпускной commit.

3. Получить размер и контрольную сумму, создать соседний файл:

   ```powershell
   $exe = Resolve-Path .\dist\LES-Setup.exe
   $sha = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLowerInvariant()
   "$sha  LES-Setup.exe" | Set-Content .\dist\LES-Setup.exe.sha256 -Encoding ascii
   Get-Item $exe | Select-Object FullName,Length,LastWriteTime
   Get-Content .\dist\LES-Setup.exe.sha256
   ```

4. Проверить установщик на Legion двумя путями:

   - чистая установка без готового состояния: bootstrap либо ставит обязательные `uv`, Ollama и
     Docker Desktop через winget, либо показывает точную причину, официальный адрес и журнал;
   - обновление поверх предыдущего выпуска: сохраняются `.env`, Qdrant volume, MetaDB,
     `RAG_Content`, `storage` и артефакты, после запуска `/api/version` показывает новую версию.

5. Создать `dist\latest.json` по схеме `les.update.v1`. Обязательны `version`, `name`, `notes`,
   `published_at`, `html_url`; дополнительно фиксировать `build_commit`. Затем опубликовать ровно
   три файла с неизменными именами:

   ```bash
   gh release create v0.24.0.406 \
     dist/LES-Setup.exe \
     dist/LES-Setup.exe.sha256 \
     dist/latest.json \
     --repo proovcme/les_rag_public \
     --title "ЛЕС 0.24.0.406" \
     --notes-file dist/release-notes.md
   ```

6. После публикации проверить не страницу, а реальные assets и updater:

   ```bash
   gh release view v0.24.0.406 --repo proovcme/les_rag_public --json tagName,assets,url
   curl -fsSL https://github.com/proovcme/les_rag_public/releases/latest/download/latest.json
   curl -fsSL https://github.com/proovcme/les_rag_public/releases/download/v0.24.0.406/LES-Setup.exe.sha256
   ```

   Установленный предыдущий выпуск должен показать `.406` по кнопке «Проверить обновление»,
   скачать EXE, самостоятельно сверить SHA-256 и только затем запустить NSIS. Фактический размер,
   SHA-256, commit, результаты чистой установки и обновления записываются в
   `docs/RELEASE_LEDGER.md` в том же выпускном коммите.

**[ручками]** Copy the installer/zip to the clean Windows machine.

---

## 4. First launch on the CLEAN target

The target needs **network** on first launch (uv install, `uv sync`, optional
model-weight download). After that it can run offline (local provider).

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

This is the canonical production install path for **Legion**. Mac builds remain
development/reference artifacts; release readiness is decided by the live
Windows RAG/chat smoke and the Windows Tauri/NSIS artifact.

1. Run `LES-Setup.exe` (per-user, **no admin**). It drops the code export under
   `%LOCALAPPDATA%\Programs\LES` + Start-Menu/Desktop shortcuts.
2. First launch: SmartScreen warns (unsigned). **[ручками]** **More info →
   Run anyway**. One time per machine.
3. The shortcut → `launcher.vbs` (hidden) → `bootstrap.ps1`:
   - separates replaceable code from persistent state: `data`, `storage`,
     `RAG_Content`, `logs`, `artifacts`, `.env` and the uv environment live in
     `%LOCALAPPDATA%\LES`; update-safe directory junctions preserve existing
     relative Python paths,
   - on the first updated launch, moves legacy runtime state into a timestamped
     backup, merges only missing files, and records `migration/last_state_init.json`;
     repeated launch is idempotent,
   - проверяет обязательные компоненты Windows: `uv`, Ollama и Docker Desktop;
     отсутствующий `uv` ставит через winget или официальный скрипт, Ollama и Docker Desktop —
     через winget; если автоматическая установка недоступна, окно ЛЕС показывает точную причину,
     официальный адрес установки и путь к журналу,
   - после установки Docker Desktop ждёт запуска движка; незавершённая настройка WSL 2 или
     необходимость перезагрузки считаются явной ошибкой первого запуска, а не «ограниченным RAG»,
   - `uv sync` (no MLX and no pywebview on Windows),
   - `lesctl init --profile windows-lite`,
   - `onboard_provider.py --skip-if-configured --provider ollama` → local
     **ollama** default (no cloud key needed to boot),
   - `start-light.ps1` keeps the selected Ollama tag in both `OLLAMA_MODEL` and
     the provider-neutral `LLM_MODEL`; all model-owned attachment/smeta steps
     therefore use the same local runtime instead of falling back to a Mac MLX
     name,
   - embeddings use Ollama `bge-m3` (`1024` dimensions) for the shared
     dense+sparse/RRF index contract,
   - bootstrap verifies/pulls the local answer model `qwen3.5:9b`, embedding
     model `bge-m3:latest` and installs/prefetches the native multilingual
     cross-encoder `BAAI/bge-reranker-v2-m3`; its weights are checksum-verified,
     corrupt cache entries are quarantined, an interrupted `.incomplete` download
     resumes, and a semantic load-probe runs before the cache is marked ready,
     with bounded `HF_MIRROR_ENDPOINT` fallback when the official Hub is unavailable,
   - `onboard_models.py --skip-if-cloud`,
   - запускает обязательный Qdrant в Docker с постоянным именованным томом
     `les-qdrant-data` и ждёт ответа `/collections`,
   - brings the stack up via `start-light.ps1`; Tauri opens the live UI.
   Ход запуска виден через уведомления. При ошибке Tauri показывает её код, официальный адрес
   установки недостающего компонента и путь к журналу. Подробный журнал:
   `%LOCALAPPDATA%\LES\logs\bootstrap.log`; машинный статус:
   `%LOCALAPPDATA%\LES\logs\bootstrap-status.json`.

На чистой Windows Docker Desktop может запросить повышение прав и завершение настройки WSL 2.
Это штатное системное требование Docker. После установки или перезагрузки достаточно снова открыть
ЛЕС: bootstrap идемпотентен и продолжит с незавершённого предусловия.

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

## 7. Quick reference

| Want | Command |
|---|---|
| Regenerate icons | `uv run --with pillow python tools/build_icons.py` |
| Offline gate | `make verify` |
| Build Mac app + dmg | `tools/build_tauri_app.py --version X.Y.Z --bundles app,dmg` |
| Stage/build Win installer | `tools/build_windows_installer.py --version X.Y.Z` |
| Set provider (first run) | `tools/onboard_provider.py [--provider …]` |
| Pre-pull weights | `tools/onboard_models.py [--skip-if-cloud]` |
| Logs (Mac) | `~/Library/Logs/LES/bootstrap.log` |
| Logs (Win) | `%LOCALAPPDATA%\LES\logs\bootstrap.log` |
| Windows persistent data | `%LOCALAPPDATA%\LES\{data,storage,RAG_Content,logs,artifacts}` |
