"""Typed advisory projection over existing LES memory stores."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, Mapping, Sequence

from proxy.services.context_governor_service import (
    ContextCandidate,
    ContextKind,
    ContextObject,
)
from proxy.services.context_memory_service import chat_memory_projection_record
from proxy.services.memory_port import project_advisory_items
from proxy.services.memory_service import (
    project_note_items,
    session_memory_items,
    session_recent_retrieval_traces,
)


class MemoryItemKind(str, Enum):
    CHECKPOINT = "checkpoint"
    BLOCKER = "blocker"
    DECISION = "decision"
    EVIDENCE_LOCATOR = "evidence_locator"
    CONTINUITY = "continuity"
    ADVISORY_FACT = "advisory_fact"


@dataclass(frozen=True)
class MemoryLimits:
    max_items: int = 24
    max_dialogue_turns: int = 6
    max_notes: int = 5
    max_advisory_items: int = 5
    max_payload_chars: int = 700


@dataclass(frozen=True)
class MemoryItem:
    item_id: str
    kind: MemoryItemKind
    payload: Mapping[str, Any]
    revision_ref: str | None
    project_id: int | None
    is_evidence: Literal[False] = False

    def as_payload(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "kind": self.kind.value,
            "payload": dict(self.payload),
            "revision_ref": self.revision_ref,
            "project_id": self.project_id,
            "context_role": "advisory_state",
            "is_evidence": False,
        }


@dataclass(frozen=True)
class MemoryProjection:
    session_id: str
    project_id: int | None
    items: tuple[MemoryItem, ...]
    omitted: int
    cursor: str
    context_role: str = "advisory_state"

    def as_context_candidates(self) -> tuple[ContextCandidate, ...]:
        checkpoint_kinds = {
            MemoryItemKind.CHECKPOINT,
            MemoryItemKind.BLOCKER,
            MemoryItemKind.DECISION,
        }
        checkpoints = tuple(
            ContextObject(item.item_id, item.as_payload())
            for item in self.items
            if item.kind in checkpoint_kinds
        )
        working = tuple(
            ContextObject(item.item_id, item.as_payload())
            for item in self.items
            if item.kind not in checkpoint_kinds
        )
        candidates: list[ContextCandidate] = []
        if checkpoints:
            candidates.append(ContextCandidate(ContextKind.CHECKPOINT, checkpoints))
        if working:
            candidates.append(ContextCandidate(ContextKind.WORKING_MEMORY, working))
        return tuple(candidates)


def _bounded_payload(payload: Mapping[str, Any], limit: int) -> dict[str, Any]:
    normalized = json.loads(json.dumps(dict(payload), ensure_ascii=False, default=str))
    limit = max(2, int(limit))
    out: dict[str, Any] = {}
    encode = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    for raw_key, value in normalized.items():
        key = str(raw_key)
        candidate = {**out, key: value}
        if len(encode(candidate)) <= limit:
            out = candidate
            continue
        if not isinstance(value, str) or len(encode({**out, key: ""})) > limit:
            continue
        low, high = 0, len(value)
        while low < high:
            middle = (low + high + 1) // 2
            if len(encode({**out, key: value[:middle]})) <= limit:
                low = middle
            else:
                high = middle - 1
        out[key] = value[:low]
    return out


def _memory_cursor(session_id: str, items: Sequence[MemoryItem]) -> str:
    digest = hashlib.sha256("|".join(item.item_id for item in items).encode("utf-8")).hexdigest()[:20]
    return f"memory:{session_id or 'anonymous'}:{digest}"


def project_memory_from_records(
    *,
    session_id: str,
    project_id: int | None,
    dataset_ids: Sequence[str],
    chat_profile: Mapping[str, Any],
    dialogue: Sequence[Mapping[str, Any]],
    notes: Sequence[Mapping[str, Any]],
    traces: Sequence[Mapping[str, Any]],
    advisory_items: Sequence[Mapping[str, Any]],
    limits: MemoryLimits,
) -> MemoryProjection:
    items: list[MemoryItem] = []
    payload_limit = limits.max_payload_chars

    if chat_profile:
        checkpoint_payload = {
            key: chat_profile.get(key)
            for key in ("turn_count", "last_status", "mode", "last_question", "assumptions")
            if chat_profile.get(key) not in (None, "", [], ())
        }
        if checkpoint_payload:
            items.append(MemoryItem(
                item_id=f"chat-checkpoint:{session_id}",
                kind=MemoryItemKind.CHECKPOINT,
                payload=_bounded_payload(checkpoint_payload, payload_limit),
                revision_ref=None,
                project_id=project_id,
            ))
        for index, blocker in enumerate(list(chat_profile.get("blockers") or [])):
            items.append(MemoryItem(
                item_id=f"chat-blocker:{session_id}:{index}",
                kind=MemoryItemKind.BLOCKER,
                payload=_bounded_payload({"text": str(blocker)}, payload_limit),
                revision_ref=None,
                project_id=project_id,
            ))

    for trace_index, trace in enumerate(traces):
        decision = trace.get("decision_checkpoint")
        if isinstance(decision, Mapping):
            payload = decision.get("payload")
            if not isinstance(payload, Mapping):
                payload = {"status": decision.get("status")} if decision.get("status") else {}
            revision_ref = str(decision.get("revision_ref") or trace.get("revision_id") or "") or None
            items.append(MemoryItem(
                item_id=f"decision:{revision_ref or trace_index}",
                kind=MemoryItemKind.DECISION,
                payload=_bounded_payload(payload, payload_limit),
                revision_ref=revision_ref,
                project_id=project_id,
            ))

    for dataset_id in dataset_ids:
        normalized_id = str(dataset_id).strip()
        if normalized_id:
            items.append(MemoryItem(
                item_id=f"dataset-locator:{normalized_id}",
                kind=MemoryItemKind.EVIDENCE_LOCATOR,
                payload=_bounded_payload(
                    {"dataset_id": normalized_id, "role": "navigation_only"}, payload_limit
                ),
                revision_ref=None,
                project_id=project_id,
            ))

    for turn in list(dialogue)[-max(0, limits.max_dialogue_turns):]:
        turn_id = str(turn.get("turn_id") or len(items))
        items.append(MemoryItem(
            item_id=f"continuity:{turn_id}",
            kind=MemoryItemKind.CONTINUITY,
            payload=_bounded_payload(
                {"question": turn.get("question", ""), "answer": turn.get("answer", "")},
                payload_limit,
            ),
            revision_ref=None,
            project_id=project_id,
        ))

    allowed_projects = {0, int(project_id or 0)}
    for note in list(notes)[:max(0, limits.max_notes)]:
        note_project = int(note.get("project_id") or 0)
        if note_project not in allowed_projects:
            continue
        items.append(MemoryItem(
            item_id=f"note:{note.get('id')}",
            kind=MemoryItemKind.ADVISORY_FACT,
            payload=_bounded_payload(
                {"text": str(note.get("text") or ""), "source": "operator_note"},
                payload_limit,
            ),
            revision_ref=None,
            project_id=note_project or project_id,
        ))

    for index, advisory in enumerate(list(advisory_items)[:max(0, limits.max_advisory_items)]):
        advisory_project = int(advisory.get("project_id") or project_id or 0)
        if advisory_project not in allowed_projects:
            continue
        items.append(MemoryItem(
            item_id=str(advisory.get("item_id") or f"memory-port:{index}"),
            kind=MemoryItemKind.ADVISORY_FACT,
            payload=_bounded_payload(advisory.get("payload") or {}, payload_limit),
            revision_ref=str(advisory.get("revision_ref") or "") or None,
            project_id=advisory_project or None,
        ))

    max_items = max(0, int(limits.max_items))
    included = tuple(items[:max_items])
    omitted_items = tuple(items[max_items:])
    return MemoryProjection(
        session_id=session_id,
        project_id=project_id,
        items=included,
        omitted=len(omitted_items),
        cursor=_memory_cursor(session_id, omitted_items) if omitted_items else "",
    )


def project_memory(
    *,
    session_id: str,
    project_id: int | None,
    dataset_ids: Sequence[str],
    limits: MemoryLimits,
) -> MemoryProjection:
    """Adapt existing stores without copying prompt dumps into memory."""
    return project_memory_from_records(
        session_id=session_id,
        project_id=project_id,
        dataset_ids=dataset_ids,
        chat_profile=chat_memory_projection_record(session_id),
        dialogue=session_memory_items(session_id, max_turns=limits.max_dialogue_turns),
        notes=project_note_items(limit=limits.max_notes, project_id=project_id),
        traces=session_recent_retrieval_traces(session_id, max_turns=limits.max_dialogue_turns),
        advisory_items=(
            project_advisory_items(int(project_id), limit=limits.max_advisory_items)
            if project_id
            else []
        ),
        limits=limits,
    )
