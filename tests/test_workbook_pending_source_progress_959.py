"""Saved operation rows and reopened source anchors cannot inflate source totals."""
from copy import deepcopy

import pytest

from sovushka.pages import chat as page


def checkpoint(*, total=20, saved=12, review=4):
    catalog = [f"Source Ω!R{index}" for index in range(1, total + 1)]
    rows = [{"source_row": source, "row_role": "work", "operation_id": f"op-{index}"}
            for index, source in enumerate(catalog[:saved], 1)]
    return {"job_id": "own-private-959", "status": "paused", "phase": "packets",
            "accepted_rows": rows, "remaining": catalog[saved - review:],
            "status_dimensions": {"processed": saved, "remaining": total - saved + review},
            "task_context": {"_source_catalog_locators": catalog,
                             "pending_research_locators": catalog[saved - review:saved],
                             "pending_research_operation_ids": [f"op-{index}" for index in range(saved - review + 1, saved + 1)]}}


def test_shared_four_pending_sources_do_not_inflate_twenty_source_denominator(monkeypatch):
    monkeypatch.setattr(page, "_work_total_from_job_events", lambda _job_id: pytest.fail("Catalog already gives exact scope"))
    job = checkpoint()
    before = deepcopy(job)
    result = page.workbook_job_to_pending_progress(job, {"total": 24})
    assert result["total"] == 20 and result["accepted"] == 8 and result["remaining"] == 12
    counts = result["source_counts"]
    assert counts["saved_operation_count"] == counts["saved_source_count"] == 12
    assert counts["unprocessed_source_count"] == 8
    assert counts["review_source_count"] == counts["review_operation_count"] == 4
    notice = page.format_paused_assembly_notice(result)
    assert "Ещё не обработано исходных строк: 8 из 20" in notice
    assert "Повторно открыто для уточнения: 4 исходных строк" in notice
    assert "В черновик записано 12 строк результата" in notice
    assert "из 24" not in notice and "Незакрытых строк покрытия: 12" not in notice
    assert job == before


def test_one_anchor_two_works_and_material_are_three_saved_operations_not_three_sources(monkeypatch):
    monkeypatch.setattr(page, "_work_total_from_job_events", lambda _job_id: pytest.fail("No DB read in exact projection"))
    job = checkpoint(total=1, saved=1, review=1)
    job["accepted_rows"] += [{**job["accepted_rows"][0], "operation_id": "op-second"},
                             {**job["accepted_rows"][0], "row_role": "material", "operation_id": "op-material"}]
    job["task_context"]["pending_research_operation_ids"] = ["op-1", "op-second"]
    result = page.workbook_job_to_pending_progress(job)
    assert result["total"] == result["remaining"] == 1 and result["accepted"] == 0
    assert result["source_counts"]["saved_operation_count"] == 3
    assert result["source_counts"]["saved_source_count"] == 1
    assert result["source_counts"]["unprocessed_source_count"] == 0
    assert result["source_counts"]["review_source_count"] == 1
    assert result["source_counts"]["review_operation_count"] == 2


@pytest.mark.parametrize("alias", ["source Ω!r9", "LOCATOR:Source Ω!R9", "R9"])
def test_verified_technical_aliases_are_counted_once(alias):
    job = checkpoint()
    job["accepted_rows"][8]["source_row"] = alias
    job["remaining"] += [alias, "Source Ω!R9"]
    job["task_context"]["pending_research_locators"] += [alias]
    counts = page._workbook_source_progress_counts(job)
    assert counts["total_source_count"] == 20 and counts["saved_source_count"] == 12
    assert counts["unprocessed_source_count"] == 8 and counts["review_source_count"] == 4
    assert counts["remaining_source_count"] == 12


def test_ambiguous_bare_row_is_not_associated_with_a_sheet_by_guessing():
    job = {"task_context": {"_source_catalog_locators": ["A!R2", "B!R2"]},
           "accepted_rows": [{"source_row": "R2", "row_role": "work"}], "remaining": []}
    counts = page._workbook_source_progress_counts(job)
    assert counts["saved_operation_count"] == 1 and counts["saved_source_count"] == 0
    assert counts["unprocessed_source_count"] == counts["remaining_source_count"] == 2


def test_legacy_without_catalog_keeps_its_existing_projection(monkeypatch):
    monkeypatch.setattr(page, "_work_total_from_job_events", lambda _job_id: 0)
    job = {"status": "paused", "work_total": 2,
           "accepted_rows": [{"source_row": "A!R1", "row_role": "work"}], "remaining": ["A!R2"]}
    assert page._workbook_source_progress_counts(job) is None
    result = page.workbook_job_to_pending_progress(job)
    assert result["total"] == 2 and result["remaining"] == result["accepted"] == 1
    assert "source_counts" not in result


def test_unassigned_research_target_is_unseen_not_a_second_review_count(monkeypatch):
    monkeypatch.setattr(page, "_work_total_from_job_events", lambda _job_id: pytest.fail("Catalog already owns the scope"))
    job = checkpoint(total=3, saved=2, review=1)
    job["task_context"]["pending_research_locators"].append("Source Ω!R3")
    job["task_context"]["pending_research_unassigned_locators"] = ["Source Ω!R3"]
    before = deepcopy(job)
    result = page.workbook_job_to_pending_progress(job)
    counts = result["source_counts"]
    assert result["total"] == 3 and result["remaining"] == 2 and result["accepted"] == 1
    assert counts["unprocessed_source_count"] == counts["review_source_count"] == 1
    assert counts["other_revisit_source_count"] == 0
    assert sum(counts[key] for key in ("unprocessed_source_count", "review_source_count", "other_revisit_source_count")) == counts["remaining_source_count"]
    notice = page.format_paused_assembly_notice(result)
    assert "Ещё не обработано исходных строк: 1 из 3" in notice
    assert "Повторно открыто для уточнения: 1 исходных строк" in notice
    assert "Повторно открыто для уточнения: 2" not in notice
    assert job == before


def test_never_saved_pending_source_is_only_unprocessed(monkeypatch):
    monkeypatch.setattr(page, "_work_total_from_job_events", lambda _job_id: pytest.fail("No event scan"))
    job = checkpoint(total=2, saved=1, review=0)
    job["task_context"]["pending_research_locators"] = ["Source Ω!R2"]
    job["task_context"]["pending_research_unassigned_locators"] = ["Source Ω!R2"]
    result = page.workbook_job_to_pending_progress(job)
    counts = result["source_counts"]
    assert counts["unprocessed_source_count"] == counts["remaining_source_count"] == 1
    assert counts["review_source_count"] == counts["review_operation_count"] == 0
    assert "Повторно открыто для уточнения" not in page.format_paused_assembly_notice(result)


def test_foreign_full_namespace_cannot_alias_a_catalog_source_by_suffix():
    job = {"task_context": {"_source_catalog_locators": ["A!R2"]},
           "accepted_rows": [{"source_row": "B!R2", "operation_id": "foreign", "row_role": "work"}], "remaining": []}
    before = deepcopy(job)
    counts = page._workbook_source_progress_counts(job)
    assert counts["saved_source_count"] == 0
    assert counts["unprocessed_source_count"] == counts["remaining_source_count"] == 1
    assert job == before
