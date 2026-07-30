from __future__ import annotations

from copy import deepcopy

from proxy.services.rim_mapping_progress_service import build_mapping_progress


def _vor_rows() -> list[dict[str, object]]:
    return [
        {
            "work_id": f"vor-{index:03d}",
            "work_name": title,
            "unit": "шт",
            "quantity": index,
            "source_ref": f"/tmp/СКС.xlsx#sheet=СКС;row={index + 5}",
        }
        for index, title in enumerate(
            [
                "Шкаф телекоммуникационный",
                "Патч-панель",
                "Организатор кабельный",
                "Блок розеток",
                "Шина заземления",
            ],
            1,
        )
    ]


def _checkpoint(*, validation_version: str) -> dict[str, object]:
    candidates = {
        f"vor-{index:03d}": {
            f"ГЭСНм10-06-00{index}-01": {
                "norm_key": f"ГЭСНм:10-06-00{index}-01",
                "norm_code": f"ГЭСНм10-06-00{index}-01",
                "title": f"Монтаж элемента {index}",
                "measure_unit": "1 шт.",
                "base_type": "ГЭСНм",
                "collection": "10",
                "source_ref": f"fsnb.sqlite#norm={index}",
            }
        }
        for index in range(1, 6)
    }
    opened = {
        work_id: {
            code: {
                **card,
                "edition": "ФСНБ-2022 изм. 14",
            }
            for code, card in cards.items()
        }
        for work_id, cards in candidates.items()
    }
    accepted = {
        "vor-001": {
            "norm_code": "",
            "review_status": "model_batch_unbound",
            "reason": "Открытые карточки не соответствуют поставке шкафа.",
        }
    }
    query_trace = [
        {
            "work_id": f"vor-{index:03d}",
            "queries": [f"монтаж элемента {index}"],
            "filters": {
                "base_types": ["ГЭСНм"],
                "collections": ["10"],
                "table_codes": [],
            },
        }
        for index in range(1, 6)
    ]
    return {
        "base_revision_id": "vor-revision",
        "updated_at": "2026-07-30T12:00:00+00:00",
        "payload": {
            "resume_state": {
                "validation_contract_version": validation_version,
                "tool_session": {
                    "candidates": candidates,
                    "opened": opened,
                    "accepted_rows": accepted,
                    "query_trace": query_trace,
                    "selected_collections": {
                        f"vor-{index:03d}": [["ГЭСНм", "10"]]
                        for index in range(1, 6)
                    },
                },
            }
        },
    }


def test_mapping_progress_exposes_all_five_durable_rows_and_readable_sources():
    checkpoint = _checkpoint(validation_version="grounded-unit-scoped-mapping-v11")

    result = build_mapping_progress(_vor_rows(), checkpoint)

    assert result["schema"] == "rim_mapping_progress_v1"
    assert result["active"] is True
    assert result["summary"] == {
        "total_rows": 5,
        "completed_rows": 1,
        "remaining_rows": 4,
        "needs_revalidation_rows": 0,
        "accepted_route_transitions": 0,
        "rejected_route_transitions": 0,
        "stage_counts": {
            "decision_accepted": 1,
            "cards_opened": 4,
        },
    }
    assert [row["candidate_count"] for row in result["rows"]] == [1, 1, 1, 1, 1]
    assert [row["opened_count"] for row in result["rows"]] == [1, 1, 1, 1, 1]
    assert result["rows"][0]["source_display"] == "СКС.xlsx · лист «СКС» · строка 6"
    assert (
        result["rows"][0]["opened_cards"][0]["source_display"]
        == "ФСНБ-2022 изм. 14 · ГЭСНм10-06-001-01"
    )
    assert result["rows"][0]["scopes"][0]["base_types"] == ["ГЭСНм"]
    assert result["rows"][0]["scopes"][0]["collections"] == ["10"]


def test_mapping_progress_marks_old_contract_decision_for_revalidation_without_mutation():
    checkpoint = _checkpoint(validation_version="grounded-terminal-unbound-v3")
    before = deepcopy(checkpoint)

    result = build_mapping_progress(_vor_rows(), checkpoint)

    assert result["requires_revalidation"] is True
    assert result["summary"]["completed_rows"] == 0
    assert result["summary"]["needs_revalidation_rows"] == 1
    assert result["rows"][0]["stage"] == "needs_revalidation"
    assert result["rows"][0]["decision"]["review_status"] == "model_batch_unbound"
    assert checkpoint == before


def test_mapping_progress_exposes_active_typed_route_success_and_rejected_attempt():
    checkpoint = _checkpoint(validation_version="grounded-unit-scoped-mapping-v11")
    resume = checkpoint["payload"]["resume_state"]
    tool_session = resume["tool_session"]
    tool_session["accepted_rows"] = {}
    tool_session["catalog_current_nodes"] = {
        "vor-001": "catalog:collection:ГЭСНм:10"
    }
    tool_session["catalog_node_registry"] = {
        "vor-001": {
            "catalog:family:ГЭСНм": {
                "node_id": "catalog:family:ГЭСНм",
                "parent_id": "catalog:root",
                "node_type": "family",
                "cipher": "ГЭСНм",
                "title": "Монтаж оборудования",
                "source_ref": "catalog.json#family=ГЭСНм",
            },
            "catalog:collection:ГЭСНм:10": {
                "node_id": "catalog:collection:ГЭСНм:10",
                "parent_id": "catalog:family:ГЭСНм",
                "node_type": "collection",
                "cipher": "10",
                "title": "Оборудование связи",
                "source_ref": "fsnb.sqlite#collection=10",
            },
        }
    }
    tool_session["catalog_trace"] = [
        {
            "trace_id": "route-family",
            "phase": "catalog_route",
            "turn": 1,
            "work_id": "vor-001",
            "outcome": "accepted",
            "decision": "continue",
            "selected_node_id": "catalog:family:ГЭСНм",
        },
        {
            "trace_id": "route-collection",
            "phase": "catalog_route",
            "turn": 2,
            "work_id": "vor-001",
            "outcome": "accepted",
            "decision": "continue",
            "selected_node_id": "catalog:collection:ГЭСНм:10",
        },
        {
            "trace_id": "route-section-rejected",
            "phase": "catalog_route",
            "turn": 3,
            "work_id": "vor-001",
            "outcome": "rejected",
            "decision": "rejected",
            "error": "selected node is also present in rejected_nodes",
        },
    ]
    resume["model_trace"] = [
        {
            "turn": 1,
            "model_wait_ms": 68620,
            "frame_profile": {
                "prompt_tokens": 1200,
                "cached_prompt_tokens": 900,
                "cache_hit_ratio": 0.75,
            },
        },
        {"turn": 2, "model_wait_ms": 59820},
        {"turn": 3, "model_wait_ms": 133490},
    ]

    result = build_mapping_progress(_vor_rows(), checkpoint)
    row = result["rows"][0]

    assert row["stage"] == "route_rejected"
    assert row["route_display"] == (
        "ГЭСНм · Монтаж оборудования → 10 · Оборудование связи"
    )
    assert row["route_timing_display"] == (
        "ГЭСНм · Монтаж оборудования (68.62 с) → "
        "10 · Оборудование связи (59.82 с)"
    )
    assert [item["trace_id"] for item in row["route_path"]] == [
        "route-family",
        "route-collection",
    ]
    assert [item["model_wait_seconds"] for item in row["route_path"]] == [
        68.62,
        59.82,
    ]
    assert row["route_path"][0]["frame_profile"]["cache_hit_ratio"] == 0.75
    assert row["route_events"][-1] == {
        "trace_id": "route-section-rejected",
        "outcome": "rejected",
        "decision": "rejected",
        "current_node_id": "",
        "selected_node_id": "",
        "model_wait_seconds": 133.49,
        "frame_profile": {},
        "error": "selected node is also present in rejected_nodes",
        "details": [],
    }
    assert result["summary"]["accepted_route_transitions"] == 2
    assert result["summary"]["rejected_route_transitions"] == 1
