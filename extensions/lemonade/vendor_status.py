"""Factual Lemonade health mapping and the preserved embedding identity."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from extensions.lemonade.contracts import (
    LemonadeBackend,
    LemonadeHealth,
    LemonadeModelDescriptor,
    LemonadeModelRole,
)


EMBEDDING_FAMILY = "Qwen/Qwen3-Embedding-0.6B"
EMBEDDING_MODEL_ID = "Qwen3-Embedding-0.6B-GGUF"
EMBEDDING_BACKEND: LemonadeBackend = "llama_cpp"
EMBEDDING_VECTOR_SIZE = 1024
EMBEDDING_CHUNK_TOKENS = 430
EMBEDDING_CHUNK_OVERLAP = 50


def embedding_identity() -> dict[str, str | int]:
    """Return a fresh wire attestation for the existing named collection."""
    return {
        "family": EMBEDDING_FAMILY,
        "model": EMBEDDING_MODEL_ID,
        "backend": EMBEDDING_BACKEND,
        "vector_size": EMBEDDING_VECTOR_SIZE,
        "chunk_tokens": EMBEDDING_CHUNK_TOKENS,
        "chunk_overlap": EMBEDDING_CHUNK_OVERLAP,
    }


def _normalized_model_id(value: Any) -> str:
    return str(value or "").strip().casefold().removesuffix(":latest")


def _normalized_backend(record: Mapping[str, Any]) -> LemonadeBackend | None:
    recipe = str(record.get("recipe") or "").strip().casefold()
    if recipe in {"llamacpp", "llama_cpp"}:
        return "llama_cpp"
    if recipe == "flm":
        return "flm"
    return None


def _record_proves_loaded(record: Mapping[str, Any]) -> bool:
    """Treat an official all_models_loaded record as proof unless it contradicts itself."""
    if record.get("loaded") is False or record.get("backend_alive") is False:
        return False
    status = str(record.get("status") or "").strip().casefold()
    if status and status not in {"ready", "in_use", "busy", "loaded", "running"}:
        return False
    backend_health = str(record.get("backend_health") or "").strip().casefold()
    if backend_health and backend_health not in {"ready", "busy", "ok", "healthy"}:
        return False
    return True


def _role_descriptor(
    records: tuple[Mapping[str, Any], ...],
    *,
    role: LemonadeModelRole,
    vendor_type: str,
    model_id: str,
) -> LemonadeModelDescriptor:
    expected = _normalized_model_id(model_id)
    record = next(
        (
            item
            for item in records
            if str(item.get("type") or "").strip().casefold() == vendor_type
            and _normalized_model_id(item.get("model_name")) == expected
        ),
        None,
    )
    return LemonadeModelDescriptor(
        model_id=model_id,
        backend=_normalized_backend(record) if record is not None else None,
        role=role,
        loaded=record is not None and _record_proves_loaded(record),
    )


def lemonade_health_from_vendor(
    payload: Mapping[str, Any] | None,
    *,
    chat_model: str,
    validation_model: str,
    rerank_model: str,
) -> LemonadeHealth:
    """Map one successful vendor health response without inventing role readiness."""
    raw_records = payload.get("all_models_loaded") if isinstance(payload, Mapping) else None
    available = (
        isinstance(payload, Mapping)
        and str(payload.get("status") or "").strip().casefold() == "ok"
        and isinstance(raw_records, list)
    )
    records = (
        tuple(item for item in raw_records if isinstance(item, Mapping))
        if available and isinstance(raw_records, list)
        else ()
    )
    specs: tuple[tuple[LemonadeModelRole, str, str], ...] = (
        ("chat", "llm", chat_model),
        ("validation", "llm", validation_model),
        ("embedding", "embedding", EMBEDDING_MODEL_ID),
        ("rerank", "reranking", rerank_model),
    )
    return LemonadeHealth(
        available=available,
        models=tuple(
            _role_descriptor(records, role=role, vendor_type=vendor_type, model_id=model_id)
            for role, vendor_type, model_id in specs
        ),
        detail="ready" if available else "vendor_health_unavailable",
    )


def vendor_has_loaded_models(payload: Mapping[str, Any] | None) -> bool:
    """Use official all_models_loaded records for the idle-unload decision."""
    records = payload.get("all_models_loaded") if isinstance(payload, Mapping) else None
    return isinstance(records, list) and any(
        isinstance(record, Mapping) and _record_proves_loaded(record)
        for record in records
    )


class VendorIdleGuard:
    """Measure observed vendor inactivity, including clients bypassing the adapter.

    Vendor last_use has its own clock; only compare its changes, never compare
    its numeric value with the adapter's monotonic clock. Missing facts fail closed.
    """

    def __init__(self) -> None:
        self._fingerprint: tuple | None = None
        self._since = 0.0

    def may_unload(self, payload: Mapping[str, Any], *, now: float, idle_seconds: float) -> bool:
        records = payload.get("all_models_loaded")
        if idle_seconds <= 0 or not isinstance(records, list) or not records or any(
            not isinstance(item, Mapping) or item.get("last_use") is None
            or item.get("is_busy") is not False or item.get("is_streaming") is not False
            or item.get("loaded") is not True
            for item in records
        ):
            self._fingerprint = None
            self._since = now
            return False
        fingerprint = tuple(sorted(
            (str(item.get("model_name")), str(item.get("pid")), str(item["last_use"]))
            for item in records
        ))
        if fingerprint != self._fingerprint:
            self._fingerprint = fingerprint
            self._since = now
        return now - self._since >= idle_seconds
