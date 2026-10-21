"""A new remark is heard by the model; a plain resume keeps durable progress."""
import hashlib
import json

import pytest

from proxy.services.chat_evidence_application_service import (
    begin_workbook_chat_review,
    workbook_chat_review_needed,
    compact_estimator_draft_rows,
    profile_system_prompt,
)
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from proxy.services import chat_evidence_application_service as application
from types import SimpleNamespace


def job():
    return {"continues_job_id": "parent", "accepted_rows": [{"source_row": "Лист 1!R14"}],
            "task_context": {"original_question": "Собери ЛСР, Москва, 3 квартал 2026",
                             "artifact_kind_declaration": {"artifact_kind": "lsr"}}}


@pytest.mark.parametrize("question", ["Продолжи", "Продолжить!", "continue",
    "Добери нормы", "Найди недостающие нормы", "Продолжи незакрытые строки",
    "Продолжи это же задание по тому же прикреплённому документу.",
    "Собери ЛСР, Москва, 3 квартал 2026"])
def test_plain_resume_does_not_restart_model_research(question):
    assert not workbook_chat_review_needed(question, job())


@pytest.mark.parametrize("question", ["Добери нормы для строки 14", "Перепроверь позиции 14, 15",
    "Для первой работы изменились условия монтажа", "Продолжи, учти новое замечание"])
def test_freeform_remark_is_not_silently_repacked(question):
    assert workbook_chat_review_needed(question, job())


@pytest.mark.parametrize("question", ["Добери нормы", "Найди недостающие нормы"])
@pytest.mark.parametrize("kind", ["vor", "", "lsr"])
def test_norm_gap_command_does_not_silently_repack_a_vor(question, kind):
    from proxy.services.workbook_research_job_service import is_plain_continuation_question

    current = job()
    current["task_context"]["artifact_kind_declaration"] = {"artifact_kind": kind}
    assert is_plain_continuation_question(question, artifact_kind=kind) is (kind == "lsr")
    assert workbook_chat_review_needed(question, current) is (kind != "lsr")


def test_estimator_response_contract_requests_every_applicability_flag_without_a_skill():
    prompt = profile_system_prompt({"mode": "estimator", "prompt_text": "Select with evidence", "skill_text": ""}, strict=False)
    for field in ("action_match", "object_match", "condition_match", "unit_compatible", "composition_covers"):
        assert field in prompt
    assert "unknown" in prompt


def test_previous_decisions_keep_all_five_flags_and_citations_for_the_normal_model_pass():
    row = {"source_row": "Лист!R14", "evidence_refs": ["Q1.H1"],
           "action_match": "yes", "object_match": "no", "condition_match": "unknown",
           "unit_compatible": "yes", "composition_covers": "no"}
    projected, = compact_estimator_draft_rows([row])
    assert all(projected[key] == value for key, value in row.items())


def test_legacy_parent_without_task_text_still_hears_a_new_remark():
    current = job()
    current["task_context"]["original_question"] = "Перепроверь все нормы"
    event = {"payload": {"parent_question_sha256": hashlib.sha256("Собери ЛСР".encode()).hexdigest()}}
    assert workbook_chat_review_needed("Перепроверь все нормы", current, [event])


def test_review_is_durable_without_model_planning_and_preserves_operator_data(tmp_path):
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    identity = service.identity(session_id="s", attachment_id="read_doc", source_sha256="a" * 64,
        dataset_ids=[], profile_revision_id="p", model_identity="35b", question="Перепроверь все нормы")
    current = service.begin_or_resume(identity)
    rows = [{"source_row": "Лист 1!R14", "title": "Первая работа", "row_role": "work"},
            {"source_row": "Лист 1!R15", "title": "Вторая работа", "row_role": "work"}]
    service.record_packet(current["job_id"], sheet="Лист 1", packet_locators=[r["source_row"] for r in rows],
                          accepted_rows=rows, evidence=[], remaining=[])
    service.record_overrides(current["job_id"], {"Лист 1!R14": {"confirmed_price": 123}})
    service.finish(current["job_id"], status="complete")
    saved_rows = service.get(current["job_id"])["accepted_rows"]
    reopened = begin_workbook_chat_review(service, current, "Перепроверь все нормы", ["Лист 1!R14", "Лист 1!R15"])
    assert reopened["accepted_rows"] == saved_rows
    assert service.pending_research_operation_ids(reopened) == {row["operation_id"] for row in saved_rows}
    assert reopened["remaining"] == ["Лист 1!R14", "Лист 1!R15"]
    assert reopened["operator_overrides"]["Лист 1!R14"]["confirmed_price"] == 123
    events = service.list_events(current["job_id"], "locators_reopened")
    assert events[-1]["payload"]["prior_rows"][0]["title"] == "Первая работа"
    assert events[-1]["payload"]["chat_review"]["decision_author"] == "user"
    assert events[-1]["payload"]["chat_review"]["review_scope"] == "document"
    assert events[-1]["payload"]["prior_rows"] == saved_rows
    repeated = job()
    assert not workbook_chat_review_needed("Перепроверь все нормы", repeated, events)


def _review_checkpoint(tmp_path):
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    def identity(question):
        return service.identity(session_id="review", attachment_id="read_review", source_sha256="b" * 64,
            dataset_ids=[], profile_revision_id="p", model_identity="35b", question=question)
    job = service.begin_or_resume(identity("Собери ВОР"))
    service.record_packet(job["job_id"], sheet="Схема", packet_locators=["Схема!R14", "Схема!R15"],
        accepted_rows=[{"source_row": "Схема!R14", "row_role": "work", "title": "Монтаж",
                        "evidence_refs": ["Q1.H1"], "evidence_bindings": {"Q1.H1": "saved-card"}},
                       {"source_row": "Схема!R15", "row_role": "material", "title": "Материал"}],
        evidence=[], remaining=[])
    service.finish(job["job_id"], status="complete")
    published = service.get(job["job_id"])["accepted_rows"]
    review = service.begin_or_resume(identity("Исправь объёмы по исходнику"))
    review = begin_workbook_chat_review(service, review, "Исправь объёмы по исходнику", ["Схема!R14", "Схема!R15"])
    assert review["accepted_rows"] == published
    return service, identity, review, published


def test_reopened_operation_can_keep_its_published_identity(tmp_path):
    service, _, review, published = _review_checkpoint(tmp_path)
    prior = service.list_events(review["job_id"], "locators_reopened")[-1]["payload"]["prior_rows"]
    changed = {**published[0], "title": "Уточнённый монтаж"}
    errors = application.validate_model_rag_result_structure([changed], [], expected_source_rows=1,
        validate_evidence_refs=False, existing_operation_rows=review["accepted_rows"], review_operation_rows=prior)
    assert not any("operation_" in error for error in errors)
    for bad, prefix in (({**changed, "operation_id": "invented"}, "unknown_operation_id:"),
                        ({**changed, "source_row": "Схема!R15"}, "operation_source_mismatch:")):
        errors = application.validate_model_rag_result_structure([bad], [], expected_source_rows=1,
            validate_evidence_refs=False, existing_operation_rows=[], review_operation_rows=prior)
        assert any(error.startswith(prefix) for error in errors)
    assert published[0]["title"] == "Монтаж"
    saved = service.record_packet(review["job_id"], sheet="Схема", packet_locators=["Схема!R14"],
        accepted_rows=[changed], evidence=[], remaining=["Схема!R15"])
    assert saved["accepted_rows"][0]["operation_id"] == published[0]["operation_id"]
    assert saved["accepted_rows"][0]["revision"] == published[0]["revision"] + 1
    assert len(saved["accepted_rows"]) == 2
    assert saved["accepted_rows"][1] == published[1]
    assert service.pending_research_operation_ids(saved) == {published[1]["operation_id"]}


def test_review_resume_retains_instruction_identity_and_exact_cited_card(tmp_path):
    service, identity, review, published = _review_checkpoint(tmp_path)
    resumed = service.begin_or_resume(identity("Продолжи"))
    assert resumed["continues_job_id"] == review["job_id"]
    assert service.list_events(resumed["job_id"], "locators_reopened") == []
    context = application.workbook_chat_review_context(service, resumed)
    assert context["prior_rows"] == published
    assert context["message"] == "Исправь объёмы по исходнику"
    card = SimpleNamespace(content="Полное прежнее доказательство", doc_id="card", doc_name="cards",
        meta={"global_evidence_id": "saved-card", "model_evidence_ref": "Q1.H1"})
    payload, retained = application.model_rag_prior_page_context([], [card], review_rows=context["prior_rows"],
        review_instruction=context["message"])
    assert payload["prior_model_decisions"][0]["operation_id"] == published[0]["operation_id"]
    assert payload["review_instruction"] == context["message"]
    assert retained == [card]
    assert payload["previously_shown_cited_evidence"][0]["content"] == card.content


def test_new_remark_during_partial_review_does_not_lose_unreviewed_baseline(tmp_path):
    service, identity, review, published = _review_checkpoint(tmp_path)
    service.record_packet(review["job_id"], sheet="Схема", packet_locators=["Схема!R14"],
        accepted_rows=[{**published[0], "title": "Исправленный монтаж"}], evidence=[], remaining=["Схема!R15"])
    next_review = service.begin_or_resume(identity("Также уточни материал"))
    begin_workbook_chat_review(service, next_review, "Также уточни материал", ["Схема!R14", "Схема!R15"])
    prior = service.list_events(next_review["job_id"], "locators_reopened")[-1]["payload"]["prior_rows"]
    assert len(prior) == 2
    assert prior[0]["title"] == "Исправленный монтаж"
    assert prior[1] == published[1]
    assert service.get(next_review["job_id"])["accepted_rows"] == prior


def test_omitted_review_operation_stays_durable_pending_until_an_explicit_model_reply(tmp_path):
    service, identity, review, published = _review_checkpoint(tmp_path)
    service.record_packet(review["job_id"], sheet="Схема", packet_locators=["Схема!R14", "Схема!R15"],
        accepted_rows=[published[0]], evidence=[], remaining=[])
    current = service.get(review["job_id"])
    assert current["accepted_rows"] == published
    assert current["remaining"] == [published[1]["source_row"]]
    assert service.pending_research_operation_ids(current) == {published[1]["operation_id"]}
    service.pause(review["job_id"], remaining=[], phase="model_result_transport_pending")
    next_review = service.begin_or_resume(identity("Проверь готовый результат"))
    begin_workbook_chat_review(service, next_review, "Проверь готовый результат", ["Схема!R14", "Схема!R15"])
    prior = service.chat_review_context(next_review["job_id"])["prior_rows"]
    assert prior == published
    assert service.get(next_review["job_id"])["accepted_rows"] == published


def test_operator_confirmations_survive_new_review_and_resume_job(tmp_path):
    service, identity, review, published = _review_checkpoint(tmp_path)
    service.record_overrides(review["job_id"], {"Схема!R14": {"confirmed_price": 12.5}})
    resumed = service.begin_or_resume(identity("Продолжи"))
    assert resumed["operator_overrides"]["Схема!R14"]["confirmed_price"] == 12.5
    reopened = begin_workbook_chat_review(service, resumed, "Уточни условия", ["Схема!R14", "Схема!R15"])
    assert reopened["operator_overrides"] == resumed["operator_overrides"]


def test_review_response_contract_is_full_while_normal_page_remains_delta():
    rows = [{"source_row": "S!R2", "operation_id": "old-operation", "revision": 4,
             "row_role": "work", "title": "Literal old title", "quantity": 3.2, "unit": "m2"}]
    normal, _ = application.model_rag_prior_page_context(rows, [])
    review, _ = application.model_rag_prior_page_context([], [], review_rows=rows,
        review_instruction="Recheck the offered operation")
    assert "текущая область обновления — новые и изменённые операции этого пакета" in normal["evidence_continuation_instruction"]
    assert "Неизменённые операции и цитаты остаются в документе" in normal["evidence_continuation_instruction"]
    instruction = review["evidence_continuation_instruction"]
    assert "текущая область результата — все предложенные прежние операции" in instruction
    assert "expected_revision" in instruction and "дословно" in instruction
    for metadata in (normal["evidence_continuation_instruction"], instruction):
        assert "Верни" not in metadata and "верни" not in metadata
    assert "текущая область обновления" not in instruction
    assert "Неизменённые операции и цитаты остаются в документе" not in instruction
    assert [{key: projected[key] for key in original}
            for original, projected in zip(rows, review["prior_model_decisions"])] == rows
    shared = application.profile_system_prompt({"mode": "estimator", "prompt_text": "Evidence only"}, strict=False)
    tail = application.sheet_pass_question_tail("Recheck", sheet="S", sheet_index=1, sheet_count=1,
        remaining_work=["S!R2"])
    for prompt in (shared, tail):
        assert "При обычном продолжении" in prompt
        assert "При явном пересмотре" in prompt
        assert "все предложенные прежние операции" in prompt
        assert "верни" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("cut", [False, True])
@pytest.mark.parametrize("repair_query_transport", [False, True])
async def test_actual_review_preserves_accepted_baseline_until_a_valid_model_revision(tmp_path, monkeypatch, cut, repair_query_transport):
    from test_model_rag_sheet_evidence_reads import _run_sheet
    from proxy.services.openai_compatible_transport_service import InferenceResponse

    run = await _run_sheet(tmp_path, monkeypatch, reads=True, json_final=True)
    store = WorkbookResearchJobService()
    job_id = run.result["retrieval_trace"]["workbook_research_job"]["job_id"]
    published = store.get(job_id)["accepted_rows"]
    assert len(published) == 2
    reopened = application.begin_workbook_chat_review(store, store.get(job_id), "Recheck these operations",
        [row["source_row"] for row in published])
    assert reopened["accepted_rows"] == published
    assert store.pending_research_operation_ids(reopened) == {row["operation_id"] for row in published}
    fields = ("source_row", "row_role", "title", "unit", "quantity", "norm_code", "resource_code", "evidence_refs", "operation_id")
    authored = [{**{key: row[key] for key in fields if key in row}, "expected_revision": row["revision"]}
                for row in published]
    authored[1]["title"] = "Model changed second title"
    frame_rows = []

    def prior_in_frame(frame):
        found = None
        decoder = json.JSONDecoder()
        for message in frame:
            content = str(message.get("content") or "")
            for index, char in enumerate(content):
                if char != "{":
                    continue
                try:
                    candidate, _ = decoder.raw_decode(content, index)
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, dict) and "prior_model_decisions" in candidate:
                    found = candidate
                    break
            if found is not None:
                break
        assert found is not None
        return found

    def review_response():
        frame = run.requests[-1].messages
        found = prior_in_frame(frame)
        assert "текущая область результата — все предложенные прежние операции" in found["evidence_continuation_instruction"]
        assert "Верни" not in found["evidence_continuation_instruction"] and "верни" not in found["evidence_continuation_instruction"]
        assert "Неизменённые операции и цитаты остаются в документе" not in found["evidence_continuation_instruction"]
        assert found["review_instruction"] == "Recheck these operations"
        assert "При явном пересмотре верни все предложенные прежние операции" in str(frame)
        offered = found["prior_model_decisions"]
        assert [row["operation_id"] for row in offered] == [row["operation_id"] for row in published]
        for prior, actual in zip(published, offered):
            assert {key: actual.get(key) for key in (*fields, "revision")} == {
                key: prior.get(key) for key in (*fields, "revision")}
        frame_rows.extend(offered)
        text = '{"artifact_kind":"lsr","rows":[' if cut else json.dumps({"artifact_kind": "lsr", "rows": authored})
        return InferenceResponse(text=text, tool_calls=(), finish_reason="length" if cut else "stop", usage={})

    literal_queries = ["S!R2 literal query", "S!R3 literal query"]
    def query_response():
        # Inspect the actual governed query (and repair), retaining the same
        # literal review baseline that the answer receives below.
        delivered = "\n".join(str(message.get("content") or "") for message in run.requests[-1].messages)
        assert "Для изменённой прежней операции верни" not in delivered
        assert "Верни только новые и изменённые операции этого пакета" not in delivered
        prior_context = prior_in_frame(run.requests[-1].messages)
        assert prior_context["review_instruction"] == "Recheck these operations"
        assert "верни" not in prior_context["evidence_continuation_instruction"]
        for prior in published:
            assert prior["operation_id"] in delivered
        return InferenceResponse(text=json.dumps({"artifact_kind": "lsr", "queries": literal_queries}),
                                 tool_calls=(), finish_reason="stop", usage={})
    # A mixed metadata/plain-query response needs the existing format repair.
    # Neither that repair nor valid transport may erase the reopened operations.
    initial_responses = ([InferenceResponse(
        text="artifact_kind: lsr\n" + "\n".join(literal_queries),
        tool_calls=(), finish_reason="stop", usage={},
    )] if repair_query_transport else [])
    run.responses[:] = [*initial_responses, query_response, review_response]
    calls_before = len(run.requests)
    result = await run.resume_same_request()
    current = store.get(job_id)
    assert frame_rows and len(run.requests) == calls_before + 2 + int(repair_query_transport) and not run.responses
    if cut:
        assert current["accepted_rows"] == published
        assert store.pending_research_operation_ids(current) == {row["operation_id"] for row in published}
        assert set(current["remaining"]) == {row["source_row"] for row in published}
        assert result["retrieval_trace"]["model_result_transport_diagnostics"]
        assert len(run.executions) == 1
    else:
        assert len(current["accepted_rows"]) == 2 and current["remaining"] == []
        for returned, expected in zip(current["accepted_rows"], authored):
            assert {key: returned.get(key) for key in fields} == {key: expected.get(key) for key in fields}
            changed = expected["operation_id"] == authored[1]["operation_id"]
            assert returned["revision"] == expected["expected_revision"] + int(changed)
        assert store.pending_research_operation_ids(current) == set()
        assert len(run.executions) == 2
    prior_event = store.list_events(job_id, "locators_reopened")[-1]
    assert prior_event["payload"]["prior_rows"] == published
