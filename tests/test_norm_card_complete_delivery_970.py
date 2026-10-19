"""Actual preview delivery cannot discharge the selected full-norm read debt."""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services import norm_card_proof_service as proof
from proxy.services.lsr_norm_quality_gate_service import applicability_gap_kind
from proxy.services.model_rag_grouped_evidence_service import card_delivery_facts
from proxy.services.openai_compatible_transport_service import InferenceResponse
from tests.test_model_rag_sheet_evidence_reads import NORM_CODE, _native, _run_sheet
from tests.test_norm_card_proof_request_930 import _shown_chunk


FIELD = "normative_card_complete"


def _row(ref="Q1.H1"):
    return {"source_row": "S!R2", "row_role": "work", "title": "Literal work",
            "unit": "m", "quantity": 12, "norm_code": NORM_CODE,
            "norm_status": "EXACT_VERIFIED", "evidence_refs": [ref],
            **{key: "yes" for key in ("action_match", "object_match", "condition_match", "unit_compatible", "composition_covers")}}


def _preview(code=NORM_CODE):
    meta = {"norm_key": "immutable-norm", "norm_code": code, "source_ref": "fixture#immutable-norm",
            "work_steps": ["Install"], "resource_count": 1,
            "resource_preview": [{"code": "R1", "name": "Literal resource", "unit": "m"}]}
    content = f"Шифр: {code}\nСостав работы: Install\nРесурсы нормы (обзор): R1 Literal resource m"
    hit = SimpleNamespace(meta=meta, content=content, doc_id="fixture-card", doc_name="smeta_norm_cards.v1", score=1)
    _, chunks, omitted = service.build_model_rag_evidence_groups([("literal model query", [hit])], max_chars=100000, hits_per_query=1)
    assert not omitted and len(chunks) == 1
    assert chunks[0].meta[FIELD] is False and chunks[0].meta["body_status"] == "full"
    return chunks[0]


def _complete_other_alias(preview, *, edition=None):
    chunk = deepcopy(preview)
    chunk.meta.update(model_evidence_ref="Q9.H1", global_evidence_id="explicit-full-read", model_read_tool="read_norm_card",
                      model_delivery_status="delivered", body_status="full", resources_complete=True, resources_returned=1,
                      resources=[{"code": "R1", "name": "Literal resource", "unit": "m", "per_unit": 2}])
    if edition is not None:
        chunk.meta["edition"] = edition
    chunk = replace(chunk, content=f'Шифр: {NORM_CODE}\nСостав работы: Install\nliteral_resources_v1={{"records":[["R1","m",2]]}}')
    chunk.meta.update(card_delivery_facts(chunk.meta, raw_body_shown=True, displayed_body=chunk.content))
    assert chunk.meta[FIELD] is True
    return chunk


def test_actual_projection_preview_debt_preserves_body_code_and_status():
    row, chunk = _row(), _preview(); original = deepcopy(row)
    bound = service.bind_row_evidence_ids([row], [chunk], binding_phase="first")[0]
    check = bound["_evidence_check"]
    assert chunk.meta["card_body_shown"] is True
    assert check["card_body_shown"] is False
    assert check["card_body_shown_basis"] == "normative_card_incomplete_preview"
    assert proof.unread_chosen_norm_rows([bound]) == [bound]
    assert proof.unread_chosen_norm_refs([bound], chunks=[chunk]) == ["Q1.H1"]
    assert applicability_gap_kind(bound) == "norm_card_body_unread"
    assert bound["norm_code"] == row["norm_code"] and bound["norm_status"] == row["norm_status"]
    assert row == original
    message = proof.proof_request_message(["Q1.H1"], [bound])
    assert "normative_card_complete=false" in message and "read_norm_card" in message and "Q1.H1" in message


def test_backend_resource_completeness_cannot_erase_actual_preview_delivery_fact():
    chunk = _preview()
    chunk.meta.update(resources_complete=True, resources_returned=1,
                      resources=[{"code": "R1", "unit": "m", "per_unit": 2}])
    bound = service.bind_row_evidence_ids([_row()], [chunk], binding_phase="first")[0]
    assert bound["_evidence_check"]["card_body_shown"] is False


@pytest.mark.parametrize("other_edition", [False, True])
def test_only_full_same_immutable_identity_discharges_preview_debt(other_edition):
    preview = _preview(); full = _complete_other_alias(preview, edition="different" if other_edition else None)
    first = service.bind_row_evidence_ids([_row()], [preview], binding_phase="first")[0]
    rebound = service.bind_row_evidence_ids([first], [preview, full], binding_phase="replay")[0]
    assert rebound["_evidence_check"]["card_body_shown"] is (not other_edition)
    assert proof.unread_chosen_norm_refs([rebound], chunks=[preview, full]) == (["Q1.H1"] if other_edition else [])
    assert rebound["norm_code"] == first["norm_code"] and rebound["evidence_bindings"] == first["evidence_bindings"]


def test_unknown_or_absent_completeness_keeps_legacy_body_contract():
    for fact in (None, 0, "false", "absent"):
        chunk = _shown_chunk("Q1.H1", NORM_CODE, identity="legacy")
        if fact != "absent": chunk.meta[FIELD] = fact
        bound = service.bind_row_evidence_ids([_row()], [chunk], binding_phase="first")[0]
        assert bound["_evidence_check"]["card_body_shown"] is True
        assert FIELD not in bound["_evidence_check"]
        assert proof.unread_chosen_norm_rows([bound]) == []


def test_unknown_ref_and_ambiguous_cited_identity_do_not_invent_completeness():
    preview = _preview()
    unknown = service.bind_row_evidence_ids([_row("Q99.H1")], [preview], binding_phase="first")[0]
    assert FIELD not in unknown["_evidence_check"] and unknown["evidence_bindings"] == {}
    conflicting = deepcopy(preview)
    conflicting.meta.update(model_evidence_ref="Q9.H1", norm_code="ГЭСН99-99-999-99", norm_key="different-card")
    bound = service.bind_row_evidence_ids([_row()], [preview, conflicting], binding_phase="first")[0]
    assert bound["_evidence_check"].get("card_body_shown_basis") != "normative_card_incomplete_preview"

    # A unique typed identity A cannot prove the literal shown cipher B.
    contradictory = _preview()
    other_code = "ГЭСН99-99-999-99"
    contradictory = replace(contradictory, content=contradictory.content.replace(NORM_CODE, other_code))
    full_a = _complete_other_alias(_preview())
    wrong_literal = service.bind_row_evidence_ids([{**_row(), "norm_code": other_code}],
                                                  [contradictory, full_a], binding_phase="first")[0]
    assert wrong_literal["_evidence_check"]["code_not_in_refs"] is False
    assert wrong_literal["_evidence_check"]["card_body_shown"] is False
    assert wrong_literal["_evidence_check"]["card_body_shown_basis"] != "complete_normative_card_delivered"


def test_model_cannot_spoof_application_owned_completeness_or_refs():
    raw = {**_row(), "_evidence_check": {FIELD: True}, FIELD: True, "evidence_bindings": {"Q1.H1": "forged"}}
    parsed = service.parse_model_rag_result(json.dumps({"rows": [raw]}, ensure_ascii=False))
    row = parsed[1][0]
    assert "_evidence_check" not in row and FIELD not in row and "evidence_bindings" not in row
    bound = service.bind_row_evidence_ids([row], [_preview()], binding_phase="first")[0]
    assert bound["_evidence_check"]["card_body_shown"] is False


ANSWER = (
    "artifact_kind: lsr\n\n"
    "| source_row | row_role | title | unit | quantity | norm_code | norm_status | evidence_refs |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
    f"| S!R2 | work | Cable A | m | 12 | {NORM_CODE} | EXACT | Q1.H1 |\n"
    f"| S!R3 | work | Cable B | m | 3 | {NORM_CODE} | EXACT | Q1.H1 |"
)


@pytest.mark.asyncio
@pytest.mark.parametrize("read_full", [False, True])
async def test_native_route_has_one_existing_proof_and_no_norm_substitution(tmp_path, monkeypatch, read_full):
    replies = ([InferenceResponse(text="", tool_calls=(_native("read_norm_card", evidence_ref="Q1.H1"),),
                                  finish_reason="tool_calls", usage={})] if read_full else [])
    replies.append(InferenceResponse(text=ANSWER, tool_calls=(), finish_reason="stop", usage={"completion_tokens": 120}))
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant="B1_CANDIDATE",
                           final_answer=ANSWER, proof_replies=replies)
    trace = run.result["retrieval_trace"]
    assert len(trace["norm_card_proof_requests"]) == 1
    assert trace["norm_card_proof_requests"][0]["refs"] == ["Q1.H1"]
    assert len(run.requests) == (4 if read_full else 3) and not run.responses
    assert len(run.exact_reads) == int(read_full)
    rows = trace["model_result"]["decision_rows"]
    assert [row["norm_code"] for row in rows] == [NORM_CODE, NORM_CODE]
    assert [row["quantity"] for row in rows] == [12, 3]
    assert all(row["_evidence_check"]["card_body_shown"] is read_full for row in rows)


def test_actual_bound_preview_cannot_confirm_or_complete_even_with_known_norm_and_prices(monkeypatch):
    from tests.test_rim_lsr_trace_service import _active_resource_norm, _ChosenBook
    from tests.lsr_citation_support import issued_norm_metadata
    from proxy.services import gesn_service
    from proxy.services.model_research_tool_service import _norm_card_content, _full_norm_card_content
    from proxy.services.model_resource_reference_service import resource_slot_records
    from proxy.services.rim_lsr_trace_service import build_lsr_trace_from_visible_rows

    # Both branches use one literal authored choice, one issued generation and
    # one selected book. Only the actually delivered card completeness differs.
    row = _active_resource_norm(monkeypatch)
    authored = {**row, "evidence_refs": ["Q1.H1"],
                **{key: "yes" for key in ("action_match", "object_match", "condition_match",
                                         "unit_compatible", "composition_covers")},
                "coverage": "Fixture: operation, object, conditions, unit and composition match."}
    original_authored = deepcopy(authored)
    norm = gesn_service.get_norm(authored["norm_code"])
    resources = deepcopy(norm["resources"])
    assert len(resources) == 2 and {item["code"] for item in resources} == {"A-1", "A-10"}
    issued = issued_norm_metadata(norm)
    book = _ChosenBook({"A-1": 777.0, "A-10": 888.0}, units={"A-1": "m", "A-10": "m"})
    card = {**issued, "title": norm["name"], "measure_unit": norm["unit"],
            "source_ref": "fixture#chosen-two-resource-norm", "work_steps": ["Install"],
            "resource_count": len(resources),
            "resource_preview": [{key: item[key] for key in ("kind", "code", "name", "unit")}
                                 for item in resources]}
    hit = SimpleNamespace(meta=deepcopy(card), content=_norm_card_content(card),
                          doc_id="fixture-priced-card", doc_name="smeta_norm_cards.v1", score=1)
    _, chunks, omitted = service.build_model_rag_evidence_groups(
        [("literal model norm query", [hit])], max_chars=100000, hits_per_query=1)
    assert not omitted and len(chunks) == 1
    preview = chunks[0]
    assert preview.meta[FIELD] is False and preview.meta["card_body_shown"] is True

    # Use the native reader's exact body producer and actual two resource records;
    # no unrelated NORM_CODE or dummy R1 resource can stand in for this row.
    full_card = {**card, "resources": resources, "resources_returned": len(resources),
                 "resources_complete": True, "resource_consumption_known": True}
    full_body = _full_norm_card_content(full_card)
    full_meta = {**deepcopy(preview.meta), **deepcopy(full_card),
                 "resources": resource_slot_records(full_card), "exact_card_read": True,
                 "model_read_tool": "read_norm_card", "model_delivery_status": "delivered",
                 "body_status": "full"}
    full_meta.update(card_delivery_facts(full_meta, raw_body_shown=True, displayed_body=full_body))
    assert full_meta[FIELD] is True and full_meta["resources_returned"] == len(full_meta["resources"]) == 2
    full = replace(preview, content=full_body, meta=full_meta)
    complete_row = service.bind_row_evidence_ids([authored], [full], binding_phase="first")[0]
    assert complete_row["_evidence_check"]["card_body_shown"] is True
    baseline = build_lsr_trace_from_visible_rows([complete_row], pricebook=book)
    complete_summary = baseline["summary"]
    complete_position = baseline["sections"][0]["positions"][0]
    assert complete_summary["normative_generation_conflicts"] == 0
    assert complete_summary["positions_built"] == complete_summary["calculated_positions"] == 1
    assert complete_summary["confirmed_amount"] > 0 and complete_summary["preliminary_amount"] == 0
    assert complete_summary["full_amount"] == complete_summary["confirmed_amount"] == complete_summary["total"]
    assert complete_summary["result_status"] == "priced_final"
    assert complete_position["summary"]["completeness_reasons"] == []
    assert complete_position["summary"]["card_priced_resources"] == []
    assert baseline["row_bindings"][0]["readiness"]["applicability_substantiated"] is True

    preview_row = service.bind_row_evidence_ids([authored], [preview], binding_phase="first")[0]
    assert preview_row["_evidence_check"]["card_body_shown"] is False
    assert preview_row["_evidence_check"]["card_body_shown_basis"] == "normative_card_incomplete_preview"
    result = build_lsr_trace_from_visible_rows([preview_row], pricebook=book)
    summary = result["summary"]
    position = result["sections"][0]["positions"][0]
    assert summary["normative_generation_conflicts"] == 0 and summary["positions_built"] == 1
    assert summary["calculated_positions"] == 0 and summary["confirmed_amount"] == 0
    assert summary["full_amount"] is None and summary["result_status"] == "priced_partial"
    # The same money is retained, now preliminary because this card was not read.
    assert summary["preliminary_amount"] == complete_summary["confirmed_amount"] == summary["total"]
    assert position["summary"]["completeness_reasons"] == ["norm_card_body_unread"]
    assert position["summary"]["card_priced_resources"] == []
    assert result["row_bindings"][0]["readiness"]["applicability_substantiated"] is False
    assert authored == original_authored
    assert all(complete_row[key] == preview_row[key] == original_authored[key] for key in original_authored)
    assert complete_row["_evidence_check"]["norm_key"] == preview_row["_evidence_check"]["norm_key"] == issued["norm_key"]
    assert complete_row["_evidence_check"]["normative_base_sha256"] == preview_row["_evidence_check"]["normative_base_sha256"] == issued["normative_base_sha256"]
    assert preview.meta[FIELD] is False and preview.meta["card_body_shown"] is True
