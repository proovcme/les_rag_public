"""Actual production opt-out: native reads and ordinary answer without a carrier."""
import copy
import json

import pytest

from proxy.services import chat_evidence_application_service as chat
from proxy.services.chat_profile_service import application_protocol_enabled
from proxy.services.openai_compatible_transport_service import InferenceResponse
from tests.test_model_rag_sheet_evidence_reads import _run_sheet, _native


def _final(text='Обычный ответ без таблицы и обязательных полей.'):
    return InferenceResponse(text=text, tool_calls=(), finish_reason='stop', usage={})


@pytest.mark.parametrize('value', ['false', 0, 1, None, [], {}])
def test_protocol_setting_rejects_non_boolean(value):
    with pytest.raises(ValueError, match='application_protocol_enabled'):
        application_protocol_enabled({'rag_policy': {'application_protocol_enabled': value}})


def test_old_profiles_keep_protocol_and_overlay_respects_explicit_opt_out():
    assert application_protocol_enabled({}) is True
    snapshot = {'mode': 'agent', 'prompt_text': 'OWNER PROMPT', 'skill_text': 'OWNER SKILL',
                'rag_policy': {'application_protocol_enabled': False}}
    original = copy.deepcopy(snapshot)
    effective = chat.overlay_tabular_estimator_snapshot(snapshot)
    assert snapshot == original
    assert effective['skill_text'] == 'OWNER SKILL'
    assert application_protocol_enabled(effective) is False
    assert chat.profile_system_prompt(effective, strict=False, purpose='workbook_result') == 'OWNER PROMPT\n\nOWNER SKILL'


@pytest.mark.asyncio
async def test_disabled_protocol_accepts_plain_answer_on_first_call_without_search_or_workbook(tmp_path, monkeypatch):
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant='',
        protocol_enabled=False, free_responses=[_final()], skill_text='OWNER SKILL')
    assert len(run.requests) == 1 and not run.responses
    assert run.result['answer'] == _final().text
    assert run.queries == [] and run.executions == []
    assert run.result['retrieval_trace']['application_protocol']['enabled'] is False
    assert run.histories[-1]['retrieval_trace']['application_protocol']['enabled'] is False
    assert not run.result.get('artifact')
    _assert_free_wire(run.requests, owner_skill=True)


def _assert_free_wire(requests, *, owner_skill=False):
    for request in requests:
        frame = json.dumps(request.messages, ensure_ascii=False)
        assert 'ВОР не создавай' in frame and 'source.xlsx' in frame
        assert 'Cable A' in frame and 'S!R2' in frame and 'Cable B' in frame and 'S!R3' in frame
        assert request.tools and request.response_format is None
        system = '\n'.join(str(m.get('content') or '') for m in request.messages if m['role'] == 'system')
        assert system == 'Answer only from shown evidence.' + ('\n\nOWNER SKILL' if owner_skill else '')
        assert chat._MODEL_RAG_QUERY_INSTRUCTION not in frame
        assert chat._MODEL_RAG_QUERY_FORMAT_CONTRACT not in frame
        assert chat._WORKBOOK_RESULT_CARRIER_INSTRUCTION not in frame


@pytest.mark.asyncio
async def test_free_answer_example_of_tool_json_is_not_executed(tmp_path, monkeypatch):
    answer = 'Пример формата: ' + json.dumps({'calls': [{'tool': 'search_sources', 'args': {'q': 'example'}}]})
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant='',
                          protocol_enabled=False, free_responses=[_final(answer)])
    assert run.result['answer'] == answer and len(run.requests) == 1
    assert not run.queries and not run.executions


@pytest.mark.asyncio
async def test_free_empty_final_is_technical_stop_without_retry(tmp_path, monkeypatch):
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant='',
                          protocol_enabled=False, free_responses=[_final('')])
    assert len(run.requests) == 1 and run.result['crag_status'] == 'MODEL_OUTPUT_INCOMPLETE'
    assert not run.queries and not run.executions


@pytest.mark.asyncio
async def test_disabled_protocol_native_model_query_and_exact_reads_reach_same_model(tmp_path, monkeypatch):
    query = 'literal native query chosen by the model'
    responses = [
        InferenceResponse(text='', tool_calls=(_native('search_sources', q=query, target='norms'),),
                          finish_reason='tool_calls', usage={}),
        InferenceResponse(text='', tool_calls=(_native('read_norm_card', norm_key='immutable-norm'),),
                          finish_reason='tool_calls', usage={}),
        _final('Источники прочитаны. Требуется уточнение условий работ.'),
    ]
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant='',
                          protocol_enabled=False, free_responses=responses)
    assert len(run.requests) == 3 and not run.responses
    assert run.queries == [query] and len(run.exact_reads) == 1
    assert not run.executions and run.result['answer'] == responses[-1].text
    assert run.result['source_map']
    assert 'fixture-resource-21' in str(run.requests[-1].messages)
    _assert_free_wire(run.requests)


@pytest.mark.asyncio
async def test_explicit_enabled_protocol_retains_existing_calculation(tmp_path, monkeypatch):
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, protocol_enabled=True)
    assert len(run.requests) == 4 and run.executions[0][1]['confirmed_amount'] == 1800


@pytest.mark.asyncio
async def test_protocol_disabled_length_is_technical_stop_without_format_repair(tmp_path, monkeypatch):
    result = InferenceResponse(text='Незавершённая мысль', tool_calls=(), finish_reason='length', usage={})
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant='',
                          protocol_enabled=False, free_responses=[result])
    assert len(run.requests) == 1 and not run.queries and not run.executions
    assert run.result['crag_status'] == 'MODEL_OUTPUT_INCOMPLETE'


@pytest.mark.asyncio
async def test_free_mode_unknown_tool_is_technical_stop_not_success(tmp_path, monkeypatch):
    result = InferenceResponse(text='', tool_calls=(_native('not_a_reader', q='literal'),),
                               finish_reason='tool_calls', usage={})
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant='',
                          protocol_enabled=False, free_responses=[result])
    assert len(run.requests) == 1 and not run.executions and not run.queries
    assert run.result['crag_status'] == 'MODEL_OUTPUT_INCOMPLETE'
    assert 'evidence_read_unknown_tool' not in run.result['answer']


@pytest.mark.asyncio
async def test_free_mode_ignores_source_frame_splitting_and_keeps_every_source_row(tmp_path, monkeypatch):
    monkeypatch.setenv('LES_CHAT_SOURCE_FRAME_ROWS', '1')
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant='', packet_count=3,
                          protocol_enabled=False, free_responses=[_final()])
    frame = str(run.requests[0].messages)
    for row in range(2, 8):
        assert f'S!R{row}' in frame
    assert len(run.requests) == 1 and 'source_frame' not in run.result['retrieval_trace']


@pytest.mark.asyncio
async def test_free_mode_oversized_original_source_stops_before_model_call(tmp_path, monkeypatch):
    called = []
    async def forbidden(*args, **kwargs):
        called.append(True)
        pytest.fail('Cannot send a reduced source instead of the original')
    monkeypatch.setattr(chat.BoundModelChatRunner, 'complete', forbidden)
    with pytest.raises(chat.HTTPException) as error:
        await _run_sheet(tmp_path, monkeypatch, reads=False, variant='', input_token_limit=10,
                         protocol_enabled=False, free_responses=[_final()])
    assert error.value.status_code == 422 and not called


def test_profile_api_rejects_invalid_protocol_before_writing(tmp_path):
    from proxy.services import chat_profile_service as profiles
    db = tmp_path / 'profiles.db'
    before = profiles.registry_snapshot(db_path=db)
    original = next(p['active'] for p in before['profiles'] if p['mode'] == 'estimator')
    with pytest.raises(ValueError, match='application_protocol_enabled'):
        profiles.publish_profile_revision(mode='estimator', name='Invalid protocol',
            prompt_revision_id=original['prompt_revision_id'], skill_revision_id=original['skill_revision_id'],
            tools=original['tools'], model_policy=original['model_policy'],
            rag_policy={'application_protocol_enabled': 'false'}, db_path=db)
    assert profiles.registry_snapshot(db_path=db) == before


def test_gui_mode_control_preserves_other_profile_data():
    from sovushka.pages import profiles as page
    import inspect
    draft = {'rag_policy': {'grounded': True}, 'skill_text': 'OWNER SKILL'}
    assert page.application_protocol_choice(draft) == 'on'
    page.set_application_protocol_choice(draft, 'off')
    assert draft == {'rag_policy': {'grounded': True, 'application_protocol_enabled': False}, 'skill_text': 'OWNER SKILL'}
    assert page.application_protocol_choice(draft) == 'off'
    with pytest.raises(ValueError):
        page.set_application_protocol_choice(draft, 'unknown')
    source = inspect.getsource(page.build_profiles)
    assert 'Обработка ВОР/ЛСР' in source and 'set_application_protocol_choice' in source
    from sovushka.pages.chat import _operator_technical_chips
    chips = _operator_technical_chips({'retrieval_trace': {'application_protocol': {'effective': 'native'}}})
    assert 'ВОР/ЛСР: свободный ответ модели' in chips
