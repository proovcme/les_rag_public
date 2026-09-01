#!/usr/bin/env python3
"""Validate dynamic Windows runtime entrypoints before Tauri/NSIS."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any


REGISTRY_SCHEMA = "les.windows-runtime-entrypoints.v1"
RESULT_SCHEMA = "les.windows-runtime-entrypoint-check.v1"
KINDS = {"python_module", "python_script", "powershell", "executable"}
_MODULE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_POWERSHELL_MODULE = re.compile(
    r"\bpython(?:\.exe)?\s+-m\s+([A-Za-z_][A-Za-z0-9_.]*)",
    re.IGNORECASE,
)
_POWERSHELL_TARGET = re.compile(
    r"(?:&\s*[\"']?|-[Ff]ile\s+[\"']?|python(?:\.exe)?\s+)"
    r"(?P<target>[A-Za-z0-9_.\\/-]+\.(?:py|ps1|exe))",
    re.IGNORECASE,
)


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must be an object")
    return payload


def _safe_relative(value: str) -> str:
    normalized = str(value or "").replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or ":" in normalized
    ):
        raise ValueError(f"unsafe runtime entrypoint path: {value}")
    return path.as_posix()


def _manifest_allows(relative: str, manifest: dict[str, Any]) -> bool:
    files = {str(item).replace("\\", "/") for item in manifest.get("include_files", [])}
    prefixes = tuple(
        str(item).replace("\\", "/") for item in manifest.get("include_prefixes", [])
    )
    return relative in files or relative.startswith(prefixes)


def _module_paths(module: str) -> tuple[str, str]:
    base = module.replace(".", "/")
    return f"{base}.py", f"{base}/__main__.py"


def _literal_targets(path: Path, staged_root: Path) -> set[tuple[str, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise RuntimeError(f"runtime entrypoint callsite is unreadable: {path.name}") from exc
    discovered: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        values = [
            item.value if isinstance(item, ast.Constant) and isinstance(item.value, str) else None
            for item in node.elts
        ]
        for index, value in enumerate(values[:-1]):
            candidate = values[index + 1]
            if value == "-m" and candidate and _MODULE.fullmatch(candidate):
                discovered.add(("python_module", candidate))
        for value in values:
            if not value:
                continue
            normalized = value.replace("\\", "/")
            kind = (
                "python_script" if normalized.endswith(".py")
                else "powershell" if normalized.endswith(".ps1")
                else "executable" if normalized.endswith(".exe")
                else ""
            )
            if kind and not PurePosixPath(normalized).is_absolute() and (
                staged_root / normalized
            ).is_file():
                discovered.add((kind, normalized))
    return discovered


def _discover_targets(staged_root: Path) -> set[tuple[str, str]]:
    discovered: set[tuple[str, str]] = set()
    for path in sorted(Path(staged_root).rglob("*.py")):
        discovered.update(_literal_targets(path, Path(staged_root)))
    for path in sorted(Path(staged_root).rglob("*.ps1")):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise RuntimeError(f"runtime entrypoint callsite is unreadable: {path.name}") from exc
        discovered.update(("python_module", item) for item in _POWERSHELL_MODULE.findall(text))
        for match in _POWERSHELL_TARGET.finditer(text):
            target = match.group("target").replace("\\", "/")
            if not (Path(staged_root) / target).is_file():
                continue
            kind = (
                "python_script" if target.casefold().endswith(".py")
                else "powershell" if target.casefold().endswith(".ps1")
                else "executable"
            )
            discovered.add((kind, target))
    return discovered


def load_registry(path: Path) -> dict[str, Any]:
    payload = _json(path, "Windows runtime entrypoint registry")
    if payload.get("schema") != REGISTRY_SCHEMA or not isinstance(payload.get("entries"), list):
        raise RuntimeError("Windows runtime entrypoint registry schema is invalid")
    return payload


def validate_registry(
    *,
    root: Path,
    staged_root: Path,
    runtime_manifest: Path,
    registry_path: Path,
) -> dict[str, Any]:
    root = Path(root).resolve()
    staged_root = Path(staged_root).resolve()
    manifest = _json(runtime_manifest, "Windows runtime manifest")
    if manifest.get("schema") != "les.windows-runtime-manifest.v1":
        raise RuntimeError("Windows runtime manifest schema is invalid")
    registry = load_registry(registry_path)
    ids: set[str] = set()
    targets: set[tuple[str, str]] = set()
    declared_targets: set[tuple[str, str]] = set()
    validated_ids: list[str] = []
    for raw in registry["entries"]:
        if not isinstance(raw, dict):
            raise ValueError("runtime entrypoint entry must be an object")
        entry_id = str(raw.get("id") or "")
        kind = str(raw.get("kind") or "")
        target = str(raw.get("target") or "")
        if re.fullmatch(r"[a-z][a-z0-9-]{1,63}", entry_id) is None:
            raise ValueError("runtime entrypoint id is invalid")
        if entry_id in ids or kind not in KINDS or not target:
            raise ValueError("runtime entrypoint identity is invalid")
        if (kind, target) in targets:
            raise ValueError("runtime entrypoint target is duplicated")
        ids.add(entry_id)
        targets.add((kind, target))
        required = [_safe_relative(str(item)) for item in raw.get("required_files", [])]
        callsites = [_safe_relative(str(item)) for item in raw.get("callsites", [])]
        if not required or not callsites:
            raise ValueError("runtime entrypoint requires files and callsites")
        for relative in [*required, *callsites]:
            if not _manifest_allows(relative, manifest):
                raise RuntimeError(f"MISSING_RUNTIME_ENTRYPOINT: {entry_id}: {relative} is not in runtime manifest")
            if not (staged_root / Path(relative)).is_file():
                raise RuntimeError(f"MISSING_RUNTIME_ENTRYPOINT: {entry_id}: {relative}")
        for relative in callsites:
            source = root / Path(relative)
            if not source.is_file():
                raise RuntimeError(f"MISSING_RUNTIME_ENTRYPOINT: {entry_id}: callsite {relative}")
            if target not in source.read_text(encoding="utf-8-sig"):
                raise RuntimeError(f"MISSING_RUNTIME_ENTRYPOINT: {entry_id}: callsite does not name target")
        if kind == "python_module":
            if _MODULE.fullmatch(target) is None:
                raise ValueError("python_module target is invalid")
            module_files = _module_paths(target)
            locked_distribution = raw.get("resolution") == "locked_distribution"
            if not locked_distribution and not any(relative in required for relative in module_files):
                raise RuntimeError(f"MISSING_RUNTIME_ENTRYPOINT: {entry_id}: module target is undeclared")
            if locked_distribution and "uv.lock" not in required:
                raise RuntimeError(f"MISSING_RUNTIME_ENTRYPOINT: {entry_id}: locked module has no uv.lock")
        declared_targets.add((kind, target.replace("\\", "/")))
        validated_ids.append(entry_id)
    undisclosed = sorted(_discover_targets(staged_root) - declared_targets)
    if undisclosed:
        raise RuntimeError(
            "UNREGISTERED_RUNTIME_ENTRYPOINT: "
            + ", ".join(f"{kind}:{target}" for kind, target in undisclosed)
        )
    registry_sha = hashlib.sha256(Path(registry_path).read_bytes()).hexdigest()
    return {
        "schema": RESULT_SCHEMA,
        "entry_count": len(validated_ids),
        "registry_sha256": registry_sha,
        "validated_ids": sorted(validated_ids),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--staged-root", type=Path, required=True)
    parser.add_argument("--runtime-manifest", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    args = parser.parse_args(argv)
    result = validate_registry(
        root=args.root,
        staged_root=args.staged_root,
        runtime_manifest=args.runtime_manifest,
        registry_path=args.registry,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
