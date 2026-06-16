"""The committed ARTEL conformance plans must equal a fresh compile of their
inputs — so the golden contract for the standalone C# port never drifts from the
Python reference oracle.

Each case: an input spec (+ optional geometry recipe) compiled against the shared
FOP reference must reproduce the committed expected plan byte-for-byte.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import artel_family_action_plan as compiler

ROOT = Path(__file__).resolve().parent.parent / "products" / "artel" / "conformance"
INPUTS = ROOT / "inputs"

# (expected file, spec file, geometry file or None)
CASES = [
    ("shkaf_base.plan.json", "shkaf.spec.json", None),
    ("shkaf_geometry.plan.json", "shkaf.spec.json", "shkaf.geometry.json"),
    ("column_geometry.plan.json", "column.spec.json", "column.geometry.json"),
    ("beam_geometry.plan.json", "beam.spec.json", "beam.geometry.json"),
    # Реальное изделие из техлиста KORF MPU: вентустановка-короб с 7 типоразмерами.
    ("mpu_geometry.plan.json", "mpu.spec.json", "mpu.geometry.json"),
]


def _compile(spec_file: str, geometry_file: str | None) -> dict:
    spec = json.loads((INPUTS / spec_file).read_text(encoding="utf-8"))
    fop = compiler.build_fop_index((INPUTS / "fop_reference.txt").read_text(encoding="utf-8"))
    recipe = (
        json.loads((INPUTS / geometry_file).read_text(encoding="utf-8"))
        if geometry_file else None
    )
    return compiler.compile_action_plan(spec, fop, recipe)


@pytest.mark.parametrize("expected_file, spec_file, geometry_file", CASES)
def test_conformance_plan_matches_oracle(expected_file, spec_file, geometry_file):
    expected = json.loads((ROOT / "expected" / expected_file).read_text(encoding="utf-8"))
    plan = _compile(spec_file, geometry_file)
    assert plan == expected, f"{expected_file} drifted from the compiler; regenerate per conformance/README.md"
    assert plan["status"] == "ok"
    compiler.validate_plan(plan)  # schema-valid, the C# port's target
