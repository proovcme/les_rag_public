"""Closed-status LSR quality gate: model judges, code only keeps states honest.

The first model table never prices a row. A later blind-review packet of the
same model may mark EXACT_VERIFIED. Free-text coverage stays explanatory.
Code does not choose a replacement norm and does not match montage vs dismantling.
Verifier CONFLICT/MISSING reject the cipher and reopen model-authored search.
If the model already named a cipher, code may read that exact card from the
readonly catalog when the RAG window omitted it. That is not a replacement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from proxy.services.model_answer_table_service import (
    is_divider_cell,
    opens_as_table,
    table_cells,
)
from proxy.services.model_lsr_result_contract import (
    MATCH_FIELDS,
    model_lsr_result_field_instruction,
)


QUALITY_GATE_SCHEMA = "les.lsr-norm-quality-gate.v1"
MAX_RESEARCH_ROUNDS_PER_LOCATOR = 3
ANALOGUES_IN_MONEY_DEFAULT = False
VERIFIER_PACKET_SIZE = 5

FIRST_PASS_STATUSES = frozenset(
    {
        "EXACT",
        "ANALOGUE_CANDIDATE",
        "NEEDS_RESEARCH",
        "MISSING",
        "CONFLICT",
        "UNVERIFIED",
    }
)
VERIFIER_STATUSES = frozenset(
    {
        "EXACT_VERIFIED",
        "ANALOGUE_VERIFIED",
        "NEEDS_RESEARCH",
        "MISSING",
        "CONFLICT",
    }
)
#: What each match fact asks, in the operator's words.  Task 2026-09-29 § 4: the
#: «Ограничения аналога» column of the delivered file names the facts an analogue row
#: left unanswered instead of printing an empty cell — the column had no wording of its
#: own, so nothing could fill it.
MATCH_FIELD_LABELS = {
    "action_match": "совпадает ли действие (монтаж/разборка/устранение)",
    "object_match": "тот ли объект или конструкция",
    "condition_match": "те ли условия производства",
    "unit_compatible": "совместима ли единица измерения",
    "composition_covers": "покрывает ли состав нормы эту работу",
}
SELF_SCORE_FIELDS = ("coverage", "analogue", "note", "norm_status", "verdict")

# Task 2026-09-29 § 3: a row the model leaves not-ready is not one kind of hole.
# Which kind it is decides *who* answers next: the normative base (a cipher that is
# not in it), the model's own citation (a шифр its referenced cards never showed),
# the analogue's match facts (an unsubstantiated analogue), the source document
# (the row does not carry enough to choose) or the estimate engineer (the cards
# were read and none fits).  The first three are structural facts the code can read
# off evidence it already holds, so they stay code-derived.  Only the last two are
# things the model knows from inside its own answer, and those two are what a model
# may declare below — never a verdict, never a cipher, just the reason an open row is
# open.  An undeclared reason stays the plain open status it was before; the code
# does not guess a cause it was not given, and it never raises a verdict from one.
MODEL_GAP_REASONS = frozenset({"insufficient_source_data", "no_suitable_candidate"})
GAP_REASON_FIELD = "gap_reason"
_GAP_REASON_ALIASES = {
    "insufficient_source_data": "insufficient_source_data",
    "insufficient source data": "insufficient_source_data",
    "недостаточные исходные сведения": "insufficient_source_data",
    "недостаточно исходных данных": "insufficient_source_data",
    "нет исходных данных": "insufficient_source_data",
    "no_suitable_candidate": "no_suitable_candidate",
    "no suitable candidate": "no_suitable_candidate",
    "нет подходящего кандидата": "no_suitable_candidate",
    "нет подходящей нормы": "no_suitable_candidate",
    "подходящая норма не найдена": "no_suitable_candidate",
}


def normalize_gap_reason(value: Any) -> str:
    """Closed model-declarable reason for an open row; anything else stays unspoken.

    Exact-cell equality, the same rule ``canonicalize_norm_status`` follows: the
    aliases exist because a live answer writes this column in Russian, not because
    prose may be classified.  A sentence is not a reason token — the model's own
    words belong in ``open_gap`` and are shown verbatim, while the token says which
    professional question the row raises.
    """

    marker = _fold(value)
    if not marker:
        return ""
    return _GAP_REASON_ALIASES.get(marker, "")


def gap_reason_of(row: Mapping[str, Any] | None) -> str:
    """The declared reason on a durable row, canonicalised, or ``""``."""

    payload = row if isinstance(row, Mapping) else {}
    return normalize_gap_reason(payload.get(GAP_REASON_FIELD))


_STATUS_ALIASES = {
    "exact": "EXACT",
    "точная": "EXACT",
    "точно": "EXACT",
    "analogue_candidate": "ANALOGUE_CANDIDATE",
    "analogue": "ANALOGUE_CANDIDATE",
    "analog": "ANALOGUE_CANDIDATE",
    "аналог": "ANALOGUE_CANDIDATE",
    "needs_research": "NEEDS_RESEARCH",
    "уточнить": "NEEDS_RESEARCH",
    "research": "NEEDS_RESEARCH",
    "missing": "MISSING",
    "нет": "MISSING",
    "н/д": "MISSING",
    "n/a": "MISSING",
    "na": "MISSING",
    "conflict": "CONFLICT",
    "конфликт": "CONFLICT",
    "exact_verified": "EXACT_VERIFIED",
    "analogue_verified": "ANALOGUE_VERIFIED",
    "unverified": "UNVERIFIED",
}
_YES = {"yes", "true", "1", "совпало", "совпадает", "да"}
_NO = {"no", "false", "0", "не совпало", "нет"}
_UNKNOWN = {"unknown", "неясно", "н/д", "n/a", "na", "—", "-", "–", "−"}
_ABSENCE = {"", "—", "-", "–", "−", "нет", "н/д", "n/a", "na", "none"}

RESEARCH_STRATEGY_HINTS = (
    "Точное название работы без бренда и артикула.",
    "Действие + объект + способ выполнения.",
    "Родительская операция и сборник.",
    "Синонимы объекта.",
    "Отдельный поиск по действию этой строки: демонтаж, монтаж, ремонт или замена. Формулировку выбираешь ты.",
    "Поиск по измерителю и ключевому составу работ.",
    "Опирайся на полные карточки ближайших кандидатов, не повторяй прежний запрос.",
    "Сравни несколько кандидатов в одном ответе; не бери первый попавшийся шифр.",
)

_QUALITY_LOCATOR_PREFIX = re.compile(
    r"^(?:строка|source[_ ]?row|row)(?:\s*№)?\s*[=:]?\s*",
    flags=re.IGNORECASE,
)
_STORE_CODE_RE = re.compile(
    r"^(?P<family>[A-Za-zА-Яа-яЁё]+)(?::)?(?P<bare>\d{2}-\d{2}-\d{3}-\d{2})$"
)


def normalize_quality_locator(value: Any) -> str:
    """Keep the authored locator. Strip only the 'Строка' prefix the prompt taught."""

    text = str(value or "").strip().strip("`*")
    if not text:
        return ""
    stripped = _QUALITY_LOCATOR_PREFIX.sub("", text, count=1).strip()
    if stripped.startswith("#") and stripped[1:].strip():
        stripped = stripped[1:].strip()
    return stripped or text


_QUALITY_HEADER_FIELDS = {
    "source_row": "source_row",
    "№": "source_row",
    "№ п/п": "source_row",
    "№ пп": "source_row",
    "locator": "source_row",
    "строка": "source_row",
    "title": "title",
    "наименование": "title",
    "unit": "unit",
    "ед. изм.": "unit",
    "ед. изм": "unit",
    "norm_code": "norm_code",
    "шифр нормы": "norm_code",
    "шифр": "norm_code",
    "verdict": "norm_status",
    "вердикт": "norm_status",
    "norm_status": "norm_status",
    "статус нормы": "norm_status",
    # § 3: the reason an open row is open has to survive the table, so the column
    # the prompt announces must be a header the reader maps.
    "gap_reason": "gap_reason",
    "причина пробела": "gap_reason",
    "причина": "gap_reason",
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
    "coefficient_basis": "coefficient_basis",
    "coefficient_status": "coefficient_status",
    "evidence_refs": "evidence_refs",
}


def _fold(value: Any) -> str:
    text = str(value or "").strip().strip("*_` ").strip()
    if len(text) >= 2 and (text[0], text[-1]) in {("(", ")"), ("[", "]")}:
        text = text[1:-1].strip()
    text = text.strip(".,;:").strip()
    return " ".join(text.casefold().replace("ё", "е").split())


def canonicalize_norm_status(value: Any) -> str:
    """Map a whole cell to a closed status. Prose is UNVERIFIED, never EXACT."""

    marker = _fold(value)
    if not marker:
        return "UNVERIFIED"
    if marker in {item.casefold() for item in FIRST_PASS_STATUSES | VERIFIER_STATUSES}:
        return marker.upper()
    return _STATUS_ALIASES.get(marker, "UNVERIFIED")


def canonicalize_match_flag(value: Any) -> str:
    marker = _fold(value)
    if marker in _YES:
        return "yes"
    if marker in _NO:
        return "no"
    if marker in _UNKNOWN:
        return "unknown"
    if not marker:
        return "missing"
    return "unknown"


def contradictions_empty(value: Any) -> bool:
    return _fold(value) in _ABSENCE


_EXACT_APPLICABILITY_STATUSES = frozenset({"EXACT", "EXACT_VERIFIED"})
_ANALOGUE_APPLICABILITY_STATUSES = frozenset(
    {"ANALOGUE", "ANALOGUE_CANDIDATE", "ANALOGUE_VERIFIED"}
)


def is_analogue_norm_status(value: Any) -> bool:
    """Did this row choose by analogy?

    One home for the analogue family (§ 10): a consumer that wants to speak about
    «ограничения аналога» asks this instead of re-listing status tokens, so the
    sheet and the gate can never disagree about which rows are analogues.
    """

    return canonicalize_norm_status(value) in _ANALOGUE_APPLICABILITY_STATUSES


def citation_record_present(row: Mapping[str, Any] | None) -> bool:
    """Were cards ever put in front of the answer that authored this cipher?

    ``bind_row_evidence_ids`` writes ``_evidence_check`` for every cipher-bearing
    model row, so the record's presence means a retrieval happened and the model
    named (or failed to name) the card it chose.  Its absence means the row came
    from a route without retrieval at all — the chat panel of «видимые строки» —
    where demanding a citation would ask the answer for a field it cannot carry
    (§ 3: «не требовать от модели скрытых полей, не предусмотренных её реальным
    ответом»).  Measured on the installed store: 1 081 of 1 082 durable cipher-
    bearing ``EXACT`` rows carry the record.
    """

    payload = row if isinstance(row, Mapping) else {}
    return isinstance(payload.get("_evidence_check"), Mapping)


def cited_ciphers_of(row: Mapping[str, Any] | None) -> list[str]:
    """Ciphers named by the cards the model actually cited.

    Recomputed from the stored ``cited`` card list rather than read from
    ``citation_checkable``: that flag was written by whichever build produced the
    row, and packets stored before it existed carry the cards without the verdict.
    Recomputing keeps an *absent* fact from being silently read as agreement —
    measured on the installed store, 440 of 1082 cipher-bearing ``EXACT`` rows
    were in that shape, and 280 of them cite a different cipher outright.
    """

    payload = row if isinstance(row, Mapping) else {}
    check = payload.get("_evidence_check")
    if not isinstance(check, Mapping):
        return []
    cards = [
        str(item.get("card") or "")
        for item in (check.get("cited") or ())
        if isinstance(item, Mapping)
    ] or [str(item or "") for item in (check.get("cited_ciphers") or ())]
    return [card for card in cards if looks_like_cipher(card)]


def cited_cipher_matches_evidence(row: Mapping[str, Any] | None) -> bool | None:
    """Is the authored cipher the cipher of the cards the model actually cited?

    ``None`` means the payload carries no citation check, it cites no card at all,
    or none of the cited cards names a cipher: nothing is known either way and the
    caller must not read that as agreement — or as contradiction.  A ``False`` is a
    structural contradiction the code can see, and ADR-16 § 6 forbids laundering it
    into confirmed applicability: the model may claim ``EXACT`` for a cipher its own
    references never showed.
    """

    payload = row if isinstance(row, Mapping) else {}
    code = authored_norm_code(payload.get("norm_code") or payload.get("code"))
    cards = cited_ciphers_of(payload)
    if not code or not cards:
        return None
    return any(ciphers_compatible(code, card) for card in cards)


def open_analogue_match_fields(row: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Match facts the model left unproven for its own analogue choice."""

    payload = row if isinstance(row, Mapping) else {}
    return tuple(
        field
        for field in MATCH_FIELDS
        if canonicalize_match_flag(payload.get(field)) != "yes"
    )


def exact_citation_ungrounded(row: Mapping[str, Any] | None) -> bool:
    """Cards were offered for this cipher, and none of them names it.

    Distinct from a contradiction: there the model pointed at a card that says
    something else («неправильная ссылка»); here its answer carries the token and no
    card behind it.  Both are visible in the row's own payload, so neither asks the
    model for a field it did not already have.
    """

    payload = row if isinstance(row, Mapping) else {}
    if not citation_record_present(payload):
        return False
    return cited_cipher_matches_evidence(payload) is None


APPLICABILITY_GAP_KINDS = (
    "cipher_not_in_cited_evidence",
    "cipher_without_cited_card",
    "norm_card_body_unread",
    "analogue_needs_confirmation",
    "exact_match_unresolved",
)


def applicability_gap_kind(row: Mapping[str, Any] | None) -> str:
    """The structural reason a written cipher is not yet substantiated, or ``""``.

    One home on purpose (§ 10): the XLSX trace column and the readiness gap card
    read the same verdict, so they cannot disagree about the same row.
    """

    payload = row if isinstance(row, Mapping) else {}
    if not authored_norm_code(payload.get("norm_code") or payload.get("code")):
        return ""
    if cited_cipher_matches_evidence(payload) is False:
        return "cipher_not_in_cited_evidence"
    check = payload.get("_evidence_check")
    if isinstance(check, Mapping) and check.get("card_body_shown") is False:
        return "norm_card_body_unread"
    status = canonicalize_norm_status(payload.get("norm_status"))
    if status in _ANALOGUE_APPLICABILITY_STATUSES:
        return "analogue_needs_confirmation" if open_analogue_match_fields(payload) else ""
    if status in _EXACT_APPLICABILITY_STATUSES and any(field in payload for field in MATCH_FIELDS):
        # A citation identifies a card; it cannot turn the model's own no/unknown
        # applicability facts into yes. Legacy rows without this factual block
        # keep their citation contract, while explicit facts remain authoritative.
        if open_analogue_match_fields(payload):
            return "exact_match_unresolved"
    if status == "EXACT_VERIFIED":
        # The verifier's own answer carries the five match facts; that is its
        # contract, and it stands in for the first-pass citation.
        if match_fields_for_exact(payload) or not exact_citation_ungrounded(payload):
            return ""
    if status == "EXACT" or status == "EXACT_VERIFIED":
        return "cipher_without_cited_card" if exact_citation_ungrounded(payload) else ""
    return ""


def norm_applicability_substantiated(row: Mapping[str, Any] | None) -> bool:
    """Whether a row's norm choice carries evidence, not just a status token.

    ADR-16 § 6 / task 2026-09-29 § 3: a written ``EXACT`` is a claim, and one token
    is not the confirmation of it.  What confirms it is a fact the code can see in
    the model's *own* answer — the card it was shown and cited, whose body names
    that cipher.  The citation column is announced in the first-pass instruction
    («обязательно укажи точную evidence_refs Qx.Hy выбранной карточки»), so nothing
    here asks the model for a hidden field. Historical rows without match facts
    retain the citation contract. When the model explicitly supplies those facts,
    an unresolved or negative fact cannot be confirmed by an EXACT token.

    An analogue is a different question and keeps its own rule: all five match
    facts, because an analogue by definition claims a transfer the model must
    substantiate.  ``EXACT_VERIFIED`` is the independent verifier's answer, whose
    contract is the match fields plus empty contradictions.  Free text
    («подходит по сути», ``extra_ops``, a note) is never a substantiation.

    A row produced by a route that showed no cards at all — the chat panel of
    visible rows — has no citation to be grounded in, and is left as it was: the
    question there is the operator's, not a missing field in a retrieval answer.
    """

    payload = row if isinstance(row, Mapping) else {}
    if not authored_norm_code(payload.get("norm_code") or payload.get("code")):
        return False
    status = canonicalize_norm_status(payload.get("norm_status"))
    if status not in _EXACT_APPLICABILITY_STATUSES | _ANALOGUE_APPLICABILITY_STATUSES:
        return False
    return not applicability_gap_kind(payload)


def parse_norm_components(value: Any) -> list[dict[str, Any]]:
    """Accept only an explicit model list. Do not split a prose cell into codes."""

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        components: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, Mapping):
                code = str(item.get("norm_code") or item.get("code") or "").strip()
                if code:
                    components.append(dict(item))
                continue
            code = str(item or "").strip()
            if code:
                components.append({"norm_code": code})
        return components
    text = str(value or "").strip()
    if not text or _fold(text) in _ABSENCE or not text.startswith("["):
        return []
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(loaded, Sequence) and not isinstance(loaded, (str, bytes)):
        return parse_norm_components(loaded)
    return []


def demote_self_verified_status(status: str) -> str:
    if status == "EXACT_VERIFIED":
        return "EXACT"
    if status == "ANALOGUE_VERIFIED":
        return "ANALOGUE_CANDIDATE"
    return status if status in FIRST_PASS_STATUSES else "UNVERIFIED"


def authored_norm_code(value: Any) -> str:
    """Strip markdown wrappers. Em-dash and empty stay empty."""

    text = str(value or "").strip().strip("`*\"' ")
    if not text or _fold(text) in _ABSENCE:
        return ""
    return text


def store_code_variants(code: Any) -> tuple[str, ...]:
    """Model writes ГЭСНм10-02-016-06; SQLite stores ГЭСНм:10-02-016-06."""

    authored = authored_norm_code(code)
    if not authored:
        return ()
    compact = authored.replace(" ", "")
    seen: list[str] = []
    for item in (authored, compact):
        if item and item not in seen:
            seen.append(item)
    match = _STORE_CODE_RE.match(compact)
    if match:
        family = match.group("family")
        bare = match.group("bare")
        for item in (f"{family}:{bare}", f"{family}{bare}"):
            if item not in seen:
                seen.append(item)
    return tuple(seen)


def review_card_from_store_row(row: Any) -> dict[str, Any]:
    code = str(getattr(row, "code", "") or "")
    title = str(getattr(row, "title", "") or "")
    measure = str(getattr(row, "measure_unit", "") or "")
    base_unit = str(getattr(row, "base_unit", "") or "")
    profile = row.profile() if hasattr(row, "profile") else {}
    card = profile.get("model_card") if isinstance(profile, Mapping) else {}
    if not isinstance(card, Mapping):
        card = {}
    composition = card.get("work_composition") if isinstance(card.get("work_composition"), Mapping) else {}
    steps = [
        str(item).strip()
        for item in (composition.get("steps") or [])
        if str(item).strip()
    ][:12]
    conditions = [
        str(item).strip()
        for item in (card.get("conditions_to_check") or [])
        if str(item).strip()
    ][:8]
    lines = [
        f"шифр: {code}",
        f"наименование: {title}",
        f"измеритель: {measure}",
        f"базовая единица: {base_unit or '—'}",
        "состав работ:",
    ]
    lines.extend(f"- {step}" for step in steps)
    if not steps:
        lines.append("- (состав в карточке не указан)")
    if conditions:
        lines.append("условия: " + ", ".join(conditions))
    lines.append("карточка каталога по шифру, который указала модель; код норму не выбирал")
    return {
        "ref": f"STORE:{code}",
        "body": "\n".join(lines),
        "code": code,
        "title": title,
        "query_index": 0,
        "hit_index": 0,
        "global_evidence_id": f"store:{code}",
    }


def default_lookup_authored_norm_card(code: Any) -> dict[str, Any] | None:
    authored = authored_norm_code(code)
    if not authored:
        return None
    try:
        from proxy.services.smeta_norm_store import get_smeta_norm_store

        store = get_smeta_norm_store()
    except Exception:
        return None
    for variant in store_code_variants(authored):
        try:
            row = store.by_code(variant)
        except Exception:
            row = None
        if row is not None:
            return review_card_from_store_row(row)
    return None


def prepare_selection_row(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """Drop inbound code-owned flags and refuse first-pass self-verification."""

    payload = dict(row or {})
    payload.pop("_quality_gate", None)
    payload.pop("_research_exhausted", None)
    code = authored_norm_code(
        payload.get("norm_code") or payload.get("code") or payload.get("basis")
    )
    if code:
        payload["norm_code"] = code
    status = demote_self_verified_status(canonicalize_norm_status(payload.get("norm_status")))
    payload["norm_status"] = status
    payload.setdefault("_research_round", 0)
    payload["_rejected_codes"] = rejected_norm_codes(payload)
    if payload.get("_rejection_reasons") in (None, ""):
        payload["_rejection_reasons"] = []
    if status in {"MISSING", "CONFLICT"}:
        return reopen_rejected_selection_for_research(payload)
    return payload


def match_fields_for_exact(row: Mapping[str, Any]) -> bool:
    if not contradictions_empty(row.get("contradictions")):
        return False
    return all(canonicalize_match_flag(row.get(name)) == "yes" for name in MATCH_FIELDS)


def match_fields_block_money(row: Mapping[str, Any]) -> bool:
    """Model-authored flags only: action mismatch never enters money."""

    return canonicalize_match_flag(row.get("action_match")) == "no"


def assign_quality_gate(
    row: Mapping[str, Any],
    *,
    analogues_in_money: bool = ANALOGUES_IN_MONEY_DEFAULT,
) -> dict[str, Any]:
    payload = dict(row)
    status = canonicalize_norm_status(payload.get("norm_status"))
    if status == "EXACT_VERIFIED" and match_fields_for_exact(payload) and not match_fields_block_money(payload):
        payload["_quality_gate"] = "verified"
        payload["norm_status"] = "EXACT_VERIFIED"
        return payload
    if status == "ANALOGUE_VERIFIED" and not match_fields_block_money(payload):
        payload["norm_status"] = "ANALOGUE_VERIFIED"
        if analogues_in_money and canonicalize_match_flag(payload.get("object_match")) != "no":
            payload["_quality_gate"] = "verified"
        else:
            payload["_quality_gate"] = "held_analogue"
        return payload
    if status == "MISSING":
        payload["_quality_gate"] = "missing"
        payload["norm_status"] = "MISSING"
        return payload
    if status == "CONFLICT":
        payload["_quality_gate"] = "rejected"
        payload["norm_status"] = "CONFLICT"
        return payload
    if status == "NEEDS_RESEARCH":
        payload["_quality_gate"] = "research"
        payload["norm_status"] = "NEEDS_RESEARCH"
        return payload
    payload["_quality_gate"] = "unverified"
    return payload


def row_is_quality_terminal(row: Mapping[str, Any] | None) -> bool:
    gate = str((row or {}).get("_quality_gate") or "")
    return gate in {"verified", "held_analogue", "missing", "rejected"} or bool(
        (row or {}).get("_research_exhausted")
    )


def row_needs_verifier(row: Mapping[str, Any] | None) -> bool:
    payload = row if isinstance(row, Mapping) else {}
    if row_is_quality_terminal(payload):
        return False
    status = canonicalize_norm_status(payload.get("norm_status"))
    code = str(payload.get("norm_code") or payload.get("code") or payload.get("basis") or "").strip()
    if status == "NEEDS_RESEARCH":
        return False
    return bool(code) and status in {"EXACT", "ANALOGUE_CANDIDATE", "UNVERIFIED"}


def row_needs_research(row: Mapping[str, Any] | None) -> bool:
    payload = row if isinstance(row, Mapping) else {}
    if row_is_quality_terminal(payload):
        return False
    status = canonicalize_norm_status(payload.get("norm_status"))
    gate = str(payload.get("_quality_gate") or "")
    return status == "NEEDS_RESEARCH" or gate == "research"


def rejected_norm_codes(row: Mapping[str, Any] | None) -> list[str]:
    raw = (row or {}).get("_rejected_codes") or []
    seen: list[str] = []
    for item in raw if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) else []:
        text = str(item or "").strip()
        if text and not any(_same_code(text, previous) for previous in seen):
            seen.append(text)
    return seen


def code_was_rejected(row: Mapping[str, Any] | None, code: Any) -> bool:
    return any(_same_code(code, item) for item in rejected_norm_codes(row))


def remember_rejected_code(
    row: Mapping[str, Any],
    code: Any,
    reason: str = "",
) -> dict[str, Any]:
    payload = dict(row)
    text = str(code or "").strip()
    if not _code_key(text):
        return payload
    codes = rejected_norm_codes(payload)
    if not any(_same_code(text, item) for item in codes):
        codes.append(text)
    payload["_rejected_codes"] = codes
    reasons = [
        dict(item)
        for item in (payload.get("_rejection_reasons") or [])
        if isinstance(item, Mapping)
    ]
    if reason:
        reasons.append({"code": text, "reason": str(reason)})
    payload["_rejection_reasons"] = reasons[-12:]
    return payload


def should_remember_rejection(row: Mapping[str, Any], status: str) -> bool:
    if status == "CONFLICT":
        return True
    if status == "MISSING" and _code_key(
        row.get("norm_code") or row.get("code") or row.get("basis")
    ):
        return True
    message = str(row.get("quality_message") or "")
    if "шифр не подменяет" in message:
        return True
    if match_fields_block_money(row):
        return True
    return canonicalize_match_flag(row.get("object_match")) == "no"


def reopen_rejected_selection_for_research(row: Mapping[str, Any]) -> dict[str, Any]:
    """CONFLICT/MISSING reject a code. The work row stays open for another search.

    Code does not pick a replacement. The model must author the next query and cipher.
    """

    payload = dict(row)
    status = canonicalize_norm_status(payload.get("norm_status"))
    if status not in {"CONFLICT", "MISSING"}:
        return payload
    if payload.get("_research_exhausted"):
        return assign_quality_gate(payload)
    code = payload.get("norm_code") or payload.get("code") or payload.get("basis")
    if should_remember_rejection(payload, status):
        payload = remember_rejected_code(
            payload,
            code,
            str(payload.get("quality_message") or status),
        )
        payload["_last_rejection_status"] = status
        payload["_last_rejected_code"] = authored_norm_code(code)
        payload["_last_rejection_message"] = str(
            payload.get("quality_message") or status
        )
    if not str(payload.get("quality_message") or "").strip():
        payload["quality_message"] = (
            "шифр не подтверждён; нужен новый поиск"
            if status == "CONFLICT"
            else "норма не найдена; нужен новый поиск"
        )
    payload["norm_status"] = "NEEDS_RESEARCH"
    payload["_quality_gate"] = "research"
    return payload


def locator_research_fingerprint(
    locator: Any,
    queries: Sequence[str],
    norm_code: Any = "",
    card_ids: Sequence[str] = (),
) -> str:
    return research_fingerprint(
        [f"{locator}:{item}" for item in queries if str(item).strip()]
        or [str(locator or "").strip()],
        (),
        [str(item) for item in (norm_code, *card_ids) if str(item).strip()],
    )


def rejected_codes_clause(rows: Sequence[Mapping[str, Any]]) -> str:
    lines: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        codes = rejected_norm_codes(row)
        if not codes:
            continue
        locator = str(row.get("source_row") or "").strip() or "?"
        lines.append(f"{locator}: {', '.join(codes)}")
    if not lines:
        return ""
    return " Не выбирай снова уже отклонённые шифры: " + "; ".join(lines) + "."


def mark_research_exhausted(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["_research_exhausted"] = True
    rejected = rejected_norm_codes(payload)
    last_status = canonicalize_norm_status(payload.get("_last_rejection_status"))
    if rejected or last_status == "CONFLICT":
        payload["norm_status"] = "CONFLICT"
        payload["_quality_gate"] = "rejected"
        last_code = authored_norm_code(payload.get("_last_rejected_code"))
        if last_code:
            payload["norm_code"] = last_code
        reason = str(payload.get("_last_rejection_message") or "").strip()
        payload["quality_message"] = (
            f"стратегии поиска исчерпаны; последний конфликт: {reason}"
            if reason and reason != "CONFLICT"
            else "стратегии поиска исчерпаны; конфликт применимости нормы сохранён"
        )
    else:
        payload["norm_status"] = "MISSING"
        payload["_quality_gate"] = "missing"
        payload["quality_message"] = (
            "стратегии поиска исчерпаны; применимый кандидат не найден"
        )
    return payload


def research_strategy_hint(round_index: int) -> str:
    if round_index <= 0:
        return RESEARCH_STRATEGY_HINTS[0]
    return RESEARCH_STRATEGY_HINTS[min(round_index, len(RESEARCH_STRATEGY_HINTS) - 1)]


def research_fingerprint(
    queries: Sequence[str],
    hit_ids: Sequence[str] = (),
    card_ids: Sequence[str] = (),
) -> str:
    blob = json.dumps(
        {
            "q": sorted({_fold(item) for item in queries if str(item).strip()}),
            "h": sorted({str(item).strip() for item in hit_ids if str(item).strip()}),
            "c": sorted({str(item).strip() for item in card_ids if str(item).strip()}),
        },
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fingerprint_is_new(previous: Sequence[str], current: str) -> bool:
    return bool(current) and current not in {str(item) for item in previous if item}


def strip_self_score(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in dict(row).items()
        if key not in SELF_SCORE_FIELDS and not str(key).startswith("_")
    }
    return payload


def _cells(line: str) -> list[str]:
    # The same table contract the decision reader uses: outer pipes are optional in
    # markdown and the model's own [Источник N] mark may sit in front of a line.
    # Cells stay verbatim either way (task § 3, one internal contract).
    return table_cells(line)


def _divider_cell(value: str) -> bool:
    return is_divider_cell(value)


def _map_quality_headers(header: Sequence[str]) -> list[str]:
    """Keep the first alias for a field. Duplicate verdict/norm_status is not a skip."""

    mapped: list[str] = []
    seen: set[str] = set()
    for item in header:
        name = _QUALITY_HEADER_FIELDS.get(
            " ".join(item.replace("**", "").strip().split()).casefold(), ""
        )
        if name and name in seen:
            mapped.append("")
            continue
        if name:
            seen.add(name)
        mapped.append(name)
    return mapped


def _quality_absence_cell(value: str) -> bool:
    marker = _fold(value)
    return marker in _ABSENCE


def align_quality_row_values(header_len: int, values: Sequence[str]) -> list[str] | None:
    """Pad short rows; drop only trailing empty/absence extras. Ambiguous extras stay unread."""

    cells = [str(item) for item in values]
    if header_len <= 0:
        return None
    if len(cells) < header_len:
        return cells + [""] * (header_len - len(cells))
    if len(cells) == header_len:
        return cells
    if len(cells) - header_len > 3:
        return None
    trimmed = list(cells)
    while len(trimmed) > header_len and trimmed and _quality_absence_cell(trimmed[-1]):
        trimmed.pop()
    if len(trimmed) == header_len:
        return trimmed
    return None


def parse_quality_table(raw: str) -> list[dict[str, Any]]:
    """Read a markdown table of closed quality fields. Unknown prose is not a status."""

    lines = str(raw or "").splitlines()
    rows: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        header = _cells(lines[index])
        mapped = _map_quality_headers(header)
        if (
            not header
            or "source_row" not in mapped
            or "norm_status" not in mapped
        ):
            index += 1
            continue
        if index + 1 >= len(lines):
            break
        divider = _cells(lines[index + 1])
        while len(divider) > len(header) and divider and _divider_cell(divider[-1]):
            divider = divider[:-1]
        has_divider = bool(divider) and all(_divider_cell(item) for item in divider)
        if has_divider and len(divider) != len(header) and abs(len(divider) - len(header)) > 3:
            index += 1
            continue
        cursor = index + 2 if has_divider else index + 1
        while cursor < len(lines):
            values = _cells(lines[cursor])
            if not values:
                break
            if len(values) < len(header) - 1 and not opens_as_table(lines[cursor]):
                # A table row may drop its final empty cells; a line much narrower
                # than the table and not opened as a row is prose, and the table
                # ends there instead of turning a sentence into a verdict.
                break
            aligned = align_quality_row_values(len(header), values)
            if aligned is None:
                cursor += 1
                continue
            raw_row = {
                name: value.replace("**", "").strip()
                for name, value in zip(mapped, aligned)
                if name and value.replace("**", "").strip()
            }
            if raw_row.get("source_row"):
                raw_row["source_row"] = normalize_quality_locator(raw_row["source_row"])
            if raw_row.get("source_row"):
                rows.append(raw_row)
            cursor += 1
        index = max(cursor, index + 1)
    return rows


def _code_key(value: Any) -> str:
    text = authored_norm_code(value) or str(value or "").strip()
    return "".join(
        character
        for character in text.casefold()
        if not character.isspace() and character != ":"
    ).rstrip("*`")


def _same_code(left: Any, right: Any) -> bool:
    first, second = _code_key(left), _code_key(right)
    return bool(first and second and first == second)


_QUALIFIED_CIPHER_RE = re.compile(
    r"(?P<family>ГЭСН|ФЕР|ТЕР)(?P<suffix>мр|м|п|р)?"
    r"(?P<bare>\d{2}-\d{2}-\d{3}-\d{2})",
    re.IGNORECASE,
)


def qualified_norm_key(value: Any) -> str:
    """Full family and item identity; presentation changes never supply a family."""

    text = _code_key(value).replace("–", "-").replace("—", "-")
    match = _QUALIFIED_CIPHER_RE.fullmatch(text)
    if not match:
        return ""
    family = match.group("family").upper() + (match.group("suffix") or "").lower()
    return f"{family}:{match.group('bare')}"


def ciphers_identical(left: Any, right: Any) -> bool:
    """Exact qualified item identity; bare codes and tables identify no item."""
    first, second = qualified_norm_key(left), qualified_norm_key(right)
    return bool(first and second and first == second)


_CIPHER_SHAPE_RE = re.compile(r"\d{1,3}[-–]\d{1,2}[-–]\d{1,3}(?:[-–]\d{1,2})?[а-яё]?")


def looks_like_cipher(value: Any) -> bool:
    """Does this string actually carry a norm cipher, not a document title?

    A citation check is only a fact when the cited card names a cipher.  Card
    bodies fall back to the document name when no ``Шифр:`` line exists, and a
    name never contradicts a cipher — it just says nothing.
    """

    return bool(_CIPHER_SHAPE_RE.search(str(value or "")))


def ciphers_compatible(left: Any, right: Any) -> bool:
    """Two presentations must name the same complete family-qualified item."""

    return ciphers_identical(left, right)


def apply_verifier_row(
    selection: Mapping[str, Any],
    verdict: Mapping[str, Any],
    *,
    analogues_in_money: bool = ANALOGUES_IN_MONEY_DEFAULT,
) -> dict[str, Any]:
    payload = dict(selection)
    status = canonicalize_norm_status(verdict.get("norm_status") or verdict.get("verdict"))
    if status not in VERIFIER_STATUSES:
        status = "NEEDS_RESEARCH"
    selected_code = payload.get("norm_code") or payload.get("code") or payload.get("basis")
    verdict_code = verdict.get("norm_code") or verdict.get("code")
    if verdict_code and selected_code and not _same_code(selected_code, verdict_code):
        status = "NEEDS_RESEARCH"
        payload["quality_message"] = "проверяющий не подтвердил тот же шифр; код шифр не подменяет"
    for name in MATCH_FIELDS:
        if name in verdict:
            payload[name] = canonicalize_match_flag(verdict.get(name))
    for name in ("extra_ops", "missing_ops", "contradictions", "coefficient_basis"):
        if verdict.get(name) not in (None, ""):
            payload[name] = verdict.get(name)
    if status == "EXACT_VERIFIED" and not match_fields_for_exact({**payload, "norm_status": status}):
        status = "NEEDS_RESEARCH"
        payload["quality_message"] = "EXACT_VERIFIED без полных признаков соответствия отклонён"
    payload["norm_status"] = status
    payload["verifier_applied"] = True
    if should_remember_rejection(payload, status):
        payload = remember_rejected_code(
            payload,
            selected_code,
            str(payload.get("quality_message") or status),
        )
    if status in {"CONFLICT", "MISSING"}:
        return reopen_rejected_selection_for_research(payload)
    return assign_quality_gate(payload, analogues_in_money=analogues_in_money)


def apply_verifier_table(
    rows: Sequence[Mapping[str, Any]],
    raw: str,
    *,
    analogues_in_money: bool = ANALOGUES_IN_MONEY_DEFAULT,
) -> list[dict[str, Any]]:
    parsed = [
        item
        for item in parse_quality_table(raw)
        if str(item.get("source_row") or "").strip()
    ]
    verdicts = {
        normalize_quality_locator(item.get("source_row")): item
        for item in parsed
        if normalize_quality_locator(item.get("source_row"))
    }
    table_unparsed = not parsed
    updated: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        key = str(payload.get("source_row") or "").strip()
        verdict = verdicts.get(normalize_quality_locator(key)) or verdicts.get(key)
        if verdict is None:
            if row_needs_verifier(payload):
                if table_unparsed:
                    payload["_verifier_unparsed"] = True
                    payload["quality_message"] = (
                        "таблица проверки не разобрана; строка не сожжена в MISSING"
                    )
                else:
                    payload["norm_status"] = "NEEDS_RESEARCH"
                    payload["_quality_gate"] = "research"
                    payload["quality_message"] = "проверяющий не вернул закрытый статус строки"
            updated.append(payload)
            continue
        payload.pop("_verifier_unparsed", None)
        updated.append(
            apply_verifier_row(payload, verdict, analogues_in_money=analogues_in_money)
        )
    return updated


def _locator_aliases(row: Mapping[str, Any], catalog: Any | None) -> set[str]:
    raw = row.get("source_row")
    if raw in (None, ""):
        return set()
    keys = {str(raw).strip()}
    lookup = getattr(catalog, "lookup", None)
    if lookup is not None:
        found = lookup(raw)
        locator = getattr(found, "locator", None) if found is not None else None
        if locator:
            keys.add(str(locator).strip())
    return {item for item in keys if item}


def _same_work_title(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    first = _fold(left.get("title") or left.get("name") or left.get("work") or "")
    second = _fold(right.get("title") or right.get("name") or right.get("work") or "")
    if not first or not second:
        return True
    if first == second:
        return True
    if len(first) >= 12 and len(second) >= 12 and (first in second or second in first):
        return True
    return first[:48] == second[:48]


def merge_quality_gated_rows(
    existing: Sequence[Mapping[str, Any]],
    incoming: Sequence[Mapping[str, Any]],
    catalog: Any | None = None,
) -> list[dict[str, Any]]:
    """Terminal rows stay. Same locator may be replaced only for the same work title."""

    merged: list[dict[str, Any]] = []
    terminal_keys: set[str] = set()
    index_by_key: dict[str, int] = {}
    for row in existing:
        if not isinstance(row, Mapping):
            continue
        payload = dict(row)
        aliases = _locator_aliases(payload, catalog)
        if not aliases:
            continue
        if row_is_quality_terminal(payload):
            merged.append(payload)
            position = len(merged) - 1
            for key in aliases:
                terminal_keys.add(key)
                index_by_key[key] = position
            continue
        merged.append(payload)
        position = len(merged) - 1
        for key in aliases:
            index_by_key[key] = position
    for row in incoming:
        if not isinstance(row, Mapping):
            continue
        payload = dict(row)
        aliases = _locator_aliases(payload, catalog)
        if not aliases or invented_source_row(payload.get("source_row")):
            continue
        if aliases & terminal_keys:
            continue
        existing_index = next((index_by_key[key] for key in aliases if key in index_by_key), None)
        if existing_index is None:
            merged.append(payload)
            position = len(merged) - 1
            if row_is_quality_terminal(payload):
                terminal_keys.update(aliases)
            for key in aliases:
                index_by_key[key] = position
            continue
        if not _same_work_title(merged[existing_index], payload):
            continue
        payload = carry_evidence_refs(merged[existing_index], payload)
        merged[existing_index] = payload
        if row_is_quality_terminal(payload):
            terminal_keys.update(aliases)
        for key in aliases:
            index_by_key[key] = existing_index
    return merged


def terminal_source_row_keys(
    rows: Sequence[Mapping[str, Any]],
    catalog: Any | None = None,
) -> set[str]:
    keys: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or not row_is_quality_terminal(row):
            continue
        keys.update(_locator_aliases(row, catalog))
    return keys


def aggregate_norms_status(rows: Sequence[Mapping[str, Any]]) -> str:
    work = [dict(row) for row in rows if isinstance(row, Mapping)]
    if not work:
        return "norms_unverified"
    verified = 0
    unresolved = 0
    for row in work:
        gate = str(row.get("_quality_gate") or "")
        if gate == "verified":
            verified += 1
        elif gate in {"held_analogue", "missing", "rejected"}:
            unresolved += 1
        else:
            unresolved += 1
    if verified and not unresolved:
        return "norms_verified"
    if verified:
        return "norms_partial"
    return "norms_unverified"


def pricing_block_reason(row: Mapping[str, Any] | None) -> tuple[bool, str, str]:
    """True when a QUALITY_DIAGNOSTIC row must not become a priced position.

    The active ADR-15 workbook adapter must not call this. Terminal model
    ciphers are priced by exact lookup; this overlay exists only for the
    isolated verifier loop.
    """

    payload = row if isinstance(row, Mapping) else {}
    if len(parse_norm_components(payload.get("norm_components"))) >= 2:
        return True, "composite_unpriced", "несколько норм на строку: применимость посчитана, сумму код не собирает"
    gate = str(payload.get("_quality_gate") or "").strip()
    status = canonicalize_norm_status(payload.get("norm_status"))
    if gate == "verified" and status in {"EXACT_VERIFIED", "ANALOGUE_VERIFIED"}:
        return False, "bound", ""
    if gate == "held_analogue" or status == "ANALOGUE_VERIFIED":
        return True, "analogue_held_for_review", "аналог не входит в стоимость до разрешения профиля"
    if gate == "missing" or status in {"MISSING", "NEEDS_RESEARCH"}:
        return True, "missing_norm", str(payload.get("quality_message") or "норма не подтверждена")
    if gate == "rejected" or status == "CONFLICT":
        return True, "quality_conflict", str(payload.get("quality_message") or "конфликт применимости нормы")
    return True, "norms_unverified", "нет независимой проверки применимости нормы"


def invented_source_row(value: Any) -> bool:
    text = str(value or "").strip()
    return (not text) or text.endswith("*")


_MODEL_EVIDENCE_REF = re.compile(r"^Q(\d+)\.H(\d+)$", re.IGNORECASE)


def model_evidence_ref_tokens(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes)):
        texts = [str(item or "") for item in value]
    else:
        texts = [str(value or "")]
    found: list[str] = []
    for text in texts:
        for token in text.replace("[", " ").replace("]", " ").replace(",", " ").split():
            candidate = token.strip(".*_`:;()").upper()
            if _MODEL_EVIDENCE_REF.fullmatch(candidate):
                found.append(candidate)
    return list(dict.fromkeys(found))


def carry_evidence_refs(
    prior: Mapping[str, Any] | None,
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep first-pass Qx.Hy when research/verify returns notes instead of handles."""

    payload = dict(incoming)
    incoming_refs = model_evidence_ref_tokens(payload.get("evidence_refs"))
    if incoming_refs:
        payload["evidence_refs"] = incoming_refs
        return payload
    prior_refs = model_evidence_ref_tokens((prior or {}).get("evidence_refs"))
    if prior_refs:
        payload["evidence_refs"] = prior_refs
        bindings = (prior or {}).get("evidence_bindings")
        if isinstance(bindings, Mapping) and bindings:
            payload["evidence_bindings"] = dict(bindings)
    elif not unresolved_placeholder(payload.get("evidence_refs")):
        payload.pop("evidence_refs", None)
    return payload


def carry_prior_norm_code(
    prior: Mapping[str, Any] | None,
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep the model cipher if research answered with an empty cell, not a new code."""

    payload = dict(incoming)
    incoming_code = authored_norm_code(
        payload.get("norm_code") or payload.get("code") or payload.get("basis")
    )
    if incoming_code:
        payload["norm_code"] = incoming_code
        return payload
    prior_payload = prior or {}
    prior_code = authored_norm_code(
        prior_payload.get("norm_code")
        or prior_payload.get("code")
        or prior_payload.get("basis")
    )
    if not prior_code or code_was_rejected(prior_payload, prior_code):
        return payload
    payload["norm_code"] = prior_code
    status = canonicalize_norm_status(payload.get("norm_status"))
    if status in {"MISSING", "UNVERIFIED", "NEEDS_RESEARCH"}:
        payload["norm_status"] = "EXACT"
        payload["_quality_gate"] = "unverified"
        payload["quality_message"] = "повторный поиск не назвал новый шифр; проверяем прежний"
    return payload


def unresolved_placeholder(value: Any) -> bool:
    marker = " ".join(str(value or "").casefold().replace("ё", "е").split())
    return "qx.hy" in marker or "отсутствует в выдаче" in marker


def verifier_packets(
    rows: Sequence[Mapping[str, Any]],
    size: int = VERIFIER_PACKET_SIZE,
) -> list[list[dict[str, Any]]]:
    packet_size = max(1, int(size or VERIFIER_PACKET_SIZE))
    packets: list[list[dict[str, Any]]] = []
    batch: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        batch.append(dict(row))
        if len(batch) >= packet_size:
            packets.append(batch)
            batch = []
    if batch:
        packets.append(batch)
    return packets


def bind_selected_review_card(
    row: Mapping[str, Any],
    cards: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Prefer the card whose code matches the selected norm, not the first Qx.Hy."""

    refs = [
        str(item).strip().upper()
        for item in (row.get("evidence_refs") or [])
        if str(item).strip()
    ]
    selected_code = row.get("norm_code") or row.get("code") or row.get("basis")
    referenced = [dict(cards[ref]) for ref in refs if ref in cards]
    matching = [card for card in referenced if _same_code(card.get("code"), selected_code)]
    if not matching and _code_key(selected_code):
        matching = [
            dict(card)
            for card in cards.values()
            if _same_code(card.get("code"), selected_code)
        ]
    selected = matching[0] if matching else None
    alternatives = [
        card
        for card in referenced
        if selected is None or card.get("ref") != selected.get("ref")
    ]
    if selected is None and referenced:
        alternatives = referenced
    return selected, alternatives[:4]


def resolve_selected_review_card(
    row: Mapping[str, Any],
    cards: Mapping[str, Mapping[str, Any]],
    lookup_norm_card: Any = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """RAG window first; if the model named a cipher, read that exact catalog card."""

    selected, alternatives = bind_selected_review_card(row, cards)
    if selected is not None:
        return selected, alternatives
    lookup = lookup_norm_card or default_lookup_authored_norm_card
    code = authored_norm_code(row.get("norm_code") or row.get("code") or row.get("basis"))
    if not code:
        return None, alternatives
    try:
        store_card = lookup(code)
    except Exception:
        store_card = None
    if isinstance(store_card, Mapping) and store_card:
        return dict(store_card), alternatives
    return None, alternatives


def _attach_selected_card(payload: dict[str, Any], selected: Mapping[str, Any]) -> dict[str, Any]:
    payload["_selected_card_ref"] = selected.get("ref")
    payload["_selected_card_id"] = selected.get("global_evidence_id")
    payload["_selected_card_code"] = selected.get("code")
    return payload


def mark_missing_selected_card(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["norm_status"] = "NEEDS_RESEARCH"
    payload["_quality_gate"] = "research"
    payload["quality_message"] = "карточка выбранного шифра не найдена в evidence"
    return payload


def split_rows_missing_selected_card(
    rows: Sequence[Mapping[str, Any]],
    evidence_chunks: Sequence[Any],
    lookup_norm_card: Any = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not evidence_chunks:
        return [dict(row) for row in rows if isinstance(row, Mapping)], []
    cards = _evidence_cards(evidence_chunks)
    to_verify: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        payload = dict(row)
        code = authored_norm_code(
            payload.get("norm_code") or payload.get("code") or payload.get("basis")
        )
        selected, _alternatives = resolve_selected_review_card(
            payload, cards, lookup_norm_card=lookup_norm_card
        )
        if code and selected is None:
            missing.append(mark_missing_selected_card(payload))
            continue
        if selected:
            payload = _attach_selected_card(payload, selected)
        to_verify.append(payload)
    return to_verify, missing


def close_quality_coverage(
    source_locators: Sequence[Any],
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    allowed = [
        str(item).strip()
        for item in source_locators
        if str(item).strip() and not invented_source_row(item)
    ]
    kept: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        key = str(row.get("source_row") or "").strip()
        if invented_source_row(key) or (allowed and key not in set(allowed)):
            continue
        kept.append(dict(row))
        seen.add(key)
    for locator in allowed:
        if locator in seen:
            continue
        kept.append(
            {
                "source_row": locator,
                "title": locator,
                "norm_status": "MISSING",
                "_quality_gate": "missing",
                "quality_message": "locator не получил терминальный статус",
            }
        )
    return kept


def verifier_generation_tokens(row_count: int, reserve: int) -> int:
    n = max(1, int(row_count or 1))
    wanted = min(max(900, 320 * n + 240), 2048)
    cap = int(reserve or wanted)
    if cap < wanted:
        return wanted
    return min(wanted, cap)


def packet_locator_keys(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    return {
        str(item.get("source_row") or "").strip()
        for item in rows
        if isinstance(item, Mapping) and str(item.get("source_row") or "").strip()
    }


def parsed_quality_locator_keys(raw: str) -> set[str]:
    return {
        normalize_quality_locator(item.get("source_row"))
        for item in parse_quality_table(raw)
        if normalize_quality_locator(item.get("source_row"))
    }


def verifier_table_covers_packet(raw: str, rows: Sequence[Mapping[str, Any]]) -> bool:
    wanted = packet_locator_keys(rows)
    parsed = parsed_quality_locator_keys(raw)
    return bool(wanted) and parsed == wanted


def merge_format_retry_rows(
    first_rows: Sequence[Mapping[str, Any]],
    retry_rows: Sequence[Mapping[str, Any]],
    expected_locators: Sequence[Any] | None = None,
) -> list[dict[str, Any]]:
    """Keep first-pass codes. Retry may only fill missing locators."""

    allowed = {
        str(item).strip()
        for item in (expected_locators or ())
        if str(item).strip() and not invented_source_row(item)
    }
    merged: dict[str, dict[str, Any]] = {}
    for row in first_rows:
        if not isinstance(row, Mapping):
            continue
        key = str(row.get("source_row") or "").strip()
        if invented_source_row(key) or (allowed and key not in allowed):
            continue
        merged[key] = dict(row)
    for row in retry_rows:
        if not isinstance(row, Mapping):
            continue
        key = str(row.get("source_row") or "").strip()
        if invented_source_row(key) or (allowed and key not in allowed) or key in merged:
            continue
        merged[key] = dict(row)
    return list(merged.values())


def expand_norm_components(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        payload = dict(row)
        parent = str(payload.get("source_row") or "").strip()
        components = parse_norm_components(payload.get("norm_components"))
        if len(components) < 2 or not parent or invented_source_row(parent):
            expanded.append(payload)
            continue
        for index, component in enumerate(components, start=1):
            child = dict(payload)
            child["norm_code"] = component.get("norm_code") or component.get("code")
            if component.get("evidence_refs"):
                child["evidence_refs"] = component.get("evidence_refs")
            child["_parent_locator"] = parent
            child["_component_id"] = index
            child["source_row"] = f"{parent}#{index}"
            expanded.append(child)
    return expanded


def collapse_norm_components(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    plain: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        payload = dict(row)
        parent = str(payload.get("_parent_locator") or "").strip()
        if not parent:
            plain.append(payload)
            continue
        groups.setdefault(parent, []).append(payload)
    collapsed = list(plain)
    for parent, children in groups.items():
        if len(children) == 1:
            child = dict(children[0])
            child["source_row"] = parent
            child.pop("_parent_locator", None)
            child.pop("_component_id", None)
            collapsed.append(child)
            continue
        parent_row = dict(children[0])
        parent_row["source_row"] = parent
        parent_row["norm_components"] = [
            {
                "norm_code": item.get("norm_code"),
                "norm_status": item.get("norm_status"),
                "_quality_gate": item.get("_quality_gate"),
                "evidence_refs": item.get("evidence_refs"),
            }
            for item in children
        ]
        if all(item.get("_quality_gate") == "verified" for item in children):
            parent_row["_quality_gate"] = "verified"
            parent_row["norm_status"] = "EXACT_VERIFIED"
        else:
            parent_row["_quality_gate"] = "missing"
            parent_row["norm_status"] = "MISSING"
            parent_row["quality_message"] = "составная работа подтверждена не полностью"
        parent_row.pop("_parent_locator", None)
        parent_row.pop("_component_id", None)
        collapsed.append(parent_row)
    return collapsed


def row_needs_coefficient_review(row: Mapping[str, Any] | None) -> bool:
    payload = row if isinstance(row, Mapping) else {}
    if str(payload.get("coefficient_status") or "").strip():
        return False
    if not row_is_quality_terminal(payload):
        return False
    coefficient = payload.get("coefficient")
    if coefficient in (None, "", 1, 1.0, "1", "1.0"):
        return False
    return True


def apply_coefficient_fields(
    selection: Mapping[str, Any],
    verdict: Mapping[str, Any],
) -> dict[str, Any]:
    payload = dict(selection)
    if verdict.get("coefficient") not in (None, ""):
        payload["coefficient"] = verdict.get("coefficient")
    if verdict.get("coefficient_applies_to") not in (None, ""):
        payload["coefficient_applies_to"] = verdict.get("coefficient_applies_to")
    if verdict.get("coefficient_basis") not in (None, ""):
        payload["coefficient_basis"] = verdict.get("coefficient_basis")
    status = str(verdict.get("coefficient_status") or "").strip().upper()
    if status in {"CONFIRMED", "UNCLEAR", "OMITTED"}:
        payload["coefficient_status"] = status
    return payload


def apply_coefficient_table(
    rows: Sequence[Mapping[str, Any]],
    raw: str,
) -> list[dict[str, Any]]:
    parsed = {
        str(item.get("source_row") or "").strip(): item
        for item in parse_quality_table(raw)
        if str(item.get("source_row") or "").strip()
    }
    updated: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        verdict = parsed.get(str(payload.get("source_row") or "").strip())
        if verdict is None:
            updated.append(payload)
            continue
        updated.append(apply_coefficient_fields(payload, verdict))
    return updated


async def run_coefficient_review(
    rows: Sequence[Mapping[str, Any]],
    *,
    review: Any = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    current = [dict(row) for row in rows if isinstance(row, Mapping)]
    events: list[dict[str, Any]] = []
    pending = [row for row in current if row_needs_coefficient_review(row)]
    if not pending or review is None:
        return current, events
    index_by_key = {
        str(row.get("source_row") or "").strip(): index
        for index, row in enumerate(current)
        if str(row.get("source_row") or "").strip()
    }
    for packet in verifier_packets(pending):
        raw = str(await review(packet) or "")
        for updated in apply_coefficient_table(packet, raw):
            key = str(updated.get("source_row") or "").strip()
            if key in index_by_key:
                current[index_by_key[key]] = apply_coefficient_fields(
                    current[index_by_key[key]], updated
                )
    events.append({"stage": "coefficient_review", "rows": len(pending)})
    return current, events


def evaluate_lsr_quality_run(
    rows: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]] = (),
    *,
    expected_locator_count: int | None = None,
    expected_locators: Sequence[Any] | None = None,
) -> dict[str, Any]:
    work = [dict(row) for row in rows if isinstance(row, Mapping)]
    locators = [
        str(row.get("source_row") or "").strip()
        for row in work
        if str(row.get("source_row") or "").strip()
    ]
    invented = [key for key in locators if invented_source_row(key)]
    real = [key for key in locators if not invented_source_row(key)]
    wanted = [
        str(item).strip()
        for item in (expected_locators or ())
        if str(item).strip() and not invented_source_row(item)
    ]
    expected_n = len(wanted) if wanted else expected_locator_count
    priced = [row for row in work if not pricing_block_reason(row)[0]]
    card_mismatch = [
        str(row.get("source_row") or "")
        for row in work
        if row.get("_selected_card_ref")
        and row.get("norm_code")
        and row.get("_selected_card_code")
        and not _same_code(row.get("norm_code"), row.get("_selected_card_code"))
    ]
    packet_ok = all(
        int(event.get("rows") or 0) <= VERIFIER_PACKET_SIZE
        for event in events
        if str(event.get("stage") or "") in {"verify", "verify_unparsed", "verify_format_retry"}
    )
    checks = {
        "no_invented_locators": not invented,
        "locator_count": expected_n is None or len(set(real)) == int(expected_n),
        "expected_locators_present": not wanted or set(wanted) <= set(real),
        "money_only_exact_verified": all(
            str(row.get("_quality_gate") or "") == "verified"
            and canonicalize_norm_status(row.get("norm_status")) == "EXACT_VERIFIED"
            for row in priced
        ),
        "selected_card_matches_code": not card_mismatch,
        "verifier_packets_small": packet_ok,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "locator_count": len(set(real)),
        "invented_locators": invented,
        "priced_rows": len(priced),
        "card_mismatch": card_mismatch,
    }


def build_blind_review_evidence_items(
    rows: Sequence[Mapping[str, Any]],
    evidence_chunks: Sequence[Any] = (),
    lookup_norm_card: Any = None,
) -> list[str]:
    """VOR first, then the matching card, then same-code and alternatives."""

    cards = _evidence_cards(evidence_chunks)
    vor_blocks: list[str] = []
    selected_blocks: list[str] = []
    same_code_blocks: list[str] = []
    alternative_blocks: list[str] = []
    for row in rows:
        visible = strip_self_score(row)
        refs = [
            str(item).strip().upper()
            for item in (visible.get("evidence_refs") or [])
            if str(item).strip()
        ]
        selected, alternatives = resolve_selected_review_card(
            visible, cards, lookup_norm_card=lookup_norm_card
        )
        locator = visible.get("source_row")
        vor_blocks.append(
            "\n".join(
                [
                    f"## source_row={locator}",
                    f"ВОР: {visible.get('title') or ''}",
                    f"Ед.: {visible.get('unit') or ''}  Кол-во: {visible.get('quantity') if visible.get('quantity') is not None else ''}",
                    f"Выбранный шифр: {visible.get('norm_code') or visible.get('code') or visible.get('basis') or ''}",
                    f"Ссылки evidence: {', '.join(refs) or '—'}",
                ]
            )
        )
        if selected:
            selected_blocks.append(
                "\n".join(
                    [
                        f"Выбранная карточка строки {locator} ({selected.get('code') or ''} {selected.get('ref') or ''}):",
                        str(selected.get("body") or "")[:4000],
                    ]
                )
            )
            same = [
                card
                for card in cards.values()
                if _same_code(card.get("code"), selected.get("code"))
                and card.get("ref") != selected.get("ref")
            ][:2]
            if same:
                same_code_blocks.append(
                    "\n".join(
                        [f"Другие карточки того же шифра, строка {locator}:"]
                        + [
                            f"- {card.get('ref')} {card.get('code') or ''}: "
                            f"{str(card.get('title') or card.get('body') or '')[:400]}"
                            for card in same
                        ]
                    )
                )
        else:
            selected_blocks.append(
                f"source_row={locator}: карточка выбранного шифра не передана. Не подтверждай норму без карточки."
            )
        if alternatives:
            alternative_blocks.append(
                "\n".join(
                    [f"Альтернативы строки {locator}:"]
                    + [
                        f"- {card.get('ref')} {card.get('code') or ''}: "
                        f"{str(card.get('title') or card.get('body') or '')[:400]}"
                        for card in alternatives
                    ]
                )
            )
    return vor_blocks + selected_blocks + same_code_blocks + alternative_blocks


def build_blind_review_payload(
    rows: Sequence[Mapping[str, Any]],
    evidence_chunks: Sequence[Any] = (),
    lookup_norm_card: Any = None,
) -> str:
    """VOR + matching card + alternatives. No first-pass self-score."""

    return "\n\n".join(
        build_blind_review_evidence_items(
            rows, evidence_chunks, lookup_norm_card=lookup_norm_card
        )
    )


def _evidence_cards(chunks: Sequence[Any]) -> dict[str, dict[str, Any]]:
    cards: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        meta = dict(getattr(chunk, "meta", None) or {})
        if not meta and isinstance(chunk, Mapping):
            meta = dict(chunk.get("meta") or chunk)
        ref = str(meta.get("model_evidence_ref") or "").strip().upper()
        if not ref:
            continue
        body = str(getattr(chunk, "content", "") or meta.get("content") or "").strip()
        code = str(meta.get("norm_code") or "").strip()
        if not code:
            for line in body.splitlines()[:12]:
                folded = line.casefold()
                if folded.startswith("шифр") or folded.startswith("norm_code"):
                    code = line.split(":", 1)[-1].strip()
                    break
        query_index = 0
        hit_index = 0
        if ref.startswith("Q") and ".H" in ref:
            left, right = ref[1:].split(".H", 1)
            if left.isdigit():
                query_index = int(left)
            if right.isdigit():
                hit_index = int(right)
        cards[ref] = {
            "ref": ref,
            "body": body,
            "code": code,
            "title": str(meta.get("title") or getattr(chunk, "doc_name", "") or ""),
            "query_index": query_index,
            "hit_index": hit_index,
            "global_evidence_id": str(meta.get("global_evidence_id") or ""),
        }
    return cards


def lsr_result_table_instruction(*, sheet_clause: str = "", remaining_clause: str = "") -> str:
    return (
        f"{sheet_clause}"
        + model_lsr_result_field_instruction()
        + " "
        "Если выбран Markdown: Начни ответ с таблицы результата; пояснения — после таблицы. "
        "Неприменимые необязательные колонки можно не объявлять. Для объявленной "
        "колонки сохраняй пустую ячейку, чтобы остальные значения не сдвигались. "
        "row_role только: work, material, equipment, resource, header или unresolved. "
        "header — заголовок, раздел, примечание или итог исходника: строка учтена "
        "и не требует монтажной нормы ни кодом, ни моделью. "
        "work — самостоятельная технологическая операция, в том числе пока без нормы. "
        "Для ВОР отсутствие нормы и цены не меняет известную работу на unresolved. "
        "Для ЛСР выбери норму/аналог либо укажи конкретный open_gap. material/equipment — "
        "отдельная стоимость поставки; resource — ресурс конкретной работы; unresolved — "
        "нерешённая позиция с конкретным open_gap. Связывай resource/material/equipment "
        "через work_row (устойчивый locator строки работы), не через шифр нормы: одинаковый "
        "шифр может встречаться несколько раз. supply_kind: install, supply или both. "
        "Монтаж и поставку учитывай раздельно, без двойного учёта материалов нормы. "
        "Норма монтажной работы относится к row_role=work; не записывай её как цену изделия. "
        "quantity — исходное количество; не подменяй его расчётным. Фасовку, длину секции и "
        "массу на метр пиши только в conversion_factor/calc_quantity вместе с conversion_source; "
        "не смешивай их с coefficient условий производства. Код пропущенные значения не угадывает. "
        "norm_status — только закрытый токен: EXACT, ANALOGUE_CANDIDATE, NEEDS_RESEARCH, "
        "MISSING или CONFLICT. Не пиши EXACT_VERIFIED и ANALOGUE_VERIFIED: это статус "
        "отдельной проверки, а не твоего первого ответа. "
        "MISSING означает, что norm_code не выбран. Отсутствие цены здесь не оценивай: "
        "если norm_code заполнен, не используй MISSING только из-за отсутствующей цены. "
        "Для строки, которую ты оставляешь не готовой (NEEDS_RESEARCH или MISSING), укажи "
        "колонку gap_reason одним из двух токенов: insufficient_source_data — сведений "
        "исходной строки не хватает, чтобы выбрать норму (напиши в open_gap, каких именно), "
        "или no_suitable_candidate — карточки просмотрены и ни одна не подходит (напиши в "
        "open_gap, что именно не подошло). Другие причины не выдумывай и не выбирай: "
        "шифр не существует в базе, ссылка противоречит твоим же карточкам или аналог "
        "не обоснован — это код видит по своим проверкам сам. Свои слова оставляй в open_gap "
        "дословно; gap_reason вердикт не повышает и норму не выбирает. "
        "Пояснения вроде «подходит по сути» можно писать в extra_ops, "
        "но они не включают строку в расчёт. Не ограничивай число возвращаемых решений. "
        "Выбранная норма/аналог: точный norm_code и evidence_refs Qx.Hy той же карточки, "
        "не Qx. Пустой norm_code — карточка не выбрана. В source_row скопируй "
        "уникальный locator исходной строки; название "
        "раздела указывай только в section. Locator, unit и quantity копируй из одной "
        "и той же строки каталога без перенумерации. Для материала title сохраняет название "
        "изделия; для обоснованной монтажной работы title описывает выбранную тобой работу. "
        "Один source_row может обосновывать материал и его монтаж разными строками. "
        "Не превращай каждое изделие в отдельную работу автоматически: учитывай состав нормы. "
        "Строки-разделы имеют собственные locator, "
        "поэтому locator работ могут идти с пропусками: не сдвигай следующие работы на номер "
        "строки-раздела. Перед ответом сверь source_row возвращаемых решений с указанными "
        "строками ВОР. При обычном продолжении неизменённые решения сохраняются по operation_id; "
        "при явном пересмотре верни все предложенные прежние операции, включая неизменённые. "
        "Код не выбирает норму и не меняет ячейки. "
        "Текущий пакет не является всем исходником: не делай вывод об отсутствии данных "
        "в остальных строках файла, которые будут предложены следующими пакетами. "
        "Коэффициент без явного coefficient_applies_to код не умножает. "
        "Если работа составная, можно добавить norm_components как JSON-список "
        "{\"norm_code\", \"evidence_refs\"}; иначе оставь ячейку пустой. "
        "Лучше честный MISSING, чем случайный шифр из выдачи."
        f"{remaining_clause}"
    )


def lsr_verifier_instruction() -> str:
    return (
        "Ты независимо проверяешь выбранную моделью норму по строке ВОР и полной карточке. "
        "Входа с самооценкой («подходит по сути», coverage, analogue) нет. "
        "Независимо определи применимость: сопоставь действие, объект, условия, физический "
        "измеритель и состав работ. Сначала заполни match-поля и фактические contradictions, "
        "если они есть, затем закрытый verdict. Не ищи противоречие, если карточка его не содержит. "
        "Верни Markdown-таблицу со столбцами source_row, title, unit, norm_code, "
        "verdict, action_match, object_match, condition_match, unit_compatible, "
        "composition_covers, extra_ops, missing_ops, contradictions. "
        "verdict только: EXACT_VERIFIED, ANALOGUE_VERIFIED, NEEDS_RESEARCH, MISSING, CONFLICT. "
        "EXACT_VERIFIED допустим только если все match-поля yes и contradictions пусты. "
        "В source_row верни ровно locator из заголовка ## source_row=… "
        "(цифру или ярлык вроде ВОР!R5), без слова «Строка». "
        "Верни ровно по одной строке на каждый переданный source_row и не добавляй новые locator. "
        "Если действие ВОР и состав нормы не совпадают — CONFLICT или NEEDS_RESEARCH, "
        "не EXACT_VERIFIED. CONFLICT/MISSING отвергают только этот шифр: строка пойдёт "
        "на новый поиск, код замену не подставит. Шифр не подменяй: либо тот же "
        "norm_code, либо NEEDS_RESEARCH. "
        "unit_compatible=yes, если это тот же физический измеритель "
        "(м² и 100 м2, шт и 100 шт). condition_match=yes, если в карточке нет "
        "особых условий, которых нет в ВОР. Если карточка передана, заполни все "
        "match-поля yes или no, не оставляй unknown. "
        "Не меняй и не оценивай коэффициент: его проверит отдельный пакет. "
        "Не выводи JSON."
    )


def lsr_format_retry_instruction() -> str:
    return (
        "Предыдущий ответ повредил Markdown-таблицу. Пересобери ТУ ЖЕ таблицу "
        "с теми же source_row, title, unit, quantity, norm_code, norm_status и "
        "evidence_refs. Не меняй нормы, не добавляй строки, не пиши пояснений. "
        "Не выводи JSON."
    )


def lsr_verifier_format_retry_instruction() -> str:
    return (
        "Предыдущий ответ проверки не разобран как таблица. Пересобери ТУ ЖЕ "
        "Markdown-таблицу: source_row, title, unit, norm_code, verdict, "
        "action_match, object_match, condition_match, unit_compatible, "
        "composition_covers, extra_ops, missing_ops, contradictions. "
        "source_row — тот же locator, без слова «Строка». "
        "Не меняй verdict и match-поля, не добавляй locator, без вступления. "
        "Не выводи JSON."
    )


def lsr_research_result_evidence(
    rows: Sequence[Mapping[str, Any]],
    groups: Sequence[str],
) -> list[str]:
    """Pack only unresolved VOR rows and the new cards. Do not resend the workbook."""

    blocks = [
        (
            f"Неподтверждённая строка {item.get('source_row')}: "
            f"{item.get('title') or ''} | {item.get('unit') or ''} | "
            f"{item.get('quantity') if item.get('quantity') is not None else ''}"
        )
        for item in rows
        if isinstance(item, Mapping)
    ]
    blocks.extend(str(item) for item in groups if str(item).strip())
    return blocks


def lsr_coefficient_instruction() -> str:
    return (
        "Проверь только коэффициент. Не меняй norm_code, verdict и match-поля нормы. "
        "Верни Markdown-таблицу: source_row, coefficient, coefficient_applies_to, "
        "coefficient_basis, coefficient_status. "
        "coefficient_status только: CONFIRMED, UNCLEAR, OMITTED. "
        "Если исходник уже учёл коэффициент в количестве — UNCLEAR. "
        "Не выводи JSON."
    )


def lsr_research_query_instruction(
    round_index: int,
    rows: Sequence[Mapping[str, Any]] = (),
) -> str:
    hint = research_strategy_hint(round_index)
    return (
        "Если ты решил, что внешний поиск нужен и предыдущий поиск не дал проверяемой нормы по указанным строкам: "
        f"Смени стратегию: {hint} "
        "Верни только новые поисковые запросы: JSON-конверт либо дословные строки запросов. "
        "Не повторяй прежние формулировки. Нормы пока не выбирай. "
        "Если для ВОР исходника достаточно, допустим ответ {\"artifact_kind\":\"vor\",\"queries\":[]}. "
        "Не расширяй область на датасеты вне явно выбранных пользователем."
        f"{rejected_codes_clause(rows)}"
    )


@dataclass
class LsrQualityGateResult:
    rows: list[dict[str, Any]]
    norms_status: str
    events: list[dict[str, Any]] = field(default_factory=list)


async def run_lsr_norm_quality_loop(
    rows: Sequence[Mapping[str, Any]],
    *,
    analogues_in_money: bool = ANALOGUES_IN_MONEY_DEFAULT,
    max_research_rounds: int = MAX_RESEARCH_ROUNDS_PER_LOCATOR,
    verify: Any = None,
    repair_verification: Any = None,
    research: Any = None,
    evidence_chunks: Sequence[Any] = (),
    source_locators: Sequence[Any] | None = None,
    lookup_norm_card: Any = None,
) -> LsrQualityGateResult:
    """Verify in small packets, then optionally re-search. Callbacks own model/RAG I/O."""

    current = expand_norm_components([prepare_selection_row(row) for row in rows])
    provided_locators = [
        str(item).strip()
        for item in (source_locators or ())
        if str(item).strip() and not invented_source_row(item)
    ]
    parsed_locators = [
        str(row.get("_parent_locator") or row.get("source_row") or "").strip()
        for row in current
        if str(row.get("_parent_locator") or row.get("source_row") or "").strip()
        and not invented_source_row(row.get("_parent_locator") or row.get("source_row"))
    ]
    source_locators = provided_locators or list(dict.fromkeys(parsed_locators))
    work_locators = {
        str(row.get("source_row") or "").strip()
        for row in current
        if str(row.get("source_row") or "").strip() and not invented_source_row(row.get("source_row"))
    } | set(source_locators)
    events: list[dict[str, Any]] = []
    fingerprints: dict[str, list[str]] = {key: [] for key in work_locators}
    lookup = lookup_norm_card

    async def _verify_pending(pending: list[dict[str, Any]], round_index: int) -> None:
        nonlocal current, events
        if not pending:
            return
        to_verify, missing_cards = split_rows_missing_selected_card(
            pending, evidence_chunks, lookup_norm_card=lookup
        )
        if missing_cards:
            current = merge_quality_gated_rows(current, missing_cards)
            events.append(
                {"stage": "missing_selected_card", "round": round_index, "rows": len(missing_cards)}
            )
        if to_verify and verify is not None:
            for packet in verifier_packets(to_verify):
                raw = str(await verify(packet) or "")
                wanted = packet_locator_keys(packet)
                parsed_keys = parsed_quality_locator_keys(raw)
                if wanted and parsed_keys != wanted:
                    retry = str(
                        (await repair_verification(packet, raw))
                        if repair_verification is not None
                        else (await verify(packet))
                    )
                    retry_keys = parsed_quality_locator_keys(retry)
                    if len(retry_keys & wanted) >= len(parsed_keys & wanted):
                        raw = retry
                        parsed_keys = retry_keys
                    events.append(
                        {
                            "stage": "verify_format_retry",
                            "round": round_index,
                            "rows": len(packet),
                            "parsed": len(parsed_keys & wanted),
                        }
                    )
                verified = apply_verifier_table(
                    packet,
                    raw,
                    analogues_in_money=analogues_in_money,
                )
                current = merge_quality_gated_rows(current, verified)
                events.append(
                    {
                        "stage": "verify_unparsed" if not parsed_keys else "verify",
                        "round": round_index,
                        "rows": len(packet),
                        "parsed": len(parsed_keys & wanted),
                    }
                )

    for round_index in range(max(1, int(max_research_rounds))):
        await _verify_pending(
            [row for row in current if row_needs_verifier(row)],
            round_index,
        )
        pending_research = [row for row in current if row_needs_research(row)]
        if not pending_research:
            break
        next_rows: list[dict[str, Any]] = []
        still_open: list[dict[str, Any]] = []
        for row in pending_research:
            round_no = int(row.get("_research_round") or 0) + 1
            payload = dict(row)
            payload["_research_round"] = round_no
            if round_no >= max_research_rounds:
                next_rows.append(mark_research_exhausted(payload))
            else:
                still_open.append(payload)
        current = merge_quality_gated_rows(current, next_rows)
        if not still_open or research is None:
            current = merge_quality_gated_rows(
                current,
                [mark_research_exhausted(row) for row in still_open],
            )
            if still_open and research is None:
                events.append({"stage": "research_skipped", "rows": len(still_open)})
            break
        researched = await research(still_open, round_index + 1)
        prior_by_key = {
            str(row.get("source_row") or "").strip(): row
            for row in still_open
            if str(row.get("source_row") or "").strip()
        }
        queries = getattr(researched, "queries", ()) or ()
        card_ids = getattr(researched, "card_ids", ()) or ()
        new_rows: list[dict[str, Any]] = []
        for item in researched.rows if hasattr(researched, "rows") else researched:
            if not isinstance(item, Mapping):
                continue
            key = str(item.get("source_row") or "").strip()
            if key not in work_locators or invented_source_row(key):
                continue
            payload = prepare_selection_row(item)
            prior = prior_by_key.get(key) or {}
            payload = carry_evidence_refs(prior, payload)
            payload = carry_prior_norm_code(prior, payload)
            payload["_rejected_codes"] = rejected_norm_codes(prior)
            payload["_rejection_reasons"] = list(prior.get("_rejection_reasons") or [])
            for field in (
                "_last_rejection_status",
                "_last_rejected_code",
                "_last_rejection_message",
            ):
                if prior.get(field) not in (None, ""):
                    payload[field] = prior[field]
            payload["_research_round"] = int(prior.get("_research_round") or 0)
            payload["_rejected_repeats"] = int(prior.get("_rejected_repeats") or 0)
            if prior.get("_parent_locator"):
                payload["_parent_locator"] = prior.get("_parent_locator")
                payload["_component_id"] = prior.get("_component_id")
            new_rows.append(payload)
        replaced: list[dict[str, Any]] = []
        for row in new_rows:
            key = str(row.get("source_row") or "").strip()
            if code_was_rejected(row, row.get("norm_code")):
                repeats = int(row.get("_rejected_repeats") or 0) + 1
                row["_rejected_repeats"] = repeats
                row["quality_message"] = "шифр уже отклонён на этой строке"
                if repeats >= 2:
                    replaced.append(mark_research_exhausted(row))
                    continue
                row["norm_status"] = "NEEDS_RESEARCH"
                row["_quality_gate"] = "research"
                replaced.append(row)
                continue
            new_fp = locator_research_fingerprint(
                key, queries, row.get("norm_code"), card_ids
            )
            seen = fingerprints.setdefault(key, [])
            if not fingerprint_is_new(seen, new_fp):
                replaced.append(mark_research_exhausted(row))
                continue
            seen.append(new_fp)
            replaced.append(row)
        current = merge_quality_gated_rows(current, replaced)
        events.append(
            {
                "stage": "research",
                "round": round_index + 1,
                "rows": len(replaced),
            }
        )
    leftover = [
        row
        for row in current
        if not row_is_quality_terminal(row)
        and (
            canonicalize_norm_status(row.get("norm_status")) == "NEEDS_RESEARCH"
            or str(row.get("_quality_gate") or "") == "research"
            or int(row.get("_research_round") or 0) > 0
        )
    ]
    if leftover:
        hydrate = lookup or default_lookup_authored_norm_card
        retry: list[dict[str, Any]] = []
        exhaust: list[dict[str, Any]] = []
        for row in leftover:
            code = authored_norm_code(
                row.get("norm_code") or row.get("code") or row.get("basis")
            )
            store_card = None
            if code and not code_was_rejected(row, code) and not row.get("_research_exhausted"):
                try:
                    store_card = hydrate(code)
                except Exception:
                    store_card = None
            if isinstance(store_card, Mapping) and store_card:
                payload = dict(row)
                payload["norm_status"] = "UNVERIFIED"
                payload["_quality_gate"] = "unverified"
                retry.append(payload)
            else:
                exhaust.append(row)
        if retry and verify is not None:
            current = merge_quality_gated_rows(current, retry)
            events.append({"stage": "store_card_verify", "rows": len(retry)})
            await _verify_pending(retry, int(max_research_rounds))
            leftover = [
                row
                for row in current
                if not row_is_quality_terminal(row)
                and (
                    canonicalize_norm_status(row.get("norm_status")) == "NEEDS_RESEARCH"
                    or str(row.get("_quality_gate") or "") == "research"
                )
            ]
            exhaust.extend(leftover)
        if exhaust:
            current = merge_quality_gated_rows(
                current,
                [mark_research_exhausted(row) for row in exhaust],
            )
            events.append({"stage": "exhaust", "rows": len(exhaust)})
    current = collapse_norm_components(current)
    current = close_quality_coverage(source_locators, current)
    return LsrQualityGateResult(
        rows=current,
        norms_status=aggregate_norms_status(current),
        events=events,
    )


@dataclass
class LsrResearchRoundResult:
    rows: list[dict[str, Any]]
    queries: tuple[str, ...] = ()
    hit_ids: tuple[str, ...] = ()
    card_ids: tuple[str, ...] = ()
