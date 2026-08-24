#!/usr/bin/env python3
"""Run a small live retrieval golden set against LES RAG.

The tool intentionally uses /api/rag/retrieve-debug instead of /api/chat so it
can be run after each indexing milestone without spending LLM time. Each case
checks that retrieval returns chunks and that expected source/content hints are
present in the returned evidence.
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CASES_PATH = Path("golden/ntd_golden_set.json")


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: str
    elapsed: float

    def json(self) -> dict[str, Any]:
        return json.loads(self.body or "{}")


@dataclass(frozen=True)
class GoldenCase:
    id: str
    question: str
    dataset_filter: str = ""
    expected_route_filter: str = ""
    expected_quality_status: str = ""
    reference_answer: str = ""
    top_k: int = 8
    min_chunks: int = 1
    min_top_score: float = 0.0
    must_find: tuple[str, ...] = ()
    must_find_same_chunk: bool = True
    source_any: tuple[str, ...] = ()
    source_top_any: tuple[str, ...] = ()
    source_top_k: int = 3


@dataclass(frozen=True)
class GoldenResult:
    id: str
    ok: bool
    detail: str
    elapsed: float
    chunks: int = 0
    top_score: float = 0.0
    sources: tuple[str, ...] = ()


class GoldenClient:
    def __init__(self, base_url: str, timeout: float, api_key: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key

    def post_json(self, path: str, payload: dict[str, Any]) -> HttpResult:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        started = time.time()
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return HttpResult(resp.status, body, time.time() - started)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return HttpResult(exc.code, body, time.time() - started)
        except OSError as exc:
            return HttpResult(0, str(exc), time.time() - started)


def _norm(value: Any) -> str:
    return str(value or "").casefold()


def _contains(haystack: str, needle: str) -> bool:
    return _norm(needle) in haystack


def _case_from_dict(raw: dict[str, Any]) -> GoldenCase:
    return GoldenCase(
        id=str(raw["id"]),
        question=str(raw["question"]),
        dataset_filter=str(raw.get("dataset_filter") or ""),
        expected_route_filter=str(raw.get("expected_route_filter") or ""),
        expected_quality_status=str(raw.get("expected_quality_status") or ""),
        reference_answer=str(raw.get("reference_answer") or ""),
        top_k=int(raw.get("top_k") or 8),
        min_chunks=int(raw.get("min_chunks") or 1),
        min_top_score=float(raw.get("min_top_score") or 0.0),
        must_find=tuple(str(item) for item in raw.get("must_find", [])),
        must_find_same_chunk=bool(raw.get("must_find_same_chunk", True)),
        source_any=tuple(str(item) for item in raw.get("source_any", [])),
        source_top_any=tuple(str(item) for item in raw.get("source_top_any", [])),
        source_top_k=int(raw.get("source_top_k") or 3),
    )


def load_cases(path: Path) -> list[GoldenCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise ValueError(f"golden cases must be a list or an object with cases: {path}")
    return [_case_from_dict(item) for item in raw_cases]


def local_active_key(db_path: str, role: str = "") -> str:
    where_role = "AND role=?" if role else ""
    params: tuple[str, ...] = (role,) if role else ()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT key_value FROM auth_keys "
            "WHERE is_active=1 "
            f"{where_role} "
            "AND (expires_at IS NULL OR expires_at > datetime('now','localtime')) "
            "ORDER BY CASE role WHEN 'user' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, created_at DESC "
            "LIMIT 1",
            params,
        ).fetchone()
    if not row:
        role_hint = f" role={role}" if role else ""
        raise SystemExit(f"no active{role_hint} key in {db_path}")
    return str(row["key_value"])


def request_payload(case: GoldenCase) -> dict[str, Any]:
    payload: dict[str, Any] = {"question": case.question, "top_k": case.top_k}
    if case.dataset_filter:
        payload["dataset_filter"] = case.dataset_filter
    return payload


def validate_source_verified_cases(cases: list[GoldenCase]) -> list[str]:
    """Return case ids that do not name an expected source."""
    return [
        case.id
        for case in cases
        if not case.source_any and not case.source_top_any
    ]


def evaluate_response(
    case: GoldenCase,
    response: dict[str, Any],
    elapsed: float = 0.0,
    *,
    require_native_rrf: bool = False,
) -> GoldenResult:
    chunks = response.get("chunks") or []
    if not isinstance(chunks, list):
        return GoldenResult(case.id, False, "response chunks is not a list", elapsed)

    sources = tuple(str(chunk.get("doc_name") or "") for chunk in chunks if isinstance(chunk, dict))
    # Expected content terms must come from retrieved content, never from a
    # convenient file title. Source-name expectations have dedicated fields.
    evidence_by_chunk = [
        _norm(f"{chunk.get('preview', '')}\n{chunk.get('expanded_preview', '')}")
        for chunk in chunks
        if isinstance(chunk, dict)
    ]
    evidence = "\n".join(evidence_by_chunk)
    scores = [
        float(chunk.get("score") or 0.0)
        for chunk in chunks
        if isinstance(chunk, dict) and isinstance(chunk.get("score"), (int, float))
    ]
    top_score = max(scores, default=0.0)

    failures: list[str] = []
    if len(chunks) < case.min_chunks:
        failures.append(f"chunks={len(chunks)} < {case.min_chunks}")
    if top_score < case.min_top_score:
        failures.append(f"top_score={top_score:.3f} < {case.min_top_score:.3f}")

    missing_terms = [term for term in case.must_find if not _contains(evidence, term)]
    if missing_terms:
        failures.append("missing terms: " + ", ".join(missing_terms))
    elif case.must_find and case.must_find_same_chunk:
        if not any(all(_contains(chunk_text, term) for term in case.must_find) for chunk_text in evidence_by_chunk):
            failures.append("expected terms are split across unrelated chunks")

    if case.source_any:
        source_text = _norm("\n".join(sources))
        if not any(_contains(source_text, hint) for hint in case.source_any):
            failures.append("missing source hint: " + " | ".join(case.source_any))

    if case.source_top_any:
        top_sources = sources[: max(1, case.source_top_k)]
        top_source_text = _norm("\n".join(top_sources))
        if not any(_contains(top_source_text, hint) for hint in case.source_top_any):
            failures.append(
                f"missing top-{case.source_top_k} source hint: "
                + " | ".join(case.source_top_any)
            )

    if case.expected_route_filter:
        route_filter = str((response.get("query_route") or {}).get("dataset_filter") or "")
        if route_filter != case.expected_route_filter:
            failures.append(f"route={route_filter or '-'} != {case.expected_route_filter}")

    if case.expected_quality_status:
        trace = response.get("retrieval_trace") or {}
        quality_status = str(trace.get("quality_status") or "")
        if quality_status != case.expected_quality_status:
            failures.append(
                f"quality={quality_status or '-'} != {case.expected_quality_status}"
            )
    if require_native_rrf:
        trace = response.get("retrieval_trace") or {}
        if str(trace.get("status") or "") != "ok":
            failures.append(f"retrieval_status={trace.get('status') or '-'} != ok")
        mode = str(trace.get("mode") or "")
        if not mode.startswith("qdrant_native_hybrid"):
            failures.append(f"mode={mode or '-'} does not start with qdrant_native_hybrid")
        fusion = str(trace.get("fusion") or "").casefold()
        if fusion not in {"rrf", "qdrant_rrf+lexical_safety_rrf"}:
            failures.append(f"fusion={trace.get('fusion') or '-'} is not native RRF")
        channels = {str(channel) for channel in (trace.get("retrieval_channels") or [])}
        missing_channels = {"dense", "qdrant_sparse"} - channels
        if missing_channels:
            failures.append("missing retrieval channels: " + ", ".join(sorted(missing_channels)))
        rerank = trace.get("rerank") if isinstance(trace.get("rerank"), dict) else {}
        if str(rerank.get("status") or "") != "bypassed":
            failures.append(f"rerank_status={rerank.get('status') or '-'} != bypassed")
        if str(rerank.get("reason") or "") != "disabled":
            failures.append(f"rerank_reason={rerank.get('reason') or '-'} != disabled")
        if str(rerank.get("preserved_order") or "") != "native_rrf":
            failures.append(
                f"preserved_order={rerank.get('preserved_order') or '-'} != native_rrf"
            )

    if failures:
        return GoldenResult(case.id, False, "; ".join(failures), elapsed, len(chunks), top_score, sources)
    return GoldenResult(case.id, True, "passed", elapsed, len(chunks), top_score, sources)


def run_case(
    client: GoldenClient,
    case: GoldenCase,
    *,
    require_native_rrf: bool = False,
) -> GoldenResult:
    result = client.post_json("/api/rag/retrieve-debug", request_payload(case))
    if result.status != 200:
        return GoldenResult(case.id, False, f"HTTP {result.status}: {result.body[:240]}", result.elapsed)
    try:
        payload = result.json()
    except json.JSONDecodeError as exc:
        return GoldenResult(case.id, False, f"invalid JSON: {exc}", result.elapsed)
    return evaluate_response(
        case,
        payload,
        result.elapsed,
        require_native_rrf=require_native_rrf,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LES RAG retrieval golden set.")
    parser.add_argument("--proxy-url", default=os.getenv("LES_PROXY_URL", "http://127.0.0.1:8050"))
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--api-key", default=os.getenv("LES_USER_KEY", os.getenv("LES_ADMIN_KEY", "")))
    parser.add_argument("--key-db", default="", help="Read active key from local SQLite DB")
    parser.add_argument("--key-role", default="", choices=("", "user", "admin"))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("LES_GOLDEN_TIMEOUT", "30")))
    parser.add_argument("--jsonl", action="store_true", help="Emit machine-readable JSON lines.")
    parser.add_argument(
        "--require-source-verification",
        action="store_true",
        help="Fail before live calls when a case has no expected source hint.",
    )
    parser.add_argument(
        "--require-native-rrf",
        action="store_true",
        help="Require retrieval_trace status=ok and fusion=rrf for every case.",
    )
    return parser.parse_args(argv)


def _result_line(result: GoldenResult) -> str:
    mark = "OK" if result.ok else "FAIL"
    elapsed = f"{result.elapsed:.2f}s" if result.elapsed else "-"
    sources = ", ".join(source for source in result.sources[:3] if source)
    suffix = f" sources={sources}" if sources else ""
    return (
        f"[{mark:4}] {result.id:28} {elapsed:>7} "
        f"chunks={result.chunks:<2} top={result.top_score:.3f} {result.detail}{suffix}"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.proxy_url = args.proxy_url.rstrip("/")
    api_key = args.api_key
    if not api_key and args.key_db:
        api_key = local_active_key(args.key_db, args.key_role)

    try:
        cases = load_cases(args.cases)
    except Exception as exc:
        print(f"Cannot load golden set {args.cases}: {exc}", file=sys.stderr)
        return 2
    if args.require_source_verification:
        missing_source_checks = validate_source_verified_cases(cases)
        if missing_source_checks:
            print(
                "Golden cases without source verification: "
                + ", ".join(missing_source_checks),
                file=sys.stderr,
            )
            return 2

    client = GoldenClient(args.proxy_url, args.timeout, api_key)
    if not args.jsonl:
        print(f"LES RAG golden set: proxy={args.proxy_url} cases={args.cases}")

    failed = 0
    for case in cases:
        result = run_case(
            client,
            case,
            require_native_rrf=bool(args.require_native_rrf),
        )
        failed += 0 if result.ok else 1
        if args.jsonl:
            print(json.dumps(result.__dict__, ensure_ascii=False), flush=True)
        else:
            print(_result_line(result), flush=True)

    if args.jsonl:
        return 1 if failed else 0
    if failed:
        print(f"\nGolden set failed: {failed}/{len(cases)} cases failed.", file=sys.stderr)
        return 1
    print(f"\nGolden set passed: {len(cases)} cases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
