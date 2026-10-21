"""Optional native VOR transport preserves authored decisions and rejects ambiguity."""
from copy import deepcopy
import json
from types import MappingProxyType

import pytest

from proxy.services.context_governor_service import NativeToolCall
from proxy.services.model_lsr_result_contract import decode_model_artifact_kind, decode_model_result_rows
from proxy.services.model_workbook_terminal_transport_service import (
    WorkbookTerminalTransportError,
    build_vor_terminal_tool_schema,
    decode_workbook_terminal_response,
)


def rows():
    return [
        {"source_row": "Sheet with spaces!R2", "row_role": "work", "work_row": "op_prior",
         "title": 'Authored "operation"\nsecond line', "unit": "m²", "quantity": 0,
         "operation_id": "op_prior", "expected_revision": 4,
         "norm_code": "MODEL_LITERAL", "coverage": "Unchanged\ncoverage",
         "new_unknown_field": {"quoted": 'do not "edit"', "nullable": None}},
        {"source_row": "Sheet with spaces!R2", "row_role": "material", "work_row": "op_prior",
         "title": "Second operation on the same source", "quantity": None, "unit": "",
         "operation_id": "", "calc_quantity": 6, "calc_unit": "m", "conversion_source": "12 / 2 = 6"},
    ]


def call(arguments, name="build_vor_workbook", call_id="provider_call"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def test_mixed_proof_schema_requires_revision_only_for_committed_identity_984():
    from proxy.services.model_workbook_terminal_transport_service import build_workbook_terminal_tool_schema
    from proxy.services.structured_extract import validate

    params = build_workbook_terminal_tool_schema(
        ["S!R2"], ["op_committed"], artifact_kind="lsr", attachment_id="read_owned",
        require_operation_identity=True, proof_operation_ids=["proof_op_issued"],
    )["function"]["parameters"]
    row = {"source_row": "S!R2", "row_role": "work", "title": "Literal operation",
           "quantity": 12, "unit": "m", "operation_id": "proof_op_issued"}
    arguments = {"attachment_id": "read_owned", "decisions": [row]}
    assert validate(arguments, params) == [], "uncommitted proof has no durable revision to invent"
    assert validate({**arguments, "decisions": [{**row, "operation_id": ""}]}, params) == []
    committed = {**row, "operation_id": "op_committed"}
    assert validate({**arguments, "decisions": [committed]}, params)
    assert validate({**arguments, "decisions": [{**committed, "expected_revision": 3}]}, params) == []
    assert validate({**arguments, "decisions": [{**committed, "expected_revision": 0}]}, params)


def test_native_lsr_annotations_distinguish_source_operation_identity_and_same_unit_multiplicity():
    from proxy.services.model_workbook_terminal_transport_service import build_workbook_terminal_tool_schema

    tool = build_workbook_terminal_tool_schema(["S!R2"], ["op_prior"], artifact_kind="lsr")
    row = tool["function"]["parameters"]["properties"]["decisions"]["items"]
    properties = row["properties"]
    source = properties["source_row"].get("description", "").casefold()
    identity = properties["operation_id"].get("description", "").casefold()
    quantity = properties["quantity"].get("description", "").casefold()
    derived = properties["calc_quantity"].get("description", "").casefold()
    assert "repeat" in source and "operation_id" in source
    assert "once" in identity and "result" in identity
    assert "empty" in identity and "additional" in identity
    assert "preserve" in quantity and "source" in quantity and "calc_quantity" in quantity
    assert "multiplicity" in derived and "same" in derived and "unit" in derived
    # Advertising the distinction must preserve the literal optional carriers.
    assert properties["operation_id"]["enum"] == ["", "op_prior", None]
    assert properties["source_row"]["enum"] == ["S!R2"]
    assert "calc_quantity" not in row["required"]
    assert set(properties["calc_quantity"]["type"]) == {"number", "string", "null"}
    assert row["additionalProperties"] is True


def test_staged_proof_schema_extends_only_result_identity_and_retains_durable_parent_scope_984():
    from proxy.services.model_workbook_terminal_transport_service import build_workbook_terminal_tool_schema
    from proxy.services.proof_operation_identity_service import stage_proof_operations
    from proxy.services.structured_extract import validate

    anchors, durable = ["S!R2", "S!R3"], ["op_prior"]
    staged, issued = stage_proof_operations([
        {"source_row": "S!R2", "row_role": "work", "title": "Literal additional operation",
         "operation_id": "", "quantity": 12, "unit": "m"},
    ])
    proof_ids = tuple(issued)
    before = deepcopy((anchors, durable, staged, issued))
    default = build_workbook_terminal_tool_schema(anchors, durable, artifact_kind="lsr", attachment_id="read_owned")
    assert build_workbook_terminal_tool_schema(anchors, durable, artifact_kind="lsr", attachment_id="read_owned",
        proof_operation_ids=()) == default
    tool = build_workbook_terminal_tool_schema(anchors, durable, artifact_kind="lsr", attachment_id="read_owned",
        proof_operation_ids=proof_ids)
    params = tool["function"]["parameters"]
    original_row = default["function"]["parameters"]["properties"]["decisions"]["items"]
    row = params["properties"]["decisions"]["items"]
    properties, original_properties = row["properties"], original_row["properties"]
    assert "enum" not in original_properties["covered_by_work_id"], "default/B0 parent contract is unchanged"
    assert [value for value in properties["operation_id"]["enum"] if value not in issued] == original_properties["operation_id"]["enum"]
    assert set(proof_ids) <= set(properties["operation_id"]["enum"])
    assert "proof_unissued" not in properties["operation_id"]["enum"]
    assert properties["work_row"] == original_properties["work_row"]
    assert properties["covered_by_work_id"] == {
        **original_properties["covered_by_work_id"], "enum": properties["work_row"]["enum"],
    }
    expected_row = deepcopy(original_row)
    expected_row["properties"]["operation_id"]["enum"] = properties["operation_id"]["enum"]
    expected_row["properties"]["covered_by_work_id"] = properties["covered_by_work_id"]
    assert row == expected_row, "no other field type, required flag or professional contract changes"
    for field in ("work_row", "covered_by_work_id"):
        for parent in ("S!R2", "op_prior", "", None):
            args = {"attachment_id": "read_owned", "decisions": [{**staged[0], field: parent}]}
            assert validate(args, params) == []
        for parent in (*proof_ids, "proof_unissued"):
            args = {"attachment_id": "read_owned", "decisions": [{**staged[0], field: parent}]}
            assert validate(args, params)
    assert (anchors, durable, staged, issued) == before


@pytest.mark.parametrize("known", [True, False], ids=["issued", "unknown"])
def test_staged_native_address_roundtrip_restores_only_owned_ids_before_admission_984(known):
    from proxy.services.model_workbook_terminal_transport_service import build_workbook_terminal_tool_schema
    from proxy.services.proof_operation_identity_service import restore_proof_operations, stage_proof_operations
    from proxy.services.model_result_packet_service import admit_model_result_packet
    from proxy.services.structured_extract import validate

    authored = {"source_row": "S!R2", "row_role": "work", "title": "Literal additional operation",
                "operation_id": "", "quantity": 12, "unit": "m"}
    staged, issued = stage_proof_operations([authored])
    returned = deepcopy(staged[0])
    if not known:
        returned["operation_id"] = "proof_unissued"
    args = {"attachment_id": "read_owned", "decisions": [returned]}
    params = build_workbook_terminal_tool_schema(["S!R2"], ["op_prior"], artifact_kind="lsr",
        attachment_id="read_owned", proof_operation_ids=tuple(issued))["function"]["parameters"]
    errors = validate(args, params)
    assert (errors == []) is known
    result = decode_workbook_terminal_response([call(args, name="build_lsr_workbook")], artifact_kind="lsr")
    assert result.envelope["rows"] == [returned]  # Transport itself does not guess or repair an ID.
    restored = restore_proof_operations(result.envelope["rows"], issued)
    admission = admit_model_result_packet(restored, packet_locators=["S!R2"], prior_operations=[
        {"source_row": "S!R2", "operation_id": "op_prior", "revision": 1},
    ])
    if known:
        assert restored == [authored]
        assert admission.accepted_rows == [authored] and not admission.unapplied_proposals
    else:
        assert restored == [returned] and not admission.accepted_rows
        assert admission.unapplied_proposals[0]["reason"] == "unknown_operation_id"
        assert admission.unapplied_proposals[0]["decision"] == returned


@pytest.mark.parametrize("representation", ["string", "mapping", "typed_native"])
def test_literal_rows_arguments_quotes_unknowns_and_one_to_many_survive(representation):
    arguments = {"attachment_id": "read_owned", "decisions": rows()}
    native_arguments = json.dumps(arguments, ensure_ascii=False, indent=3)
    if representation == "mapping":
        native = call(MappingProxyType(arguments))
        # The provider shape is a parsed mapping, not a serialized tool directive.
        before = deepcopy(arguments)
    elif representation == "typed_native":
        native = NativeToolCall("provider_call", "build_vor_workbook", native_arguments)
        before = native.as_payload()
    else:
        native = call(native_arguments)
        before = deepcopy(native)
    result = decode_workbook_terminal_response([native], "Literal commentary\nwithout decisions.",
        visible_result_parser=lambda text, diagnostics: None)
    assert result.envelope == {"artifact_kind": "vor", "rows": arguments["decisions"]}
    assert result.arguments == arguments
    assert decode_model_result_rows(result.text) == arguments["decisions"]
    assert decode_model_artifact_kind(result.text)["artifact_kind"] == "vor"
    assert result.text.endswith("Literal commentary\nwithout decisions.")
    assert result.trace["row_count"] == 2 and result.trace["native_call_count"] == 1
    if representation == "mapping":
        assert dict(native["function"]["arguments"]) == before
    elif representation == "typed_native":
        assert native.as_payload() == before
    else:
        assert native == before and result.raw_arguments == native_arguments
    result.envelope["rows"][0]["new_unknown_field"]["nullable"] = "changed result copy"
    assert arguments["decisions"][0]["new_unknown_field"]["nullable"] is None


@pytest.mark.parametrize("native", [[], [call("{}", name="read_source")], [call("{}", name="build_lsr_workbook")],
    [{"tool": "build_vor_workbook", "args": {"decisions": rows()}}]])
def test_without_actual_canonical_native_terminal_text_and_read_route_are_unchanged(native):
    before = deepcopy(native)
    assert decode_workbook_terminal_response(native, "ordinary unchanged visible text") is None
    assert native == before


@pytest.mark.parametrize("extra", [call("{}", name="read_source", call_id="read_id"),
    call("{}", name="unknown_function", call_id="unknown_id"), call("{}", call_id="second_terminal")])
def test_multiple_or_mixed_calls_are_not_selected_executed_or_dropped(extra):
    native = [call(json.dumps({"decisions": rows()})), extra]
    before = deepcopy(native)
    with pytest.raises(WorkbookTerminalTransportError, match="WORKBOOK_TERMINAL_MULTIPLE_CALLS") as caught:
        decode_workbook_terminal_response(native, "Visible commentary")
    assert caught.value.raw_calls == tuple(before)
    assert caught.value.assistant_content == "Visible commentary"
    assert caught.value.trace["native_call_count"] == 2
    assert native == before


@pytest.mark.parametrize("raw", [
    '{"decisions": [], "decisions": []}',
    '{"decisions": [{"source_row": "A!R2", "source_row": "A!R3"}]}',
    '{"decisions": [{"custom": {"a": 1, "a": 1}}]}',
])
def test_duplicate_json_fields_fail_without_picking_a_value(raw):
    with pytest.raises(WorkbookTerminalTransportError, match="WORKBOOK_TERMINAL_DUPLICATE_JSON_FIELD") as caught:
        decode_workbook_terminal_response([call(raw)])
    assert caught.value.raw_calls[0]["function"]["arguments"] == raw


@pytest.mark.parametrize("arguments", ['{"decisions":[', '[]', '{"decisions": [NaN]}',
    '{"decisions": [{"quantity": 1e999}]}', {"decisions": [], "bad": (1, 2)},
    {"decisions": [], "bad": {1: "do not coerce a key"}}])
def test_malformed_or_non_json_arguments_are_diagnostic(arguments):
    with pytest.raises(WorkbookTerminalTransportError):
        decode_workbook_terminal_response([call(arguments)])


@pytest.mark.parametrize("arguments", [{}, {"decisions": None}, {"decisions": {}}, {"decisions": [None]}])
def test_missing_or_non_object_decisions_are_not_inferred(arguments):
    with pytest.raises(WorkbookTerminalTransportError, match="WORKBOOK_TERMINAL_DECISIONS_REQUIRED"):
        decode_workbook_terminal_response([call(arguments)])


@pytest.mark.parametrize("arguments,visible,code", [
    ({"decisions": [], "artifact_kind": "lsr"}, "", "ARTIFACT_KIND_CONFLICT"),
    ({"decisions": [], "rows": []}, "", "AMBIGUOUS_ROWS"),
    ({"decisions": []}, "artifact_kind: lsr", "ARTIFACT_KIND_CONFLICT"),
    ({"decisions": []}, "artifact_kind: unknown", "ARTIFACT_KIND_CONFLICT"),
    ({"decisions": []}, json.dumps({"artifact_kind": "vor", "rows": rows()}), "AMBIGUOUS_VISIBLE_RESULT"),
])
def test_conflicting_or_duplicate_authored_terminal_carriers_are_not_silently_selected(arguments, visible, code):
    with pytest.raises(WorkbookTerminalTransportError, match="WORKBOOK_TERMINAL_" + code):
        decode_workbook_terminal_response([call(arguments)], visible)


def test_empty_decisions_are_literal_empty_not_source_copy_or_new_work():
    result = decode_workbook_terminal_response([call({"attachment_id": "read_owned", "decisions": []})])
    assert result.envelope == {"artifact_kind": "vor", "rows": []}
    assert decode_model_result_rows(result.text) == []


def test_schema_projects_only_literal_scope_and_keeps_canonical_fields_and_unknown_rows():
    from proxy.services.workbook_tool_service import BUILD_VOR_WORKBOOK

    before = BUILD_VOR_WORKBOOK.public_payload()
    anchors = ["Whole sheet!R2", "Other!R5", "Whole sheet!R2"]
    shown_ids = ["op_prior", "op_other"]
    schema = build_vor_terminal_tool_schema(anchors, shown_ids, attachment_id="read_owned")
    assert schema["function"]["name"] == "build_vor_workbook"
    parameters = schema["function"]["parameters"]
    assert parameters["additionalProperties"] is False
    assert set(parameters["properties"]) == {"decisions", "attachment_id"}
    row = parameters["properties"]["decisions"]["items"]
    assert row["properties"]["source_row"]["enum"] == ["Whole sheet!R2", "Other!R5"]
    expected_refs = ["", "Whole sheet!R2", "Other!R5", "op_prior", "op_other"]
    if "null" in row["properties"]["work_row"]["type"]:
        expected_refs.append(None)
    assert row["properties"]["work_row"]["enum"] == expected_refs
    assert set(row["properties"]["row_role"]["enum"]) == {"work", "material", "equipment", "resource", "header", "unresolved"}
    original_row = before["input_schema"]["properties"]["decisions"]["items"]
    for key, value in original_row["properties"].items():
        if key not in {"source_row", "work_row", "operation_id"}:
            assert row["properties"][key] == value
    assert row["additionalProperties"] is True
    assert "operation_id" not in row["required"] and "expected_revision" not in row["required"]
    assert "norm_code" not in row["required"] and "confirmed_price" not in row["required"]
    assert parameters["properties"]["attachment_id"]["enum"] == ["read_owned"]
    assert BUILD_VOR_WORKBOOK.public_payload() == before
    assert anchors == ["Whole sheet!R2", "Other!R5", "Whole sheet!R2"] and shown_ids == ["op_prior", "op_other"]


@pytest.mark.parametrize("shape", ["markdown", "block_text"])
def test_existing_visible_parser_rejects_second_non_json_result_without_selecting_native(shape):
    from proxy.services.chat_evidence_application_service import parse_model_rag_result

    visible_row = {"source_row": "S!R2", "row_role": "work", "work_row": "", "title": "Literal work",
                   "quantity": 99, "unit": "m", "open_gap": ""}
    if shape == "markdown":
        visible = "| " + " | ".join(visible_row) + " |\n| " + " | ".join("---" for _ in visible_row)
        visible += " |\n| " + " | ".join(str(value) for value in visible_row.values()) + " |"
    else:
        visible = "\n".join(f"{key}: {value}" for key, value in visible_row.items())
    visible = "artifact_kind: vor\n" + visible
    assert parse_model_rag_result(visible)[1][0]["quantity"] == 99
    native = [call({"decisions": [{**visible_row, "quantity": 1}]})]
    before = deepcopy(native)
    with pytest.raises(WorkbookTerminalTransportError, match="WORKBOOK_TERMINAL_AMBIGUOUS_VISIBLE_RESULT") as caught:
        decode_workbook_terminal_response(native, visible, visible_result_parser=parse_model_rag_result)
    assert caught.value.raw_calls == tuple(before) and caught.value.assistant_content == visible
    assert native == before


def test_nonempty_unclassified_visible_content_fails_closed_and_diagnostics_are_not_ignored():
    native = [call({"decisions": rows()})]
    with pytest.raises(WorkbookTerminalTransportError, match="WORKBOOK_TERMINAL_VISIBLE_CLASSIFIER_REQUIRED"):
        decode_workbook_terminal_response(native, "Unclassified commentary")

    def ambiguous(text, *, diagnostics):
        diagnostics.append({"code": "MODEL_RESULT_JSON_AMBIGUOUS_RESULTS"})
        return None
    with pytest.raises(WorkbookTerminalTransportError, match="WORKBOOK_TERMINAL_AMBIGUOUS_VISIBLE_RESULT"):
        decode_workbook_terminal_response(native, "Literal ambiguity", visible_result_parser=ambiguous)


def test_nullable_work_reference_schema_and_primitive_values_remain_distinct():
    schema = build_vor_terminal_tool_schema(["S!R2"], ["op_prior"])
    work = schema["function"]["parameters"]["properties"]["decisions"]["items"]["properties"]["work_row"]
    assert (None in work["enum"]) is ("null" in work["type"])
    authored = [{"source_row": "S!R2", "row_role": "work", "title": "Literal", "work_row": value,
                 "operation_id": value, "quantity": quantity}
                for value, quantity in ((None, "23,6"), ("", 0), ("op_prior", None))]
    result = decode_workbook_terminal_response([call({"decisions": authored})])
    assert result.envelope["rows"] == authored


@pytest.mark.parametrize("kind", ["vor", "lsr"])
def test_explicit_known_workbook_kind_has_one_literal_native_carrier(kind):
    authored = [{**rows()[0], "norm_status": "CONFLICT", "action_match": "no",
                 "resource_bindings": [{"action": "exclude", "reason": "Literal model basis"}]}]
    raw = json.dumps({"attachment_id": "read_owned", "decisions": authored}, ensure_ascii=False)
    native = [call(raw, name=f"build_{kind}_workbook")]
    result = decode_workbook_terminal_response(native, artifact_kind=kind)
    assert result.envelope == {"artifact_kind": kind, "rows": authored}
    assert decode_model_result_rows(result.text) == authored
    assert decode_model_artifact_kind(result.text)["artifact_kind"] == kind
    assert result.arguments["decisions"] == authored and result.raw_arguments == raw
    assert result.trace["function"] == f"build_{kind}_workbook"
    assert result.trace["artifact_kind"] == kind


@pytest.mark.parametrize("representation", ["string", "mapping", "typed_native"])
def test_native_lsr_supply_resource_match_reaches_the_shared_row_parser_and_draft(representation):
    from tests.test_model_lsr_result_contract import _supply_match_transport_row
    from proxy.services.chat_evidence_application_service import parse_model_rag_result, compact_estimator_draft_rows

    authored = _supply_match_transport_row("unknown")
    arguments = {"attachment_id": "read_owned", "decisions": [authored]}
    raw = json.dumps(arguments, ensure_ascii=False)
    if representation == "typed_native":
        native = NativeToolCall("supply_match", "build_lsr_workbook", raw)
    else:
        native = call(arguments if representation == "mapping" else raw, name="build_lsr_workbook")
    original = deepcopy(arguments)

    result = decode_workbook_terminal_response([native], artifact_kind="lsr")
    parsed = parse_model_rag_result(result.text)

    assert result.envelope["rows"] == [authored] and arguments == original
    assert parsed is not None
    actual, = parsed[1]
    assert actual["supply_resource_match"] == authored["supply_resource_match"]
    assert compact_estimator_draft_rows([actual])[0]["supply_resource_match"] == authored["supply_resource_match"]


def test_native_lsr_schema_exposes_typed_supply_resource_match_without_requiring_norm_flags_for_materials():
    from proxy.services.model_workbook_terminal_transport_service import build_workbook_terminal_tool_schema

    schema = build_workbook_terminal_tool_schema(["S!R2"], artifact_kind="lsr")["function"]["parameters"]
    row = schema["properties"]["decisions"]["items"]
    match = row["properties"]["supply_resource_match"]
    fields = {"source_title", "resource_code", "decision", "reason", "source_refs"}
    assert set(match["properties"]) == fields
    assert set(match["properties"]["decision"]["enum"]) == {"yes", "no", "unknown"}
    assert match["properties"]["source_refs"]["type"] == "array"
    assert match["properties"]["source_refs"]["items"]["type"] == "string"
    assert not set(row.get("required", [])) & {"action_match", "object_match", "condition_match", "composition_covers"}


@pytest.mark.parametrize("field,types", [
    ("calc_quantity", {"number", "string", "null"}),
    ("calc_unit", {"string", "null"}),
    ("conversion_factor", {"number", "string", "null"}),
    ("conversion_source", {"string", "null"}),
    ("resource_code", {"string", "null"}),
    ("resource_bindings", {"array", "object", "string", "null"}),
    ("resource_review", {"object", "string", "null"}),
])
def test_native_lsr_schema_advertises_existing_optional_calculation_and_resource_fields(field, types):
    from proxy.services.model_workbook_terminal_transport_service import build_workbook_terminal_tool_schema
    from proxy.services.structured_extract import validate

    params = build_workbook_terminal_tool_schema(["S!R2"], artifact_kind="lsr")["function"]["parameters"]
    row = params["properties"]["decisions"]["items"]
    # The model must see these existing fields in the native interface, rather
    # than having to invent additional properties from the prose contract.
    assert field in row["properties"]
    advertised = row["properties"][field]
    assert set(advertised["type"]) == types
    assert isinstance(advertised.get("description"), str) and advertised["description"].strip()
    assert field not in row["required"]
    assert all(field not in clause.get("then", {}).get("required", []) for clause in row.get("allOf", []))
    assert row["additionalProperties"] is True
    minimal = {"source_row": "S!R2", "row_role": "work", "title": "Literal undecided operation"}
    assert validate({"attachment_id": "read_owned", "decisions": [minimal]}, params) == []


@pytest.mark.parametrize("representation", ["mapping", "string"])
def test_native_lsr_optional_calculation_and_resource_decisions_remain_literal(representation):
    from proxy.services.model_lsr_result_contract import MATCH_FIELDS
    from proxy.services.model_workbook_terminal_transport_service import build_workbook_terminal_tool_schema
    from proxy.services.structured_extract import validate

    authored = {
        "source_row": "S!R2", "row_role": "work", "work_row": None, "title": "Literal model operation",
        "unit": "m²", "quantity": "23,6", "norm_code": "MODEL_CARD_CODE", "norm_status": "NEEDS_RESEARCH",
        "open_gap": "Literal unresolved condition", "evidence_refs": ["Q2.H3"],
        "coverage": "Literal model applicability", **{field: "unknown" for field in MATCH_FIELDS},
        "calc_quantity": 70.8, "calc_unit": "m²", "conversion_factor": 3,
        "conversion_source": "Literal model formula: 23.6 × 3 = 70.8; Q2.H3",
        "resource_code": "LITERAL_RESOURCE_CODE",
        "resource_bindings": [{
            "action": "replace", "target_resource_ref": "Q2.H3#resource=4",
            "resource_code": "LITERAL_SELECTED_CODE", "resource_name": "Literal model resource",
            "unit": "kg", "quantity_basis": "target_norm", "reason": "Literal model basis",
            "source_refs": ["Q2.H3", "Q4.H1"], "additional_model_fact": {"literal": "preserve me"},
        }],
        "resource_review": {
            "status": "unresolved", "reason": "Literal model resource debt",
            "labor_status": "confirmed", "labor_reason": "Literal labor basis",
            "material_status": "unresolved", "material_reason": "Literal material debt",
            "additional_model_fact": {"literal": None},
        },
        "other_professional_field": {"literal": [0, False, None, "unchanged"]},
    }
    arguments = {"attachment_id": "read_owned", "decisions": [authored]}
    before = deepcopy(arguments)
    params = build_workbook_terminal_tool_schema(["S!R2"], artifact_kind="lsr")["function"]["parameters"]
    assert validate(arguments, params) == []
    native_arguments = json.dumps(arguments, ensure_ascii=False) if representation == "string" else arguments
    result = decode_workbook_terminal_response(
        [call(native_arguments, name="build_lsr_workbook")], artifact_kind="lsr")
    assert result.envelope == {"artifact_kind": "lsr", "rows": [authored]}
    assert result.arguments == before and arguments == before
    assert decode_model_result_rows(result.text) == [authored]


@pytest.mark.parametrize("declared,actual", [("lsr", "vor"), ("vor", "lsr")])
def test_known_native_function_cannot_override_model_declared_document_kind(declared, actual):
    native = [call({"decisions": rows()}, name=f"build_{actual}_workbook")]
    with pytest.raises(WorkbookTerminalTransportError, match="WORKBOOK_TERMINAL_ARTIFACT_KIND_CONFLICT") as caught:
        decode_workbook_terminal_response(native, artifact_kind=declared)
    assert caught.value.raw_calls == tuple(native)


@pytest.mark.parametrize("kind", ["vor", "lsr"])
@pytest.mark.parametrize("semantic", ["pricebook", "document_price_basis", "confirmed_data", "question",
                                       "parent_revision_id", "dataset_ids", "unknown_top_field"])
def test_terminal_only_declares_rows_and_never_silently_applies_other_arguments(kind, semantic):
    arguments = {"attachment_id": "read_owned", "decisions": rows(), semantic: {"literal": "not applied"}}
    native = [call(arguments, name=f"build_{kind}_workbook")]
    with pytest.raises(WorkbookTerminalTransportError, match="WORKBOOK_TERMINAL_UNSUPPORTED_ARGUMENTS") as caught:
        decode_workbook_terminal_response(native, artifact_kind=kind)
    assert caught.value.raw_calls == tuple(native)


@pytest.mark.parametrize("kind", ["vor", "lsr"])
@pytest.mark.parametrize("review", [False, True])
def test_generic_schema_keeps_whole_source_scope_and_requires_review_identity_only(kind, review):
    from proxy.services.model_workbook_terminal_transport_service import build_workbook_terminal_tool_schema
    from proxy.services.structured_extract import validate
    from proxy.services.workbook_tool_service import BUILD_LSR_WORKBOOK

    ordinary_before = BUILD_LSR_WORKBOOK.public_payload()
    assert ordinary_before["input_schema"]["properties"]["decisions"]["items"] == {"type": "object"}
    schema = build_workbook_terminal_tool_schema(["S!R2", "Other sheet!R77"], ["op_prior", "op_supply"],
        artifact_kind=kind, attachment_id="read_owned", require_operation_identity=review)
    params = schema["function"]["parameters"]
    assert schema["function"]["name"] == f"build_{kind}_workbook"
    assert set(params["properties"]) == {"attachment_id", "decisions"}
    row = params["properties"]["decisions"]["items"]
    assert set(("source_row", "row_role", "title")) <= set(row["required"])
    assert ("operation_id" in row["required"]) is review
    assert ("expected_revision" in row["required"]) is review
    assert row["properties"]["operation_id"]["enum"] == ["", "op_prior", "op_supply", None]
    authored = {"source_row": "Other sheet!R77", "row_role": "work", "title": "Literal work",
                "quantity": "23,6", "unit": None, "operation_id": "op_prior", "expected_revision": 4,
                "custom": {"literal": "keep"}}
    assert validate({"attachment_id": "read_owned", "decisions": [authored]}, params) == []
    new = {**authored, "operation_id": "", "expected_revision": None}
    assert validate({"attachment_id": "read_owned", "decisions": [new]}, params) == []
    if review:
        for required in ("operation_id", "expected_revision"):
            missing = {key: value for key, value in authored.items() if key != required}
            assert validate({"attachment_id": "read_owned", "decisions": [missing]}, params)
    assert validate({"attachment_id": "read_owned", "decisions": [{**authored, "operation_id": "invented_id"}]}, params)
    assert BUILD_LSR_WORKBOOK.public_payload() == ordinary_before
    if kind == "lsr":
        from proxy.services.model_lsr_result_contract import BASE_FIELDS, MATCH_FIELDS
        assert set(BASE_FIELDS) | set(MATCH_FIELDS) <= set(row["properties"])
        assert "norm_code" not in row["required"]


def test_lsr_native_conflicting_visible_markdown_cannot_replace_or_hide_rows():
    from proxy.services.chat_evidence_application_service import parse_model_rag_result

    visible = "artifact_kind: lsr\n| source_row | row_role | title | unit | quantity | norm_code |\n|---|---|---|---|---|---|\n| S!R2 | work | Visible | m | 99 | OTHER_LITERAL |"
    assert parse_model_rag_result(visible)[1][0]["quantity"] == 99
    native = [call({"decisions": rows()}, name="build_lsr_workbook")]
    with pytest.raises(WorkbookTerminalTransportError, match="WORKBOOK_TERMINAL_AMBIGUOUS_VISIBLE_RESULT"):
        decode_workbook_terminal_response(native, visible, artifact_kind="lsr", visible_result_parser=parse_model_rag_result)


def test_selected_work_norm_needs_authored_match_fields_but_supplies_and_headers_do_not():
    from proxy.services.model_workbook_terminal_transport_service import build_workbook_terminal_tool_schema
    from proxy.services.model_lsr_result_contract import MATCH_FIELDS
    from proxy.services.structured_extract import validate

    params = build_workbook_terminal_tool_schema(["S!R2"], artifact_kind="lsr")["function"]["parameters"]
    authored = {"source_row": "S!R2", "row_role": "work", "title": "Authored", "unit": "m",
                "quantity": "23,6", "work_row": None, "open_gap": "Conditions not known",
                "norm_code": "MODEL_LITERAL_CODE", "norm_status": "NEEDS_RESEARCH", "evidence_refs": ["Q1.H1"],
                "coverage": "Literal source basis", **{name: "unknown" for name in MATCH_FIELDS}}
    assert validate({"attachment_id": "read_owned", "decisions": [authored]}, params) == []
    for missing in (*MATCH_FIELDS, "evidence_refs", "coverage"):
        incomplete = {key: value for key, value in authored.items() if key != missing}
        assert validate({"attachment_id": "read_owned", "decisions": [incomplete]}, params)
    for role in ("material", "equipment", "header"):
        row = {"source_row": "S!R2", "row_role": role, "title": "Literal row", "quantity": None}
        assert validate({"attachment_id": "read_owned", "decisions": [row]}, params) == []
    # The terminal does not fill a missing claim or promote unknown to yes.
    result = decode_workbook_terminal_response([call({"decisions": [authored]}, name="build_lsr_workbook")], artifact_kind="lsr")
    assert result.envelope["rows"] == [authored]
