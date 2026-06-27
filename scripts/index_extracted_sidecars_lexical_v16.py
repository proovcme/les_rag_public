#!/usr/bin/env python
"""v0.16 §6A — индексация sidecar-извлечений в отдельную FTS (extracted_fts). source_ref сохраняется;
дубли по source_ref не переиндексируются. dry-run по умолчанию.

  python scripts/index_extracted_sidecars_lexical_v16.py \
    --dataset-id <ID> --storage-root /Users/ovc/LES/storage/datasets \
    --dry-run --report artifacts/sidecar_lexical_index_v16_<ID>.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from proxy.services import sidecar_ops_service as ops


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-id", required=True)
    ap.add_argument("--storage-root", default="storage/datasets")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--write", action="store_true", help="реально записать в extracted_fts")
    ap.add_argument("--db-path", default=None)
    ap.add_argument("--report", default=None)
    args = ap.parse_args()
    dry = not args.write or args.dry_run
    rep = ops.lexical_index_extracted(args.dataset_id, storage_root=Path(args.storage_root),
                                      dry_run=dry, db_path=args.db_path)
    rep["qdrant"] = ops.qdrant_deferred_report(args.dataset_id, storage_root=Path(args.storage_root))
    print(f"# lexical extracted_fts | {args.dataset_id} | dry_run={rep['dry_run']}")
    print(f"  sidecar_items={rep['sidecar_items']} would_index={rep['would_index']} "
          f"indexed={rep['indexed']} skipped={rep['skipped_unchanged']} stale={rep['stale_warned']}")
    print(f"  db: {rep['db_path']}")
    print(f"  qdrant: points~{rep['qdrant']['estimated_qdrant_points']} → {rep['qdrant']['qdrant_status']} "
          f"(embedding_run={rep['qdrant']['embedding_run']})")
    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, ensure_ascii=False, indent=2))
        print(f"Отчёт: {out}")


if __name__ == "__main__":
    main()
