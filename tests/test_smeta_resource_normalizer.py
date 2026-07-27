import pytest

from proxy.smeta_core.resource_normalizer import normalize_norm_resources


def test_grade_breakdown_replaces_average_and_textual_labor_totals():
    resources = [
        {"kind": "labor", "code": "1-100-36", "name": "Средний разряд работы 3.6", "per_unit": 15.2},
        {"kind": "labor", "code": "", "name": "ЗАТРАТЫ ТРУДА РАБОЧИХ, ВСЕГО: В ТОМ ЧИСЛЕ:", "per_unit": 15.6},
        {"kind": "labor", "code": "2-100-02", "name": "Рабочий 2 разряда", "per_unit": 0.02},
        {"kind": "labor", "code": "2-100-03", "name": "Рабочий 3 разряда", "per_unit": 10.75},
        {"kind": "labor", "code": "2-100-04", "name": "Рабочий 4 разряда", "per_unit": 4.83},
        {"kind": "machine", "code": "91.1", "name": "Автомобиль", "per_unit": 0.01},
    ]

    normalized = normalize_norm_resources(resources)

    assert [row["code"] for row in normalized if row["kind"] == "labor"] == [
        "2-100-02", "2-100-03", "2-100-04"
    ]
    assert sum(row["per_unit"] for row in normalized if row["kind"] == "labor") == pytest.approx(15.6)
    assert [row["code"] for row in normalized if row["kind"] == "machine"] == ["91.1"]


def test_average_labor_is_kept_when_no_grade_breakdown_exists():
    normalized = normalize_norm_resources([
        {"kind": "labor", "code": "1-100-30", "name": "Средний разряд работы 3.0", "per_unit": 4.94},
        {"kind": "labor", "code": "", "name": "Затраты труда рабочих, всего", "per_unit": 4.94},
        {"kind": "material", "code": "01.1", "name": "Материал", "per_unit": 1},
    ])

    assert [row.get("code") for row in normalized] == ["1-100-30", "01.1"]
