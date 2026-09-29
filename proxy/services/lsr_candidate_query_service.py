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
    present* in the source: the governing section header of the sheet, the column
    header that names each bare figure («300» -> «300 [Кол-во]»), and a cipher
    written in a source cell.  No word is added.

Cells that carry no subject matter are left out of both: a service column (total,
cost, sum, item number) and a formula pointer («=АР!$G$111») are the noise § 2
names, while every plain text or numeric cell — size, composition, condition —
stays.  A row the catalog gives no cells for keeps its line verbatim, and the
report says which path ran.

Forbidden here, and checked mechanically by :func:`token_grounding_violations`:
inferring a technology, a demolition/mounting distinction, working conditions, a
volume, an applicability verdict, a coefficient or a professional status from the
text.  A query that contains any token which does not literally occur in its own
source rows is dropped, never repaired.

Both bounds a packet can hit — the number of queries and their total characters —
are technical and named per locator in ``report``, so a row whose candidate did not
fit stays «отложено» instead of becoming an invisible non-result.

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


def row_literal_text(row: Any) -> str:
    """Public form of the row's literal source text.

    Exported because query attribution has to compare a model's query against the
    same text the candidate author quotes; two copies of the locator-prefix rule
    would disagree about which row a query refers to.
    """

    return _row_text(row)


def _presented_cipher(row_text: str) -> str:
    match = _PRESENTED_CIPHER_RE.search(row_text)
    if match is None:
        return ""
    return str(match.group(1) or "").strip()


# Columns that carry no subject matter for a norm search: totals, money, numbering
# and the derived cost block.  Blocker § 2 asks for the row's relevant source text
# and its explicitly written characteristics, «а не строку с формулами итоговой
# стоимости и служебными колонками».  A cipher column is NOT here: a шифр written in
# the source is exactly the kind of characteristic a search needs.
_SERVICE_COLUMN_TERMS = (
    "итого",
    "стоимость",
    "сумма",
    "цена",
    "всего",
    "накладн",
    "сметн",
    "прибыл",
    "эксплуатационн",
    "п/п",
    "пп",
    "№",
    "номер",
    "ед. всего",
)


def _is_service_column(label: str) -> bool:
    folded = " ".join(str(label or "").casefold().split())
    if not folded:
        return False
    return any(term in folded for term in _SERVICE_COLUMN_TERMS)


def _cell_is_formula(cell: Any) -> bool:
    if str(getattr(cell, "data_type", "") or "").strip().casefold() == "f":
        return True
    return bool(str(getattr(cell, "formula", "") or "").strip())


def _cell_text(cell: Any) -> tuple[str, str]:
    """One cell's literal contribution: ``(text, why_it_was_dropped)``.

    A formula cell contributes its cached value when the workbook carries one and
    nothing when it does not.  The formula *text* is never a characteristic of the
    work: ``=АР!$G$111`` is a pointer inside the customer's own spreadsheet, and
    feeding it to a norm search is the noise § 2 names.  Dropping the pointer keeps
    every plain cell, so no size, composition or condition written in the source
    disappears with it.
    """

    display = " ".join(str(getattr(cell, "display_value", "") or "").split())
    if _cell_is_formula(cell):
        cached = getattr(cell, "cached_formula_value", None)
        if cached is None:
            return "", "formula_without_cached_value"
        text = " ".join(str(cached).split())
        return (text, "") if text else ("", "formula_without_cached_value")
    return display, ""


_QUANTITY_LIKE_RE = re.compile(r"\d")


def _is_quantity_like(text: str) -> bool:
    """A bare figure or size ("300", "12,5", "3x2.5"), not a wording.

    Such a cell states a characteristic without saying what it measures, so on the
    ``derived`` query it carries its column header: «300» alone cannot tell a norm
    search whether it is a quantity, a mass or a length.  A cell with letters is
    left verbatim — its own words already say what it is.
    """

    return bool(_QUANTITY_LIKE_RE.search(text)) and not any(
        "\u0431" <= character <= "\u04ff" for character in text.casefold()
    )


def _row_subject_texts(row: Any) -> tuple[str, str, dict[str, Any]]:
    """The row's source text two ways: verbatim, and with column headers bound.

    Returns ``(plain, labelled, counters)``.  ``plain`` joins the subject-matter
    cells; ``labelled`` annotates each quantity-like cell with the header that
    governs it, so «явные характеристики» reach the search as characteristics
    instead of as bare digits.  Both are made of source text only.

    Without cell metadata (a pasted source, a legacy catalog row) both are the
    catalog line verbatim: the filter must never quietly narrow a query the code
    cannot inspect, and ``counters["path"]`` says which path ran.
    """

    cells = tuple(getattr(row, "cells", ()) or ())
    counters: dict[str, Any] = {
        "cells_total": len(cells),
        "cells_dropped_service_column": 0,
        "cells_dropped_formula": 0,
        "cells_dropped_empty": 0,
        "path": "cells" if cells else "catalog_line",
        "labels": (),
    }
    if not cells:
        text = _row_text(row)
        return text, text, counters
    headers = {
        int(column): str(label)
        for column, label in (getattr(row, "column_headers", ()) or ())
    }
    plain_parts: list[str] = []
    labelled_parts: list[str] = []
    labels: list[str] = []
    for cell in cells:
        label = headers.get(int(getattr(cell, "column", -1) or -1), "")
        if _is_service_column(label):
            counters["cells_dropped_service_column"] += 1
            continue
        text, dropped = _cell_text(cell)
        if dropped:
            counters["cells_dropped_formula"] += 1
            continue
        if not text:
            counters["cells_dropped_empty"] += 1
            continue
        plain_parts.append(text)
        if label and _is_quantity_like(text):
            labelled_parts.append(f"{text} [{label}]")
            labels.append(label)
        else:
            labelled_parts.append(text)
    counters["labels"] = tuple(sorted(set(labels)))
    plain = " | ".join(plain_parts)
    return plain, " | ".join(labelled_parts), counters


def system_candidate_query_char_budget() -> int:
    """Character bound on the code-authored query set of one packet.

    A row dump of 900 characters is one query in the count cap and eight rows'
    worth of context in the packet.  § 2: «шум или длинные запросы не должны
    вытеснять кандидатов конкретной операции» -- so the budget is measured in
    characters as well as in queries, and what it defers is named.
    """

    try:
        return max(0, int(os.getenv("LES_LSR_SYSTEM_CANDIDATE_MAX_CHARS", "12000")))
    except ValueError:
        return 12000


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
    ``char_budget``, ``chars_used``, ``skipped_without_source_text``,
    ``deferred_by_cap``, ``deferred_by_char_budget``, ``dropped_ungrounded``,
    ``limit_reached`` and a ``source_text_filter`` block naming what the row text
    left out and why.  Every key is a reason a candidate did not reach the model;
    none of them is a statement about the norm.
    """

    limit = system_candidate_query_cap() if cap is None else max(0, int(cap))
    usable: list[CandidateQuery] = []
    dropped: list[CandidateQuery] = []
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
        return []
    char_budget = system_candidate_query_char_budget()
    seen_texts: set[str] = set()
    cell_counters = {
        "cells_total": 0,
        "cells_dropped_service_column": 0,
        "cells_dropped_formula": 0,
        "cells_dropped_empty": 0,
    }
    rows_with_cells = 0
    # Build every candidate per row first, then hand out the budget one candidate
    # per row at a time (every row's ``original`` before any row's ``derived``).
    # The previous order filled the cap with row 1's pair, row 2's pair, ... so a
    # cap of 24 gave six rows two candidates and left thirty-four rows with none:
    # § 2, «шум или длинные запросы не должны вытеснять кандидатов конкретной
    # операции».  A query that does not fit the character budget is deferred and
    # the rest of the rows still get theirs -- a 900-character row dump can no
    # longer starve the short rows behind it.
    entries: list[list[CandidateQuery]] = []
    for row in rows:
        plain, labelled, counters = _row_subject_texts(row)
        for key in cell_counters:
            cell_counters[key] += int(counters.get(key) or 0)
        if counters["path"] == "cells":
            rows_with_cells += 1
        locator = str(getattr(row, "locator", "") or "").strip()
        if not plain:
            if locator:
                skipped.append(locator)
            continue
        row_sheet = str(getattr(row, "sheet", "") or sheet or "").strip()
        section = _sheet_section(row)
        # The only literals this function may quote: the row's own cell text, the
        # section header written above it in the same sheet, and the column headers
        # governing its cells.  Grounding every authored query against exactly
        # those keeps the check able to fail — a query that quotes anything else,
        # including a word this module thought up, is caught instead of passing by
        # construction.
        labels = tuple(counters.get("labels") or ())
        literals = " ".join(part for part in (plain, labelled, section, *labels) if part)
        fields = [plain]
        if labelled and labelled != plain:
            fields.append(labelled)
        if section:
            fields.append(section)
        cipher = _presented_cipher(plain)
        if cipher:
            # Literal extraction of a cipher the source cell already states; the
            # fragment is a substring of ``plain``, so it adds no new vocabulary.
            fields.append(cipher)
        row_queries: list[CandidateQuery] = []
        # ``original`` is the bare row text; ``derived`` adds only the explicitly
        # presented column headers, section header and cipher -- never a word from
        # outside the row.
        for provenance, candidate in (("original", plain), ("derived", labelled)):
            if provenance == "original":
                folded = " ".join(candidate.casefold().split())
            else:
                extras = [part for part in (section, cipher) if part]
                candidate = " | ".join([candidate, *extras] if extras else [candidate])
                folded = " ".join(candidate.casefold().split())
            if not folded or folded in seen_texts:
                continue
            violations = token_grounding_violations(candidate, literals)
            if violations:
                # ADR-16: a query that says something the source does not say is
                # dropped, and the drop is visible instead of being "fixed".
                seen_texts.add(folded)
                dropped.append(
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
            if provenance == "derived" and folded == " ".join(plain.casefold().split()):
                continue
            # An identical query text authored for another row is the same query:
            # it is added once, and the row behind it is not "deferred" -- the
            # model already has its text.
            seen_texts.add(folded)
            row_queries.append(
                CandidateQuery(
                    text=candidate,
                    locator=locator,
                    provenance=provenance,
                    sheet=row_sheet,
                    source_fields=tuple(fields),
                )
            )
        if row_queries:
            entries.append(row_queries)
    deferred_by_chars: list[str] = []
    count_exhausted = False
    chars_used = 0
    for rank in range(max((len(entry) for entry in entries), default=0)):
        for entry in entries:
            if rank >= len(entry) or entry[rank] is None:
                continue
            item = entry[rank]
            if len(usable) >= limit:
                count_exhausted = True
                break
            if char_budget and chars_used + len(item.text) > char_budget:
                # Deferred, named, and never retried: the budget is the reason this
                # row's candidate is not in front of the model, not a missing norm.
                deferred_by_chars.append(item.locator)
                continue
            usable.append(item)
            chars_used += len(item.text)
            entry[rank] = None
        if count_exhausted:
            break
    authored_locators = {item.locator for item in usable if item.locator}
    deferred.extend(
        item.locator
        for entry in entries
        for item in entry
        if item is not None and item.locator and item.locator not in authored_locators
    )
    deferred = sorted({item for item in deferred if item})
    _fill_report(
        report,
        authored=len(usable),
        cap=limit,
        skipped=skipped,
        deferred=deferred,
        limit_reached=count_exhausted or bool(deferred_by_chars),
        dropped_ungrounded=len(dropped),
        char_budget=char_budget,
        chars_used=chars_used,
        deferred_by_char_budget=sorted(set(deferred_by_chars)),
        rows_with_cell_metadata=rows_with_cells,
        rows_in_packet=len(list(rows)),
        cells_total=cell_counters["cells_total"],
        cells_dropped_service_column=cell_counters["cells_dropped_service_column"],
        cells_dropped_formula=cell_counters["cells_dropped_formula"],
        cells_dropped_empty=cell_counters["cells_dropped_empty"],
        candidates_available=sum(len(entry) for entry in entries) + len(dropped),
    )
    return [*usable, *dropped]


def _fill_report(
    report: dict[str, Any] | None,
    *,
    authored: int,
    cap: int,
    skipped: Sequence[str],
    deferred: Sequence[str],
    limit_reached: bool = False,
    dropped_ungrounded: int = 0,
    char_budget: int = 0,
    chars_used: int = 0,
    deferred_by_char_budget: Sequence[str] = (),
    rows_with_cell_metadata: int = 0,
    rows_in_packet: int = 0,
    cells_total: int = 0,
    cells_dropped_service_column: int = 0,
    cells_dropped_formula: int = 0,
    cells_dropped_empty: int = 0,
    candidates_available: int = 0,
) -> None:
    if report is None:
        return
    report["authored"] = int(authored)
    report["cap"] = int(cap)
    report["skipped_without_source_text"] = list(skipped)
    report["deferred_by_cap"] = list(deferred)
    report["limit_reached"] = bool(limit_reached)
    # Every bound that changed what the model saw is named by its own key: a
    # bounded pass has to stay readable as «отложено», and § 2 asks separately for
    # what the source-text filter removed so a dropped total can never be read as
    # a dropped work item.
    report["dropped_ungrounded"] = int(dropped_ungrounded)
    report["char_budget"] = int(char_budget)
    report["chars_used"] = int(chars_used)
    report["deferred_by_char_budget"] = list(deferred_by_char_budget)
    report["source_text_filter"] = {
        "rows_in_packet": int(rows_in_packet),
        "rows_with_cell_metadata": int(rows_with_cell_metadata),
        "cells_total": int(cells_total),
        "cells_dropped_service_column": int(cells_dropped_service_column),
        "cells_dropped_formula": int(cells_dropped_formula),
        "cells_dropped_empty": int(cells_dropped_empty),
        "candidates_available": int(candidates_available),
    }


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
    "row_literal_text",
    "system_candidate_query_cap",
    "system_candidate_queries_enabled",
    "token_grounding_violations",
]
