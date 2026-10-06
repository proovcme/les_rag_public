"""Technical source mode never silently reuses another mode's durable job."""
import hashlib
import json
import sqlite3
from dataclasses import replace

import pytest

from proxy.services.workbook_research_job_service import WorkbookResearchJobError, WorkbookResearchJobService


def _identity(service, *, cap=0, question="Собери ЛСР"):
    kwargs = dict(session_id="session", attachment_id="read_123456abcdef", source_sha256="a" * 64,
                  dataset_ids=["smeta"], profile_revision_id="profile", model_identity="model", question=question)
    if cap:
        kwargs["source_frame_contract_sha256"] = hashlib.sha256(str(cap).encode()).hexdigest()
    return service.identity(**kwargs)


def test_zero_identity_and_serialization_are_exact_legacy(tmp_path):
    store = WorkbookResearchJobService(tmp_path / "jobs.sqlite")
    identity = _identity(store)
    old = {"session_id": "session", "attachment_id": "read_123456abcdef", "source_sha256": "a" * 64,
           "dataset_ids": ["smeta"], "profile_revision_id": "profile", "model_identity": "model",
           "question_sha256": hashlib.sha256("Собери ЛСР".encode()).hexdigest()}
    expected = hashlib.sha256(json.dumps(old, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()
    assert identity.digest() == expected
    job = store.begin_or_resume(identity)
    with sqlite3.connect(store.db_path) as conn:
        raw = conn.execute("SELECT identity_json FROM workbook_research_jobs WHERE job_id=?", (job["job_id"],)).fetchone()[0]
    assert json.loads(raw) == old


def test_fresh_mode_or_cap_does_not_inherit_legacy_or_other_frame_progress(tmp_path):
    store = WorkbookResearchJobService(tmp_path / "scope.sqlite")
    previous = None
    for cap in (0, 2, 3, 0):
        identity = _identity(store, cap=cap, question=f"Собери ЛСР {cap} {previous}")
        frame = {"source_frame": {"schema": "les.model_source_frame.v1", "mode": "source_rows", "rows_per_frame": cap,
                                  "catalog_sha256": "c" * 64}} if cap else {}
        job = store.begin_or_resume(identity, source_locators=["S!R2", "S!R3"], task_context=frame)
        if cap:
            assert not job["continues_job_id"]
            assert job["accepted_rows"] == []
            assert job["task_context"]["source_frame"] == frame["source_frame"]
        elif previous is None:
            assert not job["continues_job_id"]
        else:
            assert job["continues_job_id"] != previous
        row = {"source_row": "S!R2", "operation_id": f"op-{cap}", "row_role": "work", "norm_code": "authored",
               "evidence_refs": "Q1.H1", "evidence_bindings": {"Q1.H1": "exact"}}
        store.record_packet(job["job_id"], sheet="S", packet_locators=["S!R2"], accepted_rows=[row],
                            evidence=[], remaining=["S!R3"])
        previous = job["job_id"]


def test_same_frame_continuation_inherits_exact_rows_and_scope_after_restart(tmp_path):
    path = tmp_path / "resume.sqlite"
    store = WorkbookResearchJobService(path)
    frame = {"schema": "les.model_source_frame.v1", "mode": "source_rows", "rows_per_frame": 2, "catalog_sha256": "c" * 64}
    first = store.begin_or_resume(_identity(store, cap=2), source_locators=["S!R2", "S!R3"], task_context={"source_frame": frame})
    row = {"source_row": "S!R2", "operation_id": "permanent", "row_role": "work", "norm_code": "model-norm",
           "evidence_refs": "Q1.H1", "evidence_bindings": {"Q1.H1": "original-evidence"}}
    store.record_packet(first["job_id"], sheet="S", packet_locators=["S!R2"], accepted_rows=[row], evidence=[], remaining=["S!R3"])
    stored = store.get(first["job_id"])
    reopened = WorkbookResearchJobService(path)
    resumed = reopened.begin_or_resume(_identity(reopened, cap=2, question="Продолжи это же задание"),
                                       source_locators=["S!R2", "S!R3"], task_context={"source_frame": frame})
    assert resumed["continues_job_id"] == first["job_id"]
    assert resumed["accepted_rows"] == stored["accepted_rows"]
    assert resumed["task_context"]["source_frame"] == frame
    assert resumed["remaining"] == ["S!R3"]


@pytest.mark.parametrize("old_cap,new_cap", [(0, 2), (2, 0), (2, 3)])
def test_plain_resume_of_another_frame_scope_is_visible_error_and_preserves_checkpoint(tmp_path, old_cap, new_cap):
    store = WorkbookResearchJobService(tmp_path / "scope-change.sqlite")
    first = store.begin_or_resume(_identity(store, cap=old_cap), source_locators=["S!R2", "S!R3"])
    row = {"operation_id": "unchanged", "source_row": "S!R2", "row_role": "work", "norm_code": "authored",
           "evidence_refs": "Q1.H1", "evidence_bindings": {"Q1.H1": "pinned"}}
    store.record_packet(first["job_id"], sheet="S", packet_locators=["S!R2"], accepted_rows=[row],
                        evidence=[], remaining=["S!R3"])
    before = store.get(first["job_id"])
    with pytest.raises(WorkbookResearchJobError, match="SOURCE_FRAME_CONTINUATION_SCOPE_CHANGED"):
        store.begin_or_resume(_identity(store, cap=new_cap, question="Продолжи это же задание по тому же прикреплённому документу."),
                              source_locators=["S!R2", "S!R3"])
    assert store.get(first["job_id"])["accepted_rows"] == before["accepted_rows"]
    assert store.get(first["job_id"])["remaining"] == before["remaining"]
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM workbook_research_jobs").fetchone()[0] == 1


def test_same_cap_new_catalog_revision_requires_explicit_fresh_task(tmp_path):
    store = WorkbookResearchJobService(tmp_path / "revision.sqlite")
    old = _identity(store, cap=2)
    first = store.begin_or_resume(old)
    changed = replace(_identity(store, cap=2, question="Продолжи"), source_frame_contract_sha256="b" * 64)
    with pytest.raises(WorkbookResearchJobError, match="SOURCE_FRAME_CONTINUATION_SCOPE_CHANGED"):
        store.begin_or_resume(changed)
    explicit = replace(_identity(store, cap=2, question="Собери ЛСР заново, Санкт-Петербург, 3 квартал 2026"),
                       source_frame_contract_sha256="b" * 64)
    fresh = store.begin_or_resume(explicit)
    assert fresh["job_id"] != first["job_id"] and fresh["continues_job_id"] == ""
    assert fresh["accepted_rows"] == []
