#!/usr/bin/env python3
"""Build a deterministic smart-dataset plan for LES RAG sources.

The default mode is read-only. Use this before any destructive reset to see
where files would land and which ingestion pipeline each file would use.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.document_router import DocumentRoute
from backend.smart_index import build_smart_plan, iter_source_files


def infer_domain(path: Path, route: DocumentRoute) -> str:
    return route.domain


def dataset_name_for(path: Path, route: DocumentRoute) -> str:
    return route.dataset_name


def iter_files(root: Path):
    yield from iter_source_files(root)


def build_plan(root: Path):
    return build_smart_plan(root)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", default="RAG_Content")
    parser.add_argument("--out", default="")
    parser.add_argument("--details", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.source_root)
    if not root.exists():
        raise SystemExit(f"source root not found: {root}")

    plan = build_plan(root)
    output = plan if args.details else {k: v for k, v in plan.items() if k not in {"plan", "rejected"}}
    text = json.dumps(output, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
