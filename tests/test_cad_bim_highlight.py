"""W6.7: связка вьювер↔чат — извлечение source_id и снимок подсветки (0 LLM, офлайн)."""

import pytest

from proxy.services.cad_bim_graph import render_projection
from proxy.services.cad_bim_highlight import (
    extract_highlight,
    get_highlight,
    reset_highlight,
    set_highlight,
)


@pytest.fixture(autouse=True)
def _clean_store():
    reset_highlight()
    yield
    reset_highlight()


def _element(source_id: str, name: str, category: str = "Pipe Fitting") -> dict:
    return {
        "id": f"imp_x:{source_id}",
        "source_id": source_id,
        "speckle_type": "",
        "object_type": "Fitting",
        "name": name,
        "layer": "",
        "category": category,
        "family": "Латунный фитинг",
        "level": "Этаж 01",
        "material": "Латунь",
        "attributes_json": "{}",
        "source_path": "test.json",
    }


# ── извлечение source_id из реальной проекции ──

def test_extract_from_projection():
    elements = [_element("ELEM-1001", "Фитинг 1"), _element("ELEM-1002", "Фитинг 2")]
    text = render_projection("imp_x", "test.json", "revit", elements, relations=[])
    ids, import_id = extract_highlight([text])
    assert ids == ["ELEM-1001", "ELEM-1002"]
    assert import_id == "imp_x"


def test_extract_dedups_and_keeps_order():
    chunk_a = "## Element A\n- Source ID: G-1\n## Element B\n- Source ID: G-2\n"
    chunk_b = "## Element A\n- Source ID: G-1\n## Element C\n- Source ID: G-3\n"
    ids, _ = extract_highlight([chunk_a, chunk_b])
    assert ids == ["G-1", "G-2", "G-3"]


def test_extract_handles_globalid_form_and_blanks():
    text = "Source ID / GlobalId: 2O2Fr$t4X7Zf8NOew3FLOH\n- Source ID: -\n- Source ID:  \n"
    ids, _ = extract_highlight([text])
    assert ids == ["2O2Fr$t4X7Zf8NOew3FLOH"]


def test_extract_from_flattened_chunk():
    # Как в индексированном чанке: переводы строк схлопнуты в ` - `, source_id — токен без пробелов.
    text = (
        "## Element Element - Source ID: 40afab92-819a-4715-9c7d-ec20a89abad9-00081981 "
        "- Speckle type: - - Object type: Element - Category: Осевая линия - Level: Этаж 01"
    )
    ids, _ = extract_highlight([text])
    assert ids == ["40afab92-819a-4715-9c7d-ec20a89abad9-00081981"]


def test_extract_ignores_non_cad_chunks():
    ids, import_id = extract_highlight(["СП 4.13130 п. 8.1 — проезд пожарной техники", ""])
    assert ids == []
    assert import_id is None


# ── снимок подсветки ──

def test_set_highlight_bumps_seq_and_dedups():
    snap1 = set_highlight(["a", "a", "b"], import_id="imp_x", question="где латунные фитинги?")
    assert snap1 is not None
    assert snap1["seq"] == 1
    assert snap1["source_ids"] == ["a", "b"]
    assert snap1["import_id"] == "imp_x"

    snap2 = set_highlight(["c"])
    assert snap2["seq"] == 2
    assert get_highlight()["source_ids"] == ["c"]


def test_empty_highlight_is_ignored():
    set_highlight(["a"])
    before = get_highlight()
    assert set_highlight([]) is None
    assert set_highlight(["", "  "]) is None
    assert get_highlight() == before  # снимок не тронут пустым набором
