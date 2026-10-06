"""A result table cannot silently become model-authored search declarations."""
import json

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.model_research_tool_service import ModelResearchToolService
from tests.test_model_rag_sheet_evidence_reads import _run_sheet


FRESH_TABLE_OUTPUT = (
    "ЛСР: Ведомость объемов работ №8 — Обеспечение аварийных светильников БАП\r\n"
    "**Регион:** Санкт-Петербург\r\n"
    "**Период:** III квартал 2026 года\r\n"
    "Согласно приложенному ВОР, работы включают:\r\n"
    "| № п/п | Наименование работы | Ед. изм. | Кол-во | Примечание / Материал |\r\n"
    "| :--- | :--- | :---: | :---: | :--- |\r\n"
    "| 2.1 | Демонтаж кабельных линий | м | 160,0 | |\r\n"
    "**Следующий шаг:** Получить данные следующего листа манифеста.\r\n"
)
REASON = "result_table_in_query_declaration"


@pytest.mark.parametrize("raw", [
    FRESH_TABLE_OUTPUT,
    "Here is the bill:\n| Description | Quantity |\n| --- | ---: |\n| Install device | 4 |\nSummary.",
    "Inventario Ω:\nNombre | Cantidad\n:--- | ---:\nTubo Ø20 | 2,5\nFin.",
    "```markdown\n| 結果 |\n| --- |\n| 値 |\n```",
])
def test_unenveloped_result_table_is_preserved_without_executable_queries(raw):
    declared = service.read_model_query_response(raw, finish_reason="stop")
    assert declared["queries"] == []
    assert declared["unread_tail"] == ""
    assert declared["accompanying_answer"] == [{"line": raw, "reason": REASON}]
    assert not declared["intentional_empty"]
    diagnostic = service.declared_query_output_diagnostics(raw, declared)
    assert diagnostic["accepted_count"] == 0
    assert diagnostic["reason_counts"] == {REASON: 1}


def test_cut_result_table_gets_existing_format_repair_and_never_tail_continuation():
    declared = service.read_model_query_response(FRESH_TABLE_OUTPUT, finish_reason="length")
    phase, suffix = service.declared_query_attempt_plan(
        declared=declared, already_declared=[], phase="initial", attempts_remaining=2)
    assert declared["answer_cut"]
    assert declared["unread_tail"] == ""
    assert phase == "repair" and suffix == service._MODEL_RAG_QUERY_REPAIR_INSTRUCTION
    assert service.declared_query_attempt_plan(
        declared=declared, already_declared=[], phase="repair", attempts_remaining=1) == ("", "")


def test_explicit_queries_envelope_keeps_table_commentary_separate_and_literal():
    queries = ["Literal search for item Ω; 2,5 mm", "Name | value", "--- | ---"]
    raw = json.dumps({"artifact_kind": "lsr", "queries": queries,
                      "commentary": FRESH_TABLE_OUTPUT}, ensure_ascii=False)
    declared = service.read_model_query_response(raw, finish_reason="stop")
    assert [q.text for q in declared["queries"]] == queries[:2]
    # Existing line rules continue to apply to the explicit query list: this
    # change neither promotes a table rule to a query nor changes its wording.
    assert declared["accompanying_answer"] == [{"line": queries[2], "reason": "table_rule_line"}]
    assert declared["commentary"] == FRESH_TABLE_OUTPUT
    assert declared["artifact_kind_declaration"]["artifact_kind"] == "lsr"


@pytest.mark.parametrize("raw", [
    "Literal query Ω; item Ø20",
    "1. Literal query Ω; item Ø20",
    "1) Literal query Ω; item Ø20",
    "- Literal query Ω; item Ø20",
    "* Literal query Ω; item Ø20",
    '"Literal query Ω; item Ø20"',
    "'Literal query Ω; item Ø20'",
    'search_sources("Literal query Ω; item Ø20")',
    '```text\n"Literal query Ω; item Ø20"\n```',
])
def test_supported_literal_query_formats_are_unchanged(raw):
    declared = service.read_model_query_response(raw, finish_reason="stop")
    assert [q.text for q in declared["queries"]] == ["Literal query Ω; item Ø20"]
    assert not declared["accompanying_answer"]


@pytest.mark.parametrize("raw, expected", [
    ("Literal query with A | B\nAnother literal query", ["Literal query with A | B", "Another literal query"]),
    ("Literal query with A | B\n---\nAnother literal query", ["Literal query with A | B", "Another literal query"]),
    ("| Single row with no separator |", ["| Single row with no separator |"]),
    ("Name | Qty\n-- | --\nLiteral query", ["Name | Qty", "Literal query"]),
    ("A | B | C\n--- | ---\nLiteral query", ["A | B | C", "Literal query"]),
    ('"Header | Qty"\n"--- | ---"', ["Header | Qty"]),
])
def test_pipes_or_incomplete_table_shapes_do_not_invent_a_result_table(raw, expected):
    declared = service.read_model_query_response(raw, finish_reason="stop")
    assert [q.text for q in declared["queries"]] == expected
    assert all(item["reason"] != REASON for item in declared["accompanying_answer"])


@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.asyncio
async def test_actual_producer_does_not_search_table_then_executes_one_literal_repaired_query(tmp_path, monkeypatch, variant):
    repaired_query = "S!R2 — Cable A"
    monkeypatch.setenv("LES_LSR_SYSTEM_CANDIDATE_QUERIES", "off")
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
                           query_repair=FRESH_TABLE_OUTPUT,
                           query_declaration=json.dumps({"artifact_kind": "lsr", "queries": [repaired_query]}))
    assert run.queries == [repaired_query]
    assert len(run.requests) == 3 and not run.responses
    assert len(run.executions) == 1
    diagnostics = run.result["retrieval_trace"]["model_query_outputs"]
    assert len(diagnostics) == 2
    assert diagnostics[0]["declared_parse"]["accepted_count"] == 0
    assert diagnostics[0]["declared_parse"]["reason_counts"] == {REASON: 1}
    assert diagnostics[1]["purpose"].endswith("query_repair")
    assert diagnostics[1]["declared_parse"]["accepted_count"] == 1
    original_system = run.requests[0].messages[0]["content"]
    repair_system = run.requests[1].messages[0]["content"]
    assert service._MODEL_RAG_QUERY_REPAIR_INSTRUCTION not in original_system
    assert service._MODEL_RAG_QUERY_REPAIR_INSTRUCTION in repair_system
    assert run.requests[0].temperature == run.requests[1].temperature


@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.asyncio
async def test_actual_repeated_table_repair_fails_visibly_without_any_rag_or_no_data(tmp_path, monkeypatch, variant):
    async def no_search(self, call):
        pytest.fail("Malformed result-table output must not initiate a search")
    monkeypatch.setattr(ModelResearchToolService, "execute", no_search)
    recorded = []
    original_failure = service.model_query_failure
    def record_failure(detail, **kwargs):
        recorded.append((detail, kwargs))
        return original_failure(detail, **kwargs)
    monkeypatch.setattr(service, "model_query_failure", record_failure)

    with pytest.raises(service.HTTPException) as caught:
        await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
                         query_repair=FRESH_TABLE_OUTPUT, query_declaration=FRESH_TABLE_OUTPUT)
    assert len(recorded) == 1
    assert "MODEL_RAG_QUERY_LIST_EMPTY" in json.dumps(caught.value.detail)
    assert "NO_DATA" not in json.dumps(caught.value.detail)
    outputs = recorded[0][1]["trace"]["model_query_outputs"]
    assert len(outputs) == 2
    assert recorded[0][1]["final_texts"] == [FRESH_TABLE_OUTPUT, FRESH_TABLE_OUTPUT]
    assert all(output["declared_parse"]["accepted_count"] == 0 for output in outputs)
