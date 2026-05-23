"""Smart RAG source planning shared by tools and API routes."""

from __future__ import annotations

import re
import os
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from backend.document_router import route_document

SUPPORTED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".doc",
    ".eml",
    ".msg",
    ".md",
    ".txt",
    ".xlsx",
    ".xls",
    ".csv",
}

SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".nicegui",
    ".claude",
    "CLAUDE",
    "QWEN",
}

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
MAX_SOURCE_FILE_MB = int(os.getenv("RAG_SOURCE_MAX_MB", "100"))


@dataclass(frozen=True)
class IntakeDecision:
    accepted: bool
    reason: str
    path: str
    suffix: str = ""
    size_bytes: int = 0


def _relative_parts(path: Path, root: Path) -> tuple[str, ...]:
    try:
        return path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return path.parts


def is_uuid_staging_path(path: Path, root: Path) -> bool:
    return any(UUID_RE.match(part) for part in _relative_parts(path, root)[:-1])


def verify_source_file(path: Path, root: Path) -> IntakeDecision:
    suffix = path.suffix.lower()
    if not path.is_file():
        return IntakeDecision(False, "not_file", path.as_posix(), suffix)
    relative_parts = _relative_parts(path, root)
    if any(part in SKIP_DIRS for part in relative_parts):
        return IntakeDecision(False, "excluded_dir", path.as_posix(), suffix, path.stat().st_size)
    if is_uuid_staging_path(path, root):
        return IntakeDecision(False, "uuid_staging_dir", path.as_posix(), suffix, path.stat().st_size)
    if suffix not in SUPPORTED_SUFFIXES:
        return IntakeDecision(False, "unsupported_suffix", path.as_posix(), suffix, path.stat().st_size)
    size = path.stat().st_size
    if size <= 0:
        return IntakeDecision(False, "empty_file", path.as_posix(), suffix, size)
    if size > MAX_SOURCE_FILE_MB * 1024 * 1024:
        return IntakeDecision(False, "file_too_large", path.as_posix(), suffix, size)
    return IntakeDecision(True, "accepted", path.as_posix(), suffix, size)


def should_index_source_file(path: Path, root: Path) -> bool:
    return verify_source_file(path, root).accepted


def iter_source_files(root: Path):
    for path in sorted(root.rglob("*")):
        if should_index_source_file(path, root):
            yield path


def build_smart_plan(root: Path) -> dict[str, Any]:
    datasets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    errors = []
    rejected: list[dict[str, Any]] = []
    rejected_reasons: Counter[str] = Counter()
    accepted_files = []
    for path in sorted(root.rglob("*")):
        decision = verify_source_file(path, root)
        if decision.accepted:
            accepted_files.append(path)
            continue
        if decision.reason != "not_file":
            rejected_reasons[decision.reason] += 1
            rejected.append(asdict(decision))

    for path in accepted_files:
        try:
            route = route_document(path)
            datasets[route.dataset_name].append(
                {
                    "path": path.as_posix(),
                    "relative_path": path.relative_to(root).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "route": asdict(route),
                }
            )
        except Exception as error:
            errors.append({"path": path.as_posix(), "error": str(error)})

    summary = []
    for name, files in sorted(datasets.items()):
        by_domain = Counter(item["route"]["domain"] for item in files)
        by_doc_type = Counter(item["route"]["doc_type"] for item in files)
        by_pipeline = Counter(item["route"]["pipeline"] for item in files)
        summary.append(
            {
                "dataset": name,
                "files": len(files),
                "bytes": sum(item["size_bytes"] for item in files),
                "domains": dict(sorted(by_domain.items())),
                "doc_types": dict(sorted(by_doc_type.items())),
                "pipelines": dict(sorted(by_pipeline.items())),
            }
        )
    return {
        "source_root": root.as_posix(),
        "total_files": sum(len(files) for files in datasets.values()),
        "datasets": summary,
        "rejected_total": sum(rejected_reasons.values()),
        "rejected_reasons": dict(sorted(rejected_reasons.items())),
        "rejected": rejected[:200],
        "errors": errors,
        "plan": {name: files for name, files in sorted(datasets.items())},
    }
