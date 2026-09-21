"""Source-row coverage, roles, and operator-confirmed overlays. Code does not choose norms."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

SCHEMA = "les.lsr-source-coverage.v1"
ROLES = ("work", "material", "equipment", "resource", "unresolved")
SUPPLY_KINDS = ("install", "supply", "both")
_CONFIRMED_KEYS = (
    "conversion_factor",
    "conversion_source",
    "calc_quantity",
    "confirmed_price",
    "price_source",
    "open_gap",
    "quantity",
    "unit",
    "row_role",
    "work_row",
    "supply_kind",
)
_ROLE_ALIASES = {
    "work": "work",
    "работа": "work",
    "works": "work",
    "material": "material",
    "материал": "material",
    "equipment": "equipment",
    "оборудование": "equipment",
    "resource": "resource",
    "ресурс": "resource",
    "unresolved": "unresolved",
    "нерешено": "unresolved",
    "open": "unresolved",
}
_SUPPLY_ALIASES = {
    "install": "install",
    "монтаж": "install",
    "installation": "install",
    "supply": "supply",
    "поставка": "supply",
    "both": "both",
    "монтаж+поставка": "both",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _locator(row: Mapping[str, Any]) -> str:
    return _text(row.get("source_row"))


def canonicalize_row_role(value: Any) -> str:
    token = " ".join(_text(value).casefold().replace("ё", "е").split())
    return _ROLE_ALIASES.get(token, "")


def canonicalize_supply_kind(value: Any) -> str:
    token = " ".join(_text(value).casefold().replace("ё", "е").split())
    return _SUPPLY_ALIASES.get(token, "")


def inferred_row_role(row: Mapping[str, Any]) -> str:
    """Fallback only when the model omitted row_role. Does not invent a cipher."""

    explicit = canonicalize_row_role(row.get("row_role"))
    if explicit:
        return explicit
    status = _text(row.get("norm_status")).upper()
    code = _text(row.get("norm_code") or row.get("code") or row.get("basis"))
    if status in {"MISSING", "NEEDS_RESEARCH", "CONFLICT"} or not code:
        return "unresolved"
    return "work"


def work_row_key(row: Mapping[str, Any]) -> str:
    parent = _text(row.get("work_row"))
    if parent:
        # A bare row coordinate is relative to the source sheet, as in Excel.
        # Never resolve across sheets or interpret a norm code as a coordinate.
        source = _locator(row)
        if "!" in source and parent.startswith("R") and parent[1:].isdigit():
            return source.rsplit("!", 1)[0] + "!" + parent
        return parent
    role = inferred_row_role(row)
    if role == "work":
        return _locator(row)
    return ""


def apply_confirmed_data(
    rows: Sequence[Mapping[str, Any]],
    overlays: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Apply operator-confirmed fields. Never replace a model cipher."""

    payload = overlays if isinstance(overlays, Mapping) else {}
    merged: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        item = dict(row)
        locator = _locator(item)
        patch = payload.get(locator) if locator else None
        if isinstance(patch, Mapping):
            for key in _CONFIRMED_KEYS:
                if key not in patch or patch.get(key) in (None, ""):
                    continue
                item[key] = patch[key]
            item["confirmed_by"] = "operator"
        merged.append(item)
    return merged


def locators_with_separate_supply(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    linked: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        role = inferred_row_role(row)
        kind = canonicalize_supply_kind(row.get("supply_kind")) or (
            "supply" if role in {"material", "equipment"} else ""
        )
        parent = work_row_key(row)
        if role in {"material", "equipment"} and kind in {"supply", "both"} and parent:
            linked.add(parent)
    return linked


def build_source_coverage(
    *,
    catalog_locators: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    remaining_locators: Sequence[str] = (),
) -> dict[str, Any]:
    """Every source locator must appear as work, material, resource, or an open question."""

    wanted = [_text(item) for item in catalog_locators if _text(item)]
    remaining = [_text(item) for item in remaining_locators if _text(item)]
    by_locator: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        locator = _locator(row)
        if not locator:
            continue
        role = inferred_row_role(row)
        by_locator.setdefault(locator, []).append(
            {
                "locator": locator,
                "role": role,
                "work_row": work_row_key(row),
                "supply_kind": canonicalize_supply_kind(row.get("supply_kind")),
                "open_gap": _text(row.get("open_gap") or row.get("open_question")),
                "role_specified": bool(canonicalize_row_role(row.get("row_role"))),
            }
        )

    def _primary_record(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        for record in records:
            if record.get("role") == "work":
                return dict(record)
        return dict(records[0])

    gaps: list[dict[str, str]] = []
    accounted = 0
    for locator in wanted:
        records = by_locator.get(locator)
        if not records:
            if locator in remaining:
                gaps.append(
                    {
                        "locator": locator,
                        "kind": "unprocessed",
                        "action": (
                            f"Продолжите незакрытую строку {locator}. "
                            "Уже принятые решения повторно не ищутся."
                        ),
                    }
                )
            else:
                gaps.append(
                    {
                        "locator": locator,
                        "kind": "unexplained",
                        "action": (
                            f"Строка {locator} не получила роль. "
                            "Модель должна отметить работу, материал, ресурс или вопрос."
                        ),
                    }
                )
            continue
        accounted += 1
        if not any(record["role_specified"] for record in records):
            gaps.append(
                {
                    "locator": locator,
                    "kind": "role_unspecified",
                    "action": (
                        f"Укажите роль строки {locator}: work, material, equipment, "
                        "resource или unresolved."
                    ),
                }
            )
        for record in records:
            if record["role"] == "unresolved" and not record["open_gap"]:
                gaps.append(
                    {
                        "locator": locator,
                        "kind": "open_gap",
                        "action": f"Сформулируйте конкретный вопрос по строке {locator}.",
                    }
                )
            if record["role"] in {"resource", "material", "equipment"} and not record["work_row"]:
                gaps.append(
                    {
                        "locator": locator,
                        "kind": "missing_work_row",
                        "action": (
                            f"Свяжите строку {locator} с locator работы через work_row, "
                            "не через шифр нормы."
                        ),
                    }
                )

    orphan_parents = []
    known = set(wanted) | set(by_locator)
    work_locators = {
        locator
        for locator, records in by_locator.items()
        if any(record["role"] == "work" for record in records)
    }
    for locator, records in by_locator.items():
        for record in records:
            parent = record.get("work_row") or ""
            if parent and parent not in known and parent not in {record["locator"]}:
                orphan_parents.append(parent)
                gaps.append(
                    {
                        "locator": locator,
                        "kind": "lost_work_link",
                        "action": (
                            f"Строка {locator} ссылается на работу {parent}, которой нет "
                            "среди исходных строк."
                        ),
                    }
                )
            elif (
                parent
                and record["role"] in {"resource", "material", "equipment"}
                and parent not in work_locators
            ):
                gaps.append(
                    {
                        "locator": locator,
                        "kind": "parent_not_work",
                        "action": (
                            f"Ссылка строки {locator} ведёт на {parent}, но там нет "
                            "решения с ролью work. Модель должна связать ресурс с "
                            "работой или явно указать, каких данных не хватает."
                        ),
                    }
                )

    return {
        "schema": SCHEMA,
        "complete": not gaps and (not wanted or accounted >= len(wanted)),
        "catalog_count": len(wanted),
        "accounted": accounted,
        "gap_count": len(gaps),
        "gaps": gaps[:80],
        "incomplete_locators": list(dict.fromkeys(item["locator"] for item in gaps)),
        "roles": [
            _primary_record(by_locator[item]) for item in wanted if item in by_locator
        ],
        "supply_parents": sorted(locators_with_separate_supply(rows)),
    }
