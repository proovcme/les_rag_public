from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tools import platform_release_gate


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    shutil.which("make") is None,
    reason="Makefile profiles are checked on Unix runners",
)


def _dry_make(target: str) -> str:
    completed = subprocess.run(
        ["make", "-n", target],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_current_les_gate_is_explicit_and_does_not_collect_the_old_full_suite() -> None:
    for target in ("verify", "test", "test-release", "test-architecture"):
        command = _dry_make(target)
        assert "tests/test_rim_session.py" in command
        assert "tests/test_rag_hierarchy.py" in command
        assert "tests/test_evidence_contract.py" in command
        assert "testpaths" not in command


def test_historical_harness_has_explicit_opt_in_profile() -> None:
    command = _dry_make("test-legacy")

    assert "tests/test_construction_harness.py" in command
    assert "tests/test_unified_real_v11.py" in command
    assert "--ignore=" not in command
    assert "-o addopts=" in command


def test_previous_full_suite_is_legacy_opt_in_only() -> None:
    command = _dry_make("test-legacy-full")

    assert "python -m pytest -o addopts=" in command
    assert "--ignore=tests/test_construction_harness.py" in command
    assert "--ignore=tests/test_artel_fop_profile.py" in command


def test_unit_and_integration_profiles_are_explicit_and_behavioral() -> None:
    unit = _dry_make("test-unit")
    integration = _dry_make("test-integration")

    assert "tests/test_candidate_selection_service.py" in unit
    assert "tests/test_numeric_provenance.py" in unit
    assert "tests/test_smeta_resource_normalizer.py" in unit
    assert "tests/test_smeta_structured_base.py" in integration
    assert "tests/test_smeta_release_baseline.py" in integration


def test_release_profile_requires_real_active_artifact_smoke() -> None:
    command = _dry_make("test-release")

    assert "tools.smeta_release_baseline verify-root --root ." in command
    assert "tests/test_rim_session.py" in command


def test_ship_profiles_require_active_artifact_and_live_runtime_smokes() -> None:
    for target in ("ship-check", "ship-full-check"):
        command = _dry_make(target)
        assert "tools.smeta_release_baseline verify-root --root ." in command
        assert "tools.smeta_rerank_ab_probe --require-ok" in command
        assert "tools/basic_function_smoke.py --release" in command


def test_raw_pytest_defaults_to_current_les_collection() -> None:
    config = (ROOT / "pytest.ini").read_text(encoding="utf-8")

    assert "--ignore=tests/test_construction_harness.py" in config
    assert "--ignore=tests/test_unified_real_v11.py" in config
    assert "--ignore-glob=tests/test_artel*.py" in config


def test_platform_gate_is_behavioral_and_platform_specific() -> None:
    portable = set(platform_release_gate.PORTABLE_BEHAVIOR_TESTS)
    windows = set(platform_release_gate.WINDOWS_BEHAVIOR_TESTS)
    macos = set(platform_release_gate.MACOS_BEHAVIOR_TESTS)

    assert "tests/test_evidence_contract.py" in portable
    assert "tests/test_smeta_release_baseline.py" in portable
    assert "tests/test_basic_function_smoke.py" in portable
    assert "tests/test_static_assets.py" in portable
    assert "tests/test_installer_windows.py" in windows
    assert "tests/test_parse_admission_windows.py" in windows
    assert "tests/test_installer_macos.py" in macos
    assert windows.isdisjoint(macos)
