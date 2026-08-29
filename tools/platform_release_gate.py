#!/usr/bin/env python3
"""Portable macOS/Windows CI gate without relying on GNU Make on Windows."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_PACKAGES = (
    "backend",
    "proxy",
    "sovushka",
    "tools",
    "sovushka_ng.py",
    "proxy_server.py",
    "mlx_host.py",
)

MODEL_CONNECTION_BEHAVIOR_TESTS = (
    "tests/test_candidate_acceptance_service.py",
    "tests/test_canonical_promotion_service.py",
    "tests/test_canonical_route_service.py",
    "tests/test_les_runtime_control.py",
    "tests/test_live_workbook_acceptance_contract.py",
    "tests/test_model_capability_service.py",
    "tests/test_model_connection_chat_integration.py",
    "tests/test_model_connection_embeddings_integration.py",
    "tests/test_model_connection_live_acceptance.py",
    "tests/test_model_connection_registry_service.py",
    "tests/test_model_connection_resolver_service.py",
    "tests/test_model_connection_security_service.py",
    "tests/test_model_connections_router.py",
    "tests/test_model_engine_extension_service.py",
    "tests/test_model_preset_workflow_parity.py",
    "tests/test_model_secret_service.py",
    "tests/test_openai_compatible_transport_service.py",
    "tests/test_sovushka_model_connections.py",
)

PORTABLE_BEHAVIOR_TESTS = (
    "tests/test_answer_contract_service.py",
    "tests/test_candidate_selection_service.py",
    "tests/test_evidence_contract.py",
    "tests/test_numeric_provenance.py",
    "tests/test_publication_check.py",
    "tests/test_query_router.py",
    "tests/test_smeta_resource_normalizer.py",
    "tests/test_smeta_structured_base.py",
    "tests/test_smeta_norm_browser.py",
    "tests/test_smeta_rerank_ab_probe.py",
    "tests/test_fgis_full_update.py",
    "tests/test_smeta_release_baseline.py",
    "tests/test_qdrant_collection_layout.py",
    "tests/test_datasets_router.py",
    "tests/test_rag_config.py",
    "tests/test_document_explorer_service.py",
    "tests/test_process_status.py",
    "tests/test_basic_function_smoke.py",
    "tests/test_static_assets.py",
    "tests/test_file_viewer_service.py",
    "tests/test_list_office_service.py",
    "tests/test_list_office_agent_service.py",
    "tests/test_pdf_contour_service.py",
    "tests/test_memory_core.py",
    "tests/test_memory_api.py",
    "tests/test_memory_ui_contract.py",
    "tests/test_smeta_memory_isolation.py",
    "tests/test_parent_card_hydration_service.py",
    "tests/test_document_object_model.py",
    "tests/test_spreadsheet_object_model.py",
    "tests/test_chat_mail_query.py",
    "tests/test_mail_ingest.py",
    "tests/test_mail_registry_service.py",
    "tests/test_outlook_mail_poller.py",
    "tests/test_asbuilt_intake.py",
    "tests/test_software_versions.py",
    "tests/test_test_profiles.py",
    "tests/test_tauri_desktop.py",
    *MODEL_CONNECTION_BEHAVIOR_TESTS,
)
WINDOWS_BEHAVIOR_TESTS = (
    "tests/test_installer_windows.py",
    "tests/test_install_profile_env.py",
    "tests/test_parse_admission_windows.py",
)
UPDATER_BEHAVIOR_TESTS = (
    "tests/test_release_classification.py",
    "tests/test_github_patch_release.py",
    "tests/test_patch_release.py",
    "tests/test_vps_patch.py",
    "tests/test_windows_application_update.py",
    "tests/test_windows_update_shell.py",
    "tests/test_update_service.py",
    "tests/test_manual_update_ui.py",
    "tests/test_mac_update.py",
)
UPDATER_COMPILE_TARGETS = (
    "tools/windows_runtime.py",
    "tools/windows_update_engine.py",
    "tools/vps_patch.py",
    "tools/vps_patch_apply.py",
    "tools/windows_update_shell.py",
    "tools/mac_update.py",
    "tools/mac_update_apply.py",
    "proxy/services/update_service.py",
    "proxy/routers/updates.py",
    "sovushka/components/header.py",
    "tools/release_classification.py",
    "tools/github_patch_release.py",
)
CURRENT_LES_TESTS = tuple(
    sorted(
        {
            *MODEL_CONNECTION_BEHAVIOR_TESTS,
            "tests/test_answer_contract_service.py",
            "tests/test_build_rag_contract_sibling.py",
            "tests/test_candidate_selection_service.py",
            "tests/test_datasets_router.py",
            "tests/test_document_explorer_service.py",
            "tests/test_evidence_contract.py",
            "tests/test_evidence_packet_service.py",
            "tests/test_memory_core.py",
            "tests/test_memory_api.py",
            "tests/test_memory_ui_contract.py",
            "tests/test_smeta_memory_isolation.py",
            "tests/test_fgis_full_update.py",
            "tests/test_numeric_provenance.py",
            "tests/test_notebook_study_service.py",
            "tests/test_process_status.py",
            "tests/test_publication_check.py",
            "tests/test_qdrant_adapter_parse.py",
            "tests/test_qdrant_collection_layout.py",
            "tests/test_query_router.py",
            "tests/test_rag_config.py",
            "tests/test_rag_golden_set.py",
            "tests/test_rag_hierarchy.py",
            "tests/test_rag_index_contract_audit.py",
            "tests/test_rag_rrf_readiness.py",
            "tests/test_retrieval_quality_service.py",
            "tests/test_retrieval_service.py",
            "tests/test_rim_agent_turn.py",
            "tests/test_rim_api.py",
            "tests/test_rim_scenarios.py",
            "tests/test_rim_session.py",
            "tests/test_saferag_service.py",
            "tests/test_smeta_application_boundary.py",
            "tests/test_smeta_norm_browser.py",
            "tests/test_smeta_release_baseline.py",
            "tests/test_smeta_rerank_ab_probe.py",
            "tests/test_smeta_resource_normalizer.py",
            "tests/test_smeta_structured_base.py",
            "tests/test_software_versions.py",
            "tests/test_source_excerpts.py",
            "tests/test_system_dataset_service.py",
            "tests/test_test_profiles.py",
        }
    )
)
MACOS_BEHAVIOR_TESTS = (
    "tests/test_installer_macos.py",
    "tests/test_runtime_plist_drift.py",
    "tests/test_les_runtime_control.py",
)


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def workspace_temporary_root() -> Path:
    root = ROOT / ".codex_tmp"
    root.mkdir(exist_ok=True)
    return root


def verify_windows_mail_collector() -> None:
    if not sys.platform.startswith("win"):
        return
    windows_root = Path(os.environ.get("WINDIR", r"C:\Windows"))
    compiler_candidates = (
        windows_root / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe",
        windows_root / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe",
    )
    compiler = next((path for path in compiler_candidates if path.is_file()), None)
    if compiler is None:
        raise RuntimeError(".NET Framework csc.exe is required for the Outlook collector gate")
    source = ROOT / "clients" / "outlook_mail_poller" / "LesMailPoller.cs"
    with tempfile.TemporaryDirectory(
        prefix="les-mail-gate-", dir=workspace_temporary_root()
    ) as temporary:
        state_root = Path(temporary) / "state"
        binary = Path(temporary) / "LesMailPoller.exe"
        run(
            [
                str(compiler),
                "/nologo",
                "/target:winexe",
                f"/out:{binary}",
                "/r:System.dll",
                "/r:System.Core.dll",
                "/r:Microsoft.CSharp.dll",
                str(source),
            ]
        )
        environment = os.environ.copy()
        environment["LES_MAIL_STATE_ROOT"] = str(state_root)
        subprocess.run(
            [str(binary), "--self-test-cursor"],
            cwd=ROOT,
            env=environment,
            check=True,
        )


def verify() -> None:
    run(["uv", "run", "python", "tools/sync_version_contract.py", "--check"])
    run(["uv", "run", "python", "-m", "compileall", "-q", *PYTHON_PACKAGES])
    with tempfile.TemporaryDirectory(
        prefix="pytest-collect-", dir=workspace_temporary_root()
    ) as base:
        run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "--basetemp",
                base,
            ]
        )
    verify_windows_mail_collector()


def test() -> None:
    platform_tests = (
        WINDOWS_BEHAVIOR_TESTS
        if sys.platform.startswith("win")
        else MACOS_BEHAVIOR_TESTS
    )
    with tempfile.TemporaryDirectory(
        prefix="pytest-platform-", dir=workspace_temporary_root()
    ) as base:
        run(
            [
                "uv", "run", "python", "-m", "pytest", "-q", "--durations=20",
                "--basetemp", base,
                *PORTABLE_BEHAVIOR_TESTS,
                *platform_tests,
            ]
        )
    run(
        [
            "uv", "run", "python", "-m", "tools.smeta_release_baseline",
            "verify-root", "--root", ".",
        ]
    )


def updater() -> None:
    run(["uv", "run", "python", "tools/sync_version_contract.py", "--check"])
    run(["uv", "run", "python", "-m", "py_compile", *UPDATER_COMPILE_TARGETS])
    with tempfile.TemporaryDirectory(
        prefix="pytest-updater-", dir=workspace_temporary_root()
    ) as base:
        run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "pytest",
                "-q",
                "--basetemp",
                base,
                *UPDATER_BEHAVIOR_TESTS,
            ]
        )


def current(*, collect_only: bool) -> None:
    run(["uv", "run", "python", "tools/sync_version_contract.py", "--check"])
    run(["uv", "run", "python", "-m", "compileall", "-q", *PYTHON_PACKAGES])
    phase = "collect" if collect_only else "test"
    with tempfile.TemporaryDirectory(
        prefix=f"pytest-current-{phase}-", dir=workspace_temporary_root()
    ) as base:
        pytest_args = ["--collect-only", "-q"] if collect_only else ["-q", "--durations=20"]
        run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "pytest",
                *pytest_args,
                "--basetemp",
                base,
                *CURRENT_LES_TESTS,
            ]
        )


def build() -> None:
    tauri = ROOT / "desktop" / "tauri"
    npm = shutil.which("npm.cmd" if sys.platform.startswith("win") else "npm")
    if not npm:
        raise RuntimeError("npm is required for the native platform build")
    run([npm, "ci"], cwd=tauri)
    run([npm, "run", "tauri", "--", "build", "--no-bundle"], cwd=tauri)
    binary = (
        tauri / "src-tauri" / "target" / "release"
        / ("les-desktop.exe" if sys.platform.startswith("win") else "les-desktop")
    )
    if not binary.is_file() or binary.stat().st_size <= 0:
        raise RuntimeError(f"native Tauri binary is missing: {binary}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=("verify", "test", "current-verify", "current-test", "updater", "build"),
    )
    args = parser.parse_args(argv)
    phases = {
        "verify": verify,
        "test": test,
        "current-verify": lambda: current(collect_only=True),
        "current-test": lambda: current(collect_only=False),
        "updater": updater,
        "build": build,
    }
    phases[args.phase]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
