#!/usr/bin/env python3
"""Run Qwen RAG indexing waves until no pending files remain.

The script is deliberately conservative: it never starts a new parse-scheduler
job while another scheduler job is active. Each wave keeps batch_limit=1 so
memory guards run after every file.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any


ACTIVE_STATUSES = {"QUEUED", "PARSING", "RUNNING"}
MAX_WAVE_BATCHES = 500


def request(method: str, url: str, payload: dict[str, Any] | None = None, timeout: float = 20) -> Any:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} -> HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {url} -> {exc}") from exc
    return json.loads(body or "{}")


def log(event: str, **fields: Any) -> None:
    item = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, **fields}
    print(json.dumps(item, ensure_ascii=False), flush=True)


def health(proxy_url: str) -> dict[str, Any]:
    return request("GET", f"{proxy_url}/api/health")


def mlx_memory(mlx_url: str) -> dict[str, Any]:
    data = request("GET", f"{mlx_url}/api/health", timeout=10)
    memory = data.get("memory") or {}
    return {
        "ram_free_gb": float(memory.get("ram_free_gb") or 0),
        "swap_pct": float(memory.get("swap_pct") if memory.get("swap_pct") is not None else 100),
        "raw": memory,
    }


def memory_ok(memory: dict[str, Any], args: argparse.Namespace) -> tuple[bool, str]:
    ram_free_gb = float(memory.get("ram_free_gb") or 0)
    swap_pct = float(memory.get("swap_pct") if memory.get("swap_pct") is not None else 100)
    if ram_free_gb < args.min_free_gb:
        return False, f"ram_free_gb={ram_free_gb} < {args.min_free_gb}"
    if swap_pct > args.max_swap_pct:
        return False, f"swap_pct={swap_pct} > {args.max_swap_pct}"
    return True, f"ram_free_gb={ram_free_gb}, swap_pct={swap_pct}"


def unload_all(mlx_url: str) -> Any:
    return request("POST", f"{mlx_url}/api/unload_all", {}, timeout=20)


def wait_for_memory(args: argparse.Namespace) -> None:
    unloaded = False
    while True:
        try:
            memory = mlx_memory(args.mlx_url.rstrip("/"))
        except RuntimeError as error:
            log("memory_check_failed", error=str(error), retry_sec=args.proxy_retry_sec)
            time.sleep(args.proxy_retry_sec)
            continue

        ok, detail = memory_ok(memory, args)
        if ok:
            log("memory_ok", detail=detail)
            return

        if args.unload_on_memory_guard and not unloaded:
            try:
                log("memory_guard_unload", detail=detail, result=unload_all(args.mlx_url.rstrip("/")))
            except RuntimeError as error:
                log("memory_guard_unload_failed", detail=detail, error=str(error))
            unloaded = True

        log("memory_wait", detail=detail, retry_sec=args.memory_cooldown_sec, memory=memory)
        time.sleep(args.memory_cooldown_sec)


def pending_files(proxy_url: str) -> int:
    data = health(proxy_url)
    rag = data.get("rag") or {}
    totals = rag.get("totals") or {}
    return int(totals.get("pending_files") or 0)


def active_scheduler_jobs(proxy_url: str) -> list[tuple[str, dict[str, Any]]]:
    payload = request("GET", f"{proxy_url}/api/jobs/summary?active_only=true&limit=50", timeout=30)
    if isinstance(payload, dict) and isinstance(payload.get("jobs"), list):
        jobs = {str(job.get("id") or ""): job for job in payload["jobs"] if isinstance(job, dict)}
    else:
        jobs = request("GET", f"{proxy_url}/api/jobs", timeout=30)
        if not isinstance(jobs, dict):
            return []
    active: list[tuple[str, dict[str, Any]]] = []
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        status = str(job.get("status") or "").upper()
        message = str(job.get("message") or "")
        total = job.get("total")
        if status in ACTIVE_STATUSES and ("Batch " in message or total):
            active.append((job_id, job))
    return active


def set_indexing_mode(proxy_url: str) -> None:
    payload = {
        "enabled": True,
        "reason": "qwen index until done",
        "unload_models": False,
        "dataset_priority_order": [
            "GKRF_Index",
            "NTD_FIRE_Index",
            "NTD_ELECTRICAL_Index",
            "NTD_STRUCTURAL_Index",
            "NTD_GEOTECH_Index",
            "NTD_SPDS_Index",
            "NTD_HVAC_Index",
            "NTD_WATER_Index",
            "NTD_PIPELINES_Index",
            "NTD_TRANSPORT_Index",
            "NTD_ARCH_URBAN_Index",
            "NTD_CONSTRUCTION_Index",
            "NTD_BIM_OPERATION_Index",
            "NTD_SAFETY_Index",
            "NTD_MATERIALS_Index",
            "NTD_GENERAL_Index",
            "NTD_OTHER_Index",
        ],
    }
    result = request("POST", f"{proxy_url}/api/indexing-mode", payload)
    log("indexing_mode", result=result)


def start_wave(proxy_url: str, args: argparse.Namespace) -> str:
    payload = {
        "batch_limit": 1,
        "max_batches": args.wave_batches,
        "cooldown_sec": args.cooldown_sec,
        "unload_before_start": False,
        "unload_between_batches": False,
        "warm_embedder": True,
        "unload_after_finish": False,
        "min_free_gb": args.min_free_gb,
        "max_swap_pct": args.max_swap_pct,
        "post_batch_min_free_gb": args.post_batch_min_free_gb,
        "post_batch_max_swap_pct": args.post_batch_max_swap_pct,
        "background": True,
        "stop_on_error": True,
    }
    result = request("POST", f"{proxy_url}/api/rag/parse-scheduler", payload)
    job_id = str(result.get("job_id") or "")
    if not job_id:
        raise RuntimeError(f"parse-scheduler did not return job_id: {result}")
    log("wave_started", job_id=job_id, payload=payload, result=result)
    return job_id


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy-url", default="http://127.0.0.1:8050")
    parser.add_argument("--mlx-url", default="http://127.0.0.1:8080")
    parser.add_argument("--wave-batches", type=int, default=MAX_WAVE_BATCHES)
    parser.add_argument("--poll-sec", type=float, default=60)
    parser.add_argument("--cooldown-sec", type=float, default=0)
    parser.add_argument("--min-free-gb", type=float, default=4)
    parser.add_argument("--max-swap-pct", type=float, default=80)
    parser.add_argument("--post-batch-min-free-gb", type=float, default=3)
    parser.add_argument("--post-batch-max-swap-pct", type=float, default=80)
    parser.add_argument("--memory-cooldown-sec", type=float, default=300)
    parser.add_argument("--proxy-retry-sec", type=float, default=30)
    parser.add_argument("--unload-on-memory-guard", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.wave_batches > MAX_WAVE_BATCHES:
        log("wave_batches_clamped", requested=args.wave_batches, effective=MAX_WAVE_BATCHES)
        args.wave_batches = MAX_WAVE_BATCHES

    proxy_url = args.proxy_url.rstrip("/")
    while True:
        try:
            set_indexing_mode(proxy_url)
            break
        except RuntimeError as error:
            log("proxy_wait", step="indexing_mode", error=str(error), retry_sec=args.proxy_retry_sec)
            time.sleep(args.proxy_retry_sec)

    while True:
        try:
            pending = pending_files(proxy_url)
        except RuntimeError as error:
            log("proxy_wait", step="health", error=str(error), retry_sec=args.proxy_retry_sec)
            time.sleep(args.proxy_retry_sec)
            continue

        log("snapshot", pending_files=pending)
        if pending <= 0:
            log("done")
            return 0

        try:
            active = active_scheduler_jobs(proxy_url)
        except RuntimeError as error:
            log("proxy_wait", step="jobs", error=str(error), retry_sec=args.proxy_retry_sec)
            time.sleep(args.proxy_retry_sec)
            continue

        if active:
            for job_id, job in active:
                log(
                    "active_job",
                    job_id=job_id,
                    status=job.get("status"),
                    processed=job.get("processed"),
                    total=job.get("total"),
                    message=job.get("message"),
                )
            time.sleep(args.poll_sec)
            continue

        wait_for_memory(args)
        try:
            start_wave(proxy_url, args)
        except RuntimeError as error:
            log("wave_start_failed", error=str(error), retry_sec=args.proxy_retry_sec)
            time.sleep(args.proxy_retry_sec)
            continue
        time.sleep(args.poll_sec)


if __name__ == "__main__":
    raise SystemExit(main())
