import json

import pytest

from proxy.services import rim_agent_turn_service
from proxy.smeta_core.rim_session import RimSessionConflict, RimSessionStore


def test_rim_mapping_transport_keeps_all_vor_rows():
    rows = [
        {
            "work_id": f"w-{index:03d}",
            "work_name": f"Работа {index}",
            "unit": "шт.",
            "quantity": index,
        }
        for index in range(1, 71)
    ]

    result = rim_agent_turn_service._work_rows(rows)

    assert len(result) == 70
    assert result[-1]["work_id"] == "w-070"


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
            assert payload["session_context"]["rim_reference"]["sources"] == []
            assert payload["session_context"]["confirmed_session_facts"] == {}
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
                            "question_kind": "physical_installation",
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


def test_specification_intake_batches_all_rows_without_loss(tmp_path):
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

    seen_batches = []

    def exchange(messages, tools):
        payload = json.loads(messages[-1]["content"])
        tool_names = [tool["function"]["name"] for tool in tools]
        if tool_names == ["ask_user"]:
            return {
                "tool_calls": [
                    {
                        "function": {
                            "name": "ask_user",
                            "arguments": {
                                "question_kind": "physical_installation",
                                "text": "Как выполняется монтаж?",
                                "reason": "Условие влияет на норму",
                                "work_ids": ["source-001"],
                                "options": ["открыто", "скрыто"],
                            },
                        }
                    }
                ]
            }
        work_items = payload["session_context"]["intake"]["work_items"]
        seen_batches.append([item["work_id"] for item in work_items])
        return {
            "tool_calls": [
                {
                    "function": {
                        "name": "draft_work_schedule",
                        "arguments": {
                            "rows": [
                                {
                                    "work_id": item["work_id"],
                                    "section_name": "Монтаж",
                                    "work_name": f"Монтаж {item['title']}",
                                    "unit": item["unit"],
                                    "quantity": item["quantity"],
                                    "quantity_origin": "source_explicit",
                                    "source_ref": item["source_refs"][0],
                                }
                                for item in work_items
                            ]
                        },
                    }
                }
            ]
        }

    result = rim_agent_turn_service.run_rim_agent_turn(
        store,
        created.session["session_id"],
        owner_id="tester",
        user_message="Подготовь ВОР",
        exchange=exchange,
        mapping_exchange=lambda *_args: {},
    )

    assert seen_batches == [
        ["source-001", "source-002", "source-003", "source-004", "source-005"],
        ["source-006", "source-007"],
    ]
    vor = store.revision_payload(
        created.session["session_id"],
        result["vor_revision_id"],
        owner_id="tester",
    )
    assert len(vor["payload"]["rows"]) == 7


def test_single_action_returns_structured_validation_error_for_one_repair():
    session = {
        "session_id": "session-1",
        "phase": "vor",
        "mapping_status": "not_started",
        "pricing_status": "unpriced",
        "display_state": "awaiting_vor_approval",
        "head_revision_id": "revision-1",
        "pending_question_id": "",
    }
    calls = []

    def exchange(messages, tools):
        payload = json.loads(messages[-1]["content"])
        calls.append(payload)
        assert [tool["function"]["name"] for tool in tools] == ["draft_work_schedule"]
        if len(calls) == 1:
            return {
                "tool_calls": [
                    {
                        "function": {
                            "name": "draft_work_schedule",
                            "arguments": {"rows": [{"work_id": "vor-001"}]},
                        }
                    }
                ]
            }
        assert "arguments are invalid" in payload["rejected_tool_call"]["error"]
        return {
            "tool_calls": [
                {
                    "function": {
                        "name": "draft_work_schedule",
                        "arguments": {
                            "rows": [
                                {
                                    "work_id": "vor-001",
                                    "section_name": "Монтаж",
                                    "work_name": "Установка шкафа",
                                    "unit": "шт.",
                                    "quantity": 2,
                                    "quantity_origin": "source_explicit",
                                    "source_ref": (
                                        "Техническая часть сборника ФСНБ-2022, "
                                        "выдуманная моделью"
                                    ),
                                }
                            ]
                        },
                    }
                }
            ]
        }

    action, _message = rim_agent_turn_service._single_action(
        session=session,
        context={"instruction": "Revise the VOR."},
        user_message="Монтаж включён",
        exchange=exchange,
        only_actions={"draft_work_schedule"},
    )

    assert action["arguments"]["rows"][0]["work_name"] == "Установка шкафа"
    assert len(calls) == 2


def test_pending_vor_answer_creates_source_linked_work_revision(tmp_path):
    store = RimSessionStore(tmp_path)
    created = store.create_session(owner_id="tester")
    vor = store.save_vor_revision(
        created.session["session_id"],
        owner_id="tester",
        expected_parent_revision_id=created.revision_id,
        rows=[
            {
                "work_id": "vor-001",
                "section_name": "Оборудование СКС",
                "work_name": "Шкаф телекоммуникационный 42U",
                "unit": "шт.",
                "quantity": 2,
                "quantity_origin": "source_explicit",
                "source_ref": "СКС.xlsx#sheet=СКС;row=6",
            }
        ],
    )
    question = store.open_question(
        created.session["session_id"],
        owner_id="tester",
        expected_parent_revision_id=vor.revision_id,
        question={
            "text": "Включать монтаж оборудования в ВОР?",
            "reason": "Спецификация описывает поставку.",
            "work_ids": ["vor-001"],
            "options": [
                "Монтаж и подключение оборудования включены в ВОР",
                "Монтаж и подключение не включены, только поставка",
            ],
        },
    )
    calls = []

    def exchange(messages, tools):
        payload = json.loads(messages[-1]["content"])
        tool_names = [tool["function"]["name"] for tool in tools]
        calls.append(tool_names)
        if len(calls) == 1:
            assert tool_names == ["interpret_pending_answer"]
            return {
                "_les_model": "qwen3.5:9b",
                "tool_calls": [
                    {
                        "function": {
                            "name": "interpret_pending_answer",
                            "arguments": {
                                "answer": {
                                    "selected_option": (
                                        "Монтаж и подключение оборудования включены в ВОР"
                                    )
                                },
                                "needs_clarification": False,
                            },
                        }
                    }
                ],
            }
        assert tool_names == ["draft_work_schedule"]
        assert "technological work operations" in payload["session_context"]["instruction"]
        assert payload["session_context"]["current_vor_draft"]["rows"][0][
            "source_ref"
        ] == "СКС.xlsx#sheet=СКС;row=6"
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
                                    "section_name": "Монтаж оборудования СКС",
                                    "work_name": (
                                        "Сборка и установка напольного "
                                        "телекоммуникационного шкафа 42U"
                                    ),
                                    "unit": "шт.",
                                    "quantity": 2,
                                    "quantity_origin": "source_explicit",
                                    "source_ref": (
                                        "Техническая часть сборника ФСНБ-2022, "
                                        "выдуманная моделью"
                                    ),
                                }
                            ]
                        },
                    }
                }
            ],
        }

    result = rim_agent_turn_service.run_rim_agent_turn(
        store,
        created.session["session_id"],
        owner_id="tester",
        user_message="Монтаж и подключение оборудования включены в ВОР",
        exchange=exchange,
        mapping_exchange=lambda *_args: {},
    )

    assert result["answer_revision_id"] != question.revision_id
    assert result["vor_revision_id"] != vor.revision_id
    session = store.get_session(created.session["session_id"], owner_id="tester")
    assert session["pending_question_id"] == ""
    payload = store.revision_payload(
        created.session["session_id"],
        result["vor_revision_id"],
        owner_id="tester",
    )["payload"]
    assert payload["rows"][0]["work_name"].startswith("Сборка и установка")
    assert payload["rows"][0]["source_ref"] == "СКС.xlsx#sheet=СКС;row=6"
    assert payload["rows"][0]["source_refs"] == ["СКС.xlsx#sheet=СКС;row=6"]


def test_pending_region_answer_updates_session_without_rewriting_vor(tmp_path):
    store = RimSessionStore(tmp_path)
    created = store.create_session(
        owner_id="tester",
        region_code="test",
        price_period="test",
    )
    vor = store.save_vor_revision(
        created.session["session_id"],
        owner_id="tester",
        expected_parent_revision_id=created.revision_id,
        rows=[
            {
                "work_id": "vor-001",
                "section_name": "Оборудование СКС",
                "work_name": "Установка шкафа 42U",
                "unit": "шт.",
                "quantity": 2,
                "quantity_origin": "source_explicit",
                "source_ref": "СКС.xlsx#sheet=СКС;row=6",
            }
        ],
    )
    question = store.open_question(
        created.session["session_id"],
        owner_id="tester",
        expected_parent_revision_id=vor.revision_id,
        question={
            "question_kind": "project_condition",
            "text": "В каком регионе и квартале составляется смета?",
            "reason": "Это требуется для текущих цен.",
            "work_ids": ["vor-001"],
            "options": ["77, 2026-Q2", "78, 2026-Q2"],
        },
    )

    def exchange(_messages, tools):
        assert [tool["function"]["name"] for tool in tools] == [
            "interpret_pending_answer"
        ]
        return {
            "_les_model": "qwen3.5:9b",
            "tool_calls": [
                {
                    "function": {
                        "name": "interpret_pending_answer",
                        "arguments": {
                            "answer": {
                                "region_code": "77",
                                "price_period": "2026-Q2",
                            },
                            "needs_clarification": False,
                        },
                    }
                }
            ],
        }

    result = rim_agent_turn_service.run_rim_agent_turn(
        store,
        created.session["session_id"],
        owner_id="tester",
        user_message="77 (Москва), 2026-Q2",
        exchange=exchange,
        mapping_exchange=lambda *_args: {},
    )

    session = store.get_session(created.session["session_id"], owner_id="tester")
    assert result["revision_id"]
    assert session["current_vor_revision_id"] == vor.revision_id
    assert session["head_revision_id"] == result["revision_id"]
    assert session["region_code"] == "77"
    assert session["price_period"] == "2026-Q2"
    payload = store.revision_payload(
        created.session["session_id"],
        vor.revision_id,
        owner_id="tester",
    )["payload"]
    assert len(payload["rows"]) == 1


def test_vor_provenance_allows_model_split_only_with_parent_project_refs():
    previous = [
        {
            "work_id": "vor-001",
            "source_ref": "СКС.xlsx#sheet=СКС;row=6",
            "source_refs": ["СКС.xlsx#sheet=СКС;row=6"],
            "source_row": 6,
        }
    ]
    split = rim_agent_turn_service._preserve_project_source_provenance(
        previous,
        [
            {
                "work_id": "vor-001-install",
                "work_name": "Установка шкафа",
                "source_ref": "СКС.xlsx#sheet=СКС;row=6",
            },
            {
                "work_id": "vor-001-connect",
                "work_name": "Подключение шкафа",
                "source_refs": ["СКС.xlsx#sheet=СКС;row=6"],
            },
        ],
    )

    assert [row["source_row"] for row in split] == [6, 6]
    assert split[1]["source_ref"] == "СКС.xlsx#sheet=СКС;row=6"
    with pytest.raises(RimSessionConflict, match="project source refs"):
        rim_agent_turn_service._preserve_project_source_provenance(
            previous,
            [
                {
                    "work_id": "vor-001-install",
                    "work_name": "Установка шкафа",
                    "source_ref": "fsnb.sqlite#norm=10-01-001-01",
                }
            ],
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
            "professional_conflicts": [
                {
                    "conflict_id": "model-self-conflict",
                    "code": "technology_check_contradicts_bind",
                    "severity": "error",
                    "work_ids": ["vor-001"],
                    "claim": "Выбран bind при незакрытом технологическом конфликте.",
                    "evidence": {"norm_code": "ГЭСНм10-06-001-01"},
                }
            ],
            "catalog_trace": [{"family": "ГЭСНм", "selected_by": "model"}],
            "query_trace": [{"work_id": "vor-001", "queries": ["прокладка кабеля"]}],
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
                            "question_kind": "physical_installation",
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
    mapping_payload = store.revision_payload(
        vor.session["session_id"],
        result["mapping_revision_id"],
        owner_id="tester",
    )["payload"]
    mapping = mapping_payload["mapping_rows"]
    assert mapping[0]["norm_key"] == "ГЭСНм:10-06-001-01"
    assert mapping[0]["card_opened"] is True
    assert mapping[0]["norm_source_ref"] == "fsnb.sqlite#guid=1"
    assert mapping_payload["professional_conflicts"][0]["conflict_id"] == "model-self-conflict"
    assert mapping_payload["agent_audit"]["schema"] == "rim_norm_mapping_agent_audit_v1"
    assert mapping_payload["agent_audit"]["query_trace"][0]["work_id"] == "vor-001"


def test_mapping_turn_resumes_durable_checkpoint_and_clears_it_on_success(
    monkeypatch,
    tmp_path,
):
    store = RimSessionStore(tmp_path)
    vor = _create_vor(store)
    checkpoint_payload = {
        "resume_state": {
            "schema": "smeta_norm_agent_resume_v1",
            "next_turn": 3,
            "conversation": [{"role": "tool", "content": "family catalog"}],
        }
    }

    def interrupted(*_args, **kwargs):
        assert kwargs["resume_checkpoint"] is None
        assert kwargs["candidate_limit"] == 4
        kwargs["checkpoint"](checkpoint_payload)
        raise RuntimeError("simulated process interruption")

    monkeypatch.setattr(
        rim_agent_turn_service,
        "_run_batch_norm_agent",
        interrupted,
    )
    with pytest.raises(RuntimeError, match="simulated process interruption"):
        rim_agent_turn_service.run_rim_agent_turn(
            store,
            vor.session["session_id"],
            owner_id="tester",
            user_message="Подбери нормы",
            exchange=lambda *_args: {},
            mapping_exchange=lambda *_args: {},
        )

    saved = store.load_agent_checkpoint(
        vor.session["session_id"],
        owner_id="tester",
        checkpoint_kind="norm_mapping",
        base_revision_id=vor.revision_id,
    )
    assert saved["payload"] == checkpoint_payload

    def resumed(*_args, **kwargs):
        assert kwargs["resume_checkpoint"] == checkpoint_payload
        return {
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
                        "edition": "ФСНБ-2022",
                        "source_ref": "fsnb.sqlite#guid=1",
                        "questions_to_ask": [],
                    }
                ]
            },
            "agent_trace": {"tool_trajectory": []},
        }

    monkeypatch.setattr(
        rim_agent_turn_service,
        "_run_batch_norm_agent",
        resumed,
    )
    monkeypatch.setattr(
        rim_agent_turn_service,
        "_run_global_norm_review",
        lambda _rows, initial, *_args, **_kwargs: {
            **initial,
            "professional_conflicts": [],
        },
    )
    monkeypatch.setattr(
        rim_agent_turn_service.smeta_application,
        "calculate_visible_rows_revision",
        lambda *_args, **_kwargs: {
            "schema": "rim_lsr_trace_v1",
            "summary": {"known_amount": 1000.0},
            "sections": [],
            "blockers": [],
        },
    )
    result = rim_agent_turn_service.run_rim_agent_turn(
        store,
        vor.session["session_id"],
        owner_id="tester",
        user_message="Продолжи подбор",
        exchange=lambda *_args: {},
        mapping_exchange=lambda *_args: {},
    )

    assert result["resumed_from_checkpoint"] is True
    assert result["pricing_revision_id"]
    assert result["artifact"]["xlsx"].endswith("export?kind=draft")
    assert (
        store.load_agent_checkpoint(
            vor.session["session_id"],
            owner_id="tester",
            checkpoint_kind="norm_mapping",
            base_revision_id=vor.revision_id,
        )
        is None
    )


def test_rim_model_reference_is_phase_scoped_and_never_contains_numeric_rules():
    from proxy.services.rim_knowledge_service import model_reference_for_session

    mapping = model_reference_for_session(
        {
            "phase": "vor",
            "mapping_status": "mapping_selected",
            "pricing_status": "unpriced",
        }
    )
    pricing = model_reference_for_session(
        {
            "phase": "pricing",
            "mapping_status": "mapping_locked",
            "pricing_status": "priced_partial",
        }
    )

    assert {item["id"] for item in mapping["sources"]} == {
        "collection_technical_part_coefficients"
    }
    pricing_ids = {item["id"] for item in pricing["sources"]}
    assert {
        "fgis_split_form",
        "fsem_2022",
        "kac",
        "overhead",
        "estimated_profit",
    } <= pricing_ids
    assert all("value" not in item for item in pricing["sources"])
    assert pricing["role"] == "navigation_and_source_routing_only"
