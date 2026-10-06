"""Report offered canonical tools and decoded call identity without exposing bodies."""
import hashlib
import json

import pytest

from proxy.services import chat_evidence_application_service as service


def test_legacy_model_call_receipt_does_not_invent_native_tool_evidence():
    trace = {"last_model_call_execution": {"provider_usage": {"completion_tokens": 7}}}
    service.append_actual_model_call(trace, purpose="answer", completion_tokens=7)
    row = trace["actual_model_calls"]["calls"][0]
    assert "canonical_native_tools" not in row
    assert "native_tool_call_identities" not in row
    assert row["canonical_request_sha256"] is None


@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.asyncio
async def test_actual_call_receipts_keep_offered_tools_and_local_id_origin(tmp_path, monkeypatch, variant):
    from tests import test_model_rag_sheet_evidence_reads as fixture

    original = fixture._native

    def native(tool, **arguments):
        raw = original(tool, **arguments)
        return {**raw, "id": "les-native-fixture-" + raw["id"],
                "call_id_origin": "application/native_protocol_without_ids"}

    monkeypatch.setattr(fixture, "_native", native)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=True, variant=variant)
    calls = run.result["retrieval_trace"]["actual_model_calls"]["calls"]
    assert len(calls) == len(run.requests)
    identities = []
    for receipt, request in zip(calls, run.requests, strict=True):
        schemas = list(request.tools)
        tools = receipt["canonical_native_tools"]
        assert tools["source"] == "canonical_inference_request"
        assert tools["provider_http_capture"] is False
        assert tools["count"] == len(schemas)
        assert tools["names"] == [item["function"]["name"] for item in schemas]
        assert tools["schema_sha256"] == hashlib.sha256(json.dumps(
            schemas, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")).hexdigest()
        identities.extend(receipt["native_tool_call_identities"])
    assert calls[0]["canonical_native_tools"]["count"] == 0
    assert any("read_norm_card" in row["canonical_native_tools"]["names"] for row in calls)
    assert {row["tool"] for row in identities} == {"read_norm_card", "read_resource_price"}
    assert all(row["call_id_origin"] == "application/native_protocol_without_ids" for row in identities)
    assert all(row["call_id"].startswith("les-native-fixture-") for row in identities)
    assert all(set(row) == {"call_id", "tool", "call_id_origin"} for row in identities)
    assert "immutable-norm" not in json.dumps(identities)
    assert "arguments" not in json.dumps(identities)
