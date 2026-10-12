"""Unknown normative consumption must never close a calculated document as zero."""
from copy import deepcopy
import json
import sqlite3

import openpyxl
import pandas as pd
import pytest

from proxy.services import gesn_service as gs, rim_lsr_trace_service as rim
from proxy.services.fgis_price_service import PriceBook
from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx
from proxy.smeta_core.norm_browser import read_norm_card_exact
from tests.lsr_citation_support import cited_snapshot, issued_norm_metadata
from tools.build_smeta_structured_base import build_structured_base


CODE = "ГЭСН01-01-001-01"
KEY = "ГЭСН:01-01-001-01"
CASES = [(None, None), (0, 0.0), (float("nan"), None), (float("inf"), None),
         ("invalid", None), ("0.00", 0.0), ("0,00", 0.0), (1.5, 1.5)]


def norm_fixture(value, *, kind="material"):
    return {"code": CODE, "key": KEY, "name": "Synthetic operation", "unit": "m",
            "work_steps": ["Synthetic source composition"], "resources": [
                {"kind": kind, "code": "UNKNOWN", "name": "Tested source resource", "unit": "m", "per_unit": value},
                {"kind": "material", "code": "KNOWN", "name": "Known source resource", "unit": "m", "per_unit": 1},
            ]}


def calculate(monkeypatch, norm, *, confirmed_data=None):
    issued = issued_norm_metadata(norm, synthetic=True)
    norm = deepcopy(norm)
    norm["_source_sha256"] = issued["normative_base_sha256"]

    def lookup(code, **kwargs):
        assert code == CODE
        if kwargs.get("expected_base_sha256"):
            assert kwargs["expected_base_sha256"] == issued["normative_base_sha256"]
        return deepcopy(norm)

    monkeypatch.setattr(gs, "get_norm", lookup)
    monkeypatch.setattr(rim.nr_sp_service, "resolve", lambda *args, **kwargs:
        {"status": "resolved_fixture", "nr_pct": 0, "sp_pct": 0, "basis": "Synthetic explicit rates"})
    book = PriceBook([{"code": code, "unit": "m", "price_current": 10}
                      for code in ("UNKNOWN", "KNOWN")], region="synthetic", quarter="2026Q3")
    row = {"source_row": "Synthetic!R2", "operation_id": "synthetic-operation", "row_role": "work",
           "title": norm["name"], "unit": "m", "quantity": 2, "norm_code": CODE, "norm_status": "EXACT",
           "action_match": "yes", "object_match": "yes", "condition_match": "yes",
           "unit_compatible": "yes", "composition_covers": "yes", "coverage": "Synthetic whole composition",
           "resource_review": {"status": "keep_all_confirmed", "reason": "Synthetic model review"}}
    row = cited_snapshot(row, norm=norm, synthetic=True)
    row["_evidence_check"]["card_body_shown"] = True
    return rim.build_lsr_trace_from_visible_rows([row], pricebook=book, confirmed_data=confirmed_data)


@pytest.mark.parametrize("value,expected", CASES)
@pytest.mark.parametrize("kind", ["material", "labor"])
def test_unknown_consumption_cannot_be_confirmed_money_or_an_excel_zero(monkeypatch, tmp_path, value, expected, kind):
    trace = calculate(monkeypatch, norm_fixture(value, kind=kind))
    position = trace["sections"][0]["positions"][0]
    resource = next(row for row in position["rows"] if row["columns"].get("2") == "UNKNOWN")
    assert resource["columns"].get("5") == expected
    assert resource["columns"].get("7") == (None if expected is None else expected * 2)
    assert resource["columns"].get("12") == (None if expected is None else expected * 20)
    summary = trace["summary"]
    known = 20 + (0 if expected is None else expected * 20)
    assert summary["known_amount"] == known
    assert position["summary"]["amount_status"] == ("partial" if expected is None else "complete")
    assert summary["result_status"] == ("priced_partial" if expected is None else "priced_final")
    assert summary["full_amount"] == (None if expected is None else known)
    assert summary["confirmed_amount"] == (0 if expected is None else known)
    assert summary["preliminary_amount"] == (known if expected is None else 0)
    assert ("quantity_missing:UNKNOWN" in position["summary"]["completeness_reasons"]) is (expected is None)
    if kind == "labor":
        assert summary["labor_qty"] == (None if expected is None else expected * 2)
    # The immutable input snapshot retains the fixture's authored raw value;
    # every computed number exposed to the workbook must be finite or null.
    json.dumps({"sections": trace["sections"], "summary": summary,
                "resources": trace["row_bindings"][0]["resource_decisions"]}, allow_nan=False)

    path = render_lsr_xlsx(trace, tmp_path / "quantity with spaces.xlsx")
    workbook = openpyxl.load_workbook(path, data_only=False)
    rows = [row for row in workbook.worksheets[0] if row[1].value == "UNKNOWN"]
    assert len(rows) == 1
    exported = rows[0]
    assert exported[4].value == expected
    assert exported[6].value == (None if expected is None else expected * 2)
    if expected is None:
        assert exported[11].value is None
        body = " ".join(str(cell.value or "") for sheet in workbook for row in sheet for cell in row)
        assert "неизвестный расход" in body
        if kind == "labor":
            total = next(row for row in workbook.worksheets[0] if row[2].value == "ОТ(ЗТ)")
            assert total[6].value is None
    else:
        assert str(exported[11].value).startswith("=ROUND(")
    workbook.close()


@pytest.mark.parametrize("value,expected", CASES)
def test_new_import_preserves_unknown_and_zero_through_sqlite_typed_card_and_expansion(tmp_path, monkeypatch, value, expected):
    records = [{"norm_key": KEY, "norm_code": CODE, "base_type": "ГЭСН",
                "norm_name": "Synthetic operation", "norm_unit": "m",
                "work_steps": json.dumps(["Synthetic source composition"]),
                "kind": "material", "resource_code": code, "resource_name": code,
                "resource_unit": "m", "per_unit": None if amount is None else str(amount),
                "price": None, "source_doc": "Synthetic source", "source_guid": "synthetic-guid"}
               for code, amount in (("UNKNOWN", value), ("KNOWN", 1))]
    source = tmp_path / "source input.parquet"
    pd.DataFrame(records).to_parquet(source, index=False)
    database = tmp_path / "norm base.sqlite"
    build_structured_base(source=source, out=database, manifest_out=tmp_path / "manifest.json")
    with sqlite3.connect(database) as connection:
        stored, = connection.execute("SELECT per_unit FROM resources WHERE resource_code='UNKNOWN'").fetchone()
    assert stored == expected
    card = read_norm_card_exact(norm_key=KEY, base_path=database)["card"]
    assert next(row for row in card["resources"] if row["code"] == "UNKNOWN")["per_unit"] == expected
    assert card["resource_consumption_known"] is (expected is not None)
    norm = gs.load_structured_base_norms(str(database))[KEY]
    assert next(row for row in norm["resources"] if row["code"] == "UNKNOWN")["per_unit"] == expected
    monkeypatch.setattr(gs, "get_norm", lambda *_args, **_kwargs: deepcopy(norm))
    expanded = gs.expand_position(CODE, 2)
    assert next(row for row in expanded if row["code"] == "UNKNOWN")["qty"] == (None if expected is None else expected * 2)
    json.dumps(expanded, allow_nan=False)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf")])
def test_explicit_resource_without_quantity_is_not_backfilled_with_zero(monkeypatch, value):
    monkeypatch.setattr(rim.nr_sp_service, "resolve", lambda *args, **kwargs: {})
    book = PriceBook([{"code": "UNKNOWN", "unit": "m", "price_current": 10}])
    trace = rim.build_position_trace({"name": "Synthetic manual", "qty": 2, "nr_pct": 0, "sp_pct": 0,
        "resources": [{"kind": "material", "code": "UNKNOWN", "unit": "m", "per_unit": value}]}, pricebook=book)
    row = next(row for row in trace["rows"] if row["columns"].get("2") == "UNKNOWN")
    assert row["columns"].get("7") is None and row["columns"].get("12") is None
    assert trace["summary"]["amount_status"] == "partial"
    assert "quantity_missing:UNKNOWN" in trace["summary"]["completeness_reasons"]
    json.dumps(trace, allow_nan=False)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), float("-inf"), "invalid"])
def test_typed_reader_reports_legacy_unknown_consumption_without_rewriting_database(tmp_path, value):
    from tests.test_smeta_norm_browser import _base
    path = tmp_path / "legacy source.sqlite"
    with _base(path) as connection:
        connection.execute("ALTER TABLE resources ADD COLUMN per_unit REAL")
        connection.execute("INSERT INTO norms VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            KEY, "fixture-id", "FSNB-2022", CODE, "ГЭСН", "01-01-001-01", "Synthetic norm", "m",
            '["Synthetic work"]', "Synthetic source", "synthetic-guid", 1, '["material"]'))
        connection.execute("INSERT INTO resources VALUES (?,?,?,?,?,?,?)", (
            "fixture-id", KEY, "material", "UNKNOWN", "Synthetic material", "m", value))
    original = path.read_bytes()
    card = read_norm_card_exact(norm_key=KEY, base_path=path)["card"]
    assert card["resources"][0]["per_unit"] is None
    assert card["resource_consumption_known"] is False
    assert card["resources_complete"] is False
    json.dumps(card, allow_nan=False)
    assert path.read_bytes() == original


def test_unknown_and_zero_resources_with_same_code_are_not_deduplicated():
    rows = [{"code": "SAME", "kind": "material", "unit": "m", "per_unit": value}
            for value in (None, 0, "invalid")]
    kept, dropped = gs._dedupe_resources(rows)
    assert kept == rows and dropped == 0


@pytest.mark.parametrize("supplied_qty", [0, 4])
def test_explicit_total_quantity_can_supply_a_known_consumption(monkeypatch, supplied_qty):
    monkeypatch.setattr(rim.nr_sp_service, "resolve", lambda *args, **kwargs: {})
    trace = rim.build_position_trace({"name": "Synthetic manual", "qty": 2, "nr_pct": 0, "sp_pct": 0,
        "resources": [{"kind": "material", "code": "KNOWN", "unit": "m", "qty": supplied_qty}]},
        pricebook=PriceBook([{"code": "KNOWN", "unit": "m", "price_current": 10}]))
    row = next(row for row in trace["rows"] if row["columns"].get("2") == "KNOWN")
    assert row["columns"]["5"] == supplied_qty / 2
    assert row["columns"]["7"] == supplied_qty
    assert row["columns"]["12"] == supplied_qty * 10
    assert trace["summary"]["amount_status"] == "complete"


def test_confirmed_position_price_cannot_hide_unknown_resource_quantity(monkeypatch):
    monkeypatch.setattr(rim.nr_sp_service, "resolve", lambda *args, **kwargs: {})
    trace = rim.build_position_trace({"name": "Synthetic manual", "qty": 2, "nr_pct": 0, "sp_pct": 0,
        "confirmed_price": 100,
        "resources": [{"kind": "material", "code": "UNKNOWN", "unit": "m", "per_unit": None}]},
        pricebook=PriceBook([{"code": "UNKNOWN", "unit": "m", "price_current": 10}]))
    assert trace["summary"]["amount_status"] == "partial"
    assert trace["summary"]["full_amount"] is None
    assert trace["summary"]["known_amount"] == 200
    visible = calculate(monkeypatch, norm_fixture(None), confirmed_data={
        "Synthetic!R2": {"confirmed_price": 100, "price_source": "operator"}})
    assert visible["summary"]["result_status"] == "priced_partial"
    assert visible["summary"]["confirmed_amount"] == 0
    assert visible["summary"]["preliminary_amount"] == 200


@pytest.mark.parametrize("value,reason", [(1e308, "quantity_missing:UNKNOWN"), (1e307, "resource_amount_nonfinite:UNKNOWN")])
def test_resource_multiplication_overflow_remains_a_partial_document(monkeypatch, tmp_path, value, reason):
    trace = calculate(monkeypatch, norm_fixture(value))
    position = trace["sections"][0]["positions"][0]
    assert reason in position["summary"]["completeness_reasons"]
    assert trace["summary"]["result_status"] == "priced_partial"
    assert trace["summary"]["confirmed_amount"] == 0
    assert trace["summary"]["known_amount"] == 20
    json.dumps(trace, allow_nan=False)
    path = render_lsr_xlsx(trace, tmp_path / "overflow.xlsx")
    workbook = openpyxl.load_workbook(path, data_only=False)
    try:
        row = next(row for row in workbook.worksheets[0] if row[1].value == "UNKNOWN")
        assert row[11].value is None
    finally:
        workbook.close()
