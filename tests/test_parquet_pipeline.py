import asyncio
from zipfile import ZipFile

import backend.parquet_writer as parquet_writer
from backend.parquet_writer import (
    TableNormalizer,
    _clean_pdf_table,
    _map_columns_simple,
    read_docx_tables,
    row_to_chunk_text,
)
from backend.qdrant_adapter import QdrantLlamaIndexAdapter


def test_simple_column_mapping_covers_common_smeta_headers():
    mapping = _map_columns_simple(["№", "Наименование работ", "Ед.изм.", "Кол-во", "Цена", "Сумма"])

    assert mapping["№"] == "pos"
    assert mapping["Наименование работ"] == "name"
    assert mapping["Ед.изм."] == "unit"
    assert mapping["Кол-во"] == "qty"
    assert mapping["Цена"] == "price"
    assert mapping["Сумма"] == "amount"


def test_row_to_chunk_text_falls_back_to_compact_raw_row():
    text = row_to_chunk_text({
        "doc_type": "TABLE",
        "doc_title": "custom / CSV",
        "raw_row": '{"Колонка А": "Значение", "Колонка Б": 42}',
    })

    assert "Документ:" in text
    assert "Колонка А: Значение" in text
    assert "Колонка Б: 42" in text


def test_table_normalizer_writes_parquet_and_row_chunks(tmp_path):
    csv_path = tmp_path / "smeta.csv"
    csv_path.write_text(
        "№,Наименование работ,Ед.изм.,Кол-во,Цена,Сумма\n"
        "1,Монтаж кабеля,м,12,100,1200\n",
        encoding="utf-8",
    )

    result = asyncio.run(
        TableNormalizer(parquet_dir=str(tmp_path / "parquet"), use_llm=False).process(
            str(csv_path),
            dataset_id="ds-1",
        )
    )

    assert result["rows"] == 1
    assert result["chunks"][0]["metadata"]["type"] == "table_row"
    assert result["chunks"][0]["metadata"]["dataset_id"] == "ds-1"
    assert "Монтаж кабеля" in result["chunks"][0]["text"]
    assert "Количество: 12.0 м" in result["chunks"][0]["text"]
    assert (tmp_path / "parquet" / "smeta.parquet").exists()


def test_qdrant_adapter_builds_table_nodes_with_parquet_payload(tmp_path):
    data_dir = tmp_path / "dataset"
    data_dir.mkdir()
    csv_path = data_dir / "spec.csv"
    csv_path.write_text(
        "Позиция,Наименование,Кол-во,Ед.изм.\n"
        "1,Щит распределительный,2,шт\n",
        encoding="utf-8",
    )

    adapter = QdrantLlamaIndexAdapter.__new__(QdrantLlamaIndexAdapter)
    nodes = adapter._sync_table_nodes(csv_path, data_dir, "ds-1")

    assert len(nodes) == 1
    assert "Щит распределительный" in nodes[0]["text"]
    assert nodes[0]["payload"]["type"] == "table_row"
    assert nodes[0]["payload"]["parquet_path"] == "_parquet/spec.parquet"
    assert nodes[0]["payload"]["source_file"] == "spec.csv"


def test_pdf_table_cleanup_flattens_headers_and_drops_empty_columns():
    headers, rows = _clean_pdf_table([
        ["", "Работы", "Стоимость", ""],
        ["№", "Наименование", "Сумма", ""],
        ["1", "Монтаж кабеля", "1200", ""],
    ])

    assert headers == ["№", "Работы Наименование", "Стоимость Сумма"]
    assert rows == [{"№": "1", "Работы Наименование": "Монтаж кабеля", "Стоимость Сумма": "1200"}]


def test_pdf_table_normalizer_uses_pdf_extractor_metadata(tmp_path, monkeypatch):
    pdf_path = tmp_path / "tables.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 placeholder")

    monkeypatch.setattr(parquet_writer, "read_pdf_tables", lambda _: {
        "sheets": [{
            "sheet_name": "page_2_table_1",
            "headers": ["Позиция", "Наименование", "Кол-во", "Ед.изм."],
            "rows": [{"Позиция": "1", "Наименование": "Щит", "Кол-во": "2", "Ед.изм.": "шт"}],
            "header_row": 1,
            "source_page": 2,
            "table_index": 1,
            "extractor": "pymupdf",
        }],
        "needs_ocr": False,
        "scanned_pages": [],
    })

    result = asyncio.run(
        TableNormalizer(parquet_dir=str(tmp_path / "parquet"), use_llm=False).process(
            str(pdf_path),
            dataset_id="ds-1",
        )
    )

    assert result["rows"] == 1
    assert result["chunks"][0]["metadata"]["source_page"] == 2
    assert result["chunks"][0]["metadata"]["table_index"] == 1
    assert result["chunks"][0]["metadata"]["extractor"] == "pymupdf"
    assert (tmp_path / "parquet" / "tables.parquet").exists()


def test_pdf_table_normalizer_reports_needs_ocr(tmp_path, monkeypatch):
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 placeholder")
    monkeypatch.setattr(parquet_writer, "read_pdf_tables", lambda _: {
        "sheets": [],
        "needs_ocr": True,
        "scanned_pages": [1, 2],
    })

    result = asyncio.run(
        TableNormalizer(parquet_dir=str(tmp_path / "parquet"), use_llm=False).process(
            str(pdf_path),
            dataset_id="ds-1",
        )
    )

    assert result["chunks"] == []
    assert result["needs_ocr"] is True
    assert result["scanned_pages"] == [1, 2]


def test_docx_table_reader_extracts_row_tables(tmp_path):
    docx_path = tmp_path / "sp_tables.docx"
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Позиция</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Наименование</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Кол-во</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>1</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Клапан противопожарный</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>2</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>
"""
    with ZipFile(docx_path, "w") as archive:
        archive.writestr("word/document.xml", xml)

    result = read_docx_tables(str(docx_path))

    assert result["extractor"] == "docx_xml"
    assert result["sheets"][0]["headers"] == ["Позиция", "Наименование", "Кол-во"]
    assert result["sheets"][0]["rows"][0]["Наименование"] == "Клапан противопожарный"


def test_qdrant_adapter_builds_needs_ocr_marker(tmp_path, monkeypatch):
    data_dir = tmp_path / "dataset"
    data_dir.mkdir()
    pdf_path = data_dir / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 placeholder")
    monkeypatch.setattr(parquet_writer, "read_pdf_tables", lambda _: {
        "sheets": [],
        "needs_ocr": True,
        "scanned_pages": [3],
    })

    adapter = QdrantLlamaIndexAdapter.__new__(QdrantLlamaIndexAdapter)
    nodes = adapter._sync_table_nodes(pdf_path, data_dir, "ds-1")

    assert len(nodes) == 1
    assert nodes[0]["payload"]["type"] == "pdf_needs_ocr"
    assert nodes[0]["payload"]["needs_ocr"] is True
    assert nodes[0]["payload"]["scanned_pages"] == [3]
