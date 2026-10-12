"""Tesseract OCR-бэкенд — локальный путь для русского (бинарь, изолирован). Без живого бинаря."""
from __future__ import annotations

import subprocess
import tempfile
import types
from pathlib import Path

import pytest

from backend import ocr_parser


def test_make_ocr_parser_tesseract(monkeypatch):
    monkeypatch.setenv("RAG_OCR_BACKEND", "tesseract")
    p = ocr_parser.make_ocr_parser()
    assert isinstance(p, ocr_parser.TesseractOCRParser)


def test_tesseract_lang_default(monkeypatch):
    monkeypatch.delenv("RAG_OCR_TESSERACT_LANG", raising=False)
    assert ocr_parser.TesseractOCRParser().lang == "rus+eng"


@pytest.fixture
def ocr_temp_root(tmp_path, monkeypatch):
    root = tmp_path / "OCR кириллица с пробелами"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


def _tracked_image(monkeypatch):
    from PIL import Image

    source = Image.new("RGBA", (40, 20), (255, 255, 255, 255))
    convert = source.convert
    copies = []

    def tracked_convert(*args, **kwargs):
        result = convert(*args, **kwargs)
        copies.append(result)
        return result

    monkeypatch.setattr(source, "convert", tracked_convert)
    return source, copies


def _check_saved_png(cmd, root):
    from PIL import Image

    path = Path(cmd[1])
    assert path.is_relative_to(root)
    assert path.suffix == ".png"
    with Image.open(path) as saved:
        saved.load()
        assert saved.mode == "RGB"
        assert saved.size == (40, 20)
        assert saved.getpixel((0, 0)) == (255, 255, 255)
    return path


def _check_cleanup(source, copies, path, root):
    assert not path.exists()
    assert not path.parent.exists()
    assert list(root.iterdir()) == []
    assert source.mode == "RGBA"
    assert source.getpixel((0, 0)) == (255, 255, 255, 255)
    assert len(copies) == 1
    with pytest.raises(ValueError, match="closed image"):
        copies[0].getpixel((0, 0))


def test_tesseract_ocr_page(monkeypatch, ocr_temp_root):
    captured = {}

    def fake_run(cmd, capture_output, timeout):
        captured["cmd"] = cmd
        captured["path"] = _check_saved_png(cmd, ocr_temp_root)
        assert capture_output is True
        assert timeout == 17.5
        return types.SimpleNamespace(stdout="АКТ № 5 от 8 ноября 2023\n".encode("utf-8"))

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("RAG_OCR_TESSERACT_TIMEOUT", "17.5")
    monkeypatch.setenv("RAG_OCR_TESSERACT_PSM", "6")
    p = ocr_parser.TesseractOCRParser(lang="rus+eng", binary="fake-tesseract")
    source, copies = _tracked_image(monkeypatch)
    txt = p.ocr_page(source)
    assert "АКТ" in txt and "2023" in txt
    assert captured["cmd"] == ["fake-tesseract", str(captured["path"]), "stdout", "-l", "rus+eng", "--psm", "6"]
    _check_cleanup(source, copies, captured["path"], ocr_temp_root)
    source.close()


@pytest.mark.parametrize("failure", ["missing", "timeout"])
def test_tesseract_missing_binary_soft(monkeypatch, ocr_temp_root, failure):
    captured = {}

    def boom(cmd, capture_output, timeout):
        captured["path"] = _check_saved_png(cmd, ocr_temp_root)
        if failure == "missing":
            raise FileNotFoundError("no tesseract")
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(subprocess, "run", boom)
    source, copies = _tracked_image(monkeypatch)
    # мягкая деградация: нет бинаря → пустая строка, не падение
    assert ocr_parser.TesseractOCRParser(binary="fake-tesseract").ocr_page(source) == ""
    _check_cleanup(source, copies, captured["path"], ocr_temp_root)
    source.close()
