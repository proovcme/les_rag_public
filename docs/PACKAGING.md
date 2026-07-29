# LES Packaging Plan

Goal: turn LES into a boxed solution for macOS, Linux and Windows while keeping АТЛАС and АРТЕЛЬ as separate products that consume LES APIs. ARTEL is never bundled into a LES installer.

## Product Editions

| Edition | Target | Includes |
|---|---|---|
| LES Native Mac | Apple Silicon workstation | launchd services, MLX/Core ML, local Qdrant, Sovushka Lite |
| LES Server Linux | Linux host/VPS/private server | Docker Compose or systemd, Qdrant, provider-configurable model host |
| LES Workstation Windows | Windows BIM workstation | PowerShell installer, Docker/remote Qdrant, browser UI; ARTEL ships separately |
| LES Lite | any platform | retrieval/search, remote model provider, no local heavy model |
| LES Viewer Pack | offline/field machines | АТЛАС standalone, demo data, optional LES search endpoint |

## Delivery Stages

### Stage 1: Installer Discipline

- `lesctl doctor`
- `lesctl install`
- `lesctl init`
- `lesctl start`
- `lesctl stop`
- `lesctl status`
- `lesctl smoke`

Current command entrypoint is the `lesctl` facade. Legacy helper entrypoints `les-install` and `les-runtime` remain available for direct checks and launchd control.

Current boxed entrypoints:

```text
installers/macos/install.sh
installers/macos/uninstall.sh
installers/linux/install.sh
installers/windows/install.ps1
tools/build_release_artifacts.py
tools/clean_install_smoke.py
```

### Stage 2: Platform Profiles

Add config profiles:

```text
config/profiles/mac-native.yaml
config/profiles/linux-docker.yaml
config/profiles/linux-systemd.yaml
config/profiles/windows-docker.yaml
config/profiles/windows-lite.yaml
config/profiles/server-remote-model.yaml
```

Each profile must define:

- service manager;
- model provider;
- embedding provider;
- Qdrant mode;
- storage paths;
- ports;
- auth defaults;
- smoke expectations.

### Stage 3: Cross-Platform Service Managers

| Platform | Manager |
|---|---|
| macOS | launchd |
| Linux | systemd and Docker Compose |
| Windows | PowerShell service wrapper and Docker Desktop |

Do not let runtime code depend on one manager. The manager is an install/start adapter.

### Stage 4: Provider Abstraction

LES needs explicit provider profiles:

- `local_mlx_coreml`
- `openai_compatible`
- `ollama`
- `llama_cpp`
- `vllm`
- `openrouter_lite`

The stable product APIs are:

- `/api/health`
- `/api/search`
- `/api/chat`
- `/api/cad-bim/import`
- `/api/rag/*`

### Stage 5: Product Integration

- АТЛАС uses `/api/search`, `/api/cad-bim/source`, `/api/cad-bim/element`, `/api/chat` only for optional Ask LES.
- АРТЕЛЬ uses `/api/search` for task context and public-safe `FamilyLearningCase` seed/import into `ARTEL_Index`.
- Revit add-ins call АРТЕЛЬ, not LES directly.

### Stage 6: Release Artifacts

Produce separate artifacts:

```text
les-mac-native.tar.gz
les-linux-docker.tar.gz
les-windows-docker.zip
atlas-standalone.zip
artel-mvp.zip
```

Model files and private project corpora are not shipped inside these archives. The Windows installer
is the deliberate exception for the immutable estimating baseline: canonical typed GESN SQLite,
its source/manifest/integrity report and the FSEM SQLite/manifest are packed by
`tools/smeta_release_baseline.py` only after SHA, provenance and completeness gates pass.
This is a normative/resource baseline, not a universal price book: regional split forms, indices and
project KAC/KP stay outside the installer and are selected for an explicit price zone and period.
The patch releaser accepts either `--smeta-baseline-root <operator-root>` or an already generated
`--smeta-baseline-archive dist/LES-smeta-baseline.zip`; the archive remains a local release input,
not a git-tracked corpus.
The same applies to the separate ARTEL source/product tree, its tools, fixtures and tests.

Build LES artifacts with:

```bash
uv run python tools/build_release_artifacts.py --profile linux-docker
uv run python tools/build_release_artifacts.py --profile linux-systemd
uv run python tools/build_release_artifacts.py --profile windows-docker
uv run python tools/build_release_artifacts.py --profile windows-lite
```

Build АТЛАС standalone artifact with:

```bash
npm ci --prefix frontend/cad_bim_viewer
npm run build --prefix frontend/cad_bim_viewer
npm run build:standalone --prefix frontend/cad_bim_viewer
uv run python tools/smoke_atlas_standalone.py
uv run python tools/check_atlas_bundle_budget.py
uv run python tools/build_atlas_release.py
```

АРТЕЛЬ собирается и выпускается из канонического репозитория
<https://github.com/proovcme/Agnostis>. `products/artel` в LES — только pinned
git-submodule для интеграционных тестов и связи с ARTEL Index; LES не владеет
сборкой ARTEL installer.

## Acceptance Gates

Before a boxed release:

- `make test-release` passes for the LES package; repository-wide `make test` additionally checks the separate ARTEL product;
- `uv lock --check` passes;
- `git diff --check` passes;
- `lesctl doctor` passes for the target profile;
- `/api/health` returns `ok`;
- `/api/search` returns a valid response;
- Qdrant data is stored in the correct profile path/volume;
- docs for that platform are current;
- no `.env`, corpora, logs, snapshots or private samples are in the artifact.
- Windows contains `LES-smeta-baseline.zip`; clean-install bootstrap provisions it only into an empty
  persistent state, while release smoke requires at least 40 000 GESN norms and 1 500 FSEM rows.
- Windows does not claim complete monetary pricing until an applicable regional split form is selected;
  absent prices remain `MISSING`.
- АТЛАС zip contains `ATLAS_MANIFEST.json` and excludes private `JSON/` and `ifc-sample/` folders.
- АТЛАС bundle budget passes so dependency drift is explicit.
- ARTEL submodule инициализирован на зафиксированном commit; выпускной gate самого ARTEL выполняется в репозитории Agnostis.

## Immediate Next Work

1. Smoke `les-v0.1.0-linux-docker.tar.gz` on a real Docker host.
2. Smoke Windows Docker/lite artifacts on a real Windows workstation.
3. Keep the public-safe ARTEL seed flow green on every fresh runtime:
   `uv run python tools/seed_artel_learning_cases.py --verify-search`.
4. Add actual Linux systemd Qdrant/model unit templates.
5. Extend ARTEL `FamilyLearningCase` import from demo seed to accepted internal cases.
6. Add hub repository README for LES / АТЛАС / АРТЕЛЬ.
7. Add Windows hand-test evidence for ARTEL seeded retrieval.

Completed on 2026-06-06:

- destructive Mac reinstall stress from fresh clone;
- private `v0.1.0` boxed release;
- public `v0.1.2-public-boxed-install` snapshot release.
- LES umbrella product layout with `products/atlas` and `products/artel`;
- repeatable `atlas-standalone.zip` build and smoke scripts.
- repeatable `artel-mvp.zip` hand-test build script.
- public-safe ARTEL `FamilyLearningCase` schema/example and targeted `ARTEL_Index` seed tool.
