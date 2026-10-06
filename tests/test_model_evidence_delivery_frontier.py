"""Confirmed discovery bodies must survive later model read frames."""
import copy
import json
from types import SimpleNamespace

import pytest

from proxy.services.chat_evidence_application_service import bind_row_evidence_ids, confirm_model_read_delivery
from proxy.services.model_rag_grouped_evidence_service import prepare_model_read_replay


def _chunk(ref, body, **meta):
    return {"doc_name": "literal source", "content": body, "meta": {
        "model_evidence_ref": ref, "global_evidence_id": f"immutable-{ref}",
        "norm_key": f"key-{ref}", "norm_code": f"code-{ref}",
        "source_ref": f"source-{ref}", "source_sha256": "a" * 64,
        "edition": "literal edition", "base_type": "literal base", "body_status": "full",
        "model_read_tool": "search_sources", **meta}}


def test_discovery_frontier_survives_two_replays_without_citation():
    delivered = [_chunk(f"Q1.H{rank}", f"literal preview {rank}; quantities and conditions",
                        model_query_index=1, model_delivery_status="delivered",
                        normative_card_complete=False) for rank in range(1, 7)]
    unread = _chunk("Q2.H1", "retained but unread price body",
                    model_read_tool="search_pricebook_resources", model_delivery_status="prepared",
                    model_inventory_delivery_status="delivered", model_raw_body_retained=True,
                    body_status="deferred_capacity")
    chunks = [*delivered, unread]
    original = copy.deepcopy(chunks)
    for _ in range(2):
        plan = prepare_model_read_replay(chunks)
        rows = plan.required[1]["previously_shown_evidence_registry"]
        assert plan.exact_body_refs == [f"Q1.H{rank}" for rank in range(1, 7)]
        assert len(rows) == 6
        for row, chunk in zip(rows, delivered):
            assert row["content"].encode("utf-8") == chunk["content"].encode("utf-8")
            assert row["global_evidence_id"] == chunk["meta"]["global_evidence_id"]
            assert row["source_sha256"] == chunk["meta"]["source_sha256"]
            assert row["normative_card_complete"] is False
        assert plan.optional_body_refs == [["Q2.H1"]]
        assert unread["content"] not in json.dumps(plan.required)
        assert chunks == original


def test_delivered_legacy_pointer_without_retained_body_remains_unread():
    pointer = json.dumps(["Q1.H1", "deferred_capacity", "key", "code", "title", "m", "source"])
    plan = prepare_model_read_replay([_chunk("Q1.H1", pointer, body_status="deferred_capacity",
                                           model_delivery_status="delivered")])
    assert plan.required[1]["previously_shown_evidence_registry"] == []
    assert plan.exact_body_refs == []


@pytest.mark.parametrize("body_admitted", [False, True])
def test_inventory_confirmation_cannot_promote_retained_body_but_actual_body_is_preserved(body_admitted):
    body = "Literal retained preview: applicability, quantities, and resource conditions"
    raw = _chunk("Q1.H1", body, body_status="deferred_capacity",
                 model_delivery_status="prepared", model_inventory_delivery_status="prepared",
                 model_raw_body_retained=True, resources_complete=False,
                 resource_preview=[{"code": "literal-preview-only"}], resource_count=17,
                 normative_card_complete=False)
    chunk = SimpleNamespace(**copy.deepcopy(raw))
    receipt = {"evidence_refs": ["Q1.H1"], "model_delivery_status": "prepared"}
    confirm_model_read_delivery([chunk], [receipt], inventory_refs=["Q1.H1"],
                                body_refs=["Q1.H1"] if body_admitted else [])
    stored = copy.deepcopy(vars(chunk))

    plan = prepare_model_read_replay([chunk])

    assert chunk.meta["model_inventory_delivery_status"] == "delivered"
    assert chunk.meta["model_delivery_status"] == ("delivered" if body_admitted else "prepared")
    assert chunk.meta["body_status"] == "deferred_capacity"
    assert receipt["full_body_evidence_refs"] == (["Q1.H1"] if body_admitted else [])
    assert receipt["deferred_body_evidence_refs"] == ([] if body_admitted else ["Q1.H1"])
    if body_admitted:
        row, = plan.required[1]["previously_shown_evidence_registry"]
        assert plan.exact_body_refs == ["Q1.H1"]
        assert row["content"].encode("utf-8") == body.encode("utf-8")
        assert row["global_evidence_id"] == raw["meta"]["global_evidence_id"]
        assert row["source_sha256"] == raw["meta"]["source_sha256"]
        assert row["normative_card_complete"] is False
        assert row["normative_resources_status"] == "preview"
        assert plan.optional == plan.optional_body_refs == []
    else:
        assert plan.required[1]["previously_shown_evidence_registry"] == []
        assert plan.exact_body_refs == []
        assert body not in json.dumps(plan.required)
        assert plan.optional_body_refs == [["Q1.H1"]]
    assert vars(chunk) == stored
    assert chunk.content.encode("utf-8") == raw["content"].encode("utf-8")


@pytest.mark.parametrize("body_admitted,retained,expected_shown", [
    (True, True, True), (False, True, False),
    (True, False, False), (True, "true", False),
])
def test_confirmed_retained_body_is_available_to_citation_check_without_promoting_preview(
    body_admitted, retained, expected_shown,
):
    code = "ГЭСН20-01-001-01"
    raw = _chunk("Q1.H1", code + ": literal conditions and resource preview literal-preview-only",
                 norm_code=code, body_status="deferred_capacity", model_delivery_status="prepared",
                 model_raw_body_retained=retained, resources_complete=False,
                 resource_code="literal-preview-only",
                 resource_preview=[{"code": "literal-preview-only"}], resource_count=17,
                 normative_card_complete=False)
    chunk = SimpleNamespace(**copy.deepcopy(raw))
    confirm_model_read_delivery([chunk], inventory_refs=["Q1.H1"],
                                body_refs=["Q1.H1"] if body_admitted else [])
    stored = copy.deepcopy(vars(chunk))
    row = {"source_row": "PDF!R2", "row_role": "work", "norm_code": code,
           "resource_code": "literal-preview-only",
           "evidence_refs": ["Q1.H1"]}
    original = copy.deepcopy(row)

    bound, = bind_row_evidence_ids([row], [chunk])

    check = bound["_evidence_check"]
    if expected_shown:
        assert check.get("card_body_shown") is not False
        assert "deferred_card_refs" not in check
        assert check["citation_checkable"] is True
        assert check["code_not_in_refs"] is False
    elif body_admitted:
        assert check["card_body_shown"] is False
        assert check["deferred_card_refs"] == ["Q1.H1"]
    else:
        assert bound["_evidence_check"]["citation_checkable"] is False
        assert bound["_evidence_check"]["cited_ciphers"] == []
    assert bound["_resource_evidence_check"]["code_in_refs"] is expected_shown
    assert bound["evidence_bindings"] == {"Q1.H1": raw["meta"]["global_evidence_id"]}
    assert bound["norm_code"] == row["norm_code"]
    assert "normative_card_complete" not in bound
    assert "resources_complete" not in bound
    assert chunk.meta["resources_complete"] is False
    assert chunk.meta["normative_card_complete"] is False
    assert chunk.meta["body_status"] == "deferred_capacity"
    assert vars(chunk) == stored
    assert row == original
