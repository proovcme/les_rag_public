"""Exact model resource choices survive real SQLite, calculation, receipt and XLSX."""
from copy import deepcopy
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import openpyxl
import pandas as pd
import pytest

from proxy.services import gesn_service as gs, rim_lsr_trace_service as rim
from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx
from proxy.smeta_core.calculation_receipt import calculation_receipts
from tools.build_smeta_structured_base import build_structured_base
from tools.gesn_import import RESOURCE_FIELDS

CODE = 'ГЭСН01-01-001-01'


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    gs.load_base_norms.cache_clear()
    gs.load_structured_base_norms.cache_clear()
    monkeypatch.setattr(rim.nr_sp_service, 'resolve', lambda *a, **k:
                        dict(status='resolved_fixture', nr_pct=0, sp_pct=0))
    yield
    gs.load_base_norms.cache_clear()
    gs.load_structured_base_norms.cache_clear()


def setup_rows(tmp_path, monkeypatch, *, prices=(10, 20), code='R1', name='Synthetic', consumption=1, kind='material'):
    rows = []
    for price in prices:
        row = dict.fromkeys(RESOURCE_FIELDS)
        row.update(norm_code=CODE, base_type='ГЭСН', norm_key='ГЭСН:01-01-001-01',
            norm_name='Synthetic installation', norm_unit='шт', kind=kind,
            resource_code=code, resource_name=name or 'placeholder', resource_unit='шт',
            per_unit=consumption, price=price, source_doc='synthetic', source_guid='synthetic',
            work_steps=json.dumps(['Synthetic operation']))
        rows.append(row)
    source, base = tmp_path/'source.parquet', tmp_path/'base.sqlite'
    pd.DataFrame(rows, columns=list(RESOURCE_FIELDS)).to_parquet(source, index=False)
    build_structured_base(source=source, out=base, manifest_out=tmp_path/'manifest.json', edition='synthetic')
    with sqlite3.connect(base) as conn:
        if not name:
            conn.execute("UPDATE resources SET resource_name='' ")
        if len(prices) > 1 and len(set(prices)) == 1:
            # Importer collapses exact source duplicates. Recreate a legacy base
            # carrying both genuine SQL rows to exercise the reader contract.
            columns = ','.join(r[1] for r in conn.execute('PRAGMA table_info(resources)') if r[1] != 'id')
            conn.execute(f'INSERT INTO resources ({columns}) SELECT {columns} FROM resources LIMIT 1')
        norm_id, norm_key, edition, base_type = conn.execute(
            'SELECT norm_id,norm_key,edition,base_type FROM norms').fetchone()
        ids = [str(row[0]) for row in conn.execute('SELECT id FROM resources ORDER BY id')]
    conn.close()
    identity = dict(schema='les.norm-revision.v1', base_sha256=hashlib.sha256(base.read_bytes()).hexdigest(),
                    norm_id=norm_id, norm_key=norm_key, edition=edition, base_type=base_type)
    monkeypatch.setenv('LES_SMETA_STRUCTURED_BASE', str(base))
    parent = dict(source_row='Synthetic!1', work_id='mount', title='Synthetic installation',
        norm_code=CODE, quantity=2, unit='шт', normative_identity_status='pinned', normative_identity=identity,
        resource_delivery_proof=dict(normative_identity=identity, rows=[dict(source_resource_id=i,
            ref='Q1.H1', sha256='a'*64, packet_sha256='b'*64) for i in ids], groups=[]))
    action = dict(source_row='Synthetic!2', work_id='remove', title='Explicit synthetic removal',
        quantity=2, unit='шт', decision_kind='ресурс', included_in='mount', resource_action='excluded',
        target_resource_code=code, target_resource_id='row:'+ids[-1],
        replaced_by='not_required', coverage='Explicit synthetic model decision')
    return parent, action, ids


def test_price10_price20_selects_second_only_and_preserves_receipt_xlsx(tmp_path, monkeypatch):
    parent, action, ids = setup_rows(tmp_path, monkeypatch)
    original = deepcopy([parent, action])
    trace = rim.build_lsr_trace_from_visible_rows([parent, action])
    assert trace['row_bindings'][1]['status'] == 'resource_excluded'
    assert trace['summary']['known_amount'] == 20
    assert [parent, action] == original
    work, removed = calculation_receipts(trace)
    resources = work['calculation']['resources']
    assert [r['known_cost'] for r in resources] == [20, 0]
    assert [r['source_resource_ids'] for r in resources] == [[ids[0]], [ids[1]]]
    allocation, = removed['resource_bindings']
    assert allocation['target_resource_id'] == action['target_resource_id']
    assert allocation['parent_resource_quantity'] == 0
    assert allocation['excluded_quantity'] == 2
    target = tmp_path/'exact.xlsx'
    render_lsr_xlsx(trace, target)
    book = openpyxl.load_workbook(target)
    comments = '\n'.join(c.comment.text for s in book for row in s for c in row if c.comment)
    assert action['target_resource_id'] in comments
    assert parent['normative_identity']['base_sha256'] in comments
    assert action['target_resource_id'] in '\n'.join(str(c.value or '') for row in book['Проверка'] for c in row)
    book.close()


@pytest.mark.parametrize('code,name', [('', 'Synthetic'), ('R1', '')])
def test_exact_code_less_or_empty_name_is_not_fallback(tmp_path, monkeypatch, code, name):
    parent, action, _ = setup_rows(tmp_path, monkeypatch, code=code, name=name)
    trace = rim.build_lsr_trace_from_visible_rows([parent, action])
    assert trace['row_bindings'][1]['status'] == 'resource_excluded'
    assert trace['summary']['known_amount'] == 20


@pytest.mark.parametrize('change,status', [
    ({'target_resource_id':'row:99999'}, 'resource_target_missing'),
    ({'target_resource_code':'WRONG'}, 'resource_target_code_conflict'),
])
def test_invalid_exact_target_never_uses_code_fallback(tmp_path, monkeypatch, change, status):
    parent, action, _ = setup_rows(tmp_path, monkeypatch)
    action.update(change)
    trace = rim.build_lsr_trace_from_visible_rows([parent, action])
    assert trace['row_bindings'][1]['status'] == status
    assert trace['summary']['known_amount'] == 60


@pytest.mark.parametrize('missing', ['all', 'selected', 'revision'])
def test_selected_resource_must_be_proven_delivered(tmp_path, monkeypatch, missing):
    parent, action, _ = setup_rows(tmp_path, monkeypatch)
    if missing == 'all':
        parent.pop('resource_delivery_proof')
    elif missing == 'selected':
        parent['resource_delivery_proof']['rows'].pop()
    else:
        parent['resource_delivery_proof']['normative_identity'] = {'base_sha256':'wrong'}
    trace = rim.build_lsr_trace_from_visible_rows([parent, action])
    assert trace['row_bindings'][1]['status'] == 'target_resource_not_proven_delivered'
    assert trace['summary']['known_amount'] == 60


def test_same_code_allocations_have_independent_counters_and_costs(tmp_path, monkeypatch):
    parent, action, ids = setup_rows(tmp_path, monkeypatch)
    action.update(resource_action='included')
    first = dict(action, work_id='first', target_resource_id='row:'+ids[0])
    trace = rim.build_lsr_trace_from_visible_rows([parent, first, action])
    assert [b['status'] for b in trace['row_bindings'][1:]] == ['resource_bound', 'resource_bound']
    assert trace['summary']['known_amount'] == 60
    receipts = calculation_receipts(trace)
    assert [r['resource_bindings'][0]['allocated_known_cost'] for r in receipts[1:]] == [20, 40]


def test_duplicate_exclusion_is_not_applied_twice(tmp_path, monkeypatch):
    parent, action, _ = setup_rows(tmp_path, monkeypatch)
    trace = rim.build_lsr_trace_from_visible_rows([parent, action, dict(action, work_id='duplicate')])
    assert [b['status'] for b in trace['row_bindings'][1:]] == ['resource_excluded', 'resource_action_conflict']
    assert trace['summary']['known_amount'] == 20


@pytest.mark.parametrize('selector', ['row', 'legacy', 'group', 'undelivered_group'])
def test_deduplicated_group_requires_explicit_complete_group_scope(tmp_path, monkeypatch, selector):
    parent, action, ids = setup_rows(tmp_path, monkeypatch, prices=(10, 10))
    norm = gs.get_norm(CODE)
    resource, = norm['resources']
    assert resource['source_resource_ids'] == ids
    group = resource['source_resource_group_id']
    parent['resource_delivery_proof']['groups'] = [dict(source_resource_group_id=group,
        source_resource_ids=ids, ref='Q1.H1', sha256='c'*64, packet_sha256='b'*64)]
    if selector == 'legacy':
        action.pop('target_resource_id')
    elif selector in {'group', 'undelivered_group'}:
        action['target_resource_id'] = group
    if selector == 'undelivered_group':
        parent['resource_delivery_proof']['rows'].pop()
    trace = rim.build_lsr_trace_from_visible_rows([parent, action])
    expected = ('resource_excluded' if selector == 'group' else
        'target_resource_not_proven_delivered' if selector == 'undelivered_group' else 'resource_group_scope_required')
    assert trace['row_bindings'][1]['status'] == expected
    assert trace['summary']['known_amount'] == (0 if selector == 'group' else 20)


def test_unknown_consumption_preserved_when_exact_resource_excluded(tmp_path, monkeypatch):
    parent, action, _ = setup_rows(tmp_path, monkeypatch, consumption=None)
    trace = rim.build_lsr_trace_from_visible_rows([parent, action])
    assert trace['row_bindings'][1]['status'] == 'resource_excluded'
    receipt = calculation_receipts(trace)[1]
    assert receipt['resource_bindings'][0]['excluded_quantity'] is None
    assert receipt['resource_bindings'][0]['parent_resource_known_cost'] == 0
    assert trace['summary']['full_amount'] is None  # Other unknown row remains.


def test_exact_labor_target_is_not_permitted_even_with_same_material_code(tmp_path, monkeypatch):
    parent, action, _ = setup_rows(tmp_path, monkeypatch, kind='labor')
    trace = rim.build_lsr_trace_from_visible_rows([parent, action])
    assert trace['row_bindings'][1]['status'] == 'resource_action_not_allowed'
    assert trace['summary']['known_amount'] == 60


def test_machine_excluded_quantity_uses_machine_coefficient(tmp_path, monkeypatch):
    parent, action, _ = setup_rows(tmp_path, monkeypatch, kind='machine')
    parent.update(coefficient=3, coefficient_target='machines', coefficient_basis='Synthetic explicit basis')
    trace = rim.build_lsr_trace_from_visible_rows([parent, action])
    assert trace['row_bindings'][1]['status'] == 'resource_excluded'
    receipt = calculation_receipts(trace)[1]
    assert receipt['resource_bindings'][0]['excluded_quantity'] == 6
    assert trace['summary']['known_amount'] == 60


def test_actual_card_parser_cursor_restart_calculation_and_book(tmp_path, monkeypatch):
    from proxy.smeta_core import norm_browser
    from proxy.services import model_research_tool_service as research
    from proxy.services import chat_evidence_application_service as chat
    from proxy.services.portion_cursor_service import PortionCursorService
    parent, action, ids = setup_rows(tmp_path, monkeypatch, code='01.1.01.01-0001')
    card, = norm_browser._code_listing('ГЭСН', '01-01-001-01', base_path=tmp_path/'base.sqlite')
    body = research.smeta_card_text(card)
    metadata = research.smeta_card_delivery_metadata(card, body)
    metadata.update(model_evidence_ref='Q1.H1', norm_code=CODE, normative_identity=card['normative_identity'])
    chunk = SimpleNamespace(content=body, meta=metadata)
    packet = '[Q1.H1 | synthetic]:\n' + body
    # Full text is parsed just like a model-authored response, with no proof supplied by it.
    fields = ('source_row','work_id','title','unit','quantity','norm_code','decision_kind','included_in',
              'resource_action','target_resource_id','target_resource_code','replaced_by','coverage','evidence_refs')
    parent['evidence_refs']='Q1.H1'
    raw = '| '+' | '.join(fields)+' |\n|'+ '|'.join('---' for _ in fields)+'|\n'
    raw += '\n'.join('| '+' | '.join(str(row.get(k,'—')) for k in fields)+' |' for row in (parent,action))
    _, parsed = chat.parse_model_rag_result(raw)
    bound = chat.bind_normative_identity(parsed, chunks=[chunk], delivered_cards={'Q1.H1':CODE}, packet_text=packet)
    assert bound[0]['resource_delivery_proof']['rows'][-1]['source_resource_id'] == ids[-1]
    store = PortionCursorService(tmp_path/'cursor.sqlite')
    decisions = {row['source_row']: row for row in bound}
    store.record_pass(session_id='s', source_revision='r', completed=decisions, decisions=decisions, pass_id='p')
    saved = PortionCursorService(tmp_path/'cursor.sqlite').progress(session_id='s', source_revision='r').decisions
    rebuilt = chat.bind_normative_identity(list(saved.values()), prior_evidence=chat.saved_norm_evidence(saved))
    trace = rim.build_lsr_trace_from_visible_rows(rebuilt)
    assert trace['row_bindings'][1]['status'] == 'resource_excluded', trace['row_bindings'][1]
    assert trace['summary']['known_amount'] == 20
    render_lsr_xlsx(trace, tmp_path/'restarted.xlsx')
    book = openpyxl.load_workbook(tmp_path/'restarted.xlsx')
    assert action['target_resource_id'] in '\n'.join(str(c.value or '') for row in book['Проверка'] for c in row)
    book.close()


def test_exact_replacement_keeps_old_resource_and_new_supply_with_effect(tmp_path, monkeypatch):
    from proxy.services.fgis_price_service import PriceBook
    parent, action, ids = setup_rows(tmp_path, monkeypatch)
    action['replaced_by']='supply'
    supply=dict(source_row=action['source_row'],work_id='supply',title='Explicit new material',
                decision_kind='материал',quantity=2,unit='шт',resource_code='NEW')
    book=PriceBook([dict(code='NEW',unit='шт',price_current=100)])
    trace=rim.build_lsr_trace_from_visible_rows([parent,action,supply],pricebook=book)
    assert [r['status'] for r in trace['row_bindings']]==['bound','resource_excluded','material_bound']
    assert trace['summary']['known_amount']==220
    receipts=calculation_receipts(trace,pricebook=book)
    assert [r['known_cost'] for r in receipts[0]['calculation']['resources']]==[20,0]
    assert receipts[1]['resource_bindings'][0]['source_resource_ids']==[ids[-1]]
    assert receipts[1]['resource_bindings'][0]['replacement_quantity']==2
    assert receipts[2]['calculation']['resources'][0]['known_cost']==200


def test_exact_machine_exclusion_removes_only_selected_crew(tmp_path, monkeypatch):
    from proxy.services import fsem_machinist_service as fsem
    from proxy.services.fgis_price_service import PriceBook
    parent, action, ids=setup_rows(tmp_path,monkeypatch,kind='machine')
    # Add a genuine anonymous aggregate to the synthetic SQL revision, then pin it.
    base=tmp_path/'base.sqlite'
    with sqlite3.connect(base) as conn:
        conn.execute("INSERT INTO resources(parent_norm_id,norm_key,kind,resource_name,resource_unit,per_unit) "
                     "SELECT parent_norm_id,norm_key,'machinist','Aggregate','чел.-ч',2 FROM resources LIMIT 1")
    conn.close()
    parent['normative_identity']['base_sha256']=hashlib.sha256(base.read_bytes()).hexdigest()
    monkeypatch.setattr(fsem,'lookup',lambda *_:dict(crew_hours=1,driver_code='4-100-030',driver_grade=3))
    prices=PriceBook([dict(code='4-100-030',unit='чел.-ч',price_current=5)])
    trace=rim.build_lsr_trace_from_visible_rows([parent,action],pricebook=prices)
    assert trace['row_bindings'][1]['status']=='resource_excluded'
    resources=calculation_receipts(trace,pricebook=prices)[0]['calculation']['resources']
    machines=[r for r in resources if r['kind']=='machine']
    crews=[r for r in resources if r['kind']=='machinist']
    assert [(r['source_resource_ids'],r['known_cost']) for r in machines]==[([ids[0]],20),([ids[1]],0)]
    assert len(crews)==1 and crews[0]['quantity']==2 and crews[0]['known_cost']==10
    assert not crews[0].get('source_resource_ids')  # Derived crew is not a SQL row.
    assert trace['summary']['known_amount']==30
