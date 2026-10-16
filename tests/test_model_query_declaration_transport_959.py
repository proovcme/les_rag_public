"""Same query envelope through native arguments; no professional rewrite."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services import model_query_declaration_transport_service as transport
from proxy.services.model_connection_contracts import CapabilityName, CapabilityObservation, CapabilitySnapshot, CapabilityState
from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from tests import test_model_rag_sheet_evidence_reads as fixture

NOW = datetime.now(timezone.utc)
QUERIES = ['[S!R2] Cable A literal [variant Ω] {2,5}', '"S!R3 Cable B" literal \\ path']


def connection(state=CapabilityState.SUPPORTED, source='probe', stale=False):
    observed = NOW - timedelta(days=2) if stale else NOW
    expiry = NOW - timedelta(days=1) if stale else NOW + timedelta(days=1)
    return SimpleNamespace(revision_id='conn:fixture:r1', capability_snapshot=CapabilitySnapshot(
        snapshot_id='cap:fixture-full', connection_revision_id='conn:fixture:r1',
        observations=(CapabilityObservation(CapabilityName.TOOLS, state, source, observed),
                      CapabilityObservation(CapabilityName.STRUCTURED_OUTPUT, CapabilityState.UNKNOWN, 'unavailable', observed)),
        observed_at=observed, expires_at=expiry))


def call(arguments, name=transport.QUERY_DECLARATION_FUNCTION, identity='call:query'):
    return {'id': identity, 'type': 'function', 'function': {'name': name, 'arguments': arguments}}


def adapt(arguments, *, visible='', finish='tool_calls'):
    response = InferenceResponse(text=visible, tool_calls=(call(arguments),), finish_reason=finish, usage={})
    carrier, trace = transport.query_declaration_response_text('original native wrapper', response=response, advertised=True)
    return carrier, trace, service.read_model_query_response(carrier, finish_reason=finish)


@pytest.mark.parametrize('state,source,stale,expected', [
    (CapabilityState.SUPPORTED, 'probe', False, True),
    (CapabilityState.SUPPORTED, 'operator_declaration', False, True),
    (CapabilityState.UNKNOWN, 'probe', False, False),
    (CapabilityState.UNSUPPORTED, 'probe', False, False),
    (CapabilityState.SUPPORTED, 'template_default', False, False),
    (CapabilityState.SUPPORTED, 'unavailable', False, False),
    (CapabilityState.SUPPORTED, 'probe', True, False),
])
def test_native_admission_reuses_existing_tools_requirement_without_structured_output(state, source, stale, expected):
    conn = connection(state, source, stale)
    before = deepcopy(conn.capability_snapshot.to_dict()) if hasattr(conn.capability_snapshot, 'to_dict') else conn.capability_snapshot
    tools, decision = transport.resolve_query_declaration_transport(conn, now=NOW)
    assert bool(tools) is expected
    assert decision['capability_state'] == state.value
    assert decision['capability_evidence_source'] == source
    assert len(tools) == int(expected)
    if tools:
        schema = tools[0]['function']['parameters']
        assert schema['required'] == ['queries']
        assert schema['properties']['artifact_kind']['enum'] == ['vor', 'lsr']
    assert (conn.capability_snapshot.to_dict() if hasattr(conn.capability_snapshot, 'to_dict') else conn.capability_snapshot) == before


@pytest.mark.parametrize('kind', [None, 'vor', 'lsr'])
def test_native_literal_arguments_use_exact_current_parser_and_preserve_queries(kind):
    envelope = {'queries': QUERIES, 'commentary': 'Literal note with "quotes" and [brackets]'}
    if kind is not None:
        envelope['artifact_kind'] = kind
    raw = json.dumps(envelope, ensure_ascii=False, indent=2)
    carrier, observed, parsed = adapt(raw)
    assert carrier == raw
    assert parsed == service.read_model_query_response(raw, finish_reason='tool_calls')
    assert [query.text for query in parsed['queries']] == QUERIES
    assert observed['channel'] == 'native_function'
    assert 'raw' not in observed and 'arguments' not in observed


@pytest.mark.parametrize('kind,empty', [('vor', True), ('lsr', False)])
def test_empty_vor_and_lsr_keep_existing_meaning(kind, empty):
    _, _, parsed = adapt(json.dumps({'artifact_kind': kind, 'queries': []}))
    assert parsed['intentional_empty'] is empty


def test_native_object_arguments_preserve_values_and_own_metadata():
    envelope = {'artifact_kind': 'lsr', 'queries': QUERIES, 'commentary': 'literal'}
    before = deepcopy(envelope)
    carrier, observed, parsed = adapt(envelope)
    assert json.loads(carrier) == before and envelope == before
    assert [query.text for query in parsed['queries']] == QUERIES
    assert observed['arguments_representation'] == 'provider_object_lossless_values'


@pytest.mark.parametrize('arguments', ['not JSON', '{"queries":[', '{"queries":[],"artifact_kind":"vor","artifact_kind":"lsr"}', {'rows': []}])
def test_invalid_function_arguments_are_whole_technical_data_never_literal_queries(arguments):
    carrier, observed, parsed = adapt(arguments)
    assert observed['channel'] == 'native_invalid'
    assert observed['reason'] == 'native_arguments_not_query_envelope'
    assert parsed['queries'] == []
    saved = json.loads(carrier)
    assert saved['native_calls'][0]['function']['arguments'] == arguments


@pytest.mark.parametrize('multiple', [False, True])
def test_unknown_or_multiple_calls_are_not_selected_or_silently_dropped(multiple):
    one = call('{"artifact_kind":"vor","queries":[]}', name='unexpected' if not multiple else transport.QUERY_DECLARATION_FUNCTION)
    calls = (one, call('{"queries":["other"]}', identity='call:other')) if multiple else (one,)
    response = InferenceResponse(text='Visible commentary', tool_calls=calls, finish_reason='tool_calls', usage={}, reasoning_content='PRIVATE_THINKING_NOT_VISIBLE')
    carrier, observed = transport.query_declaration_response_text('wrapper', response=response, advertised=True)
    assert observed['native_call_count'] == len(calls)
    assert observed['channel'] == 'native_invalid'
    assert service.read_model_query_response(carrier)['queries'] == []
    assert json.loads(carrier)['native_calls'] == list(calls)
    assert 'PRIVATE_THINKING_NOT_VISIBLE' not in carrier


def test_visible_conflicting_metadata_is_not_discarded_beside_function():
    raw = '{"artifact_kind":"vor","queries":["literal"]}'
    carrier, _, parsed = adapt(raw, visible='artifact_kind: lsr')
    assert raw in carrier and 'artifact_kind: lsr' in carrier
    assert parsed == service.read_model_query_response(carrier, finish_reason='tool_calls')
    assert parsed['artifact_kind_declaration']['status'] == 'conflict'


def test_length_response_retains_current_unread_tail_semantics():
    raw = json.dumps({'artifact_kind': 'lsr', 'queries': QUERIES}, ensure_ascii=False)
    carrier, _, parsed = adapt(raw, finish='length')
    assert carrier == raw
    assert parsed == service.read_model_query_response(raw, finish_reason='length')
    assert [query.text for query in parsed['queries']] == QUERIES[:-1]
    assert parsed['unread_tail'] == QUERIES[-1]


def test_no_native_call_is_the_unchanged_text_fallback_without_another_model_turn():
    raw = '{"artifact_kind":"vor","queries":[]}'
    carrier, observed = transport.query_declaration_response_text(raw,
        response=InferenceResponse(text=raw, tool_calls=(), finish_reason='stop', usage={}), advertised=True)
    assert carrier == raw and observed['channel'] == 'text'
    assert service.read_model_query_response(carrier)['intentional_empty'] is True


def test_real_governor_native_schema_overflow_falls_back_to_identical_text_context():
    preset = ModelExecutionPreset(preset_id='query-boundary', model_family='fixture',
        input_token_limit=100000, generation_reserve_tokens=128, safety_reserve_tokens=16,
        normal_tool_count=6, max_tools=6, max_batch_items=6, parallel_read_limit=1,
        reasoning_enabled=False, source_chain=('test',))
    original = dict(preset=preset, retrieval_trace={}, purpose='model_rag_queries',
        profile_prefix='Original profile and text phase directive', request_payload={'question': 'Literal user question'},
        required_evidence=[{'source_row': 'S!R2', 'line': 'Literal source quantity12 unitm; quotes " unchanged'}])
    old_messages, old_packet = service.govern_model_query_messages(**original)
    original['preset'] = replace(preset, input_token_limit=old_packet.included_tokens + preset.generation_reserve_tokens + preset.safety_reserve_tokens)
    tools, _ = transport.resolve_query_declaration_transport(connection(), now=NOW)
    before_evidence = deepcopy(original['required_evidence'])
    messages, packet, used_tools, capacity = transport.govern_query_declaration_messages(
        service.govern_model_query_messages, native_tools=tools, **original)
    assert used_tools == [] and capacity['reason'] == 'native_query_schema_capacity'
    assert capacity['effective_transport'] == 'text'
    assert messages == old_messages
    assert original['required_evidence'] == before_evidence
    assert packet.included_tokens == old_packet.included_tokens
    assert not any('declare_research_queries' in str(message) for message in messages)


def test_schema_fallback_catches_only_capacity_errors():
    tools, _ = transport.resolve_query_declaration_transport(connection(), now=NOW)
    calls = []
    def broken(**context):
        calls.append(context)
        raise RuntimeError('Unrelated technical failure')
    with pytest.raises(RuntimeError, match='Unrelated technical failure'):
        transport.govern_query_declaration_messages(broken, native_tools=tools, profile_prefix='Original')
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('variant', ['B0_DIRECT', 'B1_CANDIDATE'])
@pytest.mark.parametrize('native', [False, True])
async def test_actual_b0_b1_query_carrier_keeps_search_and_export_without_extra_inference(tmp_path, monkeypatch, variant, native):
    monkeypatch.setenv('LES_LSR_SYSTEM_CANDIDATE_QUERIES', 'off')
    original_resolve = service.resolve_query_declaration_transport
    def measured_connection(conn, **kwargs):
        conn.capability_snapshot = connection().capability_snapshot
        return original_resolve(conn, now=NOW)
    monkeypatch.setattr(service, 'resolve_query_declaration_transport', measured_connection)
    original_complete = service.BoundModelChatRunner.complete
    first = True
    raw = json.dumps({'artifact_kind': 'lsr', 'queries': QUERIES}, ensure_ascii=False)
    async def complete(self, **kwargs):
        nonlocal first
        result = await original_complete(self, **kwargs)
        if first:
            first = False
            assert [tool['function']['name'] for tool in kwargs['request'].tools] == [transport.QUERY_DECLARATION_FUNCTION]
            assert kwargs['request'].response_format is None
            if native:
                result = replace(result, response=InferenceResponse(text='', tool_calls=(call(raw),), finish_reason='tool_calls', usage={}))
        return result
    monkeypatch.setattr(service.BoundModelChatRunner, 'complete', complete)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant, query_declaration=raw)
    assert run.queries == QUERIES
    assert len(run.requests) == 2 and not run.responses
    assert len(run.executions) == 1
    assert run.executions[0][0]['tool'] == 'build_lsr_workbook'
    state = run.result['retrieval_trace']['query_declaration_transport']
    assert state['decision']['effective'] == 'native_function_optional'
    assert [item['channel'] for item in state['calls']] == ['native_function' if native else 'text']
    assert run.requests[1].tools and all(tool['function']['name'] != transport.QUERY_DECLARATION_FUNCTION for tool in run.requests[1].tools)


@pytest.mark.asyncio
@pytest.mark.parametrize('variant', ['B0_DIRECT', 'B1_CANDIDATE'])
@pytest.mark.parametrize('invalid_kind', ['invalid_raw_arguments', 'unknown_function', 'multiple_calls'])
async def test_actual_b0_b1_invalid_native_uses_only_existing_bounded_repair(tmp_path, monkeypatch, variant, invalid_kind):
    monkeypatch.setenv('LES_LSR_SYSTEM_CANDIDATE_QUERIES', 'off')
    original_resolve = service.resolve_query_declaration_transport
    def measured_connection(conn, **kwargs):
        conn.capability_snapshot = connection().capability_snapshot
        return original_resolve(conn, now=NOW)
    monkeypatch.setattr(service, 'resolve_query_declaration_transport', measured_connection)
    original_complete = service.BoundModelChatRunner.complete
    first = True
    async def complete(self, **kwargs):
        nonlocal first
        result = await original_complete(self, **kwargs)
        if first:
            first = False
            one = call('{"queries":[' if invalid_kind == 'invalid_raw_arguments' else '{"queries":["must not execute"]}',
                       name='unexpected' if invalid_kind == 'unknown_function' else transport.QUERY_DECLARATION_FUNCTION)
            calls = (one, call('{"queries":["also must not execute"]}', identity='call:second')) if invalid_kind == 'multiple_calls' else (one,)
            result = replace(result, response=InferenceResponse(text='', tool_calls=calls, finish_reason='tool_calls', usage={}))
        return result
    monkeypatch.setattr(service.BoundModelChatRunner, 'complete', complete)
    raw = json.dumps({'artifact_kind': 'lsr', 'queries': QUERIES}, ensure_ascii=False)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_declaration=raw, query_repair='malformed first native carrier')
    assert run.queries == QUERIES
    assert len(run.requests) == 3 and not run.responses
    calls = run.result['retrieval_trace']['query_declaration_transport']['calls']
    assert [item['channel'] for item in calls] == ['native_invalid', 'text']
    assert calls[0]['native_call_count'] == (2 if invalid_kind == 'multiple_calls' else 1)
    assert len(run.executions) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('variant', ['B0_DIRECT', 'B1_CANDIDATE'])
@pytest.mark.parametrize('unavailable', ['unknown', 'stale'])
async def test_actual_b0_b1_unknown_or_stale_caps_keep_exact_legacy_query_context(tmp_path, monkeypatch, variant, unavailable):
    monkeypatch.setenv('LES_LSR_SYSTEM_CANDIDATE_QUERIES', 'off')
    original_resolve = service.resolve_query_declaration_transport
    def measured_connection(conn, **kwargs):
        conn.capability_snapshot = connection(state=CapabilityState.UNKNOWN if unavailable == 'unknown' else CapabilityState.SUPPORTED,
                                             stale=unavailable == 'stale').capability_snapshot
        return original_resolve(conn, now=NOW)
    monkeypatch.setattr(service, 'resolve_query_declaration_transport', measured_connection)
    original_govern = service.govern_model_query_messages
    expected_messages = []
    def legacy_context(**context):
        assert not context.get('native_tools')
        assert 'declare_research_queries' not in context['profile_prefix']
        before_evidence = deepcopy(context.get('required_evidence'))
        before_source_map = deepcopy(context.get('source_map'))
        result = original_govern(**context)
        assert context.get('required_evidence') == before_evidence
        assert context.get('source_map') == before_source_map
        expected_messages.append(result[0])
        return result
    monkeypatch.setattr(service, 'govern_model_query_messages', legacy_context)
    raw = json.dumps({'artifact_kind': 'lsr', 'queries': QUERIES}, ensure_ascii=False)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant, query_declaration=raw)
    assert len(run.requests) == 2 and not run.responses
    assert not run.requests[0].tools
    assert list(run.requests[0].messages) == expected_messages[0]
    assert run.queries == QUERIES and len(run.executions) == 1
    state = run.result['retrieval_trace']['query_declaration_transport']
    assert state['decision']['effective'] == 'text'
    assert state['calls'][0]['channel'] == 'text'
    assert state['calls'][0]['capacity']['requested_transport'] == 'text'


@pytest.mark.asyncio
@pytest.mark.parametrize('variant', ['B0_DIRECT', 'B1_CANDIDATE'])
async def test_actual_b0_b1_real_capacity_fallback_keeps_full_text_source_and_two_calls(tmp_path, monkeypatch, variant):
    monkeypatch.setenv('LES_LSR_SYSTEM_CANDIDATE_QUERIES', 'off')
    original_resolve = service.resolve_query_declaration_transport
    def measured_connection(conn, **kwargs):
        conn.capability_snapshot = connection().capability_snapshot
        return original_resolve(conn, now=NOW)
    monkeypatch.setattr(service, 'resolve_query_declaration_transport', measured_connection)
    original_govern = service.govern_model_query_messages
    packed = []
    def actual_query_boundary(**context):
        requested_tools = context.get('native_tools') or []
        text_context = {**context, 'native_tools': []}
        if requested_tools:
            text_context['profile_prefix'] = context['profile_prefix'].removesuffix(
                transport.query_declaration_native_instruction(requested_tools))
        old_messages, baseline = original_govern(**text_context)
        preset = context['preset']
        boundary = baseline.included_tokens + preset.generation_reserve_tokens + preset.safety_reserve_tokens
        packed.append({'native': bool(requested_tools), 'profile_prefix': text_context['profile_prefix'],
                       'required_evidence': deepcopy(context.get('required_evidence')), 'old_messages': old_messages})
        return original_govern(**{**context, 'preset': replace(preset, input_token_limit=boundary)})
    monkeypatch.setattr(service, 'govern_model_query_messages', actual_query_boundary)
    raw = json.dumps({'artifact_kind': 'lsr', 'queries': QUERIES}, ensure_ascii=False)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant, query_declaration=raw)
    assert run.queries == QUERIES and len(run.requests) == 2 and not run.responses
    assert len(run.executions) == 1
    assert [item['native'] for item in packed] == [True, False]
    assert packed[0]['profile_prefix'] == packed[1]['profile_prefix']
    assert packed[0]['required_evidence'] == packed[1]['required_evidence']
    assert list(run.requests[0].messages) == packed[1]['old_messages']
    assert not run.requests[0].tools
    state = run.result['retrieval_trace']['query_declaration_transport']['calls'][0]
    assert state['capacity']['reason'] == 'native_query_schema_capacity'
    assert state['capacity']['effective_transport'] == 'text'


@pytest.mark.asyncio
@pytest.mark.parametrize('variant', ['B0_DIRECT', 'B1_CANDIDATE'])
async def test_actual_b0_b1_both_transports_overflow_before_any_model_dispatch(tmp_path, monkeypatch, variant):
    original_resolve = service.resolve_query_declaration_transport
    def measured_connection(conn, **kwargs):
        conn.capability_snapshot = connection().capability_snapshot
        return original_resolve(conn, now=NOW)
    monkeypatch.setattr(service, 'resolve_query_declaration_transport', measured_connection)
    original_govern = service.govern_model_query_messages
    packed = []
    def no_transport_fits(**context):
        packed.append(bool(context.get('native_tools')))
        return original_govern(**{**context, 'preset': replace(context['preset'], input_token_limit=1)})
    monkeypatch.setattr(service, 'govern_model_query_messages', no_transport_fits)
    dispatches = []
    async def no_dispatch(*args, **kwargs):
        dispatches.append(kwargs)
        pytest.fail('A context-overflow request must never be sent')
    monkeypatch.setattr(service.BoundModelChatRunner, 'complete', no_dispatch)
    with pytest.raises(service.HTTPException) as stopped:
        await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant)
    assert packed == [True, False]
    assert dispatches == []
    assert stopped.value.status_code == (500 if variant == 'B0_DIRECT' else 503)
    if variant == 'B0_DIRECT':
        assert 'ContextRequiredSectionOverflow' in str(stopped.value.detail)
