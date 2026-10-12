from copy import deepcopy

from tools.smeta_practice_comparison import compare_runs, inspect_run


def sample():
    return {'manifest': {'practice_mode': 'both'},
            'registry': [{'source_row': 'S!1'}, {'source_row': 'T!1'}, {'source_row': 'S!2'}],
            'turns': [{'turn_id': 't1', 'final_messages': [{'content': 'Q1.H1 exact normative evidence'}],
                       'evidence': [{'id': 'Q1.H1', 'norm_id': 'edition:N', 'text': 'exact normative evidence', 'origins': ['search', 'similar']},
                                    {'id': 'Q2.H1', 'text': 'undelivered', 'origins': ['frequency']}]}],
            'decisions': [{'source_row': 'S!1', 'work_id': 'w1', 'kind': 'work', 'norm_id': 'edition:N',
                           'norm_code': 'N', 'quantity': 2, 'turn_id': 't1', 'evidence_refs': ['Q1.H1']},
                          {'source_row': 'S!1', 'work_id': 'w2', 'kind': 'work', 'norm_code': 'N',
                           'quantity': 1, 'turn_id': 't1', 'evidence_refs': ['Q2.H1']},
                          {'source_row': 'T!1', 'work_id': 'm1', 'kind': 'material'}],
            'calculation': [{'source_row': 'S!1', 'work_id': 'w1', 'norm_id': 'edition:N', 'quantity': 2, 'status': 'bound'}],
            'xlsx': [{'source_row': 'S!1', 'work_id': 'w1', 'norm_id': 'edition:N', 'quantity': 2, 'cell': 'ЛСР!G12',
                      'price_state': 'formula_uncached'}],
            'audit': [{'source_row': 'S!1', 'operation': 'partial', 'reason': 'second operation lacks proof', 'source': 'independent review'}]}


def test_comparison_keeps_rows_operations_and_unique_norms_separate():
    run = sample(); original = deepcopy(run)
    report = inspect_run(run)
    assert report['counts'] == {'rows': 3, 'decided_rows': 2, 'works': 2, 'materials': 1, 'resource_links': 0, 'unique_norms': 1}
    assert report['operations'][0]['chain_complete'] is True
    assert report['operations'][0]['attribution'] == 'mixed'
    assert report['operations'][1]['shown'] is False
    assert report['rows'][2]['audit']['operation'] == 'unknown'
    assert report['price_states'] == {'formula_uncached': 1}
    assert run == original


def test_same_code_or_wrong_quantity_is_not_exact_calculation_to_book_proof():
    run = sample(); run['xlsx'][0]['norm_id'] = 'other-edition:N'
    assert inspect_run(run)['operations'][0]['chain_complete'] is False
    run['xlsx'][0]['norm_id'] = 'edition:N'; run['xlsx'][0]['quantity'] = 200
    assert inspect_run(run)['operations'][0]['chain_complete'] is False


def test_regression_and_unknown_cannot_be_hidden_by_more_selected_norms():
    a = sample(); b = sample()
    a['audit'][0]['operation'] = 'correct'; b['audit'][0]['operation'] = 'incorrect'
    comparison = compare_runs(a, b)
    assert comparison['worsened'] == ['S!1']
    assert comparison['improved'] == []
    assert comparison['unassessed'] == ['T!1', 'S!2']
    assert comparison['practice_accepted'] is False


def test_duplicate_work_identity_is_rejected_instead_of_overwritten():
    import pytest
    run = sample(); run['decisions'].append(deepcopy(run['decisions'][0]))
    with pytest.raises(ValueError, match='duplicate'):
        inspect_run(run)


def test_missing_audit_source_does_not_turn_an_opinion_into_correctness():
    run = sample(); run['audit'][0] = {'source_row': 'S!1', 'operation': 'correct'}
    assert inspect_run(run)['rows'][0]['audit']['operation'] == 'unknown'


def test_visible_but_different_norm_is_not_selected_norm_evidence():
    run = sample(); run['turns'][0]['evidence'][0]['norm_id'] = 'different:N'
    result = inspect_run(run)['operations'][0]
    assert result['shown'] is True
    assert result['selected_exact_evidence'] is False
    assert result['chain_complete'] is False
