"""Проверки расширенной поддержки форматов котельной (doc/xlsm/image/p7m) + скоринг бенча.

Без внешних файлов и без тяжёлых OCR-вызовов — только конфигурация пайплайнов и чистая логика.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from backend.ocr_parser import OCRProcessingError


def test_converter_supported_extended():
    conv = importlib.import_module("backend.converter")
    for ext in (".xlsm", ".p7m", ".jpg", ".jpeg", ".png", ".tif", ".tiff"):
        assert ext in conv.SUPPORTED, ext
    assert conv.IMAGE_SUFFIXES <= conv.SUPPORTED


def test_intake_gate_extended():
    si = importlib.import_module("backend.smart_index")
    for ext in (".xlsm", ".p7m", ".jpg", ".png", ".tiff"):
        assert ext in si.SUPPORTED_SUFFIXES, ext
    # мусор САПР по-прежнему отклоняется
    for ext in (".dwg", ".bak", ".dwl", ".log"):
        assert ext not in si.SUPPORTED_SUFFIXES, ext


def test_router_groups_extended():
    dr = importlib.import_module("backend.document_router")
    assert ".xlsm" in dr.TABLE_SUFFIXES
    assert ".p7m" in dr.PDF_SUFFIXES
    assert ".jpg" in dr.IMAGE_SUFFIXES and ".png" in dr.IMAGE_SUFFIXES


def test_image_ocr_disabled_returns_none(monkeypatch, tmp_path):
    conv = importlib.import_module("backend.converter")
    monkeypatch.setenv("RAG_OCR_ENABLED", "false")
    img = tmp_path / "x.jpg"
    img.write_bytes(b"\xff\xd8\xff")  # не настоящий jpeg, но ветка выйдет раньше по флагу
    assert conv._parse_image_ocr(img) is None


@pytest.mark.parametrize(
    ("ocr_enabled", "parser_factory", "expected_code"),
    [
        ("false", None, "ocr_required_disabled"),
        (
            "true",
            lambda: type(
                "FailingParser",
                (),
                {"parse_pdf": lambda self, *_args, **_kwargs: (_ for _ in ()).throw(
                    OCRProcessingError("tesseract_failed")
                )},
            )(),
            "tesseract_failed",
        ),
        (
            "true",
            lambda: type("BlankParser", (), {"parse_pdf": lambda self, *_args, **_kwargs: ""})(),
            "ocr_required_no_searchable_text",
        ),
    ],
)
def test_explicit_ocr_route_fails_closed_without_pdf_fallback(
    monkeypatch, tmp_path, ocr_enabled, parser_factory, expected_code
):
    conv = importlib.import_module("backend.converter")
    monkeypatch.setenv("RAG_OCR_ENABLED", ocr_enabled)
    monkeypatch.setenv("RAG_PDF_PARSER", "docling")
    monkeypatch.setattr(conv, "_docling_pdf_markdown", lambda *_args, **_kwargs: pytest.fail(
        "explicit OCR must not call Docling fallback"
    ))
    monkeypatch.setitem(sys.modules, "pymupdf4llm", ModuleType("pymupdf4llm"))
    sys.modules["pymupdf4llm"].to_markdown = lambda *_args, **_kwargs: pytest.fail(
        "explicit OCR must not call pymupdf fallback"
    )
    if parser_factory is not None:
        monkeypatch.setattr("backend.ocr_parser.make_ocr_parser", parser_factory)

    route = SimpleNamespace(pipeline="markdown_needs_ocr")
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-1.7\n")
    with pytest.raises(conv.OCRRequiredError) as raised:
        conv._parse_pdf(source, route=route)

    assert raised.value.code == expected_code


def test_explicit_ocr_route_uses_300_dpi_without_environment_override(monkeypatch, tmp_path):
    conv = importlib.import_module("backend.converter")
    seen = {}

    class Parser:
        def parse_pdf(self, _path, *, dpi):
            seen["dpi"] = dpi
            return "searchable OCR evidence"

    monkeypatch.delenv("RAG_OCR_DPI", raising=False)
    monkeypatch.setenv("RAG_OCR_ENABLED", "true")
    monkeypatch.setattr("backend.ocr_parser.make_ocr_parser", lambda: Parser())

    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-1.7\n")
    assert conv._parse_pdf(
        source, route=SimpleNamespace(pipeline="markdown_needs_ocr")
    ) == "searchable OCR evidence"
    assert seen["dpi"] == 300


class _SparseTextPdf:
    page_count = 1

    def __init__(self, text="x"):
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def __getitem__(self, _index):
        return SimpleNamespace(get_text=lambda *_args, **_kwargs: self.text)

    def __iter__(self):
        return iter([self[0]])

    def close(self):
        return None


def _install_sparse_text_pdf(monkeypatch, *, fitz_text="x", pymupdf_text=""):
    monkeypatch.setitem(sys.modules, "fitz", ModuleType("fitz"))
    sys.modules["fitz"].open = lambda *_args, **_kwargs: _SparseTextPdf(fitz_text)
    monkeypatch.setitem(sys.modules, "pymupdf4llm", ModuleType("pymupdf4llm"))
    sys.modules["pymupdf4llm"].to_markdown = lambda *_args, **_kwargs: pymupdf_text


def test_sparse_fitz_probe_requires_ocr_when_ocr_is_disabled(monkeypatch, tmp_path):
    conv = importlib.import_module("backend.converter")
    source = tmp_path / "sparse.pdf"
    source.write_bytes(b"%PDF-1.7\n")
    _install_sparse_text_pdf(monkeypatch, pymupdf_text="plausible garbage " * 20)
    monkeypatch.setenv("RAG_OCR_ENABLED", "false")
    monkeypatch.setenv("RAG_PDF_PARSER", "pymupdf")
    monkeypatch.setenv("LES_LAYOUT_PDF", "false")

    with pytest.raises(conv.OCRRequiredError) as raised:
        conv._parse_pdf(source, route=SimpleNamespace(pipeline="markdown"))

    assert raised.value.code == "ocr_required_disabled"


def test_short_pymupdf_text_requires_ocr_when_ocr_is_disabled(monkeypatch, tmp_path):
    conv = importlib.import_module("backend.converter")
    source = tmp_path / "short-markdown.pdf"
    source.write_bytes(b"%PDF-1.7\n")
    _install_sparse_text_pdf(
        monkeypatch,
        fitz_text="verified source text " * 10,
        pymupdf_text="x",
    )
    monkeypatch.setenv("RAG_OCR_ENABLED", "false")
    monkeypatch.setenv("RAG_PDF_PARSER", "pymupdf")
    monkeypatch.setenv("LES_LAYOUT_PDF", "false")

    with pytest.raises(conv.OCRRequiredError) as raised:
        conv._parse_pdf(source, route=SimpleNamespace(pipeline="markdown"))

    assert raised.value.code == "ocr_required_disabled"


@pytest.mark.parametrize(
    ("ocr_enabled", "ocr_result", "expected_code"),
    [
        ("false", None, "ocr_required_disabled"),
        ("true", "", "ocr_required_no_searchable_text"),
        ("true", "## Стр. 1\n\n", "ocr_required_no_searchable_text"),
        ("true", OCRProcessingError("tesseract_timeout"), "tesseract_timeout"),
    ],
)
def test_sparse_text_pdf_dynamic_ocr_fails_closed(
    monkeypatch, tmp_path, ocr_enabled, ocr_result, expected_code
):
    conv = importlib.import_module("backend.converter")
    source = tmp_path / "sparse.pdf"
    source.write_bytes(b"%PDF-1.7\n")
    _install_sparse_text_pdf(monkeypatch)
    monkeypatch.setenv("RAG_OCR_ENABLED", ocr_enabled)
    monkeypatch.setenv("RAG_PDF_PARSER", "pymupdf")
    monkeypatch.setenv("LES_LAYOUT_PDF", "false")

    def parse_pdf(*_args, **_kwargs):
        if isinstance(ocr_result, Exception):
            raise ocr_result
        return ocr_result

    if ocr_enabled == "true":
        monkeypatch.setattr(
            "backend.ocr_parser.make_ocr_parser",
            lambda: SimpleNamespace(parse_pdf=parse_pdf),
        )

    with pytest.raises(conv.OCRRequiredError) as raised:
        conv._parse_pdf(source, route=SimpleNamespace(pipeline="markdown"))

    assert raised.value.code == expected_code


def test_sparse_text_p7m_dynamic_ocr_failure_is_not_a_warning(monkeypatch, tmp_path):
    import shutil
    import subprocess

    conv = importlib.import_module("backend.converter")
    signed = tmp_path / "sparse.pdf.p7m"
    signed.write_bytes(b"signed placeholder")
    _install_sparse_text_pdf(monkeypatch)
    monkeypatch.setenv("RAG_OCR_ENABLED", "true")
    monkeypatch.setattr(shutil, "which", lambda _name: "openssl")

    def unpack(command, **_kwargs):
        Path(command[command.index("-out") + 1]).write_bytes(b"%PDF-1.7\n")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", unpack)
    monkeypatch.setattr(
        "backend.ocr_parser.make_ocr_parser",
        lambda: SimpleNamespace(
            parse_pdf=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OCRProcessingError("ollama_vision_failed")
            )
        ),
    )

    with pytest.raises(conv.OCRRequiredError) as raised:
        conv._parse_p7m(signed, route=SimpleNamespace(pipeline="markdown"))

    assert raised.value.code == "ollama_vision_failed"


@pytest.mark.parametrize(
    ("backend", "expected_code"),
    [("ollama", "ollama_vision_failed"), ("mlx", "mlx_vision_load_failed")],
)
def test_explicit_visual_ocr_failure_is_typed_not_searchable_text(
    monkeypatch, tmp_path, backend, expected_code
):
    from PIL import Image
    from backend import ocr_parser

    conv = importlib.import_module("backend.converter")
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-1.7\n")
    monkeypatch.setenv("RAG_OCR_ENABLED", "true")
    monkeypatch.setenv("RAG_OCR_BACKEND", backend)
    monkeypatch.setattr(ocr_parser, "render_pdf_to_images", lambda *_args, **_kwargs: [Image.new("RGB", (8, 8))])
    if backend == "ollama":
        import httpx

        monkeypatch.setattr(
            httpx,
            "post",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("http://private-host secret")),
        )
    else:
        monkeypatch.setattr(
            ocr_parser.MLXVisualOCRParser,
            "load_model",
            lambda self: (_ for _ in ()).throw(RuntimeError("C:/secret/model")),
        )
        monkeypatch.setattr(ocr_parser.MLXVisualOCRParser, "unload_model", lambda self: None)

    with pytest.raises(conv.OCRRequiredError) as raised:
        conv._parse_pdf(source, route=SimpleNamespace(pipeline="markdown_needs_ocr"))
    assert raised.value.code == expected_code
    assert "private-host" not in str(raised.value)
    assert "secret" not in str(raised.value)


@pytest.mark.parametrize("backend", ["ollama", "mlx"])
def test_explicit_visual_ocr_empty_page_heading_is_not_evidence(monkeypatch, tmp_path, backend):
    from PIL import Image
    from backend import ocr_parser

    conv = importlib.import_module("backend.converter")
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-1.7\n")
    parser = (
        ocr_parser.OllamaVisualOCRParser()
        if backend == "ollama"
        else ocr_parser.MLXVisualOCRParser()
    )
    if backend == "ollama":
        monkeypatch.setattr(ocr_parser, "render_pdf_to_images", lambda *_args, **_kwargs: [Image.new("RGB", (8, 8))])
    else:
        monkeypatch.setattr(parser, "pdf_to_images", lambda *_args, **_kwargs: [Image.new("RGB", (8, 8))])
        monkeypatch.setattr(parser, "unload_model", lambda: None)
    monkeypatch.setattr(parser, "ocr_page", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(ocr_parser, "make_ocr_parser", lambda: parser)
    monkeypatch.setenv("RAG_OCR_ENABLED", "true")

    with pytest.raises(conv.OCRRequiredError) as raised:
        conv._parse_pdf(source, route=SimpleNamespace(pipeline="markdown_needs_ocr"))

    assert raised.value.code == "ocr_required_no_searchable_text"


# ── скоринг бенча ──

def test_bench_score_multiset():
    bench = importlib.import_module("tools.asbuilt_ocr_bench")
    # два «1003» в эталоне — оба должны зачесться; лишний 999 — в spurious
    matched, expected, spurious = bench._score([1003, 1003, 14], [1003, 1003, 999])
    assert matched == 2 and expected == 3 and spurious == 1


def test_bench_sheet_key():
    bench = importlib.import_module("tools.asbuilt_ocr_bench")
    assert bench._sheet_key("МФЗ_Б4_АУПС_L5_ОП_ОКЛ") == "ОП"
    assert bench._sheet_key("МФЗ_Б4_СОУЭ_L5_РО_ОКЛ") == "РО"
    assert bench._sheet_key("случайное") is None


def test_bench_ground_truth_shape():
    bench = importlib.import_module("tools.asbuilt_ocr_bench")
    assert set(bench.GROUND_TRUTH) == {"ОП", "ПП", "РО", "СО"}
    assert bench.GROUND_TRUTH["ОП"].count(1003) == 2  # кабель + труба
