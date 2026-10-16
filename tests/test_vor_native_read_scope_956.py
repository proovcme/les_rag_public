"""Actual B0/B1 native-read frames scope obligations by the model's current type."""
import json

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services.model_evidence_read_contract import (
    MODEL_EVIDENCE_READ_INSTRUCTION, model_evidence_read_instruction, model_evidence_read_tool_schemas,
)
from tests.test_model_rag_sheet_evidence_reads import _run_sheet, RESOURCE_A, RESOURCE_B


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.parametrize("kind", ["vor", "lsr", ""])
async def test_model_declared_type_scopes_actual_native_read_frames_without_changing_tools_or_source(
        tmp_path, monkeypatch, variant, kind):
    calls = []

    def scoped_instruction(*, artifact_kind=""):
        calls.append(artifact_kind)
        return model_evidence_read_instruction(artifact_kind=artifact_kind)

    monkeypatch.setattr(app, "model_evidence_read_instruction", scoped_instruction)
    queries = ["S!R2 — Cable A", "S!R3 — Cable B"]
    query = json.dumps({"artifact_kind": kind, "queries": queries}) if kind else None
    authored = [{"source_row": source, "row_role": "work", "title": title,
                 "unit": "m", "quantity": quantity, "work_row": "", "open_gap": ""}
                for source, title, quantity in [("S!R2", "Install Cable A", 12), ("S!R3", "Install Cable B", 3)]]
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant, query_declaration=query,
        final_answer=json.dumps({"artifact_kind": "vor", "rows": authored}) if kind == "vor" else None)
    assert len(run.requests) == 4 and not run.responses
    if variant == "B1_CANDIDATE":
        assert calls[0] == "", "initial pre-query scope cannot guess a document type"
    assert calls[-1] == kind
    expected = model_evidence_read_instruction(artifact_kind=kind)
    for request in run.requests[1:]:
        shown = "\n".join(str(message.get("content") or "") for message in request.messages)
        assert expected in shown
        if kind == "vor":
            assert MODEL_EVIDENCE_READ_INSTRUCTION not in shown
        else:
            assert expected == MODEL_EVIDENCE_READ_INSTRUCTION
        assert "S!R2" in shown and "S!R3" in shown
        # This deliberately literal legacy request asks for LSR. The new scope
        # follows the model declaration rather than rewriting that user text.
        assert "Собери ЛСР; ВОР не создавай" in shown
    readers = model_evidence_read_tool_schemas()
    for request in run.requests[1:]:
        tools = list(request.tools)
        # Existing read contracts stay byte-for-byte equal and in the same order.
        assert tools[:len(readers)] == readers
        if kind:
            assert len(tools) == len(readers) + 1
            terminal = tools[-1]["function"]
            assert terminal["name"] == f"build_{kind}_workbook"
            assert set(terminal["parameters"]["properties"]) == {"attachment_id", "decisions"}
            assert terminal["parameters"]["properties"]["attachment_id"]["enum"] == ["read_123456abcdef"]
        else:
            assert tools == readers, "a missing model type must not enable a terminal"
    native = run.result["retrieval_trace"]["tool_loop"]["evidence_reads"]
    assert [item["call"]["tool"] for item in native] == ["read_norm_card", "read_resource_price", "read_resource_price"]
    assert [item["call"]["args"] for item in native] == [
        {"norm_key": "immutable-norm"}, {"code": RESOURCE_A}, {"code": RESOURCE_B}]
    assert all(item["status"] == "ok" for item in native)
    if kind == "vor":
        assert run.executions[0][0]["tool"] == "build_vor_workbook"
        saved = run.executions[0][0]["args"]["decisions"]
        assert [{key: row[key] for key in source} for row, source in zip(saved, authored)] == authored
        assert run.result["retrieval_trace"]["result_readiness"]["vor_complete"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["vor", "lsr"])
async def test_declared_terminal_and_reader_schemas_are_identical_in_actual_b0_b1(tmp_path, monkeypatch, kind):
    projections = []
    for variant in ("B0_DIRECT", "B1_CANDIDATE"):
        case = tmp_path / variant
        case.mkdir()
        with monkeypatch.context() as scoped:
            run = await _run_sheet(case, scoped, reads=True, variant=variant,
                query_declaration=json.dumps({"artifact_kind": kind, "queries": ["Literal source query"]}),
                final_answer=(json.dumps({"artifact_kind": "vor", "rows": [
                    {"source_row": source, "row_role": "work", "title": title, "unit": "m", "quantity": quantity}
                    for source, title, quantity in (("S!R2", "Install Cable A", 12), ("S!R3", "Install Cable B", 3))]})
                    if kind == "vor" else None))
        assert len(run.requests) == 4 and not run.responses
        projections.append([list(request.tools) for request in run.requests[1:]])
    assert projections[0] == projections[1]
