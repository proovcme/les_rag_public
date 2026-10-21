"""Literal native transport for the two existing optional workbook declarations.

This module never executes a workbook tool or chooses document operations. The
caller still owns ordinary text fallback, result validation and packaging.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable

from proxy.services.context_governor_service import NativeToolCall
from proxy.services.model_lsr_result_contract import (
    BASE_FIELDS,
    MATCH_FIELDS,
    SELECTED_NORM_FIELDS,
    _unique_json_object,
    decode_model_artifact_kind,
    decode_model_result_rows,
)

VOR_TERMINAL_FUNCTION = "build_vor_workbook"
_TERMINAL_KINDS = {VOR_TERMINAL_FUNCTION: "vor", "build_lsr_workbook": "lsr"}
VOR_ROW_ROLES = ("work", "material", "equipment", "resource", "header", "unresolved")


@dataclass(frozen=True)
class WorkbookTerminalTransportResult:
    text: str
    envelope: dict[str, Any]
    arguments: dict[str, Any]
    raw_arguments: str
    raw_calls: tuple[Any, ...]
    trace: dict[str, Any]


class WorkbookTerminalTransportError(ValueError):
    """An unchosen native result stays available for technical diagnostics."""

    def __init__(self, code: str, *, raw_calls: tuple[Any, ...], assistant_content: str):
        super().__init__(code)
        self.code = code
        self.raw_calls = raw_calls
        self.assistant_content = assistant_content
        self.trace = {"channel": "native_terminal_invalid", "reason": code,
                      "native_call_count": len(raw_calls), "assistant_visible_chars": len(assistant_content)}


def workbook_terminal_attachment_binding(
    terminal: WorkbookTerminalTransportResult, *, root_attachment_id: str, source_catalog,
) -> dict[str, str]:
    """Bind transport identity without changing authored rows or export scope.

    ``source_catalog`` must be the catalog already loaded from the request's
    verified root metadata. A member alias does not load that child or replace
    the root: every decision must name one literal row belonging to that member
    in the same immutable collection. Ordinary root binding stays unchanged.
    """
    provided = terminal.arguments.get("attachment_id")
    source_sha = str(getattr(source_catalog, "source_file_sha256", "") or "")
    if isinstance(root_attachment_id, str) and root_attachment_id and provided == root_attachment_id:
        return {"provided_attachment_id": provided, "root_attachment_id": root_attachment_id,
                "binding_kind": "request_root", "source_sha256": source_sha}

    def reject():
        raise WorkbookTerminalTransportError("WORKBOOK_TERMINAL_ATTACHMENT_MISMATCH",
            raw_calls=terminal.raw_calls, assistant_content="")

    from proxy.services.attachment_source_catalog_service import AttachmentSourceCatalog

    if (not isinstance(root_attachment_id, str) or not root_attachment_id
            or not isinstance(provided, str) or not provided
            or not isinstance(source_catalog, AttachmentSourceCatalog)
            or not source_catalog.source_members or len(source_sha) != 64):
        reject()
    members = [member for member in source_catalog.source_members
               if member.get("attachment_id") == provided or member.get("member_key") == provided]
    if (len(members) != 1 or members[0].get("attachment_id") != provided
            or members[0].get("member_key") != provided):
        reject()
    member_sha = members[0].get("sha256")
    if not isinstance(member_sha, str) or len(member_sha) != 64:
        reject()
    decisions = terminal.arguments.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        reject()
    prefix = provided + "::"
    known = [row.locator for row in source_catalog.rows]
    for row in decisions:
        if not isinstance(row, Mapping):
            reject()
        locator = row.get("source_row")
        if not isinstance(locator, str) or not locator.startswith(prefix) or known.count(locator) != 1:
            reject()
        origins = [origin for origin in source_catalog.source_row_origins if origin.get("source_row") == locator]
        if (len(origins) != 1 or origins[0].get("member_key") != provided
                or origins[0].get("attachment_id") != provided
                or origins[0].get("source_file_sha256") != member_sha):
            reject()
    return {"provided_attachment_id": provided, "root_attachment_id": root_attachment_id,
            "binding_kind": "verified_collection_member_alias", "source_sha256": source_sha}


def _json_values(value: Any) -> bool:
    if isinstance(value, dict):
        return all(isinstance(key, str) and _json_values(item) for key, item in value.items())
    if isinstance(value, list):
        return all(_json_values(item) for item in value)
    return value is None or type(value) in (str, int, float, bool)


def _literal_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _literal_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_literal_copy(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_literal_copy(item) for item in value)
    return value


def decode_workbook_terminal_response(
    native_calls: Sequence[Any], assistant_content: str = "", *, artifact_kind: str | None = None,
    visible_result_parser: Callable | None = None,
) -> WorkbookTerminalTransportResult | None:
    """Project one explicitly declared canonical workbook call; execute nothing.

    An omitted/None kind preserves the former VOR-only API. An explicit empty
    kind allows either existing canonical function to declare its own kind;
    a known kind remains strict. Nothing is inferred from a question.
    Unrelated calls keep the existing read/text route. A
    terminal mixed with any other call is ambiguous and must not execute reads
    or select one of the authored alternatives. Reasoning is never an input.
    """
    calls = tuple(call.as_payload() if isinstance(call, NativeToolCall) else _literal_copy(call)
                  for call in (native_calls or ()))
    known_names = {VOR_TERMINAL_FUNCTION} if artifact_kind is None else set(_TERMINAL_KINDS)
    terminal = [call for call in calls if isinstance(call, Mapping)
                and isinstance(call.get("function"), Mapping)
                and call["function"].get("name") in known_names]
    if not terminal:
        return None

    def reject(code: str):
        raise WorkbookTerminalTransportError(code, raw_calls=calls, assistant_content=assistant_content)

    if len(calls) != 1:
        reject("WORKBOOK_TERMINAL_MULTIPLE_CALLS")
    function = terminal[0]["function"]["name"]
    kind = _TERMINAL_KINDS[function]
    if artifact_kind not in (None, "") and artifact_kind != kind:
        reject("WORKBOOK_TERMINAL_ARTIFACT_KIND_CONFLICT")
    authored = terminal[0]["function"].get("arguments")
    try:
        if isinstance(authored, str):
            raw_arguments = authored
            arguments = json.loads(authored, object_pairs_hook=_unique_json_object)
            representation = "provider_json_string"
        elif isinstance(authored, Mapping):
            arguments = _literal_copy(authored)
            raw_arguments = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
            representation = "provider_object_lossless_values"
        else:
            reject("WORKBOOK_TERMINAL_ARGUMENTS_OBJECT_REQUIRED")
        if not isinstance(arguments, dict) or not _json_values(arguments):
            reject("WORKBOOK_TERMINAL_ARGUMENTS_OBJECT_REQUIRED")
        # Reject non-finite constants/overflow without changing a numeric value.
        json.dumps(arguments, ensure_ascii=False, allow_nan=False)
    except json.JSONDecodeError:
        reject("WORKBOOK_TERMINAL_ARGUMENTS_INVALID_JSON")
    except (TypeError, ValueError) as error:
        if isinstance(error, WorkbookTerminalTransportError):
            raise
        code = ("WORKBOOK_TERMINAL_DUPLICATE_JSON_FIELD"
                if str(error).startswith("duplicate authored JSON field:")
                else "WORKBOOK_TERMINAL_ARGUMENTS_INVALID_JSON")
        reject(code)
    if "artifact_kind" in arguments and arguments["artifact_kind"] != kind:
        reject("WORKBOOK_TERMINAL_ARTIFACT_KIND_CONFLICT")
    if "rows" in arguments:
        reject("WORKBOOK_TERMINAL_AMBIGUOUS_ROWS")
    if set(arguments) - {"attachment_id", "decisions"}:
        # This is an alternate row carrier, not an executor invocation. Price
        # basis, confirmations and lineage remain bound by the application;
        # silently ignoring authored semantic arguments would claim false use.
        reject("WORKBOOK_TERMINAL_UNSUPPORTED_ARGUMENTS")
    decisions = arguments.get("decisions")
    if not isinstance(decisions, list) or any(not isinstance(row, dict) for row in decisions):
        reject("WORKBOOK_TERMINAL_DECISIONS_REQUIRED")
    declaration = decode_model_artifact_kind(assistant_content)
    if (declaration["status"] in {"invalid", "conflict"}
            or (declaration["status"] == "declared" and declaration["artifact_kind"] != kind)):
        reject("WORKBOOK_TERMINAL_ARTIFACT_KIND_CONFLICT")
    visible_diagnostics: list[dict] = []
    if (decode_model_result_rows(assistant_content, diagnostics=visible_diagnostics) is not None
            or visible_diagnostics):
        reject("WORKBOOK_TERMINAL_AMBIGUOUS_VISIBLE_RESULT")
    if assistant_content:
        if visible_result_parser is None:
            reject("WORKBOOK_TERMINAL_VISIBLE_CLASSIFIER_REQUIRED")
        if (visible_result_parser(assistant_content, diagnostics=visible_diagnostics) is not None
                or visible_diagnostics):
            reject("WORKBOOK_TERMINAL_AMBIGUOUS_VISIBLE_RESULT")
    envelope = {"artifact_kind": kind, "rows": deepcopy(decisions)}
    text = json.dumps(envelope, ensure_ascii=False, allow_nan=False)
    if assistant_content:
        text += "\n\n" + assistant_content
    return WorkbookTerminalTransportResult(
        text=text, envelope=envelope, arguments=arguments, raw_arguments=raw_arguments, raw_calls=calls,
        trace={"channel": "native_terminal", "function": function, "artifact_kind": kind,
               "native_call_count": 1, "arguments_representation": representation,
               "native_arguments_chars": len(raw_arguments),
               "native_arguments_sha256": hashlib.sha256(raw_arguments.encode("utf-8")).hexdigest(),
               "assistant_visible_chars": len(assistant_content), "row_count": len(decisions)},
    )


def build_vor_terminal_tool_schema(
    source_rows: Sequence[str], shown_operation_ids: Sequence[str] = (), *, attachment_id: str | None = None,
    require_operation_identity: bool = False,
) -> dict[str, Any]:
    """Keep the existing VOR schema API as a projection of the shared builder."""
    return build_workbook_terminal_tool_schema(source_rows, shown_operation_ids, artifact_kind="vor",
        attachment_id=attachment_id, require_operation_identity=require_operation_identity)


def build_workbook_terminal_tool_schema(
    source_rows: Sequence[str], shown_operation_ids: Sequence[str] = (), *, artifact_kind: str,
    attachment_id: str | None = None, require_operation_identity: bool = False,
    technical_only: bool = False,
) -> dict[str, Any]:
    """Project exact known identifiers onto the existing canonical tool schema."""
    from proxy.services.workbook_tool_service import BUILD_LSR_WORKBOOK, BUILD_VOR_WORKBOOK

    if artifact_kind not in {"vor", "lsr"}:
        raise ValueError("a model-declared vor or lsr artifact kind is required")
    contract = BUILD_VOR_WORKBOOK if artifact_kind == "vor" else BUILD_LSR_WORKBOOK

    anchors = list(dict.fromkeys(source_rows))
    operation_ids = list(dict.fromkeys(shown_operation_ids))
    if any(not isinstance(item, str) or not item for item in (*anchors, *operation_ids)):
        raise ValueError("schema identifiers must be nonempty literal strings")
    canonical = contract.public_payload()["input_schema"]
    # Keep the ordinary execution contract unchanged. Native terminal arguments
    # can declare only rows for the current server-owned attachment.
    schema = {"type": "object", "additionalProperties": False,
        "required": ["attachment_id", "decisions"], "properties": {
            key: deepcopy(canonical["properties"][key]) for key in ("attachment_id", "decisions")}}
    properties = schema["properties"]
    row = deepcopy(BUILD_VOR_WORKBOOK.public_payload()["input_schema"]["properties"]["decisions"]["items"])
    row.update(deepcopy(properties["decisions"]["items"]))
    properties["decisions"]["items"] = row
    row["type"] = "object"
    row["additionalProperties"] = True
    row_properties = row.setdefault("properties", {})
    if artifact_kind == "lsr":
        for name in BASE_FIELDS:
            row_properties.setdefault(name, {"type": ["string", "null"]})
        row_properties["evidence_refs"] = {"type": ["string", "array", "null"], "items": {"type": "string"}}
        for name in MATCH_FIELDS:
            row_properties[name] = {"type": ["string", "null"], "enum": ["yes", "no", "unknown", "", None]}
        row_properties["nr_sp_rule_id"] = {"type": ["string", "null"]}
        row_properties["supply_resource_match"] = {
            "type": ["object", "null"], "additionalProperties": False,
            "description": ("The model's explicit match of this source product to its selected resource; "
                            "a resource code's quoted price or presence in a norm does not prove product identity."),
            "required": ["source_title", "resource_code", "decision", "reason", "source_refs"],
            "properties": {
                "source_title": {"type": "string", "description": "Exact title of this decision row."},
                "resource_code": {"type": "string", "description": "Exact selected resource_code of this row."},
                "decision": {"type": "string", "enum": ["yes", "no", "unknown"]},
                "reason": {"type": "string"},
                "source_refs": {"type": "array", "items": {"type": "string"},
                                "description": "Same nonempty reference set as this row's evidence_refs."},
            },
        }
        row["allOf"] = [{
            "if": {"required": ["row_role", "norm_code"], "properties": {
                "row_role": {"enum": ["work"]}, "norm_code": {"type": "string", "minLength": 1}}},
            "then": {"required": list(dict.fromkeys([*BASE_FIELDS, *SELECTED_NORM_FIELDS]))},
        }]
    row_properties.setdefault("source_row", {"type": "string"})["enum"] = anchors
    row_properties.setdefault("row_role", {"type": "string", "enum": list(VOR_ROW_ROLES)})
    work_property = row_properties.setdefault("work_row", {"type": "string"})
    work_references = list(dict.fromkeys(["", *anchors, *operation_ids]))
    if "null" in work_property.get("type", []):
        work_references.append(None)
    work_property["enum"] = work_references
    operation_property = row_properties.setdefault("operation_id", {"type": ["string", "null"]})
    operation_property["enum"] = ["", *operation_ids]
    if "null" in operation_property.get("type", []):
        operation_property["enum"].append(None)
    row_properties.setdefault("expected_revision", {"type": "integer", "minimum": 1})
    row["required"] = list(dict.fromkeys([*row.get("required", []), "source_row", "row_role", "title",
        *(["operation_id", "expected_revision"] if require_operation_identity else [])]))
    schema["required"] = list(dict.fromkeys([*schema.get("required", []), "decisions"]))
    if attachment_id is not None:
        if not isinstance(attachment_id, str) or not attachment_id:
            raise ValueError("attachment_id must be a nonempty literal string")
        properties["attachment_id"]["enum"] = [attachment_id]
    tool = {"type": "function", "function": {"name": contract.name,
        "description": f"Declare the completed model-authored {artifact_kind.upper()} rows for packaging; this transport does not execute a tool or choose operations, prices or confirmations.",
        "parameters": schema}}
    if technical_only:
        # Until the model declares a document kind, offer both existing carriers
        # without duplicating their professional field contracts in tool hints.
        # Exact identifiers, required identity and the authored extra fields stay
        # unchanged; ordinary post-result validation still applies.
        keep = {"source_row", "row_role", "title", "work_row", "operation_id", "expected_revision"}
        row["properties"] = {key: value for key, value in row_properties.items() if key in keep}
        row.pop("allOf", None)
        tool["function"]["description"] = "Declare completed model-authored rows; the function name declares document kind."

        def without_descriptions(value):
            if isinstance(value, dict):
                return {key: without_descriptions(item) for key, item in value.items() if key != "description"}
            if isinstance(value, list):
                return [without_descriptions(item) for item in value]
            return value

        return without_descriptions(tool)
    return tool
