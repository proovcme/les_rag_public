"""Model-requested source search bound to the canonical chat retriever."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping


@dataclass(frozen=True)
class ModelResearchToolResult:
    payload: dict[str, Any]
    chunks: tuple[Any, ...] = ()
    retrieval_trace: dict[str, Any] | None = None


@dataclass(frozen=True)
class _SmetaNormChunk:
    content: str
    doc_name: str
    score: float
    meta: dict[str, Any]


def retrieve_smeta_norm_cards(query: str, *, limit: int = 6) -> dict[str, Any]:
    """Read model-facing cards from the dedicated smeta dense+sparse RRF."""

    from proxy.smeta_core.norm_browser import browse_norms

    return browse_norms(query, limit=limit)


def _chunk_payload(chunk: Any) -> dict[str, Any]:
    meta = getattr(chunk, "meta", {}) or {}
    payload: dict[str, Any] = {
        "content": str(getattr(chunk, "content", "") or ""),
        "doc_name": str(getattr(chunk, "doc_name", "") or ""),
        "score": float(getattr(chunk, "score", 0.0) or 0.0),
        "meta": dict(meta) if isinstance(meta, Mapping) else {},
    }
    for name in ("id", "chunk_id", "dataset_id", "source_ref", "page", "_rank_score"):
        value = getattr(chunk, name, None)
        if value is not None:
            payload[name] = value
    return payload


class ModelResearchToolService:
    """Execute model tools without allowing `search_sources` to leave native RRF."""

    def __init__(
        self,
        *,
        retrieve: Callable[..., Awaitable[Any]],
        frozen_dataset_ids: tuple[str, ...],
        retrieval_kwargs: Mapping[str, Any],
        fallback: Callable[[str, dict[str, Any]], Any],
        smeta_norm_retrieve: Callable[..., Mapping[str, Any]] | None = None,
    ) -> None:
        self._retrieve = retrieve
        self._dataset_ids = tuple(str(item) for item in frozen_dataset_ids if str(item))
        self._retrieval_kwargs = dict(retrieval_kwargs)
        self._fallback = fallback
        self._smeta_norm_retrieve = smeta_norm_retrieve

    async def execute(self, call: Mapping[str, Any]) -> ModelResearchToolResult:
        tool = str(call.get("tool") or "")
        args = dict(call.get("args") or {})
        if tool != "search_sources":
            payload = self._fallback(tool, args)
            if inspect.isawaitable(payload):
                payload = await payload
            return ModelResearchToolResult(payload=payload)

        query = str(args.get("q") or "").strip()
        if not query:
            return ModelResearchToolResult(
                payload={
                    "schema": "les_tool_result_v1",
                    "tool": "search_sources",
                    "operation": "native_rrf",
                    "inputs": [{"q": "", "dataset_ids": list(self._dataset_ids)}],
                    "status": "missing",
                    "result": {"hits": [], "count": 0},
                    "sources": [],
                    "missing": ["q"],
                    "warnings": [],
                    "trace": {},
                    "decision_required_from_model": True,
                }
            )

        if self._smeta_norm_retrieve is not None:
            browse = await asyncio.to_thread(
                self._smeta_norm_retrieve,
                query,
                limit=6,
            )
            trace = dict(browse.get("retrieval_trace") or {})
            rag_trace = trace.get("rag") if isinstance(trace.get("rag"), Mapping) else {}
            if str(rag_trace.get("status") or "") != "ok" or not str(
                rag_trace.get("collection") or ""
            ).strip():
                return ModelResearchToolResult(
                    payload={
                        "schema": "les_tool_result_v1",
                        "tool": "search_sources",
                        "operation": "smeta_norm_native_rrf",
                        "inputs": [{"q": query, "limit": 6}],
                        "status": "blocked",
                        "result": {"hits": [], "count": 0},
                        "sources": [],
                        "missing": ["dedicated smeta native RRF is not ready"],
                        "warnings": [],
                        "trace": trace,
                        "decision_required_from_model": True,
                    },
                    retrieval_trace=trace,
                )
            cards = list(browse.get("cards") or [])[:6]
            chunks = tuple(
                _SmetaNormChunk(
                    content="\n".join(
                        part
                        for part in (
                            f"Шифр: {card.get('norm_code') or ''}",
                            f"Наименование: {card.get('title') or ''}",
                            f"Измеритель: {card.get('measure_unit') or ''}",
                            (
                                "Состав работы: "
                                + "; ".join(
                                    str(item)
                                    for item in (card.get("work_steps") or [])
                                    if str(item).strip()
                                )
                                if card.get("work_steps")
                                else ""
                            ),
                        )
                        if part
                    ),
                    doc_name="smeta_norm_cards.v1",
                    score=float(max(len(cards) - index, 1)),
                    meta={
                        "norm_code": str(card.get("norm_code") or ""),
                        "measure_unit": str(card.get("measure_unit") or ""),
                        "source_ref": str(card.get("source_ref") or ""),
                    },
                )
                for index, card in enumerate(cards)
            )
            hits = [_chunk_payload(chunk) for chunk in chunks]
            return ModelResearchToolResult(
                payload={
                    "schema": "les_tool_result_v1",
                    "tool": "search_sources",
                    "operation": "smeta_norm_native_rrf",
                    "inputs": [{"q": query, "limit": 6}],
                    "status": "ok" if hits else "missing",
                    "result": {"hits": hits, "count": len(hits)},
                    "sources": [
                        {
                            "doc_name": hit["doc_name"],
                            "source_ref": (hit.get("meta") or {}).get("source_ref") or "",
                        }
                        for hit in hits
                    ],
                    "missing": [] if hits else ["no smeta norm cards matched query"],
                    "warnings": [],
                    "trace": trace,
                    "decision_required_from_model": True,
                },
                chunks=chunks,
                retrieval_trace=trace,
            )

        retrieval = await self._retrieve(
            question=query,
            dataset_ids=list(self._dataset_ids),
            **self._retrieval_kwargs,
        )
        chunks = tuple(retrieval.chunks)
        trace = dict(retrieval.payload())
        hits = [_chunk_payload(chunk) for chunk in chunks]
        sources = [
            {
                "doc_name": hit.get("doc_name") or "",
                "dataset_id": (hit.get("meta") or {}).get("dataset_id") or hit.get("dataset_id") or "",
                "chunk_id": (hit.get("meta") or {}).get("chunk_id") or hit.get("chunk_id") or hit.get("id") or "",
                "page": (hit.get("meta") or {}).get("page") or hit.get("page"),
            }
            for hit in hits
        ]
        payload = {
            "schema": "les_tool_result_v1",
            "tool": "search_sources",
            "operation": "native_rrf",
            "inputs": [{"q": query, "dataset_ids": list(self._dataset_ids)}],
            "status": "ok" if hits else "missing",
            "result": {"hits": hits, "count": len(hits)},
            "sources": sources,
            "missing": [] if hits else ["no indexed chunks matched query"],
            "warnings": [],
            "trace": trace,
            "decision_required_from_model": True,
        }
        return ModelResearchToolResult(
            payload=payload,
            chunks=chunks,
            retrieval_trace=trace,
        )
