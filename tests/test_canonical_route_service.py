from proxy.services.canonical_route_service import (
    CanonicalRouteMode,
    PromotionReceipt,
    canonical_route_trace_payload,
    one_model_decision_from_calls,
    resolve_canonical_route,
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
