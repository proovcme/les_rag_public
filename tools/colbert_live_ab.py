#!/usr/bin/env python3
"""Live ColBERT shadow A/B over the exact native-RRF candidate pool.

The tool is read-only: it neither creates a collection nor changes an alias.
It asks the live debug retrieval boundary for candidates, then applies BGE-M3
late interaction locally and evaluates both orders against the same golden case.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
from typing import Any, Iterable

from backend.colbert_late_interaction import BgeM3ColbertEncoder, rerank_token_vectors
from tools.rag_golden_set import (
    GoldenCase,
    GoldenClient,
    GoldenResult,
    evaluate_response,
    load_cases,
    local_active_key,
    request_payload,
)


def _chunk_text(chunk: dict[str, Any]) -> str:
    return "\n".join(
        part
        for part in (
            str(chunk.get("preview") or "").strip(),
            str(chunk.get("expanded_preview") or "").strip(),
        )
        if part
    )


def native_rrf_contract_error(response: dict[str, Any]) -> str:
    """Return a reason when the live pool is not the canonical native-RRF pool."""
    checked = deepcopy(response)
    trace = checked.get("retrieval_trace")
    if isinstance(trace, dict) and trace.get("status") == "degraded":
        # `degraded` may describe per-query answer quality/ambiguity while the
        # candidate pool itself is still the canonical native RRF result.
        mode = str(trace.get("mode") or "")
        fusion = str(trace.get("fusion") or "").casefold()
        if (
            not trace.get("error_code")
            and mode.startswith("qdrant_native_hybrid")
            and fusion in {"rrf", "qdrant_rrf+lexical_safety_rrf"}
        ):
            trace["status"] = "ok"
    contract_case = GoldenCase(
        id="native-rrf-contract",
        question="",
        min_chunks=1,
    )
    result = evaluate_response(
        contract_case,
        checked,
        require_native_rrf=True,
    )
    return "" if result.ok else result.detail


def rerank_response(
    question: str,
    response: dict[str, Any],
    *,
    encoder: Any,
    candidate_k: int,
    output_k: int,
    max_query_tokens: int,
    max_passage_tokens: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rerank only the returned RRF candidates; preserve the input payload."""
    started = time.perf_counter()
    result = deepcopy(response)
    chunks = [
        dict(item)
        for item in (response.get("chunks") or [])[: max(1, int(candidate_k))]
        if isinstance(item, dict)
    ]
    if not chunks:
        return result, {
            "status": "missing",
            "input_order": [],
            "output_order": [],
            "elapsed_ms": 0.0,
        }
    identifiers = [str(index) for index in range(len(chunks))]
    query_vectors = encoder.encode(
        [str(question or "")], max_length=max(8, int(max_query_tokens))
    )[0]
    passage_vectors = encoder.encode(
        [_chunk_text(chunk) for chunk in chunks],
        max_length=max(8, int(max_passage_tokens)),
    )
    ranking = rerank_token_vectors(
        query_vectors,
        zip(identifiers, passage_vectors, strict=True),
        top_k=min(max(1, int(output_k)), len(chunks)),
    )
    by_id = dict(zip(identifiers, chunks, strict=True))
    output_chunks: list[dict[str, Any]] = []
    for identifier, score in ranking:
        chunk = dict(by_id[identifier])
        chunk["colbert_score"] = float(score)
        output_chunks.append(chunk)
    result["chunks"] = output_chunks
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return result, {
        "status": "applied",
        "input_order": identifiers,
        "output_order": [identifier for identifier, _score in ranking],
        "candidate_count": len(chunks),
        "output_count": len(output_chunks),
        "elapsed_ms": round(elapsed_ms, 3),
    }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return float(ordered[index])


def summarize_ab(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(rows)
    baseline_passed = sum(bool(item["baseline"].ok) for item in items)
    colbert_passed = sum(bool(item["colbert"].ok) for item in items)
    improved = sum(
        not item["baseline"].ok and item["colbert"].ok for item in items
    )
    regressed = sum(
        item["baseline"].ok and not item["colbert"].ok for item in items
    )
    elapsed = [float((item.get("trace") or {}).get("elapsed_ms") or 0.0) for item in items]
    return {
        "cases": len(items),
        "baseline_passed": baseline_passed,
        "colbert_passed": colbert_passed,
        "improved": improved,
        "regressed": regressed,
        "colbert_latency_ms": {
            "p50": round(statistics.median(elapsed), 3) if elapsed else 0.0,
            "p95": round(_percentile(elapsed, 0.95), 3),
            "max": round(max(elapsed), 3) if elapsed else 0.0,
        },
        "acceptable": bool(items) and regressed == 0,
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live native-RRF vs ColBERT shadow A/B.")
    parser.add_argument("--proxy-url", default="http://127.0.0.1:8050")
    parser.add_argument("--cases", type=Path, default=Path("golden/domain_fire_hvac_set.json"))
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--api-key", default=os.getenv("LES_USER_KEY", ""))
    parser.add_argument("--key-db", default="")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--candidate-k", type=int, default=12)
    parser.add_argument("--output-k", type=int, default=8)
    parser.add_argument("--max-query-tokens", type=int, default=48)
    parser.add_argument("--max-passage-tokens", type=int, default=128)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    cases = load_cases(args.cases)[: max(1, int(args.limit))]
    if len(cases) < max(1, int(args.limit)):
        print(f"need {args.limit} cases, found {len(cases)}", file=sys.stderr)
        return 2
    api_key = args.api_key or (
        local_active_key(args.key_db) if args.key_db else ""
    )
    client = GoldenClient(args.proxy_url, args.timeout, api_key)
    # The shadow run must remain safe on the Windows CPU-only reference host.
    # Full sibling generation has a separate accelerator preflight.
    encoder = BgeM3ColbertEncoder("BAAI/bge-m3", use_fp16=False)
    rows: list[dict[str, Any]] = []
    for case in cases:
        http_result = client.post_json("/api/rag/retrieve-debug", request_payload(case))
        if http_result.status != 200:
            print(f"{case.id}: HTTP {http_result.status}", file=sys.stderr)
            return 2
        response = http_result.json()
        contract_error = native_rrf_contract_error(response)
        if contract_error:
            print(
                f"{case.id}: candidate pool is not native RRF: {contract_error}",
                file=sys.stderr,
            )
            return 2
        baseline = evaluate_response(case, response, http_result.elapsed)
        reranked, trace = rerank_response(
            case.question,
            response,
            encoder=encoder,
            candidate_k=args.candidate_k,
            output_k=args.output_k,
            max_query_tokens=args.max_query_tokens,
            max_passage_tokens=args.max_passage_tokens,
        )
        colbert = evaluate_response(case, reranked, http_result.elapsed)
        rows.append(
            {
                "case": case,
                "baseline": baseline,
                "colbert": colbert,
                "trace": trace,
            }
        )
        print(
            f"{case.id}: baseline={'PASS' if baseline.ok else 'FAIL'} "
            f"colbert={'PASS' if colbert.ok else 'FAIL'} "
            f"colbert_ms={trace['elapsed_ms']}",
            flush=True,
        )
    summary = summarize_ab(rows)
    receipt = {
        "schema": "les.colbert-live-ab.v1",
        "read_only": True,
        "proxy_url": args.proxy_url,
        "cases_path": str(args.cases),
        "summary": summary,
        "results": [
            {
                "id": item["case"].id,
                "baseline": asdict(item["baseline"]),
                "colbert": asdict(item["colbert"]),
                "trace": item["trace"],
            }
            for item in rows
        ],
    }
    _atomic_json(args.out, receipt)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["acceptable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
