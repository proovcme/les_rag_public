"""A new human Continue uses the existing exact-operation gap queue, never a model verdict."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services.lsr_result_readiness_service import build_lsr_result_readiness
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests.test_workbook_gap_followup_955 import baseline, identity, SOURCE


def _child(store, question="Продолжи"):
    requested = identity(store, question)
    return requested, store.begin_or_resume(requested, task_context={"original_question": question})


def _continue(store, job, requested, *, owner=True, question="Продолжи", catalog=None):
    return app.begin_plain_lsr_gap_continuation(store, job, identity=requested, question=question,
        owns_sheet_pass=owner, source_catalog=catalog)


@pytest.mark.parametrize("question", [
    "Продолжи", "Добери нормы", "Найди недостающие нормы", "Продолжи незакрытые строки",
])
def test_plain_continue_reopens_exact_open_ids_and_retains_closed_shared_source(tmp_path, question):
    store, original = baseline(tmp_path)
    requested, child = _child(store, question)
    before = deepcopy(child)
    assert store.is_plain_continuation(requested, {"original_question": question})
    assert not app.workbook_chat_review_needed(question, child)
    current = _continue(store, child, requested, question=question)
    expected = {row["operation_id"] for row in before["accepted_rows"][1:]}
    assert store.pending_research_operation_ids(current) == expected
    assert store.pending_research_locators(current) == {SOURCE, "Другой лист!R9"}
    assert current["accepted_rows"] == before["accepted_rows"]
    assert current["evidence"] == before["evidence"] and current["query_cache"] == before["query_cache"]
    assert current["task_context"]["price_basis"] == before["task_context"]["price_basis"]
    assert current["continues_job_id"] == original["job_id"]
    note = store.list_events(current["job_id"], "locators_reopened")[-1]["payload"]
    assert note["preserve_accepted"] is True and set(note["research_operation_ids"]) == expected
    assert note["chat_review"]["message"] == question and note["chat_review"]["review_scope"] == "operations"
    assert {row["operation_id"] for row in note["prior_rows"]} == expected
    assert not app.workbook_chat_review_needed(question, current)


@pytest.mark.parametrize("norm_status", [
    pytest.param("MISSING", id="missing-norm-status"), pytest.param("", id="role-only-gap"),
])
def test_unresolved_roles_stay_in_readiness_retry_ids_without_becoming_work(tmp_path, norm_status):
    _store, original = baseline(tmp_path)
    rows = deepcopy(original["accepted_rows"])
    for row in rows[1:]:
        row.update(row_role="unresolved", norm_code="", norm_status=norm_status,
                   gap_reason="no_suitable_candidate",
                   open_gap="Literal model reason: the available cards do not justify a decision.")
    before = deepcopy(rows)
    expected = {row["operation_id"] for row in rows[1:]}

    ready = build_lsr_result_readiness(
        packaged=True, rows=rows, catalog_locators=[SOURCE, "Другой лист!R9"],
        catalog_work_count=2, job_status="complete", pricing_status="priced_partial",
        price_basis=original["task_context"]["price_basis"],
    )

    assert set(ready["research_operation_ids"]) == expected
    assert set(ready["research_locators"]) == {SOURCE, "Другой лист!R9"}
    assert rows[0]["operation_id"] not in ready["research_operation_ids"]
    assert ready["counts"]["works"] == 1 and ready["counts"]["unresolved"] == 2
    assert ready["estimate_complete"] is False
    assert "resume" in {item["id"] for item in ready["actions"]}
    assert rows == before


def test_gap_resume_retains_unresolved_roles_norm_choices_and_closed_sibling(tmp_path):
    store, original = baseline(tmp_path)
    rows = deepcopy(original["accepted_rows"])
    for row in rows[1:]:
        # A saved cipher also survives while its operation role is unresolved.
        row.update(row_role="unresolved", norm_status="MISSING", gap_reason="no_suitable_candidate",
                   open_gap="Literal model reason: the available cards do not justify a decision.")
    store.replace_accepted_rows(original["job_id"], rows)
    requested, child = _child(store, "Добери нормы")
    before = deepcopy(child)
    expected = {row["operation_id"] for row in before["accepted_rows"][1:]}

    current = _continue(store, child, requested, question="Добери нормы")

    assert store.pending_research_operation_ids(current) == expected
    assert store.pending_research_locators(current) == {SOURCE, "Другой лист!R9"}
    assert current["accepted_rows"] == before["accepted_rows"]
    assert current["accepted_rows"][0] == before["accepted_rows"][0]
    assert all(row["row_role"] == "unresolved" for row in current["accepted_rows"][1:])
    assert current["evidence"] == before["evidence"] and current["query_cache"] == before["query_cache"]
    assert current["task_context"]["price_basis"] == before["task_context"]["price_basis"]
    assert current["continues_job_id"] == original["job_id"]
    note = store.list_events(current["job_id"], "locators_reopened")[-1]["payload"]
    assert note["preserve_accepted"] is True and set(note["research_operation_ids"]) == expected
    assert {row["operation_id"] for row in note["prior_rows"]} == expected


@pytest.mark.parametrize("question", [
    "Добери нормы для строки 14",
    "Найди недостающие нормы и проверь норму закрытой строки 14",
    "Продолжи незакрытые строки, измени объём строки 15 на 20 м",
    "Добери нормы; пересмотри уже закрытые строки",
])
def test_explicit_engineer_remarks_do_not_become_plain_gap_continuations(tmp_path, monkeypatch, question):
    store, _ = baseline(tmp_path)
    requested, child = _child(store, question)
    before = deepcopy(child)
    assert not store.is_plain_continuation(requested, {"original_question": question})
    assert app.workbook_chat_review_needed(question, child)

    def forbidden(*_args, **_kwargs):
        pytest.fail("an explicit remark must retain the existing document-review path")

    monkeypatch.setattr(store, "reopen_locators", forbidden)
    assert _continue(store, child, requested, question=question) is child
    assert child == before


@pytest.mark.parametrize("blocked", ["not_owner", "non_plain", "vor", "remaining", "proof", "held", "pending", "full_ready",
                                      "proof_capacity", "packaging"])
def test_plain_retry_does_not_replace_another_continuation_or_reopen_ready_rows(tmp_path, monkeypatch, blocked):
    store, _ = baseline(tmp_path)
    requested, child = _child(store)
    child = deepcopy(child)
    if blocked == "vor":
        child["task_context"]["artifact_kind_declaration"]["artifact_kind"] = "vor"
    elif blocked == "remaining":
        child["remaining"] = [SOURCE]
    elif blocked == "proof":
        child["held_packet"] = {"locators": [SOURCE], "pending_proof": {"purpose": "norm"}}
    elif blocked == "held":
        child["held_packet"] = {"locators": [SOURCE], "queries": ["literal saved plan"]}
    elif blocked == "pending":
        child["task_context"]["pending_research_locators"] = [SOURCE]
    elif blocked == "proof_capacity":
        child["held_packet"] = {"terminal_model_result_saved": True,
            "proof_context_failure": {"technical_failure": True, "purpose": "sheet_pass_norm_proof"}}
    elif blocked == "packaging":
        # Only delivery is missing; no authored norm decision is open.
        child["accepted_rows"] = [child["accepted_rows"][0]]
        child["document"] = {"final_revision_id": "", "draft_revision_id": "", "needs_document": True}
    elif blocked == "full_ready":
        closed = child["accepted_rows"][0]
        child["accepted_rows"] = [closed]
    question = "Проверь весь документ" if blocked == "non_plain" else "Продолжи"
    if blocked == "non_plain":
        requested = identity(store, question)
    before = deepcopy(child)
    def forbidden(*_args, **_kwargs):
        pytest.fail("this request must not mutate the existing operation queue")
    monkeypatch.setattr(store, "reopen_locators", forbidden)
    assert _continue(store, child, requested, owner=blocked != "not_owner", question=question) is child
    assert child == before


def _price_only(tmp_path):
    store, original = baseline(tmp_path)
    rows = deepcopy(original["accepted_rows"])
    rows[1].update(row_role="material", norm_code="", norm_status="", resource_code="owned-material",
                   open_gap="Exact current-book price is still missing.")
    rows[2].update(norm_code="MODEL-CLOSED", norm_status="EXACT_VERIFIED", open_gap="")
    current = store.replace_accepted_rows(original["job_id"], rows)
    material = current["accepted_rows"][1]
    store.record_packaging(current["job_id"], tool="build_lsr_workbook", revision_id="owned-price-only",
        draft=False, price_basis=current["task_context"]["price_basis"], financial_projection=[{
            "operation_id": material["operation_id"], "locator": material["source_row"],
            "row_role": "material", "status": "bound", "position_calculated": False,
            "open_reasons": ["price_missing"]}])
    requested, child = _child(store)
    return store, requested, child, material["operation_id"]


@pytest.mark.parametrize("stale", [None, "row_revision", "row_sha", "source_scope", "pricebook_sha"])
def test_only_matching_price_projection_can_reopen_the_exact_material_operation(tmp_path, monkeypatch, stale):
    store, requested, child, material_id = _price_only(tmp_path)
    before = deepcopy(child)
    snapshot = deepcopy(store.latest_financial_feedback(child["job_id"]))
    assert len(snapshot["records"]) == 1
    if stale == "row_revision": snapshot["records"][0]["revision"] += 1
    elif stale == "row_sha": snapshot["records"][0]["row_sha256"] = "e" * 64
    elif stale == "source_scope": snapshot["source_scope"]["source_sha256"] = "f" * 64
    elif stale == "pricebook_sha": snapshot["price_basis"]["pricebook_sha256"] = "d" * 64
    monkeypatch.setattr(store, "latest_financial_feedback", lambda _job: snapshot)
    current = _continue(store, child, requested)
    assert current["accepted_rows"] == before["accepted_rows"]
    assert current["evidence"] == before["evidence"] and current["query_cache"] == before["query_cache"]
    if stale is None:
        assert store.pending_research_operation_ids(current) == {material_id}
        assert store.pending_research_locators(current) == {SOURCE}
    else:
        assert current is child and not store.pending_research_operation_ids(current)


def test_source_confirmed_zero_is_not_a_new_norm_research_target(tmp_path, monkeypatch):
    from tests.test_lsr_zero_charge_observation_969 import _catalog, _row
    store, _ = baseline(tmp_path)
    requested, child = _child(store)
    child = deepcopy(child)
    child["accepted_rows"] = [_row("0")]
    child["held_packet"] = {}
    catalog = _catalog(tmp_path)
    def forbidden(*_args, **_kwargs):
        pytest.fail("source-confirmed zero needs neither a new norm nor a new charge")
    monkeypatch.setattr(store, "reopen_locators", forbidden)
    assert _continue(store, child, requested, catalog=catalog) is child


def test_mixed_zero_and_unresolved_resume_only_returns_the_unresolved_operation(tmp_path):
    from tests.test_lsr_zero_charge_observation_969 import _catalog, _row

    store = WorkbookResearchJobService(tmp_path / "zero and unresolved.sqlite")
    original = store.begin_or_resume(identity(store), task_context={
        "original_question": "Собери ЛСР, Санкт-Петербург, 3 квартал 2026",
        "price_basis": {"requested_region": "Санкт-Петербург", "requested": "3 квартал 2026"},
    })
    zero = _row("0")
    unresolved = {**_row(1, 3), "row_role": "unresolved", "norm_status": "MISSING",
                  "gap_reason": "no_suitable_candidate", "open_gap": "Literal model gap remains open."}
    store.record_packet(original["job_id"], sheet="S", packet_locators=["S!R2", "S!R3"],
        accepted_rows=[zero, unresolved], evidence=[{"global_evidence_id": "literal-source", "content": "Source"}],
        remaining=[], held_packet={"locators": ["S!R2", "S!R3"], "terminal_model_result_saved": True})
    store.record_artifact_kind(original["job_id"], declaration={"status": "declared", "artifact_kind": "lsr",
        "declarations": ["lsr"], "errors": [], "authority": "result"})
    store.finish(original["job_id"], status="complete")
    store.record_packaging(original["job_id"], tool="build_lsr_workbook", revision_id="before-zero-gap-resume",
        draft=False, price_basis={"actual_book": "sankt-peterburg_3kv2026", "pricebook_sha256": "b" * 64,
                                  "match": "exact"})
    requested, child = _child(store, "Добери нормы")
    before = deepcopy(child)
    catalog = _catalog(tmp_path, quantities=(0, 1))
    # The store assigns its durable IDs at record_packet, before any resume.
    saved = {row["source_row"]: row["operation_id"] for row in before["accepted_rows"]}

    current = _continue(store, child, requested, question="Добери нормы", catalog=catalog)

    assert store.pending_research_operation_ids(current) == {saved["S!R3"]}
    assert store.pending_research_locators(current) == {"S!R3"}
    assert saved["S!R2"] not in store.pending_research_operation_ids(current)
    assert current["accepted_rows"] == before["accepted_rows"]
    assert current["evidence"] == before["evidence"]
    assert current["task_context"]["price_basis"] == before["task_context"]["price_basis"]


def test_owned_plain_continue_never_adopts_or_resumes_a_newer_unclaimed_job(tmp_path):
    store, _ = baseline(tmp_path)
    requested, child = _child(store)
    newer = store.begin_or_resume(identity(store, "Уточнение инженера к документу"))
    store.pause(newer["job_id"], phase="operator")
    before = deepcopy(store.get(newer["job_id"]))
    events = store.list_events(newer["job_id"])
    with pytest.raises(app.HTTPException) as error:
        _continue(store, child, requested)
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "WORKBOOK_CONTINUATION_JOB_CHANGED"
    assert store.get(newer["job_id"]) == before
    assert store.list_events(newer["job_id"]) == events


def test_stale_owned_snapshot_cannot_replace_a_newer_operation_queue(tmp_path):
    store, _ = baseline(tmp_path)
    requested, child = _child(store)
    material = child["accepted_rows"][1]
    fresh = store.reopen_locators(child["job_id"], [SOURCE], preserve_accepted=True,
        operation_ids=[material["operation_id"]])
    before = deepcopy(fresh)
    events = store.list_events(child["job_id"])
    with pytest.raises(app.HTTPException) as error:
        _continue(store, child, requested)
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "WORKBOOK_CONTINUATION_STATE_CHANGED"
    assert store.get(child["job_id"]) == before
    assert store.list_events(child["job_id"]) == events


def test_new_issued_revision_invalidates_price_targets_read_from_an_older_snapshot(tmp_path, monkeypatch):
    store, requested, child, _ = _price_only(tmp_path)
    old = deepcopy(store.latest_financial_feedback(child["job_id"]))
    original_rows = deepcopy(child["accepted_rows"])
    def supersede(_job):
        store.record_packaging(child["job_id"], tool="build_lsr_workbook", revision_id="new-price-observation",
            draft=False, price_basis=child["task_context"]["price_basis"], financial_projection=[])
        return old
    monkeypatch.setattr(store, "latest_financial_feedback", supersede)
    with pytest.raises(app.HTTPException) as error:
        _continue(store, child, requested)
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "WORKBOOK_CONTINUATION_STATE_CHANGED"
    assert not store.list_events(child["job_id"], "locators_reopened")
    assert store.get(child["job_id"])["accepted_rows"] == original_rows


@pytest.mark.asyncio
async def test_actual_plain_chat_continuation_dispatches_a_bounded_turn_and_preserves_operation_ids(tmp_path, monkeypatch):
    from tests import test_model_rag_sheet_evidence_reads as fixture
    original_begin = WorkbookResearchJobService.begin_or_resume
    original_reopen = WorkbookResearchJobService.reopen_locators
    state = {}
    original_question = "Собери ЛСР; Санкт-Петербург, 3 квартал 2026"
    authored = [{"source_row": f"S!R{index}", "row_role": "work", "title": title, "unit": "m",
        "quantity": quantity, "norm_code": "", "norm_status": "MISSING", "evidence_refs": [],
        "gap_reason": "insufficient_source_data", "open_gap": "Literal model reason remains unchanged."}
        for index, title, quantity in [(2, "Cable A", 12), (3, "Cable B", 3)]]
    def begin(self, incoming, **kwargs):
        if not state:
            parent_identity = replace(incoming, question_sha256=hashlib.sha256(original_question.encode()).hexdigest())
            parent = original_begin(self, parent_identity, source_locators=["S!R2", "S!R3"],
                task_context={"original_question": original_question})
            parent = self.record_packet(parent["job_id"], sheet="S", packet_locators=["S!R2", "S!R3"],
                accepted_rows=authored, evidence=[], remaining=[],
                held_packet={"locators": ["S!R2", "S!R3"], "terminal_model_result_saved": True})
            self.record_artifact_kind(parent["job_id"], declaration=app.decode_model_artifact_kind("artifact_kind: lsr"))
            self.finish(parent["job_id"], status="complete")
            self.record_packaging(parent["job_id"], tool="build_lsr_workbook", revision_id="owned-before", draft=False)
            state.update(store=self, parent=deepcopy(self.get(parent["job_id"])), reopens=[])
        return original_begin(self, incoming, **kwargs)
    def reopen(self, job_id, *args, **kwargs):
        assert job_id in app._LIVE_SHEET_PASS_GATES, "claim must precede mutation of this running child"
        state["reopens"].append((job_id, deepcopy(kwargs)))
        return original_reopen(self, job_id, *args, **kwargs)
    def final(_requests):
        return json.dumps({"artifact_kind": "lsr", "rows": [
            {**row, "operation_id": saved["operation_id"], "expected_revision": saved["revision"]}
            for row, saved in zip(authored, state["parent"]["accepted_rows"], strict=True)]})
    monkeypatch.setattr(WorkbookResearchJobService, "begin_or_resume", begin)
    monkeypatch.setattr(WorkbookResearchJobService, "reopen_locators", reopen)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, question="Продолжи",
        query_declaration=json.dumps({"artifact_kind": "lsr", "queries": ["S!R2 — Cable A", "S!R3 — Cable B"]}),
        final_answer=final)
    assert len(run.requests) == 2 and not run.responses and run.queries == ["S!R2 — Cable A", "S!R3 — Cable B"]
    assert len(state["reopens"]) == 1, "a still-open result must not start another automatic research cycle"
    job = state["store"].get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert len(job["accepted_rows"]) == 2
    assert {row["operation_id"] for row in job["accepted_rows"]} == {
        row["operation_id"] for row in state["parent"]["accepted_rows"]}
    assert [row["gap_reason"] for row in job["accepted_rows"]] == [row["gap_reason"] for row in authored]
    assert [row["norm_status"] for row in job["accepted_rows"]] == ["MISSING", "MISSING"]
