"""Compact resource transport must prove every literal value without rewriting cards."""
from __future__ import annotations

import copy
import json
from decimal import Decimal

import pytest

from proxy.services.model_research_tool_service import _full_norm_card_content
from proxy.services.model_resource_reference_service import resource_slot_records, shown_resource_record
from proxy.services.model_rag_grouped_evidence_service import share_registry_catalogs
from proxy.services.model_resource_literal_service import restore_resource_table


MARKER = "literal_resources_v1="


def _resources(count=24):
    return [{"kind": "material", "code": f"11.1.{index:04}",
             "name": 'Literal Ω resource "quoted"\nsecond line\u2028paragraph\u2029separator', "unit": "m²",
             "per_unit": (0 if index == 0 else 0.0 if index == 1 else index / 10),
             "price": None, "source_ref": f"original-document#guid=immutable-{index}"}
            for index in range(count)]


def _literal(rows):
    return "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) for row in rows)


def test_full_resource_table_is_smaller_and_reconstructs_all_types_slots_and_provenance():
    card = {"resources": _resources(), "resources_complete": True}
    card["resources"][0]["price"] = 0
    card["resources"][1]["price"] = 0.0
    before = copy.deepcopy(card)
    body = _full_norm_card_content(card)
    table_line, = [line for line in body.split("\n") if line.startswith(MARKER)]
    table = json.loads(table_line[len(MARKER):])
    rows = resource_slot_records(card)
    recovered = [dict(zip(table["columns"], values, strict=True)) for values in table["records"]]
    assert _literal(recovered) == _literal(rows)
    assert len(table_line.encode("utf-8")) < len(_literal(rows).encode("utf-8")) * .70
    assert len(table_line) < len(_literal(rows)) * .70
    meta = {"exact_card_read": True, "resources": rows}
    for slot, original in enumerate(card["resources"], 1):
        shown = shown_resource_record(meta, body, slot)
        assert _literal([shown]) == _literal([original])
        assert list(shown) == list(original)
        assert type(shown["per_unit"]) is type(original["per_unit"])
        assert type(shown["price"]) is type(original["price"])
    assert card == before


@pytest.mark.parametrize("alter", [
    lambda rows: rows[0].update(unknown_field="keep this exact field"),
    lambda rows: rows[0].pop("price"),
    lambda rows: rows[0].update(per_unit=Decimal("0.125")),
    lambda rows: rows[0].update(per_unit=float("nan")),
    lambda rows: rows[0].update(name={"literal": "nested unusual source value"}),
])
def test_nonstandard_or_heterogeneous_resources_keep_original_full_jsonl(alter):
    card = {"resources": _resources(), "resources_complete": True}
    alter(card["resources"])
    rows = resource_slot_records(card)
    body = _full_norm_card_content(card)
    assert MARKER not in body
    assert _literal(rows) in body


@pytest.mark.parametrize("change", ["value", "type", "order", "omit", "duplicate_column", "extra_field", "duplicate_table"])
def test_table_proof_rejects_any_nonexact_full_list(change):
    card = {"resources": _resources()}
    body = _full_norm_card_content(card)
    line, = [item for item in body.split("\n") if item.startswith(MARKER)]
    table = json.loads(line[len(MARKER):])
    if change == "value":
        table["records"][-1][table["columns"].index("source_ref")] = "another-source"
    elif change == "type":
        table["records"][0][table["columns"].index("per_unit")] = 0.0
    elif change == "order":
        table["records"] = list(reversed(table["records"]))
    elif change == "omit":
        table["records"].pop()
    elif change == "duplicate_column":
        table["columns"][-1] = table["columns"][0]
    elif change == "extra_field":
        table["unknown"] = "not part of the representation"
    changed = MARKER + json.dumps(table, ensure_ascii=False, separators=(",", ":"))
    if change == "duplicate_table":
        changed += "\n" + changed
    assert shown_resource_record({"exact_card_read": True, "resources": resource_slot_records(card)},
                                 body.replace(line, changed), 1) is None


def test_immutable_legacy_evidence_and_small_cards_keep_exact_original_proof():
    card = {"resources": _resources(1)}
    rows = resource_slot_records(card)
    meta = {"exact_card_read": True, "resources": rows}
    legacy = "unchanged old evidence\n" + _literal(rows)
    assert shown_resource_record(meta, legacy, 1) == card["resources"][0]
    assert MARKER not in _full_norm_card_content(card)
    assert meta["resources"] == rows and legacy.startswith("unchanged old evidence")


@pytest.mark.parametrize("reuse_source", [True, False])
def test_table_catalog_view_restores_every_source_and_improves_existing_replay(reuse_source):
    resources = _resources()
    source = "whole immutable provenance Ω\u2028" * 40
    for index, row in enumerate(resources):
        row["source_ref"] = source if reuse_source else source + str(index)
    card = {"resources": resources, "resources_complete": True}
    rows = resource_slot_records(card)
    meta = {"exact_card_read": True, "resources": rows}
    before = copy.deepcopy(meta)
    table = _full_norm_card_content(card)
    line, = [line for line in table.split("\n") if line.startswith(MARKER)]
    legacy = table.replace(line, _literal(rows))
    # A source already present in the index catalog must retain that saving.
    from proxy.services.model_rag_grouped_evidence_service import _source_id
    existing = {_source_id(row["source_ref"]): row["source_ref"] for row in rows}
    old = share_registry_catalogs([{"evidence_ref": "Q1.H1", "content": legacy}],
                                 {"Q1.H1": meta}, source_catalog=existing)
    new = share_registry_catalogs([{"evidence_ref": "Q1.H1", "content": table}],
                                 {"Q1.H1": meta}, source_catalog=existing)
    assert len(json.dumps(new, ensure_ascii=False).encode("utf-8")) < len(json.dumps(old, ensure_ascii=False).encode("utf-8"))
    catalogs, views = new
    assert "shared_source_pointer" in views[0]["content"]
    assert restore_resource_table(views[0]["content"], rows) is None
    restored = restore_resource_table(views[0]["content"], rows, source_catalog=catalogs["literal_source_catalog"])
    assert _literal(restored) == _literal(rows)
    assert shown_resource_record(meta, views[0]["content"], 1,
        source_catalog=catalogs["literal_source_catalog"]) == resources[0]
    bad_catalog = {**catalogs["literal_source_catalog"], _source_id(source): "different literal"}
    if reuse_source:
        assert shown_resource_record(meta, views[0]["content"], 1, source_catalog=bad_catalog) is None
    assert meta == before


def test_unknown_table_serialization_is_not_catalog_rewritten():
    from proxy.services.model_rag_grouped_evidence_service import _share_resource_source_refs
    card = {"resources": _resources()}
    rows = resource_slot_records(card)
    body = _full_norm_card_content(card)
    line, = [item for item in body.split("\n") if item.startswith(MARKER)]
    unknown = body.replace(line, MARKER + json.dumps(json.loads(line[len(MARKER):]), ensure_ascii=False))
    sources = {}
    assert _share_resource_source_refs(unknown, {"resources": rows, "exact_card_read": True}, sources) == unknown
    assert sources == {}


def test_catalog_factors_only_the_producer_table_line_and_keeps_identical_inline_source_text():
    from proxy.services.model_rag_grouped_evidence_service import _share_resource_source_refs
    card = {"resources": _resources()}
    for row in card["resources"]:
        row["source_ref"] = "immutable whole resource source " * 40
    rows = resource_slot_records(card)
    body = _full_norm_card_content(card)
    line, = [item for item in body.split("\n") if item.startswith(MARKER)]
    source_sentence = "Source-owned sentence containing " + line + "\n"
    sources = {}
    projected = _share_resource_source_refs(source_sentence + body,
        {"resources": rows, "exact_card_read": True}, sources)
    assert projected.startswith(source_sentence)
    assert "shared_source_pointer" in projected[len(source_sentence):]
    assert _literal(restore_resource_table(projected, rows, source_catalog=sources)) == _literal(rows)
