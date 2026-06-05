import subprocess
from email.message import EmailMessage

from backend import mail_profile
from backend.mail_profile import build_mail_vector_profile


def test_mail_vector_profile_extracts_headers_importance_and_text_attachment(tmp_path):
    msg = EmailMessage()
    msg["Subject"] = "Re: Проект: согласование"
    msg["From"] = "Alice <alice@example.com>"
    msg["To"] = "Bob <bob@example.com>"
    msg["Cc"] = "Carol <carol@example.com>"
    msg["Date"] = "Tue, 26 May 2026 09:00:00 +0300"
    msg["Message-ID"] = "<m2@example.com>"
    msg["In-Reply-To"] = "<m1@example.com>"
    msg["Importance"] = "high"
    msg.set_content("Подтверждаю, отправим исполнительную документацию сегодня.")
    msg.add_attachment(
        "Содержимое текстового вложения про АОСР.".encode("utf-8"),
        maintype="text",
        subtype="plain",
        filename="note.txt",
    )
    path = tmp_path / "letter.eml"
    path.write_bytes(msg.as_bytes())

    profile = build_mail_vector_profile(path, source_dir=tmp_path)
    payload = profile.payload()

    assert profile.normalized_subject == "Проект: согласование"
    assert profile.thread_key.startswith("msg_")
    assert payload["mail_importance"] == "high"
    assert payload["mail_from"] == "Alice <alice@example.com>"
    assert payload["mail_to"] == ["Bob <bob@example.com>"]
    assert payload["mail_cc"] == ["Carol <carol@example.com>"]
    assert payload["mail_attachment_text_available"] is True
    assert profile.attachments[0].extraction == "text"
    assert "Содержимое текстового вложения" in profile.attachments[0].text


def test_image_attachment_without_ocr_is_marked_as_visual_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_ATTACHMENT_OCR_ENABLED", "false")
    msg = EmailMessage()
    msg["Subject"] = "Фото замечания"
    msg["From"] = "inspector@example.com"
    msg["To"] = "les@example.com"
    msg.set_content("См. картинку во вложении.")
    msg.add_attachment(
        b"not-a-real-image-but-still-image-mime",
        maintype="image",
        subtype="png",
        filename="issue.png",
    )
    path = tmp_path / "photo.eml"
    path.write_bytes(msg.as_bytes())

    profile = build_mail_vector_profile(path)
    attachment = profile.attachments[0]

    assert attachment.kind == "image"
    assert attachment.extraction == "image_needs_ocr_vlm"
    assert attachment.needs_ocr is True
    assert attachment.needs_vlm is True
    assert profile.payload()["mail_pending_visual_evidence"] is True
    assert "требует OCR/VLM" in attachment.embedding_text(profile)


def test_pdf_attachment_native_crash_is_contained(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_ATTACHMENT_PDF_SUBPROCESS_ENABLED", "true")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], -11, stdout="", stderr="segmentation fault")

    monkeypatch.setattr(mail_profile.subprocess, "run", fake_run)
    msg = EmailMessage()
    msg["Subject"] = "PDF crash"
    msg["From"] = "author@example.com"
    msg["To"] = "les@example.com"
    msg.set_content("PDF во вложении.")
    msg.add_attachment(
        b"%PDF-1.4\nbroken",
        maintype="application",
        subtype="pdf",
        filename="broken.pdf",
    )
    path = tmp_path / "pdf-crash.eml"
    path.write_bytes(msg.as_bytes())

    profile = build_mail_vector_profile(path)
    attachment = profile.attachments[0]

    assert attachment.kind == "pdf"
    assert attachment.extraction == "pdf_needs_ocr_vlm"
    assert attachment.needs_ocr is True
    assert attachment.needs_vlm is True
    assert "pdf_extractor_exit_-11" in attachment.error


def test_pdf_attachment_timeout_is_marked_for_ocr_vlm(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_ATTACHMENT_PDF_SUBPROCESS_ENABLED", "true")
    monkeypatch.setenv("MAIL_ATTACHMENT_PDF_TIMEOUT_SEC", "0.01")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    monkeypatch.setattr(mail_profile.subprocess, "run", fake_run)
    msg = EmailMessage()
    msg["Subject"] = "PDF timeout"
    msg["From"] = "author@example.com"
    msg["To"] = "les@example.com"
    msg.set_content("PDF во вложении.")
    msg.add_attachment(
        b"%PDF-1.4\nslow",
        maintype="application",
        subtype="pdf",
        filename="slow.pdf",
    )
    path = tmp_path / "pdf-timeout.eml"
    path.write_bytes(msg.as_bytes())

    profile = build_mail_vector_profile(path)
    attachment = profile.attachments[0]

    assert attachment.extraction == "pdf_needs_ocr_vlm"
    assert attachment.needs_ocr is True
    assert attachment.needs_vlm is True
    assert "pdf_extractor_timeout_after_0.01s" in attachment.error
