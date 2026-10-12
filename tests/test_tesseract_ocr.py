"""Tesseract OCR-бэкенд — локальный путь для русского (бинарь, изолирован). Без живого бинаря."""
from __future__ import annotations

import subprocess
import types

import pytest

from backend import ocr_parser


def test_make_ocr_parser_tesseract(monkeypatch):
    monkeypatch.setenv("RAG_OCR_BACKEND", "tesseract")
    p = ocr_parser.make_ocr_parser()
    assert isinstance(p, ocr_parser.TesseractOCRParser)


def test_tesseract_lang_default(monkeypatch):
    monkeypatch.delenv("RAG_OCR_TESSERACT_LANG", raising=False)
    assert ocr_parser.TesseractOCRParser().lang == "rus+eng"


def test_tesseract_ocr_page(monkeypatch):
    from PIL import Image

    captured = {}

    def fake_run(cmd, capture_output, timeout):
        with Image.open(cmd[1]) as page:
            page.load()
            captured["size"] = page.size
        captured["cmd"] = cmd
        return types.SimpleNamespace(
            returncode=0,
            stdout="АКТ № 5 от 8 ноября 2023\n".encode("utf-8"),
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    p = ocr_parser.TesseractOCRParser(lang="rus+eng")
    txt = p.ocr_page(Image.new("RGB", (40, 20), "white"))
    assert "АКТ" in txt and "2023" in txt
    assert captured["size"] == (40, 20)
    assert "-l" in captured["cmd"] and "rus+eng" in captured["cmd"]  # язык передан


@pytest.mark.parametrize(
    ("effect", "code"),
    [
        (types.SimpleNamespace(returncode=2, stdout=b"", stderr=b"private path"), "tesseract_exit_2"),
        (FileNotFoundError("missing"), "tesseract_missing"),
        (subprocess.TimeoutExpired("tesseract", 120), "tesseract_timeout"),
    ],
)
def test_tesseract_execution_failure_is_typed(monkeypatch, effect, code):
    from PIL import Image

    def fake_run(*_args, **_kwargs):
        if isinstance(effect, BaseException):
            raise effect
        return effect

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ocr_parser.OCRProcessingError) as raised:
        ocr_parser.TesseractOCRParser().ocr_page(Image.new("RGB", (10, 10)))
    assert raised.value.code == code
    assert "private path" not in str(raised.value)


def test_tesseract_missing_binary_logs_only_stable_diagnostic(monkeypatch):
    from PIL import Image

    logged = []
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(ocr_parser.logger, "error", lambda *args: logged.append(args))

    with pytest.raises(ocr_parser.OCRProcessingError):
        ocr_parser.TesseractOCRParser(binary="C:/private/path/tesseract").ocr_page(Image.new("RGB", (10, 10)))

    assert logged == [("[OCR] tesseract execution failed: tesseract_missing",)]


def test_tesseract_parse_pdf_streams_and_omits_blank_headings(monkeypatch, tmp_path):
    events = []

    def pages(_path, _dpi):
        from PIL import Image

        events.append("yield-1")
        yield 1, Image.new("RGB", (8, 8))
        events.append("yield-2")
        yield 2, Image.new("RGB", (8, 8))

    parser = ocr_parser.TesseractOCRParser()
    outputs = iter(["", "Технические условия"])
    monkeypatch.setattr(ocr_parser, "iter_pdf_images", pages)
    monkeypatch.setattr(parser, "ocr_page", lambda _image: events.append(f"ocr-{len(events)}") or next(outputs))

    text = parser.parse_pdf(tmp_path / "scan.pdf", dpi=300)

    assert events[0:2] == ["yield-1", "ocr-1"]
    assert "## Стр. 1" not in text
    assert "## Стр. 2\n\nТехнические условия" in text


def test_tesseract_parse_pdf_returns_empty_for_blank_pages(monkeypatch, tmp_path):
    from PIL import Image

    parser = ocr_parser.TesseractOCRParser()
    monkeypatch.setattr(
        ocr_parser,
        "iter_pdf_images",
        lambda _path, _dpi: iter([(1, Image.new("RGB", (8, 8))), (2, Image.new("RGB", (8, 8)))]),
    )
    monkeypatch.setattr(parser, "ocr_page", lambda _image: "  ")

    assert parser.parse_pdf(tmp_path / "scan.pdf", dpi=300) == ""


def test_tesseract_parse_pdf_annotates_execution_failure_with_page(monkeypatch, tmp_path):
    from PIL import Image

    parser = ocr_parser.TesseractOCRParser()
    monkeypatch.setattr(
        ocr_parser,
        "iter_pdf_images",
        lambda _path, _dpi: iter([(1, Image.new("RGB", (8, 8))), (2, Image.new("RGB", (8, 8)))]),
    )
    calls = 0

    def fail_on_second_page(_image):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ocr_parser.OCRProcessingError("tesseract_timeout")
        return "first page"

    monkeypatch.setattr(parser, "ocr_page", fail_on_second_page)

    with pytest.raises(ocr_parser.OCRProcessingError) as raised:
        parser.parse_pdf(tmp_path / "scan.pdf", dpi=300)
    assert raised.value.code == "tesseract_timeout"
    assert raised.value.page == 2
    assert "private path" not in str(raised.value)
