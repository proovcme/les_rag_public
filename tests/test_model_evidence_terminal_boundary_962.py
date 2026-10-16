"""A native final is a model result, never another read or a workbook side effect."""
import json
from types import SimpleNamespace

import pytest

from proxy.services.model_evidence_read_service import run_model_evidence_read_turn


def forbidden(*args, **kwargs):
    pytest.fail("A completed native result must not read, package or call the model again")


@pytest.mark.asyncio
@pytest.mark.parametrize("carrier", ["", "provider-native-carrier"])
async def test_native_final_reaches_existing_result_boundary_without_side_effects(carrier):
    literal = '{"artifact_kind":"vor","rows":[{"source_row":"Лист!R2","quantity":0}]}'
    terminal = SimpleNamespace(text=literal, trace={"call_id": "native-final"})
    result = await run_model_evidence_read_turn(
        text=carrier, usage={"completion_tokens": 17, "finish_reason": "tool_calls"},
        extract_terminal=lambda _text: terminal, parse_calls=forbidden, execute=forbidden,
        continue_turn=forbidden, allowed_tools={"read_source"}, max_calls=0,
    )
    assert result.text == literal and result.terminal_result is terminal
    assert result.usage == {"completion_tokens": 17, "finish_reason": "tool_calls"}
    assert result.extra_completion_tokens == 0 and result.stop_reason == ""
    assert result.receipts == result.results == result.native_exchanges == ()


@pytest.mark.asyncio
async def test_plain_text_stays_byte_exact_when_no_native_terminal_is_present():
    text = "Итог\n| work | 0 |\n"
    result = await run_model_evidence_read_turn(
        text=text, usage={}, extract_terminal=lambda _text: None,
        parse_calls=lambda *a, **kw: [], execute=forbidden,
        continue_turn=forbidden, allowed_tools={"read_source"},
    )
    assert result.text == text and result.terminal_result is None


@pytest.mark.asyncio
async def test_read_then_terminal_preserves_read_receipts_and_stops_without_a_second_continuation():
    executed, continued, extracted = [], [], []
    terminal = SimpleNamespace(text='{"artifact_kind":"vor","rows":[]}', trace={"call_id": "final"})
    call = {"tool": "read_source", "args": {"source": "literal"}}

    def extract(text):
        extracted.append(text)
        return terminal if text == "native-final" else None

    def parse(text, **kwargs):
        return [call]

    def execute(value):
        executed.append(value)
        return {"status": "ok"}

    def continuation(*args):
        continued.append(args)
        return "native-final", {"completion_tokens": 11, "finish_reason": "tool_calls"}

    result = await run_model_evidence_read_turn(
        text="read", usage={"completion_tokens": 3}, extract_terminal=extract,
        parse_calls=parse, execute=execute, continue_turn=continuation,
        allowed_tools={"read_source"}, max_calls=1,
    )
    assert executed == [call] and len(continued) == 1 and extracted == ["read", "native-final"]
    assert result.text == terminal.text and result.terminal_result is terminal
    assert len(result.receipts) == 1 and result.extra_completion_tokens == 3


@pytest.mark.asyncio
async def test_ambiguous_terminal_error_propagates_before_any_read_or_execution():
    class AmbiguousTerminal(ValueError):
        pass

    def extract(_text):
        raise AmbiguousTerminal("mixed native final and read")

    with pytest.raises(AmbiguousTerminal, match="mixed native final"):
        await run_model_evidence_read_turn(
            text="native-mixed", usage={}, extract_terminal=extract,
            parse_calls=forbidden, execute=forbidden, continue_turn=forbidden,
            allowed_tools={"read_source"},
        )
