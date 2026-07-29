import json

import pytest

from proxy.services import rim_agent_turn_service
from proxy.smeta_core.rim_session import RimSessionStore


def _create_vor(store):
    created = store.create_session(owner_id="tester")
    return store.save_vor_revision(
        created.session["session_id"],
        owner_id="tester",
        expected_parent_revision_id=created.revision_id,
        rows=[
            {
                "work_id": "vor-001",
                "section_name": "СКС",
                "work_name": "Прокладка кабеля",
                "unit": "м",
                "quantity": 400,
                "source_ref": "spec.xlsx#row=14",
            }
        ],
    )


def test_specification_turn_reads_nested_intake_and_opens_question(monkeypatch, tmp_path):
    store = RimSessionStore(tmp_path)
    created = store.create_session(owner_id="tester")
    intake = store.save_intake(
        created.session["session_id"],
        owner_id="tester",
        expected_parent_revision_id=created.revision_id,
        source_kind="specification",
        intake={
            "work_item_count": 1,
            "work_items": [
                {
                    "work_id": "source-001",
                    "title": "Кабель U/UTP Cat.5e, бухта 305 м",
                    "unit": "шт.",
                    "quantity": 120,
                    "section": "Оборудование",
                    "source_refs": ["СКС.xlsx#sheet=СКС;row=17"],
                }
            ],
            "issues": [],
        },
    )
    calls = []

    def exchange(messages, tools):
        payload = json.loads(messages[-1]["content"])
        tool_names = [tool["function"]["name"] for tool in tools]
        calls.append((payload, tool_names))
        if len(calls) == 1:
            assert payload["session_context"]["intake"]["work_item_count"] == 1
            assert payload["session_context"]["intake"]["work_items"][0]["title"].startswith(
                "Кабель U/UTP"
            )
            instruction = payload["session_context"]["instruction"]
            assert "Every uploaded source row is in scope by default" in instruction
            assert "norm-search strategy belongs to the model" in instruction
            assert tool_names == ["draft_work_schedule"]
            return {
                "_les_model": "qwen3.5:9b",
                "tool_calls": [
                    {
                        "function": {
                            "name": "draft_work_schedule",
                            "arguments": {
                                "rows": [
                                    {
                                        "work_id": "vor-001",
                                        "section_name": "Кабельные линии",
                                        "work_name": "Прокладка кабеля U/UTP Cat.5e",
                                        "unit": "м",
                                        "quantity": 36600,
                                        "quantity_origin": "source_calculated",
                                        "quantity_formula": "120 × 305 м",
                                        "source_ref": "СКС.xlsx#sheet=СКС;row=17",
                                    }
                                ]
                            },
                        }
                    }
                ],
            }
        assert tool_names == ["ask_user"]
        return {
            "_les_model": "qwen3.5:9b",
            "tool_calls": [
                {
                    "function": {
                        "name": "ask_user",
                        "arguments": {
                            "text": "Как проложен кабель?",
                            "reason": "Способ прокладки влияет на норму.",
                            "work_ids": ["vor-001"],
                            "options": ["в лотке", "в трубе", "открыто"],
                        },
                    }
                }
            ],
        }

    result = rim_agent_turn_service.run_rim_agent_turn(
        store,
        created.session["session_id"],
        owner_id="tester",
        user_message="Подготовь ВОР",
        exchange=exchange,
        mapping_exchange=lambda *_args: {},
    )

    assert result["vor_revision_id"]
    assert result["message"] == "Как проложен кабель?"
    session = store.get_session(created.session["session_id"], owner_id="tester")
    assert session["current_vor_revision_id"] == result["vor_revision_id"]
    assert session["pending_question"]["options"] == ["в лотке", "в трубе", "открыто"]


def test_specification_intake_batch_is_bounded_to_five_rows(tmp_path):
    store = RimSessionStore(tmp_path)
    created = store.create_session(owner_id="tester")
    store.save_intake(
        created.session["session_id"],
        owner_id="tester",
        expected_parent_revision_id=created.revision_id,
        source_kind="specification",
        intake={
            "work_items": [
                {
                    "work_id": f"source-{index:03d}",
                    "title": f"Позиция {index}",
                    "unit": "шт.",
                    "quantity": 1,
                    "source_refs": [f"spec.xlsx#row={index}"],
                }
                for index in range(1, 8)
            ],
            "issues": [],
        },
    )

    def exchange(messages, _tools):
        payload = json.loads(messages[-1]["content"])
        work_items = payload["session_context"]["intake"]["work_items"]
        assert [item["work_id"] for item in work_items] == [
            "source-001",
            "source-002",
            "source-003",
            "source-004",
            "source-005",
        ]
        assert payload["session_context"]["intake"]["remaining_work_item_count"] == 2
        raise RuntimeError("transport boundary verified")

    with pytest.raises(RuntimeError, match="transport boundary verified"):
        rim_agent_turn_service.run_rim_agent_turn(
            store,
            created.session["session_id"],
            owner_id="tester",
            user_message="Подготовь ВОР",
            exchange=exchange,
            mapping_exchange=lambda *_args: {},
        )


def test_agent_turn_persists_typed_mapping_and_asks_rag_hint(monkeypatch, tmp_path):
    store = RimSessionStore(tmp_path)
    vor = _create_vor(store)

    monkeypatch.setattr(
        rim_agent_turn_service,
        "_run_batch_norm_agent",
        lambda *_args, **kwargs: {
            "selections": {
                "vor-001": {
                    "norm_code": "ГЭСНм10-06-001-01",
                    "selection_kind": "exact",
                    "applicability": "exact",
                    "reason": "Состав работ совпадает",
                    "technology_check": {"conclusion": "applicable"},
                }
            },
            "browse_trace": {
                "vor-001": [
                    {
                        "candidates": [
                            {
                                "norm_code": "ГЭСНм10-06-001-01",
                                "norm_key": "ГЭСНм:10-06-001-01",
                                "title": "Прокладка кабеля",
                                "measure_unit": "100 м",
                                "source_ref": "fsnb.sqlite#guid=1",
                            }
                        ]
                    }
                ]
            },
            "opened_cards": {
                "vor-001": [
                    {
                        "norm_code": "ГЭСНм10-06-001-01",
                        "norm_key": "ГЭСНм:10-06-001-01",
                        "title": "Прокладка кабеля",
                        "measure_unit": "100 м",
                        "edition": "ФСНБ-2022 изм. 14",
                        "source_ref": "fsnb.sqlite#guid=1",
                        "questions_to_ask": ["Уточнить способ прокладки кабеля"],
                    }
                ]
            },
            "agent_trace": {
                "tool_trajectory": [
                    {"tool": "browse_norm_catalog"},
                    {"tool": "search_norms_batch"},
                    {"tool": "read_norms_batch"},
                    {"tool": "submit_lsr_mapping"},
                ]
            },
        },
    )

    def exchange(_messages, tools):
        assert [tool["function"]["name"] for tool in tools] == ["ask_user"]
        return {
            "_les_model": "qwen3.5:9b",
            "content": "Уточняю условие применения нормы.",
            "tool_calls": [
                {
                    "function": {
                        "name": "ask_user",
                        "arguments": {
                            "text": "Для 400 м кабеля способ прокладки не указан. Как он проложен?",
                            "reason": "От способа зависит состав работ нормы.",
                            "work_ids": ["vor-001"],
                            "options": ["в лотке", "в трубе", "открыто", "пока неизвестно"],
                        },
                    }
                }
            ],
        }

    result = rim_agent_turn_service.run_rim_agent_turn(
        store,
        vor.session["session_id"],
        owner_id="tester",
        user_message="Подбери нормы",
        exchange=exchange,
        mapping_exchange=lambda *_args: {},
    )
    assert result["status"] == "awaiting_mapping_decisions"
    assert result["mapping_revision_id"]
    session = store.get_session(vor.session["session_id"], owner_id="tester")
    assert session["pending_question_id"]
    mapping = store.revision_payload(
        vor.session["session_id"],
        result["mapping_revision_id"],
        owner_id="tester",
    )["payload"]["mapping_rows"]
    assert mapping[0]["norm_key"] == "ГЭСНм:10-06-001-01"
    assert mapping[0]["card_opened"] is True
    assert mapping[0]["norm_source_ref"] == "fsnb.sqlite#guid=1"
