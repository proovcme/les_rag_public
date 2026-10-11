"""Overflow uses immutable rereadable evidence, never silently deletes sources."""
import copy
import json
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as chat
from proxy.services.context_governor_service import ContextRequiredSectionOverflow
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from proxy.services.model_research_tool_service import ModelResearchToolService
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests.test_model_rag_sheet_evidence_reads import _run_sheet


def _chunks(count=40, chars=4000):
    return [SimpleNamespace(doc_name=f'Literal document {n}', doc_id=f'doc-{n}',
        content=f'WHOLE_BODY_{n}:' + 'x' * chars,
        meta={'model_evidence_ref': f'Q{n + 1}.H1', 'global_evidence_id': f'global-{n}',
              'source_ref': f'source-{n}', 'source_sha256': str(n % 10) * 64,
              'body_status': 'full', 'model_delivery_status': 'delivered',
              'model_inventory_delivery_status': 'delivered', 'model_read_tool': 'read_source'})
        for n in range(count)]


def _preset(tokens=5000):
    return ModelExecutionPreset(preset_id='archive-regression', model_family='fixture',
        input_token_limit=tokens, generation_reserve_tokens=0, safety_reserve_tokens=0,
        normal_tool_count=5, max_tools=5, max_batch_items=6, parallel_read_limit=1,
        reasoning_enabled=False, source_chain=('fixture',))


def _tools():
    async def forbidden(*args, **kwargs):
        pytest.fail('Saved evidence reread must not query or reopen a changed source')
    return ModelResearchToolService(retrieve=forbidden, frozen_dataset_ids=('dataset',),
        retrieval_kwargs={}, fallback=forbidden)


def test_overflow_keeps_current_read_and_complete_source_with_archive_access():
    chunks = _chunks()
    before = copy.deepcopy([vars(c) for c in chunks])
    tools = _tools()
    archive = tools.register_evidence_archive(chunks)
    receipt = {'call': {'tool': 'read_source', 'call_id': 'current'},
               'evidence_refs': ['Q40.H1']}
    messages, packet, inventory, bodies = chat.govern_model_read_messages(
        preset=_preset(), profile_prefix='literal profile', request_payload='original question',
        source_context=['COMPLETE_SOURCE', {'previous_decision': {'quantity': 17, 'norm_code': 'MODEL_CHOICE'}}],
        chunks=chunks, receipts=[receipt], evidence_archive=archive, current_read_refs=['Q40.H1'])
    wire = json.dumps(messages)
    assert packet.included_tokens <= packet.input_budget_tokens
    assert all(text in wire for text in ['COMPLETE_SOURCE', 'original question', 'MODEL_CHOICE', 'WHOLE_BODY_39'])
    assert 'evidence_archive' in wire and archive.archive_id in wire
    assert 'Q40.H1' in bodies and set(bodies) < {f'Q{n + 1}.H1' for n in range(40)}
    assert set(bodies) <= set(inventory)
    assert [vars(c) for c in chunks] == before


def test_no_archive_reader_means_no_silent_context_loss():
    with pytest.raises(ContextRequiredSectionOverflow):
        chat.govern_model_read_messages(preset=_preset(), profile_prefix='profile', request_payload='task',
            source_context=['COMPLETE_SOURCE'], chunks=_chunks())


def test_single_current_body_that_cannot_fit_still_stops():
    tools = _tools()
    chunks = _chunks(1, chars=20000)
    with pytest.raises(ContextRequiredSectionOverflow):
        chat.govern_model_read_messages(preset=_preset(), profile_prefix='profile', request_payload='task',
            source_context=['COMPLETE_SOURCE'], chunks=chunks,
            evidence_archive=tools.register_evidence_archive(chunks), current_read_refs=['Q1.H1'])


@pytest.mark.parametrize('ambiguous', [False, True])
def test_unaddressable_historical_body_cannot_be_hidden_in_archive(ambiguous):
    chunks = _chunks(1, chars=20000)
    if ambiguous:
        other = copy.deepcopy(chunks[0])
        other.content = 'DIFFERENT_GENERATION' + 'y' * 20000
        chunks.append(other)
    else:
        chunks[0].meta.pop('model_evidence_ref')
    with pytest.raises(ContextRequiredSectionOverflow):
        chat.govern_model_read_messages(preset=_preset(), profile_prefix='profile', request_payload='task',
            source_context=['COMPLETE_SOURCE'], chunks=chunks,
            evidence_archive=_tools().register_evidence_archive(chunks))


def test_fitting_frame_is_unchanged_even_when_archive_reader_is_available():
    chunks = _chunks(2, chars=50)
    context = dict(preset=_preset(), profile_prefix='profile', request_payload='task',
                   source_context=['COMPLETE_SOURCE'], chunks=chunks)
    old = chat.govern_model_read_messages(**context)
    new = chat.govern_model_read_messages(**context, evidence_archive=_tools().register_evidence_archive(chunks))
    assert new == old


@pytest.mark.asyncio
async def test_exact_counter_does_not_repack_every_historical_body_after_overflow():
    chunks = _chunks(100, chars=2000)
    archive = _tools().register_evidence_archive(chunks)
    wires = []
    async def count(messages):
        wires.append(copy.deepcopy(messages))
        return SimpleNamespace(tokens=(len(json.dumps(messages, ensure_ascii=False)) + 1) // 2,
            model_id='fixture', connection_revision_id='fixture:r1', model_identity_sha256='a' * 64,
            source='fixture-exact-wire', wire_sha256='b' * 64)
    messages, packet, _, bodies = await chat.govern_model_read_messages_bound(
        count_messages=count, preset=_preset(), profile_prefix='profile', request_payload='original task',
        source_context=['COMPLETE_SOURCE'], chunks=chunks, evidence_archive=archive,
        current_read_refs=['Q100.H1'])
    assert len(wires) == 2, 'one rejected full wire and one admitted working wire; no RPC per old body'
    assert packet.included_tokens <= packet.input_budget_tokens
    assert bodies == ['Q100.H1']
    assert archive.archive_id in json.dumps(messages)


def test_new_search_keeps_inventory_admission_without_forcing_all_new_bodies():
    old = _chunks(40)
    new = _chunks(2, chars=20000)
    for rank, chunk in enumerate(new, 1):
        chunk.meta.update(model_evidence_ref=f'Q201.H{rank}', global_evidence_id=f'fresh-{rank}',
            model_read_tool='search_sources', model_query_index=201, model_query_text='literal fresh query',
            model_inventory_delivery_status='prepared', model_delivery_status='prepared')
    chunks = [*old, *new]
    messages, packet, inventory, bodies = chat.govern_model_read_messages(
        preset=_preset(), profile_prefix='profile', request_payload='task',
        source_context=['COMPLETE_SOURCE'], chunks=chunks,
        evidence_archive=_tools().register_evidence_archive(chunks))
    assert packet.included_tokens <= packet.input_budget_tokens
    assert inventory == ['Q201.H1', 'Q201.H2'] and bodies == []
    assert 'discovery_inventory_page' in json.dumps(messages)
    assert all(c.meta['model_delivery_status'] == 'prepared' for c in new)


@pytest.mark.asyncio
async def test_saved_body_reread_uses_immutable_bytes_after_caller_changes_source():
    tools = _tools()
    chunks = _chunks(2)
    archive = tools.register_evidence_archive(chunks)
    literal = chunks[0].content
    chunks[0].content = 'CHANGED_SOURCE'
    chunks[0].meta['source_sha256'] = 'f' * 64
    result = await tools.execute({'tool': 'read_source', 'args': {
        'evidence_archive_id': archive.archive_id, 'evidence_ref': 'Q1.H1'}})
    assert result.payload['status'] == 'ok'
    assert len(result.chunks) == 1 and result.chunks[0].content == literal
    assert result.chunks[0].meta['source_sha256'] == '0' * 64
    assert result.chunks[0].meta['archive_original_global_evidence_id'] == 'global-0'


@pytest.mark.asyncio
async def test_archive_inventory_paging_retains_every_identity_in_original_order():
    tools = _tools()
    archive = tools.register_evidence_archive(_chunks(40))
    seen, offset = [], 0
    while True:
        result = await tools.execute({'tool': 'read_source', 'args': {
            'evidence_archive_id': archive.archive_id, 'evidence_offset': offset}})
        assert result.payload['status'] == 'ok' and not result.chunks
        page = result.payload['trace']['evidence_archive_page']
        assert 0 < len(page['records']) <= 12
        seen.extend(row['evidence_ref'] for row in page['records'])
        offset = page['next_offset']
        if offset is None:
            break
    assert seen == [f'Q{n + 1}.H1' for n in range(40)]


@pytest.mark.asyncio
@pytest.mark.parametrize('args', [
    {'evidence_ref': 'Q1.H1', 'source_row': 'S!R1'},
    {'evidence_offset': -1}, {'evidence_offset': True},
    {'evidence_ref': 'unknown'}, {'evidence_offset': 999},
])
async def test_archive_bad_arguments_are_visible_conflicts(args):
    tools = _tools()
    archive = tools.register_evidence_archive(_chunks(2))
    result = await tools.execute({'tool': 'read_source', 'args': {
        'evidence_archive_id': archive.archive_id, **args}})
    assert result.payload['status'] == 'conflict' and not result.chunks


@pytest.mark.asyncio
async def test_stale_archive_cursor_does_not_read_new_snapshot():
    tools = _tools()
    old = tools.register_evidence_archive(_chunks(2))
    tools.register_evidence_archive(_chunks(3))
    result = await tools.execute({'tool': 'read_source', 'args': {
        'evidence_archive_id': old.archive_id, 'evidence_ref': 'Q1.H1'}})
    assert result.payload['status'] == 'conflict' and not result.chunks


@pytest.mark.asyncio
async def test_ambiguous_old_alias_never_selects_one_body():
    tools = _tools()
    chunks = _chunks(1)
    other = copy.deepcopy(chunks[0])
    other.content = 'DIFFERENT_GENERATION'
    other.meta['source_sha256'] = 'f' * 64
    archive = tools.register_evidence_archive([*chunks, other])
    result = await tools.execute({'tool': 'read_source', 'args': {
        'evidence_archive_id': archive.archive_id, 'evidence_ref': 'Q1.H1'}})
    assert result.payload['status'] == 'conflict' and not result.chunks


@pytest.mark.asyncio
@pytest.mark.parametrize('variant', ['B0_DIRECT', 'B1_CANDIDATE'])
async def test_actual_native_continuation_uses_archive_when_history_exceeds_window(tmp_path, monkeypatch, variant):
    original = chat.govern_model_read_messages_bound
    frames = []

    async def grow_saved_history(**kwargs):
        assert kwargs['evidence_archive'] is not None, 'production callback must register a real archive'
        old = _chunks(40, chars=8000)
        for n, c in enumerate(old):
            c.meta['model_evidence_ref'] = f'Q{900 + n}.H1'
        # Inject immutable history at the real application's governed boundary;
        # its model responses and real calculator remain unchanged.
        kwargs['chunks'] = [*old, *kwargs['chunks']]
        kwargs['evidence_archive'] = _tools().register_evidence_archive(kwargs['chunks'])
        result = await original(**kwargs)
        frames.append(result)
        return result

    monkeypatch.setattr(chat, 'govern_model_read_messages_bound', grow_saved_history)
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant)
    assert run.executions and frames
    assert all('evidence_archive' in json.dumps(frame[0]) for frame in frames)
    assert all(frame[1].included_tokens <= frame[1].input_budget_tokens for frame in frames)
    assert run.executions[0][1]['confirmed_amount'] == 1800


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [OSError('disk unavailable'), RuntimeError('checkpoint unavailable')])
async def test_job_creation_failure_stops_before_model_search_or_artifact(tmp_path, monkeypatch, failure):
    calls = []
    async def complete(*args, **kwargs):
        calls.append('model')
        pytest.fail('No model call is allowed after failed durable job creation')
    def begin(*args, **kwargs):
        raise failure
    monkeypatch.setattr(WorkbookResearchJobService, 'begin_or_resume', begin)
    monkeypatch.setattr(chat.BoundModelChatRunner, 'complete', complete)
    with pytest.raises(chat.HTTPException) as caught:
        await _run_sheet(tmp_path, monkeypatch, reads=False, variant='B1_CANDIDATE')
    assert caught.value.status_code == 503
    assert caught.value.detail['code'] == 'WORKBOOK_CHECKPOINT_UNAVAILABLE'
    assert str(failure) not in str(caught.value.detail)
    assert calls == []
