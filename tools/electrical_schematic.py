#!/usr/bin/env python3
"""CLI lever for electrical single-line/load-table manifests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from proxy.services.electrical_schematic_service import extract_electrical_schematic_manifest


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
    parser = argparse.ArgumentParser(description="Build a read-only electrical schematic manifest from a PDF.")
    parser.add_argument("pdf")
    parser.add_argument("--max-pages", type=int, default=0, help="Limit pages; 0 reads the full PDF")
    parser.add_argument("--output", default="", help="Write JSON to this path instead of stdout")
    args = parser.parse_args()
    manifest = extract_electrical_schematic_manifest(
        args.pdf,
        max_pages=args.max_pages if args.max_pages > 0 else None,
    )
    _print_or_write(manifest, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
