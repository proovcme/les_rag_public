"""Unified Construction Harness v0.9 — real source adapters (unavailable-safe, без фейков).

Превращает размытые limitation'ы (parquet_only / lexical_miss / qdrant_not_used / mail_source_missing)
в ЯВНЫЕ adapter-статусы с source_kind и searched_tiers. Адаптеры оборачивают РЕАЛЬНЫЕ сервисы:
- lexical: LexicalIndex (sync SQLite/FTS) — реально находит, если индекс есть;
- vector: Qdrant/retrieval — async+backend, в sync/offline → unavailable (НЕ фейк);
- mail: mail_query — async+backend, без него → unavailable/not_configured (НЕ фейк).

Инвариант: нет реального source_ref → не RETRIEVED; backend недоступен → warning+unavailable, не выдумка.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

# статусы и source_kind
FOUND, NOT_FOUND, NO_SCOPE, UNAVAILABLE, ERROR = "found", "not_found", "no_scope", "unavailable", "error"
TIMEOUT, NO_SOURCE, WEAK_RELATED = "timeout", "no_source", "weak_related"
KIND_PARQUET = "parquet_row"
KIND_FILENAME = "filename_metadata"
KIND_LEXICAL = "lexical_chunk"
KIND_VECTOR = "vector_chunk"
KIND_MAIL = "mail_message"
KIND_WORKBOOK = "workbook_cell"


@dataclass
class AdapterMatch:
    source_kind: str
    source_ref: str
    file_name: str = ""
    dataset_id: str = ""
    snippet: str = ""
    chunk_id: str = ""
    page: int | None = None
    row_id: int | None = None
    score: float | None = None
    matched_term: str = ""


@dataclass
class SourceAdapterResult:
    status: str                       # found|not_found|no_scope|unavailable|error
    source_kind: str = "unknown"
    matches: list[AdapterMatch] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)

    @property
    def source_refs(self) -> list[str]:
        return [m.source_ref for m in self.matches]


def _norm(s: Any) -> str:
    return re.sub(r"[\s.\-_]", "", str(s)).lower()


# ── lexical adapter (sync SQLite/FTS — реально закрывает parquet_only/lexical_miss) ───────

def search_lexical_chunks(query_terms: list[str], *, dataset_ids: list[str] | None = None,
                          doc_type_filter: set[str] | None = None, top_k: int = 8) -> SourceAdapterResult:
    """Поиск термина в lexical-чанках (тело PDF/доков, если проиндексировано). source-scoped exact:
    оставляем только чанки, где термин реально встречается, и (если задан) нужного doc_type."""
    if not query_terms:
        return SourceAdapterResult(NOT_FOUND, KIND_LEXICAL, warnings=["нет термина для поиска"])
    try:
        from proxy.services.lexical_index_service import LexicalIndex, lexical_enabled
        from backend.rag_config import rag_collection_name
        if not lexical_enabled():
            return SourceAdapterResult(UNAVAILABLE, KIND_LEXICAL,
                                       warnings=["lexical_unavailable: lexical-индекс выключен"])
        idx = LexicalIndex()
        chunks = idx.search(" ".join(query_terms), collection=rag_collection_name(),
                            dataset_ids=dataset_ids or None, limit=top_k * 3)
    except Exception as e:  # noqa: BLE001
        return SourceAdapterResult(UNAVAILABLE, KIND_LEXICAL,
                                   warnings=[f"lexical_unavailable: {str(e)[:80]}"])
    terms_norm = [_norm(t) for t in query_terms if _norm(t)]
    matches: list[AdapterMatch] = []
    for c in chunks:
        text = getattr(c, "text", "") or getattr(c, "content", "") or ""
        doc = str(getattr(c, "doc_name", "") or "")
        if doc_type_filter:
            from proxy.services.unified_construction_harness_service import classify_doc_type
            if classify_doc_type(doc) not in doc_type_filter:
                continue
        tnorm = _norm(text)
        hit = next((qt for qt in terms_norm if qt and qt in tnorm), None)
        if not hit:
            continue
        ds = str(getattr(c, "dataset_id", "") or "")
        ord_ = getattr(c, "chunk_ord", None)
        ref = f"{ds}/{doc}#chunk{ord_}" if ord_ is not None else f"{ds}/{doc}#chunk"
        matches.append(AdapterMatch(KIND_LEXICAL, ref, file_name=doc, dataset_id=ds,
                                    snippet=text[:200], chunk_id=str(ord_), matched_term=hit,
                                    score=getattr(c, "score", None)))
        if len(matches) >= top_k:
            break
    status = FOUND if matches else NOT_FOUND
    return SourceAdapterResult(status, KIND_LEXICAL, matches=matches,
                               trace=[{"adapter": "lexical", "chunks_scanned": len(chunks), "matches": len(matches)}])


# ── vector adapter (Qdrant/retrieval — async+backend → unavailable в sync/offline) ────────

def search_vector_chunks(question: str, *, dataset_ids: list[str] | None = None,
                         doc_type_filter: set[str] | None = None, top_k: int = 6) -> SourceAdapterResult:
    """Векторный (Qdrant) поиск. Требует async rag_backend; в sync unified-пути/offline → UNAVAILABLE
    с явным warning (НЕ фейк). Реальная интеграция — когда backend подключён в sync-обёртке."""
    try:
        from proxy.routers.chat import get_chat_state
        state = get_chat_state()
        backend = getattr(state, "backend", None)
    except Exception:  # noqa: BLE001
        backend = None
    if backend is None or not hasattr(backend, "query_points") and not hasattr(backend, "search"):
        return SourceAdapterResult(UNAVAILABLE, KIND_VECTOR, warnings=[
            "vector_unavailable: Qdrant/vector backend не подключён к sync unified-пути"])
    # backend есть, но retrieve_chat_chunks асинхронный — в sync-обёртке не вызываем (честно unavailable)
    return SourceAdapterResult(UNAVAILABLE, KIND_VECTOR, warnings=[
        "vector_unavailable: vector-ретрив асинхронный, не вшит в sync unified-путь (v0.9 deferred)"])


# ── mail adapter (read-only; async mail_query+backend → unavailable/not_configured) ───────

def retrieve_mail_evidence(query_terms: list[str], *, project_id: int = 0,
                           dataset_ids: list[str] | None = None) -> SourceAdapterResult:
    """Read-only поиск по почте. Существующий mail_query асинхронный и требует rag_backend +
    mail-dataset. Без них → UNAVAILABLE (mail_backend_not_configured). НИКАКИХ send/push/mutate."""
    try:
        from proxy.routers.chat import get_chat_state
        state = get_chat_state()
        backend = getattr(state, "backend", None)
    except Exception:  # noqa: BLE001
        backend = None
    if backend is None or not hasattr(backend, "list_datasets"):
        return SourceAdapterResult(UNAVAILABLE, KIND_MAIL, warnings=[
            "mail_backend_not_configured: почтовый backend (rag_backend + mail-dataset) не подключён"])
    # backend есть, но maybe_answer_mail_query асинхронный — в sync-пути не вызываем (честно unavailable)
    return SourceAdapterResult(UNAVAILABLE, KIND_MAIL, warnings=[
        "mail_backend_not_configured: async mail_query не вшит в sync unified-путь (v0.9 deferred)"])


# ── v0.10: async-адаптеры (вызываются из _run_chat через инжектированные замыкания) ───────
# Адаптер НЕ знает тяжёлую сигнатуру retrieve_chat_chunks/mail_query — caller передаёт готовую
# async-функцию. Адаптер делает timeout/error→статус и требует source_ref. БЕЗ фейков.

VectorFn = Callable[[str, "list[str] | None"], Awaitable[Any]]
MailFn = Callable[[str], Awaitable[Any]]


def _chunk_ref(c: Any) -> tuple[str, str, str, str]:
    ds = str(getattr(c, "dataset_id", "") or (getattr(c, "meta", {}) or {}).get("dataset_id", "") or "")
    doc = str(getattr(c, "doc_name", "") or (getattr(c, "meta", {}) or {}).get("file_name", "") or "")
    ord_ = getattr(c, "chunk_ord", None)
    if ord_ is None:
        ord_ = (getattr(c, "meta", {}) or {}).get("chunk_ord")
    text = getattr(c, "text", "") or getattr(c, "content", "") or ""
    ref = f"{ds}/{doc}#chunk{ord_}" if ord_ is not None else (f"{ds}/{doc}#vec" if doc else "")
    return ds, doc, str(ord_), ref, text  # type: ignore[return-value]


async def search_vector_chunks_async(question: str, *, dataset_ids: list[str] | None = None,
                                     doc_type_filter: set[str] | None = None,
                                     exact_terms: list[str] | None = None,
                                     vector_fn: VectorFn | None = None,
                                     require_exact: bool = False,
                                     timeout_s: float = 8.0) -> SourceAdapterResult:
    """Векторный (Qdrant/RAG) поиск через инжектированный vector_fn. Нет fn → unavailable.
    require_exact: для source-scoped exact — матч только если термин реально в сниппете; иначе
    weak_related (НЕ выдаём семантический матч за точное вхождение). Источник без ref → не RETRIEVED."""
    if vector_fn is None:
        return SourceAdapterResult(UNAVAILABLE, KIND_VECTOR,
                                   warnings=["vector_backend_unavailable: vector-retrieval не подключён"])
    try:
        chunks = await asyncio.wait_for(vector_fn(question, dataset_ids), timeout_s)
    except asyncio.TimeoutError:
        return SourceAdapterResult(TIMEOUT, KIND_VECTOR, warnings=["vector_timeout: превышен лимит ответа"])
    except Exception as e:  # noqa: BLE001
        return SourceAdapterResult(ERROR, KIND_VECTOR, warnings=[f"vector_error: {str(e)[:80]}"])
    chunks = list(chunks or [])
    terms_norm = [_norm(t) for t in (exact_terms or []) if _norm(t)]
    matches, weak = [], 0
    for c in chunks:
        ds, doc, ord_, ref, text = _chunk_ref(c)
        if not ref:
            continue                                   # нет source_ref → не RETRIEVED (не фейк)
        if doc_type_filter and doc:
            from proxy.services.unified_construction_harness_service import classify_doc_type
            if classify_doc_type(doc) not in doc_type_filter:
                continue
        is_exact = (not terms_norm) or any(t in _norm(text) for t in terms_norm)
        if require_exact and not is_exact:
            weak += 1
            continue                                   # семантический без термина → weak, не found
        matches.append(AdapterMatch(KIND_VECTOR, ref, file_name=doc, dataset_id=ds, snippet=text[:200],
                                    chunk_id=ord_, score=getattr(c, "score", None),
                                    matched_term=(exact_terms[0] if terms_norm and is_exact else "")))
    if matches:
        return SourceAdapterResult(FOUND, KIND_VECTOR, matches=matches,
                                   trace=[{"adapter": "vector", "chunks": len(chunks), "matches": len(matches)}])
    status = WEAK_RELATED if weak else NOT_FOUND
    w = ["vector: семантически близкие документы есть, но точного термина нет (weak_related)"] if weak else []
    return SourceAdapterResult(status, KIND_VECTOR, warnings=w,
                               trace=[{"adapter": "vector", "chunks": len(chunks), "weak": weak}])


async def retrieve_mail_evidence_async(query_terms: list[str], question: str = "", *,
                                       mail_fn: MailFn | None = None, timeout_s: float = 8.0) -> SourceAdapterResult:
    """Read-only поиск по почте через инжектированный mail_fn (обёртка maybe_answer_mail_query). Нет fn →
    mail_backend_not_configured. Только snippet (НЕ полное тело в trace). НИКАКИХ send/push/delete."""
    if mail_fn is None:
        return SourceAdapterResult(UNAVAILABLE, KIND_MAIL,
                                   warnings=["mail_backend_not_configured: почтовый backend не подключён"])
    try:
        res = await asyncio.wait_for(mail_fn(question or " ".join(query_terms)), timeout_s)
    except asyncio.TimeoutError:
        return SourceAdapterResult(TIMEOUT, KIND_MAIL, warnings=["mail_timeout: превышен лимит ответа"])
    except Exception as e:  # noqa: BLE001
        return SourceAdapterResult(ERROR, KIND_MAIL, warnings=[f"mail_error: {str(e)[:80]} (почта не изменялась)"])
    if res is None:
        return SourceAdapterResult(NOT_FOUND, KIND_MAIL, warnings=["mail: писем по запросу не найдено"])
    items = getattr(res, "items", None) or getattr(res, "messages", None) or []
    matches = []
    for m in items:
        get = (lambda k: m.get(k) if isinstance(m, dict) else getattr(m, k, None))
        mid = str(get("message_id") or get("id") or "")
        subj = str(get("subject") or "")
        ref = mid or (f"mail/{subj[:30]}" if subj else "")
        if not ref:
            continue                                   # нет message_id/source_ref → не RETRIEVED
        snippet = str(get("snippet") or get("preview") or "")[:200]   # ТОЛЬКО snippet, не полное тело
        matches.append(AdapterMatch(KIND_MAIL, ref, file_name=subj[:60], snippet=snippet, matched_term=mid))
    status = FOUND if matches else NOT_FOUND
    return SourceAdapterResult(status, KIND_MAIL, matches=matches,
                               trace=[{"adapter": "mail", "messages": len(matches)}])
