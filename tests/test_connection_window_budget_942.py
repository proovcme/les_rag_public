"""Characterization for the 8214-token window measured on the installed 941 runtime.

Live evidence, frozen § 4 diagnostic set, one model / one server / one revision (Qwen3.6-35B-A3B-NVFP4,
`conn:9458be3549ad449985f9eb10dba3c9e1:r10`), identical evidence per condition:

    condition A  finish_reason=length  prompt 5572 + completion 2642 = 8214
    condition B  finish_reason=length  prompt 6882 + completion 1332 = 8214
    condition C  UPSTREAM_HTTP_ERROR 400 (the instruction stack alone no longer fitted)

The two totals are exactly the capability-observed window (transport_options
observed_context_tokens = 8214, while the model advertises 262144 and the operator requested
131072). The OpenAI-compatible path was used (`chat_protocol` absent), so the harness did not send
`num_ctx`: the ceiling is the server's, measured correctly, not a transport miscalculation.

What these tests pin is the convention that makes the measurement readable, because mixing the two
numbers would silently change every packet size:

* `preset.input_token_limit` is the whole observed window (8214);
* the ContextGovernor packet budget is that window minus the declared generation and safety
  reserves — 8214 − 1200 − 512 = 6502, which is exactly the budget the live overflow reported
  («required context needs 6528 tokens but budget is 6502»).

A regression here would make the harness either over-pack a window the server cannot serve or
shrink every packet twice.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from proxy.services.context_governor_service import (
    ContextCandidate,
    ContextGovernor,
    ContextKind,
    ContextObject,
    ContextRequiredSectionOverflow,
)
from proxy.services.llm_transport_profile_service import resolve_connection_execution_profile
from proxy.services.model_connection_contracts import (
    CapabilityName,
    CapabilityObservation,
    CapabilitySnapshot,
    CapabilityState,
    ConnectionLocality,
)
from proxy.services.model_connection_resolver_service import ResolvedModelConnection
from proxy.services.model_connection_security_service import ValidatedEndpoint
from proxy.services.model_execution_preset_service import (
    BackendCapacity,
    resolve_execution_preset,
)
from proxy.services.openai_compatible_transport_service import (
    InferenceRequest,
    OpenAICompatibleTransport,
)

NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)
ANSWER_MODEL = "Qwen3.6-35B-A3B-NVFP4"
OBSERVED_WINDOW = 8214


def _profile(window: int = OBSERVED_WINDOW):
    return resolve_connection_execution_profile(
        model_id=ANSWER_MODEL,
        requested_context_tokens=131072,
        observed_context_tokens=window,
        observed_source="probe",
        provider="freetoken",
        chat_options=None,
        remote=False,
    )


def _connection(window: int) -> ResolvedModelConnection:
    snapshot = CapabilitySnapshot(
        snapshot_id="cap:window:r1",
        connection_revision_id="conn:window:r1",
        observations=tuple(
            CapabilityObservation(
                capability=capability,
                state=CapabilityState.SUPPORTED,
                evidence_source="probe",
                observed_at=NOW,
                detail="http_200",
            )
            for capability in (CapabilityName.CHAT_COMPLETIONS, CapabilityName.STREAMING,
                               CapabilityName.TOOLS)
        ),
        observed_at=NOW,
        expires_at=NOW + timedelta(days=1),
        transport_options={"max_output_field": "max_tokens",
                           "observed_context_tokens": str(window)},
    )
    endpoint = ValidatedEndpoint(
        canonical_base_url="http://127.0.0.1:1919/v1",
        locality=ConnectionLocality.LOOPBACK,
        host="127.0.0.1",
        port=1919,
        allowed_addresses=frozenset(),
    )
    return ResolvedModelConnection(
        connection_id="conn:window",
        revision_id="conn:window:r1",
        display_name="FreeToken 35B NVFP4",
        base_url=endpoint.canonical_base_url,
        model_id=ANSWER_MODEL,
        locality=ConnectionLocality.LOOPBACK,
        requested_context_tokens=131072,
        secret_ref=None,
        extension_type="freetoken",
        capability_snapshot=snapshot,
        endpoint=endpoint,
        effective_preset=resolve_execution_preset(
            BackendCapacity("connection", ANSWER_MODEL, window, True, "probe")),
    )


def test_input_limit_is_the_whole_observed_window_and_the_packet_gives_reserves_back():
    """8214 measured live; the governor budget must be 8214 − 1200 − 512 = 6502, not 8214."""
    preset = _profile()
    assert preset.input_token_limit == OBSERVED_WINDOW
    budget = ContextGovernor(preset).pack([
        ContextCandidate(
            ContextKind.REQUEST,
            (ContextObject("one", "проверка"),),
            required=True,
        ),
    ]).input_budget_tokens
    assert budget == (preset.input_token_limit - preset.generation_reserve_tokens
                      - preset.safety_reserve_tokens) == 6502


def test_a_required_packet_beyond_the_window_minus_reserves_is_refused_not_truncated():
    """The live overflow: six full cards needed 6528 estimated tokens against a 6502 budget."""
    preset = _profile()
    # ~13 100 characters ≈ 6550 estimated tokens under the conservative chars/2 estimate.
    oversized = "а" * (preset.input_token_limit * 2 + 200)
    with pytest.raises(ContextRequiredSectionOverflow):
        ContextGovernor(preset).pack([
            ContextCandidate(ContextKind.REQUEST,
                             (ContextObject("cards", oversized),), required=True),
        ])


def test_the_native_path_still_names_the_same_window_it_was_given():
    """Only the native protocol sends a context size; it must stay the observed window.

    Today FreeToken answers on the OpenAI-compatible path (`chat_protocol` absent), which is why
    the 8214 ceiling could not have been caused by a value we invented ourselves.
    """
    connection = _connection(OBSERVED_WINDOW)
    body = OpenAICompatibleTransport._native_chat_body(
        connection,
        InferenceRequest(messages=({"role": "user", "content": "Строка."},), max_output_tokens=64),
    )
    assert body["options"]["num_ctx"] == OBSERVED_WINDOW
