"""Drive optional model-requested evidence reads without choosing a domain result."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from proxy.services.model_evidence_read_contract import read_result_receipt


@dataclass(frozen=True)
class ModelEvidenceReadTurnResult:
    text: str
    usage: dict[str, Any]
    extra_completion_tokens: int
    stop_reason: str
    receipts: tuple[dict[str, Any], ...]
    results: tuple[Any, ...]
    seen_calls: tuple[str, ...]


def evidence_read_call_identity(call: Mapping[str, Any]) -> str:
    """Literal scope, query, pointer, paging and price arguments all matter."""
    return json.dumps({"tool": call.get("tool"), "args": call.get("args") or {}},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def evidence_read_receipt(call: Mapping[str, Any], result: Any) -> dict[str, Any]:
    payload = getattr(result, "payload", result)
    payload = dict(payload) if isinstance(payload, Mapping) else {}
    return read_result_receipt(call, payload)


async def _invoke(callback: Callable, *args: Any) -> Any:
    result = callback(*args)
    return await result if inspect.isawaitable(result) else result


async def run_model_evidence_read_turn(
    *,
    text: str,
    usage: Mapping[str, Any] | None,
    parse_calls: Callable,
    execute: Callable,
    continue_turn: Callable,
    allowed_tools: Sequence[str] | set[str],
    max_calls: int = 48,
    on_read_results: Callable | None = None,
    initial_receipts: Sequence[Mapping[str, Any]] = (),
    seen_calls: Sequence[str] = (),
) -> ModelEvidenceReadTurnResult:
    """Finish a turn only when the same model requests an evidence operation.

    ``execute`` receives one literal call mapping. ``on_read_results`` receives
    the new receipt/result batch and may return a visible stop reason.
    ``continue_turn`` receives cumulative receipts/results and returns the next
    model text/usage. Exceptions propagate; the caller owns technical pauses.
    Previously executed identities can be supplied by a durable ledger.
    """
    current_text = text
    current_usage = dict(usage or {})
    receipts = [dict(item) for item in initial_receipts]
    results: list[Any] = []
    identities = list(dict.fromkeys(str(item) for item in seen_calls))
    seen = set(identities)
    remaining = max(0, int(max_calls))
    extra_tokens = 0
    stop = ""
    names = set(allowed_tools)
    while current_text:
        calls = parse_calls(current_text, allowed_tools=names, max_calls=max(remaining, 1))
        if not calls:
            break
        extra_tokens += int(current_usage.get("completion_tokens") or 0)
        if remaining <= 0:
            stop = "evidence_read_budget"
            break
        batch_receipts: list[dict[str, Any]] = []
        batch_results: list[Any] = []
        for call in calls:
            if not isinstance(call, Mapping) or str(call.get("tool") or "") not in names:
                continue
            identity = evidence_read_call_identity(call)
            if identity in seen:
                continue
            if remaining <= 0:
                stop = "evidence_read_budget"
                break
            result = await _invoke(execute, call)
            # A failed execution is not marked successful and its error remains
            # visible to the caller. Normal missing/conflict results are receipts.
            seen.add(identity)
            identities.append(identity)
            remaining -= 1
            batch_results.append(result)
            batch_receipts.append(evidence_read_receipt(call, result))
        receipts.extend(batch_receipts)
        results.extend(batch_results)
        if batch_results and on_read_results is not None:
            reason = await _invoke(on_read_results, batch_receipts, batch_results)
            if isinstance(reason, str) and reason:
                stop = reason
        if not batch_results and not stop:
            stop = "evidence_read_repeat"
        if stop:
            break
        current_text, next_usage = await _invoke(continue_turn, receipts, results)
        current_usage = dict(next_usage or {})
    return ModelEvidenceReadTurnResult(
        text=current_text, usage=current_usage, extra_completion_tokens=extra_tokens,
        stop_reason=stop, receipts=tuple(receipts), results=tuple(results), seen_calls=tuple(identities),
    )
