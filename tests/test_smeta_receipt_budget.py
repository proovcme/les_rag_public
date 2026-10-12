import pytest

from proxy.services import chat_evidence_application_service as chat
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from proxy.services.portion_cursor_service import PortionCursorService


def test_full_receipts_survive_governor_without_closing_omitted_rows(tmp_path, monkeypatch):
    monkeypatch.delenv('LES_SMETA_PORTION_ROWS', raising=False)
    preset = ModelExecutionPreset('budget-test', 'qwen', 32768, 8192, 2048, 3, 5, 5, 1, False, ('test',))
    text = 'Файл: receipt.xlsx\nS!R1: № | Наименование | Ед. изм | Количество\n'
    text += '\n'.join(f'S!R{i+1}: {i} | Fixture {i} | шт | 1' for i in range(1, 26))
    cursor = PortionCursorService(tmp_path / 'cursor.sqlite')
    _, state = chat.smeta_portion_context(text, session_id='s', limit=25, cursors=cursor)
    rows = [dict(source_row=f'S!{i}', work_id=f'w{i}', title=f'Fixture {i}', unit='шт', quantity=1,
                 norm_code='ГЭСН01-01-001-01') for i in range(1, 26)]
    receipts = [dict(source_row=r['source_row'], work_id=r['work_id'], status='resource_review_required',
                     calculation_ref=f'ref-{i}', calculation={'resources': [{'name': 'X' * 4200, 'quantity': i}]})
                for i, r in enumerate(rows, 1)]
    chat.record_portion_pass(cursor, session_id='s', portion_state=state, rows=rows,
                             closed=[], artifact_revision_id='rev',
                             row_statuses={r['source_row']: 'resource_review_required' for r in rows},
                             calculation_receipts=receipts, pass_id='first')
    context, chosen = chat.fit_smeta_portion_context(
        text, session_id='s', limit=chat.smeta_portion_rows(text), cursors=cursor, preset=preset,
        profile_prefix='profile', request_payload='question')
    assert 1 <= chosen['rows_in_pass'] < 25
    assert chosen['completed'] == 0 and chosen['pending'] == 25
    messages, packet = chat.govern_inference_messages(
        preset=preset, profile_prefix='profile', request_payload='question',
        evidence=chat.selector_evidence_payload(attachment_context=context, rendered_context=''))
    rendered = '\n'.join(m['content'] for m in messages)
    assert not packet.omissions
    for r in receipts:
        assert (f'"calculation_ref":"{r["calculation_ref"]}"' in rendered) == (r['source_row'] in chosen['shown'])
    # A second planning read neither consumes an attempt nor changes the receipt.
    _, repeated = chat.fit_smeta_portion_context(
        text, session_id='s', limit=25, cursors=cursor, preset=preset,
        profile_prefix='profile', request_payload='question')
    assert repeated['shown'] == chosen['shown']
    assert repeated['pass_no'] == chosen['pass_no']


def test_one_oversized_row_is_reported_and_still_pending(tmp_path):
    preset = ModelExecutionPreset('budget-test', 'qwen', 32768, 8192, 2048, 3, 5, 5, 1, False, ('test',))
    text = 'Файл: receipt.xlsx\nS!R1: № | Наименование | Ед. изм | Количество\nS!R2: 1 | ' + 'X' * 70000 + ' | шт | 1\n'
    context, state = chat.fit_smeta_portion_context(text, session_id='s', limit=25, cursors=None,
        preset=preset, profile_prefix='profile', request_payload='question')
    assert state['context_budget_exceeded'] is True
    assert state['pending'] == 1 and state['completed'] == 0
    messages, _ = chat.govern_inference_messages(preset=preset, profile_prefix='profile', request_payload='question',
        evidence=chat.selector_evidence_payload(attachment_context=context, rendered_context=''))
    assert '[ОХВАТ РАСЧЁТА]' in '\n'.join(m['content'] for m in messages)


def test_non_vor_attachment_is_not_replanned():
    preset = ModelExecutionPreset('budget-test', 'qwen', 32768, 8192, 2048, 3, 5, 5, 1, False, ('test',))
    context, state = chat.fit_smeta_portion_context('A letter', session_id='s', limit=25, cursors=None,
        preset=preset, profile_prefix='profile', request_payload='question')
    assert context == 'A letter' and state['state'] == 'not-a-vor'


@pytest.mark.parametrize('count', [8, 12, 25])
def test_default_portion_offers_all_source_rows_that_fit(count, monkeypatch):
    monkeypatch.delenv('LES_SMETA_PORTION_ROWS', raising=False)
    text = 'Файл: short.xlsx\nS!R1: № | Наименование | Ед. изм | Количество\n'
    text += '\n'.join(f'S!R{i+1}: {i} | Fixture {i} | шт | 1' for i in range(1, count+1))
    preset = ModelExecutionPreset('budget-test', 'qwen', 32768, 8192, 2048, 3, 5, 5, 1, False, ('test',))
    _, state = chat.fit_smeta_portion_context(text, session_id='s',
        limit=chat.smeta_portion_rows(text), cursors=None, preset=preset,
        profile_prefix='profile', request_payload='question')
    assert state['context_budget']['fits']
    assert state['shown'] == [f'S!{i}' for i in range(1, count+1)]
    assert state['completed'] == 0 and state['pending'] == count


@pytest.mark.parametrize('configured', ['1', '7', '25', '0', '-1'])
def test_explicit_portion_limit_and_disable_remain_authoritative(configured, monkeypatch):
    monkeypatch.setenv('LES_SMETA_PORTION_ROWS', configured)
    assert chat.smeta_portion_rows('ordinary attachment') == int(configured)


def test_invalid_cap_uses_source_budget_default(monkeypatch):
    monkeypatch.setenv('LES_SMETA_PORTION_ROWS', 'invalid')
    text = 'S!R1: № | Наименование | Ед. изм | Количество\n'
    text += '\n'.join(f'S!R{i+1}: {i} | Fixture {i} | шт | 1' for i in range(1, 9))
    assert chat.smeta_portion_rows(text) == 8
