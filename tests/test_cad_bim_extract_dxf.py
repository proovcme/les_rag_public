import json

import ezdxf

from tools.cad_bim_extract_dxf import extract_dxf


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
