from __future__ import annotations

from pathlib import Path

import fitz
import pytest

import backend.converter as converter


def _make_pdf(path: Path, pages: int, text: str = "") -> Path:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()
    return path


def test_fast_text_layer_returns_none_for_scan(tmp_path):
    path = _make_pdf(tmp_path / "scan.pdf", pages=5)
    assert converter._parse_pdf_fast_text_layer(path, min_chars_per_page=20) is None


def test_fast_text_layer_keeps_real_text(tmp_path):
    path = _make_pdf(tmp_path / "text.pdf", pages=3, text="Ventilation system requirements for the building")
    result = converter._parse_pdf_fast_text_layer(path, min_chars_per_page=20)
    assert result is not None
    assert "Ventilation system requirements" in result


def test_fast_text_layer_with_fallback_threshold_rejects_placeholder_projection(tmp_path):
    path = _make_pdf(tmp_path / "scan.pdf", pages=5)
    result = converter._parse_pdf_fast_text_layer(
        path,
        reason="isolated_convert_failed: boom",
        min_chars_per_page=20,
    )
    assert result is None


def test_scanned_pdf_falls_through_to_ocr_capable_converter(tmp_path, monkeypatch):
    path = _make_pdf(tmp_path / "scan.pdf", pages=57)
    calls = []
    monkeypatch.setattr(
        converter,
        "convert_to_markdown_isolated",
        lambda *args, **kwargs: calls.append("isolated") or "распознанный OCR текст",
    )
    assert converter.convert_to_markdown_for_indexing(path) == "распознанный OCR текст"
    assert calls == ["isolated"]


@pytest.mark.parametrize("raw", ["", "мусор", "-5"])
def test_invalid_fast_text_threshold_preserves_short_drawing_labels(tmp_path, monkeypatch, raw):
    monkeypatch.setenv("RAG_PDF_FAST_TEXT_MIN_CHARS_PER_PAGE", raw)
    path = _make_pdf(tmp_path / "drawing.pdf", pages=1, text="PE N")
    monkeypatch.setattr(converter, "convert_to_markdown_isolated", lambda *a, **k: pytest.fail(
        "real short drawing labels must not require OCR"
    ))
    result = converter.convert_to_markdown_for_indexing(path)
    assert "PE N" in result
    assert "## Page 1" in result


def test_blank_fast_projection_is_not_evidence_even_with_zero_threshold(tmp_path):
    path = _make_pdf(tmp_path / "blank.pdf", pages=1)
    assert converter._parse_pdf_fast_text_layer(path) is None
