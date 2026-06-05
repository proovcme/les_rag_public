#!/usr/bin/env python3
"""Run validator-only probes against MLX val-model candidates."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.model_matrix import DEFAULT_MATRIX_PATH, filter_candidates, load_matrix


DEFAULT_CASES_PATH = Path("golden/validator_probe_set.json")


@dataclass(frozen=True)
class ProbeCase:
    id: str
    expected: str
    question: str
    context: str
    answer: str


@dataclass(frozen=True)
class ProbeResult:
    model: str
    case_id: str
    ok: bool
    expected: str
    actual: str
    elapsed: float
    detail: str = ""
    raw: str = ""


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[ProbeCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise ValueError(f"validator probe cases must be a list or object with cases: {path}")
    return [
        ProbeCase(
            id=str(item["id"]),
            expected=str(item["expected"]),
            question=str(item["question"]),
            context=str(item.get("context") or ""),
            answer=str(item["answer"]),
        )
        for item in raw_cases
    ]


def _request(method: str, url: str, payload: dict[str, Any] | None, timeout: float) -> tuple[int, dict[str, Any], float, str]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    started = time.time()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(body or "{}"), time.time() - started, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body or "{}")
        except json.JSONDecodeError:
            parsed = {"detail": body[:500]}
        return exc.code, parsed, time.time() - started, body
    except (OSError, json.JSONDecodeError) as exc:
        return 0, {"detail": str(exc)}, time.time() - started, str(exc)


def switch_val_model(mlx_url: str, model: str, timeout: float) -> tuple[bool, str]:
    status, payload, _, raw = _request(
        "POST",
        f"{mlx_url.rstrip('/')}/api/switch_model",
        {"target": "val", "model": model},
        timeout,
    )
    if status != 200:
        return False, f"switch HTTP {status}: {raw[:240]}"
    return True, str(payload.get("model") or model)


def unload_all(mlx_url: str, timeout: float) -> str:
    status, _, _, raw = _request("POST", f"{mlx_url.rstrip('/')}/api/unload_all", {}, timeout)
    return f"HTTP {status}: {raw[:240]}"


def health(mlx_url: str, timeout: float) -> dict[str, Any]:
    status, payload, _, _ = _request("GET", f"{mlx_url.rstrip('/')}/api/health", None, timeout)
    return payload if status == 200 else {}


def run_case(mlx_url: str, model: str, case: ProbeCase, timeout: float) -> ProbeResult:
    status, payload, elapsed, raw = _request(
        "POST",
        f"{mlx_url.rstrip('/')}/api/validate",
        {
            "question": case.question,
            "context": case.context,
            "answer": case.answer,
        },
        timeout,
    )
    if status != 200:
        return ProbeResult(model, case.id, False, case.expected, "", elapsed, f"HTTP {status}: {raw[:240]}", raw=raw[:1000])
    actual = str(payload.get("status") or "")
    raw_status = str(payload.get("raw") or "")
    return ProbeResult(
        model=model,
        case_id=case.id,
        ok=actual == case.expected,
        expected=case.expected,
        actual=actual,
        elapsed=elapsed,
        detail="passed" if actual == case.expected else f"expected {case.expected}, got {actual}",
        raw=raw_status[:1000],
    )


def candidate_models(args: argparse.Namespace) -> list[str]:
    if args.model:
        return args.model
    candidates = filter_candidates(
        load_matrix(args.matrix),
        role="validator",
        max_disk_gb=args.max_disk_gb,
    )
    return [candidate.id for candidate in candidates if candidate.status != "active_default"]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run validator-only probes against MLX val-model candidates.")
    parser.add_argument("--mlx-url", default="http://127.0.0.1:8080")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX_PATH)
    parser.add_argument("--model", action="append", default=[], help="Explicit model id. Can be repeated.")
    parser.add_argument("--max-disk-gb", type=float, default=2.44)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--switch-timeout", type=float, default=45.0)
    parser.add_argument("--restore-model", default="", help="Restore this val model after the probes.")
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    cases = load_cases(args.cases)
    original_model = args.restore_model or str((health(args.mlx_url, 5).get("val_model") or {}).get("path") or "")
    models = candidate_models(args)
    if not models:
        print("no candidate models", file=sys.stderr)
        return 2

    lines: list[str] = []
    failed = 0
    try:
        for model in models:
            ok, detail = switch_val_model(args.mlx_url, model, args.switch_timeout)
            if not ok:
                result = ProbeResult(model, "__switch__", False, "SWITCHED", "ERROR", 0.0, detail)
                failed += 1
                line = json.dumps(asdict(result), ensure_ascii=False)
                lines.append(line)
                print(line, flush=True)
                continue
            for case in cases:
                result = run_case(args.mlx_url, model, case, args.timeout)
                failed += 0 if result.ok else 1
                line = json.dumps(asdict(result), ensure_ascii=False)
                lines.append(line)
                print(line, flush=True)
            print(f"unload {model}: {unload_all(args.mlx_url, 20)}", file=sys.stderr)
    finally:
        if original_model:
            switch_val_model(args.mlx_url, original_model, args.switch_timeout)
        unload_all(args.mlx_url, 20)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    passed = len(lines) - failed
    print(f"validator probe complete: passed={passed} failed={failed} models={len(models)}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
