import json

from backend.raptor_tree import RaptorLeaf, build_tree, evidence_leaf_ids, save_checkpoint


def _summary(texts, depth):
    return f"Уровень {depth}", " | ".join(texts)


def test_raptor_tree_is_deterministic_and_never_becomes_evidence(tmp_path):
    leaves = [RaptorLeaf(str(i), "doc", f"leaf {i}") for i in range(5)]
    first = build_tree(leaves, _summary, fanout=2, max_depth=3)
    second = build_tree(list(reversed(leaves)), _summary, fanout=2, max_depth=3)
    assert first == second
    assert all(node.node_role == "navigation" for node in first)
    assert all(node.node_kind == "raptor_summary" for node in first)
    assert set(evidence_leaf_ids(first)) == {str(i) for i in range(5)}

    checkpoint = tmp_path / "путь с пробелом" / "raptor.json"
    save_checkpoint(checkpoint, completed_leaf_hash="abc", nodes=first)
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["schema"] == "les.rag.raptor.v1"
    assert payload["nodes"][0]["node_role"] == "navigation"
