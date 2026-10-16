"""Gap research preserves durable decisions until the model revises exact operations."""
from copy import deepcopy

import pytest

from proxy.services.workbook_research_job_service import WorkbookResearchJobError, WorkbookResearchJobService


SOURCE = "Раздел Ω 'исходник'!R4"


def identity(store, question="Собери ЛСР, Санкт-Петербург, 3 квартал 2026", revision="connection:r10"):
    return store.identity(session_id="same-session", attachment_id="read_955-source", source_sha256="a" * 64,
        dataset_ids=["selected-norms"], profile_revision_id="same-profile", model_identity="same-model",
        model_connection_revision_id=revision, question=question)


def baseline(tmp_path, *, shared=2):
    store = WorkbookResearchJobService(tmp_path / "durable955.db")
    job = store.begin_or_resume(identity(store), task_context={
        "original_question": "Собери ЛСР, Санкт-Петербург, 3 квартал 2026",
        "price_basis": {"requested_region": "Санкт-Петербург", "requested": "3 квартал 2026"}})
    rows = [dict(source_row=SOURCE, row_role="work", title="Закрытая авторская работа", unit="м", quantity=12,
                 norm_code="MODEL-CLOSED", norm_status="EXACT_VERIFIED", evidence_refs=["Q1.H1"])]
    rows += [dict(source_row=SOURCE, row_role="work", title=f"Незакрытая авторская работа {index}",
                  unit="м", quantity=12, norm_code=f"MODEL-CONFLICT-{index}", norm_status="CONFLICT",
                  open_gap="Модель указала противоречие карточки", evidence_refs=["Q2.H1"])
             for index in range(shared - 1)]
    rows.append(dict(source_row="Другой лист!R9", row_role="work", title="Норма пока не найдена", unit="шт",
                     quantity=2, norm_code="", norm_status="MISSING", open_gap="Нужен дальнейший поиск"))
    job = store.record_packet(job["job_id"], sheet="Раздел Ω 'исходник'", packet_locators=[SOURCE, "Другой лист!R9"],
        accepted_rows=rows, evidence=[{"global_evidence_id": "evidence955", "content": "Original exact evidence"}],
        remaining=[], held_packet={"locators": [SOURCE, "Другой лист!R9"], "terminal_model_result_saved": True})
    store.record_search_cache(job["job_id"], {"Literal original query": [{"content": "Original card"}]})
    store.record_artifact_kind(job["job_id"], declaration={"status": "declared", "artifact_kind": "lsr",
        "declarations": ["lsr"], "errors": [], "authority": "result"})
    store.finish(job["job_id"], status="complete")
    store.record_packaging(job["job_id"], tool="build_lsr_workbook", revision_id="rev_before_955", draft=False,
        price_basis={"actual_book": "sankt-peterburg_3kv2026", "actual_region": "Санкт-Петербург",
                     "actual_quarter": "3 квартал 2026 г.", "pricebook_sha256": "b" * 64, "match": "exact"})
    return store, store.get(job["job_id"])


def queue(store, job, ids=None, locators=None):
    return store.reopen_locators(job["job_id"], locators or [SOURCE], preserve_accepted=True, operation_ids=ids,
        chat_review={"message": "Добери нормы; проверь карточки по уточнению инженера", "decision_author": "user"})


def test_scoped_gap_retry_keeps_closed_and_conflicting_operations_at_the_same_source(tmp_path):
    store, original = baseline(tmp_path)
    before = deepcopy(original)
    closed, conflict = original["accepted_rows"][:2]
    current = queue(store, original, [conflict["operation_id"]])
    assert current["accepted_rows"] == before["accepted_rows"]
    assert current["task_context"]["price_basis"] == before["task_context"]["price_basis"]
    assert current["evidence"] == before["evidence"] and current["query_cache"] == before["query_cache"]
    assert store.pending_research_operation_ids(current) == {conflict["operation_id"]}
    assert store.pending_research_locators(current) == {SOURCE}
    assert current["remaining"] == [SOURCE]
    assert store.chat_review_context(current["job_id"])["prior_rows"] == [conflict]
    assert closed not in store.chat_review_context(current["job_id"])["prior_rows"]
    assert current["document"]["final_revision_id"] == "rev_before_955"


def test_restart_and_plain_resume_keep_pending_targets_price_basis_and_full_baseline(tmp_path):
    store, original = baseline(tmp_path)
    conflict = original["accepted_rows"][1]
    queued = queue(store, original, [conflict["operation_id"]])
    store.pause(queued["job_id"], remaining=[], phase="model_query_generation_pending")
    restarted = WorkbookResearchJobService(store.db_path)
    resumed = restarted.begin_or_resume(identity(restarted, "Продолжи"))
    assert resumed["continues_job_id"] == original["job_id"]
    assert resumed["accepted_rows"] == original["accepted_rows"]
    assert resumed["remaining"] == [SOURCE]
    assert restarted.pending_research_operation_ids(resumed) == {conflict["operation_id"]}
    assert resumed["task_context"]["price_basis"]["pricebook"] == "sankt-peterburg_3kv2026"
    assert resumed["task_context"]["price_basis"]["pricebook_sha256"] == "b" * 64
    # A continuation's own packaging state is separate from the document's
    # revision lineage, which remains available through the canonical reader.
    events = restarted.document_packaging_events(attachment_id="read_955-source", source_sha256="a" * 64)
    assert events[-1]["payload"]["revision_id"] == "rev_before_955"
    assert events[-1]["job_id"] == original["job_id"]


def test_admitted_same_id_revision_replaces_only_its_baseline_and_resolves_its_queue(tmp_path):
    store, original = baseline(tmp_path)
    conflict = original["accepted_rows"][1]
    queued = queue(store, original, [conflict["operation_id"]])
    replacement = {**conflict, "expected_revision": conflict["revision"],
                   "norm_code": "MODEL-NEW-CHOICE", "norm_status": "EXACT_VERIFIED", "open_gap": ""}
    current = store.record_packet(queued["job_id"], sheet="Раздел Ω 'исходник'", packet_locators=[SOURCE],
        accepted_rows=[replacement], evidence=[], remaining=[SOURCE], enforce_packet_scope=True,
        held_packet={"locators": [SOURCE], "terminal_model_result_saved": True})
    assert current["accepted_rows"][0] == original["accepted_rows"][0]
    assert current["accepted_rows"][2] == original["accepted_rows"][2]
    revised = current["accepted_rows"][1]
    assert revised["operation_id"] == conflict["operation_id"] and revised["revision"] == 2
    assert revised["norm_code"] == "MODEL-NEW-CHOICE"
    assert store.pending_research_operation_ids(current) == set()
    assert store.pending_research_locators(current) == set() and current["remaining"] == []


def test_partial_shared_anchor_stays_pending_and_non_target_rewrite_remains_unapplied(tmp_path):
    store, original = baseline(tmp_path, shared=3)
    closed, first, second = original["accepted_rows"][:3]
    queued = queue(store, original, [first["operation_id"], second["operation_id"]])
    current = store.record_packet(queued["job_id"], sheet="S", packet_locators=[SOURCE],
        accepted_rows=[{**first, "expected_revision": 1},
                       {**closed, "expected_revision": 1, "norm_code": "UNREQUESTED-REWRITE"}],
        evidence=[], remaining=[], enforce_packet_scope=True,
        held_packet={"locators": [SOURCE], "terminal_model_result_saved": True})
    assert current["accepted_rows"] == original["accepted_rows"]
    assert store.pending_research_operation_ids(current) == {second["operation_id"]}
    assert current["remaining"] == [SOURCE]
    assert SOURCE not in store.terminal_packet_locators(current["held_packet"])
    assert current["unapplied_proposals"][-1]["code"] == "MODEL_RESULT_RESEARCH_OPERATION_NOT_REQUESTED"
    assert current["unapplied_proposals"][-1]["decision"]["norm_code"] == "UNREQUESTED-REWRITE"


def test_empty_or_stale_reply_does_not_clear_pending_or_burn_conflict_into_missing(tmp_path):
    store, original = baseline(tmp_path)
    conflict = original["accepted_rows"][1]
    queued = queue(store, original, [conflict["operation_id"]])
    current = store.record_packet(queued["job_id"], sheet="S", packet_locators=[SOURCE],
        accepted_rows=[{**conflict, "expected_revision": 0, "norm_code": "STALE"}], evidence=[], remaining=[],
        enforce_packet_scope=True, held_packet={"locators": [SOURCE], "terminal_model_result_saved": True})
    assert current["accepted_rows"] == original["accepted_rows"]
    assert current["accepted_rows"][1]["norm_status"] == "CONFLICT"
    assert current["remaining"] == [SOURCE]
    current = store.finish_with_declared_gaps(current["job_id"], gap_rows=[
        {"source_row": SOURCE, "row_role": "unresolved", "norm_status": "MISSING"}], attempts=4,
        offers_by_locator={SOURCE: 4})
    assert current["status"] == "paused" and current["remaining"] == [SOURCE]
    assert current["accepted_rows"] == original["accepted_rows"]


def test_unseen_source_target_closes_only_after_an_admitted_row(tmp_path):
    store, original = baseline(tmp_path)
    source = "Новый раздел!R21"
    queued = queue(store, original, [], [source])
    assert queued["accepted_rows"] == original["accepted_rows"]
    current = store.record_packet(queued["job_id"], sheet="Новый раздел", packet_locators=[source],
        accepted_rows=[], evidence=[], remaining=[])
    assert current["remaining"] == [source]
    current = store.record_packet(current["job_id"], sheet="Новый раздел", packet_locators=[source],
        accepted_rows=[{"source_row": source, "row_role": "work", "title": "Модельное решение",
                        "unit": "шт", "quantity": 1, "norm_status": "MISSING"}],
        evidence=[], remaining=[source], enforce_packet_scope=True)
    assert store.pending_research_locators(current) == set() and current["remaining"] == []
    assert current["accepted_rows"][:3] == original["accepted_rows"]


def test_empty_operation_targets_keep_existing_material_anchor_until_a_new_admitted_operation(tmp_path):
    store = WorkbookResearchJobService(tmp_path / "material-source955.db")
    job = store.begin_or_resume(identity(store))
    current = store.record_packet(job["job_id"], sheet="S", packet_locators=[SOURCE],
        accepted_rows=[{"source_row": SOURCE, "row_role": "material", "title": "Авторская поставка",
                        "unit": "шт", "quantity": 2}], evidence=[], remaining=[])
    material = current["accepted_rows"][0]
    store.finish(job["job_id"], status="complete")
    queued = queue(store, current, [], [SOURCE])
    assert queued["remaining"] == [SOURCE]
    assert store.pending_research_operation_ids(queued) == set()
    assert queued["task_context"]["pending_research_unassigned_locators"] == [SOURCE]
    # Repeating a retained sibling, with or without its identity, is not a new
    # admitted operation answering this explicit unassigned source scope.
    anonymous_copy = {key: value for key, value in material.items() if key not in {"operation_id", "revision"}}
    for reply in ([material], [anonymous_copy]):
        current = store.record_packet(job["job_id"], sheet="S", packet_locators=[SOURCE],
            accepted_rows=reply, evidence=[], remaining=[], enforce_packet_scope=True)
        assert current["accepted_rows"] == [material]
        assert current["remaining"] == [SOURCE]
        assert not store.list_events(job["job_id"], "research_targets_answered")
    current = store.record_packet(job["job_id"], sheet="S", packet_locators=[SOURCE],
        accepted_rows=[{"source_row": SOURCE, "row_role": "work", "title": "Новая авторская работа",
                        "unit": "шт", "quantity": 2}], evidence=[], remaining=[], enforce_packet_scope=True)
    assert current["accepted_rows"][0] == material and len(current["accepted_rows"]) == 2
    assert current["remaining"] == [] and store.pending_research_locators(current) == set()


def test_mixed_known_operation_and_unassigned_anchor_are_both_queued(tmp_path):
    store, original = baseline(tmp_path)
    conflict = original["accepted_rows"][1]
    other_source = original["accepted_rows"][2]["source_row"]
    current = queue(store, original, [conflict["operation_id"]], [SOURCE, other_source])
    assert set(current["remaining"]) == {SOURCE, other_source}
    assert store.pending_research_operation_ids(current) == {conflict["operation_id"]}
    assert current["task_context"]["pending_research_unassigned_locators"] == [other_source]
    assert current["accepted_rows"] == original["accepted_rows"]


def test_rejected_operation_source_reply_does_not_resolve_or_replace_its_pending_baseline(tmp_path):
    store, original = baseline(tmp_path)
    conflict = original["accepted_rows"][1]
    queued = queue(store, original, [conflict["operation_id"]])
    current = store.record_packet(queued["job_id"], sheet="S", packet_locators=[SOURCE],
        accepted_rows=[{**conflict, "source_row": "Чужой лист!R77"}], evidence=[], remaining=[],
        enforce_packet_scope=True)
    assert current["accepted_rows"] == original["accepted_rows"]
    assert current["remaining"] == [SOURCE]
    assert store.pending_research_operation_ids(current) == {conflict["operation_id"]}
    assert not store.list_events(current["job_id"], "research_targets_answered")


def test_default_explicit_reopen_keeps_legacy_semantics(tmp_path):
    store, original = baseline(tmp_path)
    current = store.reopen_locators(original["job_id"], [SOURCE])
    assert current["accepted_rows"] == original["accepted_rows"][2:]
    assert store.pending_research_operation_ids(current) == set()


def test_legacy_destructive_reopen_cannot_orphan_pending_operation_identities(tmp_path):
    store, original = baseline(tmp_path)
    queued = queue(store, original, [original["accepted_rows"][1]["operation_id"]])
    with pytest.raises(WorkbookResearchJobError, match="pending research requires preserving"):
        store.reopen_locators(queued["job_id"], [SOURCE])
    current = store.get(queued["job_id"])
    assert current["accepted_rows"] == queued["accepted_rows"]
    assert current["task_context"] == queued["task_context"]
    assert current["remaining"] == queued["remaining"]


def test_provider_options_revision_change_is_refused_without_erasing_old_progress(tmp_path):
    store, original = baseline(tmp_path)
    with pytest.raises(WorkbookResearchJobError, match="WORKBOOK_CONTINUATION_CONTEXT_CHANGED"):
        store.begin_or_resume(identity(store, "Продолжи", revision="connection:r11"))
    assert store.get(original["job_id"])["accepted_rows"] == original["accepted_rows"]
    resumed = store.begin_or_resume(identity(store, "Продолжи", revision="connection:r10"))
    assert resumed["accepted_rows"] == original["accepted_rows"]


def test_unknown_operation_target_fails_without_modifying_durable_state(tmp_path):
    store, original = baseline(tmp_path)
    with pytest.raises(WorkbookResearchJobError, match="outside requested source scope"):
        queue(store, original, ["not-an-existing-operation"])
    assert store.get(original["job_id"])["accepted_rows"] == original["accepted_rows"]
    assert store.pending_research_locators(store.get(original["job_id"])) == set()


def test_preserving_explicit_retry_does_not_clear_engineer_confirmations(tmp_path):
    store, original = baseline(tmp_path)
    conflict = original["accepted_rows"][1]
    store.record_overrides(original["job_id"], {SOURCE: {"confirmed_price": 123.45}})
    current = store.reopen_locators(original["job_id"], [SOURCE], preserve_accepted=True,
                                   operation_ids=[conflict["operation_id"]])
    assert current["operator_overrides"][SOURCE]["confirmed_price"] == 123.45
    assert current["accepted_rows"] == original["accepted_rows"]


def test_pending_explicit_research_cannot_be_finished_by_a_stale_completion(tmp_path):
    store, original = baseline(tmp_path)
    conflict = original["accepted_rows"][1]
    queued = queue(store, original, [conflict["operation_id"]])
    current = store.finish(queued["job_id"], status="complete", phase="stale_model_result")
    assert current["status"] == "paused" and current["phase"] == "research_pending"
    assert current["remaining"] == [SOURCE] and current["accepted_rows"] == original["accepted_rows"]
    event = store.list_events(current["job_id"], "completion_deferred")[-1]["payload"]
    assert event["operation_ids"] == [conflict["operation_id"]]
    assert event["reason"] == "pending_model_research_targets"
    store.record_packet(current["job_id"], sheet="Раздел Ω 'исходник'", packet_locators=[SOURCE],
        accepted_rows=[conflict], evidence=[], remaining=[], enforce_packet_scope=True)
    assert store.finish(current["job_id"], status="complete")["status"] == "complete"
