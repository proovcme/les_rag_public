"""Literal .193 pass-2 resource group codes must not be mistaken for shifted cells."""

import json
from pathlib import Path

import pytest

from proxy.services import chat_evidence_application_service as chat
from proxy.services.rim_lsr_trace_service import positions_from_visible_lsr_rows


FIXTURE = json.loads((Path(__file__).parent / "fixtures/smeta_resource_group_parser.json").read_text(encoding="utf-8"))


def cells(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def literal_table(code):
    row = next(line for line in FIXTURE["rows"] if cells(line)[11] == code)
    return FIXTURE["header"], row


@pytest.mark.parametrize("code", ["12.2.07.02", "01.6.03.03", "14.1.02.04", "01.7.20.08-0051"])
def test_saved_receipt_resource_code_is_not_a_shifted_model_field(code):
    header, authored = literal_table(code)
    assert len(cells(header[0])) == 32
    assert len(cells(authored)) == 30, "Only absent trailing cells need padding"
    raw = dict(zip(cells(header[0]), cells(authored) + ["", ""], strict=True))
    assert raw["resource_code"] == code
    assert raw["resource_review_ref"] == "960528670a601b9dd5259e462ad359412d9231d64fa5ecdd0c142586a368b43c"
    assert raw["resource_action"] == "included"
    assert raw["target_resource_code"] == ""
    record = next(item for item in FIXTURE["receipt_resources"] if item["code"] == code)
    assert float(raw["resource_quantity"]) == float(record["quantity"])
    assert raw["resource_unit"] == record["unit"]
    assert chat.shifted_decision_fields(raw, lambda value: value in {"—", "-"}) == []
    parsed = chat.parse_model_rag_result("\n".join([*header, authored]))
    assert parsed is not None
    rows = parsed[1]
    assert len(rows) == 1
    assert not rows[0].get("parse_error"), "Legal group code must reach subsequent identity/price/operation gates"
    assert rows[0]["resource_code"] == code
    assert rows[0]["resource_review_ref"] == raw["resource_review_ref"]
    assert rows[0]["resource_quantity"] == raw["resource_quantity"]
    assert rows[0]["resource_action"] == "included"


@pytest.mark.parametrize("field,index", [("resource_code", 11), ("target_resource_code", 16)])
@pytest.mark.parametrize("bad_code", [
    "960528670a601b9dd5259e462ad359412d9231d64fa5ecdd0c142586a368b43c",
    "NOT_A_RESOURCE_CODE!?", ".12.2.07.02", "12.2.07.02.", "12.2..07.02",
])
def test_actual_shifted_receipt_hash_and_invalid_codes_remain_format_errors(bad_code, field, index):
    header, authored = literal_table("01.7.20.08-0051")
    values = cells(authored)
    values[index] = bad_code
    raw = dict(zip(cells(header[0]), values + ["", ""], strict=True))
    assert chat.shifted_decision_fields(raw, lambda _value: False) == [field]
    parsed = chat.parse_model_rag_result("\n".join([*header, "| " + " | ".join(values) + " | "]))
    assert parsed is not None
    assert parsed[1][0]["parse_error"] == "column_count_mismatch"
    bound = positions_from_visible_lsr_rows(parsed[1])
    assert bound["row_bindings"][0]["status"] == "model_row_format_error"
    assert bound["positions"] == []


@pytest.mark.parametrize("code", ["12.2.07.02", "01.6.03.03", "14.1.02.04"])
def test_target_resource_code_preserves_group_identity_for_later_binding(code):
    header, authored = literal_table("01.7.20.08-0051")
    values = cells(authored)
    values[16] = code
    raw = dict(zip(cells(header[0]), values + ["", ""], strict=True))
    assert chat.shifted_decision_fields(raw, lambda _value: False) == []
    parsed = chat.parse_model_rag_result("\n".join([*header, "| " + " | ".join(values) + " | "]))
    assert parsed is not None
    assert not parsed[1][0].get("parse_error")
    assert parsed[1][0]["target_resource_code"] == code
    assert parsed[1][0]["resource_code"] == "01.7.20.08-0051"
