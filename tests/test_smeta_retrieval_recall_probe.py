import json
from pathlib import Path

from tools.smeta_retrieval_recall_probe import evaluate_case, summarize_results


def test_evaluate_case_reports_rank_and_hit():
    result = evaluate_case(
        query="монтаж шкафа",
        expected_code="ГЭСНм10-04-087-05",
        candidate_codes=[
            "ГЭСНм10-04-087-06",
            "ГЭСНм10-04-087-05",
        ],
        elapsed_seconds=0.125,
    )

    assert result == {
        "query": "монтаж шкафа",
        "expected_code": "ГЭСНм10-04-087-05",
        "hit": True,
        "rank": 2,
        "candidate_codes": [
            "ГЭСНм10-04-087-06",
            "ГЭСНм10-04-087-05",
        ],
        "elapsed_seconds": 0.125,
    }


def test_evaluate_case_normalizes_typed_code_spelling():
    result = evaluate_case(
        query="устройство обрешетки",
        expected_code="ГЭСН 12-01-034-02",
        candidate_codes=["ГЭСН:12-01-034-02"],
        elapsed_seconds=0.0,
    )

    assert result["hit"] is True
    assert result["rank"] == 1


def test_summary_separates_strict_ground_truth_from_ambiguous_stress_cases():
    summary = summarize_results([
        {"assessment": "strict", "hit": True},
        {"assessment": "strict", "hit": False},
        {"assessment": "stress", "hit": False},
    ], total_elapsed_seconds=0.75)

    assert summary == {
        "strict_hits": 1,
        "strict_misses": 1,
        "strict_recall_at_k": 0.5,
        "stress_expected_code_visible": 0,
        "stress_cases": 1,
        "total_elapsed_seconds": 0.75,
    }


def test_active_smeta_base_uses_the_packaged_windows_embedding_space():
    config = json.loads(
        Path("config/domain/smeta_base_active.json").read_text(encoding="utf-8")
    )

    assert config["rag_embedding_model"] == "bge-m3"
