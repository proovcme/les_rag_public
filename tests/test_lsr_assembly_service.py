"""Движок сборки ЛСР: ресурсы→цены→ОЗП/ЭМ/НР/СП→Всего. Gold — позиция Эталон_кровля."""

from __future__ import annotations

from proxy.services.lsr_assembly_service import assemble, compute_position

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
