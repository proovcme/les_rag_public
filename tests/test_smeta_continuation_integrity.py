"""Unresolved rows remain reachable; calculation review is visible and consistent."""
from proxy.services import chat_evidence_application_service as chat
from proxy.services.portion_cursor_service import PortionCursorService
from proxy.services.portion_plan_service import portion_plan


TEXT='Файл: fixture.xlsx\nS!R1: № | Наименование | Ед. изм | Количество\n'+''.join(
    f'S!R{n+1}: {n} | Item {n} | шт | 1\n' for n in range(1,7))


def test_attempt_count_never_excludes_unresolved_rows(tmp_path):
    store=PortionCursorService(tmp_path/'cursor.db')
    for turn in range(4):
        body,state=chat.smeta_portion_context(TEXT,session_id='s',limit=6,cursors=store)
        assert len(state['shown'])==6
        assert not state['complete']
        decisions=[dict(source_row=anchor,norm_code='',coverage='Evidence insufficient') for anchor in state['shown']]
        chat.record_portion_pass(store,session_id='s',portion_state=state,rows=decisions,closed=[],
            artifact_revision_id=None,pass_id=f'turn{turn}')
    progress=store.progress(session_id='s',source_revision=state['source_revision'])
    assert not progress.completed
    assert not progress.settled
    assert all(value==4 for value in progress.attempts.values())


def test_retry_priority_rotates_without_losing_source_context(tmp_path):
    store=PortionCursorService(tmp_path/'cursor.db')
    seen=[]
    for turn in range(10):
        body,state=chat.smeta_portion_context(TEXT,session_id='s',limit=2,cursors=store)
        assert len(state['shown'])==2
        for anchor in state['shown']:
            assert 'Item '+anchor.split('!')[1] in body
        seen.extend(state['shown'])
        decisions=[dict(source_row=anchor,norm_code='',coverage='Evidence insufficient') for anchor in state['shown']]
        chat.record_portion_pass(store,session_id='s',portion_state=state,rows=decisions,closed=[],
            artifact_revision_id=None,pass_id=f'turn{turn}')
    assert set(seen)=={f'S!{n}' for n in range(1,7)}
    assert min(seen.count(f'S!{n}') for n in range(1,7))>=3


def test_review_pending_counts_and_xlsx_expose_receipt(tmp_path):
    from proxy.smeta_core.calculation_receipt import apply_model_review,calculation_receipts
    from proxy.services.rim_lsr_trace_service import build_lsr_trace
    from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx
    import openpyxl
    trace=build_lsr_trace([dict(code='',name='Fixture',source_row='S!1',work_id='w1',unit='шт',qty=2,
                               nr_pct=0,sp_pct=0,resources=[])])
    trace['row_bindings']=[dict(row='S!1',work_id='w1',status='bound')]
    trace['summary'].update(source_rows=1,bound_rows=1,bound_operations=1,unbound_rows=0,unbound_operations=0)
    receipts=calculation_receipts(trace)
    apply_model_review(trace,receipts,[dict(source_row='S!1',work_id='w1')])
    assert trace['summary']['bound_operations']==0
    assert trace['summary']['unbound_rows']==1
    assert trace['summary']['unbound_operations']==1
    out=tmp_path/'review.xlsx';render_lsr_xlsx(trace,out)
    wb=openpyxl.load_workbook(out)
    try:
        assert receipts[0]['calculation_ref'] in str(wb['Проверка'].cell(2,8).value)
    finally:
        wb.close()


def test_matching_decisions_with_unavailable_file_still_require_rebuild():
    from proxy.services.portion_cursor_service import decisions_revision
    decisions={'S!1':dict(source_row='S!1',norm_code='MODEL',quantity=1,unit='шт')}
    state=dict(prior_decisions=decisions,artifact_revision_id='rev1',
               artifact_decisions_revision=decisions_revision(decisions))
    seen=[]
    def missing(revision):
        seen.append(revision)
        return False
    assert chat.stored_decisions_need_a_workbook(state,artifact_available=missing)
    assert seen==['rev1']
    assert not chat.stored_decisions_need_a_workbook(state,artifact_available=lambda _:True)
