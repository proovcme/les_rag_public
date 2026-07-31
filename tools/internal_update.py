#!/usr/bin/env python3
"""Prepare once and apply fast internal LES updates without publication."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools import internal_dual_deploy, patch_release
from tools.build_tauri_app import build as build_tauri
from tools.multiplatform_release import verify_macos_artifacts
from tools.smeta_release_baseline import create_archive


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BRANCH = "codex/audit-rag"
CACHE_ROOT = Path(
    os.getenv(
        "LES_UPDATE_CACHE",
        str(internal_dual_deploy.MAC_RUNTIME.parent / "LES_update_cache" / "audit-rag"),
    )
).resolve()
SCHEMA = "les.internal_update_bundle.v1"


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _copy_to_cache(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    if sys.platform == "darwin":
        cloned = subprocess.run(
            ["cp", "-c", str(source), str(temporary)],
            cwd=ROOT,
            check=False,
            capture_output=True,
        )
        if cloned.returncode != 0:
            shutil.copy2(source, temporary)
    else:
        shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def _manifest_path(commit: str) -> Path:
    return CACHE_ROOT / commit / "manifest.json"


def _write_manifest(payload: dict[str, Any]) -> Path:
    path = _manifest_path(str(payload["commit"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("manifest.json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


def _validate_artifact(item: dict[str, Any], label: str) -> None:
    path = Path(str(item.get("path") or ""))
    if not path.is_file():
        raise RuntimeError(f"prepared {label} is missing: {path}")
    if int(item.get("bytes") or -1) != path.stat().st_size:
        raise RuntimeError(f"prepared {label} size changed: {path}")
    if str(item.get("sha256") or "") != sha256_file(path):
        raise RuntimeError(f"prepared {label} checksum changed: {path}")


def load_prepared_bundle(*, require_windows: bool = False) -> dict[str, Any]:
    contract = patch_release.load_contract()
    commit = patch_release.require_clean_pushed_branch(BRANCH)
    path = _manifest_path(commit)
    if not path.is_file():
        raise RuntimeError(
            f"update {commit[:8]} is not prepared; run make prepare-audit-rag"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema": SCHEMA,
        "branch": BRANCH,
        "commit": commit,
        "product_version": contract["product_version"],
        "build_number": int(contract["build_number"]),
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise RuntimeError(
                f"prepared update identity mismatch for {key}: "
                f"{payload.get(key)!r} != {value!r}"
            )
    if payload.get("status") not in {"local_prepared", "dual_prepared"}:
        raise RuntimeError("prepared update is not in an applicable state")
    artifacts = payload.get("artifacts") or {}
    _validate_artifact(artifacts.get("mac_dmg") or {}, "Mac DMG")
    _validate_artifact(artifacts.get("smeta_baseline") or {}, "smeta baseline")
    if require_windows:
        windows = payload.get("windows") or {}
        if windows.get("status") != "prepared":
            raise RuntimeError(
                "Legion artifact is not prepared; run make prepare-audit-rag-legion"
            )
        if windows.get("commit") != commit:
            raise RuntimeError("prepared Legion artifact has a different commit")
    return payload


def prepare_local(*, force: bool = False) -> dict[str, Any]:
    contract = patch_release.load_contract()
    commit = patch_release.require_clean_pushed_branch(BRANCH)
    manifest_path = _manifest_path(commit)
    if not force and manifest_path.is_file():
        cached = load_prepared_bundle()
        cached["cache_hit"] = True
        return cached

    gates: dict[str, Any] = {}
    for name, command in (
        ("verify", ["make", "verify"]),
        ("test", ["make", "test"]),
        ("rag_core", ["make", "test-rag-core"]),
    ):
        run(command)
        gates[name] = "passed"
    gates.update(internal_dual_deploy.rag_gate_status())

    DIST.mkdir(exist_ok=True)
    build_tauri(
        str(contract["product_version"]),
        "app,dmg",
        build_number=int(contract["build_number"]),
    )
    mac_validation = verify_macos_artifacts(DIST / "LES.app", DIST / "LES.dmg")
    baseline = DIST / "LES-smeta-baseline.zip"
    create_archive(ROOT, baseline)
    slot = CACHE_ROOT / commit
    cached_dmg = slot / "LES.dmg"
    cached_baseline = slot / "LES-smeta-baseline.zip"
    _copy_to_cache(DIST / "LES.dmg", cached_dmg)
    _copy_to_cache(baseline, cached_baseline)
    if patch_release.output(["git", "status", "--porcelain"]):
        raise RuntimeError("preparation changed tracked source files")

    payload = {
        "schema": SCHEMA,
        "status": "local_prepared",
        "published": False,
        "branch": BRANCH,
        "commit": commit,
        "product_version": contract["product_version"],
        "build_number": int(contract["build_number"]),
        "index_contract": "les.rag.index-contract.v2",
        "prepared_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gates": gates,
        "artifacts": {
            "mac_dmg": _artifact(cached_dmg),
            "smeta_baseline": _artifact(cached_baseline),
        },
        "mac_validation": mac_validation,
        "windows": {"status": "not_prepared"},
        "cache_hit": False,
    }
    _write_manifest(payload)
    return payload


def prepare_legion(*, host: str, repo_root: str) -> dict[str, Any]:
    payload = load_prepared_bundle()
    baseline = Path(payload["artifacts"]["smeta_baseline"]["path"])
    windows = patch_release.remote_prepare_update(
        host=host,
        repo_root=repo_root,
        branch=BRANCH,
        version=str(payload["product_version"]),
        build_number=int(payload["build_number"]),
        commit=str(payload["commit"]),
        smeta_baseline_archive=baseline,
        smeta_baseline_sha256=str(payload["artifacts"]["smeta_baseline"]["sha256"]),
    )
    payload["windows"] = windows
    payload["status"] = "dual_prepared"
    payload["cache_hit"] = False
    _write_manifest(payload)
    return payload


def apply_update(*, hosts: set[str], legion_host: str, legion_root: str) -> dict[str, Any]:
    if not hosts or not hosts <= {"mac", "legion"}:
        raise RuntimeError("hosts must contain mac and/or legion")
    payload = load_prepared_bundle(require_windows="legion" in hosts)
    contract = patch_release.load_contract()
    commit = str(payload["commit"])
    transaction = internal_dual_deploy.MacTransaction(
        commit,
        str(contract["product_version"]),
        int(contract["build_number"]),
    )
    mac: dict[str, Any] = {"status": "not_requested"}
    legion: dict[str, Any] = {"status": "not_requested"}
    try:
        if "mac" in hosts:
            mac = transaction.apply()
        if "legion" in hosts:
            legion = patch_release.remote_apply_prepared_update(
                host=legion_host,
                repo_root=legion_root,
                branch=BRANCH,
                version=str(contract["product_version"]),
                build_number=int(contract["build_number"]),
                commit=commit,
            )
        report = {
            "schema": "les.internal_update_apply.v1",
            "status": "ok",
            "published": False,
            "commit": commit,
            "product_version": contract["product_version"],
            "build_number": int(contract["build_number"]),
            "hosts": sorted(hosts),
            "mac": mac,
            "legion": legion,
        }
        return report
    except Exception:
        if "mac" in hosts:
            transaction.rollback()
        raise


def preflight() -> dict[str, Any]:
    contract = patch_release.load_contract()
    commit = patch_release.require_clean_pushed_branch(BRANCH)
    prepared = False
    cache_status = "absent"
    if _manifest_path(commit).is_file():
        try:
            load_prepared_bundle()
            prepared = True
            cache_status = "valid"
        except RuntimeError as exc:
            cache_status = f"blocked: {exc}"
    mac_identity: dict[str, Any] = {"status": "unavailable"}
    try:
        mac_identity = internal_dual_deploy._version_identity(
            internal_dual_deploy._json_url("http://127.0.0.1:8050/api/version", timeout=5)
        )
    except Exception:  # noqa: BLE001
        pass
    return {
        "schema": "les.internal_update_preflight.v1",
        "status": "ok",
        "published": False,
        "branch": BRANCH,
        "commit": commit,
        "product_version": contract["product_version"],
        "build_number": int(contract["build_number"]),
        "cache_root": str(CACHE_ROOT),
        "cache_status": cache_status,
        "prepared": prepared,
        "mac_runtime": mac_identity,
        "legion_contacted": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("preflight", "prepare", "prepare-legion", "apply", "inspect"),
    )
    parser.add_argument("--hosts", default="mac,legion")
    parser.add_argument("--legion-host", default="zt-legion")
    parser.add_argument("--legion-root", default=r"C:\Users\Oleg\les_rag")
    parser.add_argument("--force", action="store_true")
    args, unknown = parser.parse_known_args(argv)
    if "--publish" in unknown or "--publish" in (argv or sys.argv[1:]):
        raise RuntimeError("--publish is forbidden for internal updates")
    if unknown:
        raise RuntimeError("unknown arguments: " + " ".join(unknown))

    if args.command == "preflight":
        payload = preflight()
    elif args.command == "prepare":
        payload = prepare_local(force=args.force)
    elif args.command == "prepare-legion":
        payload = prepare_legion(host=args.legion_host, repo_root=args.legion_root)
    elif args.command == "apply":
        payload = apply_update(
            hosts={item.strip() for item in args.hosts.split(",") if item.strip()},
            legion_host=args.legion_host,
            legion_root=args.legion_root,
        )
    else:
        payload = load_prepared_bundle()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        print(f"internal update failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
