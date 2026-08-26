# Canonical Agent Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the mixed `ToolHarness` registry/execution loop with one provider-neutral Tool Registry, Capability Broker and Trusted Executor, guarded against the rejected estimator bridge.

**Architecture:** Existing read-only handlers remain the implementation source, but registration, eligibility and execution become separate typed services. Ordinary chat obtains a bounded broker shortlist, the model chooses one call, and the executor validates scope, effect policy, idempotency and the result envelope before the model continues.

**Tech Stack:** Python 3.12, dataclasses, Enum, FastAPI, SQLite, pytest, uv, Make.

**Spec:** `docs/superpowers/specs/2026-08-26-canonical-tool-context-memory-update-design.md`

## Global Constraints

- Work only from clean commit `4f4539d0` or a descendant of it.
- Do not modify `proxy/smeta_core/**`.
- Keep the public names `build_lsr_workbook` and `build_vor_workbook`; do not create a parallel `estimate_*` workbook family.
- The model owns tool choice. No regex, substring intent rule or fallback may force a workbook call.
- Profile revisions and existing chat bindings remain immutable until an explicit operator/user action applies another revision.
- Qwen 9B and 35B receive the same professional workflows and tool contracts; presets may only alter budgets and concurrency.
- Do not add dependencies.
- Every task updates its module documentation and `docs/MODULE_INDEX.md`, increments `build_number` once in `config/version.json`, runs `make version-sync`, and records the task in `docs/RELEASE_LEDGER.md` in the same commit.

---

### Task 1: Add the fail-closed architecture gate

**Files:**
- Create: `tools/architecture_contract_gate.py`
- Create: `tests/test_architecture_contract_gate.py`
- Modify: `Makefile`
- Modify: `AGENTS.md`
- Create: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: repository root and checked-in Python/Markdown sources.
- Produces: `scan_architecture(root: Path) -> list[ArchitectureViolation]` and `make architecture-gate`.

- [ ] **Step 1: Write failing architecture-gate tests**

```python
def test_rejects_parallel_estimate_workbook_name(tmp_path):
    write(tmp_path, "proxy/services/bad.py", 'NAME = "estimate_build_lsr_workbook"')
    assert codes(scan_architecture(tmp_path)) == {"PARALLEL_WORKBOOK_TOOL"}


def test_rejects_forced_workbook_regex(tmp_path):
    write(tmp_path, "proxy/services/bad.py", 're.search("лср", question); call("build_lsr_workbook")')
    assert "FORCED_WORKBOOK_CALL" in codes(scan_architecture(tmp_path))


def test_rejects_implicit_profile_activation(tmp_path):
    write(tmp_path, "proxy/services/startup.py", "activate_profile_revision('estimator', revision)")
    assert "IMPLICIT_PROFILE_ACTIVATION" in codes(scan_architecture(tmp_path))
```

- [ ] **Step 2: Verify the new tests fail because the scanner is absent**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/architecture-gate tests/test_architecture_contract_gate.py`

Expected: collection fails on missing `tools.architecture_contract_gate`.

- [ ] **Step 3: Implement an AST-based scanner with explicit findings**

```python
@dataclass(frozen=True)
class ArchitectureViolation:
    code: str
    path: str
    line: int
    detail: str


def scan_architecture(root: Path) -> list[ArchitectureViolation]:
    """Scan tracked implementation/docs; never read runtime data or secrets."""


def main(argv: Sequence[str] | None = None) -> int:
    violations = scan_architecture(Path.cwd())
    for item in violations:
        print(f"{item.code} {item.path}:{item.line} {item.detail}")
    return 1 if violations else 0
```

The scanner must inspect AST call/name/string nodes, not raw broad regex alone. Its initial rules are:

- reject `estimate_build_lsr*`, `estimate_build_vor*`, `estimate_*workbook*` outside superseded documents;
- reject a function that both inspects natural-language text with `re`, substring/token matching and invokes either workbook tool;
- reject `activate_profile_revision()` outside the explicit profiles router/service operation and its direct tests;
- reject new model HTTP callsites not listed in `INFERENCE_CALLSITE_BASELINE` and not routed through `ContextGovernor` (the baseline is exact path + function, never a directory wildcard);
- reject test/report labels containing both `synthetic|fixture|mock` and `live model quality|live acceptance`.

- [ ] **Step 4: Add the Make target and current architecture document**

```make
.PHONY: architecture-gate
architecture-gate:
	uv run python tools/architecture_contract_gate.py
```

`docs/CURRENT_ARCHITECTURE.md` must point to the canonical spec, distinguish implemented from planned components, and state that `make architecture-gate` is structural evidence only.

- [ ] **Step 5: Run the focused and repository architecture checks**

Run:

```text
uv run python -m pytest -q --basetemp=.test-tmp/architecture-gate tests/test_architecture_contract_gate.py
make architecture-gate
git diff --check
```

Expected: tests pass; the clean baseline produces no violations.

- [ ] **Step 6: Update version/docs and commit**

Increment `build_number` by one, set `desktop_version` to `5.1.<build_number>`, run `make version-sync`, update the architecture rows, then commit:

```text
git add AGENTS.md Makefile config/version.json docs/CURRENT_ARCHITECTURE.md docs/MODULE_INDEX.md docs/RELEASE_LEDGER.md docs/SOFTWARE_VERSIONS.md docs/VERSIONING.md desktop/tauri pyproject.toml tests/test_architecture_contract_gate.py tools/architecture_contract_gate.py
git commit -m "test(architecture): enforce canonical agent boundaries"
```

### Task 2: Define canonical provider-neutral tool contracts and registry

**Files:**
- Create: `proxy/services/tool_contract_service.py`
- Create: `proxy/services/tool_registry_service.py`
- Create: `tests/test_tool_contract_service.py`
- Create: `tests/test_tool_registry_service.py`
- Modify: `proxy/services/tool_harness_service.py`
- Modify: `tests/test_tool_harness_service.py`
- Modify: `docs/ALGO-tool-harness.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: existing `ToolSpec` definitions and handlers from `tool_harness_service.py`.
- Produces: `ToolContract`, `ToolRegistration`, `ToolRegistry`, `canonical_tool_registry()`.

- [ ] **Step 1: Write failing contract tests**

```python
def test_tool_contract_contains_execution_policy():
    contract = ToolContract(
        name="read_source", version="1.0.0", title="Read source",
        category="source", summary="Read bounded evidence",
        input_schema={"type": "object"}, result_schema="les_tool_result_v1",
        effect=EffectClass.READ, scopes=("dataset",), timeout_seconds=30,
        retry=RetryPolicy.SAFE, idempotency=IdempotencyPolicy.DERIVED,
        result_budget=ResultBudget(max_chars=7000, max_items=20),
        model_owned_fields=(), provenance="source_refs_required",
    )
    assert contract.public_payload()["effect"] == "read"


def test_registry_rejects_duplicate_name_or_version():
    registry = ToolRegistry()
    registry.register(registration("read_source", "1.0.0"))
    with pytest.raises(ValueError, match="duplicate tool"):
        registry.register(registration("read_source", "1.0.0"))
```

- [ ] **Step 2: Run the focused tests and confirm the modules are missing**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/tool-contract tests/test_tool_contract_service.py tests/test_tool_registry_service.py`

Expected: import failures for the two new services.

- [ ] **Step 3: Implement the exact contract types**

```python
class EffectClass(str, Enum):
    READ = "read"
    COMPUTE = "compute"
    DRAFT = "draft"
    COMMIT = "commit"
    EXTERNAL = "external"
    DESTRUCTIVE = "destructive"


class RetryPolicy(str, Enum):
    NEVER = "never"
    SAFE = "safe"
    IDEMPOTENCY_KEY = "idempotency_key"


class IdempotencyPolicy(str, Enum):
    NONE = "none"
    DERIVED = "derived"
    REQUIRED = "required"


@dataclass(frozen=True)
class ResultBudget:
    max_chars: int
    max_items: int


@dataclass(frozen=True)
class ToolContract:
    name: str
    version: str
    title: str
    category: str
    summary: str
    input_schema: dict[str, Any]
    result_schema: str
    effect: EffectClass
    scopes: tuple[str, ...]
    timeout_seconds: int
    retry: RetryPolicy
    idempotency: IdempotencyPolicy
    result_budget: ResultBudget
    model_owned_fields: tuple[str, ...]
    provenance: str
```

`ToolRegistration` contains one contract, one sync or async handler, an `availability(runtime) -> Availability` predicate and no provider-specific business logic.

- [ ] **Step 4: Migrate existing read tools into one registry**

`ToolHarness.registry()`, `.shortlist()` and `.call()` become compatibility facades over `canonical_tool_registry()`. No handler is copied. Existing `les_tool_result_v1` payloads remain byte-shape compatible.

- [ ] **Step 5: Run compatibility tests**

Run:

```text
uv run python -m pytest -q --basetemp=.test-tmp/tool-registry tests/test_tool_contract_service.py tests/test_tool_registry_service.py tests/test_tool_harness_service.py tests/test_tool_trace_policy.py tests/test_chat_profile_service.py
make architecture-gate
```

Expected: all pass and every registered tool appears exactly once.

- [ ] **Step 6: Update version/docs and commit**

Commit: `feat(tools): add canonical provider-neutral registry`.

### Task 3: Implement the Capability Broker

**Files:**
- Create: `proxy/services/capability_broker_service.py`
- Create: `tests/test_capability_broker_service.py`
- Modify: `proxy/services/tool_harness_service.py`
- Modify: `docs/ALGO-tool-harness.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: `ToolRegistry`, immutable profile tool names, resolved scope, workflow phase, runtime availability, model preset and remaining budgets.
- Produces: `BrokerRequest`, `CapabilityShortlist`, `CapabilityBroker.shortlist()`.

- [ ] **Step 1: Write failing broker tests**

```python
def test_broker_intersects_every_policy_dimension(registry):
    request = BrokerRequest(
        profile_tools=("read_source", "build_lsr_workbook", "delete_dataset"),
        dataset_ids=("ds-1",), workflow_phase="research", model_preset="qwen-9b",
        runtime_available=frozenset({"read_source", "build_lsr_workbook"}),
        calls_remaining=1, result_chars_remaining=7000,
    )
    result = CapabilityBroker(registry).shortlist(request)
    assert result.names == ("read_source",)
    assert result.omitted_by_reason["phase"] == ("build_lsr_workbook",)


def test_9b_and_35b_share_professional_tool_names(registry):
    nine = broker_names(registry, preset="qwen-9b")
    thirty_five = broker_names(registry, preset="qwen-35b")
    assert set(nine) == set(thirty_five)
```

- [ ] **Step 2: Run and confirm failure on the absent broker**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/broker tests/test_capability_broker_service.py`

- [ ] **Step 3: Implement deterministic policy intersection**

```python
@dataclass(frozen=True)
class BrokerRequest:
    profile_tools: tuple[str, ...]
    dataset_ids: tuple[str, ...]
    workflow_phase: str
    model_preset: str
    runtime_available: frozenset[str]
    calls_remaining: int
    result_chars_remaining: int


@dataclass(frozen=True)
class CapabilityShortlist:
    contracts: tuple[ToolContract, ...]
    omitted_by_reason: Mapping[str, tuple[str, ...]]
    call_limit: int
    result_chars_limit: int

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(contract.name for contract in self.contracts)
```

The broker never inspects domain words to choose a professional action. Profile order is stable; the 9B preset returns normally 1–3 and at most 5 contracts, while 35B may return a larger coherent page without changing the set of eligible names.

- [ ] **Step 4: Replace `ToolHarness.shortlist()` internals with broker delegation**

Keep the public compatibility payload `les_tool_shortlist_v1`; add `omitted_by_reason`, `preset` and `budget` fields.

- [ ] **Step 5: Run broker, harness and profile tests**

Run:

```text
uv run python -m pytest -q --basetemp=.test-tmp/broker tests/test_capability_broker_service.py tests/test_tool_harness_service.py tests/test_chat_profile_service.py
make architecture-gate
```

- [ ] **Step 6: Update version/docs and commit**

Commit: `feat(tools): broker profile and runtime capabilities`.

### Task 4: Implement the Trusted Executor and approval boundary

**Files:**
- Create: `proxy/services/trusted_executor_service.py`
- Create: `tests/test_trusted_executor_service.py`
- Create: `tests/test_tools_router.py`
- Modify: `proxy/services/tool_harness_service.py`
- Modify: `proxy/routers/tools.py`
- Modify: `tests/test_tool_harness_service.py`
- Modify: `docs/ALGO-tool-harness.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: registry registration, `ExecutionRequest`, authorization context and optional durable approval receipt.
- Produces: `ExecutionEnvelope` serialized as `les_tool_execution_v1` while preserving nested `les_tool_result_v1`.

- [ ] **Step 1: Write failing executor tests**

```python
async def test_executor_rejects_scope_escape(executor):
    result = await executor.execute(ExecutionRequest(
        call_id="call-1", tool_name="read_source", arguments={"dataset_id": "other"},
        allowed_dataset_ids=("selected",), actor_id="user-1", approval=None,
        idempotency_key=None, deadline_monotonic=time.monotonic() + 5,
    ))
    assert result.status == "rejected"
    assert result.code == "TOOL_SCOPE_VIOLATION"


async def test_executor_requires_revision_bound_approval_for_commit(executor):
    result = await executor.execute(commit_request(approval=None))
    assert result.code == "TOOL_APPROVAL_REQUIRED"
```

- [ ] **Step 2: Run and confirm failure on the absent executor**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/executor tests/test_trusted_executor_service.py`

- [ ] **Step 3: Implement validation and execution envelopes**

```python
@dataclass(frozen=True)
class ExecutionRequest:
    call_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    allowed_dataset_ids: tuple[str, ...]
    actor_id: str
    approval: Mapping[str, Any] | None
    idempotency_key: str | None
    deadline_monotonic: float


class TrustedExecutor:
    async def execute(self, request: ExecutionRequest) -> ExecutionEnvelope:
        registration = self.registry.require(request.tool_name)
        self._validate_schema_scope_and_effect(registration.contract, request)
        raw = await self._invoke_with_timeout(registration, request)
        return self._validate_and_budget_result(registration.contract, request, raw)


@dataclass(frozen=True)
class ExecutionEnvelope:
    schema: str
    call_id: str
    tool_name: str
    status: str
    code: str
    result: Mapping[str, Any]
    cursor: str | None
    omitted_items: int
```

Read/compute/draft effects may execute under their contracts. Commit/external/destructive effects require a durable approval with matching `proposal_revision`, `tool_name`, argument hash and actor. Result overflow returns a cursor/reference and omitted counts; it never slices JSON text.

- [ ] **Step 4: Route legacy calls through the executor**

`ToolHarness.call()` builds a bounded compatibility `ExecutionRequest`; `POST /api/tools/call` supplies the authenticated actor and scope. Direct handler invocation remains private to tests and registry setup.

- [ ] **Step 5: Run executor and API tests**

Run:

```text
uv run python -m pytest -q --basetemp=.test-tmp/executor tests/test_trusted_executor_service.py tests/test_tool_harness_service.py tests/test_tool_trace_policy.py tests/test_tools_router.py
make architecture-gate
```

`tests/test_tools_router.py` uses FastAPI dependency overrides to prove user calls cannot execute commit effects and admin calls still require the bound approval receipt.

- [ ] **Step 6: Update version/docs and commit**

Commit: `feat(tools): execute canonical contracts through trust boundary`.

### Task 5: Integrate one-call model decisions into ordinary chat

**Files:**
- Modify: `proxy/services/chat_evidence_application_service.py`
- Modify: `proxy/routers/chat.py`
- Modify: `tests/test_chat_evidence_application_service.py`
- Modify: `tests/test_chat_harness_format.py`
- Modify: `tests/test_chat_profile_service.py`
- Modify: `docs/ALGO-tool-harness.md`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: `CapabilityBroker.shortlist()` and `TrustedExecutor.execute()`.
- Produces: one validated model decision per turn, one execution envelope and a continued model-composed answer.

- [ ] **Step 1: Write failing ordinary-chat integration tests**

```python
@pytest.mark.asyncio
async def test_chat_executes_only_one_model_decision_before_repacking(runtime):
    result = await run_chat_with_selector_calls([
        {"tool": "read_source", "args": {"doc_id": "d1"}},
        {"tool": "read_source", "args": {"doc_id": "d2"}},
    ], runtime=runtime)
    assert result.trace["tool_loop"]["executed_calls"] == 1
    assert result.trace["tool_loop"]["pending_calls"] == 1


def test_profile_publication_does_not_activate_or_rebind(tmp_path):
    bound = bind_factory_estimator(tmp_path)
    published = publish_estimator_revision(tmp_path)
    assert active_revision(tmp_path, "estimator") != published["revision_id"]
    assert bound_snapshot(tmp_path) == bound
```

- [ ] **Step 2: Run the focused chat/profile tests and confirm the one-call assertion fails**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/chat-tools tests/test_chat_evidence_application_service.py tests/test_chat_profile_service.py`

- [ ] **Step 3: Replace direct harness selection/execution**

The chat path performs:

```python
shortlist = broker.shortlist(broker_request)
decision = parse_one_model_tool_decision(selector_text, allowed=shortlist.names)
execution = await executor.execute(execution_request(decision, request_context))
tool_exchange.append(execution.public_payload())
```

Remove multi-call execution from one selector output. Read calls may be parallel only in the 35B preset after one validated decision explicitly contains an independent read batch; draft tools always execute singly.

- [ ] **Step 4: Preserve immutable profile behavior**

Publishing or seeding a profile revision must never call `activate_profile_revision()` and must never update `les_chat_profile_bindings`. Only the explicit activation route and `apply_revision=True` binding operation may change those records.

- [ ] **Step 5: Run the focused suite and architecture gate**

Run:

```text
uv run python -m pytest -q --basetemp=.test-tmp/chat-tools tests/test_chat_evidence_application_service.py tests/test_chat_profile_service.py tests/test_chat_profile_runtime.py tests/test_chat_harness_format.py tests/test_tool_harness_service.py
make architecture-gate
make verify
```

- [ ] **Step 6: Update version/docs and commit**

Commit: `refactor(chat): use broker and trusted executor`.

### Task 6: Close the foundation gate

**Files:**
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/TEST_INVENTORY.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: verified foundation checkpoint ready for the ContextGovernor plan.

- [ ] **Step 1: Run all focused foundation tests**

```text
uv run python -m pytest -q --basetemp=.test-tmp/foundation tests/test_architecture_contract_gate.py tests/test_tool_contract_service.py tests/test_tool_registry_service.py tests/test_capability_broker_service.py tests/test_trusted_executor_service.py tests/test_tool_harness_service.py tests/test_tool_trace_policy.py tests/test_chat_profile_service.py tests/test_chat_profile_runtime.py tests/test_chat_evidence_application_service.py tests/test_chat_harness_format.py
```

- [ ] **Step 2: Run canonical gates**

```text
make architecture-gate
make verify
make test
git diff --check
```

- [ ] **Step 3: Record exact counts and status**

Update the current architecture and test inventory with exact command output. Do not describe synthetic selector fixtures as live model quality evidence.

- [ ] **Step 4: Commit the verified checkpoint**

Commit: `docs(architecture): record verified agent foundation`.
