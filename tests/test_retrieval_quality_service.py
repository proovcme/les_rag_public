from types import SimpleNamespace as N

from proxy.services.kot_service import KotDecision
from proxy.services.lexical_index_service import RetrievalTrace
from proxy.services.retrieval_quality_service import evaluate_retrieval_quality, expanded_quality_query


def _kot() -> KotDecision:
    return KotDecision(
        dataset_filter=None,
        matched_domains=(),
        matched_terms=(),
        norm_refs=(),
        confidence=0.0,
        reason="test",
    )


def test_qdrant_rrf_score_is_not_treated_as_cosine_threshold():
    chunks = [
        N(content="ведомость объёмов работ", doc_name=f"doc-{index}.pdf", score=0.36, meta={})
        for index in range(4)
    ]

    result = evaluate_retrieval_quality(
        question="ведомость объёмов работ",
        chunks=chunks,
        trace=RetrievalTrace(mode="qdrant_native_hybrid", merged_count=8, score_kind="qdrant_rrf"),
        kot=_kot(),
    )

    assert result.status == "good"
    assert result.detail == "hybrid_evidence"
    assert result.source_diversity == 4
    assert result.score_kind == "qdrant_rrf"


def test_low_dense_similarity_and_low_term_coverage_is_weak():
    chunks = [N(content="другая тема", doc_name="doc.pdf", score=0.21, meta={})]

    result = evaluate_retrieval_quality(
        question="ведомость объёмов работ",
        chunks=chunks,
        trace=RetrievalTrace(mode="vector", merged_count=1, score_kind="dense_similarity"),
        kot=_kot(),
    )

    assert result.status == "weak"
    assert result.detail == "low_dense_score_and_term_coverage"


def test_high_score_hybrid_sources_remain_good():
    chunks = [
        N(content="ведомость объёмов работ", doc_name="target.xlsx", score=0.81, meta={}),
        N(content="ведомость объёмов работ", doc_name="appendix.pdf", score=0.72, meta={}),
    ]

    result = evaluate_retrieval_quality(
        question="ведомость объёмов работ",
        chunks=chunks,
        trace=RetrievalTrace(mode="hybrid", lexical_count=2, merged_count=8),
        kot=_kot(),
    )

    assert result.status == "good"
    assert result.detail == "hybrid_evidence"


def test_weak_retry_query_never_injects_kot_terms_or_norm_refs():
    kot = KotDecision(
        dataset_filter="NTD_FIRE",
        matched_domains=("fire",),
        matched_terms=("дымоудаление",),
        norm_refs=("СП 7.13130",),
        confidence=0.9,
        reason="test",
    )

    assert expanded_quality_query("  исходный   вопрос  ", kot) == "исходный вопрос"
