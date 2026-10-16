"""Shared resume evidence describes state; only the answer asks for decisions."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services.context_governor_service import ContextKind
from proxy.services.model_execution_preset_service import ModelExecutionPreset


USER_REVIEW = '\tВерни уточнённую работу «Ω», сохрани объём 3,2.\nЭто буквальное замечание пользователя. '


def _prior(review):
    row = {"source_row": "Схема Ω!R14", "operation_id": "saved-operation", "revision": 4,
           "row_role": "work", "title": 'Literal "Ω" operation', "quantity": 3.2, "unit": "m2",
           "norm_code": "01-02-003-04", "norm_status": "NEEDS_RESEARCH",
           "open_gap": "Literal condition question", "evidence_refs": ["Q1.H6"],
           "evidence_bindings": {"Q1.H6": "saved-card"}}
    card = SimpleNamespace(content="Literal complete cited card Ω\nsource edition retained.",
                           doc_name="cards", doc_id="card", meta={
                               "global_evidence_id": "saved-card", "model_evidence_ref": "Q1.H6"})
    before = deepcopy(row)
    payload, retained = app.model_rag_prior_page_context(
        [] if review else [row], [card], review_rows=[row] if review else (),
        review_instruction=USER_REVIEW if review else "")
    assert row == before and retained == [card]
    assert {key: payload["prior_model_decisions"][0][key] for key in row} == row
    assert payload["previously_shown_cited_evidence"] == [{
        "ref": "Q1.H6", "global_evidence_id": "saved-card", "content": card.content}]
    if review:
        assert payload["review_instruction"] == USER_REVIEW
    else:
        assert "review_instruction" not in payload
    return payload


def _assert_neutral(payload, review):
    instruction = payload["evidence_continuation_instruction"]
    # Check application metadata only. The user's remark and literal source
    # may legitimately contain these words and must never be filtered.
    for command in ("Верни", "верни", "Сохрани", "скопируй", "Проверь", "оставь"):
        assert command not in instruction
    for field in ("prior_model_decisions", "operation_id", "revision", "expected_revision",
                  "work_row", "prior_result_structural_facts", "code_in_refs=null"):
        assert field in instruction
    assert "не вердикт о применимости нормы" in instruction
    assert "Код не изменял предметные решения" in instruction
    if review:
        assert "все предложенные прежние операции" in instruction
        assert "включая неизменённые" in instruction and "дословно" in instruction
        assert "Отсутствие прежней операции в ответе не удаляет её" in instruction
        assert "сохранённое решение остаётся в документе" in instruction
        assert "запрос его пересмотра остаётся открытым" in instruction
    else:
        assert "новые и изменённые операции этого пакета" in instruction
        assert "Неизменённые операции и цитаты остаются в документе" in instruction


@pytest.mark.parametrize("review", [False, True])
def test_resume_metadata_preserves_literal_decisions_but_does_not_request_result_rows(review):
    _assert_neutral(_prior(review), review)


def _evidence(packet):
    return [obj.payload for section in packet.sections
            if section.kind in {ContextKind.EVIDENCE, ContextKind.CURRENT_READ_FRAME}
            for obj in section.objects]


@pytest.mark.parametrize("review", [False, True])
def test_query_repair_and_answer_keep_the_same_resume_data_with_distinct_output_contracts(review):
    prior = _prior(review)
    source = {"requested_source_rows": ["Схема Ω!R14"],
              "reference_source_rows": ["Схема Ω!R1"],
              "source_quantity_cells": [{"source_row": "Схема Ω!R14", "quantity": None, "unit": "m2"}],
              "source_line": 'Схема Ω!R14: Literal "Ω" operation | m2 | quantity unknown'}
    original = "Собери ЛСР, Санкт-Петербург, 3 квартал 2026."
    evidence = [source, prior]
    before = deepcopy(evidence)
    snapshot = {"mode": "estimator", "prompt_text": "Literal saved profile"}
    preset = ModelExecutionPreset("resume-scope", "fixture", 30000, 8192, 1000,
                                  1, 5, 6, 1, False, ("fixture",))
    prefix = app.profile_system_prompt(snapshot, strict=False, purpose="query")
    prefix += "\n\n" + app.sheet_pass_query_instruction(snapshot, sheet="Схема Ω", sheet_index=1, sheet_count=2)
    common = dict(preset=preset, profile_prefix=prefix,
                  request_payload={"question": original}, required_evidence=evidence)
    _, first = app.govern_model_query_messages(retrieval_trace={}, purpose="query", **common)
    rejection = app.model_query_repair_attempt_data('{"calls":[]}', finish_reason="stop", parse_diagnostics={})
    repair_messages, repaired = app.govern_model_query_messages(retrieval_trace={}, purpose="query-repair",
        rejected_attempt=rejection, first_source_packet=first, **common)
    assert _evidence(first) == _evidence(repaired) == evidence
    assert evidence == before
    for packet in (first, repaired):
        _assert_neutral(_evidence(packet)[1], review)
        assert _evidence(packet)[0]["source_quantity_cells"][0]["quantity"] is None
    assert app._MODEL_RAG_QUERY_FORMAT_CONTRACT in repair_messages[0]["content"]
    assert original in repair_messages[-1]["content"]
    if review:
        assert json.dumps(USER_REVIEW, ensure_ascii=False) in repair_messages[-1]["content"]

    answer_prefix = app.profile_system_prompt(snapshot, strict=False, purpose="workbook_result")
    tail = app.sheet_pass_question_tail(original, sheet="Схема Ω", sheet_index=1, sheet_count=2,
                                       remaining_work=source["requested_source_rows"])
    answer_messages, answered = app.govern_inference_messages(preset=preset,
        profile_prefix=answer_prefix, request_payload=tail, required_evidence=evidence)
    assert _evidence(answered) == evidence and evidence == before
    assert "Для ещё не решённых исходных строк текущего пакета дай решения" in tail
    assert "При обычном продолжении" in tail and "верни только новые" in tail
    assert "При явном пересмотре верни все предложенные прежние операции" in tail
    assert "Для прежней операции верни operation_id" in answer_prefix + tail
    assert "expected_revision из её revision" in answer_prefix + tail
    assert original in answer_messages[-1]["content"]
