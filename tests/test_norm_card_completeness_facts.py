"""Resource delivery cannot prove absent work composition or conditions."""
import pytest

from proxy.services.model_rag_grouped_evidence_service import card_delivery_facts
from proxy.services.model_research_tool_service import _norm_card_content, _full_norm_card_content


def metadata(**changes):
    return {'norm_code': 'ГЭСН01-01-001-01', 'resource_count': 1,
            'resources': [{'code': 'A', 'per_unit': 0}], 'resources_complete': True,
            'resources_returned': 1, **changes}


def test_full_resources_without_work_steps_are_not_a_complete_norm_card():
    facts = card_delivery_facts(metadata(work_steps=[]), raw_body_shown=True,
                                displayed_body="Literal resource body")
    assert facts['normative_resources_status'] == 'complete'
    assert facts['normative_card_complete'] is False
    assert facts['normative_conditions_shown'] is False
    assert facts['normative_work_steps_status'] == 'missing_in_source'


def test_unknown_composition_is_not_invented_from_any_shown_body():
    facts = card_delivery_facts(metadata(), raw_body_shown=True, displayed_body="Literal resource body")
    assert facts['raw_hit_body_shown'] and facts['card_body_shown']
    assert facts['normative_work_steps_status'] == 'unknown'
    assert facts['normative_card_complete'] is False


def test_literal_work_steps_and_resources_remain_separate_facts():
    meta = metadata(work_steps=['Literal installation step'])
    body = _full_norm_card_content(meta)
    shown = card_delivery_facts(meta, raw_body_shown=True, displayed_body=body)
    assert shown['normative_work_steps_status'] == 'complete'
    assert shown['normative_composition_shown'] and shown['normative_card_complete']
    assert shown['normative_conditions_shown'] is False
    preview = card_delivery_facts({**meta, 'resources_complete': False}, raw_body_shown=True,
                                  displayed_body=_norm_card_content(meta))
    assert preview['normative_work_steps_status'] == 'complete'
    assert preview['normative_card_complete'] is False
    unread = card_delivery_facts(meta, raw_body_shown=False, displayed_body=body)
    assert unread['normative_work_steps_status'] == 'not_read'
    assert unread['normative_card_complete'] is False and not unread['normative_conditions_shown']


@pytest.mark.parametrize('body', [
    '', 'First step; Second step', 'Состав работы: First step',
    'Состав работы: Second step; First step',
    'Quote: Состав работы: First step; Second step',
    'Состав работы: First step; Second step; Third step',
])
def test_composition_requires_whole_literal_producer_block_with_boundaries(body):
    facts = card_delivery_facts(metadata(work_steps=['First step', 'Second step']),
                                raw_body_shown=True, displayed_body=body)
    assert facts['normative_work_steps_status'] == 'not_shown'
    assert not facts['normative_composition_shown'] and not facts['normative_card_complete']
    assert facts['normative_resources_status'] == 'complete'


@pytest.mark.parametrize('prefix,suffix', [('', ''), ('Header\n', ''), ('', '\nFooter'),
                                         ('Header\n', '\nFooter')])
def test_literal_composition_block_preserves_spaces_newlines_and_unicode(prefix, suffix):
    steps = ['  First step  ', '', ' \t', 'Вторая\nстрока с "кавычками" и е\u0301']
    body = prefix + 'Состав работы:   First step  ; Вторая\nстрока с "кавычками" и е\u0301' + suffix
    facts = card_delivery_facts(metadata(work_steps=steps), raw_body_shown=True, displayed_body=body)
    assert facts['normative_work_steps_status'] == 'complete'
    assert facts['normative_composition_shown'] and facts['normative_card_complete']


@pytest.mark.parametrize('steps,status', [([], 'missing_in_source'), (['', ' \t'], 'missing_in_source'),
                                         (None, 'unknown'), ([12], 'unknown')])
def test_missing_or_unknown_steps_are_not_reconstructed_from_body(steps, status):
    facts = card_delivery_facts(metadata(work_steps=steps), raw_body_shown=True,
                                displayed_body='Состав работы: Literal installation step')
    assert facts['normative_work_steps_status'] == status
    assert not facts['normative_composition_shown'] and not facts['normative_card_complete']
