"""Tesseract OCR-бэкенд — локальный путь для русского (бинарь, изолирован). Без живого бинаря."""
from __future__ import annotations

import subprocess
import types

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
        captured["cmd"] = cmd
        return types.SimpleNamespace(stdout="АКТ № 5 от 8 ноября 2023\n".encode("utf-8"))

    monkeypatch.setattr(subprocess, "run", fake_run)
    p = ocr_parser.TesseractOCRParser(lang="rus+eng")
    txt = p.ocr_page(Image.new("RGB", (40, 20), "white"))
    assert "АКТ" in txt and "2023" in txt
    assert "-l" in captured["cmd"] and "rus+eng" in captured["cmd"]  # язык передан


def test_tesseract_missing_binary_soft(monkeypatch):
    from PIL import Image

    def boom(*a, **k):
        raise FileNotFoundError("no tesseract")

    monkeypatch.setattr(subprocess, "run", boom)
    # мягкая деградация: нет бинаря → пустая строка, не падение
    assert ocr_parser.TesseractOCRParser().ocr_page(Image.new("RGB", (10, 10))) == ""
