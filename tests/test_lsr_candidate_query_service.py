"""ADR-16: code-authored candidate retrieval stays literal, tagged and bounded.

These are the mechanical guarantees behind
``docs/ADR-16-systematic-candidate-retrieval.md``: a system query may only say what
the source row already says, every query keeps its provenance, a query that would
invent semantics is dropped instead of repaired, and the model's own queries are
never replaced.
"""
from __future__ import annotations

from proxy.services.attachment_source_catalog_service import CatalogRow
from proxy.services.lsr_candidate_query_service import (
    CandidateQuery,
    candidate_queries_enabled_for_turn,
    candidate_queries_for_packet,
    candidate_queries_for_rows,
    candidate_query_trace,
    dropped_ungrounded_queries,
    merge_candidate_queries,
    system_candidate_queries_enabled,
    token_grounding_violations,
)


def _row(
    locator: str = "СКС!R12",
    line: str = "Прокладка кабеля NYM 3x2.5 в трубе ПНД",
    *,
    sheet: str = "СКС",
    section: str = "",
) -> CatalogRow:
    return CatalogRow(
        locator=locator,
        sheet=sheet,
        excel_row=12,
        values=(line,),
        line=f"{locator}: {line}",
        numbers=(),
        section_context=section,
    )


def test_original_query_is_the_literal_row_text() -> None:
    queries = candidate_queries_for_rows([_row()], cap=10)
    original = [item for item in queries if item.provenance == "original"]
    assert [item.text for item in original] == [
        "Прокладка кабеля NYM 3x2.5 в трубе ПНД"
    ]
    assert original[0].locator == "СКС!R12"
    assert original[0].sheet == "СКС"


def test_derived_query_adds_only_explicitly_presented_attributes() -> None:
    row = _row(section="Раздел 4. Наружные сети")
    derived = [
        item
        for item in candidate_queries_for_rows([row], cap=10)
        if item.provenance == "derived"
    ]
    assert len(derived) == 1
    # The section header is literally written above the row, so it may be added;
    # no other word may appear.
    assert derived[0].text.startswith("Прокладка кабеля NYM 3x2.5 в трубе ПНД | ")
    assert "Раздел 4. Наружные сети" in derived[0].text
    assert token_grounding_violations(derived[0].text, " | ".join(derived[0].source_fields)) == ()


def test_derived_query_collapses_when_source_states_no_extra_attribute() -> None:
    queries = candidate_queries_for_rows([_row()], cap=10)
    # No section, no cipher -> "derived" would repeat "original" exactly, so it is
    # not duplicated as a second query.
    assert [item.provenance for item in queries] == ["original"]


def test_cipher_written_in_the_source_is_carried_but_never_invented() -> None:
    row = _row(line='Установка лотка, шифр: ГЭСН17-01-010-02')
    derived = [
        item
        for item in candidate_queries_for_rows([row], cap=10)
        if item.provenance == "derived"
    ]
    assert "ГЭСН17-01-010-02" in derived[0].text
    # Reading a cipher the source states is extraction; a cipher the source does
    # not state can never appear.
    other = candidate_queries_for_rows([_row(line="Установка лотка металлического")], cap=10)
    assert all("ГЭСН" not in item.text for item in other)


def test_invented_token_drops_the_query_and_stays_visible(monkeypatch) -> None:
    # A row whose text is only reachable by adding a word the source never uses
    # must not produce that query; the drop is reported, not silently skipped.
    row = _row(line="Разделка кабеля", section="Силовые линии")
    queries = candidate_queries_for_rows([row], cap=10)
    for item in queries:
        assert token_grounding_violations(item.text, " | ".join(item.source_fields)) == ()
    poisoned = CandidateQuery(
        text="Разделка кабеля демонтаж",
        locator="СКС!R1",
        provenance="derived",
        sheet="СКС",
        source_fields=("Разделка кабеля | Силовые линии",),
        ungrounded_tokens=("демонтаж",),
    )
    assert [dropped["ungrounded_tokens"] for dropped in dropped_ungrounded_queries([poisoned])] == [
        ["демонтаж"]
    ]
    assert merge_candidate_queries([], [poisoned]) == []


def test_model_query_is_never_replaced_and_exact_duplicates_merge() -> None:
    rows = [_row(locator="СКС!R1", line="Монтаж шкафа"), _row(locator="СКС!R2", line="Монтаж шкафа")]
    queries = candidate_queries_for_rows(rows, cap=10)
    texts = [item.text for item in queries]
    assert texts.count("Монтаж шкафа") == 1
    model_same = merge_candidate_queries(["Монтаж шкафа"], queries)
    assert all(item.text != "Монтаж шкафа" for item in model_same)
    # A differently worded query survives: deciding that two wordings are the same
    # query is a professional judgement code is not allowed to make.
    near = merge_candidate_queries(["Монтаж шкаф"], queries)
    assert [item.text for item in near] == ["Монтаж шкафа"]


def test_cap_is_a_technical_bound_not_a_missing_norm() -> None:
    rows = [
        _row(locator=f"СКС!R{index}", line=f"Монтаж элемента {index}")
        for index in range(1, 30)
    ]
    queries = candidate_queries_for_rows(rows, cap=4)
    assert len(queries) == 4
    assert rows[3].locator  # the row itself is untouched: only the query is deferred


def test_packet_resolves_locators_from_the_catalog() -> None:
    class _Catalog:
        rows = (_row(locator="СКС!R7", line="Установка розетки"),)

    queries = candidate_queries_for_packet(_Catalog(), sheet="СКС", locators=["СКС!R7"])
    assert [item.text for item in queries] == ["Установка розетки"]
    assert candidate_queries_for_packet(_Catalog(), sheet="СКС", locators=["СКС!R99"]) == []
    assert candidate_queries_for_packet(None, sheet="СКС", locators=["СКС!R7"]) == []
    assert candidate_queries_for_packet(_Catalog(), sheet="СКС", locators=[]) == []


def test_scope_is_the_estimator_turn_only() -> None:
    assert candidate_queries_enabled_for_turn({"mode": "estimator"}) is True
    assert candidate_queries_enabled_for_turn({"mode": "agent"}) is False
    assert candidate_queries_enabled_for_turn(None) is False
    assert candidate_queries_enabled_for_turn({"mode": "ESTIMATOR"}) is (
        system_candidate_queries_enabled()
    )


def test_trace_records_provenance_text_and_source_row() -> None:
    queries = candidate_queries_for_rows([_row(section="Раздел 2")], cap=10)
    rows = candidate_query_trace(queries)
    assert {item["query_provenance"] for item in rows} == {"original", "derived"}
    for item in rows:
        assert item["query_text"]
        assert item["source_row"] == "СКС!R12"
        assert item["sheet"] == "СКС"
        assert item["ungrounded_tokens"] == []


def test_empty_row_text_produces_no_query_and_is_not_erased() -> None:
    queries = candidate_queries_for_rows([_row(line="")], cap=10)
    assert queries == []


def test_grounding_compares_a_query_against_the_literals_it_may_quote() -> None:
    """The literalness check measures vocabulary, so it can actually fail.

    The derived query adds the section header, therefore its extra words are
    grounded only while the section is passed as a literal.  Widen or narrow the
    literals and the same query is judged differently — which is exactly what
    keeps ADR-16 § 6 from being a tautology inside ``candidate_queries_for_rows``.
    """

    row = _row(section="Раздел 4. Наружные сети")
    queries = candidate_queries_for_rows([row], cap=10)
    derived = next(item for item in queries if item.provenance == "derived")
    text = "Прокладка кабеля NYM 3x2.5 в трубе ПНД"

    assert token_grounding_violations(derived.text, f"{text} {row.section_context}") == ()
    invented = token_grounding_violations(derived.text, text)
    assert set(invented) & {"Раздел", "Наружные", "сети"}


def test_report_names_the_rows_the_cap_deferred() -> None:
    rows = [
        _row(locator=f"СКС!R{index}", line=f"Монтаж элемента {index}")
        for index in range(1, 30)
    ]
    report: dict = {}
    queries = candidate_queries_for_rows(rows, cap=3, report=report)

    assert len(queries) == 3
    assert report["authored"] == 3 and report["cap"] == 3
    assert report["limit_reached"] is True
    # a bounded pass is an interruption, not a verdict: every untouched row lives
    deferred = report["deferred_by_cap"]
    assert deferred and rows[-1].locator in deferred
    assert not (set(deferred) & {item.locator for item in queries})


def test_report_names_rows_without_literal_text_and_rows_absent_from_the_catalog() -> None:
    class _Catalog:
        rows = (_row(locator="СКС!R7", line="Установка розетки"),)

    empty_report: dict = {}
    assert candidate_queries_for_rows([_row(locator="СКС!R8", line="")], cap=10, report=empty_report) == []
    assert empty_report["skipped_without_source_text"] == ["СКС!R8"]

    packet_report: dict = {}
    queries = candidate_queries_for_packet(
        _Catalog(), sheet="СКС", locators=["СКС!R7", "СКС!R404"], report=packet_report
    )
    assert [item.text for item in queries] == ["Установка розетки"]
    assert packet_report["not_in_source_catalog"] == ["СКС!R404"]


def test_disabled_switch_defers_the_whole_packet_instead_of_dropping_it() -> None:
    rows = [_row(locator="СКС!R1", line="Монтаж шкафа")]
    report: dict = {}
    assert candidate_queries_for_rows(rows, cap=0, report=report) == []
    assert report["deferred_by_cap"] == ["СКС!R1"]
    assert report["authored"] == 0
