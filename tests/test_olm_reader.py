"""W11.14 — парсер .olm (архив Outlook для Mac). Офлайн, stdlib, без зависимостей."""

from __future__ import annotations

import zipfile
from email import message_from_bytes, policy
from email.header import make_header, decode_header
from pathlib import Path


def _hdr(value) -> str:
    return str(make_header(decode_header(str(value))))

from backend.olm_reader import extract_olm_to_eml, iter_olm_messages

_OPF_MSG = """<?xml version="1.0" encoding="UTF-8"?>
<emails>
 <email>
  <OPFMessageCopySubject>{subj}</OPFMessageCopySubject>
  <OPFMessageCopySentTime>Mon, 15 Jan 2024 10:00:00 +0300</OPFMessageCopySentTime>
  <OPFMessageCopyBody>{body}</OPFMessageCopyBody>
  <OPFMessageCopySenderAddress>
    <emailAddress OPFContactEmailAddressAddress="ivan@example.com" OPFContactEmailAddressName="Иван"/>
  </OPFMessageCopySenderAddress>
  <OPFMessageCopyToAddresses>
    <emailAddress OPFContactEmailAddressAddress="boss@example.com" OPFContactEmailAddressName="Босс"/>
  </OPFMessageCopyToAddresses>
 </email>
</emails>"""


def _make_olm(path: Path, messages: list[tuple[str, str]]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for i, (subj, body) in enumerate(messages, 1):
            zf.writestr(
                f"Accounts/acc/Inbox/message_{i:04d}.xml",
                _OPF_MSG.format(subj=subj, body=body),
            )
        zf.writestr("Accounts/acc/categories.xml", "<categories/>")  # служебный — игнор


def test_iter_olm_messages_parses_fields(tmp_path):
    olm = tmp_path / "archive.olm"
    _make_olm(olm, [("Поставка кабеля", "Кабель 3х1,5 — 744 м, ждём счёт.")])
    msgs = list(iter_olm_messages(olm))
    assert len(msgs) == 1
    m = msgs[0]
    assert m["subject"] == "Поставка кабеля"
    assert "Кабель" in m["body"]
    assert "ivan@example.com" in m["from"][0]
    assert "boss@example.com" in m["to"][0]


def test_extract_olm_to_eml(tmp_path):
    olm = tmp_path / "archive.olm"
    _make_olm(olm, [("Письмо 1", "тело раз"), ("Письмо 2", "тело два")])
    out = tmp_path / "out"
    eml_paths = extract_olm_to_eml(olm, out)
    assert len(eml_paths) == 2
    em = message_from_bytes(eml_paths[0].read_bytes(), policy=policy.default)
    assert "Письмо 1" in _hdr(em["Subject"])
    assert "ivan@example.com" in _hdr(em["From"])
    assert "тело раз" in em.get_content()


def test_html_body_stripped(tmp_path):
    olm = tmp_path / "h.olm"
    with zipfile.ZipFile(olm, "w") as zf:
        zf.writestr("Accounts/a/Inbox/message_0001.xml",
                    '<emails><email><OPFMessageCopySubject>S</OPFMessageCopySubject>'
                    '<OPFMessageCopyHTMLBody>&lt;p&gt;Привет &lt;b&gt;мир&lt;/b&gt;&lt;/p&gt;</OPFMessageCopyHTMLBody>'
                    '</email></emails>')
    m = list(iter_olm_messages(olm))[0]
    assert "Привет" in m["body"] and "<" not in m["body"]


def test_empty_archive(tmp_path):
    olm = tmp_path / "empty.olm"
    with zipfile.ZipFile(olm, "w") as zf:
        zf.writestr("Accounts/a/notes.xml", "<x/>")
    assert list(iter_olm_messages(olm)) == []
