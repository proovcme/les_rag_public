#!/usr/bin/env python3
"""Desktop/mobile layout smoke for the critical Sovushka routes."""

from __future__ import annotations

import argparse
import json
import sys


def _route_result(page, url: str, width: int, height: int) -> dict:
    page.set_viewport_size({"width": width, "height": height})
    response = page.goto(url, wait_until="networkidle", timeout=30_000)
    page.wait_for_timeout(500)
    metrics = page.evaluate(
        """() => {
          const root = document.documentElement;
          const buttons = [...document.querySelectorAll('button, a, input, textarea')];
          const clipped = buttons.filter((el) => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 &&
              (r.right > innerWidth + 1 || r.left < -1);
          });
          const focusable = buttons.find((el) => !el.disabled && el.offsetParent !== null);
          let focusVisible = false;
          if (focusable) {
            focusable.focus();
            const style = getComputedStyle(focusable);
            focusVisible = style.outlineStyle !== 'none' || style.boxShadow !== 'none';
          }
          return {
            overflow_x: root.scrollWidth - root.clientWidth,
            clipped_actions: clipped.length,
            clipped_action_labels: clipped.slice(0, 8).map((el) => ({
              text: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 80),
              class_name: el.className,
            })),
            focus_visible: focusVisible,
            body_text: (document.body.innerText || '').slice(0, 4000),
          };
        }"""
    )
    return {
        "url": page.url,
        "http_status": response.status if response else 0,
        "viewport": f"{width}x{height}",
        **metrics,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ui-url", default="http://127.0.0.1:8051")
    args = parser.parse_args(argv)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"Playwright unavailable: {exc}", file=sys.stderr)
        return 2

    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            for path in ("/", "/classic", "/les/classic"):
                for width, height in ((1440, 900), (390, 844)):
                    result = _route_result(
                        page, args.ui_url.rstrip("/") + path, width, height
                    )
                    result["ok"] = (
                        result["http_status"] == 200
                        and result["overflow_x"] <= 1
                        and result["clipped_actions"] == 0
                        and result["focus_visible"]
                        and "Internal Server Error" not in result["body_text"]
                    )
                    results.append(result)
        finally:
            browser.close()
    report = {"schema": "les.sovushka-browser-smoke.v1", "results": results}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
