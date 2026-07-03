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


def _complete_plan_with_norm_choice(plan, *, reason="тестовый выбор модели из shortlist"):
    def complete(messages):
        if messages and "search_norm вернул список норм" in messages[-1]["content"]:
            payload = json.loads(messages[-2]["content"])
            shortlist = payload["search_norm"]["shortlist"]
            candidate = next(
                (
                    c for c in shortlist
                    if c.get("applicability_status") == "accepted"
                    and c.get("unit_compatible") is not False
                ),
                shortlist[0] if shortlist else {},
            )
            return json.dumps({
                "selected_code": candidate.get("norm_code", ""),
                "reason": reason,
                "ask_user": "",
            }, ensure_ascii=False)
        return json.dumps(plan, ensure_ascii=False)
    return complete


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


def test_work_item_normalization_keeps_model_family_and_element():
    item = {
        "work": "каркасно-щитовые работы",
        "work_description": "каркасно-щитовые работы стены",
        "work_family": "metal",
        "element_type": "metal_assembly",
        "action": "assemble",
        "unit_hint": "m2",
    }

    norm, corrections = h._normalize_work_item(item)

    assert norm["work_family"] == "metal"
    assert norm["element_type"] == "metal_assembly"
    assert norm["action"] == "монтаж"
    assert norm["unit_hint"] == "м2"
    assert corrections
    hints = h._work_item_intent_hints(norm)
    assert any("work_family=wood" in hint for hint in hints)
    assert any("element_type=wood_wall" in hint for hint in hints)


def test_wrong_frame_wall_family_is_not_silently_rerouted_to_wood():
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
    assert norm["work_family"] == "metal"
    assert not (
        r["status"] == "found"
        and r["selection"].get("selected_code", "").startswith("ГЭСН:10-")
    )


def test_work_item_normalization_does_not_route_engineering_networks_to_mep():
    item = {
        "work": "устройство_инженерных_сетей",
        "work_description": "устройство инженерных сетей дома",
        "work_family": "finishes",
        "element_type": "finishes",
        "action": "устройство",
        "unit_hint": "м2",
    }

    norm, corrections = h._normalize_work_item(item)

    assert norm["work_family"] == "finishes"
    assert norm["element_type"] == "finishes"
    assert corrections == []
    hints = h._work_item_intent_hints(norm)
    assert any("work_family=mep" in hint for hint in hints)
    assert any("element_type=engineering_networks" in hint for hint in hints)


def test_excavation_signal_is_trace_hint_not_family_rewrite():
    item = {
        "work": "разработка котлована под свайный фундамент",
        "work_description": "разработка котлована под свайный фундамент",
        "work_family": "foundation",
        "element_type": "pile",
        "action": "разработка",
        "unit_hint": "м3",
    }

    norm, corrections = h._normalize_work_item(item)

    assert norm["work_family"] == "foundation"
    assert norm["element_type"] == "pile"
    assert corrections == []
    hints = h._work_item_intent_hints(norm)
    assert any("work_family=earthworks" in hint for hint in hints)
    assert any("element_type=excavation" in hint for hint in hints)


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


def test_metal_search_can_use_gesnm38_mounting_collection():
    r = h.search_norm(
        "листовые конструкции массой свыше 0,5 т сборка краном",
        work_family="metal",
        element_type="metal_assembly",
        action="монтаж",
        unit_hint="т",
        top_k=8,
    )

    codes = [c["norm_code"] for c in r["candidates"]]
    assert "ГЭСНм:38-01-001-01" in codes
    gesnm = next(c for c in r["candidates"] if c["norm_code"] == "ГЭСНм:38-01-001-01")
    assert gesnm["applicability_status"] == "accepted"
    assert gesnm["unit_compatible"] is True
    assert gesnm["norm_profile"]["navigation"]["nearby_norms"]
    assert r["norm_navigation"]["collections"]
    assert "rim_boundary" in r["norm_navigation"]


def test_electric_cable_search_routes_to_electromontage_collection():
    r = h.search_norm(
        "прокладка кабеля силового ППГнг FRHF 4х1,5",
        work_family="electric",
        element_type="cable",
        action="прокладка",
        unit_hint="м",
        top_k=8,
    )

    codes = [c["norm_code"] for c in r["candidates"]]
    assert any("08-05-038" in code or "08-04-744" in code for code in codes)
    assert not codes[0].startswith("ГЭСН:27-09")
    assert any(c["score_parts"].get("route") for c in r["candidates"])


def test_electric_pipe_search_routes_to_cable_trace_pipes():
    r = h.search_norm(
        "прокладка гибкой гофрированной трубы ПВХ d20 с протяжкой для кабеля",
        work_family="electric",
        element_type="pipe",
        action="прокладка",
        unit_hint="м",
        top_k=8,
    )

    codes = [c["norm_code"] for c in r["candidates"]]
    assert any("08-05-044" in code for code in codes)
    assert all(not code.startswith("ГЭСН:16-04-003") for code in codes[:3])


def test_electric_box_search_routes_to_electrical_boxes():
    r = h.search_norm(
        "установка коробки огнестойкой о/п 100х100х50 для кабеля",
        work_family="electric",
        element_type="box",
        action="установка",
        unit_hint="шт",
        top_k=8,
    )

    codes = [c["norm_code"] for c in r["candidates"]]
    assert any("08-03-545" in code or "08-03-641" in code for code in codes)
    assert not codes[0].startswith("ГЭСН:28-05")


def test_electric_box_route_survives_inflected_wording():
    r = h.search_norm(
        "монтаж распределительной коробки",
        work_family="electric",
        element_type="box",
        action="монтаж",
        unit_hint="шт",
        top_k=6,
    )

    candidates = r["candidates"]
    codes = [c["norm_code"] for c in candidates]
    assert any("08-03-545" in code or "08-03-641" in code for code in codes)
    assert any(c["score_parts"].get("route") for c in candidates)


def test_finish_painting_search_routes_to_painting_norms():
    r = h.search_norm(
        "окраска потолков водно-дисперсионной краской",
        work_family="finish",
        element_type="painting",
        action="окраска",
        unit_hint="м2",
        top_k=8,
    )

    codes = [c["norm_code"] for c in r["candidates"]]
    assert any("15-04-005" in code or "15-04-007" in code for code in codes)
    assert not codes[0].startswith("ГЭСН:34-01-019")


def test_mass_context_promotes_gesnm38_over_building_frame_codes():
    r = h.search_norm(
        "Монтаж металлоконструкций масса 664.711 т",
        work_family="metal",
        element_type="metal_assembly",
        action="монтаж",
        unit_hint="т",
        top_k=5,
    )

    assert r["candidates"][0]["norm_code"] == "ГЭСНм:38-01-001-01"


def test_search_norm_returns_navigation_questions_for_earthworks():
    r = h.search_norm(
        "разработка грунта вручную в траншее",
        work_family="earthworks",
        element_type="excavation",
        action="разработка",
        unit_hint="м3",
        top_k=5,
    )

    assert r["candidates"]
    assert r["norm_navigation"]["collections"]
    assert "уточнить группу грунта" in r["norm_navigation"]["questions_to_ask"]
    assert r["candidates"][0]["norm_profile"]["navigation"]["nearby_norms"]


def test_extract_json_from_markdown_wrapped_response():
    obj = h._extract_json("план ниже:\n```json\n{\"object\":{\"area_total_m2\":150},\"works\":[]}\n```")
    assert obj == {"object": {"area_total_m2": 150}, "works": []}


def test_batch_plan_repairs_first_non_json_response():
    responses = iter([
        "Я разложу объект на работы, но сейчас отвечу текстом.",
        '{"object":{"object_type":"house","area_total_m2":150,"floors":1},'
        '"works":[["кровля","устройство кровли","roofing","roofing","устройство","м2",{}]]}',
    ])
    chooser = _complete_plan_with_norm_choice({})

    def complete(messages):
        if messages and "search_norm вернул список норм" in messages[-1]["content"]:
            return chooser(messages)
        return next(responses)

    res = h.run_estimate_harness("дом 150 м2", complete)

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
    assert "experienced_estimator_v1" in system
    assert "smeta_work_plan_v1" in system
    assert "Не отказывайся из-за отсутствия проекта/ВОР/РД" not in system
    assert "3000 метров" not in h.BATCH_TOOL_CONTRACT
    assert "монолитного каркаса" not in h.BATCH_TOOL_CONTRACT
    assert "Поставка оборудования" not in h.BATCH_TOOL_CONTRACT
    assert "Это только машинный формат вызова сметных инструментов" in h.BATCH_TOOL_CONTRACT
    assert "object_templates" not in system
    assert res["notebook_context"]["service_notebooks"] == ["gesn"]


def test_assumption_prompt_tells_model_not_to_refuse_without_project():
    seen = []

    def complete(messages):
        seen.append(messages)
        return '{"object":{"object_type":"object","area_total_m2":5000,"floors":1},"works":[]}'

    res = h.run_estimate_harness("объект 5000 м2, придумай все сам и дай цены", complete)

    first_user = seen[0][1]["content"]
    repair_user = seen[1][-1]["content"]
    system = seen[0][0]["content"]
    assert "не отказывайся только потому, что нет проекта/вор/рд" in system.lower()
    assert "условное здание/участок работ по допущениям" in system
    assert "Пользователь явно разрешил сценарную прикидку" in first_user
    assert "используй правила role-pack" in repair_user
    assert res["assumption_mode"] is True


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
    chooser = _complete_plan_with_norm_choice({})

    def complete(messages):
        if messages and "search_norm вернул список норм" in messages[-1]["content"]:
            return chooser(messages)
        return next(responses)

    res = h.run_estimate_harness("дом 150 м2 кровля", complete)

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


def test_search_norm_uses_sqlite_light_norm_store_trace():
    r = h.search_norm("устройство кровли", work_family="roofing", element_type="roofing", unit_hint="м2")

    assert r["candidates"]
    assert r["norm_store"]["schema"] == "smeta_norm_store_v5"
    assert r["norm_store"]["backend"] == "sqlite_light"
    assert set(r["norm_store"]["profile_fields"]) >= {
        "family_hints", "element_hints", "resource_kinds", "model_card", "navigation",
        "applicability", "price_inputs", "decision_order",
    }
    assert r["candidate_pool"]["searched"] >= r["candidate_pool"]["scored"] >= len(r["candidates"])
    top = r["candidates"][0]
    assert "norm_profile" in top
    assert "navigation" in top["norm_profile"]
    assert "roofing" in top["norm_profile"]["family_hints"]
    assert top["norm_profile"]["provenance"]
    assert top["norm_profile"]["model_card"]["title"] == top["title"]
    assert top["norm_profile"]["model_card"]["price_inputs"]["material_gap"].startswith("материал")
    assert r["norm_navigation"]["decision_context"]["schema"] == "norm_decision_context_v1"
    assert "цены ресурсов" in r["norm_navigation"]["decision_context"]["checks"][-1]
    assert "это навигационная карточка нормы, не расчёт стоимости" in top["norm_profile"]["model_card"]["warnings"]
    assert "profile_family" in top["score_parts"]


def test_direct_quantity_candidates_are_exposed_with_provenance():
    plan = {
        "object": {"object_type": "earthworks", "area_total_m2": None, "floors": 1},
        "works": [
            ["Разработка траншеи", "разработка грунта вручную в траншее",
             "earthworks", "excavation", "разработка", "м3", {}],
        ],
    }

    res = h.run_estimate_harness(
        "регион Санкт-Петербург, рассчитай стоимость разработки траншеи вручную, объем выработки грунта 200 м3",
        _complete_plan_with_norm_choice(plan),
    )

    volume = next(c for c in res["quantity_candidates"] if c["slot"] == "volume_m3")
    assert volume["value"] == 200
    assert volume["source"] == "user_text"
    assert res["computed"][0]["quantity_source"]["slot"] == "volume_m3"
    assert res["computed"][0]["phys_qty"] == 200
    assert res["smeta_service_sources"]["schema"] == "smeta_service_sources_v1"


# ── end-to-end петля (скриптовая модель) ─────────────────────────────────────────────────

def test_legacy_tool_call_is_repaired_to_batch_plan():
    legacy = {"tool": "propose_schema", "args": {"object_type": "underground_parking",
              "area_total_m2": 4800, "levels_below_ground": 2, "structural_system": "monolithic_rc",
              "missing_inputs": ["soil_category"]}}
    plan = {
        "object": {"object_type": "underground_parking", "area_total_m2": 4800,
                   "levels_below_ground": 2, "structural_system": "monolithic_rc"},
        "works": [
            ["Фунд. плита", "устройство монолитной железобетонной фундаментной плиты",
             "concrete_monolithic", "foundation_slab", "устройство", "м3", {"slab_thickness_m": 0.4}],
        ],
    }
    chooser = _complete_plan_with_norm_choice(plan)
    calls = {"i": 0}

    def complete(messages):
        calls["i"] += 1
        if messages and "старый tool-call формат" in messages[-1]["content"]:
            return json.dumps(plan, ensure_ascii=False)
        if messages and "search_norm вернул список норм" in messages[-1]["content"]:
            return chooser(messages)
        return json.dumps(legacy, ensure_ascii=False)

    res = h.run_estimate_harness("подземный паркинг 4800 м² 2 уровня", complete, max_steps=8)
    assert res["preliminary"] is True
    assert len(res["computed"]) == 1
    assert res["computed"][0]["qty"] > 0
    assert res["total_status"] == "partial"        # принятая позиция есть, но цены ресурсов не закрыты
    assert res["partial_total"]["grand_total"] > 0
    assert res["final_total"] is None
    assert any(req["action"] == "needs_kac" for req in res["price_requirements"])
    assert calls["i"] >= 2
    assert [t["tool"] for t in res["trace"]] == [
        "planner_legacy_repair",
        "propose_schema",
        "search_norm",
        "model_norm_choice",
        "add_position",
    ]


def test_batch_plan_asks_model_to_choose_when_search_is_ambiguous():
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

    def complete(messages):
        calls["n"] += 1
        if messages and "search_norm вернул список норм" in messages[-1]["content"]:
            return json.dumps({
                "selected_code": "ГЭСН:06-02-001-04",
                "reason": "подходит для фундаментной плиты общего назначения",
                "ask_user": "",
            }, ensure_ascii=False)
        return json.dumps(plan, ensure_ascii=False)

    res = h.run_estimate_harness("паркинг 4800 м², плита 400 мм", complete)

    assert calls["n"] == 2
    assert res["planner_status"] == "batch"
    assert res["trace"][0]["tool"] == "propose_schema"
    assert res["trace"][1]["tool"] == "search_norm"
    assert res["trace"][1]["candidates"]       # номера ГЭСН видны для operator review
    assert res["trace"][1]["selection"]["schema"] == "candidate_selection_v1"
    assert res["trace"][2]["tool"] == "model_norm_choice"
    assert res["trace"][2]["status"] == "selected"
    assert res["computed"]                     # черновую стоимость считаем после выбора модели
    assert res["computed"][0]["code"].startswith("ГЭСН:06-02")
    assert any("моделью из shortlist" in a for a in res["computed"][0]["assumptions"])
    assert res["by_assumption"]
    assert res["total_status"] == "partial"
    assert res["partial_total"]["grand_total"] > 0
    assert res["final_total"] is None
    assert res["price_requirements"]


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

    res = h.run_estimate_harness("дача 150 м²", _complete_plan_with_norm_choice(plan))

    assert res["planner_status"] == "batch"
    assert res["schema"]["object_type"] == "residential_house"
    assert [t["tool"] for t in res["trace"]].count("search_norm") == 2
    assert all(t["candidates"] for t in res["trace"] if t["tool"] == "search_norm")
    assert any(p["code"].startswith("ГЭСН:12-") for p in res["computed"])
    roof = next(p for p in res["computed"] if p["code"].startswith("ГЭСН:12-"))
    assert any("моделью из shortlist" in a for a in roof["assumptions"])


def test_batch_plan_lets_model_select_later_unit_compatible_roof_candidate():
    plan = {
        "object": {"object_type": "residential_house", "area_total_m2": 150, "floors": 1},
        "works": [
            ["Кровельные работы", "Устройство двускатной кровли", "roofing", "roofing",
             "устройство", "м2", {}],
        ],
    }

    res = h.run_estimate_harness(
        "дача 150 м² двускатная кровля",
        _complete_plan_with_norm_choice(plan),
    )

    assert res["computed"]
    assert res["computed"][0]["code"] != "ГЭСН:12-01-041-01"
    assert res["computed"][0]["physical_unit"] == "м2"
    add_trace = [t for t in res["trace"] if t["tool"] == "add_position"][0]
    assert add_trace["candidate_index"] > 0
    assert any(t["tool"] == "model_norm_choice" for t in res["trace"])


def test_batch_plan_trace_reports_tool_argument_normalization():
    plan = {
        "object": {"object_type": "residential_house", "area_total_m2": 150, "floors": 1},
        "works": [
            ["каркасно-щитовые работы", "каркасно-щитовые работы стены",
             "metal", "metal_assembly", "assemble", "m2", {}],
        ],
    }

    res = h.run_estimate_harness("дача 150 м²", _complete_plan_with_norm_choice(plan))

    search_trace = [t for t in res["trace"] if t["tool"] == "search_norm"][0]
    assert search_trace["normalized"]
    assert search_trace["intent_hints"]
    assert any("work_family=wood" in hint for hint in search_trace["intent_hints"])
    assert not any(p["code"].startswith("ГЭСН:10-") for p in res["computed"])
    assert res["total_status"] == "blocked"


def test_batch_plan_computes_mass_based_metal_assembly():
    plan = {
        "object": {"object_type": "steel_structure"},
        "works": [
            ["Монтаж металлических конструкций", "Монтаж металлоконструкций",
             "metal", "metal_assembly", "монтаж", "т", {"mass_t": 664.711}],
        ],
    }

    res = h.run_estimate_harness(
        "стальные ярусы, масса 664 711 кг",
        lambda _m: json.dumps(plan, ensure_ascii=False),
    )

    assert res["computed"]
    pos = res["computed"][0]
    assert pos["code"] == "ГЭСНм:38-01-001-01"
    assert pos["physical_unit"] == "т"
    assert abs(pos["phys_qty"] - 664.711) < 0.001
    assert pos["qty"] == pos["phys_qty"]


def test_direct_mass_duplicate_norms_need_separate_quantity_not_multiplied():
    plan = {
        "object": {"object_type": "metal_structure", "area_total_m2": 150},
        "works": [
            ["Монтаж металлоконструкций", "Монтаж металлоконструкций",
             "metal", "metal_assembly", "монтаж", "т", {}],
            ["Укрупнительная сборка металлоконструкций (если требуется)",
             "Укрупнительная сборка металлоконструкций",
             "metal", "metal_assembly", "монтаж", "т", {}],
            ["Монтажные сварочные работы (уточнить долю)",
             "Монтаж металлоконструкций сварочные соединения",
             "metal", "metal_assembly", "монтаж", "т", {}],
        ],
    }

    res = h.run_estimate_harness(
        "рассчитай сметную стоимость монтажа металлоконструкций, масса 664.711,12 кг",
        lambda _m: json.dumps(plan, ensure_ascii=False),
    )

    assert len(res["computed"]) == 1
    assert abs(res["computed"][0]["phys_qty"] - 664.71112) < 0.00001
    assert len(res["needs_input"]) == 0
    assert len(res["skipped"]) == 2
    assert all("дублирует уже посчитанную позицию" in p["reason"] for p in res["skipped"])
    assert res["total_status"] == "complete"
    assert res["final_total"]["positions"] == 1
    assert res["direct_quantity_estimate"] is True
    assert res["direct_quantity_slots"] == ["mass_t"]


def test_direct_mass_can_price_explicit_distinct_operations():
    plan = {
        "object": {"object_type": "metal_structure", "area_total_m2": 150},
        "works": [
            ["Контрольная сборка облицованных бронзой стальных каркасов",
             "Контрольная сборка стальных каркасов",
             "metal", "metal_assembly", "монтаж", "т", {"mass_t": 664.711}],
            ["Промежуточная разборка после контрольной сборки",
             "Промежуточная разборка стальных каркасов",
             "metal", "metal_assembly", "демонтаж", "т", {"mass_t": 664.711}],
            ["Монтаж стальных каркасов на строительной площадке",
             "Монтаж стальных каркасов на строительной площадке",
             "metal", "metal_assembly", "монтаж", "т", {"mass_t": 664.711}],
        ],
    }

    res = h.run_estimate_harness(
        "ТЗ: масса стальных каркасов 664 711 кг. Разделы: контрольная сборка; "
        "промежуточная разборка после нее; монтаж на строительной площадке.",
        lambda _m: json.dumps(plan, ensure_ascii=False),
    )

    assert len(res["computed"]) == 3
    assert len(res["skipped"]) == 0
    assert {p["operation_key"] for p in res["computed"]} == {
        "контрольная сборка",
        "промежуточная разборка",
        "монтаж на площадке",
    }
    assert all(abs(p["phys_qty"] - 664.711) < 0.001 for p in res["computed"])
    assert res["final_total"]["positions"] == 3


def test_direct_volume_computes_without_object_geometry():
    st = {"schema": {}, "geom": {}, "positions": [], "steps": 0,
          "user_slots": {"volume_m3": 200.0}}

    obs = h._add_position({
        "work": "разработка траншеи вручную",
        "code": "01-02-056-01",
        "work_family": "earthworks",
        "element_type": "excavation",
    }, st)

    assert obs["status"] == "computed"
    assert obs["phys_qty"] == 200.0
    assert obs["quantity_for_estimate"] == 2.0
    assert st["positions"][0]["formula"] == "volume_m3"
    assert set(st["positions"][0]["norm_questions"]) >= {
        "группа грунта",
        "глубина разработки",
        "крепления траншей/котлована",
    }


def test_direct_volume_ignores_planner_placeholder_geometry_for_magnitude():
    st = {
        "schema": {},
        "geom": {"S": 1.0, "S1": 1.0, "N": 1.0, "P": 4.0, "H": 3.0},
        "positions": [],
        "steps": 0,
        "user_slots": {"volume_m3": 200.0},
    }

    obs = h._add_position({
        "work": "разработка траншеи вручную",
        "code": "01-02-056-01",
        "work_family": "earthworks",
        "element_type": "excavation",
    }, st)

    assert obs["status"] == "computed"
    assert obs["quantity_for_estimate"] == 2.0
    assert not any(p.get("status") == "rejected_magnitude" for p in st["positions"])


def test_parse_soil_group_from_question():
    assert h.parse_params("группа грунта II, объем 200 м3")["soil_group"] == 2.0
    assert h.parse_params("грунт группы IV, глубина 3 м")["soil_group"] == 4.0
    assert h.parse_params("грунт группы третьей")["soil_group"] == 3.0


def test_direct_volume_with_unconfirmed_norm_conditions_is_partial():
    plan = {
        "object": {"object_type": "earthwork"},
        "works": [
            ["Разработка траншеи вручную", "Разработка грунта вручную в траншеях",
             "earthworks", "excavation", "разработка", "м3", {}],
        ],
    }

    res = h.run_estimate_harness(
        "регион Санкт-Петербург, рассчитай стоимость разработки траншеи вручную, объем выработки грунта 200 м3",
        _complete_plan_with_norm_choice(plan),
    )

    assert res["computed"]
    assert res["total_status"] == "partial"
    assert res["final_total"] is None
    assert res["partial_total"]["positions"] == 1
    assert set(res["computed"][0]["norm_questions"]) >= {
        "группа грунта",
        "глубина разработки",
        "крепления траншей/котлована",
        "ширина или площадь сечения",
    }


def test_direct_volume_with_confirmed_norm_conditions_can_complete():
    plan = {
        "object": {"object_type": "earthwork"},
        "works": [
            ["Разработка траншеи вручную", "Разработка грунта вручную в траншеях",
             "earthworks", "excavation", "разработка", "м3", {}],
        ],
    }

    res = h.run_estimate_harness(
        "рассчитай стоимость разработки траншеи вручную, объем 200 м3, грунт группы II, глубина 2 м, с креплениями, ширина 1 м",
        _complete_plan_with_norm_choice(plan),
    )

    assert res["computed"]
    assert res["computed"][0].get("norm_questions") in (None, [])
    assert res["total_status"] == "complete"
    assert res["final_total"]["positions"] == 1


def test_object_area_does_not_override_m2_formula_quantities():
    plan = {
        "object": {"object_type": "residential_house", "area_total_m2": 200, "floors": 2},
        "works": [
            ["Каркасные стены", "Устройство деревянных каркасных стен", "wood", "wood_wall",
             "устройство", "м2", {}],
        ],
    }

    res = h.run_estimate_harness(
        "каркасный дом площадь 200 м2, 2 этажа",
        _complete_plan_with_norm_choice(plan),
    )

    assert res["computed"]
    assert res["computed"][0]["formula"] == "P * H * N"
    assert res["computed"][0]["phys_qty"] == 240.0
    assert res["direct_quantity_estimate"] is False


def test_object_area_can_be_read_from_bare_house_area_phrase():
    plan = {
        "object": {"object_type": "residential_house", "area_total_m2": None, "floors": 2},
        "works": [
            ["Каркасные стены", "Устройство деревянных каркасных стен", "wood", "wood_wall",
             "устройство", "м2", {}],
        ],
    }

    res = h.run_estimate_harness(
        "двухэтажный дом 200 м2",
        _complete_plan_with_norm_choice(plan),
    )

    assert res["computed"]
    assert res["schema"]["area_total_m2"] == 200.0


def test_vor_line_area_per_piece_is_not_object_area():
    text = (
        "Ведомость объемов работ: Сборка и монтаж скамьи тип 1.1 шт 3. "
        "Ведомость скамьи тип 1.1 (для 1 скамьи). "
        "Окраска пластин краской по металлу, площадь 0,07 м²/шт."
    )
    slots = h.parse_params(text)

    assert slots["area_m2"] == 0.07
    assert h._object_area_from_text(text, slots) is None


def test_vor_quantities_are_candidates_until_model_binds_slots():
    plan = {
        "object": {"object_type": "bench_tz", "area_total_m2": None, "floors": 1},
        "works": [
            ["Устройство бетонного основания", "устройство бетонного основания",
             "concrete_monolithic", "concrete_preparation", "устройство", "м3", {}],
        ],
    }

    res = h.run_estimate_harness(
        "ТЗ. Ведомость объемов работ: Сборка и монтаж скамьи тип 1.1 шт 3. "
        "Ведомость скамьи тип 1.1 (для 1 скамьи). "
        "Объём бетонного основания 0,4 м3. "
        "Объём выравнивающей стяжки из ЦПС 0,07 м3.",
        _complete_plan_with_norm_choice(plan),
    )

    assert any(c["slot"] == "volume_m3" for c in res["quantity_candidates"])
    assert res["computed"] == []
    assert res["needs_input"]


def test_model_placeholder_area_does_not_create_fake_object_geometry():
    plan = {
        "object": {"object_type": "concrete_house", "area_total_m2": 1, "floors": 2},
        "works": [
            ["Устройство кровли", "Устройство кровли", "roofing", "roofing",
             "устройство", "м2", {}],
            ["Отделочные работы", "Отделочные работы", "finishes", "finishes",
             "устройство", "м2", {}],
        ],
    }

    res = h.run_estimate_harness(
        "хочу построить бетонную двухэтажную дачу",
        _complete_plan_with_norm_choice(plan),
    )

    assert not res["computed"]
    assert res["total_status"] == "blocked"
    assert {p["status"] for p in res["needs_input"]} == {"needs_input"}
    assert all("area_total_m2" in (p.get("missing_slots") or []) for p in res["needs_input"])
    assert res["schema"]["area_total_m2"] is None
    search_steps = [t for t in res["trace"] if t["tool"] == "search_norm"]
    assert search_steps
    assert all(t["candidates"] for t in search_steps)
    assert any(t["tool"] == "add_position" for t in res["trace"])


def test_authorized_assumption_mode_can_use_model_scenario_geometry():
    plan = {
        "object": {
            "object_type": "concrete_house",
            "area_total_m2": 200,
            "floors": 2,
            "assumptions": ["общая площадь 200 м2 принята как сценарное допущение"],
        },
        "works": [
            ["Устройство кровли", "Устройство кровли", "roofing", "roofing",
             "устройство", "м2", {}, ["площадь кровли считается от пятна здания с коэффициентом"]],
        ],
    }

    res = h.run_estimate_harness(
        "хочу построить бетонную двухэтажную дачу. придумай сам и дай смету",
        _complete_plan_with_norm_choice(plan),
    )

    assert res["assumption_mode"] is True
    assert res["schema"]["area_total_m2"] == 200.0
    assert res["scenario_assumptions"] == ["общая площадь 200 м2 принята как сценарное допущение"]
    assert res["computed"]
    assert res["by_assumption"]


def test_explicit_work_area_can_be_direct_quantity():
    plan = {
        "object": {"object_type": "кровельные работы", "area_total_m2": 1, "floors": 1},
        "works": [
            ["Устройство кровли", "Устройство кровли", "roofing", "roofing",
             "устройство", "м2", {}],
        ],
    }

    res = h.run_estimate_harness(
        "рассчитай сметную стоимость работ по устройству кровли, площадь работ 200 м2",
        _complete_plan_with_norm_choice(plan),
    )

    assert res["computed"]
    assert res["computed"][0]["formula"] == "area_m2"
    assert res["computed"][0]["phys_qty"] == 200.0
    assert res["direct_quantity_estimate"] is True


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


def test_parse_params_accepts_meter_words():
    s = h.parse_params("глубина котлована 2 метра, высота стен 3 метра, периметр стен 160 метров")

    assert s["excavation_depth_m"] == 2.0
    assert s["wall_height_m"] == 3.0
    assert s["wall_length_m"] == 160.0


def test_parse_direct_work_volume_from_question():
    s = h.parse_params(
        "регион санкт-петербург, нужно рассчитать сметную стоимость работ по "
        "разработке траншеи вручную, объем выработки грунта 200 м3"
    )

    assert s["volume_m3"] == 200.0


def test_parse_mass_from_question():
    assert abs(h.parse_params("стальные ярусы масса 664 711 кг")["mass_t"] - 664.711) < 0.001
    assert abs(h.parse_params("Общая масса (сталь + бронза) составляет 664\xa0711,12 кг")["mass_t"] - 664.71112) < 0.00001
    assert abs(h.parse_params("Общая масса составляет 664.711,12 кг")["mass_t"] - 664.71112) < 0.00001
    assert abs(h.parse_params("Вес: 664,711.12 кг")["mass_t"] - 664.71112) < 0.00001
    assert h.parse_params("масса 12,5 т")["mass_t"] == 12.5


def test_parse_params_accept_office_thousand_separators():
    params = h.parse_params("глубина котлована 1,2 м, плита 1.200,0 мм, стены 300.0 мм")

    assert params["excavation_depth_m"] == 1.2
    assert params["slab_thickness_m"] == 1.2
    assert params["wall_thickness_m"] == 0.3


def test_explicit_work_estimate_auto_route_is_narrow():
    assert h.is_explicit_work_estimate_request(
        "регион санкт-петербург, нужно рассчитать сметную стоимость работ по "
        "разработке траншеи вручную, объем выработки грунта 200 м3"
    )
    assert not h.is_explicit_work_estimate_request("покажи позиции из сметы объем 200 м3")
    assert not h.is_explicit_work_estimate_request("найди строки сметы по работам объем 200 м3")


def test_parse_pricebook_from_spb_q2_2026(monkeypatch):
    from proxy.services import fgis_price_service as fps

    monkeypatch.setattr(fps, "available_pricebooks", lambda *a, **k: ["/tmp/spb_2kv2026.parquet"])

    assert h.parse_pricebook_hint("Расчет выполнить в ценах 2-ого квартала 2026 года по Санкт-Петербургу") == "spb_2kv2026"


def test_mass_metal_plan_passes_pricebook_and_collection_nr_sp(monkeypatch):
    from proxy.services import lsr_assembly_service as lsr

    captured = {}

    def fake_assemble(positions, *, book=None, **_kwargs):
        captured["positions"] = positions
        captured["book"] = book
        return {"summary": {"total": 110519705.74}}

    monkeypatch.setattr(lsr, "assemble", fake_assemble)
    state = {
        "pricebook": "spb_2kv2026",
        "positions": [{
            "status": "computed",
            "work": "Монтаж металлоконструкций",
            "code": "ГЭСНм:38-01-001-01",
            "qty": 664.71112,
            "norm_unit": "т",
        }],
    }

    h._finalize(state)

    assert captured["book"] == "spb_2kv2026"
    assert captured["positions"][0]["nr_pct"] == 90
    assert captured["positions"][0]["sp_pct"] == 45


def test_parse_pile_count_from_question():
    assert h.parse_params("дом на 20 сваях")["pile_count"] == 20
    assert h.parse_params("свай 24, ростверк")["pile_count"] == 24
    assert "pile_count" not in h.parse_params("дом на сваях, площадь 200 м2")
    assert "pile_count" not in h.parse_params("дом на сваях площадь 200 м2")


def test_piece_unit_hint_is_kept_for_countable_work():
    item = {
        "work": "устройство свай",
        "work_description": "устройство свай",
        "work_family": "foundation",
        "element_type": "pile",
        "action": "устройство",
        "unit_hint": "шт",
    }

    norm, _ = h._normalize_work_item(item)

    assert norm["unit_hint"] == "шт"


def test_resolve_slots_geometry_and_assume():
    geom = _geometry(3000, 3, {"geometry": {"H": 3.0}})  # S1=1000
    spec, ns, missing, asm = h.resolve_slots("foundation_slab", geom, {})
    assert "slab_thickness_m" in missing             # критичный, без него нельзя
    assert ns["slab_area_m2"] == ns["S1"]            # допущение slab_area_m2 = S1
    assert any("slab_area_m2" in a for a in asm)


def test_assumption_mode_does_not_invent_missing_formula_slots():
    st = _state()
    st["assumption_mode"] = True
    obs = h._add_position({"work": "котлован", "code": "01-02-056-01", "work_family": "earthworks",
                           "element_type": "excavation"}, st)

    assert obs["status"] == "needs_input"
    assert "excavation_depth_m" in obs["missing_slots"]


def test_model_supplied_scenario_slots_are_calculated():
    st = _state(area=3000, floors=2)
    st["assumption_mode"] = True
    obs = h._add_position({"work": "котлован", "code": "01-02-056-01", "work_family": "earthworks",
                           "element_type": "excavation",
                           "slots": {"excavation_depth_m": 2}},
                          st)

    assert obs["status"] == "computed"
    assert obs["phys_qty"] == 3600.0                 # S1(1500)*2*1.2


def test_pile_norms_are_penalized_without_pile_words():
    class Row:
        def profile(self):
            return {
                "family_hints": ["foundation"],
                "element_hints": ["pile"],
                "action_hints": ["устройство"],
                "resource_count": 1,
            }

    scored = h._score_candidate(
        ["фундамент"],
        "05-01-222-01",
        "устройство свайных фундаментов",
        "шт",
        work_family="foundation",
        element_type="foundation",
        action="устройство",
        phys_unit="м3",
        norm_row=Row(),
    )

    assert scored is not None
    assert scored[1]["pile_mismatch"] < 0


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
    """Без слотов → needs_input/partial; с параметрами нормы → computed/complete."""
    # без глубины — needs_input → не complete
    st1 = _state()
    h._add_position({"work": "котлован", "code": "01-02-056-01", "work_family": "earthworks",
                     "element_type": "excavation"}, st1)
    assert h._finalize(st1)["total_status"] != "complete"
    # одной глубины мало: для выбранной земляной нормы нужны условия применимости
    st_depth = _state()
    h._add_position({"work": "котлован", "code": "01-02-056-01", "work_family": "earthworks",
                     "element_type": "excavation", "slots": {"excavation_depth_m": 6}}, st_depth)
    assert h._finalize(st_depth)["total_status"] == "partial"
    # когда пользователь подтвердил условия нормы, computed → complete
    st2 = _state()
    st2["question_text"] = "котлован, грунт группы II, глубина 6 м, с креплениями, ширина 2 м"
    h._add_position({"work": "котлован", "code": "01-02-056-01", "work_family": "earthworks",
                     "element_type": "excavation",
                     "slots": {"excavation_depth_m": 6, "soil_group": 2}}, st2)
    r2 = h._finalize(st2)
    assert r2["total_status"] == "complete" and r2["final_total"]["grand_total"] > 0
