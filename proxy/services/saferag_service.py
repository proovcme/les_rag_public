"""SafeRAG result and context policy."""

from __future__ import annotations

import logging
import re
from typing import Iterable, Protocol

logger = logging.getLogger(__name__)


class SourceChunk(Protocol):
    content: str
    doc_name: str


STOPWORDS = {
    "какая",
    "какие",
    "какой",
    "каким",
    "что",
    "это",
    "для",
    "или",
    "при",
    "над",
    "под",
    "если",
    "есть",
    "нужно",
    "нужен",
    "требуется",
    "применяется",
    "применяются",
    "регулируется",
    "относится",
    "относятся",
}

SAFE_FALLBACK = (
    "Система безопасности (Т.О.С.К.А.) не смогла подтвердить ответ из базы знаний. "
    "Попробуйте переформулировать вопрос или выбрать другой датасет."
)


def final_answer_for_status(answer: str, status: str) -> tuple[str, str]:
    if status in ("VERIFIED", "NO_DATA", "UNVALIDATED"):
        return answer, status
    if status in ("HALLUCINATION", "UNKNOWN"):
        return SAFE_FALLBACK, status
    return SAFE_FALLBACK, "UNKNOWN"


def query_terms(question: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[0-9a-zа-яё]{3,}", question.casefold())
        if token not in STOPWORDS and len(token) >= 4
    }


def rank_chunks_for_question(question: str, chunks: list[SourceChunk]) -> list[SourceChunk]:
    """Apply a tiny lexical boost on top of vector score for evidence ordering."""
    terms = query_terms(question)
    if not terms or not chunks:
        return chunks

    def rank_key(index_chunk: tuple[int, SourceChunk]) -> tuple[float, float, int]:
        index, chunk = index_chunk
        haystack = f"{chunk.doc_name}\n{chunk.content}".casefold()
        matches = sum(1 for term in terms if term in haystack)
        title_matches = sum(1 for term in terms if term in chunk.doc_name.casefold())
        score = float(getattr(chunk, "score", 0.0) or 0.0)
        boosted = score + matches * 0.12 + title_matches * 0.03
        try:
            setattr(chunk, "_rank_score", boosted)
        except Exception:
            pass
        return (boosted, score, -index)

    ranked = sorted(enumerate(chunks), key=rank_key, reverse=True)
    return [chunk for _, chunk in ranked]


def _doc_family(name: str) -> str:
    normalized = name.casefold()
    normalized = re.sub(r"\s+\(\d+\)(?=\.[^.]+$)", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _content_fingerprint(chunk: SourceChunk) -> str:
    text = re.sub(r"\s+", " ", chunk.content.casefold()).strip()
    return text[:500]


def concentrate_sources(
    chunks: list[SourceChunk],
    max_docs: int = 2,
    min_score: float = 0.45,
    max_chunks: int | None = None,
) -> list[SourceChunk]:
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
        score = getattr(chunk, "_rank_score", getattr(chunk, "score", 0.0))
        doc_key = _doc_family(chunk.doc_name)
        if doc_key not in doc_max or doc_max[doc_key] < score:
            doc_max[doc_key] = score

    top_docs = set(sorted(doc_max, key=lambda doc: -doc_max[doc])[:max_docs])
    result = []
    seen_content: set[str] = set()
    for chunk in filtered:
        if _doc_family(chunk.doc_name) not in top_docs:
            continue
        fingerprint = _content_fingerprint(chunk)
        if fingerprint in seen_content:
            continue
        seen_content.add(fingerprint)
        result.append(chunk)
        if max_chunks is not None and len(result) >= max_chunks:
            break

    removed_docs = {chunk.doc_name for chunk in chunks if _doc_family(chunk.doc_name) not in top_docs}
    if removed_docs:
        logger.info("[FOCUS] Отсечено %s нерелевантных источников: %s", len(removed_docs), removed_docs)

    return result


def _source_label(index: int, chunk: SourceChunk, include_metadata: bool) -> str:
    if not include_metadata:
        return f"[{chunk.doc_name}]"
    score = getattr(chunk, "score", None)
    meta = getattr(chunk, "meta", {}) or {}
    details = [f"Источник {index}", chunk.doc_name]
    if isinstance(score, (int, float)):
        details.append(f"score={score:.3f}")
    page = meta.get("source_page") or meta.get("page") or meta.get("page_number")
    if page:
        details.append(f"стр. {page}")
    doc_type = meta.get("doc_type")
    if doc_type:
        details.append(str(doc_type))
    return "[" + " | ".join(details) + "]"


_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


def _clean_chunk_text(text: str) -> str:
    """Снять тег-суп `<br>` из деградированных табличных чанков (~18% корпуса: «215<br>1<br>5»,
    «**<br>**») перед подачей в LLM — модель не должна видеть HTML-мусор. Пайпы НЕ трогаем
    (можно сломать настоящую markdown-таблицу). No-op для чистого текста (дешёвый гард)."""
    if not text or "<br" not in text.lower():
        return text
    t = _BR_RE.sub(" ", text)
    t = re.sub(r"\*\*\s*\*\*", " ", t)   # осиротевшие ** после удаления <br>
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t


_NUM_RUN_RE = re.compile(r"\d[\d  .,]{2,}\d")


def numeric_provenance_check(answer: str, context: str, *, max_flags: int = 5) -> list[str]:
    """Числа в ОТВЕТЕ (4+ значащих цифр), которых НЕТ в контексте — возможно не заземлённые
    (Codex §8, пет-гард, ТОЛЬКО метит). RAG не должен сам считать: число берётся из контекста.
    Нормализуем разделители (15 030,72 ↔ 15030.72). Годы (1900-2099) и короткие — пропускаем."""
    def _norm(s: str) -> str:
        return re.sub(r"[  .,]", "", s or "")

    ctx = _norm(context)
    flagged: list[str] = []
    for m in _NUM_RUN_RE.finditer(answer or ""):
        digits = re.sub(r"\D", "", m.group())
        if len(digits) < 4:
            continue
        if len(digits) == 4 and 1900 <= int(digits) <= 2099:   # год — не флагуем
            continue
        if digits not in ctx:
            flagged.append(m.group().strip())
        if len(flagged) >= max_flags:
            break
    return flagged


def build_context(chunks: Iterable[SourceChunk], max_chars: int, *, include_metadata: bool = False) -> str:
    parts: list[str] = []
    total = 0
    for index, chunk in enumerate(chunks, 1):
        part = f"{_source_label(index, chunk, include_metadata)}:\n{_clean_chunk_text(chunk.content)}"
        if total + len(part) > max_chars:
            break
        parts.append(part)
        total += len(part)
    return "\n\n".join(parts)


def build_validation_context(
    chunks: Iterable[SourceChunk],
    max_chars: int = 8000,
    *,
    include_metadata: bool = False,
) -> str:
    """Build the cited retrieval window passed to the validator."""
    return build_context(chunks, max_chars, include_metadata=include_metadata)


def source_names(chunks: Iterable[SourceChunk]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.doc_name in seen:
            continue
        names.append(chunk.doc_name)
        seen.add(chunk.doc_name)
    return names
