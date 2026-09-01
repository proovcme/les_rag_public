from __future__ import annotations

from types import SimpleNamespace

import pytest

from proxy.routers import chat
from proxy.services.canonical_route_service import (
    BoundModelChatRunner,
    CanonicalRouteMode,
    ModelChatResult,
)
from proxy.services.model_connection_contracts import ConnectionLocality, ConnectionRole
from proxy.services.model_connection_resolver_service import ModelConnectionResolutionError
from proxy.services.openai_compatible_transport_service import (
    InferenceRequest,
    InferenceResponse,
    ModelTransportError,
)


def _connection(revision_id: str, locality=ConnectionLocality.LOOPBACK):
    return SimpleNamespace(
        connection_id=revision_id.rsplit(":r", 1)[0],
        revision_id=revision_id,
        display_name="Main model",
        model_id="model-1",
        locality=locality,
        base_url="https://must-not-leak.example/v1",
        secret_ref="env:MUST_NOT_LEAK",
    )


class Resolver:
    def __init__(self, primary, fallback=None):
        self.primary = primary
        self.fallback = fallback
        self.resolved_roles = []

    def resolve(self, role, *, required_capabilities=frozenset()):
        self.resolved_roles.append(role)
        if role is ConnectionRole.ANSWER:
            return self.primary
        raise AssertionError(f"unexpected role: {role}")

    def resolve_fallback(self, failed_revision_id, *, required_capabilities=frozenset()):
        if self.fallback is None:
            raise ModelConnectionResolutionError("ROLE_BINDING_MISSING: local_fallback")
        return self.fallback


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.revision_calls = []

    async def complete(self, connection, request):
        self.revision_calls.append(connection.revision_id)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _answer(text: str) -> InferenceResponse:
    return InferenceResponse(text=text, tool_calls=(), finish_reason="stop", usage={})


def _tool_answer(*names: str) -> InferenceResponse:
    return InferenceResponse(
        text="",
        tool_calls=tuple(
            {
                "id": f"call-{index}",
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            }
            for index, name in enumerate(names, 1)
        ),
        finish_reason="tool_calls",
        usage={},
    )


def _request() -> InferenceRequest:
    return InferenceRequest(
        messages=({"role": "user", "content": "Прочитай файл"},),
        max_output_tokens=64,
    )


@pytest.mark.asyncio
async def test_shadow_compares_resolution_without_second_model_call() -> None:
    legacy_calls = []
    resolver = Resolver(_connection("conn:primary:r1"))
    transport = Transport([_answer("candidate must stay unused")])
    runner = BoundModelChatRunner(resolver=resolver, transport=transport)

    async def legacy_call(_request):
        legacy_calls.append("called")
        return _answer("legacy answer")

    result = await runner.complete(
        mode=CanonicalRouteMode.SHADOW,
        request=_request(),
        legacy_complete=legacy_call,
    )

    assert result.response.text == "legacy answer"
    assert result.connection is None
    assert legacy_calls == ["called"]
    assert transport.revision_calls == []


@pytest.mark.asyncio
async def test_active_uses_only_bound_fallback_and_records_revision() -> None:
    primary = _connection("conn:primary:r1")
    fallback = _connection("conn:fallback:r4")
    transport = Transport([ModelTransportError("UPSTREAM_HTTP_ERROR: 503"), _answer("fallback")])
    runner = BoundModelChatRunner(
        resolver=Resolver(primary, fallback),
        transport=transport,
    )

    result = await runner.complete(
        mode=CanonicalRouteMode.ACTIVE,
        request=_request(),
        legacy_complete=lambda _request: pytest.fail("legacy path must not run in active mode"),
    )

    assert result.response.text == "fallback"
    assert result.public_connection_payload() == {
        "connection_id": "conn:fallback",
        "revision_id": "conn:fallback:r4",
        "display_name": "Main model",
        "model_id": "model-1",
        "locality": "loopback",
        "fallback_used": True,
    }
    assert transport.revision_calls == ["conn:primary:r1", "conn:fallback:r4"]


@pytest.mark.asyncio
async def test_active_missing_fallback_preserves_primary_transport_error() -> None:
    primary = _connection("conn:primary:r1")
    transport = Transport([ModelTransportError("UPSTREAM_REQUEST_FAILED")])
    runner = BoundModelChatRunner(resolver=Resolver(primary), transport=transport)

    with pytest.raises(ModelTransportError, match="UPSTREAM_REQUEST_FAILED"):
        await runner.complete(
            mode=CanonicalRouteMode.ACTIVE,
            request=_request(),
            legacy_complete=lambda _request: pytest.fail("legacy fallback is forbidden"),
        )

    assert transport.revision_calls == ["conn:primary:r1"]


def test_assigned_model_timeout_matches_full_chat_window(monkeypatch) -> None:
    monkeypatch.delenv("LES_MODEL_CONNECTION_TIMEOUT_SEC", raising=False)
    assert chat.model_connection_timeout() == 300.0

    monkeypatch.setenv("LES_MODEL_CONNECTION_TIMEOUT_SEC", "420")
    assert chat.model_connection_timeout() == 420.0


@pytest.mark.asyncio
async def test_remote_connection_without_consent_uses_only_explicit_fallback() -> None:
    primary = _connection("conn:remote:r1", ConnectionLocality.REMOTE)
    fallback = _connection("conn:local:r2")
    transport = Transport([_answer("local answer")])
    runner = BoundModelChatRunner(resolver=Resolver(primary, fallback), transport=transport)

    result = await runner.complete(
        mode=CanonicalRouteMode.ACTIVE,
        request=_request(),
        legacy_complete=lambda _request: pytest.fail("legacy fallback is forbidden"),
        remote_allowed=False,
    )

    assert result.response.text == "local answer"
    assert result.fallback_used is True
    assert transport.revision_calls == ["conn:local:r2"]


def test_public_connection_payload_never_contains_endpoint_or_secret() -> None:
    runner_result = ModelChatResult(
        response=_answer("ok"),
        connection=_connection("conn:c1:r1", ConnectionLocality.REMOTE),
        fallback_used=False,
    )

    payload = runner_result.public_connection_payload()

    assert payload["revision_id"] == "conn:c1:r1"
    assert "base_url" not in payload
    assert "secret_ref" not in payload


def test_ordinary_chat_uses_bound_answer_without_promotion_receipt(monkeypatch) -> None:
    primary = _connection("conn:answer:r9")
    resolver = Resolver(primary)
    monkeypatch.setattr(chat, "_model_connection_resolver", lambda: (resolver, object()))
    monkeypatch.setattr(
        chat,
        "resolve_promoted_route",
        lambda **_kwargs: pytest.fail("promotion receipt must not gate a user binding"),
    )

    assert chat._effective_model_connection_mode() is CanonicalRouteMode.ACTIVE
    assert resolver.resolved_roles == [ConnectionRole.ANSWER]


@pytest.mark.asyncio
async def test_active_preserves_every_model_tool_call() -> None:
    primary = _connection("conn:primary:r1")
    runner = BoundModelChatRunner(
        resolver=Resolver(primary),
        transport=Transport([_tool_answer("read_source", "read_table")]),
    )

    result = await runner.complete(
        mode=CanonicalRouteMode.ACTIVE,
        request=_request(),
        legacy_complete=lambda _request: pytest.fail("legacy path must not run"),
    )

    assert [call["function"]["name"] for call in result.response.tool_calls] == [
        "read_source",
        "read_table",
    ]
    assert result.pending_tool_calls == 0


@pytest.mark.asyncio
async def test_free_chat_active_uses_bound_runner_without_legacy_http(monkeypatch) -> None:
    primary = _connection("conn:primary:r7")
    transport = Transport([_answer("active answer")])
    runner = BoundModelChatRunner(resolver=Resolver(primary), transport=transport)
    monkeypatch.setattr(chat, "_bound_model_chat_runner", lambda _client: runner)
    monkeypatch.setattr(chat, "_effective_model_connection_mode", lambda: CanonicalRouteMode.ACTIVE)
    monkeypatch.setattr(chat, "session_memory", lambda *_args, **_kwargs: "remembered")

    result = await chat._run_free_mode(
        chat.ChatRequest(question="Что известно?", mode="free")
    )

    assert result.endswith("active answer")
    assert transport.revision_calls == ["conn:primary:r7"]


@pytest.mark.asyncio
async def test_chat_refreshes_stale_bound_capabilities_without_a_restart(monkeypatch) -> None:
    revision = SimpleNamespace(revision_id="conn:answer:r1")
    binding = SimpleNamespace(connection_revision_id=revision.revision_id)

    class Registry:
        def get_role_binding(self, role):
            return binding if role is ConnectionRole.ANSWER else None

        def get_revision(self, revision_id):
            assert revision_id == revision.revision_id
            return revision

    class StaleResolver:
        def __init__(self):
            self.registry = Registry()
            self.refreshed = False

        def resolve(self, role):
            assert role is ConnectionRole.ANSWER
            if not self.refreshed:
                raise ModelConnectionResolutionError("CAPABILITY_SNAPSHOT_STALE")
            return _connection(revision.revision_id)

    resolver = StaleResolver()
    probes = []

    class Probe:
        async def probe_and_store(self, connection, *, requested, registry, actor):
            probes.append((connection.revision_id, requested, actor))
            resolver.refreshed = True

    monkeypatch.setattr(chat, "_model_connection_resolver", lambda: (resolver, object()))
    monkeypatch.setattr(chat, "_model_capability_probe", lambda *_args: Probe())

    await chat._refresh_stale_bound_model_capabilities(object())

    assert len(probes) == 1
    assert probes[0][0] == revision.revision_id
    assert probes[0][2] == "system:chat-capability-refresh"


@pytest.mark.asyncio
async def test_installed_chat_rejects_per_request_provider_secret(monkeypatch) -> None:
    monkeypatch.delenv("LES_DEMO_PROVIDER_OVERRIDE_ENABLED", raising=False)
    monkeypatch.setattr(
        chat,
        "_run_chat",
        lambda *_args, **_kwargs: pytest.fail("request override must fail before chat"),
    )
    request = chat.ChatRequest(
        question="test",
        provider_config={
            "provider": "openrouter",
            "model": "openai/test",
            "api_key": "sk-private-key",
        },
    )

    with pytest.raises(chat.HTTPException) as error:
        await chat._run_chat_with_provider(request)

    assert error.value.status_code == 409
    assert error.value.detail == "SESSION_PROVIDER_OVERRIDE_DISABLED"
