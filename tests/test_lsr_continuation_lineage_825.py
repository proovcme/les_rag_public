"""B1 (29.09) — a chat continuation must continue the document's queue, not restart it.

Measured live on the installed build 824 with the customer's 377-row ВОР
(``stage_b/live_824/b1_continuation_824.json``): the first run reached 9 of the 10
sheets and paused on its per-run budget with 305 durable decisions, 32 deferrals and
1004 cached queries.  Sending the very sentence the «Продолжить» button sends opened a
*second* ``workbook_research_jobs`` row whose queue started again at sheet АР:
74 of its 76 decided locators were rows the previous research had already decided, it
cached 353 queries the document had already had, and the 32 rows the previous run had
set aside with a reason came back — 2 of them (АР!R43, АР!R50) were re-offered while
still deferred.  The question digest is part of the job identity, so every
continuation was a fresh start; blocker § 1 requires the opposite two halves at once:
«Состояние очереди/попыток сохранять при рестарте» and «Не повторять один и тот же
набор без новых данных/evidence».
"""

import inspect
import json
import sqlite3

from proxy.services import chat_evidence_application_service as cea
from proxy.services.chat_evidence_application_service import (
    adaptive_row_packet,
    packet_offer_counts,
    remaining_sheet_work_locators,
    settled_source_keys,
)
from proxy.services.workbook_research_job_service import WorkbookResearchJobService

FIRST_QUESTION = "Собери ЛСР по прикреплённому документу"
CONTINUATION_QUESTION = "Продолжи это же задание по тому же прикреплённому документу."


def _identity(service, question=FIRST_QUESTION, *, session="session-b1", sha="b" * 64):
    return service.identity(
        session_id=session,
        attachment_id="read_b1aaaaaaaaaaaa",
        source_sha256=sha,
        dataset_ids=["smeta"],
        profile_revision_id="factory",
        model_identity="qwen-35b",
        question=question,
    )


def _decision(locator, code="ГЭСН8-01-001-01"):
    return {
        "source_row": locator,
        "row_role": "work",
        "title": f"Монтаж {locator}",
        "unit": "м",
        "quantity": 1,
        "norm_code": code,
        "norm_status": "FOUND",
        "evidence_refs": ["Q1.1"],
    }


class _CatalogRow:
    def __init__(self, locator):
        self.locator = locator
        self.sheet = locator.split("!")[0]
        self.line = f"Монтаж {locator}"
        self.values = ("Монтаж", locator.split("!")[-1], "1", "м")
        self.row_classification = "work"
        self.header_quantity = None

    def is_work_row(self):
        return True


class _Catalog:
    def __init__(self, sheets):
        self.rows = [
            _CatalogRow(locator) for locators in sheets.values() for locator in locators
        ]

    def lookup(self, key):
        folded = str(key or "").strip().casefold()
        matches = [row for row in self.rows if row.locator.casefold() == folded]
        return matches[0] if len(matches) == 1 else None

    def work_locators(self):
        return [row.locator for row in self.rows]


# ── what a continuation picks up ─────────────────────────────────────────────


def _a_run_that_paused_on_its_budget(tmp_path):
    """The first turn: three АР rows decided, two hard rows deferred, then a pause."""

    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    for locator in ("АР!R2", "АР!R3", "АР!R4"):
        job = service.record_packet(
            job["job_id"],
            sheet="АР",
            packet_locators=[locator],
            accepted_rows=[_decision(locator)],
            evidence=[{"global_evidence_id": f"ev_{locator}", "content": "карточка"}],
            remaining=["АР!R22", "АР!R23", "АПС!R4", "АПС!R5"],
        )
    service.record_search_cache(
        job["job_id"], {"монтаж шкафа": [{"content": "карточка", "doc_id": "c1"}]}
    )
    service.record_packet(
        job["job_id"],
        sheet="АР",
        packet_locators=["АР!R22", "АР!R23"],
        accepted_rows=[],
        evidence=[],
        remaining=["АР!R22", "АР!R23", "АПС!R4", "АПС!R5"],
    )
    job = service.record_packet(
        job["job_id"],
        sheet="АР",
        packet_locators=["АР!R22", "АР!R23"],
        accepted_rows=[],
        evidence=[],
        remaining=["АР!R22", "АР!R23", "АПС!R4", "АПС!R5"],
    )
    service.defer_locators(
        job["job_id"],
        sheet="АР",
        locators=["АР!R22", "АР!R23"],
        reason="без предметного решения за 3 предложения(я)",
        offers=3,
    )
    job = service.pause(
        job["job_id"], remaining=["АР!R22", "АР!R23", "АПС!R4", "АПС!R5"]
    )
    return service, job


def test_a_continuation_carries_the_documents_decisions_evidence_and_cache(tmp_path):
    service, first = _a_run_that_paused_on_its_budget(tmp_path)

    second = service.begin_or_resume(
        _identity(service, CONTINUATION_QUESTION, session="session-2")
    )

    # It is still its own research of the document — the durable identity covers the
    # question, and the packaging lineage depends on those two rows being distinct.
    assert second["job_id"] != first["job_id"]
    assert second["continues_job_id"] == first["job_id"]
    assert {row["source_row"] for row in second["accepted_rows"]} == {
        "АР!R2",
        "АР!R3",
        "АР!R4",
    }
    assert len(second["evidence"]) == len(first["evidence"]) == 3
    assert second["query_cache"] == first["query_cache"]
    assert second["remaining"] == first["remaining"]
    # The guard counters of a run do NOT carry: a continuation is a new run with a
    # fresh budget, and its stall streak starts from what this run actually does.
    assert second["stall_guard"]["run_round_count"] == 0
    assert second["stall_guard"]["stall_count"] == 0
    assert second["stall_guard"]["pause_kind"] == ""
    event = service.list_events(second["job_id"], event_type="progress_inherited")[0]
    assert event["payload"]["schema"] == "les.progress-inherited.v1"
    assert event["payload"]["from_job"] == first["job_id"]
    assert event["payload"]["decided_rows"] == 3
    assert event["payload"]["cached_queries"] == 1
    assert event["payload"]["parent_status"] == "paused"


def test_a_continuation_keeps_the_deferrals_it_inherited(tmp_path):
    service, first = _a_run_that_paused_on_its_budget(tmp_path)
    assert service.still_deferred(first["job_id"], sheet="АР") == ["АР!R22", "АР!R23"]

    second = service.begin_or_resume(
        _identity(service, CONTINUATION_QUESTION, session="session-2")
    )

    # Re-offering a row the document already gave up on, with no new data, is the
    # exact thing § 1 forbids.  The watermark is re-based to what the continuation
    # starts with, so "new data" means data THIS turn gathered.
    assert service.still_deferred(second["job_id"], sheet="АР") == ["АР!R22", "АР!R23"]
    carried = service.get(second["job_id"])
    assert carried["stall_guard"]["deferred_locators"] == 2
    with sqlite3.connect(service.db_path) as conn:
        raw = conn.execute(
            "SELECT deferrals_json FROM workbook_research_jobs WHERE job_id=?",
            (second["job_id"],),
        ).fetchone()[0]
    entries = json.loads(raw)
    assert sorted(entries) == ["АР!R22", "АР!R23"]
    assert entries["АР!R22"]["inherited_from_job"] == first["job_id"]
    assert entries["АР!R22"]["offers"] == 3
    assert entries["АР!R22"]["reason"].startswith("без предметного решения")
    assert entries["АР!R22"]["evidence_watermark"] == len(carried["evidence"]) + len(
        carried["query_cache"]
    )
    # A different sheet is untouched, exactly as within one run.
    assert service.still_deferred(second["job_id"], sheet="АПС") == []


def test_new_evidence_in_the_continuation_releases_the_inherited_deferral(tmp_path):
    service, first = _a_run_that_paused_on_its_budget(tmp_path)
    second = service.begin_or_resume(_identity(service, CONTINUATION_QUESTION))
    assert service.still_deferred(second["job_id"], sheet="АР")

    service.record_search_cache(
        second["job_id"],
        {"монтаж лотка": [{"content": "новая карточка", "doc_id": "c2"}]},
    )

    assert service.still_deferred(second["job_id"], sheet="АР") == []
    released = service.list_events(second["job_id"], event_type="deferrals_released")
    assert [row["payload"]["locators"] for row in released] == [["АР!R22", "АР!R23"]]


def test_the_offer_ledger_of_a_continuation_is_the_documents_history(tmp_path):
    service, first = _a_run_that_paused_on_its_budget(tmp_path)
    second = service.begin_or_resume(_identity(service, CONTINUATION_QUESTION))

    assert service.list_events(second["job_id"], event_type="packet_checkpoint") == []
    ledger = packet_offer_counts(
        service.list_events_with_lineage(second["job_id"], "packet_checkpoint")
    )
    # A row the previous research put to the model is not "never offered" for the
    # continuation, and a row it never offered keeps its zero count.
    assert ledger["АР!R2"] == 1
    assert ledger["АР!R22"] == 2
    assert ledger.get("АПС!R4", 0) == 0
    assert service.lineage_job_ids(second["job_id"]) == [
        first["job_id"],
        second["job_id"],
    ]


def test_a_third_turn_still_reads_the_whole_chain(tmp_path):
    service, first = _a_run_that_paused_on_its_budget(tmp_path)
    second = service.begin_or_resume(_identity(service, CONTINUATION_QUESTION))
    service.record_packet(
        second["job_id"],
        sheet="АПС",
        packet_locators=["АПС!R4"],
        accepted_rows=[_decision("АПС!R4")],
        evidence=[],
        remaining=["АР!R22", "АР!R23", "АПС!R5"],
    )
    third = service.begin_or_resume(_identity(service, "Добери нормы", session="session-3"))

    assert third["continues_job_id"] == second["job_id"]
    assert service.lineage_job_ids(third["job_id"]) == [
        first["job_id"],
        second["job_id"],
        third["job_id"],
    ]
    assert {row["source_row"] for row in third["accepted_rows"]} == {
        "АР!R2",
        "АР!R3",
        "АР!R4",
        "АПС!R4",
    }
    # The order is the document's own: the inherited decisions first, this turn's
    # after them.
    assert [row["source_row"] for row in third["accepted_rows"]] == [
        "АР!R2",
        "АР!R3",
        "АР!R4",
        "АПС!R4",
    ]
    ledger = packet_offer_counts(
        service.list_events_with_lineage(third["job_id"], "packet_checkpoint")
    )
    assert ledger["АР!R2"] == 1 and ledger["АПС!R4"] == 1


def test_an_unchanged_question_resumes_the_same_row_and_inherits_nothing(tmp_path):
    service, first = _a_run_that_paused_on_its_budget(tmp_path)

    again = service.begin_or_resume(_identity(service))

    assert again["job_id"] == first["job_id"]
    assert again["continues_job_id"] == ""
    assert service.list_events(first["job_id"], event_type="progress_inherited") == []
    assert again["accepted_rows"] == first["accepted_rows"]


def test_a_different_file_under_the_same_attachment_starts_from_zero(tmp_path):
    service, first = _a_run_that_paused_on_its_budget(tmp_path)

    replaced = service.begin_or_resume(
        _identity(service, CONTINUATION_QUESTION, sha="c" * 64)
    )

    # § 9: what the old file decided is not a statement about the new one.
    assert replaced["continues_job_id"] == ""
    assert replaced["accepted_rows"] == []
    assert replaced["query_cache"] == {}
    assert service.still_deferred(replaced["job_id"], sheet="АР") == []


def test_a_first_research_of_an_undecided_document_inherits_nothing(tmp_path):
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    service.begin_or_resume(_identity(service))

    second = service.begin_or_resume(_identity(service, CONTINUATION_QUESTION))

    assert second["continues_job_id"] == ""
    assert second["accepted_rows"] == []
    assert service.list_events(second["job_id"], event_type="progress_inherited") == []


# ── the scheduler consequence, on the same helpers the sheet loop calls ──────


def test_a_continuation_reaches_the_sheets_the_first_run_never_got_to(tmp_path):
    """The live 824 failure, replayed with the helpers the sheet loop itself calls."""

    catalog = _Catalog(
        {
            "АР": ["АР!R2", "АР!R3", "АР!R4", "АР!R22", "АР!R23"],
            "АПС": ["АПС!R4", "АПС!R5"],
        }
    )
    service, first = _a_run_that_paused_on_its_budget(tmp_path)

    job = service.begin_or_resume(_identity(service, CONTINUATION_QUESTION))
    rows = [dict(item) for item in job["accepted_rows"]]
    offered_in_the_continuation: list[str] = []
    for sheet in ("АР", "АПС"):
        ledger = packet_offer_counts(
            service.list_events_with_lineage(job["job_id"], "packet_checkpoint")
        )
        exhausted = set(service.still_deferred(job["job_id"], sheet=sheet))
        remaining = [
            locator
            for locator in remaining_sheet_work_locators(
                catalog, sheet, settled_source_keys(rows, catalog)
            )
            if locator not in exhausted
        ]
        while remaining:
            packet = adaptive_row_packet(
                remaining,
                generation_reserve_tokens=4096,
                already_offered=tuple(offered_in_the_continuation),
                offer_counts=ledger,
            )
            if not packet:
                break
            offered_in_the_continuation.extend(packet)
            produced = [_decision(locator) for locator in packet]
            rows.extend(produced)
            remaining = [
                locator
                for locator in remaining_sheet_work_locators(
                    catalog, sheet, settled_source_keys(rows, catalog)
                )
                if locator not in exhausted
            ]
            job = service.record_packet(
                job["job_id"],
                sheet=sheet,
                packet_locators=packet,
                accepted_rows=produced,
                evidence=[],
                remaining=remaining,
            )

    # The control: build 824's continuation turn put these АР rows to the model
    # again although they already held durable decisions.  Here none of them is.
    assert set(offered_in_the_continuation).isdisjoint(
        {"АР!R2", "АР!R3", "АР!R4", "АР!R22", "АР!R23"}
    )
    assert sorted(offered_in_the_continuation) == ["АПС!R4", "АПС!R5"]
    assert settled_source_keys(rows, catalog) == {
        "АР!R2", "АР!R3", "АР!R4", "АПС!R4", "АПС!R5"
    }
    # The hard rows stay open with their reason instead of being closed by the turn.
    assert service.still_deferred(job["job_id"], sheet="АР") == ["АР!R22", "АР!R23"]
    assert service.still_deferred(job["job_id"], sheet="АПС") == []
    assert not [
        row for row in job["accepted_rows"] if row.get("decision_origin") == "declared_gap"
    ]


def test_the_loop_reads_its_ledgers_across_the_documents_lineage() -> None:
    """The rewiring is a production-path guarantee, not only a storage one."""

    source = inspect.getsource(cea._execute_chat_evidence_application)
    assert source.count("list_events_with_lineage(") >= 2, (
        "both the packet-rotation seed and the declared-gap offer ledger must read "
        "the whole document lineage"
    )


def test_inheritance_adds_a_row_and_rewrites_no_history(tmp_path) -> None:
    service, first = _a_run_that_paused_on_its_budget(tmp_path)
    before = service.get(first["job_id"])
    before_events = service.list_events(first["job_id"])

    second = service.begin_or_resume(_identity(service, CONTINUATION_QUESTION))

    # The parent's durable record is untouched: a continuation reads it, it never
    # moves or rewrites what the first turn wrote.
    after = service.get(first["job_id"])
    assert after["accepted_rows"] == before["accepted_rows"]
    assert service.list_events(first["job_id"]) == before_events
    assert after["stall_guard"]["deferred_locators"] == 2
    assert second["status_dimensions"]["operations"] == 3
    assert second["status_dimensions"]["cached_queries"] == 1
    with sqlite3.connect(service.db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM workbook_research_jobs"
            " WHERE json_extract(identity_json,'$.attachment_id')=?",
            ("read_b1aaaaaaaaaaaa",),
        ).fetchone()
        assert int(count[0]) == 2
