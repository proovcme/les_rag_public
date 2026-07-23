import json
from pathlib import Path

import ezdxf

from tools import cad_bim_extract_dxf
from tools.cad_bim_extract_dxf import _json_safe, extract_dxf


def test_extract_dxf_builds_cad_bim_json(tmp_path):
    source = tmp_path / "node.dxf"
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "A-DETAIL"})
    msp.add_text("Узел УК-1", dxfattribs={"layer": "A-TEXT", "height": 2.5}).set_placement((1, 1))
    doc.saveas(source)

    payload = extract_dxf(source)

    assert payload["type"] == "DXFModel"
    assert payload["source_format"] == "dxf"
    assert len(payload["elements"]) == 2
    assert len(payload["relations"]) == 2
    text = json.dumps(payload, ensure_ascii=False)
    assert "A-DETAIL" in text
    assert "Узел УК-1" in text


def test_extract_dxf_reconstructs_drawn_table_from_lines_and_text(tmp_path):
    source = tmp_path / "drawn_table.dxf"
    doc = ezdxf.new()
    msp = doc.modelspace()
    x_edges = [0, 10, 25, 32]
    y_edges = [20, 10, 0]
    for x in x_edges:
        msp.add_line((x, y_edges[-1]), (x, y_edges[0]), dxfattribs={"layer": "TABLE"})
    for y in y_edges:
        msp.add_line((x_edges[0], y), (x_edges[-1], y), dxfattribs={"layer": "TABLE"})
    msp.add_text("Позиция", dxfattribs={"layer": "TEXT", "height": 1.5}).set_placement((1, 15))
    msp.add_text("Наименование", dxfattribs={"layer": "TEXT", "height": 1.5}).set_placement((11, 15))
    msp.add_text("Кол.", dxfattribs={"layer": "TEXT", "height": 1.5}).set_placement((26, 15))
    msp.add_text("1", dxfattribs={"layer": "TEXT", "height": 1.5}).set_placement((1, 5))
    msp.add_text("Клапан", dxfattribs={"layer": "TEXT", "height": 1.5}).set_placement((11, 5))
    msp.add_text("2", dxfattribs={"layer": "TEXT", "height": 1.5}).set_placement((26, 5))
    doc.saveas(source)

    payload = extract_dxf(source)

    assert payload["properties"]["drawn_tables_detected"] == 1
    table = payload["tables"][0]
    assert table["row_count"] == 2
    assert table["column_count"] == 3
    assert table["rows"][0]["cells"] == ["Позиция", "Наименование", "Кол."]
    assert table["rows"][1]["cells"] == ["1", "Клапан", "2"]


def test_extract_dwg_converts_to_dxf_before_building_graph(tmp_path, monkeypatch):
    source = tmp_path / "scheme.dwg"
    source.write_bytes(b"placeholder")
    converted_dir = tmp_path / "converted"

    def fake_convert_dwg_to_dxf(source_path: Path, *, output: Path, version: str = "r2013"):
        assert source_path == source
        doc = ezdxf.new()
        doc.modelspace().add_line((0, 0), (5, 0), dxfattribs={"layer": "FIRE"})
        output.parent.mkdir(parents=True, exist_ok=True)
        doc.saveas(output)
        return {"tool": "dwg2dxf", "target_version": version, "output": output.as_posix(), "warnings": ""}

    monkeypatch.setattr(cad_bim_extract_dxf, "_convert_dwg_to_dxf", fake_convert_dwg_to_dxf)

    payload = extract_dxf(source, converted_dxf_dir=converted_dir)

    assert payload["id"] == "dwg:scheme"
    assert payload["source_format"] == "dwg"
    assert payload["source_path"] == source.as_posix()
    assert payload["properties"]["conversion"]["tool"] == "dwg2dxf"
    assert (converted_dir / "scheme.dxf").exists()
    assert len(payload["elements"]) == 1


def test_extract_dxf_repairs_invalid_group_code_lines(tmp_path):
    source = tmp_path / "broken_text.dxf"
    doc = ezdxf.new()
    doc.modelspace().add_text("Line 1", dxfattribs={"layer": "TEXT"}).set_placement((0, 0))
    doc.saveas(source)
    text = source.read_text(encoding="utf-8")
    text = text.replace("Line 1\n", "Line 1\nbroken continuation\n", 1)
    source.write_text(text, encoding="utf-8")

    payload = extract_dxf(source)

    assert payload["properties"]["dxf_read_mode"] == "repaired_group_codes"
    assert payload["properties"]["dxf_repaired_invalid_group_codes"] >= 1
    assert len(payload["elements"]) == 1


def test_json_safe_replaces_surrogate_text():
    payload = {"text": "bad\udc82text", "items": ["ok", "bad\udcbf"]}

    safe = _json_safe(payload)

    json.dumps(safe, ensure_ascii=False)
    assert "\udc82" not in safe["text"]
