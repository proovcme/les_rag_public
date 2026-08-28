import pytest

from proxy.services.workflow_checkpoint_service import (
    CheckpointBeginRequest,
    CheckpointConflict,
    WorkflowCheckpointService,
)


def _request(*, attachment_id="read_123456abcdef", attachment_sha256="a" * 64,
             key="key-1", dataset_ids=None):
    return CheckpointBeginRequest(
        session_id="session-1",
        idempotency_key=key,
        tool_name="build_vor_workbook",
        attachment_id=attachment_id,
        attachment_sha256=attachment_sha256,
        normalized_args={"attachment_id": attachment_id, "dataset_ids": dataset_ids},
        model_decision_revision="decision-1",
    )


def test_retry_resumes_same_checkpoint_and_progress(tmp_path):
    service = WorkflowCheckpointService(tmp_path / "checkpoints.db")
    first = service.begin_or_resume(_request())
    service.record_progress(first.checkpoint_id, phase="rows", completed=3, total=10)
    resumed = service.begin_or_resume(_request())

    assert resumed.checkpoint_id == first.checkpoint_id
    assert resumed.phase == "rows"
    assert resumed.completed_items == 3
    assert resumed.total_items == 10


def test_idempotency_key_cannot_change_attachment(tmp_path):
    service = WorkflowCheckpointService(tmp_path / "checkpoints.db")
    service.begin_or_resume(_request())

    with pytest.raises(CheckpointConflict, match="attachment"):
        service.begin_or_resume(_request(attachment_id="read_abcdef123456"))


def test_idempotency_key_cannot_change_attachment_hash(tmp_path):
    service = WorkflowCheckpointService(tmp_path / "checkpoints.db")
    service.begin_or_resume(_request())

    with pytest.raises(CheckpointConflict, match="hash"):
        service.begin_or_resume(_request(attachment_sha256="b" * 64))


def test_none_and_empty_dataset_scope_have_one_argument_identity(tmp_path):
    service = WorkflowCheckpointService(tmp_path / "checkpoints.db")
    first = service.begin_or_resume(_request(dataset_ids=None))
    resumed = service.begin_or_resume(_request(dataset_ids=[]))

    assert resumed.checkpoint_id == first.checkpoint_id
    assert resumed.normalized_args_sha256 == first.normalized_args_sha256


def test_completion_keeps_artifact_revision_and_bounded_blockers(tmp_path):
    service = WorkflowCheckpointService(tmp_path / "checkpoints.db", max_status_items=2)
    checkpoint = service.begin_or_resume(_request())
    service.record_status(
        checkpoint.checkpoint_id,
        status="blocked",
        missing=("m1", "m2", "m3"),
        blockers=("b1", "b2", "b3"),
    )
    service.complete(checkpoint.checkpoint_id, "rev_123")
    completed = service.get(checkpoint.checkpoint_id)

    assert completed.status == "complete"
    assert completed.artifact_revision_id == "rev_123"
    assert completed.missing == ("m1", "m2")
    assert completed.blockers == ("b1", "b2")
