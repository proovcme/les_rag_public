from types import SimpleNamespace
from email.message import EmailMessage

import pytest
from llama_index.core.node_parser import SentenceSplitter

from backend.qdrant_adapter import MetaDB, QdrantLlamaIndexAdapter, _embedding_cache_fingerprint
from backend.document_router import route_document


class EmptyPendingDB:
    def get_pending_files(self, dataset_id, limit=None):
        return []


class LegacyNamePendingDB:
    def __init__(self):
        self.updated = []

    def get_pending_files(self, dataset_id, limit=None):
        return ["doc.md"] if not self.updated else []

    def update_document_status(self, dataset_id, file_name, status, chunk_count, route=None, last_error=""):
        self.updated.append((dataset_id, file_name, status, chunk_count))

    def update_dataset_chunk_count(self, dataset_id):
        pass

    def clear_structured_rules(self, file_key):
        pass

    def insert_structured_rules(self, rules):
        pass


def test_sync_parse_does_not_parse_all_files_when_no_pending(tmp_path):
    dataset_dir = tmp_path / "ds-1"
    dataset_dir.mkdir()
    (dataset_dir / "doc.md").write_text("content")
    adapter = SimpleNamespace(
        content_dir=tmp_path,
        db=EmptyPendingDB(),
        qdrant_url="http://127.0.0.1:6333",
        collection_name="les_rag",
    )

    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=5)

    assert result == {
        "status": "completed",
        "chunks": 0,
        "files_parsed": 0,
        "files_skipped": 1,
        "remaining_pending": 0,
        "errors": 0,
        "elapsed_sec": 0,
    }


def test_sync_parse_updates_legacy_pending_file_name(tmp_path, monkeypatch):
    dataset_dir = tmp_path / "ds-1" / "nested"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "doc.md").write_text("content with enough text for a chunk")
    db = LegacyNamePendingDB()
    adapter = SimpleNamespace(
        content_dir=tmp_path,
        db=db,
        qdrant_url="http://127.0.0.1:6333",
        collection_name="les_rag",
        embed=SimpleNamespace(encode_sync=lambda texts: [[0.0] * 1024 for _ in texts]),
        _sync_delete_file_points=lambda *args: None,
        _sync_count_file_points=lambda *args: 1,
        _sync_markdown_nodes=lambda *args: [
            {"text": "content with enough text for a chunk", "doc_id": "doc-1", "payload": {}}
        ],
    )

    class FakeQdrant:
        def __init__(self, url, **kwargs):
            self.url = url

        def upsert(self, collection_name, points):
            return None

    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)

    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=1)

    assert result["files_parsed"] == 1
    assert result["remaining_pending"] == 0
    assert set(result["timings"]) == {
        "delete_sec",
        "route_sec",
        "convert_sec",
        "chunk_sec",
        "embed_sec",
        "upsert_sec",
        "count_sec",
        "cache_sec",
        "db_sec",
    }
    assert db.updated == [("ds-1", "doc.md", "INDEXED", 1)]


def test_sync_parse_prefers_exact_relative_path_over_legacy_basename(tmp_path, monkeypatch):
    dataset_dir = tmp_path / "ds-1"
    nested_dir = dataset_dir / "nested"
    nested_dir.mkdir(parents=True)
    (dataset_dir / "doc.md").write_text("root content with enough text for a chunk")
    (nested_dir / "doc.md").write_text("nested content with enough text for a chunk")
    db = LegacyNamePendingDB()
    parsed = []
    adapter = SimpleNamespace(
        content_dir=tmp_path,
        db=db,
        qdrant_url="http://127.0.0.1:6333",
        collection_name="les_rag",
        embed=SimpleNamespace(encode_sync=lambda texts: [[0.0] * 1024 for _ in texts]),
        _sync_delete_file_points=lambda *args: None,
        _sync_count_file_points=lambda *args: 1,
        _sync_markdown_nodes=lambda file_path, *args: parsed.append(
            file_path.relative_to(dataset_dir).as_posix()
        )
        or [{"text": "content with enough text for a chunk", "doc_id": "doc-1", "payload": {}}],
    )

    class FakeQdrant:
        def __init__(self, url, **kwargs):
            self.url = url

        def upsert(self, collection_name, points):
            return None

    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)

    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=1)

    assert result["files_parsed"] == 1
    assert result["files_skipped"] == 1
    assert parsed == ["doc.md"]
    assert db.updated == [("ds-1", "doc.md", "INDEXED", 1)]


def test_sync_parse_reuses_existing_vector_by_content_hash(tmp_path, monkeypatch):
    text = "content with enough text for a chunk"
    dataset_dir = tmp_path / "ds-1"
    dataset_dir.mkdir()
    (dataset_dir / "doc.md").write_text(text)
    db = LegacyNamePendingDB()
    vector = [0.25] * 1024
    embedded = {"calls": 0}
    upserts = []

    adapter = SimpleNamespace(
        content_dir=tmp_path,
        db=db,
        qdrant_url="http://127.0.0.1:6333",
        collection_name="les_rag",
        embed=SimpleNamespace(
            encode_sync=lambda texts: embedded.__setitem__("calls", embedded["calls"] + 1) or []
        ),
        _sync_delete_file_points=lambda *args: None,
        _sync_count_file_points=lambda *args: 1,
        _sync_markdown_nodes=lambda *args: [
            {"text": text, "doc_id": "doc-1", "payload": {}}
        ],
    )
    adapter._file_filter = QdrantLlamaIndexAdapter._file_filter.__get__(adapter)
    adapter._extract_point_vector = QdrantLlamaIndexAdapter._extract_point_vector
    adapter._sync_existing_file_vectors_by_hash = (
        QdrantLlamaIndexAdapter._sync_existing_file_vectors_by_hash.__get__(adapter)
    )

    class FakeQdrant:
        def __init__(self, url, **kwargs):
            self.url = url

        def scroll(self, **kwargs):
            return [
                SimpleNamespace(
                    payload={"text": text, "embedding_fingerprint": _embedding_cache_fingerprint()},
                    vector=vector,
                )
            ], None

        def upsert(self, collection_name, points):
            upserts.extend(points)

    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)

    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=1)

    assert result["files_parsed"] == 1
    assert result["embedding_cache_hits"] == 1
    assert result["embedded_chunks"] == 0
    assert embedded["calls"] == 0
    assert upserts[0].vector == vector
    assert upserts[0].payload["embedding_fingerprint"] == _embedding_cache_fingerprint()


def test_sync_parse_ignores_cached_vector_with_different_embedding_fingerprint(tmp_path, monkeypatch):
    text = "content with enough text for a chunk"
    dataset_dir = tmp_path / "ds-1"
    dataset_dir.mkdir()
    (dataset_dir / "doc.md").write_text(text)
    db = LegacyNamePendingDB()
    old_vector = [0.25] * 1024
    new_vector = [0.5] * 1024
    embedded = {"calls": 0}
    upserts = []

    def encode_sync(texts):
        embedded["calls"] += 1
        return [new_vector for _ in texts]

    adapter = SimpleNamespace(
        content_dir=tmp_path,
        db=db,
        qdrant_url="http://127.0.0.1:6333",
        collection_name="les_rag",
        embed=SimpleNamespace(encode_sync=encode_sync),
        _sync_delete_file_points=lambda *args: None,
        _sync_count_file_points=lambda *args: 1,
        _sync_markdown_nodes=lambda *args: [
            {"text": text, "doc_id": "doc-1", "payload": {}}
        ],
    )
    adapter._file_filter = QdrantLlamaIndexAdapter._file_filter.__get__(adapter)
    adapter._extract_point_vector = QdrantLlamaIndexAdapter._extract_point_vector
    adapter._sync_existing_file_vectors_by_hash = (
        QdrantLlamaIndexAdapter._sync_existing_file_vectors_by_hash.__get__(adapter)
    )

    class FakeQdrant:
        def __init__(self, url, **kwargs):
            self.url = url

        def scroll(self, **kwargs):
            return [
                SimpleNamespace(
                    payload={"text": text, "embedding_fingerprint": "old-fingerprint"},
                    vector=old_vector,
                )
            ], None

        def upsert(self, collection_name, points):
            upserts.extend(points)

    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)

    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=1)

    assert result["files_parsed"] == 1
    assert result["embedding_cache_hits"] == 0
    assert result["embedded_chunks"] == 1
    assert embedded["calls"] == 1
    assert upserts[0].vector == new_vector


def test_pending_files_are_ordered_by_size(tmp_path):
    db = MetaDB(str(tmp_path / "meta.db"))
    dataset_id = db.create_dataset("NTD_Index")
    large = tmp_path / "large.md"
    small = tmp_path / "small.md"
    large.write_text("x" * 100)
    small.write_text("x" * 10)

    db.add_document(dataset_id, "large.md", file_mtime=1, file_size=large.stat().st_size)
    db.add_document(dataset_id, "small.md", file_mtime=1, file_size=small.stat().st_size)

    assert db.get_pending_files(dataset_id, limit=2) == ["small.md", "large.md"]


def test_dataset_group_set_and_listed(tmp_path):
    db = MetaDB(str(tmp_path / "meta.db"))
    ds = db.create_dataset("W-205")
    [d0] = db.list_datasets()
    assert d0.group_name == ""  # дефолт — без группы
    db.set_dataset_group(ds, "Проект W-205")
    [d1] = db.list_datasets()
    assert d1.group_name == "Проект W-205"
    db.set_dataset_group(ds, "")  # снятие группы
    [d2] = db.list_datasets()
    assert d2.group_name == ""


def test_recover_interrupted_parsing_resets_dataset_status(tmp_path):
    db = MetaDB(str(tmp_path / "meta.db"))
    dataset_id = db.create_dataset("BOOKS_Index")
    db.update_dataset_status(dataset_id, "PARSING")

    assert db.recover_interrupted_parsing() == 1

    [dataset] = db.list_datasets()
    assert dataset.status == "IDLE"


@pytest.mark.asyncio
async def test_parse_dataset_rejects_unbounded_parse_by_default(monkeypatch):
    monkeypatch.delenv("ALLOW_UNBOUNDED_PARSE", raising=False)

    result = await QdrantLlamaIndexAdapter.parse_dataset(SimpleNamespace(), "ds-1")

    assert result["status"] == "rejected"
    assert "unbounded parse is disabled" in result["error"]


def test_adapter_uses_configured_collection_and_vector_size(monkeypatch, tmp_path):
    monkeypatch.setenv("RAG_COLLECTION_NAME", "les_rag_qwen3_06b")
    monkeypatch.setenv("RAG_VECTOR_SIZE", "1024")

    adapter = QdrantLlamaIndexAdapter(
        qdrant_url="http://127.0.0.1:6333",
        mlx_url="http://127.0.0.1:8080",
        embed_model_name="qwen3-embedding-0.6b",
        content_dir=str(tmp_path),
    )

    assert adapter.collection_name == "les_rag_qwen3_06b"
    assert adapter.vector_size == 1024
    assert adapter.embed.model == "qwen3-embedding-0.6b"


def test_adapter_adds_parent_and_neighbor_context_metadata():
    adapter = QdrantLlamaIndexAdapter.__new__(QdrantLlamaIndexAdapter)
    nodes = [
        {"text": "## Глава 1\nПервый фрагмент про таблицу.", "payload": {"type": "markdown"}},
        {"text": "Второй фрагмент с продолжением.", "payload": {"type": "markdown"}},
    ]

    adapter._apply_context_metadata(nodes, "ds-1", "book.pdf")

    first = nodes[0]["payload"]
    second = nodes[1]["payload"]
    assert first["chunk_ord"] == 0
    assert first["parent_id"] == second["parent_id"]
    assert first["context_after"] == "Второй фрагмент с продолжением."
    assert second["context_before"].startswith("## Глава 1")
    assert first["context_kind"] == "markdown_window"


def test_adapter_builds_mail_profile_nodes_with_attachment_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_ATTACHMENT_OCR_ENABLED", "false")
    data_dir = tmp_path / "ds-1"
    data_dir.mkdir()
    msg = EmailMessage()
    msg["Subject"] = "Важное письмо с картинкой"
    msg["From"] = "Alice <alice@example.com>"
    msg["To"] = "Bob <bob@example.com>"
    msg["Message-ID"] = "<mail-image@example.com>"
    msg["Importance"] = "high"
    msg.set_content("На картинке замечание по узлу.")
    msg.add_attachment(b"image-bytes", maintype="image", subtype="png", filename="remark.png")
    path = data_dir / "letter.eml"
    path.write_bytes(msg.as_bytes())

    adapter = QdrantLlamaIndexAdapter.__new__(QdrantLlamaIndexAdapter)
    route = route_document(path)
    nodes = adapter._sync_mail_nodes(
        path,
        data_dir,
        "letter.eml",
        "ds-1",
        SentenceSplitter(chunk_size=1400, chunk_overlap=100),
        route,
    )

    payloads = [node["payload"] for node in nodes]
    assert {payload["type"] for payload in payloads} == {"mail_message", "mail_attachment"}
    message_payload = next(payload for payload in payloads if payload["type"] == "mail_message")
    attachment_payload = next(payload for payload in payloads if payload["type"] == "mail_attachment")
    assert message_payload["mail_importance"] == "high"
    assert message_payload["mail_from"] == "Alice <alice@example.com>"
    assert message_payload["mail_to"] == ["Bob <bob@example.com>"]
    assert message_payload["mail_thread_key"].startswith("msg_")
    assert attachment_payload["mail_attachment_filename"] == "remark.png"
    assert attachment_payload["mail_attachment_needs_ocr"] is True
    assert attachment_payload["mail_attachment_needs_vlm"] is True
    assert any("требует OCR/VLM" in node["text"] for node in nodes)
