"""The search-query call keeps the saved role but scopes its output to search."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.context_governor_service import ContextKind
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from proxy.services.prompt_registry_service import build_factory_mode_system_prompt


_PHASE_MARKER = "Технический этап составления поисковых запросов"
_FINAL_CITATION_RULE = "Правила ссылок [Источник N] относятся к последующему ответу оператору"
_ANSWER_CITATION_RULE = "Ссылки оформляй номерами из заголовков [Источник N]"
_PRICE_SCOPE_RULE = "Регион и период цен относятся к закреплённой книге цен, а не к параметрам нормы"
_PRICE_READ_RULE = "Цены нормативных ресурсов проверяй после чтения точной карточки"


def _snapshot(mode: str = "estimator", *, factory: bool = False) -> dict:
    if factory:
        prompt = build_factory_mode_system_prompt("rag")
        skill = (Path(__file__).resolve().parents[1] / "skills/smeta/references/rag-estimator.md").read_text(
            encoding="utf-8"
        ).strip()
    else:
        prompt = "Пиши живое вступление и итоговую таблицу. Без JSON, если JSON не просили."
        skill = "# Сохранённый skill\nВерни окончательный инженерный результат с обоснованиями."
    return {
        "mode": mode,
        "revision_id": "user:profile:query:retained",
        "prompt_text": prompt,
        "skill_text": skill,
        "tabular_estimator_path": mode != "estimator",
        "model_policy": {"temperature": 0.7, "reasoning_enabled": False,
                         "query_reasoning_enabled": False, "query_output_tokens": 8192},
    }


@pytest.mark.parametrize("mode", ["estimator", "agent", "engineer"])
@pytest.mark.parametrize("strict", [False, True])
def test_query_phase_preserves_literal_profile_and_skill_then_scopes_the_output(mode, strict):
    snapshot = _snapshot(mode)
    before = copy.deepcopy(snapshot)
    prompt = service.profile_system_prompt(snapshot, strict=strict, purpose="query")

    assert prompt.startswith(snapshot["prompt_text"])
    assert snapshot["skill_text"] in prompt
    assert _PHASE_MARKER in prompt
    assert prompt.index(_PHASE_MARKER) > prompt.index(snapshot["skill_text"])
    assert "правила вступления, итоговой таблицы и оформления готового документа" in prompt
    assert "относятся к последующему ответу оператору" in prompt
    assert "ограничения профиля на JSON относятся к ответу оператору" in prompt
    assert _FINAL_CITATION_RULE in prompt
    assert _ANSWER_CITATION_RULE not in prompt
    assert "Повторная попытка: сохрани полезный ответ" not in prompt
    assert "Контракт экспорта ВОР/ЛСР:" not in prompt
    assert snapshot == before


def test_factory_profile_conflicting_prose_rules_remain_literal_but_do_not_define_query_output():
    snapshot = _snapshot(factory=True)
    profile_bytes = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
    source = 'Лист Ω!R17: Изделие "A-5" | шт. | 3'
    question = "Собери документ по прикреплённому исходнику."
    prefix = service.profile_system_prompt(snapshot, strict=False, purpose="query")
    prefix += "\n\n" + service.model_rag_query_instruction(snapshot)
    messages, packet = service.govern_inference_messages(
        preset=ModelExecutionPreset("query-scope", "fixture", 30000, 8192, 1000,
                                    1, 5, 6, 1, False, ("fixture",)),
        profile_prefix=prefix,
        request_payload=question,
        required_evidence=[source],
    )

    assert snapshot["prompt_text"] in messages[0]["content"]
    assert snapshot["skill_text"] in messages[0]["content"]
    assert _PHASE_MARKER in messages[0]["content"]
    assert _FINAL_CITATION_RULE in messages[0]["content"]
    assert _ANSWER_CITATION_RULE not in messages[0]["content"]
    assert 'без внутренних служебных терминов и JSON' in snapshot["prompt_text"]
    assert 'Markdown-таблицы' in snapshot["prompt_text"]
    assert "Контракт экспорта ВОР/ЛСР:" not in messages[0]["content"]
    delivered = [obj.payload for section in packet.sections
                 if section.kind == ContextKind.EVIDENCE for obj in section.objects]
    assert delivered == [source]
    assert question in messages[-1]["content"]
    assert not packet.omissions
    assert json.dumps(snapshot, ensure_ascii=False).encode("utf-8") == profile_bytes


@pytest.mark.parametrize("purpose", ["answer", "workbook_result"])
def test_operator_result_keeps_its_citations_without_query_phase_override(purpose):
    prompt = service.profile_system_prompt(_snapshot(), strict=False, purpose=purpose)
    assert _ANSWER_CITATION_RULE in prompt
    assert _PHASE_MARKER not in prompt
    assert _FINAL_CITATION_RULE not in prompt


def test_primary_repair_and_continuation_offer_the_same_two_query_formats():
    snapshot = _snapshot()
    primary = service.model_rag_query_instruction(snapshot)
    repair = primary + "\n\n" + service._MODEL_RAG_QUERY_REPAIR_INSTRUCTION
    continuation = primary + "\n\n" + service.declared_query_continuation_instruction(
        ['Запрос с маркой "A-5" и размером 2,5'], "Незавершённый запрос Ω"
    )
    for prompt in (primary, repair, continuation):
        assert "JSON-конверт" in prompt
        assert "дословные строки запросов" in prompt
        assert "Не смешивай эти оформления" in prompt
        assert "каждый с новой строки" not in prompt
    assert "JSON-конверт" in service._MODEL_RAG_QUERY_REPAIR_INSTRUCTION
    assert "дословные строки запросов" in service._MODEL_RAG_QUERY_REPAIR_INSTRUCTION
    assert "JSON-конверт" in service.declared_query_continuation_instruction([], "Хвост Ω")
    assert "дословные строки запросов" in service.declared_query_continuation_instruction([], "Хвост Ω")
    assert 'Запрос с маркой "A-5" и размером 2,5' in continuation
    assert "Незавершённый запрос Ω" in continuation


def test_sheet_query_uses_the_same_contract_before_any_candidate_retrieval():
    snapshot = _snapshot()
    primary = service.model_rag_query_instruction(snapshot)
    sheet = service.sheet_pass_query_instruction(snapshot, sheet="Лист Ω", sheet_index=2, sheet_count=4)
    assert sheet.startswith(primary)
    assert "JSON-конверт" in sheet and "дословные строки запросов" in sheet
    assert "системные поисковые запросы" not in sheet
    assert "Код исполнит возвращённые тобой поисковые запросы дословно" in sheet


@pytest.mark.parametrize("factory", [False, True])
@pytest.mark.parametrize("sheet", [False, True])
def test_query_pricing_scope_is_common_to_primary_repair_and_continuation_without_profile_rewrite(factory, sheet):
    snapshot = _snapshot(factory=factory)
    before = copy.deepcopy(snapshot)
    query = (service.sheet_pass_query_instruction(snapshot, sheet="Лист Ω", sheet_index=1, sheet_count=2)
             if sheet else service.model_rag_query_instruction(snapshot))
    prefix = service.profile_system_prompt(snapshot, strict=False, purpose="query")
    literal = 'Нормативный ресурс Ω, редакция ФСНБ из исходника; условия работы'
    for tail in ("", service._MODEL_RAG_QUERY_REPAIR_INSTRUCTION,
                 service.declared_query_continuation_instruction([literal], "Хвост Ω")):
        delivered = prefix + "\n\n" + query + "\n\n" + tail
        assert _PRICE_SCOPE_RULE in delivered
        assert "реальную редакцию ФСНБ и условия работы сохраняй" in delivered
        assert _PRICE_READ_RULE in delivered
        assert "штатными инструментами чтения цен" in delivered
        assert "коммерческие предложения" in delivered and "target=documents" in delivered
        assert "в ответном этапе" in delivered and "read_source" in delivered
        assert "запрос называет нужную работу или ресурс исходника" in delivered
        assert snapshot["prompt_text"] in delivered and snapshot["skill_text"] in delivered
    assert literal in tail
    assert snapshot == before


@pytest.mark.asyncio
async def test_actual_baseline_and_candidate_use_identical_query_scope_and_repair(tmp_path, monkeypatch):
    from tests.test_model_rag_sheet_evidence_reads import _run_sheet

    scopes = {}
    common_contract = service.model_rag_query_instruction({"mode": "estimator"})
    for variant in ["B0_DIRECT", "B1_CANDIDATE"]:
        variant_dir = tmp_path / variant
        variant_dir.mkdir()
        with monkeypatch.context() as variant_patch:
            run = await _run_sheet(variant_dir, variant_patch, reads=True, variant=variant,
                                   query_repair=True, temperature=0.65, query_reasoning_enabled=False)
        assert not run.responses and len(run.requests) == 5 and len(run.executions) == 1
        assert [query for query in run.queries if query in run.declared_queries] == run.declared_queries
        query_requests = run.requests[:2]
        scopes[variant] = []
        for request in query_requests:
            # Check the whole admitted request, not only its system prefix:
            # application source facts used to request result operations in
            # this search-only phase of B1 (including the repair).
            delivered = json.dumps(request.messages, ensure_ascii=False)
            assert "Верни операции requested_source_rows" not in delivered
            system = next(message["content"] for message in request.messages if message["role"] == "system")
            assert _PHASE_MARKER in system
            assert service._MODEL_RAG_QUERY_FORMAT_CONTRACT in system
            assert _FINAL_CITATION_RULE in system
            assert _ANSWER_CITATION_RULE not in system
            assert service.model_lsr_result_field_instruction() not in system
            assert request.temperature == 0.65
            assert request.reasoning_enabled is False
            assert system.count(_PHASE_MARKER) == 1
            assert common_contract in system
            assert _PRICE_SCOPE_RULE in system
            assert _PRICE_READ_RULE in system
            assert "реальную редакцию ФСНБ и условия работы сохраняй" in system
            # The candidate legitimately names its current sheet/packet. The
            # technical phase, format and repair contract must remain common.
            phase_start = system.index(_PHASE_MARKER)
            phase = system[phase_start:phase_start + len(service._MODEL_RAG_QUERY_PHASE_INSTRUCTION)]
            assert phase == service._MODEL_RAG_QUERY_PHASE_INSTRUCTION
            scopes[variant].append((phase, common_contract,
                                    service._MODEL_RAG_QUERY_REPAIR_INSTRUCTION in system))
    assert scopes["B0_DIRECT"] == scopes["B1_CANDIDATE"]


@pytest.mark.parametrize("count", [1, 75, 318])
@pytest.mark.parametrize("envelope", [False, True])
def test_both_declared_formats_preserve_every_model_authored_query(count, envelope):
    queries = [f'Поиск изделия Ω-{i}: размер 2,5; марка "A-{i}"' for i in range(count)]
    commentary = "Пояснение для оператора, которое не исполняется как поиск."
    raw = (json.dumps({"artifact_kind": "lsr", "queries": queries, "commentary": commentary},
                      ensure_ascii=False) if envelope else "\n".join(queries))
    declared = service.read_model_query_response(raw, finish_reason="stop")
    assert [query.text for query in declared["queries"]] == queries
    assert not declared["answer_cut"]
    assert not declared["accompanying_answer"]
    if envelope:
        assert declared["commentary"] == commentary
        assert declared["artifact_kind_declaration"]["artifact_kind"] == "lsr"
