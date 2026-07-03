import sqlite3
import time

import pytest

from proxy.routers import documents as documents_router
from proxy.services.document_explorer_service import DocumentExplorer
from proxy.services.lexical_index_service import LexicalIndex, content_hash


def _seed_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        LexicalIndex.ensure_schema(conn)
        conn.execute(
            """
            CREATE TABLE datasets (
                id TEXT PRIMARY KEY,
                name TEXT,
                status TEXT,
                chunk_count INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                dataset_id TEXT,
                file_name TEXT,
                status TEXT,
                file_size INTEGER,
                chunk_count INTEGER DEFAULT 0,
                doc_type TEXT DEFAULT '',
                content_type TEXT DEFAULT '',
                domain TEXT DEFAULT '',
                source_path TEXT DEFAULT '',
                last_error TEXT DEFAULT ''
            )
            """
        )
        conn.execute(
            "INSERT INTO datasets (id, name, status, chunk_count) VALUES (?, ?, ?, ?)",
            ("fire", "NTD_FIRE_Index", "IDLE", 3),
        )
        docs = [
            ("doc-1", "fire", "NTD/СП 7.13130.docx", "INDEXED", 1000, 2, "normative", "text", "NTD_FIRE", "/src/sp7.docx"),
            ("doc-2", "fire", "NTD/СП 1.13130.docx", "INDEXED", 800, 1, "normative", "text", "NTD_FIRE", "/src/sp1.docx"),
            ("doc-3", "fire", "NTD/СП 2.13130.docx", "INDEXED", 900, 1, "normative", "text", "NTD_FIRE", "/src/sp2.docx"),
        ]
        conn.executemany(
            """
            INSERT INTO documents
                (id, dataset_id, file_name, status, file_size, chunk_count, doc_type, content_type, domain, source_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            docs,
        )
        chunks = [
            ("p1", "fire", "doc-1", "NTD/СП 7.13130.docx", "Пункт 7.2. Требуется вытяжная противодымная вентиляция для удаления дыма из коридоров.", 1),
            ("p2", "fire", "doc-1", "NTD/СП 7.13130.docx", "Пункт 7.3. Допускается не выполнять дымоудаление при пожаре в одном помещении.", 2),
            ("p3", "fire", "doc-2", "NTD/СП 1.13130.docx", "Эвакуационные пути и выходы нормируются отдельным сводом правил.", 1),
            ("p4", "fire", "lex-doc-3", "NTD/СП 2.13130.docx", "Огнестойкость строительных конструкций проверяется по проектным решениям.", 1),
        ]
        conn.executemany(
            """
            INSERT INTO lexical_chunks
                (collection, point_id, dataset_id, doc_id, doc_name, text, content_hash, chunk_ord, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("les_test", point, dataset_id, doc_id, doc_name, text, content_hash(text), ord_, time.time())
                for point, dataset_id, doc_id, doc_name, text, ord_ in chunks
            ],
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def explorer(tmp_path):
    db = tmp_path / "meta.db"
    _seed_db(db)
    return DocumentExplorer(db_path=str(db), collection="les_test")


def test_document_explorer_lists_datasets_and_documents(explorer):
    datasets = explorer.list_datasets()

    assert datasets == [
        {
            "id": "fire",
            "name": "NTD_FIRE_Index",
            "status": "IDLE",
            "chunk_count": 3,
            "document_count": 3,
            "indexed_count": 3,
            "pending_count": 0,
            "error_count": 0,
            "missing_count": 0,
        }
    ]

    docs = explorer.list_documents("fire", q="7.13130")

    assert docs["total"] == 1
    assert docs["documents"][0]["file_name"] == "NTD/СП 7.13130.docx"
    assert docs["documents"][0]["source_path"] == "/src/sp7.docx"


def test_document_explorer_searches_lexical_chunks_without_llm(explorer):
    result = explorer.search("дымоудаление", dataset_ids=["fire"])

    assert result["count"] >= 1
    assert result["hits"][0]["dataset_id"] == "fire"
    assert result["hits"][0]["doc_name"] == "NTD/СП 7.13130.docx"
    assert "дымоудал" in result["hits"][0]["snippet"].lower()


def test_document_explorer_returns_ordered_document_chunks(explorer):
    result = explorer.document_chunks("fire", "NTD/СП 7.13130.docx")

    assert result["total"] == 2
    assert [chunk["chunk_ord"] for chunk in result["chunks"]] == [1, 2]
    assert "Требуется" in result["chunks"][0]["text"]
    assert "Допускается" in result["chunks"][1]["text"]


def test_document_explorer_opens_document_and_chunks_by_id(explorer):
    document = explorer.get_document("doc-1")
    result = explorer.document_chunks_by_id("doc-1")

    assert document is not None
    assert document["file_name"] == "NTD/СП 7.13130.docx"
    assert result is not None
    assert result["document"]["id"] == "doc-1"
    assert result["total"] == 2
    assert [chunk["chunk_ord"] for chunk in result["chunks"]] == [1, 2]


def test_document_explorer_doc_id_falls_back_to_dataset_and_file_name(explorer):
    result = explorer.document_chunks_by_id("doc-3")

    assert result is not None
    assert result["total"] == 1
    assert result["warning"] == "doc_id_no_lexical_match_fallback_doc_name"
    assert result["chunks"][0]["doc_id"] == "lex-doc-3"
    assert "Огнестойкость" in result["chunks"][0]["text"]


def test_document_explorer_searches_inside_single_document(explorer):
    result = explorer.document_chunks("fire", "NTD/СП 7.13130.docx", q="допускается не выполнять")

    assert result["count"] == 1
    assert result["hits"][0]["chunk_ord"] == 2
    assert "Допускается" in result["hits"][0]["text"]


def test_document_explorer_searches_inside_document_by_id(explorer):
    result = explorer.search("дымоудаление", dataset_ids=["fire"], doc_id="doc-1")

    assert result["count"] == 1
    assert result["hits"][0]["doc_id"] == "doc-1"
    assert "дымоудал" in result["hits"][0]["snippet"].lower()


def test_document_explorer_search_by_doc_id_falls_back_to_file_name(explorer):
    result = explorer.search("огнестойкость", doc_id="doc-3")

    assert result["count"] == 1
    assert result["doc_id"] == "doc-3"
    assert result["warning"] == "doc_id_no_lexical_match_fallback_doc_name"
    assert "Огнестойкость" in result["hits"][0]["snippet"]


@pytest.mark.asyncio
async def test_documents_router_uses_explorer(monkeypatch, explorer):
    monkeypatch.setattr(documents_router, "explorer", lambda: explorer)

    found = await documents_router.document_search(
        q="дымоудаление",
        dataset_id=["fire"],
        limit=50,
        max_chars=1200,
        _user=object(),
    )
    chunks = await documents_router.document_chunks(
        dataset_id="fire",
        doc_name="NTD/СП 7.13130.docx",
        limit=80,
        offset=0,
        max_chars=4000,
        _user=object(),
    )
    by_id = await documents_router.document_chunks_by_id(
        doc_id="doc-1",
        limit=80,
        offset=0,
        max_chars=4000,
        _user=object(),
    )

    assert found["count"] >= 1
    assert chunks["total"] == 2
    assert by_id["document"]["id"] == "doc-1"
    assert by_id["total"] == 2
