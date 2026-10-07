"""Full bodies on a retained partial frontier do not require all pointer identities."""
import copy
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services import model_rag_grouped_evidence_service as grouped
from tests.test_model_initial_complete_card_frontier import fixture
from tests.test_model_initial_inventory_exact_fit import _context


def test_partial_frontier_keeps_unseen_and_deferred_aliases_in_original_order():
    _, _, groups, _, page = fixture()
    before = copy.deepcopy(groups)
    full = grouped.complete_card_frontier_page(groups, page)
    assert full is not None and groups == before
    assert full.inventory_refs == page.inventory_refs
    assert full.body_refs == page.body_refs
    assert full.unshown_refs == page.unshown_refs
    assert full.deferred_refs == page.deferred_refs
    assert full.pointer_by_ref == page.pointer_by_ref
    assert full.shared_refs == page.shared_refs
    for ref in page.body_refs:
        assert full.body_by_ref[ref].startswith(page.body_by_ref[ref])
        assert full.meta_by_ref[ref]["resources_complete"] is True
    for ref in set(page.inventory_refs) - set(page.body_refs):
        assert full.meta_by_ref[ref] == page.meta_by_ref[ref]
    assert set(full.meta_by_ref).isdisjoint(page.unshown_refs)


def test_partial_frontier_does_not_expose_previously_unshown_empty_query():
    _, _, groups, _, page = fixture()
    empty = "literal zero-hit query outside the old frontier"
    groups.append(grouped.EvidenceGroup(empty, []))
    page = grouped.plan_full_group_page(groups, page.rendered_chars)
    assert empty not in "\n\n".join(page.groups)
    full = grouped.complete_card_frontier_page(groups, page)
    assert full is not None
    assert empty not in "\n\n".join(full.groups)


def test_empty_query_marker_inside_literal_work_step_cannot_expose_hidden_query():
    from proxy.services.model_research_tool_service import _norm_search_chunk
    hits, _, _, _, _ = fixture()
    empty = "literal zero-hit query outside the old frontier"
    first = hits[0][1][0]
    meta = dict(first.meta, work_steps=[*first.meta["work_steps"], empty + "\n\nhits=0"])
    hits[0][1][0] = _norm_search_chunk(meta, score=first.score, matched_before_cap=2)
    groups, _ = service._model_rag_full_groups(hits, hits_per_query=6)
    groups.append(grouped.EvidenceGroup(empty, []))
    page = grouped.plan_full_group_page(groups, 4500)
    marker = empty + "\n\nhits=0"
    assert marker not in page.groups and any(marker in text for text in page.groups)
    full = grouped.complete_card_frontier_page(groups, page)
    assert full is not None and marker not in full.groups


@pytest.mark.parametrize("field", ["inventory_refs", "unshown_refs", "deferred_refs"])
def test_partial_projection_rejects_changed_alias_order_or_complement(field):
    _, _, groups, _, page = fixture()
    refs = list(getattr(page, field))
    assert len(refs) > 1
    assert grouped.complete_card_frontier_page(groups, replace(page, **{field: refs[::-1]})) is None


async def run_partial(*, inventory_tokens=22001, full_tokens=300, owner_change=False,
                      unsupported=False, ceiling=27000, char_limit=120000):
    hits, old, _, _, page = fixture()
    calls = []
    async def count(messages):
        wire = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        full = "resources_complete=True" in wire
        calls.append((wire, full))
        if unsupported:
            return None
        return SimpleNamespace(tokens=full_tokens if full else inventory_tokens,
            source="fixture-bound-wire", model_id="fixture",
            connection_revision_id="fixture:r9" if full and owner_change else "fixture:r8",
            model_identity_sha256="a" * 64,
            wire_sha256=hashlib.sha256(wire.encode()).hexdigest())
    result = await service.govern_model_rag_initial_messages(count_messages=count,
        query_hits=hits, evidence_groups=old[0], evidence_chunks=old[1], omitted_refs=old[2],
        max_chars=page.rendered_chars, inventory_chars_limit=char_limit, hits_per_query=6,
        source_context=["whole original attachment"], native_read_reserved_tokens=5000,
        initial_input_budget_tokens=ceiling, **_context())
    legacy = service.govern_inference_messages(**_context(), required_evidence=["whole original attachment", *old[0]])
    return result, page, calls, old, legacy


@pytest.mark.asyncio
@pytest.mark.parametrize("inventory_tokens", [22001, 27001])
async def test_complete_old_frontier_is_tried_after_all_inventory_fails_capacity(inventory_tokens):
    result, page, calls, _, _ = await run_partial(inventory_tokens=inventory_tokens)
    assert any(full for _, full in calls), "full-card trial must not depend on all identities fitting"
    assert result[5]["complete_card_fit"]["status"] == "expanded"
    assert [c.meta["model_evidence_ref"] for c in result[3]] == page.inventory_refs
    assert [c.meta["model_evidence_ref"] for c in result[3] if c.meta["body_status"] == "full"] == page.body_refs
    assert result[4] == page.deferred_refs
    assert result[1].included_tokens + 5000 <= 27000
    assert "whole original attachment" in str(result[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("options, reason", [
    ({"full_tokens": 22001}, "native_read_reserve"),
    ({"full_tokens": 27001}, "input_capacity"),
    ({"full_tokens": 15001, "ceiling": 20000}, "initial_compatibility_headroom"),
    ({"owner_change": True}, "counter_identity_changed"),
])
async def test_partial_trial_nonfit_or_different_owner_keeps_original_wire(options, reason):
    result, _, calls, old, legacy = await run_partial(**options)
    assert any(full for _, full in calls)
    assert result[:2] == legacy and result[2:5] == old
    assert result[5]["complete_card_fit"]["reason"] == reason


@pytest.mark.asyncio
async def test_unknown_inventory_counter_does_not_start_a_second_owner_probe():
    result, _, calls, old, legacy = await run_partial(unsupported=True)
    assert calls and not any(full for _, full in calls)
    assert result[:2] == legacy and result[2:5] == old
