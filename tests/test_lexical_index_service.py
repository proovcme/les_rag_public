from dataclasses import dataclass

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
