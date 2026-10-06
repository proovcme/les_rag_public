"""Recognize literal carrier labels without supplying missing model decisions."""
from copy import deepcopy

import pytest

from proxy.services.chat_evidence_application_service import (
    format_lsr_partial_notice,
    parse_model_rag_result,
    validate_model_rag_result_structure,
)


def _table(headers, values):
    return "\n".join((
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        "| " + " | ".join(values) + " |",
    ))


def test_installed_907_temperature_zero_carrier_is_decoded_with_authored_gaps_preserved():
    # Literal installed output shape, including its display ordinal and proposed analogue.
    raw = _table(
        ["№ пп", "Наименование работ", "Ед. изм.", "Кол-во",
         "Шифр нормы (ГЭСНм/ГЭСН)", "Примечание / Coverage"],
        ["1.1", "Демонтаж кабельных линий 3х1,5 в гофр. трубе", "м", "160",
         "ГЭСНм 08-02-409-09 (аналог)", "Измеритель 100м. Точная применимость не подтверждена."],
    )
    diagnostics = []
    parsed = parse_model_rag_result(raw, diagnostics=diagnostics)
    assert parsed is not None
    answer, rows = parsed
    assert answer == raw and diagnostics == []
    assert rows == [{
        "source_row": "1.1", "title": "Демонтаж кабельных линий 3х1,5 в гофр. трубе",
        "unit": "м", "quantity": 160, "norm_code": "ГЭСНм 08-02-409-09 (аналог)",
        "coverage": "Измеритель 100м. Точная применимость не подтверждена.",
    }]
    before = deepcopy(rows)
    errors = validate_model_rag_result_structure(rows, [], expected_source_rows=19)
    assert "missing_evidence_ref:1.1" in errors
    notice = format_lsr_partial_notice(errors=errors, row_count=len(rows))
    assert "нет evidence_ref" in notice
    assert "нужны колонки" not in notice
    assert rows == before
    # Display numbering remains authored; never map it to a PDF coordinate or invent trust.
    assert all(key not in rows[0] for key in (
        "operation_id", "row_role", "work_row", "evidence_refs", "evidence_bindings",
        "norm_status", "action_match", "object_match", "composition_covers",
    ))


@pytest.mark.parametrize("decorated", [
    ["**source_row (адрес из файла)**", "`title (буквально (из источника))`",
     "_unit (единица исходника)_", "__quantity (объём)__", "**norm_code (выбор модели)**"],
    ["source_row(адрес)", "*title (literal)*", "unit (м или шт.)",
     "quantity (из ВОР) (без пересчёта)", "norm_code (selected)"],
    ["source_row", "Наименование работ (буквально)", "Ед. изм. (из файла)",
     "Кол-во (исходное)", "Шифр нормы (обоснование выбора)"],
])
def test_balanced_annotations_and_emphasis_preserve_the_same_row_as_canonical_headers(decorated):
    values = ["AnySheet!R17", "Exact source operation", "m", "12.5", "MODEL-CHOICE (analogue)"]
    canonical = ["source_row", "title", "unit", "quantity", "norm_code"]
    reference = parse_model_rag_result(_table(canonical, values))
    raw = _table(decorated, values)
    decoded = parse_model_rag_result(raw)
    assert decoded is not None and decoded[0] == raw
    assert decoded[1] == reference[1]


@pytest.mark.parametrize("coverage_header", [
    "Примечание / Coverage", "coverage / примечание", "**coverage (reason) / coverage**",
])
def test_equivalent_explicit_labels_do_not_discard_authored_coverage(coverage_header):
    raw = _table(["title", "unit", "norm_code", coverage_header],
                 ["Work", "pcs", "N-001", "Unknown operation extent; no full card read."])
    decoded = parse_model_rag_result(raw)
    assert decoded is not None
    assert decoded[1] == [{"title": "Work", "unit": "pcs", "norm_code": "N-001",
                           "coverage": "Unknown operation extent; no full card read."}]


@pytest.mark.parametrize("norm_label", [
    "norm_code (unfinished", "norm_code (annotation))", "norm_code () trailing",
    "norm_code / title", "norm_code / unknown label", "unknown (norm_code)",
    "norm_code (one) garbage (two)",
])
def test_malformed_unknown_or_conflicting_labels_are_not_guessed(norm_label):
    raw = _table(["source_row", "title", "unit", norm_label],
                 ["Sheet!R9", "Work", "m", "N-001"])
    assert parse_model_rag_result(raw) is None


def test_canonical_and_decorated_duplicate_columns_remain_ambiguous():
    raw = _table(["source_row", "title", "unit", "norm_code", "norm_code (alternative)"],
                 ["Sheet!R9", "Work", "m", "N-001", "N-002"])
    assert parse_model_rag_result(raw) is None


def test_parenthetical_norm_cells_are_not_normalized_with_header_decorations():
    raw = _table(["source_row", "title", "unit", "norm_code (literal selection)"],
                 ["Sheet!R9", "Work (source condition)", "m", "N-001 (analogue / unverified)"])
    decoded = parse_model_rag_result(raw)
    assert decoded is not None
    assert decoded[1][0]["title"] == "Work (source condition)"
    assert decoded[1][0]["norm_code"] == "N-001 (analogue / unverified)"


@pytest.mark.asyncio
async def test_actual_chat_recognizes_decorated_carrier_and_reports_missing_evidence_not_missing_columns(
        tmp_path, monkeypatch):
    import test_model_rag_sheet_evidence_reads as sheet_case

    raw = "artifact_kind: lsr\n" + _table(
        ["№ пп", "Наименование работ", "Ед. изм.", "Кол-во",
         "Шифр нормы (ГЭСНм/ГЭСН)", "Примечание / Coverage"],
        ["1.1", "Cable A", "m", "12", "MODEL-CHOICE (analogue)", "Full card not read."],
    )
    monkeypatch.setattr(sheet_case, "_answer", lambda **kwargs: raw)
    run = await sheet_case._run_sheet(tmp_path, monkeypatch, reads=False, variant="B0_DIRECT")
    trace = run.result["retrieval_trace"]
    assert len(run.requests) == 2 and run.exact_reads == [] and run.responses == []
    assert trace["model_result"]["status"] != "unstructured"
    model_issues = [*trace["model_result"].get("errors", []),
                    *trace["model_result"].get("warnings", [])]
    assert "missing_evidence_ref:1.1" in model_issues
    assert raw in run.result["answer"]
    assert "нет evidence_ref" in run.result["answer"]
    assert "нужны колонки наименования" not in run.result["answer"]
    for call, result in run.executions:
        row = call["args"]["decisions"][0]
        assert row["source_row"] == "1.1" and row["norm_code"] == "MODEL-CHOICE (analogue)"
        assert row["coverage"] == "Full card not read."
        assert not row.get("evidence_refs") and not row.get("action_match")
        assert result["confirmed_amount"] == 0
