"""A control experiment must not inject the production query/result protocol."""
import copy
import json
from types import SimpleNamespace

import pytest

from proxy.services.clean_model_rag_baseline_service import run_clean_model_rag_baseline
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from proxy.services.model_research_tool_service import ModelResearchToolResult
from proxy.services.openai_compatible_transport_service import InferenceResponse, ModelTransportError


def _response(text='', calls=(), finish='stop'):
    return InferenceResponse(text=text, tool_calls=tuple(calls), finish_reason=finish, usage={})


def _call(name, args, call_id='literal-provider-id'):
    return {'id': call_id, 'type': 'function', 'function': {
        'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}


class Runner:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    async def complete(self, **kwargs):
        assert kwargs['expected_connection_revision_id'] == 'connection:r1'
        self.requests.append(copy.deepcopy(kwargs['request']))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(response=response)


class Tools:
    def __init__(self):
        self.calls = []

    def register_evidence_archive(self, chunks):
        from proxy.services.model_evidence_archive_service import ModelEvidenceArchive
        return ModelEvidenceArchive(chunks)

    def register_shown_norm_cards(self, chunks):
        pass

    async def execute(self, call):
        self.calls.append(copy.deepcopy(call))
        return ModelResearchToolResult(payload={'tool': call['tool'], 'status': 'ok', 'trace': {}},
            chunks=(SimpleNamespace(content='WHOLE_LITERAL_EVIDENCE', doc_name='source', score=1,
                meta={'source_ref': 'literal-source', 'source_sha256': 'a' * 64}),))


def _context(runner, tools):
    preset = ModelExecutionPreset(preset_id='clean-control', model_family='fixture',
        input_token_limit=10000, generation_reserve_tokens=1000, safety_reserve_tokens=0,
        normal_tool_count=5, max_tools=5, max_batch_items=6, parallel_read_limit=1,
        reasoning_enabled=False, source_chain=('fixture',))
    return dict(runner=runner, research_tools=tools, preset=preset,
        connection_revision_id='connection:r1', question='Original literal question Ω',
        source_context=['COMPLETE_ORIGINAL_SOURCE'], profile_prefix='Explicit owner profile')


@pytest.mark.asyncio
async def test_model_calls_rag_verbatim_and_returns_ordinary_answer_without_handshake():
    query = 'literal model query Ω / 125 мм'
    runner = Runner([_response('I will look this up', [_call('search_sources', {'q': query})]),
                     _response('An ordinary professional answer, without required fields.')])
    tools = Tools()
    result = await run_clean_model_rag_baseline(**_context(runner, tools))
    assert result.status == 'terminal' and result.answer.startswith('An ordinary')
    assert len(runner.requests) == 2 and tools.calls[0]['args'] == {'q': query}
    assert result.receipts[0]['call']['call_id'] == 'literal-provider-id'
    for request in runner.requests:
        wire = json.dumps(request.messages, ensure_ascii=False)
        assert 'Original literal question Ω' in wire and 'COMPLETE_ORIGINAL_SOURCE' in wire
        assert request.response_format is None
        assert 'expected_revision' not in wire and 'query_declaration' not in wire
        assert 'norm_status' not in wire and 'artifact_kind' not in wire
        assert request.messages[0]['content'] == 'Explicit owner profile'
    assert 'WHOLE_LITERAL_EVIDENCE' in str(runner.requests[-1].messages)


@pytest.mark.asyncio
async def test_plain_final_does_not_force_search_or_repair():
    runner, tools = Runner([_response('Need the original drawings to determine quantities.')]), Tools()
    result = await run_clean_model_rag_baseline(**_context(runner, tools))
    assert result.status == 'terminal' and not tools.calls and len(runner.requests) == 1


@pytest.mark.asyncio
async def test_length_is_partial_output_not_success_or_format_retry():
    runner, tools = Runner([_response('Incomplete answer', finish='length')]), Tools()
    result = await run_clean_model_rag_baseline(**_context(runner, tools))
    assert result.status == 'output_limit' and result.answer == 'Incomplete answer'
    assert len(runner.requests) == 1 and not tools.calls


@pytest.mark.asyncio
async def test_provider_failure_propagates_without_model_switch_or_retry():
    runner, tools = Runner([ModelTransportError('lost provider')]), Tools()
    with pytest.raises(ModelTransportError, match='lost provider'):
        await run_clean_model_rag_baseline(**_context(runner, tools))
    assert len(runner.requests) == 1


@pytest.mark.asyncio
async def test_invalid_native_arguments_do_not_execute_or_repair():
    call = _call('search_sources', {'q': 'literal'})
    call['function']['arguments'] = '{not JSON'
    runner, tools = Runner([_response(calls=[call])]), Tools()
    result = await run_clean_model_rag_baseline(**_context(runner, tools))
    assert result.status == 'native_call_invalid' and not tools.calls and len(runner.requests) == 1


@pytest.mark.asyncio
async def test_read_budget_stops_without_inventing_final_answer():
    runner, tools = Runner([_response(calls=[_call('search_sources', {'q': 'literal'})])]), Tools()
    result = await run_clean_model_rag_baseline(**_context(runner, tools), max_read_calls=0)
    assert result.status == 'read_budget' and result.answer == '' and not tools.calls
