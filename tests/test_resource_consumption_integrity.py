"""Unknown source consumption must survive the actual SQLite/RIM/XLSX paths."""

import json
import sqlite3

import pandas as pd
import pytest
from openpyxl import load_workbook

from proxy.services import gesn_service
from proxy.services.lsr_workbook_adapter_service import collect_lsr_workbook_gaps
from proxy.services.rim_lsr_trace_service import build_lsr_trace, build_position_trace
from proxy.services.rim_trace_xlsx_service import render_trace_xlsx
from proxy.smeta_core.norm_browser import read_norm_card_exact
from tools.build_smeta_structured_base import build_structured_base


class Book:
    def lookup(self, code):
        return {"price_current": 10, "unit": "кг"}


def resource(consumption, *, code="R1", name="Material"):
    return {"kind": "material", "code": code, "name": name,
            "unit": "кг", "per_unit": consumption}


def position(resources):
    return {"name": "Authored work", "unit": "шт", "qty": 2,
            "nr_pct": 0, "sp_pct": 0, "resources": resources}


@pytest.mark.parametrize("consumption", [None, "", "П", "bad", float("nan"), float("inf"), -1, True])
def test_unknown_consumption_never_becomes_completed_zero(consumption, tmp_path):
    original = position([resource(consumption), resource(1, code="R2", name="Known")])
    trace = build_position_trace(original, pricebook=Book())
    unknown = trace["summary"]["resource_decisions"][0]
    assert unknown["per_unit"] is None
    assert unknown["qty"] is None
    assert unknown["cost"] is None
    assert trace["summary"]["full_amount"] is None
    assert "resource_quantity_missing:R1" in trace["summary"]["completeness_reasons"]
    assert trace["summary"]["total"] == 20  # the genuinely known part remains usable
    assert original["resources"][0]["per_unit"] is consumption
    lsr = build_lsr_trace([original], pricebook=Book())
    assert "resource_quantity_missing:R1" in collect_lsr_workbook_gaps(lsr)
    output = render_trace_xlsx(trace, tmp_path / "unknown.xlsx")
    for data_only in (False, True):
        workbook = load_workbook(output, data_only=data_only)
        sheet = workbook.worksheets[0]
        row = next(row for row in sheet if row[2].value == "Material")
        assert [row[index].value for index in (4, 6, 11)] == [None, None, None]
        workbook.close()


@pytest.mark.parametrize("consumption", [0, "0", "0,0", 1.25, "1,25"])
def test_valid_zero_and_fraction_remain_calculable(consumption):
    trace = build_position_trace(position([resource(consumption)]), pricebook=Book())
    quantity = float(str(consumption).replace(",", ".")) * 2
    assert trace["summary"]["resource_decisions"][0]["qty"] == quantity
    assert trace["summary"]["full_amount"] == quantity * 10


def test_explicit_unknown_per_unit_is_not_replaced_with_total_quantity():
    item = {**resource(None), "qty": 8}
    unknown = build_position_trace(position([item]), pricebook=Book())
    assert unknown["summary"]["resource_decisions"][0]["qty"] is None
    del item["per_unit"]
    known = build_position_trace(position([item]), pricebook=Book())
    assert known["summary"]["resource_decisions"][0]["qty"] == 8


def test_builder_reader_and_calculator_keep_null_distinct_from_zero(tmp_path, monkeypatch):
    source = tmp_path / "source.parquet"
    base = tmp_path / "base.sqlite"
    common = {"norm_key": "ГЭСН:08-01-001-01", "base_type": "ГЭСН",
              "norm_code": "08-01-001-01", "norm_name": "Authored work", "norm_unit": "шт",
              "kind": "material", "resource_code": "R1", "resource_name": "Material",
              "resource_unit": "кг", "source_doc": "source.xml", "source_guid": "literal-guid"}
    pd.DataFrame([{**common, "per_unit": None}, {**common, "per_unit": 0}]).to_parquet(source)
    manifest = build_structured_base(source=source, out=base, manifest_out=tmp_path / "manifest.json")
    with sqlite3.connect(base) as conn:
        quantities = [row[0] for row in conn.execute("SELECT per_unit FROM resources ORDER BY id")]
    assert quantities == [None, 0]
    assert manifest["output"]["resources_unknown_consumption"] == 1
    integrity = json.loads((tmp_path / "base_integrity.json").read_text(encoding="utf-8"))
    assert integrity["verdict"] == "passed"  # valid structure, explicitly incomplete data
    assert integrity["resources_unknown_consumption"] == 1
    exact = read_norm_card_exact(norm_code="ГЭСН08-01-001-01", base_path=base)
    assert exact["status"] == "ok"
    assert exact["card"]["resources_complete"] is False
    assert [r["per_unit"] for r in exact["card"]["resources"]] == [None, 0]
    monkeypatch.setenv("LES_SMETA_STRUCTURED_BASE", str(base))
    gesn_service.load_base_norms.cache_clear()
    gesn_service.load_structured_base_norms.cache_clear()
    try:
        lines = gesn_service.expand_position("ГЭСН08-01-001-01", 2)
        assert [r["qty"] for r in lines] == [None, 0]
        calculated = build_position_trace({"code": "ГЭСН08-01-001-01", "qty": 2,
                                          "nr_pct": 0, "sp_pct": 0}, pricebook=Book())
        assert calculated["summary"]["full_amount"] is None
        assert calculated["summary"]["resource_decisions"][0]["qty"] is None
    finally:
        gesn_service.load_base_norms.cache_clear()
        gesn_service.load_structured_base_norms.cache_clear()


def test_legacy_assembly_refuses_unknown_resource_quantity():
    from proxy.services.lsr_assembly_service import compute_position

    with pytest.raises(ValueError, match="Не указано количество ресурса"):
        compute_position({"resources": [{**resource(None), "qty": None}]})
