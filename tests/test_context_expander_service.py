from dataclasses import dataclass

from proxy.services.context_expander_service import expand_context_windows
from proxy.services.lexical_index_service import LexicalIndex


@dataclass
class Chunk:
    content: str
    doc_name: str
    score: float = 1.0
    doc_id: str = ""
    meta: dict | None = None


def test_context_expander_uses_inline_neighbor_payload(monkeypatch):
    monkeypatch.setenv("RAG_CONTEXT_WINDOW_ENABLED", "true")
    chunk = Chunk(
        "Основное требование",
        "book.pdf",
        meta={
            "context_before": "Предыдущий абзац",
            "context_after": "Следующий абзац",
            "section_heading": "Раздел 2",
        },
    )

    result = expand_context_windows([chunk], max_chars_per_chunk=500)

    assert result.expanded_count == 1
    assert result.inline_count == 1
    assert "Контекст до: Предыдущий абзац" in result.chunks[0].content
    assert "Основной фрагмент: Основное требование" in result.chunks[0].content
    assert result.chunks[0].meta["context_window_source"] == "inline_neighbors"


def test_context_expander_uses_lexical_parent_window(monkeypatch, tmp_path):
    db_path = tmp_path / "lex.db"
    monkeypatch.setenv("RAG_LEXICAL_DB_PATH", str(db_path))
    monkeypatch.setenv("RAG_CONTEXT_WINDOW_ENABLED", "true")
    index = LexicalIndex(str(db_path))
    index.upsert_chunks(
        "collection",
        [
            {
                "point_id": "p1",
                "dataset_id": "ds-book",
                "doc_id": "d1",
                "doc_name": "book.pdf",
                "text": "До таблицы",
                "content_hash": "h1",
                "chunk_ord": 1,
                "parent_id": "parent-a",
                "parent_heading": "Таблица 4",
            },
            {
                "point_id": "p2",
                "dataset_id": "ds-book",
                "doc_id": "d2",
                "doc_name": "book.pdf",
                "text": "Строка таблицы",
                "content_hash": "h2",
                "chunk_ord": 2,
                "parent_id": "parent-a",
                "parent_heading": "Таблица 4",
            },
        ],
    )

    result = expand_context_windows(
        [
            Chunk(
                "Строка таблицы",
                "book.pdf",
                meta={"dataset_id": "ds-book", "chunk_ord": 2, "parent_id": "parent-a", "content_hash": "h2"},
            )
        ],
        collection="collection",
        max_chars_per_chunk=500,
    )

    assert result.expanded_count == 1
    assert result.lexical_count == 1
    assert "Контекст до: До таблицы" in result.chunks[0].content
    assert "Основной фрагмент: Строка таблицы" in result.chunks[0].content


def test_context_expander_leaves_legacy_chunks_unchanged(monkeypatch):
    monkeypatch.setenv("RAG_CONTEXT_WINDOW_ENABLED", "true")
    chunk = Chunk("old text", "legacy.pdf", meta={})

    result = expand_context_windows([chunk], collection="collection")

    assert result.expanded_count == 0
    assert result.fallback_count == 1
    assert result.chunks[0] is chunk
