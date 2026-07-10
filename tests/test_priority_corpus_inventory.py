from tools.priority_corpus_inventory import (
    build_priority_inventory,
    build_quality_card,
    fetch_documents,
    render_markdown,
)


def _contour(dataset_id: str = "ds-1") -> dict[str, str]:
    return {"label": "ПД ИЦ", "dataset_id": dataset_id, "purpose": "проектный корпус"}


def _notebook() -> dict:
    return {
        "name": "ПД ИЦ",
        "profile": {"quality": {"status": "good"}},
        "typed_memory": {
            "revision_id": "rev-1",
            "reader_status": "model",
            "topic_map": {"topics": []},
            "section_map": {"files": []},
        },
    }


def test_quality_card_is_navigation_only_and_never_auto_quarantines():
    card = build_quality_card(
        _contour(),
        health_dataset={"name": "ПД ИЦ", "status": "IDLE"},
        notebook=_notebook(),
        documents=[
            {"file_name": "01.pdf", "status": "INDEXED", "chunk_count": 4, "doc_type": "DOCUMENT", "content_type": "text", "domain": "DOCS_OTHER", "source_path": "/src/01.pdf"},
            {"file_name": "02.pdf", "status": "PENDING", "chunk_count": 0, "doc_type": "DOCUMENT", "content_type": "", "domain": "DOCS_OTHER", "source_path": "/src/02.pdf"},
            {"file_name": "03.pdf", "status": "ERROR", "chunk_count": 0, "doc_type": "DOCUMENT", "content_type": "", "domain": "DOCS_OTHER", "source_path": "/src/03.pdf"},
        ],
    )

    assert card["context_role"] == "navigation"
    assert card["is_evidence"] is False
    assert card["dataset"]["source_revision_id"] == "rev-1"
    assert card["documents"]["status_counts"] == {"ERROR": 1, "INDEXED": 1, "PENDING": 1}
    assert card["disposition"]["status"] == "review_errors"
    assert card["disposition"]["automatic_quarantine"] is False
    assert card["observations"]["pending"][0]["file_name"] == "02.pdf"


def test_quality_card_flags_indexed_without_declared_chunks_for_review():
    card = build_quality_card(
        _contour(),
        health_dataset=None,
        notebook=_notebook(),
        documents=[
            {"file_name": "state.json", "status": "INDEXED", "chunk_count": 0, "doc_type": "DOCUMENT", "content_type": "text", "domain": "DOCS_OTHER", "source_path": ""},
        ],
    )

    assert card["disposition"]["status"] == "review_indexed_without_chunks"
    assert card["observations"]["missing_source_path_count"] == 1
    assert ".json" in card["documents"]["extension_counts"]


def test_service_state_record_is_not_reported_as_missing_evidence_chunk():
    card = build_quality_card(
        _contour(),
        health_dataset={"status": "IDLE"},
        notebook=_notebook(),
        documents=[
            {"file_name": "BAI/.pdf_preprocess_state.json", "status": "INDEXED", "chunk_count": 0, "doc_type": "DOCUMENT", "content_type": "text", "domain": "DOCS_OTHER", "source_path": "/src/state.json"},
        ],
    )

    assert card["disposition"]["status"] == "baseline_candidate"
    assert card["observations"]["indexed_zero_chunks"] == []
    assert card["observations"]["service_records"][0]["file_name"].endswith(".json")


def test_quality_card_exposes_pending_duplicate_basename_and_runtime_status_drift():
    card = build_quality_card(
        _contour(),
        health_dataset={"status": "ERROR"},
        notebook=_notebook(),
        documents=[
            {"file_name": "raw/a.xlsx", "status": "PENDING", "chunk_count": 0, "doc_type": "SMETA", "content_type": "", "domain": "TABLE_SMETA", "source_path": "/src/a.xlsx"},
            {"file_name": "projection/a.xlsx", "status": "PENDING", "chunk_count": 0, "doc_type": "SMETA", "content_type": "", "domain": "TABLE_SMETA", "source_path": "/src/a-copy.xlsx"},
        ],
    )

    assert card["observations"]["pending_duplicate_basenames"] == {"a.xlsx": 2}
    assert card["observations"]["runtime_status_drift"] is True


def test_fetch_documents_follows_document_explorer_pagination():
    calls = []

    def fetch(url: str) -> dict:
        calls.append(url)
        if "offset=0" in url:
            return {"total": 3, "documents": [{"file_name": "a"}, {"file_name": "b"}]}
        return {"total": 3, "documents": [{"file_name": "c"}]}

    rows = fetch_documents(fetch, proxy_url="http://les", dataset_id="ds", page_size=2)

    assert [row["file_name"] for row in rows] == ["a", "b", "c"]
    assert len(calls) == 2


def test_inventory_and_markdown_use_only_api_payloads():
    def fetch(url: str) -> dict:
        if url.endswith("/api/health"):
            return {
                "status": "degraded",
                "rag": {"qdrant": {"collection": "qwen", "points_match_sqlite_chunks": True}, "datasets": [{"id": "ds-1", "name": "ПД ИЦ", "status": "IDLE"}]},
            }
        if "/documents" in url:
            return {"total": 1, "documents": [{"file_name": "01.pdf", "status": "INDEXED", "chunk_count": 2, "doc_type": "DOCUMENT", "content_type": "text", "domain": "DOCS_OTHER", "source_path": "/src/01.pdf"}]}
        if "/api/notebooks/" in url:
            return _notebook()
        raise AssertionError(url)

    inventory = build_priority_inventory(proxy_url="http://les", contours=[_contour()], fetch=fetch)
    markdown = render_markdown(inventory)

    assert inventory["is_evidence"] is False
    assert inventory["cards"][0]["disposition"]["status"] == "baseline_candidate"
    assert "Не evidence" in markdown
    assert "baseline_candidate" in markdown
