"""Every post-answer proof request is admitted on its actual wire before inference."""
from __future__ import annotations

import json

import pytest

from proxy.services import fgis_price_service
from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests.test_model_rag_sheet_evidence_reads import (
    NORM_CODE, RESOURCE_A, RESOURCE_B, _run_sheet,
)
from tests.test_norm_card_proof_request_930 import SECOND_NORM_ANSWER


WORK_ANSWER = (
    "artifact_kind: lsr\n\n"
    "| source_row | row_role | title | unit | quantity | norm_code | resource_code | evidence_refs |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
    f"| S!R2 | work | Cable A | m | 12 | {NORM_CODE} | — | Q3.H1 |\n"
    f"| S!R3 | work | Cable B | m | 3 | {NORM_CODE} | — | Q3.H1 |"
)


def _group_book(monkeypatch):
    """The external fixture book prices the first exact-card slot as a family."""
    original = fgis_price_service.PriceBook.resource_group

    def resource_group(self, code, **kwargs):
        if code != "fixture-resource-0":
            return original(self, code, **kwargs)
        return {"state": "unresolved_resource_group", "group": code,
                "total": 2, "truncated": False, "members": [
                    {"code": RESOURCE_A, "name": "Cable A", "unit": "m", "price_current_eff": 100},
                    {"code": RESOURCE_B, "name": "Cable B", "unit": "m", "price_current_eff": 200},
                ]}

    monkeypatch.setattr(fgis_price_service.PriceBook, "resource_group", resource_group)


async def _proof_run(tmp_path, monkeypatch, kind, *, suffix="", input_token_limit=100_000):
    is_group = kind == "resource_group"
    if is_group:
        _group_book(monkeypatch)
    answer = (WORK_ANSWER if is_group else SECOND_NORM_ANSWER) + suffix
    run = await _run_sheet(
        tmp_path, monkeypatch, reads=is_group, distinct_norms=not is_group,
        group_char_budget=None if is_group else 7000,
        input_token_limit=input_token_limit,
        final_answer=answer,
        proof_replies=[InferenceResponse(text=answer, tool_calls=(), finish_reason="stop", usage={})],
    )
    return run, answer


def _proof_payloads(frame):
    return [obj["payload"] for section in frame["sections"] for obj in section.get("objects", [])
            if isinstance(obj.get("payload"), dict)
            and "proof_previous_model_answer" in obj["payload"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,purpose", [
    ("norm", "sheet_pass_norm_proof"),
    ("resource_group", "sheet_pass_resource_group_proof"),
])
async def test_proof_actual_request_has_own_governed_budget_and_literal_context(
    tmp_path, monkeypatch, kind, purpose,
):
    run, answer = await _proof_run(tmp_path, monkeypatch, kind)
    trace = run.result["retrieval_trace"]
    actual = trace["actual_model_calls"]["calls"]
    assert [item["purpose"] for item in actual].count(purpose) == 1
    frames = [item for item in trace["context_governor"]["calls"] if item["purpose"] == purpose]
    assert len(frames) == 1, "the proof must be admitted after adding its previous answer and request"
    frame = frames[0]
    # The fixture's ordinary answer policy resolves its configured 5000 to the
    # existing 8192 minimum. Proof admission must preserve that actual policy.
    assert frame["generation_reserve_tokens"] == 8192
    initial_frame = next(item for item in trace["context_governor"]["calls"]
                         if item["purpose"] == "sheet_pass_answer")
    # The bound norm proof can expose a narrower reader schema. Its message
    # allowance changes by that actual wire payload; the full input envelope
    # (messages plus provider tool/choice bytes) must stay exactly the same.
    assert (frame["input_budget_tokens"] + frame.get("native_tools_reserved_tokens", 0)
            == initial_frame["input_budget_tokens"]
            + initial_frame.get("native_tools_reserved_tokens", 0))
    assert frame["included_tokens"] <= frame["input_budget_tokens"]
    proof = _proof_payloads(frame)
    assert len(proof) == 1 and proof[0]["proof_previous_model_answer"] == answer
    request = run.requests[-1]
    assert request.max_output_tokens == 8192
    wire_payloads = []
    for message in request.messages:
        for line in str(message.get("content") or "").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and "proof_previous_model_answer" in item:
                wire_payloads.append(item)
    assert wire_payloads == proof, "the budget receipt must describe the dispatched literal proof"
    phase = request.messages[-1]
    assert phase["role"] == "user"
    assert "read_norm_card" in phase["content"] if kind == "norm" else \
        "fixture-resource-0" in phase["content"]
    if kind == "resource_group":
        assert "fixture-resource-21" in str(request.messages), "proof retains the actually read full card"
    assert not run.responses


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,purpose,initial_calls", [
    ("norm", "sheet_pass_norm_proof", 2),
    ("resource_group", "sheet_pass_resource_group_proof", 4),
])
async def test_proof_overflow_keeps_terminal_rows_and_explicit_technical_warning(
    tmp_path, monkeypatch, kind, purpose, initial_calls,
):
    # The answer is under 8192 conservative tokens, but replaying it beside the
    # existing source and tools exceeds the next input window.
    suffix = "\n\n" + "literal previous-answer context " * 400
    run, answer = await _proof_run(tmp_path, monkeypatch, kind, suffix=suffix,
                                   input_token_limit=24_000)
    trace = run.result["retrieval_trace"]
    assert len(run.requests) == initial_calls, "overflow cannot dispatch a proof inference"
    assert len(run.responses) == 1, "the undispatched proof response remains unused"
    assert trace["context_governor"]["error"]["purpose"] == purpose
    assert trace["context_governor"]["error"]["code"] == "CONTEXT_REQUIRED_SECTION_OVERFLOW"
    failure = trace["proof_context_failure"]
    assert failure["technical_failure"] is True and failure["model_decisions_rewritten"] is False
    assert failure["purpose"] == purpose
    assert "не помещается" in run.result["answer"]
    assert answer.rstrip() in run.result["answer"]
    job = WorkbookResearchJobService().get(trace["workbook_research_job"]["job_id"])
    assert job["status"] == "complete"
    assert job["held_packet"]["proof_context_failure"] == failure
    assert not job["held_packet"].get("model_read_pending")
    assert job["held_packet"]["terminal_model_result_saved"] is True
    assert [(row["source_row"], row["norm_code"], row["quantity"])
            for row in job["accepted_rows"]] == [
        ("S!R2", NORM_CODE if kind == "resource_group" else "ГЭСН99-01-002-01", 12),
        ("S!R3", NORM_CODE if kind == "resource_group" else "ГЭСН99-01-002-01", 3),
    ]
    assert len(run.executions) == 1, "the unchanged previous result can still be packaged"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["norm", "resource_group"])
async def test_ordinary_continue_after_proof_overflow_reuses_terminal_rows_without_zombie_pause(
    tmp_path, monkeypatch, kind,
):
    suffix = "\n\n" + "literal previous-answer context " * 400
    run, _answer = await _proof_run(tmp_path, monkeypatch, kind, suffix=suffix,
                                    input_token_limit=24_000)
    store = WorkbookResearchJobService()
    before = store.get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    rows_before = before["accepted_rows"]
    calls_before = len(run.requests)
    resumed = await run.resume_same_request(
        question="Продолжи это же задание по тому же прикреплённому документу.")
    after = store.get(resumed["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert len(run.requests) == calls_before, "a terminal result must not buy hidden inference"
    assert not (resumed["retrieval_trace"].get("actual_model_calls") or {}).get("calls")
    assert after["accepted_rows"] == rows_before
    assert after["status"] == "complete", "ordinary continue cannot remain in a zero-call proof pause"
    assert after["remaining"] == []
    assert not after["held_packet"].get("model_read_pending")
    assert after["phase"] != "proof_context_capacity"
