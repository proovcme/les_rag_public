"""Workbook rows cite issued Q/H cards; ordinary source labels retain their scope."""
from __future__ import annotations

import copy
import json

import pytest

from proxy.services import chat_evidence_application_service as app
from tests.test_model_rag_sheet_evidence_reads import _run_sheet, RESOURCE_A, RESOURCE_B
from tests.test_chat_evidence_application_service import (
    test_actual_chat_shadow_failure_preserves_legacy_answer_history_and_model_count as _run_actual_chat,
)


_OLD_SYSTEM_CITATIONS = "Ссылки оформляй номерами из заголовков [Источник N]"
_OLD_QUESTION_CITATIONS = "Не выдумывай факты и используй только существующие номера [Источник N]"


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_real_workbook_and_native_read_messages_have_one_row_citation_contract(tmp_path, monkeypatch, variant):
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant)
    assert len(run.requests) == 4 and not run.responses
    # The actual governed requests include the complete native read history,
    # source rows and full returned cards, not a synthetic prompt fragment.
    for request in run.requests[1:]:
        messages = "\n".join(str(message.get("content") or "") for message in request.messages)
        assert _OLD_SYSTEM_CITATIONS not in messages
        assert _OLD_QUESTION_CITATIONS not in messages
        assert "В evidence_refs строк результата используй буквальные Qx.Hy" in messages
        assert "[Источник N] не заменяет Qx.Hy в evidence_refs" in messages
        assert "Собери ЛСР; ВОР не создавай" in messages
        assert "S!R2" in messages and "S!R3" in messages
    final = run.requests[-1]
    assert any(message.get("role") == "tool" for message in final.messages)
    assert "fixture-resource-21" in "\n".join(str(message.get("content") or "") for message in final.messages)
    assert run.executions[0][1]["status"] == "complete"
    assert run.executions[0][1]["confirmed_amount"] == 1800
    assert [row["resource_code"] for row in run.executions[0][0]["args"]["decisions"]] == [RESOURCE_A, RESOURCE_B]


@pytest.mark.parametrize("strict", [False, True])
def test_workbook_system_contract_does_not_rewrite_saved_profile_or_skill(monkeypatch, strict):
    monkeypatch.setattr(app, "model_runtime_facts", lambda _profile: {"origin": "application"})
    snapshot = {"mode": "estimator", "prompt_text": "Literal saved profile: [Источник N].",
                "skill_text": "Literal saved skill. Q/H examples are not selections."}
    before = copy.deepcopy(snapshot)
    prompt = app.profile_system_prompt(snapshot, strict=strict, purpose="workbook_result")
    assert prompt.startswith(snapshot["prompt_text"] + "\n\n")
    assert snapshot["skill_text"] in prompt
    assert "В evidence_refs строк результата используй буквальные Qx.Hy" in prompt
    assert "[Источник N] не заменяет Qx.Hy в evidence_refs" in prompt
    assert _OLD_SYSTEM_CITATIONS not in prompt
    assert "проектные факты к [Источник N]" not in prompt
    assert snapshot == before


@pytest.mark.parametrize("purpose", ["answer", "source_read", "query"])
@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("mode", ["search", "estimator"])
def test_non_workbook_profile_citation_contract_remains_literal(monkeypatch, purpose, strict, mode):
    monkeypatch.setattr(app, "model_runtime_facts", lambda _profile: {"origin": "application"})
    snapshot = {"mode": mode, "prompt_text": "Literal saved profile.", "skill_text": "Literal saved skill."}
    prompt = app.profile_system_prompt(snapshot, strict=strict, purpose=purpose)
    assert prompt.startswith("Literal saved profile.\n\nФакты выполнения от приложения:\n"
                             + json.dumps({"origin": "application"}, ensure_ascii=False))
    assert snapshot["skill_text"] in prompt
    assert "В evidence_refs строк результата используй буквальные Qx.Hy" not in prompt
    if purpose == "query":
        assert app._MODEL_RAG_QUERY_PHASE_INSTRUCTION in prompt
    elif strict:
        assert "проектные факты к [Источник N]" in prompt
    else:
        assert _OLD_SYSTEM_CITATIONS in prompt


@pytest.mark.asyncio
async def test_actual_ordinary_chat_keeps_source_numbering(monkeypatch, tmp_path):
    async def setup(request, runtime, boundary):
        transport = runtime.model_connection_transport(None, None)
        result = await app.run_chat_evidence_application(request, runtime, boundary)
        assert result["answer"]
        final_messages = "\n".join(str(message.get("content") or "") for message in transport.requests[-1].messages)
        assert _OLD_SYSTEM_CITATIONS in final_messages
        assert _OLD_QUESTION_CITATIONS in final_messages
        assert "В evidence_refs строк результата используй буквальные Qx.Hy" not in final_messages

    await _run_actual_chat(monkeypatch, tmp_path, "active", application_setup=setup)


def test_sheet_question_keeps_scope_and_identity_with_issued_card_citations():
    prompt = app.sheet_pass_question_tail(
        "Literal original question", sheet="Generic", sheet_index=2, sheet_count=7,
        remaining_work=["Generic!R30"], reasoning_enabled=True,
    )
    assert _OLD_QUESTION_CITATIONS not in prompt
    assert "evidence_refs" in prompt and "Qx.Hy" in prompt
    for literal in ("Literal original question", "Generic!R30", "operation_id", "expected_revision",
                    "неизменённые операции сохраняются приложением", "Не обрабатывай другие листы"):
        assert literal in prompt


@pytest.mark.parametrize("authored,expected", [(["[Источник 1]"], []), (["Q1.H1"], ["Q1.H1"])])
def test_citation_decoder_still_requires_an_issued_card_reference(authored, expected):
    assert app.extract_model_evidence_refs(authored) == expected
