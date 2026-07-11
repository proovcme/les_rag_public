"""Build a fail-closed typed sibling smeta base from official FGIS data.

The command never overwrites the active v1 files and never reindexes RAG. Operators may
start with a bounded collection set, then resume into the same typed raw parquet.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from tools import gesn_bulk_import
from tools.build_smeta_structured_base import build_structured_base
from tools.gesn_unify_base import build_unified


DEFAULT_ROOT = Path("storage/cache/gesn_fgis_v2")
DEFAULT_RAW = DEFAULT_ROOT / "typed_raw.parquet"
DEFAULT_UNIFIED = Path("data/gesn_base/gesn2022_typed_v2.parquet")
DEFAULT_AUDIT = Path("data/gesn_base/gesn2022_typed_v2_audit.json")
DEFAULT_SQLITE = Path("data/smeta_base/les_smeta_base_v2.sqlite")
DEFAULT_MANIFEST = Path("data/smeta_base/les_smeta_base_v2_manifest.json")
DEFAULT_INTEGRITY = Path("data/smeta_base/les_smeta_base_v2_integrity.json")


def _collections(value: str) -> list[int]:
    if str(value).strip().lower() == "all":
        return list(gesn_bulk_import.ALL_COLLECTION_PREFIXES)
    result = sorted({int(item.strip()) for item in str(value).split(",") if item.strip()})
    invalid = [item for item in result if item < 1 or item > 69]
    if invalid or not result:
        raise ValueError("collections must be comma-separated numbers 01..69 or 'all'")
    return result


def build_sibling(
    *,
    collections: list[int],
    raw_out: Path = DEFAULT_RAW,
    unified_out: Path = DEFAULT_UNIFIED,
    audit_out: Path = DEFAULT_AUDIT,
    sqlite_out: Path = DEFAULT_SQLITE,
    manifest_out: Path = DEFAULT_MANIFEST,
    integrity_out: Path = DEFAULT_INTEGRITY,
    rate: float = 1.0,
    limit: int | None = None,
    resume: bool = True,
) -> dict:
    raw_out.parent.mkdir(parents=True, exist_ok=True)
    download = gesn_bulk_import.run(
        sborniki=collections,
        out_path=raw_out,
        rate=rate,
        limit=limit,
        resume=resume,
    )
    audit = build_unified(
        legacy=raw_out,
        overlay=Path("__typed_overlay_not_configured__"),
        out=unified_out,
        audit_out=audit_out,
    )
    manifest = build_structured_base(
        source=unified_out,
        out=sqlite_out,
        manifest_out=manifest_out,
        integrity_out=integrity_out,
    )
    return {
        "schema": "smeta_base_v2_build_v1",
        "active_base_changed": False,
        "rag_reindexed": False,
        "collections": collections,
        "download": download,
        "audit": audit,
        "manifest": manifest,
        "paths": {
            "raw": str(raw_out),
            "unified": str(unified_out),
            "audit": str(audit_out),
            "sqlite": str(sqlite_out),
            "manifest": str(manifest_out),
            "integrity": str(integrity_out),
        },
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build typed sibling smeta machine base v2")
    parser.add_argument("--collections", default="all", help="comma-separated 01..69 or all")
    parser.add_argument("--rate", type=float, default=1.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--raw-out", default=str(DEFAULT_RAW))
    parser.add_argument("--unified-out", default=str(DEFAULT_UNIFIED))
    parser.add_argument("--audit-out", default=str(DEFAULT_AUDIT))
    parser.add_argument("--sqlite-out", default=str(DEFAULT_SQLITE))
    parser.add_argument("--manifest-out", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--integrity-out", default=str(DEFAULT_INTEGRITY))
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = build_sibling(
        collections=_collections(args.collections),
        raw_out=Path(args.raw_out),
        unified_out=Path(args.unified_out),
        audit_out=Path(args.audit_out),
        sqlite_out=Path(args.sqlite_out),
        manifest_out=Path(args.manifest_out),
        integrity_out=Path(args.integrity_out),
        rate=args.rate,
        limit=args.limit,
        resume=not args.no_resume,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if (result.get("manifest") or {}).get("integrity", {}).get("verdict") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
