"""A chosen preview needs an available exact READ before a terminal data gap."""
from __future__ import annotations

import copy
import json

import pytest

from proxy.services.lsr_norm_quality_gate_service import lsr_result_table_instruction
from proxy.services.model_evidence_read_contract import MODEL_EVIDENCE_READ_INSTRUCTION, model_evidence_read_tool_schemas
from proxy.services.model_lsr_result_contract import (
    VOR_RESULT_FIELDS, model_lsr_resource_decision_instruction, model_lsr_result_field_instruction,
)


_READ_ATTEMPT = (
    "Для выбранного уже показанного кандидата с неполным составом или расходом "
    "выполни доступное read_norm_card до итоговых строк"
)
_GAP_AFTER_READ = "Терминальный пробел допустим только после чтения без нужных данных"
_FULL_CODE = "norm_code дословно копируй целиком вместе с конечным вариантом"
_CARD_REFERENCE = "В evidence_refs цитируй буквальный Qx.Hy выбранной карточки"
_SOURCE_PROVENANCE = "source_id/source_<id> обозначает документ или таблицу с несколькими нормами"


def test_chosen_preview_must_attempt_available_read_before_terminal_gap():
    instruction = MODEL_EVIDENCE_READ_INSTRUCTION
    assert _READ_ATTEMPT in instruction
    assert _GAP_AFTER_READ in instruction
    assert instruction.index(_READ_ATTEMPT) < instruction.index(_GAP_AFTER_READ)
    assert "либо явно оставь этот конкретный пробел" not in instruction


def test_read_policy_preserves_real_failures_unknown_conditions_and_complete_cards():
    instruction = MODEL_EVIDENCE_READ_INSTRUCTION
    assert "либо фактической недоступности инструмента/остановки" in instruction
    assert "по бюджету или контексту" in instruction
    assert "неизвестные условия объекта сохраняй отдельно" in instruction
    assert "при достаточном уже показанном содержании" in instruction
    assert "повторное чтение не требуется" in instruction
    assert "Отсутствие цены не означает отсутствие нормы" in instruction


def test_result_contract_distinguishes_full_card_identity_from_table_provenance():
    instruction = model_lsr_result_field_instruction()
    assert _FULL_CODE in instruction
    assert "а не заголовок таблицы" in instruction
    identity_instruction = model_lsr_resource_decision_instruction()
    assert _CARD_REFERENCE in identity_instruction
    assert _SOURCE_PROVENANCE in identity_instruction
    assert "не заменяет идентификатор конкретной карточки" in identity_instruction
    assert instruction in lsr_result_table_instruction(artifact_kind="lsr")
    duplicated = "Поля ВОР: " + ", ".join(VOR_RESULT_FIELDS) + ". "
    assert instruction.count(duplicated) == 1
    assert instruction.replace(duplicated, "", 1) in lsr_result_table_instruction()
    # The clarification explains technical identity; it still leaves selection
    # and applicability to the author of the result.
    assert "применимость выбираешь ты" in instruction
    assert "Неизвестное: unknown" in instruction


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_actual_answer_and_native_continuations_keep_policy_and_literal_decisions(
    tmp_path, monkeypatch, variant,
):
    from tests.test_model_rag_sheet_evidence_reads import _run_sheet

    run = await _run_sheet(
        tmp_path, monkeypatch, reads=True, variant=variant,
        norm_ref_read="Q1.H1", temperature=0.65,
    )
    assert not run.responses and len(run.requests) == 4
    assert len(run.exact_reads) == 1 and len(run.executions) == 1
    before = copy.deepcopy(run.executions[0][0]["args"]["decisions"])
    for request in run.requests[1:]:
        delivered = "\n".join(str(message.get("content", "")) for message in request.messages)
        assert _READ_ATTEMPT in delivered
        assert _GAP_AFTER_READ in delivered
        assert _FULL_CODE in delivered
        assert _CARD_REFERENCE in delivered
        assert _SOURCE_PROVENANCE in delivered
        assert "Answer only from shown evidence." in delivered
        assert request.temperature == 0.65
        readers = model_evidence_read_tool_schemas()
        assert list(request.tools)[:len(readers)] == readers
        assert [tool["function"]["name"] for tool in list(request.tools)[len(readers):]] == [
            "build_vor_workbook", "build_lsr_workbook"]
    # The application neither inserts a READ nor converts source provenance
    # into a card selection; it executes exactly the model-authored native call.
    native_calls = [call for message in run.requests[2].messages
                    for call in message.get("tool_calls", ())]
    exact_call = next(call for call in native_calls if call["function"]["name"] == "read_norm_card")
    assert json.loads(exact_call["function"]["arguments"]) == {"evidence_ref": "Q1.H1"}
    queries = "\n".join(str(message.get("content", "")) for message in run.requests[0].messages)
    assert _READ_ATTEMPT not in queries and _FULL_CODE not in queries
    assert [(row["source_row"], row["unit"], row["quantity"]) for row in before] == [
        ("S!R2", "m", 12), ("S!R3", "m", 3),
    ]
    assert run.executions[0][0]["args"]["decisions"] == before
