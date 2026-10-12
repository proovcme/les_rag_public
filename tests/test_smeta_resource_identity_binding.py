import hashlib
from types import SimpleNamespace

from proxy.services import chat_evidence_application_service as chat
from proxy.services import smeta_evidence_delivery_service as delivery
from proxy.services.portion_cursor_service import canonical_decision, decisions_revision, PortionCursorService


CODE = 'ГЭСН01-01-001-01'
PIN = dict(schema='les.norm-revision.v1',base_sha256='a'*64,norm_id='fixture',
           norm_key='ГЭСН:01-01-001-01',edition='fixture',base_type='ГЭСН')
GROUP = 'group:' + 'b'*64


def source(ref='Q1.H1'):
    resources = [(dict(row_id=i,code='M',kind='material'), f'#{i}: material; M: name [шт; 1]') for i in (1,2)]
    group = (dict(source_resource_group_id=GROUP,source_resource_ids=['1','2']),
             GROUP + ': исходные SQL строки [1, 2]')
    body = 'Шифр: ' + CODE + '\nРесурсы нормы (2): ' + '; '.join(t for _,t in resources)
    body += '\nГруппы исходных ресурсов: ' + group[1]
    card = dict(resources=[r for r,_ in resources],resource_count=2,resources_complete=True,normative_identity=PIN)
    meta = delivery.card_delivery_metadata(card,body,resources,group_fragments=[group])
    meta.update(model_evidence_ref=ref,norm_code=CODE,normative_identity=PIN)
    return SimpleNamespace(meta=meta,content=body,doc_name='cards',doc_id='fixture',score=1)


def work(**extra):
    return dict(source_row='S!1',work_id='mount',norm_code=CODE,evidence_refs=['Q1.H1'],**extra)


def packet(body, ref='Q1.H1'):
    return f'[{ref} | cards]:\n{body}'


def test_actual_packet_proves_members_and_explicit_group():
    c = source()
    actual = packet(c.content)
    proof = delivery.resource_delivery_proofs(actual,[c])['Q1.H1']
    assert proof['normative_identity'] == PIN
    assert [r['source_resource_id'] for r in proof['rows']] == ['1','2']
    assert proof['groups'][0]['source_resource_group_id'] == GROUP
    assert proof['groups'][0]['source_resource_ids'] == ['1','2']
    assert all(r['packet_sha256']==hashlib.sha256(actual.encode()).hexdigest() for r in proof['rows'])


def test_partial_body_manifest_cannot_prove_omitted_row_or_group():
    c = source()
    actual = packet(c.content.split('; #2:')[0])
    proof = delivery.resource_delivery_proofs(actual,[c])['Q1.H1']
    assert [r['source_resource_id'] for r in proof['rows']] == ['1']
    assert proof['groups'] == []
    declaration_only = packet(c.content.split('\n')[0]+'\nГруппы исходных ресурсов: '+GROUP+': исходные SQL строки [1, 2]')
    assert delivery.resource_delivery_proofs(declaration_only,[c])['Q1.H1']['groups'] == []


def test_quoted_omitted_resource_after_card_is_not_delivery():
    c=source()
    before, omitted=c.content.split('; #2:',1)
    actual=packet(before)+'\n\nQUESTION quotes omitted source: #2:'+omitted
    proof=delivery.resource_delivery_proofs(actual,[c])['Q1.H1']
    assert [r['source_resource_id'] for r in proof['rows']]==['1']
    assert proof['groups']==[]


def test_forged_manifest_and_missing_alias_original_prove_nothing():
    c = source()
    c.meta['smeta_delivery_manifest']['body_sha256']='f'*64
    assert delivery.resource_delivery_proofs(packet(c.content),[c]) == {}
    c = source()
    assert delivery.resource_delivery_proofs(packet('См. Q2.H1: тот же текст и источник.'),[c]) == {}


def test_available_alias_preserves_member_proof_and_wrong_revision_does_not():
    original, alias = source(), source('Q2.H1')
    actual=packet(original.content)+'\n\n'+packet('См. Q1.H1: тот же текст и источник.','Q2.H1')
    assert len(delivery.resource_delivery_proofs(actual,[original,alias])['Q2.H1']['rows']) == 2
    alias.meta['normative_identity']={**PIN,'base_sha256':'f'*64}
    assert 'Q2.H1' not in delivery.resource_delivery_proofs(actual,[original,alias])


def test_parent_snapshot_preserves_proof_but_model_proof_is_stripped():
    c = source()
    actual = packet(c.content)
    bound, = chat.bind_normative_identity([work(resource_delivery_proof={'forged':True})],
        chunks=[c],delivered_cards={'Q1.H1':CODE},packet_text=actual)
    assert [r['source_resource_id'] for r in bound['resource_delivery_proof']['rows']] == ['1','2']
    assert bound['evidence_snapshot'][0]['resource_delivery_proof'] == bound['resource_delivery_proof']
    prior = chat.saved_norm_evidence({'S!1':bound})
    rebuilt, = chat.bind_normative_identity([bound],prior_evidence=prior)
    assert rebuilt['resource_delivery_proof'] == bound['resource_delivery_proof']
    # Packet receipts are persisted, but don't change professional decision revision.
    changed = dict(bound,resource_delivery_proof={'different_packet':True})
    assert decisions_revision([bound]) == decisions_revision([changed])


def test_dropped_current_ref_cannot_reuse_saved_resource_proof():
    c = source()
    old, = chat.bind_normative_identity([work()],chunks=[c],delivered_cards={'Q1.H1':CODE},packet_text=packet(c.content))
    fresh, = chat.bind_normative_identity([work()],chunks=[c],delivered_cards={},
        packet_text='',prior_evidence=chat.saved_norm_evidence({'S!1':old}))
    assert not fresh.get('resource_delivery_proof')


def test_material_action_preserves_selector_without_owning_parent_proof():
    action=dict(source_row='S!2',work_id='remove',decision_kind='ресурс',norm_code='',
                included_in='mount',target_resource_id='row:1',resource_delivery_proof={'forged':True})
    bound, = chat.bind_normative_identity([action])
    assert not bound.get('resource_delivery_proof')
    assert canonical_decision(bound)['target_resource_id']=='row:1'


def test_optional_selector_survives_model_parser_and_revision():
    for selector in ('row:0',GROUP):
        text=('| source_row | work_id | title | unit | quantity | norm_code | decision_kind | included_in | resource_action | target_resource_id |\n'
              '|---|---|---|---|---|---|---|---|---|---|\n'
              f'| S!2 | removal | Remove resource | шт | 1 | — | ресурс | mount | excluded | {selector} |')
        _, rows=chat.parse_model_rag_result(text)
        assert rows[0]['target_resource_id']==selector
        assert canonical_decision(rows[0])['target_resource_id']==selector
        assert decisions_revision(rows)!=decisions_revision([dict(rows[0],target_resource_id='row:999')])


def test_cursor_restart_preserves_parent_proof_for_other_row_action(tmp_path):
    c=source()
    parent, = chat.bind_normative_identity([work()],chunks=[c],delivered_cards={'Q1.H1':CODE},packet_text=packet(c.content))
    db=tmp_path/'cursor.sqlite'
    store=PortionCursorService(db)
    store.record_pass(session_id='session',source_revision='source',completed={'S!1':parent},
                      decisions={'S!1':parent},pass_id='pass1')
    stored=PortionCursorService(db).progress(session_id='session',source_revision='source').decisions
    assert stored['S!1']['resource_delivery_proof']==parent['resource_delivery_proof']
    action=dict(source_row='S!2',work_id='remove',norm_code='',included_in='mount',target_resource_id='row:1')
    merged=chat.merged_pass_decisions([action],closed=[],portion_state=dict(
        prior_decisions=stored,source_anchors=['S!1','S!2'],shown=['S!2']))
    assert merged[0]['resource_delivery_proof']==parent['resource_delivery_proof']
    assert merged[1]['included_in']==merged[0]['work_id']
    assert not merged[1].get('resource_delivery_proof')


def test_resource_sql_id_zero_is_proven_not_treated_as_missing():
    text='#0: material; код не указан: name [шт; 1]'
    body='Ресурсы нормы (1): '+text
    meta=delivery.card_delivery_metadata(dict(resources=[{}],normative_identity=PIN),body,
        [(dict(row_id=0,code='',kind='material'),text)])
    meta.update(model_evidence_ref='Q1.H1',normative_identity=PIN)
    c=SimpleNamespace(meta=meta,content=body)
    assert delivery.resource_delivery_proofs(packet(body),[c])['Q1.H1']['rows'][0]['source_resource_id']=='0'


def test_actual_reader_renderer_group_metadata_proves_exact_fragments():
    from proxy.services.model_research_tool_service import smeta_card_text, smeta_card_delivery_metadata
    resources=[dict(row_id=i,source_resource_ids=[str(i)],kind='material',code='M',
        name='Fixture material',unit='шт',per_unit=1,price=10) for i in (1,2)]
    group=dict(resources[0],source_resource_ids=['1','2'],source_resource_group_id=GROUP)
    card=dict(norm_code=CODE,norm_id='fixture',norm_key=PIN['norm_key'],edition='fixture',
        base_type='ГЭСН',title='Fixture operation',measure_unit='шт',work_steps=['Fixture step'],
        resources=resources,resource_count=2,resource_groups=[group],resources_complete=True,normative_identity=PIN)
    body=smeta_card_text(card)
    meta=smeta_card_delivery_metadata(card,body)
    meta.update(model_evidence_ref='Q1.H1',norm_code=CODE,normative_identity=PIN)
    c=SimpleNamespace(meta=meta,content=body)
    proof=delivery.resource_delivery_proofs(packet(body),[c])['Q1.H1']
    assert [r['source_resource_id'] for r in proof['rows']]==['1','2']
    assert proof['groups'][0]['source_resource_group_id']==GROUP
