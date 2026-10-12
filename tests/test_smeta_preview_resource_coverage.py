"""Preview completeness must not imply full resource completeness."""
import pytest
from proxy.services import model_research_tool_service as research


def card(preview):
    return {'norm_code':'test-code','norm_id':'fixture-norm','title':'Fixture operation',
            'measure_unit':'1 unit','work_steps':['Fixture step'], 'resource_count':5,
            'resource_preview':preview}


def test_nonempty_preview_already_discloses_incomplete_resource_list(monkeypatch):
    monkeypatch.setattr(research,'norm_table_variants',lambda _code: [])
    preview = [{'kind':'machine','code':'M1','name':'Fixture machine','unit':'h','per_unit':1},
               {'kind':'material','code':'R1','name':'Fixture material','unit':'kg','per_unit':2}]
    text = research.smeta_card_text(card(preview))
    assert 'неполный перечень' in text  # Already supported; do not claim its absence.


def test_zero_visible_resources_still_discloses_incomplete_resource_coverage(monkeypatch):
    monkeypatch.setattr(research,'norm_table_variants',lambda _code: [])
    text = research.smeta_card_text(card([]))
    assert 'неполный перечень' in text
    assert 'состав ресурсов не показан' in text
    assert 'search_sources' not in text


@pytest.mark.parametrize('count',[None,0,-1,'unknown',False])
def test_unknown_or_zero_resource_count_does_not_invent_hidden_resources(monkeypatch,count):
    monkeypatch.setattr(research,'norm_table_variants',lambda _code: [])
    source = {**card([]),'resource_count':count}
    assert 'состав ресурсов не показан' not in research.smeta_card_text(source)


def test_filtered_labor_preview_discloses_known_unshown_resources(monkeypatch):
    monkeypatch.setattr(research,'norm_table_variants',lambda _code: [])
    source = card([{'kind':'labor','code':'L1','name':'Fixture labor','unit':'h','per_unit':1}])
    text = research.smeta_card_text(source)
    assert 'состав ресурсов не показан' in text
    assert 'Fixture labor' not in text


@pytest.mark.parametrize('complete',[True,False])
def test_exact_read_keeps_full_reader_completeness_and_resource_manifest(monkeypatch,complete):
    monkeypatch.setattr(research,'norm_table_variants',lambda _code: [])
    row = {'row_id':7,'kind':'labor','code':'L1','name':'Fixture labor','unit':'h','per_unit':1}
    source = {**card([]),'resource_count':1,'resources':[row],'resources_complete':complete}
    text = research.smeta_card_text(source)
    assert 'состав ресурсов не показан' not in text
    assert ('полный перечень' if complete else 'полнота не подтверждена') in text
    assert '#7: labor' in text and 'Fixture labor' in text
    manifest = research.smeta_card_delivery_metadata(source,text)
    assert manifest['smeta_full_read'] is True
    assert manifest['smeta_resources_complete'] is complete


def test_long_steps_and_empty_preview_keep_existing_truncation_and_preview_proof(monkeypatch):
    monkeypatch.setattr(research,'norm_table_variants',lambda _code: [])
    source = {**card([]),'work_steps':['x'*(research.WORK_STEPS_MAX_CHARS+100)]}
    text = research.smeta_card_text(source)
    assert '[состав сокращён]' in text and 'состав ресурсов не показан' in text
    metadata = research.smeta_card_delivery_metadata(source,text)
    assert not metadata.get('smeta_full_read')
    assert not metadata.get('smeta_resources_complete')
    assert metadata['smeta_delivery_manifest']['resources'] == []
    assert metadata['smeta_delivery_manifest']['database_resource_count'] == 5
