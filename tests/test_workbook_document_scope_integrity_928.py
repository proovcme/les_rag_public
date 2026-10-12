"""Durable research inheritance is bound to its literal scope/profile/model."""
from __future__ import annotations

import sqlite3
import json

import pytest

from proxy.services.workbook_research_job_service import WorkbookResearchJobService


def _identity(service, question="Первое задание", **changes):
    fields = {
        "session_id": "session", "attachment_id": "read_123456abcdef", "source_sha256": "a" * 64,
        "dataset_ids": ["documents", "norms"], "profile_revision_id": "profile:1",
        "model_identity": "model:1", "question": question,
    }
    fields.update(changes)
    return service.identity(**fields)


def _seed(service, identity):
    job = service.begin_or_resume(identity, source_locators=["S!R2", "S!R3"], task_context={
        "original_question": "Буквальная исходная задача", "artifact_intent": "lsr",
        "price_basis": {"region": "Москва", "quarter": "3 квартал 2026"},
    })
    service.record_packet(
        job["job_id"], sheet="S", packet_locators=["S!R2"],
        accepted_rows=[{"source_row": "S!R2", "row_role": "work", "title": "Авторская операция",
                        "quantity": 12, "unit": "м", "norm_code": "literal-model-choice"}],
        evidence=[{"global_evidence_id": "literal-evidence", "content": "Literal card from the first scope"}],
        remaining=["S!R3"],
    )
    service.record_search_cache(job["job_id"], {"literal query": [{"content": "Old scoped hit"}]})
    service.defer_locators(job["job_id"], sheet="S", locators=["S!R3"], reason="Literal unresolved reason", offers=3)
    service.record_overrides(job["job_id"], {"S!R2": {"conversion_source": "Literal operator evidence"}})
    return service.pause(
        job["job_id"], remaining=["S!R3"],
        held_packet={"sheet": "S", "locators": ["S!R3"], "queries": ["literal pending query"]},
    )


def _stored_row(service, job_id):
    with sqlite3.connect(service.db_path) as connection:
        return connection.execute("SELECT * FROM workbook_research_jobs WHERE job_id=?", (job_id,)).fetchone()


@pytest.mark.parametrize("changed", [
    {"dataset_ids": ["other-documents", "norms"]},
    {"profile_revision_id": "profile:2"},
    {"model_identity": "model:2"},
])
def test_new_incompatible_identity_never_inherits_decisions_evidence_cache_or_task(tmp_path, changed):
    service = WorkbookResearchJobService(tmp_path / "scope.sqlite")
    first = _seed(service, _identity(service))
    before = _stored_row(service, first["job_id"])
    restarted = WorkbookResearchJobService(service.db_path)

    fresh = restarted.begin_or_resume(
        _identity(restarted, question="Уточнение без специального маркера", **changed),
        source_locators=["S!R2", "S!R3"], task_context={"original_question": "Новая исходная задача"},
    )

    assert fresh["job_id"] != first["job_id"]
    assert fresh["continues_job_id"] == ""
    assert fresh["accepted_rows"] == []
    assert fresh["evidence"] == []
    assert fresh["query_cache"] == {}
    assert restarted.still_deferred(fresh["job_id"], sheet="S") == []
    assert fresh["held_packet"] == {}
    assert fresh["operator_overrides"] == {}
    assert fresh["remaining"] == ["S!R2", "S!R3"]
    assert fresh["task_context"]["original_question"] == "Новая исходная задача"
    assert fresh["task_context"]["price_basis"] == {}
    assert restarted.list_events(fresh["job_id"], event_type="progress_inherited") == []
    assert _stored_row(restarted, first["job_id"]) == before


@pytest.mark.parametrize("question", ["Уточни исходные условия", "Обработай оставшиеся строки"])
def test_same_binding_keeps_progress_task_and_prices_without_question_text_admission(tmp_path, question):
    service = WorkbookResearchJobService(tmp_path / "scope.sqlite")
    first = _seed(service, _identity(service))
    before = _stored_row(service, first["job_id"])
    restarted = WorkbookResearchJobService(service.db_path)

    continued = restarted.begin_or_resume(
        _identity(restarted, question=question, session_id="regenerated-session",
                  dataset_ids=["norms", "documents"]),
        source_locators=["S!R2", "S!R3"], task_context={"original_question": question, "price_basis": {}},
    )

    assert continued["continues_job_id"] == first["job_id"]
    for field in ("accepted_rows", "evidence", "query_cache", "operator_overrides", "remaining", "held_packet"):
        assert continued[field] == first[field]
    assert continued["task_context"] == first["task_context"]
    with sqlite3.connect(restarted.db_path) as connection:
        deferrals = json.loads(connection.execute(
            "SELECT deferrals_json FROM workbook_research_jobs WHERE job_id=?", (continued["job_id"],),
        ).fetchone()[0])
    assert deferrals["S!R3"]["inherited_from_job"] == first["job_id"]
    assert _stored_row(restarted, first["job_id"]) == before


def test_latest_compatible_parent_survives_interleaved_foreign_scope(tmp_path):
    service = WorkbookResearchJobService(tmp_path / "scope.sqlite")
    own = _seed(service, _identity(service))
    foreign = _seed(service, _identity(service, question="Другая область", dataset_ids=["foreign-corpus"]))

    continued = service.begin_or_resume(_identity(service, question="Новое уточнение"))

    assert continued["continues_job_id"] == own["job_id"]
    assert continued["continues_job_id"] != foreign["job_id"]
    assert continued["accepted_rows"] == own["accepted_rows"]
    assert service.lineage_job_ids(continued["job_id"]) == [own["job_id"], continued["job_id"]]
