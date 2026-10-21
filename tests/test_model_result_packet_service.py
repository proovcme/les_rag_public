"""Packet ownership is structural; professional decisions stay model-authored."""

import copy
import json

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


def _revision_snapshot():
    return {
        "schema": "les.model-revision-snapshot.v1", "packet_id": "packet_owned",
        "packet_locators": ["S!R2"],
        "operations": [{"operation_id": "op_known", "source_row": "S!R2", "revision": 1}],
    }


def test_capture_model_revision_snapshot_is_packet_scoped_literal_and_restart_stable():
    from proxy.services.model_result_packet_service import (
        capture_model_revision_snapshot,
        model_revision_snapshot_valid,
    )

    prior = [{"operation_id": "op_known", "source_row": "S!R2", "revision": 1,
              "title": "Literal old operation", "quantity": "2"},
             {"operation_id": "op_outside", "source_row": "S!R3", "revision": 4},
             {"source_row": "S!R2", "title": "No durable operation ID"}]
    original = copy.deepcopy(prior)
    snapshot = capture_model_revision_snapshot(prior, packet_id="packet_owned", packet_locators=["S!R2"])

    assert snapshot == _revision_snapshot() and prior == original
    assert model_revision_snapshot_valid(snapshot, packet_id="packet_owned", packet_locators=["S!R2"])
    assert not model_revision_snapshot_valid(snapshot, packet_id="packet_other", packet_locators=["S!R2"])
    assert not model_revision_snapshot_valid(snapshot, packet_id="packet_owned", packet_locators=["S!R3"])
    restarted = json.loads(json.dumps(snapshot))
    assert restarted == snapshot and model_revision_snapshot_valid(restarted)
    prior[0]["revision"] = 2
    assert snapshot["operations"][0]["revision"] == 1, "a later durable read cannot move the captured base"


@pytest.mark.parametrize("authored_revision_fields", [
    {"expected_revision": 2}, {"base_revision": "2"}, {"revision": 2},
    {"revision": 8, "base_revision": 3, "expected_revision": 2},
    {"revision": None, "base_revision": False, "expected_revision": "literal wrong CAS"},
    {},
])
def test_model_transport_binds_only_cas_to_immutable_snapshot_and_audits_literal_fields(authored_revision_fields):
    from proxy.services.model_result_packet_service import bind_model_result_revisions

    authored = {
        "source_row": "S!R2", "operation_id": "op_known", "row_role": "work",
        "title": "Literal revised operation", "quantity": "37,5", "unit": "м²",
        "norm_code": "LITERAL_MODEL_CODE", "norm_status": "NEEDS_RESEARCH",
        "calc_quantity": 150, "calc_unit": "м²", "conversion_source": "37.5 × 4; literal basis",
        "coverage": "Literal model coverage", "evidence_refs": ["Q9.H2"],
        "work_row": "S!R8", "covered_by_work_id": None,
        "resource_bindings": [{"action": "replace", "resource_code": "literal-resource",
                               "source_refs": ["Q9.H2"], "extra": {"raw": [None, False, 0]}}],
        "resource_review": {"status": "unresolved", "reason": "Literal resource debt"},
        "extra_professional_field": {"raw": [False, 0, None]},
        **authored_revision_fields,
    }
    original, snapshot = copy.deepcopy(authored), _revision_snapshot()
    snapshot_before = copy.deepcopy(snapshot)

    bound, audit = bind_model_result_revisions([authored], snapshot)

    expected = {key: value for key, value in original.items()
                if key not in {"revision", "base_revision", "expected_revision"}}
    expected["expected_revision"] = 1
    assert bound == [expected] and authored == original and snapshot == snapshot_before
    assert len(audit) == 1
    assert {key: audit[0][key] for key in (
        "action", "source_row", "operation_id", "snapshot_revision", "authored_revision_fields")} == {
            "action": "bound_to_snapshot", "source_row": "S!R2", "operation_id": "op_known",
            "snapshot_revision": 1, "authored_revision_fields": authored_revision_fields,
        }
    prior = {"source_row": "S!R2", "operation_id": "op_known", "revision": 1, "quantity": 2}
    admission = admit_model_result_packet(bound, packet_locators=["S!R2"], prior_operations=[prior])
    assert admission.accepted_rows == bound and admission.unapplied_proposals == []
    bound[0]["resource_bindings"][0]["extra"]["raw"].append("caller edit")
    assert authored == original, "binding must deep-copy nested professional decisions"


def test_model_snapshot_binding_still_rejects_a_concurrent_durable_revision():
    from proxy.services.model_result_packet_service import bind_model_result_revisions

    authored = {"source_row": "S!R2", "operation_id": "op_known", "expected_revision": 2,
                "row_role": "work", "title": "Literal changed work", "quantity": 99}
    bound, _audit = bind_model_result_revisions([authored], _revision_snapshot())
    concurrent = {"source_row": "S!R2", "operation_id": "op_known", "revision": 2,
                  "row_role": "work", "title": "Newer committed work", "quantity": 4}

    admission = admit_model_result_packet(bound, packet_locators=["S!R2"], prior_operations=[concurrent])

    assert bound[0]["expected_revision"] == 1
    assert admission.accepted_rows == []
    assert admission.unapplied_proposals[0]["reason"] == "operation_revision_mismatch"
    assert admission.unapplied_proposals[0]["decision"] == bound[0]


@pytest.mark.parametrize("change", [
    {"operation_id": "op_unknown"}, {"source_row": "S!R3"},
    {"operation_id": ""}, {"operation_id": None},
])
def test_model_revision_binding_does_not_guess_unknown_foreign_or_new_operations(change):
    from proxy.services.model_result_packet_service import bind_model_result_revisions

    authored = {"source_row": "S!R2", "operation_id": "op_known", "expected_revision": 2,
                "base_revision": "literal", "revision": 8, "title": "Same title is not an identity",
                "norm_code": "SAME_CODE", **change}
    original = copy.deepcopy(authored)

    bound, audit = bind_model_result_revisions([authored], _revision_snapshot())

    assert bound == [original] and audit == [] and authored == original


def test_model_revision_binding_does_not_assign_identity_to_a_row_without_operation_id():
    from proxy.services.model_result_packet_service import bind_model_result_revisions

    authored = {"source_row": "S!R2", "expected_revision": 8, "title": "Known title", "quantity": 2}
    bound, audit = bind_model_result_revisions([authored], _revision_snapshot())
    assert bound == [authored] and "operation_id" not in bound[0] and audit == []


def test_model_snapshot_keeps_two_operations_on_the_same_source_independent():
    from proxy.services.model_result_packet_service import (
        bind_model_result_revisions,
        capture_model_revision_snapshot,
    )

    prior = [{"source_row": "S!R2", "operation_id": "op_a", "revision": 1, "title": "Same"},
             {"source_row": "S!R2", "operation_id": "op_b", "revision": 4, "title": "Same"}]
    snapshot = capture_model_revision_snapshot(prior, packet_id="packet_owned", packet_locators=["S!R2"])
    authored = [{"source_row": "S!R2", "operation_id": "op_b", "expected_revision": 5, "title": "Same"},
                {"source_row": "S!R2", "operation_id": "op_a", "expected_revision": 2, "title": "Same"}]

    bound, audit = bind_model_result_revisions(authored, snapshot)

    assert [(row["operation_id"], row["expected_revision"]) for row in bound] == [("op_b", 4), ("op_a", 1)]
    assert [(item["operation_id"], item["snapshot_revision"]) for item in audit] == [("op_b", 4), ("op_a", 1)]


def test_model_snapshot_uses_existing_mechanical_source_key_without_rewriting_literal_source():
    from proxy.services.model_result_packet_service import bind_model_result_revisions

    authored = {"source_row": "LOCATOR:s!r2", "operation_id": "op_known", "expected_revision": 2,
                "title": "Literal source address preserved"}

    bound, audit = bind_model_result_revisions([authored], _revision_snapshot())

    assert bound == [{**authored, "expected_revision": 1}]
    assert audit[0]["source_row"] == authored["source_row"]


@pytest.mark.parametrize("invalid", [
    None, {},
    {"schema": "other"}, {"packet_id": ""}, {"packet_locators": "S!R2"},
    {"operations": [{"operation_id": "op_known", "source_row": "S!R2", "revision": True}]},
    {"operations": [{"operation_id": "op_known", "source_row": "S!R2", "revision": "1"}]},
    {"operations": [{"operation_id": "op_known", "source_row": "S!R2", "revision": 0}]},
    {"operations": [{"operation_id": "", "source_row": "S!R2", "revision": 1}]},
    {"operations": [{"operation_id": "op_known", "source_row": "S!R3", "revision": 1}]},
    {"operations": [{"operation_id": "op_known", "source_row": "S!R2", "revision": 1},
                    {"operation_id": "op_known", "source_row": "S!R2", "revision": 2}]},
])
def test_model_revision_snapshot_invalid_state_fails_closed(invalid):
    from proxy.services.model_result_packet_service import (
        bind_model_result_revisions,
        model_revision_snapshot_valid,
    )

    snapshot = ({**_revision_snapshot(), **invalid} if isinstance(invalid, dict) and invalid else invalid)
    original = copy.deepcopy(snapshot)
    assert not model_revision_snapshot_valid(snapshot)
    with pytest.raises(ValueError):
        bind_model_result_revisions([{"source_row": "S!R2", "operation_id": "op_known"}], snapshot)
    assert snapshot == original


@pytest.mark.parametrize("change", [{"revision": 2}, {"source_row": "S!R3"}])
def test_capture_rejects_inconsistent_duplicate_operation_identity(change):
    from proxy.services.model_result_packet_service import capture_model_revision_snapshot

    prior = {"source_row": "S!R2", "operation_id": "op_known", "revision": 1}
    with pytest.raises(ValueError):
        capture_model_revision_snapshot([prior, {**prior, **change}], packet_id="packet_owned",
                                        packet_locators=["S!R2", "S!R3"])


def test_capture_rejects_inconsistent_duplicate_identity_even_outside_the_requested_packet():
    from proxy.services.model_result_packet_service import capture_model_revision_snapshot

    prior = [{"source_row": "S!R2", "operation_id": "op_known", "revision": 1},
             {"source_row": "S!R3", "operation_id": "op_known", "revision": 2}]
    original = copy.deepcopy(prior)

    with pytest.raises(ValueError):
        capture_model_revision_snapshot(prior, packet_id="packet_owned", packet_locators=["S!R2"])

    assert prior == original, "scope filtering must not hide an inconsistent committed identity"


def test_model_revision_binding_is_repeatable_and_already_bound_rows_are_idempotent():
    from proxy.services.model_result_packet_service import bind_model_result_revisions

    authored = [{"source_row": "S!R2", "operation_id": "op_known", "expected_revision": 2, "quantity": 9}]
    snapshot = _revision_snapshot()
    first, first_audit = bind_model_result_revisions(authored, snapshot)
    repeated, repeated_audit = bind_model_result_revisions(authored, snapshot)
    rebound, _rebound_audit = bind_model_result_revisions(first, snapshot)
    assert repeated == first == rebound
    assert repeated_audit == first_audit
    assert authored[0]["expected_revision"] == 2 and snapshot == _revision_snapshot()


def test_direct_manual_admission_keeps_literal_stale_revision_rejected_without_transport_binding():
    prior = {"source_row": "S!R2", "operation_id": "op_known", "revision": 1, "quantity": 2}
    manual = {"source_row": "S!R2", "operation_id": "op_known", "expected_revision": 2, "quantity": 9}

    admission = admit_model_result_packet([manual], packet_locators=["S!R2"], prior_operations=[prior])

    assert admission.accepted_rows == []
    assert admission.unapplied_proposals[0]["reason"] == "operation_revision_mismatch"
    assert admission.unapplied_proposals[0]["decision"] == manual


def _catalog_alias_locator(value):
    return {"R2": "S!R2", "R3": "S!R3"}.get(value, value)


@pytest.mark.parametrize("model_source", ["R2", "S!R2"])
def test_model_snapshot_catalog_alias_preserves_literal_source_and_real_store_cas(tmp_path, model_source):
    from proxy.services.model_result_packet_service import (
        bind_model_result_revisions,
        capture_model_revision_snapshot,
    )

    store = WorkbookResearchJobService(tmp_path / "snapshot-alias.sqlite")
    job = _begin(store)
    job = store.record_packet(
        job["job_id"], sheet="S", packet_locators=["S!R2"],
        accepted_rows=[{"source_row": "R2", "row_role": "work", "title": "Literal old work",
                        "quantity": 2, "unit": "м"}], evidence=[], enforce_packet_scope=True,
        canonicalize_locator=_catalog_alias_locator,
    )
    prior = copy.deepcopy(job["accepted_rows"][0])
    assert prior["source_row"] == "R2" and prior["revision"] == 1
    snapshot = capture_model_revision_snapshot(
        [prior], packet_id="packet_owned", packet_locators=["S!R2"],
        canonicalize_locator=_catalog_alias_locator,
    )
    assert snapshot["operations"] == [{"operation_id": prior["operation_id"],
                                       "source_row": "S!R2", "revision": 1}]
    assert prior["source_row"] == "R2", "only the internal mechanical snapshot uses canonical source addresses"
    authored = {**prior, "source_row": model_source, "quantity": 9, "expected_revision": 2,
                "coverage": "Literal revised subject fields"}
    original = copy.deepcopy(authored)

    bound, audit = bind_model_result_revisions(
        [authored], snapshot, canonicalize_locator=_catalog_alias_locator,
    )

    assert authored == original and bound[0]["source_row"] == model_source
    assert bound[0]["expected_revision"] == 1 and "revision" not in bound[0]
    assert bound[0]["quantity"] == 9 and bound[0]["coverage"] == authored["coverage"]
    assert audit[0]["source_row"] == model_source
    assert audit[0]["authored_revision_fields"] == {"revision": 1, "expected_revision": 2}
    admission = admit_model_result_packet(
        bound, packet_locators=["S!R2"], prior_operations=[prior],
        canonicalize_locator=_catalog_alias_locator,
    )
    assert admission.accepted_rows == bound and admission.unapplied_proposals == []
    updated = store.record_packet(
        job["job_id"], sheet="S", packet_locators=["S!R2"], accepted_rows=bound,
        evidence=[], enforce_packet_scope=True, canonicalize_locator=_catalog_alias_locator,
    )
    assert len(updated["accepted_rows"]) == 1
    assert updated["accepted_rows"][0]["operation_id"] == prior["operation_id"]
    assert updated["accepted_rows"][0]["source_row"] == model_source
    assert updated["accepted_rows"][0]["quantity"] == 9
    assert updated["accepted_rows"][0]["revision"] == 2
    assert updated["unapplied_proposals"] == []


def test_model_snapshot_catalog_canonicalizer_does_not_repair_foreign_alias(tmp_path):
    from proxy.services.model_result_packet_service import (
        bind_model_result_revisions,
        capture_model_revision_snapshot,
    )

    store = WorkbookResearchJobService(tmp_path / "snapshot-foreign-alias.sqlite")
    job = _begin(store)
    job = store.record_packet(
        job["job_id"], sheet="S", packet_locators=["S!R2"],
        accepted_rows=[{"source_row": "R2", "row_role": "work", "quantity": 2}],
        evidence=[], enforce_packet_scope=True, canonicalize_locator=_catalog_alias_locator,
    )
    prior = copy.deepcopy(job["accepted_rows"][0])
    snapshot = capture_model_revision_snapshot(
        [prior], packet_id="packet_owned", packet_locators=["S!R2"],
        canonicalize_locator=_catalog_alias_locator,
    )
    authored = {**prior, "source_row": "R3", "quantity": 99, "expected_revision": 2}

    bound, audit = bind_model_result_revisions(
        [authored], snapshot, canonicalize_locator=_catalog_alias_locator,
    )

    assert bound == [authored] and audit == []
    updated = store.record_packet(
        job["job_id"], sheet="S", packet_locators=["S!R2"], accepted_rows=bound,
        evidence=[], enforce_packet_scope=True, canonicalize_locator=_catalog_alias_locator,
    )
    assert updated["accepted_rows"] == [prior]
    assert updated["unapplied_proposals"][0]["reason"] == "operation_source_mismatch"
    assert updated["unapplied_proposals"][0]["decision"] == authored
