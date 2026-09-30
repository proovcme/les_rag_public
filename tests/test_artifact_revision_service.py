from pathlib import Path

import pytest

from proxy.services.artifact_revision_service import (
    ArtifactImmutableError,
    ArtifactRevisionRequest,
    ArtifactRevisionStore,
)


def _request(file_path: Path, *, parent: str | None = None) -> ArtifactRevisionRequest:
    return ArtifactRevisionRequest(
        artifact_kind="vor_workbook",
        file_path=file_path,
        source_scope=("dataset-1",),
        profile_revision_id="profile-1",
        model_identity="local-model",
        model_preset="qwen-9b",
        tool_calls=({"name": "build_vor_workbook", "call_id": "call-1"},),
        decision_checkpoint_id="checkpoint-1",
        missing=(),
        blockers=(),
        parent_revision_id=parent,
    )


def _workbook(tmp_path: Path, name: str, payload: bytes) -> Path:
    target = tmp_path / name
    target.write_bytes(payload)
    return target


def test_correction_creates_new_revision_and_preserves_parent(tmp_path):
    store = ArtifactRevisionStore(tmp_path / "meta.db", tmp_path / "artifacts")
    first = store.create_revision(_request(_workbook(tmp_path, "v1.xlsx", b"first")))
    second = store.create_revision(
        _request(_workbook(tmp_path, "v2.xlsx", b"second"), parent=first.revision_id)
    )

    assert first.artifact_id == second.artifact_id
    assert (first.revision_no, second.revision_no) == (1, 2)
    assert second.parent_revision_id == first.revision_id
    assert store.read_bytes(first.revision_id) == b"first"
    assert store.read_bytes(second.revision_id) == b"second"


def test_existing_revision_file_cannot_be_overwritten(tmp_path):
    store = ArtifactRevisionStore(tmp_path / "meta.db", tmp_path / "artifacts")
    revision = store.create_revision(_request(_workbook(tmp_path, "v1.xlsx", b"first")))

    with pytest.raises(ArtifactImmutableError):
        store.replace_bytes(revision.revision_id, b"changed")


def test_recovery_from_older_parent_appends_without_revision_number_collision(tmp_path):
    """Live 834: chat retains an older parent after a successful local repack."""
    store = ArtifactRevisionStore(tmp_path / "meta.db", tmp_path / "artifacts")
    first = store.create_revision(_request(_workbook(tmp_path, "v1.xlsx", b"first")))
    repacked = store.create_revision(_request(_workbook(tmp_path, "v2.xlsx", b"repacked"), parent=first.revision_id))
    reviewed = store.create_revision(_request(_workbook(tmp_path, "v3.xlsx", b"reviewed"), parent=first.revision_id))
    assert [r.revision_no for r in store.list_revisions(first.artifact_id)] == [1, 2, 3]
    assert reviewed.parent_revision_id == first.revision_id
    assert reviewed.artifact_id == repacked.artifact_id == first.artifact_id
    assert store.read_bytes(first.revision_id) == b"first"
    assert store.read_bytes(repacked.revision_id) == b"repacked"
    assert store.read_bytes(reviewed.revision_id) == b"reviewed"


def test_parallel_delivery_from_same_parent_gets_unique_monotonic_numbers(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store = ArtifactRevisionStore(tmp_path / "meta.db", tmp_path / "artifacts")
    first = store.create_revision(_request(_workbook(tmp_path, "first.xlsx", b"first")))
    requests = [_request(_workbook(tmp_path, f"next-{i}.xlsx", str(i).encode()), parent=first.revision_id) for i in range(4)]
    with ThreadPoolExecutor(max_workers=4) as workers:
        revisions = list(workers.map(store.create_revision, requests))
    assert sorted(r.revision_no for r in revisions) == [2, 3, 4, 5]
    assert all(r.parent_revision_id == first.revision_id for r in revisions)
    assert {store.read_bytes(r.revision_id) for r in revisions} == {b"0", b"1", b"2", b"3"}


def test_hash_drift_is_detected_before_read(tmp_path):
    store = ArtifactRevisionStore(tmp_path / "meta.db", tmp_path / "artifacts")
    revision = store.create_revision(_request(_workbook(tmp_path, "v1.xlsx", b"first")))
    stored_path = store.resolve_path(revision.revision_id)
    stored_path.write_bytes(b"tampered")

    with pytest.raises(ArtifactImmutableError, match="hash"):
        store.read_bytes(revision.revision_id)
