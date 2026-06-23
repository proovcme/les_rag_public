"""Ц16: фраза → ВОР (детерминированные объёмы) → ЛСР-смета с итогом. 0 LLM в расчёте (ADR-11)."""

from __future__ import annotations

import math

import pytest

from proxy.services import object_estimate_service as oes


# ── разбор фразы ─────────────────────────────────────────────────────────────────────────

def test_parse_request_wooden_two_floors_100():
    p = oes.parse_request("дай смету на деревянный двухэтажный дом площадью 100 метров")
    assert p["material"] == "дерево"
    assert p["floors"] == 2
    assert p["area"] == 100.0
    assert p["object"] == "дом"
    assert p["source"] == "deterministic"  # без сети/LLM


@pytest.mark.parametrize(
    "phrase,floors,area",
    [
        ("деревянный одноэтажный дом 80 м²", 1, 80.0),
        ("брусовой дом площадью 120 кв.м в два этажа", None, 120.0),  # этажность словом отсутствует
        ("сруб 2-этажный 100 м2", 2, 100.0),
    ],
)
def test_parse_variants(phrase, floors, area):
    p = oes.parse_request(phrase)
    assert p["area"] == area
    if floors is not None:
        assert p["floors"] == floors


# ── геометрия / объёмы ВОР (детерминированы) ─────────────────────────────────────────────

def test_build_vor_volumes_are_deterministic():
    tpl = next(t for t in oes.load_templates() if t["id"] == "wooden_house")
    parsed = {"area": 100.0, "floors": 2}
    vor = oes.build_vor(tpl, parsed)

    # P = 4·sqrt(S/N) = 4·sqrt(50)
    P = 4.0 * math.sqrt(50.0)
    assert vor["params"]["P"] == round(P, 4)
    assert vor["params"]["S1"] == 50.0
    assert vor["params"]["N"] == 2

    by_code = {v["code"]: v for v in vor["positions"]}
    # фундамент: P × 0.30 / 100 (qty округляется до 6 знаков в движке формул)
    assert by_code["06-02-001-01"]["qty"] == pytest.approx(P * 0.30 / 100, abs=1e-5)
    # стены: P × H(3.0) × N(2) / 100
    assert by_code["10-02-024-02"]["qty"] == pytest.approx(P * 3.0 * 2 / 100, abs=1e-5)
    # перекрытия: S1(50) × N(2) / 100 = 1.0
    assert by_code["10-02-007-01"]["qty"] == pytest.approx(1.0, rel=1e-9)
    # кровля/обрешётка: S1(50) × 1.20 / 100 = 0.60
    assert by_code["12-01-034-02"]["qty"] == pytest.approx(0.60, rel=1e-9)
    assert by_code["12-01-023-01"]["qty"] == pytest.approx(0.60, rel=1e-9)
    # полы: S(100) / 100 = 1.0
    assert by_code["11-01-033-01"]["qty"] == pytest.approx(1.0, rel=1e-9)


def test_formula_eval_rejects_injection():
    with pytest.raises(ValueError):
        oes._eval_formula("__import__('os').system('echo x')", {"S": 1.0})


# ── end-to-end: смета собирается с итогом ────────────────────────────────────────────────

def test_estimate_end_to_end_assembles_total():
    r = oes.estimate("дай смету на деревянный двухэтажный дом 100 м²")
    assert r["ok"] is True
    assert r["template"]["id"] == "wooden_house"
    assert r["parsed"]["material"] == "дерево"
    assert r["parsed"]["floors"] == 2
    assert r["parsed"]["area"] == 100.0

    # ВОР непустой, объёмы перенесены в позиции движка
    assert len(r["vor"]["positions"]) == 6

    summary = r["estimate"]["summary"]
    # хотя бы часть норм нашлась локально → позиции собрались
    assert summary["positions"] >= 1
    # итог собран и положителен (числа из норм, не из LLM)
    assert summary["total"] > 0
    # каждая собранная позиция несёт итог
    for pos in r["estimate"]["positions"]:
        assert pos["total"] >= 0
        assert pos["qty"] > 0

    # допущения по геометрии присутствуют (прозрачность)
    assert any("P = 4" in a for a in r["assumptions"])


def test_estimate_needs_area():
    r = oes.estimate("дай смету на деревянный дом")
    assert r["ok"] is False
    assert "площад" in r["error"].lower()


def test_estimate_unknown_object_no_template():
    r = oes.estimate("дай смету на кирпичный дом 100 м²")
    assert r["ok"] is False  # шаблон только под дерево
