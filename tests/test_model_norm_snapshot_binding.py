"""The application binds calculation to the shown immutable normative generation."""
from copy import deepcopy
from types import SimpleNamespace

from proxy.services import chat_evidence_application_service as service

CODE = 'ГЭСНм08-02-409-01'
KEY = 'ГЭСНм:08-02-409-01'


def card(ref='Q1.H1', identity='card-one', *, sha='a' * 64, code=CODE, key=KEY):
    meta = {'model_evidence_ref': ref, 'global_evidence_id': identity,
            'norm_code': code, 'norm_key': key, 'model_delivery_status': 'delivered',
            'body_status': 'full'}
    if sha is not None:
        meta['normative_base_sha256'] = sha
    return SimpleNamespace(content=f'Шифр: {code}\nLiteral conditions',
                           doc_name='normative cards', score=1., meta=meta)


def authored(refs=None, code=CODE):
    return {'source_row': 'S!R2', 'row_role': 'work', 'title': 'Authored operation',
            'unit': 'м', 'quantity': 17, 'norm_code': code,
            'norm_status': 'ANALOGUE_CANDIDATE', 'coverage': 'Authored candidate only',
            'evidence_refs': refs or ['Q1.H1']}


def test_first_binding_records_exact_snapshot_without_promoting_model_choice():
    row = authored()
    before = deepcopy(row)
    bound = service.bind_row_evidence_ids([row], [card()], binding_phase='first')[0]
    assert bound['_evidence_check']['normative_base_sha256'] == 'a' * 64
    assert bound['_evidence_check']['norm_key'] == KEY
    assert row == before
    assert all(bound[key] == value for key, value in before.items())


def test_first_binding_discards_a_model_supplied_generation_claim():
    row = authored()
    row['_evidence_check'] = {'normative_base_sha256': 'b' * 64, 'norm_key': KEY}
    bound = service.bind_row_evidence_ids([row], [card()], binding_phase='first')[0]
    assert bound['_evidence_check']['normative_base_sha256'] == 'a' * 64


def test_conflicting_cited_generations_remain_an_explicit_conflict():
    row = authored(['Q1.H1', 'Q2.H1'])
    bound = service.bind_row_evidence_ids([row], [card(), card('Q2.H1', 'card-two', sha='b' * 64)],
                                         binding_phase='first')[0]
    assert bound['_evidence_check']['normative_snapshot_conflict'] is True
    assert bound['norm_code'] == CODE and bound['norm_status'] == row['norm_status']


def test_replay_cannot_rebind_an_old_norm_to_a_new_generation():
    row = service.bind_row_evidence_ids([authored()], [card()], binding_phase='first')[0]
    replay = service.bind_row_evidence_ids([row], [card(sha='b' * 64)], binding_phase='replay')[0]
    assert replay['_evidence_check']['normative_snapshot_conflict'] is True
    assert row['_evidence_check']['normative_base_sha256'] == 'a' * 64


def test_unknown_or_wrong_family_evidence_does_not_create_snapshot_proof():
    for chunk in (card(sha=None), card(code='ГЭСН08-02-409-01', key='ГЭСН:08-02-409-01'),
                  card(sha='not-a-digest')):
        bound = service.bind_row_evidence_ids([authored()], [chunk], binding_phase='first')[0]
        assert 'normative_base_sha256' not in bound['_evidence_check']


def test_unissued_alias_stays_unissued_even_if_future_frame_shows_snapshot():
    row = service.bind_row_evidence_ids([authored(['Q2.H1'])], [card()], binding_phase='first')[0]
    replay = service.bind_row_evidence_ids([row], [card('Q2.H1', 'later-card')], binding_phase='replay')[0]
    assert replay['evidence_bindings'] == {}
    assert 'normative_base_sha256' not in replay['_evidence_check']


def test_same_snapshot_under_two_aliases_is_not_a_conflict():
    bound = service.bind_row_evidence_ids([authored(['Q1.H1', 'Q2.H1'])],
                                         [card(), card('Q2.H1', 'card-two')], binding_phase='first')[0]
    assert bound['_evidence_check']['normative_base_sha256'] == 'a' * 64
    assert not bound['_evidence_check'].get('normative_snapshot_conflict')
