"""The committed ARTEL conformance plans must equal a fresh compile of their
inputs — so the golden contract for the standalone C# port never drifts from the
Python reference oracle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import artel_family_action_plan as compiler

ROOT = Path(__file__).resolve().parent.parent / "products" / "artel" / "conformance"
INPUTS = ROOT / "inputs"


def _compile(geometry: bool) -> dict:
    spec = json.loads((INPUTS / "shkaf.spec.json").read_text(encoding="utf-8"))
    fop = compiler.build_fop_index((INPUTS / "fop_reference.txt").read_text(encoding="utf-8"))
    recipe = (
        json.loads((INPUTS / "shkaf.geometry.json").read_text(encoding="utf-8"))
        if geometry else None
    )
    return compiler.compile_action_plan(spec, fop, recipe)


@pytest.mark.parametrize("name, geometry", [
    ("shkaf_base.plan.json", False),
    ("shkaf_geometry.plan.json", True),
])
def test_conformance_plan_matches_oracle(name, geometry):
    expected = json.loads((ROOT / "expected" / name).read_text(encoding="utf-8"))
    plan = _compile(geometry)
    assert plan == expected, f"{name} drifted from the compiler; regenerate per conformance/README.md"
    assert plan["status"] == "ok"
    compiler.validate_plan(plan)  # schema-valid, the C# port's target
