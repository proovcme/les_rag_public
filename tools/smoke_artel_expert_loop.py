"""Smoke-audit LES/ARTEL Revit expert loop readiness."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROXY_URL = "http://127.0.0.1:8050"
DEFAULT_RUNTIME_ROOT = Path(os.getenv("LES_RUNTIME_ROOT", "/Users/ovc/Projects/LES_v2_reinstall_stress"))

SEARCH_CASES = [
    {
        "name": "revit_api_sdk",
        "query": "Revit API FamilyManager Transaction FilteredElementCollector REVIT_API_SDK_DOC",
        "expected_doc_type": "REVIT_API_SDK_DOC",
    },
    {
        "name": "fop_profile",
        "query": "ADSK_Наименование FOP shared parameters ARTEL",
        "expected_doc_type": "FOP_PROFILE",
    },
    {
        "name": "learning_case",
        "query": "FamilyLearningCase ARTEL RFA validation accepted rejected fixes",
        "expected_doc_type": "LEARNING_CASE",
    },
]


def request_json(method: str, url: str, *, payload: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
    return json.loads(body) if body else {}


def run_command(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def parse_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def health_check(proxy_url: str, timeout: float) -> dict[str, Any]:
    health = request_json("GET", f"{proxy_url.rstrip('/')}/api/health", timeout=timeout)
    rag = health.get("rag", {}) if isinstance(health, dict) else {}
    totals = rag.get("totals", {}) if isinstance(rag, dict) else {}
    qdrant = rag.get("qdrant", {}) if isinstance(rag, dict) else {}
    by_doc_type = rag.get("by_doc_type", {}) if isinstance(rag, dict) else {}
    required_doc_types = {
        "FAMILY_GUIDE",
        "FOP_PROFILE",
        "REVIT_MODEL_GUIDE",
        "REVIT_API_REFERENCE",
        "REVIT_API_SYMBOL_MAP",
        "REVIT_API_SDK_DOC",
        "LEARNING_CASE",
    }
    missing_doc_types = sorted(doc_type for doc_type in required_doc_types if doc_type not in by_doc_type)
    ok = (
        health.get("status") == "ok"
        and rag.get("status") == "ready"
        and totals.get("files", 0) > 0
        and totals.get("pending_files", 0) == 0
        and totals.get("error_files", 0) == 0
        and qdrant.get("ok") is True
        and qdrant.get("points_match_sqlite_chunks") is True
        and not missing_doc_types
    )
    return {
        "ok": ok,
        "status": health.get("status"),
        "rag_status": rag.get("status"),
        "totals": totals,
        "qdrant": qdrant,
        "by_doc_type": by_doc_type,
        "missing_doc_types": missing_doc_types,
    }


def search_case(proxy_url: str, case: dict[str, str], *, timeout: float, top_k: int) -> dict[str, Any]:
    payload = {
        "query": case["query"],
        "dataset_filter": "ARTEL",
        "top_k": top_k,
        "include_trace": True,
    }
    response = request_json("POST", f"{proxy_url.rstrip('/')}/api/search", payload=payload, timeout=timeout)
    chunks = response.get("chunks", []) if isinstance(response, dict) else []
    doc_types = [chunk.get("doc_type") for chunk in chunks if isinstance(chunk, dict)]
    expected = case["expected_doc_type"]
    return {
        "name": case["name"],
        "ok": expected in doc_types,
        "expected_doc_type": expected,
        "count": response.get("count") if isinstance(response, dict) else None,
        "doc_types": doc_types,
        "top_doc": chunks[0].get("doc_name") if chunks and isinstance(chunks[0], dict) else None,
        "top_score": chunks[0].get("score") if chunks and isinstance(chunks[0], dict) else None,
        "quality": response.get("retrieval_trace", {}).get("quality_status") if isinstance(response, dict) else None,
    }


def classify_learning_case(text: str) -> str:
    lowered = text.lower()
    if "projection source: revit_addin_validation_report" in lowered:
        return "candidate_real_revit"
    if "visibility: public_demo" in lowered or "case id: demo_" in lowered:
        return "demo"
    smoke_markers = [
        "smoke validation report",
        "synthetic report",
        "persistence smoke",
        "manual_check",
        "open family in revit",
    ]
    if any(marker in lowered for marker in smoke_markers):
        return "smoke_or_pending"
    return "unknown"


def learning_case_projection_check(runtime_root: Path) -> dict[str, Any]:
    case_dir = runtime_root / "RAG_Content" / "ARTEL" / "family_learning_cases"
    files = sorted(case_dir.glob("*.md")) if case_dir.exists() else []
    classified = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        classified.append(
            {
                "file": str(path),
                "name": path.name,
                "kind": classify_learning_case(text),
            }
        )
    real_candidates = [item for item in classified if item["kind"] == "candidate_real_revit"]
    return {
        "ok": bool(real_candidates),
        "case_dir": str(case_dir),
        "count": len(classified),
        "real_candidate_count": len(real_candidates),
        "by_kind": {kind: sum(1 for item in classified if item["kind"] == kind) for kind in sorted({item["kind"] for item in classified})},
        "cases": classified,
    }


def run_legion_check(args: argparse.Namespace, *, backend_only: bool) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "tools" / "run_artel_legion_revit_validation.py"),
        "--use-legion-artel-backend",
        "--artel-health-timeout-sec",
        str(args.artel_health_timeout_sec),
    ]
    if backend_only:
        command.append("--backend-only-smoke")
    else:
        command.append("--no-ingest")
    result = run_command(command, timeout=args.legion_timeout_sec)
    payload = parse_json_object(result.stdout)
    return {
        "ok": result.returncode == 0 or (not backend_only and payload.get("status") == "locked"),
        "returncode": result.returncode,
        "status": payload.get("status"),
        "payload": payload,
        "stderr": result.stderr,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit LES/ARTEL Revit expert loop readiness.")
    parser.add_argument("--proxy-url", default=os.getenv("LES_PROXY_URL", DEFAULT_PROXY_URL))
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--timeout-sec", type=float, default=30.0)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--check-legion", action="store_true")
    parser.add_argument("--backend-only-smoke", action="store_true")
    parser.add_argument("--legion-timeout-sec", type=float, default=60.0)
    parser.add_argument("--artel-health-timeout-sec", type=float, default=20.0)
    parser.add_argument("--require-interactive-revit", action="store_true")
    parser.add_argument("--require-real-revit-learning-case", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    summary: dict[str, Any] = {
        "status": "unknown",
        "proxy_url": args.proxy_url,
    }
    try:
        summary["health"] = health_check(args.proxy_url, args.timeout_sec)
        summary["search"] = [
            search_case(args.proxy_url, case, timeout=args.timeout_sec, top_k=args.top_k)
            for case in SEARCH_CASES
        ]
        summary["learning_case_projections"] = learning_case_projection_check(args.runtime_root)
        if args.backend_only_smoke:
            summary["backend_only_smoke"] = run_legion_check(args, backend_only=True)
        if args.check_legion:
            summary["legion_revit"] = run_legion_check(args, backend_only=False)

        checks_ok = summary["health"]["ok"] and all(item["ok"] for item in summary["search"])
        if args.require_real_revit_learning_case:
            checks_ok = checks_ok and summary["learning_case_projections"]["ok"]
        if args.backend_only_smoke:
            checks_ok = checks_ok and summary["backend_only_smoke"]["ok"]
        if args.check_legion:
            legion = summary["legion_revit"]
            checks_ok = checks_ok and legion["ok"]
            if args.require_interactive_revit:
                checks_ok = checks_ok and legion.get("status") != "locked"

        if checks_ok:
            if args.check_legion and summary["legion_revit"].get("status") == "locked":
                summary["status"] = "ready_except_revit_locked"
            else:
                summary["status"] = "ok"
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0

        summary["status"] = "failed"
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1
    except (OSError, TimeoutError, urllib.error.URLError, RuntimeError, ValueError) as exc:
        summary["status"] = "error"
        summary["error"] = str(exc)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
