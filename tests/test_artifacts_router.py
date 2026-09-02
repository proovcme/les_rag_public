from fastapi import FastAPI
from fastapi.testclient import TestClient

from proxy.routers import artifacts
from proxy.security import require_user
from proxy.services.artifact_revision_service import ArtifactRevisionRequest, ArtifactRevisionStore


def test_authenticated_metadata_lineage_and_download(tmp_path, monkeypatch):
    source = tmp_path / "ЛСР черновик.xlsx"
    source.write_bytes(b"workbook")
    store = ArtifactRevisionStore(tmp_path / "meta.db", tmp_path / "artifacts")
    revision = store.create_revision(ArtifactRevisionRequest(
        artifact_kind="vor_workbook", file_path=source, source_scope=("dataset-1",),
        profile_revision_id="profile-1", model_identity="local-model", model_preset="qwen-9b",
        tool_calls=(), decision_checkpoint_id="checkpoint-1", missing=(), blockers=(),
        parent_revision_id=None,
    ))
    monkeypatch.setattr(artifacts, "artifact_revision_store", store)
    app = FastAPI()
    app.include_router(artifacts.router)
    app.dependency_overrides[require_user] = lambda: {"role": "user"}
    client = TestClient(app)

    metadata = client.get(f"/api/artifacts/{revision.revision_id}")
    lineage = client.get(f"/api/artifacts/{revision.artifact_id}/revisions")
    download = client.get(f"/api/artifacts/{revision.revision_id}/download")

    assert metadata.status_code == 200
    assert metadata.json()["sha256"] == revision.sha256
    assert [item["revision_no"] for item in lineage.json()["revisions"]] == [1]
    assert download.status_code == 200
    assert download.content == b"workbook"
    disposition = download.headers["content-disposition"]
    assert 'filename=".xlsx"' not in disposition
    assert "filename*=UTF-8''%D0%9B%D0%A1%D0%A0%20%D1%87%D0%B5%D1%80%D0%BD%D0%BE%D0%B2%D0%B8%D0%BA.xlsx" in disposition


def test_unknown_or_traversal_revision_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(
        artifacts, "artifact_revision_store",
        ArtifactRevisionStore(tmp_path / "meta.db", tmp_path / "artifacts"),
    )
    app = FastAPI()
    app.include_router(artifacts.router)
    app.dependency_overrides[require_user] = lambda: {"role": "user"}
    client = TestClient(app)

    assert client.get("/api/artifacts/missing").status_code == 404
    assert client.get("/api/artifacts/%2E%2E%2Fsecret/download").status_code in {400, 404}
