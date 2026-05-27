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

    def payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "detail": self.detail,
            "term_coverage": round(self.term_coverage, 3),
            "source_diversity": self.source_diversity,
            "top_score": round(self.top_score, 4),
        }


def evaluate_retrieval_quality(
    *,
    question: str,
    chunks: list[Any],
    trace: RetrievalTrace,
    kot: KotDecision,
) -> RetrievalQuality:
    if not chunks:
        return RetrievalQuality("weak", "no_chunks", 0.0, 0, 0.0)

    terms = query_terms(question)
    haystack = "\n".join(f"{getattr(chunk, 'doc_name', '')}\n{getattr(chunk, 'content', '')}" for chunk in chunks).casefold()
    matched = {term for term in terms if term in haystack}
    term_coverage = len(matched) / len(terms) if terms else 1.0
    source_diversity = len({getattr(chunk, "doc_name", "") for chunk in chunks})
    top_score = float(getattr(chunks[0], "score", 0.0) or 0.0)

    if kot.ambiguous and source_diversity > 2:
        return RetrievalQuality("needs_clarification", "ambiguous_kot_multi_source", term_coverage, source_diversity, top_score)
    if trace.mode == "vector" and top_score < 0.42 and term_coverage < 0.34:
        return RetrievalQuality("weak", "low_vector_score_and_term_coverage", term_coverage, source_diversity, top_score)
    if term_coverage < 0.25 and source_diversity > 3:
        return RetrievalQuality("weak", "broad_low_coverage", term_coverage, source_diversity, top_score)
    if trace.mode == "hybrid" and trace.lexical_count > 0:
        return RetrievalQuality("good", "hybrid_evidence", term_coverage, source_diversity, top_score)
    return RetrievalQuality("good", "vector_evidence", term_coverage, source_diversity, top_score)


def expanded_quality_query(question: str, kot: KotDecision) -> str:
    additions = [*kot.matched_terms, *kot.norm_refs]
    unique = [item for item in dict.fromkeys(additions) if item and item not in question.casefold()]
    if not unique:
        return question
    return question + "\n" + " ".join(unique[:12])
