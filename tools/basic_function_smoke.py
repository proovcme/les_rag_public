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


DEFAULT_CHAT_TIMEOUT = 90.0


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
        if status == "ok":
            return _r("health_reachable", "P0", "pass", t0, "", ev)
        if status == "degraded":
            return _r("health_reachable", "P0", "warn", t0, "runtime degraded", ev)
        return _r("health_reachable", "P0", "fail", t0, f"runtime status={status!r}", ev)
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


def check_diagnostics(c, base):
    """Diagnostics may require auth, but an exposed error must never pass as healthy."""
    t0 = time.monotonic()
    try:
        resp = c.get(f"{base}/api/diag")
        if resp.status_code in (401, 403):
            return _r("diagnostics_endpoint", "P1", "pass", t0, "честный auth-gate", {"http": resp.status_code})
        if resp.status_code != 200:
            return _r("diagnostics_endpoint", "P1", "fail", t0, f"http={resp.status_code}", {"http": resp.status_code})
        payload = resp.json()
        overall = str(payload.get("overall") or "")
        evidence = {"http": resp.status_code, "overall": overall}
        if overall == "ok":
            return _r("diagnostics_endpoint", "P1", "pass", t0, "", evidence)
        if overall == "warn":
            return _r("diagnostics_endpoint", "P1", "warn", t0, "diagnostics warning", evidence)
        return _r("diagnostics_endpoint", "P1", "fail", t0, f"diagnostics overall={overall!r}", evidence)
    except Exception as e:
        return _r("diagnostics_endpoint", "P1", "fail", t0, f"{type(e).__name__}: {e}")


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


def check_indexing_state(c, base, *, release: bool) -> tuple[dict, bool]:
    """Make an active index build observable without weakening release gates."""
    t0 = time.monotonic()
    try:
        payload = c.get(f"{base}/api/health").json()
        rag = payload.get("rag") if isinstance(payload.get("rag"), dict) else {}
        totals = rag.get("totals") if isinstance(rag.get("totals"), dict) else {}
        pending = int(totals.get("pending_files") or 0)
        active = pending > 0 or any(
            str(item.get("status") or "").upper() in {"PARSING", "QUEUED", "RUNNING"}
            for item in (rag.get("datasets") or []) if isinstance(item, dict)
        )
        evidence = {
            "error_code": "INDEXING_IN_PROGRESS" if active else "",
            "pending_files": pending,
            "rag_status": rag.get("status", ""),
        }
        if not active:
            return _r("indexing_state", "P0", "pass", t0, "", evidence), False
        if release:
            return _r(
                "indexing_state", "P0", "fail", t0,
                "INDEXING_IN_PROGRESS: release smoke требует завершённый индекс", evidence,
            ), True
        return _r(
            "indexing_state", "P0", "warn", t0,
            "INDEXING_IN_PROGRESS: chat-пробы отложены до завершения индексации", evidence,
        ), True
    except Exception as error:
        return _r(
            "indexing_state", "P0", "fail", t0,
            f"{type(error).__name__}: {error}", {"error_code": "INDEXING_STATE_UNAVAILABLE"},
        ), False


def indexing_chat_warning(name: str) -> dict:
    return _r(
        name,
        "P0" if name == "chat_glossary" else "P1",
        "warn",
        time.monotonic(),
        "INDEXING_IN_PROGRESS: проба не выполнялась",
        {"error_code": "INDEXING_IN_PROGRESS"},
    )


def _chat(c, base, question, *, timeout: float):
    resp = c.post(f"{base}/api/chat", json={"question": question}, timeout=timeout)
    return resp


def _has_version_trace(payload: dict) -> bool:
    """Accept the legacy top-level trace and the current response contract."""
    if isinstance(payload.get("version_info"), dict):
        return True
    versions = payload.get("versions")
    return isinstance(versions, dict) and isinstance(versions.get("version_info"), dict)


def check_chat_glossary(c, base, *, timeout: float):
    t0 = time.monotonic()
    try:
        resp = _chat(c, base, "что такое ОЖР", timeout=timeout)
        if resp.status_code == 503:
            return _r("chat_glossary", "P0", "warn", t0, f"memory-guard (транзиент): {resp.json().get('detail','')[:80]}",
                      {"http": 503})
        d = resp.json()
        ans = (d.get("answer") or "").strip()
        status = d.get("crag_status") or d.get("status") or ""
        route = d.get("query_route") if isinstance(d.get("query_route"), dict) else {}
        channel = str(route.get("channel") or "")
        has_version = _has_version_trace(d)
        ev = {"http": resp.status_code, "answer_len": len(ans), "status": status,
              "channel": channel, "version_info": has_version}
        if resp.status_code != 200:
            return _r("chat_glossary", "P0", "fail", t0, f"http={resp.status_code}: {str(d)[:80]}", ev)
        if not ans:
            return _r("chat_glossary", "P0", "fail", t0, "пустой ответ на глоссарный вопрос", ev)
        if channel in {"glossary", "scope_clarification"} or not has_version:
            return _r(
                "chat_glossary",
                "P0",
                "fail",
                t0,
                "professional answer ушёл в code-final route или потерял version_info",
                ev,
            )
        return _r("chat_glossary", "P0", "pass", t0, "", ev)
    except Exception as e:
        return _r("chat_glossary", "P0", "fail", t0, f"{type(e).__name__}: {e}")


def check_chat_project_noscope(c, base, *, timeout: float):
    """Проектный вопрос без scope идёт model-first, но никогда не в glossary."""
    t0 = time.monotonic()
    try:
        resp = _chat(c, base, "расскажи про котельную на лесном 64", timeout=timeout)
        if resp.status_code == 503:
            return _r("chat_project_noscope", "P1", "warn", t0, "memory-guard (транзиент)", {"http": 503})
        d = resp.json()
        ans = (d.get("answer") or "").strip()
        status = d.get("crag_status") or d.get("status") or ""
        route = d.get("query_route") if isinstance(d.get("query_route"), dict) else {}
        channel = str(route.get("channel") or "")
        has_version = _has_version_trace(d)
        ev = {"http": resp.status_code, "answer_len": len(ans), "status": status,
              "channel": channel, "version_info": has_version}
        if resp.status_code != 200:
            return _r("chat_project_noscope", "P1", "fail", t0, f"http={resp.status_code}", ev)
        if channel == "glossary" or not has_version:
            return _r("chat_project_noscope", "P1", "fail", t0, "project query ушёл в glossary или потерял version_info", ev)
        # Ответ модели либо честный MISSING/BLOCKED допустимы; пустота без статуса — нет.
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
    ap.add_argument("--http-timeout", type=float, default=20.0, help="таймаут обычного HTTP check")
    ap.add_argument(
        "--chat-timeout",
        type=float,
        default=DEFAULT_CHAT_TIMEOUT,
        help="отдельный конечный budget одного chat check (калиброван для локального 9B на Mac Mini)",
    )
    args = ap.parse_args()
    if args.http_timeout <= 0 or args.chat_timeout <= 0:
        ap.error("--http-timeout и --chat-timeout должны быть положительными")

    base = args.proxy_url.rstrip("/")
    results = []
    with httpx.Client(timeout=args.http_timeout, follow_redirects=True) as c:
        results.append(check_version(c, base))
        results.append(check_health(c, base))
        results.append(check_simple(c, base, "/api/status", "status_endpoint", "P1"))
        results.append(check_simple(c, base, "/api/metrics", "metrics_endpoint", "P1"))
        results.append(check_diagnostics(c, base))
        results.append(check_scope(c, base))
        indexing_result, indexing_active = check_indexing_state(c, base, release=args.release)
        results.append(indexing_result)
        if indexing_active and not args.release:
            results.append(indexing_chat_warning("chat_glossary"))
            results.append(indexing_chat_warning("chat_project_noscope"))
        else:
            results.append(check_chat_glossary(c, base, timeout=args.chat_timeout))
            results.append(check_chat_project_noscope(c, base, timeout=args.chat_timeout))
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

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    icon = {"pass": "OK", "warn": "WARN", "fail": "FAIL"}
    for x in results:
        print(f"  [{icon.get(x['status'],'?')}] [{x['severity']}] {x['name']:<24} {x['elapsed_ms']:>7.0f}ms  {x['reason']}")
    print(f"[smoke] pass={summary['pass']} warn={summary['warn']} fail={summary['fail']} → {args.json}")

    if p0_fail:
        print(f"[smoke] P0 FAIL: {p0_fail}", file=sys.stderr)
    if p1_fail and args.release:
        print(f"[smoke] P1 FAIL (release): {p1_fail}", file=sys.stderr)
    return compute_exit(results, args.release)


if __name__ == "__main__":
    sys.exit(main())
