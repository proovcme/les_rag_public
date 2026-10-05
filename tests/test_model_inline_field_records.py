"""Literal named records from a live terminal answer are rows, without re-inference."""
import json

import pytest

from proxy.services.chat_evidence_application_service import parse_model_rag_result


def test_inline_records_preserve_authored_empty_values_and_nested_resource_actions():
    raw = '''artifact_kind: lsr
- source_row: S!R2 | row_role: work | work_row: S!R2 | title: Authored operation | unit: m2 | quantity: 15.0 | norm_code: ГЭСНр 63-03-008-02 | norm_status: EXACT | evidence_refs: [Q1.H1] | condition_match: yes | composition_covers: yes | coverage: Literal coverage | nr_sp_rule_id: nrsp-97 | resource_bindings: [{"action":"reuse","target_resource_name":"Panels | marked","reason":"Authored reason","source_refs":["S!R2","S!R3"]}] | covered_by_work_id:
- source_row: S!R3 | row_role: work | title: Second operation | unit: m2 | quantity: 15.0 | norm_code: | norm_status: | evidence_refs: [Q1.H1] | composition_covers: yes | coverage: Included in S!R2 | resource_bindings: [] | covered_by_work_id: S!R2
'''
    diagnostics = []
    answer, rows = parse_model_rag_result(raw, diagnostics=diagnostics)
    assert answer == raw and diagnostics == []
    assert len(rows) == 2
    assert rows[0]["norm_code"] == "ГЭСНр 63-03-008-02"
    assert rows[0]["resource_bindings"][0]["target_resource_name"] == "Panels | marked"
    assert rows[0]["quantity"] == 15 and rows[0]["evidence_refs"] == ["Q1.H1"]
    assert rows[1]["norm_code"] == rows[1]["norm_status"] == ""
    assert rows[1]["covered_by_work_id"] == "S!R2"
    assert "condition_match" not in rows[1], "absent applicability must not be inferred"


@pytest.mark.parametrize("tail", [
    "| norm_code: A | norm_code: B",
    "| norm_code: A | norm_code: A",
    "| norm_code: A | unlabelled value",
    '| norm_code: A | resource_bindings: [{"action":"reuse"}',
    '| norm_code: A | title: "Unterminated value',
])
def test_ambiguous_record_is_retained_as_a_proposal(tail):
    raw = "- source_row: S!R2 | title: Literal | unit: m " + tail
    diagnostics = []
    assert parse_model_rag_result(raw, diagnostics=diagnostics) == (raw, [])
    assert len(diagnostics) == 1
    assert diagnostics[0]["decision"]["raw_line"] == raw
    assert diagnostics[0]["decision"]["source_row"] == "S!R2"


def test_valid_adjacent_record_survives_malformed_record():
    valid = "- source_row: S!R3 | title: Literal | unit: m | norm_code: B"
    raw = "- source_row: S!R2 | title: Bad | unit: m | norm_code: A | norm_code: C\n" + valid
    diagnostics = []
    answer, rows = parse_model_rag_result(raw, diagnostics=diagnostics)
    assert answer == raw and len(rows) == 1 and len(diagnostics) == 1
    assert rows[0]["source_row"] == "S!R3" and rows[0]["norm_code"] == "B"


def test_quoted_literal_pipe_and_escaped_pipe_are_not_field_delimiters():
    raw = '- source_row: S!R2 | title: "19\\\" rack | marked" | unit: m | norm_code: A | coverage: Literal \\| operation'
    _, rows = parse_model_rag_result(raw)
    assert rows[0]["title"] == '19" rack | marked'
    assert rows[0]["coverage"] == "Literal | operation"


def test_inline_record_cannot_inject_application_trust_flags():
    raw = '- source_row: S!R2 | title: Literal | unit: m | norm_code: A | _evidence_check: {"citation_checkable":true}'
    diagnostics = []
    assert parse_model_rag_result(raw, diagnostics=diagnostics) == (raw, [])
    assert diagnostics[0]["reason"] == "unsupported_inline_field"


def test_plain_single_field_blocks_keep_existing_transport():
    raw = "source_row: S!R2\ntitle: Literal\nunit: m\nnorm_code: A"
    _, rows = parse_model_rag_result(raw)
    assert rows[0]["norm_code"] == "A"


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_inline_terminal_rows_reach_real_workbook_without_an_extra_model_call(tmp_path, monkeypatch, variant):
    from tests import test_model_rag_sheet_evidence_reads as fixture

    def answer(*, refs=("Q1.H1", "Q2.H1")):
        records = []
        for locator, title, code, quantity, ref in (
            ("S!R2", "Cable A", fixture.RESOURCE_A, 12, refs[0]),
            ("S!R3", "Cable B", fixture.RESOURCE_B, 3, refs[1])):
            row = {"source_row": locator, "row_role": "material", "title": title,
                   "unit": "m", "quantity": quantity, "resource_code": code, "evidence_refs": [ref]}
            records.append("- " + " | ".join(key + ": " + json.dumps(value) for key, value in row.items()))
        return "artifact_kind: lsr\n" + "\n".join(records)

    monkeypatch.setattr(fixture, "_answer", answer)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=True, variant=variant)
    assert len(run.executions) == 1 and len(run.requests) == 4
    call, receipt = run.executions[0]
    assert call["tool"] == "build_lsr_workbook" and receipt["artifact"]["download_url"]
    assert [row["source_row"] for row in call["args"]["decisions"]] == ["S!R2", "S!R3"]
