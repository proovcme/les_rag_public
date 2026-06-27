"""Проверки расширенной поддержки форматов котельной (doc/xlsm/image/p7m) + скоринг бенча.

Без внешних файлов и без тяжёлых OCR-вызовов — только конфигурация пайплайнов и чистая логика.
"""
from __future__ import annotations

import importlib

import pytest


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
