"""Retrieval strategy helpers for chat."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional

from backend.interface import EmbeddingContractError
from backend.rag_config import index_contract_status, query_embedding_instruction_id
from proxy.services.kot_service import analyze_question, extract_norm_refs
from proxy.services.lexical_index_service import LexicalIndex, RetrievalTrace, lexical_enabled, merge_rrf
from proxy.services.query_router import route_query
from proxy.services.retrieval_quality_service import (
    RetrievalQuality,
    evaluate_retrieval_quality,
    expanded_quality_query,
)
from proxy.services.retrieval_candidate_service import (
    collapse_exact_duplicates,
    select_diverse_candidates,
)
from backend.colbert_late_interaction import CircuitBreaker
from proxy.services.rag_advanced_policy_service import (
    colbert_generation_readiness,
    load_policy,
    load_status,
    save_status,
)


CHAT_TOP_K = int(os.getenv("RAG_CHAT_TOP_K", "64"))
RERANK_POOL_K = int(os.getenv("RAG_CHAT_RERANK_POOL_K", "128"))
RERANK_TOP_K = int(os.getenv("RAG_CHAT_RERANK_TOP_K", "64"))
RERANK_CANDIDATE_K = int(
    os.getenv("RAG_CHAT_RERANK_CANDIDATE_K", str(RERANK_TOP_K))
)
_COLBERT_BREAKER = CircuitBreaker()
_RAPTOR_BREAKER = CircuitBreaker()


def _save_advanced_status_safely(payload: dict[str, Any]) -> None:
    try:
        save_status(payload)
    except Exception as exc:  # telemetry must never erase a valid evidence shortlist
        logging.getLogger(__name__).warning("[RAG-STATUS] status persistence skipped: %s", exc)
_SOURCE_EXACT_RE = re.compile(
    r"(?iu)(?:"
    r"[\w./\\:-]+\.(?:md|json|jsonl|dwg|dxf|rvt|rfa|ifc|ifczip|pdf|xlsx?|docx?)"
    r"|[\w./\\:-]*[/\\:_][\w./\\:-]{3,}"
    r"|[a-f0-9]{10,}"
    r"|[a-f0-9]{8}-[a-f0-9-]{8,}"
    r")"
)
_EXACT_IDENTIFIER_RE = re.compile(
    r"(?iu)(?<![\w-])(?=[\w-]{4,}(?![\w-]))(?=[\w-]*\d)(?=[\w-]*[a-zа-яё])"
    r"[\w]+(?:-[\w]+)+(?![\w-])"
)
_SOURCE_NAME_TOKEN_RE = re.compile(r"(?iu)[\wа-яё]{3,}")
_SOURCE_NAME_STOPWORDS = {
    "cad",
    "bim",
    "json",
    "projection",
    "source",
    "import",
    "domain",
    "canonical",
    "format",
    "formats",
    "dxf",
    "dwg",
    "rvt",
    "ifc",
    "md",
    "les",
    "rag",
    "content",
    "users",
    "овс",
    "для",
    "или",
    "как",
    "что",
    "это",
    "где",
    "дай",
    "покажи",
    "план",
}


def required_reranker_policy(requested: Optional[bool] = None) -> tuple[bool, dict[str, Any]]:
    """Resolve the optional reranker from runtime policy, never from a client toggle.

    ``reranker_enabled`` remains accepted by the chat API for backward compatibility,
    but an old UI or API client cannot silently change the server's retrieval path.
    Native RRF is the production ranking contract; reranking is opt-in.
    """
    runtime_enabled = os.getenv("RERANKER_ENABLED", "false").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return runtime_enabled, {
        "enabled": runtime_enabled,
        "reason": "optional_runtime_stage",
        "explicit_override": requested is not None,
        "legacy_request_ignored": requested is not None,
        "legacy_request_value": requested,
    }


_FIRST_ORDINAL_QUERY_RE = re.compile(r"(?iu)(?:\bfirst\b|перв\w*|начал\w*)")
_TABLE_ROW_QUERY_RE = re.compile(r"(?iu)(?:позици\w*|строк\w*|\brows?\b|\bitems?\b)")
_CAD_POSITION_RE = re.compile(r"(?iu)(?:\bposition\s+|\bпозиция\s+)(\d{1,5})")


@dataclass
class RerankedStub:
    content: str
    doc_name: str


@dataclass(frozen=True)
class QueryRoute:
    dataset_filter: Optional[str]
    expanded_query: str
    reason: str


@dataclass
class RetrievalResult:
    chunks: list[Any]
    trace: RetrievalTrace
    kot: Any
    quality: RetrievalQuality

    def payload(self) -> dict[str, Any]:
        trace = self.trace.payload()
        trace["quality"] = self.quality.payload()
        return trace


def _source_exact_terms(question: str) -> list[str]:
    terms: list[str] = []
    for match in _SOURCE_EXACT_RE.findall(question or ""):
        term = match.strip(" \t\r\n\"'`.,;()[]{}<>")
        if len(term) < 6:
            continue
        folded = term.casefold()
        if folded not in terms:
            terms.append(folded)
    return terms[:12]


def _chunk_exact_source_score(chunk: Any, terms: list[str]) -> int:
    if not terms:
        return 0
    meta = getattr(chunk, "meta", {}) or {}
    doc_name = str(getattr(chunk, "doc_name", "") or meta.get("file_name") or meta.get("doc_name") or "")
    doc_haystack = doc_name.casefold()
    content_haystack = str(getattr(chunk, "content", "") or "").casefold()
    score = 0
    for term in terms:
        if term in doc_haystack:
            score += 4
        elif term in content_haystack:
            score += 2
    return score


def _promote_exact_source_matches(chunks: list[Any], question: str) -> tuple[list[Any], list[str]]:
    terms = _source_exact_terms(question)
    if not terms or len(chunks) < 2:
        return chunks, []
    scored = [(_chunk_exact_source_score(chunk, terms), index, chunk) for index, chunk in enumerate(chunks)]
    matched = [term for term in terms if any(_chunk_exact_source_score(chunk, [term]) > 0 for chunk in chunks)]
    if not matched:
        return chunks, []
    ordered = [chunk for _score, _index, chunk in sorted(scored, key=lambda item: (-item[0], item[1]))]
    return ordered, matched


def _exact_identifier_terms(question: str) -> list[str]:
    terms: list[str] = []
    for match in _EXACT_IDENTIFIER_RE.findall(question or ""):
        folded = match.casefold()
        if folded not in terms:
            terms.append(folded)
    return terms[:12]


def _promote_exact_identifier_matches(chunks: list[Any], question: str) -> tuple[list[Any], list[str]]:
    """Keep exact hyphenated designations above semantic neighbours.

    This is format-neutral: the identifier may live in PDF page text, an office
    table or a plain document.  It only reorders candidates already retrieved.
    """
    terms = _exact_identifier_terms(question)
    if not terms or len(chunks) < 2:
        return chunks, []
    scored: list[tuple[int, int, Any]] = []
    matched: set[str] = set()
    for index, chunk in enumerate(chunks):
        meta = getattr(chunk, "meta", {}) or {}
        doc_name = str(getattr(chunk, "doc_name", "") or meta.get("file_name") or "").casefold()
        content = str(getattr(chunk, "content", "") or "").casefold()
        score = 0
        for term in terms:
            if term in doc_name:
                score += 4
                matched.add(term)
            elif term in content:
                score += 3
                matched.add(term)
        scored.append((score, index, chunk))
    if not matched:
        return chunks, []
    ordered = [chunk for _score, _index, chunk in sorted(scored, key=lambda item: (-item[0], item[1]))]
    return ordered, [term for term in terms if term in matched]


def _normalise_norm_reference(value: str) -> str:
    """Canonical comparison key for a user-specified СП/ГОСТ reference."""
    return re.sub(r"[^a-zа-яё0-9]+", "", str(value or "").casefold().replace("ё", "е"))


def _promote_explicit_norm_reference_matches(chunks: list[Any], question: str) -> tuple[list[Any], list[str]]:
    """Keep the named normative document ahead of documents that merely cite it.

    Dense and lexical search legitimately return related documents that mention a
    standard. When the user explicitly names a standard, its own file is the
    target evidence. The rule is generic for extracted norm references, applies
    after reranking too, and never invents a source outside the candidate pool.
    """
    refs = [ref for ref in extract_norm_refs(question) if _normalise_norm_reference(ref)]
    if not refs or len(chunks) < 2:
        return chunks, []

    ref_keys = [_normalise_norm_reference(ref) for ref in refs]
    scored: list[tuple[int, int, Any]] = []
    matched: set[str] = set()
    for index, chunk in enumerate(chunks):
        meta = getattr(chunk, "meta", {}) or {}
        doc_name = str(getattr(chunk, "doc_name", "") or meta.get("file_name") or "")
        doc_key = _normalise_norm_reference(doc_name)
        content_key = _normalise_norm_reference(str(getattr(chunk, "content", "") or ""))
        score = 0
        for ref, ref_key in zip(refs, ref_keys):
            if ref_key in doc_key:
                score += 8
                matched.add(ref)
            elif ref_key in content_key:
                score += 2
                matched.add(ref)
        scored.append((score, index, chunk))
    if not matched:
        return chunks, []
    ordered = [chunk for _score, _index, chunk in sorted(scored, key=lambda item: (-item[0], item[1]))]
    return ordered, sorted(matched)


def _record_exact_norm_refs(trace: RetrievalTrace, refs: list[str]) -> None:
    if not refs:
        return
    if "norm_ref_exact" not in trace.mode:
        trace.mode = f"{trace.mode}+norm_ref_exact"
    for ref in refs:
        if ref not in trace.exact_refs:
            trace.exact_refs.append(ref)


def _source_name_terms(question: str) -> list[str]:
    terms: list[str] = []
    for token in _SOURCE_NAME_TOKEN_RE.findall(question or ""):
        folded = token.casefold().replace("ё", "е")
        if folded in _SOURCE_NAME_STOPWORDS or folded.isdigit():
            continue
        has_cyrillic = any("а" <= ch <= "я" for ch in folded)
        if len(folded) < 4 and not has_cyrillic and not any(ch.isdigit() for ch in folded):
            continue
        if folded not in terms:
            terms.append(folded)
    return terms[:16]


def _source_name_haystack(chunk: Any) -> str:
    meta = getattr(chunk, "meta", {}) or {}
    parts = [
        getattr(chunk, "doc_name", "") or "",
        meta.get("file_name") or "",
        meta.get("doc_name") or "",
        meta.get("source_path") or "",
        str(getattr(chunk, "content", "") or "")[:5000],
    ]
    haystack = " ".join(str(part) for part in parts if part).casefold().replace("ё", "е")
    compact = re.sub(r"(?iu)[\W_]+", "", haystack)
    return f"{haystack} {compact}"


def _chunk_source_name_score(chunk: Any, terms: list[str]) -> int:
    if len(terms) < 2:
        return 0
    haystack = _source_name_haystack(chunk)
    matched = sum(1 for term in terms if term in haystack)
    if matched < 2:
        return 0
    return matched


def _promote_source_name_matches(chunks: list[Any], question: str) -> tuple[list[Any], list[str]]:
    terms = _source_name_terms(question)
    if len(terms) < 2 or len(chunks) < 2:
        return chunks, []
    scored = [(_chunk_source_name_score(chunk, terms), index, chunk) for index, chunk in enumerate(chunks)]
    max_score = max((score for score, _index, _chunk in scored), default=0)
    if max_score < 2:
        return chunks, []
    ordered = [chunk for _score, _index, chunk in sorted(scored, key=lambda item: (-item[0], item[1]))]
    matched = [term for term in terms if any(term in _source_name_haystack(chunk) for chunk in ordered[:3])]
    return ordered, matched[:8]


def _chunk_meta(chunk: Any) -> dict[str, Any]:
    meta = getattr(chunk, "meta", {}) or {}
    if not meta:
        meta = getattr(chunk, "metadata", {}) or {}
    return meta if isinstance(meta, dict) else {}


def _rerank_evidence_text(chunk: Any, question: str, *, limit: int = 1600) -> str:
    """Heading plus a query-centred window, instead of a blind text prefix."""
    meta = _chunk_meta(chunk)
    text = str(getattr(chunk, "content", "") or "")
    heading = str(meta.get("section_heading") or meta.get("parent_heading") or "").strip()
    tokens = [token.casefold() for token in re.findall(r"(?iu)[\wа-яё]{4,}", question or "")]
    folded = text.casefold()
    offsets = [folded.find(token) for token in tokens if folded.find(token) >= 0]
    if offsets and len(text) > limit:
        centre = min(offsets)
        start = max(0, centre - limit // 3)
        end = min(len(text), start + limit)
        window = text[start:end]
        if start:
            window = "…" + window
        if end < len(text):
            window += "…"
    else:
        window = text[:limit] + ("…" if len(text) > limit else "")
    return f"{heading}\n{window}".strip() if heading else window


def _chunk_ordinal(chunk: Any, fallback: int) -> int:
    meta = _chunk_meta(chunk)
    for key in ("chunk_ord", "child_ord", "ordinal"):
        try:
            return int(meta.get(key))
        except (AttributeError, TypeError, ValueError):
            continue
    return fallback


def _first_ordinal_haystack(chunk: Any) -> str:
    meta = _chunk_meta(chunk)
    parts = [
        meta.get("section_heading") or "",
        meta.get("parent_heading") or "",
        str(getattr(chunk, "content", "") or "")[:4000],
    ]
    return " ".join(str(part) for part in parts if part).casefold()


def _first_position_number(text: str) -> int | None:
    values: list[int] = []
    for match in _CAD_POSITION_RE.finditer(text or ""):
        try:
            values.append(int(match.group(1)))
        except (TypeError, ValueError):
            continue
    return min(values) if values else None


def _promote_first_ordinal_chunks(
    chunks: list[Any],
    question: str,
    *,
    doc_filter: list[str] | None = None,
) -> tuple[list[Any], bool]:
    if not doc_filter or len(chunks) < 2:
        return chunks, False
    if not (_FIRST_ORDINAL_QUERY_RE.search(question or "") and _TABLE_ROW_QUERY_RE.search(question or "")):
        return chunks, False
    scored: list[tuple[int, int, int, Any]] = []
    for index, chunk in enumerate(chunks):
        haystack = _first_ordinal_haystack(chunk)
        if "first positions" not in haystack and "первые три позиции" not in haystack:
            continue
        if "position " not in haystack and "позиция " not in haystack:
            continue
        first_position = _first_position_number(haystack)
        position_rank = first_position if first_position is not None else 1_000_000
        scored.append((position_rank, _chunk_ordinal(chunk, index), index, chunk))
    if not scored:
        return chunks, False
    promoted = min(scored, key=lambda item: (item[0], item[1], item[2]))[3]
    try:
        setattr(promoted, "_rank_pin", 1000.0)
        setattr(promoted, "_rank_pin_reason", "first_ordinal_guard")
    except Exception:
        pass
    if chunks[0] is promoted:
        return chunks, False
    ordered = [promoted]
    ordered.extend(chunk for chunk in chunks if chunk is not promoted)
    return ordered, True


def _kot_reason_alias(dataset_filter: str | None, reason: str) -> str:
    aliases = {
        "NTD_FIRE": "fire_safety_keyword",
        "NTD_ELECTRICAL": "electrical_keyword",
        "NTD_STRUCTURAL": "structural_keyword",
        "NTD_SPDS": "spds_keyword",
        "NTD_GEOTECH": "geotech_keyword",
        "NTD_HVAC": "hvac_keyword",
        "NTD_WATER": "water_keyword",
        "GKRF": "gkrf_keyword",
        "TABLE": "table_smeta_keyword",
    }
    return aliases.get(dataset_filter or "", reason)


def classify_query(question: str) -> QueryRoute:
    intent = route_query(question)
    if intent.channel == "table":
        return QueryRoute(intent.dataset_filter or "TABLE", question, intent.reason)
    if intent.channel == "mail":
        return QueryRoute(intent.dataset_filter or "MAIL", question, intent.reason)

    kot = analyze_question(question)
    if kot.dataset_filter:
        return QueryRoute(
            kot.dataset_filter,
            expand_retrieval_query(question),
            _kot_reason_alias(kot.dataset_filter, kot.reason),
        )

    q = question.casefold()
    # Нормализуем разделители, чтобы ловить ПП87 в любом написании: «пп87», «пп 87»,
    # «пп-87», «пп. 87», «пп №87». Иначе «пп87» слитно промахивался мимо «пп 87» и
    # каноничный перечень разделов (через _expand_gkrf_query) не подставлялся.
    q_compact = q.replace(" ", "").replace("-", "").replace(".", "").replace("№", "")
    if (
        "постановлени" in q
        or "пп87" in q_compact
        or "постановление87" in q_compact
        or "градостроительн" in q
        or "гкрф" in q
    ):
        return QueryRoute("GKRF", expand_retrieval_query(question), "gkrf_keyword")
    if any(token in q for token in ("эвакуац", "пожар", "огнестойк", "противодым", "дымоудал", "13130")):
        return QueryRoute("NTD_FIRE", expand_retrieval_query(question), "fire_safety_keyword")
    if any(token in q for token in ("пуэ", "электр", "кабел", "заземл", "молниезащит", "освещен", "напряжен")):
        return QueryRoute("NTD_ELECTRICAL", question, "electrical_keyword")
    if any(token in q for token in ("конструкц", "нагрузк", "фундамент", "основан", "железобетон")):
        return QueryRoute("NTD_STRUCTURAL", question, "structural_keyword")
    if any(token in q for token in ("спдс", "рабочая документац", "проектная документац", "гост 21")):
        return QueryRoute("NTD_SPDS", question, "spds_keyword")
    if any(token in q for token in ("грунт", "геотех", "сейсми", "землетряс", "основания и фундаменты")):
        return QueryRoute("NTD_GEOTECH", question, "geotech_keyword")
    if any(token in q for token in ("дорог", "мост", "тоннел", "железн", "аэродром", "транспорт")):
        return QueryRoute("NTD_TRANSPORT", question, "transport_keyword")
    if any(
        token in q
        for token in (
            "отоп",
            "вентиля",
            "кондицион",
            "теплов",
            "шум",
            "акуст",
            "воздухообмен",
            "расход воздуха",
            "микроклимат",
            "холодопроизвод",
            "сп 60",
            "60.13330",
        )
    ):
        return QueryRoute("NTD_HVAC", expand_retrieval_query(question), "hvac_keyword")
    if any(token in q for token in ("водоснаб", "водоотвед", "канализац", "гидротех", "мелиоратив")):
        return QueryRoute("NTD_WATER", question, "water_keyword")
    if any(token in q for token in ("трубопровод", "газопровод", "нефтепровод", "магистральн")):
        return QueryRoute("NTD_PIPELINES", question, "pipeline_keyword")
    if any(token in q for token in ("жил", "обществен", "градостро", "территор", "доступность", "городская среда")):
        return QueryRoute("NTD_ARCH_URBAN", question, "arch_urban_keyword")
    if any(token in q for token in ("организация строительства", "приемк", "приёмк", "производство работ")):
        return QueryRoute("NTD_CONSTRUCTION", question, "construction_keyword")
    if any(token in q for token in ("bim", "информационное модел", "обследован", "эксплуатац", "мониторинг")):
        return QueryRoute("NTD_BIM_OPERATION", question, "bim_operation_keyword")
    if any(token in q for token in ("ссбт", "охрана труда", "защитные сооружения", "опасн")):
        return QueryRoute("NTD_SAFETY", question, "safety_keyword")
    if any(token in q for token in ("материал", "изоляц", "опалуб", "полы", "покрыт", "стены")):
        return QueryRoute("NTD_MATERIALS", question, "materials_keyword")
    if any(token in q for token in ("смет", "ведомост", "таблиц", "расценк")):
        return QueryRoute("TABLE_SMETA", question, "table_smeta_keyword")
    if any(token in q for token in ("сп ", "норматив", "снип", "гост")):
        return QueryRoute("NTD", question, "generic_normative_keyword")
    return QueryRoute(None, question, "no_route")


def infer_dataset_filter(question: str) -> Optional[str]:
    return classify_query(question).dataset_filter


def expand_retrieval_query(question: str) -> str:
    """Format-agnostic normalization without injected domain prose."""
    normalized = unicodedata.normalize("NFKC", str(question or ""))
    return re.sub(r"\s+", " ", normalized).strip()


def _dataset_name_candidates(dataset_filter: str) -> list[str]:
    normalized = dataset_filter.strip()
    if not normalized:
        return []
    if normalized.endswith("_Index"):
        return [normalized]
    if normalized == "NTD":
        return [
            "NTD_FIRE_Index",
            "NTD_ELECTRICAL_Index",
            "NTD_STRUCTURAL_Index",
            "NTD_GEOTECH_Index",
            "NTD_SPDS_Index",
            "NTD_HVAC_Index",
            "NTD_WATER_Index",
            "NTD_PIPELINES_Index",
            "NTD_TRANSPORT_Index",
            "NTD_ARCH_URBAN_Index",
            "NTD_CONSTRUCTION_Index",
            "NTD_BIM_OPERATION_Index",
            "NTD_SAFETY_Index",
            "NTD_MATERIALS_Index",
            "NTD_GENERAL_Index",
            "NTD_OTHER_Index",
            "NTD_Index",
        ]
    if normalized == "TABLE":
        return [
            "TABLE_SMETA_Index",
            "TABLE_SPEC_Index",
            "TABLE_KS2_Index",
            "TABLE_AOSR_Index",
            "TABLE_TABLE_Index",
        ]
    return [f"{normalized}_Index"]


async def resolve_dataset_ids(
    rag_backend,
    dataset_ids: Optional[list[str]],
    dataset_filter: Optional[str],
    logger: logging.Logger,
    question: str = "",
    *,
    resolution_trace: dict[str, Any] | None = None,
    scope_source: str = "",
) -> Optional[list[str]]:
    def record(status: str, ids: list[str] | None, error_code: str = "") -> None:
        if resolution_trace is None:
            return
        resolution_trace.update(
            {
                "status": status,
                "error_code": error_code,
                "resolved_dataset_ids": list(ids or []),
                "scope_source": scope_source or "unspecified",
            }
        )

    if dataset_ids:
        resolved = [str(dataset_id) for dataset_id in dataset_ids if str(dataset_id).strip()]
        record("ok", resolved)
        return resolved

    effective_filter = dataset_filter
    ds_list = None
    if effective_filter and not dataset_ids:
        try:
            ds_list = await rag_backend.list_datasets()
            exact_matches = [
                dataset for dataset in ds_list
                if str(getattr(dataset, "id", "")) == effective_filter
                or str(getattr(dataset, "name", "")) == effective_filter
            ]
            if exact_matches:
                ids = [dataset.id for dataset in exact_matches]
                logger.info("[CHAT] dataset_filter='%s' exact -> ids=%s", effective_filter, ids)
                record("ok", ids)
                return ids
            candidates = _dataset_name_candidates(effective_filter)
            matches = [dataset for dataset in ds_list if dataset.name in candidates]
            if not matches and effective_filter.startswith("NTD_"):
                # СНАЧАЛА конкретный датасет по ПРЕФИКСУ (NTD_FIRE → NTD_FIRE_Index) — быстро+релевантно
                # (один датасет, малый контекст). Имена в рантайме: NTD_FIRE_Index/GENERAL/CONSTRUCTION/…
                matches = [d for d in ds_list if str(d.name).startswith(effective_filter)]
            if matches:
                ids = [dataset.id for dataset in matches]
                logger.info("[CHAT] dataset_filter='%s' -> ids=%s", effective_filter, ids)
                record("ok", ids)
                return ids
            logger.warning("[CHAT] dataset_filter='%s' не найден → blocked scope", effective_filter)
            record("blocked", [], "dataset_scope_not_found")
            return []
        except Exception as e:
            logger.warning("[CHAT] dataset_filter resolve error: %s", e)
            record("blocked", [], "dataset_catalog_unavailable")
            return []
    if dataset_ids is None and ds_list is None:
        try:
            ds_list = await rag_backend.list_datasets()
            if not ds_list:
                logger.info("[CHAT] no datasets available for retrieval")
                record("blocked", [], "corpus_empty")
                return []
        except Exception as e:
            logger.warning("[CHAT] dataset list error: %s", e)
            record("blocked", [], "dataset_catalog_unavailable")
            return []
    record("ok", dataset_ids)
    return dataset_ids


async def retrieve_chat_chunks(
    *,
    question: str,
    dataset_ids: Optional[list[str]],
    rag_backend,
    reranker_enabled: bool,
    reranker_available: bool,
    reranker_cls,
    mlx_url: str,
    logger: logging.Logger,
    llm_semaphore: Any | None = None,
    return_trace: bool = False,
    doc_filter: Optional[list[str]] = None,
    scope_source: str = "unspecified",
    scope_error_code: str = "",
    result_limit: int | None = None,
    candidate_limit: int | None = None,
    document_diversity_k: int | None = None,
):
    kot = analyze_question(question)
    retrieval_query = expand_retrieval_query(question)
    log_error = getattr(logger, "error", logger.warning)

    def blocked_result(
        error_code: str,
        *,
        detail: str = "",
        embedding_contract: str = "",
    ):
        trace = RetrievalTrace(
            status="blocked",
            error_code=error_code,
            resolved_dataset_ids=list(dataset_ids or []),
            scope_source=scope_source,
            mode="blocked",
            fallback_reason=error_code,
            quality_status="blocked",
            quality_detail=detail or error_code,
            embedding_contract=embedding_contract,
            query_embedding=query_embedding_instruction_id(),
            retrieval_channels=[],
            fusion="none",
        )
        quality = RetrievalQuality("blocked", detail or error_code, 0.0, 0, 0.0, "unknown")
        if return_trace:
            return RetrievalResult([], trace, kot, quality)
        return []

    if dataset_ids == []:
        return blocked_result(
            scope_error_code or "no_datasets",
            detail=scope_error_code or "no_datasets",
        )
    # W2.3 (ADR-3): ранней реранк-ветки больше нет — реранкер работает ПОВЕРХ
    # гибридного пула (vector + lexical → RRF → rerank), а не вместо него.

    # Query wording never changes dataset scope or the profile-owned candidate
    # limit. Structured wording may inform explicitly enabled retrieval layers,
    # but it cannot widen the model-facing search by itself.
    is_structured = any(word in question.casefold() for word in ("перечен", "состав", "список", "разделы", "все разделы", "перечисли"))
    
    bounded_result_limit = max(1, int(result_limit)) if result_limit is not None else None
    bounded_candidate_limit = (
        max(1, int(candidate_limit)) if candidate_limit is not None else None
    )
    if bounded_result_limit is not None and bounded_candidate_limit is not None:
        bounded_candidate_limit = max(bounded_candidate_limit, bounded_result_limit)
    merged_top_k = bounded_candidate_limit or bounded_result_limit or CHAT_TOP_K

    has_refs = bool(extract_norm_refs(question) or extract_norm_refs(retrieval_query))
    pool_k = max(RERANK_POOL_K, merged_top_k * 2) if has_refs or is_structured else RERANK_POOL_K
    effective_doc_filter = list(doc_filter or [])
    _rt: dict[str, float] = {}  # под-фазовый тайминг ретрива (профилирование латентности)
    if hybrid_backend() != "qdrant_native" or not hasattr(rag_backend, "retrieve_native_hybrid"):
        log_error("[RETR] required native RRF backend is unavailable")
        return blocked_result("native_rrf_unavailable")
    _s = time.monotonic()
    try:
        native_method = getattr(
            rag_backend,
            "retrieve_native_hierarchical",
            rag_backend.retrieve_native_hybrid,
        )
        native_chunks = await native_method(
            retrieval_query,
            dataset_ids=dataset_ids,
            top_k=merged_top_k,
            doc_filter=effective_doc_filter or None,
        )
    except EmbeddingContractError as native_contract_error:
        embedding_contract_error = str(native_contract_error)
        log_error("[RETR] native RRF blocked by embedding contract: %s", embedding_contract_error)
        return blocked_result(
            "embedding_contract_mismatch",
            detail="native_rrf_embedding_contract_mismatch",
            embedding_contract=embedding_contract_error,
        )
    except Exception as native_error:  # noqa: BLE001
        log_error("[RETR] native RRF failed closed: %s", native_error)
        return blocked_result(
            "native_rrf_failed",
            detail=f"{type(native_error).__name__}: {native_error}",
        )
    _rt["native"] = round(time.monotonic() - _s, 3)
    trace = RetrievalTrace(
        status="ok",
        resolved_dataset_ids=list(dataset_ids or []),
        scope_source=scope_source,
        mode=(
            "qdrant_native_hierarchical"
            if hasattr(rag_backend, "retrieve_native_hierarchical")
            else "qdrant_native_hybrid"
        ),
        vector_count=len(native_chunks),
        lexical_count=0,
        merged_count=len(native_chunks),
        score_kind="qdrant_rrf",
        retrieval_channels=["dense", "qdrant_sparse"],
        fusion=(
            "global_rrf+descendant_rrf"
            if hasattr(rag_backend, "retrieve_native_hierarchical")
            else "rrf"
        ),
    )
    if effective_doc_filter:
        trace.exact_refs.extend([f"file:{name}" for name in effective_doc_filter])
    chunks = native_chunks
    if bounded_result_limit is None:
        try:
            merged_chunks, merged_trace = _hybrid_merge(
                question,
                native_chunks,
                dataset_ids,
                rag_backend,
                logger,
                retrieval_query=retrieval_query,
                pool_k=pool_k,
                limit=merged_top_k,
                doc_filter=effective_doc_filter or None,
            )
            if merged_trace.lexical_count:
                chunks = merged_chunks
                trace = merged_trace
                trace.status = "ok"
                trace.resolved_dataset_ids = list(dataset_ids or [])
                trace.scope_source = scope_source
                trace.mode = f"qdrant_native_{merged_trace.mode}"
                trace.vector_count = len(native_chunks)
                trace.retrieval_channels = ["dense", "qdrant_sparse", "lexical"]
                trace.fusion = "qdrant_rrf+lexical_safety_rrf"
                if effective_doc_filter:
                    trace.exact_refs.extend([f"file:{name}" for name in effective_doc_filter])
                _rt["native_lexical"] = merged_trace.lexical_count
        except Exception as native_merge_error:  # noqa: BLE001
            logger.warning("[HYBRID] qdrant_native lexical safety merge skipped: %s", native_merge_error)
    logger.info("[RETR] подфазы=%s", _rt)
    trace.query_embedding = query_embedding_instruction_id()
    advanced_policy = load_policy()
    advanced_status = load_status()
    raptor_policy = advanced_policy["raptor"]
    raptor_status = advanced_status["raptor"]
    raptor_mode = str(raptor_policy["mode"])
    raptor_ready = str(raptor_status.get("readiness") or "") == "ready"
    raptor_should_run = (
        raptor_mode != "off"
        and raptor_ready
        and len(chunks) > 0
        and hasattr(rag_backend, "retrieve_raptor_evidence")
        and (
            raptor_mode == "always"
            or is_structured
            or len(question.split()) >= 6
        )
    )
    _RAPTOR_BREAKER.failure_limit = int(raptor_policy["circuit_breaker_failures"])
    _RAPTOR_BREAKER.cooldown_sec = int(raptor_policy["circuit_breaker_cooldown_sec"])
    raptor_chunks: list[Any] = []
    if raptor_should_run and _RAPTOR_BREAKER.allow():
        started = time.monotonic()
        try:
            raptor_chunks = await asyncio.wait_for(
                rag_backend.retrieve_raptor_evidence(
                    retrieval_query,
                    target_collection=str(raptor_status.get("target_collection") or ""),
                    source_collection=str(raptor_status.get("source_collection") or ""),
                    dataset_ids=dataset_ids,
                    doc_filter=effective_doc_filter or None,
                    route_k=int(raptor_policy["route_k"]),
                    top_k=min(
                        merged_top_k,
                        int(raptor_policy["route_k"]) * int(raptor_policy["fanout"]),
                    ),
                ),
                timeout=int(raptor_policy["latency_budget_ms"]) / 1000.0,
            )
            if raptor_chunks:
                from backend.rag_hierarchy import reciprocal_rank_fuse

                chunks = reciprocal_rank_fuse([chunks, raptor_chunks], limit=merged_top_k)
                trace.mode = f"{trace.mode}+raptor"
                trace.fusion = f"{trace.fusion}+raptor_rrf"
            elapsed_ms = round((time.monotonic() - started) * 1000, 2)
            _RAPTOR_BREAKER.success()
            trace.raptor = {
                "status": "applied" if raptor_chunks else "no_routes",
                "mode": raptor_mode,
                "routes_collection": str(raptor_status.get("target_collection") or ""),
                "evidence_count": len(raptor_chunks),
                "latency_ms": elapsed_ms,
            }
            _save_advanced_status_safely(
                {
                    "raptor": {
                        "last_error_code": "",
                        "last_bypass_reason": "",
                        "circuit_state": "closed",
                    },
                    "last_route": {
                        "stages": ["native_rrf", "hierarchy", "raptor"],
                        "latency_ms": {"raptor": elapsed_ms},
                    },
                }
            )
        except Exception as raptor_error:
            _RAPTOR_BREAKER.failure()
            code = (
                "RAPTOR_TIMEOUT"
                if isinstance(raptor_error, TimeoutError)
                else "RAPTOR_RETRIEVAL_FAILED"
            )
            trace.raptor = {
                "status": "bypassed",
                "error_code": code,
                "detail": type(raptor_error).__name__,
            }
            _save_advanced_status_safely(
                {
                    "raptor": {
                        "last_error_code": code,
                        "last_bypass_reason": code,
                        "circuit_state": "open" if not _RAPTOR_BREAKER.allow() else "closed",
                    }
                }
            )
            logger.warning("[RAPTOR] fallback to native hierarchy: %s", raptor_error)
    else:
        raptor_reason = (
            "disabled"
            if raptor_mode == "off"
            else "not_ready"
            if not raptor_ready
            else "circuit_open"
            if not _RAPTOR_BREAKER.allow()
            else "adaptive_bypass"
            if raptor_mode == "adaptive"
            else "backend_unavailable"
        )
        trace.raptor = {
            "status": "bypassed",
            "reason": raptor_reason,
            "mode": raptor_mode,
        }
    chunks, exact_terms = _promote_exact_source_matches(chunks, question)
    if exact_terms:
        if "source_exact" not in trace.mode:
            trace.mode = f"{trace.mode}+source_exact"
        for term in exact_terms:
            ref = f"source:{term}"
            if ref not in trace.exact_refs:
                trace.exact_refs.append(ref)
    chunks, exact_identifiers = _promote_exact_identifier_matches(chunks, question)
    if exact_identifiers:
        if "identifier_exact" not in trace.mode:
            trace.mode = f"{trace.mode}+identifier_exact"
        for term in exact_identifiers:
            ref = f"identifier:{term}"
            if ref not in trace.exact_refs:
                trace.exact_refs.append(ref)
    chunks, exact_norm_refs = _promote_explicit_norm_reference_matches(chunks, question)
    _record_exact_norm_refs(trace, exact_norm_refs)
    if not exact_terms and not exact_norm_refs and any(token in question.casefold() for token in ("cad", "bim", "dwg", "dxf", "rvt", "ifc", "атм", "гсв")):
        chunks, source_name_terms = _promote_source_name_matches(chunks, question)
        if source_name_terms and "source_name_boost" not in trace.mode:
            trace.mode = f"{trace.mode}+source_name_boost"
    # ADR-12 (Ц9): подъём ТАБЛИЧНЫХ ПРИЛОЖЕНИЙ норм. Если узлы-документы известны
    # (doc_filter из стадии-1) и запрос «табличный» (перечень/приложение/категория
    # помещений) — аддитивно подмешиваем pipe-table чанки ЭТИХ узлов в пул, чтобы
    # реранк поднял приложение (эмбеддинг строки таблицы ≠ запрос → плоско тонет).
    # Пусто/нет интента/нет узлов → no-op, плоский пул нетронут.
    table_appendix_chunks: list[Any] = []
    if effective_doc_filter:
        try:
            from proxy.services.table_appendix_service import (
                fetch_table_appendix_chunks,
                merge_table_appendix,
            )
            table_appendix_chunks = await fetch_table_appendix_chunks(
                question=question, retrieval_query=retrieval_query,
                doc_filter=effective_doc_filter, dataset_ids=dataset_ids,
                rag_backend=rag_backend, logger=logger,
            )
            if table_appendix_chunks:
                before = len(chunks)
                chunks = merge_table_appendix(chunks, table_appendix_chunks)
                if len(chunks) != before:
                    trace.mode = f"{trace.mode}+table_appendix"
        except Exception as _tbl_err:  # noqa: BLE001 — best-effort, флат не страдает
            logger.warning("[TABLE_APPENDIX] fallback на плоский пул: %s", _tbl_err)
    # NB: hot-path дедуп по content_hash снят — измерено 0.7% дублей / 3 кросс-кластера на 6000
    # (tools/ingestion_quality_report). Кросс-датасетные дубли — задача ingestion QA, не рантайма.
    if bounded_candidate_limit is not None:
        collapsed = collapse_exact_duplicates(chunks)
        chunks = select_diverse_candidates(
            collapsed,
            per_document_k=document_diversity_k or len(collapsed) or 1,
            limit=bounded_candidate_limit,
        )
    quality = evaluate_retrieval_quality(question=question, chunks=chunks, trace=trace, kot=kot)

    if return_trace and quality.status == "weak":
        retry_query = expanded_quality_query(question, kot)
        retry_top_k = (
            merged_top_k
            if bounded_result_limit is not None
            else max(pool_k, merged_top_k)
        )
        if retry_top_k > merged_top_k:
            try:
                retry_native = await rag_backend.retrieve_native_hybrid(
                    retry_query,
                    dataset_ids=dataset_ids,
                    top_k=retry_top_k,
                    doc_filter=effective_doc_filter or None,
                )
                retry_chunks, retry_trace = _hybrid_merge(
                    question,
                    retry_native,
                    dataset_ids,
                    rag_backend,
                    logger,
                    retrieval_query=retry_query,
                    pool_k=pool_k,
                    limit=retry_top_k,
                    doc_filter=effective_doc_filter or None,
                )
                retry_trace.mode = (
                    f"qdrant_native_{retry_trace.mode}"
                    if retry_trace.lexical_count
                    else "qdrant_native_hybrid"
                )
                retry_trace.vector_count = len(retry_native)
                retry_trace.score_kind = "rrf" if retry_trace.lexical_count else "qdrant_rrf"
                retry_trace.retrieval_channels = (
                    ["dense", "qdrant_sparse", "lexical"]
                    if retry_trace.lexical_count
                    else ["dense", "qdrant_sparse"]
                )
                retry_trace.fusion = (
                    "qdrant_rrf+lexical_safety_rrf"
                    if retry_trace.lexical_count
                    else "rrf"
                )
                retry_trace.status = "ok"
                retry_trace.resolved_dataset_ids = list(dataset_ids or [])
                retry_trace.scope_source = scope_source
                if effective_doc_filter:
                    retry_trace.exact_refs.extend(
                        f"file:{name}"
                        for name in effective_doc_filter
                        if f"file:{name}" not in retry_trace.exact_refs
                    )
                retry_trace.retry_count = 1
                retry_trace.retry = {
                    "reason": quality.detail,
                    "query_changed": retry_query != retrieval_query,
                    "backend_preserved": True,
                    "mode_before": trace.mode,
                    "mode_after": retry_trace.mode,
                    "top_k_before": merged_top_k,
                    "top_k_after": retry_top_k,
                }
                if trace.raptor.get("status") == "applied" and raptor_chunks:
                    from backend.rag_hierarchy import reciprocal_rank_fuse

                    retry_chunks = reciprocal_rank_fuse(
                        [retry_chunks, raptor_chunks],
                        limit=retry_top_k,
                    )
                    retry_trace.raptor = dict(trace.raptor)
                    retry_trace.mode = f"{retry_trace.mode}+raptor"
                    retry_trace.fusion = f"{retry_trace.fusion}+raptor_rrf"
                retry_quality = evaluate_retrieval_quality(
                    question=question,
                    chunks=retry_chunks,
                    trace=retry_trace,
                    kot=kot,
                )
                if retry_quality.status != "weak" or len(retry_chunks) >= len(chunks):
                    chunks, trace, quality = retry_chunks, retry_trace, retry_quality
            except Exception as retry_error:  # noqa: BLE001
                logger.warning("[RETR] weak-query native retry skipped: %s", retry_error)
                trace.retry = {
                    "status": "error",
                    "reason": quality.detail,
                    "query_changed": False,
                    "error": type(retry_error).__name__,
                }

    if bounded_candidate_limit is not None:
        collapsed = collapse_exact_duplicates(chunks)
        chunks = select_diverse_candidates(
            collapsed,
            per_document_k=document_diversity_k or len(collapsed) or 1,
            limit=bounded_candidate_limit,
        )

    # Late interaction sits strictly between RRF/hierarchy and cross-encoder.
    # It is evidence-only and fail-soft: a missing optional vector never erases
    # the already valid native-RRF shortlist.
    colbert_policy = advanced_policy["colbert"]
    colbert_mode = str(colbert_policy["mode"])
    colbert_readiness = colbert_generation_readiness(
        advanced_policy,
        advanced_status["colbert"],
        index_contract_status(),
    )
    exact_early_exit = bool(advanced_policy["execution"]["exact_early_exit"])
    colbert_should_run = (
        colbert_readiness["ready"]
        and len(chunks) > 1
        and hasattr(rag_backend, "rerank_colbert")
        and not (colbert_mode == "adaptive" and exact_early_exit and (exact_terms or exact_norm_refs))
    )
    _COLBERT_BREAKER.failure_limit = int(colbert_policy["circuit_breaker_failures"])
    _COLBERT_BREAKER.cooldown_sec = int(colbert_policy["circuit_breaker_cooldown_sec"])
    if colbert_should_run and _COLBERT_BREAKER.allow():
        started = time.monotonic()
        candidate_count = min(int(colbert_policy["candidate_k"]), len(chunks))
        try:
            ranked_head = await asyncio.wait_for(
                rag_backend.rerank_colbert(
                    retrieval_query,
                    chunks[:candidate_count],
                    top_k=min(int(colbert_policy["output_k"]), candidate_count),
                    max_query_tokens=int(colbert_policy["max_query_tokens"]),
                ),
                timeout=int(colbert_policy["latency_budget_ms"]) / 1000.0,
            )
            chunks = ranked_head + chunks[candidate_count:]
            elapsed_ms = round((time.monotonic() - started) * 1000, 2)
            _COLBERT_BREAKER.success()
            trace.colbert = {
                "status": "applied", "mode": colbert_mode,
                "model": colbert_policy["model"], "input_count": candidate_count,
                "latency_ms": elapsed_ms,
            }
            _save_advanced_status_safely({
                "colbert": {"readiness": "ready", "last_error_code": "", "last_bypass_reason": "", "circuit_state": "closed"},
                "last_route": {"stages": ["native_rrf", "hierarchy", "colbert"], "latency_ms": {"colbert": elapsed_ms}},
            })
        except Exception as colbert_error:  # optional stage keeps the proven RRF order
            _COLBERT_BREAKER.failure()
            code = "COLBERT_TIMEOUT" if isinstance(colbert_error, TimeoutError) else "COLBERT_RERANK_FAILED"
            trace.colbert = {"status": "bypassed", "error_code": code, "detail": type(colbert_error).__name__}
            _save_advanced_status_safely({"colbert": {
                "readiness": "degraded", "last_error_code": code,
                "last_bypass_reason": code,
                "circuit_state": "open" if not _COLBERT_BREAKER.allow() else "closed",
            }})
            logger.warning("[COLBERT] fallback to native RRF order: %s", colbert_error)
    else:
        reason = (
            str(colbert_readiness["reason"]) if not colbert_readiness["ready"] else
            "exact_early_exit" if exact_early_exit and (exact_terms or exact_norm_refs) else
            "circuit_open" if not _COLBERT_BREAKER.allow() else
            "backend_unavailable"
        )
        trace.colbert = {"status": "bypassed", "reason": reason, "mode": colbert_mode}

    # W2.3: cross-encoder реранк гибридного пула — переупорядочивает, не режет
    # (downstream-фокусировка сама сузит). Сопоставление по индексу через
    # metadata._idx (не по тексту). Сбой → исходный гибридный порядок.
    if len(chunks) > 1 and (not reranker_enabled or not reranker_available or reranker_cls is None):
        bypass_reason = "disabled" if not reranker_enabled else "unavailable"
        trace.rerank = {
            "status": "bypassed",
            "reason": bypass_reason,
            "preserved_order": "native_rrf",
        }
        logger.info(
            "[RERANKER] bypassed (%s); preserving native RRF order",
            bypass_reason,
        )
    if reranker_available and reranker_enabled and len(chunks) > 1:
        try:
            reranker = reranker_cls(mlx_url=mlx_url, mode="batch")
            # Native RRF may keep a wide pool for recall (up to 256 technical
            # fragments). A local CPU cross-encoder must receive a bounded
            # shortlist, otherwise one broad project question can occupy it
            # for minutes. The untouched RRF tail remains available below.
            rerank_candidate_count = min(
                max(RERANK_CANDIDATE_K, 1),
                len(chunks),
            )
            rerank_candidates = chunks[:rerank_candidate_count]
            rerank_input = [
                {
                    "text": _rerank_evidence_text(chunk, question),
                    "metadata": {"doc_name": chunk.doc_name, "_idx": idx},
                    "score": getattr(chunk, "score", 0.0),
                }
                for idx, chunk in enumerate(rerank_candidates)
            ]
            # Семафор нужен только LLM-реранкеру (держит Metal); cross-encoder — нет.
            needs_semaphore = llm_semaphore is not None and reranker_cls.__name__ == "Reranker"
            if needs_semaphore:
                async with llm_semaphore:
                    ranked = await reranker.rerank(
                        question,
                        rerank_input,
                        top_k=min(max(RERANK_TOP_K, 1), len(rerank_input)),
                    )
            else:
                ranked = await reranker.rerank(
                    question,
                    rerank_input,
                    top_k=min(max(RERANK_TOP_K, 1), len(rerank_input)),
                )
            reordered = []
            seen = set()
            rerank_items: list[dict[str, Any]] = []
            for ranked_chunk in ranked:
                idx = ranked_chunk.metadata.get("_idx")
                if isinstance(idx, int) and 0 <= idx < len(chunks) and idx not in seen:
                    seen.add(idx)
                    original = chunks[idx]
                    meta = _chunk_meta(original)
                    meta["rerank_original_rank"] = idx + 1
                    meta["rerank_rank"] = len(reordered) + 1
                    rerank_score = float(getattr(ranked_chunk, "score", 0.0) or 0.0)
                    meta["rerank_score"] = rerank_score
                    meta["rerank_model"] = reranker_cls.__name__
                    reordered.append(original)
                    rerank_items.append(
                        {
                            "doc_name": str(getattr(original, "doc_name", "")),
                            "original_rank": idx + 1,
                            "rank": len(reordered),
                            "score": rerank_score,
                        }
                    )
            for idx, chunk in enumerate(chunks):  # хвост, не вернувшийся из реранка
                if idx not in seen:
                    reordered.append(chunk)
            chunks = reordered
            chunks, exact_terms = _promote_exact_source_matches(chunks, question)
            if exact_terms and "source_exact_guard" not in trace.mode:
                trace.mode = f"{trace.mode}+source_exact_guard"
            chunks, exact_identifiers = _promote_exact_identifier_matches(chunks, question)
            if exact_identifiers:
                if "identifier_exact_guard" not in trace.mode:
                    trace.mode = f"{trace.mode}+identifier_exact_guard"
                for term in exact_identifiers:
                    ref = f"identifier:{term}"
                    if ref not in trace.exact_refs:
                        trace.exact_refs.append(ref)
            chunks, exact_norm_refs = _promote_explicit_norm_reference_matches(chunks, question)
            _record_exact_norm_refs(trace, exact_norm_refs)
            if not exact_terms and not exact_norm_refs and any(token in question.casefold() for token in ("cad", "bim", "dwg", "dxf", "rvt", "ifc", "атм", "гсв")):
                chunks, source_name_terms = _promote_source_name_matches(chunks, question)
                if source_name_terms and "source_name_boost" not in trace.mode:
                    trace.mode = f"{trace.mode}+source_name_boost"
            trace.mode = f"{trace.mode}+rerank"
            trace.rerank = {
                "status": "applied",
                "model": reranker_cls.__name__,
                "pool_count": len(chunks),
                "candidate_limit": max(RERANK_CANDIDATE_K, 1),
                "input_count": len(rerank_input),
                "returned_count": len(ranked),
                "items": rerank_items,
            }
            trace.score_kind = "rerank_logit"
            logger.info("[RERANK-CE] гибридный пул %s переупорядочен", len(chunks))
        except Exception as rerank_error:
            log_error("[RERANKER] required rerank failed closed: %s", rerank_error)
            return blocked_result(
                "reranker_failed",
                detail=f"{type(rerank_error).__name__}: {rerank_error}",
            )

    # ADR-12 (Ц9): после реранка гарантируем табличным приложениям места в видимом
    # окне ответа — иначе cross-encoder топит сырой текст таблицы под прозой и
    # приложение не доезжает. Аддитивно: без подмешанных таблиц — no-op.
    if table_appendix_chunks:
        try:
            from proxy.services.table_appendix_service import guarantee_table_appendix
            # Окно гарантии — ВИДИМЫЙ срез ответа (CHAT_TOP_K), а не весь пул:
            # пользователь читает первые CHAT_TOP_K, под ними приложение бесполезно.
            promoted = guarantee_table_appendix(chunks, table_appendix_chunks, window=CHAT_TOP_K)
            if promoted is not chunks and [id(c) for c in promoted] != [id(c) for c in chunks]:
                chunks = promoted
                if "table_appendix_guarantee" not in trace.mode:
                    trace.mode = f"{trace.mode}+table_appendix_guarantee"
        except Exception as _g_err:  # noqa: BLE001 — best-effort
            logger.warning("[TABLE_APPENDIX] guarantee fallback: %s", _g_err)

    chunks, ordinal_promoted = _promote_first_ordinal_chunks(
        chunks,
        question,
        doc_filter=effective_doc_filter or None,
    )
    if ordinal_promoted and "first_ordinal_guard" not in trace.mode:
        trace.mode = f"{trace.mode}+first_ordinal_guard"

    # Parent-card hydration: search_chunk → sibling window under the same parent_id.
    # Does not select a professional answer; only attaches typed meta.parent_card.
    try:
        from proxy.services.parent_card_hydration_service import hydrate_parent_cards

        hydration = hydrate_parent_cards(chunks, max_chunks=min(8, max(1, CHAT_TOP_K)))
        chunks = hydration.chunks
        trace.parent_hydration = hydration.payload()
        if hydration.hydrated_count and "parent_card" not in trace.mode:
            trace.mode = f"{trace.mode}+parent_card"
    except Exception as hydrate_error:  # noqa: BLE001 — best-effort, never fail retrieval
        logger.warning("[PARENT_CARD] hydration skipped: %s", hydrate_error)
        trace.parent_hydration = {
            "schema": "les.parent_card.v1",
            "hydrated_count": 0,
            "error": type(hydrate_error).__name__,
        }

    # A weak-query retry may replace the trace; record the actual query contract
    # only after every dense pass has completed.
    collapsed_chunks = collapse_exact_duplicates(chunks)
    found_count = len(collapsed_chunks)
    if bounded_result_limit is not None:
        chunks = select_diverse_candidates(
            collapsed_chunks,
            per_document_k=document_diversity_k or found_count or 1,
            limit=bounded_result_limit,
        )
        trace.candidate_selection = {
            "requested_candidate_k": merged_top_k,
            "found_count": found_count,
            "document_diversity_k": document_diversity_k or found_count or 1,
            "model_visible_count": len(chunks),
        }
    quality = evaluate_retrieval_quality(question=question, chunks=chunks, trace=trace, kot=kot)
    trace.query_embedding = query_embedding_instruction_id()
    trace.quality_status = quality.status
    trace.quality_detail = quality.detail
    trace.status = "ok" if quality.status == "good" else "degraded"
    trace.resolved_dataset_ids = list(dataset_ids or [])
    trace.scope_source = scope_source
    if return_trace:
        return RetrievalResult(chunks, trace, kot, quality)
    return chunks


def hybrid_backend() -> str:
    """There is one production retrieval architecture."""
    return "qdrant_native"


def _lexical_status_usable(status: dict[str, Any]) -> tuple[bool, str]:
    if not status.get("ready"):
        return False, "not_ready"
    if not status.get("stale"):
        return True, "ready"
    try:
        point_count = int(status.get("point_count") or 0)
        chunks = int(status.get("chunks") or 0)
    except (TypeError, ValueError):
        return False, "stale_unknown_count"
    if point_count <= 0:
        return False, "stale_unknown_point_count"
    missing_ratio = max(point_count - chunks, 0) / max(point_count, 1)
    tolerance = float(os.getenv("RAG_LEXICAL_STALE_TOLERANCE", "0.02") or "0.02")
    if missing_ratio <= max(tolerance, 0.0):
        return True, f"minor_stale:{missing_ratio:.6f}"
    return False, f"stale:{missing_ratio:.6f}"


def _hybrid_merge(
    question: str,
    vector_chunks: list[Any],
    dataset_ids: Optional[list[str]],
    rag_backend,
    logger: logging.Logger,
    *,
    retrieval_query: str = "",
    pool_k: int = RERANK_POOL_K,
    limit: int = CHAT_TOP_K,
    doc_filter: Optional[list[str]] = None,
) -> tuple[list[Any], RetrievalTrace]:
    if not lexical_enabled():
        trace = RetrievalTrace(
            mode="vector",
            vector_count=len(vector_chunks),
            lexical_count=0,
            merged_count=len(vector_chunks),
            fallback_reason="hybrid_disabled",
        )
        return vector_chunks[:limit], trace

    collection = getattr(rag_backend, "collection_name", "")
    if not collection:
        trace = RetrievalTrace(
            mode="vector",
            vector_count=len(vector_chunks),
            lexical_count=0,
            merged_count=len(vector_chunks),
            fallback_reason="missing_collection_name",
        )
        return vector_chunks[:limit], trace
    lexical_chunks: list[Any] = []
    try:
        index = LexicalIndex()
        status = index.status(collection)
        lexical_usable, lexical_reason = _lexical_status_usable(status)
        if lexical_usable:
            if status.get("stale"):
                logger.info("[HYBRID] lexical minor drift allowed for %s: %s %s", collection, lexical_reason, status)
            lexical_chunks = index.search(
                retrieval_query or question,
                collection=collection,
                dataset_ids=dataset_ids,
                doc_filter=doc_filter,
                limit=pool_k,
            )
        elif status.get("stale"):
            logger.info("[HYBRID] lexical index stale for %s: %s %s", collection, lexical_reason, status)
    except Exception as error:
        logger.warning("[HYBRID] lexical fallback: %s", error)
    merged, trace = merge_rrf(vector_chunks, lexical_chunks, question=retrieval_query or question, limit=limit)
    if not lexical_chunks and not trace.fallback_reason:
        trace.fallback_reason = "lexical_index_empty_or_unavailable"
    return merged, trace
