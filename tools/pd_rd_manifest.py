#!/usr/bin/env python3
"""CLI lever for PD/RD PDF manifests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from proxy.services.pd_rd_manifest_service import extract_pd_rd_manifest


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
    parser = argparse.ArgumentParser(description="Build a read-only PD/RD manifest from a PDF volume.")
    parser.add_argument("pdf")
    parser.add_argument("--max-pages", type=int, default=0, help="Limit pages; 0 reads the full PDF")
    parser.add_argument("--include-sheet-pages", action="store_true")
    parser.add_argument("--output", default="", help="Write JSON to this path instead of stdout")
    args = parser.parse_args()
    manifest = extract_pd_rd_manifest(
        args.pdf,
        max_pages=args.max_pages if args.max_pages > 0 else None,
        include_sheet_pages=args.include_sheet_pages,
    )
    _print_or_write(manifest, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
