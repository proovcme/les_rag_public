import json

import pytest

from backend.raptor_publication_worker import (
    publish_document_batches_with_resume,
    publish_with_resume,
)
from backend.raptor_tree import RaptorLeaf


def _summary(texts, depth):
    return f"Depth {depth}", " | ".join(texts)


def test_publication_resumes_after_last_completed_document(tmp_path):
    leaves = [
        RaptorLeaf("a1", "doc-a", "A one"),
        RaptorLeaf("a2", "doc-a", "A two"),
        RaptorLeaf("b1", "doc-b", "B one"),
        RaptorLeaf("b2", "doc-b", "B two"),
    ]
    checkpoint = tmp_path / "путь с пробелом" / "raptor.json"
    first_calls = []

    def fail_on_second(document_id, nodes):
        first_calls.append(document_id)
        if document_id == "doc-b":
            raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        publish_with_resume(
            leaves,
            _summary,
            fail_on_second,
            checkpoint_path=checkpoint,
            fanout=2,
        )
    assert first_calls == ["doc-a", "doc-b"]
    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["completed_documents"] == ["doc-a"]

    resumed = []
    result = publish_with_resume(
        leaves,
        _summary,
        lambda document_id, nodes: resumed.append((document_id, len(nodes))),
        checkpoint_path=checkpoint,
        fanout=2,
    )
    assert resumed == [("doc-b", 1)]
    assert result["status"] == "completed"
    assert result["documents_completed"] == 2


def test_changed_leaf_set_invalidates_old_checkpoint(tmp_path):
    checkpoint = tmp_path / "raptor.json"
    first = [RaptorLeaf("a1", "doc-a", "A one"), RaptorLeaf("a2", "doc-a", "A two")]
    publish_with_resume(first, _summary, lambda *_: None, checkpoint_path=checkpoint, fanout=2)
    calls = []
    changed = first + [RaptorLeaf("b1", "doc-b", "B one"), RaptorLeaf("b2", "doc-b", "B two")]
    publish_with_resume(
        changed,
        _summary,
        lambda document_id, nodes: calls.append(document_id),
        checkpoint_path=checkpoint,
        fanout=2,
    )
    assert calls == ["doc-a", "doc-b"]


def test_streaming_publication_resumes_at_unconfirmed_document(tmp_path):
    checkpoint = tmp_path / "raptor.json"
    loaded = []
    published = []

    def load_document(document_id):
        loaded.append(document_id)
        return [
            RaptorLeaf(f"{document_id}-1", document_id, "one"),
            RaptorLeaf(f"{document_id}-2", document_id, "two"),
        ]

    def fail_second(document_id, nodes):
        if document_id == "b":
            raise RuntimeError("temporary")
        published.append((document_id, len(nodes)))

    with pytest.raises(RuntimeError, match="temporary"):
        publish_document_batches_with_resume(
            ("a", "b"), load_document, _summary, fail_second,
            source_fingerprint="source-v1", documents_total=2,
            checkpoint_path=checkpoint, fanout=2,
        )

    loaded.clear()
    result = publish_document_batches_with_resume(
        ("a", "b"), load_document, _summary,
        lambda document_id, nodes: published.append((document_id, len(nodes))),
        source_fingerprint="source-v1", documents_total=2,
        checkpoint_path=checkpoint, fanout=2,
    )

    assert loaded == ["b"]
    assert [item[0] for item in published] == ["a", "b"]
    assert result["status"] == "completed"
    assert result["progress"] == 1.0


def test_streaming_publication_fails_closed_on_short_document_stream(tmp_path):
    with pytest.raises(RuntimeError, match="RAPTOR_DOCUMENT_STREAM_INCOMPLETE"):
        publish_document_batches_with_resume(
            ("a",),
            lambda document_id: [RaptorLeaf("1", document_id, "one")],
            _summary,
            lambda _document_id, _nodes: None,
            source_fingerprint="source-v1", documents_total=2,
            checkpoint_path=tmp_path / "raptor.json",
        )
