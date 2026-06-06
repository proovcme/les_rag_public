"""Seed public-safe ARTEL FamilyLearningCase projections into LES."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE = ROOT / "examples" / "artel" / "family_learning_case.metal_cabinet.json"
DEFAULT_PROXY_URL = "http://127.0.0.1:8050"
SCHEMA_VERSION = "artel.family_learning_case.v1"


def load_case(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_case_url(url: str, api_key: str = "") -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {url} failed: HTTP {exc.code}: {body}") from exc


def validate_case(case: dict[str, Any]) -> list[str]:
    required = [
        "schema_version",
        "case_id",
        "product",
        "task",
        "specification",
        "parameter_profile",
        "validation_report",
        "catalog_card",
        "acceptance",
    ]
    errors: list[str] = []
    for key in required:
        if key not in case:
            errors.append(f"missing required field: {key}")
    if case.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if case.get("product") != "ARTEL":
        errors.append("product must be ARTEL")
    task = case.get("task") or {}
    for key in ("title", "family_category", "family_name", "goal"):
        if not task.get(key):
            errors.append(f"task.{key} is required")
    return errors


def _as_lines(values: Any) -> list[str]:
    if not values:
        return []
    if isinstance(values, list):
        return [str(value).strip() for value in values if str(value).strip()]
    return [str(values).strip()]


def _bullet_lines(values: Any) -> str:
    lines = _as_lines(values)
    return "\n".join(f"- {line}" for line in lines) if lines else "- not specified"


def render_learning_case_markdown(case: dict[str, Any]) -> str:
    errors = validate_case(case)
    if errors:
        raise ValueError("; ".join(errors))

    task = case["task"]
    spec = case["specification"]
    profile = case["parameter_profile"]
    validation = case["validation_report"]
    catalog = case["catalog_card"]
    acceptance = case["acceptance"]

    parameter_lines = []
    for parameter in spec.get("parameters") or []:
        name = parameter.get("name", "")
        value = parameter.get("value_or_rule", "")
        group = parameter.get("group", "")
        suffix = f" [{group}]" if group else ""
        parameter_lines.append(f"{name}: {value}{suffix}".strip())

    source_lines = []
    for source in case.get("source_summaries") or []:
        kind = source.get("kind", "source")
        summary = source.get("summary", "")
        if summary:
            source_lines.append(f"{kind}: {summary}")

    sections = [
        "# ARTEL FamilyLearningCase",
        "",
        f"Case ID: {case['case_id']}",
        "Product: ARTEL",
        f"Visibility: {case.get('visibility', 'public_demo')}",
        "",
        "## Task",
        f"Title: {task['title']}",
        f"Family category: {task['family_category']}",
        f"Family name: {task['family_name']}",
        f"Goal: {task['goal']}",
        "Constraints:",
        _bullet_lines(task.get("constraints")),
        "",
        "## Source Summaries",
        _bullet_lines(source_lines),
        "",
        "## Approved Specification",
        "Types:",
        _bullet_lines(spec.get("types")),
        f"Geometry: {spec.get('geometry', '')}",
        "Materials:",
        _bullet_lines(spec.get("materials")),
        "Parameters:",
        _bullet_lines(parameter_lines),
        "",
        "## Parameter Profile",
        f"FOP profile: {profile.get('fop_profile', '')}",
        "Required shared parameters:",
        _bullet_lines(profile.get("required_shared_parameters")),
        "",
        "## Validation Report",
        f"Status: {validation.get('status', '')}",
        "Checks:",
        _bullet_lines(validation.get("checks")),
        "Known failures:",
        _bullet_lines(validation.get("known_failures")),
        "Fixes:",
        _bullet_lines(validation.get("fixes")),
        "",
        "## Catalog Card",
        f"Display name: {catalog.get('display_name', '')}",
        f"Category: {catalog.get('category', '')}",
        "Tags:",
        _bullet_lines(catalog.get("tags")),
        "Search terms:",
        _bullet_lines(catalog.get("search_terms")),
        "",
        "## Acceptance",
        f"Outcome: {acceptance.get('outcome', '')}",
        f"Accepted by role: {acceptance.get('accepted_by_role', '')}",
        f"Notes: {acceptance.get('notes', '')}",
        "",
        "## Retrieval Hints",
        (
            "ARTEL RFA Revit family catalog validation FOP shared parameters "
            "ADSK_Наименование ADSK_КодИзделия FamilyLearningCase"
        ),
        "",
    ]
    return "\n".join(sections)


def projection_path(case: dict[str, Any], runtime_root: Path) -> Path:
    case_id = str(case["case_id"])
    return runtime_root / "RAG_Content" / "ARTEL" / "family_learning_cases" / f"{case_id}.md"


def write_projection(case: dict[str, Any], runtime_root: Path) -> Path:
    target = projection_path(case, runtime_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_learning_case_markdown(case), encoding="utf-8")
    return target


def _request_json(method: str, url: str, payload: dict[str, Any] | None = None, api_key: str = "") -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {exc.code}: {body}") from exc


def sync_artel(proxy_url: str, api_key: str = "") -> dict[str, Any]:
    return _request_json("POST", f"{proxy_url.rstrip('/')}/api/rag/sync/ARTEL", api_key=api_key)


def search_artel(proxy_url: str, query: str, top_k: int, api_key: str = "") -> dict[str, Any]:
    return _request_json(
        "POST",
        f"{proxy_url.rstrip('/')}/api/search",
        {
            "query": query,
            "dataset_filter": "ARTEL",
            "top_k": top_k,
            "include_trace": True,
        },
        api_key=api_key,
    )


def wait_for_artel_search(
    proxy_url: str,
    query: str,
    *,
    top_k: int,
    timeout_sec: float,
    poll_sec: float,
    api_key: str = "",
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    last: dict[str, Any] = {}
    while time.monotonic() <= deadline:
        last = search_artel(proxy_url, query, top_k, api_key=api_key)
        if int(last.get("count") or 0) > 0:
            return last
        time.sleep(poll_sec)
    raise RuntimeError(f"ARTEL search stayed empty after {timeout_sec:.0f}s: {last}")


def build_default_query(case: dict[str, Any]) -> str:
    task = case["task"]
    catalog = case["catalog_card"]
    return " ".join(
        [
            "Найди похожий FamilyLearningCase для Revit RFA",
            task["family_name"],
            task["family_category"],
            catalog["display_name"],
            "ADSK_Наименование validation FOP",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed ARTEL FamilyLearningCase into LES ARTEL_Index.")
    parser.add_argument("--case", type=Path, default=DEFAULT_CASE, help="FamilyLearningCase JSON path.")
    parser.add_argument("--case-url", help="FamilyLearningCase JSON URL, for example ARTEL /api/tasks/{taskId}/learning-case.")
    parser.add_argument("--case-api-key", default=os.getenv("ARTEL_API_KEY", ""), help="Optional API key for --case-url.")
    parser.add_argument("--runtime-root", type=Path, default=Path.cwd(), help="LES runtime root that owns RAG_Content.")
    parser.add_argument("--proxy-url", default=DEFAULT_PROXY_URL, help="LES proxy URL.")
    parser.add_argument("--api-key", default=os.getenv("LES_ADMIN_KEY", ""), help="LES admin API key; localhost trusted access can omit it.")
    parser.add_argument("--no-sync", action="store_true", help="Only write the projection file; do not call LES sync.")
    parser.add_argument("--verify-search", action="store_true", help="Poll /api/search until ARTEL returns at least one chunk.")
    parser.add_argument("--timeout-sec", type=float, default=120.0, help="Search verification timeout.")
    parser.add_argument("--poll-sec", type=float, default=5.0, help="Search verification poll interval.")
    parser.add_argument("--top-k", type=int, default=8, help="Search top_k for verification.")
    args = parser.parse_args()

    case = load_case_url(args.case_url, api_key=args.case_api_key) if args.case_url else load_case(args.case)
    errors = validate_case(case)
    if errors:
        raise SystemExit("Invalid FamilyLearningCase: " + "; ".join(errors))

    written = write_projection(case, args.runtime_root)
    print(f"projection={written}")

    if not args.no_sync:
        sync_result = sync_artel(args.proxy_url, api_key=args.api_key)
        print("sync=" + json.dumps(sync_result, ensure_ascii=False, sort_keys=True))

    if args.verify_search:
        search_result = wait_for_artel_search(
            args.proxy_url,
            build_default_query(case),
            top_k=args.top_k,
            timeout_sec=args.timeout_sec,
            poll_sec=args.poll_sec,
            api_key=args.api_key,
        )
        print("search_count=" + str(search_result.get("count", 0)))
        first = (search_result.get("chunks") or [{}])[0]
        print("first_doc=" + str(first.get("doc_name", "")))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
