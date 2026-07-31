#!/usr/bin/env python3
"""Create or verify the immutable dataset scope for the general LES RAG."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.build_rag_contract_sibling import (
    _write_json_atomic,
    load_scope_manifest,
    scope_manifest_payload,
    scope_manifest_sha256,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    write = subparsers.add_parser("write")
    write.add_argument("--source-db", type=Path, required=True)
    write.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--source-db", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)

    args = parser.parse_args(argv)
    if not args.source_db.is_file():
        parser.error(f"source db not found: {args.source_db}")

    if args.command == "write":
        payload = scope_manifest_payload(args.source_db)
        _write_json_atomic(args.output, payload)
        digest = scope_manifest_sha256(payload)
        manifest_path = args.output
    else:
        try:
            payload, digest = load_scope_manifest(args.manifest, args.source_db)
        except ValueError as exc:
            parser.error(str(exc))
        manifest_path = args.manifest

    print(
        json.dumps(
            {
                "status": "verified",
                "manifest": str(manifest_path),
                "sha256": digest,
                "datasets": payload["datasets"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
