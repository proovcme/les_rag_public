# -*- coding: utf-8
"""25.09: the customer ВОР resumed forever without reaching a terminal job.

Live reproduction (build 806, job wrj_6cacfade34f449bb, source sha
74233e10406caa5b87ea48cefaeea9dc4ae9dbf3d1dfc2118b853be57f47c6b3): every resume
reported the *same* global remainder and the per-run counters could not see it,
because ``stall_count``, ``run_round_count`` and ``held_attempts`` all reset in
``begin_or_resume``.  The packet for АР!R18-R29 and АР!R30-R41 was offered with
``new_revisions=0`` on both, the sheet pass paused with ``remaining=366``, and
«Продолжить» produced the identical 366 again — an unbounded loop in which the
customer never gets a last downloadable ЛСР.

The bound lives on the *global* remainder fingerprint and survives resumes; the
terminal half closes rows that received no model decision at all as declared
gaps, which are bookkeeping and never a professional decision: no cipher, no
price, no title the source does not have.
"""
from __future__ import annotations

from proxy.services.lsr_result_readiness_service import format_lsr_readiness_notice
from tests.lsr_citation_support import cited_all

from proxy.services.workbook_research_job_service import (
    STALL_TERMINAL_OCCURRENCES,
    WorkbookResearchJobService,
    declared_gap_decision,
    remainder_fingerprint,
)


def _identity(service, question="Собери ЛСР"):
    return service.identity(
        session_id="session-bound",
        attachment_id="read_70970015f534",
        source_sha256="74233e10406caa5b87ea48cefaeea9dc4ae9dbf3d1dfc2118b853be57f47c6b3",
        dataset_ids=["smeta"],
        profile_revision_id="factory",
        model_identity="qwen-35b",
        question=question,
    )


def _started(tmp_path):
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(_identity(service))
    service.record_packet(
        job["job_id"],
        sheet="АР",
        packet_locators=["АР!R9"],
        accepted_rows=[
            {
                "source_row": "АР!R9",
                "row_role": "work",
                "title": "Монтаж шкафа",
                "unit": "шт",
                "quantity": 4,
                "norm_code": "ГЭСНм08-03-575-01",
                "norm_status": "EXACT",
            }
        ],
        evidence=[],
        remaining=["АР!R18", "АР!R19"],
    )
    return service, job["job_id"]


# ---------------------------------------------------------------- fingerprint


def test_fingerprint_ignores_order_and_duplicates():
    assert remainder_fingerprint(["АР!R19", "АР!R18", "АР!R19"]) == remainder_fingerprint(
        ["АР!R18", "АР!R19"]
    )
    assert remainder_fingerprint([]) == ""
    assert remainder_fingerprint(["АР!R18"]) != remainder_fingerprint(["АР!R19"])


# ------------------------------------------------------- the cross-resume bound


def test_identical_remainder_is_counted_across_resumes(tmp_path):
    service, job_id = _started(tmp_path)

    first = service.pause(job_id, remaining=["АР!R18", "АР!R19"], phase="packets")
    assert first["stall_guard"]["remainder_repeats"] == 1
    assert first["stall_guard"]["terminal_bound"] == STALL_TERMINAL_OCCURRENCES

    # a resume resets the per-run counters, which is exactly why the live job
    # looped 34 times: only the remainder fingerprint carries the memory.
    service.begin_or_resume(_identity(service))
    second = service.pause(job_id, remaining=["АР!R19", "АР!R18"], phase="packets")
    assert second["stall_guard"]["remainder_repeats"] == 2
    # the live 12-pass run stalled exactly like this twice and then made progress
    # again, so two repeats must NOT be terminal yet
    assert (
        second["stall_guard"]["remainder_repeats"]
        < second["stall_guard"]["terminal_bound"]
    )

    for expected in (3, 4):
        service.begin_or_resume(_identity(service))
        again = service.pause(job_id, remaining=["АР!R18", "АР!R19"], phase="packets")
        assert again["stall_guard"]["remainder_repeats"] == expected
    assert (
        again["stall_guard"]["remainder_repeats"]
        >= again["stall_guard"]["terminal_bound"]
    )


def test_progress_resets_the_repeat_streak(tmp_path):
    service, job_id = _started(tmp_path)
    service.pause(job_id, remaining=["АР!R18", "АР!R19"], phase="packets")
    service.begin_or_resume(_identity(service))
    moved = service.pause(job_id, remaining=["АР!R19"], phase="packets")
    assert moved["stall_guard"]["remainder_repeats"] == 1


def test_empty_remainder_is_not_a_stall(tmp_path):
    service, job_id = _started(tmp_path)
    done = service.pause(job_id, remaining=[], phase="packets")
    assert done["stall_guard"]["remainder_repeats"] == 0
    assert done["stall_guard"]["remainder_fingerprint"] == ""


# ------------------------------------------------------------ declared gaps


def test_declared_gap_carries_no_professional_decision():
    row = declared_gap_decision(
        "АР!R18",
        line="АР!R18: 12 | Монтаж лотка | м | 40",
        unit="м",
        quantity=40,
        row_classification="work",
        reason="Решение модели не получено после 3 предложений.",
        attempts=3,
    )
    assert row["norm_code"] == ""
    assert row["norm_status"] == "MISSING"
    assert row["row_role"] == "unresolved"
    assert row["decision_origin"] == "declared_gap"
    assert row["evidence_refs"] == []
    assert row["unit"] == "м"
    assert row["quantity"] == 40
    # the source title is carried unchanged, without the locator prefix
    assert row["title"] == "12 | Монтаж лотка | м | 40"
    assert "не получено после 3 предложений" in row["open_gap"]


def test_finish_with_declared_gaps_keeps_model_rows_and_closes_the_job(tmp_path):
    service, job_id = _started(tmp_path)
    service.pause(job_id, remaining=["АР!R18", "АР!R19"], phase="packets")
    service.begin_or_resume(_identity(service))

    before = service.get(job_id)
    model_rows_before = [dict(item) for item in before["accepted_rows"]]

    closed = service.finish_with_declared_gaps(
        job_id,
        gap_rows=[
            declared_gap_decision(
                "АР!R18", line="АР!R18: Монтаж лотка", reason="нет решения модели"
            ),
            declared_gap_decision(
                "АР!R19", line="АР!R19: Монтаж кабеля", reason="нет решения модели"
            ),
            # an already-decided locator must never be re-closed as a gap
            declared_gap_decision(
                "АР!R9", line="АР!R9: Монтаж шкафа", reason="нет решения модели"
            ),
        ],
        reason="stalled",
        attempts=3,
    )

    assert closed["status"] == "complete"
    assert closed["phase"] == "declared_gaps"
    assert closed["resumable"] is False
    assert closed["remaining"] == []
    assert closed["stall_guard"]["remainder_repeats"] == 0

    locators = [str(item.get("source_row") or "") for item in closed["accepted_rows"]]
    assert locators.count("АР!R9") == 1  # no duplicate over the model's decision
    assert {"АР!R18", "АР!R19"} <= set(locators)

    # the accepted model decision is untouched, byte for byte
    kept = [
        item
        for item in closed["accepted_rows"]
        if str(item.get("source_row") or "") == "АР!R9"
    ][0]
    for field, value in model_rows_before[0].items():
        if field in {"operation_id", "revision", "content_sha256"}:
            continue
        assert kept[field] == value

    declared = [
        item
        for item in closed["accepted_rows"]
        if str(item.get("decision_origin") or "") == "declared_gap"
    ]
    assert {item["norm_code"] for item in declared} == {""}
    assert {item["row_role"] for item in declared} == {"unresolved"}

    events = {
        str(row["event_type"])
        for row in service.list_events(job_id)
    }
    assert "gaps_declared" in events


def test_declaring_a_stalled_tail_never_completes_an_unfinished_document(tmp_path):
    """The live 12-pass run stalled on two АР rows while 200 works sat untouched.

    Closing the stalled rows must free the loop without telling the customer the
    document is finished: the other sheets stay in `remaining`, the job stays
    resumable, and only the declared locators leave the outstanding set.
    """

    service, job_id = _started(tmp_path)
    service.pause(
        job_id,
        remaining=["АР!R18", "АР!R19", "ЭОМ!R9", "ОВиК!R12", "ПТ!R9"],
        phase="packets",
    )
    closed = service.finish_with_declared_gaps(
        job_id,
        gap_rows=[
            declared_gap_decision("АР!R18", line="Монтаж лотка", reason="нет решения"),
            declared_gap_decision("АР!R19", line="Монтаж кабеля", reason="нет решения"),
        ],
        reason="stalled sheet tail",
        attempts=5,
    )
    assert closed["status"] == "paused"          # NOT complete: work is outstanding
    assert closed["phase"] == "packets"
    assert closed["resumable"] is True
    assert closed["remaining"] == ["ЭОМ!R9", "ОВиК!R12", "ПТ!R9"]
    # the streak is over: the declared rows can no longer re-trigger the bound
    assert closed["stall_guard"]["remainder_repeats"] == 0
    assert closed["stall_guard"]["stall_count"] == 0
    locators = [str(item.get("source_row")) for item in closed["accepted_rows"]]
    assert {"АР!R18", "АР!R19"} <= set(locators)
    kinds = {
        str(item.get("decision_origin") or "model")
        for item in closed["accepted_rows"]
    }
    assert kinds == {"model", "declared_gap"}
    events = [
        row for row in service.list_events(job_id, "gaps_declared")
    ]
    assert len(events) == 1
    payload = dict(events[0]["payload"])
    assert payload["job_completed"] is False
    assert payload["still_remaining"] == 3
    assert payload["model_called"] is False
    assert payload["decision_author"] == "application"
    later = service.list_events(job_id, "complete")
    assert [int(row["sequence"]) for row in later] == [] or all(
        int(row["sequence"]) < int(events[0]["sequence"]) for row in later
    )


def test_a_fully_declared_remainder_does_complete_the_job(tmp_path):
    """When the stalled rows ARE the whole document, the bound ends the research."""

    service, job_id = _started(tmp_path)
    service.pause(job_id, remaining=["ЭОМ!R9"], phase="packets")
    closed = service.finish_with_declared_gaps(
        job_id,
        gap_rows=[declared_gap_decision("ЭОМ!R9", line="Монтаж лотка", reason="нет решения")],
        reason="stalled",
        attempts=5,
    )
    assert closed["status"] == "complete"
    assert closed["phase"] == "declared_gaps"
    assert closed["resumable"] is False
    assert closed["remaining"] == []


def test_declared_gaps_are_reported_apart_from_model_rows(tmp_path):
    service, job_id = _started(tmp_path)
    service.pause(job_id, remaining=["АР!R18"], phase="packets")
    service.begin_or_resume(_identity(service))
    closed = service.finish_with_declared_gaps(
        job_id,
        gap_rows=[
            declared_gap_decision(
                "АР!R18",
                line="АР!R18: Монтаж лотка",
                unit="м",
                quantity=40,
                reason="Решение модели не получено после 3 предложений; "
                "строка закрыта приложением как пробел, норма и цена не подобраны.",
                attempts=3,
            )
        ],
        attempts=3,
    )
    from proxy.services.lsr_result_readiness_service import build_lsr_result_readiness

    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=closed["accepted_rows"],
        catalog_locators=["АР!R9", "АР!R18"],
        catalog_work_count=2,
        remaining_locators=closed["remaining"],
    )
    counts = readiness["counts"]
    assert counts["declared_gaps"] == 1
    assert counts["works"] == 1
    # coverage is closed (every source row has a role), and an ``unresolved``
    # row asks for no norm by design -- which is exactly why the declared-gap
    # count has to be the thing that blocks the "complete" claim.
    assert readiness["dimensions"]["coverage"]["complete"] is True
    assert readiness["estimate_complete"] is False
    notice = format_lsr_readiness_notice(readiness)
    assert "ЛСР собрана частично" in notice
    assert "закрыто приложением как пробел" in notice
    assert "Пробелов, закрытых приложением без решения модели: 1." in notice
    assert notice.strip() != "ЛСР собрана."


def test_no_declared_gaps_keeps_the_plain_complete_notice(tmp_path):
    service, job_id = _started(tmp_path)
    job = service.finish(job_id, status="complete", phase="research_complete")
    from proxy.services.lsr_result_readiness_service import build_lsr_result_readiness

    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=cited_all(job["accepted_rows"]),
        catalog_locators=["АР!R9"],
        catalog_work_count=1,
    )
    assert readiness["counts"]["declared_gaps"] == 0
    assert format_lsr_readiness_notice(readiness).startswith("ЛСР собрана.")


def test_bound_constant_sits_above_every_healthy_stall_streak():
    # Live evidence from the customer ВОР on build 806: a healthy 12-pass run
    # produced two streaks of three identical remainders (377 while the query
    # cache warmed, 231 on a hard packet) and then moved again, while the
    # pathological run reported the same remainder 34 times.  Four is above the
    # first and far below the second.
    assert STALL_TERMINAL_OCCURRENCES == 4


def test_declared_gap_rows_take_title_and_volume_from_the_catalog_only():
    """The app-side builder must not invent anything the source does not say."""

    from types import SimpleNamespace

    from proxy.services.chat_evidence_application_service import declared_gap_rows

    class _Catalog:
        ROWS = {
            "АР!R18": SimpleNamespace(
                line="АР!R18: 12 | Монтаж лотка | м | 40",
                values=("12", "Монтаж лотка", "м", "40"),
                header_quantity=40,
                row_classification="work",
            ),
            # a row whose quantity column the catalog could not confirm
            "АР!R19": SimpleNamespace(
                line="АР!R19: 13 | Кабель",
                values=("13", "Кабель"),
                header_quantity=None,
                row_classification="ambiguous",
            ),
        }

        def lookup(self, raw):
            return self.ROWS.get(str(raw or "").strip())

    rows = declared_gap_rows(_Catalog(), ["АР!R18", "АР!R19", "", "Неизвестно!R7"], offers=3)

    assert [row["source_row"] for row in rows] == ["АР!R18", "АР!R19", "Неизвестно!R7"]
    assert rows[0]["unit"] == "м"
    assert rows[0]["quantity"] == 40
    assert rows[0]["title"] == "12 | Монтаж лотка | м | 40"
    assert rows[0]["row_classification"] == "work"
    # nothing to read from the catalog -> nothing asserted about the row
    assert rows[1]["quantity"] is None
    assert rows[1]["unit"] == ""
    assert rows[2]["title"] == ""  # no source line, so no invented title
    assert rows[2]["source_row"] == "Неизвестно!R7"
    assert rows[2]["norm_code"] == ""
    assert all(row["decision_origin"] == "declared_gap" for row in rows)
    assert all("не получено после 3 предложений" in row["open_gap"] for row in rows)


# --------------------------------------------------- what the document shows
def test_a_declared_gap_reaches_the_document_as_a_gap_not_a_price():
    """The customer must be able to see the row in the file, with its reason.

    A declared gap has no cipher, so it can never become a priced position -
    that is exactly why it must still appear as a binding with the source line,
    unit and volume and the application's own wording.  A row that silently
    disappears would make the document look complete when it is not.
    """
    from proxy.services.rim_lsr_trace_service import positions_from_visible_lsr_rows

    decision = declared_gap_decision(
        "LOCATOR:АР!R18",
        line="LOCATOR:АР!R18: 12 | Монтаж лотка | м | 40",
        unit="м",
        quantity=40,
        row_classification="work",
        reason=(
            "Решение модели не получено после 3 предложений; строка закрыта "
            "приложением как пробел, норма и цена не подобраны."
        ),
        attempts=3,
    )
    # the machine prefix never reaches the customer's "Строка" column
    assert decision["source_row"] == "АР!R18"
    assert decision["title"].startswith("12 | Монтаж лотка")
    assert "LOCATOR" not in decision["title"].upper()

    bound = positions_from_visible_lsr_rows([decision])
    assert bound["positions"] == []  # nothing was invented, nothing was priced
    (binding,) = bound["row_bindings"]
    assert binding["row"] == "АР!R18"
    assert binding["status"] == "missing_norm"
    assert not str(binding.get("code") or "")  # no cipher, so nothing to price
    assert "не получено после 3 предложений" in str(binding.get("message"))
    assert binding.get("source_quantity") == 40
    assert binding.get("source_unit") == "м"
    # the origin survives into the rendered trace, so a gap is never read back
    # as a model decision
    assert binding["source_row"]["decision_origin"] == "declared_gap"


def test_declared_gaps_cannot_duplicate_a_row_the_model_already_answered(tmp_path):
    """A ``LOCATOR:`` spelling must not smuggle a second position for one row."""

    service, job_id = _started(tmp_path)
    extra = [
        declared_gap_decision(
            "LOCATOR:АР!R9",
            line="Монтаж шкафа",
            unit="шт",
            quantity=4,
            row_classification="work",
            reason="дубль",
            attempts=3,
        ),
        declared_gap_decision(
            "АР!R18",
            line="Монтаж лотка",
            unit="м",
            quantity=40,
            row_classification="work",
            reason="пробел",
            attempts=3,
        ),
    ]
    job = service.finish_with_declared_gaps(job_id, gap_rows=extra, attempts=3)
    rows = service.get(job_id)["accepted_rows"]
    locators = [str(item.get("source_row")) for item in rows]
    assert locators.count("АР!R9") == 1  # the model's decision, not two
    assert "АР!R18" in locators
    # АР!R19 was never declared, so the document is still open
    assert job["status"] == "paused"
    assert job["remaining"] == ["АР!R19"]
