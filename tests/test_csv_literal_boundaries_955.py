"""CSV quoting preserves source content, column identity and physical addresses."""

import csv

import pytest

from proxy.services.attachment_source_catalog_service import load_tabular_source_catalog


def _write_csv(path, rows, *, delimiter=",", encoding="utf-8", newline="\r\n", quoting=csv.QUOTE_MINIMAL):
    with path.open("w", encoding=encoding, newline="") as stream:
        writer = csv.writer(stream, delimiter=delimiter, lineterminator=newline, quoting=quoting)
        writer.writerows(rows)


@pytest.mark.parametrize("delimiter", [",", ";"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_quoted_cell_newlines_remain_literal_and_next_locator_uses_physical_start(tmp_path, delimiter, newline):
    source = tmp_path / "Слои «источник» и 'кавычка'.csv"
    multiline = f"Первый слой{newline}Второй слой"
    _write_csv(source, [["Наименование", "Ед. изм.", "Количество"],
                       [multiline, "м2", "7.25"], [], ["Следующая операция", "шт", "0"]],
               delimiter=delimiter, newline=newline)
    before = source.read_bytes()
    catalog = load_tabular_source_catalog(source)
    first = catalog.lookup("CSV!R2")
    assert first is not None
    assert first.cells[0].raw_value == multiline
    assert first.values[0] == "Первый слой Второй слой"
    assert catalog.lookup("CSV!R4") is None  # physical blank line after the quoted record
    last = catalog.lookup("CSV!R5")
    assert last is not None and last.values[0] == "Следующая операция"
    assert first.header_quantity == 7.25 and last.header_quantity == 0
    assert source.read_bytes() == before
    again = load_tabular_source_catalog(source)
    assert [(row.locator, row.row_id) for row in catalog.rows] == [
        (row.locator, row.row_id) for row in again.rows]


@pytest.mark.parametrize("delimiter,quoted_header", [
    (";", "Наименование, тип, марка, описание"),
    (",", "Наименование; тип; марка; описание"),
])
def test_quoted_header_delimiters_do_not_replace_real_csv_columns(tmp_path, delimiter, quoted_header):
    source = tmp_path / "Физические колонки.csv"
    _write_csv(source, [[quoted_header, "Ед. изм.", "Количество"], ["Операция", "м", "12"]],
               delimiter=delimiter, quoting=csv.QUOTE_ALL)
    catalog = load_tabular_source_catalog(source)
    assert catalog.lookup("CSV!R1").values == (quoted_header, "Ед. изм.", "Количество")
    row = catalog.lookup("CSV!R2")
    assert row.values == ("Операция", "м", "12")
    assert row.quantity_column_known is True and row.header_quantity == 12


def test_blank_lines_and_multiline_quoted_header_keep_physical_start_coordinates(tmp_path):
    source = tmp_path / "Заголовок с переносом.csv"
    text = '\r\n"Наименование\r\nработы";Ед. изм.;Количество\r\n"Позиция ""А""";шт;2\r\n'
    source.write_bytes(text.encode("utf-8-sig"))
    catalog = load_tabular_source_catalog(source)
    assert [row.locator for row in catalog.rows] == ["CSV!R2", "CSV!R4"]
    assert catalog.lookup("CSV!R2").cells[0].raw_value == "Наименование\r\nработы"
    row = catalog.lookup("CSV!R4")
    assert row.values == ('Позиция "А"', "шт", "2")
    assert row.header_quantity == 2


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp1251"])
def test_csv_literal_spaces_empty_columns_and_zero_are_not_rewritten(tmp_path, encoding):
    source = tmp_path / "Пустые значения.csv"
    _write_csv(source, [["Наименование", "Тип", "Ед. изм.", "Количество"],
                       ["  Название  ", "", "шт", "0"], ["Неопределённая позиция", "", "м2", ""]],
               delimiter=";", encoding=encoding)
    catalog = load_tabular_source_catalog(source)
    first, last = catalog.lookup("CSV!R2"), catalog.lookup("CSV!R3")
    assert first.cells[0].raw_value == "  Название  "
    assert first.values == ("Название", "", "шт", "0")
    assert first.header_quantity == 0
    assert last.quantity_column_known is True and last.header_quantity is None


def test_converter_uses_real_separator_and_keeps_multiline_words(tmp_path, monkeypatch):
    from backend import converter

    source = tmp_path / "Источник для преобразования.csv"
    _write_csv(source, [["Наименование, тип, марка", "Ед. изм.", "Количество"],
                       ["Первый слой\nВторой слой", "м2", "7.25"]], delimiter=";")
    monkeypatch.setattr(converter, "SPREADSHEET_FULL_TABLE_MAX_CELLS", 100)
    result = converter.convert_to_markdown(source, apply_char_limit=False)
    assert "Первый слой" in result and "Второй слой" in result
    assert "7.25" in result
    header = next(line for line in result.splitlines() if line.startswith("|"))
    assert "Ед. изм." in [cell.strip() for cell in header.strip("|").split("|")]
    assert "Количество" in [cell.strip() for cell in header.strip("|").split("|")]


@pytest.mark.parametrize("delimiter,header", [(";", "Наименование, тип, марка, описание"),
                                             (",", "Наименование; тип; марка; описание")])
def test_chat_preview_matches_catalog_columns_and_physical_addresses(tmp_path, delimiter, header):
    from proxy.routers.datasets import _format_tabular_attachment_context

    source = tmp_path / "Превью «слои» и 'кавычка'.csv"
    _write_csv(source, [[header, "Ед. изм.", "Количество"],
                       ["Первый слой\r\nВторой слой", "м2", "7.25"], [], ["Последняя позиция", "шт", "0"]],
               delimiter=delimiter, quoting=csv.QUOTE_ALL)
    preview, truncated = _format_tabular_attachment_context(source, source.name, max_chars=10000)
    catalog = load_tabular_source_catalog(source)
    assert truncated is False
    assert f"CSV!R1: {header} | Ед. изм. | Количество" in preview
    assert "CSV!R2: Первый слой Второй слой | м2 | 7.25" in preview
    assert "CSV!R5: Последняя позиция | шт | 0" in preview
    assert "CSV!R3:" not in preview and "CSV!R4:" not in preview
    assert [row.locator for row in catalog.rows] == ["CSV!R1", "CSV!R2", "CSV!R5"]
