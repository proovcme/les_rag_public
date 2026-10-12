"""Offline receipt delivery contracts; these fixtures are not professional acceptance."""

import copy
import json

import pytest

from proxy.services import chat_evidence_application_service as chat
from proxy.services import rim_lsr_trace_service as rim
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from proxy.services.portion_cursor_service import PortionCursorService
from proxy.smeta_core.calculation_receipt import (
    apply_model_review,
    calculation_receipts,
    receipt_context,
)


@pytest.mark.parametrize("reference_matches", [True, False])
def test_real_calculated_receipt_reaches_next_governed_messages_and_requires_exact_review_ref(tmp_path, reference_matches):
    # This is a deterministic numerical fixture. No model/domain selection is
    # mocked or claimed to be correct; the boundary starts with visible rows.
    terminal = (
        "| source_row | work_id | title | unit | quantity | norm_code | evidence_refs |\n"
        "|---|---|---|---|---|---|---|\n"
        "| S!1 | mount | Fixture operation | шт | 2 | ГЭСН01-01-001-01 | Q1.H1 |"
    )
    rows = chat.parse_model_rag_result(terminal)[1]
    assert rows[0]["quantity"] == 2
    trace = rim.build_lsr_trace([dict(
        code=rows[0]["norm_code"], name=rows[0]["title"], source_row="S!1",
        work_id="mount", unit="шт", qty=rows[0]["quantity"], nr_pct=0, sp_pct=0,
        resources=[
            dict(kind="labor", code="L", name="REAL_LABOR_RECEIPT_PROOF", unit="чел.-ч", per_unit=3.25, price=10),
            dict(kind="machine", code="M", name="REAL_MACHINE_RECEIPT_PROOF", unit="маш.-ч", per_unit=0.5, price=20),
            dict(kind="material", code="R", name="LAST_REAL_RESOURCE_RECEIPT_PROOF", unit="кг", per_unit=7.125, price=30),
        ],
    )])
    trace["row_bindings"] = [dict(row="S!1", work_id="mount", status="bound")]
    receipts = calculation_receipts(trace)
    receipt = receipts[0]
    assert [resource["quantity"] for resource in receipt["calculation"]["resources"]] == [6.5, 1.0, 14.25]
    assert len(receipt["calculation_ref"]) == 64
    first_trace = copy.deepcopy(trace)
    apply_model_review(first_trace, receipts, rows)
    assert first_trace["row_bindings"][0]["status"] == "resource_review_required"

    original = "Файл: source.xlsx\nS!R1: № | Наименование | Ед. изм | Количество\nS!R2: 1 | Fixture operation | шт | 2\n"
    store = PortionCursorService(tmp_path / "continuation.sqlite")
    _, first_state = chat.smeta_portion_context(original, session_id="s", limit=1, cursors=store)
    chat.record_portion_pass(
        store, session_id="s", portion_state=first_state, rows=rows, closed=[],
        artifact_revision_id=None, row_statuses={"S!1": "resource_review_required"},
        calculation_receipts=receipts, pass_id="ordinary-turn-1",
    )
    restarted = PortionCursorService(tmp_path / "continuation.sqlite")
    next_context, next_state = chat.smeta_portion_context(original, session_id="s", limit=1, cursors=restarted)
    assert next_state["prior_decisions"]["S!1"]["calculation_receipts"] == receipts
    assert next_state["completed"] == 0
    preset = ModelExecutionPreset("real-receipt", "fixture", 16000, 2000, 200, 3, 5, 5, 1, False, ("test",))
    messages, packet = chat.govern_inference_messages(
        preset=preset, profile_prefix="Original bound profile", request_payload="Continue original question",
        evidence=chat.selector_evidence_payload(attachment_context=next_context, rendered_context=""),
    )
    rendered = "\n".join(message["content"] for message in messages)
    assert not packet.omissions
    assert receipt_context(receipts) in rendered
    assert json.dumps(receipts, ensure_ascii=False, separators=(",", ":")) in rendered
    assert receipt["calculation_ref"] in rendered
    assert "LAST_REAL_RESOURCE_RECEIPT_PROOF" in rendered
    assert "14.25" in rendered
    assert "resource_review_ref" in rendered

    selected_ref = receipt["calculation_ref"] if reference_matches else "0" * 64
    second_terminal = terminal.replace("| evidence_refs |", "| evidence_refs | resource_review_ref | resource_review_status |").replace(
        "| Q1.H1 |", f"| Q1.H1 | {selected_ref} | keep_all_confirmed |"
    )
    reviewed_rows = chat.parse_model_rag_result(second_terminal)[1]
    assert reviewed_rows[0]["resource_review_ref"] == selected_ref
    second_trace = copy.deepcopy(trace)
    apply_model_review(second_trace, receipts, reviewed_rows)
    assert second_trace["row_bindings"][0]["status"] == ("bound" if reference_matches else "resource_review_required")
    assert trace["row_bindings"][0]["status"] == "bound"
    assert "resource_review_ref" not in rows[0]
