"""Fail-closed integrity contract for the normative machine base.

File presence is not evidence that norm/resource links are correct. A generated base
becomes trusted only after a separate report proves the required semantic gates for
the exact manifest/source revision. Until then it remains readable for audit and
navigation, but cannot support ``priced_final``.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any


DEFAULT_BASE_PATH = Path("data/smeta_base/les_smeta_base_v2.sqlite")
DEFAULT_MANIFEST_PATH = Path("data/smeta_base/les_smeta_base_v2_manifest.json")
DEFAULT_REPORT_PATH = Path("data/smeta_base/les_smeta_base_v2_integrity.json")
REPORT_SCHEMA = "les_smeta_base_integrity_v1"
REQUIRED_ZERO_FAILURE_CHECKS = (
    "cross_family_contamination",
    "orphan_resources",
    "duplicate_norm_keys",
    "resource_parent_mismatch",
    "empty_machine_base",
    "missing_provenance",
    "fts_coverage",
)
NAVIGATION_ZERO_FAILURE_CHECKS = tuple(
    check for check in REQUIRED_ZERO_FAILURE_CHECKS if check != "missing_provenance"
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _stamp(path: Path) -> tuple[bool, int, int]:
    try:
        stat = path.stat()
    except OSError:
        return False, 0, 0
    return True, stat.st_mtime_ns, stat.st_size


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _failure_count(raw: Any) -> int | None:
    if isinstance(raw, dict):
        raw = raw.get("failures")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=8)
def _evaluate(
    base_raw: str,
    manifest_raw: str,
    report_raw: str,
    base_stamp: tuple[bool, int, int],
    manifest_stamp: tuple[bool, int, int],
    report_stamp: tuple[bool, int, int],
) -> dict[str, Any]:
    del manifest_stamp, report_stamp  # stamps are cache keys
    base_path = Path(base_raw)
    manifest_path = Path(manifest_raw)
    report_path = Path(report_raw)
    if not base_stamp[0]:
        return {
            "schema": "smeta_base_integrity_status_v1",
            "status": "missing",
            "trusted_for_pricing": False,
            "reasons": ["structured normative base is missing"],
            "report_path": str(report_path),
        }

    manifest = _read_json(manifest_path)
    report = _read_json(report_path)
    reasons: list[str] = []
    if not report:
        reasons.append("semantic integrity report is missing")
    elif report.get("schema") != REPORT_SCHEMA:
        reasons.append("semantic integrity report schema is unsupported")
    if str(report.get("verdict") or "").lower() != "passed":
        reasons.append("semantic integrity verdict is not passed")

    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    for check in REQUIRED_ZERO_FAILURE_CHECKS:
        failures = _failure_count(checks.get(check))
        if failures is None:
            reasons.append(f"required check is absent: {check}")
        elif failures != 0:
            reasons.append(f"required check failed: {check}={failures}")

    manifest_source_sha = str((manifest.get("source") or {}).get("sha256") or "")
    report_source_sha = str(report.get("source_sha256") or "")
    if not manifest_source_sha or report_source_sha != manifest_source_sha:
        reasons.append("integrity report does not match manifest source sha256")

    expected_base_sha = str(report.get("base_sha256") or "")
    if not expected_base_sha:
        reasons.append("integrity report has no base sha256")
    else:
        try:
            if _sha256(base_path) != expected_base_sha:
                reasons.append("integrity report does not match structured base sha256")
        except OSError:
            reasons.append("structured base sha256 could not be verified")

    trusted = not reasons
    navigation_reasons: list[str] = []
    for check in NAVIGATION_ZERO_FAILURE_CHECKS:
        failures = _failure_count(checks.get(check))
        if failures is None:
            navigation_reasons.append(f"required navigation check is absent: {check}")
        elif failures != 0:
            navigation_reasons.append(f"navigation check failed: {check}={failures}")
    trusted_for_navigation = not navigation_reasons
    return {
        "schema": "smeta_base_integrity_status_v1",
        "status": "trusted" if trusted else "quarantined",
        "trusted_for_pricing": trusted,
        "trusted_for_navigation": trusted_for_navigation,
        "navigation_reasons": navigation_reasons,
        "reasons": reasons,
        "base_path": str(base_path),
        "manifest_path": str(manifest_path),
        "report_path": str(report_path),
        "report_schema": report.get("schema") or "",
        "report_verdict": report.get("verdict") or "",
        "checks": checks,
    }


def normative_base_integrity(
    *,
    base_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    from proxy.smeta_core.base_registry import active_base

    active = active_base()
    base = Path(base_path) if base_path is not None else Path(active["base_path"])
    manifest = Path(manifest_path) if manifest_path is not None else (
        Path(active["manifest_path"]) if base_path is None else base.with_name(f"{base.stem}_manifest.json")
    )
    report = Path(report_path) if report_path is not None else (
        Path(active["integrity_path"]) if base_path is None else base.with_name(f"{base.stem}_integrity.json")
    )
    return _evaluate(
        str(base),
        str(manifest),
        str(report),
        _stamp(base),
        _stamp(manifest),
        _stamp(report),
    )
