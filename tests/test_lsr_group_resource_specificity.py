"""§ 11 № 5 / § 7: a group resource is specified by its characteristics, never priced by its first member.

The estimate engine may only bind a price to a *concrete* resource code.  A group
address (``01.1.01.01``) has several members with different prices, so taking any
of them would silently reprice the estimate — the exact shortcut this regression
forbids.  These tests are mechanical proofs over a synthetic price book: no live
FGIS file, no model, no invented number.
"""

from proxy.services.fgis_price_service import PriceBook
from proxy.services.lsr_assembly_service import _price_requirement, _resource_price

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

    assert (price, source) == (None, "missing")
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
    assert _resource_price({**concrete, "code": GROUP}, book, {}) == (None, "missing")
    # a prefix of a member is still not that member
    assert _resource_price({**concrete, "code": "01.1.01"}, book, {}) == (None, "missing")


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
