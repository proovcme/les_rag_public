#!/usr/bin/env python3
"""Inspect and repair a bloated Windows LES .env without exposing values."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


KEY = re.compile(rb"^[A-Za-z_][A-Za-z0-9_]*$")
SAMPLE_BYTES = 1024 * 1024
MAX_KEYS = 512
MAX_LINE_BYTES = 64 * 1024


def _sample(path: Path, *, tail: bool) -> bytes:
    with path.open("rb") as stream:
        if tail and path.stat().st_size > SAMPLE_BYTES:
            stream.seek(-SAMPLE_BYTES, os.SEEK_END)
        return stream.read(SAMPLE_BYTES)


def _entries(payload: bytes) -> dict[bytes, bytes]:
    result: dict[bytes, bytes] = {}
    for raw in payload.splitlines():
        line = raw.strip()
        if (
            not line
            or line.startswith(b"#")
            or b"=" not in line
            or len(line) > MAX_LINE_BYTES
        ):
            continue
        key, value = line.split(b"=", 1)
        key = key.strip()
        if KEY.fullmatch(key):
            result[key] = value.strip()
            if len(result) > MAX_KEYS:
                raise RuntimeError("environment sample contains too many keys")
    return result


def inspect(path: Path) -> dict[str, Any]:
    size = path.stat().st_size
    first = _sample(path, tail=False)
    last = _sample(path, tail=True)
    first_entries = _entries(first)
    last_entries = _entries(last)
    prefix_key = ""
    if b"=" in first:
        candidate = first.split(b"=", 1)[0].strip()
        if KEY.fullmatch(candidate):
            prefix_key = candidate.decode("ascii")
    return {
        "schema": "les.windows-env-inspection.v1",
        "path": str(path),
        "bytes": size,
        "oversized": size > SAMPLE_BYTES,
        "first_sample_sha256": hashlib.sha256(first).hexdigest(),
        "last_sample_sha256": hashlib.sha256(last).hexdigest(),
        "samples_equal": first == last,
        "first_newlines": first.count(b"\n"),
        "last_newlines": last.count(b"\n"),
        "first_valid_keys": len(first_entries),
        "last_valid_keys": len(last_entries),
        "recoverable_key_count": len({*first_entries, *last_entries}),
        "oversized_first_key": prefix_key,
    }


def repair(path: Path, *, seed: Path | None = None, recovery_root: Path | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"environment file is missing: {path}")
    original_size = path.stat().st_size
    entries: dict[bytes, bytes] = {}
    if seed is not None:
        if not seed.is_file() or seed.stat().st_size > SAMPLE_BYTES:
            raise RuntimeError("environment seed is missing or oversized")
        entries.update(_entries(seed.read_bytes()))
    entries.update(_entries(_sample(path, tail=False)))
    entries.update(_entries(_sample(path, tail=True)))
    if not entries:
        raise RuntimeError("no valid environment entries could be recovered")

    recovery_base = recovery_root or path.parent / "recovery"
    recovery_base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    recovery = recovery_base / f"env-corrupt-{stamp}.bin"
    os.replace(path, recovery)
    temporary = path.with_suffix(".repair.tmp")
    try:
        with temporary.open("wb") as stream:
            for key in sorted(entries):
                stream.write(key + b"=" + entries[key] + b"\n")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        if not path.exists():
            os.replace(recovery, path)
        raise
    return {
        "schema": "les.windows-env-repair.v1",
        "path": str(path),
        "original_bytes": original_size,
        "repaired_bytes": path.stat().st_size,
        "recovered_keys": len(entries),
        "recovery_path": str(recovery),
        "values_exposed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "repair"))
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--seed", type=Path)
    parser.add_argument("--recovery-root", type=Path)
    args = parser.parse_args(argv)
    payload = (
        inspect(args.path)
        if args.command == "inspect"
        else repair(
            args.path,
            seed=args.seed,
            recovery_root=args.recovery_root,
        )
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
