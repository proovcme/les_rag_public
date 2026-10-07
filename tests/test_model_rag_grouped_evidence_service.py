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
    compact_read_replay,
    native_read_growth_budget,
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


def test_compact_read_replay_preserves_exact_catalog_bytes_and_full_resource_fields():
    rules = _rules()
    original = _body(rules)
    resource = {"code": "fixture-resource", "unit": "м³", "per_unit": 0.125}
    chunk = {
        "doc_name": "fixture-norms", "content": original,
        "meta": {**_norm_identity_meta(), "model_evidence_ref": "Q1.H1", "global_evidence_id": "g1",
                 "nr_sp_candidates": rules, "resources": [resource], "resource_count": 1,
                 "resources_returned": 1, "resources_complete": True},
    }
    unchanged = copy.deepcopy(chunk)

    catalogs, registry = compact_read_replay([chunk])

    row, = registry["previously_shown_evidence_registry"]
    factored = lossless_nrsp_body(original, chunk["meta"])
    assert catalogs["literal_nrsp_catalog"][factored.catalog_id].encode("utf-8") == _catalog_text(rules).encode("utf-8")
    restored = row["content"].replace(
        f"НР/СП: общий буквальный каталог [{factored.catalog_id}].",
        catalogs["literal_nrsp_catalog"][factored.catalog_id],
        1,
    )
    assert restored.encode("utf-8") == original.encode("utf-8")
    for literal in ('"per_unit": 0.125', '"unit": "м³"', 'Ресурс с \\"кавычками\\"', "100 м²", "первая операция; вторая операция"):
        assert literal in row["content"]
    assert row["normative_card_complete"] is True
    assert row["normative_resources_status"] == "complete"
    assert row["source_sha256"] == chunk["meta"]["source_sha256"]
    assert catalogs["literal_source_catalog"][row["source_ref"]["shared_source_pointer"]] == chunk["meta"]["source_ref"]
    assert chunk == unchanged


def _resource_source_fixture(ref="Q1.H1", *, source=None, sha="a" * 64, count=4):
    from proxy.services.model_research_tool_service import _full_norm_card_content
    from proxy.services.model_resource_reference_service import resource_slot_records

    source = source if source is not None else (
        'typed-norms://immutable/Состав "ресурсов"/' + "catalog-provenance/" * 18 + "#row=source"
    )
    card = {"norm_key": "literal-card", "norm_code": "fixture-code", "title": 'Объект "А"',
            "measure_unit": "100 м²", "source_ref": source, "source_sha256": sha,
            "work_steps": ["буквальный состав"], "resources_complete": True,
            "resources_returned": count,
            "resources": [{"kind": "material", "code": f"r-{i}", "name": 'Ресурс "А"\u2028Б',
                           "unit": "м³", "per_unit": 0.125 + i, "source_ref": source,
                           "source_sha256": sha, "optional": None, "flag": False,
                           "literal": {"quoted": '«текст» \\ "строка"'}}
                          for i in range(count)]}
    meta = {**card, "resources": resource_slot_records(card), "exact_card_read": True,
            "model_evidence_ref": ref, "global_evidence_id": "global-" + ref}
    return EvidenceCard(ref, "literal header", normative_card_identity(meta),
                        _full_norm_card_content(card), meta)


def _resource_json_lines(content):
    rows = []
    for line in content.split("\n"):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and "resource_slot" in row:
            rows.append(row)
    return rows


def _restore_resource_source_view(content, sources):
    result = []
    for line in content.split("\n"):
        try:
            row = json.loads(line)
        except ValueError:
            row = None
        if (isinstance(row, dict) and "resource_slot" in row
                and isinstance(row.get("source_ref"), dict)
                and set(row["source_ref"]) == {"shared_source_pointer"}):
            row["source_ref"] = sources[row["source_ref"]["shared_source_pointer"]]
            line = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
        result.append(line)
    return "\n".join(result)


def _page_source_catalog(page):
    sources = {}
    for line in "\n\n".join(page.groups).split("\n"):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if (isinstance(record, list) and len(record) == 2
                and isinstance(record[0], str) and record[0].startswith("source_")):
            sources[record[0]] = record[1]
    return sources


def test_resource_source_transport_restores_producer_bytes_and_literal_fields():
    card = _resource_source_fixture()
    unchanged = copy.deepcopy(card.meta)
    catalogs, rows = share_registry_catalogs([
        {"evidence_ref": card.ref, "content": card.content, "source_ref": card.meta["source_ref"]}
    ], {card.ref: card.meta})
    row, = rows
    resources = _resource_json_lines(row["content"])

    assert all(isinstance(resource["source_ref"], dict) for resource in resources)
    assert len(resources) == len(card.meta["resources"]) == 4
    assert _restore_resource_source_view(row["content"], catalogs["literal_source_catalog"]).encode("utf-8") == card.content.encode("utf-8")
    assert "shared_source_pointer" in catalogs["resource_source_pointer_meaning"]
    assert "literal_source_catalog" in catalogs["resource_source_pointer_meaning"]
    for actual, original in zip(resources, card.meta["resources"]):
        pointer = actual["source_ref"]["shared_source_pointer"]
        actual["source_ref"] = catalogs["literal_source_catalog"][pointer]
        assert actual == original
    assert card.meta == unchanged


def test_initial_and_native_resource_views_preserve_raw_resource_proof_and_aliases():
    from proxy.services.model_resource_reference_service import shown_resource_record

    card = _resource_source_fixture()
    alias = EvidenceCard("Q2.H3", "alias header", card.identity, card.content,
                         {**card.meta, "model_evidence_ref": "Q2.H3", "global_evidence_id": "global-Q2.H3"})
    groups = [EvidenceGroup("literal query", [card, alias])]
    frozen_groups = copy.deepcopy(groups)
    page = plan_full_group_page(groups, 1_000_000)
    initial = "\n\n".join(page.groups)
    sources = _page_source_catalog(page)
    assert '"source_ref": {"shared_source_pointer":' in initial
    assert "shared_source_pointer" in initial and "literal_source_catalog" in initial
    assert "Буквальные источники индекса (literal_source_catalog, пары [ID,значение])" in initial
    assert page.body_by_ref == {card.ref: card.content, alias.ref: alias.content}
    assert page.shared_refs == {alias.ref: card.ref}
    assert all(shown_resource_record(card.meta, page.body_by_ref[card.ref], slot)
               == {key: value for key, value in card.meta["resources"][slot - 1].items() if key != "resource_slot"}
               for slot in range(1, 5))

    chunks = [{"doc_name": "literal norms", "content": item.content, "meta": item.meta}
              for item in (card, alias)]
    frozen_chunks = copy.deepcopy(chunks)
    catalogs, registry = compact_read_replay(chunks)
    replay, = registry["previously_shown_evidence_registry"]
    assert '"source_ref": {"shared_source_pointer":' in replay["content"]
    assert _restore_resource_source_view(replay["content"], catalogs["literal_source_catalog"]) == card.content
    assert replay["aliases"] == [{"evidence_ref": alias.ref, "global_evidence_id": alias.meta["global_evidence_id"]}]
    assert replay["normative_card_complete"] is True and replay["normative_resources_status"] == "complete"
    assert "shared_source_pointer" in registry["body_delivery"]
    # The projected view cannot manufacture the existing raw literal proof.
    assert shown_resource_record(card.meta, replay["content"], 1) is None
    assert sources == catalogs["literal_source_catalog"]
    assert groups == frozen_groups and chunks == frozen_chunks


@pytest.mark.parametrize("changed", ["sha", "source", "resource"])
def test_distinct_resource_provenance_never_shares_card_body(changed):
    first = _resource_source_fixture()
    other = _resource_source_fixture("Q2.H1", sha="b" * 64 if changed == "sha" else "a" * 64,
                                    source=first.meta["source_ref"] + "/different" if changed == "source" else None)
    if changed == "resource":
        resources = copy.deepcopy(other.meta["resources"])
        resources[0]["per_unit"] = 9.875
        before = json.dumps(other.meta["resources"][0], ensure_ascii=False, sort_keys=True, default=str)
        after = json.dumps(resources[0], ensure_ascii=False, sort_keys=True, default=str)
        other = EvidenceCard(other.ref, other.header, other.identity, other.content.replace(before, after),
                             {**other.meta, "resources": resources})
    originals = copy.deepcopy([first, other])
    catalogs, registry = compact_read_replay([
        {"doc_name": "norms", "content": item.content, "meta": item.meta} for item in (first, other)])
    rows = registry["previously_shown_evidence_registry"]
    assert [row["evidence_ref"] for row in rows] == [first.ref, other.ref]
    assert all("aliases" not in row and "shared_body_ref" not in row for row in rows)
    assert [_restore_resource_source_view(row["content"], catalogs["literal_source_catalog"])
            for row in rows] == [first.content, other.content]
    assert [row["source_sha256"] for row in rows] == [first.meta["source_sha256"], other.meta["source_sha256"]]
    assert [first, other] == originals


@pytest.mark.parametrize("invalid", ["changed_metadata", "changed_source", "missing_line", "duplicate_line",
                                      "inline_line", "reordered_lines", "missing_slot", "duplicate_slot", "bool_slot",
                                      "missing_exact_read", "false_exact_read"])
def test_unverified_resource_lines_are_kept_whole_without_factoring(invalid):
    card = _resource_source_fixture()
    meta = copy.deepcopy(card.meta)
    content = card.content
    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) for row in meta["resources"]]
    if invalid == "changed_metadata":
        meta["resources"][1]["per_unit"] = 17
    elif invalid == "changed_source":
        meta["resources"][1]["source_ref"] += "/changed"
    elif invalid == "missing_line":
        content = content.replace(lines[1] + "\n", "")
    elif invalid == "duplicate_line":
        content += "\n" + lines[1]
    elif invalid == "inline_line":
        content = content.replace(lines[1], "prefix " + lines[1])
    elif invalid == "reordered_lines":
        content = content.replace("\n".join(lines), "\n".join(reversed(lines)))
    elif invalid == "missing_slot":
        meta["resources"][1].pop("resource_slot")
    elif invalid == "duplicate_slot":
        meta["resources"][1]["resource_slot"] = 1
    elif invalid == "bool_slot":
        meta["resources"][0]["resource_slot"] = True
    elif invalid == "missing_exact_read":
        meta.pop("exact_card_read")
    else:
        meta["exact_card_read"] = False
    unchanged = copy.deepcopy(meta)
    catalogs, rows = share_registry_catalogs([
        {"evidence_ref": card.ref, "content": content, "source_ref": meta["source_ref"]}], {card.ref: meta})
    assert rows[0]["content"] == content
    assert "resource_source_pointer_meaning" not in catalogs
    assert meta == unchanged


@pytest.mark.parametrize("invalid", ["short_source", "source_collision", "projected_line_collision"])
def test_resource_sharing_never_grows_short_values_or_resolves_collisions(monkeypatch, invalid):
    import proxy.services.model_rag_grouped_evidence_service as service

    card = _resource_source_fixture(source="short" if invalid == "short_source" else None)
    meta = copy.deepcopy(card.meta)
    content = card.content
    if invalid == "source_collision":
        monkeypatch.setattr(service, "_source_id", lambda source: "source_collision")
        meta["source_ref"] = "other literal top-level source"
    elif invalid == "projected_line_collision":
        row = dict(meta["resources"][0])
        row["source_ref"] = {"shared_source_pointer": service._source_id(meta["source_ref"])}
        content += "\n" + json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
    catalogs, rows = share_registry_catalogs([
        {"evidence_ref": card.ref, "content": content, "source_ref": meta["source_ref"]}], {card.ref: meta})
    assert rows[0]["content"] == content
    assert "resource_source_pointer_meaning" not in catalogs


@pytest.mark.parametrize("within_body", [False, True])
def test_nested_resource_catalog_collision_cannot_overwrite_an_earlier_literal(monkeypatch, within_body):
    import proxy.services.model_rag_grouped_evidence_service as service

    first = _resource_source_fixture()
    second = _resource_source_fixture("Q2.H1", sha="b" * 64)
    cards = []
    for index, card in enumerate((first, second)):
        meta = copy.deepcopy(card.meta)
        content = card.content
        for row_index, resource in enumerate(meta["resources"]):
            before = json.dumps(resource, ensure_ascii=False, sort_keys=True, default=str)
            resource["source_ref"] = "resource-only://" + ("A" if index == 0 else "B") * 280
            if within_body and row_index == 1:
                resource["source_ref"] = "resource-only://" + "C" * 280
            after = json.dumps(resource, ensure_ascii=False, sort_keys=True, default=str)
            content = content.replace(before, after)
        cards.append(EvidenceCard(card.ref, card.header, card.identity, content, meta))
    original_id = service._source_id
    monkeypatch.setattr(service, "_source_id", lambda source: "source_nested_collision"
                        if source.startswith("resource-only://") else original_id(source))
    chunks = [{"doc_name": "literal norms", "content": card.content, "meta": card.meta} for card in cards]
    unchanged = copy.deepcopy(chunks)
    catalogs, registry = compact_read_replay(chunks)
    rows = registry["previously_shown_evidence_registry"]
    if within_body:
        assert [row["content"] for row in rows] == [card.content for card in cards]
        assert "source_nested_collision" not in catalogs["literal_source_catalog"]
    else:
        assert catalogs["literal_source_catalog"]["source_nested_collision"] == cards[0].meta["resources"][0]["source_ref"]
        assert isinstance(_resource_json_lines(rows[0]["content"])[0]["source_ref"], dict)
        assert rows[1]["content"] == cards[1].content
        assert [_restore_resource_source_view(row["content"], catalogs["literal_source_catalog"])
                for row in rows] == [card.content for card in cards]
    assert chunks == unchanged


@pytest.mark.parametrize("surface", ["initial", "registry"])
def test_resource_pointer_cannot_capture_a_future_visible_top_source(monkeypatch, surface):
    import proxy.services.model_rag_grouped_evidence_service as service

    first = _resource_source_fixture(source="top-zero://" + "Z" * 280)
    nested = "resource-only://" + "A" * 280
    future = "future-top://" + "B" * 280
    meta = copy.deepcopy(first.meta)
    content = first.content
    for resource in meta["resources"]:
        before = json.dumps(resource, ensure_ascii=False, sort_keys=True, default=str)
        resource["source_ref"] = nested
        content = content.replace(before, json.dumps(resource, ensure_ascii=False, sort_keys=True, default=str))
    first = EvidenceCard(first.ref, first.header, first.identity, content, meta)
    second = _resource_source_fixture("Q2.H1", source=future, sha="b" * 64)
    original_id = service._source_id
    monkeypatch.setattr(service, "_source_id", lambda source: "source_future_collision"
                        if source in (nested, future) else original_id(source))
    originals = copy.deepcopy([first, second])
    if surface == "initial":
        page = plan_full_group_page([EvidenceGroup("one", [first]), EvidenceGroup("two", [second])], 1_000_000)
        sources = _page_source_catalog(page)
        assert sources[json.loads(page.pointer_by_ref[second.ref])[6]] == future
        assert page.body_by_ref == {card.ref: card.content for card in (first, second)}
        assert first.content in "\n\n".join(page.groups)
    else:
        sources, rows = share_registry_catalogs([
            {"evidence_ref": card.ref, "content": card.content, "source_ref": card.meta["source_ref"]}
            for card in (first, second)], {card.ref: card.meta for card in (first, second)})
        sources = sources["literal_source_catalog"]
        assert sources[rows[1]["source_ref"]["shared_source_pointer"]] == future
        assert rows[0]["content"] == first.content
        assert [_restore_resource_source_view(row["content"], sources) for row in rows] == [card.content for card in (first, second)]
    assert [first, second] == originals


def test_resource_collision_reservation_does_not_expose_unshown_top_sources(monkeypatch):
    import proxy.services.model_rag_grouped_evidence_service as service

    first = _resource_source_fixture(source="top-zero://" + "Z" * 280)
    nested = "resource-only://" + "A" * 280
    unshown = "future-unshown://" + "B" * 280
    meta = copy.deepcopy(first.meta)
    content = first.content
    for resource in meta["resources"]:
        before = json.dumps(resource, ensure_ascii=False, sort_keys=True, default=str)
        resource["source_ref"] = nested
        content = content.replace(before, json.dumps(resource, ensure_ascii=False, sort_keys=True, default=str))
    first = EvidenceCard(first.ref, first.header, first.identity, content, meta)
    second = _resource_source_fixture("Q2.H1", source=unshown, sha="b" * 64)
    original_id = service._source_id
    monkeypatch.setattr(service, "_source_id", lambda source: "source_unshown_collision"
                        if source in (nested, unshown) else original_id(source))
    page = service._render([EvidenceGroup("one", [first]), EvidenceGroup("two", [second])], {first.ref}, 1)
    sources = _page_source_catalog(page)
    assert sources["source_unshown_collision"] == nested
    assert unshown not in "\n\n".join(page.groups)
    assert second.ref in page.unshown_refs and second.ref not in page.pointer_by_ref
    assert '"source_ref": {"shared_source_pointer":' in "\n\n".join(page.groups)
    assert page.body_by_ref == {first.ref: first.content}


def test_resource_source_projection_leaves_other_literal_occurrences_and_nrsp_unchanged():
    card = _resource_source_fixture()
    rules = _rules()
    raw = _body(rules) + "\n" + card.content + "\n" + "Unrelated quoted source: " + card.meta["source_ref"]
    meta = {**card.meta, "nr_sp_candidates": rules}
    nrsp = lossless_nrsp_body(raw, meta)
    catalogs, rows = share_registry_catalogs([
        {"evidence_ref": card.ref, "content": raw, "source_ref": meta["source_ref"]}], {card.ref: meta})
    view = rows[0]["content"]
    assert '"source_ref": {"shared_source_pointer":' in view
    assert view.endswith("Unrelated quoted source: " + card.meta["source_ref"])
    restored = _restore_resource_source_view(view, catalogs["literal_source_catalog"]).replace(
        f"НР/СП: общий буквальный каталог [{nrsp.catalog_id}].", catalogs["literal_nrsp_catalog"][nrsp.catalog_id], 1)
    assert restored.encode("utf-8") == raw.encode("utf-8")
    assert catalogs["literal_nrsp_catalog"] == {nrsp.catalog_id: nrsp.catalog_text}


def test_resource_source_projection_reduces_only_transport_size_not_raw_semantics():
    card = _resource_source_fixture(count=18)
    record = {"evidence_ref": card.ref, "content": card.content, "source_ref": card.meta["source_ref"]}
    catalogs, rows = share_registry_catalogs([record], {card.ref: card.meta})
    raw_projection = copy.deepcopy(rows)
    raw_projection[0]["content"] = card.content
    before = json.dumps([{name: value for name, value in catalogs.items() if name != "resource_source_pointer_meaning"}, raw_projection], ensure_ascii=False)
    after = json.dumps([catalogs, rows], ensure_ascii=False)
    assert len(after) < len(before)
    assert len(after.encode("utf-8")) < len(before.encode("utf-8"))
    assert record["content"] == card.content
    assert _restore_resource_source_view(rows[0]["content"], catalogs["literal_source_catalog"]) == record["content"]


@pytest.mark.parametrize("changed", [{"source_sha256": "e" * 64}, {"edition": "fixture-edition-2027"}])
def test_compact_read_replay_never_aliases_identical_bodies_across_changed_provenance(changed):
    body = _body(_rules())
    chunks = [
        {"doc_name": "fixture-norms", "content": body,
         "meta": {**_norm_identity_meta(), **(changed if index == 2 else {}),
                  "model_evidence_ref": f"Q{index}.H1", "global_evidence_id": f"g{index}"}}
        for index in (1, 2)
    ]

    _, registry = compact_read_replay(chunks)

    rows = registry["previously_shown_evidence_registry"]
    assert [row["evidence_ref"] for row in rows] == ["Q1.H1", "Q2.H1"]
    assert [row["content"] for row in rows] == [body, body]
    assert all("aliases" not in row and "shared_body_ref" not in row for row in rows)
    assert rows[1]["source_sha256"] == chunks[1]["meta"]["source_sha256"]
    assert rows[1]["edition"] == chunks[1]["meta"]["edition"]


def test_compact_read_replay_preserves_literal_deferred_pointer_without_exposing_unshown_body():
    pointer = json.dumps(["Q1.H1", "deferred_capacity", "literal-key", "literal-code", 'Имя с "кавычками"', "м³", "source-id"],
                         ensure_ascii=False, indent=2)
    hidden_body = "UNSHOWN full source body must never reach the model"
    chunks = [
        {"content": pointer,
         "meta": {**_norm_identity_meta(), "model_evidence_ref": "Q1.H1", "body_status": "deferred_capacity"}},
        {"content": hidden_body,
         "meta": {**_norm_identity_meta(), "model_evidence_ref": "Q2.H1", "body_status": "deferred_capacity"}},
    ]

    replay = compact_read_replay(chunks)

    assert replay[1]["previously_shown_evidence_registry"] == []
    assert pointer.encode("utf-8") in replay[2].encode("utf-8")
    assert hidden_body not in json.dumps(replay, ensure_ascii=False)
    generated_pointer = json.loads(replay[2].splitlines()[-1])
    assert generated_pointer[:2] == ["Q2.H1", "deferred_capacity"]
    assert generated_pointer[2:4] == [chunks[1]["meta"]["norm_key"], chunks[1]["meta"]["norm_code"]]


@pytest.mark.parametrize(("available", "generation", "requested"), [(2000, 300, 300), (1001, 2000, 500), (0, 100, 0)])
def test_native_read_growth_budget_derives_request_from_generation_and_available_window(available, generation, requested):
    budget = native_read_growth_budget(available_tokens=available, generation_tokens=generation, groups=[], enabled=True)

    assert budget["requested_tokens"] == requested
    assert budget["reserved_tokens"] == requested
    assert budget["remaining_group_tokens"] == available - requested


def test_native_read_growth_reserve_preserves_first_whole_group_with_long_catalog_and_inventory():
    rules = _rules()
    rules[0]["label"] += " длинное буквальное условие" * 100
    groups = _groups(rules=rules, count=20, padding=3000)
    first_alone = plan_full_group_page(groups[:1], 1_000_000)
    available = (first_alone.rendered_chars + 1) // 2 + 1000

    budget = native_read_growth_budget(available_tokens=available, generation_tokens=available, groups=groups, enabled=True)
    page = plan_full_group_page(groups, budget["remaining_group_tokens"] * 2)

    assert budget["requested_tokens"] == available // 2
    assert 0 < budget["reserved_tokens"] < budget["requested_tokens"]
    assert budget["reserved_tokens"] == available - budget["first_whole_group_tokens"]
    assert page.included_count >= 1, budget
    assert set(_refs(groups[:1])) <= set(page.body_refs)
    assert all(page.body_by_ref[card.ref] == card.content for card in groups[0].cards)
    assert page.deferred_refs and page.unshown_refs
    assert page.rendered_chars <= budget["remaining_group_tokens"] * 2


def test_native_read_growth_budget_reserves_nothing_when_first_whole_group_cannot_fit():
    groups = _groups(rules=_rules(), count=2, padding=4000)
    available = 1000

    budget = native_read_growth_budget(available_tokens=available, generation_tokens=2000, groups=groups, enabled=True)
    page = plan_full_group_page(groups, budget["remaining_group_tokens"] * 2)

    assert budget["requested_tokens"] == 500
    assert budget["first_whole_group_tokens"] > available
    assert budget["reserved_tokens"] == 0
    assert budget["remaining_group_tokens"] == available
    assert page.included_count == 0 and page.body_refs == []


def test_six_thousand_token_window_keeps_an_already_fitting_4800_token_whole_group():
    card = _card("Q1.H1")
    groups = [EvidenceGroup("literal model query", [card])]
    initial = native_read_growth_budget(available_tokens=6000, generation_tokens=6000,
                                       groups=groups, enabled=True)
    padding = (4800 - initial["first_whole_group_tokens"]) * 2
    assert padding > 0
    groups = [EvidenceGroup(groups[0].header, [EvidenceCard(
        card.ref, card.header, card.identity, card.content + "x" * padding, card.meta)])]
    budget = native_read_growth_budget(available_tokens=6000, generation_tokens=6000,
                                      groups=groups, enabled=True)
    assert budget["first_whole_group_tokens"] == 4800
    assert budget["requested_tokens"] == 3000
    assert budget["reserved_tokens"] == 1200
    assert budget["remaining_group_tokens"] == 4800
    page = plan_full_group_page(groups, budget["remaining_group_tokens"] * 2)
    assert page.included_count == 1 and page.body_by_ref[card.ref] == groups[0].cards[0].content


def test_disabled_native_read_growth_budget_keeps_all_available_tokens_for_groups():
    budget = native_read_growth_budget(available_tokens=4000, generation_tokens=2000,
                                      groups=_groups(), enabled=False)

    assert budget["requested_tokens"] == budget["reserved_tokens"] == 0
    assert budget["remaining_group_tokens"] == 4000


def _read_replay_chunk(ref, content, **metadata):
    return {"doc_name": "literal-source", "content": content, "meta": {
        **_norm_identity_meta(), "norm_key": f"literal-key-{ref}", "norm_code": f"literal-code-{ref}",
        "source_ref": f"literal-source#{ref}", "model_evidence_ref": ref,
        "global_evidence_id": f"immutable-{ref}", "body_status": "full", **metadata,
    }}


def _prepare_read_replay(chunks, **kwargs):
    from proxy.services.model_rag_grouped_evidence_service import prepare_model_read_replay
    return prepare_model_read_replay(chunks, **kwargs)


@pytest.mark.parametrize("exact_metadata,required_refs", [
    ({"model_read_tool": "read_norm_card"}, ()),
    ({"model_read_tool": "read_resource_price"}, ()),
    ({"model_read_tool": "read_source"}, ()),
    ({"exact_card_read": True}, ()),
    ({"source_read": True}, ()),
    ({}, ("Q1.H1",)),
    ({}, ("immutable-Q1.H1",)),
])
def test_read_replay_preserves_exact_body_and_raw_discovery_identity(exact_metadata, required_refs):
    exact_body = _body(None, token="EXACT LITERAL RESOURCE RECEIPT")
    discovery_body = "UNADMITTED DISCOVERY BODY " + "resource quantity=0.125; " * 1000
    chunks = [_read_replay_chunk("Q1.H1", exact_body, **exact_metadata),
              _read_replay_chunk("Q2.H1", discovery_body, model_read_tool="search_sources",
                                 model_delivery_status="prepared", model_raw_body_retained=True)]
    original = copy.deepcopy(chunks)

    plan = _prepare_read_replay(chunks, required_refs=required_refs)

    assert plan.inventory_refs == ["Q1.H1", "Q2.H1"]
    assert plan.exact_body_refs == ["Q1.H1"]
    row, = plan.required[1]["previously_shown_evidence_registry"]
    assert row["content"].encode("utf-8") == exact_body.encode("utf-8")
    assert row["global_evidence_id"] == "immutable-Q1.H1"
    assert row["source_sha256"] == original[0]["meta"]["source_sha256"]
    assert discovery_body not in json.dumps(plan.required, ensure_ascii=False)
    assert plan.optional_body_refs == [["Q2.H1"]]
    assert discovery_body in plan.optional[0]
    assert chunks == original


def _read_replay_governor(plan, *, remaining_tokens):
    from proxy.services.context_governor_service import (
        ContextCandidate, ContextGovernor, ContextKind, ContextObject, conservative_token_estimate,
    )
    from proxy.services.model_execution_preset_service import ModelExecutionPreset
    required = tuple(ContextObject(f"required:{i}", value) for i, value in enumerate(plan.required))
    cost = sum(conservative_token_estimate(item.render()) for item in required) + len(required) - 1
    preset = ModelExecutionPreset(
        preset_id="literal-read-budget", model_family="fixture", input_token_limit=cost + remaining_tokens + 200,
        generation_reserve_tokens=100, safety_reserve_tokens=100, normal_tool_count=1, max_tools=5,
        max_batch_items=6, parallel_read_limit=1, reasoning_enabled=False, source_chain=("fixture",),
    )
    return ContextGovernor(preset), [
        ContextCandidate(ContextKind.EVIDENCE, required, required=True),
        ContextCandidate(ContextKind.EVIDENCE,
            tuple(ContextObject(f"discovery:{i}", value) for i, value in enumerate(plan.optional))),
    ]


def test_read_replay_budget_defers_entire_discovery_group_without_losing_exact_read():
    from proxy.services.context_governor_service import (
        ContextCandidate, ContextKind, ContextObject, ContextRequiredSectionOverflow,
    )
    exact_body = "EXACT ALL RESOURCES; unit=m; per_unit=0.125; conditions=literal"
    chunks = [_read_replay_chunk("Q1.H1", exact_body, model_read_tool="read_norm_card")]
    chunks.extend(_read_replay_chunk(f"Q2.H{rank}", f"DISCOVERY-{rank}-START " + "x" * 6000 + f" END-{rank}",
                                    model_read_tool="search_sources", model_query_index=2,
                                    model_query_text="literal model query", model_raw_body_retained=True)
                  for rank in range(1, 7))
    original = copy.deepcopy(chunks)
    plan = _prepare_read_replay(chunks)
    governor, candidates = _read_replay_governor(plan, remaining_tokens=50)
    # The former all-body replay reproduces the required-frame overflow.
    with pytest.raises(ContextRequiredSectionOverflow):
        governor.pack([ContextCandidate(ContextKind.EVIDENCE,
            tuple(ContextObject(f"old:{i}", value) for i, value in enumerate(compact_read_replay(chunks))),
            required=True)])

    packet = governor.pack(candidates)

    assert packet.included_tokens <= packet.input_budget_tokens
    assert packet.omissions[0].object_ids == ("discovery:0",)
    assert plan.optional_body_refs == [[f"Q2.H{rank}" for rank in range(1, 7)]]
    text = "\n".join(message["content"] for message in packet.as_messages())
    assert exact_body in text
    for rank in range(1, 7):
        assert f"Q2.H{rank}" in text
        assert f"DISCOVERY-{rank}-START" not in text
        assert f"DISCOVERY-{rank}-START" in plan.optional[0]
        assert f"END-{rank}" in plan.optional[0]
    assert chunks == original


def test_read_replay_admits_all_bodies_of_a_fitting_group_and_no_partial_next_group():
    from proxy.services.context_governor_service import conservative_token_estimate
    chunks = [_read_replay_chunk("Q1.H1", "EXACT FULL BODY", model_read_tool="read_source")]
    chunks.extend(_read_replay_chunk(f"Q{query}.H{rank}", f"WHOLE-{query}-{rank} " + "x" * padding,
                                    model_read_tool="search_sources", model_query_index=query,
                                    model_query_text=f"literal query {query}", model_raw_body_retained=True)
                  for query, padding in ((2, 50), (3, 4000)) for rank in (1, 2))
    plan = _prepare_read_replay(chunks)
    governor, candidates = _read_replay_governor(plan,
        remaining_tokens=conservative_token_estimate(plan.optional[0]) + 1)

    packet = governor.pack(candidates)

    assert packet.omissions[0].object_ids == ("discovery:1",)
    admitted = {item.object_id for section in packet.sections for item in section.objects}
    assert "discovery:0" in admitted and "discovery:1" not in admitted
    assert plan.optional_body_refs == [["Q2.H1", "Q2.H2"], ["Q3.H1", "Q3.H2"]]
    text = "\n".join(message["content"] for message in packet.as_messages())
    assert "WHOLE-2-1" in text and "WHOLE-2-2" in text
    assert "WHOLE-3-1" not in text and "WHOLE-3-2" not in text


def test_read_replay_never_promotes_legacy_deferred_pointer_to_an_optional_body():
    pointer = json.dumps(["Q1.H1", "deferred_capacity", "literal-key", "literal-code", "title", "m", "source-id"])
    retained_body = "RAW NATIVE SEARCH BODY WITH LITERAL CONDITIONS"
    chunks = [_read_replay_chunk("Q1.H1", pointer, body_status="deferred_capacity", model_read_tool="search_sources"),
              _read_replay_chunk("Q2.H1", retained_body, body_status="deferred_capacity", model_read_tool="search_sources",
                                 model_raw_body_retained=True, model_delivery_status="prepared")]
    original = copy.deepcopy(chunks)

    plan = _prepare_read_replay(chunks)

    assert plan.exact_body_refs == []
    assert plan.required[1]["previously_shown_evidence_registry"] == []
    assert pointer in plan.required[2]
    assert retained_body not in json.dumps(plan.required)
    assert plan.optional_body_refs == [["Q2.H1"]]
    assert retained_body in plan.optional[0]
    assert chunks == original


def test_read_replay_resource_discovery_pointer_keeps_literal_code_and_pricebook_without_price_proof():
    resource = {"code": "literal-resource-code", "unit": "kg", "price_current": 123.45}
    content = json.dumps({"resource": resource, "pricebook": "literal-book"})
    chunk = {"doc_name": "fgis_pricebook_resources.v1", "content": content, "meta": {
        "resource_code": resource["code"], "pricebook": "literal-book", "pricebook_sha256": "a" * 64,
        "source_ref": "literal-pricebook-source", "source_sha256": "a" * 64,
        "model_evidence_ref": "Q4.H1", "global_evidence_id": "immutable-resource",
        "model_read_tool": "search_pricebook_resources", "body_status": "deferred_capacity",
        "model_raw_body_retained": True, "model_delivery_status": "prepared",
    }}
    original = copy.deepcopy(chunk)

    plan = _prepare_read_replay([chunk])

    assert plan.exact_body_refs == []
    assert plan.required[1]["previously_shown_evidence_registry"] == []
    pointer = json.loads(plan.required[2].splitlines()[-1])
    assert pointer[0:2] == ["Q4.H1", "deferred_capacity"]
    assert pointer[-1]["resource_code"] == resource["code"]
    assert pointer[-1]["pricebook"] == "literal-book"
    assert pointer[-1]["pricebook_sha256"] == "a" * 64
    assert "123.45" not in json.dumps(plan.required)
    assert plan.optional_body_refs == [["Q4.H1"]]
    assert content in plan.optional[0]
    assert chunk == original


def test_read_replay_required_legacy_pointer_does_not_claim_a_full_body():
    pointer = json.dumps(["Q1.H1", "deferred_capacity", "literal-key", "literal-code", "title", "m", "source-id"])
    chunk = _read_replay_chunk("Q1.H1", pointer, body_status="deferred_capacity",
                               model_delivery_status="prepared")
    original = copy.deepcopy(chunk)

    plan = _prepare_read_replay([chunk], required_refs=("immutable-Q1.H1",))

    assert plan.inventory_refs == ["Q1.H1"]
    assert plan.exact_body_refs == []
    assert plan.required[1]["previously_shown_evidence_registry"] == []
    assert pointer in plan.required[2]
    assert plan.optional == plan.optional_body_refs == []
    assert chunk == original


def test_read_replay_required_retained_body_uses_full_view_without_mutating_raw():
    content = "EXACT RETAINED BODY; all resources and literal applicability remain unchanged " + "x" * 6000
    chunk = _read_replay_chunk("Q1.H1", content, body_status="deferred_capacity",
                               model_delivery_status="prepared", model_raw_body_retained=True)
    original = copy.deepcopy(chunk)

    plan = _prepare_read_replay([chunk], required_refs=("immutable-Q1.H1",))

    assert plan.inventory_refs == plan.exact_body_refs == ["Q1.H1"]
    row, = plan.required[1]["previously_shown_evidence_registry"]
    assert row["content"].encode("utf-8") == content.encode("utf-8")
    assert row["global_evidence_id"] == original["meta"]["global_evidence_id"]
    assert row["source_sha256"] == original["meta"]["source_sha256"]
    assert plan.optional == plan.optional_body_refs == []
    assert chunk == original
