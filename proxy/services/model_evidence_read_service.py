"""Drive optional model-requested evidence reads without choosing a domain result."""

from __future__ import annotations

import inspect
import json
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from proxy.services.context_governor_service import NativeToolCall, NativeToolExchange, NativeToolReply
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
    native_exchanges: tuple[NativeToolExchange, ...] = ()


def evidence_read_call_identity(call: Mapping[str, Any]) -> str:
    """Literal scope, query, pointer, paging and price arguments all matter."""
    return json.dumps({"tool": call.get("tool"), "args": call.get("args") or {}},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def evidence_read_receipt(call: Mapping[str, Any], result: Any) -> dict[str, Any]:
    payload = getattr(result, "payload", result)
    payload = dict(payload) if isinstance(payload, Mapping) else {}
    # Native protocol metadata belongs to the assistant exchange, not repeated
    # receipt/evidence prose. The provider ID remains available for every reply.
    public_call = {key: call[key] for key in ("tool", "args", "call_id") if key in call}
    return read_result_receipt(public_call, payload)


def _native_calls(calls: Sequence[Mapping[str, Any]]) -> tuple[NativeToolCall, ...]:
    if not any("call_id" in call for call in calls):
        return ()
    typed = []
    for call in calls:
        arguments = call.get("native_arguments")
        if arguments is None:
            arguments = json.dumps(call.get("args") or {}, ensure_ascii=False, separators=(",", ":"))
        native = NativeToolCall(call.get("call_id"), call.get("tool"), arguments)
        if json.loads(native.arguments) != call.get("args"):
            raise ValueError("native arguments differ from the executed literal call")
        typed.append(native)
    ids = [call.call_id for call in typed]
    if len(set(ids)) != len(ids):
        raise ValueError("native batch has duplicate provider IDs")
    return tuple(typed)


def native_evidence_read_exchange(
    calls: Sequence[Mapping[str, Any]], receipts: Sequence[Mapping[str, Any]],
) -> NativeToolExchange | None:
    """Return protocol receipts; literal card bodies stay in the cited registry."""
    typed_calls = _native_calls(calls)
    if not typed_calls:
        return None
    if len(receipts) != len(typed_calls):
        raise ValueError("native batch needs exactly one receipt per call")
    replies = []
    for call, receipt in zip(typed_calls, receipts, strict=True):
        recorded_call = receipt.get("call") or {}
        if (recorded_call.get("call_id") != call.call_id or recorded_call.get("tool") != call.name
                or recorded_call.get("args") != json.loads(call.arguments)):
            raise ValueError("native receipt belongs to another call")
        replies.append(NativeToolReply(call.call_id, call.name, json.dumps(
            dict(receipt), ensure_ascii=False, sort_keys=True, separators=(",", ":"))))
    return NativeToolExchange(calls=typed_calls, replies=tuple(replies),
                              assistant_content=calls[0].get("native_assistant_content", ""),
                              reasoning_content=calls[0].get("native_reasoning_content"))


async def _invoke(callback: Callable, *args: Any) -> Any:
    result = callback(*args)
    return await result if inspect.isawaitable(result) else result


async def run_model_evidence_read_turn(
    *,
    text: str,
    usage: Mapping[str, Any] | None,
    parse_calls: Callable,
    execute: Callable,
    continue_turn: Callable | None = None,
    continue_native_turn: Callable | None = None,
    allowed_tools: Sequence[str] | set[str],
    max_calls: int = 48,
    on_read_results: Callable | None = None,
    on_read_replays: Callable | None = None,
    initial_receipts: Sequence[Mapping[str, Any]] = (),
    seen_calls: Sequence[str] = (),
) -> ModelEvidenceReadTurnResult:
    """Finish a turn only when the same model requests an evidence operation.

    ``execute`` receives one literal call mapping. ``on_read_results`` receives
    the new receipt/result batch and may return a visible stop reason.
    ``continue_turn`` receives cumulative receipts/results. The native callback
    additionally receives complete typed exchanges for governed serialization.
    Exceptions propagate; the caller owns technical pauses.
    Previously executed identities can be supplied by a durable ledger. A native
    retry with a fresh provider ID receives the saved receipt once, without a
    second read or new evidence bindings. Replays consume the same call budget;
    a further retry of that identity stops. Legacy text calls keep their guard.
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
    native_exchanges: list[NativeToolExchange] = []
    native_ids: set[str] = set()
    # A new chat turn can change the price basis or source edition. Only reads
    # executed in this invocation are eligible; an old journal is not a cache.
    cached: dict[str, dict[str, Any]] = {}
    replayed: set[str] = set()
    while current_text:
        calls = parse_calls(current_text, allowed_tools=names, max_calls=max(remaining, 1))
        if not calls:
            break
        extra_tokens += int(current_usage.get("completion_tokens") or 0)
        if remaining <= 0:
            stop = "evidence_read_budget"
            break
        try:
            typed_calls = _native_calls(calls)
        except ValueError:
            stop = "evidence_read_native_exchange_invalid"
            break
        if typed_calls:
            if any(call.name not in names for call in typed_calls):
                stop = "evidence_read_unknown_tool"
                break
            if native_ids.intersection(call.call_id for call in typed_calls):
                stop = "evidence_read_native_exchange_invalid"
                break
            identities_in_batch = [evidence_read_call_identity(call) for call in calls]
            counts = Counter(identities_in_batch)
            if any(count > (1 if identity in seen else 2)
                   or (identity in seen and (identity not in cached or identity in replayed))
                   for identity, count in counts.items()):
                stop = "evidence_read_repeat"
                break
            if len(typed_calls) > remaining:
                stop = "evidence_read_budget"
                break
        batch_receipts: list[dict[str, Any]] = []
        batch_results: list[Any] = []
        fresh_by_identity: dict[str, dict[str, Any]] = {}
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
            receipt = evidence_read_receipt(call, result)
            batch_receipts.append(receipt)
            fresh_by_identity[identity] = receipt
        receipts.extend(batch_receipts)
        results.extend(batch_results)
        if batch_results and on_read_results is not None:
            reason = await _invoke(on_read_results, batch_receipts, batch_results)
            if isinstance(reason, str) and reason:
                stop = reason
        if not batch_results and not typed_calls and not stop:
            stop = "evidence_read_repeat"
        if stop:
            break
        if typed_calls:
            # Binding happens in on_read_results. Replay only afterwards so a
            # duplicate never gets a new Q-ref or loses the literal source IDs.
            cached.update({identity: receipt for identity, receipt in fresh_by_identity.items()
                           if receipt.get("status") in {"ok", "missing", "conflict"}})
            protocol_receipts, replay_receipts = [], []
            for call in calls:
                identity = evidence_read_call_identity(call)
                fresh = fresh_by_identity.pop(identity, None)
                if fresh is not None:
                    protocol_receipts.append(fresh)
                    continue
                previous = cached.get(identity)
                if previous is None or identity in replayed:
                    stop = "evidence_read_repeat"
                    break
                receipt = deepcopy(previous)
                receipt["replayed_from_call_id"] = str(previous["call"].get("call_id") or "saved-read")
                receipt["call"] = {key: call[key] for key in ("tool", "args", "call_id") if key in call}
                protocol_receipts.append(receipt)
                replay_receipts.append(receipt)
                replayed.add(identity)
                remaining -= 1
            if stop:
                break
            receipts.extend(replay_receipts)
            if replay_receipts and on_read_replays is not None:
                await _invoke(on_read_replays, replay_receipts)
            batch_receipts = protocol_receipts
        try:
            exchange = native_evidence_read_exchange(calls, batch_receipts)
        except ValueError:
            stop = "evidence_read_native_exchange_invalid"
            break
        if exchange is not None:
            native_exchanges.append(exchange)
            native_ids.update(call.call_id for call in exchange.calls)
        if continue_native_turn is not None:
            current_text, next_usage = await _invoke(continue_native_turn, receipts, results, tuple(native_exchanges))
        elif continue_turn is not None:
            current_text, next_usage = await _invoke(continue_turn, receipts, results)
        else:
            raise ValueError("an evidence read needs a continuation callback")
        current_usage = dict(next_usage or {})
    return ModelEvidenceReadTurnResult(
        text=current_text, usage=current_usage, extra_completion_tokens=extra_tokens,
        stop_reason=stop, receipts=tuple(receipts), results=tuple(results), seen_calls=tuple(identities),
        native_exchanges=tuple(native_exchanges),
    )
