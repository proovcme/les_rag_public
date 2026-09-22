"""Durable packet checkpoints for the active model-owned workbook path."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from proxy.config import META_DB_PATH
from proxy.services.lsr_source_coverage_service import inferred_row_role

SCHEMA = "les.workbook-research-job.v1"
TERMINAL_STATUSES = {"complete", "failed"}
RESUMABLE_STATUSES = {"running", "paused", "failed", "cancelled"}
_EXTRA_COLUMNS = {
    "remaining_json": "TEXT NOT NULL DEFAULT '[]'",
    "query_cache_json": "TEXT NOT NULL DEFAULT '{}'",
    "held_packet_json": "TEXT NOT NULL DEFAULT '{}'",
    "operator_overrides_json": "TEXT NOT NULL DEFAULT '{}'",
}


class WorkbookResearchJobError(ValueError):
    pass


def _decision_key(item: Mapping[str, Any]) -> tuple[str, str]:
    """One durable decision is a source locator plus its authored role."""

    locator = str(item.get("source_row") or "").strip()
    return locator, inferred_row_role(item) or "work"


_VOLATILE_DECISION_FIELDS = {"operation_id", "revision", "revision_origin", "content_sha256"}


def _decision_content_sha(item: Mapping[str, Any]) -> str:
    """Content fingerprint of one decision, ignoring identity/version bookkeeping."""

    core = {
        str(key): value
        for key, value in item.items()
        if str(key) not in _VOLATILE_DECISION_FIELDS
    }
    raw = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_operation_id() -> str:
    return f"op_{uuid4().hex[:16]}"


def _legacy_operation_id(job_id: str, item: Mapping[str, Any]) -> str:
    """Stable old-record -> new-identifier mapping (never by title guessing)."""

    core = {
        str(key): value
        for key, value in item.items()
        if str(key) not in _VOLATILE_DECISION_FIELDS
    }
    raw = json.dumps(
        {"job": str(job_id), "decision": core},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "op_leg_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


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
                    remaining_json TEXT NOT NULL DEFAULT '[]',
                    query_cache_json TEXT NOT NULL DEFAULT '{}',
                    held_packet_json TEXT NOT NULL DEFAULT '{}',
                    operator_overrides_json TEXT NOT NULL DEFAULT '{}',
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
                CREATE TABLE IF NOT EXISTS workbook_research_revisions (
                    job_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    origin TEXT NOT NULL,
                    base_revision INTEGER,
                    content_sha256 TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(job_id, operation_id, revision)
                );
                """
            )
            self._ensure_columns(conn)

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection) -> None:
        existing = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(workbook_research_jobs)")
        }
        for name, spec in _EXTRA_COLUMNS.items():
            if name not in existing:
                conn.execute(
                    f"ALTER TABLE workbook_research_jobs ADD COLUMN {name} {spec}"
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
        prior_elapsed = 0.0
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
                prior_elapsed = self.elapsed_seconds_between(
                    str(row["created_at"]), str(row["updated_at"])
                )
                status = str(row["status"])
                if status in RESUMABLE_STATUSES:
                    conn.execute(
                        """UPDATE workbook_research_jobs
                        SET status='running',cancel_requested=0,updated_at=CURRENT_TIMESTAMP
                        WHERE job_id=?""",
                        (job_id,),
                    )
                    self._append_event(
                        conn,
                        job_id,
                        "resumed",
                        {"from_status": status},
                    )
        job = self.get(job_id)
        job["prior_elapsed_seconds"] = prior_elapsed
        return job

    @staticmethod
    def elapsed_seconds_between(created_at: str, updated_at: str) -> float:
        """Wall time from SQLite timestamps before resume bumps updated_at."""

        def _parse(value: str) -> datetime | None:
            text = str(value or "").strip()
            if not text:
                return None
            try:
                return datetime.fromisoformat(text.replace(" ", "T"))
            except ValueError:
                return None

        start = _parse(created_at)
        end = _parse(updated_at)
        if start is None or end is None:
            return 0.0
        return max(0.0, (end - start).total_seconds())

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
        remaining: Sequence[str] = (),
        held_packet: Mapping[str, Any] | None = None,
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
            migrated = self._ensure_operation_ids(str(job_id), existing_rows)
            by_op: dict[str, dict[str, Any]] = {
                str(item["operation_id"]): item
                for item in existing_rows
                if isinstance(item, Mapping) and item.get("operation_id")
            }
            active_shas = {op: _decision_content_sha(item) for op, item in by_op.items()}
            new_revisions: list[tuple[str, int, str, dict[str, Any]]] = [
                (op, int(item.get("revision") or 1), "migration", item)
                for op, item in migrated
            ]
            for item in accepted_rows:
                if not isinstance(item, Mapping):
                    continue
                payload = dict(item)
                locator = str(payload.get("source_row") or "").strip()
                if not locator:
                    continue
                origin = str(payload.pop("revision_origin", "") or "model")
                op_id = str(payload.get("operation_id") or "").strip()
                if op_id and op_id in by_op:
                    sha = _decision_content_sha(payload)
                    if sha == active_shas.get(op_id):
                        continue
                    revision = int(by_op[op_id].get("revision") or 1) + 1
                    payload["operation_id"] = op_id
                    payload["revision"] = revision
                    by_op[op_id] = payload
                    active_shas[op_id] = sha
                    for pos, old in enumerate(existing_rows):
                        if (
                            isinstance(old, Mapping)
                            and str(old.get("operation_id") or "") == op_id
                        ):
                            existing_rows[pos] = payload
                            break
                    new_revisions.append((op_id, revision, origin, payload))
                    continue
                sha = _decision_content_sha(payload)
                if sha in active_shas.values():
                    # The identical result was delivered again; never duplicate it.
                    continue
                op_id = _new_operation_id()
                payload["operation_id"] = op_id
                payload["revision"] = 1
                existing_rows.append(payload)
                by_op[op_id] = payload
                active_shas[op_id] = sha
                new_revisions.append((op_id, 1, origin, payload))
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
            remaining_locators = [
                str(item) for item in remaining if str(item).strip()
            ]
            held_payload = dict(held_packet or {})
            for op_id, revision, origin, payload in new_revisions:
                self._insert_revision(conn, job_id, op_id, revision, origin, payload, None)
            conn.execute(
                """UPDATE workbook_research_jobs
                SET phase='packets',sheet_name=?,packet_json=?,accepted_rows_json=?,
                    evidence_json=?,omitted_json=?,remaining_json=?,held_packet_json=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE job_id=?""",
                (
                    str(sheet),
                    json.dumps(packet, ensure_ascii=False),
                    json.dumps(existing_rows, ensure_ascii=False),
                    json.dumps(existing_evidence, ensure_ascii=False),
                    json.dumps(existing_omitted, ensure_ascii=False),
                    json.dumps(remaining_locators, ensure_ascii=False),
                    json.dumps(held_payload, ensure_ascii=False),
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
                    "remaining_total": len(remaining_locators),
                    "held_queries": len(held_payload.get("queries") or []),
                    "new_revisions": len(new_revisions),
                },
            )
        return self.get(job_id)

    @staticmethod
    def _ensure_operation_ids(
        job_id: str, rows: list[Any]
    ) -> list[tuple[str, dict[str, Any]]]:
        """Assign missing operation ids in place; returns newly created (op, row).

        Legacy records map deterministically by content, so re-running the
        migration on unchanged rows produces the same identifiers.
        """

        created: list[tuple[str, dict[str, Any]]] = []
        seen: set[str] = set()
        for pos, raw in enumerate(rows):
            if not isinstance(raw, Mapping):
                continue
            item = raw if isinstance(raw, dict) else dict(raw)
            if not isinstance(raw, dict):
                rows[pos] = item
            op = str(item.get("operation_id") or "").strip()
            if not op:
                op = _legacy_operation_id(job_id, item)
                if op in seen:
                    op = _new_operation_id()
                item["operation_id"] = op
                item["revision"] = 1
                created.append((op, item))
            elif "revision" not in item:
                item["revision"] = 1
            seen.add(op)
        return created

    @staticmethod
    def _insert_revision(
        conn: sqlite3.Connection,
        job_id: str,
        operation_id: str,
        revision: int,
        origin: str,
        decision: Mapping[str, Any],
        base_revision: int | None,
    ) -> None:
        conn.execute(
            """INSERT OR IGNORE INTO workbook_research_revisions
            (job_id,operation_id,revision,origin,base_revision,content_sha256,decision_json)
            VALUES (?,?,?,?,?,?,?)""",
            (
                str(job_id),
                str(operation_id),
                int(revision),
                str(origin or "model"),
                None if base_revision is None else int(base_revision),
                _decision_content_sha(decision),
                json.dumps(dict(decision), ensure_ascii=False, default=str),
            ),
        )

    def record_search_cache(
        self,
        job_id: str,
        query_hits: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        context: Mapping[str, Any] | None = None,
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
            cache = json.loads(str(row["query_cache_json"] or "{}"))
            if not isinstance(cache, dict):
                cache = {}
            added = 0
            for query, hits in query_hits.items():
                key = str(query or "").strip()
                if not key or key in cache:
                    continue
                cache[key] = [dict(item) for item in hits if isinstance(item, Mapping)]
                added += 1
            conn.execute(
                """UPDATE workbook_research_jobs
                SET query_cache_json=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
                (json.dumps(cache, ensure_ascii=False), job_id),
            )
            if added:
                payload: dict[str, Any] = {"added": added, "cached_total": len(cache)}
                for key in ("sheet", "packet_id", "locators", "queries"):
                    value = dict(context or {}).get(key)
                    if isinstance(value, (list, tuple)):
                        value = list(value)
                    if value:
                        payload[key] = value
                self._append_event(conn, job_id, "search_cache", payload)
        return self.get(job_id)

    def record_overrides(
        self,
        job_id: str,
        overlays: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        from proxy.services.lsr_source_coverage_service import _CONFIRMED_KEYS

        payload = overlays if isinstance(overlays, Mapping) else {}
        cleaned: dict[str, dict[str, Any]] = {}
        for locator, patch in payload.items():
            key = str(locator or "").strip()
            if not key or not isinstance(patch, Mapping):
                continue
            item = {
                field: patch[field]
                for field in _CONFIRMED_KEYS
                if field in patch and patch.get(field) not in (None, "")
            }
            item.pop("norm_code", None)
            if item:
                cleaned[key] = item
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise WorkbookResearchJobError("workbook research job not found")
            existing = _json_object(row, "operator_overrides_json")
            for key, item in cleaned.items():
                current = dict(existing.get(key) or {})
                current.update(item)
                existing[key] = current
            conn.execute(
                """UPDATE workbook_research_jobs
                SET operator_overrides_json=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
                (json.dumps(existing, ensure_ascii=False), job_id),
            )
            self._append_event(
                conn,
                job_id,
                "operator_overrides",
                {"locators": sorted(cleaned)},
            )
        return self.get(job_id)

    def replace_accepted_rows(
        self,
        job_id: str,
        rows: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Overwrite listed decisions only, as a new revision. Does not invent a cipher."""

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise WorkbookResearchJobError("workbook research job not found")
            existing_rows = json.loads(str(row["accepted_rows_json"]))
            self._ensure_operation_ids(str(job_id), existing_rows)
            index_by_op: dict[str, int] = {}
            index_by_key: dict[tuple[str, str], int] = {}
            for pos, item in enumerate(existing_rows):
                if not isinstance(item, Mapping):
                    continue
                op = str(item.get("operation_id") or "").strip()
                if op:
                    index_by_op[op] = pos
                key = _decision_key(item)
                if key[0]:
                    index_by_key.setdefault(key, pos)
            replaced = 0
            for item in rows:
                if not isinstance(item, Mapping):
                    continue
                payload = dict(item)
                op = str(payload.get("operation_id") or "").strip()
                pos = index_by_op.get(op) if op else None
                if pos is None:
                    key = _decision_key(payload)
                    pos = index_by_key.get(key) if key[0] else None
                if pos is None:
                    continue
                current = existing_rows[pos]
                op = str(op or current.get("operation_id") or "")
                keep_code = current.get("norm_code")
                if "norm_code" not in payload or payload.get("norm_code") in (None, ""):
                    payload["norm_code"] = keep_code
                if not op:
                    # Pre-migration duplicate that could not carry an id: assign one now.
                    op = _new_operation_id()
                if _decision_content_sha(payload) == _decision_content_sha(current):
                    payload["operation_id"] = op
                    payload["revision"] = int(current.get("revision") or 1)
                    existing_rows[pos] = payload
                    index_by_op[op] = pos
                    continue
                revision = int(current.get("revision") or 1) + 1
                payload["operation_id"] = op
                payload["revision"] = revision
                existing_rows[pos] = payload
                index_by_op[op] = pos
                self._insert_revision(
                    conn, job_id, op, revision, "operator", payload, revision - 1
                )
                replaced += 1
            conn.execute(
                """UPDATE workbook_research_jobs
                SET accepted_rows_json=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
                (json.dumps(existing_rows, ensure_ascii=False), job_id),
            )
            self._append_event(
                conn, job_id, "rows_replaced", {"replaced": replaced}
            )
        return self.get(job_id)

    def record_revision(
        self,
        job_id: str,
        *,
        operation_id: str,
        decision: Mapping[str, Any],
        origin: str = "operator",
        base_revision: int | None = None,
    ) -> dict[str, Any]:
        """Append one revision of an existing operation.

        ``base_revision`` guards a late request against overwriting a newer
        revision; a mismatch is rejected instead of silently clobbering.
        """

        op = str(operation_id or "").strip()
        if not op:
            raise WorkbookResearchJobError("operation_id is required")
        payload = dict(decision)
        origin_text = str(payload.pop("revision_origin", "") or origin or "operator")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise WorkbookResearchJobError("workbook research job not found")
            existing_rows = json.loads(str(row["accepted_rows_json"]))
            self._ensure_operation_ids(str(job_id), existing_rows)
            pos = next(
                (
                    index
                    for index, item in enumerate(existing_rows)
                    if isinstance(item, Mapping)
                    and str(item.get("operation_id") or "") == op
                ),
                None,
            )
            if pos is None:
                raise WorkbookResearchJobError(f"unknown operation_id {op}")
            current = existing_rows[pos]
            revision = int(current.get("revision") or 1)
            if base_revision is not None and int(base_revision) != revision:
                raise WorkbookResearchJobError(
                    f"stale revision for {op}: base={int(base_revision)} current={revision}"
                )
            payload["operation_id"] = op
            payload["revision"] = revision + 1
            existing_rows[pos] = payload
            conn.execute(
                """UPDATE workbook_research_jobs
                SET accepted_rows_json=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
                (json.dumps(existing_rows, ensure_ascii=False), job_id),
            )
            self._insert_revision(
                conn, job_id, op, revision + 1, origin_text, payload, revision
            )
            self._append_event(
                conn,
                job_id,
                "decision_revision",
                {"operation_id": op, "revision": revision + 1, "origin": origin_text},
            )
        return self.get(job_id)

    def list_revisions(
        self, job_id: str, operation_id: str = ""
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if operation_id:
                rows = conn.execute(
                    """SELECT * FROM workbook_research_revisions
                    WHERE job_id=? AND operation_id=? ORDER BY revision""",
                    (str(job_id), str(operation_id)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM workbook_research_revisions
                    WHERE job_id=? ORDER BY operation_id, revision""",
                    (str(job_id),),
                ).fetchall()
        return [
            {
                "operation_id": str(item["operation_id"]),
                "revision": int(item["revision"]),
                "origin": str(item["origin"]),
                "base_revision": item["base_revision"],
                "content_sha256": str(item["content_sha256"]),
                "created_at": str(item["created_at"]),
                "decision": json.loads(str(item["decision_json"])),
            }
            for item in rows
        ]

    def reopen_locators(
        self,
        job_id: str,
        locators: Sequence[str],
    ) -> dict[str, Any]:
        """Remove listed rows from accepted decisions and return them to remaining."""

        wanted = [str(item).strip() for item in locators if str(item).strip()]
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise WorkbookResearchJobError("workbook research job not found")
            existing_rows = json.loads(str(row["accepted_rows_json"]))
            kept = [
                item
                for item in existing_rows
                if str(item.get("source_row") or "") not in wanted
            ]
            remaining = _json_list(row, "remaining_json")
            for locator in wanted:
                if locator not in remaining:
                    remaining.append(locator)
            overlays = _json_object(row, "operator_overrides_json")
            for locator in wanted:
                overlays.pop(locator, None)
            conn.execute(
                """UPDATE workbook_research_jobs
                SET status='paused',phase='refine',accepted_rows_json=?,remaining_json=?,
                    operator_overrides_json=?,cancel_requested=0,updated_at=CURRENT_TIMESTAMP
                WHERE job_id=?""",
                (
                    json.dumps(kept, ensure_ascii=False),
                    json.dumps(remaining, ensure_ascii=False),
                    json.dumps(overlays, ensure_ascii=False),
                    job_id,
                ),
            )
            self._append_event(
                conn,
                job_id,
                "locators_reopened",
                {"locators": wanted, "accepted_total": len(kept)},
            )
        return self.get(job_id)

    def pause(
        self,
        job_id: str,
        *,
        remaining: Sequence[str] | None = None,
        held_packet: Mapping[str, Any] | None = None,
        phase: str = "paused",
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
            remaining_locators = (
                [str(item) for item in remaining if str(item).strip()]
                if remaining is not None
                else _json_list(row, "remaining_json")
            )
            held_payload = (
                dict(held_packet)
                if held_packet is not None
                else _json_object(row, "held_packet_json")
            )
            conn.execute(
                """UPDATE workbook_research_jobs
                SET status='paused',phase=?,cancel_requested=0,remaining_json=?,
                    held_packet_json=?,updated_at=CURRENT_TIMESTAMP
                WHERE job_id=?""",
                (
                    str(phase),
                    json.dumps(remaining_locators, ensure_ascii=False),
                    json.dumps(held_payload, ensure_ascii=False),
                    job_id,
                ),
            )
            self._append_event(
                conn,
                job_id,
                "paused",
                {
                    "remaining_total": len(remaining_locators),
                    "held_queries": len(held_payload.get("queries") or []),
                },
            )
        return self.get(job_id)

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            changed = conn.execute(
                """UPDATE workbook_research_jobs
                SET cancel_requested=1,updated_at=CURRENT_TIMESTAMP
                WHERE job_id=? AND status NOT IN ('complete','failed')""",
                (job_id,),
            ).rowcount
            if changed:
                self._append_event(conn, job_id, "cancel_requested", {})
        return self.get(job_id)

    def should_cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if bool(job.get("cancel_requested")):
            return True
        return str(job.get("status") or "") in {"paused", "cancelled"}

    def finish(self, job_id: str, *, status: str, phase: str = "complete") -> dict[str, Any]:
        if status == "cancelled":
            return self.pause(job_id, phase="cancelled")
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

    def list_active(
        self,
        *,
        session_id: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Running sheet-pass checkpoints, newest first.

        Session match is preferred after a UI restart; if the NiceGUI session
        was regenerated, the newest running job is still returned so overnight
        progress is not blank.
        """

        limit_n = max(1, min(int(limit or 20), 100))
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM workbook_research_jobs
                   WHERE status='running'
                   ORDER BY updated_at DESC
                   LIMIT ?""",
                (limit_n,),
            ).fetchall()
        jobs = [self._row(row) for row in rows]
        sid = str(session_id or "").strip()
        if not sid:
            return jobs
        matched = [
            job
            for job in jobs
            if str((job.get("identity") or {}).get("session_id") or "") == sid
        ]
        return matched or jobs

    def list_open(
        self,
        *,
        session_id: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Running sheet-pass first; paused draft of the same session otherwise."""

        limit_n = max(1, min(int(limit or 20), 100))
        sid = str(session_id or "").strip()
        with self._connect() as conn:

            def _fetch(status: str, session: str) -> list[dict[str, Any]]:
                if session:
                    rows = conn.execute(
                        """SELECT * FROM workbook_research_jobs
                           WHERE status=? AND json_extract(identity_json,'$.session_id')=?
                           ORDER BY updated_at DESC LIMIT ?""",
                        (status, session, limit_n),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT * FROM workbook_research_jobs
                           WHERE status=? ORDER BY updated_at DESC LIMIT ?""",
                        (status, limit_n),
                    ).fetchall()
                return [self._row(row) for row in rows]

            running = _fetch("running", sid)
            if running:
                return running
            paused = _fetch("paused", sid)
            if paused:
                return paused
        return self.list_active(session_id=session_id, limit=limit)

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
        remaining = _json_list(row, "remaining_json")
        query_cache = _json_object(row, "query_cache_json")
        held_packet = _json_object(row, "held_packet_json")
        operator_overrides = _json_object(row, "operator_overrides_json")
        identity = json.loads(str(row["identity_json"] or "{}"))
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
            "remaining": remaining,
            "query_cache": query_cache,
            "held_packet": held_packet,
            "operator_overrides": operator_overrides,
            "identity": identity if isinstance(identity, dict) else {},
            "resumable": status in RESUMABLE_STATUSES and status != "failed",
            "status_dimensions": {
                "processed": len(accepted_rows),
                "omitted": len(omitted),
                "ambiguous": ambiguous,
                "missing": missing,
                "remaining": len(remaining),
                "cached_queries": len(query_cache),
                "operations": len(
                    {
                        str(item.get("operation_id"))
                        for item in accepted_rows
                        if isinstance(item, Mapping) and item.get("operation_id")
                    }
                ),
                "completeness": (
                    "full"
                    if status == "complete" and not omitted and not remaining
                    else "partial"
                ),
            },
            "cancel_requested": bool(row["cancel_requested"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }


def _json_list(row: sqlite3.Row, name: str) -> list[Any]:
    try:
        payload = json.loads(str(row[name] or "[]"))
    except (KeyError, json.JSONDecodeError, TypeError):
        return []
    return list(payload) if isinstance(payload, list) else []


def _json_object(row: sqlite3.Row, name: str) -> dict[str, Any]:
    try:
        payload = json.loads(str(row[name] or "{}"))
    except (KeyError, json.JSONDecodeError, TypeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}
