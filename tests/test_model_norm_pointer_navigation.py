"""Missing exact reads expose admitted literal navigation, never choose a norm."""

import json
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as application
from proxy.services import model_research_tool_service as research
from proxy.services.model_execution_preset_service import ModelExecutionPreset


PARENT = "CODE-12-03-004"


def _reader():
    calls = []
    def exact(**pointer):
        calls.append(pointer)
        return {"status": "ok", "card": {
            **pointer, "source_ref": "literal-source", "title": "Exact selected card",
            "resources": [{"code": "literal-resource", "unit": "m", "per_unit": 2.5}],
            "resources_complete": True, "resources_returned": 1}}
    return research.ModelResearchToolService(
        retrieve=lambda **_kw: pytest.fail("no retrieval for pointer navigation"),
        frozen_dataset_ids=(), retrieval_kwargs={},
        fallback=lambda *_a: pytest.fail("no fallback for pointer navigation"),
        norm_card_reader=exact), calls


def _bound_cards(versions=()):
    versions = versions or (("01", "source-a", "edition-a", "a" * 64),
                            ("02", "source-b", "edition-b", "b" * 64))
    raw = [SimpleNamespace(doc_name="literal-catalog", score=1.0,
        content=f"Шифр: {PARENT}-{suffix}\nНаименование: HIDDEN_RAW_TITLE\n" + "x" * 8000,
        meta={"norm_code": f"{PARENT}-{suffix}", "norm_key": f"key-{index}",
              "title": f"Shown literal title {index}", "source_ref": source,
              "source_sha256": sha, "edition": edition, "base_type": "literal-base"})
        for index, (suffix, source, edition, sha) in enumerate(versions)]
    call = {"tool": "search_sources", "args": {"q": "literal query"}}
    result = research.ModelResearchToolResult(payload={"tool": "search_sources", "inputs": [call["args"]]},
                                            chunks=tuple(raw))
    receipt = {"call": call, "status": "ok"}
    _, chunks, _ = application.bind_model_requested_read_evidence(
        [result], existing_chunks=[], evidence_namespace="navigation-test", receipts=[receipt])
    return chunks, receipt


def _admit_inventory(chunks, receipt):
    preset = ModelExecutionPreset(preset_id="navigation-index", model_family="fixture",
        input_token_limit=3000, generation_reserve_tokens=0, safety_reserve_tokens=0,
        normal_tool_count=5, max_tools=5, max_batch_items=5, parallel_read_limit=1,
        reasoning_enabled=False, source_chain=("test",))
    messages, _, inventory, bodies = application.govern_model_read_messages(
        preset=preset, profile_prefix="profile", request_payload="literal model question",
        source_context=["literal attachment"], chunks=chunks, receipts=[receipt])
    assert inventory and bodies == [] and "HIDDEN_RAW_TITLE" not in str(messages)
    application.confirm_model_read_delivery(chunks, [receipt], inventory_refs=inventory, body_refs=bodies)


@pytest.mark.asyncio
async def test_parent_code_returns_only_literal_admitted_siblings_without_reading_card():
    reader, calls = _reader()
    chunks, receipt = _bound_cards()
    reader.register_shown_norm_cards(chunks)
    before = await reader.execute({"tool": "read_norm_card", "args": {"norm_code": PARENT}})
    assert before.payload["status"] == "missing" and calls == []
    assert not before.payload["trace"].get("previously_shown_exact_options")
    _admit_inventory(chunks, receipt)
    reader.register_shown_norm_cards(chunks)
    result = await reader.execute({"tool": "read_norm_card", "args": {"norm_code": PARENT}})
    assert result.payload["status"] == "missing" and result.chunks == () and calls == []
    assert result.payload["result"]["hits"] == [] and result.payload["result"]["count"] == 0
    assert result.payload["decision_required_from_model"] is True
    options = result.payload["trace"]["previously_shown_exact_options"]
    assert [option["norm_code"] for option in options] == [PARENT + "-01", PARENT + "-02"]
    assert [option["evidence_ref"] for option in options] == [chunk.meta["model_evidence_ref"] for chunk in chunks]
    assert [option["title"] for option in options] == ["Shown literal title 0", "Shown literal title 1"]
    assert "HIDDEN_RAW_TITLE" not in json.dumps(result.payload)
    assert all(chunk.meta["model_delivery_status"] == "prepared" for chunk in chunks)
    from proxy.services.model_evidence_read_service import evidence_read_receipt, native_evidence_read_exchange
    native_call = {"call_id": "literal-parent-read", "tool": "read_norm_card", "args": {"norm_code": PARENT}}
    native_receipt = evidence_read_receipt(native_call, result)
    reply = native_evidence_read_exchange([native_call], [native_receipt]).as_messages()[-1]
    assert json.loads(reply["content"])["trace"]["previously_shown_exact_options"] == options
    assert "HIDDEN_RAW_TITLE" not in reply["content"] and calls == []


@pytest.mark.asyncio
async def test_parent_navigation_preserves_each_alias_source_edition_and_immutable_identity():
    reader, calls = _reader()
    chunks, receipt = _bound_cards((("01", "source-a", "edition-a", "a" * 64),
                                   ("01", "source-b", "edition-a", "b" * 64),
                                   ("01", "source-a", "edition-b", "a" * 64)))
    _admit_inventory(chunks, receipt)
    reader.register_shown_norm_cards(chunks)
    result = await reader.execute({"tool": "read_norm_card", "args": {"norm_code": PARENT}})
    options = result.payload["trace"]["previously_shown_exact_options"]
    assert len(options) == 3 and calls == [] and result.payload["status"] == "missing"
    for option, chunk in zip(options, chunks):
        for field in ("norm_key", "source_ref", "source_sha256", "edition", "base_type",
                      "normative_card_identity", "global_evidence_id"):
            assert option[field] == chunk.meta[field]
    assert len({option["normative_card_identity"] for option in options}) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("requested", ["OTHER-12-03-004", "CODE-12-03-00", PARENT + "0", PARENT.lower()])
async def test_navigation_requires_the_literal_code_and_dash_boundary(requested):
    reader, calls = _reader()
    chunks, receipt = _bound_cards()
    _admit_inventory(chunks, receipt)
    reader.register_shown_norm_cards(chunks)
    result = await reader.execute({"tool": "read_norm_card", "args": {"norm_code": requested}})
    assert result.payload["status"] == "missing" and calls == [] and result.chunks == ()
    assert not result.payload["trace"].get("previously_shown_exact_options")


@pytest.mark.asyncio
async def test_navigation_does_not_override_a_conflicting_explicit_key():
    reader, calls = _reader()
    chunks, receipt = _bound_cards()
    _admit_inventory(chunks, receipt)
    reader.register_shown_norm_cards(chunks)
    result = await reader.execute({"tool": "read_norm_card", "args": {"norm_code": PARENT, "norm_key": "unshown-key"}})
    assert result.payload["status"] == "conflict" and calls == [] and result.chunks == ()
    assert not result.payload["trace"].get("previously_shown_exact_options")


@pytest.mark.asyncio
async def test_literal_full_code_still_executes_only_the_models_exact_read(monkeypatch):
    monkeypatch.setattr(research.nr_sp_service, "model_candidates", lambda **_kw: [])
    reader, calls = _reader()
    chunks, receipt = _bound_cards()
    _admit_inventory(chunks, receipt)
    reader.register_shown_norm_cards(chunks)
    result = await reader.execute({"tool": "read_norm_card", "args": {"norm_code": PARENT + "-02"}})
    assert calls == [{"norm_key": "key-1", "norm_code": PARENT + "-02"}]
    assert result.payload["status"] == "ok" and len(result.chunks) == 1
    assert '"per_unit": 2.5' in result.chunks[0].content
    assert "previously_shown_exact_options" not in result.payload["trace"]
