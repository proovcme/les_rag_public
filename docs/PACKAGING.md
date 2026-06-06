# LES Packaging Plan

Goal: turn LES into a boxed solution for macOS, Linux and Windows while keeping АТЛАС and АРТЕЛЬ as separate products that consume LES APIs.

## Product Editions

| Edition | Target | Includes |
|---|---|---|
| LES Native Mac | Apple Silicon workstation | launchd services, MLX/Core ML, local Qdrant, Sovushka Lite |
| LES Server Linux | Linux host/VPS/private server | Docker Compose or systemd, Qdrant, provider-configurable model host |
| LES Workstation Windows | Windows BIM workstation | PowerShell installer, Docker/remote Qdrant, browser UI, Revit/ARTEL integration |
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

Current command entrypoints are `les-install` and `les-runtime`; the next step is to expose a single `lesctl` facade.

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
- АРТЕЛЬ uses `/api/search` for task context and future structured import for `FamilyLearningCase`.
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

Model files and private corpora are not shipped inside these archives.

Build LES artifacts with:

```bash
uv run python tools/build_release_artifacts.py --profile linux-docker
uv run python tools/build_release_artifacts.py --profile linux-systemd
uv run python tools/build_release_artifacts.py --profile windows-docker
uv run python tools/build_release_artifacts.py --profile windows-lite
```

## Acceptance Gates

Before a boxed release:

- full unit tests pass;
- `uv lock --check` passes;
- `git diff --check` passes;
- `lesctl doctor` passes for the target profile;
- `/api/health` returns `ok`;
- `/api/search` returns a valid response;
- Qdrant data is stored in the correct profile path/volume;
- docs for that platform are current;
- no `.env`, corpora, logs, snapshots or private samples are in the artifact.

## Immediate Next Work

1. Add ARTEL `FamilyLearningCase` import contract.
2. Run destructive Mac reinstall stress on a backed-up host.
3. Add actual Linux systemd Qdrant/model unit templates.
4. Add Windows service wrapper after Docker/lite smoke on a real Windows host.
5. Add hub repository README for LES / АТЛАС / АРТЕЛЬ.
