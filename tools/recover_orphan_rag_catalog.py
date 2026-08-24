"""Dry-run/apply recovery for MetaDB datasets preserved only in Qdrant."""

from __future__ import annotations

import argparse
import json
import os

from backend.rag_config import rag_collection_name, rag_meta_db_path
from proxy.services.lexical_index_service import LexicalIndex
from proxy.services.rag_catalog_recovery_service import (
    link_recovered_datasets,
    rebuild_lexical_catalog,
    recover_metadb_catalog,
    scan_qdrant_catalog,
)


def _dataset_mapping(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        dataset_id, separator, name = value.partition("=")
        if not separator or not dataset_id.strip() or not name.strip():
            raise ValueError("--dataset must use DATASET_ID=NAME")
        result[dataset_id.strip()] = name.strip()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--collection", default=rag_collection_name())
    parser.add_argument("--meta-db", default=rag_meta_db_path())
    parser.add_argument("--dataset", action="append", default=[], help="DATASET_ID=NAME")
    parser.add_argument("--project-name", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    inventory = scan_qdrant_catalog(
        qdrant_url=args.qdrant_url,
        collection=args.collection,
        meta_db_path=args.meta_db,
    )
    if not args.apply:
        print(json.dumps(inventory, ensure_ascii=False, indent=2))
        return 0

    names = _dataset_mapping(args.dataset)
    result = recover_metadb_catalog(
        inventory=inventory,
        dataset_names=names,
        meta_db_path=args.meta_db,
    )
    recovered_ids = [str(item["dataset_id"]) for item in inventory.get("orphans") or []]
    result["lexical"] = rebuild_lexical_catalog(
        qdrant_url=args.qdrant_url,
        collection=args.collection,
        dataset_ids=recovered_ids,
        lexical_index=LexicalIndex(db_path=args.meta_db),
    )
    if args.project_name.strip() and recovered_ids:
        result["project_id"] = link_recovered_datasets(
            meta_db_path=args.meta_db,
            project_name=args.project_name.strip(),
            dataset_ids=recovered_ids,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
