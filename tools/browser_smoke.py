#!/usr/bin/env python3
"""Browser-level smoke checks for Sovushka UI.

Requires Playwright only when this smoke is run:
    uv run --with playwright python tools/browser_smoke.py --help
    uv run --with playwright python -m playwright install chromium
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from typing import Any


DEFAULT_UI_URL = "http://localhost:8051"

ADMIN_TABS = ("ОБЗОР", "С.А.М.О.В.А.Р.", "П.Р.О.Р.А.Б.", "ГРАФ", "ДИАГН", "В.О.Л.К.")
USER_TABS = ("AI ЧАТ", "ИСТОРИЯ")
LOGIN_MARKERS = ("В.О.Л.К.", "Ключ доступа", "ВОЙТИ В СИСТЕМУ")


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    elapsed: float = 0.0


def _text_selector(text: str) -> str:
    return f"text={text}"


def _missing_playwright_message(exc: Exception) -> str:
    return (
        f"Playwright is not available: {exc}. "
        "Run: uv run --with playwright python tools/browser_smoke.py ..."
    )


def _visible_texts(page: Any, texts: tuple[str, ...], timeout_ms: int) -> list[str]:
    visible = []
    for text in texts:
        try:
            page.wait_for_selector(_text_selector(text), timeout=timeout_ms)
            visible.append(text)
        except Exception:
            pass
    return visible


def _assert_visible(page: Any, name: str, texts: tuple[str, ...], timeout_ms: int) -> CheckResult:
    started = time.time()
    visible = _visible_texts(page, texts, timeout_ms)
    missing = [text for text in texts if text not in visible]
    if missing:
        return CheckResult(name, False, f"missing visible text: {', '.join(missing)}", time.time() - started)
    return CheckResult(name, True, f"visible: {', '.join(texts)}", time.time() - started)


def _assert_absent(page: Any, name: str, texts: tuple[str, ...]) -> CheckResult:
    started = time.time()
    present = []
    for text in texts:
        try:
            if page.locator(_text_selector(text)).count() > 0:
                present.append(text)
        except Exception:
            present.append(text)
    if present:
        return CheckResult(name, False, f"unexpected text present: {', '.join(present)}", time.time() - started)
    return CheckResult(name, True, "admin-only text absent", time.time() - started)


def _login(page: Any, ui_url: str, key: str, timeout_ms: int) -> CheckResult:
    started = time.time()
    page.goto(ui_url, wait_until="domcontentloaded", timeout=timeout_ms)
    login_check = _assert_visible(page, "login page", LOGIN_MARKERS, timeout_ms)
    if not login_check.ok:
        return login_check
    page.fill("#volk-key", key, timeout=timeout_ms)
    page.click("#volk-btn", timeout=timeout_ms)
    try:
        page.wait_for_selector(_text_selector("AI ЧАТ"), timeout=timeout_ms)
    except Exception as exc:
        return CheckResult("login", False, f"AI ЧАТ did not appear after login: {exc}", time.time() - started)
    return CheckResult("login", True, "entered UI", time.time() - started)


def _ask_question(page: Any, question: str, timeout_ms: int) -> CheckResult:
    started = time.time()
    try:
        page.click(_text_selector("AI ЧАТ"), timeout=timeout_ms)
        before = page.locator(".chat-msg-ai").count()
        page.fill("textarea[placeholder^='Запрос по нормативам']", question, timeout=timeout_ms)
        page.click(_text_selector("ОТПРАВИТЬ"), timeout=timeout_ms)
        page.wait_for_function(
            """before => document.querySelectorAll('.chat-msg-ai:not(.typing)').length > before""",
            arg=before,
            timeout=max(timeout_ms, 120_000),
        )
    except Exception as exc:
        return CheckResult("ui chat question", False, str(exc), time.time() - started)
    return CheckResult("ui chat question", True, "answer block appeared", time.time() - started)


def _admin_scenario(context: Any, args: argparse.Namespace) -> list[CheckResult]:
    page = context.new_page()
    results: list[CheckResult] = []
    timeout_ms = int(args.timeout * 1000)

    if args.trusted_local:
        started = time.time()
        page.goto(args.ui_url, wait_until="domcontentloaded", timeout=timeout_ms)
        results.append(CheckResult("trusted local entry", True, page.url, time.time() - started))
    else:
        results.append(_login(page, args.ui_url, args.admin_key, timeout_ms))

    if results[-1].ok:
        results.append(_assert_visible(page, "admin tabs", ADMIN_TABS + USER_TABS, timeout_ms))
        if args.question:
            results.append(_ask_question(page, args.question, timeout_ms))
    page.close()
    return results


def _user_scenario(context: Any, args: argparse.Namespace) -> list[CheckResult]:
    page = context.new_page()
    timeout_ms = int(args.timeout * 1000)
    results = [_login(page, args.ui_url, args.user_key, timeout_ms)]
    if results[-1].ok:
        results.append(_assert_visible(page, "user tabs", USER_TABS, timeout_ms))
        results.append(_assert_absent(page, "user cannot see admin tabs", ADMIN_TABS))
        if args.question:
            results.append(_ask_question(page, args.question, timeout_ms))
    page.close()
    return results


def run_smoke(args: argparse.Namespace) -> list[CheckResult]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return [CheckResult("playwright import", False, _missing_playwright_message(exc))]

    results: list[CheckResult] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.show)
        try:
            admin_context = browser.new_context(ignore_https_errors=args.ignore_https_errors)
            results.extend(_admin_scenario(admin_context, args))
            admin_context.close()

            if args.user_key and not args.trusted_local:
                user_context = browser.new_context(ignore_https_errors=args.ignore_https_errors)
                results.extend(_user_scenario(user_context, args))
                user_context.close()
            elif args.trusted_local:
                results.append(CheckResult("user scenario", True, "skipped on trusted-local contour"))
            else:
                results.append(CheckResult("user scenario", True, "skipped: no user key"))
        finally:
            browser.close()
    return results


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run browser-level Sovushka smoke checks.")
    parser.add_argument("--ui-url", default=os.getenv("LES_UI_URL", DEFAULT_UI_URL))
    parser.add_argument("--admin-key", default=os.getenv("LES_ADMIN_KEY", os.getenv("ADMIN_PASSWORD", "")))
    parser.add_argument("--user-key", default=os.getenv("LES_USER_KEY", ""))
    parser.add_argument("--question", default=os.getenv("LES_BROWSER_SMOKE_QUESTION", ""))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("LES_BROWSER_SMOKE_TIMEOUT", "20")))
    parser.add_argument("--trusted-local", action="store_true", help="Skip login and verify trusted localhost/private LAN admin shell.")
    parser.add_argument("--show", action="store_true", help="Run browser headed.")
    parser.add_argument("--ignore-https-errors", action="store_true", default=True)
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> str:
    if not args.ui_url.startswith(("http://", "https://")):
        return f"Invalid --ui-url: {args.ui_url}"
    if not args.trusted_local and not args.admin_key:
        return "Provide --admin-key or set LES_ADMIN_KEY/ADMIN_PASSWORD."
    return ""


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.ui_url = args.ui_url.rstrip("/")
    error = validate_args(args)
    if error:
        print(error, file=sys.stderr)
        return 2

    print(f"LES browser smoke: ui={args.ui_url}")
    results = run_smoke(args)
    failed = 0
    for result in results:
        mark = "OK" if result.ok else "FAIL"
        elapsed = f"{result.elapsed:.2f}s" if result.elapsed else "-"
        print(f"[{mark:4}] {result.name:32} {elapsed:>7}  {result.detail}")
        failed += 0 if result.ok else 1

    if failed:
        print(f"\nBrowser smoke failed: {failed}/{len(results)} checks failed.", file=sys.stderr)
        return 1
    print(f"\nBrowser smoke passed: {len(results)} checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
