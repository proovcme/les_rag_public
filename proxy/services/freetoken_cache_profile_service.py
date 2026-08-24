"""Keep LES FreeToken context settings aligned with the physical loopback KV cache."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_SAFETY_BYTES = 128 * 1024 * 1024


def _control_url(base_url: str, suffix: str) -> str:
    root = str(base_url or "").rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return f"{root}/v1/cache/{suffix}"


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


def reconcile_freetoken_cache(
    base_url: str,
    desired_kv: int,
    *,
    client: httpx.Client | None = None,
) -> dict[str, object]:
    """Probe and, when needed, rebuild a loopback FreeToken cache."""
    desired = max(1, int(desired_kv))
    host = (urlsplit(str(base_url or "")).hostname or "").casefold()
    if host not in _LOOPBACK_HOSTS:
        return {
            "status": "unsupported_remote",
            "desired_kv_tokens": desired,
            "effective_kv_tokens": None,
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
        if effective == desired:
            return {
                "status": "aligned",
                "desired_kv_tokens": desired,
                "effective_kv_tokens": effective,
                "moe_cache_size": int(geometry.get("moe_cache_size") or 0),
                "mamba_slots": int(geometry.get("num_mamba_slots") or 0),
            }
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
        return {
            "status": "synchronized",
            "desired_kv_tokens": desired,
            "effective_kv_tokens": int(result.get("num_pages") or desired),
            "moe_cache_size": int(result.get("moe_cache_size") or moe),
            "mamba_slots": int(result.get("mamba_slots") or geometry.get("num_mamba_slots") or 0),
        }
    except (httpx.HTTPError, ValueError, RuntimeError, TypeError) as exc:
        return {
            "status": "degraded",
            "desired_kv_tokens": desired,
            "effective_kv_tokens": None,
            "reason": f"{type(exc).__name__}: {str(exc)[:180]}",
        }
    finally:
        if owned:
            http.close()
