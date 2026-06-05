from proxy.services.clause_lookup_service import maybe_answer_clause_lookup
from proxy.services.lexical_index_service import LexicalIndex


def test_clause_lookup_extracts_numbered_clause(tmp_path, monkeypatch):
    db_path = tmp_path / "lexical.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    monkeypatch.setenv("RAG_HYBRID_RETRIEVAL_ENABLED", "true")

    index = LexicalIndex(str(db_path))
    index.upsert_chunks(
        "test_collection",
        [
            {
                "point_id": "p1",
                "dataset_id": "ds-fire",
                "doc_id": "node-1",
                "doc_name": "NTD/СП 7.13130.docx",
                "text": "7\\.2 Предыдущий пункт.\n\n7\\.3 Требования пункта 7.2 не распространяются:\n\nа) на помещения до 200 м2;",
                "chunk_ord": 10,
                "content_hash": "h1",
            },
            {
                "point_id": "p2",
                "dataset_id": "ds-fire",
                "doc_id": "node-2",
                "doc_name": "NTD/СП 7.13130.docx",
                "text": "б) на помещения с газовым пожаротушением;\n\nв) на коридоры с непосредственным удалением продуктов горения;",
                "chunk_ord": 11,
                "content_hash": "h2",
            },
            {
                "point_id": "p3",
                "dataset_id": "ds-fire",
                "doc_id": "node-3",
                "doc_name": "NTD/СП 7.13130.docx",
                "text": "7\\.4 Следующий пункт.",
                "chunk_ord": 12,
                "content_hash": "h3",
            },
        ],
    )

    result = maybe_answer_clause_lookup(
        "Найди пункт 7.3 в СП 7.13130",
        collection="test_collection",
        dataset_ids=["ds-fire"],
    )

    assert result is not None
    assert result.sources == ["NTD/СП 7.13130.docx"]
    assert "Пункт 7.3 СП 7.13130" in result.answer
    assert "а) на помещения до 200 м2" in result.answer
    assert "б) на помещения с газовым пожаротушением" in result.answer
    assert "7.4 Следующий пункт" not in result.answer
    assert result.payload()["operation"] == "clause_lookup"


def test_clause_lookup_maps_smoke_control_exceptions_to_sp7_clause(tmp_path, monkeypatch):
    db_path = tmp_path / "lexical.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    monkeypatch.setenv("RAG_HYBRID_RETRIEVAL_ENABLED", "true")

    index = LexicalIndex(str(db_path))
    index.upsert_chunks(
        "test_collection",
        [
            {
                "point_id": "p1",
                "dataset_id": "ds-fire",
                "doc_id": "node-1",
                "doc_name": "NTD/СП 7.13130.docx",
                "text": "7\\.3 Требования пункта 7.2 не распространяются:\n\nа) на помещения до 200 м2;",
                "chunk_ord": 3,
                "content_hash": "h1",
            },
            {
                "point_id": "p2",
                "dataset_id": "ds-fire",
                "doc_id": "node-2",
                "doc_name": "NTD/СП 7.13130.docx",
                "text": "7\\.4 Следующий пункт.",
                "chunk_ord": 4,
                "content_hash": "h2",
            },
        ],
    )

    result = maybe_answer_clause_lookup(
        "В каких случаях допускается не выполнять систему дымоудаления",
        collection="test_collection",
        dataset_ids=["ds-fire"],
    )

    assert result is not None
    assert result.clause == "7.3"
    assert result.norm_ref == "сп 7.13130"
    assert "а) на помещения до 200 м2" in result.answer
