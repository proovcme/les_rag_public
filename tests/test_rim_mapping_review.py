from proxy.services.rim_mapping_review_service import review_mapping


def test_global_review_flags_without_changing_mapping():
    works = [
        {"work_id": "w1", "unit": "м"},
        {"work_id": "w2", "unit": "м"},
    ]
    mapping = [
        {
            "mapping_row_id": "m1",
            "work_id": "w1",
            "norm_key": "ГЭСНм:10-01-001-01",
            "norm_unit": "100 м",
            "selection_status": "selected",
            "selection_kind": "direct",
            "card_opened": True,
        },
        {
            "mapping_row_id": "m2",
            "work_id": "w2",
            "norm_key": "ГЭСНм:10-01-001-01",
            "norm_unit": "100 м",
            "selection_status": "selected",
            "selection_kind": "direct",
            "card_opened": False,
        },
    ]
    original = [dict(row) for row in mapping]
    conflicts = review_mapping(works, mapping)
    assert {item["code"] for item in conflicts} == {
        "selected_norm_card_not_opened",
        "possible_duplicate_norm_binding",
    }
    assert mapping == original

