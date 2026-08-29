"""Append-only acceptance receipts for explicit canonical-route promotion."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from backend.rag_config import rag_meta_db_path
from proxy.services.canonical_route_service import (
    CanonicalRouteDecision,
    CanonicalRouteMode,
    PromotionReceipt,
    resolve_canonical_route,
)
from proxy.services.model_connection_contracts import ConnectionRole
from tools.live_workbook_acceptance import LIVE_RUNTIME, validate_report


class CanonicalPromotionError(ValueError):
    pass


def _path(db_path: str | Path | None) -> Path:
    path = Path(db_path) if db_path is not None else Path(rag_meta_db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect(db_path: str | Path | None) -> sqlite3.Connection:
    connection = sqlite3.connect(_path(db_path))
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS les_canonical_promotion_receipts (
            acceptance_sha256 TEXT PRIMARY KEY,
            source_commit TEXT NOT NULL,
            build_number INTEGER NOT NULL,
            preset_id TEXT NOT NULL,
            observed_model_identity TEXT NOT NULL,
            passed INTEGER NOT NULL CHECK (passed = 1),
            accepted_at TEXT NOT NULL,
            accepted_by TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def _canonical_sha256(report: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _receipt(row: sqlite3.Row) -> PromotionReceipt:
    return PromotionReceipt(
        source_commit=str(row["source_commit"]),
        build_number=int(row["build_number"]),
        preset_id=str(row["preset_id"]),
        observed_model_identity=str(row["observed_model_identity"]),
        acceptance_sha256=str(row["acceptance_sha256"]),
        passed=bool(row["passed"]),
    )


def accept_promotion_report(
    db_path: str | Path | None,
    report: Mapping[str, Any],
    *,
    operator_confirmed: bool,
    actor: str,
) -> PromotionReceipt:
    """Validate and persist proof without changing the requested route mode."""
    if not operator_confirmed:
        raise CanonicalPromotionError("OPERATOR_CONFIRMATION_REQUIRED")
    try:
        validate_report(dict(report), expected_evidence_kind=LIVE_RUNTIME)
    except (TypeError, ValueError) as error:
        raise CanonicalPromotionError(f"PROMOTION_REPORT_INVALID: {error}") from error
    runtime = report.get("runtime")
    if not isinstance(runtime, Mapping):
        raise CanonicalPromotionError("PROMOTION_RUNTIME_INVALID")
    if (
        runtime.get("model_preset") != "qwen-9b"
        or runtime.get("observed_model_preset") != "qwen-9b-restrictive"
    ):
        raise CanonicalPromotionError("NINE_B_PRESET_REQUIRED")
    source_commit = str(runtime.get("source_commit_full") or "").strip().lower()
    build_number = runtime.get("build_number")
    model_identity = str(runtime.get("model_identity") or "").strip()
    if len(source_commit) != 40 or not model_identity:
        raise CanonicalPromotionError("PROMOTION_RUNTIME_IDENTITY_INVALID")
    if isinstance(build_number, bool) or not isinstance(build_number, int) or build_number < 1:
        raise CanonicalPromotionError("PROMOTION_BUILD_INVALID")
    digest = _canonical_sha256(report)
    accepted_at = datetime.now(timezone.utc).isoformat()
    accepted_by = str(actor or "").strip()
    if not accepted_by:
        raise CanonicalPromotionError("PROMOTION_ACTOR_REQUIRED")
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO les_canonical_promotion_receipts
                (acceptance_sha256, source_commit, build_number, preset_id,
                 observed_model_identity, passed, accepted_at, accepted_by)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                digest,
                source_commit,
                build_number,
                "qwen-9b-restrictive",
                model_identity,
                accepted_at,
                accepted_by,
            ),
        )
        row = connection.execute(
            "SELECT * FROM les_canonical_promotion_receipts WHERE acceptance_sha256 = ?",
            (digest,),
        ).fetchone()
    if row is None:
        raise CanonicalPromotionError("PROMOTION_RECEIPT_WRITE_FAILED")
    return _receipt(row)


def load_exact_promotion_receipt(
    db_path: str | Path | None,
    *,
    source_commit: str,
    build_number: int,
    preset_id: str,
    observed_model_identity: str,
) -> PromotionReceipt | None:
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT * FROM les_canonical_promotion_receipts
            WHERE source_commit = ? AND build_number = ? AND preset_id = ?
              AND observed_model_identity = ? AND passed = 1
            ORDER BY accepted_at DESC
            LIMIT 1
            """,
            (
                str(source_commit).strip().lower(),
                int(build_number),
                str(preset_id).strip(),
                str(observed_model_identity).strip(),
            ),
        ).fetchone()
    return _receipt(row) if row is not None else None


def resolve_promoted_route(
    *,
    resolver: Any,
    db_path: str | Path | None = None,
    runtime_identity: Mapping[str, Any] | None = None,
    requested: str | CanonicalRouteMode | None = None,
) -> CanonicalRouteDecision:
    """Resolve ACTIVE against the current runtime and exact bound answer model."""
    preliminary = resolve_canonical_route(receipt=None, requested=requested)
    if preliminary.requested is not CanonicalRouteMode.ACTIVE:
        return preliminary
    try:
        identity = dict(runtime_identity or {})
        if not identity:
            from proxy.services.version_service import version_info

            identity = version_info()
        source_commit = str(identity.get("git_commit_full") or "").strip().lower()
        build_number = int(identity.get("build_number") or 0)
        connection = resolver.resolve(ConnectionRole.ANSWER)
        preset_id = str(connection.effective_preset.preset_id)
        model_identity = str(connection.model_id)
        receipt = load_exact_promotion_receipt(
            db_path,
            source_commit=source_commit,
            build_number=build_number,
            preset_id=preset_id,
            observed_model_identity=model_identity,
        )
    except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
        return preliminary
    return resolve_canonical_route(
        receipt=receipt,
        requested=requested,
        expected_commit=source_commit,
        expected_build=build_number,
        expected_preset=preset_id,
        expected_model_identity=model_identity,
        expected_acceptance_sha256=(receipt.acceptance_sha256 if receipt else ""),
    )
