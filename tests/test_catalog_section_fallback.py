import pytest
from proxy.smeta_core import document_workflow


def test_section_transition_reuses_saved_work_features(monkeypatch):
    monkeypatch.setattr(
        document_workflow,
        "rank_norm_catalog_collections",
        lambda query, **_kwargs: {
            "cards": [{
                "key": "10",
                "node_id": "catalog:collection:ГЭСНм:10",
                "parent_id": "catalog:family:ГЭСНм",
                "node_type": "collection",
                "cipher": "10",
                "collection": "10",
                "navigation_kind": "collection",
                "title": "Оборудование связи",
                "official_name": "Оборудование связи",
                "purpose": "Оборудование связи",
            }],
            "retrieval_trace": {
                "rerank_status": "ok",
                "reranked": True,
            },
        },
    )

    monkeypatch.setattr(
        document_workflow,
        "rank_norm_catalog_tables",
        lambda query, **_kwargs: {
            "cards": [{
                "key": "10-01-001",
                "node_id": "catalog:table:ГЭСНм:10-01-001",
                "parent_id": "catalog:section:ГЭСНм:10-01",
                "node_type": "table",
                "cipher": "10-01-001",
                "navigation_kind": "table",
                "title": "Оборудование станции",
                "official_name": "Оборудование станции",
                "purpose": "Оборудование станции",
            }],
            "retrieval_trace": {
                "rerank_status": "ok",
            },
        },
    )

    session = document_workflow.SmetaNormToolSession(
        [{"work_id": "vor-001", "title": "Монтаж шкафа СКС", "unit": "шт", "quantity": 1}],
        candidate_limit=5,
        require_scoped_search=True,
    )

    family_node = {
        "node_id": "catalog:family:ГЭСНм",
        "parent_id": "catalog:root",
        "node_type": "family",
        "cipher": "ГЭСНм",
        "title": "ГЭСНм Монтаж оборудования",
        "official_heading": "ГЭСНм Монтаж оборудования",
    }
    collection_node = {
        "node_id": "catalog:collection:ГЭСНм:10",
        "parent_id": "catalog:family:ГЭСНм",
        "node_type": "collection",
        "cipher": "10",
        "title": "Оборудование связи",
        "official_name": "Оборудование связи",
    }
    section_node = {
        "node_id": "catalog:section:ГЭСНм:10-01",
        "parent_id": "catalog:collection:ГЭСНм:10",
        "node_type": "section",
        "cipher": "10-01",
        "title": "Станции телефонные",
        "official_name": "Станции телефонные",
    }

    session.catalog_menus["vor-001"]["catalog:root"] = [family_node]
    session.catalog_menus["vor-001"]["catalog:family:ГЭСНм"] = [collection_node]
    session.catalog_menus["vor-001"]["catalog:collection:ГЭСНм:10"] = [section_node]

    session.catalog_node_registry["vor-001"]["catalog:family:ГЭСНм"] = family_node
    session.catalog_node_registry["vor-001"]["catalog:collection:ГЭСНм:10"] = collection_node
    session.catalog_node_registry["vor-001"]["catalog:section:ГЭСНм:10-01"] = section_node

    # 1. Family transition with work_features provided
    family_res = session.execute(
        "continue_norm_catalog",
        {
            "items": [{
                "work_id": "vor-001",
                "current_node_id": "catalog:root",
                "selected_node_id": "catalog:family:ГЭСНм",
                "confidence": "high",
                "work_features": {
                    "domain": "электросвязь",
                    "system": "СКС",
                    "equipment": "шкаф",
                    "operation": "монтаж",
                    "assembly_state": "site_assembled",
                    "installation_context": "помещение",
                },
                "evidence": [{
                    "source_node_id": "catalog:family:ГЭСНм",
                    "field": "official_heading",
                    "claim": "ГЭСНм Монтаж оборудования",
                }],
            }]
        },
        turn=1,
    )
    assert family_res["rows"][0]["ok"] is True, family_res["rows"][0]
    assert "vor-001" in session.selected_base_types

    # 2. Collection transition
    coll_res = session.execute(
        "continue_norm_catalog",
        {
            "items": [{
                "work_id": "vor-001",
                "current_node_id": "catalog:family:ГЭСНм",
                "selected_node_id": "catalog:collection:ГЭСНм:10",
                "confidence": "high",
                "evidence": [{
                    "source_node_id": "catalog:collection:ГЭСНм:10",
                    "field": "official_name",
                    "claim": "Оборудование связи",
                }],
            }]
        },
        turn=2,
    )
    assert coll_res["rows"][0]["ok"] is True, coll_res["rows"][0]

    # 3. Section transition WITHOUT duplicating work_features or catalog_query
    sec_res = session.execute(
        "continue_norm_catalog",
        {
            "items": [{
                "work_id": "vor-001",
                "current_node_id": "catalog:collection:ГЭСНм:10",
                "selected_node_id": "catalog:section:ГЭСНм:10-01",
                "confidence": "high",
                "evidence": [{
                    "source_node_id": "catalog:section:ГЭСНм:10-01",
                    "field": "official_name",
                    "claim": "Станции телефонные",
                }],
            }]
        },
        turn=3,
    )
    assert sec_res["rows"][0]["ok"] is True, sec_res["rows"][0]
    assert sec_res["rows"][0]["items"][0]["node_id"] == "catalog:table:ГЭСНм:10-01-001"
