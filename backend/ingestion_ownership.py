"""Per-file ownership for the indexing replace window.

Replacing one file's evidence is not a single atomic operation: the adapter
upserts the new Qdrant points and FTS rows, then retires the exact old ids it
read at the start. Concurrent parses can capture the same old ids and leave
both replacements present, violating the recorded point count. Ownership must
cover the entire capture, write and retirement window.

The lock is deliberately scoped to one dataset and one file so unrelated
documents keep indexing in parallel; a global lock would serialize the whole
corpus to fix a per-file race.
"""

from __future__ import annotations

import hashlib
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None  # type: ignore[assignment]

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX
    msvcrt = None  # type: ignore[assignment]


_LOCK_DIRECTORY = "ingestion-locks"
_POLL_SECONDS = 0.05


def _default_root() -> Path:
    from backend.rag_config import rag_meta_db_path

    return Path(rag_meta_db_path()).resolve().parent


def ingestion_lock_path(dataset_id: str, file_key: str, *, root: str | Path | None = None) -> Path:
    """Return one stable lock file per dataset/file pair.

    The name is a digest: a file key is user data and may contain separators,
    traversal segments or characters this filesystem rejects.
    """
    base = Path(root) if root is not None else _default_root()
    digest = hashlib.sha256(f"{dataset_id}\n{file_key}".encode("utf-8")).hexdigest()
    return base / _LOCK_DIRECTORY / f"{digest}.lock"


def _try_acquire(handle: int) -> bool:
    if msvcrt is not None:
        try:
            msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    if fcntl is not None:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False
    # No advisory locking available: refuse to pretend the window is protected.
    raise RuntimeError("no file locking primitive is available on this platform")


def _release(handle: int) -> None:
    if msvcrt is not None:
        try:
            os.lseek(handle, 0, os.SEEK_SET)
            msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    if fcntl is not None:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        except OSError:
            pass


@contextmanager
def file_ingestion_lock(
    dataset_id: str,
    file_key: str,
    *,
    root: str | Path | None = None,
    timeout_seconds: float = 900.0,
) -> Iterator[Path]:
    """Hold exclusive ownership of one file's replace window."""
    path = ingestion_lock_path(dataset_id, file_key, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    try:
        while True:
            os.lseek(handle, 0, os.SEEK_SET)
            if _try_acquire(handle):
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"another indexing run holds {dataset_id}/{file_key}"
                )
            time.sleep(_POLL_SECONDS)
        try:
            yield path
        finally:
            os.lseek(handle, 0, os.SEEK_SET)
            _release(handle)
    finally:
        os.close(handle)
