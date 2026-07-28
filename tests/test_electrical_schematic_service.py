import pytest

from proxy.services.electrical_schematic_service import (
    extract_electrical_schematic_manifest,
    load_electrical_terms,
    normalize_load_table_matrix,
)

fitz = pytest.importorskip("fitz")

MM_TO_PT = 72 / 25.4


def _font_path():
    from pathlib import Path

    for path in (
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
    ):
        if path.exists():
            return str(path)
    return None


def test_normalize_load_table_matrix_reads_common_electrical_fields():
    table = [
        ["N", "Щит", "Потребитель", "Линия", "Руст, кВт", "Рр, кВт", "Iрасч, А", "cosφ", "Кабель", "L, м", "Аппарат защиты"],
        ["1", "ВРУ-1", "ЩО-1", "Л1", "24,5", "18.2", "32", "0,92", "ВВГнг-LS 5х16", "35,5", "QF1 63А"],
        ["2", "ВРУ-1", "ЩР-2", "Л2", "10", "7,4", "14.5", "0,9", "ВВГнг-LS 5х6", "18", "QF2 25А"],
    ]

    result = normalize_load_table_matrix(table, source_ref="loads.pdf#page=3#table=1")

    assert result["schema"] == "electrical_load_table_v1"
    assert result["row_count"] == 2
    first = result["rows"][0]
    assert first["panel"] == "ВРУ-1"
    assert first["consumer"] == "ЩО-1"
    assert first["line_id"] == "Л1"
    assert first["p_installed_kw"] == 24.5
    assert first["p_calc_kw"] == 18.2
    assert first["i_calc_a"] == 32.0
    assert first["cos_phi"] == 0.92
    assert first["cable"] == "ВВГнг-LS 5х16"
    assert first["cable_length_m"] == 35.5
    assert first["protection"] == "QF1 63А"
    assert first["source_ref"].endswith("#row=2")


def test_electrical_terms_dictionary_declares_rust_as_installed_power():
    terms = load_electrical_terms()
    installed = terms["load_fields"]["p_installed_kw"]
    assert "установленная мощность" in installed["label"]
    assert "Руст" in installed["aliases"]
    assert installed["unit"] == "кВт"


def test_load_table_dictionary_keeps_ru_panel_distinct_from_rust_power():
    table = [
        ["РУ", "Потребитель", "Ру, кВт", "Рр, кВт"],
        ["ВРУ-1", "ЩО-1", "12", "9,5"],
    ]

    result = normalize_load_table_matrix(table, source_ref="loads.pdf#page=1#table=1")

    assert result["mapping"]["panel"] == 0
    assert result["mapping"]["p_installed_kw"] == 2
    assert result["rows"][0]["panel"] == "ВРУ-1"
    assert result["rows"][0]["p_installed_kw"] == 12.0
    assert result["rows"][0]["p_calc_kw"] == 9.5


def test_normalize_load_table_matrix_reads_common_11_column_load_form():
    table = [
        [
            "Наименование ЭП",
            "Количество ЭП, шт. n",
            "Номинальная (установленная)",
            "",
            "Коэффициент использования Ки",
            "cos φ",
            "tg φ",
            "",
            "",
            "",
            "",
        ],
        ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"],
        ["нЩО1-1. Освещение", "4", "0,033", "0,13", "1,00", "0,95", "0,33", "0,13", "0,04", "0,14", "0,63"],
    ]

    result = normalize_load_table_matrix(table, source_ref="loads.pdf#page=2#table=1")

    assert result["row_count"] == 1
    row = result["rows"][0]
    assert row["consumer"] == "нЩО1-1. Освещение"
    assert row["p_installed_kw"] == 0.13
    assert row["p_calc_kw"] == 0.13
    assert row["q_calc_kvar"] == 0.04
    assert row["s_calc_kva"] == 0.14
    assert row["i_calc_a"] == 0.63
    assert row["ku"] == 1.0
    assert row["cos_phi"] == 0.95


def test_extract_electrical_schematic_manifest_reads_text_nodes_and_vectors(tmp_path):
    if not _font_path():
        pytest.skip("Cyrillic TrueType font is required for electrical PDF fixture")
    pdf = tmp_path / "ЭОМ-однолинейная.pdf"
    doc = fitz.open()
    page = doc.new_page(width=420 * MM_TO_PT, height=297 * MM_TO_PT)
    page.insert_font(fontname="cyr", fontfile=_font_path())
    page.insert_text((60, 50), "Однолинейная принципиальная схема электроснабжения", fontsize=12, fontname="cyr")
    page.insert_text((80, 130), "ВРУ-1", fontsize=10, fontname="cyr")
    page.insert_text((210, 130), "QF1 63А", fontsize=10, fontname="cyr")
    page.insert_text((340, 130), "ВВГнг-LS 5х16", fontsize=10, fontname="cyr")
    page.insert_text((520, 130), "ЩО-1", fontsize=10, fontname="cyr")
    page.insert_text((80, 170), "ВРУ-1 - ЩО-1 Л1 QF1 63А ВВГнг-LS 5х16 L=35 м Pр=18,2 кВт Iр=32 А", fontsize=9, fontname="cyr")
    page.draw_line((100, 210), (700, 210), width=1)
    page.draw_line((100, 180), (100, 250), width=1)
    page.draw_line((700, 180), (700, 250), width=1)
    doc.save(str(pdf))
    doc.close()

    manifest = extract_electrical_schematic_manifest(pdf)

    assert manifest["schema"] == "electrical_schematic_manifest_v1"
    assert manifest["summary"]["schematic_pages"] == 1
    page_payload = manifest["pages"][0]
    assert page_payload["sheet_kind"] == "electrical_single_line"
    values = {node["value"] for node in page_payload["text_nodes"]}
    assert "ВРУ-1" in values
    assert "ЩО-1" in values
    assert "QF1 63А" in values
    assert "ВВГнг-LS 5х16" in values
    assert page_payload["line_segments_total"] >= 3
    circuit = page_payload["candidate_circuits"][0]
    assert circuit["from_node"] == "ВРУ-1"
    assert circuit["to_node"] == "ЩО-1"
    assert circuit["cable"] == "ВВГнг-LS 5х16"
    assert circuit["cable_length_m"] == 35.0
    assert circuit["protection"] == "QF1 63А"
    assert circuit["load_kw"] == 18.2
    assert circuit["current_a"] == 32.0


def test_extract_electrical_schematic_manifest_blank_pdf_stays_unknown(tmp_path):
    pdf = tmp_path / "blank.pdf"
    doc = fitz.open()
    doc.new_page(width=210 * MM_TO_PT, height=297 * MM_TO_PT)
    doc.save(str(pdf))
    doc.close()

    manifest = extract_electrical_schematic_manifest(pdf)

    assert manifest["summary"]["schematic_pages"] == 0
    assert manifest["summary"]["load_rows"] == 0
    assert manifest["pages"][0]["sheet_kind"] == "unknown"
    assert manifest["pages"][0]["text_nodes"] == []


def test_extract_electrical_schematic_manifest_does_not_read_common_words_as_panels(tmp_path):
    if not _font_path():
        pytest.skip("Cyrillic TrueType font is required for electrical PDF fixture")
    pdf = tmp_path / "со.pdf"
    doc = fitz.open()
    page = doc.new_page(width=210 * MM_TO_PT, height=297 * MM_TO_PT)
    page.insert_font(fontname="cyr", fontfile=_font_path())
    page.insert_text((60, 80), "автоматический выключатель с ручки управления", fontsize=10, fontname="cyr")
    doc.save(str(pdf))
    doc.close()

    manifest = extract_electrical_schematic_manifest(pdf)

    values = {node["value"] for node in manifest["pages"][0]["text_nodes"]}
    assert "ручки" not in values
    assert not any(node["kind"] == "panel" for node in manifest["pages"][0]["text_nodes"])
