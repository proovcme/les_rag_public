"""A file-export carrier remains distinct from a saved prose profile."""
import copy
import json

import pytest

from proxy.services.chat_evidence_application_service import (
    govern_inference_messages,
    profile_system_prompt,
)
from proxy.services.context_governor_service import ContextKind
from proxy.services.model_execution_preset_service import ModelExecutionPreset


_CARRIER_MARKER = "Контракт экспорта ВОР/ЛСР:"


def _saved_profile(**overrides):
    return {
        "mode": "estimator",
        "revision_id": "user:profile:estimator:saved",
        "prompt_text": "Пиши без служебных терминов и JSON, если JSON не просили.",
        "skill_text": "Профессиональные решения принимает модель по источникам.",
        "model_policy": {"temperature": 0.7, "reasoning_enabled": False},
        **overrides,
    }


@pytest.mark.parametrize("profile", [
    _saved_profile(),
    _saved_profile(mode="agent", tabular_estimator_path=True),
    _saved_profile(mode="engineer", effective_capability_bridges=[
        "tabular_attachment_estimator_path_v1"]),
])
@pytest.mark.parametrize("strict", [False, True])
def test_workbook_carrier_clarifies_saved_prose_rules_without_rewriting_profile(profile, strict):
    before = copy.deepcopy(profile)
    prompt = profile_system_prompt(profile, strict=strict, purpose="workbook_result")

    assert prompt.startswith(profile["prompt_text"])
    assert profile["skill_text"] in prompt
    assert _CARRIER_MARKER in prompt
    assert "относятся к комментарию для оператора" in prompt
    assert "обязательные поля строк" in prompt
    assert "Правило порядка строк относится только к терминальному результату после необходимых чтений" in prompt
    assert "не требует завершать ход вместо вызова доступного инструмента чтения" in prompt
    assert "Во всех допустимых форматах (JSON, Markdown, текст) сначала верни" in prompt
    assert "Если пользователь явно задал формат, сохрани его" in prompt
    assert "это уточнение не требует JSON" in prompt
    assert "coverage/open_gap соответствующих строк" in prompt
    assert profile == before


@pytest.mark.parametrize("purpose", ["query", "answer"])
def test_carrier_scope_does_not_change_other_estimator_phases(purpose):
    prompt = profile_system_prompt(_saved_profile(), strict=False, purpose=purpose)
    assert _CARRIER_MARKER not in prompt


def test_unrelated_profile_does_not_receive_the_workbook_carrier():
    prompt = profile_system_prompt(_saved_profile(mode="agent"), strict=False,
                                   purpose="workbook_result")
    assert _CARRIER_MARKER not in prompt


@pytest.mark.parametrize("requested_format", ["JSON", "Markdown", "текст"])
def test_carrier_preserves_explicit_format_literal_input_evidence_and_model_policy(requested_format):
    profile = _saved_profile()
    profile_bytes = json.dumps(profile, ensure_ascii=False).encode("utf-8")
    question = f"Собери документ. Формат ответа: {requested_format}."
    source = "Лист исходника!R7: Изделие Ω | шт. | 3\nУсловие из документа."
    evidence = "Q3.H2: Полная карточка нормы\nОбъём ресурса: 0,25 чел.-ч."
    original = [source, evidence]
    original_bytes = [value.encode("utf-8") for value in original]
    prefix = profile_system_prompt(profile, strict=False, purpose="workbook_result")
    messages, packet = govern_inference_messages(
        preset=ModelExecutionPreset("carrier", "fixture", 20000, 1000, 1000,
                                    1, 5, 6, 1, False, ("fixture",)),
        profile_prefix=prefix,
        request_payload=question,
        required_evidence=original,
    )

    assert _CARRIER_MARKER in prefix
    assert json.dumps(profile, ensure_ascii=False).encode("utf-8") == profile_bytes
    assert profile["model_policy"] == {"temperature": 0.7, "reasoning_enabled": False}
    assert [value.encode("utf-8") for value in original] == original_bytes
    delivered = [obj.payload for section in packet.sections
                 if section.kind == ContextKind.EVIDENCE for obj in section.objects]
    assert [value.encode("utf-8") for value in delivered] == original_bytes
    request = next(obj.payload for section in packet.sections
                   if section.kind == ContextKind.REQUEST for obj in section.objects)
    assert request == question
    assert not packet.omissions
    assert question in messages[-1]["content"]
    assert all(value in messages[-1]["content"] for value in original)
