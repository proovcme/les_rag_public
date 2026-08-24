from types import SimpleNamespace

from proxy.services.raptor_publication_service import (
    indexed_document_refs,
    run_raptor_publication,
)


class FakeMetaDB:
    def list_datasets(self):
        return [
            SimpleNamespace(id="general", module_id=""),
            SimpleNamespace(id="estimate", module_id="smeta"),
        ]

    def dataset_integrity_rows(self, dataset_id):
        return [
            {
                "file_name": f"{dataset_id}.pdf",
                "status": "INDEXED",
                "chunk_count": 2,
                "file_hash": f"hash-{dataset_id}",
            }
        ]


class FakeClient:
    def __init__(self, **_kwargs):
        self.target_points = []

    def get_aliases(self):
        return SimpleNamespace(
            aliases=[SimpleNamespace(alias_name="les_rag", collection_name="les_rag_v1")]
        )

    def collection_exists(self, _collection):
        return True

    def create_collection(self, **_kwargs):
        raise AssertionError("existing target should be reused")

    def create_payload_index(self, *_args, **_kwargs):
        return None

    def delete(self, **_kwargs):
        self.target_points = []

    def scroll(self, **kwargs):
        file_name = next(
            condition.match.value
            for condition in kwargs["scroll_filter"].must
            if getattr(condition, "key", "") == "file_name"
        )
        return [
            SimpleNamespace(id="1" * 32, payload={"text": f"{file_name} requirement one"}),
            SimpleNamespace(id="2" * 32, payload={"text": f"{file_name} requirement two"}),
        ], None

    def upsert(self, **kwargs):
        assert kwargs["wait"] is True
        self.target_points.extend(kwargs["points"])

    def count(self, _collection, *, count_filter=None, exact=True):
        assert exact is True
        return SimpleNamespace(count=len(self.target_points))


def test_document_inventory_excludes_smeta_module():
    refs = indexed_document_refs(FakeMetaDB())
    assert [(ref.dataset_id, ref.file_name) for ref in refs] == [
        ("general", "general.pdf")
    ]


def test_actual_publication_resumes_to_separate_ready_collection(monkeypatch, tmp_path):
    monkeypatch.setenv("LES_RAG_ADVANCED_POLICY_PATH", str(tmp_path / "policy.json"))
    monkeypatch.setenv("LES_RAG_ADVANCED_STATUS_PATH", str(tmp_path / "status.json"))
    client = FakeClient()
    backend = SimpleNamespace(
        qdrant_url="http://127.0.0.1:6333",
        collection_name="les_rag",
        db=FakeMetaDB(),
        vector_size=2,
        embed=SimpleNamespace(encode_sync=lambda texts: [[0.1, 0.2] for _ in texts]),
    )
    policy = {
        "fanout": 2,
        "max_depth": 3,
        "summary_backend": "extractive",
        "summary_input_chars": 1000,
        "summary_max_chars": 300,
    }

    result = run_raptor_publication(
        backend,
        client_factory=lambda **_kwargs: client,
        policy=policy,
        checkpoint_path=tmp_path / "checkpoint.json",
    )

    assert result["status"] == "completed"
    assert result["readiness"]["ready"] is True
    assert result["readiness"]["source_collection"] == "les_rag_v1"
    assert result["readiness"]["target_collection"] == "les_rag_v1__raptor_v1"
    assert all(point.payload["node_role"] == "navigation" for point in client.target_points)
