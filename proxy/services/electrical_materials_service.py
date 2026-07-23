"""Read-only electrical material/equipment extraction from VOR/SO PDFs."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from proxy.services.pd_rd_manifest_service import repair_pd_rd_text

_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‑": "-"})
_POSITION_RE = re.compile(r"^(?:[IVXLC]+|\d+(?:\.\d+)*)$", re.IGNORECASE)
_CABLE_MARK_RE = re.compile(
    r"\b(?:ВВГ(?:нг(?:[-(]?[A-ZА-Я0-9]+[)]?)?)?|АВВГ|ПвВГ|ППГнг|ППГ|NYM|КГ|ПУГВ|ПВС|ПВ|КПС|UTP|FTP|КунРс)"
    r"[-A-ZА-Яа-я0-9().]*(?:\s+Внг[-A-ZА-Яа-я0-9().]*)?"
    r"(?:\s+\d+\s*[xх]\s*\d+(?:[,.]\d+)?)?",
    re.IGNORECASE,
)
_CABLE_SECTION_RE = re.compile(r"(\d+)\s*[xх]\s*(\d+(?:[,.]\d+)?)")


@dataclass(frozen=True)
class ElectricalMaterialRow:
    source_ref: str
    position: str
    name: str
    unit: str = ""
    quantity: float | None = None
    item_kind: str = "material"
    section: str = ""
    type_mark: str = ""
    product_code: str = ""
    supplier: str = ""
    note: str = ""
    mass_kg: float | None = None
    cable_mark: str = ""
    cable_cores: int | None = None
    cable_section_mm2: float | None = None
    quantity_m: float | None = None
    doc_role: str = ""
    work_action: str = ""
    ip_rating: str = ""
    rated_current_a: float | None = None
    voltage_v: float | None = None
    voltages_v: list[float] | None = None
    rated_power_w: float | None = None
    rated_power_kw: float | None = None
    rated_reactive_power_kvar: float | None = None
    install_height_m: float | None = None
    cable_diameter_mm: float | None = None
    dimensions_mm: list[int] | None = None
    unit_mass_kg: float | None = None
    total_mass_kg: float | None = None
    raw: list[str] | None = None

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def extract_electrical_material_manifest(
    pdf_path: str | Path,
    *,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """Extract electrical material/equipment rows from PDF tables."""
    path = Path(pdf_path)
    manifest: dict[str, Any] = {
        "schema": "electrical_material_manifest_v1",
        "source_path": path.as_posix(),
        "file_name": path.name,
        "pages": [],
        "summary": {
            "material_rows": 0,
            "cable_rows": 0,
            "cable_quantity_m": 0.0,
            "panel_rows": 0,
            "lighting_rows": 0,
            "containment_rows": 0,
            "busbar_rows": 0,
            "protection_rows": 0,
            "vor_rows": 0,
            "so_rows": 0,
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
                page_payload = _extract_material_page(path.name, doc[page_index], page_index + 1)
                manifest["pages"].append(page_payload)
                for row in page_payload["material_rows"]:
                    _add_summary(manifest["summary"], row)
    except Exception as err:  # noqa: BLE001
        manifest["warnings"].append(f"pdf_read_failed: {err}")
    return manifest


def normalize_electrical_material_table(
    matrix: list[list[Any]],
    *,
    source_ref: str = "",
) -> dict[str, Any] | None:
    rows = [[_clean_cell(cell) for cell in row] for row in matrix if any(_clean_cell(cell) for cell in row)]
    if len(rows) < 2:
        return None
    header_idx = _find_header_row(rows)
    if header_idx is None:
        return None
    headers = rows[header_idx]
    mapping = _map_headers(headers)
    if not {"position", "name"}.issubset(mapping) or not ({"unit", "quantity"} & set(mapping)):
        return None
    current_section = ""
    normalized: list[dict[str, Any]] = []
    for row_no, raw in enumerate(rows[header_idx + 1 :], header_idx + 2):
        padded = raw + [""] * max(0, len(headers) - len(raw))
        if _is_column_number_row(padded):
            continue
        position = _at(padded, mapping, "position")
        name = _at(padded, mapping, "name")
        if not position or not name or not _POSITION_RE.match(position):
            continue
        unit = _at(padded, mapping, "unit")
        quantity = _num(_at(padded, mapping, "quantity"))
        if not unit and quantity is None:
            current_section = name
        row = _material_row(
            source_ref=f"{source_ref}#row={row_no}" if source_ref else f"row={row_no}",
            position=position,
            name=name,
            unit=unit,
            quantity=quantity,
            section=current_section,
            type_mark=_at(padded, mapping, "type_mark"),
            product_code=_at(padded, mapping, "product_code"),
            supplier=_at(padded, mapping, "supplier"),
            note=_at(padded, mapping, "note"),
            mass_kg=_num(_at(padded, mapping, "mass_kg")),
            raw=padded[: len(headers)],
        )
        normalized.append(row.payload())
    if not normalized:
        return None
    return {
        "schema": "electrical_material_table_v1",
        "source_ref": source_ref,
        "headers": headers,
        "mapping": mapping,
        "rows": normalized,
        "row_count": len(normalized),
    }


def _extract_material_page(source_name: str, page: Any, page_no: int) -> dict[str, Any]:
    tables = []
    try:
        found = page.find_tables().tables
    except Exception:
        found = []
    for table_idx, table in enumerate(found, 1):
        try:
            matrix = table.extract()
        except Exception:
            continue
        source_ref = f"{source_name}#page={page_no}#table={table_idx}"
        normalized = normalize_electrical_material_table(matrix or [], source_ref=source_ref)
        if normalized:
            tables.append(normalized)
    rows = [row for table in tables for row in table.get("rows") or []]
    return {
        "schema": "electrical_material_page_v1",
        "page": page_no,
        "source_ref": f"{source_name}#page={page_no}",
        "material_tables": tables,
        "material_rows": rows,
        "material_rows_total": len(rows),
        "warnings": [] if tables else ["material_table_not_detected"],
    }


def _material_row(
    *,
    source_ref: str,
    position: str,
    name: str,
    unit: str,
    quantity: float | None,
    section: str,
    type_mark: str,
    product_code: str,
    supplier: str,
    note: str,
    mass_kg: float | None,
    raw: list[str],
) -> ElectricalMaterialRow:
    combined = _clean_text(" ".join(part for part in (name, type_mark, product_code, note) if part))
    item_kind = _classify_item(combined, unit)
    cable_mark = _cable_mark(combined) if item_kind == "cable" else ""
    cores, section_mm2 = _cable_dimensions(cable_mark)
    quantity_m = quantity if item_kind in {"cable", "busbar", "containment"} and _norm_unit(unit) == "м" else None
    unit_mass_kg = _unit_mass_kg(combined)
    total_mass_kg = round(unit_mass_kg * quantity, 3) if unit_mass_kg is not None and quantity is not None else None
    voltages_v = _voltages_v(combined)
    return ElectricalMaterialRow(
        source_ref=source_ref,
        position=position,
        name=name,
        unit=unit,
        quantity=quantity,
        item_kind=item_kind,
        section=section,
        type_mark=type_mark,
        product_code=product_code,
        supplier=supplier,
        note=note,
        mass_kg=mass_kg,
        cable_mark=cable_mark,
        cable_cores=cores,
        cable_section_mm2=section_mm2,
        quantity_m=quantity_m,
        doc_role=_doc_role(source_ref),
        work_action=_work_action(name),
        ip_rating=_ip_rating(combined),
        rated_current_a=_rated_current_a(combined),
        voltage_v=voltages_v[0] if voltages_v else None,
        voltages_v=voltages_v,
        rated_power_w=_rated_power(combined, "w"),
        rated_power_kw=_rated_power(combined, "kw"),
        rated_reactive_power_kvar=_rated_power(combined, "kvar"),
        install_height_m=_install_height_m(combined),
        cable_diameter_mm=_cable_diameter_mm(combined),
        dimensions_mm=_dimensions_mm(combined),
        unit_mass_kg=unit_mass_kg,
        total_mass_kg=total_mass_kg,
        raw=raw,
    )


def _find_header_row(rows: list[list[str]]) -> int | None:
    best_idx = None
    best_score = 0
    for idx, row in enumerate(rows[:8]):
        mapping = _map_headers(row)
        score = len(mapping)
        if "position" in mapping and "name" in mapping and ("quantity" in mapping or "unit" in mapping) and score > best_score:
            best_idx = idx
            best_score = score
    return best_idx


def _map_headers(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, header in enumerate(headers):
        key = _norm_header(header)
        if not key:
            continue
        field = _header_field(key)
        if field and field not in mapping:
            mapping[field] = idx
    return mapping


def _header_field(key: str) -> str:
    if key in {"поз", "позиция"}:
        return "position"
    if "наименование" in key or "характеристика" in key:
        return "name"
    if "тип" in key or "марка" in key or "обозначение" in key:
        return "type_mark"
    if "код" in key and "продук" in key:
        return "product_code"
    if "поставщик" in key:
        return "supplier"
    if key.startswith("ед") or "едизм" in key:
        return "unit"
    if key in {"кол", "колво", "количество"} or "колво" in key:
        return "quantity"
    if "масса" in key:
        return "mass_kg"
    if "примеч" in key:
        return "note"
    return ""


def _classify_item(text: str, unit: str) -> str:
    norm = _norm_text(text)
    unit_norm = _norm_unit(unit)
    if "шинопровод" in norm:
        return "busbar"
    if any(token in norm for token in ("лоток", "короб", "труб", "гофр", "металлорукав", "профиль", "канал")):
        return "containment"
    if any(token in norm for token in ("светильник", "светодиодн", "лента", "драйвер")):
        return "lighting"
    if any(token in norm for token in ("автомат", "выключател", "узо", "диф")):
        return "protection"
    cable_match = _CABLE_MARK_RE.search(text)
    cable_with_section = bool(cable_match and _CABLE_SECTION_RE.search(cable_match.group(0)))
    cable_word = ("кабел" in norm or "провод" in norm) and "розетк" not in norm
    if cable_with_section or (cable_word and unit_norm == "м"):
        return "cable"
    if any(token in norm for token in ("щит", "грщ", "укрм", "вру")) and unit_norm in {"шт", "компл"}:
        return "panel"
    if unit_norm == "м":
        return "linear"
    if unit_norm in {"шт", "компл"}:
        return "equipment"
    if not unit_norm:
        return "section"
    return "material"


def _cable_mark(text: str) -> str:
    match = _CABLE_MARK_RE.search(text)
    if not match:
        return ""
    value = _clean_text(match.group(0))
    return "" if _norm_text(value) == "кг" else value


def _cable_dimensions(mark: str) -> tuple[int | None, float | None]:
    match = _CABLE_SECTION_RE.search(mark or "")
    if not match:
        return None, None
    try:
        return int(match.group(1)), float(match.group(2).replace(",", "."))
    except ValueError:
        return None, None


def _doc_role(source_ref: str) -> str:
    norm = _norm_text(source_ref)
    if re.search(r"(?:^|[/#_.-])вор(?:[/#_.-]|$)", norm):
        return "vor"
    if re.search(r"(?:^|[/#_.-])со(?:[/#_.-]|$)", norm) or re.search(r"(?:^|[/#_.-])so(?:[/#_.-]|$)", norm):
        return "so"
    return ""


def _work_action(name: str) -> str:
    norm = _norm_text(name)
    actions = (
        ("монтаж", "install"),
        ("прокладка", "lay"),
        ("установка", "install"),
        ("сверление", "drill"),
        ("подключение", "connect"),
        ("демонтаж", "dismantle"),
        ("поставка", "supply"),
    )
    for token, action in actions:
        if norm.startswith(token) or f" {token}" in norm:
            return action
    return ""


def _ip_rating(text: str) -> str:
    match = re.search(r"\bIP\s*\d{2,3}[A-ZА-Я]?\b", text, re.IGNORECASE)
    return re.sub(r"\s+", "", match.group(0)).upper() if match else ""


def _rated_current_a(text: str) -> float | None:
    match = re.search(r"\b(\d+(?:[,.]\d+)?)\s*(?:а|a)\b", _norm_text(text), re.IGNORECASE)
    return _float_match(match)


def _voltages_v(text: str) -> list[float] | None:
    norm = _norm_text(text)
    values: list[float] = []
    for multi in re.finditer(r"\b(\d+(?:[,.]\d+)?(?:/\d+(?:[,.]\d+)?)+)\s*(?:в|v)(?![a-zа-я])", norm, re.IGNORECASE):
        for part in multi.group(1).split("/"):
            try:
                values.append(float(part.replace(",", ".")))
            except ValueError:
                continue
    for single in re.finditer(r"\b(\d+(?:[,.]\d+)?)\s*(?:в|v)(?![a-zа-я])", norm, re.IGNORECASE):
        value = _float_match(single)
        if value is not None:
            values.append(value)
    unique: list[float] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique or None


def _rated_power(text: str, kind: str) -> float | None:
    norm = _norm_text(text)
    match = re.search(r"\b(\d+(?:[,.]\d+)?)\s*(квар|kvar|квт|kw|вт|w)\b", norm, re.IGNORECASE)
    if not match:
        return None
    value = _float_match(match)
    unit = match.group(2).casefold()
    if value is None:
        return None
    if kind == "kvar" and unit in {"квар", "kvar"}:
        return value
    if kind == "kw" and unit in {"квт", "kw"}:
        return value
    if kind == "w" and unit in {"вт", "w"}:
        return value
    return None


def _install_height_m(text: str) -> float | None:
    match = re.search(r"высот[еуы]\s*(?:до\s*)?(\d+(?:[,.]\d+)?)\s*(?:м|метр)", _norm_text(text))
    return _float_match(match)


def _cable_diameter_mm(text: str) -> float | None:
    norm = _norm_text(text)
    match = re.search(r"\bd\s*каб\s*=\s*(\d+(?:[,.]\d+)?)\s*мм\b", norm)
    if not match:
        match = re.search(r"диаметр(?:ом)?\s*(\d+(?:[,.]\d+)?)\s*мм\b", norm)
    return _float_match(match)


def _dimensions_mm(text: str) -> list[int] | None:
    match = re.search(r"\b(\d{2,5})\s*[xх]\s*(\d{2,5})(?:\s*[xх]\s*(\d{2,5}))?\s*мм\b", _norm_text(text))
    if not match:
        return None
    return [int(value) for value in match.groups() if value]


def _unit_mass_kg(text: str) -> float | None:
    norm = _norm_text(text)
    match = re.search(r"\b(\d+(?:[,.]\d+)?)\s*кг\s*/\s*(?:м|шт|компл)\b", norm)
    if not match:
        match = re.search(r"вес\s*1\s*шт\.?\s*[-:]*\s*(\d+(?:[,.]\d+)?)\s*кг\b", norm)
    return _float_match(match)


def _add_summary(summary: dict[str, Any], row: dict[str, Any]) -> None:
    summary["material_rows"] += 1
    item_kind = row.get("item_kind") or "material"
    if item_kind == "cable":
        summary["cable_rows"] += 1
        summary["cable_quantity_m"] = round(float(summary.get("cable_quantity_m") or 0.0) + float(row.get("quantity_m") or 0.0), 3)
    elif item_kind == "panel":
        summary["panel_rows"] += 1
    elif item_kind == "lighting":
        summary["lighting_rows"] += 1
    elif item_kind == "containment":
        summary["containment_rows"] += 1
    elif item_kind == "busbar":
        summary["busbar_rows"] += 1
    elif item_kind == "protection":
        summary["protection_rows"] += 1
    doc_role = row.get("doc_role") or ""
    if doc_role == "vor":
        summary["vor_rows"] += 1
    elif doc_role == "so":
        summary["so_rows"] += 1


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
    return re.sub(r"[^0-9a-zа-я]+", "", text)


def _norm_unit(value: str) -> str:
    text = _norm_text(value).replace(".", "")
    if text in {"компл", "комплект"}:
        return "компл"
    if text in {"шт", "штука", "штук"}:
        return "шт"
    if text in {"м", "метр", "метров"}:
        return "м"
    return text


def _num(value: Any) -> float | None:
    text = str(value or "").strip().replace(" ", "").replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _float_match(match: re.Match[str] | None) -> float | None:
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _is_column_number_row(row: list[str]) -> bool:
    filled = [_clean_text(value) for value in row if _clean_text(value)]
    if len(filled) < 4:
        return False
    return filled == [str(idx) for idx in range(1, len(filled) + 1)]
