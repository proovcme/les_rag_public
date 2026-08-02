from __future__ import annotations

from proxy.smeta_core.document_workflow import (
    SmetaNormToolSession,
    _resolve_bounded_catalog_query,
    _resolve_selected_node_id,
    bounded_catalog_query_from_work_features,
)


def test_bounded_catalog_query_from_work_features_caps_at_12_tokens():
    query = bounded_catalog_query_from_work_features({
        "operation": "установка и закрепление шкафа СКС в стойку на пол",
        "equipment": "шкаф телекоммуникационный напольный 42U",
        "system": "система структурированной кабельной сети СКС",
    })
    tokens = query.split()
    assert 2 <= len(tokens) <= 12
    assert "шкаф" in query.casefold() or "установка" in query.casefold()


def test_resolve_prefers_model_query_then_derives():
    features = {
        "operation": "монтаж шкафа",
        "equipment": "шкаф 42U",
        "system": "СКС",
    }
    assert _resolve_bounded_catalog_query("монтаж напольного шкафа СКС", features) == (
        "монтаж напольного шкафа СКС",
        "model",
    )
    derived, source = _resolve_bounded_catalog_query("", features)
    assert source == "derived_from_work_features"
    assert 2 <= len(derived.split()) <= 12


def test_resolve_selected_node_id_from_evidence_when_transport_drops_field():
    visible = {"catalog:collection:ГЭСНм:37", "catalog:collection:ГЭСНм:08"}
    evidence = [{
        "source_node_id": "catalog:collection:ГЭСНм:37",
        "field": "typical_scope",
        "claim": "сборник 37",
    }]
    assert _resolve_selected_node_id(
        "catalog:collection:ГЭСНм:37",
        evidence,
        visible,
    ) == ("catalog:collection:ГЭСНм:37", "model")
    assert _resolve_selected_node_id("", evidence, visible) == (
        "catalog:collection:ГЭСНм:37",
        "derived_from_evidence",
    )
    assert _resolve_selected_node_id("", [], visible) == ("", "")


def test_catalog_reject_streak_soft_stops_after_three_identical_errors():
    session = SmetaNormToolSession(
        [{"work_id": "w1", "title": "Шкаф", "unit": "шт", "quantity": 1}],
        candidate_limit=4,
        require_scoped_search=True,
    )
    # Exercise failure() through a stale current_node path three times.
    result = None
    for _ in range(3):
        result = session._catalog_transition(
            {
                "items": [{
                    "work_id": "w1",
                    "decision": "continue",
                    "current_node_id": "catalog:invented",
                    "confidence": "high",
                    "selected_node_id": "x",
                    "evidence": [],
                }],
            },
            turn=1,
        )
    assert result is not None
    assert result.get("catalog_stalled") is True
    assert "catalog stalled after 3 identical" in str(result.get("error") or "")
    assert session.catalog_stall is not None
    assert int(session.catalog_stall.get("reject_streak") or 0) == 3
