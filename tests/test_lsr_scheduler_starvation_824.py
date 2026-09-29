"""B1 — the planner must not confuse "one packet gave up" with "the document stopped".

Blocker file ``QWEN_BLOCKERS_AFTER_823_2026-09-29.md`` § 1, measured on the live
customer ВОР (``stage_b/live_823/b1_plateau_trace_823.json``): seven runs in a row
worked only sheet АР, each one pausing on two dead rows, and 278 of the 295
outstanding rows of АПС/ВК/ПТ/СКС/СКУД/СОУЭ/ЭОМ/ОВиК were never put to the model at
all — while the repeated global remainder was read as proof that they had been.
"""

import inspect
import sqlite3

import pytest

from proxy.services import chat_evidence_application_service as cea
from proxy.services.chat_evidence_application_service import (
    adaptive_row_packet,
    declared_gap_rows,
    packet_attempt_seed,
    packet_offer_counts,
    remaining_sheet_work_locators,
    research_run_stopped,
    sheet_pass_keep_rows,
    sheet_pass_state,
    starved_locators,
    truncated_tail_locator,
)
from proxy.services.workbook_research_job_service import (
    PACKET_DEFERRAL_PAUSE_KINDS,
    WorkbookResearchJobService,
)


def _identity(service, question="Собери ЛСР"):
    return service.identity(
        session_id="session-b1",
        attachment_id="read_b1aaaaaaaaaaaa",
        source_sha256="b" * 64,
        dataset_ids=["smeta"],
        profile_revision_id="factory",
        model_identity="qwen-35b",
        question=question,
    )


class _CatalogRow:
    def __init__(self, locator, sheet, work=True):
        self.locator = locator
        self.sheet = sheet
        self._work = work
        self.line = f"Монтаж {locator}"
        self.values = ("Монтаж", locator.split("!")[-1], "1", "м")
        self.row_classification = "work" if work else "header"
        self.header_quantity = None

    def is_work_row(self):
        return self._work


class _Catalog:
    """The parts of ``AttachmentSourceCatalog`` the packet pool and guards read."""

    def __init__(self, sheets):
        self.rows = [
            _CatalogRow(locator, sheet)
            for sheet, locators in sheets.items()
            for locator in locators
        ]

    def lookup(self, key):
        folded = str(key or "").strip().casefold()
        matches = [row for row in self.rows if row.locator.casefold() == folded]
        return matches[0] if len(matches) == 1 else None

    def work_locators(self):
        return [row.locator for row in self.rows if row.is_work_row()]


def _decision(locator):
    return {
        "source_row": locator,
        "row_role": "work",
        "norm_code": "MISSING",
        "norm_status": "MISSING",
        "evidence_refs": ["Q1.1"],
    }


# ── the guard pause is not a stop signal ─────────────────────────────────────


def _stalled_job(tmp_path):
    """A job whose sheet stalls twice on rows the model will not decide."""

    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    for _ in range(2):
        job = service.record_packet(
            job["job_id"],
            sheet="АР",
            packet_locators=["АР!R22", "АР!R23"],
            accepted_rows=[],
            evidence=[],
            remaining=["АР!R22", "АР!R23", "АПС!R4"],
        )
    return service, job


def test_a_guard_pause_does_not_stop_the_run(tmp_path) -> None:
    service, job = _stalled_job(tmp_path)

    assert job["status"] == "paused"
    assert job["phase"] == "stalled"
    assert job["stall_guard"]["pause_kind"] == "stalled"
    assert job["stall_guard"]["run_stops"] is False
    assert service.run_should_stop(job["job_id"]) is False
    # The outside world still reads a paused job as "not being worked".
    assert service.should_cancel(job["job_id"]) is True


def test_a_held_packet_that_ran_out_of_retries_also_keeps_the_run_going(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    held = {"sheet": "АР", "locators": ["АР!R22"], "queries": ["монтаж шкафа"]}
    for _ in range(4):
        job = service.record_packet(
            job["job_id"],
            sheet="АР",
            packet_locators=["АР!R22"],
            accepted_rows=[],
            evidence=[],
            remaining=["АР!R22", "ВК!R3"],
            held_packet=held,
        )

    assert job["status"] == "paused"
    assert job["stall_guard"]["pause_kind"] in PACKET_DEFERRAL_PAUSE_KINDS
    assert service.run_should_stop(job["job_id"]) is False


def test_an_operator_pause_a_cancel_and_a_legacy_pause_all_stop_the_run(tmp_path) -> None:
    service, job = _stalled_job(tmp_path)
    assert service.run_should_stop(job["job_id"]) is False

    service.pause(job["job_id"], remaining=["АР!R22"])
    assert service.run_should_stop(job["job_id"]) is True

    resumed = service.begin_or_resume(_identity(service))
    assert service.run_should_stop(resumed["job_id"]) is False
    service.request_cancel(resumed["job_id"])
    assert service.run_should_stop(resumed["job_id"]) is True

    # A pause written before ``pause_kind`` existed keeps its old meaning: stop.
    with sqlite3.connect(service.db_path) as conn:
        conn.execute(
            "UPDATE workbook_research_jobs SET status='paused',pause_kind='',cancel_requested=0"
            " WHERE job_id=?",
            (job["job_id"],),
        )
    assert service.run_should_stop(job["job_id"]) is True


def test_recording_a_progressing_packet_puts_a_deferral_paused_job_back_to_running(
    tmp_path,
) -> None:
    service, job = _stalled_job(tmp_path)
    assert job["status"] == "paused"

    again = service.record_packet(
        job["job_id"],
        sheet="АПС",
        packet_locators=["АПС!R4"],
        accepted_rows=[_decision("АПС!R4")],
        evidence=[],
        remaining=["АР!R22"],
    )

    assert again["status"] == "running"
    assert again["stall_guard"]["pause_kind"] == ""
    assert again["stall_guard"]["run_stops"] is False


# ── the deferral is durable and lifts itself on new evidence ─────────────────


def test_a_deferred_packet_stays_deferred_across_a_restart(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.record_packet(
        job["job_id"],
        sheet="АР",
        packet_locators=["АР!R22"],
        accepted_rows=[],
        evidence=[],
        remaining=["АР!R22", "АПС!R4"],
    )
    service.defer_locators(
        job["job_id"],
        sheet="АР",
        locators=["АР!R22"],
        reason="без предметного решения за 2 предложения(я)",
        offers=2,
    )

    # A restarted process is a new service object over the same file.
    restarted = WorkbookResearchJobService(tmp_path / "meta.db")
    assert restarted.still_deferred(job["job_id"], sheet="АР") == ["АР!R22"]
    # A different sheet is untouched: the dead row of АР cannot hold АПС back.
    assert restarted.still_deferred(job["job_id"], sheet="АПС") == []
    events = restarted.list_events(job["job_id"], event_type="locators_deferred")
    assert events[0]["payload"]["schema"] == "les.packet-deferral.v1"
    assert events[0]["payload"]["reason"].startswith("без предметного решения")


def test_new_evidence_releases_a_deferred_packet(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.defer_locators(
        job["job_id"], sheet="АР", locators=["АР!R22"], reason="нет решения", offers=2
    )
    assert service.still_deferred(job["job_id"], sheet="АР") == ["АР!R22"]

    service.record_search_cache(
        job["job_id"],
        {"монтаж шкафа": [{"content": "новая карточка", "doc_id": "c1"}]},
    )
    assert service.still_deferred(job["job_id"], sheet="АР") == []
    released = service.list_events(job["job_id"], event_type="deferrals_released")
    assert released[0]["payload"]["because"] == "новое evidence с момента отложения"


def test_reopening_a_locator_lifts_its_deferral(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.record_packet(
        job["job_id"],
        sheet="АР",
        packet_locators=["АР!R22"],
        accepted_rows=[_decision("АР!R22")],
        evidence=[],
        remaining=[],
    )
    service.defer_locators(job["job_id"], sheet="АР", locators=["АР!R22"], reason="x")
    reopened = service.reopen_locators(job["job_id"], ["АР!R22"])
    assert reopened["stall_guard"]["deferred_locators"] == 0
    assert service.still_deferred(job["job_id"], sheet="АР") == []


# ── a row the model never saw is never declared as "the model produced nothing" ─


def test_declaring_gaps_leaves_a_never_offered_row_open(tmp_path) -> None:
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.record_packet(
        job["job_id"],
        sheet="АР",
        packet_locators=["АР!R22"],
        accepted_rows=[],
        evidence=[],
        remaining=["АР!R22", "ЭОМ!R7"],
    )
    for _ in range(2):
        service.pause(job["job_id"], remaining=["АР!R22", "ЭОМ!R7"])

    closed = service.finish_with_declared_gaps(
        job["job_id"],
        gap_rows=declared_gap_rows(
            None, ["АР!R22", "ЭОМ!R7"], offers=3, offers_by_locator={"АР!R22": 5}
        ),
        reason="stalled",
        attempts=3,
        offers_by_locator={"АР!R22": 5, "ЭОМ!R7": 0},
    )

    assert closed["status"] == "paused"
    assert closed["stall_guard"]["pause_kind"] == "starved_scheduler"
    assert "ЭОМ!R7" in closed["remaining"]
    assert "АР!R22" not in closed["remaining"]
    declared = [row for row in closed["accepted_rows"] if row.get("decision_origin") == "declared_gap"]
    assert [row["source_row"] for row in declared] == ["АР!R22"]
    event = service.list_events(job["job_id"], event_type="gaps_declared")[0]
    assert event["payload"]["unoffered_open"] == 1
    assert event["payload"]["unoffered_locators"] == ["ЭОМ!R7"]


def test_a_declared_row_names_its_own_offer_count() -> None:
    rows = declared_gap_rows(
        None,
        ["АР!R22", "ВК!R3"],
        offers=31,
        offers_by_locator={"АР!R22": 14, "ВК!R3": 0},
    )
    reasons = {row["source_row"]: row["open_gap"] for row in rows}
    assert "после 14 предложений" in reasons["АР!R22"]
    # The resume count of the whole document never becomes this row's history.
    assert "31" not in reasons["АР!R22"]


def test_starved_locators_reads_the_durable_ledger() -> None:
    events = [
        {"event_type": "packet_checkpoint", "payload": {"packet_locators": ["АР!R22"]}},
    ]
    ledger = packet_offer_counts(events)
    assert starved_locators(["АР!R22", "ЭОМ!R7"], ledger) == ["ЭОМ!R7"]
    assert starved_locators(["АР!R22"], ledger) == []
    assert starved_locators(["ЭОМ!R7"], {}) == ["ЭОМ!R7"]


def test_run_stop_test_is_read_from_the_durable_pause_kind() -> None:
    guard = {"run_stops": False, "pause_kind": "stalled"}
    assert research_run_stopped({"status": "paused", "stall_guard": guard}) == (
        False,
        False,
        "stalled",
    )
    stopped = research_run_stopped(
        {"status": "paused", "cancel_requested": False, "stall_guard": {"run_stops": True, "pause_kind": "run_end"}}
    )
    assert stopped == (True, False, "run_end")
    cancelled = research_run_stopped(
        {"status": "paused", "cancel_requested": True, "stall_guard": {"run_stops": True}}
    )
    assert cancelled[0] is True and cancelled[1] is True


# ── a cut-off answer is a read failure, not a professional verdict ───────────


def test_a_row_cut_off_before_its_decision_columns_is_not_saved() -> None:
    catalog = _Catalog({"АР": ["АР!R22", "АР!R23"]})
    decided = {"source_row": "АР!R22", "row_role": "work", "norm_code": "10-01-001-01"}
    cut_mid_row = {"source_row": "АР!R23", "title": "Монтаж кабеля", "quantity": "120"}
    rows = [decided, cut_mid_row]

    assert truncated_tail_locator(rows, truncated=True) == "АР!R23"
    assert truncated_tail_locator(rows, truncated=False) == ""
    kept = sheet_pass_keep_rows(
        rows, sheet="АР", catalog=catalog, errors=[], drop_locator="АР!R23"
    )
    assert kept == [decided]
    # A deliberate MISSING verdict is a decision and survives the same test.
    explicit_missing = {"source_row": "АР!R23", "norm_status": "MISSING", "coverage": "MISSING"}
    assert truncated_tail_locator([decided, explicit_missing], truncated=True) == ""


def test_the_five_states_stay_apart_in_the_report() -> None:
    catalog = _Catalog({"АР": ["АР!R22", "АР!R23", "АР!R24"]})
    rows = [
        {"source_row": "АР!R23", "row_role": "work", "norm_code": "ГЭСН8-01-001-01"},
        {"source_row": "АР!R24", "row_role": "unresolved", "open_gap": "нужна длина трассы"},
    ]
    state = sheet_pass_state(
        catalog,
        "АР",
        rows,
        offered_this_pass=("АР!R23", "АР!R24"),
        offer_counts={"АР!R23": 4, "АР!R24": 2},
        deferred=("АР!R24",),
        unread_tail=("АР!R24",),
        deferred_search=("АР!R23",),
    )

    assert state["schema"] == "les.sheet-pass-states.v1"
    assert state["never_offered"] == 1
    assert state["never_offered_locators"] == ["АР!R22"]
    assert state["decided"] == 2
    assert state["needs_clarification_locators"] == ["АР!R24"]
    assert state["deferred_rows"] == ["АР!R24"]
    assert state["unread_tail"] == ["АР!R24"]
    assert state["deferred_search_rows"] == ["АР!R23"]


# ── the scenario the blocker names: a dead first sheet must not starve the rest ─


@pytest.mark.parametrize("restart_midway", [False, True])
def test_a_dead_first_sheet_cannot_starve_the_sheets_behind_it(tmp_path, restart_midway):
    """First sheet carries an unresolvable position; the next ones are solvable.

    Mirrors the loop's own decisions with the same helpers it calls — the stop test,
    the pool ordering, the packet-exhaustion deferral and the durable ledger — and
    must end with every later sheet decided and the hard row kept aside with a real
    reason.  A restart half-way through may not lose that state.
    """

    catalog = _Catalog(
        {"АР": ["АР!R22", "АР!R23"], "АПС": [f"АПС!R{i}" for i in range(2, 8)]}
    )
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    rows: list[dict] = []
    stopped_sheets: list[str] = []
    # Control: what build 823 did at the same boundary — it read any pause as a
    # stop, and that is the whole reason eight sheets were never offered.
    legacy_would_stop_at: list[str] = []

    for run in range(2):
        if restart_midway and run == 1:
            service = WorkbookResearchJobService(tmp_path / "meta.db")
            job = service.begin_or_resume(_identity(service))
        for sheet in ("АР", "АПС"):
            if service.should_cancel(job["job_id"]):
                legacy_would_stop_at.append(sheet)
            if service.run_should_stop(job["job_id"]):
                stopped_sheets.append(sheet)
                break
            offered_this_pass: set[str] = set()
            checkpoint_events = service.list_events(
                job["job_id"], event_type="packet_checkpoint"
            )
            ledger = packet_offer_counts(checkpoint_events)
            # The loop numbers a re-delivered packet from the durable checkpoints,
            # so "the limited number of attempts" survives a restart too.
            attempts: dict[tuple, int] = packet_attempt_seed(checkpoint_events)
            exhausted = set(service.still_deferred(job["job_id"], sheet=sheet))
            remaining = [
                locator
                for locator in remaining_sheet_work_locators(catalog, sheet, set())
                if locator not in {str(item.get("source_row")) for item in rows}
                and locator not in exhausted
            ]
            while remaining:
                packet = adaptive_row_packet(
                    remaining,
                    generation_reserve_tokens=4096,
                    already_offered=tuple(sorted(offered_this_pass)),
                    offer_counts=ledger,
                )
                if not packet:
                    break
                offered_this_pass.update(packet)
                key = tuple(packet)
                attempts[key] = attempts.get(key, 0) + 1
                # АР is the unresolvable sheet: the model answers nothing useful.
                produced = [] if sheet == "АР" else [_decision(locator) for locator in packet]
                rows.extend(produced)
                # Membership follows the settled set, not "was offered": a packet
                # that produced nothing is put to the model again until its limited
                # attempts run out, which is what makes the guard pause happen.
                remaining = [
                    locator
                    for locator in remaining_sheet_work_locators(
                        catalog, sheet, {str(item["source_row"]) for item in rows}
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
                if not produced and attempts[key] >= cea._ROW_PACKET_MAX_ATTEMPTS:
                    exhausted.update(packet)
                    service.defer_locators(
                        job["job_id"],
                        sheet=sheet,
                        locators=packet,
                        reason="без предметного решения",
                        offers=attempts[key],
                    )
                    remaining = [
                        locator for locator in remaining if locator not in exhausted
                    ]

    assert stopped_sheets == [], f"the run stopped before the later sheets: {stopped_sheets}"
    assert legacy_would_stop_at == ["АПС"], (
        "the control lost the 823 failure: reading the guard pause as a stop is what "
        "abandoned every sheet behind АР"
    )
    decided = {item["source_row"] for item in rows}
    assert decided == set(catalog.work_locators()) - {"АР!R22", "АР!R23"}
    assert service.still_deferred(job["job_id"], sheet="АР") == ["АР!R22", "АР!R23"]
    assert service.still_deferred(job["job_id"], sheet="АПС") == []
    job_now = service.get(job["job_id"])
    # The hard rows are kept aside with a real reason; they are never closed as a
    # professional "no norm" verdict by the scheduler.
    assert not [row for row in job_now["accepted_rows"] if row.get("decision_origin")]
    assert {"АР!R22", "АР!R23"} <= (
        set(catalog.work_locators())
        - cea.settled_source_keys(job_now["accepted_rows"], catalog)
    )


def test_the_loop_asks_the_run_question_and_defers_instead_of_aborting() -> None:
    """The rewiring is a production-path guarantee, not only a storage one."""

    source = inspect.getsource(cea._execute_chat_evidence_application)
    loop = source[source.index("for sheet_index, sheet_name in enumerate(sheet_pass_names") :]
    assert "should_cancel(" not in loop, "the sheet loop must not read a pause as a stop"
    assert "research_run_stopped(research_job)" in loop
    assert "run_should_stop" not in loop
    assert "defer_locators(" in loop
    assert "still_deferred(" in loop
    assert "made_progress = bool(settled_after - settled_before)" in loop
    assert "truncated_tail_locator(" in loop
    assert "drop_locator=tail_locator" in loop
    assert "sheet_pass_state(" in loop
    # The § 1 chain has to be readable from the trace: response -> parsed/kept ->
    # durable merge -> settled keys -> packet pool -> stall guard.
    for field in (
        '"parsed_rows"',
        '"kept_rows"',
        '"unread_tail_row"',
        '"newly_decided"',
        '"pool_remaining"',
        '"durable_rows"',
        '"pause_kind"',
    ):
        assert field in loop, f"the pass trace lost {field}"
    tail = loop[loop.index("settled_keys = settled_source_keys") :]
    assert "starved_locators(" in tail
    assert "offers_by_locator=offer_ledger" in tail
    assert "left_open_never_offered" in tail
