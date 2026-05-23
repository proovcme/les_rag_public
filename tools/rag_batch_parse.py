#!/usr/bin/env python3
"""Memory-guarded RAG batch parser.

Runs /api/rag/parse-batch/{dataset_id} in small chunks and stops before the
host gets tight on RAM or swap. Keep batch sizes conservative for DOCX-heavy
datasets.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def request(method: str, url: str, *, timeout: float, payload: dict[str, Any] | None = None) -> tuple[int, str]:
    data = None
    headers = {"Accept": "application/json"}
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


def get_json(url: str, timeout: float) -> dict[str, Any] | list[Any] | None:
    status, body = request("GET", url, timeout=timeout)
    if status != 200:
        return None
    try:
        return json.loads(body or "{}")
    except json.JSONDecodeError:
        return None


def post_json(url: str, timeout: float, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any] | str]:
    status, body = request("POST", url, timeout=timeout, payload=payload)
    try:
        return status, json.loads(body or "{}")
    except json.JSONDecodeError:
        return status, body


def memory_ok(args: argparse.Namespace) -> tuple[bool, str]:
    health = get_json(f"{args.mlx_url}/api/health", args.health_timeout)
    if not isinstance(health, dict):
        return False, "MLX health unavailable"
    mem = health.get("memory") or {}
    free = float(mem.get("ram_free_gb") or 0)
    swap = float(mem.get("swap_pct") or 100)
    if free < args.min_free_gb:
        return False, f"ram_free_gb={free} < {args.min_free_gb}"
    if swap > args.max_swap_pct:
        return False, f"swap_pct={swap} > {args.max_swap_pct}"
    return True, f"ram_free_gb={free}, swap_pct={swap}"


def unload_all(args: argparse.Namespace) -> str:
    status, body = post_json(f"{args.mlx_url}/api/unload_all", args.health_timeout, {})
    return "unload_all ok" if status == 200 else f"unload_all HTTP {status}: {str(body)[:200]}"


def resolve_dataset(args: argparse.Namespace) -> dict[str, Any]:
    datasets = get_json(f"{args.proxy_url}/api/rag/datasets", args.health_timeout)
    if not isinstance(datasets, list):
        raise SystemExit("Could not list datasets")
    match = next(
        (
            item
            for item in datasets
            if item.get("id") == args.dataset or item.get("name") == args.dataset
        ),
        None,
    )
    if not match:
        known = ", ".join(str(item.get("name")) for item in datasets)
        raise SystemExit(f"dataset not found: {args.dataset}; known: {known}")
    return match


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="Dataset id or name")
    parser.add_argument("--proxy-url", default="http://127.0.0.1:8050")
    parser.add_argument("--mlx-url", default="http://127.0.0.1:8080")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--max-batches", type=int, default=1)
    parser.add_argument("--parse-timeout", type=float, default=1800)
    parser.add_argument("--health-timeout", type=float, default=10)
    parser.add_argument("--min-free-gb", type=float, default=8.0)
    parser.add_argument("--max-swap-pct", type=float, default=45.0)
    parser.add_argument("--cooldown-sec", type=float, default=20.0)
    parser.add_argument("--stop-on-error", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.proxy_url = args.proxy_url.rstrip("/")
    args.mlx_url = args.mlx_url.rstrip("/")
    dataset = resolve_dataset(args)
    dataset_id = dataset["id"]

    failures = 0
    for batch_no in range(1, args.max_batches + 1):
        ok, detail = memory_ok(args)
        print(json.dumps({"batch": batch_no, "step": "preflight", "memory": detail}, ensure_ascii=False), flush=True)
        if not ok:
            return 2
        started = time.time()
        status, body = post_json(
            f"{args.proxy_url}/api/rag/parse-batch/{dataset_id}?limit={args.batch_size}",
            args.parse_timeout,
            {},
        )
        item = {
            "batch": batch_no,
            "dataset": dataset.get("name"),
            "http": status,
            "sec": round(time.time() - started, 1),
            "result": body,
        }
        print(json.dumps(item, ensure_ascii=False), flush=True)
        if status != 200:
            failures += 1
            if args.stop_on_error:
                return 1
        print(json.dumps({"batch": batch_no, "step": "unload", "detail": unload_all(args)}, ensure_ascii=False), flush=True)
        remaining = 0
        if isinstance(body, dict):
            remaining = int(((body.get("result") or {}).get("remaining_pending") or 0))
        if remaining <= 0:
            return 1 if failures else 0
        if batch_no < args.max_batches:
            time.sleep(args.cooldown_sec)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
