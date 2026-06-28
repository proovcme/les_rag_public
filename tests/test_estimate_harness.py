"""Сметный харнесс + Quality Gate 1 — петля и предохранители на объекте ВНЕ YAML (паркинг).

Проверяем МЕХАНИКУ и GATE (не качество LLM): unit-контракт, применимость сборника, magnitude,
needs_input, блокировку итога. Числа из кода. 7 критериев готовности из ТЗ.
"""

import json

from proxy.services import estimate_harness_service as h
from proxy.services.estimate_math_service import _geometry


def _state(area=3000, floors=3):
    """state с готовой геометрией (S1=area/floors)."""
    return {"schema": {}, "geom": _geometry(area, floors, {"geometry": {"H": 3.0}}),
            "positions": [], "steps": 0}


# ── search_norm: тонкий кандидатор + фильтр применимости ──────────────────────────────────

def test_search_norm_thin_and_no_match():
    assert h.search_norm("жжжыыы щщщъъъ ёёёххх")["status"] == "not_found"


def test_collection_of_prefixed_norm_code():
    assert h._collection_of("ГЭСН:10-02-024-02") == "10"
    assert h._collection_of("12-01-023-01") == "12"


def test_search_rejects_wrong_collection_for_work_family():
    r = h.search_norm("каркасные стены деревянные", work_family="wood",
                      element_type="wood_wall", unit_hint="м2")
    assert r["candidates"]
    wrong = [c for c in r["candidates"] if c["collection"] != "10"]
    assert wrong
    assert all(c["applicability_status"] == "rejected" for c in wrong)


def test_work_item_normalization_repairs_frame_wall_family():
    item = {
        "work": "каркасно-щитовые работы",
        "work_description": "каркасно-щитовые работы стены",
        "work_family": "metal",
        "element_type": "metal_assembly",
        "action": "assemble",
        "unit_hint": "m2",
    }

    norm, corrections = h._normalize_work_item(item)

    assert norm["work_family"] == "wood"
    assert norm["element_type"] == "wood_wall"
    assert norm["action"] == "монтаж"
    assert norm["unit_hint"] == "м2"
    assert corrections


def test_normalized_frame_wall_search_stays_in_wood_collection():
    item = {
        "work": "каркасно-щитовые работы",
        "work_description": "каркасно-щитовые работы стены",
        "work_family": "metal",
        "element_type": "metal_assembly",
        "action": "assemble",
        "unit_hint": "m2",
    }
    norm, _ = h._normalize_work_item(item)
    r = h.search_norm(norm["work_description"], work_family=norm["work_family"],
                      element_type=norm["element_type"], action=norm["action"],
                      unit_hint=norm["unit_hint"])

    assert r["candidates"]
    assert r["candidates"][0]["collection"] == "10"


def test_work_item_normalization_routes_engineering_networks_to_mep_not_finishes():
    item = {
        "work": "устройство_инженерных_сетей",
        "work_description": "устройство инженерных сетей дома",
        "work_family": "finishes",
        "element_type": "finishes",
        "action": "устройство",
        "unit_hint": "м2",
    }

    norm, corrections = h._normalize_work_item(item)

    assert norm["work_family"] == "mep"
    assert norm["element_type"] == "engineering_networks"
    assert corrections


def test_excavation_signal_wins_over_pile_when_work_is_pit():
    item = {
        "work": "разработка котлована под свайный фундамент",
        "work_description": "разработка котлована под свайный фундамент",
        "work_family": "foundation",
        "element_type": "pile",
        "action": "разработка",
        "unit_hint": "м3",
    }

    norm, corrections = h._normalize_work_item(item)

    assert norm["work_family"] == "earthworks"
    assert norm["element_type"] == "excavation"
    assert corrections


def test_engineering_networks_do_not_bind_to_finishes_collection():
    r = h.search_norm(
        "устройство инженерных сетей водопровод канализация отопление",
        work_family="mep",
        element_type="engineering_networks",
        unit_hint="м2",
    )

    assert all(c["collection"] != "15" for c in r["candidates"])


def test_engineering_networks_without_scope_need_mep_inputs():
    st = _state(area=150, floors=1)
    obs = h._add_position({
        "work": "инженерные сети",
        "code": "16-02-004-05",
        "work_family": "mep",
        "element_type": "engineering_networks",
    }, st)

    assert obs["status"] == "needs_input"
    assert "ВК/ОВ/ЭОМ/СС" in obs["reason"]


def test_extract_json_from_markdown_wrapped_response():
    obj = h._extract_json("план ниже:\n```json\n{\"object\":{\"area_total_m2\":150},\"works\":[]}\n```")
    assert obj == {"object": {"area_total_m2": 150}, "works": []}


def test_batch_plan_repairs_first_non_json_response():
    responses = iter([
        "Я разложу объект на работы, но сейчас отвечу текстом.",
        '{"object":{"object_type":"house","area_total_m2":150,"floors":1},'
        '"works":[["кровля","устройство кровли","roofing","roofing","устройство","м2",{}]]}',
    ])

    res = h.run_estimate_harness("дом 150 м2", lambda _messages: next(responses))

    assert res["planner_status"] == "batch"
    assert res["trace"][0] == {"tool": "planner_repair", "status": "ok"}


def test_smeta_planner_prompt_includes_gesn_notebook_and_no_object_templates(monkeypatch):
    monkeypatch.setattr(h, "gesn_notebook_prompt_excerpt", lambda: "[Блокнот ГЭСН]\n01: земляные работы")
    seen = []

    def complete(messages):
        seen.append(messages)
        return '{"final": true}'

    res = h.run_estimate_harness("дом 150 м2", complete)

    system = seen[0][0]["content"]
    assert system.startswith("/no_think")
    assert "Л.Е.С." in system
    assert "Режим «Смета»" in system
    assert "[Блокнот ГЭСН]" in system
    assert "object_templates" not in system
    assert res["notebook_context"]["service_notebooks"] == ["gesn"]


def test_batch_plan_repairs_incomplete_json_plan():
    responses = iter([
        '{"object":{"floors":1}, "works":[]}',
        '{"object":{"object_type":"house","area_total_m2":150,"floors":1}, "works":[]}',
    ])

    res = h.run_estimate_harness("дом 150 м2", lambda _messages: next(responses))

    assert res["planner_status"] == "batch"
    assert res["trace"][0]["tool"] == "planner_schema_repair"
    assert res["trace"][0]["status"] == "err"


def test_batch_plan_uses_schema_repair_when_complete():
    responses = iter([
        '{"object":{"floors":1}, "works":[]}',
        '{"object":{"object_type":"house","area_total_m2":150,"floors":1},'
        '"works":[["кровля","устройство кровли","roofing","roofing","устройство","м2",{}]]}',
    ])

    res = h.run_estimate_harness("дом 150 м2 кровля", lambda _messages: next(responses))

    assert res["planner_status"] == "batch"
    assert res["trace"][0]["tool"] == "planner_schema_repair"
    assert res["trace"][0]["status"] == "ok"


# ── Gate 3: структурный ranking — хорошее всплывает, спец тонет ───────────────────────────

def test_score_forbidden_anchor_heavy_penalty():
    sc = h._score_candidate(["бетонирование", "плиты"], "06-22-003-05",
                            "бетонирование плиты защитной оболочки реактора", "100 м3",
                            work_family="concrete_monolithic", element_type="foundation_slab",
                            action="бетонирование", phys_unit="м3")
    assert sc is not None and sc[1].get("forbidden", 0) < 0 and sc[0] < 3  # утоплен


def test_score_element_anchor_boost():
    sc = h._score_candidate(["устройство", "фундамент"], "06-02-001-04",
                            "устройство железобетонных фундаментов общего назначения", "100 м3",
                            work_family="concrete_monolithic", element_type="foundation_slab",
                            action="устройство", phys_unit="м3")
    assert sc is not None and sc[1].get("element", 0) > 0 and sc[0] > 3   # поднят


def test_search_general_code_outranks_reactor():
    r = h.search_norm("устройство монолитной железобетонной фундаментной плиты",
                      work_family="concrete_monolithic", element_type="foundation_slab", unit_hint="м3")
    assert r["candidates"]
    top = r["candidates"][0]
    assert top["applicability_status"] == "accepted"        # лидер применим
    assert not top["norm_code"].startswith("06-22")         # не реактор
    # любой forbidden-кандидат имеет отрицательный score_part forbidden
    for c in r["candidates"]:
        if any(a in c["title"].lower() for a in ("реактор", "оболочк")):
            assert c["score_parts"].get("forbidden", 0) < 0


def test_search_candidates_carry_score_parts_for_trace():
    r = h.search_norm("разработка грунта котлована", work_family="earthworks",
                      element_type="excavation", unit_hint="м3")
    for c in r["candidates"]:
        assert "score_total" in c and "score_parts" in c and "applicability_status" in c
    assert r["selection"]["schema"] == "candidate_selection_v1"


def test_candidate_selection_clear_leader_contract():
    candidates = [
        {"norm_code": "01-02-056-01", "title": "разработка грунта котлована",
         "measure_unit": "100 м3", "score_total": 8.0, "score_parts": {"unit": 1, "element": 3},
         "applicability_status": "accepted", "unit_compatible": True},
        {"norm_code": "01-01-001-01", "title": "прочая земляная работа",
         "measure_unit": "100 м3", "score_total": 5.7, "score_parts": {"unit": 1},
         "applicability_status": "accepted", "unit_compatible": True},
    ]

    s = h._candidate_selection(candidates)

    assert s["action"] == "bind_top_candidate"
    assert s["selected_code"] == "01-02-056-01"
    assert s["score_gap"] == 2.3
    assert s["shortlist"][0]["reasons"]


def test_candidate_selection_small_gap_goes_back_to_model():
    candidates = [
        {"norm_code": "10-02-017-03", "title": "стены каркасные",
         "measure_unit": "100 м2", "score_total": 7.0, "score_parts": {"unit": 1, "element": 3},
         "applicability_status": "accepted", "unit_compatible": True},
        {"norm_code": "10-01-011-01", "title": "стены деревянные",
         "measure_unit": "100 м2", "score_total": 6.2, "score_parts": {"unit": 1, "family": 1},
         "applicability_status": "accepted", "unit_compatible": True},
    ]

    s = h._candidate_selection(candidates)

    assert s["status"] == "needs_model_choice"
    assert s["action"] == "ask_model_to_choose_or_request_input"
    assert s["selected_code"] == ""


def test_bind_accepts_top_applicable_general_code():
    st = _state()
    obs = h._add_position({"work": "Фунд. плита", "code": "06-02-001-04", "work_family": "concrete_monolithic",
                           "physical_unit": "м3", "qty_formula": "S1*0.4"}, st)
    assert obs["status"] == "computed"                      # general accepted → считается


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


# ── (5)+(7) допущение → by_assumption; critical → итог partial, final_total None ──────────

def test_finalize_marks_assumptions_and_partial_on_critical():
    st = _state()
    h._add_position({"work": "плита", "code": "06-02-001-01", "work_family": "concrete_monolithic",
                     "physical_unit": "м3", "qty_formula": "S1*0.4", "assumptions": ["толщина 0.4 (нет данных)"]}, st)
    h._add_position({"work": "бред", "code": "06-02-001-01", "work_family": "concrete_monolithic",
                     "physical_unit": "м3", "qty_formula": "S1*1000"}, st)   # rejected_magnitude
    res = h._finalize(st)
    assert res["by_assumption"]                    # плита по допущению
    assert res["rejected"]                         # бред отклонён
    assert res["total_status"] == "partial"        # есть computed + critical
    assert res["final_total"] is None              # final НЕ показываем
    assert res["partial_total"]["grand_total"] > 0 # partial как диагностика существует
    assert res["blockers"]                          # blocker с причиной


# ── Gate 2: ПРИМЕНИМОСТЬ нормы (барьер между кандидатом и числом) ─────────────────────────

def test_applicability_rejects_forbidden_title_anchor():
    st, rs = "rejected", h.check_applicability(
        "06-22-003-05", "Бетонирование плиты защитной оболочки реактора", "concrete_monolithic")
    assert rs[0] == st and rs[1]


def test_applicability_rejects_denied_subsection():
    s, _ = h.check_applicability("06-22-001-01", "обычное бетонирование плиты", "concrete_monolithic")
    assert s == "rejected"                         # 06-22 в denied prefixes


def test_applicability_accepts_regular_concrete():
    s, _ = h.check_applicability("06-02-001-01", "Устройство бетонных фундаментов общего назначения",
                                 "concrete_monolithic")
    assert s == "accepted"


def test_applicability_ambiguous_when_no_positive_anchor():
    s, _ = h.check_applicability("06-50-001-01", "устройство некоего объекта общего", "concrete_monolithic")
    assert s == "ambiguous"                        # сб.06, но в названии нет признаков бетона


def test_add_position_rejects_reactor_norm_not_computed():
    """Живой реакторный код (06-22-003-05) НЕ становится computed-позицией."""
    st = _state()
    obs = h._add_position({"work": "плита", "code": "06-22-003-05", "work_family": "concrete_monolithic",
                           "physical_unit": "м3", "qty_formula": "S1*0.4"}, st)
    assert obs["status"] in ("rejected_applicability", "rejected_collection")
    res = h._finalize(st)
    assert res["computed"] == []                   # в итог не попал
    assert res["total_status"] == "blocked"


def test_search_norm_marks_applicability_status():
    r = h.search_norm("бетонирование плиты", work_family="concrete_monolithic", unit_hint="м3")
    for c in r.get("candidates", []):
        assert c["applicability_status"] in ("accepted", "ambiguous", "rejected")


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
    assert res["total_status"] == "complete"       # одна accepted-позиция, критичных/нет-данных нет
    assert res["final_total"]["grand_total"] > 0
    assert [t["tool"] for t in res["trace"]] == ["propose_schema", "add_position"]


def test_batch_plan_calls_model_once_and_surfaces_gesn_candidates():
    plan = {
        "object_schema": {"object_type": "underground_parking", "area_total_m2": 4800,
                          "levels_below_ground": 2, "structural_system": "monolithic_rc"},
        "work_items": [
            {"work": "Фундаментная плита",
             "work_description": "устройство монолитной железобетонной фундаментной плиты",
             "work_family": "concrete_monolithic", "element_type": "foundation_slab",
             "action": "устройство", "unit_hint": "м3", "slots": {"slab_thickness_m": 0.4}},
        ],
    }
    calls = {"n": 0}

    def complete(_m):
        calls["n"] += 1
        return json.dumps(plan, ensure_ascii=False)

    res = h.run_estimate_harness("паркинг 4800 м², плита 400 мм", complete)

    assert calls["n"] == 1
    assert res["planner_status"] == "batch"
    assert res["trace"][0]["tool"] == "propose_schema"
    assert res["trace"][1]["tool"] == "search_norm"
    assert res["trace"][1]["candidates"]       # номера ГЭСН видны для operator review
    assert res["trace"][1]["selection"]["schema"] == "candidate_selection_v1"
    assert res["computed"]                     # черновую стоимость считаем по лучшему применимому кандидату
    assert res["computed"][0]["code"].startswith("ГЭСН:06-02")
    assert any("требуется проверка" in a for a in res["computed"][0]["assumptions"])
    assert res["by_assumption"]
    assert res["final_total"]["grand_total"] > 0


def test_compact_batch_plan_array_contract():
    plan = {
        "object": {"object_type": "residential_house", "area_total_m2": 150, "floors": 1,
                   "levels_below_ground": 0, "structural_system": "frame"},
        "works": [
            ["Устройство кровли", "Устройство двускатной кровли", "roofing", "roofing",
             "устройство", "м2", {}],
            ["Каркасные стены", "Устройство деревянных каркасных стен", "wood", "wood_wall",
             "устройство", "м2", {}],
        ],
    }

    res = h.run_estimate_harness("дача 150 м²", lambda _m: json.dumps(plan, ensure_ascii=False))

    assert res["planner_status"] == "batch"
    assert res["schema"]["object_type"] == "residential_house"
    assert [t["tool"] for t in res["trace"]].count("search_norm") == 2
    assert all(t["candidates"] for t in res["trace"] if t["tool"] == "search_norm")
    assert any(p["code"].startswith("ГЭСН:12-") for p in res["computed"])
    roof = next(p for p in res["computed"] if p["code"].startswith("ГЭСН:12-"))
    assert any("первый кандидат не прошёл" in a for a in roof["assumptions"])


def test_batch_plan_binds_first_unit_compatible_roof_candidate():
    plan = {
        "object": {"object_type": "residential_house", "area_total_m2": 150, "floors": 1},
        "works": [
            ["Кровельные работы", "Устройство двускатной кровли", "roofing", "roofing",
             "устройство", "м2", {}],
        ],
    }

    res = h.run_estimate_harness("дача 150 м² двускатная кровля", lambda _m: json.dumps(plan, ensure_ascii=False))

    assert res["computed"]
    assert res["computed"][0]["code"] != "ГЭСН:12-01-041-01"
    assert res["computed"][0]["physical_unit"] == "м2"
    add_trace = [t for t in res["trace"] if t["tool"] == "add_position"][0]
    assert add_trace["candidate_index"] > 0


def test_batch_plan_trace_reports_tool_argument_normalization():
    plan = {
        "object": {"object_type": "residential_house", "area_total_m2": 150, "floors": 1},
        "works": [
            ["каркасно-щитовые работы", "каркасно-щитовые работы стены",
             "metal", "metal_assembly", "assemble", "m2", {}],
        ],
    }

    res = h.run_estimate_harness("дача 150 м²", lambda _m: json.dumps(plan, ensure_ascii=False))

    search_trace = [t for t in res["trace"] if t["tool"] == "search_norm"][0]
    assert search_trace["normalized"]
    assert res["computed"][0]["code"].startswith("ГЭСН:10-")
    assert res["computed"][0]["phys_qty"] > 0


def test_no_numbers_from_model_text():
    res = h.run_estimate_harness("гараж 50 м²", lambda _m: "Итого 5 миллионов.", max_steps=3)
    assert res["computed"] == []
    assert res["planner_status"] == "no_json"


# ── Gate 4: SLOT REQUIREMENTS + FORMULA CATALOG (формула не придумывает входы) ────────────

def test_parse_params_from_question():
    s = h.parse_params("паркинг 4800 глубина котлована 6 м плита 400 мм стены 300 мм высота 3 м")
    assert s["excavation_depth_m"] == 6.0
    assert s["slab_thickness_m"] == 0.4              # 400 мм → 0.4 м
    assert s["wall_thickness_m"] == 0.3


def test_parse_pile_count_from_question():
    assert h.parse_params("дом на 20 сваях")["pile_count"] == 20
    assert h.parse_params("свай 24, ростверк")["pile_count"] == 24


def test_resolve_slots_geometry_and_assume():
    geom = _geometry(3000, 3, {"geometry": {"H": 3.0}})  # S1=1000
    spec, ns, missing, asm = h.resolve_slots("foundation_slab", geom, {})
    assert "slab_thickness_m" in missing             # критичный, без него нельзя
    assert ns["slab_area_m2"] == ns["S1"]            # допущение slab_area_m2 = S1
    assert any("slab_area_m2" in a for a in asm)


def test_excavation_without_depth_needs_input():
    st = _state()
    obs = h._add_position({"work": "котлован", "code": "01-02-056-01", "work_family": "earthworks",
                           "element_type": "excavation"}, st)   # нет глубины
    assert obs["status"] == "needs_input" and "excavation_depth_m" in obs["missing_slots"]


def test_excavation_with_depth_computes():
    st = _state()
    obs = h._add_position({"work": "котлован", "code": "01-02-056-01", "work_family": "earthworks",
                           "element_type": "excavation", "slots": {"excavation_depth_m": 6}}, st)
    assert obs["status"] == "computed"               # S1*6*1.2 → объём посчитан кодом
    assert obs["phys_qty"] > 0


def test_foundation_slab_without_thickness_needs_input():
    st = _state()
    obs = h._add_position({"work": "плита", "code": "06-02-001-04", "work_family": "concrete_monolithic",
                           "element_type": "foundation_slab"}, st)
    assert obs["status"] == "needs_input" and "slab_thickness_m" in obs["missing_slots"]


def test_foundation_slab_with_thickness_computes():
    st = _state()
    obs = h._add_position({"work": "плита", "code": "06-02-001-04", "work_family": "concrete_monolithic",
                           "element_type": "foundation_slab", "slots": {"slab_thickness_m": 0.4}}, st)
    assert obs["status"] == "computed" and obs["phys_qty"] == 400.0   # S1(1000)*0.4


def test_generic_foundation_without_formula_is_actionable_needs_input():
    st = _state()
    obs = h._add_position({"work": "фундамент", "code": "06-02-001-01", "work_family": "foundation",
                           "element_type": "foundation"}, st)
    assert obs["status"] == "needs_input"
    assert "нет расчётной формулы" in obs["reason"]
    assert "Недопустимая формула" not in obs["reason"]


def test_pile_without_count_requests_pile_count():
    st = _state()
    obs = h._add_position({"work": "сваи", "code": "05-01-222-01", "work_family": "foundation",
                           "element_type": "pile"}, st)
    assert obs["status"] == "needs_input"
    assert "pile_count" in obs["missing_slots"]


def test_monolithic_wall_without_geometry_needs_input():
    st = _state()
    obs = h._add_position({"work": "стены", "code": "06-02-001-04", "work_family": "concrete_monolithic",
                           "element_type": "monolithic_wall", "slots": {"wall_thickness_m": 0.3}}, st)
    assert obs["status"] == "needs_input"            # нет длины/высоты → нельзя
    assert "wall_length_m" in obs["missing_slots"]


def test_excavation_overdig_marked_as_assumption():
    st = _state()
    h._add_position({"work": "котлован", "code": "01-02-056-01", "work_family": "earthworks",
                     "element_type": "excavation", "slots": {"excavation_depth_m": 6}}, st)
    res = h._finalize(st)
    assert res["by_assumption"]                      # overdig_factor принят допущением


def test_slots_loop_partial_then_complete():
    """Без слотов → needs_input/partial; со слотами → computed/complete (петля уточнения)."""
    # без глубины — needs_input → не complete
    st1 = _state()
    h._add_position({"work": "котлован", "code": "01-02-056-01", "work_family": "earthworks",
                     "element_type": "excavation"}, st1)
    assert h._finalize(st1)["total_status"] != "complete"
    # с глубиной — computed → complete (одна позиция, критичных/нет-данных нет)
    st2 = _state()
    h._add_position({"work": "котлован", "code": "01-02-056-01", "work_family": "earthworks",
                     "element_type": "excavation", "slots": {"excavation_depth_m": 6}}, st2)
    r2 = h._finalize(st2)
    assert r2["total_status"] == "complete" and r2["final_total"]["grand_total"] > 0
