"""Persistent conversational RIM session and immutable revision graph.

This module stores operational state only.  It never chooses a work, norm,
coverage link, price, coefficient or estimating scenario.  Professional
payloads are authored by the model or user and remain append-only revisions;
code validates structural integrity and finality gates.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator
from uuid import uuid4


DEFAULT_ROOT = Path("storage/rim_sessions")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_NORM_KEY_RE = re.compile(
    r"^(?:ГЭСНМР|ГЭСНМ|ГЭСНП|ГЭСНР|ГЭСН|ФЕРМР|ФЕРМ|ФЕРП|ФЕРР|ФЕР|ТЕРМР|ТЕРМ|ТЕРП|ТЕРР|ТЕР)"
    r":[0-9]{2}-[0-9]{2}-[0-9]{3}-[0-9]{2}$",
    re.IGNORECASE,
)

MAPPING_STATUSES = {
    "not_started",
    "candidates_ready",
    "mapping_selected",
    "mapping_globally_reviewed",
    "mapping_locked",
}
PRICING_STATUSES = {"unpriced", "priced_partial", "priced_draft", "priced_final"}
SESSION_PHASES = {
    "new",
    "intake",
    "vor",
    "mapping",
    "scenarios",
    "pricing",
    "finalization",
    "finalized",
}
REQUIREMENT_POLICIES = {"blocks_final", "waivable_with_reason", "warning_only"}
REQUIREMENT_STATUSES = {"open", "resolved", "waived_by_user"}


class RimSessionError(RuntimeError):
    """Base error for the persistent RIM workflow."""


class RimSessionNotFound(RimSessionError):
    pass


class RimSessionForbidden(RimSessionError):
    pass


class RimSessionConflict(RimSessionError):
    pass


class RimSessionValidationError(RimSessionError):
    pass


@dataclass(frozen=True)
class RevisionResult:
    session: dict[str, Any]
    revision_id: str
    parent_revision_id: str
    issues: tuple[dict[str, Any], ...] = ()
    requirements: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session["session_id"],
            "revision_id": self.revision_id,
            "parent_revision_id": self.parent_revision_id,
            "status": self.session["display_state"],
            "session": self.session,
            "issues": list(self.issues),
            "requirements": list(self.requirements),
        }


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _payload_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _safe_id(value: str, *, name: str) -> str:
    cleaned = str(value or "").strip()
    if not _SAFE_ID_RE.fullmatch(cleaned):
        raise RimSessionValidationError(f"invalid {name}")
    return cleaned


def _owner_id(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise RimSessionValidationError("owner_id is required")
    return cleaned[:256]


def _json_load(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _display_state(row: dict[str, Any]) -> str:
    if row["pricing_status"] == "priced_final":
        return "priced_final"
    if row["phase"] == "finalization":
        return "awaiting_final_lock"
    if row["pricing_status"] == "priced_draft":
        return "priced_draft"
    if row["pricing_status"] == "priced_partial":
        return "awaiting_missing_data"
    if row["mapping_status"] == "mapping_locked":
        return "combinations_ready" if row.get("scenario_status") == "ready" else "mapping_locked"
    if row["mapping_status"] == "mapping_globally_reviewed":
        return "mapping_globally_reviewed"
    if row["mapping_status"] in {"mapping_selected", "candidates_ready"}:
        return "awaiting_mapping_decisions"
    if row["phase"] == "mapping":
        return "norm_mapping"
    if row["phase"] == "vor":
        return "awaiting_vor_approval"
    if row["phase"] == "intake":
        return "intake_classified"
    return "new"


def _validate_vor_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, 1):
        work_id = str(row.get("work_id") or "").strip()
        title = str(row.get("work_name") or row.get("title") or "").strip()
        unit = str(row.get("unit") or "").strip()
        section = str(row.get("section_name") or row.get("section") or "").strip()
        quantity = row.get("quantity")
        if not work_id:
            issues.append({"code": "work_id_missing", "severity": "blocking", "row": index})
        elif work_id in seen:
            issues.append(
                {"code": "work_id_duplicate", "severity": "blocking", "row": index, "work_id": work_id}
            )
        seen.add(work_id)
        if not title or title.startswith("MISSING:"):
            issues.append(
                {"code": "work_name_missing", "severity": "blocking", "row": index, "work_id": work_id}
            )
        if not unit:
            issues.append(
                {"code": "unit_missing", "severity": "blocking", "row": index, "work_id": work_id}
            )
        if not section or section == "Без раздела":
            issues.append(
                {"code": "section_missing", "severity": "blocking", "row": index, "work_id": work_id}
            )
        try:
            numeric_quantity = float(quantity)
        except (TypeError, ValueError):
            issues.append(
                {"code": "quantity_invalid", "severity": "blocking", "row": index, "work_id": work_id}
            )
        else:
            if numeric_quantity < 0:
                issues.append(
                    {"code": "quantity_negative", "severity": "blocking", "row": index, "work_id": work_id}
                )
            elif numeric_quantity == 0:
                issues.append(
                    {"code": "quantity_zero", "severity": "warning", "row": index, "work_id": work_id}
                )
    return issues


def _validate_mapping_rows(
    mapping_rows: list[dict[str, Any]],
    work_ids: set[str],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(mapping_rows, 1):
        mapping_row_id = str(row.get("mapping_row_id") or "").strip()
        work_id = str(row.get("work_id") or "").strip()
        norm_key = str(row.get("norm_key") or "").strip()
        selection_kind = str(row.get("selection_kind") or "direct")
        selection_status = str(row.get("selection_status") or "candidate")
        if not mapping_row_id:
            issues.append({"code": "mapping_row_id_missing", "severity": "blocking", "row": index})
        elif mapping_row_id in seen_ids:
            issues.append(
                {
                    "code": "mapping_row_id_duplicate",
                    "severity": "blocking",
                    "row": index,
                    "mapping_row_id": mapping_row_id,
                }
            )
        seen_ids.add(mapping_row_id)
        if work_id not in work_ids:
            issues.append(
                {
                    "code": "mapping_work_id_unknown",
                    "severity": "blocking",
                    "row": index,
                    "work_id": work_id,
                }
            )
        if selection_kind in {"covered_by", "unbound"}:
            if norm_key:
                issues.append(
                    {
                        "code": "mapping_non_norm_has_norm_key",
                        "severity": "blocking",
                        "row": index,
                        "work_id": work_id,
                    }
                )
            if selection_kind == "covered_by":
                covered_by = str(row.get("covered_by_work_id") or "").strip()
                if not covered_by or covered_by not in work_ids or covered_by == work_id:
                    issues.append(
                        {
                            "code": "coverage_provider_invalid",
                            "severity": "blocking",
                            "row": index,
                            "work_id": work_id,
                            "covered_by_work_id": covered_by,
                        }
                    )
            else:
                issues.append(
                    {
                        "code": "norm_confirmation_required",
                        "severity": "blocking",
                        "row": index,
                        "work_id": work_id,
                    }
                )
            if not str(row.get("reason") or "").strip():
                issues.append(
                    {
                        "code": "mapping_reason_missing",
                        "severity": "blocking",
                        "row": index,
                        "work_id": work_id,
                    }
                )
        elif not _NORM_KEY_RE.fullmatch(norm_key):
            issues.append(
                {
                    "code": "norm_key_invalid",
                    "severity": "blocking",
                    "row": index,
                    "work_id": work_id,
                    "norm_key": norm_key,
                }
            )
        if selection_status not in {"candidate", "accepted", "selected", "rejected", "conflict"}:
            issues.append(
                {
                    "code": "selection_status_invalid",
                    "severity": "blocking",
                    "row": index,
                    "work_id": work_id,
                }
            )
        if (
            selection_kind not in {"covered_by", "unbound"}
            and selection_status in {"accepted", "selected"}
            and not bool(row.get("card_opened"))
        ):
            issues.append(
                {
                    "code": "selected_norm_card_not_opened",
                    "severity": "blocking",
                    "row": index,
                    "work_id": work_id,
                    "norm_key": norm_key,
                }
            )
        if bool(row.get("is_analog")) and not str(row.get("reason") or "").strip():
            issues.append(
                {
                    "code": "analog_reason_missing",
                    "severity": "blocking",
                    "row": index,
                    "work_id": work_id,
                    "norm_key": norm_key,
                }
            )
    return issues


class RimSessionStore:
    """SQLite-backed session registry with append-only revisions and audit events."""

    def __init__(self, root: str | Path = DEFAULT_ROOT):
        self.root = Path(root)
        self.db_path = self.root / "rim_sessions.sqlite3"

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema(conn)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS rim_sessions (
                session_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL DEFAULT '',
                owner_id TEXT NOT NULL,
                phase TEXT NOT NULL,
                mapping_status TEXT NOT NULL,
                pricing_status TEXT NOT NULL,
                session_status TEXT NOT NULL,
                pending_question_id TEXT NOT NULL DEFAULT '',
                head_revision_id TEXT NOT NULL DEFAULT '',
                current_vor_revision_id TEXT NOT NULL DEFAULT '',
                current_mapping_revision_id TEXT NOT NULL DEFAULT '',
                mapping_lock_revision_id TEXT NOT NULL DEFAULT '',
                scenario_status TEXT NOT NULL DEFAULT 'not_started',
                current_scenario_revision_id TEXT NOT NULL DEFAULT '',
                current_pricing_revision_id TEXT NOT NULL DEFAULT '',
                final_lock_revision_id TEXT NOT NULL DEFAULT '',
                normative_base_version TEXT NOT NULL DEFAULT '',
                pricebook_id TEXT NOT NULL DEFAULT '',
                region_code TEXT NOT NULL DEFAULT '',
                price_period TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rim_revisions (
                revision_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES rim_sessions(session_id),
                parent_revision_id TEXT NOT NULL DEFAULT '',
                revision_kind TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_rim_revisions_session
                ON rim_revisions(session_id, created_at);
            CREATE TABLE IF NOT EXISTS rim_events (
                event_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES rim_sessions(session_id),
                revision_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_rim_events_session
                ON rim_events(session_id, created_at);
            CREATE TABLE IF NOT EXISTS rim_questions (
                question_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES rim_sessions(session_id),
                opened_revision_id TEXT NOT NULL,
                answered_revision_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                answer_json TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                answered_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS rim_requirements (
                requirement_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES rim_sessions(session_id),
                kind TEXT NOT NULL,
                severity TEXT NOT NULL,
                finality_policy TEXT NOT NULL,
                work_id TEXT NOT NULL DEFAULT '',
                resource_code TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL,
                required_fields_json TEXT NOT NULL,
                status TEXT NOT NULL,
                source_refs_json TEXT NOT NULL,
                created_revision_id TEXT NOT NULL,
                resolved_revision_id TEXT NOT NULL DEFAULT '',
                resolution_json TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_rim_requirements_session
                ON rim_requirements(session_id, status);
            CREATE TABLE IF NOT EXISTS rim_idempotency (
                session_id TEXT NOT NULL REFERENCES rim_sessions(session_id),
                idempotency_key TEXT NOT NULL,
                operation TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (session_id, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS rim_agent_checkpoints (
                session_id TEXT NOT NULL REFERENCES rim_sessions(session_id),
                checkpoint_kind TEXT NOT NULL,
                base_revision_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, checkpoint_kind)
            );
            """
        )
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(rim_sessions)").fetchall()
        }
        if "scenario_status" not in columns:
            conn.execute(
                "ALTER TABLE rim_sessions ADD COLUMN scenario_status TEXT NOT NULL DEFAULT 'not_started'"
            )
        if "current_scenario_revision_id" not in columns:
            conn.execute(
                "ALTER TABLE rim_sessions ADD COLUMN current_scenario_revision_id TEXT NOT NULL DEFAULT ''"
            )

    @staticmethod
    def _session_row(
        conn: sqlite3.Connection,
        session_id: str,
        *,
        owner_id: str | None = None,
        allow_admin: bool = False,
    ) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM rim_sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise RimSessionNotFound("RIM session not found")
        if owner_id is not None and not allow_admin and row["owner_id"] != owner_id:
            raise RimSessionForbidden("RIM session belongs to another user")
        return row

    @staticmethod
    def _require_expected_parent(row: sqlite3.Row, expected_parent_revision_id: str) -> None:
        expected = str(expected_parent_revision_id or "").strip()
        actual = str(row["head_revision_id"] or "")
        if expected and expected != actual:
            raise RimSessionConflict(
                f"session head changed: expected {expected}, current {actual}"
            )

    @staticmethod
    def _insert_revision(
        conn: sqlite3.Connection,
        *,
        session_id: str,
        parent_revision_id: str,
        revision_kind: str,
        created_by: str,
        payload: dict[str, Any],
    ) -> str:
        revision_id = uuid4().hex
        created_at = _utcnow()
        conn.execute(
            """
            INSERT INTO rim_revisions (
                revision_id, session_id, parent_revision_id, revision_kind,
                created_by, created_at, payload_json, payload_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                session_id,
                parent_revision_id,
                revision_kind,
                created_by,
                created_at,
                _canonical_json(payload),
                _payload_sha256(payload),
            ),
        )
        conn.execute(
            """
            INSERT INTO rim_events (
                event_id, session_id, revision_id, event_type, actor_id, created_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                session_id,
                revision_id,
                revision_kind,
                created_by,
                created_at,
                _canonical_json({"revision_kind": revision_kind}),
            ),
        )
        return revision_id

    @staticmethod
    def _update_session(
        conn: sqlite3.Connection,
        session_id: str,
        revision_id: str,
        updates: dict[str, Any],
    ) -> None:
        allowed = {
            "phase",
            "mapping_status",
            "pricing_status",
            "session_status",
            "pending_question_id",
            "current_vor_revision_id",
            "current_mapping_revision_id",
            "mapping_lock_revision_id",
            "scenario_status",
            "current_scenario_revision_id",
            "current_pricing_revision_id",
            "final_lock_revision_id",
            "normative_base_version",
            "pricebook_id",
            "region_code",
            "price_period",
        }
        invalid = set(updates) - allowed
        if invalid:
            raise RimSessionValidationError(
                "invalid session fields: " + ", ".join(sorted(invalid))
            )
        fields = {"head_revision_id": revision_id, "updated_at": _utcnow(), **updates}
        assignments = ", ".join(f"{name}=?" for name in fields)
        conn.execute(
            f"UPDATE rim_sessions SET {assignments} WHERE session_id=?",
            (*fields.values(), session_id),
        )

    def _requirements(self, conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM rim_requirements WHERE session_id=? ORDER BY requirement_id",
            (session_id,),
        ).fetchall()
        return [
            {
                "schema": "rim_requirement_v1",
                "requirement_id": row["requirement_id"],
                "kind": row["kind"],
                "severity": row["severity"],
                "finality_policy": row["finality_policy"],
                "work_id": row["work_id"],
                "resource_code": row["resource_code"],
                "description": row["description"],
                "required_fields": _json_load(row["required_fields_json"], []),
                "status": row["status"],
                "source_refs": _json_load(row["source_refs_json"], []),
                "created_revision_id": row["created_revision_id"],
                "resolved_revision_id": row["resolved_revision_id"],
                "resolution": _json_load(row["resolution_json"], {}),
            }
            for row in rows
        ]

    def _question(self, conn: sqlite3.Connection, question_id: str) -> dict[str, Any] | None:
        if not question_id:
            return None
        row = conn.execute(
            "SELECT * FROM rim_questions WHERE question_id=?", (question_id,)
        ).fetchone()
        if row is None:
            return None
        payload = _json_load(row["payload_json"], {})
        return {
            "question_id": row["question_id"],
            "status": row["status"],
            **payload,
            "answer": _json_load(row["answer_json"], None),
        }

    def _session_dict(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["schema"] = "rim_session_v1"
        payload["display_state"] = _display_state(payload)
        payload["pending_question"] = self._question(conn, payload["pending_question_id"])
        payload["open_requirement_count"] = conn.execute(
            "SELECT COUNT(*) FROM rim_requirements WHERE session_id=? AND status='open'",
            (payload["session_id"],),
        ).fetchone()[0]
        payload["allowed_user_actions"] = self.allowed_user_actions(payload)
        return payload

    @staticmethod
    def allowed_user_actions(session: dict[str, Any]) -> list[str]:
        actions = ["view_session", "view_revisions", "view_requirements"]
        if session.get("pending_question_id"):
            actions.append("answer_question")
        if session["phase"] in {"new", "intake", "vor"}:
            actions.extend(["import_source", "save_vor_revision"])
        if session["mapping_status"] != "mapping_locked":
            actions.extend(["save_mapping_revision", "import_mapping_xlsx"])
        if session["mapping_status"] == "mapping_globally_reviewed":
            actions.append("lock_mapping")
        if session["mapping_status"] == "mapping_locked":
            actions.extend(["generate_scenarios", "save_pricing_revision", "resolve_requirement"])
        if session["pricing_status"] == "priced_draft":
            actions.append("finalize_estimate")
        return actions

    def create_session(
        self,
        *,
        owner_id: str,
        project_id: str = "",
        normative_base_version: str = "",
        pricebook_id: str = "",
        region_code: str = "",
        price_period: str = "",
    ) -> RevisionResult:
        session_id = str(uuid4())
        created_at = _utcnow()
        actor = _owner_id(owner_id)
        payload = {
            "schema": "rim_session_created_v1",
            "project_id": str(project_id or ""),
            "normative_base_version": str(normative_base_version or ""),
            "pricebook_id": str(pricebook_id or ""),
            "region_code": str(region_code or ""),
            "price_period": str(price_period or ""),
        }
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO rim_sessions (
                    session_id, project_id, owner_id, phase, mapping_status, pricing_status,
                    session_status, normative_base_version, pricebook_id, region_code,
                    price_period, created_at, updated_at
                ) VALUES (?, ?, ?, 'new', 'not_started', 'unpriced', 'active', ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    str(project_id or ""),
                    actor,
                    str(normative_base_version or ""),
                    str(pricebook_id or ""),
                    str(region_code or ""),
                    str(price_period or ""),
                    created_at,
                    created_at,
                ),
            )
            revision_id = self._insert_revision(
                conn,
                session_id=session_id,
                parent_revision_id="",
                revision_kind="session_created",
                created_by=actor,
                payload=payload,
            )
            self._update_session(conn, session_id, revision_id, {})
            session = self._session_dict(conn, self._session_row(conn, session_id))
            return RevisionResult(session, revision_id, "")

    def get_session(
        self,
        session_id: str,
        *,
        owner_id: str,
        allow_admin: bool = False,
    ) -> dict[str, Any]:
        safe_id = _safe_id(session_id, name="session_id")
        with self._connection() as conn:
            row = self._session_row(
                conn, safe_id, owner_id=_owner_id(owner_id), allow_admin=allow_admin
            )
            result = self._session_dict(conn, row)
            result["requirements"] = self._requirements(conn, safe_id)
            return result

    def list_sessions(
        self,
        *,
        owner_id: str,
        allow_admin: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        actor = _owner_id(owner_id)
        bounded = max(1, min(int(limit), 500))
        with self._connection() as conn:
            if allow_admin:
                rows = conn.execute(
                    "SELECT * FROM rim_sessions ORDER BY updated_at DESC LIMIT ?",
                    (bounded,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM rim_sessions WHERE owner_id=? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (actor, bounded),
                ).fetchall()
            return [self._session_dict(conn, row) for row in rows]

    def list_revisions(
        self,
        session_id: str,
        *,
        owner_id: str,
        allow_admin: bool = False,
    ) -> list[dict[str, Any]]:
        safe_id = _safe_id(session_id, name="session_id")
        with self._connection() as conn:
            self._session_row(
                conn, safe_id, owner_id=_owner_id(owner_id), allow_admin=allow_admin
            )
            rows = conn.execute(
                """
                SELECT revision_id, parent_revision_id, revision_kind, created_by,
                       created_at, payload_json, payload_sha256
                FROM rim_revisions WHERE session_id=? ORDER BY created_at, revision_id
                """,
                (safe_id,),
            ).fetchall()
            return [
                {
                    **dict(row),
                    "payload": _json_load(row["payload_json"], {}),
                }
                for row in rows
            ]

    def save_agent_checkpoint(
        self,
        session_id: str,
        *,
        owner_id: str,
        checkpoint_kind: str,
        base_revision_id: str,
        payload: dict[str, Any],
        allow_admin: bool = False,
    ) -> dict[str, Any]:
        """Durably save internal agent progress without advancing session head."""
        safe_session = _safe_id(session_id, name="session_id")
        kind = str(checkpoint_kind or "").strip()
        base = str(base_revision_id or "").strip()
        if not kind:
            raise RimSessionValidationError("checkpoint_kind is required")
        if not base:
            raise RimSessionValidationError("base_revision_id is required")
        if not isinstance(payload, dict):
            raise RimSessionValidationError("checkpoint payload must be an object")
        now = _utcnow()
        canonical = _canonical_json(payload)
        digest = _payload_sha256(payload)
        with self._connection() as conn:
            self._session_row(
                conn,
                safe_session,
                owner_id=_owner_id(owner_id),
                allow_admin=allow_admin,
            )
            base_row = conn.execute(
                "SELECT 1 FROM rim_revisions WHERE session_id=? AND revision_id=?",
                (safe_session, base),
            ).fetchone()
            if base_row is None:
                raise RimSessionValidationError(
                    "checkpoint base revision does not belong to this RIM session"
                )
            conn.execute(
                """
                INSERT INTO rim_agent_checkpoints (
                    session_id, checkpoint_kind, base_revision_id,
                    payload_json, payload_sha256, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, checkpoint_kind) DO UPDATE SET
                    base_revision_id=excluded.base_revision_id,
                    payload_json=excluded.payload_json,
                    payload_sha256=excluded.payload_sha256,
                    updated_at=excluded.updated_at
                """,
                (
                    safe_session,
                    kind,
                    base,
                    canonical,
                    digest,
                    now,
                    now,
                ),
            )
        return {
            "session_id": safe_session,
            "checkpoint_kind": kind,
            "base_revision_id": base,
            "payload_sha256": digest,
            "updated_at": now,
        }

    def load_agent_checkpoint(
        self,
        session_id: str,
        *,
        owner_id: str,
        checkpoint_kind: str,
        base_revision_id: str,
        allow_admin: bool = False,
    ) -> dict[str, Any] | None:
        """Load only a checkpoint bound to the current immutable input revision."""
        safe_session = _safe_id(session_id, name="session_id")
        kind = str(checkpoint_kind or "").strip()
        base = str(base_revision_id or "").strip()
        with self._connection() as conn:
            self._session_row(
                conn,
                safe_session,
                owner_id=_owner_id(owner_id),
                allow_admin=allow_admin,
            )
            row = conn.execute(
                """
                SELECT base_revision_id, payload_json, payload_sha256, updated_at
                FROM rim_agent_checkpoints
                WHERE session_id=? AND checkpoint_kind=?
                """,
                (safe_session, kind),
            ).fetchone()
            if row is None or str(row["base_revision_id"] or "") != base:
                return None
            payload = _json_load(row["payload_json"], {})
            if not isinstance(payload, dict) or _payload_sha256(payload) != str(
                row["payload_sha256"] or ""
            ):
                raise RimSessionValidationError("RIM agent checkpoint integrity failure")
            return {
                "session_id": safe_session,
                "checkpoint_kind": kind,
                "base_revision_id": base,
                "payload": payload,
                "payload_sha256": str(row["payload_sha256"] or ""),
                "updated_at": str(row["updated_at"] or ""),
            }

    def clear_agent_checkpoint(
        self,
        session_id: str,
        *,
        owner_id: str,
        checkpoint_kind: str,
        allow_admin: bool = False,
    ) -> None:
        safe_session = _safe_id(session_id, name="session_id")
        kind = str(checkpoint_kind or "").strip()
        with self._connection() as conn:
            self._session_row(
                conn,
                safe_session,
                owner_id=_owner_id(owner_id),
                allow_admin=allow_admin,
            )
            conn.execute(
                "DELETE FROM rim_agent_checkpoints "
                "WHERE session_id=? AND checkpoint_kind=?",
                (safe_session, kind),
            )

    def revision_payload(
        self,
        session_id: str,
        revision_id: str,
        *,
        owner_id: str,
        allow_admin: bool = False,
    ) -> dict[str, Any]:
        safe_session = _safe_id(session_id, name="session_id")
        safe_revision = _safe_id(revision_id, name="revision_id")
        with self._connection() as conn:
            self._session_row(
                conn, safe_session, owner_id=_owner_id(owner_id), allow_admin=allow_admin
            )
            row = conn.execute(
                "SELECT * FROM rim_revisions WHERE session_id=? AND revision_id=?",
                (safe_session, safe_revision),
            ).fetchone()
            if row is None:
                raise RimSessionNotFound("RIM revision not found")
            return {**dict(row), "payload": _json_load(row["payload_json"], {})}

    def save_intake(
        self,
        session_id: str,
        *,
        owner_id: str,
        intake: dict[str, Any],
        expected_parent_revision_id: str = "",
        source_kind: str = "vor",
        allow_admin: bool = False,
    ) -> RevisionResult:
        safe_id = _safe_id(session_id, name="session_id")
        if source_kind not in {"vor", "specification", "auto"}:
            raise RimSessionValidationError("source_kind must be vor|specification|auto")
        payload = {
            "schema": "rim_source_intake_revision_v1",
            "source_kind": source_kind,
            "intake": intake,
        }
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._session_row(
                conn, safe_id, owner_id=_owner_id(owner_id), allow_admin=allow_admin
            )
            self._require_expected_parent(row, expected_parent_revision_id)
            parent = row["head_revision_id"]
            revision_id = self._insert_revision(
                conn,
                session_id=safe_id,
                parent_revision_id=parent,
                revision_kind="source_intake",
                created_by=_owner_id(owner_id),
                payload=payload,
            )
            self._update_session(conn, safe_id, revision_id, {"phase": "intake"})
            session = self._session_dict(conn, self._session_row(conn, safe_id))
            issues = tuple(intake.get("issues") or ())
            return RevisionResult(session, revision_id, parent, issues)

    def save_vor_revision(
        self,
        session_id: str,
        *,
        owner_id: str,
        rows: list[dict[str, Any]],
        expected_parent_revision_id: str = "",
        created_by: str = "model",
        change_note: str = "",
        allow_admin: bool = False,
    ) -> RevisionResult:
        safe_id = _safe_id(session_id, name="session_id")
        if created_by not in {"model", "user"}:
            raise RimSessionValidationError("created_by must be model|user")
        issues = _validate_vor_rows(rows)
        payload = {
            "schema": "rim_vor_revision_v1",
            "rows": rows,
            "issues": issues,
            "change_note": str(change_note or ""),
        }
        actor = _owner_id(owner_id) if created_by == "user" else "model"
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._session_row(
                conn, safe_id, owner_id=_owner_id(owner_id), allow_admin=allow_admin
            )
            self._require_expected_parent(row, expected_parent_revision_id)
            parent = row["head_revision_id"]
            revision_id = self._insert_revision(
                conn,
                session_id=safe_id,
                parent_revision_id=parent,
                revision_kind="vor_revision",
                created_by=actor,
                payload=payload,
            )
            self._update_session(
                conn,
                safe_id,
                revision_id,
                {
                    "phase": "vor",
                    "current_vor_revision_id": revision_id,
                    "mapping_status": "not_started",
                    "pricing_status": "unpriced",
                    "current_mapping_revision_id": "",
                    "mapping_lock_revision_id": "",
                    "scenario_status": "not_started",
                    "current_scenario_revision_id": "",
                    "current_pricing_revision_id": "",
                    "final_lock_revision_id": "",
                    "session_status": "active",
                },
            )
            session = self._session_dict(conn, self._session_row(conn, safe_id))
            return RevisionResult(session, revision_id, parent, tuple(issues))

    def _current_vor_rows(self, conn: sqlite3.Connection, row: sqlite3.Row) -> list[dict[str, Any]]:
        revision_id = str(row["current_vor_revision_id"] or "")
        if not revision_id:
            raise RimSessionConflict("VOR revision is required")
        revision = conn.execute(
            "SELECT payload_json FROM rim_revisions WHERE revision_id=? AND session_id=?",
            (revision_id, row["session_id"]),
        ).fetchone()
        payload = _json_load(revision["payload_json"] if revision else "", {})
        return list(payload.get("rows") or [])

    def save_mapping_revision(
        self,
        session_id: str,
        *,
        owner_id: str,
        mapping_rows: list[dict[str, Any]],
        expected_parent_revision_id: str = "",
        created_by: str = "model",
        revision_kind: str = "mapping_revision",
        conflicts: list[dict[str, Any]] | None = None,
        change_note: str = "",
        allow_admin: bool = False,
    ) -> RevisionResult:
        safe_id = _safe_id(session_id, name="session_id")
        if created_by not in {"model", "user"}:
            raise RimSessionValidationError("created_by must be model|user")
        if revision_kind not in {"mapping_revision", "mapping_global_review", "mapping_xlsx_import"}:
            raise RimSessionValidationError("invalid mapping revision kind")
        actor = _owner_id(owner_id) if created_by == "user" else "model"
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._session_row(
                conn, safe_id, owner_id=_owner_id(owner_id), allow_admin=allow_admin
            )
            self._require_expected_parent(row, expected_parent_revision_id)
            if row["mapping_status"] == "mapping_locked":
                raise RimSessionConflict("locked mapping cannot be overwritten; create a VOR child revision")
            vor_rows = self._current_vor_rows(conn, row)
            work_ids = {str(item.get("work_id") or "") for item in vor_rows}
            issues = _validate_mapping_rows(mapping_rows, work_ids)
            review_conflicts = list(conflicts or [])
            payload = {
                "schema": "rim_mapping_revision_v1",
                "mapping_rows": mapping_rows,
                "issues": issues,
                "professional_conflicts": review_conflicts,
                "change_note": str(change_note or ""),
                "vor_revision_id": row["current_vor_revision_id"],
            }
            parent = row["head_revision_id"]
            revision_id = self._insert_revision(
                conn,
                session_id=safe_id,
                parent_revision_id=parent,
                revision_kind=revision_kind,
                created_by=actor,
                payload=payload,
            )
            selected = any(
                str(item.get("selection_status") or "") in {"accepted", "selected"}
                for item in mapping_rows
            )
            status = (
                "mapping_globally_reviewed"
                if revision_kind == "mapping_global_review"
                else ("mapping_selected" if selected else "candidates_ready")
            )
            self._update_session(
                conn,
                safe_id,
                revision_id,
                {
                    "phase": "mapping",
                    "mapping_status": status,
                    "current_mapping_revision_id": revision_id,
                    "pricing_status": "unpriced",
                    "mapping_lock_revision_id": "",
                    "scenario_status": "not_started",
                    "current_scenario_revision_id": "",
                    "current_pricing_revision_id": "",
                    "final_lock_revision_id": "",
                    "session_status": "active",
                },
            )
            session = self._session_dict(conn, self._session_row(conn, safe_id))
            combined_issues = [*issues, *review_conflicts]
            return RevisionResult(session, revision_id, parent, tuple(combined_issues))

    def lock_mapping(
        self,
        session_id: str,
        *,
        owner_id: str,
        review_note: str,
        accepted_conflict_ids: list[str] | None = None,
        expected_parent_revision_id: str = "",
        allow_admin: bool = False,
    ) -> RevisionResult:
        safe_id = _safe_id(session_id, name="session_id")
        note = str(review_note or "").strip()
        if not note:
            raise RimSessionValidationError("review_note is required")
        accepted = {str(value) for value in (accepted_conflict_ids or []) if str(value)}
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._session_row(
                conn, safe_id, owner_id=_owner_id(owner_id), allow_admin=allow_admin
            )
            self._require_expected_parent(row, expected_parent_revision_id)
            if row["mapping_status"] != "mapping_globally_reviewed":
                raise RimSessionConflict("only globally reviewed mapping can be locked")
            source = conn.execute(
                "SELECT payload_json FROM rim_revisions WHERE revision_id=?",
                (row["current_mapping_revision_id"],),
            ).fetchone()
            source_payload = _json_load(source["payload_json"] if source else "", {})
            blocking_issues = [
                issue
                for issue in (source_payload.get("issues") or [])
                if str(issue.get("severity") or "") == "blocking"
            ]
            if blocking_issues:
                raise RimSessionConflict("mapping has blocking structural issues")
            conflict_ids = {
                str(item.get("conflict_id") or "")
                for item in (source_payload.get("professional_conflicts") or [])
                if str(item.get("conflict_id") or "")
            }
            missing = sorted(conflict_ids - accepted)
            if missing:
                raise RimSessionConflict(
                    "professional conflicts require explicit acceptance: " + ", ".join(missing)
                )
            parent = row["head_revision_id"]
            payload = {
                "schema": "rim_mapping_lock_v1",
                "mapping_revision_id": row["current_mapping_revision_id"],
                "review_note": note,
                "accepted_conflict_ids": sorted(accepted),
            }
            revision_id = self._insert_revision(
                conn,
                session_id=safe_id,
                parent_revision_id=parent,
                revision_kind="mapping_lock",
                created_by=_owner_id(owner_id),
                payload=payload,
            )
            self._update_session(
                conn,
                safe_id,
                revision_id,
                {
                    "phase": "scenarios",
                    "mapping_status": "mapping_locked",
                    "mapping_lock_revision_id": revision_id,
                    "scenario_status": "not_started",
                    "current_scenario_revision_id": "",
                    "pricing_status": "unpriced",
                    "session_status": "active",
                },
            )
            session = self._session_dict(conn, self._session_row(conn, safe_id))
            return RevisionResult(session, revision_id, parent)

    def save_scenario_revision(
        self,
        session_id: str,
        *,
        owner_id: str,
        scenario_set: dict[str, Any],
        expected_parent_revision_id: str = "",
        created_by: str = "model",
        allow_admin: bool = False,
    ) -> RevisionResult:
        safe_id = _safe_id(session_id, name="session_id")
        if created_by not in {"model", "user"}:
            raise RimSessionValidationError("created_by must be model|user")
        issues = list(scenario_set.get("issues") or [])
        blocking = any(str(item.get("severity") or "") == "blocking" for item in issues)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._session_row(
                conn, safe_id, owner_id=_owner_id(owner_id), allow_admin=allow_admin
            )
            self._require_expected_parent(row, expected_parent_revision_id)
            if row["mapping_status"] != "mapping_locked":
                raise RimSessionConflict("scenario generation requires mapping_locked")
            parent = row["head_revision_id"]
            payload = {
                **scenario_set,
                "mapping_lock_revision_id": row["mapping_lock_revision_id"],
            }
            revision_id = self._insert_revision(
                conn,
                session_id=safe_id,
                parent_revision_id=parent,
                revision_kind="scenario_revision",
                created_by=(_owner_id(owner_id) if created_by == "user" else "model"),
                payload=payload,
            )
            self._update_session(
                conn,
                safe_id,
                revision_id,
                {
                    "phase": "scenarios",
                    "scenario_status": "blocked" if blocking else "ready",
                    "current_scenario_revision_id": revision_id,
                    "pricing_status": "unpriced",
                    "current_pricing_revision_id": "",
                    "final_lock_revision_id": "",
                    "session_status": "active",
                },
            )
            session = self._session_dict(conn, self._session_row(conn, safe_id))
            return RevisionResult(session, revision_id, parent, tuple(issues))

    def open_question(
        self,
        session_id: str,
        *,
        owner_id: str,
        question: dict[str, Any],
        expected_parent_revision_id: str = "",
        allow_admin: bool = False,
    ) -> RevisionResult:
        safe_id = _safe_id(session_id, name="session_id")
        text = str(question.get("text") or "").strip()
        if not text:
            raise RimSessionValidationError("question.text is required")
        options = list(question.get("options") or [])
        if len(options) > 8:
            raise RimSessionValidationError("question supports at most 8 options")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._session_row(
                conn, safe_id, owner_id=_owner_id(owner_id), allow_admin=allow_admin
            )
            self._require_expected_parent(row, expected_parent_revision_id)
            if row["pending_question_id"]:
                raise RimSessionConflict("session already has an unanswered question")
            question_id = str(uuid4())
            parent = row["head_revision_id"]
            payload = {
                "schema": "rim_question_v1",
                "question_id": question_id,
                "question_kind": str(question.get("question_kind") or ""),
                "text": text,
                "reason": str(question.get("reason") or ""),
                "work_ids": list(question.get("work_ids") or []),
                "options": options,
                "answer_schema": dict(question.get("answer_schema") or {}),
            }
            revision_id = self._insert_revision(
                conn,
                session_id=safe_id,
                parent_revision_id=parent,
                revision_kind="question_opened",
                created_by="model",
                payload=payload,
            )
            conn.execute(
                """
                INSERT INTO rim_questions (
                    question_id, session_id, opened_revision_id, status,
                    payload_json, created_at
                ) VALUES (?, ?, ?, 'open', ?, ?)
                """,
                (question_id, safe_id, revision_id, _canonical_json(payload), _utcnow()),
            )
            self._update_session(
                conn, safe_id, revision_id, {"pending_question_id": question_id}
            )
            session = self._session_dict(conn, self._session_row(conn, safe_id))
            return RevisionResult(session, revision_id, parent)

    def answer_question(
        self,
        session_id: str,
        *,
        owner_id: str,
        answer: dict[str, Any],
        expected_parent_revision_id: str = "",
        allow_admin: bool = False,
    ) -> RevisionResult:
        safe_id = _safe_id(session_id, name="session_id")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._session_row(
                conn, safe_id, owner_id=_owner_id(owner_id), allow_admin=allow_admin
            )
            self._require_expected_parent(row, expected_parent_revision_id)
            question_id = str(row["pending_question_id"] or "")
            if not question_id:
                raise RimSessionConflict("session has no unanswered question")
            parent = row["head_revision_id"]
            payload = {
                "schema": "rim_question_answer_v1",
                "question_id": question_id,
                "answer": answer,
            }
            revision_id = self._insert_revision(
                conn,
                session_id=safe_id,
                parent_revision_id=parent,
                revision_kind="question_answered",
                created_by=_owner_id(owner_id),
                payload=payload,
            )
            conn.execute(
                """
                UPDATE rim_questions
                SET status='answered', answered_revision_id=?, answer_json=?, answered_at=?
                WHERE question_id=? AND session_id=?
                """,
                (revision_id, _canonical_json(answer), _utcnow(), question_id, safe_id),
            )
            session_updates = {"pending_question_id": ""}
            for field in ("region_code", "price_period"):
                value = answer.get(field)
                if isinstance(value, str) and value.strip():
                    session_updates[field] = value.strip()
            self._update_session(
                conn, safe_id, revision_id, session_updates
            )
            session = self._session_dict(conn, self._session_row(conn, safe_id))
            return RevisionResult(session, revision_id, parent)

    @staticmethod
    def _validate_requirement(requirement: dict[str, Any]) -> dict[str, Any]:
        policy = str(requirement.get("finality_policy") or "blocks_final")
        if policy not in REQUIREMENT_POLICIES:
            raise RimSessionValidationError("invalid requirement finality_policy")
        severity = str(requirement.get("severity") or "blocking")
        if severity not in {"blocking", "warning"}:
            raise RimSessionValidationError("invalid requirement severity")
        status = str(requirement.get("status") or "open")
        if status not in REQUIREMENT_STATUSES:
            raise RimSessionValidationError("invalid requirement status")
        description = str(requirement.get("description") or "").strip()
        if not description:
            raise RimSessionValidationError("requirement description is required")
        return {
            "requirement_id": str(requirement.get("requirement_id") or uuid4().hex),
            "kind": str(requirement.get("kind") or "norm_confirmation"),
            "severity": severity,
            "finality_policy": policy,
            "work_id": str(requirement.get("work_id") or ""),
            "resource_code": str(requirement.get("resource_code") or ""),
            "description": description,
            "required_fields": list(requirement.get("required_fields") or []),
            "status": status,
            "source_refs": list(requirement.get("source_refs") or []),
        }

    def save_pricing_revision(
        self,
        session_id: str,
        *,
        owner_id: str,
        trace: dict[str, Any],
        requirements: list[dict[str, Any]],
        expected_parent_revision_id: str = "",
        created_by: str = "model",
        change_note: str = "",
        allow_admin: bool = False,
    ) -> RevisionResult:
        safe_id = _safe_id(session_id, name="session_id")
        if created_by not in {"model", "user"}:
            raise RimSessionValidationError("created_by must be model|user")
        normalized = [self._validate_requirement(item) for item in requirements]
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._session_row(
                conn, safe_id, owner_id=_owner_id(owner_id), allow_admin=allow_admin
            )
            self._require_expected_parent(row, expected_parent_revision_id)
            if row["mapping_status"] != "mapping_locked":
                raise RimSessionConflict("pricing requires mapping_locked")
            parent = row["head_revision_id"]
            payload = {
                "schema": "rim_pricing_revision_v1",
                "trace": trace,
                "requirements": normalized,
                "mapping_lock_revision_id": row["mapping_lock_revision_id"],
                "change_note": str(change_note or ""),
            }
            revision_id = self._insert_revision(
                conn,
                session_id=safe_id,
                parent_revision_id=parent,
                revision_kind="pricing_revision",
                created_by=(_owner_id(owner_id) if created_by == "user" else "model"),
                payload=payload,
            )
            conn.execute("DELETE FROM rim_requirements WHERE session_id=?", (safe_id,))
            for requirement in normalized:
                conn.execute(
                    """
                    INSERT INTO rim_requirements (
                        requirement_id, session_id, kind, severity, finality_policy,
                        work_id, resource_code, description, required_fields_json,
                        status, source_refs_json, created_revision_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requirement["requirement_id"],
                        safe_id,
                        requirement["kind"],
                        requirement["severity"],
                        requirement["finality_policy"],
                        requirement["work_id"],
                        requirement["resource_code"],
                        requirement["description"],
                        _canonical_json(requirement["required_fields"]),
                        requirement["status"],
                        _canonical_json(requirement["source_refs"]),
                        revision_id,
                    ),
                )
            has_blocking = any(
                item["status"] == "open" and item["finality_policy"] == "blocks_final"
                for item in normalized
            )
            pricing_status = "priced_partial" if has_blocking else "priced_draft"
            self._update_session(
                conn,
                safe_id,
                revision_id,
                {
                    "phase": "pricing",
                    "pricing_status": pricing_status,
                    "current_pricing_revision_id": revision_id,
                    "final_lock_revision_id": "",
                    "session_status": "active",
                },
            )
            session = self._session_dict(conn, self._session_row(conn, safe_id))
            current_requirements = self._requirements(conn, safe_id)
            return RevisionResult(
                session, revision_id, parent, (), tuple(current_requirements)
            )

    def resolve_requirement(
        self,
        session_id: str,
        requirement_id: str,
        *,
        owner_id: str,
        status: str,
        resolution: dict[str, Any],
        expected_parent_revision_id: str = "",
        allow_admin: bool = False,
    ) -> RevisionResult:
        safe_id = _safe_id(session_id, name="session_id")
        safe_requirement = _safe_id(requirement_id, name="requirement_id")
        if status not in {"resolved", "waived_by_user"}:
            raise RimSessionValidationError("requirement status must be resolved|waived_by_user")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._session_row(
                conn, safe_id, owner_id=_owner_id(owner_id), allow_admin=allow_admin
            )
            self._require_expected_parent(row, expected_parent_revision_id)
            requirement = conn.execute(
                "SELECT * FROM rim_requirements WHERE session_id=? AND requirement_id=?",
                (safe_id, safe_requirement),
            ).fetchone()
            if requirement is None:
                raise RimSessionNotFound("RIM requirement not found")
            if requirement["status"] != "open":
                raise RimSessionConflict("requirement is already closed")
            if status == "waived_by_user" and requirement["finality_policy"] == "blocks_final":
                raise RimSessionConflict("blocking requirement cannot be waived")
            if status == "waived_by_user" and not str(resolution.get("reason") or "").strip():
                raise RimSessionValidationError("waiver reason is required")
            parent = row["head_revision_id"]
            payload = {
                "schema": "rim_requirement_resolution_v1",
                "requirement_id": safe_requirement,
                "status": status,
                "resolution": resolution,
            }
            revision_id = self._insert_revision(
                conn,
                session_id=safe_id,
                parent_revision_id=parent,
                revision_kind="requirement_resolved",
                created_by=_owner_id(owner_id),
                payload=payload,
            )
            conn.execute(
                """
                UPDATE rim_requirements
                SET status=?, resolved_revision_id=?, resolution_json=?
                WHERE session_id=? AND requirement_id=?
                """,
                (status, revision_id, _canonical_json(resolution), safe_id, safe_requirement),
            )
            # A resolved input is not a recalculated estimate.  Keep the
            # session partial until the deterministic calculator writes a new
            # pricing revision whose trace incorporates the decision.
            self._update_session(
                conn,
                safe_id,
                revision_id,
                {"phase": "pricing", "pricing_status": "priced_partial"},
            )
            session = self._session_dict(conn, self._session_row(conn, safe_id))
            requirements = self._requirements(conn, safe_id)
            return RevisionResult(session, revision_id, parent, (), tuple(requirements))

    def finalize(
        self,
        session_id: str,
        *,
        owner_id: str,
        review_note: str,
        expected_parent_revision_id: str = "",
        allow_admin: bool = False,
    ) -> RevisionResult:
        safe_id = _safe_id(session_id, name="session_id")
        note = str(review_note or "").strip()
        if not note:
            raise RimSessionValidationError("final review_note is required")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._session_row(
                conn, safe_id, owner_id=_owner_id(owner_id), allow_admin=allow_admin
            )
            self._require_expected_parent(row, expected_parent_revision_id)
            if row["mapping_status"] != "mapping_locked":
                raise RimSessionConflict("finalization requires mapping_locked")
            if row["pricing_status"] != "priced_draft":
                raise RimSessionConflict("finalization requires a complete priced draft")
            blockers = conn.execute(
                """
                SELECT requirement_id FROM rim_requirements
                WHERE session_id=? AND status='open' AND finality_policy='blocks_final'
                """,
                (safe_id,),
            ).fetchall()
            if blockers:
                raise RimSessionConflict("open blocking requirements prevent finalization")
            parent = row["head_revision_id"]
            payload = {
                "schema": "rim_final_lock_v1",
                "mapping_lock_revision_id": row["mapping_lock_revision_id"],
                "pricing_revision_id": row["current_pricing_revision_id"],
                "review_note": note,
            }
            revision_id = self._insert_revision(
                conn,
                session_id=safe_id,
                parent_revision_id=parent,
                revision_kind="final_lock",
                created_by=_owner_id(owner_id),
                payload=payload,
            )
            self._update_session(
                conn,
                safe_id,
                revision_id,
                {
                    "phase": "finalized",
                    "pricing_status": "priced_final",
                    "session_status": "finalized",
                    "final_lock_revision_id": revision_id,
                },
            )
            session = self._session_dict(conn, self._session_row(conn, safe_id))
            requirements = self._requirements(conn, safe_id)
            return RevisionResult(session, revision_id, parent, (), tuple(requirements))
