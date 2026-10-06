"""Optional profile thinking travels through existing calls; only final text exits."""

import json

import httpx
import pytest

from proxy.services.llm_transport_profile_service import FinalTextFilter, final_assistant_text
from proxy.services.model_execution_preset_service import BackendCapacity, apply_reasoning_policy, resolve_execution_preset
from proxy.services.openai_compatible_transport_service import InferenceRequest
from proxy.services.runtime_config_registry_service import runtime_factor_rows
from tests.test_openai_compatible_transport_service import _resolved, _transport


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.asyncio
async def test_freetoken_body_preserves_explicit_bool_and_final_only_content(tmp_path, enabled):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"reasoning_content": "private table | fake | 100 |",
                                        "content": "<think>private draft rows</think>\nFinal rows"},
                         "finish_reason": "stop"}],
            "usage": {"completion_tokens": 31},
        })

    transport, client = _transport(tmp_path, handler)
    try:
        result = await transport.complete(_resolved(extension_type="freetoken"), InferenceRequest(
            messages=({"role": "user", "content": "literal task"},), max_output_tokens=800,
            temperature=0.1, reasoning_enabled=enabled))
    finally:
        await client.aclose()
    assert bodies[0]["chat_template_kwargs"] == {"enable_thinking": enabled, "thinking_mode": "enabled" if enabled else "disabled"}
    assert bodies[0]["temperature"] == 0.1 and bodies[0]["max_tokens"] == 800
    assert bodies[0]["messages"] == [{"role": "user", "content": "literal task"}]
    assert "top_p" not in bodies[0] and "top_k" not in bodies[0]
    assert result.text == "Final rows" and result.usage["completion_tokens"] == 31


@pytest.mark.asyncio
async def test_default_request_keeps_thinking_disabled(tmp_path):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Answer"}}]})

    transport, client = _transport(tmp_path, handler)
    try:
        request = InferenceRequest(messages=({"role": "user", "content": "task"},), max_output_tokens=32)
        await transport.complete(_resolved(extension_type="freetoken"), request)
    finally:
        await client.aclose()
    assert request.reasoning_enabled is False
    assert bodies[0]["chat_template_kwargs"]["enable_thinking"] is False


@pytest.mark.parametrize("value", [1, "true", None, {}])
def test_request_and_profile_policy_reject_coerced_reasoning(value):
    with pytest.raises(ValueError, match="boolean"):
        InferenceRequest(messages=(), max_output_tokens=32, reasoning_enabled=value)
    preset = resolve_execution_preset(BackendCapacity("freetoken", "Qwen3.6-35B", 35000, True, "test"))
    with pytest.raises(ValueError, match="boolean"):
        apply_reasoning_policy(preset, {"reasoning_enabled": value})


def test_reasoning_policy_does_not_change_capacity_or_route_and_explains_effective_value():
    base = resolve_execution_preset(BackendCapacity("freetoken", "Qwen3.6-35B", 35000, True, "test"))
    policy = {"reasoning_enabled": True, "temperature": 0.1}
    enabled = apply_reasoning_policy(base, policy)
    assert enabled.input_token_limit == base.input_token_limit == 35000
    assert enabled.generation_reserve_tokens == base.generation_reserve_tokens
    assert enabled.max_tools == base.max_tools and enabled.source_chain == base.source_chain
    assert policy == {"reasoning_enabled": True, "temperature": 0.1}
    factor = next(item for item in runtime_factor_rows(enabled.diagnostics()) if item["id"] == "reasoning")
    assert factor["requested"] is factor["effective"] is True
    assert factor["source"] == "profile_model_policy" and factor["operator_action"] == "profile_clone"
    assert factor["restart_required"] is False
    restricted = apply_reasoning_policy(base, policy, restrictions={"reasoning_enabled": False})
    assert restricted.diagnostics()["reasoning"]["requested"] is True
    assert restricted.reasoning_enabled is False


@pytest.mark.parametrize("thinking,reserve,configured,expected", [
    (False, 4096, "", 1600), (True, 4096, "", 4096),
    (True, 1200, "", 1200), (False, 1200, "", 1200),
    (True, 4096, "1600", 1600), (True, 1200, "8000", 1200),
    (False, 4096, "512", 512),
])
def test_query_output_never_exceeds_actual_governor_reserve(thinking, reserve, configured, expected):
    from proxy.services.model_execution_preset_service import query_generation_budget
    base = resolve_execution_preset(BackendCapacity("freetoken", "Qwen3.6-35B", 35000, True, "test"))
    selected = apply_reasoning_policy(base, {"reasoning_enabled": thinking})
    before = selected.diagnostics()
    budget = query_generation_budget(selected, reserved_tokens=reserve, configured_limit=configured)
    assert budget["effective"] == expected and budget["reserved_tokens"] == reserve
    assert budget["requested"] == (int(configured) if configured else None)
    assert selected.diagnostics() == before  # no window/provider/reserve mutation


@pytest.mark.parametrize("configured", ["0", "-1", "true", "2.5", "secret=value"])
def test_invalid_explicit_query_limit_is_visible_and_never_silently_defaulted(configured):
    from proxy.services.model_execution_preset_service import query_generation_budget
    base = resolve_execution_preset(BackendCapacity("freetoken", "Qwen3.6-35B", 35000, True, "test"))
    with pytest.raises(ValueError, match="positive integer"):
        query_generation_budget(base, reserved_tokens=4096, configured_limit=configured)


@pytest.mark.parametrize("fragments, expected", [
    (["<thi", "nk>private", "</thi", "nk>Final"], "Final"),
    (["Intro", "<THINK>literal", "</THINK>", "\nFinal"], "Intro<THINK>literal</THINK>\nFinal"),
    (["<think>never closes | fake | 100 |"], ""),
    (["<think>private</think><thi"], "<thi"),
    ([" \n<thi", "nk>private</think>Final <th"], "Final <th"),
    (["```xml\n<think>literal</think>\n```"], "```xml\n<think>literal</think>\n```"),
    (["Plain < 3 and > 2"], "Plain < 3 and > 2"),
])
def test_inline_filter_suppresses_split_and_unfinished_thinking(fragments, expected):
    filter_ = FinalTextFilter()
    actual = "".join(filter_.feed(fragment) for fragment in fragments) + filter_.finish()
    assert actual == expected


@pytest.mark.asyncio
async def test_stream_separates_reasoning_channel_and_split_inline_tags(tmp_path):
    deltas = [{"reasoning_content": "private"}, {"content": "<thi"}, {"content": "nk>draft"},
              {"reasoning": "more private"}, {"content": "</thi"}, {"content": "nk>Final"}]
    payload = "".join("data: " + json.dumps({"choices": [{"delta": delta}]}) + "\n\n" for delta in deltas)
    payload += 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    transport, client = _transport(tmp_path, lambda request: httpx.Response(200, text=payload))
    try:
        events = [item async for item in transport.stream(_resolved(extension_type="freetoken"), InferenceRequest(
            messages=(), max_output_tokens=100, reasoning_enabled=True))]
    finally:
        await client.aclose()
    assert "".join(item.text for item in events if item.kind == "text_delta") == "Final"
    assert events[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_reasoning_only_length_is_empty_final_with_real_usage_not_reasoning_fallback(tmp_path):
    transport, client = _transport(tmp_path, lambda request: httpx.Response(200, json={
        "choices": [{"message": {"reasoning_content": "| source_row | quantity |\n| S!R1 | 999 |"},
                     "finish_reason": "length"}], "usage": {"completion_tokens": 800}}))
    try:
        result = await transport.complete(_resolved(extension_type="freetoken"), InferenceRequest(
            messages=(), max_output_tokens=800, reasoning_enabled=True))
    finally:
        await client.aclose()
    assert result.text == "" and result.tool_calls == ()
    assert result.finish_reason == "length" and result.usage["completion_tokens"] == 800
    assert final_assistant_text({"reasoning": "private"}) == ""


@pytest.mark.parametrize("content, expected", [
    ("```xml\n<think>literal</think>\n```", "```xml\n<think>literal</think>\n```"),
    ("Final literal <think>XML</think> and <th", "Final literal <think>XML</think> and <th"),
    ("<think>private</think><think>literal</think>", "<think>literal</think>"),
])
@pytest.mark.asyncio
async def test_complete_preserves_final_xml_and_code_literals(tmp_path, content, expected):
    transport, client = _transport(tmp_path, lambda request: httpx.Response(200, json={
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}]}))
    try:
        result = await transport.complete(_resolved(extension_type="freetoken"), InferenceRequest(
            messages=(), max_output_tokens=100, reasoning_enabled=True))
    finally:
        await client.aclose()
    assert result.text == expected


@pytest.mark.parametrize("enabled", [False, True])
def test_native_body_uses_same_typed_bool_without_provider_selection(enabled):
    from proxy.services.openai_compatible_transport_service import OpenAICompatibleTransport
    request = InferenceRequest(messages=(), max_output_tokens=64, reasoning_enabled=enabled)
    connection = _resolved(chat_protocol="native_chat_v1")
    body = OpenAICompatibleTransport._native_chat_body(connection, request)
    assert body["think"] is enabled and body["model"] == connection.model_id
    assert body["options"]["num_ctx"] == connection.effective_preset.input_token_limit


def test_profile_revision_persists_explicit_bool_without_mutating_old_policy(tmp_path):
    from proxy.services.chat_profile_service import publish_profile_revision, registry_snapshot
    path = tmp_path / "profile.db"
    before = registry_snapshot(db_path=path)
    base = next(item for item in before["profiles"] if item["mode"] == "estimator")["active"]
    old_policy = dict(base["model_policy"])
    arguments = dict(mode="estimator", name="Thinking experiment", prompt_revision_id=base["prompt_revision_id"],
                     skill_revision_id=base["skill_revision_id"], tools=base["tools"], rag_policy=base["rag_policy"],
                     db_path=path)
    revision = publish_profile_revision(**arguments, model_policy={**old_policy, "reasoning_enabled": True})
    assert revision["model_policy"] == {**old_policy, "reasoning_enabled": True}
    after = registry_snapshot(db_path=path)
    active = next(item for item in after["profiles"] if item["mode"] == "estimator")["active"]
    assert active["revision_id"] == base["revision_id"] and active["model_policy"] == old_policy
    with pytest.raises(ValueError, match="boolean"):
        publish_profile_revision(**arguments, model_policy={**old_policy, "reasoning_enabled": "true"})


@pytest.mark.asyncio
async def test_unknown_compatible_transport_reports_requested_true_effective_false_without_guessing_wire_fields(tmp_path):
    preset = resolve_execution_preset(BackendCapacity("openai-compatible", "Qwen3.6-35B", 35000, True, "probe"),
                                      operator={"reasoning_enabled": True})
    assert preset.diagnostics()["reasoning"] == {
        "requested": True, "effective": False, "source": "unsupported_by_transport", "restart_required": False}
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Final"}}]})

    transport, client = _transport(tmp_path, handler)
    try:
        await transport.complete(_resolved(), InferenceRequest(messages=(), max_output_tokens=64,
                                                               reasoning_enabled=preset.reasoning_enabled))
    finally:
        await client.aclose()
    assert bodies == [{"model": "model-1", "messages": [], "max_tokens": 64}]


@pytest.mark.parametrize("extension_type, protocol, expected", [
    ("freetoken", None, True), (None, "native_chat_v1", True), (None, None, False),
])
def test_bound_connection_transports_supply_only_known_reasoning_availability(tmp_path, extension_type, protocol, expected):
    from dataclasses import replace
    from proxy.services.model_connection_registry_service import ModelConnectionRegistry
    from tests.test_model_connection_resolver_service import _resolver, _snapshot
    from proxy.services.model_connection_contracts import CapabilityName, ConnectionLocality
    registry = ModelConnectionRegistry(tmp_path / "connections.db")
    revision = registry.create_connection(display_name="Bound model", base_url="http://127.0.0.1:1919/v1",
                                          model_id="Qwen3.6-35B", locality=ConnectionLocality.LOOPBACK,
                                          requested_context_tokens=35000, secret_ref=None,
                                          extension_type=extension_type, actor="test")
    snapshot = _snapshot(revision.revision_id, CapabilityName.CHAT_COMPLETIONS, observed_context_tokens=35000)
    if protocol:
        snapshot = replace(snapshot, transport_options={**snapshot.transport_options, "chat_protocol": protocol})
    registry.save_capability_snapshot(snapshot, actor="test")
    connection = _resolver(registry, tmp_path).resolve_revision(revision.revision_id)
    selected = apply_reasoning_policy(connection.effective_preset, {"reasoning_enabled": True})
    assert selected.reasoning_supported is expected and selected.reasoning_enabled is expected
    assert selected.reasoning_requested is True and selected.input_token_limit == 35000
