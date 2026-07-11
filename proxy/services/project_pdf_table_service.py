"""Shared PDF table readers for project source-maps.

This layer extracts normalized table rows that are useful across PD/RD
disciplines. It does not answer questions and does not infer engineering
conclusions; it only emits source-referenced facts for RAG navigation.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from proxy.services.pd_rd_manifest_service import repair_pd_rd_text

_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‑": "-"})
_MAX_TABLE_DETECTION_DRAWINGS = 3000
PROJECT_PDF_TABLE_ALGO_VERSION = "0.24.0.375"


def extract_project_pdf_table_manifest(
    pdf_path: str | Path,
    *,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """Extract shared project table layers from a PDF."""
    path = Path(pdf_path)
    manifest: dict[str, Any] = {
        "schema": "project_pdf_table_manifest_v1",
        "algo_version": PROJECT_PDF_TABLE_ALGO_VERSION,
        "source_path": path.as_posix(),
        "file_name": path.name,
        "pages": [],
        "summary": {
            "detected_tables": 0,
            "hvs_rows": 0,
            "water_balance_rows": 0,
            "room_explication_rows": 0,
            "semantic_table_types": {},
        },
        "warnings": [],
    }
    if not path.exists() or path.suffix.lower() != ".pdf":
        manifest["warnings"].append("not_pdf_or_missing")
        return manifest
    try:
        import fitz
    except Exception:
        manifest["warnings"].append("fitz_unavailable")
        return manifest
    manifest["detector_version"] = f"pymupdf:{getattr(fitz, 'VersionBind', 'unknown')}"
    try:
        with fitz.open(str(path)) as doc:
            total = int(getattr(doc, "page_count", 0) or 0)
            limit = total if max_pages is None else min(total, max(0, int(max_pages)))
            manifest["page_count"] = total
            manifest["pages_read"] = limit
            source_ref_base = path.as_posix()
            for page_index in range(limit):
                page_payload = _extract_page(source_ref_base, doc[page_index], page_index + 1)
                manifest["pages"].append(page_payload)
                summary = manifest["summary"]
                summary["detected_tables"] += page_payload["detected_tables_total"]
                summary["hvs_rows"] += page_payload["hvs_rows_total"]
                summary["water_balance_rows"] += page_payload["water_balance_rows_total"]
                summary["room_explication_rows"] += page_payload["room_explication_rows_total"]
                _merge_counts(summary["semantic_table_types"], page_payload.get("semantic_table_types") or {})
                for warning in page_payload.get("warnings") or []:
                    if warning != "project_tables_not_detected":
                        manifest["warnings"].append(f"{path.name}#page={page_index + 1}:{warning}")
    except Exception as err:  # noqa: BLE001
        manifest["warnings"].append(f"pdf_read_failed: {type(err).__name__}: {err}")
    return manifest


def summarize_project_table_manifests(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a compact dataset-level summary over project table manifests."""
    summary = {
        "detected_tables": 0,
        "hvs_rows": 0,
        "water_balance_rows": 0,
        "room_explication_rows": 0,
        "files_with_hvs": 0,
        "files_with_water_balance": 0,
        "files_with_room_explications": 0,
        "semantic_table_types": {},
    }
    source_navigation: list[dict[str, Any]] = []
    for manifest in manifests:
        if not isinstance(manifest, dict):
            continue
        file_name = str(manifest.get("file_name") or "")
        ms = manifest.get("summary") if isinstance(manifest.get("summary"), dict) else {}
        hvs = int(ms.get("hvs_rows") or 0)
        water = int(ms.get("water_balance_rows") or 0)
        rooms = int(ms.get("room_explication_rows") or 0)
        detected = int(ms.get("detected_tables") or 0)
        summary["detected_tables"] += detected
        summary["hvs_rows"] += hvs
        summary["water_balance_rows"] += water
        summary["room_explication_rows"] += rooms
        _merge_counts(summary["semantic_table_types"], ms.get("semantic_table_types") or {})
        if hvs:
            summary["files_with_hvs"] += 1
            source_navigation.append(_nav(file_name, "таблица ХВС", "ОВ", "характеристики воздушных систем", hvs, manifest))
        if water:
            summary["files_with_water_balance"] += 1
            source_navigation.append(_nav(file_name, "водный баланс", "ВК", "водопотребление/водоотведение и балансы", water, manifest))
        if rooms:
            summary["files_with_room_explications"] += 1
            source_navigation.append(_nav(file_name, "экспликация помещений", "", "номера, имена, площади и категории помещений", rooms, manifest))
        for table_nav in _semantic_nav(file_name, manifest):
            source_navigation.append(table_nav)
    return {
        "schema": "project_pdf_table_summary_v1",
        "summary": summary,
        "source_navigation": source_navigation[:80],
    }


def normalize_hvs_table(matrix: list[list[Any]], *, source_ref: str = "") -> dict[str, Any] | None:
    rows, header_idx, headers, mapping = _prepare_table(matrix, _hvs_field)
    hvs_value_fields = {"airflow_m3h", "pressure_pa", "temperature_c", "heat_load_kw", "cold_load_kw", "equipment"}
    if rows is None or header_idx is None or "system_id" not in mapping or not (hvs_value_fields & set(mapping)):
        return None
    normalized: list[dict[str, Any]] = []
    for row_no, raw in enumerate(rows[header_idx + 1 :], header_idx + 2):
        padded = raw + [""] * max(0, len(headers) - len(raw))
        if _is_column_number_row(padded):
            continue
        item = {
            "schema": "hvs_air_system_row_v1",
            "source_ref": _row_ref(source_ref, row_no),
            "system_id": _at(padded, mapping, "system_id"),
            "served_zone": _at(padded, mapping, "served_zone"),
            "airflow_m3h": _num(_at(padded, mapping, "airflow_m3h")),
            "pressure_pa": _num(_at(padded, mapping, "pressure_pa")),
            "temperature_c": _num(_at(padded, mapping, "temperature_c")),
            "heat_load_kw": _num(_at(padded, mapping, "heat_load_kw")),
            "cold_load_kw": _num(_at(padded, mapping, "cold_load_kw")),
            "equipment": _at(padded, mapping, "equipment"),
            "note": _at(padded, mapping, "note"),
            "raw": padded[: len(headers)],
        }
        if _is_hvs_data_row(item):
            normalized.append(item)
    if not normalized:
        return None
    return _table_payload("hvs_air_system_table_v1", source_ref, headers, mapping, normalized)


def normalize_water_balance_table(matrix: list[list[Any]], *, source_ref: str = "") -> dict[str, Any] | None:
    rows, header_idx, headers, mapping = _prepare_table(matrix, _water_field)
    water_value_fields = {
        "cold_water_m3_day",
        "hot_water_m3_day",
        "process_water_m3_day",
        "fire_water_m3_day",
        "wastewater_m3_day",
        "flow_m3_h",
    }
    if rows is None or header_idx is None or not (water_value_fields & set(mapping)):
        return None
    normalized: list[dict[str, Any]] = []
    for row_no, raw in enumerate(rows[header_idx + 1 :], header_idx + 2):
        padded = raw + [""] * max(0, len(headers) - len(raw))
        if _is_column_number_row(padded):
            continue
        item = {
            "schema": "vk_water_balance_row_v1",
            "source_ref": _row_ref(source_ref, row_no),
            "consumer": _at(padded, mapping, "consumer"),
            "system": _at(padded, mapping, "system"),
            "cold_water_m3_day": _num(_at(padded, mapping, "cold_water_m3_day")),
            "hot_water_m3_day": _num(_at(padded, mapping, "hot_water_m3_day")),
            "process_water_m3_day": _num(_at(padded, mapping, "process_water_m3_day")),
            "fire_water_m3_day": _num(_at(padded, mapping, "fire_water_m3_day")),
            "wastewater_m3_day": _num(_at(padded, mapping, "wastewater_m3_day")),
            "flow_m3_h": _num(_at(padded, mapping, "flow_m3_h")),
            "note": _at(padded, mapping, "note"),
            "raw": padded[: len(headers)],
        }
        if any(
            item.get(k) is not None
            for k in (
                "cold_water_m3_day",
                "hot_water_m3_day",
                "process_water_m3_day",
                "fire_water_m3_day",
                "wastewater_m3_day",
                "flow_m3_h",
            )
        ):
            normalized.append(item)
    if not normalized:
        return None
    return _table_payload("vk_water_balance_table_v1", source_ref, headers, mapping, normalized)


def normalize_room_explication_table(matrix: list[list[Any]], *, source_ref: str = "") -> dict[str, Any] | None:
    rows, header_idx, headers, mapping = _prepare_table(matrix, _room_field)
    if rows is None or header_idx is None or "area_m2" not in mapping or not ({"room_number", "room_name"} & set(mapping)):
        return None
    normalized: list[dict[str, Any]] = []
    for row_no, raw in enumerate(rows[header_idx + 1 :], header_idx + 2):
        padded = raw + [""] * max(0, len(headers) - len(raw))
        if _is_column_number_row(padded):
            continue
        item = {
            "schema": "room_explication_row_v1",
            "source_ref": _row_ref(source_ref, row_no),
            "room_number": _at(padded, mapping, "room_number"),
            "room_name": _at(padded, mapping, "room_name"),
            "area_m2": _num(_at(padded, mapping, "area_m2")),
            "category": _at(padded, mapping, "category"),
            "floor": _at(padded, mapping, "floor"),
            "note": _at(padded, mapping, "note"),
            "raw": padded[: len(headers)],
        }
        if item["area_m2"] is not None and (item["room_number"] or item["room_name"]):
            normalized.append(item)
    if not normalized:
        return None
    return _table_payload("room_explication_table_v1", source_ref, headers, mapping, normalized)


def _extract_page(source_name: str, page: Any, page_no: int) -> dict[str, Any]:
    tables: list[dict[str, Any]] = []
    table_type_candidates: list[dict[str, Any]] = []
    found, table_warning = _find_page_tables(page)
    text_norm = _norm_text(page.get_text("text") or "")
    fragments: list[dict[str, Any]] = []
    for table_idx, table in enumerate(found, 1):
        try:
            matrix = table.extract()
        except Exception:
            continue
        fragments.append(
            {
                "matrix": matrix or [],
                "table_indices": [table_idx],
                "context": _table_context(page, table),
                "bbox": _bbox_values(getattr(table, "bbox", None)),
            }
        )
    for fragment in merge_adjacent_project_table_fragments(fragments):
        table_indices = [int(value) for value in fragment.get("table_indices") or []]
        table_locator = (
            f"table={table_indices[0]}"
            if len(table_indices) == 1
            else f"tables={table_indices[0]}-{table_indices[-1]}"
        )
        source_ref = f"{source_name}#page={page_no}#{table_locator}"
        context_norm = _norm_text(str(fragment.get("context") or ""))
        matrix = fragment.get("matrix") or []
        normalized = _normalize_classified_table(
            matrix,
            source_ref=source_ref,
            page_text_norm=text_norm,
            context_norm=context_norm,
        )
        semantic = classify_project_table_semantic(
            matrix,
            source_ref=source_ref,
            context_norm=context_norm,
            page_text_norm=text_norm,
        )
        semantic = _semantic_from_normalized_tables(normalized, semantic)
        if semantic:
            semantic["source_refs"] = [
                f"{source_name}#page={page_no}#table={table_idx}" for table_idx in table_indices
            ]
            if fragment.get("inherited_header"):
                semantic["inherited_header"] = True
            semantic["bbox"] = list(fragment.get("bbox") or [])
            semantic["header_signature"] = _identity_header_signature(matrix)
            table_type_candidates.append(semantic)
        table_type_candidates.extend(_drawing_annotation_candidates(matrix, source_ref=source_ref))
        tables.extend(normalized)
    hvs_rows = [row for table in tables if table["schema"] == "hvs_air_system_table_v1" for row in table.get("rows") or []]
    water_rows = [row for table in tables if table["schema"] == "vk_water_balance_table_v1" for row in table.get("rows") or []]
    room_rows = [row for table in tables if table["schema"] == "room_explication_table_v1" for row in table.get("rows") or []]
    semantic_counts: dict[str, int] = {}
    for candidate in table_type_candidates:
        table_type = str(candidate.get("semantic_type") or "")
        if table_type:
            semantic_counts[table_type] = semantic_counts.get(table_type, 0) + 1
    return {
        "schema": "project_pdf_table_page_v1",
        "page": page_no,
        "source_ref": f"{source_name}#page={page_no}",
        "tables": tables,
        "table_type_candidates": table_type_candidates[:40],
        "semantic_table_types": semantic_counts,
        "hvs_rows": hvs_rows,
        "water_balance_rows": water_rows,
        "room_explication_rows": room_rows,
        "detected_tables_total": len(table_type_candidates),
        "hvs_rows_total": len(hvs_rows),
        "water_balance_rows_total": len(water_rows),
        "room_explication_rows_total": len(room_rows),
        "warnings": [table_warning] if table_warning else ([] if tables or table_type_candidates else ["project_tables_not_detected"]),
    }


def _find_page_tables(page: Any) -> tuple[list[Any], str]:
    try:
        drawing_count = len(page.get_drawings() or [])
    except Exception:
        drawing_count = 0
    if drawing_count > _MAX_TABLE_DETECTION_DRAWINGS:
        return [], f"table_detection_skipped_heavy_vector_page:drawings={drawing_count}"
    try:
        return list(page.find_tables().tables), ""
    except Exception as exc:  # noqa: BLE001
        return [], f"table_detection_failed:{type(exc).__name__}"


def merge_adjacent_project_table_fragments(fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join consecutive pieces of one logical table before classification.

    PDF drawing grids are often returned by PyMuPDF as several tables. Repeated
    headers are safe merge boundaries. A headerless continuation may inherit a
    known drawing-table header, currently the two-column cable journal header.
    """
    merged: list[dict[str, Any]] = []
    for raw_fragment in fragments:
        matrix = _clean_matrix(raw_fragment.get("matrix") or [])
        if not matrix:
            continue
        current = {
            "matrix": matrix,
            "table_indices": list(raw_fragment.get("table_indices") or []),
            "context": str(raw_fragment.get("context") or ""),
            "inherited_header": False,
            "bbox": _bbox_values(raw_fragment.get("bbox")),
        }
        current_signature = _repeatable_header_signature(matrix)
        if not merged:
            merged.append(current)
            continue
        previous = merged[-1]
        previous_matrix = previous.get("matrix") or []
        previous_signature = _repeatable_header_signature(previous_matrix)
        same_repeated_header = bool(current_signature and current_signature == previous_signature)
        inherited_header = bool(
            not _is_inheritable_header(current_signature)
            and _is_inheritable_header(previous_signature)
            and _matrix_width(matrix) == _matrix_width(previous_matrix)
            and _looks_like_cable_journal_rows(matrix)
        )
        if not (same_repeated_header or inherited_header):
            merged.append(current)
            continue
        data_rows = matrix[1:] if same_repeated_header else matrix
        previous["matrix"].extend(data_rows)
        previous["table_indices"].extend(current["table_indices"])
        previous["inherited_header"] = bool(previous.get("inherited_header") or inherited_header)
        previous["bbox"] = _bbox_union(previous.get("bbox"), current.get("bbox"))
        if current["context"] and current["context"] not in previous["context"]:
            previous["context"] = _clean_text(f"{previous['context']} {current['context']}")
    return merged


def _clean_matrix(matrix: list[list[Any]]) -> list[list[str]]:
    return [[_clean_cell(cell) for cell in row] for row in matrix if any(_clean_cell(cell) for cell in row)]


def _matrix_width(matrix: list[list[Any]]) -> int:
    return max((len(row) for row in matrix), default=0)


def _identity_header_signature(matrix: list[list[Any]]) -> str:
    cleaned = _clean_matrix(matrix)
    if not cleaned:
        return ""
    header = [" ".join(str(value or "").casefold().replace("ё", "е").split()) for value in cleaned[0]]
    return hashlib.sha256("|".join(header).encode("utf-8")).hexdigest()[:24]


def _bbox_values(value: Any) -> list[float]:
    try:
        values = [round(float(item), 3) for item in value]
    except (TypeError, ValueError):
        return []
    return values if len(values) == 4 else []


def _bbox_union(left: Any, right: Any) -> list[float]:
    a = _bbox_values(left)
    b = _bbox_values(right)
    if not a:
        return b
    if not b:
        return a
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _repeatable_header_signature(matrix: list[list[Any]]) -> tuple[str, ...]:
    if not matrix:
        return ()
    signature = tuple(_norm_header(_clean_cell(cell)) for cell in matrix[0])
    nonempty = [value for value in signature if value]
    if len(nonempty) < 2 or not all(any(char.isalpha() for char in value) for value in nonempty):
        return ()
    return signature


def _is_inheritable_header(signature: tuple[str, ...]) -> bool:
    values = set(signature)
    return "имяпанели" in values and "помещение" in values


def _looks_like_cable_journal_rows(matrix: list[list[Any]]) -> bool:
    checked = 0
    for row in matrix[:4]:
        values = [_clean_cell(cell) for cell in row]
        if len(values) < 2 or not values[0] or not values[1]:
            continue
        checked += 1
        if len(values[0]) > 32 or not re.search(r"[A-Za-zА-Яа-я0-9]", values[0]):
            return False
        if not re.search(r"[A-Za-zА-Яа-я]", values[1]):
            return False
    return checked > 0


def _drawing_annotation_candidates(matrix: list[list[Any]], *, source_ref: str) -> list[dict[str, Any]]:
    annotations: list[dict[str, Any]] = []
    for row_no, row in enumerate(_clean_matrix(matrix), 1):
        for cell_no, cell in enumerate(row, 1):
            match = re.search(r"\bотм\.?\s*0[.,]000\s*=*", _norm_text(cell), flags=re.IGNORECASE)
            if not match:
                continue
            annotations.append(
                {
                    "schema": "project_pdf_table_type_candidate_v1",
                    "source_ref": f"{source_ref}#row={row_no}#cell={cell_no}",
                    "source_refs": [f"{source_ref}#row={row_no}#cell={cell_no}"],
                    "semantic_type": "ANNOTATION: нулевая отметка чертежа",
                    "category": "drawing_annotation",
                    "confidence": 0.96,
                    "sample": _clean_text(match.group(0)),
                }
            )
    return annotations


def classify_project_table_semantic(
    matrix: list[list[Any]],
    *,
    source_ref: str = "",
    context_norm: str = "",
    page_text_norm: str = "",
) -> dict[str, Any] | None:
    """Classify any detected PDF table into a compact model-facing type.

    This is intentionally a navigation layer. It does not normalize rows and it
    does not assert engineering conclusions from the table contents.
    """
    rows = [[_clean_cell(cell) for cell in row] for row in matrix if any(_clean_cell(cell) for cell in row)]
    if not rows:
        return None
    sample = _sample_rows(rows)
    if len(rows) < 2 and len(_norm_text(sample)) < 24:
        return None
    # Keep classification local to the table. Full page text often contains
    # neighboring sections and causes false table roles on dense drawing sheets.
    _ = page_text_norm
    text = _norm_text(f"{context_norm} {sample}")
    strong_semantic = _strong_semantic_from_rows(rows, source_ref=source_ref, text=text)
    if strong_semantic:
        semantic_type, category, confidence = strong_semantic
    else:
        semantic_type, category, confidence = _semantic_type_from_text(text, sample)
    return {
        "schema": "project_pdf_table_type_candidate_v1",
        "source_ref": source_ref,
        "semantic_type": semantic_type,
        "category": category,
        "confidence": confidence,
        "sample": sample[:360],
    }


def _semantic_from_normalized_tables(
    normalized: list[dict[str, Any]],
    semantic: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not normalized:
        return semantic
    schema = str(normalized[0].get("schema") or "")
    overrides = {
        "hvs_air_system_table_v1": ("HVAC: характеристики воздушных систем ХВС", 0.92),
        "vk_water_balance_table_v1": ("VK: водные балансы/потребность в воде", 0.92),
        "room_explication_table_v1": ("ROOM: экспликации помещений", 0.92),
    }
    override = overrides.get(schema)
    if not override:
        return semantic
    if semantic is None:
        semantic = {
            "schema": "project_pdf_table_type_candidate_v1",
            "source_ref": str(normalized[0].get("source_ref") or ""),
            "sample": "",
        }
    semantic["semantic_type"] = override[0]
    semantic["category"] = "engineering"
    semantic["confidence"] = override[1]
    return semantic


def _normalize_classified_table(
    matrix: list[list[Any]],
    *,
    source_ref: str,
    page_text_norm: str,
    context_norm: str,
) -> list[dict[str, Any]]:
    classification = classify_project_table(matrix, page_text_norm=page_text_norm, context_norm=context_norm)
    table_type = classification.get("table_type")
    if table_type == "room_explication":
        table = normalize_room_explication_table(matrix, source_ref=source_ref)
    elif table_type == "hvs_air_system":
        table = normalize_hvs_table(matrix, source_ref=source_ref)
    elif table_type == "vk_water_balance":
        table = normalize_water_balance_table(matrix, source_ref=source_ref)
    else:
        table = None
    if not table:
        return []
    table["classification"] = classification
    return [table]


def classify_project_table(
    matrix: list[list[Any]],
    *,
    page_text_norm: str = "",
    context_norm: str = "",
) -> dict[str, Any]:
    """Classify a PDF table before reading its rows."""
    rows = [[_clean_cell(cell) for cell in row] for row in matrix if any(_clean_cell(cell) for cell in row)]
    header_text = " ".join(" ".join(row) for row in rows[:3])
    header_norm = _norm_text(header_text)
    local_context = _norm_text(f"{context_norm} {header_norm}")
    context = _norm_text(f"{local_context} {page_text_norm[:1200]}")
    _rows, _hidx, _headers, room_mapping = _prepare_table(matrix, _room_field)
    _rows, _hidx, _headers, hvs_mapping = _prepare_table(matrix, _hvs_field)
    _rows, _hidx, _headers, water_mapping = _prepare_table(matrix, _water_field)

    room_signal = (
        "area_m2" in room_mapping
        and ({"room_number", "room_name"} & set(room_mapping))
        and (
            "экспликац" in context
            or "номер помещения" in context
            or ("площад" in header_norm and "катег" in header_norm)
        )
    )
    if room_signal:
        return {
            "schema": "project_pdf_table_classification_v1",
            "table_type": "room_explication",
            "confidence": 0.82,
            "basis": "header_context",
        }

    hvs_value_fields = {"airflow_m3h", "pressure_pa", "temperature_c", "heat_load_kw", "cold_load_kw", "equipment"}
    hvs_signal = (
        "system_id" in hvs_mapping
        and bool(hvs_value_fields & set(hvs_mapping))
        and (
            "хвс" in local_context
            or "характеристик" in local_context and "воздуш" in local_context
            or "расход воздуха" in local_context
            or "воздушн" in local_context and "систем" in local_context
            or "обслуживаемого помещения" in local_context and "тип установки" in local_context
        )
    )
    if hvs_signal:
        return {
            "schema": "project_pdf_table_classification_v1",
            "table_type": "hvs_air_system",
            "confidence": 0.78,
            "basis": "header_context",
        }

    water_value_fields = {
        "cold_water_m3_day",
        "hot_water_m3_day",
        "process_water_m3_day",
        "fire_water_m3_day",
        "wastewater_m3_day",
        "flow_m3_h",
    }
    water_signal = (
        bool(water_value_fields & set(water_mapping))
        and (
            "водн" in local_context and "баланс" in local_context
            or "водопотреб" in local_context
            or "водоотвед" in local_context
            or "холодная вода" in local_context
            or "горячая вода" in local_context
            or "сточные" in local_context
        )
    )
    if water_signal:
        return {
            "schema": "project_pdf_table_classification_v1",
            "table_type": "vk_water_balance",
            "confidence": 0.78,
            "basis": "header_context",
        }

    return {
        "schema": "project_pdf_table_classification_v1",
        "table_type": "unknown",
        "confidence": 0.0,
        "basis": "no_matching_header_context",
    }


def _table_context(page: Any, table: Any) -> str:
    bbox = getattr(table, "bbox", None)
    if not bbox or len(bbox) < 4:
        return ""
    x0, y0, x1, _y1 = [float(v) for v in bbox[:4]]
    lines: list[tuple[float, str]] = []
    try:
        blocks = page.get_text("blocks") or []
    except Exception:
        return ""
    for block in blocks:
        if len(block) < 5:
            continue
        bx0, by0, bx1, by1, text = block[:5]
        if by1 <= y0 and y0 - by1 <= 110 and bx1 >= x0 - 80 and bx0 <= x1 + 80:
            value = _clean_text(str(text or ""))
            if value:
                lines.append((float(by1), value))
    return " ".join(text for _y, text in sorted(lines)[-4:])


def _prepare_table(matrix: list[list[Any]], field_mapper) -> tuple[list[list[str]] | None, int | None, list[str], dict[str, int]]:
    rows = [[_clean_cell(cell) for cell in row] for row in matrix if any(_clean_cell(cell) for cell in row)]
    if len(rows) < 2:
        return None, None, [], {}
    best_idx = None
    best_mapping: dict[str, int] = {}
    best_headers: list[str] = []
    best_score = 0
    max_header_start = min(10, len(rows))
    for idx in range(max_header_start):
        for span in range(1, min(5, len(rows) - idx + 1)):
            stacked = _stacked_headers(rows[idx : idx + span])
            mapping = _header_mapping(stacked, field_mapper)
            score = len(mapping)
            if "system_id" in mapping and {"airflow_m3h", "pressure_pa", "equipment"} & set(mapping):
                score += 3
            if "area_m2" in mapping and {"room_number", "room_name"} & set(mapping):
                score += 3
            if {"cold_water_m3_day", "wastewater_m3_day", "flow_m3_h"} & set(mapping):
                score += 2
            if score > best_score:
                best_idx = idx + span - 1
                best_mapping = mapping
                best_headers = stacked
                best_score = score
    if best_idx is None or not best_mapping:
        return rows, None, [], {}
    return rows, best_idx, best_headers, best_mapping


def _header_mapping(headers: list[str], field_mapper) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for col_idx, header in enumerate(headers):
        field = field_mapper(_norm_header(header), _norm_text(header))
        if field and field not in mapping:
            mapping[field] = col_idx
    return mapping


def _stacked_headers(header_rows: list[list[str]]) -> list[str]:
    width = max((len(row) for row in header_rows), default=0)
    headers: list[str] = []
    for col in range(width):
        parts = []
        for row in header_rows:
            if col < len(row) and row[col]:
                parts.append(row[col])
        headers.append(_clean_text(" ".join(parts)))
    return headers


def _hvs_field(key: str, text: str) -> str:
    if (
        key in {"система", "обозначение", "номерсистемы", "обозначениесистемы", "обозначениесистем"}
        or "обознач" in text and "сист" in text
    ):
        return "system_id"
    if any(token in text for token in ("обслуж", "помещ", "зона", "назначение", "технологического оборудования")):
        return "served_zone"
    if any(token in text for token in ("расход", "производительност", "воздух", "приток", "вытяж")) or "l, м3/ч" in text or "l м3/ч" in text:
        return "airflow_m3h"
    if "давлен" in text or "напор" in text or "p, па" in text or key in {"pпа", "рпа"}:
        return "pressure_pa"
    if "темпер" in text:
        return "temperature_c"
    if "тепл" in text and ("квт" in text or "мощн" in text or "нагруз" in text):
        return "heat_load_kw"
    if "холод" in text and ("квт" in text or "мощн" in text or "нагруз" in text):
        return "cold_load_kw"
    if any(token in text for token in ("оборуд", "вентилятор", "установка", "агрегат", "фильтр", "калорифер", "тип установки")):
        return "equipment"
    if "примеч" in text:
        return "note"
    return ""


def _water_field(key: str, text: str) -> str:
    if any(token in text for token in ("потребител", "наименование", "здание", "участок")):
        return "consumer"
    if key == "система" or "система" in text:
        return "system"
    if ("холод" in text or "хв" in key) and ("м3" in text or "сут" in text or "расход" in text):
        return "cold_water_m3_day"
    if ("горяч" in text or "гв" in key) and ("м3" in text or "сут" in text or "расход" in text):
        return "hot_water_m3_day"
    if "производ" in text or "технолог" in text:
        return "process_water_m3_day"
    if "пожар" in text:
        return "fire_water_m3_day"
    if any(token in text for token in ("сток", "канал", "водоотвед", "бытов")):
        return "wastewater_m3_day"
    if ("м3/ч" in text or "м3час" in key or "час" in text) and any(
        token in text for token in ("вод", "сток", "канал", "водоотвед")
    ):
        return "flow_m3_h"
    if "примеч" in text:
        return "note"
    return ""


def _room_field(key: str, text: str) -> str:
    if key in {"номер", "номерпомещения", "пом"} or ("номер" in text and "помещ" in text):
        return "room_number"
    if any(token in text for token in ("наименование", "помещение", "экспликация")):
        return "room_name"
    if "площад" in text or key in {"s", "м2", "м²"}:
        return "area_m2"
    if any(token in text for token in ("катег", "класс", "пожар", "функцион")):
        return "category"
    if "этаж" in text:
        return "floor"
    if "примеч" in text:
        return "note"
    return ""


def _table_payload(schema: str, source_ref: str, headers: list[str], mapping: dict[str, int], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": schema,
        "source_ref": source_ref,
        "headers": headers,
        "mapping": mapping,
        "rows": rows,
        "row_count": len(rows),
    }


def _is_hvs_data_row(item: dict[str, Any]) -> bool:
    system_id = str(item.get("system_id") or "").strip()
    if not system_id or system_id.isdigit():
        return False
    if str(item.get("served_zone") or "").strip():
        return True
    if str(item.get("equipment") or "").strip():
        return True
    return any(item.get(key) is not None for key in ("airflow_m3h", "pressure_pa", "temperature_c", "heat_load_kw", "cold_load_kw"))


def _nav(file_name: str, role: str, discipline: str, use_for: str, row_count: int, manifest: dict[str, Any]) -> dict[str, Any]:
    refs = []
    for page in manifest.get("pages") or []:
        if not isinstance(page, dict):
            continue
        if role == "таблица ХВС" and page.get("hvs_rows_total"):
            refs.append(str(page.get("source_ref") or ""))
        elif role == "водный баланс" and page.get("water_balance_rows_total"):
            refs.append(str(page.get("source_ref") or ""))
        elif role == "экспликация помещений" and page.get("room_explication_rows_total"):
            refs.append(str(page.get("source_ref") or ""))
    return {
        "file_name": file_name,
        "role": role,
        "discipline": discipline,
        "use_for": use_for,
        "row_count": row_count,
        "layers": ["project_pdf_table_manifest"],
        "source_refs": [ref for ref in refs if ref][:5],
    }


def _semantic_nav(file_name: str, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    by_type: dict[str, dict[str, Any]] = {}
    skip_prefixes = ("SERVICE:", "NAV:", "NOISE:", "TEXT:")
    for page in manifest.get("pages") or []:
        if not isinstance(page, dict):
            continue
        for candidate in page.get("table_type_candidates") or []:
            if not isinstance(candidate, dict):
                continue
            semantic_type = str(candidate.get("semantic_type") or "")
            if not semantic_type or semantic_type.startswith(skip_prefixes):
                continue
            row = by_type.setdefault(
                semantic_type,
                {
                    "file_name": file_name,
                    "role": semantic_type,
                    "discipline": _discipline_from_semantic_type(semantic_type),
                    "use_for": _use_for_semantic_type(semantic_type),
                    "row_count": 0,
                    "layers": ["project_pdf_table_manifest"],
                    "source_refs": [],
                },
            )
            row["row_count"] += 1
            ref = str(candidate.get("source_ref") or page.get("source_ref") or "")
            if ref and len(row["source_refs"]) < 5 and ref not in row["source_refs"]:
                row["source_refs"].append(ref)
    return sorted(by_type.values(), key=lambda item: (-int(item.get("row_count") or 0), str(item.get("role") or "")))[:20]


def _discipline_from_semantic_type(semantic_type: str) -> str:
    prefix = semantic_type.split(":", 1)[0]
    return {
        "HVAC": "ОВ",
        "VK": "ВК",
        "ELEC": "ЭС/ЭОМ",
        "LOWCURRENT": "СС",
        "AUTOMATION": "СС/А",
        "FIRE": "ПБ/СС",
        "STRUCT": "КР",
        "ENV": "ООС",
        "ENERGY": "ЭЭ",
        "ROOM": "АР/ПБ/ИОС",
        "GEO": "ПЗ/ПЗУ",
        "LEGAL/GPU": "ПЗ/ПЗУ",
        "QTY": "ВОР",
        "SPEC": "СО",
        "TEP": "ПЗ/ЭЭ",
        "CATALOG": "каталоги",
        "ESTIMATE": "СМ",
        "NORM": "нормативные перечни",
        "COMMERCIAL": "КП/КАЦ",
    }.get(prefix, "")


def _use_for_semantic_type(semantic_type: str) -> str:
    if semantic_type.startswith("STRUCT/"):
        return "расчёты, арматура, сечения, основания и проверки конструкций"
    if semantic_type.startswith("ENV/"):
        return "экологические расчёты: шум, выбросы, отходы, концентрации"
    if semantic_type.startswith("FIRE"):
        return "пожарная безопасность, эвакуация, АУПТ/ПС/СОУЭ и токопотребление"
    if semantic_type.startswith(("AUTOMATION", "LOWCURRENT")):
        return "клеммы, цепи, адресация, порты и слаботочное оборудование"
    if semantic_type.startswith("HVAC"):
        return "воздухообмен, ХВС, теплопотери и характеристики воздушных систем"
    if semantic_type.startswith("ELEC"):
        return "нагрузки, кабельные/линейные таблицы и электротехнические данные"
    if semantic_type.startswith("ROOM"):
        return "номера, имена, площади и категории помещений"
    if semantic_type.startswith("QTY"):
        return "ведомости объёмов и строки для сметы/сверки"
    if semantic_type.startswith("SPEC"):
        return "спецификации оборудования, изделий и материалов"
    if semantic_type.startswith("ENERGY"):
        return "энергоэффективность и теплотехнические расчёты"
    if semantic_type.startswith("ESTIMATE"):
        return "локальные и объектные сметы, ресурсные строки и итоги"
    if semantic_type.startswith("NORM"):
        return "навигация по перечням нормативных документов"
    if semantic_type.startswith("CATALOG"):
        return "каталожные характеристики, комплектация и цены"
    if semantic_type.startswith("COMMERCIAL"):
        return "коммерческие предложения, номенклатура, количества и цены"
    return "навигация по найденным таблицам проекта"


def _merge_counts(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if not key:
            continue
        try:
            count = int(value or 0)
        except Exception:
            count = 0
        target[str(key)] = int(target.get(str(key)) or 0) + count


def _sample_rows(rows: list[list[str]], *, limit: int = 5) -> str:
    lines: list[str] = []
    for row in rows[:limit]:
        line = " | ".join(_clean_text(cell) for cell in row if _clean_text(cell))
        if line:
            lines.append(line)
    return " / ".join(lines)


def _strong_semantic_from_rows(
    rows: list[list[str]],
    *,
    source_ref: str,
    text: str,
) -> tuple[str, str, float] | None:
    """Classify high-signal table families before generic text heuristics."""
    full_text = _norm_text(_sample_rows(rows, limit=24)[:6000])
    header = _norm_text(" | ".join(rows[0])) if rows else ""
    source_norm = source_ref.replace("\\", "/").lower()

    if _looks_like_estimate_table(rows, source_norm=source_norm, full_text=full_text):
        return "ESTIMATE: сметные расчёты и ресурсные строки", "engineering", 0.94
    if "сметная стоимость" in full_text and "наименование работ и затрат" in full_text:
        return "ESTIMATE: сводные и объектные сметные расчёты", "engineering", 0.94
    if _looks_like_commercial_offer(header):
        return "COMMERCIAL: коммерческие предложения и цены", "engineering", 0.94
    if (
        all(token in full_text for token in ("модель", "количество", "описание"))
        or all(token in full_text for token in ("название вб", "модель"))
        or all(token in full_text for token in ("нагрузка(kw)", "модель"))
        or all(token in full_text for token in ("электропитание", "mca(a)", "mfa(a)"))
        or all(token in full_text for token in ("pi-h", "воздушный поток", "звуковое давление"))
    ):
        return "HVAC/EQUIPMENT: подбор и характеристики оборудования", "engineering", 0.9
    if "изделие" in header and "поправочный коэффициент" in header:
        return "HVAC/CALC: поправочные коэффициенты подбора", "engineering", 0.92
    if all(token in full_text for token in ("изделие", "функциональные возможности", "фактическое значение")):
        return "HVAC/CALC: проверка ограничений трассы", "engineering", 0.92
    if "длина(m)" in header and "диаметр трубопровода" in header:
        return "HVAC/PIPE: длины и диаметры трубопроводов", "engineering", 0.92
    if "φ" in full_text and re.search(r"\(\d+\)\s*\|\s*[\d,.]+\s*\|\s*φ", full_text):
        return "HVAC/PIPE: длины и диаметры трубопроводов", "engineering", 0.88
    if "предел огнестойкости" in header and any(
        token in header for token in ("профиль", "металлоконструкц", "плита", "материал требуемый")
    ):
        return "FIRE/STRUCT: огнезащита металлоконструкций", "engineering", 0.92
    if "марка элемента" in header and "арматур" in header:
        return "STRUCT/REINF: арматура, сечения, материалы", "engineering", 0.92
    if "номер" in header and "наименование изделия" in header and "комплектность" in header:
        return "SPEC: спецификации оборудования/изделий/материалов", "engineering", 0.94
    if ("поз." in header or "обозначение" in header) and "наименован" in header and (
        "масса" in header or "кол. ед." in header
    ):
        return "SPEC: спецификации оборудования/изделий/материалов", "engineering", 0.9
    if all(token in header for token in ("размер", "вес", "упаковка", "цена")):
        return "CATALOG/PRICE: каталожные цены и упаковка", "engineering", 0.9
    if header == "технические характеристики" or header.startswith("технические характеристики |"):
        return "CATALOG: каталожные таблицы оборудования", "engineering", 0.86
    if "код сокращения" in header and "описание" in header:
        return "NAV: условные обозначения и сокращения", "navigation", 0.92
    if any(token in full_text for token in ("банк получателя", "сч. №")) and "инн" in full_text and "кпп" in full_text:
        return "SERVICE: банковские реквизиты/счета", "service", 0.96
    if (
        "уровне ответственности члена саморегулируемой организации" in full_text
        or ("подготовка проектной документации" in full_text and "двадцать пять миллионов" in full_text)
    ):
        return "LEGAL/SRO: допуски и уровни ответственности", "navigation", 0.92
    if all(token in header for token in ("обозначение", "наименование", "примечание")):
        if _contains_project_document_cipher(full_text):
            return "NAV: состав/содержание/ведомости документации", "navigation", 0.9
        if re.search(r"\b(?:гост|сп|фз)(?:\s*[a-zа-я])?\s*\d", full_text, flags=re.IGNORECASE):
            return "NORM: перечни нормативных документов", "navigation", 0.9
    if "обозначение" in header and "наименование" in header and _contains_project_document_cipher(full_text):
        return "NAV: состав/содержание/ведомости документации", "navigation", 0.88
    if "перечень актов освидетельствования скрытых работ" in full_text:
        return "NAV: перечень актов скрытых работ", "navigation", 0.94
    if all(token in header for token in ("лист", "наименование", "примечание")) and any(
        row and _clean_cell(row[0]).strip().isdigit() for row in rows[1:]
    ):
        return "NAV: ведомость листов комплекта", "navigation", 0.9
    if "поз." in header and "эскиз" in header:
        return "NOISE: фрагменты схем/выноски без табличной структуры", "noise", 0.9
    if _looks_like_sparse_numeric_fragment(rows, full_text):
        return "NOISE: строки-нумераторы/разорванные табличные сетки", "noise", 0.9
    return None


def _looks_like_estimate_table(rows: list[list[str]], *, source_norm: str, full_text: str) -> bool:
    if not rows:
        return False
    numbers: list[int] = []
    for cell in rows[0]:
        value = _clean_cell(cell).strip()
        if value.isdigit():
            numbers.append(int(value))
    sequential_grid = len(numbers) >= 8 and numbers[:8] == list(range(1, 9))
    estimate_folder = "/сметы/" in source_norm
    signals = sum(
        token in full_text
        for token in (
            "терм", "терп", "тер", "фер", "гэсн", "тссц", "озп=", "зпм=",
            "индекс к позиции", "накладные расходы", "сметная прибыль", "всего с нр и сп",
        )
    )
    estimate_continuation = estimate_folder and signals >= 1 and sum(len(row) for row in rows[:3]) >= 6
    return (sequential_grid and (estimate_folder or signals >= 2)) or estimate_continuation


def _looks_like_commercial_offer(header: str) -> bool:
    product_signal = any(
        token in header
        for token in ("товары (работы, услуги)", "товар |", "товары |", "наименование | ед. | кол-во")
    )
    quantity_signal = "кол-во" in header or "количество" in header
    return product_signal and quantity_signal and "цена" in header and "сумма" in header


def _contains_project_document_cipher(text: str) -> bool:
    codes = "АР|КЖ|КМ|КР|ОВ|ВК|СС|ТХ|ПЗУ|ИОС|ЭОМ|ЭС|АПС|АОВ|СОУЭ|АУПТ"
    return bool(re.search(rf"\d{{2,}}[./-].{{0,100}}(?:{codes})(?:\b|\d)", text, flags=re.IGNORECASE))


def _looks_like_sparse_numeric_fragment(rows: list[list[str]], text: str) -> bool:
    if len(rows) > 6 or len(text) > 220:
        return False
    if re.search(r"\d+\.\s*\d+", text):
        return False
    letters = re.findall(r"[a-zа-яё]", text, flags=re.IGNORECASE)
    digits = re.findall(r"\d", text)
    return len(letters) <= 2 and len(digits) >= 2


def _semantic_type_from_text(text: str, sample: str) -> tuple[str, str, float]:
    if (
        "состав проектной документации" in text
        or "состав проекта" in text
        or "содержание тома" in text
        or "содержание пояснительной записки" in text
        or ("содержание" in text and "перечень сокращений" in text)
        or "оглавление" in text
        or "ведомость рабочих чертежей" in text
        or ("прилагаемые документы" in text and "лист" in text)
        or ("№ тома" in text and "наименование раздела" in text)
        or ("обозначение" in text and "наименование раздела" in text and "приме- чание" in text)
        or ("схема электрическая принципиальная" in text and "лист" in text)
        or ("содержание" in text and "материалы" in text and "основные параметры" in text)
        or ("раздел" in text and "наименование" in text and "исполнитель" in text)
        or _looks_like_toc_fragment(sample)
    ):
        return "NAV: состав/содержание/ведомости документации", "navigation", 0.9
    if any(
        token in text
        for token in (
            "основная надпись",
            "изм. кол.уч",
            "изм. кол. уч",
            "лист №док подп",
            "лист № док",
            "кол. уч.",
            "кол.уч",
            "подпись",
            "взамен инв",
            "взам. ин",
            "инв. n подл",
            "инв. № подл",
            "таблица регистрации изменений",
            "номера листов (страниц)",
        )
    ):
        return "SERVICE: штампы/основные надписи/рамки", "service", 0.74
    if _looks_like_paragraph_fragment(sample):
        return "TEXT: фрагменты пояснительной записки/абзацы", "noise", 0.82
    if _looks_like_lowcurrent_diagram_fragment(sample) or _looks_like_fire_lowcurrent_diagram_fragment(sample) or _looks_like_signal_label_fragment(sample):
        return "NOISE: фрагменты схем/выноски без табличной структуры", "noise", 0.84
    if any(token in text for token in ("экспликация помещений", "назначение помещения", "площадь помещения", "категория помещения")) or (
        ("помещение" in text or "кладовая" in text) and "в4" in text and _looks_like_room_list_fragment(sample)
    ) or (
        "общая площадь" in text and ("наименование части помещения" in text or "помещение" in text)
    ) or _looks_like_room_area_fragment(sample):
        return "ROOM: экспликации помещений", "engineering", 0.86
    if any(token in text for token in ("pуст", "pр", "iр", "cos", "таблица нагруз")):
        return "ELEC: таблицы нагрузок", "engineering", 0.8
    if any(token in text for token in ("освещенность", "кео", "ugr", "разряд зрительных работ", "система общего освещ")):
        return "ELEC/LIGHT: освещение, КЕО и светотехнические нормы", "engineering", 0.78
    if "имя панели" in text and "помещение" in text:
        return "ELEC/CABLE_JOURNAL: панели и помещения кабельного журнала", "engineering", 0.92
    if (
        any(token in text for token in ("марка кабеля", "длина кабеля"))
        or (
            "кабель" in text
            and sum(token in text for token in ("длина", "сечение", "жила", "марка")) >= 2
        )
    ):
        return "ELEC/LINE: кабельные и линейные таблицы", "engineering", 0.76
    if any(token in text for token in ("обозначение системы", "обозна- чение сис", "обслуживаемого помещения", "l, м3/ч")):
        return "HVAC: характеристики воздушных систем ХВС", "engineering", 0.84
    if (
        "таблица воздухообменов" in text
        or ("кратность" in text and "расход воздуха" in text)
        or ("кратн" in text and "приток" in text and "вытяж" in text)
    ):
        return "HVAC: таблицы воздухообменов", "engineering", 0.84
    if (
        any(token in text for token in ("теплопотери", "теплопотери через ограждения", "теплопотери на инфильтрацию"))
        or ("тип ограждения" in text and "q [вт]" in text)
        or ("расчетные теплопоступления" in text and "расход холода" in text)
        or ("наружная стена" in text and ("окно" in text or "кровля" in text) and _looks_like_heat_loss_rows(sample))
    ):
        return "HVAC/HEAT: теплопотери и инфильтрация помещений", "engineering", 0.82
    if (
        "наименование расчетных параметров воздуха" in text
        or ("холодный период" in text and "теплый период" in text and "помещения" in text)
        or "гост 30494" in text
        or "сп 60.13330" in text
    ):
        return "HVAC: параметры воздуха и микроклимат помещений", "engineering", 0.78
    if "водный баланс" in text or "водопотреб" in text or "водоотвед" in text:
        return "VK: водные балансы/потребность в воде", "engineering", 0.82
    if any(
        token in text
        for token in (
            "удельные потери теплоты",
            "поток теплоты",
            "показатель компактности",
            "площадь окон",
            "тепловой энергии",
            "дата заполнения",
            "адрес здания",
            "наименование расчетных параметров",
            "продолжительность отопительного периода",
            "градусо-сутки",
            "расчетное проектное значение",
            "отапливаемый объем",
        )
    ):
        return "ENERGY: теплотехнические и энергоэффективные расчёты", "engineering", 0.82
    if any(token in text for token in ("расчетное сопротивление грунта", "осадка основания", "крен фундамента", "номер слоя", "тип грунта")):
        return "STRUCT/GEO: основания, грунты, фундаменты", "engineering", 0.84
    if any(
        token in text
        for token in (
            "результаты расчета",
            "коэффициент использования",
            "прочность",
            "устойчивость",
            "прогиб",
            "опорные реакции",
            "огибающая величин",
            "максимальный изгибающий момент",
            "минимальный изгибающий момент",
            "перерезывающая сила",
            "коэффициенты условий работы бетона",
        )
    ):
        return "STRUCT/CALC: результаты расчётов и проверки конструкций", "engineering", 0.78
    if any(token in text for token in ("№ констр", "тип кэ", "констр. эл", "шарниры")) and "сечение" in text and "материал" in text:
        return "STRUCT/REINF: арматура, сечения, материалы", "engineering", 0.8
    if any(token in text for token in ("арматура", "сечение", "класс", "материал")) and any(
        token in text for token in ("пролет", "участок", "имя", "стерж", "диаметр")
    ):
        return "STRUCT/REINF: арматура, сечения, материалы", "engineering", 0.76
    if any(token in text for token in ("загружение", "подзагружение", "сочетани", "вид нагрузки", "нормативная нагрузка")) or (
        "тип нагрузки" in text and "величина" in text
    ):
        return "STRUCT/LOAD: нагрузки и сочетания", "engineering", 0.78
    if any(
        token in text
        for token in (
            "источник шума",
            "источниками шума",
            "наименование иш",
            "звукового давления",
            "звуковой мощности",
            "уровни звуковой мощности",
            "уровень звука",
            "октавные уровни",
            "октавных полос",
            "среднегеометрические частоты",
            "сводная таблица источников шума",
            "излучение шума",
            "открытого конца воздуховода",
            "акустической мощности",
            "акустического давления",
            "db(a)",
            "lw [db",
            "lp [db",
            "режим работы источника",
            "тип источника шума",
            "вентустановка",
            "тип вентсистемы",
            "пространственный угол",
            "координаты на плане",
            "поправка на направленность",
            "геометрической дивергенции",
            "затухания звука",
            "показатель направленности источника",
            "узд",
            "пду",
            "превышение",
            "оценочная кривая",
            "расчетная частотная",
            "толщина, м",
            "плотность, кг/м3",
            "mэкв",
            "шумоглуш",
            "lmax, дба",
            "lэкв",
            "дба",
            "дб)",
        )
    ):
        return "ENV/ACOUSTIC: источники шума и акустические расчёты", "engineering", 0.84
    if any(
        token in text
        for token in (
            "выброс",
            "загрязня",
            "иза-",
            "работа строительной техники",
            "проезд автотранспорта",
            "сварочный пост",
            "дэс",
            "компрессор",
            "экскаватор",
            "мини-экска",
            "период года",
            "месяцы",
            "мг/м3",
            "пдв",
            "концентрация",
            "д. пдк",
            "стратификации атмосферы",
            "коэффициент рельефа местности",
            "температура воздуха наиболее",
            "повторяемость штилей",
            "румбы",
        )
    ):
        return "ENV/AIR: выбросы и загрязняющие вещества", "engineering", 0.82
    if any(
        token in text
        for token in (
            "глуб. отбора",
            "глубина отбора",
            "группа почв",
            "ph сол",
            "бенз(а)пирен",
            "категория по zc",
            "определяемые компоненты",
            "определяемый показатель",
            "гранулометрический состав",
            "органическое вещество",
            "ппр (r)",
            "мбк",
        )
    ):
        return "ENV/SOIL: почвы и загрязнение грунтов", "engineering", 0.8
    if any(token in text for token in ("отход", "фкко", "количество отходов", "плот- ность")):
        return "ENV/WASTE: отходы и обращение с отходами", "engineering", 0.8
    if any(
        token in text
        for token in (
            "щит управления",
            "место установки щита",
            "наименование параметра",
            "место отбора импульса",
            "категория трубной проводки",
            "преобразователь частоты",
            "двигатель вентилятора",
            "привод воздушной заслонки",
            "температура приточного",
            "температура вытяжного",
            "давления",
            "щит диспетчеризации",
            "пульт управления",
            "шлюз",
            "контакты",
            "цепь",
            "data+",
            "data-",
            "gnd",
            "tb1",
            "tb2",
            "24vdc",
            "qf",
            "km",
            "iologik",
            "ai",
        )
    ):
        return "AUTOMATION: контакты, клеммы, цепи, I/O", "engineering", 0.78
    if any(token in text for token in ("кол -во портов", "портов", "ip-io", "mp-c-", "линия связи")):
        return "LOWCURRENT: порты/слаботочное оборудование", "engineering", 0.76
    if any(token in text for token in ("ток потребления", "суммарный ток", "режим тревоги", "дежурный режим", "òîê ïîòðåá", "ñóììàðíûé òîê")):
        return "FIRE/LOWCURRENT: расчёты токопотребления ПС/СОУЭ/АУПТ", "engineering", 0.8
    if any(
        token in text
        for token in (
            "эвакуац",
            "пожарного риска",
            "потенциального риска",
            "вероятность присутствия",
            "частота (вероятность) пожара",
            "время блокирования",
            "расположение очага пожара",
            "очаг пожара",
            "параметры очага пожара",
            "горючая нагрузка",
            "низшая теплота сгорания",
            "скорость распространения пламени",
            "массовая скорость выгорания",
            "пожарный отсек",
            "степень огнестойкости",
            "пределы огнестойкости",
            "классы пожарной опасности",
            "аупт",
            "человек m1",
        )
    ):
        return "FIRE: эвакуация, АУПТ и пожарный риск", "engineering", 0.78
    if any(token in text for token in ("защищаемые помещения", "вид аувпт", "интенсивность орошения", "водозаполненная спринклерная")):
        return "FIRE/AUPT: параметры автоматического пожаротушения", "engineering", 0.8
    if any(token in text for token in ("область расчета", "охватываемые помещения", "пожарная модель", "всего:", "дверь")) and "помещение" in text:
        return "FIRE/RISK: исходные данные по присутствию людей", "engineering", 0.74
    if any(
        token in text
        for token in (
            "профессия",
            "количество рабочих часов",
            "рабочих дней в году",
            "рабочих часов в год",
            "сотрудник офиса",
            "сотрудник производственного цеха",
            "обслуживающий персонал",
        )
    ):
        return "FIRE/RISK: исходные данные по присутствию людей", "engineering", 0.74
    if _looks_like_spec_header(text):
        return "SPEC: спецификации оборудования/изделий/материалов", "engineering", 0.78
    if _looks_like_equipment_spec_rows(sample):
        return "SPEC: спецификации оборудования/изделий/материалов", "engineering", 0.76
    if (
        any(token in text for token in ("наименование работ", "наименование вида работ"))
        and any(token in text for token in ("ед. изм", "единица измерения", "единицы измерения"))
        and any(token in text for token in ("кол-во", "количество", "объем работ", "объём работ"))
    ):
        return "QTY: ведомости объёмов/работ", "engineering", 0.76
    if any(token in text for token in ("поз.", "поз .", "позиция", "код оборудования", "поставщик", "тип, марка")) and "наименование" in text:
        return "SPEC: спецификации оборудования/изделий/материалов", "engineering", 0.76
    if any(token in text for token in ("технико-экономические", "наименование показателей", "нормируемое значение")):
        return "TEP: технико-экономические/нормируемые показатели", "engineering", 0.76
    if any(token in text for token in ("численность работающих", "в том числе по сменам", "основные производственные рабочие")):
        return "TEP/STAFF: численность и сменность персонала", "engineering", 0.74
    if (
        "каталог" in text
        or "информация для заказа" in text
        or "параметр / модель" in text
        or ("тип панели" in text and "толщина утеплителя" in text)
        or ("модель" in text and "электропитание" in text and "производительность" in text)
        or ("опциональные элементы" in text and "приток" in text and "вытяжка" in text)
        or "puhy-" in text
        or ("аэродинамические характеристики" in text and any(token in text for token in ("клапан", "вентилятор", "шумоглушитель")))
    ):
        return "CATALOG: каталожные таблицы оборудования", "engineering", 0.72
    if any(
        token in text
        for token in (
            "№ точки",
            "х, м",
            "y, м",
            "широта",
            "долгота",
            "координат характерных точек",
            "координаты точек",
            "координаты (м)",
            "тип точки",
            "система координат",
        )
    ):
        return "GEO: координаты/геодезия/границы", "engineering", 0.8
    if any(token in text for token in ("градостроительного регламента", "отступы от границ", "земельного участка")):
        return "LEGAL/GPU: градостроительные ограничения/ГПЗУ", "engineering", 0.78
    if any(token in text for token in ("общество с ограниченной ответственностью", "акционерное общество")):
        return "SERVICE: штампы/основные надписи/рамки", "service", 0.58
    if _looks_like_drawing_fragment(sample):
        return "NOISE: фрагменты схем/выноски без табличной структуры", "noise", 0.84
    if _looks_like_numeric_grid(sample):
        return "NOISE: строки-нумераторы/разорванные табличные сетки", "noise", 0.86
    return "UNKNOWN: требует ручной/визуальной классификации", "unknown", 0.2


def _looks_like_toc_fragment(sample: str) -> bool:
    text = _norm_text(sample)
    return "..." in sample and any(
        token in text
        for token in (
            "общие положения",
            "исходные данные",
            "основание для проектирования",
            "структура и принцип работы",
        )
    )


def _looks_like_paragraph_fragment(sample: str) -> bool:
    if sample.count("|") >= 4:
        return False
    words = re.findall(r"[A-Za-zА-Яа-яЁё]{3,}", sample)
    if sample.count("|") <= 1 and len(words) >= 18 and len(sample) >= 140:
        return True
    if len(words) < 34:
        return False
    separators = sample.count("/") + sample.count("|")
    return separators <= 3


def _looks_like_room_list_fragment(sample: str) -> bool:
    rows = [row for row in sample.split(" / ") if row.strip()]
    if len(rows) < 3:
        return False
    matches = 0
    for row in rows[:8]:
        cells = [cell.strip() for cell in row.split(" | ")]
        if (
            len(cells) >= 4
            and re.fullmatch(r"\d+[А-Яа-яA-Za-z]?", cells[0] or "")
            and _num(cells[2]) is not None
            and re.fullmatch(r"[А-ЯA-Z]\d", cells[3] or "")
        ):
            matches += 1
    return matches >= 3


def _looks_like_room_area_fragment(sample: str) -> bool:
    rows = [row for row in sample.split(" / ") if row.strip()]
    if len(rows) < 3:
        return False
    room_words = (
        "раздевалка",
        "душевая",
        "умывальная",
        "туалет",
        "подсобное",
        "серверная",
        "телекоммуникационная",
        "загрузочная",
        "цех",
        "электрощитовая",
        "диспетчерская",
    )
    matches = 0
    for row in rows[:8]:
        text = _norm_text(row)
        cells = [cell.strip() for cell in row.split(" | ")]
        if any(word in text for word in room_words) and any(_num(cell) is not None for cell in cells[-3:]):
            matches += 1
    return matches >= 3


def _looks_like_heat_loss_rows(sample: str) -> bool:
    rows = [row for row in sample.split(" / ") if row.strip()]
    if len(rows) < 3:
        return False
    enclosure_tokens = ("наружная стена", "окно", "кровля", "наружная дверь", "пол")
    matches = 0
    for row in rows[:8]:
        text = _norm_text(row)
        cells = [cell.strip() for cell in row.split(" | ")]
        numeric_cells = sum(1 for cell in cells if _num(cell) is not None)
        if any(token in text for token in enclosure_tokens) and numeric_cells >= 3:
            matches += 1
    return matches >= 2


def _looks_like_lowcurrent_diagram_fragment(sample: str) -> bool:
    text = _norm_text(sample)
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9=.-]{2,}", text)
    if len(words) > 36:
        return False
    if "тревога модуля" in text and "неисправность модуля" in text:
        return True
    if "=24b" in text and any(token in text for token in ("сброс", "ethernet", "rs485", "rs-485")):
        return True
    if "аупс." in text and any(token in text for token in ("сп2", "кдл", "дплс")):
        return True
    if "шс" in text and any(token in text for token in ("сир", "лам", "rs485", "rs-485", "=24b")):
        return True
    return False


def _looks_like_fire_lowcurrent_diagram_fragment(sample: str) -> bool:
    text = _norm_text(sample)
    tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9=~.-]{2,}", text)
    if not tokens:
        return False
    markers = (
        "шпс",
        "кдл",
        "сп2",
        "аупс",
        "аппз",
        "соуэ",
        "рип",
        "дплс",
        "ппк",
        "шос",
        "=24b",
        "rwa",
        "откр",
        "закр",
        "пожар",
        "uz-",
        "им-",
        "тк-",
        "ткн-",
        "jb.",
        "~220в",
        "do3",
        "do4",
        "do5",
        "com2",
        "com3",
    )
    hits = sum(1 for marker in markers if marker in text)
    if hits >= 3 and len(tokens) <= 420:
        return True
    if hits >= 2 and (sample.count("|") >= 2 or sample.count("/") >= 2):
        return True
    return False


def _looks_like_signal_label_fragment(sample: str) -> bool:
    text = _norm_text(sample)
    compact = re.sub(r"[|\s/]+", " ", text).strip()
    if re.fullmatch(r"s\d(?: s\d){2,}", compact):
        return True
    tokens = compact.split()
    if 1 <= len(tokens) <= 8 and any(token in {"ai", "di", "do", "ao"} for token in tokens):
        return True
    return False


def _looks_like_drawing_fragment(sample: str) -> bool:
    text = _norm_text(sample)
    rows = [row.strip() for row in sample.split(" / ") if row.strip()]
    tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9=.-]{1,}", text)
    if not rows or len(tokens) > 140:
        return False
    drawing_tokens = {"n", "pe", "ret", "nc", "do", "di", "a1", "a2", "km", "к", "п", "д"}
    hits = sum(1 for token in tokens if token in drawing_tokens)
    numeric = sum(1 for token in tokens if re.fullmatch(r"\d+(?:\.\d+)?", token))
    dotted = len(re.findall(r"\b\d{2}\.\s*\d{2,3}\b", text))
    if hits >= 2 and numeric >= 2:
        return True
    if dotted >= 2:
        return True
    if all(color in text for color in ("красн", "белый")) and any(color in text for color in ("оранж", "розо", "серый")):
        return True
    if "°c" in text and any(token in text for token in ("к=", "t=", "д п", "п д")):
        return True
    if len(tokens) <= 4 and any(token in drawing_tokens for token in tokens):
        return True
    return False


def _looks_like_equipment_spec_rows(sample: str) -> bool:
    rows = [row for row in sample.split(" / ") if row.strip()]
    if len(rows) < 3:
        return False
    matches = 0
    for row in rows[:8]:
        text = _norm_text(row)
        cells = [cell.strip() for cell in row.split(" | ")]
        if len(cells) >= 4 and any(unit in text for unit in (" шт.", " шт ", "квт", "габариты")):
            matches += 1
    return matches >= 3


def _looks_like_spec_header(text: str) -> bool:
    compact = re.sub(r"[^0-9a-zа-я]+", " ", _norm_text(text)).strip()
    return (
        "поз" in compact.split()
        and "обозначение" in compact
        and "наименование" in compact
        and ("кол" in compact.split() or "кол во" in compact or "количество" in compact)
        and ("ед изм" in compact or "единица измерения" in compact)
    )


def _looks_like_numeric_grid(sample: str) -> bool:
    text = _norm_text(sample)
    simple = re.sub(r"[|\s]+", " ", text).strip()
    if simple in {"1 2", "1 2 3", "l, м"}:
        return True
    tokens = simple.split()
    if len(tokens) < 5:
        return False
    numeric = sum(1 for token in tokens if re.fullmatch(r"\d+", token))
    return numeric >= max(5, int(len(tokens) * 0.75))


def _row_ref(source_ref: str, row_no: int) -> str:
    return f"{source_ref}#row={row_no}" if source_ref else f"row={row_no}"


def _at(row: list[str], mapping: dict[str, int], field_name: str) -> str:
    idx = mapping.get(field_name)
    if idx is None or idx >= len(row):
        return ""
    return row[idx]


def _clean_cell(value: Any) -> str:
    return _clean_text(repair_pd_rd_text(str(value or "")))


def _clean_text(value: str) -> str:
    text = str(value or "").translate(_DASHES).replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _norm_text(value: str) -> str:
    return _clean_text(value).casefold().replace("ё", "е")


def _norm_header(value: str) -> str:
    text = _norm_text(value)
    return re.sub(r"[^0-9a-zа-я²]+", "", text.replace("м²", "м2"))


def _num(value: Any) -> float | None:
    text = str(value or "").strip().replace(" ", "").replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _is_column_number_row(row: list[str]) -> bool:
    filled = [_clean_text(value) for value in row if _clean_text(value)]
    if len(filled) < 4:
        return False
    return filled == [str(idx) for idx in range(1, len(filled) + 1)]
