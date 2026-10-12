"""Exercise both production initial-governor calls with whole-wire schema counts."""
import ast
import copy
from pathlib import Path

import pytest

from proxy.services import chat_evidence_application_service as service
from tests.test_model_initial_complete_card_frontier import counter, fixture
from tests.test_model_initial_inventory_exact_fit import _context


def _production_call(route):
    """Keep production keyword expressions instead of reproducing their budget math.

    The enclosing chat handler needs live services. Execute its literal B0/B1
    governor invocation with the same real governor and offline frame fixtures.
    """
    tree = ast.parse(Path(service.__file__).read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == "govern_model_rag_initial_messages"]
    assert len(calls) == 2
    query_name = "model_rag_query_hits" if route == "B0_DIRECT" else "pass_hits"
    matches = [node for node in calls if any(
        keyword.arg == "query_hits" and isinstance(keyword.value, ast.Name)
        and keyword.value.id == query_name for keyword in node.keywords)]
    assert len(matches) == 1
    return compile(ast.Expression(copy.deepcopy(matches[0])), service.__file__, "eval")


async def _invoke_production(route, count):
    hits, old, _groups, _by_ref, _page = fixture()
    context = _context()
    source = ["whole original attachment"]
    _fixed_messages, fixed = service.govern_inference_messages(
        **context, required_evidence=source)
    legacy = service.govern_inference_messages(
        **context, required_evidence=[*source, *old[0]])
    # The source fixture uses a 4500-character initial page. Native growth and
    # all exact-wire limits are still enforced by the real production governor.
    growth = {"reserved_tokens": 5000, "remaining_group_tokens": 2250}
    namespace = {
        "govern_model_rag_initial_messages": service.govern_model_rag_initial_messages,
        "_bound_input_token_counter": lambda _preset, _tools: count,
        "model_rag_group_char_budget": service.model_rag_group_char_budget,
        "_model_only_query_provenance": service._model_only_query_provenance,
        "answer_execution_preset": context["preset"],
        "answer_native_tools": context["native_tools"],
        "sheet_read_tools": context["native_tools"],
        "model_rag_query_hits": hits,
        "pass_hits": hits,
        "model_rag_evidence_groups": old[0],
        "model_evidence_chunks": old[1],
        "omitted_evidence_refs": old[2],
        "page_body_deferred": old[2],
        "fixed_model_rag_evidence": source,
        "pass_evidence": source,
        "native_growth_budget": growth,
        "fixed_packet": fixed,
        "context_chars_limit": 120000,
        "group_max_chars": 4500,
        "retrieval_limits": {"model_evidence_k": 6},
        "initial_answer_context": context,
        "initial_context": context,
        # These B1 identity fields affect neither capacity nor card contents.
        "row_packet_id": lambda *_args, **_kwargs: "source-packet",
        "source_catalog": None,
        "sheet_name": "literal-sheet",
        "packet": [],
        "packet_attempts": {"fixture": 1},
        "fingerprint": "fixture",
        "evidence_query_offset": 0,
        "pass_query_provenance": service._model_only_query_provenance(hits),
        "pass_query_addresses": None,
    }
    result = await eval(_production_call(route), namespace)
    return result, old, fixed, legacy, growth


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_production_full_cards_use_schema_tokens_already_in_bound_wire(route):
    count, calls = counter(full_tokens=22000)
    result, old, fixed, _legacy, growth = await _invoke_production(route, count)
    messages, packet, _groups, chunks, _omitted, trace = result
    assert fixed.provider_payload_tokens > 0
    assert trace["complete_card_fit"]["status"] == "expanded"
    assert packet.included_tokens + growth["reserved_tokens"] > fixed.input_budget_tokens
    assert any(full for _wire, full in calls)
    assert packet.provider_payload_tokens == 0
    assert packet.included_tokens + growth["reserved_tokens"] <= packet.input_budget_tokens
    assert packet.input_budget_tokens == 30000 - 2000 - 1000
    assert packet.generation_reserve_tokens == 2000
    assert packet.safety_reserve_tokens == 1000
    assert service.measured_connection_revision(packet) == "fixture:r8"
    previous = {chunk.meta["model_evidence_ref"]: chunk.content for chunk in old[1]
                if chunk.meta["body_status"] == "full"}
    shown = {chunk.meta["model_evidence_ref"]: chunk for chunk in chunks
             if chunk.meta["body_status"] == "full"}
    assert shown.keys() == previous.keys()
    assert all(chunk.content.startswith(previous[ref]) and chunk.meta["normative_card_complete"]
               for ref, chunk in shown.items())
    assert "whole original attachment" in str(messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_production_schema_recovery_keeps_unavailable_counter_fallback(route):
    async def unsupported(_messages):
        return None

    result, old, fixed, legacy, _growth = await _invoke_production(route, unsupported)
    assert result[:2] == legacy
    assert result[2:5] == old
    assert result[5]["reason"] == "counter_unavailable"
    assert result[1].provider_payload_tokens == fixed.provider_payload_tokens > 0
    assert service.measured_connection_revision(result[1]) == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_production_schema_recovery_cannot_spend_native_read_reserve(route):
    count, _calls = counter(full_tokens=22001)
    result, _old, _fixed, _legacy, growth = await _invoke_production(route, count)
    assert result[5]["complete_card_fit"]["status"] == "unchanged"
    assert result[5]["complete_card_fit"]["reason"] == "native_read_reserve"
    assert not any(chunk.meta["normative_card_complete"] for chunk in result[3])
    assert result[1].included_tokens + growth["reserved_tokens"] <= result[1].input_budget_tokens
