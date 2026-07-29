"""Тесты sovushka/checklist_review_view.py (T5.1) — чистые UI-хелперы, TDD red->green.

Паттерн — по образцу sovushka/m5_display.py (см. tests/test_sovushka_m5_display.py): модуль без
NiceGUI-импортов, тестируется прямым вызовом функций на dict-фикстурах формы checklist_review_v1
(та же форма item/summary, что в tests/test_checklist_report_service.py). NiceGUI-обвязка
(sovushka/pages/instrumenty.py) остаётся тонкой и здесь не тестируется.

Три хелпера:
  format_item_row(item) -> dict       — колонки таблицы (№, критерий обрезанный, suggested
                                         русским ярлыком как в checklist_report_service,
                                         уверенность, evidence count, human answer).
  summary_chips(summary) -> list[dict] — чипы сводки (всего/да/нет/не требуется/требует
                                          инженера/неизвестно/подтверждено человеком).
  evidence_lines(item) -> list[str]   — source_ref + snippet для drawer.
"""

from __future__ import annotations

from sovushka.checklist_review_view import (
    evidence_lines,
    format_item_row,
    summary_chips,
)

# ── фикстуры (форма checklist_review_v1) ────────────────────────────────────────────────────


def _item(**overrides) -> dict:
    base = {
        "item_id": "PD-OB-001",
        "item_no": "1",
        "criterion": "Приложен отчет об инженерно-геологических изысканиях",
        "discipline": "Общее",
        "status": "supported_by_evidence",
        "suggested_answer": "yes",
        "confidence": 0.75,
        "document_evidence": [
            {
                "source_ref": "ds-pd:otchet_igi.pdf#page=1",
                "snippet": "Отчет об инженерно-геологических изысканиях выполнен в 2026 году.",
            },
        ],
        "model_note": "Найден контентный хит, подтверждающий наличие документа.",
        "human_answer": "unset",
        "human_note": "",
    }
    base.update(overrides)
    return base


# ── format_item_row ──────────────────────────────────────────────────────────────────────────


def test_format_item_row_basic_fields():
    row = format_item_row(_item())

    assert row["item_id"] == "PD-OB-001"
    assert row["item_no"] == "1"
    assert row["discipline"] == "Общее"
    assert row["suggested_label"] == "Да"
    assert row["confidence"] == 0.75
    assert row["evidence_count"] == 1
    assert row["human_answer_label"] == ""  # unset -> пусто, не "—"


def test_format_item_row_criterion_is_truncated_with_ellipsis():
    long_criterion = "А" * 300
    row = format_item_row(_item(criterion=long_criterion))

    assert len(row["criterion_short"]) <= 121  # 120 символов + многоточие
    assert row["criterion_short"].endswith("…")
    assert row["criterion_full"] == long_criterion  # полный текст сохранён для drawer


def test_format_item_row_short_criterion_not_truncated():
    row = format_item_row(_item(criterion="Короткий критерий"))

    assert row["criterion_short"] == "Короткий критерий"
    assert not row["criterion_short"].endswith("…")


def test_format_item_row_suggested_answer_labels_match_report_service():
    # Русские ярлыки должны совпадать 1-в-1 с checklist_report_service._ANSWER_LABELS_RU (иначе
    # UI и XLSX/HTML разъедутся терминологией на одних и тех же данных).
    from proxy.services.checklist_report_service import _ANSWER_LABELS_RU

    for machine_value, expected_label in _ANSWER_LABELS_RU.items():
        row = format_item_row(_item(suggested_answer=machine_value))
        assert row["suggested_label"] == expected_label


def test_format_item_row_human_answer_decided():
    row = format_item_row(_item(human_answer="no", human_note="не хватает страницы"))

    assert row["human_answer_label"] == "Нет"
    assert row["human_note"] == "не хватает страницы"


def test_format_item_row_evidence_count_zero_when_no_evidence():
    row = format_item_row(_item(document_evidence=[]))

    assert row["evidence_count"] == 0


def test_format_item_row_evidence_count_ignores_refs_without_source():
    row = format_item_row(_item(document_evidence=[
        {"source_ref": "", "snippet": "пусто"},
        {"source_ref": "ds:file.pdf#p=2", "snippet": ""},
    ]))

    assert row["evidence_count"] == 1


def test_format_item_row_empty_item_does_not_raise():
    row = format_item_row({})

    assert row["item_id"] == ""
    assert row["item_no"] == ""
    assert row["criterion_short"] == ""
    assert row["suggested_label"] == "—"
    assert row["confidence"] == ""
    assert row["evidence_count"] == 0
    assert row["human_answer_label"] == ""


def test_format_item_row_missing_document_evidence_key():
    row = format_item_row({"item_id": "X", "criterion": "тест"})

    assert row["evidence_count"] == 0


# ── summary_chips ────────────────────────────────────────────────────────────────────────────


def _summary(**overrides) -> dict:
    base = {
        "total": 10,
        "suggested": {"yes": 4, "no": 1, "not_required": 2, "manual_required": 2, "unknown": 1},
        "human": {"yes": 3, "no": 0, "not_required": 0, "unset": 7},
    }
    base.update(overrides)
    return base


def test_summary_chips_contains_total_and_all_suggested_buckets():
    chips = summary_chips(_summary())
    by_key = {c["key"]: c for c in chips}

    assert by_key["total"]["value"] == 10
    assert by_key["yes"]["value"] == 4
    assert by_key["no"]["value"] == 1
    assert by_key["not_required"]["value"] == 2
    assert by_key["manual_required"]["value"] == 2
    assert by_key["unknown"]["value"] == 1
    assert by_key["human_confirmed"]["value"] == 3  # human.yes+no+not_required (не unset)


def test_summary_chips_labels_are_russian():
    chips = summary_chips(_summary())
    labels = {c["key"]: c["label"] for c in chips}

    assert labels["total"] == "Всего"
    assert labels["yes"] == "Да"
    assert labels["no"] == "Нет"
    assert labels["not_required"] == "Не требуется"
    assert labels["manual_required"] == "Требует инженера"
    assert labels["unknown"] == "Неизвестно"
    assert labels["human_confirmed"] == "Подтверждено человеком"


def test_summary_chips_empty_summary_defaults_to_zero():
    chips = summary_chips({})
    values = {c["key"]: c["value"] for c in chips}

    assert values == {
        "total": 0,
        "yes": 0,
        "no": 0,
        "not_required": 0,
        "manual_required": 0,
        "unknown": 0,
        "human_confirmed": 0,
    }


def test_summary_chips_missing_human_block_does_not_raise():
    chips = summary_chips({"total": 5, "suggested": {"yes": 5}})
    values = {c["key"]: c["value"] for c in chips}

    assert values["human_confirmed"] == 0


def test_summary_chips_order_is_stable():
    chips = summary_chips(_summary())
    keys = [c["key"] for c in chips]

    assert keys == [
        "total", "yes", "no", "not_required", "manual_required", "unknown", "human_confirmed",
    ]


# ── evidence_lines ───────────────────────────────────────────────────────────────────────────


def test_evidence_lines_formats_source_ref_and_snippet():
    lines = evidence_lines(_item())

    assert len(lines) == 1
    assert "ds-pd:otchet_igi.pdf#page=1" in lines[0]
    assert "Отчет об инженерно-геологических изысканиях" in lines[0]


def test_evidence_lines_empty_when_no_evidence():
    assert evidence_lines(_item(document_evidence=[])) == []


def test_evidence_lines_missing_document_evidence_key():
    assert evidence_lines({"item_id": "X"}) == []


def test_evidence_lines_skips_entries_without_source_ref():
    lines = evidence_lines(_item(document_evidence=[
        {"source_ref": "", "snippet": "должно исчезнуть"},
        {"source_ref": "ds:a.pdf#p=1", "snippet": "должно остаться"},
    ]))

    assert len(lines) == 1
    assert "должно остаться" in lines[0]


def test_evidence_lines_handles_missing_snippet_field():
    lines = evidence_lines(_item(document_evidence=[{"source_ref": "ds:a.pdf#p=1"}]))

    assert len(lines) == 1
    assert "ds:a.pdf#p=1" in lines[0]


def test_evidence_lines_handles_none_entries_in_list():
    lines = evidence_lines(_item(document_evidence=[None, {"source_ref": "ds:a.pdf", "snippet": "ok"}]))

    assert len(lines) == 1


def test_checklist_section_selects_do_not_use_manual_emit_value_props():
    """Регрессия T5.1-bug: в NiceGUI 3.x ручные пропы emit-value/map-options на ui.select с
    dict-опциями ломают выбор (Quasar шлёт индекс, _event_args_to_value ждёт dict ->
    TypeError: 'int' object is not subscriptable; подтверждено стектрейсом на живом UI)."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "sovushka" / "checklist_review_panel.py"
    text = src.read_text(encoding="utf-8")
    start = text.index("def build_checklist_review_card")
    end = text.index("\ndef ", start + 10) if "\ndef " in text[start + 10:] else len(text)
    section = text[start:end]
    assert "emit-value" not in section, "ручной emit-value в секции чек-листа снова сломает выбор"
    assert "map-options" not in section


def test_checklist_review_does_not_install_a_code_owned_chat_answer():
    """Checklist evidence stays an operator tool; the shared chat model writes the answer."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    chat_source = (root / "proxy" / "routers" / "chat.py").read_text(encoding="utf-8")
    panel_source = (root / "sovushka" / "checklist_review_panel.py").read_text(
        encoding="utf-8"
    )

    assert "checklist_chat_service" not in chat_source
    assert "_run_project_normcontrol" not in panel_source
    assert ".style(" not in panel_source
    assert "Evidence-статус" in panel_source
    assert "Решение инженера" in panel_source
