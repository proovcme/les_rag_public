"""Append-only, provenance-bearing artifact revision storage."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping
from uuid import uuid4


class ArtifactRevisionError(ValueError):
    pass


class ArtifactNotFoundError(ArtifactRevisionError):
    pass


class ArtifactImmutableError(ArtifactRevisionError):
    pass


@dataclass(frozen=True)
class ArtifactRevisionRequest:
    artifact_kind: Literal["lsr_workbook", "vor_workbook"]
    file_path: Path
    source_scope: tuple[str, ...]
    profile_revision_id: str
    model_identity: str
    model_preset: str
    tool_calls: tuple[Mapping[str, Any], ...]
    decision_checkpoint_id: str
    missing: tuple[str, ...]
    blockers: tuple[str, ...]
    parent_revision_id: str | None


@dataclass(frozen=True)
class ArtifactRevision:
    artifact_id: str
    revision_id: str
    artifact_kind: str
    revision_no: int
    parent_revision_id: str | None
    sha256: str
    byte_size: int
    filename: str
    download_url: str
    source_scope: tuple[str, ...]
    profile_revision_id: str
    model_identity: str
    model_preset: str
    tool_calls: tuple[Mapping[str, Any], ...]
    decision_checkpoint_id: str
    missing: tuple[str, ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ArtifactRevisionStore:
    def __init__(self, db_path: Path, root: Path):
        self.db_path = Path(db_path)
        self.root = Path(root)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS artifact_revisions (
                    revision_id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL,
                    artifact_kind TEXT NOT NULL, revision_no INTEGER NOT NULL,
                    parent_revision_id TEXT, sha256 TEXT NOT NULL, byte_size INTEGER NOT NULL,
                    filename TEXT NOT NULL, relative_path TEXT NOT NULL UNIQUE,
                    metadata_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(artifact_id, revision_no)
                )
            """)

    @staticmethod
    def _sha(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def create_revision(self, request: ArtifactRevisionRequest) -> ArtifactRevision:
        source = Path(request.file_path)
        if request.artifact_kind not in {"lsr_workbook", "vor_workbook"}:
            raise ArtifactRevisionError("unsupported artifact kind")
        if not source.is_file():
            raise ArtifactRevisionError("generated artifact file is missing")
        payload = source.read_bytes()
        if not payload:
            raise ArtifactRevisionError("generated artifact file is empty")

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if request.parent_revision_id:
                parent = conn.execute(
                    "SELECT artifact_id, artifact_kind, revision_no FROM artifact_revisions WHERE revision_id=?",
                    (request.parent_revision_id,),
                ).fetchone()
                if parent is None:
                    raise ArtifactNotFoundError("parent revision not found")
                if parent["artifact_kind"] != request.artifact_kind:
                    raise ArtifactRevisionError("parent artifact kind mismatch")
                artifact_id = str(parent["artifact_id"])
                revision_no = int(parent["revision_no"]) + 1
            else:
                artifact_id = f"art_{uuid4().hex}"
                revision_no = 1
            revision_id = f"rev_{uuid4().hex}"
            suffix = source.suffix.lower() or ".bin"
            relative_path = Path(artifact_id) / f"{revision_id}{suffix}"
            target = self.root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=f".{revision_id}-", dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_name, target)
                metadata = {
                    "source_scope": list(request.source_scope),
                    "profile_revision_id": request.profile_revision_id,
                    "model_identity": request.model_identity,
                    "model_preset": request.model_preset,
                    "tool_calls": list(request.tool_calls),
                    "decision_checkpoint_id": request.decision_checkpoint_id,
                    "missing": list(request.missing),
                    "blockers": list(request.blockers),
                }
                conn.execute(
                    """INSERT INTO artifact_revisions
                    (revision_id,artifact_id,artifact_kind,revision_no,parent_revision_id,sha256,
                     byte_size,filename,relative_path,metadata_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (revision_id, artifact_id, request.artifact_kind, revision_no,
                     request.parent_revision_id, self._sha(payload), len(payload), source.name,
                     relative_path.as_posix(), json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))),
                )
                conn.commit()
            except Exception:
                Path(temp_name).unlink(missing_ok=True)
                target.unlink(missing_ok=True)
                raise
        return self.get_revision(revision_id)

    def _row(self, revision_id: str) -> sqlite3.Row:
        if not revision_id or "/" in revision_id or "\\" in revision_id or ".." in revision_id:
            raise ArtifactNotFoundError("revision not found")
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM artifact_revisions WHERE revision_id=?", (revision_id,)).fetchone()
        if row is None:
            raise ArtifactNotFoundError("revision not found")
        return row

    def get_revision(self, revision_id: str) -> ArtifactRevision:
        row = self._row(revision_id)
        meta = json.loads(row["metadata_json"])
        return ArtifactRevision(
            artifact_id=row["artifact_id"], revision_id=row["revision_id"],
            artifact_kind=row["artifact_kind"], revision_no=int(row["revision_no"]),
            parent_revision_id=row["parent_revision_id"], sha256=row["sha256"],
            byte_size=int(row["byte_size"]), filename=row["filename"],
            download_url=f"/api/artifacts/{row['revision_id']}/download",
            source_scope=tuple(meta.get("source_scope") or ()),
            profile_revision_id=str(meta.get("profile_revision_id") or ""),
            model_identity=str(meta.get("model_identity") or ""),
            model_preset=str(meta.get("model_preset") or ""),
            tool_calls=tuple(meta.get("tool_calls") or ()),
            decision_checkpoint_id=str(meta.get("decision_checkpoint_id") or ""),
            missing=tuple(meta.get("missing") or ()), blockers=tuple(meta.get("blockers") or ()),
        )

    def list_revisions(self, artifact_id: str) -> list[ArtifactRevision]:
        if not artifact_id or "/" in artifact_id or "\\" in artifact_id or ".." in artifact_id:
            raise ArtifactNotFoundError("artifact not found")
        with self._connect() as conn:
            ids = [row[0] for row in conn.execute(
                "SELECT revision_id FROM artifact_revisions WHERE artifact_id=? ORDER BY revision_no",
                (artifact_id,),
            )]
        if not ids:
            raise ArtifactNotFoundError("artifact not found")
        return [self.get_revision(revision_id) for revision_id in ids]

    def resolve_path(self, revision_id: str) -> Path:
        row = self._row(revision_id)
        target = (self.root / row["relative_path"]).resolve()
        if self.root.resolve() not in target.parents:
            raise ArtifactImmutableError("artifact path escaped storage root")
        return target

    def read_bytes(self, revision_id: str) -> bytes:
        revision = self.get_revision(revision_id)
        target = self.resolve_path(revision_id)
        try:
            payload = target.read_bytes()
        except FileNotFoundError as exc:
            raise ArtifactImmutableError("artifact file is missing") from exc
        if self._sha(payload) != revision.sha256 or len(payload) != revision.byte_size:
            raise ArtifactImmutableError("artifact hash drift detected")
        return payload

    def replace_bytes(self, revision_id: str, payload: bytes) -> None:
        self._row(revision_id)
        raise ArtifactImmutableError("artifact revisions are immutable")
