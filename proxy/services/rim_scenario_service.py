"""Validate model/user-authored compatible RIM scenarios.

The service never combines professional alternatives on its own.  It reports
the theoretical option count, validates explicit scenarios and enforces the
configured calculation limit.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import uuid4


def theoretical_combination_count(
    work_rows: list[dict[str, Any]],
    mapping_rows: list[dict[str, Any]],
) -> int:
    """Return the candidate-space size without materialising a Cartesian product."""
    covered = {
        str(item.get("work_id") or "")
        for item in mapping_rows
        if str(item.get("selection_kind") or "") == "covered_by"
        or str(item.get("covered_by_work_id") or "")
    }
    counts: Counter[str] = Counter()
    for item in mapping_rows:
        status = str(item.get("selection_status") or "")
        if status not in {"accepted", "selected"}:
            continue
        work_id = str(item.get("work_id") or "")
        if work_id and work_id not in covered:
            counts[work_id] += 1
    total = 1
    for work in work_rows:
        work_id = str(work.get("work_id") or "")
        if work_id in covered:
            continue
        count = counts.get(work_id, 0)
        if count == 0:
            return 0
        total *= count
    return total


def validate_authored_scenarios(
    work_rows: list[dict[str, Any]],
    mapping_rows: list[dict[str, Any]],
    scenarios: list[dict[str, Any]],
    *,
    max_combinations: int = 1000,
) -> dict[str, Any]:
    if max_combinations < 1 or max_combinations > 100_000:
        raise ValueError("max_combinations must be between 1 and 100000")
    eligible = {
        str(item.get("mapping_row_id") or ""): item
        for item in mapping_rows
        if str(item.get("selection_status") or "") in {"accepted", "selected"}
        and str(item.get("mapping_row_id") or "")
    }
    all_work_ids = {str(item.get("work_id") or "") for item in work_rows if str(item.get("work_id") or "")}
    covered = {
        str(item.get("work_id") or "")
        for item in mapping_rows
        if str(item.get("selection_kind") or "") == "covered_by"
        or str(item.get("covered_by_work_id") or "")
    }
    required_work_ids = all_work_ids - covered
    theoretical = theoretical_combination_count(work_rows, mapping_rows)
    issues: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    seen_scenarios: set[str] = set()
    for index, scenario in enumerate(scenarios, 1):
        scenario_id = str(scenario.get("scenario_id") or uuid4().hex)
        if scenario_id in seen_scenarios:
            issues.append(
                {
                    "code": "scenario_id_duplicate",
                    "severity": "blocking",
                    "scenario_id": scenario_id,
                }
            )
        seen_scenarios.add(scenario_id)
        authored_by = str(scenario.get("authored_by") or "")
        compatibility_reason = str(scenario.get("compatibility_reason") or "").strip()
        if authored_by not in {"model", "user"}:
            issues.append(
                {
                    "code": "scenario_author_invalid",
                    "severity": "blocking",
                    "scenario_id": scenario_id,
                }
            )
        if not compatibility_reason:
            issues.append(
                {
                    "code": "scenario_compatibility_reason_missing",
                    "severity": "blocking",
                    "scenario_id": scenario_id,
                }
            )
        selections = list(scenario.get("selections") or [])
        selected_by_work: dict[str, str] = {}
        for selection in selections:
            mapping_row_id = str(selection.get("mapping_row_id") or "")
            mapping = eligible.get(mapping_row_id)
            if mapping is None:
                issues.append(
                    {
                        "code": "scenario_mapping_not_approved",
                        "severity": "blocking",
                        "scenario_id": scenario_id,
                        "mapping_row_id": mapping_row_id,
                    }
                )
                continue
            work_id = str(mapping.get("work_id") or "")
            if work_id in selected_by_work:
                issues.append(
                    {
                        "code": "scenario_multiple_norms_for_work",
                        "severity": "blocking",
                        "scenario_id": scenario_id,
                        "work_id": work_id,
                    }
                )
            selected_by_work[work_id] = mapping_row_id
        missing = sorted(required_work_ids - set(selected_by_work))
        unknown = sorted(set(selected_by_work) - required_work_ids)
        if missing:
            issues.append(
                {
                    "code": "scenario_work_coverage_missing",
                    "severity": "blocking",
                    "scenario_id": scenario_id,
                    "work_ids": missing,
                }
            )
        if unknown:
            issues.append(
                {
                    "code": "scenario_work_selection_unexpected",
                    "severity": "blocking",
                    "scenario_id": scenario_id,
                    "work_ids": unknown,
                }
            )
        normalized.append(
            {
                "schema": "rim_scenario_v1",
                "scenario_id": scenario_id,
                "title": str(scenario.get("title") or f"Сценарий {index}"),
                "authored_by": authored_by,
                "compatibility_reason": compatibility_reason,
                "selections": [
                    {"work_id": work_id, "mapping_row_id": mapping_row_id}
                    for work_id, mapping_row_id in sorted(selected_by_work.items())
                ],
            }
        )
    if len(normalized) > max_combinations:
        issues.append(
            {
                "code": "scenario_limit_exceeded",
                "severity": "blocking",
                "scenario_count": len(normalized),
                "max_combinations": max_combinations,
            }
        )
    if theoretical > max_combinations and not normalized:
        issues.append(
            {
                "code": "theoretical_combination_limit_exceeded",
                "severity": "blocking",
                "theoretical_count": theoretical,
                "max_combinations": max_combinations,
                "required_action": "author_explicit_compatible_scenarios",
            }
        )
    return {
        "schema": "rim_scenario_set_v1",
        "theoretical_count": theoretical,
        "max_combinations": max_combinations,
        "scenario_count": len(normalized),
        "scenarios": normalized,
        "issues": issues,
    }


def calculation_rows_for_scenario(
    work_rows: list[dict[str, Any]],
    mapping_rows: list[dict[str, Any]],
    scenario: dict[str, Any],
) -> list[dict[str, Any]]:
    """Join one authored scenario into canonical visible rows for the calculator."""
    mappings = {
        str(item.get("mapping_row_id") or ""): item
        for item in mapping_rows
        if str(item.get("mapping_row_id") or "")
    }
    selected = {
        str(item.get("work_id") or ""): mappings.get(str(item.get("mapping_row_id") or ""))
        for item in (scenario.get("selections") or [])
    }
    rows: list[dict[str, Any]] = []
    for work in work_rows:
        work_id = str(work.get("work_id") or "")
        mapping = selected.get(work_id)
        if mapping is None:
            coverage = next(
                (
                    item
                    for item in mapping_rows
                    if str(item.get("work_id") or "") == work_id
                    and (
                        str(item.get("selection_kind") or "") == "covered_by"
                        or str(item.get("covered_by_work_id") or "")
                    )
                ),
                None,
            )
            if coverage is None:
                raise ValueError(f"scenario has no mapping or coverage for {work_id}")
            rows.append(
                {
                    "work_id": work_id,
                    "title": work.get("work_name") or work.get("title"),
                    "quantity": work.get("quantity"),
                    "unit": work.get("unit"),
                    "section": work.get("section_name") or work.get("section"),
                    "source_ref": work.get("source_ref"),
                    "covered_by_work_id": coverage.get("covered_by_work_id"),
                    "coverage_reason": coverage.get("reason"),
                    "coverage_selected_by": coverage.get("edited_by") or "model",
                    "source_refs": coverage.get("source_refs") or work.get("source_refs") or [],
                }
            )
            continue
        norm_key = str(mapping.get("norm_key") or "")
        norm_code = norm_key.replace(":", "", 1)
        rows.append(
            {
                "work_id": work_id,
                "title": work.get("work_name") or work.get("title"),
                "quantity": work.get("quantity"),
                "unit": work.get("unit"),
                "section": work.get("section_name") or work.get("section"),
                "source_row": work.get("source_row"),
                "source_ref": work.get("source_ref"),
                "source_refs": mapping.get("source_refs") or work.get("source_refs") or [],
                "norm_code": norm_code,
                "selection_kind": mapping.get("selection_kind"),
                "is_analog": bool(mapping.get("is_analog")),
                "applicability": mapping.get("applicability") or "",
                "norm_reason": mapping.get("reason") or "",
                "analog_limitations": mapping.get("analog_limitations") or [],
                "technology_check": mapping.get("technology_check") or {},
                "resource_bindings": mapping.get("resource_bindings") or [],
                "resource_review_status": mapping.get("resource_review_status") or "keep_all_confirmed",
                "resource_review_reason": mapping.get("resource_review_reason")
                or "Модель выбрала открытую карточку без ресурсных изменений",
                "nr_sp_rule_id": mapping.get("nr_sp_rule_id") or "",
                "nr_sp_reason": mapping.get("nr_sp_reason") or "",
            }
        )
    return rows


def requirements_from_calculation(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert deterministic calculator gaps into typed session requirements."""
    raw: list[dict[str, Any]] = []
    raw.extend(item for item in (trace.get("blockers") or []) if isinstance(item, dict))
    summary = trace.get("summary") if isinstance(trace.get("summary"), dict) else {}
    raw.extend(
        item for item in (summary.get("price_requirements") or []) if isinstance(item, dict)
    )
    # The canonical RIM trace records price gaps on exact resource rows.  Read
    # those typed fields instead of treating a zero cost as a price.
    for section in trace.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for position in section.get("positions") or []:
            if not isinstance(position, dict):
                continue
            work_id = str(position.get("work_id") or "")
            source_refs = list(position.get("source_refs") or [])
            for row in position.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
                price_action = str(meta.get("price_action") or "")
                if not price_action:
                    continue
                columns = row.get("columns") if isinstance(row.get("columns"), dict) else {}
                resource_code = str(columns.get(2) or columns.get("2") or "")
                raw.append(
                    {
                        "action": price_action,
                        "work_id": work_id,
                        "resource_code": resource_code,
                        "description": (
                            f"Нет подтверждённой цены ресурса "
                            f"{row.get('label') or resource_code or 'без кода'}"
                        ),
                        "required_fields": (
                            ["supplier_offer_refs", "price_date", "vat_status"]
                            if price_action == "needs_kac"
                            else ["price_source_ref", "price_period"]
                        ),
                        "source_refs": source_refs,
                    }
                )
            position_summary = (
                position.get("summary")
                if isinstance(position.get("summary"), dict)
                else {}
            )
            for flag in position_summary.get("flags") or []:
                text = str(flag or "").strip()
                folded = text.casefold()
                if not text or any(
                    marker in folded
                    for marker in (
                        "нужен кац",
                        "нужна ставка",
                        "нужна цена эксплуатации",
                    )
                ):
                    continue
                if "нр/сп" in folded:
                    code = "nr_sp_binding_required"
                elif "коэффициент" in folded:
                    code = "coefficient_confirmation_required"
                else:
                    code = "norm_confirmation_required"
                raw.append(
                    {
                        "code": code,
                        "work_id": work_id,
                        "description": text,
                        "source_refs": source_refs,
                    }
                )
    requirements: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw:
        code = str(item.get("code") or item.get("action") or item.get("price_action") or "")
        folded = code.casefold()
        if "needs_kac" in folded or "kac" in folded:
            kind = "kac"
        elif "price" in folded or "rate" in folded:
            kind = "kac"
        elif "coefficient" in folded:
            kind = "coefficient"
        elif "machine" in folded or "machinist" in folded or "operator" in folded:
            kind = "machine_operator_map"
        elif "unit" in folded or "measure" in folded:
            kind = "unit_conversion"
        else:
            kind = "norm_confirmation"
        work_id = str(item.get("work_id") or "")
        resource_code = str(item.get("resource_code") or item.get("code_resource") or "")
        key = (kind, work_id, resource_code or code)
        if key in seen:
            continue
        seen.add(key)
        requirements.append(
            {
                "requirement_id": uuid4().hex,
                "kind": kind,
                "severity": "blocking",
                "finality_policy": "blocks_final",
                "work_id": work_id,
                "resource_code": resource_code,
                "description": str(item.get("description") or item.get("reason") or code or "Требуется уточнение"),
                "required_fields": list(item.get("required_fields") or []),
                "status": "open",
                "source_refs": list(item.get("source_refs") or []),
            }
        )
    return requirements
