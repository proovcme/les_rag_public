"""Typed calculation and finality implementation for the smeta core.

New application callers use :mod:`proxy.smeta_core.application`.  The
``run_smeta_workflow`` symbol below remains a compatibility import only.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from proxy.smeta_core.contracts import (
    CalculationStatus,
    CoverageBinding,
    EvidenceStatus,
    NRSPBinding,
    NormBinding,
    ResourceBinding,
    ResourceReview,
    SmetaWorkflowResult,
    WorkItem,
)


_FULL_NORM_RE = re.compile(
    r"\b((?:ГЭСНМР|ГЭСНМ|ГЭСНП|ГЭСНР|ГЭСН|ФЕРМР|ФЕРМ|ФЕРП|ФЕРР|ФЕР|ТЕРМР|ТЕРМ|ТЕРП|ТЕРР|ТЕР)"
    r"\s*:?\s*\d{2}-\d{2}-\d{3}-\d{2})\b",
    re.IGNORECASE,
)


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _full_norm_code(row: dict[str, Any]) -> str:
    raw = str(_first(row, "norm_code", "code", "basis", "justification", "обоснование") or "")
    match = _FULL_NORM_RE.search(raw)
    return re.sub(r"\s+", "", match.group(1)) if match else ""


def _resource_bindings(row: dict[str, Any], work_id: str, selected_by: str) -> list[ResourceBinding]:
    out: list[ResourceBinding] = []
    for item in row.get("resource_bindings") or []:
        if not isinstance(item, dict):
            continue
        try:
            out.append(ResourceBinding(
                work_id=work_id,
                action=str(item.get("action") or ""),
                selected_by=str(item.get("selected_by") or selected_by),
                resource_name=str(item.get("resource_name") or ""),
                resource_code=str(item.get("resource_code") or ""),
                unit=str(item.get("unit") or ""),
                quantity=_number(item.get("quantity")),
                quantity_basis=str(item.get("quantity_basis") or "explicit"),
                target_resource_code=str(item.get("target_resource_code") or ""),
                target_resource_name=str(item.get("target_resource_name") or ""),
                explicit_price=_number(item.get("explicit_price")),
                price_source_ref=str(item.get("price_source_ref") or ""),
                reason=str(item.get("reason") or ""),
                basis_ref=str(item.get("basis_ref") or ""),
                source_refs=tuple(str(ref) for ref in (item.get("source_refs") or ()) if str(ref)),
            ))
        except (TypeError, ValueError) as error:
            row.setdefault("precalculation_blockers", []).append({
                "code": "resource_binding_contract_rejected",
                "work_id": work_id,
                "action": str(item.get("action") or ""),
                "reason": str(error),
            })
    return out


def _resource_review(row: dict[str, Any], work_id: str, selected_by: str) -> ResourceReview:
    status = str(row.get("resource_review_status") or "unresolved")
    reason = str(row.get("resource_review_reason") or "")
    actions = [item for item in (row.get("resource_bindings") or []) if isinstance(item, dict)]
    if status == "actions_confirmed" and not actions:
        row.setdefault("precalculation_blockers", []).append({
            "code": "resource_review_actions_missing",
            "work_id": work_id,
            "reason": "actions_confirmed requires at least one valid resource action",
        })
        status = "unresolved"
    if status == "keep_all_confirmed" and actions:
        row.setdefault("precalculation_blockers", []).append({
            "code": "resource_review_keep_all_has_actions",
            "work_id": work_id,
            "reason": "keep_all_confirmed cannot carry resource actions",
        })
        status = "unresolved"
    component_fields_present = any(
        key in row for key in ("labor_review_status", "machine_review_status", "material_review_status")
    )
    legacy_component_status = "confirmed" if status in {"keep_all_confirmed", "actions_confirmed"} else "unresolved"
    component_values = {
        "labor_status": str(row.get("labor_review_status") or (legacy_component_status if not component_fields_present else "unresolved")),
        "labor_reason": str(row.get("labor_review_reason") or (reason if not component_fields_present else "")),
        "machine_status": str(row.get("machine_review_status") or (legacy_component_status if not component_fields_present else "unresolved")),
        "machine_reason": str(row.get("machine_review_reason") or (reason if not component_fields_present else "")),
        "material_status": str(row.get("material_review_status") or (legacy_component_status if not component_fields_present else "unresolved")),
        "material_reason": str(row.get("material_review_reason") or (reason if not component_fields_present else "")),
        "dominant_status": str(row.get("dominant_review_status") or "not_required"),
        "dominant_reason": str(row.get("dominant_review_reason") or ""),
    }
    try:
        return ResourceReview(
            work_id=work_id, status=status, selected_by=selected_by, reason=reason, **component_values,
        )
    except ValueError as error:
        row.setdefault("precalculation_blockers", []).append({
            "code": "resource_review_contract_rejected",
            "work_id": work_id,
            "reason": str(error),
        })
        return ResourceReview(
            work_id=work_id,
            status="unresolved",
            selected_by=selected_by,
            reason=str(error),
            labor_status="unresolved",
            machine_status="unresolved",
            material_status="unresolved",
        )


def _attach_precalculation_blockers(trace: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    blockers = [
        blocker
        for row in rows
        for blocker in (row.get("precalculation_blockers") or [])
        if isinstance(blocker, dict)
    ]
    if not blockers:
        return trace
    existing = list(trace.get("blockers") or [])
    existing.extend(blockers)
    trace["blockers"] = existing
    summary = trace.setdefault("summary", {})
    flags = list(summary.get("flags") or [])
    flags.extend(
        f"{item.get('code')}: {item.get('work_id')} ({item.get('reason')})"
        for item in blockers
    )
    summary["flags"] = flags
    summary["result_status"] = "priced_partial" if int(summary.get("bound_rows") or 0) else "norm_selection_required"
    summary["full_amount"] = None
    summary["amount_status"] = "partial"
    trace["evidence_status"] = EvidenceStatus.PARTIAL.value
    trace["calculation_status"] = (
        CalculationStatus.PARTIAL.value
        if int(summary.get("bound_rows") or 0)
        else CalculationStatus.NOT_CALCULATED.value
    )
    return trace


def _coverage_binding(row: dict[str, Any], work_id: str, selected_by: str) -> CoverageBinding | None:
    covered_by = str(row.get("covered_by_work_id") or "").strip()
    if not covered_by:
        return None
    return CoverageBinding(
        work_id=work_id,
        covered_by_work_id=covered_by,
        selected_by=str(row.get("coverage_selected_by") or selected_by),
        reason=str(row.get("coverage_reason") or ""),
        source_refs=tuple(str(ref) for ref in (row.get("source_refs") or ()) if str(ref)),
    )


def run_smeta_workflow(question: str, complete, *, max_steps: int = 16) -> dict[str, Any]:
    """Compatibility wrapper; use ``smeta_core.application`` for new callers."""
    from proxy.smeta_core.application import run_smeta_workflow as run_application

    return run_application(question, complete, max_steps=max_steps)


def calculate_visible_rows(
    rows: list[dict[str, Any]],
    *,
    selected_by: str = "model",
    title: str = "Локальный сметный расчет (смета)",
    book: str | None = None,
    kac_map: dict[str, float] | None = None,
    k_ozp: float = 1.0,
    k_em: float = 1.0,
    coefficient_basis: str = "",
) -> dict[str, Any]:
    """Visible rows with explicit full norm codes -> complete, renderable LSR trace."""
    from proxy.smeta_core.calculator import calculate_scenario
    from proxy.smeta_core.lsr_renderer import complete_lsr_trace

    work_items: list[WorkItem] = []
    bindings: list[NormBinding] = []
    resource_bindings: list[ResourceBinding] = []
    resource_reviews: list[ResourceReview] = []
    coverage_bindings: list[CoverageBinding] = []
    nr_sp_bindings: list[NRSPBinding] = []
    for index, row in enumerate(rows or [], 1):
        work_id = str(row.get("work_id") or row.get("vor_row_id") or f"row-{index}")
        title_value = str(_first(row, "title", "name", "work", "наименование", "работа") or "Позиция сметы")
        unit = str(_first(row, "unit", "ед", "ед.", "единица", "единица измерения") or "")
        quantity = _number(_first(row, "quantity", "qty", "quantity_total", "volume", "количество", "объем", "объём"))
        source_ref = str(row.get("source_ref") or row.get("source") or "")
        work = WorkItem(
            work_id=work_id,
            title=title_value,
            quantity=quantity,
            unit=unit,
            section=str(row.get("section") or "Без раздела"),
            source_row=index,
            note=str(row.get("note") or row.get("comment") or ""),
            source_refs=(source_ref,) if source_ref else (),
        )
        work_items.append(work)
        resource_bindings.extend(_resource_bindings(row, work_id, selected_by))
        if _full_norm_code(row) and "resource_review_status" in row:
            resource_reviews.append(_resource_review(row, work_id, selected_by))
        coverage = _coverage_binding(row, work_id, selected_by)
        if coverage:
            coverage_bindings.append(coverage)
        code = _full_norm_code(row)
        if code:
            bindings.append(
                NormBinding(
                    work_id=work_id,
                    norm_code=code,
                    selected_by=selected_by,
                    selection_kind=str(row.get("selection_kind") or "exact"),
                    is_analog=bool(row.get("is_analog", False)),
                    reason=str(row.get("norm_reason") or row.get("reason") or "явный шифр в видимой строке"),
                    source_refs=(source_ref,) if source_ref else (),
                    analog_limitations=tuple(
                        str(item) for item in (row.get("analog_limitations") or ()) if str(item).strip()
                    ),
                    applicability=str(row.get("applicability") or ""),
                    technology_check=dict(row.get("technology_check") or {}),
                )
            )
        nr_sp_rule_id = str(row.get("nr_sp_rule_id") or "").strip()
        if nr_sp_rule_id:
            nr_sp_bindings.append(NRSPBinding(
                work_id=work_id,
                rule_id=nr_sp_rule_id,
                selected_by=selected_by,
                reason=str(row.get("nr_sp_reason") or "явная строка НР/СП"),
                source_refs=(source_ref,) if source_ref else (),
            ))
    scenario = calculate_scenario(
        work_items,
        bindings,
        resource_bindings=resource_bindings,
        resource_reviews=resource_reviews,
        coverage_bindings=coverage_bindings,
        nr_sp_bindings=nr_sp_bindings,
        title=title,
        book=book,
        kac_map=kac_map,
        k_ozp=k_ozp,
        k_em=k_em,
        coefficient_basis=coefficient_basis,
        coefficient_selected_by=selected_by,
    )
    return _attach_precalculation_blockers(complete_lsr_trace(scenario), rows)


def calculate_visible_rows_revision(
    rows: list[dict[str, Any]],
    *,
    selected_by: str = "model",
    created_by: str | None = None,
    parent_revision_id: str = "",
    change_note: str = "",
    revision_root: str | None = None,
    **calculation_kwargs: Any,
) -> dict[str, Any]:
    """Calculate visible rows and persist one immutable revision.

    Persistence is opt-in at this boundary so pure callers remain side-effect free.
    Runtime/API callers pass a revision root or the canonical default explicitly.
    """
    from proxy.smeta_core.calculator import calculate_scenario
    from proxy.smeta_core.contracts import LSRRevision
    from proxy.smeta_core.lsr_renderer import complete_lsr_trace
    from proxy.smeta_core.revision_store import DEFAULT_ROOT, save_revision

    # Reuse the canonical row mapping; calculation itself stays in calculator.py.
    work_items: list[WorkItem] = []
    bindings: list[NormBinding] = []
    resource_bindings: list[ResourceBinding] = []
    resource_reviews: list[ResourceReview] = []
    coverage_bindings: list[CoverageBinding] = []
    nr_sp_bindings: list[NRSPBinding] = []
    for index, row in enumerate(rows or [], 1):
        work_id = str(row.get("work_id") or row.get("vor_row_id") or f"row-{index}")
        source_ref = str(row.get("source_ref") or row.get("source") or "")
        work_items.append(WorkItem(
            work_id=work_id,
            title=str(_first(row, "title", "name", "work", "наименование", "работа") or "Позиция сметы"),
            quantity=_number(_first(row, "quantity", "qty", "quantity_total", "volume", "количество", "объем", "объём")),
            unit=str(_first(row, "unit", "ед", "ед.", "единица", "единица измерения") or ""),
            section=str(row.get("section") or "Без раздела"),
            source_row=int(row.get("source_row") or index),
            note=str(row.get("note") or row.get("comment") or ""),
            source_refs=tuple(str(ref) for ref in (row.get("source_refs") or ()) if str(ref))
            or ((source_ref,) if source_ref else ()),
            assumptions=tuple(str(item) for item in (row.get("assumptions") or ()) if str(item)),
        ))
        resource_bindings.extend(_resource_bindings(row, work_id, selected_by))
        if _full_norm_code(row) and "resource_review_status" in row:
            resource_reviews.append(_resource_review(row, work_id, selected_by))
        coverage = _coverage_binding(row, work_id, selected_by)
        if coverage:
            coverage_bindings.append(coverage)
        code = _full_norm_code(row)
        if code:
            bindings.append(NormBinding(
                work_id=work_id,
                norm_code=code,
                selected_by=selected_by,
                selection_kind=str(row.get("selection_kind") or "exact"),
                is_analog=bool(row.get("is_analog", False)),
                reason=str(row.get("norm_reason") or row.get("reason") or "явный шифр в видимой строке"),
                source_refs=(source_ref,) if source_ref else (),
                analog_limitations=tuple(
                    str(item) for item in (row.get("analog_limitations") or ()) if str(item).strip()
                ),
                applicability=str(row.get("applicability") or ""),
                technology_check=dict(row.get("technology_check") or {}),
            ))
        nr_sp_rule_id = str(row.get("nr_sp_rule_id") or "").strip()
        if nr_sp_rule_id:
            nr_sp_bindings.append(NRSPBinding(
                work_id=work_id,
                rule_id=nr_sp_rule_id,
                selected_by=selected_by,
                reason=str(row.get("nr_sp_reason") or "явная строка НР/СП"),
                source_refs=(source_ref,) if source_ref else (),
            ))
    scenario = calculate_scenario(
        work_items,
        bindings,
        resource_bindings=resource_bindings,
        resource_reviews=resource_reviews,
        coverage_bindings=coverage_bindings,
        nr_sp_bindings=nr_sp_bindings,
        coefficient_selected_by=selected_by,
        **calculation_kwargs,
    )
    revision = LSRRevision(
        scenario=scenario,
        parent_revision_id=parent_revision_id,
        created_by=created_by or selected_by,
        change_note=change_note,
    )
    path = save_revision(revision, root=revision_root or DEFAULT_ROOT)
    trace = _attach_precalculation_blockers(complete_lsr_trace(scenario), rows)
    trace["revision"] = {
        "revision_id": revision.revision_id,
        "parent_revision_id": revision.parent_revision_id,
        "created_at": revision.created_at,
        "created_by": revision.created_by,
        "path": str(path),
    }
    return trace


def _norm_source_blocker(source_status: dict[str, Any]) -> dict[str, Any] | None:
    sources = source_status.get("sources") if isinstance(source_status, dict) else []
    for source in sources or []:
        if source.get("id") != "gesn_base":
            continue
        if str(source.get("status") or "") == "ok":
            return None
        integrity = source.get("integrity") if isinstance(source.get("integrity"), dict) else {}
        return {
            "code": "normative_base_not_trusted",
            "source_id": "gesn_base",
            "status": source.get("status") or "unknown",
            "reason": "; ".join(str(x) for x in (integrity.get("reasons") or [])[:6])
            or "normative base is not trusted for final pricing",
        }
    return None


def finalize_estimate_result(
    result: dict[str, Any],
    *,
    source_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach one honest result contract and prevent unsafe ``final_total``.

    Existing adapters may still calculate an observable draft while migration is in
    progress. If the normative source is quarantined, the amount remains visible only
    as an unverified draft and can never be represented as final.
    """
    out = deepcopy(result)
    source_status = source_status or out.get("smeta_service_sources") or {}
    source_blocker = _norm_source_blocker(source_status)
    computed_items = [item for item in (out.get("computed") or []) if isinstance(item, dict)]
    unsafe_computed = any(
        str(item.get("norm_source_kind") or "") == "structured_sqlite"
        and not (item.get("norm_source_integrity") or {}).get("trusted_for_pricing")
        for item in computed_items
    )
    blocker = source_blocker if unsafe_computed or (source_blocker and not computed_items) else None
    blockers = list(out.get("blockers") or [])
    if blocker and not any(item.get("code") == blocker["code"] for item in blockers if isinstance(item, dict)):
        blockers.append(blocker)
    computed = bool(computed_items)
    if blocker:
        out["total_status"] = "partial" if computed else "blocked"
        out["final_total"] = None
        if isinstance(out.get("partial_total"), dict):
            out["partial_total"]["unverified_due_to_source_quarantine"] = True
            out["partial_total"]["reason"] = "нормативная база не прошла semantic integrity gate"
        evidence_status = EvidenceStatus.BLOCKED
        calculation_status = CalculationStatus.UNSAFE_SOURCE if computed else CalculationStatus.NOT_CALCULATED
    elif out.get("total_status") == "complete":
        evidence_status = EvidenceStatus.SUPPORTED
        calculation_status = CalculationStatus.COMPLETE
    elif computed:
        evidence_status = EvidenceStatus.PARTIAL
        calculation_status = CalculationStatus.PARTIAL
    else:
        evidence_status = EvidenceStatus.PARTIAL
        calculation_status = CalculationStatus.NOT_CALCULATED

    amount = 0.0
    partial = out.get("partial_total") if isinstance(out.get("partial_total"), dict) else {}
    final = out.get("final_total") if isinstance(out.get("final_total"), dict) else {}
    try:
        amount = float((final or partial).get("grand_total") or 0.0)
    except (TypeError, ValueError):
        amount = 0.0
    contract = SmetaWorkflowResult(
        evidence_status=evidence_status,
        calculation_status=calculation_status,
        amount_known=amount,
        blockers=blockers,
        trace={
            "normative_source": next(
                (source for source in (source_status.get("sources") or []) if source.get("id") == "gesn_base"),
                {},
            )
        },
    )
    out["blockers"] = blockers
    out["evidence_status"] = evidence_status.value
    out["calculation_status"] = calculation_status.value
    out["workflow_result"] = contract.as_dict()
    return out
