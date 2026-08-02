#!/usr/bin/env python3
"""Unified Test Runner for LES_v2 (tools/test_runner.py).

Supports 5 standardized modes:
  - all      : Run all canonical test suites
  - unit     : Run unit test suite only
  - smoke    : Run offline smoke test suite
  - coverage : Run tests with line execution coverage report
  - ci       : Run tests with JUnit XML export for CI pipeline

Usage:
  uv run python tools/test_runner.py unit
  uv run python tools/test_runner.py smoke
  uv run python tools/test_runner.py coverage
  uv run python tools/test_runner.py ci
  uv run python tools/test_runner.py all
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import trace


UNIT_TEST_FILES = [
    "tests/test_unit_core_business.py",
    "tests/test_answer_contract_service.py",
    "tests/test_candidate_selection_service.py",
    "tests/test_evidence_contract.py",
    "tests/test_numeric_provenance.py",
    "tests/test_publication_check.py",
    "tests/test_query_router.py",
    "tests/test_smeta_resource_normalizer.py",
]

SMOKE_TEST_FILES = [
    "tests/test_smoke_offline.py",
]

CANONICAL_TEST_FILES = [
    *UNIT_TEST_FILES,
    *SMOKE_TEST_FILES,
    "tests/test_version_service_v19.py",
    "tests/test_v020_deploy_stamp_ui.py",
    "tests/test_scope_model_v21.py",
    "tests/test_rag_config.py",
    "tests/test_rag_hierarchy.py",
]


def run_pytest(args: list[str]) -> tuple[int, str, float]:
    """Execute pytest with provided CLI arguments."""
    os.makedirs("tmp/pytest_temp", exist_ok=True)
    cmd = [sys.executable, "-m", "pytest", "--basetemp=tmp/pytest_temp", *args]
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True)
    duration = time.time() - t0
    output = res.stdout + ("\n" + res.stderr if res.stderr else "")
    return res.returncode, output, duration


def mode_unit() -> int:
    print("=== [TEST RUNNER] Running Unit Tests ===")
    code, output, duration = run_pytest(["-q", *UNIT_TEST_FILES])
    print(output)
    print(f"[TEST RUNNER] Unit tests duration: {duration:.2f}s | Exit code: {code}")
    return code


def mode_smoke() -> int:
    print("=== [TEST RUNNER] Running Offline Smoke Tests ===")
    code, output, duration = run_pytest(["-v", *SMOKE_TEST_FILES])
    print(output)
    print(f"[TEST RUNNER] Smoke tests duration: {duration:.2f}s | Exit code: {code}")
    return code


def mode_ci() -> int:
    print("=== [TEST RUNNER] Running CI Tests with JUnit XML Export ===")
    os.makedirs("artifacts", exist_ok=True)
    xml_path = "artifacts/junit-report.xml"
    code, output, duration = run_pytest(["-v", f"--junitxml={xml_path}", *CANONICAL_TEST_FILES])
    print(output)
    print(f"[TEST RUNNER] CI tests duration: {duration:.2f}s | JUnit report saved to: {xml_path}")
    return code


def mode_coverage() -> int:
    print("=== [TEST RUNNER] Running Tests with Coverage Report ===")
    os.makedirs("artifacts", exist_ok=True)
    os.makedirs("tmp/pytest_temp", exist_ok=True)
    report_file = "artifacts/coverage_report.txt"
    json_file = "artifacts/coverage.json"

    import pytest

    tracer = trace.Trace(
        count=1,
        trace=0,
        ignoredirs=[sys.prefix, sys.exec_prefix],
    )

    t0 = time.time()
    # Run pytest suite in-process inside tracer to capture line execution
    exit_code = tracer.runfunc(pytest.main, ["--basetemp=tmp/pytest_temp", "-q", *UNIT_TEST_FILES])
    duration = time.time() - t0

    r = tracer.results()
    recorded_counts = r.counts

    # Filter counts to project directory
    project_root = os.path.abspath(".")
    covered_files: dict[str, int] = {}
    total_lines_executed = 0

    for (filename, lineno), count in recorded_counts.items():
        rel_path = os.path.relpath(filename, project_root)
        if (
            filename.startswith(project_root)
            and ".venv" not in rel_path
            and "tests" not in rel_path
            and "tmp" not in rel_path
        ):
            covered_files[rel_path] = covered_files.get(rel_path, 0) + count
            total_lines_executed += count

    lines = [
        "Coverage Summary Report (LES_v2)",
        "================================",
        f"Duration: {duration:.2f}s",
        f"Exit Code: {exit_code}",
        f"Total Executed Line Counts: {total_lines_executed}",
        f"Covered Project Files ({len(covered_files)}):",
    ]
    for fpath, cnt in sorted(covered_files.items()):
        lines.append(f"  - {fpath}: {cnt} line executions")

    summary_text = "\n".join(lines) + "\n"

    with open(report_file, "w", encoding="utf-8") as f:
        f.write(summary_text)

    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "total_lines_executed": total_lines_executed,
                "covered_files_count": len(covered_files),
                "covered_files": covered_files,
                "duration_s": round(duration, 2),
                "exit_code": exit_code,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(summary_text)
    print(f"[TEST RUNNER] Coverage report written to {report_file} and {json_file}")
    return exit_code


def mode_all() -> int:
    print("=== [TEST RUNNER] Running All Canonical Tests ===")
    code, output, duration = run_pytest(["-q", "--durations=10", *CANONICAL_TEST_FILES])
    print(output)
    print(f"[TEST RUNNER] All tests duration: {duration:.2f}s | Exit code: {code}")
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="LES_v2 Unified Test Runner")
    parser.add_argument(
        "mode",
        nargs="?",
        default="all",
        choices=["all", "unit", "smoke", "coverage", "ci"],
        help="Test execution mode",
    )
    args = parser.parse_args()

    if args.mode == "unit":
        return mode_unit()
    elif args.mode == "smoke":
        return mode_smoke()
    elif args.mode == "coverage":
        return mode_coverage()
    elif args.mode == "ci":
        return mode_ci()
    else:
        return mode_all()


if __name__ == "__main__":
    sys.exit(main())
