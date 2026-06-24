"""Сметный харнесс + Quality Gate 1 — петля и предохранители на объекте ВНЕ YAML (паркинг).

Проверяем МЕХАНИКУ и GATE (не качество LLM): unit-контракт, применимость сборника, magnitude,
needs_input, блокировку итога. Числа из кода. 7 критериев готовности из ТЗ.
"""

import json

from proxy.services import estimate_harness_service as h
from proxy.services.object_estimate_service import _geometry


def _state(area=3000, floors=3):
    """state с готовой геометрией (S1=area/floors)."""
    return {"schema": {}, "geom": _geometry(area, floors, {"geometry": {"H": 3.0}}),
            "positions": [], "steps": 0}


# ── search_norm: тонкий кандидатор + фильтр применимости ──────────────────────────────────

def test_search_norm_thin_and_collection_filtered():
    r = h.search_norm("разработка грунта котлован", work_family="earthworks", unit_hint="м3")
    assert r["status"] in ("found", "ambiguous", "not_found")
    # все кандидаты — только из разрешённого сборника 01; чужие — в rejected
    for c in r.get("candidates", []):
        assert c["collection"] == "01"
    assert h.search_norm("жжжыыы щщщъъъ ёёёххх")["status"] == "not_found"


# ── (1) UNIT CONTRACT: физический объём → измеритель нормы (код, не модель) ───────────────

def test_unit_conversion_physical_to_norm_measure():
    st = _state()                                  # S1 = 1000
    obs = h._add_position({"work": "плита", "code": "06-02-001-01", "work_family": "concrete_monolithic",
                           "physical_unit": "м3", "qty_formula": "S1*0.4"}, st)   # физ = 400 м³
    assert obs["status"] == "computed"
    assert obs["phys_qty"] == 400.0
    assert obs["quantity_for_estimate"] == 4.0     # 400 / 100 (норма «100 м3») — НЕ 400


# ── (2) несовместимая единица → needs_input ──────────────────────────────────────────────

def test_incompatible_unit_needs_input():
    st = _state()
    obs = h._add_position({"work": "x", "code": "12-01-021-01", "work_family": "roofing",
                           "physical_unit": "м3", "qty_formula": "S1"}, st)  # норма в м2, физ в м3
    assert obs["status"] == "needs_input"
    assert "несовместима" in obs["reason"]


# ── (3) запрещённый сборник для семейства → rejected ─────────────────────────────────────

def test_disallowed_collection_rejected():
    st = _state()
    obs = h._add_position({"work": "котлован", "code": "06-02-001-01", "work_family": "earthworks",
                           "physical_unit": "м3", "qty_formula": "S1"}, st)  # 06 не для earthworks(01)
    assert obs["status"] == "rejected_collection"


# ── (4) нет параметра в формуле → needs_input (не молча) ─────────────────────────────────

def test_missing_param_needs_input():
    st = _state()
    obs = h._add_position({"work": "гидро", "code": "06-02-001-01", "work_family": "concrete_monolithic",
                           "physical_unit": "м3", "qty_formula": "S1*depth"}, st)  # depth нет в геометрии
    assert obs["status"] == "needs_input"


# ── (6) magnitude guard блокирует порядковый бред ────────────────────────────────────────

def test_magnitude_guard_blocks_order_of_magnitude():
    st = _state()
    obs = h._add_position({"work": "котлован", "code": "06-02-001-01", "work_family": "concrete_monolithic",
                           "physical_unit": "м3", "qty_formula": "S1*1000"}, st)  # 1 млн м³ — бред
    assert obs["status"] == "rejected_magnitude"
    assert obs["phys_qty"] > obs["upper_bound"]


# ── (5)+(7) допущение → by_assumption; critical → итог НЕ как сумма ───────────────────────

def test_finalize_marks_assumptions_and_blocks_total_on_critical():
    st = _state()
    h._add_position({"work": "плита", "code": "06-02-001-01", "work_family": "concrete_monolithic",
                     "physical_unit": "м3", "qty_formula": "S1*0.4", "assumptions": ["толщина 0.4 (нет данных)"]}, st)
    h._add_position({"work": "бред", "code": "06-02-001-01", "work_family": "concrete_monolithic",
                     "physical_unit": "м3", "qty_formula": "S1*1000"}, st)   # rejected_magnitude
    res = h._finalize(st)
    assert res["by_assumption"]                    # плита по допущению
    assert res["rejected"]                         # бред отклонён
    assert res["total_blocked"] is True            # есть critical → итог не как сумма
    assert res["totals"] is None


# ── end-to-end петля (скриптовая модель) ─────────────────────────────────────────────────

def test_harness_loop_end_to_end_parking():
    script = [
        json.dumps({"tool": "propose_schema", "args": {"object_type": "underground_parking",
                    "area_total_m2": 4800, "levels_below_ground": 2, "structural_system": "monolithic_rc",
                    "missing_inputs": ["soil_category"]}}),
        json.dumps({"tool": "add_position", "args": {"work": "Фунд. плита", "code": "06-02-001-01",
                    "work_family": "concrete_monolithic", "physical_unit": "м3", "qty_formula": "S1*0.4"}}),
        json.dumps({"final": True}),
    ]
    calls = {"i": 0}

    def complete(_m):
        i = calls["i"]; calls["i"] += 1
        return script[i] if i < len(script) else json.dumps({"final": True})

    res = h.run_estimate_harness("подземный паркинг 4800 м² 2 уровня", complete, max_steps=8)
    assert res["preliminary"] is True
    assert len(res["computed"]) == 1
    assert res["computed"][0]["qty"] > 0
    assert res["total_blocked"] is False           # критичных нет → итог есть
    assert res["totals"]["grand_total"] > 0
    assert [t["tool"] for t in res["trace"]] == ["propose_schema", "add_position"]


def test_no_numbers_from_model_text():
    res = h.run_estimate_harness("гараж 50 м²", lambda _m: "Итого 5 миллионов.", max_steps=3)
    assert res["computed"] == []
