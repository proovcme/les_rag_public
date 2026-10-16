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
