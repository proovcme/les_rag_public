"""Commentary discovery cannot repair fences or hide competing JSON results."""
from copy import deepcopy
import json

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services import model_lsr_result_contract as contract
from tests.test_model_lsr_result_contract import BROKEN_ROW_TEXT, TRANSPORT_ROW


def _row(source="Edge Ω!R7"):
    return {**deepcopy(TRANSPORT_ROW), "source_row": source}


def _document(rows, carrier="object"):
    return json.dumps({"rows": rows} if carrier == "object" else rows, ensure_ascii=False)


@pytest.mark.parametrize("fence,newline", [
    ("```json", "\n"),
    ("```", "\n"),
    ("  ```json", "\r\n"),
])
def test_leading_heading_cannot_expose_rows_inside_an_unclosed_fence_975(fence, newline):
    body = _document([_row()])
    raw = newline.join(["Literal heading Ω", fence, body])
    before = raw
    diagnostics = []
    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) is None
    parsed = app.parse_model_rag_result(raw, diagnostics=[])
    assert parsed is None or parsed == (raw, [])
    assert raw == before and body in raw


@pytest.mark.parametrize("carrier", ["object", "array"])
def test_whitespace_separated_same_line_row_documents_stay_ambiguous_975(carrier):
    first = _document([_row()], carrier)
    second = _document([_row("Edge Ω!R8")], carrier)
    raw = "Literal heading\n" + first + " \t " + second + "\nLiteral trailing commentary."
    diagnostics = []
    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) is None
    assert diagnostics == [{"code": "MODEL_RESULT_JSON_AMBIGUOUS_RESULTS",
        "reason": "multiple_complete_json_results", "decision": {"raw_json": raw}}]
    assert app.parse_model_rag_result(raw, diagnostics=[]) == (raw, [])


def test_complete_then_cut_same_line_document_keeps_whole_conflict_and_no_first_result_975():
    first = _document([_row()])
    unfinished = '{"rows":[{"source_row":"Edge Ω!R8","row_role":"work","title":"Cut'
    raw = "Literal heading\n" + first + " " + unfinished
    diagnostics = []
    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) is None
    assert diagnostics == [{"code": "MODEL_RESULT_JSON_INCOMPLETE_RESULT",
        "reason": "incomplete_authored_json_result", "decision": {"raw_json": raw}}]
    assert app.parse_model_rag_result(raw, diagnostics=[]) == (raw, [])


def test_salvageable_closed_then_valid_same_line_document_cannot_hide_later_rows_975():
    first = '{"rows":[' + json.dumps(_row(), ensure_ascii=False) + ',' + BROKEN_ROW_TEXT + ']}'
    second = _document([_row("Edge Ω!R8")])
    raw = "Literal heading\n" + first + " \t " + second
    diagnostics = []
    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) is None
    assert diagnostics == [{"code": "MODEL_RESULT_JSON_AMBIGUOUS_RESULTS",
        "reason": "multiple_complete_json_results", "decision": {"raw_json": raw}}]
    assert BROKEN_ROW_TEXT in diagnostics[0]["decision"]["raw_json"]
    assert first in diagnostics[0]["decision"]["raw_json"]
    assert second in diagnostics[0]["decision"]["raw_json"]
    assert app.parse_model_rag_result(raw, diagnostics=[]) == (raw, [])
