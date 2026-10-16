"""Offline output-channel counters; no provider/model requests leave MockTransport."""
from __future__ import annotations

from dataclasses import replace
import json
import httpx
import pytest

import test_openai_compatible_transport_service as transport_fixture
import test_model_rag_sheet_evidence_reads as sheet_fixture
from proxy.services.llm_transport_profile_service import final_assistant_text
from proxy.services.model_secret_service import EnvironmentSecretStore
from proxy.services import openai_compatible_transport_service as transport
from proxy.services import chat_evidence_application_service as application

def make_transport(tmp_path,payload):
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json=payload)
    client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    instance=transport.OpenAICompatibleTransport(client=client,
        secret_store=EnvironmentSecretStore(tmp_path/'test-only-no-env',environ={}),
        peer_verifier=lambda response,endpoint:None,response_body_limit=32768)
    return instance,client,requests

@pytest.mark.asyncio
@pytest.mark.parametrize('message,content_chars,reasoning_chars',[
    ({},None,None),
    ({'content':None,'reasoning_content':None},0,0),
    ({'content':'','reasoning_content':''},0,0),
    ({'content':'Готово','reasoning_content':'private мысль'},6,13),
    ({'content':'<think>private only'},19,None),
    ({'content':'<think>private</think>Готово','reasoning_content':'channel only'},28,12),
    ({'content':[]},0,None),
    ({'content':[{'type':'text','text':'ABC'},{'type':'output_text','text':'Яя'}]},5,None),
    ({'content':[{'type':'image_url','image_url':{'url':'private://not-fetched'}}]},None,None),
    ({'content':[{'type':'text','text':None}]},None,None),
    ({'content':42},None,None),
])
async def test_real_complete_records_only_sizes_without_changing_final_text(tmp_path,message,content_chars,reasoning_chars):
    payload={'model':'fixture-model','choices':[{'message':message,'finish_reason':'length'}],
             'usage':{'prompt_tokens':3,'completion_tokens':20,'total_tokens':23,
                      'completion_tokens_details':{'reasoning_tokens':15}}}
    instance,client,requests=make_transport(tmp_path,payload)
    try:
        result=await instance.complete(transport_fixture._resolved(extension_type='freetoken'),
            transport.InferenceRequest(messages=({'role':'user','content':'synthetic'},),max_output_tokens=20,reasoning_enabled=True))
    finally:
        await client.aclose()
    assert len(requests)==1
    assert result.text==final_assistant_text(message)
    assert result.output_channel_counts=={
        'provider_content_chars':content_chars,'provider_reasoning_chars':reasoning_chars,'final_text_chars':len(result.text)}
    assert result.usage['reasoning_tokens']==15
    assert set(result.output_channel_counts)=={'provider_content_chars','provider_reasoning_chars','final_text_chars'}
    assert 'private' not in json.dumps(dict(result.output_channel_counts))

@pytest.mark.parametrize('value,expected',[
    ({'completion_tokens_details':{'reasoning_tokens':0}},0),
    ({'completion_tokens_details':{'reasoning_tokens':19}},19),
    ({'reasoning_tokens':4,'completion_tokens_details':{'reasoning_tokens':19}},4),
    ({'completion_tokens_details':{'reasoning_tokens':True}},None),
    ({'completion_tokens_details':{'reasoning_tokens':-1}},None),
    ({'completion_tokens_details':{'reasoning_tokens':'19'}},None),
    ({'completion_tokens_details':{'reasoning_tokens':19.5}},None),
    ({'completion_tokens_details':{}},None),
    ({'completion_tokens_details':None},None),
    ({},None),
])
def test_nested_reasoning_usage_retains_only_reported_integer_tokens(value,expected):
    result=transport._usage(value)
    if expected is None:
        assert 'reasoning_tokens' not in result
    else:
        assert result['reasoning_tokens']==expected

@pytest.mark.asyncio
async def test_invalid_reasoning_content_remains_a_transport_error(tmp_path):
    instance,client,_=make_transport(tmp_path,{'choices':[{'message':{'content':'ok','reasoning_content':['unsupported']}}]})
    try:
        with pytest.raises(transport.ModelTransportError,match='UPSTREAM_REASONING_CONTENT_INVALID'):
            await instance.complete(transport_fixture._resolved(),transport.InferenceRequest(messages=(),max_output_tokens=20))
    finally:
        await client.aclose()

@pytest.mark.asyncio
@pytest.mark.parametrize('variant',['B0_DIRECT','B1_CANDIDATE'])
@pytest.mark.parametrize('reasoning_usage,expected_reasoning', [
    pytest.param({}, None, id='missing-keeps-legacy-four-keys'),
    pytest.param({'reasoning_tokens': None}, None, id='unknown-omitted'),
    pytest.param({'reasoning_tokens': True}, None, id='invalid-boolean-omitted'),
    pytest.param({'reasoning_tokens': 0}, 0, id='reported-zero'),
    pytest.param({'reasoning_tokens': 7}, 7, id='reported-positive'),
])
async def test_canonical_response_metadata_survives_both_real_trace_whitelists(tmp_path,monkeypatch,variant,reasoning_usage,expected_reasoning):
    literal_reasoning='PRIVATE-REASONING-MUST-NOT-APPEAR'
    literal_inline='PRIVATE-INLINE-MUST-NOT-APPEAR'
    wire_results=[]
    actual_deps=application.EvidenceRuntimeDeps
    class WrappedFixtureTransport:
        def __init__(self,inner):self.inner=inner
        def __getattr__(self,key):return getattr(self.inner,key)
        async def complete(self,selected,request):
            reply=await self.inner.complete(selected,request)
            message={'content':f'<think>{literal_inline}</think>'+reply.text,'reasoning_content':literal_reasoning}
            if reply.tool_calls:message['tool_calls']=[dict(item) for item in reply.tool_calls]
            payload={'choices':[{'message':message,'finish_reason':reply.finish_reason}],
                     'usage':{'prompt_tokens':20,'completion_tokens':23,'total_tokens':43,
                              'completion_tokens_details':{'reasoning_tokens':7}}}
            instance,client,requests=make_transport(tmp_path,payload)
            try:
                result=await instance.complete(transport_fixture._resolved(extension_type='freetoken'),request)
            finally:
                await client.aclose()
            assert result.text==reply.text
            # Unknown metadata must be rejected at both public trace boundaries.
            provider_usage = {key: value for key, value in result.usage.items() if key != 'reasoning_tokens'}
            result=replace(result,usage={**provider_usage, **reasoning_usage},output_channel_counts={**result.output_channel_counts,
                'reasoning_content':literal_reasoning,'foreign':{'text':literal_inline}})
            wire_results.append(result)
            return result
    def deps(**kwargs):
        inner_factory=kwargs['model_connection_transport']
        kwargs['model_connection_transport']=lambda *args,**kw:WrappedFixtureTransport(inner_factory(*args,**kw))
        return actual_deps(**kwargs)
    monkeypatch.setattr(application,'EvidenceRuntimeDeps',deps)
    answer=json.dumps({'artifact_kind':'vor','rows':[
        {'source_row':'S!R2','row_role':'work','title':'Cable A','unit':'m','quantity':12,'work_row':'S!R2'},
        {'source_row':'S!R3','row_role':'work','title':'Cable B','unit':'m','quantity':3,'work_row':'S!R3'},
    ]})
    run=await sheet_fixture._run_sheet(tmp_path,monkeypatch,reads=False,variant=variant,
        query_declaration='{"artifact_kind":"vor","queries":[]}',final_answer=answer)
    trace=run.result['retrieval_trace']
    assert len(wire_results)==len(trace['actual_model_calls']['calls'])==len(run.requests)
    assert len(wire_results)>=1
    for response,call in zip(wire_results,trace['actual_model_calls']['calls']):
        expected_usage = {'prompt_tokens':20,'input_tokens':None,'completion_tokens':23,'total_tokens':43}
        if expected_reasoning is not None:
            expected_usage['reasoning_tokens'] = expected_reasoning
        assert call['provider_usage'] == expected_usage
        assert call['output_channel_counts']=={key:value for key,value in response.output_channel_counts.items()
            if key in {'provider_content_chars','provider_reasoning_chars','final_text_chars'}}
        assert set(call['output_channel_counts'])=={'provider_content_chars','provider_reasoning_chars','final_text_chars'}
    last=trace['last_model_call_execution']
    assert last['provider_usage'] == trace['actual_model_calls']['calls'][-1]['provider_usage']
    assert last['output_channel_counts']==trace['actual_model_calls']['calls'][-1]['output_channel_counts']
    public_execution=json.dumps({'last':last,'calls':trace['actual_model_calls']['calls']},ensure_ascii=False)
    assert literal_reasoning not in public_execution and literal_inline not in public_execution
    assert 'reasoning_content' not in public_execution and 'foreign' not in public_execution


@pytest.mark.parametrize('reasoning_usage,expected_reasoning', [
    ({}, None), ({'reasoning_tokens': None}, None), ({'reasoning_tokens': True}, None),
    ({'reasoning_tokens': False}, None), ({'reasoning_tokens': -1}, None),
    ({'reasoning_tokens': '7'}, None), ({'reasoning_tokens': 7.5}, None),
    ({'reasoning_tokens': {}}, None), ({'reasoning_tokens': []}, None),
    ({'reasoning_tokens': 0}, 0), ({'reasoning_tokens': 7}, 7),
])
def test_optional_reasoning_counter_preserves_exact_legacy_usage_when_unknown(reasoning_usage,expected_reasoning):
    legacy_usage = {'prompt_tokens':20,'input_tokens':None,'completion_tokens':23,'total_tokens':43}
    trace = {'last_model_call_execution': {'provider_usage': {**legacy_usage, **reasoning_usage}}}
    application.append_actual_model_call(trace, purpose='answer')
    expected_usage = dict(legacy_usage)
    if expected_reasoning is not None:
        expected_usage['reasoning_tokens'] = expected_reasoning
    assert trace['actual_model_calls']['calls'][0]['provider_usage'] == expected_usage
