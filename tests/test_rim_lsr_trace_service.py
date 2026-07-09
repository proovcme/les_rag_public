"""РИМ-трасса ЛСР: графы 2-12, цены ФГИС ЦС и итог позиции."""

from __future__ import annotations

from proxy.services.rim_lsr_trace_service import (
    build_lsr_trace,
    build_lsr_trace_from_visible_rows,
    build_position_trace,
    positions_from_visible_lsr_rows,
)


CODE = "ГЭСН12-01-034-02"


def _rows_by_type(trace):
    return {row["type"]: row for row in trace["rows"]}


def test_rim_trace_from_gesn_seed_reproduces_gold_position():
    trace = build_position_trace({"code": CODE, "qty": 0.61})
    summary = trace["summary"]

    assert summary["flags"] == []
    assert summary["ozp"] == 3750.23
    assert summary["em"] == 992.40
    assert summary["mat"] == 83.62
    assert summary["direct"] == 4826.25
    assert summary["fot"] == 4208.91
    assert summary["nr"] == 4587.71
    assert summary["sp"] == 2399.08
    assert summary["total"] == 11813.04
    # нормативные чел.-ч (в шапку многопозиционной формы) — те же, что в групп-строках
    assert summary["labor_qty"] == 7.8934
    assert summary["machinist_qty"] > 0

    rows = _rows_by_type(trace)
    assert rows["work"]["columns"]["2"] == CODE
    assert rows["work"]["columns"]["4"] == "100 м2"
    assert rows["work"]["columns"]["7"] == 0.61
    assert rows["group_labor"]["columns"]["7"] == 7.8934
    assert rows["group_labor"]["columns"]["12"] == 3750.23
    assert rows["group_machine"]["columns"]["12"] == 992.4
    assert rows["group_machinist"]["columns"]["12"] == 458.68
    assert rows["group_material"]["columns"]["12"] == 83.62
    assert rows["nr"]["source"] == "Пр/812"
    assert rows["sp"]["source"] == "Пр/774"


def test_visible_rows_accept_colon_prefixed_norm_codes():
    trace = build_lsr_trace_from_visible_rows([
        {
            "basis": "ГЭСНм:38-01-001-01",
            "title": "Монтаж листовых металлических конструкций",
            "unit": "т",
            "quantity": 1,
        }
    ])

    summary = trace["summary"]
    assert summary["bound_rows"] == 1
    assert trace["row_bindings"][0]["status"] == "bound"
    assert trace["sections"][0]["positions"][0]["code"] == "ГЭСНм38-01-001-01"


def test_visible_rows_accept_engineering_count_unit_aliases():
    trace = build_lsr_trace_from_visible_rows([
        {
            "basis": "ГЭСНм:10-02-050-01",
            "title": "Установка телекоммуникационного шкафа",
            "unit": "шт",
            "quantity": 1,
        },
        {
            "basis": "ГЭСН:10-03-032-02",
            "title": "Проверка линий связи",
            "unit": "линия",
            "quantity": 80,
        },
    ])

    summary = trace["summary"]
    assert summary["bound_rows"] == 2
    assert trace["row_bindings"][0]["quantity_trace"]["status"] == "direct_from_row"
    assert trace["row_bindings"][1]["quantity_trace"]["status"] == "direct_from_row"
    assert trace["sections"][0]["positions"][0]["code"] == "ГЭСНм10-02-050-01"
    assert trace["sections"][0]["positions"][1]["code"] == "ГЭСН10-03-032-02"


def test_visible_rows_convert_piece_dimensions_to_area_norm_qty():
    trace = build_lsr_trace_from_visible_rows([
        {
            "basis": "ГЭСН:15-01-052-01",
            "title": "Разработка проема 400х400 мм",
            "unit": "шт",
            "quantity": 10,
        },
        {
            "basis": "ГЭСН:15-01-059-01",
            "title": "Монтаж ревизионного лючка 400х400 мм скрытого типа",
            "unit": "шт",
            "quantity": 10,
        },
    ])

    assert trace["summary"]["bound_rows"] == 2
    assert trace["row_bindings"][0]["position"]["qty"] == 0.1
    assert trace["row_bindings"][1]["position"]["qty"] == 0.016
    assert trace["row_bindings"][0]["quantity_trace"]["status"] == "unit_conversion"
    assert trace["row_bindings"][1]["quantity_trace"]["status"] == "piece_area_conversion"


def test_rim_trace_applies_resource_coefficients_by_kind():
    trace = build_position_trace({"code": CODE, "qty": 0.61}, k_ozp=1.15, k_em=1.15)
    summary = trace["summary"]
    rows = _rows_by_type(trace)

    assert rows["coefficient"]["meta"] == {"k_ozp": 1.15, "k_em": 1.15}
    labor = next(row for row in trace["rows"] if row["type"] == "resource_labor")
    machine = next(row for row in trace["rows"] if row["type"] == "resource_machine")
    machinist = next(row for row in trace["rows"] if row["type"] == "resource_machinist")
    material = next(row for row in trace["rows"] if row["type"] == "resource_material")
    assert labor["columns"]["6"] == 1.15
    assert machine["columns"]["6"] == 1.15
    assert machinist["columns"]["6"] == 1.15
    assert material["columns"]["6"] == 1.0
    assert summary["ozp"] > 3750.23
    assert summary["machine"] > 533.72
    assert summary["zpm"] > 458.68
    assert summary["mat"] == 83.62
    assert summary["total"] > 11813.04


def test_rim_trace_preserves_fgis_current_vs_base_index_columns():
    class FakePriceBook:
        def lookup(self, code):
            return {
                "91.05.05-015": {
                    "price_current": 1663.18,
                    "price_base": 1167.7,
                    "index": None,
                    "price_current_eff": 1663.18,
                },
                "01.7.15.06-0111": {
                    "price_current": None,
                    "price_base": 70296.2,
                    "index": 1.3,
                    "price_current_eff": 91385.06,
                },
            }.get(code)

    trace = build_position_trace(
        {
            "code": "ГЭСН00-00-000-00",
            "name": "Тестовая работа",
            "unit": "шт",
            "qty": 2,
            "nr_pct": 0,
            "sp_pct": 0,
            "resources": [
                {"kind": "machine", "code": "91.05.05-015", "name": "Кран", "unit": "маш.-ч", "per_unit": 1},
                {"kind": "material", "code": "01.7.15.06-0111", "name": "Гвозди", "unit": "т", "per_unit": 0.001},
            ],
        },
        pricebook=FakePriceBook(),
    )

    machine = next(row for row in trace["rows"] if row["type"] == "resource_machine")
    material = next(row for row in trace["rows"] if row["type"] == "resource_material")

    assert machine["source"] == "fgis_current"
    assert machine["columns"]["10"] == 1663.18
    assert "8" not in machine["columns"]
    assert "9" not in machine["columns"]

    assert material["source"] == "fgis_base_index"
    assert material["columns"]["8"] == 70296.2
    assert material["columns"]["9"] == 1.3
    assert material["columns"]["10"] == 91385.06
    assert material["columns"]["12"] == 182.77
    assert trace["summary"]["direct"] == 3509.13


def test_build_lsr_trace_multi_position_sections_and_grand_total():
    # две gold-позиции в двух разделах → общий итог = 2× эталон; итоги разделов и свод — Σ позиций
    positions = [
        {"code": CODE, "qty": 0.61, "section": "Раздел 1. Кровля"},
        {"code": CODE, "qty": 0.61, "section": "Раздел 2. Прочее"},
    ]
    lsr = build_lsr_trace(positions, name="Кровля и прочее")

    assert lsr["name"] == "Кровля и прочее"
    assert lsr["summary"]["positions"] == 2
    assert lsr["summary"]["flags"] == []
    assert lsr["summary"]["total"] == 23626.08  # 2 × 11813.04 — gold позиции сохранён
    # свод суммирует позиции (прямые/ФОТ/НР/СП) — числа считает код, не LLM
    assert lsr["summary"]["direct"] == round(2 * 4826.25, 2)
    assert lsr["summary"]["fot"] == round(2 * 4208.91, 2)
    assert lsr["summary"]["nr"] == round(2 * 4587.71, 2)
    assert lsr["summary"]["sp"] == round(2 * 2399.08, 2)
    assert lsr["summary"]["labor_qty"] == round(2 * 7.8934, 6)

    secs = lsr["sections"]
    assert [s["section"] for s in secs] == ["Раздел 1. Кровля", "Раздел 2. Прочее"]
    assert secs[0]["total"] == 11813.04 and secs[1]["total"] == 11813.04
    # каждый раздел несёт полные трассы позиций (для рендера формы)
    assert len(secs[0]["positions"]) == 1
    assert secs[0]["positions"][0]["summary"]["total"] == 11813.04


def test_build_lsr_trace_groups_same_section_contiguously():
    # позиции одного раздела, вперемешку с другим, группируются → 2 раздела, не 3
    positions = [
        {"code": CODE, "qty": 0.61, "section": "A"},
        {"code": CODE, "qty": 0.61, "section": "B"},
        {"code": CODE, "qty": 0.61, "section": "A"},
    ]
    lsr = build_lsr_trace(positions)

    assert [s["section"] for s in lsr["sections"]] == ["A", "B"]
    assert len(lsr["sections"][0]["positions"]) == 2
    assert lsr["sections"][0]["total"] == round(2 * 11813.04, 2)
    assert lsr["summary"]["total"] == round(3 * 11813.04, 2)


def test_build_lsr_trace_default_section_when_unspecified():
    # без поля section → один раздел «Без раздела», свод = одна позиция
    lsr = build_lsr_trace([{"code": CODE, "qty": 0.61}])
    assert [s["section"] for s in lsr["sections"]] == ["Без раздела"]
    assert lsr["summary"]["total"] == 11813.04


def test_positions_from_visible_lsr_rows_converts_physical_unit_to_norm_qty():
    bound = positions_from_visible_lsr_rows([
        {"basis": "ГЭСН 12-01-034-02", "title": "Устройство обрешетки", "quantity": "61", "unit": "м2"}
    ])

    assert bound["row_bindings"][0]["status"] == "bound"
    assert bound["positions"][0]["code"] == CODE
    assert bound["positions"][0]["qty"] == 0.61
    assert bound["row_bindings"][0]["quantity_trace"]["formula"] == "61.0 м2 × 1 / 100 = 0.61"


def test_lsr_trace_from_visible_rows_builds_priced_trace_from_selected_norms():
    lsr = build_lsr_trace_from_visible_rows(
        [
            {
                "basis": "ГЭСН 12-01-034-02",
                "title": "Устройство обрешетки",
                "quantity": "61",
                "unit": "м2",
                "section": "Кровля",
            }
        ],
        name="Видимые строки",
    )

    assert lsr["summary"]["result_status"] == "priced_final"
    assert lsr["summary"]["input_rows"] == 1
    assert lsr["summary"]["bound_rows"] == 1
    assert lsr["summary"]["total"] == 11813.04
    assert lsr["sections"][0]["section"] == "Кровля"


def test_lsr_trace_from_visible_rows_keeps_unbound_rows_out_of_priced_final():
    lsr = build_lsr_trace_from_visible_rows(
        [
            {"basis": "ГЭСН 12-01-034-02", "title": "Устройство обрешетки", "quantity": "61", "unit": "м2"},
            {"title": "Работа без выбранной нормы", "quantity": "1", "unit": "шт"},
        ]
    )

    assert lsr["summary"]["result_status"] == "priced_partial"
    assert lsr["summary"]["bound_rows"] == 1
    assert lsr["summary"]["unbound_rows"] == 1
    assert lsr["row_bindings"][1]["status"] == "norm_selection_required"


def test_lsr_trace_from_visible_rows_does_not_bind_unknown_norm_code():
    lsr = build_lsr_trace_from_visible_rows(
        [{"basis": "ГЭСН 99-99-999-99", "title": "Неизвестная норма", "quantity": "1", "unit": "шт"}]
    )

    assert lsr["summary"]["result_status"] == "norm_selection_required"
    assert lsr["summary"]["bound_rows"] == 0
    assert lsr["summary"]["unbound_rows"] == 1
    assert lsr["row_bindings"][0]["status"] == "norm_not_found"
