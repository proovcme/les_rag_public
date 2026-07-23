import pytest

from proxy.services.drawing_manifest_service import (
    build_drawing_manifest_registry,
    extract_pdf_drawing_manifest,
    normalize_cipher,
    repair_pdf_text_mojibake,
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


def _make_pdf_with_stamp(path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=297 * MM_TO_PT, height=210 * MM_TO_PT)
    page.insert_text((40, 60), "Cipher: WRONG-TOP-001", fontsize=10)
    page.insert_text((40, 92), "General notes and textual part of the sheet", fontsize=10)
    stamp_rect = fitz.Rect(410, 370, 835, 580)
    page.insert_textbox(
        stamp_rect,
        "\n".join(
            [
                "Object: Innovation Center",
                "Address: 1 Test street",
                "Volume: Tom 5.2",
                "Cipher: IC-PD-IOS5.2-001",
                "Stage: P",
                "Sheet: 1",
                "Sheets: 12",
            ]
        ),
        fontsize=9,
    )
    doc.save(str(path))
    doc.close()


def test_extract_pdf_drawing_manifest_reads_bottom_right_stamp_fields(tmp_path):
    pdf = tmp_path / "IC-PD-IOS5.2-001.pdf"
    _make_pdf_with_stamp(pdf)

    manifest = extract_pdf_drawing_manifest(pdf)

    assert manifest["schema"] == "drawing_manifest_v1"
    assert manifest["page_count"] == 1
    page = manifest["pages"][0]
    assert page["sheet_format"] == "А4"
    assert page["fields"]["object_name"] == "Innovation Center"
    assert page["fields"]["object_address"] == "1 Test street"
    assert page["fields"]["volume"] == "Tom 5.2"
    assert page["fields"]["cipher"] == "IC-PD-IOS5.2-001"
    assert page["fields"]["cipher_norm"] == "IC-PD-IOS5.2-001"
    assert page["fields"]["cipher_source"]["source"] == "stamp_zone"
    assert "WRONG-TOP-001" in [candidate["value"] for candidate in page["candidates"]]
    assert manifest["groups"]["by_cipher"] == {"IC-PD-IOS5.2-001": [1]}
    assert any(block["zone"] == "stamp" for block in page["text_blocks"])
    assert any(block["zone"] == "sheet_text" for block in page["text_blocks"])


def test_extract_pdf_drawing_manifest_keeps_scan_unknown_without_ocr(tmp_path):
    pdf = tmp_path / "scan.pdf"
    doc = fitz.open()
    doc.new_page(width=210 * MM_TO_PT, height=297 * MM_TO_PT)
    doc.save(str(pdf))
    doc.close()

    manifest = extract_pdf_drawing_manifest(pdf)

    page = manifest["pages"][0]
    assert page["sheet_format"] == "А4"
    assert page["fields"] == {}
    assert page["text_blocks"] == []
    assert manifest["groups"]["by_cipher"] == {}


def test_extract_pdf_drawing_manifest_reads_structural_stamp_without_labels(tmp_path):
    source_dir = tmp_path / "5. ИОС" / "5.1. ЭС и ЭО"
    source_dir.mkdir(parents=True)
    pdf = source_dir / "395.01-B481.120100.6.4-ИОС.ЭС-СО.pdf"
    doc = fitz.open()
    page = doc.new_page(width=420 * MM_TO_PT, height=297 * MM_TO_PT)
    stamp_rect = fitz.Rect(560, 520, 1180, 830)
    page.insert_textbox(
        stamp_rect,
        "\n".join(
            [
                "Rev Qty Sheet Doc Sign Date",
                        "IC-PD-EOM-SO-001",
                "00",
                "Building A",
                "Power supply system",
                "Equipment specification",
                "Stage",
                "P",
                "Sheet",
                "1",
                "Sheets",
                "2",
            ]
        ),
        fontsize=9,
    )
    doc.save(str(pdf))
    doc.close()

    manifest = extract_pdf_drawing_manifest(pdf)

    fields = manifest["pages"][0]["fields"]
    assert fields["object_name"] == "Building A"
    assert fields["object_name_source"]["source"] == "stamp_structure"
    assert fields["sheet_title"] == "Power supply system Equipment specification"
    assert fields["volume"] == "5. ИОС"
    assert fields["volume_source"]["source"] == "source_path"


def test_build_drawing_manifest_registry_groups_by_cipher_and_reports_gaps(tmp_path):
    one = tmp_path / "5. ИОС" / "sheet-1.pdf"
    two = tmp_path / "5. ИОС" / "sheet-2.pdf"
    blank = tmp_path / "blank.pdf"
    one.parent.mkdir(parents=True)
    for path, sheet in ((one, "1"), (two, "2")):
        doc = fitz.open()
        page = doc.new_page(width=420 * MM_TO_PT, height=297 * MM_TO_PT)
        page.insert_textbox(
            fitz.Rect(560, 520, 1180, 830),
            "\n".join(
                [
                    "Rev Qty Sheet Doc Sign Date",
                    "IC-PD-EOM-SO-001",
                    "Building A",
                    f"Sheet title {sheet}",
                    "Stage",
                    "P",
                ]
            ),
            fontsize=9,
        )
        doc.save(str(path))
        doc.close()
    doc = fitz.open()
    doc.new_page(width=210 * MM_TO_PT, height=297 * MM_TO_PT)
    doc.save(str(blank))
    doc.close()

    registry = build_drawing_manifest_registry([one, two, blank], dataset_id="ds1", max_pages_per_pdf=1)

    assert registry["schema"] == "drawing_manifest_registry_v1"
    assert registry["files_read"] == 3
    assert registry["ciphers_total"] == 1
    group = registry["groups"]["by_cipher"]["IC-PD-EOM-SO-001"]
    assert len(group) == 2
    assert registry["issues"]["no_cipher"] == [blank.as_posix()]
    assert blank.as_posix() in registry["issues"]["no_stamp"]


def test_text_part_followup_stamp_extracts_sheet_no_and_cipher_semantics(tmp_path):
    pdf = tmp_path / "395.01-B481.120100.2.4-ИОС.ЭС.pdf"
    doc = fitz.open()
    page = doc.new_page(width=210 * MM_TO_PT, height=297 * MM_TO_PT)
    if not _font_path():
        pytest.skip("Cyrillic TrueType font is required for text-layer stamp fixture")
    page.insert_font(fontname="cyr", fontfile=_font_path())
    page.insert_textbox(
        fitz.Rect(300, 540, 590, 830),
        "\n".join(
            [
                "395.01/B481.120100.2.4-ИОС.ЭС.ПЗ",
                "Лист",
                "2",
                "Изм. Кол.уч Лист №док",
                "Подп.",
                "Дата",
                "Имя файла: 395_01_B481_120100_2_4_IOS_ES_PZ_00.doc",
                "Формат А4",
            ]
        ),
        fontsize=9,
        fontname="cyr",
    )
    page.insert_text((70, 500), "4 ПЕРЕЧЕНЬ ССЫЛОЧНЫХ И НОРМАТИВНЫХ ДОКУМЕНТОВ", fontsize=11, fontname="cyr")
    doc.save(str(pdf))
    doc.close()

    fields = extract_pdf_drawing_manifest(pdf)["pages"][0]["fields"]

    assert fields["cipher_norm"] == "395.01/B481.120100.2.4-ИОС.ЭС.ПЗ"
    assert fields["sheet_no"] == "2"
    assert fields["discipline_code"] == "ИОС"
    assert fields["subdiscipline_code"] == "ЭС"
    assert fields["document_kind_code"] == "ПЗ"
    assert fields["document_kind_title"] == "пояснительная записка"
    assert fields["source_file_name"] == "395_01_B481_120100_2_4_IOS_ES_PZ_00.doc"
    assert fields["declared_format"] == "А4"
    assert "object_name" not in fields
    assert "sheet_title" not in fields


def test_graphical_stamp_extracts_compact_cipher_sheet_fields_and_titles(tmp_path):
    pdf = tmp_path / "395.01-B481.120100.1.4-ИОС.ЭС.pdf"
    doc = fitz.open()
    page = doc.new_page(width=420 * MM_TO_PT, height=297 * MM_TO_PT)
    if not _font_path():
        pytest.skip("Cyrillic TrueType font is required for text-layer stamp fixture")
    page.insert_font(fontname="cyr", fontfile=_font_path())
    page.insert_textbox(
        fitz.Rect(565, 500, 1180, 835),
        "\n".join(
            [
                "Технические требования по ЩО 1.1:",
                "1. Щит напольного исполнения;",
                "Здание инновационного центра",
                "Система электроснабжения. Здание инновационного центра",
                "ЩО 1.1.1. Схема электрическая принципиальная",
                "395.01/B481.120100.1.4- ИОС .ЭС",
                "00",
                "Стадия",
                "Лист",
                "Листов",
                "П",
                "24.1",
                "7",
                "Имя файла: 395_01_B481_120100_1_4_IOS_ES_24_00.dwg",
                "Формат А3х3",
            ]
        ),
        fontsize=8,
        fontname="cyr",
    )
    doc.save(str(pdf))
    doc.close()

    fields = extract_pdf_drawing_manifest(pdf)["pages"][0]["fields"]

    assert fields["cipher_norm"] == "395.01/B481.120100.1.4-ИОС.ЭС"
    assert fields["discipline_code"] == "ИОС"
    assert fields["subdiscipline_code"] == "ЭС"
    assert "document_kind_code" not in fields
    assert fields["stage"] == "П"
    assert fields["sheet_no"] == "24.1"
    assert fields["sheet_count"] == "7"
    assert fields["object_name"] == "Здание инновационного центра"
    assert fields["sheet_title"] == "ЩО 1.1.1. Схема электрическая принципиальная"
    assert fields["source_file_name"] == "395_01_B481_120100_1_4_IOS_ES_24_00.dwg"
    assert fields["declared_format"] == "А3х3"


def test_graphical_continuation_stamp_keeps_sheet_number_out_of_object_name(tmp_path):
    pdf = tmp_path / "395.01-B481.120100.1.4-ИОС.ЭС.pdf"
    doc = fitz.open()
    page = doc.new_page(width=420 * MM_TO_PT, height=297 * MM_TO_PT)
    if not _font_path():
        pytest.skip("Cyrillic TrueType font is required for text-layer stamp fixture")
    page.insert_font(fontname="cyr", fontfile=_font_path())
    page.insert_textbox(
        fitz.Rect(565, 510, 1180, 835),
        "\n".join(
            [
                "Примечания:",
                "1. Электрические цепи выполнить проводом ПуГВ 1x0,75 мм.кв;",
                "395.01/B481.120100.1.4- ИОС .ЭС",
                "Лист",
                "24.2",
                "Имя файла: 395_01_B481_120100_1_4_IOS_ES_24_00.dwg",
                "Формат А3",
            ]
        ),
        fontsize=8,
        fontname="cyr",
    )
    doc.save(str(pdf))
    doc.close()

    page = extract_pdf_drawing_manifest(pdf)["pages"][0]
    fields = page["fields"]

    assert page["stamp_present"] is True
    assert fields["cipher_norm"] == "395.01/B481.120100.1.4-ИОС.ЭС"
    assert fields["sheet_no"] == "24.2"
    assert fields["source_file_name"] == "395_01_B481_120100_1_4_IOS_ES_24_00.dwg"
    assert fields["declared_format"] == "А3"
    assert "object_name" not in fields
    assert "sheet_title" not in fields


def test_volume_contents_page_builds_register_rows(tmp_path):
    pdf = tmp_path / "395.01-B481.120100.2.4-ИОС.ЭС.pdf"
    doc = fitz.open()
    page = doc.new_page(width=210 * MM_TO_PT, height=297 * MM_TO_PT)
    if not _font_path():
        pytest.skip("Cyrillic TrueType font is required for text-layer stamp fixture")
    page.insert_font(fontname="cyr", fontfile=_font_path())
    rows = [
        ("Обозначение", "Наименование", "Примечание"),
        ("395.01/B481.120100.2.4-ИОС.ЭС.С", "Содержание тома", "4 листа"),
        ("395.01/B481.120100.2.4-ИОС.ЭС.ПЗ", "Пояснительная записка", "40 листов"),
        ("Графическая часть", "", ""),
        ("395.01/B481.120100.1.4- ИОС .ЭС", "Электрооборудование и электроосвещение. Часть 1.", "31 лист"),
        ("", "ГРЩ1. Схема электрическая принципиальная", "Лист 1 (5 листов)"),
        ("", "ЩЭ1.1.1. Схема электрическая принципиальная", "Лист 3"),
    ]
    y = 55
    for designation, name, note in rows:
        page.insert_text((65, y), designation, fontsize=7, fontname="cyr")
        page.insert_text((235, y), name, fontsize=7, fontname="cyr")
        page.insert_text((470, y), note, fontsize=7, fontname="cyr")
        y += 22
    page.insert_text((295, 780), "Содержание тома", fontsize=9, fontname="cyr")
    doc.save(str(pdf))
    doc.close()

    manifest = extract_pdf_drawing_manifest(pdf)
    rows = manifest["volume_contents"]

    assert len(rows) == 5
    assert rows[0]["designation_norm"] == "395.01/B481.120100.2.4-ИОС.ЭС.С"
    assert rows[0]["name"] == "Содержание тома"
    assert rows[0]["sheet_count"] == "4"
    assert rows[2]["designation_norm"] == "395.01/B481.120100.1.4-ИОС.ЭС"
    assert rows[2]["section"] == "Графическая часть"
    assert rows[2]["sheet_count"] == "31"
    assert rows[3]["name"] == "ГРЩ1. Схема электрическая принципиальная"
    assert rows[3]["sheet_no"] == "1"
    assert rows[3]["sheet_count"] == "5"
    assert rows[4]["sheet_no"] == "3"
    assert manifest["pages"][0]["volume_contents"] == rows


def test_normalize_cipher_preserves_grouping_key_without_over_parsing():
    assert normalize_cipher(" ic — pd – ios5.2 - 001 ") == "IC-PD-IOS5.2-001"
    assert normalize_cipher("395.01 / В481.120000.6.4-ИОС.СС4.ВОР") == "395.01/В481.120000.6.4-ИОС.СС4.ВОР"


def test_repair_pdf_text_mojibake_recovers_cp1251_cyrillic():
    assert repair_pdf_text_mojibake("Èçì. Êîë.ó÷ Ëèñò") == "Изм. Кол.уч Лист"
    assert repair_pdf_text_mojibake("Ï") == "П"
    assert repair_pdf_text_mojibake("café") == "café"
