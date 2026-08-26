import asyncio
import time

import pytest

from proxy.services.tool_contract_service import (
    EffectClass,
    IdempotencyPolicy,
    ResultBudget,
    RetryPolicy,
    ToolContract,
)
from proxy.services.tool_registry_service import ToolRegistration, ToolRegistry
from proxy.services.trusted_executor_service import (
    ApprovalReceipt,
    ExecutionRequest,
    SqliteExecutionStore,
    TrustedExecutor,
    argument_sha256,
)


def _payload(tool: str, result=None):
    return {
        "schema": "les_tool_result_v1",
        "tool": tool,
        "operation": "call",
        "inputs": [{}],
        "status": "ok",
        "result": {} if result is None else result,
        "sources": [],
        "missing": [],
        "warnings": [],
        "trace": "test handler",
        "decision_required_from_model": True,
    }


def _registration(
    name: str,
    effect: EffectClass,
    handler,
    *,
    idempotency=IdempotencyPolicy.DERIVED,
    max_chars=7000,
    timeout=30,
    input_schema=None,
):
    return ToolRegistration(
        contract=ToolContract(
            name=name,
            version="1.0.0",
            title=name,
            category="test",
            summary=f"Execute {name}",
            input_schema=input_schema or {"type": "object"},
            result_schema="les_tool_result_v1",
            effect=effect,
            scopes=("dataset",),
            timeout_seconds=timeout,
            retry=RetryPolicy.SAFE,
            idempotency=idempotency,
            result_budget=ResultBudget(max_chars=max_chars, max_items=20),
            model_owned_fields=(),
            provenance="source_refs_required",
        ),
        handler=handler,
    )


def _request(tool_name="read_source", arguments=None, **overrides):
    values = {
        "call_id": "call-1",
        "tool_name": tool_name,
        "arguments": {"dataset_id": "selected"} if arguments is None else arguments,
        "allowed_dataset_ids": ("selected",),
        "actor_id": "user-1",
        "actor_role": "admin",
        "approval_receipt_id": None,
        "idempotency_key": None,
        "deadline_monotonic": time.monotonic() + 5,
        "shadow": False,
    }
    values.update(overrides)
    return ExecutionRequest(**values)


@pytest.mark.asyncio
async def test_executor_rejects_scope_escape_before_handler() -> None:
    calls = []
    registry = ToolRegistry(
        [_registration("read_source", EffectClass.READ, lambda args: calls.append(args))]
    )

    result = await TrustedExecutor(registry).execute(
        _request(arguments={"dataset_id": "other"})
    )

    assert result.status == "rejected"
    assert result.code == "TOOL_SCOPE_VIOLATION"
    assert calls == []


@pytest.mark.asyncio
async def test_dataset_scoped_tool_rejects_missing_selector_in_bounded_scope() -> None:
    calls = []
    registry = ToolRegistry(
        [_registration("read_source", EffectClass.READ, lambda args: calls.append(args))]
    )

    result = await TrustedExecutor(registry).execute(_request(arguments={}))

    assert result.code == "TOOL_SCOPE_VIOLATION"
    assert calls == []


@pytest.mark.asyncio
async def test_authoritative_doc_scope_overrides_forged_dataset_argument() -> None:
    calls = []
    registry = ToolRegistry(
        [_registration("read_source", EffectClass.READ, lambda args: calls.append(args))]
    )
    executor = TrustedExecutor(
        registry,
        scope_resolver=lambda _contract, _args: ("foreign",),
    )

    result = await executor.execute(
        _request(arguments={"dataset_id": "selected", "doc_id": "foreign-doc"})
    )

    assert result.code == "TOOL_SCOPE_VIOLATION"
    assert calls == []


@pytest.mark.asyncio
async def test_executor_validates_full_input_schema_before_handler() -> None:
    calls = []
    registry = ToolRegistry(
        [
            _registration(
                "read_source",
                EffectClass.READ,
                lambda args: calls.append(args),
                input_schema={
                    "type": "object",
                    "required": ["dataset_id", "limit"],
                    "properties": {
                        "dataset_id": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1},
                    },
                    "additionalProperties": False,
                },
            )
        ]
    )

    result = await TrustedExecutor(registry).execute(
        _request(arguments={"dataset_id": "selected", "limit": "many"})
    )

    assert result.status == "rejected"
    assert result.code == "TOOL_SCHEMA_INVALID"
    assert calls == []


@pytest.mark.asyncio
async def test_executor_rejects_privileged_effect_for_non_admin_actor(tmp_path) -> None:
    calls = []
    arguments = {"dataset_id": "selected", "proposal_revision": "rev-2"}
    registry = ToolRegistry(
        [
            _registration(
                "commit_report",
                EffectClass.COMMIT,
                lambda args: calls.append(args),
            )
        ]
    )
    store = SqliteExecutionStore(tmp_path / "execution.db")
    store.issue_approval(_approval(arguments))

    result = await TrustedExecutor(registry, store=store).execute(
        _request(
            "commit_report",
            arguments,
            actor_role="user",
            approval_receipt_id="approval-1",
            idempotency_key="commit-1",
        )
    )

    assert result.status == "rejected"
    assert result.code == "TOOL_AUTHORIZATION_REQUIRED"
    assert calls == []


@pytest.mark.asyncio
async def test_executor_requires_revision_bound_approval_for_commit() -> None:
    registry = ToolRegistry(
        [_registration("commit_report", EffectClass.COMMIT, lambda args: _payload("commit_report"))]
    )

    result = await TrustedExecutor(registry).execute(
        _request(
            "commit_report",
            {"dataset_id": "selected", "proposal_revision": "rev-2"},
            idempotency_key="commit-1",
        )
    )

    assert result.status == "rejected"
    assert result.code == "TOOL_APPROVAL_REQUIRED"


@pytest.mark.asyncio
async def test_privileged_effect_requires_idempotency_even_if_contract_is_derived(tmp_path) -> None:
    arguments = {"dataset_id": "selected", "proposal_revision": "rev-2"}
    registry = ToolRegistry(
        [_registration("commit_report", EffectClass.COMMIT, lambda args: _payload("commit_report"))]
    )
    store = SqliteExecutionStore(tmp_path / "execution.db")
    store.issue_approval(_approval(arguments))

    result = await TrustedExecutor(registry, store=store).execute(
        _request(
            "commit_report",
            arguments,
            approval_receipt_id="approval-1",
        )
    )

    assert result.code == "TOOL_IDEMPOTENCY_KEY_REQUIRED"


@pytest.mark.asyncio
async def test_executor_accepts_exact_durable_approval_receipt(tmp_path) -> None:
    arguments = {"dataset_id": "selected", "proposal_revision": "rev-2"}
    registry = ToolRegistry(
        [_registration("commit_report", EffectClass.COMMIT, lambda args: _payload("commit_report"))]
    )
    store = SqliteExecutionStore(tmp_path / "execution.db")
    store.issue_approval(_approval(arguments))

    result = await TrustedExecutor(registry, store=store).execute(
        _request(
            "commit_report",
            arguments,
            approval_receipt_id="approval-1",
            idempotency_key="commit-1",
        )
    )

    assert result.status == "ok"
    assert result.code == "TOOL_OK"
    assert result.result["schema"] == "les_tool_result_v1"


@pytest.mark.asyncio
async def test_revoked_approval_cannot_authorize_or_replay_commit(tmp_path) -> None:
    arguments = {"dataset_id": "selected", "proposal_revision": "rev-2"}
    registry = ToolRegistry(
        [_registration("commit_report", EffectClass.COMMIT, lambda args: _payload("commit_report"))]
    )
    store = SqliteExecutionStore(tmp_path / "execution.db")
    store.issue_approval(_approval(arguments))
    store.revoke_approval("approval-1")

    result = await TrustedExecutor(registry, store=store).execute(
        _request(
            "commit_report",
            arguments,
            approval_receipt_id="approval-1",
            idempotency_key="commit-1",
        )
    )

    assert result.code == "TOOL_APPROVAL_REQUIRED"


@pytest.mark.asyncio
async def test_approval_receipt_cannot_be_reused_with_another_key(tmp_path) -> None:
    arguments = {"dataset_id": "selected", "proposal_revision": "rev-2"}
    registry = ToolRegistry(
        [_registration("commit_report", EffectClass.COMMIT, lambda args: _payload("commit_report"))]
    )
    store = SqliteExecutionStore(tmp_path / "execution.db")
    store.issue_approval(_approval(arguments))
    executor = TrustedExecutor(registry, store=store)

    first = await executor.execute(
        _request(
            "commit_report", arguments, approval_receipt_id="approval-1", idempotency_key="key-1"
        )
    )
    second = await executor.execute(
        _request(
            "commit_report", arguments, approval_receipt_id="approval-1", idempotency_key="key-2"
        )
    )

    assert first.code == "TOOL_OK"
    assert second.code == "TOOL_APPROVAL_ALREADY_USED"


@pytest.mark.asyncio
async def test_privileged_replay_survives_executor_reconstruction(tmp_path) -> None:
    calls = []
    arguments = {"dataset_id": "selected", "proposal_revision": "rev-2"}

    def handler(_args):
        calls.append(1)
        return _payload("commit_report")

    registry = ToolRegistry(
        [_registration("commit_report", EffectClass.COMMIT, handler)]
    )
    store = SqliteExecutionStore(tmp_path / "execution.db")
    store.issue_approval(_approval(arguments))
    request = _request(
        "commit_report",
        arguments,
        approval_receipt_id="approval-1",
        idempotency_key="commit-1",
    )

    first = await TrustedExecutor(registry, store=store).execute(request)
    replay = await TrustedExecutor(
        registry,
        store=SqliteExecutionStore(tmp_path / "execution.db"),
    ).execute(request)

    assert first == replay
    assert calls == [1]


@pytest.mark.asyncio
async def test_shadow_never_executes_draft_or_commit_effects() -> None:
    calls = []
    registry = ToolRegistry(
        [_registration("draft_report", EffectClass.DRAFT, lambda args: calls.append(args))]
    )

    result = await TrustedExecutor(registry).execute(
        _request("draft_report", shadow=True)
    )

    assert result.status == "shadow"
    assert result.code == "TOOL_WOULD_EXECUTE"
    assert calls == []


@pytest.mark.asyncio
async def test_required_idempotency_key_replays_without_second_handler_call() -> None:
    calls = []

    def handler(args):
        calls.append(dict(args))
        return _payload("read_source", {"call_count": len(calls)})

    registry = ToolRegistry(
        [
            _registration(
                "read_source",
                EffectClass.READ,
                handler,
                idempotency=IdempotencyPolicy.REQUIRED,
            )
        ]
    )
    executor = TrustedExecutor(registry)
    request = _request(idempotency_key="stable-key")

    first = await executor.execute(request)
    second = await executor.execute(request)

    assert first == second
    assert calls == [{"dataset_id": "selected"}]


@pytest.mark.asyncio
async def test_concurrent_privileged_idempotency_never_executes_twice(tmp_path) -> None:
    calls = []

    async def handler(args):
        calls.append(dict(args))
        await asyncio.sleep(0.03)
        return _payload("commit_report")

    arguments = {"dataset_id": "selected", "proposal_revision": "rev-2"}
    registry = ToolRegistry(
        [
            _registration(
                "commit_report",
                EffectClass.COMMIT,
                handler,
                idempotency=IdempotencyPolicy.REQUIRED,
            )
        ]
    )
    store = SqliteExecutionStore(tmp_path / "execution.db")
    store.issue_approval(_approval(arguments))
    executor = TrustedExecutor(registry, store=store)
    request = _request(
        "commit_report",
        arguments,
        approval_receipt_id="approval-1",
        idempotency_key="commit-1",
    )

    first, second = await asyncio.gather(executor.execute(request), executor.execute(request))

    assert len(calls) == 1
    assert {first.code, second.code} <= {"TOOL_OK", "TOOL_EXECUTION_IN_PROGRESS"}


@pytest.mark.asyncio
async def test_result_overflow_returns_cursor_without_slicing_json() -> None:
    raw = _payload("read_source", {"rows": [{"id": 1, "text": "x" * 500}]})
    registry = ToolRegistry(
        [_registration("read_source", EffectClass.READ, lambda args: raw, max_chars=120)]
    )
    executor = TrustedExecutor(registry)

    result = await executor.execute(_request())

    assert result.status == "overflow"
    assert result.code == "TOOL_RESULT_BUDGET_EXCEEDED"
    assert result.cursor
    assert result.omitted_items == 0
    assert executor.resolve_cursor(result.cursor, actor_id="user-1") == raw
    assert executor.resolve_cursor(result.cursor, actor_id="other") is None


@pytest.mark.asyncio
async def test_non_json_result_is_typed_instead_of_escaping() -> None:
    raw = _payload("read_source", {"bad": object()})
    registry = ToolRegistry(
        [_registration("read_source", EffectClass.READ, lambda args: raw)]
    )

    result = await TrustedExecutor(registry).execute(_request())

    assert result.status == "error"
    assert result.code == "TOOL_RESULT_INVALID"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.pop("sources"),
        lambda payload: payload.update(status="surprising"),
        lambda payload: payload["result"].update(value=float("nan")),
    ],
)
async def test_malformed_canonical_result_is_rejected(mutate) -> None:
    raw = _payload("read_source")
    mutate(raw)
    registry = ToolRegistry(
        [_registration("read_source", EffectClass.READ, lambda args: raw)]
    )

    result = await TrustedExecutor(registry).execute(_request())

    assert result.status == "error"
    assert result.code == "TOOL_RESULT_INVALID"


@pytest.mark.asyncio
async def test_deadline_timeout_is_typed() -> None:
    async def slow_handler(_args):
        await asyncio.sleep(0.05)
        return _payload("read_source")

    registry = ToolRegistry(
        [_registration("read_source", EffectClass.READ, slow_handler, timeout=1)]
    )

    result = await TrustedExecutor(registry).execute(
        _request(deadline_monotonic=time.monotonic() + 0.001)
    )

    assert result.status == "timeout"
    assert result.code == "TOOL_DEADLINE_EXCEEDED"


def _approval(arguments: dict) -> ApprovalReceipt:
    return ApprovalReceipt(
        receipt_id="approval-1",
        status="approved",
        proposal_revision=str(arguments["proposal_revision"]),
        tool_name="commit_report",
        argument_sha256=argument_sha256(arguments),
        actor_id="user-1",
        expires_at_epoch=time.time() + 60,
    )
