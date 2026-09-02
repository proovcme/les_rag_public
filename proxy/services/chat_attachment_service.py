"""Server-owned short-lived files attached to a chat turn.

The client receives an opaque id, never a filesystem path.  Consumers resolve
that id inside the configured root and may consume the file after a successful
one-shot workflow.  This keeps document workflows lossless without widening the
chat API into an arbitrary local-file reader.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from backend.runtime_paths import mutable_path


DEFAULT_ROOT = Path(os.getenv("LES_CHAT_ATTACHMENT_ROOT", "storage/chat_attachments"))
DEFAULT_MAX_AGE_SEC = int(os.getenv("LES_CHAT_ATTACHMENT_MAX_AGE_SEC", str(7 * 24 * 3600)))
_ID_RE = re.compile(r"^read_[0-9a-f]{12}$")


def _default_root() -> Path:
    configured = os.getenv("LES_CHAT_ATTACHMENT_ROOT", "").strip()
    return Path(configured) if configured else mutable_path("storage/chat_attachments")


def _safe_id(attachment_id: str) -> str:
    value = str(attachment_id or "").strip().lower()
    if not _ID_RE.fullmatch(value):
        raise ValueError("invalid chat attachment id")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _paths(attachment_id: str, root: str | Path | None = None) -> tuple[Path, Path]:
    ident = _safe_id(attachment_id)
    base = (Path(root) if root is not None else _default_root()).resolve()
    return base / f"{ident}.json", base / ident


def cleanup_expired(
    *, root: str | Path | None = None, max_age_sec: int = DEFAULT_MAX_AGE_SEC
) -> int:
    base = Path(root) if root is not None else _default_root()
    if not base.exists():
        return 0
    now = time.time()
    removed = 0
    for metadata_path in base.glob("read_????????????.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            created_at = float(metadata.get("created_at_epoch") or metadata_path.stat().st_mtime)
            if now - created_at <= max_age_sec:
                continue
            file_path = base / str(metadata.get("stored_name") or "")
            file_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            removed += 1
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return removed


def preserve_read_attachment(
    source: str | Path,
    *,
    attachment_id: str,
    original_name: str,
    root: str | Path | None = None,
) -> dict[str, Any]:
    metadata_path, bare_path = _paths(attachment_id, root)
    base = metadata_path.parent
    base.mkdir(parents=True, exist_ok=True)
    suffix = Path(original_name).suffix.lower()
    stored_path = bare_path.with_suffix(suffix)
    temp_path = stored_path.with_suffix(stored_path.suffix + ".tmp")
    shutil.copy2(str(source), temp_path)
    temp_path.replace(stored_path)
    metadata = {
        "schema": "chat_read_attachment_v1",
        "attachment_id": _safe_id(attachment_id),
        "original_name": Path(original_name).name,
        "stored_name": stored_path.name,
        "suffix": suffix,
        "size": stored_path.stat().st_size,
        "sha256": _sha256(stored_path),
        "created_at_epoch": time.time(),
    }
    temp_metadata = metadata_path.with_suffix(".json.tmp")
    temp_metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_metadata.replace(metadata_path)
    return dict(metadata)


def resolve_read_attachment(
    attachment_id: str,
    *,
    root: str | Path | None = None,
    max_age_sec: int = DEFAULT_MAX_AGE_SEC,
) -> tuple[Path, dict[str, Any]]:
    metadata_path, _ = _paths(attachment_id, root)
    base = metadata_path.parent.resolve()
    if not metadata_path.is_file():
        raise FileNotFoundError("chat attachment not found")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("attachment_id") != _safe_id(attachment_id):
        raise ValueError("chat attachment metadata mismatch")
    created_at = float(metadata.get("created_at_epoch") or 0)
    if created_at <= 0 or time.time() - created_at > max_age_sec:
        consume_read_attachment(attachment_id, root=root)
        raise FileNotFoundError("chat attachment expired")
    stored_name = str(metadata.get("stored_name") or "")
    file_path = (base / stored_name).resolve()
    if base not in file_path.parents or not file_path.is_file():
        raise FileNotFoundError("chat attachment source missing")
    if file_path.stat().st_size != int(metadata.get("size") or -1):
        raise ValueError("chat attachment size mismatch")
    if _sha256(file_path) != str(metadata.get("sha256") or ""):
        raise ValueError("chat attachment hash mismatch")
    return file_path, dict(metadata)


def consume_read_attachment(attachment_id: str, *, root: str | Path | None = None) -> None:
    metadata_path, _ = _paths(attachment_id, root)
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata = {}
    stored_name = str(metadata.get("stored_name") or "")
    if stored_name:
        file_path = (metadata_path.parent.resolve() / stored_name).resolve()
        if metadata_path.parent.resolve() in file_path.parents:
            file_path.unlink(missing_ok=True)
    metadata_path.unlink(missing_ok=True)
