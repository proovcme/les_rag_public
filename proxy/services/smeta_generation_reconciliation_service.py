"""Conservative startup reconciliation for an already verified smeta RAG generation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient

from backend.runtime_paths import mutable_path
from proxy.services.process_status import pid_running
from tools.activate_smeta_rag_generation import activate, read_smeta_ready_report


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _readiness_path(generation_dir: Path) -> Path | None:
    for name in (
        "les_smeta_norm_rag_readiness.json",
        "les_smeta_rag_readiness.json",
        "readiness.json",
    ):
        candidate = generation_dir / name
        if candidate.is_file():
            return candidate
    return None


def _alias_target(client: Any, alias: str) -> str:
    """Return the live alias target; an unreadable alias is never trusted."""
    try:
        aliases = client.get_aliases().aliases
    except Exception:
        return ""
    for item in aliases:
        if str(getattr(item, "alias_name", "")) == alias:
            return str(getattr(item, "collection_name", ""))
    return ""


def _base_metadata_matches(
    manifest_path: Path, integrity_path: Path, base_sha: str
) -> bool:
    manifest = _json(manifest_path)
    integrity = _json(integrity_path)
    return bool(
        str((manifest.get("output") or {}).get("sha256") or "").casefold()
        == base_sha
        and integrity.get("schema") == "les_smeta_base_integrity_v1"
        and integrity.get("verdict") == "passed"
        and str(integrity.get("base_sha256") or "").casefold() == base_sha
    )


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.recover")
    shutil.copy2(source, temporary)
    temporary.replace(destination)


def reconcile_matching_generation(
    *,
    base_path: Path,
    active_base_manifest_path: Path | None = None,
    active_integrity_path: Path | None = None,
    active_manifest_path: Path,
    generations_root: Path,
    alias: str,
    client: Any,
    apply: bool,
) -> dict[str, Any]:
    """Activate only an exact-SHA saved generation that still passes live checks."""
    base_path = Path(base_path)
    if not base_path.is_file():
        return {
            "status": "blocked",
            "warning_code": "SMETA_ACTIVE_BASE_MISSING",
            "message": "Активная сметная база отсутствует.",
        }
    base_sha = _sha256(base_path)
    active = _json(Path(active_manifest_path))
    active_target = str(
        active.get("physical_generation") or active.get("collection") or ""
    )
    if (
        str(active.get("base_sha256") or "").casefold() == base_sha
        and active_target
        and _alias_target(client, alias) == active_target
    ):
        return {
            "status": "already_matching",
            "base_sha256": base_sha,
            "physical_generation": active_target,
        }

    candidates: list[tuple[float, Path, dict[str, Any], Path]] = []
    root = Path(generations_root)
    if root.is_dir():
        for manifest_path in root.glob("*/les_smeta_norm_rag_manifest.json"):
            manifest = _json(manifest_path)
            target = str(manifest.get("collection") or "")
            readiness = _readiness_path(manifest_path.parent)
            if (
                manifest.get("status") == "passed"
                and str(manifest.get("base_sha256") or "").casefold() == base_sha
                and target
                and readiness is not None
            ):
                candidates.append(
                    (manifest_path.stat().st_mtime, manifest_path, manifest, readiness)
                )
    if not candidates:
        return {
            "status": "build_required",
            "base_sha256": base_sha,
            "warning_code": "SMETA_MATCHING_RAG_GENERATION_NOT_FOUND",
            "message": (
                "Для активной сметной базы нет проверенного RAG-поколения; "
                "нужна фоновая сборка."
            ),
        }

    _mtime, manifest_path, manifest, readiness_path = max(
        candidates, key=lambda item: item[0]
    )
    target = str(manifest["collection"])
    report = read_smeta_ready_report(readiness_path, target)
    if str(report.get("base_sha256") or "").casefold() != base_sha:
        return {
            "status": "blocked",
            "base_sha256": base_sha,
            "warning_code": "SMETA_SAVED_READINESS_REVISION_MISMATCH",
            "message": "Сохранённая проверка RAG относится к другой ревизии базы.",
        }
    if not apply:
        return {
            "status": "matching_generation_found",
            "base_sha256": base_sha,
            "physical_generation": target,
        }
    metadata_recovered = False
    if active_base_manifest_path is not None or active_integrity_path is not None:
        if active_base_manifest_path is None or active_integrity_path is None:
            raise ValueError("both active smeta metadata paths are required")
        active_base_manifest_path = Path(active_base_manifest_path)
        active_integrity_path = Path(active_integrity_path)
        if not _base_metadata_matches(
            active_base_manifest_path, active_integrity_path, base_sha
        ):
            saved_base_manifest = manifest_path.parent / "les_smeta_base_manifest.json"
            saved_integrity = manifest_path.parent / "les_smeta_base_integrity.json"
            if not _base_metadata_matches(
                saved_base_manifest, saved_integrity, base_sha
            ):
                return {
                    "status": "blocked",
                    "base_sha256": base_sha,
                    "warning_code": "SMETA_SAVED_BASE_METADATA_INVALID",
                    "message": (
                        "Сохранённые метаданные сметной базы не подтверждают "
                        "активную ревизию SQLite."
                    ),
                }
            _copy_atomic(saved_base_manifest, active_base_manifest_path)
            _copy_atomic(saved_integrity, active_integrity_path)
            metadata_recovered = True
    activate(
        client=client,
        alias=alias,
        target=target,
        report=report,
        manifest_source=manifest_path,
        manifest_destinations=[Path(active_manifest_path)],
    )
    return {
        "status": "activated",
        "base_sha256": base_sha,
        "physical_generation": target,
        "manifest": str(manifest_path),
        "metadata_recovered": metadata_recovered,
    }


def _runtime_reconciliation_inputs() -> dict[str, Any]:
    from proxy.smeta_core.base_registry import active_base

    config = active_base()
    base_path = Path(str(config.get("base_path") or ""))
    return {
        "base_path": base_path,
        "active_base_manifest_path": Path(str(config.get("manifest_path") or "")),
        "active_integrity_path": Path(str(config.get("integrity_path") or "")),
        "active_manifest_path": base_path.with_name(
            "les_smeta_norm_rag_manifest.json"
        ),
        "generations_root": mutable_path("storage/smeta_generations"),
        "alias": str(config.get("rag_collection") or "les_smeta_norm_cards"),
    }


def start_background_rebuild(
    *,
    base_path: Path,
    active_manifest_path: Path,
    generations_root: Path,
    alias: str,
) -> dict[str, Any]:
    pid_path = mutable_path("storage/jobs/smeta_rag_rebuild.pid")
    log_path = mutable_path("storage/jobs/smeta_rag_rebuild.log")
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid = 0
    if pid and pid_running(pid):
        return {"status": "building", "pid": pid, "alias": alias, "started": False}
    command = [
        sys.executable,
        "-m",
        "tools.rebuild_active_smeta_rag",
        "--base-path",
        str(base_path),
        "--alias",
        alias,
        "--generations-root",
        str(generations_root),
        "--active-manifest-path",
        str(active_manifest_path),
    ]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            command,
            cwd=str(Path(__file__).resolve().parents[2]),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    pid_path.write_text(str(process.pid), encoding="utf-8")
    return {
        "status": "building",
        "pid": process.pid,
        "alias": alias,
        "started": True,
        "restart_required": False,
    }


def reconcile_runtime_generation(*, apply: bool = True) -> dict[str, Any]:
    inputs = _runtime_reconciliation_inputs()
    client = QdrantClient(
        url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
        timeout=60.0,
        check_compatibility=False,
    )
    try:
        result = reconcile_matching_generation(
            **inputs,
            client=client,
            apply=apply,
        )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    if result.get("status") == "build_required" and apply:
        return start_background_rebuild(
            base_path=inputs["base_path"],
            active_manifest_path=inputs["active_manifest_path"],
            generations_root=inputs["generations_root"],
            alias=inputs["alias"],
        )
    return result
