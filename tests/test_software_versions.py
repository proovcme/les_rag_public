from __future__ import annotations

import json
import tomllib
from pathlib import Path

from proxy.services import version_service
from tools import build_tauri_app
from tools import sync_version_contract


ROOT = Path(__file__).resolve().parents[1]


def test_single_product_version_contract_is_consistent():
    contract = json.loads((ROOT / "config/version.json").read_text(encoding="utf-8"))
    assert contract["product_version"] == version_service.PRODUCT_VERSION
    assert contract["build_number"] == version_service.BUILD_NUMBER
    assert contract["desktop_version"] == version_service.DESKTOP_VERSION
    assert build_tauri_app.desktop_semver(
        contract["product_version"], contract["build_number"]
    ) == contract["desktop_version"]
    assert f'version = "{contract["product_version"]}"' in (ROOT / "pyproject.toml").read_text()
    assert f'"version": "{contract["product_version"]}"' in (
        ROOT / "desktop/tauri/package.json"
    ).read_text()
    package_lock = json.loads(
        (ROOT / "desktop/tauri/package-lock.json").read_text(encoding="utf-8")
    )
    assert package_lock["version"] == contract["product_version"]
    assert package_lock["packages"][""]["version"] == contract["product_version"]
    assert f'version = "{contract["desktop_version"]}"' in (
        ROOT / "desktop/tauri/src-tauri/Cargo.toml"
    ).read_text()
    assert f'"version": "{contract["desktop_version"]}"' in (
        ROOT / "desktop/tauri/src-tauri/tauri.conf.json"
    ).read_text()


def test_qdrant_runtime_is_pinned_everywhere():
    container_profiles = (
        "docker-compose.yml",
        "installers/windows/docker-compose.yml",
        "installers/linux/docker-compose.yml",
    )
    for relative in container_profiles:
        text = (ROOT / relative).read_text(encoding="utf-8-sig")
        assert "qdrant/qdrant:v1.17.1" in text
        assert "qdrant/qdrant:latest" not in text
    for relative in (
        "installers/windows/start-light.ps1",
        "installers/windows/app/bootstrap.ps1",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8-sig")
        assert "qdrant/qdrant:" not in text
        assert "QDRANT_URL" in text


def test_software_version_passport_records_required_runtime():
    contract = json.loads((ROOT / "config/version.json").read_text(encoding="utf-8"))
    text = (ROOT / "docs/SOFTWARE_VERSIONS.md").read_text(encoding="utf-8")
    for marker in (
        contract["product_version"], str(contract["build_number"]), contract["desktop_version"],
        "Python", "uv", "Docker", "Qdrant", "1.17.1",
        "Ollama", "0.31.1", "qwen3.5:9b", "bge-m3:latest", "BAAI/bge-reranker-v2-m3",
    ):
        assert marker in text
    assert f'| Номер сборки | `{contract["build_number"]}` |' in text


def test_version_surfaces_have_no_drift():
    assert sync_version_contract.drifted_surfaces() == []


def test_offline_lock_root_identity_matches_project_without_reresolution():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    roots = [package for package in lock["package"] if package.get("source") == {"editable": "."}]
    assert len(roots) == 1
    assert roots[0]["name"] == project["project"]["name"]
    assert roots[0]["version"] == project["project"]["version"]


def test_offline_python_support_matches_bundled_runtime():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    bundled = json.loads((ROOT / "config/windows_python.json").read_text(encoding="utf-8"))

    assert project["project"]["requires-python"].replace(" ", "") == ">=3.12,<3.14"
    assert lock["requires-python"].replace(" ", "") == ">=3.12,<3.14"
    assert bundled["version"] == "3.13.12"


def test_uv_lock_root_package_version_is_a_managed_surface():
    """Корневой пакет в uv.lock входит в контракт версии.

    Синхронизатор обновлял pyproject, но не uv.lock, поэтому расхождение повторялось при
    каждом выпуске: .125 при конфигурации .128 (аудит Codex 17.09), до этого — при .125.
    """
    import re

    contract = sync_version_contract.load_contract()
    surfaces = sync_version_contract.desired_surfaces(contract)
    lock = sync_version_contract.ROOT / "uv.lock"
    assert lock in surfaces, "uv.lock обязан быть управляемой поверхностью версии"
    match = re.search(r'name = "les-v2"\r?\nversion = "([^"]+)"', surfaces[lock])
    assert match and match.group(1) == contract["product_version"]
