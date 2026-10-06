"""Book prices are converted to the resource unit, never resource quantities."""

from copy import deepcopy
import math

import pytest

from proxy.services import lsr_assembly_service as assembly
from proxy.services import rim_lsr_trace_service as rim


class Book:
    region = "Test region"
    quarter = "Test quarter"
    source_name = "chosen.parquet"
    source_sha256 = "chosen-snapshot-sha"

    def __init__(self, record):
        self.record = record

    def lookup(self, code):
        assert code == "14.4.01.01-0003"
        return self.record


def calculate_both(record, resource_unit, quantity, **resource_fields):
    original = deepcopy(record)
    resource = {"kind": "material", "code": "14.4.01.01-0003", "name": "Primer",
                "unit": resource_unit, **resource_fields}
    position = {"name": "Authored work", "qty": 1, "nr_pct": 0, "sp_pct": 0}
    traced = rim.build_position_trace(
        {**position, "resources": [{**resource, "per_unit": quantity}]}, pricebook=Book(record))
    assembled = assembly.compute_position(
        {**position, "resources": [{**resource, "qty": quantity}]}, pricebook=Book(record))
    assert record == original
    trace_row = next(row for row in traced["rows"] if row["type"] == "resource_material")
    assert trace_row["columns"]["7"] == quantity
    assert trace_row["columns"]["4"] == resource_unit
    assert assembled["resources"][0]["qty"] == quantity
    assert assembled["resources"][0]["unit"] == resource_unit
    return traced, trace_row, assembled


@pytest.mark.parametrize("book_unit,resource_unit,quantity,book_price,unit_price,total", [
    ("кг", "т", .002, 10, 10000, 20),
    ("т", "кг", 2, 10000, 10, 20),
    ("м", "км", .002, 10, 10000, 20),
    ("км", "м", 2, 10000, 10, 20),
])
def test_exact_si_resource_price_is_not_a_thousandfold_undercharge(
    book_unit, resource_unit, quantity, book_price, unit_price, total,
):
    record = {"unit": book_unit, "price_current": book_price,
              "price_current_eff": book_price, "source_ref": "chosen-book#row=primer"}
    traced, row, assembled = calculate_both(record, resource_unit, quantity)
    assert row["columns"].get("10") == unit_price
    assert row["columns"]["12"] == total
    assert traced["summary"]["total"] == assembled["total"] == total
    assert assembled["resources"][0]["price_used"] == unit_price
    assert assembled["price_requirements"] == []
    factor = unit_price / book_price
    for conversion in (row["meta"]["price_unit_conversion"],
                       assembled["resources"][0]["price_unit_conversion"]):
        assert conversion["book_unit"] == book_unit
        assert conversion["resource_unit"] == resource_unit
        assert conversion["conversion_factor"] == factor
        assert conversion["price_owner"] == "chosen_pricebook"
        assert conversion["source_ref"] == "chosen-book#row=primer"
        assert conversion["resource_code"] == "14.4.01.01-0003"
        assert conversion["book_source_name"] == "chosen.parquet"
        assert conversion["book_source_sha256"] == "chosen-snapshot-sha"
        assert conversion["region"] == "Test region"
        assert conversion["quarter"] == "Test quarter"
        assert f"{factor:g}" in conversion["formula"]
    assert row["source"] == "fgis_current"


@pytest.mark.parametrize("price_fields,expected,source", [
    ({"price_current": 2.34567, "price_current_eff": 99}, 2345.67, "fgis_current"),
    ({"price_base": 2.34567, "index": 1.2, "price_current_eff": 2.814804}, 2814.80, "fgis_base_index"),
    ({"price_current_eff": 2.34567}, 2345.67, "fgis_effective"),
])
def test_si_conversion_scales_raw_price_once_before_currency_rounding(price_fields, expected, source):
    traced, row, assembled = calculate_both({"unit": "кг", **price_fields}, "т", 1)
    assert row["columns"].get("10") == expected
    assert row["source"] == source
    assert traced["summary"]["total"] == assembled["total"] == expected
    if "index" in price_fields:
        assert row["columns"]["8"] == 2345.67
        assert row["columns"]["9"] == 1.2


@pytest.mark.parametrize("book_unit,resource_unit", [
    ("кг", "л"), ("шт", "кг"), ("м3", "100 м3"), ("кг", "100 т"),
    ("труб", "кг"), ("кг", "транспорт"), ("км", "м кабеля"),
])
def test_non_si_or_bulk_resource_units_remain_rejected(book_unit, resource_unit):
    traced, row, assembled = calculate_both(
        {"unit": book_unit, "price_current": 10, "price_current_eff": 10}, resource_unit, 1)
    assert row["columns"].get("10") is None
    assert assembled["resources"][0]["price_used"] is None
    assert assembled["price_requirements"][0]["action"] == "book_unit_conflict"
    assert "price_unit_conversion" not in row["meta"]


@pytest.mark.parametrize("price,fields", [
    (5, {"price_confirmed": True}),
    (0, {"price_source_ref": "engineer#reuse", "resource_binding": {"action": "reuse"}}),
])
def test_owned_manual_and_reuse_prices_are_not_converted(price, fields):
    traced, row, assembled = calculate_both(
        {"unit": "кг", "price_current": 10, "price_current_eff": 10}, "т", 2,
        price=price, **fields)
    assert row["columns"]["10"] == price
    assert assembled["resources"][0]["price_used"] == price
    assert traced["summary"]["total"] == assembled["total"] == 2 * price
    assert "price_unit_conversion" not in row["meta"]
    assert "price_unit_conversion" not in assembled["resources"][0]


def test_supply_callers_without_price_conversion_keep_the_strict_unit_guard():
    assert rim.book_price_unit_conflict("кг", "т") == "кг"
    assert rim.book_price_unit_conflict("м", "км") == "м"
    assert rim.book_price_unit_conflict("м3", "100 м3") == "м3"


def test_assembly_refuses_a_book_candidate_whose_conversion_keeps_the_wrong_unit(monkeypatch):
    record = {"unit": "кг", "price_current_eff": 10}
    monkeypatch.setattr(assembly, "convert_book_price_unit", lambda rec, *args, **kwargs: (
        rec, {"resource_current_price": 10000}))
    result = assembly.compute_position(
        {"name": "Authored work", "qty": 1, "nr_pct": 0, "sp_pct": 0,
         "resources": [{"kind": "material", "code": "14.4.01.01-0003", "name": "Primer",
                        "unit": "т", "qty": .002}]}, pricebook=Book(record))
    assert result["total"] == 0
    assert result["resources"][0]["price_used"] is None
    assert result["price_requirements"][0]["action"] == "book_unit_conflict"
    assert "price_unit_conversion" not in result["resources"][0]


def test_visible_unit_quote_caller_does_not_accept_si_factor_without_applying_it(monkeypatch):
    monkeypatch.setattr(rim.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "code": "ГЭСН01-01-001-01", "name": "Authored work", "unit": "т", "resources": [],
    })
    row = {"source_row": "S!R2", "row_role": "work", "title": "Authored work",
           "norm_code": "ГЭСН01-01-001-01", "norm_status": "EXACT", "unit": "т", "quantity": 1,
           "confirmed_price": 10, "price_kind": "unit_price", "price_unit": "кг",
           "price_source": "commercial-quote", "evidence_refs": ["Q1.H1"],
           "evidence_bindings": {"Q1.H1": "authored-quote"}}
    original = deepcopy(row)
    position = rim.positions_from_visible_lsr_rows([row])["positions"][0]
    assert position["confirmed_price"] == 10
    assert position["confirmed_price_attributed"] is False
    assert position["confirmed_price_issue"] == "position_price_unit_conflict"
    assert row == original


def test_conversion_preserves_book_values_index_and_snapshot_source():
    record = {"unit": "кг", "price_base": 2.34567, "index": 1.2,
              "price_current_eff": 2.814804}
    original = deepcopy(record)
    converted, trace = rim.convert_book_price_unit(
        record, "т", resource_code="14.4.01.01-0003", pricebook=Book(record))
    assert record == original
    assert converted["price_base"] == pytest.approx(2345.67)
    assert converted["price_current_eff"] == pytest.approx(2814.804)
    assert converted["index"] == original["index"]
    assert trace["source_ref"] == (
        "pricebook:chosen.parquet#sha256=chosen-snapshot-sha&code=14.4.01.01-0003")


@pytest.mark.parametrize("book_unit,resource_unit", [
    ("1 кг", "1 т"), ("kg", "t"), ("м.", "км."), ("метр", "километр"),
])
def test_single_explicit_si_aliases_have_the_same_conversion(book_unit, resource_unit):
    _, row, assembled = calculate_both(
        {"unit": book_unit, "price_current_eff": 10}, resource_unit, .002)
    assert row["columns"]["10"] == assembled["resources"][0]["price_used"] == 10000
    assert row["columns"]["12"] == assembled["total"] == 20


@pytest.mark.parametrize("record", [
    {"unit": "кг"}, {"unit": "кг", "price_base": 10},
    {"unit": "кг", "price_current": 10, "price_conflict": {"code": "AMBIGUOUS_PRICE_RECORD"}},
])
def test_no_usable_price_or_ambiguous_book_cannot_acquire_a_conversion(record):
    unchanged, trace = rim.convert_book_price_unit(record, "т", resource_code="14.4.01.01-0003")
    assert unchanged is record
    assert trace is None


@pytest.mark.parametrize("price_fields", [
    {"price_current": 1e308, "price_current_eff": 1e308},
    {"price_base": 1e308, "index": 1, "price_current_eff": 1e308},
    {"price_current_eff": 1e308},
    {"price_base": 1e305, "index": 10, "price_current_eff": 1e306},
])
def test_finite_book_price_that_overflows_conversion_remains_a_unit_gap(price_fields):
    record = {"unit": "кг", **price_fields}
    unchanged, conversion = rim.convert_book_price_unit(record, "т", pricebook=Book(record))
    assert unchanged is record
    assert conversion is None
    traced, row, assembled = calculate_both(record, "т", 1)
    assert row["columns"].get("10") is None
    assert traced["summary"]["total"] == assembled["total"] == 0
    assert assembled["price_requirements"][0]["action"] == "book_unit_conflict"


def test_huge_finite_converted_price_is_kept_when_it_does_not_overflow():
    record = {"unit": "кг", "price_current": 1e290, "price_current_eff": 1e290}
    traced, row, assembled = calculate_both(record, "т", 1)
    assert math.isfinite(row["columns"]["10"])
    assert row["columns"]["10"] == pytest.approx(1e293)
    assert traced["summary"]["total"] == assembled["total"]


def test_rim_work_coverage_resolves_trusted_parent_alias_without_rewriting_rows(monkeypatch):
    from proxy.services.attachment_source_catalog_service import AttachmentSourceCatalog, CatalogRow
    from proxy.services.lsr_source_coverage_service import operation_identity

    catalog = AttachmentSourceCatalog(
        original_name="authored.pdf", sheets=(("PDF", 2),), source_file_id="src_actual",
        rows=tuple(CatalogRow(locator=f"PDF!R{number}", sheet="PDF", excel_row=number,
                              values=("Authored work",), line=f"PDF!R{number}: Authored work",
                              numbers=(), row_classification="ambiguous") for number in (2, 3)),
    )
    monkeypatch.setattr(rim.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "code": "ГЭСН01-01-001-01", "name": "Authored work", "unit": "м",
        "resources": [], "nr": 0, "sp": 0,
    })
    parent = {"source_row": "PDF!R2", "row_role": "work", "title": "Authored work",
              "norm_code": "ГЭСН01-01-001-01", "norm_status": "EXACT", "unit": "м", "quantity": 1,
              "evidence_refs": ["Q1.H1"], "evidence_bindings": {"Q1.H1": "actual-card"}}
    child = {**parent, "source_row": "src_actual!R3", "covered_by_work_id": "src_actual!R2",
             "coverage": "The cited combined work includes this operation"}
    rows = [parent, child]
    original = deepcopy(rows)
    identities = [operation_identity(row) for row in rows]
    trace = rim.build_lsr_trace_from_visible_rows(rows, source_catalog=catalog)
    assert trace["summary"]["positions_built"] == 1
    assert trace["row_bindings"][1]["status"] == "covered"
    assert trace["row_bindings"][1]["covered_by_work_id"] == "PDF!R2"
    assert trace["row_bindings"][1]["covered_by_operation_id"] == identities[0]
    assert rows == original
    assert [operation_identity(row) for row in rows] == identities
    child["covered_by_work_id"] = "src_foreign!R2"
    child["_catalog_source_locator"] = "PDF!R2"
    rejected = rim.positions_from_visible_lsr_rows(rows, source_catalog=catalog)
    assert rejected["row_bindings"][1]["coverage_error"] == "coverage_target_missing"


def _mixed_parent_catalog_and_work(monkeypatch, parent_locator):
    from proxy.services.attachment_source_catalog_service import AttachmentSourceCatalog, CatalogRow
    from tests.test_rim_lsr_trace_service import _active_resource_norm

    catalog = AttachmentSourceCatalog(
        original_name="authored.pdf", sheets=(("PDF", 3),), source_file_id="src_actual",
        rows=tuple(CatalogRow(locator=f"PDF!R{number}", sheet="PDF", excel_row=number,
                              values=("Authored item",), line=f"PDF!R{number}: Authored item",
                              numbers=(), row_classification="ambiguous") for number in (2, 3, 4)),
    )
    return catalog, {**_active_resource_norm(monkeypatch), "source_row": parent_locator}


@pytest.mark.parametrize("parent_locator,child_prefix", [("PDF!R2", "src_actual"), ("src_actual!R2", "PDF")])
def test_material_parent_alias_reaches_overlap_check_without_rewriting_identity(
    monkeypatch, parent_locator, child_prefix,
):
    from proxy.services.lsr_source_coverage_service import operation_identity

    catalog, parent = _mixed_parent_catalog_and_work(monkeypatch, parent_locator)
    supply = {"source_row": f"{child_prefix}!R3", "row_role": "material", "work_row": f"{child_prefix}!R2",
              "resource_code": "A-1", "title": "Separate supply", "unit": "m", "quantity": 20}
    rows = [parent, supply]
    original = deepcopy(rows)
    identity = operation_identity(parent)
    trace = rim.build_lsr_trace_from_visible_rows(rows, source_catalog=catalog)
    work = trace["row_bindings"][0]
    overlap = next(item for item in work.get("resource_binding_conflicts", [])
                   if item["code"] == "separate_supply_possible_overlap")
    assert overlap["linked_supply_rows"] == [{"source_row": supply["source_row"], "resource_code": "A-1"}]
    assert overlap["parent_ambiguous"] is False
    assert {item["code"] for item in work["resource_decisions"]} == {"A-1", "A-10"}
    assert rows == original
    assert operation_identity(parent) == identity


@pytest.mark.parametrize("parent_locator,child_prefix", [("PDF!R2", "src_actual"), ("src_actual!R2", "PDF")])
def test_resource_parent_alias_applies_only_its_authored_action_without_rewriting_rows(
    monkeypatch, parent_locator, child_prefix,
):
    catalog, parent = _mixed_parent_catalog_and_work(monkeypatch, parent_locator)
    resource = {"source_row": f"{child_prefix}!R4", "row_role": "resource", "work_row": "R2",
                "resource_bindings": [{"action": "reuse", "target_resource_code": "A-1",
                                       "reason": "Authored reuse", "source_refs": [f"{child_prefix}!R4"]}]}
    rows = [parent, resource]
    original = deepcopy(rows)
    trace = rim.build_lsr_trace_from_visible_rows(rows, source_catalog=catalog)
    assert trace["row_bindings"][1]["status"] == "resource_linked"
    work = trace["row_bindings"][0]
    reused = next(item for item in work["resource_decisions"] if item["code"] == "A-1")
    assert (reused["per_unit"], reused["qty"], reused["price"]) == (2, 20, 0)
    assert work["resource_binding_audit"][0]["status"] == "applied"
    assert work["resource_binding_audit"][0]["source_row"] == resource["source_row"]
    assert rows == original


def test_parent_catalog_alias_cannot_choose_between_multiple_authored_works(monkeypatch):
    catalog, parent = _mixed_parent_catalog_and_work(monkeypatch, "PDF!R2")
    other = {**parent, "source_row": "src_actual!R2", "operation_id": "second"}
    supply = {"source_row": "src_actual!R3", "row_role": "material", "work_row": "src_actual!R2",
              "resource_code": "A-1", "title": "Separate supply", "unit": "m", "quantity": 20}
    resource = {"source_row": "PDF!R4", "row_role": "resource", "work_row": "src_actual!R2",
                "resource_bindings": [{"action": "reuse", "target_resource_code": "A-1",
                                       "reason": "Authored reuse", "source_refs": ["PDF!R4"]}]}
    rows = [parent, other, supply, resource]
    original = deepcopy(rows)
    bound = rim.positions_from_visible_lsr_rows(rows, source_catalog=catalog)
    assert bound["row_bindings"][3]["status"] == "resource_link_conflict"
    for work in bound["row_bindings"][:2]:
        overlap = next(item for item in work.get("resource_binding_conflicts", [])
                       if item["code"] == "separate_supply_possible_overlap")
        assert overlap["parent_ambiguous"] is True
    assert rows == original
    # An authored operation ID, in contrast, identifies the intended operation.
    resource["work_row"] = "second"
    assert rim.positions_from_visible_lsr_rows(rows, source_catalog=catalog)["row_bindings"][3]["status"] == "resource_linked"


def test_foreign_resource_parent_and_forged_catalog_field_do_not_attach_an_action(monkeypatch):
    catalog, parent = _mixed_parent_catalog_and_work(monkeypatch, "PDF!R2")
    resource = {"source_row": "PDF!R4", "row_role": "resource", "work_row": "src_foreign!R2",
                "_catalog_source_locator": "PDF!R2",
                "resource_bindings": [{"action": "reuse", "target_resource_code": "A-1",
                                       "reason": "Authored reuse", "source_refs": ["PDF!R4"]}]}
    rows = [parent, resource]
    original = deepcopy(rows)
    bound = rim.positions_from_visible_lsr_rows(rows, source_catalog=catalog)
    assert bound["row_bindings"][1]["status"] == "resource_link_conflict"
    assert "resource_bindings" not in bound["positions"][0]
    assert rows == original
