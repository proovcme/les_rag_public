"""A bound estimator can read cards without inventing a source workbook."""
from __future__ import annotations

import copy
import json
from dataclasses import replace

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.openai_compatible_transport_service import InferenceResponse


@pytest.mark.parametrize("attachment,catalog,declaration,required", [
    ("", None, {}, False), ("", None, {"status": "missing"}, False),
    ("", None, {"status": "invalid", "artifact_kind": "lsr"}, False),
    ("", None, {"status": "conflict", "artifact_kind": "vor"}, False),
    ("", None, {"status": "declared", "artifact_kind": "unknown"}, False),
    ("read_bound", None, {}, True), ("", object(), {}, True),
    ("", None, {"status": "declared", "artifact_kind": "lsr"}, True),
    ("", None, {"status": "declared", "artifact_kind": "vor"}, True),
])
def test_workbook_carrier_requires_bound_source_or_valid_model_declaration(attachment, catalog, declaration, required):
    assert service.model_workbook_carrier_required(
        attachment_id=attachment, source_catalog=catalog, model_declaration=declaration) is required


@pytest.mark.parametrize("strict", [False, True])
def test_source_read_purpose_retains_literal_profile_skill_without_workbook_additions(strict):
    profile = {"mode": "estimator", "prompt_text": "LITERAL PROFILE Ω", "skill_text": "LITERAL SKILL Ω",
               "revision_id": "saved:readonly:7", "model_policy": {"temperature": 0.17}}
    before = copy.deepcopy(profile)
    prompt = service.profile_system_prompt(profile, strict=strict, purpose="source_read")
    assert prompt.startswith(profile["prompt_text"]) and profile["skill_text"] in prompt
    for addition in (service._TABULAR_LSR_VOLUME_INSTRUCTION, service._TABULAR_LSR_OPERATION_INSTRUCTION,
                     service._WORKBOOK_RESULT_CARRIER_INSTRUCTION):
        assert addition not in prompt
    assert profile == before


async def _run_no_source(monkeypatch, tmp_path, *, final_text, query_text="literal model card search",
                         native_read=False, native_name="read_norm_card", variant="B0_DIRECT"):
    from tests.test_chat_evidence_application_service import (
        test_actual_chat_shadow_failure_preserves_legacy_answer_history_and_model_count as fixture)
    from proxy.services import model_research_tool_service as research

    captures = {}
    executions = []
    exact_reads = []
    norm_code = "LITERAL-IMMUTABLE-CARD-77"
    identity = {"norm_code": norm_code, "norm_key": "literal-card-key", "source_ref": "literal-catalog#77",
                "source_sha256": "a" * 64, "edition": "literal-edition", "base_type": "literal-base"}
    full_card = {**identity, "title": "Literal card title", "measure_unit": "m",
                 "work_steps": ["WHOLE_LITERAL_CONDITION"], "resources": [], "resource_count": 0,
                 "resources_returned": 0, "resources_complete": True, "resource_consumption_known": True}

    def exact(**args):
        exact_reads.append(dict(args))
        return {"status": "ok", "card": copy.deepcopy(full_card), "missing": [], "warnings": []}

    original_factory = service.ModelResearchToolService

    def factory(**kwargs):
        return original_factory(**kwargs, norm_card_reader=exact)

    async def setup(request, runtime, boundary):
        from proxy.routers import chat

        request.req.attachment_id = None
        request.req.attachment_context = ""
        request.req.question = "Read the shown exact card and state its measurement unit."
        request.req.comparative_acceptance_variant = variant
        request.profile_snapshot["prompt_text"] = "LITERAL READ PROFILE Ω"
        request.profile_snapshot["skill_text"] = "LITERAL READ SKILL Ω"
        monkeypatch.setattr(service, "ModelResearchToolService", factory)
        monkeypatch.setattr(research.nr_sp_service, "model_candidates", lambda **kwargs: [])
        monkeypatch.setattr(service, "retrieve_smeta_norm_cards", lambda query, **kwargs: {
            "cards": [{**identity, "title": "Literal card title", "measure_unit": "m",
                       "work_steps": ["WHOLE_LITERAL_CONDITION"]}],
            "retrieval_trace": {"rag": {"status": "ok"}},
        })
        transport = runtime.model_connection_transport(None, None)
        resolver, _secret_store = runtime.model_connection_resolver()
        from proxy.services.model_connection_contracts import ConnectionRole
        connection = resolver.resolve(ConnectionRole.ANSWER)
        connection.effective_preset = replace(connection.effective_preset, input_token_limit=24000)
        transport.responses = [InferenceResponse(text=query_text, tool_calls=(), finish_reason="stop", usage={})]
        if native_read:
            call = {"id": "literal-native-card-read", "type": "function", "function": {
                "name": native_name, "arguments": '{"evidence_ref":"Q1.H1"}'}}
            transport.responses.append(InferenceResponse(text="", tool_calls=(call,),
                                                         finish_reason="tool_calls", usage={}))
        transport.responses.append(InferenceResponse(text=final_text, tool_calls=(), finish_reason="stop", usage={}))

        async def no_workbook(call, context, progress):
            executions.append(copy.deepcopy(call))
            pytest.fail("A question-only card read must not execute workbook packaging")

        runtime = replace(runtime, workbook_tool_executor=no_workbook,
                          parse_model_tool_calls=chat._parse_model_tool_calls)
        captures["result"] = await service.run_chat_evidence_application(request, runtime, boundary)
        captures.update(requests=transport.requests, exact_reads=exact_reads, executions=executions)

    await fixture(monkeypatch, tmp_path, "active_model_rag_result", application_setup=setup)
    return captures


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "", "B1_CANDIDATE"])
async def test_actual_question_only_native_card_read_returns_literal_answer_without_workbook_errors(monkeypatch, tmp_path, variant):
    answer = "The shown immutable card measures the operation in metres. Ω"
    run = await _run_no_source(monkeypatch, tmp_path, final_text=answer, native_read=True, variant=variant)
    assert run["result"]["answer"] == answer
    assert len(run["requests"]) == 3 and len(run["exact_reads"]) == 1 and not run["executions"]
    assert run["exact_reads"] == [{"norm_key": "literal-card-key", "norm_code": "LITERAL-IMMUTABLE-CARD-77"}]
    first_answer = run["requests"][1]
    assert "read_norm_card" in {tool["function"]["name"] for tool in first_answer.tools}
    for request in run["requests"][1:]:
        messages = str(request.messages)
        assert "LITERAL READ PROFILE Ω" in messages and "LITERAL READ SKILL Ω" in messages
        assert service._WORKBOOK_RESULT_CARRIER_INSTRUCTION not in messages
        assert "source_row |" not in messages
    messages = list(run["requests"][-1].messages)
    assert any(message.get("tool_call_id") == "literal-native-card-read" for message in messages)
    assert "WHOLE_LITERAL_CONDITION" in str(messages)
    trace = run["result"]["retrieval_trace"]
    assert "model_result" not in trace and "result_readiness" not in trace
    assert len(trace["actual_model_calls"]["calls"]) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["vor", "lsr"])
@pytest.mark.parametrize("variant", ["B0_DIRECT", "", "B1_CANDIDATE"])
async def test_final_explicit_no_source_workbook_declaration_still_requires_structured_carrier(monkeypatch, tmp_path, kind, variant):
    answer = "artifact_kind: " + kind + "\nPlain text without workbook rows."
    run = await _run_no_source(monkeypatch, tmp_path, final_text=answer, variant=variant)
    assert len(run["requests"]) == 2 and not run["executions"]
    trace = run["result"]["retrieval_trace"]
    assert trace["model_result"]["status"] == "unstructured"
    assert trace["model_result"]["packaged"] is False
    assert trace["artifact_target"]["artifact_kind"] == kind
    assert run["result"]["answer"].startswith(answer)


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "", "B1_CANDIDATE"])
async def test_query_declared_no_source_workbook_retains_export_contract(monkeypatch, tmp_path, variant):
    query = '{"artifact_kind":"lsr","queries":["literal model card search"]}'
    run = await _run_no_source(monkeypatch, tmp_path, final_text="No authored rows.", query_text=query, variant=variant)
    messages = str(run["requests"][-1].messages)
    assert service._WORKBOOK_RESULT_CARRIER_INSTRUCTION in messages
    assert "source_row" in messages
    assert run["result"]["retrieval_trace"]["model_result"]["packaged"] is False
    assert bool(run["requests"][-1].tools) is (variant == "B0_DIRECT")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "", "B1_CANDIDATE"])
async def test_plain_no_source_answer_does_not_force_read_or_another_model_call(monkeypatch, tmp_path, variant):
    answer = "Literal plain answer from shown evidence. Ω"
    run = await _run_no_source(monkeypatch, tmp_path, final_text=answer, variant=variant)
    assert len(run["requests"]) == 2 and not run["exact_reads"] and not run["executions"]
    assert run["result"]["answer"] == answer
    assert {tool["function"]["name"] for tool in run["requests"][-1].tools} >= {"read_norm_card", "read_source"}


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,status", [("No document declaration.", "missing"),
    ("artifact_kind: unknown\nLiteral answer.", "invalid"),
    ("artifact_kind: lsr\nartifact_kind: vor\nLiteral answer.", "conflict")])
async def test_no_source_unresolved_declaration_is_preserved_without_an_invented_workbook(monkeypatch, tmp_path, raw, status):
    run = await _run_no_source(monkeypatch, tmp_path, final_text=raw)
    assert run["result"]["answer"] == raw and not run["executions"]
    trace = run["result"]["retrieval_trace"]
    assert trace["artifact_target"]["status"] == status
    assert "model_result" not in trace and "result_readiness" not in trace


@pytest.mark.asyncio
async def test_no_source_unfinished_native_read_has_technical_diagnostic_without_lsr_failure(monkeypatch, tmp_path):
    run = await _run_no_source(monkeypatch, tmp_path, final_text="Unused final fixture.",
                               native_read=True, native_name="unknown_reader")
    assert not run["executions"] and not run["exact_reads"]
    assert len(run["requests"]) == 2
    assert "Техническая остановка чтения источников" in run["result"]["answer"]
    assert "ЛСР" not in run["result"]["answer"]
    trace = run["result"]["retrieval_trace"]
    assert trace["tool_loop"]["evidence_read_stop"] == "evidence_read_unknown_tool"
    assert "model_result" not in trace


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "", "B1_CANDIDATE"])
async def test_actual_queries_only_json_native_read_has_no_document_carrier(monkeypatch, tmp_path, variant):
    query = json.dumps({"queries": ["literal model card search"],
                        "commentary": "Only read the exact card; no workbook requested."})
    answer = "Literal whole-card reading answer Ω"
    run = await _run_no_source(monkeypatch, tmp_path, final_text=answer, native_read=True,
                               query_text=query, variant=variant)
    assert run["result"]["answer"] == answer
    assert len(run["requests"]) == 3 and len(run["exact_reads"]) == 1
    assert not run["executions"]
    query_messages = str(run["requests"][0].messages)
    assert "можешь объявить artifact_kind только когда пользователь заказал" in query_messages
    assert "для чтения источников или ответа на вопрос" in query_messages
    for request in run["requests"][1:]:
        messages = str(request.messages)
        assert "Текущий ответ — чтение и объяснение источников" in messages
        assert "LITERAL READ PROFILE Ω" in messages and "LITERAL READ SKILL Ω" in messages
        assert service._WORKBOOK_RESULT_CARRIER_INSTRUCTION not in messages
        assert "source_row |" not in messages
    trace = run["result"]["retrieval_trace"]
    assert trace["artifact_target"]["status"] == "missing"
    assert "model_result" not in trace and "result_readiness" not in trace
    assert len(trace["actual_model_calls"]["calls"]) == 3
    assert any(message.get("tool_call_id") == "literal-native-card-read"
               for message in run["requests"][-1].messages)


@pytest.mark.parametrize("fenced", [False, True])
def test_queries_only_envelope_keeps_literal_fields_without_inventing_document_kind(fenced):
    queries = ["literal query Ω", "artifact_kind: lsr", "Name | value"]
    raw = json.dumps({"queries": queries, "commentary": "Explanation; artifact_kind: vor"}, ensure_ascii=False)
    if fenced:
        raw = "Outer commentary.\n```json\n" + raw + "\n```\nOuter tail."
    envelope = service.decode_model_query_envelope(raw)
    assert envelope is not None and envelope["queries"] == queries
    parsed = service.read_model_query_response(raw, finish_reason="stop")
    assert [item.text for item in parsed["queries"]] == queries
    assert parsed["artifact_kind_declaration"]["status"] == "missing"
    assert not parsed["intentional_empty"] and not parsed["accompanying_answer"]
    assert "Explanation; artifact_kind: vor" in parsed["commentary"]


@pytest.mark.parametrize("kind,status", [(None, "invalid"), ("", "invalid"),
    (17, "invalid"), ([], "invalid"), ("unknown", "invalid")])
def test_optional_kind_does_not_accept_explicit_invalid_declarations(kind, status):
    raw = json.dumps({"artifact_kind": kind, "queries": ["literal query Ω"]}, ensure_ascii=False)
    assert service.decode_model_query_envelope(raw) is None
    parsed = service.read_model_query_response(raw, finish_reason="stop")
    assert parsed["artifact_kind_declaration"]["status"] == status
    assert parsed["queries"] == [] and parsed["unread_tail"] == ""
    assert parsed["accompanying_answer"] == [{"line": raw, "reason": "artifact_metadata_in_query_declaration"}]


@pytest.mark.parametrize("raw", [
    'artifact_kind: unknown\n{"queries":["literal query"]}',
    'artifact_kind: lsr\nartifact_kind: vor\n{"queries":["literal query"]}',
    '{"artifact_kind":"lsr","artifact_kind":"vor","queries":["literal query"]}',
])
def test_queries_only_extension_does_not_bypass_mixed_or_conflicting_metadata(raw):
    assert service.decode_model_query_envelope(raw) is None
    parsed = service.read_model_query_response(raw, finish_reason="length")
    assert parsed["artifact_kind_declaration"]["status"] in {"invalid", "conflict"}
    assert parsed["queries"] == [] and parsed["unread_tail"] == ""
    assert parsed["accompanying_answer"] == [{"line": raw, "reason": "artifact_metadata_in_query_declaration"}]
    assert service.declared_query_attempt_plan(
        declared=parsed, already_declared=[], phase="initial", attempts_remaining=2
    ) == ("repair", service._MODEL_RAG_QUERY_REPAIR_INSTRUCTION)


@pytest.mark.parametrize("queries", [None, "literal query", [None], [7], [""], ["a\nb"], [{"query":"literal"}]])
def test_queries_only_json_keeps_invalid_query_shapes_unsupported(queries):
    raw = json.dumps({"queries": queries})
    assert service.decode_model_query_envelope(raw) is None
    parsed = service.read_model_query_response(raw, finish_reason="stop")
    assert parsed["queries"] == [] and not parsed["intentional_empty"]


@pytest.mark.parametrize("kind,intentional", [(None, False), ("lsr", False), ("vor", True)])
def test_empty_queries_are_not_a_new_source_read_or_lsr_no_search_path(kind, intentional):
    payload = {"queries": []}
    if kind is not None:
        payload["artifact_kind"] = kind
    parsed = service.read_model_query_response(json.dumps(payload), finish_reason="stop")
    assert parsed["queries"] == [] and parsed["intentional_empty"] is intentional
    if not intentional:
        assert service.declared_query_attempt_plan(
            declared=parsed, already_declared=[], phase="initial", attempts_remaining=2
        )[0] == "repair"


@pytest.mark.parametrize("strict", [False, True])
def test_source_read_phase_is_explicit_without_rewriting_literal_professional_profile(strict):
    profile = {"mode":"estimator", "prompt_text":"LITERAL PROFILE Ω\nAlways format export rows.",
               "skill_text":"LITERAL SKILL Ω\nPreserve professional checks."}
    before = copy.deepcopy(profile)
    prompt = service.profile_system_prompt(profile, strict=strict, purpose="source_read")
    assert prompt.startswith(profile["prompt_text"]) and profile["skill_text"] in prompt
    assert "Текущий ответ — чтение и объяснение источников" in prompt
    assert "только когда заказан такой документ" in prompt
    assert "Чтение подтверждается ответом инструмента" in prompt
    assert service._WORKBOOK_RESULT_CARRIER_INSTRUCTION not in prompt
    assert profile == before
