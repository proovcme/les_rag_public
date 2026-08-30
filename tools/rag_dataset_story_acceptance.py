"""Human-reviewed acceptance probe for the model-visible dataset evidence path."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


QUESTION = "Расскажи про датасет."


def chat_payload(dataset_id: str) -> dict[str, Any]:
    return {
        "question": QUESTION,
        "scope": {
            "scope_type": "dataset",
            "project_ids": [],
            "dataset_ids": [str(dataset_id)],
        },
        "semantic_cache_enabled": False,
        "response_length": "detailed",
    }


def not_ready_report(dataset_id: str, readiness: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "les.dataset-story-acceptance.v1",
        "status": "N/A: corpus not ready",
        "dataset_id": str(dataset_id),
        "question": QUESTION,
        "readiness_reason": str(readiness.get("reason") or "rrf_not_ready"),
        "readiness": readiness,
    }


def acceptance_report(dataset_id: str, response: dict[str, Any]) -> dict[str, Any]:
    retrieval_trace = response.get("retrieval_trace") or {}
    return {
        "schema": "les.dataset-story-acceptance.v1",
        "status": "human_review_required",
        "dataset_id": str(dataset_id),
        "question": QUESTION,
        "answer": str(response.get("answer") or ""),
        "sources": response.get("sources") or [],
        "evidence_packet": response.get("evidence_packet") or {},
        "model_calls": ((retrieval_trace.get("context_governor") or {}).get("calls") or []),
        "retrieval_trace": retrieval_trace,
    }


def _json_request(url: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST" if body is not None else "GET",
    )
    with urlopen(request, timeout=600) as response:  # noqa: S310 - operator-selected local endpoint
        return json.loads(response.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ask the exact open dataset-story question and save model-visible evidence."
    )
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8050")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    base_url = str(args.base_url).rstrip("/")
    readiness = _json_request(f"{base_url}/api/rag/readiness")
    if not bool(readiness.get("ready")) or not bool(readiness.get("rrf_ready")):
        report = not_ready_report(args.dataset_id, readiness)
        exit_code = 2
    else:
        response = _json_request(
            f"{base_url}/api/chat",
            payload=chat_payload(args.dataset_id),
        )
        report = acceptance_report(args.dataset_id, response)
        exit_code = 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
