from __future__ import annotations

from types import SimpleNamespace

from proxy.services.retrieval_candidate_service import select_diverse_candidates


def _chunk(path: str, chunk_id: str, page: int):
    return SimpleNamespace(
        content=f"{chunk_id} text",
        doc_name=path.rsplit("/", 1)[-1],
        doc_id="doc-a" if path.endswith("a.pdf") else "doc-b",
        meta={
            "source_ref": f"{path}#p{page}",
            "file_path": path,
            "chunk_id": chunk_id,
            "page": page,
        },
    )


def test_exact_duplicates_collapse_but_distinct_pages_survive():
    chunks = [
        _chunk("project/a.pdf", "c1", 1),
        _chunk("project/a.pdf", "c1", 1),
        _chunk("project/a.pdf", "c2", 2),
    ]

    selected = select_diverse_candidates(chunks, per_document_k=2, limit=6)

    assert [(item.meta["chunk_id"], item.meta["page"]) for item in selected] == [
        ("c1", 1),
        ("c2", 2),
    ]


def test_per_document_cap_preserves_rank_order_across_documents():
    chunks = [
        _chunk("project/a.pdf", "a1", 1),
        _chunk("project/a.pdf", "a2", 2),
        _chunk("project/b.pdf", "b1", 1),
    ]

    selected = select_diverse_candidates(chunks, per_document_k=1, limit=6)

    assert [item.meta["chunk_id"] for item in selected] == ["a1", "b1"]


def test_same_basename_in_different_paths_is_not_one_physical_document():
    chunks = [
        _chunk("project/a/spec.pdf", "a1", 1),
        _chunk("project/b/spec.pdf", "b1", 1),
    ]
    chunks[0].doc_id = ""
    chunks[1].doc_id = ""

    selected = select_diverse_candidates(chunks, per_document_k=1, limit=6)

    assert [item.meta["chunk_id"] for item in selected] == ["a1", "b1"]
