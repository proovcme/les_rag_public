"""A source-grounded VOR is not reported as an unpriced LSR."""

import copy
import json

import pytest

from proxy.services import chat_evidence_application_service as service


@pytest.mark.parametrize("kind,missing", [("vor", False), ("lsr", True), ("", True)])
def test_only_declared_normless_vor_does_not_require_external_norm_citation(kind, missing):
    rows = [{"source_row": "Different Ω!R8", "row_role": "work", "title": "Operation",
             "quantity": 4, "unit": "шт"}]
    before = copy.deepcopy(rows)
    errors = service.validate_model_rag_result_structure(rows, [], expected_source_rows=1,
                                                        artifact_kind=kind)
    assert ("missing_evidence_ref:Different Ω!R8" in errors) is missing
    assert rows == before


def test_vor_still_reports_uncited_selected_norm_and_invented_supplied_reference():
    base = {"source_row": "Input!R4", "row_role": "work", "quantity": 2, "unit": "m"}
    errors = service.validate_model_rag_result_structure(
        [{**base, "norm_code": "ГЭСН01-01-001-01"}], [], expected_source_rows=1, artifact_kind="vor")
    assert "missing_evidence_ref:Input!R4" in errors
    errors = service.validate_model_rag_result_structure(
        [{**base, "evidence_refs": "Q987.H2"}], [], expected_source_rows=1, artifact_kind="vor")
    assert "unknown_evidence_ref:Q987.H2" in errors


def test_vor_not_created_and_partial_notices_keep_technical_defects_visible():
    kwargs = {"errors": ["answer_truncated"], "row_count": 3, "artifact_kind": "vor"}
    failed = service.format_lsr_not_created_notice(**kwargs)
    partial = service.format_lsr_partial_notice(**kwargs)
    assert failed.startswith("ВОР не создана:")
    assert partial.startswith("ВОР сформирована с замечаниями:")
    assert "ответ модели оборван" in failed and "ответ модели оборван" in partial
    assert "ЛСР" not in partial and "В расчёт" not in partial
    assert service.format_lsr_partial_notice(errors=["answer_truncated"], row_count=3).startswith(
        "ЛСР собрана частично:")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_real_application_delivers_normless_vor_without_estimate_warning(tmp_path, monkeypatch, variant):
    from tests import test_model_rag_sheet_evidence_reads as fixture

    rows = [{"source_row": locator, "row_role": "work", "work_row": "", "title": title,
             "unit": "m", "quantity": quantity, "open_gap": ""}
            for locator, title, quantity in [("S!R2", "Cable A", 12), ("S!R3", "Cable B", 3)]]
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_declaration='{"artifact_kind":"vor","queries":[]}',
        final_answer=json.dumps({"artifact_kind": "vor", "rows": rows}))
    assert run.executions[0][0]["tool"] == "build_vor_workbook"
    trace = run.result["retrieval_trace"]
    assert trace["result_readiness"]["technical_complete"]
    assert trace["result_readiness"]["vor_complete"]
    assert not trace["result_readiness"]["open_questions"]
    assert "missing_evidence_ref" not in str(trace["model_result"])
    assert "ЛСР собрана частично" not in run.result["answer"]
    assert "ВОР сформирован" in run.result["answer"]
