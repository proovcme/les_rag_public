from copy import deepcopy
from types import SimpleNamespace

from proxy.services import chat_evidence_application_service as chat
from proxy.services.portion_cursor_service import PortionCursorService

CODE = 'ГЭСН11-01-038-05'
OTHER = 'ГЭСН11-01-038-02'


def saved():
    return {'S!1': {'source_row': 'S!1', 'work_id': 'w1', 'norm_code': CODE,
                     'evidence_snapshot': [{'ref': 'Q1.H1', 'norm_code': CODE,
                                            'delivered': True, 'sent_text': 'Шифр: ' + CODE,
                                            'sent_sha256': 'proof', 'source_meta': {'norm_id': 'id'}}]}}


def test_reused_evidence_cannot_bypass_ambiguity_or_cross_operations():
    proof = chat.saved_norm_evidence(saved())
    rows = [dict(source_row='S!1', work_id='w1', norm_code=f'{CODE} (аналог {OTHER})'),
            dict(source_row='S!1', work_id='w2', norm_code=CODE),
            dict(source_row='S!2', work_id='w1', norm_code=CODE),
            dict(source_row='S!1', work_id='w1', norm_code=CODE)]
    original = deepcopy(rows)
    result = chat.withhold_unreferenced_norms(rows, delivered_cards={}, prior_evidence=proof)
    assert rows == original
    assert [r.get('evidence_error') for r in result] == [
        'ambiguous_norm_code', 'missing_evidence_ref', 'missing_evidence_ref', None]
    assert result[-1]['evidence_snapshot'] == saved()['S!1']['evidence_snapshot']


def test_calculation_and_old_unverified_snapshots_are_not_delivery_proof():
    old = saved()
    old['S!1']['evidence_snapshot'][0].pop('delivered')
    old['S!1']['calculation_receipts'] = [dict(source_row='S!1', work_id='w1',
        status='bound', calculation={'norm_code': CODE})]
    assert chat.saved_norm_evidence(old) == []


def test_snapshot_records_actual_delivery_for_future_operation_reuse():
    chunk = SimpleNamespace(content='Шифр: ' + CODE, meta={'norm_code': CODE,
        'model_evidence_ref': 'Q1.H1'}, doc_name='norms', doc_id='n1', score=1)
    row = dict(source_row='S!1', work_id='w1', norm_code=CODE, evidence_refs=['Q1.H1'])
    assert chat.evidence_snapshot([row], [chunk], delivered_cards={})['S!1'][0]['delivered'] is False
    assert chat.evidence_snapshot([row], [chunk], delivered_cards={'Q1.H1': CODE})['S!1'][0]['delivered'] is True


def test_new_book_reopens_old_operation_not_in_the_current_portion(tmp_path):
    cursors = PortionCursorService(tmp_path / 'progress.db')
    old = dict(source_row='S!1', work_id='old', norm_code=CODE, quantity=1, unit='шт')
    cursors.record_pass(session_id='s', source_revision='r', completed={'S!1': old}, decisions={'S!1': old})
    new = dict(source_row='S!2', work_id='new', norm_code=CODE, quantity=1, unit='шт')
    receipt = dict(source_row='S!1', work_id='old', status='resource_review_required', calculation_ref='newhash')
    trace = {}
    chat.record_portion_pass(cursors, session_id='s',
        portion_state={'shown': ['S!2'], 'source_revision': 'r', 'prior_decisions': {'S!1': old}},
        rows=[new], closed=['S!2'], artifact_revision_id='new-book',
        row_statuses={'S!1': 'resource_review_required', 'S!2': 'bound'}, calculation_receipts=[receipt], trace=trace)
    progress = cursors.progress(session_id='s', source_revision='r')
    assert progress.completed == frozenset({'S!2'})
    assert progress.decisions['S!1']['norm_code'] == CODE
    assert progress.decisions['S!1']['calculation_receipts'] == [receipt]
    assert trace['smeta_portion_decided'] == 1


def test_deferred_query_notice_reaches_final_packet_even_with_full_retrieval_coverage():
    from proxy.services.context_governor_service import ContextGovernor, ContextCandidate, ContextKind, ContextObject
    plan = chat.plan_model_rag_queries([f'query {i}' for i in range(12)], rows_in_pass=2, truncated=True)
    fixed = chat.selector_evidence_payload(attachment_context='S!1 work', rendered_context='', query_plan=plan)
    evidence = chat.answer_evidence_blocks(fixed_blocks=fixed, group_blocks=['Q1 result'],
                                          coverage={'complete': True})
    preset = SimpleNamespace(input_token_limit=10000, generation_reserve_tokens=0,
                             safety_reserve_tokens=0, preset_id='offline')
    packet = ContextGovernor(preset).pack([ContextCandidate(kind=ContextKind.EVIDENCE,
        objects=tuple(ContextObject(str(i), s) for i,s in enumerate(evidence)))])
    sent = '\n'.join(m['content'] for m in packet.as_messages())
    assert '[ЗАПРОСЫ]' in sent and '8 из 12' in sent and 'query 8' in sent


def test_truncated_short_list_is_not_presented_as_complete():
    plan = chat.plan_model_rag_queries(['query'], rows_in_pass=2, truncated=True)
    assert 'оборван' in chat.model_rag_query_plan_note(plan)


def test_legacy_book_is_rebuilt_after_calculation_contract_upgrade():
    import hashlib
    import json
    from proxy.services.portion_cursor_service import canonical_decision
    row = dict(source_row='S!1', work_id='w1', norm_code=CODE, quantity=1, unit='шт')
    legacy = hashlib.sha256(json.dumps([canonical_decision(row)], ensure_ascii=False,
                                      sort_keys=True, default=str).encode('utf-8')).hexdigest()[:32]
    state = dict(prior_decisions={'S!1': row}, artifact_decisions_revision=legacy,
                 artifact_revision_id='old-book')
    assert chat.stored_decisions_need_a_workbook(state)
    state['artifact_decisions_revision'] = chat._portion_decisions_revision(state['prior_decisions'])
    assert not chat.stored_decisions_need_a_workbook(state)
