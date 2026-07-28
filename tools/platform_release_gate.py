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
    "tests/test_chat_mail_query.py",
    "tests/test_mail_ingest.py",
    "tests/test_mail_registry_service.py",
    "tests/test_outlook_mail_poller.py",
    "tests/test_asbuilt_intake.py",
    "tests/test_software_versions.py",
    "tests/test_test_profiles.py",
    "tests/test_tauri_desktop.py",
)
WINDOWS_BEHAVIOR_TESTS = (
    "tests/test_installer_windows.py",
    "tests/test_install_profile_env.py",
    "tests/test_parse_admission_windows.py",
)
MACOS_BEHAVIOR_TESTS = (
    "tests/test_installer_macos.py",
    "tests/test_runtime_plist_drift.py",
    "tests/test_les_runtime_control.py",
)


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    subprocess.run(command, cwd=cwd, check=True)


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
    with tempfile.TemporaryDirectory(prefix="les-mail-gate-") as temporary:
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
    run(["uv", "run", "python", "-m", "pytest", "--collect-only", "-q"])
    verify_windows_mail_collector()


def test() -> None:
    platform_tests = (
        WINDOWS_BEHAVIOR_TESTS
        if sys.platform.startswith("win")
        else MACOS_BEHAVIOR_TESTS
    )
    run(
        [
            "uv", "run", "python", "-m", "pytest", "-q", "--durations=20",
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
    parser.add_argument("phase", choices=("verify", "test", "build"))
    args = parser.parse_args(argv)
    {"verify": verify, "test": test, "build": build}[args.phase]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
