"""Provider counters and canonical request hashes are content-free call receipts."""

from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as service
from tests.test_model_rag_sheet_evidence_reads import _run_sheet


USAGE_KEYS = ("prompt_tokens", "input_tokens", "completion_tokens", "total_tokens")
UNKNOWN_USAGE = dict.fromkeys(USAGE_KEYS)


def test_actual_call_preserves_only_numeric_provider_usage_and_owned_hash():
    trace = {"last_model_call_execution": {
        "provider_usage": {"prompt_tokens": 101, "input_tokens": None,
                           "completion_tokens": 19, "total_tokens": 120,
                           "messages": "PRIVATE_MESSAGE", "reasoning": "PRIVATE_REASONING"},
        "canonical_request_sha256": "a" * 64,
        "canonical_request_source": "canonical_inference_request",
        "messages": "PRIVATE_MESSAGE", "response": "PRIVATE_RESPONSE",
    }}
    service.append_actual_model_call(trace, purpose="answer", completion_tokens=19)
    call = trace["actual_model_calls"]["calls"][0]
    assert call["provider_usage"] == {
        "prompt_tokens": 101, "input_tokens": None, "completion_tokens": 19, "total_tokens": 120}
    assert call["canonical_request_sha256"] == "a" * 64
    assert call["canonical_request_source"] == "canonical_inference_request"
    assert call["completion_tokens"] == 19  # Existing compatibility field.
    assert "PRIVATE" not in json.dumps(call)


def test_unknown_provider_counters_remain_null_without_changing_legacy_completion_field():
    trace = {}
    service.append_actual_model_call(trace, purpose="legacy")
    call = trace["actual_model_calls"]["calls"][0]
    assert call["provider_usage"] == UNKNOWN_USAGE
    assert call["canonical_request_sha256"] is None
    assert call["canonical_request_source"] is None
    assert call["completion_tokens"] == 0


@pytest.mark.parametrize("invalid", [True, False, -1, "123", 1.5, float("nan"), float("inf"), {}, []])
def test_invalid_provider_counters_cannot_become_numbers_or_content(invalid):
    trace = {"last_model_call_execution": {"provider_usage": dict.fromkeys(USAGE_KEYS, invalid)}}
    service.append_actual_model_call(trace, purpose="answer")
    assert trace["actual_model_calls"]["calls"][0]["provider_usage"] == UNKNOWN_USAGE


def test_provider_reported_zero_is_distinct_from_unknown():
    trace = {"last_model_call_execution": {"provider_usage": dict.fromkeys(USAGE_KEYS, 0)}}
    service.append_actual_model_call(trace, purpose="answer")
    assert trace["actual_model_calls"]["calls"][0]["provider_usage"] == dict.fromkeys(USAGE_KEYS, 0)


@pytest.mark.parametrize("sha,source", [("not-a-hash", "canonical_inference_request"),
                                        ("g" * 64, "canonical_inference_request"),
                                        ({"messages": "PRIVATE"}, "canonical_inference_request"),
                                        ("a" * 64, "PRIVATE_SOURCE")])
def test_unowned_or_invalid_hash_does_not_reach_the_receipt(sha, source):
    trace = {"last_model_call_execution": {
        "canonical_request_sha256": sha, "canonical_request_source": source}}
    service.append_actual_model_call(trace, purpose="answer")
    call = trace["actual_model_calls"]["calls"][0]
    assert call["canonical_request_sha256"] is None
    assert call["canonical_request_source"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_actual_bound_runner_response_keeps_usage_and_hash_of_each_canonical_request(
    tmp_path, monkeypatch, variant,
):
    original_complete = service.BoundModelChatRunner.complete
    observed = []

    async def complete(runner, **kwargs):
        result = await original_complete(runner, **kwargs)
        number = len(observed) + 1
        usage = {"prompt_tokens": 1000 + number, "completion_tokens": number,
                 "total_tokens": 1000 + 2 * number, "messages": "PRIVATE_USAGE_CONTENT"}
        actual_model = "actual-selected-model"
        connection = SimpleNamespace(**{**vars(result.connection), "model_id": actual_model})
        response = replace(result.response, usage=usage, reasoning_content="PRIVATE_PROVIDER_REASONING")
        observed.append((kwargs["request"], usage, actual_model))
        return replace(result, response=response, connection=connection)

    monkeypatch.setattr(service.BoundModelChatRunner, "complete", complete)
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant)
    calls = run.result["retrieval_trace"]["actual_model_calls"]["calls"]
    assert len(calls) == len(observed) == 4
    hashes = []
    for call, (request, usage, actual_model) in zip(calls, observed):
        assert call["provider_usage"] == {key: usage.get(key) for key in USAGE_KEYS}
        frame = {"schema": "canonical_inference_request.v1", "model_id": actual_model,
                 "messages": list(request.messages), "max_output_tokens": request.max_output_tokens,
                 "temperature": request.temperature, "tools": list(request.tools),
                 "response_format": request.response_format, "reasoning_enabled": request.reasoning_enabled}
        expected = hashlib.sha256(json.dumps(frame, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        assert call["canonical_request_sha256"] == expected
        assert call["canonical_request_source"] == "canonical_inference_request"
        hashes.append(expected)
    assert len(set(hashes)) == 4
    assert "PRIVATE" not in json.dumps(calls)
    assert "PRIVATE" not in json.dumps(run.result["retrieval_trace"]["last_model_call_execution"])
