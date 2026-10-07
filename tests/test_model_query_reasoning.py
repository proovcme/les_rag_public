"""Purpose reasoning is immutable policy, not a provider or domain override."""

import inspect
import json

import httpx
import pytest

from proxy.services import chat_evidence_application_service as chat_service
from proxy.services import model_execution_preset_service as presets
from proxy.services.runtime_config_registry_service import runtime_factor_rows
from sovushka.pages import profiles as profiles_page
from tests.test_model_rag_sheet_evidence_reads import _run_sheet
from tests.test_openai_compatible_transport_service import _resolved, _transport


def _preset(policy):
    return presets.resolve_execution_preset(
        presets.BackendCapacity("freetoken", "Qwen3.6-35B", 35000, True, "fixture"), operator=policy)


@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.parametrize("temperature", [0.0, 0.65])
@pytest.mark.asyncio
async def test_profile_temperature_reaches_initial_query_repair_and_answer(tmp_path, monkeypatch, variant, temperature):
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant,
                           query_repair=True, temperature=temperature)
    assert not run.responses and len(run.requests) == 5 and len(run.executions) == 1
    assert [request.temperature for request in run.requests] == [temperature] * 5
    assert [item["temperature"] for item in run.result["retrieval_trace"]["model_query_outputs"]] == [temperature] * 2


@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.asyncio
async def test_rejected_query_attempt_cannot_poison_repaired_document_target(tmp_path, monkeypatch, variant):
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant,
        query_repair='{"artifact_kind":"lsr","queries":["unfinished',
        query_declaration='{"artifact_kind":"lsr","queries":["S!R2 — Cable A","S!R3 — Cable B"]}')
    trace = run.result["retrieval_trace"]
    assert len(run.executions) == 1 and not run.responses
    assert trace["artifact_target"]["status"] == "declared"
    assert trace["artifact_target"]["artifact_kind"] == "lsr"
    attempts = trace["model_query_outputs"]
    assert attempts[0]["artifact_kind_declaration"]["status"] == "invalid"
    assert attempts[1]["artifact_kind_declaration"]["status"] == "declared"
    if variant == "B1_CANDIDATE":
        job = WorkbookResearchJobService().get(trace["workbook_research_job"]["job_id"])
        assert job["task_context"]["model_artifact_kind"] == "lsr"
        assert job["document"]["final_revision_id"] or job["document"]["draft_revision_id"]


@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.asyncio
async def test_query_has_no_workbook_fields_and_each_decision_has_one_contract(tmp_path, monkeypatch, variant):
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant)
    fields = chat_service.model_lsr_result_field_instruction()
    texts = ["\n".join(str(message.get("content") or "") for message in request.messages)
             for request in run.requests]
    assert len(texts) == 4 and not run.responses
    assert fields not in texts[0], "query-only inference must not request final workbook fields"
    assert all(text.count(fields) == 1 for text in texts[1:]), "answer/native-read phases must keep one complete field contract"
    assert len(run.executions) == 1 and run.result["answer"]


@pytest.mark.parametrize("query, expected", [(None, True), (False, False), (True, True)])
def test_query_reasoning_override_is_optional_and_keeps_answer_global(query, expected):
    policy = {"reasoning_enabled": True, **({"query_reasoning_enabled": query} if query is not None else {})}
    selected = _preset(policy)
    assert selected.diagnostics()["query_reasoning"]["requested"] is query
    assert selected.diagnostics()["query_reasoning"]["effective"] is expected
    query_preset = presets.model_rag_query_execution_preset(selected)
    answer = presets.model_rag_answer_execution_preset(selected, model_rag=True)
    assert query_preset.reasoning_enabled is expected and answer.reasoning_enabled is True
    assert selected.reasoning_enabled is True
    assert policy == {"reasoning_enabled": True, **({"query_reasoning_enabled": query} if query is not None else {})}
    assert query_preset.input_token_limit == answer.input_token_limit == selected.input_token_limit


@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.parametrize("query", [None, False])
@pytest.mark.asyncio
async def test_actual_query_request_uses_purpose_bool_answers_and_native_reads_keep_global(
    tmp_path, monkeypatch, variant, query,
):
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant,
                           reasoning_enabled=True, query_reasoning_enabled=query)
    assert len(run.requests) == 4 and not run.responses
    assert run.requests[0].reasoning_enabled is (query is not False)
    assert all(request.reasoning_enabled is True for request in run.requests[1:])
    calls = run.result["retrieval_trace"]["actual_model_calls"]["calls"]
    assert calls[0]["reasoning"]["effective"] is (query is not False)
    assert all(call["reasoning"]["effective"] is True for call in calls[1:])


@pytest.mark.asyncio
async def test_actual_freetoken_wire_uses_query_preset_and_reserved_output_without_provider_mutation(tmp_path):
    from proxy.services.openai_compatible_transport_service import InferenceRequest

    selected = _preset({"reasoning_enabled": True, "query_reasoning_enabled": False,
                        "query_output_tokens": 8192, "answer_output_tokens": 12000})
    posted = []

    def handler(request):
        posted.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "literal output"}, "finish_reason": "stop"}]})

    transport, client = _transport(tmp_path, handler)
    connection = _resolved(extension_type="freetoken")
    try:
        for purpose in (presets.model_rag_query_execution_preset(selected),
                        presets.model_rag_answer_execution_preset(selected, model_rag=True)):
            messages, packet = chat_service.govern_inference_messages(
                preset=purpose, profile_prefix="system", request_payload="literal task")
            await transport.complete(connection, InferenceRequest(
                messages=messages, max_output_tokens=packet.generation_reserve_tokens,
                reasoning_enabled=purpose.reasoning_enabled))
    finally:
        await client.aclose()
    assert [body["chat_template_kwargs"]["enable_thinking"] for body in posted] == [False, True]
    assert [body["max_tokens"] for body in posted] == [8192, 12000]
    assert all(body["model"] == connection.model_id for body in posted)


def test_query_reasoning_factor_shows_inheritance_and_explicit_requested_effective_source():
    for policy, requested, effective in (({"reasoning_enabled": True}, None, True),
                                        ({"reasoning_enabled": True, "query_reasoning_enabled": False}, False, False)):
        row = next(row for row in runtime_factor_rows(_preset(policy).diagnostics()) if row["id"] == "query_reasoning")
        assert row["requested"] is requested and row["effective"] is effective
        assert row["source"] and row["operator_action"] == "profile_clone"
        assert row["restart_required"] is False


def test_query_on_is_independent_of_global_off_but_cannot_enable_unsupported_transport():
    selected = _preset({"reasoning_enabled": False, "query_reasoning_enabled": True})
    assert presets.model_rag_query_execution_preset(selected).reasoning_enabled is True
    assert presets.model_rag_answer_execution_preset(selected, model_rag=True).reasoning_enabled is False
    unsupported = presets.resolve_execution_preset(
        presets.BackendCapacity("openai-compatible", "model", 35000, True, "fixture"),
        operator={"query_reasoning_enabled": True})
    assert unsupported.diagnostics()["query_reasoning"] == {
        "requested": True, "effective": False, "source": "unsupported_by_transport", "restart_required": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_existing_query_repair_uses_same_override_as_initial_query(tmp_path, monkeypatch, variant):
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
                           reasoning_enabled=True, query_reasoning_enabled=False, query_repair=True)
    assert len(run.requests) == 3 and not run.responses
    assert [request.reasoning_enabled for request in run.requests] == [False, False, True]
    calls = run.result["retrieval_trace"]["actual_model_calls"]["calls"]
    assert calls[1]["purpose"].endswith("query_repair")


@pytest.mark.parametrize("value", [None, 0, 1, "false", {}, []])
def test_invalid_optional_query_reasoning_policy_is_rejected_without_coercion(value):
    with pytest.raises(ValueError, match="boolean"):
        _preset({"query_reasoning_enabled": value})


def test_profile_query_reasoning_revision_is_immutable_and_invalid_value_never_persists(tmp_path):
    from proxy.services.chat_profile_service import publish_profile_revision, registry_snapshot

    db = tmp_path / "profile.db"
    base = next(item for item in registry_snapshot(db_path=db)["profiles"] if item["mode"] == "estimator")["active"]
    old = dict(base["model_policy"])
    arguments = dict(mode="estimator", name="Query policy", prompt_revision_id=base["prompt_revision_id"],
                     skill_revision_id=base["skill_revision_id"], tools=base["tools"], rag_policy=base["rag_policy"], db_path=db)
    policy = {**old, "reasoning_enabled": True, "query_reasoning_enabled": False}
    revision = publish_profile_revision(**arguments, model_policy=policy)
    assert revision["model_policy"] == policy
    active = next(item for item in registry_snapshot(db_path=db)["profiles"] if item["mode"] == "estimator")["active"]
    assert active["revision_id"] == base["revision_id"] and active["model_policy"] == old
    with pytest.raises(ValueError, match="boolean"):
        publish_profile_revision(**arguments, model_policy={"query_reasoning_enabled": "false"})


def test_gui_existing_choice_preserves_absent_inherit_and_only_sets_explicit_bool():
    draft = {"model_policy": {"reasoning_enabled": True, "temperature": 0.1}}
    assert profiles_page.query_reasoning_choice(draft["model_policy"]) == "inherit"
    profiles_page.set_query_reasoning_choice(draft, "off")
    assert draft["model_policy"]["query_reasoning_enabled"] is False
    profiles_page.set_query_reasoning_choice(draft, "on")
    assert draft["model_policy"]["query_reasoning_enabled"] is True
    profiles_page.set_query_reasoning_choice(draft, "inherit")
    assert draft["model_policy"] == {"reasoning_enabled": True, "temperature": 0.1}
    source = inspect.getsource(profiles_page.build_profiles)
    assert "Рассуждение при поисковых запросах" in source and "select_field" in source


def test_query_failure_prefers_actual_safe_connection_identity_over_legacy_configured_provider():
    error = chat_service.model_query_failure("empty", trace={"model_connection": {
        "provider": "freetoken", "model_id": "actual-Qwen", "revision_id": "assigned:r1"}},
        session_id="session", provider="ollama", model="legacy-model")
    execution = error.private_query_trace["model_execution"]
    assert execution["provider"] == "freetoken" and execution["model"] == "actual-Qwen"
    assert execution["configured_provider"] == "ollama" and execution["configured_model"] == "legacy-model"


@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.asyncio
async def test_finite_query_instruction_reaches_actual_producer_without_filtering_literal_queries(
    tmp_path, monkeypatch, variant,
):
    # A compactness instruction is model guidance, not a row/query quota or code filter.
    queries = [
        'S!R2 — Cable A «A-5»: ГЭСНм10-10-006-01, literal supplied cipher',
        'S!R3 — Cable B "Ω/Б": ГЭСН21-03-004-02, literal supplied cipher',
        *[f'S!R{2 + index % 2} — literal query {index}: "Ω/{index}"; 2,5 м'
          for index in range(17)],
    ]
    run = await _run_sheet(
        tmp_path, monkeypatch, reads=False, variant=variant, temperature=0.7,
        query_declaration=json.dumps({"artifact_kind": "lsr", "queries": queries}, ensure_ascii=False),
    )

    assert len(queries) > 12
    assert run.queries[:len(queries)] == queries
    assert len(run.requests) == 2 and not run.responses and len(run.executions) == 1
    initial = run.requests[0]
    prefix = initial.messages[0]["content"]
    assert "Верни компактный законченный набор" in prefix
    assert "Число запросов определяешь ты по представленным операциям" in prefix
    assert "не разворачивай их в справочник или перебор всех возможных вариантов" in prefix
    assert "До получения карточек ищи по операции и объекту исходника" in prefix
    assert "Шифр для поиска не является подтверждённой нормой" in prefix
    assert "фиксированного лимита нет" not in prefix
    assert prefix.startswith("Answer only from shown evidence.")
    wire_text = "\n".join(str(message.get("content") or "") for message in initial.messages)
    assert "Собери ЛСР; ВОР не создавай. Санкт-Петербург, 3 квартал 2026" in wire_text
    assert "Cable A" in wire_text and "Cable B" in wire_text
    expected_query = presets.model_rag_query_execution_preset(run.connection.effective_preset)
    expected_budget = presets.query_generation_budget(
        expected_query, reserved_tokens=expected_query.generation_reserve_tokens)
    assert initial.max_output_tokens == expected_budget["effective"] == 1600
    assert expected_budget["source"] == "ordinary_query_default"
    assert run.connection.effective_preset.generation_reserve_tokens == 5000
    assert all(request.temperature == 0.7 for request in run.requests)
    assert len(run.result["retrieval_trace"]["model_query_outputs"]) == 1


@pytest.mark.parametrize("mode", ["estimator", "agent"])
def test_finite_query_scope_keeps_literal_profile_skill_and_purpose_budgets(mode):
    snapshot = {
        "mode": mode, "revision_id": "user:profile:literal-query-policy",
        "prompt_text": 'Literal saved profile «Ω»; preserve "A-5".',
        "skill_text": '# Literal saved skill\nНе изменяй исходные данные «Б».',
        "tabular_estimator_path": False,
        "model_policy": {"temperature": 0.7, "reasoning_enabled": True,
                         "query_reasoning_enabled": False,
                         "query_output_tokens": 8192, "answer_output_tokens": 16384},
    }
    before = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    selected = _preset(snapshot["model_policy"])
    selected_before = selected.diagnostics()
    query = presets.model_rag_query_execution_preset(selected)
    answer = presets.model_rag_answer_execution_preset(selected, model_rag=True)
    instruction = chat_service.model_rag_query_instruction(snapshot)
    prefix = chat_service.profile_system_prompt(snapshot, strict=False, purpose="query")
    source = 'Лист Ω!R17 | Изделие "A-5" | шт. | 3 | примечание «Б»'
    question = 'Ответь по исходнику «Ω» и сохрани его единицы.'
    messages, packet = chat_service.govern_inference_messages(
        preset=query, profile_prefix=prefix + "\n\n" + instruction,
        request_payload=question, required_evidence=[source],
    )

    assert snapshot["prompt_text"] in messages[0]["content"]
    assert snapshot["skill_text"] in messages[0]["content"]
    assert "Верни компактный законченный набор" in messages[0]["content"]
    if mode == "estimator":
        assert chat_service._MODEL_RAG_QUERY_VOLUME_HINT in messages[0]["content"]
    else:
        assert chat_service._MODEL_RAG_QUERY_VOLUME_HINT not in messages[0]["content"]
        assert "До получения карточек ищи по операции и объекту исходника" not in messages[0]["content"]
    wire_text = "\n".join(str(message.get("content") or "") for message in messages)
    assert source in wire_text and question in wire_text and not packet.omissions
    assert packet.generation_reserve_tokens == query.generation_reserve_tokens == 8192
    assert answer.generation_reserve_tokens == 16384
    assert query.reasoning_enabled is False and answer.reasoning_enabled is True
    assert query.input_token_limit == answer.input_token_limit == selected.input_token_limit
    assert selected.diagnostics() == selected_before
    assert json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8") == before
