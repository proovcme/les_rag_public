from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import pytest

from proxy.services import update_service
from tools import build_tauri_app, vps_patch, vps_patch_apply


ROOT = Path(__file__).resolve().parents[1]
APPROVED_ROOTS = {"modules/", "extensions/"}
TRUSTED_STORAGE_CODE = (
    "proxy/storage/__init__.py",
    "proxy/storage/file_storage.py",
)


def test_hatch_wheel_declares_both_approved_packages_and_no_wildcard() -> None:
    payload = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    packages = payload["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]

    assert {"modules", "extensions"}.issubset(packages)
    assert "*" not in packages
    assert "**" not in packages
    assert all(".." not in Path(package).parts for package in packages)


def test_windows_runtime_manifest_includes_only_approved_new_roots() -> None:
    payload = json.loads(
        (ROOT / "config" / "windows_runtime_manifest.json").read_text(encoding="utf-8")
    )
    prefixes = set(payload["include_prefixes"])

    assert APPROVED_ROOTS.issubset(prefixes)
    assert "*/" not in prefixes
    assert "**/" not in prefixes
    assert "plugins/" not in prefixes
    assert build_tauri_app.windows_runtime_manifest_allows(ROOT / "modules" / "sample_module.py")
    assert build_tauri_app.windows_runtime_manifest_allows(ROOT / "extensions" / "lemonade.py")
    assert not build_tauri_app.windows_runtime_manifest_allows(ROOT / "plugins" / "unsafe.py")


def test_windows_stage_keeps_only_the_exact_tracked_proxy_storage_code(
    tmp_path: Path, monkeypatch
) -> None:
    manifest = json.loads(
        (ROOT / "config" / "windows_runtime_manifest.json").read_text(encoding="utf-8")
    )
    tracked = {
        path.relative_to(ROOT).as_posix()
        for path in build_tauri_app.iter_files()
    }
    resources = tmp_path / "resources"

    assert "proxy/" in manifest["include_prefixes"]
    assert set(TRUSTED_STORAGE_CODE) <= tracked
    assert all(
        build_tauri_app.windows_runtime_manifest_allows(ROOT / path)
        for path in TRUSTED_STORAGE_CODE
    )

    monkeypatch.setattr(build_tauri_app, "RESOURCES", resources)
    monkeypatch.setattr(build_tauri_app, "stage_windows_uv", lambda _runtime, **_kwargs: 0)
    monkeypatch.setattr(build_tauri_app, "stage_windows_python", lambda _runtime, **_kwargs: 0)
    monkeypatch.setattr(build_tauri_app, "stage_windows_uv_cache", lambda _runtime, **_kwargs: 0)
    monkeypatch.setattr(build_tauri_app, "stage_windows_deploy_stamp", lambda _runtime: 0)

    build_tauri_app.stage_runtime("win32")

    for relative in TRUSTED_STORAGE_CODE:
        source = ROOT / relative
        staged = resources / "runtime" / relative
        assert staged.read_bytes() == source.read_bytes()


@pytest.mark.parametrize("path", TRUSTED_STORAGE_CODE)
def test_exact_proxy_storage_code_is_allowed_by_each_windows_updater(
    path: str, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(update_service, "runtime_root", lambda: tmp_path / "runtime")

    assert set(TRUSTED_STORAGE_CODE) == build_tauri_app.TRUSTED_APPLICATION_CODE_FILES
    assert set(TRUSTED_STORAGE_CODE) == vps_patch.TRUSTED_APPLICATION_CODE_FILES
    assert set(TRUSTED_STORAGE_CODE) == vps_patch_apply.TRUSTED_APPLICATION_CODE_FILES
    assert set(TRUSTED_STORAGE_CODE) == update_service.TRUSTED_APPLICATION_CODE_FILES
    assert not update_service._contains_forbidden_runtime_part(tuple(path.split("/")))
    assert vps_patch.normalize_path(path) == path
    assert vps_patch_apply.safe_relative_path(path).as_posix() == path
    assert path in update_service.VPS_PATCH_ALLOWED_FILES
    assert update_service._validate_patch_feed(_legacy_patch_feed(path))["compatible"] is True


@pytest.mark.parametrize(
    "path",
    [
        "proxy/storage/anything.db",
        "proxy/storage/.env",
        "proxy/storage/arbitrary-data.json",
        "proxy/storage/anything.py",
        "extensions/storage/example.py",
    ],
)
def test_updater_rejects_nontrusted_storage_paths(
    path: str, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(update_service, "runtime_root", lambda: tmp_path / "runtime")

    assert update_service._contains_forbidden_runtime_part(tuple(path.split("/")))
    with pytest.raises(ValueError, match="allowlist|unsupported"):
        vps_patch.normalize_path(path)
    with pytest.raises(RuntimeError, match="allowlist|unsupported"):
        vps_patch_apply.safe_relative_path(path)
    with pytest.raises(update_service.UpdateError, match="запрещённую|список"):
        update_service._validate_patch_feed(_legacy_patch_feed(path))


def test_windows_runtime_manifest_rejects_user_supplied_root(tmp_path: Path, monkeypatch) -> None:
    manifest = tmp_path / "runtime.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "les.windows-runtime-manifest.v1",
                "include_prefixes": ["backend/", "user-root/"],
                "include_files": ["proxy_server.py"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(build_tauri_app, "WINDOWS_RUNTIME_MANIFEST_PATH", manifest)
    build_tauri_app.windows_runtime_manifest.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="approved|prefix"):
            build_tauri_app.windows_runtime_manifest()
    finally:
        build_tauri_app.windows_runtime_manifest.cache_clear()


@pytest.mark.parametrize("root", sorted(APPROVED_ROOTS))
def test_patch_builder_and_apply_helper_allow_exact_extension_roots(root: str) -> None:
    path = f"{root}example.py"

    assert vps_patch.normalize_path(path) == path
    assert vps_patch_apply.safe_relative_path(path).as_posix() == path


@pytest.mark.parametrize(
    "path",
    [
        "plugins/example.py",
        "modules/../data/les_meta_qwen.db",
        "extensions/../../storage/secret.json",
        "modules/__pycache__/example.pyc",
    ],
)
def test_patch_boundaries_reject_arbitrary_traversal_and_protected_paths(path: str) -> None:
    with pytest.raises((ValueError, RuntimeError), match="allowlist|unsafe|denied|unsupported"):
        vps_patch.normalize_path(path)
    with pytest.raises(RuntimeError, match="allowlist|unsafe|denied|unsupported"):
        vps_patch_apply.safe_relative_path(path)


def _legacy_patch_feed(path: str) -> dict:
    content = b"approved module payload"
    digest = hashlib.sha256(content).hexdigest()
    return {
        "schema": update_service.VPS_PATCH_FEED_SCHEMA,
        "archive_url": (
            "https://github.com/proovcme/les_rag_public/"
            "releases/download/v0.30.30/les-patch.zip"
        ),
        "archive_sha256": "a" * 64,
        "archive_bytes": 100,
        "patch": {
            "schema": update_service.VPS_PATCH_SCHEMA,
            "patch_id": "extension-boundary",
            "base_commit": "b" * 40,
            "target_commit": "c" * 40,
            "product_version": "0.30.30",
            "build_number": 670,
            "files": [
                {
                    "path": path,
                    "scope": "runtime",
                    "operation": "replace",
                    "base_sha256": None,
                    "accepted_missing": True,
                    "accepted_sha256": [],
                    "sha256": digest,
                    "bytes": len(content),
                }
            ],
        },
    }


@pytest.mark.parametrize("root", sorted(APPROVED_ROOTS))
def test_update_service_accepts_approved_runtime_roots(tmp_path: Path, monkeypatch, root: str) -> None:
    monkeypatch.setattr(update_service, "runtime_root", lambda: tmp_path / "runtime")

    result = update_service._validate_patch_feed(_legacy_patch_feed(f"{root}example.py"))

    assert result["compatible"] is True
    assert result["available"] is True


def test_update_service_rejects_traversal_even_under_approved_root(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(update_service, "runtime_root", lambda: tmp_path / "runtime")

    with pytest.raises(update_service.UpdateError, match="небезопасный путь"):
        update_service._validate_patch_feed(
            _legacy_patch_feed("modules/../data/les_meta_qwen.db")
        )
