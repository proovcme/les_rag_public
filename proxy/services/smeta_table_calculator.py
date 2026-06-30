"""Table extraction and small arithmetic for model-first smeta.

This is not an estimating brain and not a spec-to-BOR converter. It only turns an
attached tabular text dump into visible rows and calculator atoms that the
estimator model may use in its answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class BorRow:
    source_line: int
    row_no: str
    name: str
    article: str
    maker: str
    unit: str
    qty: float | None
    note: str
    row_type: str


def _parse_num(value: Any) -> float | None:
    text = str(value or "").replace("\xa0", " ").strip()
    if not text:
        return None
    match = re.search(r"-?\d+(?:[\s ]\d{3})*(?:[,.]\d+)?|-?\d+(?:[,.]\d+)?", text)
    if not match:
        return None
    raw = match.group(0).replace(" ", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _fmt_num(value: float | int | None) -> str:
    if value is None:
        return "—"
    number = float(value)
    if number.is_integer():
        return f"{int(number):,}".replace(",", " ")
    return f"{number:,.2f}".replace(",", " ").rstrip("0").rstrip(".")


def _row_type(name: str) -> str:
    low = name.casefold()
    if any(word in low for word in ("монтаж", "устрой", "проклад", "окраск", "нанес", "сборк", "пусконалад")):
        return "work"
    if any(word in low for word in ("кабель", "шкаф", "патч", "розет", "лоток", "короб", "pdu", "hyperline", "dкc", "dkc")):
        return "supply"
    return "supply"


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in str(line or "").split("\t")]


def _last_note(cells: list[str]) -> str:
    if len(cells) <= 6:
        return ""
    tail = [c for c in cells[6:] if c.strip()]
    return tail[-1] if tail else ""


def extract_bor_rows(table_text: str, *, limit: int = 120) -> list[BorRow]:
    rows: list[BorRow] = []
    for line_no, line in enumerate(str(table_text or "").splitlines(), 1):
        cells = _cells(line)
        if len(cells) < 6:
            continue
        row_no = cells[0].strip()
        name = cells[1].strip()
        unit = cells[4].strip()
        qty = _parse_num(cells[5])
        if not row_no.isdigit() or not name or qty is None:
            continue
        if name.casefold().startswith(("раздел ", "оборудование")):
            continue
        rows.append(BorRow(
            source_line=line_no,
            row_no=row_no,
            name=name,
            article=cells[2].strip() if len(cells) > 2 else "",
            maker=cells[3].strip() if len(cells) > 3 else "",
            unit=unit,
            qty=qty,
            note=_last_note(cells),
            row_type=_row_type(name),
        ))
        if len(rows) >= limit:
            break
    return rows


_M_RE = re.compile(r"(?<![0-9])(\d+(?:[,.]\d+)?)\s*м(?![ма-яa-z²³23])", re.IGNORECASE)
_PRICE_RE = re.compile(r"цен[аы]?\s*[:=]?\s*(\d[\d\s.,]*)\s*(?:р|руб)", re.IGNORECASE)
_MIN_ORDER_RE = re.compile(r"миним\w*\s+(?:от\s+)?(\d[\d\s.,]*)\s*(?:уп|шт)", re.IGNORECASE)
_PACK_PCS_RE = re.compile(r"\((\d+(?:[,.]\d+)?)\s*шт\.?\)", re.IGNORECASE)


def _first_meter_value(text: str) -> float | None:
    candidates: list[float] = []
    for match in _M_RE.finditer(text or ""):
        value = _parse_num(match.group(1))
        if value is None:
            continue
        # Ignore tiny connector sizes and obvious model suffixes; keep cable/cord package lengths.
        if value >= 0.1:
            candidates.append(value)
    return candidates[0] if candidates else None


def _price_value(text: str) -> float | None:
    match = _PRICE_RE.search(text or "")
    return _parse_num(match.group(1)) if match else None


def _min_order_value(text: str) -> float | None:
    match = _MIN_ORDER_RE.search(text or "")
    return _parse_num(match.group(1)) if match else None


def calculate_table_atoms(rows: list[BorRow]) -> list[dict[str, Any]]:
    atoms: list[dict[str, Any]] = []
    for row in rows:
        qty = row.qty
        if qty is None:
            continue
        haystack = f"{row.name} {row.note}"
        per_unit_m = _first_meter_value(haystack)
        price = _price_value(haystack)
        min_order = _min_order_value(haystack)
        pack_pcs = _PACK_PCS_RE.search(row.name or "")

        if per_unit_m is not None and row.unit.casefold() in {"шт", "шт.", "упак", "уп."}:
            atoms.append({
                "kind": "quantity_total",
                "row_no": row.row_no,
                "name": row.name[:160],
                "expression": f"{_fmt_num(qty)} {row.unit} × {_fmt_num(per_unit_m)} м",
                "value": round(qty * per_unit_m, 6),
                "unit": "м",
                "provenance": f"строка {row.row_no}: количество {row.qty:g} {row.unit}; длина из наименования/примечания",
            })

        if price is not None:
            atoms.append({
                "kind": "project_price",
                "row_no": row.row_no,
                "name": row.name[:160],
                "expression": f"{_fmt_num(qty)} {row.unit} × {_fmt_num(price)} руб",
                "value": round(qty * price, 2),
                "unit": "руб",
                "provenance": f"строка {row.row_no}: количество {row.qty:g} {row.unit}; цена из примечания",
            })
            if min_order is not None:
                atoms.append({
                    "kind": "minimum_supply_price",
                    "row_no": row.row_no,
                    "name": row.name[:160],
                    "expression": f"{_fmt_num(min_order)} уп × {_fmt_num(price)} руб",
                    "value": round(min_order * price, 2),
                    "unit": "руб",
                    "provenance": f"строка {row.row_no}: минимальная поставка и цена из примечания",
                })
                atoms.append({
                    "kind": "supply_delta",
                    "row_no": row.row_no,
                    "name": row.name[:160],
                    "expression": f"{_fmt_num(min_order)} уп − {_fmt_num(qty)} {row.unit}",
                    "value": round(min_order - qty, 6),
                    "unit": "уп",
                    "provenance": f"строка {row.row_no}: проектное количество против минимальной поставки",
                })
                if per_unit_m is not None:
                    atoms.append({
                        "kind": "minimum_supply_quantity",
                        "row_no": row.row_no,
                        "name": row.name[:160],
                        "expression": f"{_fmt_num(min_order)} уп × {_fmt_num(per_unit_m)} м",
                        "value": round(min_order * per_unit_m, 6),
                        "unit": "м",
                        "provenance": f"строка {row.row_no}: минимальная поставка × длина упаковки",
                    })
        if pack_pcs and row.unit.casefold() in {"шт", "шт."}:
            atoms.append({
                "kind": "unit_warning",
                "row_no": row.row_no,
                "name": row.name[:160],
                "expression": f"в названии упаковка {_fmt_num(_parse_num(pack_pcs.group(1)))} шт, единица в таблице: {row.unit}",
                "value": None,
                "unit": "",
                "provenance": f"строка {row.row_no}: возможная неоднозначность единицы измерения",
            })
    return atoms


def build_table_calculator_packet(table_text: str) -> dict[str, Any]:
    rows = extract_bor_rows(table_text)
    atoms = calculate_table_atoms(rows)
    return {
        "schema": "smeta_table_calculator_v1",
        "row_count": len(rows),
        "rows": [asdict(row) for row in rows],
        "atoms": atoms,
    }


def format_table_calculator_context(packet: dict[str, Any], *, max_rows: int = 80, max_atoms: int = 40) -> str:
    if not packet or packet.get("schema") != "smeta_table_calculator_v1":
        return ""
    rows = packet.get("rows") or []
    atoms = packet.get("atoms") or []
    if not rows:
        return ""
    lines = [
        "Проверяемая таблица/калькулятор из приложенного файла.",
        "Это не готовая смета и не готовый ВОР: код только извлёк строки и посчитал очевидную арифметику.",
        "",
        "Строки таблицы для сметчика:",
        "| N | Тип | Наименование | Ед. | Кол-во | Примечание |",
        "|---:|---|---|---:|---:|---|",
    ]
    for row in rows[:max_rows]:
        lines.append(
            f"| {row.get('row_no') or ''} | {row.get('row_type') or ''} | "
            f"{str(row.get('name') or '')[:120]} | {row.get('unit') or ''} | "
            f"{_fmt_num(row.get('qty'))} | {str(row.get('note') or '')[:100]} |"
        )
    if atoms:
        lines.extend([
            "",
            "Калькуляторные атомы:",
            "| Строка | Тип | Расчёт | Результат | Provenance |",
            "|---:|---|---|---:|---|",
        ])
        for atom in atoms[:max_atoms]:
            value = _fmt_num(atom.get("value")) if atom.get("value") is not None else "—"
            unit = atom.get("unit") or ""
            lines.append(
                f"| {atom.get('row_no') or ''} | {atom.get('kind') or ''} | "
                f"{atom.get('expression') or ''} | {value} {unit} | "
                f"{atom.get('provenance') or ''} |"
            )
    return "\n".join(lines)
