"""Authoritative FSEM machine-to-machinist enrichment with control reconciliation."""

from __future__ import annotations

from functools import lru_cache
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB = Path("data/smeta_base/fsem_2022.sqlite")


def _f(value: Any) -> float:
    try:
        return float(str(value or 0).replace(",", "."))
    except ValueError:
        return 0.0


@lru_cache(maxsize=4096)
def lookup(machine_code: str, db_path: str = str(DEFAULT_DB)) -> dict[str, Any] | None:
    path = Path(db_path)
    if not path.is_file():
        return None
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM machines WHERE machine_code=?", (str(machine_code or "").strip(),)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def machine_to_machinist(path: str | None = None) -> dict[str, tuple[str, str]]:
    """Compatibility view; unlike the old seed it is generated from the full FSEM catalog."""
    target = Path(path) if path else DEFAULT_DB
    if not target.is_file():
        return {}
    conn = sqlite3.connect(target)
    try:
        return {
            str(code): (str(driver_code), f"Машинисты, средний разряд {grade:g}")
            for code, driver_code, grade in conn.execute(
                "SELECT machine_code,driver_code,driver_grade FROM machines WHERE driver_code<>'' AND crew_hours>0"
            )
        }
    finally:
        conn.close()


def list_entries(path: str | None = None) -> list[dict[str, Any]]:
    """Return the full typed FSEM catalog for diagnostics/UI, never a seed fallback."""
    target = Path(path) if path else DEFAULT_DB
    if not target.is_file():
        return []
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM machines ORDER BY machine_code")]
    finally:
        conn.close()


def lookup_machinist(machine_code: str, path: str | None = None) -> tuple[str, str] | None:
    row = lookup(str(machine_code or "").strip(), str(Path(path) if path else DEFAULT_DB))
    if not row or not row.get("driver_code") or _f(row.get("crew_hours")) <= 0:
        return None
    return str(row["driver_code"]), f"Машинисты, средний разряд {_f(row.get('driver_grade')):g}"


def enrich_machinists(
    resources: list[dict[str, Any]],
    *,
    quantity_field: str,
    db_path: str | Path = DEFAULT_DB,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Replace anonymous aggregate only after full FSEM coverage and hour reconciliation."""
    target = str(Path(db_path))
    machines = [item for item in resources if str(item.get("kind") or "") == "machine"]
    aggregate = [
        item for item in resources
        if str(item.get("kind") or "") == "machinist" and not str(item.get("code") or "").strip()
    ]
    if not machines or not aggregate:
        return [dict(item) for item in resources], {
            "schema": "fsem_enrichment_v1",
            "status": "not_applicable",
            "machine_count": len(machines),
            "aggregate_count": len(aggregate),
        }
    if any(not str(item.get("code") or "").strip() for item in machines) and all(
        item.get("price") not in (None, "") for item in aggregate
    ):
        # Explicitly priced user/legacy aggregate with an unidentified machine
        # is already a complete monetary statement. Replacing it would discard
        # the supplied price and manufacture an incomplete FSEM split.
        return [dict(item) for item in resources], {
            "schema": "fsem_enrichment_v1",
            "status": "not_applicable_explicit_aggregate",
            "machine_count": len(machines),
            "aggregate_count": len(aggregate),
        }
    detailed: list[dict[str, Any]] = []
    missing: list[str] = []
    for machine in machines:
        code = str(machine.get("code") or "").strip()
        row = lookup(code, target) if code else None
        if row is None:
            missing.append(code or "<machine_without_code>")
            continue
        crew = _f(row.get("crew_hours"))
        driver_code = str(row.get("driver_code") or "")
        if crew <= 0 and not driver_code:
            continue
        if crew <= 0 or not driver_code:
            missing.append(code)
            continue
        detailed.append({
            "kind": "machinist",
            "name": f"Машинисты, средний разряд {_f(row.get('driver_grade')):g}",
            "unit": "чел.-ч",
            quantity_field: round(_f(machine.get(quantity_field)) * crew, 6),
            "code": driver_code,
            "machinist_basis": f"ФСЭМ-2022 {code}, экипаж {crew:g}",
            "fsem_source_page": row.get("source_page"),
        })
    source_total = round(sum(_f(item.get(quantity_field)) for item in aggregate), 6)
    derived_total = round(sum(_f(item.get(quantity_field)) for item in detailed), 6)
    tolerance = max(0.0001, abs(source_total) * 0.001)
    if missing or abs(source_total - derived_total) > tolerance:
        reasons: list[str] = []
        if missing:
            reasons.append("missing machine mapping: " + ", ".join(missing))
        if abs(source_total - derived_total) > tolerance:
            reasons.append(
                f"machinist hours mismatch: source={source_total:g}, derived={derived_total:g}"
            )
        return [dict(item) for item in resources], {
            "schema": "fsem_enrichment_v1",
            "status": "unresolved",
            "missing_machine_codes": missing,
            "source_machinist_hours": source_total,
            "derived_machinist_hours": derived_total,
            "reasons": reasons,
        }
    replaced = [
        dict(item) for item in resources
        if not (str(item.get("kind") or "") == "machinist" and not str(item.get("code") or "").strip())
    ]
    replaced.extend(detailed)
    return replaced, {
        "schema": "fsem_enrichment_v1",
        "status": "reconciled",
        "machine_count": len(machines),
        "detailed_machinist_rows": len(detailed),
        "hours": source_total,
    }
