"""Own document metadata cannot also become a model-authored search query."""
import json

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.model_research_tool_service import ModelResearchToolService
from tests.test_model_rag_sheet_evidence_reads import _run_sheet


# Exact public query projection from the frozen frame3 B1, not reconstructed
# whole primary raw: final.json /retrieval_trace/tool_loop/passes/2/
# declared_queries/1/query_text. SHA of the recorded final.json:
# 92ff35f48d649bcdb10410d77471cc556975be127c1527f8930b233fc5d15f89.
ACTUAL_EXECUTED_FIELD = "artifact_kind: lsr"
REASON = "artifact_metadata_in_query_declaration"


@pytest.mark.parametrize("raw", [
    ACTUAL_EXECUTED_FIELD,
    "artifact_kind: vor\r\n",
    "Outer explanation.\r\nartifact_kind: lsr\r\nqueries:\r\n- Literal query Ω\r\n",
    "artifact_kind: lsr\nLiteral query Ω",
    "Literal query Ω\nartifact_kind: lsr",
    "artifact_kind: unsupported\nLiteral query Ω",
    "artifact_kind: lsr\nartifact_kind: vor\nLiteral query Ω",
    "artifact_kind: lsr\nartifact_kind: lsr\nLiteral query Ω",
])
@pytest.mark.parametrize("finish_reason", ["stop", "length"])
def test_unenveloped_own_metadata_is_preserved_whole_without_queries(raw, finish_reason):
    declared = service.read_model_query_response(raw, finish_reason=finish_reason)
    assert declared["artifact_kind_declaration"]["status"] != "missing"
    assert declared["queries"] == []
    assert declared["unread_tail"] == ""
    assert declared["accompanying_answer"] == [{"line": raw, "reason": REASON}]
    assert declared["answer_cut"] is (finish_reason == "length")
    assert not declared["intentional_empty"]
    diagnostic = service.declared_query_output_diagnostics(raw, declared)
    assert diagnostic["accepted_count"] == 0
    assert diagnostic["reason_counts"] == {REASON: 1}


def test_cut_mixed_metadata_uses_only_existing_one_format_repair():
    declared = service.read_model_query_response(
        "artifact_kind: lsr\n1. Literal query Ω\n2. Incomplete query", finish_reason="length")
    phase, instruction = service.declared_query_attempt_plan(
        declared=declared, already_declared=[], phase="initial", attempts_remaining=2)
    assert phase == "repair"
    assert instruction == service._MODEL_RAG_QUERY_REPAIR_INSTRUCTION
    assert service.declared_query_attempt_plan(
        declared=declared, already_declared=[], phase="repair", attempts_remaining=1) == ("", "")


@pytest.mark.parametrize("fenced", [False, True])
def test_valid_envelope_preserves_literal_metadata_search_and_commentary(fenced):
    queries = [ACTUAL_EXECUTED_FIELD, "Literal source query Ω", "Name | value"]
    raw = json.dumps({"artifact_kind": "lsr", "queries": queries,
                      "commentary": "artifact_kind: vor\nInternal explanation."}, ensure_ascii=False)
    if fenced:
        raw = "Outer explanation.\n```json\n" + raw + "\n```\nOuter tail."
    declared = service.read_model_query_response(raw, finish_reason="stop")
    assert [query.text for query in declared["queries"]] == queries
    assert "Internal explanation." in declared["commentary"]
    assert declared["artifact_kind_declaration"]["artifact_kind"] == "lsr"
    assert not declared["accompanying_answer"]


@pytest.mark.parametrize("raw", [
    "Literal source query Ω; dimension 2,5",
    "1. Literal source query Ω; dimension 2,5",
    "1) Literal source query Ω; dimension 2,5",
    "- Literal source query Ω; dimension 2,5",
    "* Literal source query Ω; dimension 2,5",
    '"Literal source query Ω; dimension 2,5"',
    "'Literal source query Ω; dimension 2,5'",
    'search_sources("Literal source query Ω; dimension 2,5")',
    '```text\n"Literal source query Ω; dimension 2,5"\n```',
])
def test_prior_literal_plain_and_list_formats_are_unchanged(raw):
    declared = service.read_model_query_response(raw, finish_reason="stop")
    assert [query.text for query in declared["queries"]] == ["Literal source query Ω; dimension 2,5"]
    assert not declared["accompanying_answer"]


@pytest.mark.parametrize("raw", [
    "Search for document artifact_kind: lsr specification",
    '"artifact_kind: lsr"',
    'search_sources("artifact_kind: lsr")',
])
def test_inline_or_explicit_literal_query_is_not_a_standalone_metadata_declaration(raw):
    declared = service.read_model_query_response(raw, finish_reason="stop")
    assert declared["artifact_kind_declaration"]["status"] == "missing"
    expected = raw if raw.startswith("Search for") else ACTUAL_EXECUTED_FIELD
    assert [query.text for query in declared["queries"]] == [expected]


def test_public_prose_without_transport_syntax_remains_literal_not_semantically_filtered():
    # Exact first public accepted query projection of the same frozen packet.
    raw = ('Лес: "ВОР" от "ЛСР" отличаются не только наличием цен, но и наличием норм. '
           'В исходнике есть работы, но нет норм. Значит, нужно искать нормы. Ищем по операциям.')
    declared = service.read_model_query_response(raw, finish_reason="stop")
    assert declared["artifact_kind_declaration"]["status"] == "missing"
    assert [query.text for query in declared["queries"]] == [raw]
    assert not declared["accompanying_answer"]


@pytest.mark.parametrize("raw", [
    '["artifact_kind: lsr", "Literal query Ω"]',
    '[\n"artifact_kind: lsr",\n"Literal query Ω"\n]',
    '```json\n["artifact_kind: lsr", "Literal query Ω"]\n```',
])
def test_bare_json_array_keeps_existing_unsupported_transport_result(raw):
    # Root JSON query envelopes are supported; bare JSON arrays are currently
    # rejected by the old reader. Their strings are not standalone metadata.
    declared = service.read_model_query_response(raw, finish_reason="stop")
    assert declared["artifact_kind_declaration"]["status"] == "missing"
    assert declared["queries"] == []
    assert all(item["reason"] != REASON for item in declared["accompanying_answer"])


def test_intentionally_empty_vor_envelope_keeps_no_search_behavior():
    declared = service.read_model_query_response('{"artifact_kind":"vor","queries":[]}', finish_reason="stop")
    assert declared["intentional_empty"]
    assert declared["queries"] == []
    assert not declared["accompanying_answer"]


@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.asyncio
async def test_actual_producer_repairs_mixed_metadata_once_then_searches_literal_query(tmp_path, monkeypatch, variant):
    repaired_query = "S!R2 — Cable A"
    raw = "Explanation.\r\nartifact_kind: lsr\r\n- Must not execute this mixed-format query\r\n"
    monkeypatch.setenv("LES_LSR_SYSTEM_CANDIDATE_QUERIES", "off")
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
                           query_repair=raw,
                           query_declaration=json.dumps({"artifact_kind": "lsr", "queries": [repaired_query]}))
    assert run.queries == [repaired_query]
    assert len(run.requests) == 3 and not run.responses
    assert len(run.executions) == 1
    outputs = run.result["retrieval_trace"]["model_query_outputs"]
    assert len(outputs) == 2
    assert outputs[0]["declared_parse"]["accepted_count"] == 0
    assert outputs[0]["declared_parse"]["reason_counts"] == {REASON: 1}
    assert outputs[1]["purpose"].endswith("query_repair")
    assert outputs[1]["declared_parse"]["accepted_count"] == 1
    assert service._MODEL_RAG_QUERY_REPAIR_INSTRUCTION in run.requests[1].messages[0]["content"]
    assert run.requests[0].temperature == run.requests[1].temperature


@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.asyncio
async def test_actual_repeated_mixed_metadata_fails_without_rag_or_no_data(tmp_path, monkeypatch, variant):
    async def no_search(self, call):
        pytest.fail("Unsupported mixed metadata must not initiate any search")
    monkeypatch.setattr(ModelResearchToolService, "execute", no_search)
    raw = "artifact_kind: lsr\r\nqueries:\r\n- Literal query Ω\r\n"
    recorded = []
    original_failure = service.model_query_failure
    def record_failure(detail, **kwargs):
        recorded.append((detail, kwargs))
        return original_failure(detail, **kwargs)
    monkeypatch.setattr(service, "model_query_failure", record_failure)
    with pytest.raises(service.HTTPException) as caught:
        await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
                         query_repair=raw, query_declaration=raw)
    assert len(recorded) == 1
    assert "MODEL_RAG_QUERY_LIST_EMPTY" in json.dumps(caught.value.detail)
    assert "NO_DATA" not in json.dumps(caught.value.detail)
    outputs = recorded[0][1]["trace"]["model_query_outputs"]
    assert len(outputs) == 2
    assert recorded[0][1]["final_texts"] == [raw, raw]
    assert all(output["declared_parse"]["accepted_count"] == 0 for output in outputs)
