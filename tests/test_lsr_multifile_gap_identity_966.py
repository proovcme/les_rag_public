"""Transport diagnostics preserve complete source identities, including colons."""

from copy import deepcopy

import pytest

from proxy.services.lsr_result_readiness_service import _unbound_rows, build_lsr_result_readiness
from proxy.services.lsr_workbook_adapter_service import collect_lsr_workbook_gaps
from tests.lsr_citation_support import cited_all


@pytest.mark.parametrize("locator", ["Sheet!R2", "read_966::Sheet!R2", "read_966::Раздел: АР!R300", "PDF_TEXT!META:page:7"])
@pytest.mark.parametrize("status", ["norm_not_found", "missing_quantity", "future_status"])
def test_row_binding_diagnostic_roundtrip_keeps_exact_locator_and_status(locator, status):
    trace = {"row_bindings": [{"row": locator, "status": status}]}
    before = deepcopy(trace)
    gaps = collect_lsr_workbook_gaps(trace)
    parsed = _unbound_rows(gaps)
    assert [(item["locator"], item["status"]) for item in parsed] == [(locator, status)]
    assert trace == before
    assert gaps == [f"row:{locator}:{status}"]


def test_unknown_status_and_legacy_empty_status_stay_literal_and_duplicate_free():
    parsed = _unbound_rows(["row: S!R2 : future_status ", "row:S!R2:future_status", "row:S!R3", "row:S!R4:", "price_missing:code", "row:"])
    assert [(item["locator"], item["status"]) for item in parsed] == [("S!R2", "future_status"), ("S!R3", ""), ("S!R4", "")]
    assert all(item["reason"] == "строка не рассчитана" for item in parsed)


def test_multifile_missing_norm_diagnostic_targets_only_its_operation():
    source = "read_966::АР!R14"
    rows = cited_all([{
        "source_row": source, "operation_id": operation, "row_role": "work",
        "title": f"Literal authored work {operation}", "unit": "м", "quantity": 2,
        "norm_code": "ГЭСН01-01-001-01", "norm_status": "EXACT",
    } for operation in ("missing-op", "closed-op")])
    before = deepcopy(rows)
    missing = collect_lsr_workbook_gaps({"row_bindings": [{"row": source, "status": "norm_not_found"}]})
    readiness = build_lsr_result_readiness(packaged=True, rows=rows, missing=missing, job_status="complete",
        row_projection=[{"locator": source, "operation_id": "op:missing-op", "status": "norm_not_found"},
                        {"locator": source, "operation_id": "op:closed-op", "status": "complete"}])
    gap = [item for item in readiness["dimensions"]["norms"]["gaps"] if item["kind"] == "cipher_not_in_base"]
    assert len(gap) == 1
    assert gap[0]["locator"] == source
    assert gap[0]["operation_id"] == "missing-op"
    assert readiness["research_locators"] == [source]
    assert readiness["research_operation_ids"] == ["missing-op"]
    assert rows == before
