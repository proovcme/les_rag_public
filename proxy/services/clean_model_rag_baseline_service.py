"""Diagnostic control: owner input -> native model reads -> ordinary model answer.

This is not a second production workflow or a professional acceptance receipt.
It deliberately does not import query/result instructions, parse a document,
choose operations or norms, repair model formatting, or require an artifact.
Callers supply the same pinned connection, source and dataset as the candidate.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import json
from typing import Any

from proxy.services.canonical_route_service import CanonicalRouteMode
from proxy.services.chat_evidence_application_service import (
    bind_model_requested_read_evidence, confirm_model_read_delivery,
    govern_inference_messages_bound, govern_model_read_messages_bound,
)
from proxy.services.context_governor_service import ContextRequiredSectionOverflow, NativeToolCall
from proxy.services.model_evidence_read_contract import model_evidence_read_tool_schemas
from proxy.services.model_evidence_read_service import evidence_read_receipt, native_evidence_read_exchange
from proxy.services.openai_compatible_transport_service import InferenceRequest


@dataclass(frozen=True)
class CleanModelRagResult:
    status: str
    answer: str
    finish_reason: str
    model_calls: int
    evidence: tuple[Any, ...]
    receipts: tuple[dict[str, Any], ...]


async def run_clean_model_rag_baseline(*, runner, research_tools, preset,
        connection_revision_id: str, question: str, source_context,
        profile_prefix: str = '', count_messages=None, max_read_calls: int = 48,
        temperature: float | None = None, remote_allowed: bool = False) -> CleanModelRagResult:
    """Run explicitly, using existing governed transport and read-only tools.

No role fallback or changed connection can pass the exact-revision binding.
An ordinary final answer ends the control immediately, even without tool calls.
Technical limits are statuses; they never synthesize a professional MISSING.
"""
    if not isinstance(question, str) or not question.strip() or not connection_revision_id:
        raise ValueError('baseline needs the original question and exact connection revision')
    if type(max_read_calls) is not int or max_read_calls < 0:
        raise ValueError('max_read_calls must be a nonnegative integer')
    tools = model_evidence_read_tool_schemas()
    source_context = deepcopy(list(source_context))
    allowed = {tool['function']['name'] for tool in tools}
    chunks, receipts, exchanges = [], [], []
    provider_ids, executed_calls = set(), set()
    model_calls = 0
    text, finish = '', ''

    def outcome(status):
        return CleanModelRagResult(status, text, finish, model_calls, tuple(chunks), tuple(receipts))

    async def forbidden_legacy(*args, **kwargs):
        raise RuntimeError('clean baseline cannot use a legacy or unpinned model route')

    while True:
        context = dict(preset=preset, profile_prefix=profile_prefix, request_payload=question,
                       native_tools=tools, native_exchanges=exchanges)
        try:
            if chunks or exchanges:
                archive = research_tools.register_evidence_archive(chunks)
                messages, _, inventory, bodies = await govern_model_read_messages_bound(
                    count_messages=count_messages, **context, source_context=source_context,
                    chunks=chunks, receipts=receipts, evidence_archive=archive)
            else:
                messages, _ = await govern_inference_messages_bound(count_messages=count_messages,
                    **context, required_evidence=list(source_context))
                inventory, bodies = [], []
        except ContextRequiredSectionOverflow:
            return outcome('context_limit')
        result = await runner.complete(mode=CanonicalRouteMode.ACTIVE,
            request=InferenceRequest(messages=messages, tools=tools,
                max_output_tokens=max(1, preset.generation_reserve_tokens),
                temperature=temperature, reasoning_enabled=preset.reasoning_enabled),
            legacy_complete=forbidden_legacy, remote_allowed=remote_allowed,
            expected_connection_revision_id=connection_revision_id)
        model_calls += 1
        response = result.response
        text, finish = response.text, response.finish_reason
        confirm_model_read_delivery(chunks, receipts, inventory_refs=inventory, body_refs=bodies)
        research_tools.register_shown_norm_cards(chunks)
        if finish == 'length':
            return outcome('output_limit')
        if not response.tool_calls:
            return outcome('terminal' if finish == 'stop' else 'provider_stop')
        if len(receipts) + len(response.tool_calls) > max_read_calls:
            return outcome('read_budget')
        calls = []
        try:
            for raw in response.tool_calls:
                function = raw['function']
                typed = NativeToolCall(raw['id'], function['name'], function['arguments'])
                if typed.name not in allowed or typed.call_id in provider_ids:
                    return outcome('native_call_invalid')
                args = json.loads(typed.arguments)
                identity = json.dumps([typed.name, args], sort_keys=True, ensure_ascii=False, allow_nan=False)
                if identity in executed_calls:
                    return outcome('read_repeat')
                executed_calls.add(identity)
                provider_ids.add(typed.call_id)
                calls.append({'tool': typed.name, 'args': args, 'call_id': typed.call_id,
                    'native_arguments': typed.arguments, 'native_assistant_content': response.text,
                    'native_reasoning_content': response.reasoning_content})
        except (KeyError, TypeError, ValueError):
            return outcome('native_call_invalid')
        # Validate the entire native batch before executing even its first read.
        results = [await research_tools.execute(call) for call in calls]
        batch = [evidence_read_receipt(call, result) for call, result in zip(calls, results, strict=True)]
        _, new_chunks, omitted = bind_model_requested_read_evidence(results, existing_chunks=chunks,
            receipts=batch, evidence_namespace=f'clean-control:{model_calls}')
        chunks.extend(new_chunks)
        receipts.extend(batch)
        if omitted:
            return outcome('read_capacity')
        exchanges.append(native_evidence_read_exchange(calls, batch))
