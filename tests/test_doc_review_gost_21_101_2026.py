"""Тест doc_review (СПДС-нормоконтроль ГОСТ Р 21.101-2026, Phase 3) — RAG-led review.

Покрывает приёмку §6 плана: clean → нет computed-замечаний; отсутствует лист по ведомости →
computed_issue; кривое обозначение → computed_issue; отчёты JSON/HTML/XLSX создаются. Плюс
архинвариант: движок НЕ ставит финал (confirmed/rejected) — только proposed/evidence, human=unset.
"""

import json

import pytest

from proxy.services.doc_review_service import (
    S_COMPUTED_ISSUE,
    apply_human_decisions,
    build_sheet_format_evidence,
    review_summary,
    review_to_chat_text,
    review_to_html,
    review_to_json,
    review_to_xlsx,
    run_review,
)
from proxy.services.document_set_model import build_document_set
from proxy.services.normcontrol_review_map_service import load_review_map

MAP = load_review_map("gost_r_21_101_2026")
MM_TO_PT = 72.0 / 25.4


def _make_pdf(path, width_mm: float = 210, height_mm: float = 297):
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=width_mm * MM_TO_PT, height=height_mm * MM_TO_PT)
    page.insert_text((40, 40), "sheet format fixture", fontsize=11)
    doc.save(path)
    doc.close()


def test_clean_set_has_no_computed_issue():
    ds = build_document_set(["2024-15-АР-1.pdf", "2024-15-АР-2.pdf"])
    ved = [{"designation": "2024-15-АР-1", "name": "План"}, {"designation": "2024-15-АР-2", "name": "Разрез"}]
    items = run_review(ds, MAP, vedomost_entries=ved)
    assert review_summary(items)["computed_issues"] == 0


def test_missing_sheet_is_computed_issue():
    ds = build_document_set(["2024-15-АР-1.pdf"])  # АР-2 нет
    ved = [{"designation": "2024-15-АР-1", "name": "План"}, {"designation": "2024-15-АР-2", "name": "Разрез"}]
    items = run_review(ds, MAP, vedomost_entries=ved)
    missing = [it for it in items if it.computed_check.get("name") in ("vedomost_vs_files", "vedomost_missing")
               and it.status == S_COMPUTED_ISSUE]
    assert missing, "отсутствующий по ведомости лист должен дать computed_issue"
    assert all(it.requirement.get("source_ref", "").startswith("ГОСТ Р 21.101-2026") for it in items)


def test_bad_designation_is_computed_issue():
    ds = build_document_set(["2024 15 АР 1.pdf", "README.pdf"])  # пробелы + нераспознанное
    items = run_review(ds, MAP)
    issues = {it.computed_check.get("name") for it in items if it.status == S_COMPUTED_ISSUE}
    assert "designation_separators" in issues or "designation_pattern" in issues


def test_no_vedomost_marks_not_applicable_not_fake_pass():
    ds = build_document_set(["2024-15-АР-1.pdf"])
    items = run_review(ds, MAP, vedomost_entries=None)
    ved_items = [it for it in items if it.computed_check.get("name") == "vedomost_vs_files"]
    assert ved_items and all(it.status == "not_applicable" for it in ved_items)


def test_engine_never_finalizes_verdict():
    # АРХИТЕКТУРА: финал (confirmed/rejected) — только человек. Движок их не ставит.
    items = run_review(build_document_set(["2024-15-АР-1.pdf"]), MAP)
    assert all(it.human_decision == "unset" for it in items)
    assert all(it.status not in ("confirmed", "rejected") for it in items)


def test_retrieval_and_manual_kinds_are_honest():
    items = run_review(build_document_set(["2024-15-АР-1.pdf"]), MAP)
    statuses = {it.status for it in items}
    # retrieval → review_needed, layout/manual → manual_required (не fake pass)
    assert "review_needed" in statuses
    assert "manual_required" in statuses


def test_sheet_format_uses_pdf_geometry_evidence(tmp_path):
    pytest.importorskip("fitz")
    pdf = tmp_path / "2024-15-АР-1.pdf"
    _make_pdf(pdf, width_mm=500, height_mm=500)
    sheet = build_sheet_format_evidence([str(pdf)])
    items = run_review(build_document_set([pdf.name]), MAP, sheet_format=sheet)
    d4 = next(it for it in items if it.rule_id == "G21.101-2026-D4-001")
    assert d4.status == S_COMPUTED_ISSUE
    assert d4.computed_check["name"] == "sheet_format"
    assert d4.document_evidence
    assert "Нестандартный формат листа" in d4.document_evidence[0]["snippet"]


def test_chat_report_is_defensible_human_report():
    items = run_review(build_document_set(["2024 15 АР 1.pdf", "README.pdf"]), MAP)
    text = review_to_chat_text(items, MAP)
    assert "предварительный отчёт ЛЕС" in text
    assert "Замечания для решения инженера" in text
    assert "| ID | Что проверено | Основание | Evidence комплекта | Почему так | Действие |" not in text
    assert "| Класс | Кол-во |" not in text
    assert "ГОСТ Р 21.101-2026#clause=" in text
    assert "подтвердить или отклонить замечание" in text
    assert "### Как защищать отчёт" in text
    assert "manual_required" not in text
    assert "review_needed" not in text
    assert "defense.contract" not in text


def test_reports_render(tmp_path):
    items = run_review(build_document_set(["2024-15-АР-1.pdf"]), MAP)
    payload = review_to_json(items, MAP)
    assert payload["standard"] == "ГОСТ Р 21.101-2026" and payload["items"]
    assert payload["defense"]["schema"] == "defense_contract_v1"
    assert payload["defense"]["domain"] == "normcontrol.doc_review"
    assert payload["defense"]["summary"]["human_final_required"] is True
    assert payload["defense"]["claims"]
    assert {c["status"] for c in payload["defense"]["claims"]} & {"computed", "missing", "manual_required", "supported"}
    assert payload["normalized_remarks"]
    assert payload["normalized_remarks"][0]["schema"] == "normalized_remark_v1"
    assert payload["normalized_remarks"][0]["finality"] == "proposed"
    assert payload["normalized_remarks"][0]["human_decision"] == "unset"
    assert json.dumps(payload, ensure_ascii=False)  # сериализуемо
    html = review_to_html(items, MAP)
    assert "ГОСТ Р 21.101-2026" in html and "<table" in html
    out = tmp_path / "report.xlsx"
    n = review_to_xlsx(items, out, MAP)
    assert out.exists() and n == len(items)


def test_human_decision_updates_normalized_contract():
    items = run_review(build_document_set(["2024-15-АР-1.pdf"]), MAP)
    first = items[0].rule_id
    apply_human_decisions(items, {
        first: {"decision": "confirmed", "comment": "Проверено инженером", "decided_at": "2026-06-27T10:00:00+00:00"}
    })
    payload = review_to_json(items, MAP)
    remark = next(r for r in payload["normalized_remarks"] if r["id"] == first)
    assert remark["human_decision"] == "confirmed"
    assert remark["human_comment"] == "Проверено инженером"
    assert remark["finality"] == "human_decided"
    assert payload["summary"]["human_confirmed"] == 1
