"""A rejected packet query cannot be disguised by a later sheet's header."""
from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json

import openpyxl
import pytest

from proxy.services import chat_evidence_application_service as application
from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.model_research_tool_service import ModelResearchToolService
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from proxy.services.workbook_research_job_service import _packaged_price_basis
from tests import test_model_rag_sheet_evidence_reads as fixture


def _unsupported_declaration() -> str:
    # Finished valid JSON with no supported query carrier, not a cut answer.
    raw = json.dumps({'other_queries': ['literal operation search'], 'note': ''})
    return raw[:-2] + ('x' * (1242 - len(raw))) + raw[-2:]


@pytest.mark.asyncio
@pytest.mark.parametrize('first_sheet,later_sheet,prior_accepted', [
    ('PDF', 'PDF_TEXT', False),
    ('Монтаж Ω', 'Пояснение Ж', False),
    ('Электрика Ж', 'Титул Ω', True),
], ids=['pdf-like-sheet-layout', 'unicode-xlsx-layout', 'prior-packet-preserved'])
async def test_failed_packet_query_is_paused_before_later_header_can_mask_it(
        tmp_path, monkeypatch, first_sheet, later_sheet, prior_accepted):
    monkeypatch.setenv('RAG_META_DB_PATH', str(tmp_path / 'owned-jobs.sqlite'))
    monkeypatch.setenv('LES_CHAT_SOURCE_FRAME_ROWS', '4')
    snapshot = {}
    calls = []
    searches = []
    histories = []
    original_attachment = fixture.preserve_read_attachment
    original_begin = WorkbookResearchJobService.begin_or_resume
    original_application = application.run_chat_evidence_application
    original_failure = application.model_query_failure
    original_search = ModelResearchToolService.execute
    title = 'Проект Ω — титульные сведения без таблицы, выпуск 8'
    locators = [f'{first_sheet}!R2', f'{first_sheet}!R3', f'{later_sheet}!R1']
    malformed = _unsupported_declaration()
    assert len(malformed) == 1242 and json.loads(malformed)['other_queries']
    responses = [
        InferenceResponse(text=malformed, tool_calls=(), finish_reason='stop',
                          usage={'completion_tokens': 503}),
        InferenceResponse(text=malformed, tool_calls=(), finish_reason='stop',
                          usage={'completion_tokens': 504}),
        InferenceResponse(text=json.dumps({'artifact_kind': 'lsr', 'queries': [
            f'{later_sheet}!R1 — literal title lookup']}), tool_calls=(),
                          finish_reason='stop', usage={'completion_tokens': 805}),
        InferenceResponse(text=json.dumps({'artifact_kind': 'lsr', 'rows': [{
            'source_row': f'{later_sheet}!R1', 'row_role': 'header', 'work_row': '',
            'title': title, 'unit': '', 'quantity': '', 'norm_code': '',
            'norm_status': '', 'open_gap': 'No work table in this offered title row.',
            'evidence_refs': []}]}), tool_calls=(), finish_reason='stop',
                          usage={'completion_tokens': 2875}),
    ]

    def two_sheet_attachment(path, **kwargs):
        workbook = openpyxl.load_workbook(path)
        workbook.active.title = first_sheet
        # An independent numeric issue field makes this XLSX source row
        # ambiguous; only the model may adjudicate it as a title/header.
        workbook.create_sheet(later_sheet).append([title, 8])
        workbook.save(path)
        workbook.close()
        result = original_attachment(path, **kwargs)
        snapshot['source_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    def begin_with_prior_progress(self, identity, **kwargs):
        assert kwargs['source_locators'] == locators
        context = dict(kwargs.get('task_context') or {})
        context['fixture_prior_literal'] = {'text': 'existing source/task state Ω'}
        if prior_accepted:
            from proxy.services import model_pricebook_evidence_service as prices
            source = prices._provider(fixture.BOOK)
            snapshot['prior_book_quarter'] = source.book.quarter
            context['price_basis'] = _packaged_price_basis({
                'actual_book': fixture.BOOK, 'actual_region': source.book.region,
                'actual_quarter': source.book.quarter, 'match': 'exact',
                'pricebook_sha256': source.source_sha256})
        job = original_begin(self, identity, **{**kwargs, 'task_context': context})
        if prior_accepted:
            # A real earlier document packet also persisted its authored target.
            job = self.record_artifact_kind(job['job_id'],
                declaration=application.decode_model_artifact_kind('artifact_kind: lsr'))
            job = self.record_packet(job['job_id'], sheet=first_sheet,
                packet_locators=[locators[0]], accepted_rows=[{
                    'source_row': locators[0], 'row_role': 'work', 'title': 'Cable A',
                    'unit': 'm', 'quantity': 12, 'norm_code': '',
                    'norm_status': 'NEEDS_RESEARCH', 'open_gap': 'Previously authored unresolved norm.',
                    'evidence_refs': [], 'evidence_bindings': {},
                    'operation_id': 'permanent-prior-operation', 'revision': 1,
                }], evidence=[{'global_evidence_id': 'prior-global', 'content': 'whole prior evidence Ω',
                    'meta': {'source_sha256': 'b' * 64}}], remaining=locators[1:])
        job = self.record_search_cache(job['job_id'], {
            'previous literal search': [{'global_evidence_id': 'cache-global',
                'content': 'whole previous search evidence Ж', 'meta': {'source_sha256': 'c' * 64}}],
        }, cache_contract='prior-cache-contract')
        snapshot.update(store=self, before=copy.deepcopy(job), identity=identity)
        return job

    async def controlled_application(request, runtime, boundary):
        factory = runtime.model_connection_transport
        original_env_int = runtime.env_int

        def transport(client, secret_store):
            selected_transport = factory(client, secret_store)

            async def complete(selected, wire_request):
                calls.append(copy.deepcopy(wire_request))
                assert responses, 'A technical query-format error must not add a model retry'
                return responses.pop(0)

            selected_transport.complete = complete
            return selected_transport

        return await original_application(request,
            replace(runtime, model_connection_transport=transport,
                env_int=lambda key, default=0: 4 if key == 'LES_CHAT_SOURCE_FRAME_ROWS'
                    else original_env_int(key, default)),
            replace(boundary, save_chat_history=lambda **row: histories.append(row) or 'history-owned'))

    def observed_failure(detail, **kwargs):
        snapshot['failure_trace'] = copy.deepcopy(kwargs['trace'])
        return original_failure(detail, **kwargs)

    async def observed_search(self, call):
        # Returning a usable candidate makes the old silent sheet skip visible:
        # it can package the later header instead of surfacing the failed packet.
        searches.append(copy.deepcopy(call))
        return await original_search(self, call)

    monkeypatch.setattr(fixture, 'preserve_read_attachment', two_sheet_attachment)
    monkeypatch.setattr(WorkbookResearchJobService, 'begin_or_resume', begin_with_prior_progress)
    monkeypatch.setattr(application, 'run_chat_evidence_application', controlled_application)
    monkeypatch.setattr(application, 'model_query_failure', observed_failure)
    monkeypatch.setattr(ModelResearchToolService, 'execute', observed_search)

    if prior_accepted:
        run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant='B1_CANDIDATE')
        assert 'MODEL_RAG_QUERY_LIST_EMPTY' in run.result['answer']
        failure = run.result['retrieval_trace']['query_checkpoint_failure']
        assert failure['code'] == 'MODEL_RAG_QUERY_LIST_EMPTY'
        assert failure['technical_failure'] is True and failure['model_decisions_rewritten'] is False
        assert len(run.executions) == 1
        call, packaged = run.executions[0]
        assert call['args']['decisions'] == snapshot['before']['accepted_rows']
        assert packaged['artifact']['download_url']
        assert packaged['pricing_status'] == 'priced_partial'
        assert run.result['artifact']['draft'] is True
        assert len(histories) == 1
    else:
        with pytest.raises(application.HTTPException) as caught:
            await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant='B1_CANDIDATE')
        assert 'MODEL_RAG_QUERY_LIST_EMPTY' in str(caught.value.detail)
        assert histories == []
    assert len(calls) == 2 and searches == []
    expected_packet = [locators[1]] if prior_accepted else locators[:2]
    before, store = snapshot['before'], snapshot['store']
    after = store.get(before['job_id'])
    assert after['status'] == 'paused' and after['phase'] == 'model_query_format_pending'
    assert after['resumable'] is True
    assert after['held_packet']['sheet'] == first_sheet
    assert after['held_packet']['locators'] == expected_packet
    assert after['held_packet']['model_query_output_missing'] is True
    for field in ('accepted_rows', 'query_cache', 'remaining', 'evidence', 'identity'):
        assert after[field] == before[field], field
    expected_context = copy.deepcopy(before['task_context'])
    if prior_accepted:
        # The unchanged packaging path restores the exact book's period label
        # (begin_or_resume normalises it) and adds its empty inheritance marker.
        # Assert these two specific metadata changes; every other context,
        # selected book/hash/region/binding/match field remains exact.
        expected_context['price_basis']['quarter'] = snapshot['prior_book_quarter']
        expected_context['price_basis']['inherited_from'] = ''
    assert after['task_context'] == expected_context
    assert snapshot['identity'].source_sha256 == snapshot['source_sha256']
    assert before['task_context']['price_basis']
    assert before['task_context']['source_frame']['rows_per_frame'] == 4
    outputs = snapshot['failure_trace']['model_query_outputs']
    assert len(outputs) == 2
    assert [row['finish_reason'] for row in outputs] == ['stop', 'stop']
    assert [row['declared_parse']['output_shape'] for row in outputs] == ['unsupported_structured_output'] * 2
    assert after['held_packet']['query_output'] == outputs[-1]
    assert before['job_id'] not in application._LIVE_SHEET_PASS_GATES
    # Resume uses the same identity and exact held packet, without recreating or
    # silently settling the earlier authored decisions or the later title row.
    resumed = original_begin(store, snapshot['identity'])
    assert resumed['job_id'] == after['job_id'] and resumed['status'] == 'running'
    assert resumed['held_packet'] == after['held_packet']
    for field in ('accepted_rows', 'query_cache', 'task_context', 'remaining', 'evidence'):
        assert resumed[field] == after[field], field
