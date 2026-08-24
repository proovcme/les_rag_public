from pathlib import Path
import plistlib
from argparse import Namespace

from tools.rag_generation_supervisor import (
    _alias_target_from_payload,
    _worker_arguments,
    render_launchd_plist,
)


def test_launchd_generation_job_restarts_only_after_unsuccessful_exit(tmp_path: Path):
    payload = plistlib.loads(
        render_launchd_plist(
            label="me.ovc.les.rag-generation",
            python=Path("/runtime/python"),
            script=Path("/repo/tools/rag_generation_supervisor.py"),
            worker_args=["--src", "old", "--dst", "new"],
            workdir=tmp_path,
            log_path=tmp_path / "job.log",
        )
    )

    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    assert payload["ProgramArguments"][:3] == [
        str(Path("/runtime/python")),
        str(Path("/repo/tools/rag_generation_supervisor.py")),
        "run",
    ]
    assert payload["ProgramArguments"][-4:] == ["--src", "old", "--dst", "new"]
    assert payload["ThrottleInterval"] == 30


def test_generation_job_carries_windows_embedding_and_legacy_handoff_profile():
    args = Namespace(
        src="les_rag",
        dst="les_rag_windows_v3_b521",
        alias="les_rag",
        source_db=Path("data/les_meta.db"),
        scope_manifest=Path("artifacts/scope.json"),
        contract_path=Path("artifacts/contract.json"),
        alias_contract_path=Path("data/alias-contract.json"),
        lexical_db=Path("data/lexical.db"),
        migration_report=Path("artifacts/migration.json"),
        readiness_report=Path("artifacts/readiness.json"),
        progress_path=Path("artifacts/progress.json"),
        state_path=Path("artifacts/state.json"),
        qdrant_url="http://127.0.0.1:6333",
        embed_url="http://127.0.0.1:11434",
        max_failures=1,
        embed_backend="ollama",
        embedding_model="bge-m3",
        embedding_api_model="bge-m3:latest",
        rag_chunk_unit="chars",
        archive_physical_alias_as="les_rag_legacy_v2",
        create_destination=True,
    )

    worker = _worker_arguments(args)

    assert worker[worker.index("--scope-manifest") + 1] == "artifacts\\scope.json"
    assert worker[-11:] == [
        "--embed-backend", "ollama",
        "--embedding-model", "bge-m3",
        "--embedding-api-model", "bge-m3:latest",
        "--rag-chunk-unit", "chars",
        "--archive-physical-alias-as", "les_rag_legacy_v2",
        "--create-destination",
    ]


def test_generation_job_preserves_colbert_publication_contract():
    args = Namespace(
        src="les_rag",
        dst="les_rag_windows_v3_b521",
        alias="les_rag",
        source_db=Path("data/les_meta.db"),
        scope_manifest=Path("artifacts/scope.json"),
        contract_path=Path("artifacts/contract.json"),
        alias_contract_path=Path("data/alias-contract.json"),
        lexical_db=Path("data/lexical.db"),
        migration_report=Path("artifacts/migration.json"),
        readiness_report=Path("artifacts/readiness.json"),
        progress_path=Path("artifacts/progress.json"),
        state_path=Path("artifacts/state.json"),
        qdrant_url="http://127.0.0.1:6333",
        embed_url="http://127.0.0.1:11434",
        max_failures=1,
        embed_backend="ollama",
        embedding_model="bge-m3",
        embedding_api_model="bge-m3:latest",
        rag_chunk_unit="chars",
        archive_physical_alias_as=None,
        create_destination=False,
        with_colbert=True,
        colbert_dimension=1024,
        colbert_passage_tokens=96,
    )

    worker = _worker_arguments(args)

    assert "--with-colbert" in worker
    assert worker[worker.index("--colbert-dimension") + 1] == "1024"
    assert worker[worker.index("--colbert-passage-tokens") + 1] == "96"


def test_alias_target_resolution_supports_self_migration_guard():
    payload = {
        "result": {
            "aliases": [
                {"alias_name": "les_rag", "collection_name": "les_rag_v563"}
            ]
        }
    }

    assert _alias_target_from_payload(payload, "les_rag") == "les_rag_v563"
    assert _alias_target_from_payload(payload, "missing") == ""
