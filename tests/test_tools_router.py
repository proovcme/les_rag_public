from fastapi import FastAPI
from fastapi.testclient import TestClient

from proxy.routers import tools as tools_router
from proxy.security import RequestUser, get_request_user
from proxy.services.tool_contract_service import (
    EffectClass,
    IdempotencyPolicy,
    ResultBudget,
    RetryPolicy,
    ToolContract,
)
from proxy.services.tool_registry_service import ToolRegistration, ToolRegistry
from proxy.services.trusted_executor_service import TrustedExecutor


def _commit_executor() -> TrustedExecutor:
    contract = ToolContract(
        name="commit_report",
        version="1.0.0",
        title="Commit report",
        category="test",
        summary="Commit an approved report",
        input_schema={"type": "object"},
        result_schema="les_tool_result_v1",
        effect=EffectClass.COMMIT,
        scopes=("dataset",),
        timeout_seconds=30,
        retry=RetryPolicy.IDEMPOTENCY_KEY,
        idempotency=IdempotencyPolicy.REQUIRED,
        result_budget=ResultBudget(max_chars=7000, max_items=20),
        model_owned_fields=(),
        provenance="source_refs_required",
    )
    registration = ToolRegistration(
        contract=contract,
        handler=lambda args: {
            "schema": "les_tool_result_v1",
            "tool": "commit_report",
            "operation": "call",
            "inputs": [args],
            "status": "ok",
            "result": {},
            "trace": "committed",
            "decision_required_from_model": True,
        },
    )
    return TrustedExecutor(ToolRegistry([registration]))


def _client(user: RequestUser) -> TestClient:
    app = FastAPI()
    app.include_router(tools_router.router)
    app.dependency_overrides[get_request_user] = lambda: user
    return TestClient(app)


def test_user_cannot_reach_tool_executor() -> None:
    with _client(RequestUser(role="user", holder="u1")) as client:
        response = client.post("/api/tools/call", json={"tool": "read_source", "args": {}})

    assert response.status_code == 403


def test_admin_commit_still_requires_bound_approval(monkeypatch) -> None:
    monkeypatch.setattr(tools_router, "_executor", _commit_executor)
    request = {
        "tool": "commit_report",
        "args": {"dataset_id": "selected", "proposal_revision": "rev-2"},
        "idempotency_key": "commit-1",
        "timeout_seconds": 5,
    }

    with _client(RequestUser(role="admin", holder="admin-1")) as client:
        response = client.post("/api/tools/call", json=request)

    assert response.status_code == 200
    assert response.json()["code"] == "TOOL_APPROVAL_REQUIRED"


def test_public_tool_request_cannot_declare_its_own_scope() -> None:
    fields = tools_router.ToolCallRequest.model_fields

    assert "allowed_dataset_ids" not in fields
    assert "deadline_monotonic" not in fields
    assert "approval" not in fields


def test_actor_identity_does_not_collapse_keys_with_same_holder() -> None:
    first = RequestUser(role="admin", holder="same", key_value="key-a", source="api_key")
    second = RequestUser(role="admin", holder="same", key_value="key-b", source="api_key")

    assert tools_router._actor_id(first) != tools_router._actor_id(second)
    assert "key-a" not in tools_router._actor_id(first)
