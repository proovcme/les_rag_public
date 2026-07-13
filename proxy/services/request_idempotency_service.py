"""Persistent idempotency records for externally retried LES requests.

The store never keeps the raw idempotency key.  A record is scoped by operation
and authenticated caller, and binds the key to one canonical request hash.
Concurrent duplicates are rejected before an expensive model/tool workflow is
started; completed duplicates receive the original JSON response.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path(os.getenv("LES_IDEMPOTENCY_DB", "storage/request_idempotency.db"))
DEFAULT_TTL_SEC = int(os.getenv("LES_IDEMPOTENCY_TTL_SEC", str(7 * 24 * 3600)))
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


class IdempotencyConflict(ValueError):
    """The same key was used with a different request payload."""


def normalize_idempotency_key(value: str) -> str:
    key = str(value or "").strip()
    if not _KEY_RE.fullmatch(key):
        raise ValueError(
            "Idempotency-Key должен содержать 8–128 символов: буквы, цифры, '.', '_', ':' или '-'"
        )
    return key


def request_fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def caller_scope(user: Any) -> str:
    """Stable non-secret caller identity for an authenticated RequestUser."""
    identity = "|".join(
        (
            str(getattr(user, "key_value", "") or ""),
            str(getattr(user, "holder", "") or ""),
            str(getattr(user, "source", "") or ""),
            str(getattr(user, "role", "") or ""),
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS request_idempotency (
            operation TEXT NOT NULL,
            caller_scope TEXT NOT NULL,
            key_hash TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            response_json TEXT,
            created_at_epoch REAL NOT NULL,
            updated_at_epoch REAL NOT NULL,
            PRIMARY KEY (operation, caller_scope, key_hash)
        )
        """
    )
    return conn


def begin(
    *,
    operation: str,
    caller: str,
    idempotency_key: str,
    request_hash: str,
    db_path: str | Path | None = None,
    ttl_sec: int = DEFAULT_TTL_SEC,
) -> tuple[str, dict[str, Any] | None]:
    """Claim a request or return its completed response.

    Returns ``("started", None)``, ``("in_progress", None)`` or
    ``("completed", response)``.
    """
    key = normalize_idempotency_key(idempotency_key)
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    now = time.time()
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "DELETE FROM request_idempotency WHERE updated_at_epoch < ?",
            (now - max(60, int(ttl_sec)),),
        )
        row = conn.execute(
            "SELECT request_hash, status, response_json FROM request_idempotency "
            "WHERE operation=? AND caller_scope=? AND key_hash=?",
            (operation, caller, key_hash),
        ).fetchone()
        if row:
            stored_hash, status, response_json = row
            if stored_hash != request_hash:
                raise IdempotencyConflict("Idempotency-Key уже использован для другого запроса")
            if status == "completed" and response_json:
                conn.commit()
                return "completed", json.loads(response_json)
            if status == "in_progress":
                conn.commit()
                return "in_progress", None
            conn.execute(
                "UPDATE request_idempotency SET status='in_progress', response_json=NULL, "
                "updated_at_epoch=? WHERE operation=? AND caller_scope=? AND key_hash=?",
                (now, operation, caller, key_hash),
            )
        else:
            conn.execute(
                "INSERT INTO request_idempotency "
                "(operation, caller_scope, key_hash, request_hash, status, response_json, "
                "created_at_epoch, updated_at_epoch) VALUES (?, ?, ?, ?, 'in_progress', NULL, ?, ?)",
                (operation, caller, key_hash, request_hash, now, now),
            )
        conn.commit()
        return "started", None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def complete(
    *,
    operation: str,
    caller: str,
    idempotency_key: str,
    request_hash: str,
    response: dict[str, Any],
    db_path: str | Path | None = None,
) -> None:
    key_hash = hashlib.sha256(normalize_idempotency_key(idempotency_key).encode("utf-8")).hexdigest()
    payload = json.dumps(response, ensure_ascii=False, sort_keys=True, default=str)
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "UPDATE request_idempotency SET status='completed', response_json=?, updated_at_epoch=? "
            "WHERE operation=? AND caller_scope=? AND key_hash=? AND request_hash=?",
            (payload, time.time(), operation, caller, key_hash, request_hash),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("idempotency claim was lost before completion")
        conn.commit()
    finally:
        conn.close()


def release(
    *,
    operation: str,
    caller: str,
    idempotency_key: str,
    request_hash: str,
    db_path: str | Path | None = None,
) -> None:
    """Release a failed attempt so a caller can safely retry it."""
    key_hash = hashlib.sha256(normalize_idempotency_key(idempotency_key).encode("utf-8")).hexdigest()
    conn = _connect(db_path)
    try:
        conn.execute(
            "DELETE FROM request_idempotency WHERE operation=? AND caller_scope=? "
            "AND key_hash=? AND request_hash=? AND status='in_progress'",
            (operation, caller, key_hash, request_hash),
        )
        conn.commit()
    finally:
        conn.close()
