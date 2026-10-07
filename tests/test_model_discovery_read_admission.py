"""Typed discovery availability must not promote unread bodies to required reads."""
from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as chat
from proxy.services.context_governor_service import ContextRequiredSectionOverflow
from proxy.services.model_evidence_read_service import evidence_read_receipt, native_evidence_read_exchange
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from proxy.services.model_rag_grouped_evidence_service import prepare_model_read_replay
from proxy.services.model_research_tool_service import ModelResearchToolResult, _norm_search_chunk


def _card(group, rank, *, body_chars=20):
    return {
        'norm_key': f'synthetic:{group}:{rank}', 'norm_code': f'SYN-{group}-{rank}',
        'edition': 'literal fixture edition', 'base_type': 'literal fixture base',
        'title': f'Literal authored operation {group}:{rank}', 'measure_unit': 'm',
        'work_steps': ['Literal work composition'], 'source_ref': f'fixture.xml#card={group}:{rank}',
        'source_sha256': 'b'*64, 'normative_base_sha256': 'a'*64,
        'hydration_status': 'ok', 'resources_complete': True,
        'resource_consumption_known': True, 'resources_returned': 1, 'resource_count': 1,
        'resources': [{'code': f'R-{group}-{rank}', 'name': f'Literal resource {group}:{rank} ' + 'x'*body_chars,
                       'kind': 'material', 'unit': 'kg', 'per_unit': 0.5,
                       'source_ref': f'fixture.xml#resource={group}:{rank}'}],
        'resource_preview': [{'code': f'R-{group}-{rank}', 'name': f'Preview {group}:{rank}',
                             'kind': 'material', 'unit': 'kg'}],
    }


def _results(groups=1, ranks=1, *, body_chars=20, tool='search_sources'):
    results, receipts, calls = [], [], []
    for group in range(groups):
        hits = tuple(_norm_search_chunk(_card(group, rank, body_chars=body_chars),
                                      score=float(ranks-rank), matched_before_cap=ranks)
                     for rank in range(ranks))
        result = ModelResearchToolResult(payload={'tool': tool, 'status': 'ok', 'missing': [], 'warnings': [], 'trace': {}},
                                         chunks=hits)
        args = {'q': f'Literal model query {group}', 'target': 'norms'} if tool == 'search_sources' else {'evidence_ref': 'Q1.H1'}
        call = {'tool': tool, 'args': args, 'call_id': f'provider-literal-{group}',
                'native_arguments': json.dumps(args, ensure_ascii=False, separators=(',', ':'))}
        calls.append(call)
        receipts.append(evidence_read_receipt(call, result))
        results.append(result)
    _, chunks, omitted = chat.bind_model_requested_read_evidence(
        results, existing_chunks=[], reserved_query_end=1,
        evidence_namespace='generic-read-test', receipts=receipts)
    assert omitted == []
    return chunks, receipts, calls


def _snapshot(chunks, receipts=()):
    return copy.deepcopy(([vars(chunk) for chunk in chunks], list(receipts)))


def test_prepared_hydrated_search_body_is_optional_not_a_required_exact_read():
    chunks, receipts, _ = _results(groups=2, ranks=2)
    original = _snapshot(chunks, receipts)
    assert all(chunk.meta['exact_card_read'] is True and chunk.meta['resources_complete'] is True
               and chunk.meta['model_read_tool'] == 'search_sources'
               and chunk.meta['model_delivery_status'] == 'prepared' for chunk in chunks)

    replay = prepare_model_read_replay(chunks)

    assert replay.exact_body_refs == []
    assert replay.optional_body_refs == [['Q2.H1', 'Q2.H2'], ['Q3.H1', 'Q3.H2']]
    assert replay.inventory_refs == ['Q2.H1', 'Q2.H2', 'Q3.H1', 'Q3.H2']
    required = json.dumps(replay.required, ensure_ascii=False)
    for chunk in chunks:
        assert chunk.content not in required
        assert chunk.content in '\n'.join(replay.optional)
    assert _snapshot(chunks, receipts) == original


@pytest.mark.parametrize('tool', ['read_norm_card', 'read_resource_price', 'read_source'])
def test_explicit_exact_reads_remain_required(tool):
    chunks, receipts, _ = _results(tool=tool)
    original = _snapshot(chunks, receipts)
    replay = prepare_model_read_replay(chunks)
    assert replay.exact_body_refs == ['Q2.H1'] and replay.optional == []
    assert chunks[0].content in [row.get('content') for row in replay.required[1]['previously_shown_evidence_registry']]
    assert _snapshot(chunks, receipts) == original


@pytest.mark.parametrize('required_identity', ['alias', 'global'])
def test_required_reference_keeps_search_body_required(required_identity):
    chunks, receipts, _ = _results()
    original = _snapshot(chunks, receipts)
    identity = chunks[0].meta['model_evidence_ref' if required_identity == 'alias' else 'global_evidence_id']
    replay = prepare_model_read_replay(chunks, required_refs=[identity])
    assert replay.exact_body_refs == ['Q2.H1'] and replay.optional == []
    assert _snapshot(chunks, receipts) == original


def test_actually_delivered_full_search_body_remains_required():
    chunks, receipts, _ = _results()
    chat.confirm_model_read_delivery(chunks, receipts, inventory_refs=['Q2.H1'], body_refs=['Q2.H1'])
    original = _snapshot(chunks, receipts)
    replay = prepare_model_read_replay(chunks)
    assert replay.exact_body_refs == ['Q2.H1'] and replay.optional == []
    assert chunks[0].content in [row.get('content') for row in replay.required[1]['previously_shown_evidence_registry']]
    assert _snapshot(chunks, receipts) == original


def test_legacy_exact_card_without_discovery_tool_keeps_required_contract():
    chunks, receipts, _ = _results()
    chunks[0].meta.pop('model_read_tool')
    original = _snapshot(chunks, receipts)
    replay = prepare_model_read_replay(chunks)
    assert replay.exact_body_refs == ['Q2.H1'] and replay.optional == []
    assert _snapshot(chunks, receipts) == original


def test_initial_delivered_preview_remains_literal_preview_not_unshown_full_card():
    hit = _norm_search_chunk(_card(0, 0, body_chars=10000), score=1, matched_before_cap=1)
    _, chunks, _ = chat.build_model_rag_evidence_groups([('Literal model query', [hit])],
                                                     max_chars=4000, hits_per_query=1)
    chunk, = chunks
    assert chunk.meta['normative_card_complete'] is False
    assert chunk.meta['exact_card_read'] is False
    assert len(chunk.content) < len(hit.content)
    chat.confirm_model_read_delivery(chunks, inventory_refs=['Q1.H1'], body_refs=['Q1.H1'])
    original = _snapshot(chunks)
    replay = prepare_model_read_replay(chunks)
    registry = replay.required[1]['previously_shown_evidence_registry']
    assert registry[0]['content'] == chunk.content and registry[0]['normative_card_complete'] is False
    assert replay.exact_body_refs == ['Q1.H1']
    assert hit.content not in json.dumps(replay.required, ensure_ascii=False)
    assert _snapshot(chunks) == original


def _preset():
    return ModelExecutionPreset('generic-bound-read', 'fixture', 65536, 16384, 2048,
                                5, 6, 12, 1, True, ('fixture',))


@pytest.mark.asyncio
@pytest.mark.parametrize('counter_available', [True, False])
async def test_sixty_prepared_search_cards_fit_bound_continuation_as_inventory_and_whole_groups(counter_available):
    chunks, receipts, calls = _results(groups=10, ranks=6, body_chars=6000)
    original = _snapshot(chunks, receipts)
    calls[0]['native_assistant_content'] = 'Literal public assistant request'
    calls[0]['native_reasoning_content'] = 'Synthetic internal transport text ' * 140
    exchange = native_evidence_read_exchange(calls, receipts)
    native_tools = chat.model_evidence_read_tool_schemas()
    count_wires = []
    async def count(messages):
        if not counter_available:
            return None
        wire = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(wire.encode('utf-8')).hexdigest()
        assert digest not in count_wires
        count_wires.append(digest)
        return SimpleNamespace(tokens=(len(wire)+len(json.dumps(native_tools,ensure_ascii=False))+1)//2, source='fixture-whole-wire',
                               model_id='actual-fixture-model', connection_revision_id='fixture:r1',
                               model_identity_sha256='c'*64, wire_sha256=digest)
    messages, packet, inventory, bodies = await chat.govern_model_read_messages_bound(
        count_messages=count, preset=_preset(), profile_prefix='Literal profile',
        request_payload='Literal original question', source_context=['Literal complete original source'],
        chunks=chunks, receipts=receipts, native_exchanges=(exchange,), native_tools=native_tools)
    wire = json.dumps(messages, ensure_ascii=False)
    assert packet.input_budget_tokens + packet.provider_payload_tokens == 47104
    assert packet.generation_reserve_tokens == 16384
    assert packet.safety_reserve_tokens == 2048 and packet.included_tokens <= packet.input_budget_tokens
    assert len(inventory) == 60 and bodies and len(bodies) < 60
    assert 'Literal complete original source' in wire
    assert messages[-12:-1] == exchange.as_messages()
    assert messages[-12]['reasoning_content'] == calls[0]['native_reasoning_content']
    assert messages[1]['role'] == 'user' and 'Literal original question' in messages[1]['content']
    assert messages[-1]['role'] == 'user' and 'Literal complete original source' in messages[-1]['content']
    if not counter_available:
        assert packet.token_count_binding['status'] == 'fallback'
        assert packet.token_count_source == 'conservative_chars_per_two'
    for call in calls:
        assert call['native_arguments'] in [item['function']['arguments'] for item in messages[-12]['tool_calls']]
    admitted_groups = {int(ref.split('.')[0][1:]) for ref in bodies}
    assert all(sum(ref.startswith(f'Q{group}.') for ref in bodies) == 6 for group in admitted_groups)
    assert all(ref in wire for ref in inventory)
    assert _snapshot(chunks, receipts) == original


@pytest.mark.asyncio
@pytest.mark.parametrize('counter_available', [True, False])
async def test_sixty_explicit_exact_reads_still_fail_closed_without_dropping_bodies(counter_available):
    chunks, receipts, calls = _results(groups=10, ranks=6, body_chars=6000, tool='read_norm_card')
    original = _snapshot(chunks, receipts)
    exchange = native_evidence_read_exchange(calls, receipts)
    async def count(messages):
        if not counter_available:
            return None
        wire = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return SimpleNamespace(tokens=(len(wire)+1)//2, source='fixture-whole-wire',
                               model_id='actual-fixture-model', connection_revision_id='fixture:r1',
                               wire_sha256=hashlib.sha256(wire.encode('utf-8')).hexdigest())
    with pytest.raises(ContextRequiredSectionOverflow) as caught:
        await chat.govern_model_read_messages_bound(
            count_messages=count, preset=_preset(), profile_prefix='Literal profile',
            request_payload='Literal original question', source_context=['Literal complete original source'],
            chunks=chunks, receipts=receipts, native_exchanges=(exchange,))
    assert caught.value.required_tokens > caught.value.budget == 47104
    assert _snapshot(chunks, receipts) == original
