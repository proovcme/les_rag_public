"""A model selects a shown resource address; code only dereferences that choice."""

import copy
import json
from types import SimpleNamespace

import pytest

from proxy.services.chat_evidence_application_service import bind_row_evidence_ids
from proxy.services.model_resource_binding_service import resource_binding_position_fields
from proxy.services.model_research_tool_service import _full_norm_card_content


CODE = "ГЭСН01-02-003-04"
RESOURCE = {"kind": "material", "code": "A-1", "name": "Exact long resource name",
            "unit": "m", "per_unit": 12, "price": None}


def _card(identity="immutable-1", alias="Q1.H1", **extra):
    resource = {**RESOURCE, "resource_slot": 1}
    return SimpleNamespace(content=f"Norm: {CODE}\n" + json.dumps(resource, ensure_ascii=False, sort_keys=True),
        doc_name="smeta_norm_cards.v1", meta={"norm_code": CODE, "global_evidence_id": identity,
        "model_evidence_ref": alias, "exact_card_read": True, "resources": [resource], **extra})


def _row(**action):
    return {"source_row": "S!R2", "norm_code": CODE, "evidence_refs": ["Q1.H1"],
        "resource_bindings": [{"action": "reuse", "target_resource_ref": "Q1.H1#resource=1",
                              "reason": "Reuse from the original source", "basis_ref": "S!R2", **action}]}


def _apply(row, cards):
    bound = bind_row_evidence_ids([row], cards)[0]
    return bound, resource_binding_position_fields(bound, [RESOURCE], work_id="operation-1",
        work_qty=2, physical_quantity=2, physical_unit="m")


def test_full_card_exposes_resource_slots_without_changing_source_records():
    card = {"norm_code": CODE, "resources": [RESOURCE], "resources_complete": True}
    before = copy.deepcopy(card)
    assert '"resource_slot": 1' in _full_norm_card_content(card)
    assert card == before


def test_address_applies_exact_resource_and_retains_the_literal_authored_choice():
    row = _row()
    bound, result = _apply(row, [_card()])
    assert result["resource_binding_conflicts"] == []
    assert result["resource_bindings"] == row["resource_bindings"]
    assert result["resources"][0]["code"] == RESOURCE["code"]
    assert result["resources"][0]["price"] == 0
    assert result["resource_binding_audit"][0]["provenance"]["target_resource_ref"] == "Q1.H1#resource=1"
    assert bound["_resource_binding_evidence_bindings"]["0"] == {"Q1.H1": "immutable-1"}


@pytest.mark.parametrize("change", [
    {"target_resource_ref": "Q1.H1#resource=2"},
    {"target_resource_ref": "Q1.H1#resource=0"},
    {"target_resource_ref": "Q1.H2#resource=1"},
    {"target_resource_code": "different-code"},
    {"target_resource_name": "Generic shortened name"},
    {"basis_ref": "OTHER!R99"},
])
def test_invalid_address_or_disagreeing_authored_fields_never_changes_resources(change):
    _, result = _apply(_row(**change), [_card()])
    assert result["resources"] == [RESOURCE]
    assert result["resource_binding_conflicts"]


@pytest.mark.parametrize("extra", [
    {"body_status": "deferred_capacity"},
    {"model_delivery_status": "prepared", "model_inventory_delivery_status": "delivered"},
    {"norm_code": "ANOTHER-NORM"},
    {"exact_card_read": False},
])
def test_inventory_metadata_or_other_norm_cannot_be_dereferenced(extra):
    _, result = _apply(_row(), [_card(**extra)])
    assert result["resources"] == [RESOURCE]
    assert result["resource_binding_conflicts"]


def test_metadata_without_literal_slot_body_does_not_substantiate_address():
    card = _card()
    card.content = "Resource summary without the selected consumption record"
    _, result = _apply(_row(), [card])
    assert result["resources"] == [RESOURCE]
    assert result["resource_binding_conflicts"]


def test_durable_pointer_uses_original_card_across_packet_alias_collision():
    bound, _ = _apply(_row(), [_card()])
    rebound, result = _apply(bound, [_card("another-card"), _card("immutable-1", "Q9.H9")])
    assert result["resource_binding_conflicts"] == []
    assert rebound["_resource_binding_evidence_bindings"]["0"] == {"Q1.H1": "immutable-1"}


def test_unbound_ambiguous_alias_cannot_select_first_packet_card():
    _, result = _apply(_row(), [_card(), _card("another-card")])
    assert result["resources"] == [RESOURCE]
    assert result["resource_binding_conflicts"]


def test_referenced_source_resource_must_still_match_calculator_consumption():
    bound = bind_row_evidence_ids([_row()], [_card()])[0]
    different = {**RESOURCE, "per_unit": 99}
    result = resource_binding_position_fields(bound, [different], work_id="W", work_qty=1,
        physical_quantity=1, physical_unit="m")
    assert result["resources"] == [different]
    assert result["resource_binding_conflicts"]
