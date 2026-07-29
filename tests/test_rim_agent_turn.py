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

