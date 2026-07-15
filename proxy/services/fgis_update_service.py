"""Background operator job for the complete public FGIS CS source update."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
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


def _tail(path: Path, limit: int = 30) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except Exception:
        return []


_STAGE_LABELS = {
    "starting": "запуск",
    "catalog": "каталог регионов и периодов",
    "price_books": "Сплит-формы",
    "gesn": "ГЭСН: нормы и ресурсы",
    "unify": "объединение базы ГЭСН",
    "structured": "сборка расчётной SQLite",
    "service_rag": "обновление навигационного индекса",
    "done": "готово",
    "failed": "ошибка",
}


def _heartbeat_age(value: object) -> float | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds())
    except (TypeError, ValueError):
        return None


def _progress(raw: dict[str, Any], *, running: bool) -> dict[str, Any]:
    status_name = str(raw.get("status") or "")
    stage = str(raw.get("stage") or ("starting" if running else "idle"))
    completed = raw.get("completed")
    total = raw.get("total")
    remaining = raw.get("remaining")
    percent = raw.get("percent")
    current = raw.get("current") or {}
    eta_seconds = raw.get("eta_seconds")
    units = "books"

    if stage == "gesn":
        gesn = raw.get("gesn_progress") or {}
        completed = max(0, int(gesn.get("collection_index") or 1) - 1)
        total = int(gesn.get("collection_total") or 0) or None
        remaining = max(0, total - completed) if total else None
        percent = round(completed * 100 / total, 1) if total else None
        current = {
            "collection": gesn.get("collection"),
            "prefix": gesn.get("current_prefix"),
            "norms": gesn.get("norms"),
            "resources": gesn.get("resources"),
        }
        eta_seconds = None
        units = "collections"

    if status_name in {"done", "partial"}:
        state = status_name
        percent = 100.0
        reason = "Обновление завершено" if status_name == "done" else "Обновление завершено с отдельными ошибками"
    elif status_name == "failed":
        state = "failed"
        reason = str(raw.get("error") or "Обновление завершилось ошибкой")
    elif running:
        state = "running"
        reason = str(raw.get("message") or "Фоновый процесс работает")
    elif status_name == "running":
        state = "interrupted"
        reason = "Процесс больше не работает и не записал итоговый статус"
    else:
        state = "idle"
        reason = "Обновление ещё не запускалось"

    age = _heartbeat_age(raw.get("updated_at"))
    if running and age is not None and age > 150:
        reason = "Процесс работает; ждём ответ ФГИС или завершение текущей длительной операции"

    return {
        "state": state,
        "stage": stage,
        "stage_label": _STAGE_LABELS.get(stage, stage or "ожидание"),
        "activity": str(raw.get("activity") or ""),
        "reason": reason,
        "completed": completed,
        "total": total,
        "remaining": remaining,
        "percent": percent,
        "eta_seconds": eta_seconds,
        "elapsed_seconds": raw.get("elapsed_seconds"),
        "bytes_downloaded": int(raw.get("bytes_downloaded") or 0),
        "rate_bytes_per_second": raw.get("rate_bytes_per_second"),
        "units": units,
        "current": current,
        "updated_at": raw.get("updated_at"),
        "heartbeat_age_seconds": round(age, 1) if age is not None else None,
    }


def status() -> dict[str, Any]:
    raw_pid = _PID.read_text().strip() if _PID.exists() else ""
    pid = int(raw_pid) if raw_pid.isdigit() else 0
    running = bool(pid and pid_running(pid))
    raw = _read_json(DEFAULT_STATUS)
    return {
        "running": running,
        "pid": pid if running else None,
        "status": raw,
        "progress": _progress(raw, running=running),
        "catalog": {"path": str(DEFAULT_CATALOG), "exists": DEFAULT_CATALOG.exists()},
        "manifest": {"path": str(DEFAULT_MANIFEST), "exists": DEFAULT_MANIFEST.exists()},
        "log": str(_LOG),
        "log_tail": _tail(_LOG),
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
    DEFAULT_STATUS.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_STATUS.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "status": "running",
                "stage": "starting",
                "activity": "starting",
                "message": "Запускаем фоновое обновление ФГИС ЦС",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    cmd = [sys.executable, "-m", "tools.fgis_full_update"]
    if not include_gesn:
        cmd.append("--skip-gesn")
    if all_periods:
        cmd.append("--all-periods")
    try:
        with _LOG.open("ab") as log:
            proc = subprocess.Popen(cmd, cwd=str(_ROOT), stdout=log, stderr=subprocess.STDOUT)
    except Exception as exc:
        DEFAULT_STATUS.write_text(
            json.dumps(
                {
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "status": "failed",
                    "stage": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {"ok": False, "started": False, **status()}
    _PID.write_text(str(proc.pid), encoding="utf-8")
    return {"ok": True, "started": True, **status()}
