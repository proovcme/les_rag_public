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
    "qdrant_visualizer/",
    "sovushka/",
    "config/prompts/",
    "skills/",
)
PATCH_ALLOWED_FILES = {
    "env.example",
    "sovushka_ng.py",
    "proxy_server.py",
    "installers/windows/runtime-entrypoints.json",
    "tools/activate_smeta_rag_generation.py",
    "tools/build_smeta_norm_rag.py",
    "tools/build_smeta_structured_base.py",
    "tools/gesn_update_from_fgis.py",
    "tools/install_les.py",
    "tools/rebuild_active_smeta_rag.py",
    "tools/smeta_generation_coordinator.py",
    "tools/smeta_generation_lease.py",
    "tools/vps_patch.py",
    "tools/vps_patch_apply.py",
    "tools/smeta_release_baseline.py",
    "tools/smeta_model_quality_benchmark.py",
    "tools/windows_update_engine.py",
    "tools/windows_runtime.py",
    "tools/windows_env_doctor.py",
    "tools/les_runtime_control.py",
    "tools/live_workbook_acceptance.py",
    "config/version.json",
    "installers/windows/start-light.ps1",
    "installers/windows/stop-light.ps1",
    "installers/windows/runtime-process.ps1",
    "installers/windows/state.ps1",
}
PATCH_DENIED_PARTS = {"__pycache__", ".git", "migrations", "baseline", "desktop"}
PATCH_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".md", ".css", ".js", ".html", ".ps1"}
LEGACY_RUNTIME_MANIFEST_BASES = {
    "9cddee74b4818bf03d9f3e8b75ac920c85c19692",
}
PERSISTENT_RUNTIME_ROOTS = frozenset(
    {"data", "storage", "rag_content", "logs", "artifacts"}
)

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
    "config/windows_runtime_manifest.json",
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
    if normalized != "env.example" and Path(normalized).suffix.lower() not in PATCH_SUFFIXES:
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
        tool = document.get("tool")
        hatch = tool.get("hatch") if isinstance(tool, dict) else None
        build = hatch.get("build") if isinstance(hatch, dict) else None
        targets = build.get("targets") if isinstance(build, dict) else None
        wheel = targets.get("wheel") if isinstance(targets, dict) else None
        if isinstance(wheel, dict):
            wheel.pop("packages", None)
            if not wheel:
                targets.pop("wheel", None)
        if isinstance(targets, dict) and not targets:
            build.pop("targets", None)
        if isinstance(build, dict) and not build:
            hatch.pop("build", None)
        if isinstance(hatch, dict) and not hatch:
            tool.pop("hatch", None)
        if isinstance(tool, dict) and not tool:
            document.pop("tool", None)
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


def _windows_runtime_manifest(root: Path, commit: str) -> dict[str, Any] | None:
    raw = _git_bytes(root, commit, "config/windows_runtime_manifest.json")
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("runtime manifest is not valid JSON") from exc
    if payload.get("schema") != "les.windows-runtime-manifest.v1":
        raise ValueError("runtime manifest schema is invalid")
    prefixes = payload.get("include_prefixes")
    files = payload.get("include_files")
    if not isinstance(prefixes, list) or not isinstance(files, list):
        raise ValueError("runtime manifest include lists are invalid")
    if not all(isinstance(value, str) for value in [*prefixes, *files]):
        raise ValueError("runtime manifest paths are invalid")
    persistent = [
        value
        for value in [*prefixes, *files]
        if value.replace("\\", "/").strip("/").split("/", 1)[0].casefold()
        in PERSISTENT_RUNTIME_ROOTS
    ]
    if persistent:
        raise ValueError(
            f"runtime manifest cannot include persistent state: {persistent}"
        )
    return payload


def _is_declared_runtime_path(path: str, manifests: tuple[dict[str, Any], ...]) -> bool:
    return any(
        path in manifest["include_files"]
        or path.startswith(tuple(manifest["include_prefixes"]))
        for manifest in manifests
    )


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
    manifests: list[dict[str, Any] | None] = []
    for label, commit in (("base", base), ("target", target)):
        try:
            manifests.append(_windows_runtime_manifest(root, commit))
        except ValueError as exc:
            manifests.append(None)
            triggers.append(
                ReleaseTrigger(
                    "config/windows_runtime_manifest.json",
                    f"{label} runtime manifest is invalid: {exc}",
                )
            )
    legacy_manifest_introduction = (
        manifests[0] is None
        and manifests[1] is not None
        and subprocess.check_output(
            ["git", "rev-parse", base], cwd=root, text=True
        ).strip()
        in LEGACY_RUNTIME_MANIFEST_BASES
    )
    if (
        not triggers
        and (manifests[0] is None) != (manifests[1] is None)
        and not legacy_manifest_introduction
    ):
        triggers.append(
            ReleaseTrigger(
                "config/windows_runtime_manifest.json",
                "runtime manifest must exist at both release endpoints",
            )
        )
    runtime_manifests = (
        tuple(manifest for manifest in manifests if manifest is not None)
        if not triggers
        else ()
    )

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

        if runtime_manifests and not _is_declared_runtime_path(path, runtime_manifests):
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
