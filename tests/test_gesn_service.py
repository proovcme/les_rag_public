"""ГЭСН: норма→ресурсы и сборка ЛСР прямо от кода (gold = позиция эталона = 11813.04)."""

from __future__ import annotations

from proxy.services.gesn_service import expand_position, get_norm, list_norms
from proxy.services.lsr_assembly_service import compute_position

CODE = "ГЭСН12-01-034-02"


def test_norm_loaded():
    assert get_norm(CODE)["unit"] == "100 м2"
    assert get_norm("гэсн12-01-034-02") is not None     # регистр/нормализация
    assert any(n["code"] == CODE for n in list_norms())
    assert get_norm("НЕТ-ТАКОЙ") is None


def test_expand_multiplies_by_volume():
    lines = expand_position(CODE, 0.61)
    assert lines is not None and len(lines) == 8
    labor = next(l for l in lines if l["kind"] == "labor")
    assert round(labor["qty"], 4) == 7.8934              # 12.94 × 0.61
    mat = next(l for l in lines if l["kind"] == "material")
    assert round(mat["qty"], 6) == 0.000915              # 0.0015 × 0.61
    assert expand_position("НЕТ", 1) is None


def test_assemble_from_code_reproduces_etalon():
    # позиция БЕЗ ресурсов — только код+объём; движок разворачивает по норме ГЭСН
    pos = {"code": CODE, "name": "Обрешётка", "qty": 0.61, "nr_pct": 109, "sp_pct": 57}
    r = compute_position(pos)
    assert r["flags"] == []
    b = r["base"]
    assert b["ozp"] == 3750.23
    assert b["em"] == 992.40
    assert b["mat"] == 83.62
    assert b["fot"] == 4208.91
    assert r["total"] == 11813.04                        # Всего по позиции — как в эталоне


def test_unknown_code_flagged():
    r = compute_position({"code": "ГЭСН99-99-999-99", "qty": 1})
    assert r["flags"] and "норма ГЭСН не найдена" in r["flags"][0]
