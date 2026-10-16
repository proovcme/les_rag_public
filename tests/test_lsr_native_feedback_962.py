"""Calculator observations are recorded and replayed through the real chat path."""
from copy import deepcopy
import inspect
import json

import pytest

from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests import test_model_rag_sheet_evidence_reads as fixture


@pytest.mark.parametrize("uncheckable", ["unread", "foreign", "missing"])
def test_first_bind_recomputes_forged_nested_supply_checks_from_exact_shown_cards(uncheckable):
    from proxy.services import chat_evidence_application_service as app
    from tests.test_lsr_supply_retry_962 import NORM, _apply, _review, _row
    from tests.test_temporal_model_evidence_binding import _card, _OTHER

    authored = _row([_review(evidence_refs=["Q2.H1"])])
    authored["_separate_supply_review_evidence_checks"] = [{"index": 0, "selected_norm_body_shown": True}]
    authored["_separate_supply_review_evidence_bindings"] = {"0": {"Q2.H1": "forged"}}
    before = deepcopy(authored)
    cards = [_card("Q1.H1", "top-card", NORM)]
    if uncheckable != "missing":
        nested = _card("Q2.H1", "nested-card", _OTHER if uncheckable == "foreign" else NORM)
        if uncheckable == "unread":
            nested.meta.update(model_delivery_status="deferred", model_inventory_delivery_status="delivered",
                               body_status="deferred_capacity")
        cards.append(nested)
    bound = app.bind_row_evidence_ids([authored], cards, binding_phase="first")[0]
    assert bound["_separate_supply_review_evidence_checks"][0]["selected_norm_body_shown"] is False
    assert "forged" not in str(bound["_separate_supply_review_evidence_bindings"])
    assert any(item["code"] == "separate_supply_possible_overlap" for item in _apply(bound)["resource_binding_conflicts"])
    assert bound["resource_review"] == before["resource_review"] and authored == before


@pytest.mark.parametrize("original_available", [True, False])
def test_nested_supply_replay_retains_its_own_global_card_across_handle_reuse(original_available):
    from proxy.services import chat_evidence_application_service as app
    from tests.test_lsr_supply_retry_962 import NORM, _review, _row
    from tests.test_temporal_model_evidence_binding import _card, _OTHER

    authored = _row([_review(evidence_refs=["Q2.H1"])])
    before = deepcopy(authored)
    top = _card("Q1.H1", "top-card", NORM)
    original = _card("Q2.H1", "original-nested", NORM)
    saved = app.bind_row_evidence_ids([authored], [top, original], binding_phase="first")[0]
    assert saved["evidence_bindings"] == {"Q1.H1": "top-card"}
    assert saved["_separate_supply_review_evidence_bindings"] == {"0": {"Q2.H1": "original-nested"}}
    assert saved["_separate_supply_review_evidence_checks"][0]["selected_norm_body_shown"] is True
    saved_before = deepcopy(saved)
    later = [top, _card("Q2.H1", "different-nested", _OTHER)]
    if original_available:
        later.append(_card("Q9.H9", "original-nested", NORM))
    replayed = app.bind_row_evidence_ids([saved], later, binding_phase="replay")[0]
    assert replayed["_separate_supply_review_evidence_bindings"] == saved["_separate_supply_review_evidence_bindings"]
    assert replayed["_separate_supply_review_evidence_checks"][0]["selected_norm_body_shown"] is original_available
    assert replayed["resource_review"] == before["resource_review"] and saved == saved_before and authored == before
    prior, retained = app.model_rag_prior_page_context([saved], later)
    assert {chunk.meta["global_evidence_id"] for chunk in retained} == (
        {"top-card", "original-nested"} if original_available else {"top-card"})
    assert not any(key.startswith("_separate_supply") for key in prior["prior_model_decisions"][0])


@pytest.mark.asyncio
async def test_packaged_open_financial_facts_reach_the_next_engineer_review(tmp_path, monkeypatch):
    rows = [{"source_row": locator, "row_role": "work", "work_row": "", "title": title,
             "quantity": qty, "unit": "m", "norm_code": "", "norm_status": "MISSING",
             "open_gap": "Model has not selected a norm", "evidence_refs": []}
            for locator, title, qty in (("S!R2", "Cable A", 12), ("S!R3", "Cable B", 3))]
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False,
        query_declaration=json.dumps({"artifact_kind": "lsr", "queries": ["Literal norm search"]}),
        final_answer=json.dumps({"artifact_kind": "lsr", "rows": rows}))
    store = WorkbookResearchJobService()
    parent_id = run.result["retrieval_trace"]["workbook_research_job"]["job_id"]
    parent = store.get(parent_id)
    before = deepcopy(parent["accepted_rows"])
    snapshot = store.latest_financial_feedback(parent_id)
    assert snapshot["revision_id"] == run.result["artifact"]["revision_id"]
    assert {item["operation_id"] for item in snapshot["records"]} == {row["operation_id"] for row in before}
    assert all(item["projection"]["position_calculated"] is False for item in snapshot["records"])
    assert snapshot["price_basis"]["pricebook"] == fixture.BOOK
    assert snapshot["price_basis"]["pricebook_sha256"]

    request = inspect.getclosurevars(run.resume_same_request).nonlocals["request"]
    request.req.question = "Use the previous financial gaps to continue the same estimate"
    updated = [{**row, "expected_revision": row["revision"], "coverage": "Literal engineer clarification"}
               for row in before]
    native = fixture._native("build_lsr_workbook", attachment_id="read_123456abcdef", decisions=updated)
    run.responses.extend([
        InferenceResponse(text=json.dumps({"artifact_kind": "lsr", "queries": ["Literal revised norm search"]}),
                          tool_calls=(), finish_reason="stop", usage={}),
        InferenceResponse(text="", tool_calls=(native,), finish_reason="tool_calls", usage={}),
    ])
    result = await run.resume_same_request()
    assert len(run.requests) == 4 and not run.responses
    for request in run.requests[2:]:
        shown = "\n".join(str(message.get("content") or "") for message in request.messages)
        assert "financial_readiness" in shown and snapshot["revision_id"] in shown
    current = store.get(result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert current["continues_job_id"] == parent_id
    assert {row["operation_id"] for row in current["accepted_rows"]} == {row["operation_id"] for row in before}
    assert all(row["revision"] == 2 for row in current["accepted_rows"])
    assert store.get(parent_id)["accepted_rows"] == before
