#!/usr/bin/env python3
"""Smoke-test Е.Ж.И.К. IMAP intake through the proxy API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class HttpResult:
    status: int
    body: dict[str, Any] | list[Any] | str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy-url", default=os.getenv("PROXY_URL", "http://127.0.0.1:8050"))
    parser.add_argument("--api-key", default=os.getenv("LES_API_KEY", ""))
    parser.add_argument("--max-messages", type=int, default=5)
    parser.add_argument("--parse", action="store_true", help="Ask importer to parse MAIL_Index after registration")
    parser.add_argument("--no-import", action="store_true", help="Only check /api/mail/status")
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def request_json(
    method: str,
    url: str,
    *,
    api_key: str = "",
    payload: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> HttpResult:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("X-API-Key", api_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return HttpResult(response.status, parse_body(raw))
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        return HttpResult(error.code, parse_body(raw))


def parse_body(raw: str) -> dict[str, Any] | list[Any] | str:
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return raw


def public_result(status: str, checks: list[dict[str, Any]], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "component": "Е.Ж.И.К. IMAP smoke",
        "checks": checks,
        "payload": payload or {},
    }


def main() -> int:
    args = parse_args()
    base = args.proxy_url.rstrip("/")
    checks: list[dict[str, Any]] = []

    status = request_json("GET", f"{base}/api/mail/status", api_key=args.api_key, timeout=args.timeout)
    checks.append({"name": "mail_status", "http": status.status})
    if status.status != 200 or not isinstance(status.body, dict):
        print(json.dumps(public_result("failed", checks, {"mail_status": status.body}), ensure_ascii=False, indent=2))
        return 1

    imap = status.body.get("imap") if isinstance(status.body.get("imap"), dict) else {}
    checks[-1].update(
        {
            "dataset_name": status.body.get("dataset_name"),
            "mail_status": status.body.get("status"),
            "imap_enabled": bool(imap.get("enabled")),
            "host": imap.get("host", ""),
            "folders": imap.get("folders", []),
        }
    )
    if status.body.get("dataset_name") != "MAIL_Index":
        print(json.dumps(public_result("failed", checks, {"reason": "MAIL_Index missing from status"}), ensure_ascii=False, indent=2))
        return 1
    if args.no_import:
        print(json.dumps(public_result("ok", checks, {"mode": "status_only"}), ensure_ascii=False, indent=2))
        return 0
    if not imap.get("enabled"):
        print(json.dumps(public_result("skipped", checks, {"reason": "IMAP credentials are not configured"}), ensure_ascii=False, indent=2))
        return 0

    imported = request_json(
        "POST",
        f"{base}/api/mail/import-imap",
        api_key=args.api_key,
        payload={"max_messages": args.max_messages, "parse": args.parse},
        timeout=args.timeout,
    )
    checks.append({"name": "import_imap", "http": imported.status})
    if imported.status != 200 or not isinstance(imported.body, dict):
        print(json.dumps(public_result("failed", checks, {"import_imap": imported.body}), ensure_ascii=False, indent=2))
        return 1
    checks[-1].update(
        {
            "status": imported.body.get("status"),
            "files": imported.body.get("files", 0),
            "parse_started": imported.body.get("parse_started", False),
            "parse_blocked": imported.body.get("parse_blocked", ""),
        }
    )
    ok = imported.body.get("status") in {"registered", "no_new_mail"}
    print(json.dumps(public_result("ok" if ok else "failed", checks, imported.body), ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
