"""Regression: a шифр chosen from a pointer-only card is sent back for proof (build 930).

Reproduced from the installed-929 evidence (`artifacts/live_929/card_read_repro_930/repro.json`,
script `.test-tmp/repro_929_card_read_blocker.py`): B0_DIRECT named 7 norms with 0 shown card
bodies and 6 of them still carried money in the delivered XLSX; B1_CANDIDATE delivered 125 norm
pointers, 18 body entries and 3 complete cards, offered `read_norm_card` on every answer call
(`canonical_native_tools.count = 5`) and received `native_tool_call_identities = []`.

These tests fix the mechanism, not the example:

* an answer that names a norm whose cited card was never shown is refused once, in the same
  research stage, with the refs and the шифры named in the reason;
* the read remains the model's own action — the application never fabricates a tool call, and
  the durable decision still comes from the model's answer;
* when the model does read, the chosen card counts as shown and the row is no longer an unread
  guess; when it does not, the row keeps `norm_card_body_unread` and no second proof round is
  bought with another inference call.
"""

from __future__ import annotations

import json

import pytest

from proxy.services import norm_card_proof_service as proof
from proxy.services.openai_compatible_transport_service import InferenceResponse
from tests.test_model_rag_sheet_evidence_reads import (
    NORM_CODE, NORM_CODE_B, _native, _run_sheet,
)


SECOND_NORM_ANSWER = (
    "artifact_kind: lsr\n\n"
    "| source_row | row_role | title | unit | quantity | norm_code | resource_code | evidence_refs |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
    f"| S!R2 | work | Cable A | m | 12 | {NORM_CODE_B} | — | Q2.H1 |\n"
    f"| S!R3 | work | Cable B | m | 3 | {NORM_CODE_B} | — | Q2.H1 |"
)


def _chunk(ref: str, *, body_status: str, delivery: str = "delivered"):
    from types import SimpleNamespace
    return SimpleNamespace(meta={"model_evidence_ref": ref, "body_status": body_status,
                                 "model_delivery_status": delivery}, content="Шифр: X")


def test_unread_detection_uses_the_chosen_rows_own_citation_only():
    rows = [
        # a work row naming a шифр against a deferred pointer: this one owes a proof
        {"row_role": "work", "source_row": "S!R2", "norm_code": NORM_CODE_B,
         "evidence_refs": ["Q2.H1"],
         "_evidence_check": {"card_body_shown": False, "deferred_card_refs": ["Q2.H1"]}},
        # the same card shown in full under another alias discharges the identity
        {"row_role": "work", "source_row": "S!R3", "norm_code": NORM_CODE_B,
         "evidence_refs": ["Q9.H1"],
         "_evidence_check": {"card_body_shown": True, "deferred_card_refs": []}},
        # a header row names nothing and must not consume the proof budget
        {"row_role": "header", "source_row": "S!R4", "norm_code": "",
         "evidence_refs": ["Q2.H1"],
         "_evidence_check": {"card_body_shown": False, "deferred_card_refs": ["Q2.H1"]}},
        # no evidence check at all is the reader's problem, not a proof debt
        {"row_role": "work", "source_row": "S!R5", "norm_code": NORM_CODE,
         "evidence_refs": ["Q2.H1"]},
    ]
    assert proof.unread_chosen_norm_refs(rows) == ["Q2.H1"]
    # a ref whose full body is already in the delivered context is not unread
    assert proof.unread_chosen_norm_refs(
        rows, chunks=[_chunk("Q2.H1", body_status="full")]) == []
    assert proof.delivered_refs_from_chunks(
        [_chunk("Q2.H1", body_status="deferred_capacity")]) == set()


def test_proof_budget_is_bounded_and_the_message_names_facts_only():
    assert proof.proof_budget() == proof.MAX_PROOF_REFS_PER_PACKET
    assert proof.proof_budget(configured=99) == proof.MAX_PROOF_REFS_PER_PACKET
    assert proof.proof_budget(configured=2) == 2
    rows = [{"row_role": "work", "source_row": "S!R2", "norm_code": NORM_CODE_B,
             "evidence_refs": ["Q2.H1"],
             "_evidence_check": {"card_body_shown": False, "deferred_card_refs": ["Q2.H1"]}}]
    message = proof.proof_request_message(["Q2.H1"], rows)
    assert "Q2.H1" in message and NORM_CODE_B in message and "read_norm_card" in message
    # the application states the missing proof; it never proposes or rejects a norm itself
    assert "подтверждаю" not in message and "ЭТА норма подходит" not in message


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B1_CANDIDATE"])
async def test_pointer_only_norm_choice_is_sent_back_once_without_a_second_guess(tmp_path, monkeypatch, variant):
    # The model answers again with the same unread шифр and no read: one proof round only.
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
                           group_char_budget=7000, distinct_norms=True,
                           final_answer=SECOND_NORM_ANSWER,
                           proof_replies=[InferenceResponse(text=SECOND_NORM_ANSWER, tool_calls=(),
                                                            finish_reason="stop",
                                                            usage={"completion_tokens": 120})])
    trace = run.result["retrieval_trace"]
    requests = trace["norm_card_proof_requests"]
    assert [entry["refs"] for entry in requests] == [["Q2.H1"]]
    assert requests[0]["reason"] == "norm_card_body_unread"
    assert requests[0]["model_reads_after_request"] == 0
    # queries + first answer + one proof request: a second unread answer buys no third call
    assert len(run.requests) == 3 and not run.responses and not run.exact_reads
    rows = (trace.get("model_result") or {}).get("decision_rows") or []
    assert [row["_evidence_check"]["card_body_shown"] for row in rows] == [False, False]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B1_CANDIDATE"])
async def test_the_read_that_proves_the_chosen_card_is_the_models_own(tmp_path, monkeypatch, variant):
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
                           group_char_budget=7000, distinct_norms=True,
                           final_answer=SECOND_NORM_ANSWER,
                           proof_replies=[
                               InferenceResponse(
                                   text="", tool_calls=(_native("read_norm_card",
                                                                evidence_ref="Q2.H1"),),
                                   finish_reason="tool_calls", usage={}),
                               InferenceResponse(text=SECOND_NORM_ANSWER, tool_calls=(),
                                                 finish_reason="stop",
                                                 usage={"completion_tokens": 120}),
                           ])
    trace = run.result["retrieval_trace"]
    entry = trace["norm_card_proof_requests"][0]
    assert entry["model_reads_after_request"] == 1 and entry["read_statuses"] == ["ok"]
    # the card was read by exact identity, by the model, not fabricated by the application
    assert run.exact_reads == [{"norm_key": "immutable-norm-b", "norm_code": NORM_CODE_B}]
    proof_turn = run.requests[2]
    # The exact prior answer and proof ask are now mandatory Governor evidence,
    # admitted together rather than appended after the initial budget check.
    proof_payloads = []
    for message in proof_turn.messages:
        assert message["role"] not in {"tool", "function"} and not message.get("tool_calls")
        for line in str(message.get("content") or "").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and "proof_previous_model_answer" in payload:
                proof_payloads.append(payload)
    assert len(proof_payloads) == 1
    assert proof_payloads[0]["proof_previous_model_answer"] == SECOND_NORM_ANSWER
    assert NORM_CODE_B in proof_payloads[0]["proof_request"]
    rows = (trace.get("model_result") or {}).get("decision_rows") or []
    assert [row["_evidence_check"]["card_body_shown"] for row in rows] == [True, True]
    assert not [gap for gap in (trace.get("result_readiness") or {}).get("row_projection") or []
                if "norm_card_body_unread" in json.dumps(gap, ensure_ascii=False)]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B1_CANDIDATE"])
async def test_an_answer_that_already_read_its_card_buys_no_extra_inference(tmp_path, monkeypatch, variant):
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant)
    assert "norm_card_proof_requests" not in run.result["retrieval_trace"]
    assert len(run.requests) == 4 and not run.responses
    # the cost of the missing search/narration boundary is counted per packet, visibly, and
    # a clean declaration measures zero
    passes = run.result["retrieval_trace"]["tool_loop"]["passes"]
    assert [row["narration_shaped_executed_lines"] for row in passes] == [0]


def test_delivery_facts_are_read_from_the_delivered_text_not_from_the_claim():
    """The 929 counter bug in one line: `card_body_shown` echoed the caller.

    A page that rendered only the inventory pointer could still be reported as a shown card,
    which is exactly how an unread шифр reached the XLSX with money on it.
    """
    from proxy.services.model_rag_grouped_evidence_service import card_delivery_facts

    meta = {"norm_key": "immutable-norm", "norm_code": NORM_CODE, "work_steps": ["Install"],
            "resource_count": 1, "resources": [{"code": "x"}], "resources_returned": 1,
            "resources_complete": True}
    pointer = json.dumps([f"Q1.H1", "deferred_capacity", "immutable-norm", NORM_CODE,
                          "Synthetic exact norm", "m", "source_x"], ensure_ascii=False)
    claimed = card_delivery_facts(meta, raw_body_shown=True, displayed_body=pointer)
    assert claimed["card_body_shown"] is False
    assert claimed["body_claim_disagrees_with_delivery"] is True
    # a pointer marked "full" is still only a pointer until the body text is delivered
    assert card_delivery_facts(meta, raw_body_shown=True,
                               displayed_body=pointer.replace("deferred_capacity", "full")
                               )["card_body_shown"] is False
    body = f"Шифр: {NORM_CODE}\nНаименование: Synthetic exact norm\nСостав работы: Install\n"
    shown = card_delivery_facts(meta, raw_body_shown=True, displayed_body=body)
    assert shown["card_body_shown"] is True and shown["body_claim_disagrees_with_delivery"] is False
    assert shown["normative_composition_shown"] is True
    assert shown["shown_body_carries_this_cipher"] is True
    other = card_delivery_facts(meta, raw_body_shown=True,
                                 displayed_body="Шифр: ДРУГАЯ-НОРМА\nСостав работы: Install\n")
    assert other["card_body_shown"] is True
    # card А never discharges card Б: the cipher carried by the shown body is a separate fact
    assert other["shown_body_carries_this_cipher"] is False



def _pointer_chunk(ref: str, code: str, *, identity: str):
    from types import SimpleNamespace
    inventory = json.dumps([ref, "deferred_capacity", identity, code, "Synthetic norm",
                            "м2", "source_x"], ensure_ascii=False)
    return SimpleNamespace(content=inventory, doc_name="cards", meta={
        "model_evidence_ref": ref, "global_evidence_id": identity,
        "norm_code": code, "body_status": "deferred_capacity",
        "model_delivery_status": "delivered", "model_raw_body_retained": False,
        "model_inventory_view": inventory, "model_query_text": identity})


def _shown_chunk(ref: str, code: str, *, identity: str):
    from types import SimpleNamespace
    return SimpleNamespace(content=f"Шифр: {code}\nНаименование: Synthetic norm\n"
                                   f"Состав работы: Установить изделие\n",
                           doc_name="cards", meta={
        "model_evidence_ref": ref, "global_evidence_id": identity,
        "norm_code": code, "body_status": "full", "model_delivery_status": "delivered"})


def test_a_cipher_named_without_any_cited_card_still_owes_its_verdict():
    """The hole the installed 930 measured live: no citation, no verdict, still money.

    15 of the 17 БАП rows that named a шифр cited nothing, so `bind_row_evidence_ids` wrote
    no `card_body_shown` at all.  A row with no verdict is invisible to the proof request and
    to the readiness gap, and the calculator paid for a card nobody showed.
    """
    from proxy.services import chat_evidence_application_service as service
    from proxy.services.lsr_norm_quality_gate_service import applicability_gap_kind

    row = {"source_row": "S!R9", "row_role": "work", "title": "Монтаж лючка", "unit": "шт",
           "quantity": 2, "norm_code": NORM_CODE_B}
    bound = service.bind_row_evidence_ids([row], [_pointer_chunk(
        "Q7.H1", NORM_CODE, identity="other-card")])[0]
    check = bound["_evidence_check"]
    assert check["card_body_shown"] is False
    assert check["card_body_shown_basis"] == "no_delivered_card_names_this_cipher"
    assert applicability_gap_kind(bound) == "norm_card_body_unread"
    # the debt is counted from the row, and there is no ref that could discharge it
    assert [item["source_row"] for item in proof.unread_chosen_norm_rows([bound])] == ["S!R9"]
    assert proof.unread_chosen_norm_refs([bound]) == []
    message = proof.proof_request_message([], [bound])
    assert NORM_CODE_B in message and "search_sources" in message
    assert "read_norm_card" in message


def test_a_delivered_card_of_the_same_cipher_discharges_the_row():
    from proxy.services import chat_evidence_application_service as service

    row = {"source_row": "S!R9", "row_role": "work", "title": "Монтаж лючка", "unit": "шт",
           "quantity": 2, "norm_code": NORM_CODE_B}
    bound = service.bind_row_evidence_ids([row], [
        _shown_chunk("Q9.H1", NORM_CODE_B, identity="chosen-card")])[0]
    assert bound["_evidence_check"]["card_body_shown"] is True
    assert bound["_evidence_check"]["card_body_shown_basis"] == "cipher_card_body_delivered"
    assert proof.unread_chosen_norm_rows([bound]) == []
    # a shown card of another cipher does not discharge this row either
    other = service.bind_row_evidence_ids([row], [
        _shown_chunk("Q9.H1", NORM_CODE, identity="different-card")])[0]
    assert other["_evidence_check"]["card_body_shown"] is False


def test_a_non_cipher_cipher_names_no_item_and_owes_no_body_verdict():
    """A bare code identifies no item, so no delivery verdict is written for it."""
    from proxy.services import chat_evidence_application_service as service

    row = {"source_row": "S!R2", "row_role": "work", "unit": "шт", "quantity": 1,
           "norm_code": "норма"}
    bound = service.bind_row_evidence_ids([row], [_pointer_chunk(
        "Q7.H1", NORM_CODE, identity="other-card")])[0]
    assert "card_body_shown" not in bound["_evidence_check"]


def test_an_unreadable_proof_answer_leaves_the_rows_it_was_asked_about():
    """The rule the installed 932 measured as a sheet of zero works, in one call.

    A proof round is a request to the model, not a licence to overwrite the packet: an answer
    without a table keeps the earlier rows and says so.
    """
    from proxy.services import chat_evidence_application_service as service

    previous = [{"source_row": "S!R2", "row_role": "work", "norm_code": NORM_CODE_B}]
    rows, parsed = service.rows_after_proof_round(
        parsed_rows=[], previous_rows=previous, chunks=[])
    assert parsed is False and rows == previous
    # a non-empty answer is still rebound, so a genuine correction is not swallowed
    rows, parsed = service.rows_after_proof_round(
        parsed_rows=[dict(previous[0], quantity=7)], previous_rows=previous, chunks=[])
    assert parsed is True and rows[0]["quantity"] == 7
    assert "_evidence_check" in rows[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B1_CANDIDATE"])
async def test_a_proof_round_answered_in_prose_delivers_the_packet_rows(tmp_path, monkeypatch,
                                                                       variant):
    """End-to-end of the 932 regression: the ask may not turn a answered packet into zero works.

    Measured in `artifacts/live_932/installed932_bap_b1/final.json`: ``work_rows 0``,
    ``rows_naming_a_norm 0``, ``preliminary_amount 0.0`` after a proof round whose answer carried
    no table, while the same packet before the round had its rows.
    """
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
                           group_char_budget=7000, distinct_norms=True,
                           final_answer=SECOND_NORM_ANSWER,
                           proof_replies=[InferenceResponse(
                               text="Карточку я не прочитал, уточни, какой сборник брать.",
                               tool_calls=(), finish_reason="stop",
                               usage={"completion_tokens": 40})])
    trace = run.result["retrieval_trace"]
    entry = trace["norm_card_proof_requests"][0]
    assert entry["reason"] == "norm_card_body_unread"
    assert entry["answer_parsed"] is False
    assert entry["model_reads_after_request"] == 0
    rows = (trace.get("model_result") or {}).get("decision_rows") or []
    assert [row["source_row"] for row in rows] == ["S!R2", "S!R3"]
    assert [row["norm_code"] for row in rows] == [NORM_CODE_B, NORM_CODE_B]
    # the rows keep their own unread verdict — nothing here promotes a status
    assert [row["_evidence_check"]["card_body_shown"] for row in rows] == [False, False]
    counts = (trace.get("result_readiness") or {}).get("counts") or {}
    assert int(counts.get("works") or 0) == 2



def test_a_row_whose_cited_card_was_only_a_pointer_gets_the_basis_too():
    """Installed 934: 14 of the 16 unread rows were judged here, and none of them said why.

    The total verdict below this branch never ran for them, so the operator saw «не прочитано»
    without the fact it came from — while the closeout requires exactly this distinction
    (present in results / shown brief / actually delivered in full) to be readable per row.
    """
    from proxy.services import chat_evidence_application_service as service

    row = {"source_row": "S!R2", "row_role": "work", "title": "Монтаж лючка", "unit": "шт",
           "quantity": 2, "norm_code": NORM_CODE_B, "evidence_refs": ["Q7.H1"]}
    bound = service.bind_row_evidence_ids([row], [
        _pointer_chunk("Q7.H1", NORM_CODE_B, identity="deferred-chosen")])[0]
    check = bound["_evidence_check"]
    assert check["card_body_shown"] is False
    assert check["card_body_shown_basis"] == "cited_card_body_not_delivered"
    assert check["deferred_card_refs"] == ["Q7.H1"]
    # the same pointer, once its body is delivered in full, discharges with its own basis
    both = service.bind_row_evidence_ids([row], [
        _pointer_chunk("Q7.H1", NORM_CODE_B, identity="deferred-chosen"),
        _shown_chunk("Q7.H1", NORM_CODE_B, identity="deferred-chosen")])[0]
    assert both["_evidence_check"]["card_body_shown"] is True
    assert both["_evidence_check"]["card_body_shown_basis"] in (
        "cited_card_body_delivered", "cipher_card_body_delivered")

def test_the_proof_record_carries_the_answer_parse_flag():
    trace: dict = {}
    proof.record_proof_request(trace, sheet="S", packet=("S!R2",), refs=("Q2.H1",),
                               receipts=(), attempt=1,
                               unread_rows=[{"source_row": "S!R2", "norm_code": NORM_CODE_B}],
                               answer_parsed=False)
    entry = trace["norm_card_proof_requests"][0]
    assert entry["answer_parsed"] is False
    assert entry["unread_norm_rows"] == 1 and entry["unread_ciphers"] == [NORM_CODE_B]
    # a round nobody asked about parse failures still records the honest default
    proof.record_proof_request(trace, sheet="S", packet=("S!R3",), refs=(), receipts=(),
                               attempt=1, unread_rows=[])
    assert trace["norm_card_proof_requests"][1]["answer_parsed"] is True
