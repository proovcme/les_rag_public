"""Чистка колонтитулов правовых систем (кейс Постановления 87)."""

from backend.converter import strip_legal_boilerplate


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
