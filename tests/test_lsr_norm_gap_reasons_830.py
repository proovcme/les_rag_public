"""Task 2026-09-29 § 3: an unready norm names its cause, and the cause survives the chain.

§ 3 asks for one internal contract — model decision → parser → durable record →
quality checks → readiness → XLSX — and for not-ready norms to be told apart:
a wrong citation, an unsubstantiated analogue, a cipher the base does not hold,
source data too thin to choose from, and no suitable candidate among the cards that
were read.  Three of those are structural facts the code can check itself; the two
that live inside the model's own answer had nowhere to be said.  The installed 823
corpus proves the need rather than the guess: 9 222 durable rows carry free-text
``open_gap`` («Нет данных о типе, размере и количестве дверей», «В базе отсутствуют
нормы на монтаж анкер-гильз») and none carries a reason the readiness could read, so
every one of them collapsed into the same «нужна норма» hole — and a row that only
*explains* itself was still sent back to «Продолжите поиск».

These tests are the mechanical proof of the whole chain: the prompt announces the
column, the reader maps it, the durable merge refreshes it instead of dropping it,
and readiness asks two genuinely different questions — while never letting a reason
close a row or a code raise a verdict (§ 11 № 4, ADR-16 § 6).
"""

from __future__ import annotations

from proxy.services.chat_evidence_application_service import (
    _TABULAR_LSR_VOLUME_INSTRUCTION,
    merge_model_rag_rows,
    parse_model_rag_result,
)
from proxy.services.lsr_norm_quality_gate_service import (
    MODEL_GAP_REASONS,
    gap_reason_of,
    lsr_result_table_instruction,
    normalize_gap_reason,
)
from proxy.services.lsr_result_readiness_service import (
    build_lsr_result_readiness,
    classify_norm_gap,
)
from proxy.services.workbook_research_job_service import _decision_content_sha

TABLE_HEADER = (
    "| source_row | row_role | title | unit | quantity | norm_code | norm_status "
    "| gap_reason | open_gap | evidence_refs |"
)
TABLE_DIVIDER = "|---|---|---|---|---|---|---|---|---|---|"


def _table(*rows: str) -> str:
    return "\n".join([TABLE_HEADER, TABLE_DIVIDER, *rows])


def _row(
    locator: str,
    *,
    status: str = "NEEDS_RESEARCH",
    code: str = "-",
    reason: str = "",
    gap: str = "Нет подходящей нормы на монтаж лючков в ГКЛ.",
) -> str:
    return (
        f"| {locator} | work | {('Монтаж люка скрытой установки в перегородку из ГКЛ')} "
        f"| шт | 4 | {code} | {status} | {reason} | {gap} | Q1.H2 |"
    )


# ── the prompt declares what the reader maps ─────────────────────────────────


def test_both_instructions_announce_the_column_the_reader_maps() -> None:
    """§ 3 forbids hidden fields: a checked field must be one the model was told about."""

    for instruction in (
        lsr_result_table_instruction(),
        _TABULAR_LSR_VOLUME_INSTRUCTION,
    ):
        assert "gap_reason" in instruction
        for token in sorted(MODEL_GAP_REASONS):
            assert token in instruction
        # the instruction keeps the decision where it belongs — with the model and
        # the operator — and says out loud that the reason is not a verdict
        assert "вердикт не повышает" in instruction or "open_gap" in instruction


def test_a_prose_cell_is_not_a_reason() -> None:
    """Only the closed tokens count; the model's sentence stays in ``open_gap``.

    § 2's measurement rule applies here too: the reason is not built by scanning
    Russian text.  A long explanation never becomes a token, so the code cannot
    invent a cause the model did not name.
    """

    assert normalize_gap_reason("no_suitable_candidate") == "no_suitable_candidate"
    assert normalize_gap_reason("Нет подходящей нормы") == "no_suitable_candidate"
    assert normalize_gap_reason("") == ""
    assert normalize_gap_reason("нет цены на материал в базе") == ""
    assert (
        normalize_gap_reason(
            "В текущей выборке отсутствуют нормы на остекление и монтаж профилей"
        )
        == ""
    )


# ── the reader keeps it, the durable record refreshes it ─────────────────────


def test_the_reader_carries_the_declared_reason_into_the_row() -> None:
    parsed = parse_model_rag_result(
        _table(_row("ВОР!R7", reason="no_suitable_candidate"))
    )

    assert parsed is not None
    _, rows = parsed
    assert rows, "the reason column must not break the table"
    assert rows[0]["source_row"] == "ВОР!R7"
    assert gap_reason_of(rows[0]) == "no_suitable_candidate"
    # the model's own words stay verbatim beside the token
    assert "лючков" in rows[0]["open_gap"]


def test_a_continuation_that_only_explains_refreshes_the_same_decision() -> None:
    """§ 3: the reader must be able to *save* the field, not merely parse it.

    With an ``operation_id`` the merge takes the in-place refresh path, so before
    this change a resumed packet that finally named its reason was discarded as
    «same decision, nothing changed».  The reason is explanatory metadata — the
    same class as ``open_gap`` and ``note`` — so it refreshes and never duplicates.
    """

    first = parse_model_rag_result(_table(_row("ВОР!R9")))
    assert first is not None
    existing = [dict(row, operation_id="op-1", revision=3) for row in first[1]]

    second = parse_model_rag_result(
        _table(_row("ВОР!R9", reason="insufficient_source_data"))
    )
    assert second is not None
    incoming = [dict(row, operation_id="op-1", revision=3) for row in second[1]]

    merged = merge_model_rag_rows(existing, incoming)

    assert len(merged) == 1, "a reason is not a second paid operation"
    assert merged[0]["gap_reason"] == "insufficient_source_data"
    assert merged[0]["revision"] == 3
    # the content fingerprint is unchanged, so the durable packet still dedups it
    assert _decision_content_sha(existing[0]) == _decision_content_sha(merged[0])


# ── readiness asks one question per cause ────────────────────────────────────


def _readiness(rows, **kw) -> dict:
    return build_lsr_result_readiness(
        packaged=True,
        rows=rows,
        catalog_work_count=len(rows),
        **kw,
    )


def _parsed(raw: str) -> list[dict]:
    parsed = parse_model_rag_result(raw)
    assert parsed is not None
    return [dict(row) for row in parsed[1]]


def test_the_two_model_reasons_ask_two_different_questions() -> None:
    rows = _parsed(
        _table(
            _row("ВОР!R1", reason="insufficient_source_data",
                 gap="Нет данных о типе, размере и количестве дверей."),
            _row("ВОР!R2", reason="no_suitable_candidate",
                 gap="Нормы на монтаж люков скрытой установки в выдаче нет."),
        )
    )

    readiness = _readiness(rows)
    gaps = {gap["locator"]: gap for gap in readiness["dimensions"]["norms"]["gaps"]}

    assert classify_norm_gap(rows[0]) == "insufficient_source_data"
    assert classify_norm_gap(rows[1]) == "no_suitable_candidate"
    assert gaps["ВОР!R1"]["kind"] == "insufficient_source_data"
    assert gaps["ВОР!R2"]["kind"] == "no_suitable_candidate"
    # different asks, not one sentence with a different locator: too-thin source
    # data is answered by the customer, a rejected candidate list by the engineer
    assert "исходных сведений не хватает" in gaps["ВОР!R1"]["action"]
    assert "Нет данных о типе" in gaps["ВОР!R1"]["action"]
    assert "решение сметчика" in gaps["ВОР!R2"]["action"]
    assert "Нормы на монтаж люков" in gaps["ВОР!R2"]["action"]
    assert "Продолжите поиск" not in gaps["ВОР!R2"]["action"]
    assert readiness["dimensions"]["norms"]["complete"] is False


def test_an_undeclared_reason_stays_the_open_row_it_was() -> None:
    """Nothing is guessed: a row that names no cause keeps «нужен поиск».

    The rule had to be additive — the installed corpus has 9 222 open rows and no
    reason column, and re-labelling all of them by text inspection would be the
    code writing the professional sense (§ 2, § 3).
    """

    rows = _parsed(_table(_row("ВОР!R3")))

    readiness = _readiness(rows)
    gap = readiness["dimensions"]["norms"]["gaps"][0]

    assert gap["kind"] == "needs_research"
    assert "Продолжите поиск нормы" in gap["action"]


def test_an_unknown_cipher_is_a_norm_question_not_a_price_question() -> None:
    """§ 3's third cause, and § 10's one wording per row.

    ``norm_not_found`` comes from the calculation layer and used to appear only as
    «Не рассчитаны строки», i.e. as if the operator owed a price for a шифр the
    normative base does not contain.  The production shape is a row whose choice is
    structurally clean — the model cited the card it names — and the base simply has
    no such cipher.
    """

    rows = _parsed(
        _table(
            _row("ВОР!R4", status="EXACT", code="ГЭСН17-01-010-02",
                 gap="Шифр взят из карточки Q1.H2."),
        )
    )

    readiness = _readiness(rows, missing=["row:ВОР!R4:norm_not_found"])

    gaps = [gap for gap in readiness["dimensions"]["norms"]["gaps"] if gap["locator"] == "ВОР!R4"]
    prices_action = readiness["dimensions"]["prices"]["action"]

    assert [gap["kind"] for gap in gaps] == ["cipher_not_in_base"]
    assert "не найден в нормативной базе" in gaps[0]["action"]
    # the row is asked about once: the prices line no longer repeats it as a hole
    assert "ВОР!R4" not in prices_action
    assert readiness["dimensions"]["norms"]["complete"] is False


def test_a_row_already_asked_by_its_declared_reason_is_not_asked_twice() -> None:
    """§ 10: one revision, one status, one wording — the second cause stays silent."""

    rows = _parsed(_table(_row("ВОР!R7", reason="no_suitable_candidate")))

    readiness = _readiness(rows, missing=["row:ВОР!R7:norm_not_found"])
    gaps = [gap for gap in readiness["dimensions"]["norms"]["gaps"] if gap["locator"] == "ВОР!R7"]

    assert [gap["kind"] for gap in gaps] == ["no_suitable_candidate"]
    assert "ВОР!R7" not in readiness["dimensions"]["prices"]["action"]


def test_a_reason_never_closes_a_row_and_never_prices_it() -> None:
    """The guard that makes the field safe to add: declaring a cause buys nothing."""

    rows = _parsed(
        _table(
            _row("ВОР!R5", status="MISSING", reason="no_suitable_candidate"),
            _row("ВОР!R6", status="NEEDS_RESEARCH", reason="insufficient_source_data"),
        )
    )

    readiness = _readiness(rows)
    counts = readiness["counts"]

    assert classify_norm_gap(rows[0]) == "no_suitable_candidate"
    assert counts["norms_selected"] == 0
    assert readiness["dimensions"]["norms"]["complete"] is False
    assert readiness["estimate_complete"] is False
    assert readiness["technical_complete"] is True, "the file is fine; the estimate is not"
