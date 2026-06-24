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


def _safe_under(root: Path, p: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except Exception:  # noqa: BLE001
        return False


def run(dataset_id: str, *, storage_root: Path, exts: set[str], max_files: int, max_mb: float,
        do_write: bool, confirm_runtime: bool, force: bool) -> dict:
    ddir = storage_root / dataset_id
    # GATE: запись в runtime storage только с явным разрешением (env + флаг)
    runtime = de.is_runtime_path(storage_root)
    write_blocked = ""
    effective_write = do_write
    if do_write and runtime and not (confirm_runtime and de.runtime_write_allowed()):
        effective_write = False
        write_blocked = ("runtime_sidecar_write_not_approved: запись в runtime storage требует "
                         "--confirm-runtime-write И env LES_ALLOW_RUNTIME_SIDECAR_WRITE=1; выполнен dry-run")
    rep = {"dataset_id": dataset_id, "storage_root": str(storage_root), "runtime_path": runtime,
           "dry_run": not effective_write, "write_requested": do_write, "write_blocked": write_blocked,
           "originals_mutated": False, "files_seen": 0, "would_write": 0, "wrote_sidecars": 0,
           "pdf_text_pages": 0, "pdf_no_text_layer": 0, "docx_paragraphs": 0, "xlsx_rows": 0,
           "unsupported": 0, "skipped_large": 0, "failures": 0, "by_status": Counter(), "manifest": ""}
    if not ddir.exists():
        rep["error"] = "dataset_dir_not_found"
        rep["by_status"] = {}
        return rep
    max_bytes = int(max_mb * 1024 * 1024)
    manifest_entries: list[dict] = []
    for p in sorted(ddir.rglob("*")):
        if rep["files_seen"] >= max_files:
            break
        if not p.is_file() or p.name.startswith(".") or f"/{de.SIDECAR_DIRNAME}/" in p.as_posix():
            continue
        ext = p.suffix.lower()
        if ext not in exts:
            continue
        rep["files_seen"] += 1
        if not _safe_under(ddir, p):
            continue
        try:
            st = p.stat()
            if st.st_size > max_bytes:
                rep["skipped_large"] += 1
                continue
        except OSError:
            continue
        rel = p.relative_to(ddir).as_posix()
        res = de.extract_file(p, ds=dataset_id, rel=rel)
        rep["by_status"][res.status] += 1
        if res.status == "skipped":
            rep["unsupported"] += 1
            continue
        if res.status == "no_text_layer" and ext == ".pdf":
            rep["pdf_no_text_layer"] += 1
        if res.status in ("unavailable", "failed"):
            rep["failures"] += 1
        for it in res.items:
            rep["pdf_text_pages"] += it.source_kind == "pdf_text"
            rep["docx_paragraphs"] += it.source_kind in ("docx_text", "docx_table")
            rep["xlsx_rows"] += it.source_kind == "xlsx_row"
        if not res.items:
            continue
        rep["would_write"] += 1
        sp = de.sidecar_path(storage_root, dataset_id, rel)
        if effective_write and (not sp.exists() or force):
            de.write_sidecar(storage_root, dataset_id, rel, res.items)
            rep["wrote_sidecars"] += 1
        manifest_entries.append({"original_relative_path": rel, "original_size": st.st_size,
                                 "original_mtime": st.st_mtime, "ext": ext, "status": res.status,
                                 "item_count": len(res.items), "sidecar_path": str(sp),
                                 "warnings": res.warnings})
    if effective_write and manifest_entries:
        mp = de.write_manifest(storage_root, dataset_id, manifest_entries, created_at="")
        rep["manifest"] = str(mp)
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
