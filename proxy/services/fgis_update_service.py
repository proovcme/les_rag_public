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
    "baseline": "проверка и восстановление ФСНБ",
    "starting": "запуск",
    "catalog": "каталог регионов и периодов",
    "price_books": "Сплит-формы",
    "gesn": "ГЭСН: нормы и ресурсы",
    "unify": "объединение базы ГЭСН",
    "structured": "сборка расчётной SQLite",
    "service_rag": "обновление навигационного индекса",
    "done": "готово",
    "failed": "ошибка",
    "retry": "автоматическое продолжение",
}

_LAYER_ORDER = (
    ("baseline", "Основа ФСНБ и ФСЭМ"),
    ("catalog", "Каталог регионов и периодов"),
    ("price_books", "Ресурсы и цены: Сплит-формы"),
    ("gesn", "Нормы ФСНБ: ГЭСН, ГЭСНм, ГЭСНп, ГЭСНр, ГЭСНмр"),
    ("unify", "Единый типизированный Parquet"),
    ("structured", "Расчётная база SQLite"),
    ("service_rag", "Поисковый индекс сметной базы"),
)


def _operator_reason(value: object) -> str:
    text = str(value or "").strip()
    low = text.casefold()
    if not text:
        return "Неизвестная ошибка обновления"
    if "permission denied" in low or "errno 13" in low:
        return "Нет доступа к локальному файлу. ЛЕС повторит операцию после освобождения файла."
    if "timed out" in low or "timeout" in low:
        return "ФГИС не ответил вовремя. ЛЕС повторяет запрос и продолжит с контрольной точки."
    if "json" in low:
        return "ФГИС вернул повреждённый ответ. ЛЕС повторяет запрос с контрольной точки."
    if "url" in low or "connection" in low or "network" in low:
        return "Нет устойчивого соединения с ФГИС. Уже скачанное сохранено; ЛЕС повторит запрос."
    return text


def _layers(raw: dict[str, Any], *, running: bool) -> list[dict[str, Any]]:
    current_stage = str(raw.get("stage") or "")
    effective_stage = str(raw.get("retry_stage") or raw.get("failed_stage") or current_stage)
    current_index = next((i for i, item in enumerate(_LAYER_ORDER) if item[0] == effective_stage), -1)
    finished = str(raw.get("status") or "") in {"done", "partial"}
    failed = str(raw.get("status") or "") == "failed"
    layers: list[dict[str, Any]] = []
    for index, (key, label) in enumerate(_LAYER_ORDER):
        if finished:
            state = "done"
        elif failed and key == effective_stage:
            state = "error"
        elif index < current_index:
            state = "done"
        elif running and index == current_index:
            state = "running"
        else:
            state = "pending"
        item: dict[str, Any] = {"id": key, "label": label, "state": state}
        if key == "baseline" and isinstance(raw.get("baseline"), dict):
            item["detail"] = raw["baseline"].get("message")
        elif key == "price_books" and isinstance(raw.get("prices"), dict):
            item["detail"] = f"{raw['prices'].get('done', 0)}/{raw['prices'].get('requested', 0)} книг"
        elif key == effective_stage:
            item["detail"] = str(raw.get("message") or "")
        if key == "price_books" and finished and int((raw.get("prices") or {}).get("failed") or 0):
            item["state"] = "warning"
        layers.append(item)
    return layers


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
        reason = _operator_reason(raw.get("error") or "Обновление завершилось ошибкой")
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
    process_running = bool(pid and pid_running(pid))
    raw = _read_json(DEFAULT_STATUS)
    from proxy.services import gesn_update_service

    gesn = gesn_update_service.status()
    dependency = {
        "running": bool(gesn.get("running")),
        "progress": gesn.get("progress") or {},
        "stage": (gesn.get("status") or {}).get("stage"),
    }
    running = process_running or bool(dependency["running"])
    normalized_progress = _progress(raw, running=process_running)
    if dependency["running"] and not process_running:
        gesn_progress = dependency["progress"]
        total = int(gesn_progress.get("collection_total") or 0) or None
        completed = max(0, int(gesn_progress.get("collection_index") or 1) - 1)
        normalized_progress.update(
            {
                "state": "running",
                "stage": "gesn",
                "stage_label": _STAGE_LABELS["gesn"],
                "reason": "Продолжается загрузка пяти семейств норм ФСНБ",
                "completed": completed,
                "total": total,
                "remaining": max(0, total - completed) if total else None,
                "percent": round(completed * 100 / total, 1) if total else None,
                "units": "collections",
                "current": {
                    "collection": gesn_progress.get("collection"),
                    "prefix": gesn_progress.get("current_prefix"),
                },
            }
        )
    layer_status = _layers(raw, running=process_running)
    if dependency["running"]:
        for item in layer_status:
            if item["id"] == "gesn":
                item["state"] = "running"
                item["detail"] = "Скачиваются пять семейств норм ФСНБ"
    return {
        "running": running,
        "process_running": process_running,
        "pid": pid if process_running else gesn.get("pid"),
        "status": raw,
        "progress": normalized_progress,
        "gesn_dependency": dependency,
        "catalog": {"path": str(DEFAULT_CATALOG), "exists": DEFAULT_CATALOG.exists()},
        "manifest": {"path": str(DEFAULT_MANIFEST), "exists": DEFAULT_MANIFEST.exists()},
        "log": str(_LOG),
        "log_tail": _tail(_LOG),
        "layers": layer_status,
    }


def start(*, include_gesn: bool = True, all_periods: bool = False) -> dict[str, Any]:
    current = status()
    if current["process_running"]:
        return {"ok": True, "started": False, **current}
    joined_existing_gesn = False
    if include_gesn:
        from proxy.services import gesn_update_service

        if gesn_update_service.status().get("running"):
            # Price books and GESN use different staging/canonical files.  Keep
            # the already-running GESN job and start only the missing price
            # part instead of turning the operator's click into a dead end.
            include_gesn = False
            joined_existing_gesn = True
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
    cmd = [sys.executable, "-m", "tools.fgis_update_supervisor"]
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
    return {
        "ok": True,
        "started": True,
        "joined_existing_gesn": joined_existing_gesn,
        "message": (
            "Сплит-формы запущены; уже выполняющееся обновление ГЭСН продолжает работу отдельно."
            if joined_existing_gesn
            else "Полное обновление ФГИС ЦС запущено."
        ),
        **status(),
    }
