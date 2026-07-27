#!/usr/bin/env python3
"""CLI lever for electrical evidence summaries over manifest JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from proxy.services.electrical_evidence_summary_service import build_electrical_evidence_summary_from_files


def _print_or_write(payload: dict[str, Any], output: str) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        print(path.as_posix())
    else:
        print(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a read-only electrical evidence summary from manifest JSON files.")
    parser.add_argument("manifests", nargs="+", help="Electrical schematic/material manifest JSON files")
    parser.add_argument("--output", default="", help="Write JSON to this path instead of stdout")
    args = parser.parse_args()
    summary = build_electrical_evidence_summary_from_files(args.manifests)
    _print_or_write(summary, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
