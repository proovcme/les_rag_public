from __future__ import annotations

from types import SimpleNamespace

from proxy.services.source_locator_service import (
    evidence_counts,
    source_map_item,
)


def test_file_locator_preserves_source_ref_page_chunk_and_excerpt():
    chunk = SimpleNamespace(
        content="used text",
        doc_name="spec.pdf",
        doc_id="doc-7",
        score=0.9,
        meta={
            "dataset_id": "ds",
            "source_ref": "ds/spec.pdf#p7",
            "page": 7,
            "chunk_id": "c-7",
        },
    )

    item = source_map_item(chunk, index=1)

    assert item["source_ref"] == "ds/spec.pdf#p7"
    assert item["page"] == 7
    assert item["locator"] == {
        "kind": "file_excerpt",
        "dataset_id": "ds",
        "doc_id": "doc-7",
        "source_ref": "ds/spec.pdf#p7",
        "relative_path": "ds/spec.pdf",
        "page": 7,
        "chunk_id": "c-7",
        "excerpt": "used text",
    }


def test_norm_card_without_doc_id_is_not_presented_as_file():
    chunk = SimpleNamespace(
        content="Шифр: ГЭСН01-01-001-01",
        doc_name="smeta_norm_cards.v1",
        doc_id="",
        score=1.0,
        meta={
            "dataset_id": "smeta-dataset",
            "norm_code": "ГЭСН01-01-001-01",
            "source_ref": "fsnb#norm=ГЭСН01-01-001-01",
        },
    )

    item = source_map_item(chunk, index=1)

    assert item["locator"]["kind"] == "norm_card"
    assert item["locator"]["card_code"] == "ГЭСН01-01-001-01"
    assert "relative_path" not in item["locator"]


def test_web_and_unavailable_locators_never_invent_local_files():
    web = source_map_item(
        SimpleNamespace(
            content="price",
            doc_name="Supplier",
            doc_id="",
            score=0.4,
            meta={"url": "https://example.test/item", "provider": "simple"},
        ),
        index=1,
    )
    unavailable = source_map_item(
        SimpleNamespace(content="orphan", doc_name="", doc_id="", score=0.1, meta={}),
        index=2,
    )

    assert web["locator"]["kind"] == "web_result"
    assert web["locator"]["url"] == "https://example.test/item"
    assert unavailable["locator"] == {
        "kind": "unavailable",
        "reason": "source_locator_missing",
        "excerpt": "orphan",
    }


def test_evidence_counts_keep_found_visible_and_cited_independent():
    source_map = [
        {"index": 1, "evidence_ref": "Q1.H1"},
        {"index": 2, "evidence_ref": "Q1.H2"},
        {"index": 3, "evidence_ref": "Q2.H1"},
    ]

    counts = evidence_counts(
        answer="Опора [Источник 2], дополнение Q2.H1 и повтор Q2.H1.",
        source_map=source_map,
        found_count=11,
    )

    assert counts == {"found": 11, "model_visible": 3, "cited": 2}
