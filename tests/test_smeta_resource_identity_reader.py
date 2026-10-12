"""SQL resource addresses survive exact read and unchanged calculation dedupe."""
from contextlib import closing
import sqlite3

import pytest

from proxy.services import gesn_service as gs
from proxy.services import model_research_tool_service as research
from proxy.smeta_core import norm_browser as browser
from tests.test_smeta_norm_revision_reader import base,CODE


@pytest.fixture(autouse=True)
def clear_catalogs():
    gs.load_base_norms.cache_clear()
    yield
    gs.load_base_norms.cache_clear()


def source(tmp_path,records,*,price_column=True):
    path=base(tmp_path/'source.sqlite',1)
    with closing(sqlite3.connect(path)) as conn,conn:
        conn.execute('DELETE FROM resources')
        conn.execute('UPDATE norms SET resource_count=?',(len(records),))
        for row_id,kind,code,name,unit,consumption,price in records:
            conn.execute('INSERT INTO resources VALUES(?,?,?,?,?,?,?,?,?)',
                (row_id,'fixture-norm','ГЭСН:01-01-001-01',kind,code,name,unit,consumption,price))
        if not price_column:
            conn.execute('ALTER TABLE resources DROP COLUMN price')
    return path


def full_card(path):
    card,=browser._code_listing('ГЭСН','01-01-001-01',base_path=path)
    return card


def test_same_code_different_prices_are_distinct_singletons(tmp_path):
    path=source(tmp_path,[(10,'material','R','Literal','kg',1,10),(20,'material','R','Literal','kg',1,20)])
    card=full_card(path)
    resources=gs.get_norm(CODE,base_path=str(path))['resources']
    assert [r.get('source_resource_ids') for r in resources]==[['10'],['20']]
    assert [r['price'] for r in card['resources']]==[10,20]
    assert card['resource_groups']==[]
    from proxy.smeta_core.resource_identity import resource_selector
    assert [resource_selector(r) for r in resources]==['row:10','row:20']


def test_code_less_material_has_exact_source_selector(tmp_path):
    path=source(tmp_path,[(31,'material','','Literal unclassified','kg',None,None)])
    card=full_card(path)
    resource,=gs.get_norm(CODE,base_path=str(path))['resources']
    from proxy.smeta_core.resource_identity import resource_selector
    assert resource_selector(resource)=='row:31'
    assert resource.get('code','')=='' and resource['per_unit'] is None
    assert card['resources'][0]['source_resource_ids']==['31']
    assert 'row:31' in research.smeta_card_text(card)


def test_duplicate_group_matches_existing_dedupe_and_is_visibly_declared(tmp_path):
    path=source(tmp_path,[(10,'material','R','Literal','kg',1,10),(20,'material','R','Literal','kg',1,10)])
    card=full_card(path)
    norm=gs.get_norm(CODE,base_path=str(path))
    resource,=norm['resources']
    assert resource['per_unit']==1 and resource['price']==10
    assert resource['source_resource_ids']==['10','20']
    group,=card['resource_groups']
    assert group['source_resource_ids']==resource['source_resource_ids']
    assert group['source_resource_group_id']==resource['source_resource_group_id']
    assert group['source_resource_group_id'].startswith('group:')
    assert len(card['resources'])==2 and card['resources_complete']
    texts=research.smeta_resource_group_texts(card)
    assert len(texts)==1 and texts[0][0]==group
    assert group['source_resource_group_id'] in texts[0][1] and '[10, 20]' in texts[0][1]
    assert texts[0][1] in research.smeta_card_text(card)


def test_labor_source_code_fallback_groups_exactly_as_calculator(tmp_path):
    path=source(tmp_path,[(5,'labor','','Средний разряд работы 3,5','чел.-ч',2,None),
        (7,'labor','1-100-35','Explicit tariff','чел.-ч',2,None)])
    card=full_card(path)
    resource,=gs.get_norm(CODE,base_path=str(path))['resources']
    assert resource['code']=='1-100-35' and resource['per_unit']==2
    group,=card['resource_groups']
    assert group['code']=='1-100-35'
    assert group['source_resource_ids']==resource['source_resource_ids']==['5','7']
    assert card['resources'][0]['code']==''  # Literal SQL evidence is not rewritten.


def test_preview_has_sql_coordinates_but_no_complete_group_claim(tmp_path):
    records=[(n,'material','R','Literal','kg',1,10) for n in range(1,19)]
    path=source(tmp_path,records)
    card,=browser._code_listing('ГЭСН','01-01-001',base_path=path)
    assert len(card['resource_preview'])==16
    assert [r.get('row_id') for r in card['resource_preview']]==list(range(1,17))
    assert not card.get('resource_groups')
    assert research.smeta_resource_group_texts(card)==[]
    assert 'row:1' in research.smeta_card_text(card)


def test_legacy_card_without_price_column_preserves_unknown(tmp_path):
    path=source(tmp_path,[(8,'material','R','Literal','kg',None,None)],price_column=False)
    card=full_card(path)
    assert card['resources'][0]['per_unit'] is None
    assert card['resources'][0].get('price') is None


def test_helper_does_not_invent_addresses_for_derived_or_legacy_resources():
    from proxy.smeta_core.resource_identity import dedupe_resources,resource_selector
    resources,dropped=dedupe_resources([dict(kind='machinist',code='D',name='Derived',unit='чел.-ч',per_unit=1)])
    assert dropped==0 and resource_selector(resources[0]) is None


def test_group_id_is_bound_to_norm_revision_not_row_order(tmp_path):
    path=source(tmp_path,[(10,'material','R','Literal','kg',1,10),(20,'material','R','Literal','kg',1,10)])
    card=full_card(path)
    from proxy.smeta_core.resource_identity import dedupe_resources
    normal=[dict(kind='material',code='R',name='Literal',unit='kg',per_unit=1,price=10,source_resource_ids=[str(n)]) for n in (10,20)]
    first,_=dedupe_resources(normal,normative_identity=card['normative_identity'])
    reverse,_=dedupe_resources(list(reversed(normal)),normative_identity=card['normative_identity'])
    assert first[0]['source_resource_group_id']==reverse[0]['source_resource_group_id']
    changed=dict(card['normative_identity'],base_sha256='different-revision')
    later,_=dedupe_resources(normal,normative_identity=changed)
    assert first[0]['source_resource_group_id']!=later[0]['source_resource_group_id']
