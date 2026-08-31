from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pytest

from proxy.services import dataset_deletion_service as service


class _Response:
    def __init__(self, payload: dict, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code
        self.request = httpx.Request("POST", "http://qdrant.test")

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "failure",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


class _Client:
    def __init__(self, *, fail_delete: bool = False):
        self.fail_delete = fail_delete
        self.count_calls = 0
        self.snapshot_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url: str, **_kwargs):
        if url.endswith("/snapshots"):
            self.snapshot_calls += 1
            return _Response({"status": "ok", "result": {"name": "before.snapshot"}})
        if url.endswith("/points/count"):
            self.count_calls += 1
            count = 3 if self.count_calls == 1 else 0
            return _Response({"status": "ok", "result": {"count": count}})
        if url.endswith("/points/delete"):
            if self.fail_delete:
                return _Response({"status": "error"}, status_code=500)
            return _Response({"status": "ok", "result": {"status": "completed"}})
        raise AssertionError(url)


class _Lexical:
    def delete_dataset(self, _collection: str, *, dataset_id: str) -> int:
        assert dataset_id == "ds-1"
        return 3


def _db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE datasets (id TEXT PRIMARY KEY, name TEXT);
            CREATE TABLE documents (id TEXT PRIMARY KEY, dataset_id TEXT, file_name TEXT);
            CREATE TABLE les_project_links (id INTEGER PRIMARY KEY, kind TEXT, ref TEXT);
            INSERT INTO datasets VALUES ('ds-1', 'Project');
            INSERT INTO documents VALUES ('doc-1', 'ds-1', 'a.pdf');
            INSERT INTO les_project_links(kind, ref) VALUES ('dataset', 'ds-1');
            """
        )


@pytest.mark.asyncio
async def test_safe_delete_requires_verified_qdrant_and_keeps_catalog_on_failure(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "meta.db"
    db_path.parent.mkdir()
    _db(db_path)
    storage = tmp_path / "storage" / "ds-1"
    storage.mkdir(parents=True)
    (storage / "a.pdf").write_text("source", encoding="utf-8")
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **_kwargs: _Client(fail_delete=True))

    with pytest.raises(service.DatasetDeletionError, match="not proven"):
        await service.delete_datasets_safely(
            dataset_ids=["ds-1"],
            qdrant_url="http://qdrant.test",
            collection="les_rag",
            meta_db_path=db_path,
            storage_root=tmp_path / "storage",
            lexical_index=_Lexical(),
        )

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    assert storage.is_dir()
    backups = list((tmp_path / "recovery" / "dataset-deletions").glob("*/meta.db"))
    assert len(backups) == 1


@pytest.mark.asyncio
async def test_safe_delete_snapshots_verifies_and_quarantines_storage(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "meta.db"
    db_path.parent.mkdir()
    _db(db_path)
    storage = tmp_path / "storage" / "ds-1"
    storage.mkdir(parents=True)
    (storage / "a.pdf").write_text("source", encoding="utf-8")
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **_kwargs: _Client())

    result = await service.delete_datasets_safely(
        dataset_ids=["ds-1"],
        qdrant_url="http://qdrant.test",
        collection="les_rag",
        meta_db_path=db_path,
        storage_root=tmp_path / "storage",
        lexical_index=_Lexical(),
    )

    assert result["points_before"] == 3
    assert result["points_after"] == 0
    assert result["recovery"]["qdrant_snapshot"]["name"] == "before.snapshot"
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM les_project_links").fetchone()[0] == 0
    assert not storage.exists()
    quarantined = Path(result["recovery"]["storage"][0])
    assert (quarantined / "a.pdf").read_text(encoding="utf-8") == "source"


@pytest.mark.asyncio
async def test_release_acceptance_delete_skips_full_snapshot_only_for_exact_fixture(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "data" / "meta.db"
    db_path.parent.mkdir()
    _db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE datasets SET name=? WHERE id='ds-1'",
            ("LES acceptance " + "a" * 32,),
        )
        conn.execute(
            "UPDATE documents SET file_name='release-acceptance.txt' WHERE id='doc-1'"
        )
    storage = tmp_path / "storage" / "ds-1"
    storage.mkdir(parents=True)
    (storage / "release-acceptance.txt").write_text("fixture", encoding="utf-8")
    client = _Client()
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **_kwargs: client)

    result = await service.delete_datasets_safely(
        dataset_ids=["ds-1"],
        qdrant_url="http://qdrant.test",
        collection="les_rag",
        meta_db_path=db_path,
        storage_root=tmp_path / "storage",
        lexical_index=_Lexical(),
        recovery_policy="release_acceptance_ephemeral",
    )

    assert client.snapshot_calls == 0
    assert result["recovery"] == {"policy": "release_acceptance_ephemeral"}
    assert not storage.exists()


@pytest.mark.asyncio
async def test_release_acceptance_delete_rejects_a_normal_dataset(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "meta.db"
    db_path.parent.mkdir()
    _db(db_path)
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **_kwargs: _Client())

    with pytest.raises(service.DatasetDeletionError, match="release acceptance fixture"):
        await service.delete_datasets_safely(
            dataset_ids=["ds-1"],
            qdrant_url="http://qdrant.test",
            collection="les_rag",
            meta_db_path=db_path,
            storage_root=tmp_path / "storage",
            lexical_index=_Lexical(),
            recovery_policy="release_acceptance_ephemeral",
        )
