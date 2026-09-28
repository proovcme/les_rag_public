"""Systematic candidate retrieval queries for the estimator sheet-pass (ADR-16).

Division of labour fixed by ``docs/ADR-16-systematic-candidate-retrieval.md``:
code guarantees systematic candidate *collection*, the model decides which norm
applies, and the user supplies genuinely missing data.  This module owns the only
place where a retrieval query may be authored by code in the active estimate path.

Two provenances are produced here and nowhere else:

``original``
    the complete literal source text of one catalog row, unshortened and
    unparaphrased.  It is a safety net and never replaces the model's own query.
``derived``
    the same literal source text plus only the attributes that are *explicitly
    present* in the source: the governing section header of the sheet and a cipher
    written in a source cell.  No word is added.

Forbidden here, and checked mechanically by :func:`token_grounding_violations`:
inferring a technology, a demolition/mounting distinction, working conditions, a
volume, an applicability verdict, a coefficient or a professional status from the
text.  A query that contains any token which does not literally occur in its own
source rows is dropped, never repaired.

Output is consumed by the same read-only ``search_sources`` tool against the same
shared named ``dense + bm25_sparse`` collection with native RRF, so no parallel
index, boost or case-specific corpus can exist on this path.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

# Explicitly-present cipher, e.g. "Шифр: ГЭСН17-01-010-02".  Reading a cipher that
# a source cell already states is literal extraction (ADR-16 §6); it never
# *chooses* a norm and never synthesises one.
_PRESENTED_CIPHER_RE = re.compile(
    r"(?:шифр|обоснование|норм[аы]?\s+шифр)\s*[:=\-]\s*([А-Яа-яA-Za-z0-9][\w./-]{3,})",
    re.IGNORECASE,
)
_TOKEN_SPLIT_RE = re.compile(r"[^\w\u0400-\u04ff]+")
_MIN_GROUNDED_TOKEN_CHARS = 4


def system_candidate_queries_enabled() -> bool:
    """GUI-visible switch; ``on`` by default, see ``_FACTOR_PRESENTATION``."""

    raw = os.getenv("LES_LSR_SYSTEM_CANDIDATE_QUERIES", "on").strip().casefold()
    return raw not in {"0", "off", "false", "no", "disabled"}


def system_candidate_query_cap() -> int:
    """Technical bound on how many code-authored queries one packet may add."""

    try:
        return max(0, int(os.getenv("LES_LSR_SYSTEM_CANDIDATE_MAX", "24")))
    except ValueError:
        return 24


@dataclass(frozen=True)
class CandidateQuery:
    """One code-authored retrieval query with its full grounding."""

    text: str
    locator: str
    provenance: str  # "original" | "derived"
    sheet: str
    source_fields: tuple[str, ...]
    ungrounded_tokens: tuple[str, ...] = ()

    def as_trace_dict(self) -> dict[str, Any]:
        return {
            "query_provenance": self.provenance,
            "query_text": self.text,
            "source_row": self.locator,
            "sheet": self.sheet,
            "source_fields": list(self.source_fields),
            "ungrounded_tokens": list(self.ungrounded_tokens),
        }


def _row_text(row: Any) -> str:
    """Literal source text of a catalog row, with its own locator prefix removed.

    The catalog stamps every row line as ``"<locator>: <cell> | <cell> | ..."``
    (``attachment_source_catalog_service``); the address is navigation, not source
    text, so it is stripped exactly and the cell text is kept verbatim.
    """

    line = str(getattr(row, "line", "") or "").strip()
    locator = str(getattr(row, "locator", "") or "").strip()
    if locator:
        for prefix in (f"{locator}: ", f"{locator}:"):
            if line.startswith(prefix):
                line = line[len(prefix) :]
                break
        else:
            line = "" if line == locator else line
    # Leading/trailing cell separators come from the catalog join, not from the
    # source cells themselves.
    return " ".join(line.split()).strip(" :|")


def _presented_cipher(row_text: str) -> str:
    match = _PRESENTED_CIPHER_RE.search(row_text)
    if match is None:
        return ""
    return str(match.group(1) or "").strip()


def token_grounding_violations(query: str, ground_truth: str) -> tuple[str, ...]:
    """Tokens of ``query`` that do not literally occur in ``ground_truth``.

    Case- and punctuation-insensitive.  A token is a word run; short function
    words and numbers are exempt because they carry no invented subject matter.
    Any non-empty result means the query says something the source does not.
    """

    haystack = " ".join(str(ground_truth or "").casefold().split())
    violations: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN_SPLIT_RE.split(str(query or "")):
        folded = token.casefold()
        if len(folded) < _MIN_GROUNDED_TOKEN_CHARS or folded in seen:
            continue
        seen.add(folded)
        if folded not in haystack:
            violations.append(token)
    return tuple(violations)


def _sheet_section(row: Any) -> str:
    """Section header literally written above the row in the same sheet."""

    return " ".join(str(getattr(row, "section_context", "") or "").split())


def candidate_queries_for_rows(
    rows: Sequence[Any],
    *,
    sheet: str = "",
    cap: int | None = None,
    report: dict[str, Any] | None = None,
) -> list[CandidateQuery]:
    """Build the grounded ``original``/``derived`` query set for one packet.

    ``rows`` are catalog rows (``CatalogRow``-like: ``locator``, ``line``,
    ``sheet``, ``section_context``).  Rows without literal text are skipped: an
    empty query is not a candidate.  Nothing is invented for them and they are not
    removed from the completeness denominator by this function — ``report`` names
    every such locator, plus the ones the technical cap deferred, so a bounded
    pass stays visible as «отложено» instead of becoming an invisible non-result.

    ``report`` (optional, mutated) accumulates: ``authored``, ``cap``,
    ``skipped_without_source_text``, ``deferred_by_cap``, ``limit_reached``.
    """

    limit = system_candidate_query_cap() if cap is None else max(0, int(cap))
    queries: list[CandidateQuery] = []
    skipped: list[str] = []
    deferred: list[str] = []
    if limit <= 0:
        _fill_report(
            report,
            authored=0,
            cap=limit,
            skipped=skipped,
            deferred=sorted(
                {
                    str(getattr(row, "locator", "") or "").strip()
                    for row in rows
                }
                - {""}
            ),
            limit_reached=True,
        )
        return queries
    seen_texts: set[str] = set()
    exhausted_at = -1
    for index, row in enumerate(rows):
        text = _row_text(row)
        locator = str(getattr(row, "locator", "") or "").strip()
        if not text:
            if locator:
                skipped.append(locator)
            continue
        row_sheet = str(getattr(row, "sheet", "") or sheet or "").strip()
        section = _sheet_section(row)
        # The only literals this function may quote: the row's own cell text and
        # the section header written above it in the same sheet.  Grounding every
        # authored query against exactly those two keeps the check able to fail —
        # a query that quotes anything else, including a word this module thought
        # up, is caught instead of passing by construction.
        literals = " ".join(part for part in (text, section) if part)
        fields = [text]
        if section:
            fields.append(section)
        cipher = _presented_cipher(text)
        if cipher:
            # Literal extraction of a cipher the source cell already states; the
            # fragment is a substring of ``text``, so it adds no new vocabulary.
            fields.append(cipher)
        # ``original`` is the bare row text; ``derived`` adds only the explicitly
        # presented section header and cipher, never a word from outside the row.
        for provenance, candidate in (
            ("original", text),
            ("derived", " | ".join(fields)),
        ):
            folded = " ".join(candidate.casefold().split())
            if not folded or folded in seen_texts:
                continue
            violations = token_grounding_violations(candidate, literals)
            if violations:
                # ADR-16: a query that says something the source does not say is
                # dropped, and the drop is visible instead of being "fixed".
                queries.append(
                    CandidateQuery(
                        text=candidate,
                        locator=locator,
                        provenance=provenance,
                        sheet=row_sheet,
                        source_fields=tuple(fields),
                        ungrounded_tokens=violations,
                    )
                )
                continue
            if provenance == "derived" and folded == " ".join(text.casefold().split()):
                continue
            if len(queries) >= limit:
                exhausted_at = index
                break
            seen_texts.add(folded)
            queries.append(
                CandidateQuery(
                    text=candidate,
                    locator=locator,
                    provenance=provenance,
                    sheet=row_sheet,
                    source_fields=tuple(fields),
                )
            )
        if exhausted_at >= 0:
            break
    if exhausted_at >= 0:
        authored_locators = {item.locator for item in queries if item.locator}
        deferred.extend(
            str(getattr(row, "locator", "") or "").strip()
            for row in list(rows)[exhausted_at:]
            if str(getattr(row, "locator", "") or "").strip() not in authored_locators
        )
        deferred = sorted({item for item in deferred if item})
    _fill_report(
        report,
        authored=len(queries),
        cap=limit,
        skipped=skipped,
        deferred=sorted(set(deferred)),
        limit_reached=exhausted_at >= 0,
    )
    return queries


def _fill_report(
    report: dict[str, Any] | None,
    *,
    authored: int,
    cap: int,
    skipped: Sequence[str],
    deferred: Sequence[str],
    limit_reached: bool = False,
) -> None:
    if report is None:
        return
    report["authored"] = int(authored)
    report["cap"] = int(cap)
    report["skipped_without_source_text"] = list(skipped)
    report["deferred_by_cap"] = list(deferred)
    report["limit_reached"] = bool(limit_reached)


def candidate_queries_for_packet(
    catalog: Any,
    *,
    sheet: str,
    locators: Sequence[str],
    cap: int | None = None,
    report: dict[str, Any] | None = None,
) -> list[CandidateQuery]:
    """Packet-scoped candidate queries resolved from the exact source catalog.

    A packet locator the catalog does not carry is recorded in ``report`` rather
    than passed over: an unqueryable row is a visible fact, not a silent gap.
    """

    if catalog is None:
        return []
    wanted = [str(item).strip() for item in locators if str(item).strip()]
    if not wanted:
        return []
    by_locator: dict[str, Any] = {}
    for row in getattr(catalog, "rows", ()) or ():
        locator = str(getattr(row, "locator", "") or "").strip()
        if locator and locator not in by_locator:
            by_locator[locator] = row
    absent = [locator for locator in wanted if locator not in by_locator]
    rows = [by_locator[locator] for locator in wanted if locator in by_locator]
    queries = candidate_queries_for_rows(rows, sheet=sheet, cap=cap, report=report)
    if report is not None and absent:
        report["not_in_source_catalog"] = absent
    return queries


def merge_candidate_queries(
    executed_queries: Sequence[str],
    candidates: Sequence[CandidateQuery],
) -> list[CandidateQuery]:
    """Drop candidates whose text the model already authored.

    Comparison is exact after whitespace/case folding: a near-duplicate stays,
    because deciding that two differently worded queries are the same query is
    itself a professional judgement the code is not allowed to make.
    """

    already = {" ".join(str(query or "").casefold().split()) for query in executed_queries}
    merged: list[CandidateQuery] = []
    for candidate in candidates:
        if candidate.ungrounded_tokens:
            continue
        folded = " ".join(candidate.text.casefold().split())
        if folded in already:
            continue
        already.add(folded)
        merged.append(candidate)
    return merged


def candidate_query_trace(candidates: Sequence[CandidateQuery]) -> list[dict[str, Any]]:
    """Serializable trace rows recording provenance and dropped-ungrounded queries."""

    return [candidate.as_trace_dict() for candidate in candidates]


def dropped_ungrounded_queries(
    candidates: Sequence[CandidateQuery],
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.ungrounded_tokens:
            payload.append(
                {
                    "query_provenance": candidate.provenance,
                    "query_text": candidate.text,
                    "source_row": candidate.locator,
                    "sheet": candidate.sheet,
                    "reason": "query_token_not_in_source",
                    "ungrounded_tokens": list(candidate.ungrounded_tokens),
                }
            )
    return payload


def candidate_queries_enabled_for_turn(
    profile_snapshot: Mapping[str, Any] | None,
) -> bool:
    """Only the estimate path gets code-authored candidates (ADR-16 scope)."""

    snapshot = profile_snapshot if isinstance(profile_snapshot, Mapping) else {}
    mode = str(snapshot.get("mode") or "").strip().casefold()
    return mode == "estimator" and system_candidate_queries_enabled()


__all__ = [
    "CandidateQuery",
    "candidate_queries_enabled_for_turn",
    "candidate_queries_for_packet",
    "candidate_queries_for_rows",
    "candidate_query_trace",
    "dropped_ungrounded_queries",
    "merge_candidate_queries",
    "system_candidate_query_cap",
    "system_candidate_queries_enabled",
    "token_grounding_violations",
]
