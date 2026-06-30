from types import SimpleNamespace

import pytest

from proxy.routers.chat import (
    _compact_question_excerpt,
    _estimate_harness_plan_tokens,
    _format_harness,
    _format_harness_artifact,
    _format_smeta_dialog_state,
    _harness_voice_comment,
    _smeta_dialog_state,
    _voice_claims_source_truncated,
)


def test_harness_answer_is_operator_facing_with_numbers():
    text = _format_harness({
        "schema": {"object_type": "residential_house", "area_total_m2": 150},
        "total_status": "complete",
        "computed": [{
            "work": "Каркасные стены",
            "code": "ГЭСН:10-02-017-03",
            "qty": 1.86,
            "norm_unit": "100 м2",
            "phys_qty": 186.0,
            "physical_unit": "м2",
            "assumptions": ["норма выбрана по лучшему кандидату; требуется проверка"],
        }],
        "needs_input": [],
        "rejected": [],
        "partial_total": {"smr": 1000, "grand_total": 1200, "positions": 1},
        "final_total": {"smr": 1000, "grand_total": 1200, "positions": 1},
        "trace": [{"tool": "search_norm"}],
        "steps": 1,
    })

    assert text.startswith("**Предварительная сметная стоимость**")
    assert "Итого" in text
    assert "1 200.00" in text
    assert "Каркасные стены" in text
    assert "ГЭСН:10-02-017-03" in text
    assert "Планировщик" not in text
    assert "search_norm" not in text
    assert "декомпозиция" not in text.lower()


def test_harness_voice_allows_short_human_comment(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "Считаю то, что можно привязать к нормам.\n"
                "А спорное пока не тащу в итог: смета не место для гадания."
            )}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    text = _harness_voice_comment({"computed": [{}], "needs_input": [{}]}, "вопрос")

    assert "Считаю то" in text
    assert "\n" in text


def test_harness_plan_budget_scales_for_large_tz_context():
    small = [{"role": "user", "content": "скамья 3 шт"}]
    medium = [{"role": "user", "content": "ВОР\n" + ("строка\n" * 900)}]
    large = [{"role": "user", "content": "ВОР\n" + ("строка\n" * 1800)}]

    assert _estimate_harness_plan_tokens(small) == 1100
    assert _estimate_harness_plan_tokens(medium) == 1800
    assert _estimate_harness_plan_tokens(large) == 2400


def test_harness_voice_has_safe_excerpt_and_no_fake_truncation_claim():
    long_question = "начало ТЗ\n" + ("строка ведомости\n" * 180) + "конец ТЗ"
    excerpt = _compact_question_excerpt(long_question, max_chars=600)

    assert excerpt["truncated"] is True
    assert "начало ТЗ" in excerpt["text"]
    assert "конец ТЗ" in excerpt["text"]
    assert _voice_claims_source_truncated("исходные обрываются на п.9, пришлите продолжение")
    assert not _voice_claims_source_truncated("нужно уточнить толщину стены и способ монтажа")


def test_harness_voice_suppresses_unsupported_attachment_truncation_claim(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "Исходные обрываются на пункте 9, пришлите продолжение ведомости."
            )}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    text = _harness_voice_comment({"total_status": "blocked", "needs_input": [{}]}, "ВОР\n" + ("x" * 3000))

    assert text == ""


def test_harness_voice_allows_visible_estimator_reasoning(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "Я вижу объектный запрос, а не готовую ВОР: бетонная дача сама по себе ещё не объём.\n"
                "Кровлю и отделку можно обсуждать как разделы, но считать их без площади дома — это уже цирк с калькулятором.\n"
                "Сначала нужны площадь или габариты, дальше можно разложить фундамент, стены, перекрытия и кровлю.\n"
                "После этого инструмент нормально подберёт нормы и посчитает, а не будет изображать смету на салфетке."
            )}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    text = _harness_voice_comment({
        "total_status": "blocked",
        "computed": [],
        "needs_input": [{"work": "Устройство кровли", "missing_slots": ["area_total_m2"]}],
    }, "хочу построить бетонную двухэтажную дачу")

    assert "объектный запрос" in text
    assert "площадь" in text
    assert len(text) > 250


def test_harness_voice_trims_model_table_rewrite(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "Понимаю запрос как объектную смету, но исходных ещё мало.\n"
                "Сначала нужны габариты и конструктив, иначе смета будет гаданием.\n\n"
                "Таблица расчётного слоя (статус: blocked)\n"
                "1) Устройство кровли — pending"
            )}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    text = _harness_voice_comment({"total_status": "blocked", "needs_input": [{}]}, "вопрос")

    assert "Понимаю запрос" in text
    assert "Таблица расчётного слоя" not in text
    assert "Устройство кровли" not in text


def test_harness_voice_allows_exact_payload_facts(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "По ГЭСН:10-02-017-03 расчётная часть есть, 1 200.00 ₽ вижу в таблице.\n"
                "Остальное без гадания держу в уточнении."
            )}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    text = _harness_voice_comment({
        "computed": [{"code": "ГЭСН:10-02-017-03"}],
        "final_total": {"grand_total": 1200.0, "smr": 1000.0},
    }, "вопрос")

    assert "ГЭСН:10-02-017-03" in text
    assert "1 200.00 ₽" in text


def test_harness_voice_rejects_partial_money_even_when_partial_total_exists(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "Часть расчёта есть: 1 200.00 ₽, но финал держу в уточнении."
            )}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    text = _harness_voice_comment({
        "computed": [{"code": "ГЭСН:10-02-017-03"}],
        "needs_input": [{"work": "Параметры"}],
        "partial_total": {"grand_total": 1200.0, "smr": 1000.0},
        "final_total": None,
    }, "вопрос")

    assert text == ""


def test_harness_voice_rejects_partial_contradiction_when_partial_total_visible(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "Деньги сейчас не считаю: без региона это будет художественная литература."
            )}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    text = _harness_voice_comment({
        "total_status": "partial",
        "computed": [{"work": "Каркас", "code": "ГЭСН:10-02-017-03"}],
        "needs_input": [{"work": "Фундамент", "reason": "нет типа основания"}],
        "partial_total": {"grand_total": 1200.0, "smr": 1000.0},
        "final_total": None,
    }, "дай смету на дачу")

    assert text == ""


@pytest.mark.parametrize("bad_text", [
    "Получилось 1 200 ₽, жить можно.",
    "Беру ГЭСН:10-02-017-03, дальше видно.",
    "НР 109% оставляю как есть.",
])
def test_harness_voice_rejects_numbers_codes_and_percents(monkeypatch, bad_text):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": bad_text}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    assert _harness_voice_comment({"computed": [{}]}, "вопрос") == ""


def test_harness_answer_shows_candidate_table_without_tool_trace():
    text = _format_harness({
        "schema": {"object_type": "house", "area_total_m2": 150},
        "total_status": "blocked",
        "computed": [],
        "needs_input": [],
        "rejected": [{
            "work": "Сваи",
            "code": "ГЭСН:05-01-089-03",
            "reason": "нужны параметры",
            "candidates": [
                {"norm_code": "ГЭСН:05-01-089-03", "measure_unit": "шт"},
                {"norm_code": "ГЭСН:05-01-089-06", "measure_unit": "шт"},
            ],
            "selection": {"reason": "есть применимый лидер, но отрыв от альтернатив мал"},
        }],
        "partial_total": None,
        "final_total": None,
        "trace": [{"tool": "search_norm"}],
        "steps": 1,
    })

    assert "| Работа | Норма |" in text
    assert "ГЭСН:05-01-089-03" in text
    assert "Число не показываю" in text
    assert "search_norm" not in text
    assert "кандидат" not in text.lower()


def test_harness_answer_humanizes_missing_object_area_slot():
    text = _format_harness({
        "schema": {"object_type": "house", "area_total_m2": None},
        "total_status": "blocked",
        "computed": [],
        "needs_input": [{
            "work": "Устройство кровли",
            "missing_slots": ["area_total_m2"],
            "reason": "нет исходной площади/габаритов объекта",
        }],
        "rejected": [],
        "partial_total": None,
        "final_total": None,
    })

    assert "площадь/габариты объекта" in text
    assert "area_total_m2" not in text


def test_harness_answer_humanizes_internal_technical_terms():
    text = _format_harness({
        "schema": {"object_type": "house", "area_total_m2": None},
        "total_status": "blocked",
        "computed": [],
        "needs_input": [{
            "work": "Монолитные стены",
            "missing_slots": ["wall_length_m", "wall_height_m", "wall_thickness_m"],
            "reason": "нет расчётной формулы для element_type=monolithic_wall; нет параметров: wall_length_m",
        }],
        "rejected": [],
        "partial_total": None,
        "final_total": None,
    })

    assert "длина/периметр стен" in text
    assert "высота стен" in text
    assert "толщина стен" in text
    assert "для типа работ: монолитные стены" in text
    assert "element_type" not in text
    assert "wall_length_m" not in text


def test_harness_answer_marks_assumption_scenario():
    text = _format_harness({
        "schema": {"object_type": "house", "area_total_m2": 200},
        "assumption_mode": True,
        "scenario_assumptions": ["площадь принята по допущению"],
        "total_status": "partial",
        "computed": [{
            "work": "Устройство кровли",
            "code": "ГЭСН:12-01-024-01",
            "qty": 1.25,
            "norm_unit": "100 м2",
            "phys_qty": 125,
            "physical_unit": "м2",
        }],
        "needs_input": [{"work": "Фундамент", "reason": "нет типа основания"}],
        "rejected": [],
        "partial_total": {"smr": 1000, "grand_total": 1200, "positions": 1},
        "final_total": None,
    })

    assert "Сценарий по допущениям" in text
    assert "площадь принята по допущению" in text
    assert "не проектная смета" in text


def test_harness_partial_total_does_not_contradict_visible_number():
    text = _format_harness({
        "schema": {"object_type": "house", "area_total_m2": 150},
        "total_status": "partial",
        "computed": [{
            "work": "Каркасные стены",
            "code": "ГЭСН:10-02-017-03",
            "qty": 1.5,
            "norm_unit": "100 м2",
            "phys_qty": 150,
            "physical_unit": "м2",
        }],
        "needs_input": [{"work": "Земляные работы", "reason": "нет параметров"}],
        "rejected": [],
        "partial_total": {"smr": 1000, "grand_total": 1200, "positions": 1},
        "final_total": None,
        "trace": [],
        "steps": 1,
    })

    assert "~1 200.00 ₽" in text
    assert "Число не показываю" not in text
    assert "Финальную сумму не показываю" in text


def test_harness_summary_points_to_resource_artifact():
    result = {
        "schema": {"object_type": "metal_structure"},
        "total_status": "complete",
        "computed": [{
            "work": "Монтаж металлоконструкций",
            "code": "ГЭСНм:38-01-001-01",
            "qty": 664.71112,
            "norm_unit": "т",
            "phys_qty": 664.71112,
            "physical_unit": "т",
        }],
        "needs_input": [],
        "rejected": [],
        "partial_total": {"smr": 118799319.94, "grand_total": 145410367.61, "positions": 1},
        "final_total": {"smr": 118799319.94, "grand_total": 145410367.61, "positions": 1},
        "estimate": {
            "positions": [{
                "code": "ГЭСНм:38-01-001-01",
                "name": "Монтаж металлоконструкций",
                "unit": "т",
                "qty": 664.71112,
                "total": 118799319.94,
                "base": {
                    "ozp": 36405429.06,
                    "em": 16216870.11,
                    "zpm": 4992641.90,
                    "mat": 2010010.78,
                    "direct": 54632309.95,
                    "fot": 41398070.96,
                    "nr": 38500205.99,
                    "sp": 25666804.00,
                    "total": 118799319.94,
                },
                "adjusted": {
                    "ozp": 36405429.06,
                    "em": 16216870.11,
                    "zpm": 4992641.90,
                    "mat": 2010010.78,
                    "direct": 54632309.95,
                    "fot": 41398070.96,
                    "nr": 38500205.99,
                    "sp": 25666804.00,
                    "total": 118799319.94,
                },
                "resources": [
                    {
                        "kind": "labor",
                        "code": "1-1",
                        "name": "Средний разряд работы",
                        "unit": "чел.-ч",
                        "qty": 123.456,
                        "price_used": 100.0,
                        "cost": 12345.6,
                    },
                    {
                        "kind": "machine",
                        "code": "91.05.01-001",
                        "name": "Краны",
                        "unit": "маш.-ч",
                        "qty": 7.5,
                        "price_used": 2000.0,
                        "cost": 15000.0,
                    },
                    {
                        "kind": "material",
                        "code": "101-0001",
                        "name": "Электроды",
                        "unit": "кг",
                        "qty": 90.0,
                        "price_used": 10.0,
                        "cost": 900.0,
                    },
                    {
                        "kind": "material",
                        "name": "Нестандартный материал",
                        "unit": "шт",
                        "qty": 1,
                        "price_used": None,
                        "price_action": "needs_kac",
                        "cost": 0.0,
                    },
                ],
                "price_requirements": [{
                    "action": "needs_kac",
                    "resource_name": "Нестандартный материал",
                    "message": "нужен КАЦ: Нестандартный материал",
                }],
            }],
            "summary": {
                "price_requirements": [{
                    "action": "needs_kac",
                    "resource_name": "Нестандартный материал",
                    "message": "нужен КАЦ: Нестандартный материал",
                }],
            },
        },
    }

    summary = _format_harness(result)
    artifact = _format_harness_artifact(result)

    assert "Полная ресурсная расшифровка" in summary
    assert "Средний разряд работы" not in summary
    assert "## Структура стоимости" in artifact
    assert "| НР | 38 500 205.99 |" in artifact
    assert "| СП | 25 666 804.00 |" in artifact
    assert "## Ресурсы" in artifact
    assert "Средний разряд работы" in artifact
    assert "Краны" in artifact
    assert "Электроды" in artifact
    assert "## Что нужно добрать для полного расчёта" in artifact
    assert "нужен КАЦ: Нестандартный материал" in artifact
    assert "Коэффициент не применён" in artifact


def test_smeta_dialog_state_preserves_tool_result_for_next_turn():
    result = {
        "schema": {"object_type": "concrete_house", "area_total_m2": None, "floors": 2},
        "total_status": "blocked",
        "computed": [],
        "needs_input": [{
            "work": "Устройство кровли",
            "status": "needs_input",
            "missing_slots": ["area_total_m2"],
            "reason": "нет исходной площади/габаритов объекта",
        }],
        "rejected": [],
    }

    state = _smeta_dialog_state(result)
    text = _format_smeta_dialog_state(state)

    assert state["schema"] == "smeta_dialog_state_v1"
    assert state["pending"][0]["missing_slots"] == ["площадь/габариты объекта"]
    assert "Предыдущий результат smeta-инструментов" in text
    assert "Устройство кровли" in text
    assert "площадь/габариты объекта" in text
    assert "area_total_m2" not in text


def test_smeta_dialog_state_humanizes_missing_slots_for_model_memory():
    state = _smeta_dialog_state({
        "total_status": "blocked",
        "schema": {"object_type": "house"},
        "computed": [],
        "needs_input": [{
            "work": "Стены",
            "reason": "нет параметров: wall_length_m, wall_height_m",
            "missing_slots": ["wall_length_m", "wall_height_m"],
        }],
        "rejected": [],
    })
    formatted = _format_smeta_dialog_state(state)

    assert "длина/периметр стен" in formatted
    assert "высота стен" in formatted
    assert "wall_length_m" not in formatted
    assert "wall_height_m" not in formatted


def test_harness_direct_quantity_title_does_not_show_planner_area():
    text = _format_harness({
        "schema": {"object_type": "metal_structure", "area_total_m2": 150},
        "direct_quantity_estimate": True,
        "total_status": "complete",
        "computed": [{
            "work": "Монтаж металлоконструкций",
            "code": "ГЭСНм:38-01-001-01",
            "qty": 664.71112,
            "norm_unit": "т",
            "phys_qty": 664.71112,
            "physical_unit": "т",
        }],
        "needs_input": [],
        "rejected": [],
        "partial_total": {"smr": 1000, "grand_total": 1200, "positions": 1},
        "final_total": {"smr": 1000, "grand_total": 1200, "positions": 1},
        "trace": [],
        "steps": 1,
    })

    assert "Монтаж металлоконструкций" in text
    assert "150 м²" not in text
