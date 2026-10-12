import pytest
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from proxy.services import chat_evidence_application_service as chat
from proxy.services import model_research_tool_service as research
from proxy.services.model_execution_preset_service import ModelExecutionPreset


def _saved_distinct_queries():
    fixture = json.loads((Path(__file__).parent / 'fixtures/smeta_distinct_delivery.json').read_text(encoding='utf-8'))
    return [(g['query'], [SimpleNamespace(**h, score=1.0) for h in g['hits']])
            for g in fixture['groups']]


@pytest.mark.parametrize('budget', [12000, 24000, 48000])
def test_distinct_saved_previews_report_actual_body_loss_in_final_messages(budget):
    queries = _saved_distinct_queries()
    bodies = [h.content.strip() for _q, hits in queries for h in hits]
    assert len(bodies) == len(set(bodies)) == 36
    assert len({h.meta['norm_code'] for _q, hits in queries for h in hits}) == 36
    groups, chunks = chat.build_model_rag_evidence_groups(queries, max_chars=budget, hits_per_query=6)
    assert len('\n\n'.join(groups)) <= budget
    preset = ModelExecutionPreset('distinct', 'fixture', 60000, 0, 0, 3, 5, 5, 1, False, ('test',))
    messages, packet = chat.govern_inference_messages(
        preset=preset, profile_prefix='Estimator', request_payload='Inspect these saved previews',
        evidence=chat.answer_evidence_blocks(fixed_blocks=[], group_blocks=groups,
            coverage=chat.model_rag_evidence_coverage(queries, groups)))
    sent = '\n'.join(m['content'] for m in messages)
    assert not packet.omissions
    complete = 0
    for chunk in chunks:
        meta = chunk.meta
        original = queries[meta['model_query_index']-1][1][meta['model_hit_index']-1]
        assert 'model_evidence_alias_of' not in meta
        intact = chunk.content == original.content.strip()
        assert meta['model_evidence_truncated'] is not intact
        assert chunk.content in sent
        if intact:
            complete += 1
            assert original.content.strip() in sent
        else:
            assert 'карточка сокращена' in chunk.content
    if budget == 48000:
        assert len(chunks) == complete == 36
    delivery = chat.smeta_evidence_delivery_trace(queries, chunks, sent)
    assert delivery['cards_total'] == 36
    assert delivery['bodies_delivered_complete'] == complete
    assert delivery['resource_sets_complete'] == 0
    assert all(c['resources']['source_items'] is None for c in delivery['cards'])
    if budget == 48000:
        assert all(s['delivered_complete'] for c in delivery['cards'] for s in c['sections'])
    # Complete saved preview does NOT mean complete resources from the database.
    assert all(not h.meta.get('smeta_full_read') for _q, hits in queries for h in hits)


def test_same_text_different_norm_editions_never_alias():
    hit = _saved_distinct_queries()[0][1][0]
    other = copy.deepcopy(hit)
    other.meta.update(edition='different-edition', source_ref='another-source#guid=other')
    groups, chunks = chat.build_model_rag_evidence_groups(
        [('one', [hit]), ('two', [other])], max_chars=12000, hits_per_query=6)
    assert len(groups) == len(chunks) == 2
    assert not any(c.meta.get('model_evidence_alias_of') for c in chunks)
    assert chunks[0].meta['source_ref'] != chunks[1].meta['source_ref']
    # A forged cross-edition alias must not inherit the first source's contents.
    forged = groups[0] + '\n[Q2.H1 | source]:\nСм. Q1.H1: тот же текст и источник.'
    delivery = chat.smeta_evidence_delivery_trace([('one', [hit]), ('two', [other])], chunks, forged)
    assert not delivery['cards'][1]['body_delivered_complete']


@pytest.mark.parametrize('quantity, expected', [(None, 'неизвестен'), (66.0, '66.0')])
def test_target_resource_code_survives_card_packing_into_messages(monkeypatch, quantity, expected):
    # No normative database, retriever, model or runtime is accessed.
    monkeypatch.setattr(research, 'norm_table_variants', lambda code: ())
    resource_code = '01.1.01.01-0001'
    body = research.smeta_card_text(dict(
        norm_code='NORM-EXACT', title='Mount cable tray', measure_unit='m',
        work_steps=['Install support brackets and fasten the cable tray. ' * 12],
        resource_preview=[dict(kind='material', code=resource_code, name='Fastener', unit='pc', per_unit=quantity)],
    ))
    assert resource_code in body
    hit = research._SmetaNormChunk(content=body, doc_name='smeta_norm_cards.v1',
                                  score=1, meta={'norm_code': 'NORM-EXACT'})
    queries = [(f'query {index}', [hit] * 6) for index in range(20)]
    groups, chunks = chat.build_model_rag_evidence_groups(
        queries, max_chars=16000, hits_per_query=6,
    )
    evidence = chat.answer_evidence_blocks(
        fixed_blocks=[], group_blocks=groups,
        coverage=chat.model_rag_evidence_coverage(queries, groups),
    )
    preset = ModelExecutionPreset(
        preset_id='resource-review', model_family='fixture', input_token_limit=22528,
        generation_reserve_tokens=0, safety_reserve_tokens=0, normal_tool_count=3,
        max_tools=5, max_batch_items=5, parallel_read_limit=1,
        reasoning_enabled=False, source_chain=('test',),
    )
    messages, _packet = chat.govern_inference_messages(
        preset=preset, profile_prefix='Estimator', request_payload='Account for materials',
        evidence=evidence,
    )
    sent = '\n'.join(message['content'] for message in messages)
    assert 'NORM-EXACT' in sent  # The card survives; only its resource tail is lost.
    print({'raw_body_chars': len(body), 'resource_code_offset': body.index(resource_code),
           'packed_body_chars': len(chunks[0].content), 'kept_groups': len(groups),
           'resource_in_packed_chunks': any(resource_code in chunk.content for chunk in chunks),
           'resource_in_messages': resource_code in sent})
    assert resource_code in sent
    assert f'Fastener [pc; {expected}]' in sent
    assert 'расход на m' in sent


def test_archive_application_survives_long_resource_preview(monkeypatch):
    monkeypatch.setattr(research, 'norm_table_variants', lambda code: ())
    card = dict(norm_code='NORM-EXACT', title='Mount cabinet', measure_unit='pc',
                application_note='Archive: the same cabinet was paired with this norm',
                resource_preview=[dict(kind='material', code=f'R{i}',
                    name='A long resource description ' * 12, unit='kg') for i in range(8)])
    body = research.smeta_card_text(card)
    hit = research._SmetaNormChunk(content=body, doc_name='smeta_material_cards.v1',
                                 score=1, meta={'norm_code': 'NORM-EXACT'})
    groups, chunks = chat.build_model_rag_evidence_groups(
        [(f'query {i}', [hit] * 6) for i in range(20)], max_chars=16000, hits_per_query=6)
    preset = ModelExecutionPreset(
        preset_id='practice-review', model_family='fixture', input_token_limit=22528,
        generation_reserve_tokens=0, safety_reserve_tokens=0, normal_tool_count=3,
        max_tools=5, max_batch_items=5, parallel_read_limit=1,
        reasoning_enabled=False, source_chain=('test',),
    )
    messages, _ = chat.govern_inference_messages(
        preset=preset, profile_prefix='Estimator', request_payload='Select work',
        evidence=groups,
    )
    sent = '\n'.join(message['content'] for message in messages)
    assert card['application_note'] in sent
    assert 'R0' in sent
