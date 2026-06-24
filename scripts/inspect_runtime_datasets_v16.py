#!/usr/bin/env python
"""v0.16 §1 — инвентаризация датасетов рантайма (БЕЗ записи): что можно извлечь, что уже извлечено,
почта/нормы/проектные/сметные. Сохраняет JSON.

  python scripts/inspect_runtime_datasets_v16.py \
    --storage-root /Users/ovc/LES/storage/datasets \
    --output artifacts/runtime_dataset_inventory_v16.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from proxy.services import sidecar_ops_service as ops


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--storage-root", default="storage/datasets")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()
    inv = ops.inventory_datasets(Path(args.storage_root))
    print(f"# инвентарь рантайма | датасетов: {inv['dataset_count']}")
    print(f"  mail:    {len(inv['mail_datasets'])}  {inv['mail_datasets'][:3]}")
    print(f"  norm:    {len(inv['norm_datasets'])}  {inv['norm_datasets'][:3]}")
    print(f"  project: {len(inv['project_like_datasets'])}  {inv['project_like_datasets'][:3]}")
    print(f"  extract-candidates: {len(inv['extraction_candidates'])}")
    print(f"  already-extracted:  {len(inv['already_extracted'])}  {inv['already_extracted'][:3]}")
    print("  топ-датасеты:")
    for d in sorted(inv["datasets"], key=lambda x: -x["file_count"])[:8]:
        print(f"    {d['dataset_id'][:8]} files={d['file_count']:4d} pdf={d['pdf_count']} "
              f"docx={d['docx_count']} xlsx={d['xlsx_count']} eml={d['eml_count']} md={d['md_count']} "
              f"sidecar={d['sidecar_count']} guess={d['corpus_guess']}")
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(inv, ensure_ascii=False, indent=2))
        print(f"\nОтчёт: {out}")


if __name__ == "__main__":
    main()
