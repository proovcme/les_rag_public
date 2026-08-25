# Provider-neutral Windows release design

## Goal

Ship a public Windows LES installer whose own runtime works without a
preinstalled Python or uv, and whose setup screen presents compatible external
engines without choosing or installing them for the user.

## Product boundary

`LES-Setup.exe` owns LES only. It contains the exact Windows Python runtime, uv
binary, and an offline dependency payload required by the locked LES runtime.
First launch must not call winget or an internet bootstrap for Python, uv, or
Python packages. A missing or checksum-invalid bundled payload is an installer
integrity failure with a reinstall message and a diagnostic code.

Ollama, FreeToken, Lemonade, OpenAI-compatible services, Docker Desktop, and
Qdrant are external capabilities. LES detects them, explains their role and
links to their own installation/configuration surface, but does not silently
install, launch, select, or download a model. Existing provider settings are
preserved.

## Setup experience

The native Tauri page is a product status and compatibility screen rather than
a six-step Ollama wizard. It has four sections:

1. **LES core** — bundled runtime, application services, and a visible
   preparation/error state.
2. **Answer engine** — cards for Ollama, FreeToken, Lemonade, and an
   OpenAI-compatible endpoint. Each card shows `configured`, `available`, or
   `not detected`; no model is labelled as recommended.
3. **Document search** — the embedding role is explicit. The screen explains
   that an answer engine and an embedding engine can be different; FreeToken is
   currently answer-only in the Windows contract and pairs with the configured
   embedding endpoint (Ollama `bge-m3` in the current production profile).
4. **Local index** — Qdrant status is primary; Docker Desktop appears as the
   currently supported local way to run Qdrant, not as the product itself.

The primary action opens or starts LES once the bundled core is prepared.
Missing external capabilities never disable that action. LES starts in a
degraded state and its normal configuration screen owns provider/model values.
The setup page displays one atomic, accessible status message after each
refresh and retains visible keyboard focus.

## Bootstrap behavior

Windows bootstrap verifies and expands the embedded Python archive, verifies
the embedded uv binary, and synchronizes the persistent venv only from the
embedded offline uv cache. It never falls back to system Python, system uv,
winget, `irm`, or a network package download.

Bootstrap does not write `LES_LLM_PROVIDER=ollama` on a clean install. It does
not require an Ollama answer model, `bge-m3`, Docker, or Qdrant before starting
FastAPI and Sovushka. It records missing external capabilities as structured
warnings. If Docker is available, it may start the existing LES-owned Qdrant
container; otherwise it skips that step without terminating LES.

The setup snapshot is provider-neutral and reports the persisted provider,
loopback reachability for supported local engines, Ollama model inventory when
Ollama is reachable, Qdrant readiness, Docker readiness, and LES core/UI state.
It performs bounded local probes only and never downloads anything.

## Public release

The release is `0.28.1`, build `588`, with a new public README focused on:

- downloading `LES-Setup.exe` from the latest GitHub Release;
- the separation between LES core, answer engine, embeddings, and index;
- compatible choices rather than an Ollama/Qwen prescription;
- local-data boundaries and current public-test limitations;
- developer setup after the end-user quick start.

The current cleaned product tree replaces the diverged public `main` using
`--force-with-lease` only after publication scrub, offline gates, native Tauri
build, real installed-EXE smoke on Legion, and artifact checksum verification.
The GitHub Release contains `LES-Setup.exe`, `LES-Setup.exe.sha256`, and
`latest.json`. Publication is aborted before changing public `main` if any gate
or installed smoke fails.

## Public operations documentation

Public documentation is written for an end user first and an operator second.
The README stays short and points to a dedicated Windows guide and a dedicated
troubleshooting guide. The troubleshooting guide uses a stable incident format:
visible symptom, likely cause, exact read-only check, safe recovery action,
expected result, and log location. It covers at least installer integrity,
WebView2, first-run runtime preparation, locked or broken persistent venv,
occupied ports, answer-provider reachability, missing embeddings, Qdrant/Docker,
updates, and preservation/reset of `%LOCALAPPDATA%\LES`.

Raw stack traces and internal environment keys are not the primary user-facing
instruction. Every documented error code emitted by the Windows bootstrap has
one matching public troubleshooting entry. Destructive reset instructions are
separated, explicitly warn what is preserved or removed, and prefer the checked
in repair/uninstall workflow over manual deletion.

## Non-goals

- No changes under `proxy/smeta_core/**`.
- No automatic installation or updating of third-party engines.
- No bundled language-model weights, embedding-model weights, Docker, or
  Qdrant image.
- No new UI or Markdown-editor dependency.
- No claim that every answer engine also provides embeddings.
