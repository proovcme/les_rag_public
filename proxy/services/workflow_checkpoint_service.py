"""Durable idempotent checkpoints for long-running tool workflows."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping
from uuid import uuid4


class CheckpointError(ValueError):
    pass


class CheckpointConflict(CheckpointError):
    pass


@dataclass(frozen=True)
class CheckpointBeginRequest:
    session_id: str
    idempotency_key: str
    tool_name: str
    attachment_id: str
    attachment_sha256: str
    normalized_args: Mapping[str, Any]
    model_decision_revision: str


@dataclass(frozen=True)
class WorkflowCheckpoint:
    checkpoint_id: str
    tool_name: str
    attachment_id: str
    attachment_sha256: str
    normalized_args_sha256: str
    model_decision_revision: str
    phase: str
    completed_items: int
    total_items: int | None
    status: Literal["running", "blocked", "failed", "complete"]
    artifact_revision_id: str | None
    missing: tuple[str, ...]
    blockers: tuple[str, ...]


def _normalized_args(args: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(args)
    if value.get("dataset_ids") is None:
        value["dataset_ids"] = []
    return value


def _args_hash(args: Mapping[str, Any]) -> str:
    raw = json.dumps(_normalized_args(args), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class WorkflowCheckpointService:
    def __init__(self, db_path: Path, *, max_status_items: int = 100):
        self.db_path = Path(db_path)
        self.max_status_items = max(1, int(max_status_items))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL, tool_name TEXT NOT NULL,
                    attachment_id TEXT NOT NULL, attachment_sha256 TEXT NOT NULL,
                    normalized_args_sha256 TEXT NOT NULL, model_decision_revision TEXT NOT NULL,
                    phase TEXT NOT NULL, completed_items INTEGER NOT NULL,
                    total_items INTEGER, status TEXT NOT NULL, artifact_revision_id TEXT,
                    missing_json TEXT NOT NULL, blockers_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(session_id, idempotency_key)
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _validate_begin(request: CheckpointBeginRequest) -> None:
        required = (request.session_id, request.idempotency_key, request.tool_name,
                    request.attachment_id, request.attachment_sha256,
                    request.model_decision_revision)
        if any(not str(item).strip() for item in required):
            raise CheckpointError("checkpoint identity is incomplete")
        if len(request.attachment_sha256) != 64:
            raise CheckpointError("attachment hash is invalid")

    def begin_or_resume(self, request: CheckpointBeginRequest) -> WorkflowCheckpoint:
        self._validate_begin(request)
        args_sha = _args_hash(request.normalized_args)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM workflow_checkpoints WHERE session_id=? AND idempotency_key=?",
                (request.session_id, request.idempotency_key),
            ).fetchone()
            if row is not None:
                checks = (
                    ("tool", row["tool_name"], request.tool_name),
                    ("attachment", row["attachment_id"], request.attachment_id),
                    ("attachment hash", row["attachment_sha256"], request.attachment_sha256),
                    ("arguments", row["normalized_args_sha256"], args_sha),
                    ("model decision", row["model_decision_revision"], request.model_decision_revision),
                )
                for label, existing, requested in checks:
                    if existing != requested:
                        raise CheckpointConflict(f"idempotency key changed {label}")
                return self._from_row(row)
            checkpoint_id = f"cp_{uuid4().hex}"
            conn.execute(
                """INSERT INTO workflow_checkpoints
                (checkpoint_id,session_id,idempotency_key,tool_name,attachment_id,
                 attachment_sha256,normalized_args_sha256,model_decision_revision,
                 phase,completed_items,total_items,status,artifact_revision_id,missing_json,blockers_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (checkpoint_id, request.session_id, request.idempotency_key, request.tool_name,
                 request.attachment_id, request.attachment_sha256, args_sha,
                 request.model_decision_revision, "started", 0, None, "running", None, "[]", "[]"),
            )
        return self.get(checkpoint_id)

    def get(self, checkpoint_id: str) -> WorkflowCheckpoint:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM workflow_checkpoints WHERE checkpoint_id=?", (checkpoint_id,)).fetchone()
        if row is None:
            raise CheckpointError("checkpoint not found")
        return self._from_row(row)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> WorkflowCheckpoint:
        return WorkflowCheckpoint(
            checkpoint_id=row["checkpoint_id"], tool_name=row["tool_name"],
            attachment_id=row["attachment_id"], attachment_sha256=row["attachment_sha256"],
            normalized_args_sha256=row["normalized_args_sha256"],
            model_decision_revision=row["model_decision_revision"], phase=row["phase"],
            completed_items=int(row["completed_items"]), total_items=row["total_items"],
            status=row["status"], artifact_revision_id=row["artifact_revision_id"],
            missing=tuple(json.loads(row["missing_json"])),
            blockers=tuple(json.loads(row["blockers_json"])),
        )

    def record_progress(self, checkpoint_id: str, *, phase: str, completed: int, total: int | None) -> WorkflowCheckpoint:
        if completed < 0 or (total is not None and (total < 0 or completed > total)):
            raise CheckpointError("invalid progress")
        with self._connect() as conn:
            changed = conn.execute(
                """UPDATE workflow_checkpoints SET phase=?,completed_items=?,total_items=?,
                   status='running',updated_at=CURRENT_TIMESTAMP WHERE checkpoint_id=? AND status!='complete'""",
                (phase, completed, total, checkpoint_id),
            ).rowcount
        if not changed:
            raise CheckpointError("checkpoint not found or complete")
        return self.get(checkpoint_id)

    def record_status(self, checkpoint_id: str, *, status: Literal["running", "blocked", "failed"],
                      missing: tuple[str, ...] = (), blockers: tuple[str, ...] = ()) -> WorkflowCheckpoint:
        if status not in {"running", "blocked", "failed"}:
            raise CheckpointError("invalid checkpoint status")
        bounded_missing = tuple(str(x) for x in missing[: self.max_status_items])
        bounded_blockers = tuple(str(x) for x in blockers[: self.max_status_items])
        with self._connect() as conn:
            changed = conn.execute(
                """UPDATE workflow_checkpoints SET status=?,missing_json=?,blockers_json=?,
                   updated_at=CURRENT_TIMESTAMP WHERE checkpoint_id=? AND status!='complete'""",
                (status, json.dumps(bounded_missing, ensure_ascii=False),
                 json.dumps(bounded_blockers, ensure_ascii=False), checkpoint_id),
            ).rowcount
        if not changed:
            raise CheckpointError("checkpoint not found or complete")
        return self.get(checkpoint_id)

    def complete(self, checkpoint_id: str, artifact_revision_id: str) -> WorkflowCheckpoint:
        if not artifact_revision_id:
            raise CheckpointError("artifact revision is required")
        with self._connect() as conn:
            changed = conn.execute(
                """UPDATE workflow_checkpoints SET status='complete',artifact_revision_id=?,
                   updated_at=CURRENT_TIMESTAMP WHERE checkpoint_id=? AND status!='complete'""",
                (artifact_revision_id, checkpoint_id),
            ).rowcount
        if not changed:
            existing = self.get(checkpoint_id)
            if existing.status == "complete" and existing.artifact_revision_id == artifact_revision_id:
                return existing
            raise CheckpointConflict("checkpoint already completed with another artifact")
        return self.get(checkpoint_id)
