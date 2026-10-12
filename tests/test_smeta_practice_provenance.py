"""Archive coordinates and candidate identity survive builder → model evidence."""
import hashlib
import json

import openpyxl
import pytest

from tools import build_material_norm_index as material_builder
from tools.build_estimate_usage_corpus import build_corpus
from proxy.smeta_core.material_practice import similar_applications
from proxy.smeta_core.estimate_usage import usage_evidence
from proxy.services.chat_evidence_application_service import material_candidate_card, _MaterialChunk
from proxy.services.model_research_tool_service import smeta_card_text


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / 'archive'
    root.mkdir()
    path = root / 'СКС.xlsx'
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.title = 'ЛСР'
    sheet.append(['', 'ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЕТ'])
    sheet.append(['Структурированная кабельная система'])
    sheet.append(['(наименование работ и затрат)'])
    sheet.append([1, 'ТЕРм11-04-028-01', 'Включение разъемов', '1 разъем'])
    sheet.append(['О', 'Прайс п.1', 'Патч-корд RJ45', 'шт.'])
    sheet.append([2, 'ФЕРм10-02-051-01', 'Перемычки до 6 м', '100 перемычек'])
    sheet.append(['', 'Прайс п.2', 'Патч-корд RJ45', 'шт.'])
    sheet.append(['', 'Прайс п.3', 'Панель коммутационная', 'шт.'])
    sheet.append(['', 'Прайс п.4', 'Шпилька монтажная', 'шт.'])
    wb.save(path)
    wb.close()
    return root, path


def test_builders_keep_source_coordinates_and_original_family(archive, tmp_path):
    root, path = archive
    index = material_builder.build_index(root, base_path=tmp_path/'absent.sqlite')
    entry = next(e for e in index['entries'] if e['norm_code'] == 'ГЭСНм11-04-028-01')
    example = entry['examples'][0]
    assert example['document'] == str(path)
    assert example['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert (example['sheet'], example['work_row'], example['material_row']) == ('ЛСР', 4, 5)
    assert example['original_code'] == 'ТЕРм11-04-028-01'
    assert example['norm_unit'] == '1 разъем'
    assert example['material_unit'] == 'шт.'
    assert example['link_kind'] == 'following_norm'
    assert example['equipment'] is True
    assert example['edition'] is None  # A date or prefix is not a verified edition.
    assert example['work_steps'] is None
    corpus = build_corpus(root, base_path=tmp_path/'absent.sqlite')
    out = tmp_path/'corpus.json'
    out.write_text(json.dumps(corpus), encoding='utf-8')
    evidence = usage_evidence(entry['norm_code'], 'communications', path=str(out))
    assert evidence['examples'][0]['work_row'] == 4
    assert evidence['examples'][0]['original_code'] == example['original_code']


def test_alternative_norms_for_same_material_are_not_hidden(archive, tmp_path):
    root, _ = archive
    index = material_builder.build_index(root, base_path=tmp_path/'absent.sqlite')
    out = tmp_path/'index.json'
    out.write_text(json.dumps(index), encoding='utf-8')
    results = similar_applications('Патч-корд RJ45', path=str(out), limit=5)
    assert {r['norm_code'] for r in results} == {'ГЭСНм11-04-028-01', 'ГЭСНм10-02-051-01'}
    assert all(r['examples'] and r['source'] and r['revision'] for r in results)


def test_old_index_is_incomplete_and_conflict_is_visible_to_model(monkeypatch):
    item = {'norm_code': 'ГЭСНм11-04-028-01', 'material': 'Адаптер оптический',
            'norm_title': 'Розетка микрофонная', 'norm_unit': '100 шт', 'applications': 15}
    monkeypatch.setattr('proxy.smeta_core.norm_browser.browse_norms', lambda *a, **k: {'cards': [{
        'norm_code': item['norm_code'], 'norm_id': 'canonical-2022', 'edition': '2022',
        'title': 'Включение разъемов', 'measure_unit': '1 разъем'}]})
    card = material_candidate_card(item)
    chunk = _MaterialChunk(card, item, smeta_card_text)
    assert chunk.meta['archive_provenance']['status'] == 'incomplete'
    assert chunk.meta['archive_provenance']['identity_check']['equivalent'] is False
    assert 'Розетка микрофонная' in chunk.content
    assert '100 шт' in chunk.content
    assert 'не подтвержден' in chunk.content


def test_material_publication_refuses_empty_source_without_overwriting(tmp_path):
    source = tmp_path/'empty'
    source.mkdir()
    out = tmp_path/'index.json'
    out.write_text('{"existing":true}', encoding='utf-8')
    assert material_builder.main(['--source', str(source), '--out', str(out)]) != 0
    assert json.loads(out.read_text()) == {'existing': True}


@pytest.mark.parametrize('payload', [[], {'schema': material_builder.SCHEMA, 'entries': [None, {'material': 'x', 'count': 'bad'}]}])
def test_damaged_material_index_does_not_crash_reader(tmp_path, payload):
    out = tmp_path/'broken.json'
    out.write_text(json.dumps(payload), encoding='utf-8')
    assert similar_applications('Патч-корд', path=str(out)) == []


def test_mixed_editions_cannot_be_called_equivalent():
    from proxy.smeta_core.estimate_usage import archive_provenance
    result = archive_provenance({'examples': [{'edition': '2020'}, {'edition': '2022'}]}, {'edition': '2022'})
    assert result['identity_check'] == {'equivalent': False, 'differences': ['edition']}


def test_atomic_material_publication_preserves_existing_on_failure(archive, tmp_path, monkeypatch):
    root, _ = archive
    out = tmp_path/'index.json'
    out.write_bytes(b'{"existing":true}')
    def fail(*args):
        raise OSError('publication interrupted')
    monkeypatch.setattr('tools.build_estimate_usage_corpus.os.replace', fail)
    with pytest.raises(OSError, match='publication interrupted'):
        material_builder.main(['--source', str(root), '--out', str(out), '--base', str(tmp_path/'none')])
    assert out.read_bytes() == b'{"existing":true}'


def test_non_object_usage_corpus_is_unavailable(tmp_path):
    from proxy.smeta_core.estimate_usage import load_corpus
    out = tmp_path/'corpus.json'
    out.write_text('[]', encoding='utf-8')
    assert load_corpus(str(out))['sections'] == {}
