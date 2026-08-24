"""RAPTOR publication into a generation-bound navigation collection.

The primary evidence collection is read-only here. RAPTOR summaries live in a
separate collection, so a failed or interrupted build cannot alter evidence
counts, SQLite reconciliation, or citations.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from qdrant_client import models

from backend.inference.bm25_sparse import encode_bm25
from backend.raptor_tree import RAPTOR_SCHEMA, RaptorLeaf, RaptorNode


RAPTOR_COLLECTION_SCHEMA = "les.rag.raptor-collection.v1"


@dataclass(frozen=True)
class RaptorDocumentRef:
    dataset_id: str
    file_name: str
    chunk_count: int
    source_hash: str = ""

    @property
    def document_id(self) -> str:
        value = f"{self.dataset_id}\0{self.file_name}"
        return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def source_snapshot_fingerprint(
    source_collection: str,
    documents: Iterable[RaptorDocumentRef],
    *,
    contract_fingerprint: str = "",
) -> str:
    digest = hashlib.sha256()
    digest.update(str(source_collection).encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(contract_fingerprint).encode("utf-8"))
    for document in sorted(documents, key=lambda item: (item.dataset_id, item.file_name)):
        for value in (
            document.dataset_id,
            document.file_name,
            str(document.chunk_count),
            document.source_hash,
        ):
            digest.update(b"\0")
            digest.update(value.encode("utf-8", errors="replace"))
    return digest.hexdigest()


def target_collection_name(source_collection: str) -> str:
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in source_collection)
    return f"{safe}__raptor_v1"


class RaptorQdrantStore:
    def __init__(
        self,
        client: Any,
        *,
        source_collection: str,
        target_collection: str,
        embed: Callable[[list[str]], list[list[float]]],
        vector_size: int,
        dense_name: str = "dense",
        sparse_name: str = "bm25_sparse",
    ) -> None:
        self.client = client
        self.source_collection = source_collection
        self.target_collection = target_collection
        self.embed = embed
        self.vector_size = int(vector_size)
        self.dense_name = dense_name
        self.sparse_name = sparse_name

    def ensure_collection(self) -> None:
        if not self.client.collection_exists(self.target_collection):
            self.client.create_collection(
                collection_name=self.target_collection,
                vectors_config={
                    self.dense_name: models.VectorParams(
                        size=self.vector_size,
                        distance=models.Distance.COSINE,
                    )
                },
                sparse_vectors_config={
                    self.sparse_name: models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )
        for field in ("dataset_id", "file_name", "document_id", "source_collection", "node_role"):
            self.client.create_payload_index(
                self.target_collection,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )

    def load_document(self, document: RaptorDocumentRef) -> list[RaptorLeaf]:
        conditions = [
            models.FieldCondition(
                key="dataset_id", match=models.MatchValue(value=document.dataset_id)
            ),
            models.FieldCondition(
                key="file_name", match=models.MatchValue(value=document.file_name)
            ),
            models.FieldCondition(
                key="node_role", match=models.MatchValue(value="evidence")
            ),
        ]
        leaves: list[RaptorLeaf] = []
        offset = None
        while True:
            points, offset = self.client.scroll(
                collection_name=self.source_collection,
                scroll_filter=models.Filter(must=conditions),
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                payload = dict(getattr(point, "payload", None) or {})
                text = str(payload.get("text") or "").strip()
                if text:
                    leaves.append(
                        RaptorLeaf(
                            point_id=str(getattr(point, "id", "")),
                            document_id=document.document_id,
                            text=text,
                        )
                    )
            if offset is None:
                break
        if not leaves:
            raise RuntimeError(
                "RAPTOR_EVIDENCE_LEAVES_MISSING: "
                f"dataset={document.dataset_id}, document={document.file_name}"
            )
        return leaves

    def reset_source(self) -> None:
        """Remove only this generation's navigation nodes before a clean rebuild."""
        self.client.delete(
            collection_name=self.target_collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="source_collection",
                            match=models.MatchValue(value=self.source_collection),
                        )
                    ]
                )
            ),
            wait=True,
        )

    def publish_document(self, document: RaptorDocumentRef, nodes: list[RaptorNode]) -> None:
        selector = models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=document.document_id),
                    ),
                    models.FieldCondition(
                        key="source_collection",
                        match=models.MatchValue(value=self.source_collection),
                    ),
                ]
            )
        )
        self.client.delete(
            collection_name=self.target_collection,
            points_selector=selector,
            wait=True,
        )
        if not nodes:
            return
        texts = [f"{node.title}\n{node.summary}".strip() for node in nodes]
        vectors = self.embed(texts)
        if len(vectors) != len(nodes):
            raise RuntimeError("RAPTOR_EMBEDDING_COUNT_MISMATCH")
        points = []
        for node, text, dense in zip(nodes, texts, vectors, strict=True):
            if len(dense) != self.vector_size:
                raise RuntimeError("RAPTOR_EMBEDDING_DIMENSION_MISMATCH")
            sparse = encode_bm25(text)
            if not sparse:
                raise RuntimeError("RAPTOR_SPARSE_VECTOR_EMPTY")
            points.append(
                models.PointStruct(
                    id=node.node_id,
                    vector={
                        self.dense_name: dense,
                        self.sparse_name: models.SparseVector(
                            indices=list(sparse), values=list(sparse.values())
                        ),
                    },
                    payload={
                        **node.payload(),
                        "schema": RAPTOR_SCHEMA,
                        "collection_schema": RAPTOR_COLLECTION_SCHEMA,
                        "dataset_id": document.dataset_id,
                        "file_name": document.file_name,
                        "document_id": document.document_id,
                        "source_collection": self.source_collection,
                        "text": text,
                    },
                )
            )
        self.client.upsert(
            collection_name=self.target_collection,
            points=points,
            wait=True,
        )

    def readiness(self, *, expected_nodes: int, source_fingerprint: str) -> dict[str, Any]:
        total = int(self.client.count(self.target_collection, exact=True).count)
        dense = int(
            self.client.count(
                self.target_collection,
                count_filter=models.Filter(
                    must=[models.HasVectorCondition(has_vector=self.dense_name)]
                ),
                exact=True,
            ).count
        )
        sparse = int(
            self.client.count(
                self.target_collection,
                count_filter=models.Filter(
                    must=[models.HasVectorCondition(has_vector=self.sparse_name)]
                ),
                exact=True,
            ).count
        )
        ready = bool(expected_nodes >= 0 and total == expected_nodes == dense == sparse)
        return {
            "schema": RAPTOR_COLLECTION_SCHEMA,
            "status": "ready" if ready else "blocked",
            "ready": ready,
            "source_collection": self.source_collection,
            "target_collection": self.target_collection,
            "source_fingerprint": source_fingerprint,
            "expected_nodes": int(expected_nodes),
            "points": total,
            "dense_points": dense,
            "sparse_points": sparse,
        }
