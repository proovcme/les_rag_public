from pathlib import Path

from tools import build_release_artifacts, clean_install_smoke


ROOT = Path(__file__).resolve().parents[1]


def test_platform_installer_files_exist():
    expected = [
        ROOT / "installers" / "linux" / "install.sh",
        ROOT / "installers" / "linux" / "docker-compose.yml",
        ROOT / "installers" / "linux" / "systemd" / "les-proxy.service",
        ROOT / "installers" / "linux" / "systemd" / "les-ui.service",
        ROOT / "installers" / "windows" / "install.ps1",
        ROOT / "installers" / "windows" / "docker-compose.yml",
        ROOT / "installers" / "macos" / "install.sh",
        ROOT / "installers" / "macos" / "uninstall.sh",
        ROOT / "docs" / "MAC_REINSTALL_STRESS.md",
    ]

    for path in expected:
        assert path.exists(), path


def test_release_artifact_excludes_private_runtime_paths():
    excluded = [
        ROOT / ".env",
        ROOT / "data" / "les_meta.db",
        ROOT / "storage" / "x",
        ROOT / "RAG_Content" / "private.pdf",
        ROOT / "artifacts" / "snapshot.bin",
        ROOT / "local_private_archive" / "sample.ifc",
        ROOT / "frontend" / "cad_bim_viewer" / "node_modules" / "x",
        ROOT / ".claude" / "worktrees" / "scratch" / "x",
        ROOT / ".DS_Store",
        ROOT / ".qdrant-initialized",
        ROOT / "legacy" / "data" / "les_metrics.db.bak",
        ROOT / "exporters" / "artifacts" / "exporters.zip",
        ROOT / "products" / "artel" / "MyVeras.Core" / "obj" / "project.assets.json",
        ROOT / "products" / "artel" / "MyVeras.Core" / "bin" / "Release" / "x.dll",
    ]

    for path in excluded:
        assert build_release_artifacts.should_exclude(path), path


def test_release_artifact_keeps_installer_and_docs_paths():
    included = [
        ROOT / "installers" / "linux" / "install.sh",
        ROOT / "docs" / "PACKAGING.md",
        ROOT / "tools" / "lesctl.py",
        ROOT / "tools" / "clean_install_smoke.py",
        ROOT / "standalone" / "cad_bim_viewer" / "README.md",
    ]

    for path in included:
        assert not build_release_artifacts.should_exclude(path), path


def test_clean_install_smoke_does_not_copy_local_runtime_state():
    ignored = clean_install_smoke.ignore_copy(
        "/repo",
        [
            ".env",
            "local.env",
            "data",
            "storage",
            "RAG_Content",
            "dist",
            "README.md",
        ],
    )

    assert {".env", "local.env", "data", "storage", "RAG_Content", "dist"} <= ignored
    assert "README.md" not in ignored
