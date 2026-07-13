"""Background updater for the single GESN unified base."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.build_smeta_structured_base import DEFAULT_MANIFEST as DEFAULT_STRUCTURED_MANIFEST
from tools.build_smeta_structured_base import DEFAULT_OUT as DEFAULT_STRUCTURED_OUT
from tools.build_smeta_service_rag import DEFAULT_OUT as DEFAULT_SERVICE_RAG_OUT
from tools.gesn_update_from_fgis import DEFAULT_STATUS
from tools.gesn_unify_base import DEFAULT_AUDIT, DEFAULT_OUT
from proxy.services.process_status import pid_running

_ROOT = Path(__file__).resolve().parents[2]
_LOG = Path("storage/jobs/gesn_fgis_update.log")
_PID = Path("storage/jobs/gesn_fgis_update.pid")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _tail(path: Path, limit: int = 30) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except Exception:
        return []


def status() -> dict[str, Any]:
    pid = int(_PID.read_text().strip()) if _PID.exists() and _PID.read_text().strip().isdigit() else 0
    running = bool(pid and pid_running(pid))
    unified = DEFAULT_OUT
    audit = DEFAULT_AUDIT
    structured = DEFAULT_STRUCTURED_OUT
    structured_manifest = DEFAULT_STRUCTURED_MANIFEST
    service_rag_overview = DEFAULT_SERVICE_RAG_OUT / "00_smeta_service_overview.md"
    return {
        "running": running,
        "pid": pid if running else None,
        "status": _read_json(DEFAULT_STATUS),
        "unified": {
            "path": str(unified),
            "exists": unified.exists(),
            "size_bytes": unified.stat().st_size if unified.exists() else 0,
        },
        "audit": {
            "path": str(audit),
            "exists": audit.exists(),
            "size_bytes": audit.stat().st_size if audit.exists() else 0,
        },
        "structured": {
            "path": str(structured),
            "exists": structured.exists(),
            "size_bytes": structured.stat().st_size if structured.exists() else 0,
        },
        "structured_manifest": {
            "path": str(structured_manifest),
            "exists": structured_manifest.exists(),
            "size_bytes": structured_manifest.stat().st_size if structured_manifest.exists() else 0,
        },
        "service_rag": {
            "path": str(DEFAULT_SERVICE_RAG_OUT),
            "overview_exists": service_rag_overview.exists(),
            "overview_size_bytes": service_rag_overview.stat().st_size if service_rag_overview.exists() else 0,
        },
        "log": str(_LOG),
        "log_tail": _tail(_LOG),
    }


def start(*, rate: float = 1.0, limit: int | None = None) -> dict[str, Any]:
    current = status()
    if current.get("running"):
        return {"ok": True, "started": False, **current}
    from proxy.services import fgis_update_service

    if fgis_update_service.status().get("running"):
        return {
            "ok": False,
            "started": False,
            "reason": "fgis_update_running",
            "message": "Общее обновление ФГИС ЦС уже включает ГЭСН.",
            **current,
        }
    _LOG.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "tools.gesn_update_from_fgis", "--all", "--rate", str(rate)]
    if limit is not None:
        cmd.extend(["--limit", str(int(limit))])
    with _LOG.open("ab") as log:
        proc = subprocess.Popen(cmd, cwd=str(_ROOT), stdout=log, stderr=subprocess.STDOUT)
    _PID.write_text(str(proc.pid), encoding="utf-8")
    return {"ok": True, "started": True, **status()}
