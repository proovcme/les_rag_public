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


def _dry_make_with_variable(target: str, name: str, value: str) -> str:
    completed = subprocess.run(
        ["make", "-n", target, f"{name}={value}"],
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
        assert "tests/test_model_connection_registry_service.py" in command
        assert "tests/test_model_engine_extension_service.py" in command
        assert "tests/test_canonical_promotion_service.py" in command
        assert "tests/test_les_runtime_control.py" in command
        assert "testpaths" not in command


def test_canonical_pytest_profiles_use_workspace_local_temp() -> None:
    for target in (
        "verify", "test", "test-unit", "test-integration", "test-focused",
        "test-legacy", "test-legacy-full", "test-rag-core", "test-mail",
    ):
        command = _dry_make(target)
        assert "mkdir -p .test-tmp" in command
        assert "--basetemp=.test-tmp/" in command
        assert "%TEMP%" not in command


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


def test_ship_preflight_requires_active_artifacts_without_candidate_live_smoke() -> None:
    for target in ("ship-check", "ship-full-check"):
        command = _dry_make(target)
        assert "tools.smeta_release_baseline verify-root --root ." in command
        assert "golden/general_native_rrf_release_smoke.json --require-native-rrf" not in command
        assert "tools.smeta_rerank_ab_probe --require-ok" not in command
        assert "tools/basic_function_smoke.py --release" not in command


def test_ship_runs_native_rrf_smoke_only_after_candidate_deploy() -> None:
    for target in ("ship", "ship-full"):
        command = _dry_make(target)
        deploy = command.index("tools.deploy_to_runtime --apply --restart")
        native_rrf = command.index(
            "golden/general_native_rrf_release_smoke.json --require-native-rrf"
        )
        basic = command.index("tools/basic_function_smoke.py --release")

        assert deploy < native_rrf
        assert deploy < basic
        assert "post-deploy native-RRF smoke attempt" in command


def test_deploy_runtime_can_force_only_explicitly_reviewed_files() -> None:
    command = _dry_make_with_variable(
        "deploy-runtime",
        "DEPLOY_FORCE_FILES",
        "config/version.json",
    )

    forced = command.index("--apply --force --files config/version.json")
    regular = command.index("tools.deploy_to_runtime --apply --restart")
    assert forced < regular


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


def test_windows_portable_current_gate_matches_core_make_profile() -> None:
    current = set(platform_release_gate.CURRENT_LES_TESTS)

    assert "tests/test_rim_session.py" in current
    assert "tests/test_rag_hierarchy.py" in current
    assert "tests/test_evidence_contract.py" in current
    assert "tests/test_test_profiles.py" in current
    assert "tests/test_model_connection_registry_service.py" in current
    assert "tests/test_model_engine_extension_service.py" in current
    assert "tests/test_canonical_promotion_service.py" in current
    assert not any("unified_" in test for test in current)


def test_github_patch_release_target_never_calls_full_installer_builder() -> None:
    command = _dry_make_with_variable(
        "github-patch-release",
        "GITHUB_PATCH_RELEASE_ARGS",
        "--base base --target target --output out --full-feed latest.json",
    )

    assert "tools/github_patch_release.py" in command
    assert "tools/patch_release.py" not in command
    assert "LES-Setup.exe" not in command


def test_model_connection_live_acceptance_is_explicit_opt_in() -> None:
    live = _dry_make_with_variable(
        "test-model-connections-live",
        "MODEL_CONNECTION_LIVE_ARGS",
        "--revision-9b conn:qwen:r2 --out receipt.json",
    )
    ordinary = _dry_make("test")

    assert "tools/model_connection_live_acceptance.py" in live
    assert "--revision-9b conn:qwen:r2 --out receipt.json" in live
    assert "tools/model_connection_live_acceptance.py" not in ordinary


def test_tauri_compile_profile_uses_portable_cargo_lookup() -> None:
    command = _dry_make("test-tauri")

    assert "cargo check" in command
    assert "/.cargo/bin/cargo" not in command
