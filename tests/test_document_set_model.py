"""Тест document_set_model (СПДС-нормоконтроль, Phase 2): нормализация комплекта, разбор
обозначения (шифр/марка/недопустимые разделители), сопоставление ведомость ↔ файлы.
Это evidence-слой — факты для RAG-led review, без вынесения review-status."""

from proxy.services.document_set_model import (
    build_document_set,
    match_vedomost,
    parse_designation,
)


def test_parse_designation_marka_and_separators():
    d = parse_designation("2024-15-АР-1.pdf")
    assert d is not None and d.marka == "АР" and d.bad_separators is False
    assert d.base_cipher and d.base_cipher.startswith("2024-15")

    bad = parse_designation("2024 15 ОВ 3.pdf")  # пробелы — недопустимый разделитель
    assert bad is not None and bad.marka == "ОВ" and bad.bad_separators is True


def test_parse_designation_unrecognized():
    assert parse_designation("README.pdf") is None
    assert parse_designation("Письмо.docx") is None


def test_build_document_set():
    ds = build_document_set([
        "2024-15-АР-1.pdf", "2024-15-АР-2.pdf", "2024-15-КР-1.pdf", "README.pdf",
    ])
    assert len(ds.documents) == 4
    assert ds.markas == ["АР", "КР"]
    assert "README.pdf" in ds.unrecognized
    assert ds.main_cipher is not None


def test_build_document_set_accepts_dicts():
    ds = build_document_set([{"file_name": "2024-15-ОВ-1.pdf"}, {"name": "x"}])
    assert any(d.designation and d.designation.marka == "ОВ" for d in ds.documents)


def test_match_vedomost_missing_and_extra():
    ds = build_document_set(["2024-15-АР-1.pdf", "2024-15-АР-2.pdf"])
    ved = [
        {"designation": "2024-15-АР-1", "name": "План"},
        {"designation": "2024-15-АР-9", "name": "Несуществующий лист"},
    ]
    m = match_vedomost(ds, ved)
    assert "2024-15-АР-1" in m.matched
    assert any(x["designation"] == "2024-15-АР-9" for x in m.missing)  # в ведомости есть, файла нет
    assert any("АР-2" in e for e in m.extra)  # файл есть, в ведомости нет


def test_match_vedomost_empty_is_safe():
    ds = build_document_set(["2024-15-АР-1.pdf"])
    m = match_vedomost(ds, [])
    assert m.matched == [] and m.missing == []
