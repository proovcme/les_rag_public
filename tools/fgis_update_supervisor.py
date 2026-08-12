"""Keep the operator-started FGIS/FSNB update alive and resume from checkpoints."""

from __future__ import annotations

import argparse
import atexit
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from tools.fgis_full_update import DEFAULT_STATUS, _read_json, _write_json

_LOCK = Path("storage/jobs/fgis_full_update.lock")


def _release_lock() -> None:
    try:
        if not _LOCK.exists():
            return
        raw = _LOCK.read_text(encoding="utf-8").strip()
        token = raw.split(":", 1)[-1] if raw else ""
        if token == str(os.getpid()) or raw.startswith("pending:"):
            _LOCK.unlink(missing_ok=True)
    except Exception:
        pass


def _acquire_lock() -> bool:
    """Claim the lock created by start() (pending:<proxy>) or create one."""
    from proxy.services.process_status import pid_running

    _LOCK.parent.mkdir(parents=True, exist_ok=True)
    if _LOCK.exists():
        try:
            raw = _LOCK.read_text(encoding="utf-8").strip()
        except Exception:
            raw = ""
        if raw.startswith("pending:"):
            _LOCK.write_text(str(os.getpid()), encoding="utf-8")
            atexit.register(_release_lock)
            return True
        token = raw.split(":", 1)[-1] if raw else ""
        try:
            existing = int(token) if token.isdigit() else 0
        except Exception:
            existing = 0
        if existing == os.getpid() or not (existing and pid_running(existing)):
            _LOCK.write_text(str(os.getpid()), encoding="utf-8")
            atexit.register(_release_lock)
            return True
        print(
            f"[fgis-supervisor] lock held by live pid={existing}; skip duplicate start",
            flush=True,
        )
        return False
    try:
        fd = os.open(str(_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    except FileExistsError:
        print("[fgis-supervisor] lock race; skip duplicate start", flush=True)
        return False
    atexit.register(_release_lock)
    return True


def run_supervised(*, include_gesn: bool, all_periods: bool, attempts: int = 5) -> int:
    if not _acquire_lock():
        return 0

    command = [sys.executable, "-m", "tools.fgis_full_update"]
    if not include_gesn:
        command.append("--skip-gesn")
    if all_periods:
        command.append("--all-periods")
    print(f"[fgis-supervisor] start pid={os.getpid()} cmd={' '.join(command)}", flush=True)

    try:
        for attempt in range(1, max(1, attempts) + 1):
            code = subprocess.run(
                command,
                cwd=str(Path(__file__).resolve().parents[1]),
                check=False,
            ).returncode
            status = _read_json(DEFAULT_STATUS)
            if code == 0 and status.get("status") == "done":
                return 0
            if attempt >= max(1, attempts):
                return code or 1
            delay = min(60, 5 * (2 ** (attempt - 1)))
            _write_json(
                DEFAULT_STATUS,
                {
                    **status,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "status": "running",
                    "stage": "retry",
                    "retry_stage": status.get("failed_stage") or status.get("stage"),
                    "activity": "self_repair",
                    "message": "ЛЕС сохраняет уже скачанное и автоматически продолжает обновление",
                    "retry": {
                        "attempt": attempt + 1,
                        "maximum": max(1, attempts),
                        "delay_seconds": delay,
                    },
                },
            )
            time.sleep(delay)
        return 1
    finally:
        _release_lock()
        try:
            atexit.unregister(_release_lock)
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-gesn", action="store_true")
    parser.add_argument("--all-periods", action="store_true")
    parser.add_argument("--attempts", type=int, default=5)
    args = parser.parse_args()
    return run_supervised(
        include_gesn=not args.skip_gesn,
        all_periods=args.all_periods,
        attempts=args.attempts,
    )


if __name__ == "__main__":
    raise SystemExit(main())
