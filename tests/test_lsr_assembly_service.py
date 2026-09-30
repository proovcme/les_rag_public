"""Движок сборки ЛСР: ресурсы→цены→ОЗП/ЭМ/НР/СП→Всего.

Арифметика движка проверяется на позициях, которые тест пишет сам: ставки и расходы
названы прямо в ресурсах, поэтому любой иток ниже пересчитывается на бумаге и не зависит
ни от карточки нормы, ни от установленной ценовой книги.  Исторический «gold»
11 813.04 здесь заменён на авторские ставки: это была сумма, которую печатало демо-семя
``config/domain/gesn_seed.yaml`` (замер — ``stage_b/live_830/seed_vs_base_reconcile_830.md``,
запрет закреплён в ``tests/test_gesn_seed_is_test_only_830.py``), а не данные проверенной базы.
Расчёт от реальной карточки базы по детерминированной книге — в
``tests/test_rim_lsr_trace_service.py`` (``GOLD_*``).

Исключение — позиция, заданная только шифром: её ресурсы разворачиваются из карточки
базы, а деньги берёт ценовая книга.  Чтобы пин не зависел от того, какая книга лежит у
оператора, книгу замыкает фикстура ``tests/lsr_gold_pricebook.py``.
"""

from __future__ import annotations

from proxy.services import lsr_assembly_service as la
from proxy.services.lsr_assembly_service import assemble, compute_position, export_assembled
from tests.lsr_gold_pricebook import gold_pricebook  # noqa: F401  (фикстура по имени)

# Агрегированная позиция, которую тест пишет сам: четыре группы ресурсов с явными
# ставками, объём 1 условная единица формы.  Иток = 5 000 + 1 800 + 200 = 7 000 прямых,
# ФОТ 5 000 + 800 = 5 800, НР 109 % = 6 322, СП 57 % = 3 306 → 16 628,00.
GOLD_POS = {
    "code": "ГЭСН12-01-034-02",
    "name": "Устройство обрешётки с прозорами из брусков",
    "unit": "100 м2", "qty": 0.61, "section": "Раздел 1. Монтаж медного отлива. 7-й ярус",
    "nr_pct": 109, "sp_pct": 57,
    "resources": [
        {"kind": "labor", "name": "ОТ(ЗТ)", "unit": "чел.-ч", "qty": 1, "price": 5000.00},
        {"kind": "machine", "name": "Машины (краны, автомобиль)", "unit": "маш.-ч", "qty": 1, "price": 1000.00},
        {"kind": "machinist", "name": "ОТм(ЗТм)", "unit": "чел.-ч", "qty": 1, "price": 800.00},
        {"kind": "material", "name": "Гвозди строительные", "unit": "т", "qty": 1, "price": 200.00},
    ],
}
GOLD_TOTAL = 16_628.00


def test_gold_position_is_the_sum_of_its_own_named_rates():
    r = compute_position(GOLD_POS)
    b = r["base"]
    assert b["ozp"] == 5000.00
    assert b["em"] == 1800.00             # машины 1 000 + ОТм 800
    assert b["mat"] == 200.00
    assert b["direct"] == 7000.00         # ОЗП + ЭМ + М
    assert b["fot"] == 5800.00            # ОЗП + ЗПМ (без стоимости эксплуатации машин)
    assert b["nr"] == 6322.00             # ФОТ × 109 %
    assert b["sp"] == 3306.00             # ФОТ × 57 %
    assert r["total"] == GOLD_TOTAL       # Всего по позиции
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
    assert r["flags"] and "нужен КАЦ" in r["flags"][0]
    assert r["price_requirements"][0]["action"] == "needs_kac"
    assert r["resources"][0]["price_action"] == "needs_kac"


def test_missing_non_material_prices_are_actionable():
    pos = {"name": "z", "resources": [
        {"kind": "labor", "name": "Рабочий", "qty": 1},
        {"kind": "machinist", "name": "Машинист", "qty": 1},
        {"kind": "machine", "name": "Кран", "qty": 1},
    ]}
    r = compute_position(pos)
    actions = [req["action"] for req in r["price_requirements"]]
    assert actions == ["needs_labor_rate", "needs_machinist_rate", "needs_fgis_price"]


def test_assemble_rollup():
    res = assemble([GOLD_POS, GOLD_POS])
    assert res["summary"]["positions"] == 2
    assert res["summary"]["total"] == round(2 * GOLD_TOTAL, 2)
    assert len(res["sections"]) == 1
    assert res["sections"][0]["positions"] == 2


def test_default_pricebook_prefers_spb_over_first_alphabetic(monkeypatch):
    from proxy.services import fgis_price_service as fps
    from proxy.services import lsr_assembly_service as la

    chosen = {}

    class FakeBook:
        region = "Санкт-Петербург"
        quarter = "2 квартал 2026 г."

    monkeypatch.setattr(
        fps,
        "available_pricebooks",
        lambda *a, **k: ["/tmp/altayskiy-kray_2kv2026.parquet", "/tmp/spb_2kv2026.parquet"],
    )
    def _fake_get_pricebook(path):
        chosen["path"] = path
        return FakeBook()

    monkeypatch.setattr(fps, "get_pricebook", _fake_get_pricebook)

    book = la._resolve_book(None)

    assert isinstance(book, FakeBook)
    assert chosen["path"] == "/tmp/spb_2kv2026.parquet"


def test_assemble_code_only_applies_explicit_nr_sp_rule_from_typed_collection(gold_pricebook):
    """Позиция задана шифром: ресурсы — из карточки базы, деньги — из книги фикстуры.

    страж герметичности: `_resolve_book` обязана вернуть книгу эталона, иначе сумма ниже
    зависела бы от содержимого ``data/price_base`` на машине оператора.
    """

    assert la._resolve_book("spb_2kv2026") is gold_pricebook

    res = assemble([{
        "code": "ГЭСНм08-03-575-01",
        "qty": 1,
        "nr_sp_rule_id": "nrsp-49.3",
        "section": "Электромонтаж",
    }], book="spb_2kv2026")

    pos = res["positions"][0]
    assert pos["nr_sp_trace"]["rule_id"] == "nrsp-49.3"
    # карточка базы («шт», труд 1,03 чел.-ч + болты 0,02 кг) × строки книги эталона:
    # ОЗП 1,03 × 614,42 = 632,85; М 0,02 × 188,92 = 3,78; ФОТ = ОЗП (без машин и ОТм).
    assert pos["base"]["ozp"] == 632.85
    assert pos["base"]["mat"] == 3.78
    assert {r["price_source"] for r in pos["resources"]} == {"fgis"}
    assert pos["base"]["nr"] == 613.86            # ФОТ × 97 % (nrsp-49.3)
    assert pos["base"]["sp"] == 322.75            # ФОТ × 51 % (nrsp-49.3)
    assert pos["total"] == 1573.24                # 636,63 прямых + 613,86 + 322,75
    assert res["summary"]["total"] == 1573.24
    # ни одной дыры: позиция закрыта книгой, и отчёт обязан назвать её закрытой, не черновиком
    assert res["summary"]["result_status"] == "priced_final"


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
    assert any("Затраты труда машинистов" in flag for flag in res["flags"])


def test_export_assembled_csv_and_xlsx(tmp_path):
    result = assemble([GOLD_POS])
    csv_path = export_assembled(result, tmp_path / "lsr.csv", fmt="csv")
    xlsx_path = export_assembled(result, tmp_path / "lsr.xlsx", fmt="xlsx")

    assert csv_path.read_text(encoding="utf-8-sig").startswith("section;position_no;")
    assert xlsx_path.exists() and xlsx_path.stat().st_size > 0
