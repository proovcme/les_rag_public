"""Durable packet checkpoints for the active model-owned workbook path."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from proxy.config import META_DB_PATH

SCHEMA = "les.workbook-research-job.v1"
TERMINAL_STATUSES = {"complete", "failed", "cancelled"}


class WorkbookResearchJobError(ValueError):
    pass


@dataclass(frozen=True)
class WorkbookResearchIdentity:
    session_id: str
    attachment_id: str
    source_sha256: str
    dataset_ids: tuple[str, ...]
    profile_revision_id: str
    model_identity: str
    question_sha256: str

    def digest(self) -> str:
        payload = {
            "session_id": self.session_id,
            "attachment_id": self.attachment_id,
            "source_sha256": self.source_sha256,
            "dataset_ids": sorted(self.dataset_ids),
            "profile_revision_id": self.profile_revision_id,
            "model_identity": self.model_identity,
            "question_sha256": self.question_sha256,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class WorkbookResearchJobService:
    def __init__(self, db_path: Path | str = META_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workbook_research_jobs (
                    job_id TEXT PRIMARY KEY,
                    identity_hash TEXT NOT NULL UNIQUE,
                    identity_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    sheet_name TEXT NOT NULL DEFAULT '',
                    packet_json TEXT NOT NULL DEFAULT '[]',
                    accepted_rows_json TEXT NOT NULL DEFAULT '[]',
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    omitted_json TEXT NOT NULL DEFAULT '[]',
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS workbook_research_events (
                    job_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(job_id, sequence)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @staticmethod
    def identity(
        *,
        session_id: str,
        attachment_id: str,
        source_sha256: str,
        dataset_ids: Sequence[str],
        profile_revision_id: str,
        model_identity: str,
        question: str,
    ) -> WorkbookResearchIdentity:
        if not session_id or not attachment_id or len(source_sha256) != 64:
            raise WorkbookResearchJobError("durable workbook identity is incomplete")
        return WorkbookResearchIdentity(
            session_id=str(session_id),
            attachment_id=str(attachment_id),
            source_sha256=str(source_sha256),
            dataset_ids=tuple(sorted(str(item) for item in dataset_ids if str(item))),
            profile_revision_id=str(profile_revision_id or "factory"),
            model_identity=str(model_identity or "unknown"),
            question_sha256=hashlib.sha256(str(question).encode("utf-8")).hexdigest(),
        )

    def begin_or_resume(self, identity: WorkbookResearchIdentity) -> dict[str, Any]:
        digest = identity.digest()
        identity_json = json.dumps(identity.__dict__, ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE identity_hash=?", (digest,)
            ).fetchone()
            if row is None:
                job_id = f"wrj_{uuid4().hex}"
                conn.execute(
                    """INSERT INTO workbook_research_jobs
                    (job_id,identity_hash,identity_json,status,phase)
                    VALUES (?,?,?,'running','catalog')""",
                    (job_id, digest, identity_json),
                )
                self._append_event(conn, job_id, "started", {"schema": SCHEMA})
            else:
                job_id = str(row["job_id"])
                if str(row["identity_json"]) != identity_json:
                    raise WorkbookResearchJobError("identity hash collision")
                if str(row["status"]) not in {"complete", "cancelled"}:
                    conn.execute(
                        """UPDATE workbook_research_jobs
                        SET status='running',cancel_requested=0,updated_at=CURRENT_TIMESTAMP
                        WHERE job_id=?""",
                        (job_id,),
                    )
                    self._append_event(conn, job_id, "resumed", {})
        return self.get(job_id)

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        job_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM workbook_research_events WHERE job_id=?",
            (job_id,),
        ).fetchone()
        sequence = int(row[0])
        conn.execute(
            """INSERT INTO workbook_research_events
            (job_id,sequence,event_type,payload_json) VALUES (?,?,?,?)""",
            (job_id, sequence, event_type, json.dumps(dict(payload), ensure_ascii=False)),
        )
        return sequence

    def record_packet(
        self,
        job_id: str,
        *,
        sheet: str,
        packet_locators: Sequence[str],
        accepted_rows: Sequence[Mapping[str, Any]],
        evidence: Sequence[Mapping[str, Any]],
        omitted: Sequence[str] = (),
    ) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise WorkbookResearchJobError("workbook research job not found")
            if str(row["status"]) in TERMINAL_STATUSES:
                return self._row(row)
            existing_rows = json.loads(str(row["accepted_rows_json"]))
            seen = {str(item.get("source_row") or "") for item in existing_rows}
            for item in accepted_rows:
                payload = dict(item)
                key = str(payload.get("source_row") or "")
                if key and key not in seen:
                    existing_rows.append(payload)
                    seen.add(key)
            existing_evidence = json.loads(str(row["evidence_json"]))
            evidence_ids = {
                str(item.get("global_evidence_id") or "") for item in existing_evidence
            }
            for item in evidence:
                payload = dict(item)
                key = str(payload.get("global_evidence_id") or "")
                if key and key not in evidence_ids:
                    existing_evidence.append(payload)
                    evidence_ids.add(key)
            existing_omitted = list(json.loads(str(row["omitted_json"])))
            existing_omitted.extend(
                item for item in map(str, omitted) if item not in existing_omitted
            )
            packet = [str(item) for item in packet_locators]
            conn.execute(
                """UPDATE workbook_research_jobs
                SET phase='packets',sheet_name=?,packet_json=?,accepted_rows_json=?,
                    evidence_json=?,omitted_json=?,updated_at=CURRENT_TIMESTAMP
                WHERE job_id=?""",
                (
                    str(sheet),
                    json.dumps(packet, ensure_ascii=False),
                    json.dumps(existing_rows, ensure_ascii=False),
                    json.dumps(existing_evidence, ensure_ascii=False),
                    json.dumps(existing_omitted, ensure_ascii=False),
                    job_id,
                ),
            )
            self._append_event(
                conn,
                job_id,
                "packet_checkpoint",
                {
                    "sheet": str(sheet),
                    "packet_locators": packet,
                    "accepted_total": len(existing_rows),
                    "omitted_total": len(existing_omitted),
                },
            )
        return self.get(job_id)

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            changed = conn.execute(
                """UPDATE workbook_research_jobs
                SET cancel_requested=1,updated_at=CURRENT_TIMESTAMP
                WHERE job_id=? AND status NOT IN ('complete','failed','cancelled')""",
                (job_id,),
            ).rowcount
            if changed:
                self._append_event(conn, job_id, "cancel_requested", {})
        return self.get(job_id)

    def should_cancel(self, job_id: str) -> bool:
        return bool(self.get(job_id).get("cancel_requested"))

    def finish(self, job_id: str, *, status: str, phase: str = "complete") -> dict[str, Any]:
        if status not in TERMINAL_STATUSES:
            raise WorkbookResearchJobError("invalid terminal status")
        with self._connect() as conn:
            changed = conn.execute(
                """UPDATE workbook_research_jobs
                SET status=?,phase=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
                (status, str(phase), job_id),
            ).rowcount
            if not changed:
                raise WorkbookResearchJobError("workbook research job not found")
            self._append_event(conn, job_id, status, {"phase": str(phase)})
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (str(job_id),)
            ).fetchone()
        if row is None:
            raise WorkbookResearchJobError("workbook research job not found")
        return self._row(row)

    def events_after(self, job_id: str, sequence: int = 0) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT sequence,event_type,payload_json,created_at
                FROM workbook_research_events
                WHERE job_id=? AND sequence>? ORDER BY sequence""",
                (str(job_id), max(0, int(sequence))),
            ).fetchall()
        return [
            {
                "sequence": int(row["sequence"]),
                "event": str(row["event_type"]),
                "data": json.loads(str(row["payload_json"])),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        accepted_rows = json.loads(str(row["accepted_rows_json"]))
        omitted = json.loads(str(row["omitted_json"]))
        missing = sum(
            1
            for item in accepted_rows
            if not str(item.get("norm_code") or "").strip()
            or str(item.get("norm_code") or "").strip().casefold()
            in {"missing", "нет", "не найдено"}
        )
        ambiguous = sum(
            1
            for item in accepted_rows
            if str(item.get("row_classification") or "") == "ambiguous"
        )
        status = str(row["status"])
        return {
            "schema": SCHEMA,
            "job_id": str(row["job_id"]),
            "status": status,
            "phase": str(row["phase"]),
            "sheet": str(row["sheet_name"]),
            "packet_locators": json.loads(str(row["packet_json"])),
            "accepted_rows": accepted_rows,
            "evidence": json.loads(str(row["evidence_json"])),
            "omitted": omitted,
            "status_dimensions": {
                "processed": len(accepted_rows),
                "omitted": len(omitted),
                "ambiguous": ambiguous,
                "missing": missing,
                "completeness": (
                    "full" if status == "complete" and not omitted else "partial"
                ),
            },
            "cancel_requested": bool(row["cancel_requested"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
