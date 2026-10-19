"""Server-owned short-lived files attached to a chat turn.

The client receives an opaque id, never a filesystem path.  Consumers resolve
that id inside the configured root and may consume the file after a successful
one-shot workflow.  This keeps document workflows lossless without widening the
chat API into an arbitrary local-file reader.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import time
import zipfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.runtime_paths import mutable_path


DEFAULT_ROOT = Path(os.getenv("LES_CHAT_ATTACHMENT_ROOT", "storage/chat_attachments"))
DEFAULT_MAX_AGE_SEC = int(os.getenv("LES_CHAT_ATTACHMENT_MAX_AGE_SEC", str(7 * 24 * 3600)))
_ID_RE = re.compile(r"^read_[0-9a-f]{12}$")
_METADATA_LOCK_TIMEOUT_SEC = 5.0


@contextmanager
def _attachment_metadata_lock(metadata_path: Path):
    """Serialize readers and mutations across threads/processes on this source.

    The lock file is deliberately persistent: unlinking it could let a new
    caller lock a different inode while an earlier caller still owns the old
    one. The OS releases the lock if the owning process exits.
    """
    lock_path = metadata_path.with_suffix(".lock")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    locked = False
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
        deadline = time.monotonic() + _METADATA_LOCK_TIMEOUT_SEC
        while True:
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError("chat attachment metadata is busy") from exc
                time.sleep(0.01)
        yield
    finally:
        try:
            if locked:
                os.lseek(descriptor, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


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


def docx_is_image_only(path: Path) -> bool:
    """Detect a scan container; converter image labels are not document text.

    Unknown/malformed packages remain the converter's responsibility. Embedded
    altChunk content may contain text, so it must not be classified as a scan.
    Both transitional and strict OOXML use the same local element names.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError):
        return False
    has_image = False
    for element in document.iter():
        name = element.tag.rsplit("}", 1)[-1]
        if name == "altChunk":
            return False
        if name == "t" and "".join(element.itertext()).strip():
            return False
        if name in {"drawing", "pict"}:
            has_image = True
    return has_image


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
            with _attachment_metadata_lock(metadata_path):
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if metadata.get("retained_for_workbook") is True:
                    continue
                created_at = float(metadata.get("created_at_epoch") or metadata_path.stat().st_mtime)
                if now - created_at <= max_age_sec:
                    continue
                _consume_read_attachment_unlocked(metadata_path)
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
    with _attachment_metadata_lock(metadata_path):
        return _preserve_read_attachment_unlocked(source, metadata_path=metadata_path,
            bare_path=bare_path, attachment_id=attachment_id, original_name=original_name)


def _preserve_read_attachment_unlocked(
    source: str | Path, *, metadata_path: Path, bare_path: Path,
    attachment_id: str, original_name: str,
) -> dict[str, Any]:
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
    if not metadata_path.parent.is_dir():
        raise FileNotFoundError("chat attachment not found")
    with _attachment_metadata_lock(metadata_path):
        return _resolve_read_attachment_unlocked(attachment_id, metadata_path, max_age_sec=max_age_sec)


def _resolve_read_attachment_unlocked(
    attachment_id: str, metadata_path: Path, *, max_age_sec: float,
) -> tuple[Path, dict[str, Any]]:
    base = metadata_path.parent.resolve()
    if not metadata_path.is_file():
        raise FileNotFoundError("chat attachment not found")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("attachment_id") != _safe_id(attachment_id):
        raise ValueError("chat attachment metadata mismatch")
    created_at = float(metadata.get("created_at_epoch") or 0)
    if (created_at <= 0 or time.time() - created_at > max_age_sec) and metadata.get("retained_for_workbook") is not True:
        _consume_read_attachment_unlocked(metadata_path)
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


def retain_read_attachment_for_workbook(
    attachment_id: str, *, expected_sha256: str, root: str | Path | None = None,
) -> dict[str, Any]:
    """Keep a successfully read typed source for durable workbook continuation.

    Only server callers invoke this after loading the actual catalog. The exact
    source hash is checked again; bytes and their identity are never changed.
    """
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("invalid workbook source hash")
    # The caller already admitted the source before catalog extraction. Crossing
    # its TTL during that read must not delete it before this hash-verified pin.
    _source, metadata = resolve_read_attachment(attachment_id, root=root, max_age_sec=float("inf"))
    if metadata.get("sha256") != expected_sha256:
        raise ValueError("workbook source hash mismatch")
    if metadata.get("retained_for_workbook") is True:
        return metadata
    metadata_path, _ = _paths(attachment_id, root)
    pending = metadata_path.with_name(metadata_path.name + f".{uuid4().hex}.retain.tmp")
    retained = {**metadata, "retained_for_workbook": True}
    try:
        pending.write_text(json.dumps(retained, ensure_ascii=False, indent=2), encoding="utf-8")
        with _attachment_metadata_lock(metadata_path):
            _source, current = _resolve_read_attachment_unlocked(
                attachment_id, metadata_path, max_age_sec=float("inf"))
            if current.get("sha256") != expected_sha256:
                raise ValueError("workbook source hash mismatch")
            if current.get("retained_for_workbook") is True:
                return current
            # A replaced source must not inherit stale metadata from staging.
            if current != metadata:
                retained = {**current, "retained_for_workbook": True}
                pending.write_text(json.dumps(retained, ensure_ascii=False, indent=2), encoding="utf-8")
            pending.replace(metadata_path)
    finally:
        pending.unlink(missing_ok=True)
    return retained


def consume_read_attachment(
    attachment_id: str, *, root: str | Path | None = None, force: bool = False,
) -> None:
    metadata_path, _ = _paths(attachment_id, root)
    if not metadata_path.parent.is_dir():
        return
    with _attachment_metadata_lock(metadata_path):
        _consume_read_attachment_unlocked(metadata_path, force=force)


def _consume_read_attachment_unlocked(metadata_path: Path, *, force: bool = False) -> None:
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata = {}
    if metadata.get("retained_for_workbook") is True and not force:
        return
    stored_name = str(metadata.get("stored_name") or "")
    if stored_name:
        file_path = (metadata_path.parent.resolve() / stored_name).resolve()
        if metadata_path.parent.resolve() in file_path.parents:
            file_path.unlink(missing_ok=True)
    metadata_path.unlink(missing_ok=True)
