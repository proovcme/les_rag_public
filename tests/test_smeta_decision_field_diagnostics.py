"""Literal P9.16 field-grammar diagnostic; never guess a missing cell."""
import hashlib
import json
from pathlib import Path
import pytest
from proxy.services import chat_evidence_application_service as chat
from proxy.services.portion_cursor_service import PortionCursorService

FIXTURE = json.loads((Path(__file__).parent/'fixtures/smeta_actual_ar05_width.json').read_text(encoding='utf-8'))

def table(header, rows):
    return header+'\n|'+'|'.join('---' for _ in header.strip()[1:-1].split('|'))+'|\n'+'\n'.join(rows)

def simple(status, *, pad=False):
    fields = ['source_row','work_id','title','unit','quantity','norm_code','evidence_refs','material_review_status','coverage']
    values = ['S!2','ok','Fixture','m2','2','','',status,'Authored reason']
    if pad:
        values = values[:-1]
    return table('| '+' | '.join(fields)+' |',['| '+' | '.join(values)+' |'])

def test_p916_literal_ar05_reports_invalid_status_without_moving_any_cell():
    raw = table(FIXTURE['header'],[FIXTURE['row']])
    parsed = chat.parse_model_rag_result(raw)
    assert parsed is not None
    row = parsed[1][0]
    assert row.get('parse_error') == 'invalid_decision_field'
    assert row['source_row'] == 'АР!1.31'
    assert row['raw_cells'] == FIXTURE['raw_cells']
    assert row['raw_cells_sha256'] == hashlib.sha256(json.dumps(FIXTURE['raw_cells'],ensure_ascii=False,
        separators=(',', ':')).encode('utf-8')).hexdigest()
    assert row['raw_header'] == FIXTURE['raw_header']
    assert row['raw_model_row'] == FIXTURE['row']
    assert row['raw_model_row_sha256'] == FIXTURE['raw_row_sha256']
    assert row['raw_header_sha256'] == FIXTURE['raw_header_sha256']
    diagnostic = row['row_format_diagnostic']
    assert diagnostic['reason'] == 'invalid_decision_field'
    assert diagnostic['invalid_fields'] == ['material_review_status']
    assert diagnostic['observed_width'] == 31 and diagnostic['expected_width'] == 32
    assert diagnostic['trailing_padding_count'] == 1
    assert diagnostic['invalid_values']['material_review_status'] == FIXTURE['raw_cells'][19]
    assert FIXTURE['raw_cells'][10] in row['raw_cells']  # Literal real receipt SHA, not confirmation.
    assert 'material_review_status' not in row and 'resource_review_ref' not in row

@pytest.mark.parametrize('status',['confirmed','not_present','unresolved','rejected','','—','n/a'])
def test_p916_documented_material_status_and_absence_markers_remain_authored(status):
    row = chat.parse_model_rag_result(simple(status,pad=True))[1][0]
    assert not row.get('parse_error')
    if status in {'confirmed','not_present','unresolved','rejected'}:
        assert row['material_review_status'] == status

@pytest.mark.parametrize('status',['Prose instead of a status','Confirmed','keep_all_confirmed','not_required'])
def test_p916_same_width_invalid_status_is_not_claimed_to_be_a_middle_shift(status):
    row = chat.parse_model_rag_result(simple(status))[1][0]
    assert row.get('parse_error') == 'invalid_decision_field'
    d = row['row_format_diagnostic']
    assert d['observed_width'] == d['expected_width'] == 9
    assert d['trailing_padding_count'] == 0
    assert d['invalid_values'] == {'material_review_status':status}
    assert 'missing_cell_index' not in d

def test_p916_literal_bad_row_does_not_block_valid_neighbor():
    neighbor = '| S!2 | valid | Fixture | m2 | 2 | | | самостоятельный материал |'
    raw = table(FIXTURE['header'],[FIXTURE['row'],neighbor])
    rows = chat.parse_model_rag_result(raw)[1]
    assert len(rows) == 2 and rows[0].get('parse_error')
    assert not rows[1].get('parse_error') and rows[1]['work_id'] == 'valid'
    errors = chat.validate_model_rag_result_structure(rows,(),expected_source_rows=2)
    assert errors == ['model_row_format_error:АР!1.31']
    assert chat.blocking_model_rag_result_errors(errors) == []
    from proxy.services.rim_lsr_trace_service import positions_from_visible_lsr_rows
    packaged = positions_from_visible_lsr_rows(rows)
    assert len(packaged['positions']) == 1
    assert packaged['row_bindings'][0]['status'] == 'model_row_format_error'
    assert packaged['row_bindings'][1]['status'] != 'model_row_format_error'

def test_p916_raw_diagnostic_survives_cursor_reopen_and_names_the_invalid_field(tmp_path):
    original = 'Файл: source.xlsx\nАР!R1: № | Наименование | Ед. изм | Количество\nАР!R2: 1.31 | Fixture | м2 | 66.7'
    store = PortionCursorService(tmp_path/'cursor.sqlite')
    _,state = chat.smeta_portion_context(original,session_id='p916',limit=1,cursors=store)
    row = chat.parse_model_rag_result(table(FIXTURE['header'],[FIXTURE['row']]))[1][0]
    assert row.get('parse_error') == 'invalid_decision_field'
    chat.record_portion_pass(store,session_id='p916',portion_state=state,rows=[row],closed=[],
        artifact_revision_id='partial',row_statuses={'АР!1.31':'model_row_format_error'})
    reopened = PortionCursorService(store.db_path)
    text,next_state = chat.smeta_portion_context(original,session_id='p916',limit=1,cursors=reopened)
    assert 'material_review_status' in text and 'Недопустимое значение' in text
    assert 'число ячеек твоей строки не совпало' not in text
    saved = next_state['prior_decisions']['АР!1.31']
    assert saved['raw_model_row_sha256'] == FIXTURE['raw_row_sha256']
    assert saved['raw_cells'] == FIXTURE['raw_cells']
    assert not reopened.progress(session_id='p916',source_revision=state['source_revision']).completed
