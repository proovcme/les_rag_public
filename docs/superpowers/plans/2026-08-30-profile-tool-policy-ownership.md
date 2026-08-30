# Profile Tool Policy Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the unused duplicate tool allowlists from `ProfileResolver` and make the trace identify the live chat-profile snapshot as the owner of tool policy.

**Architecture:** `ProfileResolver` remains responsible only for route/profile/output-policy selection. `chat_profile_service` continues to build allowlists from the live `ToolHarness` registry, and `chat_evidence_application_service` continues to enforce the immutable per-chat snapshot.

**Tech Stack:** Python 3.12, dataclasses, pytest, FastAPI chat trace.

**Spec:** `docs/ALGO-routing.md`

## Global Constraints

- Do not modify `proxy/smeta_core/**` or smeta behavior.
- Do not change the effective tool catalog or selected chat-profile snapshots.
- Do not deploy or alter the installed Legion runtime.
- Increment `config/version.json` and update the release ledger in the same commit.

---

### Task 1: Make tool-policy ownership truthful

**Files:**
- Modify: `tests/test_profile_resolver.py`
- Modify: `tests/test_code_runtime_map.py`
- Modify: `proxy/services/profile_resolver.py`
- Modify: `docs/ALGO-routing.md`
- Modify: `docs/modules/chat-profiles.md`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: `resolve(mode: str | None, question: str) -> ProfileResolution` and `ProfileResolution.as_trace() -> dict`.
- Produces: trace field `tool_policy_source="chat_profile_snapshot"`; `Profile` no longer exposes a dead `tools` tuple.

- [x] **Step 1: Write the failing behavior test**

Add a test asserting that every resolved profile trace names `chat_profile_snapshot` as the tool-policy source. Remove tests that inspect the dead duplicate tuples.

- [x] **Step 2: Run the focused test and verify RED**

Run: `uv run pytest tests/test_profile_resolver.py -q --basetemp=.test-tmp/profile-tool-policy-red`

Expected: FAIL because `tool_policy_source` is absent.

- [x] **Step 3: Implement the minimal ownership correction**

Remove `Profile.tools`, remove the four duplicate tuples, and emit `tool_policy_source` from `as_trace()`. Keep all route, validation, failure, and output policies unchanged.

- [x] **Step 4: Update current documentation and version ledger**

Document that the live allowlist is generated from `ToolHarness`, stored in the immutable chat snapshot, and enforced by the evidence application. Set version `0.30.19`, build `659`, desktop `5.1.659`.

- [x] **Step 5: Run focused and required gates**

Run focused profile/chat-profile tests, then `make architecture-gate`, `make verify`, and `make test`.

- [x] **Step 6: Commit the cleanup**

Commit message: `chore: remove duplicate profile tool policy`
