"""Read-only structural checks for model-authored VOR rows.

These checks report missing operations, quantities and explicit relationships.
They do not choose works, infer installation from a product name, validate the
professional meaning of an authored explanation, or modify the result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import TYPE_CHECKING, Any

from proxy.services.lsr_source_coverage_service import canonicalize_row_role

if TYPE_CHECKING:
    from proxy.services.attachment_source_catalog_service import AttachmentSourceCatalog


_SUPPLY_ROLES = frozenset({"material", "equipment", "resource"})
_EMPTY_REFERENCES = frozenset({"", "-", "—"})


def _present(value: Any) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def vor_quantity_number(value: Any) -> int | float | None:
    """Read a finite authored number, never evaluate an expression or formula."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    candidate = value
    if isinstance(value, str):
        candidate = value.strip().replace("\u00a0", "").replace("\u202f", "").replace(" ", "").replace(",", ".")
    try:
        number = float(candidate)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return value if isinstance(value, (int, float)) else number


def vor_derived_quantity_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """Expose authored calculation fields separately from the original quantity.

    A conversion factor is displayed, not used to invent a result or a target
    unit. Invalid values remain in the authored decision and the visible cells.
    """
    fields = {key: row.get(key) for key in (
        "calc_unit", "calc_quantity", "conversion_factor", "conversion_source",
    )}
    return fields if any(_present(value) for value in fields.values()) else {}


def _derived_quantity_issues(row: Mapping[str, Any]) -> list[tuple[str, str]]:
    fields = vor_derived_quantity_fields(row)
    if not fields:
        return []
    issues = []
    if not _present(fields["calc_quantity"]):
        issues.append(("missing_calc_quantity", "Указан перевод объёма, но модель не указала итоговый расчётный объём."))
    elif vor_quantity_number(fields["calc_quantity"]) is None:
        issues.append(("invalid_calc_quantity", "Расчётный объём модели не является конечным числом; значение сохранено без вычисления."))
    if not isinstance(fields["calc_unit"], str) or fields["calc_unit"].strip() in _EMPTY_REFERENCES:
        issues.append(("missing_calc_unit", "Для расчётного объёма модель не указала единицу измерения."))
    if not isinstance(fields["conversion_source"], str) or fields["conversion_source"].strip() in _EMPTY_REFERENCES:
        issues.append(("missing_calc_basis", "Для расчётного объёма модель не указала формулу, исходные параметры и их источник в conversion_source."))
    if _present(fields["conversion_factor"]) and vor_quantity_number(fields["conversion_factor"]) is None:
        issues.append(("invalid_conversion_factor", "Коэффициент перевода модели не является конечным числом; значение сохранено без вычисления."))
    elif _present(fields["conversion_factor"]):
        source_number = vor_quantity_number(row.get("quantity"))
        result_number = vor_quantity_number(fields["calc_quantity"])
        if source_number is None:
            issues.append(("missing_conversion_source_quantity", "Для указанного скалярного коэффициента модель не указала числовое исходное quantity."))
        elif result_number is not None:
            expected = float(source_number) * float(vor_quantity_number(fields["conversion_factor"]))
            if not math.isclose(expected, float(result_number), rel_tol=1e-9, abs_tol=1e-9):
                issues.append(("conversion_result_mismatch", "Расчётный объём не совпадает с исходным quantity × conversion_factor; авторские числа сохранены без исправления."))
    return issues


def vor_has_complete_derived_measure(row: Mapping[str, Any]) -> bool:
    """Structural completeness only; the model still owns the numeric basis."""
    return bool(vor_derived_quantity_fields(row)) and not _derived_quantity_issues(row)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _catalog_locator(
    value: Any, source_catalog: AttachmentSourceCatalog | None,
) -> str:
    raw = _text(value)
    if raw and source_catalog is not None:
        found = source_catalog.lookup(raw)
        if found is not None and _text(found.locator):
            return _text(found.locator)
    return raw


def _source_aliases(
    value: Any, source_catalog: AttachmentSourceCatalog | None,
) -> set[str]:
    aliases = {_text(value), _catalog_locator(value, source_catalog)} - {""}
    return aliases


def _has_relationship_explanation(row: Mapping[str, Any]) -> bool:
    # Explanations remain the model's statements. Their professional validity
    # is not inferred here; a placeholder or Boolean is not an explanation.
    return any(
        isinstance(row.get(key), str)
        and row[key].strip() not in _EMPTY_REFERENCES
        for key in ("open_gap", "coverage")
    )


def audit_vor_result_integrity(
    rows: Sequence[Mapping[str, Any]], *,
    source_catalog: AttachmentSourceCatalog | None = None,
) -> list[dict[str, Any]]:
    """Return structural issues without changing any model-authored value.

    ``row_index`` is the zero-based input position. An optional existing source
    catalog resolves technical aliases only; the function does not open a DB.
    Multiple works at the same source address are allowed: this check requires
    an existing work endpoint and does not select one of those operations.
    """
    indexed = [(index, row) for index, row in enumerate(rows) if isinstance(row, Mapping)]
    roles = {index: canonicalize_row_role(row.get("row_role")) for index, row in indexed}
    source_targets: dict[str, set[int]] = {}
    operation_targets: dict[str, set[int]] = {}
    for index, row in indexed:
        for alias in _source_aliases(row.get("source_row"), source_catalog):
            source_targets.setdefault(alias, set()).add(index)
        operation_id = _text(row.get("operation_id"))
        if operation_id:
            operation_targets.setdefault(operation_id, set()).add(index)

    issues: list[dict[str, Any]] = []

    def report(code: str, index: int, row: Mapping[str, Any], reason: str, **extra: Any) -> None:
        issue: dict[str, Any] = {
            "code": code,
            "source_row": _text(row.get("source_row")),
            "row_index": index,
            "reason": reason,
        }
        if _text(row.get("operation_id")):
            issue["operation_id"] = _text(row.get("operation_id"))
        issue.update(extra)
        issues.append(issue)

    content_rows = [(index, row) for index, row in indexed if roles[index] != "header"]
    if content_rows and not any(roles[index] == "work" for index, _row in content_rows):
        first_index, first_row = content_rows[0]
        report(
            "no_work_operations", first_index, first_row,
            "В результате есть содержательные строки, но нет ни одной строки работы (row_role=work).",
        )

    for index, row in indexed:
        role = roles[index]
        if role != "header":
            for code, reason in _derived_quantity_issues(row):
                report(code, index, row, reason)
            if source_catalog is not None:
                from proxy.services.attachment_source_catalog_service import header_bound_unit

                source = source_catalog.lookup(row.get("source_row"))
                if source is not None:
                    source_quantity = getattr(source, "header_quantity", None)
                    source_unit = header_bound_unit(source)
                    if (getattr(source, "quantity_column_known", False)
                            and vor_quantity_number(source_quantity) is not None
                            and (not _present(row.get("quantity"))
                                 or _text(row.get("quantity")) in _EMPTY_REFERENCES)):
                        report("missing_source_quantity", index, row,
                            "В исходной строке есть количество, но модель не сохранила его в quantity.",
                            source_value=source_quantity)
                    if (source_unit is not None and _text(source_unit) not in _EMPTY_REFERENCES
                            and _text(row.get("unit")) in _EMPTY_REFERENCES):
                        report("missing_source_unit", index, row,
                            "В исходной строке есть единица измерения, но модель не сохранила её в unit.",
                            source_value=source_unit)
        if role == "work":
            quantity = row.get("quantity")
            derived = vor_derived_quantity_fields(row)
            has_derived_quantity = bool(derived) and vor_quantity_number(derived["calc_quantity"]) is not None
            if not _present(quantity) and not has_derived_quantity:
                report(
                    "missing_work_quantity", index, row,
                    "Для работы не указан объём; нулевой объём не считается отсутствующим.",
                )
            has_derived_unit = isinstance(derived.get("calc_unit"), str) and derived["calc_unit"].strip() not in _EMPTY_REFERENCES
            if (not _text(row.get("unit")) or _text(row.get("unit")) in _EMPTY_REFERENCES) and not has_derived_unit:
                report("missing_work_unit", index, row, "Для работы не указана единица измерения.")
            continue
        if role not in _SUPPLY_ROLES:
            continue

        parent = _text(row.get("work_row"))
        if parent in _EMPTY_REFERENCES:
            if not _has_relationship_explanation(row):
                report(
                    "missing_work_relationship", index, row,
                    "Для материала, оборудования или ресурса не указана связь с работой "
                    "и нет пояснения в open_gap или coverage.",
                )
            continue

        targets = set(operation_targets.get(parent, set()))
        source = _catalog_locator(row.get("source_row"), source_catalog)
        if "!" in source and parent.startswith("R") and parent[1:].isdigit():
            parent_source = source.rsplit("!", 1)[0] + "!" + parent
        else:
            parent_source = parent
        for alias in _source_aliases(parent_source, source_catalog):
            targets.update(source_targets.get(alias, set()))
        if not any(roles[target] == "work" for target in targets):
            report(
                "invalid_work_relationship", index, row,
                "Связь work_row не указывает на существующую строку работы (row_role=work) в результате.",
                work_row=parent,
                target_exists=bool(targets),
                target_roles=sorted({roles[target] for target in targets}),
            )
    return issues
