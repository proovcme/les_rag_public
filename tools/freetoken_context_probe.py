"""Short live proof for FreeToken prompt+generation KV budgeting.

Builds a synthetic forced tool-call near a requested input-token size using
FreeToken's own count_tokens endpoint, then performs exactly one generation.
It does not touch LES datasets, checkpoints, or the smeta workflow.
"""

from __future__ import annotations

import argparse
import json
import sys
from time import perf_counter
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def _post_json(url: str, payload: dict, *, timeout: float) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {detail}") from error


def _tool_schema() -> dict:
    return {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }


def _anthropic_count_payload(model: str, filler_words: int) -> dict:
    return {
        "model": model,
        "system": "You are testing a bounded tool transport. Preserve the evidence.",
        "messages": [{
            "role": "user",
            "content": ("typed-evidence " * filler_words) + "Call report_probe now.",
        }],
        "tools": [{
            "name": "report_probe",
            "description": "Return the transport probe result.",
            "input_schema": _tool_schema(),
        }],
        "tool_choice": {"type": "tool", "name": "report_probe"},
    }


def _fit_input_tokens(base_url: str, model: str, target: int) -> tuple[int, int]:
    low, high = 1, max(2, target * 2)
    best_words, best_tokens = 1, 0
    while low <= high:
        words = (low + high) // 2
        counted = _post_json(
            f"{base_url}/messages/count_tokens",
            _anthropic_count_payload(model, words),
            timeout=15,
        )
        tokens = int(counted.get("input_tokens") or 0)
        if abs(tokens - target) < abs(best_tokens - target) or best_tokens == 0:
            best_words, best_tokens = words, tokens
        if tokens < target:
            low = words + 1
        elif tokens > target:
            high = words - 1
        else:
            break
    return best_words, best_tokens


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:1919/v1")
    parser.add_argument("--model", default="Qwen3.6-35B-A3B-NVFP4")
    parser.add_argument("--input-tokens", type=int, default=6200)
    parser.add_argument("--max-tokens", type=int, default=1024)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    words, counted_tokens = _fit_input_tokens(
        base_url, args.model, max(256, args.input_tokens)
    )
    user_content = ("typed-evidence " * words) + "Call report_probe now."
    payload = {
        "model": args.model,
        "messages": [
            {
                "role": "system",
                "content": "You are testing a bounded tool transport. Preserve the evidence.",
            },
            {"role": "user", "content": user_content},
        ],
        "tools": [{
            "type": "function",
            "function": {
                "name": "report_probe",
                "description": "Return the transport probe result.",
                "parameters": _tool_schema(),
            },
        }],
        "tool_choice": {
            "type": "function",
            "function": {"name": "report_probe"},
        },
        "parallel_tool_calls": False,
        "temperature": 0.0,
        "max_tokens": max(1, args.max_tokens),
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = perf_counter()
    response = _post_json(
        f"{base_url}/chat/completions", payload, timeout=120
    )
    elapsed = round(perf_counter() - started, 3)
    message = ((response.get("choices") or [{}])[0].get("message") or {})
    calls = message.get("tool_calls") or []
    result = {
        "ok": bool(calls),
        "target_input_tokens": args.input_tokens,
        "counted_input_tokens": counted_tokens,
        "max_tokens": args.max_tokens,
        "elapsed_seconds": elapsed,
        "usage": response.get("usage") or {},
        "tool_name": str((((calls[0] if calls else {}).get("function") or {}).get("name") or "")),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] and result["tool_name"] == "report_probe" else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    raise SystemExit(main())
