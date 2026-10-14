"""Explicit Chat Completions controls must describe the actual generic wire."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import httpx
import pytest

from proxy.services.model_capability_service import CapabilityProbe
from proxy.services.model_connection_contracts import (
    CapabilityName, CapabilityObservation, CapabilitySnapshot, CapabilityState, ChatOptions,
    ConnectionLocality, ModelConnectionRevision,
)
from proxy.services.model_connection_resolver_service import ResolvedModelConnection
from proxy.services.model_connection_security_service import ValidatedEndpoint
from proxy.services.model_execution_preset_service import (
    apply_output_budget_policy, apply_reasoning_policy, model_rag_answer_execution_preset,
    model_rag_query_execution_preset,
)
from proxy.services.llm_transport_profile_service import resolve_connection_execution_profile
from proxy.services.context_governor_service import ContextGovernor
from proxy.services.model_secret_service import EnvironmentSecretStore
from proxy.services.openai_compatible_transport_service import (
    InferenceRequest, ModelTransportError, OpenAICompatibleTransport,
)


NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)


def _revision(options=None, *, local=False, extension=None):
    values = dict(
        connection_id="conn:generic", revision_id="conn:generic:r1", revision_no=1,
        display_name="Arbitrary model", protocol="openai_compatible",
        base_url="http://127.0.0.1:1919/v1" if local else "https://example.test/v1",
        model_id="arbitrary-model", locality=ConnectionLocality.LOOPBACK if local else ConnectionLocality.REMOTE,
        requested_context_tokens=65536, secret_ref=None, extension_type=extension,
        enabled=True, created_at=NOW.isoformat(), created_by="fixture",
    )
    if options is not None:
        values["chat_options"] = options
    return ModelConnectionRevision(**values)


def _resolved(revision, snapshot=None):
    if snapshot is None:
        snapshot = CapabilitySnapshot(
            snapshot_id="cap:generic", connection_revision_id=revision.revision_id,
            observations=tuple(CapabilityObservation(
                capability, CapabilityState.SUPPORTED, "probe", NOW, "http_200",
            ) for capability in (CapabilityName.CHAT_COMPLETIONS, CapabilityName.TOOLS)),
            observed_at=NOW, expires_at=NOW + timedelta(hours=1),
            transport_options={"max_output_field": "max_completion_tokens"},
        )
    local = revision.locality is ConnectionLocality.LOOPBACK
    endpoint = ValidatedEndpoint(
        canonical_base_url=revision.base_url, locality=revision.locality,
        host="127.0.0.1" if local else "example.test", port=1919 if local else 443,
        allowed_addresses=frozenset(),
    )
    values = dict(
        connection_id=revision.connection_id, revision_id=revision.revision_id,
        display_name=revision.display_name, base_url=revision.base_url, model_id=revision.model_id,
        locality=revision.locality, requested_context_tokens=revision.requested_context_tokens,
        secret_ref=None, extension_type=revision.extension_type, capability_snapshot=snapshot,
        endpoint=endpoint, effective_preset=resolve_connection_execution_profile(
            model_id=revision.model_id, requested_context_tokens=65536,
            observed_context_tokens=None, observed_source="unavailable",
        ),
    )
    if hasattr(revision, "chat_options"):
        values["chat_options"] = revision.chat_options
    return ResolvedModelConnection(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,effort", [("unconfigured", None), ("effort", "high"), ("enabled", None), ("enable_thinking", None)])
@pytest.mark.parametrize("enabled", [False, True])
async def test_configured_probe_and_inference_share_parameter_renderer(tmp_path, mode, effort, enabled):
    options = dict(max_output_field="max_completion_tokens", reasoning_mode=mode,
                   temperature_mode="omit", requested_output_tokens=1024)
    if effort is not None:
        options["enabled_effort"] = effort
    revision = _revision(options)
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "literal answer"}, "finish_reason": "stop"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await CapabilityProbe(
            client=client, resolver=lambda *_args: ("93.184.216.34",),
            peer_verifier=lambda *_args: None, clock=lambda: NOW,
        ).probe(revision, requested={CapabilityName.CHAT_COMPLETIONS, CapabilityName.TOOLS})
        transport = OpenAICompatibleTransport(
            client=client, secret_store=EnvironmentSecretStore(tmp_path / "fixture.env", environ={}),
            peer_verifier=lambda *_args: None,
        )
        messages = (
            {"role": "system", "content": "literal system"},
            {"role": "user", "content": "literal attachment"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "literal-id", "type": "function", "function": {"name": "read_source", "arguments": '{"ref":"source:1"}'}}]},
            {"role": "tool", "tool_call_id": "literal-id", "name": "read_source", "content": "literal receipt"},
        )
        result = await transport.complete(_resolved(revision, snapshot), InferenceRequest(
            messages=messages, max_output_tokens=512, temperature=0.7,
            reasoning_enabled=enabled, tools=({"type": "function", "function": {"name": "read_source"}},),
        ))
    assert result.text == "literal answer"
    assert snapshot.transport_options["max_output_field"] == "max_completion_tokens"
    for body in bodies:
        assert "max_tokens" not in body and "temperature" not in body
        assert "chat_template_kwargs" not in body
        assert "tool_choice" not in body
        if mode == "unconfigured":
            assert "reasoning" not in body and "reasoning_effort" not in body
        elif mode == "enabled":
            assert body["reasoning"] == {"enabled": enabled if body is bodies[-1] else False}
            assert "reasoning_effort" not in body
        elif mode == "enable_thinking":
            assert body["enable_thinking"] is (enabled if body is bodies[-1] else False)
            assert "reasoning" not in body and "reasoning_effort" not in body
        else:
            assert body["reasoning_effort"] == ("high" if body is bodies[-1] and enabled else "none")
            assert "reasoning" not in body
    assert bodies[-1]["messages"] == list(messages)
    assert bodies[-1]["max_completion_tokens"] == 512
    assert all(body["max_completion_tokens"] == 1 for body in bodies[:-1])


@pytest.mark.asyncio
async def test_legacy_snapshot_output_field_and_local_native_wire_are_preserved(tmp_path):
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = OpenAICompatibleTransport(client=client,
            secret_store=EnvironmentSecretStore(tmp_path / "fixture.env", environ={}),
            peer_verifier=lambda *_args: None)
        request = InferenceRequest(messages=({"role": "user", "content": "literal"},), max_output_tokens=64, temperature=0.7)
        await transport.complete(_resolved(_revision()), request)
        await transport.complete(_resolved(_revision(local=True, extension="freetoken")), request)
    assert bodies[0]["max_completion_tokens"] == 64 and bodies[0]["temperature"] == 0.7
    assert "reasoning" not in bodies[0] and "reasoning_effort" not in bodies[0]
    assert bodies[1]["chat_template_kwargs"] == {"enable_thinking": False, "thinking_mode": "disabled"}
    assert "reasoning" not in bodies[1]


@pytest.mark.asyncio
async def test_configured_http_400_is_visible_without_parameter_retry(tmp_path):
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(400, json={"error": "declared parameter unsupported"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = OpenAICompatibleTransport(client=client,
            secret_store=EnvironmentSecretStore(tmp_path / "fixture.env", environ={}),
            peer_verifier=lambda *_args: None)
        with pytest.raises(ModelTransportError, match="UPSTREAM_HTTP_ERROR: 400"):
            await transport.complete(_resolved(_revision({"reasoning_mode": "enabled"})),
                InferenceRequest(messages=({"role": "user", "content": "literal"},), max_output_tokens=8))
    assert len(calls) == 1 and calls[0]["reasoning"] == {"enabled": False}


@pytest.mark.asyncio
async def test_operator_output_ceiling_applies_to_actual_wire_without_becoming_observed(tmp_path):
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    revision = _revision({"requested_output_tokens": 16})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await CapabilityProbe(client=client, resolver=lambda *_args: ("93.184.216.34",),
            peer_verifier=lambda *_args: None, clock=lambda: NOW).probe(revision, requested={CapabilityName.CHAT_COMPLETIONS})
        transport = OpenAICompatibleTransport(client=client,
            secret_store=EnvironmentSecretStore(tmp_path / "fixture.env", environ={}),
            peer_verifier=lambda *_args: None)
        await transport.complete(_resolved(revision, snapshot), InferenceRequest(
            messages=({"role": "user", "content": "literal"},), max_output_tokens=512, temperature=0.7))
    assert bodies[0]["max_tokens"] == 1 and bodies[1]["max_tokens"] == 16
    assert bodies[1]["temperature"] == 0.7
    assert "observed_context_tokens" not in snapshot.transport_options
    assert "observed_output_tokens" not in snapshot.transport_options


@pytest.mark.asyncio
async def test_rejected_configured_probe_is_unknown_and_not_retried():
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(400, json={"error": "unsupported declared control"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await CapabilityProbe(client=client, resolver=lambda *_args: ("93.184.216.34",),
            peer_verifier=lambda *_args: None, clock=lambda: NOW).probe(
                _revision({"reasoning_mode": "enabled"}), requested={CapabilityName.CHAT_COMPLETIONS})
    assert len(bodies) == 1 and bodies[0]["reasoning"] == {"enabled": False}
    observation = snapshot.observation(CapabilityName.CHAT_COMPLETIONS)
    assert observation.state is CapabilityState.UNKNOWN and observation.detail == "http_400"


def _declared_preset(*, output=20000, observed=None, remote=True, restrictions=None):
    return resolve_connection_execution_profile(
        model_id="arbitrary-model", requested_context_tokens=65536,
        observed_context_tokens=observed, observed_source="probe" if observed else "unavailable",
        chat_options={"requested_output_tokens": output}, remote=remote, restrictions=restrictions,
    )


def test_declared_remote_capacity_reserves_once_without_claiming_observation():
    base = _declared_preset()
    profile = apply_output_budget_policy(base, {"query_output_tokens": 8192, "answer_output_tokens": 16384})
    answer = model_rag_answer_execution_preset(profile, model_rag=True)
    assert base.output_capacity_observed is False
    assert profile.generation_reserve_tokens == 8192 and answer.generation_reserve_tokens == 16384
    packet = ContextGovernor(answer).pack(())
    assert packet.input_budget_tokens == 65536 - 16384 - answer.safety_reserve_tokens
    diagnostics = answer.diagnostics()
    assert diagnostics["connection_output_tokens"]["requested"] == 20000
    assert diagnostics["connection_output_tokens"]["observed"] is False
    assert diagnostics["reasoning"]["effective"] is None
    assert diagnostics["query_reasoning"]["effective"] is None
    assert "unconfigured" in diagnostics["reasoning"]["source"]
    assert apply_output_budget_policy(profile, {"query_output_tokens": 8192, "answer_output_tokens": 16384}) == profile


@pytest.mark.parametrize("remote,observed,restriction,expected_window", [(False, 2048, None, 2048), (False, 65536, 12000, 12000), (True, None, 12000, 12000)])
def test_declared_capacity_does_not_override_physical_or_workflow_limit(remote, observed, restriction, expected_window):
    preset = _declared_preset(remote=remote, observed=observed,
        restrictions={"input_tokens": restriction} if restriction else None)
    profile = apply_output_budget_policy(preset, {"query_output_tokens": 24000, "answer_output_tokens": 24000})
    answer = model_rag_answer_execution_preset(profile, model_rag=True)
    assert answer.input_token_limit == expected_window
    assert answer.generation_reserve_tokens <= expected_window - answer.safety_reserve_tokens - 1024


def test_output_only_or_auto_budget_is_a_ceiling_not_observed_capacity():
    small = _declared_preset(output=512)
    assert model_rag_answer_execution_preset(small, model_rag=True).generation_reserve_tokens == 512
    unproven = resolve_connection_execution_profile(
        model_id="arbitrary", requested_context_tokens=None, observed_context_tokens=None,
        observed_source="unavailable", remote=True, chat_options={"requested_output_tokens": 24000},
    )
    requested = apply_output_budget_policy(unproven, {"query_output_tokens": 16000})
    assert requested.generation_reserve_tokens == 1200
    assert requested.output_capacity_observed is False


@pytest.mark.asyncio
async def test_native_chat_keeps_think_and_ids_with_declared_temperature_omission(tmp_path):
    bodies = []
    def handler(request):
        bodies.append((request.url.path, json.loads(request.content)))
        if request.url.path == "/api/chat":
            return httpx.Response(200, content=b'{"message":{"content":"ok"},"done":true}\n')
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    revision = _revision({"temperature_mode": "omit", "requested_output_tokens": 16}, local=True, extension="ollama")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await CapabilityProbe(client=client, resolver=lambda *_args: ("127.0.0.1",),
            peer_verifier=lambda *_args: None, clock=lambda: NOW).probe(revision, requested={CapabilityName.CHAT_COMPLETIONS})
        assert snapshot.transport_options["chat_protocol"] == "native_chat_v1"
        transport = OpenAICompatibleTransport(client=client,
            secret_store=EnvironmentSecretStore(tmp_path / "fixture.env", environ={}),
            peer_verifier=lambda *_args: None)
        result = await transport.complete(_resolved(revision, snapshot), InferenceRequest(
            messages=({"role": "user", "content": "literal native question"},), max_output_tokens=512,
            temperature=0.7, reasoning_enabled=True))
    assert result.text == "ok"
    native = [body for path, body in bodies if path == "/api/chat"]
    assert len(native) == 2 and native[0]["think"] is False and native[1]["think"] is True
    assert native[1]["options"]["num_predict"] == 16
    assert "temperature" not in native[0]["options"] and "temperature" not in native[1]["options"]
    assert native[1]["messages"] == [{"role": "user", "content": "literal native question"}]


@pytest.mark.parametrize("mode,effort", [("effort", "high"), ("enabled", None), ("enable_thinking", None)])
def test_configured_remote_boolean_is_not_suppressed_as_unsupported(mode, effort):
    options = {"reasoning_mode": mode}
    if effort:
        options["enabled_effort"] = effort
    preset = resolve_connection_execution_profile(
        model_id="arbitrary", requested_context_tokens=65536, observed_context_tokens=None,
        observed_source="unavailable", remote=True, chat_options=options,
    )
    profile = apply_reasoning_policy(preset, {"reasoning_enabled": True, "query_reasoning_enabled": False})
    assert profile.reasoning_enabled is True
    assert model_rag_query_execution_preset(profile).reasoning_enabled is False
    assert profile.diagnostics()["reasoning"]["effective"] is True
    assert profile.diagnostics()["query_reasoning"]["effective"] is False


@pytest.mark.parametrize("values", [
    {}, {"top_p": None, "top_k": None, "presence_penalty": None},
    {"top_p": 0.8, "top_k": 20, "presence_penalty": 1.5},
    {"top_p": 1, "top_k": -1, "presence_penalty": 0},
    {"top_p": 0.0001, "top_k": 1, "presence_penalty": -2},
    {"presence_penalty": 2},
])
def test_optional_sampling_values_are_sparse_and_round_trip(values):
    options = ChatOptions.from_value(values)
    expected = {key: value for key, value in values.items() if value is not None}
    assert options.to_dict() == expected
    assert ChatOptions.from_value(options.to_dict()) == options
    parameters = options.parameters(max_output_tokens=128, temperature=0.7, reasoning_enabled=False)
    assert parameters == {"max_tokens": 128, "temperature": 0.7, **expected}
    assert ChatOptions.from_value({}).to_dict() == {}  # Legacy JSON needs no rewrite.


@pytest.mark.parametrize("field,code,values", [
    ("top_p", "INVALID_TOP_P", [True, False, "0.8", 0, -0.1, 1.01, float("nan"), float("inf"), -float("inf"), [], {}]),
    ("top_k", "INVALID_TOP_K", [True, False, "20", 20.0, 0, -2, float("nan"), float("inf"), [], {}]),
    ("presence_penalty", "INVALID_PRESENCE_PENALTY", [True, False, "0", -2.01, 2.01, float("nan"), float("inf"), -float("inf"), [], {}]),
])
def test_sampling_rejects_invalid_values_without_coercion(field, code, values):
    for value in values:
        with pytest.raises(ValueError, match=code):
            ChatOptions.from_value({field: value})


def test_sampling_connection_revisions_keep_legacy_default_and_explicit_zero(tmp_path):
    from proxy.services.model_connection_registry_service import ModelConnectionRegistry

    registry = ModelConnectionRegistry(tmp_path / "registry.db")
    original = registry.create_connection(
        display_name="Arbitrary", base_url="http://127.0.0.1:1919/v1", model_id="arbitrary-model",
        locality=ConnectionLocality.LOOPBACK, requested_context_tokens=8192,
        secret_ref=None, extension_type=None, actor="fixture",
    )
    declared = {"top_p": 0.8, "top_k": -1, "presence_penalty": 0}
    revised = registry.revise_connection(original.connection_id,
        expected_revision_id=original.revision_id, actor="fixture", chat_options=declared)
    reopened = ModelConnectionRegistry(tmp_path / "registry.db")
    assert reopened.get_revision(original.revision_id).chat_options.to_dict() == {}
    assert reopened.get_revision(revised.revision_id).chat_options.to_dict() == declared
    assert reopened.latest_capability_snapshot(revised.revision_id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("extension", [None, "freetoken", "ollama"])
@pytest.mark.parametrize("declared", [{}, {"top_p": 0.8, "top_k": -1, "presence_penalty": 0}])
async def test_optional_sampling_reaches_probe_and_repeated_actual_http_body(tmp_path, extension, declared):
    bodies = []
    revision = _revision(declared, local=extension is not None, extension=extension)

    def handler(request):
        body = json.loads(request.content)
        bodies.append((request.url.path, body))
        if request.url.path == "/api/chat":
            return httpx.Response(200, content=b'{"message":{"content":"literal"},"done":true}\n')
        if request.url.path == "/api/show":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"choices": [{"message": {"content": "literal"}, "finish_reason": "stop"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await CapabilityProbe(client=client,
            resolver=lambda *_args: ("127.0.0.1" if extension else "93.184.216.34",),
            peer_verifier=lambda *_args: None, clock=lambda: NOW).probe(
                revision, requested={CapabilityName.CHAT_COMPLETIONS})
        transport = OpenAICompatibleTransport(client=client,
            secret_store=EnvironmentSecretStore(tmp_path / "fixture.env", environ={}),
            peer_verifier=lambda *_args: None)
        request = InferenceRequest(messages=({"role": "user", "content": "literal question"},),
            max_output_tokens=128, temperature=0.7, reasoning_enabled=False)
        for _ in range(2):
            assert (await transport.complete(_resolved(revision, snapshot), request)).text == "literal"
    sampling_names = {"top_p", "top_k", "presence_penalty"}
    generation_bodies = [(path, body) for path, body in bodies if path != "/api/show"]
    for path, body in generation_bodies:
        options = body["options"] if path == "/api/chat" else body
        assert {name: options[name] for name in sampling_names if name in options} == declared
        if path == "/api/chat":
            assert not sampling_names.intersection(body)
            assert body["think"] is False
    assert generation_bodies[-1] == generation_bodies[-2]
    sent = generation_bodies[-1][1]
    assert sent["messages"] == list(request.messages)
    final_options = sent["options"] if extension == "ollama" else sent
    assert final_options["temperature"] == 0.7
    assert final_options["num_predict" if extension == "ollama" else "max_tokens"] == 128
    assert not sampling_names.intersection(snapshot.transport_options)
    assert revision.chat_options.to_dict() == declared


@pytest.mark.asyncio
async def test_unsupported_declared_sampling_is_not_retried_without_it(tmp_path):
    bodies = []
    declared = {"top_p": 0.8, "top_k": 20, "presence_penalty": 0}

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(400, json={"error": "unsupported sampling control"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = OpenAICompatibleTransport(client=client,
            secret_store=EnvironmentSecretStore(tmp_path / "fixture.env", environ={}),
            peer_verifier=lambda *_args: None)
        with pytest.raises(ModelTransportError, match="UPSTREAM_HTTP_ERROR: 400"):
            await transport.complete(_resolved(_revision(declared)), InferenceRequest(
                messages=({"role": "user", "content": "literal"},), max_output_tokens=8))
    assert len(bodies) == 1
    assert {key: bodies[0][key] for key in declared} == declared
