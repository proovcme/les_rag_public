# Context Governor, Memory and Model Presets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build every canonical ordinary-chat candidate through one token-aware `ContextGovernor` with typed memory projection and capacity-bounded Qwen 9B/35B presets, without making that candidate authoritative before promotion.

**Architecture:** Model identity and observed backend capacity resolve to an immutable execution preset. Producers return typed context candidates; the governor allocates generation/safety reserves first, packs whole objects in canonical priority order and emits references plus omitted counts instead of slicing JSON. The governed candidate initially runs under the Foundation plan's `shadow` decision: legacy output remains authoritative and canonical observability is redacted and non-persistent until exact 9B acceptance and explicit promotion.

**Tech Stack:** Python 3.12, dataclasses, SQLite, FastAPI, NiceGUI, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-08-26-canonical-tool-context-memory-update-design.md`

## Global Constraints

- Complete the canonical agent foundation plan first.
- Do not modify `proxy/smeta_core/**` or backend-owned Ollama/FreeToken configuration.
- Unknown model identity or capacity resolves to the restrictive 9B-compatible preset.
- 9B and 35B share tools, workflow state, approvals and artifact contracts.
- Reasoning is a separate explicit opt-in and is disabled by default for both presets.
- Preset installation and resolution never promote `legacy`/`shadow` to `active`; route choice is an independent GUI-visible factor.
- Shadow uses the same request and bound profile snapshot as legacy, cannot persist effects and cannot replace the user-visible answer.
- Memory is advisory state, never evidence and never a professional decision engine.
- JSON objects are included whole or omitted with stable IDs/cursors; never truncate serialized JSON mid-object.
- Do not add dependencies.
- Every task updates its module documentation and `docs/MODULE_INDEX.md`, increments `build_number` once, runs `make version-sync`, and records the change in `docs/RELEASE_LEDGER.md` in the same commit.

---

### Task 1: Resolve observed backend capacity into immutable model presets

**Files:**
- Create: `proxy/services/model_execution_preset_service.py`
- Create: `tests/test_model_execution_preset_service.py`
- Create: `tests/test_llm_transport_profile_service.py`
- Create: `tests/test_version_api.py`
- Modify: `proxy/services/llm_transport_profile_service.py`
- Modify: `proxy/services/version_service.py`
- Modify: `docs/modules/chat-profiles.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: provider, served model identity, requested context, observed physical/KV capacity and immutable factory preset definitions.
- Produces: `BackendCapacity`, `ModelExecutionPreset`, `resolve_execution_preset()`.

- [ ] **Step 1: Write failing preset precedence tests**

```python
def test_unknown_identity_uses_restrictive_9b_preset():
    resolved = resolve_execution_preset(BackendCapacity(
        provider="openai-compatible", model_id="unknown", context_tokens=None,
        observed=False, source="unavailable",
    ))
    assert resolved.preset_id == "qwen-9b-restrictive"
    assert resolved.max_tools == 5
    assert resolved.reasoning_enabled is False


def test_observed_capacity_caps_operator_request():
    resolved = resolve_execution_preset(capacity(tokens=8192), operator={"input_tokens": 35000})
    assert resolved.input_token_limit < 8192
    assert resolved.source_chain[0] == "workflow_invariants"
    assert "observed_backend_capacity" in resolved.source_chain
```

- [ ] **Step 2: Run the test and confirm the service is missing**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/model-presets tests/test_model_execution_preset_service.py`

- [ ] **Step 3: Implement the exact preset types and precedence**

```python
@dataclass(frozen=True)
class BackendCapacity:
    provider: str
    model_id: str
    context_tokens: int | None
    observed: bool
    source: str


@dataclass(frozen=True)
class ModelExecutionPreset:
    preset_id: str
    model_family: str
    input_token_limit: int
    generation_reserve_tokens: int
    safety_reserve_tokens: int
    normal_tool_count: int
    max_tools: int
    max_batch_items: int
    parallel_read_limit: int
    reasoning_enabled: bool
    source_chain: tuple[str, ...]
```

Apply precedence exactly: invariants → observed capacity → factory preset → optional operator clone → narrowing workflow/profile restrictions. The factory 9B preset uses normal 1–3 tools, hard maximum 5, homogeneous batches of at most 5 and `parallel_read_limit=1`. The 35B preset keeps identical capabilities and increases only coherent shortlist/page/batch capacity within observed KV.

- [ ] **Step 4: Expose redacted effective values**

Add `requested`, `effective`, `source` and `restart_required` fields to version/config diagnostics. Do not expose secrets or rewrite provider settings.

- [ ] **Step 5: Run focused tests**

```text
uv run python -m pytest -q --basetemp=.test-tmp/model-presets tests/test_model_execution_preset_service.py tests/test_llm_transport_profile_service.py tests/test_version_api.py
make architecture-gate
```

The two new compatibility test files cover only the new transport and redacted version contracts.

- [ ] **Step 6: Update version/docs and commit**

Commit: `feat(context): resolve capacity-bounded model presets`.

### Task 2: Implement typed context candidates and the ContextGovernor packer

**Files:**
- Create: `proxy/services/context_governor_service.py`
- Create: `tests/test_context_governor_service.py`
- Modify: `proxy/services/llm_transport_profile_service.py`
- Modify: `docs/ALGO-context-memory.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: `ModelExecutionPreset`, `ContextCandidate` objects and tokenizer estimate function.
- Produces: `ContextPacket`, `ContextOmission`, `ContextGovernor.pack()`.

- [ ] **Step 1: Write failing packing tests**

```python
def test_governor_reserves_generation_before_evidence():
    packet = governor(limit=1000, generation=200, safety=100).pack(candidates())
    assert packet.input_budget_tokens == 700
    assert packet.sections[0].kind == ContextKind.PROFILE_PREFIX


def test_governor_never_cuts_json_objects():
    candidate = typed_candidate("evidence", [{"id": "a", "text": "x" * 800}])
    packet = governor(limit=300).pack([candidate])
    assert packet.sections == ()
    assert packet.omissions[0].object_ids == ("a",)
    assert packet.omissions[0].cursor


def test_packing_priority_matches_canonical_spec():
    assert [section.kind for section in governor().pack(shuffled_candidates()).sections] == [
        ContextKind.PROFILE_PREFIX, ContextKind.TOOL_SHORTLIST, ContextKind.REQUEST,
        ContextKind.CHECKPOINT, ContextKind.WORKING_MEMORY, ContextKind.EVIDENCE,
        ContextKind.SOURCE_MAP, ContextKind.TOOL_EXCHANGE, ContextKind.DIALOGUE,
    ]
```

- [ ] **Step 2: Run and confirm the governor module is missing**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/context-governor tests/test_context_governor_service.py`

- [ ] **Step 3: Implement typed whole-object packing**

```python
class ContextKind(str, Enum):
    PROFILE_PREFIX = "profile_prefix"
    TOOL_SHORTLIST = "tool_shortlist"
    REQUEST = "request"
    CHECKPOINT = "checkpoint"
    WORKING_MEMORY = "working_memory"
    EVIDENCE = "evidence"
    SOURCE_MAP = "source_map"
    TOOL_EXCHANGE = "tool_exchange"
    DIALOGUE = "dialogue"


@dataclass(frozen=True)
class ContextCandidate:
    kind: ContextKind
    objects: tuple[ContextObject, ...]
    required: bool = False


class ContextGovernor:
    def pack(self, candidates: Sequence[ContextCandidate]) -> ContextPacket:
        """Pack complete objects in canonical order after fixed reserves."""
```

Use the existing provider token/character estimator only as a conservative size estimate. `fit_prompt_sections()` becomes a compatibility wrapper over the governor and must no longer slice arbitrary section strings.

- [ ] **Step 4: Add stable omission references**

Every omitted group records `kind`, `total`, `omitted`, `object_ids`, `cursor` and `reason`. Required request/profile/checkpoint overflow returns a typed `CONTEXT_REQUIRED_SECTION_OVERFLOW` error before model invocation.

- [ ] **Step 5: Run focused packer tests**

```text
uv run python -m pytest -q --basetemp=.test-tmp/context-governor tests/test_context_governor_service.py tests/test_llm_transport_profile_service.py
make architecture-gate
```

- [ ] **Step 6: Update version/docs and commit**

Commit: `feat(context): pack inference through one governor`.

### Task 3: Project existing stores into typed working memory

**Files:**
- Create: `proxy/services/typed_memory_projection_service.py`
- Create: `tests/test_typed_memory_projection_service.py`
- Modify: `proxy/services/context_memory_service.py`
- Modify: `proxy/services/memory_port.py`
- Modify: `proxy/services/memory_service.py`
- Modify: `tests/test_context_memory_service.py`
- Modify: `tests/test_memory_service.py`
- Modify: `docs/ALGO-context-memory.md`
- Modify: `docs/modules/memory-core.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: chat profile state, chat history, MemoryPort advisory facts, evidence refs and workflow checkpoint rows.
- Produces: `MemoryProjection` with addressable typed items and `as_context_candidates()`.

- [ ] **Step 1: Write failing memory-boundary tests**

```python
def test_projection_separates_memory_from_evidence(stores):
    projection = project_memory(stores, session_id="s1", project_id=7)
    assert projection.context_role == "advisory_state"
    assert all(item.is_evidence is False for item in projection.items)


def test_model_decision_is_stored_as_revision_reference_not_rewritten_fact(stores):
    projection = project_memory(stores_with_decision("rev-2"), session_id="s1", project_id=7)
    decision = one(projection.items, kind="decision")
    assert decision.revision_ref == "rev-2"
    assert decision.payload == {"status": "accepted"}
```

- [ ] **Step 2: Run and confirm the projection module is missing**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/memory-projection tests/test_typed_memory_projection_service.py`

- [ ] **Step 3: Implement the common projection**

```python
class MemoryItemKind(str, Enum):
    CHECKPOINT = "checkpoint"
    BLOCKER = "blocker"
    DECISION = "decision"
    EVIDENCE_LOCATOR = "evidence_locator"
    CONTINUITY = "continuity"
    ADVISORY_FACT = "advisory_fact"


@dataclass(frozen=True)
class MemoryItem:
    item_id: str
    kind: MemoryItemKind
    payload: Mapping[str, Any]
    revision_ref: str | None
    project_id: int | None
    is_evidence: Literal[False] = False


def project_memory(*, session_id: str, project_id: int | None,
                   dataset_ids: Sequence[str], limits: MemoryLimits) -> MemoryProjection:
    """Adapt existing stores without copying prompt dumps into memory."""
```

Full objects remain in their source stores. Projection items carry IDs/cursors and bounded summaries only. No memory item may create a norm, coefficient, quantity or professional conclusion.

- [ ] **Step 4: Keep legacy memory APIs as adapters**

`build_context_memory_block()` and `session_memory()` serialize views from the typed projection during migration; their callers receive the same user-visible continuity but cannot bypass the governor in the next task.

- [ ] **Step 5: Run memory suites**

```text
uv run python -m pytest -q --basetemp=.test-tmp/memory-projection tests/test_typed_memory_projection_service.py tests/test_context_memory_service.py tests/test_memory_service.py tests/test_memory_core.py tests/test_memory_api.py
make architecture-gate
```

- [ ] **Step 6: Update version/docs and commit**

Commit: `feat(memory): project typed advisory working state`.

### Task 4: Govern the canonical ordinary-chat candidate in every route mode

**Files:**
- Modify: `proxy/services/chat_evidence_application_service.py`
- Modify: `proxy/routers/chat.py`
- Modify: `tests/test_chat_evidence_application_service.py`
- Modify: `tests/test_chat_stream_w51.py`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/ALGO-context-memory.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: `CanonicalRouteDecision`, profile snapshot, broker shortlist, request/checkpoint, typed memory, retrieval evidence/source map and latest tool exchange.
- Produces: one `ContextPacket` for canonical selector and answer calls plus a redacted `context_governor`/route-comparison trace; only effective `active` may replace legacy output.

- [ ] **Step 1: Write failing chat integration tests**

```python
@pytest.mark.asyncio
async def test_chat_calls_governor_for_selector_and_final_model(fake_runtime):
    result = await run_grounded_chat(fake_runtime)
    assert [call.purpose for call in fake_runtime.governor.calls] == ["tool_decision", "answer"]
    assert result["retrieval_trace"]["context_governor"]["preset_id"] == "qwen-9b-restrictive"


@pytest.mark.asyncio
async def test_required_overflow_prevents_provider_call(fake_runtime):
    result = await run_chat_with_tiny_capacity(fake_runtime)
    assert result["error"]["code"] == "CONTEXT_REQUIRED_SECTION_OVERFLOW"
    assert fake_runtime.canonical_provider_calls == []


@pytest.mark.asyncio
async def test_shadow_governs_same_snapshot_but_keeps_legacy_output(fake_runtime):
    result = await run_grounded_chat(fake_runtime, route_mode="shadow")
    assert result.answer == fake_runtime.legacy_answer
    shadow = result["retrieval_trace"]["canonical_shadow"]
    assert shadow["profile_revision"] == fake_runtime.legacy_profile_revision
    assert shadow["persisted_effects"] == 0
```

- [ ] **Step 2: Run and confirm current direct prompt assembly fails the assertion**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/chat-governor tests/test_chat_evidence_application_service.py`

- [ ] **Step 3: Replace direct prompt concatenation and independent character caps**

Each producer emits `ContextCandidate`; the application service calls:

```python
packet = context_governor.pack([
    profile_candidate, shortlist_candidate, request_candidate, checkpoint_candidate,
    memory_candidate, evidence_candidate, source_map_candidate,
    tool_exchange_candidate, dialogue_candidate,
])
messages = packet.as_messages()
```

Delete per-service final truncation in this path. Retrieval may still bound candidate generation, but only the governor owns the inference packet budget.

Resolve the route once before either branch. `legacy` skips canonical provider
calls. `shadow` gives the canonical candidate the exact same request and bound
profile snapshot, keeps the legacy answer authoritative and uses the
non-persistent executor policy defined by the Foundation plan. Effective
`active` uses the governed canonical answer; the route service must already
have validated the exact promotion receipt. Preset resolution alone can never
change the effective route.

- [ ] **Step 4: Persist redacted observability**

Trace contains route requested/effective/reason, preset ID, requested/effective capacities, source chain, per-kind included tokens/items, omission counts/cursors, reserves and structural legacy/canonical comparison fields. It contains neither prompt/answer text nor secrets and is not model-quality evidence.

- [ ] **Step 5: Run chat/context tests and gates**

```text
uv run python -m pytest -q --basetemp=.test-tmp/chat-governor tests/test_context_governor_service.py tests/test_typed_memory_projection_service.py tests/test_chat_evidence_application_service.py tests/test_chat_stream_w51.py tests/test_chat_profile_runtime.py
make architecture-gate
make verify
```

- [ ] **Step 6: Update version/docs and commit**

Commit: `refactor(chat): govern every inference packet`.

### Task 5: Show effective model/context factors in Sovushka

**Files:**
- Modify: `proxy/services/runtime_config_registry_service.py`
- Modify: `proxy/routers/settings.py`
- Modify: `sovushka/pages/diag.py`
- Modify: `tests/test_runtime_config_registry_service.py`
- Modify: `tests/test_diag_platform.py`
- Modify: `skills/sovushka-ui/SKILL.md` only if the registry contract changes
- Modify: `docs/modules/sovushka-uikit.md` only if a shared component changes
- Modify: `docs/modules/chat-profiles.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: redacted effective preset/config diagnostics.
- Produces: GUI rows showing `requested → effective · source` and restart state.

- [ ] **Step 1: Before UI edits, read required UI instructions**

Read `skills/sovushka-ui/SKILL.md` and `docs/modules/sovushka-uikit.md`; reuse the registered settings/value-row component.

- [ ] **Step 2: Write failing registry/UI contract tests**

```python
def test_context_factors_are_registered_with_effective_source():
    rows = runtime_factor_rows(effective_payload())
    ids = {row["id"] for row in rows}
    assert {"model_preset", "context_input_tokens", "generation_reserve", "reasoning"} <= ids
    assert all("effective" in row and "source" in row for row in rows)
```

- [ ] **Step 3: Run and confirm missing factor rows**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/context-ui tests/test_runtime_config_registry_service.py tests/test_diag_platform.py`

- [ ] **Step 4: Register and render the factors**

Secret values remain `задан/не задан`. Provider-owned physical KV is read-only. Operator preset values are editable only through a cloned preset; safety/observed limits remain visible and read-only.

- [ ] **Step 5: Run UI checks**

```text
uv run python -m pytest -q --basetemp=.test-tmp/context-ui tests/test_runtime_config_registry_service.py tests/test_diag_platform.py tests/test_profiles_ui.py
make architecture-gate
```

- [ ] **Step 6: Update version/docs and commit**

Commit: `feat(ui): show effective model context preset`.

### Task 6: Close preset parity and context acceptance

**Files:**
- Create: `tests/test_model_preset_workflow_parity.py`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/TEST_INVENTORY.md`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: completed preset, governor, memory and chat integration.
- Produces: contract evidence that 9B/35B semantics are identical.

- [ ] **Step 1: Add parity tests**

```python
@pytest.mark.parametrize("preset", ["qwen-9b-restrictive", "qwen-35b-extended"])
def test_primary_workflow_contract_is_identical(preset):
    contract = workflow_contract(preset)
    assert contract.tools == canonical_professional_tools()
    assert contract.states == canonical_workflow_states()
    assert contract.approval_policy == canonical_approval_policy()
    assert contract.artifact_schema == "les.artifact_revision.v1"
```

- [ ] **Step 2: Run focused and canonical gates**

```text
uv run python -m pytest -q --basetemp=.test-tmp/context-final tests/test_model_execution_preset_service.py tests/test_context_governor_service.py tests/test_typed_memory_projection_service.py tests/test_model_preset_workflow_parity.py tests/test_chat_evidence_application_service.py
make architecture-gate
make verify
make test
git diff --check
```

- [ ] **Step 3: Record exact evidence and commit**

Update docs with exact counts. State explicitly that parity tests prove contract identity, not live model quality.

Commit: `docs(context): record governed preset parity`.
