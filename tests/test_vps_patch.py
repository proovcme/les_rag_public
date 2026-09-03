from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import zipfile
import httpx
import pytest

from proxy.services import update_service
from tools import release_classification, vps_patch
from tools import vps_patch_apply


def test_windows_patch_accepts_trusted_text_with_mixed_line_endings(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    target = runtime / "proxy" / "x.py"
    target.parent.mkdir(parents=True)
    mixed = b"ONE = 1\r\nTWO = 2\nTHREE = 3\r\n"
    canonical = mixed.replace(b"\r\n", b"\n")
    target.write_bytes(mixed)
    monkeypatch.setattr(update_service, "runtime_root", lambda: runtime)
    accepted = hashlib.sha256(canonical).hexdigest()
    entry = {
        "path": "proxy/x.py",
        "base_sha256": accepted,
        "accepted_sha256": [accepted],
        "sha256": hashlib.sha256(b"AFTER = 1\n").hexdigest(),
        "bytes": len(b"AFTER = 1\n"),
    }
    payload = {
        "schema": update_service.VPS_PATCH_FEED_SCHEMA,
        "archive_url": "https://github.com/proovcme/les_rag_public/releases/download/v0.30.27/les-patch.zip",
        "archive_sha256": "a" * 64,
        "patch": {
            "schema": update_service.VPS_PATCH_SCHEMA,
            "patch_id": "mixed-eol",
            "base_commit": "b" * 40,
            "target_commit": "c" * 40,
            "product_version": "0.30.27",
            "build_number": 667,
            "files": [entry],
        },
    }

    assert update_service._validate_patch_feed(payload)["compatible"] is True
    assert vps_patch_apply.entry_accepts_current(
        entry,
        hashlib.sha256(mixed).hexdigest(),
        normalized_current=accepted,
    ) is True


def test_patch_manifest_records_exact_installed_mixed_eol_state(tmp_path):
    runtime = tmp_path / "runtime"
    installed = runtime / "proxy" / "x.py"
    installed.parent.mkdir(parents=True)
    mixed = b"ONE = 1\r\nTWO = 2\nTHREE = 3\r\n"
    installed.write_bytes(mixed)

    accepted, _missing = vps_patch.accepted_hashes_from_states(
        [mixed.replace(b"\r\n", b"\n")],
        path="proxy/x.py",
        installed_runtime=runtime,
    )

    assert hashlib.sha256(mixed).hexdigest() in accepted


def test_patch_builder_batches_history_reads_and_reports_progress(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "proxy").mkdir()
    (repo / "config").mkdir()
    (repo / "proxy" / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "proxy" / "b.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "config" / "version.json").write_text(
        json.dumps({
            "schema": "les.version.v1",
            "product_version": "0.30.23",
            "build_number": 663,
            "desktop_version": "5.1.663",
        }),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    (repo / "proxy" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "middle"], cwd=repo, check=True)
    (repo / "proxy" / "b.py").write_text("VALUE = 2\n", encoding="utf-8")
    (repo / "config" / "version.json").write_text(
        json.dumps({
            "schema": "les.version.v1",
            "product_version": "0.30.24",
            "build_number": 664,
            "desktop_version": "5.1.664",
        }),
        encoding="utf-8",
    )
    subprocess.run(["git", "commit", "-qam", "target"], cwd=repo, check=True)
    target = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    original_root = vps_patch.ROOT
    original_run = subprocess.run
    git_show_calls = []

    def counted_run(command, *args, **kwargs):
        if list(command)[:2] == ["git", "show"]:
            git_show_calls.append(list(command))
        return original_run(command, *args, **kwargs)

    events = []
    monkeypatch.setattr(subprocess, "run", counted_run)
    vps_patch.ROOT = repo
    try:
        result = vps_patch.build_patch(
            base=base,
            target=target,
            files=["proxy/a.py", "proxy/b.py"],
            output=tmp_path / "out",
            origin="https://example.invalid/release",
            progress=events.append,
        )
    finally:
        vps_patch.ROOT = original_root

    entries = {entry["path"]: entry for entry in result["patch"]["files"]}
    assert hashlib.sha256(b"VALUE = 1\n").hexdigest() in entries["proxy/a.py"]["accepted_sha256"]
    assert hashlib.sha256(b"VALUE = 2\n").hexdigest() in entries["proxy/a.py"]["accepted_sha256"]
    assert len(git_show_calls) <= 5
    assert events[-1] == {
        "stage": "files",
        "current": 2,
        "total": 2,
        "path": "proxy/b.py",
    }


def test_legacy_patch_builder_default_origin_is_public_github_release() -> None:
    assert vps_patch.DEFAULT_ORIGIN == (
        "https://github.com/proovcme/les_rag_public/releases/latest/download"
    )


def _github_feed(patch: dict, *, archive_bytes: int = 5) -> dict:
    version = patch["product_version"]
    return {
        "schema": update_service.GITHUB_UPDATE_FEED_SCHEMA,
        "repository": "proovcme/les_rag_public",
        "release_class": "patch",
        "product_version": version,
        "build_number": patch["build_number"],
        "tag": f"v{version}",
        "target_commit": patch["target_commit"],
        "compatible_bases": [patch["base_commit"]],
        "asset": {
            "url": f"https://github.com/proovcme/les_rag_public/releases/download/v{version}/les-patch.zip",
            "bytes": archive_bytes,
            "sha256": "a" * 64,
        },
        "patch": patch,
    }


def _delete_github_feed(*, path: str = "proxy/old_agent.py", scope: str = "runtime") -> dict:
    version = update_service.LES_VERSION
    build_number = update_service.BUILD_NUMBER
    patch = {
        "schema": update_service.VPS_PATCH_SCHEMA,
        "patch_id": "delete-p1",
        "base_commit": "b" * 40,
        "target_commit": "c" * 40,
        "product_version": version,
        "build_number": build_number,
        "files": [
            {
                "operation": "replace",
                "path": "tools/vps_patch_apply.py",
                "base_sha256": hashlib.sha256(b"old helper").hexdigest(),
                "accepted_sha256": [hashlib.sha256(b"old helper").hexdigest()],
                "accepted_missing": False,
                "sha256": hashlib.sha256(b"new helper").hexdigest(),
                "bytes": len(b"new helper"),
            },
            {
                "operation": "delete",
                "scope": scope,
                "path": path,
                "base_sha256": hashlib.sha256(b"known old").hexdigest(),
                "accepted_sha256": [hashlib.sha256(b"known old").hexdigest()],
                "accepted_missing": True,
                "sha256": hashlib.sha256(b"").hexdigest(),
                "bytes": 0,
            },
        ],
    }
    return _github_feed(patch)


def test_patch_allowlist_rejects_runtime_boundaries():
    assert vps_patch.normalize_path("proxy/services/example.py") == "proxy/services/example.py"
    assert (
        vps_patch.normalize_path("installers/windows/start-light.ps1")
        == "installers/windows/start-light.ps1"
    )
    assert (
        vps_patch.normalize_path("installers/windows/runtime-process.ps1")
        == "installers/windows/runtime-process.ps1"
    )
    with pytest.raises(ValueError, match="allowlist|denied"):
        vps_patch.normalize_path("pyproject.toml")
    with pytest.raises(ValueError, match="allowlist|denied"):
        vps_patch.normalize_path("installers/windows/nsis/setup.nsi")
    with pytest.raises(ValueError, match="unsafe"):
        vps_patch.normalize_path("../outside.py")


@pytest.mark.parametrize(
    "path",
    [
        "data/les_meta_qwen.db",
        "storage/artifacts/meta.db",
        "RAG_Content/project/source.pdf",
        "logs/proxy.log",
        "artifacts/result.xlsx",
    ],
)
def test_soft_patch_cannot_mutate_persistent_state(path):
    with pytest.raises(ValueError, match="allowlist|unsupported"):
        vps_patch.normalize_path(path)
    with pytest.raises(RuntimeError, match="allowlist|unsupported"):
        vps_patch_apply.safe_relative_path(path)


def test_patch_allowlist_accepts_shared_console_free_runtime_launcher():
    assert (
        vps_patch.normalize_path("tools/les_runtime_control.py")
        == "tools/les_runtime_control.py"
    )
    assert "tools/les_runtime_control.py" in vps_patch_apply.ALLOWED_FILES


def test_patch_allowlist_accepts_self_hosted_local_update_builder():
    assert vps_patch.normalize_path("tools/vps_patch.py") == "tools/vps_patch.py"
    assert "tools/vps_patch.py" in vps_patch_apply.ALLOWED_FILES


def test_patch_allowlists_accept_installed_workbook_acceptance_tool():
    path = "tools/live_workbook_acceptance.py"
    assert vps_patch.normalize_path(path) == path
    assert path in vps_patch_apply.ALLOWED_FILES
    assert path in update_service.VPS_PATCH_ALLOWED_FILES


@pytest.mark.parametrize(
    "path",
    [
        "env.example",
        "installers/windows/runtime-entrypoints.json",
        "tools/activate_smeta_rag_generation.py",
        "tools/build_smeta_norm_rag.py",
        "tools/build_smeta_structured_base.py",
        "tools/gesn_update_from_fgis.py",
        "tools/install_les.py",
        "tools/rebuild_active_smeta_rag.py",
        "tools/smeta_generation_coordinator.py",
        "tools/smeta_generation_lease.py",
    ],
)
def test_patch_allowlists_accept_declared_runtime_support_files(path):
    assert vps_patch.normalize_path(path) == path
    assert vps_patch_apply.safe_relative_path(path).as_posix() == path
    assert path in update_service.VPS_PATCH_ALLOWED_FILES


def test_patch_allowlists_are_synchronized_across_build_and_apply():
    assert release_classification.PATCH_ALLOWED_FILES <= vps_patch.ALLOWED_FILES
    assert vps_patch.ALLOWED_FILES == vps_patch_apply.ALLOWED_FILES
    assert vps_patch.ALLOWED_FILES == update_service.VPS_PATCH_ALLOWED_FILES


def test_patch_allowlist_accepts_qdrant_visualizer_content():
    path = "qdrant_visualizer/export_data.py"
    assert vps_patch.normalize_path(path) == path
    assert vps_patch_apply.safe_relative_path(path).as_posix() == path
    assert path.startswith(update_service.VPS_PATCH_DELETE_ALLOWED_ROOTS)


def test_local_updater_uses_limited_task_without_elevation(tmp_path):
    helper = tmp_path / "helper.py"
    job = tmp_path / "job.json"
    task_name, encoded = update_service._patch_task_command(helper, job, "patch-1")
    command = base64.b64decode(encoded).decode("utf-16le")
    assert task_name == "LES-Patch-patch-1"
    assert "RunLevel Limited" in command
    assert "RunLevel Highest" not in command
    assert "-Verb RunAs" not in command


def test_local_updater_reads_exact_installed_commit(tmp_path):
    commit = "a" * 40
    (tmp_path / ".les_deploy_stamp.json").write_text(
        json.dumps({"deployed_commit": commit}), encoding="utf-8"
    )
    assert vps_patch._installed_commit(tmp_path) == commit


def test_automatic_patch_files_keeps_only_runtime_allowlist(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    runtime_file = repo / "proxy" / "x.py"
    runtime_file.parent.mkdir()
    runtime_file.write_text("before\n", encoding="utf-8")
    docs_file = repo / "docs" / "runtime.md"
    docs_file.parent.mkdir()
    docs_file.write_text("before\n", encoding="utf-8")
    tests_file = repo / "tests" / "test_x.py"
    tests_file.parent.mkdir()
    tests_file.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    runtime_file.write_text("after\n", encoding="utf-8")
    docs_file.write_text("after\n", encoding="utf-8")
    tests_file.write_text("after\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "target"], cwd=repo, check=True)
    target = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    original = vps_patch.ROOT
    vps_patch.ROOT = repo
    try:
        assert vps_patch._automatic_patch_files(base, target) == ["proxy/x.py"]
    finally:
        vps_patch.ROOT = original


def test_automatic_patch_files_blocks_unknown_runtime_paths(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    runtime_file = repo / "proxy" / "x.py"
    runtime_file.parent.mkdir()
    runtime_file.write_text("before\n", encoding="utf-8")
    (repo / "README.md").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    runtime_file.write_text("after\n", encoding="utf-8")
    (repo / "README.md").write_text("after\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "target"], cwd=repo, check=True)
    target = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    original = vps_patch.ROOT
    vps_patch.ROOT = repo
    try:
        try:
            vps_patch._automatic_patch_files(base, target)
            raise AssertionError("unknown runtime path must block soft package")
        except ValueError as exc:
            assert "unknown runtime paths block" in str(exc)
            assert "README.md" in str(exc)
    finally:
        vps_patch.ROOT = original


def test_automatic_patch_files_ignores_version_only_project_metadata(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    project = repo / "pyproject.toml"
    project.write_text('[project]\nname = "les-v2"\nversion = "0.28.1"\n', encoding="utf-8")
    runtime_file = repo / "proxy" / "x.py"
    runtime_file.parent.mkdir()
    runtime_file.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    project.write_text(project.read_text(encoding="utf-8").replace("0.28.1", "0.28.2"), encoding="utf-8")
    runtime_file.write_text("after\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "target"], cwd=repo, check=True)
    target = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    original = vps_patch.ROOT
    vps_patch.ROOT = repo
    try:
        assert vps_patch._automatic_patch_files(base, target) == ["proxy/x.py"]
    finally:
        vps_patch.ROOT = original


def test_automatic_patch_files_reports_full_release_trigger(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    native = repo / "desktop" / "tauri" / "src-tauri" / "src" / "main.rs"
    native.parent.mkdir(parents=True)
    native.write_text("fn main() {}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    native.write_text('fn main() { println!("changed"); }\n', encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "target"], cwd=repo, check=True)
    target = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    original = vps_patch.ROOT
    vps_patch.ROOT = repo
    try:
        with pytest.raises(ValueError, match="full release required.*main.rs.*desktop runtime changed"):
            vps_patch._automatic_patch_files(base, target)
    finally:
        vps_patch.ROOT = original


def test_update_local_bootstraps_offline_runtime_with_persistent_python(
    tmp_path, monkeypatch
):
    runtime = tmp_path / "runtime"
    state = tmp_path / "state"
    python = state / ".venv/Scripts/python.exe"
    launcher = tmp_path / "repo/tools/windows_runtime.py"
    runtime.mkdir()
    python.parent.mkdir(parents=True)
    launcher.parent.mkdir(parents=True)
    python.write_bytes(b"fixture")
    launcher.write_bytes(b"fixture")
    live = iter((False, True))
    captured = {}
    monkeypatch.setattr(vps_patch, "ROOT", tmp_path / "repo")
    monkeypatch.setattr(vps_patch, "_local_runtime_live", lambda _runtime: next(live))
    monkeypatch.setattr(
        vps_patch.subprocess,
        "run",
        lambda arguments, **kwargs: (
            captured.update(arguments=arguments, kwargs=kwargs)
            or subprocess.CompletedProcess(arguments, 0, "ready", "")
        ),
    )

    assert vps_patch._ensure_local_runtime_live(runtime, state) is True
    assert captured["arguments"][0] == str(python)
    assert captured["arguments"][1] == str(launcher)
    assert captured["arguments"][2] == "start"


def test_update_local_does_not_restart_already_live_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(vps_patch, "_local_runtime_live", lambda _runtime: True)
    monkeypatch.setattr(
        vps_patch.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("live runtime restarted")
        ),
    )

    assert vps_patch._ensure_local_runtime_live(tmp_path / "runtime", tmp_path / "state") is False


def test_update_local_never_bootstraps_or_manages_external_qdrant(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    state = tmp_path / "state"
    runtime.mkdir()
    state.mkdir()
    assert not hasattr(vps_patch, "_ensure_local_qdrant")
    monkeypatch.setattr(vps_patch, "_installed_commit", lambda _runtime: "a" * 40)
    monkeypatch.setattr(vps_patch, "_ensure_local_runtime_live", lambda *_args: False)
    monkeypatch.setattr(vps_patch, "_automatic_patch_files", lambda *_args: ["proxy/x.py"])
    monkeypatch.setattr(vps_patch.subprocess, "check_output", lambda *_args, **_kwargs: "b" * 40)
    monkeypatch.setattr(vps_patch, "build_patch", lambda **_kwargs: {"patch": "ready"})
    monkeypatch.setattr(vps_patch, "apply_local", lambda **_kwargs: {"status": str(tmp_path / "status.json")})
    monkeypatch.setattr(vps_patch, "wait_local_update", lambda _path: {"state": "ready"})

    result = vps_patch.update_local(output=tmp_path / "out", runtime=runtime, state=state)

    assert result["ok"] is True
    assert "qdrant_started" not in result


def test_build_patch_contains_only_manifest_and_declared_payload(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    path = repo / "proxy" / "x.py"
    path.parent.mkdir()
    path.write_text("VALUE = 1\n", encoding="utf-8")
    version = repo / "config" / "version.json"
    version.parent.mkdir()
    version.write_text(
        json.dumps(
            {
                "schema": "les.version.v1",
                "product_version": "0.25.18",
                "build_number": 491,
                "desktop_version": "5.1.491",
            }
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    path.write_text("VALUE = 2\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "target"], cwd=repo, check=True)
    target = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    original = vps_patch.ROOT
    vps_patch.ROOT = repo
    try:
        result = vps_patch.build_patch(base=base, target=target, files=["proxy/x.py"], output=tmp_path / "out", origin="https://les.ovc.me/updates")
    finally:
        vps_patch.ROOT = original
    with zipfile.ZipFile(result["archive"]) as bundle:
        assert set(bundle.namelist()) == {"manifest.json", "payload/proxy/x.py"}
        manifest = json.loads(bundle.read("manifest.json"))
    assert manifest["base_commit"] == base
    assert manifest["target_commit"] == target
    assert manifest["product_version"] == "0.25.18"
    assert manifest["build_number"] == 491
    assert manifest["files"][0]["base_sha256"] == hashlib.sha256(b"VALUE = 1\r\n").hexdigest()
    assert hashlib.sha256(b"VALUE = 1\r\n").hexdigest() in manifest["files"][0]["accepted_sha256"]
    assert hashlib.sha256(b"VALUE = 2\n").hexdigest() in manifest["files"][0]["accepted_sha256"]
    assert result["archive_sha256"] == vps_patch.sha256_file(result["archive"])


def test_builder_packages_delete_as_v2_self_bridge(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    obsolete = repo / "proxy" / "old_agent.py"
    obsolete.parent.mkdir(parents=True)
    obsolete.write_text("OLD = True\n", encoding="utf-8")
    helper = repo / "tools" / "vps_patch_apply.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("BRIDGE = 1\n", encoding="utf-8")
    version = repo / "config" / "version.json"
    version.parent.mkdir(parents=True)
    version.write_text(
        json.dumps(
            {
                "schema": "les.version.v1",
                "product_version": "0.30.6",
                "build_number": 646,
                "desktop_version": "5.1.646",
            }
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    obsolete.unlink()
    helper.write_text("BRIDGE = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "delete with bridge"], cwd=repo, check=True)
    target = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    original = vps_patch.ROOT
    vps_patch.ROOT = repo
    try:
        built = vps_patch.build_patch(
            base=base,
            target=target,
            files=["proxy/old_agent.py", "tools/vps_patch_apply.py"],
            output=tmp_path / "out",
            origin="https://github.com/proovcme/les_rag_public/releases/latest/download",
        )
    finally:
        vps_patch.ROOT = original

    with zipfile.ZipFile(built["archive"]) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        deleted = next(
            entry for entry in manifest["files"]
            if entry["path"] == "proxy/old_agent.py"
        )
        assert manifest["schema"] == "les.vps-patch.v2"
        assert deleted["operation"] == "delete"
        assert deleted["bytes"] == 0
        assert deleted["sha256"] == hashlib.sha256(b"").hexdigest()
        assert bundle.read("payload/proxy/old_agent.py") == b""
        assert "payload/tools/vps_patch_apply.py" in bundle.namelist()

    original = vps_patch.ROOT
    vps_patch.ROOT = repo
    try:
        with pytest.raises(
            ValueError,
            match="delete patch must replace tools/vps_patch_apply.py",
        ):
            vps_patch.build_patch(
                base=base,
                target=target,
                files=["proxy/old_agent.py"],
                output=tmp_path / "unsafe",
                origin="https://example.invalid",
            )
    finally:
        vps_patch.ROOT = original


def test_builder_packages_one_exact_desktop_shell_with_known_base(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    version = repo / "config" / "version.json"
    version.parent.mkdir()
    version.write_text(
        json.dumps(
            {
                "schema": "les.version.v1",
                "product_version": "0.25.18",
                "build_number": 491,
                "desktop_version": "5.1.491",
            }
        ),
        encoding="utf-8",
    )
    runtime_file = repo / "proxy" / "x.py"
    runtime_file.parent.mkdir()
    runtime_file.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    runtime_file.write_text("after\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "target"], cwd=repo, check=True)
    target = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    desktop_root = tmp_path / "desktop-build"
    desktop_root.mkdir()
    desktop = desktop_root / "les-desktop.exe"
    desktop.write_bytes(b"new desktop shell")
    desktop_manifest = desktop_root / "les-desktop.update.json"
    desktop_manifest.write_text(
        json.dumps(
            {
                "schema": "les.windows-update-shell.v1",
                "target_commit": target,
                "product_version": "0.25.18",
                "build_number": 491,
                "desktop_version": "5.1.491",
                "binary": "les-desktop.exe",
                "binary_sha256": hashlib.sha256(b"new desktop shell").hexdigest(),
                "binary_bytes": len(b"new desktop shell"),
                "base_binary_sha256": hashlib.sha256(b"old desktop shell").hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    original = vps_patch.ROOT
    vps_patch.ROOT = repo
    try:
        result = vps_patch.build_patch(
            base=base,
            target=target,
            files=["proxy/x.py"],
            output=tmp_path / "out",
            origin="https://les.ovc.me/updates",
            desktop_manifest=desktop_manifest,
        )
    finally:
        vps_patch.ROOT = original

    with zipfile.ZipFile(result["archive"]) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        assert "payload/@app/les-desktop.exe" in bundle.namelist()
    desktop_entry = next(entry for entry in manifest["files"] if entry["scope"] == "app")
    assert desktop_entry["path"] == "les-desktop.exe"
    assert desktop_entry["sha256"] == hashlib.sha256(b"new desktop shell").hexdigest()

    payload = json.loads(desktop_manifest.read_text(encoding="utf-8"))
    payload["target_commit"] = "f" * 40
    desktop_manifest.write_text(json.dumps(payload), encoding="utf-8")
    vps_patch.ROOT = repo
    try:
        with pytest.raises(ValueError, match="does not match target"):
            vps_patch.build_patch(
                base=base,
                target=target,
                files=["proxy/x.py"],
                output=tmp_path / "rejected",
                origin="https://les.ovc.me/updates",
                desktop_manifest=desktop_manifest,
            )
    finally:
        vps_patch.ROOT = original


def test_patch_feed_requires_matching_base_hashes(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    target = runtime / "proxy" / "x.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"before")
    monkeypatch.setattr(update_service, "runtime_root", lambda: runtime)
    before = hashlib.sha256(b"before").hexdigest()
    after = hashlib.sha256(b"after").hexdigest()
    payload = {
        "schema": update_service.VPS_PATCH_FEED_SCHEMA,
        "archive_url": "https://github.com/proovcme/les_rag_public/releases/download/v0.25.18/les-patch.zip",
        "archive_sha256": "a" * 64,
        "patch": {
            "schema": update_service.VPS_PATCH_SCHEMA,
            "patch_id": "p1",
            "base_commit": "b" * 40,
            "target_commit": "c" * 40,
            "product_version": "0.25.18",
            "build_number": 491,
            "files": [{"path": "proxy/x.py", "base_sha256": before, "sha256": after, "bytes": 5}],
        },
    }
    result = update_service._validate_patch_feed(payload)
    assert result["available"] is True
    assert result["compatible"] is True
    payload["patch"]["patch_id"] = "../escape"
    with pytest.raises(update_service.UpdateError, match="безопасный id"):
        update_service._validate_patch_feed(payload)
    payload["patch"]["patch_id"] = "p1"
    target.write_bytes(b"foreign")
    assert update_service._validate_patch_feed(payload)["compatible"] is False


def test_patch_feed_treats_delete_target_as_absence(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    old = runtime / "proxy" / "old_agent.py"
    helper = runtime / "tools" / "vps_patch_apply.py"
    old.parent.mkdir(parents=True)
    helper.parent.mkdir(parents=True)
    old.write_bytes(b"known old")
    helper.write_bytes(b"new helper")
    monkeypatch.setattr(update_service, "runtime_root", lambda: runtime)
    feed = _delete_github_feed()

    known = update_service.validate_github_update_feed(feed)
    assert known["available"] is True
    assert known["compatible"] is True

    old.unlink()
    absent = update_service.validate_github_update_feed(feed)
    assert absent["available"] is False
    assert absent["compatible"] is True

    old.write_bytes(b"local user edit")
    unknown = update_service.validate_github_update_feed(feed)
    assert unknown["available"] is True
    assert unknown["compatible"] is False


def test_patch_feed_rejects_nonempty_delete_marker(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    helper = runtime / "tools" / "vps_patch_apply.py"
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b"new helper")
    monkeypatch.setattr(update_service, "runtime_root", lambda: runtime)
    feed = _delete_github_feed()
    delete_entry = next(
        entry
        for entry in feed["patch"]["files"]
        if entry.get("operation") == "delete"
    )
    delete_entry["bytes"] = 1
    delete_entry["sha256"] = hashlib.sha256(b"x").hexdigest()

    with pytest.raises(update_service.UpdateError, match="маркер удаления"):
        update_service.validate_github_update_feed(feed)


@pytest.mark.parametrize(
    ("scope", "path"),
    [
        ("app", "les-desktop.exe"),
        ("runtime", "config/version.json"),
        ("runtime", "tools/windows_update_engine.py"),
    ],
)
def test_patch_feed_rejects_delete_outside_content_roots(
    tmp_path, monkeypatch, scope, path
):
    runtime = tmp_path / "runtime"
    helper = runtime / "tools" / "vps_patch_apply.py"
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b"new helper")
    target = runtime.parent / path if scope == "app" else runtime / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"known old")
    monkeypatch.setattr(update_service, "runtime_root", lambda: runtime)

    with pytest.raises(update_service.UpdateError, match="удал|операц"):
        update_service.validate_github_update_feed(
            _delete_github_feed(path=path, scope=scope)
        )


def test_github_feed_binds_repository_tag_identity_and_asset(tmp_path, monkeypatch):
    version = update_service.LES_VERSION
    build_number = update_service.BUILD_NUMBER
    runtime = tmp_path / "runtime"
    target = runtime / "proxy" / "x.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"before")
    monkeypatch.setattr(update_service, "runtime_root", lambda: runtime)
    patch = {
        "schema": update_service.VPS_PATCH_SCHEMA,
        "patch_id": "github-p1",
        "base_commit": "b" * 40,
        "target_commit": "c" * 40,
        "product_version": version,
        "build_number": build_number,
        "files": [
            {
                "path": "proxy/x.py",
                "base_sha256": hashlib.sha256(b"before").hexdigest(),
                "sha256": hashlib.sha256(b"after").hexdigest(),
                "bytes": 5,
            }
        ],
    }
    payload = {
        "schema": update_service.GITHUB_UPDATE_FEED_SCHEMA,
        "repository": "proovcme/les_rag_public",
        "release_class": "patch",
        "product_version": version,
        "build_number": build_number,
        "tag": f"v{version}",
        "target_commit": "c" * 40,
        "compatible_bases": ["b" * 40],
        "asset": {
            "url": f"https://github.com/proovcme/les_rag_public/releases/download/v{version}/les-patch.zip",
            "bytes": 123,
            "sha256": "a" * 64,
        },
        "patch": patch,
    }

    result = update_service.validate_github_update_feed(payload)

    assert result["patch_id"] == "github-p1"
    assert result["archive_url"].endswith(f"/v{version}/les-patch.zip")
    for field, foreign in (
        ("repository", "other/repo"),
        ("tag", "v0.28.3"),
        ("target_commit", "d" * 40),
    ):
        bad = json.loads(json.dumps(payload))
        bad[field] = foreign
        with pytest.raises(update_service.UpdateError):
            update_service.validate_github_update_feed(bad)


def test_older_valid_github_feed_means_no_update_for_newer_installed_build(
    tmp_path, monkeypatch
):
    runtime = tmp_path / "runtime"
    target = runtime / "proxy" / "x.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"newer-installed-content")
    monkeypatch.setattr(update_service, "runtime_root", lambda: runtime)
    monkeypatch.setattr(update_service, "BUILD_NUMBER", 649)
    patch = {
        "schema": update_service.VPS_PATCH_SCHEMA,
        "patch_id": "older-public-patch",
        "base_commit": "b" * 40,
        "target_commit": "c" * 40,
        "product_version": "0.30.7",
        "build_number": 647,
        "files": [
            {
                "path": "proxy/x.py",
                "base_sha256": hashlib.sha256(b"older-base").hexdigest(),
                "sha256": hashlib.sha256(b"older-target").hexdigest(),
                "bytes": len(b"older-target"),
            }
        ],
    }

    result = update_service.validate_github_update_feed(_github_feed(patch))

    assert result["available"] is False
    assert result["compatible"] is True
    assert result["message"] == "Установлена более новая сборка"


def test_cumulative_patch_accepts_mixed_base_and_already_updated_files(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    first = runtime / "proxy" / "first.py"
    second = runtime / "proxy" / "second.py"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"after-one")
    second.write_bytes(b"before-two")
    monkeypatch.setattr(update_service, "runtime_root", lambda: runtime)
    entries = [
        {
            "path": "proxy/first.py",
            "base_sha256": hashlib.sha256(b"before-one").hexdigest(),
            "sha256": hashlib.sha256(b"after-one").hexdigest(),
            "bytes": 9,
        },
        {
            "path": "proxy/second.py",
            "base_sha256": hashlib.sha256(b"before-two").hexdigest(),
            "sha256": hashlib.sha256(b"after-two").hexdigest(),
            "bytes": 9,
        },
    ]
    payload = {
        "schema": update_service.VPS_PATCH_FEED_SCHEMA,
        "archive_url": "https://github.com/proovcme/les_rag_public/releases/download/v0.25.18/les-patch.zip",
        "archive_sha256": "a" * 64,
        "patch": {
            "schema": update_service.VPS_PATCH_SCHEMA,
            "patch_id": "cumulative",
            "base_commit": "b" * 40,
            "target_commit": "c" * 40,
            "product_version": "0.25.18",
            "build_number": 491,
            "files": entries,
        },
    }
    result = update_service._validate_patch_feed(payload)
    assert result["available"] is True
    assert result["compatible"] is True


def test_cumulative_patch_accepts_an_exact_intermediate_release_state(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    target = runtime / "proxy" / "x.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"intermediate")
    monkeypatch.setattr(update_service, "runtime_root", lambda: runtime)
    hashes = {
        name: hashlib.sha256(value).hexdigest()
        for name, value in {
            "base": b"base",
            "intermediate": b"intermediate",
            "target": b"target",
        }.items()
    }
    entry = {
        "path": "proxy/x.py",
        "base_sha256": hashes["base"],
        "accepted_sha256": list(hashes.values()),
        "sha256": hashes["target"],
        "bytes": 6,
    }
    payload = {
        "schema": update_service.VPS_PATCH_FEED_SCHEMA,
        "archive_url": "https://github.com/proovcme/les_rag_public/releases/download/v0.25.18/les-patch.zip",
        "archive_sha256": "a" * 64,
        "patch": {
            "schema": update_service.VPS_PATCH_SCHEMA,
            "patch_id": "cumulative-intermediate",
            "base_commit": "b" * 40,
            "target_commit": "c" * 40,
            "product_version": "0.25.18",
            "build_number": 491,
            "files": [entry],
        },
    }
    assert update_service._validate_patch_feed(payload)["compatible"] is True
    assert vps_patch_apply.entry_accepts_current(entry, hashes["intermediate"]) is True
    assert vps_patch_apply.entry_accepts_current(entry, hashlib.sha256(b"foreign").hexdigest()) is False


def test_patch_feed_accepts_exact_desktop_shell_and_rejects_foreign_binary(
    tmp_path, monkeypatch
):
    runtime = tmp_path / "app" / "runtime"
    runtime.mkdir(parents=True)
    desktop = runtime.parent / "les-desktop.exe"
    desktop.write_bytes(b"installed shell")
    monkeypatch.setattr(update_service, "runtime_root", lambda: runtime)
    entry = {
        "scope": "app",
        "path": "les-desktop.exe",
        "base_sha256": hashlib.sha256(b"installed shell").hexdigest(),
        "accepted_sha256": [hashlib.sha256(b"installed shell").hexdigest()],
        "sha256": hashlib.sha256(b"new shell").hexdigest(),
        "bytes": len(b"new shell"),
    }
    payload = {
        "schema": update_service.VPS_PATCH_FEED_SCHEMA,
        "archive_url": "https://github.com/proovcme/les_rag_public/releases/download/v0.25.18/les-patch.zip",
        "archive_sha256": "a" * 64,
        "patch": {
            "schema": update_service.VPS_PATCH_SCHEMA,
            "patch_id": "app-shell",
            "base_commit": "a" * 40,
            "target_commit": "b" * 40,
            "product_version": "0.25.18",
            "build_number": 491,
            "files": [entry],
        },
    }

    assert update_service._validate_patch_feed(payload)["compatible"] is True
    desktop.write_bytes(b"foreign shell")
    assert update_service._validate_patch_feed(payload)["compatible"] is False


def test_patch_helper_is_launched_as_independent_interactive_task(tmp_path):
    helper = tmp_path / "vps patch apply.py"
    job = tmp_path / "job file.json"
    task_name, encoded = update_service._patch_task_command(helper, job, "patch:one")
    command = __import__("base64").b64decode(encoded).decode("utf-16le")
    assert task_name == "LES-Patch-patch-one"
    assert "New-ScheduledTaskPrincipal" in command
    assert "-LogonType Interactive" in command
    assert "Start-ScheduledTask" not in command
    assert "AddSeconds(2)" in command
    assert "DeleteExpiredTaskAfter" in command
    assert "EndBoundary" in command
    assert str(helper) in command
    assert str(job) in command


def test_patch_helper_uses_pythonw_when_packaged_runtime_has_it(tmp_path, monkeypatch):
    python = tmp_path / "python.exe"
    pythonw = tmp_path / "pythonw.exe"
    python.write_bytes(b"")
    pythonw.write_bytes(b"")
    monkeypatch.setattr(update_service.sys, "executable", str(python))

    _, encoded = update_service._patch_task_command(
        tmp_path / "apply.py", tmp_path / "job.json", "console-free"
    )
    command = __import__("base64").b64decode(encoded).decode("utf-16le")

    assert str(pythonw) in command
    assert str(python) not in command


@pytest.mark.asyncio
async def test_patch_check_uses_only_github_release_feed(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    file = runtime / "proxy" / "x.py"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"before")
    monkeypatch.setattr(update_service, "runtime_root", lambda: runtime)
    patch = {
        "schema": update_service.VPS_PATCH_SCHEMA,
        "patch_id": "p1",
        "base_commit": "b" * 40,
        "target_commit": "c" * 40,
        "product_version": update_service.LES_VERSION,
        "build_number": update_service.BUILD_NUMBER,
        "files": [{"path": "proxy/x.py", "base_sha256": hashlib.sha256(b"before").hexdigest(), "sha256": hashlib.sha256(b"after").hexdigest(), "bytes": 5}],
    }
    payload = _github_feed(patch)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload, request=request))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await update_service.check_vps_patch(client=client)
    assert result["patch_id"] == "p1"
    assert update_service._trusted_patch_url("https://example.invalid/updates/p.zip") is False


@pytest.mark.asyncio
async def test_github_channel_failure_is_a_non_destructive_status():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(503, text="unavailable", request=request)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        result = await update_service.check_vps_patch(client=client)

    assert result["state"] == "update_channel_unavailable"
    assert result["available"] is False
    assert result["compatible"] is False


@pytest.mark.asyncio
async def test_patch_archive_download_accepts_only_tagged_github_asset(tmp_path):
    target = tmp_path / "patch.zip"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"patch", request=request))
    async with httpx.AsyncClient(transport=transport) as client:
        await update_service._download(
            client,
            "https://github.com/proovcme/les_rag_public/releases/download/v0.28.2/les-patch.zip",
            target,
            max_bytes=64,
            trusted_url=update_service._trusted_patch_url,
        )
        with pytest.raises(update_service.UpdateError, match="недоверенный"):
            await update_service._download(
                client,
                "https://example.invalid/updates/p.zip",
                target,
                max_bytes=64,
                trusted_url=update_service._trusted_patch_url,
            )
    assert target.read_bytes() == b"patch"


def test_patch_launcher_uses_checksum_declared_target_engine(tmp_path):
    runtime = tmp_path / "runtime"
    root = tmp_path / "update"
    root.mkdir()
    for name in ("vps_patch_apply.py", "windows_update_engine.py", "windows_runtime.py"):
        path = runtime / "tools" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"old-{name}".encode())
    new_engine = b"TARGET_ENGINE = True\n"
    manifest = {
        "files": [
            {
                "scope": "runtime",
                "path": "tools/windows_update_engine.py",
                "sha256": hashlib.sha256(new_engine).hexdigest(),
                "bytes": len(new_engine),
            }
        ]
    }
    archive = tmp_path / "patch.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("payload/tools/windows_update_engine.py", new_engine)

    with zipfile.ZipFile(archive) as bundle:
        helper, engine, launcher = update_service._stage_vps_patch_launcher(
            bundle,
            manifest,
            runtime=runtime,
            root=root,
        )

    assert helper.read_bytes() == b"old-vps_patch_apply.py"
    assert engine.read_bytes() == new_engine
    assert launcher.read_bytes() == b"old-windows_runtime.py"
