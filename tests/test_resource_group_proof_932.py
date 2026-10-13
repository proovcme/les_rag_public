"""Regression: a read norm card that cites a resource group is sent back for a member choice.

Measured on the installed 931 (`artifacts/live_931/installed931_big_b1/`): all 7 priced blocks of
the customer's big ВОР had their card read, and every one of them still failed to become a
calculated position, because the card cites a family (`11.2.11.01`, `04.3.01.12`) while the chosen
book prices concrete members (`11.2.11.01-0001`, …) — `open_reasons = ["price_missing:<код>"]`,
`price_action = "unresolved_resource_group"`, `calculated_positions = 0`, `confirmed_amount = 0`.

These tests pin the ask and its limits, not the example: the debt is detected only on cards the
model actually read, only for codes the book really prices as a family, bounded per packet, and
answered by the model's own choice.  The application never picks a member and never promotes a
status.
"""

from __future__ import annotations

from types import SimpleNamespace

import proxy.services.lsr_resource_group_proof_service as proof


CIPHER = "ГЭСН 15-01-050-04"
GROUP = "11.2.11.01"
MEMBERS = [{"code": f"{GROUP}-000{n}", "name": f"Пластик {n}", "unit": "м2",
            "price_current_eff": 100 + n} for n in range(1, 11)]


class _StubBook:
    """The two states the real book answers with; `resource_group` is the same call shape."""

    def __init__(self, states):
        self._states = states

    def resource_group(self, code):
        return self._states.get(str(code).strip(), {"state": "no_book_row", "group": "",
                                                    "members": [], "total": 0,
                                                    "truncated": False})


def _book(*, group_state: bool = True) -> _StubBook:
    states = {
        GROUP: ({"state": "unresolved_resource_group", "group": GROUP, "members": MEMBERS,
                 "total": len(MEMBERS), "truncated": False} if group_state else
                {"state": "resolved", "group": GROUP, "members": [], "total": 0,
                 "truncated": False}),
        "100-0103": {"state": "resolved", "group": "", "members": [], "total": 0,
                     "truncated": False},
    }
    return _StubBook(states)


def _card_chunk(resources, *, ref: str = "Q136.H1", code: str = CIPHER,
                read: bool = True):
    meta = {"norm_code": code, "model_evidence_ref": ref, "resources": list(resources),
            "resource_count": len(resources)}
    if read:
        meta["exact_card_read"] = True
        meta["body_status"] = "full"
    else:
        meta["body_status"] = "deferred_capacity"
    return SimpleNamespace(content="Шифр: " + code, meta=meta)


RESOURCE = {"kind": "material", "code": GROUP, "name": "Листы облицовочные декоративные",
            "unit": "м2", "per_unit": 20.475}
ROWS = [{"row_role": "work", "source_row": "АР!R11", "norm_code": CIPHER}]


def test_a_group_from_a_read_card_is_the_only_kind_of_debt_this_ask_sees():
    chunk = _card_chunk([RESOURCE, {"kind": "material", "code": "100-0103", "name": "Вода",
                                    "unit": "м3", "per_unit": 0.1}])
    found = proof.unresolved_groups(ROWS, [chunk], pricebook=_book())
    assert [item["code"] for item in found] == [GROUP]
    assert found[0]["cipher"] == CIPHER.upper().replace("Ё", "Е")
    assert found[0]["locator"] == "АР!R11"
    assert found[0]["total"] == len(MEMBERS)
    # a card the model never read creates no debt: the application does not invent one
    pointer = _card_chunk([RESOURCE], read=False)
    assert proof.unresolved_groups(ROWS, [pointer], pricebook=_book()) == []
    # a code the book prices directly is not a hole at all
    priced = _card_chunk([{"kind": "material", "code": "100-0103", "name": "Вода",
                           "unit": "м3", "per_unit": 0.1}], )
    assert proof.unresolved_groups(ROWS, [priced], pricebook=_book()) == []
    # and a family the book does not price at all is the existing missing-price hole
    assert proof.unresolved_groups(ROWS, [chunk], pricebook=_book(group_state=False)) == []
    assert proof.unresolved_groups(ROWS, [chunk], pricebook=None) == []


def test_the_debt_is_counted_only_for_a_cipher_the_model_chose():
    chunk = _card_chunk([RESOURCE])
    assert proof.unresolved_groups(ROWS, [chunk], pricebook=_book())
    other = [{"row_role": "work", "source_row": "АР!R11", "norm_code": "ГЭСН 99-99-9999-01"}]
    assert proof.unresolved_groups(other, [chunk], pricebook=_book()) == []
    # a header row names nothing and must not consume the budget
    assert proof.unresolved_groups([{"row_role": "header", "source_row": "АР!R1",
                                    "norm_code": CIPHER}], [chunk], pricebook=_book()) == []


def test_the_message_lists_members_and_names_the_tools_without_choosing_one():
    found = proof.unresolved_groups(ROWS, [_card_chunk([RESOURCE])], pricebook=_book())
    message = proof.proof_request_message(found)
    assert GROUP in message and f"{GROUP}-0001" in message
    assert proof.SEARCH_TOOL in message and proof.PRICE_TOOL in message
    assert "АР!R11" in message and CIPHER in message
    # the family is never priced by the message itself, and no member is preferred
    assert "первая строка группы не является ценой группы" in message
    assert all(member["name"] not in message.split("Выбери")[0] for member in MEMBERS[1:])
    assert proof.proof_request_message([]) == ""


def test_the_offer_is_bounded_and_the_truncation_is_stated():
    many = [{"row_role": "work", "source_row": f"АР!R{n}", "norm_code": f"ГЭСН 15-01-05{n}-04"}
            for n in range(1, 6)]
    chunks = [_card_chunk([RESOURCE], code=row["norm_code"], ref=f"Q{n}.H1")
              for n, row in enumerate(many, start=1)]
    found = proof.unresolved_groups(many, chunks, pricebook=_book())
    assert len(found) == proof.MAX_GROUPS_PER_PACKET
    assert len(found[0]["members"]) == proof.MAX_MEMBERS_SHOWN
    trimmed = dict(found[0], truncated=True)
    message = proof.proof_request_message([trimmed])
    assert "ещё" in message and proof.SEARCH_TOOL in message


def test_the_refusal_is_recorded_as_a_visible_fact():
    trace: dict = {}
    found = proof.unresolved_groups(ROWS, [_card_chunk([RESOURCE])], pricebook=_book())
    proof.record_proof_request(trace, sheet="АР", packet=["АР!R11"], groups=found,
                               answered=True, attempt=1)
    entry = trace[proof.PROOF_REQUEST_TRACE][0]
    assert entry["schema"] == proof.TRACE_SCHEMA
    assert entry["reason"] == "unresolved_resource_group"
    assert entry["requested"] == 1 and entry["model_answered"] is True
    assert entry["groups"][0]["group"] == GROUP
    assert entry["packet_locators"] == ["АР!R11"]


def test_the_budget_is_bounded_and_measured():
    assert proof.proof_budget() == proof.MAX_GROUPS_PER_PACKET
    assert proof.proof_budget(configured=99) == proof.MAX_GROUPS_PER_PACKET
    assert proof.proof_budget(configured=2) == 2
    assert proof.proof_budget(env_value="3") == 3
    assert proof.proof_budget(env_value="не число") == proof.MAX_GROUPS_PER_PACKET


def test_the_group_ask_reads_only_the_explicitly_chosen_book(monkeypatch):
    """ADR-16 § 7 is the contract the ask has to honour as well.

    Resolving a family through an implicit or scratch book would show the model members of a
    price basis the document never chose, and the position would then close on the wrong money.
    """
    from proxy.services import fgis_price_service as fps
    from proxy.services.chat_evidence_application_service import model_pricebook

    seen: list[dict] = []

    def fake_resolve(book=None, **kwargs):
        seen.append({"book": book, **kwargs})
        return None

    monkeypatch.setattr(fps, "resolve_pricebook_path", fake_resolve)
    assert model_pricebook({"pricebook": "spb_3kv2026"}) is None
    assert seen == [{"book": "spb_3kv2026", "explicit_only": True}]
    # no chosen book, no ask: nothing is borrowed from another region or quarter
    assert model_pricebook(None) is None and model_pricebook({}) is None
    assert model_pricebook({"pricebook": ""}) is None
    assert len(seen) == 1
    # a stored hash that no longer matches the bytes stops the ask as well
    assert model_pricebook({"pricebook": "spb_3kv2026",
                            "pricebook_sha256": "0" * 64}) is None
    assert seen[-1]["book"] == "spb_3kv2026"


def test_the_group_state_is_read_through_the_calculator_helper_not_a_second_rule():
    """One home for the family rule, or the two engines price the same row differently."""
    from proxy.services import rim_lsr_trace_service as rim

    calls: list[tuple] = []

    class _RecordingBook:
        def resource_group(self, code):
            calls.append((code,))
            return {"state": "unresolved_resource_group", "group": code, "members": MEMBERS,
                    "total": len(MEMBERS), "truncated": True}

    found = proof.unresolved_groups(ROWS, [_card_chunk([RESOURCE])], pricebook=_RecordingBook())
    assert found and calls == [(GROUP,)]
    assert rim.resource_group_state(dict(RESOURCE), _RecordingBook())["state"] \
        == "unresolved_resource_group"
