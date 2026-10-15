"""Regression for build 944: the per-packet cap on group-resource asks must be visible.

Discovered while finishing § 4 of the task on the installed 942/943. The second laboratory package
(`artifacts/handoff/lab15/runs/C0*_B.json`, `…_C.json`) showed the model accepting the row format
yet leaving `resource_bindings` empty on every one of the six contract-condition answers, which is
exactly how a norm resource stays a family code and the position never closes (#81). The application
notices that debt here and asks about it — but the ask is bounded per packet
(`MAX_GROUPS_PER_PACKET = 4`), and until now the surplus simply vanished: `unresolved_groups()`
returned the first four items, and `record_proof_request` wrote `requested = len(groups)`. An
auditor reading the receipt could not tell «no more debt» from «debt exists but was not asked in
this packet» — the same class of silence that build 942 had to fix for the truncated attachment
frame.

Visibility only, in line with § 3: no member is chosen, no status is promoted, the untouched
`price_missing:<код>` gap keeps blocking the confirmed amount.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import proxy.services.lsr_resource_group_proof_service as proof


GROUPS = [f"11.2.11.0{i}" for i in range(1, 6)]
MEMBERS = {group: [{"code": f"{group}-0001", "name": f"Пластик {group}", "unit": "м2",
                    "price_current_eff": 100.0 + index}
                   for index in range(3)]
           for group in GROUPS}


class _StubBook:
    """Answers exactly like `fgis_price_service.PriceBook.resource_group`."""

    def resource_group(self, code):
        code = str(code).strip()
        if code in MEMBERS:
            members = MEMBERS[code]
            return {"state": "unresolved_resource_group", "group": code,
                    "members": members, "total": len(members), "truncated": False}
        return {"state": "no_book_row", "group": "", "members": [], "total": 0,
                "truncated": False}


def _rows():
    return [{"norm_code": f"ГЭСН 15-01-0{i:02d}-04", "row_role": "work",
             "source_row": f"PDF!R{i}"} for i in range(1, 6)]


def _chunks():
    """Five read cards, each citing its own family code."""
    chunks = []
    for index, group in enumerate(GROUPS, start=1):
        chunks.append(SimpleNamespace(
            content=f"Карточка {index}",
            doc_name=f"card-{index}",
            meta={"norm_code": f"ГЭСН 15-01-0{index:02d}-04",
                  "model_evidence_ref": f"Q{130 + index}.H1",
                  "exact_card_read": True,
                  "resources": [{"kind": "material", "code": group,
                                 "name": f"Группа {group}", "unit": "м2"}]},
        ))
    return chunks


def test_the_packet_shows_four_but_says_that_five_were_detected():
    groups = proof.unresolved_groups(_rows(), _chunks(), pricebook=_StubBook(), max_groups=4)
    assert len(groups) == 4
    assert {item.get("detected_in_pass") for item in groups} == {5}, (
        "детектированный долг над ограничением пакета исчезает без следа")
    assert {item.get("deferred_in_pass") for item in groups} == {1}


def test_the_message_states_what_was_left_for_the_next_packet():
    groups = proof.unresolved_groups(_rows(), _chunks(), pricebook=_StubBook(), max_groups=4)
    message = proof.proof_request_message(groups)
    assert "ещё 1" in message, "сообщение не говорит, что часть долгов не запрашивалась"
    assert "следующ" in message.lower(), (
        "не сказано, куда денется неотпрашенный долг — это читается как «долгов больше нет»")


def test_the_receipt_records_the_bound_and_the_surplus():
    trace: dict = {}
    groups = proof.unresolved_groups(_rows(), _chunks(), pricebook=_StubBook(), max_groups=4)
    proof.record_proof_request(trace, sheet="PDF", packet=["PDF!R1"], groups=groups,
                              answered=True, attempt=1, answer_parsed=True, receipts=())
    entry = trace[proof.PROOF_REQUEST_TRACE][-1]
    assert entry["requested"] == 4
    assert entry.get("detected") == 5, "в квитанции не видно, что долгов было больше"
    assert entry.get("deferred_to_next_packet") == 1
    assert entry.get("max_groups_per_packet") == proof.MAX_GROUPS_PER_PACKET


def test_no_surplus_means_no_deferred_claims():
    groups = proof.unresolved_groups(_rows()[:2], _chunks()[:2], pricebook=_StubBook(),
                                     max_groups=4)
    assert len(groups) == 2
    assert {item.get("deferred_in_pass") for item in groups} == {0}
    message = proof.proof_request_message(groups)
    assert "ещё" not in message, "сообщение выдумывает неотпрашенный долг"
