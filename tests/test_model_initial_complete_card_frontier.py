"""One exact full-card supplement preserves the already admitted frontier."""
import copy
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services import model_rag_grouped_evidence_service as grouped
from proxy.services.model_research_tool_service import _norm_search_chunk
from tests.test_model_initial_inventory_exact_fit import _context


def fixture(*, all_inventory=False):
    hits = []
    for q in range(1, 23):
        cards = []
        for h in range(1, 3):
            card = dict(norm_key=f"key-{q}-{h}", norm_code=f"code-{q}-{h}",
                title=f"literal title {q}/{h}", measure_unit="m", source_ref=f"source-{q}-{h}",
                source_sha256="d" * 64, edition="literal edition", work_steps=["literal step"],
                resource_preview=[dict(kind="material", code="r0", name="literal preview", unit="m")],
                resources=[dict(kind="material", code=f"r{n}", name="complete resource " * 90,
                                unit="m", per_unit=0 if n == 0 else 1.5) for n in range(20)],
                resource_count=20, resources_returned=20, resources_complete=True,
                hydration_status="ok")
            cards.append(_norm_search_chunk(card, score=7-h, matched_before_cap=2))
        hits.append((f"literal query {q}", cards))
    groups, by_ref = service._model_rag_full_groups(hits, hits_per_query=6)
    max_chars = 4500
    if all_inventory:
        previews = [grouped.EvidenceGroup(g.header, [replace(c, content=c.preview_content,
                    meta=c.preview_meta, preview_content=None, preview_meta=None) for c in g.cards]) for g in groups]
        max_chars = grouped._render(previews, {c.ref for g in groups for c in g.cards}, 1).rendered_chars
    old = service.build_model_rag_evidence_groups(hits, max_chars=max_chars, hits_per_query=6)
    page = grouped.plan_full_group_page(groups, max_chars)
    assert page.body_refs and page.complete_card_deferred_refs
    assert bool(page.unshown_refs) is not all_inventory
    return hits, old, groups, by_ref, page


def counter(*, full_tokens=300, owner_change=False, unsupported_full=False):
    calls = []
    async def count(messages):
        wire = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        full = "resources_complete=True" in wire
        calls.append((wire, full))
        return None if full and unsupported_full else SimpleNamespace(
            tokens=full_tokens if full else 100, source="fixture-wire", model_id="fixture",
            connection_revision_id="fixture:r9" if full and owner_change else "fixture:r8",
            model_identity_sha256="a"*64, wire_sha256=hashlib.sha256(wire.encode()).hexdigest())
    return count, calls


async def run(count, *, reserve=5000, ceiling=27000, all_inventory=False):
    hits, old, groups, by_ref, page = fixture(all_inventory=all_inventory)
    before = copy.deepcopy(hits)
    result = await service.govern_model_rag_initial_messages(count_messages=count,
        query_hits=hits, evidence_groups=old[0], evidence_chunks=old[1], omitted_refs=old[2],
        max_chars=page.rendered_chars, inventory_chars_limit=120000, hits_per_query=6,
        source_context=["whole original attachment"], native_read_reserved_tokens=reserve,
        initial_input_budget_tokens=ceiling, **_context())
    assert hits == before
    return result, page


def test_complete_candidate_keeps_all_aliases_and_literal_old_body_prefix():
    _, _, groups, _, page = fixture()
    inventory = grouped.inventory_expansion_page(groups, page)
    before = copy.deepcopy(groups)
    full = grouped.complete_card_frontier_page(groups, inventory)
    assert full is not None and groups == before
    assert full.inventory_refs == inventory.inventory_refs and full.body_refs == inventory.body_refs
    assert full.pointer_by_ref == inventory.pointer_by_ref and full.shared_refs == inventory.shared_refs
    for ref in inventory.body_refs:
        assert full.body_by_ref[ref].startswith(inventory.body_by_ref[ref])
        assert "resources_complete=True" in full.body_by_ref[ref]
        assert grouped.normative_card_identity(full.meta_by_ref[ref]) == grouped.normative_card_identity(inventory.meta_by_ref[ref])
        assert grouped.card_delivery_facts(full.meta_by_ref[ref], raw_body_shown=True,
                                           displayed_body=full.body_by_ref[ref])["normative_card_complete"]
    for ref in set(inventory.inventory_refs) - set(inventory.body_refs):
        assert full.meta_by_ref[ref] == inventory.meta_by_ref[ref]


@pytest.mark.asyncio
async def test_whole_wire_full_candidate_fits_without_changing_frontier_or_queries():
    count, calls = counter()
    result, page = await run(count)
    assert any(full for _, full in calls)
    assert result[5]["complete_card_fit"]["status"] == "expanded"
    shown = {c.meta["model_evidence_ref"]: c for c in result[3] if c.meta["body_status"] == "full"}
    assert list(shown) == page.body_refs
    for ref, chunk in shown.items():
        assert chunk.content.startswith(page.body_by_ref[ref]) and chunk.meta["normative_card_complete"]
        from proxy.services.model_resource_reference_service import shown_resource_record
        assert len(chunk.meta["resources"]) == 20
        assert shown_resource_record(chunk.meta, chunk.content, 1)["per_unit"] == 0
    assert result[1].included_tokens + 5000 <= 27000
    assert service.measured_connection_revision(result[1]) == "fixture:r8"
    assert "whole original attachment" in str(result[0])


@pytest.mark.asyncio
async def test_already_shown_inventory_still_tries_one_complete_frontier_wire():
    count, calls = counter()
    result, page = await run(count, all_inventory=True)
    assert calls and all(full for _, full in calls)
    assert result[5]["complete_card_fit"]["status"] == "expanded"
    assert [c.meta["model_evidence_ref"] for c in result[3]] == page.inventory_refs
    assert [c.meta["model_evidence_ref"] for c in result[3] if c.meta["body_status"] == "full"] == page.body_refs


@pytest.mark.asyncio
async def test_already_shown_inventory_unknown_counter_keeps_legacy_wire():
    count, _ = counter(unsupported_full=True)
    result, page = await run(count, all_inventory=True)
    hits, old, _, _, _ = fixture(all_inventory=True)
    legacy = service.govern_inference_messages(**_context(), required_evidence=["whole original attachment", *old[0]])
    assert result[:2] == legacy and result[2:5] == old
    assert result[5]["reason"] == "inventory_already_shown"
    assert result[5]["complete_card_fit"]["status"] == "unchanged"
    assert result[5]["complete_card_fit"]["reason"] == "counter_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [dict(full_tokens=22001), dict(full_tokens=27001),
    dict(owner_change=True), dict(unsupported_full=True)])
async def test_nonfit_unknown_or_changed_owner_returns_existing_inventory_wire(options):
    count, _ = counter(**options)
    result, _ = await run(count)
    baseline_count, _ = counter(unsupported_full=True)
    baseline, _ = await run(baseline_count)
    assert result[:5] == baseline[:5]
    assert result[5]["complete_card_fit"]["status"] == "unchanged"


@pytest.mark.asyncio
async def test_full_candidate_keeps_pinned_original_ceiling():
    count, _ = counter(full_tokens=15001)
    result, _ = await run(count, ceiling=20000)
    assert result[5]["complete_card_fit"]["reason"] == "initial_compatibility_headroom"
    assert not any(c.meta["normative_card_complete"] for c in result[3])


@pytest.mark.parametrize("fault", ["prefix", "identity", "aliases", "incomplete", "immutable", "body"])
def test_unsafe_full_candidate_has_no_transport_projection(fault):
    _, _, groups, _, page = fixture()
    inventory = grouped.inventory_expansion_page(groups, page)
    card = groups[0].cards[0]
    meta = dict(card.meta)
    if fault == "prefix":
        card = replace(card, preview_content="different literal preview")
    elif fault == "identity":
        meta["source_sha256"] = "e"*64
    elif fault == "aliases":
        groups = [*groups, groups[0]]
    elif fault == "incomplete":
        meta["resources_complete"] = False
    elif fault == "body":
        card = replace(card, content=card.preview_content)
    else:
        meta["work_steps"] = ["changed literal step"]
    if fault != "aliases":
        card = replace(card, meta=meta)
        groups[0] = grouped.EvidenceGroup(groups[0].header, [card, *groups[0].cards[1:]])
    assert grouped.complete_card_frontier_page(groups, inventory) is None
