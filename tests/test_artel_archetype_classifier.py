"""W10.2 — cheap deterministic family -> candidate-archetype classifier and the
corpus coverage report that prioritizes which archetypes to author first.
"""

from __future__ import annotations

from tools import artel_archetype_classifier as clf


def _catalog(family_name, category, param_names, *, types=1, materials=1,
             bbox=None, solid_count=None):
    catalog = {
        "schema": "artel.revit_family_catalog.v1",
        "family_name": family_name,
        "category": category,
        "parameters": [{"name": name, "storage_type": "Double"} for name in param_names],
        "types": [{"name": f"{family_name} {i}"} for i in range(types)],
        "materials": [{"name": f"mat{i}"} for i in range(materials)],
        "family_symbols": [],
    }
    if bbox is not None:
        catalog["bounding_box"] = bbox
    if solid_count is not None:
        catalog["solid_count"] = solid_count
    return catalog


CABINET = _catalog("Шкаф архивный", "Furniture", ["ADSK_Наименование", "Ширина", "Глубина", "Высота"])
CABINET_EN = _catalog("Storage cabinet", "Casework", ["Width", "Depth", "Height"])
PANEL = _catalog("Щит стеновой", "Generic Models", ["Ширина", "Высота", "Толщина"],
                 bbox={"x": 1200, "y": 800, "z": 20})
PIPE_FITTING = _catalog("Отвод 90", "Pipe Fittings", ["Диаметр", "Угол"])
COLUMN_ROUND = _catalog("Колонна круглая", "Columns", ["Диаметр", "Высота"])
BEAM = _catalog("Балка двутавр", "Structural Framing", ["Длина", "Высота сечения"],
                bbox={"x": 100, "y": 200, "z": 6000})
WEIRD = _catalog("Светильник декоративный", "Lighting Fixtures", ["ADSK_Наименование", "Мощность"])


def test_cabinet_classifies_as_rect_cabinet():
    result = clf.classify(clf.extract_features(CABINET))
    assert result["archetype"] == "rect_cabinet"
    assert result["confidence"] in {"high", "medium"}
    assert result["implemented"] is True  # rect_cabinet is in the geometry library


def test_panel_classifies_as_panel():
    result = clf.classify(clf.extract_features(PANEL))
    assert result["archetype"] == "panel"
    assert result["implemented"] is True
    assert any("толщ" in r.lower() or "тонк" in r.lower() for r in result["reasons"])


def test_mep_fitting_classifies_as_flanged_fitting_not_implemented():
    result = clf.classify(clf.extract_features(PIPE_FITTING))
    assert result["archetype"] == "flanged_fitting"
    assert result["implemented"] is False  # not authored yet -> a "write first" candidate


def test_round_column_classifies_as_cylinder():
    result = clf.classify(clf.extract_features(COLUMN_ROUND))
    assert result["archetype"] == "cylinder_revolve"


def test_beam_classifies_as_bar_profile_via_bbox():
    result = clf.classify(clf.extract_features(BEAM))
    assert result["archetype"] == "bar_profile"
    assert any("длинн" in r.lower() or "линейн" in r.lower() for r in result["reasons"])


def test_unmatched_family_is_unknown():
    result = clf.classify(clf.extract_features(WEIRD))
    assert result["archetype"] == "unknown"
    assert result["implemented"] is False


def test_classification_is_deterministic():
    f = clf.extract_features(CABINET)
    assert clf.classify(f) == clf.classify(f)


def test_coverage_report_ranks_and_prioritizes():
    corpus = [CABINET, CABINET_EN, PANEL, PIPE_FITTING, COLUMN_ROUND, BEAM, WEIRD]
    report = clf.coverage_report(corpus)

    assert report["total_families"] == 7
    # rect_cabinet has the most members -> ranked first.
    assert report["ranking"][0]["archetype"] == "rect_cabinet"
    assert report["ranking"][0]["count"] == 2
    # unknown is always last.
    assert report["ranking"][-1]["archetype"] == "unknown"

    # write_first = highest-coverage archetypes that are not yet implemented.
    assert "flanged_fitting" in report["write_first"]
    assert "cylinder_revolve" in report["write_first"]
    assert "rect_cabinet" not in report["write_first"]  # already implemented
    assert "unknown" not in report["write_first"]


def test_report_renders_without_error():
    report = clf.coverage_report([CABINET, PANEL, PIPE_FITTING])
    text = clf._render_report(report)
    assert "Покрытие архетипами" in text
    assert "Писать первыми" in text
