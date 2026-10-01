"""Terminal resource actions preserve exact targets, quantity bases and failures."""

import copy

import pytest

from proxy.services.model_resource_binding_service import resource_binding_position_fields


BASE = [
    {"kind": "material", "code": "A-1", "name": "Target material", "unit": "t", "per_unit": 0.5, "price": 77},
    {"kind": "material", "code": "A-10", "name": "Other material", "unit": "m", "per_unit": 3},
    {"kind": "labor", "code": "L-1", "name": "Labor", "unit": "h", "per_unit": 4},
]


def _action(action="exclude", **changes):
    return {"action": action, "target_resource_code": "A-1", "reason": "Authored reason",
            "basis_ref": "S!R2", "source_refs": ["Q1.H1"], **changes}


def _apply(actions, *, resources=BASE, linked_supply_rows=(), supply_parent_ambiguous=False, **row_fields):
    if isinstance(actions, list) and "_resource_binding_evidence_checks" not in row_fields:
        row_fields["_resource_binding_evidence_checks"] = [{
            "index": index, "target_code_in_refs": True, "target_name_in_refs": True,
            "resource_code_in_refs": True, "price_in_refs": True, "unit_in_refs": True, "source_in_refs": True,
        } for index, _ in enumerate(actions)]
    row = {"source_row": "S!R2", "resource_bindings": actions, **row_fields}
    return resource_binding_position_fields(row, resources, work_id="operation-1", work_qty=10,
                                            physical_quantity=1000, physical_unit="m", linked_supply_rows=linked_supply_rows,
                                            supply_parent_ambiguous=supply_parent_ambiguous)


def test_absent_contract_does_not_change_existing_default_or_require_review():
    assert resource_binding_position_fields({}, BASE, work_id="W", work_qty=10,
                                            physical_quantity=None, physical_unit="") == {}


def test_direct_reference_names_without_evidence_checks_cannot_certify_an_action():
    result = _apply([_action()], _resource_binding_evidence_checks=None)
    assert result["resource_binding_audit"][0]["status"] == "applied"
    assert result["resource_binding_audit"][0]["evidence_status"] == "unverified"
    assert result["resource_binding_conflicts"][0]["code"] == "resource_binding_evidence_unverified"


def test_basis_ref_cannot_invent_a_different_original_source():
    result = _apply([_action("reuse", basis_ref="OTHER!R99")])
    assert result["resources"] == BASE
    assert result["resource_binding_conflicts"]


def test_exact_exclusion_preserves_other_resources_and_raw_decision():
    action = _action()
    original = copy.deepcopy((action, BASE))
    result = _apply([action])
    assert [resource["code"] for resource in result["resources"]] == ["A-10", "L-1"]
    assert result["resource_bindings"] == [action]
    assert result["resource_binding_audit"][0]["target"] == BASE[0]
    assert result["resource_binding_audit"][0]["status"] == "applied"
    assert result["resource_binding_conflicts"] == []
    assert (action, BASE) == original


def test_excluding_only_resource_keeps_explicit_empty_resources():
    assert _apply([_action()], resources=BASE[:1])["resources"] == []


def test_reuse_preserves_exact_unit_consumption_and_actual_source():
    result = _apply([_action("reuse")])
    reused = result["resources"][-1]
    assert {key: reused[key] for key in ("code", "name", "unit", "per_unit")} == {
        key: BASE[0][key] for key in ("code", "name", "unit", "per_unit")}
    assert reused["price"] == 0
    assert reused["price_source_ref"] == "S!R2"
    assert reused["resource_binding"]["selected_by"] == "model"
    assert reused["resource_binding"]["work_id"] == "operation-1"


def test_explicit_reuse_zero_uses_the_reuse_basis_without_inventing_a_market_quote():
    result = _apply([_action("reuse", explicit_price=0)], _resource_binding_evidence_checks=[{
        "index": 0, "target_code_in_refs": True, "price_in_refs": False,
        "unit_in_refs": False, "source_in_refs": False}])
    assert result["resource_binding_conflicts"] == []
    assert result["resources"][-1]["price"] == 0
    assert result["resources"][-1]["price_source_ref"] == "S!R2"
    assert result["resource_bindings"][0]["explicit_price"] == 0


def test_reuse_cannot_claim_an_operator_price_source_from_a_model_token():
    result = _apply([_action("reuse", explicit_price=0, price_source_ref="operator")],
                    _resource_binding_evidence_checks=[{"index": 0, "target_code_in_refs": True, "source_in_refs": False}])
    assert result["resources"] == BASE
    assert result["resource_binding_conflicts"]


@pytest.mark.parametrize("target", ["", "A", "A-11", "missing"])
def test_missing_or_partial_target_is_a_visible_conflict_without_mutation(target):
    result = _apply([_action(target_resource_code=target)])
    assert result["resources"] == BASE
    assert result["resource_binding_audit"][0]["status"] == "conflict"
    assert result["resource_binding_conflicts"][0]["proposal"]["target_resource_code"] == target


def test_ambiguous_target_and_disagreeing_full_name_cannot_remove_resources():
    for resources, extra in [(BASE + [BASE[0]], {}), (BASE, {"target_resource_name": "Other material"})]:
        result = _apply([_action(**extra)], resources=resources)
        assert result["resources"] == resources
        assert result["resource_binding_conflicts"]


def test_name_only_target_requires_the_complete_name():
    result = _apply([_action(target_resource_code="", target_resource_name="Target material")])
    assert [item["code"] for item in result["resources"]] == ["A-10", "L-1"]
    rejected = _apply([_action(target_resource_code="", target_resource_name="Target")])
    assert rejected["resources"] == BASE
    assert rejected["resource_binding_conflicts"]


@pytest.mark.parametrize("quantity", [0, -1, True, float("nan"), float("inf"), "bad", None])
def test_invalid_replacement_is_atomic(quantity):
    result = _apply([_action("replace", resource_name="New material", unit="kg", quantity=quantity)])
    assert result["resources"] == BASE
    assert result["resource_binding_conflicts"]


@pytest.mark.parametrize("extra", [{"selected_by": "user"}, {"work_id": "other"}, {"kind": "labor"},
                                  {"reason": ""}, {"basis_ref": "", "source_refs": []}, {"source_refs": "Q1.H1"}])
def test_owner_kind_and_malformed_provenance_are_not_silently_accepted(extra):
    result = _apply([_action(**extra)])
    assert result["resources"] == BASE
    assert result["resource_binding_conflicts"]


@pytest.mark.parametrize("payload", [None, {}, "exclude", [None], ["exclude"]])
def test_wrong_container_is_preserved_as_a_visible_proposal(payload):
    result = _apply(payload)
    assert result["resource_bindings"] == payload
    assert result["resources"] == BASE
    assert result["resource_binding_conflicts"]


def test_explicit_and_source_work_quantities_normalize_against_norm_quantity_once():
    for basis, quantity in [("explicit", 250), ("source_work", None)]:
        action = {"action": "add", "resource_name": "New material", "unit": "m", "quantity_basis": basis,
                  "reason": "Model quantity basis", "basis_ref": "S!R2"}
        if quantity is not None:
            action["quantity"] = quantity
        result = _apply([action])
        added = result["resources"][-1]
        assert added["per_unit"] == (25 if basis == "explicit" else 100)
        assert added["resource_binding"]["physical_quantity"] == (250 if basis == "explicit" else 1000)


def test_target_norm_replacement_converts_physical_consumption_and_keeps_target_audit():
    result = _apply([_action("replace", resource_name="Replacement", unit="kg", quantity_basis="target_norm")])
    assert result["resources"][-1]["per_unit"] == 500
    assert result["resources"][-1]["resource_binding"]["physical_quantity"] == 5000
    assert result["resource_binding_audit"][0]["target"]["unit"] == "t"
    mismatch = _apply([_action("replace", resource_name="Replacement", unit="m", quantity_basis="target_norm")])
    assert mismatch["resources"] == BASE
    assert mismatch["resource_binding_conflicts"]


def test_positive_addition_cannot_be_normalized_against_zero_work_quantity():
    row = {"source_row": "S!R2", "resource_bindings": [{"action": "add", "resource_name": "Material",
           "unit": "m", "quantity": 1, "reason": "Authored quantity", "basis_ref": "S!R2"}],
           "_resource_binding_evidence_checks": [{"index": 0}]}
    result = resource_binding_position_fields(row, BASE, work_id="op-zero", work_qty=0,
                                             physical_quantity=0, physical_unit="m")
    assert result["resources"] == BASE
    assert result["resource_binding_conflicts"]


def test_reuse_on_zero_work_quantity_preserves_exact_consumption_without_division():
    row = {"source_row": "S!R2", "resource_bindings": [_action("reuse")],
           "_resource_binding_evidence_checks": [{"index": 0, "target_code_in_refs": True}]}
    result = resource_binding_position_fields(row, BASE, work_id="op-zero", work_qty=0,
                                             physical_quantity=0, physical_unit="m")
    assert result["resources"][-1]["per_unit"] == 0.5
    assert result["resources"][-1]["unit"] == "t"
    assert result["resources"][-1]["price"] == 0
    assert result["resource_binding_conflicts"] == []


def test_replacement_cannot_convert_labor_to_material():
    result = _apply([_action("replace", target_resource_code="L-1", resource_name="Material", unit="kg", quantity=1)])
    assert result["resources"] == BASE
    assert result["resource_binding_conflicts"]


def test_nested_evidence_checks_reject_false_or_unresolved_and_preserve_global_identity():
    for check in [{"index": 0, "target_code_in_refs": False},
                  {"index": 0, "target_code_in_refs": True, "unresolved_refs": ["Q1.H1"]}]:
        result = _apply([_action()], _resource_binding_evidence_checks=[check])
        assert result["resources"] == BASE
        assert result["resource_binding_conflicts"]
    result = _apply([_action()], _resource_binding_evidence_checks=[{
        "index": 0, "target_code_in_refs": True, "evidence_bindings": {"Q1.H1": "immutable-target"}}])
    assert result["resource_binding_audit"][0]["provenance"]["evidence_bindings"] == {"Q1.H1": "immutable-target"}


@pytest.mark.parametrize("price", [-1, True, float("nan"), float("inf")])
def test_invalid_explicit_price_cannot_remove_a_replacement_target(price):
    result = _apply([_action("replace", resource_name="Replacement", unit="kg", quantity=1,
                            explicit_price=price, price_source_ref="Q2.H1")])
    assert result["resources"] == BASE
    assert result["resource_binding_conflicts"]


def test_explicit_price_requires_same_body_checks_and_reuse_does_not_need_a_price_quote():
    action = _action("replace", resource_name="Replacement", resource_code="B", unit="kg", quantity=1,
                     explicit_price=12, price_source_ref="Q2.H1")
    check = {"index": 0, "target_code_in_refs": True, "resource_code_in_refs": True,
             "price_in_refs": True, "unit_in_refs": True, "source_in_refs": False}
    result = _apply([action], _resource_binding_evidence_checks=[check])
    assert result["resources"] == BASE
    assert result["resource_binding_conflicts"]
    contradictory_reuse = _apply([_action("reuse", explicit_price=12, price_source_ref="Q2.H1")])
    assert contradictory_reuse["resources"] == BASE
    assert contradictory_reuse["resource_binding_conflicts"]


def test_review_is_optional_typed_reporting_and_does_not_remove_components():
    review = {"status": "keep_all_confirmed", "reason": "Authored review",
              "material_status": "rejected", "material_reason": "Model states a conflict"}
    result = _apply([], resource_review=review)
    assert result["resources"] == BASE
    assert result["resource_review"] == review
    assert result["material_review_status"] == "rejected"
    assert result["resource_binding_conflicts"] == []
    invalid = _apply([_action()], resource_review=review)
    assert invalid["resource_review"] == review
    assert invalid["resource_binding_conflicts"][-1]["code"] == "resource_review_conflict"


def test_optional_review_does_not_invent_omitted_component_statuses():
    result = _apply([], resource_review={"status": "keep_all_confirmed", "reason": "Authored review"})
    assert result["resource_review_status"] == "keep_all_confirmed"
    assert not any(f"{component}_review_status" in result for component in ("labor", "machine", "material", "dominant"))


def test_malformed_internal_evidence_index_is_unverified_instead_of_crashing():
    result = _apply([_action()], _resource_binding_evidence_checks=[{"index": [], "target_code_in_refs": True}])
    assert result["resource_binding_conflicts"][0]["code"] == "resource_binding_evidence_unverified"


SUPPLY = {"source_row": "S!R3", "resource_code": "A-1"}


def test_linked_supply_without_actions_preserves_full_card_and_exposes_possible_overlap():
    result = resource_binding_position_fields({"source_row": "S!R2"}, BASE, work_id="W", work_qty=10,
                                            physical_quantity=1000, physical_unit="m", linked_supply_rows=[SUPPLY])
    assert "resources" not in result
    conflict = result["resource_binding_conflicts"][0]
    assert conflict["code"] == "separate_supply_possible_overlap"
    assert conflict["norm_material_resources"] == BASE[:2]
    assert conflict["linked_supply_rows"] == [SUPPLY]


def test_only_explicit_exact_exclusion_on_actual_linked_source_resolves_overlap():
    result = _apply([_action(basis_ref="S!R3")], linked_supply_rows=[SUPPLY])
    assert result["resource_binding_conflicts"] == []
    assert result["resources"] == BASE[1:]
    assert result["resource_binding_audit"][0]["provenance"]["basis_ref"] == "S!R3"


@pytest.mark.parametrize("supply,action", [
    ({"source_row": "S!R3", "resource_code": "A-10"}, _action(basis_ref="S!R3")),
    ({"source_row": "S!R3", "resource_code": "a-1"}, _action(basis_ref="S!R3")),
    ({"source_row": "S!R3", "resource_code": ""}, _action(basis_ref="S!R3")),
    (SUPPLY, _action(basis_ref="S!R2")),
    (SUPPLY, _action(basis_ref="S!R3", target_resource_code="a-1")),
])
def test_nonliteral_or_unrelated_exclusion_does_not_claim_supply_resolved(supply, action):
    result = _apply([action], linked_supply_rows=[supply])
    assert result["resource_binding_audit"][0]["status"] == "applied"
    assert result["resource_binding_conflicts"][-1]["code"] == "separate_supply_possible_overlap"


@pytest.mark.parametrize("action", [
    _action("replace", basis_ref="S!R3", resource_name="Replacement", resource_code="A-1", unit="t", quantity=2),
    _action("reuse", basis_ref="S!R3", explicit_price=0),
])
def test_replacement_or_reuse_does_not_remove_standalone_supply_double_charge_ambiguity(action):
    result = _apply([action], linked_supply_rows=[SUPPLY])
    assert result["resource_binding_audit"][0]["status"] == "applied"
    assert result["resource_binding_conflicts"][-1]["code"] == "separate_supply_possible_overlap"


def test_multiple_parent_operations_and_unresolved_second_supply_remain_visible():
    for supplies, ambiguous in [([SUPPLY], True), ([SUPPLY, {"source_row": "S!R4", "resource_code": "A-10"}], False)]:
        result = _apply([_action(basis_ref="S!R3")], linked_supply_rows=supplies, supply_parent_ambiguous=ambiguous)
        conflict = result["resource_binding_conflicts"][-1]
        assert conflict["code"] == "separate_supply_possible_overlap"
        assert conflict["parent_ambiguous"] is ambiguous
        assert result["resources"] == BASE[1:]


def test_model_cannot_supply_internal_linked_rows_to_invent_a_source_basis():
    result = _apply([_action(basis_ref="S!R3")], _linked_supply_rows=[SUPPLY])
    assert result["resources"] == BASE
    assert result["resource_binding_conflicts"][0]["code"] == "resource_binding_conflict"


def test_exclusion_followed_by_same_code_addition_does_not_hide_possible_double_charge():
    result = _apply([_action(basis_ref="S!R3"),
                     _action("add", basis_ref="S!R3", resource_name="Authored addition", resource_code="A-1", unit="t", quantity=2)],
                    linked_supply_rows=[SUPPLY])
    assert all(entry["status"] == "applied" for entry in result["resource_binding_audit"])
    assert result["resources"][-1]["code"] == "A-1"
    assert result["resource_binding_conflicts"][-1]["code"] == "separate_supply_possible_overlap"
