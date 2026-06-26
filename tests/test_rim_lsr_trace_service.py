"""РИМ-трасса ЛСР: графы 2-12, цены ФГИС ЦС и итог позиции."""

from __future__ import annotations

from proxy.services.rim_lsr_trace_service import build_position_trace


CODE = "ГЭСН12-01-034-02"


def _rows_by_type(trace):
    return {row["type"]: row for row in trace["rows"]}


def test_rim_trace_from_gesn_seed_reproduces_gold_position():
    trace = build_position_trace({"code": CODE, "qty": 0.61})
    summary = trace["summary"]

    assert summary["flags"] == []
    assert summary["ozp"] == 3750.23
    assert summary["em"] == 992.40
    assert summary["mat"] == 83.62
    assert summary["direct"] == 4826.25
    assert summary["fot"] == 4208.91
    assert summary["nr"] == 4587.71
    assert summary["sp"] == 2399.08
    assert summary["total"] == 11813.04

    rows = _rows_by_type(trace)
    assert rows["work"]["columns"]["2"] == CODE
    assert rows["work"]["columns"]["4"] == "100 м2"
    assert rows["work"]["columns"]["7"] == 0.61
    assert rows["group_labor"]["columns"]["7"] == 7.8934
    assert rows["group_labor"]["columns"]["12"] == 3750.23
    assert rows["group_machine"]["columns"]["12"] == 992.4
    assert rows["group_machinist"]["columns"]["12"] == 458.68
    assert rows["group_material"]["columns"]["12"] == 83.62
    assert rows["nr"]["source"] == "Пр/812"
    assert rows["sp"]["source"] == "Пр/774"


def test_rim_trace_applies_resource_coefficients_by_kind():
    trace = build_position_trace({"code": CODE, "qty": 0.61}, k_ozp=1.15, k_em=1.15)
    summary = trace["summary"]
    rows = _rows_by_type(trace)

    assert rows["coefficient"]["meta"] == {"k_ozp": 1.15, "k_em": 1.15}
    labor = next(row for row in trace["rows"] if row["type"] == "resource_labor")
    machine = next(row for row in trace["rows"] if row["type"] == "resource_machine")
    machinist = next(row for row in trace["rows"] if row["type"] == "resource_machinist")
    material = next(row for row in trace["rows"] if row["type"] == "resource_material")
    assert labor["columns"]["6"] == 1.15
    assert machine["columns"]["6"] == 1.15
    assert machinist["columns"]["6"] == 1.15
    assert material["columns"]["6"] == 1.0
    assert summary["ozp"] > 3750.23
    assert summary["machine"] > 533.72
    assert summary["zpm"] > 458.68
    assert summary["mat"] == 83.62
    assert summary["total"] > 11813.04


def test_rim_trace_preserves_fgis_current_vs_base_index_columns():
    class FakePriceBook:
        def lookup(self, code):
            return {
                "91.05.05-015": {
                    "price_current": 1663.18,
                    "price_base": 1167.7,
                    "index": None,
                    "price_current_eff": 1663.18,
                },
                "01.7.15.06-0111": {
                    "price_current": None,
                    "price_base": 70296.2,
                    "index": 1.3,
                    "price_current_eff": 91385.06,
                },
            }.get(code)

    trace = build_position_trace(
        {
            "code": "ГЭСН00-00-000-00",
            "name": "Тестовая работа",
            "unit": "шт",
            "qty": 2,
            "nr_pct": 0,
            "sp_pct": 0,
            "resources": [
                {"kind": "machine", "code": "91.05.05-015", "name": "Кран", "unit": "маш.-ч", "per_unit": 1},
                {"kind": "material", "code": "01.7.15.06-0111", "name": "Гвозди", "unit": "т", "per_unit": 0.001},
            ],
        },
        pricebook=FakePriceBook(),
    )

    machine = next(row for row in trace["rows"] if row["type"] == "resource_machine")
    material = next(row for row in trace["rows"] if row["type"] == "resource_material")

    assert machine["source"] == "fgis_current"
    assert machine["columns"]["10"] == 1663.18
    assert "8" not in machine["columns"]
    assert "9" not in machine["columns"]

    assert material["source"] == "fgis_base_index"
    assert material["columns"]["8"] == 70296.2
    assert material["columns"]["9"] == 1.3
    assert material["columns"]["10"] == 91385.06
    assert material["columns"]["12"] == 182.77
    assert trace["summary"]["direct"] == 3509.13
