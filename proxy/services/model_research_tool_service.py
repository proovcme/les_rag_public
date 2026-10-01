"""Model-requested source search bound to the canonical chat retriever."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping

from proxy.services import nr_sp_service


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

    from proxy.smeta_core.norm_browser import browse_norms_many

    # Model-owned searches must not trigger legacy domain vocabulary from a
    # product name or a source locator. The exact declared query is the input
    # to the same typed/native-RRF reader, not a template chosen by code.
    return browse_norms_many([query], limit=limit, rerank=True, expand_queries=False)[str(query)]


def _norm_card_content(card: Mapping[str, Any]) -> str:
    """Transport typed evidence; a resource preview is not a work composition."""

    steps = [str(item) for item in card.get("work_steps") or [] if str(item).strip()]
    parts = [
        f"Шифр: {card.get('norm_code') or ''}",
        f"Наименование: {card.get('title') or ''}",
        f"Измеритель: {card.get('measure_unit') or ''}",
        "Состав работы: " + "; ".join(steps) if steps else "Состав работ в карточке не указан.",
    ]
    if card.get("edition"):
        parts.append(f"Редакция: {card['edition']}")
    if card.get("source_ref"):
        parts.append(f"Источник: {card['source_ref']}")
    rules = card.get("nr_sp_candidates") or []
    if rules:
        parts.append("НР/СП: варианты каталога для сборника; выбор модели по условиям объекта, не готовая ставка:")
        parts.extend(
            f"{rule['rule_id']}: {rule['label']}; НР {rule['nr_pct']}%; СП {rule['sp_pct']}%; "
            f"{rule['basis']}; источник {rule['source_ref']}"
            for rule in rules
        )
    resources = [
        item for item in card.get("resource_preview") or []
        if isinstance(item, Mapping) and str(item.get("name") or "").strip()
    ]
    if resources:
        count = card.get("resource_count")
        shown = f"показано {len(resources)} из {count}" if isinstance(count, int) else f"показано {len(resources)}"
        parts.append(f"Ресурсы нормы (обзор, {shown}; не заменяет состав работ):")
        parts.extend(
            " · ".join(str(item.get(key) or "") for key in ("kind", "code", "name", "unit"))
            for item in resources
        )
    return "\n".join(parts)


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


#: Blocker § 2 (29.09): «раздельно измерять найдено/показано/отложено/выбрано».
#: The pool a search matched is a different number from the cards the model
#: evidence cap lets through, and the two retrievers already report the pool —
#: the dedicated norm browser as ``fusion_candidates``, the canonical RRF as
#: ``merged_count``.  It is recorded under this key on every served chunk so the
#: per-query measurement can name found and shown apart.  A truncation that
#: happens before the count is taken is what made «найдено» read as the ceiling.
MATCHED_BEFORE_CAP_META_KEY = "matched_before_cap"


def _pre_cap_match_count(trace: Mapping[str, Any], matched: int) -> int:
    """How many candidates the search found, before any model-facing cap."""

    for key in ("fusion_candidates", "merged_count"):
        value = trace.get(key)
        if isinstance(value, (int, float)) and int(value) > 0:
            return max(int(value), matched)
    return matched


def _stamp_pre_cap_match_count(chunks: tuple[Any, ...], matched: int) -> None:
    for chunk in chunks:
        meta = getattr(chunk, "meta", None)
        if isinstance(meta, dict):
            meta[MATCHED_BEFORE_CAP_META_KEY] = int(matched)


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
        retrieval_candidate_k: int = 64,
        document_diversity_k: int = 2,
        model_evidence_k: int = 6,
    ) -> None:
        self._retrieve = retrieve
        self._dataset_ids = tuple(str(item) for item in frozen_dataset_ids if str(item))
        self._retrieval_kwargs = dict(retrieval_kwargs)
        self._fallback = fallback
        self._smeta_norm_retrieve = smeta_norm_retrieve
        self._retrieval_candidate_k = max(int(retrieval_candidate_k), 1)
        self._document_diversity_k = max(int(document_diversity_k), 1)
        self._model_evidence_k = max(int(model_evidence_k), 1)

    @property
    def cache_contract(self) -> str:
        # The old dedicated reader expanded source labels through a vocabulary.
        # Such cached hits (including empty results) must never mask a literal search.
        return "smeta_literal_query_v1" if self._smeta_norm_retrieve is not None else "shared_native_query_v1"

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
                limit=self._model_evidence_k,
            )
            trace = dict(browse.get("retrieval_trace") or {})
            rag_trace = trace.get("rag") if isinstance(trace.get("rag"), Mapping) else {}
            rag_status = str(rag_trace.get("status") or "").strip().casefold()
            cards_all = list(browse.get("cards") or [])

            # Integrity filter (NOT a norm selection): only cards that genuinely
            # originate from the typed smeta base carry a norm code plus a base
            # reference. Cards without that provenance are dropped so a leftover
            # non-empty list is never treated as authoritative evidence; the model
            # still decides which verified card applies.
            def _has_normative_provenance(card: Mapping[str, Any]) -> bool:
                return bool(str(card.get("norm_code") or "").strip()) and bool(
                    str(card.get("source_ref") or card.get("norm_key") or "").strip()
                )

            cards_verified = [card for card in cards_all if _has_normative_provenance(card)]
            dropped_unverified = len(cards_all) - len(cards_verified)
            # What the norm search matched is recorded before the model-evidence
            # cap trims it, so «найдено» and «показано» stay two numbers.
            matched_before_cap = _pre_cap_match_count(trace, len(cards_all))
            # `degraded_sparse_only` is a documented functional state: the additive
            # dense channel is down but exact/FTS cards from the typed base remain.
            # Those verified cards still reach the model, yet the search is reported
            # honestly as degraded, never as a healthy ``ok``. Block only on a hard
            # channel failure that produced no verified card, and never fall back to
            # the mixed general RRF corpus.
            dense_functional = rag_status in {"ok", "degraded_sparse_only"}
            if not dense_functional and not cards_verified:
                return ModelResearchToolResult(
                    payload={
                        "schema": "les_tool_result_v1",
                        "tool": "search_sources",
                        "operation": "smeta_norm_native_rrf",
                            "inputs": [{"q": query, "limit": self._model_evidence_k}],
                        "status": "blocked",
                        "result": {
                            "hits": [],
                            "count": 0,
                            "matched_before_cap": matched_before_cap,
                            "evidence_cap": self._model_evidence_k,
                        },
                        "sources": [],
                        "missing": ["dedicated smeta native RRF is not ready"],
                        "warnings": [],
                        "trace": trace,
                        "decision_required_from_model": True,
                    },
                    retrieval_trace=trace,
                )
            cards = [
                {**card, "nr_sp_candidates": nr_sp_service.model_candidates(code=str(card["norm_code"]))}
                for card in cards_verified[: self._model_evidence_k]
            ]
            chunks = tuple(
                _SmetaNormChunk(
                    content=_norm_card_content(card),
                    doc_name="smeta_norm_cards.v1",
                    score=float(max(len(cards) - index, 1)),
                    meta={
                        **{
                            key: card[key]
                            for key in (
                                "norm_key", "edition", "base_type", "work_steps", "resource_count",
                                "resource_kinds", "resource_preview", "nr_sp_candidates",
                            )
                            if key in card
                        },
                        "norm_code": str(card.get("norm_code") or ""),
                        "measure_unit": str(card.get("measure_unit") or ""),
                        "source_ref": str(card.get("source_ref") or ""),
                        "minimum_evidence_body_chars": len(_norm_card_content({**card, "resource_preview": []})),
                        MATCHED_BEFORE_CAP_META_KEY: int(matched_before_cap),
                    },
                )
                for index, card in enumerate(cards)
            )
            hits = [_chunk_payload(chunk) for chunk in chunks]
            # Honest effective status: a degraded channel stays degraded even when
            # it serves verified cards; zero verified hits is a model-visible
            # ``missing``; only a healthy ``ok`` channel reports ``ok``.
            if not hits:
                effective_status = "missing"
            elif rag_status == "ok":
                effective_status = "ok"
            else:
                effective_status = "degraded_sparse_only"
            result_warnings: list[str] = []
            if dropped_unverified:
                result_warnings.append(
                    f"{dropped_unverified} card(s) dropped for missing normative provenance"
                )
            if effective_status == "degraded_sparse_only":
                dense_detail = str(rag_trace.get("dense_error_detail") or "").strip()
                dense_reason = str(rag_trace.get("reason") or "").strip()
                dense_endpoint = str(rag_trace.get("dense_endpoint") or "").strip()
                dense_why = dense_detail or dense_reason or "dense vector channel unavailable"
                result_warnings.append(
                    "exact/FTS normative cards served from the dedicated base; "
                    f"dense vector channel unavailable ({dense_why}"
                    + (f" at {dense_endpoint}" if dense_endpoint else "")
                    + ")"
                )
            return ModelResearchToolResult(
                payload={
                    "schema": "les_tool_result_v1",
                    "tool": "search_sources",
                    "operation": "smeta_norm_native_rrf",
                    "inputs": [{"q": query, "limit": self._model_evidence_k}],
                    "status": effective_status,
                    "result": {
                        "hits": hits,
                        "count": len(hits),
                        "matched_before_cap": matched_before_cap,
                        "verified_before_cap": len(cards_verified),
                        "evidence_cap": self._model_evidence_k,
                    },
                    "sources": [
                        {
                            "doc_name": hit["doc_name"],
                            "source_ref": (hit.get("meta") or {}).get("source_ref") or "",
                        }
                        for hit in hits
                    ],
                    "missing": [] if hits else ["no smeta norm cards matched query"],
                    "warnings": result_warnings,
                    "trace": trace,
                    "decision_required_from_model": True,
                },
                chunks=chunks,
                retrieval_trace=trace,
            )

        retrieval = await self._retrieve(
            question=query,
            dataset_ids=list(self._dataset_ids),
            result_limit=self._model_evidence_k,
            candidate_limit=self._retrieval_candidate_k,
            document_diversity_k=self._document_diversity_k,
            **self._retrieval_kwargs,
        )
        all_chunks = tuple(retrieval.chunks)
        chunks = all_chunks[: self._model_evidence_k]
        trace = dict(retrieval.payload())
        matched_before_cap = _pre_cap_match_count(trace, len(all_chunks))
        _stamp_pre_cap_match_count(chunks, matched_before_cap)
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
            "result": {
                "hits": hits,
                "count": len(hits),
                "matched_before_cap": matched_before_cap,
                "evidence_cap": self._model_evidence_k,
            },
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
