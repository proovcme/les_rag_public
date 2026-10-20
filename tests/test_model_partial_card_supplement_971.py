"""A fitting ordered card supplement cannot be withheld by its larger suffix.

These tests exercise the real initial governor and typed-card renderer. Only
the external whole-wire token counter is replaced with a finite double.
"""
import ast
import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services import model_rag_grouped_evidence_service as grouped
from tests.test_model_initial_complete_card_frontier import fixture
from tests.test_model_initial_inventory_exact_fit import _context
from tests.test_model_initial_schema_reserve_928 import _invoke_production


FIRST = frozenset({"Q1.H1"})
BOTH = frozenset({"Q1.H1", "Q1.H2"})
THREE = frozenset({"Q1.H1", "Q1.H2", "Q1.H3"})


def _case(*, partial_inventory=False, alias=False, distinct_third=False):
    hits, old, _groups, _by_ref, page = fixture(all_inventory=not partial_inventory)
    if alias or distinct_third:
        # A repeated H1 source must travel atomically; the other case supplies
        # a third distinct identity to exercise failure after a valid prefix.
        query, cards = hits[0]
        third = cards[0] if alias else hits[1][1][0]
        hits[0] = query, [cards[0], cards[1], third]
        groups, _hits = service._model_rag_full_groups(hits, hits_per_query=6)
        previews = [grouped.EvidenceGroup(group.header, [
            replace(card, content=card.preview_content, meta=card.preview_meta,
                    preview_content=None, preview_meta=None)
            for card in group.cards]) for group in groups]
        max_chars = grouped._render(
            previews, {card.ref for group in groups for card in group.cards}, 1,
        ).rendered_chars
        old = service.build_model_rag_evidence_groups(
            hits, max_chars=max_chars, hits_per_query=6)
        page = grouped.plan_full_group_page(groups, max_chars)
        assert page.body_refs == ["Q1.H1", "Q1.H2", "Q1.H3"]
        assert page.shared_refs == ({"Q1.H3": "Q1.H1"} if alias else {})
    else:
        assert page.body_refs == ["Q1.H1", "Q1.H2"]
    return hits, old, page


def _wire_complete_refs(messages):
    """Observe delivery facts in the actual wire, not a proposed page helper."""
    refs = set()
    for message in messages:
        for line in str(message.get("content") or "").splitlines():
            if not line.startswith("{"):
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (isinstance(value, dict)
                    and isinstance(value.get("card_delivery_facts"), dict)
                    and value["card_delivery_facts"].get("normative_resources_status") == "complete"):
                refs.add(value["evidence_ref"])
    return frozenset(refs)


def _counter(tokens_by_refs, *, after_first_failure=None):
    calls = []
    first_seen = False

    async def count(messages):
        nonlocal first_seen
        assert len(calls) < 64, "initial supplementation must have a finite probe bound"
        refs = _wire_complete_refs(messages)
        wire = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        calls.append((refs, wire))
        first_seen = first_seen or refs == FIRST
        owner = "fixture:r8"
        model_hash = "a" * 64
        # A fast trial of the full suffix may happen before the first prefix.
        # Its ordinary non-fit must not pre-empt the later valid prefix.
        if after_first_failure and first_seen and "Q1.H2" in refs:
            if after_first_failure == "unavailable":
                return None
            if after_first_failure == "changed_loaded_model":
                model_hash = "b" * 64
            else:
                owner = "fixture:r9"
        return SimpleNamespace(
            tokens=tokens_by_refs.get(refs, 22001), source="fixture-bound-wire",
            model_id="fixture", connection_revision_id=owner,
            model_identity_sha256=model_hash,
            wire_sha256=hashlib.sha256(wire.encode("utf-8")).hexdigest(),
        )

    return count, calls


async def _run(case, count, *, char_limit=120000, reserve=5000, ceiling=27000):
    hits, old, page = case
    before = copy.deepcopy(hits)
    result = await service.govern_model_rag_initial_messages(
        count_messages=count, query_hits=hits,
        evidence_groups=old[0], evidence_chunks=old[1], omitted_refs=old[2],
        max_chars=page.rendered_chars, inventory_chars_limit=char_limit,
        hits_per_query=6, source_context=["whole original attachment"],
        native_read_reserved_tokens=reserve,
        initial_input_budget_tokens=ceiling, **_context(),
    )
    assert hits == before
    return result


def _complete_refs(result):
    return [chunk.meta["model_evidence_ref"] for chunk in result[3]
            if chunk.meta.get("normative_resources_status") == "complete"]


def _assert_original_frontier(result, page):
    chunks = {chunk.meta["model_evidence_ref"]: chunk for chunk in result[3]}
    assert list(chunks) == page.inventory_refs
    assert [ref for ref, chunk in chunks.items() if chunk.meta["body_status"] == "full"] == page.body_refs
    assert result[4] == page.deferred_refs
    for ref, chunk in chunks.items():
        if ref in page.body_refs:
            assert chunk.content.startswith(page.body_by_ref[ref])
        else:
            assert chunk.content == page.pointer_by_ref[ref]
    assert "whole original attachment" in str(result[0])


@pytest.mark.asyncio
async def test_character_cap_admits_first_whole_card_when_combined_supplement_cannot_fit():
    case = _case()
    hits, _old, page = case
    # Both producer bodies alone exceed this cap; a first-card prefix has
    # enough room for the unchanged inventory and previews.
    assert sum(len(hit.content) for hit in hits[0][1]) > 60000
    count, _calls = _counter({frozenset(): 100, FIRST: 10000, BOTH: 11000})

    result = await _run(case, count, char_limit=60000)

    assert _complete_refs(result) == ["Q1.H1"]
    assert len("\n\n".join(result[2])) <= 60000
    assert result[5]["complete_card_fit"]["status"] == "expanded"
    _assert_original_frontier(result, page)


@pytest.mark.asyncio
@pytest.mark.parametrize("ceiling,first_tokens,next_tokens", [
    (27000, 22000, 22001),
    (20000, 15000, 15001),
])
async def test_last_fitting_card_prefix_keeps_native_reserve_and_original_ceiling(
    ceiling, first_tokens, next_tokens,
):
    case = _case()
    count, _calls = _counter({frozenset(): 100, FIRST: first_tokens, BOTH: next_tokens})

    result = await _run(case, count, ceiling=ceiling)

    assert _complete_refs(result) == ["Q1.H1"]
    assert result[1].included_tokens == first_tokens
    assert result[1].included_tokens + 5000 == ceiling
    assert result[1].included_tokens + 5000 <= result[1].input_budget_tokens
    assert service.measured_connection_revision(result[1]) == "fixture:r8"
    _assert_original_frontier(result, case[2])


@pytest.mark.asyncio
async def test_nonfitting_first_card_does_not_select_a_later_fitting_card():
    case = _case()
    count, calls = _counter({
        frozenset(): 100, FIRST: 22001, BOTH: 22001,
        frozenset({"Q1.H2"}): 300,
    })

    result = await _run(case, count)

    assert _complete_refs(result) == []
    assert any(refs == FIRST for refs, _wire in calls), "the first indivisible unit must be checked"
    assert not any(refs == frozenset({"Q1.H2"}) for refs, _wire in calls)
    assert result[2:5] == case[1]
    _assert_original_frontier(result, case[2])


@pytest.mark.asyncio
async def test_interleaved_aliases_of_one_card_are_an_atomic_supplement():
    case = _case(alias=True)
    aliases = frozenset({"Q1.H1", "Q1.H3"})
    count, calls = _counter({frozenset(): 100, aliases: 10000})

    result = await _run(case, count)

    assert _complete_refs(result) == ["Q1.H1", "Q1.H3"]
    assert all(("Q1.H1" in refs) == ("Q1.H3" in refs) for refs, _wire in calls)
    chunks = {chunk.meta["model_evidence_ref"]: chunk for chunk in result[3]}
    assert chunks["Q1.H3"].meta["shared_evidence_ref"] == "Q1.H1"
    assert chunks["Q1.H1"].content == chunks["Q1.H3"].content
    assert len(chunks["Q1.H1"].meta["resources"]) == 20
    _assert_original_frontier(result, case[2])


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unavailable", "changed_owner"])
async def test_unknown_or_changed_counter_after_valid_prefix_preserves_that_wire(failure):
    case = _case(distinct_third=True)
    count, calls = _counter(
        {frozenset(): 100, THREE: 22001, FIRST: 10000, BOTH: 10001},
        after_first_failure=failure,
    )

    result = await _run(case, count, char_limit=0)

    assert _complete_refs(result) == ["Q1.H1"]
    assert result[1].included_tokens == 10000
    assert result[1].token_count_binding["status"] == "counted"
    assert service.measured_connection_revision(result[1]) == "fixture:r8"
    assert result[5]["complete_card_fit"]["stop_reason"] == (
        "counter_unavailable" if failure == "unavailable" else "counter_identity_changed")
    # Optional dialogue can require a second count of the same prefix. Keep
    # those adjacent observations together when checking actual probe order.
    states = []
    for refs, _wire in calls:
        if not states or states[-1] != refs:
            states.append(refs)
    assert states == [THREE, FIRST, BOTH]
    _assert_original_frontier(result, case[2])


@pytest.mark.asyncio
async def test_partial_inventory_supplement_preserves_unshown_refs_and_deferred_order():
    case = _case(partial_inventory=True)
    assert case[2].unshown_refs
    # All-inventory admission fails reserve, but the first retained body's
    # supplement fits. The existing unseen inventory must stay unseen.
    count, _calls = _counter({frozenset(): 22001, FIRST: 10000, BOTH: 22001})

    result = await _run(case, count)

    assert _complete_refs(result) == ["Q1.H1"]
    assert result[5].get("unshown_refs") == case[2].unshown_refs
    assert set(chunk.meta["model_evidence_ref"] for chunk in result[3]).isdisjoint(case[2].unshown_refs)
    _assert_original_frontier(result, case[2])


@pytest.mark.asyncio
async def test_known_loaded_model_change_cannot_dispatch_a_previously_counted_prefix():
    case = _case(distinct_third=True)
    count, calls = _counter(
        {frozenset(): 100, THREE: 22001, FIRST: 10000, BOTH: 10001},
        after_first_failure="changed_loaded_model",
    )
    with pytest.raises(service.ModelTransportError, match="TOKEN_COUNT_MODEL_CHANGED"):
        await _run(case, count, char_limit=0)
    assert any(refs == FIRST for refs, _wire in calls)
    assert any(refs == BOTH for refs, _wire in calls)


def _apply_production_trace_updates(route, result):
    """Execute the actual trace mutations without starting the enclosing app."""
    target = "grouped_trace" if route == "B0_DIRECT" else "page_trace"
    tree = ast.parse(Path(service.__file__).read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "update" and isinstance(node.func.value, ast.Name)
             and node.func.value.id == target]
    assert len(calls) == (1 if route == "B0_DIRECT" else 2)
    trace = {"unshown_refs": ["stale-ref"], "deferred_body_refs": ["stale-ref"],
             "unshown_hit_count": -1}
    namespace = {
        target: trace, "inventory_fit": result[5],
        "model_evidence_chunks": result[3],
        "page_body_deferred": result[4], "omitted_evidence_refs": result[4],
        "model_rag_evidence_groups": result[2], "context": "\n\n".join(result[2]),
    }
    for call in sorted(calls, key=lambda node: node.lineno):
        eval(compile(ast.Expression(copy.deepcopy(call)), service.__file__, "eval"), namespace)
    return trace


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_production_trace_keeps_actual_unshown_and_deferred_refs_after_partial_supplement(route):
    count, _calls = _counter({frozenset(): 22001, FIRST: 10000, BOTH: 22001})
    result, old, _fixed, _legacy, _growth = await _invoke_production(route, count)
    old_shown = {chunk.meta["model_evidence_ref"] for chunk in old[1]}
    # The fixture has 22 literal two-hit queries. These identities were absent
    # from its original inventory, independently of the new trace projection.
    expected_unshown = [f"Q{query}.H{hit}" for query in range(1, 23) for hit in (1, 2)
                        if f"Q{query}.H{hit}" not in old_shown]
    assert expected_unshown and _complete_refs(result) == ["Q1.H1"]
    assert result[5]["status"] == "expanded"

    trace = _apply_production_trace_updates(route, result)

    assert trace["unshown_refs"] == expected_unshown
    assert trace["deferred_body_refs"] == old[2]
    assert trace["inventory_hit_count"] == len(old_shown)
    if route == "B0_DIRECT":
        assert trace["unshown_hit_count"] == len(expected_unshown)
    else:
        assert trace["full_body_hit_count"] == 2
        assert trace["normative_complete_card_count"] == 1
        assert trace["normative_preview_card_count"] == 1
