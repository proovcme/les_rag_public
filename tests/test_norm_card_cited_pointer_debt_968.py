"""A cited typed pointer owes a read without qualifying the model's bare cipher.

Installed 967 B1 named bare 08-02-147-03 against deferred Q22.H1, whose literal
header named ГЭСНм08-02-147-03. Identity stayed invalid, but unknown body delivery
also bypassed the existing one-proof request. This is technical cited-read debt,
not evidence that the two cipher spellings identify the same norm.
"""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services import norm_card_proof_service as proof
from proxy.services.openai_compatible_transport_service import InferenceResponse
from tests.test_model_rag_sheet_evidence_reads import NORM_CODE_B, _run_sheet
from tests.test_norm_card_proof_request_930 import _pointer_chunk, _shown_chunk


QUALIFIED = "ГЭСНм08-02-147-03"
BARE = "08-02-147-03"
FIELD = "unread_cited_norm_card_refs"


def _row(code=BARE, refs=("Q2.H1",)):
    return {"source_row": "S!R2", "row_role": "work", "title": "Cable",
            "unit": "m", "quantity": 12, "norm_code": code,
            "evidence_refs": list(refs), "status": "EXACT_VERIFIED"}


def _bound(row=None, chunks=None, *, phase="first"):
    return service.bind_row_evidence_ids(
        [row or _row()], chunks if chunks is not None else [
            _pointer_chunk("Q2.H1", QUALIFIED, identity="card-a")],
        binding_phase=phase)[0]


def test_bare_cipher_cited_typed_pointer_owes_exact_read_without_identity_repair():
    row = _row()
    before = deepcopy(row)
    bound = _bound(row)
    check = bound["_evidence_check"]
    assert check[FIELD] == ["Q2.H1"]
    assert check["code_not_in_refs"] is True
    assert "card_body_shown" not in check
    assert bound["norm_code"] == BARE and bound["status"] == "EXACT_VERIFIED"
    assert row == before
    assert proof.unread_chosen_norm_rows([bound]) == [bound]
    assert proof.unread_chosen_norm_refs([bound]) == ["Q2.H1"]
    message = proof.proof_request_message(["Q2.H1"], [bound])
    assert "Q2.H1" in message and BARE in message and "read_norm_card" in message


def test_debt_uses_exact_cited_pointer_not_bare_digits_or_other_citations():
    # Syntax permits proof; it does not select the candidate whose digits match.
    chunks = [_pointer_chunk("Q2.H1", "ГЭСНм08-03-605-01", identity="fan"),
              _pointer_chunk("Q3.H1", QUALIFIED, identity="uncited-cable"),
              _pointer_chunk("Q4.H1", "Supplier resource", identity="resource")]
    bound = _bound(_row(refs=("Q2.H1", "Q4.H1")), chunks)
    assert bound["_evidence_check"][FIELD] == ["Q2.H1"]
    assert proof.unread_chosen_norm_refs([bound]) == ["Q2.H1"]
    assert bound["_evidence_check"]["code_not_in_refs"] is True


@pytest.mark.parametrize("code", ["", "MISSING", "NO_DATA", "норма"])
def test_empty_or_placeholder_norm_does_not_create_cited_read_debt(code):
    bound = _bound(_row(code))
    assert FIELD not in bound.get("_evidence_check", {})
    assert proof.unread_chosen_norm_rows([bound]) == []


@pytest.mark.parametrize("kind", ["full", "same_identity_other_alias", "unknown_ref",
                                 "ambiguous_alias", "non_norm_pointer"])
def test_no_debt_without_an_exact_unread_typed_norm_identity(kind):
    pointer = _pointer_chunk("Q2.H1", QUALIFIED, identity="card-a")
    row = _row()
    if kind == "full":
        chunks = [_shown_chunk("Q2.H1", QUALIFIED, identity="card-a")]
    elif kind == "same_identity_other_alias":
        # The immutable norm-card identity is independent of both query alias
        # and retrieval hit ID, which can differ on an exact reader response.
        chunks = [pointer, _shown_chunk("Q9.H1", QUALIFIED, identity="read-hit")]
    elif kind == "unknown_ref":
        row = _row(refs=("Q99.H1",))
        chunks = [pointer]
    elif kind == "ambiguous_alias":
        chunks = [pointer, _pointer_chunk("Q2.H1", QUALIFIED, identity="card-b")]
    else:
        pointer.meta.pop("norm_code")
        # Literal mention in an ordinary document is not a typed norm card.
        chunks = [pointer]
    bound = _bound(row, chunks)
    assert FIELD not in bound["_evidence_check"]
    assert "card_body_shown" not in bound["_evidence_check"]
    assert proof.unread_chosen_norm_rows([bound]) == []


def test_another_edition_full_body_does_not_discharge_the_cited_identity():
    pointer = _pointer_chunk("Q2.H1", QUALIFIED, identity="edition-a")
    pointer.meta["edition"] = "a"
    other = _shown_chunk("Q9.H1", QUALIFIED, identity="edition-b")
    other.meta["edition"] = "b"
    bound = _bound(chunks=[pointer, other])
    assert bound["_evidence_check"][FIELD] == ["Q2.H1"]
    assert proof.unread_chosen_norm_refs([bound]) == ["Q2.H1"]


def test_conflicting_typed_norms_under_one_bound_id_are_not_an_exact_read_target():
    chunks = [_pointer_chunk("Q2.H1", QUALIFIED, identity="contradictory-id"),
              _pointer_chunk("Q9.H1", "ГЭСНм08-03-605-01", identity="contradictory-id")]
    bound = _bound(chunks=chunks)
    assert FIELD not in bound["_evidence_check"]
    assert "card_body_shown" not in bound["_evidence_check"]
    assert proof.unread_chosen_norm_rows([bound]) == []


@pytest.mark.parametrize("code", [QUALIFIED, "ГЭСН08-02-147-03"])
@pytest.mark.parametrize("full", [False, True])
def test_qualified_selected_body_verdict_and_existing_proof_semantics_do_not_change(code, full):
    chunk = (_shown_chunk("Q2.H1", QUALIFIED, identity="card-a") if full else
             _pointer_chunk("Q2.H1", QUALIFIED, identity="card-a"))
    bound = _bound(_row(code), [chunk])
    check = bound["_evidence_check"]
    assert check["card_body_shown"] is (full and code == QUALIFIED)
    assert FIELD not in check
    assert proof.unread_chosen_norm_refs([bound]) == (
        [] if full and code == QUALIFIED else ["Q2.H1"])
    assert check["code_not_in_refs"] is (code != QUALIFIED)


def test_decoder_ignores_model_forged_debt_and_first_bind_recomputes_it():
    authored = _row(refs=("Q99.H1",))
    forged = {**authored, "_evidence_check": {FIELD: ["Q2.H1"]},
              FIELD: ["Q2.H1"], "evidence_bindings": {"Q99.H1": "card-a"}}
    parsed = service.parse_model_rag_result(json.dumps({"rows": [forged]}, ensure_ascii=False))
    assert parsed is not None
    decision = parsed[1][0]
    assert "_evidence_check" not in decision and FIELD not in decision
    assert "evidence_bindings" not in decision
    bound = _bound(decision)
    assert bound["evidence_bindings"] == {}
    assert FIELD not in bound["_evidence_check"]
    assert proof.unread_chosen_norm_rows([bound]) == []


def test_replay_cannot_bind_a_saved_unknown_ref_to_a_later_pointer():
    first = _bound(_row(refs=("Q99.H1",)))
    assert first["evidence_bindings"] == {}
    replay = _bound(first, [_pointer_chunk("Q99.H1", QUALIFIED, identity="future-card")],
                    phase="replay")
    assert replay["evidence_bindings"] == {}
    assert replay["_evidence_check"]["unresolved_refs"] == ["Q99.H1"]
    assert FIELD not in replay["_evidence_check"]


@pytest.mark.asyncio
async def test_native_route_asks_one_existing_proof_for_bare_cited_pointer(tmp_path, monkeypatch):
    bare = NORM_CODE_B.removeprefix("ГЭСН")
    answer = (
        "artifact_kind: lsr\n\n"
        "| source_row | row_role | title | unit | quantity | norm_code | evidence_refs |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        f"| S!R2 | work | Cable A | m | 12 | {bare} | Q2.H1 |\n"
        f"| S!R3 | work | Cable B | m | 3 | {bare} | Q2.H1 |"
    )
    run = await _run_sheet(
        tmp_path, monkeypatch, reads=False, variant="B1_CANDIDATE",
        group_char_budget=7000, distinct_norms=True, final_answer=answer,
        proof_replies=[InferenceResponse(text=answer, tool_calls=(), finish_reason="stop",
                                         usage={"completion_tokens": 120})])
    trace = run.result["retrieval_trace"]
    assert [entry["refs"] for entry in trace["norm_card_proof_requests"]] == [["Q2.H1"]]
    assert trace["norm_card_proof_requests"][0]["model_reads_after_request"] == 0
    assert len(run.requests) == 3 and not run.responses and not run.exact_reads
    rows = trace["model_result"]["decision_rows"]
    assert [row["norm_code"] for row in rows] == [bare, bare]
    assert all(row["_evidence_check"]["code_not_in_refs"] is True for row in rows)
    assert all("card_body_shown" not in row["_evidence_check"] for row in rows)
    assert all(row["_evidence_check"][FIELD] == ["Q2.H1"] for row in rows)
