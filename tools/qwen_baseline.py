#!/usr/bin/env python3
"""Run guarded LES Qwen baseline checks.

This runner is deliberately explicit about profile, reranker, and semantic
cache state so a generation run cannot accidentally test the legacy index or a
cached answer.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.rag_golden_set import (
    DEFAULT_CASES_PATH,
    GoldenCase,
    evaluate_response,
    load_cases,
    request_payload,
)


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: str
    elapsed: float

    def json(self) -> dict[str, Any]:
        return json.loads(self.body or "{}")


@dataclass(frozen=True)
class BaselineResult:
    case_id: str
    mode: str
    ok: bool
    detail: str
    elapsed: float
    question: str = ""
    answer: str = ""
    reference_answer: str = ""
    crag_status: str = ""
    chunks: int = 0
    top_score: float = 0.0
    sources: tuple[str, ...] = ()
    expected_terms: tuple[str, ...] = ()
    source_hints: tuple[str, ...] = ()
    reranker_enabled: bool | None = None
    semantic_cache_enabled: bool | None = None
    validation_enabled: bool | None = None
    guarded_stop: bool = False


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    detail: str
    metrics: dict[str, Any]
    indexing_mode: dict[str, Any]
    jobs_summary: dict[str, Any]
    ui_status: int | None = None


class BaselineClient:
    def __init__(self, base_url: str, timeout: float, api_key: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> HttpResult:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        started = time.time()
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return HttpResult(resp.status, resp.read().decode("utf-8", errors="replace"), time.time() - started)
        except urllib.error.HTTPError as exc:
            return HttpResult(exc.code, exc.read().decode("utf-8", errors="replace"), time.time() - started)
        except OSError as exc:
            return HttpResult(0, str(exc), time.time() - started)

    def get_json(self, path: str) -> tuple[int, dict[str, Any]]:
        result = self.request("GET", path)
        if result.status != 200:
            return result.status, {"detail": result.body[:500]}
        try:
            return result.status, result.json()
        except json.JSONDecodeError as exc:
            return result.status, {"detail": f"invalid JSON: {exc}"}


GUARD_DETAIL_HINTS = (
    "ram_free_gb",
    "swap_pct",
    "active_jobs",
    "llm_generation_slots",
    "indexing mode is active",
    "maintenance mode is active",
    "chat generation is paused",
)


def guarded_stop_detail(result: HttpResult) -> str:
    if result.status not in {409, 429, 503}:
        return ""
    detail = result.body[:240]
    try:
        payload = result.json()
        raw_detail = payload.get("detail", detail) if isinstance(payload, dict) else detail
        detail = "; ".join(str(item) for item in raw_detail) if isinstance(raw_detail, list) else str(raw_detail)
    except json.JSONDecodeError:
        pass
    folded = detail.casefold()
    if any(hint in folded for hint in GUARD_DETAIL_HINTS):
        return detail[:240]
    return ""


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def unload_mlx_models(mlx_url: str, timeout: float = 20.0) -> tuple[bool, str]:
    url = f"{mlx_url.rstrip('/')}/api/unload_all"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status == 200, f"HTTP {resp.status}: {body[:240]}"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return False, f"HTTP {exc.code}: {body[:240]}"
    except OSError as exc:
        return False, str(exc)


def mlx_host_memory(mlx_url: str, timeout: float = 5.0) -> tuple[bool, dict[str, Any], str]:
    url = f"{mlx_url.rstrip('/')}/api/host_memory"
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return True, json.loads(body or "{}"), f"HTTP {resp.status}: {body[:240]}"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return False, {}, f"HTTP {exc.code}: {body[:240]}"
    except (OSError, json.JSONDecodeError) as exc:
        return False, {}, str(exc)


def wait_for_mlx_memory(
    mlx_url: str,
    *,
    min_free_gb: float,
    max_swap_pct: float,
    timeout: float,
    poll_interval: float = 2.0,
) -> tuple[bool, str]:
    deadline = time.time() + timeout
    last_detail = "not checked"
    while time.time() <= deadline:
        ok, memory, detail = mlx_host_memory(mlx_url, timeout=min(5.0, max(1.0, poll_interval)))
        if ok:
            ram_free = float(memory.get("ram_free_gb") or 0.0)
            swap_pct = float(memory.get("swap_pct") if memory.get("swap_pct") is not None else 100.0)
            last_detail = f"ram_free_gb={ram_free:.1f}, swap_pct={swap_pct:.1f}"
            if ram_free >= min_free_gb and swap_pct <= max_swap_pct:
                return True, last_detail
        else:
            last_detail = detail
        time.sleep(poll_interval)
    return False, last_detail


def active_profile_trace(health: dict[str, Any]) -> dict[str, Any]:
    embedding = health.get("embedding")
    if isinstance(embedding, dict):
        return embedding
    rag = health.get("rag") if isinstance(health.get("rag"), dict) else {}
    qdrant = rag.get("qdrant") if isinstance(rag.get("qdrant"), dict) else {}
    return {
        "profile": "",
        "collection": qdrant.get("collection", ""),
        "meta_db": "",
    }


def guard_active_profile(client: BaselineClient, expected_profile: str, expected_collection: str = "") -> tuple[bool, str, dict[str, Any]]:
    result = client.request("GET", "/api/health")
    if result.status != 200:
        return False, f"health HTTP {result.status}: {result.body[:240]}", {}
    try:
        health = result.json()
    except json.JSONDecodeError as exc:
        return False, f"health invalid JSON: {exc}", {}

    trace = active_profile_trace(health)
    profile = str(trace.get("profile") or "")
    collection = str(trace.get("collection") or "")
    if expected_profile and profile and profile != expected_profile:
        return False, f"profile={profile}, expected={expected_profile}", trace
    if expected_collection and collection != expected_collection:
        return False, f"collection={collection}, expected={expected_collection}", trace
    if expected_profile and not profile and not collection:
        return False, "health response has no embedding profile or collection trace", trace
    return True, "profile guard passed", trace


def ui_probe(ui_url: str, timeout: float) -> int:
    started = time.time()
    try:
        with urllib.request.urlopen(ui_url, timeout=timeout) as resp:
            resp.read(256)
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except OSError:
        return 0
    finally:
        _ = time.time() - started


def evaluate_preflight(
    *,
    metrics: dict[str, Any],
    indexing_mode: dict[str, Any],
    jobs_summary: dict[str, Any],
    min_free_gb: float,
    max_swap_pct: float,
    ui_status: int | None = None,
    require_ui: bool = True,
) -> PreflightResult:
    failures: list[str] = []
    system = metrics.get("system") if isinstance(metrics.get("system"), dict) else {}
    ram_total = float(system.get("ram_total") or 0)
    if system.get("ram_free_gb") is not None:
        ram_free = float(system.get("ram_free_gb") or 0)
    else:
        ram_used = float(system.get("ram_used") or 0)
        ram_free = max(0.0, ram_total - ram_used)
    swap_pct = float(system.get("swap_pct") if system.get("swap_pct") is not None else 100)
    if ram_free < min_free_gb:
        failures.append(f"ram_free_gb={ram_free:.1f} < {min_free_gb:.1f}")
    if swap_pct > max_swap_pct:
        failures.append(f"swap_pct={swap_pct:.1f} > {max_swap_pct:.1f}")

    if indexing_mode.get("active") is True:
        failures.append("indexing mode is active")
    if indexing_mode.get("chat_generation_allowed") is False:
        failures.append(str(indexing_mode.get("chat_generation_reason") or "chat generation is paused"))

    active_count = int(jobs_summary.get("active_count") or 0)
    if active_count:
        failures.append(f"active_jobs={active_count}")

    if require_ui and ui_status != 200:
        failures.append(f"ui_status={ui_status or 0}")

    detail = "; ".join(failures) if failures else (
        f"ram_free_gb={ram_free:.1f}, swap_pct={swap_pct:.1f}, active_jobs={active_count}, ui={ui_status or 'skipped'}"
    )
    return PreflightResult(
        ok=not failures,
        detail=detail,
        metrics=metrics,
        indexing_mode=indexing_mode,
        jobs_summary=jobs_summary,
        ui_status=ui_status,
    )


def run_preflight(
    client: BaselineClient,
    *,
    ui_url: str,
    min_free_gb: float,
    max_swap_pct: float,
    require_ui: bool,
) -> PreflightResult:
    metrics_status, metrics = client.get_json("/api/metrics")
    indexing_status, indexing_mode = client.get_json("/api/indexing-mode")
    jobs_status, jobs_summary = client.get_json("/api/jobs/summary?active_only=true&limit=20")
    ui_status = ui_probe(ui_url, client.timeout) if require_ui else None

    if metrics_status != 200:
        metrics = {"system": {"ram_total": 0, "ram_used": 0, "swap_pct": 100}, "detail": metrics.get("detail")}
    if indexing_status != 200:
        indexing_mode = {"active": True, "chat_generation_allowed": False, "chat_generation_reason": indexing_mode.get("detail")}
    if jobs_status != 200:
        jobs_summary = {"active_count": 1, "detail": jobs_summary.get("detail")}

    return evaluate_preflight(
        metrics=metrics,
        indexing_mode=indexing_mode,
        jobs_summary=jobs_summary,
        min_free_gb=min_free_gb,
        max_swap_pct=max_swap_pct,
        ui_status=ui_status,
        require_ui=require_ui,
    )


def chat_payload(
    case: GoldenCase,
    *,
    reranker_enabled: bool,
    semantic_cache_enabled: bool,
    validation_enabled: bool,
    session_id: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question": case.question,
        "reranker_enabled": reranker_enabled,
        "semantic_cache_enabled": semantic_cache_enabled,
        "validation_enabled": validation_enabled,
        "session_id": session_id,
    }
    if case.dataset_filter:
        payload["dataset_filter"] = case.dataset_filter
    return payload


def run_retrieval_case(client: BaselineClient, case: GoldenCase) -> BaselineResult:
    result = client.request("POST", "/api/rag/retrieve-debug", request_payload(case))
    if result.status != 200:
        guard_detail = guarded_stop_detail(result)
        if guard_detail:
            return BaselineResult(
                case.id,
                "retrieval",
                True,
                f"GUARDED_STOP: {guard_detail}",
                result.elapsed,
                question=case.question,
                reference_answer=case.reference_answer,
                expected_terms=case.must_find,
                source_hints=case.source_any,
                guarded_stop=True,
            )
        return BaselineResult(case.id, "retrieval", False, f"HTTP {result.status}: {result.body[:240]}", result.elapsed)
    try:
        payload = result.json()
    except json.JSONDecodeError as exc:
        return BaselineResult(case.id, "retrieval", False, f"invalid JSON: {exc}", result.elapsed)

    evaluated = evaluate_response(case, payload, result.elapsed)
    return BaselineResult(
        case_id=case.id,
        mode="retrieval",
        ok=evaluated.ok,
        detail=evaluated.detail,
        elapsed=evaluated.elapsed,
        question=case.question,
        reference_answer=case.reference_answer,
        chunks=evaluated.chunks,
        top_score=evaluated.top_score,
        sources=evaluated.sources,
        expected_terms=case.must_find,
        source_hints=case.source_any,
    )


def run_chat_case(
    client: BaselineClient,
    case: GoldenCase,
    *,
    reranker_enabled: bool,
    semantic_cache_enabled: bool,
    validation_enabled: bool,
    session_id: str,
) -> BaselineResult:
    result = client.request(
        "POST",
        "/api/chat",
        chat_payload(
            case,
            reranker_enabled=reranker_enabled,
            semantic_cache_enabled=semantic_cache_enabled,
            validation_enabled=validation_enabled,
            session_id=session_id,
        ),
    )
    if result.status != 200:
        guard_detail = guarded_stop_detail(result)
        if guard_detail:
            return BaselineResult(
                case.id,
                "chat",
                True,
                f"GUARDED_STOP: {guard_detail}",
                result.elapsed,
                question=case.question,
                reference_answer=case.reference_answer,
                expected_terms=case.must_find,
                source_hints=case.source_any,
                reranker_enabled=reranker_enabled,
                semantic_cache_enabled=semantic_cache_enabled,
                validation_enabled=validation_enabled,
                guarded_stop=True,
            )
        return BaselineResult(
            case.id,
            "chat",
            False,
            f"HTTP {result.status}: {result.body[:240]}",
            result.elapsed,
            question=case.question,
            reference_answer=case.reference_answer,
            expected_terms=case.must_find,
            source_hints=case.source_any,
            reranker_enabled=reranker_enabled,
            semantic_cache_enabled=semantic_cache_enabled,
            validation_enabled=validation_enabled,
        )
    try:
        payload = result.json()
    except json.JSONDecodeError as exc:
        return BaselineResult(case.id, "chat", False, f"invalid JSON: {exc}", result.elapsed)

    answer = str(payload.get("answer") or "").strip()
    status = str(payload.get("crag_status") or "")
    sources = tuple(str(source) for source in (payload.get("sources") or []))
    failures: list[str] = []
    if not answer:
        failures.append("empty answer")
    if status not in {"VERIFIED", "NO_DATA", "NEEDS_CLARIFICATION", "UNVALIDATED"}:
        failures.append(f"unexpected crag_status={status or '?'}")
    if case.source_any and sources:
        source_text = "\n".join(sources).casefold()
        if not any(hint.casefold() in source_text for hint in case.source_any):
            failures.append("missing source hint: " + " | ".join(case.source_any))

    return BaselineResult(
        case_id=case.id,
        mode="chat",
        ok=not failures,
        detail="passed" if not failures else "; ".join(failures),
        elapsed=result.elapsed,
        question=case.question,
        answer=answer,
        reference_answer=case.reference_answer,
        crag_status=status,
        chunks=len(sources),
        sources=sources,
        expected_terms=case.must_find,
        source_hints=case.source_any,
        reranker_enabled=reranker_enabled,
        semantic_cache_enabled=semantic_cache_enabled,
        validation_enabled=validation_enabled,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run guarded LES Qwen baseline checks.")
    parser.add_argument("--proxy-url", default=os.getenv("LES_PROXY_URL", "http://127.0.0.1:8050"))
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--api-key", default=os.getenv("LES_USER_KEY", os.getenv("LES_ADMIN_KEY", "")))
    parser.add_argument("--mode", choices=("retrieval", "chat", "both"), default="retrieval")
    parser.add_argument("--expect-profile", default=os.getenv("LES_EXPECT_PROFILE", "qwen"))
    parser.add_argument("--expect-collection", default=os.getenv("LES_EXPECT_COLLECTION", "les_rag_qwen3_06b"))
    parser.add_argument("--skip-profile-guard", action="store_true")
    parser.add_argument("--reranker", choices=("off", "on"), default="off")
    parser.add_argument("--semantic-cache", choices=("off", "on"), default="off")
    parser.add_argument("--validation", choices=("off", "on"), default="on")
    parser.add_argument("--timeout", type=float, default=float(os.getenv("LES_BASELINE_TIMEOUT", "180")))
    parser.add_argument("--preflight-timeout", type=float, default=float(os.getenv("LES_BASELINE_PREFLIGHT_TIMEOUT", "5")))
    parser.add_argument("--ui-url", default=os.getenv("LES_UI_URL", "http://127.0.0.1:8051"))
    parser.add_argument("--min-free-gb", type=float, default=float(os.getenv("LES_BASELINE_MIN_FREE_GB", "8")))
    parser.add_argument("--max-swap-pct", type=float, default=float(os.getenv("LES_BASELINE_MAX_SWAP_PCT", "60")))
    parser.add_argument("--skip-ui-check", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--max-cases", type=positive_int, default=None)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--stop-on-guard", action="store_true")
    parser.add_argument("--unload-after-case", action="store_true")
    parser.add_argument("--mlx-url", default=os.getenv("MLX_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--unload-timeout", type=float, default=float(os.getenv("LES_BASELINE_UNLOAD_TIMEOUT", "20")))
    parser.add_argument("--wait-memory-after-unload", action="store_true")
    parser.add_argument("--memory-wait-timeout", type=float, default=float(os.getenv("LES_BASELINE_MEMORY_WAIT_TIMEOUT", "45")))
    parser.add_argument("--memory-wait-interval", type=float, default=float(os.getenv("LES_BASELINE_MEMORY_WAIT_INTERVAL", "3")))
    parser.add_argument("--jsonl", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args(argv)


def emit_result(result: BaselineResult, *, jsonl: bool) -> str:
    if jsonl:
        return json.dumps(asdict(result), ensure_ascii=False)
    mark = "GUARD" if result.guarded_stop else ("OK" if result.ok else "FAIL")
    sources = ", ".join(source for source in result.sources[:3] if source)
    suffix = f" sources={sources}" if sources else ""
    crag = f" crag={result.crag_status}" if result.crag_status else ""
    return (
        f"[{mark:4}] {result.mode:9} {result.case_id:28} {result.elapsed:7.2f}s "
        f"chunks={result.chunks:<2} top={result.top_score:.3f}{crag} {result.detail}{suffix}"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    client = BaselineClient(args.proxy_url, args.timeout, args.api_key)

    if not args.skip_preflight:
        preflight_client = BaselineClient(args.proxy_url, args.preflight_timeout, args.api_key)
        preflight = run_preflight(
            preflight_client,
            ui_url=args.ui_url,
            min_free_gb=args.min_free_gb,
            max_swap_pct=args.max_swap_pct,
            require_ui=not args.skip_ui_check,
        )
        if not preflight.ok:
            print(f"preflight failed: {preflight.detail}", file=sys.stderr)
            return 4
        if not args.jsonl:
            print(f"preflight: {preflight.detail}")

    if not args.skip_profile_guard:
        ok, detail, trace = guard_active_profile(client, args.expect_profile, args.expect_collection)
        if not ok:
            print(f"profile guard failed: {detail}; trace={trace}", file=sys.stderr)
            return 3
        if not args.jsonl:
            print(f"profile guard: {detail}; trace={trace}")

    try:
        cases = load_cases(args.cases)
    except Exception as exc:
        print(f"cannot load cases: {exc}", file=sys.stderr)
        return 2
    if args.max_cases is not None:
        cases = cases[:args.max_cases]
    if args.case_id:
        wanted = set(args.case_id)
        cases = [case for case in cases if case.id in wanted]
        missing = wanted - {case.id for case in cases}
        if missing:
            print(f"unknown case-id: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

    session_id = f"baseline-{int(time.time())}"
    reranker_enabled = args.reranker == "on"
    semantic_cache_enabled = args.semantic_cache == "on"
    validation_enabled = args.validation == "on"
    results: list[BaselineResult] = []
    lines: list[str] = []
    failed = 0
    guarded = 0

    def record(result: BaselineResult) -> bool:
        nonlocal failed, guarded
        results.append(result)
        failed += 0 if result.ok else 1
        guarded += 1 if result.guarded_stop else 0
        line = emit_result(result, jsonl=args.jsonl)
        lines.append(line)
        print(line, flush=True)
        if args.unload_after_case:
            ok, detail = unload_mlx_models(args.mlx_url, timeout=args.unload_timeout)
            if not ok:
                print(f"unload warning: {detail}", file=sys.stderr)
            elif not args.jsonl:
                print(f"unload: {detail}")
            if ok and args.wait_memory_after_unload:
                mem_ok, mem_detail = wait_for_mlx_memory(
                    args.mlx_url,
                    min_free_gb=args.min_free_gb,
                    max_swap_pct=args.max_swap_pct,
                    timeout=args.memory_wait_timeout,
                    poll_interval=args.memory_wait_interval,
                )
                if not mem_ok:
                    print(f"memory wait warning: {mem_detail}", file=sys.stderr)
                elif not args.jsonl:
                    print(f"memory wait: {mem_detail}")
        return bool(result.guarded_stop and args.stop_on_guard)

    stop = False
    for case in cases:
        if args.mode in {"retrieval", "both"}:
            stop = record(run_retrieval_case(client, case))
            if stop:
                break
        if args.mode in {"chat", "both"}:
            stop = record(
                run_chat_case(
                    client,
                    case,
                    reranker_enabled=reranker_enabled,
                    semantic_cache_enabled=semantic_cache_enabled,
                    validation_enabled=validation_enabled,
                    session_id=session_id,
                )
            )
            if stop:
                break

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if failed:
        print(f"baseline failed: {failed}/{len(results)} checks failed", file=sys.stderr)
        return 1
    if guarded:
        print(f"baseline guarded stop: {guarded}/{len(results)} checks stopped by guard")
        return 0
    print(f"baseline passed: {len(results)} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
