import sqlite3

import pytest

from proxy.services.workbook_research_job_service import (
    WorkbookResearchJobError,
    WorkbookResearchJobService,
    _legacy_operation_id,
)


def _identity(service: WorkbookResearchJobService, question: str = "Собери ЛСР"):
    return service.identity(
        session_id="session-1",
        attachment_id="read_123456abcdef",
        source_sha256="a" * 64,
        dataset_ids=["smeta"],
        profile_revision_id="factory",
        model_identity="qwen-35b",
        question=question,
    )


def test_pause_resume_keeps_rows_and_skips_cached_queries(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    first = service.begin_or_resume(_identity(service))
    service.record_search_cache(
        first["job_id"],
        {
            "монтаж шкафа": [
                {"content": "карточка", "doc_id": "c1", "doc_name": "ФСНБ", "score": 1.0, "meta": {}}
            ]
        },
    )
    service.record_packet(
        first["job_id"],
        sheet="СКС",
        packet_locators=["СКС!R2"],
        accepted_rows=[{"source_row": "СКС!R2", "norm_code": "10-01-001-01", "norm_status": "EXACT"}],
        evidence=[{"global_evidence_id": "g1", "content": "карточка"}],
        remaining=["СКС!R3"],
        held_packet={"sheet": "СКС", "locators": ["СКС!R3"], "queries": ["монтаж шкафа"]},
    )
    paused = service.pause(first["job_id"], remaining=["СКС!R3"])
    assert paused["status"] == "paused"
    assert paused["resumable"] is True
    assert paused["accepted_rows"][0]["norm_code"] == "10-01-001-01"
    assert "монтаж шкафа" in paused["query_cache"]
    assert paused["held_packet"]["queries"] == ["монтаж шкафа"]

    resumed = service.begin_or_resume(_identity(service))
    assert resumed["job_id"] == first["job_id"]
    assert resumed["status"] == "running"
    assert resumed["remaining"] == ["СКС!R3"]
    assert resumed["query_cache"]["монтаж шкафа"][0]["content"] == "карточка"
    assert resumed["held_packet"]["queries"] == ["монтаж шкафа"]
    assert resumed["prior_elapsed_seconds"] >= 0
    assert WorkbookResearchJobService.elapsed_seconds_between(
        "2026-09-16 16:53:54", "2026-09-16 17:23:54"
    ) == 1800.0


def test_reopen_selected_locator_keeps_other_decisions(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.record_packet(
        job["job_id"],
        sheet="СКС",
        packet_locators=["СКС!R2", "СКС!R3"],
        accepted_rows=[
            {"source_row": "СКС!R2", "norm_code": "10-01-001-01", "norm_status": "EXACT"},
            {"source_row": "СКС!R3", "norm_code": "10-01-002-01", "norm_status": "EXACT"},
        ],
        evidence=[],
        remaining=[],
    )
    service.finish(job["job_id"], status="complete")
    reopened = service.reopen_locators(job["job_id"], ["СКС!R3"])
    assert reopened["status"] == "paused"
    assert [row["source_row"] for row in reopened["accepted_rows"]] == ["СКС!R2"]
    assert reopened["remaining"] == ["СКС!R3"]

    overlay = service.record_overrides(
        job["job_id"],
        {"СКС!R2": {"conversion_factor": 12, "conversion_source": "упаковка", "norm_code": "hack"}},
    )
    assert overlay["operator_overrides"]["СКС!R2"]["conversion_factor"] == 12
    assert "norm_code" not in overlay["operator_overrides"]["СКС!R2"]


def test_complete_job_is_not_reopened(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.finish(job["job_id"], status="complete")
    again = service.begin_or_resume(_identity(service))
    assert again["status"] == "complete"
    assert again["resumable"] is False


def test_pause_keeps_should_cancel_true_until_resume(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.request_cancel(job["job_id"])
    assert service.should_cancel(job["job_id"]) is True
    paused = service.pause(job["job_id"], remaining=["СКС!R3"])
    assert paused["status"] == "paused"
    assert paused["cancel_requested"] is False
    assert service.should_cancel(job["job_id"]) is True
    resumed = service.begin_or_resume(_identity(service))
    assert resumed["status"] == "running"
    assert service.should_cancel(job["job_id"]) is False


def test_list_active_prefers_session_then_newest_running(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    first = service.begin_or_resume(_identity(service))
    service.record_packet(
        first["job_id"],
        sheet="СКС",
        packet_locators=["СКС!R2"],
        accepted_rows=[{"source_row": "СКС!R2", "norm_code": "10-01-001-01", "row_role": "work"}],
        evidence=[],
        remaining=["СКС!R3"],
    )
    other = service.begin_or_resume(
        service.identity(
            session_id="session-2",
            attachment_id="read_123456abcdef",
            source_sha256="b" * 64,
            dataset_ids=["smeta"],
            profile_revision_id="factory",
            model_identity="qwen-35b",
            question="Собери ЛСР",
        )
    )
    matched = service.list_active(session_id="session-1")
    assert matched[0]["job_id"] == first["job_id"]
    other_match = service.list_active(session_id="session-2")
    assert other_match[0]["job_id"] == other["job_id"]
    unknown = service.list_active(session_id="missing")
    assert unknown[0]["job_id"] in {first["job_id"], other["job_id"]}


def test_list_open_returns_paused_when_session_has_no_running(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.record_packet(
        job["job_id"],
        sheet="СКС",
        packet_locators=["СКС!R75"],
        accepted_rows=[{"source_row": "СКС!R6", "row_role": "material"}],
        evidence=[],
        remaining=[],
    )
    paused = service.pause(
        job["job_id"],
        remaining=["СКС!R3", "СКС!R4"],
        phase="packets",
    )
    assert paused["status"] == "paused"
    assert service.list_active(session_id="session-1") == []
    opened = service.list_open(session_id="session-1")
    assert opened[0]["job_id"] == job["job_id"]
    assert opened[0]["status"] == "paused"
    assert opened[0]["remaining"] == ["СКС!R3", "СКС!R4"]


def test_record_packet_keeps_material_and_work_on_same_locator(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.record_packet(
        job["job_id"],
        sheet="PDF",
        packet_locators=["PDF!R9"],
        accepted_rows=[
            {
                "source_row": "PDF!R9",
                "row_role": "work",
                "norm_code": "ГЭСН17-01-010-02",
                "norm_status": "NEEDS_RESEARCH",
            }
        ],
        evidence=[],
        remaining=[],
    )
    service.record_packet(
        job["job_id"],
        sheet="PDF",
        packet_locators=["PDF!R9"],
        accepted_rows=[
            {
                "source_row": "PDF!R9",
                "row_role": "material",
                "title": "Люк ревизионный",
                "norm_status": "MISSING",
            }
        ],
        evidence=[],
        remaining=[],
    )
    stored = service.get(job["job_id"])["accepted_rows"]
    roles = {(row["source_row"], row["row_role"]) for row in stored}
    assert roles == {("PDF!R9", "work"), ("PDF!R9", "material")}


def test_legacy_cancelled_finish_becomes_resumable_pause(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    paused = service.finish(job["job_id"], status="cancelled")
    assert paused["status"] == "paused"
    resumed = service.begin_or_resume(_identity(service))
    assert resumed["status"] == "running"


def _stage_a_rows():
    return [
        {
            "source_row": "СКС!R47",
            "row_role": "work",
            "title": "Монтаж лотка",
            "norm_code": "ГЭСН21-03-004-02",
            "norm_status": "ANALOGUE_CANDIDATE",
        },
        {
            "source_row": "СКС!R47",
            "row_role": "work",
            "title": "Монтаж лотка",
            "norm_status": "NEEDS_RESEARCH",
        },
        {
            "source_row": "СКС!R47",
            "row_role": "material",
            "title": "Лоток лестничный 300 мм",
        },
    ]


def test_two_works_and_material_on_one_locator_survive_resume(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.record_packet(
        job["job_id"],
        sheet="СКС",
        packet_locators=["СКС!R47"],
        accepted_rows=_stage_a_rows(),
        evidence=[],
        remaining=["СКС!R48"],
    )
    service.pause(job["job_id"], remaining=["СКС!R48"])
    resumed = service.begin_or_resume(_identity(service))
    rows = resumed["accepted_rows"]
    assert len(rows) == 3
    ops = {str(row["operation_id"]) for row in rows}
    assert len(ops) == 3
    assert resumed["status_dimensions"]["operations"] == 3
    # Identical re-delivery (model repeats the same packet) adds nothing.
    service.record_packet(
        job["job_id"],
        sheet="СКС",
        packet_locators=["СКС!R47"],
        accepted_rows=_stage_a_rows(),
        evidence=[],
        remaining=["СКС!R48"],
    )
    after = service.get(job["job_id"])
    assert len(after["accepted_rows"]) == 3
    assert {str(row["operation_id"]) for row in after["accepted_rows"]} == ops


def test_refine_unfinished_decision_keeps_original_revision(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    original = {
        "source_row": "СКС!R10",
        "row_role": "work",
        "title": "Монтаж шкафа",
        "norm_status": "NEEDS_RESEARCH",
    }
    service.record_packet(
        job["job_id"],
        sheet="СКС",
        packet_locators=["СКС!R10"],
        accepted_rows=[original],
        evidence=[],
        remaining=[],
    )
    stored = service.get(job["job_id"])["accepted_rows"][0]
    op = str(stored["operation_id"])
    refined = dict(original)
    refined.update({"norm_code": "10-01-001-01", "norm_status": "EXACT"})
    service.replace_accepted_rows(job["job_id"], [refined])
    current = service.get(job["job_id"])["accepted_rows"][0]
    assert current["operation_id"] == op
    assert int(current["revision"]) == 2
    assert current["norm_status"] == "EXACT"
    revisions = service.list_revisions(job["job_id"], op)
    assert [item["revision"] for item in revisions] == [1, 2]
    assert revisions[0]["decision"]["norm_status"] == "NEEDS_RESEARCH"
    assert revisions[1]["origin"] == "operator"


def test_record_revision_stale_guard(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    row = {
        "source_row": "СКС!R12",
        "row_role": "work",
        "title": "Прокладка кабеля",
        "norm_status": "NEEDS_RESEARCH",
    }
    service.record_packet(
        job["job_id"],
        sheet="СКС",
        packet_locators=["СКС!R12"],
        accepted_rows=[row],
        evidence=[],
        remaining=[],
    )
    op = str(service.get(job["job_id"])["accepted_rows"][0]["operation_id"])
    first_patch = dict(row, norm_status="ANALOGUE_CANDIDATE", norm_code="ГЭСН21-03-004-02")
    service.record_revision(
        job["job_id"], operation_id=op, decision=first_patch, base_revision=1
    )
    assert int(service.get(job["job_id"])["accepted_rows"][0]["revision"]) == 2
    late_patch = dict(row, norm_status="EXACT", norm_code="01-01-001-01")
    with pytest.raises(WorkbookResearchJobError, match="stale revision"):
        service.record_revision(
            job["job_id"], operation_id=op, decision=late_patch, base_revision=1
        )
    assert int(service.get(job["job_id"])["accepted_rows"][0]["revision"]) == 2


def test_legacy_operation_ids_are_stable_and_never_merged_by_title(tmp_path) -> None:
    legacy_a = {"source_row": "СКС!R5", "row_role": "work", "title": "Монтаж лотка"}
    legacy_b = {"source_row": "СКС!R5", "row_role": "work", "title": "Монтаж лотка",
                "norm_code": "ГЭСН21-03-004-02"}
    assert _legacy_operation_id("wrj_x", legacy_a) == _legacy_operation_id("wrj_x", dict(legacy_a))
    assert _legacy_operation_id("wrj_x", legacy_a) != _legacy_operation_id("wrj_x", legacy_b)
    assert _legacy_operation_id("wrj_x", legacy_a) != _legacy_operation_id("wrj_y", legacy_a)

    db = tmp_path / "meta.db"
    service = WorkbookResearchJobService(db)
    job = service.begin_or_resume(_identity(service))
    legacy_rows = [dict(legacy_a), dict(legacy_a), dict(legacy_b)]
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE workbook_research_jobs SET accepted_rows_json=? WHERE job_id=?",
            (__import__("json").dumps(legacy_rows, ensure_ascii=False), job["job_id"]),
        )
    service.record_packet(
        job["job_id"],
        sheet="СКС",
        packet_locators=["СКС!R5"],
        accepted_rows=[{"source_row": "СКС!R5", "row_role": "material", "title": "Лоток"}],
        evidence=[],
        remaining=[],
    )
    stored = service.get(job["job_id"])["accepted_rows"]
    legacy_ids = [str(item["operation_id"]) for item in stored[:3]]
    # Two byte-identical legacy rows still get distinct ids (no title merging).
    assert len(set(legacy_ids)) == 3
    assert sum(1 for item in legacy_ids if item.startswith("op_leg_")) == 2
    # Ids are persisted: a fresh service instance reuses stored identifiers.
    reopened = WorkbookResearchJobService(db).get(job["job_id"])
    assert [str(item["operation_id"]) for item in reopened["accepted_rows"]] == [
        str(item["operation_id"]) for item in stored
    ]
    revisions = WorkbookResearchJobService(db).list_revisions(job["job_id"])
    migrated = [item for item in revisions if item["origin"] == "migration"]
    assert {item["operation_id"] for item in migrated} == set(legacy_ids)
