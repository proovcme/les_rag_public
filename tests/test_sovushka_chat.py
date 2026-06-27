from sovushka.pages.chat import _attachment_chat_payload, _attachment_visible_text, should_skip_chat_resource_gate
from proxy.routers.chat import ChatRequest, _attachment_source_label, _question_with_attachment


def test_smeta_table_question_skips_resource_gate():
    assert should_skip_chat_resource_gate("посчитай общую стоимость по всем строкам сметы")


def test_mail_question_skips_resource_gate():
    assert should_skip_chat_resource_gate("найди последнее письмо про Dropbox")


def test_general_normative_question_keeps_resource_gate():
    assert not should_skip_chat_resource_gate("какая минимальная ширина эвакуационного выхода")


def test_attachment_payload_scopes_quick_and_index_files():
    assert _attachment_chat_payload({"id": "attach_abc", "mode": "quick"}) == {
        "dataset_ids": ["attach_abc"]
    }
    assert _attachment_chat_payload({"id": "ds-1", "mode": "index"}) == {
        "dataset_ids": ["ds-1"]
    }


def test_attachment_payload_passes_read_context():
    assert _attachment_chat_payload(
        {"id": "read_1", "mode": "read", "name": "ТЗ.docx", "text": "Текст файла"}
    ) == {
        "attachment_context": "Файл: ТЗ.docx\n\nТекст файла"
    }


def test_attachment_source_label_uses_filename():
    assert _attachment_source_label("Файл: ТЗ.docx\n\nТекст файла") == "attachment:ТЗ.docx"
    assert _attachment_source_label("Текст без имени") == "attachment"


def test_explicit_tool_modes_can_receive_read_attachment_context():
    req = ChatRequest(question="сделай смету", mode="smeta", attachment_context="Файл: ТЗ.docx\n\nПлощадь 1200 м²")
    text = _question_with_attachment(req)
    assert "сделай смету" in text
    assert "Контекст прикреплённого файла" in text
    assert "Площадь 1200 м²" in text


def test_attachment_visible_text_makes_next_request_obvious():
    title, detail, chat = _attachment_visible_text(
        {"name": "ТЗ.docx", "mode": "read", "chars": 1234}
    )
    assert "следующему сообщению" in title
    assert "В чат" in detail and "ТЗ.docx" in detail
    assert "Модель увидит" in chat

    title, detail, chat = _attachment_visible_text(
        {"name": "ВОР.xlsx", "mode": "quick", "rows": 42}
    )
    assert "следующему сообщению" in title
    assert "Таблица" in detail and "42" in detail
    assert "временный датасет" in chat
