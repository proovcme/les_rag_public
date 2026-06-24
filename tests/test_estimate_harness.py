"""Сметный харнесс — петля инструментов на объекте ВНЕ YAML (паркинг).

Модель скриптуется (детерминированно) — проверяем МЕХАНИКУ харнесса, не качество LLM:
схема → кандидаты ГЭСН → позиции (computed + needs_input) → предварительный итог. Числа из кода.
"""

import json

from proxy.services import estimate_harness_service as h


def test_search_norm_is_thin_candidate_finder():
    # тонкий кандидатор, не магия: статус + кандидаты, не «один правильный»
    r = h.search_norm("устройство бетонных фундаментов")
    assert r["status"] in ("found", "ambiguous")
    assert r["candidates"] and all("norm_code" in c for c in r["candidates"])

    assert h.search_norm("жжжыыы щщщъъъ ёёёххх ыфвапр")["status"] == "not_found"


def test_validate_schema_requires_object_and_area():
    bad = h._validate_schema({"object_type": "parking"})
    assert bad["ok"] is False and "area_total_m2" in bad["missing_required"]
    good = h._validate_schema({"object_type": "parking", "area_total_m2": 4800, "levels_below_ground": 2})
    assert good["ok"] is True and good["geometry"]["S1"] > 0


def test_harness_loop_on_parking_preliminary():
    """Скрипт «модели»: схема паркинга → норма → 2 позиции (одна computed, одна needs_input) → финал."""
    script = [
        json.dumps({"tool": "propose_schema", "args": {
            "object_type": "underground_parking", "area_total_m2": 4800,
            "levels_below_ground": 2, "structural_system": "monolithic_rc",
            "included_sections": ["foundation", "monolithic_frame", "waterproofing"],
            "excluded_sections": ["mep", "finishes"],
            "missing_inputs": ["soil_category", "concrete_class"]}}),
        json.dumps({"tool": "search_norm", "args": {"work_description": "бетонные фундаменты", "unit_hint": "м3"}}),
        # позиция считается из геометрии (S1, толщина 0.4) — число из формулы
        json.dumps({"tool": "add_position", "args": {
            "work": "Фундаментная плита", "code": "06-02-001-01", "unit": "100 м3",
            "qty_formula": "S1*0.4/100", "assumptions": ["толщина плиты 0.4 м (нет данных)"]}}),
        # позиция, где формула требует ОТСУТСТВУЮЩИЙ параметр → needs_input (не считаем молча)
        json.dumps({"tool": "add_position", "args": {
            "work": "Гидроизоляция (зависит от глубины)", "code": "06-02-001-01", "unit": "100 м2",
            "qty_formula": "P*depth/100"}}),
        json.dumps({"final": True}),
    ]
    calls = {"i": 0}

    def complete(_messages):
        i = calls["i"]; calls["i"] += 1
        return script[i] if i < len(script) else json.dumps({"final": True})

    res = h.run_estimate_harness("подземный паркинг 4800 м² 2 уровня", complete, max_steps=10)

    assert res["preliminary"] is True
    # одна позиция посчитана из формулы (число из кода), одна — needs_input (не выдумана)
    assert len(res["computed"]) == 1
    assert res["computed"][0]["code"] == "06-02-001-01"
    assert res["computed"][0]["qty"] > 0                      # qty = S1*0.4/100, посчитан кодом
    assert len(res["needs_input"]) == 1                       # гидроизоляция без глубины
    assert res["by_assumption"]                               # плита по допущению о толщине
    assert res["totals"]["grand_total"] >= 0                  # итог из ЛСР-сборки
    assert res["schema"]["object_type"] == "underground_parking"
    # trace показывает петлю инструментов
    tools = [t["tool"] for t in res["trace"]]
    assert tools == ["propose_schema", "search_norm", "add_position", "add_position"]


def test_harness_no_numbers_from_model_text():
    """Если «модель» вернёт прозу с числом вместо JSON — оно НЕ попадёт в смету (нет tool-call)."""
    def complete(_messages):
        return "Итого примерно 5 миллионов рублей."  # не JSON → игнор, число не учитывается
    res = h.run_estimate_harness("гараж 50 м²", complete, max_steps=3)
    assert res["totals"]["grand_total"] == 0.0               # ни одной позиции из текста
    assert res["computed"] == []
