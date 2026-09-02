import json
from types import SimpleNamespace

from proxy.services import colbert_generation_service as generation


class FakeMetaDB:
    def list_datasets(self):
        return [SimpleNamespace(id="ds", module_id="", pending_files=0)]

    def dataset_integrity_rows(self, _dataset_id):
        return [
            {
                "file_name": "project.pdf",
                "status": "INDEXED",
                "chunk_count": 2,
                "file_hash": "source-hash",
            }
        ]


class FakeClient:
    def __init__(self, **_kwargs):
        pass

    def get_aliases(self):
        return SimpleNamespace(
            aliases=[SimpleNamespace(alias_name="les_rag", collection_name="les_rag_v1")]
        )


def test_colbert_generation_uses_checkpointed_sibling_and_gated_activation(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LES_RAG_ADVANCED_POLICY_PATH", str(tmp_path / "policy.json"))
    monkeypatch.setenv("LES_RAG_ADVANCED_STATUS_PATH", str(tmp_path / "status.json"))
    monkeypatch.setattr(
        generation,
        "scope_manifest_payload",
        lambda _path: {
            "schema": "les.rag.collection-scope.v1",
            "collection_role": "general_project_rag",
            "datasets": [{"id": "ds", "name": "Project"}],
            "selection_policy": {"dataset_scope": "user", "module_id": ""},
        },
    )
    monkeypatch.setattr(generation, "rag_meta_db_path", lambda: str(tmp_path / "meta.db"))
    monkeypatch.setattr(generation, "lexical_db_path", lambda: str(tmp_path / "meta.db"))
    monkeypatch.setattr(generation, "index_contract_path", lambda: tmp_path / "active-contract.json")
    monkeypatch.setattr(generation, "_background_process_kwargs", lambda: {})
    captured = {}

    class Process:
        returncode = 0

        def poll(self):
            return 0

    def popen(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        state_path = command[command.index("--state-path") + 1]
        progress_path = command[command.index("--progress-path") + 1]
        with open(state_path, "w", encoding="utf-8") as stream:
            json.dump({"status": "ready", "stage": "awaiting_activation"}, stream)
        with open(progress_path, "w", encoding="utf-8") as stream:
            json.dump(
                {
                    "datasets_total": 1,
                    "completed_datasets": [{"dataset_id": "ds"}],
                },
                stream,
            )
        return Process()

    backend = SimpleNamespace(
        qdrant_url="http://127.0.0.1:6333",
        collection_name="les_rag",
        db=FakeMetaDB(),
        embed=SimpleNamespace(
            url="http://127.0.0.1:11434/v1/embeddings",
            backend="ollama",
            model="bge-m3",
        ),
    )
    result = generation.run_colbert_generation(
        backend,
        client_factory=FakeClient,
        popen=popen,
    )

    command = captured["command"]
    assert "--with-colbert" in command
    assert "--create-destination" in command
    assert "--build-only" in command
    assert command[command.index("--src") + 1] == "les_rag"
    assert command[command.index("--dst") + 1].startswith("les_rag_colbert_")
    assert result["readiness"] == "ready"
    assert result["progress"] == 1.0
