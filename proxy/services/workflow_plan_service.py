"""Shared workflow-plan contract for LES answers.

The plan is intentionally small: it does not execute tools and does not replace
domain services. It gives every answer the same machine-readable skeleton:
workflow, required inputs, evidence/claim summary, blockers and finality.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


WORKFLOW_PLAN_SCHEMA = "workflow_plan_v1"


_REQUIRED_INPUTS: dict[str, list[str]] = {
    "object_estimate": ["object_description", "norm_base", "price_basis", "project_bor_or_assumptions"],
    "estimate_harness": ["object_schema", "work_items", "norm_candidates", "price_basis"],
    "normcontrol": ["document_set", "rulepack", "requirements", "layout_or_manual_review"],
    "grounded_rag": ["scope", "retrieved_sources"],
    "table_query": ["table_dataset", "structured_rows"],
    "mail_query": ["mail_dataset", "message_sources"],
    "attachment_context": ["attachment_text"],
    "free_llm": ["user_question"],
    "command": ["command"],
    "tool": ["tool_selection"],
}


_EVIDENCE_POLICY: dict[str, str] = {
    "object_estimate": "numbers_need_provenance_and_assumptions",
    "estimate_harness": "numbers_need_provenance_and_assumptions",
    "normcontrol": "findings_need_requirement_or_computed_check",
    "grounded_rag": "claims_need_source_refs",
    "table_query": "numbers_need_structured_rows",
    "mail_query": "mail_body_snippets_only",
    "attachment_context": "attachment_context_is_not_global_evidence",
    "free_llm": "no_project_facts_without_evidence",
    "command": "tool_defined",
    "tool": "tool_defined",
}


@dataclass
class WorkflowPlan:
    workflow_id: str
    label: str
    contract_id: str
    status: str = "planned"
    finality: str = "unknown"
    route: dict[str, Any] = field(default_factory=dict)
    stages: list[dict[str, str]] = field(default_factory=list)
    required_inputs: list[str] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    evidence_policy: str = "tool_defined"
    claim_summary: dict[str, Any] = field(default_factory=dict)
    source_summary: dict[str, Any] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    schema: str = WORKFLOW_PLAN_SCHEMA

    def payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "workflow_id": self.workflow_id,
            "label": self.label,
            "contract_id": self.contract_id,
            "status": self.status,
            "finality": self.finality,
            "route": self.route,
            "stages": self.stages,
            "required_inputs": self.required_inputs,
            "missing_inputs": self.missing_inputs,
            "evidence_policy": self.evidence_policy,
            "claim_summary": self.claim_summary,
            "source_summary": self.source_summary,
            "blockers": self.blockers,
            "next_actions": self.next_actions,
        }


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _strings(values: Any) -> list[str]:
    out: list[str] = []
    for value in _as_list(values):
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _stage_id(title: str, idx: int) -> str:
    base = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(title or ""))
    base = "_".join(part for part in base.split("_") if part)
    return base[:40] or f"step_{idx + 1}"


def _stages_from_scenario(scenario: dict[str, Any]) -> list[dict[str, str]]:
    progress = _as_list(scenario.get("progress"))
    return [
        {"id": _stage_id(str(title), idx), "title": str(title), "status": "done"}
        for idx, title in enumerate(progress)
        if str(title or "").strip()
    ]


def _source_summary(payload: dict[str, Any]) -> dict[str, Any]:
    sources = _as_list(payload.get("sources"))
    source_map = payload.get("source_map")
    trace = _as_dict(payload.get("retrieval_trace"))
    if not source_map:
        source_map = trace.get("source_map") or trace.get("source_map_preview")
    return {
        "sources": len(sources),
        "source_map": len(source_map) if isinstance(source_map, (list, dict)) else 0,
        "has_retrieval_trace": bool(trace),
    }


def _defense(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("defense") or payload.get("defense_contract_v1") or {}
    raw = _as_dict(raw)
    if isinstance(raw.get("contract"), dict):
        return raw["contract"]
    return raw


def _claim_summary(payload: dict[str, Any]) -> dict[str, Any]:
    defense = _defense(payload)
    summary = _as_dict(defense.get("summary"))
    by_status = _as_dict(summary.get("by_status"))
    claims = _as_list(defense.get("claims"))
    if not by_status and claims:
        for claim in claims:
            status = str(_as_dict(claim).get("status") or "unknown")
            by_status[status] = int(by_status.get(status, 0)) + 1
    normalized = _as_list(payload.get("normalized_remarks"))
    evidence = _as_dict(payload.get("evidence_summary"))
    out = {
        "claims": len(claims),
        "by_status": by_status,
        "normalized_remarks": len(normalized),
    }
    if evidence:
        out["evidence_summary"] = evidence
    return out


def _missing_from_contract(payload: dict[str, Any]) -> list[str]:
    check = _as_dict(payload.get("answer_contract_check"))
    return _strings(check.get("missing"))


def _gaps_and_actions(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    gaps: list[str] = []
    actions: list[str] = []
    defense = _defense(payload)
    actions.extend(_strings(defense.get("required_actions")))
    for claim in _as_list(defense.get("claims")):
        c = _as_dict(claim)
        gaps.extend(_strings(c.get("gaps")))
        actions.extend(_strings(c.get("actions")))
    for item in _as_list(payload.get("normalized_remarks")):
        remark = _as_dict(item)
        if str(remark.get("human_decision") or "") in {"unset", "needs_more_evidence"}:
            action = str(remark.get("action") or "").strip()
            if action:
                actions.append(action)
    return _strings(gaps), _strings(actions)


def _blockers(payload: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for raw in _as_list(payload.get("blockers")):
        if isinstance(raw, dict):
            text = str(raw.get("reason") or raw.get("message") or raw.get("title") or "").strip()
        else:
            text = str(raw or "").strip()
        if text:
            blockers.append(text)
    trace = _as_dict(payload.get("retrieval_trace"))
    blockers.extend(_strings(trace.get("blockers")))
    return _strings(blockers)


def _status_and_finality(payload: dict[str, Any], *, blockers: list[str], missing: list[str]) -> tuple[str, str]:
    total_status = str(payload.get("total_status") or "").strip().lower()
    crag_status = str(payload.get("crag_status") or "").strip().upper()
    defense = _defense(payload)
    defense_status = str(defense.get("status") or "").strip().lower()
    if blockers or total_status == "blocked" or defense_status == "blocked":
        return "blocked", "not_final"
    if missing or total_status in {"no_data", "missing"} or defense_status == "missing":
        return "needs_data", "not_final"
    if defense_status in {"manual_required", "not_defensible"}:
        return "needs_review", "human_required"
    if total_status in {"partial", "computed_assumed", "preliminary"} or defense_status in {"partial", "assumed"}:
        return "preliminary", "not_final"
    if crag_status == "VERIFIED" or total_status == "complete" or defense_status in {"supported", "computed"}:
        return "complete", "final_for_current_sources"
    return "complete" if payload.get("answer") else "planned", "unknown"


def build_workflow_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a shared workflow plan from an already produced answer payload."""
    if not isinstance(payload, dict):
        return {}
    scenario = _as_dict(payload.get("scenario"))
    contract = _as_dict(payload.get("answer_contract"))
    route = _as_dict(payload.get("query_route"))
    workflow_id = str(scenario.get("id") or route.get("channel") or "tool")
    label = str(scenario.get("label") or workflow_id)
    contract_id = str(contract.get("id") or scenario.get("contract") or "auto")
    missing = _missing_from_contract(payload)
    gaps, actions = _gaps_and_actions(payload)
    blockers = _blockers(payload)
    missing = _strings([*missing, *gaps])
    status, finality = _status_and_finality(payload, blockers=blockers, missing=missing)
    plan = WorkflowPlan(
        workflow_id=workflow_id,
        label=label,
        contract_id=contract_id,
        status=status,
        finality=finality,
        route={
            "channel": route.get("channel"),
            "operation": route.get("operation") or route.get("intent"),
            "profile": _as_dict(route.get("profile")).get("profile_id"),
            "route_source": _as_dict(route.get("profile")).get("route_source"),
        },
        stages=_stages_from_scenario(scenario),
        required_inputs=list(_REQUIRED_INPUTS.get(workflow_id, _REQUIRED_INPUTS["tool"])),
        missing_inputs=missing,
        evidence_policy=_EVIDENCE_POLICY.get(workflow_id, "tool_defined"),
        claim_summary=_claim_summary(payload),
        source_summary=_source_summary(payload),
        blockers=blockers,
        next_actions=_strings(actions),
    )
    return plan.payload()
