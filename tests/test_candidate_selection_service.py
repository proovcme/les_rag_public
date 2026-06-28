from proxy.services.candidate_selection_service import (
    candidate_reason_labels,
    candidate_shortlist,
    select_candidates,
)


def test_select_candidates_clear_leader():
    candidates = [
        {"id": "A", "title": "first", "score_total": 8, "score_parts": {"unit": 1},
         "status": "accepted", "unit_compatible": True},
        {"id": "B", "title": "second", "score_total": 5.5, "score_parts": {"unit": 1},
         "status": "accepted", "unit_compatible": True},
    ]

    selection = select_candidates(candidates)

    assert selection["schema"] == "candidate_selection_v1"
    assert selection["action"] == "bind_top_candidate"
    assert selection["selected_code"] == "A"
    assert selection["score_gap"] == 2.5


def test_select_candidates_small_gap_returns_to_model():
    candidates = [
        {"id": "A", "title": "first", "score_total": 8, "score_parts": {"unit": 1},
         "status": "accepted", "unit_compatible": True},
        {"id": "B", "title": "second", "score_total": 7.2, "score_parts": {"unit": 1},
         "status": "accepted", "unit_compatible": True},
    ]

    selection = select_candidates(candidates)

    assert selection["status"] == "needs_model_choice"
    assert selection["action"] == "ask_model_to_choose_or_request_input"
    assert selection["selected_code"] == ""


def test_select_candidates_rejected_top_returns_to_model():
    candidates = [
        {"id": "A", "title": "first", "score_total": 8, "score_parts": {"unit": 1},
         "status": "rejected", "unit_compatible": True},
        {"id": "B", "title": "second", "score_total": 3, "score_parts": {"unit": 1},
         "status": "accepted", "unit_compatible": True},
    ]

    selection = select_candidates(candidates)

    assert selection["status"] == "needs_model_choice"
    assert selection["selected_code"] == ""
    assert selection["top_reasons"][0] == "кандидат отклонён фильтром применимости"


def test_candidate_shortlist_is_compact_and_labelled():
    labels = {"domain": ("домен совпал", "домен не совпал")}
    candidates = [
        {"id": "A", "name": "candidate", "unit": "м2", "score_total": "4,5",
         "score_parts": {"domain": 2, "noise": -1}, "status": "accepted"},
    ]

    short = candidate_shortlist(candidates, reason_labels=labels)

    assert short == [{
        "norm_code": "A",
        "title": "candidate",
        "measure_unit": "м2",
        "score_total": "4,5",
        "score_parts": {"domain": 2, "noise": -1},
        "applicability_status": "accepted",
        "unit_compatible": True,
        "reasons": [
            "применимость подтверждена",
            "домен совпал",
            "noise: отрицательный сигнал",
        ],
    }]


def test_candidate_reason_labels_limits_output():
    candidate = {
        "status": "accepted",
        "score_parts": {f"k{i}": i + 1 for i in range(10)},
    }

    assert len(candidate_reason_labels(candidate)) == 6
