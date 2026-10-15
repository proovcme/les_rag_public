from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import httpx
import pytest

from proxy.services.model_capability_service import (
    CapabilityProbe,
    CapabilityProbeError,
    CapabilityRequirementError,
    require_capabilities,
)
from proxy.services.model_connection_contracts import (
    CapabilityName,
    CapabilityObservation,
    CapabilitySnapshot,
    CapabilityState,
    ConnectionLocality,
    ModelConnectionRevision,
)
from proxy.services.model_connection_registry_service import ModelConnectionRegistry


NOW = datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc)


def _connection(
    *,
    secret_ref: str | None = None,
    extension_type: str | None = None,
) -> ModelConnectionRevision:
    return ModelConnectionRevision(
        connection_id="conn:test",
        revision_id="conn:test:r1",
        revision_no=1,
        display_name="Test model",
        protocol="openai_compatible",
        base_url="http://127.0.0.1:1919/v1",
        model_id="qwen-test",
        locality=ConnectionLocality.LOOPBACK,
        requested_context_tokens=8192,
        secret_ref=secret_ref,
        extension_type=extension_type,
        enabled=True,
        created_at=NOW.isoformat(),
        created_by="admin:test",
    )


def _client(routes: dict[tuple[str, str], tuple[int, object]]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        status, payload = routes.get(
            (request.method, request.url.path),
            (404, {"error": "missing"}),
        )
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload)
        return httpx.Response(status, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


def _peer_ok(_response, _endpoint) -> None:
    return None


@pytest.mark.asyncio
async def test_probe_records_supported_unsupported_unknown_without_model_text() -> None:
    async with _client(
        {
            ("GET", "/v1/models"): (200, {"data": [{"id": "qwen-test"}]}),
            ("POST", "/v1/chat/completions"): (
                200,
                {"choices": [{"message": {"content": "sensitive-output"}}]},
            ),
            ("POST", "/v1/responses"): (404, {"error": "missing"}),
        }
    ) as client:
        snapshot = await CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=_peer_ok,
            clock=lambda: NOW,
        ).probe(
            _connection(),
            requested={
                CapabilityName.MODELS,
                CapabilityName.CHAT_COMPLETIONS,
                CapabilityName.RESPONSES,
            },
        )

    assert snapshot.state(CapabilityName.CHAT_COMPLETIONS) is CapabilityState.SUPPORTED
    assert snapshot.state(CapabilityName.RESPONSES) is CapabilityState.UNSUPPORTED
    assert snapshot.state(CapabilityName.EMBEDDINGS) is CapabilityState.UNKNOWN
    assert snapshot.observation(CapabilityName.CHAT_COMPLETIONS).evidence_source == "probe"
    assert "sensitive-output" not in repr(snapshot)
    assert snapshot.transport_options == {"max_output_field": "max_tokens"}


@pytest.mark.asyncio
async def test_probe_records_native_chat_profile_only_after_live_probe() -> None:
    requests: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        requests.append((request.method, request.url.path, body))
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        if request.url.path == "/api/chat":
            return httpx.Response(200, json={"message": {"content": "ok"}, "done": True})
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={
                    "model_info": {"qwen35.context_length": 32768},
                    "details": {"parameter_size": "9B"},
                },
            )
        return httpx.Response(404, json={"error": "missing"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=_peer_ok,
            clock=lambda: NOW,
        ).probe(
            _connection(extension_type="ollama"),
            requested={CapabilityName.CHAT_COMPLETIONS},
        )

    assert snapshot.transport_options["chat_protocol"] == "native_chat_v1"
    assert snapshot.transport_options["observed_context_tokens"] == "32768"
    native = next(item for item in requests if item[1] == "/api/chat")
    assert native[2]["think"] is False
    show = next(item for item in requests if item[1] == "/api/show")
    assert show[2] == {"model": "qwen-test"}


@pytest.mark.asyncio
async def test_probe_follows_no_redirect_even_when_client_default_does() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/v1/models":
            return httpx.Response(302, headers={"location": "/internal"})
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    ) as client:
        snapshot = await CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=_peer_ok,
            clock=lambda: NOW,
        ).probe(_connection(), requested={CapabilityName.MODELS})

    assert calls == ["/v1/models"]
    assert snapshot.state(CapabilityName.MODELS) is CapabilityState.UNKNOWN
    assert snapshot.observation(CapabilityName.MODELS).detail == "redirect_rejected"


@pytest.mark.asyncio
async def test_probe_caps_response_body_without_retaining_it() -> None:
    async with _client({("GET", "/v1/models"): (200, b"x" * 129)}) as client:
        snapshot = await CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=_peer_ok,
            clock=lambda: NOW,
            response_body_limit=128,
        ).probe(_connection(), requested={CapabilityName.MODELS})

    assert snapshot.state(CapabilityName.MODELS) is CapabilityState.UNKNOWN
    assert snapshot.observation(CapabilityName.MODELS).detail == "response_too_large"
    assert "xxxxxxxx" not in repr(snapshot)


@pytest.mark.asyncio
async def test_probe_validates_connected_peer_before_consuming_stream() -> None:
    body_consumed = False
    peer_checks: list[bool] = []

    class ProbeStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal body_consumed
            body_consumed = True
            yield b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
            yield b"data: [DONE]\n\n"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=ProbeStream())

    def peer_before_close(response: httpx.Response, _endpoint) -> None:
        peer_checks.append(body_consumed)
        if body_consumed:
            raise ValueError("peer metadata is no longer available after body consumption")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    ) as client:
        snapshot = await CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=peer_before_close,
            clock=lambda: NOW,
        ).probe(_connection(), requested={CapabilityName.STREAMING})

    assert peer_checks == [False]
    assert body_consumed is True
    assert snapshot.state(CapabilityName.STREAMING) is CapabilityState.SUPPORTED


def test_required_capability_rejects_stale_snapshot() -> None:
    snapshot = CapabilitySnapshot(
        snapshot_id="cap:stale",
        connection_revision_id="conn:test:r1",
        observations=(
            CapabilityObservation(
                capability=CapabilityName.CHAT_COMPLETIONS,
                state=CapabilityState.SUPPORTED,
                evidence_source="probe",
                observed_at=NOW - timedelta(days=2),
                detail="http_200",
            ),
        ),
        observed_at=NOW - timedelta(days=2),
        expires_at=NOW - timedelta(days=1),
        transport_options={},
    )

    with pytest.raises(CapabilityRequirementError, match="CAPABILITY_SNAPSHOT_STALE"):
        require_capabilities(snapshot, {CapabilityName.CHAT_COMPLETIONS}, now=NOW)


def test_template_default_cannot_authorize_tool_calling() -> None:
    snapshot = CapabilitySnapshot(
        snapshot_id="cap:template",
        connection_revision_id="conn:test:r1",
        observations=(
            CapabilityObservation(
                capability=CapabilityName.TOOLS,
                state=CapabilityState.SUPPORTED,
                evidence_source="template_default",
                observed_at=NOW,
                detail="template_claim",
            ),
        ),
        observed_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        transport_options={},
    )

    with pytest.raises(CapabilityRequirementError, match="CAPABILITY_EVIDENCE_INSUFFICIENT"):
        require_capabilities(snapshot, {CapabilityName.TOOLS}, now=NOW)


def test_supported_fresh_probe_satisfies_requirement() -> None:
    snapshot = CapabilitySnapshot(
        snapshot_id="cap:fresh",
        connection_revision_id="conn:test:r1",
        observations=(
            CapabilityObservation(
                capability=CapabilityName.EMBEDDINGS,
                state=CapabilityState.SUPPORTED,
                evidence_source="probe",
                observed_at=NOW,
                detail="http_200",
            ),
        ),
        observed_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        transport_options={},
    )

    require_capabilities(snapshot, {CapabilityName.EMBEDDINGS}, now=NOW)


@pytest.mark.asyncio
async def test_probe_and_store_persists_one_immutable_snapshot(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    revision = registry.create_connection(
        display_name="Stored probe",
        base_url="http://127.0.0.1:1919/v1",
        model_id="qwen-test",
        locality=ConnectionLocality.LOOPBACK,
        requested_context_tokens=8192,
        secret_ref=None,
        extension_type=None,
        actor="admin:test",
    )
    async with _client({("GET", "/v1/models"): (200, {"data": []})}) as client:
        probe = CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=_peer_ok,
            clock=lambda: NOW,
        )
        snapshot = await probe.probe_and_store(
            revision,
            requested={CapabilityName.MODELS},
            registry=registry,
            actor="admin:test",
        )

    assert registry.latest_capability_snapshot(revision.revision_id) == snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("tools_status", [200, 400, 404])
@pytest.mark.parametrize("expired", [False, True])
async def test_partial_reprobe_remeasures_previous_capabilities_instead_of_erasing_or_reusing_them(
    tmp_path, tools_status, expired,
) -> None:
    registry = ModelConnectionRegistry(tmp_path / "capabilities.db")
    revision = registry.create_connection(
        display_name="Partial probe", base_url="http://127.0.0.1:1919/v1",
        model_id="qwen-test", locality=ConnectionLocality.LOOPBACK,
        requested_context_tokens=8192, secret_ref=None, extension_type=None,
        actor="admin:test",
    )
    calls = []
    now = NOW
    tool_status = 200

    def handler(request):
        body = json.loads(request.content) if request.content else {}
        capability = CapabilityName.TOOLS if body.get("tools") else CapabilityName.CHAT_COMPLETIONS
        calls.append(capability)
        return httpx.Response(tool_status if body.get("tools") else 200, json={"choices": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        probe = CapabilityProbe(client=client, peer_verifier=_peer_ok, clock=lambda: now)
        original = await probe.probe_and_store(
            revision, requested=[CapabilityName.CHAT_COMPLETIONS, CapabilityName.TOOLS],
            registry=registry, actor="admin:test",
        )
        assert original.state(CapabilityName.TOOLS) is CapabilityState.SUPPORTED
        calls.clear()
        now += timedelta(hours=25 if expired else 1)
        tool_status = tools_status
        refreshed = await probe.probe_and_store(
            revision, requested=iter([CapabilityName.CHAT_COMPLETIONS]),
            registry=registry, actor="admin:test",
        )

    expected = {200: CapabilityState.SUPPORTED, 400: CapabilityState.UNKNOWN,
                404: CapabilityState.UNSUPPORTED}[tools_status]
    assert refreshed.state(CapabilityName.TOOLS) is expected
    assert set(calls) == {CapabilityName.CHAT_COMPLETIONS, CapabilityName.TOOLS}
    assert refreshed.observation(CapabilityName.TOOLS).observed_at == now
    assert refreshed.observation(CapabilityName.TOOLS).detail == f"http_{tools_status}"
    assert refreshed.expires_at == now + probe.freshness
    assert refreshed.state(CapabilityName.EMBEDDINGS) is CapabilityState.UNKNOWN
    assert refreshed.observation(CapabilityName.EMBEDDINGS).detail == "not_requested"
    assert original.observation(CapabilityName.TOOLS).observed_at == NOW
    assert registry.latest_capability_snapshot(revision.revision_id) == refreshed


@pytest.mark.asyncio
async def test_partial_reprobe_never_inherits_another_revision_or_template_claim(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "capabilities.db")
    revision = registry.create_connection(
        display_name="Revision isolation", base_url="http://127.0.0.1:1919/v1",
        model_id="qwen-test", locality=ConnectionLocality.LOOPBACK,
        requested_context_tokens=8192, secret_ref=None, extension_type=None,
        actor="admin:test",
    )
    registry.save_capability_snapshot(CapabilitySnapshot(
        snapshot_id="cap:previous", connection_revision_id=revision.revision_id,
        observations=(CapabilityObservation(CapabilityName.TOOLS, CapabilityState.SUPPORTED,
                                           "probe", NOW, "http_200"),),
        observed_at=NOW, expires_at=NOW + timedelta(days=1),
    ), actor="admin:test")
    newer = registry.revise_connection(
        revision.connection_id, expected_revision_id=revision.revision_id,
        actor="admin:test", model_id="another-model",
    )
    registry.save_capability_snapshot(CapabilitySnapshot(
        snapshot_id="cap:template", connection_revision_id=newer.revision_id,
        observations=(CapabilityObservation(CapabilityName.TOOLS, CapabilityState.SUPPORTED,
                                           "template_default", NOW, "template_claim"),),
        observed_at=NOW, expires_at=NOW + timedelta(days=1),
    ), actor="admin:test")
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json={"choices": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await CapabilityProbe(client=client, peer_verifier=_peer_ok,
                                         clock=lambda: NOW).probe_and_store(
            newer, requested=[CapabilityName.CHAT_COMPLETIONS], registry=registry, actor="admin:test",
        )
    assert len(calls) == 1 and calls[0]["model"] == "another-model"
    assert "tools" not in calls[0]
    assert snapshot.state(CapabilityName.TOOLS) is CapabilityState.UNKNOWN


@pytest.mark.asyncio
async def test_partial_reprobe_rechecks_previous_failed_probe_for_recovery(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "capabilities.db")
    revision = registry.create_connection(
        display_name="Probe recovery", base_url="http://127.0.0.1:1919/v1",
        model_id="qwen-test", locality=ConnectionLocality.LOOPBACK,
        requested_context_tokens=8192, secret_ref=None, extension_type=None,
        actor="admin:test",
    )
    tools_status = 400

    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(tools_status if body.get("tools") else 200, json={"choices": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        probe = CapabilityProbe(client=client, peer_verifier=_peer_ok, clock=lambda: NOW)
        failed = await probe.probe_and_store(revision, requested=[CapabilityName.TOOLS],
                                             registry=registry, actor="admin:test")
        assert failed.state(CapabilityName.TOOLS) is CapabilityState.UNKNOWN
        assert failed.observation(CapabilityName.TOOLS).evidence_source == "probe"
        tools_status = 200
        recovered = await probe.probe_and_store(
            revision, requested=[CapabilityName.CHAT_COMPLETIONS], registry=registry, actor="admin:test",
        )
    assert recovered.state(CapabilityName.TOOLS) is CapabilityState.SUPPORTED
    assert recovered.observation(CapabilityName.TOOLS).detail == "http_200"


@pytest.mark.asyncio
async def test_persisted_reprobe_rejects_empty_request_even_after_previous_probe(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "capabilities.db")
    revision = registry.create_connection(
        display_name="Empty request", base_url="http://127.0.0.1:1919/v1",
        model_id="qwen-test", locality=ConnectionLocality.LOOPBACK,
        requested_context_tokens=8192, secret_ref=None, extension_type=None,
        actor="admin:test",
    )
    async with _client({("GET", "/v1/models"): (200, {"data": []})}) as client:
        probe = CapabilityProbe(client=client, peer_verifier=_peer_ok, clock=lambda: NOW)
        first = await probe.probe_and_store(revision, requested=[CapabilityName.MODELS],
                                            registry=registry, actor="admin:test")
        with pytest.raises(CapabilityProbeError, match="CAPABILITY_REQUEST_EMPTY"):
            await probe.probe_and_store(revision, requested=[], registry=registry, actor="admin:test")
    assert registry.latest_capability_snapshot(revision.revision_id) == first


@pytest.mark.asyncio
async def test_probe_rejects_empty_request_set() -> None:
    async with _client({}) as client:
        probe = CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=_peer_ok,
            clock=lambda: NOW,
        )
        with pytest.raises(CapabilityProbeError, match="CAPABILITY_REQUEST_EMPTY"):
            await probe.probe(_connection(), requested=set())


@pytest.mark.asyncio
async def test_freetoken_probe_records_observed_kv_from_cache_status() -> None:
    requests: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        requests.append((request.method, request.url.path, body))
        if request.url.path == "/v1/cache/status":
            return httpx.Response(
                200,
                json={"geometry": {"num_pages": 28001}, "num_pages": 28001},
            )
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "qwen-test"}]})
        return httpx.Response(404, json={"error": "missing"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=_peer_ok,
            clock=lambda: NOW,
        ).probe(
            _connection(extension_type="freetoken"),
            requested={CapabilityName.CHAT_COMPLETIONS},
        )

    assert snapshot.transport_options["observed_context_tokens"] == "28001"
    chat = next(item for item in requests if item[1] == "/v1/chat/completions")
    assert chat[2]["chat_template_kwargs"] == {"enable_thinking": False}
    assert any(item[1] == "/v1/cache/status" for item in requests)
    assert not any(item[1] == "/v1/models" for item in requests)


@pytest.mark.asyncio
async def test_freetoken_probe_falls_back_to_models_context_when_cache_absent() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "qwen-test",
                            "context_length": 28001,
                        },
                        {"id": "other", "context_length": 8192},
                    ]
                },
            )
        if request.url.path == "/v1/cache/status":
            return httpx.Response(404, json={"error": "missing"})
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=_peer_ok,
            clock=lambda: NOW,
        ).probe(
            _connection(extension_type="freetoken"),
            requested={CapabilityName.MODELS},
        )

    assert snapshot.state(CapabilityName.MODELS) is CapabilityState.SUPPORTED
    assert snapshot.transport_options["observed_context_tokens"] == "28001"
    assert requests.count("/v1/cache/status") == 1
    assert requests.count("/v1/models") == 2


@pytest.mark.asyncio
async def test_non_freetoken_probe_does_not_fetch_cache_status() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(200, json={"data": [{"id": "qwen-test"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await CapabilityProbe(
            client=client,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=_peer_ok,
            clock=lambda: NOW,
        ).probe(_connection(), requested={CapabilityName.MODELS})

    assert snapshot.transport_options == {"max_output_field": "max_tokens"}
    assert requests == ["/v1/models"]
    assert "observed_context_tokens" not in snapshot.transport_options
