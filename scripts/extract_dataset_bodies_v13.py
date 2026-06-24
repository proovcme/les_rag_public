#!/usr/bin/env python
"""Unified Construction Harness v0.13 — ingestion-lite: извлечь текст PDF/DOCX/XLSX в sidecar.

READ-ONLY к оригиналам, БЕЗ OCR, без облака. Пишет sidecar-JSONL под
storage/datasets/{ds}/_extracted/. --dry-run ничего не пишет. PDF без текст-слоя → no_text_layer
(не фейк). path-traversal безопасно, лимит размера, отчёт JSON.

  python scripts/extract_dataset_bodies_v13.py --dataset-id <ID> \
    --storage-root /Users/ovc/LES/storage/datasets --dry-run --report artifacts/extract_v13_dryrun.json
  python scripts/extract_dataset_bodies_v13.py --dataset-id <ID> \
    --storage-root /Users/ovc/LES/storage/datasets --report artifacts/extract_v13_report.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from proxy.services import doc_extract_service as de


def _safe_under(root: Path, p: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except Exception:  # noqa: BLE001
        return False


def run(dataset_id: str, *, storage_root: Path, exts: set[str], max_files: int, max_mb: float,
        dry_run: bool, force: bool) -> dict:
    ddir = storage_root / dataset_id
    rep = {"dataset_id": dataset_id, "dry_run": dry_run, "files_seen": 0, "files_extracted": 0,
           "files_skipped": 0, "pdf_text_pages": 0, "pdf_no_text_layer": 0, "docx_paragraphs": 0,
           "xlsx_rows": 0, "eml_messages": 0, "failures": 0, "by_status": Counter(), "sidecars": []}
    if not ddir.exists():
        rep["error"] = "dataset_dir_not_found"
        return rep
    max_bytes = int(max_mb * 1024 * 1024)
    for p in sorted(ddir.rglob("*")):
        if len(rep["sidecars"]) >= max_files:
            break
        if not p.is_file() or p.name.startswith(".") or f"/{de.SIDECAR_DIRNAME}/" in p.as_posix():
            continue
        ext = p.suffix.lower()
        if ext not in exts:
            continue
        rep["files_seen"] += 1
        if not _safe_under(ddir, p):
            rep["files_skipped"] += 1
            continue
        try:
            if p.stat().st_size > max_bytes:
                rep["files_skipped"] += 1
                continue
        except OSError:
            rep["files_skipped"] += 1
            continue
        rel = p.relative_to(ddir).as_posix()
        sp = de.sidecar_path(storage_root, dataset_id, rel)
        if sp.exists() and not force:
            rep["files_skipped"] += 1
            continue
        res = de.extract_file(p, ds=dataset_id, rel=rel)
        rep["by_status"][res.status] += 1
        if res.status == "no_text_layer" and ext == ".pdf":
            rep["pdf_no_text_layer"] += 1
        if res.status in ("unavailable", "failed"):
            rep["failures"] += 1
            continue
        if not res.items:
            continue
        for it in res.items:
            if it.source_kind == "pdf_text":
                rep["pdf_text_pages"] += 1
            elif it.source_kind in ("docx_text", "docx_table"):
                rep["docx_paragraphs"] += 1
            elif it.source_kind == "xlsx_row":
                rep["xlsx_rows"] += 1
            elif it.source_kind == "eml_body":
                rep["eml_messages"] += 1
        if not dry_run:
            de.write_sidecar(storage_root, dataset_id, rel, res.items)
        rep["files_extracted"] += 1
        rep["sidecars"].append(f"{dataset_id}/{rel}")
    rep["by_status"] = dict(rep["by_status"])
    return rep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-id", required=True)
    ap.add_argument("--storage-root", default="storage/datasets")
    ap.add_argument("--extensions", default="pdf,docx,xlsx,txt,md,csv")
    ap.add_argument("--max-files", type=int, default=2000)
    ap.add_argument("--max-file-size-mb", type=float, default=40.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="перезаписать существующие sidecar'ы")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    exts = {("." + e.strip().lstrip(".")) for e in args.extensions.split(",") if e.strip()}
    root = Path(args.storage_root)
    rep = run(args.dataset_id, storage_root=root, exts=exts, max_files=args.max_files,
              max_mb=args.max_file_size_mb, dry_run=args.dry_run, force=args.force)

    print(f"# extract v0.13 | dataset={args.dataset_id} | {'DRY-RUN' if args.dry_run else 'WRITE'} "
          f"| root={root}")
    for k in ("files_seen", "files_extracted", "files_skipped", "pdf_text_pages", "pdf_no_text_layer",
              "docx_paragraphs", "xlsx_rows", "failures"):
        print(f"  {k:20s}: {rep.get(k)}")
    print(f"  by_status           : {rep.get('by_status')}")
    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, ensure_ascii=False, indent=2))
        print(f"\nОтчёт: {out}")


if __name__ == "__main__":
    main()
