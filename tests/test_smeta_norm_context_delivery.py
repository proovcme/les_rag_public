"""Normative context must reach the same final evidence as its code and title."""
import asyncio

import pytest

from proxy.services import chat_evidence_application_service as chat
from proxy.services import model_research_tool_service as research
from proxy.services.model_execution_preset_service import ModelExecutionPreset


@pytest.fixture
def card(monkeypatch):
    monkeypatch.setattr(research, 'norm_table_variants', lambda _: ())
    return dict(norm_code='ГЭСНм08-05-045-03', norm_id='FSNB-2022|ГЭСНм|08-05-045-03',
        title='Заземление оборудования: центральное', measure_unit='шт',
        source_ref='Сборник 8. Электротехнические установки<br/>Отдел 5. Кабельные линии<br/>Раздел 2. ЭЛЕКТРООБОРУДОВАНИЕ В ГОРНОРУДНЫХ ВЫРАБОТКАХ<br/>Таблица ГЭСНм 08-05-045 Заземления#guid=fixture',
        work_steps=['Транспортирование шин заземления к стволу шахты и по горным выработкам.'],
        resource_preview=[dict(kind='machine',code='91.09.02-009',name='Вагонетки неопрокидные',unit='маш.-ч'),
                          dict(kind='material',code='R',name='Материал '+('длинное описание '*45),unit='т')])


@pytest.mark.parametrize('quantity, expected', [(0.0, '0.0'), (0.123456789, '0.123456789'), (None, 'неизвестен')])
def test_resource_consumption_preserves_zero_precision_and_unknown(card, quantity, expected):
    card['measure_unit'] = '100 м'
    card['resource_preview'] = [dict(kind='material', code='R', name='Ресурс', unit='кг', per_unit=quantity)]
    text = research.smeta_card_text(card)
    assert 'расход на 100 м' in text
    assert f'Ресурс [кг; {expected}]' in text


def test_card_keeps_source_section_and_machine_evidence(card):
    text = research.smeta_card_text(card)
    assert 'Раздел 2. ЭЛЕКТРООБОРУДОВАНИЕ В ГОРНОРУДНЫХ ВЫРАБОТКАХ' in text
    assert 'Вагонетки неопрокидные' in text
    assert card['norm_id'] in text and card['title'] in text
    assert '<br' not in text and '#guid=' not in text


@pytest.mark.parametrize('route', ['search', 'practice', 'material'])
def test_tight_budget_keeps_work_description_before_long_resource_preview(card, route):
    if route == 'search':
        service = research.ModelResearchToolService(retrieve=None, frozen_dataset_ids=(), retrieval_kwargs={},
            fallback=None, smeta_norm_retrieve=lambda *_a, **_k: {'cards': [card],
                'retrieval_trace': {'rag': {'status': 'ok', 'collection': 'fixture'}}})
        chunk = asyncio.run(service.execute({'tool': 'search_sources', 'args': {'q': 'model query'}})).chunks[0]
    elif route == 'material':
        chunk = chat._MaterialChunk(card, {}, research.smeta_card_text)
    else:
        chunk = chat._PracticeChunk(card)
    groups, chunks = chat.build_model_rag_evidence_groups([('model query', [chunk])],
        max_chars=600, hits_per_query=6)
    sent = '\n'.join(groups)
    assert card['work_steps'][0] in sent
    assert research.smeta_card_header(card) in sent
    assert 'карточка сокращена' in sent
    assert len(sent) <= 600


@pytest.mark.parametrize('route', ['search', 'practice', 'material'])
def test_budget_keeps_complete_norm_header_in_final_messages(card, route):
    if route == 'search':
        service = research.ModelResearchToolService(retrieve=None, frozen_dataset_ids=(), retrieval_kwargs={},
            fallback=None, smeta_norm_retrieve=lambda *_args, **_kwargs: {'cards': [card],
                'retrieval_trace': {'rag': {'status': 'ok', 'collection': 'fixture'}}})
        result = asyncio.run(service.execute({'tool': 'search_sources', 'args': {'q': 'model query'}}))
        chunk = result.chunks[0]
    elif route == 'material':
        chunk = chat._MaterialChunk(card, {}, research.smeta_card_text)
    else:
        chunk = chat._PracticeChunk(card)
    groups, chunks = chat.build_model_rag_evidence_groups(
        [('Заземление оборудования', [chunk])], max_chars=410, hits_per_query=6)
    preset = ModelExecutionPreset('test','fixture',2048,256,128,3,5,5,1,False,('test',))
    messages, packet = chat.govern_inference_messages(preset=preset,profile_prefix='Fixture',
        request_payload='Проверь условия', evidence=groups)
    sent = '\n'.join(m['content'] for m in messages)
    assert 'Раздел 2. ЭЛЕКТРООБОРУДОВАНИЕ В ГОРНОРУДНЫХ ВЫРАБОТКАХ' in sent
    assert card['norm_id'] in sent and card['title'] in sent
    assert 'карточка сокращена' in sent
    assert len(chunks) == 1 and not packet.omissions


def test_too_small_budget_never_shows_a_norm_without_its_header(card):
    chunk = chat._PracticeChunk(card)
    with pytest.raises(ValueError, match='EVIDENCE_BUDGET'):
        chat.build_model_rag_evidence_groups([('Запрос', [chunk])], max_chars=200, hits_per_query=6)


@pytest.mark.parametrize('route', ['search', 'practice', 'material'])
@pytest.mark.parametrize('budget, delivered', [(500, False), (4000, True)])
def test_archive_example_is_delivered_with_provenance_or_omitted_whole(card, route, budget, delivered):
    card['usage_evidence'] = {'note': 'в архиве применено 15 раз', 'source': 'fixture archive', 'applications': 15}
    card['archive_provenance'] = {
        'archive_title': 'Другая работа в архиве', 'archive_unit': '100 шт',
        'examples': [{'document': 'fixture-lsr.xlsx', 'sha256': 'a'*64, 'sheet': 'ЛСР',
                      'work_row': 17, 'material_row': 18, 'original_code': 'ТЕРм08-05-045-03',
                      'norm_unit': '100 шт', 'norm_title': 'Архивное наименование',
                      'link_kind': 'following_norm', 'equipment': True, 'edition': None}],
        'identity_check': {'equivalent': False, 'differences': ['unit']},
        'unknowns': ['условия монтажа', 'технологическая применимость'],
    }
    if route == 'search':
        service = research.ModelResearchToolService(retrieve=None, frozen_dataset_ids=(), retrieval_kwargs={},
            fallback=None, smeta_norm_retrieve=lambda *_a, **_k: {'cards': [card],
                'retrieval_trace': {'rag': {'status': 'ok', 'collection': 'fixture'}}})
        chunk = asyncio.run(service.execute({'tool': 'search_sources', 'args': {'q': 'model query'}})).chunks[0]
    elif route == 'material':
        chunk = chat._MaterialChunk(card, {}, research.smeta_card_text)
    else:
        chunk = chat._PracticeChunk(card)
    groups, chunks = chat.build_model_rag_evidence_groups([('model query', [chunk])],
        max_chars=budget, hits_per_query=6)
    preset = ModelExecutionPreset('test','fixture',8192,1024,256,3,5,5,1,False,('test',))
    messages, packet = chat.govern_inference_messages(preset=preset,profile_prefix='Fixture',
        request_payload='Проверь условия', evidence=groups)
    sent = '\n'.join(m['content'] for m in messages)
    assert research.smeta_card_header(card) in sent and not packet.omissions
    assert 'score=15.0000' not in sent  # Archive applications are not retrieval scores.
    assert ('архивный контекст не показан' in sent) is not delivered
    if delivered:
        assert 'в архиве применено 15 раз' in sent
        assert 'fixture-lsr.xlsx SHA256:' + 'a'*64 in sent
        assert 'ЛСР!работа:17, изделие:18' in sent
        assert 'Частота не доказывает пригодность.' in sent
        assert 'условия монтажа; технологическая применимость.' in sent
    else:
        assert 'Практика раздела:' not in sent
        assert 'Применение:' not in sent
        assert 'в архиве применено 15 раз' not in sent
    assert chunks[0].meta['model_archive_evidence_delivered'] is delivered
    assert len('\n'.join(groups)) <= budget


@pytest.mark.parametrize('budget', [600, 3000])
def test_archive_alias_snapshot_matches_its_actually_delivered_original(card, budget):
    card['usage_evidence'] = {'note': 'в архиве применено 15 раз', 'source': 'fixture archive'}
    chunk = chat._PracticeChunk(card)
    groups, chunks = chat.build_model_rag_evidence_groups(
        [('first', [chunk]), ('second', [chunk])], max_chars=budget, hits_per_query=6)
    assert len(chunks) == 2
    assert chunks[1].meta['model_evidence_alias_of'] == 'Q1.H1'
    assert chunks[0].content == chunks[1].content
    assert chunks[0].meta['model_archive_evidence_delivered'] == chunks[1].meta['model_archive_evidence_delivered']
    assert chunks[0].content in groups[0]
    if chunks[0].meta['model_archive_evidence_delivered']:
        assert research.smeta_card_context(card) in groups[0]
    else:
        assert 'Практика раздела:' not in '\n'.join(groups)
