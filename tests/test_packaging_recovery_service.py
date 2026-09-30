"""Packaging recovery: a finished job must never be left without its file."""

import os

import pytest

from proxy.services.packaging_recovery_service import (
    describe_packaging_document,
    packaging_fault,
    packaging_recovery_payload,
    release_memory_for_packaging,
    reset_packaging_fault,
    workbook_document_from_events,
)


def test_vor_job_recovers_its_actual_workbook_kind():
    document = workbook_document_from_events([{
        "event": "workbook_packaged", "data": {
            "tool": "build_vor_workbook", "revision_id": "rev_vor", "draft": False,
        },
    }, {
        "event": "packet_accepted", "data": {"tool": "build_lsr_workbook"},
    }], status="complete")
    assert document["state"] == "ready"
    assert document["artifact_kind"] == "vor_workbook"
    assert document["tool"] == "build_vor_workbook"
    assert document["final_revision_id"] == "rev_vor"


def _packaged(revision_id: str, *, draft: bool = False, tool: str = "build_lsr_workbook"):
    return {
        "sequence": 1,
        "event_type": "workbook_packaged",
        "payload": {"tool": tool, "revision_id": revision_id, "draft": draft},
    }


def test_completed_job_without_final_packaging_is_durable_pending() -> None:
    """The MemoryError case: the research is over, the file is not."""

    document = describe_packaging_document([], status="complete")

    assert document["state"] == "pending"
    assert document["needs_document"] is True
    assert [item["id"] for item in document["actions"]] == ["repack"]
    # Recovery is the single documented repair, and it never calls the model.
    assert document["actions"][0]["kind"] == "repack"


def test_draft_of_finished_job_is_not_reported_as_ready() -> None:
    """An intermediate draft must never masquerade as the finished document."""

    document = describe_packaging_document(
        [_packaged("rev_draft", draft=True)], status="complete"
    )

    assert document["state"] == "draft_only"
    assert document["needs_document"] is True
    assert document["draft_revision_id"] == "rev_draft"
    assert document["final_revision_id"] == ""


def test_draft_while_job_is_open_is_not_a_missing_document() -> None:
    document = describe_packaging_document(
        [_packaged("rev_draft", draft=True)], status="paused"
    )

    assert document["state"] == "none"
    assert document["needs_document"] is False
    assert document["actions"] == []


def test_final_packaging_after_repair_stops_offering_repair() -> None:
    document = describe_packaging_document(
        [_packaged("rev_draft", draft=True), _packaged("rev_final")],
        status="complete",
    )

    assert document["state"] == "ready"
    assert document["final_revision_id"] == "rev_final"
    assert document["needs_document"] is False
    assert document["actions"] == []


def test_events_of_the_other_workbook_do_not_close_the_lsr_document() -> None:
    document = describe_packaging_document(
        [_packaged("rev_vor", tool="build_vor_workbook")], status="complete"
    )

    assert document["state"] == "pending"


def test_recovery_payload_carries_saved_decisions_and_no_model_call() -> None:
    job = {
        "job_id": "wrj_1",
        "status": "complete",
        "identity": {
            "session_id": "s-1",
            "attachment_id": "read_abc",
            "question": "Собери ЛСР по ВОР",
        },
        "accepted_rows": [
            {"source_row": "АР!R11", "norm_code": "ГЭСНр1-01"},
            {"source_row": "ВК!R4", "norm_code": ""},
        ],
        "remaining": ["ОВиК!R20", ""],
    }
    document = describe_packaging_document([], status="complete")

    payload = packaging_recovery_payload(job, document)

    assert payload["model_called"] is False
    assert payload["endpoint"] == "/api/chat/repack-lsr"
    assert payload["job_id"] == "wrj_1"
    assert payload["attachment_id"] == "read_abc"
    assert payload["decision_count"] == 2
    assert payload["remaining"] == ["ОВиК!R20"]
    assert payload["actions"] == [{"id": "repack", "label": "Пересобрать файл", "kind": "repack"}]


def test_memory_relief_releases_the_packaging_reference_tables() -> None:
    report = release_memory_for_packaging(reason="test")

    # A missing optional loader is recorded, never raised: relief cannot become
    # the reason a run fails.
    assert report["released"] == sorted(report["released"])
    assert "fgis_pricebook" in report["released"]
    assert report["collected"] >= 0
    assert isinstance(report["errors"], list)


def test_packaging_fault_is_inert_until_the_operator_asks(monkeypatch) -> None:
    monkeypatch.delenv("LES_DEBUG_PACKAGING_FAULT", raising=False)

    assert packaging_fault() is None


@pytest.mark.parametrize("alias", ["MemoryError", "memory", "OOM"])
def test_packaging_fault_reproduces_the_memory_incident(monkeypatch, alias) -> None:
    monkeypatch.setenv("LES_DEBUG_PACKAGING_FAULT", alias)
    monkeypatch.delenv("LES_DEBUG_PACKAGING_FAULT_ROUNDS", raising=False)
    reset_packaging_fault()

    with pytest.raises(MemoryError):
        packaging_fault()


def test_injected_fault_stops_after_the_configured_rounds(monkeypatch) -> None:
    """The repair must be observable: the turn fails, the later rebuild works."""

    monkeypatch.setenv("LES_DEBUG_PACKAGING_FAULT", "MemoryError")
    monkeypatch.setenv("LES_DEBUG_PACKAGING_FAULT_ROUNDS", "1")
    reset_packaging_fault()

    with pytest.raises(MemoryError):
        packaging_fault()
    assert packaging_fault() is None


def test_unknown_injected_fault_stays_inert(monkeypatch) -> None:
    monkeypatch.setenv("LES_DEBUG_PACKAGING_FAULT", "KeyboardInterrupt")

    assert packaging_fault() is None


def test_environment_is_read_on_every_call_so_clearing_restores_packaging(monkeypatch) -> None:
    monkeypatch.setenv("LES_DEBUG_PACKAGING_FAULT", "RuntimeError")
    monkeypatch.delenv("LES_DEBUG_PACKAGING_FAULT_ROUNDS", raising=False)
    reset_packaging_fault()

    with pytest.raises(RuntimeError):
        packaging_fault()

    monkeypatch.delenv("LES_DEBUG_PACKAGING_FAULT")
    assert packaging_fault() is None
    assert os.environ.get("LES_DEBUG_PACKAGING_FAULT") is None


# --------------------------------------------------------------------------- #
# The loop the customer sees: a finished job with no file is repaired from the
# interface, and the repair closes the durable state.
# --------------------------------------------------------------------------- #
def _identity(service, question: str = "Собери ЛСР по ВОР"):
    return service.identity(
        session_id="session-1",
        attachment_id="read_123456abcdef",
        source_sha256="b" * 64,
        dataset_ids=["smeta"],
        profile_revision_id="factory",
        model_identity="qwen-35b",
        question=question,
    )


def _finished_job_without_document(tmp_path):
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService

    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.record_packet(
        job["job_id"],
        sheet="АР",
        packet_locators=["АР!R11"],
        accepted_rows=[
            {
                "source_row": "АР!R11",
                "norm_code": "ГЭСНр1-01-001",
                "norm_status": "EXACT",
                "row_role": "work",
            }
        ],
        evidence=[],
        remaining=[],
        held_packet={},
    )
    service.finish(job["job_id"], status="complete")
    return service, job


def test_router_reports_the_finished_job_the_active_list_hides(tmp_path, monkeypatch) -> None:
    import asyncio

    from proxy.routers import chat as chat_router

    service, job = _finished_job_without_document(tmp_path)
    monkeypatch.setattr(chat_router, "WorkbookResearchJobService", lambda: service)

    answer = asyncio.run(chat_router.get_last_workbook_research(session_id="session-1", _user=None))

    assert answer["found"] is True
    assert answer["job"]["job_id"] == job["job_id"]
    assert answer["document"]["state"] == "pending"
    assert answer["document_recovery"]["model_called"] is False


def test_router_never_invents_a_finished_research(tmp_path, monkeypatch) -> None:
    import asyncio

    from proxy.routers import chat as chat_router

    service, _job = _finished_job_without_document(tmp_path)
    monkeypatch.setattr(chat_router, "WorkbookResearchJobService", lambda: service)

    answer = asyncio.run(
        chat_router.get_last_workbook_research(session_id="other", _user=None)
    )

    assert answer == {"schema": "les.workbook-research-last.v1", "found": False, "job": None}


def test_repack_from_the_interface_records_the_final_document_and_closes_the_state(
    tmp_path, monkeypatch
) -> None:
    """Recovery must be observable twice: file now, and on the next re-entry."""

    import asyncio

    from proxy.routers import chat as chat_router
    from proxy.services.chat_evidence_application_service import (
        execute_workbook_with_bounded_retry,
    )

    service, job = _finished_job_without_document(tmp_path)
    monkeypatch.setattr(chat_router, "WorkbookResearchJobService", lambda: service)
    monkeypatch.setattr(
        chat_router,
        "execute_workbook_with_bounded_retry",
        _fake_packaging(execute_workbook_with_bounded_retry, "rev_repaired"),
    )

    answer = asyncio.run(
        chat_router.repack_lsr_without_model(
            chat_router.LsrRepackRequest(
                session_id="session-1",
                job_id=job["job_id"],
                # No decisions are sent: the repair reads the saved set itself.
            ),
            _user=None,
        )
    )

    assert answer["model_called"] is False
    artifact = answer["harvested"]["artifact"]
    assert artifact["download_url"] == "/api/artifacts/rev_repaired/download"
    assert artifact["document_state"]["state"] == "ready"
    assert [item["id"] for item in artifact["result_readiness"]["actions"]] == []

    # And a later re-entry reads the same durable truth from the job alone.
    stored = service.get(job["job_id"])
    assert stored["document"]["state"] == "ready"
    assert stored["document"]["final_revision_id"] == "rev_repaired"
    assert "document_recovery" not in stored


def test_failed_repack_leaves_the_job_repairable(tmp_path, monkeypatch) -> None:
    import asyncio

    from proxy.routers import chat as chat_router
    from proxy.services.chat_evidence_application_service import (
        execute_workbook_with_bounded_retry,
    )

    service, job = _finished_job_without_document(tmp_path)
    monkeypatch.setattr(chat_router, "WorkbookResearchJobService", lambda: service)
    monkeypatch.setattr(
        chat_router,
        "execute_workbook_with_bounded_retry",
        _fake_packaging(execute_workbook_with_bounded_retry, "", failed=True),
    )

    answer = asyncio.run(
        chat_router.repack_lsr_without_model(
            chat_router.LsrRepackRequest(session_id="session-1", job_id=job["job_id"]),
            _user=None,
        )
    )

    readiness = answer["harvested"]["artifact"]["result_readiness"]
    assert "repack" in {item["id"] for item in readiness["actions"]}
    assert service.get(job["job_id"])["document"]["needs_document"] is True


def test_vor_repack_preserves_document_type_and_revision_lineage(tmp_path, monkeypatch):
    import asyncio

    from proxy.routers import chat as chat_router

    service, job = _finished_job_without_document(tmp_path)
    service.record_packaging(
        job["job_id"], tool="build_vor_workbook", revision_id="rev_vor_first", draft=False,
    )
    calls = []
    packaging = _fake_packaging(None, "rev_vor_second")

    async def capture(executor, call, request_context, progress_sink, **kwargs):
        from proxy.services.workbook_tool_service import BUILD_VOR_WORKBOOK

        assert set(call["args"]) <= set(BUILD_VOR_WORKBOOK.input_schema["properties"])
        calls.append(call)
        return await packaging(executor, call, request_context, progress_sink, **kwargs)

    monkeypatch.setattr(chat_router, "WorkbookResearchJobService", lambda: service)
    monkeypatch.setattr(chat_router, "execute_workbook_with_bounded_retry", capture)
    answer = asyncio.run(chat_router.repack_lsr_without_model(
        chat_router.LsrRepackRequest(session_id="session-1", job_id=job["job_id"]), _user=None,
    ))
    assert answer["model_called"] is False
    assert calls[0]["tool"] == "build_vor_workbook"
    assert calls[0]["args"]["parent_revision_id"] == "rev_vor_first"
    artifact = answer["harvested"]["artifact"]
    assert artifact["artifact_kind"] == "vor_workbook"
    assert artifact["document_state"]["state"] == "ready"
    assert "result_readiness" not in artifact  # no LSR norm/price requirements
    stored = service.get(job["job_id"])["document"]
    assert stored["tool"] == "build_vor_workbook"
    assert stored["final_revision_id"] == "rev_vor_second"
    events = service.list_events(job["job_id"], "workbook_packaged")
    assert events[-1]["payload"]["parent_revision_id"] == "rev_vor_first"


def _fake_packaging(_real, revision_id: str, *, failed: bool = False):
    """Stand in for the packaging call; the saved decisions are what matter."""

    async def runner(executor, call, request_context, progress_sink, **kwargs):
        args = call.get("args") or {}
        assert args.get("decisions"), "recovery must reuse the saved model decisions"
        if failed:
            return (
                {
                    "schema": "les.workbook_tool_result.v1",
                    "status": "failed",
                    "code": "WORKBOOK_GENERATION_FAILED",
                    "error_type": "MemoryError",
                    "message": "injected",
                },
                [{"tool": call.get("tool"), "attempt": 1, "status": "failed"}],
            )
        return (
            {
                "schema": "les.workbook_tool_result.v1",
                "tool": call.get("tool"),
                "status": "complete",
                "artifact": {
                    "schema": "les.artifact_revision.v1",
                    "artifact_id": "art_1",
                    "revision_id": revision_id,
                    "revision_no": 2,
                    "artifact_kind": "vor_workbook" if call.get("tool") == "build_vor_workbook" else "lsr_workbook",
                    "byte_size": 1024,
                    "sha256": "c" * 64,
                    "download_url": f"/api/artifacts/{revision_id}/download",
                    "filename": "ЛСР.xlsx",
                    "decision_checkpoint_id": "cp_1",
                    "source_scope": [f"attachment:{args.get('attachment_id')}"],
                },
                "source": {
                    "attachment_id": args.get("attachment_id"),
                    "sha256": "b" * 64,
                },
                "checkpoint": {"checkpoint_id": "cp_1", "status": "complete"},
            },
            [{"tool": call.get("tool"), "attempt": 1, "status": "complete"}],
        )

    return runner
