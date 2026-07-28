"""Current tests for the legacy estimate harness as a thin model-first adapter.

The retired suite asserted private case-specific scorers, collection allow-lists and
hardcoded object geometry. Those mechanisms were removed from production. This file
keeps the live adapter contract: model-visible retrieval, explicit model selection,
typed norm identity, deterministic quantity conversion and parser/prompt safety.
"""

from __future__ import annotations

import json

from proxy.services import estimate_harness_service as h
from proxy.services.estimate_math_service import _geometry


def _state(*, slots=None):
    return {
        "schema": {},
        "geom": _geometry(100, 1, {"geometry": {"H": 3.0}}),
        "positions": [],
        "steps": 0,
        "user_slots": dict(slots or {}),
        "question_text": "",
    }


def _model_complete(plan: dict):
    def complete(messages):
        if messages and "search_norm вернул список норм" in messages[-1]["content"]:
            payload = json.loads(messages[-2]["content"])
            shortlist = payload["search_norm"]["shortlist"]
            chosen = shortlist[0] if shortlist else {}
            return json.dumps(
                {
                    "selected_code": chosen.get("norm_code", ""),
                    "selection_kind": "exact",
                    "analog_limitations": [],
                    "reason": "явный выбор тестовой модели из model-visible shortlist",
                    "ask_user": "",
                },
                ensure_ascii=False,
            )
        return json.dumps(plan, ensure_ascii=False)

    return complete


def _trusted_active_base(monkeypatch):
    from proxy.smeta_core import integrity

    monkeypatch.setattr(
        integrity,
        "normative_base_integrity",
        lambda **_kwargs: {
            "status": "trusted",
            "trusted_for_navigation": True,
            "trusted_for_pricing": True,
        },
    )


def test_search_norm_no_match_is_honest(monkeypatch):
    # Unit contract must not depend on live Qdrant/manifest state or suite order.
    # Native RRF quality is covered by the norm-browser integration/golden tests.
    from proxy.smeta_core import norm_browser

    monkeypatch.setattr(
        norm_browser,
        "browse_norms",
        lambda *_args, **_kwargs: {"cards": [], "backend": "isolated_no_match"},
    )
    assert h.search_norm("жжжыыы щщщъъъ ёёёххх")["status"] == "not_found"


def test_collection_identity_preserves_explicit_family():
    assert h._collection_of("ГЭСН:10-02-024-02") == "10"
    assert h._collection_of("12-01-023-01") == "12"
    assert h._collection_key("ГЭСНм:08-05-044-02") == "ГЭСНм08"
    assert h._plain_norm_code("ГЭСНм08-03-575-01") == "08-03-575-01"


def test_search_norm_returns_cards_but_never_selects_code():
    result = h.search_norm(
        "прибор аппарат установка присоединение",
        work_family="electric",
        element_type="device",
        action="монтаж",
        unit_hint="шт",
        top_k=5,
    )

    assert result["candidates"][0]["norm_code"] == "ГЭСНм08-03-575-01"
    assert result["candidates"][0]["applicability_status"] == "model_review_required"
    assert result["selection"]["status"] == "needs_model_choice"
    assert result["selection"]["selected_code"] == ""


def test_search_norm_exposes_exact_work_steps_and_source():
    result = h.search_norm(
        "труба гофрированная ПВХ для защиты кабелей",
        work_family="electric",
        element_type="pipe",
        action="монтаж",
        unit_hint="м",
        top_k=5,
    )
    card = next(item for item in result["candidates"] if item["norm_code"] == "ГЭСНм08-02-409-09")

    assert card["unit_compatible"] is True
    assert card["norm_profile"]["work_steps"]
    assert "guid=" in card["norm_profile"]["source_ref"]


def test_candidate_selection_never_promotes_clear_leader_in_code():
    selection = h._candidate_selection(
        [
            {
                "norm_code": "ГЭСНм08-03-575-01",
                "title": "Прибор или аппарат",
                "measure_unit": "шт",
                "score_total": 8.0,
                "score_parts": {"retrieval_rank": 1},
                "applicability_status": "model_review_required",
                "unit_compatible": True,
            },
            {
                "norm_code": "ГЭСНм08-03-599-09",
                "title": "Щиток осветительный",
                "measure_unit": "шт",
                "score_total": 2.0,
                "score_parts": {"retrieval_rank": 2},
                "applicability_status": "model_review_required",
                "unit_compatible": True,
            },
        ]
    )

    assert selection["status"] == "needs_model_choice"
    assert selection["selected_code"] == ""


def test_work_item_hints_do_not_silently_rewrite_model_fields():
    item = {
        "work": "каркасно-щитовые стены",
        "work_description": "каркасно-щитовые стены",
        "work_family": "metal",
        "element_type": "metal_assembly",
        "action": "assemble",
        "unit_hint": "m2",
    }
    normalized, corrections = h._normalize_work_item(item)

    assert normalized["work_family"] == "metal"
    assert normalized["element_type"] == "metal_assembly"
    assert normalized["action"] == "монтаж"
    assert normalized["unit_hint"] == "м2"
    assert corrections
    assert any("work_family=wood" in hint for hint in h._work_item_intent_hints(normalized))


def test_add_position_accepts_only_existing_typed_norm_and_converts_quantity(monkeypatch):
    _trusted_active_base(monkeypatch)
    state = _state(slots={"piece_count": 2})
    result = h._add_position(
        {
            "work": "Монтаж аппарата",
            "code": "ГЭСНм08-03-575-01",
            "work_family": "electric",
            "physical_unit": "шт",
            "slots": {"piece_count": 2},
        },
        state,
    )

    assert result["status"] == "computed"
    assert result["phys_qty"] == 2.0
    assert result["quantity_for_estimate"] == 2.0
    assert state["positions"][0]["norm_source_integrity"]["trusted_for_navigation"] is True
    assert state["positions"][0]["norm_source_integrity"]["trusted_for_pricing"] is True


def test_add_position_rejects_unknown_norm_without_fallback():
    state = _state(slots={"piece_count": 2})
    result = h._add_position(
        {
            "work": "Монтаж аппарата",
            "code": "ГЭСНм99-99-999-99",
            "physical_unit": "шт",
            "slots": {"piece_count": 2},
        },
        state,
    )

    assert result["status"] == "rejected_norm"
    assert state["positions"][0]["status"] == "rejected_norm"


def test_batch_plan_requires_model_choice_then_calculates_code(monkeypatch):
    _trusted_active_base(monkeypatch)
    plan = {
        "object": {"object_type": "electrical", "area_total_m2": None, "floors": 1},
        "works": [
            [
                "Монтаж аппарата",
                "прибор аппарат установка присоединение",
                "electric",
                "device",
                "монтаж",
                "шт",
                {"piece_count": 2},
            ]
        ],
    }

    result = h.run_estimate_harness("смонтировать 2 аппарата", _model_complete(plan))

    assert result["planner_status"] == "batch"
    assert result["computed"][0]["code"] == "ГЭСНм08-03-575-01"
    assert result["computed"][0]["qty"] == 2.0
    assert any(item["tool"] == "model_norm_choice" and item["status"] == "selected" for item in result["trace"])
    assert result["calculation_status"] == "partial"


def test_extract_json_from_markdown_wrapped_response():
    value = h._extract_json('план ниже:\n```json\n{"object":{"area_total_m2":150},"works":[]}\n```')
    assert value == {"object": {"area_total_m2": 150}, "works": []}


def test_model_prose_numbers_never_become_estimate():
    result = h.run_estimate_harness("гараж 50 м²", lambda _messages: "Итого 5 миллионов.", max_steps=3)
    assert result["computed"] == []
    assert result["planner_status"] == "no_json"


def test_planner_repairs_non_json_once():
    responses = iter(
        [
            "Сначала опишу план текстом.",
            '{"object":{"object_type":"house","area_total_m2":150,"floors":1},"works":[]}',
            '{"object":{"object_type":"house","area_total_m2":150,"floors":1},"works":[]}',
        ]
    )
    result = h.run_estimate_harness("дом 150 м2", lambda _messages: next(responses))

    assert result["planner_status"] == "batch"
    assert result["trace"][0] == {"tool": "planner_repair", "status": "ok"}


def test_planner_prompt_contains_role_pack_and_notebook(monkeypatch):
    monkeypatch.setattr(h, "gesn_notebook_prompt_excerpt", lambda: "[Блокнот ГЭСН]\n08: электромонтаж")
    seen = []

    def complete(messages):
        seen.append(messages)
        return '{"object":{"object_type":"x","area_total_m2":null,"floors":1},"works":[]}'

    result = h.run_estimate_harness("объект", complete)
    system = seen[0][0]["content"]

    assert "smeta_agent_v2" in system
    assert "[Блокнот ГЭСН]" in system
    assert "search_norm не выбирает норму за тебя" in system
    assert "object_templates" not in system
    assert result["notebook_context"]["service_notebooks"] == ["gesn"]


def test_assumption_prompt_allows_scenario_but_keeps_assumptions_visible():
    seen = []

    def complete(messages):
        seen.append(messages)
        return '{"object":{"object_type":"object","area_total_m2":5000,"floors":1},"works":[]}'

    result = h.run_estimate_harness("объект 5000 м2, придумай сам по допущениям", complete)

    assert "не отказывайся только потому, что нет проекта/вор/рд" in seen[0][0]["content"].lower()
    assert "Пользователь явно разрешил сценарную прикидку" in seen[0][1]["content"]
    assert result["assumption_mode"] is True


def test_parse_domain_parameters_from_user_text():
    params = h.parse_params(
        "группа грунта II, глубина котлована 2 метра, плита 400 мм, "
        "периметр стен 160 метров, объем выработки грунта 200 м3"
    )

    assert params["soil_group"] == 2.0
    assert params["excavation_depth_m"] == 2.0
    assert params["slab_thickness_m"] == 0.4
    assert params["wall_length_m"] == 160.0
    assert params["volume_m3"] == 200.0


def test_parse_mass_formats_and_pile_count():
    assert abs(h.parse_params("Общая масса 664 711,12 кг")["mass_t"] - 664.71112) < 0.00001
    assert h.parse_params("масса 12,5 т")["mass_t"] == 12.5
    assert h.parse_params("дом на 20 сваях")["pile_count"] == 20
    assert "pile_count" not in h.parse_params("дом на сваях")


def test_vor_piece_area_is_not_object_area():
    text = "ВОР: окраска пластин, площадь 0,07 м²/шт. Количество 3 шт."
    slots = h.parse_params(text)

    assert slots["area_m2"] == 0.07
    assert h._object_area_from_text(text, slots) is None


def test_explicit_work_estimate_route_is_narrow():
    assert h.is_explicit_work_estimate_request(
        "рассчитать сметную стоимость работ по разработке траншеи вручную, объем 200 м3"
    )
    assert not h.is_explicit_work_estimate_request("покажи позиции из сметы объем 200 м3")


def test_parse_pricebook_hint_uses_visible_book(monkeypatch):
    from proxy.services import fgis_price_service as fps

    monkeypatch.setattr(fps, "available_pricebooks", lambda *args, **kwargs: ["/tmp/spb_2kv2026.parquet"])
    assert h.parse_pricebook_hint("2 квартал 2026 года по Санкт-Петербургу") == "spb_2kv2026"


def test_piece_unit_hint_is_preserved():
    normalized, _ = h._normalize_work_item(
        {
            "work": "монтаж аппарата",
            "work_description": "монтаж аппарата",
            "work_family": "electric",
            "element_type": "device",
            "action": "монтаж",
            "unit_hint": "шт",
        }
    )
    assert normalized["unit_hint"] == "шт"


def test_resolve_slots_reports_critical_geometry_input():
    geom = _geometry(3000, 3, {"geometry": {"H": 3.0}})
    _spec, namespace, missing, assumptions = h.resolve_slots("foundation_slab", geom, {})

    assert "slab_thickness_m" in missing
    assert namespace["slab_area_m2"] == namespace["S1"]
    assert any("slab_area_m2" in item for item in assumptions)
