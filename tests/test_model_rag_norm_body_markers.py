"""Shown whole RAG bodies must distinguish preview resources from exact cards."""

import copy
import json

import pytest

from proxy.services.model_rag_grouped_evidence_service import (
    EvidenceCard, EvidenceGroup, _render, inventory_pointer, normative_card_identity,
    plan_full_group_page,
)


def _card(ref="Q1.H1", **fields):
    meta = {
        "norm_key": "literal-key", "norm_code": "literal-code",
        "source_ref": "literal-source#guid=immutable-card",
        "edition": "literal-edition", "base_type": "literal-base",
        "global_evidence_id": f"immutable:{ref}", **fields,
    }
    return EvidenceCard(ref, f"[{ref} | literal-source]", normative_card_identity(meta),
                        'LITERAL whole body; resources_complete=True is text, not metadata. м³\n', meta)


def _markers(page):
    return [record for line in "\n\n".join(page.groups).splitlines()
            if line.startswith("{") and "card_delivery_facts" in (record := json.loads(line))]


@pytest.mark.parametrize("fields,status,complete", [
    ({"resource_preview": [{"code": "r1"}], "resource_count": 1}, "preview", False),
    ({"resources_complete": False}, "preview", False),
    ({"resource_count": 3}, "preview", False),
    ({}, "unknown", False),
    ({"normative_card_complete": True, "normative_resources_status": "complete"}, "unknown", False),
    ({"resources_complete": True, "resources_returned": 1, "resource_count": 1,
      "resources": [{"code": "r1", "unit": "m", "per_unit": 0.125}]}, "complete", True),
    ({"resources_complete": True, "resources_returned": 1, "resource_count": 2,
      "resources": [{"code": "r1", "unit": "m", "per_unit": 0.125}]}, "preview", False),
    ({"resources_complete": True, "resources_returned": True,
      "resources": [{"code": "r1"}]}, "unknown", False),
])
def test_shown_norm_body_exposes_truthful_flags_and_literal_optional_read(fields, status, complete):
    card = _card(**fields)
    original = copy.deepcopy(card.meta)
    page = plan_full_group_page([EvidenceGroup("literal query", [card])], 1_000_000)

    marker, = _markers(page)
    expected = {"evidence_ref": card.ref, "card_delivery_facts": {
        "normative_card_complete": complete, "normative_resources_status": status,
    }}
    if not complete:
        expected["available_read"] = {"tool": "read_norm_card", "args": {"evidence_ref": card.ref}}
    assert marker == expected
    assert page.body_refs == [card.ref] and page.body_by_ref == {card.ref: card.content}
    assert f"{card.header}:\n{card.content}" in page.groups[0]
    assert page.pointer_by_ref == {card.ref: inventory_pointer(card, full=True)}
    assert json.loads(page.pointer_by_ref[card.ref])[1] == "full"
    assert card.meta == original


def test_each_shown_alias_has_own_literal_read_arguments_with_one_unchanged_raw_body():
    owner = _card("Q4.H2", resource_preview=[{"code": "r1"}], resource_count=1)
    alias = _card("Q9.H1", resource_preview=[{"code": "r1"}], resource_count=1)
    cards = [owner, alias]
    original = [copy.deepcopy(card.meta) for card in cards]
    page = plan_full_group_page([EvidenceGroup("literal query", cards)], 1_000_000)

    markers = _markers(page)
    assert [marker["evidence_ref"] for marker in markers] == [owner.ref, alias.ref]
    assert [marker["available_read"]["args"] for marker in markers] == [
        {"evidence_ref": owner.ref}, {"evidence_ref": alias.ref}]
    assert all(marker["card_delivery_facts"] == {
        "normative_card_complete": False, "normative_resources_status": "preview",
    } for marker in markers)
    assert page.shared_refs == {alias.ref: owner.ref}
    assert page.body_by_ref == {card.ref: card.content for card in cards}
    assert "\n\n".join(page.groups).count(owner.content) == 1
    assert [card.meta for card in cards] == original


def test_deferred_and_unshown_norms_never_get_shown_body_flags_or_read_marker():
    shown = _card("Q1.H1", resources_complete=False)
    deferred = _card("Q2.H1", resources_complete=True, resources_returned=0,
                     resource_count=0, resources=[])
    hidden = _card("Q3.H1", resources_complete=False)
    groups = [EvidenceGroup("literal shown", [shown]), EvidenceGroup("literal deferred", [deferred]),
              EvidenceGroup("literal hidden", [hidden])]

    page = _render(groups, {shown.ref, deferred.ref}, 1)

    marker, = _markers(page)
    assert marker["evidence_ref"] == shown.ref
    assert page.body_refs == [shown.ref]
    assert page.body_by_ref == {shown.ref: shown.content}
    assert page.deferred_refs == [deferred.ref, hidden.ref] and page.unshown_refs == [hidden.ref]
    assert json.loads(page.pointer_by_ref[deferred.ref])[1] == "deferred_capacity"
    assert hidden.ref not in page.pointer_by_ref
    assert not _markers(_render(groups, {card.ref for card in (shown, deferred, hidden)}, 0))


def test_ordinary_document_rendering_is_byte_exact_and_has_no_norm_read_marker():
    card = EvidenceCard("Q1.H1", "[literal document]", "document-identity", "RAW document body\n", {})
    page = plan_full_group_page([EvidenceGroup("literal query", [card])], 1_000_000)

    expected = (
        "Индекс: [ref,body_status,norm_key,norm_code,title,unit,source,read_source?]. "
        "full = целое найденное тело, возможен обзор ресурсов; deferred_capacity = только указатель. "
        "Доступно read_norm_card/read_source.\n\n"
        '{"returned_hits":1,"identities_shown":1,"full_body_aliases_shown":1,'
        '"deferred_body_aliases":0,"identities_unshown":0,"unshown_cursor":null}\n\n'
        'literal query\n\n["Q1.H1","full","","","[literal document]","","",{}]\n\n'
        "[literal document]:\nRAW document body\n"
    )
    assert page.groups == [expected]
    assert not _markers(page) and page.body_by_ref == {card.ref: card.content}


def test_marker_cost_is_included_in_capacity_and_cannot_claim_deferred_body_shown():
    card = _card(resources_complete=False)
    groups = [EvidenceGroup("literal query", [card])]
    full = plan_full_group_page(groups, 1_000_000)
    marker, = _markers(full)
    marker_wire = json.dumps(marker, ensure_ascii=False, separators=(",", ":"))
    assert marker_wire in full.groups[0]
    assert full.rendered_chars == len("\n\n".join(full.groups))

    exact = plan_full_group_page(groups, full.rendered_chars)
    below = plan_full_group_page(groups, full.rendered_chars - 1)

    assert exact.body_refs == [card.ref] and _markers(exact) == [marker]
    assert below.body_refs == [] and below.deferred_refs == [card.ref]
    assert not _markers(below) and below.body_by_ref == {}
    assert below.rendered_chars <= full.rendered_chars - 1
