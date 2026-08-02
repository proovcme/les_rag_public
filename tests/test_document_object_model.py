from proxy.services.document_object_model import (
    DOCUMENT_OBJECT_SCHEMA,
    classify_parser_route,
    page_fact,
)


def test_classify_parser_route_keeps_digital_text_cheap():
    route = classify_parser_route("digital_text", ocr_needed=False)
    assert route["schema"] == DOCUMENT_OBJECT_SCHEMA
    assert route["parser_chain"] == ["pymupdf_page_text"]
    assert route["heavy_allowed"] is False


def test_classify_parser_route_scan_requires_ocr():
    route = classify_parser_route("scan")
    assert route["parser_chain"] == ["ocr_required"]
    assert route["heavy_allowed"] is True


def test_page_fact_carries_provenance():
    fact = page_fact(
        file_name="spec.pdf",
        page=3,
        page_type="table",
        text="Таблица 1",
        bbox=[0.1, 0.2, 0.9, 0.8],
    )
    assert fact["schema"] == DOCUMENT_OBJECT_SCHEMA
    assert fact["provenance"]["page"] == 3
    assert fact["bbox"] == [0.1, 0.2, 0.9, 0.8]
