"""A source row may have several authored operations, none may disappear."""
import asyncio
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as chat
from proxy.services import rim_lsr_trace_service as rim
from proxy.services.portion_cursor_service import PortionCursorService, decisions_revision


def operations():
    return [dict(source_row='S!1', work_id=op, title=op, quantity=qty, unit='шт',
                 norm_code='ГЭСН01-01-001-01', evidence_refs=['Q1.H1'])
            for op, qty in [('mount', 2), ('terminate', 4)]]


def test_parser_and_structure_keep_authored_operation_ids():
    text = '| source_row | work_id | title | unit | quantity | norm_code | evidence_refs |\n'
    text += '|---|---|---|---|---|---|---|\n'
    for r in operations():
        text += f"| {r['source_row']} | {r['work_id']} | {r['title']} | шт | {r['quantity']} | {r['norm_code']} | Q1.H1 |\n"
    _, rows = chat.parse_model_rag_result(text)
    assert [r['work_id'] for r in rows] == ['mount', 'terminate']
    evidence = [SimpleNamespace(meta={'model_evidence_ref':'Q1.H1','norm_code':rows[0]['norm_code']})]
    assert chat.validate_model_rag_result_structure(rows, evidence, expected_source_rows=1) == []
    rows[1]['work_id'] = 'mount'
    assert 'duplicate_work_id:mount' in chat.validate_model_rag_result_structure(rows, evidence, expected_source_rows=1)


def test_unnamed_duplicate_still_rejected():
    rows = operations()
    del rows[1]['work_id']
    errors = chat.validate_model_rag_result_structure(rows, [], expected_source_rows=1)
    assert 'duplicate_source_row:S!1' in errors


def test_all_operations_survive_cursor_reload_and_rebuild(tmp_path):
    cursors = PortionCursorService(tmp_path/'cursor.sqlite')
    state = {'source_revision':'r', 'shown':['S!1'], 'source_anchors':['S!1']}
    rows = operations()
    chat.record_portion_pass(cursors, session_id='s', portion_state=state, rows=rows,
                             closed=['S!1'], artifact_revision_id=None, row_statuses={'S!1':'bound'})
    saved = cursors.progress(session_id='s', source_revision='r')
    merged = chat.merged_pass_decisions([], closed=[], portion_state={**state,'prior_decisions':saved.decisions})
    assert [r['work_id'] for r in merged] == ['mount','terminate']
    assert decisions_revision(saved.decisions) == decisions_revision(rows)
    changed = [dict(r) for r in rows]
    changed[1]['quantity'] = 40
    assert decisions_revision(changed) != decisions_revision(saved.decisions)


def test_failed_operation_cannot_close_whole_source():
    items = [dict(source_row='S!1',work_id='mount',status='bound'),
             dict(source_row='S!1',work_id='terminate',status='unit_conflict')]
    assert chat.workbook_row_statuses({'workbook_diagnostics':{'row_calculation':items}}) == {'S!1':'unit_conflict'}


def test_trace_and_xlsx_preserve_distinct_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda _: {
        'name':'Synthetic operation', 'unit':'шт', 'resources':[
            {'kind':'material','code':'R1','name':'Fixture material','unit':'шт','per_unit':1,'price':3}],
        'nr_pct':0,'sp_pct':0})
    bound = rim.positions_from_visible_lsr_rows(operations())
    assert [p['work_id'] for p in bound['positions']] == ['mount','terminate']
    assert [b['work_id'] for b in bound['row_bindings']] == ['mount','terminate']
    trace = rim.build_lsr_trace_from_visible_rows(operations())
    assert trace['summary']['bound_rows'] == 1
    assert trace['summary']['bound_operations'] == 2
    assert trace['summary']['unbound_rows'] == 0
    from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx
    import openpyxl
    out = tmp_path/'operations.xlsx'
    render_lsr_xlsx(trace, out)
    wb = openpyxl.load_workbook(out)
    comments = [cell.comment.text for sheet in wb for row in sheet for cell in row if cell.comment]
    assert any('work_id: mount' in text for text in comments)
    assert any('work_id: terminate' in text for text in comments)
    wb.close()


def test_rebuild_passes_all_saved_operations_to_adapter():
    calls = []
    async def executor(call, context, progress):
        calls.append(call)
        return {}
    asyncio.run(chat.rebuild_workbook_from_stored_decisions(executor=executor,
        portion_state={'prior_decisions':{'S!1':{'source_row':'S!1','operations':operations()}}},
        attachment_id='fixture', question='Calculate', context={}, progress=None))
    received = calls[0]['args']['decisions']
    assert [{k: row[k] for k in original} for row, original in zip(received, operations())] == operations()
    assert all(row['normative_identity_status'] == 'unpinned' for row in received)


def test_operation_snapshots_and_repeated_pass_are_lossless(tmp_path):
    cursors = PortionCursorService(tmp_path/'cursor.sqlite')
    rows = operations()
    rows[1]['evidence_refs'] = ['Q2.H1']
    chunks = [SimpleNamespace(content=f'card {i}',doc_name='fixture',score=1,
        meta={'model_evidence_ref':f'Q{i}.H1'}) for i in (1,2)]
    evidence = chat.evidence_snapshot(rows, chunks)
    assert [e['ref'] for e in evidence['S!1']] == ['Q1.H1','Q2.H1']
    kwargs = dict(session_id='s', portion_state={'source_revision':'r','shown':['S!1']},
        rows=rows, closed=['S!1'], artifact_revision_id=None, row_statuses={'S!1':'bound'},
        evidence=evidence, pass_id='same-turn')
    chat.record_portion_pass(cursors, **kwargs)
    chat.record_portion_pass(cursors, **kwargs)
    progress = cursors.progress(session_id='s',source_revision='r')
    assert progress.passes == 1
    saved = progress.decisions['S!1']['operations']
    assert [op['evidence_snapshot'][0]['sent_text'] for op in saved] == ['card 1','card 2']


def test_resource_targets_one_operation_not_ambiguous_source(monkeypatch):
    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda _: {'unit':'шт','resources':[
        {'kind':'material','code':'R1','unit':'шт','per_unit':1}]})
    resource = dict(source_row='S!2',work_id='allocation',title='Material',quantity=3,unit='шт',
        decision_kind='ресурс',included_in='terminate',resource_action='included',target_resource_code='R1')
    bound = rim.positions_from_visible_lsr_rows(operations()+[resource])
    assert bound['row_bindings'][-1]['status'] == 'resource_bound'
    assert bound['row_bindings'][-1]['covered_by_work_id'] == 'terminate'
    resource['included_in'] = 'S!1'
    assert rim.positions_from_visible_lsr_rows(operations()+[resource])['row_bindings'][-1]['status'] == 'resource_parent_ambiguous'


def test_duplicate_ids_cannot_be_calculated(monkeypatch):
    rows = operations()
    rows[1]['work_id'] = 'mount'
    bound = rim.positions_from_visible_lsr_rows(rows)
    assert not bound['positions']
    assert all(b['status'] == 'duplicate_work_id' for b in bound['row_bindings'])


@pytest.mark.parametrize('priced', [True, False])
def test_one_source_work_and_standalone_material_reach_receipts_and_xlsx(tmp_path, monkeypatch, priced):
    """Fixture decisions: installing 200 m and buying 200 m must stay separate."""
    from copy import deepcopy
    import openpyxl
    from proxy.services.fgis_price_service import PriceBook
    from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx
    from proxy.smeta_core.calculation_receipt import calculation_receipts

    monkeypatch.setattr(rim.gesn_service, 'get_norm', lambda _: {
        'name': 'Fixture installation', 'unit': '100 м', 'nr_pct': 0, 'sp_pct': 0,
        'resources': [
            dict(kind='labor', code='L-FIXTURE', name='Fixture labor', unit='чел.-ч', per_unit=2),
            dict(kind='material', code='M-FASTENER', name='Fixture fastener', unit='шт', per_unit=3),
        ],
    })
    prices = [dict(code='L-FIXTURE', unit='чел.-ч', price_current=10),
              dict(code='M-FASTENER', unit='шт', price_current=5)]
    if priced:
        prices.append(dict(code='M-CABLE', unit='м', price_current=7))
    pricebook = PriceBook(prices)
    raw = ('| source_row | work_id | title | unit | quantity | norm_code | decision_kind | resource_code | evidence_refs |\n'
           '|---|---|---|---|---|---|---|---|---|\n'
           '| S!1 | install | Fixture installation | м | 200 | ГЭСН01-01-001-01 | работа | — | Q1.H1 |\n'
           '| S!1 | supply | Fixture cable | м | 200 | — | материал | M-CABLE | |\n')
    _, rows = chat.parse_model_rag_result(raw)
    evidence = [SimpleNamespace(meta={'model_evidence_ref': 'Q1.H1', 'norm_code': 'ГЭСН01-01-001-01'})]
    assert chat.validate_model_rag_result_structure(rows, evidence, expected_source_rows=1) == []
    original = deepcopy(rows)
    trace = rim.build_lsr_trace_from_visible_rows(rows, pricebook=pricebook)
    assert rows == original
    assert trace['summary']['source_rows'] == 1
    assert trace['summary']['positions'] == 2
    assert trace['summary']['work_positions'] == 1
    assert trace['summary']['bound_rows'] == (1 if priced else 0)
    assert trace['summary']['total'] == (1470 if priced else 70)
    receipts = calculation_receipts(trace, pricebook=pricebook)
    assert [r['work_id'] for r in receipts] == ['install', 'supply']
    assert len({r['calculation_ref'] for r in receipts}) == 2
    install, supply = [r['calculation'] for r in receipts]
    assert [(r['code'], r['quantity'], r['known_cost']) for r in install['resources']] == [
        ('L-FIXTURE', 4, 40), ('M-FASTENER', 6, 30)]
    assert [(r['code'], r['quantity'], r['known_cost']) for r in supply['resources']] == [
        ('M-CABLE', 200, 1400 if priced else None)]
    assert supply['summary']['ozp'] == supply['summary']['em'] == 0
    if not priced:
        assert receipts[1]['status'] == 'material_price_missing'
        assert trace['summary']['full_amount'] is None
        assert 'price_missing:M-CABLE' in supply['summary']['completeness_reasons']
    path = tmp_path / f'work-and-material-{priced}.xlsx'
    render_lsr_xlsx(trace, path)
    book = openpyxl.load_workbook(path, data_only=False)
    try:
        all_rows = [r for sheet in book for r in sheet]
        comments = [cell.comment.text for r in all_rows for cell in r if cell.comment]
        assert any('work_id: install' in c for c in comments)
        assert any('work_id: supply' in c for c in comments)
        cable_rows = [r for r in all_rows if len(r)>6 and r[1].value == 'M-CABLE']
        assert len(cable_rows) == 1
        assert cable_rows[0][6].value == 200
        if not priced:
            # Missing price must not turn into a known free supply in the book.
            assert cable_rows[0][9].value is None
            assert cable_rows[0][11].value is None
    finally:
        book.close()
