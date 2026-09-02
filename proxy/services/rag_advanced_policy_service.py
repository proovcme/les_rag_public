"""GUI-first runtime policy for RAPTOR and ColBERT.

Environment variables may relocate the policy file, but cannot silently change
retrieval behaviour.  Every effective factor is persisted, returned by API and
therefore visible to the operator in Sovushka.
"""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from backend.runtime_paths import mutable_path
from typing import Any


POLICY_SCHEMA = "les.rag.advanced-policy.v1"
STATUS_SCHEMA = "les.rag.advanced-status.v1"
MODES = {"off", "adaptive", "always"}

DEFAULT_POLICY: dict[str, Any] = {
    "schema": POLICY_SCHEMA,
    "revision": 1,
    "execution": {
        "exact_early_exit": True,
        "total_latency_budget_ms": 2200,
    },
    "raptor": {
        "mode": "off",
        "fanout": 8,
        "route_k": 8,
        "max_depth": 3,
        "latency_budget_ms": 900,
        "summary_backend": "ollama",
        "summary_model": "qwen3.5:9b",
        "summary_api_url": "http://127.0.0.1:11434",
        "summary_input_chars": 12000,
        "summary_max_chars": 1800,
        "circuit_breaker_failures": 3,
        "circuit_breaker_cooldown_sec": 180,
    },
    "colbert": {
        "mode": "adaptive",
        "model": "BAAI/bge-m3",
        "candidate_k": 64,
        "output_k": 32,
        "max_query_tokens": 48,
        "max_passage_tokens": 128,
        "allow_cpu_full_build": False,
        "latency_budget_ms": 700,
        "circuit_breaker_failures": 3,
        "circuit_breaker_cooldown_sec": 300,
    },
    "reranker": {
        "candidate_k": 32,
        "latency_budget_ms": 1400,
    },
}

DEFAULT_STATUS: dict[str, Any] = {
    "schema": STATUS_SCHEMA,
    "raptor": {
        "readiness": "not_built",
        "progress": 0.0,
        "last_error_code": "",
        "last_bypass_reason": "",
    },
    "colbert": {
        "readiness": "not_built",
        "progress": 0.0,
        "last_error_code": "",
        "last_bypass_reason": "",
        "circuit_state": "closed",
    },
    "last_route": {
        "stages": [],
        "latency_ms": {},
        "fallbacks": [],
    },
}


class AdvancedPolicyError(ValueError):
    pass


def colbert_generation_readiness(
    policy: dict[str, Any],
    status: dict[str, Any],
    index_contract: dict[str, Any],
) -> dict[str, Any]:
    """Prove that ColBERT belongs to the complete active generation.

    Activation writes the audited readiness hash and exact generation count
    into the alias contract.  Retrieval reads that proof; it never probes or
    mutates Qdrant while answering a user query.
    """

    mode = str((policy.get("colbert") or {}).get("mode") or "off")
    if mode == "off":
        return {"ready": False, "reason": "disabled", "mode": mode}
    if str(status.get("readiness") or "") != "ready":
        return {"ready": False, "reason": "not_ready", "mode": mode}
    if str(status.get("circuit_state") or "closed") != "closed":
        return {"ready": False, "reason": "circuit_open", "mode": mode}

    actual = index_contract.get("actual") if isinstance(index_contract.get("actual"), dict) else {}
    target = str(status.get("target_collection") or "")
    complete = bool(
        index_contract.get("compatible")
        and target
        and str(actual.get("physical_generation") or "") == target
        and str(actual.get("colbert_schema") or "") == "les.rag.colbert.bge-m3.v1"
        and str(actual.get("colbert_vector_name") or "")
        and int(actual.get("generation_points") or 0) > 0
        and str(actual.get("readiness_report_sha256") or "")
    )
    if not complete:
        return {
            "ready": False,
            "reason": "multivector_contract_incomplete",
            "mode": mode,
        }
    return {"ready": True, "reason": "ready", "mode": mode}


def policy_path() -> Path:
    configured = os.getenv("LES_RAG_ADVANCED_POLICY_PATH", "").strip()
    return Path(configured) if configured else mutable_path("storage/config/rag_advanced_policy.json")


def status_path() -> Path:
    configured = os.getenv("LES_RAG_ADVANCED_STATUS_PATH", "").strip()
    return Path(configured) if configured else mutable_path("storage/config/rag_advanced_status.json")


def _read(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return deepcopy(default)
    except (OSError, json.JSONDecodeError) as exc:
        raise AdvancedPolicyError(f"RAG_ADVANCED_CONFIG_INVALID: {type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AdvancedPolicyError("RAG_ADVANCED_CONFIG_INVALID: root must be an object")
    return payload


def _positive_int(value: Any, field: str, *, minimum: int = 1, maximum: int = 100_000) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AdvancedPolicyError(f"RAG_ADVANCED_POLICY_INVALID: {field} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise AdvancedPolicyError(
            f"RAG_ADVANCED_POLICY_INVALID: {field} must be between {minimum} and {maximum}"
        )
    return parsed


def validate_policy(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(DEFAULT_POLICY)
    if payload.get("schema", POLICY_SCHEMA) != POLICY_SCHEMA:
        raise AdvancedPolicyError("RAG_ADVANCED_POLICY_SCHEMA_UNSUPPORTED")
    for section in ("execution", "raptor", "colbert", "reranker"):
        value = payload.get(section, {})
        if not isinstance(value, dict):
            raise AdvancedPolicyError(f"RAG_ADVANCED_POLICY_INVALID: {section} must be an object")
        result[section].update(value)
    for section in ("raptor", "colbert"):
        mode = str(result[section].get("mode") or "").lower()
        if mode not in MODES:
            raise AdvancedPolicyError(
                f"RAG_ADVANCED_POLICY_INVALID: {section}.mode must be off/adaptive/always"
            )
        result[section]["mode"] = mode
    result["execution"]["exact_early_exit"] = bool(
        result["execution"].get("exact_early_exit", True)
    )
    result["colbert"]["allow_cpu_full_build"] = bool(
        result["colbert"].get("allow_cpu_full_build", False)
    )
    integer_fields = {
        "execution": ("total_latency_budget_ms",),
        "raptor": (
            "fanout", "route_k", "max_depth", "latency_budget_ms",
            "summary_input_chars", "summary_max_chars",
            "circuit_breaker_failures", "circuit_breaker_cooldown_sec",
        ),
        "colbert": (
            "candidate_k", "output_k", "max_query_tokens", "max_passage_tokens",
            "latency_budget_ms", "circuit_breaker_failures", "circuit_breaker_cooldown_sec",
        ),
        "reranker": ("candidate_k", "latency_budget_ms"),
    }
    for section, fields in integer_fields.items():
        for field in fields:
            result[section][field] = _positive_int(result[section].get(field), f"{section}.{field}")
    if result["colbert"]["output_k"] > result["colbert"]["candidate_k"]:
        raise AdvancedPolicyError("RAG_ADVANCED_POLICY_INVALID: colbert.output_k exceeds candidate_k")
    result["colbert"]["model"] = str(result["colbert"].get("model") or "").strip()
    if result["colbert"]["model"] != "BAAI/bge-m3":
        raise AdvancedPolicyError("RAG_ADVANCED_POLICY_INVALID: only BAAI/bge-m3 is supported")
    raptor_backend = str(result["raptor"].get("summary_backend") or "").strip().lower()
    if raptor_backend not in {"ollama", "extractive"}:
        raise AdvancedPolicyError(
            "RAG_ADVANCED_POLICY_INVALID: raptor.summary_backend must be ollama/extractive"
        )
    result["raptor"]["summary_backend"] = raptor_backend
    result["raptor"]["summary_model"] = str(
        result["raptor"].get("summary_model") or ""
    ).strip()
    result["raptor"]["summary_api_url"] = str(
        result["raptor"].get("summary_api_url") or ""
    ).strip().rstrip("/")
    if raptor_backend == "ollama":
        if not result["raptor"]["summary_model"]:
            raise AdvancedPolicyError("RAG_ADVANCED_POLICY_INVALID: raptor.summary_model is required")
        if result["raptor"]["summary_api_url"] not in {
            "http://127.0.0.1:11434", "http://localhost:11434"
        }:
            raise AdvancedPolicyError(
                "RAG_ADVANCED_POLICY_INVALID: raptor.summary_api_url must be local Ollama"
            )
    result["schema"] = POLICY_SCHEMA
    result["revision"] = _positive_int(payload.get("revision", result["revision"]), "revision")
    return result


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_policy() -> dict[str, Any]:
    return validate_policy(_read(policy_path(), DEFAULT_POLICY))


def save_policy(payload: dict[str, Any]) -> dict[str, Any]:
    current = load_policy()
    candidate = validate_policy(payload)
    candidate["revision"] = int(current.get("revision") or 0) + 1
    _atomic_write(policy_path(), candidate)
    return candidate


def load_status() -> dict[str, Any]:
    payload = _read(status_path(), DEFAULT_STATUS)
    if payload.get("schema", STATUS_SCHEMA) != STATUS_SCHEMA:
        raise AdvancedPolicyError("RAG_ADVANCED_STATUS_SCHEMA_UNSUPPORTED")
    result = deepcopy(DEFAULT_STATUS)
    for section in ("raptor", "colbert", "last_route"):
        if isinstance(payload.get(section), dict):
            result[section].update(payload[section])
    return result


def save_status(payload: dict[str, Any]) -> dict[str, Any]:
    current = load_status()
    for section in ("raptor", "colbert", "last_route"):
        if isinstance(payload.get(section), dict):
            current[section].update(payload[section])
    current["schema"] = STATUS_SCHEMA
    _atomic_write(status_path(), current)
    return current


def operator_snapshot() -> dict[str, Any]:
    return {
        "schema": "les.rag.advanced-operator-snapshot.v1",
        "policy": load_policy(),
        "status": load_status(),
        "policy_source": str(policy_path()),
        "hidden_runtime_overrides": [],
    }
