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


def test_legacy_cancelled_finish_becomes_resumable_pause(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    paused = service.finish(job["job_id"], status="cancelled")
    assert paused["status"] == "paused"
    resumed = service.begin_or_resume(_identity(service))
    assert resumed["status"] == "running"
