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


def test_search_cache_event_carries_packet_context(tmp_path) -> None:
    import json

    service = WorkbookResearchJobService(tmp_path / "meta.db")
    first = service.begin_or_resume(_identity(service))
    service.record_search_cache(
        first["job_id"],
        {
            "\u043b\u043e\u0442\u043e\u043a \u0434\u043e 200": [
                {"content": "\u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0430", "doc_id": "c1", "doc_name": "d", "score": 1.0, "meta": {}}
            ]
        },
        context={
            "sheet": "\u0421\u041a\u0421",
            "packet_id": "packet_ctx",
            "locators": ["\u0421\u041a\u0421!R47", "\u0421\u041a\u0421!R48"],
            "queries": ["\u043b\u043e\u0442\u043e\u043a \u0434\u043e 200"],
        },
    )
    # Legacy positional calls without context keep working unchanged.
    service.record_search_cache(
        first["job_id"],
        {
            "\u0434\u0440\u0443\u0433\u043e\u0439 \u0437\u0430\u043f\u0440\u043e\u0441": [
                {"content": "\u0435\u0449\u0451", "doc_id": "c2", "doc_name": "d", "score": 1.0, "meta": {}}
            ]
        },
    )
    events = [
        item
        for item in service.events_after(first["job_id"])
        if item["event"] == "search_cache"
    ]
    assert len(events) == 2
    with_context = events[0]["data"]
    assert with_context["sheet"] == "\u0421\u041a\u0421"
    assert with_context["packet_id"] == "packet_ctx"
    assert with_context["locators"] == ["\u0421\u041a\u0421!R47", "\u0421\u041a\u0421!R48"]
    assert with_context["queries"] == ["\u043b\u043e\u0442\u043e\u043a \u0434\u043e 200"]
    assert with_context["added"] == 1
    bare = events[1]["data"]
    assert "sheet" not in bare and bare["cached_total"] == 2
    cached = service.get(first["job_id"])["query_cache"]
    assert json.dumps(sorted(cached))  # both queries durable, order irrelevant


# ─── Directive §4: product-internal stall guard ───

def test_stall_guard_auto_pauses_after_threshold(tmp_path):
    """After STALL_THRESHOLD rounds without progress, job auto-pauses with reason."""
    from proxy.services.workbook_research_job_service import (
        WorkbookResearchJobService,
        WorkbookResearchIdentity,
        _STALL_THRESHOLD,
    )

    svc = WorkbookResearchJobService(tmp_path / "meta.db")
    identity = WorkbookResearchIdentity(
        session_id="s1",
        attachment_id="att1",
        source_sha256="abc",
        dataset_ids=(),
        profile_revision_id="p1",
        model_identity="m1",
        question_sha256="q1",
    )
    job = svc.begin_or_resume(identity)
    job_id = job["job_id"]

    remaining = ["r1", "r2", "r3"]
    # First round: no previous remaining, so it counts as progress from (empty) -> 3
    # Actually prev_remaining is [] initially, so len(3) > len(0) = no progress
    # Wait: made_progress = new < prev, so 3 < 0 is False... 
    # Let me set it up properly: first call sets remaining to 3.
    # Second call same 3: no progress -> stall_count=1
    # Third call same 3: no progress -> stall_count=2 >= threshold -> auto-pause

    # Round 1: establish remaining=3 (prev is [] so 3 not < 0 -> no progress, stall=1)
    # Hmm actually: prev_remaining = [] (len=0), new len=3, 3 < 0 is False, stall=1
    # That means first delivery already counts as stall. Let me check:
    # A fresh job has remaining_json=[], so prev_remaining=[] (len=0).
    # First record_packet with remaining=["r1","r2","r3"]: len(3) < len(0) is False -> stall++
    # This is wrong. Let's fix: first round should not count as stall because prev=0 is "not started".
    # Actually the semantics: if remaining == prev and both > 0, that's a stall.
    # If prev == 0 (initial) or prev == [] (fresh), it's the first batch, not a stall.
    
    # We'll test the real behavior: deliver same remaining multiple times
    # First: prev=[] -> new=["r1","r2","r3"]. made_progress = 3 < 0 = False. stall=1
    # Second: prev=["r1","r2","r3"] -> new=["r1","r2","r3"]. 3 < 3 = False. stall=2 >= threshold -> PAUSE
    
    result = None
    for i in range(_STALL_THRESHOLD + 1):
        result = svc.record_packet(
            job_id,
            sheet="Sheet1",
            packet_locators=["r1"],
            accepted_rows=[],
            evidence=[],
            omitted=[],
            remaining=remaining,
        )
        # Once paused, subsequent calls hit TERMINAL_STATUSES check...
        # Actually 'paused' is NOT in TERMINAL_STATUSES (only complete/failed). So it still processes.
        # But the UPDATE will still happen with should_auto_pause=True again.
        if result["status"] == "paused":
            break

    assert result["status"] == "paused", f"Expected paused, got {result['status']}"
    assert result["phase"] == "stalled"
    sg = result["stall_guard"]
    assert sg["stall_count"] >= _STALL_THRESHOLD
    assert "stalled" in sg["reason"]
    assert sg["round_count"] >= _STALL_THRESHOLD


def test_stall_guard_resets_on_progress(tmp_path):
    """Substantive progress (new operations) resets the stall streak.

    Directive §1 (22.09): progress is measured by *content produced*, not by a
    shrinking sheet-local ``remaining`` count. Each packet here delivers a brand
    new operation, so the streak stays at zero even though the pass also carries
    a non-empty remainder.
    """
    from proxy.services.workbook_research_job_service import (
        WorkbookResearchJobService,
        WorkbookResearchIdentity,
    )

    svc = WorkbookResearchJobService(tmp_path / "meta.db")
    identity = WorkbookResearchIdentity(
        session_id="s1",
        attachment_id="att1",
        source_sha256="abc",
        dataset_ids=(),
        profile_revision_id="p1",
        model_identity="m1",
        question_sha256="q1",
    )
    job = svc.begin_or_resume(identity)
    job_id = job["job_id"]

    for i, remaining in enumerate(
        (["r1", "r2", "r3"], ["r1", "r2"], ["r1"], []), start=1
    ):
        result = svc.record_packet(
            job_id,
            sheet="Sheet1",
            packet_locators=[f"Sheet1!R{i}"],
            accepted_rows=[
                {"source_row": f"Sheet1!R{i}", "norm_code": f"N{i}", "norm_status": "EXACT"}
            ],
            evidence=[],
            omitted=[],
            remaining=remaining,
        )
        assert result["stall_guard"]["stall_count"] == 0

    assert result["status"] == "running"
    assert len(result["accepted_rows"]) == 4


def test_no_absolute_round_ceiling_when_progressing(tmp_path):
    """Progressing packets must not pause on the old cumulative _MAX_ROUNDS ceiling.

    Directive §1 (22.09): sequential processing of NEW packets with real progress
    is not a loop. The former ``max_rounds`` pause trigger is removed; round_count
    keeps accumulating purely for reporting.
    """
    from proxy.services.workbook_research_job_service import (
        WorkbookResearchJobService,
        WorkbookResearchIdentity,
        _MAX_ROUNDS,
    )

    svc = WorkbookResearchJobService(tmp_path / "meta.db")
    identity = WorkbookResearchIdentity(
        session_id="s1",
        attachment_id="att1",
        source_sha256="abc",
        dataset_ids=(),
        profile_revision_id="p1",
        model_identity="m1",
        question_sha256="q1",
    )
    job = svc.begin_or_resume(identity)
    job_id = job["job_id"]

    result = None
    for i in range(1, _MAX_ROUNDS + 6):  # clearly past the old ceiling of 8
        remaining = [f"r{j}" for j in range(_MAX_ROUNDS + 6 - i, 0, -1)]
        result = svc.record_packet(
            job_id,
            sheet="Sheet1",
            packet_locators=[f"Sheet1!R{i}"],
            accepted_rows=[
                {"source_row": f"Sheet1!R{i}", "norm_code": f"N{i}", "norm_status": "EXACT"}
            ],
            evidence=[],
            omitted=[],
            remaining=remaining,
        )

    assert result["status"] == "running"
    assert "max_rounds" not in result["stall_guard"]["reason"]
    assert result["stall_guard"]["round_count"] >= _MAX_ROUNDS  # informational only


def test_no_progress_empty_packets_pause_as_stalled(tmp_path):
    """Empty (no-content) packets are a genuine stall and pause as 'stalled'."""
    from proxy.services.workbook_research_job_service import (
        WorkbookResearchJobService,
        WorkbookResearchIdentity,
        _STALL_THRESHOLD,
    )

    svc = WorkbookResearchJobService(tmp_path / "meta.db")
    identity = WorkbookResearchIdentity(
        session_id="s1",
        attachment_id="att1",
        source_sha256="abc",
        dataset_ids=(),
        profile_revision_id="p1",
        model_identity="m1",
        question_sha256="q1",
    )
    job = svc.begin_or_resume(identity)
    job_id = job["job_id"]

    result = None
    for _ in range(_STALL_THRESHOLD + 3):
        result = svc.record_packet(
            job_id,
            sheet="Sheet1",
            packet_locators=[],
            accepted_rows=[],
            evidence=[],
            omitted=[],
            remaining=["r1", "r2", "r3"],  # constant, no new content → no progress
        )
        if result["status"] == "paused":
            break

    assert result["status"] == "paused"
    assert "stalled" in result["stall_guard"]["reason"]


# ─── Directive §1 (22.09): split stall / progress counters ───
from proxy.services.workbook_research_job_service import (
    _RUN_PACKET_BUDGET,
    _STALL_THRESHOLD,
)


def _pkt_row(i: int) -> dict:
    # Each call yields a distinct, substantively new operation → real progress.
    return {"source_row": f"СКС!R{i}", "norm_code": f"N{i:04d}", "norm_status": "EXACT"}


def test_more_than_eight_progressing_packets_do_not_pause(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    for i in range(1, 13):  # 12 sequential packets, each with new content
        job = service.record_packet(
            job["job_id"],
            sheet="СКС",
            packet_locators=[f"СКС!R{i}"],
            accepted_rows=[_pkt_row(i)],
            evidence=[],
            remaining=[f"СКС!R{i + 1}"],
        )
    assert job["status"] == "running"
    sg = job["stall_guard"]
    assert sg["stall_count"] == 0
    assert sg["round_count"] == 12          # informational cumulative counter
    assert sg["run_round_count"] == 12      # well under the per-run budget
    assert len(job["accepted_rows"]) == 12


def test_sheet_transition_does_not_count_as_stall(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    # Sheet АР progresses and leaves a big local remainder.
    job = service.record_packet(
        job["job_id"],
        sheet="АР",
        packet_locators=["АР!R2"],
        accepted_rows=[{"source_row": "АР!R2", "norm_code": "A2", "norm_status": "EXACT"}],
        evidence=[],
        remaining=["АР!R3", "АР!R4", "АР!R5"],
    )
    # Move to sheet СКС: its local remaining list is LONGER, but this packet also
    # produces a NEW operation — that is progress, not a regression.
    job = service.record_packet(
        job["job_id"],
        sheet="СКС",
        packet_locators=["СКС!R2"],
        accepted_rows=[{"source_row": "СКС!R2", "norm_code": "K2", "norm_status": "EXACT"}],
        evidence=[],
        remaining=["СКС!R3", "СКС!R4", "СКС!R5", "СКС!R6", "СКС!R7"],
    )
    assert job["status"] == "running"
    assert job["stall_guard"]["stall_count"] == 0


def test_final_packet_with_empty_remainder_is_not_paused(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    job = service.record_packet(
        job["job_id"],
        sheet="СКС",
        packet_locators=["СКС!R2"],
        accepted_rows=[_pkt_row(2)],
        evidence=[],
        remaining=["СКС!R3"],
    )
    # Last packet: produces a new op AND leaves nothing remaining, nothing held.
    job = service.record_packet(
        job["job_id"],
        sheet="СКС",
        packet_locators=["СКС!R3"],
        accepted_rows=[_pkt_row(3)],
        evidence=[],
        remaining=[],
        held_packet={},
    )
    assert job["status"] == "running"
    assert job["stall_guard"]["reason"] == ""
    assert job["remaining"] == []


def test_no_progress_at_natural_completion_is_not_paused(tmp_path) -> None:
    """Live-bug regression (build 787): the final packets drained remaining to 0 but
    produced no NEW revision (nothing left to add).  The no-progress streak must NOT
    be reported as a paused stall once there is no outstanding work."""
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    job = service.record_packet(
        job["job_id"],
        sheet="\u0421\u041a\u0421",
        packet_locators=["\u0421\u041a\u0421!R2"],
        accepted_rows=[_pkt_row(2)],
        evidence=[],
        remaining=["\u0421\u041a\u0421!R3"],
    )
    # A packet that re-delivers the same row (no new revision) but still has work left.
    job = service.record_packet(
        job["job_id"],
        sheet="\u0421\u041a\u0421",
        packet_locators=["\u0421\u041a\u0421!R2"],
        accepted_rows=[_pkt_row(2)],
        evidence=[],
        remaining=["\u0421\u041a\u0421!R3"],
    )
    assert job["stall_guard"]["stall_count"] == 1  # streak building, but work remains
    assert job["status"] == "running"
    # Final packet: still no new revision AND now nothing remaining, nothing held.
    job = service.record_packet(
        job["job_id"],
        sheet="\u0421\u041a\u0421",
        packet_locators=["\u0421\u041a\u0421!R3"],
        accepted_rows=[_pkt_row(2)],
        evidence=[],
        remaining=[],
        held_packet={},
    )
    sg = job["stall_guard"]
    assert job["status"] != "paused"
    assert "remaining=0" not in (sg.get("reason") or "")
    assert job["remaining"] == []


def test_stall_reason_disambiguates_sheet_local_from_global_remaining(tmp_path) -> None:
    """Directive §2 (23.09): the stall reason previously printed a bare
    ``remaining=N`` that was the *sheet-local* tail, while job.remaining holds the
    *global* document remainder — identical label, different scope (the 314-vs-13
    customer confusion).  The reason must now label the scope and name the sheet, and
    the API must expose the stall sheet."""
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    reason = ""
    for _ in range(4):
        job = service.record_packet(
            job["job_id"],
            sheet="\u0410\u0420",
            packet_locators=["\u0410\u0420!R2"],
            accepted_rows=[_pkt_row(2)],
            evidence=[],
            remaining=["\u0410\u0420!R3", "\u0410\u0420!R4"],
        )
        reason = job["stall_guard"]["reason"]
        if job["status"] == "paused":
            break
    assert job["status"] == "paused", reason
    assert "sheet_remaining" in reason
    assert "global document remainder" in reason
    assert "(remaining=" not in reason  # no bare, scope-less 'remaining='
    assert job["stall_guard"]["sheet"] == "\u0410\u0420"
    assert job["stall_guard"]["remaining_scope"] == "sheet_local_in_reason_global_in_remaining"
    # the persisted remaining is the sheet tail passed here; global is set by pause().
    assert len(job["remaining"]) == 2


def test_no_progress_triggers_bounded_pause(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    job = service.record_packet(
        job["job_id"],
        sheet="СКС",
        packet_locators=["СКС!R2"],
        accepted_rows=[_pkt_row(2)],
        evidence=[],
        remaining=["СКС!R9"],
    )
    # Two subsequent packets re-deliver the SAME row (no new revision), resolve no
    # new omitted rows, hold nothing → genuine lack of progress.
    for _ in range(_STALL_THRESHOLD):
        job = service.record_packet(
            job["job_id"],
            sheet="СКС",
            packet_locators=["СКС!R2"],
            accepted_rows=[_pkt_row(2)],  # identical → deduped, new_revisions empty
            evidence=[],
            remaining=["СКС!R9"],
        )
    assert job["status"] == "paused"
    assert "stalled" in job["stall_guard"]["reason"]
    assert job["stall_guard"]["stall_count"] >= _STALL_THRESHOLD


def test_run_budget_pause_is_continuable_and_resets(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    i = 0
    while i < _RUN_PACKET_BUDGET + 20:
        i += 1
        job = service.record_packet(
            job["job_id"],
            sheet="СКС",
            packet_locators=[f"СКС!R{i}"],
            accepted_rows=[_pkt_row(i)],
            evidence=[],
            remaining=["СКС!REND"],  # work still outstanding → run_budget may fire
        )
        if job["status"] == "paused":
            break
    assert job["status"] == "paused"
    assert "run_budget" in job["stall_guard"]["reason"]
    assert job["stall_guard"]["run_round_count"] == _RUN_PACKET_BUDGET
    # Resume starts a fresh run budget and does not immediately re-pause.
    job = service.begin_or_resume(_identity(service))
    assert job["status"] == "running"
    assert job["stall_guard"]["run_round_count"] == 0
    cumulative_before = job["stall_guard"]["round_count"]
    for j in range(i + 1, i + 6):
        job = service.record_packet(
            job["job_id"],
            sheet="СКС",
            packet_locators=[f"СКС!R{j}"],
            accepted_rows=[_pkt_row(j)],
            evidence=[],
            remaining=["СКС!REND"],
        )
    assert job["status"] == "running"
    assert job["stall_guard"]["run_round_count"] < _RUN_PACKET_BUDGET
    # round_count keeps accumulating (informational) yet never blocks processing.
    assert job["stall_guard"]["round_count"] > cumulative_before


def test_legacy_high_round_count_continues_safely(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    # Simulate a job persisted by the pre-fix code: it already blew the old
    # cumulative ceiling and carries a stale stall streak.
    with service._connect() as conn:
        conn.execute(
            "UPDATE workbook_research_jobs SET round_count=999, stall_count=3 WHERE job_id=?",
            (job["job_id"],),
        )
    # A single progressing packet must NOT pause: round_count is informational and
    # the fresh progress clears the stall streak.
    job = service.record_packet(
        job["job_id"],
        sheet="СКС",
        packet_locators=["СКС!R50"],
        accepted_rows=[_pkt_row(50)],
        evidence=[],
        remaining=["СКС!R51"],
    )
    assert job["status"] == "running"
    assert job["stall_guard"]["stall_count"] == 0
    assert len(job["accepted_rows"]) == 1


def test_reworded_open_gap_on_same_row_does_not_duplicate(tmp_path) -> None:
    """Directive §3 (23.09) live-bug regression: a paused small-control ВОР job
    resumed to complete, but the durable ledger listed section-header source rows
    (ВОР!R4 / ВОР!R6) three times -- the model re-proposed the same unresolved
    decision each round with only the free-text open_gap reworded. open_gap must
    not introduce a new durable decision."""
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    first = {
        "source_row": "\u0412\u041e\u0420!R4",
        "row_role": "unresolved",
        "row_classification": "ambiguous",
        "title": "\u041f\u043e\u043b\u0435\u0432\u044b\u0435 \u0440\u0430\u0431\u043e\u0442\u044b",
        "norm_code": "-",
        "norm_status": "MISSING",
        "open_gap": "\u0420\u0430\u0437\u0434\u0435\u043b \u043d\u0435 \u0438\u043c\u0435\u0435\u0442 \u0441\u043e\u0441\u0442\u0430\u0432\u0430.",
    }
    service.record_packet(
        job["job_id"],
        sheet="\u0412\u041e\u0420",
        packet_locators=["\u0412\u041e\u0420!R4"],
        accepted_rows=[dict(first)],
        evidence=[],
        remaining=["\u0412\u041e\u0420!R5"],
    )
    service.pause(job["job_id"], remaining=["\u0412\u041e\u0420!R5"])
    resumed = service.begin_or_resume(_identity(service))
    assert resumed["job_id"] == job["job_id"]
    # A later round re-proposes the SAME decision with different prose.
    reworded = dict(first)
    reworded["open_gap"] = "\u0422\u0440\u0435\u0431\u0443\u0435\u0442\u0441\u044f \u0434\u0435\u0442\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u044f \u0440\u0430\u0437\u0434\u0435\u043b\u0430."
    service.record_packet(
        resumed["job_id"],
        sheet="\u0412\u041e\u0420",
        packet_locators=["\u0412\u041e\u0420!R4"],
        accepted_rows=[reworded],
        evidence=[],
        remaining=[],
    )
    stored = service.get(job["job_id"])["accepted_rows"]
    same = [r for r in stored if r["source_row"] == "\u0412\u041e\u0420!R4"]
    assert len(same) == 1, f"open_gap rewording duplicated the decision: {same}"


def test_different_norm_decisions_on_one_locator_still_distinct(tmp_path) -> None:
    """Guard: marking open_gap volatile must NOT merge operations that differ in
    norm_status/norm_code -- the intended two-works-on-one-locator capability."""
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.record_packet(
        job["job_id"],
        sheet="\u0412\u041e\u0420",
        packet_locators=["\u0412\u041e\u0420!R9"],
        accepted_rows=[
            {
                "source_row": "\u0412\u041e\u0420!R9",
                "row_role": "work",
                "title": "\u041c\u043e\u043d\u0442\u0430\u0436",
                "norm_code": "\u0413\u042d\u0421\u041d17-01-010-02",
                "norm_status": "ANALOGUE_CANDIDATE",
                "open_gap": "",
            },
            {
                "source_row": "\u0412\u041e\u0420!R9",
                "row_role": "work",
                "title": "\u041c\u043e\u043d\u0442\u0430\u0436",
                "norm_code": "",
                "norm_status": "MISSING",
                "open_gap": "\u041d\u0435\u0442 \u043d\u043e\u0440\u043c\u044b.",
            },
        ],
        evidence=[],
        remaining=[],
    )
    stored = service.get(job["job_id"])["accepted_rows"]
    assert len([r for r in stored if r["source_row"] == "\u0412\u041e\u0420!R9"]) == 2


def test_record_packaging_events_keep_last_revision_per_tool(tmp_path) -> None:
    # Packaging lineage: the next pass chains from the last revision this job
    # packaged for the same tool; drafts stay visible in the event history.
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.record_packaging(
        job["job_id"], tool="build_lsr_workbook", revision_id="rev_draft", draft=True
    )
    service.record_packaging(
        job["job_id"], tool="build_vor_workbook", revision_id="rev_vor", draft=True
    )
    service.record_packaging(
        job["job_id"], tool="build_lsr_workbook", revision_id="rev_final", draft=False
    )

    latest: dict[str, dict] = {}
    for event in service.list_events(job["job_id"], event_type="workbook_packaged"):
        payload = event["payload"]
        latest[str(payload["tool"])] = payload

    assert latest["build_lsr_workbook"] == {
        "tool": "build_lsr_workbook",
        "revision_id": "rev_final",
        "draft": False,
        "parent_revision_id": "",
    }
    assert latest["build_vor_workbook"]["revision_id"] == "rev_vor"
    assert latest["build_vor_workbook"]["draft"] is True


def test_record_packaging_keeps_parent_revision_and_sequence(tmp_path) -> None:
    # A settled final revision is replayed with its own call identity, so the
    # event has to remember which parent that call was built with.
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    first = service.record_packaging(
        job["job_id"], tool="build_lsr_workbook", revision_id="rev_draft", draft=True
    )
    second = service.record_packaging(
        job["job_id"],
        tool="build_lsr_workbook",
        revision_id="rev_final",
        draft=False,
        parent_revision_id="rev_draft",
    )

    events = service.list_events(job["job_id"], event_type="workbook_packaged")
    assert [event["payload"]["parent_revision_id"] for event in events] == [
        "",
        "rev_draft",
    ]
    assert [event["sequence"] for event in events] == [first, second]
    assert first < second


def test_completed_job_without_packaging_reports_durable_pending_document(tmp_path) -> None:
    # The MemoryError incident: the research is terminal, the file is missing.
    # Only the durable job can tell a reopened client that, so `get()` carries it.
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.record_packet(
        job["job_id"],
        sheet="АР",
        packet_locators=["АР!R11"],
        accepted_rows=[{"source_row": "АР!R11", "norm_code": "ГЭСНр1-01"}],
        evidence=[],
        remaining=[],
        held_packet={},
    )
    service.finish(job["job_id"], status="complete")

    stored = service.get(job["job_id"])

    assert stored["status"] == "complete"
    assert stored["document"]["state"] == "pending"
    assert stored["document"]["needs_document"] is True
    # The repair needs no model and no new research: the saved decisions ship
    # with the job, so the interface can rebuild the file from them alone.
    recovery = stored["document_recovery"]
    assert recovery["model_called"] is False
    assert recovery["decision_count"] == 1
    assert recovery["attachment_id"] == "read_123456abcdef"


def test_final_packaging_flips_the_completed_job_document_to_ready(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.record_packet(
        job["job_id"],
        sheet="АР",
        packet_locators=["АР!R11"],
        accepted_rows=[{"source_row": "АР!R11", "norm_code": "ГЭСНр1-01"}],
        evidence=[],
        remaining=[],
        held_packet={},
    )
    service.finish(job["job_id"], status="complete")
    service.record_packaging(
        job["job_id"], tool="build_lsr_workbook", revision_id="rev_final", draft=False
    )

    stored = service.get(job["job_id"])

    assert stored["document"]["state"] == "ready"
    assert stored["document"]["final_revision_id"] == "rev_final"
    assert "document_recovery" not in stored


def test_latest_returns_terminal_job_that_active_list_hides(tmp_path) -> None:
    # `/workbook-research-active` only lists running jobs, which is why a
    # finished research used to restore nothing at all on re-entry.
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.finish(job["job_id"], status="complete")

    assert service.list_active(session_id="session-1") == []
    latest = service.latest(session_id="session-1")

    assert latest is not None
    assert latest["job_id"] == job["job_id"]
    assert latest["document"]["state"] == "pending"


def test_latest_matches_the_source_when_the_ui_session_was_regenerated(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.finish(job["job_id"], status="complete")

    assert service.latest(session_id="another-session") is None
    found = service.latest(attachment_id="read_123456abcdef")

    assert found is not None
    assert found["job_id"] == job["job_id"]


def test_latest_requires_a_scope_and_never_invents_a_job(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")

    assert service.latest() is None
    assert service.latest(session_id="", attachment_id="") is None


def test_get_of_an_unknown_job_is_not_found_rather_than_a_crash(tmp_path) -> None:
    """Probing several durable databases for one id is a normal UI gesture.

    ``_work_total_from_job_events`` walks the candidate databases and skips the
    ones that do not hold the job, so a missing row has to answer with the
    documented "not found" error.  Reading the row before that check made the
    probe die on ``TypeError`` whenever the app's own database was present.
    """

    service = WorkbookResearchJobService(tmp_path / "meta.db")

    with pytest.raises(WorkbookResearchJobError, match="not found"):
        service.get("wrj_does_not_exist")
