from proxy.services.rim_scenario_service import (
    calculation_rows_for_scenario,
    requirements_from_calculation,
    validate_authored_scenarios,
)


def _work_rows():
    return [
        {"work_id": "w1", "work_name": "Работа 1", "unit": "м", "quantity": 10, "section_name": "1"},
        {"work_id": "w2", "work_name": "Работа 2", "unit": "шт", "quantity": 2, "section_name": "1"},
    ]


def _mapping_rows():
    return [
        {
            "mapping_row_id": "m11",
            "work_id": "w1",
            "norm_key": "ГЭСНм:10-01-001-01",
            "selection_status": "accepted",
            "card_opened": True,
        },
        {
            "mapping_row_id": "m12",
            "work_id": "w1",
            "norm_key": "ГЭСНм:10-01-001-02",
            "selection_status": "accepted",
            "card_opened": True,
        },
        {
            "mapping_row_id": "m21",
            "work_id": "w2",
            "norm_key": "ГЭСНм:10-01-002-01",
            "selection_status": "accepted",
            "card_opened": True,
        },
        {
            "mapping_row_id": "m22",
            "work_id": "w2",
            "norm_key": "ГЭСНм:10-01-002-02",
            "selection_status": "accepted",
            "card_opened": True,
        },
    ]


def test_scenarios_are_explicit_and_not_materialized_as_cartesian_product():
    result = validate_authored_scenarios(
        _work_rows(),
        _mapping_rows(),
        [
            {
                "scenario_id": "s1",
                "title": "Основной",
                "authored_by": "model",
                "compatibility_reason": "Один технологический вариант",
                "selections": [
                    {"mapping_row_id": "m11"},
                    {"mapping_row_id": "m21"},
                ],
            }
        ],
    )
    assert result["theoretical_count"] == 4
    assert result["scenario_count"] == 1
    assert result["issues"] == []
    assert [item["mapping_row_id"] for item in result["scenarios"][0]["selections"]] == [
        "m11",
        "m21",
    ]


def test_large_candidate_space_requests_authored_strategy_without_enumeration():
    result = validate_authored_scenarios(
        _work_rows(),
        _mapping_rows(),
        [],
        max_combinations=3,
    )
    assert result["scenarios"] == []
    assert result["issues"] == [
        {
            "code": "theoretical_combination_limit_exceeded",
            "severity": "blocking",
            "theoretical_count": 4,
            "max_combinations": 3,
            "required_action": "author_explicit_compatible_scenarios",
        }
    ]


def test_calculation_rows_use_only_authored_selections():
    scenario = validate_authored_scenarios(
        _work_rows(),
        _mapping_rows(),
        [
            {
                "scenario_id": "s1",
                "authored_by": "user",
                "compatibility_reason": "Проверено",
                "selections": [{"mapping_row_id": "m12"}, {"mapping_row_id": "m22"}],
            }
        ],
    )["scenarios"][0]
    rows = calculation_rows_for_scenario(_work_rows(), _mapping_rows(), scenario)
    assert [row["norm_code"] for row in rows] == [
        "ГЭСНм10-01-001-02",
        "ГЭСНм10-01-002-02",
    ]


def test_calculation_gaps_become_typed_requirements():
    requirements = requirements_from_calculation(
        {
            "blockers": [
                {
                    "code": "machine_operator_mapping_missing",
                    "work_id": "w1",
                    "resource_code": "91.01.01-001",
                    "reason": "Нет официального mapping машиниста",
                },
                {
                    "code": "unit_incompatible",
                    "work_id": "w2",
                    "reason": "Неизвестен перевод единицы",
                },
            ],
            "summary": {
                "price_requirements": [
                    {
                        "action": "needs_kac",
                        "work_id": "w1",
                        "resource_code": "01.7.15.01-0011",
                        "description": "Нет текущей цены",
                    }
                ]
            },
        }
    )
    assert {item["kind"] for item in requirements} == {
        "machine_operator_map",
        "unit_conversion",
        "kac",
    }
    assert all(item["finality_policy"] == "blocks_final" for item in requirements)


def test_resource_row_without_price_becomes_blocking_kac_requirement():
    requirements = requirements_from_calculation(
        {
            "sections": [
                {
                    "positions": [
                        {
                            "work_id": "w1",
                            "source_refs": ["spec.xlsx#row=14"],
                            "rows": [
                                {
                                    "type": "resource_material",
                                    "label": "Кабель U/UTP",
                                    "columns": {2: "01.7.15.01-0011", 12: 0},
                                    "meta": {"price_action": "needs_kac"},
                                }
                            ],
                            "summary": {
                                "flags": [
                                    "нужен КАЦ: Кабель U/UTP (01.7.15.01-0011)"
                                ]
                            },
                        }
                    ]
                }
            ],
            "summary": {"flags": []},
        }
    )
    assert len(requirements) == 1
    assert requirements[0]["kind"] == "kac"
    assert requirements[0]["resource_code"] == "01.7.15.01-0011"
    assert requirements[0]["severity"] == "blocking"
    assert requirements[0]["source_refs"] == ["spec.xlsx#row=14"]
