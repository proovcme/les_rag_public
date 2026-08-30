#!/usr/bin/env python3
"""Classify a Git diff as a lightweight runtime patch or a full release."""

from __future__ import annotations

import copy
import json
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal


PATCH_ALLOWED_ROOTS = (
    "backend/",
    "proxy/",
    "sovushka/",
    "config/prompts/",
    "skills/",
)
PATCH_ALLOWED_FILES = {
    "sovushka_ng.py",
    "proxy_server.py",
    "tools/vps_patch.py",
    "tools/vps_patch_apply.py",
    "tools/smeta_release_baseline.py",
    "tools/smeta_model_quality_benchmark.py",
    "tools/windows_update_engine.py",
    "tools/windows_runtime.py",
    "tools/windows_env_doctor.py",
    "tools/les_runtime_control.py",
    "config/version.json",
    "installers/windows/start-light.ps1",
    "installers/windows/stop-light.ps1",
    "installers/windows/runtime-process.ps1",
    "installers/windows/state.ps1",
}
PATCH_DENIED_PARTS = {"__pycache__", ".git", "migrations", "baseline", "desktop"}
PATCH_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".md", ".css", ".js", ".html", ".ps1"}

VERSION_SURFACES = {
    "pyproject.toml": "pyproject",
    "uv.lock": "uv_lock",
    "desktop/tauri/package.json": "package_json",
    "desktop/tauri/package-lock.json": "package_lock",
    "desktop/tauri/src-tauri/Cargo.toml": "cargo_toml",
    "desktop/tauri/src-tauri/Cargo.lock": "cargo_lock",
    "desktop/tauri/src-tauri/tauri.conf.json": "tauri_json",
}

RELEASE_ONLY_FILES = {
    "tools/github_patch_release.py",
    "tools/rag_dataset_story_acceptance.py",
    "tools/release_classification.py",
}


@dataclass(frozen=True)
class ReleaseTrigger:
    path: str
    reason: str


@dataclass(frozen=True)
class ReleaseClassification:
    kind: Literal["patch", "full"]
    runtime_files: tuple[str, ...]
    triggers: tuple[ReleaseTrigger, ...]
    ignored_version_surfaces: tuple[str, ...]


def normalize_patch_path(value: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe patch path: {value}")
    normalized = path.as_posix()
    if any(part in PATCH_DENIED_PARTS for part in path.parts):
        raise ValueError(f"denied patch path: {value}")
    if not (
        normalized in PATCH_ALLOWED_FILES
        or normalized.startswith(PATCH_ALLOWED_ROOTS)
    ):
        raise ValueError(f"path is outside patch allowlist: {value}")
    if Path(normalized).suffix.lower() not in PATCH_SUFFIXES:
        raise ValueError(f"unsupported patch file type: {value}")
    return normalized


def _git_bytes(root: Path, commit: str, path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"], cwd=root, capture_output=True, check=False
    )
    return result.stdout if result.returncode == 0 else None


def _changed_paths(root: Path, base: str, target: str) -> list[str]:
    output = subprocess.check_output(
        ["git", "diff", "--name-only", f"{base}..{target}"], cwd=root, text=True
    )
    return sorted(path.replace("\\", "/") for path in output.splitlines() if path.strip())


def _without_version(kind: str, raw: bytes) -> Any:
    if kind in {"package_json", "package_lock", "tauri_json"}:
        document = json.loads(raw)
    else:
        document = tomllib.loads(raw.decode("utf-8"))
    document = copy.deepcopy(document)

    if kind == "pyproject":
        document["project"]["version"] = "<VERSION>"
    elif kind == "uv_lock":
        packages = document.get("package", [])
        les_packages = [package for package in packages if package.get("name") == "les-v2"]
        if len(les_packages) != 1:
            raise ValueError("uv.lock must contain exactly one les-v2 package")
        les_packages[0]["version"] = "<VERSION>"
    elif kind == "package_json":
        document["version"] = "<VERSION>"
    elif kind == "package_lock":
        document["version"] = "<VERSION>"
        root_package = document.get("packages", {}).get("")
        if isinstance(root_package, dict) and "version" in root_package:
            root_package["version"] = "<VERSION>"
    elif kind == "cargo_toml":
        document["package"]["version"] = "<VERSION>"
    elif kind == "cargo_lock":
        packages = document.get("package", [])
        les_packages = [package for package in packages if package.get("name") == "les-desktop"]
        if len(les_packages) != 1:
            raise ValueError("Cargo.lock must contain exactly one les-desktop package")
        les_packages[0]["version"] = "<VERSION>"
    elif kind == "tauri_json":
        document["version"] = "<VERSION>"
    return document


def _is_version_only(root: Path, base: str, target: str, path: str, kind: str) -> bool:
    before = _git_bytes(root, base, path)
    after = _git_bytes(root, target, path)
    if before is None or after is None:
        return False
    try:
        return _without_version(kind, before) == _without_version(kind, after)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError):
        return False


def classify_release(base: str, target: str, *, root: Path) -> ReleaseClassification:
    root = Path(root)
    runtime_files: list[str] = []
    triggers: list[ReleaseTrigger] = []
    ignored_versions: list[str] = []

    for path in _changed_paths(root, base, target):
        parts = PurePosixPath(path).parts
        if parts[:1] in {("docs",), ("tests",), (".github",)}:
            continue
        if path in RELEASE_ONLY_FILES:
            continue

        surface_kind = VERSION_SURFACES.get(path)
        if surface_kind:
            if _is_version_only(root, base, target, path, surface_kind):
                ignored_versions.append(path)
            else:
                reason = (
                    "dependency graph changed"
                    if path == "pyproject.toml"
                    else "locked environment changed"
                    if path == "uv.lock"
                    else "version surface contains runtime changes"
                )
                triggers.append(ReleaseTrigger(path, reason))
            continue

        if path.startswith("installers/windows/app/"):
            triggers.append(ReleaseTrigger(path, "Windows bootstrap changed"))
            continue
        if path.startswith("desktop/"):
            triggers.append(ReleaseTrigger(path, "desktop runtime changed"))
            continue

        try:
            runtime_files.append(normalize_patch_path(path))
        except ValueError:
            triggers.append(ReleaseTrigger(path, "path is not allowed in a lightweight patch"))

    return ReleaseClassification(
        kind="full" if triggers else "patch",
        runtime_files=tuple(runtime_files),
        triggers=tuple(triggers),
        ignored_version_surfaces=tuple(ignored_versions),
    )
