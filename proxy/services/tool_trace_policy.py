"""Trace policy for LES tools.

Tools may retrieve, calculate, lookup, validate, and export. They must return
transparent traces and must not silently make professional domain decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolTrace:
    tool: str
    operation: str
    inputs: list[Any]
    result: Any
    trace: str
    status: str
    warnings: list[str] = field(default_factory=list)
    decision_required_from_model: bool = False
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "operation": self.operation,
            "inputs": self.inputs,
            "result": self.result,
            "trace": self.trace,
            "warnings": list(self.warnings),
            "status": self.status,
            "decision_required_from_model": self.decision_required_from_model,
            "source": self.source,
        }


FORBIDDEN_TOOL_DECISIONS = (
    "select_work_final",
    "select_norm_final",
    "select_contract_quantity",
    "missing_as_zero",
    "candidate_as_selected",
)


def make_tool_trace(
    *,
    tool: str,
    operation: str,
    inputs: list[Any],
    result: Any,
    trace: str,
    status: str = "ok",
    warnings: list[str] | None = None,
    decision_required_from_model: bool = False,
    source: str = "",
) -> ToolTrace:
    return ToolTrace(
        tool=tool,
        operation=operation,
        inputs=inputs,
        result=result,
        trace=trace,
        status=status,
        warnings=list(warnings or []),
        decision_required_from_model=decision_required_from_model,
        source=source,
    )


def validate_tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a compact validation report for a tool result payload."""
    required = ("tool", "operation", "inputs", "result", "trace", "status")
    missing = [key for key in required if key not in payload or payload.get(key) in (None, "")]
    forbidden = [
        decision
        for decision in payload.get("decisions", []) or []
        if str(decision) in FORBIDDEN_TOOL_DECISIONS
    ]
    if payload.get("status") == "missing" and payload.get("result") in (0, 0.0, "0", "0 руб"):
        forbidden.append("missing_as_zero")
    return {
        "ok": not missing and not forbidden,
        "missing": missing,
        "forbidden_decisions": forbidden,
        "has_trace": bool(payload.get("trace")),
        "decision_required_from_model": bool(payload.get("decision_required_from_model")),
    }
