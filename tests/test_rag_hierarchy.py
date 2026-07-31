from dataclasses import dataclass

from backend.rag_hierarchy import (
    EVIDENCE_ROLE,
    NAVIGATION_ROLE,
    deterministic_node_id,
    evidence_only,
    evidence_payload,
    navigation_payload,
    reciprocal_rank_fuse,
)


@dataclass
class Hit:
    content: str
    doc_id: str
    score: float
    meta: dict
    doc_name: str = "doc.md"


def test_hierarchy_ids_are_deterministic_and_navigation_is_not_evidence():
    first = navigation_payload(
        dataset_id="ds",
        document_id="doc",
        identity="1/1.1",
        title="1.1 Требования",
        ancestor_ids=["root"],
        depth=2,
    )
    second = navigation_payload(
        dataset_id="ds",
        document_id="doc",
        identity="1/1.1",
        title="1.1 Требования",
        ancestor_ids=["root"],
        depth=2,
    )
    leaf = evidence_payload(
        dataset_id="ds",
        document_id="doc",
        identity="chunk-1",
        ancestor_ids=[first["node_id"]],
        depth=3,
    )

    assert first["node_id"] == second["node_id"]
    assert first["node_role"] == NAVIGATION_ROLE
    assert first["evidence_admissible"] is False
    assert leaf["node_role"] == EVIDENCE_ROLE
    assert leaf["hierarchy_parent_id"] == first["node_id"]
    assert deterministic_node_id(
        dataset_id="ds",
        document_id="doc",
        node_kind="chunk",
        identity="chunk-1",
    ) == leaf["node_id"]


def test_soft_fusion_keeps_global_evidence_when_navigation_leg_misses():
    global_hit = Hit("global", "g", 1.0, {"node_id": "g", "node_role": "evidence"})
    navigation_hit = Hit(
        "section",
        "n",
        1.0,
        {"node_id": "n", "node_role": "navigation"},
    )

    fused = reciprocal_rank_fuse([[global_hit], [navigation_hit]], limit=5)

    assert fused == [global_hit]
    assert evidence_only([navigation_hit, global_hit]) == [global_hit]
