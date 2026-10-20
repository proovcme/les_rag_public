"""Context labels describe the actual packet without choosing professional work."""
from copy import deepcopy
import json

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services.context_governor_service import ContextKind
from tests.test_model_current_read_frame import _preset
from tests.test_model_query_resume_scope import _prior, USER_REVIEW
from tests.test_vor_task_instruction_955 import _indexed_work, _work_index


FALSE_NEW_PACKET_LEADS = ("Это следующая страница", "для тех же строк")


def _assert_not_false_same_packet_label(payload):
    instruction = payload["evidence_continuation_instruction"]
    assert all(phrase not in instruction for phrase in FALSE_NEW_PACKET_LEADS)
    assert "новые и изменённые операции этого пакета" in instruction
    assert "Неизменённые операции и цитаты остаются в документе" in instruction


def test_new_packet_with_fresh_evidence_and_only_work_index_is_not_a_same_row_replay_975():
    parent = _indexed_work("Previous!R2", operation_id="literal-parent", quantity=0)
    before = deepcopy(parent)
    prior, retained = app.model_rag_prior_page_context([], [], full_result_rows=[parent])
    assert prior["prior_model_decisions"] == [] and retained == []
    assert _work_index(prior) == [{key: parent.get(key) for key in prior["accepted_work_index"]["columns"]}]
    assert "не запрашивает пересмотр закрытых работ" in prior["accepted_work_index_scope"]
    _assert_not_false_same_packet_label(prior)
    current, _ = app.model_rag_prior_page_context([parent], [])
    assert prior["evidence_continuation_instruction"] != current["evidence_continuation_instruction"]
    source = {"requested_source_rows": ["New!R9"], "literal_source": "new packet literal source"}
    # The forbidden application label can also occur in literal source/card text;
    # fixing metadata must not filter or rewrite this evidence.
    card = {"content": "Это следующая страница для тех же строк — literal source quotation Ω",
            "model_evidence_ref": "Q7.H2", "source_ref": "immutable-new-evidence"}
    evidence = [source, prior, card]
    frozen = deepcopy(evidence)
    messages, packet = app.govern_inference_messages(preset=_preset(), profile_prefix="profile",
        request_payload="current original question", required_evidence=evidence)
    included = [obj.payload for section in packet.sections if section.kind == ContextKind.EVIDENCE
                for obj in section.objects]
    assert included == frozen and evidence == frozen and parent == before
    assert json.dumps(card, ensure_ascii=False, sort_keys=True, separators=(",", ":")) in messages[-1]["content"]


def test_actual_same_packet_page_keeps_literal_prior_operations_and_cited_body_975():
    payload = _prior(False)
    frozen = deepcopy(payload)
    assert payload["prior_model_decisions"] and payload["previously_shown_cited_evidence"]
    assert "review_instruction" not in payload
    assert "новые и изменённые операции этого пакета" in payload["evidence_continuation_instruction"]
    assert "все предложенные прежние операции этого пакета" not in payload["evidence_continuation_instruction"]
    messages, packet = app.govern_inference_messages(preset=_preset(), profile_prefix="profile",
        request_payload="current question", required_evidence=[payload, {"new_card": "whole next-page body"}])
    assert payload == frozen
    assert next(obj.payload for section in packet.sections if section.kind == ContextKind.EVIDENCE
                for obj in section.objects) == frozen
    assert "whole next-page body" in messages[-1]["content"]


def test_explicit_review_keeps_full_offered_scope_instead_of_index_only_or_delta_975():
    payload = _prior(True)
    assert payload["review_instruction"] == USER_REVIEW
    assert payload["prior_model_decisions"] and payload["previously_shown_cited_evidence"]
    instruction = payload["evidence_continuation_instruction"]
    assert "все предложенные прежние операции этого пакета" in instruction
    assert "включая неизменённые" in instruction and "expected_revision" in instruction
    assert "Отсутствие прежней операции в ответе не удаляет её" in instruction
    assert "текущая область обновления" not in instruction
    assert all(phrase not in instruction for phrase in FALSE_NEW_PACKET_LEADS)


@pytest.mark.asyncio
async def test_later_query_and_answer_keep_index_but_truthfully_label_empty_current_prior_975(tmp_path, monkeypatch):
    from tests import test_model_rag_sheet_evidence_reads as fixture
    rows = [_indexed_work("S!R2", operation_id="", norm_code="", norm_status="", unit="m", quantity=12),
            _indexed_work("S!R3", operation_id="", norm_code="", norm_status="", unit="m", quantity=3)]
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, packet_count=2,
        query_declaration=json.dumps({"artifact_kind": "vor", "queries": []}),
        final_answer=json.dumps({"artifact_kind": "vor", "rows": rows}))
    contexts = []
    for request in run.requests[2:]:
        for message in request.messages:
            for line in str(message["content"]).splitlines():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict) and item.get("accepted_work_index"):
                    contexts.append(item)
    assert len(contexts) == len(run.requests) - 2 and not run.responses
    for payload in contexts:
        assert payload["prior_model_decisions"] == []
        assert [row["source_row"] for row in _work_index(payload)] == ["S!R2", "S!R3"]
        assert [row["quantity"] for row in _work_index(payload)] == [12, 3]
        assert all(row["operation_id"] for row in _work_index(payload))
        _assert_not_false_same_packet_label(payload)
