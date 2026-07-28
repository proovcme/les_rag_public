from __future__ import annotations

import json
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
    files = (
        "docker-compose.yml",
        "installers/windows/docker-compose.yml",
        "installers/linux/docker-compose.yml",
        "installers/windows/start-light.ps1",
        "installers/windows/app/bootstrap.ps1",
    )
    for relative in files:
        text = (ROOT / relative).read_text(encoding="utf-8-sig")
        assert "qdrant/qdrant:v1.17.1" in text
        assert "qdrant/qdrant:latest" not in text


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
