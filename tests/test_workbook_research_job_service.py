from proxy.services.workbook_research_job_service import WorkbookResearchJobService


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
