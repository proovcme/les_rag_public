"""Classify an extracted Revit family into a candidate geometry archetype, using
cheap deterministic features — no model (LES3_PLAN W10.2, archetype prioritization).

Goal: run over a RAG dump of extracted families (`artel.revit_family_catalog.v1`,
produced by the `ARTEL Family Extract` add-in command) and report which archetypes
cover the most of the real nomenclature — i.e. which archetypes to author first.

Features are taken from what the extractor actually returns today — category,
parameter names, types, material/symbol counts. Geometry signals (bounding-box
aspect ratio, solid count) are *optional*: the Windows/Revit geometry extractor will
add them later, and the classifier uses them as a tie-breaker/boost when present.

This is the dictionary/rules tier of LLM-minimalism (ADR-11): category + a
dimension-role synonym dictionary + counts decide the candidate archetype. A family
that matches nothing is `unknown` — a candidate to author a new archetype for.
"""

from __future__ import annotations

import argparse
import glob
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

try:  # pragma: no cover - import shim
    from tools import artel_family_geometry as geometry_lib
except ImportError:  # pragma: no cover
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools import artel_family_geometry as geometry_lib

# Dimension role -> substrings that name it (lowercased; RU + EN).
DIM_ROLE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "width": ("ширин", "width"),
    "depth": ("глубин", "depth"),
    "height": ("высот", "height"),
    "length": ("длин", "length"),
    "thickness": ("толщин", "thickness"),
    "diameter": ("диаметр", "diameter", "ø", "dn"),
    "radius": ("радиус", "radius"),
}

# Category keyword groups (substrings, lowercased).
_MEP_CATEGORIES = (
    "pipe", "duct", "conduit", "cable", "electrical", "mechanical", "plumbing",
    "fitting", "accessor", "труб", "воздуховод", "кабель", "электр",
)
_PANEL_CATEGORIES = ("panel", "glazing", "curtain", "sheet", "щит", "панель", "стекл")
_BOX_CATEGORIES = (
    "furniture", "casework", "equipment", "specialty", "generic", "мебель",
    "оборудован", "шкаф", "стеллаж",
)
_LINEAR_CATEGORIES = ("railing", "framing", "beam", "column", "structural", "огражд", "балк", "колонн")

MIN_SCORE = 2.0  # below this -> unknown


@dataclass
class FamilyFeatures:
    family_name: str
    category: str
    parameter_names: list[str]
    dim_roles: set[str]
    n_parameters: int
    n_types: int
    n_materials: int
    n_symbols: int
    bbox: dict[str, float] | None = None       # optional {x, y, z} (mm), future
    solid_count: int | None = None             # optional, future


def _roles_from_names(names: list[str]) -> set[str]:
    roles: set[str] = set()
    for raw in names:
        low = raw.lower()
        for role, synonyms in DIM_ROLE_SYNONYMS.items():
            if any(token in low for token in synonyms):
                roles.add(role)
    return roles


def extract_features(catalog: dict[str, Any]) -> FamilyFeatures:
    """Build features from an artel.revit_family_catalog.v1 extract (tolerant)."""
    params = catalog.get("parameters") or []
    names = [str(p.get("name", "")).strip() for p in params if p.get("name")]
    types = catalog.get("types") or []
    materials = catalog.get("materials") or []
    symbols = catalog.get("family_symbols") or []

    bbox = catalog.get("bounding_box") or catalog.get("bbox")
    if isinstance(bbox, dict):
        try:
            bbox = {axis: float(bbox[axis]) for axis in ("x", "y", "z")}
        except (KeyError, TypeError, ValueError):
            bbox = None
    else:
        bbox = None

    solid_count = catalog.get("solid_count")
    solid_count = int(solid_count) if isinstance(solid_count, (int, float)) else None

    return FamilyFeatures(
        family_name=str(catalog.get("family_name") or catalog.get("document_title") or "?"),
        category=str(catalog.get("category") or "").strip(),
        parameter_names=names,
        dim_roles=_roles_from_names(names),
        n_parameters=len(names),
        n_types=len(types),
        n_materials=len(materials),
        n_symbols=len(symbols),
        bbox=bbox,
        solid_count=solid_count,
    )


def _cat_has(category: str, hints: tuple[str, ...]) -> bool:
    low = category.lower()
    return any(hint in low for hint in hints)


def _bbox_axes_sorted(bbox: dict[str, float] | None) -> list[float] | None:
    if not bbox:
        return None
    values = sorted(v for v in bbox.values() if v > 0)
    return values if len(values) == 3 else None


# Each scorer returns (score, reasons).
Scorer = Callable[[FamilyFeatures], "tuple[float, list[str]]"]


def _score_rect_cabinet(f: FamilyFeatures) -> tuple[float, list[str]]:
    score, reasons = 0.0, []
    box_dims = f.dim_roles & {"width", "depth", "height"}
    if len(box_dims) >= 3:
        score += 3.0; reasons.append("есть width+depth+height")
    elif len(box_dims) == 2:
        score += 1.5; reasons.append(f"2 из 3 габаритов: {sorted(box_dims)}")
    if _cat_has(f.category, _BOX_CATEGORIES):
        score += 1.5; reasons.append(f"категория-корпус: {f.category}")
    axes = _bbox_axes_sorted(f.bbox)
    if axes and axes[0] / axes[2] > 0.25:
        score += 1.0; reasons.append("bbox: три соизмеримых оси")
    return score, reasons


def _score_panel(f: FamilyFeatures) -> tuple[float, list[str]]:
    score, reasons = 0.0, []
    if {"width", "height"} <= f.dim_roles and "depth" not in f.dim_roles:
        score += 2.0; reasons.append("width+height без depth")
    if "thickness" in f.dim_roles:
        score += 1.5; reasons.append("есть толщина")
    if _cat_has(f.category, _PANEL_CATEGORIES):
        score += 1.5; reasons.append(f"категория-панель: {f.category}")
    axes = _bbox_axes_sorted(f.bbox)
    if axes and axes[0] / axes[2] < 0.1:
        score += 1.5; reasons.append("bbox: одна тонкая ось")
    return score, reasons


def _score_bar_profile(f: FamilyFeatures) -> tuple[float, list[str]]:
    score, reasons = 0.0, []
    if "length" in f.dim_roles:
        score += 1.5; reasons.append("есть длина")
    if _cat_has(f.category, _LINEAR_CATEGORIES):
        score += 2.0; reasons.append(f"категория-линейная: {f.category}")
    axes = _bbox_axes_sorted(f.bbox)
    if axes and axes[2] / max(axes[1], 1e-6) > 5:
        score += 1.5; reasons.append("bbox: одна длинная ось")
    return score, reasons


def _score_cylinder_revolve(f: FamilyFeatures) -> tuple[float, list[str]]:
    score, reasons = 0.0, []
    round_roles = f.dim_roles & {"diameter", "radius"}
    if round_roles:
        score += 3.0; reasons.append(f"круглые размеры: {sorted(round_roles)}")
    return score, reasons


def _score_flanged_fitting(f: FamilyFeatures) -> tuple[float, list[str]]:
    score, reasons = 0.0, []
    if _cat_has(f.category, _MEP_CATEGORIES):
        score += 3.0; reasons.append(f"MEP-категория: {f.category}")
    if f.dim_roles & {"diameter", "radius"}:
        score += 1.0; reasons.append("номинальный диаметр")
    return score, reasons


# Candidate archetype taxonomy. `implemented` is derived from the geometry library.
ARCHETYPE_SCORERS: dict[str, Scorer] = {
    "rect_cabinet": _score_rect_cabinet,
    "panel": _score_panel,
    "bar_profile": _score_bar_profile,
    "cylinder_revolve": _score_cylinder_revolve,
    "flanged_fitting": _score_flanged_fitting,
}


def classify(features: FamilyFeatures) -> dict[str, Any]:
    """Return the best candidate archetype with score, reasons and runner-up."""
    scored = []
    for name, scorer in ARCHETYPE_SCORERS.items():
        score, reasons = scorer(features)
        scored.append((score, name, reasons))
    # Deterministic order: score desc, then archetype name asc.
    scored.sort(key=lambda item: (-item[0], item[1]))

    best_score, best_name, best_reasons = scored[0]
    runner = scored[1] if len(scored) > 1 else None

    if best_score < MIN_SCORE:
        return {
            "family_name": features.family_name,
            "archetype": "unknown",
            "score": round(best_score, 2),
            "confidence": "none",
            "reasons": [f"ни один архетип не набрал порог {MIN_SCORE}"],
            "implemented": False,
            "runner_up": None,
        }

    confidence = "high" if best_score >= 4 else "medium" if best_score >= 3 else "low"
    return {
        "family_name": features.family_name,
        "archetype": best_name,
        "score": round(best_score, 2),
        "confidence": confidence,
        "reasons": best_reasons,
        "implemented": best_name in geometry_lib.ARCHETYPES,
        "runner_up": (runner[1], round(runner[0], 2)) if runner and runner[0] > 0 else None,
    }


@dataclass
class _Bucket:
    count: int = 0
    examples: list[str] = field(default_factory=list)

    def add(self, family_name: str) -> None:
        self.count += 1
        if len(self.examples) < 5:
            self.examples.append(family_name)


def coverage_report(catalogs: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate classifications over a corpus into a prioritized coverage report."""
    buckets: dict[str, _Bucket] = {}
    classifications = []
    for catalog in catalogs:
        result = classify(extract_features(catalog))
        classifications.append(result)
        buckets.setdefault(result["archetype"], _Bucket()).add(result["family_name"])

    total = len(catalogs) or 1
    rows = []
    for archetype, bucket in buckets.items():
        rows.append({
            "archetype": archetype,
            "count": bucket.count,
            "share": round(bucket.count / total, 3),
            "implemented": archetype in geometry_lib.ARCHETYPES,
            "examples": bucket.examples,
        })
    # Rank by count desc, then name; `unknown` always last.
    rows.sort(key=lambda r: (r["archetype"] == "unknown", -r["count"], r["archetype"]))

    write_first = [
        r["archetype"] for r in rows
        if not r["implemented"] and r["archetype"] != "unknown"
    ]
    return {
        "total_families": len(catalogs),
        "ranking": rows,
        "write_first": write_first,
        "classifications": classifications,
    }


def _load_catalogs(patterns: list[str]) -> list[dict[str, Any]]:
    catalogs: list[dict[str, Any]] = []
    for pattern in patterns:
        for path in sorted(glob.glob(pattern, recursive=True)):
            try:
                catalogs.append(json.loads(Path(path).read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
    return catalogs


def _render_report(report: dict[str, Any]) -> str:
    lines = [f"Семейств в корпусе: {report['total_families']}", "", "Покрытие архетипами:"]
    for row in report["ranking"]:
        mark = "✓" if row["implemented"] else ("·" if row["archetype"] == "unknown" else "todo")
        lines.append(
            f"  [{mark:>4}] {row['archetype']:<18} {row['count']:>4}  "
            f"({row['share'] * 100:>4.0f}%)  напр.: {', '.join(row['examples'][:3])}"
        )
    lines.append("")
    lines.append("Писать первыми (по покрытию, ещё не реализованы):")
    lines.append("  " + (", ".join(report["write_first"]) or "— все покрытые архетипы уже реализованы"))
    return "\n".join(lines)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify extracted Revit families into candidate archetypes and rank coverage (W10.2).")
    parser.add_argument("globs", nargs="+", help="Glob(s) of artel.revit_family_catalog.v1 JSON extracts.")
    parser.add_argument("--json", action="store_true", help="Emit the full report as JSON.")
    args = parser.parse_args(argv)

    catalogs = _load_catalogs(args.globs)
    report = coverage_report(catalogs)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render_report(report))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
