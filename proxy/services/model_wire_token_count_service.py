"""Lossless text/native-tool mapping to FreeToken's local token counter.

Both FreeToken protocol adapters use ``generation.render_messages``. It
decodes JSON function arguments before applying the same chat template. This
module accepts only the subset for which the resulting prompt is identical;
unsupported input falls back to the existing conservative governor.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from proxy.services.model_connection_contracts import ConnectionLocality


TOKEN_COUNT_SOURCE = "freetoken.messages.count_tokens"
TOKEN_COUNT_PROVIDER_OWNER = "FreeToken"


def supports_model_token_count(extension_type: str | None, locality: ConnectionLocality,
                               endpoint_locality: ConnectionLocality) -> bool:
    """Protocol-specific capability binding kept out of the neutral transport."""
    return (extension_type == "freetoken" and locality is ConnectionLocality.LOOPBACK
            and endpoint_locality is ConnectionLocality.LOOPBACK)


def normalize_model_count_wire(body: Mapping[str, Any], extension_type: str | None) -> dict[str, Any]:
    return normalize_freetoken_count_wire(body) if extension_type == "freetoken" else dict(body)


class UnsupportedTokenCountWire(ValueError):
    """A prompt cannot be represented without dropping protocol information."""


@dataclass(frozen=True)
class InputTokenCount:
    tokens: int
    source: str
    model_id: str
    connection_revision_id: str
    wire_sha256: str
    model_identity_sha256: str


def wire_sha256(body: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def normalize_freetoken_count_wire(body: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize redundant fields on the *actual* FreeToken wire, never storage.

Tool IDs already identify replies and their function names. FreeToken's
Anthropic adapter represents replies by ID and literal content. Empty native
assistant prose is absent in that adapter. The installed Qwen template renders
both forms identically. The explicit thinking broadcast is the same for both
FreeToken protocol adapters; no model-cache path is used by admission.
"""
    result = deepcopy(dict(body))
    kwargs = result.get("chat_template_kwargs")
    if isinstance(kwargs, Mapping) and type(kwargs.get("enable_thinking")) is bool:
        result["chat_template_kwargs"] = {
            **kwargs, "thinking_mode": "enabled" if kwargs["enable_thinking"] else "disabled",
        }
    for message in result.get("messages", ()):
        if not isinstance(message, dict):
            continue
        if message.get("role") == "tool":
            message.pop("name", None)
        if message.get("role") == "assistant" and message.get("tool_calls") and message.get("content") == "":
            message.pop("content")
    return result


def freetoken_count_payload(body: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a normalized OpenAI prompt without changing any model evidence."""
    allowed = {"model", "messages", "tools", "tool_choice", "chat_template_kwargs",
               "max_tokens", "max_completion_tokens", "temperature", "stream"}
    if set(body) - allowed or body.get("stream") is True:
        raise UnsupportedTokenCountWire("unsupported_prompt_fields")
    model = body.get("model")
    if not isinstance(model, str) or not model:
        raise UnsupportedTokenCountWire("model_required")
    kwargs = body.get("chat_template_kwargs")
    if (not isinstance(kwargs, Mapping) or set(kwargs) != {"enable_thinking", "thinking_mode"}
            or type(kwargs.get("enable_thinking")) is not bool
            or kwargs["thinking_mode"] != ("enabled" if kwargs["enable_thinking"] else "disabled")):
        raise UnsupportedTokenCountWire("unsupported_template_kwargs")
    payload: dict[str, Any] = {"model": model, "messages": [],
                               "thinking": {"type": "enabled" if kwargs["enable_thinking"] else "disabled"}}
    tools = []
    for tool in body.get("tools", ()):
        if not isinstance(tool, Mapping) or set(tool) != {"type", "function"} or tool.get("type") != "function":
            raise UnsupportedTokenCountWire("unsupported_tool_schema")
        function = tool.get("function")
        if (not isinstance(function, Mapping) or set(function) != {"name", "description", "parameters"}
                or not isinstance(function.get("name"), str) or not function["name"]
                or not isinstance(function.get("description"), str)
                or not isinstance(function.get("parameters"), Mapping)):
            raise UnsupportedTokenCountWire("unsupported_tool_schema")
        tools.append({"name": function["name"], "description": function["description"],
                      "input_schema": deepcopy(dict(function["parameters"]))})
    if tools:
        payload["tools"] = tools
    choice = body.get("tool_choice", "auto")
    if choice in ("auto", "none", "required"):
        if "tool_choice" in body:
            payload["tool_choice"] = {"type": {"required": "any"}.get(choice, choice)}
    elif (isinstance(choice, Mapping) and set(choice) == {"type", "function"}
          and choice.get("type") == "function" and isinstance(choice.get("function"), Mapping)
          and set(choice["function"]) == {"name"}
          and isinstance(choice["function"]["name"], str)):
        payload["tool_choice"] = {"type": "tool", "name": choice["function"]["name"]}
    else:
        raise UnsupportedTokenCountWire("unsupported_tool_choice")
    pending: list[str] = []
    seen_ids: set[str] = set()
    messages = body.get("messages")
    if not isinstance(messages, (list, tuple)) or not messages:
        raise UnsupportedTokenCountWire("messages_required")
    for index, message in enumerate(messages):
        if not isinstance(message, Mapping):
            raise UnsupportedTokenCountWire("unsupported_message")
        role = message.get("role")
        content = message.get("content")
        if role == "system":
            if index != 0 or set(message) != {"role", "content"} or not isinstance(content, str) or not content:
                raise UnsupportedTokenCountWire("unsupported_system_message")
            payload["system"] = content
        elif role == "user":
            if pending or set(message) != {"role", "content"} or not isinstance(content, str):
                raise UnsupportedTokenCountWire("unsupported_user_message")
            payload["messages"].append({"role": role, "content": content})
        elif role == "assistant":
            if pending or set(message) - {"role", "content", "tool_calls", "reasoning_content"}:
                raise UnsupportedTokenCountWire("unsupported_assistant_message")
            reasoning = message.get("reasoning_content")
            if "reasoning_content" in message and (not isinstance(reasoning, str) or not reasoning):
                raise UnsupportedTokenCountWire("unsupported_assistant_reasoning_content")
            if "content" in message and (not isinstance(content, str) or not content):
                raise UnsupportedTokenCountWire("unsupported_empty_assistant_content")
            # Installed FreeToken converts one thinking block back to this exact
            # reasoning_content string before the shared OpenAI prompt renderer.
            blocks = [{"type": "thinking", "thinking": reasoning}] if reasoning else []
            if content:
                blocks.append({"type": "text", "text": content})
            calls = message.get("tool_calls", ())
            if not isinstance(calls, (list, tuple)):
                raise UnsupportedTokenCountWire("unsupported_tool_calls")
            for call in calls:
                if not isinstance(call, Mapping) or set(call) != {"id", "type", "function"} or call.get("type") != "function":
                    raise UnsupportedTokenCountWire("unsupported_tool_call")
                call_id, function = call.get("id"), call.get("function")
                if (not isinstance(call_id, str) or not call_id or call_id in seen_ids
                        or not isinstance(function, Mapping) or set(function) != {"name", "arguments"}
                        or not isinstance(function.get("name"), str) or not function["name"]):
                    raise UnsupportedTokenCountWire("unsupported_tool_call")
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError as exc:
                        raise UnsupportedTokenCountWire("invalid_tool_arguments") from exc
                if not isinstance(arguments, Mapping):
                    raise UnsupportedTokenCountWire("tool_arguments_object_required")
                blocks.append({"type": "tool_use", "id": call_id, "name": function["name"],
                               "input": deepcopy(dict(arguments))})
                pending.append(call_id)
                seen_ids.add(call_id)
            if not blocks:
                raise UnsupportedTokenCountWire("empty_assistant_message")
            payload["messages"].append({"role": role, "content": blocks})
        elif role == "tool":
            if (set(message) != {"role", "tool_call_id", "content"} or not isinstance(content, str)
                    or not pending or message.get("tool_call_id") != pending[0]):
                raise UnsupportedTokenCountWire("unmatched_tool_reply")
            pending.pop(0)
            payload["messages"].append({"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": message["tool_call_id"], "content": content,
            }]})
        else:
            raise UnsupportedTokenCountWire("unsupported_message_role")
    if pending or not payload["messages"]:
        raise UnsupportedTokenCountWire("incomplete_tool_exchange")
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise UnsupportedTokenCountWire("unsupported_json_value") from exc
    return payload


model_token_count_payload = freetoken_count_payload
