"""Keep LES FreeToken context settings aligned with the physical loopback KV cache."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit

import httpx


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_SAFETY_BYTES = 128 * 1024 * 1024
# Factory 35B total window. The GPU can often allocate far more pages, but
# growing past this steals MoE expert cache and lengthens prefill without a
# larger LES execution envelope. Reconcile still clamps to max_feasible_kv().
DEFAULT_FREETOKEN_CONTEXT_TOKENS = 35000


def cache_alignment_target(runtime, *, active_connection=None):
    """Use the bound answer engine in ACTIVE, never an unrelated legacy engine."""
    if active_connection is not None:
        if getattr(active_connection, "extension_type", None) != "freetoken":
            return None
        return active_connection.base_url, active_connection.model_id
    if getattr(runtime, "requires_cache_alignment", False):
        return runtime.base_url, runtime.model
    return None


async def admitted_cache_call(callback, *args, semaphore, timeout_seconds, **kwargs):
    """Serialize cache mutation with generation, including caller cancellation.

    Cancelling to_thread does not stop its worker. Retain the permit until the
    physical rebuild finishes so the next generation cannot use a changing cache.
    """
    from proxy.services.runtime_admission import acquire_generation_slot

    async with acquire_generation_slot(semaphore, timeout_seconds=timeout_seconds):
        worker = asyncio.create_task(asyncio.to_thread(callback, *args, **kwargs))
        cancelled = False
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            # Observe any worker exception before propagating cancellation.
            if not worker.cancelled():
                worker.exception()
            raise asyncio.CancelledError
        return worker.result()


def _control_url(base_url: str, suffix: str) -> str:
    root = str(base_url or "").rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return f"{root}/v1/cache/{suffix}"


def max_feasible_kv(geometry: dict[str, Any], *, min_moe: int | None = None) -> int:
    """Largest KV pages that still leave at least ``min_moe`` expert-cache slots."""
    units = geometry.get("unit_bytes") or {}
    limits = geometry.get("limits") or {}
    moe_limits = limits.get("moe_experts") or {}
    kv_limits = limits.get("kv_tokens") or {}
    budget = int(geometry.get("cache_budget_bytes") or 0)
    kv_per = int(units.get("kv_per_token") or 0)
    moe_per = int(units.get("moe_per_expert") or 0)
    mamba_bytes = int(geometry.get("num_mamba_slots") or 0) * int(
        units.get("mamba_per_slot") or 0
    )
    swa_bytes = int(geometry.get("num_swa_pages") or 0) * int(
        units.get("swa_per_token") or 0
    )
    if budget <= 0 or kv_per <= 0 or moe_per <= 0:
        raise ValueError("FreeToken cache geometry has no usable memory budget")
    engine_min = int(moe_limits.get("min") or 0)
    floor = max(engine_min, int(min_moe) if min_moe is not None else engine_min)
    available = budget - mamba_bytes - swa_bytes - _SAFETY_BYTES - floor * moe_per
    pages = max(0, available // kv_per)
    kv_max = int(kv_limits.get("max") or 0)
    if kv_max > 0:
        pages = min(pages, kv_max)
    kv_min = int(kv_limits.get("min") or 1)
    if pages < kv_min:
        raise ValueError("configured KV leaves insufficient memory for minimum MoE cache")
    return pages


def bounded_desired_kv(geometry: dict[str, Any], requested: int) -> int:
    """Clamp a requested window so rebuild cannot starve the minimum MoE cache."""
    return min(max(1, int(requested)), max_feasible_kv(geometry))


def _cache_report(
    geometry: dict[str, Any],
    *,
    status: str,
    requested_kv: int,
    desired_kv: int,
    effective_kv: int | None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    try:
        ceiling = max_feasible_kv(geometry)
    except ValueError:
        ceiling = None
    payload: dict[str, object] = {
        "status": status,
        "requested_kv_tokens": int(requested_kv),
        "desired_kv_tokens": int(desired_kv),
        "effective_kv_tokens": effective_kv,
        "max_feasible_kv_tokens": ceiling,
        "moe_cache_size": int(geometry.get("moe_cache_size") or 0),
        "mamba_slots": int(geometry.get("num_mamba_slots") or 0),
    }
    if extra:
        payload.update(extra)
    return payload


def _feasible_moe(geometry: dict[str, Any], desired_kv: int) -> int:
    units = geometry.get("unit_bytes") or {}
    limits = (geometry.get("limits") or {}).get("moe_experts") or {}
    budget = int(geometry.get("cache_budget_bytes") or 0)
    kv_bytes = desired_kv * int(units.get("kv_per_token") or 0)
    mamba_slots = int(geometry.get("num_mamba_slots") or 0)
    mamba_bytes = mamba_slots * int(units.get("mamba_per_slot") or 0)
    swa_pages = int(geometry.get("num_swa_pages") or 0)
    swa_bytes = swa_pages * int(units.get("swa_per_token") or 0)
    unit = int(units.get("moe_per_expert") or 0)
    if budget <= 0 or unit <= 0:
        raise ValueError("FreeToken cache geometry has no usable memory budget")
    feasible = max(0, (budget - kv_bytes - mamba_bytes - swa_bytes - _SAFETY_BYTES) // unit)
    minimum = int(limits.get("min") or 0)
    maximum = int(limits.get("max") or feasible)
    feasible = min(maximum, feasible)
    if feasible < minimum:
        raise ValueError("configured KV leaves insufficient memory for minimum MoE cache")
    return max(minimum, (feasible // 25) * 25)


def _loopback_host(base_url: str) -> bool:
    host = (urlsplit(str(base_url or "")).hostname or "").casefold()
    return host in _LOOPBACK_HOSTS


def probe_freetoken_cache(
    base_url: str,
    desired_kv: int | None = None,
    *,
    client: httpx.Client | None = None,
) -> dict[str, object]:
    """Read loopback cache geometry without rebuilding."""
    requested = max(1, int(desired_kv or DEFAULT_FREETOKEN_CONTEXT_TOKENS))
    if not _loopback_host(base_url):
        return {
            "status": "unsupported_remote",
            "requested_kv_tokens": requested,
            "desired_kv_tokens": requested,
            "effective_kv_tokens": None,
            "max_feasible_kv_tokens": None,
            "reason": "physical cache control is loopback-only",
        }
    owned = client is None
    http = client or httpx.Client(timeout=3.0, trust_env=False)
    try:
        response = http.get(_control_url(base_url, "status"))
        response.raise_for_status()
        payload = response.json()
        geometry = payload.get("geometry") or {}
        effective = int(geometry.get("num_pages") or 0)
        desired = bounded_desired_kv(geometry, requested)
        status = "aligned" if effective == desired else "mismatch"
        return _cache_report(
            geometry,
            status=status,
            requested_kv=requested,
            desired_kv=desired,
            effective_kv=effective or None,
        )
    except (httpx.HTTPError, ValueError, RuntimeError, TypeError) as exc:
        return {
            "status": "degraded",
            "requested_kv_tokens": requested,
            "desired_kv_tokens": requested,
            "effective_kv_tokens": None,
            "max_feasible_kv_tokens": None,
            "reason": f"{type(exc).__name__}: {str(exc)[:180]}",
        }
    finally:
        if owned:
            http.close()


def reconcile_freetoken_cache(
    base_url: str,
    desired_kv: int,
    *,
    client: httpx.Client | None = None,
) -> dict[str, object]:
    """Probe and, when needed, rebuild a loopback FreeToken cache."""
    requested = max(1, int(desired_kv))
    if not _loopback_host(base_url):
        return {
            "status": "unsupported_remote",
            "requested_kv_tokens": requested,
            "desired_kv_tokens": requested,
            "effective_kv_tokens": None,
            "max_feasible_kv_tokens": None,
            "reason": "physical cache control is loopback-only",
        }
    owned = client is None
    http = client or httpx.Client(timeout=3.0, trust_env=False)
    try:
        response = http.get(_control_url(base_url, "status"))
        response.raise_for_status()
        payload = response.json()
        geometry = payload.get("geometry") or {}
        effective = int(geometry.get("num_pages") or 0)
        desired = bounded_desired_kv(geometry, requested)
        if effective == desired:
            return _cache_report(
                geometry,
                status="aligned",
                requested_kv=requested,
                desired_kv=desired,
                effective_kv=effective,
            )
        moe = _feasible_moe(geometry, desired)
        rebuild_payload = {
            "moe_cache_size": moe,
            "num_pages": desired,
            "num_mamba_slots": int(geometry.get("num_mamba_slots") or 24),
            "timeout": 120,
        }
        swa_limits = (geometry.get("limits") or {}).get("swa_tokens") or {}
        if int(swa_limits.get("max") or 0) > 0:
            rebuild_payload["num_swa_pages"] = int(geometry.get("num_swa_pages") or 0)
        rebuild = http.post(
            _control_url(base_url, "rebuild"),
            json=rebuild_payload,
            timeout=125.0,
        )
        rebuild.raise_for_status()
        result = rebuild.json()
        if str(result.get("status") or "").casefold() != "ok":
            raise RuntimeError(str(result.get("error") or "FreeToken cache rebuild failed"))
        report = _cache_report(
            geometry,
            status="synchronized",
            requested_kv=requested,
            desired_kv=desired,
            effective_kv=int(result.get("num_pages") or desired),
            extra={
                "moe_cache_size": int(result.get("moe_cache_size") or moe),
                "mamba_slots": int(
                    result.get("mamba_slots") or geometry.get("num_mamba_slots") or 0
                ),
            },
        )
        return report
    except (httpx.HTTPError, ValueError, RuntimeError, TypeError) as exec_error:
        return {
            "status": "degraded",
            "requested_kv_tokens": requested,
            "desired_kv_tokens": requested,
            "effective_kv_tokens": None,
            "max_feasible_kv_tokens": None,
            "reason": f"{type(exec_error).__name__}: {str(exec_error)[:180]}",
        }
    finally:
        if owned:
            http.close()


def desired_kv_for_answer_model(model_id: str, requested: int | None) -> int:
    """Raise a legacy 8k FreeToken window to the factory 35B envelope."""

    from proxy.services.model_execution_preset_service import (
        MIN_EXTENDED_35B_CONTEXT_TOKENS,
        is_qwen_35b,
    )

    asked = max(1, int(requested or DEFAULT_FREETOKEN_CONTEXT_TOKENS))
    if is_qwen_35b(model_id) and asked < MIN_EXTENDED_35B_CONTEXT_TOKENS:
        return DEFAULT_FREETOKEN_CONTEXT_TOKENS
    return asked


def align_freetoken_cache_for_turn(
    base_url: str,
    *,
    model_id: str,
    requested_kv: int,
    allow_rebuild: bool = True,
    client: httpx.Client | None = None,
) -> dict[str, object]:
    """Observe live KV; rebuild once before the first generate if 35B is cramped.

    Packet loops must not call this. Bound ACTIVE chat previously kept an 8k
    cache and then ran the 9B-restrictive envelope for hours.
    """

    from proxy.services.model_execution_preset_service import (
        MIN_EXTENDED_35B_CONTEXT_TOKENS,
        is_qwen_35b,
    )

    desired = desired_kv_for_answer_model(model_id, requested_kv)
    probed = probe_freetoken_cache(base_url, desired, client=client)
    try:
        live = int(probed.get("effective_kv_tokens") or 0)
    except (TypeError, ValueError):
        live = 0
    if not is_qwen_35b(model_id):
        return probed
    if live == desired and probed.get("status") in {"aligned", "synchronized"}:
        return probed
    if not allow_rebuild:
        if live < MIN_EXTENDED_35B_CONTEXT_TOKENS:
            return {
                **probed,
                "status": "too_small_for_35b",
                "desired_kv_tokens": desired,
                "previous_effective_kv_tokens": live or None,
            }
        return probed
    rebuilt = reconcile_freetoken_cache(base_url, desired, client=client)
    rebuilt["previous_effective_kv_tokens"] = live or None
    rebuilt["aligned_for"] = "qwen-35b-extended"
    try:
        after = int(rebuilt.get("effective_kv_tokens") or 0)
    except (TypeError, ValueError):
        after = 0
    if after < MIN_EXTENDED_35B_CONTEXT_TOKENS:
        rebuilt = dict(rebuilt)
        rebuilt["status"] = "too_small_for_35b"
    return rebuilt
