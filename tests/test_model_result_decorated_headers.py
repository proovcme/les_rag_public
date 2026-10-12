"""Recognize literal carrier labels without supplying missing model decisions."""
import json

import pytest

from proxy.services.chat_evidence_application_service import parse_model_rag_result


def _table(headers, values):
    return "\n".join((
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        "| " + " | ".join(values) + " |",
    ))


@pytest.mark.parametrize("ordinal_header", ["№", "№ пп", "№ п/п", "**№ пп (порядок)**", "позиция"])
def test_display_ordinal_cannot_bind_to_an_existing_catalog_row(ordinal_header):
    from proxy.services.attachment_source_catalog_service import AttachmentSourceCatalog, CatalogRow
    from proxy.services.model_result_packet_service import admit_model_result_packet

    raw = _table([ordinal_header, "title", "unit", "quantity", "norm_code", "coverage"],
                 ["10", "Finishing operation", "m2", "3.2", "AUTHORED-NORM", "Authored uncertainty"])
    catalog = AttachmentSourceCatalog("arbitrary.pdf", (("PDF", 2),), (
        CatalogRow("PDF!R10", "PDF", 10, ("Preparation", "m2", "3.2"), "Preparation", (3.2,)),
        CatalogRow("PDF!R15", "PDF", 15, ("Finishing operation", "m2", "3.2"), "Finishing operation", (3.2,)),
    ))
    diagnostics = []
    parsed = parse_model_rag_result(raw, diagnostics=diagnostics)
    assert parsed == (raw, [])
    assert len(diagnostics) == 1
    proposal = diagnostics[0]
    assert proposal["code"] == "MODEL_RESULT_SOURCE_LOCATOR_MISSING"
    assert proposal["reason"] == "display_ordinal_is_not_source_locator"
    assert proposal["display_ordinal"] == "10"
    assert proposal["decision"]["title"] == "Finishing operation"
    assert proposal["decision"]["norm_code"] == "AUTHORED-NORM"
    assert proposal["decision"]["quantity"] == 3.2
    assert proposal["decision"]["coverage"] == "Authored uncertainty"
    assert proposal["decision"]["raw_cells"] == [
        "10", "Finishing operation", "m2", "3.2", "AUTHORED-NORM", "Authored uncertainty",
    ]
    assert "source_row" not in proposal["decision"]
    admitted = admit_model_result_packet(parsed[1], packet_locators=["PDF!R10", "PDF!R15"],
        canonicalize_locator=lambda value: catalog.lookup(value).locator if catalog.lookup(value) else value)
    assert admitted.accepted_rows == []


@pytest.mark.parametrize("source_header", ["source_row", "source_row (адрес)", "locator"])
@pytest.mark.parametrize("source_value", ["PDF!R15", "R15", "15"])
def test_explicit_source_identity_wins_over_independent_display_ordinal(source_header, source_value):
    raw = _table(["№ пп", source_header, "title", "unit", "norm_code"],
                 ["10", source_value, "Model operation", "m2", "AUTHORED-NORM"])
    diagnostics = []
    parsed = parse_model_rag_result(raw, diagnostics=diagnostics)
    assert parsed == (raw, [{"source_row": 15 if source_value == "15" else source_value,
                            "title": "Model operation", "unit": "m2", "norm_code": "AUTHORED-NORM"}])
    assert diagnostics == []


@pytest.mark.parametrize("ordinal_header", ["№ пп", "позиция"])
@pytest.mark.parametrize("locator", ["R15", "Sheet!R15"])
def test_legacy_number_column_with_literal_source_locator_preserves_that_locator(locator, ordinal_header):
    raw = _table([ordinal_header, "title", "unit", "norm_code"], [locator, "Model operation", "m2", "AUTHORED-NORM"])
    assert parse_model_rag_result(raw) == (raw, [{"source_row": locator, "title": "Model operation",
                                               "unit": "m2", "norm_code": "AUTHORED-NORM"}])


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
    assert answer == raw and rows == []
    assert diagnostics[0]["display_ordinal"] == "1.1"
    assert {key: value for key, value in diagnostics[0]["decision"].items()
            if key not in {"raw_line", "raw_cells", "table_header"}} == {
        "title": "Демонтаж кабельных линий 3х1,5 в гофр. трубе",
        "unit": "м", "quantity": 160, "norm_code": "ГЭСНм 08-02-409-09 (аналог)",
        "coverage": "Измеритель 100м. Точная применимость не подтверждена.",
    }
    # Display numbering remains authored; never map it to a PDF coordinate or invent trust.
    assert all(key not in diagnostics[0]["decision"] for key in (
        "source_row",
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
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_actual_chat_preserves_unlocated_carrier_without_inventing_source_identity(
        tmp_path, monkeypatch, variant):
    import test_model_rag_sheet_evidence_reads as sheet_case

    raw = "artifact_kind: lsr\n" + _table(
        ["№ пп", "Наименование работ", "Ед. изм.", "Кол-во",
         "Шифр нормы (ГЭСНм/ГЭСН)", "Примечание / Coverage"],
        ["1.1", "Cable A", "m", "12", "MODEL-CHOICE (analogue)", "Full card not read."],
    )
    monkeypatch.setattr(sheet_case, "_answer", lambda **kwargs: raw)
    run = await sheet_case._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant)
    trace = run.result["retrieval_trace"]
    assert len(run.requests) == 2 and run.exact_reads == [] and run.responses == []
    assert trace["model_result"]["status"] != "unstructured"
    proposals = trace["model_result"]["transport_diagnostics"]
    assert proposals[0]["code"] == "MODEL_RESULT_SOURCE_LOCATOR_MISSING"
    assert proposals[0]["display_ordinal"] == "1.1"
    assert proposals[0]["decision"]["norm_code"] == "MODEL-CHOICE (analogue)"
    assert proposals[0]["decision"]["coverage"] == "Full card not read."
    assert "source_row" not in proposals[0]["decision"]
    assert raw in run.result["answer"]
    assert "порядковые номера вместо адресов" in run.result["answer"]
    assert run.executions == []
    if variant == "B1_CANDIDATE":
        from proxy.services.workbook_research_job_service import WorkbookResearchJobService
        job = WorkbookResearchJobService().get(trace["workbook_research_job"]["job_id"])
        assert job["accepted_rows"] == []
        assert set(job["remaining"]) == {"S!R2", "S!R3"}
        assert job["unapplied_proposals"][0]["decision"]["norm_code"] == "MODEL-CHOICE (analogue)"


@pytest.mark.parametrize("ordinal", [10, "10", "1.1", "", None])
def test_json_display_number_does_not_become_a_source_identity(ordinal):
    authored = {"№ пп": ordinal, "title": "Authored work", "unit": "m", "quantity": 3,
                "norm_code": "N", "coverage": "Authored reason"}
    raw = json.dumps({"rows": [authored]}, ensure_ascii=False)
    diagnostics = []
    # The JSON envelope decoder already requires an explicit source_row. Keep
    # that boundary; the original response remains the unstructured proposal.
    assert parse_model_rag_result(raw, diagnostics=diagnostics) is None
    assert diagnostics == []
    explicit = {**authored, "source_row": "S!R15"}
    parsed = parse_model_rag_result(json.dumps({"rows": [explicit]}, ensure_ascii=False))
    assert parsed[1] == [{key: value for key, value in explicit.items() if key != "№ пп"}]


@pytest.mark.asyncio
async def test_packet_keeps_valid_rows_and_unlocated_proposals_without_charging_colliding_ordinal(tmp_path, monkeypatch):
    import test_model_rag_sheet_evidence_reads as sheet_case
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService

    valid = "\n".join(line for line in sheet_case._answer().splitlines() if not line.startswith("| S!R2 |"))
    invalid = _table(["№ пп", "title", "unit", "quantity", "norm_code", "coverage"],
                     ["2", "Different authored work", "m", "12", "AUTHORED-NORM", "Need source address"])
    raw = valid + "\n\n" + invalid
    monkeypatch.setattr(sheet_case, "_answer", lambda **kwargs: raw)
    run = await sheet_case._run_sheet(tmp_path, monkeypatch, reads=False)
    assert len(run.requests) == 2 and len(run.executions) == 1
    trace = run.result["retrieval_trace"]
    job = WorkbookResearchJobService().get(trace["workbook_research_job"]["job_id"])
    assert [row["source_row"] for row in job["accepted_rows"]] == ["S!R3"]
    # An unlocated proposal cannot be assigned to a subset of the offered
    # packet. Both addresses stay available, while the explicit row is durable.
    assert set(job["remaining"]) == {"S!R2", "S!R3"}
    proposal = job["unapplied_proposals"][0]
    assert proposal["display_ordinal"] == "2"
    assert proposal["decision"]["norm_code"] == "AUTHORED-NORM"
    assert "source_row" not in proposal["decision"]
    call, receipt = run.executions[0]
    assert [row["source_row"] for row in call["args"]["decisions"]] == ["S!R3"]
    assert receipt["status"] == "partial"
    assert any(issue["proposal"]["decision"]["norm_code"] == "AUTHORED-NORM"
               for issue in receipt["document_issues"] if isinstance(issue.get("proposal"), dict))
