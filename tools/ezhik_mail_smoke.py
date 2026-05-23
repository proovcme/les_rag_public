#!/usr/bin/env python3
"""Smoke-test EML/MSG intake before enabling Е.Ж.И.К. IMAP ingest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.converter import convert_to_markdown
from backend.document_router import route_document
from backend.smart_index import verify_source_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="EML/MSG file or folder with mail files")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--root", default="")
    return parser.parse_args()


def iter_mail_files(path: Path, limit: int):
    if path.is_file():
        yield path
        return
    count = 0
    for item in sorted(path.rglob("*")):
        if item.suffix.lower() not in {".eml", ".msg"}:
            continue
        yield item
        count += 1
        if count >= limit:
            break


def main() -> int:
    args = parse_args()
    target = Path(args.path)
    if not target.exists():
        raise SystemExit(f"path not found: {target}")
    root = Path(args.root) if args.root else (target if target.is_dir() else target.parent)

    results = []
    errors = 0
    for path in iter_mail_files(target, args.limit):
        decision = verify_source_file(path, root)
        route = route_document(path) if decision.accepted else None
        markdown = convert_to_markdown(path) if decision.accepted else None
        ok = bool(markdown and route and route.dataset_name == "MAIL_Index")
        errors += 0 if ok else 1
        results.append(
            {
                "path": path.as_posix(),
                "accepted": decision.accepted,
                "reason": decision.reason,
                "dataset": route.dataset_name if route else None,
                "doc_type": route.doc_type if route else None,
                "chars": len(markdown or ""),
                "ok": ok,
            }
        )

    print(
        json.dumps(
            {
                "status": "ok" if errors == 0 else "failed",
                "checked": len(results),
                "errors": errors,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
