"""Packet ownership is structural; professional decisions stay model-authored."""

import copy

import pytest

from proxy.services.model_result_packet_service import admit_model_result_packet
from proxy.services.workbook_research_job_service import WorkbookResearchJobService


def _last_page_rows():
    # Structural reproduction of live 858 pass 15: R98 was requested; six
    # reference descriptors were returned as twelve new work/material rows.
    rows = [{"source_row": "PDF!R98", "row_role": "header", "title": "3", "quantity": 1, "unit": "шт"}]
    for locator in ("PDF!R7", "PDF!R63", "PDF!R71", "PDF!R82", "PDF!R88", "PDF!R91"):
        for role in ("material", "work"):
            rows.append({
                "source_row": locator, "row_role": role, "title": f"authored {role}",
                "quantity": 1, "unit": "м", "operation_id": "", "norm_status": "EXACT",
                "norm_code": "08-02-409-09", "evidence_refs": ["Q163.H3"],
                "evidence_bindings": {"Q163.H3": "immutable-card"},
            })
    return rows


def test_live_last_page_preserves_twelve_off_packet_rows_as_unapplied_proposals():
    rows = _last_page_rows()
    original = copy.deepcopy(rows)
    result = admit_model_result_packet(rows, packet_locators=["PDF!R98"])
    assert result.accepted_rows == rows[:1]
    assert len(result.unapplied_proposals) == 12
    assert [item["decision"] for item in result.unapplied_proposals] == rows[1:]
    assert {item["reason"] for item in result.unapplied_proposals} == {"outside_packet_without_identity"}
    assert len(result.diagnostics) == 12
    assert rows == original
    assert all(item["decision"] is not row for item, row in zip(result.unapplied_proposals, rows[1:]))
    assert admit_model_result_packet(rows, packet_locators=["PDF!R98"]).unapplied_proposals == result.unapplied_proposals


def test_multiple_authored_operations_on_owned_locator_are_not_collapsed():
    rows = [
        {"source_row": "S!R2", "row_role": "work", "title": "mount", "quantity": 7},
        {"source_row": "S!R2", "row_role": "work", "title": "test", "quantity": 7},
        {"source_row": "S!R2", "row_role": "material", "quantity": 7},
    ]
    result = admit_model_result_packet(rows, packet_locators=["S!R2"])
    assert result.accepted_rows == rows
    assert result.unapplied_proposals == []


@pytest.mark.parametrize("revision_field", ["expected_revision", "base_revision", "revision"])
def test_explicit_known_operation_update_requires_matching_source_and_revision(revision_field):
    prior = {"source_row": "S!R2", "operation_id": "op_known", "revision": 4, "quantity": 3}
    changed = {**prior, "quantity": 9, revision_field: 4}
    result = admit_model_result_packet([changed], packet_locators=["S!R3"], prior_operations=[prior])
    assert result.accepted_rows == [changed]
    assert result.unapplied_proposals == []
    stale = {**changed, revision_field: 3}
    result = admit_model_result_packet([stale], packet_locators=["S!R2"], prior_operations=[prior])
    assert result.accepted_rows == []
    assert result.unapplied_proposals[0]["reason"] == "operation_revision_mismatch"
    assert result.unapplied_proposals[0]["decision"] == stale


@pytest.mark.parametrize("change, reason", [
    ({"source_row": "S!R3"}, "operation_source_mismatch"),
    ({"operation_id": "op_unknown"}, "unknown_operation_id"),
    ({"expected_revision": "not-a-revision"}, "invalid_expected_revision"),
    ({"expected_revision": True}, "invalid_expected_revision"),
])
def test_invalid_operation_updates_remain_complete_unapplied_proposals(change, reason):
    prior = {"source_row": "S!R2", "operation_id": "op_known", "revision": 2}
    authored = {**prior, **change, "quantity": 10, "extra_authored_field": {"literal": "unchanged"}}
    result = admit_model_result_packet([authored], packet_locators=["S!R2", "S!R3"], prior_operations=[prior])
    assert result.accepted_rows == []
    assert result.unapplied_proposals[0]["reason"] == reason
    assert result.unapplied_proposals[0]["decision"] == authored


def test_known_update_without_explicit_revision_remains_compatible():
    prior = {"source_row": "S!R2", "operation_id": "op_known", "revision": 2}
    authored = {"source_row": "S!R2", "operation_id": "op_known", "quantity": 10}
    result = admit_model_result_packet([authored], packet_locators=["S!R2"], prior_operations=[prior])
    assert result.accepted_rows == [authored]


def test_catalog_alias_comparison_never_rewrites_authored_locator():
    authored = {"source_row": "R2", "row_role": "work", "quantity": 2}
    result = admit_model_result_packet([authored], packet_locators=["S!R2"],
                                      canonicalize_locator=lambda value: "S!R2" if value == "R2" else str(value))
    assert result.accepted_rows == [authored]
    assert result.accepted_rows[0]["source_row"] == "R2"


def test_existing_bad_quantities_are_not_silently_repaired_by_packet_admission():
    six_earlier_rows = [
        {"source_row": source, "row_role": role, "quantity": quantity, "unit": unit,
         "source_quantity_confirmed": False}
        for source, role, quantity, unit in [
            ("PDF!R63", "work", .8, "км"), ("PDF!R63", "material", .8, "км"),
            ("PDF!R71", "material", .24, "км"), ("PDF!R82", "material", 200, "м"),
            ("PDF!R85", "material", 10, "м"), ("PDF!R88", "material", 500, "шт"),
        ]
    ]
    result = admit_model_result_packet(six_earlier_rows, packet_locators=[row["source_row"] for row in six_earlier_rows])
    assert result.accepted_rows == six_earlier_rows
    assert not any(row["source_quantity_confirmed"] for row in result.accepted_rows)


def _begin(service):
    identity = service.identity(session_id="packet-owner", attachment_id="read_packet", source_sha256="a" * 64,
                                dataset_ids=[], profile_revision_id="factory", model_identity="test-model", question="test")
    return service.begin_or_resume(identity)


def test_unapplied_proposals_survive_restart_and_redelivery_without_entering_accepted_rows(tmp_path):
    path = tmp_path / "packet.sqlite"
    service = WorkbookResearchJobService(path)
    job = _begin(service)
    result = admit_model_result_packet(_last_page_rows(), packet_locators=["PDF!R98"])
    kwargs = dict(sheet="PDF", packet_locators=["PDF!R98"], accepted_rows=result.accepted_rows,
                  evidence=[], unapplied_proposals=result.unapplied_proposals, remaining=[])
    first = service.record_packet(job["job_id"], **kwargs)
    repeated = service.record_packet(job["job_id"], **kwargs)
    restored = WorkbookResearchJobService(path).get(job["job_id"])
    assert len(restored["accepted_rows"]) == 1
    assert restored["accepted_rows"][0]["source_row"] == "PDF!R98"
    assert restored["unapplied_proposals"] == result.unapplied_proposals
    assert repeated["unapplied_proposals"] == first["unapplied_proposals"]
    events = [event for event in service.events_after(job["job_id"]) if event["event"] == "unapplied_model_proposals"]
    assert len(events) == 1
    assert events[0]["data"]["proposals"] == result.unapplied_proposals


def test_store_optional_scope_checks_revision_against_durable_state(tmp_path):
    service = WorkbookResearchJobService(tmp_path / "revision.sqlite")
    job = _begin(service)
    job = service.record_packet(job["job_id"], sheet="S", packet_locators=["S!R2"],
                                accepted_rows=[{"source_row": "S!R2", "row_role": "work", "quantity": 2}], evidence=[])
    original = job["accepted_rows"][0]
    first_change = {**original, "quantity": 3, "expected_revision": 1}
    job = service.record_packet(job["job_id"], sheet="S", packet_locators=["S!R2"],
                                accepted_rows=[first_change], evidence=[], enforce_packet_scope=True)
    assert job["accepted_rows"][0]["quantity"] == 3
    assert job["accepted_rows"][0]["revision"] == 2
    stale_change = {**original, "quantity": 99, "expected_revision": 1}
    job = service.record_packet(job["job_id"], sheet="S", packet_locators=["S!R2"],
                                accepted_rows=[stale_change], evidence=[], enforce_packet_scope=True)
    assert job["accepted_rows"][0]["quantity"] == 3
    assert job["unapplied_proposals"][0]["decision"] == stale_change
    assert job["unapplied_proposals"][0]["reason"] == "operation_revision_mismatch"


def test_replayed_committed_update_does_not_allocate_a_second_revision(tmp_path):
    service = WorkbookResearchJobService(tmp_path / "redelivery.sqlite")
    job = _begin(service)
    job = service.record_packet(job["job_id"], sheet="S", packet_locators=["S!R2"],
                                accepted_rows=[{"source_row": "S!R2", "row_role": "work", "quantity": 2}], evidence=[])
    original = job["accepted_rows"][0]
    changed = {**original, "quantity": 3, "expected_revision": 1}
    kwargs = dict(sheet="S", packet_locators=["S!R2"], accepted_rows=[changed], evidence=[], enforce_packet_scope=True)
    first = service.record_packet(job["job_id"], **kwargs)
    repeated = service.record_packet(job["job_id"], **kwargs)
    assert repeated["accepted_rows"] == first["accepted_rows"]
    assert repeated["accepted_rows"][0]["revision"] == 2
    assert repeated["unapplied_proposals"] == []


def test_store_rejects_unowned_rows_even_if_caller_did_not_run_helper(tmp_path):
    service = WorkbookResearchJobService(tmp_path / "direct-boundary.sqlite")
    job = _begin(service)
    job = service.record_packet(job["job_id"], sheet="PDF", packet_locators=["PDF!R98"],
                                accepted_rows=_last_page_rows(), evidence=[], enforce_packet_scope=True)
    assert len(job["accepted_rows"]) == 1
    assert len(job["unapplied_proposals"]) == 12


def test_store_scope_uses_catalog_alias_without_changing_authored_locator(tmp_path):
    service = WorkbookResearchJobService(tmp_path / "alias.sqlite")
    job = _begin(service)
    authored = {"source_row": "R2", "row_role": "work", "quantity": 2}
    job = service.record_packet(job["job_id"], sheet="S", packet_locators=["S!R2"], accepted_rows=[authored],
                                evidence=[], enforce_packet_scope=True,
                                canonicalize_locator=lambda value: "S!R2" if value == "R2" else str(value))
    assert job["accepted_rows"][0]["source_row"] == "R2"
    assert job["unapplied_proposals"] == []
