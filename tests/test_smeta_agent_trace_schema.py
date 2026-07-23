import copy
import json
from pathlib import Path

import jsonschema
import pytest


SCHEMA_PATH = Path("schema/smeta_agent_trace.schema.json")


def _schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _payload():
    return {
        "schema": "smeta_agent_trace_v1",
        "mode": "estimate",
        "mapping_status": "mapping_selected",
        "pricing_status": "priced_draft",
        "object_context": {
            "object_id": "object-1",
            "region": "region",
            "period": "2026-Q2",
            "stage": "RD",
            "construction_conditions": [],
            "source_refs": ["source.pdf"],
        },
        "work_contexts": [{
            "scope_id": "scope-1",
            "source_row_ids": ["row-1"],
            "operation_ids": ["op-1"],
            "candidate_ids": ["pos-1"],
            "source_refs": ["source.pdf#row=1"],
            "candidate_cards_released": True,
            "compact_carry_forward": {
                "object_context_ref": "object-1",
                "coverage_decisions": [],
                "source_refs": ["source.pdf#row=1"],
            },
        }],
        "source_rows": [{
            "source_row_id": "row-1",
            "title": "Operation",
            "unit": "m",
            "quantity": 10,
            "quantity_origin": "source_explicit",
            "quantity_formula": None,
            "quantity_evidence_refs": ["source.pdf#row=1"],
            "blocks_priced_final": False,
        }],
        "operations": [{
            "operation_id": "op-1",
            "source_row_ids": ["row-1"],
            "title": "Install",
            "conditions": [],
        }],
        "estimate_positions": [{
            "estimate_position_id": "pos-1",
            "operation_ids": ["op-1"],
            "pricing_basis": "norm",
            "relationship_type": "alternative",
            "applicability_status": "exact",
            "decision": "selected",
            "resolution_status": "priced",
            "review_level": "full",
            "full_review_triggers": ["selected"],
            "triage": {
                "operation_match": "yes",
                "measure_match": "yes",
                "obvious_conflict": False,
                "reason": "matched",
            },
            "full_applicability": {
                "source_operation": "ok",
                "norm_domain": "ok",
                "purpose_technology": "ok",
                "measure": "ok",
                "quantity_conversion": "ok",
                "work_steps": "ok",
                "resource_composition": "ok",
                "technical_conditions": "ok",
                "coverage_exclusions": "ok",
                "analogue_risk_decision": "selected",
            },
            "norm_code": "GESN-1",
            "resources": [{
                "resource_id": "machinist-1",
                "kind": "machinist_labor",
                "quantity": 2,
                "unit": "h",
                "machine_resource_code": "machine-1",
                "machinist_resource_code": "worker-4",
                "machine_hours": 2,
                "machinist_labor_per_machine_hour": 1,
                "machinist_hours": 2,
                "price": {
                    "value": None,
                    "source_ref": None,
                    "zero_reason": None,
                    "status": "missing",
                    "application": "not_applied",
                },
            }],
            "price": {
                "value": 100,
                "source_ref": "pricebook#1",
                "zero_reason": None,
                "status": "confirmed",
                "application": "main",
            },
            "pricing_evidence": ["pricebook#1"],
            "source_refs": ["norm#GESN-1"],
        }],
        "coefficients": [{
            "coefficient_id": "coef-1",
            "value": 1.1,
            "status": "missing_evidence",
            "source_ref": None,
            "scope": ["worker_labor"],
            "already_in_source_quantity": False,
            "application": "variant_only",
            "variant_impact": 10,
        }],
        "planning_output": {
            "mapping": {},
        },
        "execution_result": {
            "lsr_xlsx": "result.xlsx",
            "trace": {},
            "open_register": [],
        },
    }


def test_smeta_agent_trace_schema_accepts_full_review_and_null_missing_price():
    jsonschema.validate(_payload(), _schema())


def test_candidate_review_does_not_require_execution_result_or_xlsx():
    payload = _payload()
    payload["mode"] = "candidate_review"
    payload["pricing_status"] = "unpriced"
    del payload["execution_result"]

    jsonschema.validate(payload, _schema())


def test_estimate_requires_lsr_execution_artifact():
    payload = _payload()
    del payload["execution_result"]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())


def test_uploaded_mapping_without_status_is_not_silently_locked():
    payload = _payload()
    payload["mode"] = "continue_reviewed"
    del payload["mapping_status"]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())


def test_continue_reviewed_requires_locked_mapping():
    payload = _payload()
    payload["mode"] = "continue_reviewed"
    payload["mapping_status"] = "mapping_user_reviewed"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())

    payload["mapping_status"] = "mapping_locked"
    jsonschema.validate(payload, _schema())


def test_inferred_quantity_blocks_priced_final():
    payload = _payload()
    row = payload["source_rows"][0]
    row["quantity_origin"] = "inferred"
    row["blocks_priced_final"] = False

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())

    row["blocks_priced_final"] = True
    payload["pricing_status"] = "priced_final"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())


def test_zero_price_requires_actual_covered_or_excluded_reason():
    payload = _payload()
    price = payload["estimate_positions"][0]["price"]
    price["value"] = 0
    price["zero_reason"] = None

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())

    price["zero_reason"] = "covered"
    price["status"] = "actual_zero"
    jsonschema.validate(payload, _schema())

    price["value"] = None
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())

    price["zero_reason"] = None
    price["status"] = "missing"
    price["application"] = "not_applied"
    jsonschema.validate(payload, _schema())


def test_missing_evidence_coefficient_cannot_enter_main_calculation():
    payload = copy.deepcopy(_payload())
    payload["coefficients"][0]["application"] = "main"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())


def test_full_review_requires_ten_point_applicability():
    payload = _payload()
    del payload["estimate_positions"][0]["full_applicability"]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())


def test_selected_candidate_cannot_stay_triage_only():
    payload = _payload()
    position = payload["estimate_positions"][0]
    position["review_level"] = "triage"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())


def test_resolution_status_is_separate_from_pricing_basis_and_evidence():
    payload = _payload()
    position = payload["estimate_positions"][0]
    position["resolution_status"] = "covered_by"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())

    position["pricing_basis"] = None
    position["pricing_evidence"] = []
    position["price"] = {
        "value": 0,
        "source_ref": "coverage#decision",
        "zero_reason": "covered",
        "status": "actual_zero",
        "application": "main",
    }
    jsonschema.validate(payload, _schema())


def test_work_context_requires_released_cards_and_compact_carry_forward():
    payload = _payload()
    del payload["work_contexts"][0]["compact_carry_forward"]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema())
