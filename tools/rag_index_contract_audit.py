#!/usr/bin/env python3
"""Read-only sample audit of point-level embedding/chunk contracts."""

from __future__ import annotations

import argparse
import json
import urllib.request
from collections import Counter
from typing import Any

from backend.qdrant_adapter import _embedding_cache_fingerprint
from backend.rag_config import index_contract_payload, rag_collection_name


PAYLOAD_FIELDS = [
    "embedding_fingerprint",
    "embedding_backend",
    "embedding_model_id",
    "embedding_profile",
    "embedding_coreml_model",
    "embedding_coreml_seq_len",
    "embedding_coreml_compute_units",
    "embedding_coreml_fallback",
    "embedding_chunk_unit",
    "embedding_chunk_length",
    "embedding_chunk_budget",
    "embedding_budget_enforced",
    "content_sanitized",
]


def summarize_points(points: list[dict[str, Any]], *, current_fingerprint: str) -> dict[str, Any]:
    payloads = [point.get("payload") or {} for point in points]
    fingerprints = Counter(str(item.get("embedding_fingerprint") or "<missing>") for item in payloads)
    model_ids = Counter(str(item.get("embedding_model_id") or "<missing>") for item in payloads)
    backends = Counter(str(item.get("embedding_backend") or "<missing>") for item in payloads)
    budget_covered = sum(item.get("embedding_budget_enforced") is True for item in payloads)
    sanitation_reported = sum("content_sanitized" in item for item in payloads)
    if not points:
        status = "empty"
    elif len(fingerprints) != 1:
        status = "mixed_fingerprints"
    elif next(iter(fingerprints)) != current_fingerprint:
        status = "fingerprint_mismatch"
    elif budget_covered != len(points) or sanitation_reported != len(points):
        status = "legacy_chunk_contract"
    else:
        status = "compatible_sample"
    return {
        "schema": "les.rag.index-contract-audit.v1",
        "status": status,
        "sample_points": len(points),
        "current_point_fingerprint": current_fingerprint,
        "fingerprints": dict(fingerprints.most_common()),
        "model_ids": dict(model_ids.most_common()),
        "backends": dict(backends.most_common()),
        "embedding_budget_coverage": budget_covered,
        "sanitation_metadata_coverage": sanitation_reported,
        "adoptable": status == "compatible_sample",
    }


def fetch_sample(*, qdrant_url: str, collection: str, limit: int, page_size: int = 256) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    offset: Any = None
    while len(points) < limit:
        body: dict[str, Any] = {
            "limit": min(page_size, limit - len(points)),
            "with_payload": PAYLOAD_FIELDS,
            "with_vector": False,
        }
        if offset is not None:
            body["offset"] = offset
        request = urllib.request.Request(
            f"{qdrant_url.rstrip('/')}/collections/{collection}/points/scroll",
            data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        result = payload.get("result") or {}
        batch = result.get("points") or []
        points.extend(batch)
        offset = result.get("next_page_offset")
        if not batch or offset is None:
            break
    return points[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--collection", default=rag_collection_name())
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    points = fetch_sample(
        qdrant_url=args.qdrant_url,
        collection=args.collection,
        limit=max(1, args.limit),
    )
    report = summarize_points(points, current_fingerprint=_embedding_cache_fingerprint())
    report["collection"] = args.collection
    report["expected_index_contract"] = index_contract_payload()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["adoptable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
