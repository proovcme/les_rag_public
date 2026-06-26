"""Движок сборки ЛСР: ресурсы→цены→ОЗП/ЭМ/НР/СП→Всего. Gold — позиция Эталон_кровля."""

from __future__ import annotations

from proxy.services.lsr_assembly_service import assemble, compute_position, export_assembled

# Эталон_кровля, поз.1 «Устройство обрешётки» — ресурсы агрегатами с фактическими суммами.
GOLD_POS = {
    "code": "ГЭСН12-01-034-02",
    "name": "Устройство обрешётки с прозорами из брусков",
    "unit": "100 м2", "qty": 0.61, "section": "Раздел 1. Монтаж медного отлива. 7-й ярус",
    "nr_pct": 109, "sp_pct": 57,
    "resources": [
        {"kind": "labor", "name": "ОТ(ЗТ)", "unit": "чел.-ч", "qty": 1, "price": 3750.23},
        {"kind": "machine", "name": "Машины (краны, автомобиль)", "unit": "маш.-ч", "qty": 1, "price": 533.72},
        {"kind": "machinist", "name": "ОТм(ЗТм)", "unit": "чел.-ч", "qty": 1, "price": 458.68},
        {"kind": "material", "name": "Гвозди строительные", "unit": "т", "qty": 1, "price": 83.62},
    ],
}


def test_gold_position_reproduces_etalon():
    r = compute_position(GOLD_POS)
    b = r["base"]
    assert b["ozp"] == 3750.23
    assert b["em"] == 992.40            # машины 533.72 + ОТм 458.68
    assert b["mat"] == 83.62
    assert b["direct"] == 4826.25       # ОЗП + ЭМ + М
    assert b["fot"] == 4208.91          # ОЗП + ЗПМ
    assert b["nr"] == 4587.71           # ФОТ × 109%
    assert b["sp"] == 2399.08           # ФОТ × 57%
    assert r["total"] == 11813.04       # Всего по позиции — как в эталоне
    assert r["flags"] == []


def test_quantity_multiplication():
    pos = {"name": "x", "nr_pct": 100, "sp_pct": 50, "resources": [
        {"kind": "labor", "qty": 2, "price": 100},       # ОЗП 200
        {"kind": "machine", "qty": 3, "price": 10},      # машины 30
        {"kind": "machinist", "qty": 1, "price": 50},    # ЗПМ 50 → ЭМ 80
        {"kind": "material", "qty": 0.5, "price": 40},   # М 20
    ]}
    b = compute_position(pos)["base"]
    assert b["ozp"] == 200 and b["em"] == 80 and b["mat"] == 20
    assert b["fot"] == 250 and b["direct"] == 300 and b["total"] == 675.0


def test_stesnennost_in_assembly():
    r = compute_position(GOLD_POS, k_ozp=1.15, k_em=1.15)
    assert r["adjusted"]["total"] > r["base"]["total"]
    assert r["total"] == r["adjusted"]["total"]      # при k≠1 берём скорректированное


def test_kac_price_for_unlisted_material():
    pos = {"name": "y", "nr_pct": 0, "sp_pct": 0, "resources": [
        {"kind": "material", "name": "Гранит серый 600×300×30", "qty": 2},  # без price/code
    ]}
    r = compute_position(pos, kac_map={"гранит серый 600×300×30": 2300.0})
    assert r["base"]["mat"] == 4600.0
    assert r["flags"] == []
    assert r["resources"][0]["price_source"] == "kac"


def test_missing_price_flagged():
    pos = {"name": "z", "resources": [{"kind": "material", "name": "Неизвестный", "qty": 1}]}
    r = compute_position(pos)
    assert r["flags"] and "нет цены" in r["flags"][0]


def test_assemble_rollup():
    res = assemble([GOLD_POS, GOLD_POS])
    assert res["summary"]["positions"] == 2
    assert res["summary"]["total"] == round(11813.04 * 2, 2)
    assert len(res["sections"]) == 1
    assert res["sections"][0]["positions"] == 2


def test_machinist_aggregate_split_by_mapped_machines():
    class FakePriceBook:
        def lookup(self, code: str):
            prices = {
                "4-100-060": 801.41,
                "4-100-040": 650.0,
            }
            if code in prices:
                return {"price_current_eff": prices[code]}
            return None

    pos = {"name": "metal", "nr_pct": 0, "sp_pct": 0, "resources": [
        {"kind": "machine", "name": "Кран 16 т", "code": "91.05.05-015", "qty": 9, "price": 100},
        {"kind": "machine", "name": "Авто до 8 т", "code": "91.14.02-002", "qty": 0.5, "price": 50},
        {"kind": "machinist", "name": "Затраты труда машинистов", "qty": 9.5},
    ]}

    res = compute_position(pos, pricebook=FakePriceBook())

    assert res["flags"] == []
    assert res["base"]["zpm"] == round(9 * 801.41 + 0.5 * 650.0, 2)
    assert {r.get("code") for r in res["resources"] if r["kind"] == "machinist"} == {"4-100-060", "4-100-040"}


def test_machinist_aggregate_stays_missing_without_complete_mapping():
    pos = {"name": "metal", "nr_pct": 0, "sp_pct": 0, "resources": [
        {"kind": "machine", "name": "Ножницы", "code": "91.21.12-002", "qty": 2, "price": 100},
        {"kind": "machinist", "name": "Затраты труда машинистов", "qty": 2},
    ]}

    res = compute_position(pos)

    assert res["base"]["zpm"] == 0
    assert res["flags"] and "Затраты труда машинистов" in res["flags"][0]


def test_export_assembled_csv_and_xlsx(tmp_path):
    result = assemble([GOLD_POS])
    csv_path = export_assembled(result, tmp_path / "lsr.csv", fmt="csv")
    xlsx_path = export_assembled(result, tmp_path / "lsr.xlsx", fmt="xlsx")

    assert csv_path.read_text(encoding="utf-8-sig").startswith("section;position_no;")
    assert xlsx_path.exists() and xlsx_path.stat().st_size > 0
