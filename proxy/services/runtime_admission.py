"""Admission control for expensive runtime actions."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from proxy.services.resource_governor import chat_generation_allowed, current_runtime_profile


ACTIVE_JOB_STATUSES = {"QUEUED", "PARSING", "RUNNING"}

MEMORY_UNKNOWN = "UNKNOWN"
MEMORY_GREEN = "GREEN"
MEMORY_YELLOW = "YELLOW"
MEMORY_RED = "RED"
MEMORY_CRITICAL = "CRITICAL"
MEMORY_STATE_RANK = {
    MEMORY_UNKNOWN: -1,
    MEMORY_GREEN: 0,
    MEMORY_YELLOW: 1,
    MEMORY_RED: 2,
    MEMORY_CRITICAL: 3,
}


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


# Память этой машины едят только ЛОКАЛЬНЫЕ провайдеры — для них guard обязателен
# (кейс Gemma 12B: ollama выел RAM до swap 86%). Облачные (openrouter/openai)
# RAM не требуют — admission по памяти снимается (решение оператора 2026-06-13).
LOCAL_LLM_PROVIDERS = {"mlx", "local-mlx", "local_mlx", "ollama", "lemonade"}

# Облако не конкурирует за Metal — параллелизм отдельным семафором (медленная
# облачная генерация не должна блокировать чат «slots=0», кейс 2026-06-14).
_CLOUD_LLM_CONCURRENCY = int(os.getenv("LES_CLOUD_LLM_CONCURRENCY", "4") or "4")
cloud_llm_semaphore = asyncio.Semaphore(max(1, _CLOUD_LLM_CONCURRENCY))


def active_llm_provider() -> str:
    return os.getenv("LES_LLM_PROVIDER", "mlx").strip().lower() or "mlx"


def llm_provider_is_cloud() -> bool:
    return active_llm_provider() not in LOCAL_LLM_PROVIDERS


def generation_semaphore(local_semaphore):
    """Семафор генерации для активного провайдера: локальный Metal-слот или облачный пул."""
    return cloud_llm_semaphore if llm_provider_is_cloud() else local_semaphore


def chat_memory_guard_for_provider() -> bool:
    provider = os.getenv("LES_LLM_PROVIDER", "mlx").strip().lower() or "mlx"
    if provider in LOCAL_LLM_PROVIDERS:
        return chat_memory_guard_enabled()
    return _env_bool("LES_CHAT_MEMORY_GUARD", False)


def memory_green_min_free_gb() -> float:
    return _env_float("LES_MEMORY_GREEN_MIN_FREE_GB", 12.0)


def memory_red_min_free_gb() -> float:
    return _env_float("LES_MEMORY_RED_MIN_FREE_GB", 8.0)


def memory_critical_min_free_gb() -> float:
    return _env_float("LES_MEMORY_CRITICAL_MIN_FREE_GB", 6.0)


def memory_green_max_swap_pct() -> float:
    return _env_float("LES_MEMORY_GREEN_MAX_SWAP_PCT", 40.0)


def memory_red_max_swap_pct() -> float:
    return _env_float("LES_MEMORY_RED_MAX_SWAP_PCT", 60.0)


def memory_critical_max_swap_pct() -> float:
    return _env_float("LES_MEMORY_CRITICAL_MAX_SWAP_PCT", 75.0)


@dataclass(frozen=True)
class MemoryPressure:
    state: str
    reason: str
    memory: dict[str, Any]
    stale_swap_allocation: bool = False

    def payload(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "reason": self.reason,
            "memory": self.memory,
            "stale_swap_allocation": self.stale_swap_allocation,
        }


@dataclass(frozen=True)
class ChatAdmission:
    allowed: bool
    reason: str
    failures: tuple[str, ...]
    memory: dict[str, Any]
    memory_state: str
    memory_reason: str
    runtime_profile: str
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
            "memory_state": self.memory_state,
            "memory_reason": self.memory_reason,
            "runtime_profile": self.runtime_profile,
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


def _worse_state(left: str, right: str) -> str:
    return left if MEMORY_STATE_RANK[left] >= MEMORY_STATE_RANK[right] else right


def _state_from_free_memory(ram_free: float) -> tuple[str, str]:
    critical_min = memory_critical_min_free_gb()
    red_min = memory_red_min_free_gb()
    green_min = memory_green_min_free_gb()
    if ram_free < critical_min:
        return MEMORY_CRITICAL, f"ram_free_gb={ram_free:.1f} < {critical_min:.1f}"
    if ram_free < red_min:
        return MEMORY_RED, f"ram_free_gb={ram_free:.1f} < {red_min:.1f}"
    if ram_free < green_min:
        return MEMORY_YELLOW, f"ram_free_gb={ram_free:.1f} < {green_min:.1f}"
    return MEMORY_GREEN, f"ram_free_gb={ram_free:.1f} >= {green_min:.1f}"


def _state_from_swap_pct(swap_pct: float) -> tuple[str, str]:
    critical_max = memory_critical_max_swap_pct()
    red_max = memory_red_max_swap_pct()
    green_max = memory_green_max_swap_pct()
    if swap_pct > critical_max:
        return MEMORY_CRITICAL, f"swap_pct={swap_pct:.1f} > {critical_max:.1f}"
    if swap_pct > red_max:
        return MEMORY_RED, f"swap_pct={swap_pct:.1f} > {red_max:.1f}"
    if swap_pct > green_max:
        return MEMORY_YELLOW, f"swap_pct={swap_pct:.1f} > {green_max:.1f}"
    return MEMORY_GREEN, f"swap_pct={swap_pct:.1f} <= {green_max:.1f}"


def evaluate_memory_pressure(
    metrics_cache: dict[str, Any] | None,
    *,
    max_stale_swap_used_gb: float | None = None,
    stale_swap_relief_free_gb: float | None = None,
) -> MemoryPressure:
    memory = memory_snapshot(metrics_cache)
    if not memory["known"]:
        return MemoryPressure(MEMORY_UNKNOWN, "memory telemetry unavailable", memory)

    ram_free = memory.get("ram_free_gb")
    swap_used = memory.get("swap_used_gb")
    swap_pct = memory.get("swap_pct")
    max_swap_used = chat_max_swap_used_gb() if max_stale_swap_used_gb is None else max_stale_swap_used_gb
    swap_relief_free = (
        chat_swap_relief_free_gb() if stale_swap_relief_free_gb is None else stale_swap_relief_free_gb
    )
    stale_swap_allocation = (
        ram_free is not None
        and swap_used is not None
        and swap_pct is not None
        and swap_pct > memory_red_max_swap_pct()
        and ram_free >= swap_relief_free
        and swap_used <= max_swap_used
    )

    state = MEMORY_GREEN
    reasons: list[str] = []
    if ram_free is not None:
        ram_state, ram_reason = _state_from_free_memory(ram_free)
        state = _worse_state(state, ram_state)
        reasons.append(ram_reason)
    if swap_pct is not None and not stale_swap_allocation:
        swap_state, swap_reason = _state_from_swap_pct(swap_pct)
        state = _worse_state(state, swap_state)
        reasons.append(swap_reason)
    elif stale_swap_allocation:
        reasons.append(
            f"swap_pct={swap_pct:.1f} treated as stale allocation "
            f"(swap_used_gb={swap_used:.1f}, ram_free_gb={ram_free:.1f})"
        )

    reason = "; ".join(reasons) if reasons else f"memory state {state}"
    return MemoryPressure(state, reason, memory, stale_swap_allocation)


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
    guard_memory = chat_memory_guard_for_provider() if memory_guard is None else memory_guard

    mode_allowed, mode_reason = chat_generation_allowed(current_mode)
    memory = memory_snapshot(metrics_cache)
    memory_pressure = evaluate_memory_pressure(
        metrics_cache,
        max_stale_swap_used_gb=max_swap_used,
        stale_swap_relief_free_gb=swap_relief_free,
    )
    runtime_profile = current_runtime_profile(current_mode)
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
        memory_state=memory_pressure.state,
        memory_reason=memory_pressure.reason,
        runtime_profile=runtime_profile,
        active_jobs=active_jobs,
        mode_allowed=mode_allowed,
        mode_reason=mode_reason,
        status_code=status_code,
    )
