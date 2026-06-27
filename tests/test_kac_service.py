"""КАЦ: группировка котировок, выбор экономичного, достаточность ≥3, мост к ФГИС ЦС."""

from __future__ import annotations

from pathlib import Path

from proxy.services import fgis_price_service as fps
from proxy.services.doc_classifier import classify_table
from proxy.services.kac_service import (
    analyze_kac,
    kac_to_lsr_lines,
    needs_kac,
    to_xlsx,
)

QUOTES = [
    {"material": "Гранит серый 600×300×30", "supplier": "ГранитИнвест", "unit": "м2", "price": 2450, "source": "КП-1"},
    {"material": "Гранит серый 600×300×30", "supplier": "ЛЕВ", "unit": "м2", "price": "2 300", "source": "КП-2"},
    {"material": "Гранит серый 600×300×30", "supplier": "ПрофСтрой", "unit": "м2", "price": 2520, "source": "КП-3"},
    {"material": "Сетка сварная 50×50", "supplier": "ЛистМет", "unit": "м2", "price": 410, "source": "КП-4"},
    {"material": "Сетка сварная 50×50", "supplier": "БВБ", "unit": "м2", "price": 395, "source": "КП-5"},
]


def test_analyze_groups_and_chosen_min():
    res = analyze_kac(QUOTES, min_suppliers=3, strategy="min")
    s = res["summary"]
    assert s == {"materials": 2, "sufficient": 1, "insufficient": 1, "total_quotes": 5}
    granit = next(m for m in res["materials"] if "Гранит" in m["material"])
    assert granit["suppliers"] == 3 and granit["sufficient"] is True
    assert granit["chosen_price"] == 2300.0           # экономичный (с разбором «2 300»)
    assert granit["chosen_supplier"] == "ЛЕВ"
    assert granit["spread_pct"] == 9.6                # (2520-2300)/2300
    setka = next(m for m in res["materials"] if "Сетка" in m["material"])
    assert setka["sufficient"] is False               # 2 < 3 поставщиков


def test_strategy_median():
    res = analyze_kac(QUOTES, strategy="median")
    granit = next(m for m in res["materials"] if "Гранит" in m["material"])
    assert granit["chosen_price"] == 2450.0           # медиана из 2300/2450/2520


def test_lsr_lines():
    lines = kac_to_lsr_lines(analyze_kac(QUOTES))
    granit = next(l for l in lines if "Гранит" in l["name"])
    assert granit["price"] == 2300.0
    assert granit["basis"].startswith("КАЦ")
    assert granit["source"] == "КП-2"


def test_to_xlsx(tmp_path: Path):
    out = tmp_path / "kac.xlsx"
    to_xlsx(analyze_kac(QUOTES), str(out))
    assert out.is_file() and out.stat().st_size > 0


def test_needs_kac_without_book(monkeypatch):
    monkeypatch.setattr(fps, "available_pricebooks", lambda *a, **k: [])
    r = needs_kac("99.99.99-999")
    assert r["needs_kac"] is True and r["in_fgis"] is False


def test_classifier_recognizes_kp():
    res = classify_table(["Наименование", "Цена", "Поставщик", "Ед.изм"],
                         title="Коммерческое предложение № 5")
    assert res["type"] == "коммерческое_предложение"
