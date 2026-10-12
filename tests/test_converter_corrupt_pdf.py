from __future__ import annotations

import pytest

import backend.converter as converter


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _unreadable_pdf_source(path):
    try:
        return converter._pdf_source_is_unreadable(path)
    except AttributeError:
        pytest.fail("backend.converter must expose _pdf_source_is_unreadable for PDF source validation")


def _unsupported_pdf_source_error_type():
    try:
        return converter.UnsupportedPdfSourceError
    except AttributeError:
        pytest.fail("backend.converter must expose UnsupportedPdfSourceError")


def _ocr_required_error_type():
    try:
        return converter.OCRRequiredError
    except AttributeError:
        pytest.fail("backend.converter must expose OCRRequiredError")


@pytest.mark.parametrize(
    ("content", "unreadable"),
    [(PNG_MAGIC + b"x" * 20, True), (b"", True), (b"%PDF-1.7\n", False)],
)
def test_pdf_readability_uses_signature(tmp_path, content, unreadable):
    path = tmp_path / "source.pdf"
    path.write_bytes(content)
    assert _unreadable_pdf_source(path) is unreadable


def test_pdf_header_may_follow_bounded_transport_prefix(tmp_path):
    path = tmp_path / "prefixed.pdf"
    path.write_bytes(b"\xef\xbb\xbf\r\n  transport metadata\n%PDF-1.7\n")
    assert _unreadable_pdf_source(path) is False


def test_pdf_header_outside_bounded_probe_is_unreadable(tmp_path):
    path = tmp_path / "late-header.pdf"
    path.write_bytes(b"x" * 1024 + b"%PDF-1.7\n")
    assert _unreadable_pdf_source(path) is True


def test_unsupported_pdf_source_is_not_an_ocr_condition():
    assert not issubclass(_unsupported_pdf_source_error_type(), _ocr_required_error_type())


def test_unreadable_source_propagates_through_public_converter(tmp_path, monkeypatch):
    path = tmp_path / "underlay.pdf"
    path.write_bytes(PNG_MAGIC)
    unsupported = _unsupported_pdf_source_error_type()
    monkeypatch.setattr(
        converter,
        "_parse_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            unsupported("pdf_source_unreadable: underlay.pdf")
        ),
    )
    with pytest.raises(unsupported):
        converter.convert_to_markdown(path)


def test_normal_pdf_route_rejects_mislabeled_source_before_any_fallback(tmp_path, monkeypatch):
    path = tmp_path / "underlay.pdf"
    path.write_bytes(PNG_MAGIC + b"not a pdf")
    monkeypatch.setattr(
        converter,
        "_parse_pdf_fast_text_layer",
        lambda *_args, **_kwargs: pytest.fail("unusable source must not enter text fallback"),
    )
    unsupported = _unsupported_pdf_source_error_type()

    with pytest.raises(unsupported) as raised:
        converter.convert_to_markdown(path)
    assert str(raised.value) == "pdf_source_unreadable: underlay.pdf"
    assert "[WARN]" not in str(raised.value)


def test_truncated_pdf_header_is_not_returned_as_searchable_warning(tmp_path, monkeypatch):
    path = tmp_path / "truncated.pdf"
    path.write_bytes(b"%PDF-1.7\n")
    monkeypatch.setenv("RAG_OCR_ENABLED", "false")
    unsupported = _unsupported_pdf_source_error_type()

    with pytest.raises(unsupported) as raised:
        converter.convert_to_markdown(path)

    assert str(raised.value) == "pdf_source_unreadable: truncated.pdf"
    assert "[WARN]" not in str(raised.value)


def test_unreadable_source_verdict_has_dedicated_subprocess_status(monkeypatch):
    payloads = []
    queue = type("Queue", (), {"put": lambda self, item: payloads.append(item)})()
    unsupported = _unsupported_pdf_source_error_type()
    monkeypatch.setattr(
        converter,
        "convert_to_markdown",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            unsupported("pdf_source_unreadable: x.pdf")
        ),
    )
    converter._convert_to_markdown_worker("x.pdf", None, queue)
    assert payloads == [("unsupported_pdf_source", "pdf_source_unreadable: x.pdf")]
