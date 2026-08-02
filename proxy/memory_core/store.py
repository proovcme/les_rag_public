"""Durable MetaDB store for Memory Core v1.

The store is deliberately SQLite-only and project-partitioned.  It has no
dependency on RAG/Qdrant and does not initialize at module import time.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from proxy.config import META_DB_PATH
from proxy.memory_core.contracts import (
    EntryKind,
    EvidenceRef,
    MemoryEntry,
    QueueStatus,
    RouteEvidenceCacheDTO,
    SmetaSuccessTrace,
    SmetaTraceTrust,
    ValidationStatus,
    utc_now,
)


_NON_FACT_KINDS = {EntryKind.VERIFIED_TRACE, EntryKind.QUERY_PATTERN, EntryKind.SMETA_SUCCESS_TRACE}


class MemoryStore:
    def __init__(self, db_path: str | Path = META_DB_PATH):
        self.db_path = str(db_path)
        self._memory_connection: sqlite3.Connection | None = None
        if self.db_path == ":memory:":
            self._memory_connection = sqlite3.connect(":memory:", timeout=2.0, check_same_thread=False)
            self._memory_connection.row_factory = sqlite3.Row
            self._memory_connection.execute("PRAGMA foreign_keys=ON")
            self._memory_connection.execute("PRAGMA busy_timeout=2000")
        self._init_db()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._memory_connection or sqlite3.connect(self.db_path, timeout=2.0)
        if self._memory_connection is None:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=2000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if self._memory_connection is None:
                conn.close()

    def _init_db(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_entries (
                    entry_id TEXT PRIMARY KEY,
                    project_id INTEGER NOT NULL CHECK(project_id > 0),
                    scope_kind TEXT NOT NULL DEFAULT 'project' CHECK(scope_kind IN ('project','function','global')),
                    kind TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    validation_status TEXT NOT NULL,
                    provenance_json TEXT NOT NULL DEFAULT '{}',
                    valid_from TEXT NOT NULL DEFAULT '',
                    valid_to TEXT NOT NULL DEFAULT '',
                    source_version TEXT NOT NULL DEFAULT '',
                    human_verified INTEGER NOT NULL DEFAULT 0,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    last_used_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_entries_project
                    ON memory_entries(project_id, kind, validation_status, created_at DESC);

                CREATE TABLE IF NOT EXISTS memory_evidence_refs (
                    entry_id TEXT NOT NULL,
                    ref_id TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    locator TEXT NOT NULL DEFAULT '',
                    source_revision TEXT NOT NULL DEFAULT '',
                    is_evidence INTEGER NOT NULL DEFAULT 1,
                    snippet_sha256 TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(entry_id, ref_id),
                    FOREIGN KEY(entry_id) REFERENCES memory_entries(entry_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS memory_conflicts (
                    conflict_id TEXT PRIMARY KEY,
                    project_id INTEGER NOT NULL CHECK(project_id > 0),
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    entry_ids_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved')),
                    resolution_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_memory_conflicts_project
                    ON memory_conflicts(project_id, status, created_at DESC);

                CREATE TABLE IF NOT EXISTS memory_project_snapshots (
                    project_id INTEGER PRIMARY KEY CHECK(project_id > 0),
                    revision INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_ingest_queue (
                    job_id TEXT PRIMARY KEY,
                    project_id INTEGER NOT NULL CHECK(project_id > 0),
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_queue_ready
                    ON memory_ingest_queue(status, available_at, created_at);

                CREATE TABLE IF NOT EXISTS memory_smeta_traces (
                    trace_id TEXT PRIMARY KEY,
                    project_id INTEGER NOT NULL CHECK(project_id > 0),
                    source_kind TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    revision_id TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    finality TEXT NOT NULL CHECK(finality IN ('priced_draft','priced_final')),
                    question_signature TEXT NOT NULL,
                    normalized_work_features_json TEXT NOT NULL,
                    route_cache_json TEXT NOT NULL DEFAULT '[]',
                    selected_norm_refs_json TEXT NOT NULL DEFAULT '[]',
                    calculation_evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    knowledge_edition TEXT NOT NULL,
                    trust_level TEXT NOT NULL DEFAULT 'candidate',
                    reviewed_at TEXT NOT NULL DEFAULT '',
                    review_note TEXT NOT NULL DEFAULT '',
                    superseded_by_revision TEXT NOT NULL DEFAULT '',
                    stale INTEGER NOT NULL DEFAULT 0,
                    disputed INTEGER NOT NULL DEFAULT 0,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    last_used_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, source_kind, source_id, revision_id)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_smeta_project
                    ON memory_smeta_traces(project_id, stale, disputed, created_at DESC);

                CREATE TABLE IF NOT EXISTS memory_observer_cursors (
                    observer_name TEXT PRIMARY KEY,
                    last_processed_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            # Memory Core is additive beside the shared MetaDB.  Keep upgrades
            # idempotent for operators who already started the v1 shadow store.
            smeta_columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(memory_smeta_traces)")
            }
            for name, declaration in (
                ("trust_level", "TEXT NOT NULL DEFAULT 'candidate'"),
                ("reviewed_at", "TEXT NOT NULL DEFAULT ''"),
                ("review_note", "TEXT NOT NULL DEFAULT ''"),
                ("superseded_by_revision", "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in smeta_columns:
                    conn.execute(
                        f"ALTER TABLE memory_smeta_traces ADD COLUMN {name} {declaration}"
                    )

    @staticmethod
    def _require_project(project_id: int | str | None) -> int:
        try:
            value = int(project_id or 0)
        except (TypeError, ValueError) as error:
            raise ValueError("project_id must be a positive integer") from error
        if value <= 0:
            raise ValueError("project_id must be a positive integer")
        return value

    def insert_entry(self, entry: MemoryEntry, evidence_refs: list[EvidenceRef] | None = None) -> None:
        project_id = self._require_project(entry.project_id)
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO memory_entries
                (entry_id, project_id, scope_kind, kind, subject, predicate, value_json,
                 validation_status, provenance_json, valid_from, valid_to, source_version,
                 human_verified, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    entry.entry_id, project_id, "project", entry.kind.value, entry.subject,
                    entry.predicate, json.dumps(entry.value, ensure_ascii=False),
                    entry.validation_status.value, json.dumps(entry.provenance or {}, ensure_ascii=False),
                    entry.valid_from, entry.valid_to, entry.source_version,
                    int(entry.human_verified), entry.created_at, entry.updated_at,
                ),
            )
            for ref in evidence_refs or []:
                conn.execute(
                    """INSERT INTO memory_evidence_refs
                    (entry_id, ref_id, doc_id, locator, source_revision, is_evidence, snippet_sha256)
                    VALUES (?,?,?,?,?,?,?)""",
                    (
                        entry.entry_id, ref.ref_id, ref.doc_id, ref.locator,
                        ref.source_revision, int(ref.is_evidence), ref.snippet_sha256,
                    ),
                )

    def get_entries_by_project(
        self,
        project_id: int | str,
        *,
        kind: EntryKind | None = None,
        statuses: tuple[ValidationStatus, ...] | None = None,
        limit: int = 100,
    ) -> list[MemoryEntry]:
        project = self._require_project(project_id)
        clauses = ["project_id=?", "scope_kind='project'"]
        params: list[Any] = [project]
        if kind is not None:
            clauses.append("kind=?")
            params.append(kind.value)
        if statuses:
            clauses.append("validation_status IN (%s)" % ",".join("?" for _ in statuses))
            params.extend(status.value for status in statuses)
        params.append(max(1, min(int(limit), 500)))
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_entries WHERE " + " AND ".join(clauses)
                + " ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._entry_from_row(row) for row in rows]

    @staticmethod
    def _entry_from_row(row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            entry_id=row["entry_id"], project_id=int(row["project_id"]),
            kind=EntryKind(row["kind"]), subject=row["subject"], predicate=row["predicate"],
            value=json.loads(row["value_json"]),
            validation_status=ValidationStatus(row["validation_status"]),
            provenance=json.loads(row["provenance_json"] or "{}"),
            valid_from=row["valid_from"], valid_to=row["valid_to"],
            source_version=row["source_version"], human_verified=bool(row["human_verified"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def evidence_for_entry(self, entry_id: str) -> list[EvidenceRef]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_evidence_refs WHERE entry_id=? ORDER BY ref_id", (entry_id,)
            ).fetchall()
        return [EvidenceRef(
            ref_id=row["ref_id"], doc_id=row["doc_id"], locator=row["locator"],
            source_revision=row["source_revision"], is_evidence=bool(row["is_evidence"]),
            snippet_sha256=row["snippet_sha256"],
        ) for row in rows]

    def review_entry(self, entry_id: str, action: str) -> bool:
        status_by_action = {
            "confirm": ValidationStatus.CONFIRMED.value,
            "reject": ValidationStatus.REJECTED.value,
            "mark_disputed": ValidationStatus.DISPUTED.value,
        }
        if action not in status_by_action:
            raise ValueError("unsupported review action")
        now = utc_now()
        with self.connection() as conn:
            cursor = conn.execute(
                """UPDATE memory_entries SET validation_status=?, human_verified=1, updated_at=?
                WHERE entry_id=?""",
                (status_by_action[action], now, entry_id),
            )
        return cursor.rowcount > 0

    def enqueue(self, project_id: int, kind: str, payload: dict[str, Any]) -> str:
        project = self._require_project(project_id)
        job_id = uuid4().hex
        now = utc_now()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO memory_ingest_queue
                (job_id, project_id, kind, payload_json, status, attempts, available_at,
                 last_error, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (job_id, project, kind, json.dumps(payload, ensure_ascii=False),
                 QueueStatus.PENDING.value, 0, time.time(), "", now, now),
            )
        return job_id

    def claim_next_job(self) -> dict[str, Any] | None:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT * FROM memory_ingest_queue
                WHERE status='pending' AND available_at<=?
                ORDER BY created_at LIMIT 1""",
                (time.time(),),
            ).fetchone()
            if row is None:
                return None
            updated = conn.execute(
                """UPDATE memory_ingest_queue SET status='running', attempts=attempts+1, updated_at=?
                WHERE job_id=? AND status='pending'""",
                (utc_now(), row["job_id"]),
            )
            if updated.rowcount != 1:
                return None
        return {**dict(row), "payload": json.loads(row["payload_json"])}

    def finish_job(self, job_id: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE memory_ingest_queue SET status='done', updated_at=? WHERE job_id=?",
                (utc_now(), job_id),
            )

    def retry_job(self, job_id: str, error: str, delay_sec: float = 15.0) -> None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT attempts FROM memory_ingest_queue WHERE job_id=?", (job_id,)
            ).fetchone()
            attempts = int(row["attempts"] if row else 0)
            status = QueueStatus.FAILED.value if attempts >= 3 else QueueStatus.PENDING.value
            conn.execute(
                """UPDATE memory_ingest_queue SET status=?, available_at=?, last_error=?, updated_at=?
                WHERE job_id=?""",
                (status, time.time() + delay_sec, str(error)[:1000], utc_now(), job_id),
            )

    def save_smeta_trace(self, trace: SmetaSuccessTrace) -> bool:
        project = self._require_project(trace.project_id)
        if trace.finality not in {"priced_draft", "priced_final"}:
            return False
        if not trace.source_sha256 or not trace.knowledge_edition_identity:
            return False
        with self.connection() as conn:
            try:
                conn.execute(
                    """INSERT INTO memory_smeta_traces
                    (trace_id, project_id, source_kind, source_id, revision_id, source_sha256,
                     finality, question_signature, normalized_work_features_json, route_cache_json,
                     selected_norm_refs_json, calculation_evidence_refs_json, knowledge_edition,
                     trust_level, reviewed_at, review_note, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        trace.trace_id, project, trace.source_kind, trace.source_id,
                        trace.revision_id, trace.source_sha256, trace.finality,
                        trace.question_signature,
                        json.dumps(trace.normalized_work_features, ensure_ascii=False),
                        json.dumps([asdict(route) for route in trace.typed_catalog_routes], ensure_ascii=False),
                        json.dumps(list(trace.selected_norm_refs), ensure_ascii=False),
                        json.dumps(list(trace.calculation_evidence_refs), ensure_ascii=False),
                        trace.knowledge_edition_identity, trace.trust_level.value,
                        trace.reviewed_at, trace.review_note, trace.created_at,
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def get_smeta_traces(self, project_id: int | str, limit: int = 200) -> list[SmetaSuccessTrace]:
        project = self._require_project(project_id)
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM memory_smeta_traces
                WHERE project_id=? AND stale=0 AND disputed=0
                ORDER BY created_at DESC LIMIT ?""",
                (project, max(1, min(int(limit), 200))),
            ).fetchall()
        return [self._smeta_from_row(row) for row in rows]

    @staticmethod
    def _smeta_from_row(row: sqlite3.Row) -> SmetaSuccessTrace:
        routes = tuple(RouteEvidenceCacheDTO(**value) for value in json.loads(row["route_cache_json"] or "[]"))
        return SmetaSuccessTrace(
            trace_id=row["trace_id"], project_id=int(row["project_id"]),
            source_kind=row["source_kind"], source_id=row["source_id"],
            revision_id=row["revision_id"], source_sha256=row["source_sha256"],
            finality=row["finality"], question_signature=row["question_signature"],
            normalized_work_features=json.loads(row["normalized_work_features_json"]),
            typed_catalog_routes=routes,
            selected_norm_refs=tuple(json.loads(row["selected_norm_refs_json"] or "[]")),
            calculation_evidence_refs=tuple(json.loads(row["calculation_evidence_refs_json"] or "[]")),
            knowledge_edition_identity=row["knowledge_edition"],
            trust_level=SmetaTraceTrust(row["trust_level"] or "candidate"),
            reviewed_at=row["reviewed_at"], review_note=row["review_note"],
            created_at=row["created_at"],
        )

    def confirm_smeta_revision(
        self,
        source_revision_id: str,
        *,
        locked_revision_id: str,
        review_note: str,
    ) -> int:
        """Promote only an explicit user lock; Memory never confirms itself."""
        source = str(source_revision_id or "").strip()
        locked = str(locked_revision_id or "").strip()
        if not source or not locked or not str(review_note or "").strip():
            return 0
        now = utc_now()
        with self.connection() as conn:
            cursor = conn.execute(
                """UPDATE memory_smeta_traces
                SET trust_level=?, finality='priced_final', reviewed_at=?, review_note=?,
                    superseded_by_revision=?
                WHERE revision_id LIKE ? AND stale=0 AND disputed=0""",
                (
                    SmetaTraceTrust.ACCEPTED_PROJECT.value,
                    now,
                    str(review_note).strip()[:1000],
                    locked,
                    source + ":%",
                ),
            )
        return int(cursor.rowcount)

    def review_smeta_trace(self, trace_id: str, action: str, note: str) -> bool:
        if action not in {"confirm", "reject"}:
            raise ValueError("unsupported smeta trace review action")
        now = utc_now()
        if action == "confirm":
            values = (SmetaTraceTrust.ACCEPTED_PROJECT.value, now, str(note)[:1000], 0, trace_id)
        else:
            values = (SmetaTraceTrust.REJECTED.value, now, str(note)[:1000], 1, trace_id)
        with self.connection() as conn:
            cursor = conn.execute(
                """UPDATE memory_smeta_traces
                SET trust_level=?, reviewed_at=?, review_note=?, stale=? WHERE trace_id=?""",
                values,
            )
        return cursor.rowcount > 0

    def mark_smeta_used(self, trace_id: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """UPDATE memory_smeta_traces SET usage_count=usage_count+1, last_used_at=?
                WHERE trace_id=?""",
                (utc_now(), trace_id),
            )

    def get_config(self) -> dict[str, str]:
        with self.connection() as conn:
            rows = conn.execute("SELECT key, value FROM memory_config").fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    def set_config(self, values: dict[str, str]) -> None:
        now = utc_now()
        with self.connection() as conn:
            for key, value in values.items():
                conn.execute(
                    """INSERT INTO memory_config(key, value, updated_at) VALUES (?,?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                    (key, str(value), now),
                )

    def status(self) -> dict[str, Any]:
        with self.connection() as conn:
            counts = {
                row["kind"]: int(row["count"])
                for row in conn.execute("SELECT kind, COUNT(*) count FROM memory_entries GROUP BY kind")
            }
            queue = {
                row["status"]: int(row["count"])
                for row in conn.execute("SELECT status, COUNT(*) count FROM memory_ingest_queue GROUP BY status")
            }
            smeta_count = int(conn.execute("SELECT COUNT(*) FROM memory_smeta_traces").fetchone()[0])
            conflict_count = int(conn.execute(
                "SELECT COUNT(*) FROM memory_conflicts WHERE status='open'"
            ).fetchone()[0])
        return {"entries": counts, "queue": queue, "smeta_traces": smeta_count, "open_conflicts": conflict_count}

    def record_conflict(self, project_id: int, subject: str, predicate: str, entry_ids: list[str]) -> str:
        conflict_id = uuid4().hex
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO memory_conflicts
                (conflict_id, project_id, subject, predicate, entry_ids_json, created_at)
                VALUES (?,?,?,?,?,?)""",
                (conflict_id, self._require_project(project_id), subject, predicate,
                 json.dumps(entry_ids), utc_now()),
            )
            conn.execute(
                "UPDATE memory_entries SET validation_status='disputed', updated_at=? WHERE entry_id IN (%s)"
                % ",".join("?" for _ in entry_ids),
                [utc_now(), *entry_ids],
            )
        return conflict_id

    def refresh_snapshot(self, project_id: int) -> dict[str, Any]:
        project = self._require_project(project_id)
        entries = self.get_entries_by_project(
            project, statuses=(ValidationStatus.CONFIRMED,), limit=500,
        )
        facts = [entry for entry in entries if entry.kind == EntryKind.ASSERTION]
        snapshot = {
            "project_id": project,
            "facts": [
                {"subject": item.subject, "predicate": item.predicate, "value": item.value,
                 "source_version": item.source_version, "entry_id": item.entry_id}
                for item in facts
            ],
        }
        with self.connection() as conn:
            row = conn.execute(
                "SELECT revision FROM memory_project_snapshots WHERE project_id=?", (project,)
            ).fetchone()
            revision = int(row["revision"] if row else 0) + 1
            snapshot["revision"] = revision
            conn.execute(
                """INSERT INTO memory_project_snapshots(project_id, revision, snapshot_json, updated_at)
                VALUES (?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET
                revision=excluded.revision, snapshot_json=excluded.snapshot_json, updated_at=excluded.updated_at""",
                (project, revision, json.dumps(snapshot, ensure_ascii=False), utc_now()),
            )
        return snapshot

    def promote_non_fact(self, entry_id: str, scope_kind: str) -> str:
        if scope_kind not in {"function", "global"}:
            raise ValueError("scope_kind must be function or global")
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM memory_entries WHERE entry_id=?", (entry_id,)).fetchone()
            if row is None:
                raise KeyError(entry_id)
            if EntryKind(row["kind"]) not in _NON_FACT_KINDS:
                raise ValueError("project facts cannot be promoted")
            promoted_id = uuid4().hex
            conn.execute(
                """INSERT INTO memory_entries
                (entry_id, project_id, scope_kind, kind, subject, predicate, value_json,
                 validation_status, provenance_json, valid_from, valid_to, source_version,
                 human_verified, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    promoted_id, int(row["project_id"]), scope_kind, row["kind"], row["subject"],
                    row["predicate"], row["value_json"], row["validation_status"],
                    row["provenance_json"], row["valid_from"], row["valid_to"],
                    row["source_version"], 1, utc_now(), utc_now(),
                ),
            )
        return promoted_id
