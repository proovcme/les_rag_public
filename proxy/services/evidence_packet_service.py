"""Common evidence packet for ordinary LES retrieval turns.

The packet is deliberately a *composition* boundary.  It does not retrieve,
rerank, validate an answer, or make a domain decision.  Its job is to keep the
model-facing source fragments, their exact visible citations, navigation, and
retrieval quality in one explicit contract.

Navigation remains useful for choosing where to read next, but is never
serialised as source evidence.  Domain modules may add their own typed facts or
calculation traces later; the generic RAG path starts with retrieved chunks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable, Mapping

from proxy.services.saferag_service import build_context, source_map_for_context


SCHEMA = "les.evidence_packet.v1"
_SOURCE_LABEL_RE = re.compile(r"\[Источник\s+(\d+)\b", re.IGNORECASE)
_TRACE_KEYS = (
    "mode",
    "quality_status",
    "fallback_reason",
    "vector_count",
    "lexical_count",
    "merged_count",
    "rerank",
    "embedding_contract",
    "embedding_model",
    "query_embedding",
)
_LOCATOR_KEYS = (
    "dataset_id",
    "file_name",
    "source_ref",
    "source_page",
    "page",
    "page_number",
    "sheet",
    "sheet_name",
    "table_name",
    "row",
    "row_number",
    "cell",
    "section",
    "section_heading",
    "parent_heading",
    "chunk_ord",
    "content_type",
    "doc_type",
)


def _plain_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _json_value(value: Any) -> Any:
    """Keep API payloads serialisable without leaking arbitrary metadata objects."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _locator_for(source: Mapping[str, Any], chunk: Any) -> dict[str, Any]:
    meta = _plain_mapping(getattr(chunk, "meta", {}))
    locator: dict[str, Any] = {}
    for key in _LOCATOR_KEYS:
        value = source.get(key)
        if value in (None, ""):
            value = meta.get(key)
        if value not in (None, ""):
            locator[key] = _json_value(value)
    # `doc_name` is the stable file coordinate even if legacy metadata omitted
    # `file_name`; keeping it at the top level avoids a synthetic locator.
    return locator


def _retrieval_summary(trace: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in _TRACE_KEYS:
        if trace.get(key) not in (None, ""):
            summary[key] = trace[key]
    return summary


def _evidence_status(chunks: list[Any], trace: Mapping[str, Any]) -> str:
    """State source availability without claiming that the final answer is true."""
    if not chunks:
        return "missing"
    quality = str(trace.get("quality_status") or "").casefold()
    if (
        trace.get("fallback_reason")
        or trace.get("empty_retrieval")
        or quality in {"degraded", "weak", "lexical_only", "failed"}
        or quality.startswith("degraded_")
    ):
        return "partial"
    return "available"


@dataclass
class RetrievalEvidencePacket:
    """Bounded retrieved evidence plus explicit non-evidence navigation."""

    question: str
    chunks: list[Any] = field(default_factory=list, repr=False)
    retrieval_trace: dict[str, Any] = field(default_factory=dict, repr=False)
    navigation: list[dict[str, Any]] = field(default_factory=list)
    deterministic_evidence: list[dict[str, Any]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    source_excerpt_chars: int = 360

    @property
    def evidence_status(self) -> str:
        return _evidence_status(self.chunks, self.retrieval_trace)

    def source_map(self, *, max_chars: int, include_metadata: bool = True) -> list[dict[str, object]]:
        return source_map_for_context(
            self.chunks,
            max_chars,
            include_metadata=include_metadata,
            snippet_chars=self.source_excerpt_chars,
        )

    def to_dict(self, *, max_chars: int, include_metadata: bool = True) -> dict[str, Any]:
        visible_sources = self.source_map(max_chars=max_chars, include_metadata=include_metadata)
        sources: list[dict[str, Any]] = []
        for index, source in enumerate(visible_sources, 1):
            original_index = int(source.get("original_chunk_index") or 0)
            chunk = self.chunks[original_index] if 0 <= original_index < len(self.chunks) else None
            score = source.get("score")
            meta = _plain_mapping(getattr(chunk, "meta", {}))
            item: dict[str, Any] = {
                "id": f"S{index}",
                "context_label": str(source.get("label") or f"Источник {index}"),
                "doc_name": str(source.get("doc_name") or ""),
                "doc_id": str(getattr(chunk, "doc_id", "") or ""),
                "excerpt": str(source.get("snippet") or ""),
                "locator": _locator_for(source, chunk),
                "support_scope": str(meta.get("support_scope") or "retrieved_for_question"),
                "context_role": "evidence",
                "is_evidence": True,
                "source_version": _json_value(
                    meta.get("source_version") or meta.get("revision_id") or meta.get("file_mtime") or ""
                ),
            }
            retrieval_features = {
                key: _json_value(meta[key])
                for key in (
                    "dense_score",
                    "vector_rank",
                    "lexical_rank",
                    "rrf_score",
                    "rrf_rank",
                    "rerank_score",
                    "rerank_rank",
                )
                if meta.get(key) not in (None, "")
            }
            if retrieval_features:
                item["retrieval_features"] = retrieval_features
            if isinstance(score, (int, float)):
                item["score"] = float(score)
            sources.append(item)

        navigation = [
            {
                **_plain_mapping(item),
                "context_role": "navigation",
                "is_evidence": False,
            }
            for item in self.navigation
            if _plain_mapping(item)
        ]
        deterministic_evidence = [
            {
                **_plain_mapping(item),
                "context_role": "deterministic_evidence",
                "is_evidence": True,
            }
            for item in self.deterministic_evidence
            if _plain_mapping(item)
        ]
        return {
            "schema": SCHEMA,
            "evidence_status": self.evidence_status,
            "answer_status": "separate_in_chat_response",
            "calculation_status": "not_applicable",
            "retrieval": {
                **_retrieval_summary(self.retrieval_trace),
                "candidate_chunk_count": len(self.chunks),
                "visible_source_count": len(sources),
            },
            "evidence": {"is_evidence": True, "sources": sources},
            "navigation": navigation,
            "deterministic_evidence": deterministic_evidence,
            "missing": list(dict.fromkeys(str(item) for item in self.missing if str(item).strip())),
        }

    def trace_summary(self, *, max_chars: int, include_metadata: bool = True) -> dict[str, Any]:
        """Small provenance record suitable for durable retrieval trace/history."""
        payload = self.to_dict(max_chars=max_chars, include_metadata=include_metadata)
        return {
            "schema": SCHEMA,
            "evidence_status": payload["evidence_status"],
            "candidate_chunk_count": payload["retrieval"]["candidate_chunk_count"],
            "visible_source_count": payload["retrieval"]["visible_source_count"],
            "source_ids": [source["id"] for source in payload["evidence"]["sources"]],
            "source_documents": [source["doc_name"] for source in payload["evidence"]["sources"]],
            "navigation_kinds": [str(item.get("kind") or "") for item in payload["navigation"]],
            "missing": payload["missing"],
        }


def build_retrieval_evidence_packet(
    *,
    question: str,
    chunks: Iterable[Any] | None,
    retrieval_trace: Mapping[str, Any] | None,
    navigation: Iterable[Mapping[str, Any]] | None = None,
    deterministic_evidence: Iterable[Mapping[str, Any]] | None = None,
    missing: Iterable[str] | None = None,
) -> RetrievalEvidencePacket:
    """Build the common RAG packet from already selected chunks.

    The caller owns retrieval and context-window expansion.  Keeping this pure
    lets the same contract serve the normal chat route, targeted document reads,
    and later domain adapters without an index migration.
    """
    return RetrievalEvidencePacket(
        question=str(question or ""),
        chunks=list(chunks or []),
        retrieval_trace=_plain_mapping(retrieval_trace),
        navigation=[_plain_mapping(item) for item in (navigation or []) if _plain_mapping(item)],
        deterministic_evidence=[
            _plain_mapping(item) for item in (deterministic_evidence or []) if _plain_mapping(item)
        ],
        missing=[str(item) for item in (missing or []) if str(item).strip()],
    )


def render_retrieval_evidence_for_model(
    packet: RetrievalEvidencePacket,
    *,
    max_chars: int,
    include_metadata: bool = True,
) -> str:
    """Render only the retrieved sources, with the same citation labels returned to UI.

    Navigation and tool outputs intentionally remain separate prompt blocks.  A
    model can use them to choose a next read, but its factual answer must cite
    the source labels emitted here.
    """
    status = packet.evidence_status
    status_note = ""
    if status == "partial":
        status_note = (
            "[СТАТУС ИСТОЧНИКОВ: ЧАСТИЧНОЕ ПОКРЫТИЕ. "
            "Используй все приведённые фрагменты для полезного ответа, но не называй их полным покрытием корпуса; "
            "явно отделяй подтверждённое от того, что не читалось или не найдено.]\n"
        )
    elif status == "missing":
        status_note = (
            "[СТАТУС ИСТОЧНИКОВ: ФРАГМЕНТЫ НЕ НАЙДЕНЫ. "
            "Не выдумывай факт или отсутствие документа; предложи следующий read только если он следует из карты корпуса.]\n"
        )
    context = build_context(packet.chunks, max_chars, include_metadata=include_metadata)
    if not context:
        return status_note + "[ФРАГМЕНТЫ ИЗ ИСТОЧНИКОВ]\nНет найденных фрагментов."
    return status_note + "[ФРАГМЕНТЫ ИЗ ИСТОЧНИКОВ]\n" + context


def verify_answer_source_labels(answer: str, source_map: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Cheap post-generation citation integrity check; never judges domain truth."""
    sources = list(source_map or [])
    available = {
        int(item.get("index") or index)
        for index, item in enumerate(sources, 1)
        if isinstance(item, Mapping)
    }
    cited = [int(value) for value in _SOURCE_LABEL_RE.findall(str(answer or ""))]
    invalid = sorted({value for value in cited if value not in available})
    if not available:
        status = "not_applicable"
    elif invalid:
        status = "invalid_labels"
    elif not cited:
        status = "missing_labels"
    else:
        status = "supported_labels"
    return {
        "schema": "les.answer-citation-check.v1",
        "status": status,
        "available": sorted(available),
        "cited": sorted(set(cited)),
        "invalid": invalid,
    }
