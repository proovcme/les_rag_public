"""Durable ColBERT sibling-generation orchestration for Windows/Linux hosts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from backend.runtime_paths import mutable_path
from typing import Any, Callable

from backend.rag_config import index_contract_path, index_contract_payload, rag_meta_db_path
from proxy.services.lexical_index_service import lexical_db_path
from proxy.services.rag_advanced_policy_service import load_policy, load_status, save_status
from proxy.services.raptor_publication_service import (
    active_physical_collection,
    indexed_document_refs,
)
from backend.raptor_qdrant_store import source_snapshot_fingerprint
from tools.build_rag_contract_sibling import scope_manifest_payload


ROOT = Path(__file__).resolve().parents[2]
_BUILD_LOCK = threading.Lock()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def _contract_for_target(target: str) -> dict[str, Any]:
    payload = index_contract_payload()
    payload["collection"] = target
    payload.pop("fingerprint", None)
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["fingerprint"] = hashlib.sha256(stable.encode("utf-8")).hexdigest()
    return payload


def generation_plan(backend: Any, client: Any) -> dict[str, Any]:
    source = active_physical_collection(client, backend.collection_name)
    documents = indexed_document_refs(backend.db)
    fingerprint = source_snapshot_fingerprint(source, documents)
    target = f"{backend.collection_name}_colbert_{fingerprint[:12]}"
    workspace = mutable_path("storage/rag/advanced") / target
    return {
        "source": source,
        "source_alias": backend.collection_name,
        "source_fingerprint": fingerprint,
        "target": target,
        "workspace": workspace,
        "documents": len(documents),
    }


def _sync_operator_status(plan: dict[str, Any]) -> dict[str, Any]:
    workspace = Path(plan["workspace"])
    state = _read_json(workspace / "state.json")
    progress = _read_json(workspace / "progress.json")
    completed = len(progress.get("completed_datasets") or [])
    total = int(progress.get("datasets_total") or 0)
    stage = str(state.get("stage") or "preflight")
    state_status = str(state.get("status") or "queued")
    readiness = (
        "ready" if state_status in {"ready", "activated"}
        else "blocked" if state_status == "blocked"
        else "retrying" if state_status == "retrying"
        else "building"
    )
    payload = {
        "readiness": readiness,
        "progress": (completed / total) if total else 0.0,
        "stage": stage,
        "datasets_total": total,
        "datasets_completed": completed,
        "source_collection": plan["source"],
        "target_collection": plan["target"],
        "source_fingerprint": plan["source_fingerprint"],
        "workspace": str(workspace),
        "last_error_code": str(state.get("error_code") or ""),
        "last_error_detail": str(state.get("error") or "")[:500],
        "failures": int(state.get("failures") or 0),
    }
    save_status({"colbert": payload})
    return payload


def _background_process_kwargs() -> dict[str, Any]:
    if not sys.platform.startswith("win"):
        return {}
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": subprocess.STARTUPINFO(),
    }


def run_colbert_generation(
    backend: Any,
    *,
    client_factory: Callable[..., Any] | None = None,
    popen: Callable[..., Any] = subprocess.Popen,
) -> dict[str, Any]:
    """Build, gate and activate a ColBERT sibling; active evidence is untouched."""
    if not _BUILD_LOCK.acquire(blocking=False):
        raise RuntimeError("COLBERT_BUILD_ALREADY_RUNNING")
    try:
        if client_factory is None:
            from qdrant_client import QdrantClient

            client_factory = QdrantClient
        client = client_factory(
            url=backend.qdrant_url,
            timeout=30.0,
            check_compatibility=False,
        )
        plan = generation_plan(backend, client)
        workspace = Path(plan["workspace"])
        workspace.mkdir(parents=True, exist_ok=True)
        scope_path = workspace / "scope.json"
        contract_path = workspace / "contract.json"
        _write_json_atomic(scope_path, scope_manifest_payload(Path(rag_meta_db_path())))
        if not contract_path.exists():
            _write_json_atomic(contract_path, _contract_for_target(plan["target"]))
        policy = load_policy()["colbert"]
        embed_url = str(backend.embed.url).removesuffix("/v1/embeddings")
        command = [
            sys.executable,
            str(ROOT / "tools/rag_generation_supervisor.py"),
            "run",
            "--src", plan["source_alias"],
            "--dst", plan["target"],
            "--alias", plan["source_alias"],
            "--source-db", rag_meta_db_path(),
            "--scope-manifest", str(scope_path),
            "--contract-path", str(contract_path),
            "--alias-contract-path", str(index_contract_path()),
            "--lexical-db", lexical_db_path(),
            "--migration-report", str(workspace / "migration.json"),
            "--readiness-report", str(workspace / "readiness.json"),
            "--progress-path", str(workspace / "progress.json"),
            "--state-path", str(workspace / "state.json"),
            "--qdrant-url", backend.qdrant_url,
            "--embed-url", embed_url,
            "--embed-backend", str(backend.embed.backend),
            "--embedding-model", str(_contract_for_target(plan["target"])["embedding_model"]),
            "--embedding-api-model", str(backend.embed.model),
            "--rag-chunk-unit", str(_contract_for_target(plan["target"])["chunk_unit"]),
            "--with-colbert",
            "--build-only",
            "--colbert-dimension", "1024",
            "--colbert-passage-tokens", str(int(policy["max_passage_tokens"])),
            "--create-destination",
            "--max-failures", "12",
        ]
        save_status(
            {
                "colbert": {
                    "readiness": "queued",
                    "progress": 0.0,
                    "last_error_code": "",
                    "source_collection": plan["source"],
                    "target_collection": plan["target"],
                    "workspace": str(workspace),
                }
            }
        )
        while True:
            process = popen(
                command,
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **_background_process_kwargs(),
            )
            while process.poll() is None:
                _sync_operator_status(plan)
                time.sleep(2)
            status = _sync_operator_status(plan)
            if process.returncode == 0:
                return status
            if status["readiness"] != "retrying":
                return status
            time.sleep(min(30, 2 ** min(5, int(status["failures"]))))
    finally:
        _BUILD_LOCK.release()


def colbert_auto_resume_needed() -> bool:
    status = load_status()["colbert"]
    return (
        load_policy()["colbert"]["mode"] != "off"
        and str(status.get("readiness") or "") in {"queued", "building", "retrying", "verifying"}
        and bool(status.get("workspace"))
    )
