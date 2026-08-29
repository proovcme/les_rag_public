# Canonical Workbook Tools and Versioned Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver model-selected `build_lsr_workbook` and `build_vor_workbook` through the canonical registry/executor with durable checkpoints and immutable downloadable workbook revisions.

**Architecture:** A common artifact revision store owns metadata, hashes, lineage and downloads. Workbook handlers adapt verified existing application/library behavior without exposing or depending on protected smeta-core internals; the broker and model choose the call, the executor runs it, and the model composes the user-facing answer from the typed result.

**Tech Stack:** Python 3.12, SQLite, openpyxl already in the lock, FastAPI/SSE, NiceGUI, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-08-26-canonical-tool-context-memory-update-design.md`

## Global Constraints

- Complete the agent foundation and ContextGovernor plans first.
- Do not modify `proxy/smeta_core/**`.
- Canonical public names are exactly `build_lsr_workbook` and `build_vor_workbook`.
- The model alone selects a workbook tool. Do not port `workbook_file_intent()`, `maybe_forced_workbook_call()`, regex forcing, shortlist pinning or automatic estimator-profile activation from public PR13.
- Retain only the reviewed PR13 contracts and transport behaviors: empty explicit scope normalization, SSE progress, no retry after progress, artifact harvesting and attachment identity across retry/resume.
- A workbook revision is immutable; correction creates revision N+1 linked to N.
- Code calculates, validates structure/provenance and writes files; model-owned rows/norms/coefficients are never replaced by code.
- The old five-row smeta benchmark and synthetic fixtures are not acceptance evidence.
- Do not add dependencies.
- Every task updates its module documentation and `docs/MODULE_INDEX.md`, increments `build_number` once, runs `make version-sync`, and records the change in `docs/RELEASE_LEDGER.md` in the same commit.

---

### Task 1: Add the common immutable artifact revision store

**Files:**
- Create: `proxy/services/artifact_revision_service.py`
- Create: `proxy/routers/artifacts.py`
- Create: `tests/test_artifact_revision_service.py`
- Create: `tests/test_artifacts_router.py`
- Modify: `proxy/app.py`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: server-owned generated file, source/workflow metadata and optional parent revision ID.
- Produces: `ArtifactRevision`, `ArtifactRevisionStore.create_revision()`, metadata and download APIs.

- [ ] **Step 1: Write failing append-only and lineage tests**

```python
def test_correction_creates_new_revision_and_preserves_parent(tmp_path):
    store = ArtifactRevisionStore(db_path=tmp_path / "meta.db", root=tmp_path / "artifacts")
    first = store.create_revision(request(file=workbook(tmp_path, "v1"), parent=None))
    second = store.create_revision(request(file=workbook(tmp_path, "v2"), parent=first.revision_id))
    assert (first.revision_no, second.revision_no) == (1, 2)
    assert second.parent_revision_id == first.revision_id
    assert store.read_bytes(first.revision_id) != store.read_bytes(second.revision_id)


def test_existing_revision_file_cannot_be_overwritten(tmp_path):
    store, revision = seeded_store(tmp_path)
    with pytest.raises(ArtifactImmutableError):
        store.replace_bytes(revision.revision_id, b"changed")
```

- [ ] **Step 2: Run and confirm the service is absent**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/artifacts tests/test_artifact_revision_service.py tests/test_artifacts_router.py`

- [ ] **Step 3: Implement schema and atomic immutable persistence**

```python
@dataclass(frozen=True)
class ArtifactRevisionRequest:
    artifact_kind: Literal["lsr_workbook", "vor_workbook"]
    file_path: Path
    source_scope: tuple[str, ...]
    profile_revision_id: str
    model_identity: str
    model_preset: str
    tool_calls: tuple[Mapping[str, Any], ...]
    decision_checkpoint_id: str
    missing: tuple[str, ...]
    blockers: tuple[str, ...]
    parent_revision_id: str | None


@dataclass(frozen=True)
class ArtifactRevision:
    artifact_id: str
    revision_id: str
    revision_no: int
    parent_revision_id: str | None
    sha256: str
    byte_size: int
    download_url: str
```

The SQLite row and content-addressed file are published transactionally using a temporary sibling file and atomic rename. Existing revision paths are never reused. Paths returned to browser/model payloads are relative artifact IDs, never filesystem paths.

- [ ] **Step 4: Add authenticated metadata/download routes**

```text
GET /api/artifacts/{revision_id}
GET /api/artifacts/{revision_id}/download
GET /api/artifacts/{artifact_id}/revisions
```

Reject traversal, unknown revisions and hash drift. Downloads verify SHA-256 before streaming.

- [ ] **Step 5: Run focused tests**

```text
uv run python -m pytest -q --basetemp=.test-tmp/artifacts tests/test_artifact_revision_service.py tests/test_artifacts_router.py tests/test_chat_harness_format.py
make architecture-gate
```

- [ ] **Step 6: Update version/docs and commit**

Commit: `feat(artifacts): persist immutable workbook revisions`.

### Task 2: Add durable workflow checkpoints and idempotency

**Files:**
- Create: `proxy/services/workflow_checkpoint_service.py`
- Create: `tests/test_workflow_checkpoint_service.py`
- Modify: `proxy/services/chat_attachment_service.py`
- Modify: `tests/test_chat_attachment_service.py`
- Modify: `docs/ALGO-context-memory.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: session ID, attachment identity, tool name, normalized arguments and model decision revision.
- Produces: `WorkflowCheckpoint`, `begin_or_resume()`, `record_progress()`, `complete()`.

- [ ] **Step 1: Write failing resume/identity tests**

```python
def test_retry_resumes_same_checkpoint_and_attachment(tmp_path):
    service = checkpoint_service(tmp_path)
    first = service.begin_or_resume(begin_request(attachment_id="read_abc", key="k1"))
    service.record_progress(first.checkpoint_id, phase="rows", completed=3, total=10)
    resumed = service.begin_or_resume(begin_request(attachment_id="read_abc", key="k1"))
    assert resumed.checkpoint_id == first.checkpoint_id
    assert resumed.progress.completed == 3


def test_idempotency_key_cannot_change_attachment(tmp_path):
    service = checkpoint_service(tmp_path)
    service.begin_or_resume(begin_request(attachment_id="read_abc", key="k1"))
    with pytest.raises(CheckpointConflict, match="attachment"):
        service.begin_or_resume(begin_request(attachment_id="read_other", key="k1"))
```

- [ ] **Step 2: Run and confirm the checkpoint service is absent**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/checkpoints tests/test_workflow_checkpoint_service.py tests/test_chat_attachment_service.py`

- [ ] **Step 3: Implement checkpoint records**

```python
@dataclass(frozen=True)
class WorkflowCheckpoint:
    checkpoint_id: str
    tool_name: str
    attachment_id: str
    attachment_sha256: str
    normalized_args_sha256: str
    model_decision_revision: str
    phase: str
    completed_items: int
    total_items: int | None
    status: Literal["running", "blocked", "failed", "complete"]
    artifact_revision_id: str | None
```

Persist bounded blocker/missing arrays and latest progress; do not persist prompt dumps. `dataset_ids=None` must normalize to `()` before argument hashing.

- [ ] **Step 4: Preserve server-owned attachment identity**

Extend attachment metadata with immutable SHA-256 and original name. A checkpoint retains the attachment until terminal completion or explicit user cancellation; retry/resume never consumes a different attachment silently.

- [ ] **Step 5: Run focused tests**

```text
uv run python -m pytest -q --basetemp=.test-tmp/checkpoints tests/test_workflow_checkpoint_service.py tests/test_chat_attachment_service.py
make architecture-gate
```

- [ ] **Step 6: Update version/docs and commit**

Commit: `feat(workflows): checkpoint workbook execution durably`.

### Task 3: Register canonical workbook contracts and provider projections

**Files:**
- Create: `proxy/services/workbook_tool_service.py`
- Create: `proxy/services/tool_provider_projection_service.py`
- Create: `tests/test_workbook_tool_contracts.py`
- Create: `tests/test_tool_provider_projection_service.py`
- Modify: `proxy/services/tool_registry_service.py`
- Modify: `proxy/services/chat_profile_service.py`
- Modify: `tests/test_chat_profile_service.py`
- Modify: `docs/ALGO-tool-harness.md`
- Modify: `docs/modules/chat-profiles.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: canonical registry, profile snapshots and the already resolved
  `ResolvedModelConnection` executed only by `OpenAICompatibleTransport`.
- Produces: two `ToolContract`s and schema-only protocol projections. New
  FreeToken/Ollama/Lemonade/MLX branches in workbook code are forbidden.

- [ ] **Step 1: Write failing canonical-name and profile immutability tests**

```python
def test_only_canonical_workbook_names_are_registered():
    names = canonical_tool_registry().names()
    assert {"build_lsr_workbook", "build_vor_workbook"} <= set(names)
    assert not {name for name in names if name.startswith("estimate_") and "workbook" in name}


def test_installing_contracts_does_not_activate_estimator_revision(tmp_path):
    before = active_profile(tmp_path, "estimator")
    register_workbook_contracts(canonical_tool_registry())
    assert active_profile(tmp_path, "estimator") == before
```

- [ ] **Step 2: Run and confirm the workbook service is absent**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/workbook-contracts tests/test_workbook_tool_contracts.py tests/test_tool_provider_projection_service.py tests/test_chat_profile_service.py`

- [ ] **Step 3: Define exact contracts**

```python
BUILD_LSR_WORKBOOK = ToolContract(
    name="build_lsr_workbook", version="1.0.0", title="Build LSR workbook",
    category="workbook", summary="Build an immutable priced LSR draft from a server-owned attachment",
    input_schema={"type": "object", "required": ["attachment_id"], "properties": {
        "attachment_id": {"type": "string"}, "question": {"type": "string"},
        "project_id": {"type": ["integer", "null"]}, "parent_revision_id": {"type": ["string", "null"]},
        "dataset_ids": {"type": ["array", "null"], "items": {"type": "string"}},
    }},
    result_schema="les.workbook_tool_result.v1", effect=EffectClass.DRAFT,
    scopes=("chat_attachment", "dataset"), timeout_seconds=900,
    retry=RetryPolicy.IDEMPOTENCY_KEY,
    idempotency=IdempotencyPolicy.REQUIRED, provenance="artifact_revision_required",
    result_budget=ResultBudget(max_chars=12000, max_items=200),
    model_owned_fields=("norm_code", "analogue", "coverage", "coefficient"),
)
```

`build_vor_workbook` uses the same envelope without pricing/norm selection fields. Provider projections adapt JSON shape only and include the same stable name/version/effect.

- [ ] **Step 4: Add workbook tools only to new factory estimator snapshots**

New factory seeds may include the tools. Existing active revisions and existing session bindings are untouched. Operators explicitly clone/publish/activate a revision to make tools available to an existing installation.

- [ ] **Step 5: Run contract/projection/profile tests**

```text
uv run python -m pytest -q --basetemp=.test-tmp/workbook-contracts tests/test_workbook_tool_contracts.py tests/test_tool_provider_projection_service.py tests/test_chat_profile_service.py tests/test_chat_profile_runtime.py
make architecture-gate
```

- [ ] **Step 6: Update version/docs and commit**

Commit: `feat(tools): register canonical workbook contracts`.

### Task 4: Implement workbook handlers over verified existing adapters

**Files:**
- Modify: `proxy/services/workbook_tool_service.py`
- Create: `tests/test_workbook_tool_service.py`
- Modify: `proxy/services/bor_service.py` only for a pure VOR row-to-workbook adapter if required
- Modify: `tests/test_bor_service.py` only for that pure adapter
- Modify: `docs/ALGO-tool-harness.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: executor request, checkpoint service, server-owned attachment, existing verified LSR/VOR library/application adapters and artifact store.
- Produces: `build_lsr_workbook(args, execution_context)` and `build_vor_workbook(args, execution_context)` typed results.

- [ ] **Step 1: Write failing handler tests with real small XLSX input**

```python
@pytest.mark.asyncio
async def test_vor_handler_preserves_source_rows_and_creates_revision(tmp_path):
    result = await build_vor_workbook(vor_args(tmp_path), execution_context(tmp_path))
    assert result["schema"] == "les.workbook_tool_result.v1"
    assert result["artifact"]["revision_no"] == 1
    assert result["source"]["sha256"]
    assert result["missing"] == []


@pytest.mark.asyncio
async def test_lsr_handler_does_not_accept_model_supplied_prices(tmp_path):
    args = lsr_args(tmp_path) | {"rows": [{"price": 1}], "prices": [1]}
    result = await build_lsr_workbook(args, execution_context(tmp_path))
    assert result["status"] == "rejected"
    assert result["code"] == "MODEL_DECISION_FIELD_NOT_ALLOWED"
```

- [ ] **Step 2: Run and confirm handlers are unimplemented**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/workbook-tools tests/test_workbook_tool_service.py`

- [ ] **Step 3: Implement the shared execution flow**

```python
async def build_lsr_workbook(args: Mapping[str, Any], ctx: WorkbookExecutionContext) -> dict[str, Any]:
    normalized = normalize_workbook_args(args, dataset_ids_default=())
    checkpoint = ctx.checkpoints.begin_or_resume(ctx.begin_request(normalized))
    generated = await ctx.lsr_adapter.build(normalized, progress=ctx.progress)
    revision = ctx.artifacts.create_revision(ctx.revision_request(generated, checkpoint))
    ctx.checkpoints.complete(checkpoint.checkpoint_id, revision.revision_id)
    return workbook_result(generated, revision, checkpoint)
```

The first LSR adapter may call the verified existing application function, but the public result/checkpoint contains no `smeta_core` type or path. The VOR adapter preserves exact rows/quantities/provenance and reports missing unit/quantity rather than guessing.

- [ ] **Step 4: Test correction lineage and failures**

Add cases for revision 2, attachment hash drift, unsupported input, partial/missing rows, adapter exception before artifact publication and checkpoint resume after interruption.

- [ ] **Step 5: Run focused handler/artifact tests**

```text
uv run python -m pytest -q --basetemp=.test-tmp/workbook-tools tests/test_workbook_tool_service.py tests/test_workbook_tool_contracts.py tests/test_workflow_checkpoint_service.py tests/test_artifact_revision_service.py tests/test_bor_service.py
make architecture-gate
```

- [ ] **Step 6: Update version/docs and commit**

Commit: `feat(workbooks): build provenance-bound immutable drafts`.

### Task 5: Integrate progress, artifact harvesting and retry suppression

**Files:**
- Modify: `proxy/services/chat_evidence_application_service.py`
- Modify: `proxy/routers/chat.py`
- Modify: `sovushka/pages/chat.py`
- Modify: `sovushka/state.py`
- Modify: `tests/test_chat_evidence_application_service.py`
- Modify: `tests/test_chat_stream_w51.py`
- Modify: `tests/test_sovushka_chat.py`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/modules/chat-profiles.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: executor progress events and `les.workbook_tool_result.v1`.
- Produces: SSE `tool_progress`, final artifact metadata, persisted chat history and safe UI retry behavior.

- [ ] **Step 1: Before UI edits, read required Sovushka instructions**

Read `skills/sovushka-ui/SKILL.md` and `docs/modules/sovushka-uikit.md`; reuse the existing artifact/download and progress components.

- [ ] **Step 2: Write failing stream/retry tests**

```python
def test_ui_never_retries_after_progress_started():
    assert should_retry_unstreamed_chat(got_token=False, got_progress=True, stream_error=None) is False


@pytest.mark.asyncio
async def test_chat_harvests_revision_and_attachment_retry(fake_executor):
    result = await run_workbook_chat(fake_executor)
    assert result["artifact"]["revision_id"] == "rev-2"
    assert result["attachment_retry"]["attachment_id"] == "read_abc"
    assert saved_history(result.session_id)["artifact"]["revision_id"] == "rev-2"
```

- [ ] **Step 3: Run and confirm current stream behavior lacks the canonical event**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/workbook-stream tests/test_chat_evidence_application_service.py tests/test_chat_stream_w51.py tests/test_sovushka_chat.py`

- [ ] **Step 4: Emit and consume canonical progress events**

Use one event payload:

```json
{"event":"tool_progress","data":{"call_id":"call-1","checkpoint_id":"cp-1","phase":"rows","completed":3,"total":10,"label":"Собираю строки ВОР"}}
```

Any `tool_progress` marks the request as started; the UI never falls back to a second `/api/chat` call. Final artifact metadata is harvested from the executor envelope and stored in chat history with the attachment/checkpoint identity.

- [ ] **Step 5: Run stream/UI checks**

```text
uv run python -m pytest -q --basetemp=.test-tmp/workbook-stream tests/test_chat_evidence_application_service.py tests/test_chat_stream_w51.py tests/test_sovushka_chat.py tests/test_chat_harness_format.py
make architecture-gate
```

- [ ] **Step 6: Update version/docs and commit**

Commit: `feat(chat): stream and harvest workbook revisions`.

### Task 6: Add real ordinary-chat live acceptance without fake quality claims

**Files:**
- Create: `tools/live_workbook_acceptance.py`
- Create: `tests/test_live_workbook_acceptance_contract.py`
- Modify: `Makefile`
- Modify: `docs/INSTALL_RUNBOOK.md`
- Modify: `docs/TEST_INVENTORY.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: running ordinary-chat API, representative user-supplied large document, configured local 9B and optional configured 35B.
- Produces: redacted JSON acceptance report with `evidence_kind="live_runtime"`.

- [ ] **Step 1: Write failing acceptance-contract tests**

```python
def test_acceptance_report_requires_live_runtime_identity():
    with pytest.raises(ValueError, match="live_runtime"):
        validate_report({"evidence_kind": "synthetic_fixture"})


def test_acceptance_requires_two_immutable_revisions(report):
    validate_report(report)
    assert report["revision_1"]["sha256"] != report["revision_2"]["sha256"]
    assert report["revision_2"]["parent_revision_id"] == report["revision_1"]["revision_id"]
```

- [ ] **Step 2: Run and confirm the acceptance tool is absent**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/live-workbook tests/test_live_workbook_acceptance_contract.py`

- [ ] **Step 3: Implement a fail-closed live runner**

The CLI requires explicit `--attachment`, `--base-url`, `--profile-revision`, `--model-preset qwen-9b` and `--out`. It uploads/attaches through the ordinary-chat path, requests a workbook, downloads revision 1, requests a correction, downloads revision 2 and verifies hashes, provenance, blockers/missing and elapsed time. It refuses fixture paths under `tests/fixtures` for release acceptance.

- [ ] **Step 4: Add the opt-in Make target**

```make
live-workbook-acceptance:
	uv run python tools/live_workbook_acceptance.py $(LIVE_WORKBOOK_ACCEPTANCE_ARGS)
```

Do not add it to offline `make verify`. Release operators run it only with a real configured corpus/model. Repeat on 35B only when 35B is configured; semantics and artifact schema must remain identical.

- [ ] **Step 5: Run offline gates**

```text
uv run python -m pytest -q --basetemp=.test-tmp/live-workbook tests/test_live_workbook_acceptance_contract.py
make architecture-gate
make verify
make test
git diff --check
```

- [ ] **Step 6: Record the pending live gate and commit**

The docs must say `PENDING: live user-owned input/model acceptance` until a real run is performed. Commit: `test(workbooks): define real live acceptance gate`.
