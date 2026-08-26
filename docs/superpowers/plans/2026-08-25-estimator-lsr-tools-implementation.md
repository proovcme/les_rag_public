# Estimator LSR/VOR Tools Implementation Plan

> **SUPERSEDED — DO NOT EXECUTE:** This plan creates the rejected parallel
> `estimate_*` tool family. The active architecture uses PR13's stable
> `build_lsr_workbook` / `build_vor_workbook` contracts through the canonical
> registry and executor. See
> [../specs/2026-08-26-canonical-tool-context-memory-update-design.md](../specs/2026-08-26-canonical-tool-context-memory-update-design.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Ship lightweight GitHub patch release `0.28.3` with an explicit, resumable LSR/VOR tool slice that passes on local Qwen 3.5 9B and does not rebuild the installer.

**Architecture:** Extend the existing tool harness with four stable estimator-only contracts and an async adapter around `run_smeta_document_application`. The model alone selects calls; code executes/checkpoints/calculates and returns compact draft references. Existing profile snapshots and UI components provide explicit opt-in on upgrades.

**Tech Stack:** Python 3.12, FastAPI/SSE, SQLite, NiceGUI, pytest, existing smeta application adapter and XLSX writers.

**Spec:** `docs/superpowers/specs/2026-08-25-estimator-lsr-tool-slice-design.md`

## Global Constraints

- Start only after `0.28.2` is green and merged.
- Publish through the GitHub patch channel; `LES-Setup.exe`, Tauri/NSIS build,
  offline-cache rebuild and dependency sync are forbidden for this release.
- Do not cherry-pick PR #13; port only reviewed behavior in small tested diffs.
- Do not modify `proxy/smeta_core/**`, add dependencies, reindex, start services or
  access user data.
- No regex/deterministic forcing and no automatic active-profile mutation.
- A draft is never labelled final. Filesystem paths and audit dialogue never
  enter model/browser results.
- Each task follows red test → focused green test → commit.

---

### Task 1: Register typed estimator tool contracts

**Files:**
- Modify: `proxy/services/tool_harness_service.py`
- Create: `proxy/services/estimator_tool_service.py`
- Create: `tests/test_estimator_tool_service.py`
- Modify: `tests/test_tool_harness_service.py`

**Contracts:**

```python
ESTIMATOR_TOOL_NAMES = (
    "estimate_inspect_attachment",
    "estimate_get_lsr_status",
    "estimate_build_vor_draft",
    "estimate_build_lsr_draft",
)
```

The two build tools declare `side_effects="append_only_draft"`; read tools
declare `none`. All return `les_tool_result_v1` and expose typed argument schemas
with `attachment_id`, optional `dataset_ids`, and bounded output options.

**Steps:**

1. Add failing registry tests for exact names/effects and shortlist tests proving
   unrelated queries do not receive estimator tools and `limit` is honored.
2. Run the two focused test files and confirm red.
3. Register handlers through a focused service. Add a tool capability predicate
   so sync and async dispatch share one registry without pretending a coroutine
   is a synchronous handler.
4. Re-run and commit: `feat(tools): register estimator draft contracts`

### Task 2: Implement safe attachment inspection and status

**Files:**
- Modify: `proxy/services/estimator_tool_service.py`
- Modify: `proxy/services/smeta_chat_application_service.py`
- Modify: `tests/test_estimator_tool_service.py`
- Modify: `tests/test_smeta_chat_application_service.py`

**Steps:**

1. Add failing tests for a valid server-owned PDF/XLSX, unknown attachment,
   unsupported type, corrupt checkpoint and completed artifact. Assert no raw path
   or audit conversation appears.
2. Add a public read-only checkpoint-summary function beside the existing private
   loader. It returns schema/state/fingerprint/counts only and does not change the
   protected core.
3. Reuse existing attachment resolution/intake; return evidence refs and explicit
   `MISSING` rather than guessing.
4. Re-run and commit: `feat(estimator): expose safe intake and checkpoint status`

### Task 3: Implement append-only VOR draft

**Files:**
- Modify: `proxy/services/estimator_tool_service.py`
- Modify: `proxy/services/bor_service.py`
- Modify: `tests/test_estimator_tool_service.py`

**Steps:**

1. Add fixture tests proving every output row has immutable source row/page/sheet
   provenance, stable units/quantity and an opaque artifact id.
2. Add tests that missing quantity/unit yields `partial` plus `MISSING`, never an
   invented value, and rerun uses a new append-only artifact identity.
3. Implement with the existing exact intake/spec reader and writer. Do not select
   norms, coefficients or prices.
4. Re-run and commit: `feat(estimator): build provenance-bound VOR drafts`

### Task 4: Implement async resumable LSR draft execution

**Files:**
- Modify: `proxy/services/estimator_tool_service.py`
- Modify: `proxy/services/tool_harness_service.py`
- Modify: `tests/test_estimator_tool_service.py`
- Modify: `tests/test_smeta_chat_application_service.py`

**Interface:**

```python
async def call_async(
    tool: str,
    args: dict[str, Any],
    *,
    token_sink: TokenSink | None = None,
) -> dict[str, Any]: ...
```

**Steps:**

1. Add failing tests that the handler forwards `token_sink`, reuses attachment
   checkpoint identity, preserves a checkpoint on cancellation/error, and reports
   `ok` only with a downloadable `priced_draft` artifact.
2. Add a compact-result size assertion and a resume test proving accepted rows
   and artifact identities are not duplicated.
3. Call existing `run_smeta_document_application`; do not copy its orchestration
   or block the event loop with a thread join.
4. Re-run and commit: `feat(estimator): execute resumable LSR draft tool`

### Task 5: Make estimator profile upgrades explicit

**Files:**
- Modify: `proxy/services/chat_profile_service.py`
- Modify: `proxy/routers/profiles.py`
- Modify: `tests/test_chat_profile_service.py`
- Modify: `tests/test_profiles_router.py`

**Steps:**

1. Add tests for a fresh database receiving the new estimator factory tools.
2. Add upgrade tests with a user-selected active estimator revision and an old
   chat binding. Registry access may create one proposed revision, but active id
   and binding snapshot must remain byte-for-byte unchanged on repeated access.
3. Add `recommended_revision_id` to the estimator registry projection and an
   explicit existing activation endpoint; do not introduce auto-activation.
4. Filter ordinary Agent factory tools to read-only effects so draft tools cannot
   leak through `sorted(registered)`.
5. Re-run and commit: `fix(profiles): require opt-in for estimator tool upgrade`

### Task 6: Integrate the model-owned async tool loop

**Files:**
- Modify: `proxy/routers/chat.py`
- Modify: `proxy/services/chat_evidence_application_service.py`
- Modify: `tests/test_chat_evidence_application_service.py`
- Modify: `tests/test_sovushka_chat.py`

**Steps:**

1. Add deterministic provider-stub tests: explicit model call executes LSR;
   natural-language request with no model call creates no artifact; ordinary
   Agent cannot call it; selected datasets tolerate `None` via `dataset_ids or []`.
2. Add trace assertions `model_owns_selection=true` and
   `selection_source="model"`; prohibit any forced-workbook helper or regex path.
3. Dispatch async estimator tools with the request `token_sink`. Keep shortlist
   query-relevant, profile-bounded and at most three entries for the 9B preset.
4. Insert only the compact result into the next model turn; retain full trace in
   durable run storage.
5. Re-run focused tests and commit: `feat(chat): run model-selected estimator tools`

### Task 7: Harden SSE progress, timeout and cancellation

**Files:**
- Modify: `proxy/routers/chat.py`
- Modify: `sovushka/pages/chat.py`
- Modify: `tests/test_sovushka_chat.py`
- Modify: `tests/test_chat_stream_w51.py`

**Steps:**

1. Add async tests for forwarded `smeta_step`/`smeta_row`, a 15-second semantic
   heartbeat during silence and task cancellation preserving the last checkpoint.
2. Add UI source/behavior tests proving any progress sets `got_progress`, disables
   `/api/chat` retry and uses a 3600-second read timeout.
3. Implement heartbeat ownership in the chat stream wrapper, cancel it in `finally`,
   and never append heartbeat text to the assistant answer.
4. Reuse the current live table/artifact panel and stop action; add no new page or
   visual primitive.
5. Run tests and the Sovushka visual checklist at desktop/tablet/mobile widths.
6. Commit: `fix(chat): make long estimator stream retry-safe`

### Task 8: Qwen 9B acceptance and regression gate

**Files:**
- Create: `tests/test_estimator_9b_acceptance.py`
- Modify: `docs/TEST_INVENTORY.md`

**Steps:**

1. Build a deterministic local-provider fixture with Qwen-compatible tool-call
   JSON and a five-row workbook fixture. Prove explicit selection, bounded three-
   tool shortlist, five decisions, compact context and checkpoint resume.
2. Run:
   `uv run pytest tests/test_estimator_9b_acceptance.py tests/test_estimator_tool_service.py tests/test_smeta_chat_application_service.py -q`.
3. On the accepted local Qwen 3.5 9B runtime run the protected benchmark exactly:
   `uv run python tools/smeta_model_quality_benchmark.py tests/fixtures/sks_4.xlsx --profile qwen=qwen3.5:9b --allow-single-profile --max-turns 10 --candidate-limit 6 --num-ctx 8192 --interrupt-after-rows 5 --out-dir storage/ab_verify`.
4. Require 5/5 decisions and successful interrupt/resume. If it fails, stop and
   report; do not weaken cases or modify protected core.
5. Commit: `test(estimator): gate LSR tools on local Qwen 9B`

### Task 9: Documentation, version and lightweight GitHub release

**Files:**
- Create: `docs/modules/estimator-lsr-tools.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/SOFTWARE_VERSIONS.md`
- Modify: `docs/RELEASE_LEDGER.md`
- Modify: `ROADMAP_TO_V1.md`
- Modify: `config/version.json`
- Modify via `make version-sync`: `pyproject.toml`, `desktop/tauri/package.json`,
  `desktop/tauri/package-lock.json`, `desktop/tauri/src-tauri/Cargo.toml`,
  `desktop/tauri/src-tauri/Cargo.lock`, `desktop/tauri/src-tauri/tauri.conf.json`,
  `docs/VERSIONING.md`, `docs/SOFTWARE_VERSIONS.md`

**Steps:**

1. Document exact contracts, profile boundary, draft semantics, progress events,
   checkpoint/resume and the deliberate non-use of hidden routing.
2. Set product `0.28.3`, build `590`, desktop `5.1.590`, then run
   `make version-sync`.
3. Run the release classifier and require `release_class=patch`; version-only
   source surfaces may be omitted only after structural validation. Any full
   trigger blocks this release and requires owner review instead of starting an
   installer build.
4. Run all focused tests, `make verify`, `make test`, `make test-updater`,
   `git diff --check`, and
   verify `git diff --name-only 0.28.2..HEAD -- proxy/smeta_core` is empty.
5. Run the live Legion chat flow with local Qwen 9B: inspect → explicit LSR call →
   progress → interrupt → resume → downloadable `priced_draft`. Repeat an
   unrelated Agent query and prove no estimator tool is exposed.
6. Build `les-update.json`, compatibility `latest.json`, `les-patch.zip`, checksum and notes; run isolated
   apply/rollback, publish the immutable GitHub Release and verify the installed
   `0.28.2` updates without installer, uv sync or VPS access.
7. Commit: `release: prepare LES 0.28.3 estimator patch`
