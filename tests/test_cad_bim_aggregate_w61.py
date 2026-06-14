"""W6.1 — агрегатные BIM-чанки (этаж×система×категория) в проекции. 0 LLM."""
from proxy.services.cad_bim_graph import render_projection, _aggregate_projection_lines


def _el(sid, name, category, level, object_type="", family=""):
    return {
        "source_id": sid, "name": name, "object_type": object_type, "speckle_type": "",
        "layer": "", "family": family, "category": category, "level": level,
        "material": "", "attributes_json": "{}",
    }


def test_aggregate_summary_and_groups():
    elements = [
        _el("d1", "Воздуховод 1", "Воздуховоды", "Этаж 03", "duct"),
        _el("d2", "Воздуховод 2", "Воздуховоды", "Этаж 03", "duct"),
        _el("d3", "Воздуховод 3", "Воздуховоды", "Этаж 03", "duct"),
        _el("w1", "Стена 1", "Стены", "Этаж 01", "wall"),
    ]
    props_by_src = {}
    lines = "\n".join(_aggregate_projection_lines(elements, props_by_src))
    assert "## BIM summary (aggregate)" in lines
    assert "Elements: 4" in lines
    # сводка «воздуховоды на этаже 3» — отдельный агрегатный чанк
    assert "## Aggregate Этаж 03 / Вентиляция / Воздуховоды" in lines
    assert "Count/Количество: 3" in lines
    assert "Воздуховод 1" in lines and "Воздуховод 3" in lines


def test_aggregate_common_properties():
    elements = [_el("d1", "В1", "Воздуховоды", "Этаж 03"), _el("d2", "В2", "Воздуховоды", "Этаж 03")]
    props = {
        "d1": [{"name": "Система", "value": "П1", "unit": "", "property_set": ""}],
        "d2": [{"name": "Система", "value": "П1", "unit": "", "property_set": ""}],
    }
    lines = "\n".join(_aggregate_projection_lines(elements, props))
    # одинаковое системное свойство → группа по системе «П1» + общее свойство
    assert "П1" in lines
    assert "Common properties" in lines


def test_render_projection_includes_aggregate_before_elements():
    elements = [_el("d1", "Воздуховод 1", "Воздуховоды", "Этаж 03", "duct")]
    out = render_projection("imp1", "test.json", "revit", elements, relations=[], properties=[])
    assert "## BIM summary (aggregate)" in out
    # агрегат идёт ДО поэлементной секции
    assert out.index("## BIM summary") < out.index("## Element")


def test_empty_elements_no_aggregate():
    assert _aggregate_projection_lines([], {}) == []
