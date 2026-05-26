#!/usr/bin/env python3
"""Guarded production reindex for selected datasets.

The tool reindexes already indexed documents by marking exactly one target
document as PENDING, running /api/rag/parse-batch/{dataset_id}?limit=1, and
verifying SQLite/Qdrant health before moving to the next document.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.rag_config import rag_collection_name, rag_meta_db_path


ACTIVE_JOB_STATUSES = {"QUEUED", "PARSING", "RUNNING"}
DEFAULT_DATASETS = ["NTD_HVAC_Index", "NTD_FIRE_Index"]


@dataclass(frozen=True)
class TargetDoc:
    id: str
    dataset_id: str
    dataset_name: str
    file_name: str
    file_size: int
    chunk_count: int


def mask_key(key: str) -> str:
    key = str(key or "")
    if not key:
        return "<empty>"
    if len(key) <= 4:
        return f"*** ({len(key)} chars)"
    return f"{key[:2]}...{key[-2:]} ({len(key)} chars)"


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def run_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def emit(log_path: Path | None, event: str, **fields: Any) -> None:
    item = {"ts": timestamp(), "event": event, **fields}
    line = json.dumps(item, ensure_ascii=False, sort_keys=True)
    print(line, flush=True)
    if log_path is not None:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 30,
    api_key: str = "",
) -> tuple[int, dict[str, Any] | list[Any] | str]:
    data = None
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(resp.status)
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        body = exc.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return 0, {"error": str(exc)}

    try:
        return status, json.loads(body or "{}")
    except json.JSONDecodeError:
        return status, body[:1000]


def require_json_dict(status: int, body: dict[str, Any] | list[Any] | str, label: str) -> dict[str, Any]:
    if status != 200 or not isinstance(body, dict):
        raise RuntimeError(f"{label} failed: HTTP {status}: {body}")
    return body


def sqlite_connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def backup_sqlite(db_path: str, run_dir: Path) -> Path:
    source = Path(db_path)
    if not source.exists():
        raise FileNotFoundError(f"SQLite DB does not exist: {source}")
    backup = run_dir / f"{source.name}.bak"
    with sqlite3.connect(source) as src, sqlite3.connect(backup) as dst:
        src.backup(dst)
    return backup


def dataset_summaries(db_path: str, dataset_names: list[str]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in dataset_names)
    sql = f"""
        SELECT d.id,
               d.name,
               d.status,
               COUNT(doc.id) AS total_files,
               SUM(CASE WHEN doc.status='INDEXED' THEN 1 ELSE 0 END) AS indexed_files,
               SUM(CASE WHEN doc.status='PENDING' THEN 1 ELSE 0 END) AS pending_files,
               SUM(CASE WHEN doc.status='ERROR' THEN 1 ELSE 0 END) AS error_files,
               COALESCE(SUM(CASE WHEN doc.status='INDEXED' THEN doc.chunk_count ELSE 0 END), 0) AS chunks
        FROM datasets d
        LEFT JOIN documents doc ON doc.dataset_id=d.id
        WHERE d.name IN ({placeholders})
        GROUP BY d.id, d.name, d.status
        ORDER BY d.name
    """
    with sqlite_connect(db_path) as conn:
        rows = conn.execute(sql, dataset_names).fetchall()
    return [dict(row) for row in rows]


def load_target_docs(db_path: str, dataset_names: list[str], max_docs: int = 0) -> list[TargetDoc]:
    placeholders = ",".join("?" for _ in dataset_names)
    sql = f"""
        SELECT doc.id,
               doc.dataset_id,
               d.name AS dataset_name,
               doc.file_name,
               COALESCE(doc.file_size, 0) AS file_size,
               COALESCE(doc.chunk_count, 0) AS chunk_count
        FROM documents doc
        JOIN datasets d ON d.id=doc.dataset_id
        WHERE d.name IN ({placeholders})
          AND doc.status='INDEXED'
        ORDER BY d.name, COALESCE(NULLIF(doc.file_size, 0), 9223372036854775807), doc.file_name
    """
    params: list[Any] = list(dataset_names)
    if max_docs > 0:
        sql += " LIMIT ?"
        params.append(max_docs)
    with sqlite_connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [TargetDoc(**dict(row)) for row in rows]


def load_doc(db_path: str, doc_id: str) -> dict[str, Any] | None:
    with sqlite_connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, dataset_id, file_name, status, chunk_count, last_error "
            "FROM documents WHERE id=?",
            (doc_id,),
        ).fetchone()
    return dict(row) if row else None


def mark_doc_pending(db_path: str, doc: TargetDoc) -> None:
    conn = sqlite_connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT status FROM documents WHERE id=?",
            (doc.id,),
        ).fetchone()
        if not row:
            raise RuntimeError(f"document disappeared: {doc.id}")
        if row["status"] != "INDEXED":
            raise RuntimeError(f"document is not INDEXED anymore: {doc.file_name} status={row['status']}")
        cur = conn.execute(
            "UPDATE documents SET status='PENDING', chunk_count=0, last_error='' "
            "WHERE id=? AND status='INDEXED'",
            (doc.id,),
        )
        if cur.rowcount != 1:
            raise RuntimeError(f"failed to mark document pending: {doc.file_name}")
        conn.execute("UPDATE datasets SET status='IDLE' WHERE id=?", (doc.dataset_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def restore_doc_indexed(db_path: str, doc: TargetDoc) -> None:
    conn = sqlite_connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE documents SET status='INDEXED', chunk_count=?, last_error='' WHERE id=?",
            (doc.chunk_count, doc.id),
        )
        conn.execute(
            "UPDATE datasets SET chunk_count=("
            "SELECT COALESCE(SUM(chunk_count), 0) FROM documents "
            "WHERE dataset_id=? AND status='INDEXED'"
            "), status='IDLE' WHERE id=?",
            (doc.dataset_id, doc.dataset_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def local_admin_key(auth_db_path: str) -> str:
    with sqlite_connect(auth_db_path) as conn:
        row = conn.execute(
            "SELECT key_value FROM auth_keys "
            "WHERE role='admin' AND is_active=1 "
            "AND (expires_at IS NULL OR expires_at > datetime('now','localtime')) "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        raise RuntimeError(f"no active admin key in {auth_db_path}")
    return str(row["key_value"])


def active_keys_by_role(auth_db_path: str) -> dict[str, dict[str, str]]:
    with sqlite_connect(auth_db_path) as conn:
        rows = conn.execute(
            "SELECT key_value, holder_name, role FROM auth_keys "
            "WHERE is_active=1 "
            "AND (expires_at IS NULL OR expires_at > datetime('now','localtime')) "
            "ORDER BY role, created_at DESC"
        ).fetchall()
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        role = str(row["role"])
        result.setdefault(
            role,
            {
                "key_value": str(row["key_value"]),
                "holder_name": str(row["holder_name"] or ""),
                "role": role,
            },
        )
    return result


def health_snapshot(proxy_url: str, timeout: float, api_key: str) -> dict[str, Any]:
    status, body = request("GET", f"{proxy_url}/api/health", timeout=timeout, api_key=api_key)
    data = require_json_dict(status, body, "proxy health")
    rag = data.get("rag") or {}
    if not isinstance(rag, dict):
        raise RuntimeError(f"proxy health has no rag snapshot: {data}")
    qdrant = rag.get("qdrant") or {}
    if not qdrant.get("ok", False):
        raise RuntimeError(f"Qdrant is not healthy in proxy snapshot: {qdrant}")
    if qdrant.get("points_match_sqlite_chunks") is False:
        raise RuntimeError(f"Qdrant/SQLite mismatch: {qdrant.get('mismatch')}")
    return data


def mlx_memory(mlx_url: str, timeout: float) -> dict[str, Any]:
    status, body = request("GET", f"{mlx_url}/api/health", timeout=timeout)
    data = require_json_dict(status, body, "MLX health")
    memory = data.get("memory") or {}
    return {
        "ram_free_gb": float(memory.get("ram_free_gb") if memory.get("ram_free_gb") is not None else 0),
        "swap_pct": float(memory.get("swap_pct") if memory.get("swap_pct") is not None else 100),
        "raw": memory,
    }


def assert_memory(memory: dict[str, Any], min_free_gb: float, max_swap_pct: float) -> None:
    free = float(memory.get("ram_free_gb") or 0)
    swap = float(memory.get("swap_pct") if memory.get("swap_pct") is not None else 100)
    if free < min_free_gb:
        raise RuntimeError(f"memory guard failed: ram_free_gb={free} < {min_free_gb}")
    if swap > max_swap_pct:
        raise RuntimeError(f"memory guard failed: swap_pct={swap} > {max_swap_pct}")


def unload_all(mlx_url: str, timeout: float) -> dict[str, Any] | list[Any] | str:
    status, body = request("POST", f"{mlx_url}/api/unload_all", payload={}, timeout=timeout)
    if status != 200:
        return {"ok": False, "http": status, "body": body}
    if isinstance(body, dict):
        body.setdefault("ok", True)
    return body


def active_jobs(proxy_url: str, timeout: float, api_key: str) -> list[dict[str, Any]]:
    status, body = request(
        "GET",
        f"{proxy_url}/api/jobs/summary?active_only=true&limit=50",
        timeout=timeout,
        api_key=api_key,
    )
    if status != 200 or not isinstance(body, dict):
        return [{"status": "UNKNOWN", "detail": body, "http": status}]
    jobs = body.get("jobs") or []
    if not isinstance(jobs, list):
        return []
    active: list[dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        status_value = str(job.get("status") or "").upper()
        if status_value in ACTIVE_JOB_STATUSES:
            active.append(job)
    return active


def set_indexing_mode(
    proxy_url: str,
    *,
    enabled: bool,
    reason: str,
    dataset_names: list[str],
    timeout: float,
    api_key: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "enabled": enabled,
        "reason": reason,
        "unload_models": enabled,
    }
    if enabled:
        payload["dataset_priority_order"] = dataset_names
    status, body = request("POST", f"{proxy_url}/api/indexing-mode", payload=payload, timeout=timeout, api_key=api_key)
    return require_json_dict(status, body, "set indexing mode")


def create_qdrant_snapshot(qdrant_url: str, collection: str, timeout: float) -> dict[str, Any]:
    quoted_collection = urllib.parse.quote(collection, safe="")
    status, body = request(
        "POST",
        f"{qdrant_url}/collections/{quoted_collection}/snapshots",
        payload={},
        timeout=timeout,
    )
    return {"http": status, "body": body}


def parse_batch(proxy_url: str, doc: TargetDoc, timeout: float, api_key: str) -> dict[str, Any]:
    status, body = request(
        "POST",
        f"{proxy_url}/api/rag/parse-batch/{doc.dataset_id}?limit=1",
        payload=None,
        timeout=timeout,
        api_key=api_key,
    )
    data = require_json_dict(status, body, "parse batch")
    result = data.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"parse batch result is not JSON object: {data}")
    if result.get("status") != "completed" or int(result.get("errors") or 0) > 0:
        raise RuntimeError(f"parse batch failed: {result}")
    if int(result.get("files_parsed") or 0) < 1:
        raise RuntimeError(f"parse batch did not parse a file: {result}")
    return data


def auth_smoke(proxy_url: str, auth_db_path: str, timeout: float) -> dict[str, Any]:
    keys = active_keys_by_role(auth_db_path)
    results: list[dict[str, Any]] = []
    for role in ("admin", "user"):
        key_info = keys.get(role)
        if not key_info:
            results.append({"role": role, "status": "skipped", "reason": "no active key"})
            continue
        key = key_info["key_value"]
        status, body = request(
            "POST",
            f"{proxy_url}/api/auth/verify",
            payload={"key": key, "fingerprint": ""},
            timeout=timeout,
        )
        ok = status == 200 and isinstance(body, dict) and body.get("role") == role
        results.append(
            {
                "role": role,
                "holder": key_info["holder_name"],
                "key": mask_key(key),
                "verify_http": status,
                "status": "ok" if ok else "failed",
                "returned_role": body.get("role") if isinstance(body, dict) else None,
            }
        )
        if not ok:
            raise RuntimeError(f"{role} key verify failed: HTTP {status}: {body}")

        protected_url = f"{proxy_url}/api/auth/keys" if role == "admin" else f"{proxy_url}/api/rag/datasets"
        protected_status, protected_body = request(
            "GET",
            protected_url,
            timeout=timeout,
            api_key=key,
        )
        protected_ok = protected_status == 200
        results[-1]["protected_http"] = protected_status
        results[-1]["protected_status"] = "ok" if protected_ok else "failed"
        if not protected_ok:
            raise RuntimeError(f"{role} key protected endpoint failed: HTTP {protected_status}: {protected_body}")

    invalid_status, _ = request(
        "POST",
        f"{proxy_url}/api/auth/verify",
        payload={"key": "__les_invalid_key__", "fingerprint": ""},
        timeout=timeout,
    )
    invalid_ok = invalid_status in {401, 403}
    results.append(
        {
            "role": "invalid",
            "status": "ok" if invalid_ok else "failed",
            "verify_http": invalid_status,
        }
    )
    if not invalid_ok:
        raise RuntimeError(f"invalid key was not rejected: HTTP {invalid_status}")
    return {"status": "ok", "checks": results}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets", nargs="+", default=DEFAULT_DATASETS)
    parser.add_argument("--db-path", default=rag_meta_db_path())
    parser.add_argument("--auth-db-path", default="data/les_meta.db")
    parser.add_argument("--proxy-url", default="http://127.0.0.1:8050")
    parser.add_argument("--mlx-url", default="http://127.0.0.1:8080")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--collection", default=rag_collection_name())
    parser.add_argument("--api-key", default=os.getenv("LES_API_KEY", ""))
    parser.add_argument("--artifacts-dir", default="artifacts/reindex_runs")
    parser.add_argument("--max-docs", type=int, default=0)
    parser.add_argument("--min-free-gb", type=float, default=8.0)
    parser.add_argument("--max-swap-pct", type=float, default=45.0)
    parser.add_argument("--post-min-free-gb", type=float, default=6.0)
    parser.add_argument("--post-max-swap-pct", type=float, default=60.0)
    parser.add_argument("--cooldown-sec", type=float, default=5.0)
    parser.add_argument("--health-timeout", type=float, default=20.0)
    parser.add_argument("--parse-timeout", type=float, default=1800.0)
    parser.add_argument("--snapshot-timeout", type=float, default=120.0)
    parser.add_argument("--require-qdrant-snapshot", action="store_true")
    parser.add_argument("--allow-active-jobs", action="store_true")
    parser.add_argument("--auth-smoke-after", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.proxy_url = args.proxy_url.rstrip("/")
    args.mlx_url = args.mlx_url.rstrip("/")
    args.qdrant_url = args.qdrant_url.rstrip("/")

    run_dir = Path(args.artifacts_dir) / f"reindex_{run_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "reindex.jsonl"

    admin_key = args.api_key
    if not admin_key and Path(args.auth_db_path).exists():
        admin_key = local_admin_key(args.auth_db_path)

    emit(
        log_path,
        "start",
        datasets=args.datasets,
        db_path=args.db_path,
        auth_db_path=args.auth_db_path,
        collection=args.collection,
        run_dir=str(run_dir),
        dry_run=args.dry_run,
        admin_key=mask_key(admin_key),
    )

    if not admin_key:
        emit(log_path, "error", detail="admin API key is required")
        return 2

    summaries_before = dataset_summaries(args.db_path, args.datasets)
    found = {item["name"] for item in summaries_before}
    missing = [name for name in args.datasets if name not in found]
    if missing:
        emit(log_path, "error", detail="dataset not found", missing=missing)
        return 2

    targets = load_target_docs(args.db_path, args.datasets, args.max_docs)
    emit(log_path, "plan", summaries=summaries_before, target_docs=len(targets))
    if not targets:
        emit(log_path, "done", detail="no indexed target docs")
        return 0

    if args.dry_run:
        preview = [asdict(doc) for doc in targets[:20]]
        emit(log_path, "dry_run", preview=preview, omitted=max(0, len(targets) - len(preview)))
        return 0

    active = active_jobs(args.proxy_url, args.health_timeout, admin_key)
    if active and not args.allow_active_jobs:
        emit(log_path, "error", detail="active jobs present", active_jobs=active)
        return 3

    sqlite_backup = backup_sqlite(args.db_path, run_dir)
    emit(log_path, "sqlite_backup", path=str(sqlite_backup), bytes=sqlite_backup.stat().st_size)

    qdrant_snapshot = create_qdrant_snapshot(args.qdrant_url, args.collection, args.snapshot_timeout)
    qdrant_snapshot_ok = qdrant_snapshot.get("http") == 200
    emit(log_path, "qdrant_snapshot", ok=qdrant_snapshot_ok, result=qdrant_snapshot)
    if args.require_qdrant_snapshot and not qdrant_snapshot_ok:
        emit(log_path, "error", detail="qdrant snapshot failed and is required")
        return 4

    try:
        health = health_snapshot(args.proxy_url, args.health_timeout, admin_key)
        emit(log_path, "pre_health", rag=health.get("rag"))
        before_memory = mlx_memory(args.mlx_url, args.health_timeout)
        assert_memory(before_memory, args.min_free_gb, args.max_swap_pct)
        emit(log_path, "pre_memory", memory=before_memory)
        emit(log_path, "pre_unload", result=unload_all(args.mlx_url, args.health_timeout))
        mode = set_indexing_mode(
            args.proxy_url,
            enabled=True,
            reason=f"guarded reindex: {', '.join(args.datasets)}",
            dataset_names=args.datasets,
            timeout=args.health_timeout,
            api_key=admin_key,
        )
        emit(log_path, "indexing_mode", mode=mode)

        for idx, doc in enumerate(targets, 1):
            emit(log_path, "doc_start", index=idx, total=len(targets), doc=asdict(doc))
            before_doc_memory = mlx_memory(args.mlx_url, args.health_timeout)
            assert_memory(before_doc_memory, args.min_free_gb, args.max_swap_pct)
            emit(log_path, "doc_memory_pre", index=idx, memory=before_doc_memory)

            mark_doc_pending(args.db_path, doc)
            started = time.time()
            try:
                parse_result = parse_batch(args.proxy_url, doc, args.parse_timeout, admin_key)
            except Exception:
                current = load_doc(args.db_path, doc.id)
                if current and current.get("status") == "PENDING":
                    restore_doc_indexed(args.db_path, doc)
                    emit(log_path, "doc_restored_after_parse_rejection", index=idx, doc_id=doc.id)
                raise

            parsed_sec = round(time.time() - started, 1)
            current = load_doc(args.db_path, doc.id)
            emit(log_path, "doc_parse", index=idx, sec=parsed_sec, result=parse_result, current=current)
            if not current or current.get("status") != "INDEXED":
                raise RuntimeError(f"document did not return to INDEXED: {doc.file_name}: {current}")

            after_health = health_snapshot(args.proxy_url, args.health_timeout, admin_key)
            emit(log_path, "doc_health", index=idx, rag=after_health.get("rag"))
            unload_result = unload_all(args.mlx_url, args.health_timeout)
            emit(log_path, "doc_unload", index=idx, result=unload_result)
            after_memory = mlx_memory(args.mlx_url, args.health_timeout)
            assert_memory(after_memory, args.post_min_free_gb, args.post_max_swap_pct)
            emit(log_path, "doc_memory_post", index=idx, memory=after_memory)

            if idx < len(targets) and args.cooldown_sec > 0:
                time.sleep(args.cooldown_sec)

        final_health = health_snapshot(args.proxy_url, args.health_timeout, admin_key)
        final_summaries = dataset_summaries(args.db_path, args.datasets)
        emit(log_path, "final_health", rag=final_health.get("rag"))
        emit(log_path, "final_summary", summaries=final_summaries)
        if args.auth_smoke_after:
            smoke = auth_smoke(args.proxy_url, args.auth_db_path, args.health_timeout)
            emit(log_path, "auth_smoke", result=smoke)
        emit(log_path, "done", run_dir=str(run_dir), docs=len(targets))
        return 0
    except Exception as error:
        emit(log_path, "failed", error=str(error), run_dir=str(run_dir))
        return 1
    finally:
        try:
            emit(log_path, "final_unload", result=unload_all(args.mlx_url, args.health_timeout))
        except Exception as error:
            emit(log_path, "final_unload_failed", error=str(error))
        try:
            mode = set_indexing_mode(
                args.proxy_url,
                enabled=False,
                reason="guarded reindex finished",
                dataset_names=args.datasets,
                timeout=args.health_timeout,
                api_key=admin_key,
            )
            emit(log_path, "chat_mode", mode=mode)
        except Exception as error:
            emit(log_path, "chat_mode_failed", error=str(error))


if __name__ == "__main__":
    raise SystemExit(main())
