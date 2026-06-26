"""Тест doc_review (СПДС-нормоконтроль ГОСТ Р 21.101-2026, Phase 3) — RAG-led review.

Покрывает приёмку §6 плана: clean → нет computed-замечаний; отсутствует лист по ведомости →
computed_issue; кривое обозначение → computed_issue; отчёты JSON/HTML/XLSX создаются. Плюс
архинвариант: движок НЕ ставит финал (confirmed/rejected) — только proposed/evidence, human=unset.
"""

import json

from proxy.services.doc_review_service import (
    S_COMPUTED_ISSUE,
    review_summary,
    review_to_html,
    review_to_json,
    review_to_xlsx,
    run_review,
)
from proxy.services.document_set_model import build_document_set
from proxy.services.normcontrol_review_map_service import load_review_map

MAP = load_review_map("gost_r_21_101_2026")


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


def test_reports_render(tmp_path):
    items = run_review(build_document_set(["2024-15-АР-1.pdf"]), MAP)
    payload = review_to_json(items, MAP)
    assert payload["standard"] == "ГОСТ Р 21.101-2026" and payload["items"]
    assert json.dumps(payload, ensure_ascii=False)  # сериализуемо
    html = review_to_html(items, MAP)
    assert "ГОСТ Р 21.101-2026" in html and "<table" in html
    out = tmp_path / "report.xlsx"
    n = review_to_xlsx(items, out, MAP)
    assert out.exists() and n == len(items)
