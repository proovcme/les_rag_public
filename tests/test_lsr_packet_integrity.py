from types import SimpleNamespace
from proxy.services.chat_evidence_application_service import adaptive_row_packet, sheet_pass_keep_rows
from proxy.services.chat_evidence_application_service import structurally_complete_source_keys


def test_small_output_budget_produces_small_packets():
    rows = [f'S!R{i}' for i in range(1, 30)]
    assert adaptive_row_packet(rows, generation_reserve_tokens=1200) == rows[:3]
    assert adaptive_row_packet(rows, generation_reserve_tokens=4096) == rows[:12]
    assert adaptive_row_packet(rows, generation_reserve_tokens=100) == rows[:1]


def test_partial_locator_never_becomes_a_saved_decision():
    catalog = SimpleNamespace(lookup=lambda key: SimpleNamespace(sheet='S') if key == 'S!R1' else None)
    complete = {'source_row': 'S!R1', 'row_role': 'work', 'norm_code': 'MISSING'}
    rows = [complete, {'source_row': 'S'}, {'source_row': 'S!R999'}]
    assert sheet_pass_keep_rows(rows, sheet='S', catalog=catalog, errors=[]) == [complete]
    assert len(rows) == 3


def test_broken_links_remain_pending_without_changing_model_norm():
    catalog = SimpleNamespace(work_locators=lambda: ['S!R1', 'S!R2'], lookup=lambda key: None)
    rows = [
        {'source_row': 'S!R1', 'row_role': 'work', 'work_row': 'R1', 'norm_code': 'MISSING'},
        {'source_row': 'S!R2', 'row_role': 'resource', 'work_row': 'Other!R9'},
    ]
    complete = structurally_complete_source_keys(rows, catalog)
    assert complete == {'S!R1'}
    assert complete - structurally_complete_source_keys([], catalog) == {'S!R1'}
    assert rows[0]['norm_code'] == 'MISSING'


def test_material_self_links_never_close_packets_including_large_sources():
    locators = [f'S!R{i}' for i in range(1, 102)]
    catalog = SimpleNamespace(work_locators=lambda: locators, lookup=lambda key: None)
    rows = [
        {'source_row': key, 'row_role': 'material', 'work_row': key}
        for key in locators
    ]
    assert structurally_complete_source_keys(rows, catalog) == set()
    # The model may resolve the relation in a later result; code only checks it.
    rows[0] = {'source_row': 'S!R1', 'row_role': 'work', 'norm_code': 'MISSING'}
    rows[1]['work_row'] = 'R1'
    assert structurally_complete_source_keys(rows, catalog) == {'S!R1', 'S!R2'}
