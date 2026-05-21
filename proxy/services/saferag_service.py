"""SafeRAG result and context policy."""

from __future__ import annotations

import logging
from typing import Iterable, Protocol

logger = logging.getLogger(__name__)


class SourceChunk(Protocol):
    content: str
    doc_name: str

SAFE_FALLBACK = (
    "Система безопасности (Т.О.С.К.А.) не смогла подтвердить ответ из базы знаний. "
    "Попробуйте переформулировать вопрос или выбрать другой датасет."
)


def final_answer_for_status(answer: str, status: str) -> tuple[str, str]:
    if status in ("VERIFIED", "NO_DATA"):
        return answer, status
    if status in ("HALLUCINATION", "UNKNOWN"):
        return SAFE_FALLBACK, status
    return SAFE_FALLBACK, "UNKNOWN"


def concentrate_sources(chunks: list[SourceChunk], max_docs: int = 2, min_score: float = 0.45) -> list[SourceChunk]:
    """
    Keep chunks from the most relevant documents to reduce context contamination.

    The score attribute is optional for compatibility with reranker fallback stubs.
    Missing scores are treated as relevant.
    """
    if not chunks:
        return chunks

    filtered = [c for c in chunks if getattr(c, "score", 1.0) >= min_score]
    if not filtered:
        best = max(getattr(c, "score", 0.0) for c in chunks)
        filtered = [c for c in chunks if getattr(c, "score", 0.0) >= best * 0.8]

    doc_max: dict[str, float] = {}
    for chunk in filtered:
        score = getattr(chunk, "score", 0.0)
        if chunk.doc_name not in doc_max or doc_max[chunk.doc_name] < score:
            doc_max[chunk.doc_name] = score

    top_docs = set(sorted(doc_max, key=lambda doc: -doc_max[doc])[:max_docs])
    result = [chunk for chunk in filtered if chunk.doc_name in top_docs]

    removed_docs = {chunk.doc_name for chunk in chunks} - top_docs
    if removed_docs:
        logger.info("[FOCUS] Отсечено %s нерелевантных источников: %s", len(removed_docs), removed_docs)

    return result


def build_context(chunks: Iterable[SourceChunk], max_chars: int) -> str:
    parts: list[str] = []
    total = 0
    for chunk in chunks:
        part = f"[{chunk.doc_name}]:\n{chunk.content}"
        if total + len(part) > max_chars:
            break
        parts.append(part)
        total += len(part)
    return "\n\n".join(parts)


def source_names(chunks: Iterable[SourceChunk]) -> list[str]:
    return list({chunk.doc_name for chunk in chunks})
