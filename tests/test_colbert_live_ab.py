from tools.colbert_live_ab import native_rrf_contract_error, rerank_response, summarize_ab
from tools.rag_golden_set import GoldenCase, evaluate_response


class FakeEncoder:
    def encode(self, texts, *, max_length):
        vectors = {
            "нужный документ": [[1.0, 0.0]],
            "нерелевантно": [[0.0, 1.0]],
            "точный ответ": [[1.0, 0.0]],
        }
        return [vectors[text] for text in texts]


def test_live_ab_reranks_only_returned_rrf_candidates():
    response = {
        "chunks": [
            {"doc_name": "wrong.pdf", "preview": "нерелевантно", "score": 0.9},
            {"doc_name": "right.pdf", "preview": "точный ответ", "score": 0.8},
        ],
        "retrieval_trace": {"fusion": "rrf"},
    }

    reranked, trace = rerank_response(
        "нужный документ",
        response,
        encoder=FakeEncoder(),
        candidate_k=2,
        output_k=2,
        max_query_tokens=48,
        max_passage_tokens=128,
    )

    assert [row["doc_name"] for row in reranked["chunks"]] == [
        "right.pdf",
        "wrong.pdf",
    ]
    assert trace["input_order"] == ["0", "1"]
    assert trace["output_order"] == ["1", "0"]
    assert response["chunks"][0]["doc_name"] == "wrong.pdf"


def test_ab_summary_reports_quality_without_manufacturing_success():
    case = GoldenCase(
        id="fixture",
        question="нужный документ",
        source_top_any=("right.pdf",),
        source_top_k=1,
    )
    baseline = {
        "chunks": [
            {"doc_name": "wrong.pdf", "preview": "нерелевантно", "score": 0.9},
            {"doc_name": "right.pdf", "preview": "точный ответ", "score": 0.8},
        ]
    }
    reranked, trace = rerank_response(
        case.question,
        baseline,
        encoder=FakeEncoder(),
        candidate_k=2,
        output_k=2,
        max_query_tokens=48,
        max_passage_tokens=128,
    )

    summary = summarize_ab(
        [
            {
                "case": case,
                "baseline": evaluate_response(case, baseline),
                "colbert": evaluate_response(case, reranked),
                "trace": trace,
            }
        ]
    )

    assert summary["cases"] == 1
    assert summary["baseline_passed"] == 0
    assert summary["colbert_passed"] == 1
    assert summary["improved"] == 1
    assert summary["regressed"] == 0


def test_live_ab_refuses_a_candidate_pool_that_is_not_native_rrf():
    error = native_rrf_contract_error(
        {
            "chunks": [{"doc_name": "right.pdf", "preview": "точный ответ"}],
            "retrieval_trace": {"status": "blocked", "fusion": "none"},
        }
    )

    assert "retrieval_status=blocked != ok" in error


def test_live_ab_accepts_the_canonical_native_rrf_trace():
    error = native_rrf_contract_error(
        {
            "chunks": [{"doc_name": "right.pdf", "preview": "точный ответ"}],
            "retrieval_trace": {
                "status": "ok",
                "mode": "qdrant_native_hybrid_named",
                "fusion": "rrf",
                "retrieval_channels": ["dense", "qdrant_sparse"],
                "rerank": {
                    "status": "bypassed",
                    "reason": "disabled",
                    "preserved_order": "native_rrf",
                },
            },
        }
    )

    assert error == ""


def test_live_ab_accepts_native_rrf_with_query_quality_degraded():
    error = native_rrf_contract_error(
        {
            "chunks": [{"doc_name": "right.pdf", "preview": "точный ответ"}],
            "retrieval_trace": {
                "status": "degraded",
                "error_code": "",
                "mode": "qdrant_native_hybrid+parent_card",
                "fusion": "qdrant_rrf+lexical_safety_rrf",
                "retrieval_channels": ["dense", "qdrant_sparse", "lexical"],
                "rerank": {
                    "status": "bypassed",
                    "reason": "disabled",
                    "preserved_order": "native_rrf",
                },
            },
        }
    )

    assert error == ""
