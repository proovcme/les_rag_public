from pathlib import Path

import json
import inspect

from tools import internal_dual_deploy, internal_update


ROOT = Path(__file__).resolve().parents[1]


def test_internal_identity_prefers_deploy_stamp_commit():
    assert internal_dual_deploy._version_identity(
        {
            "les_version": "0.25.3",
            "build_number": 476,
            "git_commit": "runtime-checkout",
            "deployed_commit": "release-commit",
        }
    ) == {
        "product_version": "0.25.3",
        "build_number": 476,
        "commit": "release-commit",
    }


def test_internal_identity_accepts_runtime_short_commit():
    assert internal_dual_deploy._identity_matches(
        {
            "product_version": "0.25.3",
            "build_number": 476,
            "commit": "86879040",
        },
        {
            "product_version": "0.25.3",
            "build_number": 476,
            "commit": "86879040abcdef1234567890",
        },
    )


def test_dual_deploy_has_fixed_branch_and_no_publish_path():
    source = (ROOT / "tools/internal_update.py").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert 'BRANCH = "codex/audit-rag"' in source
    assert "--publish is forbidden" in source
    assert '"published": False' in source
    assert 'SCHEMA = "les.internal_update_bundle.v1"' in source
    assert "prepare-audit-rag:" in makefile
    assert "preflight-audit-rag-update inspect-audit-rag-update: inspect-mac-update" in makefile
    assert "prepare-audit-rag-legion:" in makefile
    assert 'echo "Legion отключён: сначала принимаем Mac updater."' in makefile
    assert "deploy-audit-rag-mac deploy-audit-rag: apply-mac-update" in makefile
    assert "tools/internal_update.py apply --hosts mac,legion" not in makefile
    assert "tools/internal_dual_deploy.py" not in makefile


def test_prepared_bundle_reuses_exact_sha_without_running_gates(tmp_path, monkeypatch):
    commit = "a" * 40
    dmg = tmp_path / "LES.dmg"
    baseline = tmp_path / "LES-smeta-baseline.zip"
    dmg.write_bytes(b"dmg")
    baseline.write_bytes(b"baseline")
    monkeypatch.setattr(internal_update, "CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(
        internal_update.patch_release,
        "load_contract",
        lambda: {
            "product_version": "0.25.3",
            "build_number": 476,
            "desktop_version": "5.1.476",
        },
    )
    monkeypatch.setattr(
        internal_update.patch_release,
        "require_clean_pushed_branch",
        lambda _branch: commit,
    )
    payload = {
        "schema": internal_update.SCHEMA,
        "status": "local_prepared",
        "published": False,
        "branch": internal_update.BRANCH,
        "commit": commit,
        "product_version": "0.25.3",
        "build_number": 476,
        "artifacts": {
            "mac_dmg": internal_update._artifact(dmg),
            "smeta_baseline": internal_update._artifact(baseline),
        },
        "windows": {"status": "not_prepared"},
    }
    internal_update._write_manifest(payload)
    monkeypatch.setattr(
        internal_update,
        "run",
        lambda _command: (_ for _ in ()).throw(AssertionError("gate reran")),
    )

    prepared = internal_update.prepare_local()

    assert prepared["cache_hit"] is True
    assert json.loads(internal_update._manifest_path(commit).read_text())["commit"] == commit


def test_corrupt_prepared_bundle_blocks_instead_of_rerunning_gates(
    tmp_path, monkeypatch
):
    commit = "b" * 40
    monkeypatch.setattr(internal_update, "CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(
        internal_update.patch_release,
        "load_contract",
        lambda: {
            "product_version": "0.25.3",
            "build_number": 476,
            "desktop_version": "5.1.476",
        },
    )
    monkeypatch.setattr(
        internal_update.patch_release,
        "require_clean_pushed_branch",
        lambda _branch: commit,
    )
    path = internal_update._manifest_path(commit)
    path.parent.mkdir(parents=True)
    path.write_text('{"schema":"wrong"}', encoding="utf-8")
    monkeypatch.setattr(
        internal_update,
        "run",
        lambda _command: (_ for _ in ()).throw(AssertionError("gate reran")),
    )

    try:
        internal_update.prepare_local()
    except RuntimeError as exc:
        assert "identity mismatch" in str(exc)
    else:
        raise AssertionError("corrupt prepared bundle was accepted")


def test_mac_transaction_excludes_user_state_and_has_rollback():
    source = (ROOT / "tools/internal_dual_deploy.py").read_text(encoding="utf-8")

    for name in (".env", "data", "storage", "RAG_Content", "local_private_archive"):
        assert name in source
    assert "def rollback(self)" in source
    assert "os.replace(temporary, destination)" in source
    assert "self.rollback()" in source
    assert "browser_layout_smoke.py" in source


def test_legion_deploy_is_transactional_and_preserves_data():
    release = (ROOT / "tools/windows_patch_release.ps1").read_text(encoding="utf-8")
    wrapper = (
        ROOT / "tools/windows_transactional_production_deploy.ps1"
    ).read_text(encoding="utf-8-sig")
    rollback = (ROOT / "tools/windows_production_rollback.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "windows_transactional_production_deploy.ps1" in release
    assert "robocopy.exe $InstallRoot $BackupRoot" in wrapper
    assert "/XJ" in wrapper
    assert "exit code $LASTEXITCODE" in wrapper
    assert "windows_production_rollback.ps1" in wrapper
    assert "data_untouched = $true" in wrapper
    assert 'runtime\\config\\version.json' in wrapper
    assert "Previous LES API is offline" in wrapper
    assert wrapper.index("Previous LES API is offline") < wrapper.index(
        "robocopy.exe $InstallRoot $BackupRoot"
    )
    assert "@(8050, 8051, 8052, 8053)" in rollback
    assert 'proxy_server:app|sovushka_ng\\.py' in rollback
    assert '"runtime\\installers\\windows\\start-light.ps1"' in rollback
    assert "service_fallback_used = $fallbackStarted" in rollback
    assert "Remove-Item -LiteralPath $InstallRoot" in rollback
    assert "Remove-Item -LiteralPath $StateRoot" not in rollback
    assert "New-ScheduledTaskAction -Execute $Desktop" in rollback
    assert "$env:ComSpec" not in rollback


def test_windows_production_update_uses_fast_start_not_first_run_bootstrap():
    production = (ROOT / "tools/windows_production_deploy.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "Start-PreparedUpdateRuntime" in production
    assert 'start_mode = "prepared_fast_update"' in production
    assert "--extra windows-reranker" in production
    assert '-Filter "python.exe" -Recurse' not in production
    assert "app\\bootstrap.ps1" not in production
    assert "Invoke-LesBoundedProcess" in production
    assert "-StdOut $startOut -StdErr $startErr" in production
    assert "Get-LesRuntimeProcessHygiene" in production
    assert 'process_contract -ne "direct_python_no_console_v1"' in production
    assert "cmd.exe wrapper process(es)" in production
    assert "single-instance gate failed" in production
    assert "New-ScheduledTaskAction -Execute $Desktop" in production
    assert "$env:ComSpec" not in production
    assert "services_reused = $true" in production
    assert "bootstrap_reentered = $false" in production
    assert production.count("Stop-LesRuntime") == 2


def test_windows_prepare_and_apply_are_separate_cached_steps():
    prepare = (ROOT / "tools/windows_prepare_update.ps1").read_text(
        encoding="utf-8-sig"
    )
    apply = (ROOT / "tools/windows_apply_prepared_update.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "les.windows.prepared-update.v1" in prepare
    assert "Read-PreparedUpdate" in prepare
    assert "cache_hit = $true" in prepare
    assert "windows_release_smoke.ps1" in prepare
    assert "windows_transactional_production_deploy.ps1" not in prepare
    assert "windows_transactional_production_deploy.ps1" in apply
    assert "build_windows_installer.py" not in apply
    assert "windows_release_smoke.ps1" not in apply
    assert "baseline_transfer = $false" in apply
    assert "write_deploy_stamp" in apply
    assert 'deployed_branch="codex/audit-rag"' in apply


def test_fast_apply_never_runs_release_gates_or_builds():
    source = inspect.getsource(internal_update.apply_update)

    assert '["make"' not in source
    assert "build_tauri" not in source
    assert "create_archive" not in source
