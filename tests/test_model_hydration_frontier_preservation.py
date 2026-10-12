"""Whole-card hydration must preserve the preview page's native-read frontier."""
import copy
from dataclasses import replace

import pytest

from proxy.services import model_rag_grouped_evidence_service as grouped
from proxy.services.chat_evidence_application_service import _model_rag_full_groups
from proxy.services.model_research_tool_service import (
    ModelResearchToolService, _norm_search_chunk,
)


def _card(ref, *, full_padding=4200, preview_padding=1200, generation="a" * 64):
    preview = f"Шифр: fixture-{ref}\nНаименование: Literal title {ref}\n" + "обзор " * preview_padding
    full = f"Шифр: fixture-{ref}\nНаименование: Literal title {ref}\n" + "ресурс " * full_padding
    meta = {
        "norm_key": f"key-{ref}", "norm_code": f"fixture-{ref}",
        "title": "Дословное имя " + ref + " source-name " * 5,
        "measure_unit": "100 м²", "source_ref": f"immutable-base#exact-guid={ref}",
        "edition": "fixture-edition", "normative_base_sha256": generation,
        "resource_count": 1, "resources_returned": 1, "resources_complete": True,
        "resources": [{"code": f"r-{ref}", "unit": "м²", "per_unit": 0}],
    }
    preview_meta = {key: value for key, value in meta.items()
                    if key not in {"resources", "resources_complete", "resources_returned"}}
    preview_meta.update(resource_preview=[{"code": f"r-{ref}", "unit": "м²"}], exact_card_read=False)
    return grouped.EvidenceCard(ref, f"[{ref} | fixture | score=1]", f"identity-{ref}",
                                full, meta, preview, preview_meta)


def _preview_groups(groups):
    return [grouped.EvidenceGroup(group.header, [
        grouped.EvidenceCard(card.ref, card.header, card.identity,
                             card.preview_content if card.preview_content is not None else card.content,
                             card.preview_meta if card.preview_meta is not None else card.meta)
        for card in group.cards]) for group in groups]


def _groups(count=12, hits=6):
    return [grouped.EvidenceGroup(f"Q{query}: original literal query {query}", [
        _card(f"Q{query}.H{hit}", full_padding=700, preview_padding=230)
        for hit in range(1, hits + 1)]) for query in range(1, count + 1)]


def _native_refs(page):
    reader = ModelResearchToolService(retrieve=lambda **_kw: pytest.fail("no retrieval"),
        frozen_dataset_ids=(), retrieval_kwargs={}, fallback=lambda *_args: pytest.fail("no fallback"))
    chunks = []
    for ref in page.inventory_refs:
        full = ref in page.body_refs
        meta = dict(page.meta_by_ref[ref])
        meta.update(model_evidence_ref=ref, model_inventory_delivery_status="delivered",
                    model_delivery_status="delivered" if full else "deferred",
                    body_status="full" if full else "deferred_capacity",
                    model_inventory_view=page.pointer_by_ref[ref])
        chunks.append({"content": page.body_by_ref[ref] if full else page.pointer_by_ref[ref], "meta": meta})
    reader.register_shown_norm_cards(chunks)
    return [row["evidence_ref"] for row in reader._shown_norm_refs]


def test_first_full_group_fit_cannot_hide_existing_preview_native_read_frontier():
    # Same actual-909 counterfactual shape: twelve literal queries, six retained
    # ranked cards per query. A first full group fits but crowds out later refs.
    groups = _groups()
    before = copy.deepcopy(groups)
    first_refs = {card.ref for card in groups[0].cards}
    first_plus_one = first_refs | {groups[1].cards[0].ref}
    budget = grouped._render(groups, first_plus_one, 1).rendered_chars
    hydrated = grouped._plan_single_body_page(groups, budget)
    legacy = grouped._plan_single_body_page(_preview_groups(groups), budget)
    assert hydrated.included_count == 1
    assert len(hydrated.inventory_refs) < len(legacy.inventory_refs)
    assert len(legacy.inventory_refs) > 40

    delivered = grouped.plan_full_group_page(groups, budget)

    assert delivered.groups == legacy.groups
    assert delivered.inventory_refs == legacy.inventory_refs
    assert delivered.body_refs == legacy.body_refs
    assert delivered.rendered_chars <= budget
    assert _native_refs(delivered) == _native_refs(legacy)
    assert delivered.complete_card_deferred_refs == [card.ref for group in groups for card in group.cards]
    assert groups == before
    for ref in delivered.body_refs:
        assert delivered.body_by_ref[ref] == legacy.body_by_ref[ref]
        assert grouped.card_delivery_facts(delivered.meta_by_ref[ref], raw_body_shown=True,
                                           displayed_body=delivered.body_by_ref[ref])["normative_card_complete"] is False


def test_full_resources_remain_when_both_original_frontiers_fit():
    groups = _groups(count=2, hits=2)
    full = grouped._plan_single_body_page(groups, 1_000_000)
    page = grouped.plan_full_group_page(groups, full.rendered_chars)
    assert page == full
    assert page.inventory_refs == page.body_refs == [card.ref for group in groups for card in group.cards]
    assert page.complete_card_deferred_refs == []
    for ref in page.body_refs:
        facts = grouped.card_delivery_facts(page.meta_by_ref[ref], raw_body_shown=True,
                                            displayed_body=page.body_by_ref[ref])
        assert facts["normative_resources_status"] == "complete"
        assert facts["normative_card_complete"] is False
        assert facts["normative_work_steps_status"] == "unknown"
        assert page.meta_by_ref[ref]["resources"][0]["per_unit"] == 0


def test_full_resources_cannot_displace_whole_preview_bodies_with_all_ids_still_shown():
    groups = _groups(count=3, hits=2)
    all_refs = {card.ref for group in groups for card in group.cards}
    budget = grouped._render(groups, all_refs, 1).rendered_chars
    hydrated = grouped._plan_single_body_page(groups, budget)
    legacy = grouped._plan_single_body_page(_preview_groups(groups), budget)
    assert hydrated.inventory_refs == legacy.inventory_refs
    assert set(hydrated.body_refs) < set(legacy.body_refs)

    delivered = grouped.plan_full_group_page(groups, budget)

    assert delivered.groups == legacy.groups
    assert delivered.inventory_refs == legacy.inventory_refs
    assert delivered.body_refs == legacy.body_refs
    assert delivered.rendered_chars <= budget


@pytest.mark.parametrize("lost", ["inventory_alias", "body_alias"])
def test_guard_compares_exact_refs_even_when_summary_counts_are_equal(monkeypatch, lost):
    groups = _groups(count=2, hits=1)
    preview = grouped._render(_preview_groups(groups), {"Q1.H1", "Q2.H1"}, 2)
    hydrated = grouped._render(groups, {"Q1.H1", "Q2.H1"}, 2)
    if lost == "inventory_alias":
        hydrated = replace(hydrated, inventory_refs=["Q1.H1", "another-exact-ref"])
    else:
        hydrated = replace(hydrated, body_refs=["Q1.H1", "another-exact-ref"])
    assert len(hydrated.inventory_refs) == len(preview.inventory_refs)
    assert len(hydrated.body_refs) == len(preview.body_refs)
    calls = []
    def plan(supplied, budget):
        calls.append((supplied, budget))
        return hydrated if len(calls) == 1 else preview
    monkeypatch.setattr(grouped, "_plan_single_body_page", plan)

    page = grouped.plan_full_group_page(groups, 1_000_000)

    assert page.inventory_refs == preview.inventory_refs
    assert page.body_refs == preview.body_refs
    assert page.groups == preview.groups
    assert len(calls) == 2 and calls[0][1] == calls[1][1]


def test_empty_and_unexpanded_evidence_keep_legacy_plans():
    assert grouped.plan_full_group_page([], 500) == grouped._plan_single_body_page([], 500)
    empty = [grouped.EvidenceGroup("literal empty search", [])]
    assert grouped.plan_full_group_page(empty, 500) == grouped._plan_single_body_page(empty, 500)
    card = _card("Q1.H1", full_padding=1)
    unexpanded = [grouped.EvidenceGroup("literal query", [replace(card, preview_content=None, preview_meta=None)])]
    assert grouped.plan_full_group_page(unexpanded, 5000) == grouped._plan_single_body_page(unexpanded, 5000)
    assert grouped.plan_full_group_page(_groups(count=1), 0).groups == []


def test_unverified_preview_cannot_be_invented_to_preserve_frontier():
    card = {"norm_key": "key", "norm_code": "fixture-code", "title": "Literal title",
            "measure_unit": "м", "source_ref": "exact-source", "work_steps": [],
            "resources": [{"code": "r", "name": "Literal resource", "unit": "м", "per_unit": 0}],
            "resource_preview": [], "resource_count": 1, "resources_returned": 1,
            "resources_complete": True, "hydration_status": "ok"}
    chunk = _norm_search_chunk(card, score=1, matched_before_cap=1)
    chunk.meta["hydration_preview_sha256"] = "not-the-literal-preview-sha"
    groups, _ = _model_rag_full_groups([("literal query", [chunk])], hits_per_query=6)
    assert groups[0].cards[0].preview_content is None
    page = grouped.plan_full_group_page(groups, 100_000)
    assert page.body_by_ref["Q1.H1"] == chunk.content
    assert page.complete_card_deferred_refs == []


def test_fallback_keeps_changed_source_generations_distinct_and_exact():
    first = _card("Q1.H1", full_padding=700, preview_padding=1)
    second = replace(_card("Q1.H2", full_padding=700, preview_padding=1),
                     content=first.content, preview_content=first.preview_content,
                     identity="different-base-generation",
                     meta={**first.meta, "normative_base_sha256": "b" * 64},
                     preview_meta={**first.preview_meta, "normative_base_sha256": "b" * 64})
    groups = [grouped.EvidenceGroup("literal query", [first, second])]
    legacy = grouped._render(_preview_groups(groups), {"Q1.H1", "Q1.H2"}, 1)
    page = grouped.plan_full_group_page(groups, legacy.rendered_chars)
    assert page.groups == legacy.groups
    assert page.body_refs == ["Q1.H1", "Q1.H2"]
    assert not page.shared_refs
    assert page.meta_by_ref["Q1.H1"]["normative_base_sha256"] == "a" * 64
    assert page.meta_by_ref["Q1.H2"]["normative_base_sha256"] == "b" * 64
    assert grouped.normative_card_identity(page.meta_by_ref["Q1.H1"]) != grouped.normative_card_identity(page.meta_by_ref["Q1.H2"])
