#!/usr/bin/env python
"""Unified Construction Harness v0.14 — operator-safe sidecar extraction (gate + manifest).

READ-ONLY оригиналы, БЕЗ OCR, без облака. Политика записи:
- dry-run по умолчанию;
- --write-sidecars — писать sidecar'ы (под _extracted/);
- запись в RUNTIME storage (/Users/ovc/LES) ДОПОЛНИТЕЛЬНО требует --confirm-runtime-write И
  env LES_ALLOW_RUNTIME_SIDECAR_WRITE=1; иначе → отказ (runtime_sidecar_write_not_approved), dry-run.
Manifest (_extracted/manifest.json) фиксирует mtime/size оригиналов → staleness.

  # dry-run на реальном датасете (read-only, всегда можно)
  python scripts/extract_dataset_bodies_v14.py --dataset-id <ID> \
    --storage-root /Users/ovc/LES/storage/datasets --dry-run --report artifacts/extract_v14_dryrun.json
  # запись с разрешением оператора
  LES_ALLOW_RUNTIME_SIDECAR_WRITE=1 python scripts/extract_dataset_bodies_v14.py --dataset-id <ID> \
    --storage-root /Users/ovc/LES/storage/datasets --write-sidecars --confirm-runtime-write \
    --report artifacts/extract_v14_write.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from proxy.services import doc_extract_service as de


def run(dataset_id: str, *, storage_root: Path, exts: set[str], max_files: int, max_mb: float,
        do_write: bool, confirm_runtime: bool, force: bool) -> dict:
    """v0.17: ядро перенесено в sidecar_ops_service.run_extraction (runtime-эндпоинты не зависят от
    скрипт-файла). CLI остаётся тонкой обёрткой."""
    from proxy.services.sidecar_ops_service import run_extraction
    return run_extraction(dataset_id, storage_root=storage_root, exts=exts, max_files=max_files,
                          max_mb=max_mb, do_write=do_write, confirm_runtime=confirm_runtime, force=force)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-id", required=True)
    ap.add_argument("--storage-root", default="storage/datasets")
    ap.add_argument("--extensions", default="pdf,docx,xlsx,txt,md,csv")
    ap.add_argument("--max-files", type=int, default=2000)
    ap.add_argument("--max-file-size-mb", type=float, default=40.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--write-sidecars", action="store_true")
    ap.add_argument("--confirm-runtime-write", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    exts = {("." + e.strip().lstrip(".")) for e in args.extensions.split(",") if e.strip()}
    do_write = args.write_sidecars and not args.dry_run
    rep = run(args.dataset_id, storage_root=Path(args.storage_root), exts=exts, max_files=args.max_files,
              max_mb=args.max_file_size_mb, do_write=do_write, confirm_runtime=args.confirm_runtime_write,
              force=args.force)

    mode = "WRITE" if not rep["dry_run"] else ("DRY-RUN (gate)" if rep["write_blocked"] else "DRY-RUN")
    print(f"# extract v0.14 | dataset={args.dataset_id} | {mode} | runtime={rep['runtime_path']}")
    for k in ("files_seen", "would_write", "wrote_sidecars", "pdf_text_pages", "pdf_no_text_layer",
              "docx_paragraphs", "xlsx_rows", "unsupported", "failures"):
        print(f"  {k:18s}: {rep.get(k)}")
    print(f"  by_status         : {rep.get('by_status')}")
    print(f"  originals_mutated : {rep['originals_mutated']}")
    if rep["write_blocked"]:
        print(f"  ⛔ {rep['write_blocked']}")
    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, ensure_ascii=False, indent=2))
        print(f"\nОтчёт: {out}")


if __name__ == "__main__":
    main()
