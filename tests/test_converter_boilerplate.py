"""Чистка колонтитулов правовых систем (кейс Постановления 87)."""

from backend.converter import normalize_pdf_text, strip_legal_boilerplate


def test_strips_consultant_header_lines():
    md = "## **КонсультантПлюс**\n\n**www.consultant.ru**\n\nСтраница 31 из 49\n\n**надежная правовая поддержка**\n\n9. Проектная документация состоит из разделов."
    out = strip_legal_boilerplate(md)
    assert "КонсультантПлюс" not in out
    assert "consultant.ru" not in out
    assert "Страница 31" not in out
    assert "Проектная документация состоит" in out


def test_keeps_normal_text_with_page_words():
    md = "На странице чертежа указано 5 элементов из 49 позиций."
    assert strip_legal_boilerplate(md) == md


def test_repairs_windows_utf8_latin1_pdf_mojibake():
    broken = "ÐÐ»Ð°Ð½ Ð¦ÐÐ. 4 ÑÑÐ°Ð¶ · Ð©Ð4.18 · 1600Ð"
    assert normalize_pdf_text(broken) == "План ЦОД. 4 этаж · ЩБ4.18 · 1600А"


def test_keeps_valid_cyrillic_pdf_text():
    valid = "План ЦОД. 4 этаж · ЩБ4.18 · 1600А"
    assert normalize_pdf_text(valid) == valid
