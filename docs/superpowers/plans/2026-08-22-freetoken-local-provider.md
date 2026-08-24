# FreeToken Local Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class local FreeToken provider and make LES chat/RAG/tool routing fit the Legion model and memory constraints.

**Architecture:** A small transport-profile service owns FreeToken locality, request options, and context limits. Existing chat, evidence, agent-router, settings, and Windows startup paths consume that profile without changing smeta-core behavior.

**Tech Stack:** Python 3.12, FastAPI/httpx, pytest, PowerShell, Qdrant, FreeToken OpenAI-compatible API.

**Spec:** `docs/superpowers/specs/2026-08-22-freetoken-local-provider-design.md`

## Global Constraints

- Preserve every unrelated dirty-worktree change.
- Do not modify `proxy/smeta_core/**`.
- Do not add dependencies.
- Do not reindex or delete RAG data.
- Do not commit, push, PR, or publish.

---

### Task 1: FreeToken transport profile

**Files:**
- Create: `proxy/services/llm_transport_profile_service.py`
- Modify: `proxy/routers/chat.py`
- Modify: `backend/inference/routing.py`
- Modify: `proxy/services/runtime_admission.py`
- Test: `tests/test_freetoken_provider.py`

**Interfaces:**
- Produces `apply_transport_options(body, provider)`, `provider_is_local(provider)`, and provider prompt limits.
- `chat._llm_runtime()` produces `LlmRuntime(provider="freetoken", ...)` from `FREETOKEN_*`.

- [ ] Write tests asserting FreeToken is local, resolves loopback configuration, and adds `enable_thinking=false` without mutating the caller's body.
- [ ] Run `uv run pytest tests/test_freetoken_provider.py --basetemp=.test-tmp/freetoken-provider -q` and observe failures caused by the missing service/provider branch.
- [ ] Implement the minimal transport profile and runtime branch.
- [ ] Re-run the focused test and require all cases to pass.

### Task 2: Context-safe evidence generation

**Files:**
- Modify: `proxy/routers/chat.py`
- Modify: `proxy/services/chat_evidence_application_service.py`
- Test: `tests/test_source_excerpts.py`
- Test: `tests/test_freetoken_provider.py`

**Interfaces:**
- `_local_context_budget(..., provider=...)` returns FreeToken-specific chunk/window/evidence limits.
- `fit_prompt_sections(...)` preserves question/system material and caps total prompt characters.

- [ ] Add failing tests for a 120K-character evidence packet producing a prompt under the configured FreeToken ceiling while retaining the question and first source label.
- [ ] Run the focused tests and confirm the prompt-budget assertions fail.
- [ ] Implement provider-aware evidence limits and final prompt fitting.
- [ ] Re-run both focused test files and require all cases to pass.

### Task 3: Tool and router compatibility

**Files:**
- Modify: `proxy/services/query_router.py`
- Modify: `proxy/services/agent_router_service.py`
- Modify: `proxy/services/chat_evidence_application_service.py`
- Test: `tests/test_agent_router.py`
- Test: `tests/test_freetoken_provider.py`

**Interfaces:**
- `QueryIntent.intent` returns `channel` for compatibility.
- Agent-router FreeToken requests use the active FreeToken base/model and no-thinking options.

- [ ] Add failing tests for `QueryIntent.intent`, active-provider router resolution, and a non-empty constrained tool response with the FreeToken body contract.
- [ ] Run the focused tests and confirm failures match the live defects.
- [ ] Implement the compatibility property and shared transport-profile call.
- [ ] Re-run the focused tests and require all cases to pass.

### Task 4: Windows and GUI-owned configuration

**Files:**
- Modify: `installers/windows/start-light.ps1`
- Modify: `proxy/routers/settings.py`
- Modify: `proxy/services/runtime_config_registry_service.py`
- Test: `tests/test_installer_windows.py`
- Test: `tests/test_runtime_config_registry_service.py`

**Interfaces:**
- `start-light.ps1 -Provider freetoken -Model ...` exports FreeToken generation values while leaving Ollama embeddings configured.
- Runtime registry reports FreeToken URL/model/context/prompt ceiling with restart metadata.

- [ ] Add failing behavioral/configuration tests for FreeToken startup and registry visibility.
- [ ] Run the two focused files and confirm the new cases fail.
- [ ] Implement the Windows/provider settings with no secret exposure.
- [ ] Re-run the focused tests and require all cases to pass.

### Task 5: Canon and release bookkeeping

**Files:**
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/SOFTWARE_VERSIONS.md`
- Modify: `docs/RELEASE_LEDGER.md`
- Modify: `config/version.json`

**Interfaces:**
- Product version and build number describe the same FreeToken integration shipped by code.

- [ ] Bump patch SemVer and the monotonic build number once.
- [ ] Document the provider, context budget, and live acceptance criteria in the canonical files.
- [ ] Run version synchronization if required by the repository gate.

### Task 6: Verification, runtime deploy, and Qdrant recovery

**Files:**
- Runtime copy only through the repository deployment workflow after local gates pass.

**Interfaces:**
- Live `/api/status` reports provider/model and `/api/health` reports exact RAG readiness.

- [ ] Run focused provider, agent, chat, installer, and registry tests.
- [ ] Run `make verify` and `make test` (or exact Makefile commands on Windows with workspace-local basetemp).
- [ ] Dry-run runtime deployment, then apply through the checked-in deployment tool and restart only affected LES processes.
- [ ] Inspect Docker/native Qdrant storage and aliases read-only; activate only an existing generation whose contract and exact counts match SQLite.
- [ ] Run live free, RAG, tool, memory, and Qdrant smokes; require FreeToken to remain serving after cleanup.
- [ ] For smeta, follow `docs/superpowers/plans/2026-08-24-freetoken-smeta-layered-acceptance.md` in order. Do not use a full XLSX run to diagnose transport/context/checkpoint failures.
