"""Model-requested source search bound to the canonical chat retriever."""

from __future__ import annotations

import asyncio
import inspect
import unicodedata
import json
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping

from proxy.services import nr_sp_service
from proxy.services.attachment_source_catalog_service import AttachmentSourceCatalog, catalog_source_order_basis
from proxy.services.model_rag_grouped_evidence_service import (
    EvidenceCard, card_delivery_facts, inventory_pointer, normative_card_identity,
)


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


def _full_norm_card_content(card: Mapping[str, Any]) -> str:
    from proxy.services.model_resource_reference_service import resource_slot_records

    parts = [_norm_card_content({**card, "resource_preview": []})]
    parts.append("Полные ресурсы выбранной карточки; применимость выбирает модель:")
    parts.extend(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                 for row in resource_slot_records(card))
    parts.append(f"resources_complete={card.get('resources_complete')!r}; "
                 f"resources_returned={card.get('resources_returned', len(card.get('resources') or []))}")
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
        price_basis: Mapping[str, Any] | None = None,
        norm_card_reader: Callable[..., Mapping[str, Any]] | None = None,
        pricebook_provider: Callable[[str], Any] | None = None,
        attachment_catalog: AttachmentSourceCatalog | None = None,
        expected_attachment_sha256: str | None = None,
    ) -> None:
        self._retrieve = retrieve
        self._dataset_ids = tuple(str(item) for item in frozen_dataset_ids if str(item))
        self._retrieval_kwargs = dict(retrieval_kwargs)
        document_filter = self._retrieval_kwargs.get("doc_filter")
        self._document_scope_invalid = document_filter is not None and (
            not isinstance(document_filter, (list, tuple))
            or any(not isinstance(item, str) or not item.strip() for item in document_filter)
        )
        self._document_names = tuple(document_filter or ()) if not self._document_scope_invalid else ()
        self._fallback = fallback
        self._smeta_norm_retrieve = smeta_norm_retrieve
        self._retrieval_candidate_k = max(int(retrieval_candidate_k), 1)
        self._document_diversity_k = max(int(document_diversity_k), 1)
        self._model_evidence_k = max(int(model_evidence_k), 1)
        self._norm_card_reader = norm_card_reader
        self._pricebook_provider = pricebook_provider
        self._attachment_catalog = attachment_catalog
        self._expected_attachment_sha256 = expected_attachment_sha256
        self._shown_norm_cards: list[dict[str, str]] = []
        self._shown_norm_navigation: list[dict[str, Any]] = []
        self._shown_norm_refs: list[dict[str, Any]] = []
        self._shown_documents: dict[str, tuple[str, str]] = {}
        self.set_price_basis(price_basis or {})

    def set_price_basis(self, price_basis: Mapping[str, Any]) -> None:
        """Bind application-owned durable task scope, never a model-chosen fallback."""
        self._price_basis = dict(price_basis) if isinstance(price_basis, Mapping) else {}

    @property
    def price_basis_snapshot(self) -> dict[str, Any]:
        """Copy the task basis, including the first successfully read book hash."""
        return dict(self._price_basis)

    @staticmethod
    def _document_name(value: str) -> str:
        return unicodedata.normalize("NFC", value.strip().replace("\\", "/")).casefold()

    def _document_allowed(self, name: str) -> bool:
        return not self._document_scope_invalid and (
            not self._document_names or self._document_name(name) in {
                self._document_name(item) for item in self._document_names
            }
        )

    @staticmethod
    def _shown_navigation_pointer(raw, meta, pointer):
        """Read a literal displayed title, never a retained undisclosed body."""
        view = meta.get("model_inventory_view")
        if not view and meta.get("body_status") == "deferred_capacity":
            view = raw.get("content")
        try:
            displayed = json.loads(view) if isinstance(view, str) else None
        except ValueError:
            displayed = None
        if (isinstance(displayed, list) and len(displayed) >= 5
                and isinstance(displayed[0], str) and isinstance(displayed[4], str)
                and displayed[3] == pointer["norm_code"]):
            ref, title = displayed[0], displayed[4]
        elif (meta.get("model_delivery_status") in (None, "", "delivered")
              and meta.get("body_status") != "deferred_capacity"):
            ref = meta.get("model_evidence_ref") or raw.get("model_evidence_ref") or ""
            title = next((line[len("Наименование: "):] for line in str(raw.get("content") or "").splitlines()
                          if line.startswith("Наименование: ")), "")
        else:
            return None
        record = {**pointer, "evidence_ref": ref, "title": title}
        record.update({name: meta.get(name, raw.get(name)) for name in (
            "global_evidence_id", "normative_card_identity", "source_sha256", "edition", "base_type")
            if meta.get(name, raw.get(name)) is not None})
        return record

    def register_shown_norm_cards(self, chunks) -> None:
        """Restore exact pointers from previously shown application-owned evidence."""
        for chunk in chunks:
            raw = chunk if isinstance(chunk, Mapping) else _chunk_payload(chunk)
            meta = raw.get("meta") or {}
            if not isinstance(meta, Mapping):
                continue
            if (meta.get("model_delivery_status") not in (None, "", "delivered")
                    and meta.get("model_inventory_delivery_status") != "delivered"):
                continue
            code = str(meta.get("norm_code") or raw.get("norm_code") or "").strip()
            key = str(meta.get("norm_key") or raw.get("norm_key") or "").strip()
            source = str(meta.get("source_ref") or raw.get("source_ref") or "").strip()
            if code and (key or source):
                pointer = {"norm_code": code, "norm_key": key, "source_ref": source}
                if pointer not in self._shown_norm_cards:
                    self._shown_norm_cards.append(pointer)
                navigation = self._shown_navigation_pointer(raw, meta, pointer)
                if navigation is not None and navigation not in self._shown_norm_navigation:
                    self._shown_norm_navigation.append(navigation)
                if (navigation is not None and self._admitted_norm_reference(raw, meta, navigation)
                        and navigation not in self._shown_norm_refs):
                    self._shown_norm_refs.append(navigation)
            dataset = str(meta.get("dataset_id") or raw.get("dataset_id") or "").strip()
            doc_id = str(meta.get("doc_id") or raw.get("doc_id") or "").strip()
            doc_name = str(raw.get("doc_name") or meta.get("doc_name") or "").strip()
            if dataset in self._dataset_ids and doc_id and self._document_allowed(doc_name):
                self._shown_documents[doc_id] = (dataset, doc_name)

    @staticmethod
    def _admitted_norm_reference(raw, meta, navigation) -> bool:
        """Explicit references require delivery and a consistent literal view."""
        if (meta.get("model_inventory_delivery_status") != "delivered"
                and meta.get("model_delivery_status") != "delivered"):
            return False
        ref = meta.get("model_evidence_ref", raw.get("model_evidence_ref"))
        if not isinstance(ref, str) or not ref or navigation["evidence_ref"] != ref:
            return False
        view = meta.get("model_inventory_view")
        if not view and meta.get("body_status") == "deferred_capacity":
            view = raw.get("content")
        if not view:
            return (meta.get("model_delivery_status") == "delivered"
                    and meta.get("body_status") != "deferred_capacity")
        try:
            displayed = json.loads(view) if isinstance(view, str) else None
        except ValueError:
            return False
        expected = json.loads(inventory_pointer(EvidenceCard(ref, "", "", "", meta)))
        return (isinstance(displayed, list) and len(displayed) >= 7
                and displayed[0] == ref and displayed[1] in ("full", "deferred_capacity")
                and displayed[2:4] == expected[2:4] and displayed[6] == expected[6])

    @staticmethod
    def _missing(tool: str, message: str, *, status: str = "missing") -> ModelResearchToolResult:
        return ModelResearchToolResult(payload={
            "schema": "les_tool_result_v1", "tool": tool, "operation": "scoped_evidence_read",
            "status": status, "result": {"hits": [], "count": 0}, "sources": [],
            "missing": [message], "warnings": [], "trace": {}, "decision_required_from_model": True,
        })

    async def _read_norm_card(self, args: Mapping[str, Any]) -> ModelResearchToolResult:
        reference = "evidence_ref" in args
        if reference:
            if set(args) != {"evidence_ref"}:
                return self._missing("read_norm_card", "evidence_ref must be used alone", status="conflict")
            ref = args["evidence_ref"]
            if not isinstance(ref, str) or not ref:
                return self._missing("read_norm_card", "evidence_ref must be a nonempty literal string")
            pointers = [row for row in self._shown_norm_refs if row["evidence_ref"] == ref]
            if len(pointers) != 1:
                return self._missing("read_norm_card", "evidence_ref must identify one admitted norm pointer",
                                     status="conflict" if pointers else "missing")
            return await self._read_norm_pointer(pointers[0], args, verify_source=True)
        for field in ("norm_key", "norm_code"):
            if field in args and (not isinstance(args[field], str) or not args[field].strip()):
                return self._missing("read_norm_card", f"{field} must be a nonempty string")
        key = str(args.get("norm_key") or "").strip()
        code = str(args.get("norm_code") or "").strip()
        if not key and not code:
            return self._missing("read_norm_card", "norm_key or norm_code is required")
        pointers = [row for row in self._shown_norm_cards
                    if (not key or row["norm_key"] == key) and (not code or row["norm_code"] == code)]
        if len(pointers) != 1:
            missing = self._missing("read_norm_card", "exact pointer must identify one previously shown norm card",
                                    status="conflict" if pointers or (key and code) else "missing")
            options = [dict(row) for row in self._shown_norm_navigation
                       if code and row["norm_code"].startswith(code + "-")
                       and (not key or row["norm_key"] == key)]
            if options:
                missing.payload["trace"]["previously_shown_exact_options"] = options
            return missing
        return await self._read_norm_pointer(pointers[0], args)

    async def _read_norm_pointer(self, pointer, args, *, verify_source=False) -> ModelResearchToolResult:
        reader = self._norm_card_reader
        if reader is None:
            from proxy.smeta_core.norm_browser import read_norm_card_exact
            reader = read_norm_card_exact
        result = await asyncio.to_thread(reader, norm_key=pointer["norm_key"], norm_code=pointer["norm_code"])
        card = result.get("card")
        if result.get("status") != "ok" or not isinstance(card, Mapping):
            payload = dict(result)
            payload.update({"tool": "read_norm_card", "decision_required_from_model": True})
            return ModelResearchToolResult(payload=payload)
        if str(card.get("norm_code") or "") != pointer["norm_code"] or (
            pointer["norm_key"] and str(card.get("norm_key") or "") != pointer["norm_key"]
        ):
            return self._missing("read_norm_card", "reader returned a different norm pointer", status="conflict")
        if verify_source and any(card.get(name) != pointer[name] for name in (
            "norm_key", "norm_code", "source_ref", "source_sha256", "edition", "base_type",
        ) if name in pointer):
            return self._missing("read_norm_card", "reader returned a different immutable norm pointer", status="conflict")
        card = {**card, "nr_sp_candidates": nr_sp_service.model_candidates(code=pointer["norm_code"])}
        content = _full_norm_card_content(card)
        card_meta = {
            **{name: card[name] for name in ("norm_key", "norm_code", "source_ref", "source_sha256", "edition", "base_type",
                 "work_steps", "measure_unit", "resource_count", "resources_returned", "resources_complete",
                 "resource_consumption_known", "resources", "nr_sp_candidates") if name in card},
            "exact_card_read": True, "minimum_evidence_body_chars": len(content),
            "body_status": "full", "card_body_shown": True,
        }
        from proxy.services.model_resource_reference_service import resource_slot_records
        card_meta["resources"] = resource_slot_records(card)
        card_meta["normative_card_identity"] = normative_card_identity(card_meta)
        card_meta.update(card_delivery_facts(card_meta, raw_body_shown=True))
        chunk = _SmetaNormChunk(content=content, doc_name="smeta_norm_cards.v1", score=1.0, meta=card_meta)
        return ModelResearchToolResult(payload={
            "schema": "les_tool_result_v1", "tool": "read_norm_card", "operation": "typed_exact_norm_read",
            "status": "ok", "inputs": [dict(args)], "result": {"card": card, "hits": [_chunk_payload(chunk)], "count": 1},
            "sources": [{"source_ref": card.get("source_ref") or "", "norm_key": pointer["norm_key"]}],
            "missing": list(result.get("missing") or []), "warnings": list(result.get("warnings") or []),
            "trace": {"previously_shown_pointer": pointer}, "decision_required_from_model": True,
        }, chunks=(chunk,))

    def _read_attachment_source(self, args: Mapping[str, Any]) -> ModelResearchToolResult:
        """Read literal catalog bytes already bound by the application; never open a file."""
        if set(args) != {"source_row"}:
            return self._missing("read_source", "source_row cannot be mixed with any other selector", status="conflict")
        locator = args["source_row"]
        if not isinstance(locator, str) or not locator.strip():
            return self._missing("read_source", "source_row must be a nonempty exact catalog locator")
        catalog = self._attachment_catalog
        expected_sha = self._expected_attachment_sha256
        if not isinstance(catalog, AttachmentSourceCatalog):
            return self._missing("read_source", "no current application-bound attachment catalog")
        if (not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha)
                or catalog.source_file_sha256 != expected_sha or not catalog.source_file_id):
            return self._missing("read_source", "attachment catalog does not match the application's expected source hash",
                                 status="conflict")
        row = catalog.lookup(locator)
        if row is None:
            return self._missing("read_source", "source_row is absent from the current attachment catalog")
        content = row.line
        facts = {"source_row": row.locator, "source_locator": row.locator,
                 "source_file_id": catalog.source_file_id, "source_sha256": expected_sha,
                 "source_ref": f"{catalog.source_file_id}#{row.locator}",
                 "body_complete": True, "source_extraction_complete": catalog.extraction_complete}
        if row.source_start is not None and row.source_end is not None:
            facts.update(source_start=row.source_start, source_end=row.source_end,
                         source_order_basis=catalog_source_order_basis((row,)))
        chunk = _SmetaNormChunk(content=content, doc_name=catalog.original_name, score=1.0, meta={
            **facts, "doc_id": catalog.source_file_id, "source_read": True, "attachment_source_read": True,
            "content_complete": True, "body_status": "full", "minimum_evidence_body_chars": len(content),
        })
        return ModelResearchToolResult(payload={
            "schema": "les_tool_result_v1", "tool": "read_source", "operation": "typed_attachment_source_read",
            "status": "ok", "inputs": [dict(args)],
            "result": {"hits": [_chunk_payload(chunk)], "count": 1, **facts},
            "sources": [facts], "missing": [], "warnings": list(catalog.extraction_warnings),
            "trace": facts, "decision_required_from_model": True,
        }, chunks=(chunk,))

    async def _read_source(self, args: Mapping[str, Any]) -> ModelResearchToolResult:
        for field in ("doc_id", "dataset_id", "doc_name", "q"):
            if field in args and not isinstance(args[field], str):
                return self._missing("read_source", f"{field} must be a string")
        doc_id = str(args.get("doc_id") or "").strip()
        dataset = str(args.get("dataset_id") or "").strip()
        name = str(args.get("doc_name") or "").strip()
        if doc_id:
            shown = self._shown_documents.get(doc_id)
            if shown is None or (dataset and dataset != shown[0]) or (
                name and self._document_name(name) != self._document_name(shown[1])
            ):
                return self._missing("read_source", "doc_id must identify a shown document in selected scope", status="conflict")
            dataset, name = shown
        elif dataset not in self._dataset_ids or not name:
            return self._missing("read_source", "selected dataset_id and doc_name are required", status="conflict")
        if not self._document_allowed(name):
            return self._missing("read_source", "document is outside explicit selected document filter", status="conflict")
        scoped_args = {**args, "dataset_id": dataset, "doc_name": name}
        payload = await asyncio.to_thread(self._fallback, "read_source", scoped_args)
        if inspect.isawaitable(payload):
            payload = await payload
        result = payload.get("result") or {}
        rows = (result.get("hits") or result.get("chunks") or []) if isinstance(result, Mapping) else []
        chunks = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            meta = dict(row.get("meta") or {})
            row_dataset = str(row.get("dataset_id") or meta.get("dataset_id") or dataset)
            row_doc = str(row.get("doc_id") or meta.get("doc_id") or doc_id)
            row_name = str(row.get("doc_name") or meta.get("doc_name") or name)
            if (row_dataset != dataset or (doc_id and row_doc != doc_id)
                    or self._document_name(row_name) != self._document_name(name)
                    or not self._document_allowed(row_name)):
                return self._missing("read_source", "reader returned evidence outside selected document scope", status="conflict")
            content = str(row.get("content") or row.get("text") or "")
            if not content:
                continue
            meta.update({"dataset_id": dataset, "doc_id": row_doc, "source_read": True,
                         "minimum_evidence_body_chars": len(content), "content_complete": row.get("content_complete")})
            for field in ("chunk_id", "page", "source_ref"):
                if row.get(field) is not None:
                    meta[field] = row[field]
            chunks.append(_SmetaNormChunk(content=content, doc_name=str(row.get("doc_name") or name),
                                         score=float(row.get("score") or 1.0), meta=meta))
        return ModelResearchToolResult(payload=payload, chunks=tuple(chunks))

    @property
    def cache_contract(self) -> str:
        # The old dedicated reader expanded source labels through a vocabulary.
        # Such cached hits (including empty results) must never mask a literal search.
        return "smeta_literal_query_v1" if self._smeta_norm_retrieve is not None else "shared_native_query_v1"

    async def execute(self, call: Mapping[str, Any]) -> ModelResearchToolResult:
        if not isinstance(call, Mapping) or not isinstance(call.get("args", {}), Mapping):
            return self._missing("", "tool call and args must be objects")
        tool = str(call.get("tool") or "")
        args = dict(call.get("args") or {})
        if tool == "read_source" and "source_row" in args:
            result = self._read_attachment_source(args)
            if result.payload["status"] != "ok" and set(args) == {"source_row"}:
                pointers = [row for row in self._shown_norm_refs if row["evidence_ref"] == args["source_row"]]
                if len(pointers) == 1:
                    result.payload["trace"]["previously_shown_norm_read"] = {
                        "tool": "read_norm_card", "args": {"evidence_ref": pointers[0]["evidence_ref"]},
                    }
            return result
        if tool == "read_norm_card":
            return await self._read_norm_card(args)
        if tool in {"search_pricebook_resources", "read_resource_price"}:
            from proxy.services.model_pricebook_evidence_service import read_pricebook_evidence
            payload = await asyncio.to_thread(read_pricebook_evidence, tool, args,
                price_basis=self._price_basis, pricebook_provider=self._pricebook_provider, limit=self._model_evidence_k)
            trace = payload.get("trace") or {}
            source_sha = trace.get("pricebook_sha256")
            if (payload.get("operation") == "typed_pricebook_read" and payload.get("status") in {"ok", "missing"}
                    and isinstance(source_sha, str) and re.fullmatch(r"[0-9a-f]{64}", source_sha)):
                expected_sha = self._price_basis.get("pricebook_sha256")
                if expected_sha and expected_sha != source_sha:
                    return self._missing(tool, "chosen pricebook bytes differ from stored-task source hash", status="conflict")
                self._price_basis = {**self._price_basis, "pricebook_sha256": source_sha}
            chunks = tuple(_SmetaNormChunk(content=hit["content"], doc_name=hit["doc_name"], score=hit["score"], meta=hit["meta"])
                           for hit in payload["result"]["hits"])
            return ModelResearchToolResult(payload=payload, chunks=chunks)
        if tool == "read_source" and self._smeta_norm_retrieve is not None:
            return await self._read_source(args)
        if tool != "search_sources":
            if self._smeta_norm_retrieve is not None:
                return self._missing(tool, "unsupported research action")
            payload = self._fallback(tool, args)
            if inspect.isawaitable(payload):
                payload = await payload
            return ModelResearchToolResult(payload=payload)

        target = args.get("target", "norms")
        if not isinstance(target, str) or target not in {"norms", "documents"}:
            return self._missing(tool, "target must be norms or documents")
        scoped_ids = self._dataset_ids
        if target == "documents":
            if self._document_scope_invalid:
                return self._missing(tool, "selected document filter must be a list of literal names", status="conflict")
            if not scoped_ids:
                return self._missing(tool, "selected document datasets are required")
            if "dataset_ids" in args:
                requested = args["dataset_ids"]
                if not isinstance(requested, (list, tuple)) or not requested or any(
                    not isinstance(item, str) or not item.strip() or item not in scoped_ids for item in requested
                ):
                    return self._missing(tool, "dataset_ids must be selected document datasets", status="conflict")
                scoped_ids = tuple(dict.fromkeys(requested))
        if "q" in args and not isinstance(args["q"], str):
            return self._missing(tool, "q must be a string")
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

        if self._smeta_norm_retrieve is not None and target == "norms":
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
            dataset_ids=list(scoped_ids),
            result_limit=self._model_evidence_k,
            candidate_limit=self._retrieval_candidate_k,
            document_diversity_k=self._document_diversity_k,
            **self._retrieval_kwargs,
        )
        all_chunks = tuple(retrieval.chunks)
        if target == "documents" and any(
            str((getattr(chunk, "meta", {}) or {}).get("dataset_id") or getattr(chunk, "dataset_id", "")) not in scoped_ids
            for chunk in all_chunks
        ):
            return self._missing(tool, "retriever returned evidence outside selected document datasets", status="conflict")
        if target == "documents" and any(
            not self._document_allowed(str(_chunk_payload(chunk).get("doc_name") or "")) for chunk in all_chunks
        ):
            return self._missing(tool, "retriever returned evidence outside explicit selected document filter", status="conflict")
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
            "inputs": [{"q": query, "dataset_ids": list(scoped_ids)}],
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
