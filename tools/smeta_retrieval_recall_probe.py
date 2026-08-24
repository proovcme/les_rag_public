"""Short retrieval-only recall probe for the live FSNB norm index.

This diagnostic deliberately excludes the LLM, reranker, catalog routing and the
estimate workflow.  It answers one question: does plain norm retrieval place a
known correct code in the first N candidates for several natural paraphrases?
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from typing import Any, Iterable


CASES: tuple[tuple[str, str, str], ...] = (
    ("прибор аппарат установка присоединение", "ГЭСНм08-03-575-01", "strict"),
    ("монтаж прибора с подключением", "ГЭСНм08-03-575-01", "stress"),
    ("установка электрического аппарата", "ГЭСНм08-03-575-01", "stress"),
    ("труба гофрированная ПВХ для защиты кабелей", "ГЭСНм08-02-409-09", "strict"),
    ("прокладка гофротрубы ПВХ для кабеля", "ГЭСНм08-02-409-09", "stress"),
    ("монтаж защитной гофрированной трубы", "ГЭСНм08-02-409-09", "stress"),
    ("устройство обрешётки с прозорами из брусков", "ГЭСН12-01-034-02", "strict"),
    ("устройство деревянной обрешетки кровли", "ГЭСН12-01-034-02", "stress"),
    ("обрешетка из брусков с прозорами", "ГЭСН12-01-034-02", "stress"),
    ("монтаж телекоммуникационного шкафа 42U", "ГЭСНм10-04-087-05", "strict"),
    ("установка серверного шкафа 42U", "ГЭСНм10-04-087-05", "stress"),
    ("монтаж коммутационного шкафа СКС", "ГЭСНм10-04-087-05", "stress"),
)


def _normalized_code(value: str) -> str:
    return re.sub(r"[^0-9а-яa-z]", "", str(value or "").casefold().replace("ё", "е"))


def evaluate_case(
    *,
    query: str,
    expected_code: str,
    candidate_codes: Iterable[str],
    elapsed_seconds: float,
) -> dict[str, Any]:
    codes = [str(code) for code in candidate_codes]
    expected = _normalized_code(expected_code)
    rank = next(
        (index for index, code in enumerate(codes, start=1) if _normalized_code(code) == expected),
        None,
    )
    return {
        "query": query,
        "expected_code": expected_code,
        "hit": rank is not None,
        "rank": rank,
        "candidate_codes": codes,
        "elapsed_seconds": round(float(elapsed_seconds), 3),
    }


def summarize_results(
    results: Iterable[dict[str, Any]], *, total_elapsed_seconds: float,
) -> dict[str, Any]:
    items = list(results)
    strict = [item for item in items if item.get("assessment") == "strict"]
    stress = [item for item in items if item.get("assessment") == "stress"]
    strict_hits = sum(1 for item in strict if item.get("hit"))
    stress_hits = sum(1 for item in stress if item.get("hit"))
    return {
        "strict_hits": strict_hits,
        "strict_misses": len(strict) - strict_hits,
        "strict_recall_at_k": round(strict_hits / max(len(strict), 1), 3),
        "stress_expected_code_visible": stress_hits,
        "stress_cases": len(stress),
        "total_elapsed_seconds": round(float(total_elapsed_seconds), 3),
    }


def run_probe(*, limit: int = 10) -> dict[str, Any]:
    from proxy.smeta_core.norm_browser import browse_norms_many

    queries = [query for query, _expected, _assessment in CASES]
    started = time.perf_counter()
    raw = browse_norms_many(queries, limit=limit, rerank=False)
    total_elapsed = time.perf_counter() - started

    results: list[dict[str, Any]] = []
    backends: set[str] = set()
    rag_statuses: set[str] = set()
    rag_reasons: set[str] = set()
    for query, expected_code, assessment in CASES:
        payload = raw.get(query) or {}
        backends.add(str(payload.get("backend") or "unknown"))
        rag_trace = ((payload.get("retrieval_trace") or {}).get("rag") or {})
        rag_statuses.add(str(rag_trace.get("status") or "unknown"))
        if rag_trace.get("reason"):
            rag_reasons.add(str(rag_trace["reason"]))
        cards = list(payload.get("cards") or [])
        result = evaluate_case(
            query=query,
            expected_code=expected_code,
            candidate_codes=[card.get("norm_code") or "" for card in cards[:limit]],
            elapsed_seconds=total_elapsed / max(len(CASES), 1),
        )
        result["assessment"] = assessment
        results.append(result)

    return {
        "schema": "les.smeta.retrieval_recall_probe.v1",
        "configuration": {
            "cases": len(results),
            "top_k": limit,
            "llm": False,
            "reranker": False,
            "catalog_routing": False,
        },
        "retrieval": {
            "backends": sorted(backends),
            "rag_statuses": sorted(rag_statuses),
            "rag_reasons": sorted(rag_reasons),
        },
        "summary": summarize_results(results, total_elapsed_seconds=total_elapsed),
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be positive")
    report = run_probe(limit=args.top_k)
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if report["summary"]["strict_misses"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
