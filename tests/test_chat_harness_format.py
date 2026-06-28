from proxy.routers.chat import _format_harness


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
    assert "1200" in text
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
