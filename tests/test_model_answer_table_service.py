"""One markdown-table contract for the decision reader and the quality gate (task § 3).

Every case here comes from an answer the installed app actually stored, so the
tolerance is bounded by observed provider output rather than by a growing list of
spellings:

* ``[Источник 1] | source_row | … |`` — chat row 506;
* ``|:--|:--|`` alignment cells — chat rows 53 and 55;
* ``source_row | …`` without the optional outer pipes — chat row 330.

The gate side matters as much as the reader side: the quality gate re-reads the
same answer for closed statuses, and if the two readers disagree about what a table
line is, a decision the model made is judged from a different text than the one it
was written into the document from.
"""

from proxy.services import lsr_norm_quality_gate_service as gate
from proxy.services.model_answer_table_service import (
    citation_mark_length,
    is_divider_cell,
    opens_as_table,
    table_cells,
    table_line,
)

MARKER_HEADER = "[Источник 1] | source_row | row_role | title | unit | norm_code |"
PIPE_FREE_HEADER = "source_row | row_role | title | unit | norm_code | open_gap"


def test_citation_mark_is_only_the_mark_the_prompt_mandates():
    assert citation_mark_length("[Источник 12] | a | b |") == len("[Источник 12]")
    assert citation_mark_length("[Источники 3, 4] | a | b |") == len("[Источники 3, 4]")
    assert citation_mark_length("[7] | a | b |") == len("[7]")
    # An evidence handle or a bracketed value is model content, not presentation.
    assert citation_mark_length("[Q4.H1] | a | b |") == 0
    assert citation_mark_length("[ГЭСН 15-04-007-08] | a | b |") == 0
    # A mark that runs past the table payload belongs to a cell.
    assert citation_mark_length("[Источник | 1] | a | b |") == 0


def test_table_line_removes_presentation_and_keeps_the_payload():
    assert table_line(MARKER_HEADER).startswith("| source_row |")
    assert table_cells(MARKER_HEADER) == [
        "source_row",
        "row_role",
        "title",
        "unit",
        "norm_code",
    ]
    assert table_cells(PIPE_FREE_HEADER) == [
        "source_row",
        "row_role",
        "title",
        "unit",
        "norm_code",
        "open_gap",
    ]
    assert table_cells("обычный текст без таблицы") == []
    assert table_cells("") == []


def test_a_cell_value_survives_the_split_verbatim():
    cells = table_cells("| АР!R49 | Кабель-канал 40x40 | м | ГЭСН15-04-007-08 |")
    assert cells == ["АР!R49", "Кабель-канал 40x40", "м", "ГЭСН15-04-007-08"]
    # Inner emphasis is the model's own markup and stays in the cell.
    assert table_cells("| **АР!R49** | **м** |") == ["**АР!R49**", "**м**"]


def test_divider_cells_follow_the_markdown_rule_not_a_dash_count():
    for value in ("---", ":--", "--", ":-:", ":", "-"):
        assert is_divider_cell(value) is (value != ":"), value
    for value in ("abc", "", "-- x", "-:-", "—"):
        assert is_divider_cell(value) is False, value


def test_opens_as_table_separates_a_table_row_from_prose_with_a_pipe():
    assert opens_as_table(MARKER_HEADER) is True
    assert opens_as_table("| АР!R49 | м |") is True
    assert opens_as_table("ПТ!R10: пояснение | не таблица") is False


def test_quality_gate_reads_the_same_three_renderings():
    marked = gate.parse_quality_table(
        "[Источник 1] | source_row | norm_status | title | unit | norm_code |\n"
        "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
        "| АР!R49 | EXACT | Кабель-канал 40x40 | м | ГЭСН15-04-007-08 |\n"
    )
    assert [row["source_row"] for row in marked] == ["АР!R49"]
    assert marked[0]["norm_status"] == "EXACT"

    short = gate.parse_quality_table(
        "| source_row | norm_status | title | unit | norm_code |\n"
        "|:--|:--|:--|:--|:--|\n"
        "| ВОР!R4 | MISSING | Светильник | шт |  |\n"
    )
    assert [row["source_row"] for row in short] == ["ВОР!R4"]

    pipe_free = gate.parse_quality_table(
        "source_row | norm_status | title | unit | norm_code | open_gap\n"
        "--- | --- | --- | --- | --- | ---\n"
        "ПТ!R9 | NEEDS_RESEARCH | Автоматическое пожаротушение |  |  | Раздел\n"
    )
    assert [row["source_row"] for row in pipe_free] == ["ПТ!R9"]
    assert pipe_free[0]["norm_status"] == "NEEDS_RESEARCH"


def test_quality_gate_does_not_read_prose_as_a_closed_status():
    rows = gate.parse_quality_table(
        "source_row | norm_status | title | unit | norm_code | open_gap\n"
        "--- | --- | --- | --- | --- | ---\n"
        "ПТ!R9 | EXACT | Позднее |  | ГЭСН34-01-016-02 | \n"
        "ПТ!R10: это пояснение к разделу | а не решение\n"
        "ПТ!R11 | MISSING | Другая строка |  |  | \n"
    )
    assert [row["source_row"] for row in rows] == ["ПТ!R9"]
