"""Real awaits and durable job pauses; no model/API network or user data."""
import asyncio
from copy import deepcopy
import json
import sqlite3
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as app

from proxy.routers import chat
from proxy.services.workbook_research_job_service import WorkbookResearchJobError, WorkbookResearchJobService
from tests import test_model_rag_sheet_evidence_reads as fixture


def job(store, session='owned-cancel-test'):
    identity = store.identity(session_id=session, attachment_id='read_123456abcdef',
        source_sha256='a' * 64, dataset_ids=['selected'], profile_revision_id='profile',
        model_identity='model', question='Literal user task')
    current = store.begin_or_resume(identity)
    return store.record_packet(current['job_id'], sheet='S', packet_locators=['S!R2'],
        accepted_rows=[{'source_row': 'S!R2', 'row_role': 'work', 'title': 'Saved authored work',
            'unit': 'm', 'quantity': 12, 'norm_status': 'MISSING', 'open_gap': 'Authored question'}],
        evidence=[], remaining=['S!R15'])


@pytest.mark.parametrize('status,cancelled,kind,expected', [
    ('running', 0, '', False), ('running', 1, '', True),
    ('paused', 0, 'stalled', False), ('paused', 0, 'held_retry_exhausted', False),
    ('paused', 0, 'run_end', True), ('paused', 0, 'run_budget', True),
    ('paused', 0, '', True), ('paused', 0, 'future_guard_kind', True),
    ('paused', 1, 'stalled', True), ('cancelled', 0, '', True),
    ('complete', 0, '', False), ('failed', 0, '', False),
])
def test_narrow_run_stop_read_preserves_existing_guard_semantics(tmp_path, status, cancelled, kind, expected):
    store = WorkbookResearchJobService(tmp_path / 'guard.sqlite')
    current = job(store)
    with store._connect() as conn:
        conn.execute('UPDATE workbook_research_jobs SET status=?,cancel_requested=?,pause_kind=? WHERE job_id=?',
            (status, cancelled, kind, current['job_id']))
    assert store.run_should_stop(current['job_id']) is expected
    with pytest.raises(WorkbookResearchJobError, match='workbook research job not found'):
        store.run_should_stop('absent-owned-job')


def test_run_stop_poll_fetches_only_three_small_fields_without_decoding_large_job_json(tmp_path, monkeypatch):
    store = WorkbookResearchJobService(tmp_path / 'large-owned.sqlite')
    current = job(store)
    payload = json.dumps({'literal': 'x' * 1_048_576})
    real_connect = store._connect
    with real_connect() as conn:
        conn.execute('UPDATE workbook_research_jobs SET accepted_rows_json=?,evidence_json=?,query_cache_json=? '
            'WHERE job_id=?', (payload, payload, payload, current['job_id']))
    traces, fetched = [], []
    def connect():
        conn = real_connect()
        conn.set_trace_callback(traces.append)
        def only_small_guard_fields(cursor, values):
            columns = tuple(column[0] for column in cursor.description)
            assert columns == ('status', 'cancel_requested', 'pause_kind')
            assert sum(len(str(value)) for value in values) < 128
            fetched.append((columns, values))
            return sqlite3.Row(cursor, values)
        conn.row_factory = only_small_guard_fields
        return conn
    def forbidden_decode(*args, **kwargs):
        pytest.fail('A cancellation poll must not decode saved job JSON')
    monkeypatch.setattr(store, '_connect', connect)
    monkeypatch.setattr(json, 'loads', forbidden_decode)
    for _ in range(3):
        assert store.run_should_stop(current['job_id']) is False
    with real_connect() as conn:
        conn.execute('UPDATE workbook_research_jobs SET cancel_requested=1 WHERE job_id=?', (current['job_id'],))
    assert store.run_should_stop(current['job_id']) is True
    assert len(fetched) == len(traces) == 4
    assert all(query.partition(' FROM ')[0] == 'SELECT status,cancel_requested,pause_kind' for query in traces)


@pytest.mark.asyncio
async def test_no_job_guard_preserves_the_result_and_invokes_once():
    calls = []
    async def complete():
        calls.append('literal')
        return ('original response', {'completion_tokens': 7})
    assert await app.await_workbook_model_call(complete) == ('original response', {'completion_tokens': 7})
    assert calls == ['literal']


@pytest.mark.asyncio
async def test_preexisting_stop_never_dispatches_a_model_call():
    def forbidden():
        pytest.fail('Model called after durable stop')
    with pytest.raises(asyncio.CancelledError):
        await app.await_workbook_model_call(forbidden, should_stop=lambda: True)


@pytest.mark.asyncio
async def test_api_pause_cancels_a_hanging_await_and_preserves_accepted_rows(tmp_path, monkeypatch):
    store = WorkbookResearchJobService(tmp_path / 'owned.sqlite')
    original = job(store)
    monkeypatch.setattr(chat, 'WorkbookResearchJobService', lambda: store)
    entered, cleaned = asyncio.Event(), asyncio.Event()
    calls = []
    async def hanging():
        calls.append('once')
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned.set()
    worker = asyncio.create_task(app.await_workbook_model_call(hanging,
        should_stop=lambda: store.run_should_stop(original['job_id']), poll_seconds=0.001))
    await asyncio.wait_for(entered.wait(), 1)
    paused = await chat.pause_workbook_research(original['job_id'], _user=SimpleNamespace())
    assert paused['status'] == 'paused' and paused['cancel_requested'] is False
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(worker, 1)
    assert cleaned.is_set() and calls == ['once']
    assert store.get(original['job_id'])['accepted_rows'] == original['accepted_rows']
    assert store.get(original['job_id'])['remaining'] == original['remaining']


@pytest.mark.asyncio
async def test_packet_only_guard_pause_does_not_cancel_an_unrelated_inflight_call(tmp_path):
    store = WorkbookResearchJobService(tmp_path / 'packet.sqlite')
    current = job(store)
    for _ in range(3):
        current = store.record_packet(current['job_id'], sheet='S', packet_locators=['S!R15'],
            accepted_rows=[], evidence=[], remaining=['S!R15'])
        if current['status'] == 'paused':
            break
    assert current['status'] == 'paused'
    assert current['stall_guard']['pause_kind'] in {'stalled', 'held_retry_exhausted'}
    assert store.should_cancel(current['job_id']) is True
    assert store.run_should_stop(current['job_id']) is False
    async def complete():
        await asyncio.sleep(0.01)
        return 'kept'
    assert await app.await_workbook_model_call(complete,
        should_stop=lambda: store.run_should_stop(current['job_id']), poll_seconds=0.001) == 'kept'


@pytest.mark.asyncio
async def test_stopping_one_job_does_not_interrupt_another(tmp_path):
    store = WorkbookResearchJobService(tmp_path / 'two.sqlite')
    one, two = job(store, 'one'), job(store, 'two')
    entered = [asyncio.Event(), asyncio.Event()]
    release_other = asyncio.Event()
    cleaned = []
    async def complete(index):
        entered[index].set()
        try:
            await release_other.wait()
            return index
        finally:
            cleaned.append(index)
    tasks = [asyncio.create_task(app.await_workbook_model_call(lambda index=i: complete(index),
        should_stop=lambda current=current: store.run_should_stop(current['job_id']), poll_seconds=0.001))
        for i, current in enumerate([one, two])]
    await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered)), 1)
    store.request_cancel(one['job_id'])
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(tasks[0], 1)
    assert not tasks[1].done() and cleaned == [0]
    release_other.set()
    assert await tasks[1] == 1 and cleaned == [0, 1]


@pytest.mark.asyncio
async def test_completed_response_wins_stop_race_and_next_call_is_not_dispatched():
    stopped, calls = False, []
    async def complete():
        nonlocal stopped
        calls.append('completed')
        stopped = True
        return 'finished exact response'
    assert await app.await_workbook_model_call(complete, should_stop=lambda: stopped,
        poll_seconds=0.001) == 'finished exact response'
    with pytest.raises(asyncio.CancelledError):
        await app.await_workbook_model_call(complete, should_stop=lambda: stopped)
    assert calls == ['completed']


@pytest.mark.asyncio
async def test_external_cancellation_awaits_the_call_cleanup():
    entered, cleaned = asyncio.Event(), asyncio.Event()
    async def hanging():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned.set()
    task = asyncio.create_task(app.await_workbook_model_call(hanging, should_stop=lambda: False))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize('error_type', [ValueError, app.ModelTransportError])
async def test_model_failure_is_not_retried_or_converted_into_cancellation(error_type):
    calls = []
    async def failing():
        calls.append('literal request')
        await asyncio.sleep(0)
        raise error_type('original technical failure')
    with pytest.raises(error_type, match='original technical failure'):
        await app.await_workbook_model_call(failing, should_stop=lambda: False)
    assert calls == ['literal request']


@pytest.mark.asyncio
async def test_network_error_during_cancel_cleanup_remains_visible():
    entered = asyncio.Event()
    stopped = False
    async def hanging():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            raise app.ModelTransportError('cleanup network failure')
    task = asyncio.create_task(app.await_workbook_model_call(hanging,
        should_stop=lambda: stopped, poll_seconds=0.001))
    await entered.wait()
    stopped = True
    with pytest.raises(app.ModelTransportError, match='cleanup network failure'):
        await task


@pytest.mark.asyncio
async def test_actual_completed_packet_wins_pause_race_without_dispatching_the_next_packet(tmp_path, monkeypatch):
    monkeypatch.setattr(fixture, 'service', app)
    original = app.BoundModelChatRunner.complete
    requests = []
    baseline = []
    async def pause_after_response(self, **kwargs):
        requests.append(kwargs['request'])
        result = await original(self, **kwargs)
        if len(requests) == 4:
            store = WorkbookResearchJobService()
            current = store.latest(session_id='sheet-session', attachment_id='read_123456abcdef')
            baseline.append(current['job_id'])
            await chat.pause_workbook_research(current['job_id'], _user=SimpleNamespace())
        return result
    monkeypatch.setattr(app.BoundModelChatRunner, 'complete', pause_after_response)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=True, packet_count=2)
    assert len(requests) == 4, 'Pause after a completed response must prevent the next model dispatch'
    assert len(run.executions) == 1
    current = WorkbookResearchJobService().get(baseline[0])
    assert len(current['accepted_rows']) == 2 and current['status'] == 'paused'
    assert set(current['remaining']) == {'S!R4', 'S!R5'}
    assert baseline[0] not in app._LIVE_SHEET_PASS_GATES


@pytest.mark.asyncio
@pytest.mark.parametrize('hang_at', [1, 3, 5, 7])
async def test_actual_sheet_query_or_native_continuation_stops_without_retry_or_baseline_loss(
    tmp_path, monkeypatch, hang_at,
):
    monkeypatch.setattr(fixture, 'service', app)
    original = app.BoundModelChatRunner.complete
    entered, cleaned = asyncio.Event(), asyncio.Event()
    requests = []
    async def hanging(self, **kwargs):
        requests.append(kwargs['request'])
        if len(requests) == hang_at:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                cleaned.set()
        return await original(self, **kwargs)
    monkeypatch.setattr(app.BoundModelChatRunner, 'complete', hanging)
    task = asyncio.create_task(fixture._run_sheet(tmp_path, monkeypatch, reads=True, packet_count=2))
    await asyncio.wait_for(entered.wait(), 5)
    store = WorkbookResearchJobService()
    before = store.latest(session_id='sheet-session', attachment_id='read_123456abcdef')
    saved_rows = deepcopy(before['accepted_rows'])
    paused = await chat.pause_workbook_research(before['job_id'], _user=SimpleNamespace())
    assert paused['status'] == 'paused'
    run = await asyncio.wait_for(task, 5)
    assert cleaned.is_set() and len(requests) == hang_at
    after = store.get(before['job_id'])
    assert after['accepted_rows'] == saved_rows and after['status'] == 'paused'
    assert before['job_id'] not in app._LIVE_SHEET_PASS_GATES
    if hang_at in {5, 7}:
        assert len(saved_rows) == 2 and len(run.executions) == 1
        delivered = run.executions[0][0]['args']['decisions']
        assert [row['source_row'] for row in delivered] == [row['source_row'] for row in saved_rows]
        assert run.executions[0][1]['artifact']['download_url']
    if hang_at in {3, 7}:
        assert any(message['role'] == 'tool' for message in requests[-1].messages)
        assert after['task_context'].get('model_evidence_reads'), 'Completed native reads must stay durable'
