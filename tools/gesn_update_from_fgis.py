"""Download/update GESN raw cache from FGIS and rebuild the single unified base."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from backend.runtime_paths import mutable_path
from tools import gesn_bulk_import
from tools import build_smeta_service_rag
from tools.build_smeta_structured_base import (
    DEFAULT_MANIFEST as DEFAULT_STRUCTURED_MANIFEST,
    DEFAULT_OUT as DEFAULT_STRUCTURED_OUT,
)
from tools.gesn_unify_base import (
    DEFAULT_AUDIT,
    DEFAULT_LEGACY,
    DEFAULT_OUT,
    DEFAULT_OVERLAY,
    build_unified,
)
from tools.smeta_generation_coordinator import publish_generation as publish_smeta_generation

DEFAULT_STATUS = Path("storage/jobs/gesn_fgis_update_status.json")


def _write_status(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated_at": datetime.now(timezone.utc).isoformat(), **data}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_update(
    *,
    all_sborniki: bool = True,
    sbornik: int | None = None,
    raw_out: Path = DEFAULT_LEGACY,
    overlay: Path = DEFAULT_OVERLAY,
    unified_out: Path = DEFAULT_OUT,
    audit_out: Path = DEFAULT_AUDIT,
    structured_out: Path = DEFAULT_STRUCTURED_OUT,
    structured_manifest_out: Path = DEFAULT_STRUCTURED_MANIFEST,
    service_rag_out: Path = build_smeta_service_rag.DEFAULT_OUT,
    status_out: Path = DEFAULT_STATUS,
    rate: float = 1.0,
    limit: int | None = None,
    no_resume: bool = False,
    skip_structured: bool = False,
    skip_service_rag: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict:
    from proxy.smeta_core.base_registry import active_base

    raw_out.parent.mkdir(parents=True, exist_ok=True)
    initial = {"status": "running", "stage": "download", "raw_out": str(raw_out)}
    _write_status(status_out, initial)
    if progress_callback:
        progress_callback(initial)
    sborniki = list(gesn_bulk_import.ALL_COLLECTION_PREFIXES) if all_sborniki else [int(sbornik or 0)]
    def _download_progress(progress: dict[str, Any]) -> None:
        payload = {"status": "running", "stage": "download", "raw_out": str(raw_out), "progress": progress}
        _write_status(status_out, payload)
        if progress_callback:
            progress_callback(payload)

    stats = gesn_bulk_import.run(
        sborniki=sborniki,
        out_path=raw_out,
        rate=rate,
        limit=limit,
        resume=not no_resume,
        progress_callback=_download_progress,
    )
    unify_payload = {"status": "running", "stage": "unify", "download": stats}
    _write_status(status_out, unify_payload)
    if progress_callback:
        progress_callback(unify_payload)
    base_config = active_base()
    minimum_norms = int(base_config.get("minimum_norms") or 1)
    audit = build_unified(
        legacy=raw_out,
        overlay=overlay,
        out=unified_out,
        audit_out=audit_out,
        minimum_norms=minimum_norms,
    )
    structured: dict | None = None
    if not skip_structured:
        structured_payload = {
                "status": "running",
                "stage": "structured",
                "download": stats,
                "audit": audit,
                "structured_out": str(structured_out),
            }
        _write_status(status_out, structured_payload)
        if progress_callback:
            progress_callback(structured_payload)
        configured_base = Path(str(base_config.get("base_path") or ""))
        uses_configured_base = configured_base.resolve(strict=False) == structured_out.resolve(
            strict=False
        )
        active_integrity = (
            Path(str(base_config.get("integrity_path") or ""))
            if uses_configured_base and base_config.get("integrity_path")
            else structured_out.with_name(f"{structured_out.stem}_integrity.json")
        )
        structured_generation = publish_smeta_generation(
            source=unified_out,
            active_base=structured_out,
            active_base_manifest=structured_manifest_out,
            active_integrity=active_integrity,
            active_rag_manifest=structured_out.with_name(
                "les_smeta_norm_rag_manifest.json"
            ),
            generations_root=mutable_path("storage/smeta_generations"),
            alias=str(base_config.get("rag_collection") or "les_smeta_norm_cards"),
            minimum_norms=minimum_norms,
        )
        structured = structured_generation.get("structured") or {}
    else:
        structured_generation = None
    service_rag: dict | None = None
    if not skip_service_rag:
        service_rag_payload = {
                "status": "running",
                "stage": "service_rag",
                "download": stats,
                "audit": audit,
                "structured": structured,
                "service_rag_out": str(service_rag_out),
            }
        _write_status(status_out, service_rag_payload)
        if progress_callback:
            progress_callback(service_rag_payload)
        service_rag = build_smeta_service_rag.build(service_rag_out)
    result = {
        "status": "done",
        "stage": "done",
        "download": stats,
        "audit": audit,
        "structured": structured,
        "structured_generation": structured_generation,
        "service_rag": service_rag,
    }
    _write_status(status_out, result)
    if progress_callback:
        progress_callback(result)
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update GESN unified base from official FGIS")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="all FGIS numeric prefixes 01..69")
    group.add_argument("--sbornik", type=int, help="one collection, e.g. 12")
    parser.add_argument("--raw-out", default=str(DEFAULT_LEGACY))
    parser.add_argument("--overlay", default=str(DEFAULT_OVERLAY))
    parser.add_argument("--unified-out", default=str(DEFAULT_OUT))
    parser.add_argument("--audit-out", default=str(DEFAULT_AUDIT))
    parser.add_argument("--structured-out", default=str(DEFAULT_STRUCTURED_OUT))
    parser.add_argument("--structured-manifest-out", default=str(DEFAULT_STRUCTURED_MANIFEST))
    parser.add_argument("--service-rag-out", default=str(build_smeta_service_rag.DEFAULT_OUT))
    parser.add_argument("--status-out", default=str(DEFAULT_STATUS))
    parser.add_argument("--rate", type=float, default=1.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--skip-structured", action="store_true")
    parser.add_argument("--skip-service-rag", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = run_update(
        all_sborniki=bool(args.all or not args.sbornik),
        sbornik=args.sbornik,
        raw_out=Path(args.raw_out),
        overlay=Path(args.overlay),
        unified_out=Path(args.unified_out),
        audit_out=Path(args.audit_out),
        structured_out=Path(args.structured_out),
        structured_manifest_out=Path(args.structured_manifest_out),
        service_rag_out=Path(args.service_rag_out),
        status_out=Path(args.status_out),
        rate=args.rate,
        limit=args.limit,
        no_resume=args.no_resume,
        skip_structured=args.skip_structured,
        skip_service_rag=args.skip_service_rag,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
