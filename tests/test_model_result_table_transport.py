"""Named model fields cannot be displaced by malformed Markdown presentation."""
from copy import deepcopy
import json

import pytest

from proxy.services.chat_evidence_application_service import parse_model_rag_result


FIELDS = ["source_row", "row_role", "work_row", "title", "unit", "quantity", "norm_code",
          "norm_status", "open_gap", "evidence_refs", "action_match", "object_match", "condition_match",
          "unit_compatible", "composition_covers", "coverage", "nr_sp_rule_id", "supply_kind",
          "confirmed_price", "price_kind", "price_unit", "price_source", "price_currency", "price_period"]
VALUES = ["S!R2", "work", "S!R2", "Literal selected operation", "m", "160", "ГЭСНм08-02-409-09",
          "EXACT", "unknown", "Q38.H2", "yes", "yes", "unknown", "yes", "yes",
          "Literal authored coverage", "nrsp-49.3", "install", "", "unit_price", "m", "", "RUB", ""]


def table(values, fields=FIELDS):
    return "\n".join(("| " + " | ".join(fields) + " |",
                      "| " + " | ".join("---" for _ in fields) + " |",
                      "| " + " | ".join(values) + " |"))


def test_surplus_trailing_empty_cells_preserve_every_named_field_without_joining_gap_or_refs():
    original = table([*VALUES, "", "", ""])
    diagnostics = []
    answer, rows = parse_model_rag_result(original, diagnostics=diagnostics)
    assert answer == original and diagnostics == []
    row = rows[0]
    assert row["open_gap"] == "unknown" and row["evidence_refs"] == ["Q38.H2"]
    assert row["composition_covers"] == "yes" and row["coverage"] == "Literal authored coverage"
    assert row["nr_sp_rule_id"] == "nrsp-49.3" and row["supply_kind"] == "install"
    assert row["price_kind"] == "unit_price" and row["price_currency"] == "RUB"
    assert "confirmed_price" not in row and "price_source" not in row


@pytest.mark.parametrize("changed", [
    VALUES[:8] + VALUES[10:],  # omitted gap/ref cells cannot become trailing blanks
    VALUES[:16] + ["—"] + VALUES[16:-1] + ["2026Q3"],  # never drop an internal authored absence marker
    VALUES[:16] + ["—"] + VALUES[16:],  # a named final blank cannot conceal an internal shift
    [*VALUES, "Q99.H1"],  # never discard a nonempty tail
])
def test_ambiguous_width_preserves_raw_proposal_instead_of_shifted_or_missing_decision(changed):
    raw = table(changed)
    diagnostics = []
    assert parse_model_rag_result(raw, diagnostics=diagnostics) == (raw, [])
    assert len(diagnostics) == 1
    proposal = diagnostics[0]
    assert proposal["code"] == "MODEL_RESULT_TABLE_ROW_WIDTH_MISMATCH"
    assert proposal["decision"]["raw_line"] == raw.splitlines()[2]
    assert proposal["decision"]["raw_cells"] == changed
    assert proposal["decision"]["table_header"] == FIELDS
    assert proposal["decision"]["source_row"] == "S!R2"
    assert "norm_status" not in proposal["decision"]


@pytest.mark.parametrize("field,value", [
    ("composition_covers", "Literal coverage prose"),
    ("quantity", "install"),
    ("confirmed_price", "unit_price"),
    ("row_role", "Unexpected role prose"),
])
def test_surplus_empty_trim_requires_literal_field_types_without_rewriting_them(field, value):
    values = list(VALUES)
    values[FIELDS.index(field)] = value
    raw = table([*values, ""])
    diagnostics = []
    assert parse_model_rag_result(raw, diagnostics=diagnostics) == (raw, [])
    assert diagnostics[0]["reason"] == "ambiguous_markdown_row_field_types"
    assert field in diagnostics[0]["structural_field_errors"]
    assert diagnostics[0]["decision"]["raw_cells"] == [*values, ""]


def test_unescaped_literal_title_pipes_are_not_joined_into_a_guessed_title():
    values = list(VALUES)
    values[3] = 'Шкаф 19" | 800x1000 | Hyperline'
    raw = table(values)
    diagnostics = []
    assert parse_model_rag_result(raw, diagnostics=diagnostics) == (raw, [])
    assert values[3] in diagnostics[0]["decision"]["raw_line"]
    assert diagnostics[0]["decision"]["raw_cells"][3:6] == ['Шкаф 19"', "800x1000", "Hyperline"]


def test_actual_859_second_table_trailing_empty_cells_preserve_all_named_values():
    # Literal original table schema and operation from the installed 859 B1 answer.
    raw = """| source_row | row_role | work_row | title | unit | quantity | norm_code | norm_status | open_gap | evidence_refs | action_match | object_match | condition_match | unit_compatible | composition_covers | coverage | nr_sp_rule_id | supply_kind | confirmed_price | price_kind | price_unit | price_source | price_currency | price_period | section | calc_quantity | conversion_factor | conversion_source | coefficient | coefficient_applies_to | extra_ops | missing_ops | norm_components | resource_code |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PDF!R21 | work | PDF!R21 | Монтаж блока аварийного питания для светильника светодиодного | шт. | 16 | ГЭСНм08-03-609-02 | EXACT | unknown | Q39.H1 | yes | yes | yes | yes | yes | Норма 08-03-609-02 «Светильник светодиодный накладной и подвесной линейный...» (Сборник 8) покрывает монтаж. Блок питания является частью светильника или устанавливается совместно. Измеритель 100 шт совместим. | nrsp-49.3 | install | | unit_price | 100 шт | | RUB | | Раздел 4. Монтажные работы ЭОМ | 0,16 | 1/100 | измеритель нормы | | | | | | | |"""
    diagnostics = []
    answer, rows = parse_model_rag_result(raw, diagnostics=diagnostics)
    assert answer == raw and diagnostics == [] and len(rows) == 1
    assert rows[0] == {
        "source_row": "PDF!R21", "row_role": "work", "work_row": "PDF!R21",
        "title": "Монтаж блока аварийного питания для светильника светодиодного", "unit": "шт.",
        "quantity": 16, "norm_code": "ГЭСНм08-03-609-02", "norm_status": "EXACT", "open_gap": "unknown",
        "evidence_refs": ["Q39.H1"], "action_match": "yes", "object_match": "yes", "condition_match": "yes",
        "unit_compatible": "yes", "composition_covers": "yes",
        "coverage": "Норма 08-03-609-02 «Светильник светодиодный накладной и подвесной линейный...» (Сборник 8) покрывает монтаж. Блок питания является частью светильника или устанавливается совместно. Измеритель 100 шт совместим.",
        "nr_sp_rule_id": "nrsp-49.3", "supply_kind": "install", "price_kind": "unit_price", "price_unit": "100 шт",
        "price_currency": "RUB", "section": "Раздел 4. Монтажные работы ЭОМ", "calc_quantity": 0.16,
        "conversion_factor": "1/100", "conversion_source": "измеритель нормы",
    }


def test_escaped_pipes_and_explicit_empty_internal_cells_do_not_change_the_column_mapping():
    values = list(VALUES)
    values[3], values[8] = r"Literal \| operation", r"Unknown \| condition"
    diagnostics = []
    answer, rows = parse_model_rag_result(table(values), diagnostics=diagnostics)
    assert diagnostics == []
    assert rows[0]["title"] == "Literal | operation" and rows[0]["open_gap"] == "Unknown | condition"
    assert rows[0]["evidence_refs"] == ["Q38.H2"]
    assert rows[0]["nr_sp_rule_id"] == "nrsp-49.3" and rows[0]["supply_kind"] == "install"
    assert "confirmed_price" not in rows[0]
    assert answer == table(values)


def test_rejected_row_does_not_erase_adjacent_valid_model_decision():
    valid = table(VALUES)
    malformed = "| " + " | ".join(VALUES[:8] + VALUES[10:]) + " |"
    raw = valid + "\n" + malformed
    diagnostics = []
    _, rows = parse_model_rag_result(raw, diagnostics=diagnostics)
    assert len(rows) == 1 and rows[0]["norm_code"] == VALUES[6]
    assert rows[0]["condition_match"] == "unknown"
    assert diagnostics[0]["decision"]["raw_line"] == malformed


def test_json_and_explicit_plain_text_keep_the_same_authored_fields():
    authored = {"source_row": "S!R2", "row_role": "work", "title": "Literal | operation", "unit": "m",
                "quantity": 160, "norm_code": VALUES[6], "norm_status": "ANALOGUE_CANDIDATE",
                "condition_match": "unknown", "coverage": "Authored coverage", "evidence_refs": ["Q38.H2"]}
    raw = json.dumps({"rows": [authored]}, ensure_ascii=False)
    diagnostics = []
    assert parse_model_rag_result(raw, diagnostics=diagnostics)[1] == [authored]
    assert diagnostics == []
    raw_plain = "source_row=S!R2; title=Literal operation; unit=m; norm_code=" + VALUES[6]
    _, rows = parse_model_rag_result(raw_plain, diagnostics=diagnostics)
    assert rows[0]["norm_code"] == VALUES[6] and rows[0]["title"] == "Literal operation"
    assert diagnostics == []


def test_raw_transport_proposal_survives_durable_restart_without_becoming_an_accepted_decision(tmp_path):
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService

    diagnostics = []
    parse_model_rag_result(table(VALUES[:8] + VALUES[10:]), diagnostics=diagnostics)
    expected = deepcopy(diagnostics[0])
    service = WorkbookResearchJobService(tmp_path / "jobs.sqlite")
    identity = service.identity(session_id="transport", attachment_id="read_123456789abc",
        source_sha256="a" * 64, dataset_ids=[], profile_revision_id="fixture", model_identity="offline", question="Literal")
    job = service.begin_or_resume(identity)
    service.record_packet(job["job_id"], sheet="S", packet_locators=["S!R2"], accepted_rows=[], evidence=[],
        remaining=["S!R2"], held_packet={"model_result_transport_pending": True, "locators": ["S!R2"]},
        unapplied_proposals=diagnostics)
    restored = WorkbookResearchJobService(tmp_path / "jobs.sqlite").get(job["job_id"])
    assert restored["accepted_rows"] == []
    assert restored["unapplied_proposals"][0]["decision"] == expected["decision"]
    assert restored["held_packet"]["model_result_transport_pending"] is True
    assert diagnostics[0] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_actual_chat_holds_malformed_proposals_without_packaging_missing_defaults_or_model_recall(
        tmp_path, monkeypatch, variant):
    import test_model_rag_sheet_evidence_reads as sheet_case
    from proxy.services import chat_evidence_application_service as service

    raw = """| source_row | row_role | title | unit | quantity | norm_code | resource_code | evidence_refs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S!R2 | material | Cable A | m | 12 | 20.4.01.01-0001 | Q1.H1 |
| S!R3 | material | Cable B | m | 3 | 20.4.01.01-0002 | Q2.H1 |"""
    monkeypatch.setattr(sheet_case, "_answer", lambda **kwargs: raw)
    run = await sheet_case._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant)
    assert len(run.requests) == 2 and not run.responses
    assert run.executions == [] and run.exact_reads == []
    trace = run.result["retrieval_trace"]
    assert len(trace["model_result_transport_diagnostics"]) == 2
    assert all(item["code"] == "MODEL_RESULT_TABLE_ROW_WIDTH_MISMATCH"
               for item in trace["model_result_transport_diagnostics"])
    assert raw in run.result["answer"] and "Техническая ошибка таблицы" in run.result["answer"]
    assert not trace["model_result"]["packaged"]
    if variant == "B1_CANDIDATE":
        state = trace["workbook_research_job"]
        assert state["status"] == "paused" and state["resumable"] is True
        assert set(state["remaining_locators"]) == {"S!R2", "S!R3"}
        job = service.WorkbookResearchJobService().get(state["job_id"])
        assert job["accepted_rows"] == []
        assert len(job["unapplied_proposals"]) == 2
        assert job["held_packet"]["model_result_transport_pending"] is True
        assert {item["decision"]["raw_line"] for item in job["unapplied_proposals"]} == set(raw.splitlines()[2:])
