#!/usr/bin/env python3
"""Reproducible OpenAI-compatible benchmark for local inference engines.

The tool deliberately knows nothing about LES/RAG.  It talks directly to one
already-running model server, records raw per-request observations, and keeps
OptiQ-specific telemetry (`mtplx_stats`) when the server provides it.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "les_local_inference_benchmark_v1"
SAMPLERS: dict[str, dict[str, Any]] = {
    "greedy": {"temperature": 0.0},
    "production": {"temperature": 0.7, "top_p": 0.8, "top_k": 20},
}

ENGINEERING_PREFIX = " ".join(
    [
        "Проектирование инженерных систем требует проверяемых исходных данных, "
        "явных допущений, ссылок на нормативные источники и отделения модельного "
        "решения от арифметического расчета кодом."
    ]
    * 560
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_norm",
            "description": "Найти карточку нормы по шифру.",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
                "additionalProperties": False,
            },
        },
    }
]


@dataclass(frozen=True)
class Profile:
    name: str
    messages: list[dict[str, Any]]
    max_tokens: int
    tools: list[dict[str, Any]] | None = None
    expected_tool: str | None = None


def _prefix_words(words: int) -> str:
    parts = ENGINEERING_PREFIX.split()
    if words <= len(parts):
        return " ".join(parts[:words])
    repeats = math.ceil(words / len(parts))
    return " ".join((parts * repeats)[:words])


def build_profile(name: str, *, prefix_variant: int = 1) -> Profile:
    if name == "throughput-1041x384":
        return Profile(
            name=name,
            messages=[
                # Calibrated against the pinned Qwen3.5 tokenizer: the complete
                # chat template is exactly 1,041 prompt tokens.
                {"role": "system", "content": _prefix_words(479)},
                {
                    "role": "user",
                    "content": (
                        "Составь подробный русский инженерный регламент ровно из 30 "
                        "нумерованных пунктов: входные данные, проверка источников, расчет, "
                        "контроль единиц, blockers и итоговый evidence. Не завершай раньше."
                    ),
                },
            ],
            max_tokens=384,
        )
    if name == "long-8k":
        return Profile(
            name=name,
            messages=[
                # Calibrated against the pinned Qwen3.5 tokenizer: 8,192 tokens.
                {"role": "system", "content": _prefix_words(3985)},
                {
                    "role": "user",
                    "content": "Дай структурированный аудит исходных данных в 20 пунктах.",
                },
            ],
            max_tokens=256,
        )
    if name == "tool-call":
        return Profile(
            name=name,
            messages=[
                {
                    "role": "user",
                    "content": "Вызови инструмент lookup_norm для нормы ГЭСН 10-01-034-01.",
                }
            ],
            max_tokens=128,
            tools=TOOLS,
            expected_tool="lookup_norm",
        )
    if name == "tool-continuation":
        return Profile(
            name=name,
            messages=[
                {
                    "role": "user",
                    "content": "Найди норму ГЭСН 10-01-034-01 и кратко объясни результат.",
                },
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_benchmark_1",
                            "type": "function",
                            "function": {
                                "name": "lookup_norm",
                                "arguments": '{"code":"ГЭСН 10-01-034-01"}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_benchmark_1",
                    "content": '{"found":true,"unit":"100 м2","source":"ГЭСН-2022"}',
                },
            ],
            max_tokens=128,
        )
    if name == "prefix-cache":
        question = (
            "Перечисли пять обязательных проверок единиц измерения."
            if prefix_variant == 1
            else "Перечисли пять обязательных проверок происхождения чисел."
        )
        return Profile(
            name=name,
            messages=[
                {"role": "system", "content": _prefix_words(3000)},
                {"role": "user", "content": question},
            ],
            max_tokens=96,
        )
    raise ValueError(f"unknown profile: {name}")


def percentile(values: Iterable[float], quantile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _json_request(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer sk-optiq-benchmark"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _stream_request(
    url: str, payload: dict[str, Any], timeout: float
) -> tuple[dict[str, Any], float | None]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer sk-optiq-benchmark"},
        method="POST",
    )
    started = time.perf_counter()
    first_content_at: float | None = None
    final: dict[str, Any] = {}
    content: list[str] = []
    reasoning: list[str] = []
    tool_calls: dict[int, dict[str, Any]] = {}
    finish_reason: str | None = None
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            chunk = json.loads(data)
            final.update({key: value for key, value in chunk.items() if key != "choices"})
            choices = chunk.get("choices") or []
            if choices:
                delta = choices[0].get("delta") or {}
                text = delta.get("content") or ""
                thought = delta.get("reasoning") or delta.get("reasoning_content") or ""
                if text or thought:
                    if first_content_at is None:
                        first_content_at = time.perf_counter() - started
                if text:
                    content.append(text)
                if thought:
                    reasoning.append(thought)
                finish_reason = choices[0].get("finish_reason") or finish_reason
                for call in delta.get("tool_calls") or []:
                    index = int(call.get("index", 0))
                    current = tool_calls.setdefault(
                        index,
                        {"id": call.get("id"), "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    function = call.get("function") or {}
                    current["function"]["name"] += function.get("name") or ""
                    current["function"]["arguments"] += function.get("arguments") or ""
    final["_assembled_message"] = {
        "content": "".join(content),
        "reasoning": "".join(reasoning),
        "tool_calls": [tool_calls[key] for key in sorted(tool_calls)],
    }
    final["choices"] = [{"finish_reason": finish_reason}]
    return final, first_content_at


def _usage_and_stats(response: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    usage = response.get("usage") or {}
    stats = response.get("mtplx_stats") or {}
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens", stats.get("cached_tokens", 0))
    normalized_usage = {
        "prompt_tokens": int(usage.get("prompt_tokens") or stats.get("prompt_tokens") or 0),
        "completion_tokens": int(
            usage.get("completion_tokens") or stats.get("completion_tokens") or 0
        ),
        "cached_tokens": int(cached or 0),
    }
    return normalized_usage, stats


def _telemetry_offset(path: Path | None) -> int | None:
    if path is None:
        return None
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _read_telemetry(path: Path | None, offset: int | None) -> dict[str, Any]:
    if path is None or offset is None or not path.exists():
        return {}
    with path.open("rb") as handle:
        handle.seek(offset)
        lines = [line for line in handle.read().splitlines() if line.strip()]
    if not lines:
        return {}
    return json.loads(lines[-1].decode("utf-8"))


def _message(response: dict[str, Any]) -> dict[str, Any]:
    if "_assembled_message" in response:
        return response["_assembled_message"]
    choices = response.get("choices") or []
    return (choices[0].get("message") or {}) if choices else {}


def _tool_ok(message: dict[str, Any], expected_tool: str | None) -> bool | None:
    if not expected_tool:
        return None
    calls = message.get("tool_calls") or []
    return any((call.get("function") or {}).get("name") == expected_tool for call in calls)


def run_request(
    *,
    base_url: str,
    model: str,
    profile: Profile,
    sampler: str,
    stream: bool,
    timeout: float,
    run_index: int,
    phase: str,
    seed: int | None = 0,
    telemetry_path: Path | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": profile.messages,
        "max_tokens": profile.max_tokens,
        "stream": stream,
        **SAMPLERS[sampler],
    }
    if seed is not None:
        body["seed"] = seed
    if stream:
        body["stream_options"] = {"include_usage": True}
    if profile.tools:
        body["tools"] = profile.tools
        body["tool_choice"] = "auto"
    telemetry_offset = _telemetry_offset(telemetry_path)
    started = time.perf_counter()
    try:
        if stream:
            response, client_ttft = _stream_request(
                f"{base_url.rstrip('/')}/chat/completions", body, timeout
            )
        else:
            response = _json_request(
                f"{base_url.rstrip('/')}/chat/completions", body, timeout
            )
            client_ttft = None
        wall = time.perf_counter() - started
        usage, stats = _usage_and_stats(response)
        sidecar_stats = _read_telemetry(telemetry_path, telemetry_offset)
        stats = {**stats, **sidecar_stats}
        completion = usage["completion_tokens"]
        server_decode = stats.get("decode_tok_s")
        server_ttft = stats.get("ttft_s")
        ttft = client_ttft if client_ttft is not None else server_ttft
        decode_tps = float(server_decode) if server_decode is not None else None
        if decode_tps is None and ttft is not None and wall > float(ttft) and completion:
            decode_tps = completion / (wall - float(ttft))
        accepted = sum(int(value) for value in (stats.get("accepted_by_depth") or []))
        if not accepted:
            accepted = int(stats.get("accepted_drafts") or 0)
        drafted = sum(int(value) for value in (stats.get("drafted_by_depth") or []))
        if not drafted:
            drafted = int(stats.get("drafted_tokens") or 0)
        return {
            "ok": True,
            "profile": profile.name,
            "sampler": sampler,
            "stream": stream,
            "phase": phase,
            "run_index": run_index,
            "wall_s": wall,
            "ttft_s": ttft,
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": completion,
            "cached_tokens": usage["cached_tokens"],
            "prefill_tps": stats.get("prefill_tok_s") or stats.get("prompt_tps"),
            "decode_tps": decode_tps,
            "peak_memory_bytes": stats.get("peak_memory_bytes"),
            "generation_mode": stats.get("generation_mode"),
            "mtp_depth": stats.get("mtp_depth"),
            "drafted_tokens": drafted,
            "accepted_drafts": accepted,
            "mtp_acceptance": (accepted / drafted) if drafted else None,
            "tool_call_ok": _tool_ok(_message(response), profile.expected_tool),
            "finish_reason": ((response.get("choices") or [{}])[0]).get("finish_reason"),
            "sampler_observed": {
                key: stats.get(key) for key in ("temperature", "top_p", "top_k", "min_p")
                if key in stats
            },
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        return {
            "ok": False,
            "profile": profile.name,
            "sampler": sampler,
            "stream": stream,
            "phase": phase,
            "run_index": run_index,
            "wall_s": time.perf_counter() - started,
            "error": f"{type(exc).__name__}: {exc}",
        }


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, bool], list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("phase") != "warm" or not row.get("ok"):
            continue
        key = (row["profile"], row["sampler"], bool(row["stream"]))
        groups.setdefault(key, []).append(row)
    result: list[dict[str, Any]] = []
    for (profile, sampler, stream), values in sorted(groups.items()):
        metric = lambda name: [float(row[name]) for row in values if row.get(name) is not None]
        drafted = sum(int(row.get("drafted_tokens") or 0) for row in values)
        accepted = sum(int(row.get("accepted_drafts") or 0) for row in values)
        result.append(
            {
                "profile": profile,
                "sampler": sampler,
                "stream": stream,
                "runs": len(values),
                "successes": sum(bool(row.get("ok")) for row in values),
                "decode_tps_p50": percentile(metric("decode_tps"), 0.50),
                "decode_tps_p95": percentile(metric("decode_tps"), 0.95),
                "prefill_tps_p50": percentile(metric("prefill_tps"), 0.50),
                "ttft_s_p50": percentile(metric("ttft_s"), 0.50),
                "ttft_s_p95": percentile(metric("ttft_s"), 0.95),
                "wall_s_p50": percentile(metric("wall_s"), 0.50),
                "wall_s_p95": percentile(metric("wall_s"), 0.95),
                "cached_tokens_max": max(metric("cached_tokens"), default=0),
                "mtp_acceptance": (accepted / drafted) if drafted else None,
                "tool_calls_ok": all(
                    row.get("tool_call_ok") is not False for row in values
                ),
            }
        )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18080/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--engine", required=True, help="Label stored in the report")
    parser.add_argument(
        "--profiles",
        nargs="+",
        default=["throughput-1041x384", "long-8k", "tool-call", "tool-continuation"],
        choices=["throughput-1041x384", "long-8k", "tool-call", "tool-continuation", "prefix-cache"],
    )
    parser.add_argument("--samplers", nargs="+", default=["greedy", "production"], choices=SAMPLERS)
    parser.add_argument("--warm-runs", type=int, default=5)
    parser.add_argument("--stream", choices=["both", "yes", "no"], default="both")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument(
        "--omit-seed",
        action="store_true",
        help="Do not send request seed; used to verify that an MTP server forces single-request mode itself",
    )
    parser.add_argument(
        "--telemetry-jsonl",
        type=Path,
        help="Optional JSONL sidecar produced by tools/optiq_mtp_probe_server.py",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    streams = [False, True] if args.stream == "both" else [args.stream == "yes"]
    rows: list[dict[str, Any]] = []
    for profile_name in args.profiles:
        for sampler in args.samplers:
            for stream in streams:
                for index in range(args.warm_runs + 1):
                    variant = 2 if profile_name == "prefix-cache" and index else 1
                    row = run_request(
                        base_url=args.base_url,
                        model=args.model,
                        profile=build_profile(profile_name, prefix_variant=variant),
                        sampler=sampler,
                        stream=stream,
                        timeout=args.timeout,
                        run_index=index,
                        phase="cold" if index == 0 else "warm",
                        seed=None if args.omit_seed else 0,
                        telemetry_path=args.telemetry_jsonl,
                    )
                    rows.append(row)
                    print(json.dumps(row, ensure_ascii=False), flush=True)
    payload = {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "engine": args.engine,
        "model": args.model,
        "base_url": args.base_url,
        "samplers": SAMPLERS,
        "config": {
            "profiles": args.profiles,
            "warm_runs": args.warm_runs,
            "streams": streams,
            "seed": None if args.omit_seed else 0,
            "telemetry_jsonl": str(args.telemetry_jsonl) if args.telemetry_jsonl else None,
        },
        "runs": rows,
        "summary": summarize(rows),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return 0 if all(row.get("ok") for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
