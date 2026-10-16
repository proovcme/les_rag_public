"""Pure, immutable projection of an application-bound literal source catalog.

This module does not choose a packet, interpret source roles, call a reader or
change model/RAG evidence. It exposes an explicit scope and every other exact
reader address. Catalog rendering is not a claim of original-file byte fidelity.
The caller retains the original question, file and durable whole-document scope.
"""
from __future__ import annotations

import base64
from collections import Counter
from dataclasses import dataclass, fields
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

from proxy.services.attachment_source_catalog_service import (
    AttachmentSourceCatalog, CatalogCell, CatalogRow,
    _has_text_header, _header_labels_from_row, catalog_source_order_basis,
)


SOURCE_FRAME_SCHEMA = "les.model_source_frame.v1"
SOURCE_MODEL_RENDER_SCHEMA = "les.model_source_frame_render.v1"
_MANIFEST_COLUMNS = ("source_row", "row_id", "source_start", "source_end", "content_sha256")


class ModelSourceFrameError(ValueError):
    """The supplied catalog/scope cannot be represented faithfully."""


def _source_metadata_fields(value: CatalogRow | CatalogCell):
    # This one optional extension must not change the immutable 907 frames of
    # existing sources. Every other empty/default field remains literal data.
    return tuple(field for field in fields(value) if not (
        isinstance(value, CatalogRow) and field.name == "source_order_basis" and value.source_order_basis == ""
    ))


def _literal(value: Any) -> Any:
    """Snapshot source metadata without lossy repr/coercion of unknown values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"source_value_type": "float", "value": str(value)}
    if isinstance(value, Decimal):
        return {"source_value_type": "decimal", "value": str(value)}
    if isinstance(value, datetime):
        return {"source_value_type": "datetime", "value": value.isoformat(), "fold": value.fold}
    if isinstance(value, (date, time)):
        result = {"source_value_type": type(value).__name__, "value": value.isoformat()}
        if isinstance(value, time):
            result["fold"] = value.fold
        return result
    if isinstance(value, timedelta):
        return {"source_value_type": "timedelta", "days": value.days,
                "seconds": value.seconds, "microseconds": value.microseconds}
    if isinstance(value, bytes):
        return {"source_value_type": "bytes", "base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (CatalogRow, CatalogCell)):
        return {field.name: _literal(getattr(value, field.name)) for field in _source_metadata_fields(value)}
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ModelSourceFrameError("SOURCE_METADATA_NONSTRING_MAPPING_KEY")
        return {key: _literal(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_literal(item) for item in value]
    raise ModelSourceFrameError("SOURCE_METADATA_UNSUPPORTED_LITERAL_TYPE")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _literal_types(value: Any) -> Any:
    """Keep typed values distinct from source dictionaries resembling a tag."""
    if isinstance(value, (CatalogRow, CatalogCell)):
        return {field.name: _literal_types(getattr(value, field.name)) for field in _source_metadata_fields(value)}
    if isinstance(value, Mapping):
        return {"mapping": {key: _literal_types(item) for key, item in value.items()}}
    if isinstance(value, (list, tuple)):
        return {type(value).__name__: [_literal_types(item) for item in value]}
    return type(value).__name__


@dataclass(frozen=True)
class ModelSourceFrame:
    payload_json: str
    catalog_sha256: str
    requested_scope_sha256: str
    source_frame_sha256: str
    requested_locators: tuple[str, ...]
    reference_locators: tuple[str, ...]
    shown_locators: tuple[str, ...]
    available_not_shown_locators: tuple[str, ...]
    manifest_bytes: int
    frame_bytes: int

    def to_payload(self) -> dict[str, Any]:
        """Return a fresh mutable copy; the frozen frame/hash cannot be changed."""
        return json.loads(self.payload_json)


@dataclass(frozen=True)
class ModelSourceRender:
    """Readable model projection bound to the unchanged immutable audit frame."""

    payload_json: str
    source_frame_sha256: str
    model_render_sha256: str
    render_bytes: int
    available_not_shown_locators: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)


def render_model_source_frame(frame: ModelSourceFrame) -> ModelSourceRender:
    """Keep literal rows readable; omit repeated technical audit serialization.

    Exact lines, source values, headers, quantities and section notes are direct
    literals. Extra cell metadata can refer to an identical displayed value.
    The source-text spans used only for extra cells are Python character offsets
    within that row's ``source_text``; they are not original-file byte offsets.
    No source, raw quantity, formula or model/RAG body is clipped or interpreted.
    """
    if not isinstance(frame, ModelSourceFrame):
        raise ModelSourceFrameError("IMMUTABLE_APPLICATION_SOURCE_FRAME_REQUIRED")
    audit = frame.to_payload()
    unsigned = {key: value for key, value in audit.items() if key != "source_frame_sha256"}
    if audit.get("source_frame_sha256") != frame.source_frame_sha256 or _sha(unsigned) != frame.source_frame_sha256:
        raise ModelSourceFrameError("SOURCE_FRAME_AUDIT_HASH_MISMATCH")
    manifest = dict(audit["source_manifest"])
    source_index = manifest["columns"].index("source_row")
    manifest["records"] = [[record[source_index]] for record in manifest["records"]]
    manifest["columns"] = ["source_row"]
    snapshots = {item["source_row"]: item["catalog_row"]
                 for item in audit["offered_rows"] + audit["reference_rows"]}
    cells = [cell for locator in frame.shown_locators for cell in snapshots[locator]["cells"]]
    extra_cell_fields = ("formula", "cached_formula_value", "number_format", "merged_range", "hidden_column")
    constants = {key: cells[0][key] for key in extra_cell_fields
                 if cells and all(_json(cell[key]) == _json(cells[0][key]) for cell in cells)}
    cell_columns = ["coordinate", "column", "display_value", "raw_value"] + [
        key for key in extra_cell_fields if key not in constants]
    rows: list[dict[str, Any]] = []
    for locator in frame.shown_locators:
        original = snapshots[locator]
        text = original["line"]
        # These fields are literal catalog source/context, not inferred roles.
        row = {key: original[key] for key in (
            "values", "column_headers", "section_context", "ambiguities", "header_quantity",
            "quantity_column_known", "hidden_row", "hidden_sheet", "source_start", "source_end")}
        row.update(source_row=locator, source_text=text)
        encoded_cells: list[list[Any]] = []
        for cell in original["cells"]:
            encoded = dict(cell)
            display = cell["display_value"]
            matches = [index for index, value in enumerate(original["values"]) if value == display]
            if matches:
                encoded["display_value"] = {"source_value_index": matches[0]}
            else:
                prefix = len(locator) + 2 if text.startswith(locator + ": ") else 0
                start = text.find(display, prefix) if display else -1
                encoded["display_value"] = ({"source_text_span": [start, start + len(display)]}
                    if start >= 0 else {"literal": display})
            encoded["raw_value"] = ({"same_as_display": True}
                if _json(cell["raw_value"]) == _json(display) else {"literal": cell["raw_value"]})
            if cell["formula"] and _json(cell["formula"]) == _json(cell["raw_value"]):
                encoded["formula"] = {"same_as_raw": True}
            encoded_cells.append([encoded[key] for key in cell_columns])
        row["cells"] = encoded_cells
        rows.append(row)
    payload = {
        "schema": SOURCE_MODEL_RENDER_SCHEMA, "source_frame_sha256": frame.source_frame_sha256,
        "requested_scope_sha256": frame.requested_scope_sha256, "source_manifest": manifest,
        "requested_source_rows": list(frame.requested_locators),
        "reference_source_rows": list(frame.reference_locators), "shown_rows": rows,
        "available_not_shown_selector": "source_manifest.records minus requested_source_rows and reference_source_rows",
        "available_content_status": audit["available_content_status"],
        "source_body_representation": audit["source_body_representation"],
        "source_scope_instruction": audit["source_scope_instruction"],
        "cell_columns": cell_columns, "cell_constant_fields": constants,
        "cell_value_contract": (
            "Главный исходник читается прямо в source_text и values; column_headers и section_context сохранены. "
            "Дополнительные cells используют cell_columns и общие cell_constant_fields. source_value_index "
            "ссылается на дословный values этой строки. same_as_display/same_as_raw означает точное равенство. "
            "literal содержит исходное значение без изменения. source_text_span=[start,end] — только "
            "индексы символов [start:end] внутри этой же source_text, не координаты исходного файла."
        ),
    }
    render_sha = _sha(payload)
    payload["model_render_sha256"] = render_sha
    payload_json = _json(payload)
    return ModelSourceRender(payload_json=payload_json, source_frame_sha256=frame.source_frame_sha256,
        model_render_sha256=render_sha, render_bytes=len(payload_json.encode("utf-8")),
        available_not_shown_locators=frame.available_not_shown_locators)


def _validate_catalog(catalog: AttachmentSourceCatalog) -> None:
    if not isinstance(catalog, AttachmentSourceCatalog):
        raise ModelSourceFrameError("APPLICATION_ATTACHMENT_CATALOG_REQUIRED")
    if (not isinstance(catalog.source_file_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", catalog.source_file_sha256)
            or not isinstance(catalog.source_file_id, str) or not catalog.source_file_id.strip()):
        raise ModelSourceFrameError("APPLICATION_SOURCE_IDENTITY_REQUIRED")
    names = [name for name, _count in catalog.sheets]
    if len(names) != len(set(names)):
        raise ModelSourceFrameError("DUPLICATE_SOURCE_SHEET")
    locators: set[str] = set()
    for row in catalog.rows:
        if (not isinstance(row, CatalogRow) or not isinstance(row.locator, str)
                or not row.locator or row.locator != row.locator.strip()
                or row.locator in locators or not isinstance(row.line, str)):
            raise ModelSourceFrameError("INVALID_OR_DUPLICATE_SOURCE_ROW")
        locators.add(row.locator)
        if ((row.source_start is None) != (row.source_end is None)
                or (row.source_start is not None and (
                    type(row.source_start) is not int or type(row.source_end) is not int
                    or row.source_start < 0 or row.source_end < row.source_start))):
            raise ModelSourceFrameError("INVALID_SOURCE_OFFSETS")
    counts = Counter(row.sheet for row in catalog.rows)
    if (set(counts) - set(names) or any(
            not isinstance(name, str) or not name or type(count) is not int
            or count < 0 or counts[name] != count for name, count in catalog.sheets)):
        raise ModelSourceFrameError("SOURCE_SHEET_COUNT_MISMATCH")


def _reference_locators(rows: Sequence[CatalogRow], requested: set[str]) -> set[str]:
    """Reuse the catalog's source header binding; never classify source content."""
    headers: dict[str, str] = {}
    sections: dict[str, str] = {}
    references: set[str] = set()
    offered_sheets = {row.sheet for row in rows if row.locator in requested}
    work_sheets = {row.sheet for row in rows if row.is_work_row()}
    for row in rows:
        # Match catalog_sheet_pack_lines: all same-sheet empty-quantity
        # descriptors are literal reference context, not a chosen association.
        if ((row.sheet in offered_sheets and row.quantity_column_known and row.header_quantity is None)
                or row.classification_reason == "xlsx_literal_metadata"
                and (row.sheet in offered_sheets or row.sheet not in work_sheets)):
            references.add(row.locator)
        if row.locator in requested:
            references.update(pointer for pointer in (
                headers.get(row.sheet), sections.get(row.sheet)) if pointer)
        if row.row_classification == "header" and _has_text_header(_header_labels_from_row(row)):
            headers[row.sheet] = row.locator
        if row.row_classification == "section":
            sections[row.sheet] = row.locator
    return references - requested


def build_model_source_frame(
    catalog: AttachmentSourceCatalog, offered_locators: Sequence[str],
) -> ModelSourceFrame:
    """Freeze exact offered rows and access to every other source locator.

    The explicit offered set is ordered by source order, not its caller's branch.
    There is no row cap, source-body clipping, role/norm selection or environment
    setting here. Body hashes refer to exact UTF-8 ``CatalogRow.line`` values.
    """
    _validate_catalog(catalog)
    if not isinstance(offered_locators, Sequence) or isinstance(offered_locators, (str, bytes)):
        raise ModelSourceFrameError("EXPLICIT_SOURCE_LOCATOR_SEQUENCE_REQUIRED")
    by_locator = {row.locator: row for row in catalog.rows}
    requested_set: set[str] = set()
    for locator in offered_locators:
        if not isinstance(locator, str) or locator not in by_locator or locator in requested_set:
            raise ModelSourceFrameError("NONLITERAL_ABSENT_OR_DUPLICATE_OFFERED_LOCATOR")
        requested_set.add(locator)
    offset_order = bool(catalog.rows) and all(row.source_start is not None for row in catalog.rows)
    rows = tuple(sorted(catalog.rows, key=lambda row: row.source_start)) if offset_order else catalog.rows
    order_basis = catalog_source_order_basis(rows) if offset_order else "application_catalog_order"
    requested = tuple(row.locator for row in rows if row.locator in requested_set)
    references_set = _reference_locators(rows, requested_set)
    references = tuple(row.locator for row in rows if row.locator in references_set)
    shown_set = requested_set | references_set
    shown = tuple(row.locator for row in rows if row.locator in shown_set)
    not_shown = tuple(row.locator for row in rows if row.locator not in shown_set)
    snapshots = {row.locator: _literal(row) for row in rows}
    identity = {
        "original_name": catalog.original_name, "source_file_id": catalog.source_file_id,
        "source_file_sha256": catalog.source_file_sha256, "catalog_schema": catalog.schema,
        "sheets": _literal(catalog.sheets), "extraction_complete": catalog.extraction_complete,
        "extraction_warnings": _literal(catalog.extraction_warnings),
    }
    metadata_types = {row.locator: _literal_types(row) for row in rows}
    catalog_sha = _sha({**identity, "rows": [snapshots[row.locator] for row in rows],
                       "source_literal_types": [metadata_types[row.locator] for row in rows]})
    scope_sha = _sha({"schema": SOURCE_FRAME_SCHEMA, "catalog_sha256": catalog_sha,
                      "requested_source_rows": requested})
    manifest = {
        **identity, "catalog_sha256": catalog_sha, "columns": _MANIFEST_COLUMNS,
        "records": [[row.locator, row.row_id, row.source_start, row.source_end,
                     hashlib.sha256(row.line.encode("utf-8")).hexdigest()] for row in rows],
        "read_source": {"tool": "read_source", "argument": "source_row",
                        "selector": "exact manifest source_row only", "body": "complete catalog row.line"},
    }
    type_registry: list[dict[str, Any]] = []
    type_indices: dict[str, int] = {}
    type_index_by_locator: dict[str, int] = {}
    for locator in shown:
        type_json = _json(metadata_types[locator])
        if type_json not in type_indices:
            type_indices[type_json] = len(type_registry)
            type_registry.append(metadata_types[locator])
        type_index_by_locator[locator] = type_indices[type_json]
    payload = {
        "schema": SOURCE_FRAME_SCHEMA, "source_manifest": manifest,
        "source_order_basis": order_basis, "requested_scope_sha256": scope_sha,
        "source_body_representation": "catalog rows; not a byte-identical original-file rendering",
        "requested_source_rows": requested, "reference_source_rows": references,
        # Share only byte-identical serialized technical type metadata within
        # this frame. Every literal source field/body stays in its row record.
        "source_literal_type_registry": type_registry,
        "offered_rows": [{"source_row": locator, "catalog_row": snapshots[locator],
                          "source_literal_types_index": type_index_by_locator[locator]} for locator in requested],
        "reference_rows": [{"source_row": locator, "catalog_row": snapshots[locator],
                            "source_literal_types_index": type_index_by_locator[locator]} for locator in references],
        "available_not_shown_locators": not_shown,
        "source_scope_instruction": (
            "requested_source_rows задаёт только текущую область исходника. reference_source_rows — "
            "дословный исходный контекст; их показ не является решением или обработкой этих строк. "
            "Полный манифест сохраняет адреса всех строк; остальные "
            "доступны через read_source(source_row=<точный адрес>) без смешения селекторов. "
            "not_in_current_frame не означает отсутствие данных или уже выполненное чтение. "
            "Этот пакет не доказывает завершённость всего документа. Код не выбирал нормы, "
            "операции или профессиональные роли и не изменял источник."
        ),
        "available_content_status": "not_in_current_frame",
    }
    frame_sha = _sha(payload)
    payload["source_frame_sha256"] = frame_sha
    payload_json = _json(payload)
    return ModelSourceFrame(payload_json=payload_json, catalog_sha256=catalog_sha,
        requested_scope_sha256=scope_sha, source_frame_sha256=frame_sha,
        requested_locators=requested, reference_locators=references, shown_locators=shown,
        available_not_shown_locators=not_shown, manifest_bytes=len(_json(manifest).encode("utf-8")),
        frame_bytes=len(payload_json.encode("utf-8")))
