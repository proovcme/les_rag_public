import copy
import hashlib
import json

import pytest

from proxy.services.model_rag_grouped_evidence_service import (
    EvidenceCard,
    EvidenceGroup,
    lossless_nrsp_body,
    normative_card_identity,
    plan_full_group_page,
    restore_nrsp_body,
    share_registry_catalogs,
    card_delivery_facts,
)


NRSP_HEADER = (
    "НР/СП: варианты каталога для сборника; выбор модели по условиям объекта, не готовая ставка:"
)


def test_document_index_keeps_an_actual_read_source_pointer_and_no_norm_identity():
    meta = {"doc_id": "doc:immutable", "dataset_id": "selected", "doc_name": "source.pdf",
            "source_locator": "p.7"}
    card = EvidenceCard("Q1.H1", "source.pdf", "document-identity", "literal document " * 1000, meta)
    page = plan_full_group_page([EvidenceGroup("literal query", [card])], 1500)
    assert page.inventory_refs == ["Q1.H1"] and page.body_refs == []
    pointer = json.loads(page.pointer_by_ref["Q1.H1"])
    assert pointer[-1] == meta
    assert normative_card_identity(meta) == ""


def test_read_registry_marks_deferred_pointer_as_unread_and_repeats_its_source_catalog():
    meta = {"norm_key": "fixture", "norm_code": "code-1", "source_ref": "literal-source",
            "body_status": "deferred_capacity"}
    catalogs, rows = share_registry_catalogs([
        {"evidence_ref": "Q1.H1", "content": "literal identity pointer", "source_ref": "literal-source",
         "body_available": True}], {"Q1.H1": meta})
    assert rows[0]["content"] == "literal identity pointer"
    assert rows[0]["body_available"] is False and rows[0]["card_body_shown"] is False
    source_pointer = rows[0]["source_ref"]["shared_source_pointer"]
    assert catalogs["literal_source_catalog"][source_pointer] == "literal-source"


def test_empty_search_query_headers_remain_visible_without_invented_cards():
    queries = [EvidenceGroup("Q1 literal empty query", []), EvidenceGroup("Q2 other empty query", [])]
    page = plan_full_group_page(queries, 1500)
    assert page.included_count == 2 and not page.body_refs and not page.inventory_refs
    assert "Q1 literal empty query" in "\n\n".join(page.groups)
    assert "Q2 other empty query" in "\n\n".join(page.groups)
    assert "hits=0" in "\n\n".join(page.groups)
    assert plan_full_group_page(queries, 0).groups == []


def test_whole_raw_resource_preview_does_not_claim_a_complete_typed_norm_card():
    meta = {"norm_code": "fixture", "resource_count": 2,
            "resource_preview": [{"code": "r1", "unit": "kg"}, {"code": "r2", "unit": "m"}]}
    facts = card_delivery_facts(meta, raw_body_shown=True)
    assert facts["raw_hit_body_shown"] and facts["normative_conditions_shown"] and facts["card_body_shown"]
    assert facts["normative_card_complete"] is False
    assert facts["normative_resources_status"] == "preview"
    unread = card_delivery_facts(meta, raw_body_shown=False)
    assert unread["normative_conditions_shown"] is False and unread["card_body_shown"] is False
    assert unread["normative_resources_status"] == "not_read"


def test_exact_resource_count_and_complete_flag_are_separate_from_raw_body_delivery():
    meta = {"norm_code": "fixture", "resource_count": 1, "resources_returned": 1,
            "resources_complete": True, "resources": [{"code": "r1", "unit": "kg", "per_unit": 2.5}]}
    facts = card_delivery_facts(meta, raw_body_shown=True)
    assert facts["normative_card_complete"] and facts["normative_resources_status"] == "complete"
    mismatch = card_delivery_facts({**meta, "resources_returned": 0}, raw_body_shown=True)
    assert mismatch["raw_hit_body_shown"] and not mismatch["normative_card_complete"]


def _rules():
    return [
        {
            "rule_id": f"fixture-rule-{index}",
            "label": f"Условие {index}: буквальный вариант",
            "nr_pct": 10 + index,
            "sp_pct": 5 + index,
            "basis": f"Synthetic catalog basis {index}",
            "source_ref": f"fixture-catalog#rule={index}",
            "source_sha256": {"nr": "a" * 64, "sp": "b" * 64},
            "edition": "fixture-edition-2026",
        }
        for index in (2, 1)
    ]


def _catalog_text(rules):
    return "\n".join(
        [NRSP_HEADER]
        + [
            f"{rule['rule_id']}: {rule['label']}; НР {rule['nr_pct']}%; "
            f"СП {rule['sp_pct']}%; {rule['basis']}; источник {rule['source_ref']}"
            for rule in rules
        ]
    )


def _body(rules, *, token="fixture-card", padding=0):
    resource = {
        "code": "fixture-resource",
        "name": 'Ресурс с "кавычками", пробелом и е\u0301',
        "unit": "м³",
        "per_unit": 0.125,
    }
    parts = [
        f"Шифр: {token}",
        "Наименование: Literal candidate",
        "Измеритель: 100 м²",
        "Состав работы: первая операция; вторая операция. Условия: без изменения.",
    ]
    if rules:
        parts.append(_catalog_text(rules))
    parts.extend(
        [
            "Полные ресурсы выбранной карточки; применимость выбирает модель:",
            json.dumps(resource, ensure_ascii=False, sort_keys=True),
            "resources_complete=True; resources_returned=1",
            token + "x" * padding,
        ]
    )
    return "\n".join(parts) + "\n"


def _card(ref, *, rules=None, content=None, identity=None, padding=0):
    return EvidenceCard(
        ref=ref,
        header=f"[{ref} | fixture-norms | score=0.5000]",
        identity=identity or f"immutable-{ref}",
        content=content if content is not None else _body(rules, token=ref, padding=padding),
        meta={
            "norm_key": f"key-{ref}",
            "norm_code": f"code-{ref}",
            "title": f"Literal title {ref}",
            "measure_unit": "м²",
            "source_ref": f"fixture-base#norm={ref}",
            "edition": "fixture-norm-edition",
            **({"nr_sp_candidates": rules} if rules is not None else {}),
        },
    )


def _groups(*, rules=None, count=3, padding=4000):
    return [
        EvidenceGroup(
            header=f"[Query Q{index}] Literal query {index}",
            cards=[_card(f"Q{index}.H{rank}", rules=rules, padding=padding) for rank in (1, 2)],
        )
        for index in range(1, count + 1)
    ]


def _refs(groups):
    return [card.ref for group in groups for card in group.cards]


def _minimum_inventory_budget(groups):
    expected = _refs(groups)
    low, high = 0, plan_full_group_page(groups, 1_000_000).rendered_chars
    while low < high:
        midpoint = (low + high) // 2
        if plan_full_group_page(groups, midpoint).inventory_refs == expected:
            high = midpoint
        else:
            low = midpoint + 1
    return low


def _norm_identity_meta():
    return {
        "norm_key": "fixture-immutable-key",
        "norm_code": "ГЭСНм99-01-001-02",
        "source_ref": "fixture-base#guid=exact-item",
        "source_sha256": "f" * 64,
        "edition": "fixture-edition-2026",
        "base_type": "fixture-base-type",
    }


def test_normative_identity_is_stable_across_aliases_and_metadata_key_order():
    meta = _norm_identity_meta()
    same = dict(reversed(list(meta.items())))
    same.update(model_evidence_ref="Q9.H2", global_evidence_id="another-turn-alias")

    assert normative_card_identity(meta) == normative_card_identity(same)
    assert normative_card_identity(meta) == normative_card_identity(copy.deepcopy(meta))


@pytest.mark.parametrize("changed", [
    {"norm_code": "ГЭСНм99-01-001"},
    {"norm_code": "ГЭСНм99-01-001-01"},
    {"norm_key": "another-exact-key"},
    {"source_ref": "another-base#guid=exact-item"},
    {"edition": "fixture-edition-2027"},
    {"base_type": "another-base-type"},
    {"source_sha256": "e" * 64},
    {"source_sha256": None},
])
def test_parent_cipher_or_changed_provenance_never_matches_exact_normative_identity(changed):
    meta = _norm_identity_meta()

    assert normative_card_identity(meta) != normative_card_identity({**meta, **changed})


@pytest.mark.parametrize("dash", ["-", "–", "—", "‑", "−"])
def test_only_full_cipher_case_and_dash_presentation_are_canonicalized(dash):
    meta = _norm_identity_meta()
    presented = {**meta, "norm_code": "  " + meta["norm_code"].lower().replace("-", dash) + "  "}

    assert normative_card_identity(meta) == normative_card_identity(presented)


def test_catalog_factoring_restores_every_original_utf8_byte_and_typed_field():
    rules = _rules()
    meta = {"nr_sp_candidates": rules, "source_ref": "fixture-base#norm=card"}
    original_meta = copy.deepcopy(meta)
    original = _body(rules)

    body = lossless_nrsp_body(original, meta)

    assert body.original == original
    assert body.catalog_id
    assert body.catalog_text == _catalog_text(rules)
    assert _catalog_text(rules) not in body.content
    assert body.catalog_id in body.content
    assert restore_nrsp_body(body).encode("utf-8") == original.encode("utf-8")
    assert hashlib.sha256(restore_nrsp_body(body).encode("utf-8")).digest() == hashlib.sha256(
        original.encode("utf-8")
    ).digest()
    for literal in ('"per_unit": 0.125', '"unit": "м³"', "100 м²", "первая операция; вторая операция"):
        assert literal in body.content
    assert meta == original_meta


def test_same_exact_catalog_is_shared_between_distinct_norm_sources():
    rules = _rules()
    cards = [_card("Q1.H1", rules=rules), _card("Q2.H1", rules=copy.deepcopy(rules))]
    bodies = [lossless_nrsp_body(card.content, card.meta) for card in cards]
    page = plan_full_group_page(
        [EvidenceGroup("first query", [cards[0]]), EvidenceGroup("second query", [cards[1]])],
        1_000_000,
    )

    assert cards[0].meta["source_ref"] != cards[1].meta["source_ref"]
    assert bodies[0].catalog_id == bodies[1].catalog_id
    rendered = "\n\n".join(page.groups)
    assert rendered.count(_catalog_text(rules)) == 1
    assert page.shared_refs == {}
    assert page.body_refs == ["Q1.H1", "Q2.H1"]
    assert page.body_by_ref == {card.ref: card.content for card in cards}
    assert all(body.catalog_id in rendered for body in bodies)


@pytest.mark.parametrize("changed", ["nr_sha", "sp_sha", "source_ref", "edition", "order", "label"])
def test_catalog_identity_includes_exact_candidate_metadata_and_order(changed):
    first_rules = _rules()
    second_rules = copy.deepcopy(first_rules)
    if changed in {"nr_sha", "sp_sha"}:
        second_rules[0]["source_sha256"][changed.removesuffix("_sha")] = "c" * 64
    elif changed == "order":
        second_rules.reverse()
    else:
        second_rules[0][changed] += " changed"
    first = _card("Q1.H1", rules=first_rules)
    second = _card("Q2.H1", rules=second_rules)
    first_body = lossless_nrsp_body(first.content, first.meta)
    second_body = lossless_nrsp_body(second.content, second.meta)
    page = plan_full_group_page(
        [EvidenceGroup("first", [first]), EvidenceGroup("second", [second])], 1_000_000
    )

    assert first_body.catalog_id != second_body.catalog_id
    assert restore_nrsp_body(first_body) == first.content
    assert restore_nrsp_body(second_body) == second.content
    assert "\n\n".join(page.groups).count("Общий буквальный каталог [") == 2
    assert page.shared_refs == {}


@pytest.mark.parametrize("invalid", ["no_rules", "malformed", "text_mismatch", "duplicate", "inline"])
def test_unverified_catalog_text_is_kept_literal_without_guessing(invalid):
    rules = _rules()
    meta = {"nr_sp_candidates": rules}
    original = _body(rules)
    if invalid == "no_rules":
        meta = {}
    elif invalid == "malformed":
        meta = {"nr_sp_candidates": [{"rule_id": "missing-fields"}]}
    elif invalid == "text_mismatch":
        meta = copy.deepcopy(meta)
        meta["nr_sp_candidates"][0]["label"] += " different label"
    elif invalid == "duplicate":
        original += _catalog_text(rules) + "\n"
    elif invalid == "inline":
        original = "Inline prefix " + _catalog_text(rules) + " inline suffix"

    body = lossless_nrsp_body(original, meta)

    assert body.content == original
    assert body.original == original
    assert body.catalog_id == body.catalog_text == ""
    assert restore_nrsp_body(body).encode("utf-8") == original.encode("utf-8")


def test_exact_capacity_boundary_defers_a_whole_group_without_slicing_any_card():
    groups = _groups(rules=_rules())
    full = plan_full_group_page(groups, 1_000_000)
    exact = plan_full_group_page(groups, full.rendered_chars)
    below = plan_full_group_page(groups, full.rendered_chars - 1)

    assert exact.included_count == len(groups)
    assert exact.body_refs == exact.inventory_refs == _refs(groups)
    assert exact.deferred_refs == exact.unshown_refs == []
    assert below.included_count == len(groups) - 1
    assert below.body_refs == _refs(groups[:-1])
    assert below.deferred_refs == _refs(groups[-1:])
    assert below.inventory_refs == _refs(groups)
    assert below.unshown_refs == []
    assert below.rendered_chars == len("\n\n".join(below.groups))
    assert below.rendered_chars <= full.rendered_chars - 1
    for group in groups:
        for card in group.cards:
            if card.ref in below.body_refs:
                assert below.body_by_ref[card.ref].encode("utf-8") == card.content.encode("utf-8")
            else:
                assert card.ref not in below.body_by_ref
    assert "…" not in "\n\n".join(below.groups)


def test_inventory_only_page_exposes_exact_read_pointers_without_claiming_body_delivery():
    groups = _groups()
    budget = _minimum_inventory_budget(groups)
    page = plan_full_group_page(groups, budget)

    assert page.included_count == 0
    assert page.body_refs == []
    assert page.body_by_ref == page.shared_refs == {}
    assert page.inventory_refs == page.deferred_refs == _refs(groups)
    assert page.unshown_refs == []
    assert page.rendered_chars <= budget
    rendered = "\n\n".join(page.groups)
    for group in groups:
        for card in group.cards:
            pointer = json.loads(page.pointer_by_ref[card.ref])
            assert pointer[:6] == [
                card.ref, "deferred_capacity", card.meta["norm_key"], card.meta["norm_code"],
                card.meta["title"], card.meta["measure_unit"],
            ]
            assert pointer[6] in rendered
            assert card.meta["source_ref"] in rendered
            assert card.content not in rendered
    assert "read_norm_card" in rendered


def test_inventory_tail_cannot_stall_a_physically_fitting_first_complete_group():
    first = _card("Q1.H1", padding=20)
    groups = [EvidenceGroup("first literal query", [first])] + [
        EvidenceGroup(f"query {index}", [_card(f"Q{index}.H1", padding=5000)])
        for index in range(2, 21)
    ]
    oversized_first = EvidenceCard(
        first.ref, first.header, first.identity, first.content + "z" * 90_000, first.meta
    )
    inventory_groups = [EvidenceGroup(groups[0].header, [oversized_first]), *groups[1:]]
    budget = _minimum_inventory_budget(inventory_groups)
    inventory_only = plan_full_group_page(inventory_groups, budget)
    first_alone = plan_full_group_page(groups[:1], budget)
    page = plan_full_group_page(groups, budget)

    assert inventory_only.included_count == 0
    assert inventory_only.inventory_refs == _refs(groups)
    assert first_alone.included_count == 1
    assert first_alone.body_by_ref == {first.ref: first.content}
    assert page.included_count == 1
    assert page.body_refs == [first.ref]
    assert page.body_by_ref == {first.ref: first.content}
    assert page.unshown_refs
    assert page.inventory_refs + page.unshown_refs == _refs(groups)
    assert page.deferred_refs == _refs(groups[1:])
    assert page.rendered_chars <= budget


@pytest.mark.parametrize("budget_kind", ["zero", "index_boundary"])
def test_unshown_inventory_has_explicit_refs_and_never_becomes_full_evidence(budget_kind):
    groups = _groups()
    budget = 0 if budget_kind == "zero" else _minimum_inventory_budget(groups) - 1
    page = plan_full_group_page(groups, budget)

    assert page.included_count == 0
    assert page.body_refs == []
    assert page.body_by_ref == {}
    assert page.deferred_refs == _refs(groups)
    assert page.unshown_refs
    assert page.inventory_refs + page.unshown_refs == _refs(groups)
    assert set(page.pointer_by_ref) == set(page.inventory_refs)
    assert not (set(page.pointer_by_ref) & set(page.unshown_refs))
    assert page.rendered_chars <= budget


def test_body_alias_requires_both_same_identity_and_exact_full_content():
    content = "Unique literal body\nWork steps; unit=m2; per_unit=0.125\n"
    first = _card("Q1.H1", content=content, identity="same-immutable-source")
    alias = EvidenceCard("Q2.H1", "[Q2.H1]", first.identity, first.content, first.meta)
    other_source = _card("Q3.H1", content=content, identity="different-immutable-source")
    other_content = _card("Q4.H1", content=content + "One more literal condition.\n", identity=first.identity)
    cards = [first, alias, other_source, other_content]
    page = plan_full_group_page(
        [EvidenceGroup(f"query {index}", [card]) for index, card in enumerate(cards, 1)],
        1_000_000,
    )

    assert page.shared_refs == {"Q2.H1": "Q1.H1"}
    assert page.body_refs == [card.ref for card in cards]
    assert page.body_by_ref == {card.ref: card.content for card in cards}
    assert "\n\n".join(page.groups).count(content) == 3
    assert page.deferred_refs == []


def test_found_inventory_and_complete_delivery_are_counted_separately_for_114_cards():
    groups = [
        EvidenceGroup(
            f"[Query Q{index}] Literal query {index}",
            [_card(f"Q{index}.H{rank}", rules=_rules(), padding=1000) for rank in range(1, 7)],
        )
        for index in range(1, 20)
    ]
    full = plan_full_group_page(groups, 1_000_000)
    budget = full.rendered_chars - 1
    page = plan_full_group_page(groups, budget)

    assert len(_refs(groups)) == len(page.inventory_refs) == 114
    assert len(page.body_refs) < 114
    assert len(page.body_refs) + len(page.deferred_refs) == 114
    assert not (set(page.body_refs) & set(page.deferred_refs))
    assert set(page.body_refs) | set(page.deferred_refs) == set(_refs(groups))
    assert page.unshown_refs == []
    assert "Q9.H2" in page.inventory_refs
    assert page.rendered_chars <= budget
    assert page.body_by_ref == {
        card.ref: card.content for group in groups for card in group.cards if card.ref in page.body_refs
    }
