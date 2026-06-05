#!/usr/bin/env python3
"""Safe one-file-at-a-time RAG indexing loop.

This is an operator tool, not a bulk loader. It parses one pending file per
iteration through /api/rag/parse-scheduler, then verifies health before
continuing. Stop on the first mismatch, parse error, or memory guard failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def request(
    method: str,
    url: str,
    *,
    timeout: float,
    payload: dict[str, Any] | None = None,
    api_key: str = "",
) -> tuple[int, str]:
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
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return 0, str(exc)


def decode_json(status: int, body: str) -> dict[str, Any] | list[Any] | str:
    try:
        return json.loads(body or "{}")
    except json.JSONDecodeError:
        return {"status_code": status, "body": body[:500]}


def get_json(url: str, timeout: float, *, api_key: str = "") -> dict[str, Any] | list[Any] | str:
    status, body = request("GET", url, timeout=timeout, api_key=api_key)
    value = decode_json(status, body)
    if status != 200 and isinstance(value, dict):
        value.setdefault("http", status)
    return value


def post_json(
    url: str,
    timeout: float,
    payload: dict[str, Any],
    *,
    api_key: str = "",
) -> tuple[int, dict[str, Any] | list[Any] | str]:
    status, body = request("POST", url, timeout=timeout, payload=payload, api_key=api_key)
    return status, decode_json(status, body)


def emit(item: dict[str, Any]) -> None:
    print(json.dumps(item, ensure_ascii=False), flush=True)


def local_admin_key(db_path: str) -> str:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT key_value FROM auth_keys "
            "WHERE role='admin' AND is_active=1 "
            "AND (expires_at IS NULL OR expires_at > datetime('now','localtime')) "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        raise SystemExit(f"no active admin key in {db_path}")
    return str(row["key_value"])


def memory_state(mlx_url: str, timeout: float) -> dict[str, Any]:
    health = get_json(f"{mlx_url}/api/health", timeout)
    if not isinstance(health, dict):
        return {"ok": False, "detail": "MLX health is not JSON"}
    memory = health.get("memory") or {}
    ram_free = memory.get("ram_free_gb")
    swap_pct = memory.get("swap_pct")
    return {
        "ok": True,
        "ram_free_gb": float(ram_free if ram_free is not None else 0),
        "swap_pct": float(swap_pct if swap_pct is not None else 100),
        "raw": memory,
    }


def memory_ok(mem: dict[str, Any], min_free_gb: float, max_swap_pct: float) -> tuple[bool, str]:
    if not mem.get("ok"):
        return False, str(mem.get("detail") or "MLX health unavailable")
    ram_free = mem.get("ram_free_gb")
    swap_pct = mem.get("swap_pct")
    free = float(ram_free if ram_free is not None else 0)
    swap = float(swap_pct if swap_pct is not None else 100)
    if free < min_free_gb:
        return False, f"ram_free_gb={free} < {min_free_gb}"
    if swap > max_swap_pct:
        return False, f"swap_pct={swap} > {max_swap_pct}"
    return True, f"ram_free_gb={free}, swap_pct={swap}"


def rag_snapshot(proxy_url: str, timeout: float) -> dict[str, Any]:
    health = get_json(f"{proxy_url}/api/health", timeout)
    if not isinstance(health, dict):
        return {"ok": False, "error": "proxy health is not JSON", "raw": health}
    rag = health.get("rag") or {}
    if not isinstance(rag, dict):
        return {"ok": False, "error": "rag snapshot missing", "raw": health}
    qdrant = rag.get("qdrant") or {}
    totals = rag.get("totals") or {}
    points_match = qdrant.get("points_match_sqlite_chunks")
    ok = points_match is not False and not rag.get("error")
    return {"ok": ok, "status": rag.get("status"), "totals": totals, "qdrant": qdrant, "raw": rag}


def pending_total(snapshot: dict[str, Any]) -> int:
    totals = snapshot.get("totals") or {}
    return int(totals.get("pending_files") or 0)


def unload_all(mlx_url: str, timeout: float) -> dict[str, Any]:
    status, body = post_json(f"{mlx_url}/api/unload_all", timeout, {})
    return {"http": status, "result": body}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy-url", default="http://127.0.0.1:8050")
    parser.add_argument("--mlx-url", default="http://127.0.0.1:8080")
    parser.add_argument("--api-key", default=os.getenv("LES_API_KEY", ""))
    parser.add_argument("--admin-key-db", default="", help="Read active admin key from local SQLite DB")
    parser.add_argument("--max-files", type=int, default=1)
    parser.add_argument("--min-free-gb", type=float, default=8.0)
    parser.add_argument("--max-swap-pct", type=float, default=45.0)
    parser.add_argument("--health-timeout", type=float, default=10.0)
    parser.add_argument("--parse-timeout", type=float, default=1800.0)
    parser.add_argument("--cooldown-sec", type=float, default=10.0)
    parser.add_argument("--no-unload", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.proxy_url = args.proxy_url.rstrip("/")
    args.mlx_url = args.mlx_url.rstrip("/")
    api_key = args.api_key
    if not api_key and args.admin_key_db:
        api_key = local_admin_key(args.admin_key_db)
    if not api_key:
        raise SystemExit("admin API key required: pass --api-key, LES_API_KEY, or --admin-key-db")

    for item_no in range(1, args.max_files + 1):
        before = rag_snapshot(args.proxy_url, args.health_timeout)
        emit({"item": item_no, "step": "pre_health", "snapshot": before})
        if not before.get("ok"):
            return 3
        pending_before = pending_total(before)
        if pending_before <= 0:
            return 0

        if not args.no_unload:
            emit({"item": item_no, "step": "unload", "detail": unload_all(args.mlx_url, args.health_timeout)})

        mem = memory_state(args.mlx_url, args.health_timeout)
        ok, detail = memory_ok(mem, args.min_free_gb, args.max_swap_pct)
        emit({"item": item_no, "step": "memory", "ok": ok, "detail": detail, "memory": mem})
        if not ok:
            return 2

        payload = {
            "batch_limit": 1,
            "max_batches": 1,
            "cooldown_sec": 0,
            "unload_between_batches": True,
            "unload_before_start": False,
            "min_free_gb": args.min_free_gb,
            "max_swap_pct": args.max_swap_pct,
            "background": False,
            "stop_on_error": True,
        }
        started = time.time()
        status, body = post_json(
            f"{args.proxy_url}/api/rag/parse-scheduler",
            args.parse_timeout,
            payload,
            api_key=api_key,
        )
        emit({"item": item_no, "step": "parse", "http": status, "sec": round(time.time() - started, 1), "result": body})
        if status != 200 or not isinstance(body, dict) or int(body.get("errors") or 0) > 0:
            return 1

        after = rag_snapshot(args.proxy_url, args.health_timeout)
        emit({"item": item_no, "step": "post_health", "snapshot": after})
        if not after.get("ok"):
            return 3
        pending_after = pending_total(after)
        if pending_after >= pending_before:
            emit(
                {
                    "item": item_no,
                    "step": "stop",
                    "reason": "pending did not decrease",
                    "pending_before": pending_before,
                    "pending_after": pending_after,
                }
            )
            return 4
        if item_no < args.max_files and args.cooldown_sec > 0:
            time.sleep(args.cooldown_sec)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
