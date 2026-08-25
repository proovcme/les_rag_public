from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tools import github_patch_release, vps_patch


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


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
    base = _commit(repo, "base")
    runtime.write_text("VALUE = 2\n", encoding="utf-8")
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
