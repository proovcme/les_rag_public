"""Proof replies update named decisions without losing the rest of a packet."""
import json
from copy import deepcopy

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.openai_compatible_transport_service import InferenceResponse
from tests.test_model_rag_sheet_evidence_reads import _native, _run_sheet
from tests.test_norm_card_proof_request_930 import SECOND_NORM_ANSWER


def test_partial_proof_reply_preserves_unmentioned_source_decisions():
    previous = [
        {"source_row": "Other!R7", "row_role": "work", "quantity": 4, "title": "A"},
        {"source_row": "Other!R19", "row_role": "work", "quantity": 6, "title": "B"},
    ]
    changed = dict(previous[0], quantity=9)
    rows, parsed = service.rows_after_proof_round(
        parsed_rows=[changed], previous_rows=previous, chunks=[])
    assert parsed
    assert [(r["source_row"], r["quantity"]) for r in rows] == [("Other!R7", 9), ("Other!R19", 6)]
    assert previous[0]["quantity"] == 4


def test_partial_proof_reply_preserves_other_operations_on_same_source():
    previous = [
        {"source_row": "S!R2", "row_role": "work", "operation_id": "op_a", "quantity": 2},
        {"source_row": "S!R2", "row_role": "work", "operation_id": "op_b", "quantity": 3},
    ]
    rows, parsed = service.rows_after_proof_round(
        parsed_rows=[dict(previous[0], quantity=7)], previous_rows=previous, chunks=[])
    assert parsed
    assert [(r["operation_id"], r["quantity"]) for r in rows] == [("op_a", 7), ("op_b", 3)]


def test_proof_update_without_identity_does_not_choose_between_operations():
    previous = [
        {"source_row": "S!R2", "row_role": "work", "operation_id": "op_a", "quantity": 2},
        {"source_row": "S!R2", "row_role": "work", "operation_id": "op_b", "quantity": 3},
    ]
    diagnostics = []
    rows, parsed = service.rows_after_proof_round(
        parsed_rows=[{"source_row": "S!R2", "row_role": "work", "quantity": 7}],
        previous_rows=previous, chunks=[], diagnostics=diagnostics, authored_answer="literal ambiguous reply")
    assert not parsed
    assert rows == previous
    assert diagnostics[0]["proposal"]["quantity"] == 7
    assert diagnostics[0]["raw_answer"] == "literal ambiguous reply"


def test_unique_source_role_update_preserves_application_identity_revision():
    previous = [{"source_row": "S!R2", "row_role": "work", "operation_id": "op_a",
                 "revision": 3, "revision_origin": "model", "quantity": 2}]
    rows, parsed = service.rows_after_proof_round(
        parsed_rows=[{"source_row": "S!R2", "row_role": "work", "quantity": 7}],
        previous_rows=previous, chunks=[])
    assert parsed and rows[0]["quantity"] == 7
    assert rows[0]["operation_id"] == "op_a"
    assert rows[0]["revision"] == 3


def test_duplicate_new_operation_is_a_preserved_conflicting_proposal():
    diagnostics = []
    rows, parsed = service.rows_after_proof_round(
        parsed_rows=[{"source_row": "S!R8", "row_role": "work", "operation_id": "new", "quantity": 2},
                     {"source_row": "S!R8", "row_role": "work", "operation_id": "new", "quantity": 9}],
        previous_rows=[], chunks=[], diagnostics=diagnostics, authored_answer="both authored rows")
    assert parsed and len(rows) == 1 and rows[0]["quantity"] == 2
    assert diagnostics[0]["proposal"]["quantity"] == 9
    assert diagnostics[0]["code"] == "MODEL_PROOF_UPDATE_IDENTITY_AMBIGUOUS"


@pytest.mark.parametrize("id_present", [False, True])
def test_proof_staging_issues_distinct_ids_for_identical_new_operations(id_present):
    from proxy.services.proof_operation_identity_service import (
        restore_proof_operations,
        stage_proof_operations,
    )

    row = {"source_row": "S!R8", "row_role": "work", "title": "Literal new operation",
           "quantity": "2", "norm_code": "literal-code", "evidence_refs": ["Q1.H1"]}
    if id_present:
        row["operation_id"] = ""
    original = [deepcopy(row), deepcopy(row)]
    before = deepcopy(original)

    staged, issued = stage_proof_operations(original)

    assert original == before, "staging must not mutate the model's authored rows"
    identifiers = [item["operation_id"] for item in staged]
    assert all(isinstance(identifier, str) and identifier.strip() for identifier in identifiers)
    assert len(set(identifiers)) == 2, "identical operations are not evidence of one identity"
    assert all({key: value for key, value in item.items() if key != "operation_id"}
               == {key: value for key, value in row.items() if key != "operation_id"}
               for item in staged)
    assert restore_proof_operations(staged, issued) == before


def test_proof_staging_preserves_known_ids_and_is_idempotent():
    from proxy.services.proof_operation_identity_service import stage_proof_operations

    known = {"source_row": "S!R8", "row_role": "work", "operation_id": "op_durable",
             "revision": 1, "expected_revision": 2, "quantity": "2"}
    new = {"source_row": "S!R8", "row_role": "work", "operation_id": "",
           "quantity": "2"}
    rows = [known, new]
    original = deepcopy(rows)
    staged, issued = stage_proof_operations(rows)
    stage_before, issued_before = deepcopy(staged), deepcopy(issued)

    staged_again, issued_again = stage_proof_operations(staged, issued)

    assert rows == original and staged == stage_before and issued == issued_before
    assert staged[0] == known
    assert staged[1]["operation_id"] != known["operation_id"]
    assert staged_again == staged and issued_again == issued
    assert staged_again[0]["expected_revision"] == 2


def test_proof_issued_ids_survive_json_snapshot_restart_without_reissuance():
    from proxy.services.proof_operation_identity_service import (
        restore_proof_operations,
        stage_proof_operations,
    )

    rows = [{"source_row": "S!R8", "row_role": "work", "title": "Same", "quantity": "2"},
            {"source_row": "S!R8", "row_role": "work", "operation_id": "",
             "title": "Same", "quantity": "2"}]
    staged, issued = stage_proof_operations(rows)
    snapshot = json.loads(json.dumps({"rows": staged, "issued": issued}, ensure_ascii=False))

    restarted, restarted_issued = stage_proof_operations(snapshot["rows"], snapshot["issued"])

    assert restarted == staged and restarted_issued == issued
    assert restore_proof_operations(restarted, restarted_issued) == rows


def test_staged_proof_update_replaces_only_addressed_candidate_after_evidence_changes():
    from proxy.services.proof_operation_identity_service import (
        restore_proof_operations,
        stage_proof_operations,
    )

    row = {"source_row": "S!R8", "row_role": "work", "operation_id": "",
           "title": "Literal new operation", "quantity": "2", "norm_code": "literal-code",
           "evidence_refs": ["Q1.H1"],
           "resource_bindings": [{"resource_code": "resource-a", "source_refs": ["Q1.H1"]}]}
    previous, issued = stage_proof_operations([deepcopy(row), deepcopy(row)])
    previous_before = deepcopy(previous)
    changed = deepcopy(previous[0])
    changed["evidence_refs"] = ["Q2.H1"]
    changed["resource_bindings"] = [{"resource_code": "resource-b", "source_refs": ["Q2.H1"]}]
    changed_before = deepcopy(changed)
    diagnostics = []

    updated, parsed = service.rows_after_proof_round(
        parsed_rows=[changed], previous_rows=previous, chunks=[], diagnostics=diagnostics,
        authored_answer="Literal proof update with the application-issued operation address")

    assert parsed and diagnostics == []
    assert previous == previous_before and changed == changed_before
    assert len(updated) == 2, "proof reads must not append another copy of a staged operation"
    assert [item["operation_id"] for item in updated] == [item["operation_id"] for item in previous]
    assert updated[0]["evidence_refs"] == ["Q2.H1"]
    assert updated[0]["resource_bindings"] == changed["resource_bindings"]
    assert updated[1]["resource_bindings"] == previous[1]["resource_bindings"]
    restored = restore_proof_operations(updated, issued)
    assert len(restored) == 2 and all(item["operation_id"] == "" for item in restored)
    assert restored[0]["resource_bindings"] == changed["resource_bindings"]


def test_proof_restore_uses_issued_map_preserves_blank_vs_absent_and_literal_subject():
    from proxy.services.proof_operation_identity_service import (
        restore_proof_operations,
        stage_proof_operations,
    )

    rows = [{"source_row": "S!R8", "row_role": "work", "title": "New without ID", "quantity": "2"},
            {"source_row": "S!R8", "row_role": "work", "operation_id": "",
             "title": "New with blank ID", "quantity": "3"},
            {"source_row": "S!R9", "row_role": "work", "operation_id": "op_durable",
             "title": "Durable operation", "quantity": "4", "expected_revision": 2}]
    staged, issued = stage_proof_operations(rows)
    staged[0].update(title="Literal revised title", quantity="7", expected_revision=2)
    staged[1]["evidence_refs"] = ["Q8.H4"]
    staged_before, issued_before = deepcopy(staged), deepcopy(issued)

    restored = restore_proof_operations(staged, issued)

    assert staged == staged_before and issued == issued_before
    assert "operation_id" not in restored[0]
    assert restored[1]["operation_id"] == "" and restored[2]["operation_id"] == "op_durable"
    assert restored[0] == {**rows[0], "title": "Literal revised title", "quantity": "7",
                           "expected_revision": 2}
    assert restored[1] == {**rows[1], "evidence_refs": ["Q8.H4"]}
    assert restored[2] == rows[2]
    assert restore_proof_operations(staged, {}) == staged, "ID shape alone proves no issuance"


def test_proof_restore_does_not_authorize_foreign_id_or_changed_source():
    from proxy.services.proof_operation_identity_service import (
        proof_operation_context,
        restore_proof_operations,
        stage_proof_operations,
    )

    staged, issued = stage_proof_operations([
        {"source_row": "S!R8", "row_role": "work", "operation_id": "", "quantity": "2"}])
    changed_source = {**staged[0], "source_row": "S!R9"}
    foreign = {**staged[0], "operation_id": "op_unissued"}
    proposals = [changed_source, foreign]
    before = deepcopy(proposals)

    restored = restore_proof_operations(proposals, issued)
    context = proof_operation_context(proposals, issued, [])

    assert restored == before and proposals == before
    assert context["schema"] == "les.proof-operation-identities.v1"
    assert len(context["operations"]) == 2
    for item in context["operations"]:
        assert item["committed"] is False and item["identity_status"] == "unknown"
        assert "expected_revision" not in item


def test_proof_context_exposes_durable_base_revision_without_repairing_model_cas():
    from proxy.services.proof_operation_identity_service import (
        proof_operation_context,
        restore_proof_operations,
        stage_proof_operations,
    )

    durable = {"source_row": "S!R8", "row_role": "work", "operation_id": "op_durable",
               "revision": 1, "title": "Accepted operation", "quantity": "2"}
    candidate = {**durable, "revision": 2, "expected_revision": 2, "quantity": "7"}
    new = {"source_row": "S!R8", "row_role": "work", "operation_id": "", "quantity": "3"}
    unknown = {"source_row": "S!R8", "row_role": "work", "operation_id": "op_unknown",
               "revision": 8, "expected_revision": 8, "quantity": "4"}
    staged, issued = stage_proof_operations([candidate, new, unknown])
    staged_before, existing_before = deepcopy(staged), deepcopy([durable])

    context = proof_operation_context(staged, issued, [durable])

    assert staged == staged_before and [durable] == existing_before
    assert context["schema"] == "les.proof-operation-identities.v1"
    operations = {item["operation_id"]: item for item in context["operations"]}
    assert len(operations) == 3
    assert operations["op_durable"]["source_row"] == "S!R8"
    assert operations["op_durable"]["committed"] is True
    assert operations["op_durable"]["expected_revision"] == 1
    assert operations[staged[1]["operation_id"]]["committed"] is False
    assert "expected_revision" not in operations[staged[1]["operation_id"]]
    assert operations["op_unknown"]["committed"] is False
    assert operations["op_unknown"]["identity_status"] == "unknown"
    assert "expected_revision" not in operations["op_unknown"]
    restored = restore_proof_operations(staged, issued)
    assert restored[0]["revision"] == 2 and restored[0]["expected_revision"] == 2
    assert restored[2] == unknown


@pytest.mark.parametrize("link", ["work_row", "covered_by_work_id"])
def test_proof_local_parent_address_stays_visible_but_cannot_be_admitted_as_durable_link(link):
    from proxy.services.proof_operation_identity_service import (
        restore_proof_operations,
        stage_proof_operations,
    )

    parent = {"source_row": "S!R8", "row_role": "work", "operation_id": "",
              "title": "New parent", "quantity": "2", "unit": "m"}
    staged, issued = stage_proof_operations([parent])
    child = {"source_row": "S!R9", "row_role": "material", "operation_id": "",
             "title": "New child", "quantity": "3", "unit": "m",
             link: staged[0]["operation_id"]}
    restored = restore_proof_operations([*staged, child], issued)
    assert restored[0] == parent and restored[1] == child, "never guess or erase a parent relation"

    errors = service.validate_model_rag_result_structure(
        restored, [], expected_source_rows=2, validate_evidence_refs=False,
        uncommitted_operation_ids=set(issued))

    assert any(error.startswith("uncommitted_parent_reference:") for error in errors)
    assert service._sheet_pass_row_blocked(child, errors, catalog=None)
    assert not service._sheet_pass_row_blocked(parent, errors, catalog=None)


@pytest.mark.asyncio
async def test_native_read_continuation_retains_proof_question_and_prior_table(tmp_path, monkeypatch):
    run = await _run_sheet(
        tmp_path, monkeypatch, reads=False, group_char_budget=7000,
        distinct_norms=True, final_answer=SECOND_NORM_ANSWER,
        proof_replies=[
            InferenceResponse(text="", tool_calls=(_native("read_norm_card", evidence_ref="Q2.H1"),),
                              finish_reason="tool_calls", usage={}),
            InferenceResponse(text=SECOND_NORM_ANSWER, tool_calls=(), finish_reason="stop", usage={}),
        ])
    question = str(run.requests[2].messages[-1]["content"])
    continuation = "\n".join(str(m["content"]) for m in run.requests[3].messages)
    assert question.splitlines()[0] in continuation
    assert "| S!R3 | work |" in continuation
    assert run.exact_reads
    assert not run.responses
