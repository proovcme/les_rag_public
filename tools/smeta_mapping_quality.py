#!/usr/bin/env python3
"""Score expert-labelled smeta mappings without entering answers into runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from proxy.smeta_core.professional_review import mapping_quality_metrics


def _mapping(payload: Any) -> dict[str, dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("selections"), dict):
        payload = payload["selections"]
    if isinstance(payload, dict) and isinstance(payload.get("decisions"), dict):
        payload = payload["decisions"]
    if isinstance(payload, dict):
        return {str(key): dict(value or {}) for key, value in payload.items()}
    if isinstance(payload, list):
        return {
            str(item.get("work_id")): dict(item)
            for item in payload
            if isinstance(item, dict) and item.get("work_id")
        }
    raise ValueError("mapping must be a work_id object, decisions/selections object, or row array")


def prepare_expert_template(payload: Any) -> dict[str, Any]:
    """Create an annotation queue without turning model proposals into expert truth."""
    if not isinstance(payload, dict):
        raise ValueError("mapping revision must be an object")
    decisions = _mapping(payload)
    source_rows = {
        str(row.get("work_id") or ""): row
        for row in (payload.get("source_rows") or [])
        if isinstance(row, dict) and str(row.get("work_id") or "")
    }
    work_ids = list(dict.fromkeys([*source_rows, *decisions]))
    selections: dict[str, dict[str, Any]] = {}
    for work_id in work_ids:
        row = source_rows.get(work_id) or {}
        proposal = decisions.get(work_id) or {}
        selections[work_id] = {
            "expert_status": "needs_expert_review",
            "source_title": str(row.get("title") or ""),
            "source_unit": str(row.get("unit") or ""),
            "source_quantity": row.get("quantity"),
            "expected_decision": "",
            "norm_code": "",
            "allowed_analog_codes": [],
            "covered_by_work_id": "",
            "notes": "",
            "model_proposal": {
                "decision": (
                    "bind" if proposal.get("norm_code") else
                    "covered_by" if proposal.get("covered_by_work_id") else
                    "unbound"
                ),
                "norm_code": str(proposal.get("norm_code") or ""),
                "covered_by_work_id": str(proposal.get("covered_by_work_id") or ""),
                "reason": str(proposal.get("reason") or ""),
            },
        }
    return {
        "schema": "smeta_expert_golden_v1",
        "instructions": (
            "A human estimator sets expert_status=approved, expected_decision, norm_code or "
            "covered_by_work_id, allowed_analog_codes and notes. Model proposals are context only."
        ),
        "selections": selections,
    }


def _assert_expert_labels_complete(expected: dict[str, dict[str, Any]]) -> None:
    pending = sorted(
        work_id
        for work_id, row in expected.items()
        if str(row.get("expert_status") or "").strip() == "needs_expert_review"
    )
    if pending:
        raise ValueError("expert golden contains unreviewed rows: " + ", ".join(pending))


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare an LES mapping with expert labels")
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--actual", type=Path)
    parser.add_argument(
        "--prepare-from", type=Path,
        help="Create a human annotation queue from a mapping revision; requires --out",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.prepare_from:
        if args.expected or args.actual or not args.out:
            parser.error("--prepare-from requires --out and cannot be combined with --expected/--actual")
        template = prepare_expert_template(json.loads(args.prepare_from.read_text(encoding="utf-8")))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"prepared_rows": len(template["selections"]), "out": str(args.out)}, ensure_ascii=False))
        return 0
    if not args.expected or not args.actual:
        parser.error("scoring requires --expected and --actual")
    expected = _mapping(json.loads(args.expected.read_text(encoding="utf-8")))
    _assert_expert_labels_complete(expected)
    actual = _mapping(json.loads(args.actual.read_text(encoding="utf-8")))
    metrics = mapping_quality_metrics(expected, actual)
    rendered = json.dumps(metrics, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
