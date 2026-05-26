from email.message import EmailMessage

import pytest

from backend.mail_ingest import resolve_mail_source_folder, summarize_mail_files


def test_mail_ingest_summarizes_eml_headers_and_attachments(tmp_path):
    source = tmp_path / "RAG_Content" / "MAIL"
    source.mkdir(parents=True)
    msg = EmailMessage()
    msg["Subject"] = "Исполнительная документация"
    msg["From"] = "author@example.com"
    msg["To"] = "les@example.com"
    msg["Date"] = "Sat, 23 May 2026 10:00:00 +0300"
    msg["Message-ID"] = "<mail-1@example.com>"
    msg.set_content("Добрый день.")
    msg.add_attachment(b"pdf", maintype="application", subtype="pdf", filename="aosr.pdf")
    (source / "letter.eml").write_bytes(msg.as_bytes())

    summaries = summarize_mail_files(source)

    assert len(summaries) == 1
    assert summaries[0].relative_path == "letter.eml"
    assert summaries[0].subject == "Исполнительная документация"
    assert summaries[0].sender == "author@example.com"
    assert summaries[0].attachments == ["aosr.pdf"]


def test_mail_source_folder_must_stay_under_rag_content(tmp_path):
    base = tmp_path / "RAG_Content"
    base.mkdir()

    with pytest.raises(ValueError):
        resolve_mail_source_folder("../Secrets", base=base)
