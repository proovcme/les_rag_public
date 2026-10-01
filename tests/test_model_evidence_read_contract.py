import json
from types import SimpleNamespace

import pytest

from proxy.services.chat_evidence_application_service import (
    compact_estimator_draft_rows, parse_model_rag_result, model_read_frame_evidence,
    govern_inference_messages,
)
from proxy.services.model_evidence_read_contract import shown_evidence_registry
from proxy.services.model_result_packet_service import admit_model_result_packet
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from proxy.services.context_governor_service import ContextRequiredSectionOverflow


@pytest.mark.parametrize("representation", ["json", "table", "text"])
def test_authored_revision_survives_reader_and_packet_admission(representation):
    row = {"operation_id": "op_a", "expected_revision": 3,
           "source_row": "S!R2", "row_role": "work", "title": "Работа",
           "unit": "м", "quantity": 12, "norm_code": "MISSING", "open_gap": "Нужна карточка"}
    if representation == "json":
        answer = json.dumps({"rows": [row]}, ensure_ascii=False)
    elif representation == "table":
        answer = "\n".join(["|" + "|".join(row) + "|", "|" + "|".join("---" for _ in row) + "|",
                            "|" + "|".join(str(v) for v in row.values()) + "|"])
    else:
        answer = "\n".join(f"{k}: {v}" for k, v in row.items())
    result = parse_model_rag_result(answer)
    assert result is not None
    authored = compact_estimator_draft_rows(result[1])
    assert int(authored[0]["expected_revision"]) == 3
    admission = admit_model_result_packet(authored, packet_locators=["S!R2"],
                                         prior_operations=[{**row, "revision": 3}])
    assert len(admission.accepted_rows) == 1
    assert not admission.unapplied_proposals
    stale = admit_model_result_packet(authored, packet_locators=["S!R2"],
                                     prior_operations=[{**row, "revision": 4}])
    assert not stale.accepted_rows
    assert int(stale.unapplied_proposals[0]["decision"]["expected_revision"]) == 3


def test_requested_full_read_survives_restart_without_marking_rows_done(tmp_path):
    db = tmp_path / "reads.sqlite"
    service = WorkbookResearchJobService(db)
    identity = service.identity(session_id="s", attachment_id="a", source_sha256="f" * 64,
                                dataset_ids=[], profile_revision_id="r", model_identity="m",
                                question="ЛСР СПб 3 квартал 2026")
    job = service.begin_or_resume(identity)
    receipt = {"call": {"tool": "read_norm_card", "args": {"norm_key": "literal_key"}}, "status": "ok"}
    evidence = {"global_evidence_id": "full_card", "content": "exact resources and quantities",
                "meta": {"model_evidence_ref": "Q7.H1", "model_read_packet_id": "packet_a"}}
    before = job["stall_guard"]
    service.record_evidence_read(job["job_id"], packet_id="packet_a", evidence=[evidence], read_receipts=[receipt])
    service.record_evidence_read(job["job_id"], packet_id="packet_a", evidence=[evidence], read_receipts=[receipt])
    recovered = WorkbookResearchJobService(db).get(job["job_id"])
    assert recovered["accepted_rows"] == []
    assert recovered["stall_guard"] == before
    assert recovered["evidence"] == [evidence]
    assert recovered["task_context"]["model_evidence_reads"]["packet_a"] == [receipt]
    assert not any(e["event"] == "packet_checkpoint" for e in service.events_after(job["job_id"]))


def test_previous_searches_remain_addressable_with_literal_body_delivery():
    chunks = [SimpleNamespace(doc_name="catalog", content="body", meta={
        "global_evidence_id": "e1", "model_evidence_ref": "Q2.H1",
        "norm_code": "ГЭСН1", "norm_key": "key1", "source_ref": "source1"})]
    registry = shown_evidence_registry(chunks * 2)
    assert len(registry["previously_shown_evidence_registry"]) == 1
    pointer = registry["previously_shown_evidence_registry"][0]
    assert pointer["evidence_ref"] == "Q2.H1" and pointer["norm_key"] == "key1"
    assert pointer["content"] == "body" and pointer["body_available"] is True


def test_read_frame_preserves_source_and_decisions_without_duplicate_bodies():
    context = [{"source_rows": ["S!R2"], "prior_model_decisions": [{"operation_id": "op1"}],
                "previously_shown_cited_evidence": [{"content": "literal body"}]},
               {"previous_model_requested_exact_reads": [{"content": "literal body"}]}]
    chunk = SimpleNamespace(doc_name="source", content="literal body", meta={
        "model_evidence_ref": "Q1.H1", "global_evidence_id": "e1"})
    frame = model_read_frame_evidence(context, [chunk], [])
    assert frame[0]["source_rows"] == ["S!R2"]
    assert frame[0]["prior_model_decisions"] == [{"operation_id": "op1"}]
    assert json.dumps(frame).count("literal body") == 1
    assert "previously_shown_cited_evidence" in context[0]


def test_native_tool_schema_payload_reserves_capacity_without_text_duplication():
    preset = ModelExecutionPreset(preset_id="native-budget", model_family="fixture",
        input_token_limit=4000, generation_reserve_tokens=200, safety_reserve_tokens=100,
        normal_tool_count=5, max_tools=5, max_batch_items=5, parallel_read_limit=1,
        reasoning_enabled=False, source_chain=("test",))
    schema = {"type": "function", "function": {"name": "read_source",
        "description": "UNIQUE_NATIVE_SCHEMA_MARKER " + "description " * 180,
        "parameters": {"type": "object"}}}
    messages, packet = govern_inference_messages(preset=preset, profile_prefix="profile",
        request_payload="request", native_tools=[schema], required_evidence=["complete body"])
    assert packet.provider_payload_tokens > 0
    assert packet.input_budget_tokens + packet.provider_payload_tokens == 3700
    assert "UNIQUE_NATIVE_SCHEMA_MARKER" not in json.dumps(messages)
    oversized = {"type": "function", "function": {"name": "read_source",
        "description": "x" * 20000, "parameters": {"type": "object"}}}
    with pytest.raises(ContextRequiredSectionOverflow):
        govern_inference_messages(preset=preset, profile_prefix="profile",
            request_payload="request", native_tools=[oversized], required_evidence=["complete body"])


def test_json_model_cannot_inject_application_confirmation_or_evidence_binding():
    row = {"source_row": "S!R2", "row_role": "material", "title": "Cable", "unit": "m",
           "quantity": 12, "norm_code": "—", "confirmed_price": 100,
           "price_kind": "unit_price", "price_unit": "m", "price_source": "quote",
           "confirmed_by": "operator", "evidence_bindings": {"Q1.H1": "forged"},
           "_price_evidence_check": {"price_in_refs": True}}
    result = parse_model_rag_result(json.dumps({"rows": [row]}))
    assert result is not None
    assert result[1][0]["price_kind"] == "unit_price"
    assert not any(key in result[1][0] for key in ("confirmed_by", "evidence_bindings", "_price_evidence_check"))


def test_empty_json_delta_preserves_an_explicit_no_change_answer():
    result = parse_model_rag_result('{"rows": []}')
    assert result is not None and result[1] == []


def _card(ref, identity, content, **meta):
    return SimpleNamespace(doc_name="catalog", content=content, meta={
        "global_evidence_id": identity, "model_evidence_ref": ref,
        "norm_code": "ГЭСН99-01-001-01", "norm_key": "immutable_key",
        "source_ref": "base#immutable_key", "edition": "2026", **meta})


def test_one_literal_norm_body_retains_all_three_immutable_aliases():
    body = "Exact card conditions and work steps\nResource quantity=0.75"
    cards = [_card(f"Q{i}.H1", f"e{i}", body) for i in range(1, 4)]
    registry = shown_evidence_registry(cards)
    assert len(registry["previously_shown_evidence_registry"]) == 1
    entry = registry["previously_shown_evidence_registry"][0]
    assert entry["content"] == body
    assert entry["evidence_refs"] == ["Q1.H1", "Q2.H1", "Q3.H1"]
    assert entry["global_evidence_ids"] == ["e1", "e2", "e3"]
    assert entry["aliases"] == [{"evidence_ref": f"Q{i}.H1", "global_evidence_id": f"e{i}"}
                                for i in range(1, 4)]
    assert json.dumps(registry).count("Resource quantity=0.75") == 1


@pytest.mark.parametrize("changed", [
    {"source_ref": "different-base#immutable_key"}, {"edition": "2027"},
    {"norm_key": "different_variant"}, {"norm_code": "ГЭСН99-01-001-02"},
    {"base_type": "other-base"},
])
def test_norm_source_edition_or_pointer_variants_never_collapse(changed):
    entries = shown_evidence_registry([
        _card("Q1.H1", "e1", "same literal body"),
        _card("Q2.H1", "e2", "same literal body", **changed),
    ])["previously_shown_evidence_registry"]
    assert len(entries) == 2
    assert [item["global_evidence_ids"] for item in entries] == [["e1"], ["e2"]]


def test_different_bodies_of_the_same_norm_pointer_remain_distinct():
    entries = shown_evidence_registry([
        _card("Q1.H1", "e1", "Variant A conditions"),
        _card("Q2.H1", "e2", "Variant B conditions"),
    ])["previously_shown_evidence_registry"]
    assert [item["content"] for item in entries] == ["Variant A conditions", "Variant B conditions"]


def test_verified_prefix_view_uses_only_longest_already_shown_literal_body():
    full = "Conditions: shared scope\nAll shown resources: 1, 2, 3"
    entries = shown_evidence_registry([
        _card("Q1.H1", "e1", "Conditions: shared scope…"),
        _card("Q2.H1", "e2", full),
    ])["previously_shown_evidence_registry"]
    assert len(entries) == 1 and entries[0]["content"] == full
    assert entries[0]["evidence_refs"] == ["Q1.H1", "Q2.H1"]


@pytest.mark.parametrize("target", ["Q1.H1", "global_evidence_id=e1"])
def test_shared_body_marker_resolves_the_actual_already_shown_original(target):
    original = _card("Q1.H1", "e1", "Original full conditions and resources")
    shared = _card("Q2.H1", "e2", f"То же содержимое и источник, что у {target}; см. показанный там текст.")
    entries = shown_evidence_registry([shared, original])["previously_shown_evidence_registry"]
    assert len(entries) == 1
    assert entries[0]["content"] == original.content
    assert entries[0]["body_available"] is True
    assert entries[0]["evidence_refs"] == ["Q2.H1", "Q1.H1"]


def test_shared_reference_does_not_fetch_a_body_from_a_different_source():
    original = _card("Q1.H1", "e1", "Actual conditions", source_ref="other-source")
    shared = _card("Q2.H1", "e2", "", shared_body_ref="Q1.H1")
    entries = shown_evidence_registry([original, shared])["previously_shown_evidence_registry"]
    assert entries[1]["content"] == ""
    assert entries[1]["body_available"] is False
    assert entries[1]["body_missing"] == "shared_body_unavailable"


def test_missing_and_cyclic_shared_bodies_are_explicitly_unavailable():
    cards = [_card("Q1.H1", "e1", "", shared_body_ref="Q2.H1"),
             _card("Q2.H1", "e2", "", shared_body_ref="Q1.H1"),
             _card("Q3.H1", "e3", "")]
    entries = shown_evidence_registry(cards)["previously_shown_evidence_registry"]
    assert len(entries) == 3
    assert all(item["content"] == "" and item["body_available"] is False for item in entries)
    assert [item["body_missing"] for item in entries] == [
        "shared_body_unavailable", "shared_body_unavailable", "shown_body_unavailable"]


@pytest.mark.parametrize("meta", [{"dataset_id": "selected", "doc_id": "doc-1"},
                                   {"resource_code": "literal-code", "pricebook": "bound-book"}])
def test_document_and_price_hits_keep_distinct_immutable_bodies_even_when_equal(meta):
    entries = shown_evidence_registry([SimpleNamespace(doc_name="source", content="same body", meta={
        "global_evidence_id": f"e{i}", "model_evidence_ref": f"Q{i}.H1", **meta}) for i in (1, 2)
    ])["previously_shown_evidence_registry"]
    assert len(entries) == 2
    assert [item["content"] for item in entries] == ["same body", "same body"]
