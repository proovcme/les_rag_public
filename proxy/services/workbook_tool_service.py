"""Canonical workbook tool contracts; execution handlers arrive in the next checkpoint."""
from __future__ import annotations

from typing import Any

from proxy.services.tool_contract_service import (
    EffectClass, IdempotencyPolicy, ResultBudget, RetryPolicy, ToolContract,
)
from proxy.services.tool_registry_service import ToolRegistration, ToolRegistry


_INPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["attachment_id"],
    "properties": {
        "attachment_id": {"type": "string", "minLength": 1},
        "question": {"type": "string"},
        "project_id": {"type": ["integer", "null"]},
        "parent_revision_id": {"type": ["string", "null"]},
        "dataset_ids": {"type": ["array", "null"], "items": {"type": "string"}},
    },
}


def _contract(name: str, title: str, summary: str, model_owned_fields: tuple[str, ...]) -> ToolContract:
    return ToolContract(
        name=name, version="1.0.0", title=title, category="workbook", summary=summary,
        input_schema=_INPUT_SCHEMA, result_schema="les.workbook_tool_result.v1",
        effect=EffectClass.DRAFT, scopes=("chat_attachment", "dataset"),
        timeout_seconds=900, retry=RetryPolicy.IDEMPOTENCY_KEY,
        idempotency=IdempotencyPolicy.REQUIRED,
        result_budget=ResultBudget(max_chars=12_000, max_items=200),
        model_owned_fields=model_owned_fields,
        provenance="artifact_revision_required", tags=("workbook", "immutable_revision"),
    )


BUILD_LSR_WORKBOOK = _contract(
    "build_lsr_workbook", "Build LSR workbook",
    "Build an immutable priced LSR draft from a server-owned attachment.",
    ("norm_code", "analogue", "coverage", "coefficient"),
)
BUILD_VOR_WORKBOOK = _contract(
    "build_vor_workbook", "Build VOR workbook",
    "Build an immutable VOR draft preserving source rows and quantities.", (),
)


def _handler_pending(_args: dict[str, Any]) -> dict[str, Any]:
    raise RuntimeError("WORKBOOK_HANDLER_NOT_IMPLEMENTED")


def register_workbook_contracts(registry: ToolRegistry) -> ToolRegistry:
    for contract in (BUILD_LSR_WORKBOOK, BUILD_VOR_WORKBOOK):
        if registry.get(contract.name) is None:
            registry.register(ToolRegistration(contract=contract, handler=_handler_pending))
    return registry
