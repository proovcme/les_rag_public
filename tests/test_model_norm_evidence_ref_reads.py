"""An explicit admitted alias selects a read, never a guessed norm or a verdict."""

import copy
import json
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as application
from proxy.services import model_research_tool_service as research
from proxy.services.model_evidence_read_contract import (
    MODEL_EVIDENCE_READ_INSTRUCTION, model_evidence_read_tool_schemas,
)
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from proxy.services.model_rag_grouped_evidence_service import EvidenceCard, inventory_pointer


CODE = "CODE-77-08-009-01"
IDENTITY = {"norm_key": "literal-immutable-key", "norm_code": CODE,
            "source_ref": "literal-catalog#guid=literal-card", "source_sha256": "a" * 64,
            "edition": "literal-edition", "base_type": "literal-base"}


@pytest.fixture(autouse=True)
def _isolate_catalog(monkeypatch):
    monkeypatch.setattr(research.nr_sp_service, "model_candidates", lambda **kwargs: [])


def _service(card=None):
    calls = []
    card = card or {**IDENTITY, "title": "Literal exact card", "measure_unit": "m",
                    "work_steps": ["Literal condition"], "resource_count": 1,
                    "resources": [{"code": "literal-resource", "unit": "m", "per_unit": 0.125}],
                    "resources_returned": 1, "resources_complete": True, "resource_consumption_known": True}

    def exact(**args):
        calls.append(args)
        return {"status": "ok", "card": copy.deepcopy(card), "missing": [], "warnings": []}

    return research.ModelResearchToolService(
        retrieve=lambda **kwargs: pytest.fail("No new search requested"), frozen_dataset_ids=(),
        retrieval_kwargs={}, fallback=lambda *args: pytest.fail("No fallback requested"),
        norm_card_reader=exact), calls


def _bound():
    raw = SimpleNamespace(doc_name="literal-catalog", score=1.0,
                          content=f"Cipher: {CODE}\n" + "HIDDEN RAW CONDITIONS " * 1000,
                          meta={**IDENTITY, "title": "Shown literal title", "measure_unit": "m"})
    call = {"tool": "search_sources", "args": {"q": "literal model query"}}
    result = research.ModelResearchToolResult(payload={"tool": "search_sources", "inputs": [call["args"]]},
                                            chunks=(raw,))
    receipt = {"call": call, "status": "ok"}
    _, chunks, _ = application.bind_model_requested_read_evidence(
        [result], existing_chunks=[], evidence_namespace="explicit-ref-test", receipts=[receipt])
    return chunks, receipt


def _admit(chunks, receipt):
    preset = ModelExecutionPreset(preset_id="explicit-ref-index", model_family="fixture",
        input_token_limit=4000, generation_reserve_tokens=0, safety_reserve_tokens=0,
        normal_tool_count=5, max_tools=5, max_batch_items=5, parallel_read_limit=1,
        reasoning_enabled=False, source_chain=("test",))
    messages, _, inventory, bodies = application.govern_model_read_messages(
        preset=preset, profile_prefix="literal profile", request_payload="literal question",
        source_context=["literal complete attachment"], chunks=chunks, receipts=[receipt])
    assert inventory and bodies == [] and "HIDDEN RAW CONDITIONS" not in str(messages)
    application.confirm_model_read_delivery(chunks, [receipt], inventory_refs=inventory, body_refs=bodies)


def test_existing_norm_read_schema_advertises_optional_exclusive_literal_evidence_ref():
    schema = next(item["function"] for item in model_evidence_read_tool_schemas()
                  if item["function"]["name"] == "read_norm_card")
    assert schema["parameters"]["properties"]["evidence_ref"]["type"] == "string"
    assert "evidence_ref" not in schema["parameters"]["required"]
    assert "alone" in schema["description"]
    assert "evidence_ref" in MODEL_EVIDENCE_READ_INSTRUCTION


@pytest.mark.asyncio
async def test_misused_source_row_receipt_points_only_to_exact_admitted_ref_then_reads_full_card():
    from proxy.services.model_evidence_read_service import evidence_read_receipt, native_evidence_read_exchange
    reader, calls = _service()
    chunks, receipt = _bound()
    ref = chunks[0].meta["model_evidence_ref"]
    wrong = {"call_id": "literal-wrong-tool", "tool": "read_source", "args": {"source_row": ref}}
    reader.register_shown_norm_cards(chunks)
    prepared = await reader.execute(wrong)
    assert prepared.chunks == () and calls == []
    assert not prepared.payload["trace"].get("previously_shown_norm_read")
    assert (await reader.execute({"tool": "read_norm_card", "args": {"evidence_ref": ref}})).chunks == ()
    _admit(chunks, receipt)
    reader.register_shown_norm_cards(chunks)
    original = copy.deepcopy(chunks)

    missing = await reader.execute(wrong)

    assert missing.payload["status"] == "missing" and missing.chunks == () and calls == []
    expected_call = {"tool": "read_norm_card", "args": {"evidence_ref": ref}}
    assert missing.payload["trace"]["previously_shown_norm_read"] == expected_call
    reply = native_evidence_read_exchange([wrong], [evidence_read_receipt(wrong, missing)]).as_messages()[-1]
    assert json.loads(reply["content"])["trace"]["previously_shown_norm_read"] == expected_call
    assert "HIDDEN RAW CONDITIONS" not in reply["content"]
    assert [vars(chunk) for chunk in chunks] == [vars(chunk) for chunk in original]
    full = await reader.execute(expected_call)
    assert calls == [{"norm_key": IDENTITY["norm_key"], "norm_code": CODE}]
    assert full.payload["status"] == "ok" and len(full.chunks) == 1
    assert full.payload["trace"]["previously_shown_pointer"]["evidence_ref"] == ref
    for field, value in IDENTITY.items():
        assert full.payload["trace"]["previously_shown_pointer"][field] == value
    assert full.payload["trace"]["previously_shown_pointer"]["global_evidence_id"] == chunks[0].meta["global_evidence_id"]
    assert full.chunks[0].meta["exact_card_read"] is True
    assert full.chunks[0].meta["normative_card_complete"] is True
    assert '"per_unit": 0.125' in full.chunks[0].content
    assert chunks[0].meta["model_delivery_status"] == "prepared"
    _, exact_chunks, _ = application.bind_model_requested_read_evidence(
        [full], existing_chunks=chunks, evidence_namespace="explicit-full-read")
    assert exact_chunks[0].meta["model_delivery_status"] == "prepared"
    assert exact_chunks[0].meta["global_evidence_id"] != chunks[0].meta["global_evidence_id"]
    application.confirm_model_read_delivery(exact_chunks, inventory_refs=[exact_chunks[0].meta["model_evidence_ref"]],
                                          body_refs=[exact_chunks[0].meta["model_evidence_ref"]])
    assert exact_chunks[0].meta["model_delivery_status"] == "delivered"
    assert chunks[0].meta["model_delivery_status"] == "prepared"


@pytest.mark.asyncio
@pytest.mark.parametrize("ref", ["Q999.H1", "q1.h1", " Q1.H1", "Q1.H1 ", "", None, ["Q1.H1"]])
async def test_ref_is_literal_without_whitespace_case_or_shape_repair(ref):
    reader, calls = _service()
    chunks, receipt = _bound()
    _admit(chunks, receipt)
    reader.register_shown_norm_cards(chunks)
    result = await reader.execute({"tool": "read_norm_card", "args": {"evidence_ref": ref}})
    assert result.payload["status"] in {"missing", "conflict"} and result.chunks == () and calls == []
    wrong = await reader.execute({"tool": "read_source", "args": {"source_row": ref}})
    assert not wrong.payload["trace"].get("previously_shown_norm_read") and calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("selectors", [{"norm_key": IDENTITY["norm_key"]}, {"norm_code": CODE},
                                       {"norm_key": "guessed-key"}, {"norm_code": "guessed-code"}])
async def test_evidence_ref_exclusive_policy_never_overrides_other_selectors(selectors):
    reader, calls = _service()
    chunks, receipt = _bound()
    _admit(chunks, receipt)
    reader.register_shown_norm_cards(chunks)
    result = await reader.execute({"tool": "read_norm_card", "args": {
        "evidence_ref": chunks[0].meta["model_evidence_ref"], **selectors}})
    assert result.payload["status"] == "conflict" and result.chunks == () and calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["global_evidence_id", "source_ref", "source_sha256", "edition",
                                    "base_type", "norm_key", "norm_code"])
async def test_duplicate_alias_with_changed_immutable_pointer_is_ambiguous(field):
    reader, calls = _service()
    chunks, receipt = _bound()
    _admit(chunks, receipt)
    duplicate = copy.deepcopy(chunks[0])
    duplicate.meta[field] = f"changed-{field}"
    duplicate.meta["model_inventory_view"] = inventory_pointer(EvidenceCard(
        duplicate.meta["model_evidence_ref"], duplicate.doc_name, "", "", duplicate.meta))
    reader.register_shown_norm_cards([*chunks, duplicate, *chunks])
    ref = chunks[0].meta["model_evidence_ref"]
    result = await reader.execute({"tool": "read_norm_card", "args": {"evidence_ref": ref}})
    assert result.payload["status"] == "conflict" and result.chunks == () and calls == []
    wrong = await reader.execute({"tool": "read_source", "args": {"source_row": ref}})
    assert not wrong.payload["trace"].get("previously_shown_norm_read") and calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["source_ref", "source_sha256", "edition", "base_type", "norm_key", "norm_code"])
@pytest.mark.parametrize("absent", [False, True])
async def test_exact_reader_must_match_each_known_immutable_field(field, absent):
    card = {**IDENTITY, "resources": [], "resources_returned": 0, "resources_complete": True}
    if absent:
        card.pop(field)
    else:
        card[field] = f"changed-{field}"
    reader, calls = _service(card)
    chunks, receipt = _bound()
    _admit(chunks, receipt)
    reader.register_shown_norm_cards(chunks)
    result = await reader.execute({"tool": "read_norm_card", "args": {
        "evidence_ref": chunks[0].meta["model_evidence_ref"]}})
    assert len(calls) == 1
    assert result.payload["status"] == "conflict" and result.chunks == ()
    assert result.payload["result"]["hits"] == [] and result.payload["result"]["count"] == 0


@pytest.mark.asyncio
async def test_ref_requires_explicit_delivery_and_consistent_literal_view():
    for changed in ({"model_inventory_delivery_status": "prepared"},
                    {"model_inventory_view": json.dumps(["Q99.H1", "deferred_capacity", IDENTITY["norm_key"], CODE, "title"])},
                    {"model_inventory_view": json.dumps(["Q1.H1", "deferred_capacity", "wrong-key", CODE, "title"])},
                    {"model_inventory_view": json.dumps(["Q1.H1", "deferred_capacity", IDENTITY["norm_key"], CODE, "title", "m", "wrong-source"])}):
        reader, calls = _service()
        chunks, receipt = _bound()
        _admit(chunks, receipt)
        chunks[0].meta.update(changed)
        reader.register_shown_norm_cards(chunks)
        result = await reader.execute({"tool": "read_norm_card", "args": {
            "evidence_ref": chunks[0].meta["model_evidence_ref"]}})
        assert result.payload["status"] in {"missing", "conflict"} and result.chunks == () and calls == []


@pytest.mark.asyncio
async def test_repeated_registration_is_idempotent_and_missing_optional_provenance_stays_missing():
    card = {"norm_key": IDENTITY["norm_key"], "norm_code": CODE, "source_ref": IDENTITY["source_ref"],
            "resources": [], "resources_returned": 0, "resources_complete": True}
    reader, calls = _service(card)
    chunks, receipt = _bound()
    for name in ("source_sha256", "edition", "base_type", "normative_card_identity"):
        chunks[0].meta.pop(name, None)
    _admit(chunks, receipt)
    reader.register_shown_norm_cards([*chunks, *chunks])
    reader.register_shown_norm_cards(chunks)
    result = await reader.execute({"tool": "read_norm_card", "args": {
        "evidence_ref": chunks[0].meta["model_evidence_ref"]}})
    assert result.payload["status"] == "ok" and len(calls) == 1
    assert "source_sha256" not in result.chunks[0].meta and "edition" not in result.chunks[0].meta


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [[], {}])
async def test_malformed_inventory_status_refuses_alias_without_crashing(status):
    reader, calls = _service()
    chunks, receipt = _bound()
    _admit(chunks, receipt)
    displayed = json.loads(chunks[0].meta["model_inventory_view"])
    displayed[1] = status
    chunks[0].meta["model_inventory_view"] = json.dumps(displayed)

    reader.register_shown_norm_cards(chunks)
    result = await reader.execute({"tool": "read_norm_card", "args": {
        "evidence_ref": chunks[0].meta["model_evidence_ref"]}})

    assert result.payload["status"] == "missing" and result.chunks == () and calls == []


@pytest.mark.asyncio
async def test_legacy_missing_delivery_flags_cannot_authorize_ref_or_diagnostic_but_keeps_key_semantics():
    reader, calls = _service()
    chunks, _ = _bound()
    for name in ("model_inventory_delivery_status", "model_delivery_status"):
        chunks[0].meta.pop(name)
    reader.register_shown_norm_cards(chunks)
    ref = chunks[0].meta["model_evidence_ref"]
    explicit = await reader.execute({"tool": "read_norm_card", "args": {"evidence_ref": ref}})
    assert explicit.payload["status"] == "missing" and explicit.chunks == () and calls == []
    wrong = await reader.execute({"tool": "read_source", "args": {"source_row": ref}})
    assert not wrong.payload["trace"].get("previously_shown_norm_read") and calls == []
    legacy = await reader.execute({"tool": "read_norm_card", "args": {"norm_key": IDENTITY["norm_key"]}})
    assert legacy.payload["status"] == "ok" and len(calls) == 1
