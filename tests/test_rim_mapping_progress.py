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
    checkpoint = _checkpoint(validation_version="grounded-unit-scoped-mapping-v9")

    result = build_mapping_progress(_vor_rows(), checkpoint)

    assert result["schema"] == "rim_mapping_progress_v1"
    assert result["active"] is True
    assert result["summary"] == {
        "total_rows": 5,
        "completed_rows": 1,
        "remaining_rows": 4,
        "needs_revalidation_rows": 0,
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
