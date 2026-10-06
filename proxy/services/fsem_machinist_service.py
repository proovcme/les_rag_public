"""Authoritative FSEM machine-to-machinist enrichment with control reconciliation."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from math import isfinite
import sqlite3
from pathlib import Path
from backend.runtime_paths import mutable_path
from typing import Any


DEFAULT_DB = mutable_path("data/smeta_base/fsem_2022.sqlite")


def _connect_readonly(path: Path) -> sqlite3.Connection:
    from proxy.smeta_core.base_registry import runtime_data_path

    resolved = runtime_data_path(path)
    try:
        return sqlite3.connect(
            f"{resolved.as_uri()}?mode=ro&immutable=1",
            uri=True,
            timeout=30.0,
        )
    except sqlite3.OperationalError as error:
        raise sqlite3.OperationalError(
            f"unable to open FSEM database {resolved}: {error}"
        ) from error


def _f(value: Any) -> float:
    try:
        return float(str(value or 0).replace(",", "."))
    except ValueError:
        return 0.0


def _finite_number(value: Any) -> float | None:
    """Missing/invalid typed source fields must not become a zero crew or grade."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


@lru_cache(maxsize=4096)
def lookup(machine_code: str, db_path: str = str(DEFAULT_DB)) -> dict[str, Any] | None:
    path = Path(db_path)
    if not path.is_file():
        return None
    conn = _connect_readonly(path)
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
    conn = _connect_readonly(target)
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
    conn = _connect_readonly(target)
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
    """Calculate operators by each machine; reconcile the published aggregate separately.

    421/пр, paragraph 80, formula (1.2), prices each machine's operator hours.
    916/пр, paragraphs 78–79, defines its crew hours per machine-hour. A complete
    typed linkage permits that arithmetic without fitting its components to an
    aggregate. A disagreement remains an unresolved source control, never proof
    that the source was rounded correctly or that editions are compatible.
    """
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
    if any(
        str(item.get("kind") or "") == "machinist" and str(item.get("code") or "").strip()
        for item in resources
    ):
        # An authored detail and an anonymous aggregate can overlap. Preserve
        # both and ask for source reconciliation instead of charging another
        # derived copy of the operator already present.
        return [dict(item) for item in resources], {
            "schema": "fsem_enrichment_v1", "status": "unresolved",
            "reasons": ["explicit_machinist_with_aggregate"],
            "source_aggregates": [dict(item) for item in aggregate],
        }
    detailed: list[dict[str, Any]] = []
    components: list[dict[str, Any]] = []
    derived_values: list[Decimal] = []
    missing: list[str] = []
    for machine in machines:
        code = str(machine.get("code") or "").strip()
        row = lookup(code, target) if code else None
        if row is None:
            missing.append(code or "<machine_without_code>")
            continue
        crew = _finite_number(row.get("crew_hours"))
        driver_code = str(row.get("driver_code") or "")
        grade = _finite_number(row.get("driver_grade"))
        quantity = _finite_number(machine.get(quantity_field))
        if crew is None or quantity is None or quantity < 0:
            missing.append(code)
            continue
        if crew == 0 and not driver_code:
            components.append({
                "machine_resource": dict(machine), "fsem_machine": dict(row), "operator_hours": 0.0,
            })
            continue
        if crew <= 0 or not driver_code or grade is None or grade <= 0:
            missing.append(code)
            continue
        operator_hours_decimal = (
            Decimal(str(machine[quantity_field]).replace(",", "."))
            * Decimal(str(row["crew_hours"]).replace(",", "."))
        )
        operator_hours = float(operator_hours_decimal)
        if not isfinite(operator_hours):
            missing.append(code)
            continue
        derived_values.append(operator_hours_decimal)
        components.append({
            "machine_resource": dict(machine),
            "fsem_machine": dict(row),
            "operator_hours": operator_hours,
        })
        detailed.append({
            "kind": "machinist",
            "name": f"Машинисты, средний разряд {grade:g}",
            "unit": "чел.-ч",
            quantity_field: operator_hours,
            "code": driver_code,
            "machinist_basis": f"ФСЭМ-2022 {code}, экипаж {crew:g}",
            "fsem_machine_code": code,
            "fsem_crew_hours": crew,
            "fsem_driver_grade": grade,
            "fsem_source_page": row.get("source_page"),
        })
    source_values = [_finite_number(item.get(quantity_field)) for item in aggregate]
    if any(value is None or value < 0 for value in source_values):
        return [dict(item) for item in resources], {
            "schema": "fsem_enrichment_v1", "status": "unresolved",
            "reasons": ["invalid_machinist_aggregate_quantity"],
            "source_aggregates": [dict(item) for item in aggregate],
        }
    # Compare published numeric values, not inferred decimal scale or a fitted
    # two-decimal total. Decimal also avoids inventing a float-precision gap.
    source_decimal = sum(
        (Decimal(str(item[quantity_field]).replace(",", ".")) for item in aggregate), Decimal(0),
    )
    derived_decimal = sum(derived_values, Decimal(0))
    source_total = float(source_decimal)
    derived_total = float(derived_decimal)
    disagreement = source_decimal != derived_decimal
    if missing:
        reasons: list[str] = []
        reasons.append("missing or invalid machine mapping: " + ", ".join(missing))
        if disagreement:
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
            "source_aggregates": [dict(item) for item in aggregate],
            "machine_operator_components": components,
        }
    if disagreement and any(item.get("price") not in (None, "") for item in aggregate):
        # The new arithmetic path cannot replace an already authored monetary
        # statement. Preserve the original price and source conflict together.
        return [dict(item) for item in resources], {
            "schema": "fsem_enrichment_v1", "status": "unresolved",
            "source_machinist_hours": source_total,
            "derived_machinist_hours": derived_total,
            "reasons": ["explicit_priced_aggregate_discrepancy"],
            "source_aggregates": [dict(item) for item in aggregate],
            "machine_operator_components": components,
        }
    replaced = [
        dict(item) for item in resources
        if not (str(item.get("kind") or "") == "machinist" and not str(item.get("code") or "").strip())
    ]
    replaced.extend(detailed)
    return replaced, {
        "schema": "fsem_enrichment_v1",
        "status": "derived_with_aggregate_discrepancy" if disagreement else "reconciled",
        "machine_count": len(machines),
        "detailed_machinist_rows": len(detailed),
        "hours": source_total,
        "source_machinist_hours": source_total,
        "derived_machinist_hours": derived_total,
        "calculation_basis": "421/пр п.80 формула (1.2); 916/пр пп.78–79: расход машины × экипаж",
        "aggregate_reconciliation": {
            "status": "discrepancy" if disagreement else "exact",
            "source_aggregates": [dict(item) for item in aggregate],
            "difference_hours": float(derived_decimal - source_decimal),
            "comparison": "published_values_without_fitting",
        },
        "machine_operator_components": components,
    }
