#!/usr/bin/env python3
"""Post-deploy runtime smoke checks for LES.

The checks are intentionally HTTP-level and dependency-free, so the same file can
run against localhost, the VPS reverse proxy, or a temporary tunnel.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable


DEFAULT_PROXY_URL = "http://localhost:8050"
DEFAULT_UI_URL = "http://localhost:8051"
DEFAULT_QDRANT_URL = "http://localhost:6333"


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: str
    elapsed: float

    def json(self) -> dict[str, Any]:
        return json.loads(self.body or "{}")


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    elapsed: float = 0.0


class SmokeClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        api_key: str = "",
        json_body: dict[str, Any] | None = None,
    ) -> HttpResult:
        url = f"{self.base_url}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if api_key:
            headers["X-API-Key"] = api_key

        started = time.time()
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return HttpResult(resp.status, body, time.time() - started)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return HttpResult(exc.code, body, time.time() - started)
        except urllib.error.URLError as exc:
            return HttpResult(0, str(exc.reason), time.time() - started)
        except OSError as exc:
            return HttpResult(0, str(exc), time.time() - started)


def _expect_status(name: str, result: HttpResult, expected: Iterable[int]) -> CheckResult:
    expected_set = set(expected)
    if result.status in expected_set:
        return CheckResult(name, True, f"HTTP {result.status}", result.elapsed)
    return CheckResult(name, False, f"HTTP {result.status}, expected {sorted(expected_set)}: {result.body[:240]}", result.elapsed)


def _json_check(name: str, result: HttpResult, expected: Iterable[int], required_keys: Iterable[str]) -> CheckResult:
    status = _expect_status(name, result, expected)
    if not status.ok:
        return status
    try:
        payload = result.json()
    except json.JSONDecodeError as exc:
        return CheckResult(name, False, f"invalid JSON: {exc}", result.elapsed)

    missing = [key for key in required_keys if key not in payload]
    if missing:
        return CheckResult(name, False, f"missing keys: {', '.join(missing)}", result.elapsed)
    return CheckResult(name, True, f"HTTP {result.status}", result.elapsed)


def _html_check(name: str, url: str, timeout: float) -> CheckResult:
    started = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read(4096).decode("utf-8", errors="replace")
            ok = resp.status == 200 and ("<html" in body.lower() or "<!doctype html" in body.lower())
            detail = "HTTP 200 HTML" if ok else f"HTTP {resp.status}, HTML marker not found"
            return CheckResult(name, ok, detail, time.time() - started)
    except urllib.error.HTTPError as exc:
        return CheckResult(name, False, f"HTTP {exc.code}", time.time() - started)
    except OSError as exc:
        return CheckResult(name, False, str(exc), time.time() - started)


def _question_payload(
    question: str,
    dataset_filter: str = "",
    *,
    semantic_cache_enabled: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"question": question}
    if dataset_filter:
        payload["dataset_filter"] = dataset_filter
    if semantic_cache_enabled is not None:
        payload["semantic_cache_enabled"] = semantic_cache_enabled
    return payload


def run_smoke(args: argparse.Namespace) -> list[CheckResult]:
    proxy = SmokeClient(args.proxy_url, args.timeout)
    qdrant = SmokeClient(args.qdrant_url, args.timeout)
    checks: list[CheckResult] = []

    checks.append(_json_check("qdrant collections", qdrant.request("GET", "/collections"), [200], ["result", "status"]))
    checks.append(_json_check("proxy health", proxy.request("GET", "/api/health"), [200], ["status", "backend"]))
    checks.append(_json_check("runtime status", proxy.request("GET", "/api/status"), [200], ["proxy", "mode"]))
    checks.append(_json_check("metrics", proxy.request("GET", "/api/metrics"), [200], ["system", "pipeline", "rag"]))
    checks.append(_json_check("diagnostics", proxy.request("GET", "/api/diag", api_key=args.admin_key), [200], ["checks"]))
    checks.append(_html_check("ui shell", args.ui_url, args.timeout))

    if args.expect_external_auth:
        checks.append(_expect_status("auth boundary: no-key admin denied", proxy.request("GET", "/api/auth/keys"), [401, 403]))
    else:
        checks.append(CheckResult("auth boundary: no-key admin denied", True, "skipped on trusted/local contour"))

    if args.user_key:
        checks.append(_expect_status("auth boundary: user cannot list keys", proxy.request("GET", "/api/auth/keys", api_key=args.user_key), [403]))
        checks.append(_json_check("user datasets access", proxy.request("GET", "/api/rag/datasets", api_key=args.user_key), [200], []))
    else:
        checks.append(CheckResult("auth boundary: user cannot list keys", True, "skipped: no user key"))
        checks.append(CheckResult("user datasets access", True, "skipped: no user key"))

    if args.admin_key:
        checks.append(_json_check("admin keys access", proxy.request("GET", "/api/auth/keys", api_key=args.admin_key), [200], []))
        checks.append(_json_check("admin sources access", proxy.request("GET", "/api/rag/sources", api_key=args.admin_key), [200], []))
    else:
        checks.append(CheckResult("admin keys access", True, "skipped: no admin key"))
        checks.append(CheckResult("admin sources access", True, "skipped: no admin key"))

    chat_key = args.user_key or args.admin_key
    for index, question in enumerate(args.question, start=1):
        if not chat_key:
            checks.append(CheckResult(f"rag question {index}", False, "no user/admin key supplied"))
            continue
        result = proxy.request(
            "POST",
            "/api/chat",
            api_key=chat_key,
            json_body=_question_payload(question, args.dataset_filter),
        )
        check = _json_check(f"rag question {index}", result, [200], ["answer", "crag_status", "sources"])
        if check.ok:
            payload = result.json()
            status = payload.get("crag_status", "?")
            sources = len(payload.get("sources") or [])
            check = CheckResult(check.name, True, f"HTTP 200 {status}, sources={sources}", result.elapsed)
        checks.append(check)

    return checks


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LES post-deploy runtime smoke checks.")
    parser.add_argument("--proxy-url", default=os.getenv("LES_PROXY_URL", DEFAULT_PROXY_URL))
    parser.add_argument("--ui-url", default=os.getenv("LES_UI_URL", DEFAULT_UI_URL))
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", DEFAULT_QDRANT_URL))
    parser.add_argument("--admin-key", default=os.getenv("LES_ADMIN_KEY", os.getenv("ADMIN_PASSWORD", "")))
    parser.add_argument("--user-key", default=os.getenv("LES_USER_KEY", ""))
    parser.add_argument("--dataset-filter", default=os.getenv("LES_SMOKE_DATASET", ""))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("LES_SMOKE_TIMEOUT", "20")))
    parser.add_argument(
        "--question",
        action="append",
        default=[],
        help="Live RAG question to ask. Repeat for multiple questions.",
    )
    parser.add_argument(
        "--expect-external-auth",
        action="store_true",
        default=os.getenv("LES_EXPECT_EXTERNAL_AUTH", "").lower() in {"1", "true", "yes", "on"},
        help="Expect no-key admin access to be rejected. Use on VPS/public URLs, not trusted localhost.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.proxy_url = args.proxy_url.rstrip("/")
    args.ui_url = args.ui_url.rstrip("/")
    args.qdrant_url = args.qdrant_url.rstrip("/")
    if not urllib.parse.urlparse(args.proxy_url).scheme:
        print(f"Invalid --proxy-url: {args.proxy_url}", file=sys.stderr)
        return 2
    if not urllib.parse.urlparse(args.ui_url).scheme:
        print(f"Invalid --ui-url: {args.ui_url}", file=sys.stderr)
        return 2
    if not urllib.parse.urlparse(args.qdrant_url).scheme:
        print(f"Invalid --qdrant-url: {args.qdrant_url}", file=sys.stderr)
        return 2

    print(f"LES runtime smoke: proxy={args.proxy_url} ui={args.ui_url} qdrant={args.qdrant_url}")
    checks = run_smoke(args)
    failed = 0
    for check in checks:
        mark = "OK" if check.ok else "FAIL"
        elapsed = f"{check.elapsed:.2f}s" if check.elapsed else "-"
        print(f"[{mark:4}] {check.name:38} {elapsed:>7}  {check.detail}")
        failed += 0 if check.ok else 1

    if failed:
        print(f"\nSmoke failed: {failed}/{len(checks)} checks failed.", file=sys.stderr)
        return 1
    print(f"\nSmoke passed: {len(checks)} checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
