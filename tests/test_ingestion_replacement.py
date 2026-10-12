"""Replacement regressions use real disposable SQLite and in-memory Qdrant."""
from __future__ import annotations

import sqlite3
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from qdrant_client import QdrantClient, models

import backend.qdrant_adapter as qa
from proxy.services.lexical_index_service import LexicalIndex


def rule(identity, dataset, file="spec.md"):
    return dict(id=identity, document_id=dataset, file_key=file, chunk_id="chunk",
                subject="wall", parameter="height", operator=">=", value=3.0, unit="m",
                condition="", char_start=0, char_end=12)


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "meta.db"))
    monkeypatch.setenv("RAG_LEXICAL_DB_PATH", str(tmp_path / "meta.db"))
    monkeypatch.setattr(qa, "PARSE_PREFETCH", False)
    monkeypatch.setattr(qa, "CHUNK_HASH_CACHE", False)
    db = qa.MetaDB(str(tmp_path / "meta.db"))
    ds = db.create_dataset("disposable test corpus")
    other_ds = db.create_dataset("other test corpus")
    content = tmp_path / "content"
    (content / ds).mkdir(parents=True)
    (content / ds / "spec.md").write_text("new ventilation source evidence", encoding="utf-8")
    db.add_document(ds, "spec.md")
    db.insert_structured_rules([rule("accepted-rule", ds), rule("unrelated-rule", other_ds)])
    client = QdrantClient(":memory:")
    client.create_collection("test", vectors_config={"dense": models.VectorParams(
        size=8, distance=models.Distance.COSINE)},
        sparse_vectors_config={"bm25_sparse": models.SparseVectorParams()})
    old, unrelated = str(uuid.uuid4()), str(uuid.uuid4())
    points = [models.PointStruct(id=pid, vector={"dense": [0.1] * 8,
        "bm25_sparse": models.SparseVector(indices=[1], values=[1.0])},
        payload={"text": text, "dataset_id": dataset, "file_name": "spec.md"})
        for pid, dataset, text in [(old, ds, "accepted old source evidence"),
                                   (unrelated, other_ds, "unrelated source evidence")]]
    client.upsert("test", points=points, wait=True)
    lexical = LexicalIndex(str(tmp_path / "meta.db"))
    lexical.upsert_chunks("test", qa.QdrantLlamaIndexAdapter._lexical_rows_from_points(points))
    adapter = object.__new__(qa.QdrantLlamaIndexAdapter)
    adapter.content_dir, adapter.db = content, db
    adapter.qdrant_url, adapter.collection_name = "http://disposable.invalid", "test"
    adapter.embed = SimpleNamespace(encode_sync=lambda texts: [[0.1] * 8 for _ in texts])
    route = qa.DocumentRoute("general", "test", "DOCUMENT", "text", "simple", "markdown", {})
    monkeypatch.setattr(qa.QdrantLlamaIndexAdapter, "_convert_file", lambda *a, **k: (route, [
        {"text": "new ventilation source evidence", "doc_id": "new-doc", "payload": {}}
    ]))
    monkeypatch.setattr(qa.qdrant_client, "QdrantClient", lambda **k: client)
    yield SimpleNamespace(adapter=adapter, db=db, ds=ds, other_ds=other_ds, client=client,
                          old=old, unrelated=unrelated, lexical=lexical, root=tmp_path)
    client.close()


def current_ids(c):
    return {str(p.id) for p in c.client.scroll("test", limit=1000)[0]}


def lexical_ids(c):
    with c.lexical.connect() as conn:
        return {row[0] for row in conn.execute("SELECT point_id FROM lexical_chunks WHERE collection='test'")}


@pytest.mark.parametrize("failure", ["convert", "empty", "embed", "upsert", "lexical", "rules"])
def test_failed_replacement_keeps_accepted_evidence(corpus, monkeypatch, failure):
    c = corpus
    def fail(*a, **k):
        raise RuntimeError("controlled replacement failure")
    if failure == "convert":
        monkeypatch.setattr(qa.QdrantLlamaIndexAdapter, "_convert_file", fail)
    elif failure == "empty":
        monkeypatch.setattr(qa.QdrantLlamaIndexAdapter, "_convert_file", lambda *a, **k: (None, []))
    elif failure == "embed":
        c.adapter.embed.encode_sync = fail
    elif failure == "upsert":
        monkeypatch.setattr(c.client, "upsert", fail)
    elif failure == "lexical":
        monkeypatch.setattr(LexicalIndex, "upsert_chunks", fail)
    else:
        monkeypatch.setattr(c.db, "replace_structured_rules", fail)
    result = c.adapter._sync_parse(c.ds, limit=1)
    assert result["errors"] == 1
    assert {c.old, c.unrelated} <= current_ids(c)
    assert {c.old, c.unrelated} <= lexical_ids(c)
    assert {r["id"] for r in c.db.get_structured_rules()} == {"accepted-rule", "unrelated-rule"}


def test_success_retires_exact_ids_after_new_evidence_is_written(corpus, monkeypatch):
    c = corpus
    delete = c.client.delete
    retirements = []
    def inspect_delete(*args, **kwargs):
        selector = kwargs["points_selector"]
        assert isinstance(selector, models.PointIdsList), "replacement must not use a file-wide filter"
        ids = current_ids(c)
        assert {c.old, c.unrelated} <= ids
        assert ids - {c.old, c.unrelated}, "new Qdrant evidence must exist before retirement"
        assert lexical_ids(c) - {c.old, c.unrelated}, "new lexical evidence must exist before retirement"
        retirements.extend(selector.points)
        return delete(*args, **kwargs)
    monkeypatch.setattr(c.client, "delete", inspect_delete)
    result = c.adapter._sync_parse(c.ds, limit=1)
    assert result["errors"] == 0
    assert retirements == [c.old]
    assert c.old not in current_ids(c) | lexical_ids(c)
    assert c.unrelated in current_ids(c) & lexical_ids(c)
    assert {r["id"] for r in c.db.get_structured_rules()} == {"unrelated-rule"}


def test_structured_rules_replace_is_owner_scoped_and_atomic(corpus):
    c = corpus
    broken = rule("new-rule", c.ds)
    del broken["subject"]
    with pytest.raises(sqlite3.ProgrammingError):
        c.db.replace_structured_rules(c.ds, "spec.md", [broken])
    assert {r["id"] for r in c.db.get_structured_rules()} == {"accepted-rule", "unrelated-rule"}
    with pytest.raises(ValueError):
        c.db.replace_structured_rules(c.ds, "spec.md", [rule("bad-owner", c.other_ds)])
    c.db.replace_structured_rules(c.ds, "spec.md", [rule("new-rule", c.ds)])
    assert {r["id"] for r in c.db.get_structured_rules()} == {"new-rule", "unrelated-rule"}


def test_lexical_retirement_is_scoped_batched_and_atomic(tmp_path):
    index = LexicalIndex(str(tmp_path / "lexical.db"))
    rows = [{"point_id": str(i), "text": "searchable evidence"} for i in range(600)]
    index.upsert_chunks("target", rows)
    index.upsert_chunks("other", rows[:1])
    with index.connect() as conn:
        conn.execute("""CREATE TRIGGER fail_retire BEFORE DELETE ON lexical_chunks
            WHEN old.point_id='599' BEGIN SELECT RAISE(ABORT, 'controlled failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        index.delete_point_ids("target", [row["point_id"] for row in rows])
    with index.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM lexical_chunks").fetchone()[0] == 601
        conn.execute("DROP TRIGGER fail_retire")
    assert index.delete_point_ids("target", [row["point_id"] for row in rows]) == 600
    with index.connect() as conn:
        assert [tuple(row) for row in conn.execute("SELECT collection,point_id FROM lexical_chunks")] == [("other", "0")]


def test_two_parse_windows_cannot_capture_the_same_old_generation(corpus, monkeypatch):
    c = corpus
    first_upsert = threading.Event()
    release_first = threading.Event()
    second_attempt = threading.Event()
    events = []
    upsert, scroll, delete = c.client.upsert, c.client.scroll, c.client.delete
    real_lock = qa.file_ingestion_lock

    @contextmanager
    def observed_lock(*args, **kwargs):
        if first_upsert.is_set():
            second_attempt.set()
        with real_lock(*args, **kwargs) as path:
            yield path

    def capture(**kwargs):
        result = scroll(**kwargs)
        events.append(("capture", {str(point.id) for point in result[0]}))
        return result

    def pause_upsert(*args, **kwargs):
        if not first_upsert.is_set():
            first_upsert.set()
            assert release_first.wait(5), "test controller did not release first write"
        return upsert(*args, **kwargs)

    def retire(*args, **kwargs):
        result = delete(*args, **kwargs)
        events.append(("retire", set(kwargs["points_selector"].points)))
        return result

    monkeypatch.setattr(qa, "file_ingestion_lock", observed_lock)
    monkeypatch.setattr(c.client, "scroll", capture)
    monkeypatch.setattr(c.client, "upsert", pause_upsert)
    monkeypatch.setattr(c.client, "delete", retire)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(c.adapter._sync_parse, c.ds, 1)
        assert first_upsert.wait(5)
        second = pool.submit(c.adapter._sync_parse, c.ds, 1)
        try:
            assert second_attempt.wait(5)
            assert [event[0] for event in events] == ["capture"]
        finally:
            release_first.set()
        assert first.result(timeout=10)["errors"] == 0
        assert second.result(timeout=10)["errors"] == 0
    assert [event[0] for event in events] == ["capture", "retire", "capture", "retire"]
    assert events[0][1] == {c.old}
    assert c.old not in events[2][1]
    assert len(events[2][1]) == 1
    assert c.client.count("test", count_filter=c.adapter._file_filter(c.ds, "spec.md")).count == 1


def test_rule_id_collision_cannot_replace_another_owner(corpus):
    c = corpus
    with pytest.raises(sqlite3.IntegrityError):
        c.db.replace_structured_rules(c.ds, "spec.md", [rule("unrelated-rule", c.ds)])
    assert {r["id"] for r in c.db.get_structured_rules()} == {"accepted-rule", "unrelated-rule"}


def test_normative_replacement_extracts_rules_only_from_evidence(corpus, monkeypatch):
    c = corpus
    route = qa.DocumentRoute("general", "test", "NORMATIVE", "text", "simple", "markdown", {})
    monkeypatch.setattr(qa.QdrantLlamaIndexAdapter, "_convert_file", lambda *a, **k: (route, [
        {"text": "## Requirements\n\nWall height must be at least three metres.",
         "doc_id": "page", "payload": {}}
    ]))
    from backend.rules_extractor import StructuredRulesExtractor
    seen = []
    def extract(self, *, text, document_id, file_key, chunk_id):
        seen.append(text)
        return [rule("new-rule", document_id, file_key)]
    monkeypatch.setattr(StructuredRulesExtractor, "extract_rules", extract)
    result = c.adapter._sync_parse(c.ds, limit=1)
    assert result["errors"] == 0
    assert len(seen) == 1
    assert "three metres" in seen[0]
    assert {r["id"] for r in c.db.get_structured_rules()} == {"new-rule", "unrelated-rule"}


def test_old_id_census_scrolls_pages_and_deletes_bounded_batches(corpus):
    c = corpus
    c.client.upsert("test", points=[models.PointStruct(
        id=i, vector={"dense": [0.1] * 8},
        payload={"dataset_id": c.ds, "file_name": "bulk.md"}
    ) for i in range(600)])
    ids = c.adapter._sync_file_point_ids(c.client, c.ds, "bulk.md")
    assert set(ids) == set(range(600))
    c.adapter._sync_delete_point_ids(c.client, ids)
    assert current_ids(c) == {c.old, c.unrelated}
