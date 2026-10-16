"""Missing query type must not remove either model-owned document result path."""
from copy import deepcopy
import json

import pytest

from proxy.services.model_evidence_read_contract import model_evidence_read_tool_schemas
from proxy.services.model_lsr_result_contract import model_vor_result_field_instruction
from proxy.services.lsr_norm_quality_gate_service import lsr_result_table_instruction
from tests import test_model_rag_sheet_evidence_reads as fixture
from tests.test_vor_native_terminal_workflow_962 import MARKER, _native_response, _lsr_rows, _rows


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.parametrize("kind", ["vor", "lsr"])
async def test_missing_query_kind_keeps_both_optional_terminals_and_model_selects_one(tmp_path, monkeypatch, variant, kind):
    authored = _rows() if kind == "vor" else _lsr_rows()
    before = deepcopy(authored)
    _native_response(monkeypatch, artifact_kind=kind, rows=authored)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_declaration=json.dumps({"queries": ["Literal model-owned source query"]}), final_answer=MARKER)
    assert len(run.requests) == 2 and not run.responses
    tools = list(run.requests[1].tools)
    readers = model_evidence_read_tool_schemas()
    assert tools[:len(readers)] == readers
    assert [tool["function"]["name"] for tool in tools[len(readers):]] == ["build_vor_workbook", "build_lsr_workbook"]
    assert len(run.executions) == 1
    call, _ = run.executions[0]
    assert call["tool"] == f"build_{kind}_workbook"
    assert [{key: row[key] for key in original} for row, original in zip(call["args"]["decisions"], before)] == before
    assert run.result["artifact"]["artifact_kind"] == f"{kind}_workbook"
    trace = run.result["retrieval_trace"]["workbook_terminal_transport"][-1]
    assert trace["artifact_kind"] == kind and trace["transport_complete"] is True
    assert trace["provider_finish_reason"] == "tool_calls"
    shown = "\n".join(message.get("content", "") for message in run.requests[1].messages)
    assert lsr_result_table_instruction() in shown


def test_missing_type_keeps_compact_conditional_vor_contract_and_literal_lsr_contract():
    instruction = lsr_result_table_instruction()
    vor_start = instruction.index("КОНТРАКТ ВОР")
    vor_end = instruction.index("КОНЕЦ КОНТРАКТА ВОР")
    vor = instruction[vor_start:vor_end]
    for requirement in ("source_row, row_role, work_row, title, unit, quantity, open_gap",
            "Явную работу сохраняй работой", "ГОСТ не делает её материалом",
            "работой-родителем либо вопросом", "не автоматическим монтажом",
            "неясной технологией — не header", "включённый состав — покрытием",
            "unit/quantity сохраняй", "неизвестное — null, ноль — 0",
            "calc_quantity, calc_unit, conversion_source", "с формулой и источником"):
        assert requirement in vor
    assert model_vor_result_field_instruction() in lsr_result_table_instruction(artifact_kind="vor")
    lsr_start = instruction.index("КОНТРАКТ ЛСР")
    assert lsr_result_table_instruction(artifact_kind="lsr") in instruction[lsr_start:]
    assert "отсутствие типа в поиске не означает ЛСР" in instruction
    assert "чтение/объяснение — без типа и строк документа" in instruction


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_source_read_answer_is_not_forced_into_an_optional_document_terminal(tmp_path, monkeypatch, variant):
    question = "Read the attachment and explain its stated quantities. Do not issue a workbook."
    answer = "The attachment states Cable A: 12 m; Cable B: 3 m."
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_declaration=json.dumps({"queries": ["Literal source quantities"]}),
        question=question, final_answer=answer)
    assert len(run.requests) == 2 and not run.responses
    assert not run.executions and not run.result.get("artifact")
    assert answer in run.result["answer"]
    assert question in str(run.requests[1].messages)
