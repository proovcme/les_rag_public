from types import SimpleNamespace

import pytest

from proxy.services.canonical_route_service import (
    BoundModelChatRunner,
    CanonicalRouteMode,
    PromotionReceipt,
    canonical_route_trace_payload,
    one_model_decision_from_calls,
    resolve_canonical_route,
)
from proxy.services.model_connection_contracts import ConnectionLocality, ConnectionRole
from proxy.services.openai_compatible_transport_service import (
    InferenceRequest, InferenceResponse, ModelTransportError,
)


def test_missing_route_setting_defaults_to_shadow_without_promotion(monkeypatch) -> None:
    monkeypatch.delenv("LES_CANONICAL_AGENT_ROUTE_MODE", raising=False)

    decision = resolve_canonical_route(receipt=None)

    assert decision.requested is CanonicalRouteMode.SHADOW
    assert decision.effective is CanonicalRouteMode.SHADOW


def test_trace_reports_actual_active_execution_for_ordinary_bound_chat(monkeypatch) -> None:
    monkeypatch.delenv("LES_CANONICAL_AGENT_ROUTE_MODE", raising=False)
    decision = resolve_canonical_route(receipt=None)

    payload = canonical_route_trace_payload(
        decision,
        execution_mode=CanonicalRouteMode.ACTIVE,
        candidate_acceptance=False,
    )

    assert payload["requested"] == "shadow"
    assert payload["effective"] == "active"
    assert payload["reason"] == "answer_binding_active"


def test_active_without_exact_receipt_fails_closed_to_shadow(monkeypatch) -> None:
    monkeypatch.setenv("LES_CANONICAL_AGENT_ROUTE_MODE", "active")

    decision = resolve_canonical_route(receipt=None)

    assert decision.requested is CanonicalRouteMode.ACTIVE
    assert decision.effective is CanonicalRouteMode.SHADOW
    assert decision.reason == "promotion_receipt_missing_or_stale"


def test_only_exact_passing_promotion_receipt_can_activate(monkeypatch) -> None:
    monkeypatch.setenv("LES_CANONICAL_AGENT_ROUTE_MODE", "active")
    receipt = PromotionReceipt(
        source_commit="abc123",
        build_number=596,
        preset_id="qwen-9b",
        observed_model_identity="qwen3.5:9b",
        acceptance_sha256="a" * 64,
        passed=True,
    )

    decision = resolve_canonical_route(
        receipt=receipt,
        expected_commit="abc123",
        expected_build=596,
        expected_preset="qwen-9b",
        expected_model_identity="qwen3.5:9b",
        expected_acceptance_sha256="a" * 64,
    )

    assert decision.effective is CanonicalRouteMode.ACTIVE


def test_one_model_decision_executes_only_first_allowed_call() -> None:
    decision = one_model_decision_from_calls(
        [
            {"tool": "read_source", "args": {"doc_id": "d1"}},
            {"tool": "read_source", "args": {"doc_id": "d2"}},
        ],
        allowed={"read_source"},
    )

    assert decision.call == {"tool": "read_source", "args": {"doc_id": "d1"}}
    assert decision.executed_calls == 1
    assert decision.pending_calls == 1


def test_model_decision_rejects_unlisted_and_malformed_calls() -> None:
    decision = one_model_decision_from_calls(
        [
            {"tool": "delete_dataset", "args": {}},
            {"tool": "read_source", "args": "bad"},
        ],
        allowed={"read_source"},
    )

    assert decision.call is None
    assert decision.executed_calls == 0
    assert decision.pending_calls == 0


class _CountBoundResolver:
    def __init__(self, primary_revision="primary-r1", *, remote=False):
        self.primary = SimpleNamespace(revision_id=primary_revision,
                                       locality=ConnectionLocality.REMOTE if remote else ConnectionLocality.LOOPBACK)
        self.fallback = SimpleNamespace(revision_id="fallback-r1", locality=ConnectionLocality.LOOPBACK)
        self.fallback_requests = []

    def resolve(self, role):
        assert role is ConnectionRole.ANSWER
        return self.primary

    def resolve_fallback(self, revision):
        self.fallback_requests.append(revision)
        return self.fallback


class _CountBoundTransport:
    def __init__(self, *, primary_fails=False):
        self.calls = []
        self.primary_fails = primary_fails

    async def complete(self, connection, request):
        self.calls.append((connection.revision_id, request))
        if self.primary_fails and len(self.calls) == 1:
            raise ModelTransportError("UPSTREAM_REQUEST_FAILED")
        return InferenceResponse(text="literal answer", tool_calls=(), finish_reason="stop", usage={})


def _count_request():
    return InferenceRequest(messages=({"role": "user", "content": "original complete request"},), max_output_tokens=128)


@pytest.mark.asyncio
async def test_counted_primary_revision_unchanged_passes_same_literal_request():
    resolver, transport = _CountBoundResolver(), _CountBoundTransport()
    request = _count_request()
    result = await BoundModelChatRunner(resolver=resolver, transport=transport).complete(
        mode=CanonicalRouteMode.ACTIVE, request=request,
        legacy_complete=lambda _: pytest.fail("no legacy generation"),
        expected_connection_revision_id="primary-r1",
    )
    assert transport.calls == [("primary-r1", request)]
    assert result.connection is resolver.primary and result.fallback_used is False
    assert resolver.fallback_requests == []


@pytest.mark.asyncio
async def test_changed_counted_primary_is_rejected_before_any_generation():
    resolver, transport = _CountBoundResolver("primary-r2"), _CountBoundTransport()
    with pytest.raises(ModelTransportError, match="^TOKEN_COUNT_CONNECTION_CHANGED$"):
        await BoundModelChatRunner(resolver=resolver, transport=transport).complete(
            mode=CanonicalRouteMode.ACTIVE, request=_count_request(),
            legacy_complete=lambda _: pytest.fail("no legacy generation"),
            expected_connection_revision_id="primary-r1",
        )
    assert transport.calls == [] and resolver.fallback_requests == []


@pytest.mark.asyncio
async def test_changed_fallback_after_primary_failure_cannot_use_primary_count():
    resolver, transport = _CountBoundResolver(), _CountBoundTransport(primary_fails=True)
    request = _count_request()
    with pytest.raises(ModelTransportError, match="^TOKEN_COUNT_CONNECTION_CHANGED$"):
        await BoundModelChatRunner(resolver=resolver, transport=transport).complete(
            mode=CanonicalRouteMode.ACTIVE, request=request,
            legacy_complete=lambda _: pytest.fail("no legacy generation"),
            expected_connection_revision_id="primary-r1",
        )
    assert transport.calls == [("primary-r1", request)]
    assert resolver.fallback_requests == ["primary-r1"]


@pytest.mark.asyncio
async def test_remote_denial_changed_fallback_is_rejected_before_any_generation():
    resolver, transport = _CountBoundResolver(remote=True), _CountBoundTransport()
    with pytest.raises(ModelTransportError, match="^TOKEN_COUNT_CONNECTION_CHANGED$"):
        await BoundModelChatRunner(resolver=resolver, transport=transport).complete(
            mode=CanonicalRouteMode.ACTIVE, request=_count_request(), remote_allowed=False,
            legacy_complete=lambda _: pytest.fail("no legacy generation"),
            expected_connection_revision_id="primary-r1",
        )
    assert transport.calls == [] and resolver.fallback_requests == ["primary-r1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("remote_denied", [False, True])
async def test_no_count_binding_keeps_existing_fallback_policy(remote_denied):
    resolver = _CountBoundResolver(remote=remote_denied)
    transport = _CountBoundTransport(primary_fails=not remote_denied)
    request = _count_request()
    result = await BoundModelChatRunner(resolver=resolver, transport=transport).complete(
        mode=CanonicalRouteMode.ACTIVE, request=request, remote_allowed=not remote_denied,
        legacy_complete=lambda _: pytest.fail("no legacy generation"),
    )
    assert [revision for revision, _ in transport.calls] == (["fallback-r1"] if remote_denied else ["primary-r1", "fallback-r1"])
    assert all(sent is request for _, sent in transport.calls)
    assert resolver.fallback_requests == ["primary-r1"] and result.fallback_used is True
    assert result.connection is resolver.fallback


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [CanonicalRouteMode.LEGACY, CanonicalRouteMode.SHADOW])
async def test_count_binding_cannot_authorize_unbound_legacy_generation(mode):
    resolver, transport = _CountBoundResolver(), _CountBoundTransport()
    with pytest.raises(ModelTransportError, match="^TOKEN_COUNT_CONNECTION_CHANGED$"):
        await BoundModelChatRunner(resolver=resolver, transport=transport).complete(
            mode=mode, request=_count_request(),
            legacy_complete=lambda _: pytest.fail("count cannot authorize unknown legacy model"),
            expected_connection_revision_id="primary-r1",
        )
    assert transport.calls == [] and resolver.fallback_requests == []
