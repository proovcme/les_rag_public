from pathlib import Path
from zipfile import ZipFile
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


def test_route_smeta_ru_norm_archive_projection_to_category_dataset(tmp_path):
    path = tmp_path / "RAG_Content/TABLE_SMETA/SMETA_RU_NORM/fsnb2022/00_dataset_card.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Smeta.RU norm dataset\n\nФСНБ-2022 ГЭСН ГЭСНм ФСБЦ ресурсы",
        encoding="utf-8",
    )

    route = route_document(path)

    assert route.domain == "SMETA_RU_NORM_FSNB2022"
    assert route.dataset_name == "SMETA_RU_NORM_FSNB2022_Index"


def test_smeta_service_cards_route_to_separate_system_dataset(tmp_path):
    path = tmp_path / "RAG_Content/TABLE_SMETA/SMETA_SERVICE/collection_01.md"
    path.parent.mkdir(parents=True)
    path.write_text("# ГЭСН 01\nНавигационная карточка сборника", encoding="utf-8")
    route = route_document(path)
    assert route.domain == "SMETA_SERVICE"
    assert route.dataset_name == "SMETA_SERVICE_Index"
    assert route.doc_type in {"NORMATIVE", "SMETA"}


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


def test_project_pdf_with_weak_smeta_word_is_not_table_smeta():
    probe = DocumentProbe(
        path=Path("27_05-22-Р-ЭОМ.1_19.06.2025.pdf"),
        suffix=".pdf",
        size_bytes=27_000_000,
        page_count=83,
        text_sample=(
            "Центр обработки данных. Система бесперебойного гарантированного "
            "электроснабжения. В пояснениях встречается смета затрат."
        ),
        has_text_layer=True,
        has_tables=True,
        table_count_hint=3,
    )

    route = classify_document(probe)

    assert route.doc_type == "DOCUMENT"
    assert route.domain == "NTD_ELECTRICAL"
    assert route.dataset_name == "NTD_ELECTRICAL_Index"
    assert route.pipeline == "markdown_pdf_tables"


def test_project_pdf_with_normative_references_stays_project_document():
    probe = DocumentProbe(
        path=Path("27_05-22-Р-ЭОМ.1 Изм.8.3 полный.pdf"),
        suffix=".pdf",
        size_bytes=33_000_000,
        page_count=117,
        text_sample=(
            "Заказчик: ООО «Научный центр «Большая цифра». Центр обработки данных. "
            "РАБОЧАЯ ДОКУМЕНТАЦИЯ. Система бесперебойного гарантированного "
            "электропитания. Технические решения соответствуют сводам правил, "
            "ГОСТ и СП, действующим на территории Российской Федерации."
        ),
        has_text_layer=True,
        has_tables=True,
    )

    route = classify_document(probe)

    assert route.doc_type == "DOCUMENT"
    assert route.domain == "NTD_ELECTRICAL"


def test_pdf_named_smeta_still_routes_to_table_smeta():
    probe = DocumentProbe(
        path=Path("Локальная смета ЭОМ.pdf"),
        suffix=".pdf",
        size_bytes=2_000_000,
        page_count=12,
        text_sample="Наименование работ Ед.изм. Количество Стоимость",
        has_text_layer=True,
        has_tables=True,
    )

    route = classify_document(probe)

    assert route.doc_type == "SMETA"
    assert route.domain == "TABLE_SMETA"


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


def test_route_cad_bim_folder_to_cad_bim_index():
    probe = DocumentProbe(
        path=Path("RAG_Content/CAD_BIM/exports/cad_bim_speckle_abc.md"),
        suffix=".md",
        size_bytes=2000,
        text_sample="CAD/BIM JSON projection\nLayer: A-WALL\nCategory: Walls",
    )

    route = classify_document(probe)

    assert route.doc_type == "CAD_BIM"
    assert route.domain == "CAD_BIM"
    assert route.dataset_name == "CAD_BIM_Index"
    assert route.content_type == "cad_bim"
    assert route.pipeline == "json_graph_projection"


def test_route_artel_learning_case_to_artel_index():
    probe = DocumentProbe(
        path=Path("RAG_Content/ARTEL/family_learning_cases/demo_metal_cabinet_001.md"),
        suffix=".md",
        size_bytes=3000,
        text_sample=(
            "# ARTEL FamilyLearningCase\n"
            "Family name: ARTEL_DEMO_MetalCabinet\n"
            "ADSK_Наименование: Шкаф управления металлический\n"
            "RFA catalog validation FOP shared parameters"
        ),
        has_tables=True,
    )

    route = classify_document(probe)

    assert route.doc_type == "LEARNING_CASE"
    assert route.domain == "ARTEL"
    assert route.dataset_name == "ARTEL_Index"
    assert route.content_type == "text"
    assert route.pipeline == "markdown"


def test_route_artel_fop_profile_to_artel_index():
    probe = DocumentProbe(
        path=Path("RAG_Content/ARTEL/fop_profiles/FOP2021.md"),
        suffix=".md",
        size_bytes=10_000,
        text_sample=(
            "# ARTEL FOP Shared Parameter Profile\n"
            "ФОП shared parameters Revit GUID\n"
            "ADSK_Наименование GUID=11111111-1111-1111-1111-111111111111"
        ),
        has_tables=True,
    )

    route = classify_document(probe)

    assert route.doc_type == "FOP_PROFILE"
    assert route.domain == "ARTEL"
    assert route.dataset_name == "ARTEL_Index"
    assert route.content_type == "text"
    assert route.pipeline == "markdown"


def test_route_artel_family_guide_to_artel_index():
    probe = DocumentProbe(
        path=Path("RAG_Content/ARTEL/family_guides/revit_family_creation_guide_autodesk_2017.pdf"),
        suffix=".pdf",
        size_bytes=2_000_000,
        page_count=45,
        text_sample=(
            "РУКОВОДСТВО ПО СОЗДАНИЮ СЕМЕЙСТВ Autodesk Revit\n"
            "Требования к семействам. Процедура создания семейств."
        ),
        has_text_layer=True,
    )

    route = classify_document(probe)

    assert route.doc_type == "FAMILY_GUIDE"
    assert route.domain == "ARTEL"
    assert route.dataset_name == "ARTEL_Index"
    assert route.content_type == "text"
    assert route.pipeline == "markdown"


def test_route_artel_revit_api_reference_to_artel_index():
    probe = DocumentProbe(
        path=Path("RAG_Content/ARTEL/revit_api/revit_api_family_automation_reference.md"),
        suffix=".md",
        size_bytes=12_000,
        text_sample=(
            "# ARTEL Revit API Reference\n"
            "Document type: REVIT_API_REFERENCE\n"
            "FamilyManager FilteredElementCollector Transaction NewFamilyDocument"
        ),
        has_tables=True,
    )

    route = classify_document(probe)

    assert route.doc_type == "REVIT_API_REFERENCE"
    assert route.domain == "ARTEL"
    assert route.dataset_name == "ARTEL_Index"
    assert route.content_type == "text"
    assert route.pipeline == "markdown"


def test_route_artel_revit_model_guide_to_artel_index():
    probe = DocumentProbe(
        path=Path("RAG_Content/ARTEL/revit_model_guides/rhino_inside_revit_data_model.md"),
        suffix=".md",
        size_bytes=12_000,
        text_sample=(
            "# ARTEL Revit Model Guide\n"
            "Document type: REVIT_MODEL_GUIDE\n"
            "Understanding Revit's data model. Categories, Families, Types, Parameters."
        ),
    )

    route = classify_document(probe)

    assert route.doc_type == "REVIT_MODEL_GUIDE"
    assert route.domain == "ARTEL"
    assert route.dataset_name == "ARTEL_Index"
    assert route.content_type == "text"
    assert route.pipeline == "markdown"


def test_route_artel_revit_api_symbol_map_to_artel_index():
    probe = DocumentProbe(
        path=Path("RAG_Content/ARTEL/revit_api_symbol_map/revit_api_2023_symbol_map.md"),
        suffix=".md",
        size_bytes=50_000,
        text_sample=(
            "# ARTEL Revit API Symbol Map\n"
            "Document type: REVIT_API_SYMBOL_MAP\n"
            "Schema: artel.revit_api_symbol_map.v1\n"
            "Autodesk.Revit.DB.FamilyManager method property namespace"
        ),
    )

    route = classify_document(probe)

    assert route.doc_type == "REVIT_API_SYMBOL_MAP"
    assert route.domain == "ARTEL"
    assert route.dataset_name == "ARTEL_Index"
    assert route.content_type == "text"
    assert route.pipeline == "markdown"


def test_route_artel_revit_api_sdk_doc_to_artel_index():
    probe = DocumentProbe(
        path=Path("RAG_Content/ARTEL/revit_api_sdk_docs/autodesk_revit_db_familymanager.md"),
        suffix=".md",
        size_bytes=30_000,
        text_sample=(
            "# ARTEL Revit API SDK Doc\n"
            "Document type: REVIT_API_SDK_DOC\n"
            "Source kind: Revit SDK CHM\n"
            "FamilyManager class members methods properties"
        ),
    )

    route = classify_document(probe)

    assert route.doc_type == "REVIT_API_SDK_DOC"
    assert route.domain == "ARTEL"
    assert route.dataset_name == "ARTEL_Index"
    assert route.content_type == "text"
    assert route.pipeline == "markdown"


def test_route_raw_ifc_to_cad_bim_index():
    probe = DocumentProbe(
        path=Path("RAG_Content/CAD_BIM/IFC/model.ifc"),
        suffix=".ifc",
        size_bytes=2000,
        text_sample="",
    )

    route = classify_document(probe)

    assert route.doc_type == "CAD_BIM"
    assert route.dataset_name == "CAD_BIM_Index"


def test_docx_probe_counts_tables(tmp_path):
    path = tmp_path / "СП 1.13130.docx"
    xml = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Показатель</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body>
</w:document>"""
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)

    probe = probe_document(path)
    route = classify_document(probe)

    assert probe.has_tables is True
    assert probe.table_count_hint == 1
    assert route.content_type == "mixed"


def test_book_folder_pdf_routes_to_books_index_with_rich_pipeline():
    probe = DocumentProbe(
        path=Path("RAG_Content/BOOKS/Рук-во по устройству ЭУ 2019.pdf"),
        suffix=".pdf",
        size_bytes=38_000_000,
        page_count=596,
        text_sample="Руководство по устройству электроустановок. Таблица 1.",
    )

    route = classify_document(probe)

    assert route.doc_type == "BOOK"
    assert route.domain == "BOOKS"
    assert route.dataset_name == "BOOKS_Index"
    assert route.content_type == "mixed"
    assert route.complexity == "heavy"
    assert route.pipeline == "markdown_pdf_tables"


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
    nodes = adapter._sync_table_nodes(csv_path, data_dir, "smeta.csv", "ds-1", route)

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


def test_strong_gost_signal_wins_over_smeta_word_in_normative_doc():
    route = classify_document(
        DocumentProbe(
            path=Path("Здания и фрагменты зданий. Метод натурных огневых испытаний.docx"),
            suffix=".docx",
            size_bytes=10_000,
            text_sample=(
                "ГОСТ Р 53309-2009 Национальный стандарт Российской Федерации. "
                "В программе испытаний указывается смета затрат."
            ),
        )
    )

    assert route.doc_type == "NORMATIVE"
    assert route.domain == "NTD_FIRE"


def test_gesn_pdf_norm_routes_to_normative_not_table_smeta():
    route = classify_document(
        DocumentProbe(
            path=Path("ГЭСН 81-02-09-2022. Сметные нормы на строительные работы. Сб.PDF"),
            suffix=".pdf",
            size_bytes=10_000,
            text_sample="",
            has_tables=False,
        )
    )
    assert route.doc_type == "NORMATIVE"
    assert route.domain == "NTD_CONSTRUCTION"
    assert route.dataset_name == "NTD_CONSTRUCTION_Index"


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


def test_hvac_name_beats_generic_fire_safety_text():
    route = classify_document(
        DocumentProbe(
            path=Path("СП 60.13330.2020. Отопление, вентиляция и кондиционирование.docx"),
            suffix=".docx",
            size_bytes=100_000,
            text_sample="Общие требования пожарной безопасности учитываются при проектировании.",
        )
    )

    assert route.domain == "NTD_HVAC"
    assert route.dataset_name == "NTD_HVAC_Index"


def test_fire_design_guide_number_beats_generic_spds_text():
    route = classify_document(
        DocumentProbe(
            path=Path("ГОСТ Р 59638-2021. Системы противопожарной защиты.docx"),
            suffix=".docx",
            size_bytes=100_000,
            text_sample="Руководство по проектированию систем пожарной сигнализации.",
        )
    )

    assert route.domain == "NTD_FIRE"


def test_hvac_design_norm_does_not_route_to_spds_by_project_word():
    route = classify_document(
        DocumentProbe(
            path=Path("СП 347.1325800.2017. Внутренние системы отопления.docx"),
            suffix=".docx",
            size_bytes=100_000,
            text_sample="Правила проектирования внутренних систем отопления.",
        )
    )

    assert route.domain == "NTD_HVAC"


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


def test_route_contract_pdf_and_docx():
    contract_docx = classify_document(
        DocumentProbe(
            path=Path("Договор_подряда_№123-2025.docx"),
            suffix=".docx",
            size_bytes=25_000,
            text_sample="Договор подряда №123-2025. Настоящий договор заключен между Подрядчиком и Заказчиком. Предмет договора: выполнение строительно-монтажных работ.",
        )
    )
    contract_pdf = classify_document(
        DocumentProbe(
            path=Path("Contract_Services_2025.pdf"),
            suffix=".pdf",
            size_bytes=50_000,
            text_sample="Настоящий контракт регулирует права и обязанности сторон. Адреса и реквизиты сторон.",
        )
    )

    assert contract_docx.doc_type == "CONTRACT"
    assert contract_pdf.doc_type == "CONTRACT"


def test_route_general_act_and_addendum():
    act = classify_document(
        DocumentProbe(
            path=Path("Акт_выполненных_работ_№5.pdf"),
            suffix=".pdf",
            size_bytes=15_000,
            text_sample="Акт сдачи-приемки оказанных услуг. Работы выполнены в полном объеме.",
        )
    )
    addendum = classify_document(
        DocumentProbe(
            path=Path("Доп_соглашение_№1_к_договору_123.docx"),
            suffix=".docx",
            size_bytes=12_000,
            text_sample="Дополнительное соглашение №1 к договору подряда. Приложение №1 является неотъемлемой частью.",
        )
    )

    assert act.doc_type == "ACT_GENERAL"
    assert addendum.doc_type == "ADDENDUM"


def test_route_invoice_bill():
    invoice = classify_document(
        DocumentProbe(
            path=Path("Счет_на_оплату_№45.pdf"),
            suffix=".pdf",
            size_bytes=10_000,
            text_sample="Счёт на оплату №45 от 12.02.2025. Всего к оплате: 150 000 руб.",
        )
    )
    upd = classify_document(
        DocumentProbe(
            path=Path("УПД_0012.xlsx"),
            suffix=".xlsx",
            size_bytes=8_000,
            text_sample="Универсальный передаточный документ (УПД). Счет-фактура №12.",
            has_tables=True,
        )
    )

    assert invoice.doc_type == "INVOICE_BILL"
    assert upd.doc_type == "INVOICE_BILL"
    assert upd.domain == "TABLE_INVOICE_BILL"


def test_route_tz_tor_letter_passport_drawing():
    tz = classify_document(
        DocumentProbe(
            path=Path("ТЗ_на_проектирование_ЭОМ.docx"),
            suffix=".docx",
            size_bytes=18_000,
            text_sample="Техническое задание на выполнение проектных работ. Требования к оборудованию.",
        )
    )
    letter = classify_document(
        DocumentProbe(
            path=Path("Исходящее_письмо_№105.pdf"),
            suffix=".pdf",
            size_bytes=10_000,
            text_sample="Исходящее письмо №105. Направляем согласованный протокол совещания.",
        )
    )
    passport = classify_document(
        DocumentProbe(
            path=Path("Паспорт_оборудования_ИБП.pdf"),
            suffix=".pdf",
            size_bytes=40_000,
            text_sample="Паспорт изделия и руководство по эксплуатации. Сертификат соответствия.",
        )
    )
    drawing = classify_document(
        DocumentProbe(
            path=Path("Однолинейная_схема_ЭОМ.pdf"),
            suffix=".pdf",
            size_bytes=80_000,
            text_sample="Однолинейная схема щита ЩО-1. Сборочный чертеж.",
        )
    )

    assert tz.doc_type == "TZ_TOR"
    assert letter.doc_type == "LETTER"
    assert passport.doc_type == "PASSPORT_CERT"
    assert drawing.doc_type == "DRAWING"


def test_route_extracts_doc_passport_metadata():
    route = classify_document(
        DocumentProbe(
            path=Path("Договор_подряда_№123-2025_от_15.01.2025.pdf"),
            suffix=".pdf",
            size_bytes=45_000,
            text_sample="Договор подряда № 123-2025 от 15.01.2025. Заказчик: ООО Вектор. Подрядчик: ООО СтройСервис. Сумма договора: 1 500 000 руб.",
        )
    )

    doc_passport = route.metadata.get("doc_passport") or {}

    assert doc_passport.get("doc_number") == "123-2025"
    assert doc_passport.get("doc_date") == "15.01.2025"
    assert "Заказчик" in doc_passport.get("contracting_parties", [])
    assert "Подрядчик" in doc_passport.get("contracting_parties", [])
    assert "1 500 000 руб" in doc_passport.get("amount_summary", "")
