"""Cross-process lease for smeta base/index generation work."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator
from uuid import uuid4

from proxy.services.process_status import pid_running


INCOMPLETE_LOCK_GRACE_SECONDS = 30.0


@contextmanager
def generation_lease(
    root: Path,
    *,
    operation: str,
    pid_alive: Callable[[int], bool] = pid_running,
) -> Iterator[dict[str, object]]:
    """Own the exact generation root or fail before any builder mutation."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".smeta-generation.lock"
    owner_path = lock / "owner.json"
    token = uuid4().hex
    try:
        lock.mkdir()
    except FileExistsError:
        try:
            owner = json.loads(owner_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            owner = {}
        owner_pid = int(owner.get("pid") or 0)
        if owner_pid > 0 and pid_alive(owner_pid):
            raise RuntimeError(
                f"smeta generation update already running: pid={owner_pid}"
            )
        if owner_pid <= 0:
            try:
                lock_age = max(0.0, time.time() - lock.stat().st_mtime)
            except OSError as exc:
                raise RuntimeError("smeta generation update already running") from exc
            if lock_age < INCOMPLETE_LOCK_GRACE_SECONDS:
                raise RuntimeError("smeta generation update already running")
        owner_path.unlink(missing_ok=True)
        try:
            lock.rmdir()
            lock.mkdir()
        except OSError as exc:
            raise RuntimeError("smeta generation update already running") from exc
    owner = {
        "schema": "les.smeta.generation-lease.v1",
        "pid": os.getpid(),
        "operation": str(operation),
        "token": token,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    owner_path.write_text(
        json.dumps(owner, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        yield owner
    finally:
        try:
            current = json.loads(owner_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = {}
        if current.get("token") == token:
            owner_path.unlink(missing_ok=True)
            try:
                lock.rmdir()
            except OSError:
                pass
