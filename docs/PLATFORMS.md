# LES Platform Profiles

LES should ship as a product family, not as one Mac workstation script.

## Supported Targets

| Target | Status | Runtime Manager | Model Runtime | Vector DB | Notes |
|---|---|---|---|---|---|
| macOS Apple Silicon native | Current reference | launchd | MLX/Core ML | local Qdrant binary | Best local private workstation profile |
| Linux server | Packaging target | systemd or Docker Compose | OpenAI-compatible local host, Ollama, llama.cpp, vLLM, remote provider | Qdrant Docker/native | Primary production box target |
| Windows workstation | Packaging target | PowerShell + Windows service or Docker Desktop | remote LES/model host, Ollama/llama.cpp, OpenAI-compatible provider | Qdrant named Docker volume or remote Qdrant | Best paired with Revit/ARTEL add-ins |
| Lite mode | Packaging target | any | remote/OpenRouter/OpenAI-compatible | local or remote Qdrant | No local heavy model requirement |

## Runtime Abstractions

LES must not hard-code platform decisions in product code. Platform profiles should select these adapters:

| Adapter | macOS Native | Linux Server | Windows Workstation |
|---|---|---|---|
| service manager | launchd | systemd / Docker Compose | PowerShell service / Docker Desktop |
| model host | MLX/Core ML | Ollama, llama.cpp, vLLM, OpenAI-compatible | remote provider, Ollama/llama.cpp, OpenAI-compatible |
| embeddings | Core ML Qwen | sentence-transformers, remote embeddings, OpenAI-compatible | remote embeddings, sentence-transformers |
| vector store | Qdrant binary | Qdrant Docker/native | Qdrant Docker named volume or remote |
| UI | Sovushka Lite | Sovushka Lite | browser to local/remote LES |

## Profile Names

Use these names consistently in docs, install scripts and future config files:

- `mac-native`
- `linux-docker`
- `linux-systemd`
- `windows-docker`
- `windows-lite`
- `server-remote-model`

## Platform Rules

- Keep LES API stable across all profiles.
- Keep `/api/search` as the fast product contract for АТЛАС and АРТЕЛЬ.
- Keep `/api/chat` optional; products should not depend on local generation for basic UX.
- Keep Qdrant data in named volumes on Windows Docker to avoid bind-mount fragility.
- Keep model downloads outside Docker images.
- Keep private corpora out of install packages.
- Treat launchd/systemd/Windows service logic as adapters behind `lesctl`.

## Minimum Smoke

Every platform profile must pass:

```bash
lesctl doctor --profile <profile>
lesctl init --profile <profile>
lesctl start --profile <profile>
curl -fsS http://127.0.0.1:8050/api/health
curl -fsS http://127.0.0.1:8050/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"smoke","top_k":1}'
```

For profiles without local generation, `/api/chat` may be disabled or routed to a configured provider, but `/api/search` must remain available.

## Installer Entrypoints

| Profile | Installer |
|---|---|
| `mac-native` | `uv run lesctl init --profile mac-native` then `installers/macos/install.sh` or `uv run lesctl install --profile mac-native` |
| `linux-docker` | `installers/linux/install.sh --profile linux-docker` |
| `linux-systemd` | `installers/linux/install.sh --profile linux-systemd --install-units` |
| `windows-docker` | `installers/windows/install.ps1 -Profile windows-docker` |
| `windows-lite` | `installers/windows/install.ps1 -Profile windows-lite` |
| `server-remote-model` | `uv run lesctl install --profile server-remote-model` |

Docker profiles use `installers/<platform>/docker-compose.yml` and a named
Qdrant volume. Systemd profile installs user units for `les-proxy` and `les-ui`;
Qdrant/model runtime remain explicit operator choices for now.

Mac reinstall stress is documented in `docs/MAC_REINSTALL_STRESS.md`; the
uninstall script is dry-run by default and requires explicit confirmation before
removing launchd services or runtime data.
