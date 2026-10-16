"""A missing model document type never activates estimate-only additions."""

from copy import deepcopy
import hashlib
import inspect
import json

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.lsr_norm_quality_gate_service import lsr_result_table_instruction
from proxy.services.model_lsr_result_contract import model_vor_result_field_instruction
from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests import test_model_rag_sheet_evidence_reads as fixture


LITERAL_QUERIES = ["[S!R2] Cable A literal [variant Ω]", '"S!R3 Cable B literal"']


def _vor_rows():
    return [{"source_row": locator, "row_role": "work", "title": title,
             "unit": "m", "quantity": quantity, "open_gap": ""}
            for locator, title, quantity in [("S!R2", "Cable A", 12), ("S!R3", "Cable B", 3)]]


@pytest.mark.asyncio
@pytest.mark.parametrize("query_kind", [None, "vor", "lsr"])
async def test_natural_review_of_saved_vor_adds_estimate_candidates_only_after_explicit_lsr(
    tmp_path, monkeypatch, query_kind,
):
    """Exercise real durable review, query execution and document packaging."""
    monkeypatch.setenv("LES_LSR_SYSTEM_CANDIDATE_QUERIES", "on")
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False,
        query_declaration=json.dumps({"artifact_kind": "vor", "queries": []}),
        final_answer=json.dumps({"artifact_kind": "vor", "rows": _vor_rows()}))
    store = WorkbookResearchJobService()
    original_job_id = run.result["retrieval_trace"]["workbook_research_job"]["job_id"]
    original = store.get(original_job_id)
    assert original["task_context"]["model_artifact_kind"] == "vor"
    assert len(original["accepted_rows"]) == 2
    old_rows = deepcopy(original["accepted_rows"])
    old_queries = len(run.queries)
    request = inspect.getclosurevars(run.resume_same_request).nonlocals["request"]
    request.req.question = "Учти замечание инженера и перепроверь документ"
    query_envelope = {"queries": LITERAL_QUERIES}
    if query_kind is not None:
        query_envelope["artifact_kind"] = query_kind
    final_kind = "lsr" if query_kind == "lsr" else "vor"
    reviewed_rows = [{**{key: row[key] for key in (
        "source_row", "row_role", "title", "unit", "quantity", "operation_id",
    )}, "expected_revision": row["revision"]} for row in old_rows]
    if final_kind == "lsr":
        for row in reviewed_rows:
            row.update(norm_code="", norm_status="MISSING", gap_reason="no_suitable_candidate",
                       open_gap="Модель не выбрала норму", evidence_refs=["Q1.H1"])
    run.responses.extend([
        InferenceResponse(text=json.dumps(query_envelope, ensure_ascii=False), tool_calls=(),
                          finish_reason="stop", usage={}),
        InferenceResponse(text=json.dumps({"artifact_kind": final_kind, "rows": reviewed_rows},
                                         ensure_ascii=False), tool_calls=(), finish_reason="stop", usage={}),
    ])
    result = await run.resume_same_request()
    queries = run.queries[old_queries:]
    assert queries[:2] == LITERAL_QUERIES, "literal searches must execute without rewriting"
    assert (len(queries) > 2) is (query_kind == "lsr")
    trace = result["retrieval_trace"]
    assert trace["chat_refinement"]["status"] == "reviewing"
    assert trace["artifact_target"]["artifact_kind"] == final_kind
    assert run.executions[-1][0]["tool"] == "build_" + final_kind + "_workbook"
    assert not run.responses, "the application must not start another semantic model cycle"
    assert store.get(original_job_id)["accepted_rows"] == old_rows
    if query_kind != "lsr":
        assert not trace.get("system_candidate_queries", {}).get("sheets")
    else:
        assert trace["system_candidate_queries"]["sheets"]["S"]["queries_authored_by_code"] > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("query_kind", [None, "lsr"])
async def test_direct_baseline_keeps_only_literal_model_queries(tmp_path, monkeypatch, query_kind):
    monkeypatch.setenv("LES_LSR_SYSTEM_CANDIDATE_QUERIES", "on")
    declaration = {"queries": LITERAL_QUERIES}
    if query_kind is not None:
        declaration["artifact_kind"] = query_kind
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant="B0_DIRECT",
        query_declaration=json.dumps(declaration, ensure_ascii=False))
    assert run.queries == LITERAL_QUERIES
    assert len(run.requests) == 2 and not run.responses
    assert not run.result["retrieval_trace"].get("system_candidate_queries", {}).get("sheets")


def test_undeclared_document_contract_has_two_explicit_conditional_sections():
    instruction = lsr_result_table_instruction(sheet_clause="CURRENT_PACKET\n",
                                              remaining_clause="\nREMAINING_PACKET")
    vor = model_vor_result_field_instruction()
    lsr = lsr_result_table_instruction(artifact_kind="lsr")
    assert instruction.startswith("CURRENT_PACKET\n") and instruction.endswith("\nREMAINING_PACKET")
    assert instruction.count("CURRENT_PACKET") == instruction.count("REMAINING_PACKET") == 1
    assert "Тип документа определяешь ты" in instruction
    assert "отсутствие декларации в запросном ходе не означает выбор ЛСР" in instruction
    vor_section = instruction.split("КОНТРАКТ ВОР — только при artifact_kind: vor\n", 1)[1].split(
        "\nКОНЕЦ КОНТРАКТА ВОР", 1)[0]
    for field in ("source_row", "row_role", "work_row", "title", "unit", "quantity", "open_gap",
                  "calc_quantity", "calc_unit", "conversion_source"):
        assert field in vor_section
    assert "не являются условиями создания ВОР" in vor_section
    assert vor not in instruction, "the full dedicated VOR contract is reserved for an explicit VOR"
    assert instruction.split("КОНТРАКТ ЛСР — только при artifact_kind: lsr\n", 1)[1].split(
        "\nКОНЕЦ КОНТРАКТА ЛСР", 1)[0] == lsr
    # The compact conditional carrier is mandatory and is never cut to fit.
    # It must not duplicate the complete VOR contract in a still-undecided turn.
    assert len(instruction) < len(lsr) + 1200
    assert hashlib.sha256(lsr.encode("utf-8")).hexdigest() == (
        "03ae9ba8a17f55be977790a6226790a690b6406fcc890e1228fa3570c1ad7826"
    )


def test_unknown_workbook_system_prompt_is_source_scoped_without_unconditional_estimate_rules():
    snapshot = {"mode": "estimator", "prompt_text": "Literal profile Ω", "skill_text": "Literal skill"}
    unknown = service.profile_system_prompt(snapshot, strict=False, purpose="workbook_result")
    assert service._SOURCE_CONTEXT_ROLE_INSTRUCTION in unknown
    assert "Применяй только контракт выбранного тобой типа" in unknown
    assert service._TABULAR_LSR_OPERATION_INSTRUCTION not in unknown
    assert model_vor_result_field_instruction() not in unknown
    assert "Literal profile Ω" in unknown and "Literal skill" in unknown
    explicit_lsr = service.profile_system_prompt(snapshot, strict=False, purpose="workbook_result",
                                                artifact_kind="lsr")
    assert service._TABULAR_LSR_OPERATION_INSTRUCTION in explicit_lsr
    for purpose in ("query", "source_read", "answer"):
        assert "отдельные условные контракты" not in service.profile_system_prompt(
            snapshot, strict=False, purpose=purpose)
