from types import SimpleNamespace
import asyncio
import pytest

from proxy.services import chat_evidence_application_service as chat
from proxy.services.portion_cursor_service import canonical_decision, decisions_revision
from proxy.services.smeta_evidence_delivery_service import card_delivery_metadata


CODE = 'ГЭСН01-01-001-01'


def identity(revision='a'):
    return dict(schema='les.norm-revision.v1', base_sha256=revision*64,
                norm_id='fixture', norm_key='ГЭСН:01-01-001-01', edition='fixture', base_type='ГЭСН')


def row(**kwargs):
    return dict(source_row='S!1', work_id='w', norm_code=CODE, evidence_refs=['Q1.H1'], **kwargs)


def chunk(ref='Q1.H1', revision='a'):
    return SimpleNamespace(meta=dict(model_evidence_ref=ref, norm_code=CODE,
        normative_identity=identity(revision)), content='trusted body', doc_name='cards', doc_id='fixture', score=1)


def bind(rows, chunks=(), delivered=None, prior=()):
    return chat.bind_normative_identity(rows, chunks=chunks,
        delivered_cards=delivered or {}, prior_evidence=prior)


def proof(ref='Q1.H1', work='w', revision='a'):
    return dict(source_row='S!1', work_id=work, norm_code=chat.evidence_code_identity(CODE),
        cards=[dict(ref=ref, norm_code=CODE, delivered=True, sent_text='trusted body',
                    sent_sha256='trusted', source_meta=dict(normative_identity=identity(revision)))])


def test_model_identity_is_replaced_by_delivered_metadata():
    original = row(normative_identity=identity('f'), normative_identity_status='pinned')
    result, = bind([original], [chunk()], {'Q1.H1': CODE})
    assert result['normative_identity'] == identity()
    assert result['normative_identity_status'] == 'pinned'
    assert result['normative_identity_refs'] == ['Q1.H1']
    assert result['evidence_snapshot'][0]['source_meta']['normative_identity'] == identity()
    assert original['normative_identity'] == identity('f')


def test_undelivered_and_wrong_code_cannot_pin():
    for delivered in ({}, {'Q1.H1': 'ГЭСН02-01-001-01'}):
        result, = bind([row(normative_identity=identity())], [chunk()], delivered)
        assert result['normative_identity'] is None
        assert result['normative_identity_status'] == 'unpinned'


def test_undelivered_current_local_ref_cannot_inherit_old_pin():
    result, = bind([row()], [chunk(revision='b')], {}, [proof()])
    assert result['normative_identity_status'] == 'unpinned'
    assert result['normative_identity'] is None
    assert not result.get('evidence_snapshot')
    rebuilt, = bind([row()], prior=[proof()])
    assert rebuilt['normative_identity'] == identity()


def test_prior_proof_is_operation_specific_and_new_ref_overrides():
    for work in ('other', 'w'):
        authored = row()
        authored['evidence_refs'] = []
        result, = bind([authored], prior=[proof(work=work)])
        assert result['normative_identity_status'] == ('pinned' if work == 'w' else 'unpinned')
    authored = row()
    authored['evidence_refs'] = ['Q2.H1']
    result, = bind([authored], [chunk('Q2.H1', 'b')], {'Q2.H1': CODE}, [proof()])
    assert result['normative_identity'] == identity('b')
    result, = bind([authored], prior=[proof()])
    assert result['normative_identity_status'] == 'unpinned'


@pytest.mark.parametrize('ref,delivered,error', [
    ('Q9.H9', {}, 'unknown_evidence_ref'),
    ('Q1.H1', {'Q1.H1': 'ГЭСН02-01-001-01'}, 'norm_code_not_in_referenced_evidence'),
])
def test_prior_proof_does_not_validate_a_different_new_reference(ref, delivered, error):
    """Live .186 pass2: validation allowed a row that binding subsequently unpinned."""
    authored = {**row(), 'evidence_refs': [ref]}
    old = [proof()]
    checked, = chat.withhold_unreferenced_norms(
        [authored], delivered_cards=delivered, prior_evidence=old)
    assert checked.get('evidence_error') == error
    rebound, = bind([checked], delivered=delivered, prior=old)
    assert rebound['normative_identity_status'] == 'unpinned'
    assert rebound['norm_code'] == authored['norm_code']
    assert rebound['evidence_refs'] == authored['evidence_refs']
    assert 'evidence_error' not in authored
    assert old == [proof()]


def test_omitted_current_card_cannot_borrow_the_old_local_reference():
    authored = row()
    old = [proof()]
    checked, = chat.withhold_unreferenced_norms([authored], delivered_cards={},
        observed_refs=['Q1.H1'], prior_evidence=old)
    assert checked['evidence_error'] == 'unknown_evidence_ref'
    rebound, = bind([checked], [chunk(revision='b')], {}, old)
    assert rebound['normative_identity_status'] == 'unpinned'
    assert rebound['evidence_refs'] == authored['evidence_refs']


@pytest.mark.parametrize('refs', [[], ['Q1.H1']])
def test_prior_reference_and_revision_survive_without_current_collision(refs):
    authored = {**row(), 'evidence_refs': refs}
    old = [proof()]
    checked, = chat.withhold_unreferenced_norms([authored], delivered_cards={},
        observed_refs=['Q2.H1'], prior_evidence=old)
    assert 'evidence_error' not in checked
    rebound, = bind([checked], [chunk('Q2.H1', 'b')], {}, old)
    assert rebound['normative_identity'] == identity()
    assert rebound['evidence_refs'] == refs


def test_delivered_new_revision_is_validated_and_bound_consistently():
    authored = row()
    old = [proof()]
    checked, = chat.withhold_unreferenced_norms([authored], delivered_cards={'Q1.H1': CODE},
        observed_refs=['Q1.H1'], prior_evidence=old)
    assert 'evidence_error' not in checked
    rebound, = bind([checked], [chunk(revision='b')], {'Q1.H1': CODE}, old)
    assert rebound['normative_identity'] == identity('b')


def test_conflicting_delivered_revisions_do_not_pick_one():
    authored = row()
    authored['evidence_refs'] = ['Q1.H1', 'Q2.H1']
    result, = bind([authored], [chunk(), chunk('Q2.H1', 'b')], {'Q1.H1': CODE, 'Q2.H1': CODE})
    assert result['normative_identity'] is None
    assert result['normative_identity_status'] == 'conflict'
    assert result['normative_identity_conflicts'] == [identity(), identity('b')]


def test_model_snapshot_is_not_a_trusted_prior_proof():
    result, = bind([row(evidence_snapshot=proof()['cards'])])
    assert result['normative_identity_status'] == 'unpinned'
    assert not result.get('evidence_snapshot')


def test_material_without_norm_has_no_pin_requirement():
    authored = dict(source_row='S!1', work_id='supply', decision_kind='материал',
                    norm_code='', normative_identity=identity())
    result, = bind([authored])
    assert 'normative_identity_status' not in result
    assert 'normative_identity' not in result


def test_identity_survives_canonical_revision_and_central_metadata():
    bound, = bind([row()], [chunk()], {'Q1.H1': CODE})
    assert canonical_decision(bound)['normative_identity'] == identity()
    changed = dict(bound, normative_identity=identity('b'))
    assert decisions_revision([bound]) != decisions_revision([changed])
    assert card_delivery_metadata(dict(normative_identity=identity()), '', [])['normative_identity'] == identity()


def test_reused_local_ref_binds_separate_operation_revisions():
    old = row()
    old['evidence_refs'] = []
    old, = bind([old], prior=[proof()])
    fresh = row()
    fresh.update(source_row='S!2', work_id='new')
    fresh, = bind([fresh], [chunk(revision='b')], {'Q1.H1': CODE})
    merged = chat.merged_pass_decisions([fresh], closed=[], portion_state=dict(
        prior_decisions={'S!1': old}, source_anchors=['S!1', 'S!2'], shown=['S!2']))
    assert [r['normative_identity'] for r in merged] == [identity(), identity('b')]


def test_rebuild_reads_trusted_snapshot_and_marks_legacy_unpinned():
    seen = []
    async def execute(call, context, progress):
        seen.extend(call['args']['decisions'])
        return {}
    pinned, = bind([row()], [chunk()], {'Q1.H1': CODE})
    legacy = row()
    legacy.update(source_row='S!2', work_id='legacy')
    asyncio.run(chat.rebuild_workbook_from_stored_decisions(executor=execute,
        attachment_id='attachment', question='question', portion_state=dict(
            prior_decisions={'S!1': pinned, 'S!2': legacy}, source_anchors=['S!1','S!2']),
        context={}, progress=None))
    assert [r['normative_identity_status'] for r in seen] == ['pinned', 'unpinned']


def test_successful_fallback_delivery_uses_sent_body_for_binding_and_snapshot():
    cloud_messages = [dict(role='user', content='[Q1.H1 | cards]:\nA\n\n[Q2.H1 | cards]:\nB')]
    local_messages = [dict(role='user', content='[Q1.H1 | cards]:\nA')]
    sent = []
    async def post(runtime, model, headers, body, *, allow_stream):
        sent.append(body['messages'])
        assert not allow_stream
        return 'model answer', {}
    answer, usage, actual = asyncio.run(chat.post_with_delivery_messages(
        post, None, 'same model', {}, dict(messages=local_messages), allow_stream=False))
    assert answer == 'model answer' and actual == sent[0] == local_messages
    authored = row()
    authored['evidence_refs'] = ['Q2.H1']
    chunks = [chunk(), chunk('Q2.H1', 'b')]
    before = chat.delivered_evidence_cards(cloud_messages[0]['content'], chunks)
    assert before['Q2.H1'] == CODE
    delivered = chat.delivered_evidence_cards(actual[0]['content'], chunks)
    result, = bind([authored], chunks, delivered)
    assert result['normative_identity_status'] == 'unpinned'
    snapshot = chat.evidence_snapshot([result], chunks, delivered_cards=delivered)
    assert snapshot['S!1'][0]['delivered'] is False
