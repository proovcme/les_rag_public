from email.message import EmailMessage

from backend.mail_threads import group_mail_threads, normalize_subject, read_mail_messages


def _write_message(path, *, subject, sender, to, message_id, body, date, in_reply_to="", references=""):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg["Date"] = date
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    msg.set_content(body)
    path.write_bytes(msg.as_bytes())


def test_normalize_subject_strips_reply_prefixes():
    assert normalize_subject("Re: Fwd: Ответ: Проект А") == "Проект А"


def test_mail_threads_group_message_id_references_and_who_to_whom(tmp_path):
    root = tmp_path / "mail"
    root.mkdir()
    _write_message(
        root / "01.eml",
        subject="Проект А: замечания",
        sender="Alice <alice@example.com>",
        to="Bob <bob@example.com>",
        message_id="<m1@example.com>",
        body="Нужно проверить раздел пожарной безопасности.",
        date="Tue, 26 May 2026 09:00:00 +0300",
    )
    _write_message(
        root / "02.eml",
        subject="Re: Проект А: замечания",
        sender="Bob <bob@example.com>",
        to="Alice <alice@example.com>",
        message_id="<m2@example.com>",
        in_reply_to="<m1@example.com>",
        references="<m1@example.com>",
        body="Принял, замечания внесу сегодня.",
        date="Tue, 26 May 2026 10:00:00 +0300",
    )

    messages = read_mail_messages(root)
    threads = group_mail_threads(messages)

    assert len(messages) == 2
    assert len(threads) == 1
    thread = threads[0].payload()
    assert thread["subject"] == "Проект А: замечания"
    assert thread["message_count"] == 2
    assert thread["messages"][0]["who_to_whom"]["from"] == "Alice <alice@example.com>"
    assert thread["messages"][1]["who_to_whom"]["to"] == ["Alice <alice@example.com>"]
    assert thread["messages"][1]["what"]["snippet"] == "Принял, замечания внесу сегодня."
    assert thread["edges"] == [{"from_message_id": "m1@example.com", "to_message_id": "m2@example.com"}]


def test_single_part_attachment_not_leaked_into_body(tmp_path):
    """Письмо-вложение (Content-Disposition: attachment, не multipart):
    вложение учитывается, бинарь НЕ течёт в snippet (был баг)."""
    root = tmp_path / "mail"
    root.mkdir()
    raw = (
        b"Subject: Single\r\nFrom: a@x.ru\r\nTo: b@x.ru\r\n"
        b"Date: Tue, 26 May 2026 09:00:00 +0300\r\nMessage-ID: <s@x>\r\n"
        b'Content-Type: application/pdf; name="report.pdf"\r\n'
        b'Content-Disposition: attachment; filename="report.pdf"\r\n'
        b"Content-Transfer-Encoding: base64\r\n\r\nAAEC\r\n"
    )
    (root / "single.eml").write_bytes(raw)
    messages = read_mail_messages(root)
    assert len(messages) == 1
    record = messages[0]
    assert record.attachments == ["report.pdf"]
    assert record.body_snippet == ""


def test_single_part_plain_and_html_body_preserved(tmp_path):
    root = tmp_path / "mail"
    root.mkdir()
    (root / "plain.eml").write_bytes(
        b"Subject: P\r\nFrom: a@x.ru\r\nMessage-ID: <p@x>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nhello plain"
    )
    (root / "html.eml").write_bytes(
        b"Subject: H\r\nFrom: a@x.ru\r\nMessage-ID: <h@x>\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n<b>Bold</b> hi"
    )
    by_name = {m.relative_path: m for m in read_mail_messages(root)}
    assert "hello plain" in by_name["plain.eml"].body_snippet
    assert "Bold hi" in by_name["html.eml"].body_snippet
    assert "<b>" not in by_name["html.eml"].body_snippet
