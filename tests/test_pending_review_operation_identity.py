"""Review identities are explicit; source/title/role never decide operation identity."""
from copy import deepcopy
import inspect
import json

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services.workbook_research_job_service import WorkbookResearchJobService as Store


def baseline(tmp_path):
    store = Store(tmp_path / 'owned.sqlite')
    job = store.begin_or_resume(store.identity(session_id='owned-review', attachment_id='read_123456abcdef',
        source_sha256='a' * 64, dataset_ids=[], profile_revision_id='same', model_identity='same', question='Original'))
    rows = [{'source_row': f'S!R{i + 2}', 'row_role': 'work', 'work_row': '', 'title': f'Authored work {i}',
             'unit': 'm', 'quantity': i + 1, 'open_gap': ''} for i in range(7)]
    job = store.record_packet(job['job_id'], sheet='S', packet_locators=[row['source_row'] for row in rows],
        accepted_rows=rows, evidence=[], remaining=[])
    store.finish(job['job_id'], status='complete')
    original = store.get(job['job_id'])
    ids = [row['operation_id'] for row in original['accepted_rows']]
    queued = store.reopen_locators(job['job_id'], [row['source_row'] for row in rows],
        preserve_accepted=True, operation_ids=ids)
    return store, original, queued


def parse(rows, form):
    if form == 'json':
        raw = json.dumps({'artifact_kind': 'vor', 'rows': rows})
    else:
        columns = ['source_row', 'row_role', 'work_row', 'title', 'unit', 'quantity', 'open_gap']
        if form == 'markdown_explicit':
            columns += ['operation_id', 'expected_revision']
        raw = 'artifact_kind: vor\n| ' + ' | '.join(columns) + ' |\n| ' + ' | '.join(['---'] * len(columns)) + ' |\n'
        raw += '\n'.join('| ' + ' | '.join(str(row.get(key, '')) for key in columns) + ' |' for row in rows)
    decoded = app.parse_model_rag_result(raw)
    assert decoded is not None
    return decoded[1]


def record(store, queued, rows, *, enforce=True, canonicalize=None):
    locators = list(dict.fromkeys([*queued['remaining'], *(row['source_row'] for row in rows)]))
    return store.record_packet(queued['job_id'], sheet='S', packet_locators=locators,
        accepted_rows=rows, evidence=[], remaining=[], enforce_packet_scope=enforce,
        canonicalize_locator=canonicalize)


@pytest.mark.parametrize('form', ['json', 'markdown'])
@pytest.mark.parametrize('enforce', [False, True])
def test_seven_anonymous_review_rows_cannot_duplicate_two_changed_operations(tmp_path, form, enforce):
    store, original, queued = baseline(tmp_path)
    rows = [{key: value for key, value in row.items() if key not in {'operation_id', 'revision'}}
            for row in original['accepted_rows']]
    rows[1]['open_gap'] = 'Changed authored question'
    rows[5]['open_gap'] = 'A different authored question'
    decoded = parse(rows, form)
    assert len(decoded) == 7 and all('operation_id' not in row for row in decoded)
    current = record(store, queued, decoded, enforce=enforce)
    assert current['accepted_rows'] == original['accepted_rows']
    assert Store.pending_research_operation_ids(current) == Store.pending_research_operation_ids(queued)
    assert set(current['remaining']) == set(queued['remaining'])
    assert len(current['unapplied_proposals']) == 7
    assert {proposal['reason'] for proposal in current['unapplied_proposals']} == {'missing_operation_identity'}
    assert [proposal['decision'] for proposal in current['unapplied_proposals']] == decoded
    repeated = record(store, queued, decoded, enforce=enforce)
    assert repeated['accepted_rows'] == original['accepted_rows']
    assert repeated['unapplied_proposals'] == current['unapplied_proposals']


@pytest.mark.parametrize('form', ['json', 'markdown_explicit'])
def test_explicit_blank_identity_allows_legitimate_two_new_operations_at_one_existing_source(tmp_path, form):
    store, original, queued = baseline(tmp_path)
    rows = [{'source_row': 'S!R2', 'row_role': 'work', 'work_row': '', 'title': title,
             'unit': 'm', 'quantity': quantity, 'open_gap': '', 'operation_id': ''}
            for title, quantity in [('Different authored operation A', 3), ('Different authored operation B', 5)]]
    decoded = parse(rows, form)
    assert all('operation_id' in row and row['operation_id'] == '' for row in decoded)
    current = record(store, queued, decoded)
    assert current['accepted_rows'][:7] == original['accepted_rows']
    assert len(current['accepted_rows']) == 9
    assert len({row['operation_id'] for row in current['accepted_rows']}) == 9
    assert Store.pending_research_operation_ids(current) == Store.pending_research_operation_ids(queued)
    assert not current['unapplied_proposals']


def test_new_source_without_prior_operation_does_not_require_a_synthetic_identity(tmp_path):
    store, original, queued = baseline(tmp_path)
    row = {'source_row': 'S!R15', 'row_role': 'work', 'title': 'New authored operation', 'unit': 'm', 'quantity': 2}
    current = record(store, queued, [row])
    assert current['accepted_rows'][:7] == original['accepted_rows']
    assert len(current['accepted_rows']) == 8 and current['accepted_rows'][-1]['source_row'] == 'S!R15'
    assert not current['unapplied_proposals']


@pytest.mark.parametrize('source', ['s!r2', 'LOCATOR:S!R2', 'R2'])
def test_equivalent_technical_source_addresses_do_not_bypass_the_identity_guard(tmp_path, source):
    store, original, queued = baseline(tmp_path)
    row = {'source_row': source, 'row_role': 'work', 'title': 'Changed authored operation', 'unit': 'm', 'quantity': 2}
    def canonicalize(value):
        return 'S!R2' if value == 'R2' else value
    current = record(store, queued, [row], canonicalize=canonicalize)
    assert current['accepted_rows'] == original['accepted_rows']
    assert current['unapplied_proposals'][0]['reason'] == 'missing_operation_identity'
    assert current['unapplied_proposals'][0]['decision'] == row


@pytest.mark.parametrize('enforce', [False, True])
@pytest.mark.parametrize('padded_id,source', [
    (True, 'S!R2'), (False, 's!r2'), (True, 's!r2'), (False, 'LOCATOR:S!R2'), (True, 'R2'),
])
def test_technical_identity_aliases_cannot_rewrite_a_closed_sibling_of_the_target(
    tmp_path, enforce, padded_id, source,
):
    store = Store(tmp_path / 'siblings.sqlite')
    current = store.begin_or_resume(store.identity(session_id='owned-siblings', attachment_id='read_123456abcdef',
        source_sha256='a' * 64, dataset_ids=[], profile_revision_id='same', model_identity='same', question='Original'))
    rows = [{'source_row': 'S!R2', 'row_role': 'work', 'title': title, 'unit': 'm', 'quantity': 12}
            for title in ['Closed untouched operation', 'Explicit pending review target']]
    current = store.record_packet(current['job_id'], sheet='S', packet_locators=['S!R2'],
        accepted_rows=rows, evidence=[], remaining=[])
    original = deepcopy(current['accepted_rows'])
    store.finish(current['job_id'], status='complete')
    closed, target = original
    queued = store.reopen_locators(current['job_id'], ['S!R2'], preserve_accepted=True,
        operation_ids=[target['operation_id']])
    attempted = {**closed, 'title': 'UNREQUESTED MODEL REWRITE', 'quantity': 999,
        'operation_id': ' ' + closed['operation_id'] + ' ' if padded_id else closed['operation_id'],
        'source_row': source, 'expected_revision': closed['revision']}
    def canonicalize(value):
        return 'S!R2' if value == 'R2' else value
    after = record(store, queued, [attempted], enforce=enforce, canonicalize=canonicalize)
    assert after['accepted_rows'] == original
    assert Store.pending_research_operation_ids(after) == {target['operation_id']}
    assert Store.pending_research_locators(after) == {'S!R2'}
    assert len(after['unapplied_proposals']) == 1
    assert after['unapplied_proposals'][0]['reason'] == 'existing_operation_outside_explicit_research_targets'
    assert after['unapplied_proposals'][0]['decision'] == attempted


@pytest.mark.parametrize('source', ['s!r2', 'LOCATOR:S!R2', 'R2'])
def test_admitted_target_alias_closes_pending_with_a_strict_canonical_packet(tmp_path, source):
    store = Store(tmp_path / 'target-alias.sqlite')
    job = store.begin_or_resume(store.identity(session_id='owned-target-alias', attachment_id='read_123456abcdef',
        source_sha256='a' * 64, dataset_ids=[], profile_revision_id='same', model_identity='same', question='Original'))
    job = store.record_packet(job['job_id'], sheet='S', packet_locators=['S!R2'],
        accepted_rows=[{'source_row': 'S!R2', 'row_role': 'work', 'title': title, 'unit': 'm', 'quantity': 12}
                       for title in ['Closed sibling', 'Requested target']], evidence=[], remaining=[])
    closed, target = deepcopy(job['accepted_rows'])
    store.finish(job['job_id'], status='complete')
    store.reopen_locators(job['job_id'], ['S!R2'], preserve_accepted=True, operation_ids=[target['operation_id']])
    authored = {**target, 'source_row': source, 'title': 'Authored target revision',
                'operation_id': ' ' + target['operation_id'] + ' ', 'expected_revision': target['revision']}
    def canonicalize(value):
        return 'S!R2' if value == 'R2' else value
    after = store.record_packet(job['job_id'], sheet='S', packet_locators=['S!R2'], accepted_rows=[authored],
        evidence=[], remaining=['S!R2'], enforce_packet_scope=True, canonicalize_locator=canonicalize)
    assert after['accepted_rows'][0] == closed
    assert after['accepted_rows'][1]['operation_id'] == target['operation_id']
    assert after['accepted_rows'][1]['source_row'] == source and after['accepted_rows'][1]['revision'] == 2
    assert after['accepted_rows'][1]['title'] == authored['title']
    assert not Store.pending_research_operation_ids(after) and not Store.pending_research_locators(after)
    assert after['remaining'] == [] and not after['unapplied_proposals']
    answered = store.list_events(job['job_id'], 'research_targets_answered')
    assert answered[-1]['payload']['operation_ids'] == [target['operation_id']]


def test_target_alias_resolves_only_its_own_pending_scope(tmp_path):
    store, original, queued = baseline(tmp_path)
    target = original['accepted_rows'][0]
    authored = {**target, 'source_row': 's!r2', 'coverage': 'A changed authored decision',
                'expected_revision': target['revision']}
    after = store.record_packet(queued['job_id'], sheet='S', packet_locators=['S!R2'], accepted_rows=[authored],
        evidence=[], remaining=queued['remaining'], enforce_packet_scope=True)
    assert after['accepted_rows'][1:] == original['accepted_rows'][1:]
    assert Store.pending_research_operation_ids(after) == {
        row['operation_id'] for row in original['accepted_rows'][1:]}
    assert Store.pending_research_locators(after) == {row['source_row'] for row in original['accepted_rows'][1:]}
    assert 'S!R2' not in after['remaining']


def test_admitted_new_work_alias_closes_only_the_unassigned_source_target(tmp_path):
    store = Store(tmp_path / 'unassigned-alias.sqlite')
    job = store.begin_or_resume(store.identity(session_id='owned-unassigned', attachment_id='read_123456abcdef',
        source_sha256='a' * 64, dataset_ids=[], profile_revision_id='same', model_identity='same', question='Original'))
    job = store.record_packet(job['job_id'], sheet='S', packet_locators=['S!R2'], accepted_rows=[{
        'source_row': 'S!R2', 'row_role': 'material', 'title': 'Literal authored material', 'unit': 'm', 'quantity': 12}],
        evidence=[], remaining=[])
    original = deepcopy(job['accepted_rows'])
    store.finish(job['job_id'], status='complete')
    store.reopen_locators(job['job_id'], ['S!R2'], preserve_accepted=True, operation_ids=[])
    after = store.record_packet(job['job_id'], sheet='S', packet_locators=['S!R2'], accepted_rows=[{
        'source_row': 's!r2', 'row_role': 'work', 'title': 'A model-authored new work', 'unit': 'm', 'quantity': 12}],
        evidence=[], remaining=['S!R2'], enforce_packet_scope=True)
    assert after['accepted_rows'][:1] == original and after['accepted_rows'][1]['source_row'] == 's!r2'
    assert not Store.pending_research_locators(after) and not after['remaining']
    assert not after['task_context']['pending_research_unassigned_locators']


def test_pending_helpers_match_the_catalog_without_changing_literal_rows():
    from proxy.services.attachment_source_catalog_service import AttachmentSourceCatalog, CatalogRow
    catalog = AttachmentSourceCatalog('source.xlsx', (('S', 2),), tuple(
        CatalogRow(f'S!R{n}', 'S', n, ('Literal', 'm', '12'), f'S!R{n}: Literal | m | 12', (12,))
        for n in [2, 3]))
    rows = [{'source_row': 's!r2', 'operation_id': 'op-owned', 'row_role': 'work', 'title': 'Authored work'},
            {'source_row': 'S!R3', 'operation_id': 'closed-other', 'row_role': 'work', 'title': 'Other work'}]
    job = {'accepted_rows': rows, 'task_context': {'pending_research_locators': ['s!r2'],
        'pending_research_operation_ids': ['op-owned']}}
    before = deepcopy(job)
    assert app.research_settled_source_keys(rows, catalog, job) == {'S!R3'}
    context = app.model_rag_research_target_context(job, ['S!R2'], source_catalog=catalog)
    assert context['research_target_source_rows'] == ['S!R2']
    assert context['research_target_operation_ids'] == ['op-owned']
    assert app.model_rag_research_target_context(job, ['S!R3'], source_catalog=catalog) == {}
    assert job == before


@pytest.mark.parametrize('identity', [None, False, 0])
def test_non_string_empty_identity_is_not_an_explicit_new_operation(tmp_path, identity):
    store, original, queued = baseline(tmp_path)
    row = {'source_row': 'S!R2', 'row_role': 'work', 'title': 'Different authored work', 'unit': 'm',
           'quantity': 2, 'operation_id': identity}
    current = record(store, queued, parse([row], 'json'))
    assert current['accepted_rows'] == original['accepted_rows']
    assert current['unapplied_proposals'][0]['reason'] == 'missing_operation_identity'


def test_known_identity_revision_and_stale_guards_are_unchanged(tmp_path):
    store, original, queued = baseline(tmp_path)
    previous = original['accepted_rows'][0]
    changed = {**previous, 'quantity': 20, 'expected_revision': previous['revision']}
    current = record(store, queued, [changed])
    assert current['accepted_rows'][0]['operation_id'] == previous['operation_id']
    assert current['accepted_rows'][0]['quantity'] == 20 and current['accepted_rows'][0]['revision'] == 2
    stale = record(store, current, [{**changed, 'quantity': 999}])
    assert stale['accepted_rows'] == current['accepted_rows']
    assert stale['unapplied_proposals'][-1]['reason'] == 'operation_revision_mismatch'


def test_pending_instruction_names_identity_columns_and_explicit_new_operation(tmp_path):
    store, _original, queued = baseline(tmp_path)
    before = deepcopy(queued)
    context = app.model_rag_research_target_context(queued, ['S!R2'])
    instruction = context['research_scope_instruction']
    assert 'После основных полей строк явно добавь две колонки operation_id и expected_revision' in instruction
    assert 'operation_id=""' in instruction and 'пустую ячейку в отдельной колонке operation_id' in instruction
    assert queued == before
    assert app.model_rag_research_target_context(queued, ['Other!R2']) == {}


def test_explicit_empty_block_identity_is_preserved_by_parser():
    raw = 'artifact_kind: vor\nsource_row: S!R2\noperation_id:\nrow_role: work\ntitle: New work\nunit: m\nquantity: 2\n'
    decoded = app.parse_model_rag_result(raw)
    assert decoded is not None and decoded[1][0]['operation_id'] == ''


@pytest.mark.asyncio
@pytest.mark.parametrize('variant', ['missing_json', 'missing_markdown', 'known_revision', 'explicit_new', 'known_alias'])
async def test_actual_sheet_review_keeps_seven_baselines_until_the_model_identifies_its_changes(
    tmp_path, monkeypatch, variant,
):
    from proxy.services.openai_compatible_transport_service import InferenceResponse
    from tests import test_model_rag_sheet_evidence_reads as fixture

    rows = [{'source_row': 'S!R2' if i < 6 else 'S!R3', 'row_role': 'work', 'work_row': '',
             'title': f'Author-selected operation {i}', 'unit': 'm', 'quantity': 12 if i < 6 else 3,
             'open_gap': ''} for i in range(7)]
    if variant == 'known_alias':
        for row in rows[:6]:
            row['source_row'] = 's!r2'
    query = json.dumps({'artifact_kind': 'vor', 'queries': []})
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, query_declaration=query,
        final_answer=json.dumps({'artifact_kind': 'vor', 'rows': rows}))
    store = Store()
    original_id = run.result['retrieval_trace']['workbook_research_job']['job_id']
    before = deepcopy(store.get(original_id)['accepted_rows'])
    assert len(before) == 7
    request = inspect.getclosurevars(run.resume_same_request).nonlocals['request']
    request.req.question = 'Учти замечание инженера и перепроверь документ'
    revised = [{key: row[key] for key in ('source_row', 'row_role', 'work_row', 'title', 'unit', 'quantity', 'open_gap')}
               for row in before]
    revised[1]['open_gap'] = 'Авторский вопрос о параметре одной операции'
    revised[5]['open_gap'] = 'Другой авторский вопрос'
    revised[1]['coverage'] = 'Изменённое моделью обоснование первой операции'
    revised[5]['coverage'] = 'Самостоятельное изменённое обоснование другой операции'
    if variant in {'known_revision', 'explicit_new', 'known_alias'}:
        for authored, old in zip(revised, before, strict=True):
            authored.update(operation_id=old['operation_id'], expected_revision=old['revision'])
    if variant == 'explicit_new':
        revised.extend([{**rows[0], 'operation_id': '', 'title': title}
                        for title in ['Explicit additional operation A', 'Explicit additional operation B']])
    if variant == 'missing_markdown':
        columns = ['source_row', 'row_role', 'title', 'unit', 'quantity', 'coverage', 'open_gap']
        answer = 'artifact_kind: vor\n| ' + ' | '.join(columns) + ' |\n| ' + ' | '.join(['---'] * 7) + ' |\n'
        answer += '\n'.join('| ' + ' | '.join(str(row.get(key, '')) for key in columns) + ' |' for row in revised)
    else:
        answer = json.dumps({'artifact_kind': 'vor', 'rows': revised})
    run.responses.extend([
        InferenceResponse(text=query, tool_calls=(), finish_reason='stop', usage={}),
        InferenceResponse(text=answer, tool_calls=(), finish_reason='stop', usage={}),
    ])
    initial_calls = len(run.requests)
    result = await run.resume_same_request()
    current = store.get(result['retrieval_trace']['workbook_research_job']['job_id'])
    assert len(run.requests) == initial_calls + 2 and not run.responses, 'Identity diagnostics must not buy a model retry'
    assert store.get(original_id)['accepted_rows'] == before
    if variant.startswith('missing_'):
        assert current['accepted_rows'] == before
        assert Store.pending_research_operation_ids(current) == {row['operation_id'] for row in before}
        assert len(current['unapplied_proposals']) == 7 and current['status'] == 'paused'
        assert {proposal['reason'] for proposal in current['unapplied_proposals']} == {'missing_operation_identity'}
    else:
        assert not Store.pending_research_operation_ids(current) and not current['remaining'], {
            'remaining': current['remaining'], 'phase': current['phase'],
            'pending_sources': Store.pending_research_locators(current),
            'unassigned': current['task_context'].get('pending_research_unassigned_locators'),
            'passes': result['retrieval_trace']['tool_loop']['passes'],
        }
        assert len(current['accepted_rows']) == (9 if variant == 'explicit_new' else 7)
        assert [row['operation_id'] for row in current['accepted_rows'][:7]] == [row['operation_id'] for row in before]
        assert [row['revision'] for row in current['accepted_rows'][:7]] == [1, 2, 1, 1, 1, 2, 1]
        assert current['accepted_rows'][1]['open_gap'] == revised[1]['open_gap']
        assert current['accepted_rows'][5]['open_gap'] == revised[5]['open_gap']
        assert current['accepted_rows'][1]['coverage'] == revised[1]['coverage']
        assert current['accepted_rows'][5]['coverage'] == revised[5]['coverage']
        assert not current['unapplied_proposals']
        if variant == 'known_alias':
            assert before[0]['source_row'] == current['accepted_rows'][0]['source_row'] == 's!r2'
            for captured in run.requests[-2:]:
                carriers = []
                for message in captured.messages:
                    for line in str(message.get('content') or '').splitlines():
                        try:
                            payload = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(payload, dict) and payload.get('research_target_operation_ids'):
                            carriers.append(payload)
                assert carriers, 'Canonical packet must retain the aliased pending target context'
                assert set(carriers[0]['research_target_operation_ids']) == {row['operation_id'] for row in before}
                prior_by_id = {row['operation_id']: row for row in carriers[0]['prior_model_decisions']}
                assert prior_by_id[before[0]['operation_id']]['source_row'] == 's!r2'
                assert len(carriers[0]['prior_model_decisions']) == 7
