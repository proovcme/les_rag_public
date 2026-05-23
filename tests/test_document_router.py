from pathlib import Path

from backend.document_router import DocumentProbe, classify_document, probe_document, route_document
from backend.qdrant_adapter import QdrantLlamaIndexAdapter


def test_route_csv_smeta_to_parquet(tmp_path):
    path = tmp_path / "local_smeta.csv"
    path.write_text(
        "№,Наименование работ,Ед.изм.,Кол-во,Цена,Сумма\n"
        "1,Монтаж кабеля,м,12,100,1200\n",
        encoding="utf-8",
    )

    probe = probe_document(path)
    route = classify_document(probe)

    assert probe.has_tables is True
    assert route.doc_type == "SMETA"
    assert route.domain == "TABLE_SMETA"
    assert route.dataset_name == "TABLE_SMETA_Index"
    assert route.content_type == "table"
    assert route.complexity == "structured"
    assert route.pipeline == "parquet"


def test_route_pdf_with_table_signals_to_markdown_pdf_tables():
    probe = DocumentProbe(
        path=Path("Спецификация.pdf"),
        suffix=".pdf",
        size_bytes=10_000,
        page_count=12,
        text_sample="Позиция Наименование Кол-во Ед.изм.",
        has_text_layer=True,
        has_tables=True,
        table_count_hint=1,
    )

    route = classify_document(probe)

    assert route.doc_type == "SPEC"
    assert route.domain == "TABLE_SPEC"
    assert route.content_type == "mixed"
    assert route.complexity == "structured"
    assert route.pipeline == "markdown_pdf_tables"


def test_route_scan_pdf_to_needs_ocr():
    probe = DocumentProbe(
        path=Path("scan.pdf"),
        suffix=".pdf",
        size_bytes=10_000,
        page_count=3,
        has_text_layer=False,
        needs_ocr=True,
    )

    route = classify_document(probe)

    assert route.content_type == "scan"
    assert route.complexity == "needs_ocr"
    assert route.pipeline == "markdown_needs_ocr"
    assert route.metadata["needs_ocr"] is True


def test_route_metadata_is_added_to_table_payload(tmp_path):
    data_dir = tmp_path / "dataset"
    data_dir.mkdir()
    csv_path = data_dir / "smeta.csv"
    csv_path.write_text(
        "№,Наименование работ,Ед.изм.,Кол-во,Цена,Сумма\n"
        "1,Монтаж кабеля,м,12,100,1200\n",
        encoding="utf-8",
    )

    route = route_document(csv_path)
    adapter = QdrantLlamaIndexAdapter.__new__(QdrantLlamaIndexAdapter)
    nodes = adapter._sync_table_nodes(csv_path, data_dir, "ds-1", route)

    assert nodes[0]["payload"]["doc_type"] == "SMETA"
    assert nodes[0]["payload"]["domain"] == "TABLE_SMETA"
    assert nodes[0]["payload"]["dataset_name"] == "TABLE_SMETA_Index"
    assert nodes[0]["payload"]["content_type"] == "table"
    assert nodes[0]["payload"]["complexity"] == "structured"
    assert nodes[0]["payload"]["pipeline"] == "parquet"


def test_route_pp87_to_gkrf_domain():
    probe = DocumentProbe(
        path=Path("Постановление 87.pdf"),
        suffix=".pdf",
        size_bytes=10_000,
        page_count=20,
        text_sample="Постановление 87 о составе разделов проектной документации",
    )

    route = classify_document(probe)

    assert route.doc_type == "NORMATIVE"
    assert route.domain == "GKRF"
    assert route.dataset_name == "GKRF_Index"


def test_normative_name_wins_over_table_price_words():
    probe = DocumentProbe(
        path=Path("ГОСТ 30244-94. Материалы строительные.docx"),
        suffix=".docx",
        size_bytes=10_000,
        text_sample="Таблица. Цена деления шкалы. Сумма измерений.",
        has_tables=True,
    )

    route = classify_document(probe)

    assert route.doc_type == "NORMATIVE"
    assert route.domain == "NTD_OTHER"


def test_iec_and_fire_protection_names_route_to_specific_domains():
    electrical = classify_document(
        DocumentProbe(
            path=Path("ГОСТ IEC 61008-1-2020. Выключатели.docx"),
            suffix=".docx",
            size_bytes=10_000,
        )
    )
    fire = classify_document(
        DocumentProbe(
            path=Path("СП 433.1325800.2019. Огнезащита стальных конструкций.docx"),
            suffix=".docx",
            size_bytes=10_000,
        )
    )

    assert electrical.domain == "NTD_ELECTRICAL"
    assert fire.domain == "NTD_FIRE"


def test_email_routes_to_mail_index(tmp_path):
    path = tmp_path / "site-letter.eml"
    path.write_text(
        "Subject: Акт скрытых работ\n"
        "From: author@example.com\n"
        "To: les@example.com\n"
        "\n"
        "Прошу проверить исполнительную документацию.",
        encoding="utf-8",
    )

    route = route_document(path)

    assert route.doc_type == "EMAIL"
    assert route.domain == "MAIL"
    assert route.dataset_name == "MAIL_Index"
    assert route.content_type == "email"
    assert route.pipeline == "markdown"
