"""Admission control for expensive runtime actions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from proxy.services.resource_governor import chat_generation_allowed


ACTIVE_JOB_STATUSES = {"QUEUED", "PARSING", "RUNNING"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def chat_min_free_gb() -> float:
    return _env_float("LES_CHAT_MIN_FREE_GB", 8.0)


def chat_max_swap_pct() -> float:
    return _env_float("LES_CHAT_MAX_SWAP_PCT", 60.0)


def chat_max_swap_used_gb() -> float:
    return _env_float("LES_CHAT_MAX_SWAP_USED_GB", 2.0)


def chat_swap_relief_free_gb() -> float:
    return _env_float("LES_CHAT_SWAP_RELIEF_FREE_GB", 10.0)


def chat_block_active_jobs() -> bool:
    return _env_bool("LES_CHAT_BLOCK_ACTIVE_JOBS", True)


def chat_memory_guard_enabled() -> bool:
    return _env_bool("LES_CHAT_MEMORY_GUARD", True)


@dataclass(frozen=True)
class ChatAdmission:
    allowed: bool
    reason: str
    failures: tuple[str, ...]
    memory: dict[str, Any]
    active_jobs: int
    mode_allowed: bool
    mode_reason: str
    status_code: int

    def payload(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "failures": list(self.failures),
            "memory": self.memory,
            "active_jobs": self.active_jobs,
            "mode_allowed": self.mode_allowed,
            "mode_reason": self.mode_reason,
            "status_code": self.status_code,
        }


def memory_snapshot(metrics_cache: dict[str, Any] | None) -> dict[str, Any]:
    metrics = metrics_cache or {}
    ram_total = _coerce_float(metrics.get("ram_total_gb", metrics.get("ram_total")))
    ram_used = _coerce_float(metrics.get("ram_used_gb", metrics.get("ram_used")))
    ram_free = _coerce_float(metrics.get("ram_free_gb"))
    swap_used = _coerce_float(metrics.get("swap_used_gb", metrics.get("swap_used")))
    swap_pct = _coerce_float(metrics.get("swap_pct"))

    if ram_free is None and ram_total is not None and ram_used is not None:
        ram_free = max(0.0, ram_total - ram_used)
    if ram_used is None and ram_total is not None and ram_free is not None:
        ram_used = max(0.0, ram_total - ram_free)

    return {
        "known": ram_free is not None or swap_pct is not None,
        "ram_total_gb": ram_total,
        "ram_used_gb": ram_used,
        "ram_free_gb": ram_free,
        "swap_used_gb": swap_used,
        "swap_pct": swap_pct,
    }


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def count_active_jobs(job_service: Any = None, job_tracker: dict[str, Any] | None = None) -> int:
    active_ids: set[str] = set()
    if job_service is not None:
        try:
            if hasattr(job_service, "list_active_ids"):
                active_ids.update(str(job_id) for job_id in job_service.list_active_ids(limit=500))
            else:
                jobs = job_service.list(limit=500)
                active_ids.update(
                    str(job_id)
                    for job_id, job in jobs.items()
                    if _job_is_active(job)
                )
        except Exception:
            pass

    for job_id, job in (job_tracker or {}).items():
        if _job_is_active(job):
            active_ids.add(str(job_id))
    return len(active_ids)


def _job_is_active(job: Any) -> bool:
    if not isinstance(job, dict):
        return False
    status = str(job.get("status", "")).upper()
    return status in ACTIVE_JOB_STATUSES


def evaluate_chat_admission(
    *,
    current_mode: dict[str, Any] | None,
    metrics_cache: dict[str, Any] | None,
    active_jobs: int = 0,
    llm_available: bool | None = None,
    min_free_gb: float | None = None,
    max_swap_pct: float | None = None,
    max_swap_used_gb: float | None = None,
    swap_relief_free_gb: float | None = None,
    block_active_jobs: bool | None = None,
    memory_guard: bool | None = None,
) -> ChatAdmission:
    min_free = chat_min_free_gb() if min_free_gb is None else min_free_gb
    max_swap = chat_max_swap_pct() if max_swap_pct is None else max_swap_pct
    max_swap_used = chat_max_swap_used_gb() if max_swap_used_gb is None else max_swap_used_gb
    swap_relief_free = chat_swap_relief_free_gb() if swap_relief_free_gb is None else swap_relief_free_gb
    block_jobs = chat_block_active_jobs() if block_active_jobs is None else block_active_jobs
    guard_memory = chat_memory_guard_enabled() if memory_guard is None else memory_guard

    mode_allowed, mode_reason = chat_generation_allowed(current_mode)
    memory = memory_snapshot(metrics_cache)
    failures: list[str] = []
    status_code = 200

    if not mode_allowed:
        failures.append(mode_reason)
        status_code = 409

    if guard_memory and memory["known"]:
        ram_free = memory.get("ram_free_gb")
        swap_used = memory.get("swap_used_gb")
        swap_pct = memory.get("swap_pct")
        if ram_free is not None and ram_free < min_free:
            failures.append(f"ram_free_gb={ram_free:.1f} < {min_free:.1f}")
            status_code = max(status_code, 503)
        if swap_pct is not None and swap_pct > max_swap:
            # macOS can keep swap allocated after pressure is gone. Treat that
            # as safe only when there is plenty of RAM and absolute swap is low.
            stale_swap_allocation = (
                ram_free is not None
                and swap_used is not None
                and ram_free >= swap_relief_free
                and swap_used <= max_swap_used
            )
            if not stale_swap_allocation:
                detail = f"swap_pct={swap_pct:.1f} > {max_swap:.1f}"
                if swap_used is not None:
                    detail += f" (swap_used_gb={swap_used:.1f})"
                failures.append(detail)
                status_code = max(status_code, 503)

    if block_jobs and active_jobs > 0:
        failures.append(f"active_jobs={active_jobs}")
        status_code = max(status_code, 409)

    if llm_available is False:
        failures.append("llm_generation_slots=0")
        status_code = max(status_code, 429)

    reason = "; ".join(failures) if failures else "chat generation allowed"
    return ChatAdmission(
        allowed=not failures,
        reason=reason,
        failures=tuple(failures),
        memory=memory,
        active_jobs=active_jobs,
        mode_allowed=mode_allowed,
        mode_reason=mode_reason,
        status_code=status_code,
    )
