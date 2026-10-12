"""Exact norm reads must deliver all stored rows, not the search preview."""
import asyncio
import json
import sqlite3

import pytest

from proxy.smeta_core.norm_browser import _code_listing
from proxy.services import model_research_tool_service as research
from proxy.services import chat_evidence_application_service as chat


@pytest.fixture
def norm_base(tmp_path):
    path = tmp_path / 'base.sqlite'
    with sqlite3.connect(path) as conn:
        conn.executescript('''
            CREATE TABLE norms(norm_key TEXT PRIMARY KEY, norm_id TEXT, edition TEXT,
              display_code TEXT, base_type TEXT, bare_code TEXT, norm_name TEXT,
              norm_unit TEXT, work_steps TEXT, source_doc TEXT, source_guid TEXT,
              resource_count INTEGER);
            CREATE TABLE resources(id INTEGER PRIMARY KEY, parent_norm_id TEXT,
              kind TEXT, resource_code TEXT, resource_name TEXT, resource_unit TEXT,
              per_unit REAL);
        ''')
        for n, count in enumerate((24, 26, 33), 1):
            conn.execute('INSERT INTO norms VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                         (f'key-{n}', f'norm-{n}', 'edition-a', f'ГЭСНм12-07-001-0{n}',
                          'ГЭСНм', f'12-07-001-0{n}', f'Test operation {n}', '100 м',
                          json.dumps([f'Operation {n} step {i}' for i in range(12)]),
                          'source.gsdx', f'guid-{n}', count))
            # Duplicate codes with distinct rows; zero and unknown are different.
            for i in range(count):
                conn.execute('INSERT INTO resources VALUES (?,?,?,?,?,?,?)',
                             (n * 100 + i, f'norm-{n}',
                              'labor' if i == 0 else 'material',
                              'same-code' if i < 2 else f'R-{n}-{i}',
                              '' if i == count - 1 else f'Resource {n}/{i}',
                              'кг', None if i == 1 else float(i)))
    return path


@pytest.mark.parametrize('number,count', [(1,24),(2,26),(3,33)])
def test_exact_read_preserves_every_resource_row(norm_base, number, count):
    card, = _code_listing('ГЭСНм', f'12-07-001-0{number}', base_path=norm_base)
    assert card.get('resources_complete') is True
    assert len(card['resources']) == count
    assert len({r['row_id'] for r in card['resources']}) == count
    assert len([r for r in card['resources'] if r['code'] == 'same-code']) == 2
    by_id = {r['row_id']: r for r in card['resources']}
    assert by_id[number * 100]['per_unit'] == 0
    assert by_id[number * 100 + 1]['per_unit'] is None
    assert by_id[number * 100 + count - 1]['name'] == ''
    assert card['edition'] == 'edition-a' and card['source_ref'].endswith(f'#guid=guid-{number}')


def test_table_listing_remains_explicit_preview(norm_base):
    cards = _code_listing('ГЭСНм', '12-07-001', base_path=norm_base)
    assert len(cards) == 3
    assert all(len(c['resource_preview']) == 16 for c in cards)
    assert all(not c.get('resources_complete') for c in cards)


def test_exact_and_preview_preserve_each_resource_publication(norm_base):
    with sqlite3.connect(norm_base) as conn:
        conn.execute('ALTER TABLE resources ADD COLUMN source_doc TEXT')
        conn.execute('ALTER TABLE resources ADD COLUMN source_guid TEXT')
        conn.execute('UPDATE resources SET source_doc=?,source_guid=? WHERE id=?',
                     ('Document A: exact source', 'publication-a', 100))
        conn.execute('UPDATE resources SET source_doc=?,source_guid=? WHERE id=?',
                     ('Document B: conflicting source', 'publication-b', 101))
    card, = _code_listing('ГЭСНм', '12-07-001-01', base_path=norm_base)
    rows = {r['row_id']: r for r in card['resources']}
    assert len(rows) == 24 and card['resources_complete'] is True
    assert (rows[100]['source_doc'], rows[100]['source_guid']) == ('Document A: exact source', 'publication-a')
    assert (rows[101]['source_doc'], rows[101]['source_guid']) == ('Document B: conflicting source', 'publication-b')
    assert rows[102]['source_doc'] is None and rows[102]['source_guid'] is None
    # Preview and exact read must carry the same provenance for every shown row.
    for resource in card['resource_preview']:
        raw = rows[resource['row_id']]
        assert (resource['source_doc'], resource['source_guid']) == (raw['source_doc'], raw['source_guid'])


def test_missing_resource_publication_is_not_inherited_from_parent(norm_base):
    card, = _code_listing('ГЭСНм', '12-07-001-01', base_path=norm_base)
    assert card['source_ref'].endswith('#guid=guid-1')
    assert all('source_doc' in r and r['source_doc'] is None
               and 'source_guid' in r and r['source_guid'] is None
               for r in card['resources'] + card['resource_preview'])


@pytest.mark.parametrize('code', ['12-07-001', '12-07-001-01'])
def test_reader_publication_fields_do_not_increase_visible_context(norm_base, monkeypatch, code):
    monkeypatch.setattr(research, 'norm_table_variants', lambda _code: ())
    before = _code_listing('ГЭСНм', code, base_path=norm_base)[0]
    shown_row_id = before['resource_preview'][0]['row_id']
    with sqlite3.connect(norm_base) as conn:
        conn.execute('ALTER TABLE resources ADD COLUMN source_doc TEXT')
        conn.execute('ALTER TABLE resources ADD COLUMN source_guid TEXT')
        conn.execute('UPDATE resources SET source_doc=?,source_guid=? WHERE id=?',
                     ('A literal publication ' * 200, 'publication-a', shown_row_id))
    after = _code_listing('ГЭСНм', code, base_path=norm_base)[0]
    assert after['resource_preview'][0]['source_doc'] == 'A literal publication ' * 200
    assert research.smeta_card_text(after) == research.smeta_card_text(before)
    assert research.smeta_resource_texts(after)[0][1] == research.smeta_resource_texts(before)[0][1]


def test_exact_read_unknown_code_does_not_substitute(norm_base):
    assert _code_listing('ГЭСНм', '12-07-001-99', base_path=norm_base) == []


def test_full_read_survives_model_tool_and_packet(norm_base, monkeypatch):
    monkeypatch.setattr(research, 'norm_table_variants', lambda _code: ())
    card, = _code_listing('ГЭСНм', '12-07-001-03', base_path=norm_base)
    service = research.ModelResearchToolService(
        retrieve=None, frozen_dataset_ids=(), retrieval_kwargs={}, fallback=None,
        smeta_norm_retrieve=lambda *_a, **_kw: {'cards': [card],
            'retrieval_trace': {'rag': {'status': 'ok', 'collection': 'fixture'}}})
    result = asyncio.run(service.execute({'tool':'search_sources', 'args':{'q':card['norm_code']}}))
    chunk, = result.chunks
    assert chunk.meta.get('smeta_full_read') is True
    assert 'R-3-32' in chunk.content
    assert 'same-code' in chunk.content and 'неизвестен' in chunk.content
    groups, chunks = chat.build_model_rag_evidence_groups(
        [(card['norm_code'], [chunk])], max_chars=12000, hits_per_query=6)
    assert chunks[0].content == chunk.content and chunk.content in '\n'.join(groups)
    # A full-read label must never survive on a truncated card.
    with pytest.raises(ValueError, match='EVIDENCE_BUDGET'):
        chat.build_model_rag_evidence_groups(
            [(card['norm_code'], [chunk])], max_chars=600, hits_per_query=6)


def test_count_mismatch_does_not_claim_complete(norm_base):
    with sqlite3.connect(norm_base) as conn:
        conn.execute("UPDATE norms SET resource_count=34 WHERE norm_id='norm-3'")
    card, = _code_listing('ГЭСНм', '12-07-001-03', base_path=norm_base)
    assert card.get('resources_complete') is False
    assert len(card['resources']) == 33


def test_same_code_in_two_editions_keeps_separate_identity(norm_base):
    with sqlite3.connect(norm_base) as conn:
        conn.execute('''INSERT INTO norms SELECT 'key-other','norm-other','edition-b',
            display_code,base_type,bare_code,norm_name,norm_unit,work_steps,
            'other-source.gsdx','other-guid',0 FROM norms WHERE norm_id='norm-1' ''')
    cards = _code_listing('ГЭСНм', '12-07-001-01', base_path=norm_base)
    assert len(cards) == 2
    assert {c['edition'] for c in cards} == {'edition-a','edition-b'}
    assert len({c['norm_id'] for c in cards}) == len({c['source_ref'] for c in cards}) == 2
    assert sorted(len(c['resources']) for c in cards) == [0,24]


def test_full_read_does_not_clip_long_work_steps(norm_base, monkeypatch):
    monkeypatch.setattr(research, 'norm_table_variants', lambda _code: ())
    card, = _code_listing('ГЭСНм', '12-07-001-01', base_path=norm_base)
    card['work_steps'] = ['Long source operation. ' * 500, 'LAST OPERATION']
    text = research.smeta_card_text(card)
    assert card['work_steps'][0] in text and 'LAST OPERATION' in text


@pytest.mark.parametrize('full_read,long_steps', [(False, True), (False, False), (True, True)])
def test_renderer_work_shortening_notice_reaches_final_messages(norm_base, monkeypatch, full_read, long_steps):
    from proxy.services.model_execution_preset_service import ModelExecutionPreset
    monkeypatch.setattr(research, 'norm_table_variants', lambda _code: ())
    code = '12-07-001-01' if full_read else '12-07-001'
    card = _code_listing('ГЭСНм', code, base_path=norm_base)[0]
    source_step = ('Long source operation. ' * 100 + 'LAST SOURCE OPERATION') if long_steps else 'Short source operation.'
    card['work_steps'] = [source_step]
    hit = chat._PracticeChunk(card)
    queries = [('model-owned literal query', [hit])]
    groups, chunks = chat.build_model_rag_evidence_groups(queries, max_chars=24000, hits_per_query=6)
    messages, packet = chat.govern_inference_messages(
        preset=ModelExecutionPreset('p6', 'offline-fixture', 60000, 0, 0, 3, 5, 5, 1, False, ('audit',)),
        profile_prefix='Estimator', request_payload='ORIGINAL SOURCE AND QUESTION',
        evidence=chat.answer_evidence_blocks(fixed_blocks=[], group_blocks=groups,
            coverage=chat.model_rag_evidence_coverage(queries, groups)))
    final = '\n'.join(message['content'] for message in messages)
    assert 'ORIGINAL SOURCE AND QUESTION' in final and 'model-owned literal query' in final
    assert not packet.omissions
    shortened = long_steps and not full_read
    assert ('состав сокращён' in final) is shortened
    assert card['work_steps'] == [source_step], 'Source work steps remain unchanged'
    assert chunks[0].content in final and not chunks[0].meta['model_evidence_truncated']
    if shortened:
        rendered_steps = hit.content.split('Состав работы: ', 1)[1].split('\n', 1)[0]
        assert len(rendered_steps) <= research.WORK_STEPS_MAX_CHARS + 40
        assert 'LAST SOURCE OPERATION' not in final
    else:
        assert source_step in final


@pytest.mark.parametrize('route', ['practice', 'material'])
def test_full_read_archive_routes_cannot_silently_truncate(norm_base, monkeypatch, route):
    monkeypatch.setattr(research, 'norm_table_variants', lambda _code: ())
    card, = _code_listing('ГЭСНм', '12-07-001-03', base_path=norm_base)
    chunk = (chat._PracticeChunk(card) if route == 'practice' else
             chat._MaterialChunk(card, {}, research.smeta_card_text))
    with pytest.raises(ValueError, match='EVIDENCE_BUDGET'):
        chat.build_model_rag_evidence_groups([(card['norm_code'], [chunk])], max_chars=600, hits_per_query=6)


def test_delivery_trace_checks_resources_in_last_packet_not_header(norm_base, monkeypatch):
    monkeypatch.setattr(research, 'norm_table_variants', lambda _code: ())
    card, = _code_listing('ГЭСНм', '12-07-001-03', base_path=norm_base)
    hit = chat._PracticeChunk(card)
    queries = [('original', [hit]), ('repeat', [hit])]
    groups, chunks = chat.build_model_rag_evidence_groups(queries, max_chars=12000, hits_per_query=6)
    assert hasattr(chat, 'smeta_evidence_delivery_trace'), 'Missing final-message content audit'
    trace = chat.smeta_evidence_delivery_trace(queries, chunks, '\n\n'.join(groups))
    first, alias = trace['cards']
    assert first['resources']['source_items'] == 33
    assert first['resources']['delivered_items'] == 33
    assert alias['resources']['delivered_items'] == 33
    assert first['resource_set_complete'] is True
    assert len(first['resources']['delivered_row_ids']) == 33
    # Header and intact alias survive, but the referenced body loses its tail.
    cut = groups[0].index('R-3-20')
    trace = chat.smeta_evidence_delivery_trace(queries, chunks,
        groups[0][:cut] + '\n\n' + groups[1])
    for row in trace['cards']:
        assert row['body_delivered_complete'] is False
        assert row['resources']['delivered_items'] < 33
        assert row['resource_set_complete'] is False
    # A lone alias without its body supplies no resources at all.
    trace = chat.smeta_evidence_delivery_trace(queries, chunks, groups[1])
    assert trace['cards'][1]['resources']['delivered_items'] == 0
    assert trace['cards'][1]['body_delivered_complete'] is False
    # Text quoted outside the evidence body cannot fill in its missing tail.
    trace = chat.smeta_evidence_delivery_trace(queries, chunks,
        groups[0][:cut] + '\nUser question quotes resources:\n' + hit.content)
    assert trace['cards'][0]['resources']['delivered_items'] < 33


def test_preview_delivery_does_not_claim_full_database_resources(norm_base, monkeypatch):
    monkeypatch.setattr(research, 'norm_table_variants', lambda _code: ())
    card = _code_listing('ГЭСНм', '12-07-001', base_path=norm_base)[0]
    hit = chat._PracticeChunk(card)
    queries = [('query', [hit])]
    groups, chunks = chat.build_model_rag_evidence_groups(queries, max_chars=12000, hits_per_query=6)
    trace = chat.smeta_evidence_delivery_trace(queries, chunks, '\n'.join(groups))
    row, = trace['cards']
    assert row['body_delivered_complete'] is True
    assert row['resources']['delivered_items'] == 16
    assert row['resource_set_complete'] is False
    assert row['work_steps']['delivered_items'] == 12
    # Duplicate resource text needs two occurrences, not one substring match.
    card['resource_preview'].append(dict(card['resource_preview'][0]))
    duplicate = chat._PracticeChunk(card)
    q2 = [('query', [duplicate])]
    g2, c2 = chat.build_model_rag_evidence_groups(q2, max_chars=12000, hits_per_query=6)
    resource_text = research.smeta_resource_texts(card)[-1][1]
    last = g2[0].rfind(resource_text)
    row, = chat.smeta_evidence_delivery_trace(q2, c2, g2[0][:last])['cards']
    assert row['resources']['source_items'] == 17
    assert row['resources']['delivered_items'] == 16


def test_source_rendering_loss_is_distinct_from_packing_loss(norm_base, monkeypatch):
    monkeypatch.setattr(research, 'norm_table_variants', lambda _code: ())
    card = _code_listing('ГЭСНм', '12-07-001', base_path=norm_base)[0]
    card['work_steps'] = ['Long operation ' * 500, 'Resource 1/2']
    hit = chat._PracticeChunk(card)
    queries = [('query', [hit])]
    groups, chunks = chat.build_model_rag_evidence_groups(queries, max_chars=24000, hits_per_query=6)
    row, = chat.smeta_evidence_delivery_trace(queries, chunks, '\n'.join(groups))['cards']
    assert row['body_delivered_complete'] is True  # Complete preview, not complete work list.
    assert row['work_steps']['source_items'] == 2
    assert row['work_steps']['rendered_items'] == 0
    assert row['work_steps']['delivered_items'] == 0


def test_governor_omission_is_visible_in_final_delivery_trace(norm_base, monkeypatch):
    from proxy.services.model_execution_preset_service import ModelExecutionPreset
    monkeypatch.setattr(research, 'norm_table_variants', lambda _code: ())
    card, = _code_listing('ГЭСНм', '12-07-001-03', base_path=norm_base)
    hit = chat._PracticeChunk(card)
    queries = [('query', [hit])]
    groups, chunks = chat.build_model_rag_evidence_groups(queries, max_chars=12000, hits_per_query=6)
    for budget in (700, 12000):
        preset = ModelExecutionPreset('audit', 'fixture', budget, 0, 0, 3, 5, 5, 1, False, ('test',))
        messages, packet = chat.govern_inference_messages(
            preset=preset, profile_prefix='Estimator', request_payload='Original attachment remains', evidence=groups)
        sent = '\n'.join(m['content'] for m in messages)
        assert 'Original attachment remains' in sent
        row, = chat.smeta_evidence_delivery_trace(queries, chunks, sent)['cards']
        assert row['resources']['packed_items'] == 33
        assert row['resources']['delivered_items'] == (0 if budget == 700 else 33)
        assert bool(packet.omissions) is (budget == 700)


@pytest.mark.parametrize('full_read', [False, True])
def test_official_table_heading_and_operations_reach_final_messages(norm_base, monkeypatch, full_read):
    from proxy.services.model_execution_preset_service import ModelExecutionPreset
    monkeypatch.setattr(research, 'norm_table_variants', lambda _code: ())
    code = '12-07-001-03' if full_read else '12-07-001'
    card = _code_listing('ГЭСНм', code, base_path=norm_base)[0]
    heading = 'Таблица 12-07-001 Монтаж испытательных устройств'
    # A preserved historical card also carries the literal hierarchy in source_ref.
    card['source_ref'] = 'Сборник 12<br>Раздел 07 Испытания<br>' + heading + '#guid=fixture'
    card.pop('table_heading', None)
    hit = chat._PracticeChunk(card)
    groups, _ = chat.build_model_rag_evidence_groups([('literal model query', [hit])],
        max_chars=24000, hits_per_query=6)
    preset = ModelExecutionPreset('audit', 'fixture', 12000, 0, 0, 3, 5, 5, 1, False, ('test',))
    messages, packet = chat.govern_inference_messages(preset=preset, profile_prefix='Estimator',
        request_payload='Original attachment remains', evidence=groups)
    sent = '\n'.join(message['content'] for message in messages)
    assert heading in sent
    assert 'Раздел 07 Испытания' in sent
    assert card['work_steps'][0] in sent
    assert 'literal model query' in sent
    assert 'Original attachment remains' in sent
    assert not packet.omissions


def test_missing_official_table_heading_is_not_invented():
    rendered = research.smeta_card_header({'norm_code': 'ГЭСНм12-07-001-03',
        'title': 'Variant title', 'source_ref': 'document#guid=fixture'})
    assert 'Таблица' not in rendered
    assert 'Variant title' in rendered
