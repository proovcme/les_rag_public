#!/usr/bin/env python3
"""Immutable release-attempt state and sanitized public acceptance receipts."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ATTEMPT_SCHEMA = "les.release-attempt.v1"
PUBLIC_SCHEMA = "les.release-receipt.v1"
PUBLIC_ARTIFACT_SCHEMA = "les.release-receipt.v2"
GATE_SCHEMA = "les.release-gate-receipt.v1"
ARTIFACT_SCHEMA = "les.release-artifact.v1"
ACCEPTANCE_SCHEMA = "les.release-acceptance.v2"
PUBLICATION_SCHEMA = "les.release-publication.v1"
PUBLICATION_STAGES = (
    "accepted",
    "draft_uploaded",
    "draft_verified",
    "published",
    "postflight_verified",
)
STAGES = (
    "planned",
    "prepared",
    "legion_installed",
    "legion_smoke_passed",
    "rollback_passed",
    "legion_reinstalled",
    "accepted",
    "draft_uploaded",
    "draft_verified",
    "published",
    "postflight_verified",
)
_SENSITIVE_KEY = re.compile(r"(?:secret|token|password|credential|api[_-]?key)", re.I)
_WINDOWS_PATH = re.compile(r"[A-Za-z]:[\\/]")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _validate_commit(value: str, label: str) -> str:
    commit = str(value or "")
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError(f"{label} must be an exact lowercase Git commit")
    return commit


def _artifact_records(paths: Sequence[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    names: set[str] = set()
    for raw in paths:
        path = Path(raw).resolve()
        if not path.is_file():
            raise ValueError(f"release artifact is missing: {path.name}")
        if path.name in names:
            raise ValueError(f"duplicate release artifact name: {path.name}")
        names.add(path.name)
        records.append(
            {
                "name": path.name,
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return sorted(records, key=lambda item: item["name"])


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _payload_sha(payload: dict[str, Any]) -> str:
    unsigned = {
        key: value for key, value in payload.items() if key != "payload_sha256"
    }
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def _write_hashed_json(path: Path, payload: dict[str, Any], *, immutable: bool) -> Path:
    payload = {**payload, "payload_sha256": _payload_sha(payload)}
    path = Path(path).resolve()
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError("immutable release receipt is unreadable") from exc
        ignored = {"created_at", "payload_sha256"}
        existing_comparable = {
            key: value for key, value in existing.items() if key not in ignored
        }
        payload_comparable = {
            key: value for key, value in payload.items() if key not in ignored
        }
        if existing_comparable != payload_comparable:
            raise RuntimeError("immutable release receipt already exists with different content")
        return path
    _atomic_json(path, payload)
    return path


def _load_hashed_json(path: Path, *, schema: str, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"{label} is unreadable: {path}") from exc
    if payload.get("schema") != schema:
        raise RuntimeError(f"{label} schema is unsupported")
    if payload.get("payload_sha256") != _payload_sha(payload):
        raise RuntimeError(f"{label} integrity check failed")
    return payload


def _validate_sha256(value: str, label: str) -> str:
    digest = str(value or "")
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return digest


def _normalized_policy(
    policy: Sequence[tuple[str, Sequence[str]]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    for raw_name, raw_argv in policy:
        name = str(raw_name or "")
        argv = [str(item) for item in raw_argv]
        if re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", name) is None or not argv:
            raise ValueError("gate policy is invalid")
        if name in names:
            raise ValueError("gate policy contains duplicate names")
        names.add(name)
        normalized.append({"gate": name, "argv": argv})
    if not normalized:
        raise ValueError("gate policy is empty")
    return normalized


def create_gate_receipt(
    *,
    root: Path,
    target_commit: str,
    target_tree: str,
    product_version: str,
    build_number: int,
    desktop_version: str,
    branch: str,
    upstream_commit: str,
    policy: Sequence[tuple[str, Sequence[str]]],
    results: Sequence[dict[str, Any]],
    clean: bool,
) -> Path:
    target = _validate_commit(target_commit, "target_commit")
    tree = _validate_commit(target_tree, "target_tree")
    upstream = _validate_commit(upstream_commit, "upstream_commit")
    normalized_policy = _normalized_policy(policy)
    normalized_results = [dict(item) for item in results]
    expected_names = [item["gate"] for item in normalized_policy]
    actual_names = [str(item.get("gate") or "") for item in normalized_results]
    if (
        clean is not True
        or actual_names != expected_names
        or any(int(item.get("exit_code", -1)) != 0 for item in normalized_results)
    ):
        raise ValueError("gate receipt requires successful gate results and clean source")
    policy_sha = hashlib.sha256(_canonical(normalized_policy)).hexdigest()
    identity = {
        "target_commit": target,
        "target_tree": tree,
        "product_version": str(product_version),
        "build_number": int(build_number),
        "desktop_version": str(desktop_version),
        "branch": str(branch),
        "upstream_commit": upstream,
        "policy_sha256": policy_sha,
    }
    gate_id = hashlib.sha256(_canonical(identity)).hexdigest()[:24]
    payload = {
        "schema": GATE_SCHEMA,
        "gate_id": gate_id,
        **identity,
        "clean": True,
        "policy": normalized_policy,
        "results": normalized_results,
        "created_at": _now(),
    }
    return _write_hashed_json(
        Path(root) / "gates" / gate_id / "gate-receipt.json",
        payload,
        immutable=True,
    )


def load_gate_receipt(path: Path) -> dict[str, Any]:
    return _load_hashed_json(path, schema=GATE_SCHEMA, label="gate receipt")


def verify_gate_receipt(
    receipt: dict[str, Any],
    *,
    target_commit: str,
    target_tree: str,
    product_version: str,
    build_number: int,
    desktop_version: str,
    branch: str,
    upstream_commit: str,
    policy: Sequence[tuple[str, Sequence[str]]],
) -> None:
    normalized_policy = _normalized_policy(policy)
    expected = {
        "target_commit": _validate_commit(target_commit, "target_commit"),
        "target_tree": _validate_commit(target_tree, "target_tree"),
        "product_version": str(product_version),
        "build_number": int(build_number),
        "desktop_version": str(desktop_version),
        "branch": str(branch),
        "upstream_commit": _validate_commit(upstream_commit, "upstream_commit"),
        "policy_sha256": hashlib.sha256(_canonical(normalized_policy)).hexdigest(),
    }
    actual = {key: receipt.get(key) for key in expected}
    if actual != expected or receipt.get("clean") is not True:
        raise RuntimeError("gate receipt binding changed")
    result_names = [str(item.get("gate") or "") for item in receipt.get("results", [])]
    if result_names != [item["gate"] for item in normalized_policy] or any(
        int(item.get("exit_code", -1)) != 0 for item in receipt.get("results", [])
    ):
        raise RuntimeError("gate receipt binding changed")


def create_artifact_receipt(
    *,
    root: Path,
    gate_receipt: Path,
    release_class: str,
    target_commit: str,
    base_commits: Sequence[str],
    product_version: str,
    build_number: int,
    desktop_version: str,
    assets: Sequence[Path],
    candidate_root: Path,
    acceptance_path: Path,
    runtime_manifest_sha256: str,
    entrypoint_registry_sha256: str,
    build_evidence: dict[str, Any],
    publishable: bool,
) -> Path:
    gate = load_gate_receipt(gate_receipt)
    target = _validate_commit(target_commit, "target_commit")
    if gate.get("target_commit") != target:
        raise RuntimeError("artifact gate binding changed")
    if release_class not in {"patch", "full"}:
        raise ValueError("release_class must be patch or full")
    records = _artifact_records(assets)
    identity = {
        "gate_id": gate["gate_id"],
        "release_class": release_class,
        "target_commit": target,
        "base_commits": sorted(
            {_validate_commit(value, "base_commit") for value in base_commits}
        ),
        "product_version": str(product_version),
        "build_number": int(build_number),
        "desktop_version": str(desktop_version),
        "runtime_manifest_sha256": _validate_sha256(
            runtime_manifest_sha256, "runtime_manifest_sha256"
        ),
        "entrypoint_registry_sha256": _validate_sha256(
            entrypoint_registry_sha256, "entrypoint_registry_sha256"
        ),
        "assets": [
            {key: item[key] for key in ("name", "bytes", "sha256")}
            for item in records
        ],
    }
    artifact_id = hashlib.sha256(_canonical(identity)).hexdigest()[:24]
    payload = {
        "schema": ARTIFACT_SCHEMA,
        "artifact_id": artifact_id,
        **identity,
        "gate_receipt_path": str(Path(gate_receipt).resolve()),
        "candidate_root": str(Path(candidate_root).resolve()),
        "acceptance_path": str(Path(acceptance_path).resolve()),
        "assets": records,
        "build_evidence": dict(build_evidence),
        "publishable": bool(publishable),
        "status": "ready",
        "created_at": _now(),
    }
    return _write_hashed_json(
        Path(root) / "artifacts" / artifact_id / "artifact-receipt.json",
        payload,
        immutable=True,
    )


def load_artifact_receipt(path: Path) -> dict[str, Any]:
    return _load_hashed_json(path, schema=ARTIFACT_SCHEMA, label="artifact receipt")


def verify_artifact_receipt(
    artifact: dict[str, Any], *, commit: str, assets: Sequence[Path]
) -> None:
    expected = sorted(
        [
            {key: item.get(key) for key in ("name", "bytes", "sha256")}
            for item in artifact.get("assets", [])
        ],
        key=lambda item: str(item["name"]),
    )
    actual = [
        {key: item[key] for key in ("name", "bytes", "sha256")}
        for item in _artifact_records(assets)
    ]
    if (
        _validate_commit(commit, "commit") != artifact.get("target_commit")
        or actual != expected
        or artifact.get("status") != "ready"
    ):
        raise RuntimeError("artifact binding changed")


def create_acceptance_attempt(
    artifact_path: Path,
    *,
    host: str,
    retry_of: str | None = None,
    reconciliation: dict[str, Any] | None = None,
) -> Path:
    artifact_path = Path(artifact_path).resolve()
    artifact = load_artifact_receipt(artifact_path)
    if re.fullmatch(r"[A-Za-z0-9._-]{1,80}", str(host)) is None:
        raise ValueError("release host label is unsafe")
    acceptance_id = uuid.uuid4().hex
    payload = {
        "schema": ACCEPTANCE_SCHEMA,
        "acceptance_id": acceptance_id,
        "artifact_id": artifact["artifact_id"],
        "artifact_path": str(artifact_path),
        "host": str(host),
        "retry_of": str(retry_of) if retry_of else None,
        "reconciliation": _sanitize(reconciliation or {}),
        "result": "running",
        "started_at": _now(),
        "completed_at": None,
        "evidence": {},
        "failure": None,
    }
    path = artifact_path.parent / "acceptance" / f"{acceptance_id}.json"
    return _write_hashed_json(path, payload, immutable=True)


def _load_acceptance_attempt(path: Path) -> dict[str, Any]:
    return _load_hashed_json(
        path, schema=ACCEPTANCE_SCHEMA, label="acceptance attempt"
    )


def load_acceptance_attempt(path: Path) -> dict[str, Any]:
    return _load_acceptance_attempt(path)


def _replace_acceptance(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    payload = {**payload, "payload_sha256": _payload_sha(payload)}
    _atomic_json(Path(path), payload)
    return payload


def complete_acceptance_attempt(
    path: Path, *, evidence: dict[str, Any]
) -> dict[str, Any]:
    payload = _load_acceptance_attempt(path)
    if payload.get("result") != "running" or evidence.get("accepted") is not True:
        raise RuntimeError("running successful acceptance attempt required")
    payload["result"] = "accepted"
    payload["completed_at"] = _now()
    payload["evidence"] = _sanitize(evidence)
    return _replace_acceptance(path, payload)


def fail_acceptance_attempt(
    path: Path,
    *,
    failed_stage: str,
    error: str,
    recovery: dict[str, Any],
) -> dict[str, Any]:
    payload = _load_acceptance_attempt(path)
    if payload.get("result") != "running":
        raise RuntimeError("running acceptance attempt required")
    payload["result"] = "failed"
    payload["completed_at"] = _now()
    payload["failure"] = _sanitize(
        {
            "failed_stage": str(failed_stage),
            "error": str(error)[-2000:],
            "recovery": recovery,
        }
    )
    return _replace_acceptance(path, payload)


def accepted_attempts(artifact_path: Path) -> list[dict[str, Any]]:
    return [
        attempt
        for attempt in acceptance_attempts(artifact_path)
        if attempt.get("result") == "accepted"
    ]


def acceptance_attempts(artifact_path: Path) -> list[dict[str, Any]]:
    artifact_path = Path(artifact_path).resolve()
    artifact = load_artifact_receipt(artifact_path)
    verify_artifact_receipt(
        artifact,
        commit=str(artifact["target_commit"]),
        assets=[Path(str(item["path"])) for item in artifact.get("assets", [])],
    )
    attempts: list[dict[str, Any]] = []
    for path in sorted((artifact_path.parent / "acceptance").glob("*.json")):
        attempt = _load_acceptance_attempt(path)
        if attempt.get("artifact_id") == artifact["artifact_id"]:
            attempts.append(attempt)
    return sorted(
        attempts,
        key=lambda item: (str(item.get("started_at") or ""), str(item["acceptance_id"])),
    )


def revoke_artifact(artifact_path: Path, *, reason: str) -> Path:
    artifact_path = Path(artifact_path).resolve()
    artifact = load_artifact_receipt(artifact_path)
    revocation_id = uuid.uuid4().hex
    payload = {
        "schema": "les.release-artifact-revocation.v1",
        "revocation_id": revocation_id,
        "artifact_id": artifact["artifact_id"],
        "reason": _sanitize(str(reason)[-2000:]),
        "created_at": _now(),
    }
    return _write_hashed_json(
        artifact_path.parent / "revocations" / f"{revocation_id}.json",
        payload,
        immutable=True,
    )


def create_publication(
    artifact_path: Path, *, acceptance_path: Path
) -> Path:
    artifact_path = Path(artifact_path).resolve()
    acceptance_path = Path(acceptance_path).resolve()
    artifact = load_artifact_receipt(artifact_path)
    acceptance = load_acceptance_attempt(acceptance_path)
    if (
        acceptance.get("result") != "accepted"
        or acceptance.get("artifact_id") != artifact.get("artifact_id")
        or artifact.get("publishable") is not True
    ):
        raise RuntimeError("successful acceptance required for publication")
    path = artifact_path.parent / "publication.json"
    payload = {
        "schema": PUBLICATION_SCHEMA,
        "artifact_id": artifact["artifact_id"],
        "acceptance_id": acceptance["acceptance_id"],
        "acceptance_path": str(acceptance_path),
        "stage": "accepted",
        "checkpoints": {},
        "transitions": [
            {"stage": "accepted", "at": _now(), "evidence": {"accepted": True}}
        ],
    }
    if path.is_file():
        existing = load_publication(path)
        if (
            existing.get("artifact_id") != payload["artifact_id"]
            or existing.get("acceptance_id") != payload["acceptance_id"]
        ):
            raise RuntimeError("artifact publication is already bound differently")
        return path
    _atomic_json(path, payload)
    return path


def load_publication(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"publication state is unreadable: {path}") from exc
    if payload.get("schema") != PUBLICATION_SCHEMA:
        raise RuntimeError("publication state schema is unsupported")
    return payload


def transition_publication(
    path: Path,
    *,
    expected: str,
    target: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    payload = load_publication(path)
    current = str(payload.get("stage") or "")
    if not (
        current == expected
        and expected in PUBLICATION_STAGES
        and target in PUBLICATION_STAGES
        and PUBLICATION_STAGES.index(target) == PUBLICATION_STAGES.index(expected) + 1
    ):
        raise RuntimeError(
            f"invalid publication transition: current={current}, expected={expected}, target={target}"
        )
    payload["stage"] = target
    payload["transitions"].append(
        {"stage": target, "at": _now(), "evidence": _sanitize(evidence)}
    )
    _atomic_json(Path(path), payload)
    return payload


def record_publication_checkpoint(
    path: Path, *, expected: str, name: str, evidence: dict[str, Any]
) -> dict[str, Any]:
    payload = load_publication(path)
    if payload.get("stage") != expected:
        raise RuntimeError("publication checkpoint stage changed")
    if re.fullmatch(r"[a-z][a-z0-9_]{1,63}", str(name or "")) is None:
        raise ValueError("publication checkpoint name is invalid")
    payload.setdefault("checkpoints", {}).setdefault(str(name), _sanitize(evidence))
    _atomic_json(Path(path), payload)
    return payload


def create_attempt(
    *,
    root: Path,
    release_class: str,
    product_version: str,
    build_number: int,
    target_commit: str,
    base_commits: Sequence[str],
    host: str,
    assets: Sequence[Path],
) -> Path:
    if release_class not in {"patch", "full"}:
        raise ValueError("release_class must be patch or full")
    if re.fullmatch(r"\d+\.\d+\.\d+", str(product_version)) is None:
        raise ValueError("product_version must be SemVer X.Y.Z")
    if int(build_number) <= 0:
        raise ValueError("build_number must be positive")
    if re.fullmatch(r"[A-Za-z0-9._-]{1,80}", str(host)) is None:
        raise ValueError("release host label is unsafe")
    target = _validate_commit(target_commit, "target_commit")
    bases = sorted({_validate_commit(value, "base_commit") for value in base_commits})
    artifacts = _artifact_records(assets)
    identity = {
        "release_class": release_class,
        "product_version": str(product_version),
        "build_number": int(build_number),
        "target_commit": target,
        "base_commits": bases,
        "artifacts": [
            {key: item[key] for key in ("name", "bytes", "sha256")}
            for item in artifacts
        ],
    }
    release_id = hashlib.sha256(_canonical(identity)).hexdigest()[:24]
    path = Path(root).resolve() / release_id / "release-state.json"
    payload = {
        "schema": ATTEMPT_SCHEMA,
        "release_id": release_id,
        **identity,
        "host": str(host),
        "stage": "planned",
        "publishable": True,
        "artifacts": artifacts,
        "checkpoints": {},
        "transitions": [
            {"stage": "planned", "at": _now(), "evidence": {"created": True}}
        ],
        "failure": None,
    }
    if path.is_file():
        existing = load_attempt(path)
        comparable = dict(existing)
        comparable["transitions"] = payload["transitions"]
        if comparable != payload:
            raise RuntimeError("release attempt ID collides with different state")
        return path
    _atomic_json(path, payload)
    return path


def load_attempt(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"release attempt is unreadable: {path}") from exc
    if payload.get("schema") != ATTEMPT_SCHEMA:
        raise RuntimeError("release attempt schema is unsupported")
    return payload


def transition(
    path: Path,
    *,
    expected: str,
    target: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    payload = load_attempt(path)
    current = str(payload.get("stage") or "")
    valid = (
        current == expected
        and expected in STAGES
        and target in STAGES
        and STAGES.index(target) == STAGES.index(expected) + 1
    )
    if not valid:
        raise RuntimeError(
            f"invalid release transition: current={current}, expected={expected}, target={target}"
        )
    json.dumps(evidence, ensure_ascii=False)
    payload["stage"] = target
    payload["transitions"].append(
        {"stage": target, "at": _now(), "evidence": evidence}
    )
    _atomic_json(Path(path), payload)
    return payload


def record_checkpoint(
    path: Path,
    *,
    expected: str,
    name: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Persist idempotent evidence without advancing the release stage."""
    payload = load_attempt(path)
    current = str(payload.get("stage") or "")
    if current != expected or expected not in STAGES:
        raise RuntimeError(
            f"invalid release checkpoint: current={current}, expected={expected}"
        )
    checkpoint = str(name or "")
    if re.fullmatch(r"[a-z][a-z0-9_]{1,63}", checkpoint) is None:
        raise ValueError("release checkpoint name is invalid")
    json.dumps(evidence, ensure_ascii=False)
    checkpoints = payload.setdefault("checkpoints", {})
    existing = checkpoints.get(checkpoint)
    if existing is not None:
        return payload
    checkpoints[checkpoint] = evidence
    _atomic_json(Path(path), payload)
    return payload


def fail_attempt(
    path: Path,
    *,
    stage: str,
    error: str,
    recovery: dict[str, Any],
) -> dict[str, Any]:
    payload = load_attempt(path)
    if payload.get("stage") in {"published", "postflight_verified", "failed"}:
        raise RuntimeError(f"release attempt cannot fail from {payload.get('stage')}")
    failure = {
        "failed_stage": str(stage),
        "at": _now(),
        "error": str(error)[-2000:],
        "recovery": recovery,
    }
    json.dumps(failure, ensure_ascii=False)
    payload["stage"] = "failed"
    payload["publishable"] = False
    payload["failure"] = failure
    payload["transitions"].append(
        {"stage": "failed", "at": failure["at"], "evidence": failure}
    )
    _atomic_json(Path(path), payload)
    return payload


def mark_non_publishable(path: Path, *, reason: str) -> dict[str, Any]:
    """Permanently mark a development attempt as ineligible for publication."""
    payload = load_attempt(path)
    if payload.get("stage") in {"draft_uploaded", "draft_verified", "published", "postflight_verified"}:
        raise RuntimeError("published release attempt cannot be made non-publishable")
    payload["publishable"] = False
    payload["non_publishable_reason"] = str(reason)
    _atomic_json(Path(path), payload)
    return payload


def verify_binding(
    attempt: dict[str, Any], *, commit: str, assets: Sequence[Path]
) -> None:
    expected_commit = str(attempt.get("target_commit") or "")
    actual_commit = _validate_commit(commit, "commit")
    actual = _artifact_records(assets)
    expected = sorted(
        [
            {key: item.get(key) for key in ("name", "bytes", "sha256")}
            for item in attempt.get("artifacts", [])
        ],
        key=lambda item: str(item["name"]),
    )
    comparable = [
        {key: item[key] for key in ("name", "bytes", "sha256")}
        for item in actual
    ]
    if actual_commit != expected_commit or comparable != expected:
        raise RuntimeError("artifact binding changed since release acceptance")


def _sanitize(value: Any, *, key: str = "") -> Any:
    if _SENSITIVE_KEY.search(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize(item_value, key=str(item_key))
            for item_key, item_value in sorted(value.items())
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and (
        _WINDOWS_PATH.search(value) is not None or value.startswith("/")
    ):
        return "[redacted-path]"
    return value


def write_public_receipt(attempt_path: Path, destination: Path) -> Path:
    attempt = load_attempt(attempt_path)
    if attempt.get("stage") != "accepted" or attempt.get("publishable") is not True:
        raise RuntimeError("accepted release attempt required for public receipt")
    receipt = {
        "schema": PUBLIC_SCHEMA,
        "accepted": True,
        "release_id": attempt["release_id"],
        "release_class": attempt["release_class"],
        "product_version": attempt["product_version"],
        "build_number": attempt["build_number"],
        "target_commit": attempt["target_commit"],
        "base_commits": attempt["base_commits"],
        "host": attempt["host"],
        "artifacts": [
            {key: item[key] for key in ("name", "bytes", "sha256")}
            for item in attempt["artifacts"]
        ],
        "checkpoints": _sanitize(attempt.get("checkpoints", {})),
        "transitions": _sanitize(attempt["transitions"]),
    }
    destination = Path(destination).resolve()
    _atomic_json(destination, receipt)
    return destination


def write_public_artifact_receipt(
    artifact_path: Path, acceptance_path: Path, destination: Path
) -> Path:
    artifact_path = Path(artifact_path).resolve()
    acceptance_path = Path(acceptance_path).resolve()
    artifact = load_artifact_receipt(artifact_path)
    acceptance = load_acceptance_attempt(acceptance_path)
    if (
        acceptance.get("result") != "accepted"
        or acceptance.get("artifact_id") != artifact.get("artifact_id")
        or artifact.get("publishable") is not True
        or list((artifact_path.parent / "revocations").glob("*.json"))
    ):
        raise RuntimeError("successful acceptance required for public receipt")
    verify_artifact_receipt(
        artifact,
        commit=str(artifact["target_commit"]),
        assets=[Path(str(item["path"])) for item in artifact.get("assets", [])],
    )
    receipt = {
        "schema": PUBLIC_ARTIFACT_SCHEMA,
        "accepted": True,
        "artifact_id": artifact["artifact_id"],
        "acceptance_id": acceptance["acceptance_id"],
        "release_class": artifact["release_class"],
        "product_version": artifact["product_version"],
        "build_number": artifact["build_number"],
        "desktop_version": artifact["desktop_version"],
        "target_commit": artifact["target_commit"],
        "base_commits": artifact["base_commits"],
        "host": acceptance["host"],
        "assets": [
            {key: item[key] for key in ("name", "bytes", "sha256")}
            for item in artifact["assets"]
        ],
        "evidence": _sanitize(acceptance.get("evidence", {})),
    }
    destination = Path(destination).resolve()
    _atomic_json(destination, receipt)
    return destination
