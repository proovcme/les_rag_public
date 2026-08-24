from types import SimpleNamespace

import pytest

from backend.raptor_qdrant_store import (
    RaptorDocumentRef,
    RaptorQdrantStore,
    source_snapshot_fingerprint,
    target_collection_name,
)
from backend.raptor_tree import RaptorNode


class FakeClient:
    def __init__(self):
        self.created = []
        self.deleted = []
        self.upserts = []
        self.pages = []
        self.counts = {"total": 1, "dense": 1, "sparse": 1}

    def collection_exists(self, _collection):
        return False

    def create_collection(self, **kwargs):
        self.created.append(kwargs)

    def create_payload_index(self, *_args, **_kwargs):
        return None

    def scroll(self, **_kwargs):
        if self.pages:
            return self.pages.pop(0)
        return [], None

    def delete(self, **kwargs):
        self.deleted.append(kwargs)

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)

    def count(self, _collection, *, count_filter=None, exact=True):
        assert exact is True
        if count_filter is None:
            return SimpleNamespace(count=self.counts["total"])
        name = count_filter.must[0].has_vector
        return SimpleNamespace(count=self.counts["dense" if name == "dense" else "sparse"])


def test_source_snapshot_changes_on_document_content_identity():
    first = [RaptorDocumentRef("ds", "a.pdf", 2, "hash-a")]
    second = [RaptorDocumentRef("ds", "a.pdf", 2, "hash-b")]
    assert source_snapshot_fingerprint("main", first) != source_snapshot_fingerprint("main", second)
    assert target_collection_name("main/active") == "main-active__raptor_v1"


def test_store_reads_only_evidence_and_publishes_waited_dense_sparse_nodes():
    client = FakeClient()
    client.pages = [
        ([SimpleNamespace(id="leaf-1", payload={"text": "Evidence text"})], None)
    ]
    store = RaptorQdrantStore(
        client,
        source_collection="main-v1",
        target_collection="main-v1__raptor_v1",
        embed=lambda texts: [[0.1, 0.2] for _ in texts],
        vector_size=2,
    )
    document = RaptorDocumentRef("ds", "a.pdf", 1, "hash")
    store.ensure_collection()
    leaves = store.load_document(document)
    node = RaptorNode(
        node_id="a" * 32,
        depth=1,
        title="Title",
        summary="Evidence summary",
        child_ids=("leaf-1",),
        descendant_leaf_ids=("leaf-1",),
    )
    store.publish_document(document, [node])

    assert leaves[0].point_id == "leaf-1"
    assert client.created[0]["collection_name"] == "main-v1__raptor_v1"
    assert client.deleted[0]["wait"] is True
    assert client.upserts[0]["wait"] is True
    point = client.upserts[0]["points"][0]
    assert set(point.vector) == {"dense", "bm25_sparse"}
    assert point.payload["node_role"] == "navigation"
    assert point.payload["descendant_leaf_ids"] == ("leaf-1",)


def test_store_readiness_requires_exact_dense_sparse_coverage():
    client = FakeClient()
    store = RaptorQdrantStore(
        client,
        source_collection="main-v1",
        target_collection="main-v1__raptor_v1",
        embed=lambda _texts: [],
        vector_size=2,
    )
    assert store.readiness(expected_nodes=1, source_fingerprint="fp")["ready"] is True
    client.counts["sparse"] = 0
    blocked = store.readiness(expected_nodes=1, source_fingerprint="fp")
    assert blocked["ready"] is False
    assert blocked["status"] == "blocked"


def test_store_rejects_missing_evidence_leaves():
    store = RaptorQdrantStore(
        FakeClient(),
        source_collection="main-v1",
        target_collection="main-v1__raptor_v1",
        embed=lambda _texts: [],
        vector_size=2,
    )
    with pytest.raises(RuntimeError, match="RAPTOR_EVIDENCE_LEAVES_MISSING"):
        store.load_document(RaptorDocumentRef("ds", "empty.pdf", 1))
