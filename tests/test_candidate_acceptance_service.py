import asyncio

import pytest
from fastapi import HTTPException

from proxy.security import ADMIN_ROLE, RequestUser, USER_ROLE
from proxy.services.candidate_acceptance_service import (
    CandidateAcceptanceError,
    execution_mode_for_candidate_acceptance,
    require_candidate_acceptance,
)
from proxy.services.canonical_route_service import CanonicalRouteMode, resolve_canonical_route


def _root_admin() -> RequestUser:
    return RequestUser(role=ADMIN_ROLE, source="trusted_network")


def test_candidate_acceptance_requires_root_admin_and_exact_isolated_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LES_CANONICAL_ACCEPTANCE_STATE_ROOT", str(tmp_path))

    with pytest.raises(CandidateAcceptanceError, match="ROOT_ADMIN"):
        require_candidate_acceptance(
            requested=True,
            user=RequestUser(role=USER_ROLE, source="api_key"),
        )

    assert require_candidate_acceptance(requested=True, user=_root_admin()) is True


def test_candidate_acceptance_rejects_missing_or_nonisolated_state_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LES_CANONICAL_ACCEPTANCE_STATE_ROOT", raising=False)
    with pytest.raises(CandidateAcceptanceError, match="STATE_ROOT_REQUIRED"):
        require_candidate_acceptance(requested=True, user=_root_admin())

    other = tmp_path / "not-the-process-cwd"
    other.mkdir()
    monkeypatch.setenv("LES_CANONICAL_ACCEPTANCE_STATE_ROOT", str(other))
    with pytest.raises(CandidateAcceptanceError, match="STATE_ROOT_NOT_PROCESS_CWD"):
        require_candidate_acceptance(requested=True, user=_root_admin())


def test_candidate_acceptance_enables_execution_without_changing_public_route(monkeypatch):
    monkeypatch.setenv("LES_CANONICAL_AGENT_ROUTE_MODE", "active")
    decision = resolve_canonical_route(receipt=None)

    assert decision.effective is CanonicalRouteMode.SHADOW
    assert execution_mode_for_candidate_acceptance(
        candidate_acceptance=False,
        route=decision,
    ) is CanonicalRouteMode.SHADOW
    assert execution_mode_for_candidate_acceptance(
        candidate_acceptance=True,
        route=decision,
    ) is CanonicalRouteMode.ACTIVE


def test_ordinary_stream_rejects_candidate_request_before_chat_execution(monkeypatch, tmp_path):
    from proxy.routers import chat

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LES_CANONICAL_ACCEPTANCE_STATE_ROOT", str(tmp_path))
    request = chat.ChatRequest(question="build workbook", candidate_acceptance=True)

    with pytest.raises(HTTPException, match="ROOT_ADMIN") as error:
        asyncio.run(
            chat.chat_stream(request, _user=RequestUser(role=USER_ROLE, source="api_key"))
        )
    assert error.value.status_code == 403


def test_runtime_registry_exposes_candidate_state_root_as_read_only_danger(monkeypatch):
    from proxy.services import runtime_config_registry_service as registry

    monkeypatch.delenv("LES_CANONICAL_ACCEPTANCE_STATE_ROOT", raising=False)
    registry.declared_env_defaults.cache_clear()
    registry.declared_env_keys.cache_clear()
    snapshot = registry.registry_snapshot()
    factor = next(
        item
        for item in snapshot["factors"]
        if item["key"] == "LES_CANONICAL_ACCEPTANCE_STATE_ROOT"
    )

    assert factor["effective_value"] == ""
    assert factor["danger_label"] == "Danger"
    assert factor["mutable"] is False
    assert factor["restart_required"] is True
