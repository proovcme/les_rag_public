"""General evidence/RAG application execution extracted from the HTTP router.

The caller resolves request scope and deterministic tools first. This service owns the
unchanged retrieval -> context/evidence -> model -> sources/trace execution branch.
"""
from __future__ import annotations

from proxy.services.model_output_protocol_service import FINAL_RESEARCH_INSTRUCTION, has_unconsumed_tool_frame

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from backend.runtime_paths import mutable_path
from typing import Any, Callable, Mapping, Sequence

import httpx
from fastapi import HTTPException

from backend.inference.routing import (
    cloud_allowed,
    decide_provider,
    is_cloud_provider,
)
from backend.inference.validator import rules_pre_verdict
from proxy.services.answer_form_service import classify_answer_form
from proxy.services.answer_form_service import apply_response_length
from proxy.services.cad_bim_highlight import extract_highlight, set_highlight
from proxy.services.canonical_route_service import (
    BoundModelChatRunner,
    CanonicalRouteMode,
    canonical_route_trace_payload,
    one_model_decision_from_calls,
    resolve_canonical_route,
)
from proxy.services.attachment_source_catalog_service import (
    AttachmentSourceCatalog,
    catalog_sheet_pack_lines,
    catalog_sheet_packet_facts,
    catalog_sheet_work_locators,
    catalog_work_sheet_names,
    compare_model_row_to_catalog,
    coverage_errors,
    header_bound_unit,
    load_catalog_from_attachment_id,
    locators_missing_from_text,
    sheet_coverage_from_missing,
)
from proxy.services.canonical_promotion_service import resolve_promoted_route
from proxy.services.candidate_acceptance_service import execution_mode_for_candidate_acceptance
from proxy.services.model_connection_contracts import ConnectionLocality, ConnectionRole
from proxy.services.openai_compatible_transport_service import (
    CloudBudgetStop,
    InferenceRequest,
    InferenceResponse,
    ModelTransportError,
)
from proxy.services.context_governor_service import (
    ContextCandidate,
    ContextGovernor,
    ContextKind,
    ContextObject,
    ContextPacket,
    ContextRequiredSectionOverflow,
    ContextRequiredWireOverflow,
    NativeToolCall,
    NativeToolExchange,
    NativeToolReply,
    conservative_token_estimate,
)
from proxy.services.context_expander_service import expand_context_windows
from proxy.services.evidence_packet_service import (
    build_retrieval_evidence_packet,
    render_retrieval_evidence_for_model,
)
from proxy.services.lexical_index_service import retrieval_fingerprint
from proxy.services.notebook_service import dataset_memory_prompt_excerpt
from proxy.services.notebook_study_service import (
    build_notebook_study_pack,
    format_study_artifact,
    is_notebook_study_query,
    prompt_block as notebook_study_prompt_block,
)
from proxy.services.project_summary_service import (
    build_project_summary,
    format_project_inventory_context,
    format_project_inventory_prompt,
)
from proxy.services.prompt_registry_service import build_mode_system_prompt
from proxy.services.chat_profile_service import effective_retrieval_policy
from proxy.services.retrieval_service import required_reranker_policy, retrieve_chat_chunks
from proxy.services.runtime_admission import (
    acquire_generation_slot,
    generation_semaphore,
    generation_slot_timeout_seconds,
)
from proxy.services.saferag_service import (
    build_validation_context,
    concentrate_sources,
    rank_chunks_for_question,
    source_names,
)
from proxy.services.table_query_service import maybe_answer_table_query
from proxy.services.memory_port import get_memory_port
from proxy.services.model_answer_table_service import (
    is_divider_cell,
    opens_as_table,
    table_cells,
    table_line,
)
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from proxy.services.model_result_packet_service import admit_model_result_packet
from proxy.services.model_lsr_result_contract import (
    model_lsr_result_field_instruction, decode_model_artifact_kind,
    decode_model_query_envelope, merge_model_artifact_kind,
)
from proxy.services.model_evidence_read_contract import (
    MODEL_EVIDENCE_READ_INSTRUCTION,
    model_evidence_read_tool_schemas,
    read_result_receipt,
)
from proxy.services.model_evidence_read_service import run_model_evidence_read_turn
from proxy.services.model_rag_grouped_evidence_service import (
    EvidenceCard,
    EvidenceGroup,
    plan_full_group_page,
    normative_card_identity,
    card_delivery_facts,
    compact_read_replay,
    prepare_model_read_replay,
    inventory_pointer,
    native_read_growth_budget,
)
from proxy.services.model_price_provenance_service import price_evidence_check
from proxy.services.packaging_recovery_service import (
    release_memory_for_packaging,
    packaging_recovery_payload,
    workbook_document_from_events,
)
from proxy.services.lsr_result_readiness_service import (
    build_lsr_result_readiness,
    format_lsr_readiness_notice,
)
from proxy.services.lsr_candidate_query_service import (
    candidate_queries_enabled_for_turn,
    candidate_queries_for_packet,
    dropped_ungrounded_queries,
    merge_candidate_queries,
    row_literal_text,
)
from proxy.services.lsr_norm_quality_gate_service import (
    LsrResearchRoundResult,
    aggregate_norms_status,
    build_blind_review_evidence_items,
    ciphers_compatible,
    ciphers_identical,
    invented_source_row,
    lsr_coefficient_instruction,
    lsr_format_retry_instruction,
    lsr_research_query_instruction,
    lsr_research_result_evidence,
    lsr_result_table_instruction,
    lsr_verifier_format_retry_instruction,
    lsr_verifier_instruction,
    looks_like_cipher,
    mark_research_exhausted,
    merge_format_retry_rows,
    merge_quality_gated_rows,
    prepare_selection_row,
    rejected_codes_clause,
    row_is_quality_terminal,
    run_coefficient_review,
    run_lsr_norm_quality_loop,
    verifier_generation_tokens,
)
from proxy.services.llm_transport_profile_service import (
    assistant_delta_text,
    apply_transport_options,
    final_assistant_text,
    FinalTextFilter,
    resolve_connection_execution_profile,
    resolve_transport_execution_profile,
)


_WORKBOOK_TOOL_NAMES = frozenset({"build_lsr_workbook", "build_vor_workbook"})


_VOR_INTENT_TERMS = (
    "вор", "ведомость объ", "ведомость работ", "spec to bor", "spec_to_bor",
)
_LSR_INTENT_TERMS = ("лср", "смет", "локальн")


def workbook_artifact_intent(question: str) -> str:
    """Classify the artifact the operator's own words ask to produce.

    Mixed mentions retain both capabilities: code does not distinguish the
    requested result from an input document or a future purpose.
    """
    q = (question or "").casefold()
    lsr = any(term in q for term in _LSR_INTENT_TERMS)
    vor = any(term in q for term in _VOR_INTENT_TERMS)
    if lsr and not vor:
        return "lsr"
    if vor and not lsr:
        return "vor"
    return "both"


def prioritize_workbook_tools(
    profile_tools: Sequence[str],
    *,
    workbook_phase: bool,
    question: str = "",
) -> list[str]:
    """Keep attachment-bound workbook choices inside a small-model shortlist.

    When the operator explicitly names the target artifact, only that workbook
    tool stays visible for the turn: a ВОР/ведомость request must not be answered
    with a priced ЛСР (materials silently becoming costed works), while a
    ЛСР/смета request is the priced route. This still never executes a tool on the
    model's behalf and never selects a norm; an unspecified request keeps both.
    """
    tools = [str(name) for name in profile_tools if str(name).strip()]
    if not workbook_phase:
        return tools
    hidden = {
        "vor": "build_lsr_workbook",
        "lsr": "build_vor_workbook",
    }.get(workbook_artifact_intent(question))
    if hidden:
        tools = [name for name in tools if name != hidden]
    workbook = [name for name in tools if name in _WORKBOOK_TOOL_NAMES]
    other = [name for name in tools if name not in _WORKBOOK_TOOL_NAMES]
    return workbook + other


def workbook_packaging_tool(
    profile_tools: Sequence[str], question: str, *, task_context: Mapping[str, Any] | None = None,
    model_declaration: Mapping[str, Any] | None = None,
) -> list[str]:
    """Choose the packaging tool for the sheet-pass result by intent.

    The operator's own words decide the artifact, checked before any profile
    list membership: a ВОР/ведомость request is packaged as a row-preserving
    ВОР even when an un-narrowed profile list still contains
    build_lsr_workbook (the sheet-pass and durable-resume routes never run
    prioritize_workbook_tools), while a ЛСР/смета request keeps the priced
    route. An unspecified request defaults to the priced packager only when it
    is available. Returns at most one tool name; never executes a tool and
    never selects a norm.
    """
    tools = set(profile_tools)
    declaration = model_declaration or {}
    if declaration.get("status") in {"conflict", "invalid"}:
        return []
    intent = (str(declaration.get("artifact_kind") or "") if declaration.get("status") == "declared"
              else workbook_artifact_intent(question))
    if intent == "both":
        context = task_context or {}
        if context.get("artifact_kind_status") in {"conflict", "invalid"}:
            return []
        if context.get("model_artifact_kind") in {"vor", "lsr"}:
            intent = context["model_artifact_kind"]
        saved = str(context.get("artifact_intent") or "")
        if intent == "both":
            intent = saved if saved in {"vor", "lsr"} else workbook_artifact_intent(
                str(context.get("original_question") or ""))
    if intent == "vor":
        # The operator named a ВОР: package the row-preserving ВОР even when an
        # un-narrowed profile list still carries build_lsr_workbook (sheet-pass
        # and durable-resume routes). A material line must not silently become a
        # priced монтажная работа.
        return ["build_vor_workbook"] if "build_vor_workbook" in tools else []
    if intent == "lsr":
        return ["build_lsr_workbook"] if "build_lsr_workbook" in tools else []
    return []


def workbook_model_question(question: str, job: Mapping[str, Any] | None) -> str:
    """Keep the original operator task in resumed query and answer model calls.

    The latest message remains authoritative. Saved dimensions come only from
    explicit operator requests, not from model choices or application defaults.
    Packaging/idempotency still use the literal latest message independently.
    """
    current = str(question or "")
    context = (job or {}).get("task_context") or {}
    original = str(context.get("original_question") or "")
    if not original or original == current:
        return current
    effective: dict[str, Any] = {}
    if context.get("artifact_intent") in {"vor", "lsr"}:
        effective["artifact_intent"] = context["artifact_intent"]
    if context.get("model_artifact_kind") in {"vor", "lsr"}:
        effective["model_artifact_kind"] = context["model_artifact_kind"]
    basis = context.get("price_basis")
    if isinstance(basis, Mapping):
        effective["price_basis"] = {key: basis[key] for key in ("region", "quarter", "pricebook", "pricebook_sha256") if basis.get(key)}
    return (
        f"Исходное задание пользователя:\n{original}\n\n"
        f"Текущее сообщение пользователя:\n{current}\n\n"
        "Текущее сообщение и сохранённые явные параметры имеют приоритет при изменении задания. "
        "Обычное продолжение сохраняет исходную задачу. Явные параметры этого же задания: "
        + json.dumps(effective, ensure_ascii=False)
    )


def document_price_basis_arguments(basis: object) -> dict[str, Any]:
    """Preserve the actual immutable book together with explicit price dimensions.

    Explicit request dimensions survive before the first successful packaging,
    including requests for a period whose price book has not been loaded yet.
    """
    if not isinstance(basis, Mapping):
        return {}
    book = str(basis.get("pricebook") or basis.get("actual_book") or "").strip()
    region = str(basis.get("region") or basis.get("actual_region") or basis.get("requested_region") or "").strip()
    quarter = str(basis.get("quarter") or basis.get("actual_quarter") or basis.get("requested_quarter") or "").strip()
    if not (book or region or quarter):
        return {}
    return {
        "pricebook": book,
        "region": region,
        "quarter": quarter,
        "binding": str(basis.get("binding") or "").strip(),
        "revision_id": str(basis.get("revision_id") or "").strip(),
        **({"pricebook_sha256": str(basis["pricebook_sha256"]).strip()} if basis.get("pricebook_sha256") else {}),
    }


def task_document_price_basis(job: object, previous_basis: object = None) -> dict[str, Any]:
    """Fill the first-packaging gap using durable operator request dimensions."""
    basis = document_price_basis_arguments(previous_basis)
    context = job.get("task_context") or {} if isinstance(job, Mapping) else {}
    requested = document_price_basis_arguments(context.get("price_basis"))
    from proxy.services.lsr_workbook_adapter_service import requested_price_basis
    previous_dimensions = requested_price_basis(
        " ".join(str(basis.get(key) or "") for key in ("region", "quarter"))
    )
    requested_dimensions = requested_price_basis(
        " ".join(str(requested.get(key) or "") for key in ("region", "quarter"))
    )
    changed = any(
        requested.get(key)
        and requested_dimensions.get(key, requested[key]) != previous_dimensions.get(key, basis.get(key))
        for key in ("region", "quarter")
    )
    if changed:
        # An old selected book must not override an explicitly changed period.
        basis.pop("pricebook", None)
        basis.pop("binding", None)
        basis.pop("pricebook_sha256", None)
    for key in ("region", "quarter"):
        if requested.get(key):
            if changed or not basis.get(key):
                basis[key] = requested[key]
    if requested.get("pricebook"):
        if requested["pricebook"] != basis.get("pricebook"):
            for key in ("binding", "revision_id", "pricebook_sha256"):
                basis.pop(key, None)
        basis["pricebook"] = requested["pricebook"]
        if requested.get("pricebook_sha256"):
            basis["pricebook_sha256"] = requested["pricebook_sha256"]
    return document_price_basis_arguments(basis)


def workbook_repack_replay_arguments(
    events: Sequence[Mapping[str, Any]], *, tool: str, request_identity: str,
    source_sha256: str, document_price_basis: object, current_arguments: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Replay exact server-owned arguments for an unchanged saved rebuild.

    Learning the selected book and the delivered revision changes provenance,
    not the original request. Explicit dimensions or immutable book pins still
    have to agree with the first calculation. An older event cannot override a
    newer packaging event which has no usable request snapshot.
    """
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        return None
    payload = next((event.get("payload") for event in reversed(events)
                    if isinstance(event, Mapping) and event.get("event_type") == "workbook_packaged"
                    and isinstance(event.get("payload"), Mapping)
                    and event["payload"].get("tool") == tool), None)
    if not isinstance(payload, Mapping) or not payload.get("revision_id"):
        return None
    snapshot = payload.get("repack_request")
    if (not isinstance(snapshot, Mapping) or snapshot.get("schema") != "les.workbook-repack-request.v1"
            or snapshot.get("request_identity") != request_identity
            or snapshot.get("source_sha256") != source_sha256
            or not isinstance(snapshot.get("price_basis"), Mapping)):
        return None
    arguments = snapshot.get("arguments")
    if (not isinstance(arguments, Mapping) or not isinstance(arguments.get("attachment_id"), str)
            or not arguments.get("attachment_id") or not isinstance(arguments.get("question"), str)
            or not isinstance(arguments.get("decisions"), list) or not arguments.get("decisions")):
        return None
    unchanged_fields = (set(arguments) | set(current_arguments)) - {"question", "document_price_basis"}
    if any(arguments.get(key) != current_arguments.get(key) for key in unchanged_fields):
        return None
    if tool == "build_lsr_workbook":
        current = document_price_basis_arguments(document_price_basis)
        applied = document_price_basis_arguments(snapshot["price_basis"])
        if applied.get("pricebook") and not re.fullmatch(r"[0-9a-f]{64}", str(applied.get("pricebook_sha256") or "")):
            return None
        from proxy.services.lsr_workbook_adapter_service import requested_price_basis

        for key in ("pricebook", "pricebook_sha256", "region", "quarter"):
            expected, actual = current.get(key), applied.get(key)
            if key in {"region", "quarter"}:
                expected = requested_price_basis(str(expected or "")).get(key, expected)
                actual = requested_price_basis(str(actual or "")).get(key, actual)
            if expected and expected != actual:
                return None
    # The durable event contains JSON values. Copy them so later bookkeeping
    # cannot alter the saved first request or its accepted model rows.
    return json.loads(json.dumps(dict(arguments), ensure_ascii=False))


def workbook_packaging_args(
    *,
    packaging_tool: str,
    attachment_id: str,
    question: str,
    decisions: Sequence[Mapping[str, Any]],
    operator_overrides: Mapping[str, Any] | None,
    draft: bool = False,
    parent_revision_id: str | None = None,
    document_price_basis: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build contract-valid args for the sheet-pass auto-packaging call.

    Both workbook packagers receive the row-preserving decisions; only the
    priced ЛСР tool consumes operator overlays. The ВОР contract declares
    additionalProperties False without confirmed_data, so sending the overlay
    there fails schema validation (TOOL_SCHEMA_INVALID) and drops the artifact.
    ``draft`` and ``parent_revision_id`` are emitted only when set: an ordinary
    final call keeps the identity it had before durable packaging existed, a
    paused intermediate is explicitly marked, and a terminal repack continues
    the same revision chain.

    ``document_price_basis`` is the same code-owned continuation for the money:
    the region, period and book this document was already priced in, read from
    the durable packaging history rather than from the wording of the new reply
    (§ 4).  Only the priced packager accepts it.
    """
    args: dict[str, Any] = {
        "attachment_id": attachment_id,
        "question": question,
        "decisions": [dict(item) for item in decisions or []],
    }
    if packaging_tool == "build_lsr_workbook":
        args["confirmed_data"] = dict(operator_overrides or {})
        basis = document_price_basis_arguments(document_price_basis)
        if basis:
            args["document_price_basis"] = basis
    if draft:
        args["draft"] = True
    if parent_revision_id:
        args["parent_revision_id"] = str(parent_revision_id)
    return args


# Events that can change the durable decision set a packaged workbook is built
# from.  Terminal bookkeeping is deliberately absent: every pass that re-finishes
# an already complete job appends another ``complete`` event *before* it packages,
# so treating it as a change made a re-open of a finished job write one more copy
# of the same document (live regression on job wrj_2b0fff82, events 38-41).
PACKAGING_DECISION_CHANGE_EVENTS = frozenset({
    "packet_checkpoint",
    "rows_replaced",
    "decision_revision",
    "locators_reopened",
    "operator_overrides",
})


def workbook_packaging_lineage(
    events: Sequence[Mapping[str, Any]],
    *,
    durable_decisions: bool,
    prior_events: Sequence[Mapping[str, Any]] = (),
) -> tuple[dict[str, str], dict[str, str | None]]:
    """Revision lineage for durable workbook packaging.

    ``parents`` is the last revision each packager wrote for this job, so a new
    decision set continues the same downloadable document. ``settled`` marks a
    packager whose last revision is a final one that was written after the last
    event able to change the saved durable decisions: replaying that call with
    the parent it built on (recorded in the event, or read back from the
    packaging chain for events written before the parent was recorded) keeps the
    existing call identity (which already covers ``decisions``), so opening a
    finished job again serves the same file instead of duplicating it.
    """

    # Older jobs supply a parent only. Their independent sequence numbers must
    # never make a new remark replay a settled file from before that remark.
    parents: dict[str, str] = {}
    for event in prior_events:
        if str(event.get("event_type") or "") != "workbook_packaged":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        tool = str(payload.get("tool") or "")
        revision = str(payload.get("revision_id") or "")
        if tool and revision:
            parents[tool] = revision
    settled: dict[str, str | None] = {}
    last_change_sequence = max(
        (
            int(event.get("sequence") or 0)
            for event in events
            if str(event.get("event_type") or "") in PACKAGING_DECISION_CHANGE_EVENTS
        ),
        default=0,
    )
    for event in events:
        if str(event.get("event_type") or "") != "workbook_packaged":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        tool = str(payload.get("tool") or "")
        revision_id = str(payload.get("revision_id") or "")
        if not tool or not revision_id:
            continue
        built_on = parents.get(tool)
        parents[tool] = revision_id
        if (
            durable_decisions
            and not bool(payload.get("draft"))
            and int(event.get("sequence") or 0) >= last_change_sequence
        ):
            settled[tool] = str(payload.get("parent_revision_id") or "") or built_on
    return parents, settled


def workbook_document_price_basis(
    events: Sequence[Mapping[str, Any]],
    *,
    tool: str = "build_lsr_workbook",
) -> dict[str, Any]:
    """The price basis this document was last actually priced in.

    Read from the job's own ``workbook_packaged`` events, so a continuation turn
    inherits the operator's own choice instead of re-deriving it from the text of
    the new reply (§ 4: «реплика "добери нормы" … не обнуляет регион, квартал или
    принятые решения»).  Only a basis that bound a book is carried forward: an
    earlier revision that stayed without a book asked a question, and repeating
    that question is not the same as answering it.

    The book, subject and period are read from the newest revision that bound
    one — that is what the document is priced in now — while ``revision_id``
    names the revision in which that book was *first* chosen, which is what the
    operator actually selected and what the file has to say (§ 7).  Stamping the
    newest revision instead made the inherited record grow on every turn, and
    because the record is part of the packaging call's arguments it changed that
    call's identity too: a replay of a finished job then read as a different
    request and wrote a second copy of the same document (§ 11 № 9).
    """

    newest: dict[str, Any] = {}
    first_for_book: dict[str, str] = {}
    for event in events or ():
        if not isinstance(event, Mapping):
            continue
        if str(event.get("event_type") or event.get("event") or "") != "workbook_packaged":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            payload = event.get("data")
        if not isinstance(payload, Mapping):
            continue
        if tool and str(payload.get("tool") or "") != tool:
            continue
        basis = payload.get("price_basis")
        if not isinstance(basis, Mapping):
            continue
        record = document_price_basis_arguments(
            {**dict(basis), "revision_id": str(payload.get("revision_id") or "")}
        )
        if not record:
            continue
        if record["revision_id"]:
            first_for_book.setdefault(record["pricebook"], record["revision_id"])
        newest = record
    if not newest:
        return {}
    # the revision that *chose* this book, not the newest one that re-priced it:
    # this record is part of the packaging call's arguments, and arguments decide
    # the call's identity, so a replay of a finished job has to send the same one.
    chosen_in = first_for_book.get(newest["pricebook"]) or newest["revision_id"]
    return {**newest, "revision_id": chosen_in}


def document_priced_basis(
    *,
    attachment_id: str,
    source_sha256: str = "",
    tool: str = "build_lsr_workbook",
) -> dict[str, Any]:
    """The basis the *document* was last priced in, wherever that was recorded.

    One rule for every route that packages a revision of an already-priced document
    (§ 10: the routes must not disagree about one document): the basis is read from
    the durable packaging history of the attachment, not from the job this reply
    happens to run.  A continuation opens a new research job — its durable identity
    covers the question — while the document stays one artifact, so a job-scoped read
    returned the estimate to an unchosen basis on the turn right after the one that
    chose it (build 822, live ``B0_camenka``: revision 1 priced in
    ``sankt-peterburg_3kv2026`` under one job, revisions 2..5 reporting «no_book»
    under the next).
    """

    aid = str(attachment_id or "").strip()
    if not aid:
        return {}
    try:
        events = WorkbookResearchJobService().document_packaging_events(
            attachment_id=aid,
            source_sha256=str(source_sha256 or "").strip(),
        )
    except Exception as error:  # noqa: BLE001 - durability degrades visibly
        logger.warning(
            "[WORKBOOK] document basis read across researches failed: %s",
            type(error).__name__,
        )
        return {}
    return workbook_document_price_basis(events, tool=str(tool or ""))


def workbook_research_job_for_document(
    *,
    attachment_id: str,
    source_sha256: str = "",
) -> dict[str, Any]:
    """The durable research job this very attachment was researched in, or ``{}``.

    Read-only on purpose.  A model-authored packaging turn must not create a
    checkpoint it does not own — the sheet pass begins the durable job itself,
    and a half-owned row would offer «Продолжить» on a research that never
    started.  The attachment is the key rather than the session because a UI
    restart regenerates the session id while the document, and the basis it was
    already priced in, stay the same (task 2026-09-28 § 9).  A different source
    hash under the same attachment id means the file was replaced, so nothing is
    inherited from the research of the old one.
    """

    aid = str(attachment_id or "").strip()
    if not aid:
        return {}
    try:
        job = WorkbookResearchJobService().latest(attachment_id=aid)
    except Exception as error:  # noqa: BLE001 - durability degrades visibly
        logger.warning(
            "[WORKBOOK] durable job lookup for a model-packaged revision failed: %s",
            type(error).__name__,
        )
        return {}
    if not isinstance(job, Mapping):
        return {}
    digest = str(source_sha256 or "").strip()
    identity = job.get("identity") if isinstance(job.get("identity"), Mapping) else {}
    if digest and str(identity.get("source_sha256") or "").strip() not in {"", digest}:
        return {}
    return dict(job)


def model_packaging_document_basis(job: Mapping[str, Any] | None) -> dict[str, Any]:
    """The basis a model-authored packaging call has to continue in.

    The model decides *which* tool to run; the document still decides which
    region, period and book its own revisions were priced in (§ 4).  This reads
    the same durable projection the readiness card and the no-model repack use,
    so the three routes cannot drift apart and disagree about the basis of one
    document (§ 10).  An unpriced earlier revision stored nothing, and an
    empty record keeps the question open instead of answering it (§ 7).

    The job that the current reply runs is only the fast path: when it carries no
    priced revision — a continuation always opens a fresh research of the same
    attachment, because the durable job identity covers the question — the basis is
    read from the packaging history of the *document* (`document_priced_basis`).
    Without that second read the fix for the 820 defect only survived inside a
    single research, which is exactly what build 822's live ``B0_camenka`` proved it
    does not.
    """

    if not isinstance(job, Mapping):
        return {}
    document = job.get("document") if isinstance(job.get("document"), Mapping) else {}
    basis = document.get("price_basis")
    if not isinstance(basis, Mapping) or not basis:
        basis = job.get("price_basis")
    record = document_price_basis_arguments(basis)
    if record:
        return task_document_price_basis(job, record)
    identity = job.get("identity") if isinstance(job.get("identity"), Mapping) else {}
    return task_document_price_basis(job, document_priced_basis(
        attachment_id=str(identity.get("attachment_id") or job.get("attachment_id") or ""),
        source_sha256=str(identity.get("source_sha256") or ""),
        tool=str(job.get("packaging_tool") or "build_lsr_workbook"),
    ))


def model_packaging_record_arguments(
    *,
    job: Mapping[str, Any] | None,
    tool: str,
    harvested: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """What the durable packaging event of a model-authored revision says.

    ``{}`` when there is nothing to write: no job, or no revision delivered.
    A route that produced a file but left no ``workbook_packaged`` event is the
    hole this closes — the next continuation then has no basis to inherit and
    the document silently returns to an unchosen price basis (§ 4), and the
    revision chain loses a parent (§ 11 № 9).  ``draft`` follows the job's own
    state: a revision of a research that has not finished is an intermediate
    one, never the finished document.
    """

    if not isinstance(job, Mapping) or not isinstance(harvested, Mapping):
        return {}
    job_id = str(job.get("job_id") or "").strip()
    artifact = (
        harvested.get("artifact")
        if isinstance(harvested.get("artifact"), Mapping)
        else {}
    )
    revision_id = str(artifact.get("revision_id") or "").strip()
    if not job_id or not revision_id:
        return {}
    return {
        "job_id": job_id,
        "tool": str(tool),
        "revision_id": revision_id,
        "draft": str(job.get("status") or "") not in {"complete", "failed"},
        # the parent the packager actually built on, not a guessed one
        "parent_revision_id": str(artifact.get("parent_revision_id") or ""),
        "price_basis": harvested.get("price_basis"),
    }


def workbook_chat_review_needed(question, job, events=()) -> bool:
    """Only a plain resume can reuse a finished document without hearing the remark."""
    if not isinstance(job, Mapping) or not job.get("continues_job_id") or not job.get("accepted_rows"):
        return False
    text = str(question or "").strip().rstrip(".! ").casefold()
    original = str((job.get("task_context") or {}).get("original_question") or "").strip().rstrip(".! ").casefold()
    digest = hashlib.sha256(str(question).encode("utf-8")).hexdigest()
    parent_digests = [
        str((event.get("payload") or {}).get("parent_question_sha256") or "")
        for event in events if isinstance(event, Mapping)
        and (event.get("payload") or {}).get("parent_question_sha256")
    ]
    same_question = digest == parent_digests[-1] if parent_digests else text == original
    if not text or same_question or text in {
        "продолжи", "продолжить", "continue",
        "продолжи это же задание по тому же прикреплённому документу",
    }:
        return False
    return not any(
        (event.get("payload") or {}).get("chat_review", {}).get("request_sha256") == digest
        for event in events if isinstance(event, Mapping)
    )


def begin_workbook_chat_review(service, job, question, source_locators):
    """Offer the original document again without a planning gate before RAG.

    The application schedules every source row, not a guessed professional
    subset. The same model receives the remark and its previous decisions in
    the normal query/result calls and owns every retained or revised choice.
    """
    note = {
        "request_sha256": hashlib.sha256(str(question).encode("utf-8")).hexdigest(),
        "message": str(question), "decision_author": "user", "review_scope": "document",
    }
    prior_rows = None
    if job.get("remaining") or job.get("held_packet"):
        context = workbook_chat_review_context(service, job)
        if context:
            prior_rows = model_rag_existing_operation_rows(
                job.get("accepted_rows") or (), context["prior_rows"])
    return service.reopen_locators(job["job_id"], list(source_locators), chat_review=note,
                                   review_prior_rows=prior_rows)


def workbook_chat_review_context(service, job) -> dict[str, Any]:
    """Read the latest user's review and its baseline across resume jobs."""
    return service.chat_review_context(job["job_id"])


def model_rag_existing_operation_rows(current_rows, review_rows=()) -> list[dict[str, Any]]:
    """Known identities for context/validation; never restore accepted decisions.

    A newer accepted revision wins over its review baseline. Rows without an
    identity remain distinct; their contents are not guessed or reconciled.
    """
    rows: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    for row in (*review_rows, *current_rows):
        identity = str(row.get("operation_id") or "")
        if identity and identity in positions:
            rows[positions[identity]] = dict(row)
        else:
            if identity:
                positions[identity] = len(rows)
            rows.append(dict(row))
    return rows


def terminal_research_packaging_rows(
    research_job: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return the durable accepted decisions of a completed research job.

    A terminal job's saved set is authoritative: the final workbook revision
    must be packaged from the full saved decisions even when the per-call
    re-validation of the answer reports integrity noise. The decisions are
    forwarded unchanged; no model call happens here. Returns nothing for a
    paused/running job or when durability is unavailable, so an intermediate
    file can never masquerade as the finished document.
    """
    if not isinstance(research_job, Mapping):
        return []
    if str(research_job.get("status") or "") != "complete":
        return []
    return [
        dict(item)
        for item in (research_job.get("accepted_rows") or ())
        if isinstance(item, Mapping)
    ]


def workbook_document_issues(
    research_job: Mapping[str, Any] | None,
    *,
    errors: Sequence[str] = (),
    transport_diagnostics: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Server-owned document gaps, separate from every model-authored decision."""
    job = research_job if isinstance(research_job, Mapping) else {}
    issues: list[dict[str, Any]] = []
    remaining = list(job.get("remaining") or ())
    if job and (str(job.get("status") or "") != "complete" or remaining):
        issues.append({"code": "WORKBOOK_RESEARCH_INCOMPLETE",
                       "reason": ("Промежуточная ревизия: исходные строки ещё не закрыты." if remaining
                                  else "Промежуточная ревизия: исследование ещё не завершено."),
                       "job_status": str(job.get("status") or ""),
                       "remaining_locators": remaining})
    for error in errors:
        issues.append({"code": str(error), "reason": str(error)})
    for proposal in (job.get("unapplied_proposals") or ()) if str(job.get("status") or "") != "complete" else ():
        if isinstance(proposal, Mapping):
            issues.append({"code": "MODEL_PROPOSAL_UNAPPLIED",
                           "reason": "Неприменённое предложение сохранено без исправления ячеек.",
                           "proposal": dict(proposal)})
    for diagnostic in transport_diagnostics:
        if isinstance(diagnostic, Mapping):
            issues.append({"code": str(diagnostic.get("code") or "MODEL_RESULT_TRANSPORT_ERROR"),
                           "reason": "Техническая ошибка таблицы; строка не включена в расчёт.",
                           "diagnostic": dict(diagnostic)})
    held = job.get("held_packet") or {}
    if str(job.get("status") or "") != "complete" and isinstance(held, Mapping) and held.get("read_stop"):
        issues.append({"code": "MODEL_EVIDENCE_READ_STOP",
                       "reason": str(held["read_stop"])})
    return issues


def model_answer_timeout_seconds() -> float:
    """One end-to-end window for an explicitly assigned answer connection.

    Mirrors model_connection_timeout() in routers/chat.py and the registered
    LES_MODEL_CONNECTION_TIMEOUT_SEC runtime-config knob. The agent-loop client
    previously hardcoded 300s, so a remote-model latency spike aborted a live
    workbook pass with ReadTimeout/502 and the operator setting changed nothing.
    """
    try:
        return max(1.0, float(os.getenv("LES_MODEL_CONNECTION_TIMEOUT_SEC", "300")))
    except (TypeError, ValueError):
        return 300.0



def native_research_call_batch(
    response: InferenceResponse | None,
    executed_calls: Sequence[Mapping[str, Any]],
    previous_exchanges: Sequence[NativeToolExchange] = (),
) -> tuple[NativeToolCall, ...]:
    """Retain the provider's literal calls, separately from bound execution args."""
    raw_calls = response.tool_calls if response is not None else ()
    if not raw_calls:
        return ()
    if len(raw_calls) != len(executed_calls):
        raise ValueError("native research batch must execute every provider call")
    seen_ids = {call.call_id for exchange in previous_exchanges for call in exchange.calls}
    calls = []
    for raw, executed in zip(raw_calls, executed_calls, strict=True):
        function = raw.get("function") or {}
        arguments = function.get("arguments")
        if isinstance(arguments, Mapping):
            arguments = json.dumps(dict(arguments), ensure_ascii=False, separators=(",", ":"))
        call = NativeToolCall(raw.get("id"), function.get("name"), arguments)
        if call.call_id in seen_ids:
            raise ValueError("native research history has duplicate provider IDs")
        if call.call_id != executed.get("call_id") or call.name != executed.get("tool"):
            raise ValueError("native research execution belongs to another call")
        executed_args = executed.get("args") or {}
        if any(executed_args.get(key) != value for key, value in json.loads(call.arguments).items()):
            raise ValueError("native research execution changes provider arguments")
        seen_ids.add(call.call_id)
        calls.append(call)
    return tuple(calls)


def native_research_exchange(
    calls: Sequence[NativeToolCall], payloads: Sequence[Mapping[str, Any]], *, assistant_content: str,
    reasoning_content: str | None = None,
) -> NativeToolExchange:
    """Replay whole safe result objects in matching tool roles, without body copies."""
    if len(calls) != len(payloads):
        raise ValueError("native research batch needs exactly one result per call")
    return NativeToolExchange(
        calls=tuple(calls),
        replies=tuple(NativeToolReply(call.call_id, call.name, json.dumps(
            dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
        )) for call, payload in zip(calls, payloads, strict=True)),
        assistant_content=assistant_content,
        reasoning_content=reasoning_content,
    )


def tool_selector_request_payload(
    *,
    question: str,
    mode: str,
    dataset_ids: Sequence[str],
    target_file_ref: dict[str, Any] | None,
    round_no: int,
    attachment_id: str | None,
) -> dict[str, Any]:
    """Describe the exact operator-bound inputs required for model tool choice."""
    payload: dict[str, Any] = {
        "question": question,
        "mode": mode,
        "dataset_ids": list(dataset_ids),
        "target_file": target_file_ref if target_file_ref else {},
        "round": round_no,
    }
    bound_attachment = str(attachment_id or "").strip()
    if bound_attachment:
        payload["attachment"] = {
            "bound": True,
            "attachment_id": bound_attachment,
        }
    return payload
from proxy.services.model_execution_preset_service import (
    ModelExecutionPreset, apply_output_budget_policy, apply_reasoning_policy,
    model_rag_answer_execution_preset, model_rag_query_execution_preset, query_generation_budget,
)
from proxy.services.model_research_tool_service import (
    MATCHED_BEFORE_CAP_META_KEY as _MATCHED_BEFORE_CAP_META_KEY,
    ModelResearchToolService,
    retrieve_smeta_norm_cards,
)
from proxy.services.source_locator_service import evidence_counts, source_map_item
from proxy.services.chat_evidence_manifest_service import build_evidence_manifest
from proxy.services.chat_capability_scope_service import filter_profile_tools
from proxy.services.typed_memory_projection_service import (
    MemoryLimits,
    project_memory,
    resolve_session_memory_scope,
)
from proxy.services.web_research_config_service import (
    WebResearchConfig,
    capture_web_research_config,
    public_web_research_config,
)

logger = logging.getLogger(__name__)

_DOCUMENT_EVIDENCE_TOOLS = frozenset({
    "dataset_map",
    "search_sources",
    "read_source",
    "read_pdf_source",
    "look_at_pdf_page",
    "read_excel_source",
    "search_project_tables",
    "read_project_table",
    "assemble_project_volume",
})


@dataclass(frozen=True)
class _WebToolSourceChunk:
    content: str
    doc_name: str
    score: float
    meta: dict[str, Any]


def web_tools_for_request(
    tools: Sequence[str], config: WebResearchConfig
) -> list[str]:
    """Expose page reading only for the explicitly captured extended mode."""

    normalized = [str(name) for name in tools if str(name).strip()]
    if config.mode == "extended":
        return normalized
    return [name for name in normalized if name != "web_read"]


def web_source_map_from_tool_results(
    tool_results: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Project actual web evidence into locators without changing its content."""

    chunks_by_url: dict[str, _WebToolSourceChunk] = {}
    for payload in tool_results:
        tool = str(payload.get("tool") or "")
        if tool not in {"web_search", "web_read"}:
            continue
        result = payload.get("result")
        result_data = dict(result) if isinstance(result, Mapping) else {}
        search_rows = result_data.get("results")
        rows = search_rows if isinstance(search_rows, list) else []
        rows_by_url = {
            str(row.get("url") or ""): row
            for row in rows
            if isinstance(row, Mapping) and str(row.get("url") or "")
        }
        for raw_source in payload.get("sources") or []:
            if not isinstance(raw_source, Mapping):
                continue
            url = str(raw_source.get("url") or result_data.get("final_url") or "").strip()
            if not url:
                continue
            row = rows_by_url.get(url, {})
            title = str(
                raw_source.get("title")
                or result_data.get("title")
                or (row.get("title") if isinstance(row, Mapping) else "")
                or ""
            )
            content = str(
                result_data.get("text")
                or (row.get("snippet") if isinstance(row, Mapping) else "")
                or ""
            )
            chunks_by_url[url] = _WebToolSourceChunk(
                content=content,
                doc_name=title,
                score=0.0,
                meta={
                    "url": url,
                    "title": title,
                    "provider": str(result_data.get("provider") or ""),
                    "retrieved_at": str(result_data.get("retrieved_at") or ""),
                },
            )
    return [
        source_map_item(chunk, index=index)
        for index, chunk in enumerate(chunks_by_url.values(), 1)
    ]


def _merge_web_source_map(
    source_map: Sequence[dict[str, Any]],
    tool_results: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    web_sources = web_source_map_from_tool_results(tool_results)
    if not web_sources:
        return list(source_map)
    combined_sources = [
        dict(item)
        for item in source_map
        if str(((item.get("locator") or {}).get("kind") or "")) != "web_result"
    ]
    combined_sources.extend(web_sources)
    for source_index, item in enumerate(combined_sources, 1):
        item["index"] = source_index
        item["label"] = f"Источник {source_index}"
    return combined_sources


def tools_for_document_scope(tools: Sequence[str], *, enabled: bool) -> list[str]:
    """Remove indexed-document tools when the user selected no document scope."""
    normalized = [str(name) for name in tools if str(name).strip()]
    if enabled:
        return normalized
    return [name for name in normalized if name not in _DOCUMENT_EVIDENCE_TOOLS]


def native_model_tool_schemas(
    tool_contracts: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert registry contracts to provider-native function definitions."""

    schemas: list[dict[str, Any]] = []
    for contract in tool_contracts:
        name = str(contract.get("name") or "").strip()
        parameters = contract.get("input_schema")
        if not name or not isinstance(parameters, dict):
            continue
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(contract.get("summary") or name),
                    "parameters": parameters,
                },
            }
        )
    return schemas


@dataclass(frozen=True)
class _SkippedRetrievalQuality:
    status: str = "skipped"
    top_score: float = 0.0


@dataclass(frozen=True)
class _SkippedRetrievalTrace:
    status: str = "skipped"
    error_code: str = ""


@dataclass(frozen=True)
class _SkippedDocumentRetrieval:
    chunks: tuple[Any, ...] = ()
    trace: _SkippedRetrievalTrace = _SkippedRetrievalTrace()
    quality: _SkippedRetrievalQuality = _SkippedRetrievalQuality()

    def payload(self) -> dict[str, Any]:
        return {
            "schema": "retrieval_trace_v1",
            "status": "skipped",
            "reason": "scope_none",
            "quality": {"status": "skipped", "top_score": 0.0},
        }


def safe_selected_call_trace(call: dict[str, Any]) -> dict[str, str]:
    """Expose a call's shape without retaining model-supplied argument text."""
    arguments = call.get("args") if isinstance(call.get("args"), dict) else {}
    encoded_arguments = json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    trace = {
        "tool": str(call.get("tool") or ""),
        "arguments_sha256": hashlib.sha256(encoded_arguments).hexdigest(),
    }
    if call.get("call_id"):
        trace["call_id"] = str(call["call_id"])
    return trace


def _safe_workbook_filename(value: Any) -> str:
    """Keep one operator-facing xlsx basename and never expose a local path."""

    raw = str(value or "").strip().replace("\\", "/")
    name = Path(raw).name
    if not name or name != raw or ".." in name:
        return ""
    if not name.lower().endswith(".xlsx") or name.lower() in {".xlsx", "artifact.xlsx"}:
        return ""
    return name


def _chat_workbook_filename(
    filename: Any,
    *,
    artifact_kind: str = "",
    tool: str = "",
) -> str:
    """Return a safe download name without changing workbook contents."""

    safe = _safe_workbook_filename(filename)
    if safe:
        return safe
    kind = str(artifact_kind or "").strip()
    if kind not in {"lsr_workbook", "vor_workbook"}:
        kind = "vor_workbook" if tool == "build_vor_workbook" else "lsr_workbook"
    from proxy.services.workbook_tool_service import workbook_download_filename

    return workbook_download_filename(artifact_kind=kind)


#: ADR-16 § 7: the price basis the calculation actually used, the per-resource
#: price holes and the reversed-action rows are questions the operator has to be
#: able to answer.  They travel from the workbook tool result into chat history,
#: the readiness block and the GUI, so they are copied whole — but bounded,
#: because the same projection is what the model gets back as the tool result.
_HISTORY_BASIS_TEXT_LIMIT = 2000
_HISTORY_BASIS_GAP_TEXT_LIMIT = 400
_HISTORY_BASIS_ITEMS = 40
#: One projected operation carries identity, the seven readiness answers and its own
#: open reasons; none of that needs basis-length prose (§ 4).
_HISTORY_ROW_TEXT_LIMIT = 200


def _bounded_history_value(
    value: Any,
    *,
    text_limit: int = _HISTORY_BASIS_TEXT_LIMIT,
    depth: int = 0,
) -> Any:
    """Copy one tool field into chat history without letting it grow unbounded."""

    if isinstance(value, Mapping):
        if depth >= 3:
            return {}
        return {
            str(key)[:64]: _bounded_history_value(
                item, text_limit=text_limit, depth=depth + 1
            )
            for key, item in list(value.items())[:40]
        }
    if isinstance(value, (list, tuple, set)):
        if depth >= 3:
            return []
        return [
            _bounded_history_value(item, text_limit=text_limit, depth=depth + 1)
            for item in list(value)[:_HISTORY_BASIS_ITEMS]
        ]
    if isinstance(value, bool) or isinstance(value, (int, float)) or value is None:
        return value
    return str(value)[:text_limit]


#: § 4: the fields of one projected operation the chat layer has to keep.  Identity
#: (locator / stable operation id), the answers to the seven questions and the reason
#: tags that explain a «нет» are what the readiness card and the delivered file quote;
#: the free-text binding message and the norm code are already visible elsewhere, so
#: they are not copied into every turn's tool observation.
_HISTORY_ROW_FIELDS = (
    "locator", "work_id", "operation_id", "row_role", "status",
    # § 4: identity also carries the position number the document prints and the
    # links between operations built on one source row — small scalars, kept so a
    # later turn can point at the same line of the same file.
    "position_no", "locator_operations", "parent_locator", "covered_by_work_id",
    "source_accounted", "operation_defined", "norm_selected",
    "applicability_substantiated", "structure_calculated",
    "known_amount_present", "position_calculated", "volume_verified",
    "prices_provided", "open_reasons",
    # § 4: an operator-confirmed price travels with the line that states which unit it
    # was multiplied by, so a later turn can correct the unit instead of re-asking.
    "price_note",
)


def _bounded_row_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    """Copy one projected operation whole in identity, bounded in bulk."""

    return {
        key: _bounded_history_value(row.get(key), text_limit=_HISTORY_ROW_TEXT_LIMIT)
        for key in _HISTORY_ROW_FIELDS
        if key in row
    }


def safe_workbook_history_projection(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Retain only workbook identifiers that the chat UI can safely use."""
    result = payload if isinstance(payload, dict) else {}
    if result.get("schema") != "les.workbook_tool_result.v1":
        return {}

    def selected(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
        source = value if isinstance(value, dict) else {}
        return {field: source[field] for field in fields if field in source}

    safe = selected(
        result,
        (
            "schema", "tool", "status", "code", "pricing_status", "norms_status",
            "calculated_positions", "confirmed_amount", "preliminary_amount",
            # § 4: «сколько позиций построено» and «сколько из них полностью
            # рассчитано» are two different numbers and must not be conflated here.
            "positions_built",
            "document_issues",
            "error_type", "memory_pressure",
        ),
    )
    if safe.get("status") in {"complete", "partial"}:
        for field in ("missing", "blockers"):
            values = result.get(field)
            safe[field] = [str(value)[:500] for value in values[:100]] if isinstance(values, list) else []
        if safe.get("status") == "complete" and (safe["missing"] or safe["blockers"]):
            safe["status"] = "partial"
        source_errors = result.get("vor_source_errors")
        if isinstance(source_errors, list):
            # Preserve every affected source address; bounding each message must
            # not erase the tail of a large VOR or turn it into a complete file.
            safe["vor_source_errors"] = [item[:500] for item in source_errors if isinstance(item, str) and item]
            if safe["vor_source_errors"]:
                safe["status"] = "partial"
        # The basis and the concrete price / operation questions are not extras of
        # the file: without them a draft asks for nothing, and «Выберите регион и
        # уровень цен» could never appear on this route (ADR-16 § 7, task § 7).
        basis = result.get("price_basis")
        if isinstance(basis, Mapping) and basis:
            safe["price_basis"] = _bounded_history_value(basis)
        for field in ("price_gaps", "norm_conflicts"):
            values = result.get(field)
            if not isinstance(values, list) or not values:
                continue
            safe[field] = [
                _bounded_history_value(item, text_limit=_HISTORY_BASIS_GAP_TEXT_LIMIT)
                for item in values[:_HISTORY_BASIS_ITEMS]
                if isinstance(item, Mapping)
            ]
        # Task 2026-09-29 § 4: the readiness counters and the «Проверка» sheet read one
        # per-operation projection, so it survives the history bound *in full*.  A capped
        # row list would silently change «сколько работ рассчитано», the very number this
        # task forbids deriving by subtraction.  What is bounded instead is each row's own
        # bulk — identity, the seven answers, a few reason tags — because this projection
        # also travels back as the tool observation, and a 300-row document must not crowd
        # out the rows it describes (§ 2).
        projection = result.get("row_projection")
        if isinstance(projection, list) and projection:
            safe["row_projection"] = [
                _bounded_row_projection(row) for row in projection if isinstance(row, Mapping)
            ]
    artifact = selected(
        result.get("artifact"),
        (
            "artifact_id", "revision_id", "revision_no", "parent_revision_id",
            "sha256", "byte_size", "download_url", "source_scope",
            "decision_checkpoint_id", "filename", "artifact_kind",
            "draft",
        ),
    )
    checkpoint = selected(
        result.get("checkpoint"),
        ("checkpoint_id", "phase", "status", "completed_items", "total_items", "resumed"),
    )
    source = selected(result.get("source"), ("attachment_id", "sha256", "rows"))
    if artifact:
        filename = _safe_workbook_filename(artifact.get("filename"))
        if filename:
            artifact["filename"] = filename
        else:
            artifact.pop("filename", None)
        kind = str(artifact.get("artifact_kind") or "").strip()
        if kind in {"lsr_workbook", "vor_workbook"}:
            artifact["artifact_kind"] = kind
        else:
            artifact.pop("artifact_kind", None)
        safe["artifact"] = artifact
    if checkpoint:
        safe["checkpoint"] = checkpoint
    if source:
        safe["source"] = source
    return safe


def harvest_workbook_tool_result(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Project one completed workbook tool result into chat/history metadata."""
    result = safe_workbook_history_projection(payload)
    if (
        result.get("schema") != "les.workbook_tool_result.v1"
        or result.get("status") not in {"complete", "partial"}
    ):
        return {}
    artifact = result.get("artifact") if isinstance(result.get("artifact"), dict) else {}
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    checkpoint = (
        result.get("checkpoint") if isinstance(result.get("checkpoint"), dict) else {}
    )
    attachment_id = str(source.get("attachment_id") or "").strip()
    checkpoint_id = str(checkpoint.get("checkpoint_id") or "").strip()
    source_scope = artifact.get("source_scope")
    if not isinstance(source_scope, (list, tuple, set)):
        return {}
    if (
        not artifact.get("revision_id")
        or not attachment_id
        or not checkpoint_id
        or str(checkpoint.get("status") or "") != "complete"
        or str(artifact.get("decision_checkpoint_id") or "") != checkpoint_id
        or f"attachment:{attachment_id}" not in source_scope
    ):
        return {}
    return {
        "artifact": dict(artifact),
        "source": {
            key: source[key]
            for key in ("attachment_id", "sha256")
            if key in source
        },
        "attachment_retry": {
            "attachment_id": attachment_id,
            "id": attachment_id,
            "preserved": True,
            "checkpoint_id": str(checkpoint.get("checkpoint_id") or ""),
        },
        "checkpoint": dict(checkpoint),
        "workbook_status": str(result.get("status") or ""),
        "pricing_status": str(result.get("pricing_status") or ""),
        "document_issues": list(result.get("document_issues") or []),
        "norms_status": str(result.get("norms_status") or ""),
        "missing": list(result.get("missing") or []),
        "price_gaps": list(result.get("price_gaps") or []),
        "price_basis": dict(result.get("price_basis") or {}),
        # rows the calculation itself flags as naming the opposite operation:
        # readiness turns each into one concrete question (task § 11 №8)
        "norm_conflicts": list(result.get("norm_conflicts") or []),
        "vor_source_errors": list(result.get("vor_source_errors") or []),
        # § 4: one revision projection, unchanged in row count, is what the readiness
        # counters and the «Проверка» sheet both read.
        "row_projection": list(result.get("row_projection") or []),
        "blockers": list(result.get("blockers") or []),
    }


#: A memory-pressure packaging failure is worth one extra relief-and-retry
#: attempt; other failures repeat the identical deterministic call.
_PACKAGING_MEMORY_ATTEMPTS = 3


def _turn_document_state(
    *,
    research_job_service: Any,
    research_job: Mapping[str, Any] | None,
    job_status: str,
    workbook_files: Sequence[Mapping[str, Any]],
) -> str:
    """Durable file state of this research, or "" when nothing is claimable.

    Only a terminal job can promise a finished document, so an open job keeps
    the pre-existing in-memory wording.  For a completed job the durable
    ``workbook_packaged`` events answer the question — which is what stops a
    draft, or a packaging that died of ``MemoryError``, from being reported as
    "файл собран" while the client has nothing to download.
    """

    status = str((research_job or {}).get("status") or job_status or "").strip()
    if status != "complete":
        return ""
    job_id = str((research_job or {}).get("job_id") or "").strip()
    if research_job_service is not None and job_id:
        try:
            events = research_job_service.list_events(job_id, "workbook_packaged")
        except Exception:  # noqa: BLE001 - fall back to this turn's own result
            events = []
        else:
            return str(
                workbook_document_from_events(events, status=status).get("state") or ""
            )
    files = [dict(item) for item in workbook_files or () if isinstance(item, Mapping)]
    if not files:
        return "pending"
    if any(not bool(item.get("draft")) for item in files):
        return "ready"
    return "draft_only"


async def execute_workbook_with_bounded_retry(
    executor,
    call: dict[str, Any],
    request_context: dict[str, Any],
    progress_sink,
    *,
    max_attempts: int = 2,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Retry only the idempotent packaging step, preserving model decisions.

    A packaging failure is never a professional decision: the saved model
    result is reused verbatim, the same checkpoint is resumed, and the model is
    not called again.  Under real memory pressure the *same* allocation fails
    again immediately, so a retry is only useful once the process has actually
    released the reference tables packaging built.  ``release_memory_for_packaging``
    runs between attempts, and a memory-pressure failure gets one extra
    relief-and-retry attempt before the client is told to rebuild from the
    interface.
    """

    traces: list[dict[str, Any]] = []
    safe_payload: dict[str, Any] = {}
    attempts = max(1, int(max_attempts))
    memory_relief: list[dict[str, Any]] = []
    attempt = 0
    while attempt < attempts:
        attempt += 1
        payload = await executor(call, request_context, progress_sink)
        safe_payload = safe_workbook_history_projection(payload)
        checkpoint = (
            dict(safe_payload.get("checkpoint") or {})
            if isinstance(safe_payload.get("checkpoint"), dict)
            else {}
        )
        trace = {
            "tool": str(call.get("tool") or ""),
            "attempt": attempt,
            "status": str(safe_payload.get("status") or "empty"),
            "code": str(safe_payload.get("code") or ""),
        }
        if checkpoint.get("checkpoint_id"):
            trace["checkpoint_id"] = str(checkpoint["checkpoint_id"])
            trace["resumed"] = bool(checkpoint.get("resumed"))
        if safe_payload.get("error_type"):
            trace["error_type"] = str(safe_payload["error_type"])
        traces.append(trace)
        if safe_payload.get("status") != "failed":
            break
        if not bool(safe_payload.get("memory_pressure")):
            continue
        if attempts < _PACKAGING_MEMORY_ATTEMPTS:
            attempts = _PACKAGING_MEMORY_ATTEMPTS
        if attempt >= attempts:
            break
        relief = release_memory_for_packaging(
            reason=str(call.get("tool") or "workbook")
        )
        memory_relief.append(relief)
        trace["memory_released"] = list(relief.get("released") or ())
    if memory_relief:
        safe_payload["memory_relief"] = memory_relief
    return safe_payload, traces


def _context_objects(
    prefix: str,
    values: Sequence[Any],
) -> tuple[ContextObject, ...]:
    """Create stable, whole context objects; never slice an object to make it fit."""
    objects: list[ContextObject] = []
    for index, value in enumerate(values):
        if value in (None, "", [], {}, ()):
            continue
        objects.append(ContextObject(f"{prefix}:{index}", value))
    return tuple(objects)


def _text_context_objects(prefix: str, text: str) -> tuple[ContextObject, ...]:
    """Split only at producer-owned paragraph boundaries, preserving every paragraph."""
    return _context_objects(
        prefix,
        [part.strip() for part in str(text or "").split("\n\n") if part.strip()],
    )


def workspace_note_objects(
    candidates: Sequence[ContextCandidate], *, registered: bool,
) -> tuple[ContextObject, ...]:
    """Explicit workspace notes remain optional advisory context, never evidence."""
    if not registered:
        return ()
    return tuple(
        item for candidate in candidates
        if candidate.kind == ContextKind.WORKING_MEMORY
        for item in candidate.objects if item.object_id.startswith("note:")
    )


def model_read_frame_evidence(source_context, chunks, receipts, *, native_exchanges=()):
    """Replay literal bodies once; native receipts remain in mandatory tool replies."""
    source_objects = []
    for item in source_context:
        if isinstance(item, Mapping):
            item = {key: value for key, value in item.items()
                    if key not in {"previously_shown_cited_evidence", "previous_model_requested_exact_reads"}}
            if not item:
                continue
        source_objects.append(item)
    native_ids = {reply.call_id for exchange in native_exchanges for reply in exchange.replies}
    legacy_receipts = [receipt for receipt in receipts
                       if (receipt.get("call") or {}).get("call_id") not in native_ids]
    receipt_context = ([{"model_requested_reads": legacy_receipts}]
                       if legacy_receipts or not native_exchanges else [])
    return [*source_objects, *(compact_read_replay(chunks) if chunks else []), *receipt_context]


def govern_model_read_messages(*, source_context, chunks, receipts=(), **context):
    """Use one capacity contract for initial replay and both native continuations."""
    required_refs = [str(record.get("global_evidence_id") or record.get("ref") or "")
                     for item in source_context if isinstance(item, Mapping)
                     for record in item.get("previously_shown_cited_evidence", ())
                     if isinstance(record, Mapping)]
    required_refs.extend(str(ref) for receipt in receipts
                         if (receipt.get("call") or {}).get("tool") in {
                             "read_norm_card", "read_resource_price", "read_source"}
                         for ref in [*(receipt.get("evidence_refs") or ()),
                                     *(receipt.get("evidence_bindings") or {}).values()])
    replay = prepare_model_read_replay(chunks, required_refs=required_refs)
    exchanges = context.get("native_exchanges", ())
    required = model_read_frame_evidence(source_context, (), receipts, native_exchanges=exchanges)
    messages, packet = govern_inference_messages(
        **context, required_evidence=[*required, *replay.required], evidence=replay.optional)
    admitted_objects = {obj.object_id for section in packet.sections for obj in section.objects}
    body_refs = [*replay.exact_body_refs,
                 *(ref for index, refs in enumerate(replay.optional_body_refs)
                   if f"evidence:{index}" in admitted_objects for ref in refs)]
    return messages, packet, replay.inventory_refs, body_refs


def model_read_capacity_trace(error: ContextRequiredSectionOverflow, *, purpose: str) -> dict[str, Any]:
    """Expose actual capacity numbers and producer-owned section counts, never bodies."""
    counts: dict[str, int] = {}
    for object_id in error.object_ids:
        prefix = str(object_id).partition(":")[0]
        section = prefix if prefix in {"profile", "request", "source-required", "native-exchange"} else "other"
        counts[section] = counts.get(section, 0) + 1
    return {"code": error.code, "purpose": purpose, "budget": error.budget,
            "available_tokens": error.budget, "required_tokens": error.required_tokens,
            "overflow_tokens": max(0, error.required_tokens - error.budget),
            "required_objects": len(error.object_ids), "required_section_object_counts": counts}


def govern_inference_messages(
    *,
    preset: ModelExecutionPreset,
    profile_prefix: str,
    request_payload: Any,
    shortlist: Sequence[Any] = (),
    native_tools: Sequence[Any] = (),
    checkpoint: Sequence[ContextObject] = (),
    working_memory: Sequence[ContextObject] = (),
    evidence: Sequence[Any] = (),
    required_evidence: Sequence[Any] = (),
    source_map: Sequence[Any] = (),
    tool_exchange: Sequence[Any] = (),
    native_exchanges: Sequence[NativeToolExchange] = (),
    dialogue: Sequence[Any] = (),
    admit_messages=None,
) -> tuple[list[dict[str, Any]], ContextPacket]:
    """Build the sole bounded packet used for one provider inference request."""
    if any(not isinstance(exchange, NativeToolExchange) for exchange in native_exchanges):
        raise TypeError("native exchange context needs typed NativeToolExchange objects")
    candidates = [
        ContextCandidate(
            ContextKind.PROFILE_PREFIX,
            (ContextObject("profile:bound", profile_prefix),),
            required=True,
        ),
        ContextCandidate(ContextKind.TOOL_SHORTLIST, _context_objects("tool", () if native_tools else shortlist)),
        ContextCandidate(
            ContextKind.REQUEST,
            (ContextObject("request:current", request_payload),),
            required=True,
        ),
        ContextCandidate(ContextKind.CHECKPOINT, tuple(checkpoint)),
        ContextCandidate(ContextKind.WORKING_MEMORY, tuple(working_memory)),
        ContextCandidate(
            ContextKind.EVIDENCE,
            _context_objects("source-required", required_evidence),
            required=True,
        ),
        ContextCandidate(ContextKind.EVIDENCE, _context_objects("evidence", evidence)),
        ContextCandidate(ContextKind.SOURCE_MAP, _context_objects("source", source_map)),
        ContextCandidate(ContextKind.TOOL_EXCHANGE, _context_objects("exchange", tool_exchange)),
        ContextCandidate(
            ContextKind.TOOL_EXCHANGE,
            tuple(ContextObject(f"native-exchange:{index + 1}", exchange)
                  for index, exchange in enumerate(native_exchanges)),
            required=True,
        ),
        ContextCandidate(ContextKind.DIALOGUE, _context_objects("dialogue", dialogue)),
    ]
    external_tokens = (
        conservative_token_estimate(json.dumps(list(native_tools), ensure_ascii=False, sort_keys=True)) + 2
        if native_tools else 0
    )
    governed_preset = replace(preset, input_token_limit=max(0, preset.input_token_limit - external_tokens))
    try:
        packet = ContextGovernor(governed_preset).pack(candidates, admit_messages=admit_messages)
    except ContextRequiredWireOverflow as error:
        raise CloudBudgetStop("CLOUD_TURN_TOKEN_BUDGET: REQUIRED_CONTEXT_EXCEEDS_REMAINING_RESERVATION") from error
    if external_tokens:
        packet = replace(packet, provider_payload_tokens=external_tokens)
    return packet.as_messages(), packet


def context_packet_trace(packet: ContextPacket, *, purpose: str) -> dict[str, Any]:
    """Expose exact model-visible evidence while keeping private prompt/memory redacted."""
    visible_kinds = {ContextKind.EVIDENCE, ContextKind.SOURCE_MAP}

    def section_trace(section) -> dict[str, Any]:
        item = {
            "kind": section.kind.value,
            "items": len(section.objects),
            "tokens": section.token_count,
            "object_ids": list(section.object_ids),
        }
        if section.kind in visible_kinds:
            item["objects"] = [
                {
                    "object_id": obj.object_id,
                    "payload": json.loads(json.dumps(obj.payload, ensure_ascii=False, default=str)),
                    "text": obj.render(),
                    "sha256": hashlib.sha256(obj.render().encode("utf-8")).hexdigest(),
                }
                for obj in section.objects
            ]
        return item

    return {
        "purpose": purpose,
        **({"native_tools_reserved_tokens": packet.provider_payload_tokens}
           if packet.provider_payload_tokens else {}),
        "preset_id": packet.preset_id,
        "input_budget_tokens": packet.input_budget_tokens,
        "generation_reserve_tokens": packet.generation_reserve_tokens,
        "safety_reserve_tokens": packet.safety_reserve_tokens,
        "included_tokens": packet.included_tokens,
        "sections": [section_trace(section) for section in packet.sections],
        "omissions": [
            {
                "kind": omission.kind.value,
                "total": omission.total,
                "omitted": omission.omitted,
                "object_ids": list(omission.object_ids),
                "cursor": omission.cursor,
                "reason": omission.reason,
            }
            for omission in packet.omissions
        ],
    }


async def execute_canonical_shadow_decision(
    *,
    proposed_calls: list[dict[str, Any]],
    allowed_tools: set[str],
    dataset_ids: list[str],
    tool_harness: Any,
) -> dict[str, Any]:
    """Execute at most one candidate call and return structural, redacted trace."""
    decision = one_model_decision_from_calls(proposed_calls, allowed=allowed_tools)
    trace: dict[str, Any] = {
        "schema": "les_canonical_shadow_v1",
        "user_visible": False,
        "persisted": False,
        "proposed_calls": decision.proposed_calls,
        "executed_calls": decision.executed_calls,
        "pending_calls": decision.pending_calls,
        "tool_name": str((decision.call or {}).get("tool") or ""),
    }
    if decision.call is None:
        trace.update(status="no_valid_call", execution_code="")
        return trace
    payload = await tool_harness.call_async(
        str(decision.call["tool"]),
        dict(decision.call["args"]),
        actor_id="canonical-shadow",
        actor_role="user",
        allowed_dataset_ids=tuple(str(item) for item in dataset_ids if str(item)),
        shadow=True,
    )
    execution = payload.get("execution") if isinstance(payload, dict) else {}
    trace.update(
        status=str((execution or {}).get("status") or payload.get("status") or "unknown"),
        execution_code=str((execution or {}).get("code") or ""),
        result_schema=str(payload.get("schema") or ""),
    )
    return trace


async def safe_execute_canonical_shadow_decision(**kwargs: Any) -> dict[str, Any]:
    """Keep every candidate failure outside the authoritative legacy path."""
    proposed = kwargs.get("proposed_calls") or []
    allowed = kwargs.get("allowed_tools") or set()
    structural = one_model_decision_from_calls(proposed, allowed=set(allowed))
    try:
        return await execute_canonical_shadow_decision(**kwargs)
    except Exception as error:  # noqa: BLE001 - shadow must never affect legacy
        logger.warning("[CANONICAL_SHADOW] candidate skipped: %s", type(error).__name__)
        return {
            "schema": "les_canonical_shadow_v1",
            "user_visible": False,
            "persisted": False,
            "status": "error",
            "error_type": type(error).__name__,
            "executed_calls": 0,
            "attempted_calls": structural.executed_calls,
            "pending_calls": structural.pending_calls,
        }


def profile_temperature(profile_snapshot: dict[str, Any] | None, *, fallback: float) -> float:
    """Return the bounded immutable profile temperature for generation."""

    policy = (profile_snapshot or {}).get("model_policy") or {}
    try:
        value = float(policy.get("temperature", fallback))
    except (TypeError, ValueError):
        value = fallback
    return max(0.0, min(2.0, value))


def profile_research_rounds(profile_snapshot: dict[str, Any] | None, *, configured: int) -> int:
    """Respect the profile's iterative-search switch without changing the global ceiling."""

    iterative = bool(((profile_snapshot or {}).get("rag_policy") or {}).get("iterative", True))
    return max(1, configured) if iterative else 1


TABULAR_ATTACHMENT_ESTIMATOR_BRIDGE = "tabular_attachment_estimator_path_v1"
_TABULAR_ESTIMATOR_TOOLS = ("search_sources", "read_source", "build_vor_workbook", "build_lsr_workbook")
_TABULAR_LSR_VOLUME_INSTRUCTION = model_lsr_result_field_instruction() + (
    "Пустые ценовые колонки не мешают сборке. Код рассчитывает выбранные нормы "
    "и ресурсы в явно заданной книге цен. quantity сохраняет исходный объём; "
    "calc_quantity не подменяет его, conversion_source обосновывает перевод единиц. "
    "Спецификация изделий может обосновывать монтажные работы на тех же source_row: "
    "определи операции по задаче и источникам, учитывая состав нормы и двойной учёт. "
    "Не назначай монтаж каждому изделию автоматически. work_row поставки — source_row "
    "реально возвращённой работы row_role=work, не шифр. Если работу определить "
    "нельзя, верни unresolved с open_gap. Для NEEDS_RESEARCH/MISSING укажи gap_reason: "
    "insufficient_source_data либо no_suitable_candidate и объясни причину. "
    "Отсутствие цены не делает норму MISSING."
)
_MODEL_RAG_QUERY_INSTRUCTION = (
    "Прочитай приложенный материал целиком. Определи требуемый итоговый документ. "
    "Если упомянуты ВОР и ЛСР/смета, отличай результат от исходника и дальнейшего назначения. "
    "В этом же ответе можешь объявить artifact_kind (vor или lsr) и queries в корне JSON; "
    "queries содержит твои дословные поисковые строки. Для ВОР, если исходника достаточно, "
    "допустим ответ {\"artifact_kind\":\"vor\",\"queries\":[]}; он не требует поиска норм. "
    "Когда для задачи нужен поиск: Сформулируй поисковые запросы к выбранным датасетам, "
    "необходимые для подбора evidence по всем фактическим строкам исходного материала. Число запросов "
    "определяешь ты; фиксированного лимита нет. В запросах сохраняй язык "
    "и профессиональную терминологию исходных строк; не переводи и не "
    "транслитерируй их. Сейчас не выбирай нормы "
    "и не отвечай по существу — верни только сами поисковые запросы, "
    "каждый с новой строки. Без обращения к собеседнику, без описания "
    "плана и без ожидания подтверждения. Пользовательские замечания задают "
    "требования к конечному документу: не превращай инструкции о формате, "
    "инструментах, проверках или параметрах цены в поисковые запросы. "
    "Не копируй задачу; запрос называет нужную работу или ресурс исходника."
)
_MODEL_RAG_QUERY_REPAIR_INSTRUCTION = (
    "Предыдущий ответ не содержал поисковых строк. Верни только поисковые "
    "запросы к датасетам в формате, описанном выше: каждый с новой строки, "
    "обычным текстом или пунктом списка. Без обращения, плана и "
    "подтверждения. Нормы пока не выбирай."
)
_MODEL_RAG_QUERY_VOLUME_HINT = (
    "Пустые ценовые колонки исходника не ищи. Запросы — по работам и "
    "измерителям строк, не по прайсу. Если исходник называет изделие, "
    "если задача требует подбора нормы, по задаче и данным сформулируй обоснованную монтажную операцию "
    "для поиска её нормы; ВОР без такой необходимости не требует поиска нормы. "
    "Не добавляй неизвестные условия, размеры или объёмы."
)
#: The marker spellings the prompt names and the reader strips.  One tuple feeds
#: both sides, so the declared-query contract cannot be documented on one end and
#: implemented on the other (``test_declaration_prompt_and_reader_agree``).
_DECLARED_QUERY_MARKER_EXAMPLES = ("1.", "1)", "-", "*", "•", "—")
#: The one format contract, quoted to the model and implemented by
#: :func:`read_declared_query_list`.  Blocker § 2 (29.09) asked for prompt, reader
#: and adapter to agree instead of growing a list of Russian phrases: every form
#: named here is accepted structurally, whatever model produced it.
_MODEL_RAG_QUERY_FORMAT_CONTRACT = (
    "Формат ответа: каждый поисковый запрос — отдельной строкой; "
    "код исполнит твой запрос дословно. Ты выбираешь формулировку поиска "
    "по задаче и данным исходника, она не обязана повторять название изделия. "
    "Строка может быть обычным текстом или пунктом "
    "списка ("
    + ", ".join(_DECLARED_QUERY_MARKER_EXAMPLES)
    + ") — любой из этих видов читается как один запрос, номер и маркер списка "
    "отбрасываются, текст запроса остаётся дословным. Сопровождающий ответ "
    "(вступление, пояснение, заключение) допустим только отдельными строками: он "
    "не будет выполнен как запрос и сохраняется с причиной отклонения. Строка, "
    "которая повторяет это самое задание (что именно ты собираешься искать), — "
    "сопровождающий ответ, а не запрос: запрос называет предмет и работу строки "
    "исходника. Если "
    "запрос относится к конкретной строке листа, укажи её адрес в начале строки "
    "(например «СКС!R12 — Прокладка кабеля»); адрес код читает как указатель, а "
    "не как часть формулировки."
)
_ROW_PACKET_MIN = 8
_ROW_PACKET_TARGET = 10
_ROW_PACKET_MAX = 12
_ROW_PACKET_MAX_ATTEMPTS = 2
#: One declaration call, then at most one repair and at most one continuation.
#: The ceiling bounds the orchestration, never the reading: a query list the
#: model cut off at ``finish_reason=length`` is finished by asking for exactly the
#: unread tail, which is a second call, not a second guess at the model's intent.
_MAX_SHEET_PASS_QUERY_CALLS = 3


def profile_uses_model_driven_retrieval(
    profile_snapshot: dict[str, Any] | None,
) -> bool:
    """Keep model-authored retrieval as an estimator workflow invariant."""

    snapshot = profile_snapshot if isinstance(profile_snapshot, dict) else {}
    return bool(
        str(snapshot.get("mode") or "").strip().casefold() == "estimator"
        or (snapshot.get("rag_policy") or {}).get(
            "model_authored_initial_query", False
        )
    )


def profile_uses_tabular_estimator_path(
    profile_snapshot: dict[str, Any] | None,
) -> bool:
    """True when this turn overlays estimator evidence because of a table file."""

    snapshot = profile_snapshot if isinstance(profile_snapshot, dict) else {}
    bridges = snapshot.get("effective_capability_bridges") or []
    return bool(snapshot.get("tabular_estimator_path")) or (
        TABULAR_ATTACHMENT_ESTIMATOR_BRIDGE in bridges
        if isinstance(bridges, list)
        else False
    )


def profile_uses_smeta_norm_retrieval(
    profile_snapshot: dict[str, Any] | None,
) -> bool:
    """Route estimator and tabular-attachment turns to the normative-card index."""

    snapshot = profile_snapshot if isinstance(profile_snapshot, dict) else {}
    return (
        str(snapshot.get("mode") or "").strip().casefold() == "estimator"
        or profile_uses_tabular_estimator_path(snapshot)
    )


def attachment_enables_tabular_estimator_path(
    source_catalog: AttachmentSourceCatalog | None,
) -> bool:
    """A loaded sheet catalog is the only signal; the question text is not."""

    return source_catalog is not None and bool(source_catalog.rows)


def overlay_tabular_estimator_snapshot(
    profile_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    """Enable model-authored RAG and LSR packaging for this turn only.

    Saved UI mode and the immutable profile revision are not rewritten. The
    overlay is the table file, not a keyword in the question.
    """

    snapshot = dict(profile_snapshot or {})
    rag_policy = dict(snapshot.get("rag_policy") or {})
    rag_policy["model_authored_initial_query"] = True
    modules = [
        str(item) for item in (rag_policy.get("system_datasets") or []) if str(item)
    ]
    if "smeta" not in modules:
        modules.append("smeta")
    rag_policy["system_datasets"] = modules
    snapshot["rag_policy"] = rag_policy
    tools = [str(name) for name in (snapshot.get("tools") or []) if str(name).strip()]
    for name in _TABULAR_ESTIMATOR_TOOLS:
        if name not in tools:
            tools.append(name)
    snapshot["tools"] = tools
    bridges = [
        str(item)
        for item in (snapshot.get("effective_capability_bridges") or [])
        if str(item)
    ]
    if TABULAR_ATTACHMENT_ESTIMATOR_BRIDGE not in bridges:
        bridges.append(TABULAR_ATTACHMENT_ESTIMATOR_BRIDGE)
    snapshot["effective_capability_bridges"] = bridges
    snapshot["tabular_estimator_path"] = True
    skill_path = Path(__file__).resolve().parents[2] / "skills" / "smeta" / "references" / "rag-estimator.md"
    workbook_skill = skill_path.read_text(encoding="utf-8").strip()
    existing_skill = str(snapshot.get("skill_text") or "").strip()
    if workbook_skill not in existing_skill:
        snapshot["skill_text"] = existing_skill + "\n\n" + workbook_skill
    snapshot["effective_skill_modules"] = [{
        "path": "skills/smeta/references/rag-estimator.md",
        "sha256": hashlib.sha256(workbook_skill.encode("utf-8")).hexdigest(),
        "source": "tabular_attachment_estimator_path_v1",
    }]
    return snapshot


def bind_tabular_estimator_profile(
    profile_snapshot: dict[str, Any] | None,
    *,
    attachment_id: str = "",
    source_catalog: AttachmentSourceCatalog | None = None,
) -> tuple[dict[str, Any], AttachmentSourceCatalog | None, bool]:
    """Load the attachment catalog and overlay estimator evidence for this request."""

    catalog = source_catalog
    if catalog is None:
        catalog = load_catalog_from_attachment_id(str(attachment_id or ""))
    snapshot = dict(profile_snapshot or {})
    if not attachment_enables_tabular_estimator_path(catalog):
        return snapshot, catalog, False
    return overlay_tabular_estimator_snapshot(snapshot), catalog, True


def model_rag_query_instruction(profile_snapshot: dict[str, Any] | None) -> str:
    """Search-query call contract; empty VOR prices are not a price-list search.

    The format paragraph is the same constant the reader implements, so a change
    to one side is a change to the other by construction.
    """

    parts = [_MODEL_RAG_QUERY_INSTRUCTION, _MODEL_RAG_QUERY_FORMAT_CONTRACT]
    snapshot = profile_snapshot if isinstance(profile_snapshot, dict) else {}
    if (
        str(snapshot.get("mode") or "").strip().casefold() == "estimator"
        or profile_uses_tabular_estimator_path(snapshot)
    ):
        parts.append(_MODEL_RAG_QUERY_VOLUME_HINT)
    return "\n\n".join(parts)


def sheet_pass_should_run(
    catalog: AttachmentSourceCatalog | None,
    *,
    tabular_estimator_bound: bool,
    model_driven: bool,
) -> bool:
    """Same packet order for small and large tabular sources: queries → sources → decisions."""

    if not tabular_estimator_bound or not model_driven or catalog is None:
        return False
    names = catalog_work_sheet_names(catalog)
    if not names:
        return False
    return bool(catalog.work_locators())


def sheet_pass_query_instruction(
    profile_snapshot: dict[str, Any] | None,
    *,
    sheet: str,
    sheet_index: int,
    sheet_count: int,
    research_round: int = 0,
) -> str:
    extra = ""
    if research_round > 0:
        extra = "\n" + lsr_research_query_instruction(research_round)
    return (
        model_rag_query_instruction(profile_snapshot)
        + f"\nСейчас только лист «{sheet}» ({sheet_index}/{sheet_count}). "
        "Другие листы манифеста будут отдельными шагами; не составляй запросы по ним."
        + "\nСоставляй запросы только по исходным строкам текущего пакета, "
        "полностью представленным ниже. Манифест перечисляет адреса документа, "
        "но не заменяет данные остальных пакетов. Не придумывай их содержание "
        "и не составляй заново запросы по всему листу. Число операций и запросов "
        "для представленных строк определяешь ты."
        + "\nКроме твоих запросов система гарантированно добавляет два запроса на "
        "каждую строку листа: дословный текст строки и тот же текст с явно указанными "
        "в исходнике атрибутами (раздел листа, подписанный столбец, написанный шифр). "
        "Такие запросы помечены "
        "в доказательственной части как «дословный исходный текст строки» или «системный "
        "подбор по атрибутам этой строки». Это только кандидаты: выбирать норму, оценивать "
        "её применимость и отклонять всех предложенных кандидатов решаешь ты. Отсутствие "
        "кандидата не означает отсутствие нормы в базе, а наличие кандидата не означает, "
        "что она применима."
        + extra
    )


def sheet_pass_question_tail(
    question: str,
    *,
    sheet: str,
    sheet_index: int,
    sheet_count: int,
    remaining_work: Sequence[str] | None = None,
    reasoning_enabled: bool = False,
) -> str:
    remaining = [str(item).strip() for item in (remaining_work or ()) if str(item).strip()]
    remainder = ""
    if remaining:
        preview = ", ".join(remaining[:40])
        extra = f" и ещё {len(remaining) - 40}" if len(remaining) > 40 else ""
        remainder = f" Остались только строки: {preview}{extra}."
    sheet_clause = (
        f"Вопрос: {question}\n\n"
        + ("" if reasoning_enabled else "/no_think\n")
        +
        "Дай итоговый инженерный ответ. Не выдумывай факты и используй только существующие "
        "номера [Источник N]. Если материалов недостаточно, отдели это от подтверждённых выводов."
        f"\nСейчас только лист «{sheet}» ({sheet_index}/{sheet_count}). "
        "Для ещё не решённых исходных строк текущего пакета дай решения. "
        "При обычном продолжении, если prior_model_decisions уже содержит операции, верни только новые "
        "или изменённые; неизменённые операции сохраняются приложением. "
        "При явном пересмотре верни все предложенные прежние операции, включая неизменённые "
        "с дословными прежними полями, operation_id и expected_revision из показанного revision. "
        "Не обрабатывай другие листы манифеста. "
    )
    remaining_clause = (
        remainder
        + " При обычном продолжении ответ должен вместить новые и изменённые операции текущего пакета; "
        "при явном пересмотре — все предложенные прежние операции: без вводного "
        "обзора и итоговых рекомендаций. Число операций определяешь ты; "
        "одна исходная строка может обосновывать несколько операций. "
        "Не возвращай строки других пакетов; не придумывай их содержание по манифесту."
    )
    return lsr_result_table_instruction(
        sheet_clause=sheet_clause,
        remaining_clause=remaining_clause,
    )


def cited_source_row_keys(
    rows: Sequence[Mapping[str, Any]],
    catalog: AttachmentSourceCatalog | None = None,
) -> set[str]:
    keys: set[str] = set()
    for row in rows:
        raw = row.get("source_row")
        if raw in (None, ""):
            continue
        keys.add(str(raw).strip())
        if catalog is not None:
            found = catalog.lookup(raw)
            if found is not None:
                keys.add(found.locator)
    return keys


def _source_locator_aliases(
    raw: Any,
    catalog: AttachmentSourceCatalog | None = None,
) -> set[str]:
    aliases = {str(raw).strip()} if raw not in (None, "") else set()
    if catalog is not None and raw not in (None, ""):
        found = catalog.lookup(raw)
        if found is not None:
            aliases.add(found.locator)
    return {item for item in aliases if item}


def _decision_role_key(row: Mapping[str, Any]) -> str:
    """Stable role for merge/duplicate identity. Prefer authored row_role."""

    from proxy.services.lsr_source_coverage_service import inferred_row_role

    return inferred_row_role(row) or "work"


def _decision_identity_sha(row: Mapping[str, Any]) -> str:
    """Content fingerprint of one decision, identity bookkeeping excluded."""

    from proxy.services.workbook_research_job_service import _decision_content_sha

    return _decision_content_sha(row)


def merge_model_rag_rows(
    existing: Sequence[Mapping[str, Any]],
    incoming: Sequence[Mapping[str, Any]],
    catalog: AttachmentSourceCatalog | None = None,
) -> list[dict[str, Any]]:
    """Decision identity wins: operation_id first, else locator+role+content.

    A specification line may legally carry several distinct operations on the
    same locator; those are different decisions, not duplicates. A redelivered
    identical packet is the same decision again and never enters twice. Code
    does not rewrite cells and does not fuse operations by title.
    """

    merged = [dict(row) for row in existing if isinstance(row, Mapping)]
    seen_ops: set[str] = set()
    seen_keys: set[tuple[str, str, str]] = set()
    # Index rows for in-place volatile-field refresh when a redelivery carries
    # newer note / evidence_refs / status. Directive 2.1: those updates must
    # not spawn a new operation but must not be silently discarded either.
    by_op: dict[str, dict[str, Any]] = {}
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in merged:
        op = str(row.get("operation_id") or "").strip()
        if op:
            seen_ops.add(op)
            by_op[op] = row
        role = _decision_role_key(row)
        digest = _decision_identity_sha(row)
        for alias in _source_locator_aliases(row.get("source_row"), catalog):
            key = (alias, role, digest)
            seen_keys.add(key)
            by_key.setdefault(key, row)
    from proxy.services.workbook_research_job_service import DECISION_REFRESH_FIELDS

    # One shared list with the durable store: what the digest treats as
    # explanatory is exactly what a redelivery may refresh in place.  Keeping the
    # two in sync by import is the point — a field the prompt announces but this
    # tuple forgets could never reach the record after a continuation (§ 3).
    _volatile_refresh = DECISION_REFRESH_FIELDS
    for row in incoming:
        if not isinstance(row, Mapping):
            continue
        payload = dict(row)
        raw = payload.get("source_row")
        if raw in (None, ""):
            continue
        op = str(payload.get("operation_id") or "").strip()
        role = _decision_role_key(payload)
        digest = _decision_identity_sha(payload)
        aliases = _source_locator_aliases(raw, catalog)
        target: dict[str, Any] | None = None
        if op and op in seen_ops:
            target = by_op.get(op)
        elif not op:
            for alias in aliases:
                candidate = by_key.get((alias, role, digest))
                if candidate is not None:
                    target = candidate
                    break
        if target is not None:
            # Same decision, refresh volatile metadata only. Identity, quantity,
            # unit, norm_code, title and locator stay as the first-authority.
            for field in _volatile_refresh:
                if field in payload:
                    target[field] = payload[field]
            continue
        if op:
            seen_ops.add(op)
            by_op[op] = payload
        for alias in aliases:
            key = (alias, role, digest)
            seen_keys.add(key)
            by_key.setdefault(key, payload)
        merged.append(payload)
    return merged


ACTUAL_MODEL_CALLS_SCHEMA = "les.actual_model_calls.v1"


def ensure_actual_model_calls(trace: dict[str, Any] | None) -> dict[str, Any]:
    payload = trace if isinstance(trace, dict) else {}
    bucket = payload.get("actual_model_calls")
    if not isinstance(bucket, dict):
        bucket = {
            "schema": ACTUAL_MODEL_CALLS_SCHEMA,
            "calls": [],
            "search_executions": 0,
            "search_cache_hits": 0,
            "search_hits": 0,
        }
        payload["actual_model_calls"] = bucket
    bucket.setdefault("calls", [])
    bucket.setdefault("search_executions", 0)
    bucket.setdefault("search_cache_hits", 0)
    bucket.setdefault("search_hits", 0)
    return bucket


def append_actual_model_call(
    trace: dict[str, Any] | None,
    *,
    purpose: str,
    finish_reason: str = "",
    completion_tokens: int = 0,
) -> None:
    bucket = ensure_actual_model_calls(trace)
    bucket["calls"].append(
        {
            "purpose": str(purpose or ""),
            "finish_reason": str(finish_reason or ""),
            "completion_tokens": int(completion_tokens or 0),
            **({"reasoning": dict(trace["last_model_call_execution"]["reasoning"])}
               if trace and isinstance(trace.get("last_model_call_execution"), Mapping)
               and isinstance(trace["last_model_call_execution"].get("reasoning"), Mapping) else {}),
        }
    )


def append_actual_search(
    trace: dict[str, Any] | None,
    *,
    cached: bool,
    hit_count: int,
) -> None:
    bucket = ensure_actual_model_calls(trace)
    if cached:
        bucket["search_cache_hits"] = int(bucket.get("search_cache_hits") or 0) + 1
    else:
        bucket["search_executions"] = int(bucket.get("search_executions") or 0) + 1
    bucket["search_hits"] = int(bucket.get("search_hits") or 0) + int(hit_count or 0)


def durable_research_hit(hit: Any) -> dict[str, Any]:
    if isinstance(hit, Mapping):
        meta = hit.get("meta") if isinstance(hit.get("meta"), Mapping) else {}
        return {
            "content": str(hit.get("content") or ""),
            "doc_id": str(hit.get("doc_id") or ""),
            "doc_name": str(hit.get("doc_name") or ""),
            "score": float(hit.get("score") or 0.0),
            "meta": dict(meta),
        }
    meta = getattr(hit, "meta", {}) or {}
    return {
        "content": str(getattr(hit, "content", "") or ""),
        "doc_id": str(getattr(hit, "doc_id", "") or ""),
        "doc_name": str(getattr(hit, "doc_name", "") or ""),
        "score": float(getattr(hit, "score", 0.0) or 0.0),
        "meta": dict(meta) if isinstance(meta, Mapping) else {},
    }


def research_hit_from_record(record: Mapping[str, Any]) -> _ModelRagEvidenceChunk:
    meta = dict(record.get("meta") or {}) if isinstance(record.get("meta"), Mapping) else {}
    return _ModelRagEvidenceChunk(
        content=str(record.get("content") or ""),
        doc_id=str(record.get("doc_id") or ""),
        doc_name=str(record.get("doc_name") or ""),
        score=float(record.get("score") or 0.0),
        meta=meta,
    )


def restore_query_hits_from_cache(
    queries: Sequence[str],
    cache: Mapping[str, Any],
    *,
    cache_contract: str = "",
) -> list[tuple[str, Sequence[Any]]]:
    restored: list[tuple[str, Sequence[Any]]] = []
    for query in queries:
        key = str(query or "").strip()
        records = cache.get(key) if isinstance(cache, Mapping) else None
        if isinstance(records, Mapping):
            if cache_contract and records.get("contract") != cache_contract:
                continue
            records = records.get("hits")
        elif cache_contract:
            continue
        if not key or not isinstance(records, list):
            continue
        hits = tuple(
            research_hit_from_record(item)
            for item in records
            if isinstance(item, Mapping)
        )
        restored.append((key, hits))
    return restored


async def restore_or_refresh_held_query_hits(
    queries: Sequence[str], cache: dict[str, Any], *, model_research_tools: Any,
    retrieval_trace: dict[str, Any], hits_per_query: int,
) -> tuple[list[tuple[str, Sequence[Any]]], dict[str, list[dict[str, Any]]], str]:
    """Resume pending evidence with the current reader and the original queries."""
    from proxy.services.workbook_research_job_service import research_cache_entry
    contract = str(getattr(model_research_tools, "cache_contract", "") or "")
    restored: list[tuple[str, Sequence[Any]]] = []
    updates: dict[str, list[dict[str, Any]]] = {}
    for query in queries:
        cached = restore_query_hits_from_cache([query], cache, cache_contract=contract)
        if cached:
            hits = cached[0][1]
            append_actual_search(retrieval_trace, cached=True, hit_count=len(hits))
        else:
            result = await model_research_tools.execute({"tool": "search_sources", "args": {"q": query}})
            if model_search_result_blocks_packet(result.payload):
                return restored, updates, str(result.payload.get("status") or "unknown")
            hits = tuple(result.chunks)[:max(1, int(hits_per_query))]
            updates[query] = [durable_research_hit(item) for item in hits]
            cache[query] = research_cache_entry(updates[query], cache_contract=contract, previous=cache.get(query))
            append_actual_search(retrieval_trace, cached=False, hit_count=len(hits))
        restored.append((query, hits))
    return restored, updates, ""


_MODEL_SEARCH_CONTINUE_STATUSES = frozenset({"ok", "missing", "degraded_sparse_only"})


def model_search_result_blocks_packet(payload: Mapping[str, Any] | None) -> bool:
    """Abort a packet only on search infrastructure failure.

    Zero hits (`missing`) is a model-visible fact: remaining queries and the
    terminal row table still run. The model may mark those rows MISSING.
    """

    status = str((payload or {}).get("status") or "").strip().casefold()
    return status not in _MODEL_SEARCH_CONTINUE_STATUSES


def stamp_empty_retrieval(
    trace: dict[str, Any],
    *,
    model_driven: bool,
    chunks: Sequence[Any],
) -> None:
    """Do not label an awaiting model-authored search as empty retrieval."""

    if chunks or model_driven:
        trace.pop("empty_retrieval", None)
        return
    trace["empty_retrieval"] = {
        "schema": "empty_retrieval_model_first_v1",
        "model_final_allowed": True,
        "note": "No retrieved chunks; continue to model with memory/navigation instead of code NO_DATA final.",
    }


def finalize_actual_retrieval_emptiness(
    trace: dict[str, Any],
    *,
    evidence_count: int,
    searches_executed: int,
    search_hits: int,
) -> None:
    if int(evidence_count or 0) > 0 or int(search_hits or 0) > 0:
        trace.pop("empty_retrieval", None)
        return
    if int(searches_executed or 0) <= 0:
        return
    trace["empty_retrieval"] = {
        "schema": "empty_retrieval_model_first_v1",
        "model_final_allowed": True,
        "note": "model-authored searches returned no chunks",
    }


def model_rag_row_carries_no_decision(row: Any) -> bool:
    """True when a parsed row states no norm verdict and no role at all.

    Blocker file § 1/§ 2 (29.09): an answer cut by ``finish_reason=length`` leaves
    the final table row half written — the locator and maybe the title are there,
    the columns that carry the decision are not.  Saving such a row as a model
    decision turns a technical read failure into what the customer reads as
    «модель решила, что нормы нет», which is exactly the confusion the blocker
    forbids.  A deliberate ``MISSING``/``нет`` verdict is a decision and stays.
    """

    if not isinstance(row, Mapping):
        return False
    for name in (
        "row_role",
        "norm_code",
        "norm_status",
        "open_gap",
        "analogue",
        "coverage",
        "clarification",
    ):
        if str(row.get(name) or "").strip():
            return False
    return not (row.get("resources") or row.get("evidence_refs"))


def truncated_tail_locator(rows: Sequence[Any], *, truncated: bool) -> str:
    """Locator of the answer's last row, but only when the cut left it empty.

    Order in ``rows`` is the order the model wrote, so the at-risk row is the last
    one.  Anything else in a truncated answer already carries a decision and is
    kept: dropping decided rows would lose real work over a formatting defect.
    """

    if not truncated or not rows:
        return ""
    last = rows[-1]
    if not isinstance(last, Mapping) or not model_rag_row_carries_no_decision(last):
        return ""
    return str(last.get("source_row") or "").strip()


def sheet_pass_keep_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    sheet: str,
    catalog: AttachmentSourceCatalog,
    errors: Sequence[str],
    drop_locator: str = "",
) -> list[dict[str, Any]]:
    """Keep this sheet's rows that passed per-pass Qx.Hy/quantity checks.

    ``drop_locator`` is the unread-tail locator of a cut-off answer: it is not
    saved as a decision, so it stays in the sheet's outstanding pool and the next
    packet puts it to the model again instead of the document shipping a row that
    was never actually read.
    """

    wanted = str(sheet or "").strip()
    unwanted = str(drop_locator or "").strip().upper()
    on_sheet: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        payload = dict(row)
        catalog_row = catalog.lookup(payload.get("source_row"))
        if catalog_row is not None:
            if catalog_row.sheet != wanted:
                continue
        else:
            # Keep the raw answer in history, but a partial/unknown locator
            # cannot become an accepted source decision or a workbook row.
            continue
        if unwanted and unwanted in {
            str(payload.get("source_row") or "").strip().upper(),
            str(getattr(catalog_row, "locator", "") or "").strip().upper(),
        }:
            continue
        on_sheet.append(payload)
    work_count = sum(1 for row in on_sheet if model_rag_row_kind(row) == "work")
    blocking = blocking_model_rag_result_errors(errors, work_row_count=work_count)
    kept: list[dict[str, Any]] = []
    for row in on_sheet:
        identity_blocked = any(
            error in {f"unknown_operation_id:{row.get('source_row')}:{row.get('operation_id')}",
                      f"operation_source_mismatch:{row.get('source_row')}:{row.get('operation_id')}"}
            for error in blocking
        )
        if identity_blocked or (model_rag_row_kind(row) == "work" and _sheet_pass_row_blocked(row, blocking)):
            continue
        kept.append(row)
    return kept


def _sheet_pass_row_blocked(row: Mapping[str, Any], blocking_errors: Sequence[str]) -> bool:
    key = str(row.get("source_row") or "").strip()
    refs = {
        str(item or "").strip().upper()
        for item in (row.get("evidence_refs") or [])
        if str(item or "").strip()
    }
    for error in blocking_errors:
        text = str(error)
        if text == "invalid_source_row":
            continue
        if ":" not in text:
            continue
        prefix, rest = text.split(":", 1)
        rest = rest.strip()
        if prefix in {
            "missing_evidence_ref",
            "source_quantity_mismatch",
            "duplicate_source_row",
        } and rest == key:
            return True
        if prefix == "unknown_evidence_ref" and rest.upper() in refs:
            return True
    return False


def remaining_sheet_work_locators(
    catalog: AttachmentSourceCatalog,
    sheet: str,
    cited: Sequence[str],
) -> list[str]:
    known = {str(item).strip() for item in cited if str(item).strip()}
    return [
        locator
        for locator in catalog_sheet_work_locators(catalog, sheet)
        if locator not in known
    ]


def structurally_complete_source_keys(rows, catalog):
    """Only complete source records finish a packet; norms remain model-owned."""
    from proxy.services.lsr_source_coverage_service import build_source_coverage

    keys = cited_source_row_keys(rows, catalog)
    coverage = build_source_coverage(catalog_locators=catalog.work_locators(), rows=rows)
    invalid = set(coverage["incomplete_locators"])
    return keys - invalid

def adjudicated_source_keys(rows, catalog):
    """Locators the model gave a terminal role to (work/material/equipment/resource/
    unresolved/header).

    A classified row is *decided* even when a quality gap (no norm, no work_row link,
    no open_gap sentence) remains — those gaps belong in the reported ``missing`` list,
    not in an endless resume.  Completion must not re-queue positions that legitimately
    have no applicable norm, or a large document can never finalize.
    """
    from proxy.services.lsr_source_coverage_service import inferred_row_role

    keys: set[str] = set()
    for row in rows:
        if not hasattr(row, "get"):
            continue
        raw = row.get("source_row")
        if raw in (None, ""):
            continue
        if not inferred_row_role(row):
            continue
        keys.add(str(raw).strip())
        if catalog is not None:
            found = catalog.lookup(raw)
            if found is not None:
                keys.add(found.locator)
    return keys


def settled_source_keys(rows, catalog):
    """Source rows that need no further packet: complete, or given a terminal role.

    Both halves are required.  ``structurally_complete_source_keys`` alone keeps
    a row in the packet pool for ever when the model legitimately decided it has
    no applicable norm, so a large document stalls on already-decided rows and
    the sheets behind them are never offered.  The terminal completion rule at
    the end of the sheet-pass loop has always accepted an adjudicated row; this
    helper is simply that one rule shared by the pool, so the loop can never
    queue work the completion check would already accept.  Quality gaps stay
    visible in the reported ``missing`` list, and an operator reopen of a
    locator removes its accepted rows, which returns it to the pool.
    """

    return structurally_complete_source_keys(rows, catalog) | adjudicated_source_keys(
        rows, catalog
    )


def research_run_stopped(job: Any) -> tuple[bool, bool, str]:
    """``(does_the_run_stop, is_it_a_cancellation, pause_kind)`` for a live job.

    Blocker file § 1, build 823: the sheet-pass loop asked "is this job paused" and
    treated every pause as a stop, so a packet guard that gave up on two dead rows
    of АР ended the run for the whole document and eight sheets behind it were never
    offered.  The durable job now names which guard wrote the pause, and only the
    per-run budget, an operator stop or a cancellation stops the run.
    """

    if not isinstance(job, Mapping):
        return False, False, ""
    guard = job.get("stall_guard") or {}
    if not isinstance(guard, Mapping):
        guard = {}
    cancelled = bool(job.get("cancel_requested")) or str(job.get("status") or "") == "cancelled"
    return bool(guard.get("run_stops")), cancelled, str(guard.get("pause_kind") or "")


def sheet_pass_state(
    catalog: AttachmentSourceCatalog | None,
    sheet: str,
    rows: Sequence[Any],
    *,
    offered_this_pass: Sequence[str] = (),
    offer_counts: Mapping[str, int] | None = None,
    deferred: Sequence[str] = (),
    unread_tail: Sequence[str] = (),
    deferred_search: Sequence[str] = (),
) -> dict[str, Any]:
    """One sheet's rows split into the states blocker § 1 demands be kept apart.

    «ещё не предложено модели», «ответ не прочитан/обрезан», «решение сохранено с
    предметным пробелом», «требуется уточнение», «отложенный дополнительный поиск»
    are five different facts about different rows.  Reporting them under the single
    «stalled» label is what let a scheduler gap be read as a professional verdict —
    and what let a finished-looking summary hide rows the model never saw.
    """

    work = catalog_sheet_work_locators(catalog, sheet) if catalog is not None else []
    settled = settled_source_keys(rows, catalog) if catalog is not None else set()
    complete = (
        structurally_complete_source_keys(rows, catalog) if catalog is not None else set()
    )
    seen = {str(item).strip() for item in offered_this_pass if str(item).strip()}
    durable = {
        str(key).strip(): max(0, int(value or 0))
        for key, value in (offer_counts or {}).items()
        if str(key).strip()
    }
    never_offered = [
        locator
        for locator in work
        if locator not in settled
        and locator not in seen
        and durable.get(locator, 0) == 0
    ]
    wanted_sheet = str(sheet or "").strip()
    clarification: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if not str(row.get("open_gap") or "").strip():
            continue
        raw = row.get("source_row")
        found = catalog.lookup(raw) if catalog is not None else None
        if found is not None and found.sheet != wanted_sheet:
            continue
        locator = str(getattr(found, "locator", "") or "") or str(raw or "").strip()
        if locator and locator not in clarification:
            clarification.append(locator)
    return {
        "schema": "les.sheet-pass-states.v1",
        "sheet": wanted_sheet,
        "work_rows": len(work),
        "decided": len([locator for locator in work if locator in settled]),
        "decided_with_gap": len([
            locator for locator in work if locator in settled and locator not in complete
        ]),
        "never_offered": len(never_offered),
        "never_offered_locators": never_offered[:80],
        "needs_clarification": len(clarification),
        "needs_clarification_locators": clarification[:80],
        "unread_tail": sorted({str(item).strip() for item in unread_tail if str(item).strip()}),
        "deferred_rows": sorted({str(item).strip() for item in deferred if str(item).strip()}),
        "deferred_search_rows": sorted(
            {str(item).strip() for item in deferred_search if str(item).strip()}
        ),
        "outstanding": len([locator for locator in work if locator not in settled]),
    }


def starved_locators(
    unfinished: Sequence[str],
    offer_counts: Mapping[str, int],
    *,
    ever_offered: Sequence[str] = (),
) -> list[str]:
    """Outstanding rows the model was never put to even once.

    Blocker file § 1: a repeated GLOBAL remainder does not prove that every row in
    it was offered on every pass — the live 823 job carried 278 outstanding rows
    with a zero offer count behind 17 rows the model had actually seen.  Closing
    such a row with «решение модели не получено после N предложений» would be a
    lie about a row that never reached the model, and declaring it would let a
    scheduler defect pass as a finished document.
    """

    seen = {
        str(key).strip().upper()
        for key, value in (offer_counts or {}).items()
        if str(key).strip() and int(value or 0) > 0
    }
    seen |= {
        str(item).strip().upper()
        for item in ever_offered
        if str(item).strip()
    }
    return [
        str(locator).strip()
        for locator in unfinished
        if str(locator).strip() and str(locator).strip().upper() not in seen
    ]


def declared_gap_rows(
    catalog: AttachmentSourceCatalog | None,
    locators: Sequence[str],
    *,
    offers: int,
    offers_by_locator: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Durable positions for source rows no model offer ever resolved.

    The application owns this bookkeeping and explicitly NOT the professional
    choice: every row keeps the source title the catalog rendered and gets an
    ``open_gap`` that says in plain Russian that the model produced no solution
    after ``offers`` offers.  No cipher, no price and no volume is invented.

    ``offers_by_locator`` is the durable per-row offer ledger.  When it is
    supplied, each closed row names how often *that row* was put to the model
    rather than the number of resumes the whole document happened to take.
    """

    from proxy.services.workbook_research_job_service import declared_gap_decision
    from proxy.services.attachment_source_catalog_service import (
        _WORK_UNITS,
        normalize_unit,
    )

    def _reason_for(offer_count: int) -> str:
        return (
            f"Решение модели не получено после {int(offer_count)} предложений; "
            "строка закрыта приложением как пробел, норма и цена не подобраны."
        )

    ledger = {
        str(key).strip().upper(): int(value or 0)
        for key, value in (offers_by_locator or {}).items()
        if str(key).strip()
    }
    rows: list[dict[str, Any]] = []
    for raw in locators:
        locator = str(raw or "").strip()
        if not locator:
            continue
        offer_count = ledger.get(locator.upper(), int(offers or 0))
        reason = _reason_for(max(1, offer_count))
        line = ""
        unit = ""
        quantity: Any = None
        classification = ""
        if catalog is not None:
            found = catalog.lookup(locator)
            if found is not None:
                line = str(found.line or "")
                quantity = found.header_quantity
                classification = str(found.row_classification or "")
                unit = next(
                    (
                        str(value).strip()
                        for value in found.values
                        if normalize_unit(value) in _WORK_UNITS
                    ),
                    "",
                )
        rows.append(
            declared_gap_decision(
                locator,
                line=line,
                unit=unit,
                quantity=quantity,
                row_classification=classification,
                reason=reason,
                attempts=max(1, offer_count),
            )
        )
    return rows


def adaptive_row_packet(
    remaining: Sequence[str],
    *,
    generation_reserve_tokens: int,
    already_offered: Sequence[str] = (),
    offer_counts: Mapping[str, int] | None = None,
) -> list[str]:
    """Bound one model result by row count and the available output budget.

    This is technical orchestration only: order and row content come unchanged
    from the exact catalog.  The model still owns queries and every decision.

    Rows are ordered by how often they have already been put to the model,
    least offered first, with the catalog position breaking ties.  A row the
    model classified but that keeps a quality gap stays in the completeness
    denominator, so a plain head slice re-sent the same leading rows on every
    packet and never reached the rows behind them; those unseen rows then ended
    the document with no decision from the model at all.  The rows offered in
    this pass alone are not enough: a sheet pass stops after a few packets, so
    the counts taken from the durable checkpoints are what keep the rotation
    going across resumes instead of restarting it at the head of the sheet.
    """

    locators = [str(item).strip() for item in remaining if str(item).strip()]
    if not locators:
        return []
    reserve = max(1, int(generation_reserve_tokens or 0))
    # Leave room for table headers and prose, then budget complete decision
    # rows including roles, links and provenance. Low-capacity backends must
    # be allowed packets smaller than eight rows.
    budget_rows = max(1, (reserve - 400) // 250)
    size = min(_ROW_PACKET_MAX, budget_rows, len(locators))
    offered = {str(item).strip() for item in already_offered if str(item).strip()}
    durable_counts = {
        str(key).strip(): max(0, int(value or 0))
        for key, value in (offer_counts or {}).items()
        if str(key).strip()
    }
    if offered or durable_counts:
        position = {locator: index for index, locator in enumerate(locators)}

        def _times_put_to_model(locator: str) -> int:
            return durable_counts.get(locator, 0) + (1 if locator in offered else 0)

        locators = sorted(
            locators,
            key=lambda locator: (_times_put_to_model(locator), position[locator]),
        )
    return locators[:size]


def row_packet_id(
    catalog: AttachmentSourceCatalog,
    *,
    sheet: str,
    locators: Sequence[str],
) -> str:
    payload = "\x1f".join(
        [catalog.source_file_id or catalog.original_name, str(sheet), *map(str, locators)]
    )
    return "packet_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


_SHIFR_RE = re.compile(r"\u0428\u0438\u0444\u0440:\s*([^\s,;]+)")


def _card_code_from_body(body: str, doc_name: str) -> str:
    match = _SHIFR_RE.search(body or "")
    return match.group(1) if match else str(doc_name or "")


def _card_code_from_chunk(chunk: Any) -> str:
    """Read a cipher in the shown legacy body or producer-owned JSON pointer.

    Metadata identifies a literal shown token; it never proves delivery of the
    card's conditions. The separate body/immutable-identity check owns that.
    """
    meta = getattr(chunk, "meta", {}) or {}
    body = str((meta.get("model_inventory_view")
                if meta.get("model_delivery_status") not in (None, "", "delivered")
                else getattr(chunk, "content", "")) or "")
    code = _card_code_from_body(body, str(getattr(chunk, "doc_name", "") or ""))
    if looks_like_cipher(code):
        return code
    declared = str(meta.get("norm_code") or "").strip()
    if looks_like_cipher(declared) and re.search(
        r"(?<![\w.-])" + re.escape(declared) + r"(?![\w.-])", body
    ):
        return declared
    return code


def row_evidence_provenance_check(
    row,
    bindings,
    alias_to_card,
    alias_to_query,
):
    """Structural citation check only: never rewrites the model's decision."""

    norm_code = str(row.get("norm_code") or "").strip()
    if not norm_code:
        return None
    cited = [
        {
            "ref": alias,
            "card": alias_to_card.get(alias, ""),
            "query": alias_to_query.get(alias, ""),
        }
        for alias in sorted(bindings)
    ]
    unresolved = sorted(
        {
            str(ref).strip().upper()
            for ref in row.get("evidence_refs") or ()
            if str(ref).strip() and str(ref).strip().upper() not in bindings
        }
    )
    # Only a cited card that carries a cipher can contradict the authored one:
    # a card body with no ``Шифр:`` line reports its document name, and a name is
    # not evidence either way.  Spellings are folded, so a space or a colon in
    # ``ГЭСН 10-01-001-05`` is not read as a different norm.
    known_ciphers = [item["card"] for item in cited if looks_like_cipher(item["card"])]
    return {
        "norm_code": norm_code,
        "cited": cited,
        "unresolved_refs": unresolved,
        "cited_ciphers": known_ciphers,
        "citation_checkable": bool(known_ciphers),
        "code_not_in_refs": bool(known_ciphers)
        and not any(ciphers_compatible(norm_code, code) for code in known_ciphers),
    }


def model_rag_budget_omitted_cards(included_hits, chunks, omitted_refs, *, query_offset=0):
    """Cards found by search but dropped by the evidence budget: name them."""

    if not omitted_refs:
        return []
    wanted = {str(ref).strip().upper() for ref in omitted_refs}
    shown = {
        str((getattr(chunk, "meta", {}) or {}).get("model_evidence_ref") or "")
        .strip()
        .upper()
        for chunk in chunks
    }
    detail = []
    for query_index, (query_text, hits) in enumerate(list(included_hits), max(0, query_offset) + 1):
        for hit_index, hit in enumerate(list(hits), 1):
            ref = f"Q{query_index}.H{hit_index}"
            if ref not in wanted or ref in shown:
                continue
            detail.append(
                {
                    "ref": ref,
                    "query": str(query_text or ""),
                    "card": _card_code_from_body(
                        str(getattr(hit, "content", "") or ""),
                        str(getattr(hit, "doc_name", "") or ""),
                    ),
                }
            )
    return detail[:300]


def model_rag_next_query_offset(evidence_chunks: Sequence[Any]) -> int:
    """Allocate new Q/H handles after saved evidence, including review cards.

    Old references remain literal. New packets cannot shadow cards that the
    model was explicitly shown as the basis for its previous decisions.
    A held page continues its persisted cursor instead of allocating again.
    """
    maximum = 0
    for chunk in evidence_chunks:
        ref = str((getattr(chunk, "meta", {}) or {}).get("model_evidence_ref") or "")
        match = re.fullmatch(r"Q(\d+)\.H\d+", ref.strip(), re.IGNORECASE)
        if match:
            maximum = max(maximum, int(match.group(1)))
    return maximum


def bind_model_requested_read_evidence(
    results: Sequence[Any], *, existing_chunks: Sequence[Any],
    evidence_namespace: str, packet_id: str = "", receipts: Sequence[dict[str, Any]] = (),
    reserved_query_end: int = 0,
) -> tuple[list[str], list[Any], list[str]]:
    """Allocate reads after saved handles and the whole declared query range."""
    groups, chunks, omitted = [], [], []
    offset = max(model_rag_next_query_offset(existing_chunks), max(0, int(reserved_query_end)))
    for index, result in enumerate(results):
        if not result.chunks:
            continue
        tool = str(result.payload.get("tool") or "read_source")
        inputs = result.payload.get("inputs") or []
        label = tool + " " + json.dumps(inputs, ensure_ascii=False, sort_keys=True)
        new_groups, new_chunks, new_omitted = build_model_rag_evidence_groups(
            [(label, result.chunks)], max_chars=2**63 - 1,
            hits_per_query=max(len(result.chunks), 1),
            evidence_namespace=evidence_namespace + ":" + str(index),
            query_offset=offset, query_provenance={label: "model"}, query_addresses={},
        )
        for chunk in new_chunks:
            chunk.meta["model_delivery_status"] = "prepared"
            chunk.meta["model_inventory_delivery_status"] = "prepared"
            chunk.meta["model_read_tool"] = tool
            chunk.meta["model_raw_body_retained"] = True
            chunk.meta["model_inventory_view"] = inventory_pointer(EvidenceCard(
                str(chunk.meta.get("model_evidence_ref") or ""), chunk.doc_name,
                normative_card_identity(chunk.meta), chunk.content, chunk.meta))
            if packet_id:
                chunk.meta["model_read_packet_id"] = packet_id
        if index < len(receipts):
            bindings = {str(chunk.meta.get("model_evidence_ref") or ""):
                        str(chunk.meta.get("global_evidence_id") or "") for chunk in new_chunks}
            receipts[index]["evidence_refs"] = [ref for ref in bindings if ref]
            receipts[index]["evidence_bindings"] = {ref: identity for ref, identity in bindings.items() if ref and identity}
            receipts[index]["model_delivery_status"] = "prepared"
        groups.extend(new_groups)
        chunks.extend(new_chunks)
        omitted.extend(new_omitted)
        offset = max(offset + 1, model_rag_next_query_offset(chunks))
    return groups, chunks, omitted


def confirm_model_read_delivery(chunks, receipts=(), *, inventory_refs=None, body_refs=None):
    """Confirm read feedback only after the provider has answered its admitted frame.

    A retrieved body stays durable and replayable when context packing fails,
    but cannot masquerade as evidence already received by the model.
    """
    inventory = set(inventory_refs) if inventory_refs is not None else None
    bodies = set(body_refs) if body_refs is not None else None
    for chunk in chunks:
        ref = str(chunk.meta.get("model_evidence_ref") or "")
        if inventory is None or ref in inventory:
            chunk.meta["model_inventory_delivery_status"] = "delivered"
        # Initial RAG cards predate the prepared/read lifecycle. Only an explicit
        # admitted body set proves that such a card was sent in this frame.
        body_was_sent = bodies is not None and ref in bodies
        if (chunk.meta.get("model_delivery_status") == "prepared" or body_was_sent) and (bodies is None or ref in bodies):
            chunk.meta["model_delivery_status"] = "delivered"
    for receipt in receipts:
        refs = set(receipt.get("evidence_refs") or ())
        if inventory is None or refs <= inventory:
            receipt["model_inventory_delivery_status"] = "delivered"
        if bodies is None or refs <= bodies:
            if receipt.get("model_delivery_status") == "prepared":
                receipt["model_delivery_status"] = "delivered"
        if bodies is not None:
            receipt["full_body_evidence_refs"] = [ref for ref in receipt.get("evidence_refs", ()) if ref in bodies]
            receipt["deferred_body_evidence_refs"] = [ref for ref in receipt.get("evidence_refs", ()) if ref not in bodies]


def bind_row_evidence_ids(
    rows: Sequence[Mapping[str, Any]],
    evidence_chunks: Sequence[Any],
) -> list[dict[str, Any]]:
    alias_to_global: dict[str, str] = {}
    alias_to_card: dict[str, str] = {}
    alias_to_query: dict[str, str] = {}
    global_to_card: dict[str, str] = {}
    global_to_query: dict[str, str] = {}
    global_to_resource_codes: dict[str, set[str]] = {}
    global_to_bodies: dict[str, str] = {}
    global_to_body_shown: dict[str, bool] = {}
    # Whole delivered RAG bodies prove their conditions, not complete typed
    # resource consumption; exact native reads expose that separate metadata.
    delivered_norm_identities: set[str] = set()
    deferred_norm_identities: dict[str, set[str]] = {}
    ambiguous_aliases: set[str] = set()
    for chunk in evidence_chunks:
        meta = getattr(chunk, "meta", {}) or {}
        if (meta.get("model_delivery_status") not in (None, "", "delivered")
                and meta.get("model_inventory_delivery_status") != "delivered"):
            continue
        alias = str(meta.get("model_evidence_ref") or "").strip().upper()
        global_id = str(meta.get("global_evidence_id") or "").strip()
        if alias and alias not in alias_to_card:
            alias_to_card[alias] = _card_code_from_chunk(chunk)
            alias_to_query[alias] = str(meta.get("model_query_text") or "")
        if alias and global_id:
            if alias in alias_to_global and alias_to_global[alias] != global_id:
                ambiguous_aliases.add(alias)
            else:
                alias_to_global[alias] = global_id
        if global_id:
            body_shown = (meta.get("model_delivery_status") in (None, "", "delivered")
                          and meta.get("body_status") != "deferred_capacity")
            norm_identity = (normative_card_identity(meta)
                             if meta.get("norm_code") or meta.get("norm_key") else global_id)
            if body_shown:
                delivered_norm_identities.add(norm_identity)
            else:
                deferred_norm_identities.setdefault(global_id, set()).add(norm_identity)
            if not body_shown and global_to_body_shown.get(global_id) is True:
                # A later index entry cannot erase an already delivered full
                # body with the same immutable identity.
                continue
            global_to_body_shown[global_id] = body_shown
            global_to_card[global_id] = _card_code_from_chunk(chunk)
            global_to_query[global_id] = str(meta.get("model_query_text") or "")
            body = str((getattr(chunk, "content", "") if body_shown else meta.get("model_inventory_view")) or "")
            global_to_bodies[global_id] = body
            resource_codes = {str(meta.get("resource_code") or "").strip()}
            for resource in [*(meta.get("resources") or []), *(meta.get("resource_preview") or [])]:
                if isinstance(resource, Mapping):
                    resource_codes.add(str(resource.get("code") or "").strip())
            # Metadata alone may describe the undisplayed tail of a preview.
            # Only literal codes actually delivered in its body prove a choice.
            global_to_resource_codes[global_id] = {
                code for code in resource_codes if code and re.search(
                    r"(?<![\w.-])" + re.escape(code) + r"(?![\w.-])", body
                )
            }
    bound: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        current = payload.get("evidence_bindings")
        merged = {
            str(alias).strip().upper(): str(global_id).strip()
            for alias, global_id in (current.items() if isinstance(current, Mapping) else ())
            if str(alias).strip() and str(global_id).strip()
        }
        for ref in payload.get("evidence_refs") or ():
            alias = str(ref).strip().upper()
            global_id = alias_to_global.get(alias, "") if alias not in ambiguous_aliases else ""
            if alias and global_id and alias not in merged:
                merged[alias] = global_id
        payload["evidence_bindings"] = merged
        # Q/H handles are packet-local. An already bound row must be checked
        # against its durable card, not the first same-named handle of another
        # packet when all sheets are collected for final packaging.
        cards = dict(alias_to_card)
        queries = dict(alias_to_query)
        checkable_bindings = dict(merged)
        for alias in ambiguous_aliases:
            cards.pop(alias, None)
            queries.pop(alias, None)
        for alias, global_id in merged.items():
            if global_id in global_to_card:
                cards[alias] = global_to_card[global_id]
                queries[alias] = global_to_query[global_id]
            else:
                cards.pop(alias, None)
                queries.pop(alias, None)
                checkable_bindings.pop(alias, None)
        evidence_check = row_evidence_provenance_check(
            payload, checkable_bindings, cards, queries
        )
        if evidence_check is not None:
            deferred_refs = [ref for ref, identity in checkable_bindings.items()
                             if identity in deferred_norm_identities]
            if deferred_refs:
                evidence_check["deferred_card_refs"] = deferred_refs
                # A full parent paragraph or a card from another edition/source
                # cannot prove that this deferred item was actually read.
                selected_deferred_ids = {
                    identity for ref in deferred_refs
                    if ciphers_identical(str(payload.get("norm_code") or ""), cards.get(ref, ""))
                    for identity in deferred_norm_identities[checkable_bindings[ref]]
                }
                if selected_deferred_ids:
                    evidence_check["card_body_shown"] = (
                        selected_deferred_ids <= delivered_norm_identities
                    )
            payload["_evidence_check"] = evidence_check
        resource_code = str(payload.get("resource_code") or "").strip()
        if resource_code:
            cited_resource_codes = sorted({
                code for identity in checkable_bindings.values()
                for code in global_to_resource_codes.get(identity, set())
            })
            payload["_resource_evidence_check"] = {
                "resource_code": resource_code,
                "cited_resource_codes": cited_resource_codes,
                "code_in_refs": resource_code in cited_resource_codes,
            }
        price_check = price_evidence_check(payload, evidence_chunks, checkable_bindings)
        if price_check is not None:
            payload["_price_evidence_check"] = price_check
        actions = payload.get("resource_bindings")
        if isinstance(actions, list):
            old_bindings = payload.get("_resource_binding_evidence_bindings")
            old_bindings = old_bindings if isinstance(old_bindings, Mapping) else {}
            action_checks, action_bindings = [], {}
            for index, action in enumerate(actions):
                if not isinstance(action, Mapping):
                    action_checks.append({"index": index, "invalid_action_object": True})
                    continue
                refs = extract_model_evidence_refs(action.get("source_refs"))
                prior = old_bindings.get(str(index))
                prior = prior if isinstance(prior, Mapping) else {}
                resolved = {}
                for ref in refs:
                    # Saved actions refer to their immutable card, never to a
                    # different packet's coincident Q/H alias.
                    identity = str(prior.get(ref) or "")
                    if not identity and ref not in ambiguous_aliases:
                        identity = alias_to_global.get(ref, "")
                    if identity in global_to_bodies:
                        resolved[ref] = identity
                action_bindings[str(index)] = resolved
                cited_ids = set(checkable_bindings.values()) | set(resolved.values())
                bodies = [global_to_bodies[identity] for identity in cited_ids
                          if identity in global_to_bodies]
                check = {"index": index, "evidence_bindings": resolved,
                         "unresolved_refs": [ref for ref in refs if ref not in resolved]}
                for field, diagnostic in (("target_resource_code", "target_code_in_refs"),
                                          ("resource_code", "resource_code_in_refs"),
                                          ("target_resource_name", "target_name_in_refs")):
                    literal = str(action.get(field) or "").strip()
                    if literal:
                        check[diagnostic] = any(re.search(
                            r"(?<![\w.-])" + re.escape(literal) + r"(?![\w.-])", body,
                            re.IGNORECASE,
                        ) is not None for body in bodies)
                if action.get("explicit_price") not in (None, ""):
                    quote = {"confirmed_price": action["explicit_price"],
                             "price_unit": action.get("unit"),
                             "price_source": action.get("price_source_ref"),
                             "evidence_refs": refs}
                    observed = price_evidence_check(quote, evidence_chunks, resolved) or {}
                    for diagnostic in ("price_in_refs", "unit_in_refs", "source_in_refs"):
                        check[diagnostic] = observed.get(diagnostic) is True
                if str(action.get("action") or "").casefold() == "reuse" and action.get("price_source_ref"):
                    # Reuse zero is authored accounting treatment, not a market
                    # quote. Validate only the cited source identity here.
                    source = str(action["price_source_ref"]).strip().casefold()
                    check["source_in_refs"] = any(
                        str((getattr(chunk, "meta", {}) or {}).get("global_evidence_id") or "") in resolved.values()
                        and source in {str(getattr(chunk, "doc_name", "") or "").strip().casefold(),
                                       str((getattr(chunk, "meta", {}) or {}).get("source_ref") or "").strip().casefold()}
                        for chunk in evidence_chunks
                    )
                action_checks.append(check)
            payload["_resource_binding_evidence_checks"] = action_checks
            payload["_resource_binding_evidence_bindings"] = action_bindings
        bound.append(payload)
    return bound


def durable_evidence_record(chunk: _ModelRagEvidenceChunk) -> dict[str, Any]:
    return {
        "global_evidence_id": str(chunk.meta.get("global_evidence_id") or ""),
        "model_evidence_ref": str(chunk.meta.get("model_evidence_ref") or ""),
        "content": chunk.content,
        "doc_id": chunk.doc_id,
        "doc_name": chunk.doc_name,
        "score": chunk.score,
        "meta": dict(chunk.meta),
    }


def evidence_chunk_from_record(record: Mapping[str, Any]) -> _ModelRagEvidenceChunk:
    meta = dict(record.get("meta") or {}) if isinstance(record.get("meta"), Mapping) else {}
    for key in ("global_evidence_id", "model_evidence_ref"):
        if record.get(key) not in (None, ""):
            meta[key] = record[key]
    return _ModelRagEvidenceChunk(
        content=str(record.get("content") or ""),
        doc_id=str(record.get("doc_id") or ""),
        doc_name=str(record.get("doc_name") or ""),
        score=float(record.get("score") or 0.0),
        meta=meta,
    )


def sheet_pass_progress_label(
    sheet: str,
    *,
    sheet_index: int,
    sheet_count: int,
    stage: str,
    resumed: bool = False,
) -> str:
    prefix = "Продолжаю: " if resumed else ""
    return f"{prefix}Лист «{sheet}» ({sheet_index}/{sheet_count}): {stage}"


_LIVE_SHEET_PASS_GATES: dict[str, asyncio.Event] = {}


async def claim_or_join_sheet_pass(job_id: str) -> bool:
    """Serialize packet loops on one research job inside this process.

    Returns True when this request owns the loop. A second Continue while the
    first is still running waits, then returns False so it does not dual-run.
    """

    key = str(job_id or "").strip()
    if not key:
        return True
    gate = _LIVE_SHEET_PASS_GATES.get(key)
    if gate is not None:
        await gate.wait()
        return False
    _LIVE_SHEET_PASS_GATES[key] = asyncio.Event()
    return True


def release_sheet_pass(job_id: str) -> None:
    """Allow the next Continue after this process-local sheet-pass ends."""

    key = str(job_id or "").strip()
    gate = _LIVE_SHEET_PASS_GATES.pop(key, None)
    if gate is not None:
        gate.set()


def sheet_pass_progress_counts(
    *,
    accepted_now: int,
    work_total: int,
    session_accepted_start: int,
    prior_elapsed_seconds: float = 0.0,
) -> dict[str, Any]:
    """Row counters for the sheet-pass bubble: display vs session ETA."""

    total = max(int(work_total or 0), 1)
    accepted = max(0, int(accepted_now or 0))
    started = max(0, int(session_accepted_start or 0))
    remaining_n = max(0, int(work_total or 0) - accepted)
    return {
        "completed": accepted,
        "total": total,
        "eta_completed": max(0, accepted - started),
        "eta_total": max(0, int(work_total or 0) - started),
        "resumed": started > 0,
        "remaining": remaining_n,
        "prior_completed": started,
        "prior_elapsed_seconds": float(prior_elapsed_seconds or 0.0),
    }


def compact_estimator_draft_rows(rows: Sequence[Any]) -> list[dict[str, Any]]:
    """Project model rows for display without inventing identity or a decision."""

    compact: list[dict[str, Any]] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        source_row = item.get("source_row")
        if source_row in (None, ""):
            continue
        row = {
            "work_id": str(source_row),
            "source_row": source_row,
            "section": str(item.get("section") or "").strip(),
            "title": str(item.get("title") or "").strip(),
            "quantity": item.get("quantity"),
            "unit": str(item.get("unit") or "").strip(),
            "norm_code": str(item.get("norm_code") or "").strip(),
        }
        for field_name in (
            "operation_id",
            "revision",
            "expected_revision",
            "base_revision",
            "analogue",
            "coverage",
            "coefficient",
            "evidence_refs",
            "evidence_bindings",
            "norm_status",
            "action_match",
            "object_match",
            "condition_match",
            "unit_compatible",
            "composition_covers",
            "_quality_gate",
            "_evidence_check",
            "_resource_evidence_check",
            "_price_evidence_check",
            "quality_message",
            "row_role",
            "work_row",
            "supply_kind",
            "open_gap",
            "conversion_factor",
            "conversion_source",
            "calc_quantity",
            "confirmed_price",
            "price_source",
            "price_kind",
            "price_unit",
            "price_currency",
            "price_vat",
            "price_period",
            "price_year",
            "price_quarter",
            "resource_code",
            "resource_bindings",
            "resource_review",
            "_resource_binding_evidence_checks",
            "_resource_binding_evidence_bindings",
            "nr_sp_rule_id",
        ):
            if field_name in item:
                row[field_name] = item[field_name]
        compact.append(row)
    return compact


_NARRATIVE_QUERY_PREFIXES = (
    "слушай ",
    "слушайте ",
    "коллега,",
    "коллега ",
    "что я делаю",
    "я сейчас ",
    "я делаю ",
    "жду подтверждения",
    "вот список",
    "сейчас сформирую",
    "это все запросы",
)
_NARRATIVE_QUERY_EXACT = {
    "ок",
    "хорошо",
    "понял",
    "готово",
    "сейчас",
    "коллега",
}
_TABULAR_TRUNCATION_MARK = "[Табличный контекст усечён"
_PASTE_TRUNCATION_MARK = "[Исходник усечён"
# ADR-16: a model-authored query keeps its historical header verbatim. Only a
# code-authored candidate group is labelled, so the model can see who put a group
# in front of it and can reject every candidate in it.
_QUERY_PROVENANCE_HEADER_LABELS = {
    "original": "(дословный исходный текст строки)",
    "derived": "(системный подбор по атрибутам этой строки)",
}
_MIN_MODEL_RAG_EVIDENCE_BODY_CHARS = 400
_LENGTH_FINISH_REASONS = {"length", "max_tokens", "length_truncated"}

# ---------------------------------------------------------------- blocker §  2
#
# The declared-query contract: one format, stated in the prompt, implemented here
# and used by the adapter, so the three cannot drift.  Nothing below grows a list
# of Russian phrases.  Whether a line of an answer is a query is a structural
# question — is it a list item, a label, or the accompanying text — and the answer
# is the same whatever model produced it, which is what «поддержать обычный
# текстовый вывод используемого провайдера» asks for.

#: Below this a stripped line is not a query but a fragment of the answer.
_MIN_DECLARED_QUERY_CHARS = 3
_BULLETED_LINE_RE = re.compile(r"^[-*+\u2013\u2014\u2022\u2192>]\s+")
#: ``1.``/``1)``/``(1)``/``1]`` may run into the text, but never into another
#: digit or a decimal separator: «2.5 мм кабеля» is a query, not item 2.
_NUMBERED_LINE_RE = re.compile(
    r"^(?:\(?\d{1,3}[.)\]](?![\d.,])\s*|\d{1,3}-\s+|№\s*\d{1,3}[:.)\s](?!\d)\s*)"
)
_HEADING_LINE_RE = re.compile(r"^#{1,6}\s+")
_BOLD_WRAPPER_RE = re.compile(r"^(?:\*\*|__)(?P<body>.+?)(?:\*\*|__)$")
_TABLE_RULE_RE = re.compile(r"^\|?[\s:|-]{2,}\|?$")
_LABEL_ONLY_RE = re.compile(r"^[^\n]{1,80}:\s*$")
_LOCATOR_TOKEN_RE = re.compile(
    r"[А-Яа-яA-Za-z][А-Яа-яA-Za-z0-9_.-]{0,24}!R\d+", re.IGNORECASE
)
#: The narrative prefixes the reader has carried since build 8xx.  Frozen on
#: purpose: it separates an accompanying answer from a query, and a line it does
#: not know is now classified structurally instead of needing a new entry.
_NARRATIVE_QUERY_PREFIXES_FROZEN = _NARRATIVE_QUERY_PREFIXES


@dataclass(frozen=True)
class DeclaredQuery:
    """One query as the model declared it: text verbatim, structure understood."""

    text: str
    marker_form: str  # "plain" | "numbered" | "bulleted" | "heading" | "wrapped"
    addresses: tuple[str, ...] = ()
    attribution: str = ""  # "address_written" | "literal_matches_row" | ""

    def as_trace_dict(self) -> dict[str, Any]:
        return {
            "query_text": self.text,
            "marker_form": self.marker_form,
            "addresses": list(self.addresses),
            "attribution": self.attribution,
        }


def _strip_declared_query_markers(line: str) -> tuple[str, str]:
    """Presentation only: list markers, emphasis and heading marks come off.

    Returns ``(text, marker_form)``.  The query wording itself is never touched —
    blocker § 2, «не переписывать профессиональный смысл запроса кодом» — and the
    marker form is reported so a reader can see which output style was used.
    """

    text = " ".join(str(line or "").split()).strip()
    form = "plain"
    for _round in range(3):
        before = text
        if _HEADING_LINE_RE.match(text):
            text = _HEADING_LINE_RE.sub("", text, count=1).strip()
            form = "heading"
            continue
        bold = _BOLD_WRAPPER_RE.match(text)
        if bold:
            text = bold.group("body").strip()
            form = "wrapped"
            continue
        numbered = _NUMBERED_LINE_RE.match(text)
        if numbered:
            text = text[numbered.end() :].strip()
            form = "numbered"
            continue
        if _BULLETED_LINE_RE.match(text):
            text = text[1:].strip()
            form = "bulleted"
            continue
        if text != before:
            continue
        break
    return text, form


# ------------------------------------------------------------------ task echo
#
# Blocker § 2: «Не дополнять бесконечно список русских префиксов.  Согласовать формат
# объявленных запросов в prompt, reader и адаптере; поддержать обычный текстовый вывод
# используемого провайдера.  Разделять запросы и сопровождающий ответ; сохранять причины
# отклонения.»  The live measure on the installed build 829 (29.09 20:51) named the one
# leg still broken: a line about the search was executed *as* a search, on this turn and
# in 3 of the 35 model-authored queries the document has ever stored.  The stored corpus
# says what those lines are — the model handing its own task back to it:
#
#   «Прочитал приложенный материал целиком. Сформуировал поисковые запросы к выбранным
#    датасетам, необходимые для подбора evidence по всем фактическим строкам…»
#
# which is the instruction this very call sent, restated in the first person past.  So
# the key is not a Russian phrase the code has to recognise — it is the task text the app
# authored, which is a closed set by construction and says nothing about how any model
# words a sentence.  The quantity is a long *contiguous* run of that text inside the
# candidate: sharing one word is ordinary language, and a two-word query is never
# rejected on it.  The thresholds are the ones the measure found (see
# ``stage_b/b2_narration_rule_measure_830.py``): at a run of 7 content words covering 45
# % of the line, 3 of the 3 stored narration cases are caught, the 51 distinct noise
# lines the reader had executed are caught, and 0 lines that name an operation or a
# cipher go with them — while the code-authored candidate label the prompt itself quotes
# («Системный подбор по атрибутам этой строки: …», longest run 5) still runs.

#: The measured boundary between "this line repeats its task" and "this line searches".
_TASK_ECHO_MIN_RUN = 7
_TASK_ECHO_MIN_SHARE = 0.45
_TASK_ECHO_STEM_CHARS = 5
_TASK_ECHO_MIN_TOKEN_CHARS = 3
_TASK_ECHO_MAX_RUN = 24
#: The task statements every query-declaration call sends, quoted from the prompt side
#: so the reader cannot be documented on one end and implemented on the other.
_TASK_ECHO_INSTRUCTIONS = (
    _MODEL_RAG_QUERY_INSTRUCTION,
    _MODEL_RAG_QUERY_FORMAT_CONTRACT,
    _MODEL_RAG_QUERY_REPAIR_INSTRUCTION,
)
_WORD_STEM_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


def task_instruction_tokens(text: str) -> list[str]:
    """Words of a line, in order, reduced to a fixed-length stem.

    Truncation rather than morphology on purpose: «Сформулируй» and the model's own
    «Сформуировал» have to fall on one token, or the rule would depend on the model
    quoting its task correctly — which the stored corpus shows it does not.
    """

    return [
        word[:_TASK_ECHO_STEM_CHARS]
        for word in _WORD_STEM_RE.findall(str(text or "").lower())
        if len(word) >= _TASK_ECHO_MIN_TOKEN_CHARS
    ]


@lru_cache(maxsize=64)
def _task_instruction_grams(texts: tuple[str, ...]) -> tuple[frozenset, ...]:
    """n-gram index of the task text, one set per run length, built once per variant."""

    layers: list[frozenset] = []
    for size in range(1, _TASK_ECHO_MAX_RUN + 1):
        index: set[tuple[str, ...]] = set()
        for text in texts:
            tokens = task_instruction_tokens(text)
            for start in range(len(tokens) - size + 1):
                index.add(tuple(tokens[start : start + size]))
        layers.append(frozenset(index))
    return tuple(layers)


def task_instruction_echo(text: str, instruction: str = "") -> tuple[int, float]:
    """Longest contiguous run of the sent task inside a line, and its share of the line."""

    tokens = task_instruction_tokens(text)
    if not tokens:
        return 0, 0.0
    texts = _TASK_ECHO_INSTRUCTIONS
    if instruction:
        texts = texts + (str(instruction),)
    layers = _task_instruction_grams(texts)
    for size in range(min(_TASK_ECHO_MAX_RUN, len(tokens)), 0, -1):
        layer = layers[size - 1]
        for start in range(len(tokens) - size + 1):
            if tuple(tokens[start : start + size]) in layer:
                return size, size / len(tokens)
    return 0, 0.0


def restates_the_task_instruction(text: str, instruction: str = "") -> bool:
    """True when the line is the task handed back rather than a question to search."""

    run, share = task_instruction_echo(text, instruction)
    return run >= _TASK_ECHO_MIN_RUN and share >= _TASK_ECHO_MIN_SHARE


def declared_query_rejection_reason(
    text: str,
    marker_form: str,
    instruction: str = "",
) -> str:
    """Why a line is the accompanying answer rather than a query; "" means query.

    Every rule is structural.  The frozen narrative list stays last so that an
    answer line it recognises is still separated — but a differently worded
    preamble no longer has to be added to it to be handled: it fails to look like
    a list item and is judged by shape.
    """

    if not text:
        return "empty_after_presentation_markers"
    if _TABLE_RULE_RE.match(text):
        return "table_rule_line"
    folded = " ".join(text.split()).casefold()
    if folded in _NARRATIVE_QUERY_EXACT:
        return "conversational_acknowledgement"
    if len(text) < _MIN_DECLARED_QUERY_CHARS:
        return "shorter_than_a_query"
    if marker_form == "heading":
        return "heading_line"
    if _LABEL_ONLY_RE.match(text):
        return "label_line_without_query"
    if restates_the_task_instruction(text, instruction):
        return "restates_the_task_instruction"
    if any(folded.startswith(prefix) for prefix in _NARRATIVE_QUERY_PREFIXES_FROZEN):
        return "narrative_answer_line"
    return ""


def declared_query_addresses(text: str) -> tuple[str, ...]:
    """Source addresses the model itself wrote into the query line."""

    return tuple(dict.fromkeys(
        match.upper() for match in _LOCATOR_TOKEN_RE.findall(str(text or ""))
    ))


def split_declared_query_tail(
    lines: Sequence[str],
    *,
    finish_reason: str = "",
) -> tuple[list[str], str]:
    """Complete lines, plus the line a cut-off answer left unread.

    ``finish_reason=length`` means the provider stopped mid-generation, so the
    last line may be truncated.  Executing it could search for half a phrase and
    reading the list as complete could leave queries unmade, so the line is taken
    out of the list, kept verbatim, and handed back to the model to finish
    (blocker § 2: «Finish_reason=length требует адресной обработки непрочитанного
    хвоста»).  An answer that ended normally keeps all of its lines.
    """

    items = [str(line or "").strip() for line in lines if str(line or "").strip()]
    if not items or not finish_reason_is_length(finish_reason):
        return items, ""
    return items[:-1], items[-1]


def read_declared_query_list(
    raw: str,
    *,
    finish_reason: str = "",
    packet_locators: Sequence[str] = (),
    row_literals: Mapping[str, str] | None = None,
    instruction: str = "",
) -> dict[str, Any]:
    """Apply the declared-query contract to one model answer.

    Returns ``queries`` (:class:`DeclaredQuery`), ``accompanying_answer``
    (``[{"line", "reason"}]`` — separated and kept, never executed, never
    discarded), ``unread_tail`` (the query a cut answer left behind) and
    ``answer_cut``.  Nothing is rewritten and nothing is invented: a line that is
    not a query stays in the record with the structural reason for that.

    ``instruction`` is the task text this answer was written for.  It is compared
    against, not parsed: a line that hands that task back is the accompanying
    answer (blocker § 2), and the caller that sent the prompt is the only place
    that knows what it said.
    """

    wanted = {str(item).strip().upper() for item in packet_locators if str(item).strip()}
    literals = {
        str(locator).strip().upper(): " ".join(str(text or "").casefold().split())
        for locator, text in (row_literals or {}).items()
        if str(locator or "").strip()
    }
    complete_lines, unread_tail = split_declared_query_tail(
        _unwrap_model_rag_query_lines(raw), finish_reason=finish_reason
    )
    queries: list[DeclaredQuery] = []
    accompanying: list[dict[str, str]] = []
    for line in complete_lines:
        text, marker_form = _strip_declared_query_markers(line)
        reason = declared_query_rejection_reason(text, marker_form, instruction)
        if reason:
            accompanying.append({"line": text or line.strip(), "reason": reason})
            continue
        written = declared_query_addresses(text)
        attribution = ""
        if written:
            # The model's own pointer is kept verbatim even when it names a row
            # outside this packet: an address the packet does not contain is a
            # fact to measure, not a reason to rewrite the query.
            attribution = (
                "address_written"
                if not wanted or all(item in wanted for item in written)
                else "address_outside_packet"
            )
        elif literals:
            folded = " ".join(text.casefold().split())
            matched = sorted(
                locator
                for locator, literal in literals.items()
                if literal and (literal in folded or folded in literal)
            )
            if matched:
                attribution = "literal_matches_row"
                known = [item for item in matched if not wanted or item in wanted]
                written = tuple(known or matched)
        folded_text = " ".join(text.casefold().split())
        if any(
            " ".join(item.text.casefold().split()) == folded_text for item in queries
        ):
            continue
        queries.append(
            DeclaredQuery(
                text=text,
                marker_form=marker_form,
                addresses=written,
                attribution=attribution,
            )
        )
    return {
        "schema": "les.declared-query-list.v1",
        "queries": queries,
        "accompanying_answer": accompanying,
        "unread_tail": unread_tail,
        "answer_cut": bool(finish_reason_is_length(finish_reason)),
        "finish_reason": str(finish_reason or ""),
    }


def declared_query_continuation_instruction(
    received: Sequence[str],
    unread_tail: str,
) -> str:
    """Ask for exactly the unread remainder — not for a fresh list.

    The already-received queries are named so the model does not repeat them, and
    the cut line is quoted verbatim so the model finishes the query it was
    writing instead of answering a different question.
    """

    already = "; ".join(str(item) for item in list(received)[-40:]) or "нет"
    return (
        "Предыдущий список поисковых запросов оборван на середине строки. "
        f"Оборванная строка: «{unread_tail or '—'}». "
        f"Уже получены запросы: {already}. "
        "Допиши оборванную строку и верни только оставшиеся поисковые запросы "
        "к датасетам, каждый с новой строки. Не повторяй уже полученные запросы, "
        "не перефразируй их и не выбирай нормы."
    )


def declared_query_trace(declared: Mapping[str, Any]) -> dict[str, Any]:
    """Serializable form of one declared-query answer for the durable trace."""

    payload = dict(declared or {})
    return {
        "schema": "les.declared-query-list.v1",
        "queries": [
            item.as_trace_dict() if isinstance(item, DeclaredQuery) else dict(item)
            for item in (payload.get("queries") or [])
        ],
        "accompanying_answer": list(payload.get("accompanying_answer") or []),
        "unread_tail": str(payload.get("unread_tail") or ""),
        "answer_cut": bool(payload.get("answer_cut")),
        "finish_reason": str(payload.get("finish_reason") or ""),
    }


def _matched_before_cap(hits: Sequence[Any]) -> int:
    """Pool size the search reported, carried on the served cards' own meta.

    Zero means the figure did not reach this reader — a record cached before the
    figure existed, or a query that matched nothing so no card carried it — and
    ``found_basis`` says which, instead of quietly presenting the ceiling as the
    corpus or an unreported pool as a small one.
    """

    matched = 0
    for hit in hits:
        meta = getattr(hit, "meta", None)
        if meta is None and isinstance(hit, Mapping):
            meta = hit.get("meta")
        value = (meta or {}).get(_MATCHED_BEFORE_CAP_META_KEY) if isinstance(meta, Mapping) else None
        if isinstance(value, (int, float)) and int(value) > matched:
            matched = int(value)
    return matched


def model_rag_query_measurement(
    *,
    declared_queries: Sequence[Mapping[str, Any]] = (),
    query_provenance: Mapping[str, str] | None = None,
    query_addresses: Mapping[str, Sequence[str]] | None = None,
    pass_hits: Sequence[tuple[str, Sequence[Any]]],
    leftover_query_hits: Sequence[tuple[str, Sequence[Any]]] = (),
    evidence_chunks: Sequence[Any] = (),
    omitted_refs: Sequence[str] = (),
    kept_rows: Sequence[Mapping[str, Any]] = (),
    query_offset: int = 0,
) -> dict[str, Any]:
    """Per-query found / shown / deferred / chosen for ONE packet, kept apart.

    Blocker § 2 (29.09) forbids comparing an aggregate ``found`` across packets
    with the ``model_visible`` of one later call as if it were one loss, so this
    measures a single packet: every executed query gets its own row, the four
    numbers never collapse into a single figure, and the group roll-up sums each
    of them separately per provenance.  Nothing here judges a norm — a query with
    no visible card is a retrieval fact, not «нет нормы».

    «Найдено» is the pool the search matched, which the evidence cap then trims:
    counting the trimmed list would make found and shown the same number for
    every query (the 824/826/827 measurements all read ``found = 6``).  So the
    row carries ``returned_within_cap`` next to ``found``, and ``found_basis``
    names which of the two the figure is.
    """

    def folded(text: Any) -> str:
        return " ".join(str(text or "").casefold().split())

    declared_by_text = {
        folded(item.get("query_text")): dict(item)
        for item in declared_queries
        if folded(item.get("query_text"))
    }
    alias_to_query: dict[str, str] = {}
    shown_by_query: dict[str, int] = {}
    for chunk in evidence_chunks:
        meta = getattr(chunk, "meta", {}) or {}
        query_key = folded(meta.get("model_query_text"))
        if not query_key:
            continue
        shown_by_query[query_key] = shown_by_query.get(query_key, 0) + 1
        alias = str(meta.get("model_evidence_ref") or "").strip().upper()
        if alias and alias not in alias_to_query:
            alias_to_query[alias] = query_key
    chosen_by_query: dict[str, int] = {}
    for row in kept_rows:
        counted: set[str] = set()
        for ref in row.get("evidence_refs") or ():
            query_key = alias_to_query.get(str(ref).strip().upper(), "")
            if query_key and query_key not in counted:
                counted.add(query_key)
                chosen_by_query[query_key] = chosen_by_query.get(query_key, 0) + 1
    deferred_wholly = {folded(query) for query, _hits in leftover_query_hits}
    omitted_by_query: dict[str, int] = {}
    for ref in omitted_refs or ():
        alias = str(ref).strip().upper()
        query_key = alias_to_query.get(alias, "")
        if not query_key:
            match = re.match(r"^Q(\d+)(?:\.H\d+)?$", alias)
            if match:
                index = int(match.group(1)) - max(0, query_offset)
                if 0 < index <= len(pass_hits):
                    query_key = folded(pass_hits[index - 1][0])
        if query_key:
            omitted_by_query[query_key] = omitted_by_query.get(query_key, 0) + 1

    rows: list[dict[str, Any]] = []
    groups: dict[str, dict[str, int]] = {}
    for raw_query, raw_hits in pass_hits:
        query = str(raw_query or "").strip()
        query_key = folded(query)
        provenance = _model_rag_query_provenance(query_provenance, query)
        hits = list(raw_hits or ())
        returned = len(hits)
        matched = _matched_before_cap(hits)
        found = matched if matched >= returned else returned
        if matched > returned:
            basis = "pre_cap_pool"
        elif matched > 0:
            basis = "pool_within_cap"
        else:
            basis = "pool_not_reported"
        shown = shown_by_query.get(query_key, 0)
        row = {
            "query_text": query,
            "query_provenance": provenance,
            "addresses": list(query_addresses.get(query, ()))
            if query_addresses
            else list(declared_by_text.get(query_key, {}).get("addresses") or ()),
            "attribution": str(
                declared_by_text.get(query_key, {}).get("attribution") or ""
            ),
            "found": found,
            "found_basis": basis,
            "returned_within_cap": returned,
            "model_visible": shown,
            "not_visible": max(0, found - shown),
            "deferred_wholly": query_key in deferred_wholly,
            "cards_omitted": omitted_by_query.get(query_key, 0),
            "chosen_rows": chosen_by_query.get(query_key, 0),
        }
        rows.append(row)
        group = groups.setdefault(
            provenance,
            {"queries": 0, "found": 0, "returned_within_cap": 0, "model_visible": 0,
             "not_visible": 0, "chosen_rows": 0, "found_from_pre_cap_queries": 0},
        )
        group["queries"] += 1
        if row["found_basis"] == "pre_cap_pool":
            group["found_from_pre_cap_queries"] += 1
        for key in (
            "found",
            "returned_within_cap",
            "model_visible",
            "not_visible",
            "chosen_rows",
        ):
            group[key] += int(row[key])
    return {
        "schema": "les.query-measurement.v1",
        "queries": rows,
        "groups": groups,
        "compares_only_within_this_packet": True,
    }


def declared_query_attempt_plan(
    *,
    declared: Mapping[str, Any],
    already_declared: Sequence[str],
    phase: str,
    attempts_remaining: int,
) -> tuple[str, str]:
    """Decide the next query call from one declared answer, or stop.

    Two and only two follow-ups exist, which is what keeps a cut list from
    turning into an unbounded retry loop (blocker § 1: «увеличение времени/попыток
    само по себе не исправление»):

      * ``continuation`` — the answer stopped mid-line at ``finish_reason=length``,
        so exactly that unread line is asked for, once;
      * ``repair`` — nothing at all was declared, so the format contract is
        restated, once.

    A tail is never chased twice and a declared list is never re-asked, so a model
    that answered is never prompted again for the same answer.
    """

    if attempts_remaining <= 0:
        return "", ""
    unread_tail = str(declared.get("unread_tail") or "")
    if unread_tail and phase != "continuation":
        return (
            "continuation",
            declared_query_continuation_instruction(already_declared, unread_tail),
        )
    if not already_declared and phase != "repair":
        return "repair", _MODEL_RAG_QUERY_REPAIR_INSTRUCTION
    return "", ""


def rejected_reason_counts(
    rejected: Sequence[Mapping[str, str]],
) -> dict[str, int]:
    """How many lines were separated for each structural reason.

    The count is the answer to «сохранять причины отклонения»: a reader can see
    that the model wrote prose, not that it declared nothing, without any of the
    rejected lines being discarded.
    """

    counts: dict[str, int] = {}
    for row in rejected:
        reason = str((row or {}).get("reason") or "unspecified")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def merge_query_measurement(
    rollup: dict[str, Any],
    measurement: Mapping[str, Any],
) -> dict[str, Any]:
    """Add one packet's separate counts to a sheet/run roll-up, number by number.

    A packet count is carried alongside the sums because blocker § 2 rules out
    reading a multi-packet ``found`` against one packet's ``model_visible`` as a
    single loss: the roll-up stays a per-packet average-friendly structure, and
    every figure keeps its own name.
    """

    packets = int(rollup.get("packets") or 0) + 1
    rollup["packets"] = packets
    groups = rollup.setdefault("groups", {})
    summed = (
        "queries",
        "found",
        "returned_within_cap",
        "model_visible",
        "not_visible",
        "chosen_rows",
        "found_from_pre_cap_queries",
    )
    for provenance, counters in (measurement.get("groups") or {}).items():
        group = groups.setdefault(
            str(provenance),
            {"queries": 0, "found": 0, "returned_within_cap": 0, "model_visible": 0,
             "not_visible": 0, "chosen_rows": 0, "found_from_pre_cap_queries": 0},
        )
        for key in summed:
            group[key] += int(counters.get(key) or 0)
    rollup["deferred_wholly_queries"] = int(
        rollup.get("deferred_wholly_queries") or 0
    ) + sum(1 for row in measurement.get("queries") or () if row.get("deferred_wholly"))
    rollup["cards_omitted"] = int(rollup.get("cards_omitted") or 0) + sum(
        int(row.get("cards_omitted") or 0) for row in measurement.get("queries") or ()
    )
    return rollup


def _unwrap_model_rag_query_lines(raw: str) -> list[str]:
    """Strip fences and explicit wrappers; do not invent replacement queries."""

    plain_lines = [line.strip() for line in str(raw or "").splitlines()]
    fence_indexes = [
        index for index, line in enumerate(plain_lines) if line.startswith("```")
    ]
    if len(fence_indexes) >= 2:
        plain_lines = plain_lines[fence_indexes[0] + 1 : fence_indexes[-1]]
    visible_lines = [
        line for line in plain_lines if line and not line.startswith("```")
    ]
    if any(line.startswith(("{", "[")) or line.endswith(("}", "]")) for line in visible_lines):
        return []
    explicitly_wrapped: list[str] = []
    for line in visible_lines:
        if len(line) >= 2 and line[0] == line[-1] and line[0] in {'"', "'"}:
            explicitly_wrapped.append(line[1:-1].strip())
            continue
        prefix = "search_sources"
        if not line.startswith(prefix):
            continue
        remainder = line[len(prefix) :].strip()
        if remainder.startswith("(") and remainder.endswith(")"):
            remainder = remainder[1:-1].strip()
        if (
            len(remainder) >= 2
            and remainder[0] == remainder[-1]
            and remainder[0] in {'"', "'"}
        ):
            explicitly_wrapped.append(remainder[1:-1].strip())
    raw_queries = explicitly_wrapped or visible_lines
    queries: list[str] = []
    for item in raw_queries:
        if not isinstance(item, str):
            continue
        query = item.strip()
        if query:
            queries.append(query)
    return queries


def is_model_rag_search_query_line(line: str, instruction: str = "") -> bool:
    """One line of a declared-query answer: query, or accompanying text.

    Delegated to the same structural rules :func:`read_declared_query_list` uses,
    so the historical helper and the contract cannot disagree about a line.
    """

    text, marker_form = _strip_declared_query_markers(line)
    return not declared_query_rejection_reason(text, marker_form, instruction)


def classify_model_rag_query_lines(
    raw: str,
    instruction: str = "",
    *, finish_reason: str = "",
) -> tuple[list[str], list[str]]:
    """Split an answer into executable queries and the accompanying answer text.

    The rejected half keeps its structural reason in
    :func:`read_declared_query_list`; this pair-shaped view stays for callers that
    only need the texts.
    """

    declared = read_declared_query_list(raw, instruction=instruction, finish_reason=finish_reason)
    return (
        [item.text for item in declared["queries"]],
        [str(row.get("line") or "") for row in declared["accompanying_answer"]],
    )


def parse_model_rag_queries(raw: str) -> list[str]:
    """Return the model-authored search lines without presentation wrappers or narrative."""

    accepted, _rejected = classify_model_rag_query_lines(raw)
    return accepted


def read_model_query_response(raw: str, **kwargs) -> dict:
    """Adapt an explicit query envelope to the unchanged literal query reader."""
    envelope = decode_model_query_envelope(raw)
    declaration = decode_model_artifact_kind(raw)
    query_text = "\n".join(envelope["queries"]) if envelope is not None else raw
    declared = read_declared_query_list(query_text, **kwargs)
    declared["artifact_kind_declaration"] = declaration
    declared["intentional_empty"] = bool(envelope is not None and not envelope["queries"]
        and declaration.get("status") == "declared" and declaration.get("artifact_kind") == "vor")
    return declared


_MODEL_EVIDENCE_REF = re.compile(r"^Q(\d+)\.H(\d+)$", re.IGNORECASE)


def extract_model_evidence_refs(value: Any) -> list[str]:
    """Keep only real Qn.Hm handles. Prose notes are not evidence."""

    if isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes)):
        texts = [str(item or "") for item in value]
    else:
        texts = [str(value or "")]
    found: list[str] = []
    for text in texts:
        separated = text.replace("<br>", " ").replace("<br/>", " ")
        for marker in "[](),;":
            separated = separated.replace(marker, " ")
        for token in separated.split():
            candidate = token.strip(".*_`:").upper()
            if _MODEL_EVIDENCE_REF.fullmatch(candidate):
                found.append(candidate)
    return list(dict.fromkeys(found))


def unresolved_evidence_placeholder(value: Any) -> bool:
    marker = " ".join(str(value or "").casefold().replace("ё", "е").split())
    return "qx.hy" in marker or "отсутствует в выдаче" in marker


def parse_model_rag_result(
    raw: str, *, diagnostics: list[dict[str, Any]] | None = None,
) -> tuple[str, list[dict[str, Any]]] | None:
    """Decode only an unambiguous table; preserve the authored answer and cell values."""

    required_fields = {"title", "unit", "norm_code"}
    transport_diagnostics: list[dict[str, Any]] = []
    from proxy.services.model_lsr_result_contract import (
        decode_model_result_rows, decode_model_resource_field,
    )
    json_rows = decode_model_result_rows(raw, diagnostics=transport_diagnostics)
    if diagnostics is not None:
        diagnostics.extend(transport_diagnostics)
    resource_fields = {"resource_bindings", "resource_review"}
    numeric_fields = {
        "revision",
        "expected_revision",
        "base_revision",
        "quantity",
        "coefficient",
        "conversion_factor",
        "calc_quantity",
        "confirmed_price",
    }
    header_fields = {
        "operation_id": "operation_id",
        "revision": "revision",
        "expected_revision": "expected_revision",
        "base_revision": "base_revision",
        "source_row": "source_row",
        "№": "source_row",
        "№ п/п": "source_row",
        "№ пп": "source_row",
        "section": "section",
        "раздел": "section",
        "title": "title",
        "title (наименование)": "title",
        "title (описание оборудования из комментариев)": "title",
        "наименование": "title",
        "наименование работ": "title",
        "наименование работ (из вор)": "title",
        "наименование работы": "title",
        "unit": "unit",
        "ед. изм.": "unit",
        "ед. изм": "unit",
        "ед изм": "unit",
        "ед": "unit",
        "единица": "unit",
        "quantity": "quantity",
        "кол-во": "quantity",
        "кол.": "quantity",
        "кол": "quantity",
        "количество": "quantity",
        "row_role": "row_role",
        "роль": "row_role",
        "роль строки": "row_role",
        "work_row": "work_row",
        "строка работы": "work_row",
        "supply_kind": "supply_kind",
        "вид поставки": "supply_kind",
        "open_gap": "open_gap",
        "открытый вопрос": "open_gap",
        "gap_reason": "gap_reason",
        "причина пробела": "gap_reason",
        "conversion_factor": "conversion_factor",
        "коэффициент перевода": "conversion_factor",
        "conversion_source": "conversion_source",
        "источник перевода": "conversion_source",
        "calc_quantity": "calc_quantity",
        "расчётное количество": "calc_quantity",
        "confirmed_price": "confirmed_price",
        "resource_code": "resource_code",
        "resource_bindings": "resource_bindings",
        "resource_review": "resource_review",
        "подтверждённая цена": "confirmed_price",
        "price_source": "price_source",
        "price_kind": "price_kind",
        "price_unit": "price_unit",
        "price_currency": "price_currency",
        "price_vat": "price_vat",
        "price_period": "price_period",
        "price_year": "price_year",
        "price_quarter": "price_quarter",
        "источник цены": "price_source",
        "nr_sp_rule_id": "nr_sp_rule_id",
        "norm_code": "norm_code",
        "norm_code (выбранная норма)": "norm_code",
        "norm_code (возможная норма монтажа)": "norm_code",
        "norm_code (шифр)": "norm_code",
        "нормативная база (шифр нормы)": "norm_code",
        "нормативная база (norm code)": "norm_code",
        "нормативный код (гэсн/ер)": "norm_code",
        "шифр нормы": "norm_code",
        "шифр": "norm_code",
        "выбранная норма": "norm_code",
        "код нормы": "norm_code",
        "гэсн": "norm_code",
        "позиция": "source_row",
        "строка": "source_row",
        "locator": "source_row",
        "код строки": "source_row",
        "analogue": "analogue",
        "analogue / coverage": "analogue",
        "analogue / coverage (обоснование/аналог)": "analogue",
        "analogue / coverage (обоснование)": "analogue",
        "аналог/обоснование": "analogue",
        "обоснование выбора и аналог": "analogue",
        "coverage": "coverage",
        "coverage (соответствие)": "coverage",
        "примечание инженера": "coverage",
        "примечание": "coverage_fallback",
        "примечания к составу работ": "coverage",
        "примечания к выбору": "coverage",
        "norm_status": "norm_status",
        "статус нормы": "norm_status",
        "verdict": "norm_status",
        "action_match": "action_match",
        "object_match": "object_match",
        "condition_match": "condition_match",
        "unit_compatible": "unit_compatible",
        "composition_covers": "composition_covers",
        "extra_ops": "extra_ops",
        "missing_ops": "missing_ops",
        "contradictions": "contradictions",
        "coefficient": "coefficient",
        "coefficient (кэф.)": "coefficient",
        "коэфф.": "coefficient",
        "coefficient_applies_to": "coefficient_applies_to",
        "norm_components": "norm_components",
        "evidence_refs": "evidence_refs",
        "evidence_refs (источник)": "evidence_refs",
    }

    def field_name(value: str) -> str:
        normalized = " ".join(value.replace("**", "").strip().split()).casefold()
        return header_fields.get(normalized, "")

    if json_rows is not None:
        # Same public field boundary as the visible table/text readers. A model
        # cannot author application trust flags or operator confirmations.
        public_rows = []
        for row in json_rows:
            mapped = [(field_name(str(key)), value) for key, value in row.items()
                      if field_name(str(key))]
            names = [key for key, _value in mapped]
            duplicate_aliases = [key for key in dict.fromkeys(names) if names.count(key) > 1]
            if duplicate_aliases:
                decision = {"raw_proposal": row}
                source_values = [value for key, value in mapped if key == "source_row"]
                if len(source_values) == 1:
                    decision["source_row"] = source_values[0]
                proposal = {"code": "MODEL_RESULT_JSON_DUPLICATE_FIELD_ALIAS",
                            "reason": "duplicate_json_field_alias", "fields": duplicate_aliases,
                            "decision": decision}
                transport_diagnostics.append(proposal)
                if diagnostics is not None:
                    diagnostics.append(proposal)
                continue
            public = {}
            for key, value in row.items():
                canonical = field_name(str(key))
                if canonical:
                    public[canonical] = value
            if isinstance(public.get("evidence_refs"), str):
                public["evidence_refs"] = extract_model_evidence_refs(public["evidence_refs"])
            for key in resource_fields & public.keys():
                public[key] = decode_model_resource_field(public[key])
            public_rows.append(public)
        return str(raw or ""), public_rows

    if transport_diagnostics:
        return str(raw or ""), []

    # Table lines are read through one shared contract (task § 3): the model's own
    # presentation — a pipe-opened line, a line opened without the optional outer
    # pipes, or a line carrying the mandated [Источник N] mark glued in front of it
    # — is the same table.  Cells come back verbatim; nothing here decides what a
    # cell means.
    def cells(line: str, *, strip_trailing_boundary: bool = True) -> list[str]:
        payload = table_line(line)
        if not payload:
            return []
        if payload.startswith("|"):
            payload = payload[1:]
        # Only an unescaped final pipe is the optional outer delimiter.
        if strip_trailing_boundary and payload.endswith("|"):
            slash_count = len(payload[:-1]) - len(payload[:-1].rstrip("\\"))
            if slash_count % 2 == 0:
                payload = payload[:-1]
        result, current = [], []
        index = 0
        while index < len(payload):
            character = payload[index]
            if character == "\\" and index + 1 < len(payload):
                following = payload[index + 1]
                if following == "|":
                    current.append("|")
                    index += 2
                    continue
                if following == "\\":
                    current.extend((character, following))
                    index += 2
                    continue
            if character == "|":
                result.append("".join(current).strip())
                current = []
            else:
                current.append(character)
            index += 1
        result.append("".join(current).strip())
        return result

    def number(value: str) -> int | float | None:
        normalized = value.replace("\u00a0", "").replace(" ", "").replace(",", ".")
        if not normalized:
            return None
        try:
            parsed = float(normalized)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else parsed

    def source_row_identity(value: str) -> int | str | None:
        authored = value.strip()
        if not authored:
            return None
        parsed = number(authored)
        return parsed if isinstance(parsed, int) else authored

    def absence_marker(value: str) -> bool:
        marker = value.strip().strip("*_` ").strip()
        if len(marker) >= 2 and (marker[0], marker[-1]) in {
            ("(", ")"),
            ("[", "]"),
        }:
            marker = marker[1:-1].strip()
        return marker.casefold() in {
            "—",
            "-",
            "–",
            "−",
            "нет",
            "н/д",
            "n/a",
            "na",
        }

    def divider_cell(value: str) -> bool:
        return is_divider_cell(value)

    def evidence_refs(value: str) -> list[str]:
        return extract_model_evidence_refs(value)

    def trimmed_field_errors(values: Sequence[str], names: Sequence[str]) -> list[str]:
        """Check literal types before accepting a surplus-empty presentation.

        Removing a final blank could otherwise hide an extra internal cell.
        These checks never derive a missing value or a professional verdict.
        """
        from proxy.services.lsr_source_coverage_service import (
            canonicalize_row_role, canonicalize_supply_kind,
        )

        match_names = {"action_match", "object_match", "condition_match",
                       "unit_compatible", "composition_covers"}
        match_tokens = {"yes", "true", "1", "совпало", "совпадает", "да",
                        "no", "false", "0", "не совпало", "нет", "unknown",
                        "неясно", "н/д", "n/a", "na", "—", "-", "–", "−"}
        errors = []
        for name, value in zip(names, values, strict=True):
            token = value.strip().strip("*_` ").strip()
            if len(token) >= 2 and (token[0], token[-1]) in {("(", ")"), ("[", "]")}:
                token = token[1:-1].strip()
            token = " ".join(token.strip(".,;:").casefold().replace("ё", "е").split())
            if not token:
                continue
            valid = True
            if name in match_names:
                valid = token in match_tokens
            elif name == "row_role":
                valid = bool(canonicalize_row_role(token))
            elif name == "supply_kind":
                valid = bool(canonicalize_supply_kind(token)) or absence_marker(token)
            elif name in numeric_fields:
                valid = absence_marker(token) or token in {"none", "null", "unknown"}
                if not valid:
                    parsed = number(token)
                    if parsed is None and name in {"coefficient", "conversion_factor"}:
                        numerator_text, separator, denominator_text = token.partition("/")
                        numerator, denominator = number(numerator_text), number(denominator_text)
                        if separator and numerator is not None and denominator not in {None, 0}:
                            parsed = numerator / denominator
                    valid = parsed is not None and parsed == parsed and abs(parsed) != float("inf")
            if not valid:
                errors.append(name)
        return errors

    lines = str(raw or "").splitlines()
    table_rows: list[dict[str, Any]] = []
    current_section = ""
    header_index = 0
    while header_index < len(lines):
        stripped_line = lines[header_index].strip()
        if stripped_line.startswith("### ") and stripped_line[4:].casefold().startswith(
            "раздел "
        ):
            current_section = stripped_line[4:].strip()
            header_index += 1
            continue
        header = cells(lines[header_index])
        header_has_trailing_boundary = table_line(lines[header_index]).endswith("|")
        mapped_header = [field_name(item) for item in header]
        # A display ordinal is not a second source locator when the model
        # explicitly supplies source_row. Keep the explicit identity verbatim.
        normalized_header = [
            " ".join(item.replace("**", "").strip().split()).casefold()
            for item in header
        ]
        if "source_row" in normalized_header:
            mapped_header = [
                "" if label in {"№", "№ п/п", "№ пп"} else field
                for label, field in zip(normalized_header, mapped_header, strict=True)
            ]
        if "coverage_fallback" in mapped_header:
            fallback_name = "" if "coverage" in mapped_header else "coverage"
            mapped_header = [
                fallback_name if item == "coverage_fallback" else item
                for item in mapped_header
            ]
        if (
            not header
            or not required_fields.issubset(set(mapped_header))
            or len([item for item in mapped_header if item])
            != len(set(item for item in mapped_header if item))
        ):
            header_index += 1
            continue
        if header_index + 1 >= len(lines):
            break
        divider = cells(lines[header_index + 1])
        while len(divider) > len(header) and divider and divider_cell(divider[-1]):
            divider = divider[:-1]
        # Divider cells are presentation, not the schema. Models sometimes emit
        # one fewer separator than labelled columns; the header still provides
        # the unambiguous mapping for every actual row.
        if not divider or not all(divider_cell(item) for item in divider):
            header_index += 1
            continue
        table_section = current_section
        row_index = header_index + 2
        while row_index < len(lines):
            values = cells(lines[row_index], strip_trailing_boundary=header_has_trailing_boundary)
            if not values:
                break
            if len(values) < len(header) - 1 and not opens_as_table(lines[row_index]):
                # A prose line may contain a pipe without being a model row.
                break
            if len(values) != len(header):
                authored_values = list(values)
                # Extra empty cells after every named value do not change the
                # mapping. Never remove an internal cell or an absence marker.
                while len(values) > len(header) and values[-1] == "":
                    values.pop()
                field_errors = (trimmed_field_errors(values, mapped_header)
                                if len(values) == len(header) else [])
                if len(values) != len(header) or field_errors:
                    proposal = {
                        "code": "MODEL_RESULT_TABLE_ROW_WIDTH_MISMATCH",
                        "reason": ("ambiguous_markdown_row_field_types" if field_errors
                                   else "ambiguous_markdown_row_width"),
                        "line_number": row_index + 1,
                        "expected_cells": len(header),
                        "actual_cells": len(authored_values),
                        "decision": {"raw_line": lines[row_index],
                                     "raw_cells": authored_values,
                                     "table_header": list(header)},
                    }
                    if field_errors:
                        proposal["structural_field_errors"] = field_errors
                    if mapped_header and mapped_header[0] == "source_row" and authored_values:
                        proposal["decision"]["source_row"] = authored_values[0]
                    transport_diagnostics.append(proposal)
                    if diagnostics is not None:
                        diagnostics.append(proposal)
                    row_index += 1
                    continue
            visible_values = [value.replace("**", "").strip() for value in values]
            if visible_values[0].casefold().startswith("раздел") and not any(
                visible_values[1:]
            ):
                table_section = visible_values[0]
                row_index += 1
                continue
            raw_row = {
                name: value
                for name, value in zip(mapped_header, visible_values, strict=True)
                if name
            }
            row: dict[str, Any] = {}
            for name, value in raw_row.items():
                if not value:
                    continue
                if name == "source_row":
                    parsed_source_row = source_row_identity(value)
                    if parsed_source_row is None:
                        # One broken locator must not erase the rest of the table.
                        row.clear()
                        break
                    row[name] = parsed_source_row
                elif name in numeric_fields:
                    numeric_value = value.strip()
                    if absence_marker(numeric_value):
                        continue
                    parsed_number: int | float | None = None
                    if name == "coefficient" and "/" in numeric_value:
                        numerator_text, separator, denominator_text = numeric_value.partition("/")
                        numerator = number(numerator_text)
                        denominator = number(denominator_text)
                        if separator and numerator is not None and denominator not in {None, 0}:
                            parsed_number = numerator / denominator
                    else:
                        parsed_number = number(numeric_value)
                    if parsed_number is None:
                        # Preserve the authored cell. Numeric validation belongs
                        # to calculation; one bad cell must not erase other rows.
                        row[name] = value
                        continue
                    row[name] = parsed_number
                elif name == "evidence_refs":
                    refs = evidence_refs(value)
                    if not refs and unresolved_evidence_placeholder(value):
                        refs = [value.strip()]
                    if refs:
                        row[name] = refs
                elif name in resource_fields:
                    row[name] = decode_model_resource_field(value)
                elif name:
                    row[name] = value
            embedded_refs = evidence_refs(" ".join(visible_values))
            if embedded_refs and not row.get("evidence_refs"):
                row["evidence_refs"] = embedded_refs
            if row:
                if table_section and not row.get("section"):
                    row["section"] = table_section
                table_rows.append(row)
            row_index += 1
        header_index = max(row_index, header_index + 1)
    block_fields = {
        "operation_id": "operation_id",
        "revision": "revision",
        "expected_revision": "expected_revision",
        "base_revision": "base_revision",
        "source_row": "source_row",
        "section": "section",
        "title": "title",
        "unit": "unit",
        "quantity": "quantity",
        "row_role": "row_role",
        "work_row": "work_row",
        "supply_kind": "supply_kind",
        "open_gap": "open_gap",
        "открытый вопрос": "open_gap",
        "gap_reason": "gap_reason",
        "причина пробела": "gap_reason",
        "conversion_factor": "conversion_factor",
        "conversion_source": "conversion_source",
        "calc_quantity": "calc_quantity",
        "confirmed_price": "confirmed_price",
        "resource_code": "resource_code",
        "resource_bindings": "resource_bindings",
        "resource_review": "resource_review",
        "price_source": "price_source",
        "price_kind": "price_kind",
        "price_unit": "price_unit",
        "price_currency": "price_currency",
        "price_vat": "price_vat",
        "price_period": "price_period",
        "price_year": "price_year",
        "price_quarter": "price_quarter",
        "norm_code": "norm_code",
        "nr_sp_rule_id": "nr_sp_rule_id",
        "analogue": "analogue",
        "coverage": "coverage",
        "norm_status": "norm_status",
        "action_match": "action_match",
        "object_match": "object_match",
        "condition_match": "condition_match",
        "unit_compatible": "unit_compatible",
        "composition_covers": "composition_covers",
        "extra_ops": "extra_ops",
        "missing_ops": "missing_ops",
        "contradictions": "contradictions",
        "coefficient": "coefficient",
        "coefficient_applies_to": "coefficient_applies_to",
        "evidence_refs": "evidence_refs",
    }
    # A model can present the same explicit fields on one line instead of in
    # Markdown cells. Read field delimiters, never infer a decision from prose.
    # This preserves the live 831 answers that named source_row/title/unit/code
    # but were silently lost because their presentation was `key=value`.
    inline_rows: list[dict[str, Any]] = []
    for line in lines:
        authored = line.strip()
        prefix, colon, rest = authored.partition(":")
        payload = authored if authored.startswith("source_row=") else rest.strip()
        if not payload.startswith("source_row="):
            continue
        boundaries = [(0, "source_row", len("source_row="))]
        top_level = set()
        depth, quoted, escaped = 0, False, False
        for offset, character in enumerate(payload):
            if depth == 0 and not quoted:
                top_level.add(offset)
            if escaped:
                escaped = False
            elif quoted and character == "\\":
                escaped = True
            elif character == '"':
                quoted = not quoted
            elif not quoted and character in "[{":
                depth += 1
            elif not quoted and character in "]}":
                depth = max(0, depth - 1)
        for label in block_fields:
            for separator in (", ", "; "):
                marker = separator + label + "="
                start = 0
                while (at := payload.find(marker, start)) >= 0:
                    if at in top_level:
                        boundaries.append((at, block_fields[label], at + len(marker)))
                    start = at + len(marker)
        boundaries.sort()
        if len({key for _, key, _ in boundaries}) != len(boundaries):
            continue  # duplicate field labels make interpretation ambiguous
        inline: dict[str, Any] = {}
        for index, (_at, key, value_at) in enumerate(boundaries):
            end = boundaries[index + 1][0] if index + 1 < len(boundaries) else len(payload)
            value = payload[value_at:end].strip()
            if key == "source_row":
                inline[key] = source_row_identity(value)
            elif key in numeric_fields:
                inline[key] = number(value) if number(value) is not None else value
            elif key == "evidence_refs":
                inline[key] = evidence_refs(value)
            elif key in resource_fields:
                inline[key] = decode_model_resource_field(value)
            else:
                inline[key] = value
        if not required_fields.issubset(inline) or not inline.get("source_row"):
            continue
        if not authored.startswith("source_row=") and (not colon or prefix.strip() != str(inline["source_row"])):
            continue  # a conflicting prefix is not a second locator to guess
        if not inline.get("evidence_refs"):
            refs = evidence_refs(payload)
            if refs:
                inline["evidence_refs"] = refs
        inline_rows.append(inline)
    if table_rows or inline_rows:
        return str(raw or ""), [*table_rows, *inline_rows]

    block_rows: list[dict[str, Any]] = []
    current_block: dict[str, Any] | None = None
    invalid_block = False

    def flush_block() -> None:
        nonlocal current_block, invalid_block
        if current_block is None:
            return
        if not required_fields.issubset(current_block) or current_block.get(
            "source_row"
        ) in (None, ""):
            invalid_block = True
        else:
            block_rows.append(current_block)
        current_block = None

    for line in lines:
        stripped = line.strip()
        heading = stripped.strip("*_`# ")
        heading_parts = heading.split()
        explicit_heading_row: int | None = None
        heading_row_token = (
            heading_parts[1].rstrip(":") if len(heading_parts) >= 2 else ""
        )
        is_block_heading = (
            len(heading_parts) >= 2
            and heading_parts[0].casefold() == "строка"
            and heading_row_token.isdigit()
        )
        if is_block_heading and len(heading_parts) > 2:
            heading_suffix = " ".join(heading_parts[2:]).strip()
            if heading_parts[1].endswith(":"):
                pass
            elif heading_suffix.startswith("(") and heading_suffix.endswith(")"):
                identity_label, identity_delimiter, identity_value = heading_suffix[
                    1:-1
                ].partition("=")
                if (
                    identity_delimiter
                    and identity_label.strip().casefold() == "source_row"
                    and identity_value.strip().isdigit()
                ):
                    explicit_heading_row = int(identity_value.strip())
                else:
                    is_block_heading = False
            else:
                is_block_heading = False
        if is_block_heading:
            flush_block()
            current_block = (
                {"source_row": explicit_heading_row}
                if explicit_heading_row is not None
                else {}
            )
            continue
        labelled = stripped.lstrip("*-+ ").strip()
        label, delimiter, value = labelled.partition(":")
        if not delimiter:
            continue
        key = block_fields.get(label.strip().strip("*_` ").casefold())
        if key == "source_row" and current_block is not None and required_fields.issubset(current_block):
            flush_block()
        if current_block is None and key in {"source_row", "operation_id"}:
            current_block = {}
        if current_block is None:
            continue
        clean = value.strip().lstrip("*_` ").strip()
        if not key or not clean:
            continue
        if key == "source_row":
            parsed_source_row = source_row_identity(clean)
            if parsed_source_row is None:
                invalid_block = True
                continue
            current_block[key] = parsed_source_row
        elif key in numeric_fields:
            if clean.casefold() in {
                "—", "-", "–", "−", "нет", "н/д", "n/a", "na",
            }:
                continue
            parsed_number = number(clean)
            if parsed_number is None and key == "coefficient":
                first_token = clean.split(maxsplit=1)[0].rstrip(".,;")
                parsed_number = number(first_token)
            if parsed_number is None:
                current_block[key] = clean
                continue
            current_block[key] = parsed_number
        elif key == "evidence_refs":
            refs = evidence_refs(clean)
            if refs:
                current_block[key] = refs
        elif key in resource_fields:
            current_block[key] = decode_model_resource_field(clean)
        else:
            current_block[key] = clean
    flush_block()
    if block_rows and not invalid_block:
        return str(raw or ""), block_rows

    labelled_fields = {
        "operation_id": "operation_id",
        "revision": "revision",
        "expected_revision": "expected_revision",
        "base_revision": "base_revision",
        "раздел": "section",
        "ед. изм.": "unit",
        "ед. изм": "unit",
        "единица": "unit",
        "unit": "unit",
        "количество": "quantity",
        "кол-во": "quantity",
        "quantity": "quantity",
        "row_role": "row_role",
        "work_row": "work_row",
        "supply_kind": "supply_kind",
        "open_gap": "open_gap",
        "открытый вопрос": "open_gap",
        "gap_reason": "gap_reason",
        "причина пробела": "gap_reason",
        "conversion_factor": "conversion_factor",
        "conversion_source": "conversion_source",
        "calc_quantity": "calc_quantity",
        "confirmed_price": "confirmed_price",
        "resource_code": "resource_code",
        "price_source": "price_source",
        "price_kind": "price_kind",
        "price_unit": "price_unit",
        "price_currency": "price_currency",
        "price_vat": "price_vat",
        "price_period": "price_period",
        "price_year": "price_year",
        "price_quarter": "price_quarter",
        "norm_code": "norm_code",
        "шифр нормы": "norm_code",
        "nr_sp_rule_id": "nr_sp_rule_id",
        "аналог": "analogue",
        "обоснование": "coverage",
        "coverage": "coverage",
        "коэффициент": "coefficient",
        "coefficient": "coefficient",
        "coefficient_applies_to": "coefficient_applies_to",
        "evidence": "evidence_refs",
        "evidence_refs": "evidence_refs",
    }
    labelled_rows: list[dict[str, Any]] = []
    for line in lines:
        stripped = line.strip()
        separator = next(
            (candidate for candidate in (" — ", " – ", " - ") if candidate in stripped),
            "",
        )
        if not separator:
            continue
        identity, remainder = stripped.split(separator, 1)
        identity_parts = identity.split()
        if (
            len(identity_parts) != 2
            or identity_parts[0].casefold() != "строка"
            or not identity_parts[1].isdigit()
        ):
            continue
        segments = remainder.split(";")
        title = segments[0].strip()
        if not title:
            return None
        row: dict[str, Any] = {
            "source_row": int(identity_parts[1]),
            "title": title,
        }
        for segment in segments[1:]:
            label, delimiter, value = segment.partition(":")
            if not delimiter:
                continue
            key = labelled_fields.get(" ".join(label.strip().split()).casefold())
            clean = value.strip()
            if not key or not clean:
                continue
            if key in numeric_fields:
                parsed_number = number(clean)
                if parsed_number is None:
                    row[key] = clean
                    continue
                row[key] = parsed_number
            elif key == "evidence_refs":
                refs = evidence_refs(clean)
                if refs:
                    row[key] = refs
            else:
                row[key] = clean
        if not required_fields.issubset(row):
            return None
        labelled_rows.append(row)
    if labelled_rows:
        return str(raw or ""), labelled_rows
    if transport_diagnostics:
        return str(raw or ""), []
    return None


@dataclass(frozen=True)
class _ModelRagEvidenceChunk:
    """One model-visible RAG hit with its query/hit coordinate preserved."""

    content: str
    doc_id: str
    doc_name: str
    score: float
    meta: dict[str, Any]


def model_rag_group_char_budget(
    *,
    context_chars_limit: int,
    remaining_group_tokens: int,
) -> int:
    """Char ceiling for Q/H headers: leftover tokens at 2 chars/token, capped by context."""

    remaining_chars = max(0, int(remaining_group_tokens)) * 2
    limit = max(0, int(context_chars_limit))
    if not remaining_chars:
        return 0
    if not limit:
        return remaining_chars
    return min(limit, remaining_chars)


def _model_rag_capped_hits(raw_hits: Sequence[Any], hits_per_query: int) -> list[Any]:
    return list(raw_hits)[: max(1, int(hits_per_query))]


def _query_address_list(
    query_addresses: Mapping[str, Sequence[str]] | None,
    query: str,
) -> tuple[str, ...]:
    """The source addresses this query was declared against, if any.

    Looked up on the same case-folded key :func:`_model_rag_query_provenance`
    uses, so a query cannot be attributed to one row in the header and to another
    in the budget calculation.
    """

    if not query_addresses:
        return ()
    folded = " ".join(str(query or "").casefold().split())
    for key, value in query_addresses.items():
        if " ".join(str(key or "").casefold().split()) == folded:
            return tuple(str(item) for item in (value or ()) if str(item or "").strip())
    return ()


def _model_rag_query_header(
    query_index: int,
    query: str,
    provenance: str = "model",
    addresses: Sequence[str] = (),
) -> str:
    text = str(query or "").strip()
    label = _QUERY_PROVENANCE_HEADER_LABELS.get(
        str(provenance or "model").strip().casefold(), ""
    )
    base = f"[Поисковый запрос Q{query_index}] {text}"
    # Blocker § 2: a query states which source rows it answers for.  Only
    # addresses the model itself wrote are rendered — a row the code matched by
    # text similarity stays in the trace, because telling the model "this query is
    # about АР!R7" would be the code steering the search it is meant to judge.
    known = [str(item).strip() for item in (addresses or ()) if str(item or "").strip()]
    if known:
        base += " [строки: " + ", ".join(known) + "]"
    return f"{base} {label}" if label else base


def _model_rag_query_provenance(
    query_provenance: Mapping[str, str] | None,
    query: str,
) -> str:
    """Provenance of one query text; an untagged query stays a model query.

    ADR-16 makes a missing tag visible rather than silently re-routing it: the
    estimator sheet-pass tags every query it executes, so an untagged entry can
    only come from an ordinary (non-estimate) turn, where the model is still the
    only author.
    """

    if not query_provenance:
        return "model"
    folded = " ".join(str(query or "").casefold().split())
    for key, value in query_provenance.items():
        if " ".join(str(key or "").casefold().split()) == folded:
            return str(value or "model")
    return "model"


def _model_only_query_provenance(
    query_hits: Sequence[Any],
) -> dict[str, str]:
    """Tag every query of a model-only turn as ``model`` (ADR-16 gate rule).

    ``QUERY_PROVENANCE_MISSING`` requires an evidence-builder callsite to state
    provenance rather than rely on the default.  On a turn where the model is the
    only author, this map is that statement: an untagged query cannot reach the
    rendered evidence on any path.
    """

    provenance: dict[str, str] = {}
    for item in query_hits:
        query = item[0] if isinstance(item, tuple) and item else item
        text = str(query or "").strip()
        if text:
            provenance.setdefault(text, "model")
    return provenance


async def _execute_system_candidate_queries(
    *,
    catalog: AttachmentSourceCatalog | None,
    sheet: str,
    packet: Sequence[str],
    profile_snapshot: Mapping[str, Any] | None,
    comparative_variant: str,
    model_research_tools: Any,
    model_queries: Sequence[str],
    pass_hits: list[tuple[str, Sequence[Any]]],
    pass_tools: list[dict[str, Any]],
    sheet_query_cache: dict[str, Any],
    cache_updates: dict[str, list[dict[str, Any]]],
    query_provenance: dict[str, str],
    retrieval_trace: dict[str, Any],
    hits_per_query: int,
    query_addresses: dict[str, list[str]] | None = None,
) -> int:
    """Append the ADR-16 code-authored candidate groups after the model's own.

    Scope is deliberately narrow: the estimator path only, never inside the
    ``B0_DIRECT`` live-comparison baseline, and never before the model has had
    its own queries executed.  Every query is tagged with its provenance, so a
    missing tag is impossible on this path rather than defaulted.

    ``query_addresses`` (optional) additionally records which source row a
    code-authored candidate was built from — the candidate knows its own locator,
    so the model can see the operation a query stands for instead of guessing it
    from the wording.  Without the map the attribution still reaches the trace
    through ``executed[].source_row``; only the rendered header omits it.
    """

    for query in model_queries:
        query_provenance.setdefault(str(query), "model")
    trace = retrieval_trace.setdefault("system_candidate_queries", {})
    trace.setdefault("sheets", {})
    if comparative_variant == "B0_DIRECT":
        trace["status"] = "skipped_baseline"
        return 0
    if not candidate_queries_enabled_for_turn(profile_snapshot):
        return 0
    built_report: dict[str, Any] = {}
    built = candidate_queries_for_packet(
        catalog, sheet=sheet, locators=list(packet), report=built_report
    )
    candidates = merge_candidate_queries(
        [str(query) for query in model_queries]
        + [str(query) for query, _hits in pass_hits],
        built,
    )
    dropped = dropped_ungrounded_queries(built)
    added = 0
    executed: list[dict[str, Any]] = []
    blocked = ""
    for index, candidate in enumerate(candidates):
        query = candidate.text
        cached = restore_query_hits_from_cache(
            [query], sheet_query_cache,
            cache_contract=str(getattr(model_research_tools, "cache_contract", "") or ""))
        if cached:
            hits = cached[0][1]
            pass_tools.append(
                {
                    "schema": "les_tool_result_v1",
                    "tool": "search_sources",
                    "status": "ok" if hits else "missing",
                    "result": {"count": len(hits), "cached": True},
                }
            )
        else:
            research_result = await model_research_tools.execute(
                {"tool": "search_sources", "args": {"q": query}}
            )
            payload = research_result.payload
            pass_tools.append(payload)
            if model_search_result_blocks_packet(payload):
                blocked = str(payload.get("status") or "")
                # ADR-16 § 6: a stopped search is an interruption.  The queries
                # it never reached stay recorded as deferred candidates, so no
                # later reader can take them for «норма отсутствует».
                built_report["deferred_by_search_block"] = [
                    item.text for item in list(candidates)[index:]
                ]
                break
            hits = tuple(research_result.chunks)[: max(1, int(hits_per_query))]
            records = [durable_research_hit(item) for item in hits]
            cache_updates[str(query)] = records
        pass_hits.append((query, hits))
        query_provenance[query] = candidate.provenance
        if query_addresses is not None and str(candidate.locator or "").strip():
            known_addresses = query_addresses.setdefault(str(query), [])
            if candidate.locator not in known_addresses:
                known_addresses.append(str(candidate.locator))
        executed.append(candidate.as_trace_dict())
        added += 1
    sheet_trace = trace["sheets"].setdefault(
        str(sheet),
        {"queries_authored_by_code": 0, "executed": [], "dropped_ungrounded": [],
         "deferred": {}},
    )
    # Packets of one sheet run in sequence, so every packet's facts have to add
    # up: overwriting per sheet left only the last packet visible and made the
    # earlier candidate sets untraceable.
    sheet_trace["queries_authored_by_code"] = (
        int(sheet_trace.get("queries_authored_by_code") or 0) + added
    )
    sheet_trace["executed"] = list(sheet_trace.get("executed") or []) + executed
    sheet_trace["dropped_ungrounded"] = (
        list(sheet_trace.get("dropped_ungrounded") or []) + dropped
    )
    deferred = sheet_trace.setdefault("deferred", {})
    for key in (
        "skipped_without_source_text",
        "deferred_by_cap",
        "deferred_by_char_budget",
        "deferred_by_search_block",
        "not_in_source_catalog",
    ):
        items = built_report.get(key) or []
        if items:
            deferred[key] = sorted({*(deferred.get(key) or []), *map(str, items)})
    if built_report.get("limit_reached"):
        deferred["cap"] = built_report.get("cap")
    # The source-text filter reports per packet, so its counters have to add up
    # across a sheet: blocker § 2 asks what a row's text left out, and a total
    # taken from the last packet would understate every earlier one.
    filter_now = built_report.get("source_text_filter")
    if isinstance(filter_now, Mapping):
        filter_trace = sheet_trace.setdefault("source_text_filter", {})
        for key, value in filter_now.items():
            filter_trace[key] = int(filter_trace.get(key) or 0) + int(value or 0)
        filter_trace["packets"] = int(filter_trace.get("packets") or 0) + 1
        filter_trace["char_budget"] = int(built_report.get("char_budget") or 0)
        filter_trace["chars_used_last_packet"] = int(built_report.get("chars_used") or 0)
    if blocked:
        sheet_trace["search_blocked"] = blocked
    return added


def _model_rag_source_header(query_index: int, hit_index: int, hit: Any) -> str:
    doc_name = str(getattr(hit, "doc_name", "") or "")
    score = float(getattr(hit, "score", 0.0) or 0.0)
    return f"[Q{query_index}.H{hit_index} | {doc_name} | score={score:.4f}]"


def model_rag_evidence_header_chars(
    query_hits: Sequence[tuple[str, Sequence[Any]]],
    *,
    hits_per_query: int,
    query_offset: int = 0,
    query_provenance: Mapping[str, str] | None = None,
    query_addresses: Mapping[str, Sequence[str]] | None = None,
) -> int:
    """Character tax of query and hit headers, matching grouped evidence layout."""

    fixed_chars = 0
    segment_count = 0
    cap = max(1, int(hits_per_query))
    for query_index, (raw_query, raw_hits) in enumerate(
        query_hits, max(0, query_offset) + 1
    ):
        fixed_chars += len(
            _model_rag_query_header(
                query_index,
                str(raw_query or ""),
                _model_rag_query_provenance(query_provenance, raw_query),
                _query_address_list(query_addresses, raw_query),
            )
        )
        segment_count += 1
        for hit_index, hit in enumerate(list(raw_hits)[:cap], 1):
            fixed_chars += len(_model_rag_source_header(query_index, hit_index, hit)) + 2
            segment_count += 1
    return fixed_chars + max(0, segment_count - 1) * 2


def model_rag_query_hit_refs(
    query_hits: Sequence[tuple[str, Sequence[Any]]],
    *,
    hits_per_query: int,
    query_offset: int = 0,
) -> list[str]:
    """Stable Q/H ids for queries that stay intact for a later packet or honest omit."""

    refs: list[str] = []
    cap = max(1, int(hits_per_query))
    for query_index, (_query, raw_hits) in enumerate(
        query_hits, max(0, query_offset) + 1
    ):
        refs.append(f"Q{query_index}")
        for hit_index, _hit in enumerate(list(raw_hits)[:cap], 1):
            refs.append(f"Q{query_index}.H{hit_index}")
    return refs


def select_model_rag_query_hits_for_budget(
    query_hits: Sequence[tuple[str, Sequence[Any]]],
    *,
    max_chars: int,
    hits_per_query: int,
    query_offset: int = 0,
    query_provenance: Mapping[str, str] | None = None,
    query_addresses: Mapping[str, Sequence[str]] | None = None,
    require_card_bodies: bool = False,
) -> tuple[
    list[tuple[str, Sequence[Any]]],
    list[tuple[str, Sequence[Any]]],
    list[str],
]:
    """Prefix whose evidence fits; leftover queries stay whole for the next packet.

    Technical orchestration only: query text and hit order are unchanged. If even
    the first query's hit headers exceed the budget, keep the query identity and
    drop trailing hit headers of that query. An empty budget omits this packet
    rather than raising.
    """

    items = [
        (str(query or "").strip(), tuple(_model_rag_capped_hits(hits, hits_per_query)))
        for query, hits in query_hits
    ]
    if not items:
        return [], [], []
    if max_chars <= 0:
        return [], items, []
    if require_card_bodies:
        groups, _ = _model_rag_full_groups(
            items, hits_per_query=hits_per_query, query_offset=query_offset,
            query_provenance=query_provenance, query_addresses=query_addresses,
        )
        page = plan_full_group_page(groups, max_chars)
        return items[:page.included_count], items[page.included_count:], []

    taken = 0
    for count in range(1, len(items) + 1):
        tax = model_rag_evidence_header_chars(
            items[:count],
            hits_per_query=hits_per_query,
            query_offset=query_offset,
            query_provenance=query_provenance,
            query_addresses=query_addresses,
        )
        if require_card_bodies:
            first_refs: dict[str, str] = {}
            for qi, (_query, hits) in enumerate(items[:count], max(0, query_offset) + 1):
                for hi, hit in enumerate(hits, 1):
                    key = _model_rag_exact_card_key(hit)
                    if key in first_refs:
                        tax += len(_model_rag_shared_body_ref(first_refs[key]))
                    else:
                        first_refs[key] = f"Q{qi}.H{hi}"
                        tax += _model_rag_required_body_chars(hit, _MIN_MODEL_RAG_EVIDENCE_BODY_CHARS)
        if tax <= max_chars:
            taken = count
            continue
        break
    if taken:
        return items[:taken], items[taken:], []
    if require_card_bodies:
        # No professional verdict can be based on headers alone. Preserve the
        # entire query for a visible capacity pause, not a silent no-data answer.
        return [], items, []

    query, hits = items[0]
    query_index = max(0, query_offset) + 1
    kept_hits = list(hits)
    omitted_refs: list[str] = []
    while kept_hits:
        trial = [(query, tuple(kept_hits))]
        if (
            model_rag_evidence_header_chars(
                trial,
                hits_per_query=hits_per_query,
                query_offset=query_offset,
                query_provenance=query_provenance,
                query_addresses=query_addresses,
            )
            <= max_chars
        ):
            break
        kept_hits.pop()
        omitted_refs.append(f"Q{query_index}.H{len(kept_hits) + 1}")
    if not kept_hits:
        omitted_refs = [
            f"Q{query_index}.H{hit_index}" for hit_index in range(1, len(hits) + 1)
        ]
    return [(query, tuple(kept_hits))], items[1:], omitted_refs


def _model_rag_required_body_chars(hit: Any, minimum: int) -> int:
    body = str(getattr(hit, "content", "") or "").strip()
    prefix = (getattr(hit, "meta", {}) or {}).get("minimum_evidence_body_chars")
    floor = prefix + 1 if isinstance(prefix, int) and not isinstance(prefix, bool) and prefix > 0 else 0
    return min(len(body), max(0, minimum, floor))


def _model_rag_exact_card_key(hit: Any) -> str:
    """Share byte-equivalent evidence only; keep distinct source/edition/scope."""
    meta = getattr(hit, "meta", {}) or {}
    identity = {
        "body": str(getattr(hit, "content", "") or ""),
        "doc_id": str(getattr(hit, "doc_id", "") or ""),
        "doc_name": str(getattr(hit, "doc_name", "") or ""),
        "provenance": {key: meta.get(key) for key in (
            "source_ref", "chunk_id", "source_locator", "source_sha256", "norm_code",
            "norm_key", "dataset_id", "page", "sheet", "row", "edition", "base_type",
            "nr_sp_candidates", "resource_preview", "resource_count", "resource_kinds",
            "work_steps", "minimum_evidence_body_chars", "resource_code", "pricebook",
            "pricebook_sha256", "price_evidence",
        )},
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _model_rag_shared_body_ref(ref: str) -> str:
    return f"То же содержимое и источник, что у {ref}; см. показанный там текст."


def model_rag_pending_result_packets(held_packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Keep unresolved authored transport cursors apart from the active packet."""
    candidates = list(held_packet.get("pending_model_result_packets") or ())
    if held_packet.get("model_result_transport_pending"):
        candidates.append(held_packet)
    packets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping) or not candidate.get("model_result_transport_pending"):
            continue
        packet = {key: value for key, value in candidate.items()
                  if key not in {"pending_model_result_packets", "terminal_packets", "reopened_locators"}}
        marker = json.dumps(packet, ensure_ascii=False, sort_keys=True)
        if marker not in seen:
            seen.add(marker)
            packets.append(packet)
    return packets


def model_rag_with_pending_results(
    held_packet: Mapping[str, Any], pending_packets: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    payload = dict(held_packet)
    if pending_packets:
        payload["pending_model_result_packets"] = [dict(packet) for packet in pending_packets]
    else:
        payload.pop("pending_model_result_packets", None)
    return payload


def model_rag_pending_result_targets(packet: Mapping[str, Any]) -> set[str]:
    locators = set(map(str, packet.get("locators") or ()))
    targets: set[str] = set()
    for diagnostic in packet.get("transport_diagnostics") or ():
        source = str((diagnostic.get("decision") or {}).get("source_row") or "")
        targets.update({source} if source in locators else locators)
    return targets or locators


def model_rag_pending_result_projection(packets: Sequence[Mapping[str, Any]]) -> tuple[set[str], list[dict[str, Any]]]:
    locators: set[str] = set()
    diagnostics: list[dict[str, Any]] = []
    for packet in packets:
        resolved = set(map(str, packet.get("resolved_source_rows") or ()))
        locators.update(model_rag_pending_result_targets(packet) - resolved)
        for diagnostic in packet.get("transport_diagnostics") or ():
            source = str((diagnostic.get("decision") or {}).get("source_row") or "")
            if source not in resolved and diagnostic not in diagnostics:
                diagnostics.append(dict(diagnostic))
    return locators, diagnostics


def model_rag_resolve_pending_results(
    packets: Sequence[Mapping[str, Any]], resolved_source_rows: set[str],
) -> list[dict[str, Any]]:
    pending = []
    for packet in packets:
        resolved = set(map(str, packet.get("resolved_source_rows") or ()))
        resolved.update(resolved_source_rows & set(map(str, packet.get("locators") or ())))
        if model_rag_pending_result_targets(packet) <= resolved:
            continue
        payload = dict(packet)
        if resolved:
            payload["resolved_source_rows"] = sorted(resolved)
        pending.append(payload)
    return pending


def model_rag_evidence_page_state(
    *, sheet: str, packet: Sequence[str],
    leftover_query_hits: Sequence[tuple[str, Sequence[Any]]], query_offset: int,
    query_provenance: Mapping[str, str], query_addresses: Mapping[str, Sequence[str]],
    pending_result_packets: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Durable transport cursor, independent of the model's professional verdict."""
    queries = [str(query) for query, _hits in leftover_query_hits if str(query).strip()]
    if not queries:
        return model_rag_with_pending_results({}, pending_result_packets)
    return model_rag_with_pending_results({
        "sheet": sheet, "locators": list(packet), "queries": queries,
        "query_offset": query_offset,
        "query_provenance": {q: query_provenance.get(q, "model") for q in queries},
        "query_addresses": {q: list(query_addresses.get(q, ())) for q in queries},
    }, pending_result_packets)


def model_rag_prior_page_context(
    rows: Sequence[Mapping[str, Any]], evidence_chunks: Sequence[Any],
    *, review_rows: Sequence[Mapping[str, Any]] = (), review_instruction: str = "",
    source_catalog: AttachmentSourceCatalog | None = None,
) -> tuple[dict[str, Any], list[Any]]:
    """Replay authored rows and exactly their cited cards; never choose a norm."""
    rows = model_rag_existing_operation_rows(rows, review_rows)
    structural_facts = []
    # Recompute observations from immutable cards/source, not saved diagnostics.
    # These are facts for the existing model turn, never replacement decisions.
    observation_rows = [{key: value for key, value in row.items()
                         if key not in {"_evidence_check", "_resource_evidence_check", "_price_evidence_check"}}
                        for row in rows]
    for row in bind_row_evidence_ids(observation_rows, evidence_chunks):
        fact = {"source_row": row.get("source_row"),
                "operation_id": row.get("operation_id")}
        check = row.get("_evidence_check")
        if isinstance(check, Mapping):
            fact["norm_reference"] = {
                "selected_code": check["norm_code"],
                "cited_ciphers": check["cited_ciphers"],
                "code_in_refs": (not check["code_not_in_refs"]
                                 if check["citation_checkable"] else None),
                "unresolved_refs": check["unresolved_refs"],
            }
        resource_check = row.get("_resource_evidence_check")
        if isinstance(resource_check, Mapping):
            fact["resource_reference"] = dict(resource_check)
        price_check = row.get("_price_evidence_check")
        if isinstance(price_check, Mapping):
            fact["price_reference"] = dict(price_check)
        if source_catalog is not None:
            errors = compare_model_row_to_catalog(row, source_catalog)
            if errors:
                source = source_catalog.lookup(row.get("source_row"))
                fact["source_comparison"] = {
                    "errors": errors,
                    "quantity_column_known": source.quantity_column_known if source else False,
                    "source_quantity": source.header_quantity if source else None,
                    "source_unit": header_bound_unit(source) if source else None,
                    "model_quantity": row.get("quantity"),
                    "model_unit": row.get("unit"),
                }
        if any(key in fact for key in ("norm_reference", "resource_reference", "price_reference", "source_comparison")):
            structural_facts.append(fact)
    cited = {
        str(identity) for row in rows
        for identity in (row.get("evidence_bindings") or {}).values()
    }
    for row in rows:
        nested_bindings = row.get("_resource_binding_evidence_bindings")
        if isinstance(nested_bindings, Mapping):
            for bindings in nested_bindings.values():
                if isinstance(bindings, Mapping):
                    cited.update(str(identity) for identity in bindings.values())
    retained = []
    seen = set()
    for chunk in evidence_chunks:
        identity = str((getattr(chunk, "meta", {}) or {}).get("global_evidence_id") or "")
        if identity in cited and identity not in seen:
            retained.append(chunk)
            seen.add(identity)
    first_cards: dict[str, str] = {}
    cited_evidence = []
    for chunk in retained:
        ref = (chunk.meta or {}).get("model_evidence_ref")
        identity = (chunk.meta or {}).get("global_evidence_id")
        owner = first_cards.setdefault(_model_rag_exact_card_key(chunk), identity)
        cited_evidence.append({
            "ref": ref,
            "global_evidence_id": identity,
            "content": chunk.content if owner == identity else _model_rag_shared_body_ref(f"global_evidence_id={owner}"),
        })
    return {
        **({"review_instruction": review_instruction} if review_instruction else {}),
        # These diagnostics are application-derived projections of the same
        # authored fields/citations, not additional model choices. Repeating
        # their full citation dumps crowded out the next exact evidence group.
        "prior_model_decisions": [
            {key: value for key, value in row.items()
             if key not in {"_quality_gate", "_evidence_check", "_resource_evidence_check", "_price_evidence_check", "_resource_binding_evidence_checks", "_resource_binding_evidence_bindings", "quality_message"}}
            for row in compact_estimator_draft_rows(list(rows))
        ],
        "previously_shown_cited_evidence": cited_evidence,
        "prior_result_structural_facts": structural_facts,
        "evidence_continuation_instruction": (
            "Это следующая страница уже найденных карточек для тех же строк. "
            "Сохрани корректные прежние решения и их цитаты; учитывай новые карточки. "
            "Для изменённой прежней операции верни её operation_id из prior_model_decisions "
            "и expected_revision, равный показанному revision; "
            "для новой оставь operation_id пустым: идентификаторы и ревизии назначает приложение. "
            "work_row остаётся адресом исходной строки работы. "
            "prior_result_structural_facts содержит только сравнение с буквальными "
            "карточками и исходными ячейками, не вердикт о применимости нормы. "
            "code_in_refs=null означает, что сравнить шифр невозможно. "
            "Проверь указанные противоречия; предметные решения принимаешь ты. "
            + ("При явном пересмотре верни все предложенные прежние операции этого пакета, включая неизменённые. "
               "Неизменённые предметные поля и цитаты скопируй дословно; сохрани operation_id "
               "и укажи expected_revision из показанного revision. Пропущенные операции не возвращаются "
               "в текущий документ автоматически. " if review_rows else
               "Верни только новые и изменённые операции этого пакета. Неизменённые "
               "операции и цитаты остаются в документе. ")
            + "Код не изменял предметные решения."
        ),
    }, retained


def _model_rag_full_groups(
    query_hits, *, hits_per_query, query_offset=0,
    query_provenance=None, query_addresses=None,
):
    groups, hits = [], {}
    for qi, (raw_query, raw_hits) in enumerate(query_hits, max(0, query_offset) + 1):
        query = str(raw_query or "").strip()
        provenance = _model_rag_query_provenance(query_provenance, query)
        addresses = _query_address_list(query_addresses, query)
        cards = []
        for hi, hit in enumerate(_model_rag_capped_hits(raw_hits, hits_per_query), 1):
            ref = f"Q{qi}.H{hi}"
            meta = dict(getattr(hit, "meta", {}) or {})
            meta.setdefault("doc_id", str(getattr(hit, "doc_id", "") or ""))
            meta.setdefault("doc_name", str(getattr(hit, "doc_name", "") or ""))
            cards.append(EvidenceCard(ref, _model_rag_source_header(qi, hi, hit),
                                      _model_rag_exact_card_key(hit),
                                      str(getattr(hit, "content", "") or ""), meta))
            hits[ref] = (qi, hi, query, provenance, addresses, hit)
        groups.append(EvidenceGroup(_model_rag_query_header(qi, query, provenance, addresses), cards))
    return groups, hits


def build_model_rag_evidence_groups(
    query_hits: Sequence[tuple[str, Sequence[Any]]],
    *,
    max_chars: int,
    hits_per_query: int,
    min_body_chars: int = _MIN_MODEL_RAG_EVIDENCE_BODY_CHARS,
    evidence_namespace: str = "",
    query_offset: int = 0,
    query_provenance: Mapping[str, str] | None = None,
    query_addresses: Mapping[str, Sequence[str]] | None = None,
) -> tuple[list[str], list[_ModelRagEvidenceChunk], list[str]]:
    """Show literal identities first; full bodies are indivisible capacity units."""
    groups, hits = _model_rag_full_groups(
        query_hits, hits_per_query=hits_per_query, query_offset=query_offset,
        query_provenance=query_provenance, query_addresses=query_addresses,
    )
    page = plan_full_group_page(groups, max_chars)
    chunks = []
    full = set(page.body_refs)
    for source_index, alias in enumerate(page.inventory_refs, 1):
        qi, hi, query, provenance, addresses, hit = hits[alias]
        body_shown = alias in full
        content = page.body_by_ref[alias] if body_shown else page.pointer_by_ref[alias]
        meta = dict(getattr(hit, "meta", {}) or {})
        meta.setdefault("doc_id", str(getattr(hit, "doc_id", "") or ""))
        meta.setdefault("doc_name", str(getattr(hit, "doc_name", "") or ""))
        if alias in page.shared_refs:
            meta["shared_evidence_ref"] = page.shared_refs[alias]
        identity = "\x1f".join((
            str(evidence_namespace or "ordinary"), alias,
            str(getattr(hit, "doc_id", "") or ""),
            str(meta.get("source_ref") or meta.get("chunk_id") or ""),
            hashlib.sha256(content.encode("utf-8")).hexdigest(),
        ))
        meta.update({
            "model_query_index": qi, "model_query_text": query,
            "model_query_addresses": list(addresses), "model_hit_index": hi,
            "model_evidence_ref": alias, "query_provenance": provenance,
            "global_evidence_id": "evidence_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32],
            "evidence_namespace": str(evidence_namespace or "ordinary"),
            "model_source_index": source_index,
            "body_status": "full" if body_shown else "deferred_capacity",
            **card_delivery_facts(meta, raw_body_shown=body_shown),
            "normative_card_identity": normative_card_identity(meta),
        })
        chunks.append(_ModelRagEvidenceChunk(
            content=content, doc_id=str(getattr(hit, "doc_id", "") or ""),
            doc_name=str(getattr(hit, "doc_name", "") or ""),
            score=float(getattr(hit, "score", 0.0) or 0.0), meta=meta,
        ))
    return page.groups, chunks, page.deferred_refs


def _model_rag_source_map(chunks: Sequence[_ModelRagEvidenceChunk]) -> list[dict[str, Any]]:
    return [source_map_item(chunk, index=index) for index, chunk in enumerate(chunks, 1)]


def _explicit_absence_value(value: Any) -> bool:
    if value is None:
        return True
    marker = str(value).strip().strip("*_` ").strip()
    if len(marker) >= 2 and (marker[0], marker[-1]) in {
        ("(", ")"),
        ("[", "]"),
    }:
        marker = marker[1:-1].strip()
    return marker.casefold() in {
        "",
        "—",
        "-",
        "–",
        "−",
        "нет",
        "н/д",
        "n/a",
        "na",
        "none",
        "группировка",
        "заголовок",
    }


def model_rag_row_kind(row: Mapping[str, Any]) -> str:
    """Classify a parsed row without rewriting model cells.

    Authored ``row_role`` wins when present so material/equipment decisions are
    not treated as install works for evidence/duplicate gates.
    """

    from proxy.services.lsr_source_coverage_service import canonicalize_row_role

    explicit = canonicalize_row_role(row.get("row_role"))
    if explicit in {"material", "equipment", "resource", "unresolved"}:
        return explicit
    if explicit == "work":
        return "work"

    unit_absent = _explicit_absence_value(row.get("unit"))
    quantity_absent = row.get("quantity") is None or _explicit_absence_value(
        row.get("quantity")
    )
    norm_absent = _explicit_absence_value(row.get("norm_code"))
    if unit_absent and quantity_absent and norm_absent:
        return "section_header"
    coverage = " ".join(
        str(row.get(name) or "") for name in ("analogue", "coverage", "note")
    )
    if norm_absent and "MISSING" in coverage.upper():
        return "missing"
    return "work"


def llm_usage_finish_reason(usage: Mapping[str, Any] | None) -> str:
    payload = usage if isinstance(usage, Mapping) else {}
    return str(payload.get("finish_reason") or payload.get("done_reason") or "").strip()


def finish_reason_is_length(reason: str) -> bool:
    return str(reason or "").strip().casefold() in _LENGTH_FINISH_REASONS


def model_query_output_diagnostics(
    text: str, usage: Mapping[str, Any], *, purpose: str, budget: Mapping[str, Any],
) -> dict[str, Any]:
    """Safe call facts; neither source text nor hidden reasoning is persisted here."""
    return {"purpose": purpose, "budget": dict(budget),
            "finish_reason": llm_usage_finish_reason(usage),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "final_chars": len(text or ""),
            "output_incomplete": not str(text or "").strip()
                 and finish_reason_is_length(llm_usage_finish_reason(usage))}


class ModelExecutionFailure(HTTPException):
    """Trusted private execution diagnostics survive the public error boundary."""

    def __init__(self, detail: Any, *, diagnostics: Mapping[str, Any],
                 status_code: int = 503, headers=None):
        super().__init__(status_code, detail=detail, headers=headers)
        self.private_query_trace = dict(diagnostics)


class ModelQueryFailure(ModelExecutionFailure):
    """Query failure with bounded final-output diagnostics."""


def model_query_failure(detail: Any, *, trace: Mapping[str, Any], session_id: str,
                        provider: str, model: str, secret_values: Sequence[str] = (),
                        final_texts: Sequence[str] | None = None) -> ModelQueryFailure:
    """Snapshot only query facts, bounded final text and public connection identity."""
    outputs = list(trace.get("model_query_outputs") or ())
    texts = list(final_texts) if final_texts is not None else [item.get("final_text", "") for item in outputs]
    saved = []
    for item, raw in zip(outputs[-8:], texts[-8:]):
        final = re.sub(r"<think\b[^>]*>.*?(?:</think>|$)", "", str(raw or ""), flags=re.I | re.S).strip()
        for secret in secret_values:
            if secret:
                final = final.replace(str(secret), "[redacted]")
        final = re.sub(r'''(?i)["']?\b(?:api[_-]?key|password|authorization)["']?\s*[:=]\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;]+)|\bBearer\s+[^\s,;]+''',
                       "[redacted]", final)
        output = {key: item[key] for key in ("purpose", "finish_reason", "completion_tokens", "final_chars", "output_incomplete")
                  if key in item}
        output.update(final_text=final[:8192], final_text_truncated=len(final) > 8192)
        output["budget"] = {key: value for key, value in (item.get("budget") or {}).items()
                            if key in {"requested", "effective", "reserved_tokens", "source", "restart_required"}}
        parsed = item.get("declared_parse") or {}
        output["declared_parse"] = {key: parsed[key] for key in ("accepted_count", "rejected_count", "answer_cut", "output_shape")
                                    if key in parsed}
        output["declared_parse"]["reason_counts"] = dict(list((parsed.get("reason_counts") or {}).items())[:32])
        saved.append(output)
    connection = trace.get("model_connection") or {}
    execution = {"provider": str(provider), "model": str(model)}
    if connection.get("provider"):
        execution = {"provider": str(connection["provider"]), "model": str(connection.get("model_id") or model),
                     "configured_provider": str(provider), "configured_model": str(model), "source": "model_connection"}
        requested_execution = trace.get("model_execution_requested") or {}
        for field in ("provider", "model"):
            if requested_execution.get(field):
                execution["requested_" + field] = str(requested_execution[field])
    diagnostics = {"schema": "les.model-query-failure.v1", "session_id": str(session_id or ""),
                   "model_execution": execution,
                   "model_connection": {key: connection[key] for key in (
                       "connection_id", "revision_id", "display_name", "model_id", "provider", "locality", "fallback_used") if key in connection},
                   "model_query_outputs": saved, "model_query_output_count": len(outputs),
                   "model_query_outputs_truncated": len(outputs) > 8}
    return ModelQueryFailure(detail, diagnostics=diagnostics)


def declared_query_output_diagnostics(raw: str, declared: Mapping[str, Any]) -> dict[str, Any]:
    """Parse counts/reasons only; this never alters model-authored queries."""
    reasons: dict[str, int] = {}
    for item in declared.get("accompanying_answer") or ():
        reason = str(item.get("reason") or "")
        reasons[reason] = reasons.get(reason, 0) + 1
    shape = ("empty_final" if not str(raw or "").strip() else
             "unsupported_structured_output" if not _unwrap_model_rag_query_lines(raw) else "declared_lines")
    return {"accepted_count": len(declared.get("queries") or ()),
            "rejected_count": len(declared.get("accompanying_answer") or ()),
            "reason_counts": reasons, "answer_cut": bool(declared.get("answer_cut")), "output_shape": shape}


def governed_query_generation_budget(preset: ModelExecutionPreset, packet: ContextPacket) -> dict[str, Any]:
    try:
        return query_generation_budget(
            preset, reserved_tokens=packet.generation_reserve_tokens,
            configured_limit=os.getenv("LES_CHAT_MODEL_RAG_QUERY_MAX_TOKENS", ""),
        )
    except ValueError as error:
        raise HTTPException(400, detail={
            "code": "INVALID_MODEL_QUERY_OUTPUT_LIMIT",
            "detail": "Лимит ответа для поисковых запросов должен быть положительным целым числом либо пустым (авто).",
        }) from error


def packet_evidence_text(packet: ContextPacket) -> str:
    return "\n".join(
        obj.render()
        for section in packet.sections
        if section.kind is ContextKind.EVIDENCE
        for obj in section.objects
    )


def usage_with_finish_reason(
    usage: Mapping[str, Any] | None,
    finish_reason: str,
) -> dict[str, Any]:
    payload = dict(usage or {})
    reason = str(finish_reason or "").strip()
    if reason:
        payload["finish_reason"] = reason
    return payload


def attachment_context_is_truncated(text: str) -> bool:
    raw = str(text or "")
    return _TABULAR_TRUNCATION_MARK in raw or _PASTE_TRUNCATION_MARK in raw


def parse_attachment_sheet_coverage(text: str) -> dict[str, list[str]]:
    included: list[str] = []
    omitted: list[str] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("Переданы листы:"):
            rest = stripped.split(":", 1)[1].strip()
            if rest and rest.casefold() != "нет":
                included = [item.strip() for item in rest.split(",") if item.strip()]
        elif stripped.startswith("Не переданы листы:"):
            rest = stripped.split(":", 1)[1].strip()
            if rest:
                omitted = [item.strip() for item in rest.split(",") if item.strip()]
    return {"included": included, "omitted": omitted}


def model_rag_answer_is_truncated(raw: str) -> bool:
    lines = [line.rstrip() for line in str(raw or "").splitlines() if line.strip()]
    if not lines:
        return False
    last = lines[-1]
    return last.startswith("|") and not last.endswith("|")


def _lsr_packaging_reasons(
    *,
    errors: Sequence[str],
    attachment_truncated: bool = False,
    included_sheets: Sequence[str] = (),
    omitted_sheets: Sequence[str] = (),
    rejected_queries: int = 0,
    omitted_evidence: int = 0,
) -> list[str]:
    reasons: list[str] = []
    if attachment_truncated or omitted_sheets:
        included = ", ".join(included_sheets) if included_sheets else "часть листов"
        omitted = ", ".join(omitted_sheets) if omitted_sheets else "остальные листы"
        reasons.append(f"исходник усечён (переданы: {included}; не переданы: {omitted})")
    if "answer_truncated" in errors:
        reasons.append("ответ модели оборван")
    incomplete = [
        error
        for error in errors
        if str(error).startswith("source_incomplete:")
    ]
    if incomplete or "source_incomplete" in errors:
        reasons.append("модели не переданы все строки исходника")
    qty_mismatch = [
        error.split(":", 1)[1]
        for error in errors
        if str(error).startswith("source_quantity_mismatch:")
    ]
    if qty_mismatch:
        preview = ", ".join(qty_mismatch[:5])
        extra = f" и ещё {len(qty_mismatch) - 5}" if len(qty_mismatch) > 5 else ""
        reasons.append(f"количество не совпадает с исходником у {preview}{extra}")
    missing_refs = [
        error.split(":", 1)[1]
        for error in errors
        if str(error).startswith("missing_evidence_ref:")
    ]
    if missing_refs:
        preview = ", ".join(missing_refs[:5])
        extra = f" и ещё {len(missing_refs) - 5}" if len(missing_refs) > 5 else ""
        reasons.append(f"нет evidence_ref у строк {preview}{extra}")
    skipped_prefixes = (
        "missing_evidence_ref:",
        "norm_code_not_in_referenced_evidence:",
        "source_quantity_mismatch:",
        "source_incomplete:",
        "source_coverage_incomplete:",
        "source_row_not_in_catalog:",
        "source_unit_mismatch:",
    )
    other = [
        str(error)
        for error in errors
        if error not in {"attachment_truncated", "answer_truncated"}
        and not any(str(error).startswith(prefix) for prefix in skipped_prefixes)
    ]
    if other:
        reasons.append(", ".join(other[:6]))
    if rejected_queries:
        reasons.append(f"отброшены повествовательные query-строки: {rejected_queries}")
    if omitted_evidence:
        reasons.append(f"не поместились полные карточки: {omitted_evidence}")
    coverage = [
        error.split(":", 1)[1]
        for error in errors
        if str(error).startswith("source_coverage_incomplete:")
    ]
    if coverage:
        reasons.append(f"покрытие исходника {coverage[0]}")
    return reasons or ["структурная проверка не пройдена"]


def format_lsr_not_created_notice(
    *,
    errors: Sequence[str],
    row_count: int,
    attachment_truncated: bool = False,
    included_sheets: Sequence[str] = (),
    omitted_sheets: Sequence[str] = (),
    rejected_queries: int = 0,
    omitted_evidence: int = 0,
) -> str:
    """Operator-visible reason that a workbook was not published."""

    reasons = _lsr_packaging_reasons(
        errors=errors,
        attachment_truncated=attachment_truncated,
        included_sheets=included_sheets,
        omitted_sheets=omitted_sheets,
        rejected_queries=rejected_queries,
        omitted_evidence=omitted_evidence,
    )
    return (
        f"ЛСР не создана: {'; '.join(reasons)}. "
        f"Строк в ответе модели: {row_count}."
    )


def format_lsr_partial_notice(
    *,
    errors: Sequence[str],
    row_count: int,
    attachment_truncated: bool = False,
    included_sheets: Sequence[str] = (),
    omitted_sheets: Sequence[str] = (),
    rejected_queries: int = 0,
    omitted_evidence: int = 0,
) -> str:
    """Visible reason that a workbook was published from an incomplete source/answer."""

    reasons = _lsr_packaging_reasons(
        errors=errors,
        attachment_truncated=attachment_truncated,
        included_sheets=included_sheets,
        omitted_sheets=omitted_sheets,
        rejected_queries=rejected_queries,
        omitted_evidence=omitted_evidence,
    )
    return (
        f"ЛСР собрана частично: {'; '.join(reasons)}. "
        f"В расчёт вошли {row_count} строк ответа модели; полный файл по всем "
        "листам исходника не утверждается."
    )


def format_lsr_unstructured_notice(*, sheet_pass_empty: bool = False) -> str:
    """Visible reason when the model answer is not an LSR row table."""

    if sheet_pass_empty:
        return (
            "ЛСР не создана: после поиска источников таблица строк не получена. "
            "Пустой поиск по запросу модели не считается ошибкой формата; "
            "незакрытые строки исходника остаются в задании."
        )
    return (
        "ЛСР не создана: ответ не разобран как таблица строк "
        "(нужны колонки наименования, единицы и шифра)."
    )


def build_vor_result_readiness(
    *, rows: Sequence[Mapping[str, Any]], has_file: bool,
    remaining_locators: Sequence[str], catalog_work_count: int,
    model_errors: Sequence[str],
) -> dict[str, Any]:
    """Expose authored gaps; delivering a VOR does not establish its completeness."""
    structural = [str(error) for error in model_errors if str(error).startswith(
        ("source_", "invalid_source_row", "duplicate_source_row"),
    )]
    questions = list(structural)
    for row in rows:
        gap = str(row.get("open_gap") or "").strip()
        unresolved = str(row.get("row_role") or "").strip().casefold() == "unresolved"
        if not gap and not unresolved:
            continue
        title = str(row.get("title") or row.get("source_row") or "Позиция").strip()
        questions.append(f"{title}: {gap}" if gap else f"{title}: требуется уточнение")
    questions = list(dict.fromkeys(questions))
    technical = bool(has_file) and not remaining_locators and not structural
    return {
        "schema": "les.vor-result-readiness.v1", "artifact_kind": "vor_workbook",
        "technical_complete": technical, "vor_complete": technical and not questions,
        "remaining_locators": list(remaining_locators),
        "catalog_work_count": int(catalog_work_count), "open_questions": questions,
    }


def format_lsr_packaged_notice(
    *,
    filename: str = "",
    status: str = "",
    pricing_status: str = "",
    norms_status: str = "",
    missing: Sequence[str] = (),
    blockers: Sequence[str] = (),
    readiness: Mapping[str, Any] | None = None,
    artifact_kind: str = "lsr_workbook",
) -> str:
    """Visible packaging outcome next to the workbook link."""

    if artifact_kind == "vor_workbook":
        notice = f"ВОР сформирован. Файл: {filename}." if filename else "ВОР сформирован."
        questions = list((readiness or {}).get("open_questions") or [])
        if questions:
            notice += f" Открытые вопросы по исходнику: {len(questions)}. Проверьте замечания в ответе."
        return notice

    if isinstance(readiness, Mapping) and readiness.get("dimensions"):
        return format_lsr_readiness_notice(readiness, filename=filename)

    missing_items = [str(item).strip() for item in missing if str(item).strip()]
    blocker_items = [str(item).strip() for item in blockers if str(item).strip()]
    unbound = [item for item in missing_items if item.startswith("row:")]
    unpriced = [item for item in missing_items if item.startswith("price_missing:")]
    other = [
        item for item in missing_items if item not in unbound and item not in unpriced
    ]
    file_bit = f" Файл: {filename}." if filename else ""
    incomplete = bool(
        unbound
        or unpriced
        or other
        or blocker_items
        or status == "partial"
        or pricing_status in {"priced_partial", "norm_selection_required"}
        or (norms_status and norms_status != "norms_verified")
    )
    if not incomplete:
        return f"ЛСР собрана.{file_bit}".strip()
    fallback = build_lsr_result_readiness(
        packaged=True,
        packaging_failed=False,
        rows=(),
        missing=missing_items,
        pricing_status=pricing_status,
    )
    notice = format_lsr_readiness_notice(fallback, filename=filename)
    if blocker_items:
        notice += " Блокеры: " + ", ".join(blocker_items[:6]) + "."
    if other:
        notice += " Замечания: " + ", ".join(other[:6]) + "."
    return notice


def validate_model_rag_result_structure(
    rows: Sequence[dict[str, Any]],
    evidence_chunks: Sequence[Any],
    *,
    expected_source_rows: int,
    attachment_truncated: bool = False,
    answer_truncated: bool = False,
    source_catalog: AttachmentSourceCatalog | None = None,
    source_incomplete_locators: Sequence[str] = (),
    finish_reason: str = "",
    validate_evidence_refs: bool = True,
    existing_operation_rows: Sequence[Mapping[str, Any]] | None = None,
    review_operation_rows: Sequence[Mapping[str, Any]] = (),
) -> list[str]:
    """Validate references before packaging without changing model decisions."""

    errors: list[str] = []
    if attachment_truncated:
        errors.append("attachment_truncated")
    if answer_truncated or finish_reason_is_length(finish_reason):
        errors.append("answer_truncated")
    if source_incomplete_locators:
        errors.append(
            "source_incomplete:"
            + ",".join(list(source_incomplete_locators)[:8])
        )
    observed_keys: set[tuple[str, str, str, str]] = set()
    known_operations = {
        str(row.get("operation_id")): row for row in model_rag_existing_operation_rows(
            existing_operation_rows or (), review_operation_rows)
        if row.get("operation_id")
    }
    for row in rows:
        source_row = row.get("source_row")
        is_positive_int = (
            isinstance(source_row, int)
            and not isinstance(source_row, bool)
            and source_row > 0
        )
        is_authored_label = isinstance(source_row, str) and bool(source_row.strip())
        if not is_positive_int and not is_authored_label:
            errors.append("invalid_source_row")
            continue
        # One locator may legally carry several distinct operations, even with
        # the same role. Duplicate means the identical content was authored
        # twice; distinct content on one locator is the two-operations pattern.
        source_key = (
            type(source_row).__name__,
            str(source_row),
            _decision_role_key(row),
            _decision_identity_sha(row),
        )
        if source_key in observed_keys:
            errors.append(f"duplicate_source_row:{source_row}")
        observed_keys.add(source_key)
        operation_id = str(row.get("operation_id") or "").strip()
        if operation_id and existing_operation_rows is not None:
            prior = known_operations.get(operation_id)
            if prior is None:
                errors.append(f"unknown_operation_id:{source_row}:{operation_id}")
            else:
                old_source = prior.get("source_row")
                old_row = source_catalog.lookup(old_source) if source_catalog else None
                new_row = source_catalog.lookup(source_row) if source_catalog else None
                if (old_row.locator if old_row else str(old_source)) != (new_row.locator if new_row else str(source_row)):
                    errors.append(f"operation_source_mismatch:{source_row}:{operation_id}")

    evidence_by_ref: dict[str, dict[str, Any]] = {}
    evidence_by_global_id: dict[str, dict[str, Any]] = {}
    for chunk in evidence_chunks:
        meta = dict(getattr(chunk, "meta", {}) or {})
        evidence_ref = str(meta.get("model_evidence_ref") or "").strip().upper()
        if evidence_ref:
            evidence_by_ref[evidence_ref] = meta
        global_id = str(meta.get("global_evidence_id") or "").strip()
        if global_id:
            evidence_by_global_id[global_id] = meta

    def code_identity(value: Any) -> str:
        return "".join(
            character
            for character in str(value or "").strip().casefold()
            if not character.isspace() and character != ":"
        )

    for row in rows:
        if model_rag_row_kind(row) != "work":
            continue
        source_row = row.get("source_row")
        if source_catalog is not None:
            errors.extend(compare_model_row_to_catalog(row, source_catalog))
        if not validate_evidence_refs:
            continue
        refs = extract_model_evidence_refs(row.get("evidence_refs"))
        if not refs:
            errors.append(f"missing_evidence_ref:{source_row}")
            continue
        raw_bindings = row.get("evidence_bindings")
        bindings = (
            {
                str(alias).strip().upper(): str(global_id).strip()
                for alias, global_id in raw_bindings.items()
                if str(alias).strip() and str(global_id).strip()
            }
            if isinstance(raw_bindings, Mapping)
            else {}
        )
        if bindings:
            unknown_refs: list[str] = []
            referenced_meta: list[dict[str, Any]] = []
            for ref in refs:
                global_id = bindings.get(ref, "")
                if global_id and global_id in evidence_by_global_id:
                    referenced_meta.append(evidence_by_global_id[global_id])
                    continue
                if not global_id and ref in evidence_by_ref:
                    referenced_meta.append(evidence_by_ref[ref])
                    continue
                unknown_refs.append(ref)
        else:
            unknown_refs = [ref for ref in refs if ref not in evidence_by_ref]
            referenced_meta = [
                evidence_by_ref[ref] for ref in refs if ref in evidence_by_ref
            ]
        errors.extend(f"unknown_evidence_ref:{ref}" for ref in unknown_refs)
        selected_code = (
            ""
            if _explicit_absence_value(row.get("norm_code"))
            else code_identity(row.get("norm_code"))
        )
        if selected_code and not any(
            (
                (evidence_code := code_identity(meta.get("norm_code")))
                and evidence_code in selected_code
            )
            for meta in referenced_meta
        ):
            errors.append(f"norm_code_not_in_referenced_evidence:{source_row}")
    if source_catalog is not None:
        errors.extend(coverage_errors(rows, source_catalog))
    return list(dict.fromkeys(errors))


def blocking_model_rag_result_errors(
    errors: Sequence[str],
    *,
    work_row_count: int = 0,
) -> list[str]:
    """Keep evidence-code disagreement visible without withholding the model draft.

    Governor omissions and a cut-off last table line do not drop already parsed
    work rows. A missing or unknown Qx.Hy on one work row stays visible and
    unpriced; it does not withhold the workbook when other work rows exist.
    Quantity mismatch still blocks the file.
    """

    advisory_prefixes = (
        "norm_code_not_in_referenced_evidence:",
        "source_row_not_in_catalog:",
        "source_coverage_incomplete:",
        "source_unit_mismatch:",
        "source_incomplete:",
    )
    if int(work_row_count or 0) > 0:
        advisory_prefixes = (
            *advisory_prefixes,
            "missing_evidence_ref:",
            "unknown_evidence_ref:",
        )
    advisory_exact = {"answer_truncated", "workbook_research_cancelled"} if int(work_row_count or 0) > 0 else {"workbook_research_cancelled"}
    return [
        error
        for error in errors
        if not str(error).startswith(advisory_prefixes)
        and str(error) not in advisory_exact
    ]


def model_rag_search_tool_schema() -> list[dict[str, Any]]:
    """Expose the selected datasets as one native search tool."""

    return native_model_tool_schemas(
        [
            {
                "name": "search_sources",
                "summary": "Искать evidence в явно выбранных датасетах",
                "input_schema": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                    "additionalProperties": False,
                },
            }
        ]
    )


def _bounded_source_blocks(text: str, *, max_chars: int = 700) -> list[str]:
    """Keep source rows intact while making a large attachment packable."""

    blocks: list[str] = []
    current: list[str] = []
    current_chars = 0
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        added = len(line) + (1 if current else 0)
        if current and current_chars + added > max_chars:
            blocks.append("\n".join(current))
            current = []
            current_chars = 0
        if len(line) > max_chars:
            if current:
                blocks.append("\n".join(current))
                current = []
                current_chars = 0
            blocks.append(line)
            continue
        current.append(line)
        current_chars += len(line) + (1 if current_chars else 0)
    if current:
        blocks.append("\n".join(current))
    return blocks


def selector_evidence_payload(
    *,
    attachment_context: str,
    rendered_context: str,
    source_catalog: AttachmentSourceCatalog | None = None,
    sheet: str = "",
    remaining_work: Sequence[str] | None = None,
) -> list[Any]:
    """Return model evidence as independently packable, ordered source blocks."""

    payload: list[Any] = []
    if source_catalog is not None and source_catalog.rows:
        payload.append(source_catalog.manifest_text())
        wanted_sheet = str(sheet or "").strip()
        if wanted_sheet:
            names = catalog_work_sheet_names(source_catalog) or [
                name for name, _count in source_catalog.sheets
            ]
            index = names.index(wanted_sheet) + 1 if wanted_sheet in names else 1
            payload.append(
                f"Текущий шаг: лист «{wanted_sheet}» ({index}/{len(names) or 1}). "
                "Другие листы манифеста будут отдельными шагами; не отказывайся из‑за них."
            )
            payload.extend(
                catalog_sheet_pack_lines(
                    source_catalog,
                    wanted_sheet,
                    remaining_work=remaining_work,
                )
            )
            payload.append(catalog_sheet_packet_facts(source_catalog, wanted_sheet, remaining_work))
        else:
            payload.extend(source_catalog.interleaved_row_lines())
    elif str(attachment_context or "").strip():
        payload.append("Текст явно прикреплённого пользователем файла:")
        payload.extend(_bounded_source_blocks(attachment_context))
    payload.append("Материалы из найденных документов:")
    payload.extend(
        item.payload
        for item in _text_context_objects("selector-evidence", rendered_context)
    )
    return payload


def selector_context_shortlist(
    shortlist: Sequence[Any], *, native_tool_schemas: bool,
) -> Sequence[Any]:
    """Do not duplicate native provider tool schemas inside message context."""

    return () if native_tool_schemas else shortlist


def initial_selector_context(
    rendered_context: str, *, model_authored_initial_query: bool,
) -> str:
    """Do not label a not-yet-run model-authored search as empty retrieval."""

    return "" if model_authored_initial_query else rendered_context


def model_runtime_facts(
    profile_snapshot: Mapping[str, Any] | None, *, observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Observed clock/catalog, not a choice of price basis or a price assertion."""
    snapshot = profile_snapshot or {}
    now = observed_at or datetime.now(timezone.utc)
    facts: dict[str, Any] = {
        "schema": "les.model-runtime-facts.v1", "origin": "application",
        "utc_date": now.astimezone(timezone.utc).date().isoformat(),
    }
    if str(snapshot.get("mode") or "").strip().casefold() == "estimator" or profile_uses_tabular_estimator_path(dict(snapshot)):
        from proxy.services.fgis_price_service import available_pricebooks
        books = [Path(path).stem for path in available_pricebooks()]
        visible: list[str] = []
        used = 0
        for book in books:
            size = len(json.dumps(book, ensure_ascii=False)) + 2
            if used + size <= 2048:
                visible.append(book)
                used += size
        facts["installed_pricebook_files"] = visible
        facts["installed_pricebook_file_count"] = len(books)
        facts["pricebook_inventory_complete"] = len(visible) == len(books)
    return facts


def profile_system_prompt(profile_snapshot: dict[str, Any] | None, *, strict: bool) -> str:
    """Compile the exact per-chat prompt/skill snapshot for grounded generation."""

    snapshot = profile_snapshot if isinstance(profile_snapshot, dict) else {}
    prompt = str(snapshot.get("prompt_text") or "").strip()
    skill = str(snapshot.get("skill_text") or "").strip()
    if not prompt:
        prompt = build_mode_system_prompt("rag")
    parts = [prompt]
    parts.append("Факты выполнения от приложения:\n" + json.dumps(model_runtime_facts(snapshot), ensure_ascii=False))
    if skill:
        parts.append("Активный skill профиля (правила работы, не evidence):\n" + skill)
    if strict:
        parts.append(
            "Повторная попытка: сохрани полезный ответ, но привяжи числа, требования и "
            "проектные факты к [Источник N]. Не найденное обозначь как ограничение."
        )
    else:
        parts.append(
            "Для проверяемых утверждений используй только реальные материалы текущего запроса. "
            "Ссылки оформляй номерами из заголовков [Источник N]; навигационные карты помогают "
            "выбрать файл, но сами по себе не подтверждают факт."
        )
    if (
        str(snapshot.get("mode") or "").strip().casefold() == "estimator"
        or profile_uses_tabular_estimator_path(snapshot)
    ):
        parts.append(_TABULAR_LSR_VOLUME_INSTRUCTION)
    return "\n\n".join(parts)


def profile_tool_selector_prompt(profile_snapshot: dict[str, Any] | None) -> str:
    """Compile the thin role+skill contract for one native tool decision."""

    snapshot = profile_snapshot if isinstance(profile_snapshot, dict) else {}
    mode = str(snapshot.get("mode") or "agent").strip() or "agent"
    skill = str(snapshot.get("skill_text") or "").strip()
    parts = [
        (
            f"Ты — Л.Е.С., профиль {mode}. На этом вызове выбери нужные native tools, "
            "а не формулируй итоговый ответ. Модель сама создаёт поисковые запросы и "
            "принимает предметные решения; код только исполняет вызовы и оформляет результат."
        )
    ]
    if skill:
        parts.append("Активный skill профиля:\n" + skill)
    return "\n\n".join(parts)

@dataclass(frozen=True)
class EvidenceRequestContext:
    req: Any
    dataset_ids: list[str]
    effective_dataset_filter: str
    resolved_dataset_names: list[str]
    dataset_name_by_id: dict[str, str]
    query_route_payload: dict[str, Any]
    target_doc_filter: list[str]
    target_file_ref: dict[str, Any] | None
    topic_doc_filter: list[str]
    topic_retrieval_plan: dict[str, Any] | None
    inventory_requested: bool
    study_requested: bool
    memory_block: str
    session_block: str
    class_suggestions: list[dict[str, Any]]
    use_semantic_cache: bool
    use_validation: bool
    validation_skip_reason: str
    route: Any
    table_result: Any
    request_started_at: float
    profile_snapshot: dict[str, Any] = field(default_factory=dict)
    scope_resolution: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceRuntimeDeps:
    state: Any
    rag_backend: Any
    cache: Any
    cache_embedding: Any
    cache_marker: str
    cache_scope: str
    assistant_text: Callable
    augment_model_tool_args: Callable
    chat_model_final_answer: Callable
    cloud_body_for_model: Callable
    compact_tool_result_for_prompt: Callable
    dataset_ids_from_chunks: Callable
    dataset_sensitivities: Callable
    env_bool: Callable
    env_float: Callable
    env_int: Callable
    expand_context_windows: Callable
    format_tool_results_for_model: Callable
    generation_token_budget: Callable
    llm_runtime: Callable
    local_context_budget: Callable
    mlx_runtime: Callable
    names_for_dataset_ids: Callable
    notebook_study_validation_status: Callable
    ollama_native_complete: Callable
    parse_model_tool_calls: Callable
    prepare_notebook_reader_memory: Callable
    record_cloud_cost: Callable
    retrieve_chat_chunks: Callable
    source_excerpts: Callable
    table_query_response: Callable
    cloud_fallback_models: Callable
    cloud_model_timeout: Callable
    model_connection_resolver: Callable | None = None
    model_connection_transport: Callable | None = None
    workbook_tool_executor: Callable | None = None


@dataclass(frozen=True)
class ResponseBoundary:
    save_chat_history: Callable
    token_sink: Callable | None
    version_stamp: Callable


async def run_chat_evidence_application(
    request: EvidenceRequestContext,
    runtime: EvidenceRuntimeDeps,
    response: ResponseBoundary,
):
    return await _execute_chat_evidence_application(
        _dataset_ids=request.dataset_ids,
        scope_resolution=request.scope_resolution,
        class_suggestions=request.class_suggestions,
        dataset_name_by_id=request.dataset_name_by_id,
        effective_dataset_filter=request.effective_dataset_filter,
        inventory_requested=request.inventory_requested,
        memory_block=request.memory_block,
        query_route_payload=request.query_route_payload,
        req=request.req,
        resolved_dataset_names=request.resolved_dataset_names,
        route=request.route,
        session_block=request.session_block,
        study_requested=request.study_requested,
        t_request_start=request.request_started_at,
        table_result=request.table_result,
        target_doc_filter=request.target_doc_filter,
        target_file_ref=request.target_file_ref,
        topic_doc_filter=request.topic_doc_filter,
        topic_retrieval_plan=request.topic_retrieval_plan,
        use_semantic_cache=request.use_semantic_cache,
        use_validation=request.use_validation,
        validation_skip_reason=request.validation_skip_reason,
        profile_snapshot=request.profile_snapshot,
        state=runtime.state,
        rag_backend=runtime.rag_backend,
        cache=runtime.cache,
        cache_embedding=runtime.cache_embedding,
        cache_marker=runtime.cache_marker,
        cache_scope=runtime.cache_scope,
        _assistant_text=runtime.assistant_text,
        _augment_model_tool_args=runtime.augment_model_tool_args,
        _chat_model_final_answer=runtime.chat_model_final_answer,
        _cloud_body_for_model=runtime.cloud_body_for_model,
        _compact_tool_result_for_prompt=runtime.compact_tool_result_for_prompt,
        _dataset_ids_from_chunks=runtime.dataset_ids_from_chunks,
        _dataset_sensitivities=runtime.dataset_sensitivities,
        _env_bool=runtime.env_bool,
        _env_float=runtime.env_float,
        _env_int=runtime.env_int,
        expand_context_windows=runtime.expand_context_windows,
        _format_tool_results_for_model=runtime.format_tool_results_for_model,
        _generation_token_budget=runtime.generation_token_budget,
        _llm_runtime=runtime.llm_runtime,
        _local_context_budget=runtime.local_context_budget,
        _mlx_runtime=runtime.mlx_runtime,
        _names_for_dataset_ids=runtime.names_for_dataset_ids,
        _notebook_study_validation_status=runtime.notebook_study_validation_status,
        _ollama_native_complete=runtime.ollama_native_complete,
        _parse_model_tool_calls=runtime.parse_model_tool_calls,
        _prepare_notebook_reader_memory=runtime.prepare_notebook_reader_memory,
        _record_cloud_cost=runtime.record_cloud_cost,
        retrieve_chat_chunks=runtime.retrieve_chat_chunks,
        source_excerpts=runtime.source_excerpts,
        _table_query_response=runtime.table_query_response,
        cloud_fallback_models=runtime.cloud_fallback_models,
        cloud_model_timeout=runtime.cloud_model_timeout,
        model_connection_resolver=runtime.model_connection_resolver,
        model_connection_transport=runtime.model_connection_transport,
        workbook_tool_executor=runtime.workbook_tool_executor,
        save_chat_history=response.save_chat_history,
        token_sink=response.token_sink,
        _version_stamp=response.version_stamp,
        HTTPException=HTTPException,
        Path=Path,
        asyncio=asyncio,
        build_mode_system_prompt=build_mode_system_prompt,
        build_notebook_study_pack=build_notebook_study_pack,
        build_project_summary=build_project_summary,
        build_retrieval_evidence_packet=build_retrieval_evidence_packet,
        build_validation_context=build_validation_context,
        classify_answer_form=classify_answer_form,
        concentrate_sources=concentrate_sources,
        dataset_memory_prompt_excerpt=dataset_memory_prompt_excerpt,
        decide_provider=decide_provider,
        extract_highlight=extract_highlight,
        format_project_inventory_context=format_project_inventory_context,
        format_project_inventory_prompt=format_project_inventory_prompt,
        format_study_artifact=format_study_artifact,
        generation_semaphore=generation_semaphore,
        httpx=httpx,
        is_cloud_provider=is_cloud_provider,
        is_notebook_study_query=is_notebook_study_query,
        json=json,
        logger=logger,
        maybe_answer_table_query=maybe_answer_table_query,
        notebook_study_prompt_block=notebook_study_prompt_block,
        os=os,
        rank_chunks_for_question=rank_chunks_for_question,
        render_retrieval_evidence_for_model=render_retrieval_evidence_for_model,
        retrieval_fingerprint=retrieval_fingerprint,
        rules_pre_verdict=rules_pre_verdict,
        set_highlight=set_highlight,
        source_names=source_names,
        time=time,
    )


async def _execute_chat_evidence_application(
    HTTPException,
    Path,
    _assistant_text,
    _augment_model_tool_args,
    _chat_model_final_answer,
    _cloud_body_for_model,
    _compact_tool_result_for_prompt,
    _dataset_ids,
    _dataset_ids_from_chunks,
    _dataset_sensitivities,
    _env_bool,
    _env_float,
    _env_int,
    _format_tool_results_for_model,
    _generation_token_budget,
    _llm_runtime,
    _local_context_budget,
    _mlx_runtime,
    _names_for_dataset_ids,
    _notebook_study_validation_status,
    _ollama_native_complete,
    _parse_model_tool_calls,
    _prepare_notebook_reader_memory,
    _record_cloud_cost,
    _table_query_response,
    _version_stamp,
    asyncio,
    build_mode_system_prompt,
    build_notebook_study_pack,
    build_project_summary,
    build_retrieval_evidence_packet,
    build_validation_context,
    cache,
    cache_embedding,
    cache_marker,
    cache_scope,
    class_suggestions,
    classify_answer_form,
    cloud_fallback_models,
    cloud_model_timeout,
    concentrate_sources,
    dataset_memory_prompt_excerpt,
    dataset_name_by_id,
    decide_provider,
    effective_dataset_filter,
    expand_context_windows,
    extract_highlight,
    format_project_inventory_context,
    format_project_inventory_prompt,
    format_study_artifact,
    generation_semaphore,
    httpx,
    inventory_requested,
    is_cloud_provider,
    is_notebook_study_query,
    json,
    logger,
    maybe_answer_table_query,
    memory_block,
    model_connection_resolver,
    model_connection_transport,
    workbook_tool_executor,
    notebook_study_prompt_block,
    os,
    query_route_payload,
    profile_snapshot,
    rag_backend,
    rank_chunks_for_question,
    render_retrieval_evidence_for_model,
    req,
    resolved_dataset_names,
    retrieval_fingerprint,
    retrieve_chat_chunks,
    route,
    rules_pre_verdict,
    save_chat_history,
    session_block,
    set_highlight,
    source_excerpts,
    source_names,
    state,
    study_requested,
    t_request_start,
    target_doc_filter,
    target_file_ref,
    time,
    token_sink,
    topic_doc_filter,
    topic_retrieval_plan,
    use_semantic_cache,
    use_validation,
    validation_skip_reason,
    answer=None,
    history_id=None,
    key=None,
    payload=None,
    retrieval=None,
    source_dataset_ids=None,
    source_dataset_names=None,
    scope_resolution=None,
    sources_list=None,
    status=None,
    table_result=None
):
    _dataset_ids = tuple(str(item) for item in (_dataset_ids or ()) if str(item))
    profile_snapshot, source_catalog, tabular_estimator_bound = bind_tabular_estimator_profile(
        profile_snapshot,
        attachment_id=str(getattr(req, "attachment_id", "") or ""),
    )
    document_grounding_enabled = bool(
        (scope_resolution or {}).get("document_grounding_enabled", _dataset_ids)
    )
    if tabular_estimator_bound:
        document_grounding_enabled = True
        from proxy.services.chat_profile_service import resolve_profile_system_dataset_ids

        _dataset_ids = tuple(
            resolve_profile_system_dataset_ids(
                profile_snapshot,
                current_dataset_ids=_dataset_ids,
            )
        )
    if document_grounding_enabled:
        use_semantic_cache = False
    # Ordinary chat is model-owned: validators may not judge, retry, rewrite,
    # suppress, or relabel the model's engineering conclusion.
    use_validation = False
    memory_project_id = 0
    workspace_memory_registered = False
    project_memory_advisory = ""
    try:
        memory_project_id, workspace_memory_registered = resolve_session_memory_scope(
            str(req.session_id or ""), int(getattr(req, "project_id", 0) or 0) or None,
        )
        memory_project_id = int(memory_project_id or 0)
        if memory_project_id > 0 and not workspace_memory_registered:
            project_memory_advisory = get_memory_port().recall_project_advisory(
                memory_project_id, str(req.question or "")
            )
    except Exception as memory_error:  # Memory is advisory and fail-open.
        logger.warning("[MEMORY] advisory recall skipped: %s", memory_error)
        memory_project_id = 0
        project_memory_advisory = ""

    # Карты тем/разделов остаются навигацией для модели. Production chat-path
    # физически не делает topic/file prefetch до первого модельного хода.
    requested_topic_doc_filter = list(topic_doc_filter or [])
    topic_doc_filter = []

    t_search_start = time.time()
    try:
        _reranker_on, retrieval_trace_policy = required_reranker_policy(
            getattr(req, "reranker_enabled", None)
        )
        topic_chunks: list[Any] = []
        if document_grounding_enabled and not profile_uses_model_driven_retrieval(
            profile_snapshot
        ):
            retrieval = await retrieve_chat_chunks(
                question=req.question,
                dataset_ids=_dataset_ids,
                rag_backend=rag_backend,
                reranker_enabled=_reranker_on,
                reranker_available=state.reranker_available,
                reranker_cls=state.reranker_cls,
                mlx_url=os.getenv("MLX_URL", "http://127.0.0.1:8080"),
                logger=logger,
                llm_semaphore=state.llm_semaphore,
                return_trace=True,
                doc_filter=target_doc_filter or None,
                scope_source=str((scope_resolution or {}).get("scope_source") or "unspecified"),
                scope_error_code=str((scope_resolution or {}).get("error_code") or ""),
            )
        else:
            retrieval = _SkippedDocumentRetrieval()
        chunks = [*topic_chunks, *retrieval.chunks] if topic_chunks else list(retrieval.chunks)
    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        logger.error("[CHAT] RETRIEVAL ERROR: %s\n%s", e, tb)
        raise HTTPException(500, f"Поиск по датасету не удался: {type(e).__name__}: {e}")
    t_search = time.time() - t_search_start
    retrieval_trace = retrieval.payload()
    if document_grounding_enabled and profile_uses_model_driven_retrieval(profile_snapshot):
        retrieval_trace.update(
            {
                "status": "model_driven",
                "reason": "awaiting_model_authored_query",
            }
        )
    retrieval_trace["scope_resolution"] = dict(scope_resolution or {})
    retrieval_trace["reranker_policy"] = retrieval_trace_policy
    retrieval_trace_object = getattr(retrieval, "trace", None)
    retrieval_status = str(
        getattr(retrieval_trace_object, "status", "") or retrieval_trace.get("status") or "ok"
    )
    if retrieval_status == "blocked":
        error_code = str(
            getattr(retrieval_trace_object, "error_code", "")
            or retrieval_trace.get("error_code")
            or "retrieval_blocked"
        )
        if error_code in {"dataset_scope_not_found", "no_datasets", "corpus_empty"}:
            blocked_answer = (
                "Нужный набор данных не найден или пока пуст. "
                "Выберите доступный проект/датасет либо добавьте источники — "
                "поиск по другим документам автоматически не выполнялся."
            )
            action = "Выбрать доступный датасет или загрузить источники."
        elif error_code in {"reranker_disabled", "reranker_unavailable", "reranker_failed"}:
            blocked_answer = (
                "Поиск остановлен: обязательный реранкер недоступен. "
                "Я не формирую ответ по непроверенному порядку фрагментов."
            )
            action = "Восстановить реранкер и повторить запрос."
        else:
            blocked_answer = (
                "Поиск остановлен: обязательный native RRF-контур недоступен. "
                "Старый или широкий поиск вместо него не запускался."
            )
            action = "Проверить индекс-контракт и native RRF, затем повторить запрос."
        retrieval_trace["blocker"] = {
            "schema": "retrieval_blocker_v1",
            "code": error_code,
            "action": action,
        }
        state.crag_stats["no_data"] += 1
        state.chat_metrics["retrieval_weak"] = state.chat_metrics.get("retrieval_weak", 0) + 1
        state.chat_metrics["latency_search"].append(t_search)
        state.chat_metrics["latency_gen"].append(0.0)
        state.chat_metrics["tokens"].append(0)
        state.chat_metrics["crag_fail"] += 1
        for key_name in ("latency_search", "latency_gen", "tokens"):
            state.chat_metrics[key_name] = state.chat_metrics[key_name][-100:]
        history_id = None
        try:
            history_id = save_chat_history(
                question=req.question,
                answer=blocked_answer,
                sources=[],
                crag_status="BLOCKED",
                latency_sec=t_search,
                tokens=0,
                session_id=req.session_id,
                requested_dataset_filter=req.dataset_filter,
                effective_dataset_filter=effective_dataset_filter,
                resolved_dataset_ids=_dataset_ids,
                resolved_dataset_names=resolved_dataset_names,
                query_route=query_route_payload,
                retrieval_trace=retrieval_trace,
                cache_type=cache_marker,
                validation_enabled=False,
                success=0,
            )
        except Exception as db_err:
            logger.warning("[CHAT] History save error: %s", db_err)
        return {
            "answer": blocked_answer,
            "crag_status": "BLOCKED",
            "sources": [],
            "effective_dataset_filter": effective_dataset_filter,
            "query_route": query_route_payload,
            "retrieval_trace": retrieval_trace,
            "blocker": retrieval_trace["blocker"],
            "cache": cache_marker,
            "validation": {"enabled": False, "reason": error_code},
            "history_id": history_id,
        }
    if topic_retrieval_plan:
        found_topic_docs = {str(getattr(chunk, "doc_name", "") or "") for chunk in topic_chunks}
        retrieval_trace["topic_guided_retrieval"] = {
            "schema": topic_retrieval_plan.get("schema") or "dataset_topic_selection_v1",
            "context_role": "navigation",
            "is_evidence": False,
            "selected_topics": topic_retrieval_plan.get("selected_topics") or [],
            "selected_files": topic_retrieval_plan.get("selected_files") or [],
            "selected_sections": topic_retrieval_plan.get("selected_sections") or [],
            "requested_doc_filter": requested_topic_doc_filter,
            "targeted_doc_filter": topic_doc_filter,
            "prefetch_enabled": False,
            "targeted_trace": {},
            "targeted_chunk_count": len(topic_chunks),
            "wide_fallback_trace": retrieval.payload(),
            "wide_fallback_chunk_count": len(retrieval.chunks),
            "fallback": topic_retrieval_plan.get("fallback") or "wide_retrieval",
            "not_found_files": [name for name in topic_doc_filter if name not in found_topic_docs],
        }
    if validation_skip_reason:
        retrieval_trace["validation_policy"] = {
            "enabled": False,
            "reason": validation_skip_reason,
            "evidence": "source_map+project_inventory_artifact",
        }
    if target_file_ref:
        retrieval_trace["target_file"] = target_file_ref
    if retrieval.quality.status == "good":
        state.chat_metrics["retrieval_good"] = state.chat_metrics.get("retrieval_good", 0) + 1
    else:
        state.chat_metrics["retrieval_weak"] = state.chat_metrics.get("retrieval_weak", 0) + 1

    notebook_study_pack = None
    notebook_study_prompt = ""
    notebook_study_artifact = ""
    notebook_study_latency = 0.0
    notebook_study_started = time.time()
    dataset_memory_prompt = ""
    project_inventory_prompt = ""
    project_inventory_artifact_text = ""
    project_inventory_payload: dict[str, Any] | None = None
    if _dataset_ids and study_requested:
        try:
            retrieval_trace["dataset_reader_prepare"] = await _prepare_notebook_reader_memory(
                [str(d) for d in _dataset_ids],
            )
        except Exception as reader_err:  # noqa: BLE001
            logger.warning("[DATASET_READER] study prepare failed: %s", reader_err)
            retrieval_trace["dataset_reader_prepare"] = {
                "schema": "dataset_reader_prepare_v1",
                "status": "skipped",
                "error": f"{type(reader_err).__name__}: {reader_err}",
            }
    if _dataset_ids:
        try:
            dataset_memory_prompt = await asyncio.to_thread(
                dataset_memory_prompt_excerpt,
                [str(d) for d in _dataset_ids],
                question=req.question,
            )
            if dataset_memory_prompt:
                retrieval_trace["dataset_memory"] = {
                    "schema": "dataset_brief_for_model_v1",
                    "context_role": "navigation",
                    "is_evidence": False,
                    "dataset_count": len(_dataset_ids),
                    "prompt_chars": len(dataset_memory_prompt),
                }
        except Exception as memory_err:  # noqa: BLE001
            logger.warning("[DATASET_MEMORY] skipped: %s", memory_err)
            retrieval_trace["dataset_memory"] = {
                "schema": "dataset_memory_context_v1",
                "status": "skipped",
                "error": f"{type(memory_err).__name__}: {memory_err}",
            }
    if _dataset_ids and (inventory_requested or study_requested):
        try:
            project_inventory_payload = await asyncio.to_thread(
                build_project_summary,
                [str(d) for d in _dataset_ids],
                storage_root=mutable_path("./storage/datasets"),
            )
            if inventory_requested:
                project_inventory_prompt = format_project_inventory_prompt(
                    project_inventory_payload,
                    label=", ".join(resolved_dataset_names or [str(d) for d in _dataset_ids]),
                )
                project_inventory_artifact_text = format_project_inventory_context(
                    project_inventory_payload,
                    label=", ".join(resolved_dataset_names or [str(d) for d in _dataset_ids]),
                )
            retrieval_trace["project_inventory"] = {
                "schema": "project_inventory_context_v1",
                "context_role": "deterministic_evidence",
                "source": "metadb.documents",
                "file_count": project_inventory_payload.get("file_count", 0),
                "by_ext": (project_inventory_payload.get("inventory") or {}).get("by_ext") or [],
                "prompt_chars": len(project_inventory_prompt),
                "artifact_chars": len(project_inventory_artifact_text),
                "used_for_notebook_study": bool(study_requested),
            }
        except Exception as inv_err:  # noqa: BLE001
            logger.warning("[PROJECT_INVENTORY] skipped: %s", inv_err)
            retrieval_trace["project_inventory"] = {
                "schema": "project_inventory_context_v1",
                "status": "skipped",
                "error": f"{type(inv_err).__name__}: {inv_err}",
            }
    if _dataset_ids and is_notebook_study_query(req.question):
        retrieval_trace["notebook_study"] = {
            "schema": "notebook_study_v1",
            "status": "map_only",
            "query_prefetch_enabled": False,
            "reason": "model_first_single_rrf",
            "note": "dataset map and inventory are navigation; no automatic section/file retrieval",
        }
    notebook_study_latency = time.time() - notebook_study_started
    retrieval_trace["notebook_study_latency_sec"] = round(notebook_study_latency, 3)

    # «Заставь отвечать»: не хард-режем разнородность, если есть сильный сигнал —
    # пользователь задал датасет (уже сузил) ИЛИ топ-совпадение хорошее (есть, что
    # отвечать). Гейт остаётся только для реально широких безскоповых слабых запросов.
    inventory_has_files = bool(project_inventory_payload and int(project_inventory_payload.get("file_count") or 0) > 0)
    strong_signal = bool(effective_dataset_filter) or inventory_has_files or (retrieval.quality.top_score >= 0.5)
    if retrieval.quality.status == "needs_clarification" and not strong_signal:
        retrieval_trace["wide_scope"] = {"model_final_allowed": True, "reason": "low_concentration"}

    is_structured = any(word in req.question.casefold() for word in ("перечен", "состав", "список", "разделы", "все разделы", "перечисли"))
    is_technical_or_legal = bool(effective_dataset_filter and effective_dataset_filter != "MAIL")

    # Размер контекста зависит от того, КУДА пойдёт генерация. Облако ест большой контекст
    # быстро; локальная 4B (P0-данные форсят MLX по ADR-9) захлёбывается на префилле 32K
    # символов — генерация ~1 tok/s. Поэтому большой контекст — только для облака.
    _cfg_provider = ""
    try:
        _cfg_provider = _llm_runtime().provider
        _route_preview = decide_provider(
            _cfg_provider,
            _dataset_sensitivities([str(d) for d in (_dataset_ids or [])]),
            consent=_env_bool("LES_CLOUD_CONSENT", False),
        )
        will_be_cloud = is_cloud_provider(_cfg_provider) and not _route_preview.downgraded
    except Exception:
        will_be_cloud = False
    big_context = (is_structured or is_technical_or_legal) and will_be_cloud
    local_big = (is_structured or is_technical_or_legal) and not will_be_cloud

    context_budget = _local_context_budget(
        local_big=local_big,
        big_context=big_context,
        provider=_cfg_provider,
    )
    focus_max_chunks = context_budget["focus_max_chunks"] or None
    context_max_chunks = context_budget["context_max_chunks"] or None
    context_chars_limit = context_budget["context_chars_limit"]
    context_window_chars = context_budget["context_window_chars"]
    context_radius = 0 if is_structured else None

    chunks = rank_chunks_for_question(req.question, chunks)
    protected_doc_names: list[str] = list(target_doc_filter or [])
    protected_doc_names.extend(topic_doc_filter)
    if notebook_study_pack is not None:
        protected_doc_names.extend([
            str(item.get("file_name") or "")
            for item in getattr(notebook_study_pack, "targeted_files", [])
            if item.get("file_name")
        ])
    protected_doc_names = list(dict.fromkeys(name for name in protected_doc_names if name))
    focus_max_docs = max(1, len({str(getattr(chunk, "doc_name", "") or "") for chunk in chunks}))
    chunks = concentrate_sources(
        chunks,
        max_docs=focus_max_docs,
        min_score=float("-inf"),
        max_chunks=focus_max_chunks,
        protected_doc_names=protected_doc_names,
    )
    if topic_doc_filter and retrieval.chunks:
        topic_names = {str(name or "") for name in topic_doc_filter}
        topic_basenames = {Path(name).name for name in topic_names}
        focused_names = {str(getattr(chunk, "doc_name", "") or "") for chunk in chunks}
        fallback_floor = _env_float("RAG_CHAT_FOCUS_MIN_SCORE", 0.35)
        promoted_fallback = None
        for candidate in rank_chunks_for_question(req.question, list(retrieval.chunks)):
            candidate_name = str(getattr(candidate, "doc_name", "") or "")
            if (
                not candidate_name
                or candidate_name in topic_names
                or candidate_name in focused_names
                or Path(candidate_name).name in topic_basenames
            ):
                continue
            candidate_score = float(getattr(candidate, "_rank_score", getattr(candidate, "score", 0.0)) or 0.0)
            if candidate_score < fallback_floor:
                continue
            insert_at = min(len(chunks), 5)
            if focus_max_chunks is not None and len(chunks) >= focus_max_chunks:
                chunks = [*chunks[:insert_at], candidate, *chunks[insert_at: max(focus_max_chunks - 1, insert_at)]]
            else:
                chunks = [*chunks[:insert_at], candidate, *chunks[insert_at:]]
            promoted_fallback = {
                "doc_name": candidate_name,
                "rank_score": round(candidate_score, 4),
            }
            break
        if promoted_fallback:
            retrieval_trace.setdefault("topic_guided_retrieval", {})["wide_fallback_promoted"] = promoted_fallback
    if protected_doc_names:
        retrieval_trace.setdefault("notebook_study", {})["protected_doc_names"] = protected_doc_names
    logger.info(
        "[FOCUS] После концентрации: %s чанков из %s источников",
        len(chunks),
        len(set(c.doc_name for c in chunks)),
    )
    focused_fingerprint = retrieval_fingerprint(chunks)

    if use_semantic_cache and cache_scope and not use_validation:
        session_hit = cache.lookup_session_unvalidated(
            req.question,
            cache_scope,
            focused_fingerprint,
            req.session_id,
        )
        if session_hit:
            state.chat_metrics["cache_hit"] = state.chat_metrics.get("cache_hit", 0) + 1
            history_id = None
            try:
                history_id = save_chat_history(
                    question=req.question,
                    answer=session_hit.answer,
                    sources=session_hit.sources,
                    crag_status="UNVALIDATED",
                    latency_sec=t_search,
                    tokens=0,
                    session_id=req.session_id,
                    requested_dataset_filter=req.dataset_filter,
                    effective_dataset_filter=effective_dataset_filter,
                    resolved_dataset_ids=_dataset_ids,
                    resolved_dataset_names=resolved_dataset_names,
                    source_dataset_ids=_dataset_ids,
                    source_dataset_names=resolved_dataset_names,
                    query_route=query_route_payload,
                    retrieval_trace=retrieval_trace,
                    cache_type=session_hit.cache_type,
                    validation_enabled=use_validation,
                    success=1,
                )
            except Exception as db_err:
                logger.warning("[CHAT] History save error: %s", db_err)
            return {
                "answer": session_hit.answer,
                "crag_status": "UNVALIDATED",
                "sources": session_hit.sources,
                "effective_dataset_filter": effective_dataset_filter,
                "query_route": query_route_payload,
                "retrieval_trace": retrieval_trace,
                "cache": session_hit.cache_type,
                "validation": {"enabled": use_validation},
                "history_id": history_id,
            }
    state.chat_metrics["cache_miss"] = state.chat_metrics.get("cache_miss", 0) + 1

    stamp_empty_retrieval(
        retrieval_trace,
        model_driven=profile_uses_model_driven_retrieval(profile_snapshot),
        chunks=chunks,
    )

    t_ctx_start = time.time()
    context_windows = expand_context_windows(
        chunks,
        collection=getattr(rag_backend, "collection_name", ""),
        logger=logger,
        max_chunks=context_max_chunks,
        max_chars_per_chunk=context_window_chars,
        radius=context_radius,
    )
    llm_chunks = context_windows.chunks
    retrieval_trace["context_window"] = context_windows.payload()
    retrieval_trace["context_budget"] = {
        **context_budget,
        "big_context": big_context,
        "local_big": local_big,
        "will_be_cloud": will_be_cloud,
        "context_radius": context_radius,
    }
    # ПЕРФ: валидатор теперь аддитивный/быстрый (rules+coreml fail-open) — ему НЕ нужен второй
    # дорогой проход expand_context_windows (это удваивало context-фазу, 2.7-5.7с на сложных).
    # Переиспользуем контекст ответа: те же чанки, валидатор проверяет ответ по ним.
    # Отдельный проход вернуть: RAG_VALIDATION_SEPARATE_CONTEXT=true.
    if _env_bool("RAG_VALIDATION_SEPARATE_CONTEXT", False):
        validation_context_windows = expand_context_windows(
            chunks,
            collection=getattr(rag_backend, "collection_name", ""),
            logger=logger,
            max_chunks=_env_int("RAG_VALIDATION_CONTEXT_MAX_CHUNKS", 10),
            max_chars_per_chunk=_env_int("RAG_VALIDATION_CONTEXT_WINDOW_CHARS", 2600),
            radius=_env_int("RAG_VALIDATION_CONTEXT_RADIUS", 1),
        )
    else:
        validation_context_windows = context_windows
    retrieval_trace["validation_context_window"] = validation_context_windows.payload()
    t_ctx = time.time() - t_ctx_start
    validation_context = ""

    connection_resolver = None
    connection_secret_store = None
    connection_factory_error = ""
    canonical_route = resolve_canonical_route(receipt=None)
    try:
        connection_resolver, connection_secret_store = model_connection_resolver()
        if (
            canonical_route.requested is CanonicalRouteMode.ACTIVE
            and canonical_route.effective is CanonicalRouteMode.SHADOW
        ):
            canonical_route = resolve_promoted_route(resolver=connection_resolver)
    except Exception as error:
        connection_factory_error = type(error).__name__
    candidate_acceptance = bool(getattr(req, "candidate_acceptance", False))
    canonical_execution_mode = execution_mode_for_candidate_acceptance(
        candidate_acceptance=candidate_acceptance,
        route=canonical_route,
    )
    if not candidate_acceptance and model_connection_resolver is not None:
        # The GUI-owned answer binding is authoritative for ordinary chat.
        # Shadow remains an isolated telemetry/acceptance concern only.
        canonical_execution_mode = CanonicalRouteMode.ACTIVE
    if candidate_acceptance:
        retrieval_trace["candidate_acceptance"] = {
            "enabled": True,
            "execution_mode": canonical_execution_mode.value,
            "promotion_receipt": "not_used",
            "state_root": "process_cwd_isolated",
        }
    resolved_connection = None
    connection_resolution_error = connection_factory_error
    if canonical_execution_mode is not CanonicalRouteMode.LEGACY:
        try:
            if connection_resolver is None:
                connection_resolver, connection_secret_store = model_connection_resolver()
            resolved_connection = connection_resolver.resolve(ConnectionRole.ANSWER)
        except Exception as error:  # shadow is diagnostic; active is fail-closed
            connection_resolution_error = type(error).__name__
            if canonical_execution_mode is CanonicalRouteMode.ACTIVE:
                raise HTTPException(503, f"MODEL_CONNECTION_RESOLUTION_FAILED: {error}") from error

    configured_runtime = _llm_runtime()
    # W3.3 (ADR-9): гейт чувствительности. P0-данные физически не уходят в облако;
    # P2 — только при явном LES_CLOUD_CONSENT; иначе принудительный fallback на MLX.
    _source_ds = set(_dataset_ids_from_chunks(chunks)) | {str(d) for d in (_dataset_ids or [])}
    _route = decide_provider(
        configured_runtime.provider,
        _dataset_sensitivities(_source_ds),
        consent=_env_bool("LES_CLOUD_CONSENT", False),
    )
    if _route.downgraded:
        logger.warning("[ROUTE] %s (датасеты: %s)", _route.reason, sorted(_source_ds))
        llm_runtime = _mlx_runtime()
    else:
        llm_runtime = configured_runtime
    from proxy.services.freetoken_cache_profile_service import cache_alignment_target

    active_connection = (
        resolved_connection if canonical_execution_mode is CanonicalRouteMode.ACTIVE else None
    )
    gen_semaphore = (
        state.llm_semaphore
        if active_connection is not None and active_connection.locality is not ConnectionLocality.REMOTE
        else generation_semaphore(state.llm_semaphore)
    )
    cache_target = cache_alignment_target(llm_runtime, active_connection=active_connection)
    cache_state: dict[str, Any] = {}
    if cache_target is not None:
        cache_base_url, cache_model = cache_target
        from proxy.services.freetoken_cache_profile_service import (
            DEFAULT_FREETOKEN_CONTEXT_TOKENS,
            admitted_cache_call,
            align_freetoken_cache_for_turn,
            desired_kv_for_answer_model,
            reconcile_freetoken_cache,
        )
        from proxy.services.model_execution_preset_service import (
            MIN_EXTENDED_35B_CONTEXT_TOKENS,
            is_qwen_35b,
        )

        desired_kv = desired_kv_for_answer_model(
            cache_model,
            _env_int("FREETOKEN_CONTEXT_TOKENS", DEFAULT_FREETOKEN_CONTEXT_TOKENS),
        )
        if (
            resolved_connection is not None
            and resolved_connection.requested_context_tokens
        ):
            desired_kv = desired_kv_for_answer_model(
                cache_model,
                int(resolved_connection.requested_context_tokens),
            )
        if canonical_execution_mode is CanonicalRouteMode.ACTIVE:
            # Rebuild once at HTTP-turn start if 35B is still on a legacy 8k
            # window. Packet loops must not call this; mid-generation rebuild
            # is still forbidden.
            cache_state = await admitted_cache_call(
                align_freetoken_cache_for_turn,
                cache_base_url,
                semaphore=gen_semaphore,
                timeout_seconds=generation_slot_timeout_seconds(),
                model_id=cache_model,
                requested_kv=desired_kv,
                allow_rebuild=True,
            )
            try:
                live_kv = int(cache_state.get("effective_kv_tokens") or 0)
            except (TypeError, ValueError):
                live_kv = 0
            if is_qwen_35b(cache_model) and (
                cache_state.get("status") not in {"aligned", "synchronized"}
                or live_kv < MIN_EXTENDED_35B_CONTEXT_TOKENS
            ):
                raise HTTPException(
                    503,
                    "FreeToken KV не готов для 35B: "
                    + str(cache_state.get("reason") or cache_state.get("status")),
                )
        else:
            cache_state = await admitted_cache_call(
                reconcile_freetoken_cache,
                cache_base_url,
                desired_kv,
                semaphore=gen_semaphore,
                timeout_seconds=generation_slot_timeout_seconds(),
            )
            if cache_state.get("status") not in {"aligned", "synchronized"}:
                raise HTTPException(
                    503,
                    "FreeToken KV не синхронизирован: "
                    + str(cache_state.get("reason") or cache_state.get("status")),
                )
        retrieval_trace["freetoken_cache"] = cache_state
    observed_context_tokens = None
    observed_context = False
    observed_source = "unavailable"
    if cache_state.get("status") in {"aligned", "synchronized", "mismatch"}:
        try:
            observed_context_tokens = int(cache_state.get("effective_kv_tokens") or 0) or None
        except (TypeError, ValueError):
            observed_context_tokens = None
        observed_context = observed_context_tokens is not None
        observed_source = "freetoken_cache_probe" if observed_context else "unavailable"
    model_policy = (profile_snapshot or {}).get("model_policy") or {}
    execution_preset = resolve_transport_execution_profile(
        provider=llm_runtime.provider,
        model_id=llm_runtime.model,
        observed_context_tokens=observed_context_tokens,
        observed=observed_context,
        observed_source=observed_source,
        operator=model_policy,
    )
    if canonical_execution_mode is CanonicalRouteMode.ACTIVE and resolved_connection is not None:
        if observed_context_tokens is not None:
            execution_preset = resolve_connection_execution_profile(
                model_id=resolved_connection.model_id,
                provider=getattr(resolved_connection, "extension_type", None) or "model_connection",
                reasoning_supported=resolved_connection.effective_preset.reasoning_supported,
                requested_context_tokens=resolved_connection.requested_context_tokens,
                observed_context_tokens=observed_context_tokens,
                observed_source=observed_source,
                chat_options=getattr(resolved_connection, "chat_options", None),
                remote=getattr(resolved_connection, "locality", None) is ConnectionLocality.REMOTE,
            )
        else:
            execution_preset = resolved_connection.effective_preset
    execution_preset = apply_reasoning_policy(execution_preset, model_policy)
    try:
        execution_preset = apply_output_budget_policy(execution_preset, model_policy)
    except ValueError as error:
        raise HTTPException(400, detail={
            "code": "INVALID_MODEL_OUTPUT_BUDGET",
            "detail": str(error),
        }) from error
    query_execution_preset = model_rag_query_execution_preset(execution_preset)
    if canonical_execution_mode is CanonicalRouteMode.ACTIVE and resolved_connection is not None:
        retrieval_trace["model_execution_requested"] = {
            "provider": getattr(resolved_connection, "extension_type", None) or "model_connection",
            "model": resolved_connection.model_id,
        }
    preset_diagnostics = execution_preset.diagnostics(
        requested_input_tokens=(getattr(resolved_connection, "requested_context_tokens", cache_state.get("desired_kv_tokens"))
                                if canonical_execution_mode is CanonicalRouteMode.ACTIVE and resolved_connection is not None
                                else cache_state.get("desired_kv_tokens"))
    )
    preset_diagnostics["model_preset"]["requested"] = llm_runtime.model
    retrieval_trace["model_execution_profile"] = preset_diagnostics
    retrieval_trace["context_governor"] = {
        "schema": "les.context-governor.v1",
        "preset_id": execution_preset.preset_id,
        "calls": [],
    }
    memory_projection_stage = "project_memory"
    try:
        typed_memory = await asyncio.to_thread(
            project_memory,
            session_id=str(req.session_id or ""),
            project_id=memory_project_id or None,
            dataset_ids=tuple(str(item) for item in _dataset_ids if str(item)),
            limits=MemoryLimits(),
        )
        memory_projection_stage = "context_candidates"
        memory_candidates = typed_memory.as_context_candidates()
        memory_projection_stage = "trace_projection"
        retrieval_trace["typed_memory"] = {
            "schema": "les.typed-memory-projection.v1",
            "context_role": typed_memory.context_role,
            "is_evidence": False,
            "items": len(typed_memory.items),
            "omitted": typed_memory.omitted,
            "cursor": typed_memory.cursor,
            "project_id": typed_memory.project_id,
            "registered_session": workspace_memory_registered,
            "item_ids": [item.item_id for item in typed_memory.items],
            "omitted_item_ids": list(typed_memory.omitted_item_ids),
        }
    except Exception as memory_error:  # noqa: BLE001 - memory is advisory, never an answer blocker
        logger.warning("[TYPED_MEMORY] projection skipped: %s", type(memory_error).__name__)
        memory_candidates = ()
        retrieval_trace["typed_memory"] = {
            "schema": "les.typed-memory-projection.v1",
            "status": "skipped",
            "error_type": type(memory_error).__name__,
            "error_stage": memory_projection_stage,
            "context_role": "advisory_state",
            "is_evidence": False,
        }
    retrieval_trace["routing"] = {
        "configured_provider": configured_runtime.provider,
        "configured_model": configured_runtime.model,
        "effective_provider": llm_runtime.provider,
        "effective_model": llm_runtime.model,
        "sensitivity": _route.sensitivity,
        "downgraded": llm_runtime.provider != configured_runtime.provider,
        "is_cloud": is_cloud_provider(llm_runtime.provider),
    }
    if canonical_execution_mode is CanonicalRouteMode.ACTIVE and resolved_connection is not None:
        retrieval_trace["routing"].update(
            {
                "effective_provider": "model_connection",
                "effective_model": resolved_connection.model_id,
                "downgraded": False,
                "is_cloud": resolved_connection.locality is ConnectionLocality.REMOTE,
            }
        )
    if resolved_connection is not None:
        retrieval_trace["model_connection_candidate"] = {
            "revision_id": resolved_connection.revision_id,
            "locality": resolved_connection.locality.value,
            "effective": canonical_execution_mode is CanonicalRouteMode.ACTIVE,
            "resolution_error": connection_resolution_error,
        }
    llm_model = (
        resolved_connection.model_id
        if canonical_execution_mode is CanonicalRouteMode.ACTIVE and resolved_connection is not None
        else llm_runtime.model
    )
    val_url = (
        resolved_connection.base_url.rstrip("/")
        if canonical_execution_mode is CanonicalRouteMode.ACTIVE and resolved_connection is not None
        else llm_runtime.base_url.rstrip("/")
    )
    # Локальный MLX-хост всегда держит /api/validate (coreml NLI, ~0.1с). Облачные ответы
    # валидируем им же, а не повторным промптом в облако (это давало 3-11с на P1-ответ).
    local_val_url = _mlx_runtime().base_url.rstrip("/")
    if not llm_model:
        raise HTTPException(503, f"LLM model is not configured for provider {llm_runtime.provider}")
    # W3.4-частично (вопрос оператора 2026-06-14 «почему не валидируем облаком?»):
    # у не-MLX провайдеров нет /api/validate — валидируем ТОЙ ЖЕ моделью
    # компактным промптом-вердиктом (VERIFIED/HALLUCINATION/NO_DATA).
    validate_via_llm = bool(
        use_validation
        and (
            canonical_execution_mode is CanonicalRouteMode.ACTIVE
            or not llm_runtime.supports_validation
        )
    )
    if validate_via_llm:
        logger.info("[TOSKA] validation via provider=%s (no LES /api/validate)", llm_runtime.provider)

    # The central RAG role pack already owns engineering style, source boundaries,
    # navigation-vs-evidence and human-facing wording.  Repeating those rules here
    # used to add thousands of prompt characters and, worse, made the application
    # service a second hidden prompt registry.  Keep only the source-label contract
    # that is specific to the evidence packet rendered below.
    sys_normal = profile_system_prompt(profile_snapshot, strict=False)
    sys_strict = profile_system_prompt(profile_snapshot, strict=True)

    # ADR-12 слой 2: форму ответа диктует интент вопроса (детерминированно, до генерации).
    answer_form = apply_response_length(classify_answer_form(req.question), req.response_length)
    retrieval_trace["answer_form"] = {"intent": answer_form.intent, "max_tokens": answer_form.max_tokens}
    if class_suggestions:
        retrieval_trace["class_suggestions"] = [s["class"] for s in class_suggestions]

    # Облако не держит локальный Metal-слот: отдельный пул (LES_CLOUD_LLM_CONCURRENCY).

    t_gen_start = time.time()
    t_llm = 0.0  # W0.1: чистое время LLM-вызовов (включая загрузку модели на стороне MLX)
    t_val = 0.0  # W0.1: чистое время /api/validate
    answer_source_map: list[dict[str, object]] = []
    final_evidence_packet: dict[str, Any] = {}
    evidence_navigation: list[dict[str, Any]] = []
    if topic_retrieval_plan:
        evidence_navigation.append({
            "kind": "topic_selection",
            "available": True,
            "selected_files": len(topic_doc_filter),
            "context_role": "navigation",
            "is_evidence": False,
        })
    if dataset_memory_prompt:
        evidence_navigation.append({
            "kind": "dataset_memory",
            "available": True,
            "context_role": "navigation",
            "is_evidence": False,
        })
    if notebook_study_prompt:
        evidence_navigation.append({
            "kind": "notebook_study",
            "available": True,
            "context_role": "navigation",
            "is_evidence": False,
        })
    if target_file_ref:
        evidence_navigation.append({
            "kind": "target_file",
            "available": target_file_ref.get("match_status") == "matched",
            "match_status": str(target_file_ref.get("match_status") or ""),
            "context_role": "navigation",
            "is_evidence": False,
        })
    deterministic_evidence: list[dict[str, Any]] = []
    if project_inventory_payload:
        deterministic_evidence.append({
            "kind": "project_inventory",
            "source": "metadb.documents",
            "file_count": int(project_inventory_payload.get("file_count") or 0),
        })

    model_evidence_chunks = list(llm_chunks)
    model_requested_price_basis = {}

    def _build_model_evidence(current_chunks: Sequence[Any]):
        packet = build_retrieval_evidence_packet(
            question=req.question,
            chunks=current_chunks,
            retrieval_trace=retrieval_trace,
            navigation=evidence_navigation,
            deterministic_evidence=deterministic_evidence,
        )
        rendered = render_retrieval_evidence_for_model(
            packet,
            max_chars=context_chars_limit,
            include_metadata=True,
        )
        source_map = packet.source_map(
            max_chars=context_chars_limit,
            include_metadata=True,
        )
        return (
            packet,
            rendered,
            source_map,
            packet.to_dict(max_chars=context_chars_limit, include_metadata=True),
        )

    (
        initial_evidence_packet,
        context,
        answer_source_map,
        final_evidence_packet,
    ) = _build_model_evidence(model_evidence_chunks)
    retrieval_trace["evidence_packet"] = initial_evidence_packet.trace_summary(
        max_chars=context_chars_limit,
        include_metadata=True,
    )
    attachment_context = str(getattr(req, "attachment_context", "") or "").strip()
    if (profile_snapshot or {}).get("effective_skill_modules"):
        retrieval_trace["effective_skill_modules"] = list(profile_snapshot["effective_skill_modules"])
    source_incomplete_locators: list[str] = []
    answer_finish_reason = ""
    model_driven_retrieval = profile_uses_model_driven_retrieval(profile_snapshot)
    sheet_pass_active = sheet_pass_should_run(
        source_catalog,
        tabular_estimator_bound=tabular_estimator_bound,
        model_driven=model_driven_retrieval,
    )
    comparative_variant = str(
        getattr(req, "comparative_acceptance_variant", "") or ""
    ).upper()
    if comparative_variant == "B0_DIRECT":
        sheet_pass_active = False
    if comparative_variant:
        retrieval_trace["comparative_acceptance"] = {
            "variant": comparative_variant,
            "sheet_packet_harness": comparative_variant == "B1_CANDIDATE",
            "model_owned_query_rag_result": True,
        }
    sheet_pass_names = (
        catalog_work_sheet_names(source_catalog)
        if sheet_pass_active and source_catalog is not None
        else []
    )
    sheet_pass_first = sheet_pass_names[0] if sheet_pass_names else ""

    selector_evidence = selector_evidence_payload(
        attachment_context=attachment_context,
        rendered_context=initial_selector_context(
            context,
            model_authored_initial_query=model_driven_retrieval,
        ),
        source_catalog=source_catalog,
        sheet=sheet_pass_first,
        remaining_work=(
            catalog_sheet_work_locators(source_catalog, sheet_pass_first)
            if sheet_pass_first and source_catalog is not None
            else None
        ),
    )
    selector_source_map = answer_source_map
    async with acquire_generation_slot(
        gen_semaphore,
        timeout_seconds=generation_slot_timeout_seconds(),
    ):
        try:
            async with httpx.AsyncClient(timeout=model_answer_timeout_seconds()) as client:
                answer = ""
                crag_status = "UNKNOWN"
                tokens = 0
                active_model_result = None
                active_pending_tool_calls = 0
                artifact_kind_declaration = {"status": "missing", "artifact_kind": "", "declarations": [], "errors": []}
                bound_runner = None
                if canonical_execution_mode is CanonicalRouteMode.ACTIVE:
                    if connection_resolver is None or connection_secret_store is None:
                        raise HTTPException(503, "MODEL_CONNECTION_RESOLVER_REQUIRED")
                    bound_runner = BoundModelChatRunner(
                        resolver=connection_resolver,
                        transport=model_connection_transport(client, connection_secret_store),
                    )

                def _cloud_message_admission(preset, native_tools):
                    transport = getattr(bound_runner, "transport", None)
                    can_fit = getattr(transport, "cloud_request_fits", None)
                    connection = (getattr(active_model_result, "connection", None) or resolved_connection)
                    if (not callable(can_fit) or connection is None
                            or connection.locality is not ConnectionLocality.REMOTE
                            or not transport.cloud_budget_snapshot().get("limit_tokens")):
                        return None

                    def admit(messages):
                        return can_fit(connection, InferenceRequest(
                            messages=messages, tools=native_tools,
                            max_output_tokens=preset.generation_reserve_tokens,
                            temperature=profile_temperature(profile_snapshot, fallback=_env_float("CHAT_TEMPERATURE", 0.2)),
                            reasoning_enabled=preset.reasoning_enabled,
                        ))
                    return admit

                async def _post_llm(runtime, model, hdrs, body, *, allow_stream: bool = True,
                                    inference_preset: ModelExecutionPreset | None = None):
                    """Один вызов LLM. token_sink задан → стрим (токены клиенту по
                    мере генерации), иначе — обычный POST (поведение неизменно).
                    Возвращает (answer_text, usage_dict)."""
                    nonlocal active_model_result, active_pending_tool_calls
                    call_preset = inference_preset if inference_preset is not None else execution_preset
                    if not isinstance(call_preset, ModelExecutionPreset):
                        raise TypeError("model call needs a typed execution preset")
                    retrieval_trace["last_model_call_execution"] = {
                        "reasoning": call_preset.diagnostics()["reasoning"],
                    }
                    if bound_runner is not None:
                        inference_request = InferenceRequest(
                            messages=tuple(body.get("messages") or ()),
                            max_output_tokens=max(
                                1,
                                int(
                                    body.get("max_completion_tokens")
                                    or body.get("max_tokens")
                                    or 1
                                ),
                            ),
                            temperature=body.get("temperature"),
                            tools=tuple(body.get("tools") or ()),
                            response_format=body.get("response_format"),
                            reasoning_enabled=call_preset.reasoning_enabled,
                        )

                        async def no_legacy_call(_request):
                            raise RuntimeError("LEGACY_MODEL_CALL_FORBIDDEN_IN_ACTIVE_MODE")

                        sensitivities = _dataset_sensitivities(
                            set(_dataset_ids_from_chunks(chunks))
                            | {str(item) for item in (_dataset_ids or [])}
                        )
                        try:
                            active_model_result = await bound_runner.complete(
                                mode=canonical_execution_mode,
                                request=inference_request,
                                legacy_complete=no_legacy_call,
                                remote_allowed=cloud_allowed(
                                    sensitivities,
                                    consent=_env_bool("LES_CLOUD_CONSENT", False),
                                ),
                            )
                        finally:
                            budget_snapshot = getattr(getattr(bound_runner, "transport", None), "cloud_budget_snapshot", None)
                            if callable(budget_snapshot):
                                retrieval_trace["cloud_token_budget"] = budget_snapshot()
                                if token_sink is not None and retrieval_trace["cloud_token_budget"].get("limit_tokens"):
                                    await token_sink({"event": "cloud_budget", "data": retrieval_trace["cloud_token_budget"]})
                        active_pending_tool_calls += active_model_result.pending_tool_calls
                        if (token_sink is not None and allow_stream and active_model_result.response.text
                                and not active_model_result.response.tool_calls
                                and not has_unconsumed_tool_frame(active_model_result.response.text)):
                            await token_sink(
                                {"event": "token", "data": active_model_result.response.text}
                            )
                        retrieval_trace["model_connection"] = (
                            active_model_result.public_connection_payload()
                        )
                        retrieval_trace["model_connection"]["provider"] = (
                            getattr(active_model_result.connection, "extension_type", None) or "model_connection"
                        )
                        retrieval_trace["model_connection"]["pending_tool_calls"] = active_pending_tool_calls
                        model_text = active_model_result.response.text
                        if active_model_result.response.tool_calls:
                            canonical_calls: list[dict[str, Any]] = []
                            for raw_call in active_model_result.response.tool_calls:
                                raw_function = raw_call.get("function")
                                function = raw_function if isinstance(raw_function, Mapping) else {}
                                raw_arguments = function.get("arguments")
                                try:
                                    arguments = (
                                        json.loads(raw_arguments)
                                        if isinstance(raw_arguments, str)
                                        else dict(raw_arguments)
                                    )
                                except (TypeError, ValueError, json.JSONDecodeError):
                                    arguments = {}
                                canonical_calls.append(
                                    {
                                        "call_id": raw_call.get("id"),
                                        "tool": str(function.get("name") or ""),
                                        "args": arguments,
                                        "native_arguments": raw_arguments if isinstance(raw_arguments, str)
                                        else json.dumps(raw_arguments, ensure_ascii=False, separators=(",", ":")),
                                    }
                                )
                            native_payload = {"calls": canonical_calls, "native_assistant_content": model_text}
                            if active_model_result.response.reasoning_content is not None:
                                native_payload["native_reasoning_content"] = active_model_result.response.reasoning_content
                            model_text = json.dumps(
                                native_payload,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                        return (
                            model_text,
                            usage_with_finish_reason(
                                dict(active_model_result.response.usage),
                                active_model_result.response.finish_reason,
                            ),
                        )
                    if getattr(runtime, "uses_native_chat", False):
                        # #1b: нативный /api/chat think:false → чистый ответ без CoT-дампа
                        # (OpenAI-compat ollama игнорирует reasoning-контроль). Облачного
                        # fallback у ollama нет — model == runtime.model.
                        return await _ollama_native_complete(
                            client, runtime, body["messages"],
                            max_tokens=int(body.get("max_tokens", 1400)),
                            temperature=float(body.get("temperature", 0.7)),
                            headers=hdrs, token_sink=token_sink if allow_stream else None)
                    _body = apply_transport_options(
                        _cloud_body_for_model(body, model, runtime.provider), runtime.provider,
                        reasoning_enabled=call_preset.reasoning_enabled,
                    )
                    if token_sink is not None and allow_stream:
                        sbody = {**_body, "model": model, "stream": True}
                        # include_usage нужен только облаку (учёт $); MLX/локальные —
                        # не шлём, чтобы не рисковать 400 на незнакомом поле.
                        if is_cloud_provider(runtime.provider):
                            sbody["stream_options"] = {"include_usage": True}
                        acc: list[str] = []
                        final_filter = FinalTextFilter()
                        usage_d: dict = {}
                        stream_finish = ""
                        async with client.stream("POST", runtime.chat_url, headers=hdrs, json=sbody) as sresp:
                            sresp.raise_for_status()
                            async for line in sresp.aiter_lines():
                                if not line or not line.startswith("data:"):
                                    continue
                                payload = line[5:].strip()
                                if payload == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(payload)
                                except json.JSONDecodeError:
                                    continue
                                choices = chunk.get("choices") or []
                                _delta = choices[0].get("delta", {}) if choices else {}
                                piece = final_filter.feed(assistant_delta_text(_delta))
                                if piece:
                                    acc.append(piece)
                                    await token_sink({"event": "token", "data": piece})
                                if choices:
                                    stream_finish = str(
                                        choices[0].get("finish_reason") or stream_finish
                                    )
                                if chunk.get("usage"):
                                    usage_d = chunk["usage"]
                        return "".join(acc), usage_with_finish_reason(usage_d, stream_finish)
                    r = await client.post(runtime.chat_url, headers=hdrs, json={**_body, "model": model})
                    r.raise_for_status()
                    rj = r.json()
                    choice = (rj.get("choices") or [{}])[0]
                    final_message = dict(choice.get("message") or {})
                    final_message["content"] = final_assistant_text(final_message)
                    final_message.pop("reasoning", None)
                    final_message.pop("reasoning_content", None)
                    return (
                        final_message["content"] or _assistant_text(final_message),
                        usage_with_finish_reason(
                            rj.get("usage", {}) or {},
                            str(choice.get("finish_reason") or ""),
                        ),
                    )

                async def _post_cloud_fallback(
                    runtime, hdrs, body, *, allow_stream: bool = True,
                    inference_preset: ModelExecutionPreset | None = None,
                ):
                    """Облако: перебор цепочки моделей с конечным таймаутом на модель.
                    Зависла/ошиблась/пустой ответ → следующая. Возвращает
                    (answer, usage, used_model); все упали → последняя ошибка."""
                    models = cloud_fallback_models(runtime)
                    per_model = cloud_model_timeout()
                    last_err: Exception = ValueError("облако: цепочка моделей пуста")
                    for i, m in enumerate(models):
                        # частичный вывод прошлой модели в стриме — отбросить
                        if token_sink is not None and i > 0:
                            await token_sink({"event": "reset", "data": ""})
                        try:
                            ans, usage_m = await asyncio.wait_for(
                                _post_llm(
                                    runtime,
                                    m,
                                    hdrs,
                                    body,
                                    allow_stream=allow_stream,
                                    inference_preset=inference_preset,
                                ),
                                timeout=per_model,
                            )
                            if ans:
                                if i > 0:
                                    logger.warning("[ROUTE] облако: модель %s сработала после %s", m, models[:i])
                                return ans, usage_m, m
                            last_err = ValueError(f"пустой ответ от {m}")
                            logger.warning("[ROUTE] облако: %s дала пустой ответ — следующая модель", m)
                        except (asyncio.TimeoutError, httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
                            last_err = e
                            logger.warning("[ROUTE] облако: %s не ответила (%s) — следующая модель", m, type(e).__name__)
                    raise last_err

                tool_results_for_model: list[dict[str, Any]] = []
                research_native_exchanges: list[NativeToolExchange] = []
                research_legacy_results: list[dict[str, Any]] = []
                workbook_chat_meta: dict[str, Any] = {}
                tool_context = ""
                model_rag_query_hits: list[tuple[str, Sequence[Any]]] = []
                rejected_model_queries: list[str] = []
                omitted_evidence_refs: list[str] = []
                model_rag_evidence_groups: list[str] = []
                sheet_pass_done = False
                sheet_pass_rows: list[dict[str, Any]] = []
                research_cancelled = False
                # Durable research-job handles stay unbound unless the sheet-pass
                # route initializes them; the packaging tail reads them regardless,
                # so they are pre-bound to None here (local annotations are not
                # evaluated at runtime).
                research_job_service: WorkbookResearchJobService | None = None
                research_job: dict[str, Any] | None = None
                visual_tool_requested = any(
                    marker in str(req.question or "").casefold().replace("ё", "е")
                    for marker in ("посмотри глазами", "посмотри чертеж", "посмотри схему", "что видно на лист", "что изображено на лист")
                )
                profile_tools = [
                    str(name) for name in (profile_snapshot or {}).get("tools", []) if str(name).strip()
                ]
                web_research_config = capture_web_research_config()
                selected_sources_only = bool(
                    getattr(req, "selected_sources_only", False)
                )
                profile_tools = filter_profile_tools(
                    profile_tools,
                    selected_sources_only=selected_sources_only,
                )
                profile_tools = web_tools_for_request(
                    profile_tools,
                    web_research_config,
                )
                retrieval_trace["capability_scope"] = {
                    "selected_sources_only": selected_sources_only,
                    "public_web_available": not selected_sources_only,
                    "web_research": public_web_research_config(web_research_config),
                    "web_reader_available": (
                        not selected_sources_only
                        and web_research_config.mode == "extended"
                        and "web_read" in profile_tools
                    ),
                    "source": "explicit_or_frozen_request",
                }
                profile_tools = tools_for_document_scope(
                    profile_tools,
                    enabled=document_grounding_enabled,
                )
                if canonical_execution_mode is not CanonicalRouteMode.ACTIVE:
                    profile_tools = [
                        name
                        for name in profile_tools
                        if name not in {"build_lsr_workbook", "build_vor_workbook"}
                    ]
                route_trace = canonical_route_trace_payload(
                    canonical_route,
                    execution_mode=canonical_execution_mode,
                    candidate_acceptance=candidate_acceptance,
                )
                retrieval_trace["canonical_route"] = route_trace
                retrieval_trace["route_comparison"] = {
                    "schema": "les.canonical-route-comparison.v1",
                    "requested": route_trace["requested"],
                    "effective": route_trace["effective"],
                    "legacy_output_authoritative": (
                        canonical_execution_mode is not CanonicalRouteMode.ACTIVE
                    ),
                    "same_request": True,
                    "profile_revision": str(
                        (profile_snapshot or {}).get("revision_id") or ""
                    ),
                    "canonical_provider_calls_added": 0,
                    "persisted_effects": 0,
                }
                if candidate_acceptance:
                    retrieval_trace["route_comparison"]["candidate_acceptance"] = True
                canonical_shadow_recorded = False
                tool_loop_enabled = bool(profile_tools)
                query_headers: dict[str, str] = {}
                model_research_tools = None
                retrieval_limits = effective_retrieval_policy(profile_snapshot)
                query_failure_final_texts: list[str] = []
                if model_driven_retrieval and tool_loop_enabled and not sheet_pass_active:
                    retrieval_limits = effective_retrieval_policy(profile_snapshot)
                    query_headers = {}
                    if llm_runtime.api_key:
                        query_headers["Authorization"] = f"Bearer {llm_runtime.api_key}"
                    query_instructions = [
                        model_rag_query_instruction(profile_snapshot),
                        (
                            model_rag_query_instruction(profile_snapshot)
                            + "\n\n"
                            + _MODEL_RAG_QUERY_REPAIR_INSTRUCTION
                        ),
                    ]
                    model_queries = []
                    rejected_model_queries = []
                    for query_attempt, query_instruction in enumerate(query_instructions, start=1):
                        query_messages, query_packet = govern_inference_messages(
                            preset=query_execution_preset,
                            profile_prefix=(
                                profile_system_prompt(profile_snapshot, strict=False)
                                + "\n\n"
                                + query_instruction
                            ),
                            request_payload={
                                "question": str(req.question or ""),
                                "dataset_ids": [str(item) for item in _dataset_ids],
                            },
                            checkpoint=(),
                            working_memory=workspace_note_objects(
                                memory_candidates, registered=workspace_memory_registered,
                            ),
                            evidence=selector_evidence,
                            source_map=selector_source_map,
                            tool_exchange=(),
                        )
                        retrieval_trace["context_governor"]["calls"].append(
                            context_packet_trace(
                                query_packet,
                                purpose=(
                                    "model_rag_queries"
                                    if query_attempt == 1
                                    else "model_rag_query_repair"
                                ),
                            )
                        )
                        query_budget = governed_query_generation_budget(query_execution_preset, query_packet)
                        query_body = {
                            "messages": query_messages,
                            "stream": False,
                            "temperature": 0,
                            "max_tokens": query_budget["effective"],
                        }
                        t_query_model = time.time()
                        query_text, query_usage = await _post_llm(
                            llm_runtime,
                            llm_model,
                            query_headers,
                            query_body,
                            allow_stream=False,
                            inference_preset=query_execution_preset,
                        )
                        t_llm += time.time() - t_query_model
                        append_actual_model_call(
                            retrieval_trace, purpose="model_rag_queries" if query_attempt == 1 else "model_rag_query_repair",
                            finish_reason=llm_usage_finish_reason(query_usage),
                            completion_tokens=int(query_usage.get("completion_tokens") or 0))
                        query_diagnostic = model_query_output_diagnostics(
                            query_text, query_usage, purpose="model_rag_queries" if query_attempt == 1 else "model_rag_query_repair",
                            budget=query_budget,
                        )
                        retrieval_trace.setdefault("model_query_outputs", []).append(query_diagnostic)
                        query_failure_final_texts.append(query_text)
                        query_failure_final_texts = query_failure_final_texts[-8:]
                        declared = read_model_query_response(
                            query_text, instruction=query_instruction, finish_reason=llm_usage_finish_reason(query_usage))
                        artifact_kind_declaration = merge_model_artifact_kind(
                            artifact_kind_declaration, declared["artifact_kind_declaration"])
                        query_diagnostic["declared_parse"] = declared_query_output_diagnostics(query_text, declared)
                        logger.info("[MODEL_RAG_QUERY_OUTPUT] %s", query_diagnostic)
                        if query_diagnostic["output_incomplete"]:
                            raise model_query_failure({"error": "MODEL_QUERY_OUTPUT_INCOMPLETE"}, trace=retrieval_trace,
                                session_id=req.session_id, provider=llm_runtime.provider, model=llm_model,
                                secret_values=(llm_runtime.api_key,), final_texts=query_failure_final_texts)
                        model_queries = [item.text for item in declared["queries"]]
                        rejected_model_queries = [str(item.get("line") or "") for item in declared["accompanying_answer"]]
                        if model_queries or declared.get("intentional_empty"):
                            break
                    if not model_queries and not declared.get("intentional_empty"):
                        raise model_query_failure("MODEL_RAG_QUERY_LIST_EMPTY", trace=retrieval_trace,
                            session_id=req.session_id, provider=llm_runtime.provider, model=llm_model,
                            secret_values=(llm_runtime.api_key,), final_texts=query_failure_final_texts)

                    async def _sheet_read_source_fallback(tool_name: str, args: dict[str, Any]):
                        # The executor validates selected dataset / shown document
                        # scope. No workbook mutations are exposed in this turn.
                        if tool_name != "read_source":
                            raise ValueError("unsupported sheet evidence read")
                        from proxy.services.tool_harness_service import harness
                        return await asyncio.to_thread(
                            harness(web_config=web_research_config).call, tool_name, args
                        )

                    model_research_tools = ModelResearchToolService(
                        attachment_catalog=source_catalog,
                        expected_attachment_sha256=(source_catalog.source_file_sha256 if source_catalog else None),
                        retrieve=retrieve_chat_chunks,
                        frozen_dataset_ids=tuple(
                            str(item) for item in _dataset_ids if str(item)
                        ),
                        retrieval_kwargs={
                            "rag_backend": rag_backend,
                            "reranker_enabled": _reranker_on,
                            "reranker_available": state.reranker_available,
                            "reranker_cls": state.reranker_cls,
                            "mlx_url": os.getenv("MLX_URL", "http://127.0.0.1:8080"),
                            "logger": logger,
                            "llm_semaphore": state.llm_semaphore,
                            "return_trace": True,
                            "doc_filter": target_doc_filter or None,
                            "scope_source": str(
                                (scope_resolution or {}).get("scope_source") or "unspecified"
                            ),
                            "scope_error_code": str(
                                (scope_resolution or {}).get("error_code") or ""
                            ),
                        },
                        fallback=_sheet_read_source_fallback,
                        smeta_norm_retrieve=(
                            retrieve_smeta_norm_cards
                            if profile_uses_smeta_norm_retrieval(profile_snapshot)
                            else None
                        ),
                        **retrieval_limits,
                    )
                    for query in model_queries:
                        research_result = await model_research_tools.execute(
                            {"tool": "search_sources", "args": {"q": query}}
                        )
                        append_actual_search(retrieval_trace, cached=False, hit_count=len(research_result.chunks))
                        tool_results_for_model.append(research_result.payload)
                        model_rag_query_hits.append(
                            (
                                query,
                                tuple(research_result.chunks)[
                                    : retrieval_limits["model_evidence_k"]
                                ],
                            )
                        )
                    blocked_queries = [
                        index
                        for index, payload in enumerate(tool_results_for_model, 1)
                        if model_search_result_blocks_packet(payload)
                    ]
                    if blocked_queries:
                        raise HTTPException(
                            status_code=503,
                            detail={
                                "error": "MODEL_RAG_SEARCH_INCOMPLETE",
                                "blocked_queries": blocked_queries,
                            },
                        )
                    (
                        model_rag_evidence_groups,
                        model_evidence_chunks,
                        omitted_evidence_refs,
                    ) = build_model_rag_evidence_groups(
                        model_rag_query_hits,
                        max_chars=context_chars_limit,
                        hits_per_query=retrieval_limits["model_evidence_k"],
                        # Ordinary dataset turn: the model is the only query
                        # author, and ADR-16 says the turn states that instead of
                        # letting provenance fall to a default.
                        query_provenance=_model_only_query_provenance(
                            model_rag_query_hits
                        ),
                    )
                    context = "\n\n".join(model_rag_evidence_groups)
                    model_rag_evidence_packet = build_retrieval_evidence_packet(
                        question=req.question,
                        chunks=model_evidence_chunks,
                        retrieval_trace=retrieval_trace,
                        navigation=evidence_navigation,
                        deterministic_evidence=deterministic_evidence,
                    )
                    answer_source_map = _model_rag_source_map(model_evidence_chunks)
                    final_evidence_packet = model_rag_evidence_packet.to_dict(
                        max_chars=context_chars_limit,
                        include_metadata=True,
                    )
                    retrieval_trace["evidence_packet"] = (
                        model_rag_evidence_packet.trace_summary(
                            max_chars=context_chars_limit,
                            include_metadata=True,
                        )
                    )
                    tool_context = _format_tool_results_for_model(tool_results_for_model)
                    retrieval_trace["tool_loop"] = {
                        "schema": "les_model_rag_batch_v1",
                        "enabled": True,
                        "model_owns_queries": True,
                        "model_queries": model_queries,
                        "query_usage": query_usage,
                        "results": tool_results_for_model,
                        "evidence_groups": [
                            f"Q{index}" for index in range(1, len(model_rag_evidence_groups) + 1)
                        ],
                        "hits_per_query": [
                            len(hits) for _query, hits in model_rag_query_hits
                        ],
                        "rejected_queries": rejected_model_queries,
                        "omitted_evidence_refs": omitted_evidence_refs,
                    }
                elif model_driven_retrieval and tool_loop_enabled and sheet_pass_active:
                    retrieval_limits = effective_retrieval_policy(profile_snapshot)
                    query_headers = {}
                    if llm_runtime.api_key:
                        query_headers["Authorization"] = f"Bearer {llm_runtime.api_key}"

                    async def _sheet_read_source_fallback(tool_name: str, args: dict[str, Any]):
                        if tool_name != "read_source":
                            raise ValueError("unsupported sheet evidence read")
                        from proxy.services.tool_harness_service import harness
                        return await asyncio.to_thread(
                            harness(web_config=web_research_config).call, tool_name, args
                        )

                    model_research_tools = ModelResearchToolService(
                        attachment_catalog=source_catalog,
                        expected_attachment_sha256=(source_catalog.source_file_sha256 if source_catalog else None),
                        retrieve=retrieve_chat_chunks,
                        frozen_dataset_ids=tuple(
                            str(item) for item in _dataset_ids if str(item)
                        ),
                        retrieval_kwargs={
                            "rag_backend": rag_backend,
                            "reranker_enabled": _reranker_on,
                            "reranker_available": state.reranker_available,
                            "reranker_cls": state.reranker_cls,
                            "mlx_url": os.getenv("MLX_URL", "http://127.0.0.1:8080"),
                            "logger": logger,
                            "llm_semaphore": state.llm_semaphore,
                            "return_trace": True,
                            "doc_filter": target_doc_filter or None,
                            "scope_source": str(
                                (scope_resolution or {}).get("scope_source") or "unspecified"
                            ),
                            "scope_error_code": str(
                                (scope_resolution or {}).get("error_code") or ""
                            ),
                        },
                        fallback=_sheet_read_source_fallback,
                        smeta_norm_retrieve=(
                            retrieve_smeta_norm_cards
                            if profile_uses_smeta_norm_retrieval(profile_snapshot)
                            else None
                        ),
                        **retrieval_limits,
                    )
                    retrieval_trace["tool_loop"] = {
                        "schema": "les_model_rag_sheet_pass_v1",
                        "enabled": True,
                        "model_owns_queries": True,
                        "passes": [],
                    }
                elif tool_loop_enabled:
                    retrieval_limits = effective_retrieval_policy(profile_snapshot)
                    tool_loop_stage = "harness"
                    try:
                        from proxy.services.tool_harness_service import harness

                        tool_harness = harness(web_config=web_research_config)

                        async def _fallback_model_tool(tool_name: str, args: dict[str, Any]):
                            return await asyncio.to_thread(tool_harness.call, tool_name, args)

                        model_research_tools = ModelResearchToolService(
                            attachment_catalog=source_catalog,
                            expected_attachment_sha256=(source_catalog.source_file_sha256 if source_catalog else None),
                            retrieve=retrieve_chat_chunks,
                            frozen_dataset_ids=tuple(str(item) for item in _dataset_ids if str(item)),
                            retrieval_kwargs={
                                "rag_backend": rag_backend,
                                "reranker_enabled": _reranker_on,
                                "reranker_available": state.reranker_available,
                                "reranker_cls": state.reranker_cls,
                                "mlx_url": os.getenv("MLX_URL", "http://127.0.0.1:8080"),
                                "logger": logger,
                                "llm_semaphore": state.llm_semaphore,
                                "return_trace": True,
                                "doc_filter": None,
                                "scope_source": str(
                                    (scope_resolution or {}).get("scope_source") or "unspecified"
                                ),
                                "scope_error_code": str(
                                    (scope_resolution or {}).get("error_code") or ""
                                ),
                            },
                            fallback=_fallback_model_tool,
                            **retrieval_limits,
                        )
                        shortlist_limit = (
                            len(profile_tools)
                            if model_driven_retrieval
                            else min(
                                execution_preset.max_tools,
                                max(1, _env_int("LES_CHAT_TOOL_SHORTLIST_LIMIT", 64)),
                            )
                        )
                        configured_call_limit = max(
                            1, _env_int("LES_CHAT_TOOL_MAX_CALLS", 48)
                        )
                        max_calls = (
                            configured_call_limit
                            if model_driven_retrieval
                            else min(execution_preset.max_batch_items, configured_call_limit)
                        )
                        workbook_phase = bool(
                            getattr(req, "attachment_id", None)
                            and {"build_lsr_workbook", "build_vor_workbook"}.intersection(profile_tools)
                        )
                        profile_tools = prioritize_workbook_tools(
                            profile_tools,
                            workbook_phase=workbook_phase,
                            question=str(getattr(req, "question", "") or ""),
                        )
                        tool_loop_stage = "shortlist"
                        from proxy.services.workbook_tool_service import (
                            available_chat_workbook_tools,
                        )

                        runtime_available_tools = set(profile_tools).difference(
                            {"build_lsr_workbook", "build_vor_workbook"}
                        )
                        runtime_available_tools.update(
                            available_chat_workbook_tools(
                                executor_configured=workbook_tool_executor is not None
                            )
                        )
                        runtime_available_tools.intersection_update(profile_tools)
                        shortlist = await asyncio.to_thread(
                            tool_harness.shortlist,
                            req.question,
                            mode=str(req.mode or route.intent or ""),
                            allowed_tools=profile_tools,
                            limit=shortlist_limit,
                            dataset_ids=tuple(str(item) for item in _dataset_ids if str(item)),
                            workflow_phase="draft" if workbook_phase else "research",
                            model_preset=execution_preset.preset_id,
                            runtime_available=frozenset(runtime_available_tools),
                            calls_remaining=max_calls,
                            result_chars_remaining=35_000,
                            **(
                                {"attachment_ids": (str(req.attachment_id),)}
                                if getattr(req, "attachment_id", None)
                                else {}
                            ),
                        )
                        allowed_tools = {
                            str(tool.get("name") or "")
                            for tool in shortlist.get("tools", [])
                            if isinstance(tool, dict) and tool.get("name")
                        }
                        native_tools = native_model_tool_schemas(
                            shortlist.get("tools") or []
                        )
                        selector_headers = {}
                        if llm_runtime.api_key:
                            selector_headers["Authorization"] = f"Bearer {llm_runtime.api_key}"
                        selected_calls: list[dict[str, Any]] = []
                        selector_usage: list[dict[str, Any]] = []
                        research_rounds: list[dict[str, Any]] = []
                        research_deadline_seconds = max(
                            1.0,
                            _env_float("LES_CHAT_RESEARCH_DEADLINE_SECONDS", 120.0),
                        )
                        research_deadline = time.monotonic() + research_deadline_seconds
                        research_round = 0
                        calls_remaining = max_calls
                        unexecuted_native_call_count = 0
                        stop_reason = "deadline"
                        research_legacy_results = list(tool_results_for_model)
                        while time.monotonic() < research_deadline and calls_remaining > 0:
                            research_round += 1
                            prior_results = [
                                _compact_tool_result_for_prompt(item, max_chars=2400)
                                for item in research_legacy_results[-max_calls:]
                            ]
                            tool_call_instruction = (
                                "Вызывай предоставленные инструменты напрямую. "
                                if canonical_execution_mode is CanonicalRouteMode.ACTIVE
                                else "Верни только JSON {\"calls\":[{\"tool\":\"...\",\"args\":{...}}]}. "
                            )
                            selector_profile = "".join(
                                (
                                    profile_tool_selector_prompt(profile_snapshot),
                                    "\n\nТы управляешь коротким исследовательским чтением LES. ",
                                    "Явно прикреплённый текст ниже уже доступен тебе как evidence и не требует индексации. "
                                    "Сначала прочитай его и используй read-only инструменты, чтобы закрыть конкретные пробелы. "
                                    "Если оператор просит артефакт, после получения достаточного evidence вызови "
                                    "подходящий draft-инструмент; предметные решения и поисковые запросы выбираешь ты. "
                                    "Не объявляй вложение отсутствующим, когда его текст присутствует в пакете. ",
                                    "Если оператор явно просит посмотреть глазами страницу или лист PDF, ",
                                    "обязательно выбери look_at_pdf_page с указанными файлом и номером страницы; ",
                                    "текстовый read_pdf_source не заменяет просмотр пикселей. ",
                                    "Инструменты не отвечают за тебя и не заменяют источники. ",
                                    tool_call_instruction,
                                    "Если evidence достаточно, заверши исследование без нового вызова. ",
                                    "Не выбирай инструмент вне списка и не выходи за выбранные dataset/file scope.",
                                )
                            )
                            selector_checkpoint = tuple(
                                item
                                for candidate in memory_candidates
                                if candidate.kind == ContextKind.CHECKPOINT
                                for item in candidate.objects
                            )
                            selector_working_memory = tuple(
                                item
                                for candidate in memory_candidates
                                if candidate.kind == ContextKind.WORKING_MEMORY
                                for item in candidate.objects
                            )
                            if model_driven_retrieval:
                                # The estimator's first job is to read the
                                # attachment and author RAG queries. Advisory
                                # memory must not displace that evidence.
                                selector_working_memory = ()
                            tool_loop_stage = "context_governor"
                            selector_messages, selector_packet = govern_inference_messages(
                                preset=execution_preset,
                                profile_prefix=selector_profile,
                                request_payload=tool_selector_request_payload(
                                    question=req.question,
                                    mode=req.mode or route.intent or "",
                                    dataset_ids=_dataset_ids,
                                    target_file_ref=target_file_ref,
                                    round_no=research_round,
                                    attachment_id=getattr(req, "attachment_id", None),
                                ),
                                shortlist=selector_context_shortlist(
                                    shortlist.get("tools") or [],
                                    native_tool_schemas=(
                                        canonical_execution_mode is CanonicalRouteMode.ACTIVE
                                    ),
                                ),
                                checkpoint=selector_checkpoint,
                                working_memory=selector_working_memory,
                                evidence=selector_evidence,
                                source_map=selector_source_map,
                                tool_exchange=prior_results,
                                native_tools=native_tools if canonical_execution_mode is CanonicalRouteMode.ACTIVE else (),
                                native_exchanges=research_native_exchanges,
                            )
                            retrieval_trace["context_governor"]["calls"].append(
                                context_packet_trace(selector_packet, purpose="tool_decision")
                            )
                            selector_body = {
                                "messages": selector_messages,
                                "stream": False,
                                "temperature": 0,
                                "max_tokens": max(128, _env_int("LES_CHAT_TOOL_SELECTOR_MAX_TOKENS", 700)),
                            }
                            if canonical_execution_mode is CanonicalRouteMode.ACTIVE:
                                selector_body["tools"] = native_tools
                            t_tool_selector = time.time()
                            tool_loop_stage = "selector_model"
                            selector_text, round_usage = await _post_llm(
                                llm_runtime,
                                llm_model,
                                selector_headers,
                                selector_body,
                                allow_stream=False,
                            )
                            t_llm += time.time() - t_tool_selector
                            selector_usage.append(round_usage)
                            tool_loop_stage = "selector_parse"
                            proposed_calls = [
                                _augment_model_tool_args(
                                    call,
                                    question=req.question,
                                    dataset_ids=[str(d) for d in _dataset_ids],
                                    target_file_ref=target_file_ref,
                                )
                                for call in _parse_model_tool_calls(
                                    selector_text,
                                    allowed_tools=allowed_tools,
                                    max_calls=calls_remaining,
                                )
                            ]
                            if (
                                not canonical_shadow_recorded
                                and canonical_execution_mode is CanonicalRouteMode.SHADOW
                            ):
                                tool_loop_stage = "shadow_decision"
                                shadow_trace = await safe_execute_canonical_shadow_decision(
                                        proposed_calls=proposed_calls,
                                        allowed_tools=allowed_tools,
                                        dataset_ids=[str(item) for item in _dataset_ids],
                                        tool_harness=tool_harness,
                                    )
                                shadow_trace.update(
                                    profile_revision=str(
                                        (profile_snapshot or {}).get("revision_id") or ""
                                    ),
                                    persisted_effects=0,
                                )
                                retrieval_trace["canonical_shadow"] = shadow_trace
                                canonical_shadow_recorded = True
                            calls = list(proposed_calls[:calls_remaining])
                            native_response = (
                                active_model_result.response
                                if canonical_execution_mode is CanonicalRouteMode.ACTIVE and active_model_result is not None
                                else None
                            )
                            if native_response is not None and len(native_response.tool_calls) > calls_remaining:
                                # A native assistant batch and all matching replies
                                # are indivisible. Retain completed exchanges but
                                # execute none of a batch that exceeds the budget.
                                unexecuted_native_call_count = len(native_response.tool_calls)
                                active_pending_tool_calls += unexecuted_native_call_count
                                research_rounds.append({
                                    "round": research_round, "proposed": unexecuted_native_call_count,
                                    "executed": 0, "unexecuted": unexecuted_native_call_count,
                                    "reason": "calls_budget",
                                })
                                stop_reason = "calls_budget"
                                break
                            native_calls = native_research_call_batch(
                                native_response, calls, research_native_exchanges,
                            )
                            native_payloads: list[dict[str, Any]] = []
                            research_rounds.append(
                                {"round": research_round, "proposed": len(proposed_calls), "executed": len(calls)}
                            )
                            if not calls:
                                stop_reason = "model_stop"
                                break
                            for call in calls:
                                tool_loop_stage = "tool_execution"
                                tool_name = str(call.get("tool") or "")
                                model_packaging_job: dict[str, Any] = {}
                                if (
                                    tool_name in {"build_lsr_workbook", "build_vor_workbook"}
                                    and canonical_execution_mode is CanonicalRouteMode.ACTIVE
                                    and workbook_tool_executor is not None
                                ):
                                    native_kind = "vor" if tool_name == "build_vor_workbook" else "lsr"
                                    artifact_kind_declaration = merge_model_artifact_kind(artifact_kind_declaration,
                                        {"status": "declared", "artifact_kind": native_kind, "declarations": [native_kind], "errors": []})
                                    async def workbook_progress(event: dict[str, Any]) -> None:
                                        if token_sink is not None:
                                            await token_sink({"event": "tool_progress", "data": event})

                                    # § 4 holds on the route where the model itself
                                    # asked for the file: the model chooses *which*
                                    # tool runs, the document still carries the
                                    # region, period and book its own revisions were
                                    # priced in.  Without this the first packaging
                                    # of a document could happen here, leave no
                                    # durable basis behind, and every later
                                    # continuation would report «Ценовая база не
                                    # задана явно» over a priced file.
                                    if tool_name == "build_lsr_workbook":
                                        model_packaging_job = (
                                            workbook_research_job_for_document(
                                                attachment_id=str(
                                                    getattr(req, "attachment_id", None) or ""
                                                ),
                                                source_sha256=str(
                                                    getattr(
                                                        source_catalog,
                                                        "source_file_sha256",
                                                        "",
                                                    )
                                                    or ""
                                                ),
                                            )
                                        )
                                        carried_basis = model_packaging_document_basis(
                                            model_packaging_job
                                        )
                                        call_args = call.get("args")
                                        if carried_basis and isinstance(call_args, dict):
                                            call_args.setdefault(
                                                "document_price_basis", carried_basis
                                            )

                                    payload = ({"status": "failed", "code": "ARTIFACT_KIND_UNRESOLVED",
                                                "message": "Тип документа неоднозначен; упаковка ожидает согласованного решения модели."}
                                               if artifact_kind_declaration.get("status") in {"conflict", "invalid"}
                                               else await workbook_tool_executor(
                                        call,
                                        {
                                            "session_id": str(req.session_id or ""),
                                            "question": str(req.question or ""),
                                            "dataset_ids": [str(item) for item in _dataset_ids],
                                            "project_id": getattr(req, "project_id", None),
                                            "attachment_id": str(getattr(req, "attachment_id", None) or ""),
                                            "profile_revision_id": str((profile_snapshot or {}).get("revision_id") or ""),
                                            "model_identity": str(
                                                getattr(
                                                    getattr(active_model_result, "connection", None),
                                                    "model_id",
                                                    "",
                                                )
                                                or llm_model
                                            ),
                                            "model_preset": execution_preset.preset_id,
                                        },
                                        workbook_progress,
                                    ))
                                else:
                                    research_result = await model_research_tools.execute(call)
                                    payload = research_result.payload
                                    if research_result.chunks:
                                        known_chunk_ids = {
                                            str((getattr(item, "meta", {}) or {}).get("chunk_id") or "")
                                            or hashlib.sha256(
                                                (
                                                    str(getattr(item, "doc_name", "") or "")
                                                    + "\x00"
                                                    + str(getattr(item, "content", "") or "")
                                                ).encode("utf-8")
                                            ).hexdigest()
                                            for item in chunks
                                        }
                                        for found_chunk in research_result.chunks:
                                            found_id = str(
                                                (getattr(found_chunk, "meta", {}) or {}).get("chunk_id") or ""
                                            ) or hashlib.sha256(
                                                (
                                                    str(getattr(found_chunk, "doc_name", "") or "")
                                                    + "\x00"
                                                    + str(getattr(found_chunk, "content", "") or "")
                                                ).encode("utf-8")
                                            ).hexdigest()
                                            if found_id not in known_chunk_ids:
                                                chunks.append(found_chunk)
                                                known_chunk_ids.add(found_id)
                                        research_windows = expand_context_windows(
                                            chunks,
                                            collection=getattr(rag_backend, "collection_name", ""),
                                            logger=logger,
                                            max_chunks=context_max_chunks,
                                            max_chars_per_chunk=context_window_chars,
                                            radius=context_radius,
                                        )
                                        model_evidence_chunks = list(research_windows.chunks)
                                        (
                                            _research_evidence_packet,
                                            context,
                                            answer_source_map,
                                            final_evidence_packet,
                                        ) = _build_model_evidence(model_evidence_chunks)
                                        retrieval_trace["evidence_packet"] = (
                                            _research_evidence_packet.trace_summary(
                                                max_chars=context_chars_limit,
                                                include_metadata=True,
                                            )
                                        )
                                        selector_evidence = selector_evidence_payload(
                                            attachment_context=attachment_context,
                                            rendered_context=context,
                                            source_catalog=source_catalog,
                                        )
                                        selector_source_map = answer_source_map
                                selected_calls.append(call)
                                calls_remaining -= 1
                                safe_payload = safe_workbook_history_projection(payload)
                                visible_payload = safe_payload if safe_payload else payload
                                tool_results_for_model.append(visible_payload)
                                if native_calls:
                                    native_payloads.append(visible_payload)
                                else:
                                    research_legacy_results.append(visible_payload)
                                answer_source_map = _merge_web_source_map(
                                    answer_source_map,
                                    tool_results_for_model,
                                )
                                selector_source_map = answer_source_map
                                harvested = harvest_workbook_tool_result(safe_payload)
                                if harvested:
                                    # The revision this turn delivered belongs to
                                    # the document's own history, whoever asked for
                                    # it: recorded here, the next continuation
                                    # inherits its basis and its parent instead of
                                    # starting a second chain (§ 4, § 11 № 9).
                                    durable_event = model_packaging_record_arguments(
                                        job=model_packaging_job,
                                        tool=tool_name,
                                        harvested=harvested,
                                    )
                                    if durable_event:
                                        try:
                                            WorkbookResearchJobService().record_packaging(
                                                str(durable_event.pop("job_id")),
                                                **durable_event,
                                            )
                                        except Exception as record_error:  # noqa: BLE001 - durability degrades visibly
                                            logger.warning(
                                                "[WORKBOOK] model-packaged revision not "
                                                "recorded: %s",
                                                type(record_error).__name__,
                                            )
                                    workbook_chat_meta = harvested
                                    stop_reason = "workbook_complete"
                                    if not native_calls:
                                        break
                            if native_calls:
                                research_native_exchanges.append(native_research_exchange(
                                    native_calls, native_payloads,
                                    assistant_content=native_response.text,
                                    reasoning_content=native_response.reasoning_content,
                                ))
                            if workbook_chat_meta:
                                break
                            if calls_remaining <= 0:
                                stop_reason = "calls_budget"
                                break
                        tool_context = _format_tool_results_for_model(tool_results_for_model)
                        web_research_trace = public_web_research_config(
                            web_research_config
                        )
                        for web_payload in tool_results_for_model:
                            if str(web_payload.get("tool") or "") != "web_search":
                                continue
                            web_result = web_payload.get("result") or {}
                            if isinstance(web_result, Mapping):
                                web_research_trace.update(
                                    {
                                        "requested_mode": str(
                                            web_result.get("requested_mode")
                                            or web_research_config.mode
                                        ),
                                        "effective_mode": str(
                                            web_result.get("effective_mode")
                                            or web_research_config.mode
                                        ),
                                        "provider": str(web_result.get("provider") or ""),
                                        "degraded": bool(web_result.get("degraded")),
                                        "fallback_reason": str(
                                            web_result.get("fallback_reason") or ""
                                        ),
                                    }
                                )
                        retrieval_trace["tool_loop"] = {
                            "schema": "les_model_research_loop_v1",
                            "enabled": True,
                            "model_owns_selection": True,
                            "selector_model": llm_model,
                            "selector_provider": llm_runtime.provider,
                            "shortlist": shortlist,
                            "selected_calls": [
                                safe_selected_call_trace(call) for call in selected_calls
                            ],
                            "selector_usage": selector_usage,
                            "results": tool_results_for_model,
                            "rounds": research_rounds,
                            "stop_reason": stop_reason,
                            "deadline_seconds": research_deadline_seconds,
                            "max_calls_per_model_response": max_calls,
                            "max_calls_total": max_calls,
                            "calls_remaining": calls_remaining,
                            **({"unexecuted_native_call_count": unexecuted_native_call_count}
                               if unexecuted_native_call_count else {}),
                            "native_tool_schemas": bool(native_tools),
                            "web_research": web_research_trace,
                        }
                    except ContextRequiredSectionOverflow as context_error:
                        retrieval_trace["context_governor"]["error"] = {
                            "code": context_error.code,
                            "purpose": "tool_decision",
                            "budget": context_error.budget,
                            "required_tokens": context_error.required_tokens,
                            "required_objects": len(context_error.object_ids),
                        }
                        raise HTTPException(
                            422,
                            detail={
                                "code": context_error.code,
                                "message": "Обязательная часть выбора инструмента не помещается в безопасный контекст модели.",
                            },
                        ) from context_error
                    except Exception as tool_err:  # noqa: BLE001 - tool loop must degrade into trace, not block chat
                        logger.exception(
                            "[TOOLS] model tool loop skipped: %s",
                            type(tool_err).__name__,
                        )
                        retrieval_trace["tool_loop"] = {
                            "schema": "les_model_tool_loop_v1",
                            "enabled": True,
                            "status": "error",
                            "error_type": type(tool_err).__name__,
                            "error_stage": tool_loop_stage,
                        }
                else:
                    retrieval_trace["tool_loop"] = {
                        "schema": "les_model_research_loop_v1",
                        "enabled": False,
                        "reason": "disabled_by_operator",
                        "model_owns_final_answer": True,
                    }
                if (
                    canonical_execution_mode is CanonicalRouteMode.SHADOW
                    and not canonical_shadow_recorded
                ):
                    retrieval_trace["canonical_shadow"] = {
                        "schema": "les_canonical_shadow_v1",
                        "user_visible": False,
                        "persisted": False,
                        "status": "no_model_decision",
                        "executed_calls": 0,
                        "pending_calls": 0,
                        "profile_revision": str(
                            (profile_snapshot or {}).get("revision_id") or ""
                        ),
                        "persisted_effects": 0,
                    }
                # Keep the connection/preset-owned split between input and output.
                # Reserving 4096 tokens unconditionally for model-authored rows made
                # the profile + request overflow an 8K Qwen window before evidence
                # could reach the model at all.
                answer_execution_preset = model_rag_answer_execution_preset(
                    execution_preset, model_rag=model_driven_retrieval,
                )
                retrieval_trace["model_execution_profile"]["answer_output_tokens"] = (
                    answer_execution_preset.diagnostics()["answer_output_tokens"]
                )
                if (
                    sheet_pass_active
                    and model_driven_retrieval
                    and tool_loop_enabled
                    and source_catalog is not None
                    and sheet_pass_names
                ):
                    async def _emit_sheet_progress(
                        label: str,
                        *,
                        completed: int,
                        total: int,
                        extra: Mapping[str, Any] | None = None,
                    ) -> None:
                        if token_sink is None:
                            return
                        await token_sink(
                            {
                                "event": "tool_progress",
                                "data": {
                                    "label": label,
                                    "completed": completed,
                                    "total": total,
                                    **dict(extra or {}),
                                    **(
                                        {
                                            "workbook_research_job_id": str(
                                                research_job.get("job_id") or ""
                                            )
                                        }
                                        if research_job is not None
                                        else {}
                                    ),
                                },
                            }
                        )

                    # The answer display map changes after every packet. Query
                    # generation must retain its original scope plus evidence
                    # cited by this packet, not inherit another packet's map.
                    sheet_initial_source_map = list(selector_source_map)

                    async def _sheet_pass_llm(chat_body, *, purpose: str = "sheet_pass_answer",
                                              inference_preset: ModelExecutionPreset | None = None):
                        nonlocal llm_model
                        if canonical_execution_mode is CanonicalRouteMode.ACTIVE:
                            text, usage = await _post_llm(
                                llm_runtime,
                                llm_model,
                                (
                                    {"Authorization": f"Bearer {llm_runtime.api_key}"}
                                    if llm_runtime.api_key
                                    else {}
                                ),
                                chat_body,
                                allow_stream=False,
                                inference_preset=inference_preset,
                            )
                            if active_model_result is not None:
                                llm_model = active_model_result.connection.model_id
                        elif is_cloud_provider(llm_runtime.provider):
                            text, usage, llm_model = await _post_cloud_fallback(
                                llm_runtime,
                                (
                                    {"Authorization": f"Bearer {llm_runtime.api_key}"}
                                    if llm_runtime.api_key
                                    else {}
                                ),
                                chat_body,
                                allow_stream=False,
                                inference_preset=inference_preset,
                            )
                        else:
                            text, usage = await _post_llm(
                                llm_runtime,
                                llm_model,
                                (
                                    {"Authorization": f"Bearer {llm_runtime.api_key}"}
                                    if llm_runtime.api_key
                                    else {}
                                ),
                                chat_body,
                                allow_stream=False,
                                inference_preset=inference_preset,
                            )
                        append_actual_model_call(
                            retrieval_trace,
                            purpose=purpose,
                            finish_reason=llm_usage_finish_reason(usage),
                            completion_tokens=int(
                                (usage or {}).get("completion_tokens") or 0
                            ),
                        )
                        return text, usage

                    sheet_sys_msg = sys_normal + (
                        f" {answer_form.instruction}" if answer_form.instruction else ""
                    )
                    sheet_read_tools = model_evidence_read_tool_schemas()
                    sheet_sys_msg += "\n" + MODEL_EVIDENCE_READ_INSTRUCTION
                    if req.output_directive and req.output_directive.strip():
                        sheet_sys_msg += " " + req.output_directive.strip()
                    research_job_service: WorkbookResearchJobService | None = None
                    research_job: dict[str, Any] | None = None
                    attachment_id = str(getattr(req, "attachment_id", "") or "")
                    if attachment_id and source_catalog.source_file_sha256:
                        try:
                            research_job_service = WorkbookResearchJobService()
                            research_identity = research_job_service.identity(
                                session_id=str(req.session_id or ""),
                                attachment_id=attachment_id,
                                source_sha256=source_catalog.source_file_sha256,
                                dataset_ids=[str(item) for item in _dataset_ids],
                                profile_revision_id=str(
                                    (profile_snapshot or {}).get("revision_id") or ""
                                ),
                                model_identity=str(
                                    getattr(
                                        getattr(active_model_result, "connection", None),
                                        "model_id",
                                        "",
                                    )
                                    or llm_model
                                ),
                                question=str(req.question or ""),
                            )
                            from proxy.services.lsr_workbook_adapter_service import requested_price_basis
                            research_job = research_job_service.begin_or_resume(
                                research_identity,
                                source_locators=source_catalog.work_locators(),
                                task_context={
                                    "original_question": str(req.question or ""),
                                    "artifact_intent": workbook_artifact_intent(str(req.question or "")),
                                    "price_basis": requested_price_basis(str(req.question or "")),
                                },
                            )
                        except Exception as job_error:  # noqa: BLE001 - durability degrades visibly
                            logger.exception(
                                "[WORKBOOK_RESEARCH] durable checkpoint unavailable: %s",
                                type(job_error).__name__,
                            )
                            retrieval_trace["workbook_research_job"] = {
                                "schema": "les.workbook-research-job.v1",
                                "status": "durability_unavailable",
                                "error_type": type(job_error).__name__,
                            }
                            research_job_service = None
                            research_job = None
                    if (research_job is not None and research_job_service is not None
                            and research_job_service.is_plain_continuation(
                                research_identity, {"original_question": str(req.question or "")})):
                        artifact_kind_declaration = merge_model_artifact_kind(
                            artifact_kind_declaration,
                            (research_job.get("task_context") or {}).get("artifact_kind_declaration") or
                            {"status": "missing", "artifact_kind": "", "declarations": [], "errors": []})
                    review_notice = ""
                    review_prior_rows: list[dict[str, Any]] = []
                    review_instruction = ""
                    if research_job_service is not None and research_job is not None:
                        review_events = research_job_service.list_events_with_lineage(research_job["job_id"])
                        if workbook_chat_review_needed(req.question, research_job, review_events):
                            await _emit_sheet_progress(
                                "Учитываю замечание к документу", completed=0, total=1,
                                extra={"stage": "refinement_review"},
                            )
                            research_job = begin_workbook_chat_review(
                                research_job_service, research_job, req.question,
                                source_catalog.work_locators(),
                            )
                            research_job = research_job_service.begin_or_resume(research_identity)
                            review_notice = "Замечание передано модели вместе с исходником и прежними решениями."
                            retrieval_trace["chat_refinement"] = {
                                "status": "reviewing", "review_scope": "document",
                                "request_author": "user", "decision_author": "model",
                                "source_rows": len(source_catalog.work_locators()),
                            }
                        review_context = workbook_chat_review_context(research_job_service, research_job)
                        review_prior_rows = list(review_context.get("prior_rows") or [])
                        review_instruction = str(review_context.get("message") or "")
                    accumulated_rows: list[dict[str, Any]] = [
                        dict(item)
                        for item in ((research_job or {}).get("accepted_rows") or ())
                        if isinstance(item, Mapping)
                    ]
                    sheet_pass_evidence_chunks: list[_ModelRagEvidenceChunk] = [
                        evidence_chunk_from_record(item)
                        for item in ((research_job or {}).get("evidence") or ())
                        if isinstance(item, Mapping)
                    ]
                    model_research_tools.register_shown_norm_cards(sheet_pass_evidence_chunks)
                    from proxy.services.lsr_workbook_adapter_service import explicit_estimate_pricebook
                    sheet_price_basis = explicit_estimate_pricebook(
                        question_text=workbook_model_question(str(req.question or ""), research_job),
                        source_text=attachment_context,
                        source_name=str(getattr(source_catalog, "original_name", "") or ""),
                        document_basis=dict((research_job or {}).get("task_context") or {}).get("price_basis"),
                    )
                    model_research_tools.set_price_basis(sheet_price_basis)
                    sheet_sys_msg += "\nЗакреплённая ценовая база задания: " + json.dumps(
                        sheet_price_basis, ensure_ascii=False
                    )
                    answer_parts: list[str] = [review_notice] if review_notice else []
                    any_sheet_queries = False
                    last_finish = ""
                    last_truncated = False
                    pass_rejected: list[str] = []
                    # Blocker § 2: a line separated from the query list keeps the
                    # structural reason it was separated for, so "the model wrote
                    # prose" and "the model declared nothing" stay different facts.
                    pass_rejected_reasons: list[dict[str, str]] = []
                    pass_omitted: list[str] = list(
                        (research_job or {}).get("omitted") or ()
                    )
                    research_cancelled = False
                    # Which guard stopped the run, when one did.  Reported apart from
                    # `research_cancelled` so a per-run budget is never shown as an
                    # operator cancellation.
                    run_stop_kinds: list[str] = []
                    sheet_query_cache: dict[str, Any] = {
                        str(key): value
                        for key, value in (
                            ((research_job or {}).get("query_cache") or {})
                            if isinstance((research_job or {}).get("query_cache"), dict)
                            else {}
                        ).items()
                        if str(key).strip()
                    }
                    stored_held = (
                        (research_job or {}).get("held_packet")
                        if isinstance((research_job or {}).get("held_packet"), dict)
                        else {}
                    )
                    terminal_packet_locators = WorkbookResearchJobService.terminal_packet_locators(stored_held)
                    if (research_job_service is not None and research_job is not None
                            and research_job_service.is_plain_continuation(
                                research_identity, {"original_question": str(req.question or "")})):
                        # A new explicit resume may reach sources with no saved decision.
                        # Same-request replay and this run's later terminal barriers stay intact.
                        terminal_packet_locators.intersection_update(
                            settled_source_keys(accumulated_rows, source_catalog))
                    pending_result_packets = model_rag_pending_result_packets(stored_held)
                    transport_pending_locators, pending_diagnostics = model_rag_pending_result_projection(pending_result_packets)
                    if pending_diagnostics:
                        retrieval_trace["model_result_transport_diagnostics"] = pending_diagnostics
                    explicit_reopened_locators: set[str] = set()
                    if research_job_service is not None and research_job is not None:
                        for event in research_job_service.list_events_with_lineage(research_job["job_id"]):
                            event_payload = event.get("payload") or {}
                            if event.get("event_type") == "packet_checkpoint":
                                explicit_reopened_locators.difference_update(event_payload.get("packet_locators") or ())
                            elif event.get("event_type") == "locators_reopened":
                                explicit_reopened_locators.update(event_payload.get("locators") or ())
                    if stored_held.get("terminal_model_result_saved") or stored_held.get("model_result_transport_pending"):
                        # A completed packet's unused candidates stay durable;
                        # they are not an automatic professional re-offer.
                        stored_held = {}
                    sheet_count = len(sheet_pass_names)
                    work_total = len(source_catalog.work_locators())
                    session_accepted_start = len(
                        settled_source_keys(
                            accumulated_rows, source_catalog
                        )
                        & set(source_catalog.work_locators())
                    )
                    prior_elapsed = float(
                        (research_job or {}).get("prior_elapsed_seconds") or 0.0
                    )

                    async def _emit_row_progress(
                        stage: str, *, sheet: str, index: int
                    ) -> None:
                        accepted_now = len(
                            settled_source_keys(
                                accumulated_rows, source_catalog
                            )
                            & set(source_catalog.work_locators())
                        )
                        counts = sheet_pass_progress_counts(
                            accepted_now=accepted_now,
                            work_total=work_total,
                            session_accepted_start=session_accepted_start,
                            prior_elapsed_seconds=prior_elapsed,
                        )
                        extra = {
                            key: value
                            for key, value in counts.items()
                            if key not in {"completed", "total"}
                        }
                        extra["structurally_complete"] = len(
                            structurally_complete_source_keys(accumulated_rows, source_catalog)
                        )
                        extra["processed"] = accepted_now
                        await _emit_sheet_progress(
                            sheet_pass_progress_label(
                                sheet,
                                sheet_index=index,
                                sheet_count=sheet_count,
                                stage=stage,
                                resumed=bool(counts["resumed"]),
                            ),
                            completed=int(counts["completed"]),
                            total=int(counts["total"]),
                            extra=extra,
                        )

                    if session_accepted_start > 0 and sheet_pass_names:
                        await _emit_row_progress(
                            "поиск норм",
                            sheet=sheet_pass_names[0],
                            index=1,
                        )
                    owns_sheet_pass = True
                    live_job_id = str((research_job or {}).get("job_id") or "")
                    if live_job_id:
                        owns_sheet_pass = await claim_or_join_sheet_pass(live_job_id)
                    try:
                      if not owns_sheet_pass:
                        logger.info(
                            "[SHEET_PASS] joined live job=%s; skip duplicate packet loop",
                            live_job_id,
                        )
                        if research_job_service is not None and live_job_id:
                            research_job = research_job_service.get(live_job_id) or research_job
                        latest_held = (research_job or {}).get("held_packet") or {}
                        terminal_packet_locators = WorkbookResearchJobService.terminal_packet_locators(latest_held)
                        pending_result_packets = model_rag_pending_result_packets(latest_held)
                        transport_pending_locators, pending_diagnostics = model_rag_pending_result_projection(pending_result_packets)
                        if pending_diagnostics or "model_result_transport_diagnostics" in retrieval_trace:
                            retrieval_trace["model_result_transport_diagnostics"] = pending_diagnostics
                        accumulated_rows = [
                            dict(item)
                            for item in ((research_job or {}).get("accepted_rows") or ())
                            if isinstance(item, Mapping)
                        ]
                        sheet_pass_names = ()
                      for sheet_index, sheet_name in enumerate(sheet_pass_names, start=1):
                        if research_job_service is not None and research_job is not None:
                            research_job = research_job_service.get(research_job["job_id"])
                            run_stops, cancelled_now, stop_kind = research_run_stopped(research_job)
                            if run_stops:
                                # Only the per-run budget, an operator stop or a
                                # cancellation ends the document.  A guard pause that
                                # set one packet aside used to be read as a stop here,
                                # and the customer's ВОР stopped at АР with eight
                                # sheets never offered.
                                research_cancelled = research_cancelled or cancelled_now
                                run_stop_kinds.append(stop_kind or "unlabelled_pause")
                                logger.warning(
                                    "[SHEET_PASS] run stops before sheet=%s kind=%s "
                                    "remaining=%s",
                                    sheet_name,
                                    stop_kind or "unlabelled_pause",
                                    len(research_job.get("remaining") or ()),
                                )
                                break
                        # Same definition of outstanding as the terminal rule
                        # below, otherwise the loop re-offers decided rows on the
                        # first sheet and never reaches the next one.
                        remaining = remaining_sheet_work_locators(
                            source_catalog,
                            sheet_name,
                            settled_source_keys(accumulated_rows, source_catalog),
                        )
                        remaining = [locator for locator in remaining
                                     if locator not in terminal_packet_locators
                                     and (locator not in transport_pending_locators or locator in explicit_reopened_locators)]
                        exhausted_locators: set[str] = transport_pending_locators - explicit_reopened_locators
                        # Rows already put to the model in this sheet pass.  The
                        # packet pool is ordered least-offered-first so no row can
                        # be starved by a leading row that keeps a quality gap.
                        offered_locators: set[str] = set()
                        packet_attempts: dict[tuple[str, ...], int] = {}
                        offer_counts: dict[str, int] = {}
                        if (
                            research_job_service is not None
                            and isinstance(research_job, Mapping)
                            and research_job.get("job_id")
                        ):
                            # A restarted process must continue attempt numbering
                            # from the durable checkpoints, so a Qx.Hy reference
                            # can never address another attempt's cards.  The same
                            # checkpoints carry how often each row was already put
                            # to the model, which is what keeps the rotation across
                            # the pass boundary instead of restarting it at the head
                            # of the sheet.
                            #
                            # Read across the document's lineage, not just this row:
                            # «Продолжи это же задание…» is a new research identity,
                            # and counting its offers from zero re-offered rows the
                            # previous research had already decided 14 times over
                            # (blocker § 1, live on build 824).
                            checkpoint_events = research_job_service.list_events_with_lineage(
                                str(research_job["job_id"]),
                                "packet_checkpoint",
                            )
                            packet_attempts = packet_attempt_seed(checkpoint_events)
                            offer_counts = packet_offer_counts(checkpoint_events)
                        # A packet that a previous run gave up on stays set aside
                        # across a restart.  Blocker § 1 asks for both halves: do not
                        # repeat the same dead set without new data, and do not let it
                        # hold back the rows of the other sheets.  The service lifts a
                        # deferral itself as soon as the job gained evidence.
                        deferred_here: list[str] = []
                        if (
                            research_job_service is not None
                            and isinstance(research_job, Mapping)
                            and research_job.get("job_id")
                        ):
                            deferred_here = research_job_service.still_deferred(
                                str(research_job["job_id"]), sheet=sheet_name
                            )
                        if deferred_here:
                            exhausted_locators.update(deferred_here)
                            remaining = [
                                locator
                                for locator in remaining
                                if locator not in exhausted_locators
                            ]
                            logger.info(
                                "[SHEET_PASS] %s rows of sheet=%s stay deferred from "
                                "the previous run",
                                len(deferred_here),
                                sheet_name,
                            )
                        # Rows this sheet dropped because the model answer was cut
                        # before the decision columns were written (blocker § 1: a
                        # technical read failure is not «нет нормы»).
                        unread_tail_rows: list[str] = []
                        locator_research_round: dict[str, int] = {}
                        inner = 0
                        deferred_query_hits: list[tuple[str, Sequence[Any]]] = []
                        held_packet: list[str] = []
                        evidence_query_offset = model_rag_next_query_offset(sheet_pass_evidence_chunks)
                        held_query_context: dict[str, Any] = {}
                        if (
                            str(stored_held.get("sheet") or "") == sheet_name
                            and stored_held.get("queries")
                        ):
                            held_packet = [
                                locator
                                for locator in (stored_held.get("locators") or [])
                                if source_catalog.lookup(locator) is not None
                            ]
                            held_query_context = dict(stored_held)
                            deferred_query_hits, refreshed_cache, refresh_blocked = await restore_or_refresh_held_query_hits(
                                [
                                    str(item)
                                    for item in (stored_held.get("queries") or [])
                                    if str(item).strip()
                                ],
                                sheet_query_cache,
                                model_research_tools=model_research_tools,
                                retrieval_trace=retrieval_trace,
                                hits_per_query=retrieval_limits["model_evidence_k"],
                            )
                            if refreshed_cache and research_job_service is not None and research_job is not None:
                                research_job = research_job_service.record_search_cache(
                                    research_job["job_id"], refreshed_cache, context=dict(stored_held),
                                    cache_contract=str(getattr(model_research_tools, "cache_contract", "") or ""))
                            if refresh_blocked:
                                retrieval_trace["search_cache_refresh"] = {"status": refresh_blocked, "technical_failure": True}
                                run_stop_kinds.append("search_cache_refresh_blocked")
                                if research_job_service is not None and research_job is not None:
                                    research_job = research_job_service.pause(research_job["job_id"], phase="search_cache_refresh_blocked")
                                break
                            evidence_query_offset = int(stored_held.get("query_offset") or 0)
                            stored_held = {}
                        while remaining or deferred_query_hits:
                            if research_job_service is not None and research_job is not None:
                                research_job = research_job_service.get(research_job["job_id"])
                                run_stops, cancelled_now, stop_kind = research_run_stopped(
                                    research_job
                                )
                                if run_stops:
                                    # Same rule as the sheet-level test: the guard
                                    # paused this job over one packet, so the run
                                    # finishes this sheet's deferral bookkeeping and
                                    # stops only for a budget/operator/cancel reason.
                                    research_cancelled = research_cancelled or cancelled_now
                                    run_stop_kinds.append(stop_kind or "unlabelled_pause")
                                    logger.warning(
                                        "[SHEET_PASS] run stops mid sheet=%s kind=%s "
                                        "packet_rows=%s",
                                        sheet_name,
                                        stop_kind or "unlabelled_pause",
                                        len(remaining),
                                    )
                                    break
                            reuse_hits = list(deferred_query_hits)
                            deferred_query_hits = []
                            if reuse_hits:
                                packet = [
                                    locator
                                    for locator in held_packet
                                    if source_catalog.lookup(locator) is not None
                                ]
                                if not packet:
                                    pass_omitted.extend(
                                        model_rag_query_hit_refs(
                                            reuse_hits,
                                            hits_per_query=retrieval_limits[
                                                "model_evidence_k"
                                            ],
                                            query_offset=evidence_query_offset,
                                        )
                                    )
                                    held_packet = []
                                    continue
                                offered_locators.update(packet)
                                fingerprint = tuple(packet)
                                packet_attempts.setdefault(fingerprint, 1)
                                inner += 1
                                cited_before = structurally_complete_source_keys(
                                    accumulated_rows, source_catalog
                                )
                                settled_before = settled_source_keys(
                                    accumulated_rows, source_catalog
                                )
                                pass_evidence = selector_evidence_payload(
                                    attachment_context=attachment_context,
                                    rendered_context="",
                                    source_catalog=source_catalog,
                                    sheet=sheet_name,
                                    remaining_work=packet,
                                )
                                prior_page_rows = [row for row in accumulated_rows if str(row.get("source_row") or "") in packet]
                                prior_packet_rows = [row for row in review_prior_rows if str(row.get("source_row") or "") in packet]
                                prior_page_context, prior_page_chunks = model_rag_prior_page_context(
                                    prior_page_rows, sheet_pass_evidence_chunks,
                                    review_rows=prior_packet_rows, review_instruction=review_instruction,
                                    source_catalog=source_catalog)
                                if prior_page_rows or prior_packet_rows:
                                    pass_evidence.append(prior_page_context)
                                declared_queries = []
                                query_calls = []
                                query_answer_cut = False
                                unread_query_tail = ""
                                rejected_reasons_now = []
                                pass_query_provenance = dict(held_query_context.get("query_provenance") or {})
                                pass_query_addresses = dict(held_query_context.get("query_addresses") or {})
                                selector_evidence = pass_evidence
                                pass_hits = reuse_hits
                                model_rag_query_hits = pass_hits
                                model_queries = [
                                    query for query, _hits in pass_hits
                                ]
                                any_sheet_queries = True
                            else:
                                held_packet = []
                                evidence_query_offset = model_rag_next_query_offset(sheet_pass_evidence_chunks)
                                prior_page_chunks = []
                                packet = adaptive_row_packet(
                                    remaining,
                                    generation_reserve_tokens=(
                                        answer_execution_preset.generation_reserve_tokens
                                    ),
                                    already_offered=tuple(sorted(offered_locators)),
                                    offer_counts=offer_counts,
                                )
                                if not packet:
                                    break
                                offered_locators.update(packet)
                                fingerprint = tuple(packet)
                                packet_attempts[fingerprint] = packet_attempts.get(fingerprint, 0) + 1
                                inner += 1
                                cited_before = structurally_complete_source_keys(
                                    accumulated_rows, source_catalog
                                )
                                settled_before = settled_source_keys(
                                    accumulated_rows, source_catalog
                                )
                                await _emit_row_progress(
                                    "поиск норм",
                                    sheet=sheet_name,
                                    index=sheet_index,
                                )
                                pass_evidence = selector_evidence_payload(
                                    attachment_context=attachment_context,
                                    rendered_context="",
                                    source_catalog=source_catalog,
                                    sheet=sheet_name,
                                    remaining_work=packet,
                                )
                                prior_packet_rows = [row for row in review_prior_rows if str(row.get("source_row") or "") in packet]
                                prior_page_rows = [row for row in accumulated_rows if str(row.get("source_row") or "") in packet]
                                prior_page_context, prior_page_chunks = model_rag_prior_page_context(
                                    prior_page_rows, sheet_pass_evidence_chunks,
                                    review_rows=prior_packet_rows, review_instruction=review_instruction,
                                    source_catalog=source_catalog)
                                if prior_page_rows or prior_packet_rows:
                                    pass_evidence.append(prior_page_context)
                                selector_evidence = pass_evidence
                                query_text = ""
                                model_queries: list[str] = []
                                declared_queries: list[dict[str, Any]] = []
                                declared_seen: set[str] = set()
                                rejected_now: list[str] = []
                                rejected_reasons_now: list[dict[str, str]] = []
                                rejected_seen: set[str] = set()
                                query_calls: list[dict[str, Any]] = []
                                query_answer_cut = False
                                unread_query_tail = ""
                                pass_query_addresses: dict[str, list[str]] = {}
                                packet_round = max(
                                    (locator_research_round.get(str(item), 0) for item in packet),
                                    default=0,
                                )
                                query_base_instruction = sheet_pass_query_instruction(
                                    profile_snapshot,
                                    sheet=sheet_name,
                                    sheet_index=sheet_index,
                                    sheet_count=sheet_count,
                                    research_round=packet_round,
                                )
                                query_directive = query_base_instruction
                                query_phase = "declare"
                                # Blocker § 2: a query is attributed to the row it
                                # answers for by reading it against the same literal
                                # row text the candidate author quotes, so the query
                                # and the source cannot disagree about an operation.
                                packet_row_literals: dict[str, str] = {}
                                for packet_locator in packet:
                                    packet_row = source_catalog.lookup(str(packet_locator))
                                    if packet_row is None:
                                        continue
                                    packet_row_literals[str(packet_locator)] = row_literal_text(
                                        packet_row
                                    )
                                try:
                                    for query_attempt in range(
                                        1, _MAX_SHEET_PASS_QUERY_CALLS + 1
                                    ):
                                        query_purpose = (
                                            "model_rag_sheet_queries"
                                            if query_phase == "declare"
                                            else (
                                                "model_rag_sheet_query_continuation"
                                                if query_phase == "continuation"
                                                else "model_rag_sheet_query_repair"
                                            )
                                        )
                                        query_instruction = query_directive
                                        query_messages, query_packet = govern_inference_messages(
                                            preset=query_execution_preset,
                                            profile_prefix=(
                                                profile_system_prompt(
                                                    profile_snapshot, strict=False
                                                )
                                                + "\n\n"
                                                + query_instruction
                                            ),
                                            request_payload={
                                                "question": workbook_model_question(str(req.question or ""), research_job),
                                                "dataset_ids": [
                                                    str(item) for item in _dataset_ids
                                                ],
                                            },
                                            checkpoint=(),
                                            working_memory=workspace_note_objects(
                                                memory_candidates,
                                                registered=workspace_memory_registered,
                                            ),
                                            required_evidence=pass_evidence,
                                            source_map=[*sheet_initial_source_map,
                                                        *_model_rag_source_map(prior_page_chunks)],
                                            tool_exchange=(),
                                        )
                                        retrieval_trace["context_governor"]["calls"].append(
                                            context_packet_trace(
                                                query_packet,
                                                purpose=query_purpose,
                                            )
                                        )
                                        query_budget = governed_query_generation_budget(query_execution_preset, query_packet)
                                        query_body = {
                                            "messages": query_messages,
                                            "stream": False,
                                            "temperature": 0,
                                            "max_tokens": query_budget["effective"],
                                        }
                                        t_query_model = time.time()
                                        query_text, query_usage = await _sheet_pass_llm(
                                            query_body,
                                            purpose=query_purpose,
                                            inference_preset=query_execution_preset,
                                        )
                                        t_llm += time.time() - t_query_model
                                        query_diagnostic = model_query_output_diagnostics(
                                            query_text, query_usage, purpose=query_purpose, budget=query_budget,
                                        )
                                        retrieval_trace.setdefault("model_query_outputs", []).append(query_diagnostic)
                                        query_failure_final_texts.append(query_text)
                                        query_failure_final_texts = query_failure_final_texts[-8:]
                                        query_diagnostic["declared_parse"] = declared_query_output_diagnostics(
                                            query_text, read_declared_query_list(query_text,
                                                finish_reason=llm_usage_finish_reason(query_usage), instruction=query_directive))
                                        logger.info("[MODEL_RAG_QUERY_OUTPUT] %s", query_diagnostic)
                                        if query_diagnostic["output_incomplete"]:
                                            if research_job_service is not None and research_job is not None:
                                                research_job = research_job_service.pause(
                                                    research_job["job_id"], remaining=list(dict.fromkeys([*remaining, *packet])),
                                                    phase="model_query_output_incomplete",
                                                    held_packet={"sheet": sheet_name, "locators": list(packet),
                                                                 "model_query_output_missing": True,
                                                                 "query_output": query_diagnostic},
                                                )
                                            raise model_query_failure({"error": "MODEL_QUERY_OUTPUT_INCOMPLETE"}, trace=retrieval_trace,
                                                session_id=req.session_id, provider=llm_runtime.provider, model=llm_model,
                                                secret_values=(llm_runtime.api_key,), final_texts=query_failure_final_texts)
                                        # One reader for the declared-query contract:
                                        # the prompt states the format, this adapter
                                        # reads it, and nothing re-splits the answer a
                                        # second time with different rules.
                                        declared_now = read_model_query_response(
                                            query_text,
                                            finish_reason=llm_usage_finish_reason(
                                                query_usage
                                            ),
                                            packet_locators=[str(item) for item in packet],
                                            row_literals=packet_row_literals,
                                            instruction=query_directive,
                                        )
                                        artifact_kind_declaration = merge_model_artifact_kind(
                                            artifact_kind_declaration, declared_now["artifact_kind_declaration"])
                                        if research_job_service is not None and research_job is not None:
                                            research_job = research_job_service.record_artifact_kind(
                                                research_job["job_id"], declaration=artifact_kind_declaration)
                                        query_answer_cut = bool(
                                            declared_now.get("answer_cut")
                                        )
                                        unread_query_tail = str(
                                            declared_now.get("unread_tail") or ""
                                        )
                                        for declared_item in declared_now["queries"]:
                                            folded_query = " ".join(
                                                str(declared_item.text).casefold().split()
                                            )
                                            if folded_query in declared_seen:
                                                continue
                                            declared_seen.add(folded_query)
                                            declared_queries.append(
                                                declared_item.as_trace_dict()
                                            )
                                            model_queries.append(str(declared_item.text))
                                            if declared_item.attribution in {
                                                "address_written",
                                                "address_outside_packet",
                                            } and declared_item.addresses:
                                                # Only the model's own pointer reaches
                                                # the header; a row matched by text
                                                # similarity stays in the trace, so the
                                                # code never tells the model which
                                                # operation a query "really" belongs to.
                                                pass_query_addresses[
                                                    str(declared_item.text)
                                                ] = list(declared_item.addresses)
                                        for rejected_row in declared_now["accompanying_answer"]:
                                            rejected_line = str(rejected_row.get("line") or "")
                                            if not rejected_line or rejected_line in rejected_seen:
                                                continue
                                            rejected_seen.add(rejected_line)
                                            rejected_now.append(rejected_line)
                                            rejected_reasons_now.append(dict(rejected_row))
                                        query_calls.append(
                                            {
                                                "attempt": query_attempt,
                                                "purpose": query_purpose,
                                                "finish_reason": str(
                                                    declared_now.get("finish_reason") or ""
                                                ),
                                                "declared": len(declared_now["queries"]),
                                                "rejected": len(
                                                    declared_now["accompanying_answer"]
                                                ),
                                                "completion_tokens": int(
                                                    (query_usage or {}).get(
                                                        "completion_tokens"
                                                    )
                                                    or 0
                                                ),
                                            }
                                        )
                                        # Blocker § 2: a list cut at
                                        # finish_reason=length gets one targeted call
                                        # for the unread line.  The queries already
                                        # received are still executed and the cut line
                                        # is quoted back verbatim, so no half-read
                                        # query is searched and no unmade query is read
                                        # as "the model decided nothing".
                                        next_phase, next_suffix = ("", "") if declared_now.get("intentional_empty") else declared_query_attempt_plan(
                                            declared=declared_now,
                                            already_declared=model_queries,
                                            phase=query_phase,
                                            attempts_remaining=(
                                                _MAX_SHEET_PASS_QUERY_CALLS - query_attempt
                                            ),
                                        )
                                        if not next_phase:
                                            break
                                        query_phase = next_phase
                                        query_directive = (
                                            query_base_instruction
                                            + "\n\n"
                                            + next_suffix
                                        )
                                except ContextRequiredSectionOverflow as context_error:
                                    logger.warning(
                                        "[SHEET_PASS] query overflow sheet=%s: %s",
                                        sheet_name,
                                        context_error.code,
                                    )
                                    break
                                pass_rejected.extend(rejected_now)
                                pass_rejected_reasons.extend(rejected_reasons_now)
                                if not model_queries and not declared_now.get("intentional_empty"):
                                    break
                                any_sheet_queries = True
                                pass_hits: list[tuple[str, Sequence[Any]]] = []
                                pass_tools: list[dict[str, Any]] = []
                                pass_query_provenance: dict[str, str] = {}
                                search_blocked = False
                                search_block_status = ""
                                cache_updates: dict[str, list[dict[str, Any]]] = {}
                                for query in model_queries:
                                    cached_hits = restore_query_hits_from_cache(
                                        [query], sheet_query_cache,
                                        cache_contract=str(getattr(model_research_tools, "cache_contract", "") or "")
                                    )
                                    if cached_hits:
                                        hits = cached_hits[0][1]
                                        pass_hits.append((query, hits))
                                        pass_tools.append(
                                            {
                                                "schema": "les_tool_result_v1",
                                                "tool": "search_sources",
                                                "status": "ok" if hits else "missing",
                                                "result": {
                                                    "count": len(hits),
                                                    "cached": True,
                                                },
                                            }
                                        )
                                        append_actual_search(
                                            retrieval_trace,
                                            cached=True,
                                            hit_count=len(hits),
                                        )
                                        continue
                                    research_result = await model_research_tools.execute(
                                        {"tool": "search_sources", "args": {"q": query}}
                                    )
                                    pass_tools.append(research_result.payload)
                                    if model_search_result_blocks_packet(
                                        research_result.payload
                                    ):
                                        search_blocked = True
                                        search_block_status = str(
                                            research_result.payload.get("status") or ""
                                        )
                                        break
                                    hits = tuple(research_result.chunks)[
                                        : retrieval_limits["model_evidence_k"]
                                    ]
                                    pass_hits.append((query, hits))
                                    records = [durable_research_hit(item) for item in hits]
                                    from proxy.services.workbook_research_job_service import research_cache_entry
                                    sheet_query_cache[str(query)] = research_cache_entry(
                                        records, cache_contract=str(getattr(model_research_tools, "cache_contract", "") or ""),
                                        previous=sheet_query_cache.get(str(query)))
                                    cache_updates[str(query)] = records
                                    append_actual_search(
                                        retrieval_trace,
                                        cached=False,
                                        hit_count=len(hits),
                                    )
                                if search_blocked:
                                    logger.warning(
                                        "[SHEET_PASS] search incomplete sheet=%s status=%s",
                                        sheet_name,
                                        search_block_status,
                                    )
                                    break
                                candidate_added = 0 if artifact_kind_declaration.get("artifact_kind") == "vor" else await _execute_system_candidate_queries(
                                    catalog=source_catalog,
                                    sheet=sheet_name,
                                    packet=packet,
                                    profile_snapshot=profile_snapshot,
                                    comparative_variant=comparative_variant,
                                    model_research_tools=model_research_tools,
                                    model_queries=model_queries,
                                    pass_hits=pass_hits,
                                    pass_tools=pass_tools,
                                    sheet_query_cache=sheet_query_cache,
                                    cache_updates=cache_updates,
                                    query_provenance=pass_query_provenance,
                                    retrieval_trace=retrieval_trace,
                                    hits_per_query=int(
                                        retrieval_limits["model_evidence_k"]
                                    ),
                                    query_addresses=pass_query_addresses,
                                )
                                if candidate_added:
                                    logger.info(
                                        "[SHEET_PASS] system candidates sheet=%s added=%s",
                                        sheet_name,
                                        candidate_added,
                                    )
                                if (
                                    cache_updates
                                    and research_job_service is not None
                                    and research_job is not None
                                ):
                                    research_job = research_job_service.record_search_cache(
                                        research_job["job_id"],
                                        cache_updates,
                                        cache_contract=str(getattr(model_research_tools, "cache_contract", "") or ""),
                                        context={
                                            "sheet": sheet_name,
                                            "packet_id": row_packet_id(
                                                source_catalog,
                                                sheet=sheet_name,
                                                locators=packet,
                                            ),
                                            "locators": list(packet),
                                            "queries": list(cache_updates),
                                        },
                                    )
                                tool_results_for_model = pass_tools
                                model_rag_query_hits = pass_hits
                            leftover_query_hits: list[tuple[str, Sequence[Any]]] = []
                            included_hits: list[tuple[str, Sequence[Any]]] = []
                            question_tail = sheet_pass_question_tail(
                                workbook_model_question(str(req.question or ""), research_job),
                                sheet=sheet_name,
                                sheet_index=sheet_index,
                                sheet_count=sheet_count,
                                remaining_work=packet,
                                reasoning_enabled=execution_preset.reasoning_enabled,
                            )
                            question_tail += (
                                "\nКарточки могут доставляться страницами по ёмкости контекста. "
                                "Не объявляй поиск исчерпанным по одной странице: индекс показывает "
                                "найденные карточки, а недостающее содержание прочитай инструментом "
                                "до итогового ответа. После ответа непрочитанный хвост сохраняется "
                                "для явного продолжения пользователем."
                            )
                            current_read_packet = row_packet_id(source_catalog, sheet=sheet_name, locators=packet)
                            saved_read_chunks = [
                                chunk for chunk in sheet_pass_evidence_chunks
                                if chunk.meta.get("model_read_packet_id") == current_read_packet
                            ]
                            # Every continuation retains the complete original
                            # attachment, independently of the current row packet.
                            if attachment_context and not any(
                                isinstance(item, Mapping) and "original_attachment_context" in item
                                for item in pass_evidence
                            ):
                                pass_evidence.append({"original_attachment_context": attachment_context})
                            try:
                                _, fixed_packet = govern_inference_messages(
                                    preset=answer_execution_preset,
                                    profile_prefix=sheet_sys_msg,
                                    request_payload=question_tail,
                                    native_tools=sheet_read_tools,
                                    required_evidence=pass_evidence,
                                )
                            except ContextRequiredSectionOverflow as context_error:
                                retrieval_trace["context_governor"]["error"] = model_read_capacity_trace(
                                    context_error, purpose="sheet_pass_source_frame")
                                pending_page = model_rag_evidence_page_state(
                                    sheet=sheet_name, packet=packet, leftover_query_hits=pass_hits,
                                    query_offset=evidence_query_offset,
                                    query_provenance=pass_query_provenance,
                                    query_addresses=pass_query_addresses,
                                    pending_result_packets=pending_result_packets)
                                if research_job_service is not None and research_job is not None:
                                    research_job = research_job_service.pause(
                                        research_job["job_id"], remaining=list(dict.fromkeys([*remaining, *packet])),
                                        held_packet=pending_page, phase="evidence_capacity")
                                run_stop_kinds.append("evidence_capacity")
                                break
                            remaining_group_tokens = max(
                                0,
                                fixed_packet.input_budget_tokens
                                - fixed_packet.included_tokens
                                - len(pass_hits)
                                - 2,
                            )
                            first_read_groups, _ = _model_rag_full_groups(
                                pass_hits, hits_per_query=retrieval_limits["model_evidence_k"],
                                query_offset=evidence_query_offset,
                                query_provenance=pass_query_provenance, query_addresses=pass_query_addresses)
                            native_growth_budget = native_read_growth_budget(
                                available_tokens=remaining_group_tokens,
                                generation_tokens=answer_execution_preset.generation_reserve_tokens,
                                groups=first_read_groups, enabled=bool(sheet_read_tools))
                            remaining_group_tokens = native_growth_budget["remaining_group_tokens"]
                            group_max_chars = model_rag_group_char_budget(
                                context_chars_limit=context_chars_limit,
                                remaining_group_tokens=remaining_group_tokens,
                            )
                            logger.warning(
                                "[MODEL_RAG_BUDGET] sheet=%s queries=%s hits=%s "
                                "input_budget=%s included=%s remaining_group_tokens=%s "
                                "context_chars_limit=%s group_max_chars=%s",
                                sheet_name,
                                len(pass_hits),
                                sum(len(hits) for _query, hits in pass_hits),
                                fixed_packet.input_budget_tokens,
                                fixed_packet.included_tokens,
                                remaining_group_tokens,
                                context_chars_limit,
                                group_max_chars,
                            )
                            included_hits, leftover_query_hits, trim_omitted = (
                                select_model_rag_query_hits_for_budget(
                                    pass_hits,
                                    max_chars=group_max_chars,
                                    hits_per_query=retrieval_limits["model_evidence_k"],
                                    query_offset=evidence_query_offset,
                                    query_provenance=pass_query_provenance,
                                    query_addresses=pass_query_addresses,
                                    require_card_bodies=True,
                                )
                            )
                            pass_omitted.extend(trim_omitted)
                            await _emit_row_progress(
                                f"карточки: {len(included_hits)}/{len(pass_hits)} "
                                "групп на этой странице; таблица строк",
                                sheet=sheet_name,
                                index=sheet_index,
                            )
                            if not included_hits and leftover_query_hits:
                                # Preserve a query that cannot fit even one page.
                                # Capacity is a technical pause, never NO_NORM.
                                held_query_context = model_rag_evidence_page_state(
                                    sheet=sheet_name, packet=packet,
                                    leftover_query_hits=leftover_query_hits,
                                    query_offset=evidence_query_offset,
                                    query_provenance=pass_query_provenance,
                                    query_addresses=pass_query_addresses,
                                    pending_result_packets=pending_result_packets)
                                if research_job_service is not None and research_job is not None:
                                    research_job = research_job_service.pause(
                                        research_job["job_id"], remaining=list(dict.fromkeys([*remaining, *packet])),
                                        held_packet=held_query_context, phase="evidence_capacity")
                                run_stop_kinds.append("evidence_capacity")
                                logger.warning("[SHEET_PASS] query cards exceed evidence capacity; sheet=%s budget=%s", sheet_name, group_max_chars)
                                break
                            if not included_hits:
                                pass_omitted.extend(
                                    model_rag_query_hit_refs(
                                        leftover_query_hits,
                                        hits_per_query=retrieval_limits[
                                            "model_evidence_k"
                                        ],
                                        query_offset=evidence_query_offset,
                                    )
                                )
                                leftover_query_hits = []
                                model_rag_evidence_groups = []
                                model_evidence_chunks = []
                                omitted_now: list[str] = []
                            else:
                                (
                                    model_rag_evidence_groups,
                                    model_evidence_chunks,
                                    omitted_now,
                                ) = build_model_rag_evidence_groups(
                                    pass_hits,
                                    max_chars=group_max_chars,
                                    hits_per_query=retrieval_limits["model_evidence_k"],
                                    evidence_namespace=(
                                        row_packet_id(
                                            source_catalog,
                                            sheet=sheet_name,
                                            locators=packet,
                                        )
                                        + f":a{packet_attempts[fingerprint]}"
                                    ),
                                    query_offset=evidence_query_offset,
                                    query_provenance=pass_query_provenance,
                                    query_addresses=pass_query_addresses,
                                )
                            sheet_pass_evidence_chunks.extend(model_evidence_chunks)
                            model_research_tools.register_shown_norm_cards(model_evidence_chunks)
                            page_body_deferred = list(omitted_now)
                            included_refs = set(model_rag_query_hit_refs(
                                included_hits, hits_per_query=retrieval_limits["model_evidence_k"],
                                query_offset=evidence_query_offset,
                            ))
                            omitted_now = [ref for ref in omitted_now if ref in included_refs]
                            pass_omitted.extend(omitted_now)
                            retrieval_trace.setdefault("grouped_model_evidence_pages", []).append({
                                "query_offset": evidence_query_offset,
                                "native_read_growth_budget": native_growth_budget,
                                "returned_hit_count": sum(len(hits) for _q, hits in pass_hits),
                                "inventory_hit_count": len(model_evidence_chunks),
                                "full_body_hit_count": sum(c.meta.get("body_status") == "full" for c in model_evidence_chunks),
                                "normative_complete_card_count": sum(c.meta.get("normative_card_complete") is True for c in model_evidence_chunks),
                                "normative_preview_card_count": sum(c.meta.get("normative_resources_status") == "preview" for c in model_evidence_chunks),
                                "deferred_body_refs": page_body_deferred,
                                "unshown_refs": [ref for ref in page_body_deferred if ref not in {
                                    c.meta.get("model_evidence_ref") for c in model_evidence_chunks}],
                            })
                            omitted_cards = model_rag_budget_omitted_cards(
                                included_hits,
                                model_evidence_chunks,
                                omitted_now,
                                query_offset=evidence_query_offset,
                            )
                            context = "\n\n".join(model_rag_evidence_groups)
                            answer_source_map = _model_rag_source_map(
                                model_evidence_chunks
                            )
                            selector_source_map = answer_source_map
                            model_rag_evidence_packet = build_retrieval_evidence_packet(
                                question=req.question,
                                chunks=model_evidence_chunks,
                                retrieval_trace=retrieval_trace,
                                navigation=evidence_navigation,
                                deterministic_evidence=deterministic_evidence,
                            )
                            final_evidence_packet = model_rag_evidence_packet.to_dict(
                                max_chars=context_chars_limit,
                                include_metadata=True,
                            )
                            answer_evidence = [
                                *pass_evidence,
                                *model_rag_evidence_groups,
                            ]
                            saved_read_receipts = (
                                research_job_service.evidence_read_receipts(research_job["job_id"], current_read_packet)
                                if research_job_service is not None and research_job is not None else []
                            )
                            resumed_inventory_refs = {
                                str(c.meta.get("model_evidence_ref") or "") for c in model_evidence_chunks
                            }
                            resumed_body_refs = {
                                str(c.meta.get("model_evidence_ref") or "") for c in model_evidence_chunks
                                if c.meta.get("body_status") != "deferred_capacity"
                            }
                            try:
                                initial_context = dict(
                                    preset=answer_execution_preset,
                                    admit_messages=_cloud_message_admission(answer_execution_preset, sheet_read_tools),
                                    profile_prefix=sheet_sys_msg,
                                    request_payload=question_tail,
                                    native_tools=sheet_read_tools,
                                    checkpoint=(),
                                    working_memory=workspace_note_objects(
                                        memory_candidates,
                                        registered=workspace_memory_registered,
                                    ),
                                    source_map=(),
                                    tool_exchange=[],
                                    dialogue=[session_block] if session_block else [],
                                )
                                if saved_read_chunks:
                                    messages, answer_packet, resumed_inventory_refs, resumed_body_refs = govern_model_read_messages(
                                        **initial_context, source_context=pass_evidence,
                                        chunks=[*prior_page_chunks, *saved_read_chunks, *model_evidence_chunks],
                                        receipts=saved_read_receipts)
                                else:
                                    messages, answer_packet = govern_inference_messages(
                                        **initial_context, required_evidence=answer_evidence)
                            except CloudBudgetStop:
                                if research_job_service is not None and research_job is not None:
                                    research_job = research_job_service.pause(
                                        research_job["job_id"], phase="cloud_token_budget",
                                        held_packet=model_rag_evidence_page_state(
                                            sheet=sheet_name, packet=packet, leftover_query_hits=pass_hits,
                                            query_offset=evidence_query_offset,
                                            query_provenance=pass_query_provenance,
                                            query_addresses=pass_query_addresses,
                                            pending_result_packets=pending_result_packets),
                                    )
                                raise
                            except ContextRequiredSectionOverflow as context_error:
                                retrieval_trace["context_governor"]["error"] = model_read_capacity_trace(
                                    context_error, purpose="sheet_pass_answer")
                                logger.warning(
                                    "[SHEET_PASS] answer overflow sheet=%s: %s",
                                    sheet_name,
                                    context_error.code,
                                )
                                pending_page = model_rag_evidence_page_state(
                                    sheet=sheet_name, packet=packet, leftover_query_hits=pass_hits,
                                    query_offset=evidence_query_offset,
                                    query_provenance=pass_query_provenance,
                                    query_addresses=pass_query_addresses,
                                    pending_result_packets=pending_result_packets)
                                if research_job_service is not None and research_job is not None:
                                    research_job = research_job_service.pause(
                                        research_job["job_id"], remaining=list(dict.fromkeys([*remaining, *packet])),
                                        held_packet=pending_page, phase="evidence_capacity")
                                run_stop_kinds.append("evidence_capacity")
                                break
                            retrieval_trace["context_governor"]["calls"].append(
                                context_packet_trace(
                                    answer_packet, purpose="sheet_pass_answer"
                                )
                            )
                            source_incomplete_locators = locators_missing_from_text(
                                source_catalog,
                                packet_evidence_text(answer_packet),
                                locators=packet,
                            )
                            generation_budget = (
                                answer_execution_preset.generation_reserve_tokens
                            )
                            chat_body = {
                                "messages": messages,
                                "stream": False,
                                "temperature": profile_temperature(
                                    profile_snapshot,
                                    fallback=_env_float("CHAT_TEMPERATURE", 0.2),
                                ),
                                "max_tokens": generation_budget,
                                "tools": sheet_read_tools,
                            }
                            t_llm_call = time.time()
                            pass_answer, usage = await _sheet_pass_llm(chat_body)
                            t_llm += time.time() - t_llm_call
                            confirm_model_read_delivery([*prior_page_chunks, *saved_read_chunks, *model_evidence_chunks],
                                                        saved_read_receipts,
                                                        inventory_refs=resumed_inventory_refs, body_refs=resumed_body_refs)
                            model_research_tools.register_shown_norm_cards([*prior_page_chunks, *saved_read_chunks, *model_evidence_chunks])
                            replayed_ids = {str(c.meta.get("global_evidence_id") or "") for c in model_evidence_chunks}
                            for chunk in [*prior_page_chunks, *saved_read_chunks]:
                                identity = str(chunk.meta.get("global_evidence_id") or "")
                                if identity and identity not in replayed_ids:
                                    model_evidence_chunks.append(chunk)
                                    replayed_ids.add(identity)
                            answer_source_map = _model_rag_source_map(model_evidence_chunks)
                            selector_source_map = answer_source_map
                            read_packet_id = row_packet_id(source_catalog, sheet=sheet_name, locators=packet)
                            read_groups = []
                            # The checkpoint owns the cumulative packet ledger,
                            # including reads from earlier chat turns.
                            read_receipts = list(saved_read_receipts)

                            async def _accept_sheet_read_replays(batch_receipts):
                                nonlocal research_job, active_pending_tool_calls
                                read_receipts.extend(batch_receipts)
                                retrieval_trace["tool_loop"].setdefault("evidence_reads", []).extend(batch_receipts)
                                active_pending_tool_calls = max(0, active_pending_tool_calls - len(batch_receipts))
                                if research_job_service is not None and research_job is not None:
                                    research_job = research_job_service.record_evidence_read(
                                        research_job["job_id"], packet_id=read_packet_id,
                                        evidence=[durable_evidence_record(c) for c in model_evidence_chunks],
                                        read_receipts=read_receipts,
                                    )

                            async def _accept_sheet_reads(batch_receipts, batch_results):
                                nonlocal research_job, active_pending_tool_calls, model_requested_price_basis
                                read_receipts.extend(batch_receipts)
                                groups, chunks, omitted = bind_model_requested_read_evidence(
                                    batch_results, existing_chunks=sheet_pass_evidence_chunks,
                                    reserved_query_end=evidence_query_offset + len(pass_hits),
                                    evidence_namespace=read_packet_id + ":read:" + str(len(read_receipts)),
                                    packet_id=read_packet_id,
                                    receipts=batch_receipts,
                                )
                                read_groups.extend(groups)
                                model_evidence_chunks.extend(chunks)
                                sheet_pass_evidence_chunks.extend(chunks)
                                model_research_tools.register_shown_norm_cards(chunks)
                                active_pending_tool_calls = max(0, active_pending_tool_calls - len(batch_receipts))
                                retrieval_trace["tool_loop"].setdefault("evidence_reads", []).extend(batch_receipts)
                                model_requested_price_basis = dict(model_research_tools.price_basis_snapshot)
                                if research_job_service is not None and research_job is not None:
                                    research_job = research_job_service.record_evidence_read(
                                        research_job["job_id"], packet_id=read_packet_id,
                                        evidence=[durable_evidence_record(c) for c in model_evidence_chunks],
                                        read_receipts=read_receipts,
                                        price_basis=model_requested_price_basis if model_requested_price_basis.get("pricebook_sha256") else None,
                                    )
                                return "evidence_read_capacity" if omitted else ""

                            async def _continue_sheet_reads(receipts, _results, native_exchanges):
                                nonlocal t_llm, research_job
                                messages, read_frame, inventory_refs, body_refs = govern_model_read_messages(
                                    preset=answer_execution_preset, profile_prefix=sheet_sys_msg,
                                    request_payload=question_tail, native_tools=sheet_read_tools,
                                    native_exchanges=native_exchanges,
                                    source_context=pass_evidence,
                                    admit_messages=_cloud_message_admission(answer_execution_preset, sheet_read_tools),
                                    chunks=[*prior_page_chunks, *saved_read_chunks, *model_evidence_chunks],
                                    receipts=[*saved_read_receipts, *receipts],
                                )
                                retrieval_trace["context_governor"]["calls"].append(
                                    context_packet_trace(read_frame, purpose="sheet_pass_evidence_read")
                                )
                                await _emit_row_progress("чтение карточек и цен", sheet=sheet_name, index=sheet_index)
                                started = time.time()
                                result = await _sheet_pass_llm(
                                    {**chat_body, "messages": messages}, purpose="sheet_pass_evidence_read"
                                )
                                t_llm += time.time() - started
                                confirm_model_read_delivery(model_evidence_chunks, receipts,
                                                            inventory_refs=inventory_refs, body_refs=body_refs)
                                model_research_tools.register_shown_norm_cards(model_evidence_chunks)
                                if research_job_service is not None and research_job is not None:
                                    research_job = research_job_service.record_evidence_read(
                                        research_job["job_id"], packet_id=read_packet_id,
                                        evidence=[durable_evidence_record(c) for c in model_evidence_chunks],
                                        read_receipts=read_receipts,
                                        price_basis=model_requested_price_basis if model_requested_price_basis.get("pricebook_sha256") else None,
                                    )
                                return result

                            try:
                                read_turn = await run_model_evidence_read_turn(
                                    text=pass_answer, usage=usage, parse_calls=_parse_model_tool_calls,
                                    execute=model_research_tools.execute,
                                    allowed_tools={item["function"]["name"] for item in sheet_read_tools},
                                    max_calls=max(1, _env_int("LES_CHAT_TOOL_MAX_CALLS", 48)),
                                    on_read_results=_accept_sheet_reads, continue_native_turn=_continue_sheet_reads,
                                    on_read_replays=_accept_sheet_read_replays,
                                )
                                pass_answer, usage = read_turn.text, read_turn.usage
                                tokens = int(tokens or 0) + read_turn.extra_completion_tokens
                                read_stop = read_turn.stop_reason
                                if active_model_result is not None and active_model_result.response.tool_calls:
                                    read_stop = read_stop or "evidence_read_unknown_tool"
                                    active_pending_tool_calls = max(active_pending_tool_calls, len(active_model_result.response.tool_calls))
                            except CloudBudgetStop:
                                if research_job_service is not None and research_job is not None:
                                    research_job = research_job_service.pause(
                                        research_job["job_id"], phase="cloud_token_budget",
                                        held_packet={**model_rag_evidence_page_state(
                                            sheet=sheet_name, packet=packet, leftover_query_hits=pass_hits,
                                            query_offset=evidence_query_offset,
                                            query_provenance=pass_query_provenance,
                                            query_addresses=pass_query_addresses,
                                            pending_result_packets=pending_result_packets),
                                            "model_read_pending": True, "read_stop": "cloud_token_budget"},
                                    )
                                raise
                            except ContextRequiredSectionOverflow as context_error:
                                retrieval_trace["context_governor"]["error"] = model_read_capacity_trace(
                                    context_error, purpose="sheet_pass_evidence_read")
                                read_stop = "evidence_read_capacity"
                            if read_stop:
                                retrieval_trace["tool_loop"]["evidence_read_stop"] = read_stop
                                run_stop_kinds.append(read_stop)
                                if research_job_service is not None and research_job is not None:
                                    research_job = research_job_service.pause(
                                        research_job["job_id"], remaining=list(dict.fromkeys([*remaining, *packet])),
                                        phase=read_stop,
                                        held_packet={**model_rag_evidence_page_state(
                                            sheet=sheet_name, packet=packet, leftover_query_hits=pass_hits,
                                            query_offset=evidence_query_offset,
                                            query_provenance=pass_query_provenance,
                                            query_addresses=pass_query_addresses,
                                            pending_result_packets=pending_result_packets),
                                            "model_read_pending": True, "read_stop": read_stop},
                                    )
                                break
                            active_pending_tool_calls = 0
                            if not pass_answer:
                                last_finish = llm_usage_finish_reason(usage)
                                tokens = int(tokens or 0) + int(usage.get("completion_tokens") or 0)
                                if execution_preset.reasoning_enabled or finish_reason_is_length(last_finish):
                                    run_stop_kinds.append("model_final_output_missing")
                                    retrieval_trace["model_generation"] = {
                                        "status": "technical_pending", "reason": "model_final_output_missing",
                                        "finish_reason": last_finish,
                                    }
                                    if research_job_service is not None and research_job is not None:
                                        research_job = research_job_service.pause(
                                            research_job["job_id"], remaining=list(dict.fromkeys([*remaining, *packet])),
                                            phase="model_final_output_missing",
                                            held_packet=model_rag_with_pending_results(
                                                {"sheet": sheet_name, "locators": list(packet),
                                                 "model_final_output_missing": True}, pending_result_packets),
                                        )
                                break
                            tokens = int(tokens or 0) + int(
                                usage.get("completion_tokens") or 0
                            )
                            last_finish = llm_usage_finish_reason(usage)
                            last_truncated = (
                                finish_reason_is_length(last_finish)
                                or model_rag_answer_is_truncated(pass_answer)
                            )
                            pass_transport_diagnostics: list[dict[str, Any]] = []
                            artifact_kind_declaration = merge_model_artifact_kind(
                                artifact_kind_declaration, decode_model_artifact_kind(pass_answer))
                            if research_job_service is not None and research_job is not None:
                                research_job = research_job_service.record_artifact_kind(
                                    research_job["job_id"], declaration=artifact_kind_declaration)
                            parsed_pass = parse_model_rag_result(
                                pass_answer, diagnostics=pass_transport_diagnostics,
                            )
                            if pass_transport_diagnostics:
                                for proposal in pass_transport_diagnostics:
                                    proposal["packet_locators"] = list(packet)
                                retrieval_trace.setdefault("model_result_transport_diagnostics", []).extend(
                                    pass_transport_diagnostics
                                )
                            pass_rows: list[dict[str, Any]] = []
                            if parsed_pass is not None:
                                _visible, pass_rows = parsed_pass
                            pass_rows = bind_row_evidence_ids(
                                pass_rows, [*prior_page_chunks, *saved_read_chunks, *model_evidence_chunks]
                            )
                            pass_errors = validate_model_rag_result_structure(
                                pass_rows,
                                [*prior_page_chunks, *saved_read_chunks, *model_evidence_chunks],
                                expected_source_rows=len(packet),
                                source_catalog=source_catalog,
                                source_incomplete_locators=source_incomplete_locators,
                                finish_reason=last_finish,
                                answer_truncated=last_truncated,
                                existing_operation_rows=accumulated_rows,
                                review_operation_rows=review_prior_rows,
                            )
                            tail_locator = truncated_tail_locator(
                                pass_rows, truncated=last_truncated
                            )
                            admission = admit_model_result_packet(
                                pass_rows, packet_locators=packet,
                                prior_operations=[
                                    row for row in model_rag_existing_operation_rows(accumulated_rows, review_prior_rows)
                                    if source_catalog.lookup(row.get("source_row")) is not None
                                    and source_catalog.lookup(row.get("source_row")).locator in set(packet)
                                ],
                                canonicalize_locator=lambda value: (
                                    source_catalog.lookup(value).locator if source_catalog.lookup(value) else value
                                ),
                            )
                            kept = sheet_pass_keep_rows(
                                admission.accepted_rows,
                                sheet=sheet_name,
                                catalog=source_catalog,
                                errors=pass_errors,
                                drop_locator=tail_locator,
                            )
                            if tail_locator:
                                # Addressed handling of the unread tail (blocker § 2):
                                # the cut row is put to the model again, it is not
                                # saved as a decision and not reported as «нет нормы».
                                unread_tail_rows.append(tail_locator)
                                logger.warning(
                                    "[SHEET_PASS] answer cut at finish_reason=%s; "
                                    "row=%s of sheet=%s has no decision columns and "
                                    "stays outstanding",
                                    last_finish,
                                    tail_locator,
                                    sheet_name,
                                )
                            accumulated_rows = merge_model_rag_rows(
                                accumulated_rows,
                                kept,
                                source_catalog,
                            )
                            if pass_answer:
                                answer_parts.append(pass_answer)
                            cited_after = structurally_complete_source_keys(
                                accumulated_rows, source_catalog
                            )
                            settled_after = settled_source_keys(
                                accumulated_rows, source_catalog
                            )
                            # Blocker § 2: найдено / показано / отложено / выбрано
                            # measured for this packet alone, then added to the run
                            # roll-up one number at a time.
                            query_measurement = model_rag_query_measurement(
                                declared_queries=declared_queries,
                                query_provenance=pass_query_provenance,
                                query_addresses=pass_query_addresses,
                                pass_hits=pass_hits,
                                leftover_query_hits=leftover_query_hits,
                                evidence_chunks=model_evidence_chunks,
                                omitted_refs=omitted_now,
                                kept_rows=kept,
                                query_offset=evidence_query_offset,
                            )
                            merge_query_measurement(
                                retrieval_trace.setdefault(
                                    "query_measurement",
                                    {"schema": "les.query-measurement-rollup.v1",
                                     "packets": 0, "groups": {}},
                                ),
                                query_measurement,
                            )
                            retrieval_trace["tool_loop"]["passes"].append(
                                {
                                    "sheet": sheet_name,
                                    "sheet_index": sheet_index,
                                    "inner": inner,
                                    "packet_id": row_packet_id(
                                        source_catalog,
                                        sheet=sheet_name,
                                        locators=packet,
                                    ),
                                    "packet_locators": list(packet),
                                    "packet_attempt": packet_attempts[fingerprint],
                                    "queries": model_queries,
                                    "declared_queries": declared_queries,
                                    "query_calls": query_calls,
                                    "query_answer_cut": query_answer_cut,
                                    "unread_query_tail": unread_query_tail,
                                    "rejected_query_reasons": list(rejected_reasons_now),
                                    "query_measurement": query_measurement,
                                    "shown_queries": len(included_hits),
                                    "evidence_query_offset": evidence_query_offset,
                                    "leftover_queries": len(leftover_query_hits),
                                    "leftover_query_texts": [
                                        str(query) for query, _hits in leftover_query_hits
                                    ][:100],
                                    "omitted_cards": omitted_cards,
                                    "kept_rows": len(kept),
                                    "parsed_rows": len(pass_rows),
                                    "row_errors": list(pass_errors),
                                    "transport_diagnostics": pass_transport_diagnostics,
                                    "finish_reason": last_finish,
                                    "truncated": last_truncated,
                                    "unread_tail_row": tail_locator,
                                    "newly_decided": len(settled_after - settled_before),
                                    "newly_complete": len(cited_after - cited_before),
                                }
                            )
                            remaining = remaining_sheet_work_locators(
                                source_catalog,
                                sheet_name,
                                settled_source_keys(accumulated_rows, source_catalog),
                            )
                            remaining = [
                                locator
                                for locator in remaining
                                if locator not in exhausted_locators
                            ]
                            still_in_packet = [
                                locator
                                for locator in packet
                                if locator in remaining
                            ]
                            # The evidence cursor is independent of settled rows.
                            # A terminal answer on an early page cannot discard
                            # cards the model requested but has not received yet.
                            defer_query_packet = bool(leftover_query_hits)
                            if defer_query_packet:
                                deferred_query_hits = leftover_query_hits
                                held_packet = list(packet)
                                # Advance this immutable raw-query range only.
                                # New native/new-packet handles have a separate
                                # high-water mark and cannot rename its tail.
                                evidence_query_offset += len(included_hits)
                                logger.warning(
                                    "[SHEET_PASS] defer leftover query headers "
                                    "sheet=%s shown=%s leftover=%s remaining_rows=%s",
                                    sheet_name,
                                    len(included_hits),
                                    len(leftover_query_hits),
                                    len(packet),
                                )
                            # One definition of progress for the guard and for the
                            # packet pool.  Judging progress only by the strict
                            # completeness metric counted a row the model had decided
                            # but that keeps a quality gap as zero progress, while that
                            # same row had already left the pool for good: a healthy
                            # sheet then looked stalled and nothing behind it was
                            # reached.  `settled_after` is literally the set the pool
                            # subtracts below, so the two can never disagree again.
                            made_progress = bool(settled_after - settled_before)
                            if not made_progress and not defer_query_packet:
                                if (
                                    packet_attempts[fingerprint]
                                    >= _ROW_PACKET_MAX_ATTEMPTS
                                ):
                                    exhausted_locators.update(packet)
                                    remaining = [
                                        locator
                                        for locator in remaining
                                        if locator not in exhausted_locators
                                    ]
                                    # Blocker § 1: set aside exactly this packet and
                                    # carry that decision across a restart, so the next
                                    # run does not begin from the same dead rows while
                                    # the unseen elements of the other sheets are
                                    # worked.  The deferral lifts itself once the job
                                    # gains evidence or an operator reopens a row.
                                    if (
                                        research_job_service is not None
                                        and research_job is not None
                                    ):
                                        research_job = research_job_service.defer_locators(
                                            research_job["job_id"],
                                            sheet=sheet_name,
                                            locators=packet,
                                            reason=(
                                                f"без предметного решения за "
                                                f"{int(packet_attempts[fingerprint])} "
                                                f"предложения(й)"
                                            ),
                                            offers=int(packet_attempts[fingerprint]),
                                        )
                            if pending_result_packets and not last_truncated:
                                # Only an explicit user reopen plus newly admitted
                                # literal rows resolves prior transport ambiguity.
                                pending_result_packets = model_rag_resolve_pending_results(
                                    pending_result_packets,
                                    {str(row.get("source_row") or "") for row in kept} & explicit_reopened_locators,
                                )
                            held_payload = model_rag_evidence_page_state(
                                sheet=sheet_name, packet=packet,
                                leftover_query_hits=leftover_query_hits,
                                query_offset=evidence_query_offset,
                                query_provenance=pass_query_provenance,
                                query_addresses=pass_query_addresses,
                                pending_result_packets=pending_result_packets)
                            held_query_context = held_payload
                            if not last_truncated and not pass_transport_diagnostics:
                                held_payload.update({
                                    "sheet": sheet_name, "locators": list(packet),
                                    "packet_id": row_packet_id(source_catalog, sheet=sheet_name, locators=packet),
                                    "terminal_model_result_saved": True,
                                })
                            if pass_transport_diagnostics:
                                held_payload = {**dict(held_payload or {}),
                                    "model_result_transport_pending": True,
                                    "locators": list(packet),
                                    "transport_diagnostics": pass_transport_diagnostics}
                                pending_result_packets = model_rag_pending_result_packets(held_payload)
                                held_payload = model_rag_with_pending_results(held_payload, pending_result_packets)
                                held_query_context = held_payload
                            transport_pending_locators, pending_diagnostics = model_rag_pending_result_projection(pending_result_packets)
                            if pending_diagnostics or "model_result_transport_diagnostics" in retrieval_trace:
                                retrieval_trace["model_result_transport_diagnostics"] = pending_diagnostics
                            if leftover_query_hits and research_job_service is not None and research_job is not None:
                                leftover_cache = {
                                    str(query): [durable_research_hit(item) for item in hits]
                                    for query, hits in leftover_query_hits
                                    if str(query).strip()
                                }
                                if leftover_cache:
                                    for query, records in leftover_cache.items():
                                        from proxy.services.workbook_research_job_service import research_cache_entry
                                        sheet_query_cache[query] = research_cache_entry(
                                            records, cache_contract=str(getattr(model_research_tools, "cache_contract", "") or ""))
                                    research_job = research_job_service.record_search_cache(
                                        research_job["job_id"],
                                        leftover_cache,
                                        cache_contract=str(getattr(model_research_tools, "cache_contract", "") or ""),
                                        context={
                                            "sheet": sheet_name,
                                            "packet_id": row_packet_id(
                                                source_catalog,
                                                sheet=sheet_name,
                                                locators=packet,
                                            ),
                                            "locators": list(packet),
                                            "queries": list(leftover_cache),
                                        },
                                    )
                            if (
                                research_job_service is not None
                                and research_job is not None
                            ):
                                research_job = research_job_service.record_packet(
                                    research_job["job_id"],
                                    sheet=sheet_name,
                                    packet_locators=packet,
                                    accepted_rows=[
                                        {
                                            **dict(row),
                                            "row_classification": str(
                                                getattr(
                                                    source_catalog.lookup(
                                                        row.get("source_row")
                                                    ),
                                                    "row_classification",
                                                    "",
                                                )
                                            ),
                                        }
                                        for row in kept
                                    ],
                                    evidence=[
                                        durable_evidence_record(chunk)
                                        for chunk in [*saved_read_chunks, *model_evidence_chunks]
                                    ],
                                    omitted=pass_omitted,
                                    remaining=remaining,
                                    held_packet=held_payload,
                                    unapplied_proposals=[*admission.unapplied_proposals, *pass_transport_diagnostics],
                                    enforce_packet_scope=True,
                                    canonicalize_locator=lambda value: (
                                        source_catalog.lookup(value).locator if source_catalog.lookup(value) else value
                                    ),
                                )
                                # Application IDs/revisions belong to the durable
                                # write. Replay them on the next evidence page and
                                # calculate the same canonical decisions we saved.
                                accumulated_rows = [
                                    dict(row) for row in research_job["accepted_rows"]
                                    if isinstance(row, Mapping)
                                ]
                            explicit_reopened_locators.difference_update(packet)
                            # Blocker § 1 wants the whole chain readable from one
                            # trace: response -> parsed -> kept -> durable merge ->
                            # settled keys -> packet pool -> stall guard.  The guard
                            # half is only known after the durable write, so it is
                            # stamped onto the pass entry that produced it.
                            if retrieval_trace["tool_loop"]["passes"]:
                                durable_rows = 0
                                guard_now: Mapping[str, Any] = {}
                                if isinstance(research_job, Mapping):
                                    durable_rows = len(
                                        research_job.get("accepted_rows") or ()
                                    )
                                    guard_value = research_job.get("stall_guard")
                                    if isinstance(guard_value, Mapping):
                                        guard_now = guard_value
                                retrieval_trace["tool_loop"]["passes"][-1].update(
                                    {
                                        "pool_remaining": len(remaining),
                                        "pool_deferred": len(exhausted_locators),
                                        "durable_rows": durable_rows,
                                        "stall_count": int(
                                            guard_now.get("stall_count") or 0
                                        ),
                                        "pause_kind": str(
                                            guard_now.get("pause_kind") or ""
                                        ),
                                        "run_stops": bool(guard_now.get("run_stops")),
                                    }
                                )
                            if pass_transport_diagnostics:
                                # Preserve the literal failed result without a repair
                                # offer; its technical ambiguity cannot starve new source rows.
                                transport_pending_locators.update(packet)
                                exhausted_locators.update(packet)
                                remaining = [locator for locator in remaining
                                             if locator not in offered_locators and not offer_counts.get(locator, 0)]
                                deferred_query_hits = []
                                held_packet = []
                                held_query_context = {}
                                continue
                            if not last_truncated:
                                # The final answer is scoped to this source packet.
                                # Keep its cursor; only NEVER_REACHED rows may follow.
                                terminal_packet_locators.update(packet)
                                exhausted_locators.update(locator for locator in packet if locator not in settled_after)
                                remaining = [locator for locator in remaining if locator not in set(packet)]
                                if defer_query_packet:
                                    retrieval_trace.setdefault("candidate_body_delivery", {
                                        "status": "saved_after_terminal_packets", "packets": [],
                                    })["packets"].append({
                                        "query_count": len(leftover_query_hits),
                                        "packet_locators": list(packet),
                                        "query_offset": evidence_query_offset,
                                        "saved_rows": len(kept),
                                    })
                                deferred_query_hits = []
                                held_packet = []
                                continue
                            if defer_query_packet:
                                continue
                            if not made_progress:
                                continue
                            if not remaining:
                                break
                        # Blocker § 1: the sheet reports which state each outstanding
                        # row is in, so a row the scheduler never reached is visible as
                        # that fact and is never counted as "the model decided".
                        retrieval_trace.setdefault("sheet_states", {})[sheet_name] = (
                            sheet_pass_state(
                                source_catalog,
                                sheet_name,
                                accumulated_rows,
                                offered_this_pass=tuple(offered_locators),
                                offer_counts=offer_counts,
                                deferred=tuple(exhausted_locators),
                                unread_tail=tuple(unread_tail_rows),
                                deferred_search=tuple(held_packet),
                            )
                        )
                        never_reached = (
                            retrieval_trace["sheet_states"][sheet_name]["never_offered"]
                        )
                        if never_reached:
                            logger.warning(
                                "[SHEET_PASS] sheet=%s still has %s rows never put to "
                                "the model (run stopped early or pool exhausted)",
                                sheet_name,
                                never_reached,
                            )
                    except CloudBudgetStop:
                        # Earlier packets already contain terminal model decisions.
                        # Deliver their ordinary partial workbook without another
                        # inference; unfinished packets remain technical checkpoints.
                        if not accumulated_rows or research_job_service is None or research_job is None:
                            raise
                        budget_snapshot = getattr(getattr(bound_runner, "transport", None), "cloud_budget_snapshot", None)
                        if callable(budget_snapshot):
                            retrieval_trace["cloud_token_budget"] = budget_snapshot()
                            if token_sink is not None:
                                await token_sink({"event": "cloud_budget", "data": retrieval_trace["cloud_token_budget"]})
                        held = dict(research_job.get("held_packet") or {})
                        if list(held.get("locators") or ()) != list(packet):
                            held = {}
                        held.update({"cloud_budget_pending": True, "read_stop": "cloud_token_budget"})
                        held.setdefault("sheet", sheet_name)
                        held.setdefault("locators", list(packet))
                        research_job = research_job_service.pause(
                            research_job["job_id"], phase="cloud_token_budget",
                            held_packet=model_rag_with_pending_results(held, pending_result_packets),
                        )
                        retrieval_trace["tool_loop"]["evidence_read_stop"] = "cloud_token_budget"
                    except asyncio.CancelledError:
                        logger.warning("[SHEET_PASS] cancelled; preserving accepted packets")
                        research_cancelled = True
                    finally:
                        if live_job_id and owns_sheet_pass:
                            release_sheet_pass(live_job_id)
                    if (not any_sheet_queries and not accumulated_rows and not research_cancelled
                            and not terminal_packet_locators and not pending_result_packets):
                        raise model_query_failure("MODEL_RAG_QUERY_LIST_EMPTY", trace=retrieval_trace,
                            session_id=req.session_id, provider=llm_runtime.provider, model=llm_model,
                            secret_values=(llm_runtime.api_key,), final_texts=query_failure_final_texts)
                    # A row the model adjudicated with any terminal role is finished for
                    # completion purposes even if a quality gap remains; only rows that
                    # received NO decision at all are re-queued for the next resume pass.
                    # The packet pool uses this same set, so a row counted as unfinished
                    # here is always still reachable by the loop that produces it.
                    settled_keys = settled_source_keys(accumulated_rows, source_catalog)
                    unfinished_locators = [
                        locator
                        for locator in source_catalog.work_locators()
                        if locator not in settled_keys
                    ]
                    pending_transport = (model_rag_pending_result_projection(pending_result_packets)[0]
                                         if pending_result_packets else set(transport_pending_locators))
                    pending_held = (research_job or {}).get("held_packet") or {}
                    pending_read_stop = (str(pending_held.get("read_stop") or "")
                                         if pending_held.get("model_read_pending") or pending_held.get("cloud_budget_pending") else "")
                    if ((pending_held.get("queries") and not pending_held.get("terminal_model_result_saved")) or pending_held.get("model_read_pending")
                            or pending_held.get("cloud_budget_pending")
                            or pending_held.get("model_result_transport_pending")
                            or pending_held.get("model_final_output_missing")):
                        if pending_held.get("model_result_transport_pending"):
                            pending_held_targets = model_rag_pending_result_targets(pending_held)
                        elif pending_held.get("model_read_pending") or pending_held.get("cloud_budget_pending") or pending_held.get("model_final_output_missing"):
                            pending_held_targets = set(pending_held.get("locators") or ())
                        else:
                            pending_held_targets = {locator for locator in pending_held.get("locators") or ()
                                                    if locator not in settled_keys or locator in pending_transport}
                        pending_transport.update(pending_held_targets)
                        unfinished_locators = list(dict.fromkeys([*unfinished_locators, *pending_transport]))
                    # Unanswered source rows remain gaps; unused candidates do
                    # not make accepted/proven/priced rows incomplete.
                    pending_transport.update(locator for locator in terminal_packet_locators if locator not in settled_keys)
                    resolved_transport_locators = {
                        str(locator) for pending in pending_result_packets
                        for locator in pending.get("resolved_source_rows") or ()
                    }
                    for proposal in retrieval_trace.get("model_result_transport_diagnostics", []):
                        pending_transport.update(locator for locator in model_rag_pending_result_targets(
                            {"transport_diagnostics": [proposal], "locators": proposal.get("packet_locators") or ()})
                                                 if locator not in resolved_transport_locators)
                    unfinished_locators = list(dict.fromkeys([*unfinished_locators, *pending_transport]))
                    if research_job_service is not None and research_job is not None:
                        if owns_sheet_pass:
                            if research_cancelled or unfinished_locators:
                                research_job = research_job_service.pause(
                                    research_job["job_id"],
                                    remaining=unfinished_locators,
                                    phase=pending_read_stop or "packets",
                                    held_packet=model_rag_with_pending_results(
                                        (research_job or {}).get("held_packet") or {}, pending_result_packets),
                                )
                                # A cancelled run stays resumable: the operator
                                # stopped it, so nothing here may close rows the
                                # model never saw.  An identical GLOBAL remainder
                                # reported by consecutive resumes can terminate — but
                                # only for the rows the durable checkpoints prove were
                                # actually put to the model.  Blocker § 1 (29.09)
                                # forbids the old inference from the repeated remainder
                                # that "every row must have been offered on every pass":
                                # on build 823 the plateau carried 278 rows with a zero
                                # offer count behind 17 the model had really seen.
                                guard = research_job.get("stall_guard") or {}
                                repeats = int(guard.get("remainder_repeats") or 0)
                                bound = int(guard.get("terminal_bound") or 0)
                                offer_ledger = packet_offer_counts(
                                    research_job_service.list_events_with_lineage(
                                        research_job["job_id"],
                                        "packet_checkpoint",
                                    )
                                )
                                starved = starved_locators(
                                    unfinished_locators, offer_ledger
                                )
                                closable = [
                                    locator
                                    for locator in unfinished_locators
                                    if locator not in set(starved) and locator not in pending_transport
                                ]
                                # A native read proves this held packet reached the
                                # model even when no terminal row checkpoint exists.
                                # This corrects diagnostics, not completion/closure.
                                read_packet_offered = (set(pending_held.get("locators") or ())
                                                       if pending_held.get("model_read_pending") else set())
                                diagnostic_starved = [locator for locator in starved
                                                      if locator not in read_packet_offered]
                                if (
                                    not research_cancelled
                                    and closable
                                    and bound > 0
                                    and repeats >= bound
                                ):
                                    research_job = (
                                        research_job_service.finish_with_declared_gaps(
                                            research_job["job_id"],
                                            gap_rows=declared_gap_rows(
                                                source_catalog,
                                                closable,
                                                offers=repeats + 1,
                                                offers_by_locator=offer_ledger,
                                            ),
                                            reason=str(guard.get("reason") or ""),
                                            attempts=repeats + 1,
                                            offers_by_locator=offer_ledger,
                                        )
                                    )
                                    retrieval_trace["declared_gaps"] = {
                                        "schema": "les.declared-gaps.v1",
                                        "count": len(closable),
                                        "offers": repeats + 1,
                                        "model_called": False,
                                        "locators": [str(item) for item in closable][:80],
                                        # A technical gap of the scheduler stays open
                                        # and is named as such; declaring it would make
                                        # an unfinished document look finished.
                                        "left_open_never_offered": len(starved),
                                        "left_open_locators": [
                                            str(item) for item in starved
                                        ][:80],
                                    }
                                    logger.info(
                                        "[STALL_BOUND] closing %s rows as declared "
                                        "gaps after %s identical remainders; %s rows "
                                        "stay open (never put to the model)",
                                        len(closable),
                                        repeats,
                                        len(starved),
                                    )
                                elif diagnostic_starved:
                                    retrieval_trace["scheduler_gap"] = {
                                        "schema": "les.scheduler-gap.v1",
                                        "rows_never_offered": len(diagnostic_starved),
                                        "locators": [str(item) for item in diagnostic_starved][:80],
                                        "cause": str(guard.get("reason") or ""),
                                        "pause_kind": str(guard.get("pause_kind") or ""),
                                        "meaning": (
                                            "строки не предложены модели — "
                                            "технический пробел планировщика, "
                                            "а не отсутствие нормы"
                                        ),
                                    }
                                    logger.warning(
                                        "[SCHEDULER_GAP] %s outstanding rows were never "
                                        "put to the model; they stay open instead of "
                                        "being declared as gaps",
                                        len(diagnostic_starved),
                                    )
                            else:
                                research_job = research_job_service.finish(
                                    research_job["job_id"],
                                    status="complete",
                                    phase="research_complete",
                                )
                        retrieval_trace["workbook_research_job"] = {
                            "schema": "les.workbook-research-job.v1",
                            "job_id": research_job["job_id"],
                            # Which research of the same document this turn continued
                            # from ('' on a first run), so an answer that arrives with
                            # 305 decisions already on the row can be told apart from
                            # one whose model produced 305 decisions in this turn.
                            "continues_job_id": str(
                                research_job.get("continues_job_id") or ""
                            ),
                            "status": research_job["status"],
                            "phase": research_job["phase"],
                            "resumable": bool(research_job.get("resumable")),
                            "accepted_rows": len(research_job["accepted_rows"]),
                            "omitted": len(research_job["omitted"]),
                            "remaining": len(research_job.get("remaining") or []),
                            "remaining_locators": list(research_job.get("remaining") or [])[:80],
                            "cached_queries": len(research_job.get("query_cache") or {}),
                            "operator_overrides": dict(research_job.get("operator_overrides") or {}),
                        }
                    await _emit_row_progress(
                        "сборка файла",
                        sheet=sheet_pass_names[-1] if sheet_pass_names else "",
                        index=max(sheet_count, 1),
                    )
                    sheet_pass_done = True
                    sheet_pass_rows = accumulated_rows
                    model_evidence_chunks = sheet_pass_evidence_chunks
                    answer = "\n\n".join(part.strip() for part in answer_parts if part.strip())
                    answer_finish_reason = last_finish
                    rejected_model_queries = pass_rejected
                    # Separated accompanying answer, with the reason each line got
                    # separated: never executed, never thrown away (blocker § 2).
                    retrieval_trace["declared_query_rejections"] = {
                        "schema": "les.declared-query-rejections.v1",
                        "count": len(pass_rejected_reasons),
                        "reasons": rejected_reason_counts(pass_rejected_reasons),
                        "lines": list(pass_rejected_reasons)[:200],
                    }
                    omitted_evidence_refs = pass_omitted
                    crag_status = "MODEL_OUTPUT"
                    cited_all = cited_source_row_keys(accumulated_rows, source_catalog)
                    source_incomplete_locators = [
                        locator
                        for locator in source_catalog.work_locators()
                        if locator not in cited_all
                    ]
                    retrieval_trace["tool_loop"]["sheet_count"] = sheet_count
                    retrieval_trace["tool_loop"]["accumulated_rows"] = len(
                        accumulated_rows
                    )
                    logger.info(
                        "[SHEET_PASS] sheets=%s rows=%s truncated=%s missing=%s",
                        sheet_count,
                        len(accumulated_rows),
                        last_truncated,
                        len(source_incomplete_locators),
                    )
                max_attempts = 1 if model_driven_retrieval else 2
                if not sheet_pass_done:
                  for attempt in range(1, max_attempts + 1):
                    if attempt == 2:
                        # Ретрай не выбрасывает найденные источники: повторная генерация получает
                        # весь уже собранный evidence packet, а не новый кодовый shortlist.
                        strict_chunks = list(chunks)
                        strict_windows = expand_context_windows(
                            strict_chunks if strict_chunks else chunks[:2],
                            collection=getattr(rag_backend, "collection_name", ""),
                            logger=logger,
                            max_chunks=None,
                        )
                        ctx_chunks = strict_windows.chunks
                        evidence_packet = build_retrieval_evidence_packet(
                            question=req.question,
                            chunks=ctx_chunks,
                            retrieval_trace=retrieval_trace,
                            navigation=evidence_navigation,
                            deterministic_evidence=deterministic_evidence,
                        )
                        context = render_retrieval_evidence_for_model(
                            evidence_packet,
                            max_chars=context_chars_limit,
                            include_metadata=True,
                        )
                        answer_source_map = evidence_packet.source_map(max_chars=context_chars_limit, include_metadata=True)
                        final_evidence_packet = evidence_packet.to_dict(max_chars=context_chars_limit, include_metadata=True)
                        retrieval_trace["evidence_packet"] = evidence_packet.trace_summary(
                            max_chars=context_chars_limit,
                            include_metadata=True,
                        )
                        answer_source_map = _merge_web_source_map(
                            answer_source_map,
                            tool_results_for_model,
                        )
                        sys_msg = sys_strict
                        logger.warning("[SAFERAG] Retry #2 — строгий промпт, %s чанков", len(ctx_chunks))
                    else:
                        ctx_chunks = model_evidence_chunks
                        (
                            evidence_packet,
                            context,
                            answer_source_map,
                            final_evidence_packet,
                        ) = _build_model_evidence(ctx_chunks)
                        retrieval_trace["evidence_packet"] = evidence_packet.trace_summary(
                            max_chars=context_chars_limit,
                            include_metadata=True,
                        )
                        answer_source_map = _merge_web_source_map(
                            answer_source_map,
                            tool_results_for_model,
                        )
                        if token_sink is not None and attempt == 1:
                            await token_sink({
                                "event": "sources",
                                "data": {
                                    "sources": source_names(ctx_chunks),
                                    "source_excerpts": source_excerpts(ctx_chunks, max_n=len(ctx_chunks), max_chars=280),
                                    "source_map": answer_source_map,
                                },
                            })
                        # ADR-12 §2: каркас формы под интент добавляем к нормальному промпту.
                        sys_msg = sys_normal + (f" {answer_form.instruction}" if answer_form.instruction else "")
                        # Формат/стиль из GUI (глубина/язык) — ТОЛЬКО в системный промпт генерации,
                        # чтобы роутинг/авто-заметки/ретрив видели чистый вопрос (не мусор-директиву).
                        if req.output_directive and req.output_directive.strip():
                            sys_msg += " " + req.output_directive.strip()
                        if target_doc_filter:
                            sys_msg += (
                                " Оператор явно выбрал документы. Отвечай только по их содержимому, "
                                "явно называй использованные файлы и не расширяй область на остальной датасет."
                            )
                    question_tail = (
                        f"Вопрос: {req.question}\n\n"
                        + ("" if execution_preset.reasoning_enabled else "/no_think\n")
                        +
                        "Дай итоговый инженерный ответ. Не выдумывай факты и используй только существующие "
                        "номера [Источник N]. Если материалов недостаточно, отдели это от подтверждённых выводов."
                    )
                    direct_read_tools = (
                        model_evidence_read_tool_schemas()
                        if model_driven_retrieval
                        and str(getattr(req, "comparative_acceptance_variant", "") or "") == "B0_DIRECT"
                        else []
                    )
                    if direct_read_tools:
                        from proxy.services.lsr_workbook_adapter_service import explicit_estimate_pricebook
                        direct_price_basis = explicit_estimate_pricebook(
                            question_text=str(req.question or ""), source_text=attachment_context,
                            source_name=str(getattr(source_catalog, "original_name", "") or ""),
                        )
                        model_research_tools.set_price_basis(direct_price_basis)
                        sys_msg += "\n" + MODEL_EVIDENCE_READ_INSTRUCTION
                        sys_msg += "\nЗакреплённая ценовая база задания: " + json.dumps(direct_price_basis, ensure_ascii=False)
                    if model_driven_retrieval:
                        question_tail = lsr_result_table_instruction(
                            sheet_clause=question_tail + "\n",
                            remaining_clause=(
                                " Ответ должен вместить все строки: без вводного обзора "
                                "и итоговых рекомендаций, кратко по каждой строке исходника."
                            ),
                        )
                        fixed_model_rag_evidence = selector_evidence_payload(
                            attachment_context=attachment_context,
                            rendered_context="",
                            source_catalog=source_catalog,
                        )
                        _, fixed_packet = govern_inference_messages(
                            preset=answer_execution_preset,
                            profile_prefix=sys_msg,
                            request_payload=question_tail,
                            native_tools=direct_read_tools,
                            checkpoint=(),
                            working_memory=(),
                            evidence=fixed_model_rag_evidence,
                            source_map=(),
                            tool_exchange=(),
                            dialogue=(),
                        )
                        remaining_group_tokens = max(
                            0,
                            fixed_packet.input_budget_tokens
                            - fixed_packet.included_tokens
                            - len(model_rag_query_hits)
                            - 2,
                        )
                        first_read_groups, _ = _model_rag_full_groups(
                            model_rag_query_hits, hits_per_query=retrieval_limits["model_evidence_k"],
                            query_provenance=_model_only_query_provenance(model_rag_query_hits))
                        native_growth_budget = native_read_growth_budget(
                            available_tokens=remaining_group_tokens,
                            generation_tokens=answer_execution_preset.generation_reserve_tokens,
                            groups=first_read_groups, enabled=bool(direct_read_tools))
                        remaining_group_tokens = native_growth_budget["remaining_group_tokens"]
                        logger.warning(
                            "[MODEL_RAG_BUDGET] queries=%s hits=%s input_budget=%s "
                            "included=%s remaining_group_tokens=%s context_chars_limit=%s "
                            "group_max_chars=%s",
                            len(model_rag_query_hits),
                            sum(len(hits) for _query, hits in model_rag_query_hits),
                            fixed_packet.input_budget_tokens,
                            fixed_packet.included_tokens,
                            remaining_group_tokens,
                            context_chars_limit,
                            model_rag_group_char_budget(
                                context_chars_limit=context_chars_limit,
                                remaining_group_tokens=remaining_group_tokens,
                            ),
                        )
                        (
                            model_rag_evidence_groups,
                            model_evidence_chunks,
                            omitted_evidence_refs,
                        ) = build_model_rag_evidence_groups(
                            model_rag_query_hits,
                            max_chars=model_rag_group_char_budget(
                                context_chars_limit=context_chars_limit,
                                remaining_group_tokens=remaining_group_tokens,
                            ),
                            hits_per_query=retrieval_limits["model_evidence_k"],
                            # Single-turn model-RAG path (no sheet-pass): these
                            # queries were all authored by the model, and ADR-16
                            # requires the turn to state that explicitly.
                            query_provenance=_model_only_query_provenance(
                                model_rag_query_hits
                            ),
                        )
                        model_research_tools.register_shown_norm_cards(model_evidence_chunks)
                        context = "\n\n".join(model_rag_evidence_groups)
                        answer_source_map = _model_rag_source_map(model_evidence_chunks)
                        model_rag_evidence_packet = build_retrieval_evidence_packet(
                            question=req.question,
                            chunks=model_evidence_chunks,
                            retrieval_trace=retrieval_trace,
                            navigation=evidence_navigation,
                            deterministic_evidence=deterministic_evidence,
                        )
                        final_evidence_packet = model_rag_evidence_packet.to_dict(
                            max_chars=context_chars_limit,
                            include_metadata=True,
                        )
                        retrieval_trace["grouped_model_evidence"] = {
                            "schema": "les.model-rag-grouped-evidence.v1",
                            "native_read_growth_budget": native_growth_budget,
                            "query_count": len(model_rag_evidence_groups),
                            "hit_count": len(model_evidence_chunks),
                            "returned_hit_count": sum(len(hits) for _q, hits in model_rag_query_hits),
                            "inventory_hit_count": len(model_evidence_chunks),
                            "full_body_hit_count": sum(c.meta.get("body_status") == "full" for c in model_evidence_chunks),
                            "normative_complete_card_count": sum(c.meta.get("normative_card_complete") is True for c in model_evidence_chunks),
                            "normative_preview_card_count": sum(c.meta.get("normative_resources_status") == "preview" for c in model_evidence_chunks),
                            "deferred_body_hit_count": len(omitted_evidence_refs),
                            "unshown_hit_count": sum(ref not in {
                                c.meta.get("model_evidence_ref") for c in model_evidence_chunks}
                                for ref in omitted_evidence_refs),
                            "group_ids": [
                                f"Q{index}"
                                for index in range(1, len(model_rag_evidence_groups) + 1)
                            ],
                            "rendered_chars": len(context),
                            "omitted_evidence_refs": omitted_evidence_refs,
                            "min_body_chars": _MIN_MODEL_RAG_EVIDENCE_BODY_CHARS,
                        }
                    answer_checkpoint = tuple(
                        item
                        for candidate in memory_candidates
                        if candidate.kind == ContextKind.CHECKPOINT
                        for item in candidate.objects
                    )
                    answer_working_memory = tuple(
                        item
                        for candidate in memory_candidates
                        if candidate.kind == ContextKind.WORKING_MEMORY
                        for item in candidate.objects
                    ) + _text_context_objects("working:legacy", memory_block) + _text_context_objects(
                        "working:project-advisory", project_memory_advisory
                    )
                    answer_working_memory += _context_objects(
                        "navigation:status", evidence_navigation
                    )
                    for navigation_name, navigation_text in (
                        ("dataset", dataset_memory_prompt),
                        ("inventory", project_inventory_prompt),
                        ("notebook", notebook_study_prompt),
                        (
                            "selected-documents",
                            "Выбранные документы: " + "; ".join(target_doc_filter) + "."
                            if target_doc_filter else "",
                        ),
                    ):
                        answer_working_memory += _text_context_objects(
                            f"navigation:{navigation_name}", navigation_text
                        )
                    if model_driven_retrieval:
                        answer_checkpoint = ()
                        answer_working_memory = workspace_note_objects(
                            memory_candidates, registered=workspace_memory_registered,
                        )
                    answer_tool_exchange = (
                        []
                        if model_driven_retrieval
                        else [
                            _compact_tool_result_for_prompt(item, max_chars=2400)
                            for item in (research_legacy_results if research_native_exchanges else tool_results_for_model)
                        ]
                    )
                    answer_evidence = (
                        [*fixed_model_rag_evidence, *model_rag_evidence_groups]
                        if model_driven_retrieval
                        else [
                            "Материалы из найденных документов:",
                            *[
                                item.payload
                                for item in _text_context_objects("answer-evidence", context)
                            ],
                        ]
                    )
                    try:
                        messages, answer_packet = govern_inference_messages(
                            preset=answer_execution_preset,
                            profile_prefix=sys_msg + (FINAL_RESEARCH_INSTRUCTION
                                if research_native_exchanges and not model_driven_retrieval and not direct_read_tools else ""),
                            request_payload=question_tail,
                            native_tools=direct_read_tools,
                            checkpoint=answer_checkpoint,
                            working_memory=answer_working_memory,
                            evidence=() if model_driven_retrieval else answer_evidence,
                            required_evidence=answer_evidence if model_driven_retrieval else (),
                            source_map=(() if model_driven_retrieval else answer_source_map),
                            tool_exchange=answer_tool_exchange,
                            native_exchanges=research_native_exchanges,
                            dialogue=[session_block] if session_block else [],
                        )
                    except ContextRequiredSectionOverflow as context_error:
                        retrieval_trace["context_governor"]["error"] = {
                            "code": context_error.code,
                            "budget": context_error.budget,
                            "required_tokens": context_error.required_tokens,
                            "required_objects": len(context_error.object_ids),
                        }
                        raise HTTPException(
                            422,
                            detail={
                                "code": context_error.code,
                                "message": "Обязательная часть запроса не помещается в безопасный контекст модели.",
                            },
                        ) from context_error
                    retrieval_trace["context_governor"]["calls"].append(
                        context_packet_trace(answer_packet, purpose="answer")
                    )
                    if source_catalog is not None:
                        source_incomplete_locators = locators_missing_from_text(
                            source_catalog,
                            packet_evidence_text(answer_packet),
                        )
                    user_prompt = next(
                        (message["content"] for message in messages if message["role"] == "user"),
                        "",
                    )

                    prompt_layers = {
                        "system": len(sys_msg),
                        "evidence": len(context),
                        "tools": len(tool_context),
                        "dataset_navigation": len(dataset_memory_prompt),
                        "inventory_navigation": len(project_inventory_prompt),
                        "notebook_navigation": len(notebook_study_prompt),
                        "session_memory": len(session_block),
                        "working_memory": len(memory_block),
                        "project_memory_advisory": len(project_memory_advisory),
                        "question": len(req.question),
                        "user_total": len(user_prompt),
                        "messages_total": sum(len(str(message.get("content") or "")) for message in messages),
                    }
                    retrieval_trace["prompt_layers"] = prompt_layers
                    logger.info(
                        "[PROMPT] provider=%s model=%s attempt=%s chars=%s layers=%s",
                        llm_runtime.provider,
                        llm_model,
                        attempt,
                        prompt_layers["messages_total"],
                        prompt_layers,
                    )

                    headers = {}
                    if llm_runtime.api_key:
                        headers["Authorization"] = f"Bearer {llm_runtime.api_key}"
                    generation_budget = _generation_token_budget(
                        max_tokens=answer_form.max_tokens,
                        local_big=local_big,
                        attempt=attempt,
                        intent=answer_form.intent,
                    )
                    if answer_execution_preset.answer_output_tokens_requested is not None:
                        generation_budget = answer_execution_preset.generation_reserve_tokens
                    if notebook_study_prompt:
                        generation_budget = min(
                            generation_budget,
                            _env_int("LES_NOTEBOOK_STUDY_MAX_TOKENS", 2048),
                        )
                    if project_inventory_prompt:
                        generation_budget = min(
                            generation_budget,
                            _env_int("LES_PROJECT_INVENTORY_MAX_TOKENS", 3072),
                        )
                    generation_budget = min(
                        generation_budget,
                        answer_execution_preset.generation_reserve_tokens,
                    )
                    if model_driven_retrieval:
                        generation_budget = answer_execution_preset.generation_reserve_tokens

                    chat_body = {
                        "messages": messages,
                        "stream": False,
                        "temperature": profile_temperature(
                            profile_snapshot,
                            fallback=_env_float("CHAT_TEMPERATURE", 0.2),
                        ),
                        "max_tokens": generation_budget,
                    }
                    if direct_read_tools:
                        chat_body["tools"] = direct_read_tools
                    # При стриминге ретрай (строгий промпт) шлёт уже новый текст —
                    # просим клиент очистить накопленное от прошлой попытки.
                    if token_sink is not None and attempt > 1:
                        await token_sink({"event": "reset", "data": ""})
                    t_llm_call = time.time()
                    try:
                        if canonical_execution_mode is CanonicalRouteMode.ACTIVE:
                            answer, usage = await _post_llm(
                                llm_runtime,
                                llm_model,
                                headers,
                                chat_body,
                                allow_stream=not model_driven_retrieval,
                            )
                            if active_model_result is not None:
                                llm_model = active_model_result.connection.model_id
                        elif is_cloud_provider(llm_runtime.provider):
                            # Облако: цепочка моделей с таймаутом на модель (зависла → следующая).
                            answer, usage, llm_model = await _post_cloud_fallback(
                                llm_runtime,
                                headers,
                                chat_body,
                                allow_stream=not model_driven_retrieval,
                            )
                        else:
                            answer, usage = await _post_llm(
                                llm_runtime,
                                llm_model,
                                headers,
                                chat_body,
                                allow_stream=not model_driven_retrieval,
                            )
                    except (httpx.TransportError, httpx.TimeoutException, asyncio.TimeoutError, httpx.HTTPStatusError) as net_err:
                        # W3.3/ADR-9: все облачные модели не ответили → деградация на
                        # локальный MLX. Для не-облака (MLX) ошибку прокидываем как раньше.
                        if not is_cloud_provider(llm_runtime.provider):
                            raise
                        logger.warning(
                            "[ROUTE] облако %s исчерпало модели (%s) — fallback на локальный MLX",
                            llm_runtime.provider, type(net_err).__name__,
                        )
                        llm_runtime = _mlx_runtime()
                        llm_model = llm_runtime.model
                        val_url = llm_runtime.base_url.rstrip("/")
                        validate_via_llm = bool(use_validation and not llm_runtime.supports_validation)
                        fallback_preset = resolve_transport_execution_profile(
                            provider=llm_runtime.provider,
                            model_id=llm_runtime.model,
                            observed_context_tokens=None,
                            observed=False,
                            observed_source="cloud_fallback_unprobed",
                            operator=model_policy,
                        )
                        fallback_answer_preset = model_rag_answer_execution_preset(
                            fallback_preset, model_rag=False,
                        )
                        try:
                            fallback_messages, fallback_packet = govern_inference_messages(
                                preset=fallback_answer_preset,
                                profile_prefix=sys_msg,
                                request_payload=question_tail,
                                checkpoint=answer_checkpoint,
                                working_memory=answer_working_memory,
                                required_evidence=answer_evidence if model_driven_retrieval else (),
                                evidence=[] if model_driven_retrieval else [
                                    "Материалы из найденных документов:",
                                    *[
                                        item.payload
                                        for item in _text_context_objects(
                                            "answer-evidence-fallback", context
                                        )
                                    ],
                                ],
                                source_map=(
                                    () if model_driven_retrieval else answer_source_map
                                ),
                                tool_exchange=answer_tool_exchange,
                                native_exchanges=research_native_exchanges,
                                dialogue=[session_block] if session_block else [],
                            )
                        except ContextRequiredSectionOverflow as context_error:
                            retrieval_trace["context_governor"]["error"] = {
                                "code": context_error.code,
                                "purpose": "answer_fallback",
                                "budget": context_error.budget,
                                "required_tokens": context_error.required_tokens,
                                "required_objects": len(context_error.object_ids),
                            }
                            raise HTTPException(
                                422,
                                detail={
                                    "code": context_error.code,
                                    "message": "Обязательная часть ответа не помещается в локальный fallback-контекст.",
                                },
                            ) from context_error
                        retrieval_trace["context_governor"]["calls"].append(
                            context_packet_trace(fallback_packet, purpose="answer_fallback")
                        )
                        retrieval_trace["context_governor"]["fallback_preset_id"] = (
                            fallback_preset.preset_id
                        )
                        execution_preset = fallback_preset
                        answer_execution_preset = fallback_answer_preset
                        retrieval_trace["model_execution_profile"] = (
                            fallback_answer_preset.diagnostics()
                        )
                        retrieval_trace["model_execution_profile"]["model_preset"]["requested"] = llm_runtime.model
                        headers = {}
                        retrieval_trace.setdefault("routing", {}).update(
                            {"cloud_fallback": type(net_err).__name__, "effective_provider": "mlx", "is_cloud": False}
                        )
                        # Возможный частичный вывод облака до обрыва — отбросить.
                        if token_sink is not None:
                            await token_sink({"event": "reset", "data": ""})
                        fallback_body = {
                            **chat_body,
                            "messages": fallback_messages,
                            "max_tokens": min(
                                int(chat_body.get("max_tokens") or 0),
                                fallback_answer_preset.generation_reserve_tokens,
                            ),
                        }
                        answer, usage = await _post_llm(
                            llm_runtime,
                            llm_model,
                            headers,
                            fallback_body,
                            allow_stream=not model_driven_retrieval,
                        )
                    t_llm += time.time() - t_llm_call
                    if direct_read_tools:
                        confirm_model_read_delivery(
                            model_evidence_chunks,
                            inventory_refs={str(c.meta.get("model_evidence_ref") or "") for c in model_evidence_chunks},
                            body_refs={str(c.meta.get("model_evidence_ref") or "") for c in model_evidence_chunks
                                       if c.meta.get("body_status") != "deferred_capacity"},
                        )
                        model_research_tools.register_shown_norm_cards(model_evidence_chunks)
                        direct_read_groups = []

                        async def _accept_direct_read_replays(batch_receipts):
                            nonlocal active_pending_tool_calls
                            retrieval_trace["tool_loop"].setdefault("evidence_reads", []).extend(batch_receipts)
                            active_pending_tool_calls = max(0, active_pending_tool_calls - len(batch_receipts))

                        async def _accept_direct_reads(batch_receipts, batch_results):
                            nonlocal active_pending_tool_calls, model_requested_price_basis
                            groups, chunks, omitted = bind_model_requested_read_evidence(
                                batch_results, existing_chunks=model_evidence_chunks,
                                reserved_query_end=len(model_rag_query_hits),
                                evidence_namespace="B0_DIRECT:read:" + str(len(model_evidence_chunks)),
                                receipts=batch_receipts,
                            )
                            direct_read_groups.extend(groups)
                            model_evidence_chunks.extend(chunks)
                            model_research_tools.register_shown_norm_cards(chunks)
                            active_pending_tool_calls = max(0, active_pending_tool_calls - len(batch_receipts))
                            retrieval_trace["tool_loop"].setdefault("evidence_reads", []).extend(batch_receipts)
                            model_requested_price_basis = dict(model_research_tools.price_basis_snapshot)
                            return "evidence_read_capacity" if omitted else ""

                        async def _continue_direct_reads(receipts, _results, native_exchanges):
                            nonlocal t_llm, llm_model
                            read_messages, read_frame, inventory_refs, body_refs = govern_model_read_messages(
                                preset=answer_execution_preset, profile_prefix=sys_msg,
                                request_payload=question_tail, native_tools=direct_read_tools,
                                native_exchanges=native_exchanges,
                                source_context=fixed_model_rag_evidence,
                                chunks=model_evidence_chunks, receipts=receipts,
                                admit_messages=_cloud_message_admission(answer_execution_preset, direct_read_tools),
                            )
                            retrieval_trace["context_governor"]["calls"].append(
                                context_packet_trace(read_frame, purpose="direct_evidence_read")
                            )
                            started = time.time()
                            read_text, read_usage = await _post_llm(
                                llm_runtime, llm_model, headers,
                                {**chat_body, "messages": read_messages}, allow_stream=False,
                            )
                            t_llm += time.time() - started
                            confirm_model_read_delivery(model_evidence_chunks, receipts,
                                                        inventory_refs=inventory_refs, body_refs=body_refs)
                            model_research_tools.register_shown_norm_cards(model_evidence_chunks)
                            if active_model_result is not None:
                                llm_model = active_model_result.connection.model_id
                            append_actual_model_call(retrieval_trace, purpose="direct_evidence_read",
                                finish_reason=llm_usage_finish_reason(read_usage),
                                completion_tokens=int(read_usage.get("completion_tokens") or 0))
                            return read_text, read_usage

                        try:
                            read_turn = await run_model_evidence_read_turn(
                                text=answer, usage=usage, parse_calls=_parse_model_tool_calls,
                                execute=model_research_tools.execute,
                                continue_native_turn=_continue_direct_reads, on_read_results=_accept_direct_reads,
                                on_read_replays=_accept_direct_read_replays,
                                allowed_tools={item["function"]["name"] for item in direct_read_tools},
                                max_calls=max(1, _env_int("LES_CHAT_TOOL_MAX_CALLS", 48)),
                            )
                            answer, usage = read_turn.text, read_turn.usage
                            direct_read_stop = read_turn.stop_reason
                            if active_model_result is not None and active_model_result.response.tool_calls:
                                direct_read_stop = direct_read_stop or "evidence_read_unknown_tool"
                                active_pending_tool_calls = max(active_pending_tool_calls, len(active_model_result.response.tool_calls))
                            usage = {**usage, "completion_tokens": read_turn.extra_completion_tokens
                                     + (0 if direct_read_stop else int(usage.get("completion_tokens") or 0))}
                        except ContextRequiredSectionOverflow as context_error:
                            retrieval_trace["context_governor"]["error"] = model_read_capacity_trace(
                                context_error, purpose="direct_evidence_read")
                            direct_read_stop = "evidence_read_capacity"
                        retrieval_trace["tool_loop"]["evidence_read_stop"] = direct_read_stop
                        answer_source_map = _model_rag_source_map(model_evidence_chunks)
                        selector_source_map = answer_source_map
                        if direct_read_stop:
                            answer = "Техническая остановка чтения источников: " + direct_read_stop + ". Решение модели не завершено; ЛСР не упакована."
                        else:
                            active_pending_tool_calls = 0
                    if (not model_driven_retrieval and not direct_read_tools and active_model_result is not None
                            and (active_model_result.response.tool_calls
                                 or (research_native_exchanges and has_unconsumed_tool_frame(answer)))):
                        tokens = int(usage.get("completion_tokens") or 0)
                        answer_finish_reason = llm_usage_finish_reason(usage)
                        active_pending_tool_calls = max(active_pending_tool_calls, len(active_model_result.response.tool_calls))
                        retrieval_trace["model_generation"] = {
                            "status": "technical_pending", "reason": "model_tool_request_in_final_answer",
                            "finish_reason": answer_finish_reason,
                            "unconsumed_tool_calls": len(active_model_result.response.tool_calls),
                            "unparsed_tool_frame": has_unconsumed_tool_frame(answer),
                        }
                        answer = ("Ответ не завершён: после окончания поиска модель запросила дополнительные "
                                  "действия вместо итогового ответа. Найденные источники сохранены в истории запроса.")
                        crag_status = "MODEL_OUTPUT_INCOMPLETE"
                        break
                    if not answer:
                        if execution_preset.reasoning_enabled or finish_reason_is_length(llm_usage_finish_reason(usage)):
                            answer_finish_reason = llm_usage_finish_reason(usage)
                            tokens = int(usage.get("completion_tokens") or 0)
                            retrieval_trace["model_generation"] = {
                                "status": "technical_pending", "reason": "model_final_output_missing",
                                "finish_reason": answer_finish_reason,
                            }
                            answer = (
                                "Генерация не завершена: модель не вернула финальный ответ. "
                                "Рассуждения не используются как строки сметы; ЛСР не упакована."
                            )
                            crag_status = "MODEL_OUTPUT_INCOMPLETE"
                            break
                        if attempt < max_attempts:
                            logger.warning("[CHAT] empty LLM answer on attempt=%s — retrying strict", attempt)
                            continue
                        raise ValueError(f"Пустой ответ LLM (stream={token_sink is not None})")
                    tokens = usage.get("completion_tokens", 0)
                    answer_finish_reason = llm_usage_finish_reason(usage)
                    # W3.3: учёт расходов облака (токены → $). Локальные вызовы не считаем.
                    if is_cloud_provider(llm_runtime.provider):
                        _record_cloud_cost(state, llm_model, usage)
                    logger.info(
                        "[CHAT] attempt=%s provider=%s model=%s tokens=%s",
                        attempt,
                        llm_runtime.provider,
                        llm_model,
                        tokens,
                    )

                    crag_status = "MODEL_OUTPUT"
                    logger.info("[CHAT] model answer accepted unchanged; citation check is trace-only")
                    break

                if model_driven_retrieval:
                    if sheet_pass_done:
                        parsed_model_result = (
                            (answer, sheet_pass_rows) if sheet_pass_rows else None
                        )
                    else:
                        artifact_kind_declaration = merge_model_artifact_kind(
                            artifact_kind_declaration, decode_model_artifact_kind(answer))
                        parsed_model_result = parse_model_rag_result(
                            answer, diagnostics=retrieval_trace.setdefault("model_result_transport_diagnostics", []),
                        )
                        expected_format_locators = (
                            list(source_catalog.work_locators())
                            if source_catalog is not None
                            else []
                        )
                        first_rows = (
                            parsed_model_result[1] if parsed_model_result is not None else []
                        )
                        first_keys = {
                            str(item.get("source_row") or "").strip()
                            for item in first_rows
                            if str(item.get("source_row") or "").strip()
                        }
                        # The ordinary active path has one terminal professional
                        # model result (ADR-15).  A format-repair call is useful for
                        # isolated diagnostics, but may not silently replace that
                        # result in the user's workbook path.
                        need_format_retry = comparative_variant == "QUALITY_DIAGNOSTIC" and (
                            parsed_model_result is None
                            or any(invented_source_row(key) for key in first_keys)
                            or (
                                bool(expected_format_locators)
                                and first_keys != set(expected_format_locators)
                            )
                        )
                        if need_format_retry:
                            retry_messages, retry_packet = govern_inference_messages(
                                preset=answer_execution_preset,
                                profile_prefix=lsr_format_retry_instruction(),
                                request_payload={
                                    "expected_locators": expected_format_locators
                                    or sorted(first_keys),
                                },
                                checkpoint=(),
                                working_memory=(),
                                evidence=[answer],
                                source_map=(),
                                tool_exchange=(),
                                dialogue=(),
                            )
                            retrieval_trace["context_governor"]["calls"].append(
                                context_packet_trace(
                                    retry_packet, purpose="lsr_format_retry"
                                )
                            )
                            retry_text, retry_usage = await _post_llm(
                                llm_runtime,
                                llm_model,
                                query_headers,
                                {
                                    "messages": retry_messages,
                                    "stream": False,
                                    "temperature": 0,
                                    "max_tokens": answer_execution_preset.generation_reserve_tokens,
                                },
                                allow_stream=False,
                            )
                            tokens = int(tokens or 0) + int(
                                (retry_usage or {}).get("completion_tokens") or 0
                            )
                            retry_parsed = parse_model_rag_result(retry_text or "")
                            if parsed_model_result is None:
                                parsed_model_result = retry_parsed
                                if retry_parsed is not None:
                                    answer = retry_parsed[0]
                            elif retry_parsed is not None:
                                parsed_model_result = (
                                    parsed_model_result[0],
                                    merge_format_retry_rows(
                                        first_rows,
                                        retry_parsed[1],
                                        expected_format_locators or None,
                                    ),
                                )
                            retrieval_trace["format_retry"] = {
                                "needed": True,
                                "recovered": parsed_model_result is not None,
                            }
                    model_result_rows: list[dict[str, Any]] = []
                    model_result_errors: list[str] = []
                    model_result_blocking_errors: list[str] = []
                    # The durable job, not the re-parsed answer, decides what the
                    # final revision contains once the job reached its terminal
                    # state; a not-yet-terminal durable job makes the packaged
                    # file an explicitly marked draft.
                    durable_packaging_rows = terminal_research_packaging_rows(
                        research_job
                    )
                    packaging_is_draft = bool(research_job) and not durable_packaging_rows
                    if parsed_model_result is not None:
                        answer, model_result_rows = parsed_model_result
                        # The model's first complete result is the terminal professional
                        # decision in the active estimator path (ADR-15).  The historical
                        # verifier/research loop remains available only for an explicit
                        # isolated diagnostic run; it must never rewrite or block the
                        # ordinary user workbook.
                        quality_diagnostic = comparative_variant == "QUALITY_DIAGNOSTIC"
                        if model_driven_retrieval and model_result_rows and quality_diagnostic:
                            async def _verify_quality_rows(rows_to_check, previous_response=None):
                                evidence_items = build_blind_review_evidence_items(
                                    rows_to_check, model_evidence_chunks
                                )
                                messages, packet = govern_inference_messages(
                                    preset=answer_execution_preset,
                                    profile_prefix=lsr_verifier_instruction(),
                                    request_payload={
                                        "task": "Проверь применимость выбранных норм к строкам ВОР.",
                                        **({
                                            "format_repair": lsr_verifier_format_retry_instruction(),
                                            "previous_response": previous_response,
                                        } if previous_response is not None else {}),
                                    },
                                    checkpoint=(),
                                    working_memory=(),
                                    evidence=evidence_items,
                                    source_map=(),
                                    tool_exchange=(),
                                    dialogue=(),
                                )
                                retrieval_trace["context_governor"]["calls"].append(
                                    context_packet_trace(
                                        packet, purpose="lsr_norm_verifier"
                                    )
                                )
                                if packet.omissions and len(rows_to_check) > 1:
                                    midpoint = len(rows_to_check) // 2
                                    left = await _verify_quality_rows(rows_to_check[:midpoint], previous_response)
                                    right = await _verify_quality_rows(rows_to_check[midpoint:], previous_response)
                                    return left + "\n\n" + right
                                if packet.omissions:
                                    raise ValueError("LSR_VERIFIER_EVIDENCE_INCOMPLETE")
                                text, usage = await _post_llm(
                                    llm_runtime,
                                    llm_model,
                                    query_headers,
                                    {
                                        "messages": messages,
                                        "stream": False,
                                        "temperature": 0,
                                        "max_tokens": verifier_generation_tokens(
                                            len(rows_to_check),
                                            answer_execution_preset.generation_reserve_tokens,
                                        ),
                                    },
                                    allow_stream=False,
                                )
                                tokens_now = int((usage or {}).get("completion_tokens") or 0)
                                nonlocal tokens
                                tokens = int(tokens or 0) + tokens_now
                                retrieval_trace.setdefault("norm_quality_model_calls", []).append({
                                    "stage": "verify_format_repair" if previous_response is not None else "verify",
                                    "locators": [item.get("source_row") for item in rows_to_check],
                                    "finish_reason": llm_usage_finish_reason(usage),
                                    "completion_tokens": tokens_now,
                                    "response": str(text or "")[:32000],
                                    "response_truncated": len(str(text or "")) > 32000,
                                })
                                return text or ""

                            async def _repair_quality_rows(rows_to_check, previous_response):
                                return await _verify_quality_rows(rows_to_check, previous_response)

                            async def _research_quality_rows(rows_to_check, round_index):
                                nonlocal model_evidence_chunks
                                # Bound work by row packets, never by dropping evidence.
                                if len(rows_to_check) > 3:
                                    partials = []
                                    for offset in range(0, len(rows_to_check), 3):
                                        partials.append(await _research_quality_rows(rows_to_check[offset:offset + 3], round_index))
                                    return LsrResearchRoundResult(
                                        rows=[row for part in partials for row in part.rows],
                                        queries=tuple(q for part in partials for q in part.queries),
                                        hit_ids=tuple(i for part in partials for i in part.hit_ids),
                                        card_ids=tuple(i for part in partials for i in part.card_ids),
                                    )
                                locators = [
                                    str(item.get("source_row") or "").strip()
                                    for item in rows_to_check
                                    if str(item.get("source_row") or "").strip()
                                ]
                                if model_research_tools is None:
                                    return LsrResearchRoundResult(rows=list(rows_to_check))
                                # The echo comparison (blocker § 2) is made against the
                                # task statement only.  The rejected-cipher tail this call
                                # also sends is packet data: a query that repeats a row's
                                # wording is what the prompt asks for, so it must not be
                                # mistaken for the model handing its task back.
                                research_queries_task = lsr_research_query_instruction(
                                    round_index
                                )
                                query_messages, query_packet = govern_inference_messages(
                                    preset=query_execution_preset,
                                    profile_prefix=(
                                        profile_system_prompt(
                                            profile_snapshot, strict=False
                                        )
                                        + "\n\n"
                                        + lsr_research_query_instruction(
                                            round_index, rows_to_check
                                        )
                                    ),
                                    request_payload={
                                        "question": str(req.question or ""),
                                        "unresolved": locators,
                                        "rows": [
                                            {
                                                "source_row": item.get("source_row"),
                                                "title": item.get("title"),
                                                "unit": item.get("unit"),
                                                "rejected_norm_codes": list(
                                                    item.get("_rejected_codes") or []
                                                ),
                                            }
                                            for item in rows_to_check
                                        ],
                                    },
                                    checkpoint=(),
                                    working_memory=(),
                                    evidence=selector_evidence,
                                    source_map=(),
                                    tool_exchange=(),
                                )
                                retrieval_trace["context_governor"]["calls"].append(
                                    context_packet_trace(
                                        query_packet,
                                        purpose="lsr_norm_research_queries",
                                    )
                                )
                                query_text, _query_usage = await _post_llm(
                                    llm_runtime,
                                    llm_model,
                                    query_headers,
                                    {
                                        "messages": query_messages,
                                        "stream": False,
                                        "temperature": 0,
                                        "max_tokens": min(1600, query_packet.generation_reserve_tokens),
                                    },
                                    allow_stream=False,
                                    inference_preset=query_execution_preset,
                                )
                                queries, _rejected = classify_model_rag_query_lines(
                                    query_text, research_queries_task
                                )
                                hits: list[tuple[str, Sequence[Any]]] = []
                                hit_ids: list[str] = []
                                card_ids: list[str] = []
                                for query in queries:
                                    research_result = await model_research_tools.execute(
                                        {"tool": "search_sources", "args": {"q": query}}
                                    )
                                    chunk_tuple = tuple(research_result.chunks)[
                                        : retrieval_limits["model_evidence_k"]
                                    ]
                                    hits.append((query, chunk_tuple))
                                    for chunk in chunk_tuple:
                                        hit_ids.append(
                                            str(
                                                getattr(chunk, "doc_id", "")
                                                or getattr(chunk, "doc_name", "")
                                            )
                                        )
                                        meta = dict(getattr(chunk, "meta", {}) or {})
                                        if meta.get("norm_code"):
                                            card_ids.append(str(meta["norm_code"]))
                                if not hits:
                                    return LsrResearchRoundResult(
                                        rows=list(rows_to_check),
                                        queries=tuple(queries),
                                    )
                                groups, chunks, _omitted = build_model_rag_evidence_groups(
                                    hits,
                                    max_chars=context_chars_limit,
                                    hits_per_query=retrieval_limits["model_evidence_k"],
                                    query_offset=max((int((getattr(chunk, "meta", {}) or {}).get("model_query_index") or 0) for chunk in model_evidence_chunks), default=0),
                                    # Quality-diagnostic re-research: ``queries``
                                    # come from the model, so the round states it.
                                    query_provenance=_model_only_query_provenance(hits),
                                )
                                model_evidence_chunks.extend(list(chunks))
                                result_tail = lsr_result_table_instruction(
                                    sheet_clause="Повторный подбор только для неподтверждённых строк.\n",
                                    remaining_clause=" Остались строки: "
                                    + ", ".join(locators[:40])
                                    + rejected_codes_clause(rows_to_check),
                                )
                                messages, packet = govern_inference_messages(
                                    preset=answer_execution_preset,
                                    profile_prefix=profile_system_prompt(
                                        profile_snapshot, strict=False
                                    ),
                                    request_payload={
                                        "task": result_tail,
                                        "question": str(req.question or ""),
                                        "rows": [dict(item) for item in rows_to_check],
                                    },
                                    checkpoint=(),
                                    working_memory=(),
                                    evidence=lsr_research_result_evidence(
                                        rows_to_check, groups
                                    ),
                                    source_map=(),
                                    tool_exchange=(),
                                )
                                retrieval_trace["context_governor"]["calls"].append(
                                    context_packet_trace(
                                        packet, purpose="lsr_norm_research_result"
                                    )
                                )
                                text, _usage = await _post_llm(
                                    llm_runtime,
                                    llm_model,
                                    query_headers,
                                    {
                                        "messages": messages,
                                        "stream": False,
                                        "temperature": profile_temperature(
                                            profile_snapshot, fallback=0.2
                                        ),
                                        "max_tokens": (
                                            answer_execution_preset.generation_reserve_tokens
                                        ),
                                    },
                                    allow_stream=False,
                                )
                                parsed = parse_model_rag_result(text or "")
                                new_rows = parsed[1] if parsed else list(rows_to_check)
                                new_rows = bind_row_evidence_ids(new_rows, chunks)
                                new_rows = bind_row_evidence_ids(
                                    new_rows, model_evidence_chunks
                                )
                                return LsrResearchRoundResult(
                                    rows=new_rows,
                                    queries=tuple(queries),
                                    hit_ids=tuple(hit_ids),
                                    card_ids=tuple(card_ids),
                                )

                            async def _review_coefficients(rows_to_check):
                                evidence_items = [
                                    "\n".join(
                                        [
                                            f"## source_row={item.get('source_row')}",
                                            f"ВОР: {item.get('title') or ''}",
                                            f"Шифр: {item.get('norm_code') or ''}",
                                            f"Коэффициент: {item.get('coefficient')}",
                                            f"applies_to: {item.get('coefficient_applies_to') or ''}",
                                        ]
                                    )
                                    for item in rows_to_check
                                ]
                                messages, packet = govern_inference_messages(
                                    preset=answer_execution_preset,
                                    profile_prefix=lsr_coefficient_instruction(),
                                    request_payload="Проверь только коэффициенты указанных строк.",
                                    checkpoint=(),
                                    working_memory=(),
                                    evidence=evidence_items,
                                    source_map=(),
                                    tool_exchange=(),
                                    dialogue=(),
                                )
                                retrieval_trace["context_governor"]["calls"].append(
                                    context_packet_trace(
                                        packet, purpose="lsr_coefficient_review"
                                    )
                                )
                                text, usage = await _post_llm(
                                    llm_runtime,
                                    llm_model,
                                    query_headers,
                                    {
                                        "messages": messages,
                                        "stream": False,
                                        "temperature": 0,
                                        "max_tokens": verifier_generation_tokens(
                                            len(rows_to_check),
                                            answer_execution_preset.generation_reserve_tokens,
                                        ),
                                    },
                                    allow_stream=False,
                                )
                                tokens_now = int((usage or {}).get("completion_tokens") or 0)
                                nonlocal tokens
                                tokens = int(tokens or 0) + tokens_now
                                return text or ""

                            try:
                                if sheet_pass_done:
                                    leftover = [
                                        row
                                        for row in model_result_rows
                                        if not row_is_quality_terminal(row)
                                    ]
                                    if leftover:
                                        model_result_rows = merge_quality_gated_rows(
                                            model_result_rows,
                                            [
                                                mark_research_exhausted(row)
                                                for row in leftover
                                            ],
                                            source_catalog,
                                        )
                                    retrieval_trace["norm_quality_gate"] = {
                                        "schema": "les.lsr-norm-quality-gate.v1",
                                        "norms_status": aggregate_norms_status(
                                            model_result_rows
                                        ),
                                        "events": [{"stage": "sheet_pass_terminal"}],
                                    }
                                else:
                                    gate = await run_lsr_norm_quality_loop(
                                    model_result_rows,
                                        verify=_verify_quality_rows,
                                        repair_verification=_repair_quality_rows,
                                        research=_research_quality_rows,
                                        evidence_chunks=model_evidence_chunks,
                                        source_locators=(
                                            source_catalog.work_locators()
                                            if source_catalog is not None
                                            else None
                                        ),
                                    )
                                    model_result_rows = bind_row_evidence_ids(
                                        gate.rows, model_evidence_chunks
                                    )
                                    model_result_rows, coef_events = await run_coefficient_review(
                                        model_result_rows,
                                        review=_review_coefficients,
                                    )
                                    retrieval_trace["norm_quality_gate"] = {
                                        "schema": "les.lsr-norm-quality-gate.v1",
                                        "norms_status": gate.norms_status,
                                        "events": [*gate.events, *coef_events],
                                    }
                            except Exception:
                                logger.exception(
                                    "[LSR_QUALITY] gate failed; rows stay unverified"
                                )
                                model_result_rows = [
                                    prepare_selection_row(row)
                                    for row in model_result_rows
                                ]
                                retrieval_trace["norm_quality_gate"] = {
                                    "schema": "les.lsr-norm-quality-gate.v1",
                                    "status": "error",
                                    "norms_status": "norms_unverified",
                                }
                        elif model_driven_retrieval and model_result_rows:
                            retrieval_trace["norm_quality_gate"] = {
                                "schema": "les.lsr-norm-quality-gate.v1",
                                "status": "not_run",
                                "reason": "terminal_model_result_preserved",
                                "norms_status": "model_authored",
                            }
                        from proxy.services.smeta_chat_adapter_service import (
                            _smeta_source_row_count,
                        )

                        if source_catalog is not None:
                            sheet_coverage = sheet_coverage_from_missing(
                                source_catalog,
                                source_incomplete_locators,
                            )
                            # Catalog is complete on disk. Omitted Governor rows
                            # are recorded, but they do not count as a silent cut.
                            attachment_truncated = False
                        else:
                            attachment_truncated = attachment_context_is_truncated(
                                attachment_context
                            )
                            sheet_coverage = parse_attachment_sheet_coverage(
                                attachment_context
                            )
                        retrieval_trace["attachment_integrity"] = {
                            "truncated": bool(source_incomplete_locators)
                            if source_catalog is not None
                            else attachment_truncated,
                            "included_sheets": sheet_coverage["included"],
                            "omitted_sheets": sheet_coverage["omitted"],
                            "catalog_rows": (
                                len(source_catalog.rows) if source_catalog is not None else 0
                            ),
                            "omitted_source_count": len(source_incomplete_locators),
                            "omitted_source_locators": list(source_incomplete_locators[:40]),
                            "finish_reason": answer_finish_reason,
                            "sheet_pass": sheet_pass_done,
                        }
                        model_result_rows = bind_row_evidence_ids(
                            model_result_rows, model_evidence_chunks
                        )
                        model_result_errors = validate_model_rag_result_structure(
                            model_result_rows,
                            model_evidence_chunks,
                            expected_source_rows=_smeta_source_row_count(
                                attachment_context
                            ),
                            attachment_truncated=attachment_truncated,
                            answer_truncated=model_rag_answer_is_truncated(answer),
                            source_catalog=source_catalog,
                            source_incomplete_locators=source_incomplete_locators,
                            finish_reason=answer_finish_reason,
                            validate_evidence_refs=True,
                        )
                        if research_cancelled:
                            model_result_errors.append("workbook_research_cancelled")
                        if retrieval_trace.get("model_result_transport_diagnostics"):
                            model_result_errors.append("MODEL_RESULT_TABLE_ROW_WIDTH_MISMATCH")
                        work_row_count = sum(
                            1
                            for row in model_result_rows
                            if model_rag_row_kind(row) == "work"
                        )
                        model_result_blocking_errors = blocking_model_rag_result_errors(
                            model_result_errors,
                            work_row_count=work_row_count,
                        )
                        if durable_packaging_rows:
                            # Terminal durable state wins over the ephemeral
                            # re-parse: the accepted decisions are already saved
                            # and the final revision is packaged from that full
                            # set unchanged (no model re-call). Re-parse noise
                            # stays visible in model_result_errors but can no
                            # longer suppress the complete artifact.
                            model_result_rows = durable_packaging_rows
                            model_result_blocking_errors = []
                        elif retrieval_trace.get("model_result_transport_diagnostics"):
                            model_result_blocking_errors.append("MODEL_RESULT_TABLE_ROW_WIDTH_MISMATCH")
                        notice_kwargs = {
                            "errors": model_result_errors,
                            "row_count": len(model_result_rows),
                            "attachment_truncated": bool(
                                attachment_truncated or sheet_coverage["omitted"]
                            ),
                            "included_sheets": sheet_coverage["included"],
                            "omitted_sheets": sheet_coverage["omitted"],
                            "rejected_queries": len(rejected_model_queries),
                            "omitted_evidence": len(omitted_evidence_refs),
                        }
                        if model_result_blocking_errors:
                            notice = format_lsr_not_created_notice(**notice_kwargs)
                            if notice not in answer:
                                answer = f"{answer.rstrip()}\n\n{notice}"
                            retrieval_trace["model_result"] = {
                                "schema": "les_model_rag_result_v1",
                                "status": "structural_error",
                                "row_count": len(model_result_rows),
                                "packaged": False,
                                "errors": model_result_errors,
                                "notice": notice,
                            }
                        elif model_result_errors or sheet_coverage["omitted"]:
                            notice = format_lsr_partial_notice(**notice_kwargs)
                            if notice not in answer:
                                answer = f"{answer.rstrip()}\n\n{notice}"
                            retrieval_trace["model_result"] = {
                                "schema": "les_model_rag_result_v1",
                                "status": "accepted_with_integrity_warning",
                                "row_count": len(model_result_rows),
                                "packaged": False,
                                "warnings": model_result_errors,
                                "notice": notice,
                            }
                    else:
                        read_stop_reason = str((retrieval_trace.get("tool_loop") or {}).get(
                            "evidence_read_stop") or "")
                        notice = (
                            "Чтение источников приостановлено: данные для следующего шага "
                            "не помещаются в окно контекста модели. ЛСР ещё не собрана."
                            if read_stop_reason == "evidence_read_capacity" else
                            "Чтение источников технически приостановлено (" + read_stop_reason
                            + "). Итоговое решение модели ещё не получено; ЛСР не собрана."
                            if read_stop_reason else format_lsr_unstructured_notice(
                                sheet_pass_empty=bool(sheet_pass_done))
                        )
                        if notice not in answer:
                            answer = f"{answer.rstrip()}\n\n{notice}"
                        retrieval_trace["model_result"] = {
                            "schema": "les_model_rag_result_v1",
                            "status": "technical_pending" if read_stop_reason else "unstructured",
                            **({"reason": read_stop_reason} if read_stop_reason else {}),
                            "packaged": False,
                            "notice": notice,
                        }
                    result_meta = retrieval_trace.setdefault("model_result", {
                        "schema": "les_model_rag_result_v1", "status": "accepted_unchanged",
                        "row_count": len(model_result_rows), "packaged": False,
                    })
                    if isinstance(result_meta, dict):
                        result_meta["finish_reason"] = answer_finish_reason
                    transport_diagnostics = retrieval_trace.get("model_result_transport_diagnostics") or []
                    if transport_diagnostics:
                        notice = (
                            "Техническая ошибка таблицы: число ячеек не соответствует заголовку "
                            f"в {len(transport_diagnostics)} строках. Исходные строки сохранены как "
                            "неприменённые предложения; их нормы, объёмы и цены не подставлены."
                        )
                        if notice not in answer:
                            answer = f"{answer.rstrip()}\n\n{notice}"
                        if isinstance(result_meta, dict):
                            result_meta["transport_diagnostics"] = transport_diagnostics
                    if token_sink is not None:
                        await token_sink({"event": "reset", "data": ""})
                        if answer:
                            await token_sink({"event": "token", "data": answer})
                    attachment_id = str(getattr(req, "attachment_id", None) or "").strip()
                    packaging_tools = workbook_packaging_tool(
                        profile_tools, str(getattr(req, "question", "") or ""),
                        task_context=(research_job or {}).get("task_context"),
                        model_declaration=artifact_kind_declaration,
                    )
                    retrieval_trace["artifact_target"] = dict(artifact_kind_declaration)
                    if not packaging_tools and (model_result_rows or durable_packaging_rows):
                        target_notice = "Тип итогового документа пока не определён. Строки сохранены; уточните в чате, нужна ВОР или ЛСР."
                        if target_notice not in answer:
                            answer = f"{answer.rstrip()}\n\n{target_notice}"
                        if isinstance(result_meta, dict):
                            result_meta["packaging_status"] = "pending"
                            result_meta["packaging_reason"] = "ARTIFACT_KIND_UNRESOLVED"
                            result_meta["packaged"] = False
                        if token_sink is not None:
                            await token_sink({"event": "reset", "data": ""})
                            await token_sink({"event": "token", "data": answer})
                    saved_draft_rows = [dict(row) for row in (research_job or {}).get("accepted_rows") or ()
                                        if isinstance(row, Mapping)]
                    can_package_saved_draft = bool(
                        saved_draft_rows and packaging_tools == ["build_lsr_workbook"]
                        and str((research_job or {}).get("status") or "") == "paused"
                        and all(str(error) == "MODEL_RESULT_TABLE_ROW_WIDTH_MISMATCH"
                                or str(error).startswith(("source_quantity_unconfirmed:", "source_quantity_mismatch:"))
                                for error in model_result_blocking_errors)
                    )
                    document_issues = workbook_document_issues(
                        research_job, errors=model_result_blocking_errors,
                        transport_diagnostics=transport_diagnostics,
                    )
                    if can_package_saved_draft:
                        model_result_rows = saved_draft_rows
                        packaging_is_draft = True
                        if model_result_blocking_errors and isinstance(result_meta, dict):
                            old_notice = str(result_meta.get("notice") or "")
                            draft_notice = "Сохранённые корректные строки включены в промежуточную ЛСР; технические ошибки и неприменённые строки остаются открытыми."
                            if old_notice:
                                answer = answer.replace(old_notice, draft_notice, 1)
                            result_meta["notice"] = draft_notice
                    if (
                        (parsed_model_result is not None or bool(durable_packaging_rows) or can_package_saved_draft)
                        and (
                            bool(model_result_rows)
                            or bool(durable_packaging_rows)
                            or packaging_tools == ["build_vor_workbook"]
                        )
                        and (not model_result_blocking_errors or can_package_saved_draft)
                        and attachment_id
                        and packaging_tools
                        and workbook_tool_executor is not None
                        and canonical_execution_mode is CanonicalRouteMode.ACTIVE
                    ):
                        async def workbook_progress(event: dict[str, Any]) -> None:
                            if token_sink is not None:
                                await token_sink({"event": "tool_progress", "data": event})

                        packaging_trace: list[dict[str, Any]] = []
                        packaging_failures: list[dict[str, Any]] = []
                        workbook_files: list[dict[str, str]] = []
                        # Keep one downloadable document per durable job: a new
                        # decision set chains from the last revision this job
                        # packaged; an already-settled final revision is replayed
                        # with its own identity so a re-open serves the same file.
                        packaging_parents: dict[str, str] = {}
                        packaging_settled: dict[str, str | None] = {}
                        packaging_events: list[dict[str, Any]] = []
                        if research_job_service is not None and research_job is not None:
                            packaging_events = research_job_service.list_events(
                                str(research_job.get("job_id") or "")
                            )
                            packaging_parents, packaging_settled = (
                                workbook_packaging_lineage(
                                    packaging_events,
                                    durable_decisions=bool(durable_packaging_rows),
                                    prior_events=[
                                        event for event in research_job_service.list_events_with_lineage(
                                            str(research_job.get("job_id") or ""), "workbook_packaged"
                                        )
                                        if str(event.get("job_id") or "") != str(research_job.get("job_id") or "")
                                    ],
                                )
                            )
                        # The basis is a property of the document, its lineage here is a
                        # property of this research: sequences restart per job, so only
                        # the basis read crosses the research boundary (§ 7), while the
                        # replay guard keeps its own job's chronology.
                        document_basis_events: list[dict[str, Any]] = []
                        if research_job_service is not None and attachment_id:
                            document_basis_events = (
                                research_job_service.document_packaging_events(
                                    attachment_id=attachment_id,
                                    source_sha256=str(
                                        getattr(
                                            source_catalog, "source_file_sha256", ""
                                        )
                                        or ""
                                    ),
                                )
                            )
                        if not document_basis_events:
                            # a document nothing has packaged yet reads its own job —
                            # the same answer, one query less of the whole store
                            document_basis_events = list(packaging_events)
                        for packaging_tool in packaging_tools:
                            packaging_parent = (
                                packaging_settled[packaging_tool]
                                if packaging_tool in packaging_settled
                                else packaging_parents.get(packaging_tool)
                            )
                            # § 4: the region, period and book this document was
                            # already priced in are read from its own durable
                            # packaging history, not from the wording of this
                            # reply, so «добери нормы» cannot silently return the
                            # estimate to an unchosen basis.
                            inherited_basis = workbook_document_price_basis(
                                document_basis_events, tool=packaging_tool
                            )
                            # The durable request exists before the first file. An
                            # explicit later price request takes precedence over
                            # an older revision's basis, dimension by dimension.
                            inherited_basis = task_document_price_basis(research_job, inherited_basis)
                            if model_requested_price_basis.get("pricebook_sha256"):
                                inherited_basis.update({key: value for key, value in
                                    document_price_basis_arguments(model_requested_price_basis).items() if value})
                            workbook_call = {
                                "tool": packaging_tool,
                                "args": workbook_packaging_args(
                                    packaging_tool=packaging_tool,
                                    attachment_id=attachment_id,
                                    question=str(req.question or ""),
                                    decisions=(
                                        durable_packaging_rows or model_result_rows
                                    ),
                                    operator_overrides=(
                                        retrieval_trace.get("workbook_research_job") or {}
                                    ).get("operator_overrides"),
                                    draft=packaging_is_draft,
                                    parent_revision_id=packaging_parent,
                                    document_price_basis=inherited_basis,
                                ),
                            }
                            execution_context = {
                                "document_issues": document_issues if packaging_tool == "build_lsr_workbook" else [],
                                "session_id": str(req.session_id or ""),
                                "question": str(req.question or ""),
                                "dataset_ids": [str(item) for item in _dataset_ids],
                                "project_id": getattr(req, "project_id", None),
                                "attachment_id": attachment_id,
                                "profile_revision_id": str(
                                    (profile_snapshot or {}).get("revision_id") or ""
                                ),
                                "model_identity": str(
                                    getattr(
                                        getattr(active_model_result, "connection", None),
                                        "model_id",
                                        "",
                                    )
                                    or llm_model
                                ),
                                "model_preset": execution_preset.preset_id,
                            }
                            try:
                                # One bounded retry is safe here: the workbook tool
                                # is idempotent and resumes the same persisted
                                # checkpoint.  No model or professional decision is
                                # called again.
                                safe_payload, attempt_traces = (
                                    await execute_workbook_with_bounded_retry(
                                        workbook_tool_executor,
                                        workbook_call,
                                        execution_context,
                                        workbook_progress,
                                    )
                                )
                                packaging_trace.extend(attempt_traces)
                                if safe_payload.get("status") == "failed":
                                    packaging_failures.append(dict(safe_payload))
                                    continue
                                harvested = harvest_workbook_tool_result(safe_payload)
                                if not harvested:
                                    continue
                                artifact = (
                                    harvested.get("artifact")
                                    if isinstance(harvested.get("artifact"), dict)
                                    else {}
                                )
                                if (
                                    research_job_service is not None
                                    and research_job is not None
                                    and str(artifact.get("revision_id") or "")
                                ):
                                    try:
                                        research_job_service.record_packaging(
                                            str(research_job["job_id"]),
                                            tool=packaging_tool,
                                            revision_id=str(artifact["revision_id"]),
                                            draft=packaging_is_draft,
                                            # the packager answers with the revision this
                                            # one was really built on, and that answer
                                            # crosses researches: a job-scoped hint is
                                            # empty for the first revision of a new
                                            # research of an already-priced document,
                                            # which left a hole in the durable chain
                                            # (build 822, live B0_camenka revision 2).
                                            parent_revision_id=(
                                                str(artifact.get("parent_revision_id") or "")
                                                or packaging_parent
                                            ),
                                            # the basis belongs to this document as
                                            # much as its revision chain does: the
                                            # next turn inherits it from here (§ 4).
                                            price_basis=harvested.get("price_basis"),
                                        )
                                    except Exception as record_error:  # noqa: BLE001 - lineage hint is best-effort
                                        logger.warning(
                                            "[WORKBOOK] packaging event not recorded: %s",
                                            type(record_error).__name__,
                                        )
                                if artifact.get("download_url"):
                                    kind = str(artifact.get("artifact_kind") or "").strip()
                                    if kind not in {"lsr_workbook", "vor_workbook"}:
                                        kind = (
                                            "vor_workbook"
                                            if packaging_tool == "build_vor_workbook"
                                            else "lsr_workbook"
                                        )
                                    workbook_files.append({
                                        "filename": _chat_workbook_filename(
                                            artifact.get("filename"),
                                            artifact_kind=kind,
                                            tool=packaging_tool,
                                        ),
                                        "download_url": str(artifact["download_url"]),
                                        "artifact_kind": kind,
                                        "draft": "true" if packaging_is_draft else "false",
                                    })
                                if packaging_tool == "build_lsr_workbook" or not workbook_chat_meta:
                                    workbook_chat_meta = harvested
                            except Exception as packaging_error:  # noqa: BLE001 - keep model answer visible
                                logger.exception(
                                    "[WORKBOOK] post-model packaging failed: %s",
                                    type(packaging_error).__name__,
                                )
                                packaging_trace.append({
                                    "tool": packaging_tool,
                                    "attempt": 1,
                                    "status": "error",
                                    "error_type": type(packaging_error).__name__,
                                })
                                packaging_failures.append({
                                    "status": "error",
                                    "code": type(packaging_error).__name__,
                                })
                        if workbook_chat_meta:
                            artifact_meta = workbook_chat_meta.get("artifact")
                            if isinstance(artifact_meta, dict):
                                artifact_meta["draft"] = bool(packaging_is_draft)
                                artifact_meta["draft_rows"] = compact_estimator_draft_rows(
                                    model_result_rows
                                )
                                if workbook_files:
                                    artifact_meta["files"] = workbook_files
                                    artifact_meta.setdefault(
                                        "filename", workbook_files[0]["filename"]
                                    )
                        packaging_warnings = list(model_result_errors or [])
                        packaged_notice = ""
                        job_meta = (
                            retrieval_trace.get("workbook_research_job")
                            if isinstance(retrieval_trace.get("workbook_research_job"), dict)
                            else {}
                        )
                        remaining_locators = list(
                            job_meta.get("remaining_locators")
                            or source_incomplete_locators
                            or []
                        )
                        lsr_readiness = build_lsr_result_readiness(
                            packaged=bool(workbook_files),
                            packaging_failed=bool(packaging_failures) and not workbook_files,
                            packaging_code=str(
                                (packaging_failures[-1] or {}).get("code")
                                if packaging_failures
                                else ""
                            ),
                            document_state=_turn_document_state(
                                research_job_service=research_job_service,
                                research_job=research_job,
                                job_status=str(job_meta.get("status") or ""),
                                workbook_files=workbook_files,
                            ),
                            download_url=next(
                                (
                                    str(item.get("download_url") or "")
                                    for item in reversed(workbook_files)
                                    if str(item.get("download_url") or "").strip()
                                ),
                                "",
                            ),
                            rows=model_result_rows,
                            missing=list(workbook_chat_meta.get("missing") or [])
                            if workbook_chat_meta
                            else [],
                            pricing_status=str(
                                (workbook_chat_meta or {}).get("pricing_status") or ""
                            ),
                            document_issues=list((workbook_chat_meta or {}).get("document_issues") or []),
                            paused=str(job_meta.get("status") or "") == "paused"
                            or "workbook_research_cancelled" in model_result_errors,
                            job_status=str(job_meta.get("status") or ""),
                            remaining_locators=remaining_locators,
                            catalog_work_count=(
                                len(source_catalog.work_locators())
                                if source_catalog is not None
                                else 0
                            ),
                            catalog_locators=(
                                list(source_catalog.work_locators())
                                if source_catalog is not None
                                else []
                            ),
                            price_gaps=list(
                                (workbook_chat_meta or {}).get("price_gaps") or []
                            ),
                            norm_conflicts=list(
                                (workbook_chat_meta or {}).get("norm_conflicts") or []
                            ),
                            price_basis=dict(
                                (workbook_chat_meta or {}).get("price_basis") or {}
                            ),
                            # § 4: the count of calculated positions is read off the
                            # revision's own per-operation projection, never by
                            # subtracting a number of positions from a number of works.
                            row_projection=list(
                                (workbook_chat_meta or {}).get("row_projection") or []
                            ),
                            calculated_positions=(
                                int((safe_payload or {})["calculated_positions"])
                                if isinstance(
                                    (safe_payload or {}).get("calculated_positions"), (int, float)
                                )
                                else -1
                            ),
                            confirmed_amount=(
                                float((safe_payload or {})["confirmed_amount"])
                                if isinstance(
                                    (safe_payload or {}).get("confirmed_amount"), (int, float)
                                )
                                else -1.0
                            ),
                            preliminary_amount=(
                                float((safe_payload or {})["preliminary_amount"])
                                if isinstance(
                                    (safe_payload or {}).get("preliminary_amount"), (int, float)
                                )
                                else -1.0
                            ),
                        )
                        packaged_kind = str(((workbook_chat_meta or {}).get("artifact") or {}).get("artifact_kind") or "lsr_workbook")
                        if packaged_kind == "vor_workbook":
                            lsr_readiness = build_vor_result_readiness(
                                rows=model_result_rows, has_file=bool(workbook_files),
                                remaining_locators=remaining_locators,
                                catalog_work_count=len(source_catalog.work_locators()) if source_catalog else 0,
                                model_errors=[*model_result_errors, *((safe_payload or {}).get("vor_source_errors") or [])],
                            )
                        retrieval_trace["result_readiness"] = lsr_readiness
                        if isinstance(workbook_chat_meta, dict):
                            artifact_meta = workbook_chat_meta.get("artifact")
                            if isinstance(artifact_meta, dict):
                                artifact_meta["result_readiness"] = lsr_readiness
                                artifact_meta["resume"] = {
                                    "job_id": str(job_meta.get("job_id") or ""),
                                    "question": str(req.question or ""),
                                    "attachment_id": attachment_id,
                                    "session_id": str(req.session_id or ""),
                                    "remaining_locators": list(
                                        lsr_readiness.get("remaining_locators") or []
                                    )[:80],
                                    "catalog_work_count": int(
                                        lsr_readiness.get("catalog_work_count") or 0
                                    ),
                                }
                        if workbook_chat_meta:
                            harvested_missing = [
                                str(item)
                                for item in (workbook_chat_meta.get("missing") or [])
                                if str(item).strip()
                            ]
                            harvested_blockers = [
                                str(item)
                                for item in (workbook_chat_meta.get("blockers") or [])
                                if str(item).strip()
                            ]
                            packaged_notice = format_lsr_packaged_notice(
                                filename=(
                                    workbook_files[0]["filename"] if workbook_files else ""
                                ),
                                status=str(workbook_chat_meta.get("workbook_status") or ""),
                                pricing_status=str(
                                    workbook_chat_meta.get("pricing_status") or ""
                                ),
                                norms_status=str(
                                    workbook_chat_meta.get("norms_status") or ""
                                ),
                                missing=harvested_missing,
                                blockers=harvested_blockers,
                                readiness=lsr_readiness,
                                artifact_kind=packaged_kind,
                            )
                            packaging_warnings.extend(harvested_missing)
                            packaging_warnings.extend(harvested_blockers)
                            if packaged_notice and packaged_notice not in answer:
                                answer = f"{answer.rstrip()}\n\n{packaged_notice}"
                                if token_sink is not None:
                                    await token_sink({"event": "reset", "data": ""})
                                    await token_sink({"event": "token", "data": answer})
                        elif packaging_failures:
                            failure = packaging_failures[-1]
                            failure_checkpoint = (
                                failure.get("checkpoint")
                                if isinstance(failure.get("checkpoint"), dict)
                                else {}
                            )
                            checkpoint_id = str(
                                failure_checkpoint.get("checkpoint_id") or ""
                            )
                            checkpoint_bit = (
                                f" Контрольная точка: {checkpoint_id}."
                                if checkpoint_id
                                else ""
                            )
                            packaged_notice = (
                                "ЛСР не создана: техническая ошибка упаковки "
                                f"({str(failure.get('code') or 'WORKBOOK_GENERATION_FAILED')})."
                                f"{checkpoint_bit} Строки решения модели сохранены в истории; "
                                "нормы повторно не пересматриваются."
                            )
                            if packaged_notice not in answer:
                                answer = f"{answer.rstrip()}\n\n{packaged_notice}"
                                if token_sink is not None:
                                    await token_sink({"event": "reset", "data": ""})
                                    await token_sink({"event": "token", "data": answer})
                        retrieval_trace["model_result"] = {
                            "schema": "les_model_rag_result_v1",
                            "status": (str((result_meta or {}).get("status"))
                                       if can_package_saved_draft and (result_meta or {}).get("status") in {"structural_error", "unstructured"}
                                       else "accepted_unchanged"),
                            "row_count": len(model_result_rows),
                            "packaged": bool(workbook_files),
                            "packaging": packaging_trace,
                            "decision_rows": compact_estimator_draft_rows(model_result_rows),
                            "warnings": packaging_warnings,
                            "document_issues": document_issues,
                            "transport_diagnostics": transport_diagnostics,
                            "notice": packaged_notice,
                            "finish_reason": answer_finish_reason,
                        }

                try:
                    from proxy.services.evidence_packet_service import verify_answer_source_labels

                    citation_check = verify_answer_source_labels(answer, answer_source_map)
                    retrieval_trace["citation_check"] = citation_check
                except Exception as citation_error:  # noqa: BLE001
                    retrieval_trace["citation_check"] = {
                        "schema": "les.answer-citation-check.v1",
                        "status": "error",
                        "error": type(citation_error).__name__,
                    }

                t_gen = time.time() - t_gen_start

                if crag_status == "HALLUCINATION":
                    state.crag_stats["hallucination"] += 1
                    state.chat_metrics["crag_fail"] += 1
                elif crag_status == "VERIFIED":
                    state.crag_stats["verified"] += 1
                    state.chat_metrics["crag_pass"] += 1
                elif crag_status == "MODEL_OUTPUT":
                    state.crag_stats["model_output"] = state.crag_stats.get("model_output", 0) + 1
                elif crag_status == "UNVALIDATED":
                    state.crag_stats["unvalidated"] = state.crag_stats.get("unvalidated", 0) + 1
                    state.chat_metrics["crag_fail"] += 1
                else:
                    state.crag_stats["no_data"] += 1
                    state.chat_metrics["crag_fail"] += 1

                state.chat_metrics["latency_search"].append(t_search)
                state.chat_metrics["latency_gen"].append(t_gen)
                state.chat_metrics["tokens"].append(tokens)
                # W0.1: пофазная латентность; overhead = очередь семафора + сборка промпта внутри t_gen
                wall_total = time.time() - t_request_start
                phases = {
                    "pre_retrieval": round(max(0.0, t_search_start - t_request_start), 3),
                    "retrieval": round(t_search, 3),
                    "notebook_study": round(notebook_study_latency, 3),
                    "context": round(t_ctx, 3),
                    "generation": round(t_llm, 3),
                    "validation": round(t_val, 3),
                    "overhead": round(max(0.0, t_gen - t_llm - t_val), 3),
                    "total": round(t_search + notebook_study_latency + t_ctx + t_gen, 3),
                    "wall_total": round(wall_total, 3),
                }
                retrieval_trace["latency_phases"] = phases
                calls_bucket = ensure_actual_model_calls(retrieval_trace)
                finalize_actual_retrieval_emptiness(
                    retrieval_trace,
                    evidence_count=len(model_evidence_chunks or []),
                    searches_executed=int(calls_bucket.get("search_executions") or 0),
                    search_hits=int(calls_bucket.get("search_hits") or 0),
                )
                retrieval_trace["source_map_count"] = len(answer_source_map)
                tool_candidate_counts = []
                for tool_result in tool_results_for_model:
                    tool_trace = (
                        tool_result.get("trace")
                        if isinstance(tool_result, dict)
                        and isinstance(tool_result.get("trace"), dict)
                        else {}
                    )
                    selection = (
                        tool_trace.get("candidate_selection")
                        if isinstance(tool_trace.get("candidate_selection"), dict)
                        else {}
                    )
                    if selection.get("found_count") is not None:
                        tool_candidate_counts.append(int(selection["found_count"]))
                retrieval_selection = (
                    retrieval_trace.get("candidate_selection")
                    if isinstance(retrieval_trace.get("candidate_selection"), dict)
                    else {}
                )
                found_count = (
                    sum(tool_candidate_counts)
                    if tool_candidate_counts
                    else int(
                        retrieval_selection.get("found_count")
                        or len(model_evidence_chunks)
                    )
                )
                source_counts = evidence_counts(
                    answer=answer,
                    source_map=answer_source_map,
                    found_count=found_count,
                )
                retrieval_trace["source_counts"] = source_counts
                retrieval_trace["source_map"] = answer_source_map
                evidence_manifest = build_evidence_manifest(
                    query=str(req.question or ""),
                    scope={
                        "dataset_ids": [str(item) for item in _dataset_ids],
                        "dataset_filter": str(effective_dataset_filter or ""),
                        "model_queries": list(
                            (retrieval_trace.get("tool_loop") or {}).get("model_queries")
                            or []
                        ),
                        "selected_sources_only": bool(
                            getattr(req, "selected_sources_only", False)
                        ),
                    },
                    chunks=model_evidence_chunks,
                    answer=answer,
                )
                retrieval_trace["evidence_manifest"] = evidence_manifest
                state.chat_metrics.setdefault("latency_phases", []).append(phases)
                logger.info("[METRICS] phases=%s", phases)
                for key in ("latency_search", "latency_gen", "tokens", "latency_phases"):
                    state.chat_metrics[key] = state.chat_metrics[key][-100:]

                history_chunks = model_evidence_chunks if model_evidence_chunks else chunks
                sources_list = source_names(history_chunks)
                if project_inventory_prompt:
                    sources_list = [*sources_list, "Опись файлов датасета (MetaDB documents)"]
                source_dataset_ids = _dataset_ids_from_chunks(history_chunks)
                source_dataset_names = _names_for_dataset_ids(source_dataset_ids, dataset_name_by_id)
                source_scope = {
                    "requested": [
                        str(item) for item in (getattr(req, "dataset_ids", None) or _dataset_ids)
                    ],
                    "resolved": [str(item) for item in (_dataset_ids or [])],
                    "used": source_dataset_ids,
                    "used_names": source_dataset_names,
                }
                retrieval_trace["source_scope"] = source_scope
                history_id = None

                try:
                    history_id = save_chat_history(
                        question=req.question,
                        answer=answer,
                        sources=sources_list,
                        crag_status=crag_status,
                        latency_sec=wall_total,
                        tokens=tokens,
                        session_id=req.session_id,
                        requested_dataset_filter=req.dataset_filter,
                        effective_dataset_filter=effective_dataset_filter,
                        resolved_dataset_ids=_dataset_ids,
                        resolved_dataset_names=resolved_dataset_names,
                        source_dataset_ids=source_dataset_ids,
                        source_dataset_names=source_dataset_names,
                        query_route=query_route_payload,
                        retrieval_trace=retrieval_trace,
                        artifact=(workbook_chat_meta.get("artifact") or None),
                        cache_type=cache_marker,
                        validation_enabled=use_validation,
                    )
                except Exception as db_err:
                    logger.warning("[CHAT] History save error: %s", db_err)

                if use_semantic_cache and cache_embedding and cache_scope and crag_status == "VERIFIED":
                    try:
                        cache.store(
                            req.question,
                            cache_scope,
                            cache_embedding,
                            answer,
                            sources_list,
                            crag_status,
                        )
                    except Exception as cache_err:
                        logger.warning("[SEM_CACHE] store skipped: %s", cache_err)
                elif use_semantic_cache and cache_scope and crag_status == "UNVALIDATED":
                    try:
                        cache.store_session_unvalidated(
                            req.question,
                            cache_scope,
                            focused_fingerprint,
                            answer,
                            sources_list,
                            crag_status,
                            req.session_id,
                        )
                    except Exception as cache_err:
                        logger.warning("[SESSION_CACHE] store skipped: %s", cache_err)

                # Numeric provenance гард (Codex §8, пет, flag-only): числа в ответе, которых нет
                # в контексте — возможно не заземлённые. Метим, не блокируем. Сбой → пропуск.
                try:
                    from proxy.services.saferag_service import numeric_provenance_check
                    _num_unverified = numeric_provenance_check(answer, context)
                except Exception:  # noqa: BLE001
                    _num_unverified = []

                response: dict[str, Any] = {
                    "answer": answer,
                    "crag_status": crag_status,
                    "sources": sources_list,
                    "effective_dataset_filter": effective_dataset_filter,
                    "query_route": query_route_payload,
                    "retrieval_trace": retrieval_trace,
                    "cache": cache_marker,
                    "validation": {"enabled": use_validation},
                    "history_id": history_id,
                    "source_excerpts": source_excerpts(history_chunks),
                    "source_map": answer_source_map,
                    "evidence_packet": final_evidence_packet,
                    "latency_phases": phases,
                    "class_suggestions": class_suggestions,
                    "versions": _version_stamp(),
                    "numeric_unverified": _num_unverified,
                    "source_scope": source_scope,
                    "source_counts": source_counts,
                }
                if active_model_result is not None:
                    response["model_connection"] = active_model_result.public_connection_payload()
                    response["model_connection"]["pending_tool_calls"] = active_pending_tool_calls
                if workbook_chat_meta:
                    response.update(workbook_chat_meta)
                if notebook_study_pack is not None:
                    response["notebook_context"] = notebook_study_pack.payload()
                    if notebook_study_artifact:
                        response["artifact"] = {
                            "title": "Инженерный блокнот",
                            "mode": "markdown",
                            "content": notebook_study_artifact,
                        }
                if dataset_memory_prompt:
                    response["dataset_memory"] = {
                        "schema": "dataset_memory_context_v1",
                        "context_role": "navigation",
                        "is_evidence": False,
                    }
                if project_inventory_prompt:
                    response["project_inventory"] = project_inventory_payload or {}
                    if notebook_study_pack is not None and notebook_study_artifact:
                        response["notebook_artifact"] = {
                            "title": "Инженерный блокнот",
                            "mode": "markdown",
                            "content": notebook_study_artifact,
                        }
                if project_inventory_prompt:
                    response["artifact"] = {
                        "title": "Реестр файлов",
                        "mode": "markdown",
                        "content": "```text\n" + (project_inventory_artifact_text or project_inventory_prompt).replace("```", "'''") + "\n```",
                        "project_inventory": project_inventory_payload or {},
                    }

                # W6.7: source_id CAD/BIM-элементов из текста чанков → ответ + снимок
                # подсветки. Вьювер АТЛАС поллит /api/cad-bim/highlight и перекрашивает.
                # The only ordinary-RAG write hook. It runs after a successful
                # response is complete and performs at most a durable queue INSERT.
                try:
                    evidence_sources = list(
                        ((final_evidence_packet.get("evidence") or {}).get("sources") or [])
                    )
                    memory_refs = [
                        {
                            "ref_id": str(item.get("id") or ""),
                            "doc_id": str(item.get("doc_id") or item.get("doc_name") or ""),
                            "locator": json.dumps(
                                item.get("locator") or {}, ensure_ascii=False, sort_keys=True
                            ),
                            "source_revision": str(item.get("source_version") or ""),
                            "is_evidence": bool(item.get("is_evidence")),
                            "snippet_sha256": "",
                        }
                        for item in evidence_sources
                        if isinstance(item, dict) and item.get("is_evidence")
                    ]
                    if not workspace_memory_registered:
                        get_memory_port().enqueue_rag_turn(
                            memory_project_id,
                            {
                                "question": str(req.question or ""),
                                "answer": answer,
                                "crag_status": crag_status,
                                "query_route": query_route_payload,
                                "evidence_refs": memory_refs,
                                "retrieval_fingerprint": focused_fingerprint,
                                "cache_hit": False,
                            },
                        )
                except Exception as memory_error:  # queue pressure cannot fail chat
                    logger.warning("[MEMORY] grounded turn enqueue skipped: %s", memory_error)

                cad_bim_ids, cad_bim_import_id = extract_highlight(
                    getattr(chunk, "content", "") or "" for chunk in chunks
                )
                if cad_bim_ids:
                    response["source_ids"] = cad_bim_ids
                    response["cad_bim"] = {
                        "import_id": cad_bim_import_id,
                        "source_ids": cad_bim_ids,
                    }
                    try:
                        set_highlight(cad_bim_ids, import_id=cad_bim_import_id, question=req.question)
                    except Exception as hl_err:  # подсветка не должна ронять ответ
                        logger.warning("[CHAT] highlight store skipped: %s", hl_err)

                return response

        except HTTPException:
            raise
        except httpx.TimeoutException as e:
            logger.error("[CHAT] LLM TIMEOUT: %s", e)
            raise HTTPException(504, "Истёк таймаут назначенной модели — проверь подключение или повтори запрос.")
        except CloudBudgetStop as e:
            budget_snapshot = getattr(getattr(bound_runner, "transport", None), "cloud_budget_snapshot", None)
            if callable(budget_snapshot):
                retrieval_trace["cloud_token_budget"] = budget_snapshot()
                if token_sink is not None:
                    await token_sink({"event": "cloud_budget", "data": retrieval_trace["cloud_token_budget"]})
            if (research_job_service is not None and research_job is not None
                    and not (research_job.get("status") == "paused" and research_job.get("phase") == "cloud_token_budget")):
                research_job = research_job_service.pause(
                    research_job["job_id"], phase="cloud_token_budget",
                )
            raise ModelExecutionFailure({
                "code": "CLOUD_TURN_TOKEN_BUDGET",
                "message": "Облачный прогон остановлен лимитом расхода. Следующий запрос к модели не отправлен.",
                "job_id": (research_job or {}).get("job_id"),
            }, status_code=429, diagnostics={
                "schema": "les.model-budget-failure.v1",
                "session_id": str(getattr(req, "session_id", "") or ""),
                "cloud_token_budget": retrieval_trace.get("cloud_token_budget", {}),
                "job_id": (research_job or {}).get("job_id"),
            }) from e
        except ModelTransportError as e:
            logger.error("[CHAT] ASSIGNED MODEL ERROR: %s", e)
            raise HTTPException(502, f"Назначенная модель не ответила: {e}")
        except httpx.HTTPStatusError as e:
            detail = f"LLM HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.error("[CHAT] LLM HTTP ERROR: %s", detail)
            raise HTTPException(502, detail)
        except httpx.ConnectError as e:
            logger.error("[CHAT] LLM CONNECT ERROR: %s", e)
            raise HTTPException(503, f"LLM недоступен ({llm_runtime.base_url}) — проверь MLX Host.")
        except Exception as e:
            import traceback

            logger.error("[CHAT] UNEXPECTED ERROR: %s\n%s", e, traceback.format_exc())
            raise HTTPException(500, f"{type(e).__name__}: {e}")



def packet_attempt_seed(
    events: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, ...], int]:
    """Rebuild per-packet attempt counters from durable checkpoint events.

    A restarted process must not number a second delivery of the same packet
    as the first one: the Qx.Hy evidence namespace is keyed by the attempt, so
    resuming from zero would let a fresh reference address another attempt's
    cards.
    """

    seeded: dict[tuple[str, ...], int] = {}
    for event in events or ():
        if not isinstance(event, Mapping):
            continue
        if str(event.get("event_type") or "") != "packet_checkpoint":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        locators = tuple(
            str(item) for item in (payload.get("packet_locators") or []) if str(item)
        )
        if not locators:
            continue
        seeded[locators] = seeded.get(locators, 0) + 1
    return seeded


def packet_offer_counts(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    """How many times each source row was already put to the model.

    Derived only from durable ``packet_checkpoint`` events, which record the
    exact locator set of every packet that was sent.  This is the fairness
    memory of the packet rotation: without it a resumed sheet pass restarts at
    the head of the sheet and rows that sit behind a permanently gapped row are
    never offered.
    """

    counts: dict[str, int] = {}
    for event in events or ():
        if not isinstance(event, Mapping):
            continue
        if str(event.get("event_type") or "") != "packet_checkpoint":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        for item in payload.get("packet_locators") or []:
            locator = str(item).strip()
            if locator:
                counts[locator] = counts.get(locator, 0) + 1
    return counts
