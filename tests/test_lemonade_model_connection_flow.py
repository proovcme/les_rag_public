from __future__ import annotations

from datetime import datetime, timezone
import json

import httpx
import pytest

from proxy.services.model_capability_service import CapabilityProbe
from proxy.services.model_connection_contracts import (
    CapabilityName,
    ConnectionLocality,
    ConnectionRole,
)
from proxy.services.model_connection_registry_service import ModelConnectionRegistry
from proxy.services.model_connection_resolver_service import ModelConnectionResolver
from proxy.services.model_secret_service import EnvironmentSecretStore
from proxy.services.openai_compatible_transport_service import (
    InferenceRequest,
    OpenAICompatibleTransport,
)


NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
MODEL_ID = "Carnice-Qwen3.6-MoE-35B-A3B-i1-GGUF-IQ2_S"


@pytest.mark.asyncio
@pytest.mark.parametrize("requested", [{CapabilityName.MODELS, CapabilityName.CHAT_COMPLETIONS}, {CapabilityName.CHAT_COMPLETIONS}])
async def test_lemonade_probe_snapshot_resolver_and_canonical_request_are_one_flow(
    tmp_path, requested,
) -> None:
    requests: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        requests.append((request.method, request.url.path, body))
        if request.method == "GET" and request.url.path == "/api/v1/models":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": MODEL_ID,
                            "recipe": "llamacpp",
                            "max_context_window": 262_144,
                            "recipe_options": {"ctx_size": 32_768},
                        }
                    ]
                },
            )
        if request.method == "POST" and request.url.path == "/api/v1/chat/completions":
            return httpx.Response(
                200,
                json={
                    "model": MODEL_ID,
                    "choices": [
                        {"message": {"content": "Готово"}, "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1},
                },
            )
        return httpx.Response(404, json={"error": "missing"})

    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    revision = registry.create_connection(
        display_name="Lemonade Answer 35B",
        base_url="http://127.0.0.1:13305/api/v1",
        model_id=MODEL_ID,
        locality=ConnectionLocality.LOOPBACK,
        requested_context_tokens=32_768,
        secret_ref=None,
        extension_type="lemonade",
        actor="admin:test",
    )
    secrets = EnvironmentSecretStore(tmp_path / ".env", environ={})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await CapabilityProbe(
            client=client,
            secret_store=secrets,
            resolver=lambda _host, _port: ("127.0.0.1",),
            peer_verifier=lambda _response, _endpoint: None,
            clock=lambda: NOW,
        ).probe_and_store(
            revision,
            requested=requested,
            registry=registry,
            actor="admin:test",
        )
        registry.bind_role(
            ConnectionRole.ANSWER,
            revision.revision_id,
            expected_binding_revision=None,
            actor="admin:test",
        )
        resolved = ModelConnectionResolver(
            registry=registry,
            secret_store=secrets,
            address_resolver=lambda _host, _port: ("127.0.0.1",),
            clock=lambda: NOW,
        ).resolve(ConnectionRole.ANSWER)
        response = await OpenAICompatibleTransport(
            client=client,
            secret_store=secrets,
            peer_verifier=lambda _response, _endpoint: None,
        ).complete(
            resolved,
            InferenceRequest(
                messages=({"role": "user", "content": "Ответь: готово"},),
                max_output_tokens=32,
                temperature=0.0,
            ),
        )

    assert snapshot == registry.latest_capability_snapshot(revision.revision_id)
    assert resolved.effective_preset.preset_id == "qwen-35b-extended"
    assert resolved.effective_preset.input_token_limit == 32_768
    assert response.text == "Готово"
    assert requests[0][:2] == ("GET", "/api/v1/models")
    assert requests[1][2]["chat_template_kwargs"] == {"enable_thinking": False}
    final_body = requests[-1][2]
    assert final_body["model"] == MODEL_ID
    assert final_body["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.asyncio
@pytest.mark.parametrize('configured', [None, -1, 32768])
async def test_resolved_lemonade_window_limits_preset_instead_of_catalog_maximum(tmp_path, configured):
    """Actual incident: IQ3 catalogue 262144, provider resolved/slot 4096."""
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path == '/api/v1/models':
            return httpx.Response(200, json={'data': [dict(id=MODEL_ID, recipe='llamacpp',
                max_context_window=262144, recipe_options={'ctx_size': configured})]})
        if request.url.path == f'/api/v1/models/{MODEL_ID}/options':
            return httpx.Response(200, json=dict(model_name=MODEL_ID, resolved_ctx_size=4096,
                                               effective={'ctx_size': configured}))
        if request.url.path == '/api/v1/chat/completions':
            return httpx.Response(200, json={'choices':[{'message':{'content':'ok'}}]})
        return httpx.Response(404)
    registry = ModelConnectionRegistry(tmp_path / 'meta.db')
    revision = registry.create_connection(display_name='Lemonade',
        base_url='http://127.0.0.1:13305/api/v1', model_id=MODEL_ID,
        locality=ConnectionLocality.LOOPBACK, requested_context_tokens=32768,
        secret_ref=None, extension_type='lemonade', actor='test')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await CapabilityProbe(client=client, resolver=lambda *_: ('127.0.0.1',),
            peer_verifier=lambda *_: None).probe_and_store(revision,
                requested={CapabilityName.CHAT_COMPLETIONS}, registry=registry, actor='test')
    registry.bind_role(ConnectionRole.ANSWER,revision.revision_id,expected_binding_revision=None,actor='test')
    resolved = ModelConnectionResolver(registry=registry,
        secret_store=EnvironmentSecretStore(tmp_path / '.env',environ={}),
        address_resolver=lambda *_: ('127.0.0.1',)).resolve(ConnectionRole.ANSWER)
    assert snapshot.transport_options['observed_context_tokens'] == '4096'
    assert snapshot.transport_options['observed_context_source'] == 'lemonade_model_options.resolved_ctx_size'
    assert resolved.effective_preset.input_token_limit == 4096
    assert resolved.effective_preset.preset_id != 'qwen-35b-extended'
    assert calls.count(f'/api/v1/models/{MODEL_ID}/options') == 1


@pytest.mark.parametrize('options', [{}, {'ctx_size':None}, {'ctx_size':-1}, {'ctx_size':0}])
def test_catalog_limit_is_not_observed_backend_capacity(options):
    from proxy.services.model_capability_service import _lemonade_model_transport_options
    transport = _lemonade_model_transport_options({'data':[dict(id=MODEL_ID,
        recipe='llamacpp', max_context_window=262144, recipe_options=options)]},model_id=MODEL_ID)
    assert transport['observed_backend'] == 'llama_cpp'
    assert 'observed_context_tokens' not in transport
