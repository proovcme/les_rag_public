from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import release_orchestrator, release_receipt


TARGET = "b" * 40
TREE = "c" * 40


def _gate(root: Path, **overrides) -> Path:
    values = dict(
        root=root,
        target_commit=TARGET,
        target_tree=TREE,
        product_version="0.31.132",
        build_number=860,
        desktop_version="5.1.860",
        branch="",
        upstream_commit=None,
        local_only_full=True,
        policy=release_orchestrator.PREPARE_GATES,
        results=[{"gate": label, "exit_code": 0} for label, _ in release_orchestrator.PREPARE_GATES],
        clean=True,
    )
    values.update(overrides)
    return release_receipt.create_gate_receipt(**values)


def _args(root: Path, **overrides) -> argparse.Namespace:
    values = dict(
        root=root / "repo", work_root=root / "release-work", branch="", target="HEAD",
        base="", host="local", full_feed=None, skip_gates=False,
        local_only_full=True, force_full=False, publish=False, gate_receipt=None,
        runtime=root / "installed/runtime", state=root / "state", install=root / "installed",
        smeta_baseline_archive=root / "baseline.zip", artifact=None,
    )
    values.update(overrides)
    values["root"].mkdir(parents=True, exist_ok=True)
    for name in ("config/windows_runtime_manifest.json", "installers/windows/runtime-entrypoints.json"):
        path = values["root"] / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    return argparse.Namespace(**values)


def _prepare(monkeypatch, tmp_path, **overrides):
    args = _args(tmp_path, **overrides)
    calls = []
    monkeypatch.setattr(release_orchestrator, "require_local_release_source", lambda **kwargs: TARGET)
    monkeypatch.setattr(release_orchestrator, "require_release_source", lambda **kwargs: pytest.fail("local build must not fetch origin"))
    monkeypatch.setattr(release_orchestrator, "resolve_commit", lambda _root, value="HEAD": TARGET)
    monkeypatch.setattr(release_orchestrator, "resolve_tree", lambda *a: TREE)
    monkeypatch.setattr(release_orchestrator, "current_branch", lambda *a, **k: "")
    monkeypatch.setattr(release_orchestrator, "load_contract", lambda *a: {
        "product_version": "0.31.132", "build_number": 860, "desktop_version": "5.1.860",
    })
    monkeypatch.setattr(release_orchestrator, "classify_release", lambda *a, **k: pytest.fail("no fabricated patch base"))
    monkeypatch.setattr(release_orchestrator, "run_prepare_gates", lambda *a: calls.append("gates") or [
        {"gate": name, "exit_code": 0} for name, _ in release_orchestrator.PREPARE_GATES
    ])
    monkeypatch.setattr(release_orchestrator, "verify_post_gate_source", lambda **k: calls.append("post_gate_source"))

    def build(**kwargs):
        assert kwargs["base"] is None
        assert kwargs["full_feed"] is None
        calls.append("full_build")
        public = kwargs["output"] / "public"
        acceptance = kwargs["output"] / "acceptance"
        public.mkdir(parents=True)
        acceptance.mkdir()
        installer = public / "LES-Setup.exe"
        installer.write_bytes(b"immutable-full-installer")
        accepted_installer = acceptance / installer.name
        accepted_installer.write_bytes(installer.read_bytes())
        (acceptance / "hard-update-job.json").write_text(json.dumps({
            "schema": "les.windows-hard-update.v1", "update_id": "local-acceptance",
            "installer": str(accepted_installer.resolve()),
            "installer_sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
            "install_root": str(args.install.resolve()), "state_root": str(args.state.resolve()),
            "status_path": str((args.state / "artifacts/updates/hard-update-status.json").resolve()),
            "target_commit": TARGET, "product_version": "0.31.132",
            "build_number": 860, "desktop_version": "5.1.860", "branch": "",
        }), encoding="utf-8")
        return {"assets": [installer], "acceptance_path": acceptance}

    monkeypatch.setattr(release_orchestrator, "build_full_candidate", build)
    return args, release_orchestrator.prepare(args), calls


def test_local_bootstrap_has_truthful_null_upstream_empty_base_and_all_gates(monkeypatch, tmp_path):
    args, artifact, calls = _prepare(monkeypatch, tmp_path)
    gate = release_receipt.load_gate_receipt(Path(artifact["gate_receipt_path"]))
    assert calls == ["gates", "post_gate_source", "full_build"]
    assert artifact["release_class"] == "full"
    assert artifact["base_commits"] == []
    assert artifact["local_only_full"] is True
    assert artifact["publishable"] is False
    assert gate["upstream_commit"] is None
    assert gate["local_only_full"] is True
    assert gate["publishable"] is False
    assert [r["gate"] for r in gate["results"]] == [name for name, _ in release_orchestrator.PREPARE_GATES]
    assert not (args.work_root / "full-base/latest.json").exists()


@pytest.mark.parametrize("overrides", [
    {"host": "legion"}, {"skip_gates": True}, {"publish": True},
    {"base": TARGET}, {"full_feed": Path("imaginary-feed.json")},
])
def test_local_bootstrap_rejects_conflicting_scope_before_any_build(monkeypatch, tmp_path, overrides):
    args = _args(tmp_path, **overrides)
    monkeypatch.setattr(release_orchestrator, "current_branch", lambda *a, **k: "")
    monkeypatch.setattr(release_orchestrator, "require_local_release_source", lambda **k: pytest.fail("bad scope reached source"))
    with pytest.raises(RuntimeError, match="local-only full"):
        release_orchestrator.prepare(args)


def test_local_gate_cannot_claim_a_fake_upstream(tmp_path):
    with pytest.raises(ValueError, match="upstream"):
        _gate(tmp_path, upstream_commit=TARGET)


def test_local_gate_verification_is_scope_bound_and_cannot_be_reused_publicly(tmp_path):
    gate = release_receipt.load_gate_receipt(_gate(tmp_path))
    exact = dict(target_commit=TARGET, target_tree=TREE, product_version="0.31.132", build_number=860,
                 desktop_version="5.1.860", branch="", upstream_commit=None,
                 policy=release_orchestrator.PREPARE_GATES, local_only_full=True)
    release_receipt.verify_gate_receipt(gate, **exact)
    with pytest.raises((RuntimeError, ValueError)):
        release_receipt.verify_gate_receipt(gate, **{**exact, "local_only_full": False, "upstream_commit": TARGET})


def test_local_gate_cannot_create_a_publishable_or_patch_artifact(tmp_path):
    gate = _gate(tmp_path)
    asset = tmp_path / "LES-Setup.exe"
    asset.write_bytes(b"candidate")
    values = dict(root=tmp_path, gate_receipt=gate, release_class="full", target_commit=TARGET,
                  base_commits=[], product_version="0.31.132", build_number=860, desktop_version="5.1.860",
                  assets=[asset], candidate_root=tmp_path, acceptance_path=tmp_path,
                  runtime_manifest_sha256="d" * 64, entrypoint_registry_sha256="e" * 64,
                  build_evidence={}, publishable=False)
    for change in ({"publishable": True}, {"release_class": "patch"}, {"base_commits": [TARGET]}):
        with pytest.raises(ValueError, match="local-only full"):
            release_receipt.create_artifact_receipt(**{**values, **change})


def test_publish_refuses_local_artifact_before_git_or_network(monkeypatch, tmp_path):
    args, artifact, _ = _prepare(monkeypatch, tmp_path)
    args.artifact = Path(artifact["artifact_path"])
    monkeypatch.setattr(release_orchestrator, "resolve_commit", lambda *a: pytest.fail("publication touched git"))
    with pytest.raises(RuntimeError, match="local-only full"):
        release_orchestrator.publish(args)
    with pytest.raises(RuntimeError, match="local-only full"):
        release_orchestrator.publish_artifact_candidate(
            artifact_path=args.artifact, acceptance_path=tmp_path / "unused.json", artifact=artifact,
            public=tmp_path, stage_callback=lambda *a: None, root=args.root,
        )


def test_local_artifact_uses_same_bound_full_acceptance_and_cannot_be_published_after_accept(monkeypatch, tmp_path):
    args, artifact, _ = _prepare(monkeypatch, tmp_path)
    args.artifact = Path(artifact["artifact_path"])
    args.job = None
    calls = []
    def accept_full(**kwargs):
        job = json.loads(kwargs["job_path"].read_text(encoding="utf-8"))
        assert kwargs["install"] == args.install
        assert kwargs["state"] == args.state
        assert hashlib.sha256(Path(job["installer"]).read_bytes()).hexdigest() == job["installer_sha256"]
        assert kwargs["expected"]["target_commit"] == TARGET
        calls.append("same_full_acceptance")
        return {"accepted": True, "release_class": "full", "final_identity": kwargs["expected"]}
    monkeypatch.setattr(release_orchestrator.windows_release_acceptance, "accept_full", accept_full)
    accepted = release_orchestrator.accept(args)
    assert accepted["result"] == "accepted"
    assert calls == ["same_full_acceptance"]
    acceptance = args.artifact.parent / "acceptance" / f"{accepted['acceptance_id']}.json"
    for action in (
        lambda: release_receipt.create_publication(args.artifact, acceptance_path=acceptance),
        lambda: release_receipt.write_public_artifact_receipt(args.artifact, acceptance, tmp_path / "public.json"),
    ):
        with pytest.raises(RuntimeError, match="local-only full"):
            action()
    assert release_receipt.load_artifact_receipt(args.artifact)["publishable"] is False


def test_local_artifact_cannot_start_remote_acceptance(monkeypatch, tmp_path):
    args, artifact, _ = _prepare(monkeypatch, tmp_path)
    args.artifact = Path(artifact["artifact_path"])
    args.host = "legion"
    monkeypatch.setattr(release_orchestrator, "run_remote_acceptance", lambda **k: pytest.fail("remote mutation"))
    with pytest.raises(RuntimeError, match="local acceptance host"):
        release_orchestrator.accept(args)
    assert release_receipt.acceptance_attempts(args.artifact) == []


def test_local_bootstrap_reuses_only_its_exact_local_gate_receipt(monkeypatch, tmp_path):
    gate = _gate(tmp_path / "release-work")
    _args_value, artifact, calls = _prepare(monkeypatch, tmp_path, gate_receipt=gate)
    assert calls == ["full_build"]
    assert artifact["gate_receipt_path"] == str(gate.resolve())


def test_local_source_accepts_clean_detached_exact_checkout_and_rejects_dirty_or_other_head(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()
    git("init")
    (root / "tracked.txt").write_text("source", encoding="utf-8")
    git("add", "tracked.txt")
    git("-c", "user.name=Release Test", "-c", "user.email=release-test@example.invalid", "commit", "-m", "source")
    commit = git("rev-parse", "HEAD")
    git("checkout", "--detach", commit)
    assert release_orchestrator.require_local_release_source(root=root, branch="", target=commit) == commit
    (root / "user-file.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(RuntimeError, match="clean"):
        release_orchestrator.require_local_release_source(root=root, branch="", target=commit)
    assert (root / "user-file.txt").read_text(encoding="utf-8") == "keep"
    (root / "user-file.txt").unlink()
    with pytest.raises(RuntimeError, match="HEAD"):
        release_orchestrator.require_local_release_source(root=root, branch="", target=TARGET)


def test_cli_local_bootstrap_is_explicit_and_default_release_keeps_original_scope():
    parser = release_orchestrator._parser()
    assert parser.parse_args(["prepare", "--local-only-full"]).local_only_full is True
    assert parser.parse_args(["run", "--local-only-full"]).local_only_full is True
    assert parser.parse_args(["prepare"]).local_only_full is False


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="actual Windows prepare function requires Windows PowerShell")
def test_actual_windows_prepare_cache_is_bound_to_baseline_bytes(tmp_path):
    source = (release_orchestrator.ROOT / "tools/windows_prepare_update.ps1").read_text(encoding="utf-8-sig")
    function = source[source.index("function Read-PreparedUpdate {"):source.index("\n$cached = Read-PreparedUpdate")]
    root = tmp_path / "кэш with spaces"
    root.mkdir()
    baseline = root / "baseline.zip"
    baseline.write_bytes(b"verified-baseline-a")
    installer = root / "LES-Setup.exe"
    installer.write_bytes(b"exact-installer")
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({
        "schema": "les.windows.prepared-package.v1", "status": "prepared",
        "product_version": "0.31.132", "build_number": 860, "commit": TARGET,
        "sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
        "baseline_sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
        "cache_hit": False,
    }), encoding="utf-8")
    script = root / "cache-test.ps1"
    script.write_text(
        'param([string]$SmetaBaselineArchive,[string]$ManifestPath,[string]$CachedInstaller)\n'
        '$ErrorActionPreference="Stop"\n$Version="0.31.132"\n$BuildNumber=860\n'
        '[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)\n'
        f'$BuildCommit="{TARGET}"\n' + function + '\n'
        '$result=Read-PreparedUpdate\nif ($null -eq $result) { "MISS" } else { "HIT" }\n',
        encoding="utf-8",
    )
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
               "-SmetaBaselineArchive", str(baseline), "-ManifestPath", str(manifest), "-CachedInstaller", str(installer)]
    def call():
        return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="strict")
    same = call()
    assert same.returncode == 0 and same.stdout.strip() == "HIT"
    baseline.write_bytes(b"verified-baseline-b")
    changed = call()
    assert changed.returncode == 0 and changed.stdout.strip() == "MISS"
    assert installer.read_bytes() == b"exact-installer"
    baseline.unlink()
    missing = call()
    assert missing.returncode != 0 and "baseline is missing" in missing.stderr


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="actual Windows package preparation")
def test_actual_prepare_rejects_baseline_changed_during_build_before_prior_cache_writes(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".gitignore").write_text("dist/\n", encoding="utf-8")
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()
    git("init")
    git("add", ".gitignore")
    git("-c", "user.name=Release Test", "-c", "user.email=release-test@example.invalid", "commit", "-m", "source")
    commit = git("rev-parse", "HEAD")
    baseline = tmp_path / "baseline.zip"
    baseline.write_bytes(b"baseline-a")
    cache = tmp_path / "previous-cache"
    cache.mkdir()
    cached_installer = cache / "LES-Setup.exe"
    cached_installer.write_bytes(b"prior-installer")
    cached_manifest = cache / "manifest.json"
    prior_manifest = json.dumps({"schema": "les.windows.prepared-package.v1", "status": "prepared",
                                "product_version": "0.31.131", "build_number": 859,
                                "commit": TARGET, "sha256": _sha_bytes(cached_installer),
                                "baseline_sha256": _sha_bytes(baseline), "cache_hit": False}).encode("utf-8")
    cached_manifest.write_bytes(prior_manifest)
    wrapper = tmp_path / "controlled-build.ps1"
    wrapper.write_text(
        'param([string]$PrepareScript,[string]$RepoRoot,[string]$SmetaBaselineArchive,[string]$CacheRoot,[string]$BuildCommit)\n'
        '$ErrorActionPreference="Stop"\n'
        'function global:uv {\n'
        '  New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot "dist") | Out-Null\n'
        '  [IO.File]::WriteAllText((Join-Path $RepoRoot "dist/LES-Setup.exe"), "new installer")\n'
        '  [IO.File]::WriteAllText($SmetaBaselineArchive, "baseline-b")\n'
        '  $global:LASTEXITCODE=0\n}\n'
        '. $PrepareScript -Version "0.31.132" -BuildNumber 860 -BuildCommit $BuildCommit '
        '-RepoRoot $RepoRoot -SmetaBaselineArchive $SmetaBaselineArchive -CacheRoot $CacheRoot\n',
        encoding="utf-8",
    )
    result = subprocess.run([
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper),
        "-PrepareScript", str(release_orchestrator.ROOT / "tools/windows_prepare_update.ps1"),
        "-RepoRoot", str(root), "-SmetaBaselineArchive", str(baseline), "-CacheRoot", str(cache), "-BuildCommit", commit,
    ], capture_output=True, text=True)

    assert result.returncode != 0 and "Baseline archive changed" in result.stderr
    assert cached_installer.read_bytes() == b"prior-installer"
    assert cached_manifest.read_bytes() == prior_manifest
    assert baseline.read_bytes() == b"baseline-b"


def _sha_bytes(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
