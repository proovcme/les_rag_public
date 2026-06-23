"""НР/СП по виду работ: сопоставление нормы → нормативы (Кровли сверено; дефолт для прочего)."""

from __future__ import annotations

from proxy.services.nr_sp_service import resolve


def test_kровли_verified():
    r = resolve("Устройство обрешётки с прозорами из брусков")
    assert r["nr_pct"] == 109 and r["sp_pct"] == 57
    assert r["label"] == "Кровли" and r["default"] is False
    assert resolve("Монтаж медного отлива")["label"] == "Кровли"   # «отлив»


def test_default_for_unknown():
    r = resolve("Устройство стяжек цементных")
    assert r["default"] is True                  # не Кровли → дефолт-плейсхолдер
    assert r["nr_pct"] > 0 and r["sp_pct"] > 0
    assert resolve("")["default"] is True
