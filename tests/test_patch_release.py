from __future__ import annotations

import json
import base64
import sys
from pathlib import Path

import pytest

from tools import patch_release


ROOT = Path(__file__).resolve().parents[1]


def test_release_command_tolerates_non_utf8_windows_diagnostics():
    completed = patch_release.run(
        [
            sys.executable,
            "-c",
            "import os; os.write(1, b'{\\\"ok\\\":true}\\n'); os.write(2, b'\\x8f')",
        ],
        capture=True,
    )

    assert json.loads(completed.stdout)["ok"] is True
    assert "\ufffd" in completed.stderr


def test_patch_release_contract_separates_product_and_build(tmp_path):
    contract = tmp_path / "version.json"
    contract.write_text(
        json.dumps(
            {
                "product_version": "1.2.3",
                "build_number": 44,
                "desktop_version": "5.1.44",
            }
        ),
        encoding="utf-8",
    )

    assert patch_release.load_contract(contract)["product_version"] == "1.2.3"


@pytest.mark.parametrize(
    ("product", "build", "desktop"),
    (("1.2", 44, "5.1.44"), ("1.2.3.4", 44, "5.1.44"), ("1.2.3", 44, "5.1.45")),
)
def test_patch_release_rejects_ambiguous_version_contract(tmp_path, product, build, desktop):
    contract = tmp_path / "version.json"
    contract.write_text(
        json.dumps(
            {"product_version": product, "build_number": build, "desktop_version": desktop}
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError):
        patch_release.load_contract(contract)


def test_windows_patch_release_is_fail_closed_and_isolated():
    source = (ROOT / "tools/windows_patch_release.ps1").read_text(encoding="utf-8")

    assert "LES-release-smoke" in source
    assert "@($InstallRoot, $StateRoot)" in source
    assert "does not match requested build commit" in source
    assert "windows_release_smoke.ps1" in source
    assert "Get-FileHash" in source
    assert "git -C $RepoRoot status --porcelain" in source
    assert '"--build-number", [string]$BuildNumber' in source
    assert "ARTEL must not be bundled in the LES release runtime" in source
    assert '"products\\artel"' in source
    assert "LES_SMETA_BASELINE_ARCHIVE" in source
    assert "Verified smeta baseline archive was not provided" in source


def test_windows_patch_release_creates_missing_tracking_branch():
    source = (ROOT / "tools/windows_patch_release.ps1").read_text(encoding="utf-8")

    assert 'git show-ref --verify --quiet "refs/heads/$Branch"' in source
    assert '"${Branch}:refs/remotes/origin/${Branch}"' in source
    assert '@("checkout", "-b", $Branch, "refs/remotes/origin/$Branch")' in source
    assert '@("pull", "--ff-only", "origin", $Branch)' in source


def test_remote_build_bootstraps_branch_before_versioned_script(monkeypatch):
    calls = []
    monkeypatch.setattr(patch_release, "run", lambda command, **kwargs: calls.append(list(command)))

    patch_release.remote_build(
        host="legion",
        repo_root=r"C:\Users\Oleg\les_rag",
        branch="main",
        version="0.24.1",
        build_number=407,
        commit="abc123",
        smeta_baseline_archive=Path("baseline.zip"),
    )

    assert len(calls) == 3
    assert calls[0][-2] == "-EncodedCommand"
    decoded = base64.b64decode(calls[0][-1]).decode("utf-16le")
    assert 'fetch origin "${branch}:refs/remotes/origin/${branch}"' in decoded
    assert 'checkout -b $branch "refs/remotes/origin/$branch"' in decoded
    assert calls[1][0] == "scp"
    assert calls[1][1] == "baseline.zip"
    assert calls[2][6] == "-File"
    assert calls[2][7].endswith(r"tools\windows_patch_release.ps1")
    assert "-SmetaBaselineArchive" in calls[2]


def test_makefile_exposes_one_patch_release_entrypoint():
    source = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "patch-release:" in source
    assert "tools/patch_release.py $(PATCH_RELEASE_ARGS)" in source
    assert "test-release:" in source
    assert "tests/test_artel*.py" in source


def test_patch_release_uses_les_release_suite_without_separate_artel_product():
    source = (ROOT / "tools" / "patch_release.py").read_text(encoding="utf-8")

    assert '["make", "test-release"]' in source
    assert '["make", "test"],' not in source


def test_patch_release_requires_production_legion_heavy_pdf_gate():
    source = (ROOT / "tools" / "patch_release.py").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_patch_release.ps1").read_text(encoding="utf-8")
    production = (ROOT / "tools" / "windows_production_deploy.ps1").read_text(encoding="utf-8")

    assert 'summary.get("production")' in source
    assert 'indexed_files' in source and 'smoke_dataset_removed' in source
    assert 'expected_pdf_count = int(production.get("expected_pdf_count") or 0)' in source
    assert 'int(production.get("indexed_files") or 0) != expected_pdf_count' in source
    assert '"--resume-verified-commit"' in source
    assert '"merge-base", "--is-ancestor"' in source
    assert "windows_production_deploy.ps1" in windows
    assert "production = $production" in windows
    assert "Heavy PDF polygon must contain at least 4 PDF files" in production
    assert "$expectedPdfCount = $pdfFiles.Count" in production
    assert "$indexed.Count -eq $expectedPdfCount" in production
    assert '"RAG_COLLECTION_NAME" $newCollection' in production
    assert "previous_index_contract_incompatible" in production
    assert "old_collection_preserved = $true" in production
    assert "Production index contract is not compatible after bootstrap" in production
    assert "dense+sparse RRF" in production
    assert "/api/rag/datasets/$smokeDatasetId" in production
    assert "Start-InteractiveLesDesktop" in production
    assert 'Join-Path $InstallRoot "les-desktop.exe"' in production
    assert 'launch_mode = "interactive_scheduled_task"' in production
    assert '$result.stage = "desktop_handoff"' in production
    assert "$documentPollTransientErrors += 1" in production
    assert "One transient status timeout must not" in production
    assert "foreach ($cleanupAttempt in 1..5)" in production
    assert "$smokeDatasetRemoved = $true" in production
    assert '$result.stage = "stale_smoke_cleanup"' in production
    assert '[string]$_.name -like "LES production PDF smoke *"' in production
    assert "$staleSmokeDatasetsRemoved += 1" in production


def test_patch_release_requires_independent_legion_persistence(monkeypatch):
    monkeypatch.setattr(patch_release.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        patch_release,
        "output",
        lambda _command, **_kwargs: (
            '#< CLIXML\n'
            '{"product_version":"0.24.17","build_number":428,'
            '"ui_status":200,"desktop_processes":1}\n'
            '<Objs Version="1.1.0.1" />'
        ),
    )

    result = patch_release.verify_remote_production_persistence(
        host="legion",
        expected_version="0.24.17",
    )

    assert result["ui_status"] == 200
    assert result["desktop_processes"] == 1


def test_patch_release_retries_transient_independent_persistence_failure(monkeypatch):
    sleeps = []
    responses = iter(
        (
            patch_release.subprocess.CalledProcessError(1, ["ssh", "legion"]),
            '{"product_version":"0.24.17","build_number":428,'
            '"ui_status":200,"desktop_processes":1}',
        )
    )

    def transient_output(_command, **_kwargs):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(patch_release.time, "sleep", sleeps.append)
    monkeypatch.setattr(patch_release, "output", transient_output)

    result = patch_release.verify_remote_production_persistence(
        host="legion",
        expected_version="0.24.17",
    )

    assert result["product_version"] == "0.24.17"
    assert sleeps == [5, 5]
