"""Short live proof that FreeToken thinking can use LES norm tools.

The probe asks one estimating question and requires the same model to perform
``search_norm`` followed by ``read_norm`` before answering. It is read-only: no
attachment, checkpoint, estimate artifact, dataset mutation, or reindex.
"""

from __future__ import annotations

import argparse
import json
import sys
from time import perf_counter
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen


PostJson = Callable[..., dict[str, Any]]
ExecuteTool = Callable[[str, dict[str, Any]], dict[str, Any]]


def _post_json(url: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {detail}") from error


def _tool_specs() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "search_norm",
                "description": "Search the current LES FSNB norm corpus. Returns candidates, not a decision.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "work_description": {"type": "string"},
                        "unit_hint": {"type": "string"},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 6},
                    },
                    "required": ["work_description"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_norm",
                "description": "Open one exact norm card returned by search_norm.",
                "parameters": {
                    "type": "object",
                    "properties": {"norm_code": {"type": "string"}},
                    "required": ["norm_code"],
                    "additionalProperties": False,
                },
            },
        },
    ]


def _compact_search_result(result: dict[str, Any]) -> dict[str, Any]:
    candidates = []
    for candidate in list(result.get("candidates") or [])[:6]:
        profile = candidate.get("norm_profile") if isinstance(candidate.get("norm_profile"), dict) else {}
        candidates.append({
            "norm_code": candidate.get("norm_code"),
            "title": candidate.get("title"),
            "measure_unit": candidate.get("measure_unit"),
            "unit_compatible": candidate.get("unit_compatible"),
            "work_steps": list(profile.get("work_steps") or [])[:12],
            "source_ref": profile.get("source_ref"),
        })
    return {
        "status": result.get("status"),
        "source_integrity": ((result.get("norm_store") or {}).get("source_integrity") or {}).get("status"),
        "backend": (result.get("norm_store") or {}).get("backend"),
        "candidates": candidates,
    }


def _compact_norm_card(card: dict[str, Any] | None, code: str) -> dict[str, Any]:
    if not card:
        return {"status": "not_found", "norm_code": code}
    return {
        "status": "ok",
        "norm_code": card.get("norm_code") or card.get("code") or code,
        "title": card.get("title") or card.get("name"),
        "measure_unit": card.get("measure_unit") or card.get("unit"),
        "work_steps": list(card.get("work_steps") or [])[:20],
        "resources": list(card.get("resources") or [])[:20],
        "source_ref": card.get("source_ref"),
    }


def _execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "search_norm":
        from proxy.services.estimate_harness_service import search_norm

        result = search_norm(
            str(arguments.get("work_description") or ""),
            unit_hint=str(arguments.get("unit_hint") or ""),
            top_k=min(6, max(1, int(arguments.get("top_k") or 4))),
            rerank=False,
        )
        return _compact_search_result(result)
    if name == "read_norm":
        from proxy.services.gesn_service import get_norm

        code = str(arguments.get("norm_code") or "").strip()
        return _compact_norm_card(get_norm(code, strict_family=True), code)
    return {"status": "error", "error": f"unsupported tool: {name}"}


def run_tool_loop(
    query: str,
    *,
    base_url: str = "http://127.0.0.1:1919/v1",
    model: str = "Qwen3.6-35B-A3B-NVFP4",
    thinking: bool = True,
    max_turns: int = 4,
    post_json: PostJson = _post_json,
    execute_tool: ExecuteTool = _execute_tool,
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "Ты инженер-сметчик. Нормативные коды и составы работ бери только из инструментов LES. "
                "Для текущей работы сначала вызови search_norm, затем обязательно read_norm для выбранного "
                "кандидата. Не выдумывай факты. После чтения карточки дай краткое решение со source_ref."
            ),
        },
        {"role": "user", "content": query},
    ]
    trace: list[dict[str, Any]] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    answer = ""
    started = perf_counter()
    for turn in range(1, max(1, max_turns) + 1):
        tools_used = [item["tool"] for item in trace]
        if "search_norm" not in tools_used:
            tool_choice: str | dict[str, Any] = {
                "type": "function", "function": {"name": "search_norm"},
            }
        elif "read_norm" not in tools_used:
            tool_choice = {
                "type": "function", "function": {"name": "read_norm"},
            }
        else:
            tool_choice = "none"
        body = {
            "model": model,
            "messages": list(messages),
            "tools": _tool_specs(),
            "tool_choice": tool_choice,
            "parallel_tool_calls": False,
            "temperature": 0.2,
            "max_tokens": 2048,
            "chat_template_kwargs": {"enable_thinking": bool(thinking)},
        }
        turn_started = perf_counter()
        response = post_json(
            f"{base_url.rstrip('/')}/chat/completions",
            body,
            timeout=120,
        )
        turn_elapsed = round(perf_counter() - turn_started, 3)
        response_usage = response.get("usage") or {}
        usage["prompt_tokens"] += int(response_usage.get("prompt_tokens") or 0)
        usage["completion_tokens"] += int(response_usage.get("completion_tokens") or 0)
        message = ((response.get("choices") or [{}])[0].get("message") or {})
        calls = list(message.get("tool_calls") or [])
        assistant_message = {
            "role": "assistant",
            "content": str(message.get("content") or ""),
        }
        if calls:
            assistant_message["tool_calls"] = calls
        messages.append(assistant_message)
        if not calls:
            answer = str(message.get("content") or "").strip()
            break
        for call in calls:
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            try:
                arguments = json.loads(str(function.get("arguments") or "{}"))
            except json.JSONDecodeError:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            tool_started = perf_counter()
            result = execute_tool(name, arguments)
            tool_elapsed = round(perf_counter() - tool_started, 3)
            trace.append({
                "turn": turn,
                "tool": name,
                "arguments": arguments,
                "model_elapsed_seconds": turn_elapsed,
                "tool_elapsed_seconds": tool_elapsed,
                "status": result.get("status"),
                "candidate_codes": [
                    item.get("norm_code") for item in (result.get("candidates") or [])
                ],
                "source_ref": result.get("source_ref"),
            })
            messages.append({
                "role": "tool",
                "tool_call_id": str(call.get("id") or ""),
                "name": name,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })
    tools_used = [item["tool"] for item in trace]
    return {
        "ok": bool(answer) and "search_norm" in tools_used and "read_norm" in tools_used,
        "thinking": bool(thinking),
        "elapsed_seconds": round(perf_counter() - started, 3),
        "usage": usage,
        "tool_trace": trace,
        "answer": answer,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--query",
        default="Подбери норму ФСНБ для монтажа напольного телекоммуникационного шкафа 42U, единица измерения — штука.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:1919/v1")
    parser.add_argument("--model", default="Qwen3.6-35B-A3B-NVFP4")
    parser.add_argument("--thinking", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-turns", type=int, default=4)
    args = parser.parse_args()
    result = run_tool_loop(
        args.query,
        base_url=args.base_url,
        model=args.model,
        thinking=args.thinking,
        max_turns=args.max_turns,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    raise SystemExit(main())
