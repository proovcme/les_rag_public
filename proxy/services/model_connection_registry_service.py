"""Append-only SQLite store for global model connections."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from backend.rag_config import rag_meta_db_path
from proxy.services.model_connection_contracts import (
    CapabilityName,
    CapabilityObservation,
    CapabilitySnapshot,
    CapabilityState,
    ConnectionLocality,
    ConnectionRole,
    ModelConnectionRevision,
    RoleBinding,
)


class ModelConnectionRegistryError(RuntimeError):
    """Stable fail-closed registry error."""


class RevisionConflictError(ModelConnectionRegistryError):
    """Compare-and-swap failed because another revision won."""


_REVISION_FIELDS = frozenset(
    {
        "display_name",
        "base_url",
        "model_id",
        "locality",
        "requested_context_tokens",
        "secret_ref",
        "extension_type",
        "enabled",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ModelConnectionRegistry:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path is not None else Path(rag_meta_db_path())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            self._ensure_schema(conn)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS les_model_connection_revisions (
                revision_id TEXT PRIMARY KEY,
                connection_id TEXT NOT NULL,
                revision_no INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                protocol TEXT NOT NULL,
                base_url TEXT NOT NULL,
                model_id TEXT NOT NULL,
                locality TEXT NOT NULL,
                requested_context_tokens INTEGER,
                secret_ref TEXT,
                extension_type TEXT,
                enabled INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                UNIQUE(connection_id, revision_no)
            );
            CREATE TABLE IF NOT EXISTS les_model_connection_heads (
                connection_id TEXT PRIMARY KEY,
                revision_id TEXT NOT NULL REFERENCES les_model_connection_revisions(revision_id)
            );
            CREATE TABLE IF NOT EXISTS les_model_capability_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                connection_revision_id TEXT NOT NULL REFERENCES les_model_connection_revisions(revision_id),
                observations_json TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                transport_options_json TEXT NOT NULL,
                created_by TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS les_model_role_bindings (
                role TEXT NOT NULL,
                binding_revision INTEGER NOT NULL,
                connection_revision_id TEXT NOT NULL REFERENCES les_model_connection_revisions(revision_id),
                bound_at TEXT NOT NULL,
                bound_by TEXT NOT NULL,
                PRIMARY KEY(role, binding_revision)
            );
            CREATE TABLE IF NOT EXISTS les_model_connection_audit (
                event_id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                connection_id TEXT,
                revision_id TEXT,
                actor TEXT NOT NULL,
                created_at TEXT NOT NULL,
                details_json TEXT NOT NULL
            );
            """
        )

    @staticmethod
    def _revision_from_row(row: sqlite3.Row) -> ModelConnectionRevision:
        return ModelConnectionRevision(
            connection_id=row["connection_id"],
            revision_id=row["revision_id"],
            revision_no=int(row["revision_no"]),
            display_name=row["display_name"],
            protocol=row["protocol"],
            base_url=row["base_url"],
            model_id=row["model_id"],
            locality=ConnectionLocality(row["locality"]),
            requested_context_tokens=row["requested_context_tokens"],
            secret_ref=row["secret_ref"],
            extension_type=row["extension_type"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            created_by=row["created_by"],
        )

    @staticmethod
    def _binding_from_row(row: sqlite3.Row) -> RoleBinding:
        return RoleBinding(
            role=ConnectionRole(row["role"]),
            binding_revision=int(row["binding_revision"]),
            connection_revision_id=row["connection_revision_id"],
            bound_at=row["bound_at"],
            bound_by=row["bound_by"],
        )

    @staticmethod
    def _assert_display_name_available(
        conn: sqlite3.Connection,
        display_name: str,
        *,
        excluding_connection_id: str | None = None,
    ) -> None:
        params: list[Any] = [display_name.strip()]
        excluding = ""
        if excluding_connection_id is not None:
            excluding = "AND r.connection_id <> ?"
            params.append(excluding_connection_id)
        row = conn.execute(
            f"""
            SELECT r.connection_id
            FROM les_model_connection_heads h
            JOIN les_model_connection_revisions r ON r.revision_id=h.revision_id
            WHERE r.enabled=1 AND trim(r.display_name) = trim(?) COLLATE NOCASE
            {excluding}
            LIMIT 1
            """,
            params,
        ).fetchone()
        if row is not None:
            raise ModelConnectionRegistryError("DISPLAY_NAME_IN_USE")

    @staticmethod
    def _insert_revision(conn: sqlite3.Connection, revision: ModelConnectionRevision) -> None:
        conn.execute(
            """
            INSERT INTO les_model_connection_revisions (
                revision_id,connection_id,revision_no,display_name,protocol,base_url,
                model_id,locality,requested_context_tokens,secret_ref,extension_type,
                enabled,created_at,created_by
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                revision.revision_id,
                revision.connection_id,
                revision.revision_no,
                revision.display_name,
                revision.protocol,
                revision.base_url,
                revision.model_id,
                revision.locality.value,
                revision.requested_context_tokens,
                revision.secret_ref,
                revision.extension_type,
                int(revision.enabled),
                revision.created_at,
                revision.created_by,
            ),
        )

    @staticmethod
    def _audit(
        conn: sqlite3.Connection,
        *,
        action: str,
        actor: str,
        connection_id: str | None,
        revision_id: str | None,
        details: dict[str, Any],
    ) -> None:
        conn.execute(
            """INSERT INTO les_model_connection_audit
               (event_id,action,connection_id,revision_id,actor,created_at,details_json)
               VALUES(?,?,?,?,?,?,?)""",
            (uuid4().hex, action, connection_id, revision_id, actor, _now(), _json(details)),
        )

    def create_connection(
        self,
        *,
        display_name: str,
        base_url: str,
        model_id: str,
        locality: ConnectionLocality,
        requested_context_tokens: int | None,
        secret_ref: str | None,
        extension_type: str | None,
        actor: str,
    ) -> ModelConnectionRevision:
        connection_id = f"conn:{uuid4().hex}"
        revision = ModelConnectionRevision(
            connection_id=connection_id,
            revision_id=f"{connection_id}:r1",
            revision_no=1,
            display_name=display_name,
            protocol="openai_compatible",
            base_url=base_url,
            model_id=model_id,
            locality=ConnectionLocality(locality),
            requested_context_tokens=requested_context_tokens,
            secret_ref=secret_ref,
            extension_type=extension_type,
            enabled=True,
            created_at=_now(),
            created_by=actor,
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._assert_display_name_available(conn, revision.display_name)
            self._insert_revision(conn, revision)
            conn.execute(
                "INSERT INTO les_model_connection_heads(connection_id,revision_id) VALUES(?,?)",
                (revision.connection_id, revision.revision_id),
            )
            self._audit(
                conn,
                action="connection_created",
                actor=revision.created_by,
                connection_id=revision.connection_id,
                revision_id=revision.revision_id,
                details={"revision_no": revision.revision_no},
            )
        return revision

    def import_connection(
        self,
        *,
        stable_connection_id: str,
        display_name: str,
        base_url: str,
        model_id: str,
        locality: ConnectionLocality,
        requested_context_tokens: int | None,
        secret_ref: str | None,
        extension_type: str | None,
        actor: str,
    ) -> ModelConnectionRevision:
        """Create one deterministic legacy revision, or return its existing head.

        This is deliberately narrower than normal creation. It exists only so
        startup migration can be idempotent without storing provider settings or
        secret bytes in application data.
        """
        connection_id = str(stable_connection_id or "").strip()
        if not connection_id.startswith("legacy:") or connection_id == "legacy:":
            raise ModelConnectionRegistryError("LEGACY_CONNECTION_ID_INVALID")
        revision = ModelConnectionRevision(
            connection_id=connection_id,
            revision_id=f"{connection_id}:r1",
            revision_no=1,
            display_name=display_name,
            protocol="openai_compatible",
            base_url=base_url,
            model_id=model_id,
            locality=ConnectionLocality(locality),
            requested_context_tokens=requested_context_tokens,
            secret_ref=secret_ref,
            extension_type=extension_type,
            enabled=True,
            created_at=_now(),
            created_by=actor,
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """SELECT r.* FROM les_model_connection_heads h
                   JOIN les_model_connection_revisions r ON r.revision_id=h.revision_id
                   WHERE h.connection_id=?""",
                (connection_id,),
            ).fetchone()
            if existing is not None:
                return self._revision_from_row(existing)
            self._assert_display_name_available(conn, revision.display_name)
            self._insert_revision(conn, revision)
            conn.execute(
                "INSERT INTO les_model_connection_heads(connection_id,revision_id) VALUES(?,?)",
                (revision.connection_id, revision.revision_id),
            )
            self._audit(
                conn,
                action="legacy_connection_imported",
                actor=revision.created_by,
                connection_id=revision.connection_id,
                revision_id=revision.revision_id,
                details={"revision_no": 1},
            )
        return revision

    def revise_connection(
        self,
        connection_id: str,
        *,
        expected_revision_id: str,
        actor: str,
        **changes: object,
    ) -> ModelConnectionRevision:
        unknown = set(changes) - _REVISION_FIELDS
        if unknown:
            raise ModelConnectionRegistryError(
                f"UNSUPPORTED_CONNECTION_FIELDS: {','.join(sorted(unknown))}"
            )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT r.* FROM les_model_connection_heads h
                   JOIN les_model_connection_revisions r ON r.revision_id=h.revision_id
                   WHERE h.connection_id=?""",
                (connection_id,),
            ).fetchone()
            if row is None:
                raise ModelConnectionRegistryError("CONNECTION_NOT_FOUND")
            current = self._revision_from_row(row)
            if current.revision_id != expected_revision_id:
                raise RevisionConflictError("CONNECTION_REVISION_CONFLICT")
            values = asdict(current)
            values.update(changes)
            values["locality"] = ConnectionLocality(values["locality"])
            values.update(
                revision_id=f"{connection_id}:r{current.revision_no + 1}",
                revision_no=current.revision_no + 1,
                protocol="openai_compatible",
                created_at=_now(),
                created_by=actor,
            )
            revision = ModelConnectionRevision(**values)
            if revision.enabled:
                self._assert_display_name_available(
                    conn,
                    revision.display_name,
                    excluding_connection_id=connection_id,
                )
            self._insert_revision(conn, revision)
            changed = conn.execute(
                """UPDATE les_model_connection_heads SET revision_id=?
                   WHERE connection_id=? AND revision_id=?""",
                (revision.revision_id, connection_id, expected_revision_id),
            ).rowcount
            if changed != 1:
                raise RevisionConflictError("CONNECTION_REVISION_CONFLICT")
            self._audit(
                conn,
                action="connection_revised",
                actor=actor,
                connection_id=connection_id,
                revision_id=revision.revision_id,
                details={"revision_no": revision.revision_no, "fields": sorted(changes)},
            )
        return revision

    def disable_connection(
        self,
        connection_id: str,
        *,
        expected_revision_id: str,
        actor: str,
    ) -> ModelConnectionRevision:
        return self.revise_connection(
            connection_id,
            expected_revision_id=expected_revision_id,
            enabled=False,
            actor=actor,
        )

    def get_connection(self, connection_id: str) -> ModelConnectionRevision:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT r.* FROM les_model_connection_heads h
                   JOIN les_model_connection_revisions r ON r.revision_id=h.revision_id
                   WHERE h.connection_id=?""",
                (connection_id,),
            ).fetchone()
        if row is None:
            raise ModelConnectionRegistryError("CONNECTION_NOT_FOUND")
        return self._revision_from_row(row)

    def get_revision(self, revision_id: str) -> ModelConnectionRevision:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM les_model_connection_revisions WHERE revision_id=?",
                (revision_id,),
            ).fetchone()
        if row is None:
            raise ModelConnectionRegistryError("CONNECTION_REVISION_NOT_FOUND")
        return self._revision_from_row(row)

    def list_connections(
        self,
        *,
        include_disabled: bool = False,
    ) -> tuple[ModelConnectionRevision, ...]:
        enabled_clause = "" if include_disabled else "WHERE r.enabled=1"
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT r.* FROM les_model_connection_heads h
                    JOIN les_model_connection_revisions r ON r.revision_id=h.revision_id
                    {enabled_clause}
                    ORDER BY lower(r.display_name), r.connection_id"""
            ).fetchall()
        return tuple(self._revision_from_row(row) for row in rows)

    def list_revisions(self, connection_id: str) -> tuple[ModelConnectionRevision, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM les_model_connection_revisions
                   WHERE connection_id=? ORDER BY revision_no""",
                (connection_id,),
            ).fetchall()
        return tuple(self._revision_from_row(row) for row in rows)

    def bind_role(
        self,
        role: ConnectionRole,
        connection_revision_id: str,
        *,
        expected_binding_revision: int | None,
        actor: str,
    ) -> RoleBinding:
        canonical_role = ConnectionRole(role)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            target = conn.execute(
                "SELECT enabled,connection_id FROM les_model_connection_revisions WHERE revision_id=?",
                (connection_revision_id,),
            ).fetchone()
            if target is None:
                raise ModelConnectionRegistryError("CONNECTION_REVISION_NOT_FOUND")
            if not bool(target["enabled"]):
                raise ModelConnectionRegistryError("CONNECTION_DISABLED")
            current_row = conn.execute(
                """SELECT * FROM les_model_role_bindings
                   WHERE role=? ORDER BY binding_revision DESC LIMIT 1""",
                (canonical_role.value,),
            ).fetchone()
            current_revision = int(current_row["binding_revision"]) if current_row else None
            if current_revision != expected_binding_revision:
                raise RevisionConflictError("ROLE_BINDING_CONFLICT")
            binding = RoleBinding(
                role=canonical_role,
                binding_revision=(current_revision or 0) + 1,
                connection_revision_id=connection_revision_id,
                bound_at=_now(),
                bound_by=actor,
            )
            conn.execute(
                """INSERT INTO les_model_role_bindings
                   (role,binding_revision,connection_revision_id,bound_at,bound_by)
                   VALUES(?,?,?,?,?)""",
                (
                    binding.role.value,
                    binding.binding_revision,
                    binding.connection_revision_id,
                    binding.bound_at,
                    binding.bound_by,
                ),
            )
            self._audit(
                conn,
                action="role_bound",
                actor=actor,
                connection_id=target["connection_id"],
                revision_id=connection_revision_id,
                details={"role": canonical_role.value, "binding_revision": binding.binding_revision},
            )
        return binding

    def get_role_binding(self, role: ConnectionRole) -> RoleBinding | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM les_model_role_bindings
                   WHERE role=? ORDER BY binding_revision DESC LIMIT 1""",
                (ConnectionRole(role).value,),
            ).fetchone()
        return self._binding_from_row(row) if row is not None else None

    def save_capability_snapshot(
        self,
        snapshot: CapabilitySnapshot,
        *,
        actor: str,
    ) -> None:
        observations = [
            {
                "capability": item.capability.value,
                "state": item.state.value,
                "evidence_source": item.evidence_source,
                "observed_at": item.observed_at.isoformat(),
                "detail": item.detail,
            }
            for item in snapshot.observations
        ]
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute(
                "SELECT 1 FROM les_model_connection_revisions WHERE revision_id=?",
                (snapshot.connection_revision_id,),
            ).fetchone()
            if exists is None:
                raise ModelConnectionRegistryError("CONNECTION_REVISION_NOT_FOUND")
            try:
                conn.execute(
                    """INSERT INTO les_model_capability_snapshots
                       (snapshot_id,connection_revision_id,observations_json,observed_at,
                        expires_at,transport_options_json,created_by)
                       VALUES(?,?,?,?,?,?,?)""",
                    (
                        snapshot.snapshot_id,
                        snapshot.connection_revision_id,
                        _json(observations),
                        snapshot.observed_at.isoformat(),
                        snapshot.expires_at.isoformat(),
                        _json(dict(snapshot.transport_options)),
                        actor,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ModelConnectionRegistryError("CAPABILITY_SNAPSHOT_EXISTS") from exc
            self._audit(
                conn,
                action="capabilities_recorded",
                actor=actor,
                connection_id=None,
                revision_id=snapshot.connection_revision_id,
                details={"snapshot_id": snapshot.snapshot_id},
            )

    def latest_capability_snapshot(
        self,
        connection_revision_id: str,
    ) -> CapabilitySnapshot | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM les_model_capability_snapshots
                   WHERE connection_revision_id=?
                   ORDER BY observed_at DESC, rowid DESC LIMIT 1""",
                (connection_revision_id,),
            ).fetchone()
        if row is None:
            return None
        observations = tuple(
            CapabilityObservation(
                capability=CapabilityName(item["capability"]),
                state=CapabilityState(item["state"]),
                evidence_source=item["evidence_source"],
                observed_at=datetime.fromisoformat(item["observed_at"]),
                detail=item.get("detail", ""),
            )
            for item in json.loads(row["observations_json"])
        )
        return CapabilitySnapshot(
            snapshot_id=row["snapshot_id"],
            connection_revision_id=row["connection_revision_id"],
            observations=observations,
            observed_at=datetime.fromisoformat(row["observed_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            transport_options=json.loads(row["transport_options_json"]),
        )
