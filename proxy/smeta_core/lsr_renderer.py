"""Preserve every source work row in a renderable Appendix 3 LSR trace."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx
from proxy.smeta_core.contracts import LSRScenario, WorkItem


def _placeholder(work: WorkItem, status: str, message: str) -> dict[str, Any]:
    covered = status == "covered_by"
    marker = "COVERED" if covered else "MISSING"
    amount = 0.0 if covered else None
    return {
        "work_id": work.work_id,
        "source_row": work.source_row,
        "code": "",
        "name": work.title,
        "unit": work.unit,
        "qty": work.quantity or 0.0,
        "rows": [
            {
                "type": "work",
                "label": work.title,
                "columns": {"2": marker, "3": work.title, "4": work.unit, "7": work.quantity, "12": amount},
                "source": "source_work_item",
                "meta": {"status": status, "message": message},
            },
            {
                "type": "position_total",
                "label": "Всего по позиции",
                "columns": {"3": "Всего по позиции", "12": amount},
                "source": "coverage" if covered else "missing",
                "meta": {"status": status, "message": message},
            },
        ],
        "summary": {"total": amount, "flags": [message], "result_status": status},
    }


def complete_lsr_trace(scenario: LSRScenario) -> dict[str, Any]:
    trace = deepcopy(scenario.trace)
    calculated = {
        str(position.get("work_id") or ""): position
        for section in trace.get("sections") or []
        for position in section.get("positions") or []
        if str(position.get("work_id") or "")
    }
    coverage = {
        str(item.get("work_id") or ""): item
        for item in trace.get("coverage") or []
        if str(item.get("work_id") or "")
    }
    binding_by_work = {binding.work_id: binding for binding in scenario.bindings}
    resource_review_by_work = {review.work_id: review for review in scenario.resource_reviews}
    coverage_by_work = {binding.work_id: binding for binding in scenario.coverage_bindings}
    sections: list[dict[str, Any]] = []
    by_section: dict[str, dict[str, Any]] = {}
    for work in scenario.work_items:
        section_name = work.section or "Без раздела"
        section = by_section.get(section_name)
        if section is None:
            section = {"section": section_name, "positions": [], "total": 0.0}
            by_section[section_name] = section
            sections.append(section)
        position = calculated.get(work.work_id)
        if position is None:
            item = coverage.get(work.work_id) or {}
            position = _placeholder(work, str(item.get("status") or "not_calculated"), str(item.get("message") or "строка не рассчитана"))
        section["positions"].append(position)
        section["total"] = round(section["total"] + float((position.get("summary") or {}).get("total") or 0.0), 2)
    trace["sections"] = sections
    trace["name"] = scenario.title
    trace["schema"] = "lsr_rim_complete_trace_v1"
    trace["scenario_id"] = scenario.scenario_id
    trace["evidence_status"] = scenario.evidence_status.value
    trace["calculation_status"] = scenario.calculation_status.value
    trace["blockers"] = list(scenario.blockers)
    trace["warnings"] = list(scenario.warnings)
    trace["row_bindings"] = [
        {
            "row": index,
            "work_id": work.work_id,
            "code": next((binding.norm_code for binding in scenario.bindings if binding.work_id == work.work_id), ""),
            "status": (
                "bound"
                if str((coverage.get(work.work_id) or {}).get("status") or "") in {"accepted", "unsafe_source"}
                else str((coverage.get(work.work_id) or {}).get("status") or "norm_selection_required")
            ),
            "message": str((coverage.get(work.work_id) or {}).get("message") or ""),
            "selection_kind": str(getattr(binding_by_work.get(work.work_id), "selection_kind", "") or ""),
            "is_analog": bool(getattr(binding_by_work.get(work.work_id), "is_analog", False)),
            "reason": str(getattr(binding_by_work.get(work.work_id), "reason", "") or ""),
            "analog_limitations": list(
                getattr(binding_by_work.get(work.work_id), "analog_limitations", ()) or ()
            ),
            "resource_bindings": [
                {
                    "action": item.action,
                    "resource_code": item.resource_code,
                    "resource_name": item.resource_name,
                    "quantity": item.quantity,
                    "quantity_basis": item.quantity_basis,
                    "unit": item.unit,
                    "target_resource_code": item.target_resource_code,
                    "target_resource_name": item.target_resource_name,
                    "reason": item.reason,
                    "basis_ref": item.basis_ref,
                    "source_refs": list(item.source_refs),
                    "price_source_ref": item.price_source_ref,
                }
                for item in scenario.resource_bindings
                if item.work_id == work.work_id
            ],
            "resource_review_status": str(
                getattr(resource_review_by_work.get(work.work_id), "status", "") or ""
            ),
            "resource_review_reason": str(
                getattr(resource_review_by_work.get(work.work_id), "reason", "") or ""
            ),
            "labor_review_status": str(
                getattr(resource_review_by_work.get(work.work_id), "labor_status", "") or ""
            ),
            "labor_review_reason": str(
                getattr(resource_review_by_work.get(work.work_id), "labor_reason", "") or ""
            ),
            "machine_review_status": str(
                getattr(resource_review_by_work.get(work.work_id), "machine_status", "") or ""
            ),
            "machine_review_reason": str(
                getattr(resource_review_by_work.get(work.work_id), "machine_reason", "") or ""
            ),
            "material_review_status": str(
                getattr(resource_review_by_work.get(work.work_id), "material_status", "") or ""
            ),
            "material_review_reason": str(
                getattr(resource_review_by_work.get(work.work_id), "material_reason", "") or ""
            ),
            "dominant_review_status": str(
                getattr(resource_review_by_work.get(work.work_id), "dominant_status", "not_required") or "not_required"
            ),
            "dominant_review_reason": str(
                getattr(resource_review_by_work.get(work.work_id), "dominant_reason", "") or ""
            ),
            "covered_by_work_id": str(
                getattr(coverage_by_work.get(work.work_id), "covered_by_work_id", "") or ""
            ),
            "coverage_reason": str(getattr(coverage_by_work.get(work.work_id), "reason", "") or ""),
        }
        for index, work in enumerate(scenario.work_items, 1)
    ]
    return trace


def export_lsr_xlsx(
    scenario: LSRScenario,
    out_path: str | Path,
    *,
    meta: dict[str, Any] | None = None,
) -> Path:
    return render_lsr_xlsx(complete_lsr_trace(scenario), out_path, meta=meta or {})
