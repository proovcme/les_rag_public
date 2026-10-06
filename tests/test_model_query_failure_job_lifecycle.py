"""Terminal query-format failures release the loop and preserve its durable job."""
from __future__ import annotations

import copy
from dataclasses import replace
import json

import pytest

from proxy.routers import chat
from proxy.services import chat_evidence_application_service as application
from proxy.services.model_research_tool_service import ModelResearchToolService
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests.test_model_query_table_transport import FRESH_TABLE_OUTPUT
from tests.test_model_rag_sheet_evidence_reads import _run_sheet


@pytest.mark.asyncio
@pytest.mark.parametrize('malformed', [
    FRESH_TABLE_OUTPUT,
    '{"queries": ["literal unfinished query"',
], ids=['result-table', 'malformed-envelope'])
async def test_rejected_query_and_repair_keep_same_sse_error_but_pause_owned_job(tmp_path, monkeypatch, malformed):
    monkeypatch.setenv('RAG_META_DB_PATH', str(tmp_path / 'owned-jobs.sqlite'))
    snapshots = {}
    original_begin = WorkbookResearchJobService.begin_or_resume
    original_failure = application.model_query_failure
    failures = []

    def begin_with_durable_cache(self, identity, **kwargs):
        context = dict(kwargs.get('task_context') or {})
        context['durable_fixture'] = {'literal': 'unchanged source and task context'}
        job = original_begin(self, identity, **{**kwargs, 'task_context': context})
        job = self.record_search_cache(job['job_id'], {
            'previous literal cache query': [{'global_evidence_id': 'preserved-global-id',
                                            'content': 'previous exact whole evidence',
                                            'meta': {'source_sha256': 'b' * 64}}],
        }, cache_contract='unchanged-cache-contract')
        other_identity = replace(identity, session_id='unrelated-active-session',
                                 attachment_id='read_feedfacecafe', source_sha256='c' * 64)
        other = original_begin(self, other_identity, source_locators=['U!R7'],
                               task_context={'original_question': 'unrelated active task'})
        snapshots.update(store=self, before=copy.deepcopy(job),
                         other=copy.deepcopy(self.get(other['job_id'])), identity=identity)
        return job

    def failure(detail, **kwargs):
        failures.append(copy.deepcopy(kwargs['trace']))
        return original_failure(detail, **kwargs)

    async def no_search(self, call):
        pytest.fail('Rejected whole query declarations must never start RAG or native reads')

    async def failed_producer(request, token_sink=None):
        await _run_sheet(tmp_path, monkeypatch, reads=False, variant='B1_CANDIDATE',
                         query_repair=malformed, query_declaration=malformed)
        pytest.fail('The actual producer must preserve its original terminal query error')

    monkeypatch.setattr(WorkbookResearchJobService, 'begin_or_resume', begin_with_durable_cache)
    monkeypatch.setattr(application, 'model_query_failure', failure)
    monkeypatch.setattr(ModelResearchToolService, 'execute', no_search)
    monkeypatch.setattr(chat, '_run_chat', failed_producer)
    response = await chat.chat_stream(chat.ChatRequest(question='same failed query task',
                                                       session_id='sheet-session'), _user=None)
    body = ''.join([piece if isinstance(piece, str) else piece.decode('utf-8')
                    async for piece in response.body_iterator])
    error = json.loads(body.split('event: error\ndata: ', 1)[1].split('\n\n', 1)[0])
    assert error['code'] == 'MODEL_RAG_QUERY_LIST_EMPTY'
    assert 'NO_DATA' not in body and 'MISSING' not in body
    assert len(failures) == 1
    assert len(failures[0]['actual_model_calls']['calls']) == 2
    outputs = failures[0]['model_query_outputs']
    assert len(outputs) == 2  # original declaration and the existing one format repair
    assert all(out['declared_parse']['accepted_count'] == 0 for out in outputs)
    before, store = snapshots['before'], snapshots['store']
    job = store.get(before['job_id'])
    assert job['status'] == 'paused'
    assert job['phase'] == 'model_query_format_pending'
    assert job['resumable'] is True
    for field in ['accepted_rows', 'query_cache', 'task_context', 'remaining', 'evidence', 'identity']:
        assert job[field] == before[field], field
    assert job['held_packet']['sheet'] == 'S'
    assert job['held_packet']['locators'] == ['S!R2', 'S!R3']
    assert job['held_packet']['model_query_output_missing'] is True
    assert job['held_packet']['query_output'] == outputs[-1]
    assert before['job_id'] not in application._LIVE_SHEET_PASS_GATES
    assert store.get(snapshots['other']['job_id']) == snapshots['other']
    resumed = original_begin(store, snapshots['identity'])
    assert resumed['job_id'] == job['job_id'] and resumed['status'] == 'running'
    for field in ['accepted_rows', 'query_cache', 'task_context', 'remaining', 'evidence']:
        assert resumed[field] == job[field]


@pytest.mark.asyncio
async def test_joined_duplicate_cannot_pause_or_replace_another_running_owner(tmp_path, monkeypatch):
    monkeypatch.setenv('RAG_META_DB_PATH', str(tmp_path / 'joined-jobs.sqlite'))
    joined = {}
    original_failure = application.model_query_failure
    calls = []

    async def joined_existing(job_id):
        store = WorkbookResearchJobService()
        joined.update(store=store, before=copy.deepcopy(store.get(job_id)))
        return False

    def failure(detail, **kwargs):
        calls.extend((kwargs['trace'].get('actual_model_calls') or {}).get('calls') or [])
        return original_failure(detail, **kwargs)

    monkeypatch.setattr(application, 'claim_or_join_sheet_pass', joined_existing)
    monkeypatch.setattr(application, 'model_query_failure', failure)
    with pytest.raises(application.HTTPException) as caught:
        await _run_sheet(tmp_path, monkeypatch, reads=False, variant='B1_CANDIDATE',
                         query_repair=FRESH_TABLE_OUTPUT, query_declaration=FRESH_TABLE_OUTPUT)
    assert 'MODEL_RAG_QUERY_LIST_EMPTY' in json.dumps(caught.value.detail)
    assert joined['store'].get(joined['before']['job_id']) == joined['before']
    assert joined['before']['status'] == 'running'
    assert calls == []


@pytest.mark.asyncio
async def test_direct_baseline_query_failure_creates_no_job_or_new_model_attempt(tmp_path, monkeypatch):
    def forbidden_begin(*args, **kwargs):
        pytest.fail('B0 query failure must not enter durable sheet-job lifecycle')
    monkeypatch.setattr(WorkbookResearchJobService, 'begin_or_resume', forbidden_begin)
    with pytest.raises(application.HTTPException) as caught:
        await _run_sheet(tmp_path, monkeypatch, reads=False, variant='B0_DIRECT',
                         query_repair=FRESH_TABLE_OUTPUT, query_declaration=FRESH_TABLE_OUTPUT)
    assert 'MODEL_RAG_QUERY_LIST_EMPTY' in json.dumps(caught.value.detail)
