"""W1.3: PDF-препроцессор — тест-план спеки 2026-06-07 + правки Приложения А."""

import json
from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")

from tools.pdf_preprocess import (
    ARCHIVE_DIRNAME,
    STATE_FILE,
    CleanResult,
    clean_pdf,
    main,
    preprocess_dir,
    split_pdf,
)


def _entropy_line(seed: str) -> str:
    """Детерминированная несжимаемая строка (~128 симв.) — deflate её не схлопнет."""
    import hashlib

    return hashlib.sha256(seed.encode()).hexdigest() + hashlib.sha256((seed + "x").encode()).hexdigest()


def _make_pdf(path: Path, pages: int = 3, page_kb: int = 0, toc: list | None = None) -> Path:
    """PDF c заданным числом страниц; page_kb добавляет несжимаемое содержимое на страницу."""
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((40, 50), f"Лист {i + 1}")
        for k in range(page_kb * 8):  # 8 строк по ~128 несжимаемых символов ≈ 1KB
            page.insert_text((40, 60 + (k % 95) * 8), _entropy_line(f"{path.name}:{i}:{k}"), fontsize=5)
    if toc:
        doc.set_toc(toc)
    doc.save(path, deflate=False)
    doc.close()
    return path


# ── clean_pdf ──

def test_clean_pdf_reduces_or_equals_size(tmp_path):
    pdf = _make_pdf(tmp_path / "a.pdf", pages=4, page_kb=20)
    before = pdf.stat().st_size
    result = clean_pdf(pdf)
    assert isinstance(result, CleanResult)
    assert result.new_bytes <= before


def test_clean_pdf_stays_valid_and_preserves_page_count(tmp_path):
    pdf = _make_pdf(tmp_path / "a.pdf", pages=5)
    clean_pdf(pdf)
    doc = fitz.open(pdf)
    assert doc.page_count == 5
    doc.close()


def test_clean_pdf_archives_original(tmp_path):
    pdf = _make_pdf(tmp_path / "a.pdf", pages=2)
    original_bytes = pdf.read_bytes()
    clean_pdf(pdf, archive_dir=tmp_path / ARCHIVE_DIRNAME)
    backup = tmp_path / ARCHIVE_DIRNAME / "a.pdf"
    assert backup.exists() and backup.read_bytes() == original_bytes


# ── split_pdf ──

def _big_pdf(tmp_path: Path, pages: int = 12, page_kb: int = 30, **kw) -> Path:
    return _make_pdf(tmp_path / "big.pdf", pages=pages, page_kb=page_kb, **kw)


def test_split_creates_parts_under_threshold_and_valid(tmp_path):
    pdf = _big_pdf(tmp_path)
    max_bytes = pdf.stat().st_size // 3
    result = split_pdf(pdf, max_bytes=max_bytes, archive_dir=tmp_path / ARCHIVE_DIRNAME)
    assert len(result.parts) >= 2
    total_pages = 0
    for part in result.parts:
        assert part.stat().st_size <= max_bytes * 1.15  # допуск на оверхед структуры
        doc = fitz.open(part)
        total_pages += doc.page_count
        doc.close()
    assert total_pages == 12
    assert "_часть1" in result.parts[0].name


def test_split_archives_original_by_default(tmp_path):
    pdf = _big_pdf(tmp_path)
    split_pdf(pdf, max_bytes=pdf.stat().st_size // 2, archive_dir=tmp_path / ARCHIVE_DIRNAME)
    assert not pdf.exists()
    assert (tmp_path / ARCHIVE_DIRNAME / "big.pdf").exists()


def test_split_deletes_original_only_with_flag(tmp_path):
    pdf = _big_pdf(tmp_path)
    split_pdf(pdf, max_bytes=pdf.stat().st_size // 2, archive_dir=tmp_path / ARCHIVE_DIRNAME, delete_original=True)
    assert not pdf.exists()
    assert not (tmp_path / ARCHIVE_DIRNAME / "big.pdf").exists()


def test_split_parts_carry_metadata(tmp_path):
    pdf = _big_pdf(tmp_path)
    result = split_pdf(pdf, max_bytes=pdf.stat().st_size // 2, archive_dir=tmp_path / ARCHIVE_DIRNAME)
    doc = fitz.open(result.parts[0])
    meta = json.loads(doc.metadata.get("subject") or "{}")
    doc.close()
    assert meta["part_index"] == 1
    assert meta["part_total"] == len(result.parts)
    assert meta["original_name"] == "big.pdf"


def test_split_prefers_toc_boundaries(tmp_path):
    # Закладки на страницах 1 и 7 (1-based); ровно 2 части → граница 6 совпадает с закладкой.
    pdf = _big_pdf(tmp_path, toc=[[1, "Раздел 1", 1], [1, "Раздел 2", 7]])
    doc = fitz.open(pdf)
    recompressed = len(doc.tobytes(garbage=2, deflate=True))
    doc.close()
    max_bytes = int(recompressed * 0.6)  # ceil(total / 0.9*max) == 2 части
    result = split_pdf(pdf, max_bytes=max_bytes, archive_dir=tmp_path / ARCHIVE_DIRNAME)
    assert len(result.parts) == 2
    doc = fitz.open(result.parts[0])
    first_part_pages = doc.page_count
    doc.close()
    assert first_part_pages == 6  # 0-based граница 6 = страница закладки «Раздел 2»


def test_split_rollback_on_write_failure(tmp_path, monkeypatch):
    pdf = _big_pdf(tmp_path)
    original_bytes = pdf.read_bytes()

    import tools.pdf_preprocess as pp

    calls = {"n": 0}
    real_write = pp._write_part

    def failing_write(doc, start, end, out_path, *a, **kw):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise OSError("disk full")
        return real_write(doc, start, end, out_path, *a, **kw)

    monkeypatch.setattr(pp, "_write_part", failing_write)
    with pytest.raises(OSError):
        split_pdf(pdf, max_bytes=pdf.stat().st_size // 3, archive_dir=tmp_path / ARCHIVE_DIRNAME)
    assert pdf.exists() and pdf.read_bytes() == original_bytes
    assert not list(tmp_path.glob("*_часть*.pdf"))


# ── preprocess_dir ──

def test_preprocess_dir_small_file_only_cleans(tmp_path):
    _make_pdf(tmp_path / "small.pdf", pages=2)
    results = preprocess_dir(tmp_path, max_bytes=10 * 2**20)
    assert [r.action for r in results] == ["clean"]


def test_preprocess_dir_large_file_cleans_and_splits(tmp_path):
    _big_pdf(tmp_path)
    # Порог заведомо меньше размера после очистки → обязателен сплит.
    results = preprocess_dir(tmp_path, max_bytes=20_000)
    actions = {r.action for r in results}
    assert "clean+split" in actions
    assert list(tmp_path.glob("big_часть*.pdf"))


def test_preprocess_dir_skips_corrupt_pdf_continues_others(tmp_path):
    (tmp_path / "bad.pdf").write_bytes(b"not a pdf at all")
    _make_pdf(tmp_path / "good.pdf", pages=2)
    results = {r.path.name: r.action for r in preprocess_dir(tmp_path, max_bytes=10 * 2**20)}
    assert results["bad.pdf"] == "error"
    assert results["good.pdf"] == "clean"


def test_preprocess_dir_idempotent_via_state(tmp_path):
    _make_pdf(tmp_path / "a.pdf", pages=2)
    first = preprocess_dir(tmp_path, max_bytes=10 * 2**20)
    assert first[0].action == "clean"
    assert (tmp_path / STATE_FILE).exists()
    second = preprocess_dir(tmp_path, max_bytes=10 * 2**20)
    assert [r.action for r in second if r.path.name == "a.pdf"] == ["skip"]


def test_preprocess_dir_reprocesses_changed_file(tmp_path):
    pdf = _make_pdf(tmp_path / "a.pdf", pages=2)
    preprocess_dir(tmp_path, max_bytes=10 * 2**20)
    _make_pdf(pdf, pages=3)  # файл изменился
    results = {r.path.name: r.action for r in preprocess_dir(tmp_path, max_bytes=10 * 2**20)}
    assert results["a.pdf"] == "clean"


def test_preprocess_dir_dry_run_touches_nothing(tmp_path):
    pdf = _make_pdf(tmp_path / "a.pdf", pages=2)
    before = pdf.read_bytes()
    preprocess_dir(tmp_path, max_bytes=10 * 2**20, dry_run=True)
    assert pdf.read_bytes() == before
    assert not (tmp_path / STATE_FILE).exists()
    assert not (tmp_path / ARCHIVE_DIRNAME).exists()


# ── CLI ──

def test_cli_exit_1_on_missing_dir(tmp_path):
    assert main([str(tmp_path / "nope")]) == 1


def test_cli_exit_2_on_partial_errors(tmp_path):
    (tmp_path / "bad.pdf").write_bytes(b"garbage")
    _make_pdf(tmp_path / "good.pdf", pages=2)
    assert main([str(tmp_path)]) == 2


def test_cli_exit_0_clean_run(tmp_path):
    _make_pdf(tmp_path / "good.pdf", pages=2)
    assert main([str(tmp_path), "--max-mb", "10"]) == 0


def test_clean_pdf_keeps_original_when_inflated(tmp_path, monkeypatch):
    """Очистка, раздувшая файл (перекодирование картинок), не сохраняется."""
    pdf = _make_pdf(tmp_path / "a.pdf", pages=2)
    original = pdf.read_bytes()

    import fitz as _fitz
    import tools.pdf_preprocess as pp

    real_open = _fitz.open

    class InflatingDoc:
        def __init__(self, doc):
            self._doc = doc

        def save(self, path, **kw):
            self._doc.save(path)
            with open(path, "ab") as fh:
                fh.write(b"%" + b"x" * (len(original) * 2))  # раздуваем

        def close(self):
            self._doc.close()

    monkeypatch.setattr(pp, "fitz", None, raising=False)
    import builtins
    orig_import = builtins.__import__

    def fake_import(name, *a, **kw):
        module = orig_import(name, *a, **kw)
        return module

    result = None
    monkeypatch.setattr(_fitz, "open", lambda p: InflatingDoc(real_open(p)))
    try:
        result = pp.clean_pdf(pdf)
    finally:
        monkeypatch.setattr(_fitz, "open", real_open)
    assert pdf.read_bytes() == original  # файл не тронут
    assert result.new_bytes == result.original_bytes
