"""НР/СП по виду работ: сопоставление нормы → нормативы.

Значения сверены с официальными Приказами Минстроя:
  НР — 812/пр (графа «Территория»), СП — 774/пр. Кровли дополнительно сверены на эталоне.
"""

from __future__ import annotations

from proxy.services.nr_sp_service import resolve


def test_kровли_verified():
    r = resolve("Устройство обрешётки с прозорами из брусков")
    assert r["nr_pct"] == 109 and r["sp_pct"] == 57
    assert r["label"] == "Кровли" and r["default"] is False
    assert resolve("Монтаж медного отлива")["label"] == "Кровли"   # «отлив»


def test_otdelochnye_from_orders():
    # Пр/812-15 = 100, Пр/774-15 = 49 (Отделочные работы)
    r = resolve("Штукатурка поверхностей стен по камню")
    assert r["nr_pct"] == 100 and r["sp_pct"] == 49
    assert r["default"] is False


def test_zemlyanye_from_orders():
    # Пр/812-1.1 = 92, Пр/774-1.1 = 46 (Земляные, механизированным способом)
    r = resolve("Разработка грунта в котловане экскаватором")
    assert r["nr_pct"] == 92 and r["sp_pct"] == 46
    assert r["default"] is False


def test_kirpich_from_orders():
    # Пр/812-8 = 110, Пр/774-8 = 69 (Конструкции из кирпича и блоков)
    r = resolve("Кладка стен из кирпича")
    assert r["nr_pct"] == 110 and r["sp_pct"] == 69
    assert r["default"] is False


def test_santehnika_from_orders():
    # Пр/812-16 = 121, Пр/774-16 = 72 (Сантехнические внутренние)
    r = resolve("Прокладка трубопроводов отопления")
    assert r["nr_pct"] == 121 and r["sp_pct"] == 72
    assert r["default"] is False


def test_default_for_unknown():
    # Вид без своего ключа → дефолт (Отделочные, сб.15: 100/49). default=True.
    r = resolve("Пусконаладочные работы систем автоматики XYZ")
    assert r["default"] is True
    assert r["nr_pct"] > 0 and r["sp_pct"] > 0
    assert resolve("")["default"] is True
