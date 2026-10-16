"""Only an actual canonical native function can declare an unknown workbook kind."""
from copy import deepcopy
import json

import pytest

from proxy.services.context_governor_service import NativeToolCall
from proxy.services.model_lsr_result_contract import decode_model_artifact_kind, decode_model_result_rows
from proxy.services.model_workbook_terminal_transport_service import (
    WorkbookTerminalTransportError,
    build_workbook_terminal_tool_schema,
    decode_workbook_terminal_response,
)


def rows():
    return [{"source_row": "A sheet!R2", "row_role": "work", "title": "Literal authored operation",
             "operation_id": "op_shown", "expected_revision": 3, "work_row": "op_shown",
             "unit": "m²", "quantity": "23,6", "calc_quantity": 0, "open_gap": None,
             "coverage": "Literal model basis", "custom": {"keep": [None, 0, False, ""]}}]


def call(kind, arguments=None, call_id="native_owned"):
    return {"id": call_id, "type": "function", "function": {
        "name": f"build_{kind}_workbook", "arguments": {"attachment_id": "read_owned", "decisions": rows()} if arguments is None else arguments}}


@pytest.mark.parametrize("kind", ["vor", "lsr"])
@pytest.mark.parametrize("representation", ["mapping", "json", "typed"])
def test_explicit_unknown_kind_uses_one_model_chosen_function_and_preserves_literal_rows(kind, representation):
    arguments = {"attachment_id": "read_owned", "decisions": rows()}
    raw = json.dumps(arguments, ensure_ascii=False, indent=2)
    native = call(kind, raw if representation != "mapping" else arguments)
    if representation == "typed":
        native = NativeToolCall("native_owned", f"build_{kind}_workbook", raw)
    before = deepcopy(native.as_payload() if isinstance(native, NativeToolCall) else native)
    result = decode_workbook_terminal_response([native], artifact_kind="")
    assert result.envelope == {"artifact_kind": kind, "rows": arguments["decisions"]}
    assert result.arguments == arguments
    assert result.raw_calls == (before,)
    assert decode_model_artifact_kind(result.text)["artifact_kind"] == kind
    assert decode_model_result_rows(result.text) == arguments["decisions"]
    assert result.trace["function"] == f"build_{kind}_workbook" and result.trace["native_call_count"] == 1
    assert result.trace["artifact_kind"] == kind
    if representation != "mapping": assert result.raw_arguments == raw
    assert (native.as_payload() if isinstance(native, NativeToolCall) else native) == before
    result.envelope["rows"][0]["custom"]["keep"].append("result copy only")
    assert arguments["decisions"][0]["custom"]["keep"] == [None, 0, False, ""]


def test_omitted_or_none_kind_keeps_the_legacy_vor_only_api():
    native = [call("lsr")]
    assert decode_workbook_terminal_response(native) is None
    assert decode_workbook_terminal_response(native, artifact_kind=None) is None
    assert decode_workbook_terminal_response([call("vor")]).envelope["artifact_kind"] == "vor"
    assert decode_workbook_terminal_response([call("vor")], artifact_kind=None).envelope["artifact_kind"] == "vor"


@pytest.mark.parametrize("declared,actual", [("vor", "lsr"), ("lsr", "vor"), ("unknown", "vor")])
def test_known_or_invalid_nonempty_kind_still_rejects_another_function(declared, actual):
    native = [call(actual)]
    with pytest.raises(WorkbookTerminalTransportError, match="ARTIFACT_KIND_CONFLICT") as caught:
        decode_workbook_terminal_response(native, artifact_kind=declared)
    assert caught.value.raw_calls == tuple(native)


@pytest.mark.parametrize("native", [[], [{"id": "read", "type": "function", "function": {"name": "read_source", "arguments": {"source_row": "A!R2"}}}],
    [{"id": "other", "type": "function", "function": {"name": "another_workbook", "arguments": {"decisions": rows()}}}]])
def test_unknown_kind_without_an_actual_known_terminal_keeps_existing_reader_or_text_route(native):
    before = deepcopy(native)
    assert decode_workbook_terminal_response(native, "artifact_kind: vor", artifact_kind="") is None
    assert native == before


@pytest.mark.parametrize("names", [("vor", "lsr"), ("vor", "vor"), ("lsr", "lsr"), ("vor", "read_source"), ("lsr", "read_source")])
def test_unknown_kind_never_selects_one_of_mixed_or_multiple_calls(names):
    native = [call(name, call_id=str(index)) if name in {"vor", "lsr"} else
              {"id": str(index), "type": "function", "function": {"name": name, "arguments": {"source_row": "A!R2"}}}
              for index, name in enumerate(names)]
    before = deepcopy(native)
    with pytest.raises(WorkbookTerminalTransportError, match="MULTIPLE_CALLS") as caught:
        decode_workbook_terminal_response(native, "Literal visible commentary", artifact_kind="")
    assert caught.value.raw_calls == tuple(before)
    assert caught.value.assistant_content == "Literal visible commentary"
    assert native == before


@pytest.mark.parametrize("kind,visible_kind", [("vor", "lsr"), ("lsr", "vor"), ("vor", "unknown")])
def test_unknown_kind_native_function_cannot_hide_a_contradictory_visible_declaration(kind, visible_kind):
    native = [call(kind)]
    visible = "artifact_kind: " + visible_kind
    with pytest.raises(WorkbookTerminalTransportError, match="ARTIFACT_KIND_CONFLICT") as caught:
        decode_workbook_terminal_response(native, visible, artifact_kind="", visible_result_parser=lambda text, diagnostics: None)
    assert caught.value.raw_calls == tuple(native) and caught.value.assistant_content == visible


@pytest.mark.parametrize("kind", ["vor", "lsr"])
def test_unknown_kind_native_and_visible_result_are_ambiguous_even_when_kind_agrees(kind):
    native = [call(kind)]
    visible = json.dumps({"artifact_kind": kind, "rows": rows()}, ensure_ascii=False)
    with pytest.raises(WorkbookTerminalTransportError, match="AMBIGUOUS_VISIBLE_RESULT") as caught:
        decode_workbook_terminal_response(native, visible, artifact_kind="")
    assert caught.value.raw_calls == tuple(native) and caught.value.assistant_content == visible


@pytest.mark.parametrize("kind", ["vor", "lsr"])
def test_unknown_kind_visible_commentary_still_needs_the_existing_classifier(kind):
    native = [call(kind)]
    with pytest.raises(WorkbookTerminalTransportError, match="VISIBLE_CLASSIFIER_REQUIRED"):
        decode_workbook_terminal_response(native, "Literal commentary", artifact_kind="")
    observed = []
    def classify(text, *, diagnostics):
        observed.append(text)
        return None
    result = decode_workbook_terminal_response(native, "Literal commentary", artifact_kind="", visible_result_parser=classify)
    assert observed == ["Literal commentary"] and result.envelope["artifact_kind"] == kind


@pytest.mark.parametrize("kind", ["vor", "lsr"])
def test_unknown_kind_does_not_silently_apply_server_owned_price_or_confirmation_arguments(kind):
    native = [call(kind, {"attachment_id": "read_owned", "decisions": rows(), "document_price_basis": {"pricebook": "model choice"}})]
    with pytest.raises(WorkbookTerminalTransportError, match="UNSUPPORTED_ARGUMENTS") as caught:
        decode_workbook_terminal_response(native, artifact_kind="")
    assert caught.value.raw_calls == tuple(native)


@pytest.mark.parametrize("kind", ["vor", "lsr"])
def test_compact_unknown_schema_keeps_all_literal_identifiers_nullable_identity_and_review_cas(kind):
    anchors = ["Sheet with spaces!R2", "Other sheet!R408", "Sheet with spaces!R2"]
    prior_ids = ["op_old_2", "op_old_408", "op_old_2"]
    before = deepcopy((anchors, prior_ids))
    full = build_workbook_terminal_tool_schema(anchors, prior_ids, artifact_kind=kind,
        attachment_id="read_owned", require_operation_identity=True)
    compact = build_workbook_terminal_tool_schema(anchors, prior_ids, artifact_kind=kind,
        attachment_id="read_owned", require_operation_identity=True, technical_only=True)
    schema = compact["function"]["parameters"]
    row = schema["properties"]["decisions"]["items"]
    original = full["function"]["parameters"]["properties"]["decisions"]["items"]
    expected = {"source_row", "row_role", "title", "work_row", "operation_id", "expected_revision"}
    assert set(row["properties"]) == expected
    assert schema["required"] == ["attachment_id", "decisions"] and schema["additionalProperties"] is False
    assert schema["properties"]["attachment_id"]["enum"] == ["read_owned"]
    assert row["required"] == original["required"]
    assert {"source_row", "row_role", "title", "operation_id", "expected_revision"} <= set(row["required"])
    assert row["additionalProperties"] is True
    assert row["properties"]["source_row"]["enum"] == anchors[:2]
    assert row["properties"]["work_row"]["enum"] == ["", *anchors[:2], *prior_ids[:2], None]
    assert row["properties"]["operation_id"]["enum"] == ["", *prior_ids[:2], None]
    assert row["properties"]["expected_revision"] == {"type": ["integer", "null"], "minimum": 1}
    assert "Other sheet!R408" in row["properties"]["source_row"]["enum"]  # Outside the current packet.
    assert (anchors, prior_ids) == before
    assert build_workbook_terminal_tool_schema(anchors, prior_ids, artifact_kind=kind,
        attachment_id="read_owned", require_operation_identity=True) == full


def test_compact_hint_preserves_authored_optional_business_fields_without_filling_values():
    authored = rows() + [{"source_row": "A sheet!R2", "row_role": "material", "title": "Literal supply",
        "operation_id": "", "expected_revision": None, "work_row": None, "unit": None,
        "quantity": None, "custom": {"empty": "", "false": False}, "nr_sp_rule_id": "model_literal"}]
    before = deepcopy(authored)
    for kind in ("vor", "lsr"):
        schema = build_workbook_terminal_tool_schema(["A sheet!R2"], ["op_shown"], artifact_kind=kind,
            attachment_id="read_owned", require_operation_identity=True, technical_only=True)
        assert schema["function"]["parameters"]["properties"]["decisions"]["items"]["additionalProperties"] is True
        result = decode_workbook_terminal_response([call(kind, {"attachment_id": "read_owned", "decisions": authored})],
            artifact_kind="")
        assert result.envelope["rows"] == before
        assert result.arguments["decisions"] == before
        assert result.envelope["rows"][0]["quantity"] == "23,6"
        assert result.envelope["rows"][1]["quantity"] is None
    assert authored == before


def test_known_lsr_full_schema_keeps_selected_norm_conditions_and_default_contract():
    from proxy.services.model_lsr_result_contract import BASE_FIELDS, MATCH_FIELDS, SELECTED_NORM_FIELDS

    args = dict(artifact_kind="lsr", attachment_id="read_owned", require_operation_identity=True)
    full = build_workbook_terminal_tool_schema(["S!R2", "S!R408"], ["op_prior"], **args)
    explicit_full = build_workbook_terminal_tool_schema(["S!R2", "S!R408"], ["op_prior"],
        technical_only=False, **args)
    row = full["function"]["parameters"]["properties"]["decisions"]["items"]
    assert full == explicit_full
    assert set(BASE_FIELDS) | set(MATCH_FIELDS) | {"nr_sp_rule_id", "evidence_refs"} <= set(row["properties"])
    condition = row["allOf"][0]
    assert condition["if"]["properties"] == {"row_role": {"enum": ["work"]}, "norm_code": {"type": "string", "minLength": 1}}
    assert condition["then"]["required"] == list(dict.fromkeys([*BASE_FIELDS, *SELECTED_NORM_FIELDS]))
    assert "description" in full["function"]
