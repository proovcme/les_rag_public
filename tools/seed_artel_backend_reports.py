"""Seed all archived ARTEL backend validation reports into LES as learning cases."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import ingest_artel_validation_report as ingest  # noqa: E402
from tools import seed_artel_learning_cases as learning_cases  # noqa: E402


DEFAULT_ARTEL_URL = "http://127.0.0.1:5057"
DEFAULT_PROXY_URL = "http://127.0.0.1:8050"


def list_validation_reports(artel_url: str, *, task_id: str = "", api_key: str = "") -> list[dict[str, Any]]:
    url = f"{artel_url.rstrip('/')}/api/validation-reports"
    if task_id:
        url += "?" + urllib.parse.urlencode({"taskId": task_id})
    data = ingest.request_json("GET", url, api_key=api_key)
    if not isinstance(data, list):
        raise ValueError(f"Expected validation report list from {url}, got {type(data).__name__}")
    return [item for item in data if isinstance(item, dict)]


def select_report_ids(reports: list[dict[str, Any]], *, limit: int = 0) -> list[str]:
    ids = [str(report.get("id", "")).strip() for report in reports]
    ids = [report_id for report_id in ids if report_id]
    return ids[:limit] if limit > 0 else ids


def seed_backend_reports(
    *,
    artel_url: str,
    task_id: str,
    artel_api_key: str,
    runtime_root: Path,
    proxy_url: str,
    les_api_key: str,
    limit: int,
    no_sync: bool,
    verify_search: bool,
    timeout_sec: float,
    poll_sec: float,
    top_k: int,
) -> dict[str, Any]:
    reports = list_validation_reports(artel_url, task_id=task_id, api_key=artel_api_key)
    report_ids = select_report_ids(reports, limit=limit)
    written: list[str] = []
    skipped: list[dict[str, str]] = []
    queries: list[str] = []

    for report_id in report_ids:
        try:
            case = ingest.load_learning_case_for_report(
                artel_url=artel_url,
                report_id=report_id,
                api_key=artel_api_key,
            )
            errors = learning_cases.validate_case(case)
            if errors:
                skipped.append({"report_id": report_id, "reason": "; ".join(errors)})
                continue
            path = learning_cases.write_projection(case, runtime_root)
            written.append(str(path))
            queries.append(learning_cases.build_default_query(case))
        except Exception as error:  # noqa: BLE001 - operator tool should report all per-report failures.
            skipped.append({"report_id": report_id, "reason": f"{type(error).__name__}: {error}"})

    sync_result: dict[str, Any] | None = None
    if written and not no_sync:
        sync_result = learning_cases.sync_artel(proxy_url, api_key=les_api_key)

    search_result: dict[str, Any] | None = None
    if written and verify_search:
        query = queries[0]
        search_result = learning_cases.wait_for_artel_search(
            proxy_url,
            query,
            top_k=top_k,
            timeout_sec=timeout_sec,
            poll_sec=poll_sec,
            api_key=les_api_key,
        )

    return {
        "reports_seen": len(reports),
        "reports_selected": len(report_ids),
        "written": written,
        "skipped": skipped,
        "sync": sync_result,
        "search_count": None if search_result is None else search_result.get("count", 0),
        "first_doc": None if search_result is None else ((search_result.get("chunks") or [{}])[0].get("doc_name", "")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed archived ARTEL backend validation reports into LES ARTEL_Index.")
    parser.add_argument("--artel-url", default=os.getenv("ARTEL_BASE_URL", DEFAULT_ARTEL_URL), help="ARTEL backend URL.")
    parser.add_argument("--task-id", default=os.getenv("ARTEL_TASK_ID", ""), help="Optional ARTEL task filter.")
    parser.add_argument("--artel-api-key", default=os.getenv("ARTEL_API_KEY", ""), help="Optional ARTEL backend API key.")
    parser.add_argument("--runtime-root", type=Path, default=Path.cwd(), help="LES runtime root that owns RAG_Content.")
    parser.add_argument("--proxy-url", default=DEFAULT_PROXY_URL, help="LES proxy URL.")
    parser.add_argument("--api-key", default=os.getenv("LES_ADMIN_KEY", ""), help="LES admin API key; localhost trusted access can omit it.")
    parser.add_argument("--limit", type=int, default=0, help="Only process newest N reports from backend list; 0 means all.")
    parser.add_argument("--no-sync", action="store_true", help="Write projections only; do not call LES sync.")
    parser.add_argument("--verify-search", action="store_true", help="Poll /api/search until ARTEL returns at least one chunk.")
    parser.add_argument("--timeout-sec", type=float, default=120.0, help="Search verification timeout.")
    parser.add_argument("--poll-sec", type=float, default=5.0, help="Search verification poll interval.")
    parser.add_argument("--top-k", type=int, default=8, help="Search top_k for verification.")
    args = parser.parse_args()

    result = seed_backend_reports(
        artel_url=args.artel_url,
        task_id=args.task_id,
        artel_api_key=args.artel_api_key,
        runtime_root=args.runtime_root,
        proxy_url=args.proxy_url,
        les_api_key=args.api_key,
        limit=args.limit,
        no_sync=args.no_sync,
        verify_search=args.verify_search,
        timeout_sec=args.timeout_sec,
        poll_sec=args.poll_sec,
        top_k=args.top_k,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not result["skipped"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
