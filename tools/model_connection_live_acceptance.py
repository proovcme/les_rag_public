"""Opt-in redacted live acceptance for exact model-connection revisions."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from proxy.config import ENV_PATH
from proxy.services.model_connection_contracts import CapabilityName
from proxy.services.model_connection_registry_service import ModelConnectionRegistry
from proxy.services.model_connection_resolver_service import ModelConnectionResolver
from proxy.services.model_secret_service import EnvironmentSecretStore
from proxy.services.openai_compatible_transport_service import (
    InferenceRequest,
    OpenAICompatibleTransport,
)
from proxy.services.version_service import version_info


REPORT_SCHEMA = "les.model_connection_live_acceptance.v1"
LIVE_TRANSPORT = "live_http"
REQUIRED_CASES = frozenset({"chat", "stream", "tools", "context"})
_FULL_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


@dataclass(frozen=True)
class AcceptanceConfig:
    revision_9b: str
    revision_35b: str | None
    out: Path
    timeout_seconds: float = 180.0


def _required_text(value: Any, label: str) -> str:
    rendered = str(value or "").strip()
    if not rendered:
        raise ValueError(f"{label.upper()}_REQUIRED")
    return rendered


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_receipt(
    *,
    source_commit: str,
    build_number: int,
    connection_revision_id: str,
    capability_snapshot_id: str,
    preset_id: str,
    observed_model_identity: str,
    cases: Sequence[Mapping[str, Any]],
    transport_kind: str,
) -> dict[str, Any]:
    """Build a bounded receipt; raw prompts and answers are never accepted."""
    if transport_kind != LIVE_TRANSPORT:
        raise ValueError("LIVE_EVIDENCE_REQUIRED")
    commit = _required_text(source_commit, "source_commit").lower()
    if not _FULL_COMMIT_RE.fullmatch(commit):
        raise ValueError("SOURCE_COMMIT_INVALID")
    if isinstance(build_number, bool) or not isinstance(build_number, int) or build_number < 1:
        raise ValueError("BUILD_NUMBER_INVALID")

    safe_cases: list[dict[str, Any]] = []
    for raw in cases:
        if set(raw) != {"name", "passed", "elapsed_ms", "evidence_sha256"}:
            raise ValueError("LIVE_CASE_FIELDS_INVALID")
        name = _required_text(raw.get("name"), "case_name")
        elapsed = raw.get("elapsed_ms")
        evidence_sha = str(raw.get("evidence_sha256") or "").lower()
        if isinstance(elapsed, bool) or not isinstance(elapsed, int) or elapsed < 0:
            raise ValueError("LIVE_CASE_ELAPSED_INVALID")
        if not _SHA256_RE.fullmatch(evidence_sha):
            raise ValueError("LIVE_CASE_HASH_INVALID")
        safe_cases.append(
            {
                "name": name,
                "passed": raw.get("passed") is True,
                "elapsed_ms": elapsed,
                "evidence_sha256": evidence_sha,
            }
        )
    names = {item["name"] for item in safe_cases}
    if not REQUIRED_CASES.issubset(names) or len(names) != len(safe_cases):
        raise ValueError("LIVE_CASES_INCOMPLETE")

    receipt: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "evidence_kind": "live_model_connection",
        "source_commit": commit,
        "build_number": build_number,
        "connection_revision_id": _required_text(
            connection_revision_id, "connection_revision_id"
        ),
        "capability_snapshot_id": _required_text(
            capability_snapshot_id, "capability_snapshot_id"
        ),
        "preset_id": _required_text(preset_id, "preset_id"),
        "observed_model_identity": _required_text(
            observed_model_identity, "observed_model_identity"
        ),
        "transport_kind": LIVE_TRANSPORT,
        "passed": all(item["passed"] for item in safe_cases),
        "cases": safe_cases,
    }
    receipt["acceptance_sha256"] = _canonical_sha256(receipt)
    return receipt


def _case_evidence(name: str, started: float, safe_payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "passed": True,
        "elapsed_ms": max(0, round((time.monotonic() - started) * 1000)),
        "evidence_sha256": _canonical_sha256({"name": name, **dict(safe_payload)}),
    }


def _observed_model(expected: str, observed: str) -> str:
    value = _required_text(observed, "observed_model_identity")
    if value != expected:
        raise ValueError("OBSERVED_MODEL_IDENTITY_MISMATCH")
    return value


async def exercise_connection(connection: Any, transport: Any) -> tuple[dict[str, Any], ...]:
    """Exercise real transport boundaries while retaining only hashed summaries."""
    model_id = _required_text(connection.model_id, "model_id")
    request = InferenceRequest(
        messages=({"role": "user", "content": "Ответь одним словом: готов."},),
        max_output_tokens=32,
        temperature=0.0,
    )

    started = time.monotonic()
    chat = await transport.complete(connection, request)
    _observed_model(model_id, chat.model_id)
    if not chat.text.strip() or not chat.finish_reason:
        raise ValueError("LIVE_CHAT_INCOMPLETE")
    chat_case = _case_evidence(
        "chat",
        started,
        {
            "model_id": chat.model_id,
            "finish_reason": chat.finish_reason,
            "has_text": True,
            "tool_call_count": len(chat.tool_calls),
            "usage": dict(chat.usage),
        },
    )

    started = time.monotonic()
    stream_text_length = 0
    stream_finish = ""
    stream_model = ""
    async for event in transport.stream(connection, request):
        stream_text_length += len(event.text)
        stream_finish = event.finish_reason or stream_finish
        stream_model = event.model_id or stream_model
    _observed_model(model_id, stream_model)
    if stream_text_length < 1 or not stream_finish:
        raise ValueError("LIVE_STREAM_INCOMPLETE")
    stream_case = _case_evidence(
        "stream",
        started,
        {
            "model_id": stream_model,
            "finish_reason": stream_finish,
            "text_length": stream_text_length,
        },
    )

    started = time.monotonic()
    tool_response = await transport.complete(
        connection,
        InferenceRequest(
            messages=(
                {
                    "role": "user",
                    "content": "Вызови функцию les_acceptance_ping с пустым объектом.",
                },
            ),
            max_output_tokens=64,
            temperature=0.0,
            tools=(
                {
                    "type": "function",
                    "function": {
                        "name": "les_acceptance_ping",
                        "description": "Проверка поддержки client-owned tools.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    },
                },
            ),
        ),
    )
    _observed_model(model_id, tool_response.model_id)
    selected = [
        item
        for item in tool_response.tool_calls
        if isinstance(item, Mapping)
        and isinstance(item.get("function"), Mapping)
        and item["function"].get("name") == "les_acceptance_ping"
    ]
    if len(selected) != 1:
        raise ValueError("LIVE_TOOL_CALL_REQUIRED")
    tools_case = _case_evidence(
        "tools",
        started,
        {
            "model_id": tool_response.model_id,
            "finish_reason": tool_response.finish_reason,
            "selected_tool": "les_acceptance_ping",
            "tool_call_count": len(tool_response.tool_calls),
        },
    )

    started = time.monotonic()
    preset = connection.effective_preset
    input_limit = int(getattr(preset, "input_token_limit", 0) or 0)
    generation_reserve = int(
        getattr(
            preset,
            "generation_reserve_tokens",
            getattr(preset, "max_output_tokens", 0),
        )
        or 0
    )
    if input_limit < 1 or generation_reserve < 1:
        raise ValueError("LIVE_CONTEXT_CONTRACT_INVALID")
    context_case = _case_evidence(
        "context",
        started,
        {
            "preset_id": _required_text(preset.preset_id, "preset_id"),
            "input_token_limit": input_limit,
            "generation_reserve_tokens": generation_reserve,
        },
    )
    return chat_case, stream_case, tools_case, context_case


def _runtime_identity() -> dict[str, Any]:
    identity = version_info()
    if identity.get("repo_dirty") is not False:
        raise ValueError("LIVE_RUNTIME_DIRTY")
    alignment = identity.get("runtime_alignment")
    if not isinstance(alignment, Mapping) or alignment.get("status") != "aligned":
        raise ValueError("LIVE_RUNTIME_NOT_ALIGNED")
    source_commit = str(identity.get("git_commit_full") or "").strip().lower()
    deployed_commit = str(identity.get("deployed_commit") or "").strip().lower()
    commit = (
        source_commit
        if _FULL_COMMIT_RE.fullmatch(source_commit)
        else deployed_commit
    )
    if not _FULL_COMMIT_RE.fullmatch(commit):
        raise ValueError("SOURCE_COMMIT_INVALID")
    build = identity.get("build_number")
    if isinstance(build, bool) or not isinstance(build, int) or build < 1:
        raise ValueError("BUILD_NUMBER_INVALID")
    return {"source_commit": commit, "build_number": build}


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


async def _run_acceptance(config: AcceptanceConfig) -> dict[str, Any]:
    identity = _runtime_identity()
    registry = ModelConnectionRegistry()
    secret_store = EnvironmentSecretStore(ENV_PATH)
    resolver = ModelConnectionResolver(
        registry=registry,
        secret_store=secret_store,
        allow_private_http=True,
    )
    targets = [(config.revision_9b, "qwen-9b-restrictive")]
    if config.revision_35b:
        targets.append((config.revision_35b, "qwen-35b-extended"))
    receipts: list[dict[str, Any]] = []
    required = frozenset(
        {
            CapabilityName.CHAT_COMPLETIONS,
            CapabilityName.STREAMING,
            CapabilityName.TOOLS,
        }
    )
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(config.timeout_seconds),
        follow_redirects=False,
    ) as client:
        transport = OpenAICompatibleTransport(
            client=client,
            secret_store=secret_store,
            timeout=config.timeout_seconds,
        )
        for revision_id, expected_preset in targets:
            connection = resolver.resolve_revision(
                revision_id,
                required_capabilities=required,
            )
            if connection.effective_preset.preset_id != expected_preset:
                raise ValueError("LIVE_PRESET_MISMATCH")
            cases = await exercise_connection(connection, transport)
            receipt = build_receipt(
                source_commit=identity["source_commit"],
                build_number=identity["build_number"],
                connection_revision_id=connection.revision_id,
                capability_snapshot_id=connection.capability_snapshot.snapshot_id,
                preset_id=connection.effective_preset.preset_id,
                observed_model_identity=connection.model_id,
                cases=cases,
                transport_kind=LIVE_TRANSPORT,
            )
            if receipt["passed"] is not True:
                raise ValueError("LIVE_ACCEPTANCE_FAILED")
            receipts.append(receipt)

    bundle: dict[str, Any] = {
        "schema": "les.model_connection_live_acceptance_bundle.v1",
        "evidence_kind": "live_model_connection",
        **identity,
        "receipts": receipts,
        "passed": bool(receipts) and all(item["passed"] for item in receipts),
    }
    bundle["acceptance_sha256"] = _canonical_sha256(bundle)
    _write_report(config.out, bundle)
    return bundle


def run_acceptance(config: AcceptanceConfig) -> dict[str, Any]:
    """Run only against the real registry, real secret store and real HTTP client."""
    return asyncio.run(_run_acceptance(config))


def parse_args(argv: list[str] | None = None) -> AcceptanceConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision-9b", required=True)
    parser.add_argument("--revision-35b")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    return AcceptanceConfig(
        revision_9b=str(args.revision_9b).strip(),
        revision_35b=(str(args.revision_35b).strip() if args.revision_35b else None),
        out=args.out,
        timeout_seconds=float(args.timeout_seconds),
    )


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    report = run_acceptance(config)
    print(
        f"live model-connection acceptance written: {config.out} "
        f"receipts={len(report['receipts'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
