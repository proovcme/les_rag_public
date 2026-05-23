from email.message import EmailMessage

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
