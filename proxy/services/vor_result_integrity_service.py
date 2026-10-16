"""Read-only structural checks for model-authored VOR rows.

These checks report missing operations, quantities and explicit relationships.
They do not choose works, infer installation from a product name, validate the
professional meaning of an authored explanation, or modify the result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from proxy.services.lsr_source_coverage_service import canonicalize_row_role

if TYPE_CHECKING:
    from proxy.services.attachment_source_catalog_service import AttachmentSourceCatalog


_SUPPLY_ROLES = frozenset({"material", "equipment", "resource"})
_EMPTY_REFERENCES = frozenset({"", "-", "—"})


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
        if role == "work":
            quantity = row.get("quantity")
            if quantity is None or (isinstance(quantity, str) and not quantity.strip()):
                report(
                    "missing_work_quantity", index, row,
                    "Для работы не указан объём; нулевой объём не считается отсутствующим.",
                )
            if not _text(row.get("unit")) or _text(row.get("unit")) in _EMPTY_REFERENCES:
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
