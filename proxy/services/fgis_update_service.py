"""Background operator job for the complete public FGIS CS source update."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.fgis_full_update import DEFAULT_CATALOG, DEFAULT_MANIFEST, DEFAULT_STATUS
from proxy.services.process_status import pid_running

_ROOT = Path(__file__).resolve().parents[2]
_LOG = Path("storage/jobs/fgis_full_update.log")
_PID = Path("storage/jobs/fgis_full_update.pid")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def status() -> dict[str, Any]:
    raw_pid = _PID.read_text().strip() if _PID.exists() else ""
    pid = int(raw_pid) if raw_pid.isdigit() else 0
    running = bool(pid and pid_running(pid))
    return {
        "running": running,
        "pid": pid if running else None,
        "status": _read_json(DEFAULT_STATUS),
        "catalog": {"path": str(DEFAULT_CATALOG), "exists": DEFAULT_CATALOG.exists()},
        "manifest": {"path": str(DEFAULT_MANIFEST), "exists": DEFAULT_MANIFEST.exists()},
        "log": str(_LOG),
    }


def start(*, include_gesn: bool = True, all_periods: bool = False) -> dict[str, Any]:
    current = status()
    if current["running"]:
        return {"ok": True, "started": False, **current}
    if include_gesn:
        from proxy.services import gesn_update_service

        if gesn_update_service.status().get("running"):
            return {
                "ok": False,
                "started": False,
                "reason": "gesn_update_running",
                "message": "Отдельное обновление ГЭСН уже выполняется; дождитесь его завершения.",
                **current,
            }
    _LOG.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "tools.fgis_full_update"]
    if not include_gesn:
        cmd.append("--skip-gesn")
    if all_periods:
        cmd.append("--all-periods")
    with _LOG.open("ab") as log:
        proc = subprocess.Popen(cmd, cwd=str(_ROOT), stdout=log, stderr=subprocess.STDOUT)
    _PID.write_text(str(proc.pid), encoding="utf-8")
    return {"ok": True, "started": True, **status()}
