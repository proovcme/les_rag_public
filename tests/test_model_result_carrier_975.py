"""Line-level JSON carriers keep authored rows and existing refusal guards."""
from copy import deepcopy
import json

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services import model_lsr_result_contract as contract
from tests.test_model_lsr_result_contract import BROKEN_ROW_TEXT, TRANSPORT_ROW
from tests.test_model_rag_sheet_evidence_reads import _run_sheet, NORM_CODE
from tests.test_workbook_artifact_target import MIXED, TOOLS


def _row(source="Source Ω!R7", **values):
    return {**deepcopy(TRANSPORT_ROW), "source_row": source, **values}


@pytest.mark.parametrize("kind", ["vor", "lsr"])
@pytest.mark.parametrize("carrier", ["object", "array"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_standalone_unfenced_result_after_arbitrary_heading_and_target_keeps_all_rows_975(kind, carrier, newline):
    rows = [_row(title='Literal braces { } [ ] and quote "Ω"'), _row("Source Ω!R8", quantity=None)]
    body = json.dumps({"artifact_kind": kind, "rows": rows} if carrier == "object" else rows, ensure_ascii=False)
    # A line-level standalone marker supplies the target for a bare rows array;
    # matching object + marker is already an accepted transport form.
    raw = newline.join(["## Дословный заголовок результата Ω", "Пояснение перед результатом.",
                        "artifact_kind: " + kind, "", "\t" + body, "", "Literal trailing commentary."])
    diagnostics = []
    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) == rows
    assert diagnostics == []
    assert contract.decode_model_artifact_kind(raw)["artifact_kind"] == kind
    assert app.parse_model_rag_result(raw, diagnostics=[]) == (raw, rows)


@pytest.mark.parametrize("kind", ["vor", "lsr"])
@pytest.mark.parametrize("quantity", ["0", 0, "0,25", 0.25, None, False, ""])
def test_heading_carrier_preserves_literal_scalar_types_without_truthiness_or_number_repair_975(kind, quantity):
    row = _row(quantity=quantity, work_row="", calc_quantity=None, open_gap="", coverage="literal authored coverage")
    raw = "Заголовок без предметных правил\n" + json.dumps({"artifact_kind": kind, "rows": [row]}, ensure_ascii=False)
    diagnostics = []
    rows = contract.decode_model_result_rows(raw, diagnostics=diagnostics)
    assert rows == [row] and diagnostics == []
    assert type(rows[0]["quantity"]) is type(quantity)
    assert rows[0]["work_row"] == "" and rows[0]["calc_quantity"] is None and rows[0]["open_gap"] == ""
    parsed = app.parse_model_rag_result(raw, diagnostics=[])
    assert parsed == (raw, [row]) and type(parsed[1][0]["quantity"]) is type(quantity)


@pytest.mark.parametrize("prefix", ["Example only: ", "Пояснение: ", "Text with an inline example "])
def test_inline_prose_json_example_is_not_a_standalone_result_carrier_975(prefix):
    raw = prefix + json.dumps({"rows": [_row()]}, ensure_ascii=False) + " is an example, not a result."
    diagnostics = []
    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) is None
    assert diagnostics == []
    assert app.parse_model_rag_result(raw, diagnostics=[]) is None


def test_inline_prose_target_is_not_a_declaration_but_next_line_rows_remain_literal_975():
    row = _row()
    raw = "Prose artifact_kind: vor\n" + json.dumps({"rows": [row]}, ensure_ascii=False)
    diagnostics = []
    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) == [row]
    assert diagnostics == [] and app.parse_model_rag_result(raw, diagnostics=[]) == (raw, [row])
    declaration = contract.decode_model_artifact_kind(raw)
    assert declaration["status"] == "missing" and declaration["artifact_kind"] == ""
    assert app.workbook_packaging_tool(TOOLS, MIXED, task_context={"model_artifact_kind": declaration["artifact_kind"]}) == []


@pytest.mark.parametrize("between", ["\n", "\nExplanatory commentary between documents.\n", "\nartifact_kind: vor\n"])
def test_two_complete_line_level_results_remain_ambiguous_and_keep_full_original_answer_975(between):
    first = json.dumps({"rows": [_row()]}, ensure_ascii=False)
    second = json.dumps({"rows": [_row("Source Ω!R8")]}, ensure_ascii=False)
    raw = "Heading\n" + first + between + second + "\nTrailing commentary"
    diagnostics = []
    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) is None
    assert [item["code"] for item in diagnostics] == ["MODEL_RESULT_JSON_AMBIGUOUS_RESULTS"]
    assert diagnostics[0]["decision"]["raw_json"] == raw
    assert app.parse_model_rag_result(raw, diagnostics=[]) == (raw, [])


@pytest.mark.parametrize("unfinished", [
    '{"rows":[',
    '{"artifact_kind":"vor","rows":[{"source_row":"Source Ω!R1","title":"Cut',
    '[{"source_row":"Source Ω!R1","row_role":"work","title":"Whole"},',
])
@pytest.mark.parametrize("later_fenced", [False, True])
def test_incomplete_first_result_cannot_be_discarded_for_a_later_complete_result_975(unfinished, later_fenced):
    later = json.dumps({"artifact_kind": "vor", "rows": [_row()]}, ensure_ascii=False)
    if later_fenced:
        later = "```json\n" + later + "\n```"
    raw = "Heading\n" + unfinished + "\nCommentary cannot close the unfinished result.\n" + later
    diagnostics = []
    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) is None
    assert [item["code"] for item in diagnostics] == ["MODEL_RESULT_JSON_INCOMPLETE_RESULT"]
    assert diagnostics[0]["decision"]["raw_json"] == raw
    assert app.parse_model_rag_result(raw, diagnostics=[]) == (raw, [])


@pytest.mark.parametrize("fenced", [False, True])
def test_heading_carrier_preserves_duplicate_key_proposal_without_choosing_a_value_975(fenced):
    good = _row()
    duplicate = ('{ "source_row": "Source Ω!R8", "row_role": "work", "title": "Literal duplicate", '
                 '"unit": "m", "quantity": 0, "quantity": 2 }')
    body = '{"artifact_kind":"vor","rows":[' + json.dumps(good, ensure_ascii=False) + ',' + duplicate + ']}'
    raw = "Heading\n" + ("```json\n" + body + "\n```" if fenced else body) + "\nTrailing commentary"
    diagnostics = []
    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) == [good]
    assert len(diagnostics) == 1 and diagnostics[0]["code"] == "MODEL_RESULT_JSON_DUPLICATE_FIELD"
    assert diagnostics[0]["decision"]["raw_json"] == duplicate
    assert diagnostics[0]["decision"]["source_row"] == "Source Ω!R8"
    assert diagnostics[0]["duplicate_fields"][0]["field"] == "quantity"
    assert app.parse_model_rag_result(raw, diagnostics=[]) == (raw, [good])


def test_closed_malformed_row_after_heading_keeps_good_rows_and_exact_unreadable_proposal_975():
    good = _row()
    raw = 'Heading\n{"artifact_kind":"lsr","rows":[' + json.dumps(good, ensure_ascii=False) + ',' + BROKEN_ROW_TEXT + ']}\nTrailing commentary'
    diagnostics = []
    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) == [good]
    assert [item["code"] for item in diagnostics] == ["MODEL_RESULT_JSON_INVALID_ROW"]
    assert diagnostics[0]["decision"]["raw_json"] == BROKEN_ROW_TEXT
    assert diagnostics[0]["decision"]["source_row"] == "PDF!R21"
    assert app.parse_model_rag_result(raw, diagnostics=[]) == (raw, [good])


def test_salvageable_closed_first_result_does_not_hide_a_later_complete_result_975():
    first = '{"rows":[' + json.dumps(_row(), ensure_ascii=False) + ',' + BROKEN_ROW_TEXT + ']}'
    second = json.dumps({"rows": [_row("Source Ω!R8")]}, ensure_ascii=False)
    raw = "Heading\n" + first + "\nCommentary between results\n" + second
    diagnostics = []
    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) is None
    assert any(item["code"] == "MODEL_RESULT_JSON_AMBIGUOUS_RESULTS" for item in diagnostics)
    assert any(item["decision"].get("raw_json") == raw for item in diagnostics)


def test_target_label_inside_json_fence_is_still_not_repaired_or_extracted_975():
    raw = 'Heading\n```json\nartifact_kind: vor\n' + json.dumps({"rows": [_row()]}) + '\n```'
    assert contract.decode_model_result_rows(raw) is None


@pytest.mark.asyncio
async def test_actual_direct_packaging_keeps_heading_rows_but_cannot_invent_an_undeclared_target_975(tmp_path, monkeypatch):
    rows = [_row("S!R2", quantity=12, norm_code=NORM_CODE, evidence_refs=["Q1.H1"]),
            _row("S!R3", quantity=3, norm_code=NORM_CODE, evidence_refs=["Q2.H1"])]
    raw = "Prose artifact_kind: vor\n" + json.dumps({"rows": rows}, ensure_ascii=False)
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant="B0_DIRECT", question=MIXED,
                           final_answer=raw)
    assert len(run.requests) == 2 and not run.responses and not run.executions
    result = run.result["retrieval_trace"]["model_result"]
    assert result["row_count"] == 2 and result["packaging_status"] == "pending"
    assert run.result["retrieval_trace"]["artifact_target"]["status"] == "missing"
