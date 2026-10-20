"""One token-aware packer for canonical model inference context."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Sequence

from proxy.services.model_execution_preset_service import ModelExecutionPreset


class ContextKind(str, Enum):
    PROFILE_PREFIX = "profile_prefix"
    TOOL_SHORTLIST = "tool_shortlist"
    REQUEST = "request"
    EVIDENCE = "evidence"
    CURRENT_READ_FRAME = "current_read_frame"
    SOURCE_MAP = "source_map"
    TOOL_EXCHANGE = "tool_exchange"
    CHECKPOINT = "checkpoint"
    WORKING_MEMORY = "working_memory"
    DIALOGUE = "dialogue"
    PHASE_INSTRUCTION = "phase_instruction"
    TERMINAL_REQUEST = "terminal_request"


_PACKING_ORDER = tuple(ContextKind)
_PACKING_RANK = {kind: rank for rank, kind in enumerate(_PACKING_ORDER)}


@dataclass(frozen=True)
class NativeToolCall:
    call_id: str
    name: str
    arguments: str

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, str) or not self.call_id.strip():
            raise ValueError("native tool call needs a nonempty provider ID")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("native tool call needs a function name")
        if not isinstance(self.arguments, str):
            raise ValueError("native tool arguments must be literal JSON text")
        try:
            arguments = json.loads(self.arguments)
        except (TypeError, ValueError) as exc:
            raise ValueError("native tool arguments must be a JSON object") from exc
        if not isinstance(arguments, dict):
            raise ValueError("native tool arguments must be a JSON object")

    def as_payload(self) -> dict[str, Any]:
        return {"id": self.call_id, "type": "function",
                "function": {"name": self.name, "arguments": self.arguments}}


@dataclass(frozen=True)
class NativeToolReply:
    call_id: str
    name: str
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, str) or not self.call_id.strip():
            raise ValueError("native tool reply needs a nonempty provider ID")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("native tool reply needs a function name")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("native tool reply needs literal content")


@dataclass(frozen=True)
class NativeToolExchange:
    """One inseparable provider assistant-call batch and its matching replies.

    Only these typed objects can introduce protocol roles. Ordinary context
    dictionaries, including dictionaries with a role key, remain user evidence.
    """

    calls: tuple[NativeToolCall, ...]
    replies: tuple[NativeToolReply, ...]
    assistant_content: str = ""
    reasoning_content: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "calls", tuple(self.calls))
        object.__setattr__(self, "replies", tuple(self.replies))
        if not self.calls or not all(isinstance(call, NativeToolCall) for call in self.calls):
            raise ValueError("native exchange needs typed, nonempty calls")
        if not all(isinstance(reply, NativeToolReply) for reply in self.replies):
            raise ValueError("native exchange needs typed replies")
        ids = tuple(call.call_id for call in self.calls)
        if len(set(ids)) != len(ids):
            raise ValueError("native exchange has duplicate provider IDs")
        if tuple((reply.call_id, reply.name) for reply in self.replies) != tuple(
            (call.call_id, call.name) for call in self.calls
        ):
            raise ValueError("native exchange replies must match every call in order")
        if not isinstance(self.assistant_content, str):
            raise ValueError("native assistant content must be literal text")
        if self.reasoning_content is not None and not isinstance(self.reasoning_content, str):
            raise ValueError("native reasoning content must be literal text or absent")

    def as_messages(self) -> list[dict[str, Any]]:
        assistant = {"role": "assistant", "content": self.assistant_content,
                     "tool_calls": [call.as_payload() for call in self.calls]}
        if self.reasoning_content is not None:
            assistant["reasoning_content"] = self.reasoning_content
        return [assistant,
                *({"role": "tool", "tool_call_id": reply.call_id,
                   "name": reply.name, "content": reply.content} for reply in self.replies)]

    def render(self) -> str:
        # Count roles, IDs, function arguments and result content, not only prose.
        return json.dumps(self.as_messages(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ContextObject:
    object_id: str
    payload: Any

    def render(self) -> str:
        if isinstance(self.payload, NativeToolExchange):
            return self.payload.render()
        if isinstance(self.payload, str):
            return self.payload
        return json.dumps(
            self.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class ContextCandidate:
    kind: ContextKind
    objects: tuple[ContextObject, ...]
    required: bool = False


@dataclass(frozen=True)
class ContextSection:
    kind: ContextKind
    objects: tuple[ContextObject, ...]
    token_count: int

    @property
    def object_ids(self) -> tuple[str, ...]:
        return tuple(item.object_id for item in self.objects)

    def render(self) -> str:
        return "\n".join(item.render() for item in self.objects)


@dataclass(frozen=True)
class ContextOmission:
    kind: ContextKind
    total: int
    omitted: int
    object_ids: tuple[str, ...]
    cursor: str
    reason: str


@dataclass(frozen=True)
class ContextPacket:
    preset_id: str
    input_budget_tokens: int
    generation_reserve_tokens: int
    safety_reserve_tokens: int
    included_tokens: int
    sections: tuple[ContextSection, ...]
    omissions: tuple[ContextOmission, ...]
    provider_payload_tokens: int = 0
    token_count_source: str = "conservative_chars_per_two"
    token_count_binding: dict[str, Any] = field(default_factory=dict)

    def as_messages(self) -> list[dict[str, Any]]:
        system = "\n\n".join(
            section.render()
            for section in self.sections
            if section.kind == ContextKind.PROFILE_PREFIX
        )
        user_sections = [
            "\n".join(item.render() for item in section.objects
                      if not isinstance(item.payload, NativeToolExchange))
            for section in self.sections
            if section.kind not in (ContextKind.PROFILE_PREFIX, ContextKind.CURRENT_READ_FRAME,
                                    ContextKind.PHASE_INSTRUCTION, ContextKind.TERMINAL_REQUEST)
        ]
        user_sections = [text for text in user_sections if text]
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        if user_sections:
            messages.append({"role": "user", "content": "\n".join(user_sections)})
        current_frame = "\n".join(section.render() for section in self.sections
                                  if section.kind == ContextKind.CURRENT_READ_FRAME)
        current_chain = [item.payload for section in self.sections for item in section.objects
                         if isinstance(item.payload, NativeToolExchange)]
        has_native_reasoning = any(isinstance(exchange.reasoning_content, str) and exchange.reasoning_content.strip()
                                   for exchange in current_chain)
        before_native = (bool(current_frame) and has_native_reasoning
                         and not any(section.kind == ContextKind.TERMINAL_REQUEST for section in self.sections))
        phase = "\n".join(section.render() for section in self.sections
                          if section.kind == ContextKind.PHASE_INSTRUCTION)
        if before_native:
            messages.append({"role": "user", "content": current_frame})
        # This is the current application read request, not finalization. Keep
        # it before a reasoning-bearing native chain of the same user turn.
        if phase and has_native_reasoning:
            messages.append({"role": "user", "content": phase})
        for section in self.sections:
            for item in section.objects:
                if isinstance(item.payload, NativeToolExchange):
                    messages.extend(item.payload.as_messages())
        if current_frame and not before_native:
            messages.append({"role": "user", "content": current_frame})
        if phase and not has_native_reasoning:
            messages.append({"role": "user", "content": phase})
        for section in self.sections:
            if section.kind == ContextKind.TERMINAL_REQUEST:
                messages.append({"role": "user", "content": section.render()})
        return messages


class ContextRequiredSectionOverflow(ValueError):
    code = "CONTEXT_REQUIRED_SECTION_OVERFLOW"

    def __init__(self, *, object_ids: tuple[str, ...], budget: int, required_tokens: int,
                 token_count_source: str = "conservative_chars_per_two"):
        self.object_ids = object_ids
        self.budget = budget
        self.required_tokens = required_tokens
        self.token_count_source = token_count_source
        super().__init__(
            f"required context needs {required_tokens} tokens but budget is {budget}"
        )


class ContextRequiredWireOverflow(ValueError):
    """Required whole objects fail the caller's provider-wire admission check."""


def conservative_token_estimate(text: str) -> int:
    """Provider-neutral conservative estimate until an exact tokenizer is bound."""
    return max(1, math.ceil(len(str(text or "")) / 2))


def _cursor(kind: ContextKind, objects: Sequence[ContextObject]) -> str:
    digest = hashlib.sha256()
    for item in objects:
        digest.update(item.object_id.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(item.render().encode("utf-8"))
        digest.update(b"\x00")
    return f"ctx:{kind.value}:{digest.hexdigest()[:20]}"


class ContextGovernor:
    def __init__(
        self,
        preset: ModelExecutionPreset,
        *,
        estimate_tokens: Callable[[str], int] = conservative_token_estimate,
    ) -> None:
        self.preset = preset
        self.estimate_tokens = estimate_tokens

    def _object_tokens(self, item: ContextObject) -> int:
        return max(0, int(self.estimate_tokens(item.render())))

    def pack(self, candidates: Sequence[ContextCandidate], *,
             admit_messages: Callable[[list[dict[str, Any]]], bool] | None = None,
             count_messages_tokens: Callable[[list[dict[str, Any]]], int] | None = None,
             token_count_source: str = "conservative_chars_per_two") -> ContextPacket:
        """Pack complete objects in canonical order after fixed reserves."""
        budget = max(
            0,
            int(self.preset.input_token_limit)
            - int(self.preset.generation_reserve_tokens)
            - int(self.preset.safety_reserve_tokens),
        )
        ordered = sorted(candidates, key=lambda candidate: _PACKING_RANK[candidate.kind])
        phase_candidates = [candidate for candidate in ordered if candidate.kind == ContextKind.PHASE_INSTRUCTION]
        if phase_candidates and any(candidate.kind == ContextKind.TERMINAL_REQUEST for candidate in ordered):
            raise ValueError("phase instruction and terminal request cannot be combined")
        if len(phase_candidates) > 1:
            raise ValueError("phase instruction must be one required literal instruction")
        native_ids: set[str] = set()
        for candidate in ordered:
            if candidate.kind == ContextKind.PHASE_INSTRUCTION:
                if (not candidate.required or len(candidate.objects) != 1
                        or not isinstance(candidate.objects[0].payload, str)
                        or not candidate.objects[0].payload.strip()):
                    raise ValueError("phase instruction must be one required nonempty literal instruction")
            if candidate.kind == ContextKind.TERMINAL_REQUEST:
                if (not candidate.required or len(candidate.objects) != 1
                        or not isinstance(candidate.objects[0].payload, str)
                        or not candidate.objects[0].payload.strip()):
                    raise ValueError("terminal request must be one required nonempty literal instruction")
            if any(isinstance(item.payload, NativeToolExchange) for item in candidate.objects):
                if candidate.kind != ContextKind.TOOL_EXCHANGE or not candidate.required:
                    raise ValueError("native exchanges must be required TOOL_EXCHANGE objects")
                for item in candidate.objects:
                    if isinstance(item.payload, NativeToolExchange):
                        ids = {call.call_id for call in item.payload.calls}
                        if native_ids.intersection(ids):
                            raise ValueError("native exchange history has duplicate provider IDs")
                        native_ids.update(ids)

        required_ids: list[str] = []
        required_tokens = 0
        required_by_kind: dict[ContextKind, list[ContextObject]] = {}
        required_section_tokens: dict[ContextKind, int] = {}
        required_object_count = 0
        for candidate in ordered:
            if not candidate.required:
                continue
            for item in candidate.objects:
                required_ids.append(item.object_id)
                separator = 1 if required_object_count else 0
                section_separator = 1 if required_by_kind.get(candidate.kind) else 0
                item_tokens = self._object_tokens(item)
                required_by_kind.setdefault(candidate.kind, []).append(item)
                required_section_tokens[candidate.kind] = (
                    required_section_tokens.get(candidate.kind, 0)
                    + section_separator
                    + item_tokens
                )
                required_tokens += separator + item_tokens
                required_object_count += 1
        if count_messages_tokens is None and required_tokens > budget:
            raise ContextRequiredSectionOverflow(
                object_ids=tuple(required_ids),
                budget=budget,
                required_tokens=required_tokens,
            )

        selected: dict[ContextKind, list[ContextObject]] = {
            kind: list(items) for kind, items in required_by_kind.items()
        }
        section_tokens: dict[ContextKind, int] = dict(required_section_tokens)
        omissions: list[ContextOmission] = []
        used = required_tokens

        actual_wire_tokens = None

        def wire_fits() -> bool:
            nonlocal actual_wire_tokens
            if admit_messages is None and count_messages_tokens is None:
                return True
            probe = ContextPacket(
                preset_id=self.preset.preset_id, input_budget_tokens=budget,
                generation_reserve_tokens=self.preset.generation_reserve_tokens,
                safety_reserve_tokens=self.preset.safety_reserve_tokens, included_tokens=used,
                sections=tuple(ContextSection(kind=kind, objects=tuple(selected[kind]), token_count=0)
                               for kind in _PACKING_ORDER if selected.get(kind)), omissions=(),
            )
            messages = probe.as_messages()
            if count_messages_tokens is not None:
                actual_wire_tokens = count_messages_tokens(messages)
                if type(actual_wire_tokens) is not int or actual_wire_tokens < 0:
                    raise ValueError("wire token count must be a nonnegative integer")
                if actual_wire_tokens > budget:
                    return False
            return admit_messages is None or admit_messages(messages)

        if not wire_fits():
            if actual_wire_tokens is not None and actual_wire_tokens > budget:
                raise ContextRequiredSectionOverflow(
                    object_ids=tuple(required_ids), budget=budget,
                    required_tokens=actual_wire_tokens,
                    token_count_source=token_count_source,
                )
            raise ContextRequiredWireOverflow("required context exceeds provider wire allowance")

        for candidate in ordered:
            if candidate.required:
                continue
            included: list[ContextObject] = []
            omitted: list[ContextObject] = []
            wire_omitted = False
            for item in candidate.objects:
                item_tokens = self._object_tokens(item)
                separator = 1 if used else 0
                section_separator = 1 if selected.get(candidate.kind) else 0
                if count_messages_tokens is not None or used + separator + item_tokens <= budget:
                    selected.setdefault(candidate.kind, []).append(item)
                    if not wire_fits():
                        selected[candidate.kind].pop()
                        omitted.append(item)
                        wire_omitted = True
                        continue
                    included.append(item)
                    used += separator + item_tokens
                    section_tokens[candidate.kind] = (
                        section_tokens.get(candidate.kind, 0)
                        + section_separator
                        + item_tokens
                    )
                else:
                    omitted.append(item)
            if omitted:
                omissions.append(
                    ContextOmission(
                        kind=candidate.kind,
                        total=len(candidate.objects),
                        omitted=len(omitted),
                        object_ids=tuple(item.object_id for item in omitted),
                        cursor=_cursor(candidate.kind, omitted),
                        reason="wire_budget_exhausted" if wire_omitted else "budget_exhausted",
                    )
                )

        sections = tuple(
            ContextSection(
                kind=kind,
                objects=tuple(selected[kind]),
                token_count=section_tokens[kind],
            )
            for kind in _PACKING_ORDER
            if selected.get(kind)
        )
        # A rejected optional probe must not become the count of the admitted
        # frame. Recount through the caller's memoized whole-wire binding.
        if count_messages_tokens is not None:
            wire_fits()
        return ContextPacket(
            preset_id=self.preset.preset_id,
            input_budget_tokens=budget,
            generation_reserve_tokens=self.preset.generation_reserve_tokens,
            safety_reserve_tokens=self.preset.safety_reserve_tokens,
            included_tokens=actual_wire_tokens if actual_wire_tokens is not None else used,
            sections=sections,
            omissions=tuple(omissions),
            token_count_source=token_count_source,
        )
