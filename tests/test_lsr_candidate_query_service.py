"""ADR-16: code-authored candidate retrieval stays literal, tagged and bounded.

These are the mechanical guarantees behind
``docs/ADR-16-systematic-candidate-retrieval.md``: a system query may only say what
the source row already says, every query keeps its provenance, a query that would
invent semantics is dropped instead of repaired, and the model's own queries are
never replaced.

Blocker § 2 added two further guarantees measured here: a system query carries the
row's relevant source text and its explicitly written characteristics — not the
workbook's totals, service columns and formula pointers — and neither the query cap
nor the character budget may let one long row dump displace the candidates of the
other operations in the packet.
"""
from __future__ import annotations

import pytest

from proxy.services.attachment_source_catalog_service import (
    CatalogCell,
    CatalogRow,
)
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


def _row_with_headers(
    pairs: tuple[tuple[str, str], ...],
    **kwargs: object,
) -> CatalogRow:
    """Build a row exactly as ``_bind_column_headers`` leaves it.

    Each pair is ``(governing header label, cell text)``.  A formula cell is
    written ``"=POINTER|cached value"`` so the fixture states both the pointer the
    workbook holds and the value cached for it.
    """

    cells: list[CatalogCell] = []
    headers: dict[int, str] = {}
    for index, (label, value) in enumerate(pairs, 1):
        headers[index] = label
        formula = ""
        cached: object = None
        display = value
        if value.startswith("=") and "|" in value:
            formula, cached_text = value.split("|", 1)
            display = formula
            cached = cached_text
        letter = chr(ord("A") + index - 1)
        cells.append(
            CatalogCell(
                coordinate=f"{letter}12",
                column=index,
                raw_value=cached if formula else display,
                display_value=display,
                data_type="f" if formula else "s",
                number_format="",
                formula=formula,
                cached_formula_value=cached,
            )
        )
    locator = str(kwargs.pop("locator", "СКС!R12"))
    line = " | ".join(
        f"{cell.display_value} [{headers[cell.column]}]" if headers.get(cell.column)
        else cell.display_value
        for cell in cells
    )
    return CatalogRow(
        locator=locator,
        sheet=str(kwargs.pop("sheet", "СКС")),
        excel_row=12,
        values=tuple(cell.display_value for cell in cells),
        line=f"{locator}: {line}",
        numbers=(),
        cells=tuple(cells),
        column_headers=tuple(sorted(headers.items())),
        section_context=str(kwargs.pop("section", "")),
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


# ---------------------------------------------------------------- blocker § 2 R5


def _vor_row(locator: str = "СКС!R12", **kwargs: object) -> CatalogRow:
    """One row of a real ВОР layout: numbering, name, unit, quantity, totals."""

    return _row_with_headers(
        (
            ("№ п/п", "7"),
            ("Наименование работ", "Прокладка кабеля NYM 3x2.5 в трубе ПНД"),
            ("Ед. изм.", "м"),
            ("Кол-во", "300"),
            ("Стоимость, руб. итого", "=АР!$G$111|125000"),
            ("Масса, т", "0,42"),
        ),
        locator=locator,
        **kwargs,
    )


def test_service_columns_and_formula_pointers_never_enter_a_system_query() -> None:
    """§ 2: «релевантный исходный текст и явные характеристики, а не строку с
    формулами итоговой стоимости и служебными колонками»."""

    queries = candidate_queries_for_rows([_vor_row()], cap=10)
    assert queries
    for item in queries:
        assert "АР!" not in item.text  # the pointer itself, never its text
        assert "125000" not in item.text  # the total, in any form
        assert "Итого" not in item.text.casefold()
        assert "Стоимость" not in item.text
        # what the search needs stays: the wording, the size and the unit.
        assert "Прокладка кабеля NYM 3x2.5 в трубе ПНД" in item.text
        assert "300" in item.text
        assert "м" in item.text
    report: dict = {}
    candidate_queries_for_rows([_vor_row()], cap=10, report=report)
    filtered = report["source_text_filter"]
    # Two service columns in the row: the running number and the cost total.
    assert filtered["cells_dropped_service_column"] == 2
    assert filtered["cells_dropped_formula"] == 0
    assert filtered["cells_total"] == 6


def test_soil_group_and_method_survive_the_numbering_column_filter() -> None:
    row = _row_with_headers((
        ("Наименование работ", "Разработка грунта"),
        ("Группа грунта", "2"),
        ("Способ производства", "вручную"),
        ("№ п/п", "17"),
    ))
    report: dict = {}
    queries = candidate_queries_for_rows([row], cap=10, report=report)
    assert [item.text for item in queries if item.provenance == "original"] == [
        "Разработка грунта | 2 | вручную"
    ]
    derived = next(item for item in queries if item.provenance == "derived")
    assert derived.text == "Разработка грунта | 2 [Группа грунта] | вручную"
    assert token_grounding_violations(derived.text, " ".join(derived.source_fields)) == ()
    assert report["source_text_filter"]["cells_dropped_service_column"] == 1


@pytest.mark.parametrize("header, value, labelled", [
    ("Сметный шифр", "ГЭСН01-01-001-01", False),
    ("Суммарная масса", "0,75", True),
    ("Эксплуатационные условия", "во влажном помещении", False),
    ("Количество всего", "12", True),
    ("Номер кабеля", "24", True),
])
def test_attribute_headers_do_not_become_service_columns_by_substring(
    header, value, labelled,
) -> None:
    row = _row_with_headers((
        ("Наименование", "Монтаж элемента"), (header, value),
        ("Стоимость, руб. итого", "999123"),
    ))
    report: dict = {}
    queries = candidate_queries_for_rows([row], cap=10, report=report)
    assert [item.text for item in queries if item.provenance == "original"] == [
        f"Монтаж элемента | {value}"
    ]
    assert all("999123" not in item.text for item in queries)
    if labelled:
        derived = next(item for item in queries if item.provenance == "derived")
        assert derived.text == f"Монтаж элемента | {value} [{header}]"
    assert report["source_text_filter"]["cells_dropped_service_column"] == 1
    assert all(token_grounding_violations(item.text, " ".join(item.source_fields)) == ()
               for item in queries)


@pytest.mark.parametrize("header", [
    "№ п/п", "п/п", "ПП", "Номер", "№ позиции", "Порядковый номер",
    "Цена за единицу", "Стоимость монтажа", "Сметная сумма",
    "Сметная прибыль", "Накладные расходы", "Эксплуатационные расходы",
    "Материал (итого), руб. без НДС", "Итого", "Всего",
])
def test_explicit_cost_and_ordinal_headers_still_do_not_enter_queries(header) -> None:
    row = _row_with_headers((("Наименование", "Монтаж элемента"), (header, "999123")))
    report: dict = {}
    queries = candidate_queries_for_rows([row], cap=10, report=report)
    assert [item.text for item in queries] == ["Монтаж элемента"]
    assert report["source_text_filter"]["cells_dropped_service_column"] == 1


def test_an_unresolved_formula_pointer_drops_only_itself() -> None:
    """A cached value survives as a figure; an unresolvable pointer leaves nothing.

    Neither case may reach the model as ``=АР!$G$111``: that string points inside
    the customer's own workbook and carries no subject matter for a norm search.
    """

    resolved = _row_with_headers(
        (("Наименование", "Сборка щита"), ("Кол-во", "=АР!$G$111|12"))
    )
    unresolved = _row_with_headers(
        (("Наименование", "Сборка щита"), ("Кол-во", "=АР!$G$112|"))
    )
    assert [
        item.text for item in candidate_queries_for_rows([resolved], cap=10)
        if item.provenance == "original"
    ] == ["Сборка щита | 12"]
    report: dict = {}
    queries = candidate_queries_for_rows([unresolved], cap=10, report=report)
    assert [item.text for item in queries if item.provenance == "original"] == [
        "Сборка щита"
    ]
    assert report["source_text_filter"]["cells_dropped_formula"] == 1


def test_bare_figures_carry_their_header_only_on_the_derived_query() -> None:
    """"300" is not a characteristic until the source names what it counts.

    ``original`` stays the row's literal text word-for-word; ``derived`` is where
    the governing column header is attached, and it is still only source text.
    """

    queries = candidate_queries_for_rows([_vor_row()], cap=10)
    original = next(item for item in queries if item.provenance == "original")
    derived = next(item for item in queries if item.provenance == "derived")
    assert "300 [Кол-во]" not in original.text
    assert "300 [Кол-во]" in derived.text
    assert "0,42 [Масса, т]" in derived.text
    for item in (original, derived):
        assert token_grounding_violations(
            item.text, " ".join(item.source_fields)
        ) == ()


def test_a_row_without_cell_metadata_keeps_its_line_verbatim() -> None:
    """The filter cannot inspect a pasted row, so it must not narrow it either.

    Dropping a column the code cannot see would silently delete subject matter;
    the report says which path ran instead of pretending the row was filtered.
    """

    row = _row(line="Монтаж шкафа | Итого: 125 000")
    report: dict = {}
    queries = candidate_queries_for_rows([row], cap=10, report=report)
    assert [item.text for item in queries] == ["Монтаж шкафа | Итого: 125 000"]
    assert report["source_text_filter"]["rows_with_cell_metadata"] == 0
    assert report["source_text_filter"]["rows_in_packet"] == 1


# ---------------------------------------------------------------- blocker § 2 R6


def test_every_row_gets_its_original_before_any_row_gets_its_derived() -> None:
    """A cap is per packet, not per row: 5 slots must reach 5 operations."""

    rows = [
        _row(
            locator=f"СКС!R{index}",
            line=f"Монтаж элемента {index}",
            section="Раздел 4. Наружные сети",
        )
        for index in range(1, 11)
    ]
    queries = candidate_queries_for_rows(rows, cap=5)
    assert [item.provenance for item in queries] == ["original"] * 5
    assert len({item.locator for item in queries}) == 5


def test_a_long_row_dump_cannot_starve_the_short_rows_behind_it(monkeypatch) -> None:
    """§ 2: «шум или длинные запросы не должны вытеснять кандидатов операции».

    The count cap alone could not express this: one 400-character dump is a single
    query.  With a character budget the dump is the thing that waits, it is named
    by its locator, and every short row behind it still reaches the model.
    """

    monkeypatch.setenv("LES_LSR_SYSTEM_CANDIDATE_MAX_CHARS", "400")
    dump = _row(locator="СКС!R1", line="Монтаж элемента " + ("состав и условия " * 40))
    short_rows = [
        _row(locator=f"СКС!R{index}", line=f"Монтаж узла {index}")
        for index in range(2, 10)
    ]
    report: dict = {}
    queries = candidate_queries_for_rows([dump, *short_rows], cap=50, report=report)

    assert dump.locator not in {item.locator for item in queries}
    assert {item.locator for item in queries} == {item.locator for item in short_rows}
    assert report["deferred_by_char_budget"] == [dump.locator]
    assert report["limit_reached"] is True
    assert report["chars_used"] <= 400
    # Deferred by a budget is not "no norm": the row itself stays in the packet.
    assert dump.locator in report["deferred_by_cap"]


def test_without_a_character_budget_the_count_cap_still_bounds_the_packet(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LES_LSR_SYSTEM_CANDIDATE_MAX_CHARS", "0")
    rows = [_row(locator="СКС!R1", line="Монтаж элемента " + ("длинный " * 60))]
    report: dict = {}
    queries = candidate_queries_for_rows(rows, cap=5, report=report)
    assert len(queries) == 1
    assert report["deferred_by_char_budget"] == []


# ------------------------------------------------------- blocker § 2 R7 (827)


def _write_vor_like_sheet(tmp_path, header, rows):
    """Write a workbook shaped like the customer's, read back by the real loader.

    Every fixture above hand-builds ``column_headers``, so none of them can fail
    for the reason build 826 failed for: on the customer's file no row was ever
    labelled a header strip at all — each sheet's header names a total column, and
    the subtotal rule claimed the row first — so the filter had no label to test.
    This helper goes through ``load_tabular_source_catalog``, so it exercises the
    classification and the header binding as well as the query filter.
    """

    from openpyxl import Workbook

    from proxy.services.attachment_source_catalog_service import load_tabular_source_catalog

    path = tmp_path / "ВОР 827.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "СКС"
    sheet.append(["Ведомость объемов работ"])
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return load_tabular_source_catalog(path, original_name=path.name)


def test_a_header_strip_naming_a_total_column_reaches_the_query_filter(tmp_path) -> None:
    """§ 2 end to end on the production loader: cost columns stay out of the query.

    A header label containing «итого» is still a column header, so the loader binds
    the strip and the candidate author then drops the cost cells it governs.  The
    assertion that matters is the one that was false on build 826: the money of the
    customer's own spreadsheet reached every «дословный исходный текст строки»
    query, because nothing had been bound to say which column it was.
    """

    catalog = _write_vor_like_sheet(
        tmp_path,
        [
            "№ п/п",
            "Наименование работ",
            "Ед.изм.",
            "Кол-во",
            "Материал (итого), руб. без НДС",
            "Работа (итого), руб. без НДС",
            "Стоимость (итого), руб. без НДС",
            "Примечание",
        ],
        [
            [1.1, "Прокладка кабеля ВВГнг(А)-LS 3х2,5 в коробе", "м", 146,
             1250.5, 2400.0, 3650.5, ""],
            [None, "Итого по всем разделам, руб.", None, None,
             1250.5, 2400.0, 3650.5, None],
        ],
    )

    row = catalog.lookup("СКС!R3")
    assert row is not None
    assert dict(row.column_headers).get(4) == "Кол-во"
    # The real total row keeps its own class: naming a total column in the header
    # strip must not turn sums into headers, and vice versa.
    assert catalog.lookup("СКС!R4").row_classification == "subtotal"

    report: dict = {}
    queries = candidate_queries_for_rows([row], cap=10, report=report)
    assert queries
    for item in queries:
        assert "Прокладка кабеля ВВГнг(А)-LS 3х2,5 в коробе" in item.text
        assert "1250.5" not in item.text
        assert "2400" not in item.text
        assert "3650.5" not in item.text
        assert "Стоимость" not in item.text
    filtered = report["source_text_filter"]
    assert filtered["rows_with_cell_metadata"] == 1
    # the running number plus the three cost columns the header strip names
    assert filtered["cells_dropped_service_column"] == 4
    # the quantity is stated as an explicit characteristic, not as a bare figure
    assert any("146 [Кол-во]" in item.text for item in queries)
