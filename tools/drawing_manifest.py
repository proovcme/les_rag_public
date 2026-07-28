#!/usr/bin/env python3
"""CLI levers for drawing sheet manifests."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from proxy.services.drawing_manifest_service import build_drawing_manifest_registry


def _print_or_write(payload: dict[str, Any], output: str) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        print(path.as_posix())
    else:
        print(text)


def _dataset_pdf_paths(api_base: str, dataset_id: str, *, q: str = "", limit: int = 1000) -> list[str]:
    base = api_base.rstrip("/")
    params = {"limit": str(limit)}
    if q:
        params["q"] = q
    url = f"{base}/api/documents/datasets/{urllib.parse.quote(dataset_id)}/documents?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.load(response)
    paths: list[str] = []
    for row in payload.get("documents") or []:
        source_path = str(row.get("source_path") or "")
        if source_path.lower().endswith(".pdf") and Path(source_path).exists():
            paths.append(source_path)
    return paths


def _path_pdf_paths(paths: list[str], *, recursive: bool) -> list[str]:
    out: list[str] = []
    for raw in paths:
        path = Path(raw)
        if path.is_file() and path.suffix.lower() == ".pdf":
            out.append(path.as_posix())
        elif path.is_dir():
            iterator = path.rglob("*.pdf") if recursive else path.glob("*.pdf")
            out.extend(p.as_posix() for p in sorted(iterator))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Build read-only drawing manifest registries.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--max-pages-per-pdf", type=int, default=2)
    common.add_argument("--limit", type=int, default=0, help="Limit files after discovery; 0 means no extra limit")
    common.add_argument("--include-pages", action="store_true", help="Include per-page manifest payloads")
    common.add_argument("--output", default="", help="Write JSON to this path instead of stdout")

    p_dataset = sub.add_parser("scan-dataset", parents=[common], help="Scan PDFs known to Documents API")
    p_dataset.add_argument("dataset_id")
    p_dataset.add_argument("--api-base", default="http://127.0.0.1:8050")
    p_dataset.add_argument("--q", default="", help="Documents API filename filter")
    p_dataset.add_argument("--api-limit", type=int, default=1000)

    p_path = sub.add_parser("scan-path", parents=[common], help="Scan explicit files or folders")
    p_path.add_argument("paths", nargs="+")
    p_path.add_argument("--dataset-id", default="")
    p_path.add_argument("--recursive", action="store_true")

    args = parser.parse_args()
    limit = args.limit if args.limit and args.limit > 0 else None
    if args.cmd == "scan-dataset":
        paths = _dataset_pdf_paths(args.api_base, args.dataset_id, q=args.q, limit=args.api_limit)
        registry = build_drawing_manifest_registry(
            paths,
            dataset_id=args.dataset_id,
            max_pages_per_pdf=args.max_pages_per_pdf,
            limit=limit,
            include_pages=args.include_pages,
        )
    elif args.cmd == "scan-path":
        paths = _path_pdf_paths(args.paths, recursive=args.recursive)
        registry = build_drawing_manifest_registry(
            paths,
            dataset_id=args.dataset_id,
            max_pages_per_pdf=args.max_pages_per_pdf,
            limit=limit,
            include_pages=args.include_pages,
        )
    else:
        raise AssertionError(args.cmd)
    _print_or_write(registry, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
