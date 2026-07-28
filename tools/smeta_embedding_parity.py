#!/usr/bin/env python3
"""Certify that stored smeta dense vectors and runtime query encoder share a space."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import numpy as np
from qdrant_client import QdrantClient

from backend.qdrant_adapter import EmbedClient
from backend.rag_config import embed_seq_len
from proxy.smeta_core.base_registry import active_base
from tools.build_smeta_norm_rag import _rows


def _cosine(left, right) -> float:
    a = np.asarray(left, dtype=np.float32)
    b = np.asarray(right, dtype=np.float32)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


def _sample(rows: list[dict[str, str]], count: int) -> list[dict[str, str]]:
    if len(rows) <= count:
        return rows
    indexes = sorted({round(i * (len(rows) - 1) / (count - 1)) for i in range(count)})
    return [rows[index] for index in indexes]


def main() -> int:
    from sentence_transformers import SentenceTransformer

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--threshold", type=float, default=0.999)
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--embed-url", default="http://127.0.0.1:8080")
    parser.add_argument("--certify", action="store_true")
    parser.add_argument("--manifest-path", type=Path)
    parser.add_argument("--report-path", type=Path, required=True)
    args = parser.parse_args()

    config = active_base()
    base_path = Path(config["base_path"])
    manifest_path = args.manifest_path or base_path.with_name(
        "les_smeta_norm_rag_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = _sample(_rows(base_path), max(2, args.samples))
    texts = [row["text"] for row in rows]

    local = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")
    local.max_seq_length = embed_seq_len()
    local_vectors = local.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        batch_size=min(16, len(texts)),
    ).tolist()
    runtime_vectors = EmbedClient(
        args.embed_url, model=str(manifest.get("embedding_model") or "qwen3-embedding-0.6b")
    ).encode_sync(texts)

    client = QdrantClient(
        url=args.qdrant_url, timeout=60.0, check_compatibility=False
    )
    ids = [str(uuid5(NAMESPACE_URL, f"les:smeta:norm:{row['norm_key']}")) for row in rows]
    stored_points = client.retrieve(
        args.collection, ids=ids, with_payload=False, with_vectors=True
    )
    stored_by_id = {str(point.id): point for point in stored_points}
    local_runtime = []
    stored_local = []
    missing = []
    for row, point_id, local_vector, runtime_vector in zip(
        rows, ids, local_vectors, runtime_vectors, strict=True
    ):
        point = stored_by_id.get(point_id)
        stored = (getattr(point, "vector", None) or {}).get("dense") if point else None
        if stored is None:
            missing.append(row["norm_key"])
            continue
        local_runtime.append(_cosine(local_vector, runtime_vector))
        stored_local.append(_cosine(stored, local_vector))

    minimum = min([*local_runtime, *stored_local], default=0.0)
    passed = bool(not missing and len(local_runtime) == len(rows) and minimum >= args.threshold)
    space_contract = {
        "model": "Qwen/Qwen3-Embedding-0.6B",
        "max_seq_length": embed_seq_len(),
        "document_mode": "raw",
        "normalization": "l2",
        "pooling": "exported-model-contract",
    }
    space_id = "qwen3-06b-s512-raw-l2-" + hashlib.sha256(
        json.dumps(space_contract, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    report = {
        "schema": "les.smeta.embedding-parity.v1",
        "status": "passed" if passed else "failed",
        "collection": args.collection,
        "samples": len(rows),
        "threshold": args.threshold,
        "stored_local_min": min(stored_local, default=0.0),
        "stored_local_mean": float(np.mean(stored_local)) if stored_local else 0.0,
        "local_runtime_min": min(local_runtime, default=0.0),
        "local_runtime_mean": float(np.mean(local_runtime)) if local_runtime else 0.0,
        "missing_norm_keys": missing,
        "embedding_space_id": space_id,
        "embedding_space_contract": space_contract,
        "base_sha256": hashlib.sha256(base_path.read_bytes()).hexdigest(),
        "updated_at": time.time(),
    }
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.report_path.with_suffix(args.report_path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(args.report_path)
    if args.certify and passed:
        manifest.update(
            {
                "embedding_space_id": space_id,
                "embedding_space_verified": True,
                "embedding_space_report": str(args.report_path),
            }
        )
        manifest_tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
        manifest_tmp.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        manifest_tmp.replace(manifest_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
