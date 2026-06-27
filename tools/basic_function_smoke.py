#!/usr/bin/env python3
"""basic_function_smoke — L1 HTTP-smoke базовых функций ЛЕС против живого runtime.

Закрывает класс «unit-тесты зелёные, а руками базовая функция не работает» (docs/BASIC_FUNCTIONS_AUTOTEST_PLAN.md).
НЕ браузерный (L2 — отдельный browser_smoke). Проверяет минимальные пользовательские сценарии по HTTP:
версия видна, health честен, scope доступен, чат отвечает или честно BLOCKED, diagnostics не маскирует FAIL.

  uv run python tools/basic_function_smoke.py
  uv run python tools/basic_function_smoke.py --proxy-url http://127.0.0.1:8050 --release

Каждый кейс → {name,status,severity,elapsed_ms,evidence,reason}. P0 fail → exit 1. P1 fail → exit 1 при --release.
Транзиентный memory-guard на чате (503) = WARN (честный отказ), не FAIL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx


def _r(name, severity, status, t0, reason="", evidence=None):
    return {"name": name, "status": status, "severity": severity,
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
            "evidence": evidence or {}, "reason": reason}


def check_version(c, base):
    t0 = time.monotonic()
    try:
        d = c.get(f"{base}/api/version").json()
        need = ("app_version", "harness_version", "deployed_commit", "runtime_alignment")
        missing = [k for k in need if not d.get(k)]
        ev = {"app": d.get("app_version"), "harness": d.get("harness_version"),
              "commit": d.get("deployed_commit"), "alignment": d.get("runtime_alignment")}
        if missing:
            return _r("version_visible", "P0", "fail", t0, f"нет полей: {missing}", ev)
        return _r("version_visible", "P0", "pass", t0, "", ev)
    except Exception as e:
        return _r("version_visible", "P0", "fail", t0, f"{type(e).__name__}: {e}")


def check_health(c, base):
    t0 = time.monotonic()
    try:
        resp = c.get(f"{base}/api/health")
        d = resp.json()
        status = d.get("status", "")
        ev = {"http": resp.status_code, "status": status, "backend": d.get("backend")}
        if resp.status_code != 200 or not status:
            return _r("health_reachable", "P0", "fail", t0, f"http={resp.status_code} status={status!r}", ev)
        return _r("health_reachable", "P0", "pass", t0, "", ev)
    except Exception as e:
        return _r("health_reachable", "P0", "fail", t0, f"{type(e).__name__}: {e}")


def check_simple(c, base, path, name, severity):
    t0 = time.monotonic()
    try:
        resp = c.get(f"{base}{path}")
        # 401/403 на admin-эндпоинте = честный auth-gate, не падение
        if resp.status_code in (401, 403):
            return _r(name, severity, "pass", t0, "честный auth-gate", {"http": resp.status_code})
        if resp.status_code != 200:
            return _r(name, severity, "fail", t0, f"http={resp.status_code}", {"http": resp.status_code})
        return _r(name, severity, "pass", t0, "", {"http": resp.status_code})
    except Exception as e:
        return _r(name, severity, "fail", t0, f"{type(e).__name__}: {e}")


def check_scope(c, base):
    t0 = time.monotonic()
    try:
        d = c.get(f"{base}/api/scope/options").json()
        np_, nd = len(d.get("projects", [])), len(d.get("datasets", []))
        ev = {"projects": np_, "datasets": nd}
        if np_ == 0 and nd == 0:
            return _r("scope_options", "P0", "warn", t0, "пусто: ни проектов, ни датасетов", ev)
        return _r("scope_options", "P0", "pass", t0, "", ev)
    except Exception as e:
        return _r("scope_options", "P0", "fail", t0, f"{type(e).__name__}: {e}")


def _chat(c, base, question):
    resp = c.post(f"{base}/api/chat", json={"question": question})
    return resp


def check_chat_glossary(c, base):
    t0 = time.monotonic()
    try:
        resp = _chat(c, base, "что такое ОЖР")
        if resp.status_code == 503:
            return _r("chat_glossary", "P0", "warn", t0, f"memory-guard (транзиент): {resp.json().get('detail','')[:80]}",
                      {"http": 503})
        d = resp.json()
        ans = (d.get("answer") or "").strip()
        status = d.get("crag_status") or d.get("status") or ""
        ev = {"http": resp.status_code, "answer_len": len(ans), "status": status}
        if resp.status_code != 200:
            return _r("chat_glossary", "P0", "fail", t0, f"http={resp.status_code}: {str(d)[:80]}", ev)
        if not ans:
            return _r("chat_glossary", "P0", "fail", t0, "пустой ответ на глоссарный вопрос", ev)
        return _r("chat_glossary", "P0", "pass", t0, "", ev)
    except Exception as e:
        return _r("chat_glossary", "P0", "fail", t0, f"{type(e).__name__}: {e}")


def check_chat_project_noscope(c, base):
    """Проектный вопрос без scope → ответ ИЛИ честный clarification/MISSING, не падение."""
    t0 = time.monotonic()
    try:
        resp = _chat(c, base, "расскажи про котельную на лесном 64")
        if resp.status_code == 503:
            return _r("chat_project_noscope", "P1", "warn", t0, "memory-guard (транзиент)", {"http": 503})
        d = resp.json()
        ans = (d.get("answer") or "").strip()
        status = d.get("crag_status") or d.get("status") or ""
        ev = {"http": resp.status_code, "answer_len": len(ans), "status": status}
        if resp.status_code != 200:
            return _r("chat_project_noscope", "P1", "fail", t0, f"http={resp.status_code}", ev)
        # любой структурный ответ (answer/clarification/MISSING/BLOCKED) = pass; пустота = fail
        if not ans and status not in ("MISSING", "BLOCKED", "NO_DATA", "NEEDS_CLARIFICATION"):
            return _r("chat_project_noscope", "P1", "fail", t0, "ни ответа, ни честного MISSING/clarification", ev)
        return _r("chat_project_noscope", "P1", "pass", t0, "", ev)
    except Exception as e:
        return _r("chat_project_noscope", "P1", "fail", t0, f"{type(e).__name__}: {e}")


def failures(results, severity):
    """Имена кейсов с status==fail заданной severity — для критериев exit и юнит-теста."""
    return [x["name"] for x in results if x.get("status") == "fail" and x.get("severity") == severity]


def compute_exit(results, release=False) -> int:
    """P0 fail → 1. P1 fail → 1 только при release. Иначе 0 (warn/skip не валят)."""
    if failures(results, "P0"):
        return 1
    if release and failures(results, "P1"):
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="L1 HTTP-smoke базовых функций ЛЕС")
    ap.add_argument("--proxy-url", default="http://127.0.0.1:8050")
    ap.add_argument("--ui-url", default="http://127.0.0.1:8051")
    ap.add_argument("--json", default="artifacts/basic_function_smoke.json")
    ap.add_argument("--release", action="store_true", help="P1 fail → exit 1 (перед релизом)")
    args = ap.parse_args()

    base = args.proxy_url.rstrip("/")
    results = []
    with httpx.Client(timeout=120.0, follow_redirects=True) as c:
        results.append(check_version(c, base))
        results.append(check_health(c, base))
        results.append(check_simple(c, base, "/api/status", "status_endpoint", "P1"))
        results.append(check_simple(c, base, "/api/metrics", "metrics_endpoint", "P1"))
        results.append(check_simple(c, base, "/api/diag", "diagnostics_endpoint", "P1"))
        results.append(check_scope(c, base))
        results.append(check_chat_glossary(c, base))
        results.append(check_chat_project_noscope(c, base))
        # UI достижим
        t0 = time.monotonic()
        try:
            ui = httpx.get(args.ui_url.rstrip("/") + "/", timeout=20.0, follow_redirects=False)
            ok = ui.status_code in (200, 307, 302)
            results.append(_r("ui_reachable", "P0", "pass" if ok else "fail", t0,
                              "" if ok else f"http={ui.status_code}", {"http": ui.status_code}))
        except Exception as e:
            results.append(_r("ui_reachable", "P0", "fail", t0, f"{type(e).__name__}: {e}"))

    summary = {"total": len(results),
               "pass": sum(1 for x in results if x["status"] == "pass"),
               "warn": sum(1 for x in results if x["status"] == "warn"),
               "fail": sum(1 for x in results if x["status"] == "fail")}
    p0_fail = failures(results, "P0")
    p1_fail = failures(results, "P1")
    payload = {"summary": summary, "results": results, "p0_fail": p0_fail, "p1_fail": p1_fail}

    try:
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[smoke] WARN: не записал artifact {args.json}: {e}", file=sys.stderr)

    icon = {"pass": "✓", "warn": "⚠", "fail": "✗"}
    for x in results:
        print(f"  {icon.get(x['status'],'?')} [{x['severity']}] {x['name']:<24} {x['elapsed_ms']:>7.0f}ms  {x['reason']}")
    print(f"[smoke] pass={summary['pass']} warn={summary['warn']} fail={summary['fail']} → {args.json}")

    if p0_fail:
        print(f"[smoke] P0 FAIL: {p0_fail}", file=sys.stderr)
    if p1_fail and args.release:
        print(f"[smoke] P1 FAIL (release): {p1_fail}", file=sys.stderr)
    return compute_exit(results, args.release)


if __name__ == "__main__":
    sys.exit(main())
