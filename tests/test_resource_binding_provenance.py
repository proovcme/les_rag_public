"""Only the literally shown typed resource can substantiate a model selection."""

from types import SimpleNamespace

import pytest

from proxy.services.chat_evidence_application_service import bind_row_evidence_ids
from proxy.services.rim_lsr_trace_service import build_lsr_trace_from_visible_rows


SELECTED = "20.4.01.01-0001"
OTHER = "20.4.01.01-0002"


def _row(**extra):
    return {"source_row": "S!R2", "row_role": "material", "title": "Authored supply", "unit": "m",
            "quantity": 3, "resource_code": SELECTED, "evidence_refs": ["Q1.H1"], **extra}


def _card(body, **meta):
    return SimpleNamespace(content=body, doc_name="Synthetic typed resource",
                           meta={"model_evidence_ref": "Q1.H1", "global_evidence_id": "immutable-card", **meta})


class Book:
    def lookup(self, code):
        return {"price_current": 100, "unit": "m"} if code == SELECTED else None


@pytest.mark.parametrize("card", [
    _card(f"Resource: {OTHER}", resource_code=OTHER),
    _card("Displayed header without the omitted resource tail", resources=[{"code": SELECTED}]),
    _card(f"Resource: {SELECTED}-suffix", resource_code=SELECTED),
])
def test_wrong_or_undisplayed_typed_resource_cannot_confirm_the_chosen_book_amount(card):
    bound = bind_row_evidence_ids([_row()], [card])
    assert bound[0]["evidence_bindings"] == {"Q1.H1": "immutable-card"}
    assert bound[0]["_resource_evidence_check"]["code_in_refs"] is False
    trace = build_lsr_trace_from_visible_rows(bound, pricebook=Book())
    summary = trace["sections"][0]["positions"][0]["summary"]
    assert summary["known_amount"] == 300
    assert summary["full_amount"] is None
    assert "resource_selection_unsubstantiated" in summary["completeness_reasons"]
    assert trace["row_bindings"][0]["position"]["resources"][0]["code"] == SELECTED


def test_forged_global_binding_is_preserved_without_creating_resource_proof():
    authored = _row(evidence_bindings={"Q1.H1": "unknown-global-identity"})
    bound = bind_row_evidence_ids([authored], [_card(f"Resource: {SELECTED}", resource_code=SELECTED)])
    assert bound[0]["evidence_bindings"] == authored["evidence_bindings"]
    assert bound[0]["_resource_evidence_check"]["code_in_refs"] is False
    trace = build_lsr_trace_from_visible_rows(bound, pricebook=Book())
    assert trace["summary"]["confirmed_amount"] == 0
    assert trace["summary"]["preliminary_amount"] == 300


def test_literal_resource_in_shown_typed_card_confirms_only_that_identifier():
    card = _card(f"Resource: {SELECTED}\nName: Authored supply\nUnit: m", resources=[{"code": SELECTED}])
    row = _row(supply_resource_match={
        "source_title": "Authored supply", "resource_code": SELECTED,
        "decision": "yes", "reason": "The shown typed resource names this supplied item.",
        "source_refs": ["Q1.H1"],
    })
    bound = bind_row_evidence_ids([row], [card])
    assert bound[0]["_resource_evidence_check"]["code_in_refs"] is True
    trace = build_lsr_trace_from_visible_rows(bound, pricebook=Book())
    assert trace["summary"]["confirmed_amount"] == 300
    assert trace["summary"]["preliminary_amount"] == 0
