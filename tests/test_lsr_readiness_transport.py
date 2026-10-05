"""Readiness must describe the calculator's result after the real chat projection."""
from copy import deepcopy

import pytest

from proxy.services import chat_evidence_application_service as chat
from proxy.services import fsem_machinist_service as fsem
from proxy.services import rim_lsr_trace_service as rim
from proxy.services.lsr_workbook_adapter_service import collect_lsr_price_gaps
from tests.test_chat_evidence_application_service import _lsr_tool_result_with_basis
from tests.test_rim_lsr_trace_service import _active_resource_norm
from tests.lsr_citation_support import cited


@pytest.mark.parametrize("authored_ids", [True, False])
def test_covered_operation_survives_chat_history_and_harvest(monkeypatch, authored_ids):
    parent = cited(_active_resource_norm(monkeypatch))
    child = dict(parent, source_row="S!R3", operation_id="child", norm_code="",
                 covered_by_work_id="R2", coverage="Included by the cited composition")
    parent["norm_status"] = "NEEDS_RESEARCH"
    if not authored_ids:
        parent.pop("operation_id")
        child.pop("operation_id")
    rows = [parent, child]
    before = deepcopy(rows)
    trace = rim.build_lsr_trace_from_visible_rows(rows)
    assert trace["row_projection"][1]["status"] == "covered"
    raw = _lsr_tool_result_with_basis()
    raw.update(row_projection=trace["row_projection"], price_gaps=[], missing=[],
               price_basis={"match": "exact"})
    raw_before = deepcopy(raw)
    saved = chat.safe_workbook_history_projection(raw)
    assert chat.safe_workbook_history_projection(saved) == saved
    harvested = chat.harvest_workbook_tool_result(saved)
    assert harvested["row_projection"][1]["covered_by_operation_id"] == trace["row_projection"][1]["covered_by_operation_id"]
    readiness = chat.build_lsr_result_readiness(packaged=True, rows=rows,
        pricing_status="priced_partial", row_projection=harvested["row_projection"])
    norm_gaps = readiness["dimensions"]["norms"]["gaps"]
    assert {gap["locator"] for gap in norm_gaps} == {"S!R2"}
    assert readiness["estimate_complete"] is False
    assert raw == raw_before and rows == before


def test_history_preserves_coverage_identity_without_unbounded_body():
    raw = _lsr_tool_result_with_basis()
    raw["row_projection"] = [{"locator": f"S!R{i}", "operation_id": f"op:{i}",
        "covered_by_operation_id": "op:parent", "status": "covered",
        "raw_card": "x" * 100000} for i in range(1, 319)]
    projection = chat.harvest_workbook_tool_result(raw)["row_projection"]
    assert len(projection) == 318
    assert all(row["covered_by_operation_id"] == "op:parent" for row in projection)
    assert all("raw_card" not in row for row in projection)


@pytest.mark.parametrize("authored_ids", [True, False])
def test_catalog_annotations_keep_coverage_identity_from_the_model_boundary(monkeypatch, authored_ids):
    from proxy.services.lsr_source_coverage_service import operation_identity

    parent = cited(_active_resource_norm(monkeypatch))
    child = dict(parent, source_row="S!R3", operation_id="child", norm_code="",
                 covered_by_work_id="R2", coverage="Included by the cited composition")
    parent["norm_status"] = "NEEDS_RESEARCH"
    if not authored_ids:
        parent.pop("operation_id")
        child.pop("operation_id")
    rows = [parent, child]
    before = deepcopy(rows)
    annotated = deepcopy(rows)
    for row in annotated:
        row.update(_catalog_source_values=[row["title"], row["unit"], str(row["quantity"])],
                   _catalog_source_numbers=[float(row["quantity"])], _catalog_source_quantity_known=True,
                   _catalog_source_unit=row["unit"])
    trace = rim.build_lsr_trace_from_visible_rows(annotated)
    assert trace["row_projection"][1]["status"] == "covered"
    assert [operation_identity(row) for row in rows] == [operation_identity(row) for row in annotated]
    readiness = chat.build_lsr_result_readiness(packaged=True, rows=rows,
        pricing_status="priced_partial", row_projection=trace["row_projection"])
    assert {gap["locator"] for gap in readiness["dimensions"]["norms"]["gaps"]} == {"S!R2"}
    assert readiness["estimate_complete"] is False and rows == before


def test_catalog_annotations_do_not_erase_distinct_authored_decisions():
    from proxy.services.lsr_source_coverage_service import operation_identity

    row = {"source_row": "S!R2", "row_role": "work", "title": "Literal", "unit": "m", "quantity": 12, "norm_code": "A"}
    for delta in ({"quantity": 13}, {"norm_code": "B"}, {"covered_by_work_id": "S!R3"}, {"evidence_refs": ["Q2.H1"]}):
        assert operation_identity(row) != operation_identity({**row, **delta})


@pytest.mark.parametrize("with_fsem_gap", [False, True])
def test_rejected_resource_action_is_an_actionable_gap_without_requesting_a_price(with_fsem_gap):
    conflict = {"code": "resource_binding_conflict", "reason": "resource target is missing or ambiguous"}
    position = {"code": "Authored norm", "name": "Reused material", "source_row": "S!R2",
                "rows": [], "summary": {"resource_binding_conflicts": [conflict]}}
    trace = {"sections": [{"positions": [position, {**position, "source_row": "S!R3"}]}]}
    before = deepcopy(trace)
    gaps = collect_lsr_price_gaps(trace)
    assert len(gaps) == 2
    assert all(gap["price_action"] == "resource_binding_conflict" for gap in gaps)
    assert all("Целевой ресурс отсутствует" in gap["action"] for gap in gaps)
    assert all("Задайте цену" not in gap["action"] for gap in gaps)
    if with_fsem_gap:
        gaps.append({"resource": "ОТм", "price_action": "needs_fsem_resolution", "action": "Сверьте часы ФСЭМ"})
    ready = chat.build_lsr_result_readiness(packaged=True, pricing_status="priced_partial", price_gaps=gaps)
    action = ready["dimensions"]["prices"]["action"]
    assert "действия над ресурсами" in action and "Задайте" not in action
    assert len(ready["dimensions"]["prices"]["gaps"]) == len(gaps)
    assert ready["estimate_complete"] is False and trace == before


class _TariffBook:
    region = "Test region"
    quarter = "Test period"

    def lookup(self, code):
        if code in {"M-A", "M-B", "4-100-030", "4-100-040"}:
            return {"price_current_eff": 10, "unit": "чел.-ч" if code.startswith("4-") else "маш.-ч"}
        return None


def _fsem_position():
    return {"code": "Authored norm", "qty": 0.15, "resources": [
        {"kind": "machine", "code": "M-A", "name": "Machine A", "unit": "маш.-ч", "per_unit": 0.02},
        {"kind": "machine", "code": "M-B", "name": "Machine B", "unit": "маш.-ч", "per_unit": 0.002},
        {"kind": "machinist", "code": "", "name": "ОТм", "unit": "маш.-ч", "per_unit": 0.02}]}


@pytest.mark.parametrize("missing_mapping", [False, True])
def test_fsem_unresolved_asks_for_hour_reconciliation_before_a_tariff(monkeypatch, missing_mapping):
    monkeypatch.setattr(fsem, "lookup", lambda code, _path: None if missing_mapping and code == "M-B" else
        {"crew_hours": 1, "driver_code": "4-100-030" if code == "M-A" else "4-100-040", "driver_grade": 3})
    position = _fsem_position()
    before = deepcopy(position)
    trace = rim.build_position_trace(position, pricebook=_TariffBook())
    assert trace["summary"]["fsem_trace"]["status"] == "unresolved"
    assert trace["summary"]["amount_status"] != "complete"
    row = next(row for row in trace["rows"] if row["type"] == "resource_machinist")
    assert row["meta"]["price_action"] == "needs_fsem_resolution"
    gaps = collect_lsr_price_gaps({"sections": [{"positions": [trace]}]}, pricebook=_TariffBook())
    gap = next(gap for gap in gaps if gap["resource"] == "ОТм")
    assert gap["price_action"] == "needs_fsem_resolution"
    assert "Задайте цену" not in gap["action"]
    assert "ФСЭМ" in gap["action"] and "0.02" in gap["action"]
    ready = chat.build_lsr_result_readiness(packaged=True, pricing_status="priced_partial", price_gaps=[gap])
    assert "Задайте" not in ready["dimensions"]["prices"]["action"]
    assert "ФСЭМ" in ready["dimensions"]["prices"]["action"]
    assert trace["summary"]["zpm"] == 0 and position == before


def test_named_machinist_without_tariff_still_asks_for_price():
    position = {"code": "Authored norm", "qty": 1, "resources": [
        {"kind": "machinist", "code": "4-MISSING", "name": "Driver", "unit": "чел.-ч", "per_unit": 2}]}
    trace = rim.build_position_trace(position, pricebook=_TariffBook())
    assert trace["summary"]["fsem_trace"]["status"] == "not_applicable"
    row = next(row for row in trace["rows"] if row["type"] == "resource_machinist")
    assert row["meta"]["price_action"] == "needs_machinist_rate"
    gaps = collect_lsr_price_gaps({"sections": [{"positions": [trace]}]})
    assert "Задайте цену" in next(gap["action"] for gap in gaps if gap["resource"] == "Driver")


def test_reconciled_fsem_still_prices_driver_codes(monkeypatch):
    monkeypatch.setattr(fsem, "lookup", lambda code, _path:
        {"crew_hours": 1, "driver_code": "4-100-030" if code == "M-A" else "4-100-040", "driver_grade": 3})
    position = _fsem_position()
    position["resources"][-1]["per_unit"] = 0.022
    trace = rim.build_position_trace(position, pricebook=_TariffBook())
    assert trace["summary"]["fsem_trace"]["status"] == "reconciled"
    assert trace["summary"]["zpm"] == 0.03
    assert all(row["meta"]["price_action"] != "needs_fsem_resolution" for row in trace["rows"] if row["type"] == "resource_machinist")
