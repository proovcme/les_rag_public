"""Exact resource identity must not conceal contradictory price records."""

import pytest
from types import SimpleNamespace

from proxy.services.fgis_price_service import PriceBook
from proxy.services.lsr_assembly_service import _resource_price
from proxy.services.model_pricebook_evidence_service import PriceBookEvidenceSource, read_pricebook_evidence
from proxy.services.model_price_provenance_service import price_evidence_check
from proxy.services.rim_lsr_trace_service import _resolve_price_trace


ROW = {"code": "01.1.01.01-0001", "name": "Exact material", "unit": "m",
       "price_current": 100, "price_current_eff": 100}


@pytest.mark.parametrize("change", [{"price_current": 200, "price_current_eff": 200},
    {"unit": "kg"}, {"name": "Different resource"}, {"index": 2}])
def test_different_exact_records_do_not_select_the_first_price(change):
    for rows in ([ROW, {**ROW, **change}], [{**ROW, **change}, ROW]):
        book = PriceBook(rows)
        assert book.price(ROW["code"]) is None
        conflict = book.lookup(ROW["code"])["price_conflict"]
        assert conflict["code"] == "AMBIGUOUS_PRICE_RECORD"
        assert conflict["evidence_count"] == 2
        assert len(conflict["records"]) == 2


def test_identical_duplicates_and_a_published_zero_are_valid():
    row = {**ROW, "price_current": 0, "price_current_eff": 0}
    assert PriceBook([row, dict(row)]).price(ROW["code"]) == 0
    assert PriceBook([ROW, {**ROW, "code": "FSBC-" + ROW["code"]}]).price(ROW["code"]) == 100


def test_conflict_retains_identical_rows_that_preceded_the_different_one():
    book = PriceBook([ROW, dict(ROW), {**ROW, "price_current": 200}, dict(ROW)])
    assert book.lookup(ROW["code"])["price_conflict"]["evidence_count"] == 4


def test_record_from_another_period_cannot_hide_inside_chosen_book():
    book = PriceBook([{**ROW, "region": "Region", "quarter": "2 kv. 2026"}],
                     region="Region", quarter="3 kv. 2026")
    assert book.price(ROW["code"]) is None
    assert book.lookup(ROW["code"])["price_conflict"]["code"] == "PRICE_RECORD_BASIS_CONFLICT"


def test_both_calculators_keep_the_conflict_and_do_not_use_a_card_rate_instead():
    book = PriceBook([ROW, {**ROW, "price_current": 200}])
    resource = {"code": ROW["code"], "name": ROW["name"], "unit": "m", "kind": "material",
                "price": 77, "price_origin": "norm_card"}
    trace = _resolve_price_trace(resource, pricebook=book)
    assert trace.price is None
    assert trace.action == "ambiguous_price_record"
    assert trace.column_10 is None
    price, origin = _resource_price(resource, book, {})
    assert price is None
    assert origin == "ambiguous_price_record"


def test_exact_price_read_reports_a_conflict_instead_of_a_missing_source():
    book = PriceBook([ROW, {**ROW, "price_current": 200}], region="Region", quarter="3 kv. 2026")
    source = PriceBookEvidenceSource(book, "a" * 64, "source.parquet", 100)
    result = read_pricebook_evidence("read_pricebook_resource", {"code": ROW["code"]},
        price_basis={"pricebook": "book", "region": "Region", "quarter": "3 kv. 2026"},
        pricebook_provider=lambda name: source)
    assert result["status"] == "conflict"
    assert result["trace"]["price_conflict"]["code"] == "AMBIGUOUS_PRICE_RECORD"


@pytest.mark.parametrize("conflicting", [False, True])
def test_price_search_cannot_certify_a_base_price_or_a_conflicting_row_as_current(conflicting):
    row = {**ROW, "price_base": 100, "index": 2, "price_current": 200, "price_current_eff": 200}
    rows = [row, {**row, "price_current": 100}] if conflicting else [row]
    book = PriceBook(rows, region="Region", quarter="3 kv. 2026")
    source = PriceBookEvidenceSource(book, "a" * 64, "source.parquet", 100)
    result = read_pricebook_evidence("search_pricebook_resources", {"q": "Exact material"},
        price_basis={"pricebook": "book", "region": "Region", "quarter": "3 kv. 2026"},
        pricebook_provider=lambda name: source)
    hit = result["result"]["hits"][0]
    chunk = SimpleNamespace(**hit)
    proposal = {"confirmed_price": 100, "price_unit": "m", "price_source": hit["meta"]["source_ref"],
                "evidence_refs": ["Q1.H1"]}
    check = price_evidence_check(proposal, [chunk], {"Q1.H1": hit["meta"]["global_evidence_id"]})
    assert check["price_in_refs"] is False


@pytest.mark.parametrize("components,expected", [
    ({"price_current": 200, "price_base": 100, "index": 3}, 200),
    ({"price_current": None, "price_base": 100, "index": 2}, 200),
    ({"price_current": 0, "price_base": 100, "index": 2}, 0),
])
def test_current_quote_is_confirmable_and_never_indexed_twice(components, expected):
    book = PriceBook([{**ROW, **components}], region="Region", quarter="3 kv. 2026")
    source = PriceBookEvidenceSource(book, "a" * 64, "source.parquet", 100)
    result = read_pricebook_evidence("read_pricebook_resource", {"code": ROW["code"]},
        price_basis={"pricebook": "book", "region": "Region", "quarter": "3 kv. 2026"},
        pricebook_provider=lambda name: source)
    hit = result["result"]["hits"][0]
    assert hit["meta"]["price_evidence"]["confirmed_price"] == expected
    check = price_evidence_check({"confirmed_price": expected, "price_unit": "m",
        "price_source": hit["meta"]["source_ref"], "evidence_refs": ["Q1.H1"]},
        [SimpleNamespace(**hit)], {"Q1.H1": hit["meta"]["global_evidence_id"]})
    assert check["price_in_refs"] and check["unit_in_refs"] and check["source_in_refs"]
