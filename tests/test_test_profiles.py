from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _dry_make(target: str) -> str:
    completed = subprocess.run(
        ["make", "-n", target],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_default_les_suite_excludes_historical_harness_and_artel() -> None:
    for target in ("verify", "test", "test-release", "test-architecture"):
        command = _dry_make(target)
        assert "--ignore=tests/test_construction_harness.py" in command
        assert "--ignore=tests/test_unified_real_v11.py" in command
        assert "--ignore=tests/test_artel_fop_profile.py" in command


def test_historical_harness_has_explicit_opt_in_profile() -> None:
    command = _dry_make("test-legacy")

    assert "tests/test_construction_harness.py" in command
    assert "tests/test_unified_real_v11.py" in command
    assert "--ignore=" not in command
    assert "-o addopts=" in command


def test_raw_pytest_defaults_to_current_les_collection() -> None:
    config = (ROOT / "pytest.ini").read_text(encoding="utf-8")

    assert "--ignore=tests/test_construction_harness.py" in config
    assert "--ignore=tests/test_unified_real_v11.py" in config
    assert "--ignore-glob=tests/test_artel*.py" in config
