from email.message import EmailMessage
from pathlib import Path

from backend import converter
from backend.converter import convert_to_markdown


def test_convert_eml_to_markdown_with_headers_body_and_attachments(tmp_path):
    msg = EmailMessage()
    msg["Subject"] = "Исполнительная документация"
    msg["From"] = "author@example.com"
    msg["To"] = "les@example.com"
    msg["Cc"] = "copy@example.com"
    msg["Date"] = "Sat, 23 May 2026 10:00:00 +0300"
    msg.set_content("Добрый день.\nВо вложении акт и схема.")
    msg.add_attachment(
        b"attachment-content",
        maintype="application",
        subtype="pdf",
        filename="aosr.pdf",
    )
    path = tmp_path / "mail.eml"
    path.write_bytes(msg.as_bytes())

    markdown = convert_to_markdown(path)

    assert markdown is not None
    assert "# Исполнительная документация" in markdown
    assert "От: author@example.com" in markdown
    assert "Кому: les@example.com" in markdown
    assert "Копия: copy@example.com" in markdown
    assert "Во вложении акт и схема." in markdown
    assert "Вложения:" in markdown
    assert "- aosr.pdf" in markdown


def test_book_pdf_uses_larger_character_budget(monkeypatch):
    monkeypatch.setattr(converter, "_pdf_page_count", lambda _path: 596)

    limit = converter._max_file_chars(Path("Рук-во по устройству ЭУ 2019.pdf"))

    assert limit == converter.PDF_MAX_FILE_CHARS


def test_book_pdf_image_extraction_defaults_on(monkeypatch):
    monkeypatch.delenv("PDF_IMAGE_EXTRACTION_ENABLED", raising=False)
    monkeypatch.setattr(converter, "_pdf_page_count", lambda _path: 596)

    assert converter._pdf_image_extraction_enabled(Path("book.pdf")) is True


def test_pdf_image_dir_is_sanitized_and_created(tmp_path):
    path = tmp_path / "Рук-во по устройству ЭУ 2019.pdf"
    path.write_bytes(b"%PDF-1.4")

    image_dir = converter._pdf_image_dir(path)

    assert image_dir.name == "Рук-во_по_устройству_ЭУ_2019_images"
    assert image_dir.is_dir()
