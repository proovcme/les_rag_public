from sovushka.pages.chat import (
    _attachment_chat_payload,
    _attachment_visible_text,
    _chat_profile_operator_summary,
    _dataset_profile_operator_summary,
    _operator_status_chips,
    _operator_technical_chips,
    should_skip_chat_resource_gate,
)
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


def test_operator_status_chips_hide_internal_trace_from_first_layer():
    meta = {
        "query_route": {"channel": "table", "kot": {"dataset_filter": "NTD_FIRE", "confidence": 0.8}},
        "retrieval_trace": {"mode": "hybrid", "quality_status": "good"},
        "cache": "miss",
        "validation": {"enabled": True},
        "latency_phases": {"total": 12.34},
    }

    chips = _operator_status_chips("VERIFIED", meta, ["a", "b"])
    labels = [c["label"] for c in chips]

    assert "2 источн." in labels
    assert "Проверено" in labels
    assert "Таблица" in labels
    assert "12.3с" in labels
    assert all("KOT" not in label and "CACHE" not in label for label in labels)

    tech = _operator_technical_chips(meta)
    assert "KOT NTD_FIRE 0.8" in tech
    assert "CACHE MISS" in tech


def test_dataset_and_chat_profile_operator_summaries_are_human_readable():
    ds = {
        "name": "Пожарные нормы",
        "dataset_id": "ds-fire",
        "document_count": 3,
        "chunk_count": 120,
        "keywords": ["эвакуац", "лестниц"],
        "profile_path": "storage/datasets/ds-fire/_les_dataset_profile.json",
        "deep": {
            "norm_refs": ["СП 1.13130", "ФЗ 123"],
            "content_keywords": ["выход", "коридор"],
            "table_signal_chunks": 7,
        },
    }
    chat = {
        "turn_count": 4,
        "last_status": "VERIFIED",
        "effective_dataset_filter": "NTD_FIRE",
        "blockers": ["нет PDF проекта"],
        "assumptions": ["принята высота 3 м"],
    }

    ds_lines = _dataset_profile_operator_summary(ds)
    chat_lines = _chat_profile_operator_summary(chat)

    assert "Пожарные нормы: 3 файлов, 120 чанков" in ds_lines[0]
    assert any("СП 1.13130" in line for line in ds_lines)
    assert any("Табличный сигнал" in line for line in ds_lines)
    assert "Ходов: 4" in chat_lines[0]
    assert any("нет PDF проекта" in line for line in chat_lines)
