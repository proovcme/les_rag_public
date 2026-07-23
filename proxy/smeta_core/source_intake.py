"""Document-to-WorkItem intake for bills of quantities.

The parser only preserves visible source facts. It does not infer work types,
norms, analogs, coefficients or prices. Ambiguous rows stay visible as issues.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from proxy.smeta_core.contracts import WorkItem


_HEADER_ALIASES = {
    "number": ("№", "пп", "номер"),
    "title": ("наименование", "работа", "описание"),
    "unit": ("ед. изм", "единица", "ед изм", "ед."),
    "quantity": ("кол-во", "количество", "объем", "объём"),
    "note": ("примечание", "комментарий"),
}
_SECTION_RE = re.compile(r"^\s*(?:раздел|section)\s*(?:№\s*)?(\d+)?[.\s:-]*(.*)$", re.IGNORECASE)


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _number(value: Any) -> float | None:
    text = _text(value).replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _source_id(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return f"sha256:{digest}"


def _header_map(row: Iterable[Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, raw in enumerate(row):
        value = _text(raw).casefold()
        for field, aliases in _HEADER_ALIASES.items():
            if field not in result and any(alias.casefold() in value for alias in aliases):
                result[field] = index
    return result


def _cell(row: list[Any], index: int | None) -> str:
    return _text(row[index]) if index is not None and index < len(row) else ""


def _rows_to_items(
    rows: list[list[Any]],
    *,
    source_path: Path,
    source_locator: str,
    table_index: int,
    work_id_start: int = 0,
) -> tuple[list[WorkItem], list[dict[str, Any]]]:
    items: list[WorkItem] = []
    issues: list[dict[str, Any]] = []
    if not rows:
        return items, issues
    header_at = -1
    columns: dict[str, int] = {}
    for index, row in enumerate(rows[:12]):
        candidate = _header_map(row)
        if {"title", "unit", "quantity"}.issubset(candidate):
            header_at, columns = index, candidate
            break
    if header_at < 0:
        return items, [{"code": "vor_header_not_found", "source": source_locator, "table": table_index}]

    current_section = "Без раздела"
    source_hash = _source_id(source_path)
    for raw_index, row in enumerate(rows[header_at + 1 :], header_at + 2):
        values = [_text(value) for value in row]
        nonempty = [value for value in values if value]
        if not nonempty:
            continue
        joined = " ".join(nonempty)
        # Many printed forms repeat Excel-like column numbers under the header.
        # This is layout metadata, not a work row.
        if nonempty and all(re.fullmatch(r"\d+(?:[.,]\d+)?", value) for value in nonempty):
            continue
        title = _cell(row, columns.get("title"))
        unit = _cell(row, columns.get("unit"))
        quantity_raw = _cell(row, columns.get("quantity"))
        quantity = _number(quantity_raw)
        visible_number = _cell(row, columns.get("number"))
        note = _cell(row, columns.get("note"))
        if not title and not unit and quantity is None:
            continue

        # Printed/exported workbooks commonly keep section totals as numeric
        # zeroes in price columns.  A row with a visible title but without a
        # unit or quantity is a section only when every other source cell is
        # empty or zero; no work operation is inferred or discarded here.
        title_index = columns.get("title")
        number_index = columns.get("number")
        other_values = [
            value for index, value in enumerate(values)
            if index not in {title_index, number_index} and value
        ]
        if title and not unit and quantity is None and all(_number(value) == 0 for value in other_values):
            current_section = title
            continue

        work_id = f"vor-{work_id_start + len(items) + 1:04d}"
        source_ref = f"{source_path}#{source_locator};table={table_index};row={raw_index}"
        assumptions: tuple[str, ...] = ()
        if not title or not unit or quantity is None:
            missing = [name for name, present in (("title", title), ("unit", unit), ("quantity", quantity is not None)) if not present]
            issues.append({
                "code": "vor_row_incomplete",
                "work_id": work_id,
                "source_ref": source_ref,
                "missing": missing,
                "visible_values": values,
            })
            assumptions = tuple(f"missing_source_field:{field}" for field in missing)
        items.append(
            WorkItem(
                work_id=work_id,
                title=title or "MISSING: наименование работы",
                quantity=quantity,
                unit=unit,
                section=current_section,
                source_row=raw_index,
                note=note,
                source_refs=(source_ref, source_hash),
                assumptions=assumptions + ((f"visible_row_number:{visible_number}",) if visible_number else ()),
            )
        )
    return items, issues


def intake_vor_pdf(path: str | Path) -> dict[str, Any]:
    """Extract all detectable VOR tables from a PDF without semantic guessing."""
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise ValueError(f"PDF source not found: {source}")
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - environment capability
        raise RuntimeError("pdfplumber is required for PDF VOR intake") from exc

    items: list[WorkItem] = []
    issues: list[dict[str, Any]] = []
    table_count = 0
    with pdfplumber.open(source) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            for page_table_index, table in enumerate(page.extract_tables() or [], 1):
                table_count += 1
                extracted, table_issues = _rows_to_items(
                    table,
                    source_path=source,
                    source_locator=f"page={page_number}",
                    table_index=page_table_index,
                    work_id_start=len(items),
                )
                items.extend(extracted)
                issues.extend(table_issues)
    return {
        "schema": "smeta_vor_intake_v1",
        "source_path": str(source),
        "source_sha256": _source_id(source).split(":", 1)[1],
        "table_count": table_count,
        "work_item_count": len(items),
        "section_count": len({item.section for item in items}),
        "work_items": [asdict(item) for item in items],
        "issues": issues,
        "semantic_selection_performed": False,
    }


def intake_vor_xlsx(path: str | Path) -> dict[str, Any]:
    """Extract visible work rows from every worksheet without semantic guessing."""
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError(f"XLSX source not found: {source}")
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - environment capability
        raise RuntimeError("openpyxl is required for XLSX VOR intake") from exc

    items: list[WorkItem] = []
    issues: list[dict[str, Any]] = []
    sheet_count = 0
    workbook = openpyxl.load_workbook(source, data_only=True, read_only=True)
    try:
        for worksheet in workbook.worksheets:
            rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
            if not any(any(value not in (None, "") for value in row) for row in rows):
                continue
            sheet_count += 1
            extracted, sheet_issues = _rows_to_items(
                rows,
                source_path=source,
                source_locator=f"sheet={worksheet.title}",
                table_index=1,
                work_id_start=len(items),
            )
            items.extend(extracted)
            issues.extend(sheet_issues)
    finally:
        workbook.close()
    return {
        "schema": "smeta_vor_intake_v1",
        "source_kind": "xlsx",
        "source_path": str(source),
        "source_sha256": _source_id(source).split(":", 1)[1],
        "table_count": sheet_count,
        "work_item_count": len(items),
        "section_count": len({item.section for item in items}),
        "work_items": [asdict(item) for item in items],
        "issues": issues,
        "semantic_selection_performed": False,
    }


def intake_vor_document(path: str | Path) -> dict[str, Any]:
    """Dispatch a supported source document to its lossless intake parser."""
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return intake_vor_pdf(path)
    if suffix in {".xlsx", ".xlsm"}:
        return intake_vor_xlsx(path)
    raise ValueError(f"Unsupported VOR document format: {suffix or 'none'}")
