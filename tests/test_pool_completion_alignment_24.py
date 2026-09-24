# -*- coding: utf-8 -*-
"""Build 804: the packet pool and the completion rule must mean the same thing.

A live 300+ row ВОР could not reach ``complete``.  The per-sheet packet pool was
reduced only by ``structurally_complete_source_keys`` while the terminal rule at
the end of the sheet-pass loop also honours ``adjudicated_source_keys``.  The
loop therefore kept a pool of rows for which the model had already given a
terminal role, re-offered them, stalled, paused with those same rows in
``remaining``, and never advanced to the next sheet — whose work rows were then
never put to the model at all.  These tests pin the shared definition
(``settled_source_keys``) and the one property that makes it safe: an operator
reopen still returns a position to the pool.
"""
from __future__ import annotations

from types import SimpleNamespace

from proxy.services.chat_evidence_application_service import (
    adaptive_row_packet,
    remaining_sheet_work_locators,
    settled_source_keys,
    structurally_complete_source_keys,
)
from proxy.services.workbook_research_job_service import WorkbookResearchJobService

_SHEET_A = "ЛСР РИМ"
_SHEET_B = "Проверка"


class _Catalog:
    """Duck-typed source catalog: stable ``Sheet!Rn`` locators, work rows only."""

    def __init__(self, locators):
        self.rows = [
            SimpleNamespace(sheet=str(item).split("!")[0], locator=item, is_work_row=lambda: True)
            for item in locators
        ]

    def work_locators(self):
        return [row.locator for row in self.rows]

    def lookup(self, raw):
        key = str(raw).strip()
        for row in self.rows:
            if row.locator == key:
                return row
        return None


def _decided_rows():
    return [
        # a real position with a norm: complete AND adjudicated
        {"source_row": f"{_SHEET_A}!R17", "row_role": "work", "norm_code": "ГЭСН2020-12-01-001"},
        # the build-803 shape: the model decided it is a material with no work_row
        # link, so it keeps a quality gap but is terminal for completion
        {"source_row": f"{_SHEET_A}!R18", "row_role": "material"},
    ]


def _catalog():
    return _Catalog([f"{_SHEET_A}!R17", f"{_SHEET_A}!R18", f"{_SHEET_B}!R2"])


def test_a_decided_row_stays_in_the_pool_under_the_structural_definition_only():
    catalog = _catalog()
    rows = _decided_rows()
    # The defect, stated as a fact about the old call site: R18 is decided yet
    # still queued, and the pool for the first sheet is therefore never empty.
    assert remaining_sheet_work_locators(
        catalog, _SHEET_A, structurally_complete_source_keys(rows, catalog)
    ) == [f"{_SHEET_A}!R18"]
    assert remaining_sheet_work_locators(
        catalog, _SHEET_A, settled_source_keys(rows, catalog)
    ) == []
    # A row that received no decision at all still has to be worked.
    assert remaining_sheet_work_locators(
        catalog, _SHEET_B, settled_source_keys(rows, catalog)
    ) == [f"{_SHEET_B}!R2"]


def test_pool_and_completion_rule_leave_no_row_in_disagreement():
    catalog = _catalog()
    rows = _decided_rows()
    settled = settled_source_keys(rows, catalog)
    pooled = [
        locator
        for sheet in (_SHEET_A, _SHEET_B)
        for locator in remaining_sheet_work_locators(catalog, sheet, settled)
    ]
    unfinished = [locator for locator in catalog.work_locators() if locator not in settled]
    assert pooled == unfinished
    # Under the old split definitions the loop had work the completion rule had
    # already accepted, which is exactly the state that stalled the live job.
    complete_only = structurally_complete_source_keys(rows, catalog)
    stale = [
        locator
        for sheet in (_SHEET_A, _SHEET_B)
        for locator in remaining_sheet_work_locators(catalog, sheet, complete_only)
    ]
    accepted_unfinished = [
        locator
        for locator in catalog.work_locators()
        if locator not in complete_only and locator not in settled
    ]
    assert stale == [f"{_SHEET_A}!R18", f"{_SHEET_B}!R2"]
    assert accepted_unfinished == [f"{_SHEET_B}!R2"]


def test_the_sheet_loop_drains_and_reaches_the_second_sheet():
    # A pure replay of the orchestration contract: draw packets from the settled
    # pool, record the model decision for each offered row, and the pass must
    # terminate with every position put to the model exactly once.
    catalog = _catalog()
    rows: list[dict] = []
    offered: list[str] = []
    for sheet in (_SHEET_A, _SHEET_B):
        remaining = remaining_sheet_work_locators(catalog, sheet, settled_source_keys(rows, catalog))
        while remaining:
            packet = adaptive_row_packet(remaining, generation_reserve_tokens=4096)
            assert packet
            for locator in packet:
                assert locator not in offered, f"{locator} offered twice"
                offered.append(locator)
                rows.append(
                    {"source_row": locator, "row_role": "work", "norm_code": "ГЭСН2020-12-01-001"}
                )
            remaining = [
                locator
                for locator in remaining_sheet_work_locators(
                    catalog, sheet, settled_source_keys(rows, catalog)
                )
                if locator not in packet
            ]
    assert sorted(offered) == sorted(catalog.work_locators())
    settled = settled_source_keys(rows, catalog)
    assert [locator for locator in catalog.work_locators() if locator not in settled] == []


def test_reopen_returns_the_position_to_the_pool(tmp_path):
    # Quality reopen must survive the alignment: the durable job drops the
    # accepted rows for a reopened locator, so the shared definition queues it
    # again without any special case in the loop.
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    identity = service.identity(
        session_id="session-1",
        attachment_id="read_123456abcdef",
        source_sha256="a" * 64,
        dataset_ids=["smeta"],
        profile_revision_id="factory",
        model_identity="qwen-35b",
        question="Собери ЛСР",
    )
    job = service.begin_or_resume(identity)
    service.record_packet(
        job["job_id"],
        sheet=_SHEET_A,
        packet_locators=[f"{_SHEET_A}!R17", f"{_SHEET_A}!R18"],
        accepted_rows=_decided_rows(),
        evidence=[],
        remaining=[],
    )
    catalog = _catalog()
    settled = settled_source_keys(service.get(job["job_id"])["accepted_rows"], catalog)
    assert remaining_sheet_work_locators(catalog, _SHEET_A, settled) == []
    reopened = service.reopen_locators(job["job_id"], [f"{_SHEET_A}!R18"])
    assert [row["source_row"] for row in reopened["accepted_rows"]] == [f"{_SHEET_A}!R17"]
    assert remaining_sheet_work_locators(
        catalog, _SHEET_A, settled_source_keys(reopened["accepted_rows"], catalog)
    ) == [f"{_SHEET_A}!R18"]
