"""A shared driver preserves model decisions and literal evidence-call identity."""

import json
from types import SimpleNamespace

import pytest

from proxy.services.model_evidence_read_service import run_model_evidence_read_turn


def _calls(*calls):
    return json.dumps({"calls": calls})


def _parse(text, *, allowed_tools, max_calls):
    if not text.startswith("{"):
        return []
    return [call for call in json.loads(text)["calls"] if call["tool"] in allowed_tools][:max_calls]


@pytest.mark.asyncio
async def test_plain_final_is_returned_byte_for_byte_without_reads_or_model_continuation():
    text = "Final rows\n| material | 12 | selected-code |"

    def forbidden(*args):
        pytest.fail("plain final must not trigger another model cycle")

    result = await run_model_evidence_read_turn(text=text, usage={"completion_tokens": 21},
        parse_calls=_parse, execute=forbidden, continue_turn=forbidden, on_read_results=forbidden,
        allowed_tools={"read_norm_card"})
    assert result.text == text and result.usage == {"completion_tokens": 21}
    assert result.extra_completion_tokens == 0 and result.stop_reason == ""
    assert result.receipts == () and result.results == ()


@pytest.mark.asyncio
async def test_norm_and_two_distinct_literal_price_reads_reach_same_model_before_final():
    executed, persisted, continued = [], [], []
    first = {"tool": "read_norm_card", "args": {"norm_key": "shown-immutable"}}
    prices = [{"tool": "read_resource_price", "args": {"code": code, "pricebook": "chosen"}}
              for code in ("resource-A", "resource-B")]

    async def execute(call):
        executed.append(call)
        return SimpleNamespace(payload={"status": "ok", "source_ref": call["args"]}, chunks=(call,))

    async def on_read(receipts, results):
        persisted.append((list(receipts), list(results)))

    async def continuation(receipts, results):
        continued.append((list(receipts), list(results)))
        return (_calls(*prices), {"completion_tokens": 7}) if len(continued) == 1 else ("final", {"completion_tokens": 11})

    result = await run_model_evidence_read_turn(text=_calls(first), usage={"completion_tokens": 3},
        parse_calls=_parse, execute=execute, continue_turn=continuation, on_read_results=on_read,
        allowed_tools={"read_norm_card", "read_resource_price"})
    assert executed == [first, *prices]
    assert [len(batch[0]) for batch in persisted] == [1, 2]
    assert [len(batch[0]) for batch in continued] == [1, 3]
    assert result.text == "final" and result.usage["completion_tokens"] == 11
    assert result.extra_completion_tokens == 10
    assert len(result.seen_calls) == 3 and len(result.receipts) == 3


@pytest.mark.asyncio
async def test_every_scope_argument_is_part_of_identity_but_argument_order_is_not():
    calls = [
        {"tool": "search_sources", "args": {"q": "same", "target": "norms"}},
        {"tool": "search_sources", "args": {"q": "same", "target": "documents", "dataset_ids": ["a"]}},
        {"tool": "search_sources", "args": {"q": "same", "target": "documents", "dataset_ids": ["b"]}},
        {"tool": "read_source", "args": {"doc_id": "shown", "offset": 0, "limit": 2}},
        {"tool": "read_source", "args": {"doc_id": "shown", "offset": 2, "limit": 2}},
        {"tool": "read_source", "args": {"limit": 2, "offset": 2, "doc_id": "shown"}},
    ]
    executed = []

    async def execute(call):
        executed.append(call)
        return {"status": "ok"}

    result = await run_model_evidence_read_turn(text=_calls(*calls), usage={}, parse_calls=_parse,
        execute=execute, continue_turn=lambda *a: ("final", {}), allowed_tools={"search_sources", "read_source"})
    assert executed == calls[:5]
    assert len(result.receipts) == 5 and result.stop_reason == ""


@pytest.mark.asyncio
async def test_repeated_exact_read_stops_without_executing_or_continuing_again():
    call = {"tool": "read_norm_card", "args": {"norm_key": "shown"}}
    counts = {"execute": 0, "continue": 0}

    def execute(_call):
        counts["execute"] += 1
        return {"status": "missing"}

    def continuation(*args):
        counts["continue"] += 1
        return _calls(call), {"completion_tokens": 5}

    result = await run_model_evidence_read_turn(text=_calls(call), usage={"completion_tokens": 2},
        parse_calls=_parse, execute=execute, continue_turn=continuation, allowed_tools={"read_norm_card"})
    assert counts == {"execute": 1, "continue": 1}
    assert result.stop_reason == "evidence_read_repeat" and result.extra_completion_tokens == 7
    assert result.receipts[0]["status"] == "missing"


@pytest.mark.asyncio
async def test_durable_seen_identity_is_not_reexecuted_after_resume():
    from proxy.services.model_evidence_read_service import evidence_read_call_identity
    call = {"tool": "read_resource_price", "args": {"code": "selected", "pricebook": "chosen"}}
    identity = evidence_read_call_identity(call)
    previous = {"call": call, "payload": {"status": "ok"}}
    result = await run_model_evidence_read_turn(text=_calls(call), usage={}, parse_calls=_parse,
        execute=lambda *a: pytest.fail("persisted read must not replay"),
        continue_turn=lambda *a: pytest.fail("repeat must pause"), allowed_tools={"read_resource_price"},
        initial_receipts=[previous], seen_calls=[identity])
    assert result.stop_reason == "evidence_read_repeat"
    assert result.receipts == (previous,) and result.seen_calls == (identity,)


@pytest.mark.asyncio
async def test_read_capacity_pause_persists_receipt_without_forcing_another_model_call():
    call = {"tool": "read_norm_card", "args": {"norm_key": "shown"}}
    result = await run_model_evidence_read_turn(text=_calls(call), usage={}, parse_calls=_parse,
        execute=lambda call: {"status": "ok", "resources_complete": True},
        on_read_results=lambda receipts, results: "evidence_read_capacity",
        continue_turn=lambda *a: pytest.fail("capacity cannot start a model call"),
        allowed_tools={"read_norm_card"})
    assert result.stop_reason == "evidence_read_capacity" and len(result.receipts) == 1


@pytest.mark.asyncio
async def test_budget_pause_executes_no_call_after_bound_and_preserves_final_when_available():
    call = {"tool": "read_resource_price", "args": {"code": "one"}}
    next_call = {"tool": "read_resource_price", "args": {"code": "two"}}
    executed = []
    result = await run_model_evidence_read_turn(text=_calls(call), usage={}, parse_calls=_parse,
        execute=lambda call: executed.append(call) or {"status": "ok"},
        continue_turn=lambda *a: (_calls(next_call), {"completion_tokens": 1}),
        allowed_tools={"read_resource_price"}, max_calls=1)
    assert executed == [call] and result.stop_reason == "evidence_read_budget"
    assert result.text == _calls(next_call)


@pytest.mark.asyncio
async def test_execution_failure_propagates_without_false_success_or_continuation():
    call = {"tool": "read_norm_card", "args": {"norm_key": "shown"}}

    def failed(_call):
        raise RuntimeError("offline failure")

    with pytest.raises(RuntimeError, match="offline failure"):
        await run_model_evidence_read_turn(text=_calls(call), usage={}, parse_calls=_parse,
            execute=failed, continue_turn=lambda *a: pytest.fail("failed read cannot continue"),
            allowed_tools={"read_norm_card"})
