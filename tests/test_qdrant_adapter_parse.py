from types import SimpleNamespace
from email.message import EmailMessage

import httpx
import pytest
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter

from backend.interface import EmbeddingContractError
import backend.qdrant_adapter as qdrant_adapter
from backend.qdrant_adapter import EmbedClient, MetaDB, QdrantLlamaIndexAdapter, _embedding_cache_fingerprint
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


class StatusTrackingDB(LegacyNamePendingDB):
    def update_document_status(self, dataset_id, file_name, status, chunk_count, route=None, last_error=""):
        self.updated.append((dataset_id, file_name, status, chunk_count, last_error))


def test_embed_client_accepts_actual_qwen_model_contract(monkeypatch):
    monkeypatch.setenv("EMBED_BACKEND", "coreml")
    client = EmbedClient("http://mlx", model="qwen3-embedding-0.6b")

    vectors = client._vectors_from_response(
        {
            "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
            "embedding_backend": "coreml",
            "data": [{"index": 0, "embedding": [0.1, 0.2]}],
        }
    )

    assert vectors == [[0.1, 0.2]]


def test_embed_client_accepts_ollama_openai_model_contract():
    client = EmbedClient("http://ollama", model="bge-m3:latest", backend="ollama")

    vectors = client._vectors_from_response(
        {
            "model": "bge-m3:latest",
            "data": [{"index": 0, "embedding": [0.1, 0.2]}],
        }
    )

    assert vectors == [[0.1, 0.2]]


def test_embed_client_retries_transient_ollama_rejection(monkeypatch):
    responses = [
        httpx.Response(400, json={"error": "temporary runner overload"}),
        httpx.Response(
            200,
            json={
                "model": "bge-m3:latest",
                "data": [{"index": 0, "embedding": [0.1, 0.2]}],
            },
        ),
    ]

    monkeypatch.setenv("RAG_EMBED_RETRY_ATTEMPTS", "2")
    monkeypatch.setenv("RAG_EMBED_RETRY_DELAY_SEC", "0")
    monkeypatch.setattr(qdrant_adapter.httpx, "post", lambda *_args, **_kwargs: responses.pop(0))
    client = EmbedClient("http://ollama", model="bge-m3:latest", backend="ollama")

    assert client.encode_sync(["фрагмент"]) == [[0.1, 0.2]]
    assert responses == []


def test_embed_client_splits_rejected_batch_and_preserves_order(monkeypatch):
    calls = []

    def _post(_url, *, json, timeout):
        calls.append(list(json["input"]))
        if len(json["input"]) > 1:
            return httpx.Response(400, json={"error": "batch rejected"})
        value = 1.0 if json["input"][0] == "первый" else 2.0
        return httpx.Response(
            200,
            json={
                "model": "bge-m3:latest",
                "data": [{"index": 0, "embedding": [value]}],
            },
        )

    monkeypatch.setenv("RAG_EMBED_RETRY_ATTEMPTS", "1")
    monkeypatch.setattr(qdrant_adapter.httpx, "post", _post)
    client = EmbedClient("http://ollama", model="bge-m3:latest", backend="ollama")

    assert client.encode_sync(["первый", "второй"]) == [[1.0], [2.0]]
    assert calls == [["первый", "второй"], ["первый"], ["второй"]]


def test_embed_client_exposes_ollama_reason_without_mdn_link(monkeypatch):
    monkeypatch.setenv("RAG_EMBED_RETRY_ATTEMPTS", "1")
    monkeypatch.setattr(
        qdrant_adapter.httpx,
        "post",
        lambda *_args, **_kwargs: httpx.Response(400, json={"error": "input is empty"}),
    )
    client = EmbedClient("http://ollama", model="bge-m3:latest", backend="ollama")

    with pytest.raises(RuntimeError, match="HTTP 400; input is empty") as error:
        client.encode_sync(["один фрагмент"])

    assert "developer.mozilla.org" not in str(error.value)


def test_embed_client_does_not_accept_openai_model_field_for_les_owned_backend():
    client = EmbedClient("http://mlx", model="bge-m3", backend="coreml")

    with pytest.raises(EmbeddingContractError, match="contract not reported"):
        client._vectors_from_response(
            {
                "model": "bge-m3",
                "data": [{"index": 0, "embedding": [0.1, 0.2]}],
            }
        )


def test_embed_client_rejects_wrong_ollama_model():
    client = EmbedClient("http://ollama", model="bge-m3:latest", backend="ollama")

    with pytest.raises(EmbeddingContractError, match="expected=bge-m3:latest, actual=nomic-embed-text"):
        client._vectors_from_response(
            {
                "model": "nomic-embed-text",
                "data": [{"index": 0, "embedding": [0.1, 0.2]}],
            }
        )


def test_embed_client_rejects_mixed_embedding_models(monkeypatch):
    monkeypatch.setenv("EMBED_BACKEND", "coreml")
    client = EmbedClient("http://mlx", model="qwen3-embedding-0.6b")

    with pytest.raises(EmbeddingContractError, match="expected=qwen3-embedding-0.6b, actual=BAAI/bge-m3"):
        client._vectors_from_response(
            {
                "embedding_model": "BAAI/bge-m3",
                "embedding_backend": "coreml",
                "data": [{"index": 0, "embedding": [0.1, 0.2]}],
            }
        )


@pytest.mark.asyncio
async def test_embed_client_applies_qwen_instruction_only_to_query(monkeypatch):
    captured = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
                "embedding_backend": "coreml",
                "data": [{"index": 0, "embedding": [0.1, 0.2]}],
            }

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, _url, *, json):
            captured.append(json["input"])
            return Response()

    monkeypatch.setenv("LES_EMBED_PROFILE", "qwen")
    monkeypatch.setenv("EMBED_BACKEND", "coreml")
    monkeypatch.setenv("RAG_QUERY_EMBEDDING_MODE", "qwen-retrieval-v1")
    monkeypatch.setattr(qdrant_adapter.httpx, "AsyncClient", Client)
    client = EmbedClient("http://mlx", model="qwen3-embedding-0.6b")

    await client.encode_async(["Какие системы есть?"], query=True)
    await client.encode_async(["Фрагмент документа"], query=False)

    assert captured[0][0].startswith("Instruct: Given a search query")
    assert captured[0][0].endswith("Query: Какие системы есть?")
    assert captured[1] == ["Фрагмент документа"]


def test_embed_client_rejects_backend_drift(monkeypatch):
    monkeypatch.setenv("EMBED_BACKEND", "coreml")
    client = EmbedClient("http://mlx", model="qwen3-embedding-0.6b")

    with pytest.raises(EmbeddingContractError, match="expected=coreml, actual=sentence_transformers"):
        client._vectors_from_response(
            {
                "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
                "embedding_backend": "sentence_transformers",
                "data": [{"index": 0, "embedding": [0.1, 0.2]}],
            }
        )


def test_embed_client_can_validate_backend_from_immutable_collection_contract():
    client = EmbedClient(
        "http://mlx",
        model="qwen3-embedding-0.6b",
        backend="coreml",
    )

    vectors = client._vectors_from_response(
        {
            "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
            "embedding_backend": "coreml",
            "data": [{"index": 0, "embedding": [0.25]}],
        }
    )

    assert vectors == [[0.25]]


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


def test_meta_db_reports_current_file_stage_for_operator_progress(tmp_path):
    db = MetaDB(str(tmp_path / "meta.sqlite"))
    dataset_id = db.create_dataset("Проект")
    db.add_document(dataset_id, "том/лист.pdf", file_size=100)
    db.add_document(dataset_id, "том/готов.pdf", file_size=200)
    db.update_document_status(dataset_id, "том/готов.pdf", "INDEXED", 12)
    db.update_document_stage(dataset_id, "том/лист.pdf", "EMBED")

    progress = db.dataset_parse_progress(dataset_id)

    assert progress == {
        "total": 2,
        "indexed": 1,
        "pending": 1,
        "errors": 0,
        "file_name": "том/лист.pdf",
        "stage": "EMBED",
    }


def test_sync_markdown_nodes_marks_spreadsheet_projection_payload(tmp_path):
    source = tmp_path / "table.csv"
    source.write_text(
        "Name,Qty,Note\n"
        "Cable,12,Огнестойкий кабель для системы пожарной сигнализации\n"
        "Tray,3,Лоток металлический с крышкой для трассировки кабельных линий\n",
        encoding="utf-8",
    )
    adapter = SimpleNamespace()
    adapter._route_payload = QdrantLlamaIndexAdapter._route_payload.__get__(adapter)

    nodes = QdrantLlamaIndexAdapter._sync_markdown_nodes(
        adapter,
        source,
        "table.csv",
        "ds-1",
        MarkdownNodeParser(),
        SentenceSplitter(chunk_size=800, chunk_overlap=120),
        None,
        {},
    )

    assert nodes
    assert {node["payload"]["type"] for node in nodes} == {"spreadsheet_projection"}


def test_sync_markdown_nodes_uses_pdf_page_nodes(tmp_path, monkeypatch):
    source = tmp_path / "project.pdf"
    source.write_bytes(b"%PDF placeholder")

    import backend.qdrant_adapter as qa

    monkeypatch.setattr(
        qa,
        "convert_to_markdown_for_indexing",
        lambda *_args, **_kwargs: "\n\n".join([
            "# PDF text projection: project.pdf",
            "## Page 1",
            "A" * 320,
            "## Page 2",
            "B" * 2600,
        ]),
    )
    monkeypatch.setenv("RAG_PDF_PAGE_NODE_MAX_CHARS", "1000")
    monkeypatch.setenv("RAG_PDF_PAGE_NODE_OVERLAP_CHARS", "50")
    adapter = SimpleNamespace()
    adapter._route_payload = QdrantLlamaIndexAdapter._route_payload.__get__(adapter)
    adapter._sync_pdf_page_text_nodes = QdrantLlamaIndexAdapter._sync_pdf_page_text_nodes.__get__(adapter)
    adapter._split_pdf_page_markdown = QdrantLlamaIndexAdapter._split_pdf_page_markdown
    adapter._split_pdf_page_text = QdrantLlamaIndexAdapter._split_pdf_page_text

    nodes = QdrantLlamaIndexAdapter._sync_markdown_nodes(
        adapter,
        source,
        "project.pdf",
        "ds-1",
        MarkdownNodeParser(),
        SentenceSplitter(chunk_size=200, chunk_overlap=20),
        None,
        {},
    )

    assert len(nodes) == 4
    assert {node["payload"]["type"] for node in nodes} == {"pdf_page_text"}
    assert nodes[0]["payload"]["page"] == 1
    assert nodes[-1]["payload"]["page"] == 2
    assert nodes[-1]["payload"]["page_parts"] == 3
    assert nodes[0]["doc_id"] == nodes[0]["doc_id"]


def test_sync_table_nodes_projects_large_row_sets(tmp_path, monkeypatch):
    source = tmp_path / "big.xlsx"
    source.write_text("placeholder", encoding="utf-8")

    class FakeNormalizer:
        def __init__(self, parquet_dir, use_llm=False):
            self.parquet_dir = parquet_dir

        async def process(self, file_path, dataset_id="", doc_type_override=None):
            parquet = tmp_path / "ds-1" / "_parquet" / "big.parquet"
            parquet.parent.mkdir(parents=True)
            parquet.write_text("parquet", encoding="utf-8")
            return {
                "parquet_path": parquet.as_posix(),
                "rows": 3,
                "sheets": 1,
                "chunks": [
                    {"text": "row 1", "metadata": {"name": "Cable", "code": "C1", "unit": "m"}},
                    {"text": "row 2", "metadata": {"name": "Tray", "code": "T1", "unit": "pcs"}},
                    {"text": "row 3", "metadata": {"name": "Panel", "code": "P1", "unit": "pcs"}},
                ],
            }

    import backend.qdrant_adapter as qa

    monkeypatch.setattr(qa, "TableNormalizer", FakeNormalizer)
    monkeypatch.setattr(qa, "TABLE_ROW_INDEX_MAX_CHUNKS", 2)
    adapter = SimpleNamespace()
    adapter._route_payload = QdrantLlamaIndexAdapter._route_payload.__get__(adapter)
    adapter._table_kind = lambda route: QdrantLlamaIndexAdapter._table_kind(route)
    adapter._table_navigation_projection_nodes = (
        QdrantLlamaIndexAdapter._table_navigation_projection_nodes.__get__(adapter)
    )

    nodes = QdrantLlamaIndexAdapter._sync_table_nodes(
        adapter,
        source,
        tmp_path / "ds-1",
        "big.xlsx",
        "ds-1",
        None,
        {},
    )

    assert len(nodes) == 1
    assert nodes[0]["payload"]["type"] == "table_navigation_projection"
    assert nodes[0]["payload"]["table_rows"] == 3
    assert "Cable" in nodes[0]["text"]


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


def test_sync_parse_marks_error_when_qdrant_count_mismatches(tmp_path, monkeypatch):
    dataset_dir = tmp_path / "ds-1"
    dataset_dir.mkdir()
    (dataset_dir / "doc.md").write_text("content with enough text for a chunk")
    db = StatusTrackingDB()
    deleted = []
    adapter = SimpleNamespace(
        content_dir=tmp_path,
        db=db,
        qdrant_url="http://127.0.0.1:6333",
        collection_name="les_rag",
        embed=SimpleNamespace(encode_sync=lambda texts: [[0.0] * 1024 for _ in texts]),
        _sync_delete_file_points=lambda _q, _ds, key: deleted.append(key),
        _sync_count_file_points=lambda *args: 0,
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

    assert result["errors"] == 1
    assert deleted == ["doc.md", "doc.md"]
    assert db.updated[-1][0:4] == ("ds-1", "doc.md", "ERROR", 0)
    assert "qdrant point count mismatch" in db.updated[-1][4]


def test_sync_parse_reuses_existing_vector_by_content_hash(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_QDRANT_SCHEMA", "named")
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
                    vector={"dense": vector},
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
    assert upserts[0].vector["dense"] == vector
    assert upserts[0].vector["bm25_sparse"].indices
    assert upserts[0].payload["embedding_fingerprint"] == _embedding_cache_fingerprint()


def test_sync_parse_skips_empty_sparse_noise_without_rejecting_pdf(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_QDRANT_SCHEMA", "named")
    dataset_dir = tmp_path / "ds-1"
    dataset_dir.mkdir()
    (dataset_dir / "doc.pdf").write_bytes(b"%PDF placeholder")
    db = LegacyNamePendingDB()
    db.get_pending_files = lambda dataset_id, limit=None: ["doc.pdf"] if not db.updated else []
    upserts = []
    embedded = []

    def encode_sync(texts):
        embedded.extend(texts)
        return [[0.25] * 1024 for _ in texts]

    adapter = SimpleNamespace(
        content_dir=tmp_path,
        db=db,
        qdrant_url="http://127.0.0.1:6333",
        collection_name="les_rag",
        embed=SimpleNamespace(encode_sync=encode_sync),
        _sync_delete_file_points=lambda *args: None,
        _sync_count_file_points=lambda *args: 1,
        _sync_markdown_nodes=lambda *args: [
            {"text": "Монтаж кабельной линии в защитной трубе", "doc_id": "valid", "payload": {}},
            {"text": "_" * 470, "doc_id": "underscores", "payload": {}},
            {"text": "+ - " * 120, "doc_id": "symbols", "payload": {}},
            {"text": "\u025a" * 240, "doc_id": "broken-font", "payload": {}},
        ],
    )

    class FakeQdrant:
        def __init__(self, url, **kwargs):
            self.url = url

        def upsert(self, collection_name, points):
            upserts.extend(points)

    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)

    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=1)

    assert result["files_parsed"] == 1
    assert result["errors"] == 0
    assert embedded == ["Монтаж кабельной линии в защитной трубе"]
    assert len(upserts) == 1
    assert upserts[0].payload["doc_id"].startswith("valid:")
    assert upserts[0].vector["bm25_sparse"].indices


def test_sync_parse_ignores_cached_vector_with_different_embedding_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_QDRANT_SCHEMA", "named")
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
                    vector={"dense": old_vector},
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
    assert upserts[0].vector["dense"] == new_vector
    assert upserts[0].vector["bm25_sparse"].indices


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


def test_mark_document_error_uses_stable_document_id(tmp_path):
    db = MetaDB(str(tmp_path / "meta.db"))
    dataset_id = db.create_dataset("RELEASE_SMOKE_Index")
    document_id, _, _ = db.add_document(dataset_id, "seed.txt", file_mtime=1.0, file_size=4)

    db.mark_document_error(dataset_id, document_id, "index contract missing")

    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT status, chunk_count, last_error FROM documents WHERE id=?",
            (document_id,),
        ).fetchone()
    assert dict(row) == {
        "status": "ERROR",
        "chunk_count": 0,
        "last_error": "index contract missing",
    }


@pytest.mark.asyncio
async def test_parse_dataset_rejects_unbounded_parse_by_default(monkeypatch):
    monkeypatch.delenv("ALLOW_UNBOUNDED_PARSE", raising=False)

    result = await QdrantLlamaIndexAdapter.parse_dataset(SimpleNamespace(), "ds-1")

    assert result["status"] == "rejected"
    assert "unbounded parse is disabled" in result["error"]


def test_adapter_uses_configured_collection_and_vector_size(monkeypatch, tmp_path):
    monkeypatch.setenv("RAG_COLLECTION_NAME", "les_rag")
    monkeypatch.setenv("RAG_VECTOR_SIZE", "1024")

    adapter = QdrantLlamaIndexAdapter(
        qdrant_url="http://127.0.0.1:6333",
        mlx_url="http://127.0.0.1:8080",
        embed_model_name="qwen3-embedding-0.6b",
        content_dir=str(tmp_path),
    )

    assert adapter.collection_name == "les_rag"
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
    assert first["node_role"] == "evidence"
    assert second["ancestor_ids"] == first["ancestor_ids"]
    assert len(nodes) == 3
    assert nodes[2]["payload"]["node_role"] == "navigation"
    assert nodes[2]["payload"]["evidence_admissible"] is False


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


def test_final_embedding_gate_applies_real_budget_to_every_node():
    nodes = [
        {
            "text": " ".join(f"слово-{index}" for index in range(70)),
            "doc_id": "source-node",
            "payload": {"type": "table_row", "table_header": "Наименование | Количество"},
        }
    ]

    finalized = QdrantLlamaIndexAdapter._finalize_embedding_nodes(
        nodes,
        chunking={"unit": "tokens", "chunk_size": 20, "chunk_overlap": 2, "len_fn": lambda text: len(text.split())},
    )

    assert len(finalized) > 1
    assert all(len(node["text"].split()) <= 20 for node in finalized)
    assert all(node["payload"]["embedding_budget_enforced"] is True for node in finalized)
    assert all(node["payload"]["embedding_chunk_unit"] == "tokens" for node in finalized)
    assert len({node["doc_id"] for node in finalized}) == len(finalized)
    assert all(node["payload"]["table_header"] == "Наименование | Количество" for node in finalized)


def test_final_embedding_gate_removes_mixed_base64_payload():
    encoded = "A" * 600
    nodes = [
        {
            "text": f"Полезный нормативный текст до вложения и описание требования. {encoded} "
            "Полезный нормативный текст после вложения и дополнительные условия применения.",
            "doc_id": "binary-node",
            "payload": {"type": "markdown"},
        }
    ]

    finalized = QdrantLlamaIndexAdapter._finalize_embedding_nodes(
        nodes,
        chunking={"unit": "chars", "chunk_size": 1000, "chunk_overlap": 0, "len_fn": None},
    )

    assert len(finalized) == 1
    assert encoded not in finalized[0]["text"]
    assert "Полезный нормативный текст" in finalized[0]["text"]
    assert finalized[0]["payload"]["content_sanitized"] is True
    assert finalized[0]["payload"]["content_quality"]["base64_runs_removed"] == 1
