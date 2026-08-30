from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import github_patch_release, vps_patch


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


@pytest.mark.parametrize("commit_field", ["commit", "target_commit", "build_commit"])
def test_full_installer_feed_accepts_published_commit_aliases(tmp_path, commit_field):
    feed = tmp_path / "latest.json"
    payload = {
        "schema": "les.update.v1",
        "version": "0.30.0",
        "build_number": 634,
        "desktop_version": "5.1.634",
        commit_field: "a" * 40,
    }
    feed.write_text(json.dumps(payload), encoding="utf-8")

    assert github_patch_release._read_full_feed(feed) == payload


def test_patch_release_builds_exact_assets_without_installer(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "config").mkdir()
    (repo / "config" / "version.json").write_text(
        json.dumps(
            {
                "schema": "les.version.v1",
                "product_version": "0.28.1",
                "build_number": 588,
                "desktop_version": "5.1.588",
            }
        ),
        encoding="utf-8",
    )
    runtime = repo / "proxy" / "new_tool.py"
    runtime.parent.mkdir()
    runtime.write_text("VALUE = 1\n", encoding="utf-8")
    obsolete = repo / "proxy" / "obsolete.py"
    obsolete.write_text("OBSOLETE = True\n", encoding="utf-8")
    helper = repo / "tools" / "vps_patch_apply.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("BRIDGE = 1\n", encoding="utf-8")
    base = _commit(repo, "base")
    runtime.write_text("VALUE = 2\n", encoding="utf-8")
    (repo / "proxy" / "target_only.py").write_text("ADDED = True\n", encoding="utf-8")
    obsolete.unlink()
    helper.write_text("BRIDGE = 2\n", encoding="utf-8")
    version = repo / "config" / "version.json"
    contract = json.loads(version.read_text(encoding="utf-8"))
    contract.update(product_version="0.28.2", build_number=589, desktop_version="5.1.589")
    version.write_text(json.dumps(contract), encoding="utf-8")
    target = _commit(repo, "target")
    full_feed = tmp_path / "full-latest.json"
    full_feed.write_text(
        json.dumps(
            {
                "schema": "les.update.v1",
                "version": "0.28.1",
                "build_number": 588,
                "desktop_version": "5.1.588",
                "commit": base,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(vps_patch, "ROOT", repo)
    monkeypatch.setattr(github_patch_release, "ROOT", repo)
    output = tmp_path / "out"

    result = github_patch_release.build_github_patch_release(
        base, target, output, full_feed=full_feed
    )

    assert {path.name for path in output.iterdir()} == {
        "les-update.json",
        "latest.json",
        "les-patch.zip",
        "les-patch.zip.sha256",
        "release-notes.md",
    }
    assert result["release_class"] == "patch"
    assert result["tag"] == "v0.28.2"
    assert result["compatible_bases"] == [base]
    assert not (output / "LES-Setup.exe").exists()
    assert json.loads((output / "latest.json").read_text(encoding="utf-8"))["version"] == "0.28.1"
    published = json.loads((output / "les-update.json").read_text(encoding="utf-8"))
    assert published["asset"]["url"].endswith("/v0.28.2/les-patch.zip")
    assert published["asset"]["bytes"] == (output / "les-patch.zip").stat().st_size
    assert published["evidence"]["apply_ok"] is True
    assert published["evidence"]["rollback_ok"] is True
    assert published["evidence"]["new_file_removed_on_rollback"] is True
    assert published["evidence"]["skipped_version_ok"] is True
    assert published["evidence"]["deleted_files_absent_after_apply"] is True
    assert published["evidence"]["deleted_files_restored_on_rollback"] is True
    assert set(published["evidence"]["durations_ms"]) == {"apply", "rollback", "skipped_version"}

    runtime.write_text("VALUE = 3\n", encoding="utf-8")
    contract.update(product_version="0.28.3", build_number=590, desktop_version="5.1.590")
    version.write_text(json.dumps(contract), encoding="utf-8")
    second_target = _commit(repo, "existing files only")
    full_feed.write_text(
        json.dumps(
            {
                "schema": "les.update.v1",
                "version": "0.28.2",
                "build_number": 589,
                "desktop_version": "5.1.589",
                "commit": target,
            }
        ),
        encoding="utf-8",
    )

    second = github_patch_release.build_github_patch_release(
        target, second_target, tmp_path / "out-existing", full_feed=full_feed
    )

    assert second["evidence"]["new_file_removed_on_rollback"] is True


def test_publisher_uses_immutable_draft_verify_publish_sequence(tmp_path, monkeypatch):
    assets = []
    for name in github_patch_release.ASSET_NAMES:
        path = tmp_path / name
        path.write_bytes(b"verified")
        assets.append(path)
    (tmp_path / "les-update.json").write_text(
        json.dumps({
            "schema": github_patch_release.GITHUB_UPDATE_FEED_SCHEMA,
            "repository": github_patch_release.REPOSITORY,
            "tag": "v0.28.2",
            "target_commit": "c" * 40,
        }),
        encoding="utf-8",
    )
    notes = tmp_path / "notes.md"
    notes.write_text("release notes", encoding="utf-8")
    commands: list[list[str]] = []

    monkeypatch.setattr(
        github_patch_release,
        "_git",
        lambda *args: {
            ("status", "--porcelain"): "",
            ("rev-parse", "HEAD"): "c" * 40,
            ("rev-parse", "@{u}"): "c" * 40,
            ("tag", "--list", "v0.28.2"): "",
        }[args],
    )

    def run(command, **_kwargs):
        commands.append(list(command))
        if command[:3] == ["gh", "release", "view"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="not found")
        if command[:3] == ["gh", "api", f"repos/{github_patch_release.REPOSITORY}/git/ref/heads/main"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"object": {"sha": "c" * 40}}),
                stderr="",
            )
        if command[:2] == ["gh", "api"]:
            return SimpleNamespace(returncode=0, stdout='{"enabled":true}', stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(github_patch_release, "_run", run)
    monkeypatch.setattr(
        github_patch_release, "verify_downloaded_release_assets", lambda *_args: None
    )

    github_patch_release.publish_github_patch_release(
        "v0.28.2", assets, notes
    )

    create = next(command for command in commands if command[:3] == ["gh", "release", "create"])
    upload = next(command for command in commands if command[:3] == ["gh", "release", "upload"])
    publish = next(command for command in commands if command[:3] == ["gh", "release", "edit"])
    assert "--draft" in create
    assert create[create.index("--target") + 1] == "c" * 40
    assert "--notes-file" in create
    assert "--clobber" not in upload
    assert {Path(value).name for value in upload if Path(value).name in github_patch_release.ASSET_NAMES} == set(github_patch_release.ASSET_NAMES)
    assert "--draft=false" in publish
    assert commands.index(create) < commands.index(upload) < commands.index(publish)


def test_publisher_refuses_public_main_for_a_different_commit(tmp_path, monkeypatch):
    assets = []
    for name in github_patch_release.ASSET_NAMES:
        path = tmp_path / name
        path.write_bytes(b"verified")
        assets.append(path)
    (tmp_path / "les-update.json").write_text(
        json.dumps({
            "schema": github_patch_release.GITHUB_UPDATE_FEED_SCHEMA,
            "repository": github_patch_release.REPOSITORY,
            "tag": "v0.28.2",
            "target_commit": "c" * 40,
        }),
        encoding="utf-8",
    )
    notes = tmp_path / "notes.md"
    notes.write_text("notes", encoding="utf-8")
    monkeypatch.setattr(
        github_patch_release,
        "_git",
        lambda *args: {
            ("status", "--porcelain"): "",
            ("rev-parse", "HEAD"): "c" * 40,
            ("rev-parse", "@{u}"): "c" * 40,
            ("tag", "--list", "v0.28.2"): "",
        }[args],
    )
    calls = []

    def run(command, **_kwargs):
        calls.append(list(command))
        if command[:3] == ["gh", "release", "view"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="not found")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"object": {"sha": "d" * 40}}),
            stderr="",
        )

    monkeypatch.setattr(github_patch_release, "_run", run)

    with pytest.raises(RuntimeError, match="public main does not match HEAD"):
        github_patch_release.publish_github_patch_release("v0.28.2", assets, notes)
    assert calls == [
        ["gh", "release", "view", "v0.28.2", "--repo", github_patch_release.REPOSITORY],
        ["gh", "api", f"repos/{github_patch_release.REPOSITORY}/git/ref/heads/main"],
    ]


def test_publisher_refuses_existing_release_before_upload(tmp_path, monkeypatch):
    assets = []
    for name in github_patch_release.ASSET_NAMES:
        path = tmp_path / name
        path.write_bytes(b"verified")
        assets.append(path)
    (tmp_path / "les-update.json").write_text(
        json.dumps({
            "schema": github_patch_release.GITHUB_UPDATE_FEED_SCHEMA,
            "repository": github_patch_release.REPOSITORY,
            "tag": "v0.28.2",
            "target_commit": "c" * 40,
        }),
        encoding="utf-8",
    )
    notes = tmp_path / "notes.md"
    notes.write_text("notes", encoding="utf-8")
    monkeypatch.setattr(
        github_patch_release,
        "_git",
        lambda *args: "" if args != ("rev-parse", "HEAD") and args != ("rev-parse", "@{u}") else "c" * 40,
    )
    calls = []

    def run(command, **_kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout="existing", stderr="")

    monkeypatch.setattr(github_patch_release, "_run", run)

    with pytest.raises(RuntimeError, match="already exists"):
        github_patch_release.publish_github_patch_release("v0.28.2", assets, notes)
    assert not any(command[:3] == ["gh", "release", "upload"] for command in calls)


def test_publisher_refuses_feed_for_a_different_commit_before_github_calls(tmp_path, monkeypatch):
    assets = []
    for name in github_patch_release.ASSET_NAMES:
        path = tmp_path / name
        path.write_bytes(b"verified")
        assets.append(path)
    (tmp_path / "les-update.json").write_text(
        json.dumps({
            "schema": github_patch_release.GITHUB_UPDATE_FEED_SCHEMA,
            "repository": github_patch_release.REPOSITORY,
            "tag": "v0.28.2",
            "target_commit": "d" * 40,
        }),
        encoding="utf-8",
    )
    notes = tmp_path / "notes.md"
    notes.write_text("notes", encoding="utf-8")
    monkeypatch.setattr(
        github_patch_release,
        "_git",
        lambda *args: {
            ("status", "--porcelain"): "",
            ("rev-parse", "HEAD"): "c" * 40,
            ("rev-parse", "@{u}"): "c" * 40,
        }[args],
    )
    calls = []
    monkeypatch.setattr(github_patch_release, "_run", lambda command, **_kwargs: calls.append(command))

    with pytest.raises(RuntimeError, match="feed target commit does not match HEAD"):
        github_patch_release.publish_github_patch_release("v0.28.2", assets, notes)
    assert calls == []
