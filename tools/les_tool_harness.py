#!/usr/bin/env python3
"""CLI levers for the LES tool harness."""

from __future__ import annotations

import argparse
import json
from typing import Any

from proxy.services.tool_harness_service import harness


def _print(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False))


def _json_arg(value: str) -> dict[str, Any]:
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("--args-json must decode to an object")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Run controlled LES tools locally.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_registry = sub.add_parser("registry", help="List tool registry")
    p_registry.add_argument("--category", default="")

    p_shortlist = sub.add_parser("shortlist", help="Shortlist tools for a question")
    p_shortlist.add_argument("question")
    p_shortlist.add_argument("--mode", default="")
    p_shortlist.add_argument("--limit", type=int, default=5)

    p_call = sub.add_parser("call", help="Call any tool with JSON args")
    p_call.add_argument("tool")
    p_call.add_argument("--args-json", type=_json_arg, default={})

    p_map = sub.add_parser("dataset-map", help="Show dataset navigation map")
    p_map.add_argument("dataset_id")
    p_map.add_argument("--depth", default="deep")

    p_search = sub.add_parser("search", help="Search indexed sources")
    p_search.add_argument("query")
    p_search.add_argument("--dataset-id", action="append", default=[])
    p_search.add_argument("--doc-id", default="")
    p_search.add_argument("--doc-name", default="")
    p_search.add_argument("--limit", type=int, default=50)

    p_read = sub.add_parser("read", help="Read indexed source chunks")
    p_read.add_argument("--doc-id", default="")
    p_read.add_argument("--dataset-id", default="")
    p_read.add_argument("--doc-name", default="")
    p_read.add_argument("--q", default="")
    p_read.add_argument("--limit", type=int, default=80)
    p_read.add_argument("--kind", choices=["generic", "pdf", "excel"], default="generic")

    p_fs_list = sub.add_parser("fs-list", help="List whitelisted filesystem path")
    p_fs_list.add_argument("--root", default="docs")
    p_fs_list.add_argument("--path", default="")
    p_fs_list.add_argument("--depth", type=int, default=1)

    p_fs_read = sub.add_parser("fs-read", help="Read whitelisted text file")
    p_fs_read.add_argument("--root", default="docs")
    p_fs_read.add_argument("path")
    p_fs_read.add_argument("--max-chars", type=int, default=20000)

    p_fs_search = sub.add_parser("fs-search", help="Search whitelisted filesystem path")
    p_fs_search.add_argument("query")
    p_fs_search.add_argument("--root", default="docs")
    p_fs_search.add_argument("--path", default="")
    p_fs_search.add_argument("--content", action="store_true")
    p_fs_search.add_argument("--limit", type=int, default=50)

    p_fs_stat = sub.add_parser("fs-stat", help="Stat whitelisted filesystem path")
    p_fs_stat.add_argument("--root", default="docs")
    p_fs_stat.add_argument("path")

    p_fs_hash = sub.add_parser("fs-hash", help="Hash whitelisted file")
    p_fs_hash.add_argument("--root", default="docs")
    p_fs_hash.add_argument("path")

    args = parser.parse_args()
    h = harness()
    if args.cmd == "registry":
        _print(h.registry(category=args.category))
    elif args.cmd == "shortlist":
        _print(h.shortlist(args.question, mode=args.mode, limit=args.limit))
    elif args.cmd == "call":
        _print(h.call(args.tool, args.args_json))
    elif args.cmd == "dataset-map":
        _print(h.call("dataset_map", {"dataset_id": args.dataset_id, "depth": args.depth}))
    elif args.cmd == "search":
        _print(h.call("search_sources", {
            "q": args.query,
            "dataset_ids": args.dataset_id,
            "doc_id": args.doc_id,
            "doc_name": args.doc_name,
            "limit": args.limit,
        }))
    elif args.cmd == "read":
        tool = {"generic": "read_source", "pdf": "read_pdf_source", "excel": "read_excel_source"}[args.kind]
        _print(h.call(tool, {
            "doc_id": args.doc_id,
            "dataset_id": args.dataset_id,
            "doc_name": args.doc_name,
            "q": args.q,
            "limit": args.limit,
        }))
    elif args.cmd == "fs-list":
        _print(h.call("filesystem_list", {"root": args.root, "path": args.path, "depth": args.depth}))
    elif args.cmd == "fs-read":
        _print(h.call("filesystem_read_text", {"root": args.root, "path": args.path, "max_chars": args.max_chars}))
    elif args.cmd == "fs-search":
        _print(h.call("filesystem_search", {
            "root": args.root,
            "path": args.path,
            "q": args.query,
            "content": args.content,
            "limit": args.limit,
        }))
    elif args.cmd == "fs-stat":
        _print(h.call("filesystem_stat", {"root": args.root, "path": args.path}))
    elif args.cmd == "fs-hash":
        _print(h.call("filesystem_hash", {"root": args.root, "path": args.path}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
