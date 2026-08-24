"""Hermetic A/B gate for ColBERT MaxSim and RAPTOR evidence descent."""

from __future__ import annotations

import json
import time

from backend.colbert_late_interaction import rerank_token_vectors
from backend.raptor_tree import RaptorLeaf, build_tree, evidence_leaf_ids


CASES = [
    {
        "id": "fire-clause",
        "query": [[1, 0, 0], [0, 1, 0]],
        "baseline": ["mention", "exact", "noise"],
        "vectors": {"mention": [[1, 0, 0]], "exact": [[1, 0, 0], [0, 1, 0]], "noise": [[0, 0, 1]]},
        "relevant": "exact",
    },
    {
        "id": "drawing-mark",
        "query": [[0, 1, 0], [0, 0, 1]],
        "baseline": ["generic", "wrong", "exact"],
        "vectors": {"generic": [[0, 1, 0]], "wrong": [[1, 0, 0]], "exact": [[0, 1, 0], [0, 0, 1]]},
        "relevant": "exact",
    },
    {
        "id": "table-row",
        "query": [[1, 0, 0], [0, 0, 1]],
        "baseline": ["prose", "exact", "other"],
        "vectors": {"prose": [[1, 0, 0]], "exact": [[1, 0, 0], [0, 0, 1]], "other": [[0, 1, 0]]},
        "relevant": "exact",
    },
]


def _mrr(rankings: list[list[str]], relevant: list[str]) -> float:
    return sum(1.0 / (ranking.index(target) + 1) for ranking, target in zip(rankings, relevant, strict=True)) / len(rankings)


def run() -> dict:
    started = time.perf_counter()
    baseline = [case["baseline"] for case in CASES]
    colbert = [
        [item[0] for item in rerank_token_vectors(
            case["query"], case["vectors"].items(), top_k=len(case["vectors"])
        )]
        for case in CASES
    ]
    relevant = [case["relevant"] for case in CASES]

    leaves = [
        RaptorLeaf("leaf-fire", "doc-fire", "эвакуация дым пожар"),
        RaptorLeaf("leaf-hvac", "doc-hvac", "вентиляция расход воздух"),
        RaptorLeaf("leaf-bim", "doc-bim", "марка позиция чертёж"),
    ]
    tree = build_tree(
        leaves,
        lambda texts, depth: (f"route-{depth}", " ".join(texts)),
        fanout=2,
        max_depth=2,
    )
    descended = evidence_leaf_ids(tree)
    elapsed_ms = (time.perf_counter() - started) * 1000
    result = {
        "schema": "les.rag.advanced-synthetic-ab.v1",
        "cases": len(CASES),
        "baseline_mrr": round(_mrr(baseline, relevant), 6),
        "colbert_mrr": round(_mrr(colbert, relevant), 6),
        "colbert_recall_at_1": sum(ranking[0] == target for ranking, target in zip(colbert, relevant, strict=True)) / len(CASES),
        "raptor_navigation_nodes": len(tree),
        "raptor_exact_leaf_coverage": len(set(descended)) == len(leaves),
        "raptor_navigation_citable": False,
        "elapsed_ms": round(elapsed_ms, 3),
    }
    result["passed"] = bool(
        result["colbert_mrr"] > result["baseline_mrr"]
        and result["colbert_recall_at_1"] == 1.0
        and result["raptor_exact_leaf_coverage"]
        and not result["raptor_navigation_citable"]
    )
    return result


def main() -> int:
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
