# LES Platform Profiles

LES should ship as a product family, not as one Mac workstation script.

## Supported Targets

| Target | Status | Runtime Manager | Model Runtime | Vector DB | Notes |
|---|---|---|---|---|---|
| macOS Apple Silicon native | Current reference | launchd | MLX/Core ML | local Qdrant binary | Best local private workstation profile |
| Linux server | Packaging target | systemd or Docker Compose | OpenAI-compatible local host, Ollama, llama.cpp, vLLM, remote provider | Qdrant Docker/native | Secondary server profile |
| Windows workstation | **Primary production target (Legion)** | PowerShell + Tauri bootstrap / Docker Desktop for Qdrant | Ollama is required local runtime; OpenAI-compatible provider is explicit opt-in | Qdrant in named Docker volume | Canonical production profile; CPython and `uv` are bundled, Ollama and Docker remain first-launch requirements |
| Lite mode | Packaging target | any | remote/OpenRouter/OpenAI-compatible | local or remote Qdrant | No local heavy model requirement |

## Runtime Abstractions

LES must not hard-code platform decisions in product code. Platform profiles should select these adapters:

| Adapter | macOS Native | Linux Server | Windows Workstation |
|---|---|---|---|
| service manager | launchd | systemd / Docker Compose | PowerShell service / Docker Desktop |
| model host | MLX/Core ML | Ollama, llama.cpp, vLLM, OpenAI-compatible | remote provider, Ollama/llama.cpp, Lemonade via `lemonade_host.py`, OpenAI-compatible |
| embeddings | Core ML Qwen | sentence-transformers, remote embeddings, OpenAI-compatible | Ollama/Lemonade-compatible `/v1/embeddings`, remote embeddings, sentence-transformers |
| vector store | Qdrant binary | Qdrant Docker/native | Qdrant Docker named volume or remote |
| UI | Tauri 2 shell → NiceGUI Sovushka | NiceGUI Sovushka in browser | Tauri 2 shell → NiceGUI Sovushka |

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
- On Windows with `Provider=lemonade`, keep `lemonade_host.py` between LES and
  Lemonade so `MLX_URL` still exposes embeddings, rerank, unload and model
  switch endpoints expected by shared runtime code.
- On `windows-lite` with Ollama, keep `OLLAMA_MODEL` and the provider-neutral
  `LLM_MODEL` identical. Model-owned document/smeta turns follow that configured
  local runtime; embeddings use `bge-m3` at 1024 dimensions.
- The canonical Windows/Tauri bootstrap carries SHA-256-verified CPython and `uv`; it still requires
  Ollama and Docker Desktop,
  installs missing components through winget where possible, and must fail with
  an explicit installation URL instead of opening a UI with unavailable RAG.
- Legion production additionally requires the native multilingual cross-encoder
  `BAAI/bge-reranker-v2-m3`: the answer model must not rerank its own
  evidence pool. The production RAG path remains named dense + BM25 sparse,
  native RRF, common rerank and parent/context expansion.

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

The canonical desktop package is `desktop/tauri`: Rust/Tauri owns the native
window, tray and lifecycle; Python/FastAPI/NiceGUI remains the shared runtime.

| Profile | Installer |
|---|---|
| `mac-native` | `uv run python tools/build_tauri_app.py --version X.Y.Z --bundles app,dmg` |
| `linux-docker` | `installers/linux/install.sh --profile linux-docker` |
| `linux-systemd` | `installers/linux/install.sh --profile linux-systemd --install-units` |
| `windows-docker` | `installers/windows/install.ps1 -Profile windows-docker` |
| `windows-lite` | on Windows: `uv run python tools/build_windows_installer.py --version X.Y.Z` |
| `server-remote-model` | `uv run lesctl install --profile server-remote-model` |

Docker profiles use `installers/<platform>/docker-compose.yml` and a named
Qdrant volume. Systemd profile installs user units for `les-proxy` and `les-ui`;
Qdrant/model runtime remain explicit operator choices for now.

The canonical Windows/Tauri profile also keeps mutable state outside the
replaceable NSIS application tree: `%LOCALAPPDATA%\LES` owns `.env`, uv venv,
MetaDB, source/storage data, artifacts and logs. Runtime-relative directories
are junctions to that root; Qdrant uses `les-qdrant-data`.

## Automated platform gates and release

`.github/workflows/verify.yml` runs the canonical Python suite and a real
`tauri build --no-bundle` on `macos-14` and `windows-2022` for every PR and
push to `main`. Clean runners download the private immutable prerelease fixture
`ci-smeta-baseline-20260728`, verify its manifest/SHA/counts through
`tools.smeta_release_baseline` and provision only linked ФГИС/ФСНБ/FSEM files
plus the verified default Saint Petersburg resource pricebook before pytest.
This is not user RAG or production state. CoreML cache helpers
remain importable on Windows without POSIX `fcntl`; CoreML inference itself
stays macOS-only. This proves both native shells compile without pretending
that a hosted runner has installed Ollama/Qdrant.

The production workflow is intentionally separate:
`.github/workflows/release.yml` runs on the approved self-hosted Mac release
runner. `tools/multiplatform_release.py` builds and verifies `LES.app`/`LES.dmg`,
then uses the existing SSH Legion contour to build/install/smoke the real NSIS
package. The boxed smeta baseline includes its default verified regional
pricebook because FSEM-derived machinist rows cannot be priced reproducibly
without it; additional regional books remain an FGIS update concern. GitHub
release creation receives the verified Mac and Windows assets
in one command; either platform failing blocks publication. The Windows bundle
gets only the verified immutable FGIS/FSNB smeta baseline. User RAG data is
never bundled. Release environment secret `LES_RELEASE_TOKEN` needs Actions
read for the private source repository and Contents write for
`proovcme/les_rag_public`; SSH access to Legion stays on the approved runner.

Mac reinstall stress is documented in `docs/MAC_REINSTALL_STRESS.md`; the
uninstall script is dry-run by default and requires explicit confirmation before
removing launchd services or runtime data.
