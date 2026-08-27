"""One token-aware packer for canonical model inference context."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Sequence

from proxy.services.model_execution_preset_service import ModelExecutionPreset


class ContextKind(str, Enum):
    PROFILE_PREFIX = "profile_prefix"
    TOOL_SHORTLIST = "tool_shortlist"
    REQUEST = "request"
    CHECKPOINT = "checkpoint"
    WORKING_MEMORY = "working_memory"
    EVIDENCE = "evidence"
    SOURCE_MAP = "source_map"
    TOOL_EXCHANGE = "tool_exchange"
    DIALOGUE = "dialogue"


_PACKING_ORDER = tuple(ContextKind)
_PACKING_RANK = {kind: rank for rank, kind in enumerate(_PACKING_ORDER)}


@dataclass(frozen=True)
class ContextObject:
    object_id: str
    payload: Any

    def render(self) -> str:
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

    def as_messages(self) -> list[dict[str, str]]:
        system = "\n\n".join(
            section.render()
            for section in self.sections
            if section.kind == ContextKind.PROFILE_PREFIX
        )
        user_sections = [
            section.render()
            for section in self.sections
            if section.kind != ContextKind.PROFILE_PREFIX
        ]
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        if user_sections:
            messages.append({"role": "user", "content": "\n".join(user_sections)})
        return messages


class ContextRequiredSectionOverflow(ValueError):
    code = "CONTEXT_REQUIRED_SECTION_OVERFLOW"

    def __init__(self, *, object_ids: tuple[str, ...], budget: int, required_tokens: int):
        self.object_ids = object_ids
        self.budget = budget
        self.required_tokens = required_tokens
        super().__init__(
            f"required context needs {required_tokens} tokens but budget is {budget}"
        )


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

    def pack(self, candidates: Sequence[ContextCandidate]) -> ContextPacket:
        """Pack complete objects in canonical order after fixed reserves."""
        budget = max(
            0,
            int(self.preset.input_token_limit)
            - int(self.preset.generation_reserve_tokens)
            - int(self.preset.safety_reserve_tokens),
        )
        ordered = sorted(candidates, key=lambda candidate: _PACKING_RANK[candidate.kind])

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
        if required_tokens > budget:
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

        for candidate in ordered:
            if candidate.required:
                continue
            included: list[ContextObject] = []
            omitted: list[ContextObject] = []
            for item in candidate.objects:
                item_tokens = self._object_tokens(item)
                separator = 1 if used else 0
                section_separator = 1 if selected.get(candidate.kind) else 0
                if used + separator + item_tokens <= budget:
                    selected.setdefault(candidate.kind, []).append(item)
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
                        reason="budget_exhausted",
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
        return ContextPacket(
            preset_id=self.preset.preset_id,
            input_budget_tokens=budget,
            generation_reserve_tokens=self.preset.generation_reserve_tokens,
            safety_reserve_tokens=self.preset.safety_reserve_tokens,
            included_tokens=used,
            sections=sections,
            omissions=tuple(omissions),
        )
