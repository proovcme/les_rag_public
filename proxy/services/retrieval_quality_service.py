"""Cheap retrieval quality checks before generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from proxy.services.kot_service import KotDecision
from proxy.services.lexical_index_service import RetrievalTrace
from proxy.services.saferag_service import query_terms


@dataclass(frozen=True)
class RetrievalQuality:
    status: str
    detail: str
    term_coverage: float
    source_diversity: int
    top_score: float
    score_kind: str = "unknown"

    def payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "detail": self.detail,
            "term_coverage": round(self.term_coverage, 3),
            "source_diversity": self.source_diversity,
            "top_score": round(self.top_score, 4),
            "score_kind": self.score_kind,
        }


def evaluate_retrieval_quality(
    *,
    question: str,
    chunks: list[Any],
    trace: RetrievalTrace,
    kot: KotDecision,
) -> RetrievalQuality:
    if not chunks:
        return RetrievalQuality("weak", "no_chunks", 0.0, 0, 0.0, trace.score_kind)

    terms = query_terms(question)
    haystack = "\n".join(f"{getattr(chunk, 'doc_name', '')}\n{getattr(chunk, 'content', '')}" for chunk in chunks).casefold()
    matched = {term for term in terms if term in haystack}
    term_coverage = len(matched) / len(terms) if terms else 1.0
    source_diversity = len({getattr(chunk, "doc_name", "") for chunk in chunks})
    top_score = float(getattr(chunks[0], "score", 0.0) or 0.0)

    if trace.fallback_reason == "embedding_contract_mismatch":
        return RetrievalQuality(
            "degraded",
            "lexical_only_embedding_contract_mismatch",
            term_coverage,
            source_diversity,
            top_score,
            trace.score_kind,
        )
    if kot.ambiguous and source_diversity > 2:
        return RetrievalQuality("needs_clarification", "ambiguous_kot_multi_source", term_coverage, source_diversity, top_score, trace.score_kind)
    # Absolute score thresholds are valid only for a declared dense-similarity
    # channel. Qdrant RRF, local RRF, FTS and cross-encoder logits are not cosine.
    if trace.score_kind == "dense_similarity" and top_score < 0.42 and term_coverage < 0.34:
        return RetrievalQuality("weak", "low_dense_score_and_term_coverage", term_coverage, source_diversity, top_score, trace.score_kind)
    # A broad scatter of individually weak candidates is not positive evidence just
    # because several query words occur somewhere in the pool.  Keep the model
    # path open, but make the trace/evidence packet honest: it must be able to
    # ask for a target file or a narrower follow-up instead of presenting this
    # as a good retrieval result.
    if term_coverage < 0.25 and source_diversity > 3:
        return RetrievalQuality("weak", "broad_low_coverage", term_coverage, source_diversity, top_score, trace.score_kind)
    if "hybrid" in trace.mode:
        detail = "hybrid_evidence" if term_coverage >= 0.25 or trace.exact_refs else "hybrid_partial_support"
        status = "good" if detail == "hybrid_evidence" else "weak"
        return RetrievalQuality(status, detail, term_coverage, source_diversity, top_score, trace.score_kind)
    return RetrievalQuality("good", "retrieval_evidence", term_coverage, source_diversity, top_score, trace.score_kind)


def expanded_quality_query(question: str, kot: KotDecision) -> str:
    additions = [*kot.matched_terms, *kot.norm_refs]
    unique = [item for item in dict.fromkeys(additions) if item and item not in question.casefold()]
    if not unique:
        return question
    return question + "\n" + " ".join(unique[:12])
