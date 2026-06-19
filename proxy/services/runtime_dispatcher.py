"""Runtime dispatcher for memory-aware guarded reindex control."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


def _fmt_dur(seconds: float) -> str:
    """Секунды → человекочитаемая длительность («~45с», «~12м», «~1ч 20м»)."""
    s = int(max(0, seconds))
    if s < 90:
        return f"~{s}с"
    m = s // 60
    if m < 90:
        return f"~{m}м"
    return f"~{m // 60}ч {m % 60}м"


def compute_eta(started_at: Any, completed: Any, total: Any, *, running: bool = True,
                now_ts: float | None = None) -> dict[str, Any]:
    """Оценка времени индексации из старта+скорости. Чистая функция (числа считает код, не LLM).

    Возвращает percent + (если идёт и есть прогресс) elapsed/eta/rate. ETA — оценка по средней
    скорости с начала текущего прогона: на резюме может слегка плыть, поэтому всегда «~».
    """
    out: dict[str, Any] = {"percent": None, "elapsed_seconds": None,
                           "eta_seconds": None, "eta_text": "", "rate_per_min": None}
    try:
        total_i, done_i = int(total or 0), int(completed or 0)
    except (TypeError, ValueError):
        return out
    if total_i > 0:
        out["percent"] = round(100.0 * min(done_i, total_i) / total_i, 1)
    if not running or not started_at or done_i <= 0 or total_i <= 0 or done_i >= total_i:
        return out
    try:
        started = datetime.fromisoformat(str(started_at))
    except (TypeError, ValueError):
        return out
    now = datetime.fromtimestamp(now_ts) if now_ts is not None else datetime.now()
    elapsed = (now - started).total_seconds()
    if elapsed <= 0:
        return out
    rate = done_i / elapsed  # док/сек
    eta = (total_i - done_i) / rate if rate > 0 else None
    out["elapsed_seconds"] = round(elapsed)
    out["rate_per_min"] = round(rate * 60, 1)
    if eta is not None:
        out["eta_seconds"] = round(eta)
        out["eta_text"] = _fmt_dur(eta)
    return out

from backend.rag_config import rag_collection_name, rag_meta_db_path
from proxy.services.resource_governor import current_runtime_profile, is_indexing_mode
from proxy.services.runtime_admission import evaluate_memory_pressure
from tools import les_runtime_control
from tools import reindex_datasets_guarded as guarded


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASETS = ["NTD_HVAC_Index", "NTD_FIRE_Index"]
DEFAULT_REINDEX_MAX_SWAP_PCT = 85.0
DEFAULT_REINDEX_POST_MAX_SWAP_PCT = 80.0
DEFAULT_PID_FILE = "guarded_reindex_hvac_fire.pid.json"
DEFAULT_STOP_FILE = "guarded_reindex_hvac_fire.stop.json"
ROUTE_CHANGE_PID_FILE = "guarded_reindex_route_changes.pid.json"
ROUTE_CHANGE_STOP_FILE = "guarded_reindex_route_changes.stop.json"
ROUTE_CHANGE_STATE_FILE = "reindex_state_route_changes.json"


class DispatcherError(RuntimeError):
    def __init__(self, status_code: int, detail: str, payload: dict[str, Any] | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.payload = payload or {}


def _json_default(value: Any) -> Any:
    try:
        return asdict(value)
    except TypeError:
        return str(value)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        return {"error": str(error)}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        status = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        ).stdout.strip()
        if status.startswith("Z"):
            return False
    except Exception:
        pass
    return True


def _tail_json_events(path: Path, *, max_bytes: int = 256_000) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            raw = handle.read().decode("utf-8", errors="replace")
    except Exception:
        return []
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


class RuntimeDispatcher:
    """Small source of truth for runtime memory and guarded reindex state."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        current_mode: dict[str, Any] | None = None,
        metrics_cache: dict[str, Any] | None = None,
        memory_preflight_fn: Callable[..., Any] = les_runtime_control.build_memory_preflight,
        service_status_fn: Callable[..., Any] = les_runtime_control.all_statuses,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        pid_running_fn: Callable[[int], bool] = _pid_running,
    ):
        self.root = root or ROOT
        self.current_mode = current_mode or {}
        self.metrics_cache = metrics_cache or {}
        self.memory_preflight_fn = memory_preflight_fn
        self.service_status_fn = service_status_fn
        self.popen_factory = popen_factory
        self.pid_running_fn = pid_running_fn

    @property
    def artifacts_dir(self) -> Path:
        return self.root / "artifacts" / "reindex_runs"

    @property
    def pid_file(self) -> Path:
        return self.artifacts_dir / DEFAULT_PID_FILE

    @property
    def stop_file(self) -> Path:
        return self.artifacts_dir / DEFAULT_STOP_FILE

    @property
    def route_change_pid_file(self) -> Path:
        return self.artifacts_dir / ROUTE_CHANGE_PID_FILE

    @property
    def route_change_stop_file(self) -> Path:
        return self.artifacts_dir / ROUTE_CHANGE_STOP_FILE

    @property
    def route_change_state_file(self) -> Path:
        return self.artifacts_dir / ROUTE_CHANGE_STATE_FILE

    def state_file(self, datasets: list[str] | None = None) -> Path:
        return guarded.default_state_file(str(self.artifacts_dir), datasets or DEFAULT_DATASETS)

    def status_payload(
        self,
        *,
        datasets: list[str] | None = None,
        min_free_gb: float = 4.0,
        max_swap_pct: float = DEFAULT_REINDEX_MAX_SWAP_PCT,
        include_services: bool = True,
    ) -> dict[str, Any]:
        datasets = datasets or DEFAULT_DATASETS
        preflight = self._memory_preflight(min_free_gb=min_free_gb)
        memory_decision = self._memory_decision(preflight, min_free_gb=min_free_gb, max_swap_pct=max_swap_pct)
        pressure = evaluate_memory_pressure(self._metrics_for_pressure(preflight))
        reindex = self._reindex_status(datasets=datasets, min_free_gb=min_free_gb, max_swap_pct=max_swap_pct)
        services = self._services_status() if include_services else []
        actions = {
            "can_start": (not reindex["running"]) and memory_decision["allowed"],
            "can_pause": bool(reindex["running"] and reindex.get("supports_pause")),
            "can_resume": bool((not reindex["running"]) and reindex["state_exists"] and reindex["remaining"] > 0),
            "can_unload_mlx": True,
            "blocked_reason": "" if memory_decision["allowed"] else memory_decision["reason"],
        }
        return {
            "component": "runtime_dispatcher",
            "policy": "wait_only",
            "mode": self.current_mode,
            "runtime_profile": current_runtime_profile(self.current_mode),
            "indexing_mode": is_indexing_mode(self.current_mode),
            "memory": {
                "pressure": pressure.payload(),
                "preflight": asdict(preflight),
                "decision": memory_decision,
                "recommendations": self._memory_recommendations(preflight, pressure.payload(), memory_decision, reindex),
            },
            "services": services,
            "reindex": reindex,
            "actions": actions,
        }

    def reindex_status_payload(
        self,
        *,
        datasets: list[str] | None = None,
        min_free_gb: float = 4.0,
        max_swap_pct: float = DEFAULT_REINDEX_MAX_SWAP_PCT,
    ) -> dict[str, Any]:
        return self._reindex_status(
            datasets=datasets or DEFAULT_DATASETS,
            min_free_gb=min_free_gb,
            max_swap_pct=max_swap_pct,
        )

    def start_reindex(
        self,
        *,
        datasets: list[str] | None = None,
        min_free_gb: float = 4.0,
        max_swap_pct: float = DEFAULT_REINDEX_MAX_SWAP_PCT,
        post_min_free_gb: float = 3.0,
        post_max_swap_pct: float | None = None,
        memory_wait_sec: float = 86400.0,
        memory_poll_sec: float = 30.0,
        cooldown_sec: float = 90.0,
        parse_timeout: float = 3600.0,
        parse_method: str = "scheduler",
        unload_between_docs: bool = True,
        auth_smoke_after: bool = True,
        reset_state: bool = False,
        resume: bool = False,
    ) -> dict[str, Any]:
        datasets = datasets or DEFAULT_DATASETS
        post_max_swap_pct = (
            min(max_swap_pct, DEFAULT_REINDEX_POST_MAX_SWAP_PCT)
            if post_max_swap_pct is None
            else post_max_swap_pct
        )
        status = self.status_payload(
            datasets=datasets,
            min_free_gb=min_free_gb,
            max_swap_pct=max_swap_pct,
            include_services=False,
        )
        if status["reindex"]["running"]:
            status["status"] = "already_running"
            return status
        if resume and not status["reindex"]["state_exists"]:
            raise DispatcherError(409, "no guarded reindex state exists to resume", status)
        if not status["memory"]["decision"]["allowed"]:
            raise DispatcherError(503, status["memory"]["decision"]["reason"], status)

        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        if self.stop_file.exists():
            self.stop_file.unlink()
        stamp = time.strftime("%Y%m%d_%H%M%S")
        log_path = self.artifacts_dir / f"one_click_hvac_fire_{stamp}.out"
        state_path = self.state_file(datasets)
        cmd = [
            sys.executable,
            "tools/reindex_datasets_guarded.py",
            "--datasets",
            *datasets,
            "--parse-method",
            parse_method,
            "--state-file",
            str(state_path),
            "--stop-file",
            str(self.stop_file),
            "--min-free-gb",
            str(min_free_gb),
            "--max-swap-pct",
            str(max_swap_pct),
            "--post-min-free-gb",
            str(post_min_free_gb),
            "--post-max-swap-pct",
            str(post_max_swap_pct),
            "--memory-wait-sec",
            str(memory_wait_sec),
            "--memory-poll-sec",
            str(memory_poll_sec),
            "--cooldown-sec",
            str(cooldown_sec),
            "--parse-timeout",
            str(parse_timeout),
        ]
        cmd.append("--unload-between-docs" if unload_between_docs else "--no-unload-between-docs")
        cmd.append("--auth-smoke-after" if auth_smoke_after else "--no-auth-smoke-after")
        if reset_state and not resume:
            cmd.append("--reset-state")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        with log_path.open("ab") as output:
            process = self.popen_factory(
                cmd,
                cwd=self.root,
                stdout=output,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
                env=env,
            )
        _write_json(
            self.pid_file,
            {
                "pid": int(process.pid),
                "cmd": cmd,
                "log_path": str(log_path),
                "state_file": str(state_path),
                "stop_file": str(self.stop_file),
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "datasets": datasets,
                "dispatcher": "v0",
            },
        )
        result = self.status_payload(
            datasets=datasets,
            min_free_gb=min_free_gb,
            max_swap_pct=max_swap_pct,
            include_services=False,
        )
        result["status"] = "resumed" if resume else "started"
        return result

    def pause_reindex(self, *, reason: str = "operator") -> dict[str, Any]:
        status = self.status_payload(include_services=False)
        reindex = status["reindex"]
        if not reindex["running"]:
            raise DispatcherError(409, "guarded reindex is not running", status)
        if not reindex.get("supports_pause"):
            raise DispatcherError(
                409,
                "active guarded reindex was started before dispatcher pause support",
                status,
            )
        _write_json(
            self.stop_file,
            {
                "requested_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "reason": reason,
                "policy": "safe_boundary",
            },
        )
        result = self.status_payload(include_services=False)
        result["status"] = "pause_requested"
        return result

    def resume_reindex(self, **kwargs: Any) -> dict[str, Any]:
        return self.start_reindex(resume=True, **kwargs)

    def route_change_status_payload(self) -> dict[str, Any]:
        pid_info = _read_json(self.route_change_pid_file)
        pid = int(pid_info.get("pid") or 0)
        running = self.pid_running_fn(pid)
        state_path = Path(pid_info.get("state_file") or self.route_change_state_file)
        if not state_path.is_absolute():
            state_path = self.root / state_path
        state = _read_json(state_path)
        completed = state.get("completed") if isinstance(state.get("completed"), dict) else {}
        log_path_raw = str(pid_info.get("log_path") or "")
        log_path = Path(log_path_raw) if log_path_raw else None
        if log_path is not None and not log_path.is_absolute():
            log_path = self.root / log_path
        events = _tail_json_events(log_path) if log_path is not None else []
        last_event = events[-1] if events else {}
        plan = self._last_named_event(events, "plan")
        total = int(plan.get("total") or 0) + int(plan.get("completed_in_state") or 0) if plan else len(completed or {})
        done = self._last_named_event(events, "done")
        complete = bool((done or (total and len(completed or {}) >= total)) and not running)
        return {
            **compute_eta(pid_info.get("started_at"), completed_count, total, running=running),
            "running": running,
            "pid": pid if running else None,
            "stale_pid": bool(pid and not running),
            "pid_file": str(self.route_change_pid_file),
            "state_file": str(state_path),
            "state_exists": state_path.exists() and "error" not in state,
            "stop_file": str(self.route_change_stop_file),
            "pause_requested": bool(self.route_change_stop_file.exists() and running),
            "supports_pause": True,
            "completed": len(completed or {}),
            "total": total,
            "remaining": max(0, total - len(completed or {})) if total else 0,
            "last_log": str(log_path) if log_path is not None else "",
            "last_started_at": pid_info.get("started_at"),
            "last_event": last_event,
            "complete": complete,
        }

    def start_route_change_reindex(
        self,
        *,
        source_root: str = "RAG_Content",
        dry_run: bool = True,
        max_docs: int = 0,
        min_free_gb: float = 4.0,
        max_swap_pct: float = DEFAULT_REINDEX_MAX_SWAP_PCT,
        post_min_free_gb: float = 3.0,
        post_max_swap_pct: float = DEFAULT_REINDEX_POST_MAX_SWAP_PCT,
        memory_wait_sec: float = 86400.0,
        memory_poll_sec: float = 30.0,
        cooldown_sec: float = 90.0,
        parse_timeout: float = 3600.0,
    ) -> dict[str, Any]:
        route_status = self.route_change_status_payload()
        if route_status["running"]:
            route_status["status"] = "already_running"
            return route_status
        active_reindex = self.reindex_status_payload()
        if active_reindex.get("running") and not dry_run:
            raise DispatcherError(
                409,
                "standard guarded reindex is running; route-change apply must wait for baseline",
                {"reindex": active_reindex, "route_changes": route_status},
            )
        status = self.status_payload(min_free_gb=min_free_gb, max_swap_pct=max_swap_pct, include_services=False)
        if not dry_run and not status["memory"]["decision"]["allowed"]:
            raise DispatcherError(503, status["memory"]["decision"]["reason"], status)

        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.route_change_stop_file.unlink(missing_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        log_path = self.artifacts_dir / f"route_changes_{stamp}.out"
        cmd = [
            sys.executable,
            "tools/reindex_route_changes_guarded.py",
            "--source-root",
            source_root,
            "--state-file",
            str(self.route_change_state_file),
            "--stop-file",
            str(self.route_change_stop_file),
            "--min-free-gb",
            str(min_free_gb),
            "--max-swap-pct",
            str(max_swap_pct),
            "--post-min-free-gb",
            str(post_min_free_gb),
            "--post-max-swap-pct",
            str(post_max_swap_pct),
            "--memory-wait-sec",
            str(memory_wait_sec),
            "--memory-poll-sec",
            str(memory_poll_sec),
            "--cooldown-sec",
            str(cooldown_sec),
            "--parse-timeout",
            str(parse_timeout),
        ]
        if max_docs > 0:
            cmd.extend(["--max-docs", str(max_docs)])
        if dry_run:
            cmd.append("--dry-run")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        with log_path.open("ab") as output:
            process = self.popen_factory(
                cmd,
                cwd=self.root,
                stdout=output,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
                env=env,
            )
        _write_json(
            self.route_change_pid_file,
            {
                "pid": int(process.pid),
                "cmd": cmd,
                "log_path": str(log_path),
                "state_file": str(self.route_change_state_file),
                "stop_file": str(self.route_change_stop_file),
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "dispatcher": "route_changes_v0",
                "dry_run": dry_run,
            },
        )
        result = self.route_change_status_payload()
        result["status"] = "dry_run_started" if dry_run else "started"
        return result

    def pause_route_change_reindex(self, *, reason: str = "operator") -> dict[str, Any]:
        status = self.route_change_status_payload()
        if not status["running"]:
            raise DispatcherError(409, "route-change reindex is not running", {"route_changes": status})
        _write_json(
            self.route_change_stop_file,
            {
                "requested_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "reason": reason,
                "policy": "safe_boundary",
            },
        )
        result = self.route_change_status_payload()
        result["status"] = "pause_requested"
        return result

    def _memory_preflight(self, *, min_free_gb: float) -> Any:
        return self.memory_preflight_fn(limit=10, min_rss_mb=700.0, min_free_gb=min_free_gb)

    def _metrics_for_pressure(self, preflight: Any) -> dict[str, Any]:
        metrics = dict(self.metrics_cache or {})
        if metrics.get("ram_free_gb") in (None, 0, 0.0):
            metrics["ram_free_gb"] = getattr(preflight, "ram_free_gb", None)
        metrics.setdefault("ram_total_gb", getattr(preflight, "ram_total_gb", None))
        metrics.setdefault("swap_pct", getattr(preflight, "swap_pct", None))
        return metrics

    def _memory_decision(self, preflight: Any, *, min_free_gb: float, max_swap_pct: float) -> dict[str, Any]:
        reasons: list[str] = []
        ram_free = getattr(preflight, "ram_free_gb", None)
        swap_pct = getattr(preflight, "swap_pct", None)
        if ram_free is not None and ram_free < min_free_gb:
            reasons.append(f"ram_free_gb={ram_free:.1f} < {min_free_gb:.1f}")
        if swap_pct is not None and swap_pct > max_swap_pct:
            reasons.append(f"swap_pct={swap_pct:.1f} > {max_swap_pct:.1f}")
        return {
            "allowed": not reasons,
            "reason": "; ".join(reasons),
            "min_free_gb": min_free_gb,
            "max_swap_pct": max_swap_pct,
        }

    def _services_status(self) -> list[dict[str, Any]]:
        try:
            statuses = self.service_status_fn(["qdrant", "mlx", "proxy", "indexer", "ui"])
        except Exception as error:
            return [{"error": str(error)}]
        return [json.loads(json.dumps(item, default=_json_default)) for item in statuses]

    def _memory_recommendations(
        self,
        preflight: Any,
        pressure: dict[str, Any],
        decision: dict[str, Any],
        reindex: dict[str, Any],
    ) -> dict[str, Any]:
        top = list(getattr(preflight, "top_processes", []) or [])
        user_heavy = [
            process
            for process in top
            if not getattr(process, "les_owned", False)
            and not getattr(process, "protected", False)
            and float(getattr(process, "rss_mb", 0.0) or 0.0) >= 500.0
        ]
        les_heavy = [
            process
            for process in top
            if getattr(process, "les_owned", False)
            and float(getattr(process, "rss_mb", 0.0) or 0.0) >= 300.0
        ]
        actions: list[dict[str, Any]] = []
        notes = [
            "wait_only policy: dispatcher never kills Safari, IDEs, browsers, media apps, or other user processes automatically",
            "swap can stay allocated after memory pressure falls; prefer pressure trend and active workload over a single swap number",
        ]
        if reindex.get("running") and not decision.get("allowed"):
            actions.append(
                {
                    "kind": "wait",
                    "label": "Let guarded reindex wait at its memory boundary",
                    "reason": decision.get("reason", ""),
                }
            )
        if les_heavy:
            actions.append(
                {
                    "kind": "unload_mlx",
                    "label": "Unload LES-owned MLX models before more indexing or chat",
                    "endpoint": "/api/runtime/dispatcher/mlx/unload",
                    "reason": "MLX/model memory is the safest reclaim target because it is owned by LES",
                }
            )
        if user_heavy:
            actions.append(
                {
                    "kind": "manual_quit_candidates",
                    "label": "Consider quitting these user apps manually before heavy model/index work",
                    "reason": "They are outside LES ownership; dispatcher reports them only as recommendations",
                    "processes": [self._process_summary(process) for process in user_heavy[:5]],
                }
            )
        ui_processes = [
            process
            for process in top
            if getattr(process, "les_owned", False)
            and "sovushka" in str(getattr(process, "command", "")).lower()
            and float(getattr(process, "rss_mb", 0.0) or 0.0) >= 400.0
        ]
        if ui_processes:
            actions.append(
                {
                    "kind": "restart_ui",
                    "label": "Restart Sovushka UI or stay on Lite Admin before indexing",
                    "reason": "Classic NiceGUI pages can retain client state and grow RSS",
                    "processes": [self._process_summary(process) for process in ui_processes[:3]],
                }
            )
        if pressure.get("state") in {"RED", "CRITICAL"} and not actions:
            actions.append(
                {
                    "kind": "idle_or_restart_later",
                    "label": "Leave the machine idle; if swap does not fall after jobs finish, do a normal macOS restart",
                    "reason": pressure.get("reason", ""),
                }
            )
        return {
            "policy": "wait_only",
            "state": pressure.get("state"),
            "actions": actions,
            "notes": notes,
        }

    @staticmethod
    def _process_summary(process: Any) -> dict[str, Any]:
        command = " ".join(str(getattr(process, "command", "") or "").split())
        return {
            "pid": getattr(process, "pid", None),
            "rss_mb": getattr(process, "rss_mb", None),
            "user": getattr(process, "user", ""),
            "command": command if len(command) <= 140 else command[:139] + "…",
            "les_owned": bool(getattr(process, "les_owned", False)),
        }

    def _reindex_status(
        self,
        *,
        datasets: list[str],
        min_free_gb: float,
        max_swap_pct: float,
    ) -> dict[str, Any]:
        pid_info = _read_json(self.pid_file)
        pid = int(pid_info.get("pid") or 0)
        running = self.pid_running_fn(pid)
        state_path = Path(pid_info.get("state_file") or self.state_file(datasets))
        if not state_path.is_absolute():
            state_path = self.root / state_path
        state = _read_json(state_path)
        state_exists = state_path.exists() and "error" not in state
        state_datasets = [str(item) for item in (state.get("datasets") or datasets)]
        completed = state.get("completed") if isinstance(state.get("completed"), dict) else {}
        completed_count = len(completed or {})
        total = self._total_docs(state_datasets, state, completed_count) if state_exists else 0
        remaining = max(0, total - completed_count) if total else 0
        raw_log_path = str(pid_info.get("log_path") or "")
        log_path = Path(raw_log_path) if raw_log_path else None
        if log_path is not None and not log_path.is_absolute():
            log_path = self.root / log_path
        events = _tail_json_events(log_path) if log_path is not None else []
        last_event = events[-1] if events else {}
        last_doc = self._last_doc_event(events)
        auth_smoke = self._last_named_event(events, "auth_smoke")
        done = self._last_named_event(events, "done")
        stop_exists = self.stop_file.exists()
        cmd = [str(item) for item in (pid_info.get("cmd") or [])]
        supports_pause = "--stop-file" in cmd
        complete = bool((done or (total and completed_count >= total)) and not running)
        paused = bool(stop_exists and not running and not complete)
        auth_smoke_required = bool(complete and not auth_smoke)
        return {
            **compute_eta(pid_info.get("started_at"), completed_count, total, running=running),
            "running": running,
            "pid": pid if running else None,
            "stale_pid": bool(pid and not running),
            "pid_file": str(self.pid_file),
            "state_file": str(state_path),
            "state_exists": state_exists,
            "stop_file": str(self.stop_file),
            "pause_requested": bool(stop_exists and running),
            "paused": paused,
            "supports_pause": supports_pause,
            "completed": completed_count,
            "total": total,
            "remaining": remaining,
            "datasets": state_datasets,
            "updated_at": state.get("updated_at") if isinstance(state, dict) else None,
            "runs": len(state.get("runs") or []) if isinstance(state, dict) else 0,
            "last_log": str(log_path) if log_path is not None else "",
            "last_started_at": pid_info.get("started_at"),
            "last_event": last_event,
            "current_doc": last_doc,
            "complete": complete,
            "auth_smoke_required": auth_smoke_required,
            "auth_smoke": auth_smoke,
            "guard": {"min_free_gb": min_free_gb, "max_swap_pct": max_swap_pct},
        }

    def _total_docs(self, datasets: list[str], state: dict[str, Any], completed_count: int) -> int:
        db_path = str(state.get("db_path") or rag_meta_db_path())
        try:
            summaries = guarded.dataset_summaries(db_path, datasets)
            total = sum(int(item.get("total_files") or 0) for item in summaries)
            if total:
                return total
        except Exception:
            pass
        plan = self._last_named_event_from_pid_log("plan")
        if plan:
            return int(plan.get("target_docs") or 0) + int(plan.get("completed_in_state") or completed_count)
        return completed_count

    def _last_named_event_from_pid_log(self, name: str) -> dict[str, Any]:
        pid_info = _read_json(self.pid_file)
        raw_log_path = str(pid_info.get("log_path") or "")
        if not raw_log_path:
            return {}
        log_path = Path(raw_log_path)
        if not log_path.is_absolute():
            log_path = self.root / log_path
        return self._last_named_event(_tail_json_events(log_path), name)

    @staticmethod
    def _last_named_event(events: list[dict[str, Any]], name: str) -> dict[str, Any]:
        for item in reversed(events):
            if item.get("event") == name:
                return item
        return {}

    @staticmethod
    def _last_doc_event(events: list[dict[str, Any]]) -> dict[str, Any]:
        for item in reversed(events):
            if item.get("event") in {"doc_start", "doc_memory_pre", "doc_parse", "doc_health", "campaign_progress"}:
                return item
        return {}
