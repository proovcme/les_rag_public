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
_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")


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
        _WINDOWS_PATH.match(value) is not None or value.startswith("/")
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
        "transitions": _sanitize(attempt["transitions"]),
    }
    destination = Path(destination).resolve()
    _atomic_json(destination, receipt)
    return destination
