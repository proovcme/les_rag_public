from proxy.services.active_state_service import ActiveState
from proxy.services.scoped_rag_builder import build_scoped_evidence_packet
from proxy.services.skill_snippet_registry import select_skill_snippets


def _types(packet):
    return [sec["type"] for sec in packet.to_dict()["sections"]]


def test_scoped_rag_returns_typed_sections():
    snippets = select_skill_snippets("smeta", user_input="Сделай ВОР из спецификации")
    packet = build_scoped_evidence_packet(
        module_id="smeta",
        turn_type="new_task",
        user_input="Сделай ВОР из спецификации",
        active_state=ActiveState(module_id="smeta", task="СКС"),
        source_facts=[{"file": "spec.xlsx", "fact": "кабель 100 м"}],
        table_rows=[{"row": 1, "item": "кабель"}],
        skill_snippets=snippets,
        gaps=["нет трассировки"],
    )
    assert _types(packet) == [
        "active_state",
        "user_input",
        "source_facts",
        "table_rows",
        "skill_snippets",
        "gaps",
    ]
    rendered = packet.render_for_model()
    assert "[ACTIVE_STATE]" in rendered
    assert "[TABLE_ROWS]" in rendered
    assert "[SKILL_SNIPPET]" in rendered


def test_example_pattern_not_treated_as_source_fact():
    packet = build_scoped_evidence_packet(
        module_id="general_project_rag",
        turn_type="new_task",
        user_input="Покажи похожий паттерн",
        example_patterns=[{"pattern": "типовой ответ"}],
    )
    assert "source_facts" not in _types(packet)
    assert "example_patterns" in _types(packet)


def test_price_lookup_packet_uses_lookup_records_not_semantic_chunks():
    packet = build_scoped_evidence_packet(
        module_id="smeta",
        turn_type="price_lookup",
        user_input="Цена 91.05.01-017",
        lookup_records=[{"code": "91.05.01-017", "price": 1048.03}],
    )
    assert "lookup_records" in _types(packet)
    assert "source_facts" not in _types(packet)
