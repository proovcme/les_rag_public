"""Ingest ARTEL Revit add-in validation reports into LES as learning cases."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import seed_artel_learning_cases as learning_cases  # noqa: E402


DEFAULT_ARTEL_URL = "http://127.0.0.1:5057"
DEFAULT_PROXY_URL = "http://127.0.0.1:8050"
DEFAULT_TASK_ID = "task_0241"


def load_report(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        value = json.load(fh)
    if not isinstance(value, dict):
        raise ValueError("Validation report JSON root must be an object.")
    return value


def resolve_report_path(pattern: str) -> Path:
    path = Path(pattern).expanduser()
    if any(ch in pattern for ch in "*?["):
        matches = sorted(path.parent.glob(path.name), key=lambda item: item.stat().st_mtime, reverse=True)
        if not matches:
            raise FileNotFoundError(f"No validation report matches: {pattern}")
        return matches[0]
    return path


def _key_id(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    normalized = {_key_id(str(key)): value for key, value in data.items()}
    for key in keys:
        if _key_id(key) in normalized:
            return normalized[_key_id(key)]
    return default


def _as_string(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return [value]
    return []


def _normalize_issue_severity(value: Any) -> str:
    severity = _as_string(value, "info").lower()
    if severity in {"fail", "failed", "failure", "error", "critical", "fatal"}:
        return "error"
    if severity in {"warn", "warning"}:
        return "warning"
    return "info"


def _normalize_report_status(value: Any, issues: list[dict[str, Any]]) -> str:
    status = _as_string(value).lower()
    if status in {"pass", "passed", "ok", "success", "succeeded"}:
        return "pass"
    if status in {"fail", "failed", "failure", "error", "critical", "fatal"}:
        return "fail"
    if status in {"warn", "warning", "partial"}:
        return "warning"
    severities = {issue["severity"] for issue in issues}
    if "error" in severities:
        return "fail"
    if "warning" in severities:
        return "warning"
    return "pass"


def normalize_issue(value: Any, index: int) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {"description": value}
    title = _as_string(_get(data, "title", "name"), f"Validation issue {index}")
    description = _as_string(_get(data, "description", "message", "details"), title)
    return {
        "severity": _normalize_issue_severity(_get(data, "severity", "level", "status")),
        "code": _as_string(_get(data, "code", "id"), f"ARTEL-ISSUE-{index:03d}"),
        "title": title,
        "description": description,
        "revitElementId": _as_string(_get(data, "revitElementId", "revit_element_id", "elementId", "element_id"), ""),
        "suggestedFix": _as_string(_get(data, "suggestedFix", "suggested_fix", "fix", "suggestion"), description),
    }


def normalize_action(value: Any, index: int) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {"message": value}
    return {
        "type": _as_string(_get(data, "type", "kind"), "validation"),
        "target": _as_string(_get(data, "target", "name", "familyName", "family_name"), "Revit family"),
        "status": _as_string(_get(data, "status", "state"), "completed"),
        "message": _as_string(_get(data, "message", "description", "details"), f"Validation action {index}"),
    }


def _unwrap_report(raw: dict[str, Any]) -> dict[str, Any]:
    for key in ("validation_report", "validationReport", "validation", "report"):
        value = _get(raw, key)
        if isinstance(value, dict) and (_get(value, "issues") is not None or _get(value, "status") is not None):
            return value
    return raw


def normalize_validation_report(raw: dict[str, Any]) -> dict[str, Any]:
    report = _unwrap_report(raw)
    issues = [
        normalize_issue(item, index)
        for index, item in enumerate(_as_list(_get(report, "issues", "validationIssues")), start=1)
    ]
    actions = [
        normalize_action(item, index)
        for index, item in enumerate(_as_list(_get(report, "actions", "validationActions")), start=1)
    ]
    status = _normalize_report_status(_get(report, "status", "result", "outcome"), issues)
    family = _get(report, "family", default={})
    family_name = _as_string(_get(family, "family_name", "familyName", "name", "title")) if isinstance(family, dict) else ""
    summary = _as_string(_get(report, "summary", "message", "description"))
    if not summary:
        target = family_name or "Revit family"
        summary = f"{target}: validation {status}; issues={len(issues)}; actions={len(actions)}."
    return {
        "status": status,
        "summary": summary,
        "issues": issues,
        "actions": actions,
    }


def request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    api_key: str = "",
    timeout: float = 30.0,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {exc.code}: {body}") from exc


def submit_validation_report(
    *,
    artel_url: str,
    task_id: str,
    payload: dict[str, Any],
    api_key: str = "",
) -> dict[str, Any]:
    return request_json(
        "POST",
        f"{artel_url.rstrip('/')}/api/revit/tasks/{task_id}/validation-reports",
        payload=payload,
        api_key=api_key,
    )


def load_learning_case_for_report(
    *,
    artel_url: str,
    report_id: str,
    api_key: str = "",
) -> dict[str, Any]:
    return request_json(
        "GET",
        f"{artel_url.rstrip('/')}/api/validation-reports/{report_id}/learning-case",
        api_key=api_key,
    )


def attach_projection_metadata(case: dict[str, Any], *, report_path: Path, raw_report: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(case)
    metadata = dict(enriched.get("projection_metadata") or {})
    metadata.update(
        {
            "projection_source": "revit_addin_validation_report",
            "validation_report_path": str(report_path),
            "validation_report_schema": _as_string(_get(raw_report, "schema"), "unknown"),
        }
    )
    enriched["projection_metadata"] = metadata
    return enriched


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Post an ARTEL Revit validation JSON report and seed the resulting FamilyLearningCase into LES."
    )
    parser.add_argument(
        "--report",
        required=True,
        help="JSON report exported by ARTEL.Revit.FamilyFactory. Quoted glob patterns pick the newest match.",
    )
    parser.add_argument("--artel-url", default=os.getenv("ARTEL_BASE_URL", DEFAULT_ARTEL_URL), help="ARTEL backend URL.")
    parser.add_argument("--task-id", default=os.getenv("ARTEL_TASK_ID", DEFAULT_TASK_ID), help="ARTEL task id.")
    parser.add_argument("--artel-api-key", default=os.getenv("ARTEL_API_KEY", ""), help="Optional ARTEL backend API key.")
    parser.add_argument("--runtime-root", type=Path, default=Path.cwd(), help="LES runtime root that owns RAG_Content.")
    parser.add_argument("--proxy-url", default=DEFAULT_PROXY_URL, help="LES proxy URL.")
    parser.add_argument("--api-key", default=os.getenv("LES_ADMIN_KEY", ""), help="LES admin API key; localhost trusted access can omit it.")
    parser.add_argument("--no-sync", action="store_true", help="Write projection only; do not call LES sync.")
    parser.add_argument("--verify-search", action="store_true", help="Poll /api/search until ARTEL returns at least one chunk.")
    parser.add_argument("--timeout-sec", type=float, default=120.0, help="Search verification timeout.")
    parser.add_argument("--poll-sec", type=float, default=5.0, help="Search verification poll interval.")
    parser.add_argument("--top-k", type=int, default=8, help="Search top_k for verification.")
    args = parser.parse_args()

    report_path = resolve_report_path(args.report)
    print(f"report={report_path}")
    raw_report = load_report(report_path)
    payload = normalize_validation_report(raw_report)
    print(f"normalized_status={payload['status']}")
    print(f"normalized_issues={len(payload['issues'])}")
    print(f"normalized_actions={len(payload['actions'])}")

    created = submit_validation_report(
        artel_url=args.artel_url,
        task_id=args.task_id,
        payload=payload,
        api_key=args.artel_api_key,
    )
    report_id = _as_string(_get(created, "id", "reportId", "report_id"))
    if not report_id:
        raise SystemExit("ARTEL backend did not return report id: " + json.dumps(created, ensure_ascii=False))
    print(f"report_id={report_id}")

    case = load_learning_case_for_report(artel_url=args.artel_url, report_id=report_id, api_key=args.artel_api_key)
    errors = learning_cases.validate_case(case)
    if errors:
        raise SystemExit("Invalid FamilyLearningCase from ARTEL backend: " + "; ".join(errors))

    case = attach_projection_metadata(case, report_path=report_path, raw_report=raw_report)
    written = learning_cases.write_projection(case, args.runtime_root)
    print(f"projection={written}")

    if not args.no_sync:
        sync_result = learning_cases.sync_artel(args.proxy_url, api_key=args.api_key)
        print("sync=" + json.dumps(sync_result, ensure_ascii=False, sort_keys=True))

    if args.verify_search:
        search_result = learning_cases.wait_for_artel_search(
            args.proxy_url,
            learning_cases.build_default_query(case),
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
