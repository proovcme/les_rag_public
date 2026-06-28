from dataclasses import dataclass

from qdrant_client import models

from backend.qdrant_adapter import QdrantLlamaIndexAdapter
from proxy.services.lexical_index_service import LexicalIndex, build_fts_query, merge_rrf


@dataclass
class Chunk:
    content: str
    doc_name: str
    score: float
    doc_id: str = ""
    meta: dict | None = None


def test_build_fts_query_keeps_norm_refs():
    query = build_fts_query("Какая ширина по СП 1.13130?")

    assert '"сп 1.13130"' in query


def test_lexical_index_search_returns_matching_chunks(tmp_path):
    index = LexicalIndex(str(tmp_path / "lex.db"))
    index.upsert_chunks(
        "collection",
        [
            {
                "point_id": "p1",
                "dataset_id": "ds-fire",
                "doc_id": "d1",
                "doc_name": "СП 1.13130.docx",
                "text": "Минимальная ширина путей эвакуации должна быть не менее 1,2 м.",
            },
            {
                "point_id": "p2",
                "dataset_id": "ds-other",
                "doc_id": "d2",
                "doc_name": "ГОСТ.docx",
                "text": "Требования к маркировке материалов.",
            },
        ],
    )
    index.mark_collection("collection", point_count=2, indexed_count=2)

    chunks = index.search("ширина эвакуации", collection="collection", dataset_ids=["ds-fire"], limit=5)

    assert len(chunks) == 1
    assert chunks[0].doc_name == "СП 1.13130.docx"
    assert chunks[0].meta["dataset_id"] == "ds-fire"


def test_lexical_index_delete_file_removes_only_matching_doc(tmp_path):
    index = LexicalIndex(str(tmp_path / "lex.db"))
    index.upsert_chunks(
        "collection",
        [
            {"point_id": "p1", "dataset_id": "ds", "doc_id": "d1", "doc_name": "a.pdf", "text": "котельная"},
            {"point_id": "p2", "dataset_id": "ds", "doc_id": "d2", "doc_name": "b.pdf", "text": "котельная"},
            {"point_id": "p3", "dataset_id": "other", "doc_id": "d3", "doc_name": "a.pdf", "text": "котельная"},
        ],
    )

    deleted = index.delete_file("collection", dataset_id="ds", doc_name="a.pdf")
    chunks = index.search("котельная", collection="collection", limit=10)

    assert deleted == 1
    assert {(chunk.meta["dataset_id"], chunk.doc_name) for chunk in chunks} == {
        ("ds", "b.pdf"),
        ("other", "a.pdf"),
    }


def test_qdrant_adapter_maps_points_to_lexical_rows():
    point = models.PointStruct(
        id="p1",
        vector=[0.1, 0.2],
        payload={
            "text": "PDF text",
            "dataset_id": "ds",
            "doc_id": "doc",
            "file_name": "drawing.pdf",
            "content_hash": "hash",
            "chunk_ord": 3,
            "parent_id": "parent",
            "context_kind": "pdf_page",
        },
    )

    rows = QdrantLlamaIndexAdapter._lexical_rows_from_points([point])

    assert rows == [
        {
            "point_id": "p1",
            "dataset_id": "ds",
            "doc_id": "doc",
            "doc_name": "drawing.pdf",
            "text": "PDF text",
            "content_hash": "hash",
            "chunk_ord": 3,
            "section_heading": None,
            "parent_id": "parent",
            "parent_ord": None,
            "child_ord": None,
            "parent_heading": None,
            "context_before": None,
            "context_after": None,
            "context_kind": "pdf_page",
        }
    ]


def test_rrf_merge_adds_lexical_exact_hit_and_deduplicates():
    vector = [Chunk("общий текст", "doc-a", 0.9, meta={})]
    lexical = [
        Chunk("СП 1.13130 ширина эвакуации", "СП 1.13130.docx", 0.5, meta={"content_hash": "lex"})
    ]

    merged, trace = merge_rrf(vector, lexical, question="ширина по СП 1.13130", limit=3)

    assert trace.mode == "hybrid"
    assert trace.lexical_count == 1
    assert [chunk.doc_name for chunk in merged] == ["СП 1.13130.docx", "doc-a"]


def test_lexical_index_returns_context_window_by_parent(tmp_path):
    index = LexicalIndex(str(tmp_path / "lex.db"))
    index.upsert_chunks(
        "collection",
        [
            {
                "point_id": "p1",
                "dataset_id": "ds-book",
                "doc_id": "d1",
                "doc_name": "book.pdf",
                "text": "before",
                "content_hash": "h1",
                "chunk_ord": 1,
                "parent_id": "parent-a",
                "parent_ord": 0,
                "parent_heading": "Глава 1",
                "context_kind": "markdown_window",
            },
            {
                "point_id": "p2",
                "dataset_id": "ds-book",
                "doc_id": "d2",
                "doc_name": "book.pdf",
                "text": "main",
                "content_hash": "h2",
                "chunk_ord": 2,
                "parent_id": "parent-a",
                "parent_ord": 0,
                "parent_heading": "Глава 1",
                "context_kind": "markdown_window",
            },
        ],
    )

    window = index.context_window(
        "collection",
        Chunk(
            "main",
            "book.pdf",
            1.0,
            meta={"dataset_id": "ds-book", "chunk_ord": 2, "parent_id": "parent-a", "content_hash": "h2"},
        ),
    )

    assert [chunk.content for chunk in window] == ["before", "main"]
    assert window[0].meta["parent_heading"] == "Глава 1"
