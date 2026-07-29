"""State-scoped action contract for the conversational RIM model.

The server owns session identity, state and authorization.  The model returns
only an action, its arguments and a short user-visible intent.  User locks and
finalization are deliberately absent from every model tool set.
"""

from __future__ import annotations

import copy
from typing import Any

from proxy.smeta_core.document_workflow import batch_norm_tools


_BATCH_NORM_TOOLS = {
    str(tool["function"]["name"]): tool
    for tool in batch_norm_tools()
}

_TOOLS: dict[str, dict[str, Any]] = {
    "inspect_file": {
        "description": "Read bounded workbook metadata and visible headers.",
        "arguments": {"type": "object", "properties": {}},
    },
    "classify_file": {
        "description": "Classify the uploaded source from visible evidence.",
        "arguments": {
            "type": "object",
            "properties": {
                "source_kind": {
                    "type": "string",
                    "enum": ["vor", "specification", "kac", "pricebook", "coefficients"],
                },
                "reason": {"type": "string"},
            },
            "required": ["source_kind", "reason"],
        },
    },
    "draft_work_schedule": {
        "description": "Submit a model-authored VOR draft with source refs and quantity origins.",
        "arguments": {
            "type": "object",
            "properties": {"rows": {"type": "array", "items": {"type": "object"}}},
            "required": ["rows"],
        },
    },
    "validate_vor": {
        "description": "Run structural validation for the current VOR revision.",
        "arguments": {"type": "object", "properties": {}},
    },
    "show_mapping_table": {
        "description": "Return the current mapping table and structural issues.",
        "arguments": {"type": "object", "properties": {}},
    },
    "generate_scenarios": {
        "description": "Submit explicit compatible scenarios; never request an implicit Cartesian product.",
        "arguments": {
            "type": "object",
            "properties": {"scenarios": {"type": "array", "items": {"type": "object"}}},
            "required": ["scenarios"],
        },
    },
    "calculate_scenario": {
        "description": "Calculate one explicit scenario through deterministic smeta_core.",
        "arguments": {
            "type": "object",
            "properties": {"scenario_id": {"type": "string"}},
            "required": ["scenario_id"],
        },
    },
    "list_requirements": {
        "description": "Show unresolved prices, mappings, units and confirmations.",
        "arguments": {"type": "object", "properties": {}},
    },
    "propose_coefficient": {
        "description": "Propose a sourced coefficient for explicit user approval; do not apply it.",
        "arguments": {
            "type": "object",
            "properties": {
                "coefficient_id": {"type": "string"},
                "source_ref": {"type": "string"},
                "basis_text": {"type": "string"},
                "work_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["coefficient_id", "source_ref", "basis_text", "work_ids"],
        },
    },
    "show_rim_trace": {
        "description": "Explain the ready deterministic trace without recalculating it.",
        "arguments": {"type": "object", "properties": {}},
    },
    "request_final_lock": {
        "description": "Ask the user to review the final checklist; this action cannot create a lock.",
        "arguments": {"type": "object", "properties": {}},
    },
    "ask_user": {
        "description": "Ask one highest-value question bound to work_ids and answer options.",
        "arguments": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "reason": {"type": "string"},
                "work_ids": {"type": "array", "items": {"type": "string"}},
                "options": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            },
            "required": ["text", "reason"],
        },
    },
    "interpret_pending_answer": {
        "description": "Interpret the latest user message only as an answer to the server-owned pending question.",
        "arguments": {
            "type": "object",
            "properties": {
                "answer": {"type": "object"},
                "needs_clarification": {"type": "boolean"},
            },
            "required": ["answer", "needs_clarification"],
        },
    },
}


def allowed_model_actions(session: dict[str, Any]) -> list[str]:
    """Return at most six tools for the server-authoritative session state."""
    phase = str(session.get("phase") or "new")
    mapping = str(session.get("mapping_status") or "not_started")
    pricing = str(session.get("pricing_status") or "unpriced")
    if session.get("pending_question_id"):
        return ["interpret_pending_answer"]
    if phase in {"new", "intake"}:
        return ["inspect_file", "classify_file", "draft_work_schedule", "validate_vor", "ask_user"]
    if phase == "vor" and mapping == "not_started":
        return [
            "browse_norm_catalog",
            "search_norms_batch",
            "read_norms_batch",
            "submit_lsr_mapping",
            "ask_user",
        ]
    if mapping in {"candidates_ready", "mapping_selected", "mapping_globally_reviewed"}:
        return [
            "browse_norm_catalog",
            "search_norms_batch",
            "read_norms_batch",
            "submit_lsr_mapping",
            "show_mapping_table",
            "ask_user",
        ]
    if mapping == "mapping_locked" and pricing == "unpriced":
        return ["generate_scenarios", "calculate_scenario", "ask_user"]
    if pricing == "priced_partial":
        return ["list_requirements", "propose_coefficient", "calculate_scenario", "ask_user"]
    if pricing == "priced_draft":
        return ["show_rim_trace", "list_requirements", "request_final_lock", "ask_user"]
    return ["show_rim_trace"]


def model_tool_specs(session: dict[str, Any]) -> list[dict[str, Any]]:
    specs = []
    for name in allowed_model_actions(session):
        if name in _BATCH_NORM_TOOLS:
            specs.append(copy.deepcopy(_BATCH_NORM_TOOLS[name]))
            continue
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": _TOOLS[name]["description"],
                    "parameters": _TOOLS[name]["arguments"],
                },
            }
        )
    return specs


def validate_model_action(
    session: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Stamp a model action with authoritative state after schema/state checks."""
    forbidden = {"session_id", "state", "owner_id", "revision_id", "user_id"} & set(payload)
    if forbidden:
        raise ValueError(
            "model action contains server-owned fields: " + ", ".join(sorted(forbidden))
        )
    action = str(payload.get("action") or "")
    if action not in allowed_model_actions(session):
        raise ValueError(f"action {action!r} is not allowed in current session state")
    arguments = payload.get("arguments")
    if not isinstance(arguments, dict):
        raise ValueError("model action arguments must be an object")
    if action in _BATCH_NORM_TOOLS:
        schema = _BATCH_NORM_TOOLS[action]["function"]["parameters"]
    else:
        schema = _TOOLS[action]["arguments"]

    from proxy.services.structured_extract import validate

    schema_errors = validate(arguments, schema)
    if schema_errors:
        raise ValueError("model action arguments are invalid: " + "; ".join(schema_errors[:8]))
    if action == "search_norms_batch":
        scope_errors = []
        search_items = list(arguments.get("items") or [])
        if not search_items:
            scope_errors.append("items must not be empty")
        for index, item in enumerate(search_items):
            if not isinstance(item, dict):
                continue
            if str(item.get("scope_mode") or "") != "scoped":
                scope_errors.append(f"items[{index}].scope_mode must be scoped")
            if not list(item.get("base_types") or []):
                scope_errors.append(f"items[{index}].base_types is required")
            if not list(item.get("collections") or []):
                scope_errors.append(f"items[{index}].collections is required")
        if scope_errors:
            raise ValueError(
                "RIM search scope is invalid: " + "; ".join(scope_errors[:8])
            )
    intent = str(payload.get("user_visible_intent") or "").strip()
    if not intent:
        raise ValueError("model action requires user_visible_intent")
    return {
        "schema": "rim_agent_action_v1",
        "session_id": session["session_id"],
        "state": session["display_state"],
        "head_revision_id": session["head_revision_id"],
        "action": action,
        "arguments": arguments,
        "user_visible_intent": intent,
    }
