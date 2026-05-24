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
    assert route.domain == "NTD_MATERIALS"


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


def test_industrial_smoke_stacks_are_structural_not_fire():
    route = classify_document(
        DocumentProbe(
            path=Path("СП 375.1325800.2023. Свод правил. Трубы промышленные дымовые.docx"),
            suffix=".docx",
            size_bytes=841_000,
            text_sample="Трубы промышленные дымовые. Правила проектирования и строительства.",
        )
    )

    assert route.doc_type == "NORMATIVE"
    assert route.domain == "NTD_STRUCTURAL"
    assert route.dataset_name == "NTD_STRUCTURAL_Index"


def test_smoke_control_still_routes_to_fire():
    route = classify_document(
        DocumentProbe(
            path=Path("СП 7.13130. Отопление вентиляция противодымная защита.docx"),
            suffix=".docx",
            size_bytes=100_000,
            text_sample="Требования пожарной безопасности и противодымной защиты.",
        )
    )

    assert route.domain == "NTD_FIRE"


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


def test_spds_and_geotech_route_out_of_other():
    spds = classify_document(
        DocumentProbe(
            path=Path("ГОСТ 21.101-2020. Система проектной документации.docx"),
            suffix=".docx",
            size_bytes=10_000,
        )
    )
    geotech = classify_document(
        DocumentProbe(
            path=Path("ГОСТ 12071-2014. Грунты. Отбор образцов.docx"),
            suffix=".docx",
            size_bytes=10_000,
        )
    )

    assert spds.domain == "NTD_SPDS"
    assert spds.dataset_name == "NTD_SPDS_Index"
    assert geotech.domain == "NTD_GEOTECH"
    assert geotech.dataset_name == "NTD_GEOTECH_Index"


def test_transport_and_hvac_route_out_of_other():
    transport = classify_document(
        DocumentProbe(
            path=Path("СП 35.13330.2011. Мосты и трубы.docx"),
            suffix=".docx",
            size_bytes=10_000,
        )
    )
    hvac = classify_document(
        DocumentProbe(
            path=Path("СП 51.13330.2011. Защита от шума.docx"),
            suffix=".docx",
            size_bytes=10_000,
        )
    )

    assert transport.domain == "NTD_TRANSPORT"
    assert hvac.domain == "NTD_HVAC"


def test_generic_ntd_normative_uses_general_bucket():
    route = classify_document(
        DocumentProbe(
            path=Path("RAG_Content/NTD/ГОСТ Р 70070-2022. Национальный стандарт Российской Федерации.docx"),
            suffix=".docx",
            size_bytes=10_000,
        )
    )

    assert route.domain == "NTD_GENERAL"
    assert route.dataset_name == "NTD_GENERAL_Index"
