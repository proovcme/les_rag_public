"""A/B smoke for the model-visible smeta candidate order.

This compares the same queries before and after the configured cross-encoder.
It validates retrieval transport only and never declares a norm applicable.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from proxy.smeta_core.norm_browser import browse_norms_many
from tools.smeta_rag_quality_probe import DEFAULT_QUERIES


def _top(result: dict, depth: int) -> list[str]:
    return [
        f"{card.get('norm_code') or '?'} {str(card.get('title') or '').strip()[:70]}"
        for card in (result.get("cards") or [])[:depth]
    ]


def run_probe(
    queries: list[str],
    *,
    limit: int,
    depth: int,
    base_path: Path | None = None,
    expected_terms: dict[str, list[str]] | None = None,
) -> dict:
    shared = {"limit": limit, "base_path": base_path}
    started = time.perf_counter()
    before = browse_norms_many(queries, rerank=False, **shared)
    before_ms = round((time.perf_counter() - started) * 1000)
    started = time.perf_counter()
    after = browse_norms_many(queries, rerank=True, **shared)
    after_ms = round((time.perf_counter() - started) * 1000)

    rows = []
    statuses: set[str] = set()
    moved = 0
    for query in queries:
        raw = before.get(query, {})
        ranked = after.get(query, {})
        status = str(
            (ranked.get("retrieval_trace") or {}).get("rerank_status")
            or "missing"
        )
        rag_trace = dict((ranked.get("retrieval_trace") or {}).get("rag") or {})
        statuses.add(status)
        top_raw = _top(raw, depth)
        top_ranked = _top(ranked, depth)
        changed = top_raw[:1] != top_ranked[:1]
        expected = list((expected_terms or {}).get(query) or [])
        ranked_text = " ".join(top_ranked).casefold().replace("ё", "е")
        quality_match = (
            any(term.casefold().replace("ё", "е") in ranked_text for term in expected)
            if expected
            else None
        )
        moved += int(changed)
        rows.append({
            "query": query,
            "before": top_raw,
            "after": top_ranked,
            "top1_changed": changed,
            "rerank_status": status,
            "rag_status": str(rag_trace.get("status") or ""),
            "rag_reason": str(rag_trace.get("reason") or ""),
            "expected_terms": expected,
            "quality_match": quality_match,
        })
    quality_rows = [row for row in rows if row["quality_match"] is not None]
    return {
        "schema": "les.smeta.rerank-ab.v1",
        "queries": len(queries),
        "limit": limit,
        "rerank_status": sorted(statuses),
        "top1_changed": moved,
        "quality_checks": len(quality_rows),
        "quality_passed": sum(bool(row["quality_match"]) for row in quality_rows),
        "elapsed_ms": {"rrf_only": before_ms, "reranked": after_ms},
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-path", type=Path, default=None)
    parser.add_argument("--collection", default="")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--query", action="append", default=[])
    parser.add_argument(
        "--expect-after",
        action="append",
        default=[],
        help="Pipe-separated terms; at least one must occur in the matching query's reranked top depth.",
    )
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument(
        "--require-ok",
        action="store_true",
        help="Exit non-zero unless every query reached the reranker successfully.",
    )
    parser.add_argument(
        "--require-hybrid",
        action="store_true",
        help="Exit non-zero unless dense+sparse retrieval is compatible for every query.",
    )
    parser.add_argument(
        "--require-quality",
        action="store_true",
        help="Exit non-zero unless every --expect-after check matches the visible shortlist.",
    )
    args = parser.parse_args()
    if args.collection:
        os.environ["LES_SMETA_NORM_RAG_COLLECTION"] = args.collection

    queries = args.query or DEFAULT_QUERIES
    if args.expect_after and len(args.expect_after) != len(queries):
        parser.error("--expect-after must be provided once for every query")
    expected_terms = {
        query: [term.strip() for term in spec.split("|") if term.strip()]
        for query, spec in zip(queries, args.expect_after, strict=False)
    }
    report = run_probe(
        queries,
        limit=max(1, min(args.limit, 50)),
        depth=max(1, args.depth),
        base_path=args.base_path,
        expected_terms=expected_terms,
    )
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.report_path.with_suffix(args.report_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(args.report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.require_ok and report["rerank_status"] != ["ok"]:
        return 1
    if args.require_hybrid and any(row["rag_status"] != "ok" for row in report["rows"]):
        return 1
    if args.require_quality and (
        report["quality_checks"] != len(report["rows"])
        or report["quality_passed"] != report["quality_checks"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
