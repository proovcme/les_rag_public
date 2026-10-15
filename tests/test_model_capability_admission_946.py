from __future__ import annotations

from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as application
from proxy.services.canonical_route_service import BoundModelChatRunner, CanonicalRouteMode
from proxy.services.model_connection_contracts import CapabilityName, CapabilityState, ConnectionRole
from proxy.services.openai_compatible_transport_service import (
    InferenceRequest, ModelTransportError, OpenAICompatibleTransport,
)
from proxy.services.public_error_service import public_error_payload
from tests.test_chat_evidence_application_service import (
    test_actual_chat_shadow_failure_preserves_legacy_answer_history_and_model_count as _run_actual_chat,
)
from tests.test_openai_compatible_transport_service import _resolved, _transport


def _tools_unavailable(*, state=CapabilityState.UNKNOWN, evidence_source="unavailable"):
    connection = _resolved()
    observation = SimpleNamespace(state=state, evidence_source=evidence_source)
    return SimpleNamespace(
        capability_snapshot=SimpleNamespace(
            observation=lambda capability: observation if capability is CapabilityName.TOOLS
            else connection.capability_snapshot.observation(capability),
            transport_options=connection.capability_snapshot.transport_options,
        ),
        **{key: value for key, value in vars(connection).items() if key != "capability_snapshot"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("state,evidence_source,code", [
    (CapabilityState.UNKNOWN, "unavailable", "CAPABILITY_REQUIRED"),
    (CapabilityState.SUPPORTED, "template_default", "CAPABILITY_EVIDENCE_INSUFFICIENT"),
    (CapabilityState.SUPPORTED, "unavailable", "CAPABILITY_EVIDENCE_INSUFFICIENT"),
])
async def test_unconfirmed_tools_fail_before_http_with_specific_public_error(
    tmp_path, state, evidence_source, code,
):
    def reject_http(_request):
        pytest.fail("capability admission must fail before sending a model request")

    transport, client = _transport(tmp_path, reject_http)
    try:
        with pytest.raises(ModelTransportError, match=f"{code}: tools") as error:
            await transport.complete(
                _tools_unavailable(state=state, evidence_source=evidence_source),
                InferenceRequest(messages=({"role": "user", "content": "test"},), max_output_tokens=1,
                                 tools=({"type": "function", "function": {"name": "read_source"}},)),
            )
    finally:
        await client.aclose()
    assert getattr(error.value, "code", None) == code
    detail = getattr(error.value, "public_detail", {})
    assert detail["code"] == code
    assert "tools" in detail["detail"]
    assert public_error_payload(status_code=409, detail=detail) == detail


@pytest.mark.asyncio
async def test_capability_admission_does_not_attempt_another_model():
    connection = _tools_unavailable()

    class Resolver:
        def resolve(self, role):
            assert role is ConnectionRole.ANSWER
            return connection

        def resolve_fallback(self, *_args, **_kwargs):
            pytest.fail("unconfirmed tools are configuration evidence, not an upstream failure")

    class Transport:
        async def complete(self, _connection, _request):
            OpenAICompatibleTransport._require(connection, CapabilityName.TOOLS)

    with pytest.raises(ModelTransportError, match="CAPABILITY_REQUIRED: tools"):
        await BoundModelChatRunner(resolver=Resolver(), transport=Transport()).complete(
            mode=CanonicalRouteMode.ACTIVE,
            request=InferenceRequest(messages=({"role": "user", "content": "test"},), max_output_tokens=1),
            legacy_complete=lambda _request: pytest.fail("no legacy fallback"),
        )


@pytest.mark.asyncio
async def test_actual_chat_reports_capability_failure_instead_of_upstream_502(monkeypatch, tmp_path):
    async def setup(request, runtime, boundary):
        transport = runtime.model_connection_transport(None, None)
        attempts = []

        async def denied(_connection, _request):
            attempts.append(_request)
            OpenAICompatibleTransport._require(_tools_unavailable(), CapabilityName.TOOLS)

        monkeypatch.setattr(transport, "complete", denied)
        with pytest.raises(application.HTTPException) as error:
            await application.run_chat_evidence_application(request, runtime, boundary)
        assert error.value.status_code == 409
        payload = public_error_payload(status_code=error.value.status_code, detail=error.value.detail)
        assert payload["code"] == "CAPABILITY_REQUIRED"
        assert "tools" in payload["detail"]
        assert "secret" not in payload["detail"] and "http" not in payload["detail"]
        assert len(attempts) == 1

    await _run_actual_chat(monkeypatch, tmp_path, "active_web_research", application_setup=setup)
