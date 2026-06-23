"""КАЦ из PDF-КП: извлечение котировок из текстового слоя PDF → стыковка с analyze_kac.

Фикстуры — синтетические PDF с ТЕКСТОВЫМ слоем, генерим на лету через pymupdf (fitz),
чтобы не тащить бинарные сэмплы в репозиторий и не зависеть от reportlab. OCR-путь
(скан без текста) здесь не гоняем — он зовёт бинарь Tesseract и тяжёлый рендер; тут
проверяем детерминированное regex-ядро на текстовом слое.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from proxy.services import kac_pdf_service as kps

fitz = pytest.importorskip("fitz", reason="pymupdf нужен для генерации PDF-фикстур")


def _make_pdf(path: Path, lines: list[str]) -> Path:
    """Список текстовых строк → одностраничный PDF с текстовым слоем."""
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=11, fontname="helv")
        y += 18
    doc.save(str(path))
    doc.close()
    return path


# Кириллица в helv-шрифте fitz не отрисуется в текстовый слой как кириллица,
# поэтому материалы пишем латиницей/цифрами — для regex-ядра важна СТРУКТУРА
# (текст + цена + единица), а не язык. Единицы — латинские эквиваленты (m2, sht).
def _kp_lines(supplier: str, rows: list[tuple[str, str, str]]) -> list[str]:
    head = [
        "Kommercheskoe predlozhenie",
        f"Postavshchik: {supplier}",
        "Naimenovanie                 Ed.izm   Cena",
    ]
    body = [f"{name}    {unit}   {price}" for name, unit, price in rows]
    tail = ["Itogo: 999999 rub"]
    return head + body + tail


@pytest.fixture
def kp_pdfs(tmp_path: Path) -> list[Path]:
    """Три КП на один материал (Granit) + один материал у части КП (Setka)."""
    p1 = _make_pdf(tmp_path / "KP_GranitInvest.pdf", _kp_lines(
        "GranitInvest", [("Granit seryy 600x300x30", "m2", "2 450"),
                         ("Setka svarnaya 50x50", "m2", "410")]))
    p2 = _make_pdf(tmp_path / "KP_LEV.pdf", _kp_lines(
        "LEV", [("Granit seryy 600x300x30", "m2", "2 300")]))
    p3 = _make_pdf(tmp_path / "KP_ProfStroy.pdf", _kp_lines(
        "ProfStroy", [("Granit seryy 600x300x30", "m2", "2 520")]))
    return [p1, p2, p3]


def test_extract_offers_text_layer(kp_pdfs):
    offers = kps.extract_offers(kp_pdfs[0], use_ocr=False)
    assert offers, "из текстового слоя должны извлечься предложения"
    # Поставщик прочитан из шапки «Postavshchik: …».
    assert all(o["supplier"] == "GranitInvest" for o in offers)
    assert all(o["source"] == "KP_GranitInvest.pdf" for o in offers)
    granit = next(o for o in offers if "Granit" in o["material"])
    assert granit["price"] == 2450.0          # «2 450» → 2450.0 (пробел-разделитель)
    assert granit["unit"] == "m2"
    assert granit["currency"] == "RUB"
    # Служебная строка «Itogo» не попала в материалы.
    assert not any("Itogo" in o["material"] or "itogo" in o["material"].lower() for o in offers)


def test_supplier_from_filename_fallback(tmp_path: Path):
    # КП без явной шапки «Postavshchik:» → поставщик из имени файла.
    p = _make_pdf(tmp_path / "KP_BVB_2024.pdf", [
        "Naimenovanie   Ed   Cena",
        "Setka svarnaya 50x50   m2   395",
    ])
    offers = kps.extract_offers(p, use_ocr=False)
    assert offers
    assert offers[0]["supplier"] == "BVB"     # «КП_BVB_2024» → «BVB» (служ. токены/цифры срезаны)


def test_explicit_supplier_arg_wins(kp_pdfs):
    offers = kps.extract_offers(kp_pdfs[0], supplier="ЯвныйПоставщик", use_ocr=False)
    assert all(o["supplier"] == "ЯвныйПоставщик" for o in offers)


def test_extract_and_analyze_picks_economical(kp_pdfs):
    """3 КП на Granit → analyze_kac выбирает экономичный (2300, LEV)."""
    res = kps.extract_and_analyze(kp_pdfs, min_suppliers=3, strategy="min", use_ocr=False)

    # Диагностика извлечения.
    assert res["extraction"]["files"] == 3
    assert res["extraction"]["total_offers"] >= 4   # 3×Granit + ≥1 Setka

    granit = next(m for m in res["materials"] if "Granit" in m["material"])
    assert granit["suppliers"] == 3                 # три поставщика → достаточно
    assert granit["sufficient"] is True
    assert granit["chosen_price"] == 2300.0         # ЭКОНОМИЧНЫЙ выбран
    assert granit["chosen_supplier"] == "LEV"
    assert granit["chosen_source"] == "KP_LEV.pdf"

    # Setka — только у одного КП → недостаточно для КАЦ.
    setka = next(m for m in res["materials"] if "Setka" in m["material"])
    assert setka["sufficient"] is False


def test_lsr_lines_from_pdf_kac(kp_pdfs):
    """Сквозной путь: PDF → КАЦ → линии для ЛСР (неучтённый материал)."""
    from proxy.services import kac_service

    res = kps.extract_and_analyze(kp_pdfs, min_suppliers=3, use_ocr=False)
    lines = kac_service.kac_to_lsr_lines(res)
    granit = next(line for line in lines if "Granit" in line["name"])
    assert granit["price"] == 2300.0
    assert granit["supplier"] == "LEV"
    assert granit["basis"].startswith("КАЦ")


def test_price_parsing_formats():
    """Регрессия на форматы цены: пробелы/запятые/точки."""
    assert kps._parse_price("2 300") == 2300.0
    assert kps._parse_price("1 234,56") == 1234.56
    assert kps._parse_price("1.234,56") == 1234.56     # рус. формат: точка тысячная
    assert kps._parse_price("1234.56") == 1234.56
    assert kps._parse_price("abc") is None


def test_line_to_offer_skips_noise():
    assert kps._line_to_offer("Itogo: 999999 rub") is None
    assert kps._line_to_offer("Naimenovanie Ed.izm Cena") is None   # заголовок без цифр
    off = kps._line_to_offer("Kirpich keramicheskiy   sht   18,50")
    assert off and off["price"] == 18.5 and off["unit"] == "sht"


def test_unit_normalization():
    assert kps._find_unit("ploshchad 5 кв.м") == "м2"
    assert kps._find_unit("obem 3 куб.м") == "м3"


def test_material_with_embedded_digits_not_truncated():
    """Имена с цифрами внутри (DN50, 600x300x30, M150) НЕ режутся по первой цифре."""
    o = kps._line_to_offer("Truba stalnaya DN50  m  1 200")
    assert o["material"] == "Truba stalnaya DN50" and o["price"] == 1200.0
    o = kps._line_to_offer("Granit seryy 600x300x30 m2 2 450")
    assert o["material"] == "Granit seryy 600x300x30" and o["price"] == 2450.0 and o["unit"] == "m2"
    # «rub» внутри «Truba» — не валюта; «m» в «M150» — не единица.
    o = kps._line_to_offer("Kirpich M150 sht 18,50")
    assert o["material"] == "Kirpich M150" and o["unit"] == "sht"


def test_ocr_fallback_wired_when_text_layer_empty(tmp_path, monkeypatch):
    """Скан без текстового слоя → дергается OCR-фолбэк (изолированный Tesseract)."""
    # PDF-страница без текста (пустая) — текстовый слой даст 0 предложений.
    blank = _make_pdf(tmp_path / "scan.pdf", [])

    called = {"n": 0}

    def fake_ocr(path):
        called["n"] += 1
        return ([{"material": "Profnastil S8", "unit": "m2", "price": 520.0, "currency": "RUB"}],
                "Profnastil S8 m2 520")

    monkeypatch.setattr(kps, "_extract_via_ocr", fake_ocr)
    offers = kps.extract_offers(blank, supplier="OCRPostavshchik", use_ocr=True)
    assert called["n"] == 1                       # OCR-путь действительно вызван
    assert offers and offers[0]["material"] == "Profnastil S8"
    assert offers[0]["supplier"] == "OCRPostavshchik"
    assert offers[0]["source"] == "scan.pdf"


def test_ocr_degrades_gracefully_when_unavailable():
    """Если TesseractOCRParser недоступен — фолбэк тихо возвращает ([], '')."""
    offers, text = kps._extract_via_ocr("/nope/does-not-exist.pdf")
    assert offers == [] and text == ""


def test_docstring_mentions_isolation():
    # Гарантия по памяти: OCR изолирован (subprocess-бинарь), не через venv-pytesseract.
    assert "ИЗОЛИР" in kps.__doc__.upper()
    src = textwrap.dedent(Path(kps.__file__).read_text(encoding="utf-8"))
    assert "pytesseract" not in src   # OCR только через бинарь, не Python-обёртку
