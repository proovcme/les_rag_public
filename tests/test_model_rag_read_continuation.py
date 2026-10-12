"""Whole-object continuation contracts for model-addressed normative reads."""

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.context_governor_service import (
    ContextGovernor,
    ContextRequiredSectionOverflow,
)
from proxy.services.model_execution_preset_service import ModelExecutionPreset


def preset(input_tokens=2000):
    return ModelExecutionPreset(
        preset_id="read-continuation-test", model_family="fixture",
        input_token_limit=input_tokens, generation_reserve_tokens=20,
        safety_reserve_tokens=20, normal_tool_count=3, max_tools=5,
        max_batch_items=5, parallel_read_limit=1, reasoning_enabled=False,
        source_chain=("test",),
    )


def continuation(**overrides):
    args = dict(
        preset=preset(), profile_prefix="Bound professional profile",
        request_payload={"question": "Original question", "attachment": "Original attachment"},
        fixed_evidence=["INITIAL_QUERY_AND_RESULT_PROOF"],
        read_evidence=["FULL_CURRENT_CARD\nLAST_RESOURCE_PROOF 7.125 kg"],
        prior_evidence=[], exchange=[{"tool": "search_sources", "q": "exact-code"}],
        native_tools=[],
    )
    args.update(overrides)
    return service.govern_model_rag_read_messages(**args)


def messages_body(messages):
    return "\n".join(message["content"] for message in messages)


def test_current_read_and_original_context_survive_prior_evidence_omission():
    current_body = "FULL_CURRENT_CARD\n" + "resource quantity 2.5 kg\n" * 30 + "LAST_RESOURCE_PROOF 7.125 kg"
    messages, packet = continuation(
        read_evidence=[current_body],
        prior_evidence=["OMITTED_PRIOR_BODY " * 4000],
    )
    body = messages_body(messages)
    assert current_body in body, "Current card must arrive byte-for-byte, including its last resource"
    assert "INITIAL_QUERY_AND_RESULT_PROOF" in body
    assert "Original question" in body and "Original attachment" in body
    assert "OMITTED_PRIOR_BODY" not in body
    assert packet.omissions
    for omission in packet.omissions:
        assert omission.cursor in body
        for object_id in omission.object_ids:
            assert object_id in body
    assert "evidence:0" in body


@pytest.mark.parametrize("required", ["fixed_evidence", "read_evidence"])
def test_oversized_required_object_fails_explicitly_without_truncation(required):
    with pytest.raises(ContextRequiredSectionOverflow):
        continuation(**{required: ["WHOLE_OBJECT " * 5000]})


def test_native_schema_has_separate_token_reserve_without_user_text_duplication():
    execution_preset = preset()
    native_tools = [{"type": "function", "function": {
        "name": "search_sources", "description": "NATIVE_SCHEMA_ONLY_PROOF " * 100,
        "parameters": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
    }}]
    plain_messages, plain_packet = continuation(preset=execution_preset)
    messages, packet = continuation(preset=execution_preset, native_tools=native_tools)
    schema_tokens = ContextGovernor(execution_preset).estimate_tokens(
        json.dumps(native_tools, ensure_ascii=False, separators=(",", ":"))
    )
    assert packet.safety_reserve_tokens == plain_packet.safety_reserve_tokens + schema_tokens
    assert packet.input_budget_tokens == plain_packet.input_budget_tokens - schema_tokens
    assert packet.included_tokens <= packet.input_budget_tokens
    assert "NATIVE_SCHEMA_ONLY_PROOF" not in messages_body(messages)
    assert messages == plain_messages
    assert "LAST_RESOURCE_PROOF 7.125 kg" in messages_body(messages)


def test_addressed_read_uses_global_query_identity_after_batch():
    groups, chunks = service.build_model_rag_evidence_groups(
        [("exact-code", [SimpleNamespace(
            content="FULL_CURRENT_CARD\nLAST_RESOURCE_PROOF", doc_name="norm-card",
            score=1.0, meta={"norm_code": "exact-code"},
        )])], max_chars=4000, hits_per_query=6, query_offset=20,
    )
    assert "[Поисковый запрос Q21] exact-code" in groups[0]
    assert "Q21.H1" in groups[0]
    assert "LAST_RESOURCE_PROOF" in groups[0]
    assert chunks[0].meta["model_query_index"] == 21
    assert chunks[0].meta["model_evidence_ref"] == "Q21.H1"


@pytest.mark.parametrize("error", [None, "ContextRequiredSectionOverflow"])
def test_read_receipt_persists_literal_evidence_and_original_as_utf8_json(monkeypatch, tmp_path, error):
    def receipt_path(*parts):
        return tmp_path.joinpath(*parts)

    monkeypatch.setattr(service, "mutable_path", receipt_path)
    full_card = "Полная карточка нормы\n" + "ресурс 3.25 чел.-ч\n" * 80 + "LAST_RESOURCE_RECEIPT_PROOF 7.125 кг"
    trace = {
        "literal_calls": [{"tool": "search_sources", "args": {"q": "ГЭСНм08-02-401-01"}}],
        "payload": {"status": "ok", "result": {"cards": [{"body": full_card}]}},
        "unexecuted": [{"tool": "search_sources", "args": {"q": "ГЭСНм08-02-402-01"}}],
    }
    question = "Исходный вопрос: составь смету без замены выбора модели"
    attachment_context = "Исходное вложение: строка 1 — шкаф управления, 2 шт."
    receipt = service.persist_model_rag_read_receipt(
        trace=trace, question=question, attachment_context=attachment_context,
        session_id="receipt-session", error=error,
    )
    assert receipt["receipt_id"]
    saved_path = Path(receipt["path"])
    assert saved_path.is_relative_to(tmp_path)
    saved_bytes = saved_path.read_bytes()
    assert hashlib.sha256(saved_bytes).hexdigest() == receipt["sha256"]
    saved = json.loads(saved_bytes.decode("utf-8"))
    assert saved["trace"] == trace
    assert saved["question"] == question
    assert saved["attachment_context"] == attachment_context
    assert saved["session_id"] == "receipt-session"
    assert saved["error"] == error
    assert full_card in saved["trace"]["payload"]["result"]["cards"][0]["body"]
    assert "LAST_RESOURCE_RECEIPT_PROOF 7.125 кг" in saved_bytes.decode("utf-8")
