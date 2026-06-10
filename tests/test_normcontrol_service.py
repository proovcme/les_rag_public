"""W13.1: формальный нормоконтроль — офлайн-тесты на синтетических PDF, без LLM."""

from pathlib import Path

import pytest

from backend.parquet_writer import save_parquet
from proxy.services.normcontrol_service import (
    check_cipher_consistency,
    check_pdf_sheets,
    check_vedomost_vs_files,
    classify_format,
    extract_cipher,
    run_normcontrol,
)

fitz = pytest.importorskip("fitz")

MM_TO_PT = 72.0 / 25.4


def _make_pdf(path: Path, width_mm: float = 210, height_mm: float = 297, text: str = "Лист 1 — содержимое чертежа основного комплекта"):
    doc = fitz.open()
    page = doc.new_page(width=width_mm * MM_TO_PT, height=height_mm * MM_TO_PT)
    if text:
        page.insert_text((40, 40), text, fontsize=11)
    doc.save(path)
    doc.close()


# ── NK-01 форматы ──

def test_classify_format_base_and_rotated():
    assert classify_format(210, 297) == "А4"
    assert classify_format(297, 210) == "А4"
    assert classify_format(594, 841) == "А1"


def test_classify_format_multiples_and_unknown():
    assert classify_format(297, 630) == "А4×3"   # кратный по ГОСТ 2.301
    assert classify_format(500, 500) is None


def test_check_pdf_sheets_standard_a4_clean(tmp_path):
    pdf = tmp_path / "АТ-РД-ОВ2-Л1.pdf"
    _make_pdf(pdf)
    findings = check_pdf_sheets(pdf)
    assert not [f for f in findings if f.check == "NK-01"]


def test_check_pdf_sheets_nonstandard_format_flagged(tmp_path):
    pdf = tmp_path / "плохой.pdf"
    _make_pdf(pdf, width_mm=500, height_mm=500)
    findings = check_pdf_sheets(pdf)
    nk01 = [f for f in findings if f.check == "NK-01"]
    assert nk01 and nk01[0].severity == "warning"
    assert "500×500" in nk01[0].message


# ── NK-02 текстовый слой ──

def test_check_pdf_sheets_scan_without_text_flagged(tmp_path):
    pdf = tmp_path / "скан.pdf"
    _make_pdf(pdf, text="")
    findings = check_pdf_sheets(pdf)
    nk02 = [f for f in findings if f.check == "NK-02"]
    assert nk02 and "стр.: 1" not in nk02[0].message  # формат сообщения свободный, важен сам факт
    assert nk02[0].severity == "warning"


# ── NK-03 шифры ──

def test_extract_cipher_strips_sheet_segment():
    assert extract_cipher("АТ-РД-ОВ2-С-00-П1.pdf") == "АТ-РД-ОВ2-С-00"


def test_cipher_consistency_single_set_clean():
    findings = check_cipher_consistency(["АТ-РД-ОВ2-С-00-П1.pdf", "АТ-РД-ОВ2-С-00-П2.pdf"])
    assert not [f for f in findings if f.severity == "warning"]


def test_cipher_consistency_foreign_cipher_flagged():
    findings = check_cipher_consistency(
        ["АТ-РД-ОВ2-С-00-П1.pdf", "АТ-РД-ОВ2-С-00-П2.pdf", "ЖК-РД-ЭМ1-С-01-Л1.pdf"]
    )
    warned = [f for f in findings if f.severity == "warning"]
    assert len(warned) == 1 and "ЖК-РД-ЭМ1" in warned[0].message


# ── NK-04 ведомость ↔ состав ──

def _dataset_with_vedomost(tmp_path: Path, dataset_id: str, designations: list[str]) -> Path:
    parquet_dir = tmp_path / dataset_id / "_parquet"
    parquet_dir.mkdir(parents=True)
    rows = [
        {"doc_type": "VEDOMOST", "doc_title": "Ведомость", "source_file": "ved.xlsx",
         "designation": d, "name": f"Лист {i}", "code": "", "unit": "", "qty": None}
        for i, d in enumerate(designations, 1)
    ]
    save_parquet(rows, str(parquet_dir / "ved.parquet"))
    return tmp_path


def test_vedomost_missing_sheet_is_error(tmp_path):
    storage = _dataset_with_vedomost(tmp_path, "ds1", ["АТ-РД-ОВ2-Л1", "АТ-РД-ОВ2-Л2"])
    findings = check_vedomost_vs_files("ds1", ["АТ-РД-ОВ2-Л1.pdf"], storage_root=storage)
    errors = [f for f in findings if f.severity == "error"]
    assert len(errors) == 1 and "Л2" in errors[0].target


def test_vedomost_all_present_clean(tmp_path):
    storage = _dataset_with_vedomost(tmp_path, "ds2", ["АТ-РД-ОВ2-Л1"])
    findings = check_vedomost_vs_files("ds2", ["АТ-РД-ОВ2-Л1.pdf"], storage_root=storage)
    assert not findings


def test_vedomost_absent_gives_info(tmp_path):
    findings = check_vedomost_vs_files("nope", ["x.pdf"], storage_root=tmp_path)
    assert len(findings) == 1 and findings[0].severity == "info"


# ── полный прогон ──

def test_run_normcontrol_end_to_end(tmp_path):
    dataset_dir = tmp_path / "ds3"
    dataset_dir.mkdir(parents=True)
    _make_pdf(dataset_dir / "АТ-РД-ОВ2-С-00-П1.pdf")
    _make_pdf(dataset_dir / "АТ-РД-ОВ2-С-00-П2.pdf", width_mm=500, height_mm=500, text="")
    result = run_normcontrol("ds3", files_dir=dataset_dir, storage_root=tmp_path, output_dir=dataset_dir / "_normcontrol")
    assert result["files_checked"] == 2
    assert result["warnings"] >= 2  # формат + скан
    assert Path(result["xlsx_path"]).exists()
    # severity-сортировка: error раньше warning раньше info
    severities = [f["severity"] for f in result["findings"]]
    assert severities == sorted(severities, key=lambda s: {"error": 0, "warning": 1, "info": 2}[s])


def test_normcontrol_service_uses_no_llm():
    """ADR-11: модуль нормоконтроля не импортирует HTTP/LLM-клиентов."""
    import inspect

    import proxy.services.normcontrol_service as nc

    source = inspect.getsource(nc)
    for marker in ("import httpx", "import openai", "import requests", "/api/chat", "completions"):
        assert marker not in source, f"LLM/HTTP-маркер '{marker}' в normcontrol_service"
