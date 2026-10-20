"""Proof role changes need an operation address, never a guessed replacement.

The first answer may not have application operation IDs yet. A later proof row
on that same source can be a revision or an additional operation; a changed role
alone establishes neither. Preserve the literal proposal and earlier decisions.
"""
from copy import deepcopy

import pytest

from proxy.services import chat_evidence_application_service as service


def _row(source="S!R10", role="work", *, operation=None, quantity="0", title="Original operation"):
    row = {"source_row": source, "row_role": role, "title": title,
           "unit": "unit", "quantity": quantity, "coverage": "Literal model decision"}
    if operation is not None:
        row.update(operation_id=operation, revision=3, revision_origin="model")
    return row


def _apply(previous, proposed, *, raw="literal proof answer"):
    original_previous, original_proposed = deepcopy(previous), deepcopy(proposed)
    diagnostics = []
    rows, parsed = service.rows_after_proof_round(
        parsed_rows=proposed, previous_rows=previous, chunks=[],
        diagnostics=diagnostics, authored_answer=raw,
    )
    assert previous == original_previous, "proof admission must not mutate earlier authored decisions"
    assert proposed == original_proposed, "the literal model proposal must stay available for audit"
    return rows, parsed, diagnostics


def _assert_proposal(diagnostics, proposed, raw):
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic["code"] == "MODEL_PROOF_UPDATE_IDENTITY_AMBIGUOUS"
    assert diagnostic["source_row"] == proposed["source_row"]
    assert diagnostic["proposal"] == proposed
    assert diagnostic["raw_answer"] == raw


@pytest.mark.parametrize("has_application_id", [False, True])
def test_unaddressed_role_change_is_a_literal_proposal_not_a_second_operation(has_application_id):
    previous = [_row(operation="op_work" if has_application_id else None)]
    proposed = _row(role="unresolved", title="Changed role, same source")
    raw = 'artifact_kind: lsr\n| S!R10 | unresolved | "literal" | 0 |\n'

    rows, parsed, diagnostics = _apply(previous, [proposed], raw=raw)

    assert not parsed, "a proof with only an unaddressed change has no admitted row update"
    assert rows == previous
    assert len(rows) == 1 and rows[0]["row_role"] == "work"
    _assert_proposal(diagnostics, proposed, raw)


def test_unique_same_role_update_preserves_application_identity_and_revision():
    previous = [_row(operation="op_work", quantity="2")]
    proposed = _row(quantity="7", title="Revised authored value")

    rows, parsed, diagnostics = _apply(previous, [proposed])

    assert parsed and diagnostics == [] and len(rows) == 1
    assert rows[0]["quantity"] == "7" and rows[0]["title"] == proposed["title"]
    assert {key: rows[0][key] for key in ("operation_id", "revision", "revision_origin")} == {
        key: previous[0][key] for key in ("operation_id", "revision", "revision_origin")}


def test_explicit_operation_address_can_change_role_without_removing_another_operation():
    previous = [_row(operation="op_work"), _row(role="material", operation="op_material", quantity="9")]
    proposed = _row(role="unresolved", operation="op_work", title="Explicitly revised operation")

    rows, parsed, diagnostics = _apply(previous, [proposed])

    assert parsed and diagnostics == [] and len(rows) == 2
    assert [(row["operation_id"], row["row_role"]) for row in rows] == [
        ("op_work", "unresolved"), ("op_material", "material")]
    assert rows[0]["revision"] == previous[0]["revision"]
    assert rows[1]["quantity"] == "9"


def test_a_new_source_can_add_a_literal_new_operation():
    previous = [_row(operation="op_work")]
    proposed = _row(source="S!R20", quantity="4", title="New source operation")

    rows, parsed, diagnostics = _apply(previous, [proposed])

    assert parsed and diagnostics == [] and len(rows) == 2
    assert [(row["source_row"], row["title"]) for row in rows] == [
        (previous[0]["source_row"], previous[0]["title"]),
        (proposed["source_row"], proposed["title"])]


def test_explicit_empty_id_can_add_material_to_a_source_with_work():
    previous = [_row(operation="op_work", quantity="2")]
    proposed = _row(role="material", quantity="8", title="Explicit new material")
    proposed["operation_id"] = ""

    rows, parsed, diagnostics = _apply(previous, [proposed])

    assert parsed and diagnostics == [] and len(rows) == 2
    assert {key: rows[0][key] for key in previous[0]} == previous[0]
    assert rows[1]["operation_id"] == "" and rows[1]["row_role"] == "material"
    assert rows[1]["quantity"] == "8" and rows[1]["title"] == proposed["title"]


def test_explicit_empty_id_adds_a_separate_operation_even_when_the_role_matches():
    previous = [_row(operation="op_work", quantity="2")]
    proposed = _row(quantity="5", title="Explicit new work on the same source")
    proposed["operation_id"] = ""

    rows, parsed, diagnostics = _apply(previous, [proposed])

    assert parsed and diagnostics == [] and len(rows) == 2
    assert {key: rows[0][key] for key in previous[0]} == previous[0]
    assert rows[1]["operation_id"] == "" and rows[1]["row_role"] == "work"
    assert rows[1]["quantity"] == "5" and rows[1]["title"] == proposed["title"]


@pytest.mark.parametrize("role", ["work", "unresolved"])
def test_unknown_nonblank_id_on_an_existing_source_is_retained_as_a_proposal(role):
    previous = [_row(operation="op_work", quantity="2")]
    proposed = _row(role=role, operation="op_unknown", quantity="5", title="Unproved operation ID")
    raw = "literal proof row with an unknown nonblank operation ID"

    rows, parsed, diagnostics = _apply(previous, [proposed], raw=raw)

    assert not parsed and rows == previous
    _assert_proposal(diagnostics, proposed, raw)
    assert diagnostics[0]["operation_id"] == "op_unknown"


def test_initial_work_and_material_on_one_source_remain_two_authored_operations():
    proposed = [_row(quantity="2"), _row(role="material", quantity="8", title="Separate material")]

    rows, parsed, diagnostics = _apply([], proposed)

    assert parsed and diagnostics == [] and len(rows) == 2
    assert [(row["source_row"], row["row_role"], row["quantity"]) for row in rows] == [
        ("S!R10", "work", "2"), ("S!R10", "material", "8")]


def test_same_role_update_does_not_collapse_work_and_material_sharing_a_source():
    previous = [_row(operation="op_work", quantity="2"),
                _row(role="material", operation="op_material", quantity="8")]
    proposed = _row(quantity="5", title="Only work was revised")

    rows, parsed, diagnostics = _apply(previous, [proposed])

    assert parsed and diagnostics == [] and len(rows) == 2
    assert [(row["operation_id"], row["row_role"], row["quantity"]) for row in rows] == [
        ("op_work", "work", "5"), ("op_material", "material", "8")]


def test_unaddressed_role_change_does_not_choose_between_work_and_material():
    previous = [_row(operation="op_work"), _row(role="material", operation="op_material", quantity="8")]
    proposed = _row(role="unresolved", title="No addressed parent operation")
    raw = "literal unresolved proposal for a source with two operations"

    rows, parsed, diagnostics = _apply(previous, [proposed], raw=raw)

    assert not parsed and rows == previous
    _assert_proposal(diagnostics, proposed, raw)


def test_same_role_without_identity_does_not_choose_between_two_work_operations():
    previous = [_row(operation="op_first", quantity="2"), _row(operation="op_second", quantity="3")]
    proposed = _row(quantity="7")
    raw = "literal proof without an operation address"

    rows, parsed, diagnostics = _apply(previous, [proposed], raw=raw)

    assert not parsed and rows == previous
    _assert_proposal(diagnostics, proposed, raw)


def test_partial_proof_applies_only_addressable_update_and_retains_other_operations():
    previous = [_row(operation="op_work"), _row(role="material", operation="op_material", quantity="8"),
                _row(source="S!R20", operation="op_other", quantity="3")]
    addressed = _row(source="S!R20", quantity="6", title="Addressable same-role update")
    ambiguous = _row(role="unresolved", title="Unaddressed role proposal")
    raw = "both literal proof rows, including the unaddressed role change"

    rows, parsed, diagnostics = _apply(previous, [addressed, ambiguous], raw=raw)

    assert parsed and len(rows) == 3
    assert [(row["operation_id"], row["row_role"], row["quantity"]) for row in rows] == [
        ("op_work", "work", "0"), ("op_material", "material", "8"), ("op_other", "work", "6")]
    _assert_proposal(diagnostics, ambiguous, raw)


def test_operation_id_of_another_source_cannot_retarget_or_add_an_operation():
    previous = [_row(operation="op_work"), _row(source="S!R20", operation="op_other", quantity="3")]
    proposed = _row(operation="op_other", role="unresolved", title="Foreign source for this operation ID")
    raw = "literal source/operation identity conflict"

    rows, parsed, diagnostics = _apply(previous, [proposed], raw=raw)

    assert not parsed and rows == previous
    _assert_proposal(diagnostics, proposed, raw)
