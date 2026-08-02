"""Typed contracts for the isolated LES Memory Core v1.

Memory records are advisory state with explicit provenance.  They are never
current-request evidence and never own an estimating decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryMode(str, Enum):
    OFF = "off"
    SHADOW = "shadow"
    ON = "on"


class SmetaRecallMode(str, Enum):
    OFF = "off"
    ADVISORY = "advisory"
    ROUTE_REUSE = "route_reuse"


class SmetaTraceTrust(str, Enum):
    CANDIDATE = "candidate"
    ACCEPTED_PROJECT = "accepted_project"
    VERIFIED_PATTERN = "verified_pattern"
    REJECTED = "rejected"


class EntryKind(str, Enum):
    ASSERTION = "assertion"
    VERIFIED_TRACE = "verified_trace"
    QUERY_PATTERN = "query_pattern"
    SMETA_SUCCESS_TRACE = "smeta_success_trace"


class ValidationStatus(str, Enum):
    CONFIRMED = "confirmed"
    CANDIDATE = "candidate"
    REJECTED = "rejected"
    DISPUTED = "disputed"


class QueueStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class EvidenceRef:
    ref_id: str
    doc_id: str
    locator: str = ""
    source_revision: str = ""
    is_evidence: bool = True
    snippet_sha256: str = ""


@dataclass
class MemoryEntry:
    entry_id: str
    project_id: int
    kind: EntryKind
    subject: str
    predicate: str
    value: Any
    validation_status: ValidationStatus = ValidationStatus.CANDIDATE
    provenance: dict[str, Any] = field(default_factory=dict)
    valid_from: str = ""
    valid_to: str = ""
    source_version: str = ""
    human_verified: bool = False
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class RouteEvidenceCacheDTO:
    cache_id: str
    family: str
    collection: str
    section: str
    table_code: str
    knowledge_edition: str
    source_revision: str
    work_signature: str
    source: str = "typed_catalog_trace"
    decision_owner: str = "model"
    applicability: str = "not_decided_for_current_row"


@dataclass(frozen=True)
class SmetaSuccessTrace:
    trace_id: str
    project_id: int
    source_kind: str
    source_id: str
    revision_id: str
    source_sha256: str
    finality: str
    question_signature: str
    normalized_work_features: dict[str, Any]
    typed_catalog_routes: tuple[RouteEvidenceCacheDTO, ...]
    selected_norm_refs: tuple[str, ...]
    calculation_evidence_refs: tuple[str, ...]
    knowledge_edition_identity: str
    trust_level: SmetaTraceTrust = SmetaTraceTrust.CANDIDATE
    reviewed_at: str = ""
    review_note: str = ""
    created_at: str = field(default_factory=utc_now)
