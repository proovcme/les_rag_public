"""A bounded technical repair sees its rejected visible output, not hidden reasoning."""
import copy
import hashlib
import json
from dataclasses import replace

import pytest

from proxy.services import chat_evidence_application_service as service
from tests import test_model_rag_sheet_evidence_reads as fixture

FAULT = 'Introductory output Ω\r\n```json\r\n{"queries":["S!R2 — unfinished literal Ω'
REPAIRED = ['S!R2 — Cable A', 'S!R3 — Cable B']


def request_data(request):
    for message in request.messages:
        if message.get('role') != 'user':
            continue
        for line in message.get('content', '').splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict) and 'question' in value:
                return value
    raise AssertionError('actual governed request data missing')


def response_finish(monkeypatch, fault, finish):
    original = fixture.InferenceResponse
    def response(*args, **kwargs):
        if kwargs.get('text') == fault:
            kwargs = {**kwargs, 'finish_reason': finish,
                      'usage': {'completion_tokens': 8192 if finish == 'length' else 90},
                      'reasoning_content': 'PRIVATE_REASONING_NOT_QUERY_CONTEXT'}
        return original(*args, **kwargs)
    monkeypatch.setattr(fixture, 'InferenceResponse', response)


@pytest.mark.asyncio
@pytest.mark.parametrize('variant', ['B0_DIRECT', 'B1_CANDIDATE'])
@pytest.mark.parametrize('finish', ['length', 'stop'])
async def test_actual_second_query_request_keeps_rejected_final_finish_parse_and_same_source(tmp_path, monkeypatch, variant, finish):
    monkeypatch.setenv('LES_LSR_SYSTEM_CANDIDATE_QUERIES', 'off')
    response_finish(monkeypatch, FAULT, finish)
    governed = []; governed_sources = []
    original = service.govern_inference_messages
    def record(**kwargs):
        governed.append(copy.deepcopy(kwargs))
        result = original(**kwargs)
        governed_sources.append([(section.kind, section.render()) for section in result[1].sections
                                 if section.kind in (service.ContextKind.EVIDENCE, service.ContextKind.SOURCE_MAP)])
        return result
    monkeypatch.setattr(service, 'govern_inference_messages', record)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_repair=FAULT, query_declaration=json.dumps({'artifact_kind': 'lsr', 'queries': REPAIRED}),
        temperature=0.65, query_reasoning_enabled=False)
    initial, repaired = [request_data(request) for request in run.requests[:2]]
    previous = repaired['rejected_query_attempt']
    assert previous['assistant_visible_final'] == FAULT
    assert previous['finish_reason'] == finish
    assert previous['parse_diagnostics']['accepted_count'] == 0
    assert previous['parse_diagnostics']['output_shape'] == 'unsupported_structured_output'
    assert previous['parse_diagnostics']['answer_cut'] is (finish == 'length')
    assert previous['kind'] == 'rejected_technical_attempt_data'
    assert initial == {key: value for key, value in repaired.items() if key != 'rejected_query_attempt'}
    query_governed = [call for call in governed if isinstance(call['request_payload'], dict)
                      and 'question' in call['request_payload']][:2]
    assert governed_sources[0] == governed_sources[1]
    assert governed_sources[0]
    for _, literal in governed_sources[0]:
        assert literal in run.requests[1].messages[-1]['content']
    assert query_governed[0].get('working_memory', ()) == query_governed[1].get('working_memory', ())
    assert query_governed[0]['profile_prefix'] in query_governed[1]['profile_prefix']
    assert 'не удалось разобрать' in query_governed[1]['profile_prefix']
    assert 'не содержал поисковых строк' not in query_governed[1]['profile_prefix']
    assert 'PRIVATE_REASONING_NOT_QUERY_CONTEXT' not in str(run.requests[1].messages)
    assert run.queries == REPAIRED and len(run.requests) == 3
    assert run.requests[0].temperature == run.requests[1].temperature == 0.65
    assert run.requests[0].max_output_tokens == run.requests[1].max_output_tokens
    assert len(run.executions) == 1
    assert [row['quantity'] for row in run.executions[0][0]['args']['decisions']] == [12, 3]
    context = run.result['retrieval_trace']['query_repair_context']
    assert len(context) == 1 and context[0]['status'] == 'admitted_complete'
    assert context[0]['previous_visible_chars'] == len(FAULT)
    assert context[0]['previous_visible_sha256'] == hashlib.sha256(FAULT.encode('utf-8')).hexdigest()
    assert 'assistant_visible_final' not in context[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('variant', ['B0_DIRECT', 'B1_CANDIDATE'])
async def test_full_previous_response_larger_than_history_excerpt_is_not_shortened(tmp_path, monkeypatch, variant):
    raw = FAULT + 'Ω' * 9000 + 'VISIBLE_TAIL_MUST_SURVIVE'
    response_finish(monkeypatch, raw, 'length')
    monkeypatch.setenv('LES_LSR_SYSTEM_CANDIDATE_QUERIES', 'off')
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_repair=raw, query_declaration=json.dumps({'artifact_kind': 'lsr', 'queries': REPAIRED}))
    assert request_data(run.requests[1])['rejected_query_attempt']['assistant_visible_final'] == raw
    assert len(run.requests) == 3 and run.queries == REPAIRED


@pytest.mark.asyncio
@pytest.mark.parametrize('variant', ['B0_DIRECT', 'B1_CANDIDATE'])
async def test_unfittable_previous_response_blocks_without_truncation_or_extra_model_call(tmp_path, monkeypatch, variant):
    raw = FAULT + 'Ω' * 240000 + 'VISIBLE_TAIL_MUST_SURVIVE'
    response_finish(monkeypatch, raw, 'length')
    monkeypatch.setenv('LES_LSR_SYSTEM_CANDIDATE_QUERIES', 'off')
    sent = []
    original_append = service.append_actual_model_call
    def append(*args, **kwargs):
        sent.append(kwargs.get('purpose'))
        return original_append(*args, **kwargs)
    monkeypatch.setattr(service, 'append_actual_model_call', append)
    with pytest.raises(service.ModelQueryFailure) as caught:
        await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
            query_repair=raw, query_declaration=json.dumps({'artifact_kind': 'lsr', 'queries': REPAIRED}))
    assert sent == ['model_rag_queries' if variant == 'B0_DIRECT' else 'model_rag_sheet_queries']
    context = caught.value.private_query_trace['query_repair_context']
    assert len(context) == 1 and context[0]['status'] == 'blocked_capacity'
    assert context[0]['code'] == 'MODEL_QUERY_REPAIR_CONTEXT_OVERFLOW'
    assert context[0]['previous_visible_chars'] == len(raw)
    assert context[0]['previous_visible_sha256'] == hashlib.sha256(raw.encode('utf-8')).hexdigest()
    assert context[0]['required_tokens'] > context[0]['budget_tokens']
    assert 'VISIBLE_TAIL_MUST_SURVIVE' not in str(context)
    assert caught.value.detail == 'MODEL_QUERY_GENERATION_LIMIT'
    output = caught.value.private_query_trace['model_query_outputs'][-1]
    assert output['generation_limit_reached'] is True
    assert output['finish_reason'] == 'length'
    assert output['declared_parse']['accepted_count'] == 0


def test_repair_data_excludes_reasoning_and_secrets_but_keeps_all_visible_literals():
    visible = '  literal Ω\r\n{"queries":["unchanged token"]}\n'
    data = service.model_query_repair_attempt_data(
        '<think>HIDDEN_REASONING</think>' + visible + 'Bearer secret-value\napi_key="another-secret"',
        finish_reason='', parse_diagnostics={'accepted_count': 0, 'answer_cut': True,
                                            'output_shape': 'unsupported_structured_output'},
        secret_values=('secret-value',))
    assert data['assistant_visible_final'].startswith(visible)
    assert data['finish_reason'] == 'unknown'
    assert 'HIDDEN_REASONING' not in str(data) and 'secret-value' not in str(data)
    assert 'another-secret' not in str(data)
    assert data['assistant_visible_final'].count('[redacted]') >= 2


def test_existing_whole_wire_admission_rejects_required_repair_data_without_erasing_it():
    from proxy.services.model_execution_preset_service import ModelExecutionPreset
    from proxy.services.openai_compatible_transport_service import CloudBudgetStop
    raw = FAULT + 'Ω' * 9000 + 'LITERAL_TAIL'
    data = service.model_query_repair_attempt_data(raw, finish_reason='length',
        parse_diagnostics={'accepted_count': 0, 'answer_cut': True})
    trace = {}; admitted = []
    def wire(messages):
        admitted.append(messages)
        return False
    with pytest.raises(CloudBudgetStop):
        service.govern_model_query_messages(retrieval_trace=trace, purpose='query-repair', rejected_attempt=data,
            preset=ModelExecutionPreset('repair-wire', 'fixture', 30000, 8192, 1000, 1, 5, 6, 1, False, ('fixture',)),
            profile_prefix='literal profile', request_payload={'question': 'literal source task'},
            required_evidence=['literal source row Ω'], admit_messages=wire)
    assert admitted and request_data(type('Request', (), {'messages': admitted[-1]})())['rejected_query_attempt']['assistant_visible_final'] == raw
    context = trace['query_repair_context']
    assert context[0]['status'] == 'blocked_wire_budget'
    assert context[0]['code'] == 'MODEL_QUERY_REPAIR_CONTEXT_OVERFLOW'
    assert context[0]['previous_visible_chars'] == len(raw)


@pytest.mark.asyncio
async def test_frame_zero_repair_cannot_evict_first_shown_attachment_source_before_second_call(tmp_path, monkeypatch):
    monkeypatch.setenv('LES_LSR_SYSTEM_CANDIDATE_QUERIES', 'off')
    raw = FAULT + 'R' * 4000
    response_finish(monkeypatch, raw, 'length')
    original_selector = service.selector_evidence_payload
    def padded_source(**kwargs):
        result = list(original_selector(**kwargs))
        result.append('FIRST_SHOWN_SOURCE_LITERAL_' + 'S' * 12000)
        return result
    monkeypatch.setattr(service, 'selector_evidence_payload', padded_source)
    original_govern = service.govern_inference_messages
    query_frames = []; limit = None
    def tight_query_budget(**kwargs):
        nonlocal limit
        if isinstance(kwargs['request_payload'], dict) and 'question' in kwargs['request_payload']:
            if limit is None:
                _, first = original_govern(**kwargs)
                limit = first.included_tokens + first.generation_reserve_tokens + first.safety_reserve_tokens + 200
            kwargs = {**kwargs, 'preset': replace(kwargs['preset'], input_token_limit=limit)}
            messages, packet = original_govern(**kwargs)
            query_frames.append((messages, packet))
            return messages, packet
        return original_govern(**kwargs)
    monkeypatch.setattr(service, 'govern_inference_messages', tight_query_budget)
    purposes = []
    original_append = service.append_actual_model_call
    def append(*args, **kwargs):
        purposes.append(kwargs.get('purpose'))
        return original_append(*args, **kwargs)
    monkeypatch.setattr(service, 'append_actual_model_call', append)
    with pytest.raises(service.ModelQueryFailure) as caught:
        await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant='B0_DIRECT',
            query_repair=raw, query_declaration=json.dumps({'artifact_kind': 'lsr', 'queries': REPAIRED}))
    assert purposes == ['model_rag_queries']
    assert len(query_frames) == 1
    messages, packet = query_frames[0]
    assert 'FIRST_SHOWN_SOURCE_LITERAL_' in str(messages)
    assert 'Cable A' in str(messages) and 'Cable B' in str(messages)
    assert not packet.omissions
    assert caught.value.private_query_trace['query_repair_context'][0]['code'] == 'MODEL_QUERY_REPAIR_CONTEXT_OVERFLOW'


def test_generic_spending_stop_keeps_its_identity_and_is_not_context_overflow():
    from proxy.services.model_execution_preset_service import ModelExecutionPreset
    from proxy.services.openai_compatible_transport_service import CloudBudgetStop
    stop = CloudBudgetStop('CLOUD_FREE_QUOTA_EXHAUSTED')
    def quota(messages):
        raise stop
    trace = {}
    with pytest.raises(CloudBudgetStop) as caught:
        service.govern_model_query_messages(retrieval_trace=trace, purpose='query-repair',
            rejected_attempt=service.model_query_repair_attempt_data(FAULT, finish_reason='stop', parse_diagnostics={}),
            preset=ModelExecutionPreset('quota', 'fixture', 30000, 8192, 1000, 1, 5, 6, 1, False, ('fixture',)),
            profile_prefix='literal profile', request_payload={'question': 'literal task'}, admit_messages=quota)
    assert caught.value is stop
    assert trace['query_repair_context'][0]['status'] == 'blocked_spending_budget'
    assert 'code' not in trace['query_repair_context'][0]


def test_repair_retains_only_first_admitted_whole_source_sections_and_not_unseen_source():
    from proxy.services.model_execution_preset_service import ModelExecutionPreset
    common = dict(preset=ModelExecutionPreset('source', 'fixture', 1400, 100, 10, 1, 5, 6, 1, False, ('fixture',)),
        profile_prefix='original profile', request_payload={'question': 'original task'},
        evidence=['SHOWN_SOURCE_' + 'S' * 800, 'UNSHOWN_SOURCE_' + 'U' * 10000],
        source_map=[{'source_ref': 'S!R2', 'title': 'original source title'}])
    _, first = service.govern_model_query_messages(retrieval_trace={}, purpose='query', **common)
    assert first.omissions
    repair, packet = service.govern_model_query_messages(retrieval_trace={}, purpose='query-repair',
        rejected_attempt=service.model_query_repair_attempt_data(FAULT, finish_reason='length', parse_diagnostics={}),
        first_source_packet=first, **common)
    before = [(section.kind, section.render()) for section in first.sections
              if section.kind in (service.ContextKind.EVIDENCE, service.ContextKind.SOURCE_MAP)]
    after = [(section.kind, section.render()) for section in packet.sections
             if section.kind in (service.ContextKind.EVIDENCE, service.ContextKind.SOURCE_MAP)]
    assert before == after
    assert 'SHOWN_SOURCE_' in str(repair) and 'UNSHOWN_SOURCE_' not in str(repair)
    assert 'original source title' in str(repair)
    assert not packet.omissions
