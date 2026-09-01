from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools import release_classification
from tools.release_classification import classify_release


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo, check=True)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def release_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

    (repo / "pyproject.toml").write_text(
        '[project]\nname = "les-v2"\nversion = "0.28.1"\nrequires-python = ">=3.12,<3.14"\n'
        'dependencies = ["fastapi"]\n',
        encoding="utf-8",
    )
    (repo / "uv.lock").write_text(
        'version = 1\nrevision = 3\n\n[[package]]\nname = "les-v2"\nversion = "0.28.1"\n',
        encoding="utf-8",
    )
    desktop = repo / "desktop" / "tauri"
    desktop.mkdir(parents=True)
    (desktop / "package.json").write_text(
        json.dumps({"name": "les-desktop", "version": "0.28.1", "scripts": {"build": "vite"}}),
        encoding="utf-8",
    )
    (desktop / "src-tauri" / "src").mkdir(parents=True)
    (desktop / "src-tauri" / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    (repo / "proxy").mkdir()
    (repo / "proxy" / "existing.py").write_text("VALUE = 1\n", encoding="utf-8")
    return repo, _commit(repo, "base")


def test_version_only_project_change_remains_a_lightweight_patch(release_repo):
    repo, base = release_repo
    project = repo / "pyproject.toml"
    project.write_text(project.read_text(encoding="utf-8").replace("0.28.1", "0.28.2"), encoding="utf-8")
    lock = repo / "uv.lock"
    lock.write_text(lock.read_text(encoding="utf-8").replace("0.28.1", "0.28.2"), encoding="utf-8")

    result = classify_release(base, _commit(repo, "version"), root=repo)

    assert result.kind == "patch"
    assert result.runtime_files == ()
    assert result.ignored_version_surfaces == ("pyproject.toml", "uv.lock")
    assert result.triggers == ()


@pytest.mark.parametrize(
    ("path", "replacement", "expected_reason"),
    [
        ("pyproject.toml", ("fastapi", "fastapi>=1"), "dependency graph changed"),
        ("uv.lock", (None, "version = 1\n"), "locked environment changed"),
        (
            "installers/windows/app/bootstrap.ps1",
            (None, "Write-Host bootstrap\n"),
            "Windows bootstrap changed",
        ),
    ],
)
def test_environment_changes_require_a_full_release(
    release_repo, path, replacement, expected_reason
):
    repo, base = release_repo
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    old, new = replacement
    if old is None:
        target.write_text(new, encoding="utf-8")
    else:
        target.write_text(target.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")

    result = classify_release(base, _commit(repo, "environment"), root=repo)

    assert result.kind == "full"
    assert result.triggers[0].path == path
    assert expected_reason in result.triggers[0].reason


def test_desktop_version_is_ignored_but_native_code_requires_full_release(release_repo):
    repo, base = release_repo
    package = repo / "desktop" / "tauri" / "package.json"
    package.write_text(package.read_text(encoding="utf-8").replace("0.28.1", "0.28.2"), encoding="utf-8")
    version_target = _commit(repo, "desktop version")

    version_result = classify_release(base, version_target, root=repo)

    assert version_result.kind == "patch"
    assert version_result.ignored_version_surfaces == ("desktop/tauri/package.json",)

    native = repo / "desktop" / "tauri" / "src-tauri" / "src" / "main.rs"
    native.write_text("fn main() { println!(\"changed\"); }\n", encoding="utf-8")
    native_result = classify_release(version_target, _commit(repo, "native"), root=repo)

    assert native_result.kind == "full"
    assert native_result.triggers[0].path.endswith("main.rs")
    assert "desktop runtime changed" in native_result.triggers[0].reason


def test_allowed_runtime_file_is_packaged_and_unknown_runtime_path_blocks_patch(release_repo):
    repo, base = release_repo
    (repo / "proxy" / "new_tool.py").write_text("VALUE = 2\n", encoding="utf-8")
    patch_target = _commit(repo, "runtime")

    patch_result = classify_release(base, patch_target, root=repo)

    assert patch_result.kind == "patch"
    assert patch_result.runtime_files == ("proxy/new_tool.py",)

    (repo / "unexpected_runtime.bin").write_bytes(b"runtime")
    full_result = classify_release(patch_target, _commit(repo, "unknown"), root=repo)

    assert full_result.kind == "full"
    assert full_result.triggers[0].path == "unexpected_runtime.bin"
    assert "not allowed in a lightweight patch" in full_result.triggers[0].reason


def test_allowed_runtime_deletion_remains_lightweight_patch(release_repo):
    repo, base = release_repo
    (repo / "proxy" / "existing.py").unlink()

    result = classify_release(base, _commit(repo, "delete runtime file"), root=repo)

    assert result.kind == "patch"
    assert result.runtime_files == ("proxy/existing.py",)
    assert result.triggers == ()


def test_installed_live_acceptance_tool_can_ship_in_runtime_patch(release_repo):
    repo, base = release_repo
    tool = repo / "tools" / "live_workbook_acceptance.py"
    tool.parent.mkdir(parents=True)
    tool.write_text("VALUE = 1\n", encoding="utf-8")

    result = classify_release(base, _commit(repo, "installed acceptance repair"), root=repo)

    assert result.kind == "patch"
    assert result.runtime_files == ("tools/live_workbook_acceptance.py",)
    assert result.triggers == ()


def test_runtime_manifest_ignores_repo_only_files_and_keeps_visualizer_content(
    release_repo,
):
    repo, _base = release_repo
    manifest = repo / "config" / "windows_runtime_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema": "les.windows-runtime-manifest.v1",
                "include_prefixes": ["proxy/", "qdrant_visualizer/"],
                "include_files": ["pyproject.toml", "uv.lock"],
            }
        ),
        encoding="utf-8",
    )
    visualizer = repo / "qdrant_visualizer" / "export_data.py"
    visualizer.parent.mkdir(parents=True)
    visualizer.write_text("VALUE = 1\n", encoding="utf-8")
    readme = repo / "README.md"
    readme.write_text("base\n", encoding="utf-8")
    base = _commit(repo, "runtime manifest base")

    visualizer.unlink()
    readme.write_text("docs only\n", encoding="utf-8")
    target = _commit(repo, "runtime and docs")

    result = classify_release(base, target, root=repo)

    assert result.kind == "patch"
    assert result.runtime_files == ("qdrant_visualizer/export_data.py",)
    assert result.triggers == ()


def test_wheel_package_metadata_does_not_require_dependency_rebuild(release_repo):
    repo, base = release_repo
    project = repo / "pyproject.toml"
    project.write_text(
        project.read_text(encoding="utf-8")
        + '\n[tool.hatch.build.targets.wheel]\npackages = ["proxy"]\n',
        encoding="utf-8",
    )

    result = classify_release(base, _commit(repo, "wheel metadata"), root=repo)

    assert result.kind == "patch"
    assert result.runtime_files == ()
    assert result.triggers == ()


@pytest.mark.parametrize(
    "hatch_metadata",
    [
        '\n[tool.hatch.build.targets.sdist]\ninclude = ["proxy"]\n',
        '\n[tool.hatch.build.hooks.custom]\npath = "build_hook.py"\n',
    ],
)
def test_non_wheel_hatch_build_changes_require_full_release(
    release_repo, hatch_metadata
):
    repo, base = release_repo
    project = repo / "pyproject.toml"
    project.write_text(
        project.read_text(encoding="utf-8") + hatch_metadata,
        encoding="utf-8",
    )

    result = classify_release(base, _commit(repo, "material hatch metadata"), root=repo)

    assert result.kind == "full"
    assert result.triggers[0].path == "pyproject.toml"
    assert "dependency graph changed" in result.triggers[0].reason


@pytest.mark.parametrize("target_state", ["missing", "malformed"])
def test_runtime_manifest_must_be_valid_at_both_release_endpoints(
    release_repo, target_state
):
    repo, _base = release_repo
    manifest = repo / "config" / "windows_runtime_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema": "les.windows-runtime-manifest.v1",
                "include_prefixes": ["proxy/"],
                "include_files": ["pyproject.toml", "uv.lock"],
            }
        ),
        encoding="utf-8",
    )
    base = _commit(repo, "runtime manifest base")
    (repo / "proxy" / "new_tool.py").write_text("VALUE = 2\n", encoding="utf-8")
    if target_state == "missing":
        manifest.unlink()
    else:
        manifest.write_text("{broken", encoding="utf-8")

    result = classify_release(base, _commit(repo, "invalid runtime manifest"), root=repo)

    assert result.kind == "full"
    assert any(
        trigger.path == "config/windows_runtime_manifest.json"
        for trigger in result.triggers
    )


def test_pinned_legacy_public_base_may_introduce_runtime_manifest(
    release_repo, monkeypatch
):
    repo, base = release_repo
    manifest = repo / "config" / "windows_runtime_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema": "les.windows-runtime-manifest.v1",
                "include_prefixes": ["proxy/"],
                "include_files": ["pyproject.toml", "uv.lock"],
            }
        ),
        encoding="utf-8",
    )
    (repo / "proxy" / "new_tool.py").write_text("VALUE = 2\n", encoding="utf-8")
    target = _commit(repo, "introduce runtime manifest")
    monkeypatch.setattr(
        release_classification, "LEGACY_RUNTIME_MANIFEST_BASES", {base}
    )

    result = classify_release(base, target, root=repo)

    assert result.kind == "patch"
    assert result.runtime_files == ("proxy/new_tool.py",)
    assert result.triggers == ()


def test_release_only_tooling_does_not_force_full_runtime_release(release_repo):
    repo, base = release_repo
    tool = repo / "tools" / "github_patch_release.py"
    tool.parent.mkdir(parents=True)
    tool.write_text("VALUE = 1\n", encoding="utf-8")

    result = classify_release(base, _commit(repo, "release tooling"), root=repo)

    assert result.kind == "patch"
    assert result.runtime_files == ()
    assert result.triggers == ()
