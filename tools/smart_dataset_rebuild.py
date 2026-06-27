#!/usr/bin/env python3
"""Reset LES RAG metadata/Qdrant and register smart datasets from a plan.

This tool is intentionally two-stage:
1. Run tools/smart_dataset_plan.py and inspect the plan.
2. Run this script with --execute --confirm-reset RESET_SMART_DATASETS.

It registers files as PENDING in smart datasets. Vectorization should then be
done in small batches through /api/rag/parse-batch/{dataset_id} or a guarded
operator loop, not as one huge parse.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import qdrant_client

from backend.qdrant_adapter import QdrantLlamaIndexAdapter
from tools.smart_dataset_plan import build_plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", default="RAG_Content")
    parser.add_argument("--content-dir", default="storage/datasets")
    parser.add_argument("--db-path", default="data/les_meta.db")
    parser.add_argument("--qdrant-url", default="http://10.195.146.98:6333")
    parser.add_argument("--mlx-url", default="http://127.0.0.1:8080")
    parser.add_argument("--embed-model", default="BAAI/bge-m3")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume-existing", action="store_true")
    parser.add_argument("--confirm-reset", default="")
    return parser.parse_args()


def backup_path(path: Path) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return path.with_name(f"{path.name}.bak_smart_{stamp}")


def reset_local_state(db_path: Path, content_dir: Path, qdrant_url: str) -> dict:
    backups = {}
    if db_path.exists():
        target = backup_path(db_path)
        shutil.copy2(db_path, target)
        backups["sqlite"] = target.as_posix()
        db_path.unlink()

    if content_dir.exists():
        target = backup_path(content_dir)
        if target.exists():
            raise RuntimeError(f"backup target already exists: {target}")
        shutil.move(content_dir, target)
        backups["content_dir"] = target.as_posix()
    content_dir.mkdir(parents=True, exist_ok=True)

    client = qdrant_client.QdrantClient(url=qdrant_url)
    try:
        client.delete_collection("les_rag")
        backups["qdrant_collection_deleted"] = "les_rag"
    except Exception as error:
        backups["qdrant_delete_warning"] = str(error)
    return backups


async def register_plan(args: argparse.Namespace, plan: dict) -> dict:
    adapter = QdrantLlamaIndexAdapter(
        qdrant_url=args.qdrant_url,
        mlx_url=args.mlx_url,
        embed_model_name=args.embed_model,
        content_dir=args.content_dir,
    )
    await adapter._ensure_collection()

    result = {"datasets": [], "files": 0}
    existing = {dataset.name: dataset.id for dataset in await adapter.list_datasets()}
    for dataset_name, items in plan["plan"].items():
        dataset_id = existing.get(dataset_name)
        if dataset_id is None:
            dataset_id = await adapter.create_dataset(dataset_name)
        for item in items:
            source = Path(item["path"])
            await adapter.upload_file(dataset_id, source, relative_path=item["relative_path"])
        result["datasets"].append(
            {"id": dataset_id, "name": dataset_name, "pending_files": len(items)}
        )
        result["files"] += len(items)
    return result


async def amain() -> int:
    args = parse_args()
    if not args.execute:
        raise SystemExit("Refusing to reset without --execute")
    if not args.resume_existing and args.confirm_reset != "RESET_SMART_DATASETS":
        raise SystemExit("Refusing to reset without --confirm-reset RESET_SMART_DATASETS")

    source_root = Path(args.source_root)
    db_path = Path(args.db_path)
    content_dir = Path(args.content_dir)
    if not source_root.exists():
        raise SystemExit(f"source root not found: {source_root}")

    plan = build_plan(source_root)
    backups = {}
    if not args.resume_existing:
        backups = reset_local_state(db_path, content_dir, args.qdrant_url)
    registered = await register_plan(args, plan)
    print(
        json.dumps(
            {
                "status": "registered",
                "backups": backups,
                "registered": registered,
                "datasets": plan["datasets"],
                "errors": plan["errors"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
