"""Коэффициент стеснённости: каталог условий + пересчёт позиции ЛСР (ОЗП/ЭМ→ФОТ/НР/СП/Всего)."""

from __future__ import annotations

import pytest

from proxy.services.stesnennost_service import (
    apply,
    apply_position,
    get_condition,
    list_conditions,
)

POS = {"name": "обрешётка", "ozp": 1000, "em": 200, "zpm": 150, "mat": 300, "nr_pct": 100, "sp_pct": 50}


def test_catalog_loads():
    ids = {c["id"] for c in list_conditions()}
    assert "city_dense" in ids
    assert get_condition("city_dense")["k_ozp"] == 1.15
    assert get_condition("Стеснённые условия застроенной части города")["id"] == "city_dense"
    assert get_condition("нет такого") is None


def test_apply_position_recompute():
    r = apply_position(POS, k_ozp=1.2, k_em=1.1)
    # база: direct=1500, fot=1150, nr=1150, sp=575, total=3225
    assert r["base"]["total"] == 3225.0
    assert r["base"]["fot"] == 1150.0
    # скорр: озп 1200, эм 220, зпм 165 → direct=1720, fot=1365, nr=1365, sp=682.5, total=3767.5
    assert r["adjusted"]["ozp"] == 1200.0
    assert r["adjusted"]["em"] == 220.0
    assert r["adjusted"]["fot"] == 1365.0
    assert r["adjusted"]["total"] == 3767.5
    assert r["uplift"] == 542.5
    assert r["base"]["mat"] == r["adjusted"]["mat"]  # материалы не затронуты


def test_apply_by_condition():
    res = apply([POS], condition="city_dense")
    assert res["k_ozp"] == 1.15 and res["k_em"] == 1.15
    assert res["condition"] == "city_dense"
    assert res["summary"]["adjusted_total"] > res["summary"]["base_total"]
    assert res["summary"]["uplift"] == round(
        res["summary"]["adjusted_total"] - res["summary"]["base_total"], 2
    )


def test_apply_requires_condition_or_k():
    with pytest.raises(ValueError):
        apply([POS])
    with pytest.raises(ValueError):
        apply([POS], condition="несуществующее")


def test_manual_k_overrides():
    res = apply([POS], k_ozp=1.25, k_em=1.25)
    assert res["k_ozp"] == 1.25 and res["condition"] is None
