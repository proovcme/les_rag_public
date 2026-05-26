# LES Runtime Memory Profiles

Updated: 26.05.2026

This document defines the operator-facing runtime model for LES memory control.
The goal is to keep Qdrant, proxy, UI, MLX models, indexing, validation, and
retrieval from competing for the same RAM budget without an explicit state.

The core rule is simple:

```text
Services may be alive, but models are not resident unless a current operation
has an explicit lease for them.
```

No runtime guard is allowed to kill unrelated macOS, GUI, IDE, browser, or user
processes. Guards may unload LES-owned models and stop LES-owned jobs/services.

## Memory States

| State | Condition | Allowed behavior |
|---|---|---|
| `GREEN` | `ram_free_gb >= 12` and `swap_pct <= 40` | New profile actions may start. Short model TTL is allowed. |
| `YELLOW` | `8 <= ram_free_gb < 12` or `40 < swap_pct <= 60` | Heavy actions require explicit profile admission. Models unload immediately after the action. |
| `RED` | `ram_free_gb < 8` or `swap_pct > 60` | No new LLM/index actions. Unload all LES models. Keep only lightweight health checks. |
| `CRITICAL` | `ram_free_gb < 6` or `swap_pct > 75` | Stop LES-owned active jobs and optional UI/proxy if needed. Do not touch foreign processes. |

Use the strictest state if metrics disagree between proxy and MLX host.

## Runtime Profiles

| Profile | Services | Model policy | Allowed actions | Forbidden actions |
|---|---|---|---|---|
| `STOPPED` | none or disabled launchd jobs | no models | none | all runtime work |
| `CORE_IDLE` | Qdrant, MLX Host, proxy | no resident models | health, status, metadata, retrieval debug without generation | auto-index, warmup, chat generation |
| `OBSERVE_UI` | `CORE_IDLE` + UI | no resident models | operator UI, dashboards, read-only checks | index/chat unless admitted separately |
| `RETRIEVAL` | proxy + Qdrant + MLX Host | embedder lazy lease | vector/hybrid retrieval, golden retrieval set | chat, validator, parse scheduler |
| `CHAT` | proxy + Qdrant + MLX Host | main model lazy lease | one chat generation at a time | validator loaded concurrently, indexing |
| `CHAT_VALIDATED` | proxy + Qdrant + MLX Host | main then validator, sequential leases | answer + optional validation | indexing, simultaneous LLM residency under pressure |
| `INDEX_LIGHT` | proxy + Qdrant + MLX Host | embedder lazy lease | small/normal documents, one batch at a time | chat, validator |
| `INDEX_HEAVY_PDF` | proxy + Qdrant + MLX Host, UI normally off | embedder lazy lease, no image/table extras unless admitted | one heavy PDF, foreground or tracked background job | chat, validator, auto-loop |
| `MAINTENANCE` | selected core services | normally no models | lexical index, diagnostics, migrations, snapshots | chat/index unless explicitly reprofiled |

`qwen-index-until-done` launchd is not a default runtime component. It may be
enabled only by an operator decision and only while the active profile is an
indexing profile.

## Model Leases

Every model load must be tied to a lease:

| Lease | Model | Typical profile | Release rule |
|---|---|---|---|
| `embedder` | `Qwen/Qwen3-Embedding-0.6B` | `RETRIEVAL`, `INDEX_LIGHT`, `INDEX_HEAVY_PDF` | unload after request/batch in `YELLOW`; short TTL only in `GREEN` |
| `main` | default chat model | `CHAT`, `CHAT_VALIDATED` | unload after answer in `YELLOW`; short TTL only in `GREEN` |
| `validator` | validator model | `CHAT_VALIDATED` | acquire only after main answer; unload immediately after validation |

Lease admission requires:

1. Current profile allows the requested lease.
2. Memory state is not `RED` or `CRITICAL`.
3. No active conflicting job exists.
4. `main` and `validator` are not resident together unless memory state is
   `GREEN` and the policy explicitly allows it.

## Action Algorithm

Before starting chat, validation, retrieval, or indexing:

1. Read current runtime profile.
2. Read memory snapshot from MLX Host and proxy metrics.
3. Resolve memory state using the strictest snapshot.
4. Check that the action is allowed in the current profile.
5. Acquire the required model lease lazily.
6. Run the operation.
7. Record trace: profile, memory state, lease, unload decision, active jobs.
8. Release the lease:
   - immediately in `YELLOW`;
   - immediately after validation;
   - immediately after indexing batch;
   - after short TTL only in `GREEN`.
9. If post-action state is `RED`, unload all LES models.
10. If post-action state is `CRITICAL`, stop LES-owned active jobs and optional
    UI/proxy, then leave Qdrant/MLX Host idle only if they are stable.

## Admission Matrix

| Action | Required profile | Required memory | Required active jobs |
|---|---|---|---|
| Read-only status | any non-stopped profile | any | any |
| Retrieval debug | `RETRIEVAL`, `CHAT`, `CHAT_VALIDATED`, `OBSERVE_UI` | not `RED` | no index job |
| Chat without validator | `CHAT` | `GREEN` or `YELLOW` | `active_jobs = 0` |
| Chat with validator | `CHAT_VALIDATED` | preferably `GREEN`; `YELLOW` only with sequential unload | `active_jobs = 0` |
| Light indexing | `INDEX_LIGHT` | `GREEN` or high `YELLOW` | no chat/validator job |
| Heavy PDF indexing | `INDEX_HEAVY_PDF` | `GREEN` strongly preferred | no chat/validator job; UI off by default |
| Lexical index build | `MAINTENANCE` | `GREEN` or `YELLOW` | no parse/chat job |

## Heavy PDF Rule

Heavy PDF parsing is a separate profile, not normal indexing.

Observed failure mode:

- A 40 MB book PDF with `markdown_pdf_tables` drove proxy RSS above 7 GB.
- Disabling image/table extraction reduced scope but did not solve the memory
  peak because the current converter still materializes too much document state.
- The safe response is to stop parse, unload models, and require a streaming or
  page-windowed PDF pipeline before retrying.

Until that pipeline exists:

1. Do not run heavy book PDFs through auto-index loops.
2. Do not run UI, chat, validator, or reranker while indexing a heavy PDF.
3. Use one tracked job only.
4. Stop immediately if `ram_free_gb < 8` or `swap_pct > 60`.

The launchd auto-index loop must treat a heavy-only pending queue as manual
admission work: log `heavy_pending_only`, do not start a parse job, and restore
`CHAT` mode before exiting.

## Operator Defaults

Safe startup:

```bash
uv run python tools/les_runtime_control.py memory-preflight --offer-kill
uv run python tools/les_runtime_control.py start qdrant
uv run python tools/les_runtime_control.py start mlx
uv run python tools/les_runtime_control.py start proxy
uv run python tools/les_runtime_control.py start ui
```

`start_les.command` runs the same memory preflight automatically before
`start-core`. It prints the largest resident processes and, only in an
interactive terminal, asks which non-LES, non-protected candidates should receive
`SIGTERM`. Press Enter to skip. It never kills foreign processes without an
explicit selection.

Runtime status checks must use lightweight health endpoints. For Sovushka UI,
use `/healthz`. The default `/` route is the static Sovushka Lite chat shell;
do not use `/classic` or `/les` as health probes because those routes render
NiceGUI pages and can create large server-side client state.

Safe session close:

```bash
uv run python tools/les_runtime_control.py stop ui
uv run python tools/les_runtime_control.py stop proxy
curl -fsS -X POST http://127.0.0.1:8080/api/unload_all || true
uv run python tools/les_runtime_control.py stop mlx
uv run python tools/les_runtime_control.py stop qdrant
```

Safe status:

```bash
uv run python tools/les_runtime_control.py status
launchctl print-disabled gui/$(id -u) | rg -i 'me\.ovc\.les|com\.les\.sovushka|ollama|qwen-index'
```

## UI Requirements

UI should show the active profile and memory state directly:

- profile chip: `CORE_IDLE`, `OBSERVE_UI`, `CHAT`, `INDEX_LIGHT`, etc.;
- memory chip: `GREEN`, `YELLOW`, `RED`, `CRITICAL`;
- model chips: `main`, `validator`, `embedder`, each `loaded` or `idle`;
- action denial reason, for example `ram_free_gb=7.7 < 8.0`;
- active job count from `/api/jobs/summary`, not full `/api/jobs`.

The UI must not present runtime pause as indexing unless the active profile is
actually an indexing profile.

## Runtime API Surface

The proxy exposes the active profile and memory state through the same admission
path used by chat/runtime controls:

- `/api/status` returns `runtime_profile`, `memory_state`, and
  `chat_admission.runtime_profile`;
- `/api/indexing-mode` returns `runtime_profile`, `memory_state`, and the full
  `chat_admission` payload;
- parse scheduler results include the active `runtime_profile`;
- `GREEN/YELLOW/RED/CRITICAL` thresholds are centralized in
  `proxy/services/runtime_admission.py`.

## Implementation Target

The desired implementation shape is:

```text
RuntimeProfileManager
  -> current profile
  -> allowed actions
  -> operator transitions

MemoryGovernor
  -> memory state
  -> admission decisions
  -> unload/stop decisions for LES-owned resources only

ModelLeaseManager
  -> lazy acquire
  -> conflict checks
  -> TTL/unload policy
```

Chat, validator, retrieval, parse scheduler, baselines, and UI controls should
all call the same admission path. No component should invent its own memory
thresholds without routing through the governor.
