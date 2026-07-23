import pytest

from proxy.services.pd_rd_manifest_service import extract_pd_rd_manifest, repair_pd_rd_text

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


def _insert_lines(page, lines, *, x=55, y=55, step=15):
    page.insert_font(fontname="cyr", fontfile=_font_path())
    for line in lines:
        page.insert_text((x, y), line, fontsize=8, fontname="cyr")
        y += step


def test_pd_rd_manifest_extracts_volume_contents_project_composition_and_pz_toc(tmp_path):
    if not _font_path():
        pytest.skip("Cyrillic TrueType font is required for text-layer fixture")
    pdf = tmp_path / "395.01-B481.120100.2.4-ИОС.ЭС.pdf"
    doc = fitz.open()

    page = doc.new_page(width=210 * MM_TO_PT, height=297 * MM_TO_PT)
    _insert_lines(
        page,
        [
            "395.01/B481.120100.2.4-ИОС.ЭС.С",
            "Имя файла: 395_01_B481_120100_2_4_IOS_ES_S_00.doc",
            "Формат А4",
            "Обозначение",
            "Наименование",
            "Примечание",
            "395.01/B481.120100.2.4-ИОС.ЭС.ПЗ",
            "Пояснительная записка",
            "40 листов",
            "Графическая часть",
            "395.01/B481.120100.1.4-ИОС.ЭС",
            "Электрооборудование и электроосвещение. Часть 1.",
            "31 лист",
            "ГРЩ1. Схема электрическая принципиальная",
            "Лист 1 (5 листов)",
        ],
    )

    page = doc.new_page(width=210 * MM_TO_PT, height=297 * MM_TO_PT)
    _insert_lines(
        page,
        [
            "395.01/B481.120100.2.4-ИОС.ЭС.С",
            "Лист",
            "2",
            "Имя файла: 395_01_B481_120100_2_4_IOS_ES_S_00.doc",
            "Формат А4",
            "ЩО1.1.1. Схема электрическая принципиальная",
            "Лист 24 (7 листов)",
            "Прилагаемые документы",
            "Приложение 1",
            "Технические условия на технологическое присоединение",
            "6 листов",
            "Общее количество листов:",
            "242 листа",
        ],
    )

    page = doc.new_page(width=210 * MM_TO_PT, height=297 * MM_TO_PT)
    _insert_lines(
        page,
        [
            "395.01/B481.120000.2.4-СП",
            "СОСТАВ ПРОЕКТНОЙ ДОКУМЕНТАЦИИ",
            "№",
            "тома",
            "Обозначение",
            "Наименование раздела, подраздела",
            "Примечание",
            "5.1.1",
            "395.01/B481.120100.2.4-ИОС.ЭС",
            "Система электроснабжения. Здание инновационного центра",
            "5.5.5",
            "395.01/B481.120100.2.4-ИОС.СС5",
            "Автоматизация комплексная. Здание инновационного центра",
        ],
    )

    page = doc.new_page(width=210 * MM_TO_PT, height=297 * MM_TO_PT)
    _insert_lines(
        page,
        [
            "395.01/B481.120100.2.4-ИОС.ЭС.ПЗ",
            "ПОЯСНИТЕЛЬНАЯ ЗАПИСКА",
            "Оглавление",
            "5 ОСНОВНЫЕ ТЕХНИЧЕСКИЕ РЕШЕНИЯ ........ 4",
            "5.1",
            "Характеристика источников электроснабжения ........ 4",
            "6.4 Расчет токов короткого замыкания ........ 30",
        ],
    )

    doc.save(str(pdf))
    doc.close()

    manifest = extract_pd_rd_manifest(pdf, include_sheet_pages=True)

    assert manifest["schema"] == "pd_rd_manifest_v1"
    volume = manifest["volume_contents_register"]
    assert volume["declared_total_sheets"] == 242
    assert volume["row_count"] >= 5
    assert any(row["name"] == "Пояснительная записка" and row["sheet_count"] == "40" for row in volume["rows"])
    assert any(row["name"] == "ЩО1.1.1. Схема электрическая принципиальная" and row["sheet_no"] == "24" for row in volume["rows"])
    assert any(row["section"] == "Прилагаемые документы" and row["sheet_count"] == "6" for row in volume["rows"])

    project = manifest["project_composition_register"]
    assert project["row_count"] == 2
    assert project["rows"][0]["volume_no"] == "5.1.1"
    assert project["rows"][0]["designation_norm"] == "395.01/B481.120100.2.4-ИОС.ЭС"
    assert project["rows"][1]["volume_no"] == "5.5.5"

    toc = manifest["pz_toc"]
    assert [row["section_no"] for row in toc["rows"]] == ["5", "5.1", "6.4"]
    assert toc["rows"][1]["title"] == "Характеристика источников электроснабжения"
    assert toc["rows"][2]["target_sheet"] == 30


def test_repair_pd_rd_text_recovers_pdf_cyrillic_glyph_mojibake():
    assert repair_pd_rd_text("395.01/B481.120000.2.4-ɋɉ") == "395.01/B481.120000.2.4-СП"
    assert repair_pd_rd_text("ɋɢɫɬɟɦɚ ɷɥɟɤɬɪɨɫɧɚɛɠɟɧɢɹ") == "Система электроснабжения"
