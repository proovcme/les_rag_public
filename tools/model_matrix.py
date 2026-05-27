#!/usr/bin/env python3
"""List guarded MLX model candidates for LES RAG experiments."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_MATRIX_PATH = Path("golden/model_candidates.json")


@dataclass(frozen=True)
class ModelCandidate:
    id: str
    family: str
    roles: tuple[str, ...]
    tier: str
    disk_gb: float
    status: str
    source_url: str = ""
    notes: str = ""


def _candidate_from_dict(raw: dict[str, Any]) -> ModelCandidate:
    roles = raw.get("roles") or []
    if not isinstance(roles, list):
        raise ValueError(f"roles must be a list for {raw.get('id')}")
    return ModelCandidate(
        id=str(raw["id"]),
        family=str(raw.get("family") or ""),
        roles=tuple(str(role) for role in roles),
        tier=str(raw.get("tier") or ""),
        disk_gb=float(raw.get("disk_gb") or 0.0),
        status=str(raw.get("status") or ""),
        source_url=str(raw.get("source_url") or ""),
        notes=str(raw.get("notes") or ""),
    )


def load_matrix(path: Path = DEFAULT_MATRIX_PATH) -> list[ModelCandidate]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ValueError(f"model matrix must contain candidates list: {path}")
    return [_candidate_from_dict(item) for item in raw_candidates]


def filter_candidates(
    candidates: list[ModelCandidate],
    *,
    role: str = "",
    tier: str = "",
    status: str = "",
    max_disk_gb: float | None = None,
) -> list[ModelCandidate]:
    result: list[ModelCandidate] = []
    for candidate in candidates:
        if role and role not in candidate.roles:
            continue
        if tier and candidate.tier != tier:
            continue
        if status and candidate.status != status:
            continue
        if max_disk_gb is not None and candidate.disk_gb > max_disk_gb:
            continue
        result.append(candidate)
    return result


def format_table(candidates: list[ModelCandidate]) -> str:
    if not candidates:
        return "No candidates matched."
    rows = [("role", "tier", "disk", "status", "model")]
    for candidate in candidates:
        rows.append(
            (
                ",".join(candidate.roles),
                candidate.tier,
                f"{candidate.disk_gb:.2f}GB",
                candidate.status,
                candidate.id,
            )
        )
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    lines = []
    for index, row in enumerate(rows):
        lines.append("  ".join(cell.ljust(widths[col]) for col, cell in enumerate(row)))
        if index == 0:
            lines.append("  ".join("-" * width for width in widths))
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List MLX model candidates for guarded LES RAG experiments.")
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX_PATH)
    parser.add_argument("--role", choices=("", "chat", "validator"), default="")
    parser.add_argument("--tier", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--max-disk-gb", type=float, default=None)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    candidates = filter_candidates(
        load_matrix(args.matrix),
        role=args.role,
        tier=args.tier,
        status=args.status,
        max_disk_gb=args.max_disk_gb,
    )
    if args.json:
        print(json.dumps([candidate.__dict__ for candidate in candidates], ensure_ascii=False, indent=2))
    else:
        print(format_table(candidates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
