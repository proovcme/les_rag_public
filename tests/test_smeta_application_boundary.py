from pathlib import Path

from proxy.smeta_core import application
from proxy.smeta_core.unit_contract import measure_units_compatible, norm_measure


ROOT = Path(__file__).resolve().parents[1]


def test_dead_workflow_compatibility_runners_are_removed():
    from proxy.smeta_core import workflow

    assert not hasattr(application, "run_smeta_workflow")
    assert not hasattr(workflow, "run_smeta_workflow")


def test_all_production_smeta_entrypoints_use_application_facade():
    violations = []
    for path in (ROOT / "proxy").rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        if rel != "proxy/smeta_core/application.py":
            if "from proxy.services.estimate_harness_service import run_estimate_harness" in text:
                violations.append((rel, "direct legacy runner"))
            if "from proxy.smeta_core.workflow import run_smeta_workflow" in text:
                violations.append((rel, "compatibility workflow used as application"))
            if "from proxy.smeta_core.workflow import calculate_visible_rows" in text:
                violations.append((rel, "calculation bypasses application"))
        if rel == "proxy/services/construction_harness_service.py":
            assert "estimate_harness_service" not in text
            assert "LEGACY_PRIVATE = True" in text
    assert violations == []


def test_shared_measure_contract_handles_compound_norm_measures():
    assert norm_measure("100 м труб") == (100.0, "м труб")
    assert measure_units_compatible("м", "100 м труб")
    assert norm_measure("100 м2") == (100.0, "м2")
    assert not measure_units_compatible("м3", "100 м2")
