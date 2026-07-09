"""Read-only electrical schematic and load-table manifest extraction.

This is a navigation/evidence layer for electrical PD/RD. It does not solve the
electrical design task and does not pretend that a graphic scheme was fully
understood. The service extracts text labels, vector line primitives, obvious
candidate circuits and normalized load-calculation tables with source refs.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from proxy.services.drawing_manifest_service import repair_pdf_text_mojibake
from proxy.services.pd_rd_manifest_service import repair_pd_rd_text

_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‑": "-"})
DEFAULT_TERMS_PATH = Path("config/domain/electrical_schema_terms.yaml")

_SCHEME_MARKERS = (
    "однолин",
    "принципиальн",
    "схема пита",
    "схема распредел",
    "схема электроснаб",
    "расчетная схема",
)
_LOAD_TABLE_MARKERS = (
    "расчет нагруз",
    "расчёт нагруз",
    "электрические нагрузки",
    "нагрузки электроприемников",
)

_PANEL_RE = re.compile(
    r"\b(?:ВРУ|ГРЩ|РЩ|ЩО|ЩР|ЩС|ЩЭ|ЩК|ЩУ|РУ|ТП|КТП|РП|ШР|ШС)"
    r"(?:[-./]?[А-ЯA-Z0-9]+){0,4}\b",
    re.IGNORECASE,
)
_PROTECTION_RE = re.compile(
    r"\b(?:QF|QFD|QS|FU|KM|АВ|ВА)\s*[-./]?\s*[А-ЯA-Z0-9]*"
    r"(?:\s*\d+(?:[,.]\d+)?\s*(?:A|А))?",
    re.IGNORECASE,
)
_CABLE_RE = re.compile(
    r"\b(?:ВВГ(?:нг(?:[-(]?[A-ZА-Я0-9]+[)]?)?)?|АВВГ|ПвВГ|ППГнг|NYM|КГ|ПУГВ|ПВС)"
    r"[-A-ZА-Яа-я0-9().]*\s+\d+\s*[xх]\s*\d+(?:[,.]\d+)?\b",
    re.IGNORECASE,
)
_LINE_RE = re.compile(
    r"\b(?:(?:L|Л)\s*[-№]?\s*\d+[A-ZА-Я0-9./-]*|(?:Гр\.?|гр\.?|линия|фидер)\s*[-№]?\s*[A-ZА-Я0-9./-]+)\b",
    re.IGNORECASE,
)
_FIELD_PRIORITY = (
    "protection",
    "p_installed_kw",
    "p_calc_kw",
    "q_calc_kvar",
    "s_calc_kva",
    "i_calc_a",
    "cos_phi",
    "ku",
    "cable_length_m",
    "cable",
    "line_id",
    "consumer",
    "panel",
)


@dataclass(frozen=True)
class ElectricalTextNode:
    kind: str
    value: str
    source_ref: str
    bbox_pt: list[float]
    confidence: float = 0.75

    def payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ElectricalLineSegment:
    source_ref: str
    start_pt: list[float]
    end_pt: list[float]
    orientation: str
    length_pt: float

    def payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateCircuit:
    source_ref: str
    from_node: str = ""
    to_node: str = ""
    line_id: str = ""
    cable: str = ""
    cable_length_m: float | None = None
    protection: str = ""
    load_kw: float | None = None
    current_a: float | None = None
    confidence: float = 0.45
    basis: str = "text_cooccurrence"
    warnings: list[str] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def extract_electrical_schematic_manifest(
    pdf_path: str | Path,
    *,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """Extract a bounded electrical schematic manifest from a PDF.

    The function reads text, vector drawing primitives and load tables. It never
    mutates project data and never calls an LLM.
    """
    path = Path(pdf_path)
    manifest: dict[str, Any] = {
        "schema": "electrical_schematic_manifest_v1",
        "source_path": path.as_posix(),
        "file_name": path.name,
        "pages": [],
        "summary": {
            "schematic_pages": 0,
            "load_table_pages": 0,
            "candidate_circuits": 0,
            "load_rows": 0,
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

    try:
        with fitz.open(str(path)) as doc:
            total = int(getattr(doc, "page_count", 0) or 0)
            limit = total if max_pages is None else min(total, max(0, int(max_pages)))
            manifest["page_count"] = total
            manifest["pages_read"] = limit
            for page_index in range(limit):
                page_payload = _extract_page(path.name, doc[page_index], page_index + 1)
                manifest["pages"].append(page_payload)
                if page_payload["sheet_kind"] == "electrical_single_line":
                    manifest["summary"]["schematic_pages"] += 1
                if page_payload["load_tables"]:
                    manifest["summary"]["load_table_pages"] += 1
                manifest["summary"]["candidate_circuits"] += len(page_payload["candidate_circuits"])
                manifest["summary"]["load_rows"] += sum(
                    len(table.get("rows") or []) for table in page_payload["load_tables"]
                )
    except Exception as err:  # noqa: BLE001
        manifest["warnings"].append(f"pdf_read_failed: {err}")
    return manifest


def normalize_load_table_matrix(
    matrix: list[list[Any]],
    *,
    source_ref: str = "",
) -> dict[str, Any] | None:
    """Normalize a load-calculation table matrix into stable row fields."""
    rows = [[_clean_cell(cell) for cell in row] for row in matrix if any(_clean_cell(cell) for cell in row)]
    if len(rows) < 2:
        return None
    header_idx = _find_load_header_row(rows)
    if header_idx is None:
        return None
    headers = rows[header_idx]
    mapping = _map_load_headers(headers)
    if not mapping:
        return None
    normalized: list[dict[str, Any]] = []
    for row_no, raw in enumerate(rows[header_idx + 1 :], header_idx + 2):
        padded = raw + [""] * max(0, len(headers) - len(raw))
        if _is_column_number_row(padded[: len(headers)]):
            continue
        item: dict[str, Any] = {
            "schema": "electrical_load_row_v1",
            "source_ref": f"{source_ref}#row={row_no}" if source_ref else f"row={row_no}",
            "raw": padded[: len(headers)],
        }
        for field_name, col_idx in mapping.items():
            value = padded[col_idx] if col_idx < len(padded) else ""
            if field_name in {
                "p_installed_kw",
                "p_calc_kw",
                "q_calc_kvar",
                "s_calc_kva",
                "i_calc_a",
                "cos_phi",
                "ku",
                "cable_length_m",
            }:
                item[field_name] = _num(value)
            else:
                item[field_name] = value
        if any(item.get(k) for k in ("consumer", "panel", "line_id", "p_calc_kw", "i_calc_a", "cable", "protection")):
            normalized.append(item)
    if not normalized:
        return None
    return {
        "schema": "electrical_load_table_v1",
        "source_ref": source_ref,
        "headers": headers,
        "mapping": mapping,
        "rows": normalized,
        "row_count": len(normalized),
    }


@lru_cache(maxsize=4)
def load_electrical_terms(path: str = "") -> dict[str, Any]:
    """Load electrical extraction aliases.

    The dictionary is operator-editable. Bad/missing YAML returns a minimal empty
    contract so extractor fallback rules still work offline.
    """
    p = Path(path) if path else DEFAULT_TERMS_PATH
    try:
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    data.setdefault("load_fields", {})
    data.setdefault("text_nodes", {})
    return data


def _extract_page(source_name: str, page: Any, page_no: int) -> dict[str, Any]:
    text = repair_pd_rd_text(page.get_text("text") or "")
    text_norm = _norm_text(text)
    text_blocks = _text_blocks(page, source_name=source_name, page_no=page_no)
    nodes = _nodes_from_blocks(text_blocks)
    segments = _line_segments(page, source_name=source_name, page_no=page_no)
    load_tables = _load_tables_from_page(page, source_name=source_name, page_no=page_no)
    candidate_circuits = _candidate_circuits_from_blocks(text_blocks)
    schematic_signal = (
        any(marker in text_norm for marker in _SCHEME_MARKERS)
        or (len(segments) >= 8 and any(node.kind in {"panel", "protection"} for node in nodes))
    )
    load_signal = any(marker in text_norm for marker in _LOAD_TABLE_MARKERS) or bool(load_tables)
    sheet_kind = "electrical_single_line" if schematic_signal else ("electrical_load_table" if load_signal else "unknown")
    return {
        "schema": "electrical_schematic_page_v1",
        "page": page_no,
        "source_ref": f"{source_name}#page={page_no}",
        "sheet_kind": sheet_kind,
        "signals": {
            "schematic_text": any(marker in text_norm for marker in _SCHEME_MARKERS),
            "load_table_text": any(marker in text_norm for marker in _LOAD_TABLE_MARKERS),
            "text_nodes": len(nodes),
            "line_segments": len(segments),
        },
        "text_nodes": [node.payload() for node in nodes],
        "line_segments": [segment.payload() for segment in segments[:120]],
        "line_segments_total": len(segments),
        "candidate_circuits": [circuit.payload() for circuit in candidate_circuits],
        "load_tables": load_tables,
        "warnings": _page_warnings(nodes, segments, candidate_circuits, load_tables, schematic_signal),
    }


def _text_blocks(page: Any, *, source_name: str, page_no: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        blocks = page.get_text("dict").get("blocks", [])
    except Exception:
        return out
    for block in blocks:
        if block.get("type") != 0:
            continue
        parts: list[str] = []
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            if text.strip():
                parts.append(text)
        text = repair_pdf_text_mojibake("\n".join(parts)).strip()
        if not text:
            continue
        bbox = [float(x) for x in block.get("bbox", [])[:4]]
        out.append({"text": text, "bbox_pt": bbox, "source_ref": f"{source_name}#page={page_no}"})
    return out


def _nodes_from_blocks(blocks: list[dict[str, Any]]) -> list[ElectricalTextNode]:
    seen: set[tuple[str, str, tuple[float, ...]]] = set()
    nodes: list[ElectricalTextNode] = []
    for block in blocks:
        text = _clean_text(block.get("text", ""))
        bbox = [float(x) for x in block.get("bbox_pt") or []]
        source_ref = str(block.get("source_ref") or "")
        for kind, pattern in (
            ("panel", _PANEL_RE),
            ("protection", _PROTECTION_RE),
            ("cable", _CABLE_RE),
            ("line", _LINE_RE),
        ):
            for match in pattern.finditer(text):
                value = _clean_text(match.group(0))
                if kind == "panel" and not _valid_panel_value(value):
                    continue
                key = (kind, value.casefold(), tuple(round(x, 1) for x in bbox))
                if key in seen:
                    continue
                seen.add(key)
                nodes.append(ElectricalTextNode(kind, value, source_ref, bbox, _confidence_for_node(kind)))
    return nodes


def _candidate_circuits_from_blocks(blocks: list[dict[str, Any]]) -> list[CandidateCircuit]:
    circuits: list[CandidateCircuit] = []
    for block in blocks:
        text = _clean_text(block.get("text", ""))
        panels = [m.group(0) for m in _PANEL_RE.finditer(text) if _valid_panel_value(m.group(0))]
        cables = [m.group(0) for m in _CABLE_RE.finditer(text)]
        protections = [m.group(0) for m in _PROTECTION_RE.finditer(text)]
        lines = [m.group(0) for m in _LINE_RE.finditer(text)]
        if not (panels and (cables or protections or lines)):
            continue
        warnings = []
        if len(panels) < 2:
            warnings.append("to_node_not_read_from_same_text_block")
        circuits.append(
            CandidateCircuit(
                source_ref=str(block.get("source_ref") or ""),
                from_node=_clean_text(panels[0]) if panels else "",
                to_node=_clean_text(panels[1]) if len(panels) > 1 else "",
                line_id=_clean_text(lines[0]) if lines else "",
                cable=_clean_text(cables[0]) if cables else "",
                cable_length_m=_length_m(text),
                protection=_clean_text(protections[0]) if protections else "",
                load_kw=_power_kw(text),
                current_a=_current_a(text),
                confidence=0.62 if len(panels) > 1 else 0.45,
                basis="same_text_block",
                warnings=warnings,
            )
        )
    circuits.sort(key=_circuit_score, reverse=True)
    return circuits


def _circuit_score(circuit: CandidateCircuit) -> float:
    score = circuit.confidence
    for value in (
        circuit.from_node,
        circuit.to_node,
        circuit.line_id,
        circuit.cable,
        circuit.protection,
        circuit.cable_length_m,
        circuit.load_kw,
        circuit.current_a,
    ):
        if value not in ("", None):
            score += 0.1
    return score


def _line_segments(page: Any, *, source_name: str, page_no: int) -> list[ElectricalLineSegment]:
    segments: list[ElectricalLineSegment] = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return segments
    for drawing in drawings:
        for item in drawing.get("items", []) or []:
            if not item or item[0] != "l" or len(item) < 3:
                continue
            p1, p2 = item[1], item[2]
            x1, y1, x2, y2 = float(p1.x), float(p1.y), float(p2.x), float(p2.y)
            dx, dy = abs(x2 - x1), abs(y2 - y1)
            length = (dx * dx + dy * dy) ** 0.5
            if length < 8:
                continue
            if dx < 2:
                orientation = "vertical"
            elif dy < 2:
                orientation = "horizontal"
            else:
                orientation = "diagonal"
            segments.append(
                ElectricalLineSegment(
                    source_ref=f"{source_name}#page={page_no}",
                    start_pt=[x1, y1],
                    end_pt=[x2, y2],
                    orientation=orientation,
                    length_pt=round(length, 2),
                )
            )
    segments.sort(key=lambda item: item.length_pt, reverse=True)
    return segments


def _load_tables_from_page(page: Any, *, source_name: str, page_no: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        finder = page.find_tables()
    except Exception:
        return out
    for table_idx, table in enumerate(getattr(finder, "tables", []) or [], 1):
        try:
            matrix = table.extract()
        except Exception:
            continue
        source_ref = f"{source_name}#page={page_no}#table={table_idx}"
        normalized = normalize_load_table_matrix(matrix or [], source_ref=source_ref)
        if normalized:
            out.append(normalized)
    return out


def _find_load_header_row(rows: list[list[str]]) -> int | None:
    best_idx = None
    best_score = 0
    for idx, row in enumerate(rows[:8]):
        mapped = _map_load_headers(row)
        score = len(mapped)
        has_load = any(key in mapped for key in ("p_calc_kw", "p_installed_kw", "i_calc_a"))
        has_name = any(key in mapped for key in ("consumer", "panel", "line_id"))
        if has_load and has_name and score > best_score:
            best_idx = idx
            best_score = score
    return best_idx


def _map_load_headers(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, header in enumerate(headers):
        key = _norm_header(header)
        field_name = _header_field(key)
        if field_name and field_name not in mapping:
            mapping[field_name] = idx
    _apply_common_load_table_layout(headers, mapping)
    return mapping


def _apply_common_load_table_layout(headers: list[str], mapping: dict[str, int]) -> None:
    if len(headers) < 11:
        return
    keys = [_norm_header(header) for header in headers]
    if (
        mapping.get("consumer") == 0
        and any("установ" in key or "номиналь" in key for key in keys[2:4])
        and "ku" in mapping
        and "cos_phi" in mapping
    ):
        mapping["p_installed_kw"] = 3
        mapping.setdefault("p_calc_kw", 7)
        mapping.setdefault("q_calc_kvar", 8)
        mapping.setdefault("s_calc_kva", 9)
        mapping.setdefault("i_calc_a", 10)


def _header_field(key: str) -> str:
    dictionary_hit = _header_field_from_dictionary(key)
    if dictionary_hit:
        return dictionary_hit
    if "автомат" in key or "защит" in key or "аппарат" in key or "qf" in key:
        return "protection"
    if any(token in key for token in ("электроприем", "потребител", "наименован", "нагрузк")):
        return "consumer"
    if (
        key.startswith(("щит", "панел", "вру", "грщ"))
        or key in {"ру", "распредустройство"}
    ):
        return "panel"
    if any(token in key for token in ("линия", "фидер", "группа", "гр")):
        return "line_id"
    if "установ" in key or "руст" in key or key in {"py", "pу"}:
        return "p_installed_kw"
    if ("расч" in key and ("р" in key or "p" in key) and "i" not in key) or key in {"рр", "pp", "ррквт", "ppkw"}:
        return "p_calc_kw"
    if "q" in key and ("квар" in key or "расч" in key):
        return "q_calc_kvar"
    if "s" in key and ("ква" in key or "расч" in key):
        return "s_calc_kva"
    if ("i" in key or "ток" in key) and ("расч" in key or "а" in key):
        return "i_calc_a"
    if "cos" in key or "cosφ" in key or "cosфи" in key:
        return "cos_phi"
    if key in {"ку", "ks", "kс"} or "спрос" in key:
        return "ku"
    if "кабель" in key or "провод" in key:
        return "cable"
    if "длина" in key or key in {"l", "lм"}:
        return "cable_length_m"
    return ""


def _header_field_from_dictionary(key: str) -> str:
    fields = load_electrical_terms().get("load_fields") or {}
    for field_name in _FIELD_PRIORITY:
        spec = fields.get(field_name) or {}
        aliases = sorted((str(x) for x in spec.get("aliases") or []), key=len, reverse=True)
        for alias in aliases:
            if _alias_matches_header(key, alias):
                return field_name
    return ""


def _alias_matches_header(key: str, alias: str) -> bool:
    alias_key = _norm_header(alias)
    if not key or not alias_key:
        return False
    if len(alias_key) <= 2:
        if key == alias_key:
            return alias_key in {"l"}
        return key.startswith(alias_key) and any(unit in key[len(alias_key):] for unit in ("квт", "ква", "квар", "а", "м"))
    return alias_key in key


def _page_warnings(
    nodes: list[ElectricalTextNode],
    segments: list[ElectricalLineSegment],
    circuits: list[CandidateCircuit],
    load_tables: list[dict[str, Any]],
    schematic_signal: bool,
) -> list[str]:
    warnings = []
    if schematic_signal and segments and not circuits:
        warnings.append("graphic_scheme_without_readable_circuit_rows")
    if schematic_signal and not any(node.kind == "panel" for node in nodes):
        warnings.append("panel_labels_not_read")
    if load_tables and not any(table.get("rows") for table in load_tables):
        warnings.append("load_table_detected_without_rows")
    return warnings


def _clean_cell(value: Any) -> str:
    return _clean_text(str(value or ""))


def _clean_text(value: str) -> str:
    text = str(value or "").translate(_DASHES)
    return re.sub(r"\s+", " ", text).strip()


def _norm_text(value: str) -> str:
    return _clean_text(value).casefold().replace("ё", "е")


def _norm_header(value: str) -> str:
    text = _norm_text(value)
    text = text.replace("φ", "фи")
    return re.sub(r"[^0-9a-zа-я]+", "", text)


def _num(value: Any) -> float | None:
    text = str(value or "").strip().replace(" ", "").replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _power_kw(text: str) -> float | None:
    match = re.search(
        r"(?:P|Р)\s*(?:расч|р)?\s*[=:]?\s*([0-9]+(?:[,.][0-9]+)?)\s*(?:кВт|kW)",
        text,
        re.IGNORECASE,
    )
    return _num(match.group(1)) if match else None


def _current_a(text: str) -> float | None:
    match = re.search(
        r"(?:I|/)\s*(?:расч|р)?\s*[=:]?\s*([0-9]+(?:[,.][0-9]+)?)\s*(?:A|А)",
        text,
        re.IGNORECASE,
    )
    return _num(match.group(1)) if match else None


def _length_m(text: str) -> float | None:
    patterns = (
        r"(?:L|l|Длина|длина)\s*[=:]?\s*([0-9]+(?:[,.][0-9]+)?)\s*(?:м|m)\b",
        r"([0-9]+(?:[,.][0-9]+)?)\s*(?:м|m)\s+(?:каб|провод|ВВГ|АВВГ|ПвВГ|NYM)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _num(match.group(1))
    return None


def _is_column_number_row(row: list[str]) -> bool:
    values = [_clean_text(value) for value in row]
    filled = [value for value in values if value]
    if len(filled) < 4:
        return False
    expected = [str(idx) for idx in range(1, len(filled) + 1)]
    return filled == expected


def _confidence_for_node(kind: str) -> float:
    return {"panel": 0.78, "protection": 0.7, "cable": 0.82, "line": 0.62}.get(kind, 0.6)


def _valid_panel_value(value: str) -> bool:
    text = _clean_text(value)
    return bool(text) and text != text.casefold()
