from proxy.routers.chat import _format_harness, _format_harness_artifact


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

    assert "| Работа | Лучший кандидат |" in text
    assert "ГЭСН:05-01-089-03" in text
    assert "Число не показываю" in text
    assert "search_norm" not in text


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
                ],
            }],
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
    assert "Коэффициент не применён" in artifact
