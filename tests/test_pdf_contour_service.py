"""Unified PDF contour: GUI passport and RAG page-node enrichment."""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

fitz = pytest.importorskip("fitz")

from backend.qdrant_adapter import QdrantLlamaIndexAdapter, _pdf_page_nodes_enabled
from backend.converter import _parse_pdf_fast_text_layer
from proxy.routers.documents import router as documents_router
from proxy.routers import documents as documents_module
from proxy.services import pdf_contour_service as contour


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _white_pixmap(width: int = 200, height: int = 200):
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), 0)
    pixmap.clear_with(245)
    return pixmap


def _make_pdf(path: Path) -> None:
    document = fitz.open()

    text_page = document.new_page(width=595, height=842)
    text_page.insert_textbox(
        fitz.Rect(48, 48, 545, 760),
        "Digital searchable project text with exact designations A-101 and OV-2. " * 20,
        fontsize=10,
    )

    scan_page = document.new_page(width=595, height=842)
    scan_page.insert_image(scan_page.rect, pixmap=_white_pixmap())

    drawing_page = document.new_page(width=842, height=595)
    for index in range(24):
        y = 30 + index * 20
        drawing_page.draw_line((25, y), (817, y))
    drawing_page.insert_text((40, 560), "A-102", fontsize=10)

    table_page = document.new_page(width=595, height=842)
    rows = [["Code", "Name", "Qty"], ["E-1", "Panel", "2"], ["E-2", "Cable", "40"]]
    x0, y0, cell_w, cell_h = 50, 60, 150, 32
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            table_page.insert_text(
                (x0 + column_index * cell_w + 5, y0 + row_index * cell_h + 20),
                value,
                fontsize=10,
            )
    for column_index in range(4):
        x = x0 + column_index * cell_w
        table_page.draw_line((x, y0), (x, y0 + len(rows) * cell_h))
    for row_index in range(len(rows) + 1):
        y = y0 + row_index * cell_h
        table_page.draw_line((x0, y), (x0 + 3 * cell_w, y))

    mixed_page = document.new_page(width=595, height=842)
    mixed_page.insert_textbox(
        fitz.Rect(40, 40, 280, 760),
        "Mixed page explanatory text and equipment designation AHU-1. " * 15,
        fontsize=10,
    )
    mixed_page.insert_image(fitz.Rect(320, 70, 570, 700), pixmap=_white_pixmap())

    document.save(str(path))
    document.close()


def test_pdf_contour_classifies_pages_and_preserves_original(tmp_path):
    source = tmp_path / "project.pdf"
    _make_pdf(source)
    before = _sha(source)

    result = contour.audit_pdf(source, doc_id="doc-1", file_name="project.pdf", max_pages=20)

    assert result["schema"] == contour.PDF_CONTOUR_SCHEMA
    assert result["status"] == "ready"
    assert result["page_total"] == 5
    assert [page["page_type"] for page in result["pages"]] == [
        "digital_text",
        "scan",
        "drawing",
        "table",
        "mixed",
    ]
    assert result["pages"][1]["requires_ocr"] is True
    assert result["pages"][0]["evidence_fragments"][0]["bbox"]
    assert result["pages"][0]["source_ref"] == "project.pdf#page=1"
    assert result["tables_detected"] >= 1
    assert _sha(source) == before


def test_pdf_contour_reports_partial_and_damaged_text_route(tmp_path):
    source = tmp_path / "project.pdf"
    _make_pdf(source)

    result = contour.audit_pdf(source, max_pages=2)
    assert result["status"] == "partial"
    assert result["pages_inspected"] == 2
    assert result["warnings"] == ["Показаны первые 2 из 5 страниц"]

    page_type, confidence, warnings = contour._classify_page(
        text_chars=80,
        image_coverage=0.0,
        drawing_count=0,
        table_count=0,
        text_quality={"status": "damaged"},
    )
    assert page_type == "damaged_text_layer"
    assert confidence >= 0.9
    assert warnings


def test_pdf_contour_preview_supports_page_and_evidence_bbox(tmp_path):
    source = tmp_path / "project.pdf"
    _make_pdf(source)
    before = _sha(source)

    page_png = contour.render_page_preview(source, page_number=1, max_width=700)
    clip_png = contour.render_page_preview(
        source,
        page_number=1,
        max_width=700,
        bbox=(40.0, 40.0, 300.0, 220.0),
    )

    assert page_png.startswith(b"\x89PNG\r\n\x1a\n")
    assert clip_png.startswith(b"\x89PNG\r\n\x1a\n")
    page_image = fitz.Pixmap(page_png)
    clip_image = fitz.Pixmap(clip_png)
    assert clip_image.height < page_image.height
    assert _sha(source) == before


def test_rag_page_nodes_receive_pdf_passport_and_scan_route(tmp_path):
    source = tmp_path / "project.pdf"
    _make_pdf(source)
    markdown = "\n\n".join([
        "## Page 1",
        "A" * 320,
        "## Стр. 2",
        "OCR text from scanned page " * 20,
    ])
    adapter = SimpleNamespace()
    adapter._route_payload = QdrantLlamaIndexAdapter._route_payload.__get__(adapter)
    adapter._split_pdf_page_markdown = QdrantLlamaIndexAdapter._split_pdf_page_markdown
    adapter._split_pdf_page_text = QdrantLlamaIndexAdapter._split_pdf_page_text

    nodes = QdrantLlamaIndexAdapter._sync_pdf_page_text_nodes(
        adapter,
        "project.pdf",
        "dataset-1",
        markdown,
        None,
        file_path=source,
    )

    assert len(nodes) == 2
    text_payload, scan_payload = (node["payload"] for node in nodes)
    assert text_payload["pdf_page_type"] == "digital_text"
    assert text_payload["source_ref"] == "project.pdf#page=1"
    assert text_payload["pdf_fragment_bboxes"]
    assert text_payload["source_layer"] == "pdf_text_layer"
    assert scan_payload["pdf_page_type"] == "scan"
    assert scan_payload["pdf_requires_ocr"] is True
    assert scan_payload["source_layer"] == "pdf_ocr_text"


def test_short_searchable_pdf_pages_are_not_dropped_from_rag(tmp_path):
    source = tmp_path / "short-project.pdf"
    document = fitz.open()
    for text in (
        "COVER LES-SMOKE-B455",
        "LES-SMOKE-B455-VALVE-731 AIRFLOW 7310 M3/H DRAWING SHEET OV-2",
        "NOTES B455",
    ):
        page = document.new_page(width=595, height=842)
        page.insert_text((48, 72), text, fontsize=10)
    document.save(source)
    document.close()

    markdown = _parse_pdf_fast_text_layer(source, reason="regression_test")
    adapter = SimpleNamespace()
    adapter._route_payload = QdrantLlamaIndexAdapter._route_payload.__get__(adapter)
    adapter._split_pdf_page_markdown = QdrantLlamaIndexAdapter._split_pdf_page_markdown
    adapter._split_pdf_page_text = QdrantLlamaIndexAdapter._split_pdf_page_text

    nodes = QdrantLlamaIndexAdapter._sync_pdf_page_text_nodes(
        adapter,
        source.name,
        "dataset-short-pages",
        markdown,
        None,
        file_path=source,
    )

    assert len(nodes) == 3
    page_two = next(node for node in nodes if node["payload"]["page"] == 2)
    assert "LES-SMOKE-B455-VALVE-731" in page_two["text"]
    assert page_two["payload"]["source_ref"] == "short-project.pdf#page=2"
    assert page_two["payload"]["type"] == "pdf_page_text"


def test_ocr_pdf_still_uses_page_nodes():
    route = SimpleNamespace(pipeline="markdown_needs_ocr")
    assert _pdf_page_nodes_enabled(Path("scan.pdf"), route) is True
    assert QdrantLlamaIndexAdapter._split_pdf_page_markdown("## Стр. 7\n\nOCR result") == [(7, "OCR result")]


def test_pdf_contour_routes_are_registered():
    routes = {
        (route.path, method)
        for route in documents_router.routes
        for method in getattr(route, "methods", set())
    }
    assert ("/api/documents/by-id/{doc_id}/pdf-contour", "GET") in routes
    assert ("/api/documents/by-id/{doc_id}/pdf-contour/pages/{page_number}/preview", "GET") in routes


def test_uploaded_pdf_source_resolves_inside_dataset_storage(tmp_path, monkeypatch):
    source = tmp_path / "storage" / "datasets" / "dataset-1" / "folder" / "project.pdf"
    source.parent.mkdir(parents=True)
    _make_pdf(source)
    fake_explorer = SimpleNamespace(
        get_document=lambda _doc_id: {
            "id": "doc-1",
            "dataset_id": "dataset-1",
            "file_name": "folder/project.pdf",
            "source_path": "",
        }
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(documents_module, "explorer", lambda: fake_explorer)

    document, resolved = documents_module._pdf_document_source("doc-1")

    assert document["file_name"] == "folder/project.pdf"
    assert Path(resolved) == source.resolve()
