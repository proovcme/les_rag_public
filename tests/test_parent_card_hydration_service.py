from dataclasses import dataclass

from proxy.services.parent_card_hydration_service import (
    PARENT_CARD_SCHEMA,
    hydrate_parent_cards,
)


@dataclass
class Chunk:
    content: str
    doc_name: str = "doc.pdf"
    doc_id: str = ""
    score: float = 1.0
    meta: dict | None = None


def test_hydrate_parent_cards_from_candidate_pool():
    chunks = [
        Chunk(
            "Строка нормы",
            doc_id="d2",
            meta={
                "parent_id": "p1",
                "parent_heading": "Таблица 4",
                "dataset_id": "ds",
                "chunk_ord": 2,
                "content_hash": "h2",
            },
        ),
        Chunk(
            "Условие применимости",
            doc_id="d1",
            meta={
                "parent_id": "p1",
                "parent_heading": "Таблица 4",
                "dataset_id": "ds",
                "chunk_ord": 1,
                "content_hash": "h1",
            },
        ),
        Chunk("Чужой раздел", meta={"parent_id": "other", "chunk_ord": 1}),
    ]

    result = hydrate_parent_cards(chunks, max_chunks=2)

    assert result.hydrated_count == 2
    card = chunks[0].meta["parent_card"]
    assert card["schema"] == PARENT_CARD_SCHEMA
    assert card["parent_id"] == "p1"
    assert card["sibling_count"] == 2
    assert card["texts"][0] == "Условие применимости"
    assert card["texts"][1] == "Строка нормы"


def test_hydrate_parent_cards_uses_provider_and_skips_missing_parent():
    hit = Chunk("hit", meta={"parent_id": "p9", "dataset_id": "ds", "chunk_ord": 3, "content_hash": "hit"})
    orphan = Chunk("no parent", meta={})

    def provider(parent_id: str, dataset_id: str):
        assert parent_id == "p9"
        assert dataset_id == "ds"
        return [Chunk("sibling", meta={"parent_id": "p9", "chunk_ord": 1, "content_hash": "sib"})]

    result = hydrate_parent_cards([hit, orphan], sibling_provider=provider, max_chunks=2)

    assert result.hydrated_count == 1
    assert result.skipped_without_parent == 1
    assert result.provider_sibling_count == 1
    assert hit.meta["parent_card"]["texts"] == ["sibling", "hit"]
