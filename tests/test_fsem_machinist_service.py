"""Тест полного typed ФСЭМ «машина→машинист» и reconciliation ОТм."""

from copy import deepcopy

import pytest

from proxy.services import fsem_machinist_service as fsem


def test_full_catalog_loads_entries():
    m = fsem.machine_to_machinist()
    assert m["91.05.05-015"][0] == "4-100-060"
    assert m["91.05.05-015"][1] == "Машинисты, средний разряд 6"
    assert "91.14.02-002" in m  # 3-я запись
    assert len(m) >= 900


def test_lookup_and_list():
    assert fsem.lookup("91.14.02-001")["driver_code"] == "4-100-040"
    assert fsem.lookup("нет-такой-машины") is None
    entries = fsem.list_entries()
    assert any(e["machine_code"] == "91.05.05-015" for e in entries)


def test_missing_catalog_fails_closed_without_seed(tmp_path):
    m = fsem.machine_to_machinist(str(tmp_path / "absent.yaml"))
    assert m == {}
    assert fsem.list_entries(str(tmp_path / "absent.sqlite")) == []


def test_rim_trace_uses_reconciled_full_fsem():
    """Агрегат «Затраты труда машинистов» расходится на конкретные шифры ОТм.

    Книга — детерминированный двойник из ``tests/test_rim_lsr_trace_service.py``, а не то,
    что резолвит рантайм: без выбранной книги ФСЭМ не применяет разбор вовсе
    (``not_applied_without_pricebook``), поэтому и статус, и деньги разборки на книге
    оператора зависели бы от содержимого ``data/price_base``.
    """
    from proxy.services import rim_lsr_trace_service as rim
    from tests import test_rim_lsr_trace_service as gold

    trace = rim.build_position_trace(
        {"code": gold.CODE, "qty": gold.GOLD_QTY}, pricebook=gold._Book(), k_ozp=1.0, k_em=1.0
    )
    summary = trace["summary"]

    assert summary["fsem_trace"]["status"] == "reconciled"
    assert summary["fsem_trace"]["machine_count"] == 3
    assert summary["fsem_trace"]["detailed_machinist_rows"] == 3
    assert summary["fsem_trace"]["hours"] == 1.01  # the card's aggregate ОТм, fully split
    # детализация обязательна: без неё ЗПМ — одна агрегатная строка без шифра и без цены,
    # а с ней ЗПМ считается по ставкам книги, которые названы в строках 4-100-*
    assert summary["zpm"] == gold.GOLD_ZPM
    machinist_rows = [row for row in trace["rows"] if row["type"] == "resource_machinist"]
    assert sorted(str(row["columns"]["2"]) for row in machinist_rows) == [
        "4-100-040",
        "4-100-060",
        "4-100-060",
    ]


@pytest.fixture
def typed_machine_mapping(monkeypatch):
    rows = {
        "M-A": {"machine_code": "M-A", "driver_code": "4-100-030",
                "driver_grade": 3.0, "crew_hours": 1.0, "source_page": 83},
        "M-B": {"machine_code": "M-B", "driver_code": "4-100-040",
                "driver_grade": 4.0, "crew_hours": 1.0, "source_page": 168},
    }
    monkeypatch.setattr(fsem, "lookup", lambda code, _path: deepcopy(rows.get(code)))
    return rows


def _published_resources(aggregate_hours=0.02):
    return [
        {"kind": "machine", "code": "M-A", "name": "Machine A", "unit": "маш.-ч",
         "per_unit": 0.02, "source_guid": "norm-publication", "source_value": "0.02"},
        {"kind": "machine", "code": "M-B", "name": "Machine B", "unit": "маш.-ч",
         "per_unit": 0.002, "source_guid": "norm-publication", "source_value": "0.002"},
        {"kind": "machinist", "code": "", "name": "Published aggregate", "unit": "маш.-ч",
         "per_unit": aggregate_hours, "source_guid": "norm-publication", "source_value": str(aggregate_hours)},
    ]


class _MachineTariffBook:
    region = "Deterministic test region"
    quarter = "Deterministic test period"

    def lookup(self, code):
        rows = {
            "M-A": (59.71, "маш.-ч"), "M-B": (644.72, "маш.-ч"),
            "4-100-030": (538.37, "чел.-ч"), "4-100-040": (606.23, "чел.-ч"),
        }
        if code not in rows:
            return None
        price, unit = rows[code]
        return {"price_current": price, "price_current_eff": price, "unit": unit}


@pytest.mark.parametrize("aggregate_hours", [0.02, 1.0])
def test_machine_tariffs_calculate_without_fitting_to_an_unreconciled_aggregate(
    typed_machine_mapping, aggregate_hours,
):
    """421/пр formula (1.2) prices each machine; disagreement is a source blocker."""
    from proxy.services import rim_lsr_trace_service as rim

    position = {"code": "Model-selected norm", "qty": 0.15, "nr_pct": 0, "sp_pct": 0,
                "resources": _published_resources(aggregate_hours)}
    before = deepcopy(position)
    trace = rim.build_position_trace(position, pricebook=_MachineTariffBook())
    summary = trace["summary"]
    assert summary["zpm"] == 1.80  # .003 * 538.37 + .0003 * 606.23, rounded per line
    assert summary["total"] == 2.17  # .18 + .19 machine costs; aggregate is not charged
    assert summary["machinist_qty"] == 0.0033
    assert summary["full_amount"] is None and summary["amount_status"] == "partial"
    assert "fsem_aggregate_discrepancy" in summary["completeness_reasons"]
    assert not any(reason.startswith("price_missing:") for reason in summary["completeness_reasons"])
    audit = summary["fsem_trace"]
    assert audit["status"] == "derived_with_aggregate_discrepancy"
    assert audit["source_machinist_hours"] == aggregate_hours
    assert audit["derived_machinist_hours"] == 0.022
    assert audit["aggregate_reconciliation"]["status"] == "discrepancy"
    assert audit["aggregate_reconciliation"]["source_aggregates"] == before["resources"][-1:]
    components = audit["machine_operator_components"]
    assert [item["machine_resource"] for item in components] == before["resources"][:2]
    assert [item["fsem_machine"] for item in components] == list(typed_machine_mapping.values())
    assert [item["operator_hours"] for item in components] == [0.02, 0.002]
    driver_rows = [row for row in trace["rows"] if row["type"] == "resource_machinist"]
    assert len(driver_rows) == 2
    assert [row["columns"]["2"] for row in driver_rows] == ["4-100-030", "4-100-040"]
    assert [row["columns"]["12"] for row in driver_rows] == [1.62, 0.18]
    assert sum(row["columns"]["12"] for row in trace["rows"] if row["type"].startswith("resource_")) == 2.17
    assert any("0.022" in flag and f"{aggregate_hours:g}" in flag for flag in summary["flags"])
    assert position == before


def test_incomplete_machine_linkage_never_prices_a_partial_operator_split(typed_machine_mapping):
    del typed_machine_mapping["M-B"]
    resources = _published_resources()
    before = deepcopy(resources)
    detailed, audit = fsem.enrich_machinists(resources, quantity_field="per_unit")
    assert detailed == before and resources == before
    assert audit["status"] == "unresolved"
    assert audit["missing_machine_codes"] == ["M-B"]


def test_exact_aggregate_keeps_confirmed_tariff_arithmetic(typed_machine_mapping):
    from proxy.services import rim_lsr_trace_service as rim

    position = {"code": "Model-selected norm", "qty": 0.15, "nr_pct": 0, "sp_pct": 0,
                "resources": _published_resources(0.022)}
    before = deepcopy(position)
    trace = rim.build_position_trace(position, pricebook=_MachineTariffBook())
    summary = trace["summary"]
    assert summary["fsem_trace"]["status"] == "reconciled"
    assert summary["fsem_trace"]["aggregate_reconciliation"]["status"] == "exact"
    assert summary["zpm"] == 1.80 and summary["full_amount"] == 2.17
    assert summary["amount_status"] == "complete" and summary["completeness_reasons"] == []
    assert summary["flags"] == [] and position == before


def test_derived_operator_with_missing_tariff_keeps_its_price_gap(typed_machine_mapping, monkeypatch):
    from proxy.services import rim_lsr_trace_service as rim

    book = _MachineTariffBook()
    lookup = book.lookup
    monkeypatch.setattr(book, "lookup", lambda code: None if code == "4-100-040" else lookup(code))
    trace = rim.build_position_trace(
        {"code": "Model-selected norm", "qty": 0.15, "nr_pct": 0, "sp_pct": 0,
         "resources": _published_resources()}, pricebook=book,
    )
    summary = trace["summary"]
    assert summary["zpm"] == 1.62 and summary["full_amount"] is None
    assert "fsem_aggregate_discrepancy" in summary["completeness_reasons"]
    assert "price_missing:4-100-040" in summary["completeness_reasons"]
    row = next(row for row in trace["rows"]
               if row["type"] == "resource_machinist" and row["columns"]["2"] == "4-100-040")
    assert row["meta"]["price_action"] == "needs_machinist_rate" and row["columns"].get("12") is None


def test_published_numeric_disagreement_is_not_hidden_by_six_decimal_rounding(typed_machine_mapping):
    resources = _published_resources("0.02200002")
    resources[0]["per_unit"] = "0.02000001"
    resources[0]["source_value"] = "0.02000001"
    before = deepcopy(resources)
    detailed, audit = fsem.enrich_machinists(resources, quantity_field="per_unit")
    assert audit["status"] == "derived_with_aggregate_discrepancy"
    assert audit["source_machinist_hours"] == 0.02200002
    assert audit["derived_machinist_hours"] == 0.02200001
    assert audit["aggregate_reconciliation"]["difference_hours"] == -0.00000001
    assert next(row for row in detailed if row.get("fsem_machine_code") == "M-A")["per_unit"] == 0.02000001
    assert resources == before


def test_discrepancy_does_not_replace_a_price_already_written_on_the_aggregate(typed_machine_mapping):
    resources = _published_resources()
    resources[-1].update(price=777.0, price_source_ref="operator-authored-price")
    before = deepcopy(resources)
    detailed, audit = fsem.enrich_machinists(resources, quantity_field="per_unit")
    assert detailed == before and resources == before
    assert audit["status"] == "unresolved"
    assert "explicit_priced_aggregate_discrepancy" in audit["reasons"]
    assert audit["source_machinist_hours"] == 0.02 and audit["derived_machinist_hours"] == 0.022


def test_known_machine_without_operator_is_not_confused_with_an_unknown_crew(typed_machine_mapping):
    typed_machine_mapping["M-C"] = {"machine_code": "M-C", "driver_code": "", "driver_grade": None,
                                    "crew_hours": 0.0, "source_page": 12}
    resources = _published_resources()
    resources.insert(2, {"kind": "machine", "code": "M-C", "unit": "маш.-ч", "per_unit": 0.9})
    before = deepcopy(resources)
    detailed, audit = fsem.enrich_machinists(resources, quantity_field="per_unit")
    assert audit["status"] == "derived_with_aggregate_discrepancy"
    assert audit["derived_machinist_hours"] == 0.022 and audit["detailed_machinist_rows"] == 2
    assert audit["machine_operator_components"][-1]["operator_hours"] == 0
    assert [row for row in detailed if row["kind"] == "machine"] == before[:3]
    assert resources == before


def test_crew_factor_is_applied_to_its_machine_without_changing_consumption(typed_machine_mapping):
    typed_machine_mapping["M-A"]["crew_hours"] = 2.0
    resources = _published_resources(0.042)
    before = deepcopy(resources)
    detailed, audit = fsem.enrich_machinists(resources, quantity_field="per_unit")
    assert audit["status"] == "reconciled" and audit["derived_machinist_hours"] == 0.042
    assert [row["per_unit"] for row in detailed if row["kind"] == "machinist"] == [0.04, 0.002]
    assert [row for row in detailed if row["kind"] == "machine"] == before[:2]
    assert resources == before


def test_legacy_assembly_keeps_computable_money_preliminary(typed_machine_mapping, monkeypatch):
    from proxy.services import lsr_assembly_service as assembly

    resources = _published_resources()
    for resource in resources:
        resource["qty"] = resource.pop("per_unit")
    position = {"code": "Model-selected norm", "nr_pct": 0, "sp_pct": 0, "resources": resources}
    before = deepcopy(position)
    monkeypatch.setattr(assembly, "_resolve_book", lambda _book: _MachineTariffBook())
    result = assembly.assemble([position], book="deterministic")
    computed = result["positions"][0]
    assert computed["base"]["zpm"] == 11.98
    assert result["summary"]["result_status"] == "priced_partial"
    gaps = [gap for gap in computed["price_requirements"] if gap["action"] == "needs_fsem_resolution"]
    assert len(gaps) == 1 and "предварительн" in gaps[0]["message"]
    assert len([row for row in computed["resources"] if row["kind"] == "machinist"]) == 2
    assert position == before


@pytest.mark.parametrize("field,value", [
    ("crew_hours", None), ("crew_hours", -1), ("crew_hours", float("inf")),
    ("driver_grade", None), ("driver_grade", 0), ("driver_grade", float("nan")),
    ("driver_code", ""),
])
def test_incomplete_or_invalid_crew_grade_blocks_operator_derivation(typed_machine_mapping, field, value):
    typed_machine_mapping["M-B"][field] = value
    resources = _published_resources()
    before = deepcopy(resources)
    detailed, audit = fsem.enrich_machinists(resources, quantity_field="per_unit")
    assert detailed == before and resources == before
    assert audit["status"] == "unresolved" and audit["missing_machine_codes"] == ["M-B"]


def test_existing_named_operator_is_not_charged_again_from_an_aggregate(typed_machine_mapping):
    resources = _published_resources(0.022)
    resources.append({"kind": "machinist", "code": "4-100-030", "name": "Authored driver",
                      "unit": "чел.-ч", "per_unit": 0.02})
    before = deepcopy(resources)
    detailed, audit = fsem.enrich_machinists(resources, quantity_field="per_unit")
    assert detailed == before and resources == before
    assert audit["status"] == "unresolved"
    assert "explicit_machinist_with_aggregate" in audit["reasons"]
