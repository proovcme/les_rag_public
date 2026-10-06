"""Source-row coverage, roles, and operator-confirmed overlays. Code does not choose norms."""
from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:
    from proxy.services.attachment_source_catalog_service import AttachmentSourceCatalog

SCHEMA = "les.lsr-source-coverage.v1"
ROLES = ("work", "material", "equipment", "resource", "unresolved", "header")
SUPPLY_KINDS = ("install", "supply", "both")
_CONFIRMED_KEYS = (
    "operation_id",
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
    "header": "header",
    "заголовок": "header",
    "заголов": "header",
    "раздел": "header",
    "шапка": "header",
    "примечание": "header",
    "note": "header",
    "итог": "header",
    "итоги": "header",
    "subtotal": "header",
    "сводка": "header",
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


def catalog_source_locator(
    value: Any, source_catalog: AttachmentSourceCatalog | None = None,
) -> str:
    """Resolve a technical source identity through the original file catalog.

    The authored row and its operation identity remain untouched. Model-supplied
    ``_catalog_*`` annotations are not authority for an alias association.
    """
    if source_catalog is not None:
        found = source_catalog.lookup(value)
        if found is not None:
            return found.locator
    return _text(value)


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


_VOLATILE_IDENTITY_FIELDS = frozenset(
    {"operation_id", "revision", "revision_origin", "content_sha256",
     # These server-owned annotations describe source cells, not an authored
     # operation. The workbook adapter adds them after the model boundary.
     "_catalog_source_values", "_catalog_source_numbers",
     "_catalog_source_quantity_known", "_catalog_source_unit"}
)


def operation_identity(row: Mapping[str, Any]) -> str:
    """Stable operation key: authored operation_id, else locator+content digest.

    Distinct content on one locator stays a distinct operation; the identical
    decision redelivered resolves to the same key. No title guessing involved.
    """

    op = _text(row.get("operation_id"))
    if op:
        return f"op:{op}"
    core = {
        str(key): value
        for key, value in row.items()
        if str(key) not in _VOLATILE_IDENTITY_FIELDS
    }
    raw = json.dumps(
        core, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return f"id:{_locator(row)}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def resolve_work_coverage(
    rows: Sequence[Mapping[str, Any]], *,
    source_catalog: AttachmentSourceCatalog | None = None,
) -> dict[int, dict[str, Any]]:
    """Resolve only explicit authored coverage edges, without judging their meaning.

    A locator must identify exactly one operation; operation_id disambiguates it.
    Iterative traversal also handles long documents and cycles without recursion.
    Indices are internal references into the unmodified input, never model IDs.
    """
    aliases: dict[str, set[int]] = {}
    for index, row in enumerate(rows):
        for key in {_locator(row), catalog_source_locator(row.get("source_row"), source_catalog),
                    _text(row.get("operation_id")), operation_identity(row)} - {""}:
            aliases.setdefault(key, set()).add(index)
    edges: dict[int, int] = {}
    result: dict[int, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        value = row.get("covered_by_work_id")
        if value in (None, "", "-", "—"):
            continue
        if not isinstance(value, str):
            result[index] = {"error": "coverage_target_invalid"}
            continue
        ref = value.strip()
        if "!" in _locator(row) and ref.startswith("R") and ref[1:].isdigit():
            ref = _locator(row).rsplit("!", 1)[0] + "!" + ref
        candidates = set(aliases.get(ref, set()))
        candidates.update(aliases.get(catalog_source_locator(ref, source_catalog), set()))
        work_candidates = {candidate for candidate in candidates
                           if inferred_row_role(rows[candidate]) == "work"}
        error = ""
        if inferred_row_role(row) != "work":
            error = "coverage_role_conflict"
        elif not candidates:
            error = "coverage_target_missing"
        elif not work_candidates:
            error = "coverage_role_conflict"
        elif len(work_candidates) != 1:
            error = "coverage_target_ambiguous"
        if error:
            result[index] = {"error": error}
        else:
            edges[index] = next(iter(work_candidates))
    for start in edges:
        if start in result:
            continue
        trail: list[int] = []
        seen: set[int] = set()
        current = start
        while current in edges and current not in result and current not in seen:
            seen.add(current)
            trail.append(current)
            current = edges[current]
        resolved = (
            {"error": "coverage_cycle"} if current in seen
            else result.get(current, {"target_index": current})
        )
        for index in trail:
            result[index] = dict(resolved)
    for index, target in edges.items():
        result[index]["direct_target_index"] = target
    return result


def double_count_conflicts(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Same locator, different supply roles, same item: an accounting conflict.

    Code never deletes one of the rows on a guess. It surfaces the conflict so
    the model or the operator resolves the role explicitly; both rows and the
    full history stay in place.
    """

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        role = inferred_row_role(row)
        if role not in {"material", "equipment"}:
            continue
        locator = _locator(row)
        if not locator:
            continue
        grouped.setdefault(locator, []).append(row)
    conflicts: list[dict[str, Any]] = []
    for locator, group in grouped.items():
        by_item: dict[str, list[Mapping[str, Any]]] = {}
        for row in group:
            name = " ".join(_text(row.get("title") or row.get("name")).casefold().split())
            if not name:
                continue
            by_item.setdefault(name, []).append(row)
        for name, items in by_item.items():
            roles = {inferred_row_role(row) for row in items}
            if len(items) > 1 and len(roles) > 1:
                conflicts.append(
                    {
                        "locator": locator,
                        "item": name,
                        "roles": sorted(roles),
                        "operations": [operation_identity(row) for row in items],
                    }
                )
    return conflicts


def apply_confirmed_data(
    rows: Sequence[Mapping[str, Any]],
    overlays: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Apply operator-confirmed fields. Never replace a model cipher.

    A patch may be addressed to one operation via ``operation_id`` or
    ``row_role``. An unaddressed patch on a locator that carries several
    operations stays ambiguous: a confirmed price is never applied to every
    row of the locator without an explicit target.
    """

    payload = overlays if isinstance(overlays, Mapping) else {}
    shaped = [dict(row) for row in rows if isinstance(row, Mapping)]
    rows_by_locator: dict[str, list[dict[str, Any]]] = {}
    for item in shaped:
        locator = _locator(item)
        if locator:
            rows_by_locator.setdefault(locator, []).append(item)
    merged: list[dict[str, Any]] = []
    for row in shaped:
        item = dict(row)
        locator = _locator(item)
        patch = payload.get(locator) if locator else None
        if isinstance(patch, Mapping):
            target_op = _text(patch.get("operation_id"))
            target_role = canonicalize_row_role(patch.get("row_role"))
            addressed = bool(target_op or target_role)
            matches = True
            if target_op:
                matches = matches and _text(item.get("operation_id")) == target_op
            if target_role:
                matches = matches and inferred_row_role(item) == target_role
            if addressed and matches:
                _apply_overlay_fields(item, patch)
            elif not addressed and len(rows_by_locator.get(locator, [])) > 1:
                # One locator, several operations: an unaddressed confirmation
                # must not silently price all of them. Keep it visible instead.
                item["confirm_ambiguous"] = True
            elif not addressed:
                _apply_overlay_fields(item, patch)
        merged.append(item)
    return merged


def _apply_overlay_fields(item: dict[str, Any], patch: Mapping[str, Any]) -> None:
    for key in _CONFIRMED_KEYS:
        if key not in patch or patch.get(key) in (None, ""):
            continue
        item[key] = patch[key]
    item["confirmed_by"] = "operator"


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
    source_catalog: AttachmentSourceCatalog | None = None,
) -> dict[str, Any]:
    """Every source locator must appear as work, material, resource, or an open question."""

    wanted = [catalog_source_locator(item, source_catalog) for item in catalog_locators if _text(item)]
    remaining = [catalog_source_locator(item, source_catalog) for item in remaining_locators if _text(item)]
    by_locator: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        locator = catalog_source_locator(row.get("source_row"), source_catalog)
        if not locator:
            continue
        role = inferred_row_role(row)
        by_locator.setdefault(locator, []).append(
            {
                "locator": locator,
                "role": role,
                "work_row": catalog_source_locator(work_row_key(row), source_catalog),
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
        "supply_parents": sorted({catalog_source_locator(item, source_catalog)
                                  for item in locators_with_separate_supply(rows)}),
    }
