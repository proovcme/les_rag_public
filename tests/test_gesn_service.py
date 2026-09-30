"""ГЭСН: норма→ресурсы и сборка ЛСР прямо от кода с полным ФСЭМ.

The card consumed here is the canonical base card (data/smeta_base/les_smeta_base.sqlite),
so its consumptions are real data.  Its money is not: a base card states no price, so the
rates below come from a ценовая база the test names, and each pinned sum is the product of
the card's own consumption and one of those rates.
"""

from __future__ import annotations

from proxy.services.gesn_service import _dedupe_resources, expand_position, get_norm, list_norms
from proxy.services.lsr_assembly_service import compute_position
from proxy.services.rim_lsr_trace_service import build_position_trace

CODE = "ГЭСН12-01-034-02"

# Ставки выбранной книги для шифров этой карточки (тест пишет их сам, чтобы сумму можно
# было пересчитать на бумаге) плюс строки ОТм, в которые ФСЭМ детализует агрегат
# «Затраты труда машинистов» 1,01 маш.-ч этой же карточки.
BOOK_PRICES = {
    "1-100-25": 500.00,          # Средний разряд работы 2.5, руб./чел.-ч
    "91.05.01-017": 900.00,      # Краны башенные 8 т, руб./маш.-ч
    "91.05.05-015": 1700.00,     # Краны на автомобильном ходу 16 т, руб./маш.-ч
    "91.14.02-001": 600.00,      # Автомобили бортовые 5 т, руб./маш.-ч
    "4-100-060": 800.00,         # ОТм 6 разряда (краны), руб./чел.-ч
    "4-100-040": 600.00,         # ОТм 4 разряда (бортовые), руб./чел.-ч
    "01.7.15.06-0111": 90000.00,  # Гвозди строительные, руб./т
    "11.1.03.01-0076": 25000.00,  # Бруски, руб./м3
}


class _Book:
    """Выбранная ценовая база: точный поиск по шифру."""

    def lookup(self, code):
        price = BOOK_PRICES.get(str(code or "").strip())
        return None if price is None else {"price_current": price, "price_current_eff": price}


def test_norm_loaded():
    assert get_norm(CODE)["unit"] == "100 м2"
    assert get_norm("гэсн12-01-034-02") is not None     # регистр/нормализация
    assert any(n["code"] == CODE for n in list_norms())
    assert get_norm("НЕТ-ТАКОЙ") is None


def test_expand_multiplies_by_volume():
    lines = expand_position(CODE, 0.61)
    # base card: 3 машины + агрегат машинистов + труд + 2 материала
    assert lines is not None and len(lines) == 7
    labor = next(l for l in lines if l["kind"] == "labor")
    assert round(labor["qty"], 4) == 7.8934              # 12.94 × 0.61
    mat = next(l for l in lines if l["kind"] == "material")
    assert round(mat["qty"], 6) == 0.000915              # 0.0015 × 0.61
    assert expand_position("НЕТ", 1) is None


def test_base_card_expands_without_a_single_price():
    """Карточка основной базы даёт количества и не даёт денег.

    Это то, из-за чего демо-семя нельзя возвращать в расчёт: его ставка 475,11 руб./чел.-ч
    выглядела как число карточки, а база называет расход труда и шифр, а цену требует из
    выбранной базы региона и квартала (§ 3, § 7).
    """
    lines = expand_position(CODE, 0.61) or []
    assert [l for l in lines if l.get("price") not in (None, "")] == []
    labor = next(l for l in lines if l["kind"] == "labor")
    assert labor["code"] == "1-100-25"                     # the card states its own шифр
    assert not labor.get("code_derivation")                # nobody derived it here
    assert get_norm(CODE)["_source_kind"] == "structured_sqlite"


def test_assemble_from_code_prices_the_base_card_through_the_chosen_book():
    # позиция БЕЗ ресурсов — только код+объём; движок разворачивает по норме ГЭСН,
    # детализирует ОТм по ФСЭМ и закрывает цены выбранной книгой.
    # Разбор цены — лестница ADR-16 § 7, та же, что в РИМ-трассе (§ 10).
    # ОЗП 3 946,70 = 12,94 × 0,61 чел.-ч × 500,00
    # машины       = 0,97×0,61×900 + 0,01×0,61×1700 + 0,03×0,61×600 = 553,88
    # ЗПМ (ФСЭМ)   = 0,5917×800 + 0,0061×800 + 0,0183×600          = 489,22 → ЭМ 1 043,10
    # М            = 0,000915×90 000 + 0,244×25 000                 = 6 182,35
    # прямые 11 172,15;  ФОТ 4 435,92;  НР 4 835,15 + СП 2 528,47   = 18 535,77
    pos = {"code": CODE, "name": "Обрешётка", "qty": 0.61, "nr_pct": 109, "sp_pct": 57}
    r = compute_position(pos, pricebook=_Book())
    assert r["flags"] == []
    b = r["base"]
    assert b["ozp"] == 3946.70
    assert b["em"] == 1043.10
    assert b["zpm"] == 489.22
    assert b["mat"] == 6182.35
    assert b["fot"] == 4435.92
    assert r["total"] == 18535.77


def test_both_engines_state_one_amount_for_one_document():
    """§ 10: сборка ЛСР и РИМ-трасса на том же входе называют одну и ту же сумму."""
    pos = {"code": CODE, "name": "Обрешётка", "qty": 0.61, "nr_pct": 109, "sp_pct": 57}
    legacy = compute_position(pos, pricebook=_Book())
    rim = build_position_trace(pos, pricebook=_Book())["summary"]

    assert rim["total"] == legacy["total"] == 18535.77
    assert rim["ozp"] == legacy["base"]["ozp"]
    assert rim["amount_status"] == "complete"


def test_overlay_fills_missing_norm_without_replacing_seed(tmp_path, monkeypatch):
    import pandas as pd
    from proxy.services import gesn_service

    overlay = tmp_path / "gesn2022_overlay.parquet"
    pd.DataFrame(
        [
            {
                "norm_code": "10-99-001-01",
                "base_type": "ГЭСНм",
                "norm_key": "ГЭСНм:10-99-001-01",
                "norm_name": "Overlay only",
                "norm_unit": "шт",
                "kind": "labor",
                "per_unit": 1.0,
                "resource_name": "Рабочие",
                "resource_unit": "чел.-ч",
            }
        ]
    ).to_parquet(overlay)
    monkeypatch.setattr(gesn_service, "DEFAULT_OVERLAY_PATH", overlay)
    gesn_service.load_overlay_norms.cache_clear()
    gesn_service.load_base_norms.cache_clear()
    try:
        filled = gesn_service.get_norm("ГЭСНм10-99-001-01")
        assert filled is not None
        assert filled["name"] == "Overlay only"
        assert gesn_service.get_norm(CODE)["unit"] == "100 м2"
    finally:
        gesn_service.load_overlay_norms.cache_clear()
        gesn_service.load_base_norms.cache_clear()


def test_unknown_code_flagged():
    r = compute_position({"code": "ГЭСН99-99-999-99", "qty": 1})
    assert r["flags"] and "норма ГЭСН не найдена" in r["flags"][0]


def test_stale_base_resource_dedup_uses_code_and_preserves_distinct_consumption():
    resources, dropped = _dedupe_resources([
        {"kind": "machine", "code": "91.05.01-017", "name": "Кран башенный", "unit": "маш.-ч", "per_unit": 3},
        {"kind": "machine", "code": "91.05.01-017", "name": "КРАН  БАШЕННЫЙ", "unit": "маш.-ч", "per_unit": 3.0},
        {"kind": "machine", "code": "91.05.01-017", "name": "Кран башенный", "unit": "маш.-ч", "per_unit": 4},
    ])

    assert dropped == 1
    assert [row["per_unit"] for row in resources] == [3, 4]
