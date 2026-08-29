from __future__ import annotations

import json
import base64
import shutil
import sys
from pathlib import Path

import pytest

from tools import patch_release, platform_release_gate


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


def test_windows_json_parser_accepts_multiline_payload_with_clixml_noise():
    payload = patch_release._last_json_object(
        "remote preface\n"
        "{\n"
        '  "status": "prepared",\n'
        '  "smoke": {"ok": true}\n'
        "}\n"
        '<Objs Version="1.1.0.1" />'
    )

    assert payload == {"status": "prepared", "smoke": {"ok": True}}


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


def test_commit_identity_accepts_runtime_abbreviation_only():
    assert patch_release.commits_match("86879040", "86879040abcdef")
    assert not patch_release.commits_match("8687904", "deadbeef1234")


def test_remote_baseline_cache_skips_unchanged_transfer(monkeypatch, tmp_path):
    archive = tmp_path / "baseline.zip"
    archive.write_bytes(b"same")
    monkeypatch.setattr(
        patch_release,
        "output",
        lambda _command, **_kwargs: (
            '{"cached":true,"path":"C:\\\\cache\\\\same.zip","sha256":"abc"}'
        ),
    )
    monkeypatch.setattr(
        patch_release,
        "run",
        lambda _command, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unchanged baseline transferred")
        ),
    )

    result = patch_release._ensure_remote_baseline_cache(
        host="legion",
        archive=archive,
        expected_sha256="abc",
    )

    assert result["transferred"] is False


def test_release_requires_successful_platform_gate_for_exact_commit(monkeypatch):
    monkeypatch.setattr(
        patch_release,
        "output",
        lambda _command, **_kwargs: json.dumps(
            [
                {
                    "headSha": "abc",
                    "status": "completed",
                    "conclusion": "success",
                    "url": "https://example.test/run",
                }
            ]
        ),
    )

    assert patch_release.require_platform_gate("abc")["conclusion"] == "success"


def test_release_rejects_incomplete_platform_gate(monkeypatch):
    monkeypatch.setattr(
        patch_release,
        "output",
        lambda _command, **_kwargs: json.dumps(
            [{"headSha": "abc", "status": "in_progress", "conclusion": ""}]
        ),
    )

    with pytest.raises(RuntimeError, match="not successful"):
        patch_release.require_platform_gate("abc")


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
    assert "[guid]::NewGuid().ToString(\"N\")" in source
    assert '"LES-release-smoke\\app"' not in source
    assert '"LES-release-smoke\\state"' not in source
    assert "does not match requested build commit" in source
    assert "windows_release_smoke.ps1" in source
    assert "Get-FileHash" in source
    assert "git -C $RepoRoot status --porcelain" in source
    assert '"--build-number", [string]$BuildNumber' in source
    assert "ARTEL must not be bundled in the LES release runtime" in source
    assert '"products\\artel"' in source
    assert "LES_SMETA_BASELINE_ARCHIVE" in source
    assert "Verified smeta baseline archive was not provided" in source
    assert '$env:LES_RELEASE_SMOKE = "1"' in source
    assert '$env:LES_WINDOWS_STATE_ROOT = $StateRoot' in source
    assert "Restore-SmokeEnvironment" in source


def test_prepared_update_smoke_uses_checkout_owned_temporary_root():
    source = (ROOT / "tools/windows_prepare_update.ps1").read_text(encoding="utf-8")

    assert '.codex_tmp\\windows-release-smoke' in source
    assert '[guid]::NewGuid().ToString("N")' in source
    assert 'Join-Path $env:LOCALAPPDATA "LES-release-smoke"' not in source


def test_windows_release_smoke_does_not_replace_user_outlook_task():
    source = (ROOT / "tools/windows_release_smoke.ps1").read_text(encoding="utf-8-sig")

    assert '$env:LES_RELEASE_SMOKE = "1"' in source


def test_windows_patch_release_creates_missing_tracking_branch():
    source = (ROOT / "tools/windows_patch_release.ps1").read_text(encoding="utf-8")

    assert 'git show-ref --verify --quiet "refs/heads/$Branch"' in source
    assert '"${Branch}:refs/remotes/origin/${Branch}"' in source
    assert '@("checkout", "-b", $Branch, "refs/remotes/origin/$Branch")' in source
    assert '@("pull", "--ff-only", "origin", $Branch)' in source


def test_windows_release_entrypoint_derives_identity_and_runs_full_pipeline():
    source = (ROOT / "tools/windows_release.ps1").read_text(encoding="utf-8")

    assert "config\\version.json" in source
    assert 'git -C $RepoRoot rev-parse HEAD' in source
    assert 'git -C $RepoRoot rev-parse --abbrev-ref HEAD' in source
    assert "windows_patch_release.ps1" in source
    assert "-Version $Contract.product_version" in source
    assert "-BuildNumber $Contract.build_number" in source
    assert "-BuildCommit $Commit" in source


def test_portable_updater_gate_matches_make_profile(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        platform_release_gate,
        "run",
        lambda command, **_kwargs: calls.append(list(command)),
    )

    platform_release_gate.updater()

    assert calls[0][-2:] == ["tools/sync_version_contract.py", "--check"]
    assert calls[1][3:6] == ["-m", "py_compile", "tools/windows_runtime.py"]
    assert calls[2][3:6] == ["-m", "pytest", "-q"]
    assert calls[2][6] == "--basetemp"
    assert set(calls[2][8:]) == set(platform_release_gate.UPDATER_BEHAVIOR_TESTS)


def test_prepared_update_preserves_requested_branch(monkeypatch):
    calls: list[list[str]] = []

    def fake_output(command):
        calls.append(list(command))
        return '{"status":"applied","commit":"abc123"}'

    monkeypatch.setattr(patch_release, "output", fake_output)
    monkeypatch.setattr(
        patch_release,
        "verify_remote_production_persistence",
        lambda **_kwargs: {"status": "ok"},
    )

    result = patch_release.remote_apply_prepared_update(
        host="legion",
        repo_root=r"C:\Users\Oleg\les_rag",
        branch="codex/legion-model-quality",
        version="0.27.1",
        build_number=518,
        commit="abc123",
    )

    branch_index = calls[0].index("-Branch")
    assert calls[0][branch_index + 1] == "codex/legion-model-quality"
    assert result["status"] == "applied"


def test_apply_prepared_update_job_uses_branch_parameter():
    source = (ROOT / "tools/windows_apply_prepared_update.ps1").read_text(
        encoding="utf-8"
    )

    assert "[Parameter(Mandatory = $true)][string]$Branch" in source
    assert "branch = $Branch" in source
    assert 'branch = "codex/sovushka-ui-kit"' not in source


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
    assert 'fetch origin "+${branch}:refs/remotes/origin/${branch}"' in decoded
    assert 'checkout -B $branch "refs/remotes/origin/$branch"' in decoded
    assert "pull --ff-only origin $branch" not in decoded
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


def test_patch_release_keeps_heavy_pdf_smoke_isolated_from_production():
    source = (ROOT / "tools" / "patch_release.py").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_patch_release.ps1").read_text(encoding="utf-8")
    production = (ROOT / "tools" / "windows_production_deploy.ps1").read_text(encoding="utf-8")

    assert 'summary.get("production")' in source
    assert 'production.get("application_tree_replaced") is not True' in source
    assert 'production.get("user_data_untouched") is not True' in source
    assert 'production.get("state") != "ready"' in source
    assert '"--resume-verified-commit"' in source
    assert '"merge-base", "--is-ancestor"' in source
    assert "les.windows-hard-update.v1" in windows
    assert "windows_production_deploy.ps1" in windows
    assert "production = $production" in windows
    assert "Heavy PDF polygon" not in production
    assert "LES production PDF smoke" not in production
    assert "windows_update_engine.py" in production
    assert "Get-CimInstance" not in production
    assert "Get-NetTCPConnection" not in production


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


def test_publish_includes_and_verifies_extra_platform_assets(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "LES-Setup.exe").write_bytes(b"windows")
    (dist / "LES-Setup.exe.sha256").write_text("placeholder", encoding="ascii")
    (dist / "latest.json").write_text(
        json.dumps({"version": "1.2.3"}),
        encoding="utf-8",
    )
    dmg = dist / "LES.dmg"
    checksum = dist / "LES.dmg.sha256"
    dmg.write_bytes(b"macos")
    checksum.write_text("placeholder", encoding="ascii")
    monkeypatch.setattr(patch_release, "DIST", dist)
    monkeypatch.setattr(
        patch_release.subprocess,
        "run",
        lambda *args, **kwargs: patch_release.subprocess.CompletedProcess(
            args[0], 1, "", ""
        ),
    )
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        if command[:3] == ["gh", "release", "download"]:
            target = Path(command[command.index("--dir") + 1])
            for source in dist.iterdir():
                if source.is_file() and source.name != "release-notes.md":
                    shutil.copy2(source, target / source.name)
        return patch_release.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(patch_release, "run", fake_run)
    (dist / "release-notes.md").write_text("notes", encoding="utf-8")

    patch_release.publish(
        {
            "product_version": "1.2.3",
            "build_number": 4,
            "desktop_version": "5.1.4",
        },
        extra_assets=[dmg, checksum],
    )

    create = next(call for call in calls if call[:3] == ["gh", "release", "create"])
    assert str(dmg.resolve()) in create
    assert str(checksum.resolve()) in create


def test_platform_workflows_cover_mac_windows_builds_and_atomic_release():
    verify = (ROOT / ".github/workflows/verify.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    orchestrator = (ROOT / "tools/multiplatform_release.py").read_text(encoding="utf-8")

    assert "macos-14" in verify
    assert "windows-2022" in verify
    assert "platform_release_gate.py test" in verify
    assert "platform_release_gate.py build" in verify
    assert "environment: production" in release
    assert "LES_RELEASE_TOKEN" in release
    assert "tools/multiplatform_release.py" in release
    assert '"app,dmg"' in orchestrator
    assert '"--extra-asset"' in orchestrator


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
