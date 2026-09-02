from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tools import build_tauri_app, release_classification, vps_patch_apply
from tools.windows_update_engine import PERSISTENT_NAMES, validate_boundary


ROOT = Path(__file__).resolve().parents[1]

FAILURE_PROOFS = {
    "dataset_parse_resume": (
        "tests/test_parse_resume.py",
        "test_metadb_requeues_interrupted_and_due_retryable_errors",
    ),
    "general_rag_atomic_progress": (
        "tests/test_build_rag_contract_sibling.py",
        "test_progress_json_is_atomic_and_invalid_state_fails_empty",
    ),
    "general_rag_alias_rollback": (
        "tests/test_activate_qdrant_generation.py",
        "test_activation_rollback_clears_new_alias_fts_when_no_previous_generation",
    ),
    "smeta_readiness_before_switch": (
        "tests/test_smeta_generation_coordinator.py",
        "test_generation_coordinator_keeps_active_base_when_readiness_is_blocked",
    ),
    "smeta_concurrent_update": (
        "tests/test_smeta_generation_coordinator.py",
        "test_generation_coordinator_refuses_to_build_while_an_update_lease_is_held",
    ),
    "smeta_interrupted_switch": (
        "tests/test_smeta_generation_reconciliation_service.py",
        "test_reconciler_repairs_exact_saved_metadata_after_interrupted_file_switch",
    ),
    "smeta_corrupt_recovery": (
        "tests/test_smeta_generation_reconciliation_service.py",
        "test_reconciler_blocks_corrupt_saved_metadata_without_overwriting_active_files",
    ),
    "baseline_repair_backup": (
        "tests/test_smeta_release_baseline.py",
        "test_release_baseline_repair_backs_up_partial_state_and_restores_complete_set",
    ),
    "soft_update_locked_file": (
        "tests/test_windows_application_update.py",
        "test_windows_updater_rolls_back_runtime_when_desktop_replace_is_locked",
    ),
    "hard_update_preserves_state": (
        "tests/test_windows_application_update.py",
        "test_hard_update_replaces_complete_application_tree_and_keeps_state",
    ),
    "soft_rollback_failure": (
        "tests/test_windows_application_update.py",
        "test_failed_soft_rollback_restores_the_accepted_candidate",
    ),
    "hard_rollback_failure": (
        "tests/test_windows_application_update.py",
        "test_failed_hard_rollback_restores_the_accepted_candidate",
    ),
}


def _test_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


@pytest.mark.parametrize(("scenario", "proof"), FAILURE_PROOFS.items())
def test_every_update_failure_scenario_keeps_an_executable_proof(scenario, proof):
    relative, test_name = proof
    assert test_name in _test_functions(ROOT / relative), scenario


def test_database_state_roots_are_identical_across_full_and_soft_update_contracts():
    expected = {name.casefold() for name in PERSISTENT_NAMES}
    assert build_tauri_app.PERSISTENT_RUNTIME_ROOTS == expected
    assert release_classification.PERSISTENT_RUNTIME_ROOTS == expected
    for name in PERSISTENT_NAMES:
        with pytest.raises(RuntimeError, match="allowlist|unsupported"):
            vps_patch_apply.safe_relative_path(f"{name}/sentinel.db")


def test_hard_update_rejects_state_on_either_side_of_application_boundary(tmp_path):
    install = tmp_path / "Programs" / "LES"
    nested_state = install / "data" / "LES"
    with pytest.raises(RuntimeError, match="disjoint"):
        validate_boundary(install, nested_state)

    state = tmp_path / "UserState" / "LES"
    nested_install = state / "Programs" / "LES"
    with pytest.raises(RuntimeError, match="disjoint"):
        validate_boundary(nested_install, state)


def test_failure_matrix_and_general_activation_proofs_are_in_release_gates():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "tests/test_update_resilience_matrix.py" in makefile
    assert "tests/test_activate_qdrant_generation.py" in makefile
