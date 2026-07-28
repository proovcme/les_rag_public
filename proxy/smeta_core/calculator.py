"""Deterministic calculation for explicitly bound work items."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import uuid4
from itertools import product

from proxy.services import fgis_price_service
from proxy.services import rim_lsr_trace_service as rim
from proxy.smeta_core.contracts import (
    CalculationStatus,
    CoverageBinding,
    EvidenceStatus,
    LSRScenario,
    NRSPBinding,
    NormBinding,
    ResourceBinding,
    ResourceReview,
    PriceTraceRecord,
    CoefficientTrace,
    WorkItem,
)
from proxy.smeta_core.norm_validator import validate_binding
from proxy.smeta_core.resource_normalizer import normalize_norm_resources


def _resource_key(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("ё", "е").split())


def _resource_matches(resource: dict[str, Any], binding: ResourceBinding) -> bool:
    if binding.target_resource_code:
        return _resource_key(resource.get("code")) == _resource_key(binding.target_resource_code)
    return _resource_key(resource.get("name")) == _resource_key(binding.target_resource_name)


def _resource_quantity_convert(quantity: float, source_unit: str, target_unit: str) -> float | None:
    source = _resource_key(source_unit).replace(".", "")
    target = _resource_key(target_unit).replace(".", "")
    aliases = {"шт": "шт", "м²": "м2", "м³": "м3"}
    source = aliases.get(source, source)
    target = aliases.get(target, target)
    if source == target:
        return quantity
    factor = {
        ("т", "кг"): 1000.0,
        ("кг", "т"): 0.001,
        ("100 м2", "м2"): 100.0,
        ("м2", "100 м2"): 0.01,
        ("1000 м", "м"): 1000.0,
        ("м", "1000 м"): 0.001,
        ("100 шт", "шт"): 100.0,
        ("шт", "100 шт"): 0.01,
    }.get((source, target))
    return quantity * factor if factor is not None else None


def _bound_resource_line(
    binding: ResourceBinding,
    *,
    work_qty: float,
    total_quantity: float | None = None,
) -> dict[str, Any]:
    total_quantity = float(binding.quantity or 0.0) if total_quantity is None else float(total_quantity)
    if work_qty <= 0 and total_quantity:
        raise ValueError("resource binding cannot be normalized against zero work quantity")
    line: dict[str, Any] = {
        "kind": "material",
        "name": binding.resource_name,
        "unit": binding.unit,
        "per_unit": total_quantity / work_qty if work_qty else 0.0,
        "resource_binding": {
            "action": binding.action,
            "selected_by": binding.selected_by,
            "reason": binding.reason,
            "source_refs": list(binding.source_refs),
            "price_source_ref": binding.price_source_ref,
            "quantity_basis": binding.quantity_basis,
        },
    }
    if binding.basis_ref:
        line["resource_binding"]["basis_ref"] = binding.basis_ref
    if binding.resource_code:
        line["code"] = binding.resource_code
    if binding.explicit_price is not None:
        line["price"] = float(binding.explicit_price)
        line["price_source_ref"] = binding.price_source_ref
    return line


def _apply_resource_bindings(
    norm_resources: list[dict[str, Any]],
    decisions: list[ResourceBinding],
    *,
    work_qty: float,
    physical_quantity: float | None = None,
    physical_unit: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply only explicit resource decisions; unmatched targets fail closed."""
    resources = [dict(item) for item in norm_resources]
    problems: list[dict[str, Any]] = []
    for decision in decisions:
        matches = [index for index, item in enumerate(resources) if _resource_matches(item, decision)]
        if decision.action in {"replace", "exclude", "reuse"} and not matches:
            problems.append({
                "code": "resource_target_not_found",
                "work_id": decision.work_id,
                "action": decision.action,
                "target_resource_code": decision.target_resource_code,
                "target_resource_name": decision.target_resource_name,
            })
            continue
        if decision.action in {"replace", "exclude", "reuse"}:
            target_rows = [resources[index] for index in matches]
            resources = [item for index, item in enumerate(resources) if index not in set(matches)]
        else:
            target_rows = []
        if decision.action in {"add", "replace"}:
            try:
                total_quantity = None
                if decision.quantity_basis == "target_norm":
                    target_units = {_resource_key(item.get("unit")) for item in target_rows}
                    if len(target_units) != 1:
                        raise ValueError("target_norm resources have incompatible units")
                    raw_total = sum(float(item.get("per_unit") or 0.0) * work_qty for item in target_rows)
                    source_unit = str(target_rows[0].get("unit") or "")
                    total_quantity = _resource_quantity_convert(raw_total, source_unit, decision.unit)
                    if total_quantity is None:
                        raise ValueError(
                            f"target_norm quantity unit mismatch: {source_unit!r} -> {decision.unit!r}"
                        )
                elif decision.quantity_basis == "source_work":
                    if physical_quantity is None:
                        raise ValueError("source_work quantity is missing")
                    total_quantity = _resource_quantity_convert(
                        float(physical_quantity), physical_unit, decision.unit
                    )
                    if total_quantity is None:
                        raise ValueError(
                            f"source_work quantity unit mismatch: {physical_unit!r} -> {decision.unit!r}"
                        )
                resources.append(
                    _bound_resource_line(decision, work_qty=work_qty, total_quantity=total_quantity)
                )
            except ValueError as exc:
                problems.append({
                    "code": "resource_binding_invalid_quantity",
                    "work_id": decision.work_id,
                    "reason": str(exc),
                })
        elif decision.action == "reuse":
            # Keep the exact targeted norm resource and its consumption visible,
            # changing only its price to zero. Rebuilding it as a synthetic ``add``
            # loses the norm unit/quantity and used to crash when the model quite
            # correctly omitted those redundant fields from a reuse decision.
            for target in target_rows:
                reused = dict(target)
                reused["price"] = 0.0
                reused["price_source_ref"] = decision.price_source_ref or "reuse decision"
                reused["resource_binding"] = {
                    "action": "reuse",
                    "selected_by": decision.selected_by,
                    "reason": decision.reason,
                    "source_refs": list(decision.source_refs),
                    "price_source_ref": decision.price_source_ref or "reuse decision",
                }
                if decision.basis_ref:
                    reused["resource_binding"]["basis_ref"] = decision.basis_ref
                resources.append(reused)
    return resources, problems


def _pricebook(book: str | None):
    path = fgis_price_service.resolve_pricebook_path(book, allow_scratch=bool(book))
    return fgis_price_service.get_pricebook(path) if path else None


def calculate_scenario(
    work_items: list[WorkItem],
    bindings: list[NormBinding],
    *,
    resource_bindings: list[ResourceBinding] | None = None,
    resource_reviews: list[ResourceReview] | None = None,
    coverage_bindings: list[CoverageBinding] | None = None,
    nr_sp_bindings: list[NRSPBinding] | None = None,
    title: str = "Локальный сметный расчет (смета)",
    book: str | None = None,
    kac_map: dict[str, float] | None = None,
    k_ozp: float = 1.0,
    k_em: float = 1.0,
    coefficient_basis: str = "",
    coefficient_selected_by: str = "model",
) -> LSRScenario:
    nr_sp_binding_by_work = {item.work_id: item for item in (nr_sp_bindings or [])}
    resource_review_by_work = {item.work_id: item for item in (resource_reviews or [])}
    resources_by_work: dict[str, list[ResourceBinding]] = {}
    for item in resource_bindings or []:
        resources_by_work.setdefault(item.work_id, []).append(item)
    coverage_by_work: dict[str, CoverageBinding] = {}
    duplicate_coverage: list[str] = []
    for item in coverage_bindings or []:
        if item.work_id in coverage_by_work:
            duplicate_coverage.append(item.work_id)
            continue
        coverage_by_work[item.work_id] = item
    binding_by_work: dict[str, NormBinding] = {}
    duplicate_bindings: list[str] = []
    for binding in bindings:
        if binding.work_id in binding_by_work:
            duplicate_bindings.append(binding.work_id)
            continue
        binding_by_work[binding.work_id] = binding

    coverage: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = [
        {"code": "duplicate_norm_binding", "work_id": work_id}
        for work_id in sorted(set(duplicate_bindings))
    ]
    blockers.extend(
        {"code": "duplicate_coverage_binding", "work_id": work_id}
        for work_id in sorted(set(duplicate_coverage))
    )
    if (k_ozp != 1.0 or k_em != 1.0) and not str(coefficient_basis or "").strip():
        blockers.append({
            "code": "coefficient_source_missing",
            "work_id": "",
            "k_ozp": k_ozp,
            "k_em": k_em,
        })
    work_ids = {work.work_id for work in work_items}
    unsafe_source = False
    for index, work in enumerate(work_items, 1):
        binding = binding_by_work.get(work.work_id)
        coverage_binding = coverage_by_work.get(work.work_id)
        if binding is not None and coverage_binding is not None:
            blockers.append({"code": "norm_and_coverage_conflict", "work_id": work.work_id})
            coverage.append({
                "work_id": work.work_id,
                "source_row": work.source_row or index,
                "status": "rejected",
                "work": asdict(work),
                "message": "строка не может одновременно иметь норму и covered_by",
            })
            continue
        if binding is None:
            if coverage_binding is not None:
                provider = coverage_binding.covered_by_work_id
                if provider not in work_ids or provider not in binding_by_work or provider in coverage_by_work:
                    blockers.append({
                        "code": "coverage_provider_invalid",
                        "work_id": work.work_id,
                        "covered_by_work_id": provider,
                    })
                    coverage.append({
                        "work_id": work.work_id,
                        "source_row": work.source_row or index,
                        "status": "rejected",
                        "work": asdict(work),
                        "message": "covered_by ссылается на строку без прямой нормы",
                    })
                    continue
                coverage.append({
                    "work_id": work.work_id,
                    "source_row": work.source_row or index,
                    "status": "covered_by",
                    "work": asdict(work),
                    "coverage_binding": asdict(coverage_binding),
                    "message": coverage_binding.reason,
                })
                continue
            coverage.append({
                "work_id": work.work_id,
                "source_row": work.source_row or index,
                "status": "norm_selection_required",
                "work": asdict(work),
                "message": "модель или пользователь ещё не выбрал норму",
            })
            blockers.append({"code": "norm_selection_required", "work_id": work.work_id})
            continue
        validation = validate_binding(work, binding)
        status = str(validation.get("status") or "rejected")
        coverage.append({
            "work_id": work.work_id,
            "source_row": work.source_row or index,
            "status": status,
            "work": asdict(work),
            "binding": asdict(binding),
            "validation": validation,
        })
        if status == "rejected":
            coverage[-1]["message"] = str(validation.get("reason") or "formal validation failed")
            blockers.append({
                "code": "norm_binding_rejected",
                "work_id": work.work_id,
                "reason": validation.get("reason") or "formal validation failed",
            })
            continue
        unsafe_source = unsafe_source or status == "unsafe_source"
        norm = validation.get("norm") or {}
        from proxy.services import gesn_service

        norm_record = gesn_service.get_norm(binding.norm_code, strict_family=True) or {}
        norm_quantity = float(validation.get("norm_quantity") or 0.0)
        explicit_resources, resource_problems = _apply_resource_bindings(
            normalize_norm_resources(list(norm_record.get("resources") or [])),
            resources_by_work.get(work.work_id, []),
            work_qty=norm_quantity,
            physical_quantity=work.quantity,
            physical_unit=work.unit,
        )
        if resource_problems:
            blockers.extend(resource_problems)
        resource_review = resource_review_by_work.get(work.work_id)
        # Review statuses describe evidence/completeness; they are not hidden
        # edit commands.  Only explicit model-owned ResourceBinding actions may
        # add, replace, reuse or exclude a norm resource.  Filtering a whole
        # component here made a bound position look calculated while silently
        # reducing its labor/machines/materials to zero.
        nr_sp_binding = nr_sp_binding_by_work.get(work.work_id)
        official_name = str(norm_record.get("name") or norm.get("name") or "").strip()
        positions.append({
            "work_id": work.work_id,
            "source_row": work.source_row or index,
            "source_refs": list(work.source_refs),
            "section": work.section or "Без раздела",
            "code": binding.norm_code,
            "name": work.title or official_name,
            "official_name": official_name,
            "unit": norm.get("unit") or work.unit,
            "qty": norm_quantity,
            "source_quantity": work.quantity,
            "source_unit": work.unit,
            "unit_conversion_factor": float(validation.get("unit_conversion_factor") or 0.0),
            "norm_quantity": norm_quantity,
            "resource_quantity_coefficient": 1.0,
            "physical_quantity": work.quantity,
            "physical_unit": work.unit,
            "binding_selected_by": binding.selected_by,
            "binding_reason": binding.reason,
            "selection_kind": binding.selection_kind,
            "is_analog": binding.is_analog,
            "analog_limitations": list(binding.analog_limitations),
            "applicability": binding.applicability,
            "technology_check": dict(binding.technology_check),
            "resources": explicit_resources,
            "resource_bindings": [
                asdict(item) for item in resources_by_work.get(work.work_id, [])
            ],
            "resource_review_status": str(
                getattr(resource_review_by_work.get(work.work_id), "status", "unresolved")
            ),
            "resource_review_reason": str(
                getattr(resource_review_by_work.get(work.work_id), "reason", "")
            ),
            "labor_review_status": str(getattr(resource_review, "labor_status", "unresolved")),
            "labor_review_reason": str(getattr(resource_review, "labor_reason", "")),
            "machine_review_status": str(getattr(resource_review, "machine_status", "unresolved")),
            "machine_review_reason": str(getattr(resource_review, "machine_reason", "")),
            "material_review_status": str(getattr(resource_review, "material_status", "unresolved")),
            "material_review_reason": str(getattr(resource_review, "material_reason", "")),
            "dominant_review_status": str(getattr(resource_review, "dominant_status", "not_required")),
            "dominant_review_reason": str(getattr(resource_review, "dominant_reason", "")),
            "norm_source_integrity": validation.get("source_integrity") or {},
            "nr_sp_rule_id": nr_sp_binding.rule_id if nr_sp_binding else "",
            "nr_sp_selected_by": nr_sp_binding.selected_by if nr_sp_binding else "",
            "nr_sp_reason": nr_sp_binding.reason if nr_sp_binding else "",
        })
        if work.work_id not in resource_review_by_work:
            positions[-1].pop("resource_review_status", None)
            positions[-1].pop("resource_review_reason", None)
            for key in (
                "labor_review_status", "labor_review_reason", "machine_review_status",
                "machine_review_reason", "material_review_status", "material_review_reason",
                "dominant_review_status", "dominant_review_reason",
            ):
                positions[-1].pop(key, None)

    pricebook = _pricebook(book)
    lsr = rim.build_lsr_trace(
        positions,
        pricebook=pricebook,
        kac_map=kac_map,
        k_ozp=k_ozp,
        k_em=k_em,
        coefficient_basis=coefficient_basis,
        name=title,
    )
    lsr["coverage"] = coverage
    price_trace_records: list[PriceTraceRecord] = []
    for section in lsr.get("sections") or []:
        for position in section.get("positions") or []:
            for row in position.get("rows") or []:
                if not str(row.get("type") or "").startswith("resource_"):
                    continue
                columns = row.get("columns") if isinstance(row.get("columns"), dict) else {}
                price_trace_records.append(PriceTraceRecord(
                    resource_code=str(columns.get("2") or ""),
                    price=float(columns["10"]) if columns.get("10") not in (None, "") else None,
                    source_type=str(row.get("source") or "missing"),
                    source_ref=str((row.get("meta") or {}).get("basis") or ""),
                    region=str(getattr(pricebook, "region", "") or ""),
                    period=str(getattr(pricebook, "quarter", "") or ""),
                    note=str((row.get("meta") or {}).get("price_action") or ""),
                ))
    coefficient_traces: list[CoefficientTrace] = []
    if k_ozp != 1.0:
        coefficient_traces.append(CoefficientTrace(
            coefficient_id="k_ozp", value=k_ozp, applies_to=("labor",),
            selected_by=coefficient_selected_by, source_ref=coefficient_basis,
        ))
    if k_em != 1.0:
        coefficient_traces.append(CoefficientTrace(
            coefficient_id="k_em", value=k_em, applies_to=("machine", "machinist"),
            selected_by=coefficient_selected_by, source_ref=coefficient_basis,
        ))
    summary = lsr.setdefault("summary", {})
    from proxy.services.tax_policy_service import resolve_vat

    vat_trace = resolve_vat(str(getattr(pricebook, "quarter", "") or "")) if pricebook else {
        "status": "unresolved", "vat_pct": None, "reason": "pricebook is missing"
    }
    net_total = float(summary.get("total") or 0.0)
    if vat_trace.get("status") == "resolved":
        vat_pct = float(vat_trace["vat_pct"])
        vat_amount = round(net_total * vat_pct / 100, 2)
        full_net = summary.get("full_amount")
        summary.update({
            "total_without_vat": net_total,
            "known_amount_without_vat": net_total,
            "vat_pct": vat_pct,
            "vat": vat_amount,
            "total_with_vat": round(net_total + vat_amount, 2),
            "known_amount_with_vat": round(net_total + vat_amount, 2),
            "full_amount_without_vat": full_net,
            "full_amount_with_vat": (
                round(float(full_net) * (1 + vat_pct / 100), 2)
                if full_net is not None else None
            ),
            "vat_trace": vat_trace,
        })
    else:
        summary["vat_trace"] = vat_trace
    summary["input_rows"] = len(work_items)
    summary["bound_rows"] = len(positions)
    covered_rows = sum(1 for item in coverage if item.get("status") == "covered_by")
    open_rows = sum(
        1
        for item in coverage
        if item.get("status") not in {"accepted", "unsafe_source", "covered_by"}
    )
    summary["covered_rows"] = covered_rows
    summary["open_rows"] = open_rows
    # Historical consumers read ``unbound_rows``. Keep the field, but make it
    # mean genuinely open rows rather than counting model-approved coverage as
    # missing work.
    summary["unbound_rows"] = open_rows
    summary["known_amount"] = float(summary.get("total") or 0.0)
    if open_rows:
        summary["full_amount"] = None
        summary["full_amount_without_vat"] = None
        summary["full_amount_with_vat"] = None
    flags = list(summary.get("flags") or [])
    if blockers:
        flags.extend(f"{item['code']}: {item.get('work_id', '')}".strip() for item in blockers)
    summary["flags"] = flags
    if unsafe_source:
        summary["result_status"] = "unsafe_source"
        evidence_status = EvidenceStatus.BLOCKED
        calculation_status = CalculationStatus.UNSAFE_SOURCE
    elif blockers or flags:
        summary["result_status"] = "priced_partial" if positions else "norm_selection_required"
        evidence_status = EvidenceStatus.PARTIAL
        calculation_status = CalculationStatus.PARTIAL if positions else CalculationStatus.NOT_CALCULATED
    else:
        summary["result_status"] = "priced_final"
        evidence_status = EvidenceStatus.SUPPORTED
        calculation_status = CalculationStatus.COMPLETE
    return LSRScenario(
        scenario_id=uuid4().hex,
        title=title,
        work_items=work_items,
        bindings=bindings,
        resource_bindings=list(resource_bindings or []),
        resource_reviews=list(resource_reviews or []),
        coverage_bindings=list(coverage_bindings or []),
        nr_sp_bindings=list(nr_sp_bindings or []),
        price_trace_records=price_trace_records,
        coefficient_traces=coefficient_traces,
        trace=lsr,
        evidence_status=evidence_status,
        calculation_status=calculation_status,
        amount_known=float(summary.get("total_with_vat") or summary.get("total") or 0.0),
        blockers=blockers,
        warnings=flags,
    )


def calculate_scenario_range(
    work_items: list[WorkItem],
    binding_options: dict[str, list[NormBinding]],
    *,
    max_combinations: int = 256,
    **calculation_kwargs: Any,
) -> dict[str, Any]:
    """Calculate min/max over model/user-approved options without choosing semantics in code."""
    ordered_options: list[list[NormBinding]] = []
    for work in work_items:
        options = [item for item in (binding_options.get(work.work_id) or []) if item.work_id == work.work_id]
        if not options:
            return {
                "schema": "lsr_scenario_range_v1",
                "status": "blocked",
                "reason": "every work item needs at least one approved binding option",
                "work_id": work.work_id,
            }
        ordered_options.append(options)
    combination_count = 1
    for options in ordered_options:
        combination_count *= len(options)
    if combination_count > max_combinations:
        return {
            "schema": "lsr_scenario_range_v1",
            "status": "blocked",
            "reason": "combination limit exceeded",
            "combination_count": combination_count,
            "max_combinations": max_combinations,
        }
    scenarios = [
        calculate_scenario(work_items, list(combination), **calculation_kwargs)
        for combination in product(*ordered_options)
    ]
    ranked = sorted(
        scenarios,
        key=lambda scenario: (scenario.amount_known, tuple(binding.norm_code for binding in scenario.bindings)),
    )
    return {
        "schema": "lsr_scenario_range_v1",
        "status": "calculated",
        "combination_count": combination_count,
        "min": ranked[0].as_dict(),
        "max": ranked[-1].as_dict(),
        "scenarios": [scenario.as_dict() for scenario in ranked],
    }
