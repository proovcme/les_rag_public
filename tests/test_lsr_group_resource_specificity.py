"""§ 11 № 5 / § 7 / § 3: a group resource has its own state, candidates and question.

The estimate engine may only bind a price to a *concrete* resource code.  A group
address (``01.1.01.01``) has several members with different prices, so taking any
of them would silently reprice the estimate — the exact shortcut this regression
forbids.  Task 2026-09-29 § 3 adds the other half: that ban is only a guard, and a
refusal alone leaves the operator with «нужна цена», a question the book has already
answered for the family.  So a group reference now carries an explicit
``unresolved_resource_group`` state, a read-only listing of the concrete resources
of the price book (service method *and* the two ``/api/lsr/resources/*`` routes that
make it reachable), and one question worded after its real cause.  Both LSR engines
have to stop on the same row, or one document gets two sums (§ 10), which the last
test pins.  The numbers are mechanical proof over a synthetic price book — no model
and no invented amount; the read-only routes are then re-run against the locally
installed price book so the path is shown working on real data, not only on a stub.
"""

from __future__ import annotations

import asyncio

import pytest

from proxy.services.fgis_price_service import PriceBook, resource_group_prefix
from proxy.services.lsr_assembly_service import (
    _price_requirement,
    _resource_price,
    compute_position,
)
from proxy.services.rim_lsr_trace_service import (
    RESOURCE_GROUP_ACTION,
    _resolve_price_trace,
)

GROUP = "01.1.01.01"
MEMBERS = (
    {
        "code": f"{GROUP}-0001",
        "name": "Кабель силовой с бумаговой изоляцией, 1 кВ, 3 жилы, сечение 5 мм²",
        "unit": "м",
        "price_base": 90.0,
        "price_current_eff": 100.0,
        "group_no": GROUP,
        "group_name": "Кабели силовые",
    },
    {
        "code": f"{GROUP}-0002",
        "name": "Кабель силовой с бумаговой изоляцией, 1 кВ, 3 жилы, сечение 120 мм²",
        "unit": "м",
        "price_base": 270.0,
        "price_current_eff": 300.0,
        "group_no": GROUP,
        "group_name": "Кабели силовые",
    },
)


def _book() -> PriceBook:
    return PriceBook([dict(item) for item in MEMBERS], region="СПб", quarter="3 квартал 2026 г.")


def test_a_group_code_is_never_priced_by_the_first_member_of_the_group() -> None:
    book = _book()

    price, source = _resource_price(
        {"kind": "material", "code": GROUP, "name": "Кабель", "unit": "м", "qty": 10},
        book,
        {},
    )

    # the refusal still holds (§ 11 № 5), and it is now named for what it is: no
    # money was taken, and the hole is the member, not the number (§ 3)
    assert (price, source) == (None, RESOURCE_GROUP_ACTION)
    # the members exist and differ; picking the first would have been 100, the
    # second 300 — neither is the resource the source row described
    assert [book.lookup(code)["price_current_eff"] for code in
            (f"{GROUP}-0001", f"{GROUP}-0002")] == [100.0, 300.0]


def test_an_exact_member_code_is_priced_and_the_group_stays_unbound() -> None:
    book = _book()
    concrete = {
        "kind": "material", "code": f"{GROUP}-0002", "name": "Кабель", "unit": "м",
        "qty": 10,
    }

    assert _resource_price(concrete, book, {}) == (300.0, "fgis")
    assert _resource_price({**concrete, "code": GROUP}, book, {}) == (
        None, RESOURCE_GROUP_ACTION
    )
    # a prefix of a member is still not that member: 01.1.01 names a family the book
    # prices, so it gets the family's state and still no amount
    assert _resource_price({**concrete, "code": "01.1.01"}, book, {}) == (
        None, RESOURCE_GROUP_ACTION
    )


def test_the_book_lists_the_concrete_resources_of_a_group_without_choosing_one() -> None:
    """The read-only path § 3 asks for: named members, no bound price."""

    book = _book()

    state = book.resource_group(GROUP)
    assert state["state"] == RESOURCE_GROUP_ACTION
    assert state["group"] == GROUP
    assert state["total"] == 2
    assert [item["code"] for item in state["members"]] == [
        f"{GROUP}-0001", f"{GROUP}-0002"
    ]
    # characteristics, not just a number: the choice is made on unit and name
    assert {item["unit"] for item in state["members"]} == {"м"}
    assert [item["price_current_eff"] for item in state["members"]] == [100.0, 300.0]
    assert "Кабель" in state["members"][0]["name"]

    # a member is resolved, a code the book has never heard of is not a group
    assert book.resource_group(f"{GROUP}-0001")["state"] == "resolved"
    assert book.resource_group("99.99.99.99")["state"] == "no_book_row"
    assert book.resource_group("Кабель силовой")["state"] == "no_book_row"


def test_the_group_question_asks_for_a_member_and_carries_the_candidates() -> None:
    requirement = _price_requirement(
        {"kind": "material", "code": GROUP, "name": "Кабель", "unit": "м"}, _book()
    )

    assert requirement["action"] == RESOURCE_GROUP_ACTION
    assert requirement["resource_group"] == GROUP
    assert requirement["resource_total"] == 2
    assert len(requirement["resources"]) == 2
    # the sentence names the family and says the first price is not taken, so an
    # operator reading it knows which decision is theirs
    assert GROUP in requirement["message"]
    assert "первая цена группы не берётся" in requirement["message"]


def test_a_group_row_stops_the_position_without_dropping_the_other_resources() -> None:
    result = compute_position(
        {
            "code": "",
            "name": "Монтаж кабеля",
            "unit": "100 м",
            "qty": 1.0,
            "nr_pct": 0,
            "sp_pct": 0,
            "resources": [
                {"kind": "labor", "code": "1.1.1.1", "name": "Монтажник", "unit": "ч",
                 "qty": 2.0, "price": 200.0},
                {"kind": "material", "code": GROUP, "name": "Кабель", "unit": "м",
                 "qty": 100.0},
            ],
        },
        pricebook=_book(),
    )

    # labour is still paid; the family contributes nothing until a member is named
    assert result["base"]["ozp"] == 400.0
    assert result["base"]["mat"] == 0.0
    by_code = {str(item["code"]): item for item in result["resources"]}
    assert by_code[GROUP]["price_used"] is None
    assert by_code[GROUP]["cost"] == 0.0
    # the row keeps what the operator has to answer with: the question, the family
    # and the concrete resources the book offers (§ 3)
    assert by_code[GROUP]["price_action"] == RESOURCE_GROUP_ACTION
    assert [item["action"] for item in result["price_requirements"]] == [
        RESOURCE_GROUP_ACTION
    ]
    assert len(result["price_requirements"][0]["resources"]) == 2
    assert any(GROUP in flag for flag in result["flags"])


def test_both_lsr_engines_stop_on_the_same_group_row() -> None:
    """§ 10: one document, one sum — the guard cannot live in only one engine."""

    resource = {"kind": "material", "code": GROUP, "name": "Кабель", "unit": "м",
                "qty": 100.0}
    book = _book()

    trace = _resolve_price_trace(resource, pricebook=book, kac_map={})
    assert trace.price is None
    assert trace.action == RESOURCE_GROUP_ACTION
    assert trace.group is not None and trace.group["total"] == 2
    assert _resource_price(resource, book, {})[1] == trace.action


def test_browsing_offers_the_group_members_as_candidates_without_binding_one() -> None:
    book = _book()

    candidates = book.browse("Кабель силовой с бумаговой изоляцией", limit=5)

    assert len(candidates) > 1
    assert {str(item.get("code")) for item in candidates} >= {f"{GROUP}-0001", f"{GROUP}-0002"}
    # ranking candidates is not pricing them: without a concrete code the position
    # still has no money, so the operator or the model must choose by characteristics
    assert _resource_price(
        {"kind": "material", "code": "", "name": "Кабель силовой", "unit": "м"}, book, {}
    ) == (None, "missing")


def test_the_unpriced_resource_is_asked_for_by_code_and_name() -> None:
    requirement = _price_requirement(
        {"kind": "material", "code": GROUP, "name": "Кабель", "unit": "м"}
    )

    assert requirement["action"] == "needs_kac"
    assert requirement["resource_code"] == GROUP
    assert "Кабель" in requirement["message"]


def test_a_resource_without_a_book_price_goes_to_the_manual_price_list() -> None:
    # § 7: an unpriced material belongs to КАЦ — and an internet price never
    # enters that list, so the only accepted manual source is the operator's own.
    price, source = _resource_price(
        {"kind": "material", "code": GROUP, "name": "Кабель", "unit": "м"}, _book(),
        {"кабель": 42.5},
    )

    assert (price, source) == (42.5, "kac")


# ── the read-only HTTP path § 3 asks for ──────────────────────────────────────
#
# A guard with no door is a dead end: whoever is told «назовите конкретный ресурс»
# needs somewhere to read the concrete resources from.  These tests go through the
# route functions, not the service, because a method nobody can call is not a
# working path.  The book is stubbed for the assertions on known numbers; the last
# test runs the same route against the real local price book and is skipped only
# when no price book is installed at all.


def test_the_group_route_shows_the_members_and_binds_no_price(monkeypatch) -> None:
    from proxy.routers import lsr as lsr_router

    monkeypatch.setattr(lsr_router.la, "_resolve_book", lambda book: _book())

    payload = asyncio.run(
        lsr_router.lsr_pricebook_resource_group(
            code=GROUP, unit="м", book="spb", limit=40, _user=object()
        )
    )

    assert payload["schema"] == "lsr_pricebook_resource_state_v1"
    assert payload["selection_owner"] == "model_or_user"
    assert payload["price_binding"] == "not_selected"
    assert payload["state"]["state"] == RESOURCE_GROUP_ACTION
    assert [item["code"] for item in payload["state"]["members"]] == [
        f"{GROUP}-0001", f"{GROUP}-0002"
    ]
    assert payload["book"] == {"requested": "spb", "region": "СПб", "quarter": "3 квартал 2026 г."}
    # the operator gets one sentence naming the family and the ban, so the answer
    # they type back is a code, not another «нужна цена»
    assert GROUP in payload["note"]
    assert "первая цена группы не берётся" in payload["note"]


def test_the_browse_route_returns_candidates_without_choosing_one(monkeypatch) -> None:
    from proxy.routers import lsr as lsr_router

    monkeypatch.setattr(lsr_router.la, "_resolve_book", lambda book: _book())

    payload = asyncio.run(
        lsr_router.lsr_pricebook_resource_browse(
            q="Кабель силовой с бумаговой изоляцией", book="", limit=5, _user=object()
        )
    )

    assert payload["price_binding"] == "not_selected"
    assert payload["returned_candidates"] == len(payload["resources"])
    assert {str(item["code"]) for item in payload["resources"]} >= {
        f"{GROUP}-0001", f"{GROUP}-0002"
    }
    # ranking is evidence: the row says which tokens matched, never that a
    # candidate fits the position
    assert payload["resources"][0]["match"]["schema"] == "fgis_price_lexical_match_v1"


def test_an_unknown_book_is_named_and_never_silently_swapped(monkeypatch) -> None:
    from fastapi import HTTPException

    from proxy.routers import lsr as lsr_router

    monkeypatch.setattr(lsr_router.la, "_resolve_book", lambda book: None)
    monkeypatch.setattr(lsr_router, "_book_stems", lambda: ["sankt-peterburg_2kv2026"])

    with pytest.raises(HTTPException) as refused:
        asyncio.run(
            lsr_router.lsr_pricebook_resource_group(code=GROUP, _user=object())
        )

    assert refused.value.status_code == 400
    assert "sankt-peterburg_2kv2026" in refused.value.detail


def test_the_group_route_reads_the_real_price_book() -> None:
    from proxy.routers import lsr as lsr_router

    book = lsr_router.la._resolve_book(None)
    if book is None or not getattr(book, "_rows", ()):
        pytest.skip("no local price book installed — nothing real to read here")

    row = book._rows[0]
    member = str(row.get("code") or "")
    group = resource_group_prefix(member)
    if not group:
        pytest.skip(f"real book row {member!r} is not a grouped resource code")

    payload = asyncio.run(
        lsr_router.lsr_pricebook_resource_group(code=group, unit="", book="", limit=10, _user=object())
    )

    # the family resolves through the same route the operator would call, on real
    # data: it is priced as a group, so the members are listable
    assert payload["state"]["total"] >= 1
    assert payload["price_binding"] == "not_selected"
    assert payload["book"]["region"] or payload["book"]["quarter"]
    codes = [str(item["code"]) for item in payload["state"]["members"]]
    assert member in codes
    # listing a family is still not pricing it: no response field carries money as
    # the position's price
    assert "price" not in payload
